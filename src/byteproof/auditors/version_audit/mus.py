"""MUS（极小不可满足子集）—— M3/M4 共用的唯一实现（照搬旧仓 ``src/mus/minimal-set.mjs``）。

定义（旧仓 ``data/README.md`` §7.2）：
  M ⊆ R 是最小冲突集 ⇔ ① M 无解（任何候选版本都不满足 M 的全部范围）；
                      ② ∀ M' ⊊ M，M' 有解（"有解"对子集单调，单元素移除已足够）。

两条求法：
  1. **未超限**：按基数 k = 1,2,3,… 升序遍历子集，首个无解层即**基数最小**，同层平局全返回。
  2. **超限**：改用**删除法** —— 从全量 R 出发逐个尝试移除，只有移除后仍无解才真的移除。
     结果仍是无解的极小集，但**不保证基数最小**、也**不列全部平局集**，必须 ``degraded: true``。

降级不能把"不是冲突"报成冲突：删除法保证返回集合确实无解。
"""

from __future__ import annotations

from itertools import combinations
from typing import Callable, Dict, List, Optional

from .spec import MAX_REQUESTERS


def is_satisfiable(requesters, candidates, satisfies_fn: Callable[[str, str], bool]) -> bool:
    return any(all(satisfies_fn(v, r["range"]) for r in requesters) for v in candidates)


def _compare_requester(a: Dict, b: Dict) -> int:
    if a["id"] < b["id"]:
        return -1
    if a["id"] > b["id"]:
        return 1
    return 0


def _compare_requester_lists(a, b) -> int:
    for ra, rb in zip(a, b):
        c = _compare_requester(ra, rb)
        if c != 0:
            return c
    return (len(a) > len(b)) - (len(a) < len(b))


def find_minimal_conflict_set(
    requesters: List[Dict],
    candidates: List[str],
    satisfies_fn: Callable[[str, str], bool],
    max_requesters: int = MAX_REQUESTERS,
) -> Dict:
    """求 MUS。``requesters`` 每项 ``{id, range}``；返回 ``{minimal_sets, minimal, degraded, reason, searched}``。"""
    total = len(requesters)

    # 单元素：某个请求者的范围自己就无解（R5 形态）
    singles = [r for r in requesters if not any(satisfies_fn(v, r["range"]) for v in candidates)]
    if singles:
        minimal_sets = [[r] for r in singles]
        return {
            "minimal_sets": minimal_sets,
            "minimal": minimal_sets[0],
            "degraded": False,
            "reason": None,
            "searched": 1,
        }

    if total > max_requesters:
        # 显式降级：删除法求**一个**极小冲突集。前提：调用方只在"全量 R 无解"时进来。
        # 不变量：每轮只移除"移除后仍无解"的元素 → 结束时集合无解，且移除任一元素后有解。
        core = list(requesters)
        for r in requesters:
            smaller = [x for x in core if x is not r]
            if smaller and not is_satisfiable(smaller, candidates, satisfies_fn):
                core = smaller
        minimal = sorted(core, key=_cmp_key)
        return {
            "minimal_sets": [minimal],
            "minimal": minimal,
            "degraded": True,
            # 口径固定串（§7.2）：超限必须写这一句。
            "reason": "requesters > max",
            "searched": 0,
        }

    # 按基数升序枚举；极小性显式复核一次，防组合枚举写错
    for k in range(2, total + 1):
        found = []
        for subset in combinations(requesters, k):
            if is_satisfiable(subset, candidates, satisfies_fn):
                continue
            minimal = True
            for idx in range(k):
                smaller = [subset[j] for j in range(k) if j != idx]
                if not is_satisfiable(smaller, candidates, satisfies_fn):
                    minimal = False
                    break
            if minimal:
                found.append(list(subset))
        if found:
            sorted_found = sorted(
                (sorted(s, key=_cmp_key) for s in found), key=_cmp_list_key
            )
            return {
                "minimal_sets": sorted_found,
                "minimal": sorted_found[0],
                "degraded": False,
                "reason": None,
                "searched": k,
            }

    # 全集都无解却找不到更小的 → 理论上不该发生（单元素检查已覆盖）；保守返回全集并标注
    return {
        "minimal_sets": [requesters],
        "minimal": list(requesters),
        "degraded": False,
        "reason": "fallback: full set",
        "searched": total,
    }


def _cmp_key(r: Dict):
    return r["id"]


def _cmp_list_key(lst: List[Dict]):
    return [r["id"] for r in lst]
