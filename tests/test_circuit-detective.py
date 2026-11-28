"""``circuit-detective`` 器官的无损测试（迁自 10-19-circuit-detective，Node/mjs 源）。

无损 = 旧仓 core 的**判定语义仍然是那一套**：三值 unit-delay 仿真（X 传递语义、环
恒 X）、NOT/AND/OR 精确 DP 求解器（按每灯单独计的门数口径）、种子确定性关卡生成
（xorshift128+ + FNV-1a）、提交判定（16 行全表不抽样）、回放短码（CRC16 + Base64url，
篡改/截断/版本不兼容明确报错）、逐层点亮计划。跨语言参考值（fnv1a64 / rng 序列 /
crc16 / 一份关卡 JSON）取自旧仓 node 实跑，直接内联为对撞断言。

**没迁的部分逐条写在 ``docs/circuit-detective.md`` §6 的处置表里**（Canvas/DOM、
构建产物、静态扫描门、sprint-layout 门）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 22 个测试文件剔除 ``cli`` 与 ``release`` 后 19 文件
`node --test` 实跑 **X = 121 passed**（旧层 ``test(`` 调用数 124）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors.circuit_detective import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    generator,
    judge,
    netlist,
    replay,
    rng,
    sim,
    solver,
    spec,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    Basis,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "circuit-detective"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "circuit-detective.basis.json"
THRESHOLDS_PATH = DATA_DIR / "circuit-detective.thresholds.json"
SAMPLE = ROOT / "samples" / "circuit-detective.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def _netlist(gates, outputs_map, inputs=None, outputs=None):
    return {
        "inputs": inputs or ["i0", "i1", "i2", "i3"],
        "outputs": outputs or ["o0", "o1", "o2", "o3"],
        "gates": gates,
        "outputsMap": outputs_map,
    }


def _net_i0():
    return _netlist([{"id": "g01", "type": "NOT", "in": ["i0"]}], {"o0": "g01", "o1": "i1", "o2": "i2", "o3": "i3"})


def _level():
    return {
        "seed": "11952473959851858958",
        "label": "2026-01-19",
        "inputs": ["i0", "i1", "i2", "i3"],
        "outputs": ["o0", "o1", "o2", "o3"],
        "optimal": 7,
        "netlist": {
            "inputs": ["i0", "i1", "i2", "i3"],
            "outputs": ["o0", "o1", "o2", "o3"],
            "gates": [
                {"id": "g01", "type": "AND", "in": ["i0", "i1"]},
                {"id": "g02", "type": "OR", "in": ["i0", "i1"]},
                {"id": "g03", "type": "NOT", "in": ["g01"]},
                {"id": "g04", "type": "AND", "in": ["g03", "i2"]},
                {"id": "g05", "type": "OR", "in": ["g04", "i3"]},
                {"id": "g06", "type": "AND", "in": ["g02", "i3"]},
            ],
            "outputsMap": {"o0": "g01", "o1": "g02", "o2": "g04", "o3": "g06"},
        },
    }


def _draft_of(netlist):
    gates = [dict(gate, x=32, y=32) for gate in netlist["gates"]]
    return {
        "inputs": list(netlist["inputs"]),
        "outputs": list(netlist["outputs"]),
        "gates": gates,
        "outputsMap": dict(netlist["outputsMap"]),
        "nextGateNumber": len(netlist["gates"]) + 1,
    }


def _subject(mode="judge", **extra):
    subject = {"mode": mode}
    subject.update(extra)
    return subject


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _report(subject):
    return Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="test.json", records=tuple(_evaluate(subject)))


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG


def test_pack_declares_mode_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "circuit_detective" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_sample_is_a_clean_solve():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert data["mode"] == "solve"
    records = _evaluate(data)
    assert [r.verdict for r in records if r.rule_id != spec.RULE_SUMMARY] == [INFO]


def test_basis_has_every_declared_rule():
    assert set(BASIS.rule_ids()) == set(spec.RULE_IDS)


def test_basis_rules_all_have_version_source_and_text():
    for rule_id in BASIS.rule_ids():
        rule = BASIS.require(rule_id)
        assert rule.version == "1", rule_id
        assert rule.source, rule_id
        assert rule.text, rule_id


def test_basis_rule_ids_are_sorted():
    assert BASIS.rule_ids() == sorted(BASIS.rule_ids())


def test_every_rule_has_a_nominal_verdict():
    assert set(spec.RULE_IDS) == set(spec.VERDICTS)


def test_thresholds_verdicts_match_runtime():
    assert SETTINGS["verdicts"] == spec.VERDICTS


def test_thresholds_constants_match_runtime():
    constants = SETTINGS["constants"]
    assert constants["max_solver_gates"] == spec.MAX_SOLVER_GATES
    assert constants["signal_bits"] == spec.SIGNAL_BITS
    assert constants["record_version"] == spec.RECORD_VERSION
    assert constants["max_code_length"] == spec.MAX_CODE_LENGTH
    assert constants["max_redraws"] == spec.MAX_REDRAWS


def test_thresholds_gate_types_match_runtime():
    assert SETTINGS["gate_types"] == list(spec.GATE_TYPES)
    assert SETTINGS["gate_arity"] == spec.GATE_ARITY
    assert SETTINGS["x_value"] == spec.X


def test_thresholds_difficulty_bands_match_runtime():
    assert SETTINGS["difficulty_bands"] == {"easy": 2, "normal": 4, "hard": 12}


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("cd-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== netlist
def test_gate_arity_table():
    assert netlist.gate_arity("NOT") == 1
    assert netlist.gate_arity("AND") == 2
    assert netlist.gate_arity("OR") == 2
    assert netlist.gate_arity("XOR") == 0


def test_validate_netlist_ok():
    ok, errors = netlist.validate_netlist(_net_i0())
    assert ok is True and errors == []


def test_validate_netlist_rejects_empty_inputs():
    bad = {"inputs": [], "outputs": ["o0"], "gates": [], "outputsMap": {"o0": "i0"}}
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and "inputs 必须是非空数组" in errors


def test_validate_netlist_rejects_duplicate_inputs():
    bad = {"inputs": ["i0", "i0"], "outputs": ["o0"], "gates": [], "outputsMap": {"o0": "i0"}}
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and "inputs 含重复端口名" in errors


def test_validate_netlist_rejects_output_named_like_input():
    bad = {"inputs": ["i0"], "outputs": ["i0"], "gates": [], "outputsMap": {"i0": "i0"}}
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("同名" in e for e in errors)


def test_validate_netlist_rejects_unknown_gate_type():
    bad = _netlist([{"id": "g01", "type": "XOR", "in": ["i0", "i1"]}], {"o0": "g01"})
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("未知门类型" in e for e in errors)


def test_validate_netlist_rejects_wrong_arity():
    bad = _netlist([{"id": "g01", "type": "AND", "in": ["i0"]}], {"o0": "g01"})
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("引脚数" in e for e in errors)


def test_validate_netlist_rejects_undefined_signal():
    bad = _netlist([{"id": "g01", "type": "NOT", "in": ["ghost"]}], {"o0": "g01"})
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("未定义信号" in e for e in errors)


def test_validate_netlist_rejects_duplicate_gate_id():
    bad = _netlist(
        [{"id": "g01", "type": "NOT", "in": ["i0"]}, {"id": "g01", "type": "NOT", "in": ["i1"]}],
        {"o0": "g01"},
    )
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("重复" in e for e in errors)


def test_validate_netlist_rejects_missing_outputs_map():
    bad = {"inputs": ["i0"], "outputs": ["o0"], "gates": []}
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("outputsMap" in e for e in errors)


def test_validate_netlist_rejects_unmapped_output():
    bad = _netlist([], {"o0": None, "o1": "i1", "o2": "i2", "o3": "i3"})
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("未映射到信号" in e for e in errors)


def test_topo_order_and_cycle_detection():
    loop = _netlist(
        [
            {"id": "g02", "type": "AND", "in": ["g01", "i0"]},
            {"id": "g01", "type": "OR", "in": ["g02", "i1"]},
        ],
        {"o0": "g02"},
    )
    order, cyclic = netlist.topo_order(loop)
    assert order == []
    assert cyclic == ["g01", "g02"]


def test_topo_order_ties_by_gate_id():
    net = _netlist(
        [
            {"id": "g02", "type": "NOT", "in": ["i0"]},
            {"id": "g01", "type": "NOT", "in": ["i1"]},
        ],
        {"o0": "g02"},
    )
    order, cyclic = netlist.topo_order(net)
    assert order == ["g01", "g02"] and cyclic == []


def test_level_to_json_key_order_is_fixed():
    level = dict(_level(), id="seed-1", seed="1", format=spec.LEVEL_FORMAT, version=spec.LEVEL_VERSION, difficulty="hard")
    text = netlist.level_to_json(level)
    assert text.index('"format"') < text.index('"version"') < text.index('"netlist"') < text.index('"optimal"')


def test_level_to_json_compact_separators():
    level = dict(_level(), id="seed-1", seed="1", format=spec.LEVEL_FORMAT, version=spec.LEVEL_VERSION, difficulty="hard")
    text = netlist.level_to_json(level)
    assert ": " not in text and ", " not in text


# ================================================================== sim
def test_sim_not_gate():
    result = sim.simulate(_net_i0(), [0, 0, 0, 0], {"recordTrace": False})
    assert result["ok"] is True and result["stable"] is True
    assert result["outputs"]["o0"] == 1


def test_sim_and_or_basics():
    net = _netlist(
        [{"id": "g01", "type": "AND", "in": ["i0", "i1"]}, {"id": "g02", "type": "OR", "in": ["i0", "i1"]}],
        {"o0": "g01", "o1": "g02", "o2": "i2", "o3": "i3"},
    )
    result = sim.simulate(net, [1, 0, 0, 0], {"recordTrace": False})
    assert result["outputs"]["o0"] == 0
    assert result["outputs"]["o1"] == 1


def test_sim_x_is_dominant_for_and_and_or():
    # 三值语义：AND 见 0 得 0、OR 见 1 得 1、NOT(X)=X；环成员恒 X
    net = _netlist([{"id": "g01", "type": "OR", "in": ["g02", "i1"]}, {"id": "g02", "type": "AND", "in": ["g01", "i0"]}], {"o0": "g02", "o1": "i1", "o2": "i2", "o3": "i3"})
    result = sim.simulate(net, [1, 1, 0, 0], {"recordTrace": False})
    assert result["outputs"]["o0"] == spec.X
    assert any("组合环" in d for d in result["diagnostics"])


def test_sim_unstable_reports_all_x():
    net = _netlist([{"id": "g01", "type": "NOT", "in": ["g01"]}], {"o0": "g01", "o1": "i1", "o2": "i2", "o3": "i3"})
    result = sim.simulate(net, [0, 0, 0, 0], {"recordTrace": False})
    assert result["outputs"]["o0"] == spec.X
    assert any("组合环" in d for d in result["diagnostics"])  # 自反环每 tick 强制 X → 立即稳定


def test_sim_dict_input_vector():
    result = sim.simulate(_net_i0(), {"i0": 1, "i1": 0, "i2": 0, "i3": 0}, {"recordTrace": False})
    assert result["outputs"]["o0"] == 0


def test_sim_invalid_netlist_reported():
    bad = {"inputs": [], "outputs": ["o0"], "gates": [], "outputsMap": {}}
    result = sim.simulate(bad, [0, 0, 0, 0])
    assert result["ok"] is False


def test_input_combinations_order():
    rows = sim.input_combinations(2)
    assert rows == [[0, 0], [0, 1], [1, 0], [1, 1]]


def test_truth_table_row_count():
    table = sim.truth_table(_net_i0())
    assert len(table) == 16
    assert all(row["ok"] and row["stable"] for row in table)


def test_truth_table_masks_bit_order():
    # NOT(i0)：bit i 对应第 i 行（i0 = 行号最高位）→ 1 的行 = i0 为 0 的行
    masks, has_x = sim.truth_table_masks(_net_i0())
    assert has_x == {"o0": False, "o1": False, "o2": False, "o3": False}
    assert masks["o0"] == 0x00FF  # NOT(i0)：i0=0 的前 8 行
    assert masks["o1"] == 0xF0F0  # i1 直通：i1=1 的行


def test_first_mismatch_reports_row_and_output():
    a = _net_i0()
    b = _netlist([{"id": "g01", "type": "AND", "in": ["i0", "i0"]}], {"o0": "g01", "o1": "i1", "o2": "i2", "o3": "i3"})
    mismatch = sim.first_mismatch(a, b)
    assert mismatch is not None
    assert mismatch["output"] == "o0"
    assert mismatch["expected"] != mismatch["actual"]


def test_first_mismatch_none_when_equal():
    assert sim.first_mismatch(_net_i0(), _net_i0()) is None


# ================================================================== rng（跨语言参考值）
def test_fnv1a64_reference_value():
    # 旧仓 node 实跑：fnv1a64('2026-01-19')
    assert rng.fnv1a64("2026-01-19") == 18100102244837192254


def test_normalize_seed_negative_wraps():
    # 旧仓 node 实跑：normalizeSeed(-1)
    assert rng.normalize_seed(-1) == 18446744073709551615


def test_normalize_seed_string_uses_fnv():
    assert rng.normalize_seed("2026-01-19") == rng.fnv1a64("2026-01-19")


def test_normalize_seed_rejects_bool_and_float():
    with pytest.raises(TypeError):
        rng.normalize_seed(True)
    with pytest.raises(TypeError):
        rng.normalize_seed(1.5)


def test_rng_sequence_matches_node():
    # 旧仓 node 实跑：createRng(1) 的前三个 nextU32
    stream = rng.create_rng(1)
    values = [stream.next_u32() for _ in range(3)]
    assert values == [2559615116, 2443280914, 3555056611]


def test_rng_same_seed_same_sequence():
    a = rng.create_rng("seed-x")
    b = rng.create_rng("seed-x")
    assert [a.next_u32() for _ in range(5)] == [b.next_u32() for _ in range(5)]


def test_rng_next_int_rejects_non_positive():
    stream = rng.create_rng(1)
    with pytest.raises(ValueError):
        stream.next_int(0)


def test_pick_distinct_deterministic_and_distinct():
    stream_a = rng.create_rng(42)
    stream_b = rng.create_rng(42)
    picked = rng.pick_distinct(stream_a, 8, 4)
    assert picked == rng.pick_distinct(stream_b, 8, 4)
    assert len(picked) == 4
    assert len(set(picked)) == 4
    assert all(0 <= index < 8 for index in picked)


def test_pick_distinct_caps_count_at_n():
    stream = rng.create_rng(7)
    picked = rng.pick_distinct(stream, 3, 10)
    assert sorted(picked) == [0, 1, 2]


# ================================================================== solver
def test_input_masks_cover_all_rows():
    # 行序 00,01,10,11 → i0 = 后两行 = 0b1100；i1 = 第 1/3 行 = 0b1010
    masks = solver.input_masks(2)
    assert masks == [0b1100, 0b1010]


def test_minimal_gates_for_inputs_and_not():
    assert solver.minimal_gates_for_mask(0b1100, 2) == 0  # 输入变量本身 0 门
    assert solver.minimal_gates_for_mask(0b1010, 2) == 0
    # NOT 是 16 位补：~0b1010 = 0xFFF5，不是 4 行语义的 0b0101 → 单独的 0b0101 不可达
    assert solver.minimal_gates_for_mask(0b0101, 2) == -1


def test_minimal_gates_xor_needs_four_gates():
    # XOR 在 16 位补语义下 = AND(OR(a,b), NOT(AND(a,b))) → 4 门（与旧仓 node 实跑一致）
    mask = 0b0110  # i0 XOR i1
    assert solver.minimal_gates_for_mask(mask, 2, 12) == 4


def test_solve_optimal_sums_per_output():
    solved = solver.solve_optimal({"o0": 0b1100, "o1": 0b0110}, 2)
    assert solved["optimal"] == 4
    assert solved["per_output"] == {"o0": 0, "o1": 4}


def test_solve_optimal_unreachable_reports_minus_one():
    solved = solver.solve_optimal({"o0": 0b0011}, 2, 12)  # 低 4 位孤立函数在 16 位补语义下不可达
    assert solved["optimal"] == -1
    assert solved["reason"] == "unreachable"


def test_cost_table_rejects_bad_input_count():
    with pytest.raises(ValueError):
        solver.build_cost_table(5, 12)
    with pytest.raises(ValueError):
        solver.build_cost_table(0, 12)


def test_counted_gates_counts_shared_per_output():
    net = _netlist(
        [{"id": "g01", "type": "NOT", "in": ["i0"]}, {"id": "g02", "type": "AND", "in": ["g01", "i1"]}],
        {"o0": "g01", "o1": "g02", "o2": "i2", "o3": "i3"},
    )
    # o0 锥 = 1 门（g01）；o1 锥 = 2 门（g02 + 引用 g01 再计一次）；共 3
    assert solver.counted_gates(net) == 3


def test_counted_gates_ignores_unused_gates():
    net = _net_i0()
    net["gates"].append({"id": "g99", "type": "NOT", "in": ["i3"]})
    assert solver.counted_gates(net) == 1


def test_cone_of_contains_upstream():
    net = _netlist(
        [{"id": "g01", "type": "NOT", "in": ["i0"]}, {"id": "g02", "type": "AND", "in": ["g01", "i1"]}],
        {"o0": "g02", "o1": "i1", "o2": "i2", "o3": "i3"},
    )
    assert solver.cone_of(net, "o0") == {"g02", "g01"}


def test_formula_for_mask_reproduces_optimal():
    mask = 0b0110  # XOR（16 位补语义下最优 4 门）
    counter = {"n": 1}

    def next_id():
        gate_id = "w%02d" % counter["n"]
        counter["n"] += 1
        return gate_id

    gates, signal = solver.formula_for_mask(mask, 2, 12, next_id)
    net = {"inputs": ["i0", "i1"], "outputs": ["o0"], "gates": gates, "outputsMap": {"o0": signal}}
    assert solver.counted_gates(net) == 4
    masks, _has_x = sim.truth_table_masks(net)
    assert masks["o0"] == mask


def test_optimal_netlist_matches_declared_optimal():
    masks = {"o0": 0b1100, "o1": 0b0110}
    net = solver.optimal_netlist(masks, 2, 12)
    assert solver.counted_gates(net) == solver.solve_optimal(masks, 2)["optimal"]


# ================================================================== generator（跨语言对撞）
REFERENCE_JSON = '{"format":"circuit-detective/level","version":1,"id":"seed-18100102244837192254","seed":"18100102244837192254","label":"2026-01-19","difficulty":"hard","inputs":["i0","i1","i2","i3"],"outputs":["o0","o1","o2","o3"],"netlist":{"inputs":["i0","i1","i2","i3"],"outputs":["o0","o1","o2","o3"],"gates":[{"id":"g01","type":"NOT","in":["i0"]},{"id":"g02","type":"AND","in":["i2","g01"]},{"id":"g03","type":"AND","in":["g02","g01"]},{"id":"g04","type":"NOT","in":["g01"]},{"id":"g05","type":"OR","in":["g01","g02"]},{"id":"g06","type":"NOT","in":["i3"]},{"id":"g07","type":"AND","in":["i0","g06"]}],"outputsMap":{"o0":"g01","o1":"g07","o2":"g05","o3":"g06"}},"optimal":5}'


def test_generate_level_matches_node_byte_for_byte():
    # 旧仓 node 实跑 generateLevel('2026-01-19') 的 JSON 原文（跨语言逐字节对撞）
    result = generator.generate_level("2026-01-19")
    assert result["ok"] is True
    assert result["attempts"] == 2
    assert result["json"] == REFERENCE_JSON


def test_generate_level_same_seed_identical():
    a = generator.generate_level("2026-01-19")
    b = generator.generate_level("2026-01-19")
    assert a["json"] == b["json"]


def test_generate_level_difficulty_bands():
    assert generator.difficulty_of(1) == "easy"
    assert generator.difficulty_of(2) == "easy"
    assert generator.difficulty_of(4) == "normal"
    assert generator.difficulty_of(5) == "hard"


def test_generate_level_id_and_seed_format():
    result = generator.generate_level("2026-01-19")
    level = result["level"]
    assert level["id"] == "seed-" + level["seed"]
    assert level["seed"] == str(rng.fnv1a64("2026-01-19"))


def test_generate_level_optimal_within_budget():
    result = generator.generate_level("2026-01-19")
    assert 2 <= result["level"]["optimal"] <= 8


def test_generate_level_rejects_impossible_budget():
    result = generator.generate_level("2026-01-19", {"gateBudget": 1, "minOptimal": 2})
    assert result["ok"] is False
    assert result["code"] == "level-generation-failed"


def test_daily_seed_passthrough():
    assert generator.daily_seed("2026-10-19") == "2026-10-19"


# ================================================================== judge
def test_validate_draft_accepts_level_netlist_as_draft():
    level = _level()
    validation = judge.validate_draft(_draft_of(level["netlist"]))
    assert validation["ok"] is True and validation["errors"] == []


def test_validate_draft_rejects_empty():
    level = _level()
    draft = {"inputs": level["inputs"], "outputs": level["outputs"], "gates": [], "outputsMap": {name: None for name in level["outputs"]}}
    validation = judge.validate_draft(draft)
    assert validation["ok"] is False
    codes = {error["code"] for error in validation["errors"]}
    assert {"empty", "output-unmapped"} <= codes


def test_validate_draft_reports_unconnected_pin():
    level = _level()
    draft = _draft_of(level["netlist"])
    draft["gates"][0]["in"] = [None, "i1"]
    validation = judge.validate_draft(draft)
    assert validation["ok"] is False
    assert any(error["code"] == "pin-unconnected" for error in validation["errors"])


def test_validate_draft_reports_unknown_signal():
    level = _level()
    draft = _draft_of(level["netlist"])
    draft["gates"][0]["in"] = ["ghost", "i1"]
    validation = judge.validate_draft(draft)
    assert validation["ok"] is False
    assert any(error["code"] == "pin-unknown" for error in validation["errors"])


def test_validate_draft_ignores_unused_gate_errors():
    # 只有输出锥内的零件参与校验：未使用零件缺引脚不卡提交
    level = _level()
    draft = _draft_of(level["netlist"])
    draft["gates"].append({"id": "g99", "type": "NOT", "in": [None], "x": 0, "y": 0})
    validation = judge.validate_draft(draft)
    assert validation["ok"] is True


def test_validate_draft_reports_cycle_in_cone():
    level = _level()
    draft = _draft_of(level["netlist"])
    draft["outputsMap"]["o0"] = "g01"
    draft["gates"][0] = {"id": "g01", "type": "OR", "in": ["g02", "i0"], "x": 0, "y": 0}
    draft["gates"][1] = {"id": "g02", "type": "AND", "in": ["g01", "i1"], "x": 0, "y": 0}
    validation = judge.validate_draft(draft)
    assert validation["ok"] is False
    assert any(error["code"] == "cycle" for error in validation["errors"])


def test_judge_accepts_identical_netlist():
    level = _level()
    result = judge.judge_submission(_draft_of(level["netlist"]), level)
    assert result["accepted"] is True
    assert result["settlement"]["difference"] == 0
    assert result["settlement"]["yourGates"] == level["optimal"]


def test_judge_settlement_counts_shared_gates():
    level = _level()
    draft = _draft_of(level["netlist"])
    result = judge.judge_submission(draft, level)
    assert result["settlement"]["optimalGates"] == 7
    assert result["settlement"]["basisLabel"] == spec.SETTLEMENT_BASIS_LABEL


def test_judge_reports_first_mismatch():
    level = _level()
    draft = _draft_of(level["netlist"])
    draft["gates"][0] = {"id": "g01", "type": "OR", "in": ["i0", "i1"], "x": 0, "y": 0}
    result = judge.judge_submission(draft, level)
    assert result["accepted"] is False
    assert result["reason"] == "mismatch"
    assert result["mismatch"]["output"] in ("o0", "o2")


def test_judge_invalid_draft_short_circuits():
    level = _level()
    draft = {"inputs": level["inputs"], "outputs": level["outputs"], "gates": [], "outputsMap": {name: None for name in level["outputs"]}}
    result = judge.judge_submission(draft, level)
    assert result["accepted"] is False
    assert result["reason"] == "invalid-draft"
    assert result["errors"]


def test_vector_bits_roundtrip():
    assert judge.vector_bits(0b1010) == [1, 0, 1, 0]
    assert judge.bits_to_vector([1, 0, 1, 0]) == 0b1010


def test_recompute_probes_deterministic():
    level = _level()
    rows_a = judge.recompute_probes(level, [0, 15, 5])
    rows_b = judge.recompute_probes(level, [0, 15, 5])
    assert rows_a == rows_b
    assert [row["vector"] for row in rows_a] == [0, 15, 5]


def test_probes_match_positive_and_negative():
    level = _level()
    rows = judge.recompute_probes(level, [0, 15])
    assert judge.probes_match(level, [0, 15], rows) is True
    assert judge.probes_match(level, [0, 15], rows[:1]) is False
    tampered = [dict(row, outputs=dict(row["outputs"], o0=1 - row["outputs"]["o0"])) for row in rows]
    assert judge.probes_match(level, [0, 15], tampered) is False


# ================================================================== replay / reveal
def test_crc16_reference_value():
    # 旧仓 node 实跑：crc16(Uint8Array([1,2,3]))
    assert replay.crc16([1, 2, 3]) == 44461


def test_encode_decode_roundtrip():
    result = generator.generate_level("2026-01-19")
    record = {"seed": result["level"]["seed"], "probes": [0, 15, 5], "netlist": result["level"]["netlist"]}
    code = replay.encode_record(record)
    assert len(code) <= spec.MAX_CODE_LENGTH
    decoded = replay.decode_record(code)
    # 旧仓同语义：字符串 seed 编码走 FNV-1a，解码回数字串
    assert decoded["seedText"] == str(rng.fnv1a64(result["level"]["seed"]))
    assert decoded["probes"] == [0, 15, 5]
    assert decoded["netlist"]["gates"] == result["level"]["netlist"]["gates"]
    assert decoded["netlist"]["outputsMap"] == result["level"]["netlist"]["outputsMap"]


def test_encode_rejects_too_many_gates():
    gates = [{"id": "g%02d" % i, "type": "NOT", "in": ["i0"]} for i in range(13)]
    net = _netlist(gates, {"o0": "g01"})
    with pytest.raises(replay.CodeError):
        replay.encode_record({"seed": 1, "probes": [], "netlist": net})


def test_encode_rejects_bad_input_count():
    net = {"inputs": ["i0"], "outputs": ["o0"], "gates": [], "outputsMap": {"o0": "i0"}}
    with pytest.raises(replay.CodeError):
        replay.encode_record({"seed": 1, "probes": [], "netlist": net})


def test_decode_rejects_illegal_characters():
    with pytest.raises(replay.CodeError):
        replay.decode_record("!!!not-base64url!!!")


def test_decode_rejects_empty_and_overlong():
    with pytest.raises(replay.CodeError):
        replay.decode_record("")
    with pytest.raises(replay.CodeError):
        replay.decode_record("a" * (spec.MAX_CODE_LENGTH + 1))


def test_decode_rejects_tampered_checksum():
    record = {"seed": "2026-01-19", "probes": [1], "netlist": _net_i0()}
    code = replay.encode_record(record)
    tampered = code[:-2] + ("AA" if code[-2:] != "AA" else "BB")
    with pytest.raises(replay.CodeError):
        replay.decode_record(tampered)


def test_decode_rejects_high_bit_seed_nonequivalent():
    # 64 位 seed 高位参与编码：不同 seed 编出的码解码回不同 seedText
    code_a = replay.encode_record({"seed": 1, "probes": [], "netlist": _net_i0()})
    code_b = replay.encode_record({"seed": 0xFFFFFFFFFFFFFFFF, "probes": [], "netlist": _net_i0()})
    assert replay.decode_record(code_a)["seedText"] == "1"
    assert replay.decode_record(code_b)["seedText"] == "18446744073709551615"


def test_build_reveal_plan_layers_from_input_side():
    plan = replay.build_reveal_plan(_level()["netlist"])
    assert plan["layers"][0] == ["g01", "g02"]  # 直接吃输入的门为第 0 层
    assert plan["layerById"]["g04"] == 2  # NOT(AND(...)) → 1 + 上游最大层
    assert plan["cyclic"] == []


def test_build_reveal_plan_sorts_within_layer():
    plan = replay.build_reveal_plan(_level()["netlist"])
    for layer in plan["layers"]:
        assert layer == sorted(layer)


def test_reveal_progress_done():
    plan = replay.build_reveal_plan(_level()["netlist"])
    progress = replay.reveal_progress(plan, len(plan["layers"]))
    assert progress["done"] is True
    assert len(progress["revealed"]) == len(plan["order"])
    partial = replay.reveal_progress(plan, 1)
    assert partial["done"] is False
    assert partial["revealed"] == set(plan["layers"][0])


def test_reveal_sequence_strictly_increasing():
    plan = replay.build_reveal_plan(_level()["netlist"])
    assert replay.reveal_sequence(plan) == list(range(len(plan["layers"])))


# ================================================================== 账本/模式/校验
def test_mode_judge_accepted_stays_rc0():
    level = _level()
    subject = _subject("judge", level=level, draft=_draft_of(level["netlist"]))
    assert _report(subject).exit_code() == EXIT_OK


def test_mode_judge_mismatch_blocks():
    level = _level()
    draft = _draft_of(level["netlist"])
    draft["gates"][0] = {"id": "g01", "type": "OR", "in": ["i0", "i1"], "x": 0, "y": 0}
    subject = _subject("judge", level=level, draft=draft)
    assert _report(subject).exit_code() == EXIT_BLOCKED
    mismatches = _records(subject, spec.RULE_MISMATCH)
    assert len(mismatches) == 1 and mismatches[0].verdict == ERROR


def test_mode_judge_invalid_draft_blocks():
    level = _level()
    draft = {"inputs": level["inputs"], "outputs": level["outputs"], "gates": [], "outputsMap": {name: None for name in level["outputs"]}}
    subject = _subject("judge", level=level, draft=draft)
    assert _report(subject).exit_code() == EXIT_BLOCKED
    assert _records(subject, spec.RULE_DRAFT_INVALID)


def test_mode_generate_success_and_failure():
    ok = _records(_subject("generate", seed="2026-01-19"), spec.RULE_LEVEL_GENERATION)
    assert ok[0].verdict == INFO
    fail = _records(_subject("generate", seed="2026-01-19", options={"gateBudget": 1, "minOptimal": 2}), spec.RULE_LEVEL_GENERATION)
    assert fail[0].verdict == ERROR
    assert _report(_subject("generate", seed="2026-01-19")).exit_code() == EXIT_OK
    assert _report(_subject("generate", seed="2026-01-19", options={"gateBudget": 1, "minOptimal": 2})).exit_code() == EXIT_BLOCKED


def test_mode_replay_roundtrip_records():
    result = generator.generate_level("2026-01-19")
    code = replay.encode_record({"seed": result["level"]["seed"], "probes": [0, 15], "netlist": result["level"]["netlist"]})
    subject = _subject("replay", code=code, observed=None)
    records = _evaluate(subject)
    assert [r for r in records if r.path == "replay.decode"]
    assert [r for r in records if r.path == "replay.reveal"]


def test_mode_replay_mismatch_blocks():
    result = generator.generate_level("2026-01-19")
    code = replay.encode_record({"seed": result["level"]["seed"], "probes": [0], "netlist": result["level"]["netlist"]})
    decoded = replay.decode_record(code)
    level = dict(result["level"], inputs=decoded["netlist"]["inputs"], outputs=decoded["netlist"]["outputs"])
    rows = judge.recompute_probes(level, [15])  # observed 与短码探测序列不一致
    subject = _subject("replay", code=code, observed=rows)
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_mode_replay_bad_code_is_input_error():
    with pytest.raises(ValueError):
        _evaluate(_subject("replay", code="%%broken%%"))


def test_mode_solve_matches_declared_optimal():
    level = _level()
    subject = _subject("solve", level=level)
    assert _report(subject).exit_code() == EXIT_OK
    records = _records(subject, spec.RULE_SETTLEMENT)
    assert "复算一致" in records[0].message


def test_mode_solve_reports_declared_mismatch():
    level = dict(_level(), optimal=99)
    subject = _subject("solve", level=level)
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_mode_audit_runs_judge_and_probes():
    level = _level()
    subject = _subject("audit", level=level, draft=_draft_of(level["netlist"]), probes=[0, 15])
    records = _evaluate(subject)
    assert [r for r in records if r.path == "settlement"]
    assert [r for r in records if r.path == "probes.replay"]


def test_mode_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject("editor"))


def test_judge_requires_draft():
    with pytest.raises(ValueError):
        _evaluate(_subject("judge", level=_level()))


def test_simulate_requires_level():
    with pytest.raises(ValueError):
        _evaluate(_subject("simulate", probes=[0]))


def test_records_unique_ids():
    level = _level()
    subject = _subject("audit", level=level, draft=_draft_of(level["netlist"]), probes=[0, 15])
    report = _report(subject)
    ids = [r.id for r in report.records]
    assert len(ids) == len(set(ids))


def test_determinism_double_run():
    level = _level()
    subject = _subject("audit", level=level, draft=_draft_of(level["netlist"]), probes=[0, 15])
    a = json.dumps(_report(subject).as_dict(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_report(subject).as_dict(), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_exit_codes_cli(tmp_path):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject("solve", level=_level()), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_OK


def test_exit_code_two_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "judge"}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT


def test_exit_code_three_missing_rule(tmp_path):
    basis_path = tmp_path / "empty.basis.json"
    basis_path.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject("solve", level=_level()), ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["check", SLUG, "--input", str(path), "--basis", str(basis_path)])
    assert rc == EXIT_CONTRACT


# ================================================================== 补充：边界与结构
def test_gate_map_helper():
    mapping = netlist.gate_map(_net_i0())
    assert set(mapping) == {"g01"}


def test_validate_netlist_rejects_non_object():
    ok, errors = netlist.validate_netlist(None)
    assert ok is False and errors == ["网表必须是对象"]


def test_validate_netlist_reports_gate_without_id():
    bad = _netlist([{"type": "NOT", "in": ["i0"]}], {"o0": "i0", "o1": "i1", "o2": "i2", "o3": "i3"})
    ok, errors = netlist.validate_netlist(bad)
    assert ok is False and any("缺少字符串 id" in e for e in errors)


def test_topo_order_allows_forward_reference():
    # 允许前向引用：g01 引用后定义的 g02（非环）
    net = _netlist(
        [
            {"id": "g01", "type": "AND", "in": ["i0", "g02"]},
            {"id": "g02", "type": "NOT", "in": ["i1"]},
        ],
        {"o0": "g01", "o1": "i1", "o2": "i2", "o3": "i3"},
    )
    order, cyclic = netlist.topo_order(net)
    assert order == ["g02", "g01"] and cyclic == []


def test_sim_record_trace_default_on():
    result = sim.simulate(_net_i0(), [1, 0, 0, 0])
    assert result["trace"]
    assert result["trace"][0]["tick"] == 0


def test_sim_ticks_counted():
    result = sim.simulate(_net_i0(), [1, 0, 0, 0], {"recordTrace": False})
    assert result["ticks"] >= 2  # 初始全 X → 第 1 tick 稳定


def test_rng_next_u64_in_range():
    stream = rng.create_rng(99)
    for _ in range(8):
        assert 0 <= stream.next_u64() < 2 ** 64


def test_pick_distinct_single():
    stream = rng.create_rng(5)
    picked = rng.pick_distinct(stream, 6, 1)
    assert len(picked) == 1 and 0 <= picked[0] < 6


def test_solve_optimal_empty_masks():
    assert solver.solve_optimal({}, 2)["optimal"] == 0


def test_counted_gates_empty_netlist():
    net = _netlist([], {"o0": "i0", "o1": "i1", "o2": "i2", "o3": "i3"})
    assert solver.counted_gates(net) == 0


def test_generate_level_numeric_seed():
    result = generator.generate_level(11952473959851858958)
    assert result["ok"] is True
    assert result["level"]["seed"] == "11952473959851858958"


def test_generate_level_default_shape():
    result = generator.generate_level("2026-01-19")
    level = result["level"]
    assert len(level["inputs"]) == 4 and len(level["outputs"]) == 4
    assert level["format"] == spec.LEVEL_FORMAT and level["version"] == spec.LEVEL_VERSION


def test_judge_settlement_carries_probes_option():
    level = _level()
    result = judge.judge_submission(_draft_of(level["netlist"]), level, {"probes": 7})
    assert result["settlement"]["probes"] == 7


def test_reveal_plan_single_gate_layer():
    plan = replay.build_reveal_plan(_net_i0())
    assert plan["layers"] == [["g01"]]
    assert plan["orderIndex"]["g01"] == 0


def test_decode_record_rejects_tiny_body():
    # 不足 3 字节无法容纳 CRC → 明确报错
    import base64 as b64

    tiny = b64.urlsafe_b64encode(bytes([1, 2])).decode().rstrip("=")
    with pytest.raises(replay.CodeError):
        replay.decode_record(tiny)


def test_mode_simulate_rejects_negative_vector():
    with pytest.raises(ValueError):
        _evaluate(_subject("simulate", level=_level(), probes=[-1]))


def test_settlement_basis_label_matches_thresholds():
    assert SETTINGS["settlement_basis_label"] == spec.SETTLEMENT_BASIS_LABEL