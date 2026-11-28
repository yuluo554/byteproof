"""器官 ``http-semantics``：HTTP 语义判定账本（迁自 10-19-http-semantics-mcp，Python 源）。

旧仓是 MCP server（stdio），五个工具（``cache_evaluate`` / ``conditional_evaluate`` /
``cors_evaluate`` / ``cors_simulate_fetch`` / ``vary_match``）做确定性 HTTP 语义判定：
CORS check、重定向链逐 hop 仿真、RFC 9111 新鲜度、前置条件优先级、Vary 缓存键。
**MCP 壳（JSON-RPC 传输 / schemas / registry / server）留旧仓**，本器官只迁判定层：
judgement/ 六模块 + canonical 序列化 1:1 移植，措辞唯一来源是随包
``http-semantics.basis.json``（旧仓 rules.py CATALOG 生成件逐字节迁入）。

不读文件、不联网、不读环境变量、不读时钟——``now`` 是参数不是时钟读数（旧仓决策 D7）。
逐条处置见 ``docs/http-semantics.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="http-semantics",
        version=ORGAN_VERSION,
        summary="HTTP 语义判定账本：CORS check + 重定向逐 hop 仿真 + RFC 9111 新鲜度 + 前置条件优先级 + Vary 缓存键",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)
