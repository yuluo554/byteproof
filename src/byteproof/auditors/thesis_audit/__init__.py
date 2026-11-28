"""器官 ``thesis-audit``：学位论文审计账本（迁自 10-7-thesis-audit-workbench，Python 源）。

旧仓是**论文审计工作台**（GUI + CLI + docx 读取 + 规则集组合）。器官只迁**判定层**：
参考文献卡校验与格式规则（字段/类型标记/作者阈值/页码/引用体例/标准时效/一致性/标点）、
正文引用对账（编号展开/标记解析/未定义与未引用/次序）、去重（标题与 DOI 归一、编辑距离、
字段冲突）、伪造信号（DOI 前缀/ISBN 校验与出版社区间/不可能组合/自引）、推荐（BM25）、
文献库指纹与篡改、综述聚类与年代缺口；AIGC 特征分档、结构检查（标题层级/摘要要素/章节）、
术语与数字用法、图表交叉引用与编号缺口、学校格式（样式/版式）、确定性 RNG。

**docx 读取 / GUI / CLI / SQLite / 规则文件加载留输入层与宿主**（D1 逐文件处置见
``docs/thesis-audit.md`` §6）：subject 携带摊平事实，判定核零第三方依赖、零 IO。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="thesis-audit",
        version=ORGAN_VERSION,
        summary="论文审计账本：参考文献八条格式规则 + 引用对账 + 去重与伪造信号 + AIGC 分档 + 结构/术语/图表/学校格式 + 确定性 RNG",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)