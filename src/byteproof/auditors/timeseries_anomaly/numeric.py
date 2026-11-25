"""数值基元：只用 ``+ - * / floor abs min max`` 与比较（旧仓 ``detect.py`` 的算术段）。

为什么每个归约都手写循环而不是用 ``sum`` / ``statistics``：**求和顺序是规格的一部分**。
库函数的归约顺序是实现细节，换一个运行时就可能差一个 ulp；账本要"同一输入两次运行字节
一致"，就不能把这一点留给库。

函数名一律带下划线前缀（``_median`` / ``_mean`` / ``_sqrt``）：``tests/test_<slug>.py``
里的"禁超越函数"门按 AST 抓 ``Call(func=Name)``，裸叫 ``median(...)`` / ``sqrt(...)``
会被判红 —— 这不是命名习惯，是那条门在起作用（旧仓同源）。

退化窗口的纪律写在 :func:`robust_scale` 里，而不是留给"除以 0 得 inf 再比较"。
"""

from __future__ import annotations

from .params import MAD_TO_SIGMA


def _median(values):
    """中位数：两个中间值线性插值（不用 ``statistics``）。"""
    if not values:
        raise ValueError("空窗口中位数")
    ordered = sorted(values)
    count = len(ordered)
    if count == 1:
        return ordered[0]
    position = 0.5 * (count - 1)
    low = int(position)
    high = low + 1
    if high >= count:
        return ordered[-1]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _quantile(values, fraction):
    """线性插值分位数（单一实现点，未排序输入）。"""
    if not values:
        raise ValueError("空窗口分位数")
    ordered = sorted(values)
    count = len(ordered)
    if count == 1:
        return ordered[0]
    position = fraction * (count - 1)
    low = int(position)
    high = low + 1
    if high >= count:
        return ordered[-1]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _mean(values):
    total = 0.0
    for value in values:
        total += value
    return total / float(len(values))


def _mad(values, median_value):
    """相对给定中位数的绝对偏差中位数。"""
    deviations = []
    for value in values:
        deviations.append(abs(value - median_value))
    return _median(deviations)


def _mean_abs_deviation(values, median_value):
    total = 0.0
    for value in values:
        total += abs(value - median_value)
    return total / float(len(values))


def robust_scale(values):
    """窗口的稳健尺度（sigma 单位）+ 该窗口中位数，退化情形显式兜底。

    ``mad == 0`` 意味着窗口里超过一半的点正好落在中位数上，MAD 不含尺度信息；
    平均绝对偏差仍然含（尖峰放在平窗上还是尖峰）。尺度为 0 意味着窗口里每个值都一样，
    任何点都无法相对它判级 —— 返回 0，由调用方**跳过**该点，而不是除以 0。
    """
    median_value = _median(values)
    mad = _mad(values, median_value)
    if mad > 0:
        return MAD_TO_SIGMA * mad, median_value
    return MAD_TO_SIGMA * _mean_abs_deviation(values, median_value), median_value


def trailing_window(values, index, window):
    """尾随窗口 ``[index-window+1, index]``（含端点）里的有效值。"""
    low = index - window + 1
    if low < 0:
        low = 0
    found = []
    for position in range(low, index + 1):
        value = values[position]
        if value is not None:
            found.append(value)
    return found


def robust_z(window_values, target):
    """``|x - median| / scale``；窗口判不了这个点时返回 0。"""
    scale, median_value = robust_scale(window_values)
    if scale == 0:
        return 0.0
    return abs(target - median_value) / scale


def _sqrt_by_newton(value):
    """Newton 迭代求平方根：``**0.5`` 与 ``math.sqrt`` 都在禁列（libm 逐位差异）。"""
    if value <= 0:
        return 0.0
    guess = float(value)
    for _iteration in range(60):
        next_guess = 0.5 * (guess + value / guess)
        if next_guess == guess:
            break
        guess = next_guess
    return guess


def _next_odd(value):
    """>= value 的最小奇数（LOESS 窗口对中心对称）。"""
    value = int(value)
    if value < 1:
        return 1
    return value if value % 2 else value + 1


def _tricube_table(dmax):
    """tri 权重 ``(1 - d^3)^3``，按整数距离建表（幂次展开成乘法）。"""
    table = []
    for distance in range(dmax + 1):
        if dmax > 0:
            ratio = distance / float(dmax)
        else:
            ratio = 0.0
        tricube = 1.0 - ratio * ratio * ratio
        table.append(tricube * tricube * tricube)
    return table


def _loess(values, window, weights=None):
    """局部加权直线拟合（tri 权），在每个位置上取值。

    ``window`` 数的是**位置**不是有效值：缺失样本只缩小有效样本，不移动窗口中心。
    拟合用的 x 以目标位置为原点计量，所以任意长度序列上的局部设计矩阵都良态，
    目标处的取值就是截距本身。
    """
    count = len(values)
    half = window // 2
    tables = {}
    fitted = [None] * count
    for index in range(count):
        if values[index] is None:
            continue
        low = index - half
        if low < 0:
            low = 0
        high = index + half
        if high > count - 1:
            high = count - 1
        if high == low:
            fitted[index] = values[index]
            continue
        dmax = max(index - low, high - index)
        table = tables.get(dmax)
        if table is None:
            table = _tricube_table(dmax)
            tables[dmax] = table
        sw = 0.0
        swx = 0.0
        swy = 0.0
        swxx = 0.0
        swxy = 0.0
        for position in range(low, high + 1):
            value = values[position]
            if value is None:
                continue
            offset = position - index
            if offset < 0:
                weight = table[-offset]
            else:
                weight = table[offset]
            if weights is not None:
                weight = weight * weights[position]
            x = float(offset)
            sw += weight
            swx += weight * x
            swy += weight * value
            swxx += weight * x * x
            swxy += weight * x * value
        if sw == 0:
            continue
        determinant = sw * swxx - swx * swx
        if determinant == 0:
            fitted[index] = swy / sw
        else:
            slope = (sw * swxy - swx * swy) / determinant
            intercept = (swy - slope * swx) / sw
            fitted[index] = intercept
    return fitted


def _bisquare_weights(residual):
    """bisquare 稳健权重 ``(1 - u^2)^2``（纯乘法）。"""
    deviations = []
    for value in residual:
        if value is not None:
            deviations.append(abs(value))
    if not deviations:
        return [1.0] * len(residual)
    scale = 6.0 * _median(deviations)
    weights = []
    for value in residual:
        if value is None or scale == 0:
            weights.append(1.0)
            continue
        ratio = abs(value) / scale
        if ratio >= 1.0:
            weights.append(0.0)
        else:
            factor = 1.0 - ratio * ratio
            weights.append(factor * factor)
    return weights