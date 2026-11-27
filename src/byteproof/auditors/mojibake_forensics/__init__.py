"""器官 ``mojibake-forensics``：已解坏文本/字节工件 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``forensics`` 的五个子命令（attr / explain / recover / file / scan）被收敛成
本器官的五个 ``subject.mode``：候选归因、逐步证明、判死/还原、原始字节诊断、CI 门禁。
判定的证据形态（候选集 + 每步字节 + 不可逆点）保留；文件读取、目录遍历、``--out``
写盘、CLI 参数与输出排版不迁，逐条处置见 ``docs/mojibake-forensics.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="mojibake-forensics",
        version=ORGAN_VERSION,
        summary="乱码尸检账本：有界候选 + 每步字节证明 + 不可逆判死 + 字节工件诊断 + 语料门禁",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)