"""自研区间代数（照搬旧仓 ``src/semver/interval.mjs``，1:1 移植）。

rawRange ──valid_range──▶ expandedRange ──拆分──▶ 半开区间集合 [lo, hi)。
多个范围的交集 = 逐分支求交（笛卡尔积），非空 ⇔ 存在候选版本。

**硬纪律（旧仓 ``data/README.md`` §7.1）**：区间非空只是"可能有解"的必要条件；
``CONVERGIBLE`` 的最终判据必须用 ``satisfies`` 对**实际锁定版本**实算。

本模块不做 I/O、不读时钟、不联网。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from . import semver_core

INF = ("inf",)  # 哨兵：无上界（与版本三元组 tuple 形态不同型即可比较性区分）
NEG_INF = ("-inf",)

Bound = Tuple  # (v: (major, minor, patch) | INF | NEG_INF, pre: str | None)


def _bound_from(version_string) -> Bound:
    if version_string in (None, ""):
        return (INF, None)
    parsed = semver_core.parse(version_string)
    if parsed is None:
        return (INF, None)
    pre = ".".join(str(part) for part in parsed.prerelease) if parsed.prerelease else None
    return ((parsed.major, parsed.minor, parsed.patch), pre)


def _cmp_identifier(a: str, b: str) -> int:
    """SemVer §11：数字标识符按数值比较，且数字恒小于字母数字。"""
    a_num = a.isdigit()
    b_num = b.isdigit()
    if a_num and b_num:
        na, nb = int(a), int(b)
        return 0 if na == nb else (-1 if na < nb else 1)
    if a_num:
        return -1
    if b_num:
        return 1
    if a == b:
        return 0
    return -1 if a < b else 1


def _cmp_pre(a, b) -> int:
    if a is None and b is None:
        return 0
    if a is None:
        return 1  # 无预发布 > 有预发布
    if b is None:
        return -1
    as_parts = a.split(".")
    bs_parts = b.split(".")
    for i in range(min(len(as_parts), len(bs_parts))):
        c = _cmp_identifier(as_parts[i], bs_parts[i])
        if c != 0:
            return c
    if len(as_parts) == len(bs_parts):
        return 0
    return -1 if len(as_parts) < len(bs_parts) else 1


def _is_inf(v) -> bool:
    # 哨兵用**同一性**判定：版本三元组也是 tuple，不能按类型区分
    return v is INF or v is NEG_INF


#: 给兄弟模块用的公开名（哨兵判定必须在同一处定义）。
is_sentinel = _is_inf


def cmp_bound(a: Bound, b: Bound) -> int:
    """照搬旧仓 cmpBound：NEG_INF 先判、INF 后判（顺序错了会把有限界当成无穷）。"""
    va, vb = a[0], b[0]
    if _is_inf(va) and _is_inf(vb):
        if va == vb:
            return 0
        return -1 if va == NEG_INF else 1
    if _is_inf(va):
        return -1 if va == NEG_INF else 1
    if _is_inf(vb):
        return 1 if vb == NEG_INF else -1
    if va != vb:
        return -1 if va < vb else 1
    return _cmp_pre(a[1], b[1])


def _next_major(parsed) -> Bound:
    return ((parsed.major + 1, 0, 0), "0")


def _next_minor(parsed) -> Bound:
    return ((parsed.major, parsed.minor + 1, 0), "0")


def _next_patch(parsed) -> Bound:
    return ((parsed.major, parsed.minor, parsed.patch + 1), "0")


def comparator_to_bounds(comp: str) -> Dict:
    """把一个展开后的比较器转成 {lo, hi}。

    只覆盖 valid_range 会产出的比较器形态（``>=`` / ``<=`` / ``>`` / ``<`` / ``=`` /
    ``^`` / ``~`` / ``*``）；出现未知形态时**显式抛错**而不是猜。
    """
    if comp in ("*", ""):
        return {
            "lo": (NEG_INF, None),
            "hi": (INF, None),
            "exclusive_lo": False,
            "exclusive_hi": False,
        }
    m = _COMPARATOR_SHAPE.match(comp)
    if not m:
        raise ValueError('区间代数：无法识别的比较器 "%s"' % comp)
    op = m.group(1) or "="
    target = m.group(2)
    parsed = semver_core.parse(target)
    if parsed is None:
        raise ValueError('区间代数：比较器 "%s" 的版本部分不可解析' % comp)
    base = _bound_from(target)
    exclusive_lo = False
    exclusive_hi = False
    if op == ">=":
        lo, hi = base, (INF, None)
    elif op == ">":
        # >1.2.3 = 严格大于；不制造假后继，用 exclusive_lo 标记开区间
        lo, hi = base, (INF, None)
        exclusive_lo = True
    elif op == "<":
        lo, hi = (NEG_INF, None), base
        exclusive_hi = True
    elif op == "<=":
        lo, hi = (NEG_INF, None), base
    elif op == "=":
        # 精确版本 = 单点闭区间；等界排除形态（1.0.0 >1.0.0）由开闭标记判定
        lo, hi = base, base
    elif op == "^":
        if parsed.major > 0:
            hi = _next_major(parsed)
        elif parsed.minor > 0:
            hi = _next_minor(parsed)
        else:
            hi = _next_patch(parsed)
        lo = base
    elif op == "~":
        lo, hi = base, _next_minor(parsed)
    else:
        raise ValueError('区间代数：未实现的比较器运算符 "%s"' % op)
    return {"lo": lo, "hi": hi, "exclusive_lo": exclusive_lo, "exclusive_hi": exclusive_hi}


_COMPARATOR_SHAPE = __import__("re").compile(r"^(\^|~|>=|<=|>|<|=)?\s*(.+)$")


def normalize_range(raw_range: str) -> Optional[Dict]:
    """一个 rawRange → 若干分支；返回 None 表示不是 semver 范围（如 ``latest``）。"""
    expanded = semver_core.valid_range(raw_range)
    if expanded is None:
        return None
    branches = [part.strip() for part in expanded.split("||") if part.strip()]
    norm_branches: List[Dict] = []
    for branch in branches:
        comps = [c for c in branch.split() if c]
        lo: Bound = (NEG_INF, None)
        hi: Bound = (INF, None)
        exclusive_lo = False
        exclusive_hi = False
        for comp in comps:
            b = comparator_to_bounds(comp)
            if not _is_inf(b["lo"][0]):
                cl = cmp_bound(b["lo"], lo)
                if cl > 0:
                    lo = b["lo"]
                    exclusive_lo = bool(b["exclusive_lo"])
                elif cl == 0:
                    exclusive_lo = exclusive_lo or bool(b["exclusive_lo"])
            if not _is_inf(b["hi"][0]):
                ch = cmp_bound(b["hi"], hi)
                if ch < 0:
                    hi = b["hi"]
                    exclusive_hi = bool(b["exclusive_hi"])
                elif ch == 0:
                    exclusive_hi = exclusive_hi or bool(b["exclusive_hi"])
        norm_branches.append(
            {"lo": lo, "hi": hi, "exclusive_lo": exclusive_lo, "exclusive_hi": exclusive_hi, "comps": comps}
        )
    return {"raw_range": raw_range, "expanded_range": expanded, "branches": norm_branches}


def branch_is_empty(branch: Dict) -> bool:
    """分支是否为空（lo > hi，或 lo == hi 且排除端点）。

    端点开闭性决定一切：``>=1.0.0 <=1.0.0`` 非空单点；``>=1.0.0 <1.0.0`` 空；
    精确比较器与排除侧并存（``1.0.0 >1.0.0``）也空 —— 判空只看两侧开闭。
    """
    c = cmp_bound(branch["lo"], branch["hi"])
    if c > 0:
        return True
    if c == 0:
        return branch["exclusive_lo"] is True or branch["exclusive_hi"] is True
    return False


def range_is_empty(raw_range: str) -> Optional[bool]:
    """整个范围是否为空（所有分支都空）。``latest`` 返回 None。"""
    norm = normalize_range(raw_range)
    if norm is None:
        return None
    return all(branch_is_empty(b) for b in norm["branches"])


def intersect_branches(a: Dict, b: Dict) -> Optional[Dict]:
    """两个分支的交集（无交集返回 None）。"""
    clo = cmp_bound(a["lo"], b["lo"])
    lo = a["lo"] if clo >= 0 else b["lo"]
    lo_exclusive = (a["exclusive_lo"] or b["exclusive_lo"]) if clo == 0 else (a["exclusive_lo"] if clo > 0 else b["exclusive_lo"])
    chi = cmp_bound(a["hi"], b["hi"])
    hi = a["hi"] if chi <= 0 else b["hi"]
    hi_exclusive = (a["exclusive_hi"] or b["exclusive_hi"]) if chi == 0 else (a["exclusive_hi"] if chi < 0 else b["exclusive_hi"])
    merged = {"lo": lo, "hi": hi, "exclusive_lo": lo_exclusive, "exclusive_hi": hi_exclusive}
    return None if branch_is_empty(merged) else merged


def intersect_ranges(ranges: Iterable[str]) -> Dict:
    """多个 rawRange 的交集：分支笛卡尔积，保留非空者。

    返回 ``{empty, branches, culprit_pair?}``；含非法范围时 ``empty=None`` 并给出
    ``invalid_index`` / ``invalid_range``。
    """
    range_list = list(ranges)
    norms = [normalize_range(r) for r in range_list]
    invalid = next((i for i, n in enumerate(norms) if n is None), -1)
    if invalid >= 0:
        return {"empty": None, "branches": [], "invalid_index": invalid, "invalid_range": range_list[invalid]}
    acc: List[Dict] = [{"lo": (NEG_INF, None), "hi": (INF, None), "exclusive_lo": False, "exclusive_hi": False}]
    for i, norm in enumerate(norms):
        nxt: List[Dict] = []
        for cur in acc:
            for branch in norm["branches"]:
                merged = intersect_branches(cur, branch)
                if merged:
                    nxt.append(merged)
        acc = nxt
        if not acc:
            return {"empty": True, "branches": [], "failed_at_index": i}
    return {"empty": len(acc) == 0, "branches": acc}


def evaluate_candidates(candidates: Iterable[str], ranges: Iterable[str], satisfies_fn) -> List[Dict]:
    """给定候选版本列表，返回每个候选对全部范围的满足性实算结果。"""
    range_list = list(ranges)
    return [
        {"version": version, "satisfied": all(satisfies_fn(version, r) for r in range_list)}
        for version in candidates
    ]


def sort_versions(versions: Iterable[str]) -> List[str]:
    """稳定版本序（semver 升序）；非法版本排最后并按字典序兜底，保证确定性。"""
    import functools

    def cmp(a: str, b: str) -> int:
        va = semver_core.parse(a) is not None
        vb = semver_core.parse(b) is not None
        if va and vb:
            c = semver_core.compare(a, b)
            if c != 0:
                return c
        elif va:
            return -1
        elif vb:
            return 1
        if a < b:
            return -1
        if a > b:
            return 1
        return 0

    return sorted(versions, key=functools.cmp_to_key(cmp))
