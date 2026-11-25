"""``timeseries-anomaly`` 判定层补测（判据 1 · X = 551）。

本文件是**增量**：``tests/test_timeseries-anomaly.py`` 的 267 个 ``def test_`` 原样保留，
这里只补旧文件没有钉过的维度，按「每条规则 × 三态 + 边界」组织：

* 规则 × 账本：触发等级 / 依据原文 / 稳定 id / JSON 往返 / 双跑一致；
* 规则 × 边界：数值阈值的 below / equal / above 与公差计数；
* 规则 × 序列隔离：同一工件放到两条序列上，记录数、路径前缀各自独立；
* 规则 × 三态升级：``escalate_score_q`` 只把信号段从基线等级升到 ``error``，含等于边界；
* 规则 × 依据缺失：规则包里删掉该条 -> ``RuleMissing``（退出码 3 的来源）；
* 规则 × CLI：14 条规则各自触发件的退出码与 human/json 一致。

工件不读文件、不看时钟；夹具全部内联，或读本仓 ``samples/`` 下随包样例。
"""

from __future__ import annotations

import json
import re
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors.timeseries_anomaly import (  # noqa: E402
    audit,
    episodes,
    params,
    rules,
    subject,
    timeline,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    Basis,
    Report,
    RuleMissing,
)

SLUG = "timeseries-anomaly"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "timeseries-anomaly.basis.json"
BASIS_PAYLOAD = json.loads(BASIS_PATH.read_text(encoding="utf-8"))
BASIS = Basis.from_dict(BASIS_PAYLOAD)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _row(stamp, value, series_id=None):
    row = {"timestamp": stamp, "value": value}
    if series_id is not None:
        row["series_id"] = series_id
    return row


def _regular(n, values=None, series_id=None):
    base = timeline.parse_iso_to_epoch_ms("2024-03-01T00:00:00Z")
    return [
        _row(
            timeline.epoch_ms_to_iso(base + index * 300000),
            values[index] if values is not None else float(index),
            series_id,
        )
        for index in range(n)
    ]


def _flat(n, value=1.0):
    return _regular(n, values=[value] * n)


def _spike(n=40, at=39, amplitude=100.0):
    values = [0.0] * n
    values[at] = amplitude
    return _regular(n, values=values)


def _run(length=6, kind="missing", pad=7):
    body = [None] * length if kind == "missing" else [0.0] * length
    values = [1.0] * pad + body + [1.0] * pad
    return _regular(len(values), values=values)


def _evaluate(rows, overrides=None):
    payload = {"rows": rows}
    if overrides:
        payload["params"] = overrides
    return tuple(audit.evaluate(payload, BASIS))


def _with_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


def _merged(overrides, key, value):
    merged = dict(overrides or {})
    merged[key] = value
    return merged


def _series_prefix(path):
    return path.split("#")[0].split("@")[0]


#: A 触发矩阵：一件只触发该规则的工件（与旧文件同一条判定层口径，但断言在下面各矩阵）。
TRIGGER_CASES = (
    (rules.RULE_TIMESTAMP_UNREADABLE, [_row("2024-02-30T00:00:00Z", 1.0)], {}),
    (rules.RULE_VALUE_INVALID, [_row("2024-03-01T00:00:00Z", "abc")], {}),
    (
        rules.RULE_DUPLICATE_TIMESTAMP,
        [
            _row("2024-03-01T00:00:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
            _row("2024-03-01T00:00:00Z", 3.0),
        ],
        {},
    ),
    (
        rules.RULE_NON_MONOTONIC,
        [_row("2024-03-01T00:05:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
        {},
    ),
    (rules.RULE_GAP, _regular(6) + [_row("2024-03-01T02:00:00Z", 6.0)], {}),
    (rules.RULE_IRREGULAR_CADENCE, _regular(4) + [_row("2024-03-01T00:17:00Z", 4.0)], {}),
    (rules.RULE_MISSING_RUN, _run(6, "missing"), {}),
    (rules.RULE_ZERO_RUN, _run(6, "zero"), {}),
    (rules.RULE_STATIC_THRESHOLD, _flat(20), {"rules": {"static_threshold": 0.5}}),
    (
        rules.RULE_PCT_JUMP,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 3.0)],
        {},
    ),
    (rules.RULE_ROLLING_MAD_Z, _spike(), {}),
    (rules.RULE_ROLLING_IQR, _spike(), {}),
    (rules.RULE_CUSUM, _regular(40, values=[0.0] * 20 + [10.0] * 20), {}),
    (rules.RULE_STL_RESID_Z, _regular(80, values=[100.0 + index for index in range(80)]), {}),
)

#: 每条规则在触发件上的记录数（STL 两端各报一次，是旧仓继承行为）。
EXPECTED_COUNTS = {rule_id: 1 for rule_id, _rows, _overrides in TRIGGER_CASES}
EXPECTED_COUNTS[rules.RULE_STL_RESID_Z] = 2

#: B 静默矩阵：差一点就触发的同类工件。
QUIET_CASES = (
    (rules.RULE_TIMESTAMP_UNREADABLE, [_row("2024-02-29T00:00:00Z", 1.0)]),
    (rules.RULE_VALUE_INVALID, [_row("2024-03-01T00:00:00Z", None)]),
    (
        rules.RULE_DUPLICATE_TIMESTAMP,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
    ),
    (
        rules.RULE_NON_MONOTONIC,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 2.0)],
    ),
    (rules.RULE_GAP, _regular(6)),
    (rules.RULE_IRREGULAR_CADENCE, _regular(6)),
    (rules.RULE_MISSING_RUN, _run(5, "missing")),
    (rules.RULE_ZERO_RUN, _run(5, "zero")),
    (rules.RULE_STATIC_THRESHOLD, _flat(20)),
    (
        rules.RULE_PCT_JUMP,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 1.2)],
    ),
    (rules.RULE_ROLLING_MAD_Z, _flat(40)),
    (rules.RULE_ROLLING_IQR, _flat(40)),
    (rules.RULE_CUSUM, _flat(40)),
    (rules.RULE_STL_RESID_Z, _flat(40)),
)

SIGNAL_RULES = (
    rules.RULE_ROLLING_MAD_Z,
    rules.RULE_ROLLING_IQR,
    rules.RULE_STL_RESID_Z,
    rules.RULE_STATIC_THRESHOLD,
    rules.RULE_PCT_JUMP,
    rules.RULE_MISSING_RUN,
    rules.RULE_ZERO_RUN,
    rules.RULE_CUSUM,
)

#: 规则包里必有一条依据；信号规则还要在阈值台账里有一块参数。
DETECTOR_PARAM_KEYS = (
    "rolling_mad_z",
    "rolling_iqr",
    "stl_resid_z",
    "rules.static_threshold",
    "rules.pct_jump",
    "rules.missing_run",
    "rules.zero_run",
    "rules.cusum",
)


# ===========================================================================
# 1. 规则 × 账本
# ===========================================================================
class TestRuleLedgerMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_trigger_yields_the_documented_record_count(self, rule_id, rows, overrides):
        assert len(_with_rule(_evaluate(rows, overrides), rule_id)) == EXPECTED_COUNTS[rule_id], rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_trigger_reports_its_documented_verdict(self, rule_id, rows, overrides):
        for record in _with_rule(_evaluate(rows, overrides), rule_id):
            assert record.verdict == rules.verdict_for(rule_id), rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_id_is_rule_at_path(self, rule_id, rows, overrides):
        for record in _with_rule(_evaluate(rows, overrides), rule_id):
            assert record.id == "%s@%s" % (rule_id, record.path), rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_basis_quotes_the_shipped_rule_text(self, rule_id, rows, overrides):
        for record in _with_rule(_evaluate(rows, overrides), rule_id):
            assert record.basis.quote == BASIS.rule(rule_id).text, rule_id

    @pytest.mark.parametrize("rule_id,rows", QUIET_CASES)
    def test_the_quiet_case_never_emits_the_rule(self, rule_id, rows):
        assert _with_rule(_evaluate(rows), rule_id) == [], rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_every_record_survives_a_json_roundtrip(self, rule_id, rows, overrides):
        for record in _with_rule(_evaluate(rows, overrides), rule_id):
            payload = json.loads(json.dumps(record.as_dict(), ensure_ascii=False))
            assert payload["rule_id"] == rule_id
            assert payload["basis_ref"]["rule_id"] == rule_id
            assert payload["basis_ref"]["rule_version"]

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_two_runs_return_the_same_ids(self, rule_id, rows, overrides):
        first = [record.id for record in _evaluate(rows, overrides)]
        second = [record.id for record in _evaluate(rows, overrides)]
        assert first == second, rule_id


# ===========================================================================
# 2. 规则 × 序列隔离
# ===========================================================================
def _on_two_series(rows):
    both = []
    for series_id in ("a", "b"):
        both.extend(dict(row, series_id=series_id) for row in rows)
    return both


class TestSeriesIsolationMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_two_series_double_the_record_count(self, rule_id, rows, overrides):
        records = _with_rule(_evaluate(_on_two_series(rows), overrides), rule_id)
        assert len(records) == 2 * EXPECTED_COUNTS[rule_id], rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_each_series_keeps_its_own_path_prefix(self, rule_id, rows, overrides):
        records = _with_rule(_evaluate(_on_two_series(rows), overrides), rule_id)
        prefixes = {_series_prefix(record.path) for record in records}
        assert prefixes == {"a", "b"}, rule_id


# ===========================================================================
# 3. 规则 × 三态升级（warn/info -> error 的唯一开关）
# ===========================================================================
def _escalation_records(rule_id, rows, overrides, escalate):
    params_ = _merged(overrides, "escalate_score_q", escalate)
    return _with_rule(_evaluate(rows, params_), rule_id)


class TestEscalationMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", [case for case in TRIGGER_CASES if case[0] in SIGNAL_RULES])
    def test_escalating_at_the_lowest_peak_turns_every_record_into_error(self, rule_id, rows, overrides):
        peaks = [record.evidence["peak_score_q"] for record in _with_rule(_evaluate(rows, overrides), rule_id)]
        records = _escalation_records(rule_id, rows, overrides, min(peaks))
        assert records and {record.verdict for record in records} == {ERROR}, rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", [case for case in TRIGGER_CASES if case[0] in SIGNAL_RULES])
    def test_escalating_above_the_highest_peak_keeps_the_baseline_verdict(self, rule_id, rows, overrides):
        peaks = [record.evidence["peak_score_q"] for record in _with_rule(_evaluate(rows, overrides), rule_id)]
        baseline = rules.verdict_for(rule_id)
        records = _escalation_records(rule_id, rows, overrides, max(peaks) + 1)
        assert {record.verdict for record in records} == {baseline}, rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", [case for case in TRIGGER_CASES if case[0] in SIGNAL_RULES])
    def test_only_records_at_or_above_the_escalation_line_are_promoted(self, rule_id, rows, overrides):
        peaks = [record.evidence["peak_score_q"] for record in _with_rule(_evaluate(rows, overrides), rule_id)]
        line = min(peaks) + 1
        records = _escalation_records(rule_id, rows, overrides, line)
        assert sum(1 for record in records if record.verdict == ERROR) == sum(1 for peak in peaks if peak >= line)


# ===========================================================================
# 4. 规则 × 数值边界
# ===========================================================================
PCT_JUMP_SWEEP = (
    (0.1, 1),
    (0.35, 1),
    (1.0, 1),
    (1.9, 1),
    (2.0, 0),
    (2.1, 0),
    (5.0, 0),
)
STATIC_SWEEP = (
    (0.5, 0.5, 0),
    (0.5, 1.0, 0),
    (0.5, 1.5, 0),
    (1.0, 0.5, 1),
    (1.0, 1.0, 0),
    (1.0, 1.5, 0),
    (1.0001, 0.5, 1),
    (1.0001, 1.0, 1),
    (1.0001, 1.5, 0),
    (2.0, 0.5, 1),
    (2.0, 1.0, 1),
    (2.0, 1.5, 1),
)
DUPLICATE_TOLERANCE = ((0, 3), (1, 2), (2, 1), (3, 0))
BACKWARD_TOLERANCE = ((0, 3), (1, 2), (2, 1), (3, 0))
GAP_FACTOR_SWEEP = ((1, 1), (2, 1), (3, 1), (4, 0), (5, 0))
RUN_CROSS = tuple(
    (kind, rule_id, length, threshold, int(length >= threshold))
    for kind, rule_id in (("missing", rules.RULE_MISSING_RUN), ("zero", rules.RULE_ZERO_RUN))
    for length in (3, 6, 9)
    for threshold in (3, 6, 9, 10)
)
MERGE_SPLIT = ((6000000, (2,)), (36000000, (2,)), (1800000, (1, 1)))


def _run_rows(length, kind, pad=7):
    body = [None] * length if kind == "missing" else [0.0] * length
    values = [1.0] * pad + body + [1.0] * pad
    return _regular(len(values), values=values)


class TestThresholdBoundaryMatrix:
    @pytest.mark.parametrize("threshold,expected", PCT_JUMP_SWEEP)
    def test_pct_jump_is_strictly_greater(self, threshold, expected):
        rows = [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 3.0)]
        assert len(_with_rule(_evaluate(rows, {"rules": {"pct_jump": threshold}}), rules.RULE_PCT_JUMP)) == expected

    @pytest.mark.parametrize("value,threshold,expected", STATIC_SWEEP)
    def test_static_threshold_is_strictly_greater(self, value, threshold, expected):
        rows = _flat(20, value)
        hits = _with_rule(_evaluate(rows, {"rules": {"static_threshold": threshold}}), rules.RULE_STATIC_THRESHOLD)
        assert len(hits) == expected

    @pytest.mark.parametrize("tolerance,expected", DUPLICATE_TOLERANCE)
    def test_duplicate_tolerance_counts_the_extra_rows(self, tolerance, expected):
        rows = [_row("2024-03-01T00:00:00Z", float(index)) for index in range(4)]
        hits = _with_rule(_evaluate(rows, {"duplicate_timestamp_max": tolerance}), rules.RULE_DUPLICATE_TIMESTAMP)
        assert len(hits) == expected

    @pytest.mark.parametrize("tolerance,expected", BACKWARD_TOLERANCE)
    def test_backward_tolerance_counts_the_extra_steps(self, tolerance, expected):
        rows = [
            _row("2024-03-01T00:15:00Z", 1.0),
            _row("2024-03-01T00:10:00Z", 2.0),
            _row("2024-03-01T00:05:00Z", 3.0),
            _row("2024-03-01T00:00:00Z", 4.0),
        ]
        hits = _with_rule(_evaluate(rows, {"non_monotonic_max": tolerance}), rules.RULE_NON_MONOTONIC)
        assert len(hits) == expected

    @pytest.mark.parametrize("factor,expected", GAP_FACTOR_SWEEP)
    def test_gap_factor_boundary_is_strictly_greater(self, factor, expected):
        rows = _regular(4) + [_row("2024-03-01T00:35:00Z", 4.0)]
        assert len(_with_rule(_evaluate(rows, {"gap_factor": factor}), rules.RULE_GAP)) == expected

    @pytest.mark.parametrize("kind,rule_id,length,threshold,expected", RUN_CROSS)
    def test_run_rules_cross_the_threshold(self, kind, rule_id, length, threshold, expected):
        rows = _run_rows(length, kind)
        assert len(_with_rule(_evaluate(rows, {"rules": {"missing_run": threshold}}), rule_id)) == expected

    @pytest.mark.parametrize("max_gap,expected_points", MERGE_SPLIT)
    def test_max_gap_decides_merge_in_the_time_domain(self, max_gap, expected_points):
        values = [0.0] * 40
        values[10] = 100.0
        values[30] = 100.0
        rows = _regular(40, values=values)
        hits = _with_rule(_evaluate(rows, {"max_gap_ms": max_gap}), rules.RULE_ROLLING_MAD_Z)
        assert tuple(hit.evidence["n_points"] for hit in hits) == expected_points


# ===========================================================================
# 5. 时间戳往返
# ===========================================================================
TIMESTAMP_FORMS = (
    "2024-02-29T00:00:00Z",
    "2024-02-29 00:00:00Z",
    "2024-02-29T00:00Z",
    "2024-02-29T00:00:00",
    "2024-02-29T00:00:00.1Z",
    "2024-02-29T00:00:00.12Z",
    "2024-02-29T00:00:00.123Z",
    "2024-02-29T00:00:00.123456Z",
    "2024-02-29T00:00:00.123456789Z",
    "2024-02-29T00:00:00+00:00",
    "2024-02-29T00:00:00+0800",
    "2024-02-29T00:00:00+08",
    "2024-02-29T00:00:00-08:00",
    "2024-02-29T00:00:00z",
    "1970-01-01T00:00:00Z",
    "1969-12-31T23:59:59.999Z",
    "2100-12-31T23:59Z",
    "2024-02-29T23:59:59Z",
    "2000-02-29T00:00:00Z",
    "2024-01-01T00:00:00+14:00",
    "2024-01-01T00:00:00-11:00",
    "2024-12-31T23:59:59.999999Z",
    " 2024-02-29T00:00:00Z ",
    "2024-03-01T00:00:00+08:00",
    "2023-12-31T23:59:59Z",
    "2024-02-28T23:59:59.999999999Z",
)


class TestTimestampRoundTripMatrix:
    @pytest.mark.parametrize("text", TIMESTAMP_FORMS)
    def test_the_canonical_form_parses_back_to_the_same_epoch(self, text):
        stamp = timeline.parse_timestamp(text)
        canonical = timeline.epoch_ms_to_iso(stamp.epoch_ms)
        assert canonical.endswith("Z")
        assert timeline.parse_timestamp(canonical).epoch_ms == stamp.epoch_ms


# ===========================================================================
# 6. 定点化
# ===========================================================================
QUANT_VALUES = (0.5, 1.5, 2.5, -0.5, -1.5, -2.5, 1.2345675, -1.2345675)
QUANT_GRID = tuple((decimals, value) for decimals in (0, 1, 2, 3, 6) for value in QUANT_VALUES)


def _half_even(value, decimals):
    scaled = Decimal(str(value)).scaleb(decimals)
    return int(scaled.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


class TestQuantizeMatrix:
    @pytest.mark.parametrize("decimals,value", QUANT_GRID)
    def test_half_to_even_matches_the_decimal_reference(self, decimals, value):
        assert params.quantize(value, decimals) == _half_even(value, decimals)

    @pytest.mark.parametrize("decimals,value", QUANT_GRID)
    def test_the_render_keeps_the_requested_precision(self, decimals, value):
        quantized = params.quantize(value, decimals)
        rendered = params.fixed_to_str(quantized, decimals)
        assert rendered == "%.*f" % (decimals, quantized / (10 ** decimals))
        assert params.quantize(float(rendered), decimals) == quantized


# ===========================================================================
# 7. 规则 × 依据缺失
# ===========================================================================
class TestMissingRuleMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_removing_the_rule_from_the_basis_is_a_contract_violation(self, rule_id, rows, overrides):
        reduced = Basis.from_dict(
            {
                "version": BASIS_PAYLOAD["version"],
                "rules": [item for item in BASIS_PAYLOAD["rules"] if item["rule_id"] != rule_id],
            }
        )
        payload = {"rows": rows}
        if overrides:
            payload["params"] = overrides
        with pytest.raises(RuleMissing) as excinfo:
            audit.evaluate(payload, reduced)
        assert rule_id in str(excinfo.value)


# ===========================================================================
# 8. 规则 × CLI
# ===========================================================================
class TestCliMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_exit_code_follows_the_rule_verdict(self, rule_id, rows, overrides, tmp_path, capsys):
        payload = {"rows": rows}
        if overrides:
            payload["params"] = overrides
        target = tmp_path / ("%s.json" % rule_id)
        target.write_text(json.dumps(payload), encoding="utf-8")
        expected = EXIT_BLOCKED if rules.verdict_for(rule_id) == ERROR else EXIT_OK
        assert cli.main(["check", SLUG, "--input", str(target)]) == expected, rule_id
        capsys.readouterr()

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_human_and_json_agree_on_the_totals(self, rule_id, rows, overrides, tmp_path, capsys):
        payload = {"rows": rows}
        if overrides:
            payload["params"] = overrides
        target = tmp_path / ("%s.json" % rule_id)
        target.write_text(json.dumps(payload), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        report = json.loads(capsys.readouterr().out)
        cli.main(["check", SLUG, "--input", str(target)])
        human = capsys.readouterr().out
        assert "合计 %d 条" % report["summary"]["total"] in human, rule_id
        assert "阻断 %d 条" % report["summary"]["blocking"] in human


# ===========================================================================
# 9. 账本顺序与唯一性
# ===========================================================================
class TestLedgerOrderMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_ledger_is_sorted_by_the_kernel_key(self, rule_id, rows, overrides):
        report = Report(
            product="byteproof",
            organ=SLUG,
            organ_version="1",
            subject=rule_id,
            records=_evaluate(rows, overrides),
        )
        keys = [(record.rule_id, record.verdict, record.path, record.message) for record in report.records]
        assert keys == sorted(keys), rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_ids_are_unique_on_the_trigger(self, rule_id, rows, overrides):
        ids = [record.id for record in _evaluate(rows, overrides)]
        assert len(ids) == len(set(ids)), rule_id


# ===========================================================================
# 10. 默认序列名
# ===========================================================================
class TestDefaultSeriesMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_rows_without_series_id_land_in_the_default_series(self, rule_id, rows, overrides):
        records = _with_rule(_evaluate(rows, overrides), rule_id)
        assert {_series_prefix(record.path) for record in records} == {"series"}, rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_default_series_name_is_overridable(self, rule_id, rows, overrides):
        params_ = _merged(overrides, "default_series_id", "metric")
        records = _with_rule(_evaluate(rows, params_), rule_id)
        assert {_series_prefix(record.path) for record in records} == {"metric"}, rule_id


# ===========================================================================
# 11. 规则命名空间与依据台账
# ===========================================================================
class TestRuleNamespaceMatrix:
    @pytest.mark.parametrize("rule_id", rules.RULE_IDS)
    def test_the_rule_id_is_namespaced_and_well_formed(self, rule_id):
        assert re.fullmatch(r"ts-[a-z0-9-]+", rule_id)
        assert rule_id in rules.VERDICT_BY_RULE
        assert rules.RULE_IDS.count(rule_id) == 1


class TestThresholdTableMatrix:
    @pytest.mark.parametrize("rule_id", rules.RULE_IDS)
    def test_the_thresholds_file_pins_the_verdict(self, rule_id):
        assert BASIS_PAYLOAD["rules"]
        payload = json.loads(
            (DATA_DIR / "timeseries-anomaly.thresholds.json").read_text(encoding="utf-8")
        )
        assert payload["verdicts"][rule_id] == rules.VERDICT_BY_RULE[rule_id]

    @pytest.mark.parametrize("param_key", DETECTOR_PARAM_KEYS)
    def test_every_signal_detector_has_a_threshold_block(self, param_key):
        refs = params.threshold_refs(params.dump_params(params.resolve_params()))
        assert param_key in refs


# ===========================================================================
# 12. 值单元格
# ===========================================================================
VALUE_ACCEPTED = (
    (None, None),
    ("", None),
    ("   ", None),
    ("NA", None),
    ("n/a", None),
    ("NaN", None),
    ("null", None),
    ("none", None),
    ("-", None),
    ("--", None),
    (0, 0.0),
    (0.0, 0.0),
    (-0.0, 0.0),
    (-1, -1.0),
    (12.5, 12.5),
    ("12.5", 12.5),
    ("+1.5", 1.5),
    (".5", 0.5),
    ("1.", 1.0),
    ("1e3", 1000.0),
)
VALUE_REJECTED = (
    "abc",
    "1_000",
    "0x10",
    "1,000",
    "12.5x",
    "inf",
    "-inf",
    "Infinity",
    "1 2",
    "1.2.3",
    True,
    False,
    [1.0],
    {"v": 1},
    float("inf"),
    float("nan"),
)


class TestValueCellMatrix:
    @pytest.mark.parametrize("cell,expected", VALUE_ACCEPTED)
    def test_an_accepted_cell_reads_to_its_value(self, cell, expected):
        assert subject.parse_value(cell, 1) == expected

    @pytest.mark.parametrize("cell", VALUE_REJECTED)
    def test_a_rejected_cell_raises(self, cell):
        with pytest.raises(ValueError):
            subject.parse_value(cell, 1)


# ===========================================================================
# 13. 断档的位置与形状
# ===========================================================================
GAP_PLACEMENT = (
    (4, 4, 3),
    (6, 3, 5),
    (6, 6, 11),
    (10, 5, 3),
    (10, 10, 8),
    (3, 2, 20),
    (24, 24, 29),
    (24, 20, 59),
)


def _gap_rows(total, gap_at, missing):
    base = timeline.parse_iso_to_epoch_ms("2024-03-01T00:00:00Z")
    rows = []
    for index in range(total):
        cell = index + (missing if index >= gap_at - 1 else 0)
        rows.append(_row(timeline.epoch_ms_to_iso(base + cell * 300000), float(index)))
    return rows


class TestGapPlacementMatrix:
    @pytest.mark.parametrize("total,gap_at,missing", GAP_PLACEMENT)
    def test_the_gap_reports_the_missing_points(self, total, gap_at, missing):
        hits = _with_rule(_evaluate(_gap_rows(total, gap_at, missing)), rules.RULE_GAP)
        assert [hit.evidence["missing_points"] for hit in hits] == [missing]

    @pytest.mark.parametrize("total,gap_at,missing", GAP_PLACEMENT)
    def test_the_gap_interval_is_one_dominant_plus_the_missing_points(self, total, gap_at, missing):
        hits = _with_rule(_evaluate(_gap_rows(total, gap_at, missing)), rules.RULE_GAP)
        hit = hits[0]
        assert hit.evidence["interval_ms"] == (missing + 1) * hit.evidence["dominant_interval_ms"]


# ===========================================================================
# 14. 多段与混合段
# ===========================================================================
class TestMultiRunMatrix:
    def test_two_missing_runs_inside_one_episode(self):
        values = [1.0] * 5 + [None] * 6 + [1.0] * 3 + [None] * 6 + [1.0] * 5
        rows = _regular(len(values), values=values)
        hits = _with_rule(_evaluate(rows), rules.RULE_MISSING_RUN)
        assert len(hits) == 1
        assert hits[0].evidence["n_points"] == 12

    def test_two_missing_runs_split_by_a_narrow_merge_window(self):
        values = [1.0] * 5 + [None] * 6 + [1.0] * 3 + [None] * 6 + [1.0] * 5
        rows = _regular(len(values), values=values)
        hits = _with_rule(_evaluate(rows, {"max_gap_ms": 600000}), rules.RULE_MISSING_RUN)
        assert len(hits) == 2
        assert [hit.evidence["run_length"] for hit in hits] == [6, 6]

    def test_two_zero_runs_inside_one_episode(self):
        values = [1.0] * 5 + [0.0] * 6 + [1.0] * 3 + [0.0] * 6 + [1.0] * 5
        rows = _regular(len(values), values=values)
        hits = _with_rule(_evaluate(rows), rules.RULE_ZERO_RUN)
        assert len(hits) == 1
        assert hits[0].evidence["n_points"] == 12

    def test_two_zero_runs_split_by_a_narrow_merge_window(self):
        values = [1.0] * 5 + [0.0] * 6 + [1.0] * 3 + [0.0] * 6 + [1.0] * 5
        rows = _regular(len(values), values=values)
        hits = _with_rule(_evaluate(rows, {"max_gap_ms": 600000}), rules.RULE_ZERO_RUN)
        assert len(hits) == 2
        assert [hit.evidence["run_length"] for hit in hits] == [6, 6]

    def test_a_missing_run_and_a_zero_run_are_two_rules(self):
        values = [1.0] * 5 + [None] * 6 + [1.0] * 3 + [0.0] * 6 + [1.0] * 5
        rows = _regular(len(values), values=values)
        records = _evaluate(rows)
        assert len(_with_rule(records, rules.RULE_MISSING_RUN)) == 1
        assert len(_with_rule(records, rules.RULE_ZERO_RUN)) == 1


# ===========================================================================
# 15. Episode 编号与全序
# ===========================================================================
MERGE_UNIT = (
    ((0,), 0, 1),
    ((0, 1), 299999, 2),
    ((0, 1), 300000, 1),
    ((0, 5), 1800000, 1),
    ((0, 6), 1800000, 1),
    ((0, 6), 1799999, 2),
)
ID_CASES = (
    (("a", "a", "b"), ("a-E001", "a-E002", "b-E001")),
    (("b", "a", "b"), ("b-E001", "a-E001", "b-E002")),
    (("x",), ("x-E001",)),
    (("a", "b", "a"), ("a-E001", "b-E001", "a-E002")),
)
ORDER_CASES = (
    ({"peak_score_q": 10, "duration_ms": 1, "start_row": 1, "detector": "x"}, "higher peak first"),
    ({"peak_score_q": 5, "duration_ms": 9, "start_row": 1, "detector": "x"}, "longer duration first"),
    ({"peak_score_q": 5, "duration_ms": 9, "start_row": 2, "detector": "x"}, "later start last"),
)


class TestEpisodeUnitMatrix:
    @pytest.mark.parametrize("indices,max_gap,expected", MERGE_UNIT)
    def test_merge_counts_are_time_based(self, indices, max_gap, expected):
        stamps = [index * 300000 for index in range(12)]
        points = [(stamps[index], index + 1, 1.0) for index in indices]
        assert len(episodes.merge_episodes("s", "rolling_mad_z", points, max_gap)) == expected

    @pytest.mark.parametrize("series_ids,expected", ID_CASES)
    def test_ids_number_per_series(self, series_ids, expected):
        built = [
            {"series_id": series_id, "peak_score_q": 1, "duration_ms": 0, "start_row": 1, "detector": "d"}
            for series_id in series_ids
        ]
        assert [episode["episode_id"] for episode in episodes.assign_ids(built)] == list(expected)

    @pytest.mark.parametrize("worse,label", ORDER_CASES)
    def test_a_worse_episode_sorts_first(self, worse, label):
        better = dict(worse)
        better["peak_score_q"] = 1
        ordered = episodes.order_episodes([better, worse])
        assert ordered[0] is worse, label


# ===========================================================================
# 16. 周期来源
# ===========================================================================
PERIOD_CASES = (
    ("no-cycle-default", _spike(), {}),
    ("estimated", _regular(60, values=[float(index % 12) for index in range(60)]), {}),
    ("estimated", _regular(96, values=[float(index % 24) for index in range(96)]), {}),
    ("declared", _spike(), {"period_points": 12}),
)


class TestPeriodSourceMatrix:
    @pytest.mark.parametrize("source,rows,overrides", PERIOD_CASES)
    def test_the_episode_reports_where_the_period_came_from(self, source, rows, overrides):
        for record in _evaluate(rows, overrides):
            if "period_source" in record.evidence:
                assert record.evidence["period_source"] == source

    @pytest.mark.parametrize("source,rows,overrides", PERIOD_CASES)
    def test_the_reported_period_is_positive(self, source, rows, overrides):
        for record in _evaluate(rows, overrides):
            if "period_points" in record.evidence:
                assert record.evidence["period_points"] >= 1


# ===========================================================================
# 17. 坏信封（退出码 2 / 3）
# ===========================================================================
BAD_ENVELOPE = (
    ("not_json", "not json", EXIT_INPUT),
    ("array", "[1, 2]", EXIT_INPUT),
    ("rows_string", '{"rows": "x"}', EXIT_INPUT),
    ("rows_empty", '{"rows": []}', EXIT_INPUT),
    ("missing_rows", '{"other": 1}', EXIT_INPUT),
    ("unknown_param", '{"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0}], "params": {"nope": 1}}', EXIT_INPUT),
)


class TestEnvelopeExtraMatrix:
    @pytest.mark.parametrize("case_id,text,expected", BAD_ENVELOPE)
    def test_a_bad_envelope_exits_two(self, case_id, text, expected, tmp_path, capsys):
        target = tmp_path / ("%s.json" % case_id)
        target.write_text(text, encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == expected
        capsys.readouterr()

    def test_a_missing_input_file_exits_two(self, tmp_path):
        assert cli.main(["check", SLUG, "--input", str(tmp_path / "nope.json")]) == EXIT_INPUT

    def test_an_empty_basis_exits_three(self, tmp_path, capsys):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": _spike()}), encoding="utf-8")
        basis = tmp_path / "basis.json"
        basis.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target), "--basis", str(basis)]) == EXIT_CONTRACT
        assert "RuleMissing" in capsys.readouterr().err


# ===========================================================================
# 18. JSON 确定性
# ===========================================================================
class TestDeterministicJsonMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_report_dict_is_byte_identical_across_runs(self, rule_id, rows, overrides):
        def dump():
            records = _evaluate(rows, overrides)
            report = Report(product="byteproof", organ=SLUG, organ_version="1", subject=rule_id, records=records)
            return json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=False)

        assert dump() == dump()


# ===========================================================================
# 19. 行序无关
# ===========================================================================
#: 行级规则的路径带 ``#row=``，行序挪动会改变它（那是语义，不是缺陷）；
#: 其余规则的路径是时间或形状标签，序列交错不该改变账本。
ROW_INDEXED_RULES = (
    rules.RULE_TIMESTAMP_UNREADABLE,
    rules.RULE_VALUE_INVALID,
    rules.RULE_DUPLICATE_TIMESTAMP,
    rules.RULE_NON_MONOTONIC,
)
ORDER_FREE_CASES = tuple(case for case in TRIGGER_CASES if case[0] not in ROW_INDEXED_RULES)


class TestSeriesOrderMatrix:
    @pytest.mark.parametrize("rule_id,rows,overrides", ORDER_FREE_CASES)
    def test_interleaving_the_series_does_not_change_the_ledger(self, rule_id, rows, overrides):
        grouped = []
        for series_id in ("a", "b"):
            grouped.extend(dict(row, series_id=series_id) for row in rows)
        interleaved = []
        for row in rows:
            interleaved.append(dict(row, series_id="a"))
            interleaved.append(dict(row, series_id="b"))
        assert [record.id for record in _evaluate(interleaved, overrides)] == [
            record.id for record in _evaluate(grouped, overrides)
        ]