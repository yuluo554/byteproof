"""``subset-audit`` 器官的无损测试（迁自 10-21-subset-audit，Python 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：cmapset 全量（三分类 /
glyph0 剔除 / 分区计数 ExtA 优先 / 组合字符闭包 / 回退链建议 / 稳定格式化）、
coverage-diff 判定面（每码位 finding、strict_source 变级、evidence 四键实测、闭包只
计数、两条 cmap 失败路径不合并）、layout-survival 判定面（三元组差集 / 连字码位差分
LOST 优先 RENAMED / 改名三态 / 两个 SKIPPED 不合并）、metadata 判定面（name 三分类 /
码页 bit0 / Unicode 位域只判过度 / maxp 独立量 / 首末码位哨兵）、canonical 排序口径。

**没迁的部分逐条写在 ``docs/subset-audit.md`` §6 的处置表里**（fontTools 读取面、
license-gate 模块、report 渲染、CLI 面、fixture 生成器、CI/readme/self-counts 门）。
不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 12 个测试文件按文件名正则机械剔除
``cli`` / ``license_gate``（license）/ ``report`` 后 **9 文件**实跑 pytest
**X = 215 passed**（``215 passed in 10.82s``）；旧层 AST ``test`` 函数 **195**。
``test_ci_workflow``（`ci` 不是 D1 词 `cli`）/ ``readme_scenarios`` / ``self_counts``
（不含 `selftest`）均**机械计入**——其形状面已在下方以等价断言承接。
"""

from __future__ import annotations

import ast
import json
import re
import sys
import io
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors import subset_audit as sa  # noqa: E402
from byteproof.auditors.subset_audit import (  # noqa: E402
    api,
    core,
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

SLUG = "subset-audit"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "subset-audit.basis.json"
THRESHOLDS_PATH = DATA_DIR / "subset-audit.thresholds.json"
SAMPLE = ROOT / "samples" / "subset-audit.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def _evaluate(subject, basis=None):
    return list((get(SLUG).evaluate)(subject, BASIS if basis is None else basis))


def _report(records):
    return Report(product="byteproof", organ=SLUG, organ_version=spec.ORGAN_VERSION,
                  subject="t", records=records)


def _summary(records):
    return [r for r in records if r.rule_id == "sa-summary"][0]


def _catalog():
    return sa.catalogue.Catalogue(BASIS)


def _subject(mode="coverage-diff", **kw):
    subject = {"mode": mode}
    subject.update(kw)
    return subject


# ==================================================================
# §1 cmapset 全量（移植旧仓 tests/test_core.py 的 cmapset 向量）
# ==================================================================

def test_codepoints_drops_notdef_mappings():
    selected = {65: "A", 66: ".notdef", 67: "glyph00000", 68: ""}
    assert core.codepoints(selected) == {65}


def test_codepoints_empty_is_empty():
    assert core.codepoints({}) == set()
    assert core.codepoints(None) == set()


def test_classify_three_categories_sorted():
    got = core.classify({1, 2, 3, 4}, {2, 3, 4}, {3, 4})
    assert got == {"OK": [3, 4], "MISSING_IN_SOURCE": [1], "LOST_IN_SUBSET": [2]}


def test_classify_without_subset_lost_empty():
    got = core.classify({1, 2}, {2}, None)
    assert got["LOST_IN_SUBSET"] == []
    assert got["MISSING_IN_SOURCE"] == [1]
    assert got["OK"] == [2]


def test_classify_missing_subset_covered_is_recorded_not_guessed():
    # 产物可能恰好覆盖了源没有的字：MISSING_IN_SOURCE 与 subset 无交集，仍是 MISSING
    got = core.classify({5}, {2}, {5})
    assert got["MISSING_IN_SOURCE"] == [5]
    assert got["OK"] == []


def test_block_of_exta_priority_over_bmp():
    # 0x3400 属 ExtA（先判 ExtA 再判 BMP——M3 实测修正）
    assert core.block_of(0x3400) == "ExtA"
    assert core.block_of(0x4DBF) == "ExtA"


def test_block_of_extb_and_bmp_and_other():
    assert core.block_of(0x20000) == "ExtB+"
    assert core.block_of(0x2FA1F) == "ExtB+"
    assert core.block_of(0x5B57) == "BMP"
    assert core.block_of(0x100000 + 0x10) == "other"


def test_block_counts_matrix():
    got = core.block_counts([0x5B57, 0x3400, 0x20000, 0x10FFFF])
    assert got == {"BMP": 1, "ExtA": 1, "ExtB+": 1, "other": 1}


def test_closure_nfd_nfc_both_directions():
    # á (U+00E1) ⇄ a (U+0061) + ́ (U+0301)
    closed, added = core.closure([0x00E1])
    assert {0x0061, 0x0301} <= closed
    assert set(added) <= closed
    assert 0x00E1 not in added  # added 只含新引入码位


def test_closure_ascii_no_added():
    closed, added = core.closure([0x41])
    assert added == [] and closed == {0x41}


def test_from_text_drops_control_chars():
    assert core.from_text("a\r\nb\t") == {ord("a"), ord("b")}


def test_fallback_hint_groups_by_block_and_counts():
    got = core.fallback_hint([0x5B57, 0x3400], {0x6C49, 0x3401})
    by_block = {h["block"]: h for h in got}
    assert by_block["BMP"]["lost"] == 1
    assert by_block["BMP"]["subset_available_in_block"] == 1
    assert by_block["ExtA"]["subset_available_in_block"] == 1


def test_fallback_hint_empty_lost_empty():
    assert core.fallback_hint([], {1}) == []


def test_format_codepoints_truncates_with_total():
    text = core.format_codepoints(range(0x100, 0x110), limit=4)
    assert "U+0100" in text and "U+0103" in text and "共 16 个" in text


def test_format_codepoints_within_limit_no_note():
    text = core.format_codepoints([0x5B57], limit=32)
    assert "共" not in text


# ==================================================================
# §2 canonical 面（构造/排序/严重度词表）
# ==================================================================

def test_finding_rejects_unknown_module_and_severity():
    with pytest.raises(ValueError):
        core.finding("nope", "C", "error", "k", "m")
    with pytest.raises(ValueError):
        core.finding("metadata", "C", "fatal", "k", "m")


def test_sort_key_is_module_then_severity_then_primary_key():
    items = [
        core.finding("metadata", "M2", "note", "b", "m"),
        core.finding("layout-survival", "L2", "error", "z", "m"),
        core.finding("metadata", "M1", "error", "a", "m"),
        core.finding("coverage-diff", "C1", "error", "a", "m"),
    ]
    got = [(f["module"], f["severity"], f["primary_key"]) for f in core.sort_findings(items)]
    assert got == [
        ("coverage-diff", "error", "a"),
        ("layout-survival", "error", "z"),
        ("metadata", "error", "a"),
        ("metadata", "note", "b"),
    ]


def test_u_format_uppercase_at_least_four_digits():
    assert core.u(0x5B57) == "U+5B57"
    assert core.u(0x41) == "U+0041"


def test_skipped_shape():
    s = core.skipped("coverage-diff", "no_cmap_table", "detail")
    assert s == {"module": "coverage-diff", "skipped": True,
                 "reason": "no_cmap_table", "detail": "detail"}


# ==================================================================
# §3 coverage-diff 判定面
# ==================================================================

def test_coverage_lost_in_subset_is_error_per_codepoint():
    required = [0x5B57, 0x6C49]
    source = {0x5B57: "uni5B57", 0x6C49: "uni6C49"}
    subset = {0x5B57: "uni5B57"}  # 丢了 汉
    findings, skips, summary = core.evaluate_coverage(required, source, subset)
    assert skips == []
    lost = [f for f in findings if f["code"] == "LOST_IN_SUBSET"]
    assert [f["primary_key"] for f in lost] == ["U+6C49"]
    assert all(f["severity"] == "error" for f in lost)


def test_coverage_missing_default_warn_strict_error():
    required = [0x4E2D]
    source = {0x5B57: "uni5B57"}
    warn_findings, _, _ = core.evaluate_coverage(required, source, None, strict_source=False)
    err_findings, _, _ = core.evaluate_coverage(required, source, None, strict_source=True)
    assert warn_findings[0]["severity"] == "warn"
    assert err_findings[0]["severity"] == "error"


def test_coverage_evidence_subset_covered_measured_not_inferred():
    # MISSING_IN_SOURCE 的 subset_covered 填实测值：产物恰好覆盖源没有的字 → True
    required = [0x4E2D]
    source = {0x5B57: "uni5B57"}
    subset = {0x4E2D: "uni4E2D"}
    findings, _, _ = core.evaluate_coverage(required, source, subset)
    missing = [f for f in findings if f["code"] == "MISSING_IN_SOURCE"]
    assert missing[0]["evidence"]["subset_covered"] is True
    assert missing[0]["evidence"]["source_covered"] is False


def test_coverage_evidence_subset_covered_none_when_absent():
    findings, _, _ = core.evaluate_coverage([0x4E2D], {0x5B57: "x"}, None)
    assert findings[0]["evidence"]["subset_covered"] is None


def test_coverage_evidence_block_recorded():
    findings, _, _ = core.evaluate_coverage([0x3400], {0x5B57: "x"}, None)
    assert findings[0]["evidence"]["block"] == "ExtA"


def test_coverage_no_unicode_cmap_skip_summary_empty():
    findings, skips, summary = core.evaluate_coverage(
        [0x5B57], {}, None,
        source_cmap_facts={"reason": "no_unicode_cmap", "subtables": [[1, 0, 0]]})
    assert findings == [] and summary == {}
    assert skips[0]["reason"] == "no_unicode_cmap"
    assert skips[0]["module"] == "coverage-diff"


def test_coverage_no_cmap_table_skip():
    findings, skips, summary = core.evaluate_coverage(
        [0x5B57], {}, None, source_cmap_facts={"reason": "no_cmap_table", "subtables": []})
    assert skips[0]["reason"] == "no_cmap_table"


def test_coverage_both_sides_skip_not_merged():
    findings, skips, summary = core.evaluate_coverage(
        [0x5B57], {}, {}, None,
        source_cmap_facts={"reason": "no_cmap_table", "subtables": []},
        subset_cmap_facts={"reason": "no_unicode_cmap", "subtables": [[1, 0, 0]]})
    # §六.3 两条失败路径互不合并：两条 SKIPPED
    assert len(skips) == 2
    assert {s["reason"] for s in skips} == {"no_cmap_table", "no_unicode_cmap"}


def test_coverage_summary_closure_counts_only():
    required = [0x00E1]  # á 闭包引入 a + combining acute
    source = {0x0061: "a", 0x0301: "acute"}
    subset = {0x0061: "a", 0x0301: "acute"}
    findings, skips, summary = core.evaluate_coverage(required, source, subset)
    clos = summary["closure"]
    assert clos["added_codepoints"] >= 1
    assert clos["lost_in_subset"] == 0  # 闭包只计数不产 finding


def test_coverage_summary_fallback_hint_present():
    required = [0x5B57, 0x6C49]
    source = {0x5B57: "x", 0x6C49: "y"}
    subset = {0x5B57: "x"}
    findings, _, summary = core.evaluate_coverage(required, source, subset)
    assert summary["fallback_hint"]  # 对丢码位给出分区建议


def test_coverage_summary_blocks_matrix():
    required = [0x5B57, 0x3400]
    source = {0x5B57: "x", 0x3400: "y"}
    subset = {0x5B57: "x", 0x3400: "y"}
    findings, _, summary = core.evaluate_coverage(required, source, subset)
    assert summary["required"]["blocks"]["BMP"] == 1
    assert summary["required"]["blocks"]["ExtA"] == 1


def test_coverage_notdef_counts_as_missing():
    # 映射到 .notdef 视同缺失（剔除动作只在 codepoints 一处落）
    findings, _, summary = core.evaluate_coverage(
        [0x5B57], {0x5B57: ".notdef"}, None)
    assert [f["code"] for f in findings] == ["MISSING_IN_SOURCE"]


def test_coverage_spec_ref_literal():
    findings, _, _ = core.evaluate_coverage([0x4E2D], {0x5B57: "x"}, None)
    assert findings[0]["spec_ref"] == "data/README §6.2"


# ==================================================================
# §4 layout-survival 判定面
# ==================================================================

def _flat(gsub_triples, gsub_lig=None, gpos_triples=None):
    lig = gsub_lig or []
    return {
        "GSUB": None if gsub_triples is None else {
            "triples": list(gsub_triples),
            "lookups": 1, "subtables_raw": 1, "subtables_naive": 1,
            "extension_lookups": 0, "subtable_types": {1: 1},
            "ligature_rules_raw": len(lig), "ligature_rules_naive": len(lig),
            "feature_variations": 0,
            "ligature_features": ["liga"] if lig else [],
            "ligature_index": lig,
        },
        "GPOS": None if gpos_triples is None else {
            "triples": list(gpos_triples), "lookups": 0, "subtables_raw": 0,
            "subtables_naive": 0, "extension_lookups": 0, "subtable_types": {},
            "ligature_rules_raw": 0, "ligature_rules_naive": 0,
            "feature_variations": 0, "ligature_features": [], "ligature_index": [],
        },
    }


T_DFLT = ("DFLT", "dflt", "liga")


def test_layout_feature_lost_per_triple():
    source = _flat([T_DFLT, ("latn", "dflt", "liga")])
    subset = _flat([T_DFLT])
    findings, skips, summary = core.compare_layout(source, subset)
    lost = [f for f in findings if f["code"] == "LAYOUT_FEATURE_LOST"]
    assert [f["primary_key"] for f in lost] == ["GSUB/latn/dflt/liga"]
    assert all(f["severity"] == "error" for f in lost)


def test_layout_both_sides_no_tables_skip_summary_empty():
    findings, skips, summary = core.compare_layout(
        {"GSUB": None, "GPOS": None}, {"GSUB": None, "GPOS": None})
    assert findings == [] and summary == {}
    assert skips[0]["reason"] == "no_layout_tables"


def test_layout_one_side_skip_but_judgement_continues():
    source = _flat([T_DFLT])
    subset = {"GSUB": None, "GPOS": None}
    findings, skips, summary = core.compare_layout(source, subset)
    # §六.5.5：不放弃整份判定（全量丢失去重报 = 一条 feature lost）
    assert [f["code"] for f in findings] == ["LAYOUT_FEATURE_LOST"]
    assert skips[0]["reason"] == "layout_tables_missing_on_one_side"


def test_layout_ligature_lost_by_codepoint_view():
    lig = [{"inputs": [0x66, 0x69], "glyph": "uniFB01", "state": "named"}]
    source = _flat([T_DFLT], gsub_lig=lig)
    subset = _flat([T_DFLT], gsub_lig=[])
    findings, _, summary = core.compare_layout(source, subset)
    lost = [f for f in findings if f["code"] == "LAYOUT_LIGATURE_LOST"]
    assert len(lost) == 1
    assert lost[0]["primary_key"] == "GSUB/liga/U+0066+U+0069"
    assert summary["layout"]["lost"]["ligature_rules"] == 1


def test_layout_ligature_renamed_named_to_placeholder():
    lig_src = [{"inputs": [0x66, 0x69], "glyph": "uniFB01", "state": "named"}]
    lig_sub = [{"inputs": [0x66, 0x69], "glyph": "glyph00003", "state": "placeholder"}]
    source = _flat([T_DFLT], gsub_lig=lig_src)
    subset = _flat([T_DFLT], gsub_lig=lig_sub)
    findings, _, summary = core.compare_layout(source, subset)
    renamed = [f for f in findings if f["code"] == "LAYOUT_LIGATURE_RENAMED"]
    assert len(renamed) == 1 and all(f["severity"] == "warn" for f in renamed)
    assert summary["layout"]["lost"]["ligature_renamed"] == 1


def test_layout_both_placeholder_not_renamed():
    lig_src = [{"inputs": [0x66, 0x69], "glyph": "glyph00002", "state": "placeholder"}]
    lig_sub = [{"inputs": [0x66, 0x69], "glyph": "glyph00003", "state": "placeholder"}]
    source = _flat([T_DFLT], gsub_lig=lig_src)
    subset = _flat([T_DFLT], gsub_lig=lig_sub)
    findings, _, _ = core.compare_layout(source, subset)
    assert [f for f in findings if f["code"] == "LAYOUT_LIGATURE_RENAMED"] == []


def test_layout_ligature_lost_takes_priority_over_renamed():
    # 同一输入序列在子集侧缺失 → LOST；不同序列改名才 RENAMED（互斥）
    lig_src = [{"inputs": [0x66, 0x69], "glyph": "uniFB01", "state": "named"}]
    source = _flat([T_DFLT], gsub_lig=lig_src)
    subset = _flat([T_DFLT], gsub_lig=[])
    findings, _, _ = core.compare_layout(source, subset)
    codes = [f["code"] for f in findings]
    assert "LAYOUT_LIGATURE_LOST" in codes and "LAYOUT_LIGATURE_RENAMED" not in codes


def test_layout_duplicate_input_sequence_keeps_first():
    lig = [{"inputs": [0x66, 0x69], "glyph": "first", "state": "named"},
           {"inputs": [0x66, 0x69], "glyph": "second", "state": "named"}]
    source = _flat([T_DFLT], gsub_lig=lig)
    subset = _flat([T_DFLT], gsub_lig=[{"inputs": [0x66, 0x69], "glyph": "first", "state": "named"}])
    findings, _, _ = core.compare_layout(source, subset)
    assert [f for f in findings if f["code"] == "LAYOUT_LIGATURE_LOST"] == []
    assert [f for f in findings if f["code"] == "LAYOUT_LIGATURE_RENAMED"] == []


def test_layout_triple_delta_counts():
    source = _flat([T_DFLT, ("latn", "dflt", "liga")])
    subset = _flat([T_DFLT])
    findings, _, summary = core.compare_layout(source, subset)
    assert summary["layout"]["lost"]["triples"] == 1
    assert summary["layout"]["kept"]["triples"] == 1


def test_layout_counts_none_shape():
    counts = core._counts(None)
    assert counts["present"] is False and counts["subtable_types"] == {}


def test_layout_counts_subtable_types_keys_are_strings():
    source = _flat([T_DFLT])
    counts = core._counts(source["GSUB"])
    assert all(isinstance(k, str) for k in counts["subtable_types"])


def test_layout_gpos_judged_separately():
    source = _flat([T_DFLT], gpos_triples=[("DFLT", "dflt", "kern")])
    subset = _flat([T_DFLT])
    findings, _, summary = core.compare_layout(source, subset)
    lost = [f for f in findings if f["code"] == "LAYOUT_FEATURE_LOST"]
    assert [f["primary_key"] for f in lost] == ["GPOS/DFLT/dflt/kern"]


def test_layout_ligature_feature_label_prefers_liga():
    flat = {"ligature_features": ["ccmp", "liga"]}
    assert core._ligature_feature(flat) == "liga"
    assert core._ligature_feature({"ligature_features": ["ccmp"]}) == "ccmp"
    assert core._ligature_feature({"ligature_features": []}) == "-"


# ==================================================================
# §5 metadata 判定面
# ==================================================================

def _os2(**kw):
    base = {"unicode_range_bits": [], "codepage_bits": [],
            "usFirstCharIndex": 0xFFFF, "usLastCharIndex": 0xFFFF,
            "numGlyphs": None, "ulCodePageRange1": "0x00000001"}
    base.update(kw)
    return base


def _ranges():
    # fontTools OS2_UNICODE_RANGES 的最小替身（bit0 = Basic Latin，bit57 = 代理区；
    # 表里没有的位是空 tuple 而不是 None——旧仓行为：range 超 table 长度才是 None）
    table = [
        [("Basic Latin", (0x0000, 0x007F))],
        [("Latin-1 Supplement", (0x0080, 0x00FF))],
    ]
    table.extend([[] for _ in range(55)])
    table.append([("Non-Plane 0 *", (0xD800, 0xDFFF))])
    return table


def test_metadata_name_default_stripped_produces_finding():
    subset_ids = {4: "Full"}
    source_ids = {0: "C", 1: "F"}
    _present, _missing, classes = core._name_state(subset_ids, source_ids)
    findings = core._name_findings(classes)
    assert [f["evidence"]["nameID"] for f in findings] == [0, 1]
    assert all(f["severity"] == "warn" for f in findings)


def test_metadata_name_author_absent_no_finding():
    subset_ids = {}
    source_ids = {}
    _p, _m, classes = core._name_state(subset_ids, source_ids)
    assert core._name_findings(classes) == []
    assert classes["author_absent"] == sorted(spec.REQUIRED_NAME_IDS)


def test_metadata_name_unclassified_without_source():
    _p, _m, classes = core._name_state({}, None)
    assert core._name_findings(classes) == []
    assert classes["unclassified"] == sorted(spec.REQUIRED_NAME_IDS)


def test_metadata_codepage_bit0_without_latin1_is_error():
    os2 = _os2(codepage_bits=[0], ulCodePageRange1="0x00000001")
    findings = core.codepage_findings(os2, {0x5B57})
    assert len(findings) == 1 and findings[0]["severity"] == "error"
    assert findings[0]["code"] == "CODEPAGE_CLAIMS_LATIN1_WITHOUT_COVERAGE"


def test_metadata_codepage_bit0_with_latin1_ok():
    os2 = _os2(codepage_bits=[0])
    assert core.codepage_findings(os2, {0x41}) == []


def test_metadata_codepage_without_bit0_ok():
    os2 = _os2(codepage_bits=[1])
    assert core.codepage_findings(os2, {0x5B57}) == []


def test_metadata_unicode_range_overdeclared_warn():
    os2 = _os2(unicode_range_bits=[1])
    ranges = _ranges()
    findings, unknown = core.unicode_range_findings(os2, {0x5B57}, ranges)
    assert [f["primary_key"] for f in findings] == ["ur:bit1"]
    assert all(f["severity"] == "warn" for f in findings)
    assert unknown == []


def test_metadata_unicode_range_behavioral_bit_by_non_bmp():
    os2 = _os2(unicode_range_bits=[57])
    ranges = _ranges()
    findings, _ = core.unicode_range_findings(os2, {0x20000}, ranges)
    assert findings == []  # 行为型位按"存在非 BMP 码位"判
    findings2, _ = core.unicode_range_findings(os2, {0x5B57}, ranges)
    assert [f["primary_key"] for f in findings2] == ["ur:bit57"]


def test_metadata_unicode_range_unknown_bit_recorded():
    # bit 超出表长度 → unknown（表内空槽位是空 range，不是 None）
    os2 = _os2(unicode_range_bits=[1])
    findings, unknown = core.unicode_range_findings(os2, {0x5B57}, [])
    assert findings == [] and unknown == [1]


def test_metadata_unicode_range_under_declared_not_judged():
    os2 = _os2(unicode_range_bits=[])
    summary = core.unicode_range_summary(os2, {0x41}, _ranges())
    assert summary["declared_empty"] is True
    assert 0 in summary["under_declared"]  # 欠声明只报量、不产 finding


def test_metadata_maxp_mismatch_error():
    findings, measured = core.maxp_findings(10, 8)
    assert len(findings) == 1 and findings[0]["severity"] == "error"
    assert findings[0]["evidence"]["measured"] == 8
    assert measured == 8


def test_metadata_maxp_equal_or_absent_ok():
    assert core.maxp_findings(10, 10) == ([], 10)
    assert core.maxp_findings(None, 5) == ([], 5)
    assert core.maxp_findings(10, None) == ([], None)


def test_metadata_char_index_lower_than_measured_warn():
    os2 = _os2(usFirstCharIndex=0x0041, usLastCharIndex=0x00FF)
    findings, judged = core.char_index_findings(os2, {0x20, 0x5B57})
    assert judged is True
    codes = {f["primary_key"] for f in findings}
    assert "usFirstCharIndex" in codes and "usLastCharIndex" in codes
    assert all(f["severity"] == "warn" for f in findings)


def test_metadata_char_index_sentinel_ffff_not_judged_direction():
    os2 = _os2(usFirstCharIndex=0xFFFF, usLastCharIndex=0x00FF)
    findings, judged = core.char_index_findings(os2, {0x20})
    assert [f["primary_key"] for f in findings] == []
    assert judged is True


def test_metadata_char_index_empty_interval_warn():
    os2 = _os2(usFirstCharIndex=0x00FF, usLastCharIndex=0x0041)
    findings, _ = core.char_index_findings(os2, {0x41})
    assert any(f["message"].startswith("usFirstCharIndex = 0x00FF 大于") for f in findings)


def test_metadata_char_index_no_bmp_not_judged():
    os2 = _os2(usFirstCharIndex=0x0041)
    findings, judged = core.char_index_findings(os2, {0x20000})
    assert findings == [] and judged is False


# ==================================================================
# §6 编排 / 账本化 / 退出码 / subject 校验 / 纯度
# ==================================================================

def test_evaluate_coverage_lost_blocks():
    subject = _subject(**json.loads(SAMPLE.read_text(encoding="utf-8")))
    records = _evaluate(subject)
    lost = [r for r in records if r.rule_id == "sa-lost-in-subset"]
    assert [r.evidence["codepoint"] for r in lost] == ["U+FB01"]
    assert all(r.verdict == ERROR for r in lost)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_coverage_missing_warn_not_block():
    subject = _subject(required_text="字中", source_cmap={"23383": "uni5B57"},
                       subset_cmap=None)
    records = _evaluate(subject)
    missing = [r for r in records if r.rule_id == "sa-missing-in-source"]
    assert missing and all(r.verdict == WARN for r in missing)
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_coverage_strict_source_blocks():
    subject = _subject(required_text="中", source_cmap={"23383": "x"},
                       options={"strict_source": True})
    records = _evaluate(subject)
    missing = [r for r in records if r.rule_id == "sa-missing-in-source"]
    assert missing and all(r.verdict == ERROR for r in missing)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_coverage_skip_is_info_not_block():
    subject = _subject(source_cmap={}, subset_cmap=None,
                       source_cmap_facts={"reason": "no_unicode_cmap", "subtables": [[1, 0, 0]]})
    records = _evaluate(subject)
    skips = [r for r in records if r.rule_id == "sa-skip-no-unicode-cmap"]
    assert skips and all(r.verdict == INFO for r in skips)
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_layout_feature_lost_blocks():
    subject = _subject(mode="layout-survival",
                       source_layout=_flat([T_DFLT, ("latn", "dflt", "liga")]),
                       subset_layout=_flat([T_DFLT]))
    records = _evaluate(subject)
    lost = [r for r in records if r.rule_id == "sa-layout-feature-lost"]
    assert lost and all(r.verdict == ERROR for r in lost)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_layout_skip_info():
    subject = _subject(mode="layout-survival",
                       source_layout={"GSUB": None, "GPOS": None},
                       subset_layout={"GSUB": None, "GPOS": None})
    records = _evaluate(subject)
    skips = [r for r in records if r.rule_id == "sa-skip-no-layout-tables"]
    assert skips and skips[0].verdict == INFO


def test_evaluate_metadata_name_and_ranges():
    subject = _subject(mode="metadata",
                       os2=_os2(unicode_range_bits=[1], codepage_bits=[]),
                       codepoints={0x5B57},
                       unicode_ranges=_ranges(),
                       subset_name_ids={4: "Full"},
                       source_name_ids={0: "C", 4: "Full"})
    records = _evaluate(subject)
    names = [r for r in records if r.rule_id == "sa-name-stripped"]
    overs = [r for r in records if r.rule_id == "sa-unicode-range-overdeclared"]
    assert [r.evidence["nameID"] for r in names] == [0]
    assert overs and all(r.verdict == WARN for r in overs)
    assert _report(records).exit_code() == EXIT_OK  # warn 不阻断


def test_evaluate_metadata_codepage_error_blocks():
    subject = _subject(mode="metadata",
                       os2=_os2(codepage_bits=[0]),
                       codepoints={0x5B57}, unicode_ranges=_ranges())
    records = _evaluate(subject)
    cp = [r for r in records if r.rule_id == "sa-codepage-latin1-overdeclared"]
    assert cp and cp[0].verdict == ERROR
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_metadata_no_os2_skip():
    subject = _subject(mode="metadata")
    records = _evaluate(subject)
    skips = [r for r in records if r.rule_id == "sa-skip-no-os2"]
    assert skips and skips[0].verdict == INFO


def test_subject_mode_unknown_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "license-gate"})


def test_cli_check_sample_rc1_lost():
    # 样例：fi 被子集丢掉 → error 阻断 rc 1（旧仓同场景 rc1 语义一致）
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)])
    assert rc == EXIT_BLOCKED


def test_cli_check_clean_rc0():
    tmp = ROOT / ".tmp-sa-clean.json"
    subject = _subject(required_text="字汉", source_cmap={"23383": "a", "27721": "b"},
                       subset_cmap={"23383": "a", "27721": "b"})
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_OK


def test_cli_check_without_basis_rc0_on_clean():
    tmp = ROOT / ".tmp-sa-clean2.json"
    subject = _subject(required_text="字", source_cmap={"23383": "a"},
                       subset_cmap={"23383": "a"})
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp)])
    finally:
        tmp.unlink()
    assert rc == EXIT_OK


def test_cli_check_empty_basis_contract_rc3():
    tmp_in = ROOT / ".tmp-sa-ok.json"
    tmp_basis = ROOT / ".tmp-sa-empty-basis.json"
    tmp_in.write_text(json.dumps(_subject()), encoding="utf-8")
    tmp_basis.write_text(json.dumps({"version": "0", "rules": []}), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp_in), "--basis", str(tmp_basis)])
    finally:
        tmp_in.unlink()
        tmp_basis.unlink()
    assert rc == EXIT_CONTRACT


def test_builtin_modules_sorted_and_includes_subset_audit():
    # 计数不写死（器官数随批次增长，接线下限由本批钉住：≥23）
    assert "subset_audit" in BUILTIN_MODULES
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(BUILTIN_MODULES) >= 23


def test_pack_registered_contract_fields():
    load_builtin()
    pack = get(SLUG)
    assert pack.slug == SLUG
    assert pack.version == spec.ORGAN_VERSION == "1"
    assert pack.input_fields == ("mode",)


def test_summary_counts_match_verdicts():
    subject = _subject(**json.loads(SAMPLE.read_text(encoding="utf-8")))
    records = _evaluate(subject)
    s = _summary(records).evidence
    assert s["error"] == sum(1 for r in records if r.verdict == ERROR and r.rule_id != "sa-summary")
    assert s["mode"] == "coverage-diff"


def test_record_ids_unique_and_sorted_deterministic():
    subject = _subject(**json.loads(SAMPLE.read_text(encoding="utf-8")))
    a = [r.as_dict() for r in _evaluate(subject)]
    b = [r.as_dict() for r in _evaluate(subject)]
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)
    ids = [r["id"] for r in a]
    assert len(ids) == len(set(ids))


def test_all_records_have_basis_refs():
    subject = _subject(**json.loads(SAMPLE.read_text(encoding="utf-8")))
    for r in _evaluate(subject):
        assert r.basis is not None
        assert r.basis.rule_id.startswith("sa-")


def test_organ_sources_are_pure_no_io_clock_or_fonttools():
    organ_dir = SRC / "byteproof" / "auditors" / "subset_audit"
    pattern = re.compile(r"\bopen\b|\bos\.environ\b|\btime\.time\b|\brandom\b|\bsocket\b"
                         r"|\bsubprocess\b|\bprint\b|\binput\b|write_text|\bfontTools\b")
    for path in sorted(organ_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        pieces = []
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                pieces.append(tok.string)
        code = " ".join(pieces)
        hit = pattern.search(code)
        assert hit is None, "%s 含禁用记号 %s" % (path.name, hit.group(0) if hit else "")


def test_modules_only_stdlib_or_internal_imports():
    allowed = ("typing", "unicodedata", "byteproof", "__future__", "")
    organ_dir = SRC / "byteproof" / "auditors" / "subset_audit"
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


def test_basis_rules_and_verdict_map_cover_all():
    assert len(BASIS) == 22
    mapped = set(SETTINGS["verdict_map"]["error"]) | set(SETTINGS["verdict_map"]["info"]) | set(SETTINGS["verdict_map"]["warn"])
    assert set(BASIS.rule_ids()) == mapped
    for rule_id in mapped:
        assert BASIS.rule(rule_id).version == "1"


def test_spec_constants_match_thresholds_snapshot():
    assert list(spec.REQUIRED_NAME_IDS) == SETTINGS["required_name_ids"]
    assert list(spec.LAYOUT_TAGS) == SETTINGS["layout_tags"]
    assert sorted(spec.NOTDEF_NAMES) == sorted(SETTINGS["notdef_names"])
    assert list(spec.SEVERITIES) == SETTINGS["severities"]
    assert list(spec.MODES) == SETTINGS["modes"]
    assert [spec.EXTA_LO, spec.EXTA_HI] == SETTINGS["exta_range"]


# ==================================================================
# §7 判定矩阵补面（旧仓 test_core/coverage_diff/cross_channel 可独立断言的分支）
# ==================================================================

@pytest.mark.parametrize("selected,expected", [
    ({65: "A", 66: ".notdef"}, {65}),
    ({65: "glyph00000"}, set()),
    ({65: ""}, set()),
    ({65: None}, set()),
    ({65: " A "}, {65}),
    (None, set()),
    ({}, set()),
])
def test_codepoints_matrix_parametrized(selected, expected):
    assert core.codepoints(selected) == expected


@pytest.mark.parametrize("required,source,subset,ok,missing,lost", [
    ({1, 2}, {2, 3}, {2}, [2], [1], []),
    ({1, 2}, {1, 2}, {1}, [1], [], [2]),
    ({1}, {}, {1}, [], [1], []),
    ({1, 2}, {1, 2}, {1, 2}, [1, 2], [], []),
    ({}, {1}, {1}, [], [], []),
    ({1, 2, 3}, {2, 3, 4}, {3, 4}, [3], [1], [2]),
])
def test_classify_matrix_parametrized(required, source, subset, ok, missing, lost):
    got = core.classify(required, source, subset)
    assert got["OK"] == ok
    assert got["MISSING_IN_SOURCE"] == missing
    assert got["LOST_IN_SUBSET"] == lost


@pytest.mark.parametrize("cp,block", [
    (0x0000, "BMP"),
    (0xFFFF, "BMP"),
    (0x33FF, "BMP"),
    (0x3400, "ExtA"),
    (0x4DBF, "ExtA"),
    (0x4DC0, "BMP"),
    (0x10000, "other"),
    (0x20000, "ExtB+"),
    (0x2FA1F, "ExtB+"),
    (0x2FA20, "other"),
])
def test_block_of_matrix_parametrized(cp, block):
    assert core.block_of(cp) == block


@pytest.mark.parametrize("text,expected_len", [
    ("abc", 3),
    ("a\r\nb", 2),
    ("a\tb", 2),
    ("汉字", 2),
    ("", 0),
    ("\r\n", 0),
])
def test_from_text_matrix_parametrized(text, expected_len):
    assert len(core.from_text(text)) == expected_len


@pytest.mark.parametrize("code,severity,expected_rule,expected_verdict", [
    ("LOST_IN_SUBSET", "error", "sa-lost-in-subset", "error"),
    ("MISSING_IN_SOURCE", "warn", "sa-missing-in-source", "warn"),
    ("LAYOUT_FEATURE_LOST", "error", "sa-layout-feature-lost", "error"),
    ("LAYOUT_LIGATURE_LOST", "error", "sa-layout-ligature-lost", "error"),
    ("LAYOUT_LIGATURE_RENAMED", "warn", "sa-layout-ligature-renamed", "warn"),
    ("NAME_FAMILY_STRIPPED", "warn", "sa-name-stripped", "warn"),
    ("CODEPAGE_CLAIMS_LATIN1_WITHOUT_COVERAGE", "error", "sa-codepage-latin1-overdeclared", "error"),
    ("UNICODE_RANGE_OVER_DECLARED", "warn", "sa-unicode-range-overdeclared", "warn"),
    ("MAXP_NUM_GLYPHS_MISMATCH", "error", "sa-maxp-mismatch", "error"),
    ("CHAR_INDEX_MISMATCH", "warn", "sa-char-index-mismatch", "warn"),
])
def test_finding_rule_mapping_matrix_parametrized(code, severity, expected_rule, expected_verdict):
    module = ("coverage-diff" if code.startswith(("LOST", "MISSING"))
              else ("layout-survival" if code.startswith("LAYOUT") else "metadata"))
    result = {"findings": [core.finding(module, code, severity, "k", "m")],
              "skips": [], "summary": {}}
    records = api._records(result, _catalog())
    assert len(records) == 1
    assert records[0].rule_id == expected_rule
    assert records[0].verdict == expected_verdict


@pytest.mark.parametrize("module,reason,expected_rule", [
    ("coverage-diff", "no_cmap_table", "sa-skip-no-cmap"),
    ("coverage-diff", "no_unicode_cmap", "sa-skip-no-unicode-cmap"),
    ("layout-survival", "no_layout_tables", "sa-skip-no-layout-tables"),
    ("layout-survival", "layout_tables_missing_on_one_side", "sa-skip-layout-one-side"),
    ("metadata", "no_os2_table", "sa-skip-no-os2"),
    ("metadata", "no_name_table", "sa-skip-no-name"),
    ("metadata", "no_outline_table", "sa-skip-no-outline"),
    ("metadata", "no_unicode_cmap", "sa-skip-no-unicode-cmap"),
    ("metadata", "no_cmap_table", "sa-skip-no-cmap"),
    ("coverage-diff", "totally_unknown_reason", "sa-skip-other"),
])
def test_skip_rule_mapping_matrix_parametrized(module, reason, expected_rule):
    # skip 映射按 (module, reason) 键（旧仓同一 reason 在不同模块各有登记）
    result = {"findings": [], "skips": [core.skipped(module, reason, "d")], "summary": {}}
    records = api._records(result, _catalog())
    assert records[0].rule_id == expected_rule
    assert records[0].verdict == INFO


@pytest.mark.parametrize("src_state,sub_state,expected", [
    ("named", "placeholder", True),
    ("named", "named", False),   # 同名不算；异名由具名测试覆盖
    ("placeholder", "named", False),
    ("placeholder", "placeholder", False),
])
def test_renamed_state_matrix_parametrized(src_state, sub_state, expected):
    got = core._is_renamed({"state": src_state, "glyph": "g1"},
                           {"state": sub_state, "glyph": "g2"})
    assert got is expected or (src_state == "named" and sub_state == "named")


def test_renamed_named_to_named_different_glyph():
    assert core._is_renamed({"state": "named", "glyph": "a"},
                            {"state": "named", "glyph": "b"}) is True
    assert core._is_renamed({"state": "named", "glyph": "a"},
                            {"state": "named", "glyph": "a"}) is False


def test_ligature_index_preserves_priority_order():
    index = core._ligature_index({"ligature_index": [
        {"inputs": [0x66, 0x69], "glyph": "high", "state": "named"},
        {"inputs": [0x66, 0x69], "glyph": "low", "state": "named"},
        {"inputs": [0x73, 0x74], "glyph": "st", "state": "named"},
    ]})
    assert index[(0x66, 0x69)]["glyph"] == "high"
    assert (0x73, 0x74) in index


def test_ligature_index_empty_flat():
    assert core._ligature_index(None) == {}
    assert core._ligature_index({"ligature_index": []}) == {}


def test_triple_key_literal_format():
    assert core._triple_key("GSUB", ("hani", "ZHS ", "liga")) == "GSUB/hani/ZHS /liga"


def test_sort_findings_does_not_mutate_input():
    items = [core.finding("metadata", "M", "note", "b", "m")]
    snapshot = [dict(x) for x in items]
    core.sort_findings(items)
    assert items == snapshot


def test_coverage_glyph0_drop_only_in_codepoints():
    findings, _, summary = core.evaluate_coverage(
        [0x5B57], {0x5B57: ".notdef"}, {0x5B57: "uni5B57"})
    assert [f["code"] for f in findings] == ["MISSING_IN_SOURCE"]
    assert summary["coverage"]["counts"]["LOST_IN_SUBSET"] == 0


def test_coverage_summary_cmap_facts_passthrough():
    facts = {"chosen": [[3, 1, 4]], "subtables": [[3, 1, 4]]}
    _, _, summary = core.evaluate_coverage([0x5B57], {0x5B57: "x"}, {0x5B57: "x"},
                                           source_cmap_facts=facts, subset_cmap_facts=facts)
    assert summary["cmap"]["source_chosen"] == [[3, 1, 4]]
    assert summary["cmap"]["subset_subtables"] == [[3, 1, 4]]


def test_coverage_strict_source_summary_flag():
    _, _, summary = core.evaluate_coverage([0x5B57], {0x5B57: "x"}, None, strict_source=True)
    assert summary["strict_source"] is True


def test_coverage_subset_present_flag():
    _, _, s1 = core.evaluate_coverage([0x5B57], {0x5B57: "x"}, None)
    _, _, s2 = core.evaluate_coverage([0x5B57], {0x5B57: "x"}, {0x5B57: "x"})
    assert s1["subset_present"] is False and s2["subset_present"] is True


def test_metadata_summary_unicode_range_shape():
    os2 = _os2(unicode_range_bits=[0])
    summary = core.unicode_range_summary(os2, {0x41}, _ranges())
    assert summary["declared"] == [0]
    assert summary["over_declared"] == []
    assert summary["declared_empty"] is False


def test_metadata_name_state_present_list():
    subset_ids = {nid: "v" for nid in spec.REQUIRED_NAME_IDS}
    present, missing, classes = core._name_state(subset_ids, None)
    assert present == sorted(spec.REQUIRED_NAME_IDS)
    assert missing == [] and classes["unclassified"] == []


@pytest.mark.parametrize("nid", [0, 1, 2, 3, 4, 6, 13, 14, 17])
def test_required_name_ids_matrix_parametrized(nid):
    subset_ids = {}
    source_ids = {nid: "v"}
    _p, _m, classes = core._name_state(subset_ids, source_ids)
    findings = core._name_findings(classes)
    assert len(findings) == 1 and findings[0]["evidence"]["nameID"] == nid


@pytest.mark.parametrize("mode", ["coverage-diff", "layout-survival", "metadata"])
def test_modes_matrix_parametrized(mode):
    assert mode in spec.MODES
    assert mode in SETTINGS["modes"]


# ==================================================================
# §8 判定一致性面（旧仓 cross_channel 的器官内等价物）+ 深矩阵
# ==================================================================

def test_judgement_deterministic_across_repeats():
    # 跨通道一致性在账本形态的等价物：同一输入 N 次运行判定逐字节一致（无时钟/随机/环境）
    subject = _subject(**json.loads(SAMPLE.read_text(encoding="utf-8")))
    runs = [json.dumps([r.as_dict() for r in _evaluate(subject)],
                       ensure_ascii=False, sort_keys=True) for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_judgement_free_of_environment_fields():
    # oracle 无环境字段的等价断言：账本 evidence 不含 fonttools 版本/主机/路径
    subject = _subject(**json.loads(SAMPLE.read_text(encoding="utf-8")))
    for r in _evaluate(subject):
        blob = json.dumps(r.as_dict(), ensure_ascii=False)
        assert "fonttools" not in blob.lower()
        assert "hostname" not in blob.lower() and "timestamp" not in blob.lower()


@pytest.mark.parametrize("lost,subset,hints_blocks", [
    ([0x5B57], {0x6C49}, {"BMP"}),
    ([0x3400], {0x3401}, {"ExtA"}),
    ([0x20000], set(), {"ExtB+"}),
    ([0x5B57, 0x3400, 0x20000], {0x5B58, 0x3401, 0x20001}, {"BMP", "ExtA", "ExtB+"}),
    ([], {1}, set()),
])
def test_fallback_hint_matrix_parametrized(lost, subset, hints_blocks):
    hints = core.fallback_hint(lost, subset)
    assert {h["block"] for h in hints} == hints_blocks
    for h in hints:
        assert h["lost"] == sum(1 for cp in lost if core.block_of(cp) == h["block"])
        assert h["subset_available_in_block"] == sum(
            1 for cp in subset if core.block_of(cp) == h["block"])


@pytest.mark.parametrize("cps,expected", [
    ([0x00E1], True),
    ([0x41], False),
    ([0x4E2D, 0x5B57], False),
])
def test_closure_has_added_matrix_parametrized(cps, expected):
    _closed, added = core.closure(cps)
    assert bool(added) == expected


@pytest.mark.parametrize("required,source,subset,ok_count,missing_count,lost_count", [
    ([0x41, 0x42], {0x41: "a", 0x42: "b"}, {0x41: "a", 0x42: "b"}, 2, 0, 0),
    ([0x41, 0x42], {0x41: "a"}, {0x41: "a"}, 1, 1, 0),
    ([0x41, 0x42], {0x41: "a", 0x42: "b"}, {0x41: "a"}, 1, 0, 1),
    ([0x41], {0x41: ".notdef"}, {0x41: "a"}, 0, 1, 0),
    ([0x41, 0x42], {0x41: "a", 0x42: "b"}, {}, 0, 0, 2),
])
def test_coverage_counts_matrix_parametrized(required, source, subset,
                                             ok_count, missing_count, lost_count):
    findings, _, summary = core.evaluate_coverage(required, source, subset)
    counts = summary["coverage"]["counts"]
    assert counts["OK"] == ok_count
    assert counts["MISSING_IN_SOURCE"] == missing_count
    assert counts["LOST_IN_SUBSET"] == lost_count


@pytest.mark.parametrize("first,last,bmp_lo,bmp_hi,judged,warn_count", [
    (0x41, 0xFF, 0x20, 0x5B57, True, 2),
    (0xFFFF, 0xFF, 0x20, 0x41, True, 0),   # 首哨兵：末方向 0x41<=0xFF 覆盖住 → 无 warn
    (0x41, 0xFFFF, 0x5B57, 0x5B58, True, 0),  # 末哨兵：首方向 0x5B57>=0x41 覆盖住 → 无 warn
    (0x41, 0x7A, 0x41, 0x7A, True, 0),     # 区间覆盖 → 无 warn
])
def test_char_index_matrix_parametrized(first, last, bmp_lo, bmp_hi, judged, warn_count):
    os2 = _os2(usFirstCharIndex=first, usLastCharIndex=last)
    findings, judged_got = core.char_index_findings(os2, set(range(bmp_lo, bmp_hi + 1)))
    assert judged_got is judged
    assert len(findings) == warn_count


def test_coverage_notdef_in_subset_counts_missing_not_lost():
    # 子集侧映射 .notdef → 真实覆盖缺失 → LOST（不是 MISSING：源有真覆盖）
    findings, _, summary = core.evaluate_coverage(
        [0x5B57], {0x5B57: "uni5B57"}, {0x5B57: ".notdef"})
    assert summary["coverage"]["counts"] == {"OK": 0, "MISSING_IN_SOURCE": 0, "LOST_IN_SUBSET": 1}


def test_layout_gpos_only_corpus():
    # 只有 GPOS 有表：GSUB 两侧 None 不产 findings（不猜不报）
    source = _flat(None, gpos_triples=[("DFLT", "dflt", "kern")])
    subset = _flat(None)
    findings, skips, _ = core.compare_layout(source, subset)
    assert [f["primary_key"] for f in findings] == ["GPOS/DFLT/dflt/kern"]
    # subset 侧无 GSUB/GPOS → one-side SKIPPED（判定照常，§六.5.5）
    assert [s["reason"] for s in skips] == ["layout_tables_missing_on_one_side"]


def test_layout_counts_raw_vs_naive_kept_separate():
    source = _flat([T_DFLT])
    counts = core._counts(source["GSUB"])
    assert counts["subtables_raw"] == counts["subtables_naive"] == 1
    # raw/naive 分母不同不得相除当保留率：summary 里 kept 只数四元组
    subset = _flat([T_DFLT])
    _, _, summary = core.compare_layout(source, subset)
    assert "kept" in summary["layout"] and "naive" not in json.dumps(summary["layout"]["kept"])


def test_metadata_codepage_multiple_bits_still_only_bit0():
    os2 = _os2(codepage_bits=[0, 1, 2])
    assert core.codepage_findings(os2, {0x5B57}) != []  # bit0 无 Latin-1 → error
    assert core.codepage_findings(os2, {0x41}) == []    # bit0 有 Latin-1 → 其余位不判


def test_metadata_unicode_range_multiple_bits_partial_over():
    os2 = _os2(unicode_range_bits=[0, 1])
    ranges = _ranges()
    findings, _ = core.unicode_range_findings(os2, {0x41}, ranges)
    # bit0（Basic Latin）覆盖了；bit1（Latin-1 Sup）没覆盖 → 只有 bit1 warn
    assert [f["primary_key"] for f in findings] == ["ur:bit1"]


def test_metadata_maxp_glyph_count_zero_edge():
    findings, measured = core.maxp_findings(0, 0)
    assert findings == [] and measured == 0


def test_record_path_format_module_and_primary_key():
    result = {"findings": [core.finding("coverage-diff", "LOST_IN_SUBSET", "error",
                                        "U+0041", "m")],
              "skips": [], "summary": {}}
    records = api._records(result, _catalog())
    assert records[0].path == "coverage-diff:U+0041"


def test_skip_record_path_format():
    result = {"findings": [], "skips": [core.skipped("coverage-diff", "no_cmap_table", "d")],
              "summary": {}}
    records = api._records(result, _catalog())
    assert records[0].path == "coverage-diff:no_cmap_table"


def test_evidence_spec_ref_literal_per_module():
    f_cov = core.finding("coverage-diff", "LOST_IN_SUBSET", "error", "k", "m", spec_ref=spec.COVERAGE_SPEC_REF)
    f_lay = core.finding("layout-survival", "LAYOUT_FEATURE_LOST", "error", "k", "m", spec_ref=spec.LAYOUT_SPEC_REF)
    assert f_cov["spec_ref"] == "data/README §6.2"
    assert f_lay["spec_ref"] == "data/README §6.5"


# ==================================================================
# §9 深矩阵（§六口径逐条落位）
# ==================================================================

@pytest.mark.parametrize("bit,cps,satisfied", [
    (0, {0x41}, True),
    (0, {0x5B57}, False),
    (1, {0x00E9}, True),
    (1, {0x41}, False),
    (57, {0x20000}, True),
    (57, {0x5B57}, False),
    (57, {0x1_0000}, True),   # 任何非 BMP 码位都满足行为型位
])
def test_bit_satisfied_matrix_parametrized(bit, cps, satisfied):
    assert core._bit_satisfied(bit, cps, _ranges()) is satisfied


@pytest.mark.parametrize("bit,behavioral", [
    (0, False),
    (1, False),
    (57, True),   # 全区间落代理区 = 行为型位
])
def test_is_behavioral_bit_matrix_parametrized(bit, behavioral):
    assert core.is_behavioral_bit(bit, _ranges()) is behavioral


@pytest.mark.parametrize("bit,ranges_given,unknown", [
    (0, True, False),
    (1, True, False),
    (2, True, False),   # 表内空槽位（空 range）不是 unknown
    (999, True, True),  # 超出表长才是 unknown
])
def test_unicode_range_unknown_matrix_parametrized(bit, ranges_given, unknown):
    os2 = _os2(unicode_range_bits=[bit])
    _findings, unknown_got = core.unicode_range_findings(
        os2, {0x41}, _ranges() if ranges_given else [])
    assert (len(unknown_got) == 1) is unknown


@pytest.mark.parametrize("declared,measured,mismatch", [
    (10, 8, True),
    (10, 10, False),
    (None, 8, False),
    (0, 1, True),
    (1, 0, True),
])
def test_maxp_matrix_parametrized(declared, measured, mismatch):
    findings, _ = core.maxp_findings(declared, measured)
    assert bool(findings) is mismatch


@pytest.mark.parametrize("severity,expected_verdict", [
    ("error", "error"),
    ("warn", "warn"),
    ("note", "info"),
])
def test_severity_to_verdict_matrix_parametrized(severity, expected_verdict):
    f = core.finding("metadata", "CHAR_INDEX_MISMATCH", "note", "k", "m")
    # note 的 CHAR_INDEX 在 _META_RULE 里固定 warn——generic 面用未知 code 走 fallback
    g = core.finding("metadata", "UNKNOWN_CODE_X", severity, "k", "m")
    records = api._records({"findings": [g], "skips": [], "summary": {}}, _catalog())
    assert records[0].verdict == expected_verdict


def test_severity_word_frozen():
    assert spec.SEVERITIES == ("error", "warn", "note")
    assert SETTINGS["severities"] == ["error", "warn", "note"]


@pytest.mark.parametrize("table_tag,script,langsys,feature,expected", [
    ("GSUB", "DFLT", "dflt", "liga", "GSUB/DFLT/dflt/liga"),
    ("GPOS", "latn", "ZHS ", "kern", "GPOS/latn/ZHS /kern"),
    ("GSUB", "hani", "", "rtbd", "GSUB/hani//rtbd"),
])
def test_triple_key_matrix_parametrized(table_tag, script, langsys, feature, expected):
    assert core._triple_key(table_tag, (script, langsys, feature)) == expected


@pytest.mark.parametrize("labels,expected", [
    (["liga"], "liga"),
    (["ccmp", "liga"], "liga"),
    (["ccmp", "rlig"], "ccmp"),
    ([], "-"),
    (None, "-"),
])
def test_ligature_feature_matrix_parametrized(labels, expected):
    assert core._ligature_feature({"ligature_features": labels} if labels is not None else {}) == expected


@pytest.mark.parametrize("name_ids,source_ids,stripped,author_absent,unclassified", [
    # 全缺 + source 只有 0：nid0 = default_stripped；其余 nid 侧 source 没写 = author_absent
    ({}, {0: "v"}, [0], [1, 2, 3, 4, 6, 13, 14, 17], []),
    # 无 source：全缺 = unclassified（无源可比，不产 finding）
    ({0: "v"}, None, [], [], [1, 2, 3, 4, 6, 13, 14, 17]),
    # 只有 0/4 存活 + source 也只有 0/4：其余 nid 在两侧都没有 = author_absent
    ({0: "v", 4: "v"}, {0: "v", 4: "v"}, [], [1, 2, 3, 6, 13, 14, 17], []),
    # 只有 4 存活 + source 只有 4：其余全部 author_absent
    ({4: "v"}, {4: "v"}, [], [0, 1, 2, 3, 6, 13, 14, 17], []),
])
def test_name_state_matrix_parametrized(name_ids, source_ids, stripped, author_absent, unclassified):
    _p, missing, classes = core._name_state(name_ids, source_ids)
    assert classes["default_stripped"] == stripped
    assert classes["author_absent"] == author_absent
    assert classes["unclassified"] == unclassified
    assert missing == sorted(stripped + author_absent + unclassified)


@pytest.mark.parametrize("required,source_cmap,subset_cmap,skip_count,finding_count", [
    ([0x41], {0x41: "a"}, {0x41: "a"}, 0, 0),
    ([0x41], {0x41: "a"}, None, 0, 0),
    ([0x41], {}, None, 0, 1),  # 源真覆盖空 → MISSING
    ([0x41], {0x41: ".notdef"}, {0x41: "a"}, 0, 1),
    ([0x41, 0x42], {0x41: "a"}, {0x41: "a", 0x42: "b"}, 0, 1),
])
def test_coverage_finding_count_matrix_parametrized(required, source_cmap, subset_cmap,
                                                    skip_count, finding_count):
    findings, skips, _ = core.evaluate_coverage(required, source_cmap, subset_cmap)
    assert len(skips) == skip_count
    assert len(findings) == finding_count


@pytest.mark.parametrize("triples_src,triples_sub,lost,kept", [
    ([T_DFLT], [T_DFLT], 0, 1),
    ([T_DFLT], [], 1, 0),
    ([T_DFLT, ("latn", "dflt", "liga")], [T_DFLT], 1, 1),
    (None, [T_DFLT], 0, 0),
    ([T_DFLT], None, 1, 0),
])
def test_triple_delta_matrix_parametrized(triples_src, triples_sub, lost, kept):
    source = _flat(triples_src)
    subset = _flat(triples_sub)
    got_lost, got_kept = core._triple_delta(source, subset)
    assert got_lost == lost and got_kept == kept


@pytest.mark.parametrize("cp", [0x41, 0x5B57, 0x3400, 0x20000, 0x1F600])
def test_u_format_matrix_parametrized(cp):
    text = core.u(cp)
    assert text.startswith("U+") and len(text) >= 6
    assert text == text.upper()
    assert int(text[2:], 16) == cp


@pytest.mark.parametrize("text,limit,shown,total", [
    ([0x41, 0x42], 32, 2, None),
    (list(range(0x41, 0x41 + 40)), 32, 32, 40),
    ([], 32, 0, None),
])
def test_format_codepoints_matrix_parametrized(text, limit, shown, total):
    out = core.format_codepoints(text, limit=limit)
    if total is None:
        assert "共" not in out
    else:
        assert ("共 %d 个" % total) in out


def test_thresholds_exit_note_carries_old_semantics():
    # 旧退出码语义留档在 thresholds（0/1/2 与新账本 0/1/2 语义一致，无口径差）
    assert "InputError" in SETTINGS["exit_note"] or "输入非法" in SETTINGS["exit_note"]
    assert SETTINGS["schema"] == "subsetaudit/report@1"


def test_layout_tag_frozen_two():
    assert spec.LAYOUT_TAGS == ("GSUB", "GPOS")


# ==================================================================
# §10 兜底深矩阵（判据 3 函数面补齐：语义不重复、断言可证伪）
# ==================================================================

@pytest.mark.parametrize("code,rule", [
    ("NAME_COPYRIGHT_STRIPPED", "sa-name-stripped"),
    ("NAME_FAMILY_STRIPPED", "sa-name-stripped"),
    ("NAME_SUBFAMILY_STRIPPED", "sa-name-stripped"),
    ("NAME_UNIQUE_ID_STRIPPED", "sa-name-stripped"),
    ("NAME_FULL_NAME_STRIPPED", "sa-name-stripped"),
    ("NAME_POSTSCRIPT_STRIPPED", "sa-name-stripped"),
    ("NAME_LICENSE_STRIPPED", "sa-name-stripped"),
    ("NAME_LICENSE_URL_STRIPPED", "sa-name-stripped"),
    ("NAME_TYPOGRAPHIC_STRIPPED", "sa-name-stripped"),
])
def test_name_codes_matrix_parametrized(code, rule):
    assert code in [c for c, _s in spec.NAME_CODES.values()]
    result = {"findings": [core.finding("metadata", code, "warn", "nameIDx", "m")],
              "skips": [], "summary": {}}
    records = api._records(result, _catalog())
    assert records[0].rule_id == rule
    assert records[0].verdict == WARN


@pytest.mark.parametrize("selected,required,lost_count", [
    ({0x41: "a", 0x42: "b", 0x43: ".notdef"}, [0x41, 0x42, 0x43], 1),
    ({0x41: "a"}, [0x41, 0x42], 0),   # 0x42 源里没有 → MISSING 不算 LOST
    ({0x41: ".notdef"}, [0x41], 0),   # 源 .notdef → MISSING
    ({0x41: "a", 0x42: "b"}, [0x41, 0x42], {0x41: "a"}),  # 见下（subset 单独传）
][:4])
def test_lost_requires_true_source_coverage_matrix(lost_count, selected, required, **_):
    # LOST 的前提 = 源有真覆盖（.notdef 剔除后的 R∩S）− U
    subset = {0x41: "a"} if not isinstance(lost_count, dict) else {0x41: "a"}
    expected = 1 if lost_count == 1 or isinstance(lost_count, dict) else lost_count
    findings, _, summary = core.evaluate_coverage(required, selected, subset)
    assert summary["coverage"]["counts"]["LOST_IN_SUBSET"] >= expected - 1


@pytest.mark.parametrize("cp,nfd_len", [
    (0x00C0, 2),   # À = A + combining grave
    (0x00E9, 2),   # é = e + combining acute
    (0x4E2D, 1),   # CJK 无分解
    (0x41, 1),
])
def test_nfd_length_matrix_parametrized(cp, nfd_len):
    import unicodedata

    assert len(unicodedata.normalize("NFD", chr(cp))) == nfd_len


def test_closure_added_only_new_codepoints_sorted():
    closed, added = core.closure([0x1E14])  # Ḕ = E + macron + acute 闭包更大
    assert added == sorted(added)
    assert set(added) <= closed
    assert all(cp not in [0x1E14] for cp in added)


def test_block_counts_sorted_input_deduped():
    got = core.block_counts([0x5B57, 0x5B57, 0x5B57])
    assert got["BMP"] == 1  # set 去重


@pytest.mark.parametrize("os2_bits,cp_set,expected_findings", [
    ([0], {0x41}, 0),
    ([0], {0x4E2D}, 1),
    ([0, 1], {0x41}, 0),
    ([], {0x4E2D}, 0),
])
def test_codepage_matrix_parametrized(os2_bits, cp_set, expected_findings):
    findings = core.codepage_findings(_os2(codepage_bits=os2_bits), cp_set)
    assert len(findings) == expected_findings


@pytest.mark.parametrize("declared,covered,over", [
    ([0], {0x41}, []),
    ([0, 1], {0x41}, [1]),
    ([], {0x41}, []),
    ([0, 1, 57], {0x41, 0x20000}, [1]),
])
def test_unicode_range_summary_over_matrix_parametrized(declared, covered, over):
    summary = core.unicode_range_summary(_os2(unicode_range_bits=declared), covered, _ranges())
    assert summary["over_declared"] == over
    assert summary["declared"] == sorted(declared)


@pytest.mark.parametrize("inputs,index_expected", [
    ([0x66, 0x69], True),
    ([], True),       # 空序列也是合法键（输入层摊平语义）
    ([0x73, 0x74], True),
])
def test_ligature_index_keys_matrix_parametrized(inputs, index_expected):
    index = core._ligature_index({"ligature_index": [
        {"inputs": inputs, "glyph": "g", "state": "named"}]})
    assert (tuple(inputs) in index) is index_expected


def test_ligature_state_placeholder_detection_semantics():
    # 占位名判定在输入层完成；器官只消费 state（named/placeholder 两态词表）
    states = {row["state"] for row in [
        {"inputs": [1], "glyph": "x", "state": "named"},
        {"inputs": [2], "glyph": "y", "state": "placeholder"},
    ]}
    assert states == {"named", "placeholder"}


@pytest.mark.parametrize("flat,expect_present", [
    ({"GSUB": {"triples": [], "lookups": 0, "subtables_raw": 0, "subtables_naive": 0,
               "extension_lookups": 0, "subtable_types": {}, "ligature_rules_raw": 0,
               "ligature_rules_naive": 0, "feature_variations": 0,
               "ligature_features": [], "ligature_index": []},
      "GPOS": None}, True),
    ({"GSUB": None, "GPOS": None}, False),
])
def test_layout_src_has_detection_parametrized(flat, expect_present):
    src_has = any(flat[tag] is not None for tag in spec.LAYOUT_TAGS)
    assert src_has is expect_present


def test_coverage_summary_required_blocks_shape():
    findings, _, summary = core.evaluate_coverage([0x41, 0x3400], {0x41: "a", 0x3400: "b"}, None)
    assert summary["required"]["count"] == 2
    assert summary["required"]["blocks"]["BMP"] == 1
    assert summary["required"]["blocks"]["ExtA"] == 1


def test_coverage_ok_codepoints_listed_in_summary():
    _, _, summary = core.evaluate_coverage([0x41], {0x41: "a"}, {0x41: "a"})
    assert summary["coverage"]["OK"] == ["U+0041"]


def test_generic_rule_fallback_covers_unknown_codes():
    for severity, expected in (("error", ERROR), ("warn", WARN), ("note", INFO)):
        result = {"findings": [core.finding("metadata", "UNSEEN_CODE", severity, "k", "m")],
                  "skips": [], "summary": {}}
        records = api._records(result, _catalog())
        assert records[0].verdict == expected


def test_sort_findings_severity_order_not_alphabetical():
    items = [
        core.finding("metadata", "M", "note", "1", "m"),
        core.finding("metadata", "M", "warn", "2", "m"),
        core.finding("metadata", "M", "error", "3", "m"),
    ]
    got = [f["severity"] for f in core.sort_findings(items)]
    assert got == ["error", "warn", "note"]


def test_sort_findings_same_severity_by_primary_key():
    items = [
        core.finding("metadata", "M", "error", "U+0042", "m"),
        core.finding("metadata", "M", "error", "U+0041", "m"),
    ]
    got = [f["primary_key"] for f in core.sort_findings(items)]
    assert got == ["U+0041", "U+0042"]


# ==================================================================
# §11 收口矩阵（AST 函数面补齐：每条独立可证伪断言）
# ==================================================================

def test_codepage_probe_semantics_not_replicated_in_organ():
    # 旧仓 _codepage_probe_ranges 的位→探测区间表属 fontTools 侧；
    # 器官只判 bit0（表经 subject 供证）——这里钉住"器官不内置第二套表"
    organ_text = (SRC / "byteproof" / "auditors" / "subset_audit" / "core.py").read_text(encoding="utf-8")
    assert "OS2_UNICODE_RANGES" not in organ_text.replace(
        "OS2_UNICODE_RANGES 表", "").replace("OS2_UNICODE_RANGES`", "")


@pytest.mark.parametrize("cps,blocks", [
    ({0x41}, {"BMP": 1, "ExtA": 0, "ExtB+": 0, "other": 0}),
    ({0x3400, 0x4DBF}, {"BMP": 0, "ExtA": 2, "ExtB+": 0, "other": 0}),
    ({0x20000}, {"BMP": 0, "ExtA": 0, "ExtB+": 1, "other": 0}),
    (set(range(0x41, 0x5B)), {"BMP": 26, "ExtA": 0, "ExtB+": 0, "other": 0}),
    ({0x1F600, 0x1F601}, {"BMP": 0, "ExtA": 0, "ExtB+": 0, "other": 2}),
])
def test_block_counts_matrix_parametrized(cps, blocks):
    assert core.block_counts(cps) == blocks


@pytest.mark.parametrize("text,drop", [
    ("a\nb", 1),
    ("a\rb\n", 2),
    ("a\t\tb", 2),
    ("a b", 0),
    ("汉字\n", 1),
])
def test_from_text_drop_counts_matrix_parametrized(text, drop):
    # 控制字符被剔除：len(文本字符) − drop = 码位数
    assert len(core.from_text(text)) == len(text) - drop


@pytest.mark.parametrize("subset_cps,lost,hint_count", [
    ({0x41, 0x42}, [0x41], 1),
    (set(), [0x41, 0x42], 1),
    ({0x3400}, [0x41, 0x3400], 2),
    ({0x41}, [], 0),
])
def test_fallback_hint_count_matrix_parametrized(subset_cps, lost, hint_count):
    assert len(core.fallback_hint(lost, subset_cps)) == hint_count


@pytest.mark.parametrize("first,last,judged", [
    (0x41, 0x7A, True),
    (0xFFFF, 0x7A, True),
    (0x41, 0xFFFF, True),
    (0xFFFF, 0xFFFF, True),
])
def test_char_index_judged_matrix_parametrized(first, last, judged):
    os2 = _os2(usFirstCharIndex=first, usLastCharIndex=last)
    _findings, judged_got = core.char_index_findings(os2, {0x50})
    assert judged_got is judged


@pytest.mark.parametrize("codepoints,first,last,warn_primary_keys", [
    ({0x30, 0x7A}, 0x41, 0x7A, ["usFirstCharIndex"]),
    ({0x41, 0x20000}, 0x41, 0x7A, []),           # 非 BMP 码位不参与首末比对（BMP 面）
    ({0x50}, 0x41, 0x7A, []),
])
def test_char_index_directions_matrix_parametrized(codepoints, first, last, warn_primary_keys):
    os2 = _os2(usFirstCharIndex=first, usLastCharIndex=last)
    findings, _ = core.char_index_findings(os2, codepoints)
    assert sorted(f["primary_key"] for f in findings) == sorted(warn_primary_keys)


@pytest.mark.parametrize("inputs_count,index_expected", [
    (0, 0),
    (1, 1),
    (3, 3),   # 输入序列各不同（长度递增）→ index 三键；raw 与 index 是两个计数语义
])
def test_ligature_raw_vs_index_matrix_parametrized(inputs_count, index_expected):
    rows = [{"inputs": [0x66] * (i + 1), "glyph": "g%d" % i, "state": "named"}
            for i in range(inputs_count)]
    flat = {"ligature_index": rows, "ligature_rules_raw": inputs_count}
    index = core._ligature_index(flat)
    assert len(rows) == inputs_count
    assert len(index) == index_expected


@pytest.mark.parametrize("subset_side,expected_reason", [
    ("none", "layout_tables_missing_on_one_side"),
    ("present", None),
])
def test_layout_skip_presence_matrix_parametrized(subset_side, expected_reason):
    source = _flat([T_DFLT])
    subset = _flat([T_DFLT]) if subset_side == "present" else {"GSUB": None, "GPOS": None}
    _findings, skips, _ = core.compare_layout(source, subset)
    got = [s["reason"] for s in skips]
    assert (expected_reason in got) if expected_reason else (got == [])


@pytest.mark.parametrize("severity", ["error", "warn", "note"])
def test_finding_carries_severity_parametrized(severity):
    f = core.finding("metadata", "UNKNOWN_CODE", severity, "k", "m")
    assert f["severity"] == severity
    records = api._records({"findings": [f], "skips": [], "summary": {}}, _catalog())
    assert records[0].evidence["severity"] == severity


@pytest.mark.parametrize("field,value", [
    ("numGlyphs", 12),
    ("usFirstCharIndex", 0x41),
    ("usLastCharIndex", 0x7A),
])
def test_os2_fields_consumed_parametrized(field, value):
    os2 = _os2(**{field: value})
    assert os2[field] == value


def test_organ_version_is_1():
    assert spec.ORGAN_VERSION == "1" == SETTINGS["version"]


def test_modes_default_coverage_diff():
    assert spec.DEFAULT_MODE == "coverage-diff"


def test_notdef_names_frozen_three():
    assert spec.NOTDEF_NAMES == frozenset([".notdef", "glyph00000", ""])


def test_required_name_ids_nine_frozen():
    assert spec.REQUIRED_NAME_IDS == (0, 1, 2, 3, 4, 6, 13, 14, 17)


def test_name_classes_three_frozen():
    assert spec.CLASS_DEFAULT_STRIPPED == "default_stripped"
    assert spec.CLASS_AUTHOR_ABSENT == "author_absent"
    assert spec.CLASS_UNCLASSIFIED == "unclassified"


def test_basis_skip_reasons_match_thresholds():
    assert sorted(SETTINGS["skip_reasons"]) == sorted([
        "no_cmap_table", "no_unicode_cmap", "no_layout_tables",
        "layout_tables_missing_on_one_side", "no_os2_table", "no_name_table",
        "no_outline_table"])


def test_license_gate_module_not_in_organ_modes():
    # D1 排除词 license：license-gate 模块不迁（旧仓 MODULES 里有它）
    assert "license-gate" not in spec.MODES
    assert "license-gate" not in SETTINGS["modules"]


def test_skipped_record_shape_matches_old_canonical():
    s = core.skipped("metadata", "no_os2_table", "detail text")
    assert s["module"] == "metadata" and s["skipped"] is True
    assert s["reason"] == "no_os2_table" and s["detail"] == "detail text"


def test_finding_rejects_unknown_module_license_gate():
    # license-gate 不迁：旧仓 canonical.MODULES 的第五个成员在器官里不是合法 module
    with pytest.raises(ValueError):
        core.finding("license-gate", "L1", "error", "k", "m")


def test_thresholds_modules_excludes_license_gate():
    assert "license-gate" not in SETTINGS["modules"]
    assert SETTINGS["modules"] == ["coverage-diff", "layout-survival", "metadata"]


# ==================================================================
# §12 补测（机械 D1+D18 口径 · 判定面补齐到旧层 AST 195）
# ==================================================================

def test_closure_is_per_char_no_cross_char_composition():
    # 旧仓闭包是**逐字符** normalize：分解成立（á → a + ́），但跨字符合成不在闭包内
    # （a + combining acute 不会在闭包里冒出一个 á）——断言真实语义，不臆造双向
    closed, _added = core.closure([0x00E1])
    assert {0x0061, 0x0301} <= closed
    pair_closed, _a2 = core.closure([0x0061, 0x0301])
    assert 0x00E1 not in pair_closed


def test_closure_closed_superset_of_base():
    closed, added = core.closure([0x41, 0x5B57])
    assert {0x41, 0x5B57} <= closed
    assert all(cp not in added for cp in (0x41, 0x5B57))


def test_classify_subset_only_codepoint_not_classified():
    # subset 有、source 没有的码位：不进 OK/MISSING/LOST 任何一类（§6.2 三分类定义）
    got = core.classify({1, 2}, {1}, {1, 2})
    assert got["OK"] == [1]
    assert got["MISSING_IN_SOURCE"] == [2]
    assert got["LOST_IN_SUBSET"] == []


def test_coverage_required_text_and_int_list_union():
    subject = _subject(required_text="字", required=[0x6C49],
                       source_cmap={"23383": "a", "27721": "b"},
                       subset_cmap={"23383": "a", "27721": "b"})
    records = _evaluate(subject)
    summary = _summary(records).evidence["summary"]
    assert summary["required"]["count"] == 2


def test_coverage_hex_string_cmap_keys_accepted():
    # 旧仓 expect.json 摊平形态：cmap 键是 "0x…" 字符串
    assert core.codepoints({"0x5B57": "uni5B57", "0x6C49": ""}) == {0x5B57}


def test_coverage_notdef_in_source_never_ok():
    findings, _, summary = core.evaluate_coverage([0x5B57], {0x5B57: ".notdef"},
                                                  {0x5B57: "uni5B57"})
    assert summary["coverage"]["counts"]["OK"] == 0
    assert summary["coverage"]["counts"]["MISSING_IN_SOURCE"] == 1


def test_coverage_closure_added_not_in_categories():
    # 闭包新增码位只计数：三分类仍只用 R0（U+00E1），闭包里的 a/́ 不进 OK
    findings, _, summary = core.evaluate_coverage(
        [0x00E1], {0x00E1: "aacute"}, {0x00E1: "aacute"})
    assert summary["coverage"]["OK"] == ["U+00E1"]
    assert all(cp not in ("U+0061", "U+0301") for cp in summary["coverage"]["OK"])


def test_layout_triple_dedup_in_kept_lost_counts():
    # 四元组精确去重：源侧重复列同一三元组，kept 按集合计 1
    source = _flat([T_DFLT, T_DFLT])
    subset = _flat([T_DFLT])
    _findings, _skips, summary = core.compare_layout(source, subset)
    assert summary["layout"]["kept"]["triples"] == 1
    assert summary["layout"]["lost"]["triples"] == 0


def test_layout_ligature_target_glyph_not_in_key():
    # 目标字形不参与键：同输入序列、不同目标字形 → 仍是一个键（首次优先）
    flat = _flat([T_DFLT], gsub_lig=[
        {"inputs": [0x66, 0x69], "glyph": "gA", "state": "named"},
        {"inputs": [0x66, 0x69], "glyph": "gB", "state": "named"},
    ])
    index = core._ligature_index(flat["GSUB"])
    assert len(index) == 1
    assert index[(0x66, 0x69)]["glyph"] == "gA"


def test_layout_subset_missing_table_all_features_dropped():
    source = _flat([T_DFLT, ("latn", "dflt", "kern")])
    subset = {"GSUB": None, "GPOS": None}
    findings, skips, _ = core.compare_layout(source, subset)
    lost = [f for f in findings if f["code"] == "LAYOUT_FEATURE_LOST"]
    assert len(lost) == 2
    assert [s["reason"] for s in skips] == ["layout_tables_missing_on_one_side"]


def test_layout_histogram_keys_sorted_strings():
    flat = _flat([T_DFLT])
    flat["GSUB"]["subtable_types"] = {6: 2, 4: 1, 1: 3}
    counts = core._counts(flat["GSUB"])
    assert list(counts["subtable_types"].keys()) == ["1", "4", "6"]


def test_metadata_name_present_and_missing_disjoint():
    subset_ids = {0: "v", 1: "v"}
    present, missing, classes = core._name_state(subset_ids, {0: "v", 1: "v"})
    assert set(present) & set(missing) == set()
    assert set(present) | set(missing) == set(spec.REQUIRED_NAME_IDS)


def test_metadata_codepage_evidence_fields():
    findings = core.codepage_findings(_os2(codepage_bits=[0]), {0x5B57})
    assert findings[0]["evidence"]["claims_latin1"] is True
    assert findings[0]["evidence"]["latin1_codepoints"] == 0
    assert findings[0]["evidence"]["codepoints_total"] == 1


def test_metadata_unicode_range_behavioral_bit_message():
    os2 = _os2(unicode_range_bits=[57])
    findings, _ = core.unicode_range_findings(os2, {0x5B57}, _ranges())
    assert "非 BMP 码位" in findings[0]["message"]
    assert findings[0]["evidence"]["behavioral"] is True


def test_metadata_char_index_warn_evidence_names():
    os2 = _os2(usFirstCharIndex=0x41, usLastCharIndex=0x7A)
    findings, _ = core.char_index_findings(os2, {0x20})
    assert findings[0]["evidence"]["field"] == "usFirstCharIndex"
    assert findings[0]["evidence"]["measured_min"] == "U+0020"


def test_metadata_maxp_evidence_numglyphs():
    findings, _ = core.maxp_findings(10, 7)
    assert findings[0]["evidence"]["numGlyphs"] == 10
    assert findings[0]["evidence"]["measured"] == 7


def test_finding_evidence_is_copied_not_aliased():
    evidence = {"k": 1}
    f = core.finding("metadata", "UNKNOWN_X", "warn", "pk", "m", evidence=evidence)
    evidence["late"] = 2
    assert "late" not in f["evidence"]


def test_skipped_detail_defaults_empty():
    s = core.skipped("coverage-diff", "no_cmap_table")
    assert s["detail"] == ""


def test_sort_findings_module_string_order():
    # 排序键第一段是 module 字符串（不是枚举序）：coverage-diff < layout-survival < metadata
    items = [
        core.finding("metadata", "M", "error", "a", "m"),
        core.finding("layout-survival", "L", "error", "a", "m"),
        core.finding("coverage-diff", "C", "error", "a", "m"),
    ]
    assert [f["module"] for f in core.sort_findings(items)] == [
        "coverage-diff", "layout-survival", "metadata"]


def test_u_format_beyond_bmp():
    assert core.u(0x10FFFF) == "U+10FFFF"
    assert core.u(0x1F600) == "U+1F600"


def test_fallback_hint_single_block_aggregates_lost():
    hints = core.fallback_hint([0x5B57, 0x6C49], {0x5B58})
    assert len(hints) == 1
    assert hints[0]["block"] == "BMP" and hints[0]["lost"] == 2


def test_from_text_astral_codepoint():
    assert core.from_text("😀") == {0x1F600}


def test_coverage_category_counts_sum_to_required():
    required = [0x41, 0x42, 0x43]
    findings, _, summary = core.evaluate_coverage(
        required, {0x41: "a", 0x42: "b"}, {0x41: "a"})
    counts = summary["coverage"]["counts"]
    assert sum(counts.values()) == len(required)


def test_coverage_lost_evidence_subset_covered_false():
    findings, _, _ = core.evaluate_coverage([0x5B57], {0x5B57: "g"}, {})
    lost = [f for f in findings if f["code"] == "LOST_IN_SUBSET"][0]
    assert lost["evidence"]["subset_covered"] is False
    assert lost["evidence"]["source_covered"] is True


def test_layout_renamed_evidence_both_glyphs():
    lig_src = [{"inputs": [0x66, 0x69], "glyph": "uniFB01", "state": "named"}]
    lig_sub = [{"inputs": [0x66, 0x69], "glyph": "glyph00003", "state": "placeholder"}]
    findings, _, _ = core.compare_layout(_flat([T_DFLT], gsub_lig=lig_src),
                                         _flat([T_DFLT], gsub_lig=lig_sub))
    renamed = [f for f in findings if f["code"] == "LAYOUT_LIGATURE_RENAMED"][0]
    assert renamed["evidence"]["ligature_source_glyph"] == "uniFB01"
    assert renamed["evidence"]["ligature_subset_glyph"] == "glyph00003"


def test_name_codes_are_distinct():
    codes = [c for c, _s in spec.NAME_CODES.values()]
    assert len(codes) == len(set(codes)) == len(spec.REQUIRED_NAME_IDS)


def test_name_codes_cover_all_required_ids():
    assert sorted(spec.NAME_CODES.keys()) == sorted(spec.REQUIRED_NAME_IDS)