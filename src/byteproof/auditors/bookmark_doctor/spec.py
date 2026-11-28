"""口径面：规则 id、名义 verdict、模式集合与固定口径串（迁自 10-16-bookmark-doctor）。

默认严重度照搬旧仓 ``plan/04`` 冻结口径：dead = 阻断（error）、review = 待复核
（warn）、alive = 记录（info）；重复组 = 清理建议（warn）；锚点未启用与未访问画像 =
显式记录（info）。规则 id 前缀 ``bd-``。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

#: 旧仓 CLI 的五个子命令；import/report/export/run 的文件编排面不迁（输入层/报告层）。
MODES = ("audit", "check", "dedupe", "aging")
DEFAULT_MODE = "audit"

VERDICT_SEVERITY = {
    "dead": "error",
    "review": "warn",
    "alive": "info",
}

SEVERITY_TO_VERDICT = {"error": "error", "warning": "warn", "info": "info"}

RULE_LINK_DEAD = "bd-link-dead"
RULE_LINK_REVIEW = "bd-link-review"
RULE_LINK_ALIVE = "bd-link-alive"
RULE_CONFLICT = "bd-rule-conflict"
RULE_ANCHOR_DISABLED = "bd-anchor-disabled"
RULE_DUPLICATE_GROUP = "bd-duplicate-group"
RULE_AGING_TIER = "bd-aging-tier"
RULE_AGING_UNKNOWN = "bd-aging-unknown"
RULE_SUMMARY = "bd-summary"

RULE_BY_LINK_VERDICT = {
    "dead": RULE_LINK_DEAD,
    "review": RULE_LINK_REVIEW,
    "alive": RULE_LINK_ALIVE,
}

RULE_IDS = (
    RULE_LINK_DEAD,
    RULE_LINK_REVIEW,
    RULE_LINK_ALIVE,
    RULE_CONFLICT,
    RULE_ANCHOR_DISABLED,
    RULE_DUPLICATE_GROUP,
    RULE_AGING_TIER,
    RULE_AGING_UNKNOWN,
    RULE_SUMMARY,
)

VERDICTS = {
    RULE_LINK_DEAD: "error",
    RULE_LINK_REVIEW: "warn",
    RULE_LINK_ALIVE: "info",
    RULE_CONFLICT: "warn",
    RULE_ANCHOR_DISABLED: "info",
    RULE_DUPLICATE_GROUP: "warn",
    RULE_AGING_TIER: "info",
    RULE_AGING_UNKNOWN: "info",
    RULE_SUMMARY: "info",
}

#: 旧仓 classify._VERDICT_ORDER_CONSERVATIVE 的冲突保守序。
CONSERVATIVE_ORDER = {"review": 0, "dead": 1, "alive": 2}

AGING_NOTE = "以添加时间近似未访问；浏览器不导出真实访问记录"
