"""设置面 + 规则表 + 报告期常量（旧仓 ``funddiff`` 的判定子集）。

旧仓把窗口、阈值、状态标签全部集中在冻结配置 ``data/config/app.json``（K10：代码零硬编码）。
本器官保留这条纪律的**判定部分**：可调数字随包登记在
``src/byteproof/data/fund-quarter-report.thresholds.json``，运行期常量与它逐项相等；
季度窗口、阈值、模式由 subject 的 ``params`` 覆盖。

**没有搬**：配置包 MANIFEST / 冻结校验、抓取、页面解析（HTML）、SQLite/清单存储、
报告渲染、合规词表业务内容（词表由 subject 提供）、系统时钟。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping

from byteproof.core.ledger import ERROR, INFO, WARN

QUANT_DECIMALS = 2
PARAMS_VERSION = "1"

QUARTER_ORDER = ("Q1", "Q2", "Q3", "Q4")
DEFAULT_QUARTER_ENDS = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}

STATUS_NEW = "新进"
STATUS_EXIT = "退出"
STATUS_INCREASE = "加仓"
STATUS_DECREASE = "减仓"
STATUS_UNCHANGED = "不变"
STATUS_PENDING = "待确认"

STATUS_LABELS = (STATUS_NEW, STATUS_EXIT, STATUS_INCREASE, STATUS_DECREASE, STATUS_UNCHANGED)
PENDING_LABEL = STATUS_PENDING

BASIS_COMPUTED = "computed"
BASIS_PROVIDER = "provider"
BASIS_INSUFFICIENT = "insufficient_data"
MODES = (BASIS_COMPUTED, BASIS_PROVIDER)

FUND_STATUS_OK = "ok"
FUND_STATUS_EMPTY = "empty"
FUND_STATUS_FAILED = "failed"
FUND_INSUFFICIENT = "insufficient_data"

BASELINE_AVAILABLE = "available"
BASELINE_NO_PREV = "no_prev_baseline"
BASELINES = (BASELINE_AVAILABLE, BASELINE_NO_PREV)

CLASS_IN_PERIOD = "in_period"
CLASS_PRIOR_PERIOD = "prior_period"
CLASS_NONE = "none"
CLASS_UNPARSED = "unparsed"
MANAGER_CLASSES = (CLASS_IN_PERIOD, CLASS_PRIOR_PERIOD, CLASS_NONE, CLASS_UNPARSED)

DISCLOSED = "已披露"
PENDING = "待披露"
NO_DATA = "无数据"

# ── 规则 ─────────────────────────────────────────────────────────────────
RULE_INVALID_CODE = "fq-invalid-code"
RULE_DUPLICATE_HOLDING = "fq-duplicate-holding"
RULE_RATIO_MISSING = "fq-ratio-missing"
RULE_RATIO_INVALID = "fq-ratio-invalid"
RULE_CHANGE_TYPE_MISSING = "fq-change-type-missing"
RULE_PROVIDER_CONFLICT = "fq-provider-conflict"
RULE_FAILED_QUARTER = "fq-failed-quarter"
RULE_PERIOD_MISMATCH = "fq-period-mismatch"
RULE_MANAGER_UNPARSED = "fq-manager-unparsed"
RULE_MANAGER_LABEL_DRIFT = "fq-manager-label-drift"
RULE_SCALE_FIELD_MISSING = "fq-scale-field-missing"
RULE_SCALE_BASELINE_FLOW = "fq-scale-baseline-flow"
RULE_SCALE_UNIT_MISSING = "fq-scale-unit-missing"
RULE_SCALE_NUMBER = "fq-scale-number"
RULE_SCALE_RATE = "fq-scale-rate"
RULE_SCALE_SOURCE = "fq-scale-source"
RULE_COMPLIANCE_TERM = "fq-compliance-term"
RULE_DISCLOSURE_UNVERIFIED = "fq-disclosure-unverified"
RULE_DISCLOSURE_PENDING = "fq-disclosure-pending"
RULE_DISCLOSURE_NO_DATA = "fq-disclosure-no-data"

RULE_IDS = (
    RULE_INVALID_CODE,
    RULE_DUPLICATE_HOLDING,
    RULE_RATIO_MISSING,
    RULE_RATIO_INVALID,
    RULE_CHANGE_TYPE_MISSING,
    RULE_PROVIDER_CONFLICT,
    RULE_FAILED_QUARTER,
    RULE_PERIOD_MISMATCH,
    RULE_MANAGER_UNPARSED,
    RULE_MANAGER_LABEL_DRIFT,
    RULE_SCALE_FIELD_MISSING,
    RULE_SCALE_BASELINE_FLOW,
    RULE_SCALE_UNIT_MISSING,
    RULE_SCALE_NUMBER,
    RULE_SCALE_RATE,
    RULE_SCALE_SOURCE,
    RULE_COMPLIANCE_TERM,
    RULE_DISCLOSURE_UNVERIFIED,
    RULE_DISCLOSURE_PENDING,
    RULE_DISCLOSURE_NO_DATA,
)

#: 规则 -> 等级。error 只给「结论不可复核」的结构性违约（重复代码、跨季错配、
#: 台账标签漂移、规模字段自相矛盾）；数据缺口的痕迹一律 warn / info。
VERDICT_BY_RULE = {
    RULE_INVALID_CODE: WARN,
    RULE_DUPLICATE_HOLDING: ERROR,
    RULE_RATIO_MISSING: WARN,
    RULE_RATIO_INVALID: ERROR,
    RULE_CHANGE_TYPE_MISSING: INFO,
    RULE_PROVIDER_CONFLICT: WARN,
    RULE_FAILED_QUARTER: WARN,
    RULE_PERIOD_MISMATCH: ERROR,
    RULE_MANAGER_UNPARSED: WARN,
    RULE_MANAGER_LABEL_DRIFT: ERROR,
    RULE_SCALE_FIELD_MISSING: ERROR,
    RULE_SCALE_BASELINE_FLOW: ERROR,
    RULE_SCALE_UNIT_MISSING: ERROR,
    RULE_SCALE_NUMBER: ERROR,
    RULE_SCALE_RATE: ERROR,
    RULE_SCALE_SOURCE: ERROR,
    RULE_COMPLIANCE_TERM: ERROR,
    RULE_DISCLOSURE_UNVERIFIED: WARN,
    RULE_DISCLOSURE_PENDING: INFO,
    RULE_DISCLOSURE_NO_DATA: WARN,
}


def verdict_for(rule_id):
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))


@dataclass(frozen=True)
class Settings:
    mode: str = BASIS_COMPUTED
    threshold: str = "0.10"
    disclosure_count: int = 15
    quarter_ends: Mapping = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.quarter_ends is None:
            object.__setattr__(self, "quarter_ends", dict(DEFAULT_QUARTER_ENDS))


DEFAULT_SETTINGS = Settings()

_PARAM_KEYS = ("mode", "threshold", "disclosure_count", "quarter_ends")


def _coerce_mode(value):
    if value not in MODES:
        raise ValueError("params.mode 必须是 %s 之一，得到 %r" % (MODES, value))
    return value


def _coerce_threshold(value):
    if value is None or isinstance(value, bool):
        raise ValueError("params.threshold 必须是十进制字符串")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("params.threshold 必须是十进制数，得到 %r" % (value,))
    if number <= 0:
        raise ValueError("params.threshold 必须 > 0，得到 %r" % (value,))
    return str(value)


def _coerce_count(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("params.disclosure_count 必须是正整数")
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError("params.disclosure_count 必须是正整数，得到 %r" % (value,))
    if count < 1:
        raise ValueError("params.disclosure_count 必须 >= 1")
    return count


def _coerce_quarter_ends(value):
    if not isinstance(value, Mapping):
        raise ValueError("params.quarter_ends 必须是对象")
    if tuple(sorted(value)) != tuple(sorted(QUARTER_ORDER)):
        raise ValueError("params.quarter_ends 必须恰好含 Q1–Q4")
    ends = {}
    for quarter in QUARTER_ORDER:
        text = value[quarter]
        if not isinstance(text, str) or len(text) != 5 or text[2] != "-":
            raise ValueError("quarter_ends.%s 必须是 MM-DD" % quarter)
        ends[quarter] = text
    return ends


def resolve_params(params=None) -> Settings:
    """把 subject.params 叠在默认值上；未知键 -> ``ValueError``（退出码 2）。"""
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params 必须是 JSON 对象")
    resolved = {
        "mode": DEFAULT_SETTINGS.mode,
        "threshold": DEFAULT_SETTINGS.threshold,
        "disclosure_count": DEFAULT_SETTINGS.disclosure_count,
        "quarter_ends": dict(DEFAULT_SETTINGS.quarter_ends),
    }
    if params:
        unknown = sorted(set(params) - set(_PARAM_KEYS))
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        for key in _PARAM_KEYS:
            if key in params:
                resolved[key] = params[key]
    return Settings(
        mode=_coerce_mode(resolved["mode"]),
        threshold=_coerce_threshold(resolved["threshold"]),
        disclosure_count=_coerce_count(resolved["disclosure_count"]),
        quarter_ends=_coerce_quarter_ends(resolved["quarter_ends"]),
    )