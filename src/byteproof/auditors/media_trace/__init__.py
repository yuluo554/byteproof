"""器官 ``media-trace``：MP4 时间轴自洽审计账本（迁自 target-map ② 行，Go 源）。

旧仓 ``mediatrace`` 判「同一个文件内部，多条时间轴口径是否互相自洽；不自洽时差在
哪个盒子、哪一字节、差多少」。本器官保留 M1–M5 五个模块的判定，把 ISO BMFF 盒子
解析与字节读取留给输入层（``facts``）。逐条处置见 ``docs/media-trace.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="media-trace",
        version=ORGAN_VERSION,
        summary="MP4 时间轴账本：结构自洽 + 时长/编辑表 + stts/tfdt + priming/裁剪 + display matrix",
        input_fields=("mode", "facts"),
        evaluate=audit.evaluate,
    )
)