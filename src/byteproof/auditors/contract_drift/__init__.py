"""器官 ``contract-drift``：跨格式契约差异 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``contractcompat`` 回答「这个变更砸老消费者还是新消费者、该不该放行」，本器官把
每条差异归到 R1–R7、按 policy 判三值 severity、按 deploy-order 出四态归因，并落账。

**没有搬**：三格式解析、IR 归一、逐字段 diff、canonical/golden、报告渲染。
逐条处置见 ``docs/contract-drift.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="contract-drift",
        version=ORGAN_VERSION,
        summary="契约差异账本：R1–R7 规则 + 三值 severity + 七档 policy + 四态 blast_radius",
        input_fields=("differences",),
        evaluate=evaluate,
    )
)