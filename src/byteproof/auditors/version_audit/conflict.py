"""M4 ``conflict-explain`` —— 冲突的最小请求者集合（照搬旧仓 ``src/checks/conflict.mjs``）。

复用 M3 的 MUS 内核（K4），不另写一套。两种 kind：
  - ``peer-conflict``    ：peer 声明与实际提供者不匹配
  - ``version-conflict`` ：同一被依赖包的多条声明互相冲突且无已锁定解

可机械校验的属性：``minimal_set`` 去掉任一元素后冲突消失。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import interval
from . import semver_core
from .dedupe import intersect_ranges_safe
from .graph import group_by_name, path_to_chain
from .mus import find_minimal_conflict_set
from .spec import CONFLICT_SEVERITY, MAX_REQUESTERS, SEVERITY_TO_VERDICT


def _conflict_severity(kind: str, severity_table: Optional[Dict]) -> str:
    if severity_table and kind in severity_table:
        return severity_table[kind]
    return CONFLICT_SEVERITY.get(kind, "info")


def run_conflict_explain(
    graph: Dict,
    severity_table: Optional[Dict] = None,
    max_requesters: int = MAX_REQUESTERS,
    ignore_peer: bool = False,
) -> List[Dict]:
    table = severity_table or {}
    conflicts: List[Dict] = []
    nodes = graph["nodes"]

    # ── peer 冲突 ─────────────────────────────────────────────────────────────
    for path in sorted(nodes):
        pkg = nodes[path]
        if not pkg.get("name") or not pkg.get("peer_deps"):
            continue
        peer_deps = _string_map(pkg.get("peer_deps"))
        chain = path_to_chain(nodes, path)
        for name in sorted(peer_deps):
            peer_range = peer_deps[name]
            # 从上层的视角看谁提供了这个包
            provider_edge = _find_provider_edge(graph["edges"], name, path)
            if provider_edge is None:
                severity = "info" if ignore_peer else _conflict_severity("peer-conflict", table)
                conflict = {
                    "kind": "peer-conflict",
                    "declaring_path": path,
                    "package": name,
                    "severity": severity,
                    "verdict": SEVERITY_TO_VERDICT[severity],
                    "locked_version": None,
                    "minimal_set": [
                        {
                            "requester": "%s@%s" % (pkg["name"], pkg.get("version") or "?"),
                            "range": peer_range,
                            "path": chain,
                        }
                    ],
                    "conflict_proof": {
                        "ranges": [peer_range],
                        "intersects": False,
                        "computed_by": "absence",
                    },
                    "explanation": "UNMET peer：%s@%s 需要 %s@%s，树中无提供者"
                    % (pkg["name"], pkg.get("version") or "?", name, peer_range),
                }
                if ignore_peer:
                    conflict["downgraded_by"] = "--ignore-peer"
                conflicts.append(conflict)
                continue
            if semver_core.satisfies(provider_edge["locked_version"], peer_range):
                continue

            provider_chain = path_to_chain(nodes, provider_edge["declaring_path"])
            provider_node = nodes.get(provider_edge["declaring_path"])
            minimal_set = _dedupe_by_id(
                [
                    {
                        "requester": "%s@%s" % (pkg["name"], pkg.get("version") or "?"),
                        "range": peer_range,
                        "path": chain,
                    },
                    {
                        "requester": "%s@%s"
                        % (
                            provider_edge["declaring_package"] or "<root>",
                            provider_node.get("version") if provider_node else "?",
                        ),
                        "range": provider_edge["range"],
                        "path": provider_chain,
                    },
                ]
            )
            severity = "info" if ignore_peer else _conflict_severity("peer-conflict", table)
            conflict = {
                "kind": "peer-conflict",
                "declaring_path": path,
                "package": name,
                "severity": severity,
                "verdict": SEVERITY_TO_VERDICT[severity],
                "locked_version": provider_edge["locked_version"],
                "minimal_set": minimal_set,
                "conflict_proof": _pairwise_proof([m["range"] for m in minimal_set]),
                "explanation": "%s@%s 需要 %s@%s，实际提供 %s"
                % (pkg["name"], pkg.get("version") or "?", name, peer_range, provider_edge["locked_version"]),
            }
            if ignore_peer:
                conflict["downgraded_by"] = "--ignore-peer"
            conflicts.append(conflict)

    # ── version 冲突（同名多声明无共同已锁定解）────────────────────────────────
    groups = group_by_name(graph["edges"], nodes)
    for name in sorted(groups):
        version_map = groups[name]
        if len(version_map) < 2:
            continue
        candidates = list(version_map.keys())
        requesters = []
        for version in sorted(version_map):
            for req in version_map[version]:
                requesters.append(
                    {
                        "id": "%s|%s" % (req["requester"], req["range"]),
                        "requester": req["requester"],
                        "range": req["range"],
                        "path": req["requester_path"],
                    }
                )
        unique = _dedupe_by_id(sorted(requesters, key=lambda r: r["id"]))
        if len(unique) < 2:
            continue
        if any(all(semver_core.satisfies(v, r["range"]) for r in unique) for v in candidates):
            continue

        # 复用 M3 的 MUS 内核（K4）：minimalSet 必须是**最小**冲突集，不是全量请求者
        mus = find_minimal_conflict_set(
            [{"id": r["id"], "range": r["range"]} for r in unique],
            candidates,
            semver_core.satisfies,
            max_requesters=max_requesters,
        )
        by_id = {r["id"]: r for r in unique}
        minimal_requesters = [
            {"requester": by_id[m["id"]]["requester"], "range": by_id[m["id"]]["range"], "path": by_id[m["id"]]["path"]}
            for m in mus["minimal"]
        ]

        intersection = intersect_ranges_safe([r["range"] for r in minimal_requesters])
        severity = _conflict_severity("version-conflict", table)
        conflict = {
            "kind": "version-conflict",
            "package": name,
            "severity": severity,
            "verdict": SEVERITY_TO_VERDICT[severity],
            "locked_version": None,
            "minimal_set": minimal_requesters,
            "requesters": len(unique),
            "conflict_proof": {
                "ranges": [r["range"] for r in minimal_requesters],
                "intersects": _pairwise_proof([r["range"] for r in minimal_requesters])["intersects"],
                "computed_by": "interval",
                "reason": "empty-intersection" if intersection["empty"] is True else "no-locked-candidate",
            },
            "explanation": "%s 有 %d 条互相冲突的声明；最小冲突集为其中 %d 条，且无任何已锁定版本可同时满足"
            % (name, len(unique), len(minimal_requesters)),
            "degraded": mus["degraded"],
        }
        if mus["degraded"]:
            conflict["degrade_reason"] = mus["reason"]
        conflicts.append(conflict)

    return sort_conflicts(conflicts)


def _find_provider_edge(edges: List[Dict], name: str, excluding_path: str) -> Optional[Dict]:
    for edge in edges:
        if edge["dependency"] == name and edge["declaring_path"] != excluding_path and edge["locked_path"] is not None:
            return edge
    return None


def _string_map(value) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(v, str)}


def _dedupe_by_id(items: List[Dict]) -> List[Dict]:
    seen = set()
    out = []
    for item in items:
        key = "%s|%s" % (item["requester"], item["range"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _pairwise_proof(ranges: List[str]) -> Dict:
    """两两相交证明（取前两条）。旧仓用 semver.intersects 做交叉复核；器官内只有
    一套区间实现（差分对照不迁），``cross_checked`` 恒为 None 并在 docs 登记口径差。"""
    if len(ranges) < 2:
        return {"ranges": list(ranges), "intersects": False, "computed_by": "interval", "cross_checked": None}
    all_intersect = True
    for i in range(len(ranges)):
        if not all_intersect:
            break
        for j in range(i + 1, len(ranges)):
            a = semver_core.intersects(ranges[i], ranges[j])
            try:
                b = interval.intersect_ranges([ranges[i], ranges[j]])["empty"] is not True
            except Exception:
                b = False
            if not a:
                all_intersect = False
                break
    return {"ranges": ranges[:2], "intersects": all_intersect, "computed_by": "interval", "cross_checked": None}


def sort_conflicts(conflicts: List[Dict]) -> List[Dict]:
    def key(c: Dict):
        return (
            c["kind"],
            c["package"],
            "/".join(m["requester"] for m in c["minimal_set"]),
        )

    return sorted(conflicts, key=key)
