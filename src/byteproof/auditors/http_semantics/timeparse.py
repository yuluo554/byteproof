"""Time parsing（1:1 移植自旧仓 ``judgement/timeparse.py``，data/README.md §4.4）。

Exactly two forms are accepted, and both resolve to whole UTC seconds:

* ``YYYY-MM-DDTHH:MM:SSZ`` —— 可选小数秒，**截断**（不四舍五入）；
* IMF-fixdate ``Day, DD Mon YYYY HH:MM:SS GMT`` —— 星期必须与日期一致。

不读时钟、locale 或时区库：epoch 秒来自 civil-date 公式，星期来自天数计数，
所以本模块是其输入字符串的纯函数。只依赖 ``re``（纯度：判定层禁
``time`` / ``datetime`` / ``calendar``）。

不是两种形态之一的值是 caller mistake：抛 ``INVALID_TIME_FORMAT`` 而不是修复。
没有"回落到当前时间"——猜"大概是现在"会让输出依赖跑它的机器。
"""

from __future__ import annotations

import re

from .errors import invalid_time_format

__all__ = ["parse_time", "ISO_FORM", "HTTP_DATE_FORM"]

_SECONDS_PER_DAY = 86400

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?Z$")

_HTTP_DATE = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d{2}) "
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(\d{4}) (\d{2}):(\d{2}):(\d{2}) GMT$"
)

_MONTH_NUMBERS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}

_MONTH_LENGTHS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

# 1970-01-01 was a Thursday, which fixes this table's rotation.
_WEEKDAY_NAMES = ("Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed")

ISO_FORM = "iso8601"
HTTP_DATE_FORM = "http-date"


def _is_leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _month_length(year, month):
    if month == 2 and _is_leap(year):
        return 29
    return _MONTH_LENGTHS[month - 1]


def _days_from_civil(year, month, day):
    """Whole days from 1970-01-01 for a proleptic Gregorian date.

    Howard Hinnant's ``days_from_civil``：把年份移位到三月起算再数 400 年纪元。
    写出来而不是从 ``datetime`` 推导，因为判定层不许 import 它。
    """
    year -= 1 if month <= 2 else 0
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def _fields_are_valid(year, month, day, hour, minute, second):
    if not 1 <= month <= 12:
        return False
    if not 1 <= day <= _month_length(year, month):
        return False
    # Leap seconds (``:60``) are tolerated and folded onto the last second of
    # the minute below; everything else must be a real clock reading.
    return 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 60


def _weekday_name(day_count):
    return _WEEKDAY_NAMES[day_count % 7]


def parse_time(value, field):
    """Return ``(form, timestamp)`` or raise ``INVALID_TIME_FORMAT``。

    ``field`` names the offending input so the error payload can point at it.
    """
    if not isinstance(value, str):
        raise invalid_time_format(field, value)

    iso = _ISO.match(value)
    if iso is not None:
        year, month, day, hour, minute, second = [int(part) for part in iso.groups()[:6]]
        if not _fields_are_valid(year, month, day, hour, minute, second):
            raise invalid_time_format(field, value)
        days = _days_from_civil(year, month, day)
        # Fractional seconds are dropped, not rounded: 00:00:00.999Z is still
        # second 1767225600, the same instant as 00:00:00Z.
        return ISO_FORM, days * _SECONDS_PER_DAY + hour * 3600 + minute * 60 + min(second, 59)

    http = _HTTP_DATE.match(value)
    if http is not None:
        weekday, day, month_name, year, hour, minute, second = http.groups()
        day, year, hour, minute, second = int(day), int(year), int(hour), int(minute), int(second)
        month = _MONTH_NUMBERS[month_name]
        if not _fields_are_valid(year, month, day, hour, minute, second):
            raise invalid_time_format(field, value)
        days = _days_from_civil(year, month, day)
        epoch = days * _SECONDS_PER_DAY + hour * 3600 + minute * 60 + min(second, 59)
        if _weekday_name(days) != weekday:
            raise invalid_time_format(field, value)
        return HTTP_DATE_FORM, epoch

    raise invalid_time_format(field, value)
