"""``thesis_audit.core_doc`` 的纯判定核测试（迁自 10-7-thesis-audit-workbench 的文档面）。

覆盖六个 mode（aigc / structure / terms / figures / school / rng）的判定面与
输入守卫：白名单 rule_id、verdict 纪律、纯函数性（不读文件/环境/时钟、不改入参）、
阈值相等、空白归一、确定性 RNG 金标，以及每类坏输入的 ``ValueError``。

测试自足：不读旧仓、不读数据文件；所有事实由 subject 直接构造。
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof.auditors.thesis_audit import core_doc


# ---------------------------------------------------------------- 辅助
def _p(i, text, style=""):
    return {"i": i, "text": text, "style": style}


def _rules(*rules):
    return {"rules": list(rules)}


def _by_rule(findings, rule_id):
    return [f for f in findings if f["rule_id"] == rule_id]


def _paths(findings, rule_id):
    return [f["path"] for f in _by_rule(findings, rule_id)]


def _items(findings, rule_id):
    return [f["evidence"].get("item") for f in _by_rule(findings, rule_id)]


def _good_tree():
    """结构检查的基线文档：摘要四要素 / 中英关键词 / 三类章 / 章小结 / 结论呼应齐全。"""
    return [
        _p(0, "论文题目", "Title"),
        _p(1, "摘要", "Normal"),
        _p(2, "针对问题，提出方法，结果表明，因此得出结论。", "Normal"),
        _p(3, "关键词：甲；乙；丙", "Normal"),
        _p(4, "Abstract", "Normal"),
        _p(5, "Keywords: a; b; c", "Normal"),
        _p(6, "第一章 绪论", "Heading 1"),
        _p(7, "本章小结：内容。", "Normal"),
        _p(8, "第二章 方法", "Heading 1"),
        _p(9, "本章小结：内容。", "Normal"),
        _p(10, "第三章 结论", "Heading 1"),
        _p(11, "针对问题提出方法，结果表明结论成立。", "Normal"),
    ]


def _term(canonical="机器学习", variants=None, term_id="T1", kind=None):
    return {"term_id": term_id, "canonical": canonical,
            "variants": variants if variants is not None else [canonical],
            "kind": kind}


def _style_rule(activation="active", rule_id="S1"):
    return {"rule_id": rule_id, "check_type": "style", "activation": activation}


def _fmt_rule(param="margin_left_mm", op="eq", value=30, tolerance=None,
              activation="active", rule_id="F1"):
    detect = {"param": param, "op": op, "value": value}
    if tolerance is not None:
        detect["tolerance"] = tolerance
    return {"rule_id": rule_id, "check_type": "format",
            "activation": activation, "detect": detect}


def _verdict_subjects():
    """六 mode 的「全规则」输入：用于白名单 / verdict 纪律 / 输出 schema 横扫。"""
    return {
        "aigc": {"paragraphs": ["首先"],
                 "features": {"aigc-02": {"threshold": {"warn": 0.0}}}},
        "structure": {"style_tree": [_p(0, "第一章 绪论", "Heading 2")]},
        "terms": {
            "style_tree": [
                _p(0, "第一章 绪论", "Heading 1"),
                _p(1, "GB/T7714规范 与 12,345。", "Normal"),
                _p(2, "12345。", "Normal"),
            ],
            "terms": [_term(canonical="GB/T 7714",
                            variants=["GB/T7714", "GB/T7714规范"])],
            "number_usage": {"enabled": True},
        },
        "figures": {"parsed": {
            "objects": [{"kind": "figure", "label": "图1-1"},
                        {"kind": "figure", "label": "图1-3"}],
            "markers": [{"label": "图1-1"}, {"label": "图1-9"}],
        }},
        "school": {
            "style_tree": [_p(0, "第1章 绪论", "Normal")],
            "doc_format": {"margin_left_mm": 40.0},
            "ruleset": _rules(_style_rule(), _fmt_rule()),
        },
        "rng": {"seed": 0, "n": 2},
    }


# ================================================================ 契约面
def test_unknown_mode_raises_value_error():
    with pytest.raises(ValueError, match="未知 mode"):
        core_doc.evaluate("nope", {})


def test_non_string_mode_raises_value_error():
    with pytest.raises(ValueError, match="mode 必须是 str"):
        core_doc.evaluate(3, {})


def test_non_mapping_subject_raises_value_error():
    with pytest.raises(ValueError, match="subject 必须是 dict"):
        core_doc.evaluate("aigc", [("para", "x")])


def test_all_six_modes_return_lists():
    subjects = {
        "aigc": {"paragraphs": []},
        "structure": {"style_tree": []},
        "terms": {"style_tree": [], "terms": []},
        "figures": {"parsed": {"objects": []}},
        "school": {"doc_format": {}, "ruleset": _rules()},
        "rng": {"seed": 0, "n": 0},
    }
    for mode, subject in subjects.items():
        assert isinstance(core_doc.evaluate(mode, subject), list)


def test_modes_constant_lists_six_modes():
    assert set(core_doc.MODES) == {"aigc", "structure", "terms",
                                   "figures", "school", "rng"}


def test_rule_id_whitelist_has_fifteen_entries():
    assert len(core_doc.RULE_IDS) == 15
    assert len(set(core_doc.RULE_IDS)) == 15


def test_findings_have_exactly_five_keys():
    for mode, subject in _verdict_subjects().items():
        for finding in core_doc.evaluate(mode, subject):
            assert set(finding) == {"rule_id", "verdict", "message", "path", "evidence"}


def test_rule_ids_stay_in_whitelist():
    for mode, subject in _verdict_subjects().items():
        for finding in core_doc.evaluate(mode, subject):
            assert finding["rule_id"] in core_doc.RULE_IDS


def test_verdict_discipline_covers_all_rules():
    expected = {
        "taw-aigc-band": "warn", "taw-aigc-dist": "info",
        "taw-struct-heading": "error", "taw-struct-abstract": "error",
        "taw-struct-chapter": "error",
        "taw-term-hit": "warn", "taw-term-stray": "warn",
        "taw-term-number": "warn", "taw-term-heat": "info",
        "taw-fig-xref": "error", "taw-fig-gap": "error",
        "taw-fig-renumber": "info",
        "taw-school-style": "error", "taw-school-format": "error",
        "taw-rng-determinism": "info",
    }
    seen = {}
    for mode, subject in _verdict_subjects().items():
        for finding in core_doc.evaluate(mode, subject):
            seen.setdefault(finding["rule_id"], set()).add(finding["verdict"])
    assert set(seen) == set(expected)
    for rule_id, verdicts in seen.items():
        assert verdicts == {expected[rule_id]}


def test_module_does_not_bind_forbidden_imports():
    for name in ("os", "sys", "pathlib", "json", "time", "datetime",
                 "random", "docx"):
        assert name not in vars(core_doc)


def test_evaluate_is_the_only_documented_entry():
    assert callable(core_doc.evaluate)
    assert core_doc.evaluate.__code__.co_argcount == 2


def test_repeated_calls_are_deterministic():
    subject = {"paragraphs": ["首先。", "综上所述。"],
               "features": {"aigc-02": {"threshold": {"warn": 0.0}}}}
    assert core_doc.evaluate("aigc", subject) == core_doc.evaluate("aigc", subject)


def test_subject_is_not_mutated():
    subject = {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"},
                    {"kind": "figure", "label": "图1-3"}],
        "markers": [{"label": "图1-9", "para_index": 3}],
    }}
    before = copy.deepcopy(subject)
    core_doc.evaluate("figures", subject)
    assert subject == before


def test_edits_input_is_not_mutated():
    subject = {"parsed": {"objects": [{"kind": "figure", "label": "图1-1"}]},
               "edits": [{"type": "insert", "new_item_id": "图9-9",
                          "target": "图1-1", "before": True}]}
    before = copy.deepcopy(subject)
    core_doc.evaluate("figures", subject)
    assert subject == before


# ================================================================ AIGC
def test_aigc_empty_paragraphs_only_distribution():
    findings = core_doc.evaluate("aigc", {"paragraphs": []})
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "taw-aigc-dist"


def test_aigc_distribution_zero_counts():
    evidence = core_doc.evaluate("aigc", {"paragraphs": []})[0]["evidence"]
    assert evidence["paragraphs_scored"] == 0
    assert evidence["paragraphs_flagged"] == 0
    assert evidence["by_feature"] == {"aigc-01": 0, "aigc-02": 0,
                                      "aigc-03": 0, "aigc-04": 0}


def test_aigc_string_paragraph_is_scored():
    findings = core_doc.evaluate("aigc", {"paragraphs": ["普通正文。"]})
    assert findings[0]["evidence"]["paragraphs_scored"] == 1


def test_aigc_dict_paragraph_index_used_in_path():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": [{"index": 7, "text": "首先", "style": "Normal"}],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}}},
    })
    assert "para:7/aigc-02" in _paths(findings, "taw-aigc-band")


def test_aigc_template_connector_warn_band():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先"],
        "features": {"aigc-02": {"threshold": {"warn": 500.0}}},
    })
    band = _by_rule(findings, "taw-aigc-band")[0]
    assert band["evidence"]["band"] == "warn"
    assert band["evidence"]["counts"]["aigc-02"] == 1


def test_aigc_summary_cliche_high_band():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["综上所述"],
        "features": {"aigc-03": {"threshold": {"high": 0.0}}},
    })
    assert _by_rule(findings, "taw-aigc-band")[0]["evidence"]["band"] == "high"


def test_aigc_parallel_marker_band():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["不仅"],
        "features": {"aigc-04": {"threshold": {"warn": 500.0}}},
    })
    band = _by_rule(findings, "taw-aigc-band")[0]
    assert band["evidence"]["fired"] == ["aigc-04"]


def test_aigc_uniform_sentences_enter_distribution_only():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["abc。def。"],
        "features": {"aigc-01": {"threshold": {"high": 0.1}}},
    })
    assert _by_rule(findings, "taw-aigc-band") == []
    dist = _by_rule(findings, "taw-aigc-dist")[0]
    assert dist["evidence"]["by_feature"]["aigc-01"] == 1


def test_aigc_cv_threshold_equality_is_high():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["abc。def。"],
        "features": {"aigc-01": {"threshold": {"high": 0.0}}},
    })
    assert findings[0]["evidence"]["by_feature"]["aigc-01"] == 1


def test_aigc_single_sentence_cv_is_none():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["单句没有标点"],
        "features": {"aigc-01": {"threshold": {"high": 0.9}}},
    })
    assert findings[0]["evidence"]["by_feature"]["aigc-01"] == 0


def test_aigc_density_is_per_thousand_chars():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先，其次。"],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}}},
    })
    band = _by_rule(findings, "taw-aigc-band")[0]
    assert band["evidence"]["densities"]["aigc-02"] == pytest.approx(2000.0 / 6.0)


def test_aigc_band_threshold_equality_high():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先"],
        "features": {"aigc-02": {"threshold": {"high": 500.0}}},
    })
    assert _by_rule(findings, "taw-aigc-band")[0]["evidence"]["band"] == "high"


def test_aigc_band_threshold_equality_warn():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先"],
        "features": {"aigc-02": {"threshold": {"warn": 500.0}}},
    })
    assert _by_rule(findings, "taw-aigc-band")[0]["evidence"]["band"] == "warn"


def test_aigc_below_warn_threshold_is_silent():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先"],
        "features": {"aigc-02": {"threshold": {"warn": 500.0001}}},
    })
    assert _by_rule(findings, "taw-aigc-band") == []


def test_aigc_heading_paragraphs_are_skipped():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": [{"text": "首先", "style": "Heading 1"}],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}}},
    })
    assert findings[0]["evidence"]["paragraphs_scored"] == 0


def test_aigc_title_and_caption_are_skipped():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": [{"text": "首先", "style": "Title"},
                       {"text": "首先", "style": "Caption"}],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}}},
    })
    assert findings[0]["evidence"]["paragraphs_scored"] == 0


def test_aigc_blank_text_is_skipped():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": [{"text": "   ", "style": "Normal"}],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}}},
    })
    assert findings[0]["evidence"]["paragraphs_scored"] == 0


def test_aigc_multiple_features_yield_single_finding():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先。综上所述。"],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}},
                     "aigc-03": {"threshold": {"high": 0.0}}},
    })
    bands = _by_rule(findings, "taw-aigc-band")
    assert len(bands) == 1
    assert bands[0]["evidence"]["fired"] == ["aigc-02", "aigc-03"]
    assert bands[0]["evidence"]["band"] == "high"


def test_aigc_risk_score_weights_high_and_warn():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先。综上所述。"],
        "features": {"aigc-02": {"threshold": {"high": 0.0}, "weight": 0.5},
                     "aigc-03": {"threshold": {"warn": 0.0}, "weight": 0.4}},
    })
    assert _by_rule(findings, "taw-aigc-band")[0]["evidence"]["score"] == 0.74


def test_aigc_risk_score_is_capped_at_one():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先。综上所述。"],
        "features": {"aigc-02": {"threshold": {"high": 0.0}, "weight": 1.0},
                     "aigc-03": {"threshold": {"high": 0.0}, "weight": 1.0}},
    })
    assert _by_rule(findings, "taw-aigc-band")[0]["evidence"]["score"] == 1.0


def test_aigc_distribution_flagged_paras():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": [{"index": 3, "text": "首先"},
                       {"index": 9, "text": "综上所述"}],
        "features": {"aigc-02": {"threshold": {"warn": 0.0}},
                     "aigc-03": {"threshold": {"warn": 0.0}}},
    })
    dist = _by_rule(findings, "taw-aigc-dist")[0]
    assert dist["evidence"]["flagged_paras"] == [3, 9]
    assert dist["evidence"]["paragraphs_flagged"] == 2


def test_aigc_distribution_max_score():
    findings = core_doc.evaluate("aigc", {
        "paragraphs": ["首先"],
        "features": {"aigc-02": {"threshold": {"high": 0.0}, "weight": 1.0}},
    })
    assert _by_rule(findings, "taw-aigc-dist")[0]["evidence"]["max_score"] == 1.0


def test_aigc_features_absent_means_no_bands():
    findings = core_doc.evaluate("aigc", {"paragraphs": ["首先"]})
    dist = _by_rule(findings, "taw-aigc-dist")[0]
    assert dist["evidence"]["by_feature"] == {"aigc-01": 0, "aigc-02": 0,
                                              "aigc-03": 0, "aigc-04": 0}


def test_aigc_missing_paragraphs_raises():
    with pytest.raises(ValueError, match="缺少字段 paragraphs"):
        core_doc.evaluate("aigc", {})


def test_aigc_paragraph_wrong_type_raises():
    with pytest.raises(ValueError, match="必须是 str 或 dict"):
        core_doc.evaluate("aigc", {"paragraphs": [3]})


def test_aigc_paragraph_missing_text_raises():
    with pytest.raises(ValueError, match="缺少字段 text"):
        core_doc.evaluate("aigc", {"paragraphs": [{"index": 0}]})


def test_aigc_features_wrong_type_raises():
    with pytest.raises(ValueError, match="features 必须是 dict"):
        core_doc.evaluate("aigc", {"paragraphs": [], "features": []})


def test_aigc_threshold_wrong_type_raises():
    with pytest.raises(ValueError, match="threshold.warn 必须是数值"):
        core_doc.evaluate("aigc", {
            "paragraphs": [],
            "features": {"aigc-02": {"threshold": {"warn": "500"}}},
        })


def test_aigc_weight_wrong_type_raises():
    with pytest.raises(ValueError, match="weight 必须是数值"):
        core_doc.evaluate("aigc", {
            "paragraphs": [],
            "features": {"aigc-02": {"weight": "heavy"}},
        })


# ================================================================ 结构
def test_structure_good_document_has_no_findings():
    assert core_doc.evaluate("structure", {"style_tree": _good_tree()}) == []


def test_structure_missing_abstract_reports_abstract():
    tree = [_p(0, "第一章 绪论", "Heading 1"),
            _p(1, "第二章 方法", "Heading 1"),
            _p(2, "第三章 结论", "Heading 1")]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "abstract_present" in _items(findings, "taw-struct-abstract")


def test_structure_abstract_with_two_elements_fails():
    tree = _good_tree()
    tree[2] = _p(2, "针对问题，提出方法。", "Normal")
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "abstract_elements" in _items(findings, "taw-struct-abstract")


def test_structure_keywords_two_fails():
    tree = _good_tree()
    tree[3] = _p(3, "关键词：甲；乙", "Normal")
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "keywords_count" in _items(findings, "taw-struct-abstract")


def test_structure_keywords_three_passes():
    findings = core_doc.evaluate("structure", {"style_tree": _good_tree()})
    assert "keywords_count" not in _items(findings, "taw-struct-abstract")


def test_structure_keywords_eight_passes():
    tree = _good_tree()
    tree[3] = _p(3, "关键词：" + "；".join(str(i) for i in range(8)), "Normal")
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "keywords_count" not in _items(findings, "taw-struct-abstract")


def test_structure_keywords_nine_fails():
    tree = _good_tree()
    tree[3] = _p(3, "关键词：" + "；".join(str(i) for i in range(9)), "Normal")
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "keywords_count" in _items(findings, "taw-struct-abstract")


def test_structure_english_abstract_missing_fails():
    tree = [p for p in _good_tree() if p["i"] not in (4, 5)]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "english_abstract" in _items(findings, "taw-struct-abstract")


def test_structure_chapters_missing_fails():
    tree = _good_tree()
    tree[8] = _p(8, "第二章 讨论", "Heading 1")
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "chapters_complete" in _items(findings, "taw-struct-chapter")


def test_structure_chapter_summary_missing_fails():
    tree = [p for p in _good_tree() if p["i"] not in (7, 9)]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "chapter_summary" in _items(findings, "taw-struct-chapter")


def test_structure_conclusion_echo_low_fails():
    tree = _good_tree()
    tree[11] = _p(11, "天气很好。", "Normal")
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "conclusion_echo" in _items(findings, "taw-struct-chapter")


def test_structure_degraded_chapter_heading_reports_heading():
    tree = [_p(0, "第一章 绪论", "Heading 2")]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "heading:0" in _paths(findings, "taw-struct-heading")


def test_structure_level_jump_reports_heading():
    tree = [_p(0, "第一章 绪论", "Heading 1"),
            _p(1, "1.1 小节", "Heading 3")]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    jumps = [f for f in _by_rule(findings, "taw-struct-heading")
             if f["evidence"].get("issue") == "level_jump"]
    assert [f["path"] for f in jumps] == ["heading:1"]
    assert jumps[0]["evidence"]["from"] == 1
    assert jumps[0]["evidence"]["to"] == 3


def test_structure_heading_levels_checklist_item_also_fires():
    tree = [_p(0, "第一章 绪论", "Heading 2")]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert _paths(findings, "taw-struct-heading") == ["heading:0", "report"]


def test_structure_empty_tree_fails_all_checklist():
    findings = core_doc.evaluate("structure", {"style_tree": []})
    items = {f["evidence"]["item"] for f in findings}
    assert items == {"abstract_present", "abstract_elements", "keywords_count",
                     "english_abstract", "chapters_complete", "chapter_summary",
                     "conclusion_echo"}
    assert all(f["path"] == "report" for f in findings)


def test_structure_headings_override_suppresses_level_jump():
    tree = [_p(0, "第一章 绪论", "Heading 1"),
            _p(1, "小节", "Heading 3")]
    derived = core_doc.evaluate("structure", {"style_tree": tree})
    assert any(f["evidence"].get("issue") == "level_jump" for f in derived)
    override = core_doc.evaluate("structure", {"style_tree": {
        "paragraphs": tree,
        "headings": [{"para": 0, "level": 1, "text": "第一章 绪论"},
                     {"para": 1, "level": 1, "text": "小节"}],
    }})
    assert not any(f["evidence"].get("issue") == "level_jump" for f in override)


def test_structure_abstract_pseudo_heading_is_not_chapter():
    tree = [_p(0, "摘要", "Normal"),
            _p(1, "内容", "Normal"),
            _p(2, "第一章 绪论", "Heading 1")]
    model = core_doc.parse_structure(tree)
    assert [c["para"] for c in model["chapters"]] == [2]
    assert "摘要" not in [c["text"] for c in model["chapters"]]


def test_structure_ruleset_only_order_suppresses_checklist():
    tree = [_p(0, "第一章 绪论", "Heading 2")]
    ruleset = _rules({"rule_id": "R1", "check_type": "structure_order",
                      "activation": "active"})
    findings = core_doc.evaluate("structure", {"style_tree": tree,
                                               "ruleset": ruleset})
    assert [f["path"] for f in findings] == ["heading:0"]
    assert all(f["rule_id"] == "taw-struct-heading" for f in findings)


def test_structure_ruleset_inactive_rule_suppresses_order():
    tree = [_p(0, "第一章 绪论", "Heading 2")]
    ruleset = _rules({"rule_id": "R1", "check_type": "structure_order",
                      "activation": "gated"})
    subject = {"style_tree": tree, "ruleset": ruleset}
    findings = core_doc.evaluate("structure", subject)
    assert findings == []


def test_structure_ruleset_status_verified_without_activation_is_on():
    tree = [_p(0, "第一章 绪论", "Heading 2")]
    ruleset = _rules({"rule_id": "R1", "check_type": "structure_order",
                      "status": "verified"})
    findings = core_doc.evaluate("structure", {"style_tree": tree,
                                               "ruleset": ruleset})
    assert [f["path"] for f in findings] == ["heading:0"]


def test_structure_ruleset_bad_shape_raises():
    with pytest.raises(ValueError, match="ruleset.rules 必须是 list"):
        core_doc.evaluate("structure", {"style_tree": [],
                                        "ruleset": {"rules": "nope"}})


def test_structure_missing_style_tree_raises():
    with pytest.raises(ValueError, match="缺少字段 style_tree"):
        core_doc.evaluate("structure", {})


def test_structure_paragraph_missing_text_raises():
    with pytest.raises(ValueError, match="缺少字段 text"):
        core_doc.evaluate("structure", {"style_tree": [{"i": 0}]})


def test_structure_heading_override_bad_level_raises():
    with pytest.raises(ValueError, match="level 必须是 >=1 的 int"):
        core_doc.evaluate("structure", {"style_tree": {
            "paragraphs": [],
            "headings": [{"para": 0, "level": 0, "text": "x"}],
        }})


def test_structure_checklist_finding_keeps_checklist_evidence():
    findings = core_doc.evaluate("structure", {"style_tree": []})
    item = _by_rule(findings, "taw-struct-abstract")[0]
    assert item["evidence"]["item"] in {"abstract_present", "abstract_elements",
                                        "keywords_count", "english_abstract"}
    assert "detail" in item["evidence"]


def test_structure_chapter_violation_verdict_is_error():
    findings = core_doc.evaluate("structure", {"style_tree": []})
    assert all(f["verdict"] == "error" for f in findings)


def test_structure_chinese_numeral_degraded_heading():
    tree = [_p(0, "第二章 方法", "Heading 2")]
    findings = core_doc.evaluate("structure", {"style_tree": tree})
    assert "heading:0" in _paths(findings, "taw-struct-heading")


# ================================================================ 术语与数字
def test_terms_empty_terms_only_heat():
    findings = core_doc.evaluate("terms", {"style_tree": [], "terms": []})
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "taw-term-heat"


def test_terms_canonical_only_no_hit():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习。", "Normal")],
        "terms": [_term(variants=["机器学习"])],
    })
    assert _by_rule(findings, "taw-term-hit") == []


def test_terms_variant_reports_warn_hit():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    hits = _by_rule(findings, "taw-term-hit")
    assert len(hits) == 1
    assert hits[0]["verdict"] == "warn"


def test_terms_hit_path_format():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(2, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    path = _by_rule(findings, "taw-term-hit")[0]["path"]
    assert path == "term:机器学习法@para:2"


def test_terms_whitespace_equal_variant_skipped_by_hit_scan():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习。", "Normal")],
        "terms": [_term(variants=["机器 学习"])],
    })
    assert _by_rule(findings, "taw-term-hit") == []
    assert _by_rule(findings, "taw-term-stray") == []


def test_terms_extra_space_reported_as_stray():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器  学习。", "Normal")],
        "terms": [_term(variants=["机器 学习"])],
    })
    stray = _by_rule(findings, "taw-term-stray")
    assert len(stray) == 1
    assert stray[0]["evidence"]["variant"] == "机器  学习"


def test_terms_missing_space_reported_as_stray():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "GB/T7714。", "Normal")],
        "terms": [_term(canonical="GB/T 7714", variants=["GB/T 7714"])],
    })
    assert _by_rule(findings, "taw-term-stray")[0]["evidence"]["variant"] == "GB/T7714"


def test_terms_exact_canonical_not_reported_as_stray():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "GB/T 7714。", "Normal")],
        "terms": [_term(canonical="GB/T 7714", variants=["GB/T 7714"])],
    })
    assert _by_rule(findings, "taw-term-stray") == []


def test_terms_stray_routes_by_flag_even_with_term_kind():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器  学习。", "Normal")],
        "terms": [_term(variants=["机器 学习"], kind="concept")],
    })
    stray = _by_rule(findings, "taw-term-stray")
    assert len(stray) == 1
    assert stray[0]["evidence"]["kind"] == "concept"


def test_terms_heading_paragraphs_are_exempt():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法", "Heading 1")],
        "terms": [_term(variants=["机器学习法"])],
    })
    assert _by_rule(findings, "taw-term-hit") == []
    assert _by_rule(findings, "taw-term-heat")[0]["evidence"]["by_para"] == {}


def test_terms_reference_label_paragraphs_are_exempt():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "[1] 机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    assert _by_rule(findings, "taw-term-hit") == []


def test_terms_caption_paragraphs_are_exempt():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法", "Caption")],
        "terms": [_term(variants=["机器学习法"])],
    })
    assert _by_rule(findings, "taw-term-hit") == []


def test_terms_hits_aggregate_per_paragraph():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法。", "Normal"),
                       _p(1, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    assert len(_by_rule(findings, "taw-term-hit")) == 2


def test_terms_number_usage_both_forms_reports_each_para():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "共 12,345 人。", "Normal"),
                       _p(1, "共 12345 人。", "Normal")],
        "terms": [],
        "number_usage": {"enabled": True},
    })
    numbers = _by_rule(findings, "taw-term-number")
    assert [f["path"] for f in numbers] == ["para:0/number_form",
                                            "para:1/number_form"]
    assert numbers[0]["evidence"]["value"] == "12345"


def test_terms_number_usage_same_para_single_finding():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "12,345 与 12345。", "Normal")],
        "terms": [],
        "number_usage": {"enabled": True},
    })
    assert len(_by_rule(findings, "taw-term-number")) == 1


def test_terms_number_sep_only_is_silent():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "12,345。", "Normal")],
        "terms": [],
        "number_usage": {"enabled": True},
    })
    assert _by_rule(findings, "taw-term-number") == []


def test_terms_number_plain_only_is_silent():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "12345。", "Normal")],
        "terms": [],
        "number_usage": {"enabled": True},
    })
    assert _by_rule(findings, "taw-term-number") == []


def test_terms_number_three_digits_is_not_plain():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "999 与 999。", "Normal")],
        "terms": [],
        "number_usage": {"enabled": True},
    })
    assert _by_rule(findings, "taw-term-number") == []


def test_terms_number_heading_is_exempt():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "12,345 与 12345", "Heading 1")],
        "terms": [],
        "number_usage": {"enabled": True},
    })
    assert _by_rule(findings, "taw-term-number") == []


def test_terms_heat_by_para():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "正文。", "Normal"), _p(1, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    heat = _by_rule(findings, "taw-term-heat")[0]
    assert heat["evidence"]["by_para"] == {1: 1}


def test_terms_heat_by_chapter():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "第一章 绪论", "Heading 1"),
                       _p(1, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    heat = _by_rule(findings, "taw-term-heat")[0]
    assert heat["evidence"]["by_chapter"] == {"第一章 绪论": 1}


def test_terms_heat_uses_preamble_label():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
    })
    heat = _by_rule(findings, "taw-term-heat")[0]
    assert heat["evidence"]["by_chapter"] == {"(篇首)": 1}


def test_terms_ruleset_inactive_suppresses_hits():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
        "ruleset": _rules({"rule_id": "T", "check_type": "term_consistency",
                           "activation": "gated"}),
    })
    assert _by_rule(findings, "taw-term-hit") == []
    assert _by_rule(findings, "taw-term-heat")[0]["evidence"]["hits"] == 0


def test_terms_ruleset_active_enables_hits():
    findings = core_doc.evaluate("terms", {
        "style_tree": [_p(0, "机器学习法。", "Normal")],
        "terms": [_term(variants=["机器学习法"])],
        "ruleset": _rules({"rule_id": "T", "check_type": "term_consistency",
                           "activation": "active"}),
    })
    assert len(_by_rule(findings, "taw-term-hit")) == 1


def test_terms_bad_terms_type_raises():
    with pytest.raises(ValueError, match="terms 必须是 list"):
        core_doc.evaluate("terms", {"style_tree": [], "terms": {}})


def test_terms_term_missing_canonical_raises():
    with pytest.raises(ValueError, match="canonical 必须是非空 str"):
        core_doc.evaluate("terms", {"style_tree": [],
                                    "terms": [{"variants": ["x"]}]})


def test_terms_empty_variants_raises():
    with pytest.raises(ValueError, match="variants 必须是非空 list"):
        core_doc.evaluate("terms", {"style_tree": [],
                                    "terms": [{"canonical": "x", "variants": []}]})


def test_terms_number_usage_wrong_type_raises():
    with pytest.raises(ValueError, match="number_usage 必须是 dict"):
        core_doc.evaluate("terms", {"style_tree": [], "terms": [],
                                    "number_usage": "yes"})


def test_terms_missing_terms_raises():
    with pytest.raises(ValueError, match="缺少字段 terms"):
        core_doc.evaluate("terms", {"style_tree": []})


def test_terms_missing_style_tree_raises():
    with pytest.raises(ValueError, match="缺少字段 style_tree"):
        core_doc.evaluate("terms", {"terms": []})


# ================================================================ 图表/公式/交叉引用
def test_figures_empty_objects_only_renumber():
    findings = core_doc.evaluate("figures", {"parsed": {"objects": []}})
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "taw-fig-renumber"
    assert findings[0]["evidence"]["verified"] is True


def test_figures_parsed_dangling_typed():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [],
        "markers": [{"label": "图9-9", "para_index": 4}],
    }})
    dangling = _by_rule(findings, "taw-fig-xref")[0]
    assert dangling["path"] == "object:图9-9"
    assert "手打编号" in dangling["message"]
    assert dangling["verdict"] == "error"


def test_figures_parsed_dangling_ref_field_message():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [],
        "dangling": [{"label": "图1-2", "kind": "ref_field",
                      "target_bookmark": "BKM_7", "raw": "图1-2"}],
    }})
    dangling = _by_rule(findings, "taw-fig-xref")[0]
    assert "BKM_7" in dangling["message"]
    assert dangling["evidence"]["mode"] == "ref_field"


def test_figures_parsed_ghost():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"}],
        "markers": [],
    }})
    ghost = _by_rule(findings, "taw-fig-xref")[0]
    assert "无任何提及" in ghost["message"]
    assert ghost["evidence"]["ghost"] is True


def test_figures_parsed_gap_reported():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1", "caption_para": 2},
                    {"kind": "figure", "label": "图1-3", "caption_para": 5}],
    }})
    gap = _by_rule(findings, "taw-fig-gap")[0]
    assert gap["evidence"]["missing"] == [2]
    assert gap["evidence"]["chapter"] == 1
    assert gap["path"] == "object:图1-1"


def test_figures_parsed_no_gap_for_consecutive_numbers():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"},
                    {"kind": "figure", "label": "图1-2"}],
    }})
    assert _by_rule(findings, "taw-fig-gap") == []


def test_figures_parsed_gap_when_not_starting_at_one():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图5-2"}],
    }})
    assert _by_rule(findings, "taw-fig-gap")[0]["evidence"]["missing"] == [1]


def test_figures_parsed_kinds_are_grouped_separately():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图2-1"},
                    {"kind": "table", "label": "表2-1"}],
    }})
    assert _by_rule(findings, "taw-fig-gap") == []


def test_figures_parsed_unparseable_label_ignored_for_gaps():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "附录A"}],
    }})
    assert _by_rule(findings, "taw-fig-gap") == []


def test_figures_markers_derive_dangling():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"}],
        "markers": [{"label": "图1-9", "para_index": 3}],
    }})
    issues = [f["evidence"]["issue"] for f in _by_rule(findings, "taw-fig-xref")]
    assert "dangling_reference" in issues


def test_figures_markers_derive_ghost():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"},
                    {"kind": "figure", "label": "图1-2"}],
        "markers": [{"label": "图1-1", "para_index": 2}],
    }})
    ghosts = [f["evidence"]["label"] for f in _by_rule(findings, "taw-fig-xref")
              if f["evidence"].get("ghost")]
    assert ghosts == ["图1-2"]


def test_figures_equation_is_not_derived_ghost():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "equation", "label": "式(3-1)"}],
        "markers": [],
    }})
    assert _by_rule(findings, "taw-fig-xref") == []


def test_figures_explicit_dangling_overrides_derivation():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"}],
        "markers": [{"label": "图1-9", "para_index": 3}],
        "dangling": [],
    }})
    issues = [f["evidence"]["issue"] for f in _by_rule(findings, "taw-fig-xref")]
    assert "dangling_reference" not in issues


def test_figures_explicit_ghosts_are_used():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"}],
        "ghosts": [{"kind": "figure", "label": "图1-1"}],
    }})
    ghost = _by_rule(findings, "taw-fig-xref")[0]
    assert ghost["evidence"]["ghost"] is True


def test_figures_labels_text_matching_labels_are_clean():
    findings = core_doc.evaluate("figures", {
        "labels": ["图1-1", "图1-2"],
        "text": "图1-1 的结果见图1-2。",
    })
    assert _by_rule(findings, "taw-fig-xref") == []


def test_figures_labels_text_caption_is_not_a_mention():
    findings = core_doc.evaluate("figures", {
        "labels": ["图1-1", "图1-2"],
        "text": "图1-1 展示实验结果\n正文见图1-2。",
    })
    ghosts = [f["evidence"]["label"] for f in _by_rule(findings, "taw-fig-xref")]
    assert ghosts == ["图1-1"]


def test_figures_labels_text_body_mention_counts():
    findings = core_doc.evaluate("figures", {
        "labels": ["图1-2"],
        "text": "见图1-2。",
    })
    assert _by_rule(findings, "taw-fig-xref") == []


def test_figures_labels_text_dangling_mention():
    findings = core_doc.evaluate("figures", {
        "labels": ["图1-1"],
        "text": "见图1-9。",
    })
    dangling = [f for f in _by_rule(findings, "taw-fig-xref")
                if f["evidence"].get("issue") == "dangling_reference"]
    assert dangling[0]["evidence"]["label"] == "图1-9"


def test_figures_equation_caption_counts_as_mention():
    findings = core_doc.evaluate("figures", {
        "labels": ["式(3-1)"],
        "text": "式(3-1) y=x+1",
    })
    assert _by_rule(findings, "taw-fig-xref") == []


def test_figures_unparseable_label_literal_mention():
    findings = core_doc.evaluate("figures", {
        "labels": ["附图A"],
        "text": "见附图A。",
    })
    assert _by_rule(findings, "taw-fig-xref") == []


def test_figures_unparseable_label_without_mention_is_ghost():
    findings = core_doc.evaluate("figures", {
        "labels": ["附图A"],
        "text": "正文无关。",
    })
    assert _by_rule(findings, "taw-fig-xref")[0]["evidence"]["ghost"] is True


def test_figures_renumber_empty_edits_verified():
    findings = core_doc.evaluate("figures", {"parsed": {
        "objects": [{"kind": "figure", "label": "图1-1"}],
        "markers": [{"label": "图1-1", "para_index": 2}],
    }})
    evidence = _by_rule(findings, "taw-fig-renumber")[0]["evidence"]
    assert evidence["n_items"] == 1
    assert evidence["n_markers"] == 1
    assert evidence["verified"] is True


def test_figures_renumber_insert_edit():
    findings = core_doc.evaluate("figures", {
        "parsed": {"objects": [{"kind": "figure", "label": "图1-1"},
                               {"kind": "figure", "label": "图1-2"}]},
        "edits": [{"type": "insert", "new_item_id": "图9-9",
                   "target": "图1-1", "before": True}],
    })
    evidence = _by_rule(findings, "taw-fig-renumber")[0]["evidence"]
    assert evidence["new_order"] == ["图9-9", "图1-1", "图1-2"]
    assert evidence["verified"] is True


def test_figures_renumber_delete_edit():
    findings = core_doc.evaluate("figures", {
        "parsed": {"objects": [{"kind": "figure", "label": "图1-1"},
                               {"kind": "figure", "label": "图1-2"}]},
        "edits": [{"type": "delete", "target": "图1-1"}],
    })
    evidence = _by_rule(findings, "taw-fig-renumber")[0]["evidence"]
    assert evidence["new_order"] == ["图1-2"]


def test_figures_renumber_duplicate_insert_is_inconsistent():
    findings = core_doc.evaluate("figures", {
        "parsed": {"objects": [{"kind": "figure", "label": "图1-1"},
                               {"kind": "figure", "label": "图1-2"}]},
        "edits": [{"type": "insert", "new_item_id": "图1-1",
                   "target": "图1-2"}],
    })
    evidence = _by_rule(findings, "taw-fig-renumber")[0]["evidence"]
    assert evidence["consistent"] is False
    assert evidence["verified"] is False
    assert any(d["kind"] == "duplicate_item_id_after_edits"
               for d in evidence["diagnostics"])


def test_figures_unknown_edit_type_raises():
    with pytest.raises(ValueError, match="type 必须是 insert/delete"):
        core_doc.evaluate("figures", {
            "parsed": {"objects": []},
            "edits": [{"type": "swap", "target": "图1-1"}],
        })


def test_figures_ruleset_gates_xref_off():
    findings = core_doc.evaluate("figures", {
        "parsed": {"objects": [],
                   "markers": [{"label": "图9-9", "para_index": 1}]},
        "ruleset": _rules({"rule_id": "D", "check_type": "dangling_reference",
                           "activation": "gated"}),
    })
    assert _by_rule(findings, "taw-fig-xref") == []


def test_figures_ruleset_gates_gap_off():
    findings = core_doc.evaluate("figures", {
        "parsed": {"objects": [{"kind": "figure", "label": "图1-1"},
                               {"kind": "figure", "label": "图1-3"}]},
        "ruleset": _rules({"rule_id": "O", "check_type": "xref_order",
                           "activation": "gated"}),
    })
    assert _by_rule(findings, "taw-fig-gap") == []


def test_figures_bad_parsed_type_raises():
    with pytest.raises(ValueError, match="parsed 必须是 dict"):
        core_doc.evaluate("figures", {"parsed": []})


def test_figures_object_without_label_raises():
    with pytest.raises(ValueError, match="label 必须是非空 str"):
        core_doc.evaluate("figures", {"parsed": {"objects": [{"kind": "figure"}]}})


def test_figures_labels_without_text_raises():
    with pytest.raises(ValueError, match="labels 与 text 必须同时给"):
        core_doc.evaluate("figures", {"labels": ["图1-1"]})


def test_figures_edits_wrong_type_raises():
    with pytest.raises(ValueError, match="edits 必须是 list"):
        core_doc.evaluate("figures", {"parsed": {"objects": []},
                                      "edits": "insert"})


def test_figures_missing_parsed_raises():
    with pytest.raises(ValueError, match="需要 parsed 或 labels\\+text"):
        core_doc.evaluate("figures", {})


# ================================================================ 学校格式
def test_school_chapter_title_wrong_style():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "第1章 绪论", "Normal")],
        "ruleset": _rules(_style_rule()),
    })
    assert _paths(findings, "taw-school-style") == ["para:0/heading_level"]
    assert findings[0]["verdict"] == "error"


def test_school_chapter_title_heading_one_passes():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "第1章 绪论", "Heading 1")],
        "ruleset": _rules(_style_rule()),
    })
    assert findings == []


def test_school_caption_wrong_style():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "图3-1 系统架构", "Normal")],
        "ruleset": _rules(_style_rule()),
    })
    assert _paths(findings, "taw-school-style") == ["para:0/caption_style"]


def test_school_caption_style_passes():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "图3-1 系统架构", "Caption")],
        "ruleset": _rules(_style_rule()),
    })
    assert findings == []


def test_school_caption_with_punctuation_is_not_caption():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "图3-1 系统架构，展示整体结构", "Normal")],
        "ruleset": _rules(_style_rule()),
    })
    assert findings == []


def test_school_heading_with_sentence_end_is_flagged():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "正文内容。", "Heading 2")],
        "ruleset": _rules(_style_rule()),
    })
    assert _paths(findings, "taw-school-style") == ["para:0/body_style"]


def test_school_heading_without_sentence_end_passes():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "正文内容", "Heading 2")],
        "ruleset": _rules(_style_rule()),
    })
    assert findings == []


def test_school_blank_paragraph_is_skipped():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "   ", "Heading 2")],
        "ruleset": _rules(_style_rule()),
    })
    assert findings == []


def test_school_format_eq_within_tolerance_passes():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 30.4},
        "ruleset": _rules(_fmt_rule(tolerance=0.5)),
    })
    assert findings == []


def test_school_format_eq_outside_tolerance_fails():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 30.6},
        "ruleset": _rules(_fmt_rule(tolerance=0.5)),
    })
    assert len(_by_rule(findings, "taw-school-format")) == 1


def test_school_format_gte_passes_with_tolerance():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 24.6},
        "ruleset": _rules(_fmt_rule(op="gte", value=25.0, tolerance=0.5)),
    })
    assert findings == []


def test_school_format_gte_fails_below():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 20.0},
        "ruleset": _rules(_fmt_rule(op="gte", value=25.0)),
    })
    assert len(_by_rule(findings, "taw-school-format")) == 1


def test_school_format_lte_passes():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 20.0},
        "ruleset": _rules(_fmt_rule(op="lte", value=25.0)),
    })
    assert findings == []


def test_school_format_lte_fails_above():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 30.0},
        "ruleset": _rules(_fmt_rule(op="lte", value=25.0)),
    })
    assert len(_by_rule(findings, "taw-school-format")) == 1


def test_school_format_present_true_passes():
    findings = core_doc.evaluate("school", {
        "doc_format": {"header_present": True},
        "ruleset": _rules(_fmt_rule(param="header_present", op="present",
                                    value=True)),
    })
    assert findings == []


def test_school_format_present_false_fails():
    findings = core_doc.evaluate("school", {
        "doc_format": {"header_present": False},
        "ruleset": _rules(_fmt_rule(param="header_present", op="present",
                                    value=True)),
    })
    assert len(_by_rule(findings, "taw-school-format")) == 1


def test_school_format_missing_field_reports_uncheckable():
    findings = core_doc.evaluate("school", {
        "doc_format": {},
        "ruleset": _rules(_fmt_rule(param="margin_top_mm", value=25.0)),
    })
    record = _by_rule(findings, "taw-school-format")[0]
    assert "无法核对" in record["message"]
    assert record["evidence"]["got"] is None


def test_school_format_unknown_operator_reports():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 30.0},
        "ruleset": _rules(_fmt_rule(op="fuzzy")),
    })
    assert "未知判定算子" in _by_rule(findings, "taw-school-format")[0]["message"]


def test_school_format_string_equality():
    findings = core_doc.evaluate("school", {
        "doc_format": {"paper": "A4"},
        "ruleset": _rules(_fmt_rule(param="paper", op="eq", value="A4")),
    })
    assert findings == []


def test_school_format_dotted_path():
    findings = core_doc.evaluate("school", {
        "doc_format": {"meta": {"size": "A4"}},
        "ruleset": _rules(_fmt_rule(param="meta.size", op="eq", value="A4")),
    })
    assert findings == []


def test_school_format_inactive_rule_is_skipped():
    findings = core_doc.evaluate("school", {
        "doc_format": {"margin_left_mm": 40.0},
        "ruleset": _rules(_fmt_rule(activation="gated")),
    })
    assert findings == []


def test_school_style_and_format_run_together():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "第1章 绪论", "Normal")],
        "doc_format": {"margin_left_mm": 40.0},
        "ruleset": _rules(_style_rule(), _fmt_rule()),
    })
    rule_ids = {f["rule_id"] for f in findings}
    assert rule_ids == {"taw-school-style", "taw-school-format"}


def test_school_ruleset_without_style_rule_suppresses_style():
    findings = core_doc.evaluate("school", {
        "style_tree": [_p(0, "第1章 绪论", "Normal")],
        "doc_format": {"margin_left_mm": 40.0},
        "ruleset": _rules(_fmt_rule()),
    })
    assert {f["rule_id"] for f in findings} == {"taw-school-format"}


def test_school_missing_ruleset_raises():
    with pytest.raises(ValueError, match="缺少字段 ruleset"):
        core_doc.evaluate("school", {"style_tree": []})


def test_school_without_any_inputs_raises():
    with pytest.raises(ValueError, match="需要 style_tree 或 doc_format"):
        core_doc.evaluate("school", {"ruleset": _rules()})


def test_school_doc_format_wrong_type_raises():
    with pytest.raises(ValueError, match="doc_format 必须是 dict"):
        core_doc.evaluate("school", {"doc_format": "A4",
                                     "ruleset": _rules(_fmt_rule())})


def test_school_format_rule_missing_detect_raises():
    with pytest.raises(ValueError, match="缺少 detect"):
        core_doc.evaluate("school", {
            "doc_format": {},
            "ruleset": _rules({"rule_id": "F", "check_type": "format",
                               "activation": "active"}),
        })


def test_school_format_numeric_got_type_raises():
    with pytest.raises(ValueError, match="不是数值"):
        core_doc.evaluate("school", {
            "doc_format": {"margin_left_mm": "wide"},
            "ruleset": _rules(_fmt_rule(value=30)),
        })


def test_school_ruleset_wrong_type_raises():
    with pytest.raises(ValueError, match="ruleset 必须是 dict"):
        core_doc.evaluate("school", {"doc_format": {}, "ruleset": []})


# ================================================================ 确定性 RNG
def test_rng_seed_zero_first_value_is_golden():
    findings = core_doc.evaluate("rng", {"seed": 0, "n": 1})
    assert findings[0]["evidence"]["first"] == 16294208416658607535


def test_rng_seed_zero_first_three_values_are_golden():
    findings = core_doc.evaluate("rng", {"seed": 0, "n": 3})
    assert findings[0]["evidence"]["values"] == [
        16294208416658607535, 7960286522194355700, 487617019471545679]


def test_rng_same_seed_same_sequence():
    first = core_doc.evaluate("rng", {"seed": 42, "n": 5})
    second = core_doc.evaluate("rng", {"seed": 42, "n": 5})
    assert first[0]["evidence"]["values"] == second[0]["evidence"]["values"]


def test_rng_different_seed_differs():
    first = core_doc.evaluate("rng", {"seed": 1, "n": 1})
    second = core_doc.evaluate("rng", {"seed": 2, "n": 1})
    assert first[0]["evidence"]["first"] != second[0]["evidence"]["first"]


def test_rng_zero_count_is_empty():
    evidence = core_doc.evaluate("rng", {"seed": 0, "n": 0})[0]["evidence"]
    assert evidence["values"] == []
    assert evidence["first"] is None


def test_rng_max_values_stay_in_range():
    evidence = core_doc.evaluate("rng", {"seed": 0, "n": 20, "max": 10})[0]["evidence"]
    assert len(evidence["values"]) == 20
    assert all(0 <= value < 10 for value in evidence["values"])


def test_rng_max_one_yields_zeros():
    evidence = core_doc.evaluate("rng", {"seed": 7, "n": 4, "max": 1})[0]["evidence"]
    assert evidence["values"] == [0, 0, 0, 0]


def test_rng_max_zero_raises():
    with pytest.raises(ValueError, match="max 必须 >= 1"):
        core_doc.evaluate("rng", {"seed": 0, "n": 1, "max": 0})


def test_rng_negative_seed_is_masked():
    evidence = core_doc.evaluate("rng", {"seed": -1, "n": 1})[0]["evidence"]
    assert evidence["seed_masked"] == (1 << 64) - 1


def test_rng_bool_seed_raises():
    with pytest.raises(ValueError, match="seed 必须是 int"):
        core_doc.evaluate("rng", {"seed": True, "n": 1})


def test_rng_negative_n_raises():
    with pytest.raises(ValueError, match="n 必须 >= 0"):
        core_doc.evaluate("rng", {"seed": 0, "n": -1})


def test_rng_non_int_n_raises():
    with pytest.raises(ValueError, match="n 必须是 int"):
        core_doc.evaluate("rng", {"seed": 0, "n": "3"})


def test_rng_missing_seed_raises():
    with pytest.raises(ValueError, match="缺少字段 seed"):
        core_doc.evaluate("rng", {"n": 1})


def test_rng_missing_n_raises():
    with pytest.raises(ValueError, match="缺少字段 n"):
        core_doc.evaluate("rng", {"seed": 0})


def test_rng_values_length_equals_n():
    evidence = core_doc.evaluate("rng", {"seed": 3, "n": 17})[0]["evidence"]
    assert len(evidence["values"]) == 17


def test_rng_deterministic_flag_is_true():
    evidence = core_doc.evaluate("rng", {"seed": 5, "n": 8})[0]["evidence"]
    assert evidence["deterministic"] is True
    assert evidence["runs"] == 2


def test_rng_within_max_flag():
    evidence = core_doc.evaluate("rng", {"seed": 5, "n": 8, "max": 3})[0]["evidence"]
    assert evidence["within_max"] is True


def test_rng_total_equals_sum_of_values():
    evidence = core_doc.evaluate("rng", {"seed": 9, "n": 4})[0]["evidence"]
    assert evidence["total"] == sum(evidence["values"])


def test_rng_bool_max_raises():
    with pytest.raises(ValueError, match="max 必须是 int"):
        core_doc.evaluate("rng", {"seed": 0, "n": 1, "max": True})


def test_splitmix64_golden_sequence():
    generator = core_doc.SplitMix64(0)
    values = [generator.next_u64() for _ in range(3)]
    assert values == [16294208416658607535, 7960286522194355700,
                      487617019471545679]


def test_splitmix64_negative_seed_matches_masked_seed():
    assert core_doc.SplitMix64(-1).next_u64() == core_doc.SplitMix64(
        (1 << 64) - 1).next_u64()


def test_splitmix64_below_rejects_zero():
    with pytest.raises(ValueError, match="below"):
        core_doc.SplitMix64(0).below(0)


def test_splitmix64_chance_rejects_out_of_range():
    with pytest.raises(ValueError, match="概率"):
        core_doc.SplitMix64(0).chance(1.5)


def test_splitmix64_sample_rejects_oversize():
    with pytest.raises(ValueError, match="超过序列长度"):
        core_doc.SplitMix64(0).sample([1, 2], 3)


def test_splitmix64_shuffle_keeps_permutation():
    items = list(range(10))
    shuffled = core_doc.SplitMix64(3).shuffle(items)
    assert sorted(shuffled) == list(range(10))
    assert shuffled is items


def test_splitmix64_choice_stays_in_sequence():
    seq = ["a", "b", "c"]
    assert core_doc.SplitMix64(11).choice(seq) in seq