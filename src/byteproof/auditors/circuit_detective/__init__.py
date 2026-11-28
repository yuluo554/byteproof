"""器官 ``circuit-detective``：黑盒电路侦探账本（迁自 target-map ② 行，Node/mjs 源）。

屏幕上只有一个黑色芯片盒：左边 4 个输入拨杆，右边 4 个指示灯；拨开关、看灯亮灭，
反推盒子里最少用了哪几个逻辑门。答案由内置求解器现场复算，关卡由种子确定性生成，
探测序列可回放。本器官保留整颗 core（三值仿真 / 求解器 / 生成器 / 判定 / 短码 /
揭示计划）；Canvas 渲染、DOM 交互、构建产物留输入层。逐条处置见
``docs/circuit-detective.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="circuit-detective",
        version=ORGAN_VERSION,
        summary="黑盒电路账本：三值 unit-delay 仿真 + NOT/AND/OR 精确 DP 最少门求解 + 种子确定性关卡 + 全表比对判定 + CRC16 回放短码",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)
