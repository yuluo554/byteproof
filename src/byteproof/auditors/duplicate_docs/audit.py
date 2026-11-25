"""器官主体：文档工件 -> 缺陷账本。

两段：

1. **构件**（每份文档自己）：路径是否唯一、正文是否为空、是否短到无法比对。
   这三条与"和谁重复"无关，所以先跑完，再决定谁进比对。
2. **重复**（两份文档之间）：归一化 -> 精确 Jaccard -> 并查集聚类 ->
   每个簇里每个成员落一条账本，指向**同一簇里与它最像的那一份**。

为什么指向"最像的那一份"而不是"簇代表"：簇是连通分量，A–B 与 B–C 成边时 A–C 可能
根本没到阈值；说"C 与 A 是同一份内容"就是伪造结论。指向最强的那条边，账本说的每一句
都有那条边兜着。

``path`` 是文档在工件里的路径（唯一可指回的位置）；路径在工件里重复时追加 `#<序号>`，
保证 `id = <rule_id>@<path>` 仍然唯一 —— 账本宁可位置难看，也不能两条结论抢一个 id。

本模块不打印、不读文件/环境、不看时钟、不带参数解析器 —— 由
``tests/test_duplicate-docs.py::TestNoClockNoSideEffects``（AST 扫描本包）守着。
"""

from __future__ import annotations

import hashlib
from typing import Iterable, List, Mapping

from byteproof.core.basis import Basis
from byteproof.core.ledger import Record

from . import cluster as cluster_module
from . import spec
from .fingerprint import jaccard, shingle_hashes
from .normalize import normalize


def evaluate(subject: Mapping, basis: Basis) -> Iterable[Record]:
    """审一次文档工件。"""
    if not isinstance(subject, Mapping):
        raise ValueError("输入必须是 JSON 对象")
    settings = spec.resolve_params(subject.get("params"))
    documents = _parse_documents(subject)
    path_counts = {}
    for document in documents:
        path_counts[document["path"]] = path_counts.get(document["path"], 0) + 1
    dumped = spec.dump_params(settings)

    records: List[Record] = []
    for document in documents:
        document["normalized"] = normalize(document["text"], settings)
        document["normalized_length"] = len(document["normalized"])
        document["label"] = _label(document, path_counts)
    records.extend(_document_records(documents, path_counts, basis, dumped))
    records.extend(_duplicate_records(documents, settings, basis, dumped))
    return tuple(records)


def _label(document, path_counts):
    """账本位置：路径唯一时就是路径，重复时追加序号。"""
    if path_counts[document["path"]] > 1:
        return "%s#%d" % (document["path"], document["ordinal"])
    return document["path"]


def _record(rule_id, message, basis, path, evidence):
    return Record(
        rule_id=rule_id,
        verdict=spec.verdict_for(rule_id),
        message=message,
        basis=basis.ref(rule_id),
        path=path,
        evidence=evidence,
    )


def _parse_documents(subject):
    """``documents`` 必须是对象数组，每项有 ``path`` 与 ``text``。"""
    raw = subject.get("documents")
    if not isinstance(raw, list):
        raise ValueError("documents 必须是数组")
    if not raw:
        raise ValueError("documents 为空：没有可审的工件")
    documents = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError("documents[%d] 必须是对象" % (index + 1,))
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("documents[%d].path 必须是非空字符串" % (index + 1,))
        if "text" not in item:
            raise ValueError("documents[%d] 缺必填字段 text（无正文请显式写空串）" % (index + 1,))
        text = item["text"]
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise ValueError("documents[%d].text 必须是字符串" % (index + 1,))
        documents.append({"path": path.strip(), "text": text, "ordinal": index + 1})
    return documents


def _norm_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _document_records(documents, path_counts, basis, dumped):
    """每份文档自己的三条判定（路径唯一 / 正文空 / 正文过短）。"""
    min_chars = int(dumped["min_text_chars"])
    built = []
    for document in documents:
        path = document["path"]
        label = document["label"]
        if path_counts[path] > 1:
            built.append(
                _record(
                    spec.RULE_DUPLICATE_PATH,
                    "工件里有 %d 份文档共用路径 %r（位置不唯一，任何指向它的结论都无法复核）"
                    % (path_counts[path], path),
                    basis,
                    label,
                    {
                        "ordinal": document["ordinal"],
                        "path": path,
                        "path_uses": path_counts[path],
                    },
                )
            )
        if not document["text"].strip():
            built.append(
                _record(
                    spec.RULE_EMPTY_TEXT,
                    "文档没有正文：无法参与任何比对（缺失是数据，但不构成可复核的结论）",
                    basis,
                    label,
                    {
                        "ordinal": document["ordinal"],
                        "raw_length": len(document["text"]),
                        "normalized_length": document["normalized_length"],
                    },
                )
            )
            continue
        if document["normalized_length"] < min_chars:
            built.append(
                _record(
                    spec.RULE_TOO_SHORT,
                    "正文归一化后只有 %d 个字符（不足 min_text_chars=%d）："
                    "不参与比对，既不会被指为重复，也不会被当成参照"
                    % (document["normalized_length"], min_chars),
                    basis,
                    label,
                    {
                        "ordinal": document["ordinal"],
                        "normalized_length": document["normalized_length"],
                        "min_text_chars": min_chars,
                    },
                )
            )
    return built


def _is_comparable(document, min_chars):
    return bool(document["text"].strip()) and document["normalized_length"] >= min_chars


def _duplicate_records(documents, settings, basis, dumped):
    min_chars = int(dumped["min_text_chars"])
    comparable = [item for item in documents if _is_comparable(item, min_chars)]
    digests = {item["label"]: _norm_digest(item["normalized"]) for item in comparable}
    hashes = {
        item["label"]: shingle_hashes(item["normalized"], settings.shingle_size)
        for item in comparable
    }

    scores = {}
    edges = []
    for left_index in range(len(comparable)):
        for right_index in range(left_index + 1, len(comparable)):
            left = comparable[left_index]["label"]
            right = comparable[right_index]["label"]
            score = jaccard(hashes[left], hashes[right])
            kind = cluster_module.edge_kind(
                score,
                digests[left] == digests[right],
                settings.near_duplicate_threshold,
            )
            if kind is None:
                continue
            key = (min(left, right), max(left, right))
            scores[key] = score
            edges.append((left, right, kind))

    clusters = cluster_module.build_clusters(
        edges, [item["label"] for item in comparable]
    )
    by_label = {item["label"]: item for item in comparable}

    built = []
    for cluster in clusters:
        for member in cluster["members"]:
            strongest = _strongest_edge(edges, scores, member)
            other, kind, score = strongest
            rule_id = (
                spec.RULE_EXACT_DUPLICATE if kind == cluster_module.EXACT else spec.RULE_NEAR_DUPLICATE
            )
            quantized = spec.quantize(score)
            built.append(
                _record(
                    rule_id,
                    "与 %r 是同一份内容（归一化 Jaccard %s，%s 档，簇 %s 共 %d 份）"
                    % (
                        other,
                        spec.fixed_to_str(quantized),
                        cluster["tier"],
                        cluster["cluster_id"],
                        len(cluster["members"]),
                    ),
                    basis,
                    member,
                    {
                        "other": other,
                        "jaccard_q": quantized,
                        "jaccard": spec.fixed_to_str(quantized),
                        "edge_kind": kind,
                        "tier": cluster["tier"],
                        "cluster_id": cluster["cluster_id"],
                        "cluster_size": len(cluster["members"]),
                        "members": sorted(cluster["members"]),
                        "normalized_length": by_label[member]["normalized_length"],
                        "incoming_label": by_label[member]["path"],
                        "near_duplicate_threshold": dumped["near_duplicate_threshold"],
                        "shingle_size": int(dumped["shingle_size"]),
                        "normalize_version": spec.NORMALIZE_VERSION,
                    },
                )
            )
    return built


def _strongest_edge(edges, scores, member):
    """``member`` 所属最强的一条边（分数优先，平局取字典序更小的对手）。"""
    best = None
    for left, right, kind in edges:
        if member not in (left, right):
            continue
        other = right if left == member else left
        score = scores[(min(left, right), max(left, right))]
        candidate = (-score, other, kind, score)
        if best is None or candidate < best:
            best = candidate
    if best is None:  # pragma: no cover - 簇成员的度至少为 1
        raise ValueError("簇成员没有任何边：%s" % (member,))
    return best[1], best[2], best[3]