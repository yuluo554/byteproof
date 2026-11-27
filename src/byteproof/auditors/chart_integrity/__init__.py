"""器官 ``chart-integrity``：图表工件 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``chartaudit`` 回答「这张图能不能发布」，本器官回答「这份图表工件哪里不可复核、
依据是哪条规则」：九条反误导规则、逐值溯源完备性、样本量门禁、误差棒来源真实性。

**没有搬**：CSV 解析、spec 解析层、HTML 渲染与几何包、发布门、bench、冻结数据生成。
逐条处置见 ``docs/chart-integrity.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="chart-integrity",
        version=ORGAN_VERSION,
        summary="图表工件缺陷账本：九条反误导规则 + 逐值溯源 + 样本量门禁 + 误差棒来源",
        input_fields=("dataset", "spec", "provenance"),
        evaluate=evaluate,
    )
)