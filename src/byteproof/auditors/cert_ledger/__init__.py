"""器官 ``cert-ledger``：证书/私钥台账 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``certledger`` 把一台机器上的证书与私钥做成台账，再对台账做卫生判定。
本器官保留判定面（去重/配对/过期/强度/权限/孤儿/重复/容器信号/基线差异/报告门禁），
把解析与采集留给输入层：PEM/DER/PKCS#12/JKS、``cryptography``、``keytool``、
系统信任库、目录遍历与密码环境变量都不在器官里。逐条处置见 ``docs/cert-ledger.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="cert-ledger",
        version=ORGAN_VERSION,
        summary="证书台账缺陷账本：去重配对 + 过期/强度/权限/孤儿/重复 + 容器信号 + 基线差异",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)