"""``thesis-audit`` 的编排 / 账本 / 口径快照测试（判定核的行为测试见两个核各自的测试文件）。

本文件钉的是**器官层契约**：mode 分发、rule_id 白名单、verdict 取值、basis 挂载、
账本确定性与阻断映射、口径快照双向一致、以及判定核的纯函数纪律（无 IO/时钟/环境）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.thesis_audit import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    api,
    core_doc,
    core_ref,
    spec,
)
from byteproof.core import ERROR, INFO, Basis, Report  # noqa: E402
from byteproof.core.basis import RuleMissing  # noqa: E402
from byteproof.core.registry import get  # noqa: E402

SLUG = "thesis-audit"
DATA_DIR = SRC / "byteproof" / "data"
BASIS = Basis.from_json(str(DATA_DIR / "thesis-audit.basis.json"))
SNAPSHOT = json.loads((DATA_DIR / "thesis-audit.thresholds.json").read_text(encoding="utf-8"))
LABEL = "1"


def card(card_id="ref-000001", label="1", title="A Study", year="2024", **kwargs):
    item = {
        "card_id": card_id,
        "entry_type": "J",
        "authors": [{"family": "Zhang", "given": "San"}],
        "title": title,
        "source": {"container": "Journal", "journal": "Journal", "volume": "1",
                   "issue": "2", "pages": "1-9", "year": year},
        "identifiers": {"doi": "10.1000/x", "isbn": None, "url": None},
        "evidence": {"src": "refs.txt", "ordinal": 1, "label": label, "raw": "raw"},
        "confidence": 1.0,
        "flags": [],
    }
    item.update(kwargs)
    return item


def recs(subject, basis=BASIS):
    return list(api.evaluate(subject, basis))


def body(subject, basis=BASIS):
    return [record for record in recs(subject, basis) if record.rule_id != spec.SUMMARY_RULE]


def summary(subject):
    return [record for record in recs(subject) if record.rule_id == spec.SUMMARY_RULE][0]


# ============================================================ 接线 / basis / 快照
def test_pack_registered():
    assert PACK.slug == SLUG
    assert PACK.version == ORGAN_VERSION == "1"
    assert get(SLUG) is PACK


def test_builtin_modules_sorted_unique():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(set(BUILTIN_MODULES)) == len(BUILTIN_MODULES)
    assert "thesis_audit" in BUILTIN_MODULES


def test_list_reaches_26(capsys):
    from byteproof import cli

    assert cli.main(["list"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) >= 26
    assert any(line.startswith("thesis-audit ") for line in lines)


def test_basis_covers_all_rules():
    assert set(spec.ALL_RULES) <= set(BASIS.rule_ids())
    assert len(BASIS) == len(spec.ALL_RULES) == 36


def test_basis_rule_texts_and_sources():
    for rule_id in spec.ALL_RULES:
        rule = BASIS.require(rule_id)
        assert rule.version, rule_id
        assert rule.text, rule_id
        assert "10-7-thesis-audit-workbench" in rule.source, rule_id


def test_modes_snapshot():
    assert tuple(SNAPSHOT["modes"]) == spec.MODES
    assert tuple(SNAPSHOT["ref_modes"]) == spec.REF_MODES
    assert tuple(SNAPSHOT["doc_modes"]) == spec.DOC_MODES


def test_rules_snapshot():
    assert tuple(SNAPSHOT["rules"]) == spec.ALL_RULES
    assert tuple(SNAPSHOT["ref_rules"]) == spec.REF_RULES
    assert tuple(SNAPSHOT["doc_rules"]) == spec.DOC_RULES


def test_severity_snapshot_covers_all_rules():
    assert SNAPSHOT["severity"] == spec.SEVERITY
    assert set(spec.SEVERITY) == set(spec.ALL_RULES)


def test_numeric_params_snapshot():
    assert SNAPSHOT["edit_threshold"] == spec.EDIT_THRESHOLD
    assert SNAPSHOT["author_threshold"] == spec.AUTHOR_THRESHOLD
    assert SNAPSHOT["aigc_bands"] == list(spec.AIGC_BANDS)


def test_core_mode_and_rule_ids_align_spec():
    assert set(core_ref.MODES) == set(spec.REF_MODES)
    assert set(core_doc.MODES) == set(spec.DOC_MODES)
    assert set(core_ref.RULE_IDS) == set(spec.REF_RULES)
    assert set(core_doc.RULE_IDS) == set(spec.DOC_RULES)


def test_core_verdicts_are_registered():
    for rule_id in set(core_ref.RULE_IDS) | set(core_doc.RULE_IDS):
        assert spec.SEVERITY[rule_id] in spec.VERDICTS


def test_missing_basis_rule_is_contract_error():
    with pytest.raises(RuleMissing):
        body({"mode": "dedup", "cards": [card(), card("ref-000002")]}, basis=Basis.empty())


# ============================================================ 分发 / 账本契约
def test_refcheck_runs_through_api():
    records = body({"mode": "refcheck", "cards": [card()]})
    for record in records:
        assert record.rule_id.startswith("taw-")
        assert record.basis is not None


def test_invalid_card_reports_ref_card():
    bad = card()
    del bad["evidence"]
    records = body({"mode": "refcheck", "cards": [bad]})
    assert "taw-ref-card" in [record.rule_id for record in records]


def test_cite_resolves_defined_marker():
    assert body({"mode": "cite", "cards": [card()], "text": "正文 [1]。"}) == []


def test_cite_flags_dangling_marker():
    records = body({"mode": "cite", "cards": [card()], "text": "正文 [9]。"})
    markers = [record for record in records if record.rule_id == "taw-cite-marker"]
    assert markers and markers[0].verdict == ERROR


def test_dedup_same_card_twice():
    records = body({"mode": "dedup", "cards": [card(), card("ref-000002")]})
    assert "taw-dedup-pair" in [record.rule_id for record in records]


def test_fake_health_info_only():
    records = body({"mode": "fake", "cards": [card()]})
    assert records and all(record.verdict == INFO for record in records)


def test_library_unchanged_is_info():
    card_a = card()
    manifest = core_ref.build_manifest([card_a], doc_name="d")
    records = body({"mode": "library", "old_manifest": manifest, "new_cards": [card_a]})
    assert [record.verdict for record in records] == [INFO]


def test_library_mutation_is_error():
    card_a = card()
    manifest = core_ref.build_manifest([card_a], doc_name="d")
    records = body({"mode": "library", "old_manifest": manifest,
                    "new_cards": [dict(card_a, title="Changed")]})
    assert records and all(record.verdict == ERROR for record in records)


def test_review_single_entry_cluster_info():
    records = body({"mode": "review", "entries": [
        {"id": "a", "title": "thesis audit", "abstract": "synthetic", "year": 2024}]})
    assert records and all(record.rule_id.startswith("taw-review") for record in records)


def test_aigc_dist_info():
    records = body({"mode": "aigc", "paragraphs": ["一个句子。", "另一个句子。"]})
    assert "taw-aigc-dist" in [record.rule_id for record in records]


def test_structure_requires_style_tree():
    with pytest.raises(ValueError):
        body({"mode": "structure", "style_tree": None})


def test_terms_requires_canonical():
    with pytest.raises(ValueError):
        body({"mode": "terms", "style_tree": {"paragraphs": []},
              "terms": [{"term": "深度学习"}]})


def test_figures_labels_produce_xref():
    records = body({"mode": "figures", "labels": ["图1", "图3"], "text": "见图2。"})
    assert "taw-fig-xref" in [record.rule_id for record in records]


def test_school_empty_ruleset_no_findings():
    assert body({"mode": "school", "doc_format": {}, "ruleset": {"rules": []}}) == []


def test_rng_determinism_info():
    records = body({"mode": "rng", "seed": 7, "n": 3})
    assert [record.rule_id for record in records] == ["taw-rng-determinism"]
    assert records[0].verdict == INFO


def test_unknown_mode_valueerror():
    with pytest.raises(ValueError):
        recs({"mode": "nope"})


def test_non_mapping_subject_valueerror():
    with pytest.raises(ValueError):
        list(api.evaluate(["not", "a", "dict"], BASIS))


def test_unknown_rule_id_rejected(monkeypatch):
    monkeypatch.setattr(core_ref, "evaluate",
                        lambda mode, subject: [{"rule_id": "taw-nope", "verdict": "info",
                                                "message": "m", "path": "p", "evidence": {}}])
    with pytest.raises(ValueError):
        body({"mode": "fake", "cards": [card()]})


def test_unknown_verdict_rejected(monkeypatch):
    monkeypatch.setattr(core_ref, "evaluate",
                        lambda mode, subject: [{"rule_id": "taw-fake-health", "verdict": "fatal",
                                                "message": "m", "path": "p", "evidence": {}}])
    with pytest.raises(ValueError):
        body({"mode": "fake", "cards": [card()]})


def test_summary_counts_match_records():
    subject = {"mode": "figures", "labels": ["图1", "图3"], "text": "见图2。"}
    record = summary(subject)
    # total 计的是汇总行以外的账本行
    assert record.evidence["total"] == len(recs(subject)) - 1
    assert sum(record.evidence["by_verdict"].values()) == record.evidence["total"]


def test_record_ids_unique():
    subject = {"mode": "figures", "labels": ["图1", "图3"], "text": "见图2 与图4。"}
    ids = [record.id for record in recs(subject)]
    assert len(ids) == len(set(ids))


def test_report_deterministic():
    subject = {"mode": "figures", "labels": ["图1", "图3"], "text": "见图2。"}
    first = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                   subject="s", records=recs(subject))
    second = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                    subject="s", records=recs(subject))
    assert json.dumps(first.as_dict(), ensure_ascii=False) == json.dumps(
        second.as_dict(), ensure_ascii=False)


def test_blocking_exit_code():
    report = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                    subject="s", records=recs({"mode": "dedup",
                                                "cards": [card(), card("ref-000002")]}))
    assert report.exit_code() == 1


def test_clean_exit_code():
    report = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION,
                    subject="s", records=recs({"mode": "school", "doc_format": {},
                                                "ruleset": {"rules": []}}))
    assert report.exit_code() == 0


def test_cores_have_no_io_imports():
    allowed = {"__future__", "copy", "hashlib", "itertools", "math", "re", "typing",
               "dataclasses", "collections", "fractions", "decimal"}
    for name in ("core_ref.py", "core_doc.py"):
        tree = ast.parse((SRC / "byteproof" / "auditors" / "thesis_audit" / name)
                         .read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= allowed, (name, imported - allowed)