"""规模变动的六字段校验（旧仓 ``funddiff/scale.py`` 的判定子集）。

原样保留的口径：

- 六字段：报告期 / 期间申购 / 期间赎回 / 期末份额 / 期末净资产 / 份额变动率；
- **单位一律读表头原样记录**，代码不做换算；
- **K3**：缺失是 ``null``，真实 0 是 ``"0.00"``，二者必须可区分；
- ``baseline=no_prev_baseline`` 时流量字段必须为 ``null``（不得补 0）。

**没有搬**：``gmbd`` HTML / apidata 解析、页面抓取、产物渲染。
输入是**已解析**的规模对象（旧仓 ``events.scale`` 的形状）。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .spec import BASELINE_AVAILABLE, BASELINE_NO_PREV, BASELINES

SCALE_KEYS = (
    "report_period",
    "subscribe",
    "redeem",
    "shares",
    "net_assets",
    "share_change_rate",
    "baseline",
    "units_from_header",
    "source",
)
FLOW_KEYS = ("subscribe", "redeem", "share_change_rate")
NUMBER_KEYS = ("subscribe", "redeem", "shares", "net_assets")
UNIT_RULE = {"subscribe": "申购单位", "net_assets": "净资产单位"}
SOURCE = "gmbd"

_RATE_RE = re.compile(r"^-?\d+(\.\d+)?%$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def missing_fields(scale):
    if not isinstance(scale, dict):
        return tuple(SCALE_KEYS)
    return tuple(key for key in SCALE_KEYS if key not in scale)


def bad_baseline(scale):
    baseline = scale.get("baseline")
    if baseline not in BASELINES:
        return "未知 baseline %r" % (baseline,)
    return None


def unit_problem(scale):
    units = scale.get("units_from_header")
    if not isinstance(units, dict):
        return "units_from_header 必须是对象"
    for key, label in UNIT_RULE.items():
        if not units.get(key):
            return "units_from_header 缺少 %s（%s）" % (key, label)
    return None


def number_problem(scale):
    for key in NUMBER_KEYS:
        value = scale.get(key)
        if value is None:
            continue
        try:
            Decimal(str(value))
        except (InvalidOperation, ValueError):
            return "%s 不是十进制数值：%r" % (key, value)
    return None


def rate_problem(scale):
    rate = scale.get("share_change_rate")
    if rate is None:
        return None
    if not _RATE_RE.match(str(rate)):
        return "share_change_rate 格式非法：%r" % (rate,)
    return None


def baseline_flow_problem(scale):
    """返回 (字段, 说明)；无问题返回 (None, None)。"""
    if scale.get("baseline") != BASELINE_NO_PREV:
        return None, None
    for key in FLOW_KEYS:
        if scale.get(key) is not None:
            return key, "baseline=no_prev_baseline 时 %s 必须为 null，不得补 0 或填入数值" % (key,)
    return None, None


def source_problem(scale):
    if scale.get("source") != SOURCE:
        return "scale.source 必须是 gmbd，实际 %r" % (scale.get("source"),)
    raw_sha = scale.get("raw_sha256")
    if raw_sha is not None and not _SHA_RE.match(str(raw_sha)):
        return "scale.raw_sha256 必须是 64 位小写十六进制"
    return None


def is_zero_flow(scale):
    """真实零申赎：baseline 可用且申购、赎回都恰为 0（不是 null）。"""
    if scale.get("baseline") != BASELINE_AVAILABLE:
        return False
    subscribe = scale.get("subscribe")
    redeem = scale.get("redeem")
    if subscribe is None or redeem is None:
        return False
    return Decimal(str(subscribe)) == 0 and Decimal(str(redeem)) == 0