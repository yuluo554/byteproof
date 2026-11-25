"""器官 ``timeseries-anomaly``：时序工件 -> 缺陷账本。

来源：迁自 target-map ② 行（旧包 ``anomaly_atlas``）。搬过来的是**判定**，
不是工具：旧仓的 CLI、HTML 渲染、Node 复算镜像、报告数字白名单、合成数据生成器一律留在旧仓 ——
它们是"怎么呈现"，而 byteproof 的器官只允许回答"哪里不对、依据是哪条规则"。

一个工件 = 一张长表（``timestamp`` / ``series_id`` / ``value`` 解析后的 JSON，见
:mod:`byteproof.auditors.timeseries_anomaly.subject`）。一条缺陷 = 一个可定位位置
（行号或时间区段）+ 一条规则依据 + 一段机器可读证据。

四段判定的等级口径写在 :mod:`~byteproof.auditors.timeseries_anomaly.rules`，
输入/规则/输出示例写在 ``docs/timeseries-anomaly.md``。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

#: 器官版本。改判定口径（规则集合、等级映射、检测算术）-> 改它；只改文档不动。
ORGAN_VERSION = "1"

#: 导入即登记：一个器官 = 一份声明。加载清单在 ``auditors/__init__.py`` 的
#: ``BUILTIN_MODULES``（显式清单，不扫描 —— 扫描会把"忘了登记"变成静默空跑）。
PACK = register(
    Pack(
        slug="timeseries-anomaly",
        version=ORGAN_VERSION,
        summary="时序工件缺陷账本：时间轴完整性 + 采样形状 + 四个确定性检测器命中段",
        input_fields=("rows",),
        evaluate=evaluate,
    )
)