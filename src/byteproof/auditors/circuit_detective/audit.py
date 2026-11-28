"""器官 ``circuit-detective``：黑盒电路侦探账本（迁自 10-19-circuit-detective，Node/mjs 源）。

旧仓是纯前端游戏：拨开关、看灯、反推黑盒里的最少门电路——三值 unit-delay 仿真核、
种子确定性关卡生成、最少门求解器（NOT/AND/OR 门基精确 DP）、提交判定（16 行全表
不抽样比对）、逐层点亮、回放短码（CRC16 校验）。本器官把整颗 core 用 Python 重写；
Canvas/UI/构建产物留输入层。

**账本映射**：提交判定 accepted → info（结算行）；结构无效/不稳定/有未知/真值表
不匹配 → error（阻断）；探测回放不一致 → error；关卡生成失败 → error；短码损坏 →
ValueError（rc2，明确提示，绝不静默进别的关卡）。
"""

from __future__ import annotations

from typing import Iterable, List, Mapping, Optional

from byteproof.core.ledger import ERROR, INFO, Record

from . import generator as generator_mod
from . import judge as judge_mod
from . import replay as replay_mod
from . import sim as sim_mod
from . import solver as solver_mod
from . import spec


def evaluate(subject: Mapping, basis) -> Iterable[Record]:
    """账本入口：subject = {mode, level?, draft?, probes?, seed?, code?, options?}。

    ``mode`` ∈ judge（缺省：draft 对 level 的提交判定）/ simulate（探测重算）/
    generate（seed 生成关卡）/ replay（短码解码 + 探测一致性）/ solve（最优门数复核）/
    audit（judge + simulate + reveal 一次跑完）。
    """
    mode = _mode_of(subject)
    records: List[Record] = []
    level = subject.get("level")
    options = subject.get("options") or {}

    if mode == "replay":
        records.extend(_replay_records(subject, basis, options))
    elif mode == "generate":
        records.extend(_generate_records(subject, basis, options))
    elif mode == "solve":
        records.extend(_solve_records(subject, basis, level))
    elif mode in ("audit", "simulate", "judge"):
        if not isinstance(level, dict):
            raise ValueError("subject.level 必须是对象（关卡：inputs/outputs/netlist/optimal）")
        if mode == "audit":
            plan = replay_mod.build_reveal_plan(level["netlist"])
            records.append(
                Record(
                    rule_id=spec.RULE_REVEAL_PLAN,
                    verdict=INFO,
                    message="逐层点亮计划：%d 层（同层按门 id 升序，顺序固定可复现）" % len(plan["layers"]),
                    basis=basis.ref(spec.RULE_REVEAL_PLAN),
                    path="reveal.plan",
                    evidence={"layers": plan["layers"], "layerById": plan["layerById"], "cyclic": plan["cyclic"]},
                )
            )
        if mode in ("audit", "simulate"):
            records.extend(_simulate_records(level, subject.get("probes"), basis))
        if mode in ("audit", "judge"):
            records.extend(_judge_records(level, subject.get("draft"), basis, options))

    blocking = sum(1 for record in records if record.verdict == ERROR)
    records.append(
        Record(
            rule_id=spec.RULE_SUMMARY,
            verdict=INFO,
            message="mode=%s：阻断 %d 条（旧仓「提交通过/不通过」映射为账本 0/1）" % (mode, blocking),
            basis=basis.ref(spec.RULE_SUMMARY),
            path="summary",
            evidence={"mode": mode, "blocking": blocking},
        )
    )
    return records


# ------------------------------------------------------------------ judge
def _judge_records(level: dict, draft, basis, options: dict) -> List[Record]:
    records: List[Record] = []
    if not isinstance(draft, dict):
        raise ValueError("mode=judge 需要 subject.draft（门编辑器草稿）")
    result = judge_mod.judge_submission(draft, level, options)
    for index, error in enumerate(result["errors"]):
        records.append(
            Record(
                rule_id=spec.RULE_DRAFT_INVALID,
                verdict=ERROR,
                message="%s：%s" % (error.get("code"), error.get("message")),
                basis=basis.ref(spec.RULE_DRAFT_INVALID),
                path="draft.errors[%d]" % index,
                evidence=dict(error),
            )
        )
    if result["reason"] == "mismatch":
        mismatch = result["mismatch"]
        records.append(
            Record(
                rule_id=spec.RULE_MISMATCH,
                verdict=ERROR,
                message="第 %d 行（输入 %s）灯 %s 应亮 %s、实际 %s"
                % (mismatch["row"], "".join(str(b) for b in mismatch["input"]), mismatch["output"], mismatch["expected"], mismatch["actual"]),
                basis=basis.ref(spec.RULE_MISMATCH),
                path="mismatch.row-%d" % mismatch["row"],
                evidence=dict(mismatch),
            )
        )
    if result["accepted"]:
        settlement = result["settlement"]
        records.append(
            Record(
                rule_id=spec.RULE_SETTLEMENT,
                verdict=INFO,
                message="结算通过：你的门数 %d / 最少门数 %d（差值 %d）"
                % (settlement["yourGates"], settlement["optimalGates"], settlement["difference"]),
                basis=basis.ref(spec.RULE_SETTLEMENT),
                path="settlement",
                evidence=dict(settlement),
            )
        )
    return records


# ------------------------------------------------------------------ simulate
def _simulate_records(level: dict, probes, basis) -> List[Record]:
    records: List[Record] = []
    if probes is None:
        probes = []
    if not isinstance(probes, list):
        raise ValueError("subject.probes 必须是数组（探测向量整数）")
    for index, vector in enumerate(probes):
        if not isinstance(vector, int) or isinstance(vector, bool) or vector < 0:
            raise ValueError("probes 每项必须是非负整数向量")
        bits = judge_mod.vector_bits(vector, len(level["inputs"]))
        result = sim_mod.simulate(level["netlist"], bits, {"recordTrace": False})
        for diagnostic in result["diagnostics"]:
            records.append(
                Record(
                    rule_id=spec.RULE_SIM_DIAGNOSTIC,
                    verdict=INFO,
                    message="探测 %d：%s" % (index, diagnostic),
                    basis=basis.ref(spec.RULE_SIM_DIAGNOSTIC),
                    path="probes[%d].diagnostic" % index,
                    evidence={"vector": vector, "diagnostic": diagnostic},
                )
            )
    records.append(
        Record(
            rule_id=spec.RULE_PROBES_REPLAY,
            verdict=INFO,
            message="探测重算 %d 步完成（输出序列随记录给出，同一序列在任何实例逐项相同）" % len(probes),
            basis=basis.ref(spec.RULE_PROBES_REPLAY),
            path="probes.replay",
            evidence={"steps": judge_mod.recompute_probes(level, probes)},
        )
    )
    return records


# ------------------------------------------------------------------ generate
def _generate_records(subject, basis, options: dict) -> List[Record]:
    seed = subject.get("seed")
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise ValueError("mode=generate 需要 subject.seed（整数或字符串）")
    result = generator_mod.generate_level(seed, options)
    if result["ok"]:
        level = result["level"]
        return [
            Record(
                rule_id=spec.RULE_LEVEL_GENERATION,
                verdict=INFO,
                message="关卡生成成功：seed=%s 难度=%s 最优门数=%d（尝试 %d 次）"
                % (level["seed"], level["difficulty"], level["optimal"], result["attempts"]),
                basis=basis.ref(spec.RULE_LEVEL_GENERATION),
                path="generation",
                evidence={"level": level, "attempts": result["attempts"], "json": result["json"]},
            )
        ]
    return [
        Record(
            rule_id=spec.RULE_LEVEL_GENERATION,
            verdict=ERROR,
            message=result["message"],
            basis=basis.ref(spec.RULE_LEVEL_GENERATION),
            path="generation",
            evidence={"code": result["code"], "attempts": result["attempts"]},
        )
    ]


# ------------------------------------------------------------------ replay
def _replay_records(subject, basis, options: dict) -> List[Record]:
    records: List[Record] = []
    code = subject.get("code")
    if not isinstance(code, str) or not code:
        raise ValueError("mode=replay 需要 subject.code（分享短码）")
    decoded = replay_mod.decode_record(code)
    netlist = decoded["netlist"]
    level = {
        "seed": decoded["seedText"],
        "label": "replay-%s" % decoded["seedText"],
        "inputs": list(netlist["inputs"]),
        "outputs": list(netlist["outputs"]),
        "netlist": netlist,
    }
    masks, has_x = sim_mod.truth_table_masks(netlist)
    solved = solver_mod.solve_optimal(masks, len(level["inputs"]), spec.MAX_SOLVER_GATES)
    level["optimal"] = solved["optimal"]
    records.append(
        Record(
            rule_id=spec.RULE_PROBES_REPLAY,
            verdict=INFO,
            message="短码解码成功：seed=%s 探测 %d 步（解码侧重算最优门数 %d）"
            % (decoded["seedText"], len(decoded["probes"]), level["optimal"]),
            basis=basis.ref(spec.RULE_PROBES_REPLAY),
            path="replay.decode",
            evidence={"seed": decoded["seedText"], "probes": list(decoded["probes"]), "optimal": level["optimal"]},
        )
    )
    plan = replay_mod.build_reveal_plan(netlist)
    records.append(
        Record(
            rule_id=spec.RULE_REVEAL_PLAN,
            verdict=INFO,
            message="逐层点亮计划：%d 层（同层按门 id 升序，顺序固定可复现）" % len(plan["layers"]),
            basis=basis.ref(spec.RULE_REVEAL_PLAN),
            path="replay.reveal",
            evidence={"layers": plan["layers"], "layerById": plan["layerById"], "cyclic": plan["cyclic"]},
        )
    )
    observed = subject.get("observed")
    if isinstance(observed, list):
        if not judge_mod.probes_match(level, decoded["probes"], observed):
            records.append(
                Record(
                    rule_id=spec.RULE_PROBES_REPLAY,
                    verdict=ERROR,
                    message="探测序列与重算不一致（回放数据被篡改或实例不同）",
                    basis=basis.ref(spec.RULE_PROBES_REPLAY),
                    path="replay.probes",
                    evidence={"observed_steps": len(observed), "replayed_steps": len(decoded["probes"])},
                )
            )
    return records


# ------------------------------------------------------------------ solve
def _solve_records(subject, basis, level) -> List[Record]:
    if not isinstance(level, dict):
        raise ValueError("mode=solve 需要 subject.level")
    netlist = level["netlist"]
    masks, has_x = sim_mod.truth_table_masks(netlist)
    if any(has_x.values()):
        raise ValueError("关卡真值表含 X（问号），不能作为可用关卡求解")
    solved = solver_mod.solve_optimal(masks, len(netlist["inputs"]), spec.MAX_SOLVER_GATES)
    optimal = level.get("optimal")
    if optimal is not None and solved["optimal"] != optimal:
        return [
            Record(
                rule_id=spec.RULE_SETTLEMENT,
                verdict=ERROR,
                message="关卡声明最优门数 %r 与求解器复算 %d 不一致" % (optimal, solved["optimal"]),
                basis=basis.ref(spec.RULE_SETTLEMENT),
                path="solve.optimal",
                evidence={"declared": optimal, "recomputed": solved["optimal"], "per_output": solved["per_output"]},
            )
        ]
    return [
        Record(
            rule_id=spec.RULE_SETTLEMENT,
            verdict=INFO,
            message="最优门数复算一致：%d（%s）" % (solved["optimal"], solved["per_output"]),
            basis=basis.ref(spec.RULE_SETTLEMENT),
            path="solve.optimal",
            evidence={"optimal": solved["optimal"], "per_output": solved["per_output"]},
        )
    ]


# ------------------------------------------------------------------ 输入规整
def _mode_of(subject) -> str:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if not isinstance(mode, str) or mode not in spec.MODES:
        raise ValueError("subject.mode 必须是 %s 之一" % "|".join(spec.MODES))
    return mode
