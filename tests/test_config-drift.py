"""``config-drift`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那个函数仍然在、语义仍然是那一套**：
值族归一化（quantity/duration/decimal/bool/null）、六类影响分类、semver 子类、gate
语义都是逐条搬用旧仓 ``internal/value/value_test.go`` / ``internal/classify/classify_test.go``
的断言（旧仓为 Go；本仓用 Python 重写判定）。

**没迁的部分逐条写在 ``docs/config-drift.md`` §6 的处置表里**（格式解析、结构无关 diff、
默认值 profile、CLI 渲染、golden harness）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 6 个判定层包 `go test` 实跑 **X = 79 passed**
（含子测试；顶层 66 个 `func Test`）。
"""

from __future__ import annotations

import ast
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.config_drift import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    classify,
    spec,
    value,
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

SLUG = "config-drift"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "config-drift.basis.json"
THRESHOLDS_PATH = DATA_DIR / "config-drift.thresholds.json"
SAMPLE = ROOT / "samples" / "config-drift.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = spec.resolve_params()


def _node(family, raw):
    return {"family": family, "raw": raw}


def _entry(path, kind="changed", left=None, right=None, reason=None):
    entry = {"path": path, "kind": kind}
    if left is not None:
        entry["left"] = left
    if right is not None:
        entry["right"] = right
    if reason is not None:
        entry["reason"] = reason
    return entry


def _subject(entries, params=None):
    subject = {"entries": entries}
    if params is not None:
        subject["params"] = params
    return subject


def _evaluate(subject=None, basis=None):
    if subject is None:
        subject = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return list(audit.evaluate(subject, basis or BASIS))


def _by_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


def _classified(entries):
    return classify.apply([classify.normalize_entry(entry, index) for index, entry in enumerate(entries)])


# ════════════════════════════════════════════════════════════════════════
# 1. 值族代数（旧仓 value_test.go）
# ════════════════════════════════════════════════════════════════════════
class TestQuantity:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1", Fraction(1)),
            ("1Ki", Fraction(1024)),
            ("1Mi", Fraction(1024 ** 2)),
            ("1Gi", Fraction(1024 ** 3)),
            ("1k", Fraction(1000)),
            ("1M", Fraction(1000 ** 2)),
            ("500m", Fraction(1, 2)),
            ("1e3", Fraction(1000)),
            ("1.5Gi", Fraction(3, 2) * Fraction(1024 ** 3)),
            ("-2Mi", Fraction(-2 * 1024 ** 2)),
            ("+1Ki", Fraction(1024)),
        ],
    )
    def test_parse_quantity(self, text, expected):
        assert value.parse_quantity(text) == expected

    def test_1gi_is_not_1000m(self):
        assert value.parse_quantity("1Gi") != value.parse_quantity("1000M")

    def test_mb_is_indeterminate(self):
        with pytest.raises(value.Indeterminate) as exc:
            value.parse_quantity("1MB")
        assert exc.value.reason == value.REASON_AMBIGUOUS_UNIT

    def test_mib_is_indeterminate(self):
        with pytest.raises(value.Indeterminate):
            value.parse_quantity("1MiB")

    def test_plain_b_is_indeterminate(self):
        with pytest.raises(value.Indeterminate):
            value.parse_quantity("1B")

    def test_exponent_and_suffix_are_exclusive(self):
        with pytest.raises(value.ValueError_):
            value.parse_quantity("1e3Mi")

    def test_empty_quantity_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_quantity("")

    def test_sign_without_number_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_quantity("-")

    def test_bad_number_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_quantity("abcGi")


class TestDuration:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1ns", Fraction(1)),
            ("1us", Fraction(1000)),
            ("1µs", Fraction(1000)),
            ("1ms", Fraction(1000000)),
            ("1s", Fraction(1000000000)),
            ("1m", Fraction(60000000000)),
            ("1h", Fraction(3600000000000)),
            ("1h30m", Fraction(5400000000000)),
            ("-1s", Fraction(-1000000000)),
            ("0", Fraction(0)),
            ("0s", Fraction(0)),
        ],
    )
    def test_parse_duration(self, text, expected):
        assert value.parse_duration(text) == expected

    def test_unknown_unit_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_duration("1d")

    def test_empty_duration_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_duration("")

    def test_missing_number_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_duration("s")

    def test_fractional_duration(self):
        assert value.parse_duration("1.5h") == Fraction(5400000000000)


class TestDecimalBool:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1", Fraction(1)),
            ("1.0", Fraction(1)),
            ("1e3", Fraction(1000)),
            ("1.50", Fraction(3, 2)),
            ("-0.5", Fraction(-1, 2)),
        ],
    )
    def test_parse_decimal(self, text, expected):
        assert value.parse_decimal(text) == expected

    def test_bad_decimal_is_error(self):
        with pytest.raises(value.ValueError_):
            value.parse_decimal("abc")

    @pytest.mark.parametrize("text", ["yes", "on", "TRUE", "y", "true"])
    def test_parse_bool_true(self, text):
        assert value.parse_bool(text) is True

    @pytest.mark.parametrize("text", ["no", "off", "FALSE", "n", "false"])
    def test_parse_bool_false(self, text):
        assert value.parse_bool(text) is False

    def test_parse_bad_bool(self):
        with pytest.raises(value.ValueError_):
            value.parse_bool("maybe")


class TestCanonical:
    def test_null_absent(self):
        canonical = value.canonicalize(None)
        assert canonical.family == value.FAMILY_NULL and canonical.state == "absent"

    def test_null_explicit(self):
        assert value.canonicalize({"family": "null", "state": "null"}).state == "null"

    def test_null_empty_string(self):
        assert value.canonicalize({"family": "null", "state": "empty"}).state == "empty"

    def test_null_bad_state(self):
        with pytest.raises(value.ValueError_):
            value.canonicalize({"family": "null", "state": "other"})

    def test_unknown_family_is_indeterminate(self):
        with pytest.raises(value.Indeterminate) as exc:
            value.canonicalize({"family": "unknown", "raw": "${var.x}"})
        assert exc.value.reason == value.REASON_UNKNOWN_FAMILY

    def test_unknown_family_reason_is_kept(self):
        with pytest.raises(value.Indeterminate) as exc:
            value.canonicalize({"family": "unknown", "raw": "x", "reason": value.REASON_UNEVALUATED})
        assert exc.value.reason == value.REASON_UNEVALUATED

    def test_string(self):
        assert value.canonicalize({"family": "string", "raw": "x"}).text == "x"

    def test_bad_family(self):
        with pytest.raises(value.ValueError_):
            value.canonicalize({"family": "nope", "raw": "x"})

    def test_missing_raw(self):
        with pytest.raises(value.ValueError_):
            value.canonicalize({"family": "quantity"})

    def test_non_mapping_node(self):
        with pytest.raises(value.ValueError_):
            value.canonicalize("1Gi")

    def test_compare_quantity(self):
        equal, _ = value.compare(
            value.canonicalize(_node("quantity", "1Gi")),
            value.canonicalize(_node("quantity", "1024Mi")),
        )
        assert equal is True

    def test_compare_quantity_not_equal(self):
        equal, _ = value.compare(
            value.canonicalize(_node("quantity", "1Gi")),
            value.canonicalize(_node("quantity", "1000M")),
        )
        assert equal is False

    def test_compare_duration(self):
        equal, _ = value.compare(
            value.canonicalize(_node("duration", "1h")),
            value.canonicalize(_node("duration", "60m")),
        )
        assert equal is True

    def test_compare_decimal(self):
        equal, _ = value.compare(
            value.canonicalize(_node("decimal", "1.0")),
            value.canonicalize(_node("decimal", "1")),
        )
        assert equal is True

    def test_compare_bool(self):
        equal, _ = value.compare(
            value.canonicalize(_node("bool", "yes")),
            value.canonicalize(_node("bool", "true")),
        )
        assert equal is True

    def test_compare_null(self):
        equal, _ = value.compare(
            value.canonicalize({"family": "null", "state": "absent"}),
            value.canonicalize({"family": "null", "state": "null"}),
        )
        assert equal is False

    def test_compare_string(self):
        equal, _ = value.compare(
            value.canonicalize(_node("string", "a")),
            value.canonicalize(_node("string", "b")),
        )
        assert equal is False

    def test_compare_different_families(self):
        equal, _ = value.compare(
            value.canonicalize(_node("decimal", "1")),
            value.canonicalize(_node("string", "1")),
        )
        assert equal is False


# ════════════════════════════════════════════════════════════════════════
# 2. 分类（旧仓 classify_test.go）
# ════════════════════════════════════════════════════════════════════════
class TestClassify:
    def _one(self, entry):
        return _classified([entry])["entries"][0]

    def test_image_major(self):
        item = self._one(_entry("/spec/template/spec/containers/0/image", left=_node("string", "registry.io/app:1.2.3"), right=_node("string", "registry.io/app:2.0.0")))
        assert (item["class"], item["subclass"]) == (spec.IMAGE_CHANGE, "major")

    def test_image_minor(self):
        item = self._one(_entry("/spec/template/spec/containers/0/image", left=_node("string", "registry.io/app:1.2.3"), right=_node("string", "registry.io/app:1.3.0")))
        assert item["subclass"] == "minor"

    def test_image_patch(self):
        item = self._one(_entry("/spec/template/spec/containers/0/image", left=_node("string", "registry.io/app:1.2.3"), right=_node("string", "registry.io/app:1.2.4")))
        assert item["subclass"] == "patch"

    def test_image_non_semver(self):
        item = self._one(_entry("/spec/template/spec/containers/0/image", left=_node("string", "app:latest"), right=_node("string", "app:stable")))
        assert item["subclass"] == "non-semver"

    def test_image_digest_non_semver(self):
        item = self._one(_entry("/spec/template/spec/containers/0/image", left=_node("string", "app@sha256:abc"), right=_node("string", "app@sha256:def")))
        assert item["subclass"] == "non-semver"

    def test_image_registry_prefix_stripped(self):
        item = self._one(_entry("/spec/containers/0/image", left=_node("string", "registry.io/ns/app:1.2.3"), right=_node("string", "registry.io/ns/app:1.2.4")))
        assert item["subclass"] == "patch"

    def test_resources_shrink(self):
        item = self._one(_entry("/spec/containers/0/resources/limits/memory", left=_node("quantity", "1Gi"), right=_node("quantity", "512Mi")))
        assert item["class"] == spec.RESOURCE_SHRINK

    def test_resources_grow_is_config(self):
        item = self._one(_entry("/spec/containers/0/resources/limits/memory", left=_node("quantity", "512Mi"), right=_node("quantity", "1Gi")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_resources_equal_is_config_by_source_order(self):
        item = self._one(_entry("/spec/containers/0/resources/limits/memory", left=_node("quantity", "1Gi"), right=_node("quantity", "1024Mi")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_requests_shrink(self):
        item = self._one(_entry("/spec/containers/0/resources/requests/cpu", left=_node("quantity", "500m"), right=_node("quantity", "250m")))
        assert item["class"] == spec.RESOURCE_SHRINK

    def test_resources_different_family_not_shrink(self):
        item = self._one(_entry("/spec/containers/0/resources/limits/memory", left=_node("quantity", "1Gi"), right=_node("string", "512Mi")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_replicas_shrink(self):
        item = self._one(_entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1")))
        assert item["class"] == spec.RESOURCE_SHRINK

    def test_replicas_grow_is_config(self):
        item = self._one(_entry("/spec/replicas", left=_node("decimal", "1"), right=_node("decimal", "3")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_max_unavailable_grow_is_deploy(self):
        item = self._one(_entry("/spec/strategy/rollingUpdate/maxUnavailable", left=_node("decimal", "1"), right=_node("decimal", "2")))
        assert item["class"] == spec.DEPLOY_SHRINK

    def test_max_unavailable_shrink_is_config(self):
        item = self._one(_entry("/spec/strategy/rollingUpdate/maxUnavailable", left=_node("decimal", "2"), right=_node("decimal", "1")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_min_ready_seconds_grow_is_deploy(self):
        item = self._one(_entry("/spec/minReadySeconds", left=_node("decimal", "0"), right=_node("decimal", "10")))
        assert item["class"] == spec.DEPLOY_SHRINK

    def test_min_ready_seconds_duration_grow_is_deploy(self):
        item = self._one(_entry("/spec/minReadySeconds", left=_node("duration", "1s"), right=_node("duration", "2s")))
        assert item["class"] == spec.DEPLOY_SHRINK

    def test_service_type_is_exposure(self):
        item = self._one(_entry("/spec/type", left=_node("string", "ClusterIP"), right=_node("string", "NodePort")))
        assert item["class"] == spec.EXPOSURE

    def test_ports_is_exposure(self):
        item = self._one(_entry("/spec/ports/0/port", left=_node("decimal", "80"), right=_node("decimal", "8080")))
        assert item["class"] == spec.EXPOSURE

    def test_selector_is_exposure(self):
        item = self._one(_entry("/spec/selector/app", kind="added", right=_node("string", "web")))
        assert item["class"] == spec.EXPOSURE

    def test_protocol_is_not_exposure(self):
        item = self._one(_entry("/spec/ports/0/protocol", left=_node("string", ""), right=_node("string", "TCP")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_ingress_rules_is_exposure(self):
        item = self._one(_entry("/spec/rules/0/host", kind="added", right=_node("string", "example.test")))
        assert item["class"] == spec.EXPOSURE

    def test_env_added_is_config(self):
        item = self._one(_entry("/spec/containers/0/env/0/name", kind="added", right=_node("string", "MODE")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_configmap_data_is_config(self):
        item = self._one(_entry("/data/foo", kind="removed", left=_node("string", "x")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_secret_is_config(self):
        item = self._one(_entry("/stringData/token", kind="added", right=_node("string", "x")))
        assert item["class"] == spec.CONFIG_CHANGE

    def test_equal_values_are_cosmetic(self):
        item = self._one(_entry("/metadata/annotations/revision", left=_node("decimal", "1.0"), right=_node("decimal", "1")))
        assert item["class"] == spec.COSMETIC

    def test_equal_duration_is_cosmetic(self):
        item = self._one(_entry("/metadata/annotations/ttl", left=_node("duration", "1h"), right=_node("duration", "60m")))
        assert item["class"] == spec.COSMETIC

    def test_unequal_values_are_config_guess(self):
        item = self._one(_entry("/metadata/annotations/x", left=_node("decimal", "1"), right=_node("decimal", "2")))
        assert item["class"] == spec.CONFIG_CHANGE and item["guess"] is True

    def test_unknown_family_classifies_config_guess(self):
        item = self._one(_entry("/x", left=_node("unknown", "${var.x}"), right=_node("unknown", "${var.y}")))
        assert item["kind"] == "indeterminate"

    def test_changed_without_sides_is_config_guess(self):
        item = self._one(_entry("/x"))
        assert item["class"] == spec.CONFIG_CHANGE and item["guess"] is True

    def test_indeterminate_kind_is_cosmetic_class(self):
        item = self._one(_entry("/x", kind="indeterminate", reason="ambiguous_unit_family"))
        assert item["class"] == spec.COSMETIC

    def test_explicit_cosmetic_kind(self):
        item = self._one(_entry("/x", kind="cosmetic"))
        assert item["class"] == spec.COSMETIC

    def test_order_is_class_then_path(self):
        result = _classified(
            [
                _entry("/z", kind="added", right=_node("string", "x")),
                _entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1")),
                _entry("/a", kind="added", right=_node("string", "x")),
            ]
        )
        classes = [(item["class"], item["path"]) for item in result["entries"]]
        assert classes[0][0] == spec.RESOURCE_SHRINK
        assert [path for cls, path in classes[1:]] == ["/a", "/z"]

    def test_summary_counts(self):
        result = _classified(
            [
                _entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1")),
                _entry("/metadata/x", left=_node("decimal", "1"), right=_node("decimal", "1")),
                _entry("/y", kind="indeterminate", reason="r"),
            ]
        )
        assert result["summary"]["total"] == 3
        assert result["summary"]["behavioral"] == 1
        assert result["summary"]["cosmetic"] == 1
        assert result["summary"]["indeterminate"] == 1

    def test_normalize_entry_rejects_non_mapping(self):
        with pytest.raises(classify.ClassifyError):
            classify.normalize_entry("x", 0)

    def test_normalize_entry_rejects_bad_kind(self):
        with pytest.raises(classify.ClassifyError):
            classify.normalize_entry({"path": "/x", "kind": "same"}, 0)

    def test_normalize_entry_rejects_bad_path(self):
        with pytest.raises(classify.ClassifyError):
            classify.normalize_entry({"path": 1, "kind": "added"}, 0)


# ════════════════════════════════════════════════════════════════════════
# 3. gate 与参数
# ════════════════════════════════════════════════════════════════════════
class TestGate:
    def _summary(self, behavioral=0, cosmetic=0, indeterminate=0, by_class=None):
        return {
            "total": behavioral + cosmetic + indeterminate,
            "by_class": by_class or {name: 0 for name in spec.ALL_CLASSES},
            "behavioral": behavioral,
            "cosmetic": cosmetic,
            "indeterminate": indeterminate,
        }

    def test_default_blocks_behavioral(self):
        blocked, reason = classify.gate(self._summary(behavioral=1), (), False)
        assert blocked is True and reason == "behavioral"

    def test_default_passes_cosmetic(self):
        assert classify.gate(self._summary(cosmetic=1), (), False) == (False, "")

    def test_indeterminate_blocks_by_default(self):
        blocked, reason = classify.gate(self._summary(indeterminate=1), (), False)
        assert blocked is True and reason == "indeterminate"

    def test_allow_indeterminate(self):
        assert classify.gate(self._summary(indeterminate=1), (), True) == (False, "")

    def test_fail_on_specific_class_blocks(self):
        summary = self._summary(behavioral=1, by_class={**{name: 0 for name in spec.ALL_CLASSES}, spec.EXPOSURE: 1})
        blocked, reason = classify.gate(summary, (spec.EXPOSURE,), False)
        assert blocked is True and reason == spec.EXPOSURE

    def test_fail_on_other_class_passes(self):
        summary = self._summary(behavioral=1, by_class={**{name: 0 for name in spec.ALL_CLASSES}, spec.CONFIG_CHANGE: 1})
        assert classify.gate(summary, (spec.EXPOSURE,), False) == (False, "")

    def test_resolve_fail_on(self):
        assert spec.resolve_params({"fail_on": ["接口·暴露"]}).fail_on == ("接口·暴露",)

    def test_resolve_allow_indeterminate(self):
        assert spec.resolve_params({"allow_indeterminate": True}).allow_indeterminate is True

    def test_resolve_unknown_class(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"fail_on": ["未知类"]})

    def test_resolve_non_list_fail_on(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"fail_on": "接口·暴露"})

    def test_resolve_non_bool_allow(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"allow_indeterminate": "yes"})

    def test_resolve_unknown_key(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"shingle_size": 1})


# ════════════════════════════════════════════════════════════════════════
# 4. 器官编排（evaluate）
# ════════════════════════════════════════════════════════════════════════
class TestEvaluate:
    def test_sample_is_clean(self):
        records = _evaluate()
        assert [record.rule_id for record in records] == [spec.RULE_COSMETIC, spec.RULE_SUMMARY]

    def test_sample_exit_zero(self):
        report = Report(product="byteproof", organ=SLUG, organ_version="1", subject="x", records=_evaluate())
        assert report.exit_code() == EXIT_OK

    def test_summary_record_counts(self):
        summary = _by_rule(_evaluate(), spec.RULE_SUMMARY)[0]
        assert summary.evidence["summary"]["total"] == 1
        assert summary.evidence["blocked"] is False

    def test_behavioral_without_fail_on_blocks(self):
        subject = _subject([_entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1"))])
        records = _evaluate(subject)
        assert _by_rule(records, spec.RULE_GATE)[0].verdict == ERROR

    def test_behavioral_with_matching_fail_on_blocks(self):
        subject = _subject(
            [_entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1"))],
            {"fail_on": [spec.RESOURCE_SHRINK]},
        )
        assert _by_rule(_evaluate(subject), spec.RULE_GATE)

    def test_behavioral_with_other_fail_on_passes(self):
        subject = _subject(
            [_entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1"))],
            {"fail_on": [spec.EXPOSURE]},
        )
        assert _by_rule(_evaluate(subject), spec.RULE_GATE) == []

    def test_indeterminate_blocks_by_default(self):
        subject = _subject([_entry("/x", kind="indeterminate", reason="ambiguous_unit_family")])
        records = _evaluate(subject)
        assert _by_rule(records, spec.RULE_INDETERMINATE)[0].verdict == WARN
        assert _by_rule(records, spec.RULE_GATE)

    def test_indeterminate_allowed(self):
        subject = _subject(
            [_entry("/x", kind="indeterminate", reason="ambiguous_unit_family")],
            {"allow_indeterminate": True},
        )
        assert _by_rule(_evaluate(subject), spec.RULE_GATE) == []

    def test_image_record(self):
        subject = _subject([_entry("/spec/containers/0/image", left=_node("string", "registry.io/app:1.0.0"), right=_node("string", "registry.io/app:2.0.0"))])
        records = _evaluate(subject)
        assert _by_rule(records, spec.RULE_IMAGE)[0].evidence["subclass"] == "major"

    def test_exposure_record(self):
        subject = _subject([_entry("/spec/type", left=_node("string", "ClusterIP"), right=_node("string", "NodePort"))])
        assert _by_rule(_evaluate(subject), spec.RULE_EXPOSURE)

    def test_config_record(self):
        subject = _subject([_entry("/data/foo", kind="removed", left=_node("string", "x"))])
        assert _by_rule(_evaluate(subject), spec.RULE_CONFIG)

    def test_config_guess_flag_in_evidence(self):
        subject = _subject([_entry("/metadata/x", left=_node("decimal", "1"), right=_node("decimal", "2"))])
        assert _by_rule(_evaluate(subject), spec.RULE_CONFIG)[0].evidence["class_guess"] is True

    def test_all_records_have_basis(self):
        subject = _subject([_entry("/spec/type", left=_node("string", "ClusterIP"), right=_node("string", "NodePort"))])
        for record in _evaluate(subject):
            assert record.basis is not None and record.basis.complete
            assert record.basis.rule_id == record.rule_id

    def test_ids_are_unique(self):
        subject = _subject(
            [
                _entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1")),
                _entry("/spec/replicas", left=_node("decimal", "5"), right=_node("decimal", "2")),
            ]
        )
        ids = [record.id for record in _evaluate(subject)]
        assert len(ids) == len(set(ids))

    def test_entries_must_be_list(self):
        with pytest.raises(classify.ClassifyError):
            _evaluate({"entries": "x"})

    def test_bad_entry_kind_is_rejected(self):
        with pytest.raises(classify.ClassifyError):
            _evaluate({"entries": [{"path": "/x", "kind": "same"}]})

    def test_report_is_deterministic(self):
        subject = _subject([_entry("/spec/type", left=_node("string", "ClusterIP"), right=_node("string", "NodePort"))])
        def build():
            return Report(product="byteproof", organ=SLUG, organ_version="1", subject="x",
                          records=_evaluate(subject)).as_dict()
        assert json.dumps(build(), ensure_ascii=False) == json.dumps(build(), ensure_ascii=False)

    @pytest.mark.parametrize("rule,expected", [
        (spec.RULE_RESOURCE, WARN), (spec.RULE_DEPLOY, WARN), (spec.RULE_IMAGE, WARN),
        (spec.RULE_EXPOSURE, WARN), (spec.RULE_CONFIG, WARN), (spec.RULE_COSMETIC, INFO),
        (spec.RULE_INDETERMINATE, WARN), (spec.RULE_GATE, ERROR), (spec.RULE_SUMMARY, INFO),
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

    def test_blocked_subject_returns_one(self, tmp_path):
        subject = _subject([_entry("/spec/replicas", left=_node("decimal", "3"), right=_node("decimal", "1"))])
        path = tmp_path / "blocked.json"
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
        assert get(SLUG) is PACK and PACK.input_fields == ("entries",)

    def test_wiring_version(self):
        assert PACK.version == ORGAN_VERSION == "1"

    def test_builtin_modules_sorted(self):
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_builtin_modules_include_slug(self):
        assert "config_drift" in BUILTIN_MODULES

    def test_organ_is_package(self):
        assert (SRC / "byteproof" / "auditors" / "config_drift" / "__init__.py").is_file()

    def test_no_clock_calls(self):
        for name in ("audit.py", "classify.py", "value.py"):
            text = (SRC / "byteproof" / "auditors" / "config_drift" / name).read_text(encoding="utf-8")
            assert "datetime.now(" not in text and "date.today(" not in text and "time.time(" not in text

    def test_no_network_imports(self):
        tree = ast.parse((SRC / "byteproof" / "auditors" / "config_drift" / "audit.py").read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "socket" not in names and "requests" not in names and "urllib" not in names

    def test_docs_page_exists(self):
        assert (ROOT / "docs" / (SLUG + ".md")).is_file()

    def test_docs_page_has_four_criteria(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        for marker in ("X = 79", "判据 4", "处置表", "口径差"):
            assert marker in text

    def test_docs_page_names_sample(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        assert "samples/config-drift.minimal.json" in text