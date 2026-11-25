"""整数时间基：civil <-> epoch 毫秒，全程整数运算（旧仓 ``anomaly_atlas/timebase.py``）。

搬过来的理由：账本里的位置与时长必须是**可复算的整数**。``datetime.fromisoformat``
会带入本机时区库与平台差异，这里一律显式算，并用 Hinnant 的 civil 算法。

接受的语法（``[ T]`` 分隔符必需）：::

    YYYY-MM-DD[T ]HH:MM[:SS[.f{1,9}]][Z | +HH:MM | +HHMM | +HH]

语义：
  * 尾部 ``Z`` 或数字偏移是**显式** UTC 偏移（分钟，东为正）；
  * 无偏移 = 该值属于声明时区，用 ``default_tz_offset_min``（0 = UTC）解释，
    并回报实际使用的偏移（证据里能说清"这个时间是怎么读出来的"）；
  * 亚秒位截断（不是四舍五入）到毫秒，不让 float 碰到时间戳；
  * 不存在的民用日期（2024-02-30）直接拒绝，不静默归一化。
"""

from __future__ import annotations

import re
from collections import namedtuple

MS_PER_SECOND = 1000
MS_PER_MINUTE = 60 * MS_PER_SECOND
MS_PER_HOUR = 60 * MS_PER_MINUTE
MS_PER_DAY = 24 * MS_PER_HOUR

#: Hinnant 常量：0000-03-01 到 1970-01-01 的天数。
_EPOCH_SHIFT_DAYS = 719468
_DAYS_PER_ERA = 146097

_ISO_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mo>\d{2})-(?P<d>\d{2})"
    r"[T ](?P<h>\d{2}):(?P<mi>\d{2})"
    r"(?::(?P<s>\d{2})(?:\.(?P<f>\d{1,9}))?)?"
    r"(?P<tz>Z|z|[+-]\d{2}(?::?\d{2})?)?$"
)

_TZ_RE = re.compile(r"^(?P<sign>[+-])(?P<h>\d{2})(?::?(?P<m>\d{2}))?$")


class TimeParseError(ValueError):
    """时间戳不合上面那条语法。

    继承 ``ValueError``：调用方只需要知道"这不是一个时间戳"。宿主 ``cli.main``
    把 ``ValueError`` 映射到退出码 2，但本器官**不**让它冒到那里 ——
    行级时间戳错误是一条 ``error`` 账本（工件缺陷），不是信封缺陷。
    """


ParsedTimestamp = namedtuple("ParsedTimestamp", "epoch_ms offset_min offset_explicit")


def days_from_civil(year, month, day):
    """proleptic Gregorian 日期距 1970-01-01 的天数（Hinnant 整数算法）。"""
    year = int(year)
    month = int(month)
    day = int(day)
    year -= 1 if month <= 2 else 0
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400  # [0, 399]
    doy = (153 * (month - 3 if month > 2 else month + 9) + 2) // 5 + day - 1  # [0, 365]
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy  # [0, 146096]
    return era * _DAYS_PER_ERA + doe - _EPOCH_SHIFT_DAYS


def civil_from_days(days):
    """``days_from_civil`` 的逆：距 epoch 的天数 -> (年, 月, 日)。"""
    z = int(days) + _EPOCH_SHIFT_DAYS
    era = (z if z >= 0 else z - 146096) // _DAYS_PER_ERA
    doe = z - era * _DAYS_PER_ERA  # [0, 146096]
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365  # [0, 399]
    year = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)  # [0, 365]
    mp = (5 * doy + 2) // 153  # [0, 11]
    day = doy - (153 * mp + 2) // 5 + 1  # [1, 31]
    month = mp + (3 if mp < 10 else -9)  # [1, 12]
    return (year + (1 if month <= 2 else 0), month, day)


def is_valid_civil_date(year, month, day):
    """(y, m, d) 在这个历法里真的存在吗。"""
    if not (1 <= month <= 12):
        return False
    if not (1 <= day <= 31):
        return False
    return civil_from_days(days_from_civil(year, month, day)) == (year, month, day)


def epoch_ms_to_civil(ms):
    """UTC epoch 毫秒拆成 (年, 月, 日, 时, 分, 秒, 毫秒)；负数按 floor 分解。"""
    days, rest = divmod(int(ms), MS_PER_DAY)
    year, month, day = civil_from_days(days)
    hour, rest = divmod(rest, MS_PER_HOUR)
    minute, rest = divmod(rest, MS_PER_MINUTE)
    second, milli = divmod(rest, MS_PER_SECOND)
    return (year, month, day, hour, minute, second, milli)


def epoch_ms_to_iso(ms):
    """UTC epoch 毫秒 -> 定宽 ``'YYYY-MM-DDTHH:MM:SS.mmmZ'``（只由整数派生）。"""
    year, month, day, hour, minute, second, milli = epoch_ms_to_civil(ms)
    if year < 0:
        raise ValueError("年份超出 4 位 ISO 范围：%d" % year)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        year,
        month,
        day,
        hour,
        minute,
        second,
        milli,
    )


def _parse_offset(text):
    if text in ("Z", "z"):
        return (0, True)
    match = _TZ_RE.match(text)
    if not match:
        raise TimeParseError("UTC 偏移写法不合法：%r" % (text,))
    hours = int(match.group("h"))
    minutes = int(match.group("m")) if match.group("m") is not None else 0
    if hours > 23 or minutes > 59:
        raise TimeParseError("UTC 偏移越界：%r" % (text,))
    total = hours * 60 + minutes
    if match.group("sign") == "-":
        total = -total
    return (total, True)


def parse_timestamp(text, default_tz_offset_min=0):
    """把一个时间戳字符串解析成 ``ParsedTimestamp``（UTC epoch 毫秒 + 实际偏移）。"""
    if not isinstance(text, str):
        raise TimeParseError("时间戳必须是字符串，得到 %r" % (type(text).__name__,))
    raw = text.strip()
    if not raw:
        raise TimeParseError("时间戳为空")
    match = _ISO_RE.match(raw)
    if not match:
        raise TimeParseError("不是 ISO-8601 时间戳：%r" % (text,))

    year = int(match.group("y"))
    month = int(match.group("mo"))
    day = int(match.group("d"))
    hour = int(match.group("h"))
    minute = int(match.group("mi"))
    second = int(match.group("s")) if match.group("s") is not None else 0
    frac = match.group("f") or ""

    if not is_valid_civil_date(year, month, day):
        raise TimeParseError("这个日期不存在：%r" % (text,))
    if hour > 23:
        raise TimeParseError("小时越界：%r" % (text,))
    if minute > 59:
        raise TimeParseError("分钟越界：%r" % (text,))
    if second > 59:
        # 闰秒在定长 epoch 网格上不可表示；拒绝它，接受域与 stdlib 能确认的一致。
        raise TimeParseError("秒越界：%r" % (text,))

    milli = int((frac + "000")[:3]) if frac else 0

    tz_text = match.group("tz")
    if tz_text is None:
        offset_min = int(default_tz_offset_min)
        explicit = False
    else:
        offset_min, explicit = _parse_offset(tz_text)

    local_ms = (
        days_from_civil(year, month, day) * MS_PER_DAY
        + hour * MS_PER_HOUR
        + minute * MS_PER_MINUTE
        + second * MS_PER_SECOND
        + milli
    )
    return ParsedTimestamp(local_ms - offset_min * MS_PER_MINUTE, offset_min, explicit)


def parse_iso_to_epoch_ms(text, default_tz_offset_min=0):
    """时间戳字符串 -> UTC 整数 epoch 毫秒。"""
    return parse_timestamp(text, default_tz_offset_min).epoch_ms