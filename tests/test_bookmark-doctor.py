"""``bookmark-doctor`` 器官的无损测试（迁自 10-16-bookmark-doctor）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：URL 规范化六步流水线、
状态分类引擎（通用映射表 / 规则优先 / 保守冲突 / 首跳或终态命中）、锚点硬门、
去重引擎（保留策略固定、绝不自动删、fragment_variant）、未访问画像分档
（缺失不猜补、参考日不读时钟）、三态口径（dead 是唯一阻断，反爬/风控一律待复核）。

**没迁的部分逐条写在 ``docs/bookmark-doctor.md`` §6 的处置表里**（Netscape/Chrome
解析、网络探测、HTML 报告、导回写盘、CLI、零字面量门）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 13 个测试文件剔除 ``bench|cli|parse`` 后 9 文件实跑
**X = 106 passed**（旧层 AST ``test_`` 函数 86）。
"""

from __future__ import annotations

import ast
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
from byteproof.auditors.bookmark_doctor import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    aging,
    audit,
    classify,
    dedupe,
    normalize,
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
    RuleMissing,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "bookmark-doctor"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "bookmark-doctor.basis.json"
THRESHOLDS_PATH = DATA_DIR / "bookmark-doctor.thresholds.json"
SAMPLE = ROOT / "samples" / "bookmark-doctor.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

_TRACKED = {
    "exact": ["share_token", "spm", "scm", "fbclid", "gclid", "igshid"],
    "prefixes": ["utm_", "share_"],
}

_RULE_403 = {
    "id": "R-TEST-403",
    "match": {"host_suffix": "example.com", "http_status": 403},
    "disposition": "review",
    "reason": "http_403_botguard",
    "anchor": {"observation_id": "obs-1"},
}
_RULE_DEAD = {
    "id": "R-TEST-DEAD",
    "match": {"host_suffix": "example.com", "http_status": 403},
    "disposition": "dead",
    "reason": "rule_dead",
    "anchor": {"observation_id": "obs-1"},
}


# ================================================================== 夹具助手
def _bm(bid, url, add_date=100, source="s.html"):
    return {
        "id": bid,
        "title": bid,
        "url": url,
        "add_date": add_date,
        "folder": [],
        "source": source,
    }


def _obs(url, status=200, first=None, error=None, final=None):
    record = {"url": url, "http_status": status, "error_class": error}
    if first is not None:
        record["first_hop_status"] = first
    if final is not None:
        record["final_url"] = final
    return record


def _subject(mode="audit", bookmarks=None, observations=None, rules=None, ledger=None, **extra):
    subject = {
        "mode": mode,
        "bookmarks": bookmarks if bookmarks is not None else [_bm("a", "https://x.com/1")],
        "observations": observations if observations is not None else [_obs("https://x.com/1")],
        "degrade_rules": rules or [],
        "observations_ledger": ledger or {"observations": [{"id": "obs-1", "check_status": "verified"}]},
        "tracked_query_params": _TRACKED,
        "aging": {"tiers_days": [365, 730, 1095]},
        "options": {"aging_date": "2026-10-15"},
    }
    subject.update(extra)
    return subject


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


def _aging_days(base, days):
    return int(
        datetime.datetime.combine(
            base - datetime.timedelta(days=days), datetime.time.min
        )
        .replace(tzinfo=datetime.timezone.utc)
        .timestamp()
    )


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG


def test_pack_declares_mode_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "bookmark_doctor" in BUILTIN_MODULES


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


def test_thresholds_link_severity_matches_runtime():
    assert SETTINGS["link_verdict_severity"] == spec.VERDICT_SEVERITY


def test_thresholds_conservative_order_matches_runtime():
    assert SETTINGS["conservative_order"] == spec.CONSERVATIVE_ORDER


def test_thresholds_generic_reasons_match_runtime():
    reasons = SETTINGS["generic_reasons"]
    assert reasons["http_2xx"] == "alive"
    assert reasons["http_404"] == "dead"
    assert reasons["http_4xx_blocked"] == "review"
    assert reasons["cdn_blocked"] == "review"


def test_thresholds_statuses_match_runtime():
    assert SETTINGS["review_4xx_statuses"] == list(classify.REVIEW_4XX_STATUSES)
    assert SETTINGS["cdn_blocked_statuses"] == list(classify.CDN_BLOCKED_STATUSES)


def test_thresholds_anchor_reasons_match_runtime():
    assert SETTINGS["anchor_gate_reasons"] == [
        classify.REASON_ANCHOR_MISSING,
        classify.REASON_ANCHOR_NOT_VERIFIED,
    ]


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("bd-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== URL 规范化六步流水线
def test_scheme_http_to_https():
    assert normalize.normalize_url("http://example.com/a", _TRACKED) == "https://example.com/a"


def test_host_lowercase_and_default_port():
    assert normalize.normalize_url("https://EXAMPLE.com:443/a", _TRACKED) == "https://example.com/a"
    assert normalize.normalize_url("http://EXAMPLE.com:80/a", _TRACKED) == "https://example.com/a"


def test_non_default_port_kept():
    assert normalize.normalize_url("https://example.com:8080/a", _TRACKED) == "https://example.com:8080/a"


def test_port_80_judged_by_original_scheme():
    # http://host:80 → https://host（按原 scheme 的默认端口判，不是保留 80）
    assert normalize.normalize_url("http://example.com:80/a", _TRACKED) == "https://example.com/a"


def test_path_trailing_slash_and_collapsing():
    assert normalize.normalize_url("https://example.com/a/", _TRACKED) == "https://example.com/a"
    assert normalize.normalize_url("https://example.com//a///b", _TRACKED) == "https://example.com/a/b"
    assert normalize.normalize_url("https://example.com/", _TRACKED) == "https://example.com/"


def test_path_distinct_not_merged():
    assert normalize.normalize_url("https://example.com/a", _TRACKED) != normalize.normalize_url(
        "https://example.com/b", _TRACKED
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://example.com/p?utm_source=x&id=2", "https://example.com/p?id=2"),
        ("https://example.com/p?share_token=abc&id=2", "https://example.com/p?id=2"),
        ("https://example.com/p?spm=a&scm=b&id=2", "https://example.com/p?id=2"),
        ("https://example.com/p?fbclid=z", "https://example.com/p"),
    ],
)
def test_tracked_params_stripped(raw, expected):
    assert normalize.normalize_url(raw, _TRACKED) == expected


def test_query_params_sorted():
    assert normalize.normalize_url("https://example.com/p?b=2&a=1", _TRACKED) == normalize.normalize_url(
        "https://example.com/p?a=1&b=2", _TRACKED
    )


def test_blank_query_value_kept():
    assert normalize.normalize_url("https://example.com/p?a=", _TRACKED) == "https://example.com/p?a="


def test_fragment_stripped_but_recoverable():
    assert normalize.normalize_url("https://example.com/p#sec", _TRACKED) == "https://example.com/p"
    assert normalize.fragment_of("https://example.com/p#sec") == "sec"
    assert normalize.fragment_of("https://example.com/p") is None


def test_shortlink_known_mapping_applied():
    mapping = {"https://short.cn/abc": "https://x.com/real"}
    assert normalize.normalize_url("https://short.cn/abc", _TRACKED, mapping) == "https://x.com/real"


def test_shortlink_unknown_not_guessed():
    assert normalize.normalize_url("https://short.cn/other", _TRACKED, {"a": "b"}) == "https://short.cn/other"


def test_original_url_never_rewritten():
    url = "https://Example.com:443/A/?utm_source=x#frag"
    normalize.normalize_url(url, _TRACKED)
    assert url == "https://Example.com:443/A/?utm_source=x#frag"


# ================================================================== 分类引擎：通用映射
@pytest.mark.parametrize(
    "status,verdict,reason",
    [
        (200, "alive", "http_2xx"),
        (204, "alive", "http_2xx"),
        (302, "review", "redirect_unresolved"),
        (404, "dead", "http_404"),
        (410, "dead", "http_410"),
        (403, "review", "http_4xx_blocked"),
        (401, "review", "http_4xx_blocked"),
        (405, "review", "http_4xx_blocked"),
        (429, "review", "http_4xx_blocked"),
        (451, "review", "http_4xx_blocked"),
        (521, "review", "cdn_blocked"),
        (523, "review", "cdn_blocked"),
        (500, "review", "http_5xx"),
        (503, "review", "http_5xx"),
        (400, "review", "http_other"),
    ],
)
def test_generic_mapping_table(status, verdict, reason):
    assert classify.generic_verdict({"http_status": status, "error_class": None}) == (verdict, reason)


@pytest.mark.parametrize(
    "error_class",
    ["dns_failure", "timeout", "tls_error", "connection_error", "too_many_redirects", "redirect_loop"],
)
def test_error_class_always_review(error_class):
    assert classify.generic_verdict({"http_status": None, "error_class": error_class}) == ("review", error_class)


def test_probe_incomplete_conservative():
    # 无状态无错误：保守 review，绝不静默判 alive
    assert classify.generic_verdict({"http_status": None, "error_class": None}) == ("review", "probe_incomplete")


def test_rule_beats_generic():
    record = {"url": "https://www.example.com/p", "http_status": 403, "error_class": None}
    result = classify.classify(record, [_RULE_403])
    assert result == {"verdict": "review", "reason": "http_403_botguard", "rule_id": "R-TEST-403", "conflict": None}


def test_no_rules_falls_to_generic():
    record = {"url": "https://www.example.com/p", "http_status": 403, "error_class": None}
    result = classify.classify(record, [])
    assert result["verdict"] == "review"
    assert result["reason"] == "http_4xx_blocked"
    assert result["rule_id"] is None


def test_host_suffix_boundary_positive():
    record = {"url": "https://www.example.com/p", "http_status": 403, "error_class": None}
    assert classify.match_rule(record, _RULE_403) is True
    assert classify.match_rule({**record, "url": "https://example.com/p"}, _RULE_403) is True


def test_host_suffix_boundary_negative():
    record = {"url": "https://notexample.com/p", "http_status": 403, "error_class": None}
    assert classify.match_rule(record, _RULE_403) is False


def test_status_mismatch_rule_not_hit():
    record = {"url": "https://example.com/p", "http_status": 500, "error_class": None}
    assert classify.match_rule(record, _RULE_403) is False


def test_match_rule_first_hop_status_hits_after_redirect():
    # 风控链：首跳 302（风控）、终态 200（访客页）→ 规则按首跳命中
    record = {
        "url": "https://example.com/p",
        "first_hop_status": 302,
        "http_status": 200,
        "error_class": None,
    }
    assert classify.match_rule(record, _RULE_403) is False
    rule_302 = {"id": "R-302", "match": {"host_suffix": "example.com", "http_status": 302}, "disposition": "review", "reason": "risk_chain"}
    assert classify.match_rule(record, rule_302) is True


def test_match_rule_terminal_status_still_hits():
    record = {"url": "https://example.com/p", "first_hop_status": 200, "http_status": 403, "error_class": None}
    assert classify.match_rule(record, _RULE_403) is True


def test_conflict_conservative_review_wins():
    pairs = [("dead", "r1", "A"), ("review", "r2", "B")]
    verdict, reason, note = classify._conservative(pairs)
    assert verdict == "review"
    # 处置不一致 → 必须留冲突备注（降级不等于静默）
    assert note and note.startswith("rule_conflict:")


def test_conflict_dead_beats_alive():
    pairs = [("alive", "r1", "A"), ("dead", "r2", "B")]
    verdict, reason, note = classify._conservative(pairs)
    assert verdict == "dead"
    assert note and note.startswith("rule_conflict:")


def test_conflict_note_is_deterministic():
    pairs = [("alive", "r1", "B"), ("dead", "r2", "A")]
    _, _, note = classify._conservative(pairs)
    assert note == "rule_conflict:A=r2|B=r1"


# ================================================================== 锚点硬门
def _rule_with_anchor(rule_id, obs_id):
    return {
        "id": rule_id,
        "match": {"host_suffix": "example.com", "http_status": 403},
        "disposition": "review",
        "reason": "degrade",
        "anchor": {"observation_id": obs_id},
    }


def test_anchor_gate_all_rules_enabled():
    ledger = {"observations": [{"id": "obs-1", "check_status": "verified"}]}
    enabled, disabled = classify.apply_anchor_gate({"degrade_rules": [_rule_with_anchor("R1", "obs-1")]}, ledger)
    assert [r["id"] for r in enabled] == ["R1"]
    assert disabled == []


def test_anchor_gate_rejects_pending():
    ledger = {"observations": [{"id": "obs-1", "check_status": "pending"}]}
    enabled, disabled = classify.apply_anchor_gate({"degrade_rules": [_rule_with_anchor("R1", "obs-1")]}, ledger)
    assert enabled == []
    assert disabled == [{"id": "R1", "reason": "anchor_not_verified", "observation_id": "obs-1", "check_status": "pending"}]


def test_anchor_gate_rejects_missing_observation():
    enabled, disabled = classify.apply_anchor_gate({"degrade_rules": [_rule_with_anchor("R1", "obs-x")]}, {"observations": []})
    assert enabled == []
    assert disabled == [{"id": "R1", "reason": "anchor_missing", "observation_id": "obs-x"}]


def test_anchor_gate_mixed_list():
    ledger = {"observations": [{"id": "obs-1", "check_status": "verified"}]}
    rules = [_rule_with_anchor("R-ok", "obs-1"), _rule_with_anchor("R-bad", "obs-none")]
    enabled, disabled = classify.apply_anchor_gate({"degrade_rules": rules}, ledger)
    assert [r["id"] for r in enabled] == ["R-ok"]
    assert [d["id"] for d in disabled] == ["R-bad"]


def test_anchor_gate_directly_controls_check():
    # 锚点未验证的规则不得参与判定：规则本身想判 dead 也不行
    subject = _subject(
        observations=[_obs("https://www.example.com/p", status=403)],
        rules=[_rule_with_anchor("R-DEAD", "obs-none")],
        ledger={"observations": []},
    )
    hits = [r for r in _records(subject, spec.RULE_LINK_DEAD) if r.evidence.get("reason") == "rule_dead"]
    assert hits == []
    disabled = _records(subject, spec.RULE_ANCHOR_DISABLED)
    assert len(disabled) == 1
    assert disabled[0].evidence["reason"] == "anchor_missing"


# ================================================================== 去重引擎
def test_tracking_variant_group_merged():
    groups = dedupe.build_duplicate_groups(
        [
            _bm("a", "https://x.com/posts/1?utm_source=share&utm_medium=link", 100),
            _bm("b", "https://x.com/posts/1/?share_token=abc4", 200),
        ],
        _TRACKED,
    )
    assert len(groups) == 1
    assert groups[0]["key"] == "https://x.com/posts/1"
    assert [m["id"] for m in groups[0]["members"]] == ["a", "b"]


def test_fragment_variant_marked():
    groups = dedupe.build_duplicate_groups(
        [_bm("a", "https://x.com/p/1"), _bm("b", "https://x.com/p/1#daily")],
        _TRACKED,
    )
    assert len(groups) == 1
    assert groups[0]["fragment_variant"] is True


def test_fragment_same_not_marked():
    groups = dedupe.build_duplicate_groups(
        [_bm("a", "https://x.com/p/1#daily"), _bm("b", "https://x.com/p/1#daily")],
        _TRACKED,
    )
    assert groups[0]["fragment_variant"] is False


def test_keep_prefers_https():
    groups = dedupe.build_duplicate_groups(
        [_bm("h", "http://x.com/p", 50), _bm("s", "https://x.com/p", 100)],
        _TRACKED,
    )
    assert groups[0]["keep"]["id"] == "s"


def test_keep_prefers_no_tracked_param():
    groups = dedupe.build_duplicate_groups(
        [_bm("t", "https://x.com/p?utm_source=x", 50), _bm("c", "https://x.com/p", 100)],
        _TRACKED,
    )
    assert groups[0]["keep"]["id"] == "c"


def test_keep_prefers_earliest_add_date_then_file_order():
    groups = dedupe.build_duplicate_groups(
        [_bm("late", "https://x.com/p", 200), _bm("early", "https://x.com/p", 50)],
        _TRACKED,
    )
    assert groups[0]["keep"]["id"] == "early"
    groups = dedupe.build_duplicate_groups(
        [_bm("x", "https://x.com/q", None), _bm("y", "https://x.com/q/", None)],
        _TRACKED,
    )
    assert groups[0]["keep"]["id"] == "x"


def test_unique_urls_no_groups():
    assert dedupe.build_duplicate_groups([_bm("a", "https://x.com/1"), _bm("b", "https://x.com/2")], _TRACKED) == []


def test_final_url_takes_priority():
    groups = dedupe.build_duplicate_groups(
        [_bm("a", "https://short.cn/abc"), _bm("b", "https://x.com/real")],
        _TRACKED,
        check_records=[{"url": "https://short.cn/abc", "final_url": "https://x.com/real"}],
    )
    assert len(groups) == 1


def test_never_modifies_input():
    bms = [_bm("a", "https://x.com/p/1?utm_source=x"), _bm("b", "https://x.com/p/1/")]
    original_urls = [bm["url"] for bm in bms]
    dedupe.build_duplicate_groups(bms, _TRACKED)
    assert [bm["url"] for bm in bms] == original_urls


def test_group_ids_stable_and_ordered():
    groups = dedupe.build_duplicate_groups(
        [_bm("a", "https://x.com/1?utm_source=x"), _bm("b", "https://x.com/1"), _bm("c", "https://y.com/1?utm_source=x"), _bm("d", "https://y.com/1")],
        _TRACKED,
    )
    assert [g["group_id"] for g in groups] == ["dup-0001", "dup-0002"]


def test_check_mode_emits_duplicate_records():
    subject = _subject(
        mode="dedupe",
        bookmarks=[_bm("a", "https://x.com/1?utm_source=x"), _bm("b", "https://x.com/1")],
        observations=[],
    )
    hits = _records(subject, spec.RULE_DUPLICATE_GROUP)
    assert len(hits) == 1
    assert hits[0].verdict == WARN
    assert hits[0].evidence["keep"]["id"] == "b"  # 无追踪参数优先（a 更早但带 utm）


# ================================================================== 未访问画像
def test_aging_tiers_loaded():
    tiers = aging.load_aging_tiers({"aging": {"tiers_days": [365, 730, 1095]}})
    assert tiers == [365, 730, 1095]


def test_aging_config_missing_rejected():
    with pytest.raises(aging.AgingConfigError):
        aging.load_aging_tiers({})
    with pytest.raises(aging.AgingConfigError):
        aging.load_aging_tiers({"aging": {}})
    with pytest.raises(aging.AgingConfigError):
        aging.load_aging_tiers({"aging": {"tiers_days": [730, 365]}})
    with pytest.raises(aging.AgingConfigError):
        aging.load_aging_tiers({"aging": {"tiers_days": [0]}})
    with pytest.raises(aging.AgingConfigError):
        aging.load_aging_tiers({"aging": {"tiers_days": [365, True]}})


def test_aging_profile_tiers_and_unknown():
    base = datetime.date(2026, 10, 15)
    bookmarks = [
        _bm("a", "http://x/1", add_date=_aging_days(base, 400)),
        _bm("b", "http://x/2", add_date=_aging_days(base, 800)),
        _bm("c", "http://x/3", add_date=_aging_days(base, 10)),
        _bm("d", "http://x/4", add_date=None),
        _bm("e", "http://x/5", add_date=_aging_days(base, 1300)),
    ]
    profile = aging.build_aging_profile(bookmarks, [365, 730, 1095], base)
    assert profile["as_of_date"] == "2026-10-15"
    assert [t["tier"] for t in profile["tiers"]] == ["1年+", "2年+", "3年+"]
    assert [t["count"] for t in profile["tiers"]] == [1, 1, 1]
    assert profile["within"]["count"] == 1
    assert profile["unknown_add_date"]["count"] == 1
    assert profile["unknown_add_date"]["ids"] == ["d"]
    assert "以添加时间近似未访问" in profile["note"]


def test_aging_tier_label_converted_not_literal():
    tiers = [100, 200, 400]
    base = datetime.date(2026, 1, 1)
    profile = aging.build_aging_profile(
        [_bm("x", "http://x/1", add_date=_aging_days(base, 150)), _bm("y", "http://x/2", add_date=_aging_days(base, 450))],
        tiers,
        base,
    )
    assert [t["tier"] for t in profile["tiers"]] == ["1年+", "2年+", "4年+"]


def test_aging_date_from_options_not_clock():
    subject = _subject(mode="aging", options={"aging_date": "2026-10-15"})
    records = _records(subject, spec.RULE_AGING_TIER)
    assert all(r.evidence["as_of_date"] == "2026-10-15" for r in records)


def test_aging_requires_options_date():
    subject = _subject(mode="aging")
    subject["options"] = {}
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_aging_invalid_date_rejected():
    subject = _subject(mode="aging", options={"aging_date": "2026-13-99"})
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_aging_empty_tiers_not_emitted():
    subject = _subject(mode="aging", bookmarks=[_bm("a", "http://x/1", add_date=_aging_days(datetime.date(2026, 10, 15), 10))])
    subject["options"] = {"aging_date": "2026-10-15"}
    records = _records(subject, spec.RULE_AGING_TIER)
    assert [r.evidence["tier"] for r in records] == ["1年内"]


# ================================================================== 三态账本映射与模式
def test_dead_is_the_only_blocking_link_verdict():
    subject = _subject(observations=[_obs("https://x.com/1", status=404)])
    records = _records(subject, spec.RULE_LINK_DEAD)
    assert len(records) == 1
    assert records[0].verdict == ERROR
    assert records[0].evidence["reason"] == "http_404"


def test_review_is_warn_and_alive_is_info():
    subject = _subject(
        observations=[_obs("https://x.com/1", status=403), _obs("https://x.com/2", status=200)]
    )
    review = _records(subject, spec.RULE_LINK_REVIEW)
    alive = _records(subject, spec.RULE_LINK_ALIVE)
    assert len(review) == 1 and review[0].verdict == WARN
    assert len(alive) == 1 and alive[0].verdict == INFO


def test_review_only_does_not_block():
    subject = _subject(observations=[_obs("https://x.com/1", error="dns_failure")])
    assert _report(subject).exit_code() == EXIT_OK


def test_duplicate_only_does_not_block():
    subject = _subject(
        mode="dedupe",
        bookmarks=[_bm("a", "https://x.com/1?utm_source=x"), _bm("b", "https://x.com/1")],
        observations=[],
    )
    assert _report(subject).exit_code() == EXIT_OK


def test_conflict_record_emitted():
    subject = _subject(
        observations=[_obs("https://www.example.com/p", status=403)],
        rules=[_RULE_403, _RULE_DEAD],
    )
    conflicts = _records(subject, spec.RULE_CONFLICT)
    assert len(conflicts) == 1
    assert conflicts[0].verdict == WARN
    # 保守序：review > dead > alive → review 赢
    verdicts = [r.evidence.get("verdict") for r in _records(subject) if r.path == "observations[0]"]
    assert verdicts == ["review"]


def test_mode_check_only_skips_dedupe_and_aging():
    subject = _subject(mode="check")
    records = _evaluate(subject)
    assert not [r for r in records if r.path.startswith("dedupe.")]
    assert not [r for r in records if r.path.startswith("aging.")]


def test_mode_dedupe_only():
    subject = _subject(mode="dedupe")
    records = _evaluate(subject)
    assert not [r for r in records if r.path.startswith("observations")]
    assert not [r for r in records if r.path.startswith("aging.")]


def test_mode_aging_only():
    subject = _subject(mode="aging")
    records = _evaluate(subject)
    assert not [r for r in records if r.path.startswith("dedupe.")]
    assert not [r for r in records if r.path.startswith("observations")]


def test_mode_audit_runs_all_three():
    subject = _subject(
        bookmarks=[_bm("a", "https://x.com/1?utm_source=x"), _bm("b", "https://x.com/1", add_date=None)],
        observations=[_obs("https://x.com/1", status=200), _obs("https://x.com/1?utm_source=share", status=200)],
    )
    records = _evaluate(subject)
    assert [r for r in records if r.path.startswith("observations")]
    assert [r for r in records if r.path.startswith("dedupe.")]
    assert [r for r in records if r.path.startswith("aging.")]
    assert [r for r in records if r.path == "summary"]


def test_mode_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(mode="export"))


# ================================================================== 输入校验与退出码
def test_missing_bookmarks_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit"})


def test_bookmark_without_url_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(bookmarks=[{"id": "a"}]))


def test_observations_not_list_rejected():
    subject = _subject(observations="oops")
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_exit_code_zero_clean(tmp_path):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject(), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_OK


def test_exit_code_one_dead_link(tmp_path):
    subject = _subject(observations=[_obs("https://x.com/1", status=404)])
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_BLOCKED


def test_exit_code_two_invalid_input(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "audit"}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT


def test_exit_code_three_missing_rule(tmp_path):
    basis_path = tmp_path / "empty.basis.json"
    basis_path.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject(), ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["check", SLUG, "--input", str(path), "--basis", str(basis_path)])
    assert rc == EXIT_CONTRACT


def test_records_unique_ids():
    subject = _subject(
        bookmarks=[_bm("a", "https://x.com/1?utm_source=x"), _bm("b", "https://x.com/1", add_date=None)],
        observations=[_obs("https://x.com/1", status=200), _obs("https://x.com/1?utm_source=share", status=200)],
        rules=[_RULE_403, _RULE_DEAD],
    )
    report = _report(subject)
    ids = [r.id for r in report.records]
    assert len(ids) == len(set(ids))


def test_determinism_double_run():
    subject = _subject(
        bookmarks=[_bm("a", "https://x.com/1?utm_source=x"), _bm("b", "https://x.com/1", add_date=None)],
        observations=[_obs("https://x.com/1", status=200)],
    )
    a = json.dumps(_report(subject).as_dict(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_report(subject).as_dict(), ensure_ascii=False, sort_keys=True)
    assert a == b
