"""``fund-quarter-report`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那个函数仍然在、语义仍然是那一套**：
五态 diff、双口径冲突、失败季、经理四类、区间复算、规模六字段、合规扫描、披露窗口
都是逐条搬用旧仓 ``tests/test_diff.py`` / ``test_managers.py`` / ``test_scale.py`` /
``test_window.py`` / ``test_compliance.py`` 的断言，只把模块路径换成器官的模块路径。

**没迁的部分逐条写在 ``docs/fund-quarter-report.md`` §6 的处置表里**（抓取、HTML 解析、
配置包冻结、清单存储、报告渲染、基准、系统时钟）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 14 个判定层文件实跑 **X = 184 passed**（AST 函数 167）。
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.fund_quarter_report import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    compliance,
    holdings,
    managers,
    scale,
    spec,
    window,
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

SLUG = "fund-quarter-report"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "fund-quarter-report.basis.json"
THRESHOLDS_PATH = DATA_DIR / "fund-quarter-report.thresholds.json"
SAMPLE = ROOT / "samples" / "fund-quarter-report.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
QUARTER_ENDS = dict(spec.DEFAULT_QUARTER_ENDS)

CAL2026 = {
    "2026": {
        "holidays": [
            "2026-01-01", "2026-01-02", "2026-01-03",
            "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
            "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
            "2026-04-04", "2026-04-05", "2026-04-06",
            "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
            "2026-06-19", "2026-06-20", "2026-06-21",
            "2026-09-25", "2026-09-26", "2026-09-27",
            "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
            "2026-10-05", "2026-10-06", "2026-10-07",
        ],
        "makeup_workdays": [
            "2026-01-04", "2026-02-14", "2026-02-28",
            "2026-05-09", "2026-09-20", "2026-10-10",
        ],
    }
}
DISCLOSURE_OK = {"rule": {"kind": "workdays_after_period_end", "count": 15}, "calendar": CAL2026}


def _sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _evaluate(subject=None, basis=None):
    return list(audit.evaluate(subject if subject is not None else _sample(), basis or BASIS))


def _rules(records):
    return [record.rule_id for record in records]


def _by_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


def _row(code, ratio, change_type=None, change_pct=None, name=None):
    row = {"stock_code": code, "ratio": ratio, "change_type": change_type}
    if change_pct is not None:
        row["change_pct"] = change_pct
    if name is not None:
        row["stock_name"] = name
    return row


def _payload(period, rows, status="ok"):
    return {"report_period": period, "status": status, "rows": rows}


def _diff(prev_rows, cur_rows, mode="computed", threshold="0.10"):
    return holdings.diff_fund(
        _payload("2026Q2", prev_rows),
        _payload("2026Q3", cur_rows),
        Decimal(threshold),
        mode,
    )


def _subject(prev_rows, cur_rows, **extra):
    subject = {
        "fund_code": "990001",
        "period": "2026Q3",
        "prev_period": "2026Q2",
        "holdings": {"prev": _payload("2026Q2", prev_rows), "cur": _payload("2026Q3", cur_rows)},
    }
    subject.update(extra)
    return subject


# ════════════════════════════════════════════════════════════════════════
# 1. 参数面（spec）
# ════════════════════════════════════════════════════════════════════════
class TestSpec:
    def test_defaults_match_thresholds_file(self):
        document = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        params = document["params"]
        assert params["mode"] == spec.DEFAULT_SETTINGS.mode
        assert params["threshold"] == spec.DEFAULT_SETTINGS.threshold
        assert params["disclosure_count"] == spec.DEFAULT_SETTINGS.disclosure_count
        assert params["quarter_ends"] == dict(spec.DEFAULT_SETTINGS.quarter_ends)

    def test_verdict_table_matches_thresholds_file(self):
        document = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert document["verdicts"] == spec.VERDICT_BY_RULE

    def test_rule_ids_are_registered_and_unique(self):
        assert len(spec.RULE_IDS) == len(set(spec.RULE_IDS))
        assert set(spec.RULE_IDS) == set(spec.VERDICT_BY_RULE)

    def test_basis_pack_contains_every_rule(self):
        assert set(spec.RULE_IDS) <= set(BASIS.rule_ids())

    def test_default_mode_is_computed(self):
        assert spec.resolve_params(None).mode == "computed"

    def test_mode_override(self):
        assert spec.resolve_params({"mode": "provider"}).mode == "provider"

    def test_threshold_override(self):
        assert spec.resolve_params({"threshold": "0.25"}).threshold == "0.25"

    def test_disclosure_count_override(self):
        assert spec.resolve_params({"disclosure_count": 20}).disclosure_count == 20

    def test_quarter_ends_override(self):
        ends = {"Q1": "03-30", "Q2": "06-29", "Q3": "09-29", "Q4": "12-30"}
        assert spec.resolve_params({"quarter_ends": ends}).quarter_ends == ends

    def test_unknown_param_key_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"shingle_size": 3})

    def test_non_mapping_params_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params(["mode"])

    def test_unknown_mode_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"mode": "auto"})

    def test_non_decimal_threshold_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"threshold": "abc"})

    def test_zero_threshold_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"threshold": "0"})

    def test_negative_threshold_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"threshold": "-0.1"})

    def test_zero_disclosure_count_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"disclosure_count": 0})

    def test_boolean_disclosure_count_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"disclosure_count": True})

    def test_quarter_ends_missing_key_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"quarter_ends": {"Q1": "03-31"}})

    def test_quarter_ends_bad_format_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params(
                {"quarter_ends": {"Q1": "3-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}}
            )

    def test_verdict_for_unknown_rule_raises(self):
        with pytest.raises(ValueError):
            spec.verdict_for("no-such-rule")


# ════════════════════════════════════════════════════════════════════════
# 2. 报告期与披露窗口（旧仓 test_window.py）
# ════════════════════════════════════════════════════════════════════════
class TestWindow:
    def test_parse_period_returns_year_and_quarter(self):
        assert window.parse_period("2026Q3") == (2026, "Q3")

    def test_parse_period_rejects_q5(self):
        with pytest.raises(window.WindowError):
            window.parse_period("2026Q5")

    def test_parse_period_rejects_short_year(self):
        with pytest.raises(window.WindowError):
            window.parse_period("26Q3")

    def test_parse_period_rejects_hyphen(self):
        with pytest.raises(window.WindowError):
            window.parse_period("2026-Q3")

    def test_parse_period_rejects_non_string(self):
        with pytest.raises(window.WindowError):
            window.parse_period(2026)

    def test_previous_period_within_year(self):
        assert window.previous_period("2026Q3") == "2026Q2"

    def test_previous_period_crosses_year(self):
        assert window.previous_period("2026Q1") == "2025Q4"

    def test_period_end_of_q3(self):
        assert window.period_end_of(QUARTER_ENDS, "2026Q3") == date(2026, 9, 30)

    def test_window_bounds_start(self):
        start, _end = window.window_bounds(QUARTER_ENDS, "2026Q3")
        assert start.isoformat() == "2026-07-01"

    def test_window_bounds_end(self):
        _start, end = window.window_bounds(QUARTER_ENDS, "2026Q3")
        assert end.isoformat() == "2026-09-30"

    @pytest.mark.parametrize(
        "period,expected",
        [
            ("2025Q1", "2025-04-22"),
            ("2025Q2", "2025-07-21"),
            ("2025Q3", "2025-10-28"),
            ("2025Q4", "2026-01-22"),
            ("2026Q1", "2026-04-22"),
            ("2026Q2", "2026-07-21"),
            ("2026Q3", "2026-10-27"),
        ],
    )
    def test_deadlines_follow_workday_rule(self, period, expected):
        disclosure = {"rule": {"kind": "workdays_after_period_end", "count": 15}, "calendar": CAL2026}
        if period.startswith("2025"):
            disclosure = {
                "rule": {"kind": "workdays_after_period_end", "count": 15},
                "calendar": {
                    "2025": {
                        "holidays": [
                            "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30",
                            "2025-01-31", "2025-02-01", "2025-02-02", "2025-02-03",
                            "2025-02-04", "2025-04-04", "2025-04-05", "2025-04-06",
                            "2025-05-01", "2025-05-02", "2025-05-03", "2025-05-04",
                            "2025-05-05", "2025-05-31", "2025-06-01", "2025-06-02",
                            "2025-10-01", "2025-10-02", "2025-10-03", "2025-10-04",
                            "2025-10-05", "2025-10-06", "2025-10-07", "2025-10-08",
                        ],
                        "makeup_workdays": [
                            "2025-01-26", "2025-02-08", "2025-04-27", "2025-09-28", "2025-10-11"
                        ],
                    },
                    "2026": CAL2026["2026"],
                },
            }
        info = window.window_for_period(period, QUARTER_ENDS, disclosure)
        assert info["disclosure_deadline"] == expected
        assert info["unverified"] is False
        assert info["deadline_rule"] == "workdays_after_period_end"
        assert info["deadline_count"] == 15

    def test_missing_calendar_is_not_approximated(self):
        info = window.window_for_period("2026Q4", QUARTER_ENDS, DISCLOSURE_OK)
        assert info["disclosure_deadline"] is None
        assert info["unverified"] is True
        assert info["unverified_reason"] == "calendar_missing:2027"
        assert info["calendar_years"] == []

    def test_deadline_rolls_into_next_year(self):
        info = window.window_for_period("2025Q4", QUARTER_ENDS, {"rule": {"kind": "workdays_after_period_end", "count": 15}, "calendar": CAL2026})
        assert info["disclosure_deadline"] == "2026-01-22"
        assert info["calendar_years"] == ["2026"]

    def test_deadline_count_comes_from_subject(self):
        disclosure = {"rule": {"kind": "workdays_after_period_end", "count": 1}, "calendar": CAL2026}
        assert window.window_for_period("2026Q3", QUARTER_ENDS, disclosure)["disclosure_deadline"] == "2026-10-08"

    def test_unknown_deadline_rule_is_rejected(self):
        with pytest.raises(window.WindowError):
            window.window_for_period("2026Q3", QUARTER_ENDS, {"rule": {"kind": "fixed_date", "count": 15}})

    def test_non_positive_deadline_count_is_rejected(self):
        with pytest.raises(window.WindowError):
            window.window_for_period("2026Q3", QUARTER_ENDS, {"rule": {"kind": "workdays_after_period_end", "count": 0}})

    def test_non_mapping_calendar_is_rejected(self):
        with pytest.raises(window.WindowError):
            window.window_for_period("2026Q3", QUARTER_ENDS, {"calendar": []})

    def test_invalid_quarter_end_is_rejected(self):
        with pytest.raises(window.WindowError):
            window.period_end_of({"Q1": "02-30", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}, "2026Q1")

    def test_parse_date_accepts_iso(self):
        assert window.parse_date("2026-10-18") == date(2026, 10, 18)

    @pytest.mark.parametrize("bad", ["2026-13-01", "2026-1-1", "20261018", "", "2026-02-30"])
    def test_parse_date_rejects_bad_values(self, bad):
        with pytest.raises(window.WindowError):
            window.parse_date(bad)

    def test_parse_date_rejects_non_string(self):
        with pytest.raises(window.WindowError):
            window.parse_date(20261018)

    def test_workday_makeup_day(self):
        entry = {"holidays": ["2026-10-01"], "makeup_workdays": ["2026-10-10"]}
        assert window._is_workday(entry, date(2026, 10, 10)) is True

    def test_workday_holiday(self):
        entry = {"holidays": ["2026-10-01"], "makeup_workdays": []}
        assert window._is_workday(entry, date(2026, 10, 1)) is False

    def test_workday_weekend(self):
        assert window._is_workday({}, date(2026, 10, 3)) is False

    def test_workday_normal_thursday(self):
        assert window._is_workday({}, date(2026, 10, 8)) is True

    @pytest.mark.parametrize(
        "day,expected",
        [
            (date(2026, 10, 18), "2026Q3"),
            (date(2026, 9, 30), "2026Q3"),
            (date(2026, 9, 29), "2026Q2"),
            (date(2026, 6, 30), "2026Q2"),
            (date(2026, 1, 5), "2025Q4"),
            (date(2025, 12, 31), "2025Q4"),
        ],
    )
    def test_period_for_date(self, day, expected):
        assert window.period_for_date(QUARTER_ENDS, day) == expected

    def test_disclosure_three_states(self):
        reports = [{"fundcode": "990001", "report_period": "2026Q3"}]
        assert window.disclosure_status(True, reports, "990001", "2026Q3") == window.DISCLOSED
        assert window.disclosure_status(True, reports, "990002", "2026Q3") == window.PENDING
        assert window.disclosure_status(False, reports, "990001", "2026Q3") == window.NO_DATA

    def test_disclosure_as_of_replays_history(self):
        reports = [{"fundcode": "990001", "report_period": "2026Q3", "report_send_date": "2026-10-20"}]
        assert window.disclosure_status(True, reports, "990001", "2026Q3", "2026-10-19") == window.PENDING
        assert window.disclosure_status(True, reports, "990001", "2026Q3", "2026-10-20") == window.DISCLOSED

    def test_disclosure_undated_report_cannot_claim_disclosed(self):
        reports = [{"fundcode": "990001", "report_period": "2026Q3"}]
        assert window.disclosure_status(True, reports, "990001", "2026Q3", "2026-12-31") == window.PENDING

    def test_disclosure_empty_reports_is_pending(self):
        assert window.disclosure_status(True, [], "990001", "2026Q3") == window.PENDING

    def test_disclosure_ignores_non_mapping_rows(self):
        assert window.disclosure_status(True, ["x"], "990001", "2026Q3") == window.PENDING

    def test_disclosure_no_data_wins_over_reports(self):
        reports = [{"fundcode": "990001", "report_period": "2026Q3"}]
        assert window.disclosure_status(False, reports, "990001", "2026Q3") == window.NO_DATA


# ════════════════════════════════════════════════════════════════════════
# 3. 持仓五态（旧仓 test_diff.py）
# ════════════════════════════════════════════════════════════════════════
class TestHoldings:
    def test_parse_ratio_none(self):
        assert holdings.parse_ratio(None) is None

    def test_parse_ratio_decimal(self):
        assert holdings.parse_ratio("8.54") == Decimal("8.54")

    def test_parse_ratio_invalid_raises(self):
        with pytest.raises(holdings.HoldingsError):
            holdings.parse_ratio("8,54")

    def test_format_delta_positive(self):
        assert holdings.format_delta(Decimal("0.5")) == "0.50"

    def test_format_delta_negative(self):
        assert holdings.format_delta(Decimal("-0.5")) == "-0.50"

    def test_format_delta_zero(self):
        assert holdings.format_delta(Decimal("0")) == "0.00"

    @pytest.mark.parametrize("code", ["600001", "000001", "999999"])
    def test_valid_code_accepts_six_digits(self, code):
        assert holdings.is_valid_code(code) is True

    @pytest.mark.parametrize("code", ["ABC123", "60001", "6000011", "", None, 600001])
    def test_valid_code_rejects_other_shapes(self, code):
        assert holdings.is_valid_code(code) is False

    def test_detect_ratio_null(self):
        assert "ratio_null" in holdings.detect_anomalies({"stock_code": "600001", "ratio": None, "change_type": "不变"})

    def test_detect_invalid_code(self):
        assert "invalid_stock_code" in holdings.detect_anomalies({"stock_code": "ABC", "ratio": "1"})

    def test_detect_change_type_missing(self):
        assert "change_type_missing" in holdings.detect_anomalies({"stock_code": "600001", "ratio": "1"})

    def test_detect_clean_row(self):
        assert holdings.detect_anomalies({"stock_code": "600001", "ratio": "1", "change_type": "不变"}) == []

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("增持", "加仓"),
            ("减持", "减仓"),
            ("不变", "不变"),
            ("新进", "新进"),
            ("退出", "退出"),
            ("其它", None),
            (None, None),
        ],
    )
    def test_provider_status_mapping(self, value, expected):
        assert holdings.provider_status({"change_type": value}) == expected

    def test_duplicate_codes_none(self):
        assert holdings.duplicate_codes([_row("600001", "1"), _row("600002", "2")]) == {}

    def test_duplicate_codes_reports_indexes(self):
        rows = [_row("600001", "1"), _row("600001", "2"), _row("600002", "3")]
        assert holdings.duplicate_codes(rows) == {"600001": [0, 1]}

    def test_five_states_all_present(self):
        _fund, _conflicts = _diff(
            [_row("600001", "7.66"), _row("600002", "4.26"), _row("600003", "8.45"), _row("600004", "8.63")],
            [
                _row("600001", "8.16", "增持"),
                _row("600002", "3.76", "减持"),
                _row("600003", "8.45", "不变"),
                _row("600005", "8.54"),
            ],
        )
        states = {entry["stock_code"]: entry["status"] for entry in _fund["entries"]}
        assert states == {
            "600001": "加仓",
            "600002": "减仓",
            "600003": "不变",
            "600004": "退出",
            "600005": "新进",
        }

    def test_deltas_are_two_decimal_strings(self):
        fund, _ = _diff([_row("600001", "7.66"), _row("600002", "4.26")], [_row("600001", "8.16"), _row("600002", "3.76")])
        entries = {entry["stock_code"]: entry for entry in fund["entries"]}
        assert entries["600001"]["delta"] == "0.50"
        assert entries["600002"]["delta"] == "-0.50"

    def test_new_entry_delta_is_none(self):
        fund, _ = _diff([], [_row("600001", "1.00")])
        assert fund["entries"][0]["delta"] is None

    def test_exit_entry_cur_ratio_is_none(self):
        fund, _ = _diff([_row("600001", "1.00")], [])
        assert fund["entries"][0]["cur_ratio"] is None

    def test_new_entry_prev_ratio_is_none(self):
        fund, _ = _diff([], [_row("600001", "1.00")])
        assert fund["entries"][0]["prev_ratio"] is None

    def test_missing_ratio_is_pending_not_zero(self):
        fund, _ = _diff([_row("600021", None)], [_row("600021", "5.00")])
        entry = fund["entries"][0]
        assert entry["status"] == "待确认"
        assert entry["basis"] == "insufficient_data"
        assert entry["delta"] is None

    def test_missing_ratio_on_both_sides_is_pending(self):
        fund, _ = _diff([_row("600021", None)], [_row("600021", None)])
        assert fund["entries"][0]["status"] == "待确认"

    def test_pending_entry_keeps_anomaly(self):
        fund, _ = _diff([_row("600021", None)], [_row("600021", "5.00")])
        assert "ratio_null" in fund["entries"][0]["anomalies"]

    def test_failed_prev_quarter_is_insufficient(self):
        result, conflicts = holdings.diff_fund(
            _payload("2026Q2", [], status="failed"),
            _payload("2026Q3", [_row("600001", "1.00")]),
            Decimal("0.10"),
        )
        assert result["status"] == "insufficient_data"
        assert result["entries"] == []
        assert conflicts == []

    def test_failed_cur_quarter_is_insufficient(self):
        result, _ = holdings.diff_fund(
            _payload("2026Q2", [_row("600001", "1.00")]),
            _payload("2026Q3", [], status="failed"),
            Decimal("0.10"),
        )
        assert result["status"] == "insufficient_data"

    def test_empty_quarter_is_not_insufficient(self):
        result, _ = _diff([_row("600001", "1.00")], [])
        assert result["status"] == "ok"
        assert result["entries"][0]["status"] == "退出"

    def test_provider_mode_uses_upstream_label(self):
        fund, _ = _diff([_row("600001", "7.66")], [_row("600001", "8.16", "增持", "0.50")], mode="provider")
        entry = fund["entries"][0]
        assert entry["basis"] == "provider"
        assert entry["status"] == "加仓"
        assert entry["delta"] == "0.50"

    def test_provider_mode_uses_upstream_change_pct(self):
        fund, _ = _diff([_row("600001", "7.66")], [_row("600001", "8.16", "增持", "9.99")], mode="provider")
        assert fund["entries"][0]["delta"] == "9.99"

    def test_provider_mode_falls_back_when_label_missing(self):
        fund, _ = _diff([_row("600001", "7.66")], [_row("600001", "8.16")], mode="provider")
        entry = fund["entries"][0]
        assert entry["basis"] == "computed"
        assert entry["status"] == "加仓"

    def test_conflict_when_provider_disagrees_with_computed(self):
        _fund, conflicts = _diff(
            [_row("600003", "8.45")], [_row("600003", "8.45", "增持", "0.00")]
        )
        assert len(conflicts) == 1
        assert conflicts[0]["stock_code"] == "600003"
        assert conflicts[0]["provider_status"] == "加仓"
        assert conflicts[0]["computed_status"] == "不变"

    def test_conflict_keeps_computed_entry(self):
        fund, _ = _diff([_row("600003", "8.45")], [_row("600003", "8.45", "增持", "0.00")])
        entry = fund["entries"][0]
        assert entry["status"] == "不变"
        assert entry["basis"] == "computed"

    def test_no_conflict_when_labels_agree(self):
        _fund, conflicts = _diff([_row("600001", "7.66")], [_row("600001", "8.16", "增持", "0.50")])
        assert conflicts == []

    def test_no_conflict_in_provider_mode(self):
        _fund, conflicts = _diff(
            [_row("600003", "8.45")], [_row("600003", "8.45", "增持", "0.00")], mode="provider"
        )
        assert conflicts == []

    def test_conflict_evidence_carries_both_ratios(self):
        _fund, conflicts = _diff([_row("600003", "8.45")], [_row("600003", "8.45", "增持", "0.00")])
        assert conflicts[0]["prev_ratio"] == "8.45"
        assert conflicts[0]["cur_ratio"] == "8.45"

    def test_sorting_is_ratio_desc_nulls_last(self):
        fund, _ = _diff([], [_row("600004", "3.99"), _row("600001", "8.65"), _row("600002", None), _row("600003", "6.36")])
        assert [entry["stock_code"] for entry in fund["entries"]] == ["600001", "600003", "600004", "600002"]

    def test_sorting_ties_by_stock_code(self):
        fund, _ = _diff([], [_row("600002", "1.00"), _row("600001", "1.00")])
        assert [entry["stock_code"] for entry in fund["entries"]] == ["600001", "600002"]

    def test_source_quarters_are_recorded(self):
        fund, _ = _diff([_row("600001", "1.00")], [_row("600001", "2.00")])
        assert fund["entries"][0]["source_quarters"] == {"prev": "2026Q2", "cur": "2026Q3"}

    def test_summary_counts_all_states(self):
        fund, _ = _diff([_row("600001", "1.00")], [_row("600001", "2.00"), _row("600002", "1.00")])
        assert fund["summary"]["加仓"] == 1
        assert fund["summary"]["新进"] == 1
        assert fund["summary"]["不变"] == 0

    def test_threshold_comes_from_params(self):
        fund, _ = _diff([_row("600001", "1.00")], [_row("600001", "1.50")], threshold="10")
        assert fund["entries"][0]["status"] == "不变"
        assert fund["entries"][0]["delta"] == "0.50"

    def test_threshold_boundary_is_strict_less_than(self):
        fund, _ = _diff([_row("600001", "1.00")], [_row("600001", "1.10")], threshold="0.10")
        assert fund["entries"][0]["status"] == "加仓"

    def test_union_of_both_quarters(self):
        fund, _ = _diff([_row("600001", "1.00")], [_row("600002", "2.00")])
        assert [entry["stock_code"] for entry in fund["entries"]] == ["600002", "600001"]

    def test_stock_name_prefers_current_row(self):
        fund, _ = _diff([_row("600001", "1.00", name="旧名")], [_row("600001", "2.00", name="新名")])
        assert fund["entries"][0]["stock_name"] == "新名"

    def test_stock_name_falls_back_to_previous_row(self):
        fund, _ = _diff([_row("600001", "1.00", name="旧名")], [])
        assert fund["entries"][0]["stock_name"] == "旧名"

    def test_industry_is_present_when_given(self):
        cur = _row("600001", "2.00")
        cur["industry"] = "医药生物"
        fund, _ = _diff([_row("600001", "1.00")], [cur])
        assert fund["entries"][0]["industry"] == "医药生物"

    def test_duplicate_code_last_row_wins_like_source(self):
        fund, _ = _diff([], [_row("600001", "1.00"), _row("600001", "9.00")])
        assert len(fund["entries"]) == 1
        assert fund["entries"][0]["cur_ratio"] == "9.00"

    def test_empty_payload_is_empty_list(self):
        assert holdings.payload_rows(None, "prev") == []

    def test_payload_rows_reject_non_list(self):
        with pytest.raises(holdings.HoldingsError):
            holdings.payload_rows({"rows": "x"}, "prev")

    def test_payload_rows_reject_non_mapping_row(self):
        with pytest.raises(holdings.HoldingsError):
            holdings.payload_rows({"rows": ["x"]}, "prev")

    def test_payload_reject_non_mapping(self):
        with pytest.raises(holdings.HoldingsError):
            holdings.payload_rows([], "prev")


# ════════════════════════════════════════════════════════════════════════
# 4. 经理变更（旧仓 test_managers.py）
# ════════════════════════════════════════════════════════════════════════
class TestManagers:
    def test_normalize_iso_date(self):
        assert managers.normalize_date("2026-08-15") == "2026-08-15"

    def test_normalize_slash_date(self):
        assert managers.normalize_date("2026/8/15") == "2026-08-15"

    def test_normalize_chinese_date(self):
        assert managers.normalize_date("2026年8月15日") == "2026-08-15"

    def test_normalize_invalid_date_returns_none(self):
        assert managers.normalize_date("2026-13-40") is None

    def test_normalize_non_string_returns_none(self):
        assert managers.normalize_date(20260815) is None

    @pytest.mark.parametrize(
        "day,expected",
        [
            ("2026-07-01", managers.CLASS_IN_PERIOD),
            ("2026-09-30", managers.CLASS_IN_PERIOD),
            ("2026-06-30", managers.CLASS_PRIOR_PERIOD),
            ("2026-04-01", managers.CLASS_PRIOR_PERIOD),
            ("2026-08-15", managers.CLASS_IN_PERIOD),
        ],
    )
    def test_classify_change_windows(self, day, expected):
        assert managers.classify_change(day, "2026Q3", QUARTER_ENDS) == expected

    def test_classify_change_older_history_is_none(self):
        assert managers.classify_change("2019-01-01", "2026Q3", QUARTER_ENDS) is None

    def test_classify_change_future_is_none(self):
        assert managers.classify_change("2026-12-31", "2026Q3", QUARTER_ENDS) is None

    def test_classify_change_invalid_date_raises(self):
        with pytest.raises(ValueError):
            managers.classify_change("2026-13-40", "2026Q3", QUARTER_ENDS)

    def test_interval_comes_from_quarter_ends(self):
        mutated = dict(QUARTER_ENDS)
        mutated["Q3"] = "08-01"
        assert managers.classify_change("2026-08-15", "2026Q3", mutated) is None

    def test_interval_shift_moves_prior_into_current(self):
        mutated = dict(QUARTER_ENDS)
        mutated["Q2"] = "05-31"
        assert managers.classify_change("2026-06-30", "2026Q3", mutated) == managers.CLASS_IN_PERIOD

    def test_snapshot_hash_matches_text(self):
        import hashlib

        snap = managers.snapshot("2026-13-40 | 至今 | 样例经理甲")
        assert snap["sha256"] == hashlib.sha256(snap["raw_text"].encode("utf-8")).hexdigest()

    def test_snapshot_of_empty_text_still_hashed(self):
        assert managers.snapshot(None)["sha256"] == managers.snapshot("")["sha256"]

    def test_is_unparsed_explicit(self):
        assert managers.is_unparsed({"change_class": "unparsed"}) is True

    def test_is_unparsed_when_claimed_class_has_no_date(self):
        assert managers.is_unparsed({"change_class": "in_period"}) is True

    def test_is_unparsed_false_for_valid_record(self):
        assert managers.is_unparsed({"change_class": "in_period", "change_date": "2026-08-15"}) is False

    def test_label_drift_none_for_matching_class(self):
        assert managers.label_drift({"change_class": "in_period", "change_date": "2026-08-15"}, "2026Q3", QUARTER_ENDS) is None

    def test_label_drift_detected_for_mismatch(self):
        drift = managers.label_drift({"change_class": "prior_period", "change_date": "2026-08-15"}, "2026Q3", QUARTER_ENDS)
        assert drift and "重算" in drift

    def test_label_drift_none_entry_is_rejected(self):
        drift = managers.label_drift({"change_class": "none"}, "2026Q3", QUARTER_ENDS)
        assert drift and "none" in drift

    def test_label_drift_unknown_class_is_rejected(self):
        drift = managers.label_drift({"change_class": "other"}, "2026Q3", QUARTER_ENDS)
        assert drift and "未知" in drift

    def test_label_drift_missing_date(self):
        drift = managers.label_drift({"change_class": "in_period"}, "2026Q3", QUARTER_ENDS)
        assert drift and "change_date" in drift

    def test_label_drift_missing_class_outside_window(self):
        drift = managers.label_drift({"change_date": "2019-01-01"}, "2026Q3", QUARTER_ENDS)
        assert drift and "不在" in drift

    def test_missing_class_inside_window_is_fine(self):
        assert managers.label_drift({"change_date": "2026-08-15"}, "2026Q3", QUARTER_ENDS) is None

    def test_unparsed_class_has_no_drift(self):
        assert managers.label_drift({"change_class": "unparsed"}, "2026Q3", QUARTER_ENDS) is None

    def test_summarize_empty_is_none_once(self):
        assert managers.summarize([]) == {"in_period": 0, "prior_period": 0, "none": 1, "unparsed": 0}

    def test_summarize_counts_each_class(self):
        records = [
            {"change_class": "in_period"},
            {"change_class": "in_period"},
            {"change_class": "unparsed"},
        ]
        assert managers.summarize(records) == {"in_period": 2, "prior_period": 0, "none": 0, "unparsed": 1}

    def test_sort_records_dates_ascending_nulls_last(self):
        records = [
            {"change_date": None, "change_class": "unparsed", "name": "乙"},
            {"change_date": "2026-08-15", "change_class": "in_period", "name": "甲"},
            {"change_date": "2026-05-20", "change_class": "prior_period", "name": "丙"},
        ]
        assert [record["name"] for record in managers.sort_records(records)] == ["丙", "甲", "乙"]


# ════════════════════════════════════════════════════════════════════════
# 5. 规模六字段（旧仓 test_scale.py）
# ════════════════════════════════════════════════════════════════════════
def _scale_ok(**overrides):
    value = {
        "report_period": "2026Q3",
        "subscribe": "1.20",
        "redeem": "0.80",
        "shares": "30.00",
        "net_assets": "45.00",
        "share_change_rate": "1.35%",
        "baseline": "available",
        "units_from_header": {"subscribe": "亿份", "net_assets": "亿元"},
        "source": "gmbd",
        "raw_sha256": None,
    }
    value.update(overrides)
    return value


class TestScale:
    def test_good_scale_has_no_problem(self):
        assert scale.missing_fields(_scale_ok()) == ()
        assert scale.bad_baseline(_scale_ok()) is None
        assert scale.unit_problem(_scale_ok()) is None
        assert scale.number_problem(_scale_ok()) is None
        assert scale.rate_problem(_scale_ok()) is None
        assert scale.source_problem(_scale_ok()) is None

    def test_missing_fields_detects_one(self):
        value = _scale_ok()
        del value["redeem"]
        assert scale.missing_fields(value) == ("redeem",)

    def test_missing_fields_detects_all(self):
        assert len(scale.missing_fields({})) == len(scale.SCALE_KEYS)

    def test_missing_fields_non_mapping(self):
        assert len(scale.missing_fields(None)) == len(scale.SCALE_KEYS)

    def test_unknown_baseline(self):
        assert scale.bad_baseline(_scale_ok(baseline="unknown"))

    def test_unit_missing_subscribe(self):
        problem = scale.unit_problem(_scale_ok(units_from_header={"net_assets": "亿元"}))
        assert "subscribe" in problem

    def test_unit_missing_net_assets(self):
        problem = scale.unit_problem(_scale_ok(units_from_header={"subscribe": "亿份"}))
        assert "net_assets" in problem

    def test_units_not_mapping(self):
        assert scale.unit_problem(_scale_ok(units_from_header=[]))

    @pytest.mark.parametrize("key", ["subscribe", "redeem", "shares", "net_assets"])
    def test_number_problem_per_field(self, key):
        problem = scale.number_problem(_scale_ok(**{key: "abc"}))
        assert problem and key in problem

    def test_number_null_is_allowed(self):
        assert scale.number_problem(_scale_ok(subscribe=None, redeem=None)) is None

    def test_rate_valid_negative(self):
        assert scale.rate_problem(_scale_ok(share_change_rate="-3.69%")) is None

    def test_rate_null_is_allowed(self):
        assert scale.rate_problem(_scale_ok(share_change_rate=None)) is None

    @pytest.mark.parametrize("bad", ["48.93", "abc", "1.2.3%", "－3.69%"])
    def test_rate_invalid_formats(self, bad):
        assert scale.rate_problem(_scale_ok(share_change_rate=bad))

    @pytest.mark.parametrize("key", ["subscribe", "redeem", "share_change_rate"])
    def test_baseline_flow_violation_per_key(self, key):
        flows = {"subscribe": None, "redeem": None, "share_change_rate": None}
        flows[key] = "0.00"
        problem_key, message = scale.baseline_flow_problem(
            _scale_ok(baseline="no_prev_baseline", **flows)
        )
        assert problem_key == key and message

    def test_baseline_flow_null_is_fine(self):
        key, message = scale.baseline_flow_problem(
            _scale_ok(baseline="no_prev_baseline", subscribe=None, redeem=None, share_change_rate=None)
        )
        assert key is None and message is None

    def test_baseline_available_does_not_check_flows(self):
        key, message = scale.baseline_flow_problem(_scale_ok(baseline="available"))
        assert key is None and message is None

    def test_source_must_be_gmbd(self):
        assert scale.source_problem(_scale_ok(source="jjjl"))

    def test_raw_sha_must_be_hex64(self):
        assert scale.source_problem(_scale_ok(raw_sha256="a" * 63))

    def test_raw_sha_valid(self):
        assert scale.source_problem(_scale_ok(raw_sha256="a" * 64)) is None

    def test_zero_flow_true(self):
        assert scale.is_zero_flow(_scale_ok(subscribe="0.00", redeem="0.00")) is True

    def test_zero_flow_false_when_null(self):
        assert scale.is_zero_flow(_scale_ok(subscribe=None, redeem="0.00")) is False

    def test_zero_flow_false_without_baseline(self):
        assert scale.is_zero_flow(_scale_ok(baseline="no_prev_baseline", subscribe="0.00", redeem="0.00")) is False

    def test_zero_flow_false_when_nonzero(self):
        assert scale.is_zero_flow(_scale_ok(subscribe="0.01", redeem="0.00")) is False

    def test_scale_flows_are_not_converted(self):
        value = _scale_ok(subscribe="14900.00", net_assets="3938.00")
        assert scale.number_problem(value) is None
        assert value["subscribe"] == "14900.00"


# ════════════════════════════════════════════════════════════════════════
# 6. 合规扫描（旧仓 test_compliance.py）
# ════════════════════════════════════════════════════════════════════════
class TestCompliance:
    def test_neutral_text_has_no_hits(self):
        assert compliance.scan_text("本季度持仓发生变化，详见明细。", ["保证收益"]) == []

    def test_hit_reports_line_and_term(self):
        hits = compliance.scan_text("第一行正常\n第二行含保证收益表述", ["保证收益"])
        assert hits and hits[0]["line"] == 2 and hits[0]["term"] == "保证收益"

    def test_matching_is_case_insensitive(self):
        assert compliance.scan_text("ａｂｃ", ["ABC"])

    def test_matching_is_width_insensitive(self):
        assert compliance.scan_text("ＡＢＣ", ["abc"])

    def test_whitespace_is_folded(self):
        assert compliance.scan_text("跟随 基金 经理", ["跟随基金经理"])

    def test_empty_terms_is_noop(self):
        assert compliance.scan_text("任意文本", []) == []

    def test_empty_text_is_noop(self):
        assert compliance.scan_text("", ["任意"]) == []

    def test_non_string_text_is_noop(self):
        assert compliance.scan_text(None, ["任意"]) == []

    def test_multiple_terms_all_reported(self):
        hits = compliance.scan_text("保证收益\n排名第一", ["保证收益", "排名第一"])
        assert [hit["term"] for hit in hits] == ["保证收益", "排名第一"]

    def test_excerpt_is_stripped(self):
        hit = compliance.scan_text("  保证收益  ", ["保证收益"])[0]
        assert hit["excerpt"] == "保证收益"

    def test_whitespace_only_term_is_ignored(self):
        assert compliance.scan_text("任意文本", ["   "]) == []


# ════════════════════════════════════════════════════════════════════════
# 7. 器官接线（PACK / BUILTIN_MODULES）
# ════════════════════════════════════════════════════════════════════════
class TestWiring:
    def test_pack_is_registered(self):
        assert get(SLUG) is PACK

    def test_pack_version(self):
        assert PACK.version == ORGAN_VERSION == "1"

    def test_builtin_modules_are_sorted(self):
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_builtin_modules_include_slug_underscored(self):
        assert "fund_quarter_report" in BUILTIN_MODULES

    def test_input_fields(self):
        assert PACK.input_fields == ("period", "holdings")

    def test_summary_mentions_fund(self):
        assert "基金" in PACK.summary

    def test_basis_file_is_shipped_json(self):
        assert BASIS_PATH.is_file()
        assert BASIS_PATH.parent == DATA_DIR

    def test_thresholds_file_is_shipped_json(self):
        assert THRESHOLDS_PATH.is_file()

    def test_organ_directory_is_a_package(self):
        assert (SRC / "byteproof" / "auditors" / "fund_quarter_report" / "__init__.py").is_file()

    def test_no_network_imports_in_organ_module(self):
        tree = ast.parse(
            (SRC / "byteproof" / "auditors" / "fund_quarter_report" / "audit.py").read_text(encoding="utf-8")
        )
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert "socket" not in names and "requests" not in names and "urllib" not in names

    def test_no_clock_calls_in_judgement_modules(self):
        for name in ("audit.py", "holdings.py", "managers.py", "scale.py", "window.py"):
            text = (SRC / "byteproof" / "auditors" / "fund_quarter_report" / name).read_text(encoding="utf-8")
            assert "datetime.now(" not in text
            assert "datetime.today(" not in text
            assert "date.today(" not in text
            assert "time.time(" not in text


# ════════════════════════════════════════════════════════════════════════
# 8. 器官编排（evaluate -> 缺陷账本）
# ════════════════════════════════════════════════════════════════════════
class TestEvaluate:
    def test_sample_produces_records(self):
        assert len(_evaluate()) == 9

    def test_sample_has_no_blocking_findings(self):
        assert all(record.verdict != ERROR for record in _evaluate())

    def test_sample_warn_rules(self):
        assert set(_rules(_evaluate())) == {
            "fq-change-type-missing",
            "fq-disclosure-pending",
            "fq-invalid-code",
            "fq-manager-unparsed",
            "fq-ratio-missing",
        }

    def test_sample_warn_count(self):
        assert sum(1 for record in _evaluate() if record.verdict == WARN) == 4

    def test_sample_info_count(self):
        assert sum(1 for record in _evaluate() if record.verdict == INFO) == 5

    def test_every_record_has_complete_basis(self):
        for record in _evaluate():
            assert record.basis is not None and record.basis.complete
            assert record.basis.rule_id == record.rule_id

    def test_every_record_has_unique_id(self):
        ids = [record.id for record in _evaluate()]
        assert len(ids) == len(set(ids))

    def test_report_exit_code_is_zero_for_sample(self):
        report = Report(
            product="byteproof",
            organ=SLUG,
            organ_version=ORGAN_VERSION,
            subject="sample",
            records=_evaluate(),
        )
        assert report.exit_code() == EXIT_OK
        assert report.summary()["blocking"] == 0

    def test_report_json_is_deterministic(self):
        def build():
            return Report(
                product="byteproof",
                organ=SLUG,
                organ_version=ORGAN_VERSION,
                subject="sample",
                records=_evaluate(),
            ).as_dict()

        assert json.dumps(build(), ensure_ascii=False) == json.dumps(build(), ensure_ascii=False)

    def test_report_records_are_sorted(self):
        report = Report(
            product="byteproof",
            organ=SLUG,
            organ_version=ORGAN_VERSION,
            subject="sample",
            records=_evaluate(),
        )
        keys = [(record.rule_id, record.path) for record in report.records]
        assert keys == sorted(keys)

    def test_change_type_missing_covers_exit_row(self):
        records = _evaluate(_subject([_row("600004", "8.63")], [_row("600001", "8.16", "增持")]))
        paths = [record.path for record in _by_rule(records, "fq-change-type-missing")]
        assert "holdings.prev.rows[0]" in paths

    def test_change_type_missing_ignored_in_provider_mode(self):
        subject = _subject([_row("600004", "8.63")], [_row("600001", "8.16", "增持")])
        subject["params"] = {"mode": "provider"}
        assert _by_rule(_evaluate(subject), "fq-change-type-missing") == []

    def test_duplicate_holding_is_error(self):
        records = _evaluate(_subject([], [_row("600001", "1.00"), _row("600001", "2.00")]))
        hits = _by_rule(records, "fq-duplicate-holding")
        assert len(hits) == 1 and hits[0].verdict == ERROR

    def test_duplicate_holding_evidence_indexes(self):
        records = _evaluate(_subject([], [_row("600001", "1.00"), _row("600001", "2.00")]))
        assert _by_rule(records, "fq-duplicate-holding")[0].evidence["row_indexes"] == [0, 1]

    def test_duplicate_holding_blocks(self):
        report = Report(product="byteproof", organ=SLUG, organ_version="1", subject="x",
                        records=_evaluate(_subject([], [_row("600001", "1.00"), _row("600001", "2.00")])))
        assert report.exit_code() == EXIT_BLOCKED

    def test_prev_period_mismatch_is_error(self):
        subject = _subject([_row("600001", "1.00")], [_row("600001", "2.00")])
        subject["holdings"]["prev"]["report_period"] = "2026Q1"
        hits = _by_rule(_evaluate(subject), "fq-period-mismatch")
        assert len(hits) == 1 and hits[0].verdict == ERROR

    def test_cur_period_mismatch_is_error(self):
        subject = _subject([_row("600001", "1.00")], [_row("600001", "2.00")])
        subject["holdings"]["cur"]["report_period"] = "2026Q4"
        hits = _by_rule(_evaluate(subject), "fq-period-mismatch")
        assert len(hits) == 1

    def test_period_mismatch_suppresses_anomaly_free_diff(self):
        subject = _subject([_row("600001", "1.00")], [_row("600001", "2.00")])
        subject["holdings"]["prev"]["report_period"] = "2026Q1"
        assert _by_rule(_evaluate(subject), "fq-provider-conflict") == []

    def test_failed_quarter_is_warn(self):
        subject = _subject([_row("600001", "1.00")], [_row("600001", "2.00")])
        subject["holdings"]["cur"]["status"] = "failed"
        hits = _by_rule(_evaluate(subject), "fq-failed-quarter")
        assert len(hits) == 1 and hits[0].verdict == WARN

    def test_failed_quarter_suppresses_change_type_records(self):
        subject = _subject([], [_row("600001", "2.00")])
        subject["holdings"]["cur"]["status"] = "failed"
        assert _by_rule(_evaluate(subject), "fq-change-type-missing") == []

    def test_ratio_invalid_is_error(self):
        records = _evaluate(_subject([_row("600001", "1.00")], [_row("600001", "x")]))
        hits = _by_rule(records, "fq-ratio-invalid")
        assert len(hits) == 1 and hits[0].verdict == ERROR

    def test_ratio_missing_is_warn_per_side(self):
        records = _evaluate(_subject([_row("600001", None)], [_row("600001", "1.00")]))
        hits = _by_rule(records, "fq-ratio-missing")
        assert len(hits) == 1 and hits[0].path == "holdings.prev.rows[0]"

    def test_invalid_code_is_warn(self):
        records = _evaluate(_subject([], [_row("ABC123", "1.00")]))
        hits = _by_rule(records, "fq-invalid-code")
        assert len(hits) == 1 and hits[0].verdict == WARN

    def test_provider_conflict_record(self):
        records = _evaluate(_subject([_row("600003", "8.45")], [_row("600003", "8.45", "增持", "0.00")]))
        hits = _by_rule(records, "fq-provider-conflict")
        assert len(hits) == 1
        assert hits[0].evidence["provider_status"] == "加仓"
        assert hits[0].evidence["computed_status"] == "不变"

    def test_provider_conflict_path_is_current_row(self):
        records = _evaluate(_subject([_row("600003", "8.45")], [_row("600003", "8.45", "增持", "0.00")]))
        assert _by_rule(records, "fq-provider-conflict")[0].path == "holdings.cur.rows[600003]"

    def test_manager_unparsed_record(self):
        subject = _subject([], [])
        subject["managers"] = [{"change_class": "unparsed", "raw_text": "坏行", "unparsed_reason": "列数不足"}]
        hits = _by_rule(_evaluate(subject), "fq-manager-unparsed")
        assert len(hits) == 1 and hits[0].verdict == WARN

    def test_manager_unparsed_evidence_hash(self):
        subject = _subject([], [])
        subject["managers"] = [{"change_class": "unparsed", "raw_text": "坏行"}]
        evidence = _by_rule(_evaluate(subject), "fq-manager-unparsed")[0].evidence
        assert evidence["sha256"] == managers.snapshot("坏行")["sha256"]

    def test_manager_unparsed_without_raw_text_has_no_snapshot(self):
        subject = _subject([], [])
        subject["managers"] = [{"change_class": "unparsed"}]
        assert "sha256" not in _by_rule(_evaluate(subject), "fq-manager-unparsed")[0].evidence

    def test_manager_label_drift_record(self):
        subject = _subject([], [])
        subject["managers"] = [{"name": "甲", "change_date": "2026-08-15", "change_class": "prior_period"}]
        hits = _by_rule(_evaluate(subject), "fq-manager-label-drift")
        assert len(hits) == 1 and hits[0].verdict == ERROR

    def test_manager_none_class_is_error(self):
        subject = _subject([], [])
        subject["managers"] = [{"change_class": "none"}]
        assert _by_rule(_evaluate(subject), "fq-manager-label-drift")

    def test_manager_records_accept_wrapped_object(self):
        subject = _subject([], [])
        subject["managers"] = {"records": [{"change_date": "2026-08-15", "change_class": "in_period"}]}
        assert _by_rule(_evaluate(subject), "fq-manager-label-drift") == []

    def test_manager_non_list_is_rejected(self):
        subject = _subject([], [])
        subject["managers"] = "x"
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_manager_non_mapping_item_is_rejected(self):
        subject = _subject([], [])
        subject["managers"] = ["x"]
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_scale_missing_field_is_error(self):
        subject = _subject([], [])
        subject["scale"] = {"baseline": "available"}
        hits = _by_rule(_evaluate(subject), "fq-scale-field-missing")
        assert hits and hits[0].verdict == ERROR

    def test_scale_good_has_no_records(self):
        subject = _subject([], [])
        subject["scale"] = _scale_ok()
        assert [r for r in _evaluate(subject) if r.rule_id.startswith("fq-scale")] == []

    def test_scale_baseline_flow_is_error(self):
        subject = _subject([], [])
        subject["scale"] = _scale_ok(baseline="no_prev_baseline", subscribe="0.00")
        hits = _by_rule(_evaluate(subject), "fq-scale-baseline-flow")
        assert len(hits) == 1 and hits[0].path == "scale.subscribe"

    def test_scale_unit_missing_is_error(self):
        subject = _subject([], [])
        subject["scale"] = _scale_ok(units_from_header={"subscribe": "亿份"})
        hits = _by_rule(_evaluate(subject), "fq-scale-unit-missing")
        assert len(hits) == 1

    def test_scale_number_is_error(self):
        subject = _subject([], [])
        subject["scale"] = _scale_ok(shares="abc")
        assert _by_rule(_evaluate(subject), "fq-scale-number")

    def test_scale_rate_is_error(self):
        subject = _subject([], [])
        subject["scale"] = _scale_ok(share_change_rate="48.93")
        assert _by_rule(_evaluate(subject), "fq-scale-rate")

    def test_scale_source_is_error(self):
        subject = _subject([], [])
        subject["scale"] = _scale_ok(source="jjjl")
        assert _by_rule(_evaluate(subject), "fq-scale-source")

    def test_scale_non_mapping_is_rejected(self):
        subject = _subject([], [])
        subject["scale"] = []
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_compliance_hit_is_error(self):
        subject = _subject([], [])
        subject["report_text"] = "本产品保证收益"
        subject["compliance_terms"] = ["保证收益"]
        hits = _by_rule(_evaluate(subject), "fq-compliance-term")
        assert len(hits) == 1 and hits[0].verdict == ERROR

    def test_compliance_hit_path_has_line(self):
        subject = _subject([], [])
        subject["report_text"] = "第一行\n保证收益"
        subject["compliance_terms"] = ["保证收益"]
        assert _by_rule(_evaluate(subject), "fq-compliance-term")[0].path.startswith("report_text[2]")

    def test_compliance_clean_text_no_records(self):
        subject = _subject([], [])
        subject["report_text"] = "中性文本"
        subject["compliance_terms"] = ["保证收益"]
        assert _by_rule(_evaluate(subject), "fq-compliance-term") == []

    def test_compliance_terms_not_list_is_rejected(self):
        subject = _subject([], [])
        subject["report_text"] = "x"
        subject["compliance_terms"] = "保证收益"
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_disclosure_unverified_is_warn(self):
        subject = _subject([], [])
        subject["disclosure"] = {"metadata_available": True, "reports": []}
        hits = _by_rule(_evaluate(subject), "fq-disclosure-unverified")
        assert len(hits) == 1 and hits[0].verdict == WARN

    def test_disclosure_unverified_has_reason(self):
        subject = _subject([], [])
        subject["disclosure"] = {"metadata_available": True, "reports": []}
        evidence = _by_rule(_evaluate(subject), "fq-disclosure-unverified")[0].evidence
        assert evidence["unverified_reason"] == "calendar_missing:2026"

    def test_disclosure_no_data_is_warn(self):
        subject = _subject([], [])
        subject["disclosure"] = {"metadata_available": False, "reports": []}
        hits = _by_rule(_evaluate(subject), "fq-disclosure-no-data")
        assert len(hits) == 1 and hits[0].verdict == WARN

    def test_disclosure_pending_is_info(self):
        subject = _subject([], [])
        subject["disclosure"] = {"metadata_available": True, "reports": [], "calendar": CAL2026}
        hits = _by_rule(_evaluate(subject), "fq-disclosure-pending")
        assert len(hits) == 1 and hits[0].verdict == INFO

    def test_disclosure_reported_is_silent(self):
        subject = _subject([], [])
        subject["disclosure"] = {
            "metadata_available": True,
            "reports": [{"fundcode": "990001", "report_period": "2026Q3"}],
            "calendar": CAL2026,
        }
        assert [r for r in _evaluate(subject) if r.rule_id.startswith("fq-disclosure")] == []

    def test_disclosure_non_mapping_is_rejected(self):
        subject = _subject([], [])
        subject["disclosure"] = []
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_disclosure_metadata_flag_must_be_bool(self):
        subject = _subject([], [])
        subject["disclosure"] = {"metadata_available": "yes"}
        with pytest.raises(ValueError):
            _evaluate(subject)

    def test_holdings_absent_gives_empty_ledger(self):
        assert _evaluate({"period": "2026Q3", "holdings": None}) == []

    def test_one_holdings_side_missing_is_rejected(self):
        with pytest.raises(holdings.HoldingsError):
            _evaluate({"period": "2026Q3", "holdings": {"prev": _payload("2026Q2", [])}})

    def test_holdings_non_mapping_is_rejected(self):
        with pytest.raises(holdings.HoldingsError):
            _evaluate({"period": "2026Q3", "holdings": []})

    def test_missing_period_is_rejected(self):
        with pytest.raises(ValueError):
            _evaluate({"holdings": None})

    def test_bad_period_is_rejected(self):
        with pytest.raises(window.WindowError):
            _evaluate({"period": "2026Q9", "holdings": None})

    def test_bad_prev_period_is_rejected(self):
        with pytest.raises(window.WindowError):
            _evaluate({"period": "2026Q3", "prev_period": "26Q2", "holdings": None})

    def test_prev_period_defaults_to_previous_quarter(self):
        subject = {"period": "2026Q3", "holdings": {"prev": _payload("2026Q2", [_row("600001", "1.00")]),
                                                    "cur": _payload("2026Q3", [_row("600001", "2.00")])}}
        assert [r for r in _evaluate(subject) if r.rule_id == "fq-period-mismatch"] == []

    def test_unknown_param_is_input_error_through_evaluate(self):
        subject = _subject([], [])
        subject["params"] = {"shingle_size": 3}
        with pytest.raises(ValueError):
            _evaluate(subject)


# ════════════════════════════════════════════════════════════════════════
# 9. 唯一入口（CLI 退出码 0/1/2/3）
# ════════════════════════════════════════════════════════════════════════
class TestCli:
    def test_list_includes_new_organ(self, capsys):
        assert cli.main(["list"]) == EXIT_OK
        assert SLUG in capsys.readouterr().out

    def test_list_json_includes_new_organ(self, capsys):
        assert cli.main(["list", "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert any(item["slug"] == SLUG for item in payload)

    def test_check_sample_returns_zero(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE)]) == EXIT_OK

    def test_check_sample_json_parses(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert payload["organ"] == SLUG
        assert payload["summary"]["blocking"] == 0

    def test_check_json_fields_are_contract(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"product", "organ", "organ_version", "subject", "summary", "records"}
        assert set(payload["records"][0]) == {"id", "rule_id", "verdict", "message", "basis_ref", "path", "evidence"}

    def test_check_stdout_is_deterministic(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        first = capsys.readouterr().out
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        assert capsys.readouterr().out == first

    def test_check_error_subject_returns_one(self, tmp_path, capsys):
        subject = _subject([], [_row("600001", "1.00"), _row("600001", "2.00")])
        path = tmp_path / "dup.json"
        path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_BLOCKED

    def test_check_explicit_basis(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)]) == EXIT_OK

    def test_check_empty_basis_is_contract_violation(self, tmp_path, capsys):
        empty = tmp_path / "empty.json"
        empty.write_text('{"version": "1", "rules": []}', encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(empty)]) == EXIT_CONTRACT

    def test_check_missing_input_file_returns_two(self):
        assert cli.main(["check", SLUG, "--input", "no-such.json"]) == EXIT_INPUT

    def test_check_invalid_json_returns_two(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT

    def test_check_missing_input_field_returns_two(self, tmp_path):
        path = tmp_path / "noperiod.json"
        path.write_text(json.dumps({"holdings": None}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT

    def test_check_unknown_slug_returns_three(self):
        assert cli.main(["check", "no-such", "--input", str(SAMPLE)]) == EXIT_CONTRACT

    def test_check_subject_label_is_basename(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE)])
        assert capsys.readouterr().out.splitlines()[0].endswith(SAMPLE.name)

    def test_check_human_output_has_summary_line(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE)])
        assert "合计 9 条" in capsys.readouterr().out


# ════════════════════════════════════════════════════════════════════════
# 10. 文档面（docs/<slug>.md 的四项判据必须落纸）
# ════════════════════════════════════════════════════════════════════════
class TestDocs:
    def test_docs_page_exists(self):
        assert (ROOT / "docs" / (SLUG + ".md")).is_file()

    def test_docs_page_has_four_criteria_rows(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        for marker in ("判据", "X = 184", "判据 4", "口径差"):
            assert marker in text

    def test_docs_page_names_the_sample(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        assert "samples/fund-quarter-report.minimal.json" in text

    def test_docs_page_has_disposition_table(self):
        text = (ROOT / "docs" / (SLUG + ".md")).read_text(encoding="utf-8")
        assert "处置表" in text