"""口径面：规则 id、名义 verdict 与固定口径串（迁自 10-18-browser-history-vault）。

旧仓五个功能命令（report/search/cluster/archive/snapshot）**完成即 rc0**——洞察结论
是辅助参考，不阻断。账本映射照此口径：全部规则 info 级（severity/语义写进
evidence），与旧退出码逐一对齐。规则 id 前缀 ``bh-``。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

MODES = ("audit", "normalize", "report", "search", "cluster")
DEFAULT_MODE = "audit"

RULE_PRIVACY_EXCLUDED = "bh-privacy-private-excluded"
RULE_PRIVACY_MASKED = "bh-privacy-sensitive-masked"
RULE_COVERAGE_GAP = "bh-coverage-gap"
RULE_FORGOTTEN = "bh-forgotten-treasure"
RULE_SESSION_STATS = "bh-session-stats"
RULE_CLUSTER = "bh-topic-cluster"
RULE_RESEARCH_PATH = "bh-research-path"
RULE_SEARCH_HIT = "bh-search-hit"
RULE_NORMALIZE_DUPLICATE = "bh-normalize-duplicate"
RULE_SUMMARY = "bh-summary"

RULE_IDS = (
    RULE_PRIVACY_EXCLUDED,
    RULE_PRIVACY_MASKED,
    RULE_COVERAGE_GAP,
    RULE_FORGOTTEN,
    RULE_SESSION_STATS,
    RULE_CLUSTER,
    RULE_RESEARCH_PATH,
    RULE_SEARCH_HIT,
    RULE_NORMALIZE_DUPLICATE,
    RULE_SUMMARY,
)

VERDICTS = {rule_id: "info" for rule_id in RULE_IDS}

SESSION_SPLIT_RULE = "相邻间隔严格大于配置间隔才切分（恰好等于不切分）；按来源分组"

FORGOTTEN_CONDITIONS = (
    "last_visit_days_ago_strictly_greater_than_threshold",
    "visits_at_least_min_visits",
    "distinct_local_days_at_least_min",
    "host_not_private_or_sensitive",
)

FORGOTTEN_DEFINITION = (
    "命中 = ①最后访问距『今天』的天数**严格大于** forgotten.days_threshold "
    "②总访问次数 ≥ forgotten.min_visits ③跨越的**本地**日历日数 ≥ forgotten.min_distinct_days "
    "④主机不在私密/敏感清单（天数按配置时区下的本地日计算）"
)

COVERAGE_DECLARATION = "覆盖区间按**口径时区下的本地日**统计（含首尾）；连续无数据的本地日合并为缺口区间"

PRIVACY_NOTE = (
    "私密（private）= 完全排除（连统计都不进）；敏感（sensitive）= 保留统计，仅打码呈现"
)
