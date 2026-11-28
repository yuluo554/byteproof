# -*- coding: utf-8 -*-
"""``core_ref``（文献审计判定内核）的测试：七个 mode + 旧仓函数面逐条钉住。

口径与模块 docstring 一致：旧三级 ``pass|fail|manual_confirm`` 折算
``error|warn|info``；``rule_id`` 只准是二十个白名单值；输入全是 subject 显式事实。
测试自足，不读旧仓文件（只读本模块源码做纯度断言）。
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof.auditors.thesis_audit import core_ref  # noqa: E402

# ============================================================ 夹具
FULL_SOURCE = {
    "container": "Journal of Tests", "year": "2020", "volume": "12",
    "issue": "3", "pages": "10-20", "publisher": "Press",
    "city": "Beijing", "edition": None, "report_no": None,
}


def _author(raw="Zhang San", family="Zhang", given="San"):
    return core_ref.make_author(raw, family, given)


def _card(card_id="a1", entry_type="J", title="Title A", authors=None,
          source=None, identifiers=None, evidence=None, flags=None,
          confidence=1.0, raw=None):
    src = dict(FULL_SOURCE)
    if source:
        src.update(source)
    ev = {"src": "refs"}
    if evidence:
        ev.update(evidence)
    if raw is not None:
        ev["raw"] = raw
    return core_ref.make_ref_card(
        entry_type, authors if authors is not None else [_author()], title,
        source=src, identifiers=identifiers or {}, evidence=ev,
        confidence=confidence, flags=flags, card_id=card_id)


def _assert_shape(findings):
    assert isinstance(findings, list)
    for finding in findings:
        assert set(finding) == {"rule_id", "verdict", "message", "path", "evidence"}
        assert finding["rule_id"] in core_ref.RULE_IDS
        assert finding["verdict"] in core_ref.VERDICTS
        assert isinstance(finding["message"], str) and finding["message"]
        assert isinstance(finding["path"], str) and finding["path"]
        assert isinstance(finding["evidence"], dict)


def _rule_ids(findings):
    return [finding["rule_id"] for finding in findings]


# ============================================================ 契约面
def test_modes_are_the_seven_required():
    assert core_ref.MODES == ("refcheck", "cite", "dedup", "fake", "rec", "library", "review")


def test_rule_ids_whitelist_is_exact():
    expected = {
        "taw-ref-card", "taw-ref-field-required", "taw-ref-type-marker",
        "taw-ref-author-threshold", "taw-ref-page-range", "taw-ref-citation-style",
        "taw-ref-standard-currency", "taw-ref-consistency", "taw-ref-punct",
        "taw-cite-marker", "taw-cite-uncited", "taw-cite-order",
        "taw-dedup-pair", "taw-dedup-merge-conflict", "taw-fake-signal",
        "taw-fake-health", "taw-rec-hint", "taw-lib-tamper",
        "taw-review-cluster", "taw-review-gap",
    }
    assert set(core_ref.RULE_IDS) == expected
    assert len(core_ref.RULE_IDS) == 20


def test_rule_ids_are_unique():
    assert len(set(core_ref.RULE_IDS)) == len(core_ref.RULE_IDS)


def test_verdicts_are_three_level():
    assert core_ref.VERDICTS == ("error", "warn", "info")


def test_unknown_mode_raises_value_error():
    with pytest.raises(ValueError):
        core_ref.evaluate("nope", {})


def test_subject_must_be_dict():
    with pytest.raises(ValueError):
        core_ref.evaluate("refcheck", [])


def test_evaluate_output_shape_is_fixed():
    findings = core_ref.evaluate("refcheck", {"cards": [_card()]})
    _assert_shape(findings)
    assert findings == []


def test_every_mode_emits_only_whitelisted_rule_ids():
    subjects = {
        "refcheck": {"cards": [_card(source={"pages": "30-10"})]},
        "cite": {"cards": [_card(evidence={"label": "1"})], "text": "见 [2]。"},
        "dedup": {"cards": [_card("d1", title="Same"), _card("d2", title="Same")]},
        "fake": {"cards": [_card(identifiers={"doi": "10.7777/x"})]},
        "rec": {"cards": [_card()], "sentence": "title"},
        "library": {"cards": [_card()], "doc_name": "doc"},
        "review": {"entries": [{"id": "e1", "title": "graph network", "year": 2020}]},
    }
    for mode, subject in subjects.items():
        findings = core_ref.evaluate(mode, subject)
        _assert_shape(findings)
        assert all(finding["rule_id"] in core_ref.RULE_IDS for finding in findings)


def test_module_has_no_forbidden_imports():
    source = Path(core_ref.__file__).read_text(encoding="utf-8")
    pattern = r"^\s*(?:import|from)\s+(os|sys|pathlib|json|time|datetime|random|sqlite3)\b"
    assert re.search(pattern, source, re.MULTILINE) is None


def test_module_never_prints():
    source = Path(core_ref.__file__).read_text(encoding="utf-8")
    assert re.search(r"(?<![\w.])print\s*\(", source) is None


def test_module_imports_only_deterministic_helpers():
    source = Path(core_ref.__file__).read_text(encoding="utf-8")
    assert "import hashlib" in source
    assert "import math" in source


# ============================================================ 参数卡构造器
def test_make_author_keeps_none_split():
    author = core_ref.make_author("李四")
    assert author == {"family": None, "given": None, "raw": "李四"}


def test_make_ref_card_fills_none_slots():
    card = _card()
    assert set(card["source"]) == set(core_ref.REF_SOURCE_FIELDS)
    assert card["source"]["edition"] is None
    assert set(card["identifiers"]) == {"doi", "isbn", "url"}
    assert card["identifiers"]["doi"] is None
    assert card["evidence"] == {"src": "refs", "ordinal": None, "label": None, "raw": None}


def test_make_ref_card_strips_internal_whitespace():
    card = _card(source={"pages": " 10 - 20 ", "report_no": " GB 1"},
                 identifiers={"doi": "10.1000 / abc", "isbn": "978 7 0487"})
    assert card["source"]["pages"] == "10-20"
    assert card["source"]["report_no"] == "GB1"
    assert card["identifiers"]["doi"] == "10.1000/abc"
    assert card["identifiers"]["isbn"] == "97870487"


def test_make_ref_card_maps_journal_alias():
    card = core_ref.make_ref_card(
        "J", [_author()], "T", source={"journal": "J X", "year": "2020"},
        evidence={"src": "refs"}, card_id="j1")
    assert card["source"]["container"] == "J X"


def test_make_ref_card_rejects_bad_entry_type():
    with pytest.raises(ValueError):
        _card(entry_type="X")


def test_make_ref_card_rejects_confidence_out_of_range():
    with pytest.raises(ValueError):
        _card(confidence=1.2)


def test_make_ref_card_requires_evidence_src():
    with pytest.raises(ValueError):
        core_ref.make_ref_card("J", [_author()], "T", evidence={}, card_id="x")


def test_validate_ref_card_accepts_valid_card():
    assert core_ref.validate_ref_card(_card()) is None


def test_validate_ref_card_rejects_missing_key():
    card = _card()
    del card["flags"]
    with pytest.raises(ValueError):
        core_ref.validate_ref_card(card)


def test_validate_ref_card_rejects_author_without_raw():
    card = _card()
    card["authors"] = [{"family": "Zhang"}]
    with pytest.raises(ValueError):
        core_ref.validate_ref_card(card)


def test_make_doc_object_fills_anchor_defaults():
    card = core_ref.make_doc_object("figure", "图1", {"para_index": 3})
    assert card["anchor"] == {"para_index": 3, "style": None, "is_ref_field": False}
    assert card["caption"] is None


def test_validate_doc_object_rejects_bad_kind():
    with pytest.raises(ValueError):
        core_ref.make_doc_object("video", "图1", {"para_index": 1})


def test_validate_doc_object_rejects_missing_label():
    with pytest.raises(ValueError):
        core_ref.make_doc_object("table", "", {"para_index": 1})


def test_make_finding_returns_five_keys():
    finding = core_ref.make_finding("taw-ref-punct", "warn", "m", "card:a/punctuation")
    assert set(finding) == {"rule_id", "verdict", "message", "path", "evidence"}
    assert finding["evidence"] == {}


def test_make_finding_rejects_unknown_rule_id():
    with pytest.raises(ValueError):
        core_ref.make_finding("not-whitelisted", "info", "m", "report")


def test_make_finding_rejects_old_status_word():
    with pytest.raises(ValueError):
        core_ref.make_finding("taw-ref-punct", "fail", "m", "report")


def test_summarize_counts_by_verdict_and_rule():
    findings = core_ref.evaluate("refcheck", {"cards": [_card(source={"pages": "30-10"})]})
    summary = core_ref.summarize(findings)
    assert summary["total"] == 1
    assert summary["by_verdict"] == {"error": 1}
    assert summary["by_rule"] == {"taw-ref-page-range": 1}


# ============================================================ refcheck：卡片自检
def test_refcheck_empty_cards_returns_empty():
    assert core_ref.evaluate("refcheck", {"cards": []}) == []


def test_refcheck_clean_card_returns_no_findings():
    assert core_ref.evaluate("refcheck", {"cards": [_card()]}) == []


def test_refcheck_missing_cards_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("refcheck", {})


def test_refcheck_cards_must_be_list():
    with pytest.raises(ValueError):
        core_ref.evaluate("refcheck", {"cards": "not-a-list"})


def test_refcheck_unknown_entry_type_reported():
    card = _card()
    card["entry_type"] = "X"
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-card"]
    assert findings[0]["verdict"] == "error"
    assert findings[0]["path"] == "card:a1/entry_type"


def test_refcheck_confidence_out_of_range_reported():
    card = _card()
    card["confidence"] = 1.5
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-card"]
    assert findings[0]["path"] == "card:a1/confidence"


def test_refcheck_author_without_raw_reported():
    card = _card()
    card["authors"] = [{"family": None, "given": None, "raw": ""}]
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-card"]
    assert "著者项缺 raw" in findings[0]["message"]


def test_refcheck_missing_evidence_src_reported():
    card = _card()
    card["evidence"]["src"] = None
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-card"]
    assert findings[0]["path"] == "card:a1/evidence"


def test_refcheck_doc_name_fills_evidence_src():
    card = _card()
    card["evidence"]["src"] = None
    assert core_ref.evaluate("refcheck", {"cards": [card], "doc_name": "paper"}) == []


def test_refcheck_missing_title_reported():
    card = _card()
    del card["title"]
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-card"]
    assert findings[0]["path"] == "card:a1/title"


def test_refcheck_duplicate_card_id_reported():
    cards = [_card("dup", title="One"), _card("dup", title="Two")]
    findings = core_ref.evaluate("refcheck", {"cards": cards})
    assert "taw-ref-card" in _rule_ids(findings)
    assert any("重复" in finding["message"] for finding in findings)


def test_refcheck_card_id_alias_and_journal_alias():
    subject = {"cards": [{"id": "r1", "entry_type": "J", "title": "T",
                          "authors": [{"family": "Zhang", "given": "San"}],
                          "source": {"journal": "J X", "year": "2020",
                                     "volume": "1", "pages": "1-9"},
                          "evidence": {"src": "refs"}}]}
    assert core_ref.evaluate("refcheck", subject) == []


def test_refcheck_author_string_is_accepted():
    card = _card()
    card["authors"] = ["张三"]
    assert core_ref.evaluate("refcheck", {"cards": [card]}) == []


def test_refcheck_author_type_error_raises():
    card = _card()
    card["authors"] = [123]
    with pytest.raises(ValueError):
        core_ref.evaluate("refcheck", {"cards": [card]})


# ============================================================ refcheck：缺项池
def test_refcheck_field_required_year():
    cards = [_card("a", source={"year": None}), _card("b")]
    findings = core_ref.evaluate("refcheck", {"cards": cards})
    assert _rule_ids(findings) == ["taw-ref-field-required"]
    assert findings[0]["path"] == "card:a/year"
    assert findings[0]["verdict"] == "error"


def test_refcheck_field_required_pages():
    cards = [_card("a", source={"pages": None}), _card("b")]
    findings = core_ref.evaluate("refcheck", {"cards": cards})
    assert findings[0]["path"] == "card:a/pages"


def test_refcheck_field_required_volume():
    cards = [_card("a", source={"volume": None}), _card("b")]
    findings = core_ref.evaluate("refcheck", {"cards": cards})
    assert findings[0]["path"] == "card:a/volume"


def test_refcheck_field_required_skips_non_carrier_field():
    lonely = _card(source={"year": None, "pages": None, "volume": None,
                           "publisher": None, "city": None})
    assert core_ref.evaluate("refcheck", {"cards": [lonely]}) == []


def test_refcheck_field_required_risky_flag_suppresses():
    cards = [_card("a", source={"pages": None}, flags=["hyphen_repaired"]), _card("b")]
    assert core_ref.evaluate("refcheck", {"cards": cards}) == []


def test_refcheck_field_required_year_survives_risky_flag():
    cards = [_card("a", source={"year": None}, flags=["linebreak_repaired"]), _card("b")]
    findings = core_ref.evaluate("refcheck", {"cards": cards})
    assert _rule_ids(findings) == ["taw-ref-field-required"]
    assert findings[0]["path"] == "card:a/year"


def test_refcheck_field_required_uses_inferred_type():
    declared_j = _card("x1", entry_type="J", raw="// 会议论文集, 2020.",
                       source={"publisher": None})
    carrier = _card("x2")
    findings = core_ref.evaluate("refcheck", {"cards": [declared_j, carrier]})
    rules = _rule_ids(findings)
    assert "taw-ref-type-marker" in rules
    required = [finding for finding in findings
                if finding["rule_id"] == "taw-ref-field-required"]
    assert required and required[0]["path"] == "card:x1/publisher"
    assert required[0]["evidence"]["entry_type"] == "C"


def test_refcheck_no_type_inference_uses_declared_type():
    cards = [_card("a", source={"publisher": None}), _card("b")]
    assert core_ref.evaluate("refcheck", {"cards": cards}) == []


# ============================================================ refcheck：标识 / 著者 / 页码
def test_refcheck_type_marker_bib_signature():
    bib = "@article{k,\n  journal = {J of X},\n  year = {2020},\n  volume = {1},\n  pages = {1--9},\n}"
    card = _card("b1", entry_type="C", evidence={"ordinal": 1})
    findings = core_ref.evaluate(
        "refcheck", {"cards": [card], "fmt": "bib", "src_text": bib})
    assert _rule_ids(findings) == ["taw-ref-type-marker"]
    assert findings[0]["evidence"]["inferred"] == "J"


def test_refcheck_type_marker_txt_conference():
    card = _card("c1", entry_type="J", raw="// 会议论文集, 2020.")
    findings = core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt",
                                              "src_text": ""})
    assert _rule_ids(findings) == ["taw-ref-type-marker"]
    assert findings[0]["evidence"]["inferred"] == "C"


def test_refcheck_type_marker_requires_unique_signature():
    ris = "TY  - JOUR\nJO  - Journal\nSN  - 123\nER  -"
    card = _card("r1", entry_type="J", evidence={"ordinal": 1})
    assert core_ref.evaluate(
        "refcheck", {"cards": [card], "fmt": "ris", "src_text": ris}) == []


def test_refcheck_author_threshold_more_than_three():
    authors = [_author("A"), _author("B"), _author("C"), _author("D")]
    card = _card(authors=authors)
    findings = core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt"})
    assert _rule_ids(findings) == ["taw-ref-author-threshold"]
    assert findings[0]["verdict"] == "error"
    assert findings[0]["evidence"]["fix"]["after"] == ["A", "B", "C", "et al"]


def test_refcheck_author_threshold_cjk_uses_deng():
    authors = [_author("甲", None, None), _author("乙", None, None),
               _author("丙", None, None), _author("丁", None, None)]
    findings = core_ref.evaluate("refcheck", {"cards": [_card(authors=authors)],
                                              "fmt": "txt"})
    assert findings[0]["evidence"]["fix"]["after"][-1] == "等"


def test_refcheck_author_threshold_less_than_three_with_deng():
    authors = [_author("A"), _author("B")]
    card = _card(authors=authors, flags=["authors_truncated"])
    findings = core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt"})
    assert _rule_ids(findings) == ["taw-ref-author-threshold"]
    assert "仅 2 位著者" in findings[0]["message"]


def test_refcheck_author_threshold_three_ambiguous_silent_by_default():
    authors = [_author("A"), _author("B"), _author("C")]
    card = _card(authors=authors, flags=["authors_truncated"])
    assert core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt"}) == []


def test_refcheck_author_threshold_three_strict_is_warn():
    authors = [_author("A"), _author("B"), _author("C")]
    cards = [_card(authors=authors, flags=["authors_truncated"])]
    findings = core_ref._check_author_threshold(cards, "refs", "txt", strict=True)
    assert findings[0]["verdict"] == "warn"
    assert findings[0]["evidence"]["ambiguous"] is True


def test_refcheck_author_threshold_not_judged_for_ris():
    authors = [_author("A"), _author("B"), _author("C"), _author("D")]
    card = _card(authors=authors)
    assert core_ref.evaluate("refcheck", {"cards": [card], "fmt": "ris"}) == []


def test_refcheck_page_range_inverted():
    findings = core_ref.evaluate(
        "refcheck", {"cards": [_card(source={"pages": "30-10"})]})
    assert _rule_ids(findings) == ["taw-ref-page-range"]
    assert findings[0]["evidence"]["fix"]["after"] == "10-30"


def test_refcheck_page_range_valid_is_silent():
    assert core_ref.evaluate("refcheck", {"cards": [_card(source={"pages": "10-30"})]}) == []


# ============================================================ refcheck：编码制 / 标准 / 一致性 / 标点
def test_refcheck_citation_style_mixed():
    card = _card(evidence={"label": None}, flags=["author_year_form"])
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-citation-style"]
    assert findings[0]["verdict"] == "error"
    assert findings[0]["path"] == "report"


def test_refcheck_standard_currency_warn():
    card = _card(title="GB/T 7714-2015 著录规则")
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-standard-currency"]
    assert findings[0]["verdict"] == "warn"
    assert findings[0]["evidence"]["new"] == "GB/T 7714-2025"


def test_refcheck_standard_currency_filters_unverified():
    card = _card(title="GB/T 7714-2015 著录规则")
    replacements = [{"old": "GB/T 7714-2015", "new": "GB/T 7714-2025",
                     "identity_status": "pending", "source": "s"}]
    assert core_ref.evaluate("refcheck", {"cards": [card],
                                          "replacements": replacements}) == []


def test_refcheck_consistency_doi_year_mismatch():
    card = _card(source={"year": "2020"}, identifiers={"doi": "10.1000/abc.2019.001"})
    findings = core_ref.evaluate("refcheck", {"cards": [card]})
    assert _rule_ids(findings) == ["taw-ref-consistency"]
    assert findings[0]["evidence"]["doi_year"] == "2019"


def test_refcheck_consistency_skips_noisy_year():
    card = _card(source={"year": "2019SP- 16"}, identifiers={"doi": "10.1000/abc.2019.001"})
    assert core_ref.evaluate("refcheck", {"cards": [card]}) == []


def test_refcheck_punct_cjk_comma():
    card = _card(raw="张三,李四. 题名. 刊名, 2020.")
    findings = core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt"})
    assert _rule_ids(findings) == ["taw-ref-punct"]
    assert findings[0]["verdict"] == "warn"
    assert "中文逗号" in findings[0]["message"]


def test_refcheck_punct_separator_flag():
    card = _card(raw="张三. 题名.", flags=["authors_title_separator_missing"])
    findings = core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt"})
    assert _rule_ids(findings) == ["taw-ref-punct"]
    assert "分隔" in findings[0]["message"]


def test_refcheck_punct_trailing_punct():
    card = _card(raw="张三. 题名. 刊名, 2020..")
    findings = core_ref.evaluate("refcheck", {"cards": [card], "fmt": "txt"})
    assert _rule_ids(findings) == ["taw-ref-punct"]
    assert "末尾" in findings[0]["message"]


def test_refcheck_punct_bib_author_line_missing_comma():
    bib = "@article{k,\n author = {Zhang, San}\n}"
    card = _card("b1", entry_type="J", evidence={"ordinal": 1})
    findings = core_ref.evaluate(
        "refcheck", {"cards": [card], "fmt": "bib", "src_text": bib})
    assert _rule_ids(findings) == ["taw-ref-punct"]
    assert "逗号" in findings[0]["message"]


# ============================================================ refcheck：规则门控 / 修正
def test_refcheck_ruleset_can_deactivate():
    ruleset = {"rules": [{"rule_id": "taw-ref-page-range",
                          "check_type": "page_range", "activation": "gated",
                          "status": "verified"}]}
    subject = {"cards": [_card(source={"pages": "30-10"})], "ruleset": ruleset}
    assert core_ref.evaluate("refcheck", subject) == []


def test_refcheck_ruleset_pending_without_activation_is_inactive():
    ruleset = {"rules": [{"rule_id": "taw-ref-punct", "check_type": "punct",
                          "status": "pending"}]}
    card = _card(raw="张三,李四. 题名.", flags=["authors_title_separator_missing"])
    subject = {"cards": [card], "fmt": "txt", "ruleset": ruleset}
    assert core_ref.evaluate("refcheck", subject) == []


def test_refcheck_ruleset_missing_check_type_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("refcheck", {"cards": [_card()],
                                       "ruleset": {"rules": [{"rule_id": "x"}]}})


def test_refcheck_fmt_invalid_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("refcheck", {"cards": [_card()], "fmt": "docx"})


def test_check_format_exposes_fixes():
    result = core_ref.check_format([_card(source={"pages": "30-10"})],
                                   None, None, None, "refs")
    assert result["fixes"][0]["field"] == "pages"
    assert result["summary"]["total"] == 1


def test_apply_fix_pages():
    card = _card(source={"pages": "30-10"})
    fixed = core_ref.apply_fix(card, {"type": "auto", "field": "pages",
                                      "before": "30-10", "after": "10-30"})
    assert fixed["source"]["pages"] == "10-30"
    assert card["source"]["pages"] == "30-10"


def test_apply_fix_authors_syncs_truncated_flag():
    authors = [_author("A"), _author("B"), _author("C"), _author("D")]
    card = _card(authors=authors)
    fixed = core_ref.apply_fix(card, {"field": "authors",
                                      "before": ["A", "B", "C", "D"],
                                      "after": ["A", "B", "C", "et al"]})
    assert len(fixed["authors"]) == 3
    assert fixed["authors"][-1]["raw"] == "C, et al"
    assert "authors_truncated" in fixed["flags"]
    assert "authors_truncated" not in card["flags"]


def test_apply_fix_never_mutates_input():
    card = _card(source={"pages": "30-10"})
    snapshot = copy.deepcopy(card)
    core_ref.apply_fix(card, {"field": "pages", "after": "10-30"})
    assert card == snapshot


def test_refcheck_is_deterministic():
    cards = [_card("a", source={"pages": "30-10"}),
             _card("b", identifiers={"doi": "10.1000/abc.2019.001"})]
    first = core_ref.evaluate("refcheck", {"cards": cards})
    second = core_ref.evaluate("refcheck", {"cards": cards})
    assert first == second


# ============================================================ cite
def test_expand_numbers_ranges():
    assert core_ref.expand_numbers("2,5-7") == [2, 5, 6, 7]


def test_expand_numbers_fullwidth_comma():
    assert core_ref.expand_numbers("1，3") == [1, 3]


def test_expand_numbers_reversed_range():
    assert core_ref.expand_numbers("7-5") == [5, 6, 7]


def test_expand_numbers_drops_garbage():
    assert core_ref.expand_numbers("abc, 4") == [4]


def test_parse_markers_numeric():
    markers = core_ref.parse_markers("A[1,3-4].")
    assert len(markers) == 1
    assert markers[0]["kind"] == "numeric"
    assert markers[0]["numbers"] == [1, 3, 4]
    assert markers[0]["label"] == "1,3-4"


def test_parse_markers_author_year_paren():
    markers = core_ref.parse_markers("(张三, 2020)")
    assert len(markers) == 1
    assert markers[0]["kind"] == "author_year"
    assert markers[0]["author"] == "张三"
    assert markers[0]["year"] == "2020"


def test_parse_markers_author_year_inline():
    markers = core_ref.parse_markers("张三（2020）")
    assert [marker["kind"] for marker in markers] == ["author_year"]
    assert markers[0]["author"] == "张三"


def test_parse_markers_context_is_its_sentence():
    markers = core_ref.parse_markers("前文。[1] 之后。")
    assert markers[0]["context"] == "[1] 之后"


def test_parse_markers_empty_text():
    assert core_ref.parse_markers("") == []


def test_reconcile_dangling_citation():
    cards = [_card(evidence={"label": "1"})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "[1] 与 [2]。"})
    assert _rule_ids(findings) == ["taw-cite-marker"]
    assert findings[0]["verdict"] == "error"
    assert findings[0]["evidence"]["ref_no"] == 2


def test_reconcile_uncited_reference():
    cards = [_card("a", evidence={"label": "1"}), _card("b", evidence={"label": "2"})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "[1]。"})
    assert _rule_ids(findings) == ["taw-cite-uncited"]
    assert findings[0]["verdict"] == "warn"
    assert findings[0]["path"] == "card:b"


def test_reconcile_ghost_skipped_when_only_dangling():
    cards = [_card(evidence={"label": "1"})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "正文 [9]。"})
    assert _rule_ids(findings) == ["taw-cite-marker"]


def test_reconcile_uncited_skipped_without_numeric_markers():
    cards = [_card(evidence={"label": "1"})]
    assert core_ref.evaluate("cite", {"cards": cards, "text": "无标记。"}) == []


def test_reconcile_order_descending_is_warn():
    cards = [_card("a", evidence={"label": "1"}), _card("b", evidence={"label": "2"})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "[2] 与 [1]。"})
    assert _rule_ids(findings) == ["taw-cite-order"]
    assert findings[0]["verdict"] == "warn"
    assert findings[0]["evidence"]["first_seen"] == [2, 1]


def test_reconcile_order_gap_is_error():
    cards = [_card("a", evidence={"label": "1"}), _card("b", evidence={"label": "3"})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "[1] 与 [3]。"})
    assert _rule_ids(findings) == ["taw-cite-order"]
    assert findings[0]["verdict"] == "error"
    assert findings[0]["evidence"]["missing"] == [2]


def test_reconcile_author_year_missing_author():
    cards = [_card(evidence={"label": None})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "(Smith, 2020)"})
    assert _rule_ids(findings) == ["taw-cite-marker"]
    assert findings[0]["verdict"] == "error"


def test_reconcile_author_year_mismatch_is_warn():
    cards = [_card(evidence={"label": None})]
    findings = core_ref.evaluate("cite", {"cards": cards, "text": "(Zhang, 2021)"})
    assert _rule_ids(findings) == ["taw-cite-marker"]
    assert findings[0]["verdict"] == "warn"
    assert findings[0]["evidence"]["table_years"] == ["2020"]


def test_reconcile_author_year_match_is_silent():
    cards = [_card(evidence={"label": None})]
    assert core_ref.evaluate("cite", {"cards": cards, "text": "(Zhang, 2020)"}) == []


def test_author_key_cjk_and_latin():
    assert core_ref._author_key("张三") == "张"
    assert core_ref._author_key("Smith, J.") == "smith"
    assert core_ref._author_key("") == ""


def test_refs_by_label_uses_first_of_merged_label():
    card = _card("m1", evidence={"label": "2,5"})
    assert core_ref._refs_by_label([card]) == {2: card}


def test_cite_ruleset_deactivates_dangling():
    ruleset = {"rules": [{"rule_id": "taw-cite-order", "check_type": "order_gap",
                          "activation": "active", "status": "pending"}]}
    cards = [_card(evidence={"label": "1"})]
    subject = {"cards": cards, "text": "[9]。", "ruleset": ruleset}
    assert core_ref.evaluate("cite", subject) == []


def test_cite_accepts_explicit_markers():
    cards = [_card(evidence={"label": "1"})]
    markers = [{"kind": "numeric", "numbers": [9], "para": 0, "pos": 5}]
    findings = core_ref.evaluate("cite", {"cards": cards, "markers": markers})
    assert findings[0]["path"] == "marker:body@5"


def test_cite_text_and_markers_conflict_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("cite", {"cards": [], "text": "[1]", "markers": []})


def test_cite_requires_text_or_markers():
    with pytest.raises(ValueError):
        core_ref.evaluate("cite", {"cards": []})


def test_cite_marker_bad_kind_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("cite", {"cards": [],
                                   "markers": [{"kind": "foo", "para": 0}]})


def test_cite_is_deterministic():
    cards = [_card(evidence={"label": "1"})]
    subject = {"cards": cards, "text": "(Zhang, 2021) [2]。", "doc_name": "d"}
    assert core_ref.evaluate("cite", subject) == core_ref.evaluate("cite", subject)


# ============================================================ dedup
def test_norm_title_fullwidth_and_punct():
    assert core_ref.norm_title("ＡＢＣ：测试") == "abc测试"


def test_norm_title_empty():
    assert core_ref.norm_title(None) == ""
    assert core_ref.norm_title("") == ""


def test_norm_doi_strips_and_lowers():
    assert core_ref.norm_doi(" 10.1000/ABC. ") == "10.1000/abc"


def test_norm_doi_none():
    assert core_ref.norm_doi(None) is None


def test_levenshtein_basic():
    assert core_ref._levenshtein("kitten", "sitting") == 3
    assert core_ref._levenshtein("", "abc") == 3
    assert core_ref._levenshtein("same", "same") == 0


def test_author_families_normalizes_case_and_space():
    card = _card(authors=[_author("Zhang San", "Zhang", "San"),
                          _author("李 四", None, None)])
    assert core_ref._author_families(card) == {"zhang", "李四"}


def test_field_conflicts_detects_title_and_source():
    left = _card("l", title="A", source={"year": "2020"})
    right = _card("r", title="B", source={"year": "2021"})
    conflicts = core_ref._field_conflicts(left, right)
    fields = {conflict["field"] for conflict in conflicts}
    assert {"title", "year"} <= fields


def test_field_conflicts_ignore_one_sided_values():
    left = _card("l", identifiers={"doi": "10.1000/x"})
    right = _card("r", identifiers={"doi": None})
    assert core_ref._field_conflicts(left, right) == []


def test_pair_verdict_doi_exact():
    left = _card("l", title="A", identifiers={"doi": "10.1000/x"})
    right = _card("r", title="B", identifiers={"doi": "10.1000/X"})
    verdict, reason, _conflicts = core_ref._pair_verdict(left, right)
    assert verdict == "duplicate"
    assert reason == "DOI 精确匹配"


def test_pair_verdict_title_same_authors_year():
    left = _card("l", title="Graph Network")
    right = _card("r", title="Graph Network")
    verdict, _reason, _conflicts = core_ref._pair_verdict(left, right)
    assert verdict == "duplicate"


def test_pair_verdict_title_same_year_conflict_is_manual():
    left = _card("l", title="Graph Network", source={"year": "2020"})
    right = _card("r", title="Graph Network", source={"year": "2021"})
    verdict, _reason, conflicts = core_ref._pair_verdict(left, right)
    assert verdict == "manual_confirm"
    assert any(conflict["field"] == "year" for conflict in conflicts)


def test_pair_verdict_title_same_without_authors_is_manual():
    left = _card("l", title="Graph Network", authors=[])
    right = _card("r", title="Graph Network", authors=[])
    verdict, _reason, _conflicts = core_ref._pair_verdict(left, right)
    assert verdict == "manual_confirm"


def test_pair_verdict_fuzzy_positive_is_manual():
    left = _card("l", title="graph neural network")
    right = _card("r", title="graph neural networks")
    verdict, reason, conflicts = core_ref._pair_verdict(left, right, 2)
    assert verdict == "manual_confirm"
    assert reason == "标题模糊接近但证据不足以硬合"
    assert any(conflict["field"] == "title" for conflict in conflicts)


def test_pair_verdict_unrelated_is_none():
    left = _card("l", title="deep learning")
    right = _card("r", title="database systems")
    assert core_ref._pair_verdict(left, right) == (None, None, [])


def test_pair_verdict_edit_threshold_boundary():
    left = _card("l", title="aaaaa")
    right = _card("r", title="aaabb")
    assert core_ref._pair_verdict(left, right, 2)[0] == "manual_confirm"
    assert core_ref._pair_verdict(left, right, 1)[0] is None


def test_find_duplicates_cluster_keeps_first_with_fewer_empty_slots():
    cards = [_card("d1", title="Same Title"), _card("d2", title="Same Title"),
             _card("d3", title="Other Title")]
    result = core_ref.find_duplicates(cards)
    assert len(result["clusters"]) == 1
    cluster = result["clusters"][0]
    assert cluster["entry_ids"] == ["d1", "d2"]
    assert cluster["keep"] == "d1"
    assert cluster["drop"] == ["d2"]
    assert _rule_ids(result["findings"]) == ["taw-dedup-pair"]
    assert result["findings"][0]["verdict"] == "error"


def test_find_duplicates_manual_pair():
    cards = [_card("d1", title="Same Title", source={"year": "2020"}),
             _card("d2", title="Same Title", source={"year": "2021"})]
    result = core_ref.find_duplicates(cards)
    assert result["clusters"] == []
    assert len(result["manual_pairs"]) == 1
    assert _rule_ids(result["findings"]) == ["taw-dedup-merge-conflict"]
    assert result["findings"][0]["verdict"] == "warn"
    assert result["findings"][0]["path"] == "pair:d1:d2"


def test_find_duplicates_empty_cards():
    result = core_ref.find_duplicates([])
    assert result == {"clusters": [], "manual_pairs": [], "findings": []}


def test_merge_cluster_absorbs_missing_fields():
    cards = [_card("d1", title="Same Title", source={"volume": None}),
             _card("d2", title="Same Title", source={"volume": "9"})]
    cluster = core_ref.find_duplicates(cards)["clusters"][0]
    merged = core_ref.merge_cluster(cards, cluster)
    assert merged["source"]["volume"] == "9"
    assert merged["card_id"] == "d2"
    assert merged["absorbed_from"] == ["d1"]


def test_merge_cluster_absorbs_field_of_equal_weight_card():
    cards = [_card("d1", title="Same Title", source={"edition": "2nd", "city": None}),
             _card("d2", title="Same Title", source={"edition": None, "city": "Shanghai"})]
    cluster = core_ref.find_duplicates(cards)["clusters"][0]
    merged = core_ref.merge_cluster(cards, cluster)
    assert merged["card_id"] == "d1"
    assert merged["source"]["city"] == "Shanghai"
    assert merged["absorbed_from"] == ["d2"]


def test_merge_cluster_does_not_mutate_cards():
    cards = [_card("d1", title="Same Title", source={"volume": None}),
             _card("d2", title="Same Title", source={"volume": "9"})]
    snapshot = copy.deepcopy(cards)
    cluster = core_ref.find_duplicates(cards)["clusters"][0]
    core_ref.merge_cluster(cards, cluster)
    assert cards == snapshot


def test_dedup_edit_threshold_validation():
    with pytest.raises(ValueError):
        core_ref.find_duplicates([], -1)
    with pytest.raises(ValueError):
        core_ref.find_duplicates([], True)


def test_dedup_is_deterministic():
    cards = [_card("d1", title="Same Title"), _card("d2", title="Same Title")]
    subject = {"cards": cards}
    assert core_ref.evaluate("dedup", subject) == core_ref.evaluate("dedup", subject)


# ============================================================ fake
def test_doi_prefix_extract():
    assert core_ref.doi_prefix(" 10.1234/x") == "10.1234"


def test_doi_prefix_url_is_not_prefix():
    assert core_ref.doi_prefix("https://doi.org/10.1000/x") is None


def test_isbn_checksum_valid_13():
    assert core_ref._isbn_checksum_ok("978-0-306-40615-7") is True


def test_isbn_checksum_invalid_13():
    assert core_ref._isbn_checksum_ok("978-0-306-40615-8") is False


def test_isbn_checksum_valid_10():
    assert core_ref._isbn_checksum_ok("0-306-40615-2") is True


def test_isbn_checksum_bad_length_is_none():
    assert core_ref._isbn_checksum_ok("12345") is None


def test_isbn_publisher_range():
    assert core_ref._isbn_publisher_range("978-7-0487-1234-5") == "978-7-0487"


def test_profile_entry_unknown_doi_prefix_is_medium():
    profile = core_ref.profile_entry(_card(identifiers={"doi": "10.7777/x"}))
    assert [signal["type"] for signal in profile["signals"]] == ["doi_prefix_unknown"]
    assert profile["risk"] == "medium"
    assert profile["penalty"] == 30


def test_profile_entry_known_prefix_is_silent():
    profile = core_ref.profile_entry(_card(identifiers={"doi": "10.1016/x"}))
    assert profile["signals"] == []
    assert profile["risk"] == "low"


def test_profile_entry_isbn_fake_range_exempt():
    card = _card(identifiers={"isbn": "978-7-0487-1234-1"})
    exempt_types = {signal["type"] for signal in core_ref.profile_entry(card)["signals"]}
    assert "isbn_checksum_invalid" not in exempt_types
    strict_types = {signal["type"] for signal in
                    core_ref.profile_entry(card, fake_isbn_ranges=())["signals"]}
    assert "isbn_checksum_invalid" in strict_types


def test_profile_entry_year_out_of_range():
    profile = core_ref.profile_entry(_card(source={"year": "2099"}))
    assert [signal["type"] for signal in profile["signals"]] == ["year_out_of_range"]


def test_profile_entry_year_upper_boundary():
    assert core_ref.profile_entry(_card(source={"year": "2026"}))["signals"] == []


def test_profile_entry_page_inverted_is_structural():
    profile = core_ref.profile_entry(_card(source={"pages": "20-10"}))
    assert [signal["type"] for signal in profile["signals"]] == ["page_range_inverted"]
    assert profile["risk"] == "high"
    assert profile["penalty"] == 15


def test_profile_entry_impossible_combo_journal_isbn():
    card = _card(identifiers={"isbn": "978-0-306-40615-7"})
    profile = core_ref.profile_entry(card)
    assert [signal["type"] for signal in profile["signals"]] == ["impossible_field_combo"]
    assert profile["risk"] == "high"


def test_profile_entry_impossible_combo_book_volume():
    card = _card(entry_type="M", source={"volume": "2"})
    assert [signal["type"] for signal in core_ref.profile_entry(card)["signals"]] == [
        "impossible_field_combo"]


def test_profile_entry_self_referential_title():
    title = "Journal of Tests"
    assert [signal["type"] for signal in core_ref.profile_entry(
        _card(title=title))["signals"]] == ["self_referential_title"]


def test_grade_levels():
    assert core_ref._grade([]) == "low"
    assert core_ref._grade([{"type": "doi_prefix_unknown"}]) == "medium"
    assert core_ref._grade([{"type": "isbn_checksum_invalid"}]) == "high"


def test_health_score_empty_is_100():
    assert core_ref.health_score([]) == 100.0


def test_health_score_averages_penalties():
    assert core_ref.health_score([{"penalty": 30}, {"penalty": 0}]) == 85.0


def test_health_score_clamps_to_zero():
    assert core_ref.health_score([{"penalty": 1000}]) == 0.0


def test_profile_refs_reports_signals_and_health():
    cards = [_card("f1", identifiers={"doi": "10.7777/x"}),
             _card("f2", source={"pages": "20-10"}),
             _card("f3")]
    result = core_ref.profile_refs(cards)
    signals = [finding for finding in result["findings"]
               if finding["rule_id"] == "taw-fake-signal"]
    assert [finding["verdict"] for finding in signals] == ["warn", "error"]
    assert result["health_score"] == 85.0
    assert result["findings"][-1]["rule_id"] == "taw-fake-health"
    assert result["findings"][-1]["verdict"] == "info"


def test_fake_known_prefixes_override():
    cards = [_card(identifiers={"doi": "10.7777/x"})]
    findings = core_ref.evaluate("fake", {"cards": cards,
                                          "known_prefixes": {"10.7777": "synthetic"}})
    assert _rule_ids(findings) == ["taw-fake-health"]


def test_fake_empty_known_prefixes_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("fake", {"cards": [_card()], "known_prefixes": {}})


def test_fake_empty_cards_still_reports_health():
    findings = core_ref.evaluate("fake", {"cards": []})
    assert _rule_ids(findings) == ["taw-fake-health"]
    assert findings[0]["evidence"]["health_score"] == 100.0


def test_fake_is_deterministic():
    cards = [_card(identifiers={"doi": "10.7777/x"})]
    subject = {"cards": cards}
    assert core_ref.evaluate("fake", subject) == core_ref.evaluate("fake", subject)


# ============================================================ rec / renumber
def test_tokenize_mixed_script():
    assert core_ref.tokenize("Deep learning 深度学习") == [
        "deep", "learning", "深", "度", "学", "习", "深度", "度学", "学习"]


def test_tokenize_empty():
    assert core_ref.tokenize("") == []
    assert core_ref.tokenize(None) == []


def test_bm25_search_ranks_relevant_first():
    index = core_ref.BM25().fit([("a", "graph neural network"),
                                 ("b", "database systems")])
    results = index.search("neural network", top_k=2)
    assert results[0]["doc_id"] == "a"
    assert results[0]["score"] > 0
    assert {hit["term"] for hit in results[0]["hits"]} == {"neural", "network"}


def test_bm25_top_k_limits_results():
    index = core_ref.BM25().fit([("a", "graph neural network"),
                                 ("b", "graph neural model")])
    assert len(index.search("graph", top_k=1)) == 1


def test_bm25_empty_query_returns_empty():
    index = core_ref.BM25().fit([("a", "graph")])
    assert index.search("", top_k=5) == []


def test_build_index_uses_card_ids():
    index = core_ref.build_index([_card("c1"), _card("c2")])
    assert [doc_id for doc_id, _tokens in index.docs] == ["c1", "c2"]


def test_recommend_returns_library_subset():
    cards = [_card("c1", title="graph neural network"),
             _card("c2", title="database systems")]
    hits = core_ref.recommend(cards, "neural network", top_k=5)
    assert hits[0]["card_id"] == "c1"
    assert hits[0]["in_library"] is True
    assert {hit["card_id"] for hit in hits} <= {"c1", "c2"}


def test_recommend_no_hit_returns_empty():
    cards = [_card("c1", title="graph neural network")]
    assert core_ref.recommend(cards, "量子纠缠", top_k=5) == []


def test_recommend_top_k_must_be_positive():
    with pytest.raises(ValueError):
        core_ref.recommend([], "x", top_k=0)


def test_renumber_insert_after_target():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.renumber(items, [{"type": "insert", "new_item_id": "x",
                                      "target": "a"}])
    assert plan["new_order"] == ["a", "x", "b"]
    assert plan["n_items"] == 3
    assert plan["consistent"] is True


def test_renumber_insert_before_target():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.renumber(items, [{"type": "insert", "new_item_id": "x",
                                      "target": "b", "before": True}])
    assert plan["new_order"] == ["a", "x", "b"]


def test_renumber_delete_target():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.renumber(items, [{"type": "delete", "target": "a"}])
    assert plan["new_order"] == ["b"]
    assert plan["n_items"] == 1


def test_renumber_missing_target_records_diagnostic():
    items = [{"item_id": "a", "markers": []}]
    plan = core_ref.renumber(items, [{"type": "delete", "target": "z"}])
    assert plan["new_order"] == ["a"]
    assert plan["diagnostics"][0]["kind"] == "delete_target_missing"
    assert core_ref.verify_plan(plan) is True


def test_renumber_duplicate_item_id_is_inconsistent():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.renumber(items, [{"type": "insert", "new_item_id": "a",
                                      "target": "b"}])
    assert plan["new_order"] == ["a", "b", "a"]
    assert plan["consistent"] is False
    assert plan["diagnostics"][0]["kind"] == "duplicate_item_id_after_edits"


def test_renumber_marker_claimed_twice_is_inconsistent():
    items = [{"item_id": "a", "markers": [{"marker_id": "m1"}]},
             {"item_id": "b", "markers": [{"marker_id": "m1"}]}]
    plan = core_ref.renumber(items, [])
    assert plan["consistent"] is False
    assert plan["diagnostics"][0]["kind"] == "marker_claimed_by_multiple_items"


def test_renumber_maps_markers_to_new_numbers():
    items = [{"item_id": "a", "markers": [{"marker_id": "m1"}]},
             {"item_id": "b", "markers": [{"marker_id": "m2"}]}]
    plan = core_ref.renumber(items, [{"type": "delete", "target": "a"}])
    assert plan["mappings"] == [{"marker_id": "m2", "item_id": "b",
                                 "old_no": 2, "new_no": 1}]


def test_renumber_requires_item_id():
    with pytest.raises(ValueError):
        core_ref.renumber([{"markers": []}], [])


def test_verify_plan_rejects_tampered_plan():
    items = [{"item_id": "a", "markers": [{"marker_id": "m1"}]}]
    plan = core_ref.renumber(items, [])
    assert core_ref.verify_plan(plan) is True
    plan["mappings"][0]["new_no"] = 99
    assert core_ref.verify_plan(plan) is False
    assert core_ref.verify_plan(dict(plan, consistent=False)) is False


def test_insert_reference_requires_audited_card():
    with pytest.raises(ValueError):
        core_ref.insert_reference([{"item_id": "a", "markers": []}],
                                  [_card("known")], "new")


def test_insert_reference_appends_to_last_position():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.insert_reference(items, [_card("x")], "x")
    assert plan["new_order"] == ["a", "b", "x"]


def test_insert_reference_at_head_when_before():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.insert_reference(items, [_card("x")], "x", before=True)
    assert plan["new_order"] == ["x", "a", "b"]


def test_insert_reference_into_empty_items():
    plan = core_ref.insert_reference([], [_card("x")], "x")
    assert plan["new_order"] == ["x"]
    assert plan["n_items"] == 1


def test_delete_reference():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    plan = core_ref.delete_reference(items, "a")
    assert plan["new_order"] == ["b"]


def test_edit_matrix_counts_with_two_edits():
    base_ids, cases = core_ref.edit_matrix(3, 2)
    assert base_ids == ["it1", "it2", "it3"]
    assert len(cases) == 22


def test_edit_matrix_counts_with_single_edit():
    _base_ids, cases = core_ref.edit_matrix(3, 1)
    assert len(cases) == 7


def test_edit_matrix_validation():
    with pytest.raises(ValueError):
        core_ref.edit_matrix(0)
    with pytest.raises(ValueError):
        core_ref.edit_matrix(2, 0)


def test_rec_sentence_mode_emits_hints():
    cards = [_card("c1", title="graph neural network"),
             _card("c2", title="database systems")]
    findings = core_ref.evaluate("rec", {"cards": cards, "sentence": "neural network"})
    assert _rule_ids(findings) == ["taw-rec-hint"] * len(findings)
    assert findings[0]["verdict"] == "info"
    assert findings[0]["evidence"]["in_library"] is True


def test_rec_insert_mode_reports_plan():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    subject = {"cards": [_card("x")], "items": items, "new_card_id": "x"}
    findings = core_ref.evaluate("rec", subject)
    assert findings[0]["rule_id"] == "taw-rec-hint"
    assert findings[0]["path"] == "item:x"
    assert findings[0]["evidence"]["plan"]["new_order"] == ["a", "b", "x"]
    assert "新编号 3" in findings[0]["message"]


def test_rec_insert_before_mode():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    subject = {"cards": [_card("x")], "items": items, "new_card_id": "x",
               "before": True}
    findings = core_ref.evaluate("rec", subject)
    assert findings[0]["evidence"]["plan"]["new_order"] == ["x", "a", "b"]
    assert findings[0]["evidence"]["before"] is True


def test_rec_delete_mode():
    items = [{"item_id": "a", "markers": []}, {"item_id": "b", "markers": []}]
    findings = core_ref.evaluate("rec", {"cards": [], "items": items,
                                         "delete_id": "a"})
    assert findings[0]["evidence"]["action"] == "delete"
    assert findings[0]["evidence"]["plan"]["new_order"] == ["b"]


def test_rec_delete_missing_target_is_warn():
    items = [{"item_id": "a", "markers": []}]
    findings = core_ref.evaluate("rec", {"cards": [], "items": items,
                                         "delete_id": "z"})
    assert findings[0]["verdict"] == "info"
    assert findings[1]["verdict"] == "warn"
    assert findings[1]["evidence"]["diagnostic"]["kind"] == "delete_target_missing"


def test_rec_delete_does_not_require_cards():
    items = [{"item_id": "a", "markers": []}]
    findings = core_ref.evaluate("rec", {"items": items, "delete_id": "a"})
    assert findings[0]["evidence"]["plan"]["n_items"] == 0


def test_rec_matrix_does_not_require_cards():
    findings = core_ref.evaluate("rec", {"n_items": 1, "max_edits": 1})
    assert findings[0]["rule_id"] == "taw-rec-hint"
    assert findings[0]["evidence"]["action"] == "matrix"


def test_rec_matrix_mode_all_consistent():
    findings = core_ref.evaluate("rec", {"cards": [], "n_items": 3, "max_edits": 2})
    assert findings[0]["verdict"] == "info"
    assert "全部一致" in findings[0]["message"]
    assert len(findings[0]["evidence"]["cases"]) == 22


def test_rec_requires_a_selector():
    with pytest.raises(ValueError):
        core_ref.evaluate("rec", {"cards": []})


def test_rec_insert_requires_items():
    with pytest.raises(ValueError):
        core_ref.evaluate("rec", {"cards": [_card("x")], "new_card_id": "x"})


def test_rec_top_k_validation():
    with pytest.raises(ValueError):
        core_ref.evaluate("rec", {"cards": [], "sentence": "x", "top_k": 0})


def test_rec_is_deterministic():
    cards = [_card("c1", title="graph neural network")]
    subject = {"cards": cards, "sentence": "neural network"}
    assert core_ref.evaluate("rec", subject) == core_ref.evaluate("rec", subject)


# ============================================================ library
def test_entry_fingerprint_is_stable():
    assert core_ref.entry_fingerprint(_card()) == core_ref.entry_fingerprint(_card())


def test_entry_fingerprint_ignores_author_order():
    first = _card("x", authors=[_author("A"), _author("B")])
    second = _card("y", authors=[_author("B"), _author("A")])
    assert core_ref.entry_fingerprint(first) == core_ref.entry_fingerprint(second)


def test_entry_fingerprint_ignores_whitespace():
    first = _card("x", title="Title A")
    second = _card("y", title=" Title  A ")
    assert core_ref.entry_fingerprint(first) == core_ref.entry_fingerprint(second)


def test_entry_fingerprint_ignores_audit_metadata():
    first = _card("x")
    second = _card("y", flags=["hyphen_repaired"], confidence=0.5,
                   evidence={"label": "9", "ordinal": 3, "raw": "Z"})
    assert core_ref.entry_fingerprint(first) == core_ref.entry_fingerprint(second)


def test_entry_fingerprint_ignores_card_id():
    assert core_ref.entry_fingerprint(_card("x")) == core_ref.entry_fingerprint(_card("y"))


def test_entry_fingerprint_keeps_title_case():
    assert core_ref.entry_fingerprint(_card("x", title="Title")) != \
        core_ref.entry_fingerprint(_card("y", title="title"))


def test_manifest_fingerprint_is_order_independent():
    cards = [_card("a", title="One"), _card("b", title="Two")]
    assert core_ref.manifest_fingerprint(cards) == \
        core_ref.manifest_fingerprint(list(reversed(cards)))


def test_build_manifest_fields():
    cards = [_card("a", evidence={"label": "1"}), _card("b")]
    manifest = core_ref.build_manifest(cards, "paper")
    assert manifest["count"] == 2
    assert manifest["doc"] == "paper"
    assert manifest["schema_version"] == core_ref.SCHEMA_VERSION
    assert [entry["card_id"] for entry in manifest["entries"]] == ["a", "b"]
    assert manifest["entries"][0]["label"] == "1"
    assert len(manifest["fingerprint"]) == 64


def test_detect_tampering_intact():
    cards = [_card("a"), _card("b")]
    manifest = core_ref.build_manifest(cards, "paper")
    report = core_ref.detect_tampering(manifest, cards)
    assert report["intact"] is True
    assert report["unchanged"] == 1  # 两条卡内容相同 → 指纹集合去重后 1 条
    assert report["manifest_changed"] is False


def test_detect_tampering_added_and_removed():
    old_cards = [_card("a")]
    manifest = core_ref.build_manifest(old_cards)
    new_cards = [_card("b", title="Brand New")]
    report = core_ref.detect_tampering(manifest, new_cards)
    assert len(report["added"]) == 1
    assert len(report["removed"]) == 1
    assert report["intact"] is False


def test_detect_tampering_modified_is_add_remove_and_modified():
    old_cards = [_card("a", title="Old Title")]
    manifest = core_ref.build_manifest(old_cards)
    new_cards = [_card("a", title="New Title")]
    report = core_ref.detect_tampering(manifest, new_cards)
    assert len(report["modified"]) == 1
    assert report["modified"][0]["card_id"] == "a"
    assert len(report["added"]) == 1
    assert len(report["removed"]) == 1
    assert report["manifest_changed"] is True


def test_detect_tampering_card_id_change_is_unchanged():
    old_cards = [_card("a")]
    manifest = core_ref.build_manifest(old_cards)
    report = core_ref.detect_tampering(manifest, [_card("z")])
    assert report["intact"] is True
    assert report["added"] == []
    assert report["removed"] == []


def test_library_build_mode_emits_info_manifest():
    findings = core_ref.evaluate("library", {"cards": [_card()], "doc_name": "paper"})
    assert _rule_ids(findings) == ["taw-lib-tamper"]
    assert findings[0]["verdict"] == "info"
    assert findings[0]["evidence"]["manifest"]["doc"] == "paper"


def test_library_tamper_mode_emits_errors():
    old_cards = [_card("a")]
    manifest = core_ref.build_manifest(old_cards, "paper")
    new_cards = [_card("a", title="Changed"), _card("b", title="Brand New")]
    findings = core_ref.evaluate("library", {"old_manifest": manifest,
                                             "new_cards": new_cards})
    assert all(finding["rule_id"] == "taw-lib-tamper" for finding in findings)
    assert any(finding["verdict"] == "error" for finding in findings)
    assert any(finding["path"].startswith("card:a") for finding in findings)


def test_library_intact_emits_single_info():
    cards = [_card("a")]
    manifest = core_ref.build_manifest(cards, "paper")
    findings = core_ref.evaluate("library", {"old_manifest": manifest,
                                             "new_cards": cards})
    assert len(findings) == 1
    assert findings[0]["verdict"] == "info"
    assert findings[0]["evidence"]["change"] == "none"


def test_library_requires_cards_or_manifest():
    with pytest.raises(ValueError):
        core_ref.evaluate("library", {})


def test_library_is_deterministic():
    subject = {"cards": [_card()], "doc_name": "paper"}
    assert core_ref.evaluate("library", subject) == core_ref.evaluate("library", subject)


# ============================================================ review
def test_review_text_includes_abstract_and_keywords():
    text = core_ref._review_text({"title": "T", "abstract": "A",
                                  "keywords": ["k1"], "year": 2020})
    assert "T" in text and "A" in text and "k1" in text
    assert "2020" not in text


def test_tfidf_vectors_shape():
    vectors = core_ref.tfidf_vectors([
        {"entry_id": "e1", "title": "graph neural network"},
        {"entry_id": "e2", "title": "graph neural model"}])
    assert [vector["entry_id"] for vector in vectors] == ["e1", "e2"]
    assert all(vector["norm"] > 0 for vector in vectors)
    assert all(isinstance(vector["vector"], dict) for vector in vectors)


def test_tfidf_norm_is_l2_of_vector():
    vectors = core_ref.tfidf_vectors([{"entry_id": "e", "title": "a b c"}])
    total = sum(weight * weight for weight in vectors[0]["vector"].values())
    assert vectors[0]["norm"] == pytest.approx(total ** 0.5)


def test_cosine_self_is_one():
    vectors = core_ref.tfidf_vectors([
        {"entry_id": "e1", "title": "graph neural network"},
        {"entry_id": "e2", "title": "graph neural network"}])
    assert core_ref.cosine(vectors[0], vectors[1]) == pytest.approx(1.0)


def test_cosine_disjoint_is_zero():
    vectors = core_ref.tfidf_vectors([
        {"entry_id": "e1", "title": "graph network"},
        {"entry_id": "e2", "title": "quantum physics"}])
    assert core_ref.cosine(vectors[0], vectors[1]) == 0.0


def test_cluster_groups_similar_entries():
    entries = [{"entry_id": "e1", "title": "graph neural network"},
               {"entry_id": "e2", "title": "graph neural networks"},
               {"entry_id": "e3", "title": "quantum physics experiment"}]
    clusters = core_ref.cluster(entries)
    sizes = [len(cluster["entry_ids"]) for cluster in clusters]
    assert sizes[0] == 2
    assert clusters[0]["entry_ids"] == ["e1", "e2"]


def test_cluster_zero_threshold_merges_all():
    entries = [{"entry_id": "e1", "title": "graph network"},
               {"entry_id": "e2", "title": "quantum physics"}]
    clusters = core_ref.cluster(entries, threshold=0.0)
    assert len(clusters) == 1
    assert clusters[0]["entry_ids"] == ["e1", "e2"]


def test_cluster_is_deterministic():
    entries = [{"entry_id": "b", "title": "graph network"},
               {"entry_id": "a", "title": "graph networks"}]
    assert core_ref.cluster(entries) == core_ref.cluster(entries)


def test_cluster_threshold_validation():
    with pytest.raises(ValueError):
        core_ref.cluster([], threshold=1.5)
    with pytest.raises(ValueError):
        core_ref.cluster([], threshold=True)


def test_cluster_purity_majority():
    clusters = [{"cluster_id": "c0", "entry_ids": ["a", "b"]}]
    result = core_ref.cluster_purity(clusters, None, {"g1": ["a", "b"]})
    assert result["purity"] == 1.0
    assert result["clusters"][0]["majority"] == "g1"


def test_cluster_purity_split_is_half():
    clusters = [{"cluster_id": "c0", "entry_ids": ["a", "c"]}]
    result = core_ref.cluster_purity(clusters, None, {"g1": ["a"], "g2": ["c"]})
    assert result["purity"] == 0.5


def test_cluster_purity_without_truth_is_zero():
    assert core_ref.cluster_purity([{"cluster_id": "c0", "entry_ids": ["a"]}],
                                   None, {})["purity"] == 0.0


def test_timeline_groups_by_group():
    entries = [{"group": "g1", "year": 2019}, {"group": "g1", "year": 2021},
               {"group": "g2", "year": 2020}]
    assert core_ref.timeline(entries) == {"g1": {"2019": 1, "2021": 1},
                                          "g2": {"2020": 1}}


def test_research_gaps_boundary_emits_when_older():
    entries = [{"group": "g", "year": 2021}]
    gaps = core_ref.research_gaps(entries, now_year=2024, recent_years=3)
    assert gaps[0]["group"] == "g"
    assert gaps[0]["latest_year"] == 2021


def test_research_gaps_boundary_exact_cutoff_is_silent():
    entries = [{"group": "g", "year": 2022}]
    assert core_ref.research_gaps(entries, now_year=2024, recent_years=3) == []


def test_research_gaps_recent_years_validation():
    with pytest.raises(ValueError):
        core_ref.research_gaps([], now_year=2024, recent_years=0)


def test_build_review_assigns_cluster_as_group():
    entries = [{"entry_id": "e1", "title": "graph neural network", "year": 2020},
               {"entry_id": "e2", "title": "graph neural networks", "year": 2021}]
    result = core_ref.build_review(entries, now_year=2024)
    assert result["cluster_count"] == 1
    assert result["timeline"] == {"c0": {"2020": 1, "2021": 1}}
    assert result["purity"]["purity"] == 0.0


def test_build_review_keeps_explicit_group():
    entries = [{"entry_id": "e1", "title": "graph neural network",
                "year": 2020, "group": "custom"}]
    result = core_ref.build_review(entries, now_year=2024)
    assert list(result["timeline"]) == ["custom"]
    assert result["purity"]["purity"] == 1.0


def test_build_review_now_year_defaults_to_latest():
    entries = [{"entry_id": "e1", "title": "a", "year": 2019},
               {"entry_id": "e2", "title": "b", "year": 2021}]
    assert core_ref.build_review(entries)["now_year"] == 2021


def test_review_evaluate_emits_cluster_and_gap():
    entries = [{"id": "e1", "title": "graph neural network", "year": 2015},
               {"id": "e2", "title": "graph neural networks", "year": 2016}]
    findings = core_ref.evaluate("review", {"entries": entries, "now_year": 2024})
    rules = _rule_ids(findings)
    assert "taw-review-cluster" in rules
    assert "taw-review-gap" in rules
    gap = [finding for finding in findings if finding["rule_id"] == "taw-review-gap"][0]
    assert gap["path"] == "cluster:c0"
    assert gap["evidence"]["latest_year"] == 2016
    assert gap["verdict"] == "info"


def test_review_evaluate_no_gap_when_recent():
    entries = [{"id": "e1", "title": "graph neural network", "year": 2023}]
    findings = core_ref.evaluate("review", {"entries": entries, "now_year": 2024})
    assert "taw-review-gap" not in _rule_ids(findings)


def test_review_empty_entries_emits_summary_only():
    findings = core_ref.evaluate("review", {"entries": []})
    assert len(findings) == 1
    assert findings[0]["verdict"] == "info"
    assert findings[0]["path"] == "report"


def test_review_entry_missing_id_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("review", {"entries": [{"title": "T"}]})


def test_review_entry_bad_year_raises():
    with pytest.raises(ValueError):
        core_ref.evaluate("review", {"entries": [{"id": "e", "title": "T",
                                                  "year": "abc"}]})


def test_review_year_string_is_normalized():
    entries = [{"id": "e1", "title": "graph neural network", "year": "2020"}]
    findings = core_ref.evaluate("review", {"entries": entries, "now_year": 2024})
    assert findings[-1]["evidence"]["timeline"] == {"c0": {"2020": 1}}


def test_review_threshold_validation():
    with pytest.raises(ValueError):
        core_ref.evaluate("review", {"entries": [], "threshold": 2.0})


def test_review_recent_years_validation():
    with pytest.raises(ValueError):
        core_ref.evaluate("review", {"entries": [], "recent_years": 0})


def test_review_is_deterministic():
    entries = [{"id": "e1", "title": "graph neural network", "year": 2020}]
    subject = {"entries": entries, "now_year": 2024}
    assert core_ref.evaluate("review", subject) == core_ref.evaluate("review", subject)


def test_review_accepts_ref_id_alias():
    entries = [{"ref_id": "r1", "title": "graph neural network", "year": 2020}]
    findings = core_ref.evaluate("review", {"entries": entries, "now_year": 2024})
    assert findings[0]["evidence"]["entry_ids"] == ["r1"]


def test_evaluate_does_not_mutate_subject():
    subject = {"cards": [_card(source={"pages": "30-10"})],
               "fmt": None, "doc_name": "paper"}
    snapshot = copy.deepcopy(subject)
    core_ref.evaluate("refcheck", subject)
    assert subject == snapshot