"""设置面 + 分类表（旧仓 ``cfgdelta`` 的判定子集）。

五类 + 纯书写，顺序即输出顺序；``fail_on`` / ``allow_indeterminate`` 是门禁参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from byteproof.core.ledger import ERROR, INFO, WARN

RESOURCE_SHRINK = "资源·收缩"
DEPLOY_SHRINK = "部署·收缩"
IMAGE_CHANGE = "镜像·变更"
EXPOSURE = "接口·暴露"
CONFIG_CHANGE = "配置·新增·移除"
COSMETIC = "纯书写"

BEHAVIORAL = (RESOURCE_SHRINK, DEPLOY_SHRINK, IMAGE_CHANGE, EXPOSURE, CONFIG_CHANGE)
ALL_CLASSES = BEHAVIORAL + (COSMETIC,)

RULE_RESOURCE = "cfg-resource-shrink"
RULE_DEPLOY = "cfg-deploy-shrink"
RULE_IMAGE = "cfg-image-change"
RULE_EXPOSURE = "cfg-exposure"
RULE_CONFIG = "cfg-config-change"
RULE_COSMETIC = "cfg-cosmetic"
RULE_INDETERMINATE = "cfg-indeterminate"
RULE_GATE = "cfg-gate"
RULE_SUMMARY = "cfg-summary"

RULE_BY_CLASS = {
    RESOURCE_SHRINK: RULE_RESOURCE,
    DEPLOY_SHRINK: RULE_DEPLOY,
    IMAGE_CHANGE: RULE_IMAGE,
    EXPOSURE: RULE_EXPOSURE,
    CONFIG_CHANGE: RULE_CONFIG,
    COSMETIC: RULE_COSMETIC,
}

ALL_RULE_IDS = tuple(RULE_BY_CLASS.values()) + (RULE_INDETERMINATE, RULE_GATE, RULE_SUMMARY)

VERDICT_BY_RULE = {
    RULE_RESOURCE: WARN,
    RULE_DEPLOY: WARN,
    RULE_IMAGE: WARN,
    RULE_EXPOSURE: WARN,
    RULE_CONFIG: WARN,
    RULE_COSMETIC: INFO,
    RULE_INDETERMINATE: WARN,
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
    fail_on: tuple = ()
    allow_indeterminate: bool = False


DEFAULT_SETTINGS = Settings()


def resolve_params(params=None) -> Settings:
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params 必须是 JSON 对象")
    fail_on = ()
    allow = False
    if params:
        unknown = sorted(set(params) - {"fail_on", "allow_indeterminate"})
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        if "fail_on" in params:
            value = params["fail_on"]
            if not isinstance(value, list):
                raise ValueError("params.fail_on 必须是列表")
            for item in value:
                if item not in ALL_CLASSES:
                    raise ValueError("params.fail_on 含未知类：%r" % (item,))
            fail_on = tuple(sorted(set(value)))
        if "allow_indeterminate" in params:
            if not isinstance(params["allow_indeterminate"], bool):
                raise ValueError("params.allow_indeterminate 必须是布尔值")
            allow = params["allow_indeterminate"]
    return Settings(fail_on=fail_on, allow_indeterminate=allow)