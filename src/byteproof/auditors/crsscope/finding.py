"""crsscope 判定核共享件（照搬旧仓 geodesy.py / report.Finding / mask 纯判定 / errors 全序）。

文件 I/O（read_text/read_points/load_mask）属输入层；本包收解析后的点集 / 掩膜网格 /
GeoJSON 文档 / 瓦片组。``outcome_code`` 的 5→1→0 段与退出码映射在 audit.py 折算。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

# ------------------------------------------------------------------ geodesy（照搬）
EARTH_RADIUS_M = 6371008.8


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """球面大圆距离（米）。度与米换算的唯一实现处。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def normalize_lon(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def lon_delta(a: float, b: float) -> float:
    return normalize_lon(a - b)


def approx_meters_per_degree_lat(lat: float) -> float:
    return math.pi * EARTH_RADIUS_M / 180.0


def approx_meters_per_degree_lon(lat: float) -> float:
    return math.pi * EARTH_RADIUS_M * math.cos(math.radians(lat)) / 180.0


# ------------------------------------------------------------------ Finding（照搬形状）
STATUS_CONSISTENT = "consistent"
STATUS_CONFLICT = "conflict"
STATUS_UNDECIDABLE = "undecidable"
STATUS_INFO = "info"
STATUS_WARNING = "warning"
STATUS_ERROR = "error"

#: 默认视为"判定命中"的状态（warning 刻意不含——分级而非拒绝）。
DEFAULT_HIT_STATUSES = frozenset({"conflict", "error"})


@dataclass
class Finding:
    """统一结果项：所有模块的每条结论都长这个形状。"""

    check: str
    status: str
    detail: str
    reason: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "check": self.check,
            "status": self.status,
            "reason": self.reason,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def outcome_code(findings: Iterable[Finding]) -> int:
    """把一份判定结果折算成账本阻断语义：undecidable → 0（灰区不阻断，warn 可见），
    命中（conflict/error）→ 1，其余 0。旧仓 5（灰区）→ 0 已登记口径差。"""
    statuses = [f.status for f in findings]
    if any(status in DEFAULT_HIT_STATUSES for status in statuses):
        return 1
    return 0


# ------------------------------------------------------------------ mask 纯判定（照搬）
MAX_RESOLUTION_DEG = 1.0
LAND = "land"
WATER = "water"
UNKNOWN = "unknown"
COASTAL = "coastal"


class EnvironmentMissing(ValueError):
    """掩膜步长超限等环境不满足（旧仓 exit 3 → 本账本 ValueError → rc2）。"""


@dataclass(frozen=True)
class Mask:
    """构造网格。cells 以 (lat_idx, lon_idx) 为键，值为 land/water/unknown。"""

    version: str
    resolution_deg: float
    lon_min: float
    lat_min: float
    n_lon: int
    n_lat: int
    cells: Dict[Tuple[int, int], str]

    def __post_init__(self) -> None:
        if self.resolution_deg > MAX_RESOLUTION_DEG + 1e-12:
            raise EnvironmentMissing(
                "掩膜步长 %s° 超过首期上限 %s°" % (self.resolution_deg, MAX_RESOLUTION_DEG)
            )

    @property
    def max_resolution_deg(self) -> float:
        return self.resolution_deg

    def index_of(self, lon: float, lat: float) -> Optional[Tuple[int, int]]:
        i_lon = int((lon - self.lon_min) // self.resolution_deg)
        i_lat = int((lat - self.lat_min) // self.resolution_deg)
        if not (0 <= i_lon < self.n_lon and 0 <= i_lat < self.n_lat):
            return None
        return i_lat, i_lon

    def cell_at(self, lon: float, lat: float) -> str:
        index = self.index_of(lon, lat)
        if index is None:
            return UNKNOWN
        return self.cells.get(index, UNKNOWN)

    def is_coastal(self, lon: float, lat: float) -> bool:
        """与异类相邻的格在评分时单独计数，不进分母。"""
        index = self.index_of(lon, lat)
        if index is None:
            return False
        i_lat, i_lon = index
        center = self.cells.get((i_lat, i_lon))
        for d_lat in (-1, 0, 1):
            for d_lon in (-1, 0, 1):
                if d_lat == 0 and d_lon == 0:
                    continue
                neighbor = self.cells.get((i_lat + d_lat, i_lon + d_lon))
                if neighbor is not None and neighbor != center and center in (LAND, WATER) and neighbor in (LAND, WATER):
                    return True
        return False


class MaskStats:
    """落水评分累计器。分母规则只在这里实现一次：unknown 与海岸带不计入分母。"""

    def __init__(self) -> None:
        self.water = 0
        self.land = 0
        self.unknown = 0
        self.coastal = 0

    def add(self, mask: Mask, lon: float, lat: float) -> None:
        value = mask.cell_at(lon, lat)
        if value == UNKNOWN:
            self.unknown += 1
            return
        if mask.is_coastal(lon, lat):
            self.coastal += 1
            return
        if value == WATER:
            self.water += 1
        else:
            self.land += 1

    @property
    def evaluable(self) -> int:
        return self.water + self.land

    @property
    def water_ratio(self) -> Optional[float]:
        """落水率；无格内点（分母 0）→ None（不硬造比率）。"""
        if self.evaluable == 0:
            return None
        return self.water / self.evaluable

    def as_header(self, mask: Mask) -> dict:
        return {
            "mask_version": mask.version,
            "mask_max_resolution_deg": mask.max_resolution_deg,
            "water": self.water,
            "land": self.land,
            "unknown": self.unknown,
            "coastal": self.coastal,
        }
