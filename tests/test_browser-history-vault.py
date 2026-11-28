"""``browser-history-vault`` 器官的无损测试（迁自 10-18-browser-history-vault）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：1601 纪元时间换算（整数
运算、不读时钟、固定偏移）、隐私门禁（私密完全排除/敏感保留统计只打码/私密进输出面
当场红）、会话切分（严格大于才切、按来源分组、显式次排序键）、规范化器（主机解析/
去重键确定性保留）、行为洞察（覆盖缺口合并缺失日/频次榜分子分母/热力分桶/遗忘四条件）、
主题聚类（词族分组+高同现合并+防链式吞并）、字 n-gram 检索（标题∪URL、分页稳定）。

**没迁的部分逐条写在 ``docs/browser-history-vault.md`` §6 的处置表里**（SQLite 快照/
归档、文件 I/O、HTML 报告、CLI、netguard 静态门、数据底座生成器）。测试数据全部
合成（禁真实用户数据）。

判定层口径（D1 + D18）：旧仓 26 个测试文件剔除 ``bench|cli|guard|generat|audit|
report|release|selftest`` 后 15 文件实跑 **X = 223 passed**（旧层 AST ``test_`` 函数
183）。
"""

from __future__ import annotations

import datetime
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
from byteproof.auditors.browser_history_vault import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    cluster,
    insight,
    norm,
    privacy,
    search,
    sessions,
    spec,
    timeutil,
)
from byteproof.core import (  # noqa: E402
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    Basis,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "browser-history-vault"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "browser-history-vault.basis.json"
THRESHOLDS_PATH = DATA_DIR / "browser-history-vault.thresholds.json"
SAMPLE = ROOT / "samples" / "browser-history-vault.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

REF_DT = datetime.datetime(2026, 1, 10, 12, 30, 45)
REF_US = timeutil.datetime_to_us(REF_DT)


def _row(visit_id, url, title, host, day_offset, hour=10, browser="chrome", profile="Default", duration=60000000, minute=0):
    moment = datetime.datetime(2026, 1, 1, hour, minute, 0) + datetime.timedelta(days=day_offset)
    return {
        "visit_id": visit_id,
        "url": url,
        "title": title,
        "host": host,
        "visit_time_us": timeutil.datetime_to_us(moment),
        "source_browser": browser,
        "source_profile": profile,
        "transition": 805306368,
        "visit_duration_us": duration,
    }


def _rows():
    return [
        _row(1, "https://docs.example.test/guide", "使用指南", "docs.example.test", 0, 10),
        _row(2, "https://docs.example.test/api", "API 参考", "docs.example.test", 0, 10, minute=20),
        _row(3, "https://vault.example.test/article", "深度文章", "vault.example.test", 2, 10),
    ]


_PRIVATE = ["private.example.test"]
_SENSITIVE = ["secret.example.test"]


def _options(rows=None, mode=None, **extra):
    options = {
        "timezone_utc_offset_minutes": 480,
        "session_gap_minutes": 30,
        "report_top_n": 5,
        "weekday_start": "monday",
        "today_local_date": "2026-01-15",
        "forgotten_days_threshold": 5,
        "forgotten_min_visits": 2,
        "forgotten_min_distinct_days": 2,
        "cluster_min_df": 2,
        "cluster_max_features": 20,
        "cluster_top_terms": 3,
        "cluster_similarity_threshold": 0.6,
        "random_seed": 0,
        "search_ngram_n": 2,
        "privacy": {"private_domains": _PRIVATE, "sensitive_domains": _SENSITIVE},
        "search": {"text": "指南"},
    }
    options.update(extra)
    subject = {"mode": mode or "audit", "rows": rows if rows is not None else _rows(), "options": options}
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


def _forgotten_rows(days_ago, visits=3, distinct_days=2):
    today = datetime.date(2026, 1, 15)
    rows = []
    visit_id = 1
    for index in range(visits):
        day = today - datetime.timedelta(days=days_ago + (index % distinct_days))
        rows.append(
            {
                "visit_id": visit_id,
                "url": "https://old.example.test/treasure",
                "title": "宝藏",
                "host": "old.example.test",
                "visit_time_us": timeutil.local_day_start_us(day, 0) + index * 1000000,
                "source_browser": "chrome",
                "source_profile": "Default",
                "transition": 1,
                "visit_duration_us": 1,
            }
        )
        visit_id += 1
    return rows


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG


def test_pack_declares_mode_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "browser_history_vault" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_sample_is_a_clean_audit():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert data["mode"] == "audit"
    assert {r.verdict for r in _evaluate(data)} == {INFO}


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


def test_thresholds_canonical_fields_match_runtime():
    assert SETTINGS["canonical_fields"] == list(norm.CANONICAL_FIELDS)
    assert SETTINGS["canonical_sort_fields"] == list(norm.CANONICAL_SORT_FIELDS)


def test_thresholds_known_browsers_match_runtime():
    assert SETTINGS["known_browsers"] == list(norm.KNOWN_BROWSERS)


def test_thresholds_forgotten_conditions_match_runtime():
    assert SETTINGS["forgotten_conditions"] == list(spec.FORGOTTEN_CONDITIONS)


def test_thresholds_session_rule_matches_runtime():
    assert SETTINGS["session_split_rule"] == spec.SESSION_SPLIT_RULE


def test_thresholds_weekday_starts_match_runtime():
    assert SETTINGS["weekday_starts"] == list(timeutil.WEEKDAY_STARTS)


def test_thresholds_search_order_keys_match_runtime():
    assert SETTINGS["search_order_keys"] == list(search.ORDER_KEYS)


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("bh-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== timeutil
def test_epoch_constant_is_1601():
    assert timeutil.EPOCH_1601 == datetime.datetime(1601, 1, 1)


def test_epoch_start_maps_to_zero():
    assert timeutil.datetime_to_us(datetime.datetime(1601, 1, 1)) == 0


def test_datetime_to_us_integer_precision():
    moment = datetime.datetime(2026, 1, 10, 12, 30, 45, 123456)
    us = timeutil.datetime_to_us(moment)
    assert timeutil.us_to_datetime(us) == moment


def test_epoch_conversion_reference_point():
    delta = REF_DT - timeutil.EPOCH_1601
    expected = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    assert REF_US == expected


def test_rejects_aware_datetime():
    aware = REF_DT.replace(tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError):
        timeutil.datetime_to_us(aware)


def test_local_datetime_of_us_applies_offset():
    local = timeutil.local_datetime_of_us(REF_US, 480)
    assert local == REF_DT + datetime.timedelta(minutes=480)


def test_local_us_of_datetime_roundtrip():
    local = datetime.datetime(2026, 1, 10, 20, 30, 45)
    us = timeutil.local_us_of_datetime(local, 480)
    assert timeutil.local_datetime_of_us(us, 480) == local


def test_local_date_of_us_uses_local_calendar():
    us = timeutil.datetime_to_us(datetime.datetime(2026, 1, 10, 18, 0, 0))
    assert timeutil.local_date_of_us(us, 480) == datetime.date(2026, 1, 11)


def test_local_day_start_us_is_midnight():
    day = datetime.date(2026, 1, 11)
    start_us = timeutil.local_day_start_us(day, 480)
    assert timeutil.local_datetime_of_us(start_us, 480) == datetime.datetime(2026, 1, 11, 0, 0, 0)


def test_resolve_weekday_start_normalizes_case():
    assert timeutil.resolve_weekday_start(" Monday ") == "monday"


def test_resolve_weekday_start_rejects_unknown():
    with pytest.raises(ValueError):
        timeutil.resolve_weekday_start("tuesday")


def test_local_weekday_index_monday_start():
    us = timeutil.datetime_to_us(datetime.datetime(2026, 1, 10, 3, 0, 0))
    assert timeutil.local_weekday_index(us, 0, "monday") == 5  # 2026-01-10 周六


def test_local_weekday_index_sunday_start_shifts():
    us = timeutil.datetime_to_us(datetime.datetime(2026, 1, 10, 3, 0, 0))
    assert timeutil.local_weekday_index(us, 0, "sunday") == 6


def test_local_weekday_index_honors_offset():
    us = timeutil.datetime_to_us(datetime.datetime(2026, 1, 10, 18, 0, 0))
    assert timeutil.local_weekday_index(us, 480, "monday") == 6  # 本地已是周日


def test_weekday_names_monday_start():
    assert timeutil.weekday_names("monday") == ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def test_weekday_names_sunday_start():
    assert timeutil.weekday_names("sunday") == ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


# ================================================================== privacy
@pytest.mark.parametrize(
    "host,expected",
    [
        ("private.example.test", "private"),
        ("mail.private.example.test", "private"),
        ("secret.example.test", "sensitive"),
        ("x.secret.example.test", "sensitive"),
        ("docs.example.test", "public"),
        ("notprivate.example.test", "public"),
        ("PRIVATE.example.test", "private"),
        ("Private.Example.Test", "private"),
        ("example.test", "public"),
        ("secret.example.test.other", "public"),
    ],
)
def test_classify_host_table(host, expected):
    assert privacy.classify_host(host, _PRIVATE, _SENSITIVE) == expected


def test_private_wins_over_sensitive():
    assert privacy.classify_host("dual.example.test", ["dual.example.test"], ["dual.example.test"]) == "private"


def test_classify_host_rejects_empty():
    with pytest.raises(privacy.PrivacyError):
        privacy.classify_host("", _PRIVATE, _SENSITIVE)


@pytest.mark.parametrize(
    "host,entry,expected",
    [
        ("example.test", "example.test", True),
        ("x.example.test", "example.test", True),
        ("notexample.test", "example.test", False),
        ("example.test", "other.test", False),
        ("example.test", "  ", False),
        ("x.y.example.test", "example.test", True),
        ("example.test.evil.test", "example.test", False),
    ],
)
def test_host_matches_entry_table(host, entry, expected):
    assert privacy.host_matches_entry(host, entry) is expected


def test_mask_host_keeps_last_two_segments():
    assert privacy.mask_host("vault.sensitive.example.test") == "***.***.example.test"


def test_mask_host_short_hosts():
    assert privacy.mask_host("localhost") == "***"
    assert privacy.mask_host("a.test") == "***"


def test_fingerprint_is_stable_and_irreversible():
    assert privacy.fingerprint("Secret.Example.Test") == privacy.fingerprint("secret.example.test")
    assert privacy.fingerprint("secret.example.test").startswith("h-")
    assert "secret" not in privacy.fingerprint("secret.example.test")


def test_redact_text_public_untouched():
    assert privacy.redact_text("https://docs.example.test/a", "docs.example.test", _PRIVATE, _SENSITIVE) == "https://docs.example.test/a"


def test_redact_text_sensitive_masks_url_and_title():
    text = "https://secret.example.test/page"
    masked = privacy.redact_text(text, "secret.example.test", _PRIVATE, _SENSITIVE)
    assert "secret.example.test" not in masked
    assert masked == "https://***.example.test/page"


def test_redact_text_private_raises():
    with pytest.raises(privacy.PrivacyError):
        privacy.redact_text("x", "private.example.test", _PRIVATE, _SENSITIVE)


def test_display_host_classes():
    assert privacy.display_host("Docs.Example.Test", _PRIVATE, _SENSITIVE) == "docs.example.test"
    assert privacy.display_host("secret.example.test", _PRIVATE, _SENSITIVE) == "***.example.test"
    with pytest.raises(privacy.PrivacyError):
        privacy.display_host("private.example.test", _PRIVATE, _SENSITIVE)


def test_keep_visible_excludes_private_keeps_sensitive():
    rows = [
        {"host": "docs.example.test"},
        {"host": "private.example.test"},
        {"host": "secret.example.test"},
    ]
    visible = privacy.keep_visible(rows, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    assert [r["host"] for r in visible] == ["docs.example.test", "secret.example.test"]


def test_classify_rows_counts_excluded():
    rows = [{"host": "private.example.test"}, {"host": "docs.example.test"}, {"host": "private.example.test"}]
    visible, excluded = privacy.classify_rows(rows, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    assert len(visible) == 1 and excluded == 2


def test_summarize_counts_by_host():
    rows = [
        {"host": "private.example.test"},
        {"host": "private.example.test"},
        {"host": "secret.example.test"},
    ]
    summary = privacy.summarize(rows, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    assert summary["excluded_visit_records"] == 2
    assert summary["masked_visit_records"] == 1
    assert summary["private_host_counts"] == {"private.example.test": 2}
    assert summary["sensitive_host_counts"] == {"secret.example.test": 1}


# ================================================================== sessions
def test_split_sessions_basic_grouping():
    result = sessions.split_sessions(_rows(), 30)
    assert len(result) == 2
    assert result[0].size == 2 and result[1].size == 1


def test_split_gap_strictly_greater_splits():
    base = datetime.datetime(2026, 1, 1, 8, 0, 0)
    gap = 30
    exact_rows = [
        {"visit_id": 1, "url": "https://a.test/1", "visit_time_us": timeutil.datetime_to_us(base), "source_browser": "chrome", "source_profile": "Default"},
        {"visit_id": 2, "url": "https://a.test/2", "visit_time_us": timeutil.datetime_to_us(base + datetime.timedelta(minutes=gap)), "source_browser": "chrome", "source_profile": "Default"},
    ]
    assert len(sessions.split_sessions(exact_rows, gap)) == 1
    over_rows = [
        exact_rows[0],
        {"visit_id": 2, "url": "https://a.test/2", "visit_time_us": timeutil.datetime_to_us(base + datetime.timedelta(minutes=gap, microseconds=1)), "source_browser": "chrome", "source_profile": "Default"},
    ]
    assert len(sessions.split_sessions(over_rows, gap)) == 2


def test_split_groups_never_merge_sources():
    base = datetime.datetime(2026, 1, 1, 8, 0, 0)
    rows = [
        {"visit_id": 1, "url": "https://a.test/1", "visit_time_us": timeutil.datetime_to_us(base), "source_browser": "chrome", "source_profile": "Default"},
        {"visit_id": 2, "url": "https://a.test/2", "visit_time_us": timeutil.datetime_to_us(base + datetime.timedelta(minutes=1)), "source_browser": "edge", "source_profile": "Default"},
    ]
    result = sessions.split_sessions(rows, 30)
    assert len(result) == 2
    assert {s.source_browser for s in result} == {"chrome", "edge"}


def test_split_profiles_never_merge():
    base = datetime.datetime(2026, 1, 1, 8, 0, 0)
    rows = [
        {"visit_id": 1, "url": "https://a.test/1", "visit_time_us": timeutil.datetime_to_us(base), "source_browser": "chrome", "source_profile": "Default"},
        {"visit_id": 2, "url": "https://a.test/2", "visit_time_us": timeutil.datetime_to_us(base + datetime.timedelta(minutes=1)), "source_browser": "chrome", "source_profile": "Profile 1"},
    ]
    assert len(sessions.split_sessions(rows, 30)) == 2


def test_split_session_ids_ordered_by_start():
    result = sessions.split_sessions(_rows(), 30)
    assert [s.session_id for s in result] == [1, 2]
    assert result[0].start_us <= result[1].start_us


def test_split_step_order_uses_url_tiebreak():
    base = datetime.datetime(2026, 1, 1, 8, 0, 0)
    us = timeutil.datetime_to_us(base)
    rows = [
        {"visit_id": 2, "url": "https://a.test/b", "visit_time_us": us, "source_browser": "chrome", "source_profile": "Default"},
        {"visit_id": 1, "url": "https://a.test/a", "visit_time_us": us, "source_browser": "chrome", "source_profile": "Default"},
    ]
    result = sessions.split_sessions(rows, 30)
    assert result[0].urls() == ("https://a.test/a", "https://a.test/b")


def test_session_span_properties():
    result = sessions.split_sessions(_rows(), 30)
    first = result[0]
    assert first.size == 2
    assert first.span_us == first.end_us - first.start_us
    assert first.visit_ids() == (1, 2)


def test_sessions_containing_by_url():
    result = sessions.split_sessions(_rows(), 30)
    hit = sessions.sessions_containing(result, ["https://vault.example.test/article"])
    assert len(hit) == 1 and hit[0].session_id == 2


def test_size_histogram_and_sequence():
    result = sessions.split_sessions(_rows(), 30)
    assert sessions.size_histogram(result) == {"1": 1, "2": 1}
    assert sessions.session_size_sequence(result) == (1, 2)


def test_split_rejects_non_positive_gap():
    with pytest.raises(sessions.SessionError):
        sessions.split_sessions(_rows(), 0)


def test_split_rejects_missing_fields():
    with pytest.raises(sessions.SessionError):
        sessions.split_sessions([{"visit_id": 1, "url": "https://a.test/1"}], 30)


def test_step_urls_matches_urls_property():
    result = sessions.split_sessions(_rows(), 30)
    assert sessions.step_urls(result[0]) == result[0].urls()


# ================================================================== norm
def test_host_of_basic():
    assert norm.host_of("https://Example.test/path") == "example.test"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://user:pass@Host.test:8080/p", "host.test"),
        ("https://host.test?q=1#frag", "host.test"),
        ("http://host.test", "host.test"),
        ("example.test/path", "example.test"),
        ("HTTPS://HOST.TEST/p", "host.test"),
        ("https://host.test", "host.test"),
        ("https://host.test./p", "host.test."),
    ],
)
def test_host_of_strips_everything_but_host(url, expected):
    assert norm.host_of(url) == expected


def test_host_of_rejects_empty():
    with pytest.raises(norm.NormalizeError):
        norm.host_of("")


def test_profile_name_of_known_patterns():
    assert norm.profile_name_of("Default") == "Default"
    assert norm.profile_name_of("Profile 1") == "Profile 1"
    assert norm.profile_name_of("Guest Profile") == "Guest Profile"


def test_profile_name_of_falls_back_to_default():
    assert norm.profile_name_of("something-else") == "Default"


def test_normalize_rows_sorts_by_canonical_key():
    rows = [_row(2, "https://b.test/2", "b", "b.test", 0), _row(1, "https://a.test/1", "a", "a.test", 0, hour=9)]
    normalized = norm.normalize_rows(rows)
    assert normalized[0]["url"] == "https://a.test/1"


def test_normalize_rows_dedupe_keeps_first_and_counts():
    base = datetime.datetime(2026, 1, 1, 8, 0, 0)
    us = timeutil.datetime_to_us(base)
    rows = [
        {"url": "https://a.test/1", "title": "first", "host": "a.test", "visit_time_us": us, "source_browser": "chrome", "source_profile": "Default", "transition": 1, "visit_duration_us": 1},
        {"url": "https://a.test/1", "title": "second", "host": "a.test", "visit_time_us": us, "source_browser": "chrome", "source_profile": "Default", "transition": 2, "visit_duration_us": 2},
    ]
    normalized = norm.normalize_rows(rows)
    assert len(normalized) == 1
    assert normalized[0]["title"] == "first"


def test_normalize_rows_error_mode_rejects_duplicates():
    rows = [
        {"url": "u", "title": "t", "host": "h", "visit_time_us": 1, "source_browser": "chrome", "source_profile": "Default", "transition": 1, "visit_duration_us": 1},
        {"url": "u", "title": "t", "host": "h", "visit_time_us": 1, "source_browser": "chrome", "source_profile": "Default", "transition": 1, "visit_duration_us": 1},
    ]
    with pytest.raises(norm.NormalizeError):
        norm.normalize_rows(rows, on_duplicate="error")


def test_normalize_rows_rejects_unknown_mode():
    with pytest.raises(norm.NormalizeError):
        norm.normalize_rows([], on_duplicate="merge")


def test_normalize_rows_rejects_missing_fields():
    with pytest.raises(norm.NormalizeError):
        norm.normalize_rows([{"url": "u"}])


def test_canonical_fields_order_is_contract():
    assert norm.CANONICAL_FIELDS == (
        "url", "title", "host", "visit_time_us", "source_browser", "source_profile", "transition", "visit_duration_us",
    )


# ================================================================== insight：覆盖
def test_coverage_block_counts_days_and_gaps():
    block = insight.coverage_block(_rows(), offset_minutes=0)
    assert block["interval_days"] == 3
    assert block["days_with_visits"] == 2
    assert block["gap_days_total"] == 1
    assert block["gaps"] == [{"from": "2026-01-02", "to": "2026-01-02", "days": 1}]
    assert block["note"].startswith("归档覆盖区间不足 90 天")


def test_coverage_block_includes_private_rows():
    rows = _rows() + [_row(9, "https://private.example.test/x", "私", "private.example.test", 5)]
    block = insight.coverage_block(rows, offset_minutes=0)
    assert block["days_with_visits"] == 3  # 私密记录也计入覆盖


def test_coverage_block_empty_rows():
    block = insight.coverage_block([], offset_minutes=0)
    assert block["first_local_date"] is None
    assert block["interval_days"] == 0
    assert block["note"].startswith("归档库没有任何访问记录")


def test_coverage_block_per_source():
    rows = _rows() + [_row(4, "https://edge.test/1", "e", "edge.test", 0, browser="edge")]
    block = insight.coverage_block(rows, offset_minutes=0)
    by_source = {s["source_browser"]: s for s in block["by_source"]}
    assert set(by_source) == {"chrome", "edge"}


def test_gap_ranges_merges_missing_days():
    days = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-09"]
    assert insight.gap_ranges(days) == [
        ("2026-01-03", "2026-01-04", 2),
        ("2026-01-07", "2026-01-08", 2),
    ]


def test_gap_ranges_no_gap_when_dense():
    assert insight.gap_ranges(["2026-01-01", "2026-01-02", "2026-01-03"]) == []


def test_gap_ranges_single_day_no_gap():
    assert insight.gap_ranges(["2026-01-01"]) == []


# ================================================================== insight：频次与集中度
def test_url_ranking_counts_and_visit_ids():
    rows = _rows() + [_row(4, "https://docs.example.test/guide", "使用指南", "docs.example.test", 3)]
    ranked = insight.url_ranking(rows)
    assert ranked[0]["url"] == "https://docs.example.test/guide"
    assert ranked[0]["visits"] == 2
    assert ranked[0]["visit_ids"] == [1, 4]


def test_url_ranking_tie_orders_by_url():
    rows = [
        _row(1, "https://b.test/1", "b", "b.test", 0),
        _row(2, "https://a.test/1", "a", "a.test", 0),
    ]
    ranked = insight.url_ranking(rows)
    assert [item["url"] for item in ranked] == ["https://a.test/1", "https://b.test/1"]


def test_domain_ranking_dedupes_urls():
    ranked = insight.domain_ranking(_rows())
    docs = next(item for item in ranked if item["domain"] == "docs.example.test")
    assert docs["visits"] == 2 and docs["urls"] == 2
    assert ranked[0]["domain"] == "docs.example.test"


def test_concentration_block_numerator_denominator():
    block = insight.concentration_block(_rows(), top_n=2, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    assert block["denominator_records"] == 3
    assert block["items"][0]["share_numerator"] == 2
    assert block["items"][0]["share_denominator"] == 3
    assert block["items"][0]["share_percent_text"] == "66.67"


def test_concentration_block_masks_sensitive_domain():
    rows = _rows() + [_row(9, "https://secret.example.test/x", "s", "secret.example.test", 0)]
    block = insight.concentration_block(rows, top_n=5, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    domains = [item["domain"] for item in block["items"]]
    assert "***.example.test" in domains
    assert "secret.example.test" not in domains


def test_heatmap_counts_buckets_by_local_weekday_hour():
    counts = insight.heatmap_counts(_rows(), offset_minutes=0, weekday_start="monday")
    assert counts == {"3:10": 2, "5:10": 1}


def test_heatmap_counts_shifts_with_sunday_start():
    counts = insight.heatmap_counts(_rows(), offset_minutes=0, weekday_start="sunday")
    assert counts == {"4:10": 2, "6:10": 1}


@pytest.mark.parametrize(
    "count,maximum,expected",
    [
        (0, 10, 0),
        (10, 10, 9),
        (5, 10, 4),  # Python round 银行家舍入：round(4.5)=4（与旧仓同式）
        (1, 10, 1),
        (3, 0, 0),
        (0, 0, 0),
    ],
)
def test_spark_level_bounds(count, maximum, expected):
    assert insight.spark_level(count, maximum) == expected


def test_sessions_block_summary():
    block = insight.sessions_block(_rows(), gap_minutes=30, top_n=5)
    assert block["session_count"] == 2
    assert block["total_visits"] == 3
    assert block["sessions_by_source"] == {"chrome": 2}
    assert block["split_rule"] == spec.SESSION_SPLIT_RULE


def test_sessions_block_largest_ordered():
    rows = _rows() + [
        _row(4, "https://x.test/1", "x", "x.test", 1),
        _row(5, "https://x.test/2", "x", "x.test", 1, hour=10, minute=10),
        _row(6, "https://x.test/3", "x", "x.test", 1, hour=10, minute=20),
    ]
    block = insight.sessions_block(rows, gap_minutes=30, top_n=2)
    assert block["largest"][0]["size"] == 3
    assert len(block["largest"]) == 2


# ================================================================== insight：遗忘
def test_forgotten_state_all_conditions_met():
    state = insight.forgotten_state(
        _forgotten_rows(10), "https://old.example.test/treasure",
        days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert state["forgotten"] is True
    assert state["failed_conditions"] == []
    assert state["host_class"] == "public"


def test_forgotten_state_fails_days_threshold():
    state = insight.forgotten_state(
        _forgotten_rows(3), "https://old.example.test/treasure",
        days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert state["forgotten"] is False
    assert spec.FORGOTTEN_CONDITIONS[0] in state["failed_conditions"]


def test_forgotten_state_fails_min_visits():
    state = insight.forgotten_state(
        _forgotten_rows(10, visits=1, distinct_days=1), "https://old.example.test/treasure",
        days_threshold=5, min_visits=2, min_distinct_days=1,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert spec.FORGOTTEN_CONDITIONS[1] in state["failed_conditions"]


def test_forgotten_state_fails_distinct_days():
    state = insight.forgotten_state(
        _forgotten_rows(10, visits=3, distinct_days=1), "https://old.example.test/treasure",
        days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert spec.FORGOTTEN_CONDITIONS[2] in state["failed_conditions"]


def test_forgotten_state_fails_private_host():
    rows = _forgotten_rows(10)
    for row in rows:
        row["host"] = "private.example.test"
    state = insight.forgotten_state(
        rows, "https://old.example.test/treasure",
        days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert spec.FORGOTTEN_CONDITIONS[3] in state["failed_conditions"]


def test_forgotten_state_unknown_url():
    state = insight.forgotten_state(
        _forgotten_rows(10), "https://other.test/none",
        days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert state["forgotten"] is False
    assert state["failed_conditions"] == ["no_visits_for_url"]


def test_forgotten_block_orders_by_days_ago():
    rows = _forgotten_rows(10) + [
        dict(_forgotten_rows(40)[0], url="https://older.example.test/x", host="older.example.test", visit_id=99),
        dict(_forgotten_rows(41)[0], url="https://older.example.test/x", host="older.example.test", visit_id=98),
    ]
    block = insight.forgotten_block(
        rows, days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert block["state"] == "assessed"
    assert [item["url"] for item in block["items"]] == ["https://older.example.test/x", "https://old.example.test/treasure"]


def test_forgotten_block_not_assessed_when_empty():
    block = insight.forgotten_block(
        [], days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert block["state"] == "not_assessed"
    assert block["matched_count"] == 0


def test_forgotten_block_never_lists_private_host():
    rows = _forgotten_rows(10)
    for row in rows:
        row["host"] = "private.example.test"
    block = insight.forgotten_block(
        rows, days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert block["items"] == []


def test_forgotten_block_guard_keeps_non_public_out():
    # 条件④ + 结构护栏共同保证：非公开主机不可能出现在命中项里
    rows = _forgotten_rows(10)
    for row in rows:
        row["host"] = "secret.example.test"
    block = insight.forgotten_block(
        rows, days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert block["state"] == "assessed"
    assert block["items"] == []


def test_forgotten_today_accepts_string_date():
    state = insight.forgotten_state(
        _forgotten_rows(10), "https://old.example.test/treasure",
        days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert state["last_visit_days_ago"] >= 5


def test_forgotten_today_rejects_aware_datetime():
    with pytest.raises(insight.InsightError):
        insight.forgotten_state(
            _forgotten_rows(10), "https://old.example.test/treasure",
            days_threshold=5, min_visits=2, min_distinct_days=2,
            today_local_date=datetime.datetime(2026, 1, 15, tzinfo=datetime.timezone.utc),
            offset_minutes=0,
            private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
        )


# ================================================================== cluster
def test_title_tokens_casefold_and_dedup():
    tokens = cluster.title_tokens("Rust Programming rust guide")
    assert tokens == ("guide", "programming", "rust")


def test_title_tokens_chinese_segment_becomes_one_token():
    assert cluster.title_tokens("使用指南") == ("使用指南",)


def test_title_tokens_drops_short_tokens():
    # MIN_TOKEN_LENGTH = 2：单词符剔除
    assert cluster.title_tokens("a ab abc") == ("ab", "abc")


def test_host_tokens_leftmost_plus_full_host():
    assert cluster.host_tokens("docs.example.test") == ("docs", "docs.example.test")


def test_host_tokens_skips_short_leftmost():
    assert cluster.host_tokens("x.test") == ("x.test",)


def test_host_tokens_empty():
    assert cluster.host_tokens("") == ()


def test_row_terms_union_sorted():
    terms = cluster.row_terms({"title": "Rust Guide", "host": "docs.example.test"})
    assert terms == ("docs", "docs.example.test", "guide", "rust")


def test_term_weight_idf():
    import math

    weight = cluster.term_weight("term", df=2, document_count=8)
    assert weight == pytest.approx(math.log(4.0))


def test_term_weight_rejects_df_below_one():
    with pytest.raises(cluster.ClusterError):
        cluster.term_weight("term", df=0, document_count=8)


def test_term_weight_rejects_df_exceeding_documents():
    with pytest.raises(cluster.ClusterError):
        cluster.term_weight("term", df=9, document_count=8)


def test_rank_terms_orders_by_weight_then_lexicographic():
    frequencies = {"common": 8, "rare-a": 1, "rare-b": 1}
    ordered = cluster.rank_terms(frequencies, document_count=8, max_features=3)
    assert ordered == ["rare-a", "rare-b", "common"]


def test_rank_terms_caps_max_features():
    ordered = cluster.rank_terms({"common": 8, "rare-a": 1, "rare-b": 1}, document_count=8, max_features=1)
    assert ordered == ["rare-a"]


def test_mergeable_subset_high_jaccard():
    assert cluster.mergeable({"a", "b"}, {"a", "b", "c"}, 0.6) is True


def test_mergeable_rejects_partial_overlap():
    # 部分重叠不合并：防链式吞并（Jaccard 再高也不行）
    assert cluster.mergeable({"a", "b"}, {"b", "c"}, 0.5) is False


def test_mergeable_rejects_low_similarity():
    assert cluster.mergeable({"a", "b"}, {"a", "b", "c", "d", "e", "f", "g", "h", "i", "j"}, 0.6) is False


def _cluster_options(**extra):
    options = {
        "cluster_min_df": 2,
        "cluster_max_features": 20,
        "cluster_top_terms": 3,
        "cluster_similarity_threshold": 0.6,
        "random_seed": 0,
        "private_domains": _PRIVATE,
        "sensitive_domains": _SENSITIVE,
    }
    options.update(extra)
    return options


def _cluster_rows():
    rows = []
    visit_id = 1
    for index in range(3):
        rows.append(_row(visit_id, "https://docs.example.test/topic-a-%d" % index, "示例文章 topic", "docs.example.test", index))
        visit_id += 1
    for index in range(2):
        rows.append(_row(visit_id, "https://blog.example.test/post-%d" % index, "博客随笔", "blog.example.test", index))
        visit_id += 1
    return rows


def test_cluster_topics_groups_same_topic():
    result = cluster.cluster_topics(_cluster_rows(), options=_cluster_options())
    assert result.documents == 5
    assert len(result.clusters) >= 2
    merged = [c for c in result.clusters if "docs.example.test" in c.member_domains]
    assert merged and merged[0].visits == 3


def test_cluster_topics_every_kept_term_covered():
    # 截断（top_terms）之后簇内词 ⊆ 保留词；保留词面 = df ≥ min_df 且未被同形禁用
    result = cluster.cluster_topics(_cluster_rows(), options=_cluster_options())
    covered = {term for c in result.clusters for term in c.terms}
    assert covered <= set(result.kept_terms)
    assert {"docs", "docs.example.test", "topic", "示例文章", "博客随笔", "blog", "blog.example.test"} == set(result.kept_terms)


def test_cluster_topics_drops_below_min_df():
    rows = _cluster_rows() + [_row(99, "https://solo.example.test/1", "独特孤词 xyzzy", "solo.example.test", 0)]
    result = cluster.cluster_topics(rows, options=_cluster_options(cluster_min_df=2))
    assert "xyzzy" in result.dropped_terms
    assert "xyzzy" not in result.kept_terms


def test_cluster_topics_blocks_private_shaped_terms():
    rows = _cluster_rows() + [_row(98, "https://private.example.test/p", "private page", "private.example.test", 0)]
    result = cluster.cluster_topics(rows, options=_cluster_options())
    assert "private.example.test" in result.blocked_terms


def test_cluster_topics_input_order_independent():
    rows_a = _cluster_rows()
    rows_b = list(reversed(_cluster_rows()))
    a = [(c.cluster_id, c.terms, c.urls) for c in cluster.cluster_topics(rows_a, options=_cluster_options()).clusters]
    b = [(c.cluster_id, c.terms, c.urls) for c in cluster.cluster_topics(rows_b, options=_cluster_options()).clusters]
    assert a == b


def test_cluster_topics_rejects_min_df_below_one():
    with pytest.raises(cluster.ClusterError):
        cluster.cluster_topics(_cluster_rows(), options=_cluster_options(cluster_min_df=0))


def test_cluster_topics_urls_sorted_and_visits_summed():
    result = cluster.cluster_topics(_cluster_rows(), options=_cluster_options())
    for item in result.clusters:
        assert list(item.urls) == sorted(item.urls)
        assert item.visits == len(item.urls)


def test_research_paths_follow_sessions():
    paths = cluster.research_paths(_rows(), gap_minutes=30)
    assert [p.session_id for p in paths] == [1, 2]
    assert len(paths[0].steps) == 2
    assert paths[0].steps[0].host == "docs.example.test"


def test_research_paths_every_step_has_visit_id():
    paths = cluster.research_paths(_rows(), gap_minutes=30)
    for path in paths:
        for step in path.steps:
            assert step.visit_id in (1, 2, 3)


# ================================================================== search
def test_char_ngrams_sliding_window():
    grams = search.char_ngrams("abcd", 2)
    assert grams == frozenset({"ab", "bc", "cd"})
    # 重复滑窗在集合里去重
    assert search.char_ngrams("aabb", 2) == frozenset({"aa", "ab", "bb"})


def test_char_ngrams_short_text_takes_whole_string():
    assert search.char_ngrams("ab", 3) == frozenset({"ab"})


def test_char_ngrams_rejects_n_below_one():
    with pytest.raises(search.SearchError):
        search.char_ngrams("abc", 0)


def test_char_ngrams_rejects_non_string():
    with pytest.raises(search.SearchError):
        search.char_ngrams(123, 2)


def test_text_matches_all_grams_must_appear():
    assert search.text_matches("指南", "使用指南文档", 2) is True
    assert search.text_matches("指南", "使用手册", 2) is False


def test_text_matches_casefold():
    assert search.text_matches("Rust", "rustLang", 2) is True


def test_text_matches_exact_length_n():
    assert search.text_matches("指南", "指南", 2) is True


def test_row_text_hit_title_or_url():
    assert search.row_text_hit({"title": "无", "url": "https://x.test/使用指南"}, "指南", 2) is True
    assert search.row_text_hit({"title": "使用指南", "url": "https://x.test/a"}, "指南", 2) is True
    assert search.row_text_hit({"title": "无", "url": "https://x.test/a"}, "指南", 2) is False


def test_run_search_text_filter_and_order():
    result = search.run_search(_rows(), search.SearchQuery(text="指南"), ngram_n=2)
    assert result.matched == 1
    assert result.hits[0].visit_id == 1


def test_run_search_domain_filter_includes_subdomain():
    rows = _rows() + [_row(9, "https://api.docs.example.test/x", "api", "api.docs.example.test", 0)]
    result = search.run_search(rows, search.SearchQuery(domain="docs.example.test"), ngram_n=2)
    assert result.matched == 3


def test_run_search_time_range():
    result = search.run_search(
        _rows(),
        search.SearchQuery(since_us=_rows()[2]["visit_time_us"], until_us=_rows()[2]["visit_time_us"]),
        ngram_n=2,
    )
    assert result.matched == 1
    assert result.hits[0].visit_id == 3


def test_run_search_pagination_stable():
    first = search.run_search(_rows(), search.SearchQuery(limit=1, offset=0), ngram_n=2)
    second = search.run_search(_rows(), search.SearchQuery(limit=1, offset=1), ngram_n=2)
    assert first.hits[0].visit_time_us >= second.hits[0].visit_time_us
    assert first.matched == second.matched == 3


def test_run_search_rejects_unknown_order():
    with pytest.raises(search.SearchError):
        search.run_search(_rows(), search.SearchQuery(order="title"), ngram_n=2)


def test_run_search_rejects_inverted_range():
    with pytest.raises(search.SearchError):
        search.run_search(_rows(), search.SearchQuery(since_us=10, until_us=5), ngram_n=2)


def test_run_search_rejects_bad_offset_and_limit():
    with pytest.raises(search.SearchError):
        search.run_search(_rows(), search.SearchQuery(offset=-1), ngram_n=2)
    with pytest.raises(search.SearchError):
        search.run_search(_rows(), search.SearchQuery(limit=0), ngram_n=2)


def test_matched_urls_deduped_sorted():
    result = search.run_search(_rows(), search.SearchQuery(), ngram_n=2)
    assert search.matched_urls(result) == sorted(set(search.matched_urls(result)))


def test_search_rows_applies_privacy_gate():
    rows = _rows() + [_row(9, "https://private.example.test/secret-指南", "指南", "private.example.test", 0)]
    result = search.search_rows(
        rows, search.SearchQuery(text="指南"),
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE, ngram_n=2,
    )
    assert all("private.example.test" not in hit.url for hit in result.hits)


def test_search_hit_document_masks_sensitive():
    rows = [_row(9, "https://secret.example.test/page", "页面", "secret.example.test", 0)]
    result = search.search_rows(
        rows, search.SearchQuery(),
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE, ngram_n=2,
    )
    document = result.hits[0].to_document(offset_minutes=0, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    assert document["url"] == "https://***.example.test/page"
    assert document["domain"] == "***.example.test"
    assert "secret.example.test" not in json.dumps(document, ensure_ascii=False)


def test_search_hit_document_private_raises():
    hit = search.SearchHit(visit_id=1, url="https://private.example.test/x", title="", host="private.example.test", visit_time_us=1, source_browser="chrome", source_profile="Default")
    with pytest.raises(privacy.PrivacyError):
        hit.to_document(offset_minutes=0, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)


def test_search_hit_local_time_text():
    text = search.local_time_text(timeutil.datetime_to_us(datetime.datetime(2026, 1, 10, 2, 30, 0)), 480)
    assert text == "2026-01-10T10:30:00"


# ================================================================== 账本/模式/校验
def test_audit_mode_emits_all_sections():
    records = _evaluate(_options())
    paths = {r.path.split(".")[0] for r in records}
    assert {"coverage", "sessions", "paths", "cluster", "search", "summary"} <= paths


def test_report_only_mode():
    records = _evaluate(_options(mode="report"))
    paths = {r.path.split(".")[0] for r in records}
    assert "cluster" not in paths and "search" not in paths
    assert "coverage" in paths


def test_search_only_mode():
    records = _evaluate(_options(mode="search"))
    assert [r for r in records if r.path.startswith("search.")]
    assert not [r for r in records if r.path.startswith("coverage.")]


def test_cluster_only_mode():
    records = _evaluate(_options(mode="cluster"))
    assert [r for r in records if r.path.startswith("cluster.")]
    assert not [r for r in records if r.path.startswith("coverage.")]


def test_normalize_only_mode():
    records = _evaluate(_options(mode="normalize"))
    assert not [r for r in records if r.path.startswith("coverage.")]
    assert [r for r in records if r.rule_id in (spec.RULE_NORMALIZE_DUPLICATE, spec.RULE_SUMMARY)]


def test_mode_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_options(mode="archive"))


def test_clean_audit_stays_rc0():
    assert _report(_options()).exit_code() == EXIT_OK


def test_private_rows_excluded_records():
    rows = _rows() + [_row(9, "https://private.example.test/x", "私", "private.example.test", 0)]
    hits = _records(_options(rows=rows), spec.RULE_PRIVACY_EXCLUDED)
    assert len(hits) == 1
    assert hits[0].evidence["excluded_visit_records"] == 1
    assert hits[0].evidence["fingerprint"].startswith("h-")


def test_sensitive_rows_masked_records():
    rows = _rows() + [_row(9, "https://secret.example.test/x", "s", "secret.example.test", 0)]
    hits = _records(_options(rows=rows), spec.RULE_PRIVACY_MASKED)
    assert len(hits) == 1
    assert hits[0].evidence["masked_form"] == "***.example.test"


def test_private_rows_never_in_ranking_output():
    rows = [_row(9, "https://private.example.test/guide", "使用指南", "private.example.test", 0)]
    records = _evaluate(_options(rows=rows, mode="report"))
    dumped = json.dumps([r.as_dict() for r in records], ensure_ascii=False)
    assert "private.example.test/guide" not in dumped


def test_private_rows_never_in_search_output():
    rows = [_row(9, "https://private.example.test/guide", "使用指南", "private.example.test", 0)]
    records = _evaluate(_options(rows=rows, mode="search"))
    dumped = json.dumps([r.as_dict() for r in records], ensure_ascii=False)
    assert "private.example.test/guide" not in dumped


def test_forgotten_record_emitted():
    rows = _forgotten_rows(10)
    records = _records(_options(rows=rows, mode="report", forgotten_days_threshold=5), spec.RULE_FORGOTTEN)
    assert len(records) == 1
    assert records[0].evidence["last_visit_days_ago"] >= 5
    assert records[0].evidence["visit_ids"]


def test_coverage_gap_records_present():
    records = _records(_options(mode="report"), spec.RULE_COVERAGE_GAP)
    assert any(r.path == "coverage.summary" for r in records)
    assert any(r.path.startswith("coverage.gaps[") for r in records)


def test_normalize_duplicate_record_when_present():
    rows = _rows() + [
        dict(_rows()[0], visit_id=77),
    ]
    hits = _records(_options(rows=rows, mode="normalize"), spec.RULE_NORMALIZE_DUPLICATE)
    assert len(hits) == 1
    assert hits[0].evidence["dropped"] == 1


def test_records_unique_ids():
    report = _report(_options())
    ids = [r.id for r in report.records]
    assert len(ids) == len(set(ids))


def test_determinism_double_run():
    a = json.dumps(_report(_options()).as_dict(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_report(_options()).as_dict(), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_missing_rows_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "options": _options()["options"]})


def test_row_missing_required_field_rejected():
    rows = [{"url": "https://x.test/1", "visit_time_us": 1}]
    with pytest.raises(ValueError):
        _evaluate(_options(rows=rows))


@pytest.mark.parametrize(
    "key,value",
    [
        ("timezone_utc_offset_minutes", None),
        ("session_gap_minutes", None),
        ("cluster_min_df", None),
        ("search_ngram_n", None),
        ("today_local_date", None),
        ("weekday_start", None),
        ("report_top_n", None),
        ("cluster_similarity_threshold", None),
        ("random_seed", None),
        ("forgotten_min_visits", None),
    ],
)
def test_options_required_keys_rejected(key, value):
    options = _options()["options"]
    options[key] = value
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "rows": _rows(), "options": options})


def test_options_zero_defaults_rejected():
    # 数值口径唯一来源 = subject：缺了就是输入不合法，器官不设默认值
    options = _options()["options"]
    del options["forgotten_days_threshold"]
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "rows": _rows(), "options": options})


def test_privacy_list_type_rejected():
    options = _options()["options"]
    options["privacy"]["private_domains"] = "not-a-list"
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "rows": _rows(), "options": options})


def test_exit_codes_cli(tmp_path):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_options(), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_OK


def test_exit_code_two_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "audit"}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT


def test_exit_code_three_missing_rule(tmp_path):
    basis_path = tmp_path / "empty.basis.json"
    basis_path.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_options(), ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["check", SLUG, "--input", str(path), "--basis", str(basis_path)])
    assert rc == EXIT_CONTRACT


# ================================================================== 补充：常量与边界
def test_timeutil_unit_constants():
    assert timeutil.US_PER_SECOND == 1_000_000
    assert timeutil.US_PER_MINUTE == 60 * timeutil.US_PER_SECOND
    assert timeutil.US_PER_HOUR == 60 * timeutil.US_PER_MINUTE
    assert timeutil.US_PER_DAY == 24 * timeutil.US_PER_HOUR


def test_privacy_class_constants():
    assert (privacy.PRIVATE, privacy.SENSITIVE, privacy.PUBLIC) == ("private", "sensitive", "public")


def test_coverage_declaration_present():
    block = insight.coverage_block(_rows(), offset_minutes=0)
    assert block["declaration"] == spec.COVERAGE_DECLARATION


def test_concentration_top_n_caps_items():
    block = insight.concentration_block(_rows(), top_n=1, private_domains=_PRIVATE, sensitive_domains=_SENSITIVE)
    assert len(block["items"]) == 1
    assert block["top_n"] == 1


def test_url_ranking_empty_rows():
    assert insight.url_ranking([]) == []


def test_domain_ranking_empty_rows():
    assert insight.domain_ranking([]) == []


def test_heatmap_counts_empty_rows():
    assert insight.heatmap_counts([], offset_minutes=0, weekday_start="monday") == {}


def test_sessions_block_empty_rows():
    block = insight.sessions_block([], gap_minutes=30, top_n=5)
    assert block["session_count"] == 0
    assert block["size_histogram"] == {}


def test_forgotten_block_items_carry_visit_ids():
    block = insight.forgotten_block(
        _forgotten_rows(10), days_threshold=5, min_visits=2, min_distinct_days=2,
        today_local_date="2026-01-15", offset_minutes=0,
        private_domains=_PRIVATE, sensitive_domains=_SENSITIVE,
    )
    assert block["items"][0]["visit_ids"] == [1, 2, 3]


def test_cluster_kept_terms_members_sorted():
    result = cluster.cluster_topics(_cluster_rows(), options=_cluster_options())
    for term, members in result.kept_terms.items():
        members = list(members)
        assert members == sorted(members)


def test_research_paths_empty_rows():
    assert cluster.research_paths([], gap_minutes=30) == ()


def test_search_empty_rows_no_hits():
    result = search.run_search([], search.SearchQuery(text="指南"), ngram_n=2)
    assert result.matched == 0 and result.hits == ()


def test_search_casefold_disabled():
    assert search.text_matches("Rust", "rustLang", 2, casefold=False) is False


def test_normalize_rows_single_row_unchanged():
    rows = _rows()[:1]
    normalized = norm.normalize_rows(rows)
    assert normalized == rows


def test_host_of_ipv4_style_host():
    assert norm.host_of("http://localhost:9222/devtools") == "localhost"


def test_session_span_zero_for_single_step():
    result = sessions.split_sessions(_rows()[2:], 30)
    assert result[0].span_us == 0


def test_thresholds_modes_match_runtime():
    assert SETTINGS["modes"] == list(spec.MODES)


def test_sample_options_carry_required_keys():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    for key in ("timezone_utc_offset_minutes", "session_gap_minutes", "today_local_date", "weekday_start", "search_ngram_n"):
        assert key in data["options"]


def test_summary_evidence_counts():
    rows = _rows() + [_row(9, "https://private.example.test/x", "私", "private.example.test", 0)]
    records = _evaluate(_options(rows=rows))
    summary = next(r for r in records if r.path == "summary")
    assert summary.evidence["records"] == 4
    assert summary.evidence["private_excluded"] == 1
    assert summary.evidence["visible"] == 3


def test_cluster_top_terms_truncation():
    result = cluster.cluster_topics(_cluster_rows(), options=_cluster_options(cluster_top_terms=1))
    for item in result.clusters:
        assert len(item.terms) <= 1


def test_term_rank_key_deterministic_ties():
    key_a = cluster.term_rank_key("alpha", df=2, document_count=8)
    key_b = cluster.term_rank_key("alpha", df=2, document_count=8)
    assert key_a == key_b


def test_audit_mode_emits_privacy_records_when_private_present():
    rows = _rows() + [_row(9, "https://private.example.test/x", "私", "private.example.test", 0)]
    records = _evaluate(_options(rows=rows))
    assert [r for r in records if r.path.startswith("privacy.private.")]
