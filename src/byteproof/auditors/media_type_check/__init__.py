"""器官 ``media-type-check``：已解析的 MIME 工件 -> 缺陷账本。

来源：迁自 target-map ② 行。规则 ID 原样保留（``MC-H07`` 等），
因为它们同时是旧仓 ``data/rfc-ledger.json`` 的索引键 —— 改名就断掉了
"这条账本能反查到 RFC 条款"这条链。

搬过来的是 **19 条规则的判定**（头宽/编码字/传输编码/容器/归属）。
没搬的（逐条写在 ``docs/media-type-check.md`` 的处置表里）：raw 字节扫描层（``scan.py``）、
mbox 容器变体（``container.py``）、两棵候选树分歧（``MC-B06``）、报告渲染、CLI、
golden 夹具、打包门。理由同另两个器官：工具面与呈现层不是判定。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="media-type-check",
        version=ORGAN_VERSION,
        summary="MIME 工件缺陷账本：头宽/编码字/传输编码/容器/归属五域的条款一致性",
        input_fields=("parts",),
        evaluate=evaluate,
    )
)