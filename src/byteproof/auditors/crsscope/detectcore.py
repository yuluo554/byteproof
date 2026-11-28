"""M2 偏移检测（照搬旧仓 ``detect.py`` 评分核）+ M3 跨实现差分（照搬 ``xdiff.py``）。

落水率判的是**逆变换后的落点**；分母规则只走 MaskStats（unknown 与海岸带不进分母）。
灰区优先：可判定点不足 / 并列第一 / 覆盖率过差都是灰区，不硬判。三段残差固定齐全。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from .algorithms import (
    CT_PY_BBOX,
    GCOORD_BBOX,
    INVERSE_TOLERANCE_DEG,
    PROFILE_CT_PY,
    PROFILE_GCOORD,
    inverse_for,
)
from .finding import (
    STATUS_CONFLICT,
    STATUS_CONSISTENT,
    STATUS_INFO,
    STATUS_UNDECIDABLE,
    STATUS_WARNING,
    Finding,
    MaskStats,
    Mask,
    haversine_m,
)

WEIGHT_BOUNDARY = 0.25
WEIGHT_DECLARED = 0.30
CONFIDENCE_HIGH_MARGIN = 0.15
CONFIDENCE_MEDIUM_MARGIN = 0.05
MIN_EVALUABLE_POINTS = 30
UNKNOWN_COASTAL_MAX_RATIO = 0.8
CONFIDENCE_UNDECIDABLE = "undecidable"
REASON_INSUFFICIENT = "insufficient_samples"
REASON_TIE = "tie"
REASON_OUT_OF_COVERAGE = "out_of_coverage"

#: 掩膜是构造网格，不是地理真值——报告必须同时输出版本与步长上限。
MASK_NOTE = (
    "掩膜为构造网格，不是地理真值；unknown 与海岸带不计入落水分母；"
    "分辨率不足时结论为 undecidable"
)

BOUNDARY_BAND_DEG = 0.05

REASON_BOUNDARY_DIVERGENCE = "boundary_divergence"
REASON_NOT_CONVERGED = "not_converged"
JUMP_REASON = "out_of_china 边界内外跳变"

IMPLEMENTATIONS = ("coordTransform_py", "gcoord", "proj4js_webmercator")
TARGET_CHOICES = ("wgs84", "gcj02", "bd09", "webmercator")
TARGET_IMPLEMENTATIONS: Dict[str, Tuple[str, ...]] = {
    "wgs84": IMPLEMENTATIONS,
    "gcj02": (PROFILE_CT_PY, PROFILE_GCOORD),
    "bd09": (PROFILE_CT_PY, PROFILE_GCOORD),
    "webmercator": ("gcoord", "proj4js_webmercator"),
}
BOUNDARY_PROFILES = (PROFILE_CT_PY, PROFILE_GCOORD)


class UsageError(ValueError):
    """不覆盖的 target（旧仓 exit 2 → 本账本 ValueError → rc2）。"""


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _p95(values: List[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    idx = math.ceil(0.95 * len(ordered)) - 1
    return ordered[max(0, idx)]


def _compass(east: float, north: float) -> Optional[str]:
    if east == 0.0 and north == 0.0:
        return None
    parts = []
    if north > 0:
        parts.append("北")
    elif north < 0:
        parts.append("南")
    if east > 0:
        parts.append("东")
    elif east < 0:
        parts.append("西")
    return "".join(parts)


def _declared_conflict(hypothesis: str, declared: Optional[str]) -> int:
    if declared is None:
        return 0
    if hypothesis == "WGS84":
        return 0 if declared in ("4326", "4490", "crs84") else 1
    if hypothesis == "GCJ02":
        return 0 if declared == "gcj02" else 1
    if hypothesis == "BD09":
        return 0 if declared == "bd09" else 1
    return 0


def distance_to_bbox_deg(lon: float, lat: float, bbox: dict) -> float:
    from .algorithms import distance_to_bbox_deg as _d

    return _d(lon, lat, bbox)


@dataclass
class Boundary:
    """边界带（距任一库边界 < 0.05°）与两库结论分歧。"""

    near_band: bool
    per_point_disagree: List[bool]
    per_point_near: List[bool]


def boundary_analysis(points: List[Tuple[float, float]]) -> Boundary:
    per_disagree: List[bool] = []
    per_near: List[bool] = []
    for lon, lat in points:
        ct = CT_PY_BBOX if PROFILE_CT_PY in BOUNDARY_PROFILES else None
        gc = GCOORD_BBOX if PROFILE_GCOORD in BOUNDARY_PROFILES else None
        d_ct = distance_to_bbox_deg(lon, lat, ct) if ct else 0.0
        d_gc = distance_to_bbox_deg(lon, lat, gc) if gc else 0.0
        per_near.append(min(d_ct, d_gc) < BOUNDARY_BAND_DEG)
        agree = in_china_ct(lon, lat) == in_china_gc(lon, lat)
        per_disagree.append(not agree)
    return Boundary(near_band=any(per_near), per_point_disagree=per_disagree, per_point_near=per_near)


def in_china_ct(lon: float, lat: float) -> bool:
    from .algorithms import in_bbox

    return in_bbox(lon, lat, CT_PY_BBOX)


def in_china_gc(lon: float, lat: float) -> bool:
    from .algorithms import in_bbox

    return in_bbox(lon, lat, GCOORD_BBOX)


@dataclass
class Hypothesis:
    """一个候选假设的完整评分。score=None 表示没有任何可判定点，无从打分。"""

    name: str
    score: Optional[float]
    water_ratio: Optional[float]
    stats: MaskStats
    offset_m: float
    p95_offset_m: float
    direction: Optional[str]
    boundary: int
    declared: int
    not_converged: int

    @property
    def evaluable_points(self) -> int:
        return self.stats.evaluable

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score": None if self.score is None else round(self.score, 6),
            "water_ratio": None if self.water_ratio is None else round(self.water_ratio, 6),
            "offset_m": round(self.offset_m, 1),
            "p95_offset_m": round(self.p95_offset_m, 1),
            "direction": self.direction,
            "evaluable_points": self.evaluable_points,
            "boundary": self.boundary,
            "declared_conflict": self.declared,
            "not_converged": self.not_converged,
        }


def evaluate_hypothesis(
    name: str,
    points: List[Tuple[float, float]],
    mask: Mask,
    declared: Optional[str],
    boundary: int,
) -> Hypothesis:
    """对一个假设做完整逆变换并评分。分母规则只走 MaskStats。"""
    stats = MaskStats()
    offsets: List[float] = []
    east = north = 0.0
    not_converged = 0
    for lon, lat in points:
        inv = inverse_for(name, lon, lat)
        if not inv.converged:
            not_converged += 1
        stats.add(mask, inv.lon, inv.lat)
        offsets.append(haversine_m(lon, lat, inv.lon, inv.lat))
        east += inv.lon - lon
        north += inv.lat - lat
    ratio = stats.water_ratio
    conflict = _declared_conflict(name, declared)
    score = None
    if ratio is not None:
        score = (1.0 - ratio) - WEIGHT_BOUNDARY * boundary - WEIGHT_DECLARED * conflict
    return Hypothesis(
        name=name,
        score=score,
        water_ratio=ratio,
        stats=stats,
        offset_m=_median(offsets),
        p95_offset_m=_p95(offsets),
        direction=None if not offsets else _compass(east, north),
        boundary=boundary,
        declared=conflict,
        not_converged=not_converged,
    )


def rank_hypotheses(hypotheses: List[Hypothesis]) -> List[Hypothesis]:
    """score 降序；同分按假设名字典序（BD09 < GCJ02 < WGS84）；无分者殿后。"""
    return sorted(
        hypotheses,
        key=lambda h: (h.score is None, -(h.score if h.score is not None else 0.0), h.name),
    )


def confidence_of(scorable: List[Hypothesis], boundary: Boundary) -> Tuple[str, Optional[float], Optional[str]]:
    """置信档位 + 灰区。灰区优先：不足 / 并列第一 / 覆盖率过差不硬判。"""
    if not scorable:
        return (CONFIDENCE_UNDECIDABLE, None, REASON_INSUFFICIENT)
    top = scorable[0]
    total = top.stats.water + top.stats.land + top.stats.unknown + top.stats.coastal
    if top.evaluable_points < MIN_EVALUABLE_POINTS:
        return (CONFIDENCE_UNDECIDABLE, None, REASON_INSUFFICIENT)
    if total and (top.stats.unknown + top.stats.coastal) / total > UNKNOWN_COASTAL_MAX_RATIO:
        return (CONFIDENCE_UNDECIDABLE, None, REASON_INSUFFICIENT)
    second_score = scorable[1].score if len(scorable) >= 2 else None
    margin = top.score - second_score if second_score is not None else top.score
    if margin is None or margin <= 0.0:
        return (CONFIDENCE_UNDECIDABLE, margin, REASON_TIE)
    if margin >= CONFIDENCE_HIGH_MARGIN:
        confidence = "high"
    elif margin >= CONFIDENCE_MEDIUM_MARGIN:
        confidence = "medium"
    else:
        confidence = "low"
    if boundary.near_band and confidence == "high":
        confidence = "medium"
    return (confidence, margin, None)


def residual_three_parts(winner: Optional[Hypothesis], boundary: Boundary, points: List[Tuple[float, float]]) -> List[dict]:
    """三段残差固定齐全；只说"在某实现假设下的位移"，不说"已还原为真实坐标"。"""
    offset_points = 0
    if winner is not None and winner.offset_m > 0.0:
        offset_points = sum(
            1
            for lon, lat in points
            if inverse_for(winner.name, lon, lat).lon != lon
            or inverse_for(winner.name, lon, lat).lat != lat
        )
    jump_points = sum(1 for dis, near in zip(boundary.per_point_disagree, boundary.per_point_near) if dis or near)
    return [
        {
            "kind": "formula_approximation",
            "detail": "上述偏移是民间公开公式下的近似，不保证等价于未公开的实现；结论只表述为'在某实现假设下的残差与置信'。",
            "affected_points": offset_points,
        },
        {
            "kind": "vendor_divergence",
            "detail": "高德 / Google 中国 / 腾讯等实现的同一坐标可能对应不同的'真值'，实现差异可达米级；本工具不指定唯一真值。",
            "affected_points": offset_points,
        },
        {
            "kind": "boundary_jump",
            "detail": "out_of_china 是硬边界，边界两侧的输出不连续；且 coordTransform_py 与 gcoord 的边界框不同——这是审计发现点，不是任何一方的 bug。",
            "affected_points": jump_points,
        },
    ]


def run_detect(
    points: List[Tuple[float, float]],
    mask: Mask,
    declared: Optional[str] = None,
) -> dict:
    """判定入口（判定顺序固定）。mask 由输入层解析提供（缺失属环境问题，不默认全陆地）。"""
    boundary = boundary_analysis(points)
    boundary_count = sum(1 for near in boundary.per_point_near if near)
    hypotheses = [
        evaluate_hypothesis(name, points, mask, declared, boundary_count)
        for name in ("WGS84", "GCJ02", "BD09")
    ]
    ranked = rank_hypotheses(hypotheses)
    scorable = [h for h in ranked if h.score is not None]
    confidence, margin, gray_reason = confidence_of(scorable, boundary)
    winner = ranked[0] if ranked and ranked[0].score is not None else None
    if winner is None and ranked:
        winner = ranked[0]
    residual = residual_three_parts(ranked[0] if ranked else None, boundary, points)
    return {
        "confidence": confidence,
        "margin": None if margin is None else round(margin, 6),
        "gray_reason": gray_reason,
        "winner": winner.as_dict() if winner else None,
        "hypotheses": [h.as_dict() for h in ranked],
        "residual": residual,
        "mask_note": MASK_NOTE,
        "mask_header": ranked[0].stats.as_header(mask) if ranked else {},
        "boundary_near_band": boundary.near_band,
    }


# ------------------------------------------------------------------ xdiff（M3）
def _identity(lon: float, lat: float) -> "object":
    from .algorithms import InverseResult

    return InverseResult(lon, lat, True, 0)


def implementation_to_wgs84(name: str, target: str, lon: float, lat: float):
    """三个本地实现：输入（target 坐标系）→ WGS84（唯一可比的公共参照系）。"""
    from .algorithms import (
        InverseResult,
        bd09_to_gcj02,
        gcj02_to_wgs84_iterative,
        gcj02_to_wgs84_linear,
        webmercator_to_wgs84,
    )

    if name == "coordTransform_py":
        if target == "wgs84":
            return InverseResult(lon, lat, True, 0)
        if target == "gcj02":
            return gcj02_to_wgs84_linear(lon, lat, PROFILE_CT_PY)
        if target == "bd09":
            g_lon, g_lat = bd09_to_gcj02(lon, lat)
            return gcj02_to_wgs84_linear(g_lon, g_lat, PROFILE_CT_PY)
        raise UsageError("coordTransform_py 不覆盖 target=%r" % target)
    if name == "gcoord":
        if target == "wgs84":
            return InverseResult(lon, lat, True, 0)
        if target == "gcj02":
            return gcj02_to_wgs84_iterative(lon, lat, PROFILE_GCOORD)
        if target == "bd09":
            g_lon, g_lat = bd09_to_gcj02(lon, lat)
            return gcj02_to_wgs84_iterative(g_lon, g_lat, PROFILE_GCOORD)
        if target == "webmercator":
            w_lon, w_lat = webmercator_to_wgs84(lon, lat)
            return InverseResult(w_lon, w_lat, True, 1)
        raise UsageError("gcoord 不覆盖 target=%r" % target)
    if name == "proj4js_webmercator":
        if target == "wgs84":
            return InverseResult(lon, lat, True, 0)
        if target == "webmercator":
            w_lon, w_lat = webmercator_to_wgs84(lon, lat)
            return InverseResult(w_lon, w_lat, True, 0)
        raise UsageError("proj4js_webmercator 不覆盖 target=%r" % target)
    raise UsageError("未知实现: %r" % name)


def run_xdiff(points: List[Tuple[float, float]], target: str) -> dict:
    """跨实现差分。每个实现把输入转成 WGS84；差分在 WGS84 输出之间做（米，§4.4）。"""
    if target not in TARGET_CHOICES:
        raise UsageError("非法 --target: %r" % (target,))
    applicable = [name for name in IMPLEMENTATIONS if name in TARGET_IMPLEMENTATIONS[target]]
    outputs: Dict[str, List[Tuple[float, float]]] = {}
    per_impl_not_converged: Dict[str, List[Tuple[float, float]]] = {}
    for name in applicable:
        converted: List[Tuple[float, float]] = []
        failures: List[Tuple[float, float]] = []
        for lon, lat in points:
            inv = implementation_to_wgs84(name, target, lon, lat)
            if not inv.converged:
                failures.append((lon, lat))
            converted.append((inv.lon, inv.lat))
        outputs[name] = converted
        per_impl_not_converged[name] = failures

    pairwise: List[dict] = []
    for a, b in combinations(applicable, 2):
        oa, ob = outputs[a], outputs[b]
        dists = [haversine_m(pa[0], pa[1], pb[0], pb[1]) for pa, pb in zip(oa, ob)]
        if dists:
            max_idx = max(range(len(dists)), key=lambda i: (dists[i], -i))
            max_at = [points[max_idx][0], points[max_idx][1]]
            max_m = round(dists[max_idx], 1)
        else:
            max_at = None
            max_m = 0.0
        pairwise.append({
            "a": a,
            "b": b,
            "median_m": round(_median(dists), 1),
            "max_m": max_m,
            "p95_m": round(_p95(dists), 1),
            "max_at": max_at,
            "points_compared": len(dists),
        })

    boundary_rows = []
    for lon, lat in points:
        ct = in_china_ct(lon, lat)
        gc = in_china_gc(lon, lat)
        boundary_rows.append({"lon": lon, "lat": lat, "ct_py": ct, "gcoord": gc, "agree": ct == gc})
    jumps = [row for row in boundary_rows if not row["agree"]]
    diverge = [row for row in boundary_rows if not row["agree"]]
    not_converged = [point for name in applicable for point in per_impl_not_converged[name]]

    findings = [
        Finding(check="implementations", status=STATUS_INFO,
                detail="target=%s；适用实现：%s" % (target, "、".join(applicable)),
                evidence={"rule": "data/README.md §1.3", "implementations": list(IMPLEMENTATIONS),
                          "applicable": list(applicable), "input_points": len(points)}),
        Finding(check="pairwise", status=STATUS_INFO,
                detail=("%d 对实现差分" % len(pairwise)) if pairwise else "无可比较的实现对",
                evidence={"rule": "data/README.md §4.4",
                          "pairs": ["%s/%s" % (r["a"], r["b"]) for r in pairwise],
                          "max_m": round(max((r["max_m"] for r in pairwise), default=0.0), 1)}),
        Finding(check="boundary_table", status=STATUS_WARNING if diverge else STATUS_CONSISTENT,
                reason=REASON_BOUNDARY_DIVERGENCE if diverge else None,
                detail=("两库 out_of_china 结论不同的点：%d/%d（coordTransform_py 开区间 / gcoord 闭区间）——这是审计发现点，不是任何一方的 bug"
                        % (len(diverge), len(boundary_rows)))
                if diverge else "两库 out_of_china 对本批坐标结论一致",
                evidence={"rule": "data/README.md §1.3", "rows": len(boundary_rows), "disagree": len(diverge)}),
        Finding(check="jumps", status=STATUS_INFO,
                detail="边界内外跳变点 %d 个（两库对'是否偏移'结论相反）" % len(jumps),
                evidence={"rule": "plan/03 §三", "jumps": len(jumps), "reason": JUMP_REASON}),
        Finding(check="not_converged", status=STATUS_UNDECIDABLE if not_converged else STATUS_CONSISTENT,
                reason=REASON_NOT_CONVERGED if not_converged else None,
                detail=("gcoord 定点迭代在 %d 个点上超上限未收敛（容差 %s°）——这些点的差分不可信，按灰区处理"
                        % (len(not_converged), INVERSE_TOLERANCE_DEG))
                if not_converged else "所有适用实现的逆向均在容差内收敛",
                evidence={"rule": "plan/03 §三", "tolerance_deg": INVERSE_TOLERANCE_DEG, "points": len(not_converged)}),
    ]
    return {
        "target": target,
        "input_points": len(points),
        "implementations": {
            name: {"points": [list(c) for c in outputs[name]], "not_converged": len(per_impl_not_converged[name])}
            for name in applicable
        },
        "pairwise": pairwise,
        "boundary_table": boundary_rows,
        "jumps": len(jumps),
        "not_converged": len(not_converged),
        "findings": [f.as_dict() for f in findings],
        "verdict": ("两库边界结论 %d 点不同" % len(diverge)) if diverge else "两库边界结论对全部坐标一致",
    }
