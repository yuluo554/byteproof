"""M2 ``lock-manifest-check`` —— 双向一致性（照搬旧仓 ``src/checks/lock-manifest.mjs``）。

核心承诺：每条 finding 都带 ``declaring_package`` / ``declared_range`` / ``requester_path``
——``npm ci`` 只给目标版本，范围与来源都没有。

两条实测口径（照搬台账 A22/A23/A24）：
  - 根条目四类键**各写各的**，逐类对比同一类键（dev 不参与比对）；
  - 锁条目无 version（link/optional 占位）是"无法判定"，不是"不满足" —— 记降级不记错。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import semver_core
from .graph import path_to_chain
from .spec import LOCK_SEVERITY, ROOT_MARKER, SEVERITY_TO_VERDICT


def _lock_severity(kind: str, severity_table: Optional[Dict]) -> str:
    if severity_table and kind in severity_table:
        return severity_table[kind]
    return LOCK_SEVERITY.get(kind, "info")


def run_lock_manifest_check(
    manifest: dict,
    lock: dict,
    graph: Dict,
    severity_table: Optional[Dict] = None,
    strict: bool = False,
) -> Dict:
    """跑双向一致性。返回 ``{findings, degradations}``。

    ``degradations`` 非空 = "有判定做不了"（当前只有一类：锁条目无 ``version``），
    缺省也该进报告的 ``degraded``（K8：任何降级必须显式，不许静默近似）。
    """
    table = severity_table or {}
    degradations: List[str] = []
    findings: List[Dict] = []

    def push(finding: Dict) -> None:
        severity = _lock_severity(finding["kind"], table)
        finding = dict(finding)
        finding["severity"] = severity
        finding["verdict"] = SEVERITY_TO_VERDICT[severity]
        findings.append(finding)

    manifest_name = manifest.get("name")
    nodes = graph["nodes"]

    # ── 1. manifest-not-satisfied / missing-from-lock ─────────────────────────
    for edge in graph["edges"]:
        chain = path_to_chain(nodes, edge["declaring_path"])
        if edge["declaring_path"] == ROOT_MARKER:
            declaring_package = manifest_name if manifest_name else "<root>"
        else:
            entry = nodes.get(edge["declaring_path"])
            declaring_package = "%s@%s" % (
                entry.get("name") if entry else "?",
                entry.get("version") if entry else "?",
            )

        if not edge["locked_path"]:
            if edge["optional"]:
                continue  # optional 缺了不算错（plan/03 M2 判据）
            push(
                {
                    "kind": "missing-from-lock",
                    "declaring_package": declaring_package,
                    "declaring_path": chain,
                    "dependency": edge["dependency"],
                    "declared_range": edge["range"],
                    "locked_version": None,
                    "requester_path": chain,
                    "explanation": "%s 声明 %s@%s，锁中无对应条目"
                    % (declaring_package, edge["dependency"], edge["range"]),
                }
            )
            continue

        # `latest` 等 dist-tag 不是 semver 范围：跳过 satisfies 判定，把判定交给 R2
        declared_expanded = semver_core.valid_range(edge["range"])
        if declared_expanded is None:
            continue

        # 锁中条目没有版本时不得制造"不满足"（台账 A23）：那是"无法判定"
        if edge["locked_version"] is None:
            degradations.append(
                "%s（%s）：锁中条目无 version 字段（link/optional 占位），无法判定是否满足 %s"
                % (edge["dependency"], " › ".join(chain), edge["range"])
            )
            continue

        if not semver_core.satisfies(edge["locked_version"], edge["range"]):
            push(
                {
                    "kind": "manifest-not-satisfied",
                    "declaring_package": declaring_package,
                    "declaring_path": chain,
                    "dependency": edge["dependency"],
                    "declared_range": edge["range"],
                    "locked_version": edge["locked_version"],
                    "requester_path": chain,
                    "explanation": "%s 声明 %s@%s，锁中解析为 %s"
                    % (declaring_package, edge["dependency"], edge["range"], edge["locked_version"]),
                }
            )
            continue

        # --strict：锁中版本 vs 声明下界所指最小版本 → lock-outdated（默认不判）
        if strict:
            minimum = _min_version_of(edge["range"])
            if minimum and edge["locked_version"] != minimum:
                push(
                    {
                        "kind": "lock-outdated",
                        "declaring_package": declaring_package,
                        "declaring_path": chain,
                        "dependency": edge["dependency"],
                        "declared_range": edge["range"],
                        "locked_version": edge["locked_version"],
                        "requester_path": chain,
                        "explanation": "--strict：声明下界为 %s，锁中为 %s（默认档不判\"过期 vs 有意 override\"）"
                        % (minimum, edge["locked_version"]),
                    }
                )

    # ── 2. manifest-changed-unsynced ─────────────────────────────────────────
    # 最接近 npm ci 的基线对照：lock 根条目的各声明键 vs manifest，逐类对比。
    root_pairs = [
        ("dependencies", lock.get("root_manifest_deps") or {}, (manifest.get("deps") or {}).get("dependencies") or {}),
        ("optionalDependencies", lock.get("root_optional_deps") or {}, (manifest.get("deps") or {}).get("optionalDependencies") or {}),
    ]
    has_lock_root_deps = bool(root_pairs[0][1]) or bool(root_pairs[1][1])
    if has_lock_root_deps:
        for kind, lock_map, manifest_map in root_pairs:
            keys = sorted(set(list(lock_map.keys()) + list(manifest_map.keys())))
            for name in keys:
                in_lock = lock_map.get(name)
                in_manifest = manifest_map.get(name)
                if in_lock == in_manifest:
                    continue
                if in_manifest is None:
                    explanation = "锁中根 %s 有 %s@%s，manifest 已删除该声明" % (kind, name, in_lock)
                elif in_lock is None:
                    explanation = "manifest 声明 %s@%s，锁中根 %s 缺失（npm ci 会 EUSAGE）" % (name, in_manifest, kind)
                else:
                    explanation = "manifest 声明 %s@%s，锁中根 %s 为 %s@%s" % (name, in_manifest, kind, name, in_lock)
                push(
                    {
                        "kind": "manifest-changed-unsynced",
                        "root_kind": kind,
                        "declaring_package": manifest_name if manifest_name else "<root>",
                        "declaring_path": [ROOT_MARKER],
                        "dependency": name,
                        "declared_range": in_manifest,
                        "locked_version": in_lock,
                        "requester_path": [ROOT_MARKER],
                        "explanation": explanation,
                    }
                )

    # ── 3. lock-extra-undeclared ─────────────────────────────────────────────
    # 判据 = 声明图可达性。跳过：根条目、树外路径（链接目标体）、link 条目。
    for path in sorted(nodes):
        pkg = nodes[path]
        if path == ROOT_MARKER:
            continue
        if not path.startswith("node_modules/"):
            continue
        if pkg.get("link"):
            continue
        if path in graph["reachable"]:
            continue
        push(
            {
                "kind": "lock-extra-undeclared",
                "locked_path": path,
                "declaring_package": None,
                "declaring_path": [],
                "dependency": pkg.get("name") or "?",
                "declared_range": None,
                "locked_version": pkg.get("version"),
                "requester_path": [],
                "explanation": "锁中 %s 在 manifest 可达图里没有任何请求者（基于声明图，不依赖 node_modules 实际存在）" % path,
            }
        )

    return {"findings": sort_m2(findings), "degradations": degradations}


def _min_version_of(range_str: str) -> Optional[str]:
    """声明范围下界所指的最小版本（只在 --strict 用；不装新依赖，用展开结果自行取）。"""
    expanded = semver_core.valid_range(range_str)
    if expanded is None:
        return None
    first = expanded.split("||")[0].strip()
    comps = [c for c in first.split() if c]
    best = None
    for comp in comps:
        m = _RE_STRICT_LOWER.match(comp)
        if not m:
            continue
        op = m.group(1) or "="
        if op not in ("=", ">=", "^", "~"):
            continue
        v = _normalize_to3(m.group(2))
        if not v:
            continue
        if best is None or _compare_tuple(v, best) > 0:
            best = v
    return ".".join(str(part) for part in best) if best else None


_RE_STRICT_LOWER = __import__("re").compile(r"^(>=|\^|~|=)?(.+)$")


def _normalize_to3(v: str):
    m = _RE_V3.match(v)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


_RE_V3 = __import__("re").compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def _compare_tuple(a, b) -> int:
    for x, y in zip(a, b):
        if x != y:
            return -1 if x < y else 1
    return 0


def sort_m2(findings: List[Dict]) -> List[Dict]:
    """稳定排序：kind → requester_path → dependency → locked_version（照搬旧仓）。"""
    def key(f: Dict):
        return (
            f["kind"],
            "/".join(f.get("requester_path") or []),
            f["dependency"] or "",
            str(f.get("locked_version") or ""),
        )

    return sorted(findings, key=key)
