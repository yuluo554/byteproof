"""基金经理变更四类判定（旧仓 ``funddiff/managers.py`` 的判定子集）。

原样保留的口径：

- 四类：``in_period`` / ``prior_period`` / ``none`` / ``unparsed``；
- 区间由报告期季末推导（不读系统时钟、不写死日期）；
- ``unparsed`` 必须附页面快照（raw_text + sha256），与「无变更」分开；
- 台账标签必须能由区间**反向复算**出同一个值，漂移即内部一致性错误。

**没有搬**：``jjjl`` HTML 解析（``<table>`` / ``<h4>`` 提取）、页面抓取、产物渲染。
输入是**已解析**的经理记录（旧仓 ``events.managers`` 的形状），解析属于工具面。
"""

from __future__ import annotations

import datetime
import hashlib
import re

from .spec import CLASS_IN_PERIOD, CLASS_NONE, CLASS_PRIOR_PERIOD, CLASS_UNPARSED
from .window import window_bounds

_VALID_CLASSES = (CLASS_IN_PERIOD, CLASS_PRIOR_PERIOD, CLASS_NONE, CLASS_UNPARSED)

_DATE_RE = re.compile(r"^(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*日?$")


def normalize_date(value):
    """常见日期格式 -> ISO；无法识别返回 None（调用方决定 unparsed）。"""
    if isinstance(value, datetime.date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value.strip())
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def classify_change(change_date, period, quarter_ends):
    """按报告期区间分类；区间外返回 None（与当前报告无关）。

    ``change_date`` 必须是 ISO 或可识别日期；非法抛 ValueError（调用方先 normalize）。
    """
    day = normalize_date(change_date)
    if day is None:
        raise ValueError("非法变更日期 %r" % (change_date,))
    from .window import previous_period

    start, end = window_bounds(quarter_ends, period)
    prev_start, prev_end = window_bounds(quarter_ends, previous_period(period))
    if start.isoformat() <= day <= end.isoformat():
        return CLASS_IN_PERIOD
    if prev_start.isoformat() <= day <= prev_end.isoformat():
        return CLASS_PRIOR_PERIOD
    return None


def snapshot(raw_text):
    """页面快照证据：原文 + 自身 SHA256（留证，不猜）。"""
    text = raw_text or ""
    return {
        "kind": "page_text",
        "raw_text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def is_unparsed(record):
    """台账明确标了 unparsed，或自称在窗口内却给不出可识别日期。"""
    change_class = record.get("change_class")
    if change_class == CLASS_UNPARSED:
        return True
    if change_class in (CLASS_IN_PERIOD, CLASS_PRIOR_PERIOD):
        return normalize_date(record.get("change_date")) is None
    return False


def label_drift(record, period, quarter_ends):
    """台账标签与区间重算不一致（含 none 用于单条记录、缺 change_date）。"""
    change_class = record.get("change_class")
    if change_class is None:
        day = normalize_date(record.get("change_date"))
        if day is None:
            return "change_class 缺失且日期不可解析"
        computed = classify_change(day, period, quarter_ends)
        if computed is None:
            return "change_class 缺失且日期不在本/上报告期"
        return None
    if change_class not in _VALID_CLASSES:
        return "未知经理变更分类 %r" % (change_class,)
    if change_class == CLASS_NONE:
        return "单条记录不应使用 none（无变更用空列表表达）"
    if change_class == CLASS_UNPARSED:
        return None
    day = normalize_date(record.get("change_date"))
    if day is None:
        return "缺少可解析的 change_date"
    computed = classify_change(day, period, quarter_ends)
    if computed != change_class:
        return "change_class=%r 与配置区间重算=%r 不一致" % (change_class, computed)
    return None


def summarize(records):
    summary = {name: 0 for name in _VALID_CLASSES}
    if not records:
        summary[CLASS_NONE] = 1
    for record in records:
        summary[record["change_class"]] = summary[record["change_class"]] + 1
    return summary


def sort_records(records):
    """确定性排序：change_date 升序（null 最后）→ 分类 → 姓名。"""

    def key(record):
        change_date = record.get("change_date")
        if change_date is None:
            return (1, "", record.get("change_class") or "", record.get("name") or "")
        return (0, change_date, record.get("change_class") or "", record.get("name") or "")

    return sorted(records, key=key)