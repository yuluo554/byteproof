"""器官 ``bookmark-doctor``：收藏夹体检账本（迁自 target-map ② 行）。

旧仓 ``bookmark-doctor`` 从浏览器导出的 bookmarks.html 一次跑完失效检测 + 重复合并 +
长期未访问画像，专门适配中文站点（微信/知乎/B站/微博不能按非 200 一刀切）。本器官
保留判定层（规范化六步流水线 / 分类引擎 / 锚点硬门 / 去重引擎 / 画像分档）；把
Netscape/Chrome 解析、网络探测、HTML 报告与导回写盘留给输入层。逐条处置见
``docs/bookmark-doctor.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="bookmark-doctor",
        version=ORGAN_VERSION,
        summary="收藏夹体检账本：三态失效判定（规则优先+保守冲突+锚点硬门）+ URL 规范化去重 + 未访问画像分档",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)
