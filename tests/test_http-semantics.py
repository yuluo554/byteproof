"""``http-semantics`` 器官的无损测试（迁自 10-19-http-semantics-mcp，Python 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：五个判定工具
（``cache_evaluate`` / ``conditional_evaluate`` / ``cors_evaluate`` /
``cors_simulate_fetch`` / ``vary_match``）的**同参**调用 + 80 个冻结 golden 案例
（18+19+24+10+9）**逐字节对账** + 时间解析器（7 个 ``_time`` 案例）+ 31 条规则目录
（basis ↔ thresholds ↔ 模块常量三向一致）+ 规范化/比较函数/指令解析的单元面。

**没迁的部分逐条写在 ``docs/http-semantics.md`` §6 的处置表里**（MCP 传输壳、
JSON-RPC 协议、schemas/registry/server、gen_codes/gen_golden 生成器、WPT 台账、
CI/readme/release 门）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 26 个测试文件剔除 ``packaging`` / ``release_gate`` /
``utf8_guard`` 后 23 文件实跑 pytest **X = 367 passed**（``367 passed in 11.86s``）。
旧层 AST ``test`` 函数 **259**（口径乙分母）。本文件 AST ``test_`` 函数与用例数
见 docs §6 表格。

golden 夹具 = 旧仓 ``data/golden/`` 87 个案例文件**原样复制**（case_id / source /
spec_basis 字段保留，来源可追溯），位于 ``tests/fixtures/http-semantics-golden/``。
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors import http_semantics as hs  # noqa: E402
from byteproof.auditors.http_semantics import (  # noqa: E402
    api,
    cache,
    canonical,
    catalogue,
    conditional,
    cors,
    default_settings,
    errors as hs_errors,
    fetch_sim,
    normalise,
    spec,
    timeparse,
    vary,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    Basis,
    Record,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "http-semantics"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "http-semantics.basis.json"
THRESHOLDS_PATH = DATA_DIR / "http-semantics.thresholds.json"
SAMPLE = ROOT / "samples" / "http-semantics.minimal.json"
GOLDEN = ROOT / "tests" / "fixtures" / "http-semantics-golden"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

#: 五个工具结果对象的冻结键集（旧仓 tests/test_golden.py OUTPUT_KEYS 同构）。
OUTPUT_KEYS = {
    "_time": {"form", "timestamp"},
    "cache_evaluate": {"action", "current_age", "freshness_lifetime", "is_fresh",
                       "must_revalidate", "reasons", "stale_while_revalidate_window"},
    "conditional_evaluate": {"explain", "rule_applied", "status", "weak_comparison_used"},
    "cors_evaluate": {"decision", "violations", "missing_headers", "recommended_headers", "notes"},
    "cors_simulate_fetch": {"decision", "events", "final_type", "hops", "max_age_effective",
                            "preflight_cache_key", "preflight_occurred", "visible_headers"},
    "vary_match": {"differing_headers", "match", "normalized_vary", "reasons"},
}


# ================================================================== 加载器
def _load_cases():
    """加载 87 个 golden 案例：``{case_id: {tool, input, expected}}``。"""
    cases = {}
    for tool_dir in sorted(GOLDEN.iterdir()):
        if not tool_dir.is_dir():
            continue
        for path in sorted(tool_dir.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            cases[case["case_id"]] = {
                "tool": tool_dir.name,
                "input": case["input"],
                "expected": case["expected"],
                "file": path.name,
            }
    return cases


CASES = _load_cases()
TOOL_CASES = {
    "cache_evaluate": [cid for cid, c in CASES.items() if c["tool"] == "cache_evaluate"],
    "conditional_evaluate": [cid for cid, c in CASES.items() if c["tool"] == "conditional_evaluate"],
    "cors_evaluate": [cid for cid, c in CASES.items() if c["tool"] == "cors_evaluate"],
    "cors_simulate_fetch": [cid for cid, c in CASES.items() if c["tool"] == "cors_simulate_fetch"],
    "vary_match": [cid for cid, c in CASES.items() if c["tool"] == "vary_match"],
}


def _catalog(basis=None, settings=None):
    return catalogue.Catalogue(BASIS if basis is None else basis,
                               SETTINGS if settings is None else settings)


def _run_tool(tool, arguments):
    """跑一个工具（同参），返回 result 或抛 JudgementError。"""
    return api._dispatch(tool, arguments, _catalog())


def _subject(mode, arguments):
    return {"mode": mode, "arguments": arguments}


def _evaluate(subject, basis=None):
    return list((get(SLUG).evaluate)(subject, BASIS if basis is None else basis))


def _report(records):
    """由已求得的记录构建 Report（不二次求值）。"""
    return Report(product="byteproof", organ=SLUG, organ_version=spec.ORGAN_VERSION,
                  subject="t", records=records)


def _summary(records):
    return [r for r in records if r.rule_id == "hs-summary"][0]


def _result_of(records):
    return _summary(records).evidence["result"]


# ==================================================================
# §1 golden 逐案例对账（80 工具案例 + 7 时间案例；结果逐字节 / 键集冻结 / 双跑一致）
# ==================================================================

def _golden_tool(case_id):
    """工具案例三断言：结果逐字节 + 键集冻结 + 双跑一致。"""
    case = CASES[case_id]
    tool, arguments, expected = case["tool"], case["input"], case["expected"]
    if "error" in expected:
        with pytest.raises(hs_errors.JudgementError) as excinfo:
            _run_tool(tool, arguments)
        got = excinfo.value.payload()["error"]
        want = expected["error"]
        assert set(got) == set(want) == {"code", "field", "detail"}, case_id
        assert got == want, case_id
        # 双跑一致：caller mistake 的渲染同样确定
        with pytest.raises(hs_errors.JudgementError) as again:
            _run_tool(tool, arguments)
        assert again.value.payload()["error"] == want, case_id
        return
    result = _run_tool(tool, arguments)
    assert set(result) == OUTPUT_KEYS[tool], "%s 键集漂移: %s" % (case_id, set(result) ^ OUTPUT_KEYS[tool])
    assert canonical.dumps(result) == canonical.dumps(expected), (
        "%s 结果逐字节不一致:\n got=%s\nwant=%s" % (case_id, canonical.dumps(result), canonical.dumps(expected))
    )
    repeat = _run_tool(tool, arguments)
    assert canonical.dumps(repeat) == canonical.dumps(result), "%s 双跑不一致" % case_id


def _golden_time(case_id):
    """时间案例：form/timestamp 逐字段对账（_time 不是工具，无 result 包裹）。"""
    case = CASES[case_id]
    arguments, expected = case["input"], case["expected"]
    if "error" in expected:
        with pytest.raises(hs_errors.JudgementError) as excinfo:
            timeparse.parse_time(arguments["value"], "_time")
        assert excinfo.value.code == "INVALID_TIME_FORMAT", case_id
        return
    form, timestamp = timeparse.parse_time(arguments["value"], "_time")
    assert form == expected["form"], case_id
    assert timestamp == expected["timestamp"], case_id


def test_golden_time_001_iso():
    _golden_time("time-001-iso")


def test_golden_time_002_http_date():
    _golden_time("time-002-http-date")


def test_golden_time_003_subsecond_truncated():
    _golden_time("time-003-subsecond-truncated")


def test_golden_time_004_invalid():
    _golden_time("time-004-invalid")


def test_golden_time_005_wrong_weekday():
    _golden_time("time-005-wrong-weekday")


def test_golden_time_006_missing_zone():
    _golden_time("time-006-missing-zone")


def test_golden_time_007_subsecond_truncates_not_rounds():
    _golden_time("time-007-subsecond-truncates-not-rounds")


def test_golden_cache_001_fresh():
    _golden_tool("cache-001-fresh")


def test_golden_cache_002_age_exceeds_lifetime():
    _golden_tool("cache-002-age-exceeds-lifetime")


def test_golden_cache_003_no_store():
    _golden_tool("cache-003-no-store")


def test_golden_cache_004_no_cache():
    _golden_tool("cache-004-no-cache")


def test_golden_cache_005_must_revalidate_stale():
    _golden_tool("cache-005-must-revalidate-stale")


def test_golden_cache_006_stale_while_revalidate():
    _golden_tool("cache-006-stale-while-revalidate")


def test_golden_cache_007_swr_window_closed():
    _golden_tool("cache-007-swr-window-closed")


def test_golden_cache_008_expires_in_past():
    _golden_tool("cache-008-expires-in-past")


def test_golden_cache_009_heuristic():
    _golden_tool("cache-009-heuristic")


def test_golden_cache_010_heuristic_no_last_modified():
    _golden_tool("cache-010-heuristic-no-last-modified")


def test_golden_cache_011_max_age_zero():
    _golden_tool("cache-011-max-age-zero")


def test_golden_cache_012_invalid_max_age():
    _golden_tool("cache-012-invalid-max-age")


def test_golden_cache_013_invalid_age():
    _golden_tool("cache-013-invalid-age")


def test_golden_cache_014_age_exceeds_freshness():
    _golden_tool("cache-014-age-exceeds-freshness")


def test_golden_cache_015_boundary_equal():
    _golden_tool("cache-015-boundary-equal")


def test_golden_cache_016_s_maxage():
    _golden_tool("cache-016-s-maxage")


def test_golden_cache_017_http_date_now():
    _golden_tool("cache-017-http-date-now")


def test_golden_cache_018_expires_without_date():
    _golden_tool("cache-018-expires-without-date")


def test_golden_cond_001_no_condition():
    _golden_tool("cond-001-no-condition")


def test_golden_cond_002_if_match_pass():
    _golden_tool("cond-002-if-match-pass")


def test_golden_cond_003_if_match_failed():
    _golden_tool("cond-003-if-match-failed")


def test_golden_cond_004_if_match_star():
    _golden_tool("cond-004-if-match-star")


def test_golden_cond_005_if_unmodified_since_failed():
    _golden_tool("cond-005-if-unmodified-since-failed")


def test_golden_cond_006_if_unmodified_since_pass():
    _golden_tool("cond-006-if-unmodified-since-pass")


def test_golden_cond_007_if_none_match_weak_304():
    _golden_tool("cond-007-if-none-match-weak-304")


def test_golden_cond_008_if_none_match_put_412():
    _golden_tool("cond-008-if-none-match-put-412")


def test_golden_cond_009_if_none_match_star():
    _golden_tool("cond-009-if-none-match-star")


def test_golden_cond_010_if_modified_since_304():
    _golden_tool("cond-010-if-modified-since-304")


def test_golden_cond_011_if_modified_since_200():
    _golden_tool("cond-011-if-modified-since-200")


def test_golden_cond_012_invalid_date_ignored():
    _golden_tool("cond-012-invalid-date-ignored")


def test_golden_cond_013_both_preconditions():
    _golden_tool("cond-013-both-preconditions")


def test_golden_cond_014_lowercase_weak_marker():
    _golden_tool("cond-014-lowercase-weak-marker")


def test_golden_cond_015_if_match_with_unmodified_since():
    _golden_tool("cond-015-if-match-with-unmodified-since")


def test_golden_cond_016_unmodified_since_with_none_match():
    _golden_tool("cond-016-unmodified-since-with-none-match")


def test_golden_cond_017_none_match_with_modified_since():
    _golden_tool("cond-017-none-match-with-modified-since")


def test_golden_cond_018_unmodified_since_with_modified_since():
    _golden_tool("cond-018-unmodified-since-with-modified-since")


def test_golden_cond_019_if_match_with_modified_since():
    _golden_tool("cond-019-if-match-with-modified-since")


def test_golden_cors_eval_001_basic_allow():
    _golden_tool("cors-eval-001-basic-allow")


def test_golden_cors_eval_002_missing_allow_origin():
    _golden_tool("cors-eval-002-missing-allow-origin")


def test_golden_cors_eval_003_origin_mismatch():
    _golden_tool("cors-eval-003-origin-mismatch")


def test_golden_cors_eval_004_wildcard_with_credentials():
    _golden_tool("cors-eval-004-wildcard-with-credentials")


def test_golden_cors_eval_005_wildcard_omit_allowed():
    _golden_tool("cors-eval-005-wildcard-omit-allowed")


def test_golden_cors_eval_006_missing_allow_credentials():
    _golden_tool("cors-eval-006-missing-allow-credentials")


def test_golden_cors_eval_007_credentials_allow():
    _golden_tool("cors-eval-007-credentials-allow")


def test_golden_cors_eval_008_preflight_missing_methods():
    _golden_tool("cors-eval-008-preflight-missing-methods")


def test_golden_cors_eval_009_preflight_missing_headers():
    _golden_tool("cors-eval-009-preflight-missing-headers")


def test_golden_cors_eval_010_preflight_allow():
    _golden_tool("cors-eval-010-preflight-allow")


def test_golden_cors_eval_011_preflight_required():
    _golden_tool("cors-eval-011-preflight-required")


def test_golden_cors_eval_012_disallowed_header():
    _golden_tool("cors-eval-012-disallowed-header")


def test_golden_cors_eval_013_null_origin():
    _golden_tool("cors-eval-013-null-origin")


def test_golden_cors_eval_014_null_origin_credentials():
    _golden_tool("cors-eval-014-null-origin-credentials")


def test_golden_cors_eval_015_authorization_not_wildcard():
    _golden_tool("cors-eval-015-authorization-not-wildcard")


def test_golden_cors_eval_016_same_origin():
    _golden_tool("cors-eval-016-same-origin")


def test_golden_cors_eval_017_unsupported_method():
    _golden_tool("cors-eval-017-unsupported-method")


def test_golden_cors_eval_018_header_order_invariance_a():
    _golden_tool("cors-eval-018-header-order-invariance-a")


def test_golden_cors_eval_019_header_order_invariance_b():
    _golden_tool("cors-eval-019-header-order-invariance-b")


def test_golden_cors_eval_020_preflight_star_method_credentials():
    _golden_tool("cors-eval-020-preflight-star-method-credentials")


def test_golden_cors_eval_021_safelisted_content_type():
    _golden_tool("cors-eval-021-safelisted-content-type")


def test_golden_cors_eval_022_json_content_type_preflight():
    _golden_tool("cors-eval-022-json-content-type-preflight")


def test_golden_cors_eval_023_allow_origin_whitespace():
    _golden_tool("cors-eval-023-allow-origin-whitespace")


def test_golden_cors_eval_024_allow_credentials_with_wildcard():
    _golden_tool("cors-eval-024-allow-credentials-with-wildcard")


def test_golden_cors_sim_001_same_origin_hop():
    _golden_tool("cors-sim-001-same-origin-hop")


def test_golden_cors_sim_002_cross_origin_credentials_dropped():
    _golden_tool("cors-sim-002-cross-origin-credentials-dropped")


def test_golden_cors_sim_003_cross_origin_omit():
    _golden_tool("cors-sim-003-cross-origin-omit")


def test_golden_cors_sim_004_no_cors_opaque():
    _golden_tool("cors-sim-004-no-cors-opaque")


def test_golden_cors_sim_005_same_origin_mode_blocked():
    _golden_tool("cors-sim-005-same-origin-mode-blocked")


def test_golden_cors_sim_006_cross_to_cross():
    _golden_tool("cors-sim-006-cross-to-cross")


def test_golden_cors_sim_007_preflight_cache_key():
    _golden_tool("cors-sim-007-preflight-cache-key")


def test_golden_cors_sim_008_expose_headers():
    _golden_tool("cors-sim-008-expose-headers")


def test_golden_cors_sim_009_max_age_effective():
    _golden_tool("cors-sim-009-max-age-effective")


def test_golden_cors_sim_010_redirect_after_preflight():
    _golden_tool("cors-sim-010-redirect-after-preflight")


def test_golden_vary_001_hit_single():
    _golden_tool("vary-001-hit-single")


def test_golden_vary_002_miss_value():
    _golden_tool("vary-002-miss-value")


def test_golden_vary_003_star():
    _golden_tool("vary-003-star")


def test_golden_vary_004_field_missing():
    _golden_tool("vary-004-field-missing")


def test_golden_vary_005_accept_case_insensitive():
    _golden_tool("vary-005-accept-case-insensitive")


def test_golden_vary_006_whitespace():
    _golden_tool("vary-006-whitespace")


def test_golden_vary_007_duplicate():
    _golden_tool("vary-007-duplicate")


def test_golden_vary_008_multi_field():
    _golden_tool("vary-008-multi-field")


def test_golden_vary_009_accept_order():
    _golden_tool("vary-009-accept-order")


# ==================================================================
# §2 golden 覆盖双向（每个 code 至少被一个案例命中；案例只用可发出的 code）
# ==================================================================

@pytest.mark.parametrize("tool", sorted(OUTPUT_KEYS)[1:])
def test_golden_cases_only_use_emittable_codes(tool):
    """正向覆盖：每份案例的 reasons/violations/explain 里的 code 都在规则目录里。"""
    finding_key = {"cache_evaluate": "reasons", "conditional_evaluate": "explain",
                   "cors_evaluate": "violations", "cors_simulate_fetch": "violations",
                   "vary_match": "reasons"}[tool]
    for case_id in TOOL_CASES[tool]:
        case = CASES[case_id]
        if "error" in case["expected"]:
            continue
        result = _run_tool(tool, case["input"])
        emitted = []
        if tool == "cors_simulate_fetch":
            for hop in result["hops"]:
                emitted.extend(f["code"] for f in hop["violations"])
        else:
            emitted.extend(f["code"] for f in result[finding_key])
        for code in emitted:
            assert BASIS.rule(code) is not None, "%s 发出了目录外的 code %s" % (case_id, code)


def test_every_tool_has_golden_cases():
    # 反向覆盖（阳性对照）：五个工具各配了完整 golden 组（18/19/24/10/9）
    counts = {t: len(v) for t, v in TOOL_CASES.items()}
    assert counts == {"cache_evaluate": 18, "conditional_evaluate": 19, "cors_evaluate": 24,
                      "cors_simulate_fetch": 10, "vary_match": 9}


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_golden_header_order_invariance(case_id):
    # 旧仓 cors-eval-018/019 的性质推广到全部**工具**案例：JSON 对象键序不影响结果
    # （normalise_headers 按 sorted 名字合并，值序保留）。_time 不是工具调用，跳过。
    case = CASES[case_id]
    if case["tool"] == "_time" or "error" in case["expected"]:
        return  # 错误路径与时间解析在别处已对账
    reversed_input = _reverse_json_objects(case["input"])
    result = _run_tool(case["tool"], reversed_input)
    assert canonical.dumps(result) == canonical.dumps(case["expected"]), case_id


def _reverse_json_objects(value):
    if isinstance(value, dict):
        out = {}
        for key in reversed(list(value.keys())):
            out[key] = _reverse_json_objects(value[key])
        return out
    if isinstance(value, list):
        return [_reverse_json_objects(item) for item in value]
    return value


@pytest.mark.parametrize("case_id", sorted(CASES))
def test_golden_strict_json_round_trip(case_id):
    # canonical.dumps 的不变量：sort_keys + 无 NaN → dumps → parse 得回同一对象
    case = CASES[case_id]
    if case["tool"] == "_time" or "error" in case["expected"]:
        return
    result = _run_tool(case["tool"], case["input"])
    text = canonical.dumps(result)
    assert canonical.loads(text) == result, case_id
    assert "\\u" not in text.replace("\\\\u", ""), case_id  # ensure_ascii=False：中文不转义


# ==================================================================
# §3 规则目录三向一致（basis ↔ thresholds ↔ 模块常量，逐 code）
# ==================================================================

def _check_code(code):
    rule = BASIS.rule(code)
    assert rule is not None, "%s 不在 basis 里" % code
    assert rule.version == "1"
    assert rule.text, "%s 模板为空" % code
    record = _catalog().codes(code)
    assert record["template"] == rule.text
    assert record["meaning"] == rule.title
    assert record["meaning"], "%s 缺 meaning" % code
    assert record["spec_ref"], "%s 缺 spec_ref" % code
    # CORS 族的 spec_ref 是 "Fetch section …" 形态，cache/cond/vary 是 "RFC…" 形态
    assert all(isinstance(ref, str) and ref for ref in record["spec_ref"]), "%s spec_ref 形态" % code
    assert record["severity"] == SETTINGS["severity"][code]
    assert record["severity"] == default_settings.SEVERITY[code]
    assert record["severity"] in ("decisive", "informational")


def test_basis_cache_age_exceeds_lifetime():
    _check_code("CACHE_AGE_EXCEEDS_LIFETIME")


def test_basis_cache_expires_in_past():
    _check_code("CACHE_EXPIRES_IN_PAST")


def test_basis_cache_heuristic_freshness():
    _check_code("CACHE_HEURISTIC_FRESHNESS")


def test_basis_cache_invalid_age():
    _check_code("CACHE_INVALID_AGE")


def test_basis_cache_invalid_max_age():
    _check_code("CACHE_INVALID_MAX_AGE")


def test_basis_cache_max_age_zero():
    _check_code("CACHE_MAX_AGE_ZERO")


def test_basis_cache_must_revalidate_stale():
    _check_code("CACHE_MUST_REVALIDATE_STALE")


def test_basis_cache_no_cache():
    _check_code("CACHE_NO_CACHE")


def test_basis_cache_no_store():
    _check_code("CACHE_NO_STORE")


def test_basis_cache_stale_while_revalidate():
    _check_code("CACHE_STALE_WHILE_REVALIDATE")


def test_basis_cond_if_match_failed():
    _check_code("COND_IF_MATCH_FAILED")


def test_basis_cond_if_modified_since_not_modified():
    _check_code("COND_IF_MODIFIED_SINCE_NOT_MODIFIED")


def test_basis_cond_if_none_match_matched():
    _check_code("COND_IF_NONE_MATCH_MATCHED")


def test_basis_cond_if_unmodified_since_failed():
    _check_code("COND_IF_UNMODIFIED_SINCE_FAILED")


def test_basis_cond_ignored_invalid_date():
    _check_code("COND_IGNORED_INVALID_DATE")


def test_basis_cond_weak_comparison_used():
    _check_code("COND_WEAK_COMPARISON_USED")


def test_basis_cors_disallowed_header_not_exposed():
    _check_code("CORS_DISALLOWED_HEADER_NOT_EXPOSED")


def test_basis_cors_missing_allow_credentials():
    _check_code("CORS_MISSING_ALLOW_CREDENTIALS")


def test_basis_cors_missing_allow_headers():
    _check_code("CORS_MISSING_ALLOW_HEADERS")


def test_basis_cors_missing_allow_methods():
    _check_code("CORS_MISSING_ALLOW_METHODS")


def test_basis_cors_missing_allow_origin():
    _check_code("CORS_MISSING_ALLOW_ORIGIN")


def test_basis_cors_mode_opaque():
    _check_code("CORS_MODE_OPAQUE")


def test_basis_cors_null_origin():
    _check_code("CORS_NULL_ORIGIN")


def test_basis_cors_origin_mismatch():
    _check_code("CORS_ORIGIN_MISMATCH")


def test_basis_cors_preflight_required():
    _check_code("CORS_PREFLIGHT_REQUIRED")


def test_basis_cors_redirect_not_same_origin():
    _check_code("CORS_REDIRECT_NOT_SAME_ORIGIN")


def test_basis_cors_wildcard_with_credentials():
    _check_code("CORS_WILDCARD_WITH_CREDENTIALS")


def test_basis_vary_duplicate_field():
    _check_code("VARY_DUPLICATE_FIELD")


def test_basis_vary_field_mismatch():
    _check_code("VARY_FIELD_MISMATCH")


def test_basis_vary_field_missing():
    _check_code("VARY_FIELD_MISSING")


def test_basis_vary_star_never_matches():
    _check_code("VARY_STAR_NEVER_MATCHES")


@pytest.mark.parametrize("code", sorted(default_settings.SEVERITY))
def test_thresholds_severity_table_matches_module(code):
    assert SETTINGS["severity"][code] == default_settings.SEVERITY[code]


def test_basis_rule_count_matches_catalogue():
    # 31 条目录规则 + 1 条 hs-summary，双向集合相等（多一条少一条都红）
    assert len(BASIS) == 32
    assert set(BASIS.rule_ids()) == set(default_settings.SEVERITY) | {"hs-summary"}
    assert set(SETTINGS["severity"]) == set(default_settings.SEVERITY)
    assert BASIS.rule("hs-summary") is not None


# ==================================================================
# §4 规范化 / 解析 / 比较函数的单元面（旧仓判定层的可独立断言函数）
# ==================================================================

def test_normalise_header_name_lowercases_and_trims():
    assert normalise.normalise_header_name("  Content-Type ", "f") == "content-type"


def test_normalise_header_name_rejects_non_token():
    with pytest.raises(hs_errors.JudgementError) as e:
        normalise.normalise_header_name("bad name", "f")
    assert e.value.code == "INVALID_HEADER_NAME"


def test_normalise_header_name_rejects_non_string():
    with pytest.raises(hs_errors.JudgementError) as e:
        normalise.normalise_header_name(42, "f")
    assert e.value.code == "INVALID_HEADER_NAME"


def test_normalise_headers_merges_case_insensitively():
    # 名按 sorted 序合并（名的顺序不可观测——消费方全走 first_value/排序视图），值序保留
    merged = normalise.normalise_headers({"Accept": "a", "ACCEPT": ["b", "c"]}, "f")
    assert merged == {"accept": ["b", "c", "a"]}


def test_normalise_headers_rejects_non_string_value():
    with pytest.raises(hs_errors.JudgementError) as e:
        normalise.normalise_headers({"x": [1]}, "f")
    assert e.value.code == "INVALID_INPUT"


def test_normalise_headers_none_is_empty():
    assert normalise.normalise_headers(None, "f") == {}


def test_normalise_method_uppercases_and_accepts_set():
    assert normalise.normalise_method(" get ") == "GET"


def test_normalise_method_rejects_unknown():
    with pytest.raises(hs_errors.JudgementError) as e:
        normalise.normalise_method("TEST-METHOD")
    assert e.value.code == "UNSUPPORTED_METHOD"


def test_serialise_origin_drops_default_port():
    assert normalise.serialise_origin("https://api.example.com/") == "https://api.example.com"


def test_serialise_origin_keeps_nondefault_port_and_strips_path():
    assert normalise.serialise_origin("http://api.example.com:8443/x?y=1#z") == "http://api.example.com:8443"


def test_serialise_origin_rejects_bad_scheme_and_port():
    with pytest.raises(hs_errors.JudgementError):
        normalise.serialise_origin("ftp://h")
    with pytest.raises(hs_errors.JudgementError):
        normalise.serialise_origin("http://h:99999")


def test_origin_key_null_literal_and_none():
    assert normalise.origin_key(None) is None
    assert normalise.origin_key("NULL") == "null"
    assert normalise.origin_key("https://h") == "https://h"


def test_origin_key_rejects_garbage():
    with pytest.raises(hs_errors.JudgementError) as e:
        normalise.origin_key("not-a-url")
    assert e.value.code == "INVALID_INPUT"


def test_split_comma_list_trims_and_skips_empties():
    assert normalise.split_comma_list(["a, b ,, c"]) == ["a", "b", "c"]


def test_first_value_trims_ows():
    headers = normalise.normalise_headers({"x": "  v  "}, "f")
    assert normalise.first_value(headers, "x") == "v"
    assert normalise.first_value(headers, "absent") is None


def test_header_name_list_dedupes_and_sorts():
    assert normalise.header_name_list(["B", "a", "b", ""]) == ["a", "b"]


def test_sha256_prefix_is_deterministic():
    assert normalise.sha256_prefix("x\ny", 16) == normalise.sha256_prefix("x\ny", 16)
    assert len(normalise.sha256_prefix("x", 16)) == 16


def test_timeparse_leap_year_feb29():
    form, ts = timeparse.parse_time("2024-02-29T00:00:00Z", "f")
    assert form == "iso8601"


def test_timeparse_non_leap_feb29_rejected():
    with pytest.raises(hs_errors.JudgementError):
        timeparse.parse_time("2023-02-29T00:00:00Z", "f")


def test_timeparse_leap_second_folds_to_minute_end():
    # :60 容忍并折叠到分钟最后一秒：:60 与 :59 是同一时刻
    _, a = timeparse.parse_time("2026-01-01T00:00:60Z", "f")
    _, b = timeparse.parse_time("2026-01-01T00:00:59Z", "f")
    assert a == b


def test_timeparse_weekday_name_from_day_count():
    # 1970-01-01 was a Thursday（表旋转锚）
    form, ts = timeparse.parse_time("Thu, 01 Jan 1970 00:00:00 GMT", "f")
    assert form == "http-date" and ts == 0


def test_timeparse_month_names_table():
    # 2026-01-01 是周四、2026-12-01 是周二（星期必须与日期一致）
    form, _ = timeparse.parse_time("Thu, 01 Jan 2026 00:00:00 GMT", "f")
    assert form == "http-date"
    form2, _ = timeparse.parse_time("Tue, 01 Dec 2026 00:00:00 GMT", "f")
    assert form2 == "http-date"


def test_timeparse_rejects_out_of_range_fields():
    for value in ("2026-13-01T00:00:00Z", "2026-01-32T00:00:00Z", "2026-01-01T24:00:00Z"):
        with pytest.raises(hs_errors.JudgementError):
            timeparse.parse_time(value, "f")


def test_error_payload_shape_is_fixed():
    payload = hs_errors.invalid_input("f", "d").payload()
    assert payload == {"error": {"code": "INVALID_INPUT", "field": "f", "detail": "d"}}


def test_error_codes_are_the_frozen_five():
    assert hs_errors.ERROR_CODES == ("INVALID_INPUT", "INVALID_TIME_FORMAT",
                                     "INVALID_HEADER_NAME", "INVALID_HEADER_VALUE",
                                     "UNSUPPORTED_METHOD")


def test_error_unknown_code_rejected():
    with pytest.raises(ValueError):
        hs_errors.JudgementError("NOT_A_CODE", "f", "d")


def test_error_invalid_time_detail_template():
    e = hs_errors.invalid_time_format("now", "tomorrow")
    assert e.detail == "expected YYYY-MM-DDTHH:MM:SSZ or an HTTP-date, got 'tomorrow'"


def test_error_is_valueerror_for_cli_mapping():
    assert issubclass(hs_errors.JudgementError, ValueError)


def test_conditional_strong_compare_requires_both_strong():
    left = {"weak": False, "tag": '"a"'}
    assert conditional.strong_compare(left, {"weak": False, "tag": '"a"'}) is True
    assert conditional.strong_compare(left, {"weak": True, "tag": '"a"'}) is False
    assert conditional.strong_compare(left, {"weak": False, "tag": '"b"'}) is False


def test_conditional_weak_compare_ignores_marker():
    assert conditional.weak_compare({"weak": True, "tag": '"a"'}, {"weak": False, "tag": '"a"'}) is True


def test_conditional_parse_entity_tag_keeps_quotes():
    parsed = conditional.parse_entity_tag('"abc"', "f")
    assert parsed == {"weak": False, "tag": '"abc"'}


def test_conditional_parse_entity_tag_weak_marker():
    assert conditional.parse_entity_tag('W/"abc"', "f") == {"weak": True, "tag": '"abc"'}


def test_conditional_parse_entity_tag_lowercase_weak_is_error():
    with pytest.raises(hs_errors.JudgementError) as e:
        conditional.parse_entity_tag('w/"abc"', "f")
    assert e.value.code == "INVALID_HEADER_VALUE"


def test_conditional_parse_entity_tag_rejects_unquoted_and_inner_quote():
    for raw in ("abc", '"abc', '""a""'):
        with pytest.raises(hs_errors.JudgementError):
            conditional.parse_entity_tag(raw, "f")


def test_conditional_parse_condition_value_wildcard_only_as_whole_value():
    assert conditional.parse_condition_value("*", "f") == (True, [])
    tags = conditional.parse_condition_value('"a", "b"', "f")
    assert tags == (False, [{"weak": False, "tag": '"a"'}, {"weak": False, "tag": '"b"'}])


def test_conditional_parse_condition_value_inner_star_rejected():
    with pytest.raises(hs_errors.JudgementError):
        conditional.parse_condition_value('"a", *', "f")


def test_conditional_read_resource_validates_up_front():
    with pytest.raises(hs_errors.JudgementError):
        conditional._read_resource({"resource": {"last_modified": "not a date"}})


def test_cors_unsafe_request_headers_authorization_never_safelisted():
    headers = normalise.normalise_headers({"Authorization": "x"}, "f")
    assert cors.unsafe_request_headers(headers) == ["authorization"]


def test_cors_unsafe_request_headers_value_gated():
    safe = normalise.normalise_headers({"Accept": "text/plain"}, "f")
    assert cors.unsafe_request_headers(safe) == []
    unsafe = normalise.normalise_headers({"Accept": 'a"b'}, "f")
    assert cors.unsafe_request_headers(unsafe) == ["accept"]


def test_cors_safelisted_content_type_essence_only():
    headers = normalise.normalise_headers(
        {"Content-Type": "text/plain; charset=utf-8"}, "f")
    assert cors.unsafe_request_headers(headers) == []
    headers2 = normalise.normalise_headers({"Content-Type": "application/json"}, "f")
    assert cors.unsafe_request_headers(headers2) == ["content-type"]


def test_cors_simple_range_check():
    headers = normalise.normalise_headers({"Range": "bytes=0-99"}, "f")
    assert cors.unsafe_request_headers(headers) == []
    headers2 = normalise.normalise_headers({"Range": "bytes=99-0"}, "f")
    assert cors.unsafe_request_headers(headers2) == ["range"]
    headers3 = normalise.normalise_headers({"Range": "bytes=0-1,5-6"}, "f")
    assert cors.unsafe_request_headers(headers3) == ["range"]


def test_cors_language_value_byte_range():
    headers = normalise.normalise_headers({"Accept-Language": "en-US, en;q=0.9"}, "f")
    assert cors.unsafe_request_headers(headers) == []
    headers2 = normalise.normalise_headers({"Accept-Language": "en_US"}, "f")
    assert cors.unsafe_request_headers(headers2) == ["accept-language"]


def test_cors_needs_preflight_by_method_and_headers():
    assert cors.needs_preflight("DELETE", {}) is True
    assert cors.needs_preflight("GET", {}) is False
    assert cors.needs_preflight("GET", normalise.normalise_headers({"x-custom": "1"}, "f")) is True


def test_cors_notes_always_present():
    # 三个键恒出现（字段时有时无无法被逐字节比对钉住）
    result = _run_tool("cors_evaluate", {
        "method": "GET", "url": "https://api.example.com", "origin": "https://web.example.com",
        "is_preflight": False,
        "response": {"status": 200, "headers": {"Access-Control-Allow-Origin": "https://web.example.com"}},
    })
    assert set(result["notes"]) == {"wildcard_with_credentials", "allow_credentials_null_origin",
                                    "max_age_capped_by_client"}


def test_cache_split_directives_respects_quotes():
    values = ['no-cache="set-cookie, x-foo"']
    headers = {"cache-control": values}
    directives = cache.parse_directives(headers)
    assert directives == {"no-cache": "set-cookie, x-foo"}


def test_cache_parse_directives_first_wins_and_quotes_stripped():
    directives = cache.parse_directives({"cache-control": ['max-age="60"', "max-age=1"]})
    assert directives == {"max-age": "60"}


def test_cache_parse_directives_bare_directive_is_true():
    assert cache.parse_directives({"cache-control": ["no-store"]}) == {"no-store": True}


def test_cache_delta_seconds_bare_is_invalid_not_zero():
    assert cache._delta_seconds(True) is None
    assert cache._delta_seconds("10.5") is None
    assert cache._delta_seconds("-1") is None
    assert cache._delta_seconds("60") == 60


def test_cache_no_store_short_circuits():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "no-store, max-age=60",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z", "age": "10"},
    })
    assert result["action"] == "miss"
    assert result["current_age"] == 0


def test_cache_freshness_priority_smaxage_over_maxage():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "s-maxage=120, max-age=10",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["freshness_lifetime"] == 120


def test_cache_invalid_max_age_falls_through_to_expires():
    # malformed max-age 记 informational 后落 Expires，不整体失败
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "max-age=abc",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT",
                             "Expires": "Thu, 01 Jan 2026 01:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["freshness_lifetime"] == 3600
    assert result["is_fresh"] is True


def test_cache_stale_is_strict_less():
    # current_age == freshness_lifetime 是 stale（plan/03 §3.2）：
    # apparent=10、age=10 → corrected=10，resident=now−stored_at=50 → current_age=60 == 60
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:01:00Z",
        "response_headers": {"Cache-Control": "max-age=60",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z", "age": "10"},
    })
    assert result["current_age"] == result["freshness_lifetime"] == 60
    assert result["is_fresh"] is False


def test_cache_heuristic_caps_at_24h():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Date": "Thu, 01 Jan 2026 00:00:00 GMT",
                             "Last-Modified": "Mon, 01 Jan 2001 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["freshness_lifetime"] == spec.MAX_HEURISTIC_SECONDS


def test_vary_members_dedupe_sort_and_first_repeat():
    members, repeat = vary._members("accept, User-Agent, ACCEPT")
    assert members == ["accept", "user-agent"]
    assert repeat == "accept"


def test_vary_members_accepts_list_and_rejects_garbage():
    assert vary._members(["accept", "user-agent"])[0] == ["accept", "user-agent"]
    with pytest.raises(hs_errors.JudgementError):
        vary._members(42)


def test_vary_wildcard_decides_before_field_comparison():
    result = _run_tool("vary_match", {
        "cached": {"vary": "*",
                   "request_headers_at_store": {"Accept": "a"}},
        "incoming": {"request_headers": {"Accept": "a"}},
    })
    assert result["match"] == "miss"
    assert result["differing_headers"] == []


def test_vary_absent_and_empty_report_differently():
    # 只有一侧携带的字段仍是 VARY_FIELD_MISSING；"absent" 与 "present but empty"
    # 归一同值 → 只报缺失、值不判差（differing 空 → match=hit）
    result = _run_tool("vary_match", {
        "cached": {"vary": "accept", "request_headers_at_store": {}},
        "incoming": {"request_headers": {"Accept": ""}},
    })
    assert result["match"] == "hit"
    assert result["differing_headers"] == []
    codes = [f["code"] for f in result["reasons"]]
    assert codes == ["VARY_FIELD_MISSING"]


def test_vary_normalise_value_policy_matrix():
    policy = {"trim": True, "fold_whitespace": True, "case_sensitive": False, "sort_comma_segments": False}
    assert vary.normalise_vary_value("  A  B ", policy) == "a b"
    policy_sort = dict(policy, sort_comma_segments=True)
    assert vary.normalise_vary_value("b, a", policy_sort) == "a,b"
    policy_case = dict(policy, case_sensitive=True)
    assert vary.normalise_vary_value("A", policy_case) == "A"


def test_vary_policy_is_data_not_branch():
    # 策略表是数据：user-agent 不折叠空白（真实 CATALOG 值）
    ua = default_settings.VARY_NORMALIZATION["fields"]["user-agent"]
    assert ua == {"case_sensitive": True, "fold_whitespace": False,
                  "sort_comma_segments": False, "trim": True}


def test_fetch_max_age_never_capped():
    headers = normalise.normalise_headers({"Access-Control-Max-Age": "999999"}, "f")
    assert fetch_sim._max_age(headers) == 999999
    assert fetch_sim._max_age(normalise.normalise_headers({}, "f")) == 0


def test_fetch_visible_headers_by_mode():
    headers = normalise.normalise_headers({"x-private": "1", "Access-Control-Expose-Headers": "x-open"}, "f")
    assert fetch_sim._visible_headers("no-cors", headers, "omit") == []
    assert fetch_sim._visible_headers("same-origin", headers, "omit") == ["access-control-expose-headers", "x-private"]
    assert fetch_sim._visible_headers("cors", headers, "omit") == ["access-control-expose-headers", "x-open", "x-private"]


def test_fetch_wildcard_expose_with_credentials_exposes_nothing():
    # include 时通配不再暴露任何**额外**头；响应自身头名仍在可见列表里（旧仓同构）
    headers = normalise.normalise_headers({"Access-Control-Expose-Headers": "*"}, "f")
    assert fetch_sim._visible_headers("cors", headers, "include") == ["access-control-expose-headers"]
    # header_name_list 排序："*" 排在 "a…" 前
    assert fetch_sim._visible_headers("cors", headers, "omit") == ["*", "access-control-expose-headers"]


def test_fetch_events_order_is_fixed():
    # events[] 保序且从不排序：origin_set_to_null 先、credentials_dropped 后
    result = _run_tool("cors_simulate_fetch", {
        "method": "GET", "url": "https://a.example.com", "origin": "https://a.example.com",
        "credentials": "include", "mode": "cors", "is_preflight": False,
        "response": {"status": 200, "headers": {"Access-Control-Allow-Origin": "*"}},
        "redirects": [{"status": 302, "url": "https://b.example.com", "headers": {}}],
    })
    assert result["events"] == ["origin_set_to_null", "credentials_dropped"]


def test_fetch_redirect_hops_carry_requested_url_in_order():
    result = _run_tool("cors_simulate_fetch", {
        "method": "GET", "url": "https://a.example.com", "origin": None,
        "credentials": "omit", "mode": "cors", "is_preflight": False,
        "response": {"status": 200, "headers": {"Access-Control-Allow-Origin": "*"}},
        "redirects": [{"status": 301, "url": "https://b.example.com", "headers": {}}],
    })
    assert [h["url"] for h in result["hops"]] == ["https://a.example.com", "https://b.example.com"]
    assert result["final_type"] == "cors"


# ==================================================================
# §5 账本化 / 退出码 / subject 校验 / 宿主 CLI
# ==================================================================

def test_ledger_golden_result_stored_in_summary():
    # 工具结果整体进 hs-summary 的 evidence.result，golden 对撞按它逐字节比对
    records = _evaluate(_subject("cache_evaluate", CASES["cache-001-fresh"]["input"]))
    assert _result_of(records) == CASES["cache-001-fresh"]["expected"]


def test_ledger_decisive_findings_are_errors():
    # cache-002 的 decisive finding（CACHE_AGE_EXCEEDS_LIFETIME）→ error 阻断
    records = _evaluate(_subject("cache_evaluate", CASES["cache-002-age-exceeds-lifetime"]["input"]))
    errors = [r for r in records if r.verdict == ERROR]
    assert any(r.rule_id == "CACHE_AGE_EXCEEDS_LIFETIME" for r in errors)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_ledger_informational_findings_are_info():
    # cache-012 只有 informational（invalid max-age）→ 全 info，rc 0
    records = _evaluate(_subject("cache_evaluate", CASES["cache-012-invalid-max-age"]["input"]))
    assert all(r.verdict == INFO for r in records if r.rule_id != "hs-summary")
    assert _report(records).exit_code() == EXIT_OK


def test_ledger_record_ids_unique_on_same_path():
    # 同一 path 上同 code 多条时 #n 消歧（账本 id 唯一契约）
    subject = _subject("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "max-age=abc, s-maxage=xyz",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT",
                             "Expires": "Thu, 01 Jan 2026 01:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    records = _evaluate(subject)
    ids = [r.id for r in records]
    assert len(ids) == len(set(ids))


def test_ledger_records_carry_spec_ref_and_severity():
    records = _evaluate(_subject("cache_evaluate", CASES["cache-002-age-exceeds-lifetime"]["input"]))
    rec = [r for r in records if r.rule_id == "CACHE_AGE_EXCEEDS_LIFETIME"][0]
    assert rec.evidence["spec_ref"] == ["RFC9111 §4.2", "RFC9111 §4.2.3"]
    assert rec.evidence["severity"] == "decisive"
    assert rec.basis.rule_id == "CACHE_AGE_EXCEEDS_LIFETIME"
    assert rec.basis.rule_version == "1"


def test_ledger_fetch_hop_path_is_hop_url():
    records = _evaluate(_subject("cors_simulate_fetch", CASES["cors-sim-005-same-origin-mode-blocked"]["input"]))
    blocked = [r for r in records if r.verdict == ERROR]
    assert blocked and all(r.path.startswith("hop[") for r in blocked)


def test_subject_mode_unknown_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject("no_such_tool", {}))


def test_subject_arguments_not_dict_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "cache_evaluate", "arguments": []})


def test_subject_thresholds_not_dict_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "cache_evaluate", "arguments": {}, "thresholds": []})


def test_subject_mode_missing_defaults_to_cache_evaluate():
    records = _evaluate({"arguments": CASES["cache-001-fresh"]["input"]})
    assert _summary(records).evidence["mode"] == "cache_evaluate"


def test_cli_check_sample_rc0():
    # README 手算示例（cache-001 同参）：新入口 rc 0，无阻断
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)])
    assert rc == EXIT_OK


def test_cli_check_sample_without_basis_rc0():
    # 随包 basis 缺省可用
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE)])
    assert rc == EXIT_OK


def test_cli_check_decisive_rc1():
    tmp = ROOT / ".tmp-hs-problem.json"
    subject = _subject("cache_evaluate", CASES["cache-002-age-exceeds-lifetime"]["input"])
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_BLOCKED


def test_cli_check_caller_mistake_rc2():
    # caller mistake（坏时间）：旧 MCP 渲染 isError（rc0）→ 新 rc2 输入不合法（口径差）
    tmp = ROOT / ".tmp-hs-badtime.json"
    subject = _subject("cache_evaluate", dict(CASES["cache-001-fresh"]["input"], now="tomorrow"))
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_INPUT


def test_cli_check_empty_basis_contract_rc3():
    tmp_in = ROOT / ".tmp-hs-ok.json"
    tmp_basis = ROOT / ".tmp-hs-empty-basis.json"
    tmp_in.write_text(json.dumps(_subject("cache_evaluate", CASES["cache-001-fresh"]["input"])), encoding="utf-8")
    tmp_basis.write_text(json.dumps({"version": "0", "rules": []}), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp_in), "--basis", str(tmp_basis)])
    finally:
        tmp_in.unlink()
        tmp_basis.unlink()
    assert rc == EXIT_CONTRACT


def test_cli_list_includes_http_semantics():
    load_builtin()
    from byteproof.core.registry import all_packs
    assert SLUG in [p.slug for p in all_packs()]


def test_builtin_modules_sorted_and_count_20():
    assert "http_semantics" in BUILTIN_MODULES
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(BUILTIN_MODULES) == 20


def test_pack_registered_contract_fields():
    load_builtin()
    pack = get(SLUG)
    assert pack.slug == SLUG
    assert pack.version == spec.ORGAN_VERSION == "1"
    assert pack.input_fields == ("mode",)


def test_determinism_double_run_byte_identical():
    # 每工具一例（同输入两次 → 逐字节一致；旧仓 test_determinism 的器官内移植面）
    probes = {
        "cache_evaluate": CASES["cache-001-fresh"]["input"],
        "conditional_evaluate": CASES["cond-002-if-match-pass"]["input"],
        "cors_evaluate": CASES["cors-eval-001-basic-allow"]["input"],
        "cors_simulate_fetch": CASES["cors-sim-002-cross-origin-credentials-dropped"]["input"],
        "vary_match": CASES["vary-001-hit-single"]["input"],
    }
    for tool, arguments in probes.items():
        a = canonical.dumps(_run_tool(tool, arguments))
        b = canonical.dumps(_run_tool(tool, arguments))
        assert a == b, tool


def test_summary_record_counts_modes():
    records = _evaluate(_subject("vary_match", CASES["vary-001-hit-single"]["input"]))
    s = _summary(records).evidence
    assert s["mode"] == "vary_match"
    assert s["records"] == len(records) - 1
    assert s["error"] + s["info"] == s["records"]


def test_summary_error_info_match_verdicts():
    records = _evaluate(_subject("cache_evaluate", CASES["cache-002-age-exceeds-lifetime"]["input"]))
    s = _summary(records).evidence
    assert s["error"] == sum(1 for r in records if r.verdict == ERROR and r.rule_id != "hs-summary")


# ==================================================================
# §6 纯度 / 架构（旧仓 gates 判定层的器官内移植面：tokenize 去注释/字符串后判码）
# ==================================================================

def _organ_sources():
    organ_dir = SRC / "byteproof" / "auditors" / "http_semantics"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(organ_dir.glob("*.py"))}


def _code_only(text):
    """tokenize 去掉注释与字符串字面量（docstring 提及 ≠ 代码使用，同旧仓 stripComments 纪律）。"""
    import io
    import tokenize

    pieces = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            pieces.append(tok.string)
    return " ".join(pieces)


def test_judgement_layer_no_io_clock_or_random():
    pattern = re.compile(r"\bopen\b|\bos\.environ\b|\btime\.time\b|\bdatetime\b|\bcalendar\b"
                         r"|\brandom\b|\bsocket\b|\burllib\b|\bsubprocess\b")
    for name, text in _organ_sources().items():
        code = _code_only(text)
        hit = pattern.search(code)
        assert hit is None, "%s 含禁用记号 %s" % (name, hit.group(0) if hit else "")


def test_judgement_layer_no_print_or_file_writes():
    pattern = re.compile(r"\bprint\b|\binput\b|write_text|\.write\b|\.write_text\b")
    for name, text in _organ_sources().items():
        code = _code_only(text)
        hit = pattern.search(code)
        assert hit is None, "%s 含输出/输入面记号 %s" % (name, hit.group(0) if hit else "")


def test_modules_only_stdlib_or_internal_imports():
    allowed = ("json", "re", "hashlib", "typing", "byteproof", "__future__", "")
    organ_dir = SRC / "byteproof" / "auditors" / "http_semantics"
    for path in sorted(organ_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed, "%s: 未知导入 %s" % (path.name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0] if not node.level else ""
                assert root in allowed, "%s: 未知导入 %s" % (path.name, node.module)


def test_spec_constants_match_thresholds_snapshot():
    assert spec.MODES == (
        "cache_evaluate", "conditional_evaluate", "cors_evaluate",
        "cors_simulate_fetch", "vary_match",
    )
    assert list(spec.METHOD_NAMES) == SETTINGS["methods"]
    assert list(spec.REDIRECT_STATUSES) == SETTINGS["redirect_statuses"]
    assert spec.FETCH_MODES == tuple(SETTINGS["modes"])
    assert spec.FINAL_TYPES == SETTINGS["final_types"]
    # error_codes 集合相等（顺序不是契约：模块侧是 errors.py 的冻结元组，快照侧是 CATALOG 键序）
    assert set(default_settings.ERROR_CODES) == set(SETTINGS["error_codes"])
    assert default_settings.PREFLIGHT_CACHE_KEY == SETTINGS["preflight_cache_key"]
    assert default_settings.VARY_NORMALIZATION == SETTINGS["vary_normalization"]


# ==================================================================
# §7 序列化 / 依据包 / 契约面
# ==================================================================

def test_canonical_dumps_sorts_keys_and_stays_ascii_off():
    text = canonical.dumps({"b": 1, "a": {"中": 2}})
    assert text == '{"a":{"中":2},"b":1}'


def test_canonical_dumps_rejects_nan():
    # allow_nan=False：json.dumps 对 NaN 抛 ValueError；loads 的 parse_constant 抛 NonFiniteNumber
    with pytest.raises(ValueError):
        canonical.dumps({"x": float("nan")})


def test_canonical_loads_rejects_nan_constant():
    with pytest.raises(canonical.NonFiniteNumber):
        canonical.loads('{"x": NaN}')


def test_basis_version_is_1():
    assert BASIS.version == "1"


def test_catalogue_missing_rule_raises_rule_missing():
    with pytest.raises(Exception) as e:
        _catalog(Basis.empty("0")).codes("CACHE_NO_STORE")
    assert type(e.value).__name__ == "RuleMissing"


def test_catalogue_finding_formats_template():
    f = _catalog().finding("CACHE_AGE_EXCEEDS_LIFETIME", current_age=30, freshness_lifetime=10)
    assert f["detail"] == "current_age=30 is not below freshness_lifetime=10"
    assert f["spec_ref"] == ["RFC9111 §4.2", "RFC9111 §4.2.3"]


def test_modes_are_exactly_five_tools():
    assert spec.MODES == ("cache_evaluate", "conditional_evaluate", "cors_evaluate",
                          "cors_simulate_fetch", "vary_match")


# ==================================================================
# §8 判定层内部函数的补面（旧仓可独立断言的内部分支逐条落位）
# ==================================================================

def test_cors_method_is_allowed_declared_or_safelisted():
    assert cors._method_is_allowed(["PATCH"], "PATCH", "omit") is True
    assert cors._method_is_allowed([], "GET", "include") is True


def test_cors_method_is_allowed_wildcard_needs_no_credentials():
    assert cors._method_is_allowed(["*"], "DELETE", "omit") is True
    assert cors._method_is_allowed(["*"], "DELETE", "include") is False


def test_cors_header_is_allowed_declared_case_insensitive():
    assert cors._header_is_allowed(["X-Custom"], "x-custom", "omit") is True


def test_cors_header_is_allowed_authorization_never_wildcard():
    assert cors._header_is_allowed(["*"], "authorization", "omit") is False
    assert cors._header_is_allowed(["authorization"], "authorization", "omit") is True


def test_cors_header_is_allowed_wildcard_with_credentials_covers_nothing():
    assert cors._header_is_allowed(["*"], "x-any", "include") is False
    assert cors._header_is_allowed(["*"], "x-any", "omit") is True


def test_cors_is_simple_range_direct():
    assert cors._is_simple_range("bytes=0-100") is True
    assert cors._is_simple_range("bytes=100-100") is True
    assert cors._is_simple_range("bytes=100-0") is False


def test_cors_has_unsafe_byte_separators():
    assert cors._has_unsafe_byte("ok") is False
    assert cors._has_unsafe_byte('a"b') is True
    assert cors._has_unsafe_byte("a\x01b") is True
    assert cors._has_unsafe_byte("a\tb") is False  # HTAB 豁免


def test_cors_allow_origin_reader():
    headers = normalise.normalise_headers({"Access-Control-Allow-Origin": " https://h "}, "f")
    assert cors._allow_origin(headers) == "https://h"
    assert cors._allow_origin({}) is None


def test_cors_credentials_true_reader():
    assert cors._credentials_true(normalise.normalise_headers(
        {"Access-Control-Allow-Credentials": "true"}, "f")) is True
    assert cors._credentials_true(normalise.normalise_headers(
        {"Access-Control-Allow-Credentials": "TRUE"}, "f")) is False  # 精确小写 true 才算


def test_conditional_if_match_holds_wildcard_needs_etag():
    assert conditional._if_match_holds(True, [], None) is False
    assert conditional._if_match_holds(True, [], {"weak": False, "tag": '"x"'}) is True


def test_conditional_if_match_holds_strong_only():
    etag = {"weak": False, "tag": '"x"'}
    assert conditional._if_match_holds(False, [{"weak": False, "tag": '"x"'}], etag) is True
    assert conditional._if_match_holds(False, [{"weak": True, "tag": '"x"'}], etag) is False


def test_conditional_if_none_match_holds_weak():
    etag = {"weak": True, "tag": '"x"'}
    assert conditional._if_none_match_holds(False, [{"weak": False, "tag": '"x"'}], etag) is True
    assert conditional._if_none_match_holds(False, [{"weak": False, "tag": '"y"'}], etag) is False


def test_conditional_header_date_records_ignore_not_epoch():
    findings = []
    got = conditional._header_date("not a date", "if-modified-since", findings, _catalog())
    assert got is None  # None = 该条件不评（不是"日期是 epoch"）
    assert [f["code"] for f in findings] == ["COND_IGNORED_INVALID_DATE"]
    assert findings[0]["detail"] == "if-modified-since is not a valid HTTP-date and was ignored"


def test_conditional_result_shape():
    result = conditional._result("if_match", 412, [], False)
    assert result == {"explain": [], "rule_applied": "if_match", "status": 412,
                      "weak_comparison_used": False}


def test_conditional_empty_if_match_value_has_no_tags():
    assert conditional.parse_condition_value("", "f") == (False, [])


def test_conditional_post_to_if_none_match_is_412():
    # 非 GET/HEAD 上 If-None-Match 命中 → 412（不是 304）
    result = _run_tool("conditional_evaluate", {
        "method": "POST",
        "request_headers": {"If-None-Match": '"e1"'},
        "resource": {"etag": '"e1"'},
    })
    assert result["status"] == 412


def test_conditional_if_modified_since_ignored_for_non_safe_methods():
    result = _run_tool("conditional_evaluate", {
        "method": "DELETE",
        "request_headers": {"If-Modified-Since": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "resource": {"last_modified": "2026-01-01T00:00:00Z"},
    })
    assert result["rule_applied"] == "none"
    assert result["status"] == 200


def test_conditional_bad_resource_field_is_tool_error():
    # 资源字段是 caller 提供的元数据 → 坏值是工具错误（与坏请求日期"忽略"相对）
    with pytest.raises(hs_errors.JudgementError) as e:
        _run_tool("conditional_evaluate", {
            "method": "GET", "request_headers": {},
            "resource": {"etag": "unquoted"},
        })
    assert e.value.code == "INVALID_HEADER_VALUE"


def test_cache_freshness_invalid_smaxage_falls_to_valid_maxage():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "s-maxage=abc, max-age=45",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["freshness_lifetime"] == 45


def test_cache_expires_in_past_quotes_stored_at_when_date_missing():
    # Date 缺失时 CACHE_EXPIRES_IN_PAST 引 stored_at 字面量（旧仓同款回退）；
    # reasons 是 (code, detail) 排序的，按 code 找该条
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Expires": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["freshness_lifetime"] == 0
    detail = [f["detail"] for f in result["reasons"] if f["code"] == "CACHE_EXPIRES_IN_PAST"][0]
    assert "Date=2026-01-01T00:00:10Z" in detail


def test_cache_age_header_fallback_when_stored_age_absent():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "max-age=60",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT",
                             "Age": "20"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["current_age"] == 40  # corrected_initial_age=20 + resident=20


def test_cache_invalid_age_falls_back_to_zero():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "max-age=60",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z", "age": "ten"},
    })
    # invalid age 记 informational 后按 0：corrected = max(apparent 10, 0) = 10 + resident 20
    assert result["current_age"] == 30
    assert any(f["code"] == "CACHE_INVALID_AGE" for f in result["reasons"])


def test_cache_swr_window_open_serves_stale():
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:01:05Z",
        "response_headers": {"Cache-Control": "max-age=60, stale-while-revalidate=30",
                             "Date": "Thu, 01 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z", "age": "10"},
    })
    # current_age = 65, 超窗 5 ≤ 30 → serve（SWR finding）
    assert result["action"] == "serve"
    assert result["stale_while_revalidate_window"] == 30


def test_cache_apparent_age_never_negative():
    # Date 晚于 stored_at → apparent_age 钳到 0（时钟偏差不产生负年龄）
    result = _run_tool("cache_evaluate", {
        "now": "2026-01-01T00:00:30Z",
        "response_headers": {"Cache-Control": "max-age=60",
                             "Date": "Fri, 02 Jan 2026 00:00:00 GMT"},
        "stored": {"stored_at": "2026-01-01T00:00:10Z"},
    })
    assert result["current_age"] == 20


def test_fetch_read_redirects_rejects_bad_status():
    with pytest.raises(hs_errors.JudgementError) as e:
        fetch_sim._read_redirects([{"status": 200, "url": "https://h"}])
    assert "redirects[0].status" in e.value.field


def test_fetch_read_redirects_names_offending_index():
    with pytest.raises(hs_errors.JudgementError) as e:
        fetch_sim._read_redirects([{"status": 302, "url": "https://h"}, {"status": 301}])
    assert e.value.field == "redirects[1].url"


def test_fetch_read_redirects_normalises_hops():
    hops = fetch_sim._read_redirects([{"status": 307, "url": "https://h/x", "headers": {"A": "b"}}])
    assert hops == [{"url": "https://h", "status": 307, "headers": {"a": ["b"]}}]


def test_fetch_preflight_occurred_flag_or_method():
    base = {"method": "GET", "url": "https://a.example.com", "origin": "https://a.example.com",
            "credentials": "omit", "mode": "cors",
            "response": {"status": 200, "headers": {"Access-Control-Allow-Origin": "https://a.example.com"}}}
    result = _run_tool("cors_simulate_fetch", dict(base, is_preflight=True, redirects=[]))
    assert result["preflight_occurred"] is True
    result2 = _run_tool("cors_simulate_fetch", dict(base, is_preflight=False, redirects=[]))
    assert result2["preflight_occurred"] is False
    result3 = _run_tool("cors_simulate_fetch", dict(
        base, is_preflight=False, method="DELETE", redirects=[]))
    assert result3["preflight_occurred"] is True  # DELETE 需要 preflight


def test_fetch_preflight_cache_key_is_16_hex():
    result = _run_tool("cors_simulate_fetch", {
        "method": "GET", "url": "https://a.example.com", "origin": "https://a.example.com",
        "credentials": "omit", "mode": "cors", "is_preflight": False,
        "response": {"status": 200, "headers": {}}, "redirects": [],
    })
    key = result["preflight_cache_key"]
    assert len(key) == 16
    assert all(c in "0123456789abcdef" for c in key)


def test_fetch_blocked_chain_stops_without_final_hop():
    result = _run_tool("cors_simulate_fetch", {
        "method": "GET", "url": "https://a.example.com", "origin": "https://other.example.com",
        "credentials": "omit", "mode": "cors", "is_preflight": False,
        "response": {"status": 200, "headers": {}},
        "redirects": [{"status": 302, "url": "https://b.example.com", "headers": {}}],
    })
    assert result["decision"] == "block"
    assert result["hops"][-1]["decision"] == "block"


def test_fetch_same_origin_mode_blocks_cross_redirect():
    result = _run_tool("cors_simulate_fetch", {
        "method": "GET", "url": "https://a.example.com", "origin": "https://a.example.com",
        "credentials": "omit", "mode": "same-origin", "is_preflight": False,
        "response": {"status": 200, "headers": {}},
        "redirects": [{"status": 302, "url": "https://b.example.com", "headers": {}}],
    })
    assert result["decision"] == "block"
    assert result["final_type"] == "basic"
    assert any(v["code"] == "CORS_REDIRECT_NOT_SAME_ORIGIN"
               for h in result["hops"] for v in h["violations"])


def test_vary_outcome_shape():
    out = vary._outcome("hit", [], ["accept"], [])
    assert out == {"differing_headers": [], "match": "hit", "normalized_vary": ["accept"], "reasons": []}


def test_vary_members_empty_vary_is_no_keys():
    members, repeat = vary._members(None)
    assert members == [] and repeat is None
    members2, repeat2 = vary._members("")
    assert members2 == [] and repeat2 is None


def test_vary_normalise_value_none_is_empty_string():
    policy = default_settings.VARY_NORMALIZATION["default"]
    assert vary.normalise_vary_value(None, policy) == ""


def test_vary_multi_field_two_members_mismatch_lists_both():
    result = _run_tool("vary_match", {
        "cached": {"vary": "Accept, User-Agent",
                   "request_headers_at_store": {"Accept": "a", "User-Agent": "x"}},
        "incoming": {"request_headers": {"Accept": "b", "User-Agent": "y"}},
    })
    assert result["differing_headers"] == ["accept", "user-agent"]
    assert result["match"] == "miss"


def test_normalise_origin_key_trims_ows():
    assert normalise.origin_key("  https://h  ") == "https://h"


def test_normalise_token_charset_is_rfc_9110_tchar():
    # '!' 到 '~' 的 tchar 全放行、空格与非 ASCII 拒收
    assert normalise.normalise_header_name("a!#$%&'*+.^_`|~-09", "f") == "a!#$%&'*+.^_`|~-09"
    with pytest.raises(hs_errors.JudgementError):
        normalise.normalise_header_name("hé", "f")


def test_normalise_serialise_origin_uppercase_scheme_host_lowered():
    assert normalise.serialise_origin("HTTPS://API.Example.COM") == "https://api.example.com"


def test_timeparse_iso_fractional_any_length():
    _, a = timeparse.parse_time("2026-01-01T00:00:00.1Z", "f")
    _, b = timeparse.parse_time("2026-01-01T00:00:00.123456Z", "f")
    assert a == b


def test_timeparse_http_date_rejects_lowercase_month():
    with pytest.raises(hs_errors.JudgementError):
        timeparse.parse_time("Thu, 01 jan 2026 00:00:00 GMT", "f")


def test_timeparse_days_from_civil_known_anchors():
    assert timeparse._days_from_civil(1970, 1, 1) == 0
    assert timeparse._days_from_civil(2000, 3, 1) == 11017  # 公历纪元公式已知锚点


def test_errors_str_carries_code_and_detail():
    e = hs_errors.unsupported_method("method", "TELEPORT")
    assert str(e) == "UNSUPPORTED_METHOD: method not in the accepted set: 'TELEPORT'"


def test_canonical_dumps_unicode_not_escaped():
    assert "中" in canonical.dumps({"k": "中文"})


def test_canonical_dumps_preserves_array_order():
    assert canonical.dumps({"a": [3, 1, 2]}) == '{"a":[3,1,2]}'


def test_ledger_conditional_evidence_carries_rule_and_weak_flag():
    records = _evaluate(_subject("conditional_evaluate", CASES["cond-007-if-none-match-weak-304"]["input"]))
    rec = [r for r in records if r.rule_id.startswith("COND_")][0]
    result = _result_of(records)
    assert result["weak_comparison_used"] is True
    assert result["rule_applied"] == "if_none_match"


def test_ledger_summary_path_is_summary():
    records = _evaluate(_subject("vary_match", CASES["vary-001-hit-single"]["input"]))
    assert _summary(records).path == "summary"
    assert _summary(records).basis.rule_id == "hs-summary"


def test_subject_thresholds_override_is_honored():
    # subject.thresholds 覆盖模块常量：把 VARY_FIELD_MISMATCH 改成 informational → 不再阻断
    settings = json.loads(json.dumps(SETTINGS))
    settings["severity"]["VARY_FIELD_MISMATCH"] = "informational"
    records = _evaluate({"mode": "vary_match", "arguments": CASES["vary-002-miss-value"]["input"],
                         "thresholds": settings})
    rec = [r for r in records if r.rule_id == "VARY_FIELD_MISMATCH"][0]
    assert rec.verdict == INFO


def test_pack_duplicate_slug_rejected():
    from byteproof.core.registry import Pack, register
    with pytest.raises(ValueError):
        register(Pack(slug=SLUG, version="1", summary="x", input_fields=("mode",), evaluate=api.evaluate))


def test_pack_rejects_bad_slug_and_empty_fields():
    from byteproof.core.registry import Pack
    with pytest.raises(ValueError):
        Pack(slug="Bad_Slug", version="1", summary="x", input_fields=("mode",), evaluate=api.evaluate)
    with pytest.raises(ValueError):
        Pack(slug="ok-slug", version="1", summary="", input_fields=("mode",), evaluate=api.evaluate)
    with pytest.raises(ValueError):
        Pack(slug="ok-slug", version="1", summary="x", input_fields=(), evaluate=api.evaluate)


def test_registry_all_packs_sorted():
    load_builtin()
    from byteproof.core.registry import all_packs
    slugs = [p.slug for p in all_packs()]
    assert slugs == sorted(slugs)
    assert SLUG in slugs



