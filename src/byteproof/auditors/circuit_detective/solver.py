"""求解器（照搬旧仓 ``solver.mjs``）：在 NOT/AND/OR 门基下给出最少门数。

口径（照搬 D14）：每个输出端口单独计数（输出锥内按引用展开的门数之和；共享门按
使用它的输出各计一次）；单输出最少数 = 公式复杂度，精确动态规划（16 位掩码分层展开）。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .sim import input_combinations
from .spec import MAX_SOLVER_GATES

MASK16 = 0xFFFF

_COST_CACHE: Dict[Tuple[int, int], dict] = {}


def input_masks(count: int) -> List[int]:
    """输入变量掩码：第 j 个输入在第 i 行（input_combinations 顺序）为 1 时置位。"""
    rows = input_combinations(count)
    masks = []
    for j in range(count):
        mask = 0
        for index, row in enumerate(rows):
            if row[j] == 1:
                mask |= 1 << index
        masks.append(mask)
    return masks


def build_cost_table(input_count: int, max_gates: int) -> dict:
    """成本表：cost[mask] = 用 NOT/AND/OR 计算该 16 位函数所需的最少门数（-1 = 未达）。

    按门数递增分层展开；op/left/right 保留构造痕迹供 formula_for_mask 展开。
    """
    if input_count < 1 or input_count > 4:
        raise ValueError("首期只支持 1–4 个输入")
    size = 1 << 16
    cost = [-1] * size
    op = [0] * size
    left = [-1] * size
    right = [-1] * size
    levels: List[List[int]] = [[]]
    variables = input_masks(input_count)
    for mask in variables:
        if cost[mask] == -1:
            cost[mask] = 0
            levels[0].append(mask)
    for k in range(1, max_gates + 1):
        fresh = set()
        for i in range(k):
            j = k - 1 - i
            if j >= len(levels) or not levels[j]:
                continue
            a_level = levels[i] if i < len(levels) else []
            b_level = levels[j]
            for a in a_level:
                for b in b_level:
                    and_mask = a & b
                    if cost[and_mask] == -1:
                        cost[and_mask] = k
                        op[and_mask] = 1
                        left[and_mask] = a
                        right[and_mask] = b
                        fresh.add(and_mask)
                    or_mask = a | b
                    if cost[or_mask] == -1:
                        cost[or_mask] = k
                        op[or_mask] = 2
                        left[or_mask] = a
                        right[or_mask] = b
                        fresh.add(or_mask)
        previous = levels[k - 1] if k - 1 < len(levels) else []
        for a in previous:
            not_mask = ~a & MASK16
            if cost[not_mask] == -1:
                cost[not_mask] = k
                op[not_mask] = 3
                left[not_mask] = a
                fresh.add(not_mask)
        levels.append(sorted(fresh))
    return {"cost": cost, "op": op, "left": left, "right": right, "vars": variables, "max_gates": max_gates}


def cost_table(input_count: int, max_gates: int) -> dict:
    key = (input_count, max_gates)
    if key not in _COST_CACHE:
        _COST_CACHE[key] = build_cost_table(input_count, max_gates)
    return _COST_CACHE[key]


def minimal_gates_for_mask(mask: int, input_count: int, max_gates: int = MAX_SOLVER_GATES) -> int:
    """单个输出函数的最少门数；不可达返回 -1。"""
    table = cost_table(input_count, max_gates)
    return table["cost"][mask & MASK16]


def cone_of(netlist: dict, output_name: str) -> set:
    """输出锥（含该输出映射到的信号及其上游门）。"""
    gate_by_id = gate_map(netlist)
    seen = set()
    stack = [netlist["outputsMap"][output_name]]
    while stack:
        gate_id = stack.pop()
        if gate_id in seen or gate_id not in gate_by_id:
            continue
        seen.add(gate_id)
        stack.extend(gate_by_id[gate_id]["in"])
    return seen


def _count_uses(signal: str, gate_by_id: Dict[str, dict], stack: set) -> int:
    gate = gate_by_id.get(signal)
    if not gate or gate["id"] in stack:
        return 0  # 输入端口计 0；环不再展开
    stack.add(gate["id"])
    total = 1
    for src in gate["in"]:
        total += _count_uses(src, gate_by_id, stack)
    stack.discard(gate["id"])
    return total


def counted_gates(netlist: dict) -> int:
    """按声明口径计算提交网表的门数：每输出锥内按引用展开的门数之和。

    共享门每被引用一次计一次（同一输出内的重复引用也各计一次），未使用的门不计分。
    与单输出公式复杂度对齐：counted_gates(submitted) >= optimal 恒成立。
    """
    gate_by_id = gate_map(netlist)
    total = 0
    for name in netlist["outputs"]:
        total += _count_uses(netlist["outputsMap"][name], gate_by_id, set())
    return total


def solve_optimal(masks: Dict[str, int], input_count: int, max_gates: int = MAX_SOLVER_GATES) -> dict:
    """求解一个真值表集合的最少门数（按声明口径求和）；不可达返回 optimal=-1。"""
    table = cost_table(input_count, max_gates)
    per_output: Dict[str, int] = {}
    total = 0
    for name in sorted(masks):
        value = table["cost"][masks[name] & MASK16]
        per_output[name] = value
        if value < 0:
            return {"optimal": -1, "per_output": per_output, "reason": "unreachable"}
        total += value
    return {"optimal": total, "per_output": per_output, "reason": None}


def formula_for_mask(mask: int, input_count: int, max_gates: int, next_id) -> Tuple[List[dict], str]:
    """按成本表构造痕迹展开一个函数的最优公式（证明"最优门数确实可达"）。

    返回 {gates, signal}；递归是后序的，gates 已按依赖先于使用者排列。
    """
    table = cost_table(input_count, max_gates)
    cost = table["cost"]
    op = table["op"]
    left = table["left"]
    right = table["right"]
    variables = table["vars"]
    gates: List[dict] = []

    def build(node: int) -> str:
        value = node & MASK16
        var_index = variables.index(value) if value in variables else -1
        if cost[value] == 0 and var_index >= 0:
            return "i%d" % var_index
        if cost[value] < 0:
            raise ValueError("函数 %x 在门数上限内不可达" % value)
        gate_id = next_id()
        kind = op[value]
        if kind == 1:
            gates.append({"id": gate_id, "type": "AND", "in": [build(left[value]), build(right[value])]})
        elif kind == 2:
            gates.append({"id": gate_id, "type": "OR", "in": [build(left[value]), build(right[value])]})
        elif kind == 3:
            gates.append({"id": gate_id, "type": "NOT", "in": [build(left[value])]})
        else:
            raise ValueError("成本表缺少构造痕迹: %x" % value)
        return gate_id

    signal = build(mask)
    return (gates, signal)


def optimal_netlist(masks: Dict[str, int], input_count: int, max_gates: int, outputs=None) -> dict:
    """用求解器结果构造"最优网表"：每输出独立公式（不共享），
    因此 counted_gates(结果) == solve_optimal(masks).optimal。"""
    names = list(outputs) if outputs is not None else sorted(masks)
    counter = {"n": 1}

    def next_id() -> str:
        gate_id = "w%02d" % counter["n"]
        counter["n"] += 1
        return gate_id

    gates: List[dict] = []
    outputs_map: Dict[str, str] = {}
    for name in names:
        built, signal = formula_for_mask(masks[name], input_count, max_gates, next_id)
        gates.extend(built)
        outputs_map[name] = signal
    return {
        "inputs": ["i%d" % i for i in range(input_count)],
        "outputs": list(names),
        "gates": gates,
        "outputsMap": outputs_map,
    }


def gate_map(netlist: dict) -> Dict[str, dict]:
    return {gate["id"]: gate for gate in netlist["gates"]}
