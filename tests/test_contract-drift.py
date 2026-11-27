"""``contract-drift`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那个函数仍然在、语义仍然是那一套**：
R1–R7 规则映射、三值 severity（相对 policy）、七档方向判定、四态 blast_radius 都是
逐条搬用旧仓 ``tests/test_rules.py`` / ``test_severity.py`` / ``test_policy.py`` /
``test_blast.py`` 的断言（旧仓为 Python；本仓为同一判定）。

**没迁的部分逐条写在 ``docs/contract-drift.md`` §6 的处置表里**（三格式解析、IR 归一、
逐字段 diff、canonical/golden、报告渲染）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 13 个判定层文件实跑 **X = 248 passed**（AST 函数 181）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.contract_drift import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    spec,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    WARN,
    Basis,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "contract-drift"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "contract-drift.basis.json"
THRESHOLDS_PATH = DATA_DIR / "contract-drift.thresholds.json"
SAMPLE = ROOT / "samples" / "contract-drift.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = spec.resolve_params()


def _diff(kind, fmt="proto", direction="FORWARD_OK", **extra):
    item = {"kind": kind, "format": fmt, "direction": direction,
            "stable_path": extra.pop("stable_path", "message.User.field.name")}
    item.update(extra)
    return item


def _subject(differences=None, params=None):
    subject = {"differences": list(differences or [])}
    if params is not None:
        subject["params"] = params
    return subject


def _evaluate(subject=None, basis=None):
    return list(audit.evaluate(subject if subject is not None else _subject(), basis or BASIS))


def _by_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


# ════════════════════════════════════════════════════════════════════════
# 1. 参数与 policy（旧仓 test_policy.py）
# ════════════════════════════════════════════════════════════════════════
class TestSpec:
    def test_default_policy_is_backward(self):
        assert spec.resolve_params(None).policy == "backward"

    def test_default_deploy_order_is_none(self):
        assert spec.resolve_params(None).deploy_order is None

    def test_default_history_is_empty(self):
        assert spec.resolve_params(None).history == ()

    def test_all_seven_policies_accepted(self):
        for policy in spec.POLICIES:
            params = {"policy": policy}
            if policy in spec.TRANSITIVE:
                params["history"] = [[]]
            assert spec.resolve_params(params).policy == policy

    def test_unknown_policy_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"policy": "backwards"})

    def test_deploy_order_override(self):
        assert spec.resolve_params({"deploy_order": "replay"}).deploy_order == "replay"

    def test_unknown_deploy_order_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"deploy_order": "later"})

    def test_unknown_param_key_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"foo": 1})

    def test_non_mapping_params_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params([])

    def test_transitive_requires_history(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"policy": "backward-transitive"})

    def test_history_only_for_transitive(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"policy": "backward", "history": [[]]})

    def test_history_must_be_list(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"policy": "backward-transitive", "history": {}})

    def test_history_items_must_be_lists(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"policy": "backward-transitive", "history": [{}]})

    def test_transitive_with_history_ok(self):
        settings = spec.resolve_params({"policy": "forward-transitive", "history": [[]]})
        assert settings.history == ((),)

    def test_rule_ids_are_r1_to_r7(self):
        assert spec.RULE_IDS == ("R1", "R2", "R3", "R4", "R5", "R6", "R7")

    def test_verdict_table_matches_thresholds_file(self):
        document = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert document["verdicts"] == spec.VERDICT_BY_RULE

    def test_basis_pack_contains_every_rule(self):
        assert set(spec.ALL_RULE_IDS) <= set(BASIS.rule_ids())

    def test_verdict_for_unknown_rule_raises(self):
        with pytest.raises(ValueError):
            spec.verdict_for("nope")

    def test_policies_include_transitive_forms(self):
        assert set(spec.TRANSITIVE) == {
            "backward-transitive", "forward-transitive", "full-transitive"
        }

    def test_directions_are_closed(self):
        assert spec.DIRECTIONS == ("BACKWARD_OK", "FORWARD_OK", "BOTH_OK", "NONE_OK")

    def test_deploy_orders_are_closed(self):
        assert spec.DEPLOY_ORDERS == ("consumers-first", "producers-first", "simultaneous", "replay")

    def test_blast_radius_mapping(self):
        assert spec.BLAST_RADIUS == {
            "consumers-first": "OLD_CONSUMER",
            "producers-first": "NEW_CONSUMER",
            "simultaneous": "BOTH",
            "replay": "REPLAY_ONLY",
        }


class TestAllows:
    def test_backward_accepts_backward_ok(self):
        assert spec.allows("backward", "BACKWARD_OK") is True

    def test_backward_accepts_both_ok(self):
        assert spec.allows("backward", "BOTH_OK") is True

    def test_backward_rejects_forward_ok(self):
        assert spec.allows("backward", "FORWARD_OK") is False

    def test_backward_rejects_none_ok(self):
        assert spec.allows("backward", "NONE_OK") is False

    def test_forward_accepts_forward_ok(self):
        assert spec.allows("forward", "FORWARD_OK") is True

    def test_forward_rejects_backward_ok(self):
        assert spec.allows("forward", "BACKWARD_OK") is False

    def test_full_accepts_both_ok(self):
        assert spec.allows("full", "BOTH_OK") is True

    def test_full_rejects_one_way(self):
        assert spec.allows("full", "BACKWARD_OK") is False

    def test_none_accepts_everything(self):
        for direction in spec.DIRECTIONS:
            assert spec.allows("none", direction) is True

    def test_transitive_uses_same_direction_matrix(self):
        assert spec.allows("backward-transitive", "FORWARD_OK") is False

    @pytest.mark.parametrize("direction,expected", [
        ("BACKWARD_OK", True), ("FORWARD_OK", False), ("BOTH_OK", True), ("NONE_OK", False),
    ])
    def test_backward_matrix(self, direction, expected):
        assert spec.allows("backward", direction) is expected

    @pytest.mark.parametrize("direction,expected", [
        ("BACKWARD_OK", False), ("FORWARD_OK", True), ("BOTH_OK", True), ("NONE_OK", False),
    ])
    def test_forward_matrix(self, direction, expected):
        assert spec.allows("forward", direction) is expected

    @pytest.mark.parametrize("direction,expected", [
        ("BACKWARD_OK", False), ("FORWARD_OK", False), ("BOTH_OK", True), ("NONE_OK", False),
    ])
    def test_full_matrix(self, direction, expected):
        assert spec.allows("full", direction) is expected


# ════════════════════════════════════════════════════════════════════════
# 2. 规则映射 R1–R7（旧仓 test_rules.py）
# ════════════════════════════════════════════════════════════════════════
class TestRuleMapping:
    def test_field_removed_is_r1(self):
        assert audit.rule_of(_diff("field_removed")) == "R1"

    def test_type_changed_is_r2(self):
        assert audit.rule_of(_diff("type_changed")) == "R2"

    def test_cardinality_changed_is_r3(self):
        assert audit.rule_of(_diff("cardinality_changed")) == "R3"

    def test_requiredness_changed_is_r3(self):
        assert audit.rule_of(_diff("requiredness_changed")) == "R3"

    def test_enum_narrowed_is_r4(self):
        assert audit.rule_of(_diff("enum_narrowed")) == "R4"

    def test_enum_widened_is_r4(self):
        assert audit.rule_of(_diff("enum_widened")) == "R4"

    def test_enum_renumbered_is_r4(self):
        assert audit.rule_of(_diff("enum_renumbered")) == "R4"

    def test_enum_changed_is_r4(self):
        assert audit.rule_of(_diff("enum_changed")) == "R4"

    def test_field_number_reused_is_r5(self):
        assert audit.rule_of(_diff("field_number_reused")) == "R5"

    def test_reserved_conflict_is_r5(self):
        assert audit.rule_of(_diff("reserved_conflict")) == "R5"

    def test_cross_message_reuse_is_r5(self):
        assert audit.rule_of(_diff("cross_message_reuse")) == "R5"

    def test_oneof_moved_is_r6(self):
        assert audit.rule_of(_diff("oneof_moved")) == "R6"

    def test_default_changed_is_r7(self):
        assert audit.rule_of(_diff("default_changed")) == "R7"

    def test_field_added_required_is_r3(self):
        assert audit.rule_of(_diff("field_added", direction="BACKWARD_OK")) == "R3"

    def test_field_added_optional_is_not_a_rule(self):
        assert audit.rule_of(_diff("field_added", direction="FORWARD_OK")) is None

    def test_unknown_kind_is_not_a_rule(self):
        assert audit.rule_of(_diff("unknown_kind")) is None


class TestSeverity:
    def test_r1_default_breaking(self):
        assert audit.severity_of(_diff("field_removed", direction="FORWARD_OK"), "R1", "backward") == "breaking"

    def test_r1_allowed_becomes_non_breaking(self):
        assert audit.severity_of(_diff("field_removed", direction="BACKWARD_OK"), "R1", "backward") == "non-breaking"

    def test_r2_default_breaking(self):
        assert audit.severity_of(_diff("type_changed", direction="FORWARD_OK"), "R2", "backward") == "breaking"

    def test_r2_union_widened_is_non_breaking(self):
        assert audit.severity_of(_diff("type_changed", detail="union_widened", direction="FORWARD_OK"), "R2", "backward") == "non-breaking"

    def test_r2_wire_compatible_is_runtime(self):
        assert audit.severity_of(_diff("type_changed", detail="wire_compatible"), "R2", "backward") == "runtime-dependent"

    def test_r2_promotion_is_runtime(self):
        assert audit.severity_of(_diff("type_changed", detail="promotion"), "R2", "backward") == "runtime-dependent"

    def test_r2_widened_is_runtime(self):
        assert audit.severity_of(_diff("type_changed", detail="widened"), "R2", "backward") == "runtime-dependent"

    def test_r3_default_breaking(self):
        assert audit.severity_of(_diff("cardinality_changed"), "R3", "backward") == "breaking"

    def test_r4_default_runtime(self):
        assert audit.severity_of(_diff("enum_narrowed"), "R4", "backward") == "runtime-dependent"

    def test_r5_default_breaking(self):
        assert audit.severity_of(_diff("field_number_reused"), "R5", "backward") == "breaking"

    def test_r6_default_runtime(self):
        assert audit.severity_of(_diff("oneof_moved"), "R6", "backward") == "runtime-dependent"

    def test_r7_default_non_breaking(self):
        assert audit.severity_of(_diff("default_changed"), "R7", "backward") == "non-breaking"

    def test_policy_none_makes_everything_non_breaking(self):
        for kind, rule in spec.KIND_RULES.items():
            assert audit.severity_of(_diff(kind), rule, "none") == "non-breaking"

    def test_allowed_direction_beats_detail_override(self):
        assert audit.severity_of(_diff("type_changed", detail="wire_compatible", direction="BACKWARD_OK"), "R2", "backward") == "non-breaking"


class TestRulesTable:
    def test_repair_actions(self):
        assert {rule: spec.RULE_META[rule]["repair_action"] for rule in spec.RULE_IDS} == {
            "R1": "reserve", "R2": "bump-and-version", "R3": "add-default",
            "R4": "bump-and-version", "R5": "reserve", "R6": "add-branch", "R7": "add-default",
        }

    def test_default_severities(self):
        assert {rule: spec.RULE_META[rule]["default"] for rule in spec.RULE_IDS} == {
            "R1": "breaking", "R2": "breaking", "R3": "breaking",
            "R4": "runtime-dependent", "R5": "breaking", "R6": "runtime-dependent",
            "R7": "non-breaking",
        }

    def test_r5_na_for_avro(self):
        assert "R5" in spec.NOT_APPLICABLE["avro"]

    def test_r6_na_for_avro(self):
        assert "R6" in spec.NOT_APPLICABLE["avro"]

    def test_r5_na_for_jsonschema(self):
        assert "R5" in spec.NOT_APPLICABLE["jsonschema"]

    def test_proto_has_no_na(self):
        assert spec.NOT_APPLICABLE["proto"] == {}

    def test_r1_evidence_proto(self):
        assert spec.EVIDENCE["R1"]["proto"] == "field_number_missing_without_reserved"

    def test_r2_evidence_avro(self):
        assert spec.EVIDENCE["R2"]["avro"] == "type_or_logical_type_change"

    def test_r3_evidence_jsonschema(self):
        assert spec.EVIDENCE["R3"]["jsonschema"] == "required_list_added"

    def test_r4_evidence_proto(self):
        assert spec.EVIDENCE["R4"]["proto"] == "enum_value_removed_or_renamed"

    def test_r5_only_proto(self):
        assert set(spec.EVIDENCE["R5"]) == {"proto"}

    def test_r6_proto_and_jsonschema(self):
        assert set(spec.EVIDENCE["R6"]) == {"proto", "jsonschema"}

    def test_r7_all_formats(self):
        assert set(spec.EVIDENCE["R7"]) == {"proto", "avro", "jsonschema"}

    def test_organ_rule_ids(self):
        assert spec.RULE_FOR_ORGAN == {
            "R1": "contract-r1", "R2": "contract-r2", "R3": "contract-r3",
            "R4": "contract-r4", "R5": "contract-r5", "R6": "contract-r6",
            "R7": "contract-r7",
        }


# ════════════════════════════════════════════════════════════════════════
# 3. 方向判定与 blast_radius
# ════════════════════════════════════════════════════════════════════════
class TestJudge:
    def test_none_policy_is_compatible(self):
        settings = spec.resolve_params({"policy": "none"})
        verdict, _ = audit.judge(settings, [[_diff("field_removed", direction="NONE_OK")]])
        assert verdict == "compatible"

    def test_backward_rejects_forward_ok(self):
        verdict, reason = audit.judge(SETTINGS, [[_diff("field_removed", direction="FORWARD_OK")]])
        assert verdict == "breaking" and reason == "field_removed"

    def test_backward_accepts_backward_ok(self):
        assert audit.judge(SETTINGS, [[_diff("field_removed", direction="BACKWARD_OK")]])[0] == "compatible"

    def test_forward_accepts_forward_ok(self):
        settings = spec.resolve_params({"policy": "forward"})
        assert audit.judge(settings, [[_diff("field_removed", direction="FORWARD_OK")]])[0] == "compatible"

    def test_full_rejects_one_way(self):
        settings = spec.resolve_params({"policy": "full"})
        assert audit.judge(settings, [[_diff("field_removed", direction="BACKWARD_OK")]])[0] == "breaking"

    def test_full_accepts_both_ok(self):
        settings = spec.resolve_params({"policy": "full"})
        assert audit.judge(settings, [[_diff("field_removed", direction="BOTH_OK")]])[0] == "compatible"

    def test_transitive_sees_history(self):
        settings = spec.resolve_params({"policy": "backward-transitive", "history": [[_diff("field_removed", direction="FORWARD_OK")]]})
        assert audit.judge(settings, [[]])[0] == "breaking"

    def test_transitive_clean_history(self):
        settings = spec.resolve_params({"policy": "backward-transitive", "history": [[_diff("field_removed", direction="BACKWARD_OK")]]})
        assert audit.judge(settings, [[]])[0] == "compatible"

    def test_empty_differences_compatible(self):
        assert audit.judge(SETTINGS, [[]])[0] == "compatible"

    def test_none_direction_is_breaking(self):
        assert audit.judge(SETTINGS, [[_diff("field_removed", direction="NONE_OK")]])[0] == "breaking"


class TestBlast:
    def test_consumers_first_is_old_consumer(self):
        records = _evaluate(_subject([_diff("field_removed")], {"deploy_order": "consumers-first"}))
        assert _by_rule(records, "contract-r1")[0].evidence["blast_radius"] == "OLD_CONSUMER"

    def test_producers_first_is_new_consumer(self):
        records = _evaluate(_subject([_diff("field_removed")], {"deploy_order": "producers-first"}))
        assert _by_rule(records, "contract-r1")[0].evidence["blast_radius"] == "NEW_CONSUMER"

    def test_simultaneous_is_both(self):
        records = _evaluate(_subject([_diff("field_removed")], {"deploy_order": "simultaneous"}))
        assert _by_rule(records, "contract-r1")[0].evidence["blast_radius"] == "BOTH"

    def test_replay_is_replay_only(self):
        records = _evaluate(_subject([_diff("field_removed")], {"deploy_order": "replay"}))
        assert _by_rule(records, "contract-r1")[0].evidence["blast_radius"] == "REPLAY_ONLY"

    def test_missing_deploy_order_is_null(self):
        records = _evaluate(_subject([_diff("field_removed")]))
        assert _by_rule(records, "contract-r1")[0].evidence["blast_radius"] is None

    def test_missing_deploy_order_note(self):
        summary = _by_rule(_evaluate(_subject([_diff("field_removed")])), "contract-summary")[0]
        assert spec.NOT_GIVEN_NOTE in summary.evidence["notes"]

    def test_summary_carries_blast_radius(self):
        summary = _by_rule(_evaluate(_subject([_diff("field_removed")], {"deploy_order": "replay"})), "contract-summary")[0]
        assert summary.evidence["blast_radius"] == "REPLAY_ONLY"

    def test_na_rows_have_no_blast_radius(self):
        records = _evaluate(_subject([_diff("field_removed", fmt="avro")], {"deploy_order": "replay"}))
        na = [record for record in records if record.path.startswith("<na:")]
        assert all(record.evidence["blast_radius"] is None for record in na)


# ════════════════════════════════════════════════════════════════════════
# 4. 器官编排（evaluate）
# ════════════════════════════════════════════════════════════════════════
class TestEvaluate:
    def test_sample_is_clean(self):
        records = _evaluate({"differences": json.loads(SAMPLE.read_text(encoding="utf-8"))["differences"]})
        assert [record.rule_id for record in records] == ["contract-r7", "contract-summary"]

    def test_sample_exit_zero(self):
        subject = json.loads(SAMPLE.read_text(encoding="utf-8"))
        report = Report(product="byteproof", organ=SLUG, organ_version="1", subject="x", records=_evaluate(subject))
        assert report.exit_code() == EXIT_OK

    def test_r1_breaking_blocks(self):
        subject = _subject([_diff("field_removed", direction="FORWARD_OK")])
        records = _evaluate(subject)
        assert _by_rule(records, "contract-r1")[0].verdict == ERROR
        assert _by_rule(records, "contract-gate")[0].verdict == ERROR

    def test_r1_accepted_is_info(self):
        subject = _subject([_diff("field_removed", direction="BACKWARD_OK")])
        records = _evaluate(subject)
        assert _by_rule(records, "contract-r1")[0].verdict == INFO
        assert _by_rule(records, "contract-gate") == []

    def test_r2_runtime_is_warn(self):
        subject = _subject([_diff("type_changed", detail="wire_compatible", direction="FORWARD_OK")])
        assert _by_rule(_evaluate(subject), "contract-r2")[0].verdict == WARN

    def test_r2_union_widened_is_info(self):
        subject = _subject([_diff("type_changed", detail="union_widened", direction="FORWARD_OK")])
        assert _by_rule(_evaluate(subject), "contract-r2")[0].verdict == INFO

    def test_r3_record(self):
        subject = _subject([_diff("cardinality_changed")])
        assert _by_rule(_evaluate(subject), "contract-r3")

    def test_r4_record(self):
        subject = _subject([_diff("enum_narrowed")])
        assert _by_rule(_evaluate(subject), "contract-r4")

    def test_r5_record(self):
        subject = _subject([_diff("field_number_reused", number=3)])
        assert _by_rule(_evaluate(subject), "contract-r5")[0].verdict == ERROR

    def test_r5_repair_hint_contains_number(self):
        subject = _subject([_diff("field_number_reused", number=3)])
        assert "3" in _by_rule(_evaluate(subject), "contract-r5")[0].evidence["repair_hint"]

    def test_r6_record(self):
        subject = _subject([_diff("oneof_moved")])
        assert _by_rule(_evaluate(subject), "contract-r6")

    def test_r7_record(self):
        subject = _subject([_diff("default_changed", direction="BACKWARD_OK")])
        assert _by_rule(_evaluate(subject), "contract-r7")

    def test_r7_default_is_non_breaking_even_when_not_allowed(self):
        subject = _subject([_diff("default_changed", direction="FORWARD_OK")])
        record = _by_rule(_evaluate(subject), "contract-r7")[0]
        assert record.verdict == INFO
        # 但 verdict 仍按方向判：policy=backward 不接受 FORWARD_OK
        assert _by_rule(_evaluate(subject), "contract-gate")

    def test_field_added_required_is_r3(self):
        subject = _subject([_diff("field_added", direction="BACKWARD_OK")])
        assert _by_rule(_evaluate(subject), "contract-r3")

    def test_field_added_optional_has_no_rule_record(self):
        subject = _subject([_diff("field_added", direction="FORWARD_OK")])
        assert not any(record.rule_id.startswith("contract-r") and record.rule_id != "contract-r" for record in _evaluate(subject))

    def test_unknown_kind_has_no_rule_record(self):
        subject = _subject([_diff("unknown_kind")])
        rules = [record.rule_id for record in _evaluate(subject)]
        assert "contract-r1" not in rules and "contract-summary" in rules

    def test_policy_none_never_blocks(self):
        subject = _subject([_diff("field_removed", direction="NONE_OK")], {"policy": "none"})
        assert _by_rule(_evaluate(subject), "contract-gate") == []

    def test_avro_has_r5_na(self):
        subject = _subject([_diff("default_changed", fmt="avro")])
        assert _by_rule(_evaluate(subject), "contract-r5")

    def test_avro_has_r6_na(self):
        subject = _subject([_diff("default_changed", fmt="avro")])
        assert _by_rule(_evaluate(subject), "contract-r6")

    def test_jsonschema_has_r5_na(self):
        subject = _subject([_diff("default_changed", fmt="jsonschema")])
        assert _by_rule(_evaluate(subject), "contract-r5")

    def test_jsonschema_has_no_r6_na(self):
        subject = _subject([_diff("default_changed", fmt="jsonschema")])
        assert _by_rule(_evaluate(subject), "contract-r6") == []

    def test_proto_has_no_na_rows(self):
        subject = _subject([_diff("default_changed", fmt="proto")])
        rules = [record.rule_id for record in _evaluate(subject)]
        assert "contract-r5" not in rules and "contract-r6" not in rules

    def test_na_rows_are_info(self):
        subject = _subject([_diff("default_changed", fmt="avro")])
        assert _by_rule(_evaluate(subject), "contract-r5")[0].verdict == INFO

    def test_summary_counts(self):
        subject = _subject([
            _diff("field_removed", direction="FORWARD_OK"),
            _diff("default_changed", direction="BACKWARD_OK"),
        ])
        summary = _by_rule(_evaluate(subject), "contract-summary")[0]
        assert summary.evidence["counts"] == {"breaking": 1, "runtime-dependent": 0, "non-breaking": 1}

    def test_summary_verdict(self):
        subject = _subject([_diff("field_removed", direction="FORWARD_OK")])
        summary = _by_rule(_evaluate(subject), "contract-summary")[0]
        assert summary.evidence["verdict"] == "breaking"

    def test_all_records_have_basis(self):
        subject = _subject([_diff("field_removed")])
        for record in _evaluate(subject):
            assert record.basis is not None and record.basis.complete
            assert record.basis.rule_id == record.rule_id

    def test_ids_are_unique(self):
        subject = _subject([_diff("field_removed"), _diff("field_removed")])
        ids = [record.id for record in _evaluate(subject)]
        assert len(ids) == len(set(ids))

    def test_duplicate_paths_get_ordinals(self):
        subject = _subject([_diff("field_removed"), _diff("field_removed")])
        paths = [record.path for record in _by_rule(_evaluate(subject), "contract-r1")]
        assert paths[0] == "message.User.field.name#1" and paths[1].endswith("#2")

    def test_differences_must_be_list(self):
        with pytest.raises(ValueError):
            _evaluate({"differences": "x"})

    def test_difference_must_be_mapping(self):
        with pytest.raises(ValueError):
            _evaluate({"differences": ["x"]})

    def test_bad_format_rejected(self):
        with pytest.raises(ValueError):
            _evaluate({"differences": [{"kind": "field_removed", "format": "yaml"}]})

    def test_bad_direction_rejected(self):
        with pytest.raises(ValueError):
            _evaluate({"differences": [_diff("field_removed", direction="SIDEWAYS")]})

    def test_missing_kind_rejected(self):
        with pytest.raises(ValueError):
            _evaluate({"differences": [{"format": "proto"}]})

    def test_transitive_without_history_rejected(self):
        with pytest.raises(ValueError):
            _evaluate(_subject([], {"policy": "backward-transitive"}))

    def test_history_group_is_normalized(self):
        settings = {"policy": "backward-transitive", "history": [[_diff("field_removed", direction="FORWARD_OK")]]}
        assert _by_rule(_evaluate(_subject([], settings)), "contract-gate")

    def test_report_is_deterministic(self):
        subject = _subject([_diff("field_removed")])
        def build():
            return Report(product="byteproof", organ=SLUG, organ_version="1", subject="x",
                          records=_evaluate(subject)).as_dict()
        assert json.dumps(build(), ensure_ascii=False) == json.dumps(build(), ensure_ascii=False)

    @pytest.mark.parametrize("rule,expected", [
        ("contract-r1", ERROR), ("contract-r2", ERROR), ("contract-r3", ERROR),
        ("contract-r4", WARN), ("contract-r5", ERROR), ("contract-r6", WARN),
        ("contract-r7", INFO), ("contract-gate", ERROR), ("contract-summary", INFO),
    ])
    def test_verdicts_are_pinned(self, rule, expected):
        assert spec.verdict_for(rule) == expected


# ════════════════════════════════════════════════════════════════════════
# 5. 唯一入口与文档
# ════════════════════════════════════════════════════════════════════════
class TestCliDocs:
    def test_list_includes_organ(self, capsys):
        assert cli.main(["list"]) == EXIT_OK
        assert SLUG in capsys.readouterr().out

    def test_sample_returns_zero(self):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE)]) == EXIT_OK

    def test_sample_json(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["blocking"] == 0

    def test_breaking_subject_returns_one(self, tmp_path):
        subject = _subject([_diff("field_removed", direction="FORWARD_OK")])
        path = tmp_path / "breaking.json"
        path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_BLOCKED

    def test_missing_file_returns_two(self):
        assert cli.main(["check", SLUG, "--input", "no-such.json"]) == EXIT_INPUT

    def test_missing_field_returns_two(self, tmp_path):
        path = tmp_path / "missing.json"
        path.write_text(json.dumps({"params": {}}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT

    def test_empty_basis_returns_three(self, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text('{"version": "1", "rules": []}', encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(empty)]) == EXIT_CONTRACT

    def test_unknown_slug_returns_three(self):
        assert cli.main(["check", "no-such", "--input", str(SAMPLE)]) == EXIT_CONTRACT

    def test_output_is_deterministic(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        first = capsys.readouterr().out
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        assert capsys.readouterr().out == first

    def test_wiring_pack(self):
        assert get(SLUG) is PACK and PACK.input_fields == ("differences",)

    def test_wiring_version(self):
        assert PACK.version == ORGAN_VERSION == "1"

    def test_builtin_modules_sorted(self):
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_builtin_modules_include_slug(self):
        assert "contract_drift" in BUILTIN_MODULES

    def test_organ_is_package(self):
        assert (SRC / "byteproof" / "auditors" / "contract_drift" / "__init__.py").is_file()

    def test_no_clock_calls(self):
        for name in ("audit.py", "spec.py"):
            text = (SRC / "byteproof" / "auditors" / "contract_drift" / name).read_text(encoding="utf-8")
            assert "datetime.now(" not in text and "date.today(" not in text and "time.time(" not in text

    def test_no_network_imports(self):
        tree = ast.parse((SRC / "byteproof" / "auditors" / "contract_drift" / "audit.py").read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "socket" not in names and "requests" not in names and "urllib" not in names

    def test_docs_page_exists(self):
        assert (ROOT / "docs" / (SLUG + ".md")).is_file()

    def test_docs_page_has_four_criteria(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        for marker in ("X = 248", "判据 4", "处置表", "口径差"):
            assert marker in text

    def test_docs_page_names_sample(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        assert "samples/contract-drift.minimal.json" in text


# ════════════════════════════════════════════════════════════════════════
# 6. 方向矩阵逐格（七档 policy × 四个 direction）
# ════════════════════════════════════════════════════════════════════════
class TestDirectionMatrix:
    def test_backward_accepts_backward(self):
        assert spec.allows("backward", "BACKWARD_OK")

    def test_backward_accepts_both(self):
        assert spec.allows("backward", "BOTH_OK")

    def test_backward_rejects_forward(self):
        assert not spec.allows("backward", "FORWARD_OK")

    def test_backward_rejects_none(self):
        assert not spec.allows("backward", "NONE_OK")

    def test_backward_transitive_accepts_backward(self):
        assert spec.allows("backward-transitive", "BACKWARD_OK")

    def test_backward_transitive_accepts_both(self):
        assert spec.allows("backward-transitive", "BOTH_OK")

    def test_backward_transitive_rejects_forward(self):
        assert not spec.allows("backward-transitive", "FORWARD_OK")

    def test_backward_transitive_rejects_none(self):
        assert not spec.allows("backward-transitive", "NONE_OK")

    def test_forward_accepts_forward(self):
        assert spec.allows("forward", "FORWARD_OK")

    def test_forward_accepts_both(self):
        assert spec.allows("forward", "BOTH_OK")

    def test_forward_rejects_backward(self):
        assert not spec.allows("forward", "BACKWARD_OK")

    def test_forward_rejects_none(self):
        assert not spec.allows("forward", "NONE_OK")

    def test_forward_transitive_accepts_forward(self):
        assert spec.allows("forward-transitive", "FORWARD_OK")

    def test_forward_transitive_accepts_both(self):
        assert spec.allows("forward-transitive", "BOTH_OK")

    def test_forward_transitive_rejects_backward(self):
        assert not spec.allows("forward-transitive", "BACKWARD_OK")

    def test_forward_transitive_rejects_none(self):
        assert not spec.allows("forward-transitive", "NONE_OK")

    def test_full_accepts_both(self):
        assert spec.allows("full", "BOTH_OK")

    def test_full_rejects_backward(self):
        assert not spec.allows("full", "BACKWARD_OK")

    def test_full_rejects_forward(self):
        assert not spec.allows("full", "FORWARD_OK")

    def test_full_rejects_none(self):
        assert not spec.allows("full", "NONE_OK")

    def test_full_transitive_accepts_both(self):
        assert spec.allows("full-transitive", "BOTH_OK")

    def test_full_transitive_rejects_backward(self):
        assert not spec.allows("full-transitive", "BACKWARD_OK")

    def test_full_transitive_rejects_forward(self):
        assert not spec.allows("full-transitive", "FORWARD_OK")

    def test_full_transitive_rejects_none(self):
        assert not spec.allows("full-transitive", "NONE_OK")

    def test_none_accepts_backward(self):
        assert spec.allows("none", "BACKWARD_OK")

    def test_none_accepts_forward(self):
        assert spec.allows("none", "FORWARD_OK")

    def test_none_accepts_both(self):
        assert spec.allows("none", "BOTH_OK")

    def test_none_accepts_none(self):
        assert spec.allows("none", "NONE_OK")

    @pytest.mark.parametrize("rule,expected", [
        ("R1", "field_number_missing_without_reserved"),
        ("R2", "wire_incompatible_type_change"),
        ("R3", "label_change_or_new_required_without_default"),
        ("R4", "enum_value_removed_or_renamed"),
        ("R5", "field_number_reused_or_conflicts_with_reserved"),
        ("R6", "field_entered_or_left_oneof"),
        ("R7", "default_value_changed"),
    ])
    def test_proto_evidence_matrix(self, rule, expected):
        assert audit.format_evidence(rule, "proto", "x", None) == expected

    @pytest.mark.parametrize("rule,expected", [
        ("R1", "field_absent_or_renamed_without_alias"),
        ("R2", "type_or_logical_type_change"),
        ("R3", "new_field_without_default"),
        ("R4", "symbol_removed"),
        ("R7", "default_changed"),
    ])
    def test_avro_evidence_matrix(self, rule, expected):
        assert audit.format_evidence(rule, "avro", "x", None) == expected

    @pytest.mark.parametrize("rule,expected", [
        ("R1", "property_absent_or_removed_from_required"),
        ("R2", "type_or_format_change"),
        ("R3", "required_list_added"),
        ("R4", "enum_list_narrowed"),
        ("R6", "oneof_or_anyof_branch_moved"),
        ("R7", "default_changed"),
    ])
    def test_jsonschema_evidence_matrix(self, rule, expected):
        assert audit.format_evidence(rule, "jsonschema", "x", None) == expected

    @pytest.mark.parametrize("kind,expected", [
        ("enum_widened", "enum_value_added"),
        ("enum_renumbered", "enum_value_renumbered"),
    ])
    def test_proto_enum_detail_evidence(self, kind, expected):
        assert audit.format_evidence("R4", "proto", kind, None) == expected

    @pytest.mark.parametrize("detail,expected", [
        ("union_widened", "union_branch_added"),
        ("wire_compatible", "wire_compatible_type_change"),
    ])
    def test_avro_detail_evidence(self, detail, expected):
        assert audit.format_evidence("R2", "avro", "type_changed", detail) == expected

    @pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R5", "R6", "R7"])
    def test_repair_action_is_non_empty(self, rule):
        assert audit.repair_hint(rule, {"number": 1, "field": "f"})

    @pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R5", "R6", "R7"])
    def test_rule_meta_has_repair_action(self, rule):
        assert spec.RULE_META[rule]["repair_action"]

    @pytest.mark.parametrize("rule", ["R1", "R2", "R3", "R4", "R5", "R6", "R7"])
    def test_rule_meta_has_default(self, rule):
        assert spec.RULE_META[rule]["default"] in ("breaking", "runtime-dependent", "non-breaking")

    def test_severity_table_has_only_r2(self):
        assert set(spec.SEVERITY_BY_DETAIL) == {"R2"}

    def test_every_kind_maps_to_known_rule(self):
        assert set(spec.KIND_RULES.values()) <= set(spec.RULE_IDS)

    def test_na_reasons_are_non_empty(self):
        for fmt in spec.NOT_APPLICABLE:
            for reason in spec.NOT_APPLICABLE[fmt].values():
                assert reason

    def test_summary_notes_without_order(self):
        summary = _by_rule(_evaluate(_subject([_diff("default_changed", direction="BACKWARD_OK")])), "contract-summary")[0]
        assert summary.evidence["notes"] == [spec.NOT_GIVEN_NOTE]

    def test_summary_notes_empty_with_order(self):
        summary = _by_rule(_evaluate(_subject([_diff("default_changed", direction="BACKWARD_OK")], {"deploy_order": "replay"})), "contract-summary")[0]
        assert summary.evidence["notes"] == []

    def test_summary_policy_recorded(self):
        summary = _by_rule(_evaluate(_subject([], {"policy": "none"})), "contract-summary")[0]
        assert summary.evidence["policy"] == "none"

    def test_empty_subject_still_has_summary(self):
        records = _evaluate(_subject([]))
        assert [record.rule_id for record in records] == ["contract-summary"]