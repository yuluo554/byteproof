"""器官 ``browser-history-vault``：浏览器历史档案账本（迁自 10-18-browser-history-vault）。

旧仓 ``bhvault`` 做"先归档、再分析"：只读快照沉淀长期档案，回答"我过去在做什么"
"哪些是遗忘的宝藏""作息与兴趣怎么变"。本器官照搬纯判定面：1601 纪元时间换算、
隐私门禁（私密完全排除/敏感保留统计只打码）、会话切分、规范化器（主机解析/去重键/
规范序）、行为洞察（覆盖缺口/频次榜/集中度/热力分桶/遗忘四条件）、主题聚类
（词族分组+高同现合并）、字 n-gram 检索。把 SQLite 读写、文件 I/O、HTML/文本渲染、
CLI 留在输入层/报告层。

**账本口径**：旧仓五命令完成即 rc0（洞察是辅助参考，不阻断）→ 全部规则 info 级，
语义与阈值写进 evidence；私密主机走到输出面 = 门禁被绕过，当场 ValueError（rc2）。
"""

from __future__ import annotations

from typing import Iterable, List, Mapping

from byteproof.core.ledger import INFO, Record

from . import cluster as cluster_mod
from . import insight as insight_mod
from . import norm as norm_mod
from . import privacy as privacy_mod
from . import search as search_mod
from . import spec


def evaluate(subject: Mapping, basis) -> Iterable[Record]:
    """账本入口：subject = {mode, rows, options}。

    ``rows`` 是归档库的规范化行（含 visit_id）；``options`` 携带时区偏移、隐私清单、
    会话间隔与各阈值（数值口径唯一来源 = subject，器官零默认值——report/cluster/
    search 所需键缺失即 ValueError）。
    """
    mode = _mode_of(subject)
    rows = _rows_of(subject)
    options = _options_of(subject, mode)

    records: List[Record] = []
    private_domains = options["private_domains"]
    sensitive_domains = options["sensitive_domains"]
    visible, excluded_rows = privacy_mod.classify_rows(
        rows, private_domains=private_domains, sensitive_domains=sensitive_domains
    )

    if mode in ("audit", "report", "cluster", "search"):
        records.extend(_privacy_records(basis, rows, private_domains, sensitive_domains))

    if mode in ("audit", "normalize"):
        records.extend(_normalize_records(rows, basis))

    if mode in ("audit", "report"):
        records.extend(_report_records(basis, rows, visible, excluded_rows, options, private_domains, sensitive_domains))

    if mode in ("audit", "cluster"):
        records.extend(_cluster_records(basis, visible, options, private_domains, sensitive_domains))

    if mode in ("audit", "search"):
        records.extend(_search_records(basis, rows, options, private_domains, sensitive_domains))

    records.append(
        Record(
            rule_id=spec.RULE_SUMMARY,
            verdict=INFO,
            message="mode=%s：记录 %d 条（可见 %d / 私密排除 %d）→ 账本行 %d 条（全部 info：旧仓五命令完成即 rc0）"
            % (mode, len(rows), len(visible), len(rows) - len(visible), len(records)),
            basis=basis.ref(spec.RULE_SUMMARY),
            path="summary",
            evidence={
                "mode": mode,
                "records": len(rows),
                "visible": len(visible),
                "private_excluded": len(rows) - len(visible),
            },
        )
    )
    return records


# ------------------------------------------------------------------ privacy
def _privacy_records(basis, rows, private_domains, sensitive_domains) -> List[Record]:
    summary = privacy_mod.summarize(rows, private_domains=private_domains, sensitive_domains=sensitive_domains)
    records: List[Record] = []
    for host, count in summary["private_host_counts"].items():
        records.append(
            Record(
                rule_id=spec.RULE_PRIVACY_EXCLUDED,
                verdict=INFO,
                message="私密主机 %s：%d 条记录被完全排除（连统计都不进）" % (host, count),
                basis=basis.ref(spec.RULE_PRIVACY_EXCLUDED),
                path="privacy.private.%s" % host,
                evidence={"host": host, "excluded_visit_records": count, "fingerprint": privacy_mod.fingerprint(host)},
            )
        )
    for host, count in summary["sensitive_host_counts"].items():
        records.append(
            Record(
                rule_id=spec.RULE_PRIVACY_MASKED,
                verdict=INFO,
                message="敏感主机 %s：%d 条记录保留统计、呈现打码（%s）" % (host, count, privacy_mod.mask_host(host)),
                basis=basis.ref(spec.RULE_PRIVACY_MASKED),
                path="privacy.sensitive.%s" % host,
                evidence={
                    "host": host,
                    "masked_visit_records": count,
                    "masked_form": privacy_mod.mask_host(host),
                    "fingerprint": privacy_mod.fingerprint(host),
                },
            )
        )
    return records


# ------------------------------------------------------------------ normalize
def _normalize_records(rows, basis) -> List[Record]:
    records: List[Record] = []
    for row in rows:
        row = dict(row)
        row.setdefault("transition", 0)
        row.setdefault("visit_duration_us", 0)
        if "host" not in row:
            row["host"] = norm_mod.host_of(str(row["url"]))
    normalized = norm_mod.normalize_rows(rows, on_duplicate="dedupe")
    dropped = len(rows) - len(normalized)
    if dropped:
        records.append(
            Record(
                rule_id=spec.RULE_NORMALIZE_DUPLICATE,
                verdict=INFO,
                message="规范化：%d 条重复去重键被确定性保留首条（显式计数，不静默）" % dropped,
                basis=basis.ref(spec.RULE_NORMALIZE_DUPLICATE),
                path="normalize.duplicates",
                evidence={"dropped": dropped, "total": len(rows), "kept": len(normalized)},
            )
        )
    return records


# ------------------------------------------------------------------ report
def _report_records(basis, rows, visible, excluded_rows, options, private_domains, sensitive_domains) -> List[Record]:
    records: List[Record] = []
    offset = options["timezone_utc_offset_minutes"]

    coverage = insight_mod.coverage_block(rows, offset_minutes=offset)
    for index, gap in enumerate(coverage["gaps"]):
        records.append(
            Record(
                rule_id=spec.RULE_COVERAGE_GAP,
                verdict=INFO,
                message="覆盖缺口 %s → %s（%d 天，本地日）：如实列出，不补齐不插值"
                % (gap["from"], gap["to"], gap["days"]),
                basis=basis.ref(spec.RULE_COVERAGE_GAP),
                path="coverage.gaps[%d]" % index,
                evidence=dict(gap, declaration=coverage["declaration"]),
            )
        )
    records.append(
        Record(
            rule_id=spec.RULE_COVERAGE_GAP,
            verdict=INFO,
            message="覆盖 %s → %s：%d 天区间 / %d 天有访问 / %d 个缺口（%s）"
            % (
                coverage["first_local_date"],
                coverage["last_local_date"],
                coverage["interval_days"],
                coverage["days_with_visits"],
                coverage["gap_count"],
                coverage["note"],
            ),
            basis=basis.ref(spec.RULE_COVERAGE_GAP),
            path="coverage.summary",
            evidence={key: coverage[key] for key in ("first_local_date", "last_local_date", "interval_days", "days_with_visits", "gap_days_total", "gap_count", "note")},
        )
    )

    sessions = insight_mod.sessions_block(visible, gap_minutes=options["session_gap_minutes"], top_n=options["report_top_n"])
    records.append(
        Record(
            rule_id=spec.RULE_SESSION_STATS,
            verdict=INFO,
            message="会话（间隔 %d 分钟，%s）：%d 个 / 访问 %d 条" % (sessions["gap_minutes"], sessions["split_rule"], sessions["session_count"], sessions["total_visits"]),
            basis=basis.ref(spec.RULE_SESSION_STATS),
            path="sessions.summary",
            evidence=dict(sessions),
        )
    )

    forgotten = insight_mod.forgotten_block(
        visible,
        days_threshold=options["forgotten_days_threshold"],
        min_visits=options["forgotten_min_visits"],
        min_distinct_days=options["forgotten_min_distinct_days"],
        today_local_date=options["today_local_date"],
        offset_minutes=offset,
        private_domains=private_domains,
        sensitive_domains=sensitive_domains,
    )
    for index, item in enumerate(forgotten["items"]):
        records.append(
            Record(
                rule_id=spec.RULE_FORGOTTEN,
                verdict=INFO,
                message="遗忘的宝藏：%s（距今 %d 天、%d 次访问、跨 %d 个本地日）"
                % (item["url"], item["last_visit_days_ago"], item["visits"], item["distinct_local_days"]),
                basis=basis.ref(spec.RULE_FORGOTTEN),
                path="forgotten.items[%d]" % index,
                evidence=dict(item, definition=forgotten["definition"], state=forgotten["state"]),
            )
        )
    if forgotten["state"] == "not_assessed":
        records.append(
            Record(
                rule_id=spec.RULE_FORGOTTEN,
                verdict=INFO,
                message="遗忘项未评估：归档库没有可用记录（『没查』不等于『查了没问题』）",
                basis=basis.ref(spec.RULE_FORGOTTEN),
                path="forgotten.state",
                evidence=dict(forgotten),
            )
        )
    return records


# ------------------------------------------------------------------ cluster
def _cluster_records(basis, visible, options, private_domains, sensitive_domains) -> List[Record]:
    records: List[Record] = []
    result = cluster_mod.cluster_topics(
        visible,
        options={
            "cluster_min_df": options["cluster_min_df"],
            "cluster_max_features": options["cluster_max_features"],
            "cluster_top_terms": options["cluster_top_terms"],
            "cluster_similarity_threshold": options["cluster_similarity_threshold"],
            "random_seed": options["random_seed"],
            "private_domains": private_domains,
            "sensitive_domains": sensitive_domains,
        },
    )
    for item in result.clusters:
        records.append(
            Record(
                rule_id=spec.RULE_CLUSTER,
                verdict=INFO,
                message="簇 %d：%d 个 URL / %d 次访问（词：%s）"
                % (item.cluster_id, len(item.urls), item.visits, "、".join(item.terms)),
                basis=basis.ref(spec.RULE_CLUSTER),
                path="cluster.cluster-%d" % item.cluster_id,
                evidence={
                    "cluster_id": item.cluster_id,
                    "terms": list(item.terms),
                    "member_domains": list(item.member_domains),
                    "urls": list(item.urls),
                    "visits": item.visits,
                    "visit_ids": list(item.visit_ids),
                    "thresholds": dict(result.thresholds),
                },
            )
        )
    paths = cluster_mod.research_paths(visible, gap_minutes=options["session_gap_minutes"])
    for path in paths:
        records.append(
            Record(
                rule_id=spec.RULE_RESEARCH_PATH,
                verdict=INFO,
                message="研究路径 会话%d（%s@%s）：%d 步" % (path.session_id, path.source_browser, path.source_profile, len(path.steps)),
                basis=basis.ref(spec.RULE_RESEARCH_PATH),
                path="paths.session-%d" % path.session_id,
                evidence={
                    "session_id": path.session_id,
                    "source_browser": path.source_browser,
                    "source_profile": path.source_profile,
                    "steps": [dict(visit_id=s.visit_id, url=s.url, host=s.host, visit_time_us=s.visit_time_us) for s in path.steps],
                },
            )
        )
    return records


# ------------------------------------------------------------------ search
def _search_records(basis, rows, options, private_domains, sensitive_domains) -> List[Record]:
    records: List[Record] = []
    sq = options.get("search")
    if not isinstance(sq, dict):
        return records
    query = search_mod.SearchQuery(
        text=sq.get("text"),
        domain=sq.get("domain"),
        since_us=sq.get("since_us"),
        until_us=sq.get("until_us"),
        limit=sq.get("limit"),
        offset=int(sq.get("offset", 0)),
        order=sq.get("order", search_mod.DEFAULT_ORDER),
    )
    result = search_mod.search_rows(
        rows,
        query,
        private_domains=private_domains,
        sensitive_domains=sensitive_domains,
        ngram_n=int(options["search_ngram_n"]),
    )
    for index, hit in enumerate(result.hits):
        document = hit.to_document(
            offset_minutes=options["timezone_utc_offset_minutes"],
            private_domains=private_domains,
            sensitive_domains=sensitive_domains,
        )
        records.append(
            Record(
                rule_id=spec.RULE_SEARCH_HIT,
                verdict=INFO,
                message="命中 visit %d：%s（%s）" % (document["visit_id"], document["title"] or document["url"], document["domain"]),
                basis=basis.ref(spec.RULE_SEARCH_HIT),
                path="search.hits[%d]" % index,
                evidence=dict(document, matched_total=result.matched, query=query.to_document()),
            )
        )
    if not result.hits and result.matched == 0:
        records.append(
            Record(
                rule_id=spec.RULE_SEARCH_HIT,
                verdict=INFO,
                message="检索无命中（matched=0；查询=%s）" % query.to_document(),
                basis=basis.ref(spec.RULE_SEARCH_HIT),
                path="search.empty",
                evidence={"matched": 0, "query": query.to_document()},
            )
        )
    return records


# ------------------------------------------------------------------ 输入规整
def _mode_of(subject) -> str:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if not isinstance(mode, str) or mode not in spec.MODES:
        raise ValueError("subject.mode 必须是 %s 之一" % "|".join(spec.MODES))
    return mode


def _rows_of(subject) -> list:
    rows = subject.get("rows")
    if not isinstance(rows, list):
        raise ValueError("subject.rows 必须是数组（归档库的规范化行）")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows 的每一项必须是对象")
        for field in ("url", "visit_time_us", "source_browser", "source_profile", "visit_id", "host"):
            if field not in row:
                raise ValueError("rows 每项缺字段 %s" % field)
    return rows


def _options_of(subject, mode) -> dict:
    raw = subject.get("options")
    if not isinstance(raw, dict):
        raise ValueError("subject.options 必须是对象（数值口径唯一来源，器官零默认值）")
    privacy_cfg = raw.get("privacy") or {}
    if not isinstance(privacy_cfg, dict):
        raise ValueError("options.privacy 必须是对象")
    private_domains = _domain_list(privacy_cfg.get("private_domains"), "options.privacy.private_domains")
    sensitive_domains = _domain_list(privacy_cfg.get("sensitive_domains"), "options.privacy.sensitive_domains")
    options = {
        "private_domains": private_domains,
        "sensitive_domains": sensitive_domains,
    }
    need_keys = {
        "timezone_utc_offset_minutes": int,
        "session_gap_minutes": int,
        "report_top_n": int,
        "cluster_min_df": int,
        "cluster_max_features": int,
        "cluster_top_terms": int,
        "cluster_similarity_threshold": float,
        "random_seed": int,
        "search_ngram_n": int,
        "forgotten_days_threshold": int,
        "forgotten_min_visits": int,
        "forgotten_min_distinct_days": int,
    }
    for key, caster in need_keys.items():
        value = raw.get(key)
        if value is None:
            raise ValueError("options.%s 必填（数值口径唯一来源 = subject，器官零默认值）" % key)
        options[key] = caster(value)
    weekday_start = raw.get("weekday_start")
    if weekday_start is None:
        raise ValueError("options.weekday_start 必填（monday|sunday）")
    options["weekday_start"] = str(weekday_start)
    today = raw.get("today_local_date")
    if today is None:
        raise ValueError("options.today_local_date 必填（ISO 日期串；器官不读时钟）")
    options["today_local_date"] = today
    if "search" in raw:
        options["search"] = raw["search"]
    return options


def _domain_list(value, label: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("%s 必须是字符串数组" % label)
    return value
