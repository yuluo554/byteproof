"""M4 RFC 7946 结构审计（照搬旧仓 ``geojson.py`` 的检查项；输入为解析后的 JSON 文档）。

七项检查顺序固定、一项一责：环方向（R1，级别由 R2 决定 → 默认 warning）/
轴序 / bbox（含跨 180° 合法性）/ 嵌套 / null geometry / crs 成员 / 坐标精度。
精度读 Decimal 十进制指数，**不经过 float 往返**。结构性问题 → error（整体 InvalidInput 语义）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from .finding import (
    STATUS_CONSISTENT,
    STATUS_ERROR,
    STATUS_INFO,
    STATUS_WARNING,
    Finding,
)

PRECISION_MAX_FRACTION_DIGITS = 9
PRECISION_SAMPLES_CAP = 5

REASON_RING = "ring"
REASON_AXIS = "axis"
REASON_BBOX = "bbox"
REASON_STRUCTURE = "structure"

#: RFC 7946 原文锚点（变异靶子：R2 的容忍语义决定 R1 违规的级别）。
RFC_R1 = "right-hand rule"
RFC_R2 = "for backwards compatibility, parsers SHOULD NOT reject Polygons that do not follow the right-hand rule"
R2_TOLERANCE_MARKER = "SHOULD NOT reject"
RING_ORDER_DEFAULT_STATUS = STATUS_WARNING
RING_ORDER_STRICT_STATUS = STATUS_ERROR

CRS_REMOVED_WORDING = "RFC 7946 已移除 crs 成员（原第 4 节删除）"
CRS_PRIOR_ARRANGEMENT = "双方同意另行指定 CRS 仍可加 crs 成员"

GEOMETRY_DIMS: Dict[str, int] = {
    "Point": 0,
    "MultiPoint": 1,
    "LineString": 1,
    "MultiLineString": 2,
    "Polygon": 2,
    "MultiPolygon": 3,
}
GEOMETRY_TYPES = frozenset({"GeometryCollection", *GEOMETRY_DIMS})
TOP_TYPES = frozenset({"Feature", "FeatureCollection"}) | GEOMETRY_TYPES

_MISSING = object()


@dataclass
class FileAudit:
    """一个文件的审计事实（只记录，判定在 check_* 里）。"""

    name: str
    issues: List[Finding]
    points: List[Tuple[float, float]]
    ring_signs: List[dict]
    ring_violations: List[dict]
    bbox_members: List[dict]
    precision_samples: List[dict]
    geometry_types: List[str]
    max_fraction_digits: int
    null_geometries: int
    null_properties: int
    nesting_depth: int
    has_crs: bool
    top_type: Optional[str]

    @classmethod
    def empty(cls, name: str) -> "FileAudit":
        return cls(name=name, issues=[], points=[], ring_signs=[], ring_violations=[],
                   bbox_members=[], precision_samples=[], geometry_types=[],
                   max_fraction_digits=0, null_geometries=0, null_properties=0,
                   nesting_depth=0, has_crs=False, top_type=None)


def _issue(audit: FileAudit, message: str, **evidence: Any) -> None:
    """结构性问题：级别固定 error，check 固定 structure（§4.6）。"""
    audit.issues.append(
        Finding(check="structure", status=STATUS_ERROR, reason=REASON_STRUCTURE,
                detail="%s: %s" % (audit.name, message),
                evidence={"file": audit.name, "rule": "data/README.md §4.6", **evidence})
    )


def _number(value: object) -> Optional[float]:
    """JSON 数值 → float；布尔、字符串与非有限值一律 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
    elif isinstance(value, float):
        if not math_isfinite(value):
            return None
    elif not isinstance(value, int):
        return None
    result = float(value)
    return result if math_isfinite(result) else None


def math_isfinite(value: float) -> bool:
    import math

    return math.isfinite(value)


def fraction_digits(value: object) -> int:
    """单分量的十进制小数位；整数为 0。精度检查直接读 Decimal 指数。"""
    if isinstance(value, Decimal):
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int):
            return max(0, -exponent)
    return 0


def _leaf(node: object, audit: FileAudit) -> Optional[Tuple[float, float]]:
    """一个坐标对。长度 < 2 / 非数值 → 结构错误。"""
    if not isinstance(node, list):
        _issue(audit, "坐标对必须是数组", value_type=type(node).__name__)
        return None
    if len(node) < 2:
        _issue(audit, "坐标对只有 %d 个元素（至少需要 2 个）" % len(node),
               coordinate_length=len(node), min_length=2)
        return None
    lon, lat = _number(node[0]), _number(node[1])
    if lon is None or lat is None:
        _issue(audit, "坐标对含非数值或非有限分量: %r" % (node[:2],))
        return None
    for index, component in enumerate(node):
        digits = fraction_digits(component)
        if digits > audit.max_fraction_digits:
            audit.max_fraction_digits = digits
        if digits > PRECISION_MAX_FRACTION_DIGITS and len(audit.precision_samples) < PRECISION_SAMPLES_CAP:
            audit.precision_samples.append({"component": index, "value": str(component), "fraction_digits": digits})
    audit.points.append((lon, lat))
    return (lon, lat)


def _collect(node: object, depth: int, audit: FileAudit) -> Any:
    if depth == 0:
        return _leaf(node, audit)
    if not isinstance(node, list):
        _issue(audit, "坐标数组形态非法（该层级应为数组）", expected_depth=depth)
        return None
    return [_collect(child, depth - 1, audit) for child in node]


def _flatten_pairs(node: Any) -> List[Tuple[float, float]]:
    if node is None:
        return []
    if isinstance(node, tuple):
        return [node]
    out: List[Tuple[float, float]] = []
    for child in node:
        out.extend(_flatten_pairs(child))
    return out


def shoelace_sign(pairs: List[Tuple[float, float]]) -> int:
    """环方向：+1 逆时针（CCW）/ -1 顺时针（CW）/ 0 退化。闭式 Shoelace。"""
    if len(pairs) < 3:
        return 0
    total = 0.0
    for index, (x1, y1) in enumerate(pairs):
        x2, y2 = pairs[(index + 1) % len(pairs)]
        total += x1 * y2 - x2 * y1
    if total > 0:
        return 1
    if total < 0:
        return -1
    return 0


def _polygons(tree: Any, geometry_type: str) -> List[Any]:
    if geometry_type == "Polygon":
        return [tree] if isinstance(tree, list) else []
    if geometry_type == "MultiPolygon":
        return [poly for poly in tree if isinstance(poly, list)] if isinstance(tree, list) else []
    return []


def _audit_rings(tree: Any, geometry_type: str, audit: FileAudit) -> None:
    """Polygon / MultiPolygon 的环方向判定（R1）；违规只记录，级别在 check_ring_order。"""
    for polygon_index, polygon in enumerate(_polygons(tree, geometry_type)):
        rings = polygon if isinstance(polygon, list) else []
        for ring_index, ring in enumerate(rings):
            if not isinstance(ring, list):
                continue
            pairs = [pair for pair in ring if isinstance(pair, tuple)]
            if len(pairs) != len(ring):
                continue
            role = "exterior" if ring_index == 0 else "hole"
            sign = shoelace_sign(pairs)
            record: Dict[str, Any] = {
                "file": audit.name, "geometry": geometry_type, "polygon": polygon_index,
                "ring": role, "index": ring_index, "sign": sign,
            }
            audit.ring_signs.append(record)
            if sign == 0:
                _issue(audit, "环退化（Shoelace 面积为 0）：%s ring #%d" % (role, ring_index),
                       polygon=polygon_index, ring=role)
                continue
            expected = 1 if role == "exterior" else -1
            if sign != expected:
                audit.ring_violations.append({**record, "expected": expected})


def bbox_contains(west: float, south: float, east: float, north: float, lon: float, lat: float) -> bool:
    """bbox 包含判定。west > east 时按跨 180° 解读（RFC 7946 §7.1 / §5.2）。"""
    if not (south <= lat <= north):
        return False
    if west <= east:
        return west <= lon <= east
    return lon >= west or lon <= east


def audit_bbox_member(raw: object, points: List[Tuple[float, float]], audit: FileAudit, where: str) -> None:
    """bbox 成员：长度 / 顺序 / 与真实外包框一致 / 跨 180° 合法性。"""
    if not isinstance(raw, list) or len(raw) not in (4, 6):
        length = len(raw) if isinstance(raw, list) else None
        _issue(audit, "bbox 长度必须为 4 或 6", bbox_length=length, allowed=[4, 6], where=where)
        return
    values = [_number(item) for item in raw]
    if any(value is None for value in values):
        _issue(audit, "bbox 含非数值或非有限分量", where=where)
        return
    numeric = [float(value) for value in values]
    if len(numeric) == 4:
        west, south, east, north = numeric
        extra: Dict[str, Any] = {}
    else:
        west, south, minz, east, north, maxz = numeric
        extra = {"minz": minz, "maxz": maxz}
    problems: List[str] = []
    if south > north:
        problems.append("south > north，违反 [west, south, east, north] 顺序")
    outside = [point for point in points if not bbox_contains(west, south, east, north, point[0], point[1])]
    if points and outside:
        problems.append("%d/%d 个坐标落在声明 bbox 之外（bbox 与几何真实外包框不一致）" % (len(outside), len(points)))
    record: Dict[str, Any] = {
        "file": audit.name, "where": where, "bbox": numeric,
        "west_greater_than_east": west > east, "problems": problems, **extra,
    }
    if outside:
        record["outside_sample"] = list(outside[0])
    audit.bbox_members.append(record)


def _geometry(geom: object, audit: FileAudit, depth: int = 0) -> List[Tuple[float, float]]:
    """递归审计一个几何对象，返回它覆盖的坐标点。"""
    if geom is None:
        return []
    if not isinstance(geom, dict):
        _issue(audit, "几何对象必须是 JSON object 或 null", value_type=type(geom).__name__)
        return []
    geometry_type = geom.get("type")
    if not isinstance(geometry_type, str) or geometry_type not in GEOMETRY_TYPES:
        _issue(audit, "未知几何类型: %r" % (geometry_type,), geometry_type=geometry_type)
        return []
    audit.geometry_types.append(geometry_type)
    points: List[Tuple[float, float]] = []
    if geometry_type == "GeometryCollection":
        children = geom.get("geometries")
        if not isinstance(children, list):
            _issue(audit, "GeometryCollection.geometries 必须是数组")
            children = []
        audit.nesting_depth = max(audit.nesting_depth, depth + 1)
        for child in children:
            points.extend(_geometry(child, audit, depth + 1))
    else:
        coordinates = geom.get("coordinates")
        if coordinates is None:
            _issue(audit, "%s 缺少 coordinates 成员" % geometry_type, geometry_type=geometry_type)
        else:
            tree = _collect(coordinates, GEOMETRY_DIMS[geometry_type], audit)
            points = _flatten_pairs(tree)
            if geometry_type in {"Polygon", "MultiPolygon"}:
                _audit_rings(tree, geometry_type, audit)
    if "bbox" in geom:
        audit_bbox_member(geom["bbox"], points, audit, "geometry:%s" % geometry_type)
    return points


def _feature(feature: object, audit: FileAudit, index: int) -> List[Tuple[float, float]]:
    if not isinstance(feature, dict):
        _issue(audit, "features[%d] 必须是 JSON object" % index, feature_index=index)
        return []
    if feature.get("type") != "Feature":
        _issue(audit, "features[%d].type 应为 Feature（实得 %r）" % (index, feature.get("type")), feature_index=index)
        return []
    properties = feature.get("properties", _MISSING)
    if properties is _MISSING:
        _issue(audit, "Feature 缺少 properties 成员（RFC 7946 §3.2：可为 null）", feature_index=index)
    elif properties is None:
        audit.null_properties += 1
    elif not isinstance(properties, dict):
        _issue(audit, "Feature.properties 必须是 JSON object 或 null", feature_index=index)
    if "geometry" not in feature:
        _issue(audit, "Feature 缺少 geometry 成员（RFC 7946 §3.2：可为 null）", feature_index=index)
        return []
    geometry = feature.get("geometry")
    if geometry is None:
        audit.null_geometries += 1
        return []
    points = _geometry(geometry, audit)
    if "bbox" in feature:
        audit_bbox_member(feature["bbox"], points, audit, "feature[%d]" % index)
    return points


def audit_document(name: str, data: Any) -> FileAudit:
    """审计一个解析后的 GeoJSON 文档（不读文件；Decimal 解析由输入层做）。"""
    audit = FileAudit.empty(name)
    if not isinstance(data, dict):
        _issue(audit, "顶层应为 GeoJSON object")
        return audit
    top_type = data.get("type")
    audit.top_type = top_type if isinstance(top_type, str) else None
    if top_type not in TOP_TYPES:
        _issue(audit, "未知 GeoJSON type: %r" % (top_type,), type=top_type)
        return audit
    audit.has_crs = "crs" in data
    points: List[Tuple[float, float]] = []
    if top_type == "FeatureCollection":
        features = data.get("features")
        if not isinstance(features, list):
            _issue(audit, "FeatureCollection.features 必须是数组")
            features = []
        for index, feature in enumerate(features):
            points.extend(_feature(feature, audit, index))
    elif top_type == "Feature":
        points.extend(_feature(data, audit, 0))
    else:
        points.extend(_geometry(data, audit))
    if "bbox" in data:
        audit_bbox_member(data["bbox"], points, audit, str(top_type))
    return audit


# ------------------------------------------------------------------ 七项检查
def ring_order_status(strict_ring: bool) -> str:
    """R1 违规的级别由 R2 决定：R2 的容忍语义在 → warning；不在 → error。"""
    if strict_ring:
        return RING_ORDER_STRICT_STATUS
    if R2_TOLERANCE_MARKER not in RFC_R2:
        return RING_ORDER_STRICT_STATUS
    return RING_ORDER_DEFAULT_STATUS


def check_ring_order(audits: List[FileAudit], strict_ring: bool) -> Finding:
    violations = [record for audit in audits for record in audit.ring_violations]
    signs = [record for audit in audits for record in audit.ring_signs]
    evidence: Dict[str, Any] = {
        "rule": "RFC 7946 §3.1.6", "r1": RFC_R1, "r2": RFC_R2, "strict_ring": strict_ring,
        "rings_checked": len(signs), "violations": len(violations),
    }
    if violations:
        status = ring_order_status(strict_ring)
        first = violations[0]
        detail = (
            "%d 个环违反 R1（右手法则：外环逆时针、洞顺时针；首个为 %s 的 %s ring，Shoelace 符号 %d）；"
            "按 R2（for backwards compatibility, parsers SHOULD NOT reject…）报告不放弃、"
            "但级别默认为 %s，--strict-ring 是唯一升 error 的路径"
            % (len(violations), first["file"], first["ring"], first["sign"], RING_ORDER_DEFAULT_STATUS)
        )
        evidence["samples"] = violations[:PRECISION_SAMPLES_CAP]
        return Finding(check="ring_order", status=status, reason=REASON_RING, detail=detail, evidence=evidence)
    if not signs:
        return Finding(check="ring_order", status=STATUS_INFO,
                       detail="没有 Polygon / MultiPolygon 环可判（R1 不适用）", evidence=evidence)
    return Finding(check="ring_order", status=STATUS_CONSISTENT,
                   detail="%d 个环全部符合 R1（外环逆时针、洞顺时针）" % len(signs), evidence=evidence)


def check_axis(audits: List[FileAudit]) -> Finding:
    points = [point for audit in audits for point in audit.points]
    evidence: Dict[str, Any] = {"rule": "RFC 7946 §3.1.1", "coordinates": len(points)}
    if not points:
        return Finding(check="axis", status=STATUS_INFO, detail="没有坐标对可判轴序", evidence=evidence)
    swapped = [point for point in points if abs(point[1]) > 90 and abs(point[0]) <= 90]
    if swapped:
        evidence["sample"] = list(swapped[0])
        evidence["affected"] = len(swapped)
        return Finding(check="axis", status=STATUS_WARNING, reason=REASON_AXIS,
                       detail="%d/%d 个坐标对的第二分量越出纬度域（> 90°）而第一分量仍在经度域（样本 %s）→ 呈 (lat, lon) 排列，RFC 7946 要求 (lon, lat)"
                              % (len(swapped), len(points), list(swapped[0])),
                       evidence=evidence)
    lon_clear = [point for point in points if abs(point[0]) > 90]
    if lon_clear:
        evidence["sample"] = list(lon_clear[0])
        return Finding(check="axis", status=STATUS_CONSISTENT,
                       detail="%d 个坐标对的第一分量越出纬度域 → 只能是经度，轴序呈 (lon, lat)" % len(lon_clear),
                       evidence=evidence)
    return Finding(check="axis", status=STATUS_INFO,
                   detail="全部坐标分量都落在 ±90 内，无法区分 (lon, lat) 与 (lat, lon)", evidence=evidence)


def check_bbox(audits: List[FileAudit]) -> Finding:
    members = [record for audit in audits for record in audit.bbox_members]
    evidence: Dict[str, Any] = {"rule": "RFC 7946 §7.1 / §5.2", "bbox_members": len(members), "members": members}
    if not members:
        return Finding(check="bbox", status=STATUS_INFO, detail="没有 bbox 成员", evidence=evidence)
    warned = [record for record in members if record["problems"]]
    if warned:
        first = warned[0]
        return Finding(check="bbox", status=STATUS_WARNING, reason=REASON_BBOX,
                       detail="%d/%d 个 bbox 成员与几何不一致：%s —— %s"
                              % (len(warned), len(members), first["where"], "；".join(first["problems"])),
                       evidence={**evidence, "problems": warned[:PRECISION_SAMPLES_CAP]})
    crossing = [record for record in members if record["west_greater_than_east"]]
    if crossing:
        return Finding(check="bbox", status=STATUS_INFO,
                       detail="%d 个 bbox 呈 west > east（跨 180°）——RFC 7946 §7.1 / §5.2（R4）明确合法，不是错误" % len(crossing),
                       evidence={**evidence, "crossing": crossing[:PRECISION_SAMPLES_CAP]})
    return Finding(check="bbox", status=STATUS_CONSISTENT,
                   detail="%d 个 bbox 成员与几何外包框一致" % len(members), evidence=evidence)


def check_nesting(audits: List[FileAudit]) -> Finding:
    depth = max((audit.nesting_depth for audit in audits), default=0)
    evidence: Dict[str, Any] = {
        "rule": "RFC 7946 §3.1", "max_depth": depth,
        "geometry_collections": sum(1 for audit in audits for kind in audit.geometry_types if kind == "GeometryCollection"),
    }
    if depth:
        return Finding(check="nesting", status=STATUS_INFO,
                       detail="GeometryCollection 最大嵌套深度 %d，类型自洽" % depth, evidence=evidence)
    return Finding(check="nesting", status=STATUS_CONSISTENT, detail="没有 GeometryCollection 嵌套", evidence=evidence)


def check_null_geometry(audits: List[FileAudit]) -> Finding:
    null_geometries = sum(audit.null_geometries for audit in audits)
    null_properties = sum(audit.null_properties for audit in audits)
    evidence: Dict[str, Any] = {
        "rule": "RFC 7946 §3.2", "null_geometries": null_geometries, "null_properties": null_properties,
    }
    if null_geometries or null_properties:
        return Finding(check="null_geometry", status=STATUS_INFO,
                       detail="geometry: null 的 Feature %d 个、properties: null 的 %d 个——RFC 7946 §3.2 明确合法（unlocated feature），只做提示，不进 exit 4"
                              % (null_geometries, null_properties),
                       evidence=evidence)
    return Finding(check="null_geometry", status=STATUS_CONSISTENT,
                   detail="没有 geometry: null / properties: null 的 Feature", evidence=evidence)


def check_crs_member(audits: List[FileAudit]) -> Finding:
    files = [audit.name for audit in audits if audit.has_crs]
    evidence: Dict[str, Any] = {
        "rule": "RFC 7946 §4 与 Appendix B.1", "source": "RFC 7946 §4 / Appendix B.1",
        "files": files, "wording": CRS_REMOVED_WORDING,
    }
    if files:
        return Finding(check="crs_member", status=STATUS_WARNING, reason="crs",
                       detail="%d 个文件声明了 crs 成员：%s；RFC 7946 §4 同时留了活口：%s"
                              % (len(files), CRS_REMOVED_WORDING, CRS_PRIOR_ARRANGEMENT),
                       evidence=evidence)
    return Finding(check="crs_member", status=STATUS_CONSISTENT, detail="没有文件使用 crs 成员", evidence=evidence)


def check_precision(audits: List[FileAudit]) -> Finding:
    max_digits = max((audit.max_fraction_digits for audit in audits), default=0)
    samples = [sample for audit in audits for sample in audit.precision_samples]
    evidence: Dict[str, Any] = {
        "rule": "data/README.md §4.6", "max_fraction_digits": max_digits,
        "threshold_digits": PRECISION_MAX_FRACTION_DIGITS, "samples": samples[:PRECISION_SAMPLES_CAP],
    }
    if max_digits > PRECISION_MAX_FRACTION_DIGITS:
        return Finding(check="precision", status=STATUS_WARNING, reason="precision",
                       detail="单分量小数位最多 %d 位，超过阈值 %d 位（9 位十进制 ≈ 0.1 mm，对任何地表坐标无意义）"
                              % (max_digits, PRECISION_MAX_FRACTION_DIGITS),
                       evidence=evidence)
    return Finding(check="precision", status=STATUS_CONSISTENT,
                   detail="单分量小数位最多 %d 位，未超阈值 %d 位" % (max_digits, PRECISION_MAX_FRACTION_DIGITS),
                   evidence=evidence)


def verdict_of(findings: List[Finding]) -> str:
    errors = [f.check for f in findings if f.status == STATUS_ERROR]
    if errors:
        return "结构错误：" + "、".join(errors)
    warnings = [f.check for f in findings if f.status == STATUS_WARNING]
    if warnings:
        return "结构与声明审计有提示项：" + "、".join(warnings)
    infos = [f.check for f in findings if f.status == STATUS_INFO]
    if infos:
        return "结构自洽（信息项：" + "、".join(infos) + "）"
    return "结构自洽（七项检查均未命中）"


def run_geojson(documents: List[Tuple[str, Any]], strict_ring: bool = False) -> dict:
    """GeoJSON 审计入口。documents = [(名字, 解析后的文档)]；结构性问题进 issues（error 级）。"""
    audits = [audit_document(name, data) for name, data in documents]
    issues = [issue for audit in audits for issue in audit.issues]
    findings = [
        check_ring_order(audits, strict_ring),
        check_axis(audits),
        check_bbox(audits),
        check_nesting(audits),
        check_null_geometry(audits),
        check_crs_member(audits),
        check_precision(audits),
    ]
    payload: Dict[str, Any] = {
        "verdict": verdict_of(findings),
        "strict_ring": strict_ring,
        "files": [
            {
                "name": audit.name,
                "type": audit.top_type,
                "geometry_types": sorted(set(audit.geometry_types)),
                "coordinates": len(audit.points),
                "rings": audit.ring_signs,
                "ring_violations": audit.ring_violations,
                "bbox_members": audit.bbox_members,
                "max_fraction_digits": audit.max_fraction_digits,
                "null_geometry": audit.null_geometries,
                "null_properties": audit.null_properties,
                "nesting_depth": audit.nesting_depth,
                "has_crs": audit.has_crs,
            }
            for audit in audits
        ],
        "counts": {
            "files": len(audits),
            "coordinates": sum(len(audit.points) for audit in audits),
            "rings": sum(len(audit.ring_signs) for audit in audits),
            "ring_violations": sum(len(audit.ring_violations) for audit in audits),
        },
        "findings": [f.as_dict() for f in findings],
        "structure_issues": [f.as_dict() for f in issues],
    }
    return payload
