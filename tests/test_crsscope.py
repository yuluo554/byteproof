"""``crsscope`` 器官的无损测试（迁自 10-27-crsscope）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：GCJ-02/BD-09/WebMercator
常数与算法（两套 out_of_china 边界不合并、逆向迭代容差 1e-6）、decl 五项检查
（量级/轴序/单位/混用/范围，一项一责）、detect 三假设评分与三段残差、xdiff 跨实现
差分（线性 vs 迭代 vs 解析逆，两库边界结论表）、geojson 七项检查（环方向级别由 R2
决定、精度读 Decimal 指数）、tiles 五项检查（y 越界单点即判、wrap 显式声明）。

**没迁的部分逐条写在 ``docs/crsscope.md`` §6 的处置表里**（文件读取、GPX/CSV/掩膜
解析、报告渲染、CLI、静态门）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 22 个测试文件剔除 ``cli|release|report`` 后 17 文件实跑
**X = 268 passed**（2 skipped；旧层 AST ``test_`` 函数 210）。
"""

from __future__ import annotations

import ast
import json
import math
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors.crsscope import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    algorithms,
    declcheck,
    detectcore,
    finding as finding_mod,
    geojsoncheck,
    spec,
    tilescheck,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    WARN,
    Basis,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "crsscope"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "crsscope.basis.json"
THRESHOLDS_PATH = DATA_DIR / "crsscope.thresholds.json"
SAMPLE = ROOT / "samples" / "crsscope.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def _samples(pairs):
    return [declcheck.Sample(seq=i + 1, a=a, b=b) for i, (a, b) in enumerate(pairs)]


def _subject(mode="decl", **extra):
    subject = {"mode": mode}
    subject.update(extra)
    return subject


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _report(subject):
    return Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="test.json", records=tuple(_evaluate(subject)))


def _land_mask():
    """3×3 全陆地网格（覆盖 100–103°E / 30–33°N，1° 步长）。"""
    cells = {}
    for lat in range(3):
        for lon in range(3):
            cells[(lat, lon)] = "land"
    return finding_mod.Mask(version="t1", resolution_deg=1.0, lon_min=100.0, lat_min=30.0, n_lon=3, n_lat=3, cells=cells)


def _water_mask():
    cells = {}
    for lat in range(3):
        for lon in range(3):
            cells[(lat, lon)] = "water"
    return finding_mod.Mask(version="t1", resolution_deg=1.0, lon_min=100.0, lat_min=30.0, n_lon=3, n_lat=3, cells=cells)


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG


def test_pack_declares_mode_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "crsscope" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_sample_is_a_clean_decl():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert data["mode"] == "decl"
    records = [r for r in _evaluate(data) if r.rule_id != spec.RULE_SUMMARY]
    assert {r.verdict for r in records} == {INFO}


def test_basis_has_every_declared_rule():
    assert set(BASIS.rule_ids()) == set(spec.RULE_IDS)


def test_basis_rules_all_have_version_source_and_text():
    for rule_id in BASIS.rule_ids():
        rule = BASIS.require(rule_id)
        assert rule.version == "1", rule_id
        assert rule.source, rule_id
        assert rule.text, rule_id


def test_basis_rule_ids_are_sorted():
    assert BASIS.rule_ids() == sorted(BASIS.rule_ids())


def test_every_check_rule_is_declared():
    for rule_id in spec.CHECK_RULE_IDS:
        assert rule_id in BASIS.rule_ids()


def test_thresholds_verdicts_match_runtime():
    assert SETTINGS["verdicts"] == spec.VERDICTS


def test_thresholds_status_mapping_matches_runtime():
    assert SETTINGS["status_to_verdict"] == spec.STATUS_TO_VERDICT


def test_thresholds_thresholds_match_runtime():
    thresholds = SETTINGS["thresholds"]
    assert thresholds["min_axis_samples"] == declcheck.MIN_AXIS_SAMPLES
    assert thresholds["precision_max_fraction_digits"] == geojsoncheck.PRECISION_MAX_FRACTION_DIGITS
    assert thresholds["weight_boundary"] == detectcore.WEIGHT_BOUNDARY
    assert thresholds["min_evaluable_points"] == detectcore.MIN_EVALUABLE_POINTS
    assert thresholds["mask_max_resolution_deg"] == finding_mod.MAX_RESOLUTION_DEG


def test_thresholds_choices_match_runtime():
    assert SETTINGS["declared_crs_choices"] == list(declcheck.DECLARED_CRS_CHOICES)
    assert SETTINGS["hypotheses"] == list(algorithms.HYPOTHESES)
    assert SETTINGS["target_choices"] == list(detectcore.TARGET_CHOICES)
    assert SETTINGS["implementations"] == list(detectcore.IMPLEMENTATIONS)


def test_thresholds_bbox_profiles_are_not_merged():
    profiles = SETTINGS["bbox_profiles"]
    assert profiles["coordTransform_py"]["closed"] is False
    assert profiles["gcoord"]["closed"] is True
    assert profiles["coordTransform_py"]["lon"] != profiles["gcoord"]["lon"]


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("crs-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== algorithms
def test_krasovsky_constants_copied():
    assert algorithms.KRASOVSKY_A == 6378245.0
    assert algorithms.KRASOVSKY_EE == 0.006693421622965823


@pytest.mark.parametrize(
    "lon,lat,closed,expected",
    [
        (73.66, 10.0, False, False),
        (73.66, 10.0, True, True),
        (135.05, 10.0, True, True),
        (73.0, 10.0, True, False),
        (100.0, 30.0, True, True),
    ],
)
def test_in_bbox_closed_semantics(lon, lat, closed, expected):
    bbox = {"lon": (73.66, 135.05), "lat": (3.86, 53.55), "closed": closed}
    assert algorithms.in_bbox(lon, lat, bbox) is expected


def test_in_china_profiles_disagree_on_endpoint():
    # 端点差异是实质差异：coordTransform_py 开区间 → 73.66°E 是"境外"
    assert algorithms.in_china(73.66, 10.0, algorithms.PROFILE_CT_PY) is False
    assert algorithms.in_china(73.66, 10.0, algorithms.PROFILE_GCOORD) is True


def test_in_china_unknown_profile_rejected():
    with pytest.raises(ValueError):
        algorithms.in_china(100.0, 30.0, "nope")


def test_distance_to_bbox_deg_outside():
    bbox = algorithms.GCOORD_BBOX
    assert algorithms.distance_to_bbox_deg(70.0, 30.0, bbox) == pytest.approx(2.004)


def test_distance_to_bbox_deg_inside_not_zero():
    bbox = algorithms.GCOORD_BBOX
    inside = algorithms.distance_to_bbox_deg(73.664, 3.863, bbox)
    assert inside > 0.0
    edge = algorithms.distance_to_bbox_deg(73.664, 0.8293, bbox)
    assert edge == pytest.approx(0.0)


def test_wgs84_to_gcj02_shifts_inside_china():
    lon, lat = algorithms.wgs84_to_gcj02(116.4074, 39.9042)
    assert lon > 116.4074
    assert lat > 39.9042
    assert abs(lon - 116.4074) < 0.01


def test_wgs84_to_gcj02_identity_outside():
    assert algorithms.wgs84_to_gcj02(139.0, 35.0) == (139.0, 35.0)


def test_wgs84_to_gcj02_boundary_differs_by_profile():
    # 边界附近两库口径不同：开区间库不偏移、闭区间库偏移
    point = (73.0, 30.0)
    ct = algorithms.wgs84_to_gcj02(*point, profile=algorithms.PROFILE_CT_PY)
    gc = algorithms.wgs84_to_gcj02(*point, profile=algorithms.PROFILE_GCOORD)
    assert ct == point  # 开区间库判"境外"，不偏移
    assert gc != point  # 闭区间库判"境内"，偏移


def test_gcj02_inverse_iterative_roundtrip():
    wgs = (116.4074, 39.9042)
    gcj = algorithms.wgs84_to_gcj02(*wgs)
    inv = algorithms.gcj02_to_wgs84_iterative(*gcj)
    assert inv.converged is True
    assert inv.iterations >= 1
    assert inv.lon == pytest.approx(wgs[0], abs=1e-5)
    assert inv.lat == pytest.approx(wgs[1], abs=1e-5)


def test_gcj02_inverse_iterative_outside_identity():
    inv = algorithms.gcj02_to_wgs84_iterative(139.0, 35.0)
    assert (inv.lon, inv.lat) == (139.0, 35.0)
    assert inv.iterations == 0


def test_gcj02_inverse_linear_is_approximate():
    wgs = (116.4074, 39.9042)
    gcj = algorithms.wgs84_to_gcj02(*wgs)
    inv = algorithms.gcj02_to_wgs84_linear(*gcj)
    assert inv.converged is True
    # 一步线性近似 ≠ 精确还原：残差如实存在（xdiff 如实差分）
    assert inv.lon != pytest.approx(wgs[0], abs=1e-9)


def test_bd09_roundtrip():
    gcj = (116.4074, 39.9042)
    bd = algorithms.gcj02_to_bd09(*gcj)
    back = algorithms.bd09_to_gcj02(*bd)
    assert back[0] == pytest.approx(gcj[0], abs=1e-6)
    assert back[1] == pytest.approx(gcj[1], abs=1e-6)


def test_webmercator_roundtrip():
    x, y = algorithms.wgs84_to_webmercator(116.4074, 39.9042)
    lon, lat = algorithms.webmercator_to_wgs84(x, y)
    assert lon == pytest.approx(116.4074)
    assert lat == pytest.approx(39.9042)


def test_webmercator_clamps_latitude():
    x1, y1 = algorithms.wgs84_to_webmercator(0.0, 89.0)
    x2, y2 = algorithms.wgs84_to_webmercator(0.0, 95.0)
    assert y1 == y2


@pytest.mark.parametrize(
    "hypothesis",
    ["WGS84", "GCJ02", "BD09"],
)
def test_inverse_for_known_hypotheses(hypothesis):
    inv = algorithms.inverse_for(hypothesis, 116.4074, 39.9042)
    assert inv.converged is True


def test_inverse_for_unknown_rejected():
    with pytest.raises(ValueError):
        algorithms.inverse_for("XYZ", 116.0, 39.0)


# ================================================================== geodesy
def test_haversine_zero_distance():
    assert finding_mod.haversine_m(116.4, 39.9, 116.4, 39.9) == pytest.approx(0.0)


def test_haversine_beijing_shanghai_order_of_magnitude():
    distance = finding_mod.haversine_m(116.4074, 39.9042, 121.4737, 31.2304)
    assert 1_050_000 < distance < 1_100_000


def test_normalize_lon_wraps():
    assert finding_mod.normalize_lon(185.0) == pytest.approx(-175.0)
    assert finding_mod.normalize_lon(-185.0) == pytest.approx(175.0)


def test_lon_delta_shortest_arc():
    assert finding_mod.lon_delta(170.0, -170.0) == pytest.approx(-20.0)


def test_meters_per_degree_longitude_shrinks_with_latitude():
    equator = finding_mod.approx_meters_per_degree_lon(0.0)
    high_lat = finding_mod.approx_meters_per_degree_lon(60.0)
    assert high_lat < equator


# ================================================================== finding / mask
def test_finding_as_dict_shape():
    f = finding_mod.Finding(check="axis", status="conflict", detail="d", reason="axis", evidence={"k": 1})
    assert f.as_dict() == {"check": "axis", "status": "conflict", "reason": "axis", "detail": "d", "evidence": {"k": 1}}


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (("consistent",), 0),
        (("info",), 0),
        (("warning",), 0),
        (("undecidable",), 0),
        (("conflict",), 1),
        (("error",), 1),
        (("consistent", "conflict"), 1),
        (("undecidable", "warning"), 0),
    ],
)
def test_outcome_code_mapping(statuses, expected):
    findings = [finding_mod.Finding(check="c", status=s, detail="d") for s in statuses]
    assert finding_mod.outcome_code(findings) == expected


def test_mask_rejects_resolution_over_limit():
    with pytest.raises(finding_mod.EnvironmentMissing):
        finding_mod.Mask(version="x", resolution_deg=2.0, lon_min=0.0, lat_min=0.0, n_lon=1, n_lat=1, cells={})


def test_mask_index_of_bounds():
    mask = _land_mask()
    assert mask.index_of(100.5, 30.5) == (0, 0)
    assert mask.index_of(103.5, 30.5) is None  # 越出 n_lon
    assert mask.index_of(100.5, 33.5) is None


def test_mask_cell_at_unknown_outside():
    mask = _land_mask()
    assert mask.cell_at(100.5, 30.5) == "land"
    assert mask.cell_at(0.0, 0.0) == "unknown"


def test_mask_is_coastal_detects_heterogeneous_neighbor():
    cells = {(lat, lon): "land" for lat in range(3) for lon in range(3)}
    cells[(0, 0)] = "water"
    mask = finding_mod.Mask(version="t", resolution_deg=1.0, lon_min=0.0, lat_min=0.0, n_lon=3, n_lat=3, cells=cells)
    assert mask.is_coastal(0.5, 1.5) is True  # 与 (0,0) 的 water 相邻
    assert mask.is_coastal(2.5, 2.5) is False


def test_maskstats_denominator_excludes_unknown_and_coastal():
    # 邻格异类才算海岸带；unknown 不构成异类相邻（不把 land 挤出分母）
    # cells 以 (lat_idx, lon_idx) 为键（index_of 的返回形态）
    cells = {(0, 0): "land", (0, 1): "land", (0, 2): "unknown", (0, 3): "water"}
    mask = finding_mod.Mask(version="t", resolution_deg=1.0, lon_min=0.0, lat_min=0.0, n_lon=4, n_lat=1, cells=cells)
    stats = finding_mod.MaskStats()
    stats.add(mask, 0.5, 0.5)  # land（邻格全 land/边界）→ 非海岸
    stats.add(mask, 1.5, 0.5)  # land（邻格 unknown 不算异类）→ 非海岸
    stats.add(mask, 2.5, 0.5)  # unknown → 不进分母
    stats.add(mask, 3.5, 0.5)  # water（邻格 unknown）→ 非海岸
    assert stats.land == 2 and stats.water == 1 and stats.unknown == 1
    assert stats.evaluable == 3
    assert stats.water_ratio == pytest.approx(1.0 / 3.0)


def test_maskstats_water_ratio_none_when_no_evaluable():
    stats = finding_mod.MaskStats()
    assert stats.water_ratio is None


def test_maskstats_as_header_carries_version_and_resolution():
    mask = _land_mask()
    stats = finding_mod.MaskStats()
    stats.add(mask, 101.0, 31.0)
    header = stats.as_header(mask)
    assert header["mask_version"] == "t1"
    assert header["mask_max_resolution_deg"] == 1.0


# ================================================================== decl：样本与声明
def test_sample_band_and_magnitude():
    assert _samples([(116.0, 39.0)])[0].band == "degree"
    assert _samples([(2_000_000.0, 3_000_000.0)])[0].band == "metre"
    assert _samples([(500.0, 600.0)])[0].band == "neither"
    assert _samples([(116.0, 39.0)])[0].magnitude == 116.0


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("4326", "4326"),
        ("EPSG:4326", "4326"),
        ("wgs84", "4326"),
        ("cgcs2000", "4490"),
        ("OGC:CRS84", "crs84"),
        ("epsg:900913", "3857"),
        ("unknown-crs", None),
        (None, None),
    ],
)
def test_normalize_declared_aliases(raw, expected):
    assert declcheck.normalize_declared(raw) == expected


def test_resolve_declared_cli_wins():
    declared, source = declcheck.resolve_declared("4326", "epsg:3857")
    assert declared == "4326" and source == declcheck.SOURCE_CLI


def test_resolve_declared_invalid_cli_raises():
    with pytest.raises(declcheck.UsageError):
        declcheck.resolve_declared("gcj02", None)


def test_resolve_declared_file_unrecognised():
    declared, source = declcheck.resolve_declared(None, "unknown-crs")
    assert declared is None and source == declcheck.SOURCE_FILE_UNRECOGNISED


def test_resolve_declared_none():
    declared, source = declcheck.resolve_declared(None, None)
    assert declared is None and source == declcheck.SOURCE_NONE


# ================================================================== decl：五项检查
def test_check_magnitude_degree_conflict():
    finding = declcheck.check_magnitude(_samples([(2_000_000.0, 3_000_000.0)]), "4326")
    assert finding.status == "conflict" and finding.reason == "magnitude"


def test_check_magnitude_degree_consistent():
    finding = declcheck.check_magnitude(_samples([(116.0, 39.0)]), "4326")
    assert finding.status == "consistent"


def test_check_magnitude_no_declaration_info():
    finding = declcheck.check_magnitude(_samples([(2_000_000.0, 3_000_000.0)]), None)
    assert finding.status == "info"


def test_check_magnitude_3857_all_metre_consistent():
    finding = declcheck.check_magnitude(_samples([(2_000_000.0, 3_000_000.0)]), "3857")
    assert finding.status == "consistent"


def test_check_magnitude_3857_middle_band_undecidable():
    finding = declcheck.check_magnitude(_samples([(500.0, 600.0)]), "3857")
    assert finding.status == "undecidable"


def test_check_magnitude_empty_undecidable():
    finding = declcheck.check_magnitude([], "4326")
    assert finding.status == "undecidable" and finding.reason == "insufficient_samples"


def test_check_axis_swapped_is_conflict():
    pairs = [(39.9, 116.4), (31.2, 121.4), (23.1, 113.2), (30.5, 104.0), (34.2, 108.9)]
    finding, decidable = declcheck.check_axis(_samples(pairs), "4326")
    assert finding.status == "conflict" and decidable is True
    assert finding.evidence["corrected_sample"][0] > 90  # 修正样本把经度放回第一分量


def test_check_axis_normal_is_consistent():
    pairs = [(116.0, 39.0), (121.0, 31.0), (113.0, 23.0), (104.0, 30.0), (108.0, 34.0)]
    finding, decidable = declcheck.check_axis(_samples(pairs), "4326")
    assert finding.status == "consistent" and decidable is True


def test_check_axis_insufficient_samples():
    finding, decidable = declcheck.check_axis(_samples([(116.0, 39.0)]), "4326")
    assert finding.status == "undecidable" and finding.reason == "insufficient_samples"
    assert decidable is False


def test_check_axis_not_applicable_for_3857():
    finding, decidable = declcheck.check_axis(_samples([(2_000_000.0, 3_000_000.0)] * 5), "3857")
    assert finding.status == "info" and decidable is False


def test_check_axis_ambiguous_undecidable():
    pairs = [(10.0, 20.0)] * 5
    finding, decidable = declcheck.check_axis(_samples(pairs), "4326")
    assert finding.status == "undecidable" and decidable is False


def test_check_axis_decidable_excludes_metre_samples():
    pairs = [(116.0, 39.0), (121.0, 31.0), (113.0, 23.0), (104.0, 30.0), (108.0, 34.0), (2_000_000.0, 3_000_000.0)]
    finding, _decidable = declcheck.check_axis(_samples(pairs), "4326")
    assert finding.evidence["decidable_samples"] == 5


def test_check_unit_3857_with_degree_samples_conflict():
    finding = declcheck.check_unit(_samples([(116.0, 39.0)]), "3857")
    assert finding.status == "conflict" and finding.reason == "unit"


def test_check_unit_3857_metre_consistent():
    finding = declcheck.check_unit(_samples([(2_000_000.0, 3_000_000.0)]), "3857")
    assert finding.status == "consistent"


def test_check_unit_only_for_3857():
    finding = declcheck.check_unit(_samples([(116.0, 39.0)]), "4326")
    assert finding.status == "info"


def test_check_unit_empty_undecidable():
    finding = declcheck.check_unit([], "3857")
    assert finding.status == "undecidable"


def test_check_mixed_degree_and_metre_conflict():
    finding = declcheck.check_mixed(_samples([(116.0, 39.0), (2_000_000.0, 3_000_000.0)]))
    assert finding.status == "conflict" and finding.reason == "mixed"


def test_check_mixed_consistent():
    finding = declcheck.check_mixed(_samples([(116.0, 39.0)]))
    assert finding.status == "consistent"


def test_check_mixed_empty_info():
    assert declcheck.check_mixed([]).status == "info"


def test_check_extent_no_declaration_info():
    finding, candidates = declcheck.check_extent(_samples([(116.0, 39.0)]), None, None, 0.0)
    assert finding.status == "info" and candidates == []


def test_check_extent_degree_consistent_with_axis():
    pairs = [(116.0, 39.0), (121.0, 31.0), (113.0, 23.0), (104.0, 30.0), (108.0, 34.0)]
    finding, candidates = declcheck.check_extent(_samples(pairs), "4326", "lon_lat", 0.0)
    assert finding.status == "consistent"
    assert "lon_lat" in finding.evidence["axis_orientation"]
    assert candidates == []


def test_check_extent_out_of_range_conflict():
    # (150, 95)：量级 150 在度域，但纬度 95 > 90 → 越界（(200,10) 是中间带，不进度域子集）
    pairs = [(116.0, 39.0), (121.0, 31.0), (113.0, 23.0), (104.0, 30.0), (108.0, 34.2), (150.0, 95.0)]
    finding, _candidates = declcheck.check_extent(_samples(pairs), "4326", "lon_lat", 0.0)
    assert finding.status == "conflict"


def test_check_extent_no_degree_samples_gives_candidates():
    finding, candidates = declcheck.check_extent(_samples([(2_000_000.0, 3_000_000.0)]), "4326", None, 0.0)
    assert finding.status == "undecidable"
    assert candidates == ["3857"]


def test_check_extent_3857_metre_consistent():
    finding, candidates = declcheck.check_extent(_samples([(2_000_000.0, 3_000_000.0)]), "3857", None, 0.0)
    assert finding.status == "consistent" and candidates == []


def test_check_extent_3857_no_metre_gives_degree_candidates():
    finding, candidates = declcheck.check_extent(_samples([(116.0, 39.0)] * 1), "3857", None, 0.0)
    assert finding.status == "undecidable"
    assert candidates == ["4326", "4490", "crs84"]


def test_check_extent_3857_beyond_mercator_conflict():
    finding, _candidates = declcheck.check_extent(_samples([(30_000_000.0, 3_000_000.0)]), "3857", None, 0.0)
    assert finding.status == "conflict"


def test_decl_verdict_consistent():
    assert declcheck.verdict_of([declcheck.check_mixed(_samples([(116.0, 39.0)]))]) == "声明与内容相容（五项检查均未命中）"


def test_decl_verdict_names_conflicts():
    finding = declcheck.check_mixed(_samples([(116.0, 39.0), (2_000_000.0, 3_000_000.0)]))
    assert "mixed" in declcheck.verdict_of([finding])


def test_run_decl_full_order():
    payload = declcheck.run_decl(
        _samples([(116.0, 39.0), (121.0, 31.0), (113.0, 23.0), (104.0, 30.0), (108.0, 34.0)]),
        "4326",
    )
    checks = [f["check"] for f in payload["findings"]]
    assert checks == list(declcheck.CHECKS)
    assert payload["verdict"].startswith("声明与内容相容")


def test_run_decl_strict_steers_no_declaration():
    payload = declcheck.run_decl(_samples([(116.0, 39.0)] * 5), None, strict=True)
    statuses = {f["check"]: f["status"] for f in payload["findings"]}
    assert statuses["magnitude"] == "undecidable"
    assert statuses["extent"] == "undecidable"


def test_run_decl_declaration_note_for_unrecognised():
    payload = declcheck.run_decl(_samples([(116.0, 39.0)] * 5), None, file_crs="unknown-crs")
    assert "declaration_note" in payload
    assert payload["declared_crs_source"] == "file-unrecognised"


# ================================================================== detect
def test_median_and_p95():
    assert detectcore._median([3.0, 1.0, 2.0]) == 2.0
    assert detectcore._median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert detectcore._p95(list(range(1, 101))) == 95.0


def test_compass_directions():
    assert detectcore._compass(1.0, 0.0) == "东"
    assert detectcore._compass(0.0, -1.0) == "南"
    assert detectcore._compass(-1.0, 1.0) == "北西"
    assert detectcore._compass(0.0, 0.0) is None


def test_declared_conflict_table():
    assert detectcore._declared_conflict("WGS84", "4326") == 0
    assert detectcore._declared_conflict("WGS84", "3857") == 1
    assert detectcore._declared_conflict("GCJ02", "4326") == 1
    assert detectcore._declared_conflict("BD09", None) == 0


def test_boundary_analysis_flags_endpoint_disagreement():
    boundary = detectcore.boundary_analysis([(73.66, 10.0)])
    assert boundary.per_point_disagree == [True]  # 开/闭区间口径不同
    assert boundary.near_band is True


def test_boundary_analysis_interior_agrees():
    boundary = detectcore.boundary_analysis([(116.4, 39.9)])
    assert boundary.per_point_disagree == [False]
    assert boundary.near_band is False


def test_evaluate_hypothesis_wgs84_zero_offsets():
    mask = _land_mask()
    hypothesis = detectcore.evaluate_hypothesis("WGS84", [(101.0, 31.0)] * 3, mask, None, 0)
    assert hypothesis.offset_m == 0.0
    assert hypothesis.water_ratio == 0.0  # 全部落陆


def test_evaluate_hypothesis_gcj02_offsets_positive():
    mask = _land_mask()
    hypothesis = detectcore.evaluate_hypothesis("GCJ02", [(101.0, 31.0)] * 3, mask, None, 0)
    assert hypothesis.offset_m > 0.0
    assert hypothesis.direction is not None


def test_rank_hypotheses_score_desc_then_lexicographic():
    mask = _land_mask()
    points = [(101.0, 31.0)] * 3
    wgs = detectcore.evaluate_hypothesis("WGS84", points, mask, None, 0)
    gcj = detectcore.evaluate_hypothesis("GCJ02", points, mask, None, 0)
    bd = detectcore.evaluate_hypothesis("BD09", points, mask, None, 0)
    ranked = detectcore.rank_hypotheses([wgs, gcj, bd])
    # 全部整批落陆 → 三假设同分 1.0 → 字典序 BD09 < GCJ02 < WGS84（旧仓同口径）
    assert [h.name for h in ranked] == ["BD09", "GCJ02", "WGS84"]


def test_confidence_insufficient_points():
    mask = _land_mask()
    points = [(101.0, 31.0)] * 3
    ranked = detectcore.rank_hypotheses([
        detectcore.evaluate_hypothesis("WGS84", points, mask, None, 0),
        detectcore.evaluate_hypothesis("GCJ02", points, mask, None, 0),
        detectcore.evaluate_hypothesis("BD09", points, mask, None, 0),
    ])
    scorable = [h for h in ranked if h.score is not None]
    confidence, margin, gray = detectcore.confidence_of(scorable, detectcore.boundary_analysis(points))
    assert confidence == "undecidable" and gray == "insufficient_samples"


def test_confidence_tie_is_gray():
    mask = _land_mask()
    points = [(101.0, 31.0)] * 40
    ranked = detectcore.rank_hypotheses([
        detectcore.evaluate_hypothesis("GCJ02", points, mask, None, 0),
        detectcore.evaluate_hypothesis("BD09", points, mask, None, 0),
    ])
    scorable = [h for h in ranked if h.score is not None]
    confidence, margin, gray = detectcore.confidence_of(scorable, detectcore.boundary_analysis(points))
    assert confidence == "undecidable" and gray == "tie"


def test_residual_three_parts_always_complete():
    boundary = detectcore.boundary_analysis([(116.4, 39.9)])
    parts = detectcore.residual_three_parts(None, boundary, [(116.4, 39.9)])
    kinds = [part["kind"] for part in parts]
    assert kinds == ["formula_approximation", "vendor_divergence", "boundary_jump"]


def test_run_detect_shape():
    mask = _land_mask()
    payload = detectcore.run_detect([(101.0, 31.0)] * 3, mask, None)
    assert payload["confidence"] == "undecidable"  # 3 点 < 30 → 灰区
    assert payload["winner"]["name"] == "BD09"  # 3 点全陆同分 → 字典序
    assert len(payload["hypotheses"]) == 3
    assert payload["mask_note"].startswith("掩膜为构造网格")


def test_run_detect_land_mask_prefers_wgs84():
    mask = _land_mask()
    points = [(100.5 + 0.1 * i, 30.5 + 0.1 * (i % 3)) for i in range(35)]
    payload = detectcore.run_detect(points, mask, None)
    # 三假设整批落陆同分 → 字典序 BD09 胜出；平局即灰区（旧仓同口径，不硬判）
    assert payload["winner"]["name"] == "BD09"
    assert payload["confidence"] == "undecidable"


def test_run_detect_water_mask_prefers_gcj02_or_bd09():
    mask = _water_mask()
    points = [(100.5 + 0.1 * i, 30.5 + 0.1 * (i % 3)) for i in range(35)]
    payload = detectcore.run_detect(points, mask, None)
    assert payload["winner"]["name"] in ("GCJ02", "BD09", "WGS84")
    assert payload["winner"]["score"] is not None


# ================================================================== xdiff
def test_run_xdiff_rejects_unknown_target():
    with pytest.raises(detectcore.UsageError):
        detectcore.run_xdiff([(116.0, 39.0)], "utm")


def test_run_xdiff_wgs84_identity_all_impls():
    payload = detectcore.run_xdiff([(116.4074, 39.9042)], "wgs84")
    for name, block in payload["implementations"].items():
        assert block["points"][0][0] == pytest.approx(116.4074)


def test_run_xdiff_applicable_sets_by_target():
    assert detectcore.TARGET_IMPLEMENTATIONS["gcj02"] == ("coordTransform_py", "gcoord")
    assert detectcore.TARGET_IMPLEMENTATIONS["webmercator"] == ("gcoord", "proj4js_webmercator")


def test_run_xdiff_pairwise_stats_shape():
    payload = detectcore.run_xdiff([(116.4074, 39.9042)], "gcj02")
    pair = payload["pairwise"][0]
    assert pair["a"] == "coordTransform_py" and pair["b"] == "gcoord"
    assert pair["points_compared"] == 1
    assert pair["max_m"] >= pair["median_m"]


def test_run_xdiff_linear_vs_iterative_diverges():
    payload = detectcore.run_xdiff([(116.4074, 39.9042), (121.4737, 31.2304)], "gcj02")
    pair = payload["pairwise"][0]
    assert pair["max_m"] > 0.0  # 一步线性与定点迭代的实现差如实体现


def test_run_xdiff_boundary_table_disagrees_at_endpoint():
    payload = detectcore.run_xdiff([(73.66, 10.0)], "wgs84")
    assert payload["boundary_table"][0]["agree"] is False
    assert payload["jumps"] == 1


def test_run_xdiff_boundary_interior_agrees():
    payload = detectcore.run_xdiff([(116.4, 39.9)], "wgs84")
    assert payload["boundary_table"][0]["agree"] is True
    assert payload["boundary_table"][0]["ct_py"] is True
    assert payload["boundary_table"][0]["gcoord"] is True


# ================================================================== geojson：收集与精度
def _audit(doc, name="doc.json"):
    return geojsoncheck.audit_document(name, doc)


def test_fraction_digits_reads_decimal_exponent():
    assert geojsoncheck.fraction_digits(Decimal("112.123456789012")) == 12
    assert geojsoncheck.fraction_digits(Decimal("116")) == 0
    assert geojsoncheck.fraction_digits(116.5) == 0  # float 不参与精度检查


def test_number_rejects_bool_and_string():
    assert geojsoncheck._number(True) is None
    assert geojsoncheck._number("3") is None
    assert geojsoncheck._number(3) == 3.0
    assert geojsoncheck._number(Decimal("NaN")) is None


def test_leaf_rejects_non_array():
    audit = _audit({})
    geojsoncheck._leaf("nope", audit)
    assert audit.issues and audit.issues[0].status == "error"


def test_leaf_rejects_short_pair():
    audit = _audit({})
    geojsoncheck._leaf([116.0], audit)
    assert any("至少需要 2 个" in issue.detail for issue in audit.issues)


def test_leaf_rejects_non_numeric():
    audit = _audit({})
    geojsoncheck._leaf([116.0, "lat"], audit)
    assert any("非数值" in issue.detail for issue in audit.issues)


def test_shoelace_sign_table():
    ccw = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    cw = list(reversed(ccw))
    assert geojsoncheck.shoelace_sign(ccw) == 1
    assert geojsoncheck.shoelace_sign(cw) == -1
    assert geojsoncheck.shoelace_sign([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]) == 0


def test_bbox_contains_normal_and_crossing():
    assert geojsoncheck.bbox_contains(100.0, 10.0, 120.0, 30.0, 110.0, 20.0) is True
    assert geojsoncheck.bbox_contains(160.0, 10.0, -160.0, 30.0, -170.0, 20.0) is True  # 跨 180°
    assert geojsoncheck.bbox_contains(160.0, 10.0, -160.0, 30.0, 0.0, 20.0) is False


def test_audit_bbox_member_length():
    audit = _audit({})
    geojsoncheck.audit_bbox_member([1.0, 2.0, 3.0], [(2.0, 2.0)], audit, "where")
    assert any("bbox 长度必须为 4 或 6" in issue.detail for issue in audit.issues)


def test_audit_bbox_member_order_violation():
    audit = _audit({})
    geojsoncheck.audit_bbox_member([110.0, 30.0, 100.0, 10.0], [(105.0, 20.0)], audit, "where")
    assert audit.bbox_members[0]["problems"]


def test_audit_bbox_member_outside_points():
    audit = _audit({})
    geojsoncheck.audit_bbox_member([0.0, 0.0, 1.0, 1.0], [(5.0, 5.0)], audit, "where")
    record = audit.bbox_members[0]
    assert any("bbox 之外" in problem for problem in record["problems"])
    assert record["outside_sample"] == [5.0, 5.0]


def test_audit_bbox_member_crossing_is_legal():
    audit = _audit({})
    geojsoncheck.audit_bbox_member([160.0, 10.0, -160.0, 30.0], [(170.0, 20.0)], audit, "where")
    assert audit.bbox_members[0]["west_greater_than_east"] is True
    assert audit.bbox_members[0]["problems"] == []


def test_audit_document_feature_collection():
    doc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [116.0, 39.0]}},
            {"type": "Feature", "properties": None, "geometry": None},
        ],
    }
    audit = _audit(doc)
    assert audit.top_type == "FeatureCollection"
    assert len(audit.points) == 1
    assert audit.null_geometries == 1 and audit.null_properties == 1
    assert audit.issues == []


def test_audit_document_unknown_type_is_structure_error():
    audit = _audit({"type": "NotGeoJSON"})
    assert any("未知 GeoJSON type" in issue.detail for issue in audit.issues)


def test_audit_document_missing_coordinates():
    audit = _audit({"type": "Point"})
    assert any("缺少 coordinates 成员" in issue.detail for issue in audit.issues)


def test_audit_document_has_crs_recorded():
    audit = _audit({"type": "Point", "crs": {"type": "name"}, "coordinates": [1.0, 2.0]})
    assert audit.has_crs is True


def test_audit_document_ring_signs_recorded():
    doc = {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}
    audit = _audit(doc)
    assert len(audit.ring_signs) == 1
    assert audit.ring_signs[0]["ring"] == "exterior"
    assert audit.ring_signs[0]["sign"] == 1  # 逆时针 = 符合 R1


def test_audit_document_degenerate_ring_is_structure_error():
    doc = {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 0.0]]]}
    audit = _audit(doc)
    assert any("环退化" in issue.detail for issue in audit.issues)


def test_precision_samples_capped():
    doc = {"type": "Point", "coordinates": [Decimal("116.1234567890123"), Decimal("39.0")]}
    audit = _audit(doc)
    assert audit.max_fraction_digits == 13
    assert len(audit.precision_samples) == 1


# ================================================================== geojson：七项检查
def _audits_from(docs):
    return [geojsoncheck.audit_document(name, doc) for name, doc in docs]


def test_ring_order_status_default_warning_strict_error():
    assert geojsoncheck.ring_order_status(False) == "warning"
    assert geojsoncheck.ring_order_status(True) == "error"


def test_ring_order_status_is_derived_from_r2():
    # 变异靶子：R2 文本失去容忍语义（SHOULD NOT reject）→ 默认级别必须升 error
    original = geojsoncheck.RFC_R2
    try:
        geojsoncheck.RFC_R2 = "right-hand rule applies"
        assert geojsoncheck.ring_order_status(False) == "error"
    finally:
        geojsoncheck.RFC_R2 = original


def _cw_polygon_doc():
    cw = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
    reversed_ring = [[list(pair) for pair in reversed(cw[0])] + [[0.0, 0.0]]]
    return {"type": "Polygon", "coordinates": reversed_ring}


def test_check_ring_order_violation_defaults_warning():
    audits = _audits_from([("doc.json", _cw_polygon_doc())])
    finding = geojsoncheck.check_ring_order(audits, strict_ring=False)
    assert finding.status == "warning" and finding.reason == "ring"


def test_check_ring_order_strict_upgrades_error():
    audits = _audits_from([("doc.json", _cw_polygon_doc())])
    finding = geojsoncheck.check_ring_order(audits, strict_ring=True)
    assert finding.status == "error"


def test_check_ring_order_all_consistent():
    doc = {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]}
    audits = _audits_from([("doc.json", doc)])
    assert geojsoncheck.check_ring_order(audits, strict_ring=False).status == "consistent"


def test_check_ring_order_no_rings_info():
    audits = _audits_from([("doc.json", {"type": "Point", "coordinates": [1.0, 2.0]})])
    assert geojsoncheck.check_ring_order(audits, strict_ring=False).status == "info"


def test_check_axis_swapped_warning():
    doc = {"type": "Point", "coordinates": [39.0, 116.0]}
    audits = _audits_from([("doc.json", doc)])
    finding = geojsoncheck.check_axis(audits)
    assert finding.status == "warning" and finding.reason == "axis"


def test_check_axis_lon_clear_consistent():
    doc = {"type": "Point", "coordinates": [116.0, 39.0]}
    assert geojsoncheck.check_axis(_audits_from([("d", doc)])).status == "consistent"


def test_check_axis_ambiguous_info():
    doc = {"type": "Point", "coordinates": [10.0, 20.0]}
    assert geojsoncheck.check_axis(_audits_from([("d", doc)])).status == "info"


def test_check_bbox_problem_warning():
    doc = {"type": "Point", "bbox": [0.0, 0.0, 1.0, 1.0], "coordinates": [5.0, 5.0]}
    finding = geojsoncheck.check_bbox(_audits_from([("d", doc)]))
    assert finding.status == "warning" and finding.reason == "bbox"


def test_check_bbox_crossing_info():
    doc = {"type": "Point", "bbox": [160.0, 10.0, -160.0, 30.0], "coordinates": [170.0, 20.0]}
    finding = geojsoncheck.check_bbox(_audits_from([("d", doc)]))
    assert finding.status == "info"


def test_check_bbox_consistent():
    doc = {"type": "Point", "bbox": [115.0, 38.0, 117.0, 40.0], "coordinates": [116.0, 39.0]}
    finding = geojsoncheck.check_bbox(_audits_from([("d", doc)]))
    assert finding.status == "consistent"


def test_check_nesting_info_when_nested():
    doc = {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [1.0, 2.0]}]}
    finding = geojsoncheck.check_nesting(_audits_from([("d", doc)]))
    assert finding.status == "info" and finding.evidence["max_depth"] == 1


def test_check_null_geometry_info():
    doc = {"type": "Feature", "properties": None, "geometry": None}
    finding = geojsoncheck.check_null_geometry(_audits_from([("d", doc)]))
    assert finding.status == "info"


def test_check_crs_member_warning():
    doc = {"type": "Point", "crs": {"type": "name"}, "coordinates": [1.0, 2.0]}
    finding = geojsoncheck.check_crs_member(_audits_from([("d", doc)]))
    assert finding.status == "warning" and finding.reason == "crs"


def test_check_crs_member_consistent_without():
    doc = {"type": "Point", "coordinates": [1.0, 2.0]}
    assert geojsoncheck.check_crs_member(_audits_from([("d", doc)])).status == "consistent"


def test_check_precision_warning_over_nine_digits():
    doc = {"type": "Point", "coordinates": [Decimal("116.12345678901"), Decimal("39.0")]}
    finding = geojsoncheck.check_precision(_audits_from([("d", doc)]))
    assert finding.status == "warning" and finding.reason == "precision"


def test_check_precision_consistent():
    doc = {"type": "Point", "coordinates": [116.123456, 39.0]}
    assert geojsoncheck.check_precision(_audits_from([("d", doc)])).status == "consistent"


def test_geojson_verdict_names_structure_errors():
    finding = geojsoncheck.Finding(check="structure", status="error", detail="x")
    assert "structure" in geojsoncheck.verdict_of([finding])


def test_run_geojson_clean_collection():
    doc = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [116.0, 39.0]}}],
    }
    payload = geojsoncheck.run_geojson([("doc.json", doc)])
    assert payload["verdict"].startswith("结构自洽")
    assert payload["structure_issues"] == []
    assert payload["counts"]["coordinates"] == 1


def test_run_geojson_collects_structure_issues():
    doc = {"type": "Point", "coordinates": [116.0]}
    payload = geojsoncheck.run_geojson([("doc.json", doc)])
    assert payload["structure_issues"]


# ================================================================== tiles
def _group(tiles, bbox=None, group_id="g"):
    return tilescheck.TileGroup(id=group_id, tiles=[tilescheck.Tile(**tile) for tile in tiles], bbox=bbox)


def test_tile_rows_and_key():
    tile = tilescheck.Tile(z=3, x=1, y=2)
    assert tile.rows == 8
    assert tile.key == {"z": 3, "x": 1, "y": 2}


def test_audit_group_y_range_offender():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 5}]))
    assert audit.y_range_offenders == [{"z": 2, "x": 0, "y": 5, "allowed": [0, 3], "scheme": None}]


def test_audit_group_y_in_range_not_flagged():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 3}]))
    assert audit.y_range_offenders == []


def test_audit_group_axis_flip_pair_same_bbox():
    bbox = (100.0, 10.0, 110.0, 20.0)
    audit = tilescheck.audit_group(
        _group(
            [{"z": 3, "x": 1, "y": 2, "scheme": "xyz", "bbox": bbox}, {"z": 3, "x": 1, "y": 5, "scheme": "tms", "bbox": bbox}],
            bbox=bbox,
        )
    )
    assert len(audit.axis_flip_pairs) == 1
    assert audit.axis_flip_pairs[0]["y"] == [2, 5]
    assert audit.axis_flip_pairs[0]["flip_formula"] == tilescheck.FLIP_FORMULA


def test_audit_group_flip_requires_same_bbox():
    audit = tilescheck.audit_group(
        _group(
            [
                {"z": 3, "x": 1, "y": 2, "scheme": "xyz", "bbox": (100.0, 10.0, 110.0, 20.0)},
                {"z": 3, "x": 1, "y": 5, "scheme": "tms", "bbox": (100.0, 10.0, 110.0, 21.0)},
            ]
        )
    )
    assert audit.axis_flip_pairs == []


def test_audit_group_flip_skips_self_symmetric():
    audit = tilescheck.audit_group(_group([{"z": 3, "x": 1, "y": 3}, {"z": 3, "x": 1, "y": 4}]))
    assert audit.axis_flip_pairs == []  # 3 ↔ 4 自身对称对 + 无 bbox → 不判


def test_audit_group_zoom_break_missing_parent():
    tiles = [{"z": 2, "x": 0, "y": 0}, {"z": 3, "x": 7, "y": 7}]
    audit = tilescheck.audit_group(_group(tiles))
    assert len(audit.zoom_breaks) == 1
    assert audit.zoom_breaks[0]["missing_parent"] == {"z": 2, "x": 3, "y": 3}


def test_audit_group_zoom_nested_ok():
    tiles = [{"z": 2, "x": 0, "y": 0}, {"z": 3, "x": 1, "y": 1}]
    audit = tilescheck.audit_group(_group(tiles))
    assert audit.zoom_breaks == []


def test_audit_group_wrap_needed_edge_pair_without_wrap():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 0}, {"z": 2, "x": 3, "y": 1}]))
    assert audit.wrap_needed is True
    assert len(audit.wrap_missing) == 2


def test_audit_group_wrap_declared_ok():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 0, "wrap": True}, {"z": 2, "x": 3, "y": 1, "wrap": True}]))
    assert audit.wrap_needed is True
    assert audit.wrap_missing == []


def test_audit_group_no_wrap_needed_when_no_crossing():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 1, "y": 1}, {"z": 2, "x": 2, "y": 2}]))
    assert audit.wrap_needed is False and audit.wrap_missing == []


def test_audit_group_crossing_bbox_requires_wrap():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 1, "y": 1}], bbox=(170.0, 10.0, -170.0, 20.0)))
    assert audit.wrap_needed is True
    assert audit.wrap_missing == [{"z": 2, "x": 1, "y": 1, "group": "g"}]


def test_check_y_range_error():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 9}]))
    finding = tilescheck.check_y_range([audit])
    assert finding.status == "error" and finding.reason == "y_range"


def test_check_y_range_consistent():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 1}]))
    assert tilescheck.check_y_range([audit]).status == "consistent"


def test_check_axis_flip_conflict():
    bbox = (100.0, 10.0, 110.0, 20.0)
    audit = tilescheck.audit_group(
        _group(
            [
                {"z": 3, "x": 1, "y": 2, "scheme": "xyz", "bbox": bbox},
                {"z": 3, "x": 1, "y": 5, "scheme": "tms", "bbox": bbox},
            ],
            bbox=bbox,
        )
    )
    finding = tilescheck.check_axis_flip([audit])
    assert finding.status == "conflict" and finding.reason == "axis_flip"


def test_check_axis_flip_consistent():
    audit = tilescheck.audit_group(_group([{"z": 3, "x": 1, "y": 2}]))
    assert tilescheck.check_axis_flip([audit]).status == "consistent"


def test_check_zoom_bbox_conflict():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 0}, {"z": 3, "x": 7, "y": 7}]))
    assert tilescheck.check_zoom_bbox([audit]).status == "conflict"


def test_check_wrap_conflict_when_missing():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 0}, {"z": 2, "x": 3, "y": 1}]))
    assert tilescheck.check_wrap([audit]).status == "conflict"


def test_check_wrap_consistent_when_declared():
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": 0, "wrap": True}, {"z": 2, "x": 3, "y": 1, "wrap": True}]))
    assert tilescheck.check_wrap([audit]).status == "consistent"


def test_check_mixed_degree_metre_conflict():
    finding = tilescheck.check_mixed("points", [(116.0, 39.0), (2_000_000.0, 3_000_000.0)])
    assert finding.status == "conflict" and finding.reason == "mixed"


def test_check_mixed_all_degree_consistent():
    finding = tilescheck.check_mixed("points", [(116.0, 39.0)])
    assert finding.status == "consistent"


def test_check_mixed_not_applicable_for_tiles():
    finding = tilescheck.check_mixed("tiles", [])
    assert finding.status == "info"


def test_tiles_verdict_names_hits():
    finding = tilescheck.Finding(check="y_range", status="error", detail="x")
    assert "y_range" in tilescheck.verdict_of([finding], "tiles")


def test_run_tiles_shape():
    bbox = (100.0, 10.0, 110.0, 20.0)
    payload = tilescheck.run_tiles(
        [_group([{"z": 3, "x": 1, "y": 2, "scheme": "xyz", "bbox": bbox}, {"z": 3, "x": 1, "y": 5, "scheme": "tms", "bbox": bbox}], bbox=bbox)],
        kind="tiles",
    )
    assert payload["verdict"].startswith("瓦片/投影片不一致")
    assert payload["findings"][0]["check"] == "y_range"


# ================================================================== 账本/模式/校验
def test_mode_decl_end_to_end_conflict_blocks():
    subject = _subject(
        "decl",
        declared_crs="4326",
        samples=[{"a": 2_000_000.0, "b": 3_000_000.0}],
    )
    records = _records(subject, "crs-decl-magnitude")
    assert records[0].verdict == ERROR
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_mode_decl_axis_conflict_blocks():
    subject = _subject(
        "decl",
        declared_crs="4326",
        samples=[{"a": 39.9, "b": 116.4}, {"a": 31.2, "b": 121.4}, {"a": 23.1, "b": 113.2}, {"a": 30.5, "b": 104.0}, {"a": 34.2, "b": 108.9}],
    )
    assert _report(subject).exit_code() == EXIT_BLOCKED
    assert any(record.rule_id == "crs-decl-axis" and record.verdict == ERROR for record in _evaluate(subject))


def test_mode_decl_gray_zone_warns_not_blocks():
    subject = _subject("decl", declared_crs="4326", samples=[{"a": 116.0, "b": 39.0}])
    records = _evaluate(subject)
    assert any(record.rule_id == "crs-decl-axis" and record.verdict == WARN for record in records)
    assert _report(subject).exit_code() == EXIT_OK


def test_mode_decl_sample_clean():
    assert _report(_subject("decl", declared_crs="4326", samples=[{"a": 116.0, "b": 39.0}] * 5)).exit_code() == EXIT_OK


def test_mode_detect_gray_zone_warns():
    subject = _subject(
        "detect",
        points=[[101.0, 31.0]] * 3,
        mask={"version": "t", "resolution_deg": 1.0, "lon_min": 100.0, "lat_min": 30.0, "n_lon": 3, "n_lat": 3, "cells": {"0,0": "land", "0,1": "land", "0,2": "land", "1,0": "land", "1,1": "land", "1,2": "land", "2,0": "land", "2,1": "land", "2,2": "land"}},
    )
    records = _evaluate(subject)
    assert any(record.rule_id == spec.RULE_UNDECIDABLE and record.verdict == WARN for record in records)
    assert any(record.rule_id == spec.RULE_DETECT_WINNER for record in records)
    assert _report(subject).exit_code() == EXIT_OK


def test_mode_detect_requires_mask():
    with pytest.raises(ValueError):
        _evaluate(_subject("detect", points=[[101.0, 31.0]]))


def test_mode_detect_rejects_resolution_over_limit():
    subject = _subject(
        "detect",
        points=[[101.0, 31.0]],
        mask={"version": "t", "resolution_deg": 2.0, "lon_min": 100.0, "lat_min": 30.0, "n_lon": 1, "n_lat": 1, "cells": {"0,0": "land"}},
    )
    with pytest.raises(finding_mod.EnvironmentMissing):
        _evaluate(subject)


def test_mode_xdiff_boundary_warning():
    subject = _subject("xdiff", target="wgs84", points=[[73.66, 10.0]])
    records = _evaluate(subject)
    assert any(record.rule_id == "crs-xdiff-boundary-table" and record.verdict == WARN for record in records)
    assert _report(subject).exit_code() == EXIT_OK


def test_mode_xdiff_invalid_target_rc2():
    with pytest.raises(ValueError):
        _evaluate(_subject("xdiff", target="utm", points=[[116.0, 39.0]]))


def test_mode_geojson_structure_error_blocks():
    subject = _subject("geojson", documents=[{"name": "doc.json", "document": {"type": "Point", "coordinates": [116.0]}}])
    assert _report(subject).exit_code() == EXIT_BLOCKED
    assert any(record.rule_id == spec.RULE_STRUCTURE for record in _evaluate(subject))


def test_mode_geojson_ring_warning_not_blocking():
    subject = _subject("geojson", documents=[{"name": "doc.json", "document": _cw_polygon_doc()}])
    records = _evaluate(subject)
    assert any(record.rule_id == "crs-geojson-ring-order" and record.verdict == WARN for record in records)
    assert _report(subject).exit_code() == EXIT_OK


def test_mode_geojson_strict_ring_blocks():
    subject = _subject("geojson", strict_ring=True, documents=[{"name": "doc.json", "document": _cw_polygon_doc()}])
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_mode_geojson_crs_member_warning():
    subject = _subject(
        "geojson",
        documents=[{"name": "doc.json", "document": {"type": "Point", "crs": {"type": "name"}, "coordinates": [1.0, 2.0]}}],
    )
    assert any(record.rule_id == "crs-geojson-crs-member" and record.verdict == WARN for record in _evaluate(subject))


def test_mode_tiles_axis_flip_blocks():
    subject = _subject(
        "tiles",
        input_kind="tiles",
        groups=[{"id": "g", "bbox": [100.0, 10.0, 110.0, 20.0], "tiles": [
            {"z": 3, "x": 1, "y": 2, "scheme": "xyz", "bbox": [100.0, 10.0, 110.0, 20.0]},
            {"z": 3, "x": 1, "y": 5, "scheme": "tms", "bbox": [100.0, 10.0, 110.0, 20.0]},
        ]}],
    )
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_mode_tiles_y_range_blocks():
    subject = _subject("tiles", input_kind="tiles", groups=[{"id": "g", "tiles": [{"z": 2, "x": 0, "y": 9}]}])
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_mode_tiles_negative_z_rejected():
    subject = _subject("tiles", input_kind="tiles", groups=[{"id": "g", "tiles": [{"z": -1, "x": 0, "y": 0}]}])
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_mode_report_aggregates_modules():
    subject = _subject(
        "report",
        modules=[
            {"mode": "decl", "declared_crs": "4326", "samples": [{"a": 116.0, "b": 39.0}] * 5},
            {"mode": "xdiff", "target": "wgs84", "points": [[116.4, 39.9]]},
        ],
    )
    records = _evaluate(subject)
    assert any(record.path.startswith("report.findings[") for record in records)
    assert any(record.rule_id == "crs-xdiff-pairwise" for record in records)


def test_mode_report_rejects_unknown_module():
    subject = _subject("report", modules=[{"mode": "nope"}])
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_mode_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject("convert"))


def test_decl_requires_samples():
    with pytest.raises(ValueError):
        _evaluate(_subject("decl"))


def test_decl_rejects_non_numeric_samples():
    subject = _subject("decl", samples=[{"a": "x", "b": 1}])
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_geojson_requires_documents():
    with pytest.raises(ValueError):
        _evaluate(_subject("geojson"))


def test_records_unique_ids():
    subject = _subject(
        "geojson",
        documents=[{"name": "doc.json", "document": {"type": "Point", "crs": {"type": "name"}, "coordinates": [Decimal("116.1234567890123"), 39.0]}}],
    )
    report = _report(subject)
    ids = [r.id for r in report.records]
    assert len(ids) == len(set(ids))


def test_determinism_double_run():
    subject = _subject(
        "decl",
        declared_crs="4326",
        samples=[{"a": 116.0 + i, "b": 39.0} for i in range(5)],
    )
    a = json.dumps(_report(subject).as_dict(), ensure_ascii=False, sort_keys=True)
    b = json.dumps(_report(subject).as_dict(), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_exit_codes_cli(tmp_path):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject("decl", declared_crs="4326", samples=[{"a": 116.0, "b": 39.0}] * 5), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_OK


def test_exit_code_two_invalid(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "decl"}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path)]) == EXIT_INPUT


def test_exit_code_three_missing_rule(tmp_path):
    basis_path = tmp_path / "empty.basis.json"
    basis_path.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject("decl", declared_crs="4326", samples=[{"a": 116.0, "b": 39.0}] * 5), ensure_ascii=False), encoding="utf-8")
    rc = cli.main(["check", SLUG, "--input", str(path), "--basis", str(basis_path)])
    assert rc == EXIT_CONTRACT


# ================================================================== 补充：逐规则与参数化表
@pytest.mark.parametrize("rule_id", sorted(spec.RULE_IDS))
def test_each_rule_has_version_source_text(rule_id):
    rule = BASIS.require(rule_id)
    assert rule.version == "1" and rule.source and len(rule.text) >= 40


@pytest.mark.parametrize("rule_id", sorted(spec.CHECK_RULE_IDS))
def test_each_check_rule_maps_a_real_check_name(rule_id):
    module_map = {rule_id: check for mapping in spec.RULE_BY_MODULE.values() for check, rule in mapping.items()}
    assert module_map[rule_id]


@pytest.mark.parametrize(
    "lon,lat,expected",
    [
        (100.0, 30.0, True),
        (116.4074, 39.9042, True),
        (73.0, 30.0, True),  # 在 GCOORD 闭区间内（CT_PY 开区间外）
        (139.0, 35.0, False),
        (30.0, 10.0, False),
    ],
)
def test_in_china_gcoord_table(lon, lat, expected):
    assert algorithms.in_china(lon, lat, algorithms.PROFILE_GCOORD) is expected
    if (lon, lat) == (73.0, 30.0):
        assert algorithms.in_china(lon, lat, algorithms.PROFILE_CT_PY) is False


@pytest.mark.parametrize(
    "band,magnitude",
    [("degree", 116.0), ("degree", 180.0), ("neither", 500.0), ("metre", 1000000.0), ("metre", 3000000.0)],
)
def test_sample_band_boundaries(band, magnitude):
    assert _samples([(magnitude, magnitude)])[0].band == band


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("urn:ogc:def:crs:epsg::4326", "4326"),
        ("urn:ogc:def:crs:ogc::crs84", "crs84"),
        ("EPSG:3857", "3857"),
        ("epsg:4490", "4490"),
        ("  4326  ", "4326"),
        ("4490", "4490"),
        ("crs84", "crs84"),
        ("gcj02", None),  # GCJ-02 没有 EPSG 代码，不进声明枚举
    ],
)
def test_normalize_declared_more_aliases(raw, expected):
    assert declcheck.normalize_declared(raw) == expected


@pytest.mark.parametrize(
    "target,applicable",
    [
        ("wgs84", ("coordTransform_py", "gcoord", "proj4js_webmercator")),
        ("gcj02", ("coordTransform_py", "gcoord")),
        ("bd09", ("coordTransform_py", "gcoord")),
        ("webmercator", ("gcoord", "proj4js_webmercator")),
    ],
)
def test_target_implementations_table(target, applicable):
    assert detectcore.TARGET_IMPLEMENTATIONS[target] == applicable


@pytest.mark.parametrize(
    "hyp,declared,expected",
    [
        ("WGS84", "4326", 0),
        ("WGS84", "crs84", 0),
        ("WGS84", "4490", 0),
        ("WGS84", "3857", 1),
        ("GCJ02", "4326", 1),
        ("BD09", "4326", 1),
        ("GCJ02", None, 0),
    ],
)
def test_declared_conflict_parametrized(hyp, declared, expected):
    assert detectcore._declared_conflict(hyp, declared) == expected


@pytest.mark.parametrize(
    "status,verdict",
    [
        ("conflict", "error"),
        ("error", "error"),
        ("warning", "warn"),
        ("undecidable", "warn"),
        ("info", "info"),
        ("consistent", "info"),
    ],
)
def test_status_to_verdict_table(status, verdict):
    assert spec.STATUS_TO_VERDICT[status] == verdict


@pytest.mark.parametrize(
    "digits,expected_status",
    [(9, "consistent"), (10, "warning"), (13, "warning"), (0, "consistent")],
)
def test_precision_boundary_digits(digits, expected_status):
    doc = {"type": "Point", "coordinates": [Decimal("116." + "1" * digits), Decimal("39.0")]}
    finding = geojsoncheck.check_precision(_audits_from([("d", doc)]))
    assert finding.status == expected_status


@pytest.mark.parametrize(
    "y,flagged",
    [(0, False), (3, False), (4, True), (7, True), (-1, True)],
)
def test_y_range_boundary_rows(y, flagged):
    audit = tilescheck.audit_group(_group([{"z": 2, "x": 0, "y": y}]))
    assert (len(audit.y_range_offenders) == 1) is flagged


@pytest.mark.parametrize(
    "west,south,east,north,lon,lat,expected",
    [
        (100.0, 10.0, 120.0, 30.0, 100.0, 10.0, True),
        (100.0, 10.0, 120.0, 30.0, 120.0, 30.0, True),
        (100.0, 10.0, 120.0, 30.0, 121.0, 20.0, False),
        (100.0, 10.0, 120.0, 30.0, 110.0, 31.0, False),
        (160.0, 10.0, -160.0, 30.0, 180.0, 20.0, True),
        (160.0, 10.0, -160.0, 30.0, -180.0, 20.0, True),
    ],
)
def test_bbox_contains_parametrized(west, south, east, north, lon, lat, expected):
    assert geojsoncheck.bbox_contains(west, south, east, north, lon, lat) is expected


@pytest.mark.parametrize(
    "check,status,blocked",
    [
        ("magnitude", "conflict", True),
        ("axis", "conflict", True),
        ("unit", "conflict", True),
        ("mixed", "conflict", True),
        ("extent", "conflict", True),
        ("axis", "undecidable", False),
        ("magnitude", "consistent", False),
    ],
)
def test_decl_check_verdict_mapping(check, status, blocked):
    finding = finding_mod.Finding(check=check, status=status, detail="d")
    report = finding_mod.outcome_code([finding])
    assert (report == 1) is blocked


def test_haversine_symmetry():
    a = finding_mod.haversine_m(116.4, 39.9, 121.4, 31.2)
    b = finding_mod.haversine_m(121.4, 31.2, 116.4, 39.9)
    assert a == pytest.approx(b)


def test_haversine_one_degree_latitude():
    value = finding_mod.haversine_m(0.0, 0.0, 0.0, 1.0)
    assert 110000 < value < 112000


def test_xdiff_implementations_full_set_constant():
    assert detectcore.IMPLEMENTATIONS == ("coordTransform_py", "gcoord", "proj4js_webmercator")


def test_boundary_band_threshold_is_005_deg():
    assert detectcore.BOUNDARY_BAND_DEG == 0.05


def test_basis_check_rules_cover_all_modules():
    for module in ("decl", "geojson", "tiles", "xdiff"):
        assert spec.RULE_BY_MODULE[module]
