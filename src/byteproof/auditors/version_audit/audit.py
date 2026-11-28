"""器官 ``version-audit``：npm 版本约束审计账本（迁自 10-27-versionaudit，Node/mjs 源）。

旧仓 ``versionaudit`` 把 npm 的版本范围当一等公民：范围语义风险（R1–R8）、锁与
manifest 的双向不一致（带请求者路径）、重复版本收敛可行性的证明与最小冲突集、
冲突的最小解释。本器官照搬五个判定模块（range-lint / lock-manifest / dedupe /
conflict / MUS）与自研区间代数 + semver 语义核心；把 package.json / package-lock.json
的文件读取、v1/v2/v3 解析、报告排版与写盘、Node 运行环境检查留给输入层。

**没有搬**：CLI（doctor/audit 子命令、--format/--out/--fail-on）、SARIF/文本排版、
`--severity-map` 覆盖表、`node --version` 环境门（器官禁读环境变量）、与 semver 库的
差分自检（跨语言重写后无第二实现；语义保真由旧仓 14 组差分向量期望值承担）。

**等级与阻断**：旧仓 error 级结论（R5 空交集、manifest-not-satisfied、
missing-from-lock、manifest-changed-unsynced、NOT_CONVERGIBLE、peer/version-conflict）
在本器官仍是 error（账本唯一阻断档）；warning（R1/R2/R4/R6、lock-extra-undeclared、
lock-outdated、REQUIRES_OVERRIDE）与 info（R3/R7/R8、CONVERGIBLE）不阻断。
旧仓退出码 2（--fail-on=warning）映射为本账本的 0（warn 不阻断）；旧 3（输入不可解析）
映射为 2（subject 不是合法 IR）；旧 4/5 无对应物（差分自检 / 环境门，见 docs §7）。
"""

from __future__ import annotations

from typing import Iterable, List, Mapping

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import conflict as conflict_mod
from . import dedupe as dedupe_mod
from . import graph as graph_mod
from . import lint as lint_mod
from . import lockcheck as lockcheck_mod
from . import spec


def evaluate(subject: Mapping, basis) -> Iterable[Record]:
    """账本入口：subject = {mode, manifest, lock, options?}。

    ``mode`` 缺省 ``audit``（四个判定模块一次跑完）；``manifest`` / ``lock`` 是输入层
    规整好的 IR。规则依据一律走 ``basis.ref(rule_id)``。
    """
    mode = _mode_of(subject)
    manifest = _manifest_ir(subject)
    lock = _lock_ir(subject)
    options = _options_of(subject)

    records: List[Record] = []
    blocking = 0

    graph = None
    if mode in ("audit", "range-lint"):
        declarations = flatten_declarations(manifest)
        findings = lint_mod.run_range_lint(
            manifest,
            declarations,
            severity_table=None,
            enable_r8=options["enable_r8"],
            prerelease_targets=graph_mod.prerelease_targets_from_lock(lock),
        )
        for index, finding in enumerate(findings):
            rule_id = spec.RULE_BY_LINT[finding["rule"]]
            records.append(
                Record(
                    rule_id=rule_id,
                    verdict=spec.SEVERITY_TO_VERDICT[finding["severity"]],
                    message=finding["evidence"],
                    basis=basis.ref(rule_id),
                    path="manifest.deps.%s.%s" % (finding["declaration"], finding["package"]),
                    evidence=_evidence_of(finding),
                )
            )
            blocking += 1 if finding["severity"] == "error" else 0

    if mode in ("audit", "lock-manifest", "dedupe", "conflict"):
        graph = graph_mod.build_graph(manifest, lock)

    if mode in ("audit", "lock-manifest"):
        result = lockcheck_mod.run_lock_manifest_check(manifest, lock, graph, strict=options["strict"])
        for finding in result["findings"]:
            rule_id = spec.RULE_BY_LOCK[finding["kind"]]
            path = _lock_path_of(finding)
            records.append(
                Record(
                    rule_id=rule_id,
                    verdict=spec.SEVERITY_TO_VERDICT[finding["severity"]],
                    message=finding["explanation"],
                    basis=basis.ref(rule_id),
                    path=path,
                    evidence={
                        "kind": finding["kind"],
                        "declaring_package": finding["declaring_package"],
                        "declaring_path": list(finding["declaring_path"]),
                        "dependency": finding["dependency"],
                        "declared_range": finding["declared_range"],
                        "locked_version": finding["locked_version"],
                        "requester_path": list(finding["requester_path"]),
                        "severity": finding["severity"],
                    },
                )
            )
            blocking += 1 if finding["severity"] == "error" else 0
        for degradation in result["degradations"]:
            records.append(
                Record(
                    rule_id=spec.RULE_LOCK_ENTRY_NO_VERSION,
                    verdict=INFO,
                    message=degradation,
                    basis=basis.ref(spec.RULE_LOCK_ENTRY_NO_VERSION),
                    path="lock.degradation[%d]" % len([r for r in records if r.rule_id == spec.RULE_LOCK_ENTRY_NO_VERSION]),
                    evidence={"degraded": True},
                )
            )

    if mode in ("audit", "dedupe"):
        results = dedupe_mod.run_dedupe_feasibility(
            graph,
            max_requesters=options["max_requesters"],
            prefer=options["prefer"],
        )
        for item in results:
            rule_id = {
                "CONVERGIBLE": spec.RULE_CONVERGIBLE,
                "REQUIRES_OVERRIDE": spec.RULE_REQUIRES_OVERRIDE,
                "NOT_CONVERGIBLE": spec.RULE_NOT_CONVERGIBLE,
            }[item["status"]]
            records.append(
                Record(
                    rule_id=rule_id,
                    verdict=spec.SEVERITY_TO_VERDICT[item["severity"]],
                    message=_dedupe_message(item),
                    basis=basis.ref(rule_id),
                    path="dedupe.%s" % item["package"],
                    evidence={
                        "package": item["package"],
                        "status": item["status"],
                        "locked_versions": list(item["locked_versions"]),
                        "requesters": item["requesters"],
                        "targets": [_target_evidence(t) for t in item["targets"]],
                        "minimal_conflict_set": item["minimal_conflict_set"],
                        "minimal_conflict_sets": item.get("minimal_conflict_sets"),
                        "reason": item["reason"],
                        "degraded": item["degraded"],
                        "degrade_reason": item.get("degrade_reason"),
                        "suggestion": item.get("suggestion"),
                        "severity": item["severity"],
                    },
                )
            )
            blocking += 1 if item["severity"] == "error" else 0

    if mode in ("audit", "conflict"):
        conflicts = conflict_mod.run_conflict_explain(
            graph,
            max_requesters=options["max_requesters"],
            ignore_peer=options["ignore_peer"],
        )
        for item in conflicts:
            rule_id = spec.RULE_PEER_CONFLICT if item["kind"] == "peer-conflict" else spec.RULE_VERSION_CONFLICT
            records.append(
                Record(
                    rule_id=rule_id,
                    verdict=spec.SEVERITY_TO_VERDICT[item["severity"]],
                    message=item["explanation"],
                    basis=basis.ref(rule_id),
                    path="conflicts.%s.%s" % (item["kind"], item.get("declaring_path") or item["package"]),
                    evidence={
                        "kind": item["kind"],
                        "package": item["package"],
                        "locked_version": item["locked_version"],
                        "minimal_set": item["minimal_set"],
                        "requesters": item.get("requesters"),
                        "conflict_proof": item["conflict_proof"],
                        "degraded": item.get("degraded", False),
                        "degrade_reason": item.get("degrade_reason"),
                        "downgraded_by": item.get("downgraded_by"),
                        "severity": item["severity"],
                    },
                )
            )
            blocking += 1 if item["severity"] == "error" else 0

    counts = {verdict: 0 for verdict in (ERROR, WARN, INFO)}
    for record in records:
        counts[record.verdict] += 1
    records.append(
        Record(
            rule_id=spec.RULE_SUMMARY,
            verdict=INFO,
            message="mode=%s：error=%d warn=%d info=%d（阻断 %d 条，旧仓默认 --fail-on=error 语义）"
            % (mode, counts[ERROR], counts[WARN], counts[INFO], blocking),
            basis=basis.ref(spec.RULE_SUMMARY),
            path="summary",
            evidence={
                "mode": mode,
                "error": counts[ERROR],
                "warn": counts[WARN],
                "info": counts[INFO],
                "blocking": blocking,
            },
        )
    )
    return records


# ------------------------------------------------------------------ 输入规整
def _mode_of(subject) -> str:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if not isinstance(mode, str) or mode not in spec.MODES:
        raise ValueError("subject.mode 必须是 %s 之一" % "|".join(spec.MODES))
    return mode


def _manifest_ir(subject) -> dict:
    manifest = subject.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("subject.manifest 必须是对象")
    name = manifest.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError("manifest.name 必须是字符串或 null")
    deps_raw = manifest.get("deps")
    if deps_raw is None:
        deps_raw = {}
    if not isinstance(deps_raw, dict):
        raise ValueError("manifest.deps 必须是对象")
    deps = {}
    for kind in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        kind_map = deps_raw.get(kind)
        if kind_map is None:
            kind_map = {}
        if not isinstance(kind_map, dict):
            raise ValueError("manifest.deps.%s 必须是对象" % kind)
        checked = {}
        for dep_name in sorted(kind_map):
            value = kind_map[dep_name]
            if not isinstance(value, str):
                raise ValueError("manifest.deps.%s.%s 必须是字符串" % (kind, dep_name))
            checked[dep_name] = value
        deps[kind] = checked
    overrides = _opt_string_map(manifest.get("overrides"), "manifest.overrides")
    resolutions = _opt_string_map(manifest.get("resolutions"), "manifest.resolutions")
    return {"name": name, "deps": deps, "overrides": overrides, "resolutions": resolutions}


def _lock_ir(subject) -> dict:
    lock = subject.get("lock")
    if not isinstance(lock, dict):
        raise ValueError("subject.lock 必须是对象")
    packages_raw = lock.get("packages")
    if packages_raw is None:
        packages_raw = []
    if not isinstance(packages_raw, list):
        raise ValueError("lock.packages 必须是数组")
    packages = []
    for pkg in packages_raw:
        if not isinstance(pkg, dict):
            raise ValueError("lock.packages 的每一项必须是对象")
        path = pkg.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError("lock.packages 每项必须有非空 path")
        if path == spec.ROOT_MARKER:
            raise ValueError("lock.packages 不应包含根条目（根声明以 subject.manifest 为准）")
        version = pkg.get("version")
        if version is not None and not isinstance(version, str):
            raise ValueError("lock.packages[].version 必须是字符串或 null")
        packages.append(
            {
                "path": path,
                "name": pkg.get("name"),
                "version": version,
                "deps": _opt_string_map(pkg.get("deps"), "lock.packages[%s].deps" % path),
                "dev_deps": _opt_string_map(pkg.get("dev_deps"), "lock.packages[%s].dev_deps" % path),
                "peer_deps": _opt_string_map(pkg.get("peer_deps"), "lock.packages[%s].peer_deps" % path),
                "optional_deps": _opt_string_map(pkg.get("optional_deps"), "lock.packages[%s].optional_deps" % path),
                "link": pkg.get("link") is True,
            }
        )
    root_manifest = _opt_string_map(lock.get("root_manifest_deps"), "lock.root_manifest_deps")
    root_optional = _opt_string_map(lock.get("root_optional_deps"), "lock.root_optional_deps")
    return {
        "packages": packages,
        "root_manifest_deps": root_manifest,
        "root_optional_deps": root_optional,
    }


def _options_of(subject) -> dict:
    raw = subject.get("options")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("subject.options 必须是对象")
    prefer = raw.get("prefer")
    if prefer is not None and prefer not in ("latest", "min-change"):
        raise ValueError("options.prefer 必须是 latest|min-change|null")
    max_requesters = raw.get("max_requesters", spec.MAX_REQUESTERS)
    if not isinstance(max_requesters, int) or isinstance(max_requesters, bool) or max_requesters < 1:
        raise ValueError("options.max_requesters 必须是正整数")
    return {
        "enable_r8": raw.get("enable_r8") is True,
        "strict": raw.get("strict") is True,
        "ignore_peer": raw.get("ignore_peer") is True,
        "max_requesters": max_requesters,
        "prefer": prefer,
    }


def _opt_string_map(value, label: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("%s 必须是对象" % label)
    out = {}
    for key in sorted(value):
        entry = value[key]
        if not isinstance(entry, str):
            raise ValueError("%s.%s 必须是字符串" % (label, key))
        out[key] = entry
    return out


def flatten_declarations(manifest: dict) -> List[dict]:
    """展平成 (kind, name, range) 列表，供规则逐条遍历（顺序稳定）。"""
    out = []
    for kind in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        for name in manifest["deps"][kind]:
            out.append({"kind": kind, "name": name, "raw_range": manifest["deps"][kind][name]})
    for name in manifest["overrides"]:
        out.append({"kind": "overrides", "name": name, "raw_range": manifest["overrides"][name]})
    for name in manifest["resolutions"]:
        out.append({"kind": "resolutions", "name": name, "raw_range": manifest["resolutions"][name]})
    return out


def _evidence_of(finding: dict) -> dict:
    evidence = {
        "rule": finding["rule"],
        "package": finding["package"],
        "declaration": finding["declaration"],
        "raw_range": finding["raw_range"],
        "expanded_range": finding["expanded_range"],
        "severity": finding["severity"],
    }
    if finding.get("details") is not None:
        evidence["details"] = finding["details"]
    if finding.get("not_a_range"):
        evidence["not_a_range"] = True
    return evidence


def _lock_path_of(finding: dict) -> str:
    kind = finding["kind"]
    if kind in ("manifest-not-satisfied", "missing-from-lock", "lock-outdated"):
        return "lock.edges[%s → %s]" % (finding["declaring_path"][-1] if finding["declaring_path"] else "-", finding["dependency"])
    if kind == "manifest-changed-unsynced":
        return "lock.root.%s.%s" % (finding.get("root_kind", "dependencies"), finding["dependency"])
    if kind == "lock-extra-undeclared":
        return "lock.packages.%s" % finding.get("locked_path", finding["dependency"] or "?")
    raise ValueError("未知 M2 kind：%s" % kind)


def _dedupe_message(item: dict) -> str:
    status = item["status"]
    if status == "CONVERGIBLE":
        return "%s：%d 个已锁定版本全部满足全部请求者 → 可收敛；可行目标 %s" % (
            item["package"],
            len(item["locked_versions"]),
            "、".join(t["version"] for t in item["targets"]) or "（无）",
        )
    note = "超限降级（%s）；" % item["degrade_reason"] if item.get("degraded") else ""
    return "%s：%s%d 条请求者无共同可满足版本（%s）→ 最小冲突集 %d 条" % (
        item["package"],
        note,
        item["requesters"],
        item["reason"],
        len(item["minimal_conflict_set"]),
    )


def _target_evidence(target: dict) -> dict:
    return {
        "version": target["version"],
        "preferred": target.get("preferred", False),
        "proof": [{"requester": p["requester"], "range": p["range"], "satisfies": p["satisfies"]} for p in target["proof"]],
    }
