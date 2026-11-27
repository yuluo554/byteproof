"""``media-trace`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行，Go 源）里**被判定的那套函数仍然在、语义仍然是那一套**：
M1 八条结构规则、M2 六条时长/编辑表规则、M3 六条时间戳规则、M4 六条偏移/priming 规则、
M5 六条显示规则，以及 fail>gray>pass 的退出码优先级。

**没迁的部分逐条写在 ``docs/media-trace.md`` §6 的处置表里**（ISO BMFF 盒子解析、
字节读取、真实文件 I/O、报告排版、CLI）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 10 个判定包 `go test -json` 实跑 **X = 115 pass 事件**
（顶层 `func Test` 105；已剔除 `dist/` 副本、`internal/report`）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors.media_trace import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    judge,
    spec,
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
    RuleMissing,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "media-trace"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "media_trace"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "media-trace.basis.json"
THRESHOLDS_PATH = DATA_DIR / "media-trace.thresholds.json"
SAMPLE = ROOT / "samples" / "media-trace.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def _track(**extra):
    base = {
        "id": 1,
        "codec": "mp4a",
        "timescale": 90000,
        "duration": 90000,
        "tkhd_duration": 1000,
        "stts": [[30, 3000]],
        "elst": [],
        "first_pts": 0,
        "fragments": [],
        "declared_priming": 1024,
        "has_edts": True,
        "start_time": 0,
        "roll_distance": None,
    }
    base.update(extra)
    return base


def _facts(**extra):
    base = {
        "file_size": 1000,
        "boxes": [
            {"type": "ftyp", "offset": 0, "size": 24, "depth": 1},
            {"type": "moov", "offset": 24, "size": 500, "depth": 1},
            {"type": "mdat", "offset": 524, "size": 476, "depth": 1},
        ],
        "anomalies": [],
        "mdat": [{"offset": 524, "size": 476}],
        "moov_count": 1,
        "stco": [600],
        "ftyp": {"major": "isom", "compatible_brands": ["isom", "mp42"]},
        "movie": {"timescale": 1000, "duration": 1000, "tracks": [_track()]},
    }
    base.update(extra)
    return base


def _subject(**extra):
    return {"mode": "audit", "facts": _facts(**extra)}


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _codes(subject):
    return [record.evidence.get("code") for record in _evaluate(subject) if record.path.startswith("findings[")]


def _report(subject):
    return Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="test.json", records=tuple(_evaluate(subject)))


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG
    assert PACK.version == "1"


def test_pack_declares_mode_and_facts():
    assert PACK.input_fields == ("mode", "facts")


def test_builtin_modules_include_the_organ():
    assert "media_trace" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_modules_are_m1_to_m5():
    assert spec.MODULES == ("M1", "M2", "M3", "M4", "M5")


def test_sample_is_a_clean_audit():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert data["mode"] == "audit"
    assert data["facts"]["moov_count"] == 1


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


def test_every_rule_has_a_nominal_verdict():
    assert set(spec.RULE_IDS) == set(spec.VERDICTS)


def test_thresholds_code_rules_match_runtime():
    assert SETTINGS["code_rule"] == spec.CODE_RULE


def test_thresholds_policy_matches_runtime():
    policy = SETTINGS["policy"]
    assert policy["tick_tolerance"] == spec.TICK_TOLERANCE
    assert policy["timescale_suspect_below"] == spec.TIMESCALE_SUSPECT_BELOW
    assert policy["matrix_ortho_tolerance"] == spec.MATRIX_ORTHO_TOLERANCE
    assert policy["dts_regression_tolerance"] == spec.DTS_REGRESSION_TOLERANCE
    assert policy["rate_one"] == spec.RATE_ONE
    assert policy["q16_one"] == spec.Q16_ONE


def test_thresholds_known_priming_matches():
    assert SETTINGS["known_priming"] == spec.KNOWN_PRIMING


def test_thresholds_roll_distance_codecs_match():
    assert set(SETTINGS["roll_distance_codecs"]) == spec.ROLL_DISTANCE_CODECS


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("mt-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== M1 结构
def test_too_small_size():
    facts = _facts(anomalies=[{"kind": "too_small_size", "box_type": "free", "declared": 4, "offset": 10}])
    assert "too_small_size" in _codes(_subject(anomalies=facts["anomalies"]))


def test_max_depth():
    assert "max_depth_exceeded" in _codes(_subject(anomalies=[{"kind": "max_depth", "depth": 40, "offset": 9}]))


def test_mdat_truncated():
    facts = _facts(file_size=500)
    assert "truncated_mdat" in _codes(_subject(file_size=500))


def test_child_overrun():
    boxes = [
        {"type": "moov", "offset": 0, "size": 100, "depth": 1, "parent_end": 50},
    ]
    assert "child_overruns_parent" in _codes(_subject(boxes=boxes))


def test_mdat_not_truncated_at_exact_end():
    assert "truncated_mdat" not in _codes(_subject())


def test_duplicate_moov():
    assert "duplicate_moov" in _codes(_subject(moov_count=2))


def test_duplicate_moov_skips_stco_check():
    codes = _codes(_subject(moov_count=2, stco=[1]))
    assert "duplicate_moov" in codes
    assert "stco_out_of_mdat" not in codes


def test_duplicate_mdat():
    boxes = _facts()["boxes"] + [{"type": "mdat", "offset": 900, "size": 100, "depth": 1}]
    assert "duplicate_mdat" in _codes(_subject(boxes=boxes))


def test_stco_inside_mdat_is_clean():
    assert "stco_out_of_mdat" not in _codes(_subject(stco=[600]))


def test_stco_outside_mdat():
    assert "stco_out_of_mdat" in _codes(_subject(stco=[100]))


def test_stco_reports_only_first():
    records = _records(_subject(stco=[1, 2, 3]))
    assert len([record for record in records if record.evidence.get("code") == "stco_out_of_mdat"]) == 1


def test_ftyp_brand_mismatch():
    ftyp = {"major": "avc1", "compatible_brands": ["avc1"]}
    assert "ftyp_brand_mismatch" in _codes(_subject(ftyp=ftyp))


def test_ftyp_codec_major_with_isom_is_fine():
    ftyp = {"major": "avc1", "compatible_brands": ["isom", "avc1"]}
    assert "ftyp_brand_mismatch" not in _codes(_subject(ftyp=ftyp))


def test_ftyp_generic_major_is_fine():
    assert "ftyp_brand_mismatch" not in _codes(_subject())


def test_m1_boxes_must_have_int_offset():
    boxes = [{"type": "mdat", "offset": "0", "size": 1, "depth": 1}]
    with pytest.raises(ValueError):
        _evaluate(_subject(boxes=boxes))


def test_m1_boxes_must_be_objects():
    with pytest.raises(ValueError):
        _evaluate(_subject(boxes=["oops"]))


def test_m1_stco_must_be_ints():
    with pytest.raises(ValueError):
        _evaluate(_subject(stco=["x"]))


def test_m1_anomaly_has_module():
    records = _records(_subject(anomalies=[{"kind": "too_small_size", "box_type": "free", "declared": 4, "offset": 0}]))
    assert any(record.evidence.get("module") == "M1" for record in records if record.path.startswith("findings["))


# ================================================================== M2 时长
def test_duration_clean():
    assert "duration_mismatch" not in _codes(_subject())


def test_duration_mismatch():
    movie = {"timescale": 1000, "duration": 2000, "tracks": [_track()]}
    assert "duration_mismatch" in _codes(_subject(movie=movie))


def test_duration_tolerance_is_one_tick():
    movie = {"timescale": 1000, "duration": 1001, "tracks": [_track()]}
    assert "duration_mismatch" not in _codes(_subject(movie=movie))


def test_duration_two_ticks_is_mismatch():
    movie = {"timescale": 1000, "duration": 1002, "tracks": [_track()]}
    assert "duration_mismatch" in _codes(_subject(movie=movie))


def test_duration_unknown():
    movie = {"timescale": 1000, "duration": 0, "tracks": [_track(stts=[])]}
    assert "duration_unknown" in _codes(_subject(movie=movie))


def test_duration_unknown_is_gray():
    movie = {"timescale": 1000, "duration": 0, "tracks": [_track(stts=[])]}
    record = [record for record in _evaluate(_subject(movie=movie)) if record.evidence.get("code") == "duration_unknown"][0]
    assert record.evidence["status"] == "gray"


def test_duration_unknown_not_when_samples_exist():
    movie = {"timescale": 1000, "duration": 0, "tracks": [_track()]}
    assert "duration_unknown" not in _codes(_subject(movie=movie))


def test_elst_rate_not_one():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=[{"segment_duration": 1000, "media_time": 0, "rate": 32768}])]}
    assert "elst_item_rate_not_one" in _codes(_subject(movie=movie))


def test_elst_rate_one_is_clean():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=[{"segment_duration": 1000, "media_time": 0, "rate": 65536}])]}
    assert "elst_item_rate_not_one" not in _codes(_subject(movie=movie))


def test_empty_edit_after_media():
    elst = [{"segment_duration": 500, "media_time": 0, "rate": 65536}, {"segment_duration": 500, "media_time": -1, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst)]}
    assert "empty_edit" in _codes(_subject(movie=movie))


def test_empty_edit_zero_duration():
    elst = [{"segment_duration": 0, "media_time": -1, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst)]}
    assert "empty_edit" in _codes(_subject(movie=movie))


def test_empty_edit_first_is_clean():
    elst = [{"segment_duration": 500, "media_time": -1, "rate": 65536}, {"segment_duration": 500, "media_time": 0, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst)]}
    assert "empty_edit" not in _codes(_subject(movie=movie))


def test_elst_order_suspect():
    elst = [
        {"segment_duration": 500, "media_time": 0, "rate": 65536},
        {"segment_duration": 500, "media_time": 500, "rate": 65536},
    ]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst, first_pts=600)]}
    assert "elst_item_order_suspect" in _codes(_subject(movie=movie))


def test_elst_order_first_segment_is_clean():
    elst = [{"segment_duration": 1000, "media_time": 0, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst, first_pts=100)]}
    assert "elst_item_order_suspect" not in _codes(_subject(movie=movie))


def test_first_pts_outside_media():
    elst = [{"segment_duration": 900, "media_time": 500, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst, first_pts=50, duration=90000)]}
    assert "first_pts_outside_media" in _codes(_subject(movie=movie))


def test_first_pts_inside_media_is_clean():
    elst = [{"segment_duration": 900, "media_time": 500, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst, first_pts=600, duration=90000)]}
    assert "first_pts_outside_media" not in _codes(_subject(movie=movie))


def test_legal_trim_is_not_first_pts_outside():
    elst = [{"segment_duration": 1000, "media_time": 100, "rate": 65536}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=elst, first_pts=0, duration=90000)]}
    assert "first_pts_outside_media" not in _codes(_subject(movie=movie))


def test_movie_must_be_object():
    with pytest.raises(ValueError):
        _evaluate(_subject(movie=[]))


# ================================================================== M3 时间戳
def test_zero_duration_entry():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(stts=[[10, 0]])]}
    assert "zero_duration_entry" in _codes(_subject(movie=movie))


def test_vfr_detected():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(stts=[[10, 3000], [20, 3000]])]}
    assert "vfr_detected" in _codes(_subject(movie=movie))


def test_single_stts_entry_is_not_vfr():
    assert "vfr_detected" not in _codes(_subject())


def test_timescale_suspect():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(timescale=50, duration=50, stts=[[1, 1]])]}
    assert "timescale_suspect" in _codes(_subject(movie=movie))


def test_timescale_at_floor_is_fine():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(timescale=100, duration=100, stts=[[1, 1]])]}
    assert "timescale_suspect" not in _codes(_subject(movie=movie))


def test_dts_overflow():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(stts=[[2, 2 ** 31]])]}
    assert "dts_overflow_risk" in _codes(_subject(movie=movie))


def test_dts_overflow_skips_timescale_suspect():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(timescale=50, duration=50, stts=[[2, 2 ** 31]])]}
    codes = _codes(_subject(movie=movie))
    assert "dts_overflow_risk" in codes
    assert "timescale_suspect" not in codes


def test_tfdt_regression():
    fragments = [{"index": 0, "tfdt": 100, "duration": 10, "version": 1}, {"index": 1, "tfdt": 50, "duration": 10, "version": 1}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(fragments=fragments)]}
    assert "tfdt_regression" in _codes(_subject(movie=movie))


def test_tfdt_monotonic_is_clean():
    fragments = [{"index": 0, "tfdt": 10, "duration": 10, "version": 1}, {"index": 1, "tfdt": 20, "duration": 10, "version": 1}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(fragments=fragments)]}
    assert "tfdt_regression" not in _codes(_subject(movie=movie))


def test_tfdt_v0_overflow():
    fragments = [{"index": 0, "tfdt": 2 ** 32 - 1, "duration": 10, "version": 0}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(fragments=fragments)]}
    assert "dts_overflow_risk" in _codes(_subject(movie=movie))


def test_tfdt_v1_does_not_overflow():
    fragments = [{"index": 0, "tfdt": 2 ** 32 - 1, "duration": 10, "version": 1}]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(fragments=fragments)]}
    assert "dts_overflow_risk" not in _codes(_subject(movie=movie))


def test_zero_duration_evidence_nominal():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(stts=[[10, 3000], [1, 0]])]}
    record = [r for r in _evaluate(_subject(movie=movie)) if r.evidence.get("code") == "zero_duration_entry"][0]
    assert record.evidence["values"][1]["value"] == 3000


# ================================================================== M4 偏移
def test_priming_undeclared():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(declared_priming=None, has_edts=False)]}
    assert "priming_undeclared" in _codes(_subject(movie=movie))


def test_priming_declared_is_clean():
    assert "priming_undeclared" not in _codes(_subject())


def test_priming_mismatch():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(declared_priming=512)]}
    assert "priming_mismatch" in _codes(_subject(movie=movie))


def test_unknown_codec_priming_is_gray():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(codec="av01", declared_priming=None)]}
    record = [r for r in _evaluate(_subject(movie=movie)) if r.evidence.get("code") == "unknown_codec_priming"][0]
    assert record.evidence["status"] == "gray"


def test_start_trim():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(elst=[{"segment_duration": 1000, "media_time": 100, "rate": 65536}])]}
    assert "start_trim" in _codes(_subject(movie=movie))


def test_no_roll_distance():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(codec="ac-3", declared_priming=0, roll_distance=None)]}
    assert "no_roll_distance" in _codes(_subject(movie=movie))


def test_roll_distance_present_is_clean():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(codec="ac-3", declared_priming=0, roll_distance=2)]}
    assert "no_roll_distance" not in _codes(_subject(movie=movie))


def test_no_edts_but_nonzero_start():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(start_time=500, has_edts=False)]}
    assert "no_edts_but_nonzero_start" in _codes(_subject(movie=movie))


def test_zero_start_without_edts_is_clean():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(start_time=0, has_edts=False)]}
    assert "no_edts_but_nonzero_start" not in _codes(_subject(movie=movie))


def test_known_priming_table_has_aac():
    assert spec.KNOWN_PRIMING["aac"] == 1024


def test_roll_distance_codecs_are_audio():
    assert "ac-3" in spec.ROLL_DISTANCE_CODECS


# ================================================================== M5 显示
def _display(**extra):
    base = {
        "matrix": [65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824],
        "width": 64,
        "height": 48,
        "stored_width": 64,
        "stored_height": 48,
        "sar": [1, 1],
        "colr": [],
        "hdr": False,
        "hdr_metadata": None,
        "hdr_range_ok": True,
    }
    base.update(extra)
    return base


def test_identity_matrix_is_orthogonal():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display())]}
    assert "matrix_not_orthogonal" not in _codes(_subject(movie=movie))


def test_non_orthogonal_matrix():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(matrix=[65536, 0, 0, 32768, 65536, 0, 0, 0, 1073741824]))]}
    assert "matrix_not_orthogonal" in _codes(_subject(movie=movie))


def test_rotation_without_dimension_swap():
    matrix = [0, 65536, 0, -65536, 0, 0, 0, 0, 1073741824]
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(matrix=matrix))]}
    assert "rotation_dimension_conflict" in _codes(_subject(movie=movie))


def test_rotation_with_dimension_swap_is_clean():
    matrix = [0, 65536, 0, -65536, 0, 0, 0, 0, 1073741824]
    display = _display(matrix=matrix, width=48, height=64)
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=display)]}
    assert "rotation_dimension_conflict" not in _codes(_subject(movie=movie))


def test_sar_with_zero():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(sar=[0, 1]))]}
    assert "sar_dar_conflict" in _codes(_subject(movie=movie))


def test_sar_positive_is_clean():
    assert "sar_dar_conflict" not in _codes(_subject(movie={"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display())]}))


def test_dar_conflict_flag():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(dar_conflict=True))]}
    assert "sar_dar_conflict" in _codes(_subject(movie=movie))


def test_colr_multi_instance():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(colr=[{"type": "nclx"}, {"type": "prof"}]))]}
    record = [r for r in _evaluate(_subject(movie=movie)) if r.evidence.get("code") == "colr_multi_instance"][0]
    assert record.evidence["values"][0]["value"] == 2


def test_single_colr_is_clean():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(colr=[{"type": "nclx"}]))]}
    assert "colr_multi_instance" not in _codes(_subject(movie=movie))


def test_hdr_metadata_missing_is_gray():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(hdr=True, hdr_metadata=None))]}
    record = [r for r in _evaluate(_subject(movie=movie)) if r.evidence.get("code") == "hdr_metadata_missing"][0]
    assert record.evidence["status"] == "gray"


def test_hdr_metadata_present_is_clean():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(hdr=True, hdr_metadata={"max": 1}))]}
    assert "hdr_metadata_missing" not in _codes(_subject(movie=movie))


def test_hdr_range_suspect():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=_display(hdr=True, hdr_metadata={"max": 1}, hdr_range_ok=False))]}
    assert "hdr_range_suspect" in _codes(_subject(movie=movie))


def test_display_missing_is_skipped():
    movie = {"timescale": 1000, "duration": 1000, "tracks": [_track(display=None)]}
    assert "matrix_not_orthogonal" not in _codes(_subject(movie=movie))


# ================================================================== 入口/门禁
def test_clean_sample_passes():
    assert _report(_subject()).exit_code() == EXIT_OK


def test_fail_triggers_gate():
    movie = {"timescale": 1000, "duration": 2000, "tracks": [_track()]}
    record = _records(_subject(movie=movie), spec.RULE_GATE)[0]
    assert record.evidence["source_exit_code"] == 1
    assert _report(_subject(movie=movie)).exit_code() == EXIT_BLOCKED


def test_gray_triggers_gate_with_exit_two():
    subject = _subject(anomalies=[{"kind": "noop"}])
    movie = {"timescale": 1000, "duration": 0, "tracks": [_track(stts=[])]}
    record = _records(_subject(movie=movie), spec.RULE_GATE)[0]
    assert record.evidence["source_exit_code"] == 2


def test_no_findings_no_gate():
    assert _records(_subject(), spec.RULE_GATE) == []


def test_summary_counts_fail_and_gray():
    movie = {"timescale": 1000, "duration": 0, "tracks": [_track(stts=[])]}
    summary = _records(_subject(movie=movie), spec.RULE_SUMMARY)[0]
    assert summary.evidence["gray"] == 1
    assert summary.evidence["verdict"] == "inconclusive"


def test_modules_filter_limits_scope():
    subject = {"mode": "audit", "facts": _facts(movie={"timescale": 1000, "duration": 2000, "tracks": [_track()]}), "modules": ["M1"]}
    assert "duration_mismatch" not in _codes(subject)


def test_modules_must_be_known():
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "facts": _facts(), "modules": ["M9"]})


def test_mode_must_be_audit():
    with pytest.raises(ValueError):
        _evaluate({"mode": "collect", "facts": _facts()})


def test_missing_facts_is_input_error():
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit"})


def test_missing_rule_is_contract_violation():
    with pytest.raises(RuleMissing):
        _evaluate(_subject(), basis=Basis.empty("1"))


def test_record_ids_unique():
    movie = {"timescale": 1000, "duration": 2000, "tracks": [_track(stts=[[10, 0]])]}
    ids = [record.id for record in _report(_subject(movie=movie)).records]
    assert len(ids) == len(set(ids))


def test_every_record_has_complete_basis():
    for record in _evaluate(_subject()):
        assert record.basis is not None
        assert record.basis.rule_version == "1"


def test_finding_records_are_non_blocking():
    movie = {"timescale": 1000, "duration": 2000, "tracks": [_track()]}
    for record in _evaluate(_subject(movie=movie)):
        if record.rule_id != spec.RULE_GATE:
            assert record.verdict in (INFO, WARN)


# ================================================================== CLI
def test_cli_sample_exits_zero(capsys):
    code = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["organ"] == SLUG


def test_cli_fail_exits_one(tmp_path, capsys):
    subject = _subject(movie={"timescale": 1000, "duration": 2000, "tracks": [_track()]})
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_BLOCKED


def test_cli_bad_mode_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "nope", "facts": {}}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_INPUT


def test_cli_missing_rule_exits_three(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject(), ensure_ascii=False), encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(empty), "--json"]) == EXIT_CONTRACT


def test_cli_basis_is_optional(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject(), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--json"]) == EXIT_OK


def test_cli_double_run_is_byte_identical(capsys):
    argv = ["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"]
    assert cli.main(argv) == EXIT_OK
    first = capsys.readouterr().out
    assert cli.main(argv) == EXIT_OK
    second = capsys.readouterr().out
    assert first == second


def test_cli_list_contains_the_organ(capsys):
    assert cli.main(["list"]) == EXIT_OK
    assert SLUG in capsys.readouterr().out


# ================================================================== 器官契约（静态）
def _organ_sources():
    return sorted(path for path in ORGAN_DIR.glob("*.py"))


def test_organ_has_no_network_imports():
    forbidden = {"requests", "socket", "http", "urllib", "ftplib", "smtplib"}
    hits = []
    for path in _organ_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_does_not_open_files_or_read_environment():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                hits.append((path.name, "open"))
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_read_the_wall_clock():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow", "today", "time"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_import_the_old_package():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "mediatrace":
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "mediatrace":
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_does_not_spawn_subprocesses():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "subprocess":
                        hits.append((path.name, alias.name))
    assert hits == []


def test_organ_does_not_parse_boxes():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in ("struct.unpack", "read_box", "mmap"):
            if token in text:
                hits.append((path.name, token))
    assert hits == []


def test_organ_data_lives_under_package_data_directory():
    assert BASIS_PATH.parent == DATA_DIR
    assert THRESHOLDS_PATH.parent == DATA_DIR
    assert not list(ORGAN_DIR.glob("*.json"))


def test_organ_never_uses_lossy_codec_error_handlers():
    hits = []
    for path in _organ_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "errors" and isinstance(keyword.value, ast.Constant) and keyword.value.value in ("replace", "ignore"):
                    hits.append((path.name, keyword.value.value))
    assert hits == []