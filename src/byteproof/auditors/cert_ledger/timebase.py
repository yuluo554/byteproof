"""``--as-of``：整个器官唯一的「现在」，没有缺省值。

旧仓的 K2 在这里照搬：不读墙钟、不读环境变量；调用方必须给 Unix 秒或带时区的
ISO-8601。``raw`` 保留调用方原样拼写（账本回显），``seconds`` 是所有比较用的整数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_EPOCH_RE = re.compile(r"^-?\d+$")
STAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class AsOf:
    raw: str
    seconds: int

    @property
    def iso(self) -> str:
        return format_utc(self.seconds)


def format_utc(seconds: int) -> str:
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return moment.strftime(STAMP_FORMAT)


def parse_as_of(raw):
    """Unix 秒或带时区的 ISO-8601；无时区/无法解析 -> ``ValueError``（退出码 2）。"""
    if raw is None or not str(raw).strip():
        raise ValueError("as_of 必填：没有「当前时间」缺省值")
    text = str(raw).strip()

    if _EPOCH_RE.match(text):
        return AsOf(raw=str(raw), seconds=int(text))

    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        moment = datetime.fromisoformat(candidate)
    except ValueError:
        raise ValueError(
            "as_of 无法解析：期望 Unix 秒或 ISO-8601（如 1900000000 或 2030-03-17T17:46:40Z），收到 %r"
            % (text,)
        ) from None

    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(
            "as_of 缺少时区：%r 没有偏移，请写成 2030-03-17T17:46:40Z 或带 +00:00 的形式" % (text,)
        )
    return AsOf(raw=str(raw), seconds=int(moment.timestamp()))


def add_days(seconds: int, days: int) -> int:
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc) + timedelta(days=days)
    return int(moment.timestamp())


def format_stamp(seconds: int) -> str:
    return format_utc(seconds)


def parse_stamp(text):
    """台账时间戳 -> 秒；不是 ``YYYY-MM-DDTHH:MM:SSZ`` 就返回 ``None``（不中止整轮）。"""
    if not text:
        return None
    try:
        moment = datetime.strptime(str(text), STAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return int(moment.timestamp())