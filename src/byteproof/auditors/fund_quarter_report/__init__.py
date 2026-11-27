"""器官 ``fund-quarter-report``：基金季报工件 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``funddiff`` 回答「这一季我的基金换了什么」，本器官回答「这份季报工件哪里不对、
依据是哪条规则」：五态 diff 的异常行、双口径冲突、失败季；经理变更的未解析与标签漂移；
规模六字段的缺失/零值/单位；报告正文的合规禁词；披露窗口三态。

**没有搬**：抓取（东财 / 巨潮 / 证监会 eid）、HTML 页面解析、配置包加载与 MANIFEST 冻结、
自选清单存储、报告渲染、基准、系统时钟。逐条处置见 ``docs/fund-quarter-report.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="fund-quarter-report",
        version=ORGAN_VERSION,
        summary="基金季报工件缺陷账本：五态 diff 异常行 + 经理分类 + 规模缺失/零值 + 合规与披露",
        input_fields=("period", "holdings"),
        evaluate=evaluate,
    )
)