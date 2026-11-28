"""器官 ``subtitle-preflight``：字幕投放前体检账本（迁自 10-19-subtitle-preflight，Node/mjs 源）。

旧仓是**单文件 HTML**（浏览器内解析 SRT/VTT/ASS + 四类确定性规则 + 三格式报告 + 可逆修复）。
器官只迁**判定层**：时序 T01–T12（含 fps 漂移拟合）、可读性 R01–R07、卫生 S01–S10、
编码嗅探（BOM → UTF-8 → GBK → lossy，回退显式）、可逆修复白名单（去重叠/修间隔 +
行尾空白 + 闭合标签 + SRT 序号重编）。**解析（SRT/VTT/ASS）与报告渲染留输入层与宿主**
（D1+D18 排除词 ``parse`` / ``report``）——cue 序列由输入层摊平传入，器官零文件 IO。

跨语言重写：判定核为 Python，阈值唯一来源 ``spec.THRESHOLDS``（快照
``byteproof/data/subtitle-preflight.thresholds.json`` 双向断言）；定点整数复刻旧仓
``Math.round`` 语义。逐条处置见 ``docs/subtitle-preflight.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="subtitle-preflight",
        version=ORGAN_VERSION,
        summary="字幕体检账本：时序 T01–T12（含 fps 漂移拟合）+ 可读性 R01–R07 + 卫生 S01–S10 + 编码回退 + 可逆修复白名单",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)