"""报告期与披露窗口（旧仓 ``funddiff/window.py`` 的判定子集）。

纪律原样保留：

- **不读系统时钟**：``as_of`` 只能由 subject 提供；缺省即「以最新已发送为准」，
  不拿今天去推断；
- 披露三态严格区分：已披露 / 待披露 / 无数据；
- 截止日 = 季度结束次日起算的第 N 个工作日（周末与法定节假日不计，调休上班日计入）；
  所需年份日历未登记 -> ``deadline=None`` + ``unverified``，**禁止近似冒充**。

窗口边界来自 subject：``quarter_ends``（季末月日）与 ``disclosure``（规则 + 日历）。
"""

from __future__ import annotations

import datetime
import re

from .spec import (
    DEFAULT_QUARTER_ENDS,
    DISCLOSED,
    NO_DATA,
    PENDING,
    QUARTER_ORDER,
)

MAX_SPAN_DAYS = 366

_PERIOD_RE = re.compile(r"^(\d{4})(Q[1-4])$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class WindowError(ValueError):
    """报告期 / 日期非法（输入不合法，退出码 2）。"""


def parse_period(period):
    """校验 ``YYYYQn``；返回 (year:int, quarter:str)，非法抛 WindowError。"""
    if not isinstance(period, str):
        raise WindowError("报告期必须是 YYYYQn，得到 %r" % (period,))
    match = _PERIOD_RE.match(period)
    if not match:
        raise WindowError("报告期必须是 YYYYQn，得到 %r" % (period,))
    return int(match.group(1)), match.group(2)


def parse_date(value):
    """校验 ISO 日期 ``YYYY-MM-DD``；返回 ``datetime.date``，非法抛 WindowError。"""
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        raise WindowError("日期必须是 YYYY-MM-DD，得到 %r" % (value,))
    match = _DATE_RE.match(value)
    if not match:
        raise WindowError("日期必须是 YYYY-MM-DD，得到 %r" % (value,))
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError as exc:
        raise WindowError("日期非法：%r（%s）" % (value, exc))


def quarter_end(quarter_ends, year, quarter):
    text = quarter_ends[quarter]
    month, day = int(text[0:2]), int(text[3:5])
    try:
        return datetime.date(year, month, day)
    except ValueError as exc:
        raise WindowError("quarter_ends.%s 非法：%s" % (quarter, exc))


def period_end_of(quarter_ends, period):
    year, quarter = parse_period(period)
    return quarter_end(quarter_ends, year, quarter)


def previous_period(period):
    year, quarter = parse_period(period)
    index = QUARTER_ORDER.index(quarter)
    if index == 0:
        return "%dQ4" % (year - 1)
    return "%d%s" % (year, QUARTER_ORDER[index - 1])


def window_bounds(quarter_ends, period):
    """报告期起止：本期季末的前一季季末次日起，至本期季末。"""
    end = period_end_of(quarter_ends, period)
    prev_end = period_end_of(quarter_ends, previous_period(period))
    return (prev_end + datetime.timedelta(days=1), end)


def _is_workday(entry, day):
    text = day.isoformat()
    if text in entry.get("makeup_workdays", []):
        return True
    if text in entry.get("holidays", []):
        return False
    return day.weekday() < 5


def _deadline(period_end, count, calendar):
    day = period_end + datetime.timedelta(days=1)
    remaining = count
    used_years = []
    while remaining > 0:
        year_key = "%04d" % day.year
        entry = calendar.get(year_key)
        if entry is None:
            return None, True, "calendar_missing:%s" % year_key, used_years
        if year_key not in used_years:
            used_years.append(year_key)
        if _is_workday(entry, day):
            remaining -= 1
            if remaining == 0:
                return day.isoformat(), False, None, used_years
        day += datetime.timedelta(days=1)
        if (day - period_end).days > MAX_SPAN_DAYS:
            return None, True, "deadline_out_of_range", used_years
    raise AssertionError("unreachable")


def window_for_period(period, quarter_ends=None, disclosure=None):
    """一个报告期的窗口：起止 + 披露截止日 + 是否可验证。"""
    quarter_ends = quarter_ends or DEFAULT_QUARTER_ENDS
    disclosure = disclosure or {}
    rule = disclosure.get("rule") or {}
    kind = rule.get("kind", "workdays_after_period_end")
    if kind != "workdays_after_period_end":
        raise WindowError("disclosure.rule.kind 只支持 workdays_after_period_end，得到 %r" % (kind,))
    count = rule.get("count", 15)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise WindowError("disclosure.rule.count 必须是正整数，得到 %r" % (count,))
    calendar = disclosure.get("calendar")
    if calendar is None:
        calendar = {}
    if not isinstance(calendar, dict):
        raise WindowError("disclosure.calendar 必须是对象")

    start, end = window_bounds(quarter_ends, period)
    deadline, unverified, reason, years = _deadline(end, count, calendar)
    return {
        "report_period": period,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "disclosure_deadline": deadline,
        "unverified": unverified,
        "unverified_reason": reason,
        "deadline_rule": kind,
        "deadline_count": count,
        "calendar_years": years,
    }


def disclosure_status(reports_available, reports, fund_code, period, as_of=None):
    """三态判定。

    ``reports_available=False`` -> 无数据（不得与待披露合并）。
    ``as_of`` 给出时按历史时点回放：只有 ``report_send_date <= as_of`` 才算已披露；
    发送日缺失或非法不能证明当时已披露，按待披露处理。
    """
    if not reports_available:
        return NO_DATA
    cutoff = parse_date(as_of) if as_of is not None else None
    for report in reports or []:
        if not isinstance(report, dict):
            continue
        if report.get("fundcode") != fund_code or report.get("report_period") != period:
            continue
        if cutoff is None:
            return DISCLOSED
        try:
            sent = parse_date(report.get("report_send_date"))
        except WindowError:
            continue
        if sent <= cutoff:
            return DISCLOSED
    return PENDING


def period_for_date(quarter_ends, day):
    """该日期所属的（最近一个已结束的）报告期。``day`` 必须是 ``datetime.date``。"""
    for quarter in reversed(QUARTER_ORDER):
        end = quarter_end(quarter_ends, day.year, quarter)
        if day >= end:
            return "%d%s" % (day.year, quarter)
    return "%dQ4" % (day.year - 1)