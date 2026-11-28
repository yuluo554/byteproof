"""M2 确定性列血缘核（移植自旧仓 ``core.py`` 的判定面，消费**泛型 AST 树**）。

sqlglot 解析（SQL 文本 → AST）是输入层职责：subject 携带输入层 dump 的泛型树
（``{"t":"e","c":<类名>,"args":{...},"name"/"alias"}``，字符串/字面量为
``{"t":"s"/"lit","v":...}``）。器官在其上移植旧仓 ``_Resolver`` 的判定面：
关系收集 / CTE 链 / 输出列回溯 / value-control 分型（§4.1 判定顺序）/
零静默（每条写语句有边或有诊断）。

判定顺序（旧仓 data/README.md §4.1）：AST 定不了 → unknown + reason code；
再分 value / control。窗口强制口径：
``SUM(x) OVER (PARTITION BY k ORDER BY t)`` → (w,value,x) + (w,control,k) + (w,control,t)。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import spec


# ---------------------------------------------------------------- 泛型树助手
def is_node(obj: Any) -> bool:
    return isinstance(obj, dict) and obj.get("t") == "e"


def node_class(obj: Any) -> str:
    return obj.get("c", "") if isinstance(obj, dict) else ""


def node_name(obj: Any) -> str:
    """节点名：顶层 ``name``（dump 属性）→ Identifier.this 的字符串（Table→Identifier 两层）。"""
    if not isinstance(obj, dict):
        return ""
    name = obj.get("name")
    if name:
        return str(name)
    inner = arg(obj, "this")
    if isinstance(inner, dict):
        if inner.get("t") == "s":
            return str(inner.get("v"))
        if node_class(inner) == "Identifier":
            id_inner = arg(inner, "this")
            if isinstance(id_inner, dict) and id_inner.get("t") == "s":
                return str(id_inner.get("v"))
    return ""


def node_alias(obj: Any) -> str:
    return obj.get("alias", "") if isinstance(obj, dict) else ""


def arg(node: Mapping[str, Any], key: str) -> Any:
    args = node.get("args") or {}
    return args.get(key)


def iter_nodes(root: Any):
    """深度优先遍历泛型树（dict 节点 + list）。"""
    if is_node(root):
        yield root
        for value in (root.get("args") or {}).values():
            yield from iter_nodes(value)
    elif isinstance(root, list):
        for item in root:
            yield from iter_nodes(item)


def find_first(root: Any, cls: str):
    for node in iter_nodes(root):
        if node_class(node) == cls:
            return node
    return None


def _literal_str(value: Any) -> str:
    if isinstance(value, dict):
        if value.get("t") in ("s", "lit"):
            return str(value.get("v"))
        return node_name(value) or node_alias(value) or ""
    return str(value) if value is not None else ""


# ---------------------------------------------------------------- 边与诊断
def make_edge(target_table, target_column, kind, source_table, source_column, expr,
              statement_id, aggregation=None, window=None, reason_code=None) -> Dict[str, Any]:
    return {
        "target": "%s.%s" % (target_table, target_column),
        "source": "%s.%s" % (source_table, source_column) if source_table else "*",
        "kind": kind,
        "expr": expr,
        "statement_id": statement_id,
        "aggregation": aggregation,
        "window": window,
        "reason_code": reason_code,
        "approximate": kind == spec.KIND_UNKNOWN,
    }


def make_diag(file, statement_index, reason_code, message, approximate=False):
    return {"file": file, "statement_index": statement_index, "reason_code": reason_code,
            "message": message, "approximate": approximate}


# ---------------------------------------------------------------- 作用域解析
def _relations(select: Mapping[str, Any], scope: Dict[str, Tuple[str, Any]]) -> Dict[str, Tuple[str, Any]]:
    """alias → ('table', name) | ('select', select 节点)。保持 FROM → JOIN 顺序。"""
    rels: Dict[str, Tuple[str, Any]] = {}

    def add(node: Any, force_alias: Optional[str] = None) -> None:
        cls = node_class(node)
        if cls == "Table":
            name = node_name(node)
            alias = force_alias or node_alias(node) or name
            rels[alias] = ("table", name)
            if alias != name and name not in rels:
                rels[name] = ("table", name)  # 允许用裸表名限定
        elif cls == "Subquery":
            alias = force_alias or node_alias(node)
            inner = arg(node, "this")
            if alias and inner is not None:
                rels[alias] = ("select", inner)
        elif cls == "Lateral":
            add(arg(node, "this"), force_alias or node_alias(node))

    frm = arg(select, "from_") or arg(select, "from")
    if frm is not None:
        add(arg(frm, "this"))
        for extra in arg(frm, "expressions") or []:
            add(extra)
    for j in arg(select, "joins") or []:
        add(arg(j, "this"))
    # CTE 名当表引用（FROM agg / JOIN cte）
    for alias, (kind, node) in list(rels.items()):
        if kind == "table" and node in scope:
            rels[alias] = ("select", scope[node])
    return rels


def _cte_scope(select: Mapping[str, Any], parent: Dict[str, Any]) -> Dict[str, Any]:
    scope = dict(parent)
    with_ = arg(select, "with_") or arg(select, "with")
    if with_ is None:
        return scope
    for cte in arg(with_, "expressions") or []:
        alias = node_alias(cte) or node_name(arg(cte, "this"))
        if alias:
            scope[alias] = arg(cte, "this")
    return scope


def _table_name_of(node: Any) -> Optional[str]:
    """从表引用节点取表名（Table → name；CTE/Subquery → None，需回溯）。"""
    if node_class(node) == "Table":
        return node_name(node)
    return None


def _column_of(node: Any) -> str:
    """Column 节点的列名（this 是 Identifier 或 Star）。"""
    inner = arg(node, "this")
    if isinstance(inner, dict) and node_class(inner) == "Star":
        return "*"
    return _literal_str(inner) if inner is not None else ""


def _collect_sources(expr: Any, rels: Mapping[str, Tuple[str, Any]],
                     scope: Mapping[str, Any], state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """§4.1 分型：表达式树 → 来源候选列表。

    - Column → value（经 rels 解析到表名；解析不到表 → unknown/unknown_type）；
    - 聚合函数 → 参数各出一 value 边 + aggregation 标注；
    - Window → PARTITION BY / ORDER BY 参数出 control 边，其余按表达式走；
    - 星号 → unknown/unknown_wildcard；
    - 字面量 → 不出边。
    """
    sources: List[Dict[str, Any]] = []
    cls = node_class(expr)

    if cls == "Column":
        column = _column_of(expr)
        if column == "*":
            state.setdefault("wildcard", [])
            state["wildcard"].append(_literal_str(arg(expr, "table")))
            return sources
        table_ref = arg(expr, "table")
        table_alias = _literal_str(table_ref) if table_ref is not None else None
        resolved = None
        if table_alias:
            # 限定列（t.x）：只按限定名解析，解析不到就是 unknown（不落"唯一 rel"兜底）
            resolved = rels.get(table_alias)
        elif len(rels) == 1:
            resolved = next(iter(rels.values()))
        kind = spec.KIND_VALUE
        reason = None
        table = None
        if resolved is not None:
            rkind, rvalue = resolved
            if rkind == "table":
                table = rvalue
            else:
                table = "__select__%s" % id(rvalue)  # CTE/子查询：输出列回溯由上层展开
                state["pending_selects"].append((table, column, rvalue))
        else:
            kind = spec.KIND_UNKNOWN
            reason = spec.R_UNKNOWN_TYPE
        sources.append({"kind": kind, "table": table, "column": column,
                        "expr": _expr_text(expr), "reason": reason})
        return sources

    if cls in spec.AGGREGATE_CLASSES:
        state["in_aggregation"] += 1
        for child in (arg(expr, "this"), ):
            if child is not None:
                for sub in _collect_sources(child, rels, scope, state):
                    sub["aggregation"] = _expr_text(expr)
                    sources.append(sub)
        state["in_aggregation"] -= 1
        return sources

    if cls == spec.WINDOW_CLASS:
        partition = arg(expr, "partition_by") or []
        order = arg(expr, "order") or []
        order_expr = arg(order[0], "this") if order and is_node(order[0]) else None
        for part in partition:
            for sub in _collect_sources(part, rels, scope, state):
                sub["kind"] = spec.KIND_CONTROL
                sub["window"] = _expr_text(expr)
                sources.append(sub)
        if order_expr is not None:
            for sub in _collect_sources(order_expr, rels, scope, state):
                sub["kind"] = spec.KIND_CONTROL
                sub["window"] = _expr_text(expr)
                sources.append(sub)
        inner = arg(expr, "this")
        if inner is not None:
            sources.extend(_collect_sources(inner, rels, scope, state))
        return sources

    if cls in ("Star",):
        state.setdefault("wildcard", [])
        state["wildcard"].append(None)
        return sources

    if cls == "Alias":
        return _collect_sources(arg(expr, "this"), rels, scope, state)

    if cls == "Paren" or cls == "Neg" or cls == "Not":
        return _collect_sources(arg(expr, "this"), rels, scope, state)

    if cls == "Cast":
        return _collect_sources(arg(expr, "this"), rels, scope, state)

    if cls == "Case":
        for branch in arg(expr, "ifs") or []:
            sources.extend(_collect_sources(branch, rels, scope, state))
        default = arg(expr, "default")
        if default is not None:
            sources.extend(_collect_sources(default, rels, scope, state))
        return sources

    if cls == "If":
        for key in ("this", "true", "false"):
            child = arg(expr, key)
            if child is not None:
                sources.extend(_collect_sources(child, rels, scope, state))
        return sources

    if cls in ("Coalesce", "Greatest", "Least", "Nullif", "Concat", "ConcatWs", "Abs",
               "Round", "Floor", "Ceil", "Sqrt", "Pow", "Lower", "Upper", "Trim",
               "Substring", "Replace", "Length", "DateAdd", "DateDiff", "CurrentDate",
               "CurrentTimestamp", "Anonymous", "ConcatWs", "IfNull", "Nvl", "Coalesce"):
        for key, value in (expr.get("args") or {}).items():
            if key in ("dialect",):
                continue
            for sub in _collect_sources(value, rels, scope, state):
                sub.setdefault("expr", _expr_text(expr))
                sources.append(sub)
        return sources

    if cls == "Literal" or cls == "Boolean" or cls == "Null":
        return sources  # 字面量不出边

    # 其余表达式类：递归展开 args（值参数仍算 value；未知类不计 reason——由上层 unknown 兜底）
    if isinstance(expr, list):
        for item in expr:
            sources.extend(_collect_sources(item, rels, scope, state))
        return sources
    if isinstance(expr, dict):
        for key, value in (expr.get("args") or {}).items():
            if key in ("dialect",):
                continue
            sources.extend(_collect_sources(value, rels, scope, state))
    return sources


def _expr_text(node: Any) -> str:
    """重建表达式文本（泛型树的规范化拼装；旧仓 _clean_sql 的近似等价）。

    列/表名拼点分文本；函数拼 ``FN(arg,…)``；其余回退类名+列名——确定性即可，
    边的身份由 (target, source, kind) 承担，expr 是留档。
    """
    if node is None:
        return ""
    if isinstance(node, dict):
        if node.get("t") in ("s", "lit"):
            return str(node.get("v"))
        cls = node_class(node)
        if cls == "Column":
            table = _literal_str(arg(node, "table")) if arg(node, "table") is not None else ""
            column = _column_of(node)
            return "%s.%s" % (table, column) if table else column
        if cls == "Star":
            return "*"
        parts = []
        for key, value in (node.get("args") or {}).items():
            if key in ("dialect", "with_", "with"):
                continue
            child = _expr_text(value)
            if child:
                parts.append(child)
        if cls in spec.AGGREGATE_CLASSES:
            return "%s(%s)" % (cls.upper(), ", ".join(parts))
        if node_alias(node):
            return node_alias(node)
        return " ".join(p for p in [cls] + parts if p)
    if isinstance(node, list):
        return ", ".join(_expr_text(item) for item in node if _expr_text(item))
    return str(node)


def _output_columns(select: Mapping[str, Any]) -> List[Tuple[str, Any]]:
    """select 的输出列：``(name, expr)``；无别名时取表达式文本。"""
    outputs: List[Tuple[str, Any]] = []
    expressions = arg(select, "expressions") or []
    for expr in expressions:
        cls = node_class(expr)
        if cls == "Alias":
            outputs.append((node_alias(expr), arg(expr, "this")))
        elif cls == "Column" and _column_of(expr) != "*":
            outputs.append((_column_of(expr), expr))
        elif cls == "Star":
            outputs.append(("*", expr))
        else:
            text = _expr_text(expr) or cls
            outputs.append((text, expr))
    return outputs


class Resolver:
    """一条语句内的作用域解析器（泛型树版 _Resolver 判定面）。"""

    def __init__(self, file: str, index: int, statement_id: str):
        self.file = file
        self.index = index
        self.statement_id = statement_id
        self.diags: List[Dict[str, Any]] = []
        self.edges: List[Dict[str, Any]] = []
        self.seen_selects: set = set()

    def resolve_write(self, statement_root: Any, target_table: str, target_columns: List[str],
                      select_node: Any, parent_scope: Optional[Dict[str, Any]] = None) -> None:
        scope = _cte_scope(select_node, parent_scope or {})
        rels = _relations(select_node, scope)
        state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
        outputs = _output_columns(select_node)
        if not outputs:
            self.diags.append(make_diag(
                self.file, self.index, spec.R_NO_SOURCE_COLUMNS,
                "no output columns to trace in %s" % target_table))
        # 目标列对齐：INSERT INTO t (cols) SELECT … → **按位置**配对（columns[i] ←
        # expressions[i]，旧仓同语义：`INSERT INTO stage_g3 (c2, c1) SELECT a, b` 是
        # c2←a、c1←b，不是按名字找）；CTAS 无列单 → 输出名即目标列
        outputs = _output_columns(select_node)
        by_name = {name: expr for name, expr in outputs}
        expressions = arg(select_node, "expressions") or []
        if target_columns:
            columns = target_columns
        else:
            columns = [name for name, _ in outputs]
        for position, column in enumerate(columns):
            if target_columns and position < len(expressions):
                # INSERT 带列单：按位置取第 i 个输出表达式
                expr = expressions[position]
            else:
                expr = by_name.get(column)
                if expr is None:
                    expr = expressions[0] if expressions else None
            if expr is None:
                continue
            self._resolve_column(target_table, column, expr, rels, scope, state)
        self._expand_pending(state)
        if state.get("wildcard"):
            # 星号 → 一条 unknown 边（target 表.*、source=null）+ 一条 diag（旧仓同构）
            self.edges.append({
                "target": "%s.*" % target_table,
                "source": None,
                "kind": spec.KIND_UNKNOWN,
                "expr": "*",
                "statement_id": self.statement_id,
                "aggregation": None,
                "window": None,
                "reason_code": spec.R_UNKNOWN_WILDCARD,
                "approximate": True,
            })
            self.diags.append(make_diag(
                self.file, self.index, spec.R_UNKNOWN_WILDCARD,
                "unknown edge %s.* (*) carries reason_code=unknown_wildcard" % target_table))
        elif not self.edges and not self.diags:
            self.diags.append(make_diag(
                self.file, self.index, spec.R_NO_SOURCE_COLUMNS,
                "no edges produced for %s" % target_table))

    def _resolve_column(self, target_table: str, column: str, expr: Any,
                        rels: Mapping[str, Tuple[str, Any]], scope: Mapping[str, Any],
                        state: Dict[str, Any]) -> None:
        sources = _collect_sources(expr, rels, scope, state)
        if not sources:
            if not state.get("wildcard"):
                # 星号场景由 resolve_write 的 unknown_wildcard 面统一出边+诊断
                self.diags.append(make_diag(
                    self.file, self.index, spec.R_NO_SOURCE_COLUMNS,
                    "no source candidates for %s.%s" % (target_table, column)))
            return
        for source in sources:
            table = source["table"]
            if table is None and source["kind"] != spec.KIND_UNKNOWN:
                source["kind"] = spec.KIND_UNKNOWN
                source["reason"] = source["reason"] or spec.R_UNKNOWN_TYPE
            self.edges.append(make_edge(
                target_table, column, source["kind"], source["table"], source["column"],
                source.get("expr", ""), self.statement_id,
                aggregation=source.get("aggregation"), window=source.get("window"),
                reason_code=source.get("reason")))

    def _expand_pending(self, state: Dict[str, Any]) -> None:
        """CTE/子查询回溯：把 ``__select__<id>`` 占位边展开成被引用 select 的输出列。"""
        pending = state.get("pending_selects", [])
        state["pending_selects"] = []
        for placeholder, column, select_node in pending:
            key = id(select_node)
            if key in self.seen_selects:
                continue
            self.seen_selects.add(key)
            scope = _cte_scope(select_node, {})
            rels = _relations(select_node, scope)
            sub_state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
            outputs = _output_columns(select_node)
            by_name = {name: expr for name, expr in outputs}
            expr = by_name.get(column)
            if expr is None and outputs:
                expr = outputs[0][1]
            if expr is None:
                continue
            # 占位边替换：收集到该占位上的边改写到真实源
            for edge in self.edges:
                if edge["source"].startswith("%s." % placeholder) or edge["source"] == "%s.*" % placeholder:
                    sources = _collect_sources(expr, rels, scope, sub_state)
                    if sources:
                        first = sources[0]
                        edge["source"] = "%s.%s" % (first["table"] or edge["source"], first["column"])
                        edge["kind"] = first["kind"] if first["kind"] != spec.KIND_UNKNOWN else edge["kind"]
                        edge["reason_code"] = first.get("reason")
            state["pending_selects"].extend(sub_state.get("pending_selects", []))
        if state.get("pending_selects"):
            self._expand_pending(state)


def classify_statement(statement_root: Any) -> Tuple[str, Optional[str]]:
    """语句分类：insert / ctas / merge / unsupported(reason)。返回 (kind, target_class)。"""
    cls = node_class(statement_root)
    if cls == "Insert":
        return spec.WRITE_INSERT, None
    if cls == "Create":
        if find_first(statement_root, "Select") is not None and arg(statement_root, "expression") is not None:
            return spec.WRITE_CTAS, None
        return "other", cls
    if cls == "Merge":
        return spec.WRITE_MERGE, None
    if cls in spec.UNSUPPORTED_CLASSES:
        return "unsupported", cls
    return "other", cls
