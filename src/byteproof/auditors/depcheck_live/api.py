"""编排层（迁自旧仓 ``src/api.mjs`` 的 check/drift 主流程 + 账本化）。

纯函数：``evaluate(subject, basis) -> Iterable[Record]``。不碰退出码、不写文件、
不读文件系统——旧仓 ``decideExit`` 的三态（0/1/3）在账本模型里收敛为两值退出码：

| 旧仓情形 | 旧 rc | 新账本 | 新 rc |
|---|---:|---|---:|
| 无问题（含仅 AMBIGUOUS，显式计数） | 0 | 只有 info 级记录 | 0 |
| 发现判定问题（MISSING-EXPORT / ESM-CJS-MISMATCH / NOT-EXPORTED-SUBPATH / DRIFT） | 1 | 对应 error 级记录 | 1 |
| 算不了（依赖缺失 / exports 解析不了 / 基准缺失 / 降级记账，且无确证问题） | 3 | 对应 error 级阻断记录（``dp-no-package-json`` 等族） | 1 |

旧 3 → 新 1 是**登记在案的口径差**（同 #22 build-diff-ledger 先例）：账本没有
"算不了"专用退出码，把"算不了"落成不阻断的 warn 会回 0——那正是旧仓设计红线
（``data/README.md`` §5.1："零命中"与"算不了"必须落在不同退出码）要防的假绿。
"算不了"与"发现问题"的区分保留在 rule_id 族与 evidence 里。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, Record

from . import drift as drift_mod
from . import scan as scan_mod
from .check import build_dep_index, judge_point
from .spec import (
    DEFAULT_MODE,
    DRIFT,
    MODES,
    NO_BASELINE,
    PROBLEM_STATUSES,
    PROBLEM_STATUSES_WITH_DRIFT,
    STATUS,
)

#: 判定态 → 规则 id（问题三态 + AMBIGUOUS + RESOLVED）。
_STATUS_RULE = {
    STATUS["RESOLVED"]: "dp-resolved",
    STATUS["MISSING_EXPORT"]: "dp-missing-export",
    STATUS["ESM_CJS_MISMATCH"]: "dp-esm-cjs-mismatch",
    STATUS["NOT_EXPORTED_SUBPATH"]: "dp-not-exported-subpath",
    STATUS["AMBIGUOUS"]: "dp-ambiguous",
}
#: 「算不了」gap 种类 → 规则 id（error 级阻断记录；旧 rc3 族，见模块 docstring 的口径差）。
_GAP_RULE = {
    "NO_PACKAGE_JSON": "dp-no-package-json",
    "UNPARSEABLE": "dp-exports-unparseable",
    "EXPORTS_NOT_DECLARED": "dp-exports-not-declared",
    "UNRESOLVABLE_TARGET": "dp-unresolvable-target",
    "EXPORT_SURFACE_UNPARSEABLE": "dp-export-surface-unparseable",
    "NO-BASELINE": "dp-no-baseline",
    "LARGE_FILE_DOWNGRADED": "dp-large-file-downgraded",
    "UNREADABLE_FILE": "dp-unreadable-file",
}
#: 不在已知 gap 枚举里的输入层 gap 兜底规则（仍阻断——旧仓任何 gap 都把退出码抬离 0）。
_GAP_RULE_FALLBACK = "dp-input-gap"

GAP_RULE_IDS = tuple(_GAP_RULE.values()) + (_GAP_RULE_FALLBACK,)


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    """``check`` / ``drift`` 主流程的账本化入口。"""
    mode = subject.get("mode", DEFAULT_MODE)
    if mode not in MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(MODES), mode))

    project = subject.get("project")
    if not isinstance(project, dict):
        raise ValueError("project 必须是 JSON 对象（依赖面事实）")
    declared = project.get("declared_deps")
    if not isinstance(declared, dict):
        raise ValueError("project.declared_deps 必须是对象（dependencies ∪ devDependencies）")
    installed = project.get("deps", {})
    if not isinstance(installed, dict):
        raise ValueError("project.deps 必须是对象（node_modules 依赖事实）")
    sources = subject.get("sources", [])
    if not isinstance(sources, list) or any(not isinstance(s, dict) for s in sources):
        raise ValueError("sources 必须是 [{file, text}] 数组")
    baselines = subject.get("baselines", {})
    if not isinstance(baselines, dict):
        raise ValueError("baselines 必须是对象（包名 → 基线值；无基线 = 键缺省或 null）")
    options = subject.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("options 必须是对象")
    input_gaps = subject.get("input_gaps", [])
    if not isinstance(input_gaps, list):
        raise ValueError("input_gaps 必须是数组（输入层独有事实的 gap，如 UNREADABLE_FILE）")

    records: List[Record] = []
    records.extend(_gap_records(input_gaps, basis))

    if mode == "drift":
        records, total_points = _drift_flow(declared, installed, sources, baselines, options, basis, records)
        records.append(_summary_record(mode, records, basis, total_points))
        return records

    records, total_points = _check_flow(declared, installed, sources, baselines, options, basis, records)
    records.append(_summary_record(mode, records, basis, total_points))
    return records


# ------------------------------------------------------------------ 依赖面
def _build_deps(declared: Mapping[str, Any], installed: Mapping[str, Any],
                basis: Basis) -> Tuple[Dict[str, Dict[str, Any]], List[Record]]:
    """声明依赖 → 判定面记录。未安装的依赖 = NO_PACKAGE_JSON（算不了 gap，绝不静默跳过）。"""
    # 只收**声明过**的依赖（旧仓 collectDeclaredDeps：dependencies ∪ devDependencies，
    # 字符串 range 才计入；peer/optional 首期不计入"直接依赖面"）。
    declared_clean = {name: rng for name, rng in sorted(declared.items()) if isinstance(rng, str)}
    records: List[Record] = []
    deps: Dict[str, Dict[str, Any]] = {}
    for name in declared_clean:
        record_src = installed.get(name)
        if not isinstance(record_src, dict):
            deps[name] = {
                "name": name,
                "declaredRange": declared_clean[name],
                "installedVersion": None,
                "type": None,
                "parseState": "NO_PACKAGE_JSON",
                "index": {"entries": [], "unparseable": False, "ignored": []},
                "files": {},
            }
            records.append(_gap_record(
                {"kind": "NO_PACKAGE_JSON", "pkg": name, "detail": "node_modules 下没有该包的 package.json"},
                basis,
            ))
            continue
        record = build_dep_index({**record_src, "name": name, "declared_range": declared_clean[name]})
        deps[name] = record
        if record["parseState"] == "UNPARSEABLE":
            # 覆盖率缺口：解析不了就显式记账，绝不静默跳过
            records.append(_gap_record(
                {"kind": "UNPARSEABLE", "pkg": name, "detail": "exports 字段形态无法按 Node 语义解析"},
                basis,
            ))
    return deps, records


# ------------------------------------------------------------------ check 流程
def _check_flow(declared: Mapping[str, Any], installed: Mapping[str, Any],
                sources: List[Mapping[str, Any]], baselines: Mapping[str, Any],
                options: Mapping[str, Any], basis: Basis,
                records: List[Record]) -> Tuple[List[Record], int]:
    deps, deps_records = _build_deps(declared, installed, basis)
    records.extend(deps_records)

    max_file_bytes = options.get("max_file_bytes")
    scan = scan_mod.scan_sources_texts(sources, set(deps.keys()), max_file_bytes)
    records.extend(_gap_records(scan["gaps"], basis))

    findings: List[Dict[str, Any]] = []
    gap_rows: List[Dict[str, Any]] = []
    for point in scan["points"]:
        judged = judge_point(point, deps)
        if judged.get("gap"):
            gap_rows.append({**judged["gap"], "file": point["file"], "line": point["line"]})
            continue
        if judged.get("outOfScope"):
            continue
        if judged.get("status") is None:
            continue
        findings.append({
            "status": judged["status"],
            **judged["evidence"],
            "kind": point.get("kind"),
            "specifier": point.get("specifier"),
        })

    if options.get("with_drift"):
        # drift 按**引用点**判（不是按包）。``drift_all`` 只保留有结论的点；
        # DRIFT 是同一引用点上**更精确**的诊断，就地取代较粗的那条（通常是 MISSING-EXPORT）
        # ——不取代的后果：一个引用点产出两条 problem，problems 被算两遍，"1 个问题"读成"2 个"。
        for d in drift_mod.drift_all(deps, scan["points"], baselines):
            if d.get("status") == DRIFT:
                key = _point_key(d["file"], d["line"], d.get("specifier"))
                findings = [f for f in findings if _point_key(f["file"], f["line"], f.get("specifier")) != key]
                findings.append({**{k: v for k, v in d.items() if k != "status"}, "status": d["status"]})
            elif d.get("status") == NO_BASELINE:
                gap_rows.append({
                    "kind": NO_BASELINE, "pkg": d["pkg"], "file": d["file"], "line": d["line"],
                    "specifier": d.get("specifier"), "detail": d.get("detail"),
                })

    seen_ids: Dict[Tuple[str, str], int] = {}
    for f in _sort_findings(findings):
        records.append(_finding_record(f, basis, seen_ids))
    for row in _sort_gaps(gap_rows):
        records.append(_gap_record(row, basis, seen_ids))
    return records, len(scan["points"])


# ------------------------------------------------------------------ drift 流程
def _drift_flow(declared: Mapping[str, Any], installed: Mapping[str, Any],
                sources: List[Mapping[str, Any]], baselines: Mapping[str, Any],
                options: Mapping[str, Any], basis: Basis,
                records: List[Record]) -> Tuple[List[Record], int]:
    deps, deps_records = _build_deps(declared, installed, basis)
    records.extend(deps_records)

    scan = scan_mod.scan_sources_texts(sources, set(deps.keys()), options.get("max_file_bytes"))
    for d in drift_mod.drift_all(deps, scan["points"], baselines):
        if d.get("status") == DRIFT:
            records.append(_finding_record(
                {**{k: v for k, v in d.items() if k != "status"}, "status": d["status"]}, basis,
            ))
        elif d.get("status") == NO_BASELINE:
            records.append(_gap_record({
                "kind": NO_BASELINE, "pkg": d["pkg"], "file": d["file"], "line": d["line"],
                "specifier": d.get("specifier"), "detail": d.get("detail"),
            }, basis))
    return records, len(scan["points"])


def _dedupe_path(rule_id: str, path: str, seen_ids: Dict[Tuple[str, str], int]) -> str:
    """同一 (rule_id, path) 上出现第 n 条记录时给 path 加 ``#n`` 序号。

    旧仓 findings/gaps 是**列表**（同一 file|line|specifier 键上的多个调用点各自一条）；
    账本 id = rule@path 必须唯一，故从第 2 条起加序号。排序稳定（file → line → status →
    原扫描序），序号分配确定，双跑逐字节一致。
    """
    count = seen_ids.get((rule_id, path), 0) + 1
    seen_ids[(rule_id, path)] = count
    if count == 1:
        return path
    return "%s#%d" % (path, count)


# ------------------------------------------------------------------ 记录构造
def _point_key(file: str, line: Any, specifier: Any) -> str:
    return "%s|%s|%s" % (file, line, specifier if specifier is not None else "")


def _sort_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """稳定排序：file → line → status（确定性双跑逐字节一致的前提）。"""
    return sorted(findings, key=lambda f: (str(f.get("file", "")), f.get("line") or 0, str(f.get("status", ""))))


def _sort_gaps(gaps: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return sorted(list(gaps), key=lambda g: "%s|%s|%s|%s" % (
        g.get("kind", ""), g.get("pkg", ""), g.get("file", ""), g.get("line", 0) or 0,
    ))


def _ref(basis: Basis, rule_id: str):
    return basis.ref(rule_id)


def _finding_record(finding: Mapping[str, Any], basis: Basis,
                    seen_ids: Optional[Dict[Tuple[str, str], int]] = None) -> Record:
    status = finding.get("status")
    if status == DRIFT:
        rule_id = "dp-version-behavior-drift"
        verdict = ERROR
    elif status in PROBLEM_STATUSES:
        rule_id = _STATUS_RULE[status]
        verdict = ERROR
    else:
        rule_id = _STATUS_RULE.get(status, "dp-ambiguous")
        verdict = INFO
    path = "%s:%s:%s" % (finding.get("file", ""), finding.get("line", ""), finding.get("specifier") or "")
    if seen_ids is not None:
        path = _dedupe_path(rule_id, path, seen_ids)
    return Record(
        rule_id=rule_id,
        verdict=verdict,
        message=_finding_message(finding),
        basis=_ref(basis, rule_id),
        path=path,
        # 旧仓 finding 的 status/file/line/kind/specifier 是平铺字段，evidence 全量保留
        evidence=dict(finding),
    )


def _finding_message(finding: Mapping[str, Any]) -> str:
    status = finding.get("status")
    if status == STATUS["MISSING_EXPORT"]:
        return "缺少导出符号 %s（可用前 20：%s）" % (
            ",".join(finding.get("missing", [])),
            ",".join(finding.get("available", [])) or "（无）",
        )
    if status == STATUS["ESM_CJS_MISMATCH"]:
        return "require() 拿到命名空间对象，API 在 .default 下（exports 无 require 分支）"
    if status == STATUS["NOT_EXPORTED_SUBPATH"]:
        return "子路径 %s 未被 exports 暴露（%s）" % (finding.get("subpath", "."), finding.get("rule", ""))
    if status == DRIFT:
        return "版本行为漂移：基线 %s 有 %s，已装 %s 没有" % (
            finding.get("baselineVersion"), ",".join(finding.get("missing", [])),
            finding.get("installedVersion"),
        )
    if status == STATUS["AMBIGUOUS"]:
        return "动态形态，不可静态判定（不代表代码有错）：%s" % (finding.get("note") or "动态 specifier")
    return "RESOLVED：该符号在声明的入口下确实导出"


def _gap_record(row: Mapping[str, Any], basis: Basis,
                seen_ids: Optional[Dict[Tuple[str, str], int]] = None) -> Record:
    kind = row.get("kind", "")
    rule_id = _GAP_RULE.get(kind, _GAP_RULE_FALLBACK)
    file = row.get("file")
    pkg = row.get("pkg")
    if file is not None:
        line = row.get("line")
        path = "%s:%s" % (file, line if line is not None else "")
    elif pkg is not None:
        path = str(pkg)
    else:
        path = str(kind)
    if seen_ids is not None:
        path = _dedupe_path(rule_id, path, seen_ids)
    return Record(
        rule_id=rule_id,
        verdict=ERROR,
        message="%s（算不了/覆盖率缺口：旧仓退出码 3 族，账本化为阻断记录）" % (row.get("detail") or kind),
        basis=_ref(basis, rule_id),
        path=path,
        evidence=dict(row),
    )


def _gap_records(rows: List[Mapping[str, Any]], basis: Basis) -> List[Record]:
    return [_gap_record(row, basis) for row in _sort_gaps(rows)]


def _summary_record(mode: str, records: List[Record], basis: Basis, total_points: int) -> Record:
    resolved = 0
    ambiguous = 0
    problems = 0
    gaps = 0
    by_status: Dict[str, int] = {}
    for record in records:
        if record.rule_id == "dp-summary":
            continue
        status = record.evidence.get("status")
        if status:
            by_status[status] = by_status.get(status, 0) + 1
        if status in PROBLEM_STATUSES or status == DRIFT:
            problems += 1
        elif record.rule_id in GAP_RULE_IDS:
            gaps += 1
        elif status == STATUS["RESOLVED"]:
            resolved += 1
        elif status == STATUS["AMBIGUOUS"]:
            ambiguous += 1
    by_status = {k: by_status[k] for k in sorted(by_status)}
    return Record(
        rule_id="dp-summary",
        verdict=INFO,
        message="mode=%s：problems=%d gaps=%d resolved=%d ambiguous=%d totalPoints=%d"
                % (mode, problems, gaps, resolved, ambiguous, total_points),
        basis=_ref(basis, "dp-summary"),
        path="summary",
        evidence={
            "mode": mode,
            "totalPoints": total_points,
            "resolved": resolved,
            "ambiguous": ambiguous,
            "problems": problems,
            "gaps": gaps,
            "byStatus": by_status,
        },
    )
