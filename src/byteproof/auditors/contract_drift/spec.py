"""设置面 + 规则表（旧仓 ``contractcompat`` 的判定子集）。

规则表是数据（旧仓 ``rules/rule-table.json``）；本器官把规则 id / 默认 severity /
修复动作固化在 basis 与 ``spec``，求值函数只做映射与三值判定。

七档 policy = 允许哪个方向；direction 是事实，policy 是选择。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from byteproof.core.ledger import ERROR, INFO, WARN

POLICIES = (
    "backward",
    "backward-transitive",
    "forward",
    "forward-transitive",
    "full",
    "full-transitive",
    "none",
)
TRANSITIVE = tuple(name for name in POLICIES if name.endswith("-transitive"))

DIRECTIONS = ("BACKWARD_OK", "FORWARD_OK", "BOTH_OK", "NONE_OK")
DEPLOY_ORDERS = ("consumers-first", "producers-first", "simultaneous", "replay")
BLAST_RADIUS = {
    "consumers-first": "OLD_CONSUMER",
    "producers-first": "NEW_CONSUMER",
    "simultaneous": "BOTH",
    "replay": "REPLAY_ONLY",
}
NOT_GIVEN_NOTE = "deploy_order_not_given"

FORMATS = ("proto", "avro", "jsonschema")
KIND_RULES = {
    "field_removed": "R1",
    "type_changed": "R2",
    "cardinality_changed": "R3",
    "requiredness_changed": "R3",
    "enum_narrowed": "R4",
    "enum_widened": "R4",
    "enum_renumbered": "R4",
    "enum_changed": "R4",
    "field_number_reused": "R5",
    "reserved_conflict": "R5",
    "cross_message_reuse": "R5",
    "oneof_moved": "R6",
    "default_changed": "R7",
}

RULE_META = {
    "R1": {"default": "breaking", "repair_action": "reserve"},
    "R2": {"default": "breaking", "repair_action": "bump-and-version"},
    "R3": {"default": "breaking", "repair_action": "add-default"},
    "R4": {"default": "runtime-dependent", "repair_action": "bump-and-version"},
    "R5": {"default": "breaking", "repair_action": "reserve"},
    "R6": {"default": "runtime-dependent", "repair_action": "add-branch"},
    "R7": {"default": "non-breaking", "repair_action": "add-default"},
}

SEVERITY_BY_DETAIL = {
    "R2": {
        "union_widened": "non-breaking",
        "wire_compatible": "runtime-dependent",
        "promotion": "runtime-dependent",
        "widened": "runtime-dependent",
    }
}

EVIDENCE = {
    "R1": {
        "proto": "field_number_missing_without_reserved",
        "avro": "field_absent_or_renamed_without_alias",
        "jsonschema": "property_absent_or_removed_from_required",
    },
    "R2": {
        "proto": "wire_incompatible_type_change",
        "avro": "type_or_logical_type_change",
        "jsonschema": "type_or_format_change",
    },
    "R3": {
        "proto": "label_change_or_new_required_without_default",
        "avro": "new_field_without_default",
        "jsonschema": "required_list_added",
    },
    "R4": {
        "proto": "enum_value_removed_or_renamed",
        "avro": "symbol_removed",
        "jsonschema": "enum_list_narrowed",
    },
    "R5": {"proto": "field_number_reused_or_conflicts_with_reserved"},
    "R6": {"proto": "field_entered_or_left_oneof", "jsonschema": "oneof_or_anyof_branch_moved"},
    "R7": {"proto": "default_value_changed", "avro": "default_changed", "jsonschema": "default_changed"},
}

#: 该格式没有这个概念的规则槽位 -> 显式 N/A，不得省略。
NOT_APPLICABLE = {
    "avro": {"R5": "Avro 无字段号概念（按字段名解析），本规则不适用", "R6": "Avro 无 oneof 概念；union 分支移动按 R2/R4 归因"},
    "jsonschema": {"R5": "JSON Schema 无字段号概念（按属性名寻址），本规则不适用"},
    "proto": {},
}

RULE_IDS = ("R1", "R2", "R3", "R4", "R5", "R6", "R7")
RULE_FOR_ORGAN = {rule: "contract-" + rule.lower() for rule in RULE_IDS}
RULE_GATE = "contract-gate"
RULE_SUMMARY = "contract-summary"
ALL_RULE_IDS = tuple(RULE_FOR_ORGAN.values()) + (RULE_GATE, RULE_SUMMARY)

VERDICT_BY_RULE = {
    "contract-r1": ERROR,
    "contract-r2": ERROR,
    "contract-r3": ERROR,
    "contract-r4": WARN,
    "contract-r5": ERROR,
    "contract-r6": WARN,
    "contract-r7": INFO,
    RULE_GATE: ERROR,
    RULE_SUMMARY: INFO,
}


def verdict_for(rule_id):
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))


@dataclass(frozen=True)
class Settings:
    policy: str = "backward"
    deploy_order: str = None  # type: ignore[assignment]
    history: tuple = ()


def allows(policy, direction):
    if policy == "none":
        return True
    if policy in ("backward", "backward-transitive"):
        return direction in ("BACKWARD_OK", "BOTH_OK")
    if policy in ("forward", "forward-transitive"):
        return direction in ("FORWARD_OK", "BOTH_OK")
    return direction == "BOTH_OK"


def resolve_params(params=None) -> Settings:
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params 必须是 JSON 对象")
    policy = "backward"
    deploy_order = None
    history = []
    if params:
        unknown = sorted(set(params) - {"policy", "deploy_order", "history"})
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        policy = params.get("policy", policy)
        deploy_order = params.get("deploy_order", deploy_order)
        history = params.get("history", history)
    if policy not in POLICIES:
        raise ValueError("未知 policy：%r（允许 %s）" % (policy, ", ".join(POLICIES)))
    if deploy_order is not None and deploy_order not in DEPLOY_ORDERS:
        raise ValueError("未知 deploy_order：%r（允许 %s）" % (deploy_order, ", ".join(DEPLOY_ORDERS)))
    if not isinstance(history, list):
        raise ValueError("params.history 必须是列表")
    for group in history:
        if not isinstance(group, list):
            raise ValueError("params.history 的每一项必须是差异列表")
    if policy in TRANSITIVE and not history:
        raise ValueError("%s 需要 history（至少一个历史版本）；不降级为单版本比较" % policy)
    if policy not in TRANSITIVE and history:
        raise ValueError("%s 不接受 history（只有 *-transitive 档使用历史版本）" % policy)
    return Settings(policy=policy, deploy_order=deploy_order, history=tuple(tuple(group) for group in history))