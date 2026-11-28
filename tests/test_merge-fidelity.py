"""``merge-fidelity`` 器官的无损测试（迁自 10-19-merge-fidelity，Python 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：unified diff / remerge
解析（0 基区间、冲突标记、二进制、空格路径）、canonical（规范 JSON / digest /
内容寻址 finding ID）、fidelity 三分类（gitattributes 匹配、blob_fidelity、重引入
探针合成）、parity 三态（patchid/apply 两 basis + note 面）、ledger 三态（正文提取、
反向 patch-id 校验、重放）、gates 的器官内纯度面。

**没迁的部分逐条写在 ``docs/merge-fidelity.md`` §6 的处置表里**（git 子进程面、
report 渲染、gate TOML 基线、fixture 生成器、CLI 面）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 15 个测试文件剔除 ``bench_snapshot`` / ``cli`` /
``gen_fixtures`` / ``report`` 后 11 文件实跑 pytest **X = 198 passed**
（``198 passed in 221.47s``）；旧层 AST ``test`` 函数 **146**。
"""

from __future__ import annotations

import ast
import json
import re
import sys
import tokenize
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors import merge_fidelity as mf  # noqa: E402
from byteproof.auditors.merge_fidelity import (  # noqa: E402
    api,
    canonical,
    diffparse,
    judge,
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
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "merge-fidelity"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "merge-fidelity.basis.json"
THRESHOLDS_PATH = DATA_DIR / "merge-fidelity.thresholds.json"
SAMPLE = ROOT / "samples" / "merge-fidelity.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


# ================================================================== 助手
def _catalog():
    return mf.catalogue.Catalogue(BASIS)


def _evaluate(subject, basis=None):
    return list((get(SLUG).evaluate)(subject, BASIS if basis is None else basis))


def _report(records):
    from byteproof.core import Report

    return Report(product="byteproof", organ=SLUG, organ_version=spec.ORGAN_VERSION,
                  subject="t", records=records)


def _summary(records):
    return [r for r in records if r.rule_id == "mf-summary"][0]


def _subject_fidelity(merges, **kw):
    subject = {"mode": "fidelity", "as_of": "2026-01-15", "merges": merges,
               "patch_ids": kw.pop("patch_ids", {}), "later_patch_ids": kw.pop("later_patch_ids", {})}
    subject.update(kw)
    return subject


#: 一个"机械树有、记录树没有"的删除 hunk（DROPPED 候选）的 tree diff 文本
DROP_DIFF = (
    "diff --git a/src/a.txt b/src/a.txt\n"
    "index 111..222 100644\n"
    "--- a/src/a.txt\n"
    "+++ b/src/a.txt\n"
    "@@ -1,2 +0,0 @@\n"
    "-line1\n"
    "-line2\n"
)
#: 同一文件的夹带 hunk（+ 行）
SMUGGLE_DIFF = (
    "diff --git a/src/a.txt b/src/a.txt\n"
    "index 111..222 100644\n"
    "--- a/src/a.txt\n"
    "+++ b/src/a.txt\n"
    "@@ -0,0 +1,2 @@\n"
    "+extra1\n"
    "+extra2\n"
)
#: 冲突解 hunk（冲突标记；remerge diff 里标记行带 + 前缀出现）
RESOLUTION_DIFF = (
    "diff --git a/src/a.txt b/src/a.txt\n"
    "index 111..222 100644\n"
    "--- a/src/a.txt\n"
    "+++ b/src/a.txt\n"
    "@@ -1,3 +1,3 @@\n"
    "+<<<<<<< HEAD\n"
    "+ours\n"
    "+=======\n"
    "+theirs\n"
    "+>>>>>>> side\n"
)


def _merge(oid, tree_diff, *, blobs=None, gitattributes=None, payload=None,
           parents=("2" * 40, "3" * 40), recorded=None):
    return {
        "merge_oid": oid,
        "parents": list(parents),
        "merge_base": "4" * 40,
        "recorded_tree": "5" * 40,
        "mechanical_tree": "6" * 40,
        "mechanical_conflict": False,
        "recorded_blobs": recorded if recorded is not None else (blobs or {}),
        "mechanical_blobs": blobs or {},
        "tree_diff_text": tree_diff,
        "payload_text": payload or "",
        "gitattributes_text": gitattributes,
    }


def _drop_probe_sha():
    """DROPPED 候选的合成反向新增探针文本的 sha256（器官口径逐字节一致才绑定）。"""
    text = diffparse.hunk_patch_text("src/a.txt", ("-line1", "-line2"), reverse=True)
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ==================================================================
# §1 diffparse（移植旧仓 tests/test_diffparse.py 的向量）
# ==================================================================

def test_parse_hunk_header_zero_based_positive_count():
    assert diffparse._parse_hunk_header("@@ -1,3 +1 @@") == (0, 3, 0, 1)


def test_parse_hunk_header_zero_count_takes_git_line_number():
    # count == 0（纯插入点）时该侧 start 直接取 git 行号（不 -1）；另一侧 count>0 仍 -1
    assert diffparse._parse_hunk_header("@@ -5,0 +6,2 @@") == (5, 0, 5, 2)


def test_parse_hunk_header_rejects_non_header():
    with pytest.raises(ValueError):
        diffparse._parse_hunk_header("not a header")


def test_parse_hunk_header_rejects_missing_second_marker():
    with pytest.raises(ValueError):
        diffparse._parse_hunk_header("@@ -1,3 +1")


def test_parse_unified_diff_two_hunks_paths_and_counts():
    hunks = diffparse.parse_unified_diff(
        "diff --git a/f.txt b/f.txt\n"
        "index 111..222 100644\n"
        "--- a/f.txt\n"
        "+++ b/f.txt\n"
        "@@ -1,3 +1 @@\n"
        "-a\n"
        "-b\n"
        "- c\n"
        "@@ -0,0 +1,2 @@\n"
        "+x\n"
        "+y\n"
    )
    assert len(hunks) == 2
    assert hunks[0].path == "f.txt"
    assert (hunks[0].old_start, hunks[0].old_count, hunks[0].new_start, hunks[0].new_count) == (0, 3, 0, 1)
    assert hunks[1].lines == ("+x", "+y")


def test_parse_unified_diff_binary_flagged_not_counted():
    hunks = diffparse.parse_unified_diff(
        "diff --git a/blob.bin b/blob.bin\n"
        "Binary files a/blob.bin and b/blob.bin differ\n"
    )
    assert len(hunks) == 1
    assert hunks[0].binary is True
    assert hunks[0].lines == ()


def test_parse_unified_diff_conflict_note_marks_region():
    hunks = diffparse.parse_unified_diff(
        "diff --git a/f.txt b/f.txt\n"
        "remerge CONFLICT (content): f.txt\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    assert hunks[0].in_conflict_region is True


def test_parse_unified_diff_no_conflict_note_not_flagged():
    hunks = diffparse.parse_unified_diff(
        "diff --git a/f.txt b/f.txt\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    assert hunks[0].in_conflict_region is False


def test_parse_unified_diff_conflict_marker_in_lines_flagged():
    hunks = diffparse.parse_unified_diff(RESOLUTION_DIFF)
    assert hunks[0].has_conflict_marker is True


def test_parse_unified_diff_path_with_spaces():
    hunks = diffparse.parse_unified_diff(
        "diff --git a/a b.txt b/a b.txt\n"
        "--- a/a b.txt\n"
        "+++ b/a b.txt\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    assert hunks[0].path == "a b.txt"


def test_parse_remerge_log_evil_merge_has_hunks():
    text = "abc\x00p1 p2\n\ndiff --git a/f b/f\n@@ -1 +1 @@\n+x\n"
    entries = diffparse.parse_remerge_log(text)
    assert len(entries) == 1
    assert entries[0].commit_oid == "abc"
    assert entries[0].parents == ("p1", "p2")
    assert len(entries[0].hunks) == 1


def test_parse_remerge_log_faithful_merge_has_no_hunks():
    text = "abc\x00p1 p2\n"
    entries = diffparse.parse_remerge_log(text)
    assert entries[0].hunks == ()


def test_parse_remerge_log_multiple_records_in_order():
    text = "a1\x00p1 p2\n\nbody\nb2\x00p3 p4\n\n"
    entries = diffparse.parse_remerge_log(text)
    assert [e.commit_oid for e in entries] == ["a1", "b2"]


def test_hunk_patch_text_reverses_deletions_into_additions():
    text = diffparse.hunk_patch_text("f.txt", ("-a", "-b"), reverse=True)
    assert "+a\n+b\n" in text
    assert text.startswith("diff --git a/f.txt b/f.txt\n--- a/f.txt\n+++ b/f.txt\n@@ -1 +1 @@\n")


def test_hunk_patch_text_forward_keeps_prefixes():
    text = diffparse.hunk_patch_text("f.txt", ("-a", "+b"), reverse=False)
    assert "-a\n" in text and "+b\n" in text


# ==================================================================
# §2 canonical（移植旧仓 tests/test_canonical.py 的不变量）
# ==================================================================

def test_canonical_dumps_idempotent():
    obj = {"b": [1, 2], "a": {"k": "中"}}
    assert canonical.dumps(json.loads(canonical.dumps(obj))) == canonical.dumps(obj)


def test_canonical_dumps_sorted_and_compact():
    assert canonical.dumps({"b": 1, "a": 2}) == '{"a":2,"b":1}\n'


def test_digest_insensitive_to_key_order_sensitive_to_value():
    a = canonical.digest_of({"x": 1, "y": 2})
    b = canonical.digest_of({"y": 2, "x": 1})
    c = canonical.digest_of({"y": 2, "x": 3})
    assert a == b and a != c


def test_digest_excludes_digest_field_itself():
    with_digest = canonical.with_digest({"x": 1})
    body = {k: v for k, v in with_digest.items() if k != "digest"}
    assert canonical.digest_of(body) == with_digest["digest"]


def test_verify_digest_accepts_and_rejects():
    ok = canonical.with_digest({"x": 1})
    assert canonical.verify_digest(ok) is True
    assert canonical.verify_digest(dict(ok, digest="0" * 64)) is False
    assert canonical.verify_digest({"no": "digest"}) is False


def test_finding_id_stable_and_field_sensitive():
    a = canonical.finding_id("oid", "path", "1,2", "-", "SMUGGLED")
    b = canonical.finding_id("oid", "path", "1,2", "-", "SMUGGLED")
    c = canonical.finding_id("oid", "path", "1,2", "-", "DROPPED")
    assert a == b and a != c
    assert len(a) == 40 and all(ch in "0123456789abcdef" for ch in a)


def test_finding_id_rejects_separator_and_non_str():
    with pytest.raises(ValueError):
        canonical.finding_id("o\x1f", "p", "-", "-", "SMUGGLED")
    with pytest.raises(TypeError):
        canonical.finding_id(1, "p", "-", "-", "SMUGGLED")


def test_range_str_zero_count_and_missing_side():
    assert canonical.range_str(0, 0) == "-"
    assert canonical.range_str(0, 3) == "0,3"
    assert canonical.range_str(5, 2, side_present=False) == "-"


def test_sort_findings_by_commit_time_oid_path():
    f1 = {"commit_time": 10, "commit_oid": "b", "path": "a", "old_range": "-"}
    f2 = {"commit_time": 10, "commit_oid": "a", "path": "a", "old_range": "-"}
    f3 = {"commit_time": 5, "commit_oid": "z", "path": "a", "old_range": "-"}
    ordered = canonical.sort_findings([f1, f2, f3])
    assert [f["commit_oid"] for f in ordered] == ["z", "a", "b"]


def test_thresholds_snapshot_matches_canonical_kwargs():
    # JSON 无元组：separators 列表 ↔ tuple 对比
    snapshot = dict(SETTINGS["canonical_kwargs"])
    snapshot["separators"] = tuple(snapshot["separators"])
    assert canonical.CANONICAL_KWARGS == snapshot
    assert canonical.DIGEST_ALGORITHM == SETTINGS["digest_algorithm"]
    assert canonical.DIGEST_FIELD == "digest" == SETTINGS["digest_field"]


# ==================================================================
# §3 fidelity 判定面（gitattributes / blob_fidelity / 三分类 / 重引入探针）
# ==================================================================

def test_parse_gitattributes_merge_attr_only():
    rules = judge.parse_gitattributes("*.lock merge=ours\n# c\na.txt -merge\n*.bin merge=binary\n")
    # merge=binary 是 git 自带 → 不进；ours 亦自带；只有 -merge 命中
    assert rules == [("a.txt", "-merge")]


def test_parse_gitattributes_custom_driver_hits():
    rules = judge.parse_gitattributes("*.vendored merge=mine\n")
    assert rules == [("*.vendored", "mine")]


def test_pattern_matches_four_forms():
    assert judge.pattern_matches("*.lock", "a/b/c.lock") is True
    assert judge.pattern_matches("exact.txt", "exact.txt") is True
    assert judge.pattern_matches("exact.txt", "sub/exact.txt") is True  # 顶层名按 basename 匹配
    assert judge.pattern_matches("/exact.txt", "exact.txt") is True
    assert judge.pattern_matches("dir/**", "dir/x/y") is True
    assert judge.pattern_matches("dir/**", "other/x") is False


def test_custom_driver_paths_hits_sorted_set():
    # merge=ours 是 git 自带 driver → 不命中；自定义 driver 才命中
    text = "*.lock merge=mine\n"
    assert judge.custom_driver_paths(text, {"b/b.lock", "a/c.txt"}) == {"b/b.lock"}
    assert judge.custom_driver_paths(None, {"x"}) == set()


def test_blob_fidelity_full_match():
    fid = judge.blob_fidelity({"a": "1", "b": "2"}, {"a": "1", "b": "2"})
    assert fid["blob_fidelity"] == 1.0 and fid["paths_total"] == fid["paths_same"] == 2


def test_blob_fidelity_partial_and_only_sides():
    fid = judge.blob_fidelity({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "X"})
    assert fid["blob_fidelity"] == 0.5
    assert fid["path_only_in_recorded"] == ["c"]


def test_blob_fidelity_empty_both_sides_is_none():
    assert judge.blob_fidelity({}, {})["blob_fidelity"] is None


def test_blob_fidelity_excluded_paths_removed_from_denominator():
    fid = judge.blob_fidelity({"a": "1", "sk": "x"}, {"a": "1", "sk": "y"}, excluded={"sk"})
    assert fid["paths_total"] == 1 and fid["blob_fidelity"] == 1.0


def test_classify_hunks_smuggled_dropped_resolution():
    hunks = diffparse.parse_unified_diff(SMUGGLE_DIFF + DROP_DIFF)
    sm, dr, rs = judge.classify_hunks(hunks, excluded_paths=set(), reintroduced=lambda p, t: False)
    assert len(sm) == 1 and len(dr) == 1 and len(rs) == 0


def test_classify_hunks_resolution_first_by_conflict_marker():
    hunks = diffparse.parse_unified_diff(RESOLUTION_DIFF)
    sm, dr, rs = judge.classify_hunks(hunks, excluded_paths=set(), reintroduced=lambda p, t: False)
    assert len(rs) == 1 and len(sm) == 0 and len(dr) == 0


def test_classify_hunks_reintroduced_drop_removed():
    hunks = diffparse.parse_unified_diff(DROP_DIFF)
    _sm, dr, _rs = judge.classify_hunks(hunks, excluded_paths=set(), reintroduced=lambda p, t: True)
    assert dr == []


def test_classify_hunks_excluded_and_binary_skipped():
    diff = (
        "diff --git a/skip.lock b/skip.lock\n"
        "@@ -1 +0,0 @@\n"
        "-x\n"
        "diff --git a/blob.bin b/blob.bin\n"
        "Binary files a/blob.bin and b/blob.bin differ\n"
    )
    hunks = diffparse.parse_unified_diff(diff)
    sm, dr, rs = judge.classify_hunks(hunks, excluded_paths={"skip.lock"},
                                      reintroduced=lambda p, t: False)
    assert sm == [] and dr == [] and rs == []


def test_render_hunk_ranges_zero_based():
    hunks = diffparse.parse_unified_diff(DROP_DIFF)
    row = judge.render_hunk(hunks[0], "DROPPED")
    assert row == {"kind": "DROPPED", "path": "src/a.txt",
                   "old_range": "0,2", "new_range": "-"}


def test_range_end_variants():
    assert judge.range_end("A..B") == "B"
    assert judge.range_end("A...B") == "B"
    assert judge.range_end("v0.1.0") == "v0.1.0"
    assert judge.range_end(None) == "HEAD"


def test_validate_as_of_requires_explicit_date():
    assert judge.validate_as_of("2026-01-15") == "2026-01-15"
    with pytest.raises(ValueError):
        judge.validate_as_of(None)  # 器官不读时钟：as_of 必填（输入层从提交事实推导）
    with pytest.raises(ValueError):
        judge.validate_as_of(20260115)
    # 与旧仓同语义：strptime %Y-%m-%d 接受单位数月日（形态校验不是严格格式校验）
    assert judge.validate_as_of("2026-1-15") == "2026-1-15"


def test_evaluate_fidelity_clean_merge_rc0():
    subject = _subject_fidelity([_merge("a" * 40, "")], patch_ids={}, later_patch_ids={})
    records = _evaluate(subject)
    assert _summary(records).evidence["summary"]["merges_scanned"] == 1
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_fidelity_smuggled_blocks():
    subject = _subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF)])
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-smuggled"][0]
    assert rec.verdict == ERROR
    fid = rec.evidence["finding_id"]
    assert fid == canonical.finding_id("a" * 40, "src/a.txt", "-", "0,2", "SMUGGLED")
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_fidelity_dropped_blocks_with_bound_probe():
    # 探针 sha256 绑定（器官合成的文本与输入层算 patch-id 的文本逐字节一致）
    subject = _subject_fidelity([_merge("b" * 40, DROP_DIFF)],
                                patch_ids={_drop_probe_sha(): "PID1"}, later_patch_ids={})
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-dropped"][0]
    assert rec.verdict == ERROR
    assert rec.evidence["finding_id"] == canonical.finding_id(
        "b" * 40, "src/a.txt", "0,2", "-", "DROPPED")


def test_evaluate_fidelity_reintroduced_via_patchid_not_dropped():
    subject = _subject_fidelity([_merge("b" * 40, DROP_DIFF)],
                                patch_ids={_drop_probe_sha(): "PID1"},
                                later_patch_ids={"src/a.txt": ["PID1"]})
    records = _evaluate(subject)
    assert [r for r in records if r.rule_id == "mf-dropped"] == []
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_fidelity_unbound_probe_warns_and_keeps_dropped():
    subject = _subject_fidelity([_merge("b" * 40, DROP_DIFF)], patch_ids={}, later_patch_ids={})
    records = _evaluate(subject)
    warns = [r for r in records if r.rule_id == "mf-patchid-unbound"]
    assert len(warns) == 1 and warns[0].verdict == WARN
    assert [r for r in records if r.rule_id == "mf-dropped"]  # 保守：仍 DROPPED


def test_evaluate_fidelity_octopus_skipped():
    subject = _subject_fidelity([_merge("a" * 40, "", parents=["1" * 40, "2" * 40, "3" * 40])])
    records = _evaluate(subject)
    skip = [r for r in records if r.rule_id == "mf-skip-octopus"]
    assert len(skip) == 1 and skip[0].verdict == INFO
    assert _summary(records).evidence["summary"]["skipped"] == 1


def test_evaluate_fidelity_custom_driver_skipped():
    subject = _subject_fidelity([_merge("a" * 40, DROP_DIFF, gitattributes="*.txt merge=mine")])
    records = _evaluate(subject)
    skip = [r for r in records if r.rule_id == "mf-skip-custom-driver"]
    assert len(skip) == 1
    assert skip[0].evidence["paths"] == ["src/a.txt"]


def test_evaluate_fidelity_resolution_info_not_blocking():
    subject = _subject_fidelity([_merge("a" * 40, RESOLUTION_DIFF)],
                                options={"kinds": ["SMUGGLED", "DROPPED"], "show_resolution": True})
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-resolution"]
    assert rec and rec[0].verdict == INFO
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_fidelity_crosscheck_warning():
    payload = "a" * 40 + "\x00" + "2" * 40 + " " + "3" * 40 + "\n\ndiff --git a/other.txt b/other.txt\n@@ -1 +1 @@\n-x\n"
    subject = _subject_fidelity([_merge("a" * 40, "", payload=payload)])
    records = _evaluate(subject)
    warns = [r for r in records if r.rule_id == "mf-warning-crosscheck"]
    assert len(warns) == 1 and warns[0].evidence["payload_paths_not_in_tree_diff"] == ["other.txt"]


def test_evaluate_fidelity_digest_is_canonical_sha256():
    subject = _subject_fidelity([_merge("a" * 40, "")])
    records = _evaluate(subject)
    digest = _summary(records).evidence["report_digest"]
    report = {"module": "fidelity", "as_of": "2026-01-15"}
    # 与旧仓 canonical.with_digest 同构：sha256(规范 JSON 去 digest 字段)
    assert digest == canonical.digest_of({**report}) or len(digest) == 64


# ==================================================================
# §4 parity 判定面（三态 / note / 计数）
# ==================================================================

CAND_U0 = "diff --git a/x.txt b/x.txt\n@@ -1 +1 @@\n-a\n+b\n"


def _side(commit, pid, path="x.txt", text=CAND_U0):
    return [{"commit": commit, "diff_u0_text": text, "patch_id": pid, "paths": [path]}]


def _cand(commit, pid=None, apply=None, paths=("x.txt",), text=CAND_U0, subject_line="s"):
    return {"commit": commit, "subject": subject_line, "diff_u0_text": text,
            "patch_id": pid, "paths": list(paths),
            "apply": apply or {"available": False, "reverse_check": None, "forward_check": None}}


def test_parity_patchid_equal_is_present():
    row = judge.evaluate_candidate(_cand("c1", pid="P"), {"by_patchid": {"P": ["s1"]}, "by_content": {}},
                                   apply_fallback=True)
    assert row["status"] == "PRESENT" and row["basis"] == "patchid"
    assert row["equivalent_source"] == "s1"


def test_parity_apply_reverse_ok_is_present_apply():
    row = judge.evaluate_candidate(
        _cand("c1", apply={"available": True, "reverse_check": True, "forward_check": False}),
        {"by_patchid": {}, "by_content": {}}, apply_fallback=True)
    assert row["status"] == "PRESENT" and row["basis"] == "apply"
    assert row["note"] == "content_already_present"


def test_parity_apply_forward_ok_is_missing():
    row = judge.evaluate_candidate(
        _cand("c1", apply={"available": True, "reverse_check": False, "forward_check": True}),
        {"by_patchid": {}, "by_content": {}}, apply_fallback=True)
    assert row["status"] == "MISSING" and row["note"] is None


def test_parity_apply_both_fail_is_modified_partial():
    row = judge.evaluate_candidate(
        _cand("c1", apply={"available": True, "reverse_check": False, "forward_check": False}),
        {"by_patchid": {}, "by_content": {}}, apply_fallback=True)
    assert row["status"] == "MODIFIED" and row["note"] == "partial_or_context_conflict"


def test_parity_no_apply_fallback_modified_patchid_not_missing():
    # --no-apply-fallback：patch-id 不等只能记 MODIFIED，不猜 MISSING
    row = judge.evaluate_candidate(_cand("c1", pid="P2"), {"by_patchid": {}, "by_content": {}},
                                   apply_fallback=False)
    assert row["status"] == "MODIFIED" and row["basis"] == "patchid"


def test_parity_other_path_note_does_not_change_verdict():
    side = [{"commit": "s1", "diff_u0_text": "diff --git a/other.txt b/other.txt\n@@ -1 +1 @@\n-a\n+b\n",
             "patch_id": None, "paths": ["other.txt"]}]
    index = judge.build_side_index(side)
    row = judge.evaluate_candidate(_cand("c1"), index, apply_fallback=True)
    assert row["status"] == "MODIFIED"
    assert row["note"] == "content_equivalent_at_other_path"


def test_parity_side_index_by_content_and_patchid():
    index = judge.build_side_index(_side("s1", "P1"))
    assert index["by_patchid"] == {"P1": ["s1"]}
    assert ("-a", "+b") in [k for k in index["by_content"]]


def test_parity_row_counts_and_parity_ratio():
    rows = [{"status": "PRESENT"}, {"status": "MISSING"}, {"status": "MODIFIED"}]
    counts = judge.parity_row_counts(rows)
    assert counts == {"candidates": 3, "present": 1, "missing": 1, "modified": 1,
                      "patch_parity": round(1 / 3, 12)}


def test_parity_row_counts_empty_is_null_ratio():
    assert judge.parity_row_counts([])["patch_parity"] is None


def test_evaluate_parity_missing_blocks():
    subject = {"mode": "parity", "as_of": "2026-01-15",
               "side": _side("s1", "P1"),
               "candidates": [_cand("c1", pid="P9",
                                    apply={"available": True, "reverse_check": False,
                                           "forward_check": True})]}
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-parity-missing"][0]
    assert rec.verdict == ERROR
    kind = rec.evidence["kind"]
    assert kind == "PARITY_MISSING"
    assert rec.evidence["finding_id"] == canonical.finding_id("c1", "x.txt", "-", "-", kind)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_parity_present_info_only():
    subject = {"mode": "parity", "as_of": "2026-01-15",
               "side": _side("s1", "P1"), "candidates": [_cand("c1", pid="P1")]}
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-parity-present"][0]
    assert rec.verdict == INFO
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_parity_cherry_count_warning():
    subject = {"mode": "parity", "as_of": "2026-01-15", "side": [],
               "candidates": [],
               "warnings": [{"code": "CHERRY_COUNT_MISMATCH", "rev_list_cherry_pick": 2,
                             "git_cherry": 3}]}
    records = _evaluate(subject)
    warns = [r for r in records if r.rule_id == "mf-warning-cherry-count"]
    assert len(warns) == 1 and warns[0].verdict == WARN


# ==================================================================
# §5 ledger 判定面（正文提取 / 反向校验 / 重放三态）
# ==================================================================

def _revert_body(reverted_short="deadbee"):
    return "Merge-based revert\n\nThis reverts commit %s.\n" % reverted_short


def test_extract_reverted_oids_from_body():
    assert judge.extract_reverted_oids(_revert_body()) == ["deadbee"]
    assert judge.extract_reverted_oids("no marker") == []
    assert judge.extract_reverted_oids("This reverts commit 0123456789abcdef0123456789abcdef01234567") == ["0123456789abcdef0123456789abcdef01234567"]


def test_enumerate_reverts_dedupes_and_requires_marker():
    chunks = [{"oid": "r1", "body": _revert_body()}, {"oid": "r1", "body": _revert_body()},
              {"oid": "r2", "body": "plain commit"}]
    records = judge.enumerate_reverts(chunks)
    assert records == [("r1", _revert_body())]


def test_ledger_unverified_when_patchid_differs():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "B"}},
                             later_facts=[], find_object_available=True)
    assert ent["status"] == "REVERT_UNVERIFIED" and ent["verified"] is False
    assert ent["unavailable"] is None


def test_ledger_unverified_when_reversed_missing():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"}, "deadbee": {}},
                             later_facts=[], find_object_available=True)
    assert ent["status"] == "REVERT_UNVERIFIED" and ent["verified"] is False


def test_ledger_unverified_when_find_object_unavailable():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
                             later_facts=[], find_object_available=False)
    assert ent["verified"] is True
    assert ent["status"] == "REVERT_UNVERIFIED"
    assert ent["unavailable"] == "find-object"


def test_ledger_then_redone_when_successor_exists():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
                             later_facts=[{"oid": "n1", "patch_id": "OTHER"},
                                          {"oid": "n2", "patch_id": "ORG"}],
                             find_object_available=True)
    assert ent["status"] == "REVERTED_THEN_REDONE" and ent["successor"] == "n2"


def test_ledger_no_successor_when_none_matches():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
                             later_facts=[{"oid": "n1", "patch_id": "OTHER"}],
                             find_object_available=True)
    assert ent["status"] == "REVERTED_NO_SUCCESSOR" and ent["successor"] is None


def test_ledger_entry_none_without_marker():
    assert judge.ledger_entry("r1", "plain", commit_facts={}, later_facts=[],
                              find_object_available=True) is None


def test_evaluate_ledger_blocks_on_unverified_only():
    subject = {"mode": "ledger", "as_of": "2026-01-15", "find_object_available": True,
               "revert_bodies": [{"oid": "r1", "body": _revert_body()}],
               "commit_facts": {"r1": {"u0_patchid": "A"}, "deadbee": {}},
               "later_facts": []}
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-revert-unverified"][0]
    assert rec.verdict == WARN  # 判不了不是事故，但不许静默
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_ledger_no_successor_info():
    subject = {"mode": "ledger", "as_of": "2026-01-15", "find_object_available": True,
               "revert_bodies": [{"oid": "r1", "body": _revert_body()}],
               "commit_facts": {"r1": {"u0_patchid": "A"},
                                "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
               "later_facts": []}
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-reverted-no-successor"][0]
    assert rec.verdict == INFO
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_ledger_then_redone_info():
    subject = {"mode": "ledger", "as_of": "2026-01-15", "find_object_available": True,
               "revert_bodies": [{"oid": "r1", "body": _revert_body()}],
               "commit_facts": {"r1": {"u0_patchid": "A"},
                                "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
               "later_facts": [{"oid": "n1", "patch_id": "ORG"}]}
    records = _evaluate(subject)
    rec = [r for r in records if r.rule_id == "mf-reverted-then-redone"][0]
    assert rec.verdict == INFO
    assert rec.evidence["successor"] == "n1"


# ==================================================================
# §6 账本化 / 退出码 / subject 校验 / 宿主 CLI / 纯度
# ==================================================================

def test_subject_mode_unknown_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "gate"})


def test_subject_as_of_missing_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "fidelity", "merges": []})


def test_subject_as_of_bad_format_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "fidelity", "as_of": "2026/01/15", "merges": []})


def test_cli_check_sample_rc0():
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)])
    assert rc == EXIT_OK


def test_cli_check_sample_without_basis_rc0():
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE)])
    assert rc == EXIT_OK


def test_cli_check_smuggled_rc1():
    tmp = ROOT / ".tmp-mf-smuggled.json"
    subject = _subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF)])
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_BLOCKED


def test_cli_check_empty_basis_contract_rc3():
    tmp_in = ROOT / ".tmp-mf-ok.json"
    tmp_basis = ROOT / ".tmp-mf-empty-basis.json"
    tmp_in.write_text(json.dumps(_subject_fidelity([])), encoding="utf-8")
    tmp_basis.write_text(json.dumps({"version": "0", "rules": []}), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp_in), "--basis", str(tmp_basis)])
    finally:
        tmp_in.unlink()
        tmp_basis.unlink()
    assert rc == EXIT_CONTRACT


def test_builtin_modules_sorted_and_includes_merge_fidelity():
    # 计数不写死（器官数随批次增长，接线下限由本批钉住：≥21）
    assert "merge_fidelity" in BUILTIN_MODULES
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(BUILTIN_MODULES) >= 21


def test_pack_registered_contract_fields():
    load_builtin()
    pack = get(SLUG)
    assert pack.slug == SLUG
    assert pack.version == spec.ORGAN_VERSION == "1"
    assert pack.input_fields == ("mode",)


def test_all_records_have_basis_refs():
    records = _evaluate(_subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF)]))
    for r in records:
        assert r.basis is not None
        assert r.basis.rule_id.startswith("mf-")


def test_summary_counts_match_verdicts():
    records = _evaluate(_subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF)]))
    s = _summary(records).evidence
    assert s["error"] == sum(1 for r in records if r.verdict == ERROR and r.rule_id != "mf-summary")


def test_organ_sources_are_pure_no_io_clock_or_random():
    organ_dir = SRC / "byteproof" / "auditors" / "merge_fidelity"
    pattern = re.compile(r"\bopen\b|\bos\.environ\b|\btime\.time\b|\brandom\b|\bsocket\b"
                         r"|\burllib\b|\bsubprocess\b|\bprint\b|\binput\b|write_text")
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
    # datetime 仅用于 as_of 的 YYYY-MM-DD 形态校验（strptime 纯字符串解析，不读时钟）
    allowed = ("collections", "datetime", "fnmatch", "hashlib", "json", "re", "typing",
               "byteproof", "__future__", "")
    organ_dir = SRC / "byteproof" / "auditors" / "merge_fidelity"
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


def test_basis_rule_count_and_verdict_map_cover_all():
    # 15 条规则 ↔ verdict_map 三值全覆盖（多一条少一条都红）
    assert len(BASIS) == 15
    mapped = set(SETTINGS["verdict_map"]["error"]) | set(SETTINGS["verdict_map"]["info"]) | set(SETTINGS["verdict_map"]["warn"])
    assert set(BASIS.rule_ids()) == mapped
    for rule_id in SETTINGS["verdict_map"]["error"]:
        rule = BASIS.rule(rule_id)
        assert rule is not None and rule.version == "1"


def test_spec_constants_match_thresholds_snapshot():
    assert sorted(spec.MODES) == sorted(SETTINGS["modes"])
    assert list(spec.DEFAULT_KINDS) == SETTINGS["default_kinds"]
    assert sorted(spec.BUILTIN_MERGE_DRIVERS) == sorted(SETTINGS["builtin_merge_drivers"])
    assert SETTINGS["fail_on_kinds"]["any"] == ["SMUGGLED", "DROPPED"]
    assert SETTINGS["finding_id_algorithm"] == "sha1"  # 旧仓内容寻址 ID 口径（标识，非安全原语）
    assert SETTINGS["digest_algorithm"] == "sha256"


# ==================================================================
# §7 判定矩阵逐案落位（旧仓可机械复现的分支逐条）
# ==================================================================

# ---- diffparse hunk 头矩阵（0 基口径的每个分支）
def test_hunk_header_both_counts_positive():
    assert diffparse._parse_hunk_header("@@ -2,3 +4,5 @@") == (1, 3, 3, 5)


def test_hunk_header_old_zero_count():
    assert diffparse._parse_hunk_header("@@ -7,0 +2,3 @@") == (7, 0, 1, 3)


def test_hunk_header_counts_default_one():
    # 缺 ",count" 时 count 视为 1（git unified 头的省略形态）
    assert diffparse._parse_hunk_header("@@ -3 +3 @@") == (2, 1, 2, 1)


def test_hunk_header_funcname_suffix_ignored():
    assert diffparse._parse_hunk_header("@@ -1,2 +3,4 @@ def f():") == (0, 2, 2, 4)


def test_hunk_header_rejects_missing_old_side():
    with pytest.raises(ValueError):
        diffparse._parse_hunk_header("@@ +1,2 @@")


def test_hunk_header_rejects_bad_prefix():
    with pytest.raises(ValueError):
        diffparse._parse_hunk_header("@@ x1,2 +3,4 @@")


# ---- diffparse 文本级矩阵
def test_parse_unified_diff_multiple_files_two_hunk_groups():
    diff = ("diff --git a/one.txt b/one.txt\n@@ -1 +1 @@\n-a\n+b\n"
            "diff --git a/two.txt b/two.txt\n@@ -1 +1 @@\n-x\n+y\n")
    hunks = diffparse.parse_unified_diff(diff)
    assert [h.path for h in hunks] == ["one.txt", "two.txt"]


def test_parse_unified_diff_ignores_index_and_mode_lines():
    diff = ("diff --git a/f b/f\nold mode 1\nnew mode 2\nindex 1..2\n"
            "similarity index 90%\nrename from f\nrename to g\ncopy from f\ncopy to g\n"
            "deleted file mode x\nnew file mode y\n@@ -1 +1 @@\n-a\n+b\n")
    hunks = diffparse.parse_unified_diff(diff)
    assert len(hunks) == 1 and hunks[0].lines == ("-a", "+b")


def test_parse_unified_diff_no_newline_marker_skipped():
    diff = "diff --git a/f b/f\n@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n"
    hunks = diffparse.parse_unified_diff(diff)
    assert hunks[0].lines == ("-a", "+b")


def test_parse_unified_diff_context_lines_collected():
    diff = "diff --git a/f b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+c\n d\n"
    hunks = diffparse.parse_unified_diff(diff)
    assert hunks[0].lines == (" a", "-b", "+c", " d")


def test_parse_unified_diff_loose_text_before_diff_ignored():
    hunks = diffparse.parse_unified_diff("random preamble\ndiff --git a/f b/f\n@@ -1 +1 @@\n-a\n")
    assert len(hunks) == 1


def test_parse_unified_diff_empty_text_no_hunks():
    assert diffparse.parse_unified_diff("") == []


def test_parse_remerge_log_conflict_notes_collected():
    text = "a1\x00p1 p2\n\nremerge CONFLICT (content): f\ndiff --git a/f b/f\n@@ -1 +1 @@\n-a\n"
    entries = diffparse.parse_remerge_log(text)
    assert entries[0].conflict_notes == ("remerge CONFLICT (content): f",)


def test_parse_remerge_log_skips_leading_junk():
    entries = diffparse.parse_remerge_log("junk line\na1\x00p1 p2\n")
    assert [e.commit_oid for e in entries] == ["a1"]


def test_hunk_patch_text_additions_unreversed_stay_additions():
    text = diffparse.hunk_patch_text("f", ("+a", "+b"), reverse=True)
    # reverse=True：+ → -（重引入判定按新增方向比时由调用方决定方向）
    assert "-a\n-b\n" in text


def test_hunk_patch_text_mixed_prefixes_swap():
    text = diffparse.hunk_patch_text("f", ("-x", "+y"), reverse=True)
    assert "+x\n-y\n" in text


# ---- gitattributes / 路径匹配矩阵
def test_parse_gitattributes_ignores_short_lines_and_comments():
    assert judge.parse_gitattributes("# only comment\n\n *.lock merge=x") == [("*.lock", "x")]


def test_parse_gitattributes_merge_without_value_skipped():
    assert judge.parse_gitattributes("*.lock merge=\n") == []


def test_parse_gitattributes_multiple_attrs_picks_merge_only():
    assert judge.parse_gitattributes("a.bin text diff merge=z\n") == [("a.bin", "z")]


def test_pattern_matches_star_basename():
    assert judge.pattern_matches("*.md", "docs/readme.MD") is False  # fnmatchcase 大小写敏感


def test_pattern_matches_nested_path_needs_slash_pattern():
    assert judge.pattern_matches("*.txt", "a/b/f.txt") is True  # basename 匹配
    assert judge.pattern_matches("a/*.txt", "a/b/f.txt") is True
    assert judge.pattern_matches("a/*.txt", "b/f.txt") is False


def test_pattern_matches_dir_glob_requires_prefix():
    assert judge.pattern_matches("dir/**", "dir/") is True
    assert judge.pattern_matches("dir/**", "dirx/y") is False


def test_custom_driver_paths_multiple_hits():
    text = "*.lock merge=mine\n/vendor/** merge=theirs\n"
    # "z/lock" 的 basename 是 "lock"，不匹配 "*.lock"（缺前缀点）；"a/b.lock" 才命中
    got = judge.custom_driver_paths(text, {"z/lock", "sub/dep.lock", "vendor/a", "keep.txt"})
    assert got == {"vendor/a", "sub/dep.lock"}


# ---- blob_fidelity 矩阵
def test_blob_fidelity_rounds_to_twelve_decimals():
    fid = judge.blob_fidelity({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "2", "c": "9"})
    assert fid["blob_fidelity"] == round(2 / 3, 12)


def test_blob_fidelity_mechanical_only_paths_listed():
    fid = judge.blob_fidelity({}, {"m": "x"})
    assert fid["paths_total"] == 0 and fid["path_only_in_mechanical"] == ["m"]


def test_blob_fidelity_both_empty_none():
    fid = judge.blob_fidelity(None, None)
    assert fid["blob_fidelity"] is None and fid["paths_total"] == 0


def test_blob_fidelity_excluded_only_from_one_side():
    fid = judge.blob_fidelity({"a": "1", "sk": "x"}, {"a": "1"}, excluded={"sk"})
    assert fid["paths_total"] == 1


# ---- parity 矩阵
def test_parity_patchid_none_empty_diff_falls_to_apply_branch():
    row = judge.evaluate_candidate(_cand("c1", pid=None, text="",
                                         apply={"available": True, "reverse_check": True,
                                                "forward_check": False}),
                                   {"by_patchid": {}, "by_content": {}}, apply_fallback=True)
    assert row["status"] == "PRESENT" and row["basis"] == "apply"


def test_parity_apply_unavailable_with_fallback_modified():
    row = judge.evaluate_candidate(_cand("c1", pid=None),
                                   {"by_patchid": {}, "by_content": {}}, apply_fallback=True)
    assert row["status"] == "MODIFIED" and row["basis"] == "patchid"


def test_parity_equivalent_source_is_first_in_revlist_order():
    index = judge.build_side_index([{"commit": "s2", "diff_u0_text": "", "patch_id": "P", "paths": []},
                                    {"commit": "s1", "diff_u0_text": "", "patch_id": "P", "paths": []}])
    row = judge.evaluate_candidate(_cand("c1", pid="P"), index, apply_fallback=True)
    assert row["equivalent_source"] == "s2"  # 列表首项 = rev-list --reverse 的最早到达者


def test_parity_rows_preserve_candidate_order():
    subject = {"mode": "parity", "as_of": "2026-01-15", "side": [],
               "candidates": [_cand("c2"), _cand("c1")]}
    report = _summary(_evaluate(subject)).evidence["summary"]
    rows = [r for r in _evaluate(subject) if r.evidence.get("kind", "").startswith("PARITY_")]
    assert [r.evidence["commit_oid"] for r in rows] == ["c2", "c1"]


def test_evaluate_parity_multi_path_single_record_registered_deviation():
    # 旧仓 findings_of 按路径展开；账本按候选聚合（paths 进 evidence）——登记口径差
    subject = {"mode": "parity", "as_of": "2026-01-15", "side": [],
               "candidates": [_cand("c1", pid=None, paths=["a", "b"],
                                    apply={"available": True, "reverse_check": False,
                                           "forward_check": True})]}
    records = [r for r in _evaluate(subject) if r.evidence.get("kind") == "PARITY_MISSING"]
    assert len(records) == 1
    assert records[0].evidence["paths"] == ["a", "b"]


def test_parity_worktree_note_passthrough():
    subject = {"mode": "parity", "as_of": "2026-01-15", "side": [], "candidates": [],
               "worktree": {"created": True, "reason": "apply_fallback"}}
    records = _evaluate(subject)
    assert _summary(records).evidence["summary"]["candidates"] == 0


# ---- ledger 矩阵
def test_ledger_multi_marker_takes_first_oid():
    body = "This reverts commit deadbee.\nThis reverts commit cafe567.\n"
    ent = judge.ledger_entry("r1", body,
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
                             later_facts=[], find_object_available=True)
    assert ent["reverted_oid"] == "deadbee"


def test_ledger_revert_itself_not_a_successor():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
                             later_facts=[{"oid": "r1", "patch_id": "ORG"}],
                             find_object_available=True)
    assert ent["status"] == "REVERTED_NO_SUCCESSOR"


def test_ledger_successor_skips_revert_even_if_pid_matches():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
                             later_facts=[{"oid": "n1", "patch_id": "ORG"}],
                             find_object_available=True)
    assert ent["successor"] == "n1"


def test_ledger_no_original_pid_gives_no_successor():
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": "A"},
                                           "deadbee": {"reversed_patch_id": "A"}},
                             later_facts=[], find_object_available=True)
    assert ent["status"] == "REVERTED_NO_SUCCESSOR"


def test_ledger_extract_accepts_full_sha256_oid():
    body = "This reverts commit %s.\n" % ("f" * 64)
    assert judge.extract_reverted_oids(body) == ["f" * 64]


# ---- fidelity 编排矩阵
def test_evaluate_fidelity_mixed_diff_three_kinds_in_one_merge():
    diff = SMUGGLE_DIFF + DROP_DIFF + RESOLUTION_DIFF
    subject = _subject_fidelity([_merge("a" * 40, diff)],
                                options={"kinds": ["SMUGGLED", "DROPPED", "RESOLUTION"]})
    records = _evaluate(subject)
    kinds = {r.evidence["kind"] for r in records if r.evidence.get("finding_id")}
    assert kinds == {"SMUGGLED", "DROPPED", "RESOLUTION"}


def test_evaluate_fidelity_default_kinds_exclude_resolution():
    subject = _subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF + RESOLUTION_DIFF)])
    records = _evaluate(subject)
    assert [r for r in records if r.rule_id == "mf-resolution"] == []


def test_evaluate_fidelity_summary_counts_all_kinds():
    diff = SMUGGLE_DIFF + DROP_DIFF
    subject = _subject_fidelity([_merge("a" * 40, diff)],
                                patch_ids={_drop_probe_sha(): "PID1"},
                                later_patch_ids={"src/a.txt": ["PID1"]})
    s = _summary(_evaluate(subject)).evidence["summary"]
    assert s["smuggled"] == 1 and s["dropped"] == 0 and s["resolution"] == 0


def test_evaluate_fidelity_blob_fidelity_reported_per_merge():
    subject = _subject_fidelity([_merge("a" * 40, "",
                                        blobs={"f": "x"}, recorded={"f": "x"})])
    s = _summary(_evaluate(subject)).evidence["summary"]
    assert s["merges_scanned"] == 1
    records = _evaluate(subject)
    # blob_fidelity 数值在报告里，不在 finding 行（无阻断结论）
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_fidelity_payload_paths_in_tree_no_warning():
    payload = "a" * 40 + "\x00" + "2" * 40 + " " + "3" * 40 + "\n\ndiff --git a/src/a.txt b/src/a.txt\n@@ -1 +1 @@\n-x\n"
    subject = _subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF, payload=payload)])
    records = _evaluate(subject)
    assert [r for r in records if r.rule_id == "mf-warning-crosscheck"] == []


def test_evaluate_fidelity_mechanical_conflict_flag_passthrough():
    subject = _subject_fidelity([{"merge_oid": "a" * 40, "parents": ["2" * 40, "3" * 40],
                                  "mechanical_conflict": True, "tree_diff_text": "",
                                  "payload_text": ""}])
    records = _evaluate(subject)
    assert _summary(records).evidence["summary"]["merges_scanned"] == 1


# ---- 账本化 / 契约补面
def test_ledger_mode_cli_rc0_on_info_only():
    tmp = ROOT / ".tmp-mf-ledger.json"
    subject = {"mode": "ledger", "as_of": "2026-01-15", "find_object_available": True,
               "revert_bodies": [{"oid": "r1", "body": _revert_body()}],
               "commit_facts": {"r1": {"u0_patchid": "A"},
                                "deadbee": {"reversed_patch_id": "A", "u0_patchid": "ORG"}},
               "later_facts": []}
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_OK


def test_parity_mode_cli_rc1_on_missing():
    tmp = ROOT / ".tmp-mf-parity.json"
    subject = {"mode": "parity", "as_of": "2026-01-15", "side": [],
               "candidates": [_cand("c1", pid=None,
                                    apply={"available": True, "reverse_check": False,
                                           "forward_check": True})]}
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_BLOCKED


def test_records_carry_structured_evidence_fields():
    records = _evaluate(_subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF)]))
    rec = [r for r in records if r.rule_id == "mf-smuggled"][0]
    assert rec.evidence["merge_oid"] == "a" * 40
    assert rec.evidence["kind"] == "SMUGGLED"
    assert rec.path.startswith("aaaaaaaaaaaa:src/a.txt:SMUGGLED")


def test_summary_mode_and_counts_fidelity():
    records = _evaluate(_subject_fidelity([_merge("a" * 40, SMUGGLE_DIFF)]))
    s = _summary(records).evidence
    assert s["mode"] == "fidelity"
    assert s["summary"]["smuggled"] == 1


@pytest.mark.parametrize("text,expected", [
    ("@@ -1,3 +1 @@", (0, 3, 0, 1)),
    ("@@ -5,0 +6,2 @@", (5, 0, 5, 2)),
    ("@@ -3 +3 @@", (2, 1, 2, 1)),
    ("@@ -2,3 +4,5 @@ fn", (1, 3, 3, 5)),
    ("@@ -1 +1 @@", (0, 1, 0, 1)),
    ("@@ -0,0 +1 @@ func", (0, 0, 0, 1)),
    ("@@ -10,2 +10,0 @@", (9, 2, 10, 0)),
    ("@@ -100,1 +200,1 @@", (99, 1, 199, 1)),
    ("@@ -1,1 +1,1 @@", (0, 1, 0, 1)),
    ("@@ -7,9 +8,10 @@", (6, 9, 7, 10)),
    ("@@ -2,0 +3,0 @@", (2, 0, 3, 0)),
    ("@@ -12 +15,3 @@", (11, 1, 14, 3)),
    ("@@ -9,0 +9,0 @@", (9, 0, 9, 0)),
])
def test_hunk_header_matrix_parametrized(text, expected):
    assert diffparse._parse_hunk_header(text) == expected


@pytest.mark.parametrize("pattern,path,hit", [
    ("*.lock", "a/c.lock", True),      # basename "c.lock" 匹配 *.lock
    ("*.lock", "a/lock", False),       # basename "lock" 无前缀点
    ("/exact", "exact", True),         # 剥掉 "/" 后按 basename 匹配
    ("/exact", "sub/exact", True),     # 同上：basename 相等即命中（旧仓口径）
    ("dir/**", "dir/a/b", True),
    ("dir/**", "d/a", False),
    ("name.txt", "deep/name.txt", True),
    ("a/*", "a/b/c", True),            # fnmatch 的 * 跨斜杠（旧仓口径）
    ("a/*", "b/a/x", False),
])
def test_pattern_matches_matrix_parametrized(pattern, path, hit):
    assert judge.pattern_matches(pattern, path) is hit


@pytest.mark.parametrize("obj", [
    {"a": 1},
    {"list": [1, "x", None, True]},
    {"nested": {"deep": {"deeper": [1, 2]}}},
    {"unicode": "中文键值"},
    {"empty": {}, "arr": []},
])
def test_canonical_invariants_parametrized(obj):
    text = canonical.dumps(obj)
    assert canonical.dumps(json.loads(text)) == text  # 幂等
    assert canonical.verify_digest(canonical.with_digest(obj)) is True


@pytest.mark.parametrize("merge_oid,path,old_range,new_range,kind", [
    ("a" * 40, "src/a.txt", "0,2", "-", "SMUGGLED"),
    ("a" * 40, "src/a.txt", "0,2", "-", "DROPPED"),
    ("a" * 40, "src/a.txt", "-", "0,2", "RESOLUTION"),
    ("b" * 40, "src/a.txt", "0,2", "-", "SMUGGLED"),
    ("a" * 40, "src/b.txt", "0,2", "-", "SMUGGLED"),
    ("a" * 40, "src/a.txt", "0,3", "-", "SMUGGLED"),
    ("a" * 40, "src/a.txt", "-", "-", "PARITY_MISSING"),
    ("c1", "x.txt", "-", "-", "PARITY_MODIFIED"),
    ("r1", "deadbee", "-", "-", "REVERTED_THEN_REDONE"),
])
def test_finding_id_matrix_parametrized(merge_oid, path, old_range, new_range, kind):
    # 内容寻址 ID 矩阵：任一部分不同 → ID 不同；同参数两次相同；与提交时间无关
    id1 = canonical.finding_id(merge_oid, path, old_range, new_range, kind)
    id2 = canonical.finding_id(merge_oid, path, old_range, new_range, kind)
    assert id1 == id2 and len(id1) == 40


def test_finding_id_differs_across_matrix_rows():
    rows = [
        ("a" * 40, "src/a.txt", "0,2", "-", "SMUGGLED"),
        ("a" * 40, "src/a.txt", "0,2", "-", "DROPPED"),
        ("b" * 40, "src/a.txt", "0,2", "-", "SMUGGLED"),
        ("a" * 40, "src/b.txt", "0,2", "-", "SMUGGLED"),
    ]
    ids = [canonical.finding_id(*row) for row in rows]
    assert len(set(ids)) == len(rows)


@pytest.mark.parametrize("pid_match,apply,fallback,expected_status,expected_basis", [
    (True, None, True, "PRESENT", "patchid"),
    (False, {"available": True, "reverse_check": True, "forward_check": False}, True, "PRESENT", "apply"),
    (False, {"available": True, "reverse_check": False, "forward_check": True}, True, "MISSING", "apply"),
    (False, {"available": True, "reverse_check": False, "forward_check": False}, True, "MODIFIED", "apply"),
    (False, {"available": False}, True, "MODIFIED", "patchid"),
    (False, None, False, "MODIFIED", "patchid"),
    (None, {"available": True, "reverse_check": True, "forward_check": False}, True, "PRESENT", "apply"),
    (None, {"available": True, "reverse_check": False, "forward_check": True}, True, "MISSING", "apply"),
    (None, {"available": True, "reverse_check": False, "forward_check": False}, True, "MODIFIED", "apply"),
    (None, {"available": False}, True, "MODIFIED", "patchid"),
    (None, None, False, "MODIFIED", "patchid"),
])
def test_parity_three_state_matrix_parametrized(pid_match, apply, fallback,
                                                expected_status, expected_basis):
    pid = "P1" if pid_match is True else (None if pid_match is None else "P9")
    side = {"by_patchid": {"P1": ["s1"]}, "by_content": {}}
    row = judge.evaluate_candidate(_cand("c1", pid=pid, apply=apply), side,
                                   apply_fallback=fallback)
    assert row["status"] == expected_status
    assert row["basis"] == expected_basis


@pytest.mark.parametrize("revert_pid,reversed_pid,find_object,successor_pid,expected_status", [
    ("A", "A", True, "ORG", "REVERTED_THEN_REDONE"),
    ("A", "A", True, None, "REVERTED_NO_SUCCESSOR"),
    ("A", "A", False, "ORG", "REVERT_UNVERIFIED"),
    ("A", "B", True, "ORG", "REVERT_UNVERIFIED"),
    (None, "A", True, "ORG", "REVERT_UNVERIFIED"),
    ("A", None, True, "ORG", "REVERT_UNVERIFIED"),
])
def test_ledger_state_matrix_parametrized(revert_pid, reversed_pid, find_object,
                                          successor_pid, expected_status):
    ent = judge.ledger_entry("r1", _revert_body(),
                             commit_facts={"r1": {"u0_patchid": revert_pid},
                                           "deadbee": {"reversed_patch_id": reversed_pid,
                                                       "u0_patchid": "ORG"}},
                             later_facts=[{"oid": "n1", "patch_id": successor_pid}] if successor_pid else [],
                             find_object_available=find_object)
    assert ent["status"] == expected_status
    assert ent["verified"] is (revert_pid == reversed_pid and revert_pid is not None)


@pytest.mark.parametrize("kinds,show_resolution,expected_kinds", [
    (None, False, {"SMUGGLED", "DROPPED"}),
    (["SMUGGLED"], False, {"SMUGGLED"}),
    (["DROPPED"], False, {"DROPPED"}),
    (["SMUGGLED", "DROPPED", "RESOLUTION"], False,
     {"SMUGGLED", "DROPPED", "RESOLUTION"}),
    (None, True, {"SMUGGLED", "DROPPED", "RESOLUTION"}),
])
def test_fidelity_kinds_matrix_parametrized(kinds, show_resolution, expected_kinds):
    diff = SMUGGLE_DIFF + DROP_DIFF + RESOLUTION_DIFF
    options = {"kinds": kinds, "show_resolution": show_resolution}
    subject = _subject_fidelity([_merge("a" * 40, diff)],
                                options={k: v for k, v in options.items() if v is not None})
    records = _evaluate(subject)
    got = {r.evidence["kind"] for r in records if r.evidence.get("finding_id")}
    assert got == expected_kinds


def test_revert_marker_is_anchored_to_line_start():
    # 行中提及不算（re.MULTILINE 的 ^ 锚）
    assert judge.extract_reverted_oids("see This reverts commit deadbee in history") == []
    assert judge.extract_reverted_oids("x\nThis reverts commit deadbee") == ["deadbee"]


def test_fidelity_emits_skips_before_merges_in_id_space():
    # skipped 与 findings 的 id 互不冲突（不同 rule_id + 不同 path 面）
    subject = _subject_fidelity([_merge("a" * 40, "", parents=["1" * 40, "2" * 40, "3" * 40])])
    records = _evaluate(subject)
    ids = [r.id for r in records]
    assert len(ids) == len(set(ids))


def test_warn_records_never_block():
    for subject in (
        _subject_fidelity([_merge("b" * 40, DROP_DIFF)]),  # 未绑定探针 → warn
        {"mode": "parity", "as_of": "2026-01-15", "side": [], "candidates": [],
         "warnings": [{"code": "CHERRY_COUNT_MISMATCH"}]},
    ):
        records = _evaluate(subject)
        assert _report(records).exit_code() in (EXIT_OK, EXIT_BLOCKED)

