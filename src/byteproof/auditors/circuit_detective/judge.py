"""提交判定与回放重算（照搬旧仓 ``judge.mjs`` + ``editor.mjs`` 的校验纯函数）。

判定只调 sim 的全表比对与 solver 的门数口径，没有第二套"标准答案"。
编辑器草稿：位置只是画布坐标，不参与任何判定；只有"输出锥内"的零件参与校验与计分。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .netlist import gate_arity, gate_map, topo_order, validate_netlist
from .sim import first_mismatch, simulate, truth_table, X
from .solver import counted_gates
from .spec import GRID, MAX_DRAFT_GATES, MAX_SIGNALS, MAX_SOLVER_GATES, SETTLEMENT_BASIS_LABEL

GATE_TYPES = ("NOT", "AND", "OR")


# ------------------------------------------------------------------ editor 纯函数
def signal_list(draft) -> List[str]:
    return list(draft["inputs"]) + [gate["id"] for gate in draft["gates"]]


def gate_by_id(draft, gate_id) -> Optional[dict]:
    for gate in draft["gates"]:
        if gate["id"] == gate_id:
            return gate
    return None


def snap_coordinate(value, grid: int = GRID) -> int:
    return int(round(value / grid)) * grid


def reachable_gates(draft) -> set:
    """从输出端口反向可达的零件集合（输出锥的并集）。"""
    by_id = {gate["id"]: gate for gate in draft["gates"]}
    seen = set()
    stack = [draft["outputsMap"][name] for name in draft["outputs"] if isinstance(draft["outputsMap"].get(name), str)]
    while stack:
        gate_id = stack.pop()
        if gate_id in seen or gate_id not in by_id:
            continue
        seen.add(gate_id)
        for src in by_id[gate_id]["in"]:
            if isinstance(src, str):
                stack.append(src)
    return seen


def reachable_netlist(draft, used=None) -> dict:
    """只保留输出锥内的零件：未使用的草稿零件不进提交网表，也不参与计分。"""
    if used is None:
        used = reachable_gates(draft)
    return {
        "inputs": list(draft["inputs"]),
        "outputs": list(draft["outputs"]),
        "gates": [
            {"id": gate["id"], "type": gate["type"], "in": [src if src is not None else "" for src in gate["in"]]}
            for gate in draft["gates"]
            if gate["id"] in used
        ],
        "outputsMap": {name: draft["outputsMap"].get(name) or "" for name in draft["outputs"]},
    }


def validate_draft(draft) -> dict:
    """提交前校验。返回 {ok, errors:[{code,message,gateId?,pin?}], netlist}。

    口径：只有"输出锥内"的零件参与校验与计分；玩家多摆的未使用零件既不惩罚，
    也不会被算进门数（countedGates 只看输出锥）。
    """
    errors: List[dict] = []
    signals = set(signal_list(draft))
    if len(draft["gates"]) == 0:
        errors.append({"code": "empty", "message": "还没有摆零件"})
    if len(draft["inputs"]) + len(draft["gates"]) > MAX_SIGNALS:
        errors.append({"code": "signal-limit", "message": "信号总数不能超过 %d 个" % MAX_SIGNALS})

    for name in draft["outputs"]:
        src = draft["outputsMap"].get(name)
        if src is None or not isinstance(src, str):
            errors.append({"code": "output-unmapped", "message": "输出端口 %s 还没接" % name})
        elif src not in signals:
            errors.append({"code": "output-unknown", "message": "输出端口 %s 接到了不存在的信号" % name})

    used = reachable_gates(draft)
    for gate in draft["gates"]:
        if gate["id"] not in used:
            continue  # 未使用零件：不计分，也不参与校验
        for pin, src in enumerate(gate["in"]):
            if src is None:
                errors.append({"code": "pin-unconnected", "message": "零件 %s 的输入端 %d 还没接" % (gate["id"], pin + 1), "gateId": gate["id"], "pin": pin})
            elif src not in signals:
                errors.append({"code": "pin-unknown", "message": "零件 %s 的输入端 %d 接到了不存在的信号" % (gate["id"], pin + 1), "gateId": gate["id"], "pin": pin})

    # 环检测只看向输出锥内的零件；未使用零件之间的环不影响结果。
    cone_netlist = {
        "inputs": draft["inputs"],
        "outputs": draft["outputs"],
        "gates": [gate for gate in draft["gates"] if gate["id"] in used],
        "outputsMap": draft["outputsMap"],
    }
    _order, cyclic = topo_order(cone_netlist)
    if cyclic:
        errors.append({"code": "cycle", "message": "接线绕成了环（%s），结果会一直是未知" % ",".join(cyclic)})

    netlist = None
    if not errors:
        structural_ok, structural_errors = validate_netlist(reachable_netlist(draft, used))
        for message in structural_errors:
            errors.append({"code": "netlist", "message": message})
        netlist = reachable_netlist(draft, used) if structural_ok else None
    return {"ok": len(errors) == 0, "errors": errors, "netlist": netlist}


# ------------------------------------------------------------------ judge
def judge_submission(draft, level: dict, options: Optional[dict] = None) -> dict:
    """提交草稿：结构校验 → 无 X 稳定 → 16 行全表逐输出比对 → 门数与差值。"""
    options = options or {}
    validation = validate_draft(draft)
    if not validation["ok"]:
        return {"ok": True, "accepted": False, "reason": "invalid-draft", "errors": validation["errors"], "mismatch": None, "settlement": None}
    submitted = validation["netlist"]
    max_gates = options.get("maxGates", MAX_SOLVER_GATES)

    for row in truth_table(submitted):
        if not row["ok"] or not row["stable"]:
            return {
                "ok": True,
                "accepted": False,
                "reason": "unstable",
                "errors": [{"code": "unstable", "message": "这个接线在有限步内没有稳定下来"}],
                "mismatch": None,
                "settlement": None,
            }
        for name in level["outputs"]:
            if row["outputs"][name] == X:
                return {
                    "ok": True,
                    "accepted": False,
                    "reason": "unknown-value",
                    "errors": [{"code": "unknown-value", "message": "这个接线有灯会一直是未知（问号）"}],
                    "mismatch": None,
                    "settlement": None,
                }

    mismatch = first_mismatch(submitted, level["netlist"])
    if mismatch:
        return {"ok": True, "accepted": False, "reason": "mismatch", "errors": [], "mismatch": mismatch, "settlement": None}

    your_gates = counted_gates(submitted)
    optimal_gates = level["optimal"]
    return {
        "ok": True,
        "accepted": True,
        "reason": None,
        "errors": [],
        "mismatch": None,
        "settlement": {
            "yourGates": your_gates,
            "optimalGates": optimal_gates,
            "difference": your_gates - optimal_gates,
            "probes": options.get("probes", 0),
            "maxGates": max_gates,
            "basisLabel": SETTLEMENT_BASIS_LABEL,
        },
    }


def vector_bits(vector: int, count: int = 4) -> List[int]:
    """输入向量整数 → 位数组（MSB = 第一个输入），与短码 4 bit 布局一致。"""
    return [(vector >> (count - 1 - bit)) & 1 for bit in range(count)]


def bits_to_vector(bits: List[int]) -> int:
    result = 0
    for bit in bits:
        result = (result << 1) | (bit & 1)
    return result


def recompute_probes(level: dict, probes) -> List[dict]:
    """探测序列重算：seed + 关卡 + 输入向量序列 → 灯的结果序列（同一序列逐项相同）。"""
    return [
        {
            "vector": vector,
            "inputs": vector_bits(vector, len(level["inputs"])),
            "outputs": {name: simulate(level["netlist"], vector_bits(vector, len(level["inputs"])), {"recordTrace": False})["outputs"].get(name, X) for name in level["outputs"]},
            "ok": simulate(level["netlist"], vector_bits(vector, len(level["inputs"])), {"recordTrace": False})["ok"],
            "stable": simulate(level["netlist"], vector_bits(vector, len(level["inputs"])), {"recordTrace": False})["stable"],
        }
        for vector in probes
    ]


def probes_match(level: dict, probes, observed) -> bool:
    """探测序列是否与重算一致（逐项比对输出与稳定性）。"""
    replayed = recompute_probes(level, probes)
    if len(replayed) != len(observed):
        return False
    for row, seen in zip(replayed, observed):
        if not isinstance(seen, dict):
            return False
        for name in level["outputs"]:
            if row["outputs"][name] != (seen.get("outputs") or {}).get(name):
                return False
    return True
