"""声明图（照搬旧仓 ``src/model/graph.mjs`` + ``lock-common.mjs`` 的判定相关部分）。

manifest 声明 + 锁中实际条目 → 请求者/被请求者的完整边集。三个关键口径：

1. **解析规则不是"就近取"**：npm 的 node_modules 查找是从请求者目录向上逐级找
   （:func:`resolve_dependency`），否则"谁真正满足了我"会判错。
2. **extraneous 的判据是声明图可达性**，不是 node_modules 是否存在。
3. 每条边都带 ``requester_path``（M2 的命脉）。

输入是输入层规整好的 IR：manifest.deps 四类键 + lock.packages 条目列表。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .spec import ROOT_MARKER


def resolve_dependency(packages_by_path: Dict[str, dict], from_path: str, name: str) -> Optional[str]:
    """从某个包的路径向上找 ``name``（npm 的解析算法；最近者胜）。"""
    scope = "" if from_path == ROOT_MARKER else from_path
    while True:
        candidate = "%s/node_modules/%s" % (scope, name) if scope else "node_modules/%s" % name
        if candidate in packages_by_path:
            return candidate
        if not scope:
            return None
        marker = "/node_modules/"
        idx = scope.rfind(marker)
        scope = "" if idx < 0 else scope[:idx]


def build_graph(manifest: dict, lock: dict) -> Dict:
    """构造图。返回 ``{nodes, edges, reachable}``。

    nodes: ``{path: package_entry}``；edges: 每条声明边；reachable: 从根声明可达的路径集。
    """
    packages: List[dict] = lock.get("packages") or []
    packages_by_path: Dict[str, dict] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            raise ValueError("lock.packages 的每一项必须是对象")
        path = pkg.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("lock.packages 每项必须有非空 path")
        if path == ROOT_MARKER:
            raise ValueError("lock.packages 不应包含根条目（根声明以 subject.manifest 为准）")
        packages_by_path[path] = pkg

    edges: List[dict] = []

    def push_edge(declaring_path: str, kind: str, dependency: str, range_str: str, lock_entry) -> None:
        requester = packages_by_path.get(declaring_path)
        edges.append(
            {
                "declaring_path": declaring_path,
                "declaring_package": requester.get("name") if requester else None,
                "declaring_version": requester.get("version") if requester else None,
                "kind": kind,
                "dependency": dependency,
                "range": range_str,
                "locked_path": lock_entry["path"] if lock_entry else None,
                "locked_version": lock_entry.get("version") if lock_entry else None,
                "optional": kind == "optionalDependencies",
                "peer": kind == "peerDependencies",
            }
        )

    # 根声明（manifest 是根的真相源）
    deps = manifest.get("deps") if isinstance(manifest.get("deps"), dict) else {}
    for kind in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        kind_map = _string_map(deps.get(kind), "manifest.deps.%s" % kind)
        for name in sorted(kind_map):
            locked_path = resolve_dependency(packages_by_path, ROOT_MARKER, name)
            entry = packages_by_path.get(locked_path) if locked_path else None
            push_edge(ROOT_MARKER, kind, name, kind_map[name], entry)

    # 锁中每个条目的声明（传递依赖；dev 是"发布后不存在"，不进图）
    for pkg in packages:
        for field, kind in (("deps", "dependencies"), ("optional_deps", "optionalDependencies"), ("peer_deps", "peerDependencies")):
            kind_map = _string_map(pkg.get(field), "lock.packages.%s.%s" % (pkg["path"], field))
            for name in sorted(kind_map):
                locked_path = resolve_dependency(packages_by_path, pkg["path"], name)
                entry = packages_by_path.get(locked_path) if locked_path else None
                push_edge(pkg["path"], kind, name, kind_map[name], entry)

    reachable = _compute_reachable(edges)
    return {"nodes": packages_by_path, "edges": edges, "reachable": reachable}


def _string_map(value, label: str) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("%s 必须是对象" % label)
    out: Dict[str, str] = {}
    for key in sorted(value):
        entry = value[key]
        if not isinstance(entry, str):
            raise ValueError("%s.%s 必须是字符串" % (label, key))
        out[key] = entry
    return out


def _compute_reachable(edges: List[dict]) -> Set[str]:
    """可达性：从根的声明出发沿边走。缺失边不产生节点，因此不扩展可达集。"""
    by_requester: Dict[str, List[str]] = {}
    for edge in edges:
        if not edge["locked_path"]:
            continue
        by_requester.setdefault(edge["declaring_path"], []).append(edge["locked_path"])
    seen: Set[str] = set()
    stack = list(by_requester.get(ROOT_MARKER, []))
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        seen.add(path)
        stack.extend(by_requester.get(path, []))
    return seen


def path_to_chain(packages_by_path: Dict[str, dict], declaring_path: str) -> List[str]:
    """把路径转成人类可读的请求者链（``["<root>", "send@0.18.0"]`` 形态）。

    链里不带 ``node_modules/`` 前缀（那是实现细节，不是请求者身份）。
    """
    if declaring_path == ROOT_MARKER:
        return [ROOT_MARKER]
    chain: List[str] = []
    scope = declaring_path
    while True:
        marker = "/node_modules/"
        idx = scope.rfind(marker)
        raw_last = scope if idx < 0 else scope[idx + len(marker):]
        last = raw_last[len("node_modules/"):] if raw_last.startswith("node_modules/") else raw_last
        entry = packages_by_path.get(scope)
        version = "@%s" % entry["version"] if entry and entry.get("version") else ""
        chain.insert(0, "%s%s" % (last, version))
        if idx < 0:
            break
        scope = scope[:idx]
    return [ROOT_MARKER] + chain


def group_by_name(edges: List[dict], packages_by_path: Dict[str, dict]) -> Dict[str, Dict[str, List[dict]]]:
    """同一包名的所有锁定版本与请求者（M3/M4 的输入）。

    返回 ``{name: {version: [requester...]}}``；requester 带 ``requester`` /
    ``requester_path`` / ``range`` / ``kind`` / ``locked_path``。
    """
    groups: Dict[str, Dict[str, List[dict]]] = {}
    for edge in edges:
        entry = packages_by_path.get(edge["locked_path"]) if edge["locked_path"] else None
        if not entry:
            continue
        name = entry.get("name")
        version = entry.get("version")
        if not name or not version:
            continue
        chain = path_to_chain(packages_by_path, edge["declaring_path"])
        versions = groups.setdefault(name, {})
        versions.setdefault(version, []).append(
            {
                "requester": " › ".join(chain),
                "requester_path": chain,
                "range": edge["range"],
                "kind": edge["kind"],
                "locked_path": entry["path"],
            }
        )
    return groups


def prerelease_targets_from_lock(lock: dict) -> Dict[str, List[dict]]:
    """R4 需要的预发布目标：从锁中挑出同名的预发布版本。"""
    map_out: Dict[str, List[dict]] = {}
    for pkg in lock.get("packages") or []:
        path = pkg.get("path")
        if path == ROOT_MARKER or not pkg.get("name") or not pkg.get("version"):
            continue
        version = pkg["version"]
        if "-" not in version:
            continue
        head = version.split("-")[0].split("+")[0]
        parts = head.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            continue
        maj, mino, pat = (int(p) for p in parts)
        map_out.setdefault(pkg["name"], []).append(
            {"version": version, "major": maj, "minor": mino, "patch": pat, "is_prerelease": True}
        )
    return map_out
