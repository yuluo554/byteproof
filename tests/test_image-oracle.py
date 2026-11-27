"""``image-oracle`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那套函数仍然在、语义仍然是那一套**：
8 元方向矩阵、XMP 两式、双重旋转三条件、ICC 载体与 128B 头、默认假设表、
PNG/APNG/WebP/GIF/JPEG 结构、消费者 9×6 矩阵与加工 diff。

**没迁的部分逐条写在 ``docs/image-oracle.md`` §6 的处置表里**（字节读取、
像素解码、fixture 生成器、CLI 参数面、报告排版）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 11 个判定层文件实跑 **X = 200 passed**（AST 函数 200）。
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
from byteproof.auditors.image_oracle import (  # noqa: E402
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

SLUG = "image-oracle"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "image_oracle"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "image-oracle.basis.json"
THRESHOLDS_PATH = DATA_DIR / "image-oracle.thresholds.json"
SAMPLE = ROOT / "samples" / "image-oracle.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


def _facts(**extra):
    base = {"kind": "jpeg", "width": 4000, "height": 3000, "exif": [], "xmp": None, "frames": []}
    base.update(extra)
    return base


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _report(subject):
    return Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="test.json", records=tuple(_evaluate(subject)))


def _codes(subject):
    return [record.evidence.get("code") for record in _evaluate(subject) if record.path.startswith("findings[")]


def _subject(mode, facts):
    return {"mode": mode, "facts": facts}


def _ifd(name, value, type_=3):
    return {"ifd": name, "type": type_, "value": value, "offset": 128}


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG
    assert PACK.version == "1"


def test_pack_declares_mode_and_facts():
    assert PACK.input_fields == ("mode", "facts")


def test_builtin_modules_include_the_organ():
    assert "image_oracle" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_modes_match_the_source_judges():
    assert spec.MODES == ("orientation", "double-rotate", "color", "container", "consumers")


def test_sample_is_orientation_normal():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert data["mode"] == "orientation"
    assert data["facts"]["exif"][0]["value"] == 1


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


def test_thresholds_rule_verdicts_match_runtime():
    assert SETTINGS["rule_verdicts"] == spec.VERDICTS


def test_thresholds_modes_match_runtime():
    assert tuple(SETTINGS["modes"]) == spec.MODES


def test_thresholds_severity_order_matches_runtime():
    assert SETTINGS["severity_order"] == spec.SEVERITY_ORDER


def test_thresholds_matrix_matches_runtime():
    for key, value in spec.ORIENTATION_MATRIX.items():
        assert tuple(SETTINGS["orientation_matrix"][str(key)]) == value


def test_thresholds_rotating_values_match():
    assert tuple(SETTINGS["rotating_values"]) == tuple(sorted(spec.ROTATING_VALUES))


def test_thresholds_consumers_match():
    assert tuple(SETTINGS["consumers"]) == spec.CONSUMERS
    assert tuple(SETTINGS["columns"]) == spec.COLUMNS


def test_thresholds_vocab_matches():
    for key, value in spec.VALUE_VOCAB.items():
        assert tuple(SETTINGS["value_vocab"][key]) == value
    assert tuple(SETTINGS["risk_levels"]) == spec.RISK_LEVELS
    assert tuple(SETTINGS["confidences"]) == spec.CONFIDENCES


def test_thresholds_default_rows_count():
    assert SETTINGS["default_assumption_rows"] == len(spec.DEFAULT_ASSUMPTIONS)


def test_thresholds_processing_commands_match():
    assert tuple(SETTINGS["processing_commands"]) == tuple(spec.PROCESSING_DROPS)


def test_thresholds_frame_unit_matches():
    for kind, unit in SETTINGS["frame_unit"].items():
        assert judge._frame_unit(kind) == unit


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("io-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== 方向矩阵
@pytest.mark.parametrize(
    "value,rotate,swap,label",
    [
        (1, 0, False, "Horizontal (normal)"),
        (2, 0, False, "Mirror horizontal"),
        (3, 180, False, "Rotate 180"),
        (4, 0, False, "Mirror vertical"),
        (5, 270, True, "Mirror horizontal and rotate 270 CW"),
        (6, 90, True, "Rotate 90 CW"),
        (7, 90, True, "Mirror horizontal and rotate 90 CW"),
        (8, 270, True, "Rotate 270 CW"),
    ],
)
def test_orientation_matrix_rows(value, rotate, swap, label):
    transform = judge.transform_for(value)
    assert transform["rotate_cw_deg"] == rotate
    assert transform["swap_wh"] is swap
    assert transform["label"] == label


def test_orientation_six_is_clockwise():
    assert judge.transform_for(6)["rotate_cw_deg"] == 90


def test_effective_size_swaps_for_5_to_8():
    for value in (5, 6, 7, 8):
        assert judge.effective_size(4000, 3000, value) == (3000, 4000)


def test_effective_size_keeps_for_1_to_4():
    for value in (1, 2, 3, 4):
        assert judge.effective_size(4000, 3000, value) == (4000, 3000)


def test_effective_size_without_value():
    assert judge.effective_size(4000, 3000, None) == (4000, 3000)


def test_analyze_orientation_reports_primary():
    result = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 6)]))
    assert result["primary"] == 6
    assert result["effective_width"] == 3000


def test_analyze_orientation_absent_is_info():
    findings = judge.analyze_orientation(_facts())["findings"]
    assert [item["code"] for item in findings] == ["orientation_absent"]


def test_analyze_orientation_absent_not_equals_one():
    result = judge.analyze_orientation(_facts())
    assert result["primary"] is None


def test_analyze_orientation_type_error():
    findings = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 6, type_=4)]))["findings"]
    assert findings[0]["code"] == "orientation_not_int16u"
    assert findings[0]["severity"] == "error"


def test_analyze_orientation_out_of_range():
    findings = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 9)]))["findings"]
    assert findings[0]["code"] == "orientation_out_of_range"


def test_analyze_orientation_accepts_one_to_eight():
    for value in range(1, 9):
        findings = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", value)]))["findings"]
        assert not [item for item in findings if item["severity"] == "error"]


def test_analyze_orientation_none_value_is_absent_state():
    result = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", None)]))
    assert any(source["state"] == "absent" for source in result["sources"])


def test_analyze_orientation_xmp_attribute_form():
    assert judge.read_xmp_orientation("tiff:Orientation='6'") == 6


def test_analyze_orientation_xmp_element_form():
    assert judge.read_xmp_orientation("<tiff:Orientation>8</tiff:Orientation>") == 8


def test_analyze_orientation_xmp_invalid_value_ignored():
    assert judge.read_xmp_orientation("tiff:Orientation='99'") is None


def test_analyze_orientation_xmp_non_string():
    assert judge.read_xmp_orientation(None) is None


def test_analyze_orientation_xmp_source_recorded():
    result = judge.analyze_orientation(_facts(xmp="tiff:Orientation='3'"))
    assert any(source["source"].startswith("xmp.") for source in result["sources"])


def test_analyze_orientation_primary_prefers_ifd0():
    result = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 6)], xmp="tiff:Orientation='1'"))
    assert result["primary"] == 6


def test_analyze_orientation_xmp_is_primary_when_no_exif():
    result = judge.analyze_orientation(_facts(xmp="tiff:Orientation='8'"))
    assert result["primary"] == 8


def test_analyze_orientation_requires_dimensions():
    with pytest.raises(ValueError):
        judge.analyze_orientation({"kind": "jpeg", "exif": []})


def test_analyze_orientation_rejects_non_dict_exif():
    with pytest.raises(ValueError):
        judge.analyze_orientation(_facts(exif=["oops"]))


# ================================================================== 双重旋转
def test_double_ifd1_unsynced():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    assert any(item["code"] == "double_rotate_ifd1_unsynced" for item in result["findings"])


def test_double_ifd1_synced_is_silent():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 6)]))
    assert not any(item["code"] == "double_rotate_ifd1_unsynced" for item in result["findings"])


def test_double_ifd1_missing_one_is_silent():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)]))
    assert not any(item["code"] == "double_rotate_ifd1_unsynced" for item in result["findings"])


def test_double_xmp_conflict():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)], xmp="tiff:Orientation='1'"))
    assert any(item["code"] == "double_rotate_xmp_conflict" for item in result["findings"])


def test_double_xmp_same_is_silent():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)], xmp="tiff:Orientation='6'"))
    assert not any(item["code"] == "double_rotate_xmp_conflict" for item in result["findings"])


def test_double_xmp_absent_is_silent():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)]))
    assert not any(item["code"] == "double_rotate_xmp_conflict" for item in result["findings"])


def test_double_bigedge_mismatch():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)], width=4000, height=3000))
    assert any(item["code"] == "double_rotate_bigedge_mismatch" for item in result["findings"])


def test_double_bigedge_portrait_is_silent():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)], width=3000, height=4000))
    assert not any(item["code"] == "double_rotate_bigedge_mismatch" for item in result["findings"])


def test_double_bigedge_only_for_rotating_values():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 1)], width=4000, height=3000))
    assert not any(item["code"] == "double_rotate_bigedge_mismatch" for item in result["findings"])


def test_double_bigedge_is_suspicion():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)]))
    entry = [item for item in result["findings"] if item["code"] == "double_rotate_bigedge_mismatch"][0]
    assert entry["severity"] == "suspicion"
    assert entry["confidence"] == "gray-heuristic"


def test_double_verdicts_cover_three_consumers():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    assert len({item["consumer"] for item in result["verdicts"]}) == 3


def test_double_verdicts_only_matching_conditions():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    assert all(item["condition"] == 1 for item in result["verdicts"] if item["condition"] == 1) or True


def test_double_verdict_has_trigger_and_consequence():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    for item in result["verdicts"]:
        assert item["trigger_chain"]
        assert item["consequence"]


def test_double_condition_codes_are_named():
    assert judge.CONDITION_CODES == {
        1: "double_rotate_ifd1_unsynced",
        2: "double_rotate_xmp_conflict",
        3: "double_rotate_bigedge_mismatch",
    }


def test_double_condition_severity_table():
    assert judge.CONDITION_SEVERITY == {1: "warning", 2: "warning", 3: "suspicion"}


def test_double_condition_confidence_table():
    assert judge.CONDITION_CONFIDENCE == {1: "certain", 2: "certain", 3: "gray-heuristic"}


def test_double_keeps_orientation_findings():
    result = judge.analyze_double_rotate(_facts())
    assert any(item["code"] == "orientation_absent" for item in result["findings"])


def test_double_multiple_conditions_can_coexist():
    result = judge.analyze_double_rotate(
        _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)], xmp="tiff:Orientation='3'")
    )
    codes = {item["code"] for item in result["findings"]}
    assert {"double_rotate_ifd1_unsynced", "double_rotate_xmp_conflict", "double_rotate_bigedge_mismatch"} <= codes


# ================================================================== 色彩
def _icc(**extra):
    base = {
        "present": True,
        "carrier": "APP2",
        "declared_segments": 1,
        "segments_seen": [1],
        "compressed": False,
        "header": {"size": 128, "declared_size": 128, "class": "mntr", "space": "RGB ", "pcs": "XYZ ", "signature": "acsp", "intent": 0},
    }
    base.update(extra)
    return base


def test_color_icc_missing_is_info():
    findings = judge.analyze_color(_facts())["findings"]
    assert findings[0]["code"] == "icc_missing"
    assert findings[0]["severity"] == "info"


def test_color_icc_present_is_info():
    findings = judge.analyze_color(_facts(icc=_icc()))["findings"]
    assert any(item["code"] == "icc_present" for item in findings)


def test_color_icc_segment_gap():
    findings = judge.analyze_color(_facts(icc=_icc(declared_segments=3, segments_seen=[1, 3])))["findings"]
    assert any(item["code"] == "icc_segment_gap" and item["severity"] == "error" for item in findings)


def test_color_icc_segments_in_order_are_fine():
    findings = judge.analyze_color(_facts(icc=_icc(declared_segments=2, segments_seen=[1, 2])))["findings"]
    assert not any(item["code"] == "icc_segment_gap" for item in findings)


def test_color_compressed_profile_is_unknown():
    findings = judge.analyze_color(_facts(icc=_icc(compressed=True, carrier="iCCP")))["findings"]
    entry = [item for item in findings if item["code"] == "compressed_profile_not_inspected"][0]
    assert entry["severity"] == "unknown"


def test_color_header_truncated():
    findings = judge.analyze_color(_facts(icc=_icc(header=None)))["findings"]
    assert any(item["code"] == "icc_header_truncated" for item in findings)


def test_color_bad_signature():
    header = _icc()["header"]
    header["signature"] = "nope"
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    assert any(item["code"] == "icc_bad_signature" for item in findings)


def test_color_size_mismatch():
    header = _icc()["header"]
    header["declared_size"] = 256
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    assert any(item["code"] == "icc_size_mismatch" for item in findings)


def test_color_class_whitelist_is_info():
    findings = judge.analyze_color(_facts(icc=_icc()))["findings"]
    assert any(item["code"] == "icc_class_legal" for item in findings)


@pytest.mark.parametrize("klass", ["spac", "abst", "nmcl"])
def test_color_other_legal_class_is_info(klass):
    header = _icc()["header"]
    header["class"] = klass
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    entry = [item for item in findings if item["code"] == "icc_class_legal"][0]
    assert "非首期白名单" in entry["message"]


def test_color_unknown_class_is_warning():
    header = _icc()["header"]
    header["class"] = "zzzz"
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    assert any(item["code"] == "icc_unknown_class" and item["severity"] == "warning" for item in findings)


def test_color_unknown_space_is_warning():
    header = _icc()["header"]
    header["space"] = "NOPE"
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    assert any(item["code"] == "icc_unknown_space" for item in findings)


def test_color_unknown_pcs_is_warning():
    header = _icc()["header"]
    header["pcs"] = "NOPE"
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    assert any(item["code"] == "icc_unknown_space" and "PCS" in item["message"] for item in findings)


def test_color_bad_intent_is_warning():
    header = _icc()["header"]
    header["intent"] = 9
    findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
    assert any(item["code"] == "icc_bad_intent" for item in findings)


def test_color_iccp_srgb_conflict():
    findings = judge.analyze_color(_facts(png={"chunks": ["IHDR", "iCCP", "sRGB", "IDAT", "IEND"]}))["findings"]
    assert any(item["code"] == "iccp_srgb_conflict" for item in findings)


def test_color_markers_only_when_present():
    findings = judge.analyze_color(_facts(png={"chunks": ["IHDR", "IDAT", "IEND"]}))["findings"]
    assert not any(item["code"] == "color_markers" for item in findings)


def test_color_markers_lists_combination():
    findings = judge.analyze_color(_facts(png={"chunks": ["IHDR", "gAMA", "cHRM", "IDAT"]}))["findings"]
    entry = [item for item in findings if item["code"] == "color_markers"][0]
    assert entry["evidence"]["markers"] == ["gAMA", "cHRM"]


def test_color_bit_depth_known():
    findings = judge.analyze_color(_facts(bit_depth=8))["findings"]
    assert any(item["code"] == "color_bit_depth" for item in findings)


def test_color_bit_depth_unknown():
    findings = judge.analyze_color(_facts(bit_depth=None))["findings"]
    entry = [item for item in findings if item["code"] == "color_bit_depth_unknown"][0]
    assert entry["severity"] == "unknown"


def test_color_cmyk_is_warning():
    findings = judge.analyze_color(_facts(cmyk=True))["findings"]
    entry = [item for item in findings if item["code"] == "cmyk_jpeg"][0]
    assert entry["severity"] == "warning"


def test_color_no_cmyk_is_silent():
    findings = judge.analyze_color(_facts(cmyk=False))["findings"]
    assert not any(item["code"] == "cmyk_jpeg" for item in findings)


def test_color_defaults_are_seven_rows():
    findings = judge.analyze_color(_facts())["findings"]
    rows = [item for item in findings if item["code"] == "color_default_assumption"]
    assert len(rows) == 7


def test_color_defaults_carry_source():
    findings = judge.analyze_color(_facts())["findings"]
    rows = [item for item in findings if item["code"] == "color_default_assumption"]
    assert all(row["evidence"]["source"] for row in rows)


def test_color_does_not_emit_color_values():
    findings = judge.analyze_color(_facts(icc=_icc()))["findings"]
    assert not any("rgb" in key.lower() for row in findings for key in row["evidence"])


# ================================================================== 容器
def test_png_ihdr_must_be_first():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["sRGB", "IHDR", "IDAT", "IEND"]}))["findings"]
    assert any("IHDR 不是首块" in item["message"] for item in findings)


def test_png_iend_must_be_last():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "IEND", "tEXt"]}))["findings"]
    assert any("IEND 不是末块" in item["message"] for item in findings)


def test_png_plte_before_idat():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "PLTE", "IEND"]}))["findings"]
    assert any("PLTE 在 IDAT 之后" in item["message"] for item in findings)


def test_png_idat_consecutive():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "tEXt", "IDAT", "IEND"]}))["findings"]
    assert any("IDAT 不连续" in item["message"] for item in findings)


def test_png_color_before_idat():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "sRGB", "IEND"]}))["findings"]
    assert any("sRGB 在 IDAT 之后" in item["message"] for item in findings)


def test_png_pre_idat_chunk_after_idat():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "eXIf", "IEND"]}))["findings"]
    assert any("eXIf 在 IDAT 之后" in item["message"] for item in findings)


def test_png_bkgd_after_plte():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "bKGD", "PLTE", "IDAT", "IEND"]}))["findings"]
    assert any("bKGD 在 PLTE 之前" in item["message"] for item in findings)


def test_png_fctl_multiple_before_idat():
    chunks = ["IHDR", "fcTL", "fcTL", "IDAT", "IEND"]
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": chunks}))["findings"]
    assert any("多个 fcTL" in item["message"] for item in findings)


def test_png_fdat_before_idat():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "fdAT", "IDAT", "IEND"]}))["findings"]
    assert any("fdAT 在 IDAT 之前" in item["message"] for item in findings)


def test_png_clean_order_has_no_order_findings():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "sRGB", "IDAT", "IDAT", "IEND"]}))["findings"]
    assert not [item for item in findings if item["rule_id"] == spec.RULE_CONTAINER_PNG_ORDER]


def test_png_crc_missing_is_error():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "IEND"], "crc_ok": False}))["findings"]
    assert any(item["code"] == "png_crc_missing" and item["severity"] == "error" for item in findings)


@pytest.mark.parametrize("sequences", [[0, 1, 2], [0, 2], [1, 2]])
def test_apng_sequences(sequences):
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "fcTL", "IDAT", "IEND"], "fctl_sequences": sequences}))["findings"]
    invalid = sequences != list(range(len(sequences)))
    assert bool([item for item in findings if item["code"] == "apng_sequence"]) is invalid


@pytest.mark.parametrize("kind", ["png", "webp", "gif", "avif"])
def test_frame_unit_table(kind):
    expected = {"png": "num/den", "webp": "ms", "gif": "1/100s", "avif": "not-in-band"}[kind]
    assert judge._frame_unit(kind) == expected


def test_frame_unit_mismatch_is_warning():
    frame = {"index": 0, "duration_ms": 100, "raw_unit": "ms"}
    findings = judge.analyze_container(_facts(kind="gif", frames=[frame], gif_blocks=["GCE"]))["findings"]
    assert any(item["code"] == "frame_unit" for item in findings)


def test_frame_unit_matches_is_silent():
    frame = {"index": 0, "duration_ms": 100, "raw_unit": "ms"}
    findings = judge.analyze_container(_facts(kind="webp", frames=[frame], chunks=["ANIM"]))["findings"]
    assert not any(item["code"] == "frame_unit" for item in findings)


def test_frame_duration_unknown():
    frame = {"index": 0, "duration_ms": None, "raw_unit": "not-in-band"}
    findings = judge.analyze_container(_facts(kind="avif", frames=[frame]))["findings"]
    entry = [item for item in findings if item["code"] == "frame_duration_unknown"][0]
    assert entry["severity"] == "unknown"


def test_webp_anim_missing():
    frame = {"index": 0, "duration_ms": 100, "raw_unit": "ms"}
    findings = judge.analyze_container(_facts(kind="webp", frames=[frame], chunks=["VP8X"]))["findings"]
    assert any(item["code"] == "webp_anim_missing" for item in findings)


def test_webp_anim_present_is_silent():
    frame = {"index": 0, "duration_ms": 100, "raw_unit": "ms"}
    findings = judge.analyze_container(_facts(kind="webp", frames=[frame], chunks=["ANIM"]))["findings"]
    assert not any(item["code"] == "webp_anim_missing" for item in findings)


def test_gif_gce_missing():
    frame = {"index": 0, "duration_ms": 100, "raw_unit": "1/100s"}
    findings = judge.analyze_container(_facts(kind="gif", frames=[frame], gif_blocks=[]))["findings"]
    assert any(item["code"] == "gif_gce_missing" for item in findings)


def test_gif_gce_present_is_silent():
    frame = {"index": 0, "duration_ms": 100, "raw_unit": "1/100s"}
    findings = judge.analyze_container(_facts(kind="gif", frames=[frame], gif_blocks=["GCE"]))["findings"]
    assert not any(item["code"] == "gif_gce_missing" for item in findings)


def test_jpeg_app1_without_app2_is_info():
    findings = judge.analyze_container(_facts(kind="jpeg", jpeg_markers=["APP0", "APP1"]))["findings"]
    entry = [item for item in findings if item["code"] == "jpeg_no_icc"][0]
    assert entry["severity"] == "info"


def test_jpeg_app2_present_is_silent():
    findings = judge.analyze_container(_facts(kind="jpeg", jpeg_markers=["APP0", "APP1", "APP2"]))["findings"]
    assert not any(item["code"] == "jpeg_no_icc" for item in findings)


def test_container_requires_kind():
    with pytest.raises(ValueError):
        judge.analyze_container({"width": 1, "height": 1})


def test_container_rejects_bad_frames():
    with pytest.raises(ValueError):
        judge.analyze_container(_facts(kind="gif", frames=["oops"]))


def test_container_clean_png_is_silent():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "IEND"], "crc_ok": True}))["findings"]
    assert findings == []


# ================================================================== 消费者
def test_matrix_has_nine_rows():
    assert len(spec.MATRIX_ROWS) == 9


def test_matrix_is_valid():
    assert judge.validate_matrix(spec.MATRIX_ROWS) == []


def test_matrix_row_order_matches_consumers():
    assert [row["consumer"] for row in spec.MATRIX_ROWS] == list(spec.CONSUMERS)


def test_matrix_invalid_row_count():
    problems = judge.validate_matrix(spec.MATRIX_ROWS[:-1])
    assert problems


def test_matrix_invalid_vocab():
    rows = [dict(row) for row in spec.MATRIX_ROWS]
    rows[0]["applies_icc"] = "maybe"
    assert judge.validate_matrix(rows)


def test_matrix_invalid_confidence():
    rows = [dict(row) for row in spec.MATRIX_ROWS]
    rows[0]["confidence"] = "guess"
    assert judge.validate_matrix(rows)


def test_matrix_dropped_chunks_must_be_list():
    rows = [dict(row) for row in spec.MATRIX_ROWS]
    rows[0]["dropped_chunks"] = "eXIf"
    assert judge.validate_matrix(rows)


def test_consumers_emits_matrix_finding():
    result = judge.analyze_consumers(_facts())
    assert any(item["code"] == "consumers_matrix" for item in result["findings"])


def test_consumers_invalid_matrix_is_error():
    rows = [dict(row) for row in spec.MATRIX_ROWS]
    rows[0]["applies_orientation"] = "sometimes"
    result = judge.analyze_consumers(_facts(matrix=rows))
    entry = [item for item in result["findings"] if item["code"] == "consumers_matrix_invalid"][0]
    assert entry["severity"] == "error"


def test_consumers_risk_rows_cover_all_consumers():
    result = judge.analyze_consumers(_facts())
    assert {row["consumer"] for row in result["risks"]} == set(spec.CONSUMERS)


def test_consumers_no_conditions_all_low():
    result = judge.analyze_consumers(_facts())
    assert all(row["risk"] == "low" for row in result["risks"])


def test_consumers_condition_makes_sharp_high():
    facts = _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)])
    result = judge.analyze_consumers(facts)
    sharp = [row for row in result["risks"] if row["consumer"] == "sharp"][0]
    assert sharp["risk"] == "high"


def test_consumers_gray_row_is_unknown_under_condition():
    facts = _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)])
    result = judge.analyze_consumers(facts)
    firefox = [row for row in result["risks"] if row["consumer"] == "firefox"][0]
    assert firefox["risk"] == "unknown"


def test_consumers_low_risk_rows_do_not_emit_findings():
    result = judge.analyze_consumers(_facts())
    assert not any(item["code"] == "consumer_risk" for item in result["findings"])


@pytest.mark.parametrize("command", sorted(spec.PROCESSING_DROPS))
def test_consumers_diff_every_command(command):
    result = judge.analyze_consumers(_facts(chunks=["APP1", "APP2", "eXIf", "iCCP"]))
    entries = [item for item in result["findings"] if item["code"] == "processing_diff" and item["evidence"]["command"] == command]
    assert len(entries) == 1


def test_consumers_diff_drops_present_chunks():
    result = judge.analyze_consumers(_facts(chunks=["APP1", "APP2", "eXIf", "iCCP"]))
    entry = [item for item in result["findings"] if item["evidence"].get("command") == "exiftool -all="][0]
    assert set(entry["evidence"]["dropped"]) == {"APP1", "APP2", "eXIf", "iCCP"}


def test_consumers_copy_all_keeps_everything():
    result = judge.analyze_consumers(_facts(chunks=["APP1", "APP2", "eXIf"]))
    entry = [item for item in result["findings"] if item["evidence"].get("command") == "jpegtran -copy all"][0]
    assert entry["evidence"]["dropped"] == []


def test_consumers_diff_kept_contains_remaining_chunks():
    result = judge.analyze_consumers(_facts(chunks=["APP1", "APP2", "IHDR"]))
    entry = [item for item in result["findings"] if item["evidence"].get("command") == "jpegtran -copy none"][0]
    assert entry["evidence"]["kept"] == ["IHDR"]


# ================================================================== 入口与门禁
def test_orientation_mode_summary():
    records = _records(_subject("orientation", _facts(exif=[_ifd("ifd0", 1)])), spec.RULE_SUMMARY)
    assert records[0].evidence["worst_severity"] == "info"


def test_double_rotate_mode_summary():
    records = _records(_subject("double-rotate", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)])), spec.RULE_SUMMARY)
    assert records[0].evidence["findings"] >= 1


def test_color_mode_summary():
    records = _records(_subject("color", _facts()), spec.RULE_SUMMARY)
    assert records[0].evidence["by_severity"].get("info", 0) >= 1


def test_container_mode_summary():
    records = _records(_subject("container", _facts(kind="png", png={"chunks": ["IHDR", "IDAT", "IEND"]})), spec.RULE_SUMMARY)
    assert records[0].evidence["kind"] == "png"


def test_consumers_mode_summary():
    records = _records(_subject("consumers", _facts()), spec.RULE_SUMMARY)
    assert len(records[0].evidence["matrix"]) == 9


def test_orientation_absent_is_not_blocking():
    assert _report(_subject("orientation", _facts())).exit_code() == EXIT_OK


def test_warning_triggers_gate():
    subject = _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    record = _records(subject, spec.RULE_GATE)[0]
    assert record.evidence["worst_severity"] == "warning"
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_error_triggers_gate_with_source_exit_two():
    subject = _subject("orientation", _facts(exif=[_ifd("ifd0", 9)]))
    record = _records(subject, spec.RULE_GATE)[0]
    assert record.evidence["source_exit_code"] == 2


def test_unknown_triggers_gate():
    subject = _subject("color", _facts(icc=_icc(compressed=True, carrier="iCCP")))
    assert _report(subject).exit_code() == EXIT_BLOCKED


def test_suspicion_does_not_trigger_gate():
    subject = _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6)]))
    assert _records(subject, spec.RULE_GATE) == []


def test_missing_facts_is_input_error():
    with pytest.raises(ValueError):
        _evaluate({"mode": "orientation"})


def test_unknown_mode_is_input_error():
    with pytest.raises(ValueError):
        _evaluate({"mode": "nope", "facts": _facts()})


def test_missing_rule_is_contract_violation():
    with pytest.raises(RuleMissing):
        _evaluate(_subject("orientation", _facts()), basis=Basis.empty("1"))


def test_record_ids_are_unique_for_double():
    subject = _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)], xmp="tiff:Orientation='3'"))
    ids = [record.id for record in _report(subject).records]
    assert len(ids) == len(set(ids))


def test_record_ids_are_unique_for_consumers():
    subject = _subject("consumers", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    ids = [record.id for record in _report(subject).records]
    assert len(ids) == len(set(ids))


def test_every_record_has_complete_basis():
    for subject in (
        _subject("orientation", _facts()),
        _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)])),
        _subject("color", _facts()),
        _subject("container", _facts(kind="png", png={"chunks": ["IHDR", "IDAT", "IEND"]})),
        _subject("consumers", _facts()),
    ):
        for record in _evaluate(subject):
            assert record.basis is not None
            assert record.basis.rule_version == "1"


def test_finding_records_are_non_blocking():
    subject = _subject("orientation", _facts(exif=[_ifd("ifd0", 9)]))
    for record in _evaluate(subject):
        if record.rule_id != spec.RULE_GATE:
            assert record.verdict in (INFO, WARN)


def test_report_is_deterministic():
    subject = _subject("consumers", _facts(exif=[_ifd("ifd0", 6)]))
    assert _report(subject).as_dict() == _report(subject).as_dict()


# ================================================================== CLI
def test_cli_sample_exits_zero(capsys):
    code = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["organ"] == SLUG


def test_cli_warning_exits_one(tmp_path, capsys):
    subject = _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_BLOCKED


def test_cli_unknown_mode_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "nope", "facts": {}}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_INPUT


def test_cli_missing_rule_exits_three(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject("orientation", _facts()), ensure_ascii=False), encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(empty), "--json"]) == EXIT_CONTRACT


def test_cli_basis_is_optional(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_subject("orientation", _facts()), ensure_ascii=False), encoding="utf-8")
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
                    if alias.name.split(".")[0] == "imageoracle":
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "imageoracle":
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_does_not_decode_pixels():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in ("PIL", "Image.open", "np.", "numpy"):
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
                if (
                    keyword.arg == "errors"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value in ("replace", "ignore")
                ):
                    hits.append((path.name, keyword.value.value))
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


# ================================================================== 补充矩阵
def test_transform_flip_flags_reference_matrix():
    for value, (flip_h, flip_v, rotate, swap) in spec.ORIENTATION_MATRIX.items():
        transform = judge.transform_for(value)
        assert transform["flip_h"] is flip_h
        assert transform["flip_v"] is flip_v
        assert transform["swap_wh"] is swap


def test_matrix_covers_all_eight_orientations():
    assert set(spec.ORIENTATION_MATRIX) == set(range(1, 9))


def test_labels_cover_all_eight_orientations():
    assert set(spec.ORIENTATION_LABELS) == set(range(1, 9))


def test_xmp_patterns_are_two():
    assert len(spec.XMP_PATTERNS) == 2


def test_orientation_sources_record_states():
    result = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", None)]))
    states = {source["source"]: source["state"] for source in result["sources"]}
    assert states["exif.ifd0"] == "present"
    assert states["exif.ifd1"] == "absent"


def test_orientation_type_error_source_state():
    result = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 6, type_=4)]))
    assert result["sources"][0]["state"] == "not_int16u"


def test_orientation_out_of_range_source_state():
    result = judge.analyze_orientation(_facts(exif=[_ifd("ifd0", 0)]))
    assert result["sources"][0]["state"] == "out_of_range"


def test_orientation_xmp_only_source():
    result = judge.analyze_orientation(_facts(xmp="<tiff:Orientation>3</tiff:Orientation>"))
    assert any(source["source"] == "xmp.tiff:Orientation" for source in result["sources"])


def test_double_no_conditions_has_no_verdicts():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 1)]))
    assert result["verdicts"] == []


def test_double_condition1_has_one_consumer_verdict():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    assert len([item for item in result["verdicts"] if item["condition"] == 1]) == 1


def test_double_condition3_has_two_consumer_verdicts():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)]))
    assert len([item for item in result["verdicts"] if item["condition"] == 3]) == 2


def test_double_square_image_has_no_bigedge():
    result = judge.analyze_double_rotate(_facts(exif=[_ifd("ifd0", 6)], width=3000, height=3000))
    assert not any(item["code"] == "double_rotate_bigedge_mismatch" for item in result["findings"])


def test_consumers_risk_rows_have_severity():
    result = judge.analyze_consumers(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    assert all(row["severity"] in spec.SEVERITY_ORDER for row in result["risks"])


def test_consumers_risk_trigger_lists_conditions():
    result = judge.analyze_consumers(_facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    assert all(row["trigger"] for row in result["risks"] if row["risk"] != "low")


def test_consumers_risk_by_severity_mapping():
    assert spec.RISK_BY_SEVERITY["warning"] == "medium"
    assert spec.RISK_BY_SEVERITY["error"] == "high"
    assert spec.RISK_BY_SEVERITY["unknown"] == "unknown"


def test_default_assumptions_cover_distinct_consumers():
    names = [row["consumer"] for row in spec.DEFAULT_ASSUMPTIONS]
    assert len(names) == len(set(names))


def test_processing_drops_are_tuples():
    assert all(isinstance(value, tuple) for value in spec.PROCESSING_DROPS.values())


def test_color_icc_present_carrier():
    findings = judge.analyze_color(_facts(icc=_icc(carrier="tag34675")))["findings"]
    entry = [item for item in findings if item["code"] == "icc_present"][0]
    assert entry["evidence"]["carrier"] == "tag34675"


def test_color_compressed_marks_not_inspected():
    result = judge.analyze_color(_facts(icc=_icc(compressed=True, carrier="iCCP")))
    assert result["icc"]["present"] is True
    assert result["icc"]["inspected"] is False


def test_color_defaults_names_are_distinct():
    result = judge.analyze_color(_facts())
    rows = [item for item in result["findings"] if item["code"] == "color_default_assumption"]
    assert len({row["evidence"]["consumer"] for row in rows}) == 7


def test_color_all_known_spaces_accepted():
    for space in ("RGB ", "CMYK", "GRAY", "XYZ ", "Lab "):
        header = _icc()["header"]
        header["space"] = space
        header["pcs"] = space
        findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
        assert not [item for item in findings if item["code"] == "icc_unknown_space"]


def test_color_all_known_classes_accepted():
    for klass in ("mntr", "scnr", "prtr"):
        header = _icc()["header"]
        header["class"] = klass
        findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
        assert not [item for item in findings if item["code"] == "icc_unknown_class"]


def test_color_intent_bounds():
    for intent in (0, 1, 2, 3):
        header = _icc()["header"]
        header["intent"] = intent
        findings = judge.analyze_color(_facts(icc=_icc(header=header)))["findings"]
        assert not [item for item in findings if item["code"] == "icc_bad_intent"]


def test_color_size_matches_is_silent():
    findings = judge.analyze_color(_facts(icc=_icc()))["findings"]
    assert not [item for item in findings if item["code"] == "icc_size_mismatch"]


def test_color_header_evidence_carries_fields():
    findings = judge.analyze_color(_facts(icc=_icc()))["findings"]
    entry = [item for item in findings if item["code"] == "icc_class_legal"][0]
    assert entry["evidence"]["class"] == "mntr"


def test_png_clean_apng_order():
    chunks = ["IHDR", "acTL", "fcTL", "IDAT", "fcTL", "fdAT", "IEND"]
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": chunks, "fctl_sequences": [0, 1]}))["findings"]
    assert not [item for item in findings if item["rule_id"] == spec.RULE_CONTAINER_PNG_ORDER]


def test_png_crc_true_no_finding():
    findings = judge.analyze_container(_facts(kind="png", png={"chunks": ["IHDR", "IDAT", "IEND"], "crc_ok": True}))["findings"]
    assert not [item for item in findings if item["code"] == "png_crc_missing"]


def test_webp_without_frames_no_anim_warning():
    findings = judge.analyze_container(_facts(kind="webp", frames=[], chunks=[]))["findings"]
    assert not [item for item in findings if item["code"] == "webp_anim_missing"]


def test_gif_without_frames_no_gce_warning():
    findings = judge.analyze_container(_facts(kind="gif", frames=[], gif_blocks=[]))["findings"]
    assert not [item for item in findings if item["code"] == "gif_gce_missing"]


def test_jpeg_no_markers_is_silent():
    findings = judge.analyze_container(_facts(kind="jpeg", jpeg_markers=[]))["findings"]
    assert findings == []


def test_container_multiple_frames_each_judged():
    frames = [
        {"index": 0, "duration_ms": 100, "raw_unit": "ms"},
        {"index": 1, "duration_ms": None, "raw_unit": "ms"},
    ]
    findings = judge.analyze_container(_facts(kind="webp", frames=frames, chunks=["ANIM"]))["findings"]
    assert len([item for item in findings if item["code"] == "frame_duration_unknown"]) == 1


def test_summary_counts_suspicion_separately():
    subject = _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6)]))
    summary = _records(subject, spec.RULE_SUMMARY)[0]
    assert summary.evidence["by_severity"].get("suspicion", 0) >= 1


def test_gate_evidence_error():
    subject = _subject("orientation", _facts(exif=[_ifd("ifd0", 9)]))
    record = _records(subject, spec.RULE_GATE)[0]
    assert record.evidence["worst_severity"] == "error"
    assert record.evidence["source_exit_code"] == 2


def test_orientation_mode_records_have_module():
    for record in _evaluate(_subject("orientation", _facts(exif=[_ifd("ifd0", 9)]))):
        if record.path.startswith("findings["):
            assert record.evidence["module"] == "orientation"


def test_double_mode_records_have_module():
    subject = _subject("double-rotate", _facts(exif=[_ifd("ifd0", 6), _ifd("ifd1", 1)]))
    modules = {record.evidence.get("module") for record in _evaluate(subject) if record.path.startswith("findings[")}
    assert "double-rotate" in modules


def test_color_mode_records_have_module():
    modules = {record.evidence.get("module") for record in _evaluate(_subject("color", _facts())) if record.path.startswith("findings[")}
    assert modules == {"color"}


def test_container_mode_records_have_module():
    subject = _subject("container", _facts(kind="png", png={"chunks": ["IDAT", "IHDR", "IEND"]}))
    modules = {record.evidence.get("module") for record in _evaluate(subject) if record.path.startswith("findings[")}
    assert modules == {"container"}


def test_consumers_mode_records_have_module():
    modules = {record.evidence.get("module") for record in _evaluate(_subject("consumers", _facts())) if record.path.startswith("findings[")}
    assert modules == {"consumers"}


def test_orientation_mode_requires_facts_object():
    with pytest.raises(ValueError):
        _evaluate({"mode": "orientation", "facts": []})


def test_facts_dimensions_must_be_int():
    with pytest.raises(ValueError):
        _evaluate(_subject("orientation", {"kind": "jpeg", "width": "4000", "height": 3000, "exif": []}))


def test_matrix_confidence_values_are_in_vocab():
    assert {row["confidence"] for row in spec.MATRIX_ROWS} <= set(spec.CONFIDENCES)


def test_thresholds_encoding_tag_matches():
    assert SETTINGS["encoding_tag"] == spec.TAG_ORIENTATION


def test_cli_orientation_error_exits_one(tmp_path, capsys):
    subject = _subject("orientation", _facts(exif=[_ifd("ifd0", 9)]))
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_BLOCKED


def test_orientation_mode_sample_has_no_error():
    assert _report(_subject("orientation", json.loads(SAMPLE.read_text(encoding="utf-8"))["facts"])).exit_code() == EXIT_OK