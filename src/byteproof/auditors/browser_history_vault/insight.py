"""行为洞察纯判定面（照搬旧仓 ``insight.py``：覆盖/频次/集中度/热力/会话/遗忘）。

K21 口径照搬：每个聚合数字都给**分子与分母**；每个频次都带 ``visit_ids`` 可下钻；
遗忘判定四条件与参照实现逐字一致；无数据 → ``not_assessed``（『没查』不等于
『查了没问题』）。报告排版/渲染不迁（K16 渲染层禁算术的面属报告层）。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from . import privacy
from .sessions import Session, SessionStep, size_histogram, split_sessions
from .timeutil import (
    local_date_of_us,
    local_datetime_of_us,
    local_weekday_index,
    resolve_weekday_start,
)
from .spec import (
    COVERAGE_DECLARATION,
    FORGOTTEN_CONDITIONS,
    FORGOTTEN_DEFINITION,
    SESSION_SPLIT_RULE,
)


class InsightError(ValueError):
    """洞察层的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""


# ------------------------------------------------------------------ 覆盖区间
def coverage_block(rows: Sequence[Dict[str, Any]], *, offset_minutes: int) -> Dict[str, Any]:
    """覆盖区间 + 缺口（全库视角：私密记录也在归档库里，同样计入覆盖）。"""
    offset = int(offset_minutes)
    by_source: Dict[str, List[str]] = {}
    for row in rows:
        day = local_date_of_us(int(row["visit_time_us"]), offset).isoformat()
        by_source.setdefault(str(row["source_browser"]), []).append(day)

    all_days = sorted({day for days in by_source.values() for day in days})
    gaps = [{"from": start, "to": end, "days": count} for start, end, count in gap_ranges(all_days)]
    if all_days:
        first = datetime.date(*[int(part) for part in all_days[0].split("-")])
        last = datetime.date(*[int(part) for part in all_days[-1].split("-")])
        interval = (last - first).days + 1
    else:
        interval = 0

    sources = []
    for source in sorted(by_source):
        days = sorted(set(by_source[source]))
        sources.append(
            {
                "source_browser": source,
                "first_local_date": days[0],
                "last_local_date": days[-1],
                "days_with_visits": len(days),
                "visits": len(by_source[source]),
                "gaps": [{"from": s, "to": e, "days": c} for s, e, c in gap_ranges(days)],
            }
        )

    if not all_days:
        note = "归档库没有任何访问记录：覆盖区间为空（先跑一次 bhvault archive）"
    elif interval < 90:
        note = (
            "归档覆盖区间不足 90 天（浏览器默认只保留约 90 天历史，越早归档越完整）；"
            "本工具不做任何补齐：缺口如实列出"
        )
    else:
        note = "归档覆盖区间如上；区间内的缺口如实列出，本工具不做任何补齐或插值"
    return {
        "first_local_date": all_days[0] if all_days else None,
        "last_local_date": all_days[-1] if all_days else None,
        "interval_days": interval,
        "days_with_visits": len(all_days),
        "gap_days_total": interval - len(all_days),
        "gaps": gaps,
        "gap_count": len(gaps),
        "by_source": sources,
        "declaration": COVERAGE_DECLARATION,
        "note": note,
    }


def gap_ranges(days: List[str]) -> List[Tuple[str, str, int]]:
    """把连续**缺失**的本地日合并成区间（照搬旧仓 archive.gap_ranges 同一口径）。"""
    ordered = sorted(set(days))
    if not ordered:
        return []
    first = datetime.date(*[int(part) for part in ordered[0].split("-")])
    last = datetime.date(*[int(part) for part in ordered[-1].split("-")])
    present = set(ordered)
    gaps: List[Tuple[str, str, int]] = []
    run_start = None
    day = first
    while day <= last + datetime.timedelta(days=1):
        missing = day <= last and day.isoformat() not in present
        if missing and run_start is None:
            run_start = day
        elif not missing and run_start is not None:
            end = day - datetime.timedelta(days=1)
            gaps.append((run_start.isoformat(), end.isoformat(), (end - run_start).days + 1))
            run_start = None
        day += datetime.timedelta(days=1)
    return gaps


# ------------------------------------------------------------------ 频次与集中度
def url_ranking(visible_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 URL 聚合访问记录数；并列时 URL 升序。每项带 visit_ids 可下钻。"""
    counts: Dict[str, int] = {}
    ids: Dict[str, List[int]] = {}
    for row in visible_rows:
        url = str(row["url"])
        counts[url] = counts.get(url, 0) + 1
        ids.setdefault(url, []).append(int(row["visit_id"]))
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"url": url, "visits": count, "visit_ids": sorted(ids[url])} for url, count in ranked]


def domain_ranking(visible_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按域名聚合访问记录数（去重后的 URL 条目数一并给出）；并列时域名升序。"""
    visits: Dict[str, int] = {}
    urls: Dict[str, set] = {}
    ids: Dict[str, List[int]] = {}
    for row in visible_rows:
        host = str(row["host"]).strip().lower()
        visits[host] = visits.get(host, 0) + 1
        urls.setdefault(host, set()).add(str(row["url"]))
        ids.setdefault(host, []).append(int(row["visit_id"]))
    ranked = sorted(visits.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"domain": host, "visits": count, "urls": len(urls[host]), "visit_ids": sorted(ids[host])}
        for host, count in ranked
    ]


def concentration_block(
    visible_rows: Sequence[Dict[str, Any]],
    *,
    top_n: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """域名集中度：分子是域名记录数，分母是全部非私密访问记录数（两个都给）。

    域名列过 display_host：敏感域名保留在分子分母里（"保留统计"），呈现时打码。
    """
    ranked = domain_ranking(visible_rows)
    denominator = len(visible_rows)
    items = []
    for index, item in enumerate(ranked[: int(top_n)], 1):
        percent = "n/a" if denominator == 0 else "%.2f" % (100.0 * item["visits"] / denominator)
        items.append(
            {
                "rank": index,
                "domain": privacy.display_host(item["domain"], private_domains, sensitive_domains),
                "visits": item["visits"],
                "urls": item["urls"],
                "share_numerator": item["visits"],
                "share_denominator": denominator,
                "share_percent_text": percent,
                "visit_ids": item["visit_ids"],
            }
        )
    return {
        "top_n": int(top_n),
        "distinct_domains": len(ranked),
        "denominator_records": denominator,
        "denominator_definition": "全部**非私密**访问记录数（敏感域名保留在分母内：它们只是打码呈现）",
        "numerator_definition": "该域名的访问记录数（按 visit 计，不是去重后的 URL 条目数）",
        "items": items,
    }


# ------------------------------------------------------------------ 时段热力
def heatmap_counts(rows: Iterable[Dict[str, Any]], *, offset_minutes: int, weekday_start: str) -> Dict[str, int]:
    """`"<星期序号>:<小时>" → 访问记录数`（序号 0 = 配置里的起算日）。"""
    start = resolve_weekday_start(weekday_start)
    offset = int(offset_minutes)
    buckets: Dict[str, int] = {}
    for row in rows:
        key = "%d:%d" % (
            local_weekday_index(int(row["visit_time_us"]), offset, start),
            local_datetime_of_us(int(row["visit_time_us"]), offset).hour,
        )
        buckets[key] = buckets.get(key, 0) + 1
    return {key: buckets[key] for key in sorted(buckets, key=_bucket_key)}


def _bucket_key(key: str) -> Tuple[int, int]:
    weekday, hour = key.split(":", 1)
    return (int(weekday), int(hour))


def spark_level(count: int, maximum: int) -> int:
    """把计数折算成 0–9 的展示等级（0 = 无数据）——数据层口径，不是渲染层算术。"""
    if count <= 0 or maximum <= 0:
        return 0
    level = int(round(9.0 * count / maximum))
    return max(1, min(9, level))


# ------------------------------------------------------------------ 会话统计
def sessions_block(visible_rows: Sequence[Dict[str, Any]], *, gap_minutes: int, top_n: int) -> Dict[str, Any]:
    """会话统计：总数 / 长度分布 / 最大的若干条（每条带步骤级 visit_id 供下钻）。"""
    sessions: Tuple[Session, ...] = split_sessions(visible_rows, int(gap_minutes))
    by_source: Dict[str, int] = {}
    for session in sessions:
        by_source[session.source_browser] = by_source.get(session.source_browser, 0) + 1
    largest = sorted(sessions, key=lambda item: (-item.size, item.session_id))[: int(top_n)]
    return {
        "gap_minutes": int(gap_minutes),
        "split_rule": SESSION_SPLIT_RULE,
        "session_count": len(sessions),
        "sessions_by_source": {key: by_source[key] for key in sorted(by_source)},
        "total_visits": sum(session.size for session in sessions),
        "size_histogram": size_histogram(sessions),
        "largest": [
            {
                "session_id": session.session_id,
                "source_browser": session.source_browser,
                "source_profile": session.source_profile,
                "size": session.size,
                "start_us": session.start_us,
                "end_us": session.end_us,
                "visit_ids": list(session.visit_ids()),
            }
            for session in largest
        ],
    }


# ------------------------------------------------------------------ 遗忘的宝藏
def forgotten_state(
    rows: Sequence[Dict[str, Any]],
    url: str,
    *,
    days_threshold: int,
    min_visits: int,
    min_distinct_days: int,
    today_local_date: Any,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """逐条复算某 URL 的遗忘状态与未满足条件名（与参照实现同口径、各自实现）。"""
    today = _as_date(today_local_date)
    subset = [row for row in rows if str(row["url"]) == url]
    if not subset:
        return {
            "forgotten": False,
            "visits": 0,
            "distinct_local_days": 0,
            "failed_conditions": ["no_visits_for_url"],
        }
    last_us = max(int(row["visit_time_us"]) for row in subset)
    days_ago = (today - local_date_of_us(last_us, int(offset_minutes))).days
    distinct_days = len({local_date_of_us(int(row["visit_time_us"]), int(offset_minutes)) for row in subset})
    host = str(subset[0]["host"])
    host_kind = privacy.classify_host(host, private_domains, sensitive_domains)

    conditions = (
        (FORGOTTEN_CONDITIONS[0], days_ago > int(days_threshold)),
        (FORGOTTEN_CONDITIONS[1], len(subset) >= int(min_visits)),
        (FORGOTTEN_CONDITIONS[2], distinct_days >= int(min_distinct_days)),
        (FORGOTTEN_CONDITIONS[3], host_kind == privacy.PUBLIC),
    )
    return {
        "forgotten": all(ok for _, ok in conditions),
        "visits": len(subset),
        "last_visit_us": last_us,
        "last_visit_days_ago": days_ago,
        "distinct_local_days": distinct_days,
        "host": host,
        "host_class": host_kind,
        "failed_conditions": [name for name, ok in conditions if not ok],
    }


def forgotten_block(
    rows: Sequence[Dict[str, Any]],
    *,
    days_threshold: int,
    min_visits: int,
    min_distinct_days: int,
    today_local_date: Any,
    offset_minutes: int,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """全库范围的遗忘项清单；无数据 → `not_assessed`（『没查』不等于『查了没问题』）。"""
    thresholds = {
        "days_threshold": int(days_threshold),
        "min_visits": int(min_visits),
        "min_distinct_days": int(min_distinct_days),
    }
    base = {
        "definition": FORGOTTEN_DEFINITION,
        "conditions": list(FORGOTTEN_CONDITIONS),
        "thresholds": thresholds,
        "today_local_date": _as_date(today_local_date).isoformat(),
        "timezone_utc_offset_minutes": int(offset_minutes),
    }
    if not rows:
        return dict(
            base,
            state="not_assessed",
            matched_count=0,
            items=[],
            note="归档库没有可用记录：未评估（『没查』不等于『查了没问题』）",
        )

    items = []
    for url in sorted({str(row["url"]) for row in rows}):
        state = forgotten_state(
            rows,
            url,
            days_threshold=int(days_threshold),
            min_visits=int(min_visits),
            min_distinct_days=int(min_distinct_days),
            today_local_date=today_local_date,
            offset_minutes=int(offset_minutes),
            private_domains=private_domains,
            sensitive_domains=sensitive_domains,
        )
        if not state["forgotten"]:
            continue
        host = state["host"]
        # 结构护栏：命中项必然是公开主机（条件④），这里再断言一次。
        if state["host_class"] != privacy.PUBLIC:
            raise InsightError(
                "forgotten-private-output",
                "遗忘命中项的主机 %r 不是公开主机（条件表与隐私口径不一致）" % (host,),
            )
        items.append(
            {
                "url": url,
                "domain": host,
                "visits": state["visits"],
                "distinct_local_days": state["distinct_local_days"],
                "last_visit_days_ago": state["last_visit_days_ago"],
                "last_visit_us": state["last_visit_us"],
                "visit_ids": sorted(int(row["visit_id"]) for row in rows if str(row["url"]) == url),
            }
        )
    items.sort(key=lambda item: (-item["last_visit_days_ago"], item["url"]))
    return dict(
        base,
        state="assessed",
        matched_count=len(items),
        items=items,
        note="命中项按『距今越久越靠前，同天按 URL 升序』排列；每项都带 visit_id 供下钻",
    )


def _as_date(value: Any) -> datetime.date:
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            raise InsightError("today-shape", "today_local_date 只接受朴素日期/日期时间（不读时钟，不引入 tzinfo）")
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            pass
    raise InsightError("today-shape", "today_local_date 须为 ISO 日期串或 date：%r" % (value,))
