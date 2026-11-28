"""器官 ``bookmark-doctor``：收藏夹体检账本（迁自 10-16-bookmark-doctor）。

旧仓 ``bookmark-doctor`` 导入浏览器书签后做失效检测 + 重复合并 + 长期未访问画像。
本器官照搬判定层：URL 规范化六步流水线、状态分类引擎（规则优先 + 通用映射 +
保守冲突）、锚点硬门、去重引擎（保留策略固定、绝不自动删）、未访问画像分档。
把 Netscape/Chrome 解析、网络探测、HTML 报告、导回写盘、CLI 留在输入层/报告层。

**三态口径（照搬）**：失效（dead）= 唯一通用判死证据是 404/410；反爬/风控/5xx/
DNS/超时一律**待复核**（review），绝不判失效；"未探测"不会被说成"存活"。
账本映射：dead → error（阻断）、review → warn、alive → info。
"""

from __future__ import annotations

import datetime
from typing import Iterable, List, Mapping

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import aging as aging_mod
from . import classify as classify_mod
from . import dedupe as dedupe_mod
from . import spec


def evaluate(subject: Mapping, basis) -> Iterable[Record]:
    """账本入口：subject = {mode, bookmarks, observations?, degrade_rules?,
    observations_ledger?, tracked_query_params?, aging?, options?}。

    ``mode`` ∈ audit（check+dedupe+aging 一次跑完）/ check / dedupe / aging。
    """
    mode = _mode_of(subject)
    bookmarks = _bookmarks_of(subject)
    records: List[Record] = []

    if mode in ("audit", "check"):
        records.extend(_run_check(subject, basis))

    if mode in ("audit", "dedupe"):
        tracked = _tracked_of(subject)
        records.extend(_run_dedupe(subject, basis, bookmarks, tracked))

    if mode in ("audit", "aging"):
        records.extend(_run_aging(subject, basis, bookmarks))

    counts = {verdict: 0 for verdict in (ERROR, WARN, INFO)}
    for record in records:
        counts[record.verdict] += 1
    records.append(
        Record(
            rule_id=spec.RULE_SUMMARY,
            verdict=INFO,
            message="mode=%s：error=%d warn=%d info=%d（error 档 = dead 链接，warn 档 = review/重复组）"
            % (
                mode,
                counts[ERROR],
                counts[WARN],
                counts[INFO],
            ),
            basis=basis.ref(spec.RULE_SUMMARY),
            path="summary",
            evidence={
                "mode": mode,
                "error": counts[ERROR],
                "warn": counts[WARN],
                "info": counts[INFO],
            },
        )
    )
    return records


# ------------------------------------------------------------------ check
def _run_check(subject, basis) -> List[Record]:
    records: List[Record] = []
    observations = _observations_of(subject)
    if observations is None:
        return records
    degrade_rules = _degrade_rules_of(subject)
    ledger = _ledger_of(subject)
    enabled, disabled = classify_mod.apply_anchor_gate(
        {"degrade_rules": degrade_rules}, ledger
    )
    for item in disabled:
        records.append(
            Record(
                rule_id=spec.RULE_ANCHOR_DISABLED,
                verdict=INFO,
                message="规则 %s 未启用（%s）：观测 %s 未验证，不参与判定"
                % (item["id"], item["reason"], item.get("observation_id")),
                basis=basis.ref(spec.RULE_ANCHOR_DISABLED),
                path="rules.disabled.%s" % item["id"],
                evidence=dict(item),
            )
        )
    for index, obs in enumerate(observations):
        if not isinstance(obs, dict):
            raise ValueError("observations 的每一项必须是对象")
        url = obs.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("observations 每项必须有非空 url")
        result = classify_mod.classify(obs, enabled)
        rule_id = spec.RULE_BY_LINK_VERDICT[result["verdict"]]
        verdict = spec.VERDICT_SEVERITY[result["verdict"]]
        records.append(
            Record(
                rule_id=rule_id,
                verdict=verdict,
                message="%s：%s（%s）" % (url, result["verdict"], result["reason"]),
                basis=basis.ref(rule_id),
                path="observations[%d]" % index,
                evidence={
                    "url": url,
                    "verdict": result["verdict"],
                    "reason": result["reason"],
                    "rule_id": result["rule_id"],
                    "http_status": obs.get("http_status"),
                    "first_hop_status": obs.get("first_hop_status"),
                    "error_class": obs.get("error_class"),
                },
            )
        )
        if result["conflict"]:
            records.append(
                Record(
                    rule_id=spec.RULE_CONFLICT,
                    verdict=WARN,
                    message="%s：多规则判定冲突，保守取 %s" % (url, result["verdict"]),
                    basis=basis.ref(spec.RULE_CONFLICT),
                    path="observations[%d].conflict" % index,
                    evidence={"url": url, "conflict": result["conflict"], "verdict": result["verdict"]},
                )
            )
    return records


# ------------------------------------------------------------------ dedupe
def _run_dedupe(subject, basis, bookmarks, tracked) -> List[Record]:
    records: List[Record] = []
    check_records = []
    for obs in _observations_of(subject) or []:
        if obs.get("final_url"):
            check_records.append(obs)
    groups = dedupe_mod.build_duplicate_groups(bookmarks, tracked, check_records)
    for group in groups:
        records.append(
            Record(
                rule_id=spec.RULE_DUPLICATE_GROUP,
                verdict=WARN,
                message="%s：%d 条同键重复（建议保留 %s，只出清单不删除）"
                % (group["group_id"], len(group["members"]), group["keep"]["id"]),
                basis=basis.ref(spec.RULE_DUPLICATE_GROUP),
                path="dedupe.%s" % group["group_id"],
                evidence=dict(group),
            )
        )
    return records


# ------------------------------------------------------------------ aging
def _run_aging(subject, basis, bookmarks) -> List[Record]:
    records: List[Record] = []
    aging_date = _aging_date_of(subject)
    tiers_days = aging_mod.load_aging_tiers({"aging": subject.get("aging")})
    profile = aging_mod.build_aging_profile(bookmarks, tiers_days, aging_date)
    for kind, key, tier in aging_mod.aging_assignments(profile):
        if kind == "unknown":
            if not tier["ids"]:
                continue
            records.append(
                Record(
                    rule_id=spec.RULE_AGING_UNKNOWN,
                    verdict=INFO,
                    message="%d 条添加时间未知（缺失不猜补，不参与分档）" % tier["count"],
                    basis=basis.ref(spec.RULE_AGING_UNKNOWN),
                    path="aging.unknown",
                    evidence={"count": tier["count"], "ids": list(tier["ids"]), "as_of_date": profile["as_of_date"]},
                )
            )
            continue
        if not tier["ids"]:
            continue
        rule_id = spec.RULE_AGING_TIER
        if kind == "within":
            message = "%s：%d 条（as_of %s，%s）" % (key, tier["count"], profile["as_of_date"], profile["note"])
            evidence = {"tier": key, "count": tier["count"], "ids": list(tier["ids"]), "as_of_date": profile["as_of_date"], "proxy": profile["note"]}
        else:
            message = "%s（≥%d 天）：%d 条（as_of %s，%s）" % (
                key,
                tier["min_days"],
                tier["count"],
                profile["as_of_date"],
                profile["note"],
            )
            evidence = {
                "tier": key,
                "min_days": tier["min_days"],
                "count": tier["count"],
                "ids": list(tier["ids"]),
                "as_of_date": profile["as_of_date"],
                "proxy": profile["note"],
            }
        records.append(
            Record(
                rule_id=rule_id,
                verdict=INFO,
                message=message,
                basis=basis.ref(rule_id),
                path="aging.%s" % key,
                evidence=evidence,
            )
        )
    return records


# ------------------------------------------------------------------ 输入规整
def _mode_of(subject) -> str:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if not isinstance(mode, str) or mode not in spec.MODES:
        raise ValueError("subject.mode 必须是 %s 之一" % "|".join(spec.MODES))
    return mode


def _bookmarks_of(subject) -> list:
    bookmarks = subject.get("bookmarks")
    if not isinstance(bookmarks, list):
        raise ValueError("subject.bookmarks 必须是数组")
    out = []
    for bm in bookmarks:
        if not isinstance(bm, dict):
            raise ValueError("bookmarks 的每一项必须是对象")
        url = bm.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError("bookmarks 每项必须有非空 url")
        out.append(bm)
    return out


def _observations_of(subject):
    observations = subject.get("observations")
    if observations is None:
        return None
    if not isinstance(observations, list):
        raise ValueError("subject.observations 必须是数组")
    return observations


def _degrade_rules_of(subject) -> list:
    rules = subject.get("degrade_rules")
    if rules is None:
        return []
    if not isinstance(rules, list):
        raise ValueError("subject.degrade_rules 必须是数组")
    return rules


def _ledger_of(subject) -> dict:
    ledger = subject.get("observations_ledger")
    if ledger is None:
        return {"observations": []}
    if not isinstance(ledger, dict):
        raise ValueError("subject.observations_ledger 必须是对象")
    return {"observations": ledger.get("observations") or []}


def _tracked_of(subject) -> dict:
    tracked = subject.get("tracked_query_params")
    if tracked is None:
        return {"exact": [], "prefixes": []}
    if not isinstance(tracked, dict):
        raise ValueError("subject.tracked_query_params 必须是对象")
    return tracked


def _aging_date_of(subject) -> datetime.date:
    options = subject.get("options") or {}
    raw = options.get("aging_date")
    if not isinstance(raw, str) or not raw:
        raise ValueError("options.aging_date 必填（YYYY-MM-DD 参考日，器官不读时钟）")
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise ValueError("options.aging_date 不是合法日期：%r" % (raw,))
