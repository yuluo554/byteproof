"""M3 ``dedupe-feasibility`` —— 收敛可行性三态（照搬旧仓 ``src/checks/dedupe.mjs``）。

判定顺序**固定**（K3）：CONVERGIBLE → 求 MUS → REQUIRES_OVERRIDE / NOT_CONVERGIBLE。

两条诚实性约束（照搬）：
  - ``CONVERGIBLE`` 的判据是**实际候选版本 satisfies 全部请求者**，不是"区间非空"；
  - 无候选但区间非空 → ``reason: "no-locked-candidate"``；区间本身为空 →
    ``"empty-intersection"``。两者**不许合并陈述**。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import interval
from . import semver_core
from .graph import group_by_name
from .mus import find_minimal_conflict_set
from .spec import DEDUPE_SEVERITY, MAX_REQUESTERS, SEVERITY_TO_VERDICT


def _dedupe_severity(status: str, severity_table: Optional[Dict]) -> str:
    if severity_table and status in severity_table:
        return severity_table[status]
    return DEDUPE_SEVERITY.get(status, "info")


def run_dedupe_feasibility(
    graph: Dict,
    severity_table: Optional[Dict] = None,
    max_requesters: int = MAX_REQUESTERS,
    prefer: Optional[str] = None,
) -> List[Dict]:
    """对同名多版本的包逐个判定。``--prefer`` 只改排序与标注，不改可行性（§7.4）。"""
    table = severity_table or {}
    groups = group_by_name(graph["edges"], graph["nodes"])
    results: List[Dict] = []

    for name in sorted(groups):
        version_map = groups[name]
        if len(version_map) < 2:
            continue  # 单版本无"去重"问题

        locked_versions = interval.sort_versions(list(version_map.keys()))
        requesters = []
        for version in sorted(version_map):
            for req in version_map[version]:
                requesters.append(
                    {
                        "id": "%s|%s|%s" % (req["requester"], req["range"], req["locked_path"]),
                        "requester": req["requester"],
                        "requester_path": req["requester_path"],
                        "range": req["range"],
                        "kind": req["kind"],
                        "locked_path": req["locked_path"],
                        "locked_version": version,
                    }
                )
        sorted_requesters = sorted(requesters, key=lambda r: r["id"])

        # 1. CONVERGIBLE：对每个已锁定版本实算
        targets = []
        for version in locked_versions:
            if all(semver_core.satisfies(version, r["range"]) for r in sorted_requesters):
                targets.append(
                    {
                        "version": version,
                        "proof": [
                            {
                                "requester": r["requester"],
                                "range": r["range"],
                                "satisfies": semver_core.satisfies(version, r["range"]),
                            }
                            for r in sorted_requesters
                        ],
                    }
                )

        if targets:
            severity = _dedupe_severity("CONVERGIBLE", table)
            results.append(
                {
                    "package": name,
                    "status": "CONVERGIBLE",
                    "severity": severity,
                    "verdict": SEVERITY_TO_VERDICT[severity],
                    "locked_versions": locked_versions,
                    "targets": _order_targets(targets, prefer),
                    "requesters": len(sorted_requesters),
                    "minimal_conflict_set": None,
                    "degraded": False,
                    "reason": None,
                }
            )
            continue

        # 2. 求 MUS（复用唯一实现 K4）
        candidates = locked_versions
        mus = find_minimal_conflict_set(
            [{"id": r["id"], "range": r["range"]} for r in sorted_requesters],
            candidates,
            semver_core.satisfies,
            max_requesters=max_requesters,
        )

        intersection = intersect_ranges_safe([r["range"] for r in sorted_requesters])
        status = "REQUIRES_OVERRIDE" if len(mus["minimal"]) < len(sorted_requesters) else "NOT_CONVERGIBLE"
        severity = _dedupe_severity(status, table)
        by_id = {r["id"]: r for r in sorted_requesters}

        def mus_item(m: Dict) -> Dict:
            original = by_id[m["id"]]
            return {
                "requester": original["requester"],
                "range": original["range"],
                "requester_path": original["requester_path"],
            }

        item = {
            "package": name,
            "status": status,
            "severity": severity,
            "verdict": SEVERITY_TO_VERDICT[severity],
            "locked_versions": locked_versions,
            "targets": [],
            "requesters": len(sorted_requesters),
            "minimal_conflict_set": [mus_item(m) for m in mus["minimal"]],
            "degraded": mus["degraded"],
            "reason": "empty-intersection" if intersection["empty"] is True else "no-locked-candidate",
        }
        if len(mus["minimal_sets"]) > 1:
            item["minimal_conflict_sets"] = [[mus_item(m) for m in s] for s in mus["minimal_sets"]]
        if status == "REQUIRES_OVERRIDE":
            item["suggestion"] = {
                "nature": "suggestion",
                "note": "放宽 minimalConflictSet 中的声明即可收敛；本工具不替用户决定改哪一条",
            }
        if mus["degraded"]:
            item["degrade_reason"] = mus["reason"]
        results.append(item)

    return results


def intersect_ranges_safe(ranges: List[str]) -> Dict:
    """区间求交；非法范围按"非空、无候选"处理（R2 已报过非范围）。"""
    result = interval.intersect_ranges(ranges)
    if result["empty"] is None:
        return {"empty": False, "branches": []}
    return result


def _order_targets(targets: List[Dict], prefer: Optional[str]) -> List[Dict]:
    if prefer == "latest":
        ordered = list(reversed(targets))
        return [dict(t, preferred=i == 0) for i, t in enumerate(ordered)]
    if prefer == "min-change":
        # "最小变更"= 目标越接近现存已锁定的最小版本，变更越小；只标注不改集合
        return [dict(t, preferred=i == 0) for i, t in enumerate(targets)]
    return targets
