"""器官 ``artifact-drift``：两份已产出工件 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``bdiff`` 回答「这是哪一类差异、有几处、归一化后还剩多少真差异、最少改哪几项」，
本器官回答同一组问题并把每处差异落成带规则依据的账本条目。

**没有搬**：归档装载与字节解析（tar/zip/gzip/whl/jar/OCI、ELF/PE/Mach-O）、facts 抽取、
report.md、CLI、发布门、合成样张生成。逐条处置见 ``docs/artifact-drift.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="artifact-drift",
        version=ORGAN_VERSION,
        summary="构建产物差异账本：结构对齐 + T1–T12 归因 + 残留字节 + 最小原因集",
        input_fields=("left", "right"),
        evaluate=evaluate,
    )
)