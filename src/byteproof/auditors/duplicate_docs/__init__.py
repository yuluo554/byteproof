"""器官 ``duplicate-docs``：文档工件 -> 缺陷账本（"这份工件是另一份的同一内容"）。

来源：迁自 target-map ② 行（旧包 ``docdedupe``）。搬过来的是**判定**：
正文归一化（五步）+ 字符 3-gram shingle + 精确 Jaccard + 并查集聚类。

**没有搬的部分**（逐条写进 ``docs/duplicate-docs.md`` 的处置表）：文件抽取（PDF/DOCX/HTML）、
SQLite 索引与缓存、目录扫描、FastAPI 复核页、隔离/复原执行层、报告渲染、基准、
MinHash/LSH 候选召回、SimHash 预筛、模板族判定与保留建议打分。
理由只有一条：它们要么是**工具面**（读文件、写库、起服务、出报告），要么是**性能装置**
（LSH/SimHash 只减少候选，不改变"是不是近重复"这个判定），而 byteproof 的器官只回答
"哪里不对、依据是哪条规则"。

一句话：旧仓回答"该留哪一份"，本器官回答"这一份和那一份是不是同一份内容、依据是哪条规则"。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from .audit import evaluate

ORGAN_VERSION = "1"

PACK = register(
    Pack(
        slug="duplicate-docs",
        version=ORGAN_VERSION,
        summary="文档工件缺陷账本：正文归一化后按精确 Jaccard 判同源重复",
        input_fields=("documents",),
        evaluate=evaluate,
    )
)