"""器官目录：每个器官一个子包 ``<slug>/``，导入时向注册表登记自己的 ``Pack``。

**显式清单，不用 pkgutil 扫描**：扫描式加载会把「某个器官忘了登记」变成静默空跑，
而显式清单在导入失败时立刻红。

新增器官的三步（SKELETON-SPEC §1/§2）：

1. 在 ``byteproof/auditors/<slug>/__init__.py`` 里 ``register(Pack(...))``；
2. 把模块名加进下面的 ``BUILTIN_MODULES``；
3. 补 ``tests/test_<slug>.py`` 与 ``docs/<slug>.md``（输入 / 规则 / 输出示例）。

器官的规则包（``rule_id`` + 依据文本 + 版本）随包分发在
``byteproof/data/<slug>.basis.json``；宿主 CLI 在没给 ``--basis`` 时读它，
器官本身从不读文件（契约见 ``docs/byteproof.md``）。
"""

from __future__ import annotations

import importlib
from typing import Tuple

#: 已迁入的内置器官模块名（相对 ``byteproof.auditors``）。按 slug 字典序维护。
#:
#: 模块名用下划线、slug 用连字符（``timeseries_anomaly`` <-> ``timeseries-anomaly``）：
#: Python 包名不能带 ``-``，而账本与 README 里的 slug 必须能当命令行参数用。
BUILTIN_MODULES: Tuple[str, ...] = (
    "artifact_drift",
    "barcode_preflight",
    "bookmark_doctor",
    "browser_history_vault",
    "cert_ledger",
    "chart_integrity",
    "circuit_detective",
    "config_drift",
    "contract_drift",
    "crsscope",
    "duplicate_docs",
    "fund_quarter_report",
    "image_oracle",
    "media_trace",
    "media_type_check",
    "mojibake_forensics",
    "timeseries_anomaly",
    "version_audit",
)


def load_builtin() -> None:
    """导入全部内置器官模块（每个模块在 import 时登记自己的 Pack）。"""
    for name in BUILTIN_MODULES:
        importlib.import_module("byteproof.auditors." + name)