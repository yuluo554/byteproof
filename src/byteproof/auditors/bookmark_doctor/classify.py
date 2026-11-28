"""状态分类引擎（照搬旧仓 ``src/bookmark_doctor/classify.py`` + ruleset 的锚点硬门纯判定）。

判定优先级（冻结，照搬）：
1. **规则命中**（锚点硬门已通过的 degrade_rules）> 通用映射；
2. 多规则冲突 → **保守**：``review`` > ``dead`` > ``alive``，并留冲突备注；
3. 通用映射表：终态 2xx → alive；终态 3xx → review；404/410 → dead（唯一通用判死
   证据）；401/403/405/406/429/451 → review；5xx → review；521/522/523 → cdn_blocked
   review；error_class → review；无状态无错误 → probe_incomplete review（不可静默判 alive）。

规则匹配维度：``host_suffix`` + ``http_status``，**首跳或终态任一命中**即可
（风控链首跳 302、终态登录/访客页 200——只读终态则规则永不命中）。

网络探测本身属输入层：器官消费输入层给出的**观测事实**（probe record），不发请求。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .spec import CONSERVATIVE_ORDER

# HTTP 语义区间（语义分类表，非政策数值）
REASON_HTTP_2XX = "http_2xx"
REASON_REDIRECT_UNRESOLVED = "redirect_unresolved"
REASON_HTTP_404 = "http_404"
REASON_HTTP_410 = "http_410"
REASON_HTTP_4XX_BLOCKED = "http_4xx_blocked"
REASON_HTTP_5XX = "http_5xx"
REASON_CDN_BLOCKED = "cdn_blocked"

CDN_BLOCKED_STATUSES = (521, 522, 523)
REVIEW_4XX_STATUSES = (401, 403, 405, 406, 429, 451)

# 锚点硬门原因码（与旧仓同名，测试锁定）
REASON_ANCHOR_MISSING = "anchor_missing"
REASON_ANCHOR_NOT_VERIFIED = "anchor_not_verified"


def _host_matches(host_suffix, url_host):
    """域名后缀匹配：host == suffix 或 host 以 "." + suffix 结尾（防近似域名误命中）。"""
    if not host_suffix:
        return False
    return url_host == host_suffix or url_host.endswith("." + host_suffix)


def _url_host(url):
    return (urlsplit(url).hostname or "").lower()


def generic_verdict(probe_record):
    """通用映射：观测记录 → (verdict, reason)。规则未命中时消费。"""
    error_class = probe_record.get("error_class")
    if error_class:
        # 跳转超限/成环/DNS/超时/TLS/连接失败 → 全部 review（保守）
        return "review", error_class
    status = probe_record.get("http_status")
    if status is None:
        # 无状态无错误：探测记录异常——保守 review（不可静默判 alive）
        return "review", "probe_incomplete"
    if 200 <= status < 300:
        return "alive", REASON_HTTP_2XX
    if 300 <= status < 400:
        return "review", REASON_REDIRECT_UNRESOLVED
    if status == 404:
        return "dead", REASON_HTTP_404
    if status == 410:
        return "dead", REASON_HTTP_410
    if status in REVIEW_4XX_STATUSES:
        return "review", REASON_HTTP_4XX_BLOCKED
    if status in CDN_BLOCKED_STATUSES:
        return "review", REASON_CDN_BLOCKED
    if 500 <= status < 600:
        return "review", REASON_HTTP_5XX
    # 其余 4xx（400/402/407-428/430+ 等）：语义不明 → 保守 review
    return "review", "http_other"


def match_rule(probe_record, rule):
    """单条规则是否命中该观测记录（host_suffix + http_status，首跳或终态）。"""
    match = rule.get("match") or {}
    suffix = match.get("host_suffix")
    if not suffix or not _host_matches(suffix, _url_host(probe_record.get("url", ""))):
        return False
    want_status = match.get("http_status")
    if want_status is None:
        return False
    observed = []
    for key in ("first_hop_status", "http_status"):
        value = probe_record.get(key)
        if value is not None:
            observed.append(value)
    return want_status in observed


def _conservative(pairs):
    """多判定冲突 → 保守取值 + 冲突备注。pairs: [(verdict, reason, rule_id)]。"""
    if not pairs:
        return None
    best = min(pairs, key=lambda item: CONSERVATIVE_ORDER.get(item[0], 3))
    verdicts = {item[0] for item in pairs}
    conflict_note = None
    if len(verdicts) > 1:
        conflict_note = "rule_conflict:" + "|".join(
            sorted("%s=%s" % (item[2] or "?", item[1]) for item in pairs)
        )
    return best[0], best[1], conflict_note


def classify(probe_record, effective_rules, match_fn=None):
    """观测记录 + 生效规则 → 分类结果 dict。

    返回 ``{"verdict", "reason", "rule_id"(或 None), "conflict"(或 None)}``。
    """
    matcher = match_fn or match_rule
    hits = []
    for rule in effective_rules:
        if matcher(probe_record, rule):
            hits.append((rule.get("disposition"), rule.get("reason"), rule.get("id")))
    if hits:
        verdict, reason, conflict_note = _conservative(hits)
        return {
            "verdict": verdict,
            "reason": reason,
            "rule_id": hits[0][2],
            "conflict": conflict_note,
        }
    verdict, reason = generic_verdict(probe_record)
    return {"verdict": verdict, "reason": reason, "rule_id": None, "conflict": None}


def apply_anchor_gate(ruleset, observations):
    """锚点硬门 → (enabled_rules, disabled)（照搬 ruleset.apply_anchor_gate）。

    每条 ``degrade_rules`` 规则的 ``anchor.observation_id`` 必须解析到台账中
    ``check_status=verified`` 的观测；否则该规则**拒绝启用**，连同原因进未启用清单。
    disabled 每项 ``{"id", "reason", "observation_id", "check_status"?}``。
    """
    by_id = {}
    for obs in observations.get("observations", []):
        by_id[obs.get("id")] = obs
    enabled, disabled = [], []
    for rule in ruleset.get("degrade_rules", []):
        anchor = rule.get("anchor") or {}
        obs_id = anchor.get("observation_id")
        obs = by_id.get(obs_id)
        if obs is None:
            disabled.append(
                {"id": rule["id"], "reason": REASON_ANCHOR_MISSING, "observation_id": obs_id}
            )
        elif obs.get("check_status") != "verified":
            disabled.append(
                {
                    "id": rule["id"],
                    "reason": REASON_ANCHOR_NOT_VERIFIED,
                    "observation_id": obs_id,
                    "check_status": obs.get("check_status"),
                }
            )
        else:
            enabled.append(rule)
    return enabled, disabled
