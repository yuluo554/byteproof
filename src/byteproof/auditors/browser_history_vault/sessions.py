"""会话切分（照搬旧仓 ``sessions.py``：模块③④共用的唯一生产实现）。

口径（照搬）：按 ``(source_browser, source_profile)`` 分组；组内按
``(visit_time_us, url)`` 升序（次键与存储过程无关）；相邻间隔**严格大于**
``gap_minutes`` 才切分（恰好等于不切）；会话按 ``(start_us, source, profile)``
排序后从 1 编 ``session_id``。每条 step 携带 ``visit_id`` 供下钻。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .timeutil import US_PER_MINUTE

SESSION_STEP_SORT_FIELDS: Tuple[str, ...] = ("visit_time_us", "url")

SESSION_SPLIT_RULE = "相邻间隔严格大于配置间隔才切分（恰好等于不切分）；按来源分组"

_REQUIRED_FIELDS: Tuple[str, ...] = (
    "visit_id",
    "url",
    "visit_time_us",
    "source_browser",
    "source_profile",
)


class SessionError(ValueError):
    """会话切分的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""


@dataclass(frozen=True)
class SessionStep:
    visit_id: int
    url: str
    visit_time_us: int
    source_browser: str
    source_profile: str


@dataclass(frozen=True)
class Session:
    session_id: int
    source_browser: str
    source_profile: str
    steps: Tuple[SessionStep, ...]

    @property
    def size(self) -> int:
        return len(self.steps)

    @property
    def start_us(self) -> int:
        return self.steps[0].visit_time_us

    @property
    def end_us(self) -> int:
        return self.steps[-1].visit_time_us

    @property
    def span_us(self) -> int:
        return self.end_us - self.start_us

    def visit_ids(self) -> Tuple[int, ...]:
        return tuple(step.visit_id for step in self.steps)

    def urls(self) -> Tuple[str, ...]:
        return tuple(step.url for step in self.steps)


def _coerce_step(row: Dict[str, Any]) -> SessionStep:
    missing = [field for field in _REQUIRED_FIELDS if field not in row]
    if missing:
        raise SessionError(
            "row-shape",
            "会话切分需要可下钻的行（缺 %s）：会话序号与引用都要能落到具体 visit 上" % ", ".join(missing),
        )
    return SessionStep(
        visit_id=int(row["visit_id"]),
        url=str(row["url"]),
        visit_time_us=int(row["visit_time_us"]),
        source_browser=str(row["source_browser"]),
        source_profile=str(row["source_profile"]),
    )


def split_sessions(rows: Iterable[Dict[str, Any]], gap_minutes: int) -> Tuple[Session, ...]:
    """按来源分组切分会话；返回按 ``(start_us, source, profile)`` 排序、id 从 1 起的元组。"""
    gap = int(gap_minutes)
    if gap < 1:
        raise SessionError("gap-range", "会话间隔必须是正整数分钟，实际是 %r" % (gap_minutes,))
    gap_us = gap * US_PER_MINUTE

    grouped: Dict[Tuple[str, str], list] = {}
    for row in rows:
        step = _coerce_step(row)
        grouped.setdefault((step.source_browser, step.source_profile), []).append(step)

    collected: list = []
    for source_key in sorted(grouped):
        ordered = sorted(
            grouped[source_key],
            key=lambda step: tuple(getattr(step, field) for field in SESSION_STEP_SORT_FIELDS),
        )
        current: list = []
        previous_us: Optional[int] = None
        for step in ordered:
            if previous_us is not None and step.visit_time_us - previous_us > gap_us:
                collected.append((source_key, tuple(current)))
                current = []
            current.append(step)
            previous_us = step.visit_time_us
        if current:
            collected.append((source_key, tuple(current)))

    collected.sort(key=lambda item: (item[1][0].visit_time_us, item[0][0], item[0][1]))
    return tuple(
        Session(session_id=index, source_browser=source_key[0], source_profile=source_key[1], steps=steps)
        for index, (source_key, steps) in enumerate(collected, 1)
    )


def sessions_containing(sessions: Sequence[Session], urls: Sequence[str]) -> Tuple[Session, ...]:
    """含给定任一 url 的会话（按 session_id 升序）——真值用 url 定位，不用实现产物定位。"""
    wanted = set(urls)
    return tuple(session for session in sessions if wanted.intersection(session.urls()))


def size_histogram(sessions: Sequence[Session]) -> Dict[str, int]:
    """会话长度分布（键是字符串化的长度，便于确定性 JSON 序列化）。"""
    counts: Dict[str, int] = {}
    for session in sessions:
        key = str(session.size)
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts, key=int)}


def step_urls(session: Session) -> Tuple[str, ...]:
    return session.urls()


def session_size_sequence(sessions: Sequence[Session]) -> Tuple[int, ...]:
    """各会话长度的序列（真值对撞用：期望是**排序后**的）。"""
    return tuple(sorted(session.size for session in sessions))
