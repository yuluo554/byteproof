"""GCJ-02 / BD-09 / WebMercator 常数与算法（照搬旧仓 ``algorithms.py`` 全文）。

常数**原样照录**；两套 ``out_of_china`` 边界各留一份，**不合并、不取并集**——
它们不同这件事本身就是审计发现点。前向变换只服务测试构造，不作为产品能力
（不提供 convert）。逆向迭代超上限 → ``converged=False``，不得静默返回。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KRASOVSKY_A = 6378245.0
KRASOVSKY_EE = 0.006693421622965823
X_PI = math.pi * 3000.0 / 180.0
WEBMERCATOR_MAX = 20037508.342789244
INVERSE_TOLERANCE_DEG = 1e-6
INVERSE_MAX_ITER = 100

CT_PY_BBOX = {"lon": (73.66, 135.05), "lat": (3.86, 53.55), "closed": False}
GCOORD_BBOX = {"lon": (72.004, 137.8347), "lat": (0.8293, 55.8271), "closed": True}

PROFILE_CT_PY = "coordTransform_py"
PROFILE_GCOORD = "gcoord"

HYPOTHESES = ("WGS84", "GCJ02", "BD09")


def in_bbox(lon: float, lat: float, bbox: dict) -> bool:
    """按给定边界框判定；``closed`` 决定端点是否算"境内"——端点差异是实质差异。"""
    (lon_lo, lon_hi), (lat_lo, lat_hi) = bbox["lon"], bbox["lat"]
    if bbox["closed"]:
        return lon_lo <= lon <= lon_hi and lat_lo <= lat <= lat_hi
    return lon_lo < lon < lon_hi and lat_lo < lat < lat_hi


def in_china(lon: float, lat: float, profile: str = PROFILE_GCOORD) -> bool:
    if profile == PROFILE_CT_PY:
        return in_bbox(lon, lat, CT_PY_BBOX)
    if profile == PROFILE_GCOORD:
        return in_bbox(lon, lat, GCOORD_BBOX)
    raise ValueError("未知边界画像: %s" % profile)


def distance_to_bbox_deg(lon: float, lat: float, bbox: dict) -> float:
    """到边界框矩形边的近似角距（度）；框内不是 0——只有落在边上才是 0。"""
    (lon_lo, lon_hi), (lat_lo, lat_hi) = bbox["lon"], bbox["lat"]
    dlon = max(lon_lo - lon, 0.0, lon - lon_hi)
    dlat = max(lat_lo - lat, 0.0, lat - lat_hi)
    if dlon > 0.0 or dlat > 0.0:
        return math.hypot(dlon, dlat)
    return min(lon - lon_lo, lon_hi - lon, lat - lat_lo, lat_hi - lat)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def _delta(lon: float, lat: float) -> tuple[float, float]:
    dlat_rad = _transform_lat(lon - 105.0, lat - 35.0)
    dlon_rad = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = math.radians(lat)
    magic = 1.0 - KRASOVSKY_EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat_rad * 180.0) / ((KRASOVSKY_A * (1.0 - KRASOVSKY_EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon_rad * 180.0) / (KRASOVSKY_A / sqrtmagic * math.cos(radlat) * math.pi)
    return dlon, dlat


def wgs84_to_gcj02(lon: float, lat: float, profile: str = PROFILE_GCOORD) -> tuple[float, float]:
    """WGS84 → GCJ-02。境外按 profile 的边界框原样返回（不偏移）。"""
    if not in_china(lon, lat, profile):
        return lon, lat
    dlon, dlat = _delta(lon, lat)
    return lon + dlon, lat + dlat


@dataclass(frozen=True)
class InverseResult:
    """逆向结果。``converged=False`` 时调用方必须把 not_converged 报出来。"""

    lon: float
    lat: float
    converged: bool
    iterations: int


def gcj02_to_wgs84_iterative(lon: float, lat: float, profile: str = PROFILE_GCOORD) -> InverseResult:
    """gcoord 口径：定点迭代，容差 1e-6°；超上限返回 converged=False（不抛异常不静默）。"""
    if not in_china(lon, lat, profile):
        return InverseResult(lon, lat, True, 0)
    cur_lon, cur_lat = lon, lat
    for i in range(1, INVERSE_MAX_ITER + 1):
        fwd_lon, fwd_lat = wgs84_to_gcj02(cur_lon, cur_lat, profile)
        dx, dy = fwd_lon - lon, fwd_lat - lat
        cur_lon -= dx
        cur_lat -= dy
        if abs(dx) <= INVERSE_TOLERANCE_DEG and abs(dy) <= INVERSE_TOLERANCE_DEG:
            return InverseResult(cur_lon, cur_lat, True, i)
    return InverseResult(cur_lon, cur_lat, False, INVERSE_MAX_ITER)


def gcj02_to_wgs84_linear(lon: float, lat: float, profile: str = PROFILE_CT_PY) -> InverseResult:
    """coordTransform_py 口径：一步线性近似；恒 converged 但不代表精确（xdiff 如实差分）。"""
    if not in_china(lon, lat, profile):
        return InverseResult(lon, lat, True, 0)
    mg_lon, mg_lat = wgs84_to_gcj02(lon, lat, profile)
    return InverseResult(lon * 2.0 - mg_lon, lat * 2.0 - mg_lat, True, 1)


def gcj02_to_bd09(lon: float, lat: float) -> tuple[float, float]:
    z = math.sqrt(lon * lon + lat * lat) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lon) + 0.000003 * math.cos(lon * X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def bd09_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    x, y = lon - 0.0065, lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def wgs84_to_bd09(lon: float, lat: float, profile: str = PROFILE_GCOORD) -> tuple[float, float]:
    g_lon, g_lat = wgs84_to_gcj02(lon, lat, profile)
    return gcj02_to_bd09(g_lon, g_lat)


def bd09_to_wgs84(lon: float, lat: float, profile: str = PROFILE_GCOORD) -> InverseResult:
    g_lon, g_lat = bd09_to_gcj02(lon, lat)
    return gcj02_to_wgs84_iterative(g_lon, g_lat, profile)


def wgs84_to_webmercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = lon * WEBMERCATOR_MAX / 180.0
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * WEBMERCATOR_MAX / math.pi
    return x, y


def webmercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    lon = x / WEBMERCATOR_MAX * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(y * math.pi / WEBMERCATOR_MAX)) - math.pi / 2.0)
    return lon, lat


def inverse_for(hypothesis: str, lon: float, lat: float, profile: str = PROFILE_GCOORD) -> InverseResult:
    """给定假设 h，求"若输入是 h 则真实 WGS84 坐标"。"""
    if hypothesis == "WGS84":
        return InverseResult(lon, lat, True, 0)
    if hypothesis == "GCJ02":
        return gcj02_to_wgs84_iterative(lon, lat, profile)
    if hypothesis == "BD09":
        return bd09_to_wgs84(lon, lat, profile)
    raise ValueError("未知假设: %s" % hypothesis)
