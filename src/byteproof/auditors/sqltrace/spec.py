"""口径面（迁自 10-20-sqltrace 的 constants + §4.1 判定顺序 + 零静默纪律）。

规则 id 前缀 ``st-``；边 kind 三值（value/control/unknown）与 reason code 词表
原样保留（机器可读，零静默）。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

MODES = ("lineage", "census", "diff")
DEFAULT_MODE = "lineage"

#: 边 kind 三值。
KIND_VALUE = "value"
KIND_CONTROL = "control"
KIND_UNKNOWN = "unknown"

#: reason code（data/README.md §四 词表摘录；器官覆盖其判定核子集）。
R_DIALECT_DEFAULTED = "dialect_defaulted"
R_UNKNOWN_WILDCARD = "unknown_wildcard"
R_UNKNOWN_TYPE = "unknown_type"
R_UNSUPPORTED_WRITE_STATEMENT = "unsupported_write_statement"
R_PARSE_ERROR = "parse_error"
R_RECURSION_LIMIT = "recursion_limit"
R_NO_SOURCE_COLUMNS = "no_source_columns"

#: 写语句分类（零静默：后四类不做列级血缘 → 显式诊断）。
WRITE_INSERT = "insert"
WRITE_CTAS = "ctas"
WRITE_MERGE = "merge"
UNSUPPORTED_CLASSES = {
    "Update": "update",
    "Delete": "delete",
    "TruncateTable": "truncate",
    "Copy": "copy",
    "Command": "command",
    "Execute": "execute",
}

#: 聚合函数类名（SUM/COUNT/AVG/MIN/MAX 及变体）：参数是 value 边、聚合标注。
AGGREGATE_CLASSES = frozenset({
    "Sum", "Count", "Avg", "Min", "Max", "Total", "ArrayAgg", "Stddev", "StddevPop",
    "StddevSamp", "Variance", "VarPop", "VarSamp", "Median", "ApproxQuantile",
})

#: 窗口：PARTITION BY / ORDER BY 参数 → control 边。
WINDOW_CLASS = "Window"

#: 递归上限（constants.RECURSION_LIMIT / MAX_AST_NODES 留档）。
RECURSION_LIMIT = 100
MAX_AST_NODES = 200000
