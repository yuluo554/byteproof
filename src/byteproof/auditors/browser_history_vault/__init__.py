"""器官 ``browser-history-vault``：浏览器历史档案账本（迁自 target-map ② 行）。

旧仓 ``bhvault`` 做「先归档、再分析」——浏览器只留 90 天历史然后静默删除
（Chromium ``kExpireDaysThreshold = 90`` 源码可证），长期趋势只能在自有档案库上回答。
本器官保留纯判定面（隐私门禁/会话切分/规范化/洞察/聚类/检索）；把 SQLite 快照与
增量归档、文件 I/O、单文件 HTML 报告、CLI 留在输入层。逐条处置见
``docs/browser-history-vault.md`` §6。合成数据底座（禁真实用户数据）由测试内联。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="browser-history-vault",
        version=ORGAN_VERSION,
        summary="浏览器历史档案账本：隐私门禁（私密排除/敏感打码）+ 会话切分 + 覆盖缺口 + 遗忘宝藏四条件 + 主题聚类 + 字 n-gram 检索",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)
