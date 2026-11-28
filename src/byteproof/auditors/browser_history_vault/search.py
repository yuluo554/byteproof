"""归档检索纯判定面（照搬旧仓 ``search.py``：字 n-gram 包含匹配 + 过滤排序分页）。

检索面 = 标题 ∪ URL（任一命中即命中）；中文走字 n-gram 包含匹配（逐字符滑窗，
不做词切分）。``rows`` 必须已过隐私门禁（单点在 privacy.py），出口形态在遇到私密
主机时当场报错（fail-closed）。CSV 写盘/渲染不迁（输出层）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import privacy
from .timeutil import local_datetime_of_us

DEFAULT_ORDER = "visit_time_desc"
ORDER_KEYS: Tuple[str, ...] = ("visit_time_desc",)


class SearchError(ValueError):
    """检索的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""


@dataclass(frozen=True)
class SearchQuery:
    """一次检索的输入（全部显式；无隐式默认口径）。"""

    text: Optional[str] = None
    domain: Optional[str] = None
    since_us: Optional[int] = None
    until_us: Optional[int] = None
    limit: Optional[int] = None
    offset: int = 0
    order: str = DEFAULT_ORDER

    def to_document(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "domain": self.domain,
            "since_us": self.since_us,
            "until_us": self.until_us,
            "limit": self.limit,
            "offset": int(self.offset),
            "order": self.order,
        }


@dataclass(frozen=True)
class SearchHit:
    """一条命中（保留原始主机；呈现形态由 display_host 单点决定）。"""

    visit_id: int
    url: str
    title: str
    host: str
    visit_time_us: int
    source_browser: str
    source_profile: str

    def display_domain(self, private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> str:
        return privacy.display_host(self.host, private_domains, sensitive_domains)

    def to_document(
        self,
        *,
        offset_minutes: int,
        private_domains: Sequence[str],
        sensitive_domains: Sequence[str],
    ) -> Dict[str, Any]:
        """机读形态（私密主机在这里会直接报错——它本该已被剔除）。"""
        return {
            "visit_id": self.visit_id,
            "visit_time_us": self.visit_time_us,
            "visit_time_local": local_time_text(self.visit_time_us, offset_minutes),
            "url": privacy.redact_text(self.url, self.host, private_domains, sensitive_domains),
            "title": privacy.redact_text(self.title, self.host, private_domains, sensitive_domains),
            "domain": self.display_domain(private_domains, sensitive_domains),
            "source_browser": self.source_browser,
            "source_profile": self.source_profile,
        }


@dataclass(frozen=True)
class SearchResult:
    """一次检索的结果（含"匹配总数 / 本次返回"两轴计数）。"""

    query: SearchQuery
    matched: int
    hits: Tuple[SearchHit, ...]
    ngram_n: int
    casefold: bool


def char_ngrams(text: str, n: int) -> frozenset:
    """字 n-gram 集合（含空格与标点，逐字符滑窗；不做词切分）。

    长度不足 n 时取整串（端点语义：短查询仍可按包含匹配工作）。
    """
    if n < 1:
        raise SearchError("ngram-range", "字 n-gram 的 n 必须 ≥ 1，实际是 %r" % (n,))
    if not isinstance(text, str):
        raise SearchError("text-shape", "待切分的文本必须是字符串，实际是 %r" % (text,))
    if len(text) < n:
        return frozenset({text})
    return frozenset(text[index : index + n] for index in range(len(text) - n + 1))


def text_matches(query: str, target: str, n: int, *, casefold: bool = True) -> bool:
    """查询的全部 n-gram 都出现在目标里 → 命中（"包含匹配"的字 n-gram 读法）。"""
    if casefold:
        query = query.casefold()
        target = target.casefold()
    return char_ngrams(query, n) <= char_ngrams(target, n)


def row_text_hit(row: Dict[str, Any], text: str, n: int, *, casefold: bool = True) -> bool:
    """检索面 = 标题 ∪ URL（任一命中即命中）。"""
    return text_matches(text, str(row.get("title", "")), n, casefold=casefold) or text_matches(
        text, str(row.get("url", "")), n, casefold=casefold
    )


def _validate_query(query: SearchQuery) -> None:
    if query.order not in ORDER_KEYS:
        raise SearchError(
            "order-unknown",
            "未知排序键 %r（白名单：%s）——不回落默认值，否则'我按什么排的'说不清"
            % (query.order, " / ".join(sorted(ORDER_KEYS))),
        )
    if query.offset is None or int(query.offset) < 0:
        raise SearchError("offset-range", "offset 必须 ≥ 0，实际是 %r" % (query.offset,))
    if query.limit is not None and int(query.limit) < 1:
        raise SearchError("limit-range", "limit 必须是正整数或省略，实际是 %r" % (query.limit,))
    if query.since_us is not None and query.until_us is not None and int(query.since_us) > int(query.until_us):
        raise SearchError(
            "range-inverted",
            "时间范围下界 %d 大于上界 %d（空范围的查询是输入错误，不是'没有结果'）"
            % (int(query.since_us), int(query.until_us)),
        )


def _key_for(order: str):
    if order != "visit_time_desc":
        raise SearchError("order-unknown", "未实现的排序键 %r" % (order,))
    return lambda hit: (-hit.visit_time_us, hit.visit_id)


def run_search(
    rows: Iterable[Dict[str, Any]],
    query: SearchQuery,
    *,
    ngram_n: int,
    casefold: bool = True,
) -> SearchResult:
    """在**已过隐私门禁**的行集上执行检索（本模块不过滤隐私——单点在 privacy.py）。"""
    _validate_query(query)
    n = int(ngram_n)
    if n < 1:
        raise SearchError("ngram-range", "search.ngram_n 必须 ≥ 1（来自配置），实际是 %r" % (ngram_n,))

    matched: List[SearchHit] = []
    for row in rows:
        if query.domain is not None and not privacy.host_matches_entry(str(row["host"]), query.domain):
            continue
        since = query.since_us
        until = query.until_us
        moment = int(row["visit_time_us"])
        if since is not None and moment < int(since):
            continue
        if until is not None and moment > int(until):
            continue
        if query.text:
            if not row_text_hit(row, query.text, n, casefold=casefold):
                continue
        matched.append(
            SearchHit(
                visit_id=int(row["visit_id"]),
                url=str(row["url"]),
                title=str(row["title"]),
                host=str(row["host"]),
                visit_time_us=moment,
                source_browser=str(row["source_browser"]),
                source_profile=str(row["source_profile"]),
            )
        )

    ordered = sorted(matched, key=_key_for(query.order))
    offset = int(query.offset)
    window = ordered[offset:] if query.limit is None else ordered[offset : offset + int(query.limit)]
    return SearchResult(query=query, matched=len(ordered), hits=tuple(window), ngram_n=n, casefold=bool(casefold))


def matched_urls(result: SearchResult) -> List[str]:
    """本次**返回窗口**覆盖的去重 URL（升序）——真值对撞用。"""
    return sorted({hit.url for hit in result.hits})


def search_rows(rows, query: SearchQuery, *, private_domains, sensitive_domains, ngram_n: int, casefold: bool = True):
    """带门禁的取数入口：把"过门禁"绑进取数，调用方少写一行就漏掉整条隐私约束。"""
    return run_search(
        privacy.keep_visible(rows, private_domains=private_domains, sensitive_domains=sensitive_domains),
        query,
        ngram_n=ngram_n,
        casefold=casefold,
    )


def local_time_text(us: int, offset_minutes: int) -> str:
    """本地时间的确定性文本形态（YYYY-MM-DDTHH:MM:SS，口径时区）。"""
    return local_datetime_of_us(us, offset_minutes).strftime("%Y-%m-%dT%H:%M:%S")
