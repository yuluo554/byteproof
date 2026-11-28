"""时间与纪元（照搬旧仓 ``timeutil.py``，全项目唯一时间戳转换点）。

口径三条（照搬）：1601 纪元微秒（Chromium）；全程不读时钟（"现在"由调用方注入）；
时区 = 固定 UTC 偏移（分钟），不引入命名时区。整数运算不走浮点（逐字节一致）。
"""

from __future__ import annotations

import datetime
from typing import Tuple

EPOCH_1601 = datetime.datetime(1601, 1, 1, 0, 0, 0)

US_PER_SECOND = 1000000
US_PER_MINUTE = 60 * US_PER_SECOND
US_PER_HOUR = 60 * US_PER_MINUTE
US_PER_DAY = 24 * US_PER_HOUR

WEEKDAY_STARTS: Tuple[str, ...] = ("monday", "sunday")

_WEEKDAY_NAMES_MONDAY_FIRST = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def datetime_to_us(moment: datetime.datetime) -> int:
    """UTC 朴素 datetime → 1601 纪元微秒（整数运算，不走浮点）。"""
    if moment.tzinfo is not None:
        raise ValueError("本模块只接受**朴素 UTC** datetime（时区口径走固定偏移，不用 tzinfo）")
    delta = moment - EPOCH_1601
    return (delta.days * 86400 + delta.seconds) * US_PER_SECOND + delta.microseconds


def us_to_datetime(us: int) -> datetime.datetime:
    seconds, microseconds = divmod(int(us), US_PER_SECOND)
    days, seconds_of_day = divmod(seconds, 86400)
    return EPOCH_1601 + datetime.timedelta(days=days, seconds=seconds_of_day, microseconds=microseconds)


def local_datetime_of_us(us: int, offset_minutes: int) -> datetime.datetime:
    """纪元微秒 → **口径时区下的本地**朴素 datetime（展示/分桶用）。"""
    return us_to_datetime(us) + datetime.timedelta(minutes=int(offset_minutes))


def local_us_of_datetime(local_moment: datetime.datetime, offset_minutes: int) -> int:
    return datetime_to_us(local_moment - datetime.timedelta(minutes=int(offset_minutes)))


def local_date_of_us(us: int, offset_minutes: int) -> datetime.date:
    """纪元微秒 → 本地日历日期。会话/热力/遗忘判定一律按**本地日历**。"""
    return local_datetime_of_us(us, offset_minutes).date()


def local_day_start_us(day: datetime.date, offset_minutes: int) -> int:
    start = datetime.datetime(day.year, day.month, day.day, 0, 0, 0)
    return local_us_of_datetime(start, offset_minutes)


def local_hour_of_us(us: int, offset_minutes: int) -> int:
    return local_datetime_of_us(us, offset_minutes).hour


def resolve_weekday_start(weekday_start: str) -> str:
    """校验并规范化「星期起算日」取值（大小写不敏感）。"""
    if not isinstance(weekday_start, str):
        raise ValueError("weekday_start 必须是字符串")
    normalized = weekday_start.strip().lower()
    if normalized not in WEEKDAY_STARTS:
        raise ValueError(
            "weekday_start 必须是 %s 之一，实际是 %r" % (" / ".join(WEEKDAY_STARTS), weekday_start)
        )
    return normalized


def local_weekday_index(us: int, offset_minutes: int, weekday_start: str) -> int:
    """本地星期序号 0..6：0 = 配置里的起算日。分桶结果随起算日整体平移。"""
    start = resolve_weekday_start(weekday_start)
    python_weekday = local_datetime_of_us(us, offset_minutes).weekday()  # 0=Mon .. 6=Sun
    if start == "monday":
        return python_weekday
    return (python_weekday + 1) % 7


def weekday_names(weekday_start: str) -> Tuple[str, ...]:
    """索引 → 星期简称（索引 0 对应起算日）。"""
    start = resolve_weekday_start(weekday_start)
    shift = 0 if start == "monday" else 6  # sunday 起算时，索引 0 是 Sun
    return tuple(_WEEKDAY_NAMES_MONDAY_FIRST[(i + shift) % 7] for i in range(7))
