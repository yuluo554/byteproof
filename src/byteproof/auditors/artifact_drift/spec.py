"""设置面 + 规则表（旧仓 ``bdiff`` 的判定子集）。

规则集与计数键序只在 ``src/byteproof/data/artifact-drift.thresholds.json`` 定义；
``T1–T12`` 是旧仓 ``data/README.md`` §4.1 的闭合分类法，顺序即优先级。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from byteproof.core.ledger import ERROR, INFO, WARN

T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12 = (
    "T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12"
)
RULE_IDS = [T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12]
METADATA_RULES = RULE_IDS[:-1]

RULE_PREFIX = "drift-"
RULE_DIFF = {rule: RULE_PREFIX + rule.lower() for rule in RULE_IDS}
RULE_UNBUDGETED = "drift-unbudgeted"
RULE_CAUSE = "drift-cause"

ALL_RULE_IDS = tuple(RULE_DIFF.values()) + (RULE_UNBUDGETED, RULE_CAUSE)

VERDICT_BY_RULE = {RULE_DIFF[rule]: (ERROR if rule == T12 else WARN) for rule in RULE_IDS}
VERDICT_BY_RULE[RULE_UNBUDGETED] = ERROR
VERDICT_BY_RULE[RULE_CAUSE] = INFO

STATUS_SAME = "SAME"
STATUS_ADDED = "ADDED"
STATUS_REMOVED = "REMOVED"
STATUS_RENAMED = "RENAMED"

KIND_FILE = "file"
KIND_DIR = "dir"
KIND_LINK = "symlink"
KINDS = (KIND_FILE, KIND_DIR, KIND_LINK)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def verdict_for(rule_id):
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))


@dataclass(frozen=True)
class Settings:
    budget: tuple = ()

    def allows(self, rule):
        return rule in self.budget


DEFAULT_SETTINGS = Settings()


def resolve_params(params=None) -> Settings:
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params 必须是 JSON 对象")
    budget = ()
    if params:
        unknown = sorted(set(params) - {"budget"})
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        if "budget" in params:
            value = params["budget"]
            if not isinstance(value, list):
                raise ValueError("params.budget 必须是列表")
            for item in value:
                if item not in METADATA_RULES:
                    raise ValueError("params.budget 里的类别必须是 T1–T11：%r" % (item,))
            budget = tuple(sorted(set(value)))
    return Settings(budget=budget)