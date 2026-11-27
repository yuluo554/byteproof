"""器官 ``config-drift``：配置差异 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``cfgdelta`` 回答「两份配置行为是否相同」，本器官把每条差异按六类落成带规则依据的
账本条目，并由 gate 决定是否阻断：资源/部署/镜像/暴露/配置五类行为差异 + 纯书写计数 +
不可判定；fail-on 与 allow-indeterminate 语义照搬。

**没有搬**：格式解析、结构无关 diff、默认值 profile 双侧施加、CLI 渲染、golden harness。
逐条处置见 ``docs/config-drift.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="config-drift",
        version=ORGAN_VERSION,
        summary="配置差异账本：值族归一 + 六类影响分类 + semver 子类 + gate 门禁",
        input_fields=("entries",),
        evaluate=evaluate,
    )
)