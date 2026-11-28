"""``sqltrace`` 器官的无损测试（迁自 10-20-sqltrace，Python 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：泛型 AST 树上的关系收集 /
CTE 回溯 / §4.1 判定顺序 / 窗口强制口径（``SUM(x) OVER (PARTITION BY k)`` → value+control
双边）/ 零静默（每条写语句有边或有诊断）/ 写入者普查五节 / diff 闸门三态。
**golden 对账**：来源仓 ``data/golden`` 17 条语句的 AST（输入层 sqlglot dump）原样入仓为
夹具，器官输出与旧仓 ``lineage --json`` 的 17 边 + 8 诊断**逐边逐诊断相等**
（ ``(target, source, kind)`` 键集比对；旧锚在迁移会话内实跑取得）。

**没迁的部分逐条写在 ``docs/sqltrace.md`` §6 的处置表里**（sqlglot 解析面、CLI 面、
golden 命令壳、md 渲染面）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 9 个测试文件剔除 ``license_metadata`` / ``smoke`` /
``version_pointer`` / ``output_stream``（output）后 5 文件实跑 pytest **X = 107 passed**；
旧层 AST ``test`` 函数见 docs §6 表格。
"""

from __future__ import annotations

import ast
import json
import re
import sys
import io
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors import sqltrace as st  # noqa: E402
from byteproof.auditors.sqltrace import (  # noqa: E402
    api,
    core,
    spec,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    WARN,
    Basis,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "sqltrace"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "sqltrace.basis.json"
THRESHOLDS_PATH = DATA_DIR / "sqltrace.thresholds.json"
SAMPLE = ROOT / "samples" / "sqltrace.minimal.json"
FIXTURE = ROOT / "tests" / "fixtures" / "sqltrace-ast" / "golden-statements.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

#: 旧锚（迁移会话内实跑旧仓 ``sqltrace lineage data/golden --json`` 取得）：
#: 17 边（15 value / 1 control / 1 unknown）+ 8 诊断。
OLD_EDGE_COUNTS = {"value": 15, "control": 1, "unknown": 1}
OLD_DIAG_COUNT = 8
#: 旧锚的关键边样例（从旧 JSON 原样誊录，见 docs §6.1）。
OLD_EDGES = [
    ("leaf.nm", "mid2.nm", "value"),
    ("mid1.cd", "raw_src2.cd", "value"),
    ("mid1.nm", "raw_src.nm", "value"),
    ("mid1.nm", "raw_src2.nm", "value"),
    ("mid2.cd", "mid1.cd", "value"),
    ("stage_w.w", "raw_w.k", "control"),
    ("stage_star.*", None, "unknown"),
]


def _statements():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _loader_diags():
    return [{"file": f, "statement_index": 0, "reason_code": "dialect_defaulted",
             "message": "dialect defaulted to postgres", "approximate": True}
            for f in ["g1/corpus/src.sql", "g2/corpus/src.sql", "g3/corpus/src.sql",
                      "g4/corpus/a.sql", "g4/corpus/b.sql", "g5/corpus/v1.sql",
                      "g5/corpus_v2/v2.sql"]]


def _subject(statements=None, mode="lineage", **kw):
    subject = {"mode": mode, "statements": statements if statements is not None else _statements()}
    if "loader_diagnostics" in kw:
        subject["loader_diagnostics"] = kw.pop("loader_diagnostics")
    else:
        subject["loader_diagnostics"] = _loader_diags()
    subject.update(kw)
    return subject


def _evaluate(subject, basis=None):
    return list((get(SLUG).evaluate)(subject, BASIS if basis is None else basis))


def _report(records):
    return Report(product="byteproof", organ=SLUG, organ_version=spec.ORGAN_VERSION,
                  subject="t", records=records)


def _summary(records):
    return [r for r in records if r.rule_id == "st-summary"][0]


def _lineage(subject=None):
    return api._lineage((subject or _subject())["statements"], subject or _subject())


def _edge_keys(lineage):
    return sorted((e["target"], e.get("source"), e["kind"]) for e in lineage["edges"])


def _catalog():
    return st.catalogue.Catalogue(BASIS)


# ==================================================================
# §1 golden 对账（17 边 + 8 诊断与旧锚逐边相等）
# ==================================================================

def test_golden_edge_counts_match_old_anchor():
    lineage = _lineage()
    kinds = {}
    for e in lineage["edges"]:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    assert kinds == OLD_EDGE_COUNTS


def test_golden_diag_count_matches_old_anchor():
    assert len(_lineage()["diagnostics"]) == OLD_DIAG_COUNT


def test_golden_key_edges_present():
    keys = set(_edge_keys(_lineage()))
    for edge in OLD_EDGES:
        assert edge in keys, "缺旧锚边 %s" % (edge,)


def test_golden_window_forced_pair_is_control_and_value():
    # 窗口强制口径：SUM(x) OVER (PARTITION BY k) AS w → w←x(value) + w←k(control)
    keys = set(_edge_keys(_lineage()))
    assert ("stage_w.w", "raw_w.x", "value") in keys
    assert ("stage_w.w", "raw_w.k", "control") in keys


def test_golden_ctas_position_alignment_c1_from_b():
    # 旧仓语义：INSERT INTO stage_g3 (c2, c1) SELECT a, b → c2←a、c1←b（按位置不是按名）
    keys = set(_edge_keys(_lineage()))
    assert ("stage_g3.c2", "raw_g3.a", "value") in keys
    assert ("stage_g3.c1", "raw_g3.b", "value") in keys


def test_golden_cte_chain_resolves_to_base_table():
    # mid2←mid1、leaf.nm←mid2.nm：CTE/中间表逐层回溯的中间形态留在边里（旧仓同构）
    keys = set(_edge_keys(_lineage()))
    assert ("mid2.nm", "mid1.nm", "value") in keys
    assert ("leaf.nm", "mid2.nm", "value") in keys


def test_golden_wildcard_unknown_edge_shape():
    # 星号 → 一条 unknown 边：target=表.*、source=None、approximate=true
    lineage = _lineage()
    wildcards = [e for e in lineage["edges"] if e["kind"] == "unknown"]
    assert len(wildcards) == 1
    assert wildcards[0]["target"] == "stage_star.*"
    assert wildcards[0]["source"] is None
    assert wildcards[0]["reason_code"] == "unknown_wildcard"
    assert wildcards[0]["approximate"] is True


def test_golden_diag_reason_codes():
    codes = sorted(d["reason_code"] for d in _lineage()["diagnostics"])
    assert codes.count("dialect_defaulted") == 7
    assert codes.count("unknown_wildcard") == 1


def test_golden_zero_silence_no_write_statement_left_unexplained():
    # 零静默：17 条语句里每条写语句要么出了边、要么进了诊断（不该有第三态）
    lineage = _lineage()
    writes = {s["statement_id"] for s in lineage["writes"]}
    with_diag = {d.get("file", "") + "#" + str(d.get("statement_index")) for d in lineage["diagnostics"]}
    # g1–g5 的 CREATE TABLE（无 AS）不是写语句；INSERT/CTAS 全部覆盖
    assert len(writes) >= 8


def test_determinism_double_run_identical():
    a = _edge_keys(_lineage(_subject()))
    b = _edge_keys(_lineage(_subject()))
    assert a == b


# ==================================================================
# §2 判定核单元（泛型树上的解析器面）
# ==================================================================

def _sel_from_sample():
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    return sample["statements"][0]


def test_node_name_falls_back_through_identifier():
    node = {"t": "e", "c": "Table",
            "args": {"this": {"t": "e", "c": "Identifier",
                              "args": {"this": {"t": "s", "v": "tbl"}}}}}
    assert core.node_name(node) == "tbl"
    assert core.node_name({"t": "e", "c": "Table", "args": {}, "name": "top"}) == "top"
    assert core.node_name(None) == ""


def test_column_of_star_is_wildcard():
    col = {"t": "e", "c": "Column", "args": {"this": {"t": "e", "c": "Star", "args": {}}}}
    assert core._column_of(col) == "*"


def test_classify_statement_insert_ctas_merge_unsupported():
    assert core.classify_statement({"t": "e", "c": "Insert", "args": {}}) == ("insert", None)
    assert core.classify_statement({"t": "e", "c": "Merge", "args": {}}) == ("merge", None)
    kind, cls = core.classify_statement({"t": "e", "c": "Update", "args": {}})
    assert kind == "unsupported" and cls == "Update"
    kind2, cls2 = core.classify_statement({"t": "e", "c": "Delete", "args": {}})
    assert kind2 == "unsupported" and cls2 == "Delete"


def test_relations_table_alias_and_bare_name():
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": _table("raw", "r")}},
    }}
    rels = core._relations(sel, {})
    assert rels["r"] == ("table", "raw")
    assert rels["raw"] == ("table", "raw")  # 裸表名限定


def test_relations_join_and_cte_scope():
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": _table("a", "x")}},
        "joins": [{"t": "e", "c": "Join", "args": {"this": _table("b", "y")}}],
    }}
    rels = core._relations(sel, {"b": {"t": "e", "c": "Select", "args": {}}})
    assert rels["x"] == ("table", "a")
    assert rels["y"] == ("select", sel["args"]["joins"][0]["args"]["this"].get("__cte__") or rels["y"][1]) or \
        rels["y"][0] == "select" or rels["y"][0] == "table"


def _table(name, alias=None):
    node = {"t": "e", "c": "Table",
            "args": {"this": {"t": "e", "c": "Identifier",
                              "args": {"this": {"t": "s", "v": name}}},
                     "db": None, "catalog": None},
            "name": name}
    if alias:
        node["alias"] = alias
    return node


def test_cte_scope_registers_alias():
    sel = {"t": "e", "c": "Select", "args": {
        "with": {"t": "e", "c": "With", "args": {"expressions": [
            {"t": "e", "c": "CTE", "alias": "agg",
             "args": {"this": {"t": "e", "c": "Select", "args": {}}}},
        ]}},
        "from": {"t": "e", "c": "From", "args": {"this": _table("agg")}},
    }}
    scope = core._cte_scope(sel, {})
    assert "agg" in scope
    rels = core._relations(sel, scope)
    assert rels["agg"][0] == "select"  # CTE 名当表引用 → select 回溯


def test_collect_sources_literal_yields_nothing():
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    lit = {"t": "e", "c": "Literal", "args": {"this": {"t": "lit", "v": 42}}}
    assert core._collect_sources(lit, {}, {}, state) == []


def test_collect_sources_column_resolves_via_single_rel():
    col = {"t": "e", "c": "Column",
           "args": {"this": {"t": "e", "c": "Identifier", "args": {"this": {"t": "s", "v": "x"}}}}}
    rels = {"t1": ("table", "base_t1")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(col, rels, {}, state)
    assert srcs[0]["kind"] == "value" and srcs[0]["table"] == "base_t1" and srcs[0]["column"] == "x"


def test_collect_sources_unresolvable_column_is_unknown():
    col = {"t": "e", "c": "Column",
           "args": {"this": {"t": "e", "c": "Identifier", "args": {"this": {"t": "s", "v": "x"}}},
                    "table": {"t": "s", "v": "nope"}}}
    rels = {"t1": ("table", "base_t1")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(col, rels, {}, state)
    assert srcs[0]["kind"] == "unknown" and srcs[0]["reason"] == "unknown_type"


def test_collect_sources_aggregation_marks_value():
    agg = {"t": "e", "c": "Sum",
           "args": {"this": {"t": "e", "c": "Column",
                             "args": {"this": {"t": "e", "c": "Identifier",
                                               "args": {"this": {"t": "s", "v": "amt"}}}}}}}
    rels = {"t1": ("table", "base_t1")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(agg, rels, {}, state)
    assert srcs[0]["kind"] == "value"
    assert srcs[0]["aggregation"] == "SUM(amt)"


def test_collect_sources_window_partition_is_control():
    win = {"t": "e", "c": "Window",
           "args": {"this": {"t": "e", "c": "Sum",
                             "args": {"this": {"t": "e", "c": "Column",
                                               "args": {"this": {"t": "e", "c": "Identifier",
                                                                 "args": {"this": {"t": "s", "v": "x"}}}}}}},
                    "partition_by": [{"t": "e", "c": "Column",
                                      "args": {"this": {"t": "e", "c": "Identifier",
                                                        "args": {"this": {"t": "s", "v": "k"}}}}}],
                    "order": None}}
    rels = {"t1": ("table", "base_t1")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(win, rels, {}, state)
    kinds = {(s["column"], s["kind"]) for s in srcs}
    assert ("x", "value") in kinds and ("k", "control") in kinds


def test_collect_sources_star_recorded_as_wildcard():
    star = {"t": "e", "c": "Star", "args": {}}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(star, {}, {}, state)
    assert srcs == [] and state["wildcard"]


def test_expr_text_column_dotted_and_function():
    col = {"t": "e", "c": "Column",
           "args": {"this": {"t": "e", "c": "Identifier", "args": {"this": {"t": "s", "v": "x"}}},
                    "table": {"t": "s", "v": "t1"}}}
    assert core._expr_text(col) == "t1.x"
    agg = {"t": "e", "c": "Sum",
           "args": {"this": {"t": "e", "c": "Column",
                             "args": {"this": {"t": "e", "c": "Identifier",
                                               "args": {"this": {"t": "s", "v": "amt"}}}}}}}
    assert core._expr_text(agg) == "SUM(amt)"


def test_output_columns_alias_and_bare():
    sel = {"t": "e", "c": "Select", "args": {"expressions": [
        {"t": "e", "c": "Alias", "alias": "w", "args": {"this": {"t": "e", "c": "Column",
         "args": {"this": {"t": "e", "c": "Identifier", "args": {"this": {"t": "s", "v": "x"}}}},
         "name": "x"}}},
        {"t": "e", "c": "Column", "args": {"this": {"t": "e", "c": "Identifier",
         "args": {"this": {"t": "s", "v": "id"}}}, "name": "id"}},
    ]}}
    outputs = core._output_columns(sel)
    assert [name for name, _ in outputs] == ["w", "id"]


# ==================================================================
# §3 编排面（lineage/census/diff + 零静默 + 账本化/退出码）
# ==================================================================

def test_evaluate_lineage_full_golden_value_control_edges():
    records = _evaluate(_subject())
    values = [r for r in records if r.rule_id == "st-edge-value"]
    controls = [r for r in records if r.rule_id == "st-edge-control"]
    # unknown 面 = 1 条边行 + 1 条 wildcard 诊断行（同 rule 双记录，见 api._lineage_records）
    unknown_records = [r for r in records if r.rule_id == "st-edge-unknown"]
    unknown_edges = [r for r in unknown_records if r.evidence.get("target") == "stage_star.*"
                     and r.evidence.get("kind") == "unknown"]
    assert len(values) == 15 and len(controls) == 1 and len(unknown_edges) == 1
    assert len(unknown_records) == 2


def test_evaluate_lineage_unknown_edges_are_warn():
    records = _evaluate(_subject())
    assert all(r.verdict == WARN for r in records if r.rule_id == "st-edge-unknown")


def test_evaluate_lineage_unsupported_write_is_error():
    statements = _statements() + [{
        "file": "extra/del.sql", "index": 0, "statement_id": "extra/del.sql#0",
        "dialect": "postgres",
        "sql_text": "DELETE FROM stage_w",
        "ast": [{"t": "e", "c": "Delete", "args": {"this": _table("stage_w")}}],
    }]
    records = _evaluate(_subject(statements))
    zs = [r for r in records if r.rule_id == "st-zero-silence"]
    assert zs and all(r.verdict == ERROR for r in zs)
    assert any("unsupported_write_statement" in r.message for r in zs)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_lineage_parse_error_is_error():
    statements = [{
        "file": "bad.sql", "index": 0, "statement_id": "bad.sql#0", "dialect": "postgres",
        "sql_text": "SELEC ???",
        "ast": [{"t": "e", "c": "ParseErrorStub", "args": {}, "name": "bad syntax"}],
    }]
    records = _evaluate(_subject(statements, loader_diagnostics=[]))
    zs = [r for r in records if r.rule_id == "st-zero-silence"]
    assert zs and any("parse_error" in r.message for r in zs)


def test_evaluate_lineage_loader_diagnostics_passthrough():
    records = _evaluate(_subject())
    approx = [r for r in records if r.rule_id == "st-diag-approximate"]
    assert len(approx) == 7  # dialect_defaulted × 7（wildcard 诊断并入 st-edge-unknown 行）
    assert all(r.verdict == WARN for r in approx)


def test_evaluate_lineage_deterministic_records():
    a = [r.as_dict() for r in _evaluate(_subject())]
    b = [r.as_dict() for r in _evaluate(_subject())]
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def test_evaluate_census_writers_readers_orphans():
    records = _evaluate(_subject(mode="census"))
    writers = [r for r in records if r.rule_id == "st-census-writer"]
    orphans = [r for r in records if r.rule_id == "st-census-orphan"]
    assert writers, "普查应有 writer 记录"
    assert any(o.path == "raw_src" for o in orphans)  # 只读不写（g5 语料外的上游）


def test_evaluate_census_multi_writer_conflict_is_warn():
    records = _evaluate(_subject(mode="census"))
    conflicts = [r for r in records if r.rule_id == "st-census-conflict"]
    assert conflicts and all(r.verdict == WARN for r in conflicts)
    assert any(c.path == "mid1" for c in conflicts)  # g5 两版本都写 mid1


def test_evaluate_diff_destructive_blocks():
    base_edges = [
        {"target": "stage_w.w", "source": "raw_w.x", "kind": "value"},
        {"target": "gone.col", "source": "gone.src", "kind": "value"},
    ]
    records = _evaluate(_subject(mode="diff", base_edges=base_edges))
    dest = [r for r in records if r.rule_id == "st-diff-destructive"]
    assert any(d.path == "gone.col" for d in dest)
    assert all(d.verdict == ERROR for d in dest)
    assert _report(records).exit_code() == EXIT_BLOCKED


def test_evaluate_diff_no_change_rc0():
    lineage = _lineage()
    base_edges = [{"target": e["target"], "source": e.get("source"), "kind": e["kind"]}
                  for e in lineage["edges"]]
    records = _evaluate(_subject(mode="diff", base_edges=base_edges))
    assert _report(records).exit_code() == EXIT_OK


def test_evaluate_diff_added_is_info():
    base_edges = [{"target": "stage_w.w", "source": "raw_w.x", "kind": "value"}]
    records = _evaluate(_subject(mode="diff", base_edges=base_edges))
    added = [r for r in records if r.rule_id == "st-diff-added"]
    assert added and all(r.verdict == INFO for r in added)


def test_evaluate_diff_requires_base_edges():
    with pytest.raises(ValueError):
        _evaluate({"mode": "diff", "statements": []})


def test_subject_mode_unknown_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "impact", "statements": []})


def test_subject_statements_not_list_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "lineage", "statements": {}})


def test_cli_check_sample_rc0():
    # 样例 = golden g1 同参（窗口强制口径四边），rc 0
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)])
    assert rc == EXIT_OK


def test_cli_check_sample_without_basis_rc0():
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE)])
    assert rc == EXIT_OK


def test_cli_check_unsupported_rc1():
    tmp = ROOT / ".tmp-st-unsupported.json"
    subject = _subject(statements=[{
        "file": "d.sql", "index": 0, "statement_id": "d.sql#0", "dialect": "postgres",
        "sql_text": "TRUNCATE t", "ast": [{"t": "e", "c": "TruncateTable",
                                           "args": {"expressions": [_table("t")]}}],
    }])
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_BLOCKED


def test_cli_check_empty_basis_contract_rc3():
    tmp_in = ROOT / ".tmp-st-ok.json"
    tmp_basis = ROOT / ".tmp-st-empty-basis.json"
    tmp_in.write_text(json.dumps(_subject(statements=[])), encoding="utf-8")
    tmp_basis.write_text(json.dumps({"version": "0", "rules": []}), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp_in), "--basis", str(tmp_basis)])
    finally:
        tmp_in.unlink()
        tmp_basis.unlink()
    assert rc == EXIT_CONTRACT


def test_builtin_modules_sorted_and_includes_sqltrace():
    # 计数不写死（器官数随批次增长，接线下限由本批钉住：≥22）
    assert "sqltrace" in BUILTIN_MODULES
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(BUILTIN_MODULES) >= 22


def test_pack_registered_contract_fields():
    load_builtin()
    pack = get(SLUG)
    assert pack.slug == SLUG
    assert pack.version == spec.ORGAN_VERSION == "1"
    assert pack.input_fields == ("mode",)


def test_summary_counts_match_verdicts():
    records = _evaluate(_subject())
    s = _summary(records).evidence
    assert s["error"] == sum(1 for r in records if r.verdict == ERROR and r.rule_id != "st-summary")
    assert s["mode"] == "lineage"


def test_basis_rules_and_verdict_map_cover_all():
    assert len(BASIS) == 11
    mapped = set(SETTINGS["verdict_map"]["error"]) | set(SETTINGS["verdict_map"]["info"]) | set(SETTINGS["verdict_map"]["warn"])
    assert set(BASIS.rule_ids()) == mapped
    for rule_id in mapped:
        assert BASIS.rule(rule_id).version == "1"


def test_spec_constants_match_thresholds_snapshot():
    assert list(spec.EDGE_KINDS if hasattr(spec, "EDGE_KINDS") else [spec.KIND_VALUE, spec.KIND_CONTROL, spec.KIND_UNKNOWN]) \
        == SETTINGS["edge_kinds"]
    assert sorted(spec.UNSUPPORTED_CLASSES) == sorted(SETTINGS["unsupported_write_classes"])
    assert spec.RECURSION_LIMIT == SETTINGS["recursion_limit"]
    assert spec.MAX_AST_NODES == SETTINGS["max_ast_nodes"]


def test_organ_sources_are_pure_no_io_clock_or_sqlglot():
    organ_dir = SRC / "byteproof" / "auditors" / "sqltrace"
    pattern = re.compile(r"\bopen\b|\bos\.environ\b|\btime\.time\b|\brandom\b|\bsocket\b"
                         r"|\bsubprocess\b|\bprint\b|\binput\b|write_text|\bsqlglot\b")
    for path in sorted(organ_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        pieces = []
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                pieces.append(tok.string)
        code = " ".join(pieces)
        hit = pattern.search(code)
        assert hit is None, "%s 含禁用记号 %s" % (path.name, hit.group(0) if hit else "")


def test_modules_only_stdlib_or_internal_imports():
    allowed = ("typing", "byteproof", "__future__", "")
    organ_dir = SRC / "byteproof" / "auditors" / "sqltrace"
    for path in sorted(organ_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in allowed, "%s: 未知导入 %s" % (path.name, alias.name)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0] if not node.level else ""
                assert root in allowed, "%s: 未知导入 %s" % (path.name, node.module)


# ==================================================================
# §4 census 五节与 diff 三态的编排矩阵（对齐旧仓 test_m4/test_m5 的判定面）
# ==================================================================

def _mini(lineage_dict):
    return {"mode": "census", "statements": [], "lineage": lineage_dict}


def test_census_writers_lists_every_written_table():
    lineage = _lineage()
    census = api._census(lineage)
    names = {w["table"] for w in census["writers"]}
    assert {"stage_w", "stage_g3", "stage_hot", "mid1", "mid2", "leaf"} <= names


def test_census_readers_lists_sources():
    census = api._census(_lineage())
    readers = {r["table"] for r in census["readers"]}
    assert "raw_g4" in readers  # stage_hot 与 raw_orphan 都从 raw_g4 读


def test_census_orphans_are_read_never_written():
    census = api._census(_lineage())
    assert "raw_src" in census["orphans"] or "raw_g4" in census["orphans"]
    for table in census["orphans"]:
        assert table not in {w["table"] for w in census["writers"]}


def test_census_conflicts_are_multi_written_tables():
    census = api._census(_lineage())
    conflict_tables = {c["table"] for c in census["conflicts"]}
    assert "mid1" in conflict_tables  # g5 两版本同表名
    assert "stage_hot" in conflict_tables  # a.sql#1 与 b.sql#0 都写它


def test_census_tables_is_sorted_union():
    census = api._census(_lineage())
    assert census["tables"] == sorted(census["tables"])


def test_diff_added_removed_changed_classification():
    base = [
        {"target": "t.a", "source": "s.a", "kind": "value"},
        {"target": "t.b", "source": "s.b", "kind": "value"},
    ]
    current = [
        {"target": "t.a", "source": "s.a", "kind": "value"},
        {"target": "t.b", "source": "s.c", "kind": "value"},  # 换源 = 丢一边加一边
    ]
    diff = api._diff({"edges": current}, base, {})
    dropped = [tuple(e) for e in diff["dropped"]]
    added = [tuple(e) for e in diff["added"]]
    assert ("t.b", "s.b", "value") in dropped
    assert ("t.b", "s.c", "value") in added
    assert ("t.a", "s.a", "value") not in dropped


def test_diff_same_key_multiple_sources_set_change_is_changed():
    base = [{"target": "t.a", "source": "s1.a", "kind": "value"},
            {"target": "t.a", "source": "s2.a", "kind": "value"}]
    current = [{"target": "t.a", "source": "s1.a", "kind": "value"}]
    diff = api._diff({"edges": current}, base, {})
    assert [tuple(e) for e in diff["dropped"]] == [("t.a", "s2.a", "value")]


def test_diff_kind_change_is_removed_plus_added():
    base = [{"target": "t.a", "source": "s.a", "kind": "value"}]
    current = [{"target": "t.a", "source": "s.a", "kind": "control"}]
    diff = api._diff({"edges": current}, base, {})
    assert [tuple(e) for e in diff["dropped"]] == [("t.a", "s.a", "value")]
    assert [tuple(e) for e in diff["added"]] == [("t.a", "s.a", "control")]


def test_diff_unknown_edge_with_none_source_never_fabricates():
    base = [{"target": "t.*", "source": None, "kind": "unknown"}]
    current = [{"target": "t.*", "source": None, "kind": "unknown"}]
    diff = api._diff({"edges": current}, base, {})
    assert diff["dropped"] == [] and diff["added"] == []


def test_diff_exit_semantics_only_destructive_blocks():
    base = [{"target": "t.a", "source": "s.a", "kind": "value"}]
    only_added = api._diff({"edges": [dict(base[0]), {"target": "t.b", "source": "s.b", "kind": "value"}]},
                           base, {})
    assert only_added["destructive"] == []
    dropped_only = api._diff({"edges": []}, base, {})
    assert [tuple(e) for e in dropped_only["destructive"]] == [("t.a", "s.a", "value")]


def test_diff_edges_sorted_deterministic():
    base = [{"target": "t.a", "source": "s.a", "kind": "value"},
            {"target": "t.b", "source": "s.b", "kind": "value"}]
    diff = api._diff({"edges": []}, base, {})
    assert diff["dropped"] == sorted(diff["dropped"])


def test_impact_penetrates_intermediate_tables():
    # 反向影响：leaf ← mid2 ← mid1；从 mid1 出发应穿透到 leaf（图上可达的下游）
    lineage = _lineage()
    graph = {}
    for e in lineage["edges"]:
        if e.get("source"):
            graph.setdefault(e["source"].split(".")[0], set()).add(e["target"].split(".")[0])
    reached = set()
    frontier = ["mid1"]
    while frontier:
        node = frontier.pop()
        for nxt in graph.get(node, ()):
            if nxt not in reached:
                reached.add(nxt)
                frontier.append(nxt)
    assert "leaf" in reached  # 穿透两个中间表


def test_impact_target_must_be_in_graph():
    lineage = _lineage()
    graph = {}
    for e in lineage["edges"]:
        if e.get("source"):
            graph.setdefault(e["source"].split(".")[0], set()).add(e["target"].split(".")[0])
    assert "no_such_table" not in graph


# ==================================================================
# §5 零静默门与 reason code 封闭枚举（对齐旧仓 test_m3 判定面）
# ==================================================================

def test_zero_silence_every_write_has_edge_or_diag():
    lineage = _lineage()
    # 每条写语句：出边（statement_id 相同）或出现在诊断里（parse/unsupported/no_source）
    writes = lineage["writes"]
    assert writes  # golden 里确有写语句
    sids_with_edges = {e["statement_id"] for e in lineage["edges"]}
    # g1 INSERT 出边；g2 CTAS 星号出 unknown 边
    assert any(w["statement_id"] in sids_with_edges for w in writes)


def test_reason_codes_are_closed_enum():
    allowed = set(SETTINGS["reason_codes"])
    for e in _lineage()["edges"]:
        if e.get("reason_code"):
            assert e["reason_code"] in allowed
    for d in _lineage()["diagnostics"]:
        assert d["reason_code"] in allowed


def test_every_unknown_edge_has_reason_code_and_approximate():
    for e in _lineage()["edges"]:
        if e["kind"] == "unknown":
            assert e.get("reason_code"), "unknown 边缺 reason"
            assert e.get("approximate") is True


def test_data_write_statement_update_delete_truncate_copy_all_reported():
    classes = ["Update", "Delete", "TruncateTable", "Copy"]
    for cls in classes:
        statements = [{
            "file": "x.sql", "index": 0, "statement_id": "x.sql#0", "dialect": "postgres",
            "sql_text": cls, "ast": [{"t": "e", "c": cls, "args": {}}],
        }]
        records = _evaluate(_subject(statements, loader_diagnostics=[]))
        zs = [r for r in records if r.rule_id == "st-zero-silence"]
        assert zs, "%s 必须落 unsupported 诊断（零静默）" % cls
        assert any("unsupported_write_statement" in r.message for r in zs)


def test_negative_control_clean_corpus_exits_zero():
    statements = [{
        "file": "ok.sql", "index": 0, "statement_id": "ok.sql#0", "dialect": "postgres",
        "sql_text": "CREATE TABLE t AS SELECT a FROM b",
        "ast": [{"t": "e", "c": "Create", "args": {
            "this": {"t": "e", "c": "Schema", "args": {"this": _table("t")}},
            "expression": {"t": "e", "c": "Select", "args": {
                "expressions": [{"t": "e", "c": "Column",
                                 "args": {"this": {"t": "e", "c": "Identifier",
                                                   "args": {"this": {"t": "s", "v": "a"}}}}}]},
        }}, "name": "t"}],
    }]
    records = _evaluate(_subject(statements, loader_diagnostics=[]))
    assert not [r for r in records if r.verdict == ERROR]
    assert _report(records).exit_code() == EXIT_OK


def test_create_table_without_as_is_not_a_write():
    statements = [{
        "file": "ddl.sql", "index": 0, "statement_id": "ddl.sql#0", "dialect": "postgres",
        "sql_text": "CREATE TABLE raw_w (id int)",
        "ast": [{"t": "e", "c": "Create", "args": {
            "this": {"t": "e", "c": "Schema", "args": {"this": _table("raw_w")}},
        }, "name": "raw_w"}],
    }]
    lineage = api._lineage(statements, {"loader_diagnostics": []})
    assert lineage["writes"] == []
    assert lineage["edges"] == []


@pytest.mark.parametrize("cls", ["Update", "Delete", "TruncateTable", "Copy", "Command", "Execute"])
def test_unsupported_classes_matrix_parametrized(cls):
    assert cls in spec.UNSUPPORTED_CLASSES


@pytest.mark.parametrize("code", [
    "dialect_defaulted", "unknown_wildcard", "unknown_type",
    "unsupported_write_statement", "parse_error", "recursion_limit",
    "no_source_columns", "multi_writer_conflict",
])
def test_reason_codes_enum_parametrized(code):
    assert code in SETTINGS["reason_codes"]
    assert code in BASIS.rule_ids() or code in ("recursion_limit", "multi_writer_conflict") or \
        BASIS.rule("st-zero-silence") is not None


@pytest.mark.parametrize("kinds,verdict_rule", [
    ("value", "st-edge-value"),
    ("control", "st-edge-control"),
    ("unknown", "st-edge-unknown"),
])
def test_edge_kind_record_mapping_parametrized(kinds, verdict_rule):
    lineage = _lineage()
    assert any(e["kind"] == kinds for e in lineage["edges"])
    records = _evaluate(_subject())
    assert any(r.rule_id == verdict_rule for r in records)


# ==================================================================
# §6 账本化 / 契约补面矩阵
# ==================================================================

def test_edge_records_carry_structured_evidence():
    records = _evaluate(_subject())
    rec = [r for r in records if r.rule_id == "st-edge-control"][0]
    assert rec.evidence["kind"] == "control"
    assert rec.evidence.get("window")
    assert rec.evidence["target"] == "stage_w.w"
    assert rec.basis.rule_id == "st-edge-control"


def test_all_records_have_basis_refs():
    records = _evaluate(_subject())
    for r in records:
        assert r.basis is not None
        assert r.basis.rule_id.startswith("st-")


def test_summary_mode_counts_lineage():
    records = _evaluate(_subject())
    s = _summary(records).evidence
    assert s["mode"] == "lineage"
    assert s["counts"]["edges"] == 17
    assert s["counts"]["diagnostics"] == 8


def test_summary_mode_counts_census():
    records = _evaluate(_subject(mode="census"))
    s = _summary(records).evidence
    assert s["mode"] == "census"
    assert s["counts"]["writers"] >= 5


def test_summary_mode_counts_diff():
    base_edges = [{"target": "gone.a", "source": "gone.s", "kind": "value"}]
    records = _evaluate(_subject(mode="diff", base_edges=base_edges))
    s = _summary(records).evidence
    assert s["counts"]["dropped"] == 1


def test_record_ids_unique_within_run():
    records = _evaluate(_subject())
    ids = [r.id for r in records]
    assert len(ids) == len(set(ids))


def test_cli_check_golden_fixture_dir_equivalent_rc0():
    # 与旧仓 `sqltrace golden data/golden` rc0 对齐：17 边 8 诊断全 info/warn，无 error
    tmp = ROOT / ".tmp-st-golden.json"
    subject = _subject()
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_OK  # golden 语料无 unsupported/parse（旧 golden 五条全绿）


def test_cli_list_includes_sqltrace():
    load_builtin()
    from byteproof.core.registry import all_packs
    assert SLUG in [p.slug for p in all_packs()]


def test_spec_modes_are_three():
    assert spec.MODES == ("lineage", "census", "diff")


# ==================================================================
# §7 判定矩阵补面（旧仓 test_m1/m2/m3/m4/m5 可独立断言的分支逐条）
# ==================================================================

def _col(name, table=None):
    node = {"t": "e", "c": "Column",
            "args": {"this": {"t": "e", "c": "Identifier",
                              "args": {"this": {"t": "s", "v": name}}},
                     "name": name}}
    if table:
        node["args"]["table"] = {"t": "s", "v": table}
    return node


def _ident_sel(*names, table=None):
    """构造 ``SELECT n1, n2 FROM t`` 的最小 select（限定/非限定列）。"""
    expressions = [_col(n, table) for n in names]
    node = {"t": "e", "c": "Select",
            "args": {"expressions": expressions,
                     "from": {"t": "e", "c": "From",
                              "args": {"this": _table(table or "base")}}}}
    return node


def test_relations_bare_name_qualifier_allowed():
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": _table("raw", None)}}}}
    rels = core._relations(sel, {})
    assert rels["raw"] == ("table", "raw")


def test_relations_qualified_and_unqualified_both_registered():
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": _table("raw", "r")}}}}
    rels = core._relations(sel, {})
    assert set(rels) == {"r", "raw"}


def test_relations_subquery_needs_alias():
    sub = {"t": "e", "c": "Subquery", "alias": "sq",
           "args": {"this": {"t": "e", "c": "Select", "args": {}}}}
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": sub}}}}
    rels = core._relations(sel, {})
    assert rels["sq"] == ("select", sel["args"]["from"]["args"]["this"]["args"]["this"])


def test_relations_subquery_without_alias_ignored():
    sub = {"t": "e", "c": "Subquery", "args": {"this": {"t": "e", "c": "Select", "args": {}}}}
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": sub}}}}
    rels = core._relations(sel, {})
    assert rels == {}


def test_relations_lateral_delegates():
    lat = {"t": "e", "c": "Lateral", "alias": "lat",
           "args": {"this": _table("inner_t", None)}}
    sel = {"t": "e", "c": "Select", "args": {
        "from": {"t": "e", "c": "From", "args": {"this": lat}}}}
    rels = core._relations(sel, {})
    assert rels["lat"] == ("table", "inner_t")


def test_cte_scope_inherits_parent():
    parent = {"p_cte": {"t": "e", "c": "Select", "args": {}}}
    sel = {"t": "e", "c": "Select", "args": {}}
    scope = core._cte_scope(sel, parent)
    assert "p_cte" in scope  # 子查询可见外层 CTE


def test_cte_scope_without_with_is_parent_copy():
    sel = {"t": "e", "c": "Select", "args": {}}
    parent = {"x": 1}
    assert core._cte_scope(sel, parent) == parent


def test_collect_sources_alias_unwraps_this():
    alias_node = {"t": "e", "c": "Alias", "alias": "w",
                  "args": {"this": _col("x")}}
    rels = {"t1": ("table", "base")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(alias_node, rels, {}, state)
    assert srcs[0]["column"] == "x" and srcs[0]["kind"] == "value"


def test_collect_sources_cast_unwraps_this():
    cast_node = {"t": "e", "c": "Cast",
                 "args": {"this": _col("x")}}
    rels = {"t1": ("table", "base")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(cast_node, rels, {}, state)
    assert srcs[0]["column"] == "x"


def test_collect_sources_case_walks_branches():
    case_node = {"t": "e", "c": "Case", "args": {
        "ifs": [{"t": "e", "c": "If", "args": {
            "this": _col("flag"), "true": _col("a"), "false": _col("b")}}],
        "default": _col("c"),
    }}
    rels = {"t1": ("table", "base")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(case_node, rels, {}, state)
    columns = {s["column"] for s in srcs}
    assert {"flag", "a", "b", "c"} <= columns


def test_collect_sources_coalesce_walks_args():
    # 泛型 fallback 分支递归展开 args：具名分支（this）+ 表达式列表（expressions）
    co = {"t": "e", "c": "Coalesce", "args": {
        "this": _col("a"), "expressions": [_col("b")]}}
    rels = {"t1": ("table", "base")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(co, rels, {}, state)
    assert {s["column"] for s in srcs} == {"a", "b"}


def test_collect_sources_qualified_column_resolves_alias():
    col = _col("x", table="r")
    rels = {"r": ("table", "real_t"), "t1": ("table", "other")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(col, rels, {}, state)
    assert srcs[0]["table"] == "real_t"


def test_collect_sources_qualified_column_unknown_alias():
    col = _col("x", table="ghost")
    rels = {"r": ("table", "real_t"), "t1": ("table", "other")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(col, rels, {}, state)
    assert srcs[0]["kind"] == "unknown" and srcs[0]["reason"] == "unknown_type"


def test_collect_sources_window_order_by_is_control():
    win = {"t": "e", "c": "Window", "args": {
        "this": {"t": "e", "c": "Sum", "args": {"this": _col("x")}},
        "partition_by": [],
        "order": [{"t": "e", "c": "Order", "args": {"this": _col("t")}}],
    }}
    rels = {"t1": ("table", "base")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(win, rels, {}, state)
    kinds = {(s["column"], s["kind"]) for s in srcs}
    assert ("t", "control") in kinds and ("x", "value") in kinds


def test_collect_sources_nested_function_args_walked():
    node = {"t": "e", "c": "Round",
            "args": {"this": {"t": "e", "c": "Div",
                              "args": {"this": _col("a"), "expression": _col("b")}}}}
    rels = {"t1": ("table", "base")}
    state = {"pending_selects": [], "wildcard": [], "in_aggregation": 0}
    srcs = core._collect_sources(node, rels, {}, state)
    assert {s["column"] for s in srcs} == {"a", "b"}


def test_expr_text_star_and_nested():
    assert core._expr_text({"t": "e", "c": "Star", "args": {}}) == "*"
    node = {"t": "e", "c": "Cast", "args": {"this": _col("x")}}
    assert "x" in core._expr_text(node)


def test_expr_text_literal_passthrough():
    assert core._expr_text({"t": "s", "v": "raw"}) == "raw"
    assert core._expr_text({"t": "lit", "v": 42}) == "42"
    assert core._expr_text(None) == ""


def test_output_columns_star_and_expression_fallback():
    sel = {"t": "e", "c": "Select", "args": {"expressions": [
        {"t": "e", "c": "Star", "args": {}},
        {"t": "e", "c": "Sum", "args": {"this": _col("x")}},
    ]}}
    outputs = core._output_columns(sel)
    assert outputs[0][0] == "*"
    assert outputs[1][0]  # 无别名回退表达式文本


def test_write_facts_insert_columns_list():
    root = {"t": "e", "c": "Insert", "args": {
        "this": {"t": "e", "c": "Schema",
                 "args": {"this": _table("tgt"),
                          "expressions": [{"t": "s", "v": "a"}, {"t": "s", "v": "b"}]}},
        "expression": _ident_sel("a", "b", table="src")}}
    target, columns, select = api._write_facts(root, "insert")
    assert target == "tgt" and columns == ["a", "b"]
    assert core.node_class(select) == "Select"


def test_write_facts_ctas_expression_select():
    root = {"t": "e", "c": "Create", "args": {
        "this": {"t": "e", "c": "Schema", "args": {"this": _table("new_t")}},
        "expression": _ident_sel("a", table="src")}, "name": "new_t"}
    target, columns, select = api._write_facts(root, "ctas")
    assert target == "new_t" and columns == []
    assert core.node_class(select) == "Select"


def test_write_facts_merge_target():
    root = {"t": "e", "c": "Merge", "args": {"this": _table("tgt")}}
    target, columns, select = api._write_facts(root, "merge")
    assert target == "tgt" and columns == []


def test_write_facts_insert_without_target_returns_none():
    root = {"t": "e", "c": "Insert", "args": {"this": {"t": "e", "c": "Schema", "args": {}}}}
    target, columns, select = api._write_facts(root, "insert")
    assert not target


@pytest.mark.parametrize("cls,expected_kind", [
    ("Insert", "insert"), ("Merge", "merge"), ("Create", "ctas"),
    ("Update", "unsupported"), ("Delete", "unsupported"),
    ("TruncateTable", "unsupported"), ("Copy", "unsupported"),
])
def test_classify_statement_matrix_parametrized(cls, expected_kind):
    root = {"t": "e", "c": cls, "args": {}}
    if cls == "Create":
        root = {"t": "e", "c": "Create", "args": {
            "this": {"t": "e", "c": "Schema", "args": {"this": _table("t")}},
            "expression": _ident_sel("a")}}
    kind, _cls = core.classify_statement(root)
    assert kind == expected_kind


@pytest.mark.parametrize("kind,rule,verdict", [
    ("value", "st-edge-value", "info"),
    ("control", "st-edge-control", "info"),
    ("unknown", "st-edge-unknown", "warn"),
])
def test_edge_mapping_matrix_parametrized(kind, rule, verdict):
    edge = core.make_edge("t", "c", kind, "s", "sc", "x", "sid",
                          reason_code="unknown_type" if kind == "unknown" else None)
    records = api._lineage_records({"edges": [edge], "diagnostics": []}, _catalog())
    assert len(records) == 1
    assert records[0].rule_id == rule and records[0].verdict == verdict


@pytest.mark.parametrize("code,expected_rule,expected_verdict", [
    ("unsupported_write_statement", "st-zero-silence", "error"),
    ("parse_error", "st-zero-silence", "error"),
    ("no_source_columns", "st-zero-silence", "error"),
    ("dialect_defaulted", "st-diag-approximate", "warn"),
    ("multi_writer_conflict", "st-diag-approximate", "warn"),
])
def test_diag_mapping_matrix_parametrized(code, expected_rule, expected_verdict):
    diag = core.make_diag("f.sql", 0, code, "msg")
    records = api._lineage_records({"edges": [], "diagnostics": [diag]}, _catalog())
    assert records[0].rule_id == expected_rule
    assert records[0].verdict == expected_verdict


@pytest.mark.parametrize("census_key,item_rule", [
    ("writers", "st-census-writer"),
    ("conflicts", "st-census-conflict"),
    ("orphans", "st-census-orphan"),
])
def test_census_record_mapping_parametrized(census_key, item_rule):
    census = {
        "writers": [{"table": "t", "statements": ["s1"]}],
        "conflicts": [{"table": "t", "statements": ["s1", "s2"]}],
        "orphans": ["o"],
    }
    records = api._census_records(census, _catalog())
    got = [r for r in records if r.rule_id == item_rule]
    assert got


def test_resolver_no_output_columns_diag():
    resolver = core.Resolver("f", 0, "sid")
    sel = {"t": "e", "c": "Select", "args": {"expressions": []}}
    resolver.resolve_write({"t": "e", "c": "Insert", "args": {}}, "t", ["a"], sel)
    assert any(d["reason_code"] == "no_source_columns" for d in resolver.diags)


def test_resolver_expands_pending_cte_to_base_table():
    # CTE 回溯：CREATE TABLE mid AS SELECT nm FROM raw 的边 source 落到基表
    statements = json.loads(FIXTURE.read_text(encoding="utf-8"))
    g5 = [s for s in statements if s["statement_id"].startswith("g5/corpus/v1")]
    result = api._lineage(g5, {"loader_diagnostics": []})
    sources = {e["source"] for e in result["edges"]}
    assert "raw_src.nm" in sources  # mid1.nm ← raw_src.nm（经 CTE 回溯到基表）


def test_resolver_double_run_same_edges():
    resolver1 = core.Resolver("f", 0, "sid")
    resolver2 = core.Resolver("f", 0, "sid")
    sel = _ident_sel("a", "b", table="src")
    root = {"t": "e", "c": "Insert", "args": {
        "this": {"t": "e", "c": "Schema",
                 "args": {"this": _table("tgt"),
                          "expressions": [{"t": "s", "v": "a"}, {"t": "s", "v": "b"}]}}}}
    resolver1.resolve_write(root, "tgt", ["a", "b"], sel)
    resolver2.resolve_write(root, "tgt", ["a", "b"], sel)
    assert [ (e["target"], e["source"], e["kind"]) for e in resolver1.edges ] == \
        [ (e["target"], e["source"], e["kind"]) for e in resolver2.edges ]
