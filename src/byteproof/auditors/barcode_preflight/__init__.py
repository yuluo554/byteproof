"""器官 ``barcode-preflight``：条码印前可扫描性账本（迁自 target-map ② 行）。

旧仓 ``bpreflight`` 从生成参数直接判「这个条码印出来会不会扫不出」。本器官保留
数据层（GS1 校验位 / 元素 / 语义）、符号层（字符集 / 长度 / 编码计划 / 容量 / 校验位）、
印刷层（静区 / 放大率 / DPI / 条高 / 颜色）与阈值三态；把规格文件读取、字典装载、
报告排版与写盘、外部解码引擎探测留给输入层。逐条处置见 ``docs/barcode-preflight.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="barcode-preflight",
        version=ORGAN_VERSION,
        summary="条码印前账本：GS1 校验/语义 + 符号可行性 + 静区/放大率/DPI/条高/颜色 + 阈值三态",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)