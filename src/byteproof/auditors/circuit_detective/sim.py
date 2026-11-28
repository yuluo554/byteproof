"""三值 unit-delay 仿真核（照搬旧仓 ``sim.mjs``）。纯整数运算；输入取上一 tick 的值；
组合环成员恒为 X。本模块不读时钟、不读随机数、不做任何渲染。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .netlist import gate_arity, gate_map, topo_order, validate_netlist
from .spec import X


def _apply_gate(gate_type: str, values: List[int]) -> int:
    if gate_type == "NOT":
        v = values[0]
        if v == X:
            return X
        return 0 if v == 1 else 1
    if gate_type == "AND":
        saw_x = False
        for v in values:
            if v == 0:
                return 0
            if v == X:
                saw_x = True
        return X if saw_x else 1
    if gate_type == "OR":
        saw_x = False
        for v in values:
            if v == 1:
                return 1
            if v == X:
                saw_x = True
        return X if saw_x else 0
    return X


def _read_input_vector(inputs, input_vector) -> Dict[str, int]:
    result: Dict[str, int] = {}
    if isinstance(input_vector, list):
        for index, name in enumerate(inputs):
            raw = input_vector[index] if index < len(input_vector) else None
            result[name] = raw if raw in (0, 1) else X
        return result
    if isinstance(input_vector, dict):
        for name in inputs:
            raw = input_vector.get(name)
            result[name] = raw if raw in (0, 1) else X
    return result


def _read_outputs(netlist, gate_values: Dict[str, int], input_values: Dict[str, int]) -> Dict[str, int]:
    outputs = {}
    for name in netlist["outputs"]:
        src = netlist["outputsMap"][name]
        if src in input_values:
            outputs[name] = input_values[src]
        else:
            outputs[name] = gate_values.get(src, X)
    return outputs


def simulate(netlist: dict, input_vector, options: Optional[dict] = None) -> dict:
    """求值一个网表（unit-delay 迭代至稳定；环成员恒 X；超限按全 X 处理）。"""
    options = options or {}
    ok, errors = validate_netlist(netlist)
    if not ok:
        return {
            "ok": False,
            "errors": errors,
            "outputs": {},
            "gates": {},
            "stable": False,
            "ticks": 0,
            "trace": [],
            "diagnostics": ["网表不合法"],
        }

    values = _read_input_vector(netlist["inputs"], input_vector)
    order, cyclic = topo_order(netlist)
    gate_by_id = gate_map(netlist)
    limit = options.get("maxTicks", len(netlist["gates"]) + 1)
    record_trace = options.get("recordTrace", True)
    trace: List[dict] = []

    prev: Dict[str, int] = {gate["id"]: X for gate in netlist["gates"]}
    current = dict(prev)
    outputs = _read_outputs(netlist, current, values)
    stable = False
    ticks = 0
    diagnostics: List[str] = []

    if cyclic:
        diagnostics.append("组合环 %s 恒为 X" % ",".join(cyclic))

    for tick in range(limit):
        ticks = tick + 1
        nxt: Dict[str, int] = {}
        for gate_id in order:
            gate = gate_by_id[gate_id]
            arity = gate_arity(gate["type"])
            args = []
            for i in range(arity):
                src = gate["in"][i]
                args.append(values[src] if src in values else prev.get(src, X))
            nxt[gate_id] = _apply_gate(gate["type"], args)
        for gate_id in cyclic:
            nxt[gate_id] = X

        next_outputs = _read_outputs(netlist, nxt, values)
        if record_trace:
            trace.append({"tick": tick, "gates": dict(nxt), "outputs": dict(next_outputs)})

        if tick > 0 and prev == nxt and outputs == next_outputs:
            stable = True
            current = nxt
            outputs = next_outputs
            break
        prev = nxt
        current = nxt
        outputs = next_outputs

    if not stable:
        diagnostics.append("未在 %d tick 内稳定，按全 X 处理" % limit)
        current = {gate["id"]: X for gate in netlist["gates"]}
        outputs = _read_outputs(netlist, current, values)

    return {
        "ok": True,
        "errors": [],
        "outputs": outputs,
        "gates": dict(current),
        "stable": stable,
        "ticks": ticks,
        "trace": trace,
        "diagnostics": diagnostics,
    }


def input_combinations(count: int) -> List[List[int]]:
    """输入的全部 2^n 行组合，按 [A,B,C,D] 从 0000 到 1111 排序。"""
    rows = []
    for i in range(1 << count):
        row = [(i >> (count - 1 - bit)) & 1 for bit in range(count)]
        rows.append(row)
    return rows


def truth_table(netlist: dict) -> List[dict]:
    """全表求值（不抽样）。行序 = input_combinations 的顺序。"""
    rows = input_combinations(len(netlist["inputs"]))
    return [
        dict(
            zip(
                ("input", "outputs", "stable", "ok"),
                (row, simulate(netlist, row, {"recordTrace": False})["outputs"], simulate(netlist, row, {"recordTrace": False})["stable"], simulate(netlist, row, {"recordTrace": False})["ok"]),
            )
        )
        for row in rows
    ]


def truth_table_masks(netlist: dict) -> Tuple[Dict[str, int], Dict[str, bool]]:
    """真值表压成每输出一个 16 位掩码：bit i 对应第 i 行的输出。

    含 X 的行在掩码里记 0，并由 hasX 标出，调用方不得把含 X 的表当作可用关卡。
    """
    table = truth_table(netlist)
    masks: Dict[str, int] = {}
    has_x: Dict[str, bool] = {}
    for name in netlist["outputs"]:
        mask = 0
        x_seen = False
        for index, row in enumerate(table):
            value = row["outputs"][name]
            if value == X:
                x_seen = True
            elif value == 1:
                mask |= 1 << index
        masks[name] = mask
        has_x[name] = x_seen
    return (masks, has_x)


def first_mismatch(netlist_a: dict, netlist_b: dict, input_count: Optional[int] = None) -> Optional[dict]:
    """两网表全表比对的第一处不一致（行号 + 逐输出期望/实际）。"""
    count = input_count if input_count is not None else len(netlist_a["inputs"])
    rows = input_combinations(count)
    for index, row in enumerate(rows):
        out_a = simulate(netlist_a, row, {"recordTrace": False})["outputs"]
        out_b = simulate(netlist_b, row, {"recordTrace": False})["outputs"]
        for name in netlist_a["outputs"]:
            if out_a.get(name) != out_b.get(name):
                return {"row": index, "input": row, "output": name, "expected": out_a.get(name), "actual": out_b.get(name)}
    return None
