"""M5 瓦片轴序/投影一致性（照搬旧仓 ``tiles.py`` 判定核；输入为解析后的瓦片组）。

五项检查顺序固定、一项一责：y 越界（单点即判）/ y 轴翻转（XYZ vs TMS 混用）/
zoom↔bbox 嵌套 / wrap 显式声明 / 3857-4326 混用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .finding import (
    STATUS_CONFLICT,
    STATUS_CONSISTENT,
    STATUS_ERROR,
    STATUS_INFO,
    Finding,
)

REASON_AXIS_FLIP = "axis_flip"
REASON_Y_RANGE = "y_range"
REASON_ZOOM_BBOX = "zoom_bbox"
REASON_WRAP = "wrap"
REASON_MIXED = "mixed"

FLIP_FORMULA = "2**z - 1 - y"
TMS_NOTE = "XYZ 原点在左上、TMS 在左下；mercantile 没有 tms 形参，'y 轴翻转'被抹平——本项把它翻出来"

DEGREE_MAX = 180.0
METRE_MIN = 1_000_000.0
BAND_DEGREE = "degree"
BAND_METRE = "metre"
BAND_NEITHER = "neither"


@dataclass(frozen=True)
class Tile:
    z: int
    x: int
    y: int
    wrap: bool = False
    scheme: Optional[str] = None
    bbox: Optional[Tuple[float, float, float, float]] = None

    @property
    def rows(self) -> int:
        return 2 ** self.z

    @property
    def key(self) -> Dict[str, int]:
        return {"z": self.z, "x": self.x, "y": self.y}

    def as_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"z": self.z, "x": self.x, "y": self.y, "wrap": self.wrap}
        if self.scheme is not None:
            data["scheme"] = self.scheme
        if self.bbox is not None:
            data["bbox"] = list(self.bbox)
        return data


@dataclass
class TileGroup:
    id: str
    tiles: List[Tile] = field(default_factory=list)
    bbox: Optional[Tuple[float, float, float, float]] = None


@dataclass
class GroupAudit:
    id: str
    bbox: Optional[Tuple[float, float, float, float]] = None
    tiles: List[Tile] = field(default_factory=list)
    axis_flip_pairs: List[dict] = field(default_factory=list)
    y_range_offenders: List[dict] = field(default_factory=list)
    zoom_breaks: List[dict] = field(default_factory=list)
    wrap_missing: List[dict] = field(default_factory=list)
    wrap_needed: bool = False


def _row_limit(tile: Tile) -> int:
    return 2 ** tile.z - 1


def _same_bbox(group: TileGroup, first: Tile, second: Tile) -> bool:
    if first.bbox is not None and second.bbox is not None:
        return first.bbox == second.bbox
    if group.bbox is not None:
        return True
    return False


def audit_group(group: TileGroup) -> GroupAudit:
    """一组的判定事实（只记录，判定在 check_* 里）。"""
    audit = GroupAudit(id=group.id, bbox=group.bbox, tiles=list(group.tiles))

    # 1) y 越界：单点即判（§4.7）
    for tile in group.tiles:
        limit = _row_limit(tile)
        if tile.y < 0 or tile.y > limit:
            audit.y_range_offenders.append({**tile.key, "allowed": [0, limit], "scheme": tile.scheme})

    # 2) y 轴翻转：同一 z / 同一 x 下 y 与 2^z-1-y 并存，且指向同一 bbox
    by_column: Dict[Tuple[int, int], List[Tile]] = {}
    for tile in group.tiles:
        limit = _row_limit(tile)
        if 0 <= tile.y <= limit:
            by_column.setdefault((tile.z, tile.x), []).append(tile)
    for (z, x), column in sorted(by_column.items()):
        by_y = {tile.y: tile for tile in column}
        limit = 2 ** z - 1
        seen: set = set()
        for y, tile in sorted(by_y.items()):
            flipped = limit - y
            if flipped == y or flipped not in by_y:
                continue
            pair_key = (min(y, flipped), max(y, flipped))
            if pair_key in seen:
                continue
            other = by_y[flipped]
            if not _same_bbox(group, tile, other):
                continue
            seen.add(pair_key)
            audit.axis_flip_pairs.append({
                "group": group.id, "z": z, "x": x, "y": [y, flipped],
                "flip_formula": FLIP_FORMULA,
                "bbox": list(group.bbox) if group.bbox is not None else None,
                "schemes": [tile.scheme, other.scheme], "row_span": [0, limit],
            })

    # 3) zoom ↔ bbox：z+1 的父瓦片必须出现在 z 的集合里（否则覆盖不单调）
    by_zoom: Dict[int, List[Tile]] = {}
    for tile in group.tiles:
        if 0 <= tile.y <= _row_limit(tile):
            by_zoom.setdefault(tile.z, []).append(tile)
    for z, parent_tiles in sorted(by_zoom.items()):
        children = by_zoom.get(z + 1)
        if not children:
            continue
        parents = {(tile.x, tile.y) for tile in parent_tiles if 0 <= tile.x < 2 ** z}
        for child in sorted(children, key=lambda t: (t.x, t.y)):
            if not 0 <= child.x < 2 ** (z + 1):
                continue
            parent = (child.x // 2, child.y // 2)
            if parent not in parents:
                audit.zoom_breaks.append({
                    "group": group.id, "z": child.z, "x": child.x, "y": child.y,
                    "missing_parent": {"z": z, "x": parent[0], "y": parent[1]},
                })

    # 4) wrap：x 环绕必须显式 wrap: true（§4.7）
    crossing_bbox = group.bbox is not None and group.bbox[2] < group.bbox[0]
    for z, tiles in sorted(by_zoom.items()):
        limit_x = 2 ** z - 1
        columns = {tile.x for tile in tiles}
        out_of_range = [tile for tile in tiles if tile.x < 0 or tile.x > limit_x]
        edge_pair = z > 0 and 0 in columns and limit_x in columns
        if not (edge_pair or out_of_range or (crossing_bbox and z > 0)):
            continue
        audit.wrap_needed = True
        if crossing_bbox:
            required = tiles
        else:
            required = [tile for tile in tiles if tile.x in (0, limit_x) or tile.x < 0 or tile.x > limit_x]
        for tile in required:
            if not tile.wrap:
                audit.wrap_missing.append({**tile.key, "group": group.id})
    return audit


def _band_point(lon: float, lat: float) -> str:
    magnitude = max(abs(lon), abs(lat))
    if magnitude <= DEGREE_MAX:
        return BAND_DEGREE
    if magnitude >= METRE_MIN:
        return BAND_METRE
    return BAND_NEITHER


def check_axis_flip(audits: List[GroupAudit]) -> Finding:
    pairs = [pair for audit in audits for pair in audit.axis_flip_pairs]
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.7", "flip_formula": FLIP_FORMULA, "pairs": pairs}
    if pairs:
        first = pairs[0]
        return Finding(check="axis_flip", status=STATUS_CONFLICT, reason=REASON_AXIS_FLIP,
                       detail="%d 组 y 轴混用（XYZ 与 TMS 同时出现）：首个为 z=%d x=%d y=%d ↔ %d（%s），bbox=%s——同一 bbox 被两种 y 轴语义同时声明，静态可判，无需底图"
                              % (len(pairs), first["z"], first["x"], first["y"][0], first["y"][1], FLIP_FORMULA, first["bbox"]),
                       evidence=evidence)
    return Finding(check="axis_flip", status=STATUS_CONSISTENT,
                   detail="未发现 y 与 %s 同时指向同一 bbox 的混用" % FLIP_FORMULA, evidence=evidence)


def check_y_range(audits: List[GroupAudit]) -> Finding:
    offenders = [offender for audit in audits for offender in audit.y_range_offenders]
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.7", "offenders": offenders}
    if offenders:
        first = offenders[0]
        return Finding(check="y_range", status=STATUS_ERROR, reason=REASON_Y_RANGE,
                       detail="%d 枚瓦片的 y 越界（单点即判）：首个为 z=%d x=%d y=%d，该 z 的合法范围是 [%d, %d]"
                              % (len(offenders), first["z"], first["x"], first["y"], first["allowed"][0], first["allowed"][1]),
                       evidence=evidence)
    return Finding(check="y_range", status=STATUS_CONSISTENT, detail="全部瓦片的 y 都在 [0, 2^z - 1] 内", evidence=evidence)


def check_zoom_bbox(audits: List[GroupAudit]) -> Finding:
    breaks = [item for audit in audits for item in audit.zoom_breaks]
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.7", "breaks": breaks}
    if breaks:
        first = breaks[0]
        parent = first["missing_parent"]
        return Finding(check="zoom_bbox", status=STATUS_CONFLICT, reason=REASON_ZOOM_BBOX,
                       detail="%d 处 z+1 覆盖集合不嵌套：z=%d x=%d y=%d 的父瓦片 z=%d x=%d y=%d 不在集合里"
                              % (len(breaks), first["z"], first["x"], first["y"], parent["z"], parent["x"], parent["y"]),
                       evidence=evidence)
    return Finding(check="zoom_bbox", status=STATUS_CONSISTENT,
                   detail="z+1 的覆盖集合都嵌套在 z 的集合里（或输入只有单一 zoom）", evidence=evidence)


def check_wrap(audits: List[GroupAudit]) -> Finding:
    missing = [item for audit in audits for item in audit.wrap_missing]
    needed = any(audit.wrap_needed for audit in audits)
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.7", "wrap_required": needed, "missing": missing}
    if missing:
        first = missing[0]
        return Finding(check="wrap", status=STATUS_CONFLICT, reason=REASON_WRAP,
                       detail="x 环绕未显式声明 wrap：%d 枚（首个为 z=%d x=%d y=%d）——跨日界线的 x 环绕必须显式记录 wrap: true"
                              % (len(missing), first["z"], first["x"], first["y"]),
                       evidence=evidence)
    if not needed:
        return Finding(check="wrap", status=STATUS_CONSISTENT, detail="输入未出现跨日界线的 x 环绕", evidence=evidence)
    return Finding(check="wrap", status=STATUS_CONSISTENT, detail="跨日界线的 x 环绕已全部显式声明 wrap: true", evidence=evidence)


def check_mixed(kind: str, points: List[Tuple[float, float]]) -> Finding:
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.1", "input_kind": kind}
    if kind != "points":
        return Finding(check="mixed_3857_4326", status=STATUS_INFO,
                       detail="输入为 z/x/y 瓦片编号，没有 3857/4326 坐标量级可比（本项不适用）", evidence=evidence)
    if not points:
        return Finding(check="mixed_3857_4326", status=STATUS_INFO, detail="点集为空，量级无从判定", evidence=evidence)
    bands = {band: 0 for band in (BAND_DEGREE, BAND_METRE, BAND_NEITHER)}
    first_degree: Optional[Tuple[float, float]] = None
    first_metre: Optional[Tuple[float, float]] = None
    for lon, lat in points:
        band = _band_point(lon, lat)
        bands[band] += 1
        if band == BAND_DEGREE and first_degree is None:
            first_degree = (lon, lat)
        if band == BAND_METRE and first_metre is None:
            first_metre = (lon, lat)
    evidence["bands"] = bands
    evidence["degree_max"] = DEGREE_MAX
    evidence["metre_min"] = METRE_MIN
    if first_degree is not None and first_metre is not None:
        evidence["samples"] = [
            {"lon": first_degree[0], "lat": first_degree[1], "band": BAND_DEGREE},
            {"lon": first_metre[0], "lat": first_metre[1], "band": BAND_METRE},
        ]
        return Finding(check="mixed_3857_4326", status=STATUS_CONFLICT, reason=REASON_MIXED,
                       detail="同一集合内度域与米域并存：%d 个度域样本（如 %s）与 %d 个米域样本（如 %s）——3857 与 4326 混用"
                              % (bands[BAND_DEGREE], list(first_degree), bands[BAND_METRE], list(first_metre)),
                       evidence=evidence)
    if bands[BAND_DEGREE]:
        label = "全部在度域（与 4326 相容）"
    elif bands[BAND_METRE]:
        label = "全部在米域（与 3857 相容）"
    else:
        label = "全部落在中间带（180 < m < 1e6，量级无法归档）"
    return Finding(check="mixed_3857_4326", status=STATUS_CONSISTENT,
                   detail="量级分档一致：%s（%s）" % (label, bands), evidence=evidence)


def verdict_of(findings: List[Finding], kind: str) -> str:
    hits = [f.check for f in findings if f.status in {STATUS_CONFLICT, STATUS_ERROR}]
    if hits:
        return "瓦片/投影片不一致：" + "、".join(hits)
    if kind == "points":
        return "点集量级一致；瓦片轴序项不适用"
    return "瓦片轴序 / 范围 / 嵌套 / 环绕均未命中"


def run_tiles(groups: List[TileGroup], kind: str = "tiles", points: Optional[List[Tuple[float, float]]] = None) -> dict:
    """瓦片审计入口。判定顺序固定：y 越界 → 轴翻转 → 嵌套 → 环绕 → 混用。"""
    audits = [audit_group(group) for group in groups]
    findings = [
        check_y_range(audits),
        check_axis_flip(audits),
        check_zoom_bbox(audits),
        check_wrap(audits),
        check_mixed(kind, points or []),
    ]
    return {
        "kind": kind,
        "verdict": verdict_of(findings, kind),
        "groups": [
            {
                "id": audit.id,
                "tiles": len(audit.tiles),
                "axis_flip_pairs": audit.axis_flip_pairs,
                "y_range_offenders": audit.y_range_offenders,
                "zoom_breaks": audit.zoom_breaks,
                "wrap_missing": audit.wrap_missing,
                "wrap_needed": audit.wrap_needed,
            }
            for audit in audits
        ],
        "tms_note": TMS_NOTE,
        "findings": [f.as_dict() for f in findings],
    }
