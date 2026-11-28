"""M1 声明-内容一致性（照搬旧仓 ``decl.py`` 的五项检查；输入为解析后的样本对）。

判定顺序固定：量级 → 轴序 → 单位 → 混用 → 范围。一项一责：每个检查只回答一件事。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .finding import (
    STATUS_CONFLICT,
    STATUS_CONSISTENT,
    STATUS_INFO,
    STATUS_UNDECIDABLE,
    Finding,
)

CHECKS: Tuple[str, ...] = ("magnitude", "axis", "unit", "mixed", "extent")

DECLARED_CRS_CHOICES: Tuple[str, ...] = ("4326", "3857", "4490", "crs84")
#: GCJ-02 / BD-09 不在其中：没有 EPSG 代码，只能作为 detect 的检测假设。

DEGREE_MAX = 180.0
METRE_MIN = 1_000_000.0
LAT_RANGE_MAX = 90.0
MIN_AXIS_SAMPLES = 5
DEGREE_DECLARED: Tuple[str, ...] = ("4326", "4490", "crs84")

BAND_DEGREE = "degree"
BAND_METRE = "metre"
BAND_NEITHER = "neither"

_FILE_CRS_ALIASES: Dict[str, str] = {
    "crs84": "crs84",
    "ogc:crs84": "crs84",
    "urn:ogc:def:crs:ogc:1.3:crs84": "crs84",
    "urn:ogc:def:crs:ogc::crs84": "crs84",
    "urn:ogc:def:crs:epsg::4326": "4326",
    "urn:ogc:def:crs:epsg:6.6:4326": "4326",
    "epsg:4326": "4326",
    "wgs84": "4326",
    "urn:ogc:def:crs:epsg::3857": "3857",
    "epsg:3857": "3857",
    "epsg:900913": "3857",
    "urn:ogc:def:crs:epsg::4490": "4490",
    "epsg:4490": "4490",
    "cgcs2000": "4490",
}

SOURCE_CLI = "cli"
SOURCE_FILE = "file"
SOURCE_FILE_UNRECOGNISED = "file-unrecognised"
SOURCE_NONE = "none"


class UsageError(ValueError):
    """非法声明值（旧仓 exit 2 → 本账本 ValueError → rc2）。"""


@dataclass(frozen=True)
class Sample:
    """一对坐标。a/b 保持**文件里的分量顺序**——轴序判定正是要判这个顺序。"""

    seq: int
    a: float
    b: float

    @property
    def magnitude(self) -> float:
        return max(abs(self.a), abs(self.b))

    @property
    def band(self) -> str:
        if self.magnitude <= DEGREE_MAX:
            return BAND_DEGREE
        if self.magnitude >= METRE_MIN:
            return BAND_METRE
        return BAND_NEITHER

    @property
    def pair(self) -> List[float]:
        return [self.a, self.b]


def normalize_declared(raw: Optional[str]) -> Optional[str]:
    """声明值归一成四值枚举；认不出返回 None（不猜）。"""
    if raw is None:
        return None
    key = raw.strip().lower()
    if key in DECLARED_CRS_CHOICES:
        return key
    return _FILE_CRS_ALIASES.get(key)


def resolve_declared(cli_value: Optional[str], file_value: Optional[str]) -> Tuple[Optional[str], str]:
    """CLI 声明优先于文件内 crs 成员；非法 CLI 值拦一道（UsageError → rc2）。"""
    if cli_value is not None:
        if cli_value not in DECLARED_CRS_CHOICES:
            raise UsageError(
                "非法的 --declared-crs: %r" % cli_value,
            )
        return cli_value, SOURCE_CLI
    if file_value is not None:
        normalised = normalize_declared(file_value)
        if normalised is None:
            return None, SOURCE_FILE_UNRECOGNISED
        return normalised, SOURCE_FILE
    return None, SOURCE_NONE


def _bands(samples: List[Sample]) -> Dict[str, int]:
    return dict(sorted(Counter(s.band for s in samples).items()))


def check_magnitude(samples: List[Sample], declared: Optional[str]) -> Finding:
    """量级：声明是度制而 m > 180 → conflict/magnitude。"""
    if not samples:
        return Finding(check="magnitude", status=STATUS_UNDECIDABLE, reason="insufficient_samples",
                       detail="没有任何坐标样本，量级无从判定", evidence={"rule": "data/README.md §4.1", "samples": 0})
    bands = _bands(samples)
    worst = max(s.magnitude for s in samples)
    evidence: Dict[str, Any] = {
        "rule": "data/README.md §4.1",
        "declared_crs": declared or "none",
        "magnitude_m": round(worst, 6),
        "bands": bands,
        "degree_max": DEGREE_MAX,
        "metre_min": METRE_MIN,
    }
    if declared is None:
        return Finding(check="magnitude", status=STATUS_INFO,
                       detail="无声明值可比；最大量级 %g，分档 %s" % (worst, bands), evidence=evidence)
    if declared in DEGREE_DECLARED:
        if worst > DEGREE_MAX:
            return Finding(check="magnitude", status=STATUS_CONFLICT, reason="magnitude",
                           detail="声明为度制（%s），但最大量级 %g 超过度域上限 %g" % (declared, worst, DEGREE_MAX),
                           evidence=evidence)
        return Finding(check="magnitude", status=STATUS_CONSISTENT,
                       detail="声明为度制（%s），最大量级 %g 在度域内" % (declared, worst), evidence=evidence)
    if bands.get(BAND_METRE) and len(bands) == 1:
        return Finding(check="magnitude", status=STATUS_CONSISTENT,
                       detail="声明 3857（米制），全部样本量级在米域", evidence=evidence)
    if bands.get(BAND_NEITHER) and len(bands) == 1:
        return Finding(check="magnitude", status=STATUS_UNDECIDABLE,
                       detail="声明 3857，但全部样本落在中间带（%g < m < %g）" % (DEGREE_MAX, METRE_MIN),
                       evidence=evidence)
    return Finding(check="magnitude", status=STATUS_INFO,
                   detail="声明 3857；量级分档 %s，矛盾由 unit / mixed 项给出" % bands, evidence=evidence)


def decidable_samples(samples: List[Sample]) -> List[Sample]:
    """可判定样本 = 两分量都在 ±180 内（米域样本天然被排除）。"""
    return [s for s in samples if abs(s.a) <= DEGREE_MAX and abs(s.b) <= DEGREE_MAX]


def check_axis(samples: List[Sample], declared: Optional[str]) -> Tuple[Finding, bool]:
    """轴序：只用可判定样本；< 5 → undecidable(insufficient_samples)。"""
    decidable = decidable_samples(samples)
    evidence: Dict[str, Any] = {
        "rule": "data/README.md §4.1",
        "total_samples": len(samples),
        "decidable_samples": len(decidable),
        "min_decidable_samples": MIN_AXIS_SAMPLES,
    }
    if declared == "3857":
        return (Finding(check="axis", status=STATUS_INFO,
                        detail="声明为投影坐标系（3857），经度/纬度域判据不适用", evidence=evidence), False)
    if len(decidable) < MIN_AXIS_SAMPLES:
        return (Finding(check="axis", status=STATUS_UNDECIDABLE, reason="insufficient_samples",
                        detail="可判定样本 %d 个，低于下限 %d，不得凭少量点下结论" % (len(decidable), MIN_AXIS_SAMPLES),
                        evidence=evidence), False)
    swapped = [s for s in decidable if abs(s.b) > LAT_RANGE_MAX and abs(s.a) <= LAT_RANGE_MAX]
    if swapped:
        first = swapped[0]
        return (Finding(check="axis", status=STATUS_CONFLICT, reason="axis",
                        detail="%d/%d 个可判定样本的第二分量越出纬度域（±%g），而第一分量仍在经度域内 → 呈 (lat, lon) 排列"
                               % (len(swapped), len(decidable), LAT_RANGE_MAX),
                        evidence={**evidence, "affected_samples": len(swapped), "sample": first.pair,
                                  "corrected_sample": [first.b, first.a]}), True)
    normal = [s for s in decidable if abs(s.a) > LAT_RANGE_MAX and abs(s.b) <= LAT_RANGE_MAX]
    if normal:
        return (Finding(check="axis", status=STATUS_CONSISTENT,
                        detail="%d 个可判定样本的第一分量越出纬度域 → 只能是经度，轴序呈 (lon, lat)" % len(normal),
                        evidence={**evidence, "affected_samples": len(normal), "sample": normal[0].pair}), True)
    return (Finding(check="axis", status=STATUS_UNDECIDABLE,
                    detail="全部可判定样本都落在 ±90 内，无法区分 (lon, lat) 与 (lat, lon)",
                    evidence=evidence), False)


def check_unit(samples: List[Sample], declared: Optional[str]) -> Finding:
    """单位：declared = 3857 且量级在度域 → conflict/unit。"""
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.1", "declared_crs": declared or "none"}
    if declared != "3857":
        return Finding(check="unit", status=STATUS_INFO,
                       detail="unit 项只对 --declared-crs 3857 生效；本次声明不是 3857", evidence=evidence)
    if not samples:
        return Finding(check="unit", status=STATUS_UNDECIDABLE, reason="insufficient_samples",
                       detail="没有任何坐标样本，单位无从判定", evidence=evidence)
    degree_pts = [s for s in samples if s.band == BAND_DEGREE]
    evidence["degree_domain_samples"] = len(degree_pts)
    evidence["samples"] = len(samples)
    if degree_pts:
        return Finding(check="unit", status=STATUS_CONFLICT, reason="unit",
                       detail="声明 3857（米），但有 %d/%d 个样本量级 ≤ %g（度域），单位与声明不相容"
                              % (len(degree_pts), len(samples), DEGREE_MAX),
                       evidence=evidence)
    return Finding(check="unit", status=STATUS_CONSISTENT,
                   detail="声明 3857，没有样本落在度域（分档 %s）" % _bands(samples), evidence=evidence)


def check_mixed(samples: List[Sample]) -> Finding:
    """混用：同一批数据内量级分档冲突 → conflict/mixed。"""
    bands = _bands(samples)
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.1", "bands": bands}
    if not samples:
        return Finding(check="mixed", status=STATUS_INFO, detail="没有任何坐标样本，无混用可判", evidence=evidence)
    if bands.get(BAND_DEGREE) and bands.get(BAND_METRE):
        return Finding(check="mixed", status=STATUS_CONFLICT, reason="mixed",
                       detail="同一批数据内同时出现度域（%d 个）与米域（%d 个）样本，量级分档冲突"
                              % (bands[BAND_DEGREE], bands[BAND_METRE]),
                       evidence=evidence)
    return Finding(check="mixed", status=STATUS_CONSISTENT, detail="量级分档一致：%s" % bands, evidence=evidence)


def _bbox_pairs(samples: List[Sample]) -> Optional[List[float]]:
    if not samples:
        return None
    aa = [s.a for s in samples]
    bb = [s.b for s in samples]
    return [round(min(aa), 9), round(min(bb), 9), round(max(aa), 9), round(max(bb), 9)]


def _decode(s: Sample, axis_orientation: Optional[str]) -> Tuple[float, float]:
    """按已判定的轴序把一对分量读成 (lon, lat)；轴序未定时保持文件顺序。"""
    return (s.b, s.a) if axis_orientation == "lat_lon" else (s.a, s.b)


def check_extent(
    samples: List[Sample], declared: Optional[str], axis_orientation: Optional[str],
    webmercator_max: float,
) -> Tuple[Finding, List[str]]:
    """范围：外包框与声明 CRS 的定义域是否相容；判不出时必须给候选建议。"""
    from .algorithms import WEBMERCATOR_MAX

    webmercator_max = WEBMERCATOR_MAX
    candidates: List[str] = []
    evidence: Dict[str, Any] = {"rule": "data/README.md §4.1", "declared_crs": declared or "none"}
    if axis_orientation:
        evidence["axis_orientation"] = axis_orientation
    if declared is None:
        evidence["bbox"] = _bbox_pairs(samples)
        return (Finding(check="extent", status=STATUS_INFO,
                        detail=("无声明值；外包框 %s" % evidence["bbox"]) if samples else "无声明值且无样本",
                        evidence=evidence), candidates)
    if declared in DEGREE_DECLARED:
        degree_pts = [s for s in samples if s.band == BAND_DEGREE]
        evidence["degree_domain_samples"] = len(degree_pts)
        if not degree_pts:
            candidates = ["3857"]
            evidence["bbox"] = _bbox_pairs(samples)
            return (Finding(check="extent", status=STATUS_UNDECIDABLE,
                            detail="声明为地理坐标系，但没有任何样本落在度域；外包框与声明不相容，量级上看更像 3857 米域",
                            evidence={**evidence, "candidates": candidates}), candidates)
        pairs = [_decode(s, axis_orientation) for s in degree_pts]
        lons = [p[0] for p in pairs]
        lats = [p[1] for p in pairs]
        bbox = [round(min(lons), 9), round(min(lats), 9), round(max(lons), 9), round(max(lats), 9)]
        evidence["bbox_lon_lat"] = bbox
        out_of_range = [p for p in pairs if abs(p[0]) > 180.0 or abs(p[1]) > LAT_RANGE_MAX]
        if out_of_range:
            evidence["out_of_range_samples"] = len(out_of_range)
            return (Finding(check="extent", status=STATUS_CONFLICT,
                            detail="声明为地理坐标系（%s），但按当前轴序读出的外包框 %s 越出 ±180 / ±%g，有 %d 个样本越界"
                                   % (declared, bbox, LAT_RANGE_MAX, len(out_of_range)),
                            evidence=evidence), candidates)
        note = ("（按 axis 项判定的 %s 顺序读取）" % axis_orientation) if axis_orientation else "（轴序未定，按文件顺序读取）"
        return (Finding(check="extent", status=STATUS_CONSISTENT,
                        detail="度域样本外包框 %s 落在 ±180 / ±%g 内%s" % (bbox, LAT_RANGE_MAX, note),
                        evidence=evidence), candidates)
    metre_pts = [s for s in samples if s.band == BAND_METRE]
    evidence["metre_domain_samples"] = len(metre_pts)
    evidence["bbox"] = _bbox_pairs(metre_pts)
    if not metre_pts:
        candidates = list(DEGREE_DECLARED)
        return (Finding(check="extent", status=STATUS_UNDECIDABLE,
                        detail="声明 3857（米），但没有任何样本落在米域；外包框与声明不相容，量级上看更像度制",
                        evidence={**evidence, "candidates": candidates}), candidates)
    if any(abs(s.a) > webmercator_max or abs(s.b) > webmercator_max for s in metre_pts):
        return (Finding(check="extent", status=STATUS_CONFLICT,
                        detail="声明 3857，但外包框 %s 越出 Web Mercator 全球范围 ±%g m" % (evidence["bbox"], webmercator_max),
                        evidence={**evidence, "webmercator_max_m": webmercator_max}), candidates)
    return (Finding(check="extent", status=STATUS_CONSISTENT,
                    detail="米域样本外包框 %s 落在 Web Mercator 全球范围内" % evidence["bbox"],
                    evidence=evidence), candidates)


def verdict_of(findings: List[Finding]) -> str:
    conflicts = [f.check for f in findings if f.status == STATUS_CONFLICT]
    if conflicts:
        return "声明与内容不一致：" + "、".join(conflicts)
    undecided = [f.check for f in findings if f.status == STATUS_UNDECIDABLE]
    if undecided:
        return "结论不可判定（需人工介入）：" + "、".join(undecided)
    return "声明与内容相容（五项检查均未命中）"


def run_decl(samples: List[Sample], declared_crs: Optional[str], file_crs: Optional[str] = None, strict: bool = False) -> dict:
    """判定入口。判定顺序固定为 CHECKS 的顺序；strict 把"无声明可比"升为 undecidable。"""
    declared, source = resolve_declared(declared_crs, file_crs)
    findings: List[Finding] = []
    findings.append(check_magnitude(samples, declared))
    axis_finding, axis_decidable = check_axis(samples, declared)
    findings.append(axis_finding)
    findings.append(check_unit(samples, declared))
    findings.append(check_mixed(samples))
    axis_orientation: Optional[str] = None
    if axis_finding.status == STATUS_CONFLICT:
        axis_orientation = "lat_lon"
    elif axis_finding.status == STATUS_CONSISTENT:
        axis_orientation = "lon_lat"
    extent_finding, candidates = check_extent(samples, declared, axis_orientation, 0.0)
    findings.append(extent_finding)

    if strict and declared is None:
        steered: List[Finding] = []
        for f in findings:
            if f.status == STATUS_INFO and f.check in {"magnitude", "unit", "extent"}:
                steered.append(Finding(check=f.check, status=STATUS_UNDECIDABLE, reason=None,
                                       detail="--strict：无声明值即不可判定（原判：%s）" % f.detail,
                                       evidence=dict(f.evidence, strict=True)))
            else:
                steered.append(f)
        findings = steered

    payload: Dict[str, Any] = {
        "declared_crs": declared,
        "declared_crs_source": source,
        "verdict": verdict_of(findings),
        "axis_decidable": axis_decidable,
        "sample_counts": {
            "total": len(samples),
            "decidable": len(decidable_samples(samples)),
            "bands": _bands(samples),
        },
        "candidates": candidates,
        "findings": [f.as_dict() for f in findings],
    }
    if source == SOURCE_FILE_UNRECOGNISED:
        payload["declaration_note"] = (
            "文件内 crs 成员 %r 未登记于本工具的声明枚举，未按声明参与判定（不猜）" % (file_crs,)
        )
    return payload
