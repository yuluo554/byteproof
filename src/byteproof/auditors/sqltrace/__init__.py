"""器官 ``sqltrace``：SQL 值/控制双通道血缘账本（迁自 10-20-sqltrace，Python 源）。

旧仓三个切口：值边 vs 控制边分型（``SUM(x) OVER (PARTITION BY k) AS w`` →
``w←x``(value) + ``w←k``(control)）、写入者普查五节、git 维度 lineage diff 闸门。
正确性纪律：value 边精确率 100%（宁可 unknown 不得假边）；每档降级带机器可读
reason code（**零静默**：每条写语句有边或有诊断）；同输入两次运行字节级一致。

**sqlglot 解析留输入层**：subject 携带解析后的泛型 AST 树
（``{"t":"e","c":<类名>,"args":{...}}``），器官在其上移植旧仓 ``_Resolver`` 的判定面
（关系收集 / CTE 回溯 / §4.1 判定顺序 / 窗口强制口径）。判定核零第三方依赖。
逐条处置见 ``docs/sqltrace.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="sqltrace",
        version=ORGAN_VERSION,
        summary="SQL 血缘账本：值/控制双通道分型 + 窗口强制口径 + 写入者普查五节 + lineage diff 闸门 + 零静默诊断",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)
