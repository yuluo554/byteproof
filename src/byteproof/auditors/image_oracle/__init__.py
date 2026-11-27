"""器官 ``image-oracle``：图像呈现预言机账本（迁自 target-map ② 行）。

旧仓 ``imageoracle`` 在打开一张图之前预言它在浏览器/预览器/工具里会显示成什么样。
本器官保留五个判决器（orientation / double-rotate / color / container / consumers），
把字节读取与像素解码留给输入层（``facts``）。逐条处置见 ``docs/image-oracle.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="image-oracle",
        version=ORGAN_VERSION,
        summary="图像呈现预言账本：方向矩阵 + 双重旋转三条件 + ICC/色彩体检 + 容器结构 + 消费者矩阵",
        input_fields=("mode", "facts"),
        evaluate=audit.evaluate,
    )
)