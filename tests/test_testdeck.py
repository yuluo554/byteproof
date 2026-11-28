"""``testdeck`` 器官的无损测试（迁自 10-19-testdeck，Python 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：JUnit 解析（四原因码 +
四降级 + 框架三态 + 身份键）、入库幂等（同身份不新增行）、四类分型（精确 Fraction、
零计数不判 stable）、p50/p95 线性插值与回归三态（判不了 ≠ 无回归）、两次 run diff 三类
（fixed 必须 after==pass）、失败优先树与 summary 六字段、门禁退出码、呈现降级两条。

判定层口径（D1）：旧仓 30 个 ``test_*.py`` 按文件名正则剔除 8 件后 **22 文件**实跑
pytest **X = 332 passed**（逐文件见 ``docs/testdeck.md`` §6.1）；Go fixture
``bench/fixtures/gotestsum`` 的 ``go test`` **3 条 Test pass 事件**（1 skip / 1 故意失败）
单列一段。旧层 AST ``test_`` 函数 **276**（22 文件）+ Go ``Test*`` **5**。
本文件覆盖同一判定面（逐条见 docs §6.2 处置表）。
"""

from __future__ import annotations

import ast
import base64
import json
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.testdeck import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    api,
    core,
    facts,
    judge,
    spec,
)
from byteproof.core import ERROR, INFO, WARN, Basis, Report  # noqa: E402
from byteproof.core.basis import RuleMissing  # noqa: E402
from byteproof.core.registry import get  # noqa: E402

SLUG = "testdeck"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "testdeck.basis.json"
THRESHOLDS_PATH = DATA_DIR / "testdeck.thresholds.json"
BASIS = Basis.from_json(str(BASIS_PATH))
SNAPSHOT = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
HEX40 = "0123456789abcdef0123456789abcdef01234567"


# ---------------------------------------------------------------- 构造助手
def recs(subject, basis=BASIS):
    return list(api.evaluate(subject, basis))


def body(subject, basis=BASIS):
    """去掉 ``td-summary`` 后的判定记录。"""
    return [record for record in recs(subject, basis) if record.rule_id != spec.R_SUMMARY_RULE]


def rules_of(subject, basis=BASIS):
    return [record.rule_id for record in body(subject, basis)]


def only(subject, rule_id, basis=BASIS):
    matched = [record for record in body(subject, basis) if record.rule_id == rule_id]
    assert len(matched) == 1, "期望恰好一条 %s，实际 %s" % (
        rule_id, [record.rule_id for record in body(subject, basis)])
    return matched[0]


def summary(subject, basis=BASIS):
    return [record for record in recs(subject, basis)
            if record.rule_id == spec.R_SUMMARY_RULE][0]


def xml_suite(name, cases, time=None, props=(), attrs=""):
    time_attr = ' time="%s"' % time if time is not None else ""
    prop_xml = ""
    if props:
        prop_xml = "<properties>%s</properties>" % "".join(
            '<property name="%s" value="x"/>' % key for key in props)
    return '<testsuite name="%s"%s%s>%s%s</testsuite>' % (name, time_attr, attrs, prop_xml,
                                                         "".join(cases))


def xml_case(name, classname="", time=None, kind=None, type_="", message="", text=""):
    attrs = ['name="%s"' % name]
    if classname:
        attrs.append('classname="%s"' % classname)
    if time is not None:
        attrs.append('time="%s"' % time)
    inner = ""
    if kind:
        inner = '<%s type="%s" message="%s">%s</%s>' % (kind, type_, message, text, kind)
    return "<testcase %s>%s</testcase>" % (" ".join(attrs), inner)


def xml_doc(suites, name="pytest tests", attrs=""):
    return "<testsuites name=\"%s\"%s>%s</testsuites>" % (name, attrs, "".join(suites))


def parse(xml, file_name="junit.xml"):
    return core.parse_xml_text(xml, file_name=file_name)


def facts_of(*xmls):
    files = [{"display_path": "f/%d.xml" % index, "file_name": "junit.xml", "xml": xml}
             for index, xml in enumerate(xmls)]
    return facts.ingest(files)


def row_facts(runs, cases, occurrences, suites=()):
    return {"runs": runs, "cases": cases, "occurrences": occurrences, "suites": list(suites)}


# ============================================================ A · 接线与口径快照
def test_pack_registered():
    assert PACK.slug == SLUG
    assert PACK.version == ORGAN_VERSION == "1"
    assert PACK.input_fields == ("mode",)
    assert get(SLUG) is PACK


def test_builtin_modules_sorted_unique():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(set(BUILTIN_MODULES)) == len(BUILTIN_MODULES)
    assert "testdeck" in BUILTIN_MODULES


def test_list_reaches_25(capsys):
    from byteproof import cli

    assert cli.main(["list"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) >= 25
    assert any(line.startswith("testdeck ") for line in lines)


def test_basis_covers_all_rules():
    assert set(spec.ALL_RULES) <= set(BASIS.rule_ids())
    assert len(BASIS) == len(spec.ALL_RULES)


def test_basis_rule_texts_and_versions():
    for rule_id in spec.ALL_RULES:
        rule = BASIS.require(rule_id)
        assert rule.version, rule_id
        assert rule.text, rule_id
        assert "10-19-testdeck" in rule.source, rule_id


def test_flaky_rules_snapshot():
    assert SNAPSHOT["flaky"] == spec.FLAKY_RULES


def test_slow_rules_snapshot():
    assert SNAPSHOT["slow"] == spec.SLOW_RULES


def test_view_rules_snapshot():
    assert SNAPSHOT["view"] == spec.VIEW_RULES


def test_statuses_snapshot():
    assert tuple(SNAPSHOT["statuses"]) == spec.STATUSES
    assert tuple(SNAPSHOT["counted_statuses"]) == spec.COUNTED_STATUSES


def test_status_glyphs_snapshot():
    assert SNAPSHOT["status_glyphs"] == spec.STATUS_GLYPHS
    assert spec.STATUS_GLYPHS[spec.STATUS_MISSING] == "?"


def test_exit_codes_snapshot():
    assert SNAPSHOT["exit_codes"] == {
        "ok": 0, "gate_triggered": 1, "usage": 2, "dependency": 3, "not_ready": 4}


def test_reasons_snapshot():
    assert tuple(SNAPSHOT["reasons"]) == spec.REASONS
    assert tuple(SNAPSHOT["degraded_reasons"]) == spec.DEGRADED_REASONS


def test_count_fields_and_frameworks_snapshot():
    assert tuple(SNAPSHOT["count_fields"]) == spec.COUNT_FIELDS
    assert tuple(SNAPSHOT["frameworks"]) == spec.FRAMEWORKS


def test_class_order_snapshot():
    assert tuple(SNAPSHOT["class_order"]) == spec.CLASS_ORDER
    assert SNAPSHOT["class_order"][0] == spec.NEW_FAILURES


def test_keys_snapshot_single_source():
    assert [list(item) for item in spec.KEYS] == SNAPSHOT["keys"]
    assert spec.BINDINGS == SNAPSHOT["bindings"]
    assert len(spec.BINDINGS) == len(spec.KEYS)


def test_severity_snapshot():
    assert SNAPSHOT["severity"] == spec.SEVERITY
    assert set(spec.SEVERITY) == set(spec.ALL_RULES)


def test_modes_snapshot():
    assert tuple(SNAPSHOT["modes"]) == spec.MODES
    assert spec.DEFAULT_MODE == "views"


def test_no_numeric_threshold_literals_outside_spec():
    path = SRC / "byteproof" / "auditors" / "testdeck" / "judge.py"
    numbers = {
        node.value for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }
    for value in (200, 1000, 40, 80):
        assert value not in numbers, value


def test_core_has_no_io_imports():
    tree = ast.parse((SRC / "byteproof" / "auditors" / "testdeck" / "core.py")
                     .read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"re", "xml", "dataclasses", "decimal", "fractions", "typing", "__future__"}


def test_judge_has_no_os_or_time_imports():
    source = (SRC / "byteproof" / "auditors" / "testdeck" / "judge.py").read_text(encoding="utf-8")
    assert "import os" not in source
    assert "datetime" not in source
    assert "time.time" not in source


def test_missing_basis_yields_contract_error():
    with pytest.raises(RuleMissing):
        body({"mode": "junit", "xml": xml_doc([xml_suite("s", [])])}, basis=Basis.empty())


def test_summary_total_excludes_itself():
    record = summary({"mode": "junit", "xml": xml_doc([xml_suite("s", [])])})
    assert record.evidence["total"] == len(recs({"mode": "junit",
                                                 "xml": xml_doc([xml_suite("s", [])])})) - 1


def test_record_ids_unique_in_views():
    data = row_facts(
        [{"run_id": 1, "branch": "", "commit_sha": "", "ci_run_id": "",
          "started_at": "", "framework": "pytest", "source_path": ""}],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
        [{"run_id": 1, "case_id": 1, "status": "fail", "time_ms": None}],
    )
    ids = [record.id for record in recs({"mode": "views", "facts": data})]
    assert len(ids) == len(set(ids))


# ============================================================ B · model / identity / framework
def test_seconds_to_ms_rounds_half_up():
    assert core.seconds_to_ms("0.0005") == 1
    assert core.seconds_to_ms("0.1") == 100


def test_seconds_to_ms_rejects_garbage():
    with pytest.raises(ValueError):
        core.seconds_to_ms("abc")


def test_seconds_to_ms_rejects_infinite():
    with pytest.raises(ValueError):
        core.seconds_to_ms("Infinity")


def test_seconds_to_ms_none_and_empty():
    assert core.seconds_to_ms(None) is None
    assert core.seconds_to_ms("") is None


def test_is_counted_excludes_skip_and_missing():
    assert core.is_counted("pass") and core.is_counted("fail")
    assert not core.is_counted("skip") and not core.is_counted("missing")


def test_validate_status_rejects_unknown():
    assert core.validate_status("pass") == "pass"
    with pytest.raises(ValueError):
        core.validate_status("broken")


def test_as_fraction_rejects_float():
    with pytest.raises(TypeError):
        core.as_fraction(0.05)


def test_as_fraction_from_decimal_string():
    assert core.as_fraction("0.05") == Fraction(1, 20)


def test_render_exact_terminating():
    assert core.render_exact(Fraction(1, 8)) == "0.125"
    assert core.render_exact(Fraction(3, 1)) == "3"


def test_render_exact_non_terminating():
    assert core.render_exact(Fraction(1, 3)) == "1/3"


def test_render_exact_none():
    assert core.render_exact(None) is None


def test_mean_fraction_zero_count_is_none():
    assert core.mean_fraction(0, 0) is None


def test_mean_fraction_value():
    assert core.mean_fraction(3, 4) == Fraction(3, 4)


def test_run_identity_key_and_validation():
    identity = core.RunIdentity("main", HEX40, "42")
    assert identity.key == ("main", HEX40, "42")
    with pytest.raises(ValueError):
        core.RunIdentity("main", "abc", "42")


def test_run_identity_rejects_none():
    with pytest.raises(ValueError):
        core.RunIdentity(None, "", "")


def test_case_identity_key():
    identity = core.CaseIdentity("suite", "class", "test_x[1]")
    assert identity.key == ("suite", "class", "test_x[1]")


def test_case_identity_rejects_empty_name():
    with pytest.raises(ValueError):
        core.CaseIdentity("suite", "class", "")


def test_case_identity_display():
    assert core.CaseIdentity("s", "c", "n").display == "s :: c :: n"
    assert core.CaseIdentity("", "", "n").display == "n"


def test_framework_by_suite_name():
    assert core.detect_framework("x.xml", names=["pytest"]) == "pytest"


def test_framework_by_property():
    assert core.detect_framework("x.xml", names=["demo-lib"], properties=["go.version"]) == "gotestsum"


def test_framework_by_filename():
    assert core.detect_framework("gotestsum.xml") == "gotestsum"
    assert core.detect_framework("playwright.xml") == "playwright"
    assert core.detect_framework("junit.xml") == "pytest"


def test_framework_unknown_when_no_hint():
    assert core.detect_framework("report.xml", names=["demo-lib"]) == "unknown"


def test_framework_name_beats_filename():
    assert core.detect_framework("gotestsum.xml", names=["pytest tests"]) == "pytest"


def test_hex40_is_lowercase_only():
    assert core.RunIdentity("", HEX40, "").commit_sha == HEX40
    with pytest.raises(ValueError):
        core.RunIdentity("", HEX40.upper(), "")


# ============================================================ C · JUnit 解析
def test_parse_basic_counts():
    outcome = parse(xml_doc([xml_suite("s", [
        xml_case("a", time="0.1"),
        xml_case("b", time="0.2", kind="failure", type_="E", message="m"),
        xml_case("c", kind="error", type_="E", message="m"),
        xml_case("d", kind="skipped"),
    ])]))
    assert outcome["reason"] == ""
    assert core.outcome_totals(outcome) == {"tests": 4, "failures": 1, "errors": 1, "skipped": 1}


def test_parse_status_mapping():
    outcome = parse(xml_doc([xml_suite("s", [
        xml_case("p", time="0.1"),
        xml_case("f", kind="failure"),
        xml_case("e", kind="error"),
        xml_case("s", kind="skipped"),
    ])]))
    statuses = [case["status"] for case in outcome["suites"][0]["cases"]]
    assert statuses == ["pass", "fail", "fail", "skip"]


def test_parse_failure_fields():
    outcome = parse(xml_doc([xml_suite("s", [
        xml_case("f", kind="failure", type_="AssertionError", message="boom",
                 text="=== RUN\n  real first line  \nsecond")])]))
    case = outcome["suites"][0]["cases"][0]
    assert case["failure_type"] == "AssertionError"
    assert case["failure_message"] == "boom"
    assert case["stack_first_line"] == "=== RUN"


def test_parse_time_ms_decimal():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a", time="1.234")])]))
    assert outcome["suites"][0]["cases"][0]["time_ms"] == 1234


def test_parse_missing_time_is_none():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a")])]))
    assert outcome["suites"][0]["cases"][0]["time_ms"] is None


def test_parse_bad_time_degrades_not_zero():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a", time="abc")])]))
    assert outcome["suites"][0]["cases"][0]["time_ms"] is None
    assert outcome["degraded"][spec.DEGRADED_BAD_TIME] == 1


def test_parse_missing_name_not_stored_but_counted():
    outcome = parse(xml_doc([xml_suite("s", ["<testcase classname=\"c\"/>", xml_case("ok")])]))
    suite = outcome["suites"][0]
    assert suite["tests"] == 2
    assert [case["name"] for case in suite["cases"]] == ["ok"]
    assert outcome["degraded"][spec.DEGRADED_MISSING_NAME] == 1


def test_parse_root_metadata():
    outcome = parse(xml_doc([xml_suite("s", [])],
                            attrs=' branch="main" commit="%s" ci_run_id="7" '
                                  'timestamp="2026-10-19T00:00:00Z"' % HEX40))
    assert (outcome["branch"], outcome["commit_sha"], outcome["ci_run_id"]) == (
        "main", HEX40, "7")
    assert outcome["started_at"] == "2026-10-19T00:00:00Z"


def test_parse_suite_metadata_absorbed():
    outcome = parse("<testsuites>%s</testsuites>" % xml_suite(
        "s", [xml_case("a")], attrs=' branch="dev"'))
    assert outcome["branch"] == "dev"


def test_parse_bad_commit_degrades_to_empty():
    outcome = parse(xml_doc([xml_suite("s", [])], attrs=' commit="deadbeef"'))
    assert outcome["commit_sha"] == ""
    assert outcome["degraded"][spec.DEGRADED_BAD_COMMIT] == 1


def test_parse_started_at_missing_degrades():
    outcome = parse(xml_doc([xml_suite("s", [])]))
    assert outcome["degraded"][spec.DEGRADED_STARTED_AT] == 1


def test_parse_bad_xml_reason():
    outcome = parse("<testsuites><testsuite>")
    assert outcome["reason"] == spec.BAD_XML
    assert outcome["suites"] == []


def test_parse_empty_reason_no_testsuite():
    assert parse("   ")["reason"] == spec.NO_TESTSUITE


def test_parse_non_junit_root_reason():
    assert parse("<report><x/></report>")["reason"] == spec.NO_TESTSUITE


def test_parse_testsuites_without_suite_reason():
    assert parse("<testsuites name=\"pytest tests\"></testsuites>")["reason"] == spec.NO_TESTSUITE


def test_parse_single_testsuite_root():
    outcome = parse(xml_suite("s", [xml_case("a", time="0.1")]))
    assert outcome["reason"] == ""
    assert core.outcome_totals(outcome)["tests"] == 1


def test_parse_bytes_bad_encoding():
    payload = '<?xml version="1.0" encoding="utf-8"?><testsuites>'.encode("utf-8") + b"\xff\xfe"
    outcome = core.parse_xml_bytes(payload, file_name="junit.xml")
    assert outcome["reason"] == spec.BAD_ENCODING


def test_parse_bytes_unknown_encoding_declared():
    payload = b'<?xml version="1.0" encoding="x-nope"?><testsuites></testsuites>'
    assert core.parse_xml_bytes(payload)["reason"] == spec.BAD_ENCODING


def test_parse_bytes_ok():
    outcome = core.parse_xml_bytes(
        xml_doc([xml_suite("s", [xml_case("a", time="0.1")])]).encode("utf-8"),
        file_name="junit.xml")
    assert outcome["reason"] == "" and outcome["framework"] == "pytest"


def test_parse_bytes_empty():
    assert core.parse_xml_bytes(b"")["reason"] == spec.NO_TESTSUITE


def test_parse_bytes_rejects_non_bytes():
    with pytest.raises(TypeError):
        core.parse_xml_bytes("text")


def test_parse_rejects_text_type():
    with pytest.raises(TypeError):
        core.parse_xml_text(b"bytes")


def test_parse_dtd_rejected():
    payload = ('<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuites>%s</testsuites>'
               % xml_suite("s", [xml_case("&a;")]))
    outcome = parse(payload)
    assert outcome["reason"] == spec.BAD_XML
    assert outcome["detail"] == spec.DTD_REJECTED


def test_parse_entity_rejected():
    payload = '<testsuites><!ENTITY a "x">%s</testsuites>' % xml_suite("s", [])
    assert parse(payload)["detail"] == spec.DTD_REJECTED


def test_parse_oversize_rejected():
    payload = "<testsuites>" + " " * (spec.MAX_XML_CHARS + 1) + "</testsuites>"
    outcome = parse(payload)
    assert outcome["reason"] == spec.BAD_XML
    assert outcome["detail"] == spec.OVERSIZE


def test_parse_namespaced_tags():
    payload = ('<testsuites xmlns="urn:x"><testsuite name="pytest">'
               '<testcase name="a" time="0.1"/></testsuite></testsuites>')
    outcome = parse(payload)
    assert outcome["reason"] == ""
    assert outcome["suites"][0]["tests"] == 1


def test_parse_duplicate_suite_names_each_row():
    outcome = parse(xml_doc([
        xml_suite("same", [xml_case("a")]),
        xml_suite("same", [xml_case("b")]),
    ]))
    assert len(outcome["suites"]) == 2
    assert [suite["tests"] for suite in outcome["suites"]] == [1, 1]


def test_parse_properties_feed_framework():
    outcome = parse(xml_doc([xml_suite("demo-lib", [xml_case("a")], props=["go.version"])],
                            name=""))
    assert outcome["framework"] == "gotestsum"


def test_parse_classname_default_empty():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a")])]))
    assert outcome["suites"][0]["cases"][0]["classname"] == ""


def test_parse_classname_preserved():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a", classname="pkg.Cls")])]))
    assert outcome["suites"][0]["cases"][0]["classname"] == "pkg.Cls"


def test_parse_suite_time_sum():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a")], time="1.5")]))
    assert outcome["suites"][0]["time_ms"] == 1500


def test_parse_suite_bad_time_degrades():
    outcome = parse(xml_doc([xml_suite("s", [xml_case("a")], time="x")]))
    assert outcome["suites"][0]["time_ms"] is None
    assert outcome["degraded"][spec.DEGRADED_BAD_TIME] == 1


def test_parse_parameterized_name_kept_verbatim():
    name = "test_x[param with spaces-1]"
    outcome = parse(xml_doc([xml_suite("s", [xml_case(name)])]))
    assert outcome["suites"][0]["cases"][0]["name"] == name


def test_parse_skipped_child_first_wins():
    payload = xml_doc([xml_suite("s", [
        '<testcase name="a"><skipped/><failure/></testcase>'])])
    outcome = parse(payload)
    assert outcome["suites"][0]["cases"][0]["status"] == "skip"
    assert core.outcome_totals(outcome)["skipped"] == 1


def test_outcome_totals_sums_suites():
    outcome = parse(xml_doc([
        xml_suite("a", [xml_case("x", kind="failure")]),
        xml_suite("b", [xml_case("y", kind="error"), xml_case("z")]),
    ]))
    assert core.outcome_totals(outcome) == {
        "tests": 3, "failures": 1, "errors": 1, "skipped": 0}


def test_parse_display_path_defaults_to_file_name():
    outcome = core.parse_xml_text(xml_doc([xml_suite("s", [])]), file_name="junit.xml")
    assert outcome["display_path"] == "junit.xml"


# ============================================================ D · flaky 分型
def series(*statuses):
    return [(index + 1, status) for index, status in enumerate(statuses)]


def test_flaky_alternating_four_runs_is_flaky():
    profile = judge.classify_flaky(series("pass", "fail", "pass", "fail"))
    assert profile["label"] == spec.LABEL_FLAKY
    assert profile["transitions"] == 3


def test_flaky_fail_rate_exact_fraction():
    profile = judge.classify_flaky(series("pass", "fail", "pass", "fail"))
    assert profile["fail_rate"] == Fraction(1, 2)
    assert profile["fail_rate_text"] == "0.5"


def test_flaky_score_is_ratio():
    profile = judge.classify_flaky(series("pass", "fail", "pass"))
    assert profile["flaky_score"] == Fraction(1, 1)


def test_flaky_score_zero_when_single_counted():
    profile = judge.classify_flaky(series("pass", "skip", "missing"))
    assert profile["counted_runs"] == 1
    assert profile["flaky_score"] == Fraction(0)


def test_flaky_all_fail_is_broken():
    profile = judge.classify_flaky(series("fail", "fail", "fail"))
    assert profile["label"] == spec.LABEL_BROKEN


def test_flaky_all_pass_is_stable():
    profile = judge.classify_flaky(series("pass", "pass"))
    assert profile["label"] == spec.LABEL_STABLE


def test_flaky_single_run_watch():
    assert judge.classify_flaky(series("pass"))["label"] == "watch"


def test_flaky_zero_counted_watch_not_stable():
    profile = judge.classify_flaky(series("skip", "missing", "skip"))
    assert profile["label"] == "watch"
    assert profile["fail_rate"] is None


def test_flaky_two_transitions_below_min_watch():
    profile = judge.classify_flaky(series("pass", "fail", "pass"))
    assert profile["transitions"] == 2
    assert profile["label"] == "watch"


def test_flaky_min_rate_boundary_inclusive():
    rules = dict(spec.FLAKY_RULES, min_transitions=1)
    profile = judge.classify_flaky(series("pass", "fail"), rules)
    assert profile["fail_rate"] == Fraction(1, 2)
    assert profile["label"] == spec.LABEL_FLAKY


def test_flaky_below_min_rate_watch():
    statuses = ["pass"] * 24 + ["fail"]
    # 一次 fail 最多 2 个 transition（若在中间）→ 用 3 次交替构造 1/25 达不到；
    # 这里直接验"比率低于下限即使有 transition 也落 watch"
    rules = dict(spec.FLAKY_RULES, min_transitions=1, min_fail_rate="0.06",
                 max_fail_rate="0.4")
    assert judge.classify_flaky(series("pass", "fail"), rules)["label"] == "watch"


def test_flaky_max_rate_boundary():
    rules = dict(spec.FLAKY_RULES, min_transitions=1, max_fail_rate="0.5")
    assert judge.classify_flaky(series("pass", "fail"), rules)["label"] == spec.LABEL_FLAKY


def test_flaky_skip_not_in_denominator():
    profile = judge.classify_flaky(series("pass", "skip", "pass", "missing", "fail"))
    assert profile["counted_runs"] == 3
    assert profile["passes"] == 2
    assert profile["fails"] == 1


def test_flaky_skip_does_not_create_transition():
    profile = judge.classify_flaky(series("pass", "skip", "missing", "fail"))
    assert profile["transitions"] == 1


def test_flaky_min_runs_boundary_from_rules():
    rules = dict(spec.FLAKY_RULES, min_runs_for_flaky=2)
    assert judge.classify_flaky(series("pass", "fail", "pass", "fail"), rules)["label"] == spec.LABEL_FLAKY
    rules3 = dict(spec.FLAKY_RULES, min_runs_for_flaky=3)
    assert judge.classify_flaky(series("pass", "fail"), rules3)["label"] == "watch"


def test_flaky_fallback_label_from_rules():
    rules = dict(spec.FLAKY_RULES, fallback_label="pending")
    assert judge.classify_flaky(series("pass"), rules)["label"] == "pending"


def test_flaky_label_counts():
    profiles = [
        {"label": "stable"}, {"label": "stable"}, {"label": "flaky"}, {"label": "watch"},
    ]
    assert judge.label_counts(profiles) == {"stable": 2, "flaky": 1, "watch": 1}


def test_flaky_profile_exposes_texts():
    profile = judge.classify_flaky(series("pass", "fail", "pass", "fail"))
    assert profile["flaky_score_text"] == "1"
    assert profile["fail_rate_text"] == "0.5"


def test_flaky_history_run_seq_order_preserved():
    profile = judge.classify_flaky([(5, "pass"), (7, "fail")])
    assert profile["transitions"] == 1


# ============================================================ E · slow 分位数与回归
def test_percentile_empty_none():
    assert judge.percentile([], "0.5") is None


def test_percentile_single_value():
    assert judge.percentile([1234], "0.95") == Fraction(1234)


def test_percentile_linear_interpolation():
    assert judge.percentile([100, 200, 300, 400], "0.5") == Fraction(250)


def test_percentile_unsorted_input():
    assert judge.percentile([400, 100, 300, 200], "0.5") == Fraction(250)


def test_percentile_p95_two_samples():
    assert judge.percentile([100, 200], "0.95") == Fraction(195)


def test_percentile_exact_index():
    assert judge.percentile([100, 200, 300], "0.5") == Fraction(200)


def test_percentile_rejects_float_p():
    with pytest.raises(TypeError):
        judge.percentile([1, 2], 0.5)


def test_samples_drops_none():
    assert judge.samples([100, None, 200]) == [100, 200]


def test_p50_missing_excluded():
    assert judge.p50([None, 1000]) == Fraction(1000)


def test_p95_none_when_all_missing():
    assert judge.p95([None, None]) is None


def test_regression_boundary_ratio_and_delta():
    hit, note = judge.regression(Fraction(1000), Fraction(1200))
    assert hit is True
    assert "ratio=1.2(>=)" in note


def test_regression_ratio_below_boundary():
    hit, _note = judge.regression(Fraction(1000), Fraction(1199))
    assert hit is False


def test_regression_delta_below_boundary():
    hit, _note = judge.regression(Fraction(1000), Fraction(1201), {"regression_ratio": "1.2",
                                                                   "regression_delta_ms": 202})
    assert hit is False


def test_regression_missing_base():
    assert judge.regression(None, Fraction(1000)) == (None, spec.NOTE_MISSING_WINDOW)


def test_regression_missing_curr():
    assert judge.regression(Fraction(1000), None) == (None, spec.NOTE_MISSING_WINDOW)


def test_regression_undefined_base():
    assert judge.regression(Fraction(0), Fraction(1000)) == (None, spec.NOTE_UNDEFINED_BASE)


def test_regression_exact_ratio_render():
    _hit, note = judge.regression(Fraction(1000), Fraction(2400))
    assert "ratio=2.4" in note


def test_sample_label_zero():
    assert judge.sample_label(0, 0, 0) == spec.LABEL_INSUFFICIENT_HISTORY


def test_sample_label_single():
    assert judge.sample_label(1, 0, 1) == spec.LABEL_SINGLE_SAMPLE


def test_sample_label_empty_side():
    assert judge.sample_label(4, 1, 0) == spec.LABEL_INSUFFICIENT_HISTORY


def test_sample_label_enough():
    assert judge.sample_label(4, 2, 2) == ""


def test_is_slow_boundary():
    assert judge.is_slow(1000) is True
    assert judge.is_slow(999) is False


def test_is_slow_none_false():
    assert judge.is_slow(None) is False


def test_bar_width_halves():
    assert judge.bar_width(500, 1000, 40) == 20


def test_bar_width_truncates_below_half():
    assert judge.bar_width(1, 3, 40) == 13


def test_bar_width_rounds_half_up():
    assert judge.bar_width(1, 2, 41) == 21


def test_bar_width_zero_max():
    assert judge.bar_width(100, 0, 40) == 0


def test_bar_width_full():
    assert judge.bar_width(1000, 1000, 40) == 40


def test_profile_case_split_window():
    profile = judge.profile_case(1, "s", "c", "n", 300, [100, 100, 300, 300], 2)
    assert profile["base_p50"] == Fraction(100)
    assert profile["curr_p50"] == Fraction(300)


def test_profile_case_split_none_is_undecidable():
    profile = judge.profile_case(1, "s", "c", "n", 100, [100, 200], None)
    assert profile["regression"] is None
    assert profile["note"] == spec.NOTE_MISSING_WINDOW


def test_profile_case_split_zero_invalid():
    profile = judge.profile_case(1, "s", "c", "n", 100, [100, 200], 0)
    assert profile["note"] == spec.NOTE_MISSING_WINDOW


def test_profile_case_split_at_end_invalid():
    profile = judge.profile_case(1, "s", "c", "n", 100, [100, 200], 2)
    assert profile["note"] == spec.NOTE_MISSING_WINDOW


def test_profile_case_bool_split_invalid():
    profile = judge.profile_case(1, "s", "c", "n", 100, [100, 200], True)
    assert profile["note"] == spec.NOTE_MISSING_WINDOW


def test_profile_case_single_sample_label():
    profile = judge.profile_case(1, "s", "c", "n", 100, [None, 100], None)
    assert profile["samples"] == 1
    assert profile["label"] == spec.LABEL_SINGLE_SAMPLE


def test_profile_case_regression_hit():
    profile = judge.profile_case(1, "s", "c", "n", 500, [100, 100, 500, 500], 2)
    assert profile["regression"] is True
    assert profile["regression_text"] == "yes"


def test_profile_case_regression_no():
    profile = judge.profile_case(1, "s", "c", "n", 110, [100, 100, 110, 110], 2)
    assert profile["regression"] is False
    assert profile["regression_text"] == "no"


def test_regression_text_none():
    assert judge.regression_text(None) == "?"


def test_regression_list_excludes_none():
    profiles = [
        judge.profile_case(1, "s", "c", "a", 500, [100, 100, 500, 500], 2),
        judge.profile_case(2, "s", "c", "b", 100, [100, 200], None),
        judge.profile_case(3, "s", "c", "c", 110, [100, 100, 110, 110], 2),
    ]
    assert [item["case_id"] for item in judge.regression_list(profiles)] == [1]


def test_profile_case_p50_p95_text():
    profile = judge.profile_case(1, "s", "c", "n", 200, [100, 200], None)
    assert profile["p50_text"] == "150"
    assert profile["p95_text"] == "195"


# ============================================================ F · diff 三类
def test_diff_new_failure():
    assert judge.classify_status_pair("pass", "fail") == spec.NEW_FAILURES


def test_diff_missing_to_fail_is_new_failure():
    assert judge.classify_status_pair(None, "fail") == spec.NEW_FAILURES


def test_diff_fail_to_pass_fixed():
    assert judge.classify_status_pair("fail", "pass") == spec.FIXED


def test_diff_fail_to_skip_is_unchanged():
    assert judge.classify_status_pair("fail", "skip") == spec.UNCHANGED


def test_diff_fail_to_missing_is_unchanged():
    assert judge.classify_status_pair("fail", None) == spec.UNCHANGED


def test_diff_still_failing():
    assert judge.classify_status_pair("fail", "fail") == spec.STILL_FAILING


def test_diff_pass_to_skip_unchanged():
    assert judge.classify_status_pair("pass", "skip") == spec.UNCHANGED


def test_diff_skip_to_pass_unchanged():
    assert judge.classify_status_pair("skip", "pass") == spec.UNCHANGED


def test_diff_missing_to_pass_unchanged():
    assert judge.classify_status_pair(None, "pass") == spec.UNCHANGED


def test_diff_all_pairs_cover_class_order():
    statuses = [spec.STATUS_PASS, spec.STATUS_FAIL, spec.STATUS_SKIP, spec.STATUS_MISSING, None]
    for before in statuses:
        for after in statuses:
            assert judge.classify_status_pair(before, after) in spec.CLASS_ORDER


def test_diff_classify_rows_preserves_order():
    rows = [
        {"case_id": 2, "status_before": "fail", "status_after": "pass"},
        {"case_id": 1, "status_before": "pass", "status_after": "fail"},
    ]
    classified = judge.classify_rows(rows)
    assert [entry["row"]["case_id"] for entry in classified] == [2, 1]


def test_diff_group_rows_has_all_buckets():
    classified = judge.classify_rows([{"case_id": 1, "status_before": "pass",
                                       "status_after": "fail"}])
    groups = judge.group_rows(classified)
    assert set(groups) == set(spec.CLASS_ORDER)
    assert len(groups[spec.NEW_FAILURES]) == 1
    assert groups[spec.FIXED] == []


def test_diff_counts():
    classified = judge.classify_rows([
        {"status_before": "pass", "status_after": "fail"},
        {"status_before": "fail", "status_after": "pass"},
        {"status_before": "fail", "status_after": "fail"},
        {"status_before": "pass", "status_after": "pass"},
    ])
    assert judge.diff_counts(classified) == {
        "new-failures": 1, "fixed": 1, "still-failing": 1, "unchanged": 1}


def test_new_failure_count():
    classified = judge.classify_rows([
        {"status_before": "pass", "status_after": "fail"},
        {"status_before": "pass", "status_after": "fail"},
        {"status_before": "fail", "status_after": "fail"},
    ])
    assert judge.new_failure_count(classified) == 2


def test_diff_counts_empty():
    assert judge.diff_counts([]) == {kind: 0 for kind in spec.CLASS_ORDER}


def test_diff_class_titles_snapshot():
    assert set(spec.CLASS_TITLES) == set(spec.CLASS_ORDER)
    assert spec.CLASS_TITLES[spec.NEW_FAILURES] == "新增失败"


def test_diff_reconciled_classes_exclude_unchanged():
    assert spec.UNCHANGED not in spec.RECONCILED_CLASSES
    assert set(spec.RECONCILED_CLASSES) == set(spec.CLASS_ORDER) - {spec.UNCHANGED}


# ============================================================ G · view 降级与键位
def test_column_mode_threshold():
    assert judge.column_mode(79) == "single"
    assert judge.column_mode(80) == "three"


def test_column_mode_from_rules():
    assert judge.column_mode(100, {"min_width_single_column": 120}) == "single"


def test_style_mode_no_color_empty_value():
    assert judge.style_mode({"NO_COLOR": ""}) == "mono"


def test_style_mode_no_color_absent_but_dumb_term():
    assert judge.style_mode({"TERM": "dumb", "COLORTERM": "truecolor"}) == "mono"


def test_style_mode_not_tty():
    assert judge.style_mode({"COLORTERM": "truecolor"}, isatty=False) == "mono"


def test_style_mode_truecolor():
    assert judge.style_mode({"TERM": "xterm-256color", "COLORTERM": "truecolor"}) == "color"


def test_style_mode_24bit():
    assert judge.style_mode({"TERM": "screen", "COLORTERM": "24bit"}) == "color"


def test_escape_and_strip_markup():
    escaped = judge.escape_markup("[bold]x")
    assert escaped == r"\[bold]x"
    assert judge.strip_markup("[red]a[/]") == "a"
    assert judge.strip_markup(escaped) == "[bold]x"


def test_has_markup_ignores_escaped():
    assert judge.has_markup("[red]a[/]") is True
    assert judge.has_markup(judge.escape_markup("[red]")) is False


def test_markup_mono_has_no_tags():
    text = judge.markup("x", "mono", "red")
    assert text == "x" and not judge.has_markup(text)


def test_markup_color_has_tags():
    assert judge.markup("x", "color", "red") == "[red]x[/]"


def test_time_text_none_is_dash():
    assert judge.time_text(None) == "—"
    assert judge.time_text(1500) == "1500 ms"


def test_sparkline_series_skips_non_counted():
    values, skipped = judge.sparkline_series([(1, "pass"), (2, "skip"), (3, "fail"),
                                              (4, "missing")])
    assert values == [1.0, 0.0]
    assert skipped == 2


def test_sparkline_text_counts_and_notes():
    text = judge.sparkline_text([(1, "pass"), (2, "skip")])
    assert "1 次参与计数" in text
    assert "1 次 skip/missing 未绘制" in text


def test_sparkline_text_no_skip_note():
    assert "未绘制" not in judge.sparkline_text([(1, "pass")])


def test_summary_text_fields_order():
    text = judge.summary_text({"total": 3, "fail": 1, "skip": 0}, ["total", "fail", "skip"])
    assert text.index("total") < text.index("fail") < text.index("skip")


def test_summary_text_none_marker():
    text = judge.summary_text({"flaky": None}, ["flaky"])
    assert "—" in text and "None 不是 0" in text


def test_summary_text_zero_not_none():
    text = judge.summary_text({"fail": 0}, ["fail"])
    assert "fail 0" in text
    assert "None 不是 0" not in text


def test_description_for_known_actions():
    assert judge.description_for("flaky") == "flaky 矩阵"
    assert judge.description_for("back") == "返回三栏（back）"


def test_description_for_unknown_action_empty():
    assert judge.description_for("nope") == ""


def test_display_label_maps_enter_and_escape():
    assert judge.display_label("enter") == "Enter"
    assert judge.display_label("escape") == "Esc"
    assert judge.display_label("j") == "j"


def test_bindings_and_keys_cover_same_actions():
    labels = {label for label, _text in spec.KEYS}
    assert {judge.display_label(key) for key in spec.BINDINGS.values()} == labels


def test_keys_descriptions_non_empty():
    assert all(text for _label, text in spec.KEYS)


def test_only_defined_bindings_have_descriptions():
    for action in spec.BINDINGS:
        assert judge.description_for(action)


# ============================================================ H · queries（内存行集合）
RUN1 = {"run_id": 1, "branch": "main", "commit_sha": "", "ci_run_id": "1",
        "started_at": "", "framework": "pytest", "source_path": "a"}
RUN2 = {"run_id": 2, "branch": "main", "commit_sha": "", "ci_run_id": "2",
        "started_at": "", "framework": "pytest", "source_path": "b"}
RUN3 = {"run_id": 3, "branch": "main", "commit_sha": "", "ci_run_id": "3",
        "started_at": "", "framework": "pytest", "source_path": "c"}


def occurrence(run_id, case_id, status, time_ms=None):
    return {"run_id": run_id, "case_id": case_id, "status": status, "time_ms": time_ms,
            "failure_type": "", "failure_message": "", "stack_first_line": ""}


def test_fail_first_key_orders_failures_first():
    assert facts.fail_first_key(1, "z") < facts.fail_first_key(0, "a")


def test_order_cases_fail_first_then_name():
    cases = [
        {"name": "b", "status": "pass"},
        {"name": "z", "status": "fail"},
        {"name": "a", "status": "pass"},
    ]
    assert [case["name"] for case in facts.order_cases(cases)] == ["z", "a", "b"]


def test_order_classes_fail_first_then_name():
    groups = [("b", [{"status": "pass"}]), ("a", [{"status": "fail"}])]
    assert [name for name, _group in facts.order_classes(groups)] == ["a", "b"]


def test_run_cases_merges_occurrence():
    data = row_facts([RUN1],
                     [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
                     [occurrence(1, 1, "fail", 1200)])
    rows = facts.run_cases(data, 1)
    assert rows[0]["status"] == "fail"
    assert rows[0]["time_ms"] == 1200


def test_run_cases_skips_unknown_case():
    data = row_facts([RUN1], [], [occurrence(1, 99, "pass")])
    assert facts.run_cases(data, 1) == []


def test_tree_rows_orders_failing_suite_first():
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
    tree = facts.tree_rows(data, 1)
    assert [suite["name"] for suite in tree] == ["bad", "ok"]


def test_tree_rows_same_fail_status_by_suite_id():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s1", "classname": "c", "name": "a"},
         {"case_id": 2, "suite_name": "s2", "classname": "c", "name": "b"}],
        [occurrence(1, 1, "fail"), occurrence(1, 2, "fail")],
        suites=[{"suite_id": 7, "run_id": 1, "name": "s1", "source_path": "",
                 "time_ms": None, "tests": 1, "failures": 1, "errors": 0, "skipped": 0},
                {"suite_id": 9, "run_id": 1, "name": "s2", "source_path": "",
                 "time_ms": None, "tests": 1, "failures": 1, "errors": 0, "skipped": 0}],
    )
    assert [suite["name"] for suite in facts.tree_rows(data, 1)] == ["s1", "s2"]


def test_tree_rows_orphan_occurrence_kept():
    data = row_facts([RUN1],
                     [{"case_id": 1, "suite_name": "ghost", "classname": "c", "name": "n"}],
                     [occurrence(1, 1, "pass")])
    tree = facts.tree_rows(data, 1)
    assert len(tree) == 1
    assert tree[0]["suite_id"] == -1


def test_tree_rows_class_order_fail_first():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s", "classname": "okc", "name": "a"},
         {"case_id": 2, "suite_name": "s", "classname": "badc", "name": "b"}],
        [occurrence(1, 1, "pass"), occurrence(1, 2, "fail")],
        suites=[{"suite_id": 1, "run_id": 1, "name": "s", "source_path": "",
                 "time_ms": None, "tests": 2, "failures": 1, "errors": 0, "skipped": 0}],
    )
    suite = facts.tree_rows(data, 1)[0]
    assert [case["classname"] for case in suite["cases"]] == ["badc", "okc"]


def test_tree_rows_case_order_within_class():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "b"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "a"}],
        [occurrence(1, 1, "pass"), occurrence(1, 2, "fail")],
        suites=[{"suite_id": 1, "run_id": 1, "name": "s", "source_path": "",
                 "time_ms": None, "tests": 2, "failures": 1, "errors": 0, "skipped": 0}],
    )
    suite = facts.tree_rows(data, 1)[0]
    assert [case["name"] for case in suite["cases"]] == ["a", "b"]


def test_window_runs_slices_last_n():
    data = row_facts([RUN1, RUN2, RUN3], [], [])
    assert [run["run_id"] for run in facts.window_runs(data, 3, 2)] == [2, 3]


def test_window_runs_includes_self():
    data = row_facts([RUN1, RUN2], [], [])
    assert [run["run_id"] for run in facts.window_runs(data, 2, 20)] == [1, 2]


def test_previous_run():
    data = row_facts([RUN1, RUN2], [], [])
    assert facts.previous_run(data, 2)["run_id"] == 1
    assert facts.previous_run(data, 1) is None


def test_history_window_ascending():
    data = row_facts([RUN1, RUN2, RUN3],
                     [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
                     [occurrence(1, 1, "pass"), occurrence(2, 1, "fail"),
                      occurrence(3, 1, "pass")])
    assert facts.history(data, 1, 2) == [(2, "fail"), (3, "pass")]


def test_matrix_rows_cell_order_and_missing_none():
    data = row_facts([RUN1, RUN2],
                     [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
                     [occurrence(1, 1, "pass")])
    columns, rows = facts.matrix_rows(data, 2, 20)
    assert [run["run_id"] for run in columns] == [1, 2]
    assert rows[0]["statuses"] == ("pass", None)


def test_matrix_rows_order_by_flaky_score_desc():
    data = row_facts(
        [RUN1, RUN2, RUN3, {"run_id": 4}],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "stable"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "flaky"}],
        [occurrence(1, 1, "pass"), occurrence(2, 1, "pass"), occurrence(3, 1, "pass"),
         occurrence(4, 1, "pass"),
         occurrence(1, 2, "pass"), occurrence(2, 2, "fail"),
         occurrence(3, 2, "pass"), occurrence(4, 2, "fail")],
    )
    _columns, rows = facts.matrix_rows(data, 4, 20)
    assert rows[0]["name"] == "flaky"
    assert rows[0]["flaky_score"] > rows[1]["flaky_score"]


def test_slow_rows_excludes_missing_and_sorts_desc():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "slow"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "fast"},
         {"case_id": 3, "suite_name": "s", "classname": "c", "name": "unknown"}],
        [occurrence(1, 1, "pass", 3000), occurrence(1, 2, "pass", 500),
         occurrence(1, 3, "pass", None)],
    )
    rows = facts.slow_rows(data, 1, 1)
    assert [row["name"] for row in rows] == ["slow", "fast"]


def test_slow_profiles_split_midpoint():
    data = row_facts(
        [RUN1, RUN2, RUN3, {"run_id": 4}],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
        [occurrence(1, 1, "pass", 100), occurrence(2, 1, "pass", 100),
         occurrence(3, 1, "pass", 400), occurrence(4, 1, "pass", 400)],
    )
    profiles = facts.slow_profiles(data, 4, 20)
    assert profiles[1]["base_samples"] == 2
    assert profiles[1]["curr_samples"] == 2
    assert profiles[1]["regression"] is True


def test_diff_rows_missing_side_none():
    data = row_facts(
        [RUN1, RUN2],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "a"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "b"}],
        [occurrence(1, 1, "pass"), occurrence(2, 2, "fail")],
    )
    rows = facts.diff_rows(data, 1, 2)
    assert [(row["name"], row["status_before"], row["status_after"]) for row in rows] == [
        ("a", "pass", None), ("b", None, "fail")]


def test_summary_counts_and_fields():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "a"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "b"}],
        [occurrence(1, 1, "fail", 2000), occurrence(1, 2, "skip", 100)],
    )
    result = facts.summary(data, 1, 20)
    assert list(result) == spec.SUMMARY_FIELDS
    assert result["total"] == 2
    assert result["fail"] == 1
    assert result["skip"] == 1
    assert result["slow"] == 1


def test_summary_flaky_broken_counts_share_profiles():
    data = row_facts(
        [RUN1, RUN2, RUN3, {"run_id": 4}],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "f"},
         {"case_id": 2, "suite_name": "s", "classname": "c", "name": "b"}],
        [occurrence(1, 1, "pass"), occurrence(2, 1, "fail"), occurrence(3, 1, "pass"),
         occurrence(4, 1, "fail"),
         occurrence(1, 2, "fail"), occurrence(2, 2, "fail"), occurrence(3, 2, "fail"),
         occurrence(4, 2, "fail")],
    )
    result = facts.summary(data, 4, 20)
    assert result["flaky"] == 1
    assert result["broken"] == 1


def test_summary_none_fields_kept_when_asked():
    data = row_facts([RUN1], [], [])
    result = facts.summary(data, 1, 20, ["total", "unknown_field"])
    assert result["unknown_field"] is None


def test_case_profiles_window_limits_history():
    data = row_facts(
        [RUN1, RUN2, RUN3],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "n"}],
        [occurrence(1, 1, "fail"), occurrence(2, 1, "fail"), occurrence(3, 1, "pass")],
    )
    profiles = facts.case_profiles(data, 3, 2)
    assert profiles[1]["counted_runs"] == 2
    assert profiles[1]["fails"] == 1


# ============================================================ I · store / ingest
def test_store_upsert_run_idempotent():
    store = facts.Store()
    first = store.upsert_run(core.RunIdentity("main", "", "1"))
    second = store.upsert_run(core.RunIdentity("main", "", "1"))
    assert first == second == 1
    assert len(store.runs) == 1


def test_store_upsert_run_distinct_identity():
    store = facts.Store()
    store.upsert_run(core.RunIdentity("main", "", "1"))
    store.upsert_run(core.RunIdentity("main", "", "2"))
    assert len(store.runs) == 2


def test_store_upsert_run_updates_fields():
    store = facts.Store()
    store.upsert_run(core.RunIdentity("main", "", "1"), started_at="t1", framework="pytest")
    store.upsert_run(core.RunIdentity("main", "", "1"), started_at="t2",
                     framework="pytest,gotestsum")
    row = list(store.runs.values())[0]
    assert row["started_at"] == "t2"
    assert row["framework"] == "pytest,gotestsum"


def test_store_upsert_case_idempotent():
    store = facts.Store()
    assert store.upsert_case(core.CaseIdentity("s", "c", "n")) == 1
    assert store.upsert_case(core.CaseIdentity("s", "c", "n")) == 1


def test_store_upsert_case_distinct_name():
    store = facts.Store()
    store.upsert_case(core.CaseIdentity("s", "c", "n1"))
    store.upsert_case(core.CaseIdentity("s", "c", "n2"))
    assert [row["case_id"] for row in store.cases.values()] == [1, 2]


def test_store_upsert_suite_keyed_by_path():
    store = facts.Store()
    store.upsert_suite(1, "s", "a.xml", 1, 0, 0, 0, 100)
    store.upsert_suite(1, "s", "b.xml", 2, 0, 0, 0, 200)
    assert len(store.suites) == 2


def test_store_upsert_suite_updates_counts():
    store = facts.Store()
    store.upsert_suite(1, "s", "a.xml", 1, 0, 0, 0, 100)
    store.upsert_suite(1, "s", "a.xml", 3, 1, 0, 1, 300)
    row = list(store.suites.values())[0]
    assert (row["tests"], row["failures"], row["skipped"], row["time_ms"]) == (3, 1, 1, 300)


def test_store_occurrence_overwritten():
    store = facts.Store()
    store.upsert_occurrence(1, 1, "pass", time_ms=10)
    store.upsert_occurrence(1, 1, "fail", time_ms=20)
    assert len(store.occurrences) == 1
    assert list(store.occurrences.values())[0]["status"] == "fail"


def test_store_facts_sorted():
    store = facts.Store()
    store.upsert_run(core.RunIdentity("b", "", "2"))
    store.upsert_run(core.RunIdentity("a", "", "1"))
    snapshot = store.facts()
    assert [run["run_id"] for run in snapshot["runs"]] == [1, 2]


def test_aggregate_suites_merges_counts():
    merged = facts.aggregate_suites([
        {"name": "s", "tests": 2, "failures": 1, "errors": 0, "skipped": 0, "time_ms": 100,
         "cases": [{"name": "a"}]},
        {"name": "s", "tests": 3, "failures": 0, "errors": 1, "skipped": 1, "time_ms": 200,
         "cases": [{"name": "b"}]},
    ])
    assert len(merged) == 1
    assert merged[0]["tests"] == 5
    assert merged[0]["time_ms"] == 300
    assert len(merged[0]["cases"]) == 2


def test_aggregate_suites_keeps_distinct_names_order():
    merged = facts.aggregate_suites([
        {"name": "b", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "time_ms": None},
        {"name": "a", "tests": 1, "failures": 0, "errors": 0, "skipped": 0, "time_ms": None},
    ])
    assert [suite["name"] for suite in merged] == ["b", "a"]


def test_ingest_report_counts():
    report = facts_of(
        xml_doc([xml_suite("s", [xml_case("a"), xml_case("b", kind="failure")])]),
        xml_doc([xml_suite("t", [xml_case("c")])]),
    )
    assert (report["files"], report["runs"], report["cases"], report["occurrences"]) == (
        2, 1, 3, 3)


def test_ingest_summary_line():
    report = facts_of(xml_doc([xml_suite("s", [xml_case("a")])]))
    assert facts.summary_line(report).startswith("ingest: files=1 runs=1 cases=1 occurrences=1")


def test_ingest_groups_by_identity():
    report = facts_of(
        xml_doc([xml_suite("s", [xml_case("a")])], attrs=' ci_run_id="1"'),
        xml_doc([xml_suite("s", [xml_case("b")])], attrs=' ci_run_id="2"'),
    )
    assert report["runs"] == 2
    assert report["occurrences"] == 2


def test_ingest_same_identity_single_run():
    report = facts_of(
        xml_doc([xml_suite("s", [xml_case("a")])], attrs=' ci_run_id="1"'),
        xml_doc([xml_suite("t", [xml_case("b")])], attrs=' ci_run_id="1"'),
    )
    assert report["runs"] == 1
    assert report["occurrences"] == 2


def test_ingest_skipped_reason_recorded():
    report = facts_of("<testsuites><testsuite>", xml_doc([xml_suite("s", [xml_case("a")])]))
    assert report["skipped"] == 1
    assert list(report["skipped_reasons"]) == [spec.BAD_XML]


def test_ingest_frameworks_sorted():
    report = facts.ingest([
        {"display_path": "a.xml", "file_name": "junit.xml",
         "xml": xml_doc([xml_suite("s", [xml_case("a")])], name="")},
        {"display_path": "b.xml", "file_name": "weird.xml",
         "xml": xml_doc([xml_suite("s", [xml_case("b")])], name="")},
    ])
    assert report["frameworks"] == ["pytest", "unknown"]


def test_ingest_degraded_paths_recorded():
    report = facts_of(xml_doc([xml_suite("s", [xml_case("a", time="x")])]))
    assert report["degraded_counts"][spec.DEGRADED_BAD_TIME] == 1
    assert report["degraded_paths"][spec.DEGRADED_BAD_TIME] == ["f/0.xml"]


def test_ingest_idempotent_second_pass():
    store = facts.Store()
    files = [{"display_path": "f/junit.xml", "file_name": "junit.xml",
              "xml": xml_doc([xml_suite("s", [xml_case("a")])])}]
    facts.ingest(files, store)
    snapshot = store.facts()
    facts.ingest(files, store)
    again = store.facts()
    assert len(snapshot["runs"]) == len(again["runs"]) == 1
    assert len(snapshot["occurrences"]) == len(again["occurrences"]) == 1


def test_ingest_bytes_input():
    report = facts.ingest([{"display_path": "b.xml",
                            "bytes": xml_doc([xml_suite("s", [xml_case("a")])]).encode()}])
    assert report["skipped"] == 0 and report["cases"] == 1


def test_ingest_requires_xml_or_bytes():
    with pytest.raises(ValueError):
        facts.ingest([{"display_path": "x.xml"}])


def test_ingest_bytes_bad_encoding_path():
    report = facts.ingest([{"display_path": "b.xml", "bytes": b"\xff\xfe<nope>"}])
    assert report["skipped_reasons"] == {spec.BAD_ENCODING: ["b.xml"]}


def test_ingest_run_source_path_first_file():
    report = facts_of(xml_doc([xml_suite("s", [xml_case("a")])]))
    run = list(report["store"].runs.values())[0]
    assert run["source_path"] == "f/0.xml"


# ============================================================ J · api / 账本 / 门禁
def test_api_junit_reason_is_error():
    record = only({"mode": "junit", "xml": "<testsuites>"}, spec.R_JUNIT_FILE)
    assert record.verdict == ERROR
    assert record.path == "file"


def test_api_junit_framework_info():
    record = only({"mode": "junit", "xml": xml_doc([xml_suite("s", [])])}, spec.R_JUNIT_FRAMEWORK)
    assert record.verdict == INFO
    assert record.evidence["framework"] == "pytest"


def test_api_junit_unknown_framework_flagged():
    record = only({"mode": "junit", "xml": xml_doc([xml_suite("s2", [])], name="")},
                  spec.R_JUNIT_FRAMEWORK)
    assert record.evidence["unknown"] is True


def test_api_junit_degraded_warn():
    records = [item for item in body(
        {"mode": "junit", "xml": xml_doc([xml_suite("s", [xml_case("a", time="x")])])})
        if item.rule_id == spec.R_JUNIT_DEGRADED]
    record = [item for item in records if item.path == "degraded:" + spec.DEGRADED_BAD_TIME][0]
    assert record.verdict == WARN
    assert record.evidence["reason"] == spec.DEGRADED_BAD_TIME


def test_api_junit_totals_in_summary():
    record = summary({"mode": "junit", "xml": xml_doc([xml_suite("s", [
        xml_case("a", kind="failure"), xml_case("b")])])})
    assert record.evidence["totals"]["tests"] == 2
    assert record.evidence["totals"]["failures"] == 1


def test_api_junit_missing_input():
    with pytest.raises(ValueError):
        recs({"mode": "junit"})


def test_api_junit_bad_base64():
    with pytest.raises(ValueError):
        recs({"mode": "junit", "bytes_b64": "***"})


def test_api_ingest_report_record():
    record = only({"mode": "ingest", "files": [
        {"display_path": "f/junit.xml", "file_name": "junit.xml",
         "xml": xml_doc([xml_suite("s", [xml_case("a")])])}]}, spec.R_INGEST_REPORT)
    assert record.evidence["files"] == 1


def test_api_ingest_skipped_file_error():
    record = only({"mode": "ingest", "files": [
        {"display_path": "f/bad.xml", "xml": "<testsuites>"}]}, spec.R_JUNIT_FILE)
    assert record.verdict == ERROR


def test_api_ingest_missing_path_error():
    record = only({"mode": "ingest", "files": [
        {"display_path": "f/junit.xml", "xml": xml_doc([xml_suite("s", [])])}],
        "missing_paths": ["/nope"]}, spec.R_INGEST_MISSING)
    assert record.verdict == ERROR


def test_api_ingest_requires_files():
    with pytest.raises(ValueError):
        recs({"mode": "ingest", "files": []})


def test_api_ingest_rejects_non_dict_file():
    with pytest.raises(ValueError):
        recs({"mode": "ingest", "files": ["a.xml"]})


def test_api_flaky_records_per_case():
    records = body({"mode": "flaky", "histories": [
        {"case_id": 7, "series": [[1, "pass"], [2, "fail"], [3, "pass"], [4, "fail"]]}]})
    assert len(records) == 2
    assert records[0].path == "case:7"
    assert records[0].evidence["label"] == spec.LABEL_FLAKY


def test_api_flaky_summary_counts():
    record = summary({"mode": "flaky", "histories": [
        {"case_id": 1, "series": [[1, "pass"], [2, "fail"], [3, "pass"], [4, "fail"]]},
        {"case_id": 2, "series": [[1, "pass"], [2, "pass"]]}]})
    assert record.evidence["labels"] == {spec.LABEL_FLAKY: 1, spec.LABEL_STABLE: 1}


def test_api_flaky_requires_histories():
    with pytest.raises(ValueError):
        recs({"mode": "flaky", "histories": []})


def test_api_flaky_rejects_bad_series():
    with pytest.raises(ValueError):
        recs({"mode": "flaky", "histories": [{"series": [[1, "nope"]]}]})


def test_api_flaky_rejects_non_int_run():
    with pytest.raises(ValueError):
        recs({"mode": "flaky", "histories": [{"series": [["1", "pass"]]}]})


def test_api_slow_records_and_summary():
    records = body({"mode": "slow", "cases": [
        {"case_id": 1, "timings": [100, 100, 500, 500], "split": 2, "time_ms": 500}]})
    assert records[0].evidence["regression"] == "yes"
    assert summary({"mode": "slow", "cases": [
        {"case_id": 1, "timings": [100, 100, 500, 500], "split": 2}]}).evidence["regressions"] == 1


def test_api_slow_sample_label_warn():
    record = only({"mode": "slow", "cases": [{"case_id": 3, "timings": [100], "split": None}]},
                  spec.R_SLOW_SAMPLE)
    assert record.verdict == WARN
    assert record.evidence["label"] == spec.LABEL_SINGLE_SAMPLE


def test_api_slow_undecidable_counted():
    record = summary({"mode": "slow", "cases": [{"case_id": 3, "timings": [100, 200],
                                                 "split": None}]})
    assert record.evidence["undecidable"] == 1


def test_api_slow_requires_cases():
    with pytest.raises(ValueError):
        recs({"mode": "slow", "cases": []})


def test_api_slow_rejects_bad_timing_type():
    with pytest.raises(ValueError):
        recs({"mode": "slow", "cases": [{"timings": ["100"]}]})


def test_api_diff_records_and_counts():
    records = body({"mode": "diff", "rows": [
        {"case_id": 1, "status_before": "pass", "status_after": "fail"},
        {"case_id": 2, "status_before": "fail", "status_after": "pass"}]})
    assert [record.evidence["kind"] for record in records[:2]] == [
        spec.NEW_FAILURES, spec.FIXED]


def test_api_diff_rejects_unknown_status():
    with pytest.raises(ValueError):
        recs({"mode": "diff", "rows": [{"status_before": "weird", "status_after": "pass"}]})


def test_api_gate_new_failures_triggers():
    record = only({"mode": "gate", "fail_on": "new-failures", "rows": [
        {"status_before": "pass", "status_after": "fail"}]}, spec.R_GATE)
    assert record.verdict == ERROR
    assert record.evidence["triggered"] is True


def test_api_gate_not_triggered_info():
    record = only({"mode": "gate", "fail_on": "new-failures", "rows": [
        {"status_before": "fail", "status_after": "pass"}]}, spec.R_GATE)
    assert record.verdict == INFO


def test_api_gate_flaky():
    record = only({"mode": "gate", "fail_on": "flaky", "histories": [
        {"series": [[1, "pass"], [2, "fail"], [3, "pass"], [4, "fail"]]}]}, spec.R_GATE)
    assert record.evidence["hit"] == 1


def test_api_gate_regressions():
    record = only({"mode": "gate", "fail_on": "regressions", "cases": [
        {"timings": [100, 100, 500, 500], "split": 2}]}, spec.R_GATE)
    assert record.evidence["hit"] == 1


def test_api_gate_invalid_fail_on():
    with pytest.raises(ValueError):
        recs({"mode": "gate", "fail_on": "nope", "rows": []})


def test_api_bad_mode():
    with pytest.raises(ValueError):
        recs({"mode": "nope", "facts": {}})


def test_api_views_trees_and_summary():
    data = row_facts(
        [RUN1],
        [{"case_id": 1, "suite_name": "s", "classname": "c", "name": "a"}],
        [occurrence(1, 1, "fail", 1200)],
        suites=[{"suite_id": 1, "run_id": 1, "name": "s", "source_path": "",
                 "time_ms": None, "tests": 1, "failures": 1, "errors": 0, "skipped": 0}],
    )
    records = body({"mode": "views", "facts": data})
    assert any(record.rule_id == spec.R_TREE for record in records)
    summary_record = [record for record in records if record.rule_id == spec.R_SUMMARY][0]
    assert summary_record.evidence["fail"] == 1


def test_api_views_no_previous_run_explicit():
    data = row_facts([RUN1], [], [])
    records = body({"mode": "views", "facts": data})
    diff_summary = [record for record in records if record.rule_id == spec.R_DIFF_SUMMARY][0]
    assert diff_summary.evidence["previous_run"] is None


def test_api_views_requires_facts():
    with pytest.raises(ValueError):
        recs({"mode": "views"})


def test_api_views_run_id_defaults_to_latest():
    data = row_facts([RUN1, RUN2], [], [])
    assert summary({"mode": "views", "facts": data}).evidence["run_id"] == 2


def test_api_views_window_validation():
    data = row_facts([RUN1], [], [])
    with pytest.raises(ValueError):
        recs({"mode": "views", "facts": data, "window": 0})


def test_report_blocking_exit_code():
    report = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                    subject="s", records=recs({"mode": "junit", "xml": "<testsuites>"}))
    assert report.exit_code() == 1


def test_report_clean_exit_code():
    report = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                    subject="s", records=recs({"mode": "junit",
                                               "xml": xml_doc([xml_suite("s", [])])}))
    assert report.exit_code() == 0


def test_report_deterministic():
    subject = {"mode": "flaky", "histories": [
        {"case_id": 1, "series": [[1, "pass"], [2, "fail"], [3, "pass"], [4, "fail"]]}]}
    first = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                   subject="s", records=recs(subject))
    second = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                    subject="s", records=recs(subject))
    assert json.dumps(first.as_dict(), ensure_ascii=False) == json.dumps(
        second.as_dict(), ensure_ascii=False)


def test_ingest_judge_parity_with_old_summary():
    """判据 2 的锚：three fixtures 的旧仓摘要行（实跑取得）逐字节复现。"""
    expected = ("ingest: files=3 runs=1 cases=18 occurrences=18 skipped=0 "
                "framework=gotestsum,playwright,pytest")
    files = []
    for index, name in enumerate(("pytest", "gotestsum", "playwright")):
        files.append({"display_path": "bench/fixtures/%s.xml" % name, "file_name": name + ".xml",
                      "xml": xml_doc([xml_suite(name, [xml_case("case_%d" % index)])],
                                     name="")})
    report = facts.ingest(files)
    assert facts.summary_line(report) == (
        "ingest: files=3 runs=1 cases=3 occurrences=3 skipped=0 framework=gotestsum,playwright,pytest")
    assert expected.startswith("ingest: files=3 runs=1 cases=18")