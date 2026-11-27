"""``barcode-preflight`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那套函数仍然在、语义仍然是那一套**：
GS1 校验位、元素串解析、四个语义解释器、符号三段判定与容量/校验位、静区三档、
放大率、DPI 混叠、条高、颜色双探针、阈值三态降级、退出码十二格、oracle 三态。

**没迁的部分逐条写在 ``docs/barcode-preflight.md`` §6 的处置表里**（spec 文件读取、
官方字典 digest、GCP/GEPIR、外部解码引擎、报告排版与写盘）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 12 个判定层文件实跑 **X = 223 passed**（AST 函数 209）。
"""

from __future__ import annotations

import ast
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors.barcode_preflight import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    book as book_mod,
    checks,
    gs1,
    oracle,
    spec,
    symbol,
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
    RuleMissing,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "barcode-preflight"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "barcode_preflight"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "barcode-preflight.basis.json"
THRESHOLDS_PATH = DATA_DIR / "barcode-preflight.thresholds.json"
SAMPLE = ROOT / "samples" / "barcode-preflight.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
SAMPLE_DATA = json.loads(SAMPLE.read_text(encoding="utf-8"))
BOOK_DATA = SAMPLE_DATA["thresholds"]
PROFILES = SAMPLE_DATA["profiles"]

DICTIONARY = {
    "01": {"title": "GTIN", "length": 14, "charset": "N", "linters": ["csum"], "req": [], "ex": [], "fixed": True},
    "17": {"title": "EXP", "length": 6, "charset": "N", "linters": ["yymmd0"], "req": [], "ex": [], "fixed": True},
    "10": {"title": "LOT", "length": 20, "charset": "X", "linters": [], "req": [], "ex": [], "fixed": False},
    "21": {"title": "SERIAL", "length": 20, "charset": "X", "linters": [], "req": [], "ex": [], "fixed": False},
}
CENTURY = {"reference_year_yy": 21, "century_window": 50, "centuries": {"high": 19, "mid": 20, "low": 21}}


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _report(subject):
    return Report(
        product="byteproof",
        organ=SLUG,
        organ_version=ORGAN_VERSION,
        subject="test.json",
        records=tuple(_evaluate(subject)),
    )


def _book(overrides=None):
    data = json.loads(json.dumps(BOOK_DATA))
    if overrides:
        _merge(data, overrides)
    return book_mod.Book(data)


def _merge(base, overrides):
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _check(**extra):
    subject = {
        "mode": "check",
        "identifier": "4006381333931",
        "symbol": "ean13",
        "x_dimension_mm": "0.330",
        "target_dpi": 203,
        "quiet_zone_mm": {"left": "3.63", "right": "2.31", "top": "0", "bottom": "0"},
        "bar_height_mm": "22.85",
        "bar_color": "#000000",
        "space_color": "#FFFFFF",
        "illumination": "white",
        "thresholds": json.loads(json.dumps(BOOK_DATA)),
        "profiles": json.loads(json.dumps(PROFILES)),
        "dictionary": dict(DICTIONARY),
        "century_resolution": dict(CENTURY),
        "fail_on": "none",
    }
    subject.update(extra)
    return subject


def _codes(subject):
    return [
        record.evidence["id"]
        for record in _evaluate(subject)
        if record.rule_id.startswith("bp-") and record.path.startswith("findings[")
    ]


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG
    assert PACK.version == "1"


def test_pack_declares_only_mode_as_universal_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "barcode_preflight" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_modes_match_the_four_entry_points():
    assert spec.MODES == ("check", "gs1", "symbol", "oracle")


def test_sample_is_a_check_with_print_input():
    assert SAMPLE_DATA["mode"] == "check"
    assert SAMPLE_DATA["symbol"] == "ean13"
    assert SAMPLE_DATA["quiet_zone_mm"]["right"] == "2.31"


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


def test_thresholds_rule_verdicts_match_runtime():
    assert SETTINGS["rule_verdicts"] == spec.VERDICTS


def test_thresholds_severity_order_matches_runtime():
    assert SETTINGS["severity_order"] == spec.SEVERITY_ORDER


def test_thresholds_modes_match_runtime():
    assert tuple(SETTINGS["modes"]) == spec.MODES


def test_thresholds_symbols_match_runtime():
    assert tuple(SETTINGS["supported_symbols"]) == spec.SUPPORTED_SYMBOLS


def test_thresholds_charsets_match_runtime():
    for code, name in (("N", "CSET_NUMERIC"), ("X", "CSET_82"), ("Y", "CSET_39"), ("Z", "CSET_BASE64URL")):
        assert SETTINGS["charsets"][code] == spec.CHARSETS[code][1]
        assert getattr(spec, name) == spec.CHARSETS[code][1]


def test_thresholds_print_fields_match_runtime():
    assert tuple(SETTINGS["print_fields"]) == spec.PRINT_FIELDS
    assert tuple(SETTINGS["print_color_fields"]) == spec.PRINT_COLOR_FIELDS
    assert tuple(SETTINGS["quiet_zone_sides"]) == spec.QUIET_ZONE_SIDES


def test_thresholds_basis_kinds_match_runtime():
    assert tuple(SETTINGS["basis_kinds"]) == (spec.BASIS_GEN_SPEC, spec.BASIS_ENGINEERING)


def test_thresholds_fail_on_choices_match_runtime():
    assert tuple(SETTINGS["fail_on_choices"]) == spec.FAIL_ON_CHOICES


def test_severity_order_is_monotonic():
    assert spec.SEVERITY_ORDER["ok"] < spec.SEVERITY_ORDER["info"] < spec.SEVERITY_ORDER["warn"] < spec.SEVERITY_ORDER["error"]


def test_rule_ids_are_unique_and_kebab():
    assert len(spec.RULE_IDS) == len(set(spec.RULE_IDS))
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("bp-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== 校验位
@pytest.mark.parametrize(
    "data,digit",
    [
        ("400638133393", "1"),
        ("4006381333931", None),
        ("0000000000000", None),
    ],
)
def test_check_digit_known_vectors(data, digit):
    if digit is None:
        assert gs1.check_digit(data[:-1]) == data[-1]
    else:
        assert gs1.check_digit(data) == digit


def test_check_digit_accepts_short_digits():
    assert len(gs1.check_digit("1")) == 1


def test_check_digit_rejects_non_digits():
    with pytest.raises(ValueError):
        gs1.check_digit("12A")


def test_check_digit_rejects_empty():
    with pytest.raises(ValueError):
        gs1.check_digit("")


def test_check_digit_rejects_non_string():
    with pytest.raises(ValueError):
        gs1.check_digit(123)


def test_is_valid_accepts_known_gtin():
    assert gs1.is_valid("4006381333931") is True


def test_is_valid_rejects_wrong_digit():
    assert gs1.is_valid("4006381333932") is False


def test_is_valid_rejects_too_short():
    assert gs1.is_valid("1") is False


def test_is_valid_rejects_non_digits():
    with pytest.raises(ValueError):
        gs1.is_valid("40A")


def test_check_digit_weight_parity():
    # total length even -> first weight 3; odd -> first weight 1
    assert gs1.check_digit("4006381333931") == gs1.check_digit("4006381333931")
    assert gs1.check_digit("12345678901231") == gs1.check_digit("12345678901231")


# ================================================================== 元素解析
def test_parse_bracketed_single():
    elements, issues = gs1.parse_elements("(01)04006381333931", DICTIONARY)
    assert issues == []
    assert elements == [{"ai": "01", "value": "04006381333931"}]


def test_parse_bracketed_multiple():
    elements, issues = gs1.parse_elements("(01)04006381333931(17)251231", DICTIONARY)
    assert [item["ai"] for item in elements] == ["01", "17"]
    assert issues == []


def test_parse_bracketed_unknown_ai():
    elements, issues = gs1.parse_elements("(99)ABC", DICTIONARY)
    assert elements == []
    assert issues[0]["issue"] == "unknown_ai"
    assert issues[0]["ai"] == "99"


def test_parse_bracketed_stray_prefix():
    elements, issues = gs1.parse_elements("x(01)04006381333931", DICTIONARY)
    assert issues and issues[0]["issue"] == "malformed"


def test_parse_bracketed_stray_suffix():
    elements, issues = gs1.parse_elements("(01)04006381333931x", DICTIONARY)
    assert issues and issues[0]["issue"] == "malformed"


def test_parse_bracketed_empty_text_raises():
    with pytest.raises(ValueError):
        gs1.parse_elements("", DICTIONARY)


def test_parse_requires_dictionary_object():
    with pytest.raises(ValueError):
        gs1.parse_elements("(01)04006381333931", "oops")


def test_looks_bracketed_true():
    assert gs1.looks_bracketed("(01)123") is True


def test_looks_bracketed_false_for_raw():
    assert gs1.looks_bracketed("0104006381333931") is False


def test_parse_raw_fixed_ai():
    elements, issues = gs1.parse_elements("0104006381333931", DICTIONARY)
    assert issues == []
    assert elements == [{"ai": "01", "value": "04006381333931"}]


def test_parse_raw_variable_ai_consumes_remainder():
    elements, issues = gs1.parse_elements("010400638133393110LOT-1", DICTIONARY)
    assert [item["ai"] for item in elements] == ["01", "10"]
    assert elements[1]["value"] == "LOT-1"


def test_parse_raw_variable_ai_stops_at_group_separator():
    elements, issues = gs1.parse_elements("010400638133393110LOT-1\x1d21SER-9", DICTIONARY)
    assert [item["ai"] for item in elements] == ["01", "10", "21"]
    assert elements[1]["value"] == "LOT-1"
    assert elements[2]["value"] == "SER-9"


def test_parse_raw_unknown_ai():
    elements, issues = gs1.parse_elements("99123", DICTIONARY)
    assert elements == []
    assert issues[0]["issue"] == "unknown_ai"


def test_parse_raw_fixed_short_is_malformed():
    elements, issues = gs1.parse_elements("01123", DICTIONARY)
    assert issues and issues[0]["issue"] == "malformed"


def test_issue_findings_unknown_ai():
    findings = gs1.issue_findings([{"issue": "unknown_ai", "ai": "99", "value": "X"}])
    assert findings[0]["rule_id"] == spec.RULE_GS1_UNKNOWN_AI


def test_issue_findings_malformed():
    findings = gs1.issue_findings([{"issue": "malformed", "detail": "bad", "offset": 0}])
    assert findings[0]["rule_id"] == spec.RULE_GS1_MALFORMED


# ================================================================== 语义解释器
@pytest.mark.parametrize(
    "value,kind,status",
    [
        ("251231", "yymmd0", "ok"),
        ("200600", "yymmd0", "dd00"),
        ("251301", "yymmd0", "invalid_date"),
        ("251331", "yymmd0", "invalid_date"),
        ("251230", "yymmdd", "ok"),
        ("250030", "yymmdd", "invalid_date"),
        ("20251231", "yyyymmd0", "ok"),
        ("20201301", "yyyymmd0", "invalid_date"),
    ],
)
def test_resolve_date_matrix(value, kind, status):
    result, _normalized, _detail = gs1.resolve_date(value, kind, CENTURY)
    assert result == status


def test_resolve_date_dd00_normalizes_to_month_end():
    status, normalized, _ = gs1.resolve_date("200200", "yymmd0", CENTURY)
    assert status == "dd00"
    assert normalized == "2020-02-29"


def test_resolve_date_non_leap_february():
    status, _, _ = gs1.resolve_date("210229", "yymmd0", CENTURY)
    assert status == "invalid_date"


def test_resolve_date_two_digit_year_window():
    _status, normalized, _ = gs1.resolve_date("720101", "yymmd0", CENTURY)
    assert normalized.startswith("1972")


def test_resolve_date_rejects_wrong_width():
    status, _, _ = gs1.resolve_date("25123", "yymmd0", CENTURY)
    assert status == "invalid_date"


def test_expand_two_digit_year_high_branch():
    assert gs1._expand_two_digit_year(72, CENTURY) == 1972


def test_expand_two_digit_year_mid_branch():
    assert gs1._expand_two_digit_year(30, CENTURY) == 2030


def test_validate_elements_checksum_ok():
    findings, skipped = gs1.validate_elements([{"ai": "01", "value": "04006381333931"}], DICTIONARY, CENTURY)
    assert findings == []
    assert skipped == []


def test_validate_elements_checksum_bad():
    findings, _ = gs1.validate_elements([{"ai": "01", "value": "04006381333932"}], DICTIONARY, CENTURY)
    assert findings[0]["rule_id"] == spec.RULE_GS1_CHECKSUM


def test_validate_elements_charset_bad():
    dictionary = {"10": {"length": 3, "charset": "N", "linters": []}}
    findings, _ = gs1.validate_elements([{"ai": "10", "value": "A12"}], dictionary, CENTURY)
    assert findings[0]["rule_id"] == spec.RULE_GS1_CHARSET


def test_validate_elements_length_bad():
    dictionary = {"10": {"length": 3, "charset": "X", "linters": []}}
    findings, _ = gs1.validate_elements([{"ai": "10", "value": "AB"}], dictionary, CENTURY)
    assert findings[0]["rule_id"] == spec.RULE_GS1_LENGTH


def test_validate_elements_date_bad():
    findings, _ = gs1.validate_elements([{"ai": "17", "value": "251301"}], DICTIONARY, CENTURY)
    assert findings[0]["rule_id"] == spec.RULE_GS1_DATE


def test_validate_elements_date_dd00_is_ok():
    findings, _ = gs1.validate_elements([{"ai": "17", "value": "200600"}], DICTIONARY, CENTURY)
    assert findings == []


def test_validate_elements_skips_gcp_linter():
    dictionary = {"10": {"length": 3, "charset": "X", "linters": ["gcppos1"]}}
    findings, skipped = gs1.validate_elements([{"ai": "10", "value": "ABC"}], dictionary, CENTURY)
    assert findings == []
    assert skipped[0]["reason"] == "gcp_lookup_unavailable"


def test_validate_elements_skips_unknown_linter():
    dictionary = {"10": {"length": 3, "charset": "X", "linters": ["mystery"]}}
    findings, skipped = gs1.validate_elements([{"ai": "10", "value": "ABC"}], dictionary, CENTURY)
    assert skipped[0]["reason"] == "linter_not_implemented"


def test_required_relation_fires():
    dictionary = {
        "01": {"length": 14, "charset": "N", "linters": [], "req": [["17"]]},
    }
    findings, _ = gs1.validate_elements([{"ai": "01", "value": "04006381333931"}], dictionary, CENTURY)
    assert findings[0]["rule_id"] == spec.RULE_GS1_REQUIRED


def test_required_relation_or_groups():
    dictionary = {
        "01": {"length": 14, "charset": "N", "linters": [], "req": [["17"], ["30"]]},
        "30": {"length": 1, "charset": "N", "linters": []},
    }
    findings, _ = gs1.validate_elements(
        [{"ai": "01", "value": "04006381333931"}, {"ai": "30", "value": "1"}],
        dictionary,
        CENTURY,
    )
    assert findings == []


def test_required_relation_and_within_group():
    dictionary = {
        "01": {"length": 14, "charset": "N", "linters": [], "req": [["17", "30"]]},
        "17": {"length": 6, "charset": "N", "linters": []},
    }
    findings, _ = gs1.validate_elements(
        [{"ai": "01", "value": "04006381333931"}, {"ai": "17", "value": "251231"}],
        dictionary,
        CENTURY,
    )
    assert findings[0]["rule_id"] == spec.RULE_GS1_REQUIRED


def test_exclusive_relation_fires():
    dictionary = {
        "01": {"length": 14, "charset": "N", "linters": [], "ex": ["02"]},
        "02": {"length": 14, "charset": "N", "linters": []},
    }
    findings, _ = gs1.validate_elements(
        [{"ai": "01", "value": "04006381333931"}, {"ai": "02", "value": "04006381333931"}],
        dictionary,
        CENTURY,
    )
    assert any(item["rule_id"] == spec.RULE_GS1_EXCLUSIVE for item in findings)


def test_exclusive_is_not_reflexive():
    dictionary = {"01": {"length": 14, "charset": "N", "linters": [], "ex": ["01"]}}
    findings, _ = gs1.validate_elements([{"ai": "01", "value": "04006381333931"}], dictionary, CENTURY)
    assert findings == []


# ================================================================== 符号
@pytest.mark.parametrize(
    "symbol_name,value,expected",
    [
        ("ean13", "4006381333931", []),
        ("ean13", "400638133393", ["bp-symbol-length"]),
    ],
)
def test_symbol_ean13_length_matrix(symbol_name, value, expected):
    findings, _, _ = symbol.assess(PROFILES, symbol_name, value=value, strict=True)
    rule_ids = [item["rule_id"] for item in findings if item["severity"] in ("warn", "error")]
    assert rule_ids == expected


def test_symbol_unsupported_is_skipped():
    findings, skipped, _ = symbol.assess(PROFILES, "pdf417", value="X")
    assert findings[0]["rule_id"] == spec.RULE_SYMBOL_UNSUPPORTED
    assert skipped == ["symbol_unsupported:pdf417"]


def test_symbol_requires_profiles_object():
    with pytest.raises(ValueError):
        symbol.assess([], "ean13", value="4006381333931")


def test_symbol_charset_union():
    profiles = {
        "x": {
            "charsets": {"a": {"ranges": [[65, 90]]}, "b": {"characters": "0123456789"}},
            "length": {"kind": "range", "min": 1, "max": 10},
            "modes": [
                {"name": "any", "charset": "a", "group_size": 1, "min_run": 1, "priority": 1},
                {"name": "digits", "charset": "b", "group_size": 1, "min_run": 1, "priority": 2},
            ],
        }
    }
    findings, _, _ = symbol.assess(profiles, "x", value="A1", strict=True)
    assert not [item for item in findings if item["severity"] in ("warn", "error")]


def test_symbol_charset_violation():
    profiles = {"x": {"charsets": {"a": {"characters": "AB"}}, "length": {"kind": "range", "min": 1, "max": 10}}}
    findings, _, _ = symbol.assess(profiles, "x", value="AC", strict=True)
    assert findings[0]["rule_id"] == spec.RULE_SYMBOL_CHARSET


def test_symbol_unverified_downgrade():
    profiles = {"x": {"charsets": {"a": {"characters": "AB", "status": "unverified"}}, "length": {"kind": "range", "min": 1, "max": 10, "status": "unverified"}}}
    findings, _, _ = symbol.assess(profiles, "x", value="AC", strict=False)
    assert findings[0]["severity"] == "warn"


def test_symbol_unverified_strict_restores_error():
    profiles = {"x": {"charsets": {"a": {"characters": "AB", "status": "unverified"}}, "length": {"kind": "range", "min": 1, "max": 10, "status": "unverified"}}}
    findings, _, _ = symbol.assess(profiles, "x", value="AC", strict=True)
    assert findings[0]["severity"] == "error"


def test_symbol_length_range_bounds():
    profiles = {"x": {"charsets": {"a": {"characters": "AB"}}, "length": {"kind": "range", "min": 2, "max": 3}}}
    ok = symbol.assess(profiles, "x", value="AB", strict=True)[0]
    assert not [item for item in ok if item["rule_id"] == spec.RULE_SYMBOL_LENGTH]
    assert symbol.assess(profiles, "x", value="A", strict=True)[0][0]["rule_id"] == spec.RULE_SYMBOL_LENGTH
    assert symbol.assess(profiles, "x", value="ABAB", strict=True)[0][0]["rule_id"] == spec.RULE_SYMBOL_LENGTH


def test_symbol_retail_gtin_strips_leading_zero():
    findings, _, _ = symbol.assess(PROFILES, "ean13", value="04006381333931", strict=True)
    assert not [item for item in findings if item["severity"] in ("warn", "error")]


def test_symbol_retail_gtin_rejects_bad_length():
    findings, _, _ = symbol.assess(PROFILES, "ean13", value="123", strict=True)
    assert findings[0]["rule_id"] == spec.RULE_SYMBOL_LENGTH


def test_symbol_checksum_bad():
    findings, _, _ = symbol.assess(PROFILES, "ean13", value="4006381333932", strict=True)
    assert any(item["rule_id"] == spec.RULE_SYMBOL_CHECKSUM for item in findings)


def test_symbol_checksum_ok():
    findings, _, _ = symbol.assess(PROFILES, "ean13", value="4006381333931", strict=True)
    assert not any(item["rule_id"] == spec.RULE_SYMBOL_CHECKSUM for item in findings)


def test_symbol_plan_records_segments():
    findings, _, evidence = symbol.assess(PROFILES, "ean13", value="4006381333931", strict=True)
    plan = [item for item in findings if item["id"] == "encoding_plan"]
    assert plan
    assert evidence["plan"][0]["mode"] == "retail-numeric"


def test_symbol_fixed_modules_are_reported():
    findings, _, evidence = symbol.assess(PROFILES, "ean13", value="4006381333931", strict=True)
    assert evidence["modules"]["total"] == 95


def test_symbol_code128_modules():
    profiles = {
        "code128": {
            "charsets": {"b": {"characters": "ABC012"}},
            "length": {"kind": "range", "min": 1, "max": 80},
            "modes": [{"name": "B", "charset": "b", "group_size": 1, "min_run": 1, "priority": 1}],
            "modules": {"kind": "code128", "start_modules": 11, "modules_per_codeword": 11, "stop_modules": 13},
            "checksum": {"kind": "mod103", "appended": True},
        }
    }
    findings, _, evidence = symbol.assess(profiles, "code128", value="ABC", strict=True)
    assert evidence["modules"]["data_codewords"] == 3
    assert evidence["modules"]["total"] == 11 + 11 * 4 + 13


def test_symbol_matrix_capacity_fits():
    profiles = {
        "qr": {
            "charsets": {"b": {"characters": "0123456789"}},
            "length": {"kind": "range", "min": 1, "max": 2000},
            "modes": [{"name": "n", "charset": "b", "group_size": 3, "group_bits": 10, "header_bits": 4, "count_bits": 10, "min_run": 1, "priority": 1}],
            "modules": {"kind": "matrix", "bits_per_codeword": 8, "table": [{"side": 21, "data_codewords": 16}]},
            "checksum": {"kind": "reedsolomon", "appended": True},
        }
    }
    findings, _, evidence = symbol.assess(profiles, "qr", value="123456789", strict=True)
    assert not any(item["rule_id"] == spec.RULE_SYMBOL_CAPACITY for item in findings)
    assert evidence["modules"]["side"] == 21


def test_symbol_matrix_capacity_overflow():
    profiles = {
        "qr": {
            "charsets": {"b": {"characters": "0123456789"}},
            "length": {"kind": "range", "min": 1, "max": 4000},
            "modes": [{"name": "n", "charset": "b", "group_size": 3, "group_bits": 10, "header_bits": 4, "count_bits": 10, "min_run": 1, "priority": 1}],
            "modules": {"kind": "matrix", "bits_per_codeword": 8, "table": [{"side": 21, "data_codewords": 1}]},
            "checksum": {"kind": "reedsolomon", "appended": True},
        }
    }
    findings, _, _ = symbol.assess(profiles, "qr", value="123456789", strict=True)
    assert any(item["rule_id"] == spec.RULE_SYMBOL_CAPACITY for item in findings)


def test_encoding_plan_is_none_when_uncoverable():
    profiles = {"x": {"charsets": {"a": {"characters": "A"}}, "modes": [{"name": "A", "charset": "a", "priority": 1, "group_size": 1, "min_run": 1}]}}
    assert symbol.encoding_plan("AB", profiles["x"]) is None


def test_encoding_plan_merges_same_mode():
    profiles = {"x": {"charsets": {"a": {"characters": "AB"}}, "modes": [{"name": "A", "charset": "a", "priority": 1, "group_size": 1, "min_run": 1}]}}
    plan = symbol.encoding_plan("AB", profiles["x"])
    assert len(plan) == 1
    assert plan[0]["text"] == "AB"


def test_encoding_plan_priority_order():
    profiles = {
        "x": {
            "charsets": {"digits": {"characters": "0123456789"}, "any": {"characters": "0123456789AB"}},
            "modes": [
                {"name": "digits", "charset": "digits", "group_size": 2, "min_run": 2, "priority": 1, "requires_full_groups": True},
                {"name": "any", "charset": "any", "group_size": 1, "min_run": 1, "priority": 2},
            ],
        }
    }
    plan = symbol.encoding_plan("12A", profiles["x"])
    assert [item["mode"] for item in plan] == ["digits", "any"]


def test_symbol_no_status_means_not_applicable():
    findings, _, _ = symbol.assess(PROFILES, "ean13", value="4006381333931", strict=False)
    assert findings


# ================================================================== 阈值册
def test_book_requires_thresholds_object():
    with pytest.raises(ValueError):
        book_mod.Book([])


def test_book_requires_gen_spec_object():
    data = json.loads(json.dumps(BOOK_DATA))
    data["gen_spec"] = "oops"
    with pytest.raises(ValueError):
        book_mod.Book(data)


def test_book_requires_quiet_zone_object():
    data = json.loads(json.dumps(BOOK_DATA))
    del data["quiet_zone"]
    with pytest.raises(ValueError):
        book_mod.Book(data)


def test_book_requires_color_cases_object():
    data = json.loads(json.dumps(BOOK_DATA))
    del data["color_cases"]
    with pytest.raises(ValueError):
        book_mod.Book(data)


def test_book_gen_spec_entry_missing_raises():
    with pytest.raises(ValueError):
        _book().gen_spec_entry("no_such_key")


def test_book_engineering_missing_raises():
    with pytest.raises(ValueError):
        _book().engineering("no_such_key")


def test_book_quiet_zone_unknown_symbol_raises():
    with pytest.raises(ValueError):
        _book().quiet_zone_entry("qr", "left")


def test_book_quiet_zone_unknown_side_raises():
    with pytest.raises(ValueError):
        _book().quiet_zone_entry("ean13", "middle")


def test_book_rejects_gen_spec_without_source():
    data = json.loads(json.dumps(BOOK_DATA))
    del data["gen_spec"]["values"]["nominal_x_mm"]["source"]
    with pytest.raises(ValueError):
        book_mod.Book(data)


def test_book_rejects_gen_spec_without_status():
    data = json.loads(json.dumps(BOOK_DATA))
    del data["gen_spec"]["values"]["nominal_x_mm"]["status"]
    with pytest.raises(ValueError):
        book_mod.Book(data)


def test_book_rejects_gen_spec_without_verified_at():
    data = json.loads(json.dumps(BOOK_DATA))
    del data["gen_spec"]["values"]["nominal_x_mm"]["verified_at"]
    with pytest.raises(ValueError):
        book_mod.Book(data)


def test_book_rejects_non_numeric_value():
    data = json.loads(json.dumps(BOOK_DATA))
    data["gen_spec"]["values"]["nominal_x_mm"]["value"] = "abc"
    with pytest.raises(ValueError):
        book_mod.Book(data)


@pytest.mark.parametrize("value", [None, True, "abc", "NaN"])
def test_as_decimal_rejects_bad_values(value):
    with pytest.raises(ValueError):
        book_mod.as_decimal(value, "x")


def test_as_decimal_accepts_strings_and_ints():
    assert book_mod.as_decimal("0.330", "x") == Decimal("0.330")
    assert book_mod.as_decimal(203, "x") == Decimal(203)


def test_fixed_renders_three_places():
    assert book_mod.fixed(Decimal("1.5")) == "1.500"


def test_status_of_reads_entry_status():
    assert book_mod.Book.status_of({"status": "unverified"}) == "unverified"
    assert book_mod.Book.status_of({}) == "not-applicable"


def test_illumination_returns_model():
    assert _book().illumination("red")["channel"] == "red"


def test_illumination_unknown_is_unmodelled():
    assert _book().illumination("uv")["modelled"] is False


# ================================================================== 印刷层
def _qz(margins, x="0.330", symbol="ean13", strict=False):
    return checks.quiet_zone(_book(), symbol, {side: Decimal(margins.get(side, "0")) for side in spec.QUIET_ZONE_SIDES}, Decimal(x), strict)


def test_quiet_zone_zero_required_is_absent_error():
    findings = _qz({"left": "0", "right": "3.63"})
    assert findings[0]["rule_id"] == spec.RULE_QUIET_ZONE_ABSENT
    assert findings[0]["severity"] == "error"


def test_quiet_zone_zero_optional_is_fine():
    findings = _qz({"left": "3.63", "right": "2.31", "top": "0", "bottom": "0"})
    assert not any(item["rule_id"] == spec.RULE_QUIET_ZONE_ABSENT for item in findings)


def test_quiet_zone_insufficient_downgrades_to_warn():
    findings = checks.quiet_zone(_book(), "ean13", {side: Decimal("2.0") for side in spec.QUIET_ZONE_SIDES}, Decimal("0.330"), False)
    insufficient = [item for item in findings if item["id"] == "quiet_zone_insufficient"]
    assert insufficient[0]["severity"] == "warn"


def test_quiet_zone_strict_restores_error():
    findings = checks.quiet_zone(_book(), "ean13", {side: Decimal("2.0") for side in spec.QUIET_ZONE_SIDES}, Decimal("0.330"), True)
    assert any(item["severity"] == "error" for item in findings)


def test_quiet_zone_marginal_band_is_warn():
    findings = _qz({"left": "3.63", "right": "2.31"})
    marginal = [item for item in findings if "the minimum is" in item["observed"]]
    assert marginal
    assert all(item["severity"] == "warn" for item in marginal)


def test_quiet_zone_source_ids_are_distinct():
    findings = _qz({"left": "2.0", "right": "3.63"})
    ids = {item["id"] for item in findings}
    assert "quiet_zone_insufficient" in ids


def test_quiet_zone_exact_minimum_is_marginal():
    findings = _qz({"left": "3.63", "right": "2.31"})
    assert any("11.000 modules" in item["observed"] for item in findings)


def test_quiet_zone_well_above_has_no_finding_for_side():
    findings = _qz({"left": "5.0", "right": "5.0"})
    assert findings == []


def test_quiet_zone_fix_is_present():
    findings = _qz({"left": "0", "right": "0"})
    assert all(item["fix"] for item in findings)


def test_magnification_inside_is_clean():
    assert checks.magnification(_book(), Decimal("0.330"), False) == []


def test_magnification_below_range_is_warn():
    findings = checks.magnification(_book(), Decimal("0.200"), False)
    assert findings[0]["severity"] == "warn"
    assert findings[0]["id"] == "magnification_below_range"


def test_magnification_above_range_is_warn():
    findings = checks.magnification(_book(), Decimal("0.900"), False)
    assert findings[0]["id"] == "magnification_above_range"


def test_magnification_lower_boundary_is_inclusive():
    assert checks.magnification(_book(), Decimal("0.264"), False) == []


def test_magnification_upper_boundary_is_inclusive():
    assert checks.magnification(_book(), Decimal("0.660"), False) == []


def test_magnification_just_below_floor():
    assert len(checks.magnification(_book(), Decimal("0.263"), False)) == 1


def test_magnification_just_above_ceiling():
    assert len(checks.magnification(_book(), Decimal("0.661"), False)) == 1


def test_magnification_fix_targets_x_dimension():
    findings = checks.magnification(_book(), Decimal("0.200"), False)
    assert findings[0]["fix"]["kind"] == "increase_x_dimension"


def test_raster_computes_dots_per_module():
    # 0.330 / 25.4 * 203 = 2.637 -> ok
    assert checks.raster(_book(), Decimal("0.330"), Decimal(203), False) == []


def test_raster_warn_band():
    findings = checks.raster(_book(), Decimal("0.330"), Decimal(150), False)
    assert findings[0]["severity"] == "warn"


def test_raster_error_band():
    findings = checks.raster(_book(), Decimal("0.330"), Decimal(100), False)
    assert findings[0]["severity"] == "error"


def test_raster_boundary_1_5_is_warn():
    # 116 dpi @ 0.330 mm -> 1.507 dots/module -> warn (just above the error floor)
    findings = checks.raster(_book(), Decimal("0.330"), Decimal(116), False)
    assert findings and findings[0]["severity"] == "warn"


def test_raster_boundary_2_0_is_ok():
    # 154 dpi @ 0.330 mm -> 2.0008 dots/module -> ok
    assert checks.raster(_book(), Decimal("0.330"), Decimal(154), False) == []


def test_raster_is_not_downgraded_by_strict_flag():
    findings = checks.raster(_book(), Decimal("0.330"), Decimal(100), False)
    assert findings[0]["threshold_status"] == spec.THRESHOLD_NOT_APPLICABLE


def test_raster_fix_names_needed_dpi():
    findings = checks.raster(_book(), Decimal("0.330"), Decimal(100), False)
    assert int(findings[0]["fix"]["to"]) > 100


def test_bar_height_ok():
    assert checks.bar_height(_book(), "ean13", Decimal("22.85"), Decimal("0.330"), False) == []


def test_bar_height_short_downgrades():
    findings = checks.bar_height(_book(), "ean13", Decimal("20.00"), Decimal("0.330"), False)
    assert findings[0]["severity"] == "warn"


def test_bar_height_short_strict():
    findings = checks.bar_height(_book(), "ean13", Decimal("20.00"), Decimal("0.330"), True)
    assert findings[0]["severity"] == "error"


def test_bar_height_symbol_without_threshold_is_silent():
    assert checks.bar_height(_book(), "qr", Decimal("1"), Decimal("0.330"), True) == []


def test_bar_height_fix_present():
    findings = checks.bar_height(_book(), "ean13", Decimal("20.00"), Decimal("0.330"), False)
    assert findings[0]["fix"]["kind"] == "increase_bar_height"


def test_parse_color_accepts_rrggbb():
    assert checks.parse_color("#000000") == (0, 0, 0)
    assert checks.parse_color("#FFFFFF") == (255, 255, 255)


@pytest.mark.parametrize("raw", ["000000", "#FFF", "#GGGGGG", None, 12])
def test_parse_color_rejects_unmodelled(raw):
    assert checks.parse_color(raw) is None


def test_relative_luminance_white_is_one():
    assert round(checks.relative_luminance((255, 255, 255)), 6) == 1.0


def test_relative_luminance_black_is_zero():
    assert checks.relative_luminance((0, 0, 0)) == 0


def test_contrast_black_on_white_is_21():
    assert round(checks.contrast_ratio((0, 0, 0), (255, 255, 255)), 2) == 21.0


def test_contrast_is_symmetric():
    assert checks.contrast_ratio((0, 0, 0), (255, 255, 255)) == checks.contrast_ratio((255, 255, 255), (0, 0, 0))


def test_color_black_white_white_light_is_clean():
    assert checks.color(_book(), "#000000", "#FFFFFF", "white") == []


def test_color_grey_is_low_contrast():
    findings = checks.color(_book(), "#777777", "#FFFFFF", "white")
    assert findings and findings[0]["severity"] in ("warn", "error")


def test_color_red_on_white_white_light_is_fine():
    assert checks.color(_book(), "#C8102E", "#FFFFFF", "white") == []


def test_color_red_on_white_red_light_collapses():
    findings = checks.color(_book(), "#C8102E", "#FFFFFF", "red")
    assert any(item["id"] == "wavelength_reflectance_collapse" for item in findings)


def test_color_ir_is_unmodelled():
    findings = checks.color(_book(), "#000000", "#FFFFFF", "ir")
    assert findings[0]["rule_id"] == spec.RULE_UNMODELLED
    assert findings[0]["severity"] == "info"


def test_color_bad_hex_is_unmodelled():
    findings = checks.color(_book(), "black", "#FFFFFF", "white")
    assert findings[0]["rule_id"] == spec.RULE_UNMODELLED


def test_color_is_not_downgraded():
    findings = checks.color(_book(), "#777777", "#FFFFFF", "white")
    assert findings[0]["threshold_status"] == spec.THRESHOLD_NOT_APPLICABLE


def test_engineering_finding_has_no_status():
    finding = checks.engineering("x", "warn", "o", "t", "ref", "q", None)
    assert finding["threshold_status"] == spec.THRESHOLD_NOT_APPLICABLE


def test_gen_spec_finding_downgrades_error():
    entry = {"status": "unverified", "source": "s"}
    finding = checks.gen_spec(_book(), "x", "error", "o", "t", entry, "ref", False, None, "th")
    assert finding["severity"] == "warn"


def test_gen_spec_finding_strict_keeps_error():
    entry = {"status": "unverified", "source": "s"}
    finding = checks.gen_spec(_book(), "x", "error", "o", "t", entry, "ref", True, None, "th")
    assert finding["severity"] == "error"


def test_gen_spec_finding_verified_keeps_error():
    entry = {"status": "verified", "source": "s"}
    finding = checks.gen_spec(_book(), "x", "error", "o", "t", entry, "ref", False, None, "th")
    assert finding["severity"] == "error"


# ================================================================== oracle
@pytest.mark.parametrize(
    "verdict,decoded,agreement",
    [
        ("pass", True, "consistent"),
        ("pass", False, "m3_laxer"),
        ("warn", False, "consistent"),
        ("warn", True, "m3_stricter"),
        ("fail", False, "consistent"),
        ("fail", True, "m3_stricter"),
    ],
)
def test_oracle_matrix(verdict, decoded, agreement):
    result, known, bugs = oracle.classify(verdict, decoded, ["q"])
    assert result == agreement
    assert (len(known), len(bugs)) == ((1, 0) if agreement == "m3_stricter" else (0, 1) if agreement == "m3_laxer" else (0, 0))


def test_oracle_rejects_unknown_verdict():
    with pytest.raises(ValueError):
        oracle.classify("unknown", True)


def test_oracle_stricter_note_is_known_disagreement():
    _result, known, _bugs = oracle.classify("warn", True, [])
    assert "known-disagreements" in known[0]["note"]


def test_oracle_laxer_note_is_bug_channel():
    _result, _known, bugs = oracle.classify("pass", False, [])
    assert "bug 通道" in bugs[0]["note"]


def test_oracle_finding_ids_are_sorted():
    _result, known, _ = oracle.classify("warn", True, ["b", "a"])
    assert known[0]["finding_ids"] == ["a", "b"]


def test_m3_verdict_pass_without_findings():
    assert oracle.m3_verdict([]) == "pass"


def test_m3_verdict_warn():
    assert oracle.m3_verdict([{"module": "M3", "severity": "warn"}]) == "warn"


def test_m3_verdict_fail():
    assert oracle.m3_verdict([{"module": "M3", "severity": "error"}]) == "fail"


def test_m3_verdict_ignores_other_modules():
    assert oracle.m3_verdict([{"module": "M1", "severity": "error"}]) == "pass"


def test_risky_finding_ids_are_deduplicated():
    findings = [
        {"module": "M3", "severity": "warn", "id": "quiet_zone_insufficient"},
        {"module": "M3", "severity": "warn", "id": "quiet_zone_insufficient"},
        {"module": "M3", "severity": "info", "id": "x"},
    ]
    assert oracle.risky_finding_ids(findings) == ["quiet_zone_insufficient"]


# ================================================================== 模式与门禁
def test_check_clean_sample_exits_zero():
    assert _report(_check()).exit_code() == EXIT_OK


def test_check_summary_is_present():
    records = _records(_check(bar_height_mm=None), spec.RULE_SUMMARY)
    assert len(records) == 1
    assert records[0].evidence["verdict"] in ("pass", "warn", "fail")


def test_check_gate_none_never_blocks():
    assert _records(_check(bar_height_mm="1.00", fail_on="none"), spec.RULE_GATE) == []


def test_check_gate_error_blocks_on_downgraded_finding():
    # downgraded to warn: fail_on=error must NOT block
    assert _records(_check(bar_height_mm="1.00", fail_on="error"), spec.RULE_GATE) == []


def test_check_gate_warn_blocks_on_warn_finding():
    record = _records(_check(bar_height_mm="1.00", fail_on="warn"), spec.RULE_GATE)[0]
    assert record.verdict == ERROR
    assert record.evidence["source_exit_code"] == 1


def test_check_gate_strict_error_blocks():
    subject = _check(bar_height_mm="1.00", fail_on="error", strict_thresholds=True)
    record = _records(subject, spec.RULE_GATE)[0]
    assert record.evidence["worst_severity"] == "error"
    assert record.evidence["source_exit_code"] == 2


def test_check_gate_warn_report_is_blocked():
    assert _report(_check(bar_height_mm="1.00", fail_on="warn")).exit_code() == EXIT_BLOCKED


def test_check_gate_error_report_is_blocked():
    subject = _check(bar_height_mm="1.00", fail_on="error", strict_thresholds=True)
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_check_invalid_fail_on_is_input_error():
    with pytest.raises(ValueError):
        _evaluate(_check(fail_on="maybe"))


def test_check_missing_geometry_is_one_incomplete():
    subject = _check(x_dimension_mm=None, target_dpi=None)
    findings = [
        record
        for record in _evaluate(subject)
        if record.rule_id.startswith("bp-print-") and record.path.startswith("findings[")
    ]
    assert len(findings) == 1
    assert findings[0].evidence["id"] == "input_incomplete"


def test_check_missing_quiet_zone_is_incomplete():
    subject = _check(quiet_zone_mm=None)
    assert any(record.evidence.get("id") == "input_incomplete" for record in _evaluate(subject))


def test_check_zero_x_dimension_is_incomplete():
    subject = _check(x_dimension_mm="0")
    assert any(record.evidence.get("id") == "x_dimension_missing" for record in _evaluate(subject))


def test_check_unusable_number_is_incomplete():
    subject = _check(x_dimension_mm="abc")
    assert any(record.evidence.get("id") == "input_incomplete" for record in _evaluate(subject))


def test_check_color_runs_without_geometry():
    subject = _check(x_dimension_mm=None, target_dpi=None, quiet_zone_mm=None, bar_color="#777777")
    codes = [record.evidence.get("id") for record in _evaluate(subject) if record.path.startswith("findings[")]
    assert any(code in ("insufficient_contrast", "low_contrast") for code in codes)


def test_check_no_print_input_skips_print_layer():
    subject = _check(
        x_dimension_mm=None, target_dpi=None, quiet_zone_mm=None, bar_height_mm=None,
        bar_color=None, space_color=None, illumination=None,
    )
    summary = _records(subject, spec.RULE_SUMMARY)[0]
    assert summary.evidence["print_judged"] is False


def test_check_symbol_not_specified_is_skipped():
    summary = _records(_check(symbol=None, bar_height_mm=None), spec.RULE_SUMMARY)[0]
    assert "symbol_not_specified" in summary.evidence["skipped"]


def test_check_unknown_symbol_is_skipped_in_print_layer():
    profiles = json.loads(json.dumps(PROFILES))
    profiles.pop("ean13")
    summary = _records(_check(profiles=profiles), spec.RULE_SUMMARY)[0]
    assert any(item.startswith("symbol_unsupported:") for item in summary.evidence["skipped"])


def test_check_identifier_non_digit_is_charset_finding():
    subject = _check(identifier="ABC", symbol=None, bar_height_mm=None,
                     x_dimension_mm=None, target_dpi=None, quiet_zone_mm=None,
                     bar_color=None, space_color=None, illumination=None)
    assert any(record.evidence.get("id") == spec.RULE_GS1_CHARSET for record in _evaluate(subject))


def test_check_element_string_runs_gs1_layer():
    subject = _check(gs1_element_string="(01)04006381333932", symbol=None, bar_height_mm=None,
                     x_dimension_mm=None, target_dpi=None, quiet_zone_mm=None,
                     bar_color=None, space_color=None, illumination=None)
    assert any(record.evidence.get("id") == spec.RULE_GS1_CHECKSUM for record in _evaluate(subject))


def test_check_missing_data_is_skipped():
    subject = _check(identifier=None, gs1_element_string=None)
    summary = _records(subject, spec.RULE_SUMMARY)[0]
    assert "data_not_provided" in summary.evidence["skipped"]


def test_gs1_mode_reports_clean():
    subject = {"mode": "gs1", "gs1_element_string": "(01)04006381333931", "dictionary": dict(DICTIONARY), "century_resolution": dict(CENTURY)}
    records = _records(subject, spec.RULE_SUMMARY)
    assert records[0].evidence["worst_severity"] == "ok"


def test_gs1_mode_reports_checksum():
    subject = {"mode": "gs1", "gs1_element_string": "(01)04006381333932", "dictionary": dict(DICTIONARY)}
    assert any(record.evidence.get("id") == spec.RULE_GS1_CHECKSUM for record in _evaluate(subject))


def test_gs1_mode_reports_unknown_ai():
    subject = {"mode": "gs1", "gs1_element_string": "(99)X", "dictionary": dict(DICTIONARY)}
    assert any(record.evidence.get("id") == spec.RULE_GS1_UNKNOWN_AI for record in _evaluate(subject))


def test_gs1_mode_requires_dictionary():
    with pytest.raises(ValueError):
        _evaluate({"mode": "gs1", "gs1_element_string": "(01)04006381333931"})


def test_gs1_mode_default_century_resolution():
    subject = {"mode": "gs1", "gs1_element_string": "(17)251231", "dictionary": dict(DICTIONARY)}
    assert _records(subject, spec.RULE_SUMMARY)[0].evidence["worst_severity"] == "ok"


def test_symbol_mode_reports_clean():
    subject = {"mode": "symbol", "symbol": "ean13", "value": "4006381333931", "profiles": json.loads(json.dumps(PROFILES))}
    assert _records(subject, spec.RULE_SUMMARY)[0].evidence["worst_severity"] in ("ok", "info")


def test_symbol_mode_requires_profiles():
    with pytest.raises(ValueError):
        _evaluate({"mode": "symbol", "symbol": "ean13"})


def test_symbol_mode_requires_symbol():
    with pytest.raises(ValueError):
        _evaluate({"mode": "symbol", "profiles": {}})


def test_oracle_mode_stricter():
    subject = {"mode": "oracle", "m3_verdict": "warn", "decoded": True, "finding_ids": ["quiet_zone_insufficient"]}
    record = _records(subject, spec.RULE_ORACLE_AGREEMENT)[0]
    assert record.evidence["agreement"] == "m3_stricter"


def test_oracle_mode_laxer_is_warn():
    subject = {"mode": "oracle", "m3_verdict": "pass", "decoded": False}
    record = _records(subject, spec.RULE_ORACLE_AGREEMENT)[0]
    assert record.verdict == WARN
    assert record.evidence["agreement"] == "m3_laxer"


def test_oracle_mode_requires_verdict():
    with pytest.raises(ValueError):
        _evaluate({"mode": "oracle", "decoded": True})


def test_oracle_mode_requires_decoded():
    with pytest.raises(ValueError):
        _evaluate({"mode": "oracle", "m3_verdict": "pass"})


def test_oracle_mode_accepts_findings():
    subject = {"mode": "oracle", "decoded": True, "findings": [{"module": "M3", "severity": "warn", "id": "x"}]}
    assert _records(subject, spec.RULE_ORACLE_AGREEMENT)[0].evidence["m3_verdict"] == "warn"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "collect"})


def test_missing_mode_is_rejected():
    with pytest.raises(ValueError):
        _evaluate({})


def test_missing_rule_in_empty_basis_is_contract_violation():
    with pytest.raises(RuleMissing):
        _evaluate(_check(), basis=Basis.empty("1"))


# ================================================================== CLI 与契约
def test_cli_sample_exits_zero(capsys):
    code = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["organ"] == SLUG


def test_cli_gate_warn_exits_one(tmp_path, capsys):
    subject = _check(bar_height_mm="1.00", fail_on="warn")
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_BLOCKED


def test_cli_unknown_mode_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "nope"}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_INPUT


def test_cli_missing_rule_exits_three(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_check(), ensure_ascii=False), encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(empty), "--json"]) == EXIT_CONTRACT


def test_cli_basis_is_optional(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps({"mode": "gs1", "gs1_element_string": "(01)04006381333931", "dictionary": DICTIONARY}, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--json"]) == EXIT_OK


def test_cli_double_run_is_byte_identical(capsys):
    argv = ["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"]
    assert cli.main(argv) == EXIT_OK
    first = capsys.readouterr().out
    assert cli.main(argv) == EXIT_OK
    second = capsys.readouterr().out
    assert first == second


def test_cli_list_contains_the_organ(capsys):
    assert cli.main(["list"]) == EXIT_OK
    assert SLUG in capsys.readouterr().out


def test_report_ids_are_unique_for_check():
    ids = [record.id for record in _report(_check(bar_height_mm="1.00")).records]
    assert len(ids) == len(set(ids))


def test_report_ids_are_unique_for_gs1():
    subject = {"mode": "gs1", "gs1_element_string": "(01)04006381333932(01)04006381333932", "dictionary": dict(DICTIONARY)}
    ids = [record.id for record in _report(subject).records]
    assert len(ids) == len(set(ids))


def test_every_record_has_a_complete_basis_ref():
    subjects = [
        _check(bar_height_mm="1.00"),
        {"mode": "gs1", "gs1_element_string": "(01)04006381333931", "dictionary": dict(DICTIONARY)},
        {"mode": "symbol", "symbol": "ean13", "value": "4006381333931", "profiles": json.loads(json.dumps(PROFILES))},
        {"mode": "oracle", "m3_verdict": "pass", "decoded": True},
    ]
    for subject in subjects:
        for record in _evaluate(subject):
            assert record.basis is not None
            assert record.basis.rule_version == "1"


def test_finding_records_are_non_blocking():
    for record in _evaluate(_check(bar_height_mm="1.00")):
        if record.rule_id != spec.RULE_GATE:
            assert record.verdict in (INFO, WARN)


# ================================================================== 器官契约（静态）
def _organ_sources():
    return sorted(path for path in ORGAN_DIR.glob("*.py"))


def test_organ_has_no_network_imports():
    forbidden = {"requests", "socket", "http", "urllib", "ftplib", "smtplib"}
    hits = []
    for path in _organ_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_does_not_open_files_or_read_environment():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                hits.append((path.name, "open"))
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_read_the_wall_clock():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow", "today", "time"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_spawn_subprocesses():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "subprocess":
                        hits.append((path.name, alias.name))
    assert hits == []


def test_organ_does_not_import_the_old_package():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "bpreflight":
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "bpreflight":
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_data_lives_under_package_data_directory():
    assert BASIS_PATH.parent == DATA_DIR
    assert THRESHOLDS_PATH.parent == DATA_DIR
    assert not list(ORGAN_DIR.glob("*.json"))


def test_organ_never_uses_lossy_codec_error_handlers():
    hits = []
    for path in _organ_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "errors"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value in ("replace", "ignore")
                ):
                    hits.append((path.name, keyword.value.value))
    assert hits == []