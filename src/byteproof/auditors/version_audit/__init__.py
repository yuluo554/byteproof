"""器官 ``version-audit``：npm 版本约束审计账本（迁自 10-27-versionaudit，Node/mjs 源）。

旧仓 ``versionaudit`` 是离线版本约束审计器：R1–R8 范围语义风险、锁与 manifest 双向
不一致（带请求者路径）、重复版本收敛可行性三态 + MUS、冲突最小解释。本器官保留
数据层（semver 语义核心 + 区间代数）、判定层（五个模块）与全部诚实性约束
（MUS 可机械校验、降级显式、reason 两态不合并）；把文件读取、v1/v2/v3 锁解析、
报告排版与写盘、Node 环境门留给输入层。逐条处置见 ``docs/version-audit.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="version-audit",
        version=ORGAN_VERSION,
        summary="npm 版本约束账本：R1–R8 范围语义 + 锁/manifest 双向不一致 + 收敛可行性三态 MUS + 冲突最小集",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)
