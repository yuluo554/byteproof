"""器官 ``merge-fidelity``：Merge 保真度账本（迁自 10-19-merge-fidelity，Python 源）。

旧仓用 **git 自己的合并引擎**复算"机械合并应该得到什么"，再与仓库实际记录的树逐 blob
对比，挖出三类代码事故：夹带（SMUGGLED / evil merge）、静默吞掉（DROPPED）、跨分支
漏搬（PARITY_MISSING / PARITY_MODIFIED）；另有 revert / 复活账本（REVERT_* 三态）。

**判定面全迁、git 子进程面留输入层**：diffparse / canonical（dumps / digest / 内容寻址
finding ID）/ 三模块判定核（gitattributes 匹配、blob_fidelity、hunk 三分类、parity
三态、revert 校验与重放）1:1 移植；``rev-list`` / ``cat-file`` / ``merge-tree`` /
``git patch-id`` / 临时 worktree 的 ``apply --check`` 由输入层执行，subject 携带预抽取
事实与 ``sha256(diff 文本) → patch-id`` 绑定映射。不读文件、不联网、不读环境变量、
不读时钟（``as_of`` 必填，输入层从提交事实推导）。``report`` 渲染与 ``gate`` 的
TOML 基线面不迁（宿主报告层）。逐条处置见 ``docs/merge-fidelity.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import api, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="merge-fidelity",
        version=ORGAN_VERSION,
        summary="Merge 保真度账本：机械树复算三分类（夹带/吞掉/冲突解）+ 跨分支三态对齐 + revert 校验与重放",
        input_fields=("mode",),
        evaluate=api.evaluate,
    )
)
