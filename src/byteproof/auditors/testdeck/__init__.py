"""器官 ``testdeck``：测试结果历史账本（迁自 10-19-testdeck，Python 源）。

旧仓是**终端工作台**：把多次 run 的 JUnit XML 归一到 SQLite，回答"谁在抖、谁在变慢、
这次是不是新坏"。器官只迁**判定层**：JUnit 解析（原因码 / 单项降级 / 框架三态 /
身份键）、入库幂等语义、四类分型（精确 Fraction）、p50/p95 与回归三态、两次 run 的
diff 三类、失败优先树与 summary 六字段、门禁退出码、呈现降级两条。

**SQLite 读写与 CLI/TUI/导出留输入层与宿主**（D1 逐文件处置见 ``docs/testdeck.md`` §6）：
账本在内存行集合（runs / suites / cases / occurrences）上重算，不碰磁盘、不读时钟。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="testdeck",
        version=ORGAN_VERSION,
        summary="测试历史账本：JUnit 原因码/降级 + 四类分型（精确有理数）+ p50/p95 回归三态 + 两次 run diff 三类 + 失败优先树 + 门禁",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)