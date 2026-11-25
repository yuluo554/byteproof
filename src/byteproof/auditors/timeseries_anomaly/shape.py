"""数据形状规则：采样间隔、断档、重复时间戳、时间倒序（旧仓 ``profile.py`` 的规则段）。

旧仓把这张卡片写成 ``profile.json``（一份人读的报告）；本器官把它写成**账本条目** ——
同一批规则，换宿主。搬过来的判定一条没改：

* 主间隔 = 最常见的正间隔，并列取最短；
* 断档 = 某个间隔大于 ``gap_factor`` × 主间隔；
* 重复时间戳 / 时间倒序按**每条序列各自的容差**（``duplicate_timestamp_max`` /
  ``non_monotonic_max``）判，超出容差的那几行才落账 —— 上界内的重复是合法输入；
* 采样不规则 = 间隔里不是主间隔的比例（ppm），它是**比率**，不判断好坏。

``list``/``dict`` 的迭代顺序一律不参与输出：所有结果都按 ``(row_no / epoch_ms)`` 排序后再用。
"""

from __future__ import annotations


def intervals(rows):
    """相邻样本的有效间隔 ``[(prev_row_no, row_no, delta_ms)]``（严格递增的那些）。"""
    found = []
    for index in range(1, len(rows)):
        delta = rows[index][1] - rows[index - 1][1]
        if delta > 0:
            found.append((rows[index - 1][0], rows[index][0], delta))
    return found


def backwards_steps(rows):
    """时间倒序的位置 ``[(row_no, prev_row_no, delta_ms)]``（delta < 0）。"""
    found = []
    for index in range(1, len(rows)):
        delta = rows[index][1] - rows[index - 1][1]
        if delta < 0:
            found.append((rows[index][0], rows[index - 1][0], delta))
    return found


def dominant_interval(intervals_found):
    """主采样间隔；没有正间隔时为 ``None``。平局取最短（顺序确定）。"""
    counts = {}
    for _prev_row, _row, delta in intervals_found:
        counts[delta] = counts.get(delta, 0) + 1
    if not counts:
        return None
    return sorted(counts, key=lambda delta: (-counts[delta], delta))[0]


def distribution(intervals_found):
    """间隔分布 ``[{interval_ms, count}]``，按间隔升序。"""
    counts = {}
    for _prev_row, _row, delta in intervals_found:
        counts[delta] = counts.get(delta, 0) + 1
    return [
        {"interval_ms": delta, "count": counts[delta]} for delta in sorted(counts)
    ]


def gaps(rows, intervals_found, dominant, gap_factor):
    """超出 ``gap_factor × 主间隔`` 的断档；每条带"缺了几个点"。"""
    if dominant is None:
        return []
    threshold = dominant * gap_factor
    stamp_by_row = {row[0]: row[1] for row in rows}
    found = []
    for prev_row, row_no, delta in intervals_found:
        if delta > threshold:
            found.append(
                {
                    "prev_ms": stamp_by_row[prev_row],
                    "ms": stamp_by_row[row_no],
                    "prev_row": prev_row,
                    "row_no": row_no,
                    "interval_ms": delta,
                    "missing_points": delta // dominant - 1,
                }
            )
    return found


def duplicate_timestamps(rows):
    """每一条被重复使用的时间戳 ``[{epoch_ms, row_nos}]``，``row_nos`` 升序。"""
    seen = {}
    for row_no, epoch_ms, _value in rows:
        seen.setdefault(epoch_ms, []).append(row_no)
    return [
        {"epoch_ms": epoch_ms, "row_nos": sorted(row_nos), "extra_rows": len(row_nos) - 1}
        for epoch_ms, row_nos in sorted(seen.items())
        if len(row_nos) > 1
    ]


def cadence_summary(rows, gap_factor):
    """一条序列的采样间隔摘要（只有整数），直接进证据。"""
    found = intervals(rows)
    dominant = dominant_interval(found)
    ordered = sorted(delta for _p, _r, delta in found)
    counts = {}
    for _p, _r, delta in found:
        counts[delta] = counts.get(delta, 0) + 1
    irregular_count = len(found) - counts.get(dominant, 0) if dominant is not None else 0
    irregular_ppm = 0
    if found:
        irregular_ppm = (irregular_count * 1000000 + len(found) // 2) // len(found)
    return {
        "n_intervals": len(found),
        "dominant_interval_ms": dominant,
        "median_interval_ms": ordered[(len(ordered) - 1) // 2] if ordered else None,
        "min_interval_ms": ordered[0] if ordered else None,
        "max_interval_ms": ordered[-1] if ordered else None,
        "gap_threshold_ms": dominant * gap_factor if dominant is not None else None,
        "irregular_count": irregular_count,
        "irregular_ratio_ppm": irregular_ppm,
    }


def value_counts(rows):
    """值形状计数：缺失 / 零 / 负 / 正。"""
    n_missing = 0
    n_zero = 0
    n_negative = 0
    n_positive = 0
    for _row_no, _epoch_ms, value in rows:
        if value is None:
            n_missing += 1
        elif value == 0.0:
            # `-0.0 == 0.0` 也成立：带符号零仍然是一个零值样本。
            n_zero += 1
        elif value < 0:
            n_negative += 1
        else:
            n_positive += 1
    return {
        "n_values_present": len(rows) - n_missing,
        "n_values_missing": n_missing,
        "n_values_zero": n_zero,
        "n_values_negative": n_negative,
        "n_values_positive": n_positive,
    }