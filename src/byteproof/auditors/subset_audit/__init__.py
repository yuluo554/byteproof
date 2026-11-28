"""器官 ``subset-audit``：字体子集产物体检账本（迁自 10-21-subset-audit，Python 源）。

旧仓审的是**产物，不是字体项目**：输入 = 原字体 + 子集字体 + 必须支持的字符集；
输出 = 子集是否真覆盖、GSUB/GPOS 是否被弄坏、元数据是否被剥掉。三个判定模块：
coverage-diff（§六.2 三分类 + 闭包计数 + 分区计数 + 回退链建议）、layout-survival
（§六.5 三元组差集 + 连字码位差分 + 两个 SKIPPED 理由不合并）、metadata（§六.9
name 存活三分类 + 码页 bit0 + Unicode 位域过度声明 + maxp 独立量 + 首末码位）。

**fontTools 读取留输入层**：subject 携带摊平事实（cmap 映射 / OS/2 位域 / nameID /
布局摊平 / OS2_UNICODE_RANGES 表——旧仓"不复制第二套口径"的纪律保持为经 subject 供表）。
判定核零第三方依赖；Finding 排序口径（module → severity 序 → primary_key）1:1 保留。
逐条处置见 ``docs/subset-audit.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="subset-audit",
        version=ORGAN_VERSION,
        summary="字体子集产物账本：覆盖三分类（缺源/丢产物）+ GSUB/GPOS 三元组与连字差分 + name 存活与 OS/2 位域过度声明",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)
