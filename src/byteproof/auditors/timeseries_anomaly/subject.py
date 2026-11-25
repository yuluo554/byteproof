"""工件（subject）解析：JSON 长表 -> 每条序列的 ``(row_no, epoch_ms, value)``。

旧仓的工件是一份 CSV；本器官的工件是**同一张表解析后的 JSON**，所以这里搬的是
``csvio.load_series`` 的**行级契约**，不搬 CSV 文本读写（器官不读文件）：

::

    {
      "rows": [
        {"timestamp": "2024-03-01T00:00:00Z", "series_id": "temperature", "value": 12.4},
        {"timestamp": "2024-03-01T00:05:00Z", "series_id": "temperature", "value": null}
      ],
      "params": { ... 可选，旧仓 run-spec 的同名字段 ... }
    }

三条口径与旧仓一致，理由是它们决定"什么算缺失、什么算损坏"：

* ``value`` 为 ``null``（或 ``""`` / ``NA`` / ``NaN`` / ``null`` / ``none`` / ``-`` / ``--``）
  是**缺失**，不是错误 —— 缺失是数据，喂给段规则与剖面；
* 数值必须是有限十进制数（``inf`` / ``nan`` 拼写一律拒绝），因为一个 NaN 会静默毒化
  其后每一个区间与分数；
* ``series_id`` 缺省或为空 -> ``params.default_series_id``；同一 ``series_id`` 的行
  保持**输入顺序**，因为"时间倒序"正是要审的东西。

行号 = 该行在 ``rows`` 里的 1 基下标（工件自己的位置，不是某个外部 CSV 的物理行号）。
它出现在账本 ``path`` 与 ``evidence`` 里，是这条缺陷可以被指回去的唯一坐标。

**信封错误 vs 工件缺陷**：``rows`` 不是数组、行不是对象、``timestamp`` 键缺失
-> ``SubjectError``（``ValueError`` 子类 -> 宿主退出码 2，"输入不合法"）；
时间戳读不出来、值不是有限数 -> 一条 ``error`` 账本（工件缺陷，退出码 1）。
这条分界线是本器官对 byteproof 口径的落地，写进 ``docs/timeseries-anomaly.md``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import rules
from .timeline import TimeParseError, parse_timestamp

#: 缺失标记（与旧仓 ``csvio.MISSING_TOKENS`` 逐字一致）。
MISSING_TOKENS = frozenset(("", "na", "n/a", "nan", "null", "none", "-", "--"))

#: 有限十进制数：不认下划线/十六进制/``inf``/``nan``/千分位 —— 每种语言都写得出的那一种。
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


class SubjectError(ValueError):
    """信封结构不合法（退出码 2）。不是工件缺陷。"""


@dataclass(frozen=True)
class Issue:
    """行级工件缺陷：一条已知位置的、可落账的问题。"""

    rule_id: str
    row_no: int
    series_id: str
    detail: str


@dataclass
class Parsed:
    """解析结果：按序列归好的行 + 行级缺陷 + 计数。

    ``rows_by_series[series_id]`` 是 ``[(row_no, epoch_ms, value_or_none)]``，
    保持输入顺序。``quality`` 只有整数，直接进证据。
    """

    rows_by_series: Dict[str, List[Tuple[int, int, Optional[float]]]] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    n_rows: int = 0
    n_values_present: int = 0
    n_values_missing: int = 0

    @property
    def series_order(self) -> List[str]:
        return sorted(self.rows_by_series)


def parse_value(cell, row_no):
    """把一个 ``value`` 单元格读成 float 或 ``None``；非有限数抛 :class:`Issue` 的 detail。"""
    if cell is None:
        return None
    if isinstance(cell, bool):
        raise ValueError("value 是布尔值 %r" % (cell,))
    if isinstance(cell, str):
        stripped = cell.strip()
        if stripped.lower() in MISSING_TOKENS:
            return None
        if not _NUMBER_RE.match(stripped):
            raise ValueError("value 不是有限十进制数：%r" % (cell,))
        value = float(stripped)
    elif isinstance(cell, (int, float)):
        value = float(cell)
    else:
        raise ValueError("value 类型不支持：%s" % (type(cell).__name__,))
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("value 不是有限十进制数：%r" % (cell,))
    return value


def _series_id_of(row, params, row_no):
    raw = row.get("series_id")
    if raw is None:
        return params["default_series_id"]
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise SubjectError(
            "rows[%d].series_id 必须是字符串或整数，得到 %s" % (row_no, type(raw).__name__)
        )
    text = str(raw).strip()
    if not text:
        return params["default_series_id"]
    return text


def parse_subject(subject, params):
    """解析并校验工件。信封错误抛 :class:`SubjectError`，行级缺陷收进 ``Parsed.issues``。"""
    if not isinstance(subject, dict):
        raise SubjectError("输入必须是 JSON 对象")
    rows = subject.get("rows")
    if not isinstance(rows, list):
        raise SubjectError("rows 必须是数组")
    if not rows:
        raise SubjectError("rows 为空：没有可审的样本")
    offset_default = params["timezone_offset_min"]

    parsed = Parsed()
    for index, row in enumerate(rows):
        row_no = index + 1
        if not isinstance(row, dict):
            raise SubjectError("rows[%d] 必须是对象" % (row_no,))
        if "timestamp" not in row:
            raise SubjectError("rows[%d] 缺必填字段 timestamp" % (row_no,))
        if "value" not in row:
            raise SubjectError("rows[%d] 缺必填字段 value（缺失请显式写 null）" % (row_no,))
        series_id = _series_id_of(row, params, row_no)
        parsed.n_rows += 1

        try:
            stamp = parse_timestamp(row["timestamp"], offset_default)
        except TimeParseError as exc:
            parsed.issues.append(
                Issue(rules.RULE_TIMESTAMP_UNREADABLE, row_no, series_id, "%s" % (exc,))
            )
            continue

        try:
            value = parse_value(row["value"], row_no)
        except ValueError as exc:
            parsed.issues.append(Issue(rules.RULE_VALUE_INVALID, row_no, series_id, "%s" % (exc,)))
            continue

        parsed.rows_by_series.setdefault(series_id, []).append((row_no, stamp.epoch_ms, value))
        if value is None:
            parsed.n_values_missing += 1
        else:
            parsed.n_values_present += 1

    if not parsed.rows_by_series and not parsed.issues:
        raise SubjectError("rows 里没有任何可用样本")
    return parsed