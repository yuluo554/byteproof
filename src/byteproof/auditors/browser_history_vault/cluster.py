"""主题聚类与研究路径（照搬旧仓 ``cluster.py`` 的纯判定面）。

实现是"词族分组 + 高同现合并"：先按 df 筛词（``df ≥ min_df``，df 是**文档频率** =
含该词的 URL 条目数），每个保留词给出成员 URL 集；再把成员集高度重叠
（Jaccard ≥ similarity_threshold **且一方包含另一方**）的词族并成一簇——只按
Jaccard 合并会链式吞并整库。同分同序靠显式次排序键（权重降序 + 词面升序）。
渲染/文档装配不迁（报告层）。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import privacy
from .sessions import SessionStep, split_sessions

MIN_TOKEN_LENGTH = 2

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class ClusterError(ValueError):
    """聚类的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""


@dataclass(frozen=True)
class PathStep:
    visit_id: int
    url: str
    host: str
    visit_time_us: int
    source_browser: str
    source_profile: str


@dataclass(frozen=True)
class ResearchPath:
    session_id: int
    source_browser: str
    source_profile: str
    steps: Tuple[PathStep, ...]


@dataclass(frozen=True)
class TopicCluster:
    cluster_id: int
    terms: Tuple[str, ...]
    member_domains: Tuple[str, ...]
    urls: Tuple[str, ...]
    visits: int
    visit_ids: Tuple[int, ...]


@dataclass(frozen=True)
class TopicClusterResult:
    clusters: Tuple[TopicCluster, ...]
    kept_terms: Dict[str, Tuple[str, ...]]
    dropped_terms: Dict[str, int]
    blocked_terms: Tuple[str, ...]
    thresholds: Dict[str, Any]
    documents: int
    records: int


def title_tokens(title: str) -> Tuple[str, ...]:
    """标题词（小写、去重、按词面升序）——中文字段在空格分隔时整段成词。"""
    found = {
        match.group(0).casefold()
        for match in _TOKEN_RE.finditer(str(title))
        if len(match.group(0)) >= MIN_TOKEN_LENGTH
    }
    return tuple(sorted(found))


def host_tokens(host: str) -> Tuple[str, ...]:
    """域名 token = 站点名（主机最左标签）+ 完整主机（不按 `.` 全拆成标签——
    注册后缀标签在每个主机里都出现，会把"主题"退化成"一个大桶"）。"""
    normalized = str(host).strip().lower()
    if not normalized:
        return ()
    found = {normalized}
    leftmost = normalized.split(".")[0]
    if len(leftmost) >= MIN_TOKEN_LENGTH:
        found.add(leftmost)
    return tuple(sorted(t for t in found if len(t) >= MIN_TOKEN_LENGTH))


def row_terms(row: Dict[str, Any]) -> Tuple[str, ...]:
    """一行的特征词 = 标题词 ∪ 域名 token（升序，确定性）。"""
    return tuple(sorted(set(title_tokens(row["title"])) | set(host_tokens(row["host"]))))


def keep_visible_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Dict[str, Any]]:
    """带门禁的取数入口：聚合与路径都只吃 privacy.keep_visible 之后的行。"""
    return privacy.keep_visible(rows, private_domains=private_domains, sensitive_domains=sensitive_domains)


def thresholds_of(options: Dict[str, Any]) -> Dict[str, Any]:
    """本次实际生效的聚类阈值（全部取自 subject options，代码零默认值）。"""
    return {
        "min_df": int(options["cluster_min_df"]),
        "max_features": int(options["cluster_max_features"]),
        "top_terms": int(options["cluster_top_terms"]),
        "similarity_threshold": float(options["cluster_similarity_threshold"]),
        "random_seed": int(options["random_seed"]),
    }


def term_weight(term: str, df: int, document_count: int) -> float:
    """`idf = ln(N / df)`：越独特的词权重越高（df ≥ 1 由构造保证）。"""
    if df < 1:
        raise ClusterError("df-range", "df 必须 ≥ 1，实际是 %r（词 %r）" % (df, term))
    if document_count < df:
        raise ClusterError("df-exceeds-documents", "df (%d) 不得大于文档数 (%d)：词 %r" % (df, document_count, term))
    return math.log(float(document_count) / float(df))


def term_rank_key(term: str, df: int, document_count: int) -> Tuple[Any, ...]:
    """保留词的排序键 = 权重降序 + 词面升序（同权重必有次键，K15）。"""
    return (-term_weight(term, df, document_count), term)


def rank_terms(frequencies: Dict[str, int], *, document_count: int, max_features: int) -> List[str]:
    ordered = sorted(frequencies, key=lambda term: term_rank_key(term, frequencies[term], document_count))
    return ordered[: int(max_features)]


def _jaccard(left: set, right: set) -> float:
    union = len(left | right)
    return (len(left & right) / union) if union else 0.0


def mergeable(left: set, right: set, similarity: float) -> bool:
    """两个词族能否并成一簇：同现高度一致（Jaccard ≥ 阈值且一方包含另一方）。

    加包含关系是为了防链式吞并：部分重叠的两个大类保持分开。
    """
    if not (left <= right or right <= left):
        return False
    return _jaccard(left, right) >= similarity


def cluster_topics(rows: Sequence[Dict[str, Any]], *, options: Dict[str, Any]) -> TopicClusterResult:
    """在**已过隐私门禁**的行集上做主题聚类（本函数不自己过滤）。"""
    thresholds = thresholds_of(options)
    min_df = int(thresholds["min_df"])
    if min_df < 1:
        raise ClusterError("min_df-range", "cluster.min_df 必须 ≥ 1，实际是 %r" % (min_df,))
    max_features = int(thresholds["max_features"])
    similarity = float(thresholds["similarity_threshold"])

    records = len(rows)
    documents = len({str(row["url"]) for row in rows})

    frequencies: Dict[str, int] = {}
    members: Dict[str, set] = {}
    visits_of_url: Dict[str, int] = {}
    ids_of_url: Dict[str, List[int]] = {}
    host_of_url: Dict[str, str] = {}
    seen_urls: set = set()
    for row in rows:
        url = str(row["url"])
        visits_of_url[url] = visits_of_url.get(url, 0) + 1
        ids_of_url.setdefault(url, []).append(int(row["visit_id"]))
        host_of_url[url] = str(row["host"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        # df 是文档频率（含该词的 URL 条目数），不是记录数
        for term in row_terms(row):
            frequencies[term] = frequencies.get(term, 0) + 1
            members.setdefault(term, set()).add(url)

    # 词表过滤：与私密/敏感主机同形的词不进词表（零出现判据是主机身份）。
    private_domains = options["private_domains"]
    sensitive_domains = options["sensitive_domains"]
    blocked_terms = {
        term
        for term in frequencies
        if privacy.classify_host(term, private_domains, sensitive_domains) != privacy.PUBLIC
    }
    frequencies = {term: df for term, df in frequencies.items() if term not in blocked_terms}

    dropped = {term: df for term, df in frequencies.items() if df < min_df}
    kept_frequencies = {term: df for term, df in frequencies.items() if df >= min_df}
    kept_order = rank_terms(kept_frequencies, document_count=documents, max_features=max_features)

    # 词族分组 + 高同现合并（按 rank_terms 的显式次序处理 → 与输入物理序无关）
    merged: List[Dict[str, Any]] = []
    for term in kept_order:
        term_members = members[term]
        target: Optional[Dict[str, Any]] = None
        for candidate in merged:
            if mergeable(term_members, candidate["urls"], similarity):
                target = candidate
                break
        if target is None:
            merged.append({"urls": set(term_members), "terms": {term}})
        else:
            target["urls"] |= term_members
            target["terms"].add(term)

    # 保留词必须每一个都在某个簇里（合并不会丢词）——自检式护栏。
    covered = {term for cluster in merged for term in cluster["terms"]}
    if covered != set(kept_order):
        raise ClusterError(
            "cluster-term-coverage",
            "有保留词未落进任何簇：%s" % sorted(set(kept_order) - covered)[:5],
        )

    clusters: List[TopicCluster] = []
    for cluster in merged:
        urls = sorted(cluster["urls"])
        terms = tuple(
            sorted(cluster["terms"], key=lambda term: term_rank_key(term, frequencies[term], documents))
        )
        clusters.append(
            TopicCluster(
                cluster_id=0,  # 稍后按显式排序键统一编号
                terms=terms,
                member_domains=tuple(sorted({host_of_url[url] for url in urls})),
                urls=tuple(urls),
                visits=sum(visits_of_url[url] for url in urls),
                visit_ids=tuple(sorted(vid for url in urls for vid in ids_of_url[url])),
            )
        )
    clusters.sort(key=lambda item: (-item.visits, item.terms[0], item.urls[0]))
    clusters = [
        TopicCluster(
            cluster_id=index,
            terms=item.terms,
            member_domains=item.member_domains,
            urls=item.urls,
            visits=item.visits,
            visit_ids=item.visit_ids,
        )
        for index, item in enumerate(clusters, 1)
    ]
    top_terms = int(thresholds["top_terms"])
    clusters = [
        TopicCluster(
            cluster_id=item.cluster_id,
            terms=item.terms[:top_terms],
            member_domains=item.member_domains,
            urls=item.urls,
            visits=item.visits,
            visit_ids=item.visit_ids,
        )
        for item in clusters
    ]
    return TopicClusterResult(
        clusters=tuple(clusters),
        kept_terms={term: tuple(sorted(members[term])) for term in kept_order},
        dropped_terms={term: dropped[term] for term in sorted(dropped)},
        blocked_terms=tuple(sorted(blocked_terms)),
        thresholds=thresholds,
        documents=documents,
        records=records,
    )


def research_paths(rows: Sequence[Dict[str, Any]], *, gap_minutes: int) -> Tuple[ResearchPath, ...]:
    """按会话切分产出跳转序列（sessions.split_sessions 的唯一消费点）。"""
    host_of_url = {str(row["url"]): str(row["host"]) for row in rows}
    paths: List[ResearchPath] = []
    sessions: Tuple = split_sessions(rows, int(gap_minutes))
    for session in sessions:
        steps = tuple(
            PathStep(
                visit_id=step.visit_id,
                url=step.url,
                host=host_of_url.get(step.url, ""),
                visit_time_us=step.visit_time_us,
                source_browser=step.source_browser,
                source_profile=step.source_profile,
            )
            for step in session.steps
        )
        paths.append(
            ResearchPath(
                session_id=session.session_id,
                source_browser=session.source_browser,
                source_profile=session.source_profile,
                steps=steps,
            )
        )
    return tuple(paths)
