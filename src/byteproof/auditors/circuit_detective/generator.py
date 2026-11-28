"""关卡生成器（照搬旧仓 ``generator.mjs``）：seed → xorshift128+ → 随机网表 →
求解器复核 → 关卡 JSON。确定性纪律：同 seed 生成字节级相同的关卡。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .netlist import gate_arity, level_to_json, validate_netlist
from .rng import create_rng, pick_distinct
from .sim import truth_table_masks
from .solver import solve_optimal
from .spec import DEFAULT_MAX_GATES, GATE_BASIS, LEVEL_FORMAT, MAX_REDRAWS, LEVEL_VERSION

DIFFICULTY_BANDS = (("easy", 2), ("normal", 4), ("hard", 12))


def difficulty_of(optimal: int) -> str:
    for name, max_optimal in DIFFICULTY_BANDS:
        if optimal <= max_optimal:
            return name
    return "hard"


def _random_netlist(rng, input_count: int, output_count: int, gate_budget: int) -> dict:
    inputs = ["i%d" % i for i in range(input_count)]
    gates: List[dict] = []
    available = list(inputs)
    gate_count = 2 + rng.next_int(max(1, gate_budget - 1))
    for index in range(gate_count):
        gate_type = GATE_BASIS[rng.next_int(len(GATE_BASIS))]
        arity = gate_arity(gate_type)
        pins = [available[rng.next_int(len(available))] for _ in range(arity)]
        gate_id = "g%02d" % (index + 1)
        gates.append({"id": gate_id, "type": gate_type, "in": pins})
        available.append(gate_id)

    outputs = ["o%d" % i for i in range(output_count)]
    outputs_map: Dict[str, str] = {}
    chosen = pick_distinct(rng, len(available), output_count)
    for name, index in zip(outputs, chosen):
        outputs_map[name] = available[index]
    return {"inputs": inputs, "outputs": outputs, "gates": gates, "outputsMap": outputs_map}


def _fingerprint(netlist: dict, masks: Dict[str, int]) -> str:
    return "|".join("%s:%x" % (name, masks[name]) for name in netlist["outputs"])


def generate_level(seed, options: Optional[dict] = None) -> dict:
    """生成关卡。失败时返回 {ok:false, code, message}，不抛异常、不静默换 seed。"""
    options = options or {}
    input_count = options.get("inputCount", 4)
    output_count = options.get("outputCount", 4)
    gate_budget = options.get("gateBudget", 8)
    max_gates = options.get("maxGates", DEFAULT_MAX_GATES)
    min_optimal = options.get("minOptimal", 2)
    rng = create_rng(seed)

    for attempt in range(MAX_REDRAWS):
        netlist = _random_netlist(rng, input_count, output_count, gate_budget)
        ok, _errors = validate_netlist(netlist)
        if not ok:
            continue
        # 拒绝恒等冗余门（AND(i,i) / OR(i,i) = i）：隐藏实现里不该有玩家看不出的死结构
        if any(len(g["in"]) == 2 and g["in"][0] == g["in"][1] for g in netlist["gates"]):
            continue

        masks, has_x = truth_table_masks(netlist)
        if any(has_x.values()):
            continue

        if len(set(masks.values())) < 2:
            continue

        solved = solve_optimal(masks, input_count, max_gates)
        if solved["optimal"] < min_optimal:
            continue
        if solved["optimal"] > gate_budget:
            continue

        level = {
            "format": LEVEL_FORMAT,
            "version": LEVEL_VERSION,
            "id": "seed-%d" % rng.seed,
            "seed": str(rng.seed),
            "label": str(seed),
            "difficulty": difficulty_of(solved["optimal"]),
            "inputs": netlist["inputs"],
            "outputs": netlist["outputs"],
            "netlist": netlist,
            "optimal": solved["optimal"],
            "optimalPerOutput": solved["per_output"],
            "fingerprint": _fingerprint(netlist, masks),
        }
        return {"ok": True, "level": level, "json": level_to_json(level), "attempts": attempt + 1}

    return {
        "ok": False,
        "code": "level-generation-failed",
        "message": "seed %s 在 %d 次重抽内未得到合格关卡" % (str(seed), MAX_REDRAWS),
        "attempts": MAX_REDRAWS,
    }


def daily_seed(date_string: str) -> str:
    """每日题：日期字符串（YYYY-MM-DD）直接作为 seed 走 FNV-1a。"""
    return date_string
