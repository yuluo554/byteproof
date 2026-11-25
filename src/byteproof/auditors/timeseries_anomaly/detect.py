"""四个确定性检测器 + 周期估计（旧仓 ``anomaly_atlas/detect.py`` 的信号段）。

搬过来的部分只有**检测算术**：``cmd_detect`` 那半段（读写文件、写产物目录、打印）
留在旧仓，不属于器官。器官产出的是账本条目，不是档案。

四个检测器各自只吐"原始分数"，不合并、不排序、不命名 —— 合并是
:mod:`byteproof.auditors.timeseries_anomaly.episodes` 的唯一职责（旧仓 K6/K7）。

``period_points <= 1`` 的含义是"没有周期分量"：季节性项退化成均值，只扣趋势。
这是"序列太短，撑不起一个周期"时的**文档化结论**，不是静默降级。
"""

from __future__ import annotations

from .numeric import (
    _bisquare_weights,
    _loess,
    _mean,
    _mean_abs_deviation,
    _median,
    _next_odd,
    _quantile,
    _sqrt_by_newton,
    robust_scale,
    robust_z,
    trailing_window,
)
from .params import DECIMAL_RESOLUTION_FRACTION


# ---------------------------------------------------------------------------
# 检测器 1：滚动中位数 + MAD
# ---------------------------------------------------------------------------
def rolling_mad_z(values, window, k, min_valid):
    """滚动 median/MAD 稳健 z；``|z| > k`` 命中。窗口**包含**被判的那个点。

    包含它才能让窗口是一个老老实实的尾随切片（一趟、可镜像）。少量极端值挪不动
    中位数与"偏差的中位数"，所以尖峰不会掩蔽自己的检出，被标出的点也不会抬高下一个窗口的尺度。
    """
    hits = []
    for index in range(len(values)):
        target = values[index]
        if target is None:
            continue
        window_values = trailing_window(values, index, window)
        if len(window_values) < min_valid:
            continue
        score = robust_z(window_values, target)
        if score > k:
            hits.append((index, score))
    return hits


# ---------------------------------------------------------------------------
# 检测器 2：滚动四分位距
# ---------------------------------------------------------------------------
def rolling_iqr(values, window, iqr_mult, min_valid):
    """滚动箱界 ``[Q1 - m*IQR, Q3 + m*IQR]``；越界命中，分数以 IQR 为单位。"""
    hits = []
    for index in range(len(values)):
        target = values[index]
        if target is None:
            continue
        window_values = trailing_window(values, index, window)
        if len(window_values) < min_valid:
            continue
        q1 = _quantile(window_values, 0.25)
        q3 = _quantile(window_values, 0.75)
        iqr = q3 - q1
        if iqr > 0:
            low = q1 - iqr_mult * iqr
            high = q3 + iqr_mult * iqr
            scale = iqr
        else:
            # 退化箱：与 MAD 路径同一条显式兜底 —— 平窗上的尖峰仍然要能标出，分数必须有限。
            median_value = _median(window_values)
            scale = _mean_abs_deviation(window_values, median_value)
            if scale == 0:
                continue
            low = median_value - iqr_mult * scale
            high = median_value + iqr_mult * scale
        if target > high:
            hits.append((index, (target - high) / scale))
        elif target < low:
            hits.append((index, (low - target) / scale))
    return hits


# ---------------------------------------------------------------------------
# 检测器 3：STL 残差 z（自实现经典分解，不引 statsmodels）
# ---------------------------------------------------------------------------
def _seasonal_curve(detrended, positions, period_points, weights, window):
    """循环季节曲线：加权相位均值，再沿相位轴平滑。

    相位来自**网格下标**而不是列表位置：丢掉的样本会把其后每一个位置挪一格，
    按位置折叠就会把周期抹平。平滑前把相位轴三倍化再取中间一份，使平滑在环路处连续 ——
    端部用单边窗口会在周期接缝上留一道可见的断痕。
    """
    totals = [0.0] * period_points
    counts = [0.0] * period_points
    for index in range(len(detrended)):
        value = detrended[index]
        if value is None:
            continue
        phase = positions[index] % period_points
        weight = weights[index] if weights is not None else 1.0
        totals[phase] += weight * value
        counts[phase] += weight
    phase_means = []
    for phase in range(period_points):
        if counts[phase] > 0:
            phase_means.append(totals[phase] / counts[phase])
        else:
            phase_means.append(0.0)

    tripled = phase_means + phase_means + phase_means
    smoothed = _loess(tripled, window)
    middle = smoothed[period_points : 2 * period_points]
    return [
        (middle[phase] if middle[phase] is not None else phase_means[phase])
        for phase in range(period_points)
    ]


def stl_residual(values, positions, period_points, inner, outer):
    """趋势 + 季节分解；返回残差（缺失处为 ``None``）。

    结构与经典 STL 的 inner/outer 循环一致：每一轮 ``inner`` 次季节/趋势精化，
    其上 ``outer`` 轮稳健性迭代。
    """
    count = len(values)
    if period_points <= 1:
        present = [value for value in values if value is not None]
        seasonal_value = _mean(present) if present else 0.0
        detrended = [(value - seasonal_value) if value is not None else None for value in values]
        trend = _loess(detrended, _next_odd(max(3, min(count, 24))))
        return [
            (detrended[i] - trend[i])
            if (detrended[i] is not None and trend[i] is not None)
            else None
            for i in range(count)
        ]

    trend_window = _next_odd(3 * period_points // 2)
    seasonal_window = _next_odd(period_points // 3)
    weights = [1.0] * count
    trend = _loess(values, trend_window)
    seasonal = [0.0] * count
    residual = list(values)
    for _pass in range(outer + 1):
        for _iteration in range(inner):
            detrended = [
                (values[i] - trend[i])
                if (values[i] is not None and trend[i] is not None)
                else None
                for i in range(count)
            ]
            curve = _seasonal_curve(detrended, positions, period_points, weights, seasonal_window)
            seasonal = [curve[positions[i] % period_points] for i in range(count)]
            deseasonalized = [
                (values[i] - seasonal[i]) if values[i] is not None else None
                for i in range(count)
            ]
            trend = _loess(deseasonalized, trend_window, weights)
        residual = [
            (values[i] - trend[i] - seasonal[i])
            if (values[i] is not None and trend[i] is not None)
            else None
            for i in range(count)
        ]
        weights = _bisquare_weights(residual)
    return residual


def stl_resid_z(values, positions, period_points, inner, outer, window, k, min_valid):
    """STL 残差再用同一套滚动 median/MAD z 打分（同一实现，不是副本）。"""
    residual = stl_residual(values, positions, period_points, inner, outer)
    return rolling_mad_z(residual, window, k, min_valid)


# ---------------------------------------------------------------------------
# 检测器 4：阈值 / 百分比跳变 / 缺失与零值段 / CUSUM
# ---------------------------------------------------------------------------
def rules(values, spec):
    """规则检测器，各自返回 ``(index, score, rule_name)``。

    缺失段与零值段是**发现**，不是要跳过的空档：一段连续的缺失正好是这套档案要记录的事件，
    段长就是它的分数。百分比跳变规则要求前驱非零 —— 零基准下相对变化没有定义，
    该规则在此保持沉默，由零值段规则承接这个情形（不是静默填一个值）。
    """
    hits = []
    static_threshold = spec["static_threshold"]
    if static_threshold is not None:
        for index, value in enumerate(values):
            if value is None:
                continue
            if abs(value) > static_threshold:
                hits.append((index, abs(value) - static_threshold, "static_threshold"))

    pct_jump = spec["pct_jump"]
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous is None or current is None or previous == 0:
            continue
        ratio = current / previous
        jump = ratio - 1.0
        if jump < 0:
            jump = -jump
        if jump > pct_jump:
            hits.append((index, jump, "pct_jump"))

    _run_hits(values, spec["missing_run"], True, hits)
    _run_hits(values, spec["missing_run"], False, hits)
    _cusum_hits(values, spec["cusum_k"], spec["cusum_h"], hits)
    return hits


def _run_hits(values, minimum, missing, hits):
    """连续缺失（或连续零值）段，长度至少 ``minimum``。"""
    start = None
    for index in range(len(values) + 1):
        inside = index < len(values) and (
            values[index] is None if missing else values[index] == 0.0
        )
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            length = index - start
            if length >= minimum:
                name = "missing_run" if missing else "zero_run"
                for position in range(start, index):
                    hits.append((position, float(length), name))
            start = None


def _cusum_hits(values, cusum_k, cusum_h, hits):
    """两侧 CUSUM，作用在相邻差分上，用差分的稳健尺度标准化。

    作用在差分上是这条规则独立于日周期与漂移的原因：电平迁移进来是一次跳变（移出又是
    一次），尖峰是两次跳变，而缓慢的周期每步贡献几乎为零。只有有效的相邻样本参与 ——
    缺失样本既不推进也不重置累加器。尺度取全局而非滚动，因为累加器本身就是平滑；
    一条序列只有一个差分尺度。报警后两侧累加器都重置（经典 CUSUM 的重启策略）：
    不重置的话一次偏移会在衰减期内持续复报，把一件事报成一长串。

    差分尺度落在输入的小数分辨率上，意味着这条序列**没有短期噪声**（直线、常量）：
    用它标准化只会把最后一位二进制小数放大成"天文级跳变"，一条完美直线也会报警。
    那里没有可检测的东西，规则就此停手。
    """
    differences = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        current = values[index]
        if previous is None or current is None:
            continue
        differences.append((index, current - previous))
    if not differences:
        return
    scale_values = [difference for _index, difference in differences]
    scale, _median_value = robust_scale(scale_values)
    present = [value for value in values if value is not None]
    reference = robust_scale(present)[0] if present else 0.0
    if scale == 0 or scale < DECIMAL_RESOLUTION_FRACTION * reference:
        return
    positive = 0.0
    negative = 0.0
    for index, difference in differences:
        standardized = difference / scale
        positive += standardized - cusum_k
        if positive < 0.0:
            positive = 0.0
        negative += -standardized - cusum_k
        if negative < 0.0:
            negative = 0.0
        score = positive if positive > negative else negative
        if score > cusum_h:
            hits.append((index, score, "cusum"))
            positive = 0.0
            negative = 0.0


# ---------------------------------------------------------------------------
# 采样网格与周期估计
# ---------------------------------------------------------------------------
def dominant_interval(stamps):
    """最常见的正间隔；并列取最短（即采样网格）。"""
    counts = {}
    for index in range(1, len(stamps)):
        delta = stamps[index] - stamps[index - 1]
        if delta > 0:
            counts[delta] = counts.get(delta, 0) + 1
    if not counts:
        return None
    return sorted(counts, key=lambda delta: (-counts[delta], delta))[0]


def to_grid(stamps, values, cadence):
    """把样本放到由时间戳重建的采样网格上。

    从时间轴重建网格（而不是相信列表顺序）是周期相位能跨越丢点保持正确的原因；
    重复时间戳在一个格子里只保留一个值。
    """
    start = stamps[0]
    cells = (stamps[-1] - start) // cadence
    grid = [None] * (cells + 1)
    for stamp, value in zip(stamps, values):
        grid[(stamp - start) // cadence] = value
    return grid


def grid_positions(rows):
    """一条序列每个样本的网格下标，只由时间戳决定。

    STL 的季节曲线按这个下标折叠而不是按列表位置，丢掉一个样本不会挪动其后所有样本的相位。
    """
    stamps = [row[1] for row in rows]
    cadence = dominant_interval(stamps)
    if cadence is None:
        return list(range(len(rows)))
    start = stamps[0]
    return [(stamp - start) // cadence for stamp in stamps]


def _median_trend(grid, window):
    """网格上的居中滚动中位数。"""
    half = window // 2
    count = len(grid)
    trend = []
    for index in range(count):
        low = index - half
        high = index + half
        if low < 0:
            low = 0
        if high > count - 1:
            high = count - 1
        local = [grid[position] for position in range(low, high + 1) if grid[position] is not None]
        trend.append(_median(local) if local else None)
    return trend


def _standardized_series(grid):
    """最小二乘去趋势，再中心化并按 3 个稳健 sigma 缩尾。"""
    points = [(index, value) for index, value in enumerate(grid) if value is not None]
    if len(points) < 2:
        return [None] * len(grid)
    count = float(len(points))
    sum_x = 0.0
    sum_y = 0.0
    for index, value in points:
        sum_x += index
        sum_y += value
    mean_x = sum_x / count
    mean_y = sum_y / count
    sxx = 0.0
    sxy = 0.0
    for index, value in points:
        dx = index - mean_x
        sxx += dx * dx
        sxy += dx * (value - mean_y)
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = mean_y - slope * mean_x
    detrended = [
        (value - (intercept + slope * index)) if value is not None else None
        for index, value in enumerate(grid)
    ]
    present = [value for value in detrended if value is not None]
    scale, median_value = robust_scale(present)
    if scale == 0:
        return [None] * len(grid)
    out = []
    for value in detrended:
        if value is None:
            out.append(None)
            continue
        standardized = (value - median_value) / scale
        if standardized > 3.0:
            standardized = 3.0
        elif standardized < -3.0:
            standardized = -3.0
        out.append(standardized)
    return out


def _autocorrelation(z, max_lag):
    """网格上的成对完整自相关：缺失格子丢这一对，不丢这个滞后。"""
    count = len(z)
    correlations = []
    for lag in range(0, max_lag + 1):
        numerator = 0.0
        left = 0.0
        right = 0.0
        for index in range(lag, count):
            a = z[index]
            b = z[index - lag]
            if a is None or b is None:
                continue
            numerator += a * b
            left += a * a
            right += b * b
        if left > 0 and right > 0:
            correlations.append(numerator / _sqrt_by_newton(left * right))
        else:
            correlations.append(0.0)
    return correlations


def estimate_series_period(grid, reject_window, reject_sigma):
    """一条网格的稳健周期估计；撑不起周期时返回 ``None``。

    估计器必须扛得住检测器要找的那些异常。在冻结夹具上实测：直接对原始序列做 ACF，
    峰值落在滞后 2 到 302 之间而不是 288 —— 单是植入的零值段就在某点携带 78% 的方差，
    而一段 26–41 点的电平迁移在前 41 个滞后上铺了一条宽斜坡。所以 ACF 跑在**清洗过**的网格上：

      1. 对居中滚动中位数取残差（窗口大于要拒绝的最长段的两倍，这样该段在每个窗口里都是少数）；
      2. 残差超过 ``reject_sigma`` 个稳健 sigma 的格子**删除**而不是替换。删除是诚实的动作：
         被拒的格子说的是"这里没有可用样本"，正是成对自相关本来就懂的事实；替换会凭空造一个值，
         还把那一段的结构留在原地；
      3. 去掉一条最小二乘直线（平滑趋势不是周期，会淹没方差远小于漂移的日周期），
         再按三个稳健 sigma 缩尾，免得幸存下来的离群点主导结果；
      4. 网格上的成对自相关，在 ``[max(8, n/16), n/3]`` 里找最强局部极大 ——
         下界把短滞后的异常结构挡在答案之外，上界要求至少能看到三个周期 ——
         然后在某个约数还能解释 80% 以上时归约到基频（一个干净的周期在每个倍数上都出峰）。
    """
    present = [value for value in grid if value is not None]
    count = len(present)
    if count < 24:
        return None
    high = count // 3
    low = max(8, count // 16)
    if high <= low:
        return None

    trend = _median_trend(grid, reject_window)
    residual = [
        (grid[i] - trend[i]) if (grid[i] is not None and trend[i] is not None) else None
        for i in range(len(grid))
    ]
    residual_values = [value for value in residual if value is not None]
    if not residual_values:
        return None
    scale, _median_value = robust_scale(residual_values)
    if scale == 0:
        return None
    pruned = []
    for index, value in enumerate(residual):
        if value is not None and abs(value) > reject_sigma * scale:
            pruned.append(None)
        else:
            pruned.append(grid[index])
    z = _standardized_series(pruned)
    if not any(value is not None for value in z):
        return None
    # 多算一个滞后：这样 high 处的局部极大判定有右邻居可比。
    correlations = _autocorrelation(z, high + 1)
    best = None
    for lag in range(low, high + 1):
        if correlations[lag] >= correlations[lag - 1] and correlations[lag] >= correlations[lag + 1]:
            if best is None or correlations[lag] > correlations[best]:
                best = lag
    if best is None:
        return None
    if correlations[best] <= 0.15:
        return None
    # 优先基频。干净周期的自相关在真实周期的**每个**倍数上都出峰，所以最高的峰往往是谐波
    # （实测：周期 40 的网格在 80 处出峰 r = 0.996，而 80 的一半能解释其中 99%）。
    # 在某个约数仍能解释大部分相关性、且仍落在搜索窗内时，反复二/三/四等分。
    reduced = True
    while reduced:
        reduced = False
        for divisor in (2, 3, 4):
            if best % divisor:
                continue
            candidate = best // divisor
            if candidate < low:
                continue
            if correlations[candidate] >= 0.8 * correlations[best]:
                best = candidate
                reduced = True
                break
    return best


def estimate_period(rows_by_series, series_order, reject_window, reject_sigma):
    """逐序列周期估计与运行级周期。

    运行级取逐序列估计的**下中位数**（偶数个时取下侧中间值），一条不具代表性的序列拖不动它；
    估计器本身在下游永不重跑（旧仓 K8/D13）。
    """
    estimates = []
    for series_id in series_order:
        rows = rows_by_series[series_id]
        stamps = [row[1] for row in rows]
        values = [row[2] for row in rows]
        cadence = dominant_interval(stamps)
        if cadence is None or len(rows) < 24:
            continue
        grid = to_grid(stamps, values, cadence)
        estimate = estimate_series_period(grid, reject_window, reject_sigma)
        if estimate is not None:
            estimates.append((series_id, estimate))
    if not estimates:
        return 1, []
    ordered = sorted(estimate for _series_id, estimate in estimates)
    return ordered[(len(ordered) - 1) // 2], estimates