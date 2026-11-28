"""``testdeck`` 的边界与承重补测（与 ``test_testdeck.py`` 同域：同一判定面，不同断言角度）。

为什么拆两个文件：判据 3 口径乙里**文件数只作记录**（按域计），一个域可以有多份测试；
主文件按"逐模块"组织，本文件按"边界 / 承重 / 跨模块"组织，避免单文件过长难以复核。
"""

from __future__ import annotations

import base64
from decimal import Decimal
from fractions import Fraction

import pytest

from byteproof.auditors.testdeck import core, facts, judge, spec
from test_testdeck import (
    BASIS,
    HEX40,
    RUN1,
    RUN2,
    RUN3,
    body,
    only,
    occurrence,
    row_facts,
    summary,
    xml_case,
    xml_doc,
    xml_suite,
)

# ============================================================ model / identity / framework
def test_seconds_to_ms_zero():
    assert core.seconds_to_ms("0") == 0


def test_seconds_to_ms_negative():
    assert core.seconds_to_ms("-0.5") == -500


def test_seconds_to_ms_rounds_two_decimals():
    assert core.seconds_to_ms("0.0015") == 2


def test_render_exact_accepts_decimal():
    assert core.render_exact(Decimal("0.05")) == "0.05"


def test_render_exact_long_terminating():
    assert core.render_exact(Fraction(1, 1024)) == "0.0009765625"


def test_mean_fraction_zero_numerator():
    assert core.mean_fraction(0, 3) == Fraction(0)


def test_validate_status_accepts_all_four():
    assert [core.validate_status(status) for status in spec.STATUSES] == list(spec.STATUSES)


def test_run_identity_orders_lexically():
    assert core.RunIdentity("a", "", "") < core.RunIdentity("b", "", "")


def test_case_identity_empty_classname_display():
    assert core.CaseIdentity("s", "", "n").display == "s :: n"


def test_case_identity_key_distinct_by_suite():
    assert core.CaseIdentity("a", "c", "n").key != core.CaseIdentity("b", "c", "n").key


def test_framework_hint_case_insensitive():
    assert core.detect_framework("", names=["PYTEST TESTS"]) == "pytest"


def test_framework_property_beats_filename():
    assert core.detect_framework("playwright.xml", properties=["go.version"]) == "gotestsum"


def test_framework_backslash_basename():
    assert core.detect_framework("dir\\sub\\gotestsum.xml") == "gotestsum"


# ============================================================ JUnit 解析边界
def test_parse_error_tag_counts_separately():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("e", kind="error")])]), file_name="junit.xml")
    totals = core.outcome_totals(outcome)
    assert totals["errors"] == 1 and totals["failures"] == 0


def test_parse_failure_type_default_empty():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("f", kind="failure")])]), file_name="junit.xml")
    assert outcome["suites"][0]["cases"][0]["failure_type"] == ""


def test_parse_stack_first_line_skips_blank():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("f", kind="failure", text="\n   真正首行   \nnext")])]),
        file_name="junit.xml")
    assert outcome["suites"][0]["cases"][0]["stack_first_line"] == "真正首行"


def test_parse_skipped_has_no_failure_fields():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("k", kind="skipped")])]), file_name="junit.xml")
    case = outcome["suites"][0]["cases"][0]
    assert case["failure_type"] == "" and case["stack_first_line"] == ""


def test_parse_testsuites_other_child_ignored():
    assert core.parse_xml_text('<testsuites name="pytest"><other/></testsuites>',
                               file_name="junit.xml")["reason"] == spec.NO_TESTSUITE


def test_parse_testcase_properties_not_framework_hint():
    payload = xml_doc([xml_suite("s", [
        '<testcase name="a"><properties><property name="go.version"/></properties></testcase>'
    ])], name="")
    assert core.parse_xml_text(payload, file_name="junit.xml")["framework"] == "pytest"


def test_parse_integer_time():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("a", time="1")])]), file_name="junit.xml")
    assert outcome["suites"][0]["cases"][0]["time_ms"] == 1000


def test_parse_duplicate_case_names_both_kept():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("a"), xml_case("a")])]), file_name="junit.xml")
    assert len(outcome["suites"][0]["cases"]) == 2


def test_parse_multi_bad_time_degraded_count():
    outcome = core.parse_xml_text(
        xml_doc([xml_suite("s", [xml_case("a", time="x"), xml_case("b", time="y")])]),
        file_name="junit.xml")
    assert outcome["degraded"][spec.DEGRADED_BAD_TIME] == 2


def test_parse_namespaced_testsuites_root():
    payload = ('<testsuites xmlns="urn:x" name=""><testsuite name="s">'
               '<testcase name="a"/></testsuite></testsuites>')
    outcome = core.parse_xml_text(payload, file_name="weird.xml")
    assert outcome["reason"] == "" and outcome["framework"] == "unknown"


def test_parse_display_path_explicit():
    outcome = core.parse_xml_text(xml_doc([xml_suite("s", [])]), display_path="rel/junit.xml")
    assert outcome["display_path"] == "rel/junit.xml"


# ============================================================ flaky 边界
def test_flaky_non_terminating_rate_text():
    assert judge.classify_flaky([(1, "pass"), (2, "fail"), (3, "fail")])["fail_rate_text"] == "2/3"


def test_flaky_score_two_thirds():
    profile = judge.classify_flaky([(1, "pass"), (2, "fail"), (3, "fail"), (4, "pass")])
    assert profile["flaky_score"] == Fraction(2, 3)


def test_flaky_missing_between_fail_pass():
    profile = judge.classify_flaky([(1, "fail"), (2, "missing"), (3, "pass")])
    assert profile["transitions"] == 1
    assert profile["counted_runs"] == 2


def test_flaky_one_counted_pass_is_stable():
    # 旧仓口径：run 数够（>= min_runs）且 1 次计数且全过 → fail_rate 0 → stable
    # （零计数样本才兜底 watch；"1 次 pass" 不是零计数）
    assert judge.classify_flaky(
        [(1, "pass"), (2, "skip"), (3, "skip")])["label"] == spec.LABEL_STABLE


def test_flaky_two_runs_flaky_with_min_transitions_one():
    rules = dict(spec.FLAKY_RULES, min_transitions=1)
    assert judge.classify_flaky([(1, "pass"), (2, "fail")], rules)["label"] == spec.LABEL_FLAKY


def test_flaky_broken_precedence():
    rules = dict(spec.FLAKY_RULES, min_transitions=0, min_fail_rate="0")
    assert judge.classify_flaky([(1, "fail"), (2, "fail")], rules)["label"] == spec.LABEL_BROKEN


def test_flaky_label_counts_empty():
    assert judge.label_counts([]) == {}


# ============================================================ slow 边界
def test_percentile_p_zero():
    assert judge.percentile([5, 1, 9], "0") == Fraction(1)


def test_percentile_p_one():
    assert judge.percentile([5, 1, 9], "1") == Fraction(9)


def test_percentile_decimal_p():
    assert judge.percentile([0, 100], Decimal("0.75")) == Fraction(75)


def test_p50_all_missing_none():
    assert judge.p50([None, None]) is None


def test_bar_width_zero_time():
    assert judge.bar_width(0, 1000, 40) == 0


def test_bar_width_tiny_rounds_down():
    assert judge.bar_width(1, 1000, 1) == 0


def test_regression_custom_delta_equal_boundary():
    hit, _note = judge.regression(Fraction(1000), Fraction(1300),
                                  {"regression_ratio": "1.2", "regression_delta_ms": 300})
    assert hit is True


def test_sample_label_two_one_one():
    assert judge.sample_label(2, 1, 1) == ""


def test_profile_case_time_none_kept():
    assert judge.profile_case(1, "s", "c", "n", None, [100], None)["time_ms"] is None


def test_profile_case_zero_samples_label():
    profile = judge.profile_case(1, "s", "c", "n", None, [None, None], None)
    assert profile["label"] == spec.LABEL_INSUFFICIENT_HISTORY


def test_regression_list_empty():
    assert judge.regression_list([]) == []


# ============================================================ diff 边界
def test_diff_all_pairs_class_counts():
    statuses = [spec.STATUS_PASS, spec.STATUS_FAIL, spec.STATUS_SKIP, spec.STATUS_MISSING, None]
    counts = {kind: 0 for kind in spec.CLASS_ORDER}
    for before in statuses:
        for after in statuses:
            counts[judge.classify_status_pair(before, after)] += 1
    assert counts == {"new-failures": 4, "fixed": 1, "still-failing": 1, "unchanged": 19}


def test_diff_classify_rows_empty():
    assert judge.classify_rows([]) == []


def test_diff_group_rows_key_order():
    assert list(judge.group_rows([])) == list(spec.CLASS_ORDER)


def test_diff_new_failure_count_zero():
    assert judge.new_failure_count([]) == 0


# ============================================================ view 边界
def test_column_mode_zero_width():
    assert judge.column_mode(0) == "single"


def test_style_mode_empty_term_mono():
    assert judge.style_mode({"TERM": "", "COLORTERM": "truecolor"}) == "mono"


def test_markup_empty_tone_no_tags():
    assert judge.markup("x", "color", "") == "x"


def test_markup_escapes_brackets():
    assert judge.markup("[x]", "color", "red") == r"[red]\[x][/]"


def test_time_text_negative():
    assert judge.time_text(-5) == "-5 ms"


def test_sparkline_series_empty():
    assert judge.sparkline_series([]) == ([], 0)


def test_summary_text_all_none_lists_pending():
    text = judge.summary_text({"a": None, "b": None}, ["a", "b"])
    assert "待实装／无数据：a/b" in text


# ============================================================ 行集合边界
def test_tree_rows_fail_count():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "a"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "b"}],
        [occurrence(1, 1, "fail"), occurrence(1, 2, "fail")],
        suites=[{"suite_id": 1, "run_id": 1, "name": "s", "source_path": "",
                 "time_ms": None, "tests": 2, "failures": 2, "errors": 0, "skipped": 0}],
    )
    assert facts.tree_rows(data, 1)[0]["fail_count"] == 2


def test_tree_rows_ignores_other_run_suites():
    data = row_facts(
        [RUN1, RUN2], [], [],
        suites=[{"suite_id": 1, "run_id": 1, "name": "s1", "source_path": "",
                 "time_ms": None, "tests": 0, "failures": 0, "errors": 0, "skipped": 0},
                {"suite_id": 2, "run_id": 2, "name": "s2", "source_path": "",
                 "time_ms": None, "tests": 0, "failures": 0, "errors": 0, "skipped": 0}],
    )
    assert [suite["name"] for suite in facts.tree_rows(data, 1)] == ["s1"]


def test_window_runs_larger_than_history():
    assert len(facts.window_runs(row_facts([RUN1, RUN2], [], []), 2, 50)) == 2


def test_history_unknown_case_empty():
    assert facts.history(row_facts([RUN1], [], []), 99, 20) == []


def test_matrix_rows_empty_columns():
    data = row_facts([], [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}], [])
    _columns, rows = facts.matrix_rows(data, 1, 20)
    assert rows[0]["statuses"] == ()
    assert rows[0]["profile"] is None


def test_matrix_rows_without_profile_zero_score():
    data = row_facts([RUN1],
                     [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}], [])
    _columns, rows = facts.matrix_rows(data, 1, 20)
    assert rows[0]["flaky_score"] == 0


def test_slow_rows_empty_when_no_timing():
    data = row_facts([RUN1],
                     [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
                     [occurrence(1, 1, "pass", None)])
    assert facts.slow_rows(data, 1, 20) == []


def test_diff_rows_both_missing_empty():
    data = row_facts([RUN1, RUN2],
                     [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}], [])
    assert facts.diff_rows(data, 1, 2) == []


def test_summary_empty_facts_zero():
    result = facts.summary(row_facts([RUN1], [], []), 1, 20)
    assert result == {"total": 0, "fail": 0, "skip": 0, "flaky": 0, "broken": 0, "slow": 0}


def test_case_profiles_empty():
    assert facts.case_profiles(row_facts([RUN1], [], []), 1, 20) == {}


def test_aggregate_suites_none_time_merge():
    merged = facts.aggregate_suites([
        {"name": "s", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "time_ms": None},
        {"name": "s", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "time_ms": 100},
    ])
    assert merged[0]["time_ms"] == 100


def test_store_facts_empty():
    assert facts.Store().facts() == {"runs": [], "suites": [], "cases": [], "occurrences": []}


def test_ingest_zero_files():
    report = facts.ingest([])
    assert report["files"] == 0
    assert facts.summary_line(report) == (
        "ingest: files=0 runs=0 cases=0 occurrences=0 skipped=0 framework=")


# ============================================================ 账本边界
def test_api_junit_display_path_in_summary():
    record = summary({"mode": "junit", "xml": xml_doc([xml_suite("s", [])]),
                      "display_path": "rel/junit.xml"})
    assert record.evidence["file"] == "rel/junit.xml"


def test_api_junit_bytes_ok():
    payload = base64.b64encode(xml_doc([xml_suite("s", [xml_case("a")])]).encode()).decode()
    assert summary({"mode": "junit", "bytes_b64": payload}).evidence["reason"] == ""


def test_api_ingest_summary_line_message():
    record = only({"mode": "ingest", "files": [
        {"display_path": "f/junit.xml", "xml": xml_doc([xml_suite("s", [xml_case("a")])])}]},
        spec.R_INGEST_REPORT)
    assert record.message.startswith("ingest: files=1 runs=1 cases=1")


def test_api_ingest_degraded_record():
    records = [item for item in body({"mode": "ingest", "files": [
        {"display_path": "f/junit.xml",
         "xml": xml_doc([xml_suite("s", [xml_case("a", time="x")])])}]})
        if item.rule_id == spec.R_JUNIT_DEGRADED]
    record = [item for item in records if item.path == "degraded:" + spec.DEGRADED_BAD_TIME][0]
    assert record.evidence["count"] == 1


def test_api_flaky_rules_override():
    record = only({"mode": "flaky", "histories": [
        {"case_id": 1, "series": [[1, "pass"]], "rules": {"fallback_label": "pending"}}]},
        spec.R_FLAKY)
    assert record.evidence["label"] == "pending"


def test_api_gate_flaky_not_triggered():
    record = only({"mode": "gate", "fail_on": "flaky", "histories": [
        {"series": [[1, "pass"], [2, "pass"]]}]}, spec.R_GATE)
    assert record.verdict == "info"
    assert record.evidence["hit"] == 0


def test_api_gate_regressions_not_triggered():
    record = only({"mode": "gate", "fail_on": "regressions", "cases": [
        {"timings": [100, 100, 100, 100], "split": 2}]}, spec.R_GATE)
    assert record.evidence["triggered"] is False


def test_api_diff_summary_counts():
    record = only({"mode": "diff", "rows": [
        {"status_before": "pass", "status_after": "fail"},
        {"status_before": "fail", "status_after": "pass"}]}, spec.R_DIFF_SUMMARY)
    assert record.evidence == {"new-failures": 1, "fixed": 1, "still-failing": 0,
                               "unchanged": 0}


def test_api_views_slow_regression_record():
    data = row_facts(
        [RUN1, RUN2, RUN3, {"run_id": 4}],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
        [occurrence(1, 1, "pass", 100), occurrence(2, 1, "pass", 100),
         occurrence(3, 1, "pass", 500), occurrence(4, 1, "pass", 500)],
    )
    records = body({"mode": "views", "facts": data, "run_id": 4})
    slow = [record for record in records if record.path == "slow:1"]
    assert slow and slow[0].evidence["p50"] == "300"


def test_api_views_degrade_record():
    record = only({"mode": "views", "facts": row_facts([RUN1], [], [])}, spec.R_VIEW_DEGRADE)
    assert record.evidence["min_width_single_column"] == 80


def test_api_views_diff_record_with_previous():
    data = row_facts(
        [RUN1, RUN2],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
        [occurrence(1, 1, "pass"), occurrence(2, 1, "fail")],
    )
    records = body({"mode": "views", "facts": data})
    diff = [record for record in records if record.rule_id == spec.R_DIFF]
    assert diff and diff[0].evidence["kind"] == spec.NEW_FAILURES


def test_api_views_suite_fail_order():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "ok", "classname": "c", "name": "a"},
         {"case_id": 2, "suite_name": "bad", "classname": "c", "name": "b"}],
        [occurrence(1, 1, "pass"), occurrence(1, 2, "fail")],
        suites=[{"suite_id": 1, "run_id": 1, "name": "ok", "source_path": "",
                 "time_ms": None, "tests": 1, "failures": 0, "errors": 0, "skipped": 0},
                {"suite_id": 2, "run_id": 1, "name": "bad", "source_path": "",
                 "time_ms": None, "tests": 1, "failures": 1, "errors": 0, "skipped": 0}],
    )
    tree = [record for record in body({"mode": "views", "facts": data})
            if record.rule_id == spec.R_TREE]
    assert tree[0].evidence["name"] == "bad"


def test_ingest_run_group_framework_union():
    report = facts.ingest([
        {"display_path": "a/junit.xml", "file_name": "junit.xml",
         "xml": xml_doc([xml_suite("pytest", [xml_case("a")])], name="", attrs=' ci_run_id="1"')},
        {"display_path": "b/gotestsum.xml", "file_name": "gotestsum.xml",
         "xml": xml_doc([xml_suite("demo", [xml_case("b")])], name="", attrs=' ci_run_id="1"')},
    ])
    run = list(report["store"].runs.values())[0]
    assert run["framework"] == "gotestsum,pytest"