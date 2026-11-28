"""器官 ``depcheck-live``：已装依赖引用点解析账本（迁自 11-1-depcheck-live，Node/mjs 源）。

旧仓 ``depcheck-live`` 判断**源码里每一个对已装依赖的引用点**，在「这份 ``node_modules``」
下是否真的可解析；不可解析时，是缺导出（MISSING-EXPORT）、加载方式错
（ESM-CJS-MISMATCH）、子路径未导出（NOT-EXPORTED-SUBPATH），还是动态形态（AMBIGUOUS）；
另有 ``drift`` 层按引用点判版本行为漂移（判据是符号行为，不是 semver 字符串）。

本器官保留判定层全量：``exports`` 解析语义核心（Node 官方算法 1:1 移植，含 D1 实测
修正的 10 处语义）、词法级引用点抽取（静态形态 + 字符串兜底 + 动态显式落 AMBIGUOUS）、
导出面静态读取（CJS/ESM/桶文件递归）、五个判定态、drift 三条口径；把文件系统读取、
目录遍历、``package.json`` 解析、报告排版与退出码壳留给输入层。逐条处置见
``docs/depcheck-live.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="depcheck-live",
        version=ORGAN_VERSION,
        summary="已装依赖引用点账本：exports 六形态解析 + 引用点五判定态 + ESM/CJS 招牌判据 + 版本行为漂移",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)
