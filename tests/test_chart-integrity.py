"""``chart-integrity`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那个函数仍然在、语义仍然是那一套**：
九条反误导规则、逐值溯源（白名单变换 / ID / 重算）、G2 样本量门禁、G3 误差棒来源判定
都是逐条搬用旧仓 ``tests/test_rules.py`` / ``test_provenance.py`` / ``test_gates.py`` /
``test_provenance_regression.py`` / ``test_rules_regression.py`` 的断言。

**没迁的部分逐条写在 ``docs/chart-integrity.md`` §6 的处置表里**（CSV 解析、spec 解析层、
HTML 渲染与几何包、发布门、bench、冻结数据生成）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 9 个判定层文件实跑 **X = 222 passed**（AST 函数 122）。
"""

from __future__ import annotations

import ast
import copy
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
from byteproof.auditors.chart_integrity import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    gates,
    provenance,
    rules,
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

SLUG = "chart-integrity"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "chart-integrity.basis.json"
THRESHOLDS_PATH = DATA_DIR / "chart-integrity.thresholds.json"
SAMPLE = ROOT / "samples" / "chart-integrity.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = spec.resolve_params()
SHA = "a" * 64


def _dataset(header=None, rows=None, types=None, sha=SHA):
    header = header or ["组", "值"]
    types = types or ["text", "decimal"]
    return {
        "header": list(header),
        "columns": [{"name": name, "type": kind} for name, kind in zip(header, types)],
        "rows": [list(row) for row in (rows or [])],
        "row_count": len(rows or []),
        "source": {"name": "synthetic.csv", "sha256": sha},
    }


def _spec(mark="line", x="组", y="值", title="合成图", **extra):
    encoding = {"x": {"field": x}, "y": {"field": y, "decimals": 2}}
    if "aggregate" in extra:
        encoding["y"]["aggregate"] = extra.pop("aggregate")
    if "error_bar" in extra:
        encoding["error_bar"] = extra.pop("error_bar")
    if "series" in extra:
        encoding["series"] = {"field": extra.pop("series")}
    spec_obj = {
        "spec_id": "spec-test",
        "mark": mark,
        "title": title,
        "encoding": encoding,
    }
    spec_obj.update(extra)
    return spec_obj


def _prov(dataset, spec_obj, records=None):
    return {
        "spec_id": spec_obj["spec_id"],
        "source": {"name": "synthetic.csv", "sha256": dataset["source"]["sha256"]},
        "rendered_values": list(records) if records is not None else provenance.compile_records(dataset, spec_obj),
    }


def _subject(dataset=None, spec_obj=None, prov=None, **extra):
    dataset = dataset if dataset is not None else _dataset(rows=[["A", "10.00"], ["A", "12.50"]])
    spec_obj = spec_obj if spec_obj is not None else _spec()
    subject = {
        "dataset": dataset,
        "spec": spec_obj,
        "provenance": prov if prov is not None else _prov(dataset, spec_obj),
    }
    subject.update(extra)
    return subject


def _evaluate(subject=None, basis=None):
    return list(audit.evaluate(subject if subject is not None else _subject(), basis or BASIS))


def _by_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


def _grouped(rows, values):
    return _dataset(rows=[[group, value] for group, value in zip(rows, values)])


# ════════════════════════════════════════════════════════════════════════
# 1. 参数面（spec）
# ════════════════════════════════════════════════════════════════════════
class TestSpec:
    def test_defaults_match_thresholds_file(self):
        document = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        params = document["params"]
        for key in (
            "n_min", "skew_abs_threshold", "skew_min_n", "multimodal_bins",
            "multimodal_min_n", "multimodal_min_count_floor",
            "multimodal_min_count_divisor", "sem_tolerance_abs", "pie_max_sectors",
        ):
            assert params[key] == getattr(spec.DEFAULT_SETTINGS, key)
        assert params["aliases"] == json.loads(json.dumps(spec.DEFAULT_SETTINGS.aliases))

    def test_verdict_table_matches_thresholds_file(self):
        document = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert document["verdicts"] == spec.VERDICT_BY_RULE

    def test_rule_ids_are_registered_and_unique(self):
        assert len(spec.RULE_IDS) == len(set(spec.RULE_IDS))
        assert set(spec.RULE_IDS) == set(spec.VERDICT_BY_RULE)

    def test_basis_pack_contains_every_rule(self):
        assert set(spec.RULE_IDS) <= set(BASIS.rule_ids())

    def test_verdict_for_unknown_rule_raises(self):
        with pytest.raises(ValueError):
            spec.verdict_for("no-such")

    def test_override_n_min(self):
        assert spec.resolve_params({"n_min": 8}).n_min == 8

    def test_override_skew_threshold(self):
        assert spec.resolve_params({"skew_abs_threshold": 2}).skew_abs_threshold == 2.0

    def test_override_pie_max_sectors(self):
        assert spec.resolve_params({"pie_max_sectors": 6}).pie_max_sectors == 6

    def test_override_tolerance_string(self):
        assert spec.resolve_params({"sem_tolerance_abs": "0.5"}).sem_tolerance_abs == "0.5"

    def test_override_aliases(self):
        aliases = json.loads(json.dumps(spec.DEFAULT_ALIASES))
        aliases["case_sensitive"] = True
        assert spec.resolve_params({"aliases": aliases}).aliases["case_sensitive"] is True

    def test_unknown_param_key_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"shingle_size": 3})

    def test_non_mapping_params_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params([])

    def test_zero_n_min_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"n_min": 0})

    def test_boolean_n_min_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"n_min": True})

    def test_non_positive_skew_threshold_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"skew_abs_threshold": 0})

    def test_non_numeric_tolerance_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"sem_tolerance_abs": "abc"})

    def test_negative_tolerance_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"sem_tolerance_abs": "-0.1"})

    def test_skew_min_n_below_three_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"skew_min_n": 2})

    def test_multimodal_bins_below_two_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"multimodal_bins": 1})

    def test_aliases_non_mapping_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"aliases": []})

    def test_aliases_case_sensitive_must_be_bool(self):
        aliases = json.loads(json.dumps(spec.DEFAULT_ALIASES))
        aliases["case_sensitive"] = "no"
        with pytest.raises(ValueError):
            spec.resolve_params({"aliases": aliases})

    def test_aliases_match_mode_must_be_suffix(self):
        aliases = json.loads(json.dumps(spec.DEFAULT_ALIASES))
        aliases["match_mode"] = "prefix"
        with pytest.raises(ValueError):
            spec.resolve_params({"aliases": aliases})

    def test_aliases_missing_type_is_rejected(self):
        aliases = json.loads(json.dumps(spec.DEFAULT_ALIASES))
        del aliases["types"]["n"]
        with pytest.raises(ValueError):
            spec.resolve_params({"aliases": aliases})

    def test_decimal_or_raise(self):
        assert spec.decimal_or_raise("1.5", "x") == spec.Decimal("1.5")

    def test_decimal_or_raise_invalid(self):
        with pytest.raises(ValueError):
            spec.decimal_or_raise("abc", "x")


# ════════════════════════════════════════════════════════════════════════
# 2. 精确算术 / 变换 / ID（旧仓 test_provenance.py）
# ════════════════════════════════════════════════════════════════════════
class TestProvenanceCore:
    def test_round_half_up_rounds_up(self):
        assert provenance.round_half_up(Fraction(1, 2), 0) == Fraction(1)

    def test_round_half_up_rounds_down(self):
        assert provenance.round_half_up(Fraction(3, 10), 0) == Fraction(0)

    def test_round_half_up_negative(self):
        assert provenance.round_half_up(Fraction(-1, 2), 0) == Fraction(-1)

    def test_round_half_up_two_decimals(self):
        assert provenance.round_half_up(Fraction("1.005"), 2) == Fraction("1.01")

    def test_round_half_up_none_decimals(self):
        assert provenance.round_half_up(Fraction(1, 3), None) == Fraction(1, 3)

    def test_round_half_up_rejects_negative_decimals(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.round_half_up(Fraction(1), -1)

    def test_format_value_two_decimals(self):
        assert provenance.format_value(Fraction("10"), 2) == "10.00"

    def test_format_value_zero_decimals(self):
        assert provenance.format_value(Fraction("11.5"), 0) == "12"

    def test_format_value_negative(self):
        assert provenance.format_value(Fraction("-2.345"), 2) == "-2.35"

    def test_format_value_exact_string(self):
        assert provenance.format_value(Fraction("12.50"), None) == "12.5"

    def test_format_value_exact_fraction_string(self):
        assert provenance.format_value(Fraction(1, 3), None) == "1/3"

    def test_apply_identity(self):
        assert provenance.apply_transform("identity", [Fraction(1)]) == [Fraction(1)]

    def test_apply_group_sum(self):
        assert provenance.apply_transform("group_sum", [Fraction(1), Fraction(2)]) == [Fraction(3)]

    def test_apply_group_mean(self):
        assert provenance.apply_transform("group_mean", [Fraction(1), Fraction(3)]) == [Fraction(2)]

    def test_apply_group_median_odd(self):
        assert provenance.apply_transform("group_median", [Fraction(3), Fraction(1), Fraction(2)]) == [Fraction(2)]

    def test_apply_group_median_even(self):
        assert provenance.apply_transform("group_median", [Fraction(1), Fraction(4)]) == [Fraction(5, 2)]

    def test_apply_group_count(self):
        assert provenance.apply_transform("group_count", [Fraction(1)] * 3) == [Fraction(3)]

    def test_apply_ratio(self):
        assert provenance.apply_transform("ratio", [Fraction(1)], denominator="4") == [Fraction(1, 4)]

    def test_apply_ratio_requires_one_value(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.apply_transform("ratio", [Fraction(1), Fraction(1)], denominator="4")

    def test_apply_ratio_requires_denominator(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.apply_transform("ratio", [Fraction(1)])

    def test_apply_ratio_zero_denominator(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.apply_transform("ratio", [Fraction(1)], denominator="0")

    def test_apply_sort(self):
        assert provenance.apply_transform("sort", [Fraction(2), Fraction(1)]) == [Fraction(1), Fraction(2)]

    def test_apply_top_n(self):
        assert provenance.apply_transform("top_n", [Fraction(1), Fraction(3), Fraction(2)], n=2) == [Fraction(3), Fraction(2)]

    def test_apply_top_n_bad_n(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.apply_transform("top_n", [Fraction(1)], n=0)

    def test_apply_stack_offset(self):
        assert provenance.apply_transform("stack_offset", [Fraction(1), Fraction(2)]) == [Fraction(1), Fraction(3)]

    def test_apply_unknown_transform(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.apply_transform("exec", [Fraction(1)])

    def test_apply_group_sum_empty(self):
        with pytest.raises(provenance.ProvenanceError):
            provenance.apply_transform("group_sum", [])

    def test_canonical_id_payload_field_order(self):
        payload = provenance.canonical_id_payload("s", "m", None, "c", 0, "y", [{"op": "identity"}])
        assert payload.startswith('["s","m",null,"c",0,"y",')

    def test_rendered_value_id_is_16_hex(self):
        value = provenance.rendered_value_id("s", "m", None, "c", 0, "y", [])
        assert len(value) == 16 and int(value, 16) >= 0

    def test_rendered_value_id_is_stable(self):
        args = ("s", "m", None, "c", 0, "y", [{"op": "identity"}])
        assert provenance.rendered_value_id(*args) == provenance.rendered_value_id(*args)

    def test_rendered_value_id_changes_with_category(self):
        base = provenance.rendered_value_id("s", "m", None, "c", 0, "y", [])
        assert base != provenance.rendered_value_id("s", "m", None, "d", 0, "y", [])

    def test_compile_identity_record_shape(self):
        dataset = _dataset(rows=[["A", "10.00"]])
        records = provenance.compile_records(dataset, _spec())
        record = records[0]
        assert record["row_index"] == 0 and record["csv_line"] == 2
        assert record["raw_cell"] == "10.00" and record["parsed_value"] == "10"
        assert record["rendered_label"] == "10.00"
        assert record["match"] is True

    def test_compile_identity_uses_filter_chain(self):
        dataset = _dataset(rows=[["A", "1.00"], ["B", "2.00"]])
        spec_obj = _spec()
        spec_obj["encoding"]["x"]["filter"] = {"field": "组", "equals": "A"}
        records = provenance.compile_records(dataset, spec_obj)
        assert len(records) == 1
        assert records[0]["transform_chain"][0] == {"op": "filter", "field": "组", "equals": "A"}

    def test_compile_group_mean(self):
        dataset = _dataset(rows=[["A", "1"], ["A", "3"]])
        records = provenance.compile_records(dataset, _spec(mark="bar", aggregate="group_mean"))
        assert records[0]["exact_value"] == "2"
        assert records[0]["transform_chain"][-1] == {"op": "group_mean", "field": "值"}

    def test_compile_group_sum(self):
        dataset = _dataset(rows=[["A", "1"], ["A", "3"]])
        records = provenance.compile_records(dataset, _spec(mark="pie", aggregate="group_sum"))
        assert records[0]["exact_value"] == "4"

    def test_compile_group_count(self):
        dataset = _dataset(rows=[["A", "1"], ["A", "3"]])
        records = provenance.compile_records(dataset, _spec(mark="bar", aggregate="group_count"))
        assert records[0]["exact_value"] == "2"

    def test_compile_ratio_chain(self):
        dataset = _dataset(rows=[["A", "1"], ["B", "3"]])
        records = provenance.compile_records(dataset, _spec(mark="pie", aggregate="ratio"))
        values = {record["category"]: record["exact_value"] for record in records}
        assert values == {"A": "0.25", "B": "0.75"}

    def test_compile_ratio_zero_total_raises(self):
        dataset = _dataset(rows=[["A", "0"], ["B", "0"]])
        with pytest.raises(provenance.ProvenanceError):
            provenance.compile_records(dataset, _spec(mark="pie", aggregate="ratio"))

    def test_compile_missing_numeric_cell_raises(self):
        dataset = _dataset(rows=[["A", ""]])
        with pytest.raises(provenance.ProvenanceError):
            provenance.compile_records(dataset, _spec())

    def test_compile_non_numeric_column_raises(self):
        dataset = _dataset(rows=[["A", "1"]], types=["text", "text"])
        with pytest.raises(provenance.ProvenanceError):
            provenance.compile_records(dataset, _spec())

    def test_compile_empty_filter_raises(self):
        dataset = _dataset(rows=[["A", "1"]])
        spec_obj = _spec()
        spec_obj["encoding"]["x"]["filter"] = {"field": "组", "equals": "B"}
        with pytest.raises(provenance.ProvenanceError):
            provenance.compile_records(dataset, spec_obj)

    def test_compile_negative_decimals_raises(self):
        dataset = _dataset(rows=[["A", "1"]])
        spec_obj = _spec()
        spec_obj["encoding"]["y"]["decimals"] = -1
        with pytest.raises(provenance.ProvenanceError):
            provenance.compile_records(dataset, spec_obj)

    def test_compile_series_field(self):
        dataset = _dataset(header=["组", "系列", "值"], rows=[["A", "s1", "1"]], types=["text", "text", "decimal"])
        spec_obj = _spec(series="系列")
        record = provenance.compile_records(dataset, spec_obj)[0]
        assert record["series"] == "s1"


# ════════════════════════════════════════════════════════════════════════
# 3. 溯源校验（G1）
# ════════════════════════════════════════════════════════════════════════
class TestProvenanceValidate:
    def _base(self):
        dataset = _dataset(rows=[["A", "10.00"], ["A", "12.50"]])
        spec_obj = _spec()
        return dataset, spec_obj, _prov(dataset, spec_obj)

    def _issues(self, dataset, spec_obj, prov):
        return provenance.validate(prov, dataset, spec_obj)[0]

    def test_clean_provenance_has_no_issues(self):
        dataset, spec_obj, prov = self._base()
        assert self._issues(dataset, spec_obj, prov) == []

    def test_checked_count(self):
        dataset, spec_obj, prov = self._base()
        assert provenance.validate(prov, dataset, spec_obj)[1] == 2

    def test_spec_id_mismatch_is_malformed(self):
        dataset, spec_obj, prov = self._base()
        prov["spec_id"] = "other"
        issues = self._issues(dataset, spec_obj, prov)
        assert issues and issues[0]["rule_id"] == spec.RULE_PROV_MALFORMED

    def test_source_hash_mismatch_is_malformed(self):
        dataset, spec_obj, prov = self._base()
        prov["source"]["sha256"] = "b" * 64
        assert any(issue["rule_id"] == spec.RULE_PROV_MALFORMED for issue in self._issues(dataset, spec_obj, prov))

    def test_rendered_values_not_list_is_malformed(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"] = "x"
        assert any(issue["rule_id"] == spec.RULE_PROV_MALFORMED for issue in self._issues(dataset, spec_obj, prov))

    def test_non_mapping_record_is_malformed(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0] = "x"
        assert any(issue["rule_id"] == spec.RULE_PROV_MALFORMED for issue in self._issues(dataset, spec_obj, prov))

    def test_bad_id_length_is_malformed(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["rendered_value_id"] = "abc"
        assert any(issue["rule_id"] == spec.RULE_PROV_MALFORMED for issue in self._issues(dataset, spec_obj, prov))

    def test_duplicate_id_is_malformed(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][1]["rendered_value_id"] = prov["rendered_values"][0]["rendered_value_id"]
        assert any("重复" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_missing_record_is_reported(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"].pop()
        issues = self._issues(dataset, spec_obj, prov)
        assert any(issue["rule_id"] == spec.RULE_PROV_MISSING for issue in issues)

    def test_unexpected_record_is_reported(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"].append(copy.deepcopy(prov["rendered_values"][0]))
        prov["rendered_values"][-1]["rendered_value_id"] = "0123456789abcdef"
        issues = self._issues(dataset, spec_obj, prov)
        assert any(issue["rule_id"] == spec.RULE_PROV_UNEXPECTED for issue in issues)

    def test_row_index_out_of_range_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["row_index"] = 99
        assert any(issue["rule_id"] == spec.RULE_PROV_MISMATCH for issue in self._issues(dataset, spec_obj, prov))

    def test_column_missing_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["column"] = "无此列"
        assert any("不存在" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_sources_empty_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["sources"] = []
        assert any(issue["rule_id"] == spec.RULE_PROV_MISMATCH for issue in self._issues(dataset, spec_obj, prov))

    def test_raw_cell_tamper_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["raw_cell"] = "99"
        assert any("raw_cell" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_parsed_value_tamper_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["parsed_value"] = "99"
        assert any("parsed_value" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_source_raw_cell_tamper_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["sources"][0]["raw_cell"] = "99"
        assert any("sources[0]" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_csv_line_must_be_row_plus_two(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["csv_line"] = 7
        assert any("csv_line" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_id_mismatch_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        record = prov["rendered_values"][0]
        record["mark_id"] = "bar"  # 字段改了、id 保持 expected -> 复算 id 不同
        issues = self._issues(dataset, spec_obj, prov)
        assert any("重新计算" in issue["message"] for issue in issues)

    def test_match_false_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["match"] = False
        assert any("match" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_recomputed_value_tamper_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["recomputed_value"] = "99.00"
        assert any("recomputed_value" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_rendered_label_tamper_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["rendered_label"] = "99.00"
        assert any("rendered_label" in issue["message"] for issue in self._issues(dataset, spec_obj, prov))

    def test_swapped_ids_are_detected(self):
        dataset, spec_obj, prov = self._base()
        first, second = prov["rendered_values"][0], prov["rendered_values"][1]
        first["rendered_value_id"], second["rendered_value_id"] = second["rendered_value_id"], first["rendered_value_id"]
        assert any(issue["rule_id"] == spec.RULE_PROV_MISMATCH for issue in self._issues(dataset, spec_obj, prov))

    def test_bad_transform_chain_is_mismatch(self):
        dataset, spec_obj, prov = self._base()
        prov["rendered_values"][0]["transform_chain"] = [{"op": "exec"}]
        assert any(issue["rule_id"] == spec.RULE_PROV_MISMATCH for issue in self._issues(dataset, spec_obj, prov))

    def test_aggregate_outside_whitelist_raises(self):
        dataset = _dataset(rows=[["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="median")
        with pytest.raises(provenance.ProvenanceError):
            provenance.compile_records(dataset, spec_obj)


# ════════════════════════════════════════════════════════════════════════
# 4. 九条规则（旧仓 test_rules.py）
# ════════════════════════════════════════════════════════════════════════
class TestRules:
    def _audit(self, spec_obj, dataset=None):
        dataset = dataset or _dataset(rows=[["A", "1"]])
        prov = _prov(dataset, spec_obj)
        return rules.audit(dataset, spec_obj, prov, SETTINGS)

    def test_bar_zero_baseline_not_hit(self):
        assert self._audit(_spec(mark="bar")) == []

    def test_bar_nonzero_baseline_hit(self):
        findings = self._audit(_spec(mark="bar", y_zero=False))
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_BAR]

    def test_bar_y_zero_false_on_line_is_ignored(self):
        assert self._audit(_spec(mark="line", y_zero=False)) == []

    def test_dual_y_hit(self):
        findings = self._audit(_spec(mark="line", dual_y=True))
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_DUAL_Y]

    def test_dual_y_false_not_hit(self):
        assert self._audit(_spec(mark="line", dual_y=False)) == []

    def test_pseudo_3d_hit(self):
        findings = self._audit(_spec(mark="bar", pseudo_3d=True))
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_3D]

    def test_radius_hit(self):
        findings = self._audit(_spec(mark="scatter", size_channel="radius"))
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_RADIUS]

    def test_size_area_not_hit(self):
        assert self._audit(_spec(mark="scatter", size_channel="area")) == []

    def test_smooth_hit(self):
        findings = self._audit(_spec(mark="line", smooth=True))
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_SMOOTH]

    def test_low_contrast_hit(self):
        findings = self._audit(_spec(mark="bar", low_contrast=True))
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_CONTRAST]

    def test_spec_invalid_checker_never_hits(self):
        findings = self._audit(_spec(mark="bar"))
        assert spec.RULE_SPEC_INVALID not in [finding["rule_id"] for finding in findings]

    def test_pie_too_many_sectors_hit(self):
        rows = [["A", "1"], ["B", "1"], ["C", "1"], ["D", "1"], ["E", "1"]]
        findings = self._audit(_spec(mark="pie"), _dataset(rows=rows))
        assert any(finding["rule_id"] == spec.RULE_PIE for finding in findings)

    def test_pie_sector_count_at_limit_not_hit(self):
        rows = [["A", "25"], ["B", "25"], ["C", "25"], ["D", "25"]]
        findings = self._audit(_spec(mark="pie"), _dataset(rows=rows))
        assert [finding["rule_id"] for finding in findings] == []

    def test_pie_percent_sum_not_100_hit(self):
        rows = [["A", "1"], ["B", "1"], ["C", "1"]]
        spec_obj = _spec(mark="pie")
        spec_obj["encoding"]["y"]["decimals"] = 0
        findings = rules.audit(_dataset(rows=rows), spec_obj, _prov(_dataset(rows=rows), spec_obj), SETTINGS)
        assert any(finding["rule_id"] == spec.RULE_PIE for finding in findings)

    def test_pie_evidence_percent_sum(self):
        rows = [["A", "1"], ["B", "1"], ["C", "1"]]
        spec_obj = _spec(mark="pie")
        dataset = _dataset(rows=rows)
        findings = rules.audit(dataset, spec_obj, _prov(dataset, spec_obj), SETTINGS)
        evidence = [finding for finding in findings if finding["rule_id"] == spec.RULE_PIE][0]["evidence"]
        assert evidence["percent_sum"] == "99.99"
        assert evidence["sector_count"] == 3

    def test_pie_max_sectors_comes_from_settings(self):
        settings = spec.resolve_params({"pie_max_sectors": 2})
        rows = [["A", "1"], ["B", "1"], ["C", "1"]]
        dataset = _dataset(rows=rows)
        spec_obj = _spec(mark="pie")
        findings = rules.audit(dataset, spec_obj, _prov(dataset, spec_obj), settings)
        assert any(finding["rule_id"] == spec.RULE_PIE for finding in findings)

    def test_time_axis_uneven_hit(self):
        rows = [["2026-01-01", "1"], ["2026-02-01", "1"], ["2026-03-01", "1"]]
        dataset = _dataset(header=["月份", "值"], rows=rows, types=["date", "decimal"])
        findings = self._audit(_spec(mark="line", x="月份"), dataset)
        assert any(finding["rule_id"] == spec.RULE_TIME for finding in findings)

    def test_time_axis_even_not_hit(self):
        rows = [["2026-01-01", "1"], ["2026-01-08", "1"], ["2026-01-15", "1"]]
        dataset = _dataset(header=["月份", "值"], rows=rows, types=["date", "decimal"])
        findings = self._audit(_spec(mark="line", x="月份"), dataset)
        assert [finding["rule_id"] for finding in findings] == []

    def test_time_axis_non_date_column_not_hit(self):
        rows = [["A", "1"], ["B", "1"]]
        findings = self._audit(_spec(mark="line"), _dataset(rows=rows))
        assert [finding["rule_id"] for finding in findings] == []

    def test_time_axis_single_date_not_hit(self):
        rows = [["2026-01-01", "1"]]
        findings = self._audit(_spec(mark="line"), _dataset(rows=rows))
        assert spec.RULE_TIME not in [finding["rule_id"] for finding in findings]

    def test_time_axis_invalid_date_not_hit(self):
        rows = [["2026-01-01", "1"], ["not-a-date", "1"]]
        findings = self._audit(_spec(mark="line"), _dataset(rows=rows))
        assert spec.RULE_TIME not in [finding["rule_id"] for finding in findings]

    def test_time_axis_pie_skipped(self):
        rows = [["2026-01-01", "1"], ["2026-02-01", "1"]]
        findings = self._audit(_spec(mark="pie", aggregate="group_sum"), _dataset(rows=rows))
        assert spec.RULE_TIME not in [finding["rule_id"] for finding in findings]

    def test_multiple_rules_can_fire(self):
        findings = self._audit(_spec(mark="bar", y_zero=False, dual_y=True, smooth=True))
        assert {finding["rule_id"] for finding in findings} == {spec.RULE_BAR, spec.RULE_DUAL_Y, spec.RULE_SMOOTH}

    def test_severity_order_is_fixed(self):
        assert rules.severity_order() == ("ERROR", "WARN", "INFO")


# ════════════════════════════════════════════════════════════════════════
# 5. G2 样本量
# ════════════════════════════════════════════════════════════════════════
class TestG2:
    def _one_group(self, values, mark="bar", overlay=False):
        dataset = _grouped(["A"] * len(values), [str(value) for value in values])
        spec_obj = _spec(mark=mark, aggregate="group_mean", overlay_scatter=overlay)
        return gates.audit_g2(dataset, spec_obj, SETTINGS)

    def test_skew_formula(self):
        assert gates.skew_g1([Fraction(1), Fraction(1), Fraction(1), Fraction(1)], SETTINGS) is None

    def test_skew_below_min_n_is_none(self):
        assert gates.skew_g1([Fraction(1), Fraction(2)], SETTINGS) is None

    def test_skew_symmetric_is_zero(self):
        assert gates.skew_g1([Fraction(1), Fraction(2), Fraction(3)], SETTINGS) == 0.0

    def test_skew_positive(self):
        assert gates.skew_g1([Fraction(1), Fraction(1), Fraction(1), Fraction(9)], SETTINGS) > 0

    def test_bin_counts_constant_is_none(self):
        assert gates.bin_counts([Fraction(1)] * 5, SETTINGS) is None

    def test_bin_counts_too_few_is_none(self):
        assert gates.bin_counts([Fraction(1), Fraction(2)], SETTINGS) is None

    def test_bin_counts_total_equals_n(self):
        counts = gates.bin_counts([Fraction(value) for value in range(10)], SETTINGS)
        assert sum(counts) == 10 and len(counts) == SETTINGS.multimodal_bins

    def test_bin_counts_max_falls_in_last_bin(self):
        counts = gates.bin_counts([Fraction(value) for value in range(12)], SETTINGS)
        assert counts[-1] >= 1

    def test_is_multimodal_none(self):
        assert gates.is_multimodal(None, 5, SETTINGS) is None

    def test_is_multimodal_unimodal(self):
        assert gates.is_multimodal([0, 1, 3, 1, 0, 0], 5, SETTINGS) is False

    def test_is_multimodal_two_peaks(self):
        assert gates.is_multimodal([2, 0, 2, 0, 0, 0], 4, SETTINGS) is True

    def test_is_multimodal_adjacent_peaks_not_counted(self):
        assert gates.is_multimodal([2, 2, 0, 0, 0, 0], 4, SETTINGS) is False

    def test_group_stats_shape(self):
        stats = gates.group_stats([Fraction(value) for value in (1, 1, 1, 9)], SETTINGS)
        assert stats["n"] == 4 and stats["n_below_min"] is True
        assert stats["skewed"] is True and stats["multimodal"] is not None

    def test_small_skewed_group_violation(self):
        groups, findings = self._one_group([1, 1, 1, 9])
        assert groups[0]["status"] == "violation"
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_G2_VIOLATION]

    def test_small_skewed_with_overlay_is_alternative(self):
        groups, findings = self._one_group([1, 1, 1, 9], overlay=True)
        assert groups[0]["status"] == "alternative"
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_G2_ALTERNATIVE]

    def test_small_skewed_with_box_is_alternative(self):
        dataset = _grouped(["A"] * 4, ["1", "1", "1", "9"])
        spec_obj = _spec(mark="box")
        groups, findings = gates.audit_g2(dataset, spec_obj, SETTINGS)
        assert groups[0]["status"] == "alternative"

    def test_small_undetermined_group(self):
        groups, findings = self._one_group([1, 2])
        assert groups[0]["status"] == "undetermined"
        assert [finding["rule_id"] for finding in findings] == [spec.RULE_G2_UNDETERMINED]

    def test_large_group_passes(self):
        groups, findings = self._one_group([1, 2, 3, 4, 5])
        assert groups[0]["status"] == "pass" and findings == []

    def test_not_applicable_for_line_without_aggregate(self):
        dataset = _grouped(["A"] * 3, ["1", "2", "3"])
        spec_obj = _spec(mark="line")
        groups, findings = gates.audit_g2(dataset, spec_obj, SETTINGS)
        assert groups == [] and findings == []

    def test_g2_applicable_box(self):
        assert gates.g2_applicable(_spec(mark="box")) is True

    def test_g2_applicable_group_mean(self):
        assert gates.g2_applicable(_spec(mark="bar", aggregate="group_mean")) is True

    def test_g2_not_applicable_group_sum(self):
        assert gates.g2_applicable(_spec(mark="bar", aggregate="group_sum")) is False

    def test_g2_alternative_scatter(self):
        assert gates.g2_alternative(_spec(mark="scatter")) is True

    def test_g2_alternative_overlay(self):
        assert gates.g2_alternative(_spec(mark="bar", overlay_scatter=True)) is True

    def test_g2_no_alternative_line(self):
        assert gates.g2_alternative(_spec(mark="line")) is False

    def test_threshold_comes_from_settings(self):
        settings = spec.resolve_params({"n_min": 10})
        dataset = _grouped(["A"] * 5, ["1", "2", "3", "4", "5"])
        groups, _findings = gates.audit_g2(dataset, _spec(mark="bar", aggregate="group_mean"), settings)
        assert groups[0]["n_below_min"] is True

    def test_group_with_missing_value_is_skipped(self):
        dataset = _grouped(["A", "A", "A"], ["1", "", "3"])
        groups, findings = gates.audit_g2(dataset, _spec(mark="bar", aggregate="group_mean"), SETTINGS)
        assert groups == [] and findings == []


# ════════════════════════════════════════════════════════════════════════
# 6. G3 误差棒来源
# ════════════════════════════════════════════════════════════════════════
def _g3_dataset(rows, header=("组", "值")):
    types = ["text"] + ["decimal"] * (len(header) - 1)
    return _dataset(header=list(header), rows=rows, types=types)


class TestG3:
    def test_alias_case_insensitive(self):
        assert gates.matches_alias("sd", ["SD"], SETTINGS.aliases) is True

    def test_alias_suffix_match(self):
        assert gates.matches_alias("值_std", ["std"], SETTINGS.aliases) is True

    def test_alias_not_substring_at_start(self):
        assert gates.matches_alias("stdx", ["std"], SETTINGS.aliases) is False

    def test_title_declares_sd(self):
        assert gates.title_declared_type("均值±SD", SETTINGS.aliases) == "sd"

    def test_title_declares_sem(self):
        assert gates.title_declared_type("均值±标准误", SETTINGS.aliases) == "sem"

    def test_title_declares_n(self):
        assert gates.title_declared_type("各组样本量", SETTINGS.aliases) == "n"

    def test_title_no_declaration(self):
        assert gates.title_declared_type("月度值", SETTINGS.aliases) is None

    def test_sd_source_found_by_alias(self):
        dataset = _g3_dataset([["A", "1", "0.1"]], header=("组", "值", "SD"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sd"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "ok" and findings == []

    def test_sd_missing_is_error(self):
        dataset = _g3_dataset([["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sd"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "error"
        assert findings[0]["rule_id"] == spec.RULE_G3_SOURCE

    def test_sd_declared_column_not_alias_is_error(self):
        dataset = _g3_dataset([["A", "1", "0.1"]], header=("组", "值", "误差"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sd", "column": "误差"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "error"

    def test_sem_source_from_sem_column(self):
        dataset = _g3_dataset([["A", "1", "0.1"]], header=("组", "值", "SEM"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sem"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["source"]["source"] == "sem_column" and findings == []

    def test_sem_source_recomputed_from_sd_column(self):
        dataset = _g3_dataset([["A", "1", "1", "1"]], header=("组", "值", "SD", "SEM"))
        # SEM=1, SD=1, n=1 -> sqrt(1)=1 -> consistent
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sem"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "ok"

    def test_sem_value_mismatch_is_error(self):
        dataset = _g3_dataset([["A", "1", "1", "9"]], header=("组", "值", "SD", "SEM"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sem", "column": "SEM"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "error"
        assert findings[0]["evidence"]["gate_id"] == "G3_SEM_MISMATCH"

    def test_sem_missing_all_sources_is_error(self):
        dataset = _g3_dataset([["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sem"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert findings[0]["evidence"]["gate_id"] == "G3_SEM_SOURCE_MISSING"

    def test_ci_pair_found(self):
        dataset = _g3_dataset([["A", "1", "0.5", "1.5"]], header=("组", "值", "CI下限", "CI上限"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "ci"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "ok" and findings == []

    def test_ci_single_declared_column_is_error(self):
        dataset = _g3_dataset([["A", "1", "0.5", "1.5"]], header=("组", "值", "CI下限", "CI上限"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "ci", "column": "CI下限"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert findings[0]["evidence"]["gate_id"] == "G3_CI_INCOMPLETE"

    def test_ci_missing_upper_is_error(self):
        dataset = _g3_dataset([["A", "1", "0.5"]], header=("组", "值", "CI下限"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "ci"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert findings[0]["evidence"]["gate_id"] == "G3_CI_INCOMPLETE"

    def test_n_matches_group_count(self):
        dataset = _g3_dataset([["A", "1", "2"], ["A", "2", "2"]], header=("组", "值", "样本数"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "n"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert declarations[0]["status"] == "ok" and findings == []

    def test_n_mismatch_is_error(self):
        dataset = _g3_dataset([["A", "1", "9"]], header=("组", "值", "样本数"))
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "n"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert findings[0]["evidence"]["gate_id"] == "G3_N_MISMATCH"

    def test_n_source_missing_is_error(self):
        dataset = _g3_dataset([["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "n"})
        declarations, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert findings[0]["evidence"]["gate_id"] == "G3_N_SOURCE_MISSING"

    def test_title_sd_without_source_is_error(self):
        dataset = _g3_dataset([["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="group_mean", title="均值±SD")
        declarations, findings, title_declared, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert title_declared == "sd" and findings[0]["rule_id"] == spec.RULE_G3_SOURCE

    def test_title_sem_without_source_is_error(self):
        dataset = _g3_dataset([["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="group_mean", title="均值±SEM")
        _d, findings, _t, _s = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert findings[0]["evidence"]["gate_id"] == "G3_SEM_WITHOUT_SOURCE"

    def test_undeclared_sd_column_is_info(self):
        dataset = _g3_dataset([["A", "1", "0.1"]], header=("组", "值", "SD"))
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        _d, findings, _t, suspicious = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert suspicious == ["SD"]
        assert findings[0]["rule_id"] == spec.RULE_G3_UNDECLARED

    def test_undeclared_sem_column_is_info(self):
        dataset = _g3_dataset([["A", "1", "0.1"]], header=("组", "值", "标准误"))
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        _d, findings, _t, suspicious = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert "标准误" in suspicious

    def test_undeclared_empty_sd_column_not_suspicious(self):
        dataset = _g3_dataset([["A", "1", ""]], header=("组", "值", "SD"))
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        _d, _f, _t, suspicious = gates.audit_g3(dataset, spec_obj, SETTINGS)
        assert suspicious == []


# ════════════════════════════════════════════════════════════════════════
# 7. 器官编排（evaluate -> 缺陷账本）
# ════════════════════════════════════════════════════════════════════════
class TestEvaluate:
    def test_sample_is_clean(self):
        assert _evaluate() == []

    def test_sample_report_exit_zero(self):
        report = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="sample", records=_evaluate())
        assert report.exit_code() == EXIT_OK and report.summary()["total"] == 0

    def test_every_record_has_complete_basis(self):
        subject = _subject(spec_obj=_spec(mark="bar", y_zero=False, dual_y=True, smooth=True))
        records = _evaluate(subject)
        for record in records:
            assert record.basis is not None and record.basis.complete
            assert record.basis.rule_id == record.rule_id

    def test_record_ids_are_unique(self):
        subject = _subject(spec_obj=_spec(mark="bar", y_zero=False, dual_y=True, smooth=True))
        ids = [record.id for record in _evaluate(subject)]
        assert len(ids) == len(set(ids))

    def test_report_blocks_on_rule_error(self):
        subject = _subject(spec_obj=_spec(mark="bar", y_zero=False))
        report = Report(product="byteproof", organ=SLUG, organ_version="1", subject="x", records=_evaluate(subject))
        assert report.exit_code() == EXIT_BLOCKED

    def test_bar_rule_record(self):
        records = _evaluate(_subject(spec_obj=_spec(mark="bar", y_zero=False)))
        assert [record.rule_id for record in records] == [spec.RULE_BAR]

    def test_dual_y_rule_record(self):
        records = _evaluate(_subject(spec_obj=_spec(mark="line", dual_y=True)))
        assert [record.rule_id for record in records] == [spec.RULE_DUAL_Y]

    def test_3d_rule_record(self):
        records = _evaluate(_subject(spec_obj=_spec(mark="bar", pseudo_3d=True)))
        assert [record.rule_id for record in records] == [spec.RULE_3D]

    def test_radius_rule_record(self):
        records = _evaluate(_subject(spec_obj=_spec(mark="scatter", size_channel="radius")))
        assert [record.rule_id for record in records] == [spec.RULE_RADIUS]

    def test_smooth_rule_record(self):
        records = _evaluate(_subject(spec_obj=_spec(mark="line", smooth=True)))
        assert [record.rule_id for record in records] == [spec.RULE_SMOOTH]

    def test_contrast_rule_record(self):
        records = _evaluate(_subject(spec_obj=_spec(mark="bar", low_contrast=True)))
        assert [record.rule_id for record in records] == [spec.RULE_CONTRAST]

    def test_time_rule_record(self):
        dataset = _dataset(header=["月份", "值"],
                           rows=[["2026-01-01", "1"], ["2026-02-01", "1"], ["2026-03-01", "1"]],
                           types=["date", "decimal"])
        records = _evaluate(_subject(dataset=dataset, spec_obj=_spec(mark="line", x="月份")))
        assert [record.rule_id for record in records] == [spec.RULE_TIME]

    def test_pie_rule_record(self):
        rows = [["A", "1"], ["B", "1"], ["C", "1"], ["D", "1"], ["E", "1"]]
        records = _evaluate(_subject(dataset=_dataset(rows=rows), spec_obj=_spec(mark="pie")))
        assert [record.rule_id for record in records] == [spec.RULE_PIE]

    def test_provenance_missing_record(self):
        dataset = _dataset(rows=[["A", "10.00"]])
        spec_obj = _spec()
        prov = _prov(dataset, spec_obj, records=[])
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj, prov=prov))
        assert any(record.rule_id == spec.RULE_PROV_MISSING for record in records)

    def test_provenance_malformed_record(self):
        dataset = _dataset(rows=[["A", "10.00"]])
        spec_obj = _spec()
        prov = _prov(dataset, spec_obj)
        prov["spec_id"] = "other"
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj, prov=prov))
        assert any(record.rule_id == spec.RULE_PROV_MALFORMED for record in records)

    def test_provenance_mismatch_record(self):
        dataset = _dataset(rows=[["A", "10.00"]])
        spec_obj = _spec()
        prov = _prov(dataset, spec_obj)
        prov["rendered_values"][0]["match"] = False
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj, prov=prov))
        assert any(record.rule_id == spec.RULE_PROV_MISMATCH for record in records)

    def test_g2_violation_record(self):
        dataset = _grouped(["A"] * 4, ["1", "1", "1", "9"])
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj))
        assert any(record.rule_id == spec.RULE_G2_VIOLATION for record in records)

    def test_g2_undetermined_record(self):
        dataset = _grouped(["A", "A"], ["1", "2"])
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj))
        assert any(record.rule_id == spec.RULE_G2_UNDETERMINED for record in records)

    def test_g2_alternative_record(self):
        dataset = _grouped(["A"] * 4, ["1", "1", "1", "9"])
        spec_obj = _spec(mark="bar", aggregate="group_mean", overlay_scatter=True)
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj))
        assert any(record.rule_id == spec.RULE_G2_ALTERNATIVE for record in records)

    def test_g3_source_record(self):
        dataset = _g3_dataset([["A", "1"]])
        spec_obj = _spec(mark="bar", aggregate="group_mean", error_bar={"type": "sd"})
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj))
        assert any(record.rule_id == spec.RULE_G3_SOURCE for record in records)

    def test_g3_undeclared_record(self):
        dataset = _g3_dataset([["A", "1", "0.1"]], header=("组", "值", "SD"))
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        records = _evaluate(_subject(dataset=dataset, spec_obj=spec_obj))
        assert any(record.rule_id == spec.RULE_G3_UNDECLARED for record in records)

    def test_threshold_override_changes_g2(self):
        dataset = _grouped(["A"] * 5, ["1", "1", "1", "1", "9"])
        spec_obj = _spec(mark="bar", aggregate="group_mean")
        subject = _subject(dataset=dataset, spec_obj=spec_obj, params={"n_min": 10})
        records = _evaluate(subject)
        assert any(record.rule_id == spec.RULE_G2_VIOLATION for record in records)

    def test_dataset_missing_header_is_rejected(self):
        subject = _subject()
        del subject["dataset"]["header"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_dataset_rows_not_list_is_rejected(self):
        subject = _subject()
        subject["dataset"]["rows"] = "x"
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_dataset_columns_length_mismatch_is_rejected(self):
        subject = _subject()
        subject["dataset"]["columns"] = subject["dataset"]["columns"][:1]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_dataset_row_width_mismatch_is_rejected(self):
        subject = _subject()
        subject["dataset"]["rows"][0] = ["A"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_dataset_row_count_mismatch_is_rejected(self):
        subject = _subject()
        subject["dataset"]["row_count"] = 9
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_dataset_source_missing_is_rejected(self):
        subject = _subject()
        del subject["dataset"]["source"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_spec_missing_field_is_rejected(self):
        subject = _subject()
        del subject["spec"]["mark"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_spec_missing_encoding_x_is_rejected(self):
        subject = _subject()
        del subject["spec"]["encoding"]["x"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_provenance_non_mapping_is_rejected(self):
        subject = _subject()
        subject["provenance"] = []
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_provenance_missing_source_is_rejected(self):
        subject = _subject()
        del subject["provenance"]["source"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_unknown_param_is_rejected(self):
        subject = _subject()
        subject["params"] = {"shingle_size": 3}
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_report_is_deterministic(self):
        subject = _subject(spec_obj=_spec(mark="bar", y_zero=False, dual_y=True))
        def build():
            return Report(product="byteproof", organ=SLUG, organ_version="1", subject="x",
                          records=_evaluate(subject)).as_dict()
        assert json.dumps(build(), ensure_ascii=False) == json.dumps(build(), ensure_ascii=False)

    @pytest.mark.parametrize("rule_id,expected", [
        (spec.RULE_BAR, ERROR),
        (spec.RULE_DUAL_Y, ERROR),
        (spec.RULE_PIE, ERROR),
        (spec.RULE_3D, ERROR),
        (spec.RULE_RADIUS, ERROR),
        (spec.RULE_SMOOTH, ERROR),
        (spec.RULE_TIME, ERROR),
        (spec.RULE_CONTRAST, ERROR),
        (spec.RULE_SPEC_INVALID, ERROR),
        (spec.RULE_PROV_MISSING, ERROR),
        (spec.RULE_PROV_UNEXPECTED, ERROR),
        (spec.RULE_PROV_MALFORMED, ERROR),
        (spec.RULE_PROV_MISMATCH, ERROR),
        (spec.RULE_G2_VIOLATION, ERROR),
        (spec.RULE_G2_UNDETERMINED, WARN),
        (spec.RULE_G2_ALTERNATIVE, INFO),
        (spec.RULE_G3_SOURCE, ERROR),
        (spec.RULE_G3_UNDECLARED, INFO),
    ])
    def test_verdict_levels_are_pinned(self, rule_id, expected):
        assert spec.verdict_for(rule_id) == expected


# ════════════════════════════════════════════════════════════════════════
# 8. 唯一入口（CLI 0/1/2/3）
# ════════════════════════════════════════════════════════════════════════
class TestCli:
    def test_list_includes_organ(self, capsys):
        assert cli.main(["list"]) == EXIT_OK
        assert SLUG in capsys.readouterr().out

    def test_check_sample_returns_zero(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE)]) == EXIT_OK

    def test_check_sample_json(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["organ"] == SLUG and payload["summary"]["total"] == 0

    def test_check_blocked_subject_returns_one(self, tmp_path, capsys):
        subject = _subject(spec_obj=_spec(mark="bar", y_zero=False))
        path = tmp_path / "blocked.json"
        path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_BLOCKED

    def test_check_missing_input_file_returns_two(self):
        assert cli.main(["check", SLUG, "--input", "no-such.json"]) == EXIT_INPUT

    def test_check_invalid_json_returns_two(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT

    def test_check_missing_field_returns_two(self, tmp_path):
        path = tmp_path / "missing.json"
        path.write_text(json.dumps({"dataset": {}, "spec": {}}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT

    def test_check_empty_basis_returns_three(self, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text('{"version": "1", "rules": []}', encoding="utf-8")
        blocked = tmp_path / "blocked.json"
        blocked.write_text(
            json.dumps(_subject(spec_obj=_spec(mark="bar", y_zero=False)), ensure_ascii=False),
            encoding="utf-8",
        )
        assert cli.main(["check", SLUG, "--input", str(blocked), "--basis", str(empty)]) == EXIT_CONTRACT

    def test_check_unknown_slug_returns_three(self):
        assert cli.main(["check", "no-such", "--input", str(SAMPLE)]) == EXIT_CONTRACT

    def test_check_explicit_basis(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)]) == EXIT_OK

    def test_stdout_is_deterministic(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        first = capsys.readouterr().out
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        assert capsys.readouterr().out == first

    def test_json_summary_has_verdict_counts(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["verdicts"] == {"error": 0, "warn": 0, "info": 0}


# ════════════════════════════════════════════════════════════════════════
# 9. 接线与文档
# ════════════════════════════════════════════════════════════════════════
class TestWiringDocs:
    def test_pack_registered(self):
        assert get(SLUG) is PACK

    def test_pack_version(self):
        assert PACK.version == ORGAN_VERSION == "1"

    def test_input_fields(self):
        assert PACK.input_fields == ("dataset", "spec", "provenance")

    def test_builtin_modules_sorted(self):
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_builtin_modules_include_slug(self):
        assert "chart_integrity" in BUILTIN_MODULES

    def test_organ_directory_is_package(self):
        assert (SRC / "byteproof" / "auditors" / "chart_integrity" / "__init__.py").is_file()

    def test_no_clock_calls(self):
        for name in ("audit.py", "rules.py", "gates.py", "provenance.py"):
            text = (SRC / "byteproof" / "auditors" / "chart_integrity" / name).read_text(encoding="utf-8")
            assert "datetime.now(" not in text and "date.today(" not in text and "time.time(" not in text

    def test_no_network_imports(self):
        tree = ast.parse((SRC / "byteproof" / "auditors" / "chart_integrity" / "audit.py").read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "socket" not in names and "requests" not in names and "urllib" not in names

    def test_docs_page_exists(self):
        assert (ROOT / "docs" / (SLUG + ".md")).is_file()

    def test_docs_page_has_four_criteria(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        for marker in ("X = 222", "判据 4", "处置表", "口径差"):
            assert marker in text

    def test_docs_page_names_sample(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        assert "samples/chart-integrity.minimal.json" in text