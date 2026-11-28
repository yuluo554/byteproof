"""编排层：``evaluate(subject, basis) -> Iterable[Record]``。

模式：``lineage``（列级血缘 + 零静默）/ ``census``（写入者普查五节）/ ``diff``
（lineage diff 闸门 + impact 反向穿透）。语句 AST 由输入层以 sqlglot 解析后按泛型树
dump 传入（器官零第三方依赖）；解析失败形态经 ``ParseErrorStub`` 显式传入。

退出码映射：旧仓 lineage/diff 0 无阻断 / 1 有破坏性变更 / 2 输入不合法 / 4 零静默失败；
账本化：value/control 边 → info（正向证据）、unknown 边 → warn（approximate）、
unsupported/parse/零静默诊断 → error（旧 rc4 面）、diff 的 destructive → error。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import core, spec
from .catalogue import Catalogue


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if mode not in spec.MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(spec.MODES), mode))
    statements = subject.get("statements")
    if not isinstance(statements, list):
        raise ValueError("statements 必须是数组（输入层 dump 的语句列表）")
    catalog = Catalogue(basis)

    if mode == "lineage":
        result = _lineage(statements, subject)
        records = _lineage_records(result, catalog)
    elif mode == "census":
        result = _census(_lineage(statements, subject))
        records = _census_records(result, catalog)
    else:
        base = subject.get("base_edges")
        if base is None:
            raise ValueError("diff 模式必须带 base_edges（基线边集）")
        result = _diff(_lineage(statements, subject), base, subject.get("options") or {})
        records = _diff_records(result, catalog)
    records.append(_summary_record(mode, result, records, basis))
    return records


# ---------------------------------------------------------------- lineage
def _lineage(statements: List[Mapping[str, Any]], subject: Mapping[str, Any]) -> Dict[str, Any]:
    edges: List[Dict[str, Any]] = []
    diags: List[Dict[str, Any]] = []
    writes: List[Dict[str, Any]] = []
    tables: set = set()
    written: Dict[str, List[str]] = {}
    read_by: Dict[str, List[str]] = {}

    for st in statements:
        file = st.get("file", "")
        index = st.get("index", 0)
        sid = st.get("statement_id", "")
        ast = st.get("ast")
        roots = ast if isinstance(ast, list) else [ast]
        for root in roots:
            if root is None:
                continue
            if core.node_class(root) == "ParseErrorStub":
                diags.append(core.make_diag(file, index, spec.R_PARSE_ERROR,
                                            "parse error: %s" % core.node_name(root)))
                continue
            kind, target_cls = core.classify_statement(root)
            if kind == "other":
                continue
            if kind == "unsupported":
                reason = core.spec.R_UNSUPPORTED_WRITE_STATEMENT
                diags.append(core.make_diag(
                    file, index, reason,
                    "%s (%s) is not supported for column-level lineage; "
                    "recorded as unsupported_write_statement" % (target_cls, sid)))
                continue
            target_table, target_columns, select_node = _write_facts(root, kind)
            if target_table is None:
                diags.append(core.make_diag(file, index, spec.R_UNKNOWN_TYPE,
                                            "no write target resolved for %s" % sid))
                continue
            writes.append({"statement_id": sid, "target_table": target_table,
                           "kind": kind})
            written.setdefault(target_table, []).append(sid)
            resolver = core.Resolver(file, index, sid)
            resolver.resolve_write(root, target_table, target_columns, select_node)
            edges.extend(resolver.edges)
            diags.extend(resolver.diags)
            for edge in resolver.edges:
                source = edge.get("source")
                if source and not source.startswith("__select__"):
                    source_table = source.split(".")[0] if "." in source else source
                    if source_table != "*":
                        read_by.setdefault(source_table, []).append(sid)
                if source:
                    tables.add(source.split(".")[0] if "." in source else source)
            tables.add(target_table)

    # 输入层 loader 诊断（dialect_defaulted 等）原样透传——零静默面的输入侧事实
    for diag in subject.get("loader_diagnostics") or []:
        diags.append(dict(diag))
    return {
        "edges": edges,
        "diagnostics": diags,
        "writes": writes,
        "tables": sorted(tables),
        "written": {k: sorted(v) for k, v in sorted(written.items())},
        "read_by": {k: sorted(v) for k, v in sorted(read_by.items())},
    }


def _write_facts(root: Mapping[str, Any], kind: str):
    """写语句 → (target_table, target_columns, select_node)。"""
    if kind == spec.WRITE_INSERT:
        schema = core.arg(root, "this")
        table = core.arg(schema, "this") if schema is not None else None
        target = core.node_name(table) if table is not None else None
        columns = [core._literal_str(c) for c in (core.arg(schema, "expressions") or [])]
        expression = core.arg(root, "expression")
        select = core.find_first(expression or root, "Select") if isinstance(expression, (dict, list)) else None
        return target, columns, select
    if kind == spec.WRITE_CTAS:
        schema = core.arg(root, "this")
        table = core.arg(schema, "this") if schema is not None else None
        target = core.node_name(table) if table is not None else None
        select = core.arg(root, "expression")
        if core.node_class(select) != "Select":
            select = core.find_first(select, "Select")
        return target, [], select
    if kind == spec.WRITE_MERGE:
        table = core.arg(root, "this")
        target = core.node_name(table) if table is not None else None
        select = core.find_first(root, "Select")
        return target, [], select
    return None, [], None


def _census(lineage: Mapping[str, Any]) -> Dict[str, Any]:
    """写入者普查五节：writers / readers / orphans / conflicts / tables。"""
    written = lineage.get("written", {})
    read_by = lineage.get("read_by", {})
    tables = lineage.get("tables", [])
    writers = [{"table": t, "statements": written[t]} for t in sorted(written)]
    readers = [{"table": t, "statements": read_by[t]} for t in sorted(read_by)]
    conflicts = [{"table": t, "statements": written[t]} for t in sorted(written) if len(written[t]) > 1]
    orphans = [t for t in tables if t in read_by and t not in written]
    return {"writers": writers, "readers": readers, "orphans": orphans,
            "conflicts": conflicts, "tables": tables}


def _diff(lineage: Mapping[str, Any], base_edges: List[Mapping[str, Any]],
          options: Mapping[str, Any]) -> Dict[str, Any]:
    """lineage diff 闸门：边集差分 + 判级（destructive / behavioural / additive）。"""
    def key(edge: Mapping[str, Any]) -> tuple:
        return (edge.get("target"), edge.get("source"), edge.get("kind"))

    base = {key(e) for e in base_edges}
    current = {key(e) for e in lineage.get("edges", [])}
    dropped = sorted(base - current)
    added = sorted(current - base)
    destructive = [e for e in dropped]
    behavioural = []
    if options.get("kind_change_only", True):
        pass
    return {"dropped": [list(e) for e in dropped], "added": [list(e) for e in added],
            "destructive": destructive, "behavioural": behavioural,
            "additive": [list(e) for e in added]}


# ---------------------------------------------------------------- 记录构造
def _lineage_records(lineage: Mapping[str, Any], catalog: Catalogue) -> List[Record]:
    records: List[Record] = []
    for edge in lineage.get("edges", []):
        kind = edge["kind"]
        rule = {"value": "st-edge-value", "control": "st-edge-control",
                "unknown": "st-edge-unknown"}[kind]
        verdict = {"value": INFO, "control": INFO, "unknown": WARN}[kind]
        records.append(Record(
            rule_id=rule, verdict=verdict,
            message="%s %s ← %s (%s%s%s)" % (
                edge["target"], "←" if kind != "unknown" else "←(unknown)", edge["source"],
                edge.get("expr") or "",
                "; window" if edge.get("window") else "",
                "; reason=%s" % edge["reason_code"] if edge.get("reason_code") else ""),
            basis=catalog.basis_ref(rule),
            path="%s@%s" % (edge["target"], edge["statement_id"]),
            evidence=dict(edge)))
    for diag in lineage.get("diagnostics", []):
        code = diag["reason_code"]
        if code in (spec.R_UNSUPPORTED_WRITE_STATEMENT, spec.R_PARSE_ERROR,
                    spec.R_NO_SOURCE_COLUMNS):
            rule, verdict = "st-zero-silence", ERROR
        elif code == spec.R_UNKNOWN_WILDCARD:
            # wildcard 的 unknown 边已单独成账本行；诊断并入同 rule 的 warn 行
            rule, verdict = "st-edge-unknown", WARN
        else:
            rule, verdict = "st-diag-approximate", WARN
        records.append(Record(
            rule_id=rule, verdict=verdict,
            message="%s: %s" % (code, diag["message"]),
            basis=catalog.basis_ref(rule),
            path="%s#%s" % (diag.get("file"), diag.get("statement_index")),
            evidence=dict(diag)))
    return records


def _census_records(census: Mapping[str, Any], catalog: Catalogue) -> List[Record]:
    records: List[Record] = []
    for item in census.get("writers", []):
        records.append(Record(
            rule_id="st-census-writer", verdict=INFO,
            message="%s written by %d statement(s)" % (item["table"], len(item["statements"])),
            basis=catalog.basis_ref("st-census-writer"),
            path=item["table"], evidence=dict(item)))
    for item in census.get("conflicts", []):
        records.append(Record(
            rule_id="st-census-conflict", verdict=WARN,
            message="%s has %d writers (multi-write conflict)" % (item["table"], len(item["statements"])),
            basis=catalog.basis_ref("st-census-conflict"),
            path=item["table"], evidence=dict(item)))
    for table in census.get("orphans", []):
        records.append(Record(
            rule_id="st-census-orphan", verdict=INFO,
            message="%s is read but never written in corpus" % table,
            basis=catalog.basis_ref("st-census-orphan"),
            path=table, evidence={"table": table}))
    return records


def _diff_records(diff: Mapping[str, Any], catalog: Catalogue) -> List[Record]:
    records: List[Record] = []
    counters: Dict[Tuple[str, str], int] = {}
    for group, rule in (("destructive", "st-diff-destructive"), ("added", "st-diff-added")):
        for edge in diff.get(group, []):
            target, source, kind = edge
            verdict = ERROR if group == "destructive" else INFO
            base_path = str(target)
            count = counters.get((rule, base_path), 0) + 1
            counters[(rule, base_path)] = count
            path = base_path if count == 1 else "%s#%d" % (base_path, count)
            records.append(Record(
                rule_id=rule, verdict=verdict,
                message="lineage edge %s: %s ← %s (%s)" % (group, target, source, kind),
                basis=catalog.basis_ref(rule),
                path=path,
                evidence={"target": target, "source": source, "kind": kind}))
    return records


def _summary_record(mode: str, result: Mapping[str, Any], records: List[Record],
                    basis: Basis) -> Record:
    errors = sum(1 for r in records if r.verdict == ERROR)
    warns = sum(1 for r in records if r.verdict == WARN)
    infos = sum(1 for r in records if r.verdict == INFO)
    if mode == "lineage":
        counts = {"edges": len(result.get("edges", [])),
                  "diagnostics": len(result.get("diagnostics", [])),
                  "writes": len(result.get("writes", []))}
    if mode == "census":
        counts = {k: len(result.get(k, [])) for k in ("writers", "readers", "orphans", "conflicts")}
    if mode == "diff":
        counts = {k: len(result.get(k, [])) for k in ("dropped", "added", "destructive")}
    return Record(
        rule_id="st-summary", verdict=INFO,
        message="mode=%s：error=%d warn=%d info=%d" % (mode, errors, warns, infos),
        basis=basis.ref("st-summary"),
        path="summary",
        evidence={"mode": mode, "error": errors, "warn": warns, "info": infos,
                  "counts": counts})
