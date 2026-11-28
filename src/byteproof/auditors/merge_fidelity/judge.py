"""三模块判定核（移植自旧仓 ``fidelity.py`` / ``parity.py`` / ``ledger.py`` 的纯面）。

git 子进程面（rev-list / cat-file / patch-id / merge-tree / worktree）全部留输入层：
subject 携带**预抽取的事实**（blob 映射 / diff 文本 / patch-id 及其绑定），
器官做纯判定。patch-id 等值比较口径不变；器官不实现 git patch-id 算法
（实现漂移风险 > 查表），由 subject 的 ``patch_ids`` 映射提供
（``sha256(逐字节 diff 文本) → git patch-id --stable 第一列``），查不到按
"不能证重引入 → 保守不排除"处理并记 warn（口径差，见 docs §7）。
"""

from __future__ import annotations

import fnmatch
import re

from . import diffparse
from . import spec

# ---------------------------------------------------------------- fidelity 纯面

#: git 自带 merge driver；其余视为自定义 driver
BUILTIN_MERGE_DRIVERS = spec.BUILTIN_MERGE_DRIVERS


def parse_gitattributes(text):
    """解析 ``.gitattributes`` 的 ``merge=`` 属性 → ``[(pattern, driver)]``。"""
    found = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        pattern = fields[0]
        for attr in fields[1:]:
            if attr.startswith("merge="):
                driver = attr[len("merge="):]
                if driver and driver not in BUILTIN_MERGE_DRIVERS:
                    found.append((pattern, driver))
            elif attr == "-merge":
                found.append((pattern, "-merge"))
    return found


def pattern_matches(pattern, path):
    """gitattributes 模式的**简化**匹配（旧仓口径：宁保守少命中，不做近似分析）。

    支持：``*.ext`` / 顶层文件名 / ``dir/**`` / ``/精确路径``。
    """
    if pattern.startswith("/"):
        pattern = pattern[1:]
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3] + "/")
    if "/" not in pattern:
        return fnmatch.fnmatchcase(path.split("/")[-1], pattern)
    return fnmatch.fnmatchcase(path, pattern)


def custom_driver_paths(gitattributes_text, paths):
    """命中自定义 merge driver 的路径集合（空集 = 无命中）。"""
    rules = parse_gitattributes(gitattributes_text)
    if not rules:
        return set()
    hit = set()
    for path in sorted(paths):
        for pattern, _driver in rules:
            if pattern_matches(pattern, path):
                hit.add(path)
                break
    return hit


def blob_fidelity(recorded_blobs, mechanical_blobs, excluded=()):
    """旧仓 §4.2：分母 = 两侧都存在的 path（剔除 SKIPPED 路径）。"""
    recorded = dict(recorded_blobs or {})
    mechanical = dict(mechanical_blobs or {})
    for path in excluded:
        recorded.pop(path, None)
        mechanical.pop(path, None)
    both = sorted(set(recorded) & set(mechanical))
    same = [p for p in both if recorded[p] == mechanical[p]]
    value = None if not both else round(float(len(same)) / len(both), 12)
    return {
        "blob_fidelity": value,
        "paths_total": len(both),
        "paths_same": len(same),
        "path_only_in_recorded": sorted(set(recorded) - set(mechanical)),
        "path_only_in_mechanical": sorted(set(mechanical) - set(recorded)),
    }


def classify_hunks(hunks, *, excluded_paths, reintroduced):
    """按旧仓 §4.3 把 tree diff 的 hunk 三分。

    ``hunks`` 来自 ``git diff -U0 <mechanical> <recorded>`` —— 方向已定，
    因此"只含 ``-`` 行"即"机械树有、记录树没有" = 内容被吞掉。
    ``reintroduced(path, addition_text)`` 是重引入判定回调：
    输入层以 ``git patch-id`` 供证（口径见本模块 docstring）。
    """
    smuggled, dropped, resolution = [], [], []
    for hunk in hunks:
        if hunk.path in excluded_paths or hunk.binary:
            continue
        if hunk.has_conflict_marker:
            resolution.append(hunk)
            continue
        if any(line.startswith("+") for line in hunk.lines):
            smuggled.append(hunk)
            continue
        addition = diffparse.hunk_patch_text(hunk.path, hunk.lines, reverse=True)
        if reintroduced(hunk.path, addition):
            continue
        dropped.append(hunk)
    return smuggled, dropped, resolution


def render_hunk(hunk, kind):
    from . import canonical

    return {
        "kind": kind,
        "path": hunk.path,
        "old_range": canonical.range_str(hunk.old_start, hunk.old_count),
        "new_range": canonical.range_str(hunk.new_start, hunk.new_count),
    }


def range_end(spec_text):
    """报告头指纹用的"范围右端"：``A..B`` → ``B``；单个 REV → 它自己；无范围 → ``HEAD``。"""
    if not spec_text:
        return "HEAD"
    separator = "..." if "..." in spec_text else ".."
    if separator not in spec_text:
        return spec_text
    _left, _, right = spec_text.partition(separator)
    return right or "HEAD"


def validate_as_of(value):
    """``as_of`` 必须是 ``YYYY-MM-DD``（旧仓：全项目只有这一处实现）。

    旧仓 ``--as-of`` 可缺省（由范围内最新提交时间推导，零时钟）；器官的 subject
    必须显式带 ``as_of``（输入层从提交事实算好传入），缺了按输入不合法处理。
    """
    import datetime

    if value is None:
        raise ValueError("as_of 必填（YYYY-MM-DD）：输入层从提交事实推导传入，器官不读时钟")
    if not isinstance(value, str):
        raise ValueError("as_of 必须是 YYYY-MM-DD 字符串")
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError("as_of 必须是 YYYY-MM-DD：%r" % (value,))
    return value


# ---------------------------------------------------------------- parity 纯面

STATUS_PRESENT = spec.STATUS_PRESENT
STATUS_MISSING = spec.STATUS_MISSING
STATUS_MODIFIED = spec.STATUS_MODIFIED
BASIS_PATCHID = spec.BASIS_PATCHID
BASIS_APPLY = spec.BASIS_APPLY
NOTE_ALREADY_PRESENT = spec.NOTE_ALREADY_PRESENT
NOTE_PARTIAL = spec.NOTE_PARTIAL
NOTE_OTHER_PATH = spec.NOTE_OTHER_PATH


def build_side_index(side_facts):
    """A 侧索引：``patch_id`` → 提交列表 + 内容指纹索引（输入层给逐提交 diff 文本与 patch-id）。

    * ``by_patchid``：值取列表首项作为 ``equivalent_source``（与 golden 一致——
      ``rev-list --reverse`` 的"最早到达者"）。
    * ``by_content``：``hunk 内容行元组`` → ``[(path, commit)]``，只用于**提示**。
    """
    by_patchid = {}
    by_content = {}
    for fact in side_facts:
        commit = fact["commit"]
        diff_u0 = fact.get("diff_u0_text", "")
        patch = fact.get("patch_id")
        if patch:
            by_patchid.setdefault(patch, []).append(commit)
        for hunk in diffparse.parse_unified_diff(diff_u0):
            by_content.setdefault(tuple(hunk.lines), []).append((hunk.path, commit))
    return {"by_patchid": by_patchid, "by_content": by_content}


def classify_apply(reverse_check, forward_check):
    """apply 三态兜底（旧仓 ``_classify_with_apply``；两个布尔由输入层的 worktree 检查给出）。

    reverse 成功 → PRESENT(basis=apply, already present)；forward 成功 → MISSING；
    皆失败 → MODIFIED(partial)。
    """
    if reverse_check:
        return STATUS_PRESENT, BASIS_APPLY, NOTE_ALREADY_PRESENT
    if forward_check:
        return STATUS_MISSING, BASIS_APPLY, None
    return STATUS_MODIFIED, BASIS_APPLY, NOTE_PARTIAL


def evaluate_candidate(candidate, side_index, *, apply_fallback):
    """单个候选 → 三态判定行（旧仓 ``_evaluate`` 的纯面）。

    ``candidate`` 带键：``commit`` / ``subject`` / ``diff_u0_text`` / ``patch_id`` /
    ``paths`` / ``apply``（``{"available": bool, "reverse_check": bool|None,
    "forward_check": bool|None}``，``available=False`` 表示输入层未做 apply 检查）。
    """
    diff_u0 = candidate.get("diff_u0_text", "")
    patch_u0 = candidate.get("patch_id")

    equivalent_source = None
    if patch_u0 and patch_u0 in side_index["by_patchid"]:
        status, basis, note = STATUS_PRESENT, BASIS_PATCHID, None
        equivalent_source = side_index["by_patchid"][patch_u0][0]
    elif not apply_fallback:
        # 没有 apply 证据：patch-id 不等**不能**推出"缺失"，只能记 MODIFIED
        status, basis, note = STATUS_MODIFIED, BASIS_PATCHID, None
    else:
        apply = candidate.get("apply") or {}
        if not apply.get("available"):
            # apply 检查声称可用但没有检查结果 —— 与"未启用 apply 兜底"同样只能记 MODIFIED
            status, basis, note = STATUS_MODIFIED, BASIS_PATCHID, None
        else:
            status, basis, note = classify_apply(
                apply.get("reverse_check"), apply.get("forward_check"))

    if status != STATUS_PRESENT and note is None:
        note, equivalent_source = other_path_note(side_index, diff_u0)

    return {
        "commit": candidate["commit"],
        "subject": candidate.get("subject"),
        "u0_patchid": patch_u0,
        "status": status,
        "basis": basis,
        "note": note,
        "equivalent_source": equivalent_source,
        "paths": list(candidate.get("paths", [])),
    }


def other_path_note(side_index, diff_u0):
    """同内容落在别的路径 → 只提示（路径参与 patch-id，这种候选**仍是 MISSING**）。"""
    for hunk in diffparse.parse_unified_diff(diff_u0):
        for path, commit in side_index["by_content"].get(tuple(hunk.lines), []):
            if path != hunk.path:
                return NOTE_OTHER_PATH, commit
    return None, None


def parity_row_counts(rows):
    present = len([r for r in rows if r["status"] == STATUS_PRESENT])
    missing = len([r for r in rows if r["status"] == STATUS_MISSING])
    modified = len([r for r in rows if r["status"] == STATUS_MODIFIED])
    total = len(rows)
    return {
        "candidates": total,
        "present": present,
        "missing": missing,
        "modified": modified,
        "patch_parity": None if total == 0 else round(float(present) / total, 12),
    }


# ---------------------------------------------------------------- ledger 纯面

STATUS_NO_SUCCESSOR = spec.STATUS_NO_SUCCESSOR
STATUS_THEN_REDONE = spec.STATUS_THEN_REDONE
STATUS_UNVERIFIED = spec.STATUS_UNVERIFIED
REASON_GIT_TOO_OLD = spec.REASON_GIT_TOO_OLD
CAPABILITY_FIND_OBJECT = spec.CAPABILITY_FIND_OBJECT

#: 只认正文里 git revert 生成的那一行；7–64 位十六进制（短 OID / sha1 / sha256 都覆盖）
REVERT_MARKER_RE = re.compile(spec.REVERT_MARKER_PATTERN, re.MULTILINE)

RECORD_SEP = spec.RECORD_SEP
FIELD_SEP = spec.FIELD_SEP


def enumerate_reverts(commit_bodies):
    """从 ``--format=%H<US>%B<RS>`` 的正文块提取 ``[(revert_oid, body)]``。

    输入层把 ``git log --grep='^This reverts commit'`` 的输出按记录切好传入；
    同一 revert 只入账一次（旧仓 ``_enumerate_reverts`` 的提取/去重面）。
    """
    seen = set()
    records = []
    for chunk in commit_bodies:
        oid = chunk.get("oid", "")
        body = chunk.get("body", "")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        if REVERT_MARKER_RE.search(body):
            records.append((oid, body))
        # 无标记的提交不进账本（枚举面 --grep 已过滤；这里的正则是第二道提取）
    return records


def extract_reverted_oids(body):
    """正文 → 被回滚 OID 列表（``^This reverts commit`` 多行正则）。"""
    return REVERT_MARKER_RE.findall(body)


def ledger_entry(revert_oid, body, *, commit_facts, later_facts, find_object_available,
                 later_revert_facts=None):
    """单条 revert 的校验与重放（旧仓 ``_entry`` 的纯面）。

    ``commit_facts``：``oid → {"patch_id", "reversed_patch_id", "u0_patchid"?}``
    （输入层对 revert、被回滚提交各自用 ``git diff-tree -p -U0`` + ``git patch-id
    --stable`` 算好；被回滚提交取反无意义（根提交）时 ``reversed_patch_id`` 为 null）。
    ``later_facts``：``[{"oid", "patch_id"}]``——revert 之后的提交（重放候选）。
    """
    oids = extract_reverted_oids(body)
    if not oids:
        return None
    reverted_oid = oids[0]

    revert_fact = commit_facts.get(revert_oid) or {}
    reverted_fact = commit_facts.get(reverted_oid) or {}
    revert_pid = revert_fact.get("u0_patchid") or revert_fact.get("patch_id")
    reversed_pid = reverted_fact.get("reversed_patch_id")

    verified = revert_pid is not None and reversed_pid is not None and revert_pid == reversed_pid
    if not verified:
        # 不猜意图，也不算 successor
        return {
            "revert_oid": revert_oid,
            "reverted_oid": reverted_oid,
            "verified": False,
            "status": STATUS_UNVERIFIED,
            "unavailable": None,
            "successor": None,
        }

    if not find_object_available:
        # 确知这条 revert 是真的，但无法判定是否被重做（能力缺失），不降级猜
        return {
            "revert_oid": revert_oid,
            "reverted_oid": reverted_oid,
            "verified": True,
            "status": STATUS_UNVERIFIED,
            "unavailable": CAPABILITY_FIND_OBJECT,
            "successor": None,
        }

    original_pid = reverted_fact.get("u0_patchid") or reverted_fact.get("patch_id")
    successor = None
    if original_pid:
        for fact in later_facts:
            if fact["oid"] == revert_oid:
                continue
            if fact.get("patch_id") and fact["patch_id"] == original_pid:
                successor = fact["oid"]
                break

    return {
        "revert_oid": revert_oid,
        "reverted_oid": reverted_oid,
        "verified": True,
        "status": STATUS_THEN_REDONE if successor else STATUS_NO_SUCCESSOR,
        "unavailable": None,
        "successor": successor,
        "original_pid": original_pid,
    }
