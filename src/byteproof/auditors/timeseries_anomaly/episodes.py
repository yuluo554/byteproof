"""Episode 合并、严重度排序与编号（旧仓 ``anomaly_atlas/episodes.py``，K6/K7 口径照搬）。

合并发生在**时间域**（``max_gap_ms``）：相邻两个异常点的时间戳相距不超过 ``max_gap_ms``
就并入同一段 episode。按点数距离合并会把两个无关的 episode 跨越数据断档焊在一起 ——
断档的语义是"这里没有样本"，不是"这里什么都没发生"（旧仓 plan/06 D10），
所以合并规则从不看下标。

严重度排序用**定点整数分数**，不用原始 float：两个在第 12 位小数上不同的分数，在
CPython 与 V8 里可能排出不同顺序，那会移动 episode 编号、改变档案指纹 ——
为一个人眼看不见的差异（旧仓 K6/D12）。本器官里同一个理由变成"账本路径必须是确定性的"。

编号按**序列内**计数（``<series_id>-E<NNN>``）：新增一条序列不该重排别的序列的编号。
"""

from __future__ import annotations

from .params import QUANT_DECIMALS, quantize
from .timeline import epoch_ms_to_iso


def severity_key(episode):
    """严重度键，按平局判定顺序排列（旧仓 data/README 4.2）。分量全是整数或字符串，
    元组是**全序**：同一序列内一个检测器对某一行最多标一次，所以两段 episode 不会共享
    ``(peak_score_q, duration_ms, start_row, detector)``。"""
    return (
        -episode["peak_score_q"],
        -episode["duration_ms"],
        episode["start_row"],
        episode["detector"],
    )


def merge_episodes(series_id, detector, points, max_gap_ms, decimals=QUANT_DECIMALS):
    """把一条序列上某个检测器的异常点按时间域分组成 episode。

    ``points`` 是 ``[(epoch_ms, row_no, score)]``，已按时间排序（行号破时间平局）。
    峰值分数存成定点整数，所以严重度键与账本都不带原始 float。
    """
    episodes = []
    current = []
    for point in points:
        if current and point[0] - current[-1][0] > max_gap_ms:
            episodes.append(_finish(series_id, detector, current, decimals))
            current = []
        current.append(point)
    if current:
        episodes.append(_finish(series_id, detector, current, decimals))
    return episodes


def _finish(series_id, detector, points, decimals):
    peak = 0.0
    for point in points:
        if point[2] > peak:
            peak = point[2]
    start_ms = points[0][0]
    end_ms = points[-1][0]
    # 段规则的"分数"就是段长（旧仓口径）；换成整数存进证据，人读时不必再从定点数反推。
    run_length = None
    if detector in ("rules.missing_run", "rules.zero_run"):
        run_length = int(peak)
    return {
        "episode_id": "",
        "series_id": series_id,
        "detector": detector,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "start": epoch_ms_to_iso(start_ms),
        "end": epoch_ms_to_iso(end_ms),
        "duration_ms": end_ms - start_ms,
        "peak_score_q": quantize(peak, decimals),
        "n_points": len(points),
        "start_row": points[0][1],
        "end_row": points[-1][1],
        "run_length": run_length,
    }


def order_episodes(episodes):
    """按严重度键排序：最严重的在前（整数与字符串，可复现）。"""
    return sorted(episodes, key=severity_key)


def assign_ids(episodes):
    """给排好序的 episode 按序列编号：``<series_id>-E<NNN>``，1 起。"""
    seen = {}
    for episode in episodes:
        series_id = episode["series_id"]
        seen[series_id] = seen.get(series_id, 0) + 1
        episode["episode_id"] = "%s-E%03d" % (series_id, seen[series_id])
    return episodes


def build_episodes(rows_by_series, detections, max_gap_ms, decimals=QUANT_DECIMALS):
    """把每个检测器的命中合并成排好序、编好号的 episode 列表。

    ``detections`` 把 ``(series_id, detector)`` 映到 ``[(epoch_ms, row_no, score)]``；
    这里再按 ``(时间, 行号)`` 重排一次，调用方就没法夹带迭代顺序依赖（旧仓 plan/02 §4.2）。
    """
    episodes = []
    for series_id in sorted(rows_by_series):
        for detector in sorted(_detectors_for(detections, series_id)):
            points = sorted(detections[(series_id, detector)], key=lambda item: (item[0], item[1]))
            if not points:
                continue
            episodes.extend(merge_episodes(series_id, detector, points, max_gap_ms, decimals))
    return assign_ids(order_episodes(episodes))


def _detectors_for(detections, series_id):
    return [key[1] for key in detections if key[0] == series_id]