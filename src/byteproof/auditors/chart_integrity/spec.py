"""设置面 + 规则表（旧仓 ``chartaudit`` 的判定子集）。

阈值唯一出处是 ``src/byteproof/data/chart-integrity.thresholds.json``；运行期默认值
必须与它逐项相等（测试钉住）。别名表（误差棒列名）随 params 提供，器官不内置业务词表。

**没有搬**：CSV 解析、normalized spec 校验（解析层）、HTML 渲染与几何包、发布门、
bench、冻结数据生成、系统时钟。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Mapping

from byteproof.core.ledger import ERROR, INFO, WARN

CONTRACT_VERSION = 1
QUANT_DECIMALS = 6
ROW_INDEX_OFFSET = 2
DATE_COLUMN_TYPE = "date"

NUMERIC_COLUMN_TYPES = ("integer", "decimal")
AGGREGATE_TRANSFORMS = ("group_sum", "group_mean", "group_median", "group_count", "ratio")
TRANSFORM_WHITELIST = (
    "identity",
    "filter",
    "group_sum",
    "group_mean",
    "group_median",
    "group_count",
    "ratio",
    "sort",
    "top_n",
    "stack_offset",
)

RULE_BAR = "chart-bar-baseline"
RULE_DUAL_Y = "chart-dual-y"
RULE_PIE = "chart-pie-sectors"
RULE_3D = "chart-pseudo-3d"
RULE_RADIUS = "chart-radius"
RULE_SMOOTH = "chart-smooth"
RULE_TIME = "chart-time-axis"
RULE_CONTRAST = "chart-low-contrast"
RULE_SPEC_INVALID = "chart-spec-invalid"

RULE_PROV_MISSING = "chart-provenance-missing"
RULE_PROV_UNEXPECTED = "chart-provenance-unexpected"
RULE_PROV_MALFORMED = "chart-provenance-malformed"
RULE_PROV_MISMATCH = "chart-provenance-mismatch"

RULE_G2_VIOLATION = "chart-g2-small-n"
RULE_G2_UNDETERMINED = "chart-g2-undetermined"
RULE_G2_ALTERNATIVE = "chart-g2-alternative"
RULE_G3_SOURCE = "chart-g3-source"
RULE_G3_UNDECLARED = "chart-g3-undeclared"

RULE_IDS = (
    RULE_BAR,
    RULE_DUAL_Y,
    RULE_PIE,
    RULE_3D,
    RULE_RADIUS,
    RULE_SMOOTH,
    RULE_TIME,
    RULE_CONTRAST,
    RULE_SPEC_INVALID,
    RULE_PROV_MISSING,
    RULE_PROV_UNEXPECTED,
    RULE_PROV_MALFORMED,
    RULE_PROV_MISMATCH,
    RULE_G2_VIOLATION,
    RULE_G2_UNDETERMINED,
    RULE_G2_ALTERNATIVE,
    RULE_G3_SOURCE,
    RULE_G3_UNDECLARED,
)

VERDICT_BY_RULE = {
    RULE_BAR: ERROR,
    RULE_DUAL_Y: ERROR,
    RULE_PIE: ERROR,
    RULE_3D: ERROR,
    RULE_RADIUS: ERROR,
    RULE_SMOOTH: ERROR,
    RULE_TIME: ERROR,
    RULE_CONTRAST: ERROR,
    RULE_SPEC_INVALID: ERROR,
    RULE_PROV_MISSING: ERROR,
    RULE_PROV_UNEXPECTED: ERROR,
    RULE_PROV_MALFORMED: ERROR,
    RULE_PROV_MISMATCH: ERROR,
    RULE_G2_VIOLATION: ERROR,
    RULE_G2_UNDETERMINED: WARN,
    RULE_G2_ALTERNATIVE: INFO,
    RULE_G3_SOURCE: ERROR,
    RULE_G3_UNDECLARED: INFO,
}


def verdict_for(rule_id):
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))


DEFAULT_ALIASES = {
    "case_sensitive": False,
    "match_mode": "suffix",
    "type_order": ["sd", "sem", "ci", "n"],
    "types": {
        "sd": {"columns": ["SD", "标准差", "标准偏差", "std", "stddev"], "title": ["SD", "标准差"]},
        "sem": {"columns": ["SEM", "标准误", "标准误差", "SE"], "title": ["SEM", "标准误"]},
        "ci": {
            "lower": ["CI下限", "CI下界", "置信区间下限", "ci_low", "ci_lower"],
            "upper": ["CI上限", "CI上界", "置信区间上限", "ci_high", "ci_upper"],
            "title": ["CI", "置信区间"],
        },
        "n": {"columns": ["样本数", "样本量"], "title": ["样本量", "样本数", "n="]},
    },
}


@dataclass(frozen=True)
class Settings:
    n_min: int = 5
    skew_abs_threshold: float = 1.0
    skew_min_n: int = 3
    multimodal_bins: int = 6
    multimodal_min_n: int = 4
    multimodal_min_count_floor: int = 2
    multimodal_min_count_divisor: int = 6
    sem_tolerance_abs: str = "0.000000000001"
    pie_max_sectors: int = 4
    aliases: Mapping = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.aliases is None:
            object.__setattr__(self, "aliases", json.loads(json.dumps(DEFAULT_ALIASES)))


DEFAULT_SETTINGS = Settings()

_INT_KEYS = (
    "n_min",
    "skew_min_n",
    "multimodal_bins",
    "multimodal_min_n",
    "multimodal_min_count_floor",
    "multimodal_min_count_divisor",
    "pie_max_sectors",
)
_PARAM_KEYS = _INT_KEYS + ("skew_abs_threshold", "sem_tolerance_abs", "aliases")


def _coerce_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("params.%s 必须是正整数，得到 %r" % (key, value))
    return value


def _coerce_float(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("params.skew_abs_threshold 必须是正数，得到 %r" % (value,))
    return float(value)


def _coerce_tolerance(value):
    try:
        number = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        raise ValueError("params.sem_tolerance_abs 不是数值：%r" % (value,))
    if number < 0:
        raise ValueError("params.sem_tolerance_abs 不能为负")
    return str(value)


def _coerce_aliases(value):
    if not isinstance(value, Mapping):
        raise ValueError("params.aliases 必须是对象")
    if not isinstance(value.get("case_sensitive"), bool):
        raise ValueError("aliases.case_sensitive 必须是布尔值")
    if value.get("match_mode") != "suffix":
        raise ValueError("aliases.match_mode 只允许 suffix")
    order = value.get("type_order")
    if not isinstance(order, list) or not order or len(set(order)) != len(order):
        raise ValueError("aliases.type_order 必须是非空唯一列表")
    types = value.get("types")
    if not isinstance(types, Mapping):
        raise ValueError("aliases.types 必须是对象")
    for type_name in order:
        if type_name not in types:
            raise ValueError("aliases.types 缺少 %s" % type_name)
        entry = types[type_name]
        keys = ("lower", "upper") if type_name == "ci" else ("columns", "title")
        for key in keys:
            if not isinstance(entry.get(key), list) or not entry[key]:
                raise ValueError("aliases.types.%s.%s 必须是非空列表" % (type_name, key))
    return json.loads(json.dumps(value))


def resolve_params(params=None) -> Settings:
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params 必须是 JSON 对象")
    resolved = {key: getattr(DEFAULT_SETTINGS, key) for key in _PARAM_KEYS}
    if params:
        unknown = sorted(set(params) - set(_PARAM_KEYS))
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        for key in _PARAM_KEYS:
            if key in params:
                resolved[key] = params[key]
    for key in _INT_KEYS:
        resolved[key] = _coerce_int(key, resolved[key])
    resolved["skew_abs_threshold"] = _coerce_float(resolved["skew_abs_threshold"])
    resolved["sem_tolerance_abs"] = _coerce_tolerance(resolved["sem_tolerance_abs"])
    resolved["aliases"] = _coerce_aliases(resolved["aliases"])
    if resolved["multimodal_min_n"] < 2:
        raise ValueError("params.multimodal_min_n 必须 >= 2")
    if resolved["skew_min_n"] < 3:
        raise ValueError("params.skew_min_n 必须 >= 3")
    if resolved["multimodal_bins"] < 2:
        raise ValueError("params.multimodal_bins 必须 >= 2")
    return Settings(**resolved)


def decimal_or_raise(value, label):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("%s 不是十进制数值：%r" % (label, value))