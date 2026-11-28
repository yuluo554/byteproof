"""``subtitle-preflight`` 器官的无损测试（迁自 10-19-subtitle-preflight，Node/mjs 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：时序 T01–T12（含 fps 漂移
整数拟合）、可读性 R01–R07（千分字符 + 主导文字档位）、卫生 S01–S10（十条判定式 +
白名单计数）、编码嗅探（BOM → UTF-8 → GBK → lossy，回退显式）、可逆修复白名单
（去重叠/修间隔 → 行尾空白 → 闭合标签 → SRT 序号重编）。

判定层口径（D1 + D18）：旧仓 24 个 ``.test.mjs`` 按文件名正则剔除 11 件后 **13 文件**
实跑 ``node --test`` **X = 155 pass**（逐文件 pass 数见 ``docs/subtitle-preflight.md``
§6.1）；旧层 ``test(`` 调用 **155**。本文件 **181 个 ``test_`` 函数**（AST 计）覆盖同一判定面。

**没迁的部分逐条写在 ``docs/subtitle-preflight.md`` §6.2 的处置表里**（SRT/VTT/ASS 解析、
报告 JSON/Markdown/CSV 渲染、单一 HTML 产物构建、浏览器 e2e、真值门/口径门本体）。
解析后的 cue 序列由输入层摊平传入；器官不解析字幕文本。
"""

from __future__ import annotations

import ast
import base64
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.subtitle_preflight import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    api,
    core,
    spec,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    INFO,
    WARN,
    Basis,
    ContractError,
    Report,
    RuleRef,
)
from byteproof.core.basis import RuleMissing  # noqa: E402
from byteproof.core.registry import get  # noqa: E402

SLUG = "subtitle-preflight"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "subtitle-preflight.basis.json"
THRESHOLDS_PATH = DATA_DIR / "subtitle-preflight.thresholds.json"
BASIS = Basis.from_json(str(BASIS_PATH))
SNAPSHOT = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
TH = spec.THRESHOLDS


# ---------------------------------------------------------------- 构造助手
def cue(start, end, *lines, **kwargs):
    """一条摊平后的 cue（默认：文本类 finding 取 ``sourceLine``，时序取 ``timeLine``）。"""
    item = {
        "startMs": start,
        "endMs": end,
        "textLines": list(lines),
        "sourceLine": kwargs.pop("source_line", 2),
        "timeLine": kwargs.pop("time_line", 2),
        "endLine": kwargs.pop("end_line", 4),
    }
    if "text_line_numbers" in kwargs:
        item["textLineNumbers"] = kwargs.pop("text_line_numbers")
    item.update(kwargs)
    return item


def evaluate(subject, basis=BASIS):
    return list(api.evaluate(subject, basis))


def findings(subject, basis=BASIS):
    """去掉 ``sp-summary`` / ``sp-skipped`` 后的判定记录。"""
    return [
        record
        for record in evaluate(subject, basis)
        if record.rule_id not in (spec.SUMMARY_RULE, spec.SKIPPED_RULE)
    ]


def rules(subject, basis=BASIS):
    return [record.rule_id for record in findings(subject, basis)]


def only(subject, rule_id, basis=BASIS):
    matched = [record for record in findings(subject, basis) if record.rule_id == rule_id]
    assert len(matched) == 1, "期望恰好一条 %s，实际 %d 条：%s" % (
        rule_id,
        len(matched),
        [record.rule_id for record in findings(subject, basis)],
    )
    return matched[0]


def summary(subject, basis=BASIS):
    return [record for record in evaluate(subject, basis) if record.rule_id == spec.SUMMARY_RULE][0]


def skips(subject, basis=BASIS):
    return [record for record in evaluate(subject, basis) if record.rule_id == spec.SKIPPED_RULE]


def grid_cues(n, fps, steps=(7, 8, 6, 9, 7, 8), durations=(4, 5, 4, 5, 4, 5)):
    """声明帧栅格上的 n 条 cue（起点 = 整数帧号 × 帧长），与旧仓 ``gridCues`` 同构。"""
    frame_ms = 1000.0 / fps
    frame = 0
    out = []
    for index in range(n):
        out.append(cue(
            core.js_round(frame * frame_ms),
            core.js_round((frame + durations[index % len(durations)]) * frame_ms),
            "第 %d 句" % (index + 1),
        ))
        frame += steps[index % len(steps)]
    return out


def stretch(cues, scale):
    return [
        cue(core.js_round(item["startMs"] * scale), core.js_round(item["endMs"] * scale),
            *item["textLines"])
        for item in cues
    ]


def starts(cues):
    return [item["startMs"] for item in cues]


# ============================================================ A · 接线与口径快照
def test_pack_is_registered_under_slug():
    assert PACK.slug == SLUG
    assert PACK.version == ORGAN_VERSION == "1"
    assert PACK.input_fields == ("mode",)
    assert get(SLUG) is PACK


def test_builtin_modules_sorted_and_unique():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    assert len(set(BUILTIN_MODULES)) == len(BUILTIN_MODULES)
    assert "subtitle_preflight" in BUILTIN_MODULES


def test_list_contains_organ_and_reaches_24(capsys):
    from byteproof import cli

    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    # 计数改用下限：别处测试可能向全局注册表登记临时 Pack（跨文件累计不可作不变式）
    assert len(lines) >= 24
    assert any(line.startswith("subtitle-preflight ") for line in lines)


def test_basis_rule_ids_cover_spec():
    assert set(spec.ALL_RULES) <= set(BASIS.rule_ids())
    assert len(BASIS) == len(spec.ALL_RULES)


def test_basis_rule_versions_filled():
    for rule_id in spec.ALL_RULES:
        rule = BASIS.require(rule_id)
        assert rule.version, rule_id
        assert rule.text, rule_id
        assert "10-19-subtitle-preflight" in rule.source, rule_id


def test_thresholds_snapshot_matches_spec():
    assert SNAPSHOT["thresholds"] == TH


def test_whitelist_snapshot_matches_spec():
    assert tuple(SNAPSHOT["whitelist"]) == spec.WHITELIST


def test_severity_snapshot_matches_spec():
    assert SNAPSHOT["severity"] == spec.SEVERITY
    assert set(spec.SEVERITY) == set(spec.ALL_RULES)


def test_skip_reasons_snapshot_matches_spec():
    assert tuple(SNAPSHOT["skip_reasons"]) == spec.SKIP_REASONS


def test_modes_snapshot_matches_spec():
    assert tuple(SNAPSHOT["modes"]) == spec.MODES
    assert spec.DEFAULT_MODE in spec.MODES


def test_ruleset_versions_snapshot():
    assert SNAPSHOT["ruleset_version"] == spec.RULESET_VERSION == 1
    assert SNAPSHOT["schema_version"] == spec.SCHEMA_VERSION == 2


def test_sort_keys_are_old_report_keys():
    assert tuple(spec.SORT_KEYS) == ("line", "ruleId")
    sorted_items = core.sort_findings([
        {"line": 9, "ruleId": "b", "field": "z"},
        {"line": 9, "ruleId": "a", "field": "z"},
        {"line": 3, "ruleId": "z", "field": "z"},
    ])
    assert [(item["line"], item["ruleId"]) for item in sorted_items] == [(3, "z"), (9, "a"), (9, "b")]


def test_no_numeric_threshold_literals_in_core():
    """K1：阈值只从 ``th`` 读——核心模块里不许出现这些**特征值**的数值字面量。"""
    path = SRC / "byteproof" / "auditors" / "subtitle_preflight" / "core.py"
    source = path.read_text(encoding="utf-8")
    numbers = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    }
    for distinctive in (800, 7000, 80, 42, 17, 16, 20, 40, 30000):
        assert distinctive not in numbers, distinctive
    for key in TH:
        assert '"%s"' % key in source, key


def test_core_has_no_io_or_clock_imports():
    tree = ast.parse((SRC / "byteproof" / "auditors" / "subtitle_preflight" / "core.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"math", "re", "typing", "__future__"}, imported


def test_organ_does_not_import_host_cli():
    source = (SRC / "byteproof" / "auditors" / "subtitle_preflight" / "api.py").read_text(encoding="utf-8")
    assert "argparse" not in source
    assert "byteproof.cli" not in source


def test_missing_basis_rule_yields_contract_error():
    with pytest.raises(RuleMissing):
        findings({"mode": "timing", "cues": [cue(0, 1000, "你好")]}, basis=Basis.empty())


def test_summary_counts_are_self_consistent():
    subject = {"mode": "all", "cues": [cue(0, 2000, "你好world"), cue(1990, 4000, "再见")]}
    record = summary(subject)
    # total 计的是"summaary 行以外"的账本行（旧仓 report.summary.total = findings 长度）
    assert record.evidence["total"] == len(evaluate(subject)) - 1
    assert sum(record.evidence["by_severity"].values()) == record.evidence["total"]
    assert sum(record.evidence["by_rule"].values()) == record.evidence["total"]


def test_record_ids_unique():
    subject = {"mode": "all", "cues": [cue(0, 100, "好"), cue(50, 60, "好")]}
    ids = [record.id for record in evaluate(subject)]
    assert len(ids) == len(set(ids))


# ============================================================ B · 编码嗅探（core/decode.js）
def test_decode_ascii_utf8_no_fallback():
    result = core.decode_bytes(b"helloS")
    assert result["encoding"] == "utf-8"
    assert result["fallback"] is False
    assert result["lossy"] is False
    assert result["bom"] is None


def test_decode_utf8_bom_stripped_reported():
    result = core.decode_bytes(b"\xef\xbb\xbfab")
    assert result["bom"] == "utf-8"
    assert result["text"] == "ab"
    assert result["fallback"] is False


def test_decode_utf16le_bom():
    payload = "你好".encode("utf-16-le")
    result = core.decode_bytes(b"\xff\xfe" + payload)
    assert result["bom"] == "utf-16le"
    assert result["encoding"] == "utf-16le"
    assert result["text"] == "你好"


def test_decode_utf16be_bom():
    payload = "你好".encode("utf-16-be")
    result = core.decode_bytes(b"\xfe\xff" + payload)
    assert result["bom"] == "utf-16be"
    assert result["text"] == "你好"


def test_decode_gbk_fallback_explicit():
    result = core.decode_bytes("你好".encode("gbk"))
    assert result["encoding"] == "gbk"
    assert result["fallback"] is True
    codes = [item["code"] for item in result["diagnostics"]]
    assert codes == ["decode.gbk-fallback"]


def test_decode_gbk_text_roundtrip():
    original = "示例字幕"
    assert core.decode_bytes(original.encode("gbk"))["text"] == original


def test_decode_lossy_when_both_fail():
    # 0x81 0x40 是 GBK 合法双字节；取一段 GBK 与 UTF-8 均严格失败的字节
    result = core.decode_bytes(b"\xff\xff\xff")
    assert result["lossy"] is True
    codes = [item["code"] for item in result["diagnostics"]]
    assert codes == ["decode.lossy"]


def test_decode_mixed_eol_diagnostic():
    result = core.decode_bytes(b"a\r\nb\nc\r")
    assert result["text"] == "a\nb\nc\n"
    assert result["eol"] == "mixed"
    assert "decode.mixed-eol" in [item["code"] for item in result["diagnostics"]]


def test_detect_eol_crlf():
    assert core.detect_eol("a\r\nb\r\n") == "crlf"


def test_detect_eol_cr():
    assert core.detect_eol("a\rb\r") == "cr"


def test_detect_eol_lf():
    assert core.detect_eol("a\nb\n") == "lf"


def test_detect_eol_mixed():
    assert core.detect_eol("a\r\nb\n") == "mixed"


def test_detect_eol_no_newline_defaults_lf():
    assert core.detect_eol("abc") == "lf"


def test_normalize_eol_line_count_preserved():
    before = "a\r\nb\rc\n"
    after = core.normalize_eol(before)
    assert after == "a\nb\nc\n"
    assert len(re.split(r"\r\n|\r|\n", before)) == len(after.split("\n"))


def test_decode_rejects_non_bytes():
    with pytest.raises(TypeError):
        core.decode_bytes("字符串不是字节")


def test_decode_subject_bad_base64_input_error():
    with pytest.raises(ValueError):
        evaluate({"mode": "decode", "bytes_b64": "***"})


def test_decode_mode_records_fallback_only():
    records = evaluate({"mode": "decode", "bytes_b64": base64.b64encode("你好".encode("gbk")).decode()})
    assert [record.rule_id for record in records if record.rule_id != spec.SUMMARY_RULE] == [
        "decode.gbk-fallback"
    ]


def test_decode_mode_gbk_summary_carry_encoding():
    records = evaluate({"mode": "decode", "bytes_b64": base64.b64encode("你好".encode("gbk")).decode()})
    record = [item for item in records if item.rule_id == spec.SUMMARY_RULE][0]
    assert record.evidence["decode"]["encoding"] == "gbk"
    assert record.evidence["decode"]["fallback"] is True


# ============================================================ C · 时序 T01–T12
def test_overlap_fires():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(1990, 4000, "乙")]}
    record = only(subject, "timing.overlap")
    assert record.verdict == ERROR
    assert record.path == "cue:2"
    assert record.evidence["actual"] == "1990"


def test_adjacent_touching_not_overlap():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(2000, 4000, "乙")]}
    assert "timing.overlap" not in rules(subject)


def test_zero_duration():
    subject = {"mode": "timing", "cues": [cue(0, 2000), cue(2000, 2000)]}
    assert only(subject, "timing.zero-duration").evidence["expected"] == "> startMs"


def test_negative_duration_wins_over_zero():
    subject = {"mode": "timing", "cues": [cue(3000, 2000)]}
    assert "timing.negative-duration" in rules(subject)
    assert "timing.zero-duration" not in rules(subject)


def test_gap_too_small():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(2050, 4000, "乙")]}
    record = only(subject, "timing.gap-too-small")
    assert record.evidence["actual"] == "2050"


def test_gap_equal_min_not_reported():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(2080, 4000, "乙")]}
    assert "timing.gap-too-small" not in rules(subject)


def test_overlap_does_not_also_report_gap():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(1900, 4000, "乙")]}
    assert "timing.overlap" in rules(subject)
    assert "timing.gap-too-small" not in rules(subject)


def test_non_monotonic():
    subject = {"mode": "timing", "cues": [cue(1000, 2000, "甲"), cue(500, 1500, "乙")]}
    assert "timing.non-monotonic" in rules(subject)


def test_duplicate_cue_warn():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(0, 2000, "甲")]}
    assert only(subject, "timing.duplicate-cue").verdict == WARN


def test_same_time_different_text_not_duplicate():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(0, 2000, "乙")]}
    assert "timing.duplicate-cue" not in rules(subject)


def test_negative_start():
    subject = {"mode": "timing", "cues": [cue(-100, 1000, "甲")]}
    assert only(subject, "timing.negative-start").verdict == ERROR


def test_past_media_end_reports_last():
    subject = {
        "mode": "timing",
        "cues": [cue(0, 2000, "甲"), cue(3000, 5000, "乙")],
        "declared": {"mediaDurationMs": 4000},
    }
    record = only(subject, "timing.past-media-end")
    assert record.path == "cue:2"


def test_past_media_end_unknown_skipped_info():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲")]}
    skip = [item for item in skips(subject) if "media_duration_unknown" in item.path]
    assert len(skip) == 1
    assert skip[0].verdict == INFO


def test_past_media_end_within_bounds():
    subject = {
        "mode": "timing",
        "cues": [cue(0, 2000, "甲")],
        "declared": {"mediaDurationMs": 5000},
    }
    assert "timing.past-media-end" not in rules(subject)


def test_unparsable_timecode_passthrough():
    subject = {
        "mode": "timing",
        "cues": [cue(0, 1000, "甲")],
        "diagnostics": [{"code": "parse.unparsable-timecode", "line": 3, "field": "timecode",
                         "detail": "00:0x:01"}],
    }
    record = only(subject, "timing.unparsable-timecode")
    assert record.verdict == ERROR
    assert record.path == "line:3"
    assert record.evidence["actual"] == "00:0x:01"


def test_timecode_precision_diagnostic_to_finding():
    subject = {
        "mode": "timing",
        "cues": [cue(0, 1000, "甲")],
        "diagnostics": [{"code": "parse.timecode-precision", "line": 2, "field": "timecode",
                         "detail": "毫秒位 2 位"}],
    }
    record = only(subject, "timing.timecode-precision")
    assert record.verdict == WARN
    assert record.path == "line:2"
    assert record.evidence["actual"] == "毫秒位 2 位"


def test_file_order_mismatch_single_finding():
    subject = {"mode": "timing", "cues": [cue(5000, 6000, "甲"), cue(1000, 2000, "乙"),
                                           cue(3000, 4000, "丙")]}
    assert rules(subject).count("timing.file-order-mismatch") == 1


def test_file_order_mismatch_points_first_reversal():
    cues = [cue(5000, 6000, "甲"), cue(1000, 2000, "乙")]
    assert core.find_first_reversal(cues) == 1
    subject = {"mode": "timing", "cues": cues}
    assert only(subject, "timing.file-order-mismatch").path == "cue:2"


def test_find_first_reversal_none():
    assert core.find_first_reversal([cue(0, 1000, "甲"), cue(1000, 2000, "乙")]) is None


def test_findings_sorted_by_line_rule_field():
    subject = {"mode": "all", "cues": [cue(0, 1000, "你好world", source_line=9),
                                        cue(900, 2000, "再见", source_line=3)]}
    order = [(record.evidence["line"], record.rule_id) for record in findings(subject)]
    assert order == sorted(order)


def test_timing_mode_only_timing_rules():
    subject = {"mode": "timing", "cues": [cue(0, 100, "你好world")]}
    assert all(rule.startswith("timing.") for rule in rules(subject))


def test_timing_expected_fields_carry_values():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(1990, 4000, "乙")]}
    record = only(subject, "timing.overlap")
    assert record.evidence["field"] == "startMs"
    assert record.evidence["expected"] == ">= 2000"


def test_timing_warn_severity_mapping():
    subject = {"mode": "timing", "cues": [cue(5000, 6000, "甲"), cue(1000, 2000, "乙")]}
    assert only(subject, "timing.file-order-mismatch").verdict == WARN
    assert spec.SEVERITY["timing.duplicate-cue"] == WARN


def test_empty_cues_no_findings_but_skips():
    subject = {"mode": "timing", "cues": []}
    assert rules(subject) == []
    assert len(skips(subject)) == 2


def test_cue_line_used_not_time_line():
    subject = {"mode": "timing", "cues": [cue(0, 2000, "甲", source_line=40, time_line=41),
                                          cue(1990, 3000, "乙", source_line=44, time_line=45)]}
    assert only(subject, "timing.overlap").evidence["line"] == 44


def test_timing_paths_are_cue_indexed():
    subject = {"mode": "timing", "cues": [cue(1000, 2000, "甲"), cue(500, 1500, "乙")]}
    paths = {record.rule_id: record.path for record in findings(subject)}
    assert paths["timing.non-monotonic"] == "cue:2"


# ============================================================ D · fps 漂移拟合 T11
TRUE_SCALE = 25 / 23.976


def test_drift_scale_recovered():
    drifted = stretch(grid_cues(24, 23.976), TRUE_SCALE)
    outcome = core.drift_fit(starts(drifted), 23.976, TH)
    assert outcome["ok"] is True
    fit = outcome["fit"]
    assert abs(fit["scale"] - TRUE_SCALE) < 0.001
    assert abs(fit["scale"] - TRUE_SCALE) * fit["spanMs"] < 40


def test_drift_offset_zero_when_none():
    outcome = core.drift_fit(starts(stretch(grid_cues(24, 23.976), TRUE_SCALE)), 23.976, TH)
    assert outcome["fit"]["offsetMs"] == 0


def test_drift_samples_count():
    outcome = core.drift_fit(starts(stretch(grid_cues(24, 23.976), TRUE_SCALE)), 23.976, TH)
    assert outcome["fit"]["samples"] == 24


def test_drift_deterministic():
    values = starts(stretch(grid_cues(24, 23.976), TRUE_SCALE))
    assert core.drift_fit(values, 23.976, TH) == core.drift_fit(values, 23.976, TH)


def test_drift_clean_skipped_within_tolerance():
    outcome = core.drift_fit(starts(grid_cues(24, 23.976)), 23.976, TH)
    assert outcome["ok"] is False
    assert outcome["skipped"]["reason"] == "drift_within_tolerance"


def test_drift_pure_offset_absorbed():
    shifted = [
        cue(item["startMs"] + 1500, item["endMs"] + 1500, *item["textLines"])
        for item in grid_cues(24, 23.976)
    ]
    outcome = core.drift_fit(starts(shifted), 23.976, TH)
    assert outcome["ok"] is False
    assert outcome["skipped"]["reason"] == "drift_within_tolerance"


def test_drift_small_ratio_within_tolerance():
    mild = stretch(grid_cues(24, 23.976), 1.0005)
    outcome = core.drift_fit(starts(mild), 23.976, TH)
    assert outcome["ok"] is False
    assert outcome["skipped"]["reason"] == "drift_within_tolerance"


def test_drift_missing_fps_skipped():
    outcome = core.drift_fit(starts(stretch(grid_cues(24, 23.976), TRUE_SCALE)), None, TH)
    assert outcome["ok"] is False
    assert outcome["skipped"]["reason"] == "media_fps_unknown"


def test_drift_samples_below_min_skipped():
    drifted = stretch(grid_cues(19, 25), TRUE_SCALE)
    outcome = core.drift_fit(starts(drifted), 23.976, TH)
    assert outcome["ok"] is False
    assert outcome["skipped"]["reason"] == "samples_below_min"
    assert outcome["skipped"]["samples"] == 19


def test_drift_not_frame_grid_skipped():
    irregular = []
    value = 1000
    for index in range(24):
        irregular.append(value)
        value += 1200 + ((index * 617) % 1400)
    outcome = core.drift_fit(irregular, 23.976, TH)
    assert outcome["ok"] is False
    assert outcome["skipped"]["reason"] == "not_frame_grid"


def test_drift_thresholds_from_spec():
    outcome = core.drift_fit(starts(stretch(grid_cues(24, 23.976), TRUE_SCALE)), 23.976, TH)
    assert outcome["fit"]["residualMaxMs"] == TH["drift.residualMaxMs"]
    assert outcome["fit"]["gridToleranceMs"] == TH["drift.gridToleranceMs"]


def test_drift_clean_run_longest_segment():
    clean = grid_cues(24, 23.976)
    bad = cue(clean[23]["startMs"] - 10, clean[23]["endMs"], "坏")
    run = core.clean_run_starts(clean + [bad], TH["timing.gapMin"])
    assert len(run) == 24
    assert bad["startMs"] not in run


def test_median_int_odd():
    assert core.median_int([5, 1, 3]) == 3


def test_median_int_even_lower():
    assert core.median_int([1, 2, 100, 200]) == 51


def test_median_int_even_picks_lower_of_middle_pair():
    assert core.median_int([4, 10]) == 7
    assert core.median_int([0, 1]) == 0


def test_js_round_half_up():
    assert core.js_round(0.5) == 1
    assert core.js_round(1.5) == 2
    assert core.js_round(-1.5) == -1


def test_drift_finding_line1_field_fit():
    subject = {"mode": "timing", "cues": stretch(grid_cues(24, 23.976), TRUE_SCALE),
               "declared": {"declaredFps": 23.976}}
    record = only(subject, "timing.fps-drift")
    assert record.verdict == WARN
    assert record.path == "line:1"
    assert record.evidence["field"] == "fit"


# ============================================================ E · 可读性 R01–R07
def test_dominant_lang_en():
    assert core.dominant_lang(["hello world"]) == "en"


def test_dominant_lang_zh():
    assert core.dominant_lang(["你好，世界"]) == "zh"


def test_dominant_lang_ja():
    assert core.dominant_lang(["こんにちは"]) == "ja"


def test_dominant_lang_kana_half():
    # 假名 1 / 全角 3 → kana*2=2 < 3 → zh
    assert core.dominant_lang(["あ漢字"]) == "zh"


def test_strip_decorations_ass():
    assert core.strip_decorations(r"{\an8}正文") == "正文"


def test_strip_decorations_font_tag():
    assert core.strip_decorations("<i>斜体</i>") == "斜体"


def test_strip_decorations_brackets():
    assert core.strip_decorations("[music] 歌") == " 歌"


def test_strip_decorations_notes():
    assert core.strip_decorations("（笑声）♪") == ""


def test_line_width_full_and_half():
    assert core.line_width_milli("你好") == 2 * spec.FULL_MILLI
    assert core.line_width_milli("ab") == 2 * spec.HALF_MILLI


def test_line_width_ignores_space():
    assert core.line_width_milli("a b") == 2 * spec.HALF_MILLI


def test_measure_cue_counts():
    measured = core.measure_cue(["你好", "a", "  "])
    assert measured["visibleLineCount"] == 2
    assert measured["charsMilli"] == 2 * spec.FULL_MILLI + spec.HALF_MILLI
    assert measured["maxLineWidthMilli"] == 2 * spec.FULL_MILLI


def test_is_full_width_ranges():
    assert core.is_full_width("你") is True
    assert core.is_full_width("a") is False
    assert core.is_full_width("，") is True


def test_cps_zh_fires():
    # 20 个全角字 / 1000 ms = 20 cps > 9
    subject = {"mode": "readability", "cues": [cue(0, 1000, "一二三四五六七八九十一二三四五六七八九十")]}
    assert only(subject, "readability.cps").verdict == ERROR


def test_cps_en_limit_higher():
    # 20 半角字 / 1000 ms = 10 cps < 17（英文档不报 cps）
    subject = {"mode": "readability", "cues": [cue(0, 1000, "abcdefghijklmnopqrst")]}
    assert "readability.cps" not in rules(subject)


def test_cps_exactly_at_limit_not_reported():
    # 9 全角字 / 1000 ms = 9 cps，恰在限上（> 才报）
    subject = {"mode": "readability", "cues": [cue(0, 1000, "一二三四五六七八九")]}
    assert "readability.cps" not in rules(subject)


def test_cps_zero_duration_not_reported():
    subject = {"mode": "readability", "cues": [cue(1000, 1000, "一二三四五六七八九十")]}
    assert "readability.cps" not in rules(subject)


def test_line_length_zh():
    subject = {"mode": "readability", "cues": [cue(0, 5000, "一" * 17)]}
    record = only(subject, "readability.line-length")
    assert record.evidence["expected"] == "<= 16000 千分字符（档位 zh）"


def test_line_length_en_uses_half_limit():
    # 43 半角 = 21500 千分 > 42*500 = 21000
    subject = {"mode": "readability", "cues": [cue(0, 5000, "a" * 43)]}
    record = only(subject, "readability.line-length")
    assert record.evidence["expected"] == "<= 21000 千分字符（档位 en）"


def test_too_many_lines():
    subject = {"mode": "readability", "cues": [cue(0, 5000, "一", "二", "三")]}
    assert only(subject, "readability.too-many-lines").evidence["actual"] == "3"


def test_too_few_chars():
    subject = {"mode": "readability", "cues": [cue(0, 5000, "一")]}
    record = only(subject, "readability.too-few-chars")
    assert record.evidence["actual"] == "1000"


def test_duration_short():
    subject = {"mode": "readability", "cues": [cue(0, 500, "一二")]}
    assert only(subject, "readability.duration-short").verdict == WARN


def test_duration_long():
    subject = {"mode": "readability", "cues": [cue(0, 8000, "一二")]}
    assert only(subject, "readability.duration-long").verdict == WARN


def test_repeated_text_warn():
    subject = {"mode": "readability", "cues": [cue(0, 3000, "一二三"), cue(4000, 7000, "一二三")]}
    assert only(subject, "readability.repeated-text").verdict == WARN


def test_repeated_text_same_times_not_reported():
    subject = {"mode": "readability", "cues": [cue(0, 3000, "一二三"), cue(0, 3000, "一二三")]}
    assert "readability.repeated-text" not in rules(subject)


def test_readability_mode_skips_timing():
    subject = {"mode": "readability", "cues": [cue(0, 2000, "甲"), cue(1990, 4000, "乙")]}
    assert "timing.overlap" not in rules(subject)
    assert all(rule.startswith("readability.") for rule in rules(subject))


def test_readability_finding_lines_source_line():
    subject = {"mode": "readability", "cues": [cue(0, 500, "一二", source_line=77)]}
    assert only(subject, "readability.duration-short").evidence["line"] == 77


def test_readability_cps_message_lang_label():
    subject = {"mode": "readability", "cues": [cue(0, 1000, "一二三四五六七八九十一二三四五六七八九十")]}
    assert "中文" in only(subject, "readability.cps").message


def test_measure_cue_all_decorations_zero():
    measured = core.measure_cue(["[music]", "（笑声）", "♪"])
    assert measured == {"charsMilli": 0, "maxLineWidthMilli": 0, "visibleLineCount": 0}


def test_dominant_lang_half_dominant_en():
    assert core.dominant_lang(["abc你好"]) == "en"


def test_line_width_cjk_punctuation_counts_full():
    assert core.line_width_milli("！") == spec.FULL_MILLI


# ============================================================ F · 卫生 S01–S10
def test_s01_cjk_latin_fires():
    assert core.cjk_latin_spacing("你好world", spec.WHITELIST) == "world"


def test_s01_latin_before_cjk_fires():
    assert core.cjk_latin_spacing("abc你好", spec.WHITELIST) == "abc"


def test_s01_whitelist_suppressed():
    assert core.cjk_latin_spacing("用iPhone拍摄", spec.WHITELIST) is None


def test_s01_pure_cjk_not_fires():
    assert core.cjk_latin_spacing("你好世界", spec.WHITELIST) is None


def test_s02_zh_halfwidth_punct():
    assert core.punctuation_width("你好,世界", spec.WHITELIST) == ","


def test_s02_en_fullwidth_punct():
    assert core.punctuation_width("hello，world", spec.WHITELIST) == "，"


def test_s02_numbers_not_reported():
    assert core.punctuation_width("版本1.5发布", spec.WHITELIST) is None


def test_s02_ellipsis_not_reported():
    assert core.punctuation_width("你好...", spec.WHITELIST) is None


def test_s03_trailing_cn_period():
    assert core.trailing_punctuation("你好。", spec.WHITELIST) == "。"


def test_s03_trailing_dot():
    assert core.trailing_punctuation("hello.", spec.WHITELIST) == "."


def test_s03_question_not():
    assert core.trailing_punctuation("你好？", spec.WHITELIST) is None


def test_s03_ellipsis_not():
    assert core.trailing_punctuation("hello...", spec.WHITELIST) is None


def test_s03_whitelist_abbrev_not():
    assert core.trailing_punctuation("for example e.g.", spec.WHITELIST) is None


def test_s04_unclosed_i():
    assert core.unclosed_tag("<i>斜体") == "<i>"


def test_s04_self_closing_ok():
    assert core.unclosed_tag("<i/>正常") is None


def test_s04_cross_nesting():
    assert core.unclosed_tag("<b><i></b></i>") == "</b>"


def test_s04_closing_without_open():
    assert core.unclosed_tag("</i>孤立") == "</i>"


def test_s05_ass_override():
    assert core.ass_override_residue(r"{\an8}顶部") == r"{\an8}"


def test_s05_unclosed_brace():
    assert core.ass_override_residue("{未闭合") == "{"


def test_s06_percent_s():
    assert core.placeholder_residue("共 %s 项") == "%s"


def test_s06_index_brace():
    assert core.placeholder_residue("第 {0} 项") == "{0}"


def test_s06_named_brace():
    assert core.placeholder_residue("你好 {name}") == "{name}"


def test_s06_single_letter_brace_not():
    assert core.placeholder_residue("集合 {x}") is None


def test_s07_font_tag():
    assert core.font_tag_residue('<font color="red">红</font>') == '<font color="red">'


def test_s08_music_bracket():
    assert core.sdh_marker("[music] 背景") == "[music]"


def test_s08_paren_emotion():
    assert core.sdh_marker("（笑声）他说") == "（笑声）"


def test_s08_note():
    assert core.sdh_marker("哼♪") == "♪"


def test_s08_song_context_not():
    assert core.sdh_marker("♪ 啦啦啦 ♪") is None


def test_s09_all_caps():
    assert core.all_caps("A" * 20, spec.WHITELIST, TH["hygiene.allCapsMinLength"]) == "A" * 20


def test_s09_short_not():
    assert core.all_caps("ABC", spec.WHITELIST, TH["hygiene.allCapsMinLength"]) is None


def test_s09_whitelist_not():
    assert core.all_caps("IPHONE" * 4, spec.WHITELIST, TH["hygiene.allCapsMinLength"]) == "IPHONE" * 4


def test_s10_repeat_punct():
    assert core.repeated_punctuation("你好！！！", TH["hygiene.repeatPunctMin"]) == "！！！"


def test_s10_two_not_enough():
    assert core.repeated_punctuation("你好！！", TH["hygiene.repeatPunctMin"]) is None


def test_hygiene_same_rule_once_per_cue():
    subject = {"mode": "hygiene", "cues": [cue(0, 3000, "你好world", "再见world")]}
    assert rules(subject).count("hygiene.cjk-latin-spacing") == 1


def test_hygiene_whitelist_counts_in_summary():
    subject = {"mode": "hygiene", "cues": [cue(0, 3000, "用 iPhone 与 iPhone 拍摄")]}
    record = summary(subject)
    assert record.evidence["whitelist"] == {"iPhone": 2}


def test_hygiene_mode_only():
    subject = {"mode": "hygiene", "cues": [cue(0, 100, "你好.world")]}
    assert all(rule.startswith("hygiene.") for rule in rules(subject))


def test_hygiene_checks_order_matches_spec():
    assert tuple(entry[0] for entry in core._CHECK_ORDER) == spec.HYGIENE_RULES


def test_hygiene_multiple_rules_same_cue():
    subject = {"mode": "hygiene", "cues": [cue(0, 3000, "<i>你好world。")]}
    found = set(rules(subject))
    assert {"hygiene.cjk-latin-spacing", "hygiene.trailing-punctuation",
            "hygiene.unclosed-tag"} <= found


# ============================================================ G · 可逆修复
SRT_TWO = (
    "1\n"
    "00:00:00,000 --> 00:00:04,000\n"
    "甲\n"
    "\n"
    "2\n"
    "00:00:03,900 --> 00:00:09,000\n"
    "乙"
)


def test_fix_shape_of_comma_sep():
    assert core.shape_of("00:00:01,000") == {"hourDigits": 2, "sep": ",", "fracDigits": 3}


def test_fix_shape_of_rejects_garbage():
    assert core.shape_of("不是时间码") is None


def test_fix_format_ms_pads():
    shape = core.shape_of("1:02:03.004")
    assert core.format_ms(3723004, shape) == "1:02:03.004"


def test_fix_format_ms_fraction_digits():
    shape = {"hourDigits": 2, "sep": ",", "fracDigits": 1}
    assert core.format_ms(1500, shape) == "00:00:01,5"


def test_fix_rewrite_time_line_preserves_shape():
    line = "00:00:01,000 --> 00:00:02,000"
    assert core.rewrite_time_line(line, 0, 1500) == "00:00:00,000 --> 00:00:01,500"


def test_fix_rewrite_time_line_needs_two_tokens():
    assert core.rewrite_time_line("00:00:01,000 只有一个", 0, 1000) is None


def test_fix_overlap_trim():
    cues = [
        cue(0, 4000, "甲", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(3900, 9000, "乙", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ]
    fixed = core.apply_fix(SRT_TWO, cues, TH)
    assert fixed["fixes"][0]["ruleId"] == "fix.trim-overlap"
    assert "00:00:03,820" in fixed["text"]


def test_fix_gap_fill():
    text = "1\n00:00:00,000 --> 00:00:04,000\n甲\n\n2\n00:00:04,050 --> 00:00:05,000\n乙"
    cues = [
        cue(0, 4000, "甲", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(4050, 5000, "乙", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ]
    fixed = core.apply_fix(text, cues, TH)
    assert fixed["fixes"][0]["ruleId"] == "fix.fill-gap"
    assert "00:00:03,970" in fixed["text"]


def test_fix_guard_duration_min():
    text = "1\n00:00:00,000 --> 00:00:00,850\n甲\n\n2\n00:00:00,860 --> 00:00:05,000\n乙"
    cues = [
        cue(0, 850, "甲", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(860, 5000, "乙", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ]
    fixed = core.apply_fix(text, cues, TH)
    assert [item["ruleId"] for item in fixed["fixes"]] == []
    assert fixed["text"] == text


def test_fix_guard_positive_duration():
    text = "1\n00:00:00,000 --> 00:00:00,050\n甲\n\n2\n00:00:00,020 --> 00:00:05,000\n乙"
    cues = [
        cue(0, 50, "甲", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(20, 5000, "乙", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ]
    assert core.apply_fix(text, cues, TH)["fixes"] == []


def test_fix_strip_trailing_space():
    text = "1\n00:00:00,000 --> 00:00:02,000\n你好   "
    cues = [cue(0, 2000, "你好", source_line=1, end_line=3, time_line=2, index=1, format="srt",
                text_line_numbers=[3])]
    fixed = core.apply_fix(text, cues, TH)
    assert fixed["text"].endswith("你好")
    assert fixed["fixes"][0]["ruleId"] == "fix.strip-trailing-space"


def test_fix_all_whitespace_line_untouched():
    assert core.strip_trailing_space("   ") is None


def test_fix_close_tags():
    assert core.close_tags("<i>斜体") == "<i>斜体</i>"


def test_fix_close_tags_double():
    assert core.close_tags("<b><i>双层") == "<b><i>双层</i></b>"


def test_fix_close_tags_cross_nesting_none():
    assert core.close_tags("<b><i></b>") is None


def test_fix_trailing_space_before_tag_close():
    text = "1\n00:00:00,000 --> 00:00:02,000\n<i>斜体  "
    cues = [cue(0, 2000, "<i>斜体", source_line=1, end_line=3, time_line=2, index=1, format="srt",
                text_line_numbers=[3])]
    fixed = core.apply_fix(text, cues, TH)
    assert fixed["text"].endswith("<i>斜体</i>")


def test_fix_renumber_srt():
    text = ("1\n00:00:05,000 --> 00:00:06,000\n后\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n先")
    cues = [
        cue(5000, 6000, "后", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(1000, 2000, "先", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ]
    fixed = core.apply_fix(text, cues, TH)
    assert fixed["text"].split("\n")[0] == "1"
    assert fixed["text"].split("\n")[4] == "2"
    assert fixed["text"].split("\n")[2] == "先"
    assert [item["ruleId"] for item in fixed["fixes"]] == ["fix.renumber-index"] * 2


def test_fix_renumber_requires_index_lines():
    text = "x\n00:00:05,000 --> 00:00:06,000\n后"
    cues = [cue(5000, 6000, "后", source_line=1, end_line=3, time_line=2, index=7, format="srt",
                text_line_numbers=[3])]
    assert core.plan_reorder(text.split("\n"), cues) is None


def test_fix_renumber_non_srt_skipped():
    cues = [cue(0, 1000, "甲", source_line=1, end_line=3, time_line=2, index=1, format="vtt")]
    assert core.plan_reorder(["1", "00:00:00.000 --> 00:00:01.000", "甲"], cues) is None


def test_fix_crlf_output():
    text = "1\n00:00:00,000 --> 00:00:02,000\n你好   "
    cues = [cue(0, 2000, "你好", source_line=1, end_line=3, time_line=2, index=1, format="srt",
                text_line_numbers=[3])]
    fixed = core.apply_fix(text, cues, TH, eol="crlf")
    assert "\r\n" in fixed["text"]
    assert "\n\n" not in fixed["text"].replace("\r\n", "\n").replace("\n\n", "")


def test_fix_mode_records_info_and_no_op_skip():
    records = evaluate({"mode": "fix", "text": SRT_TWO, "cues": [
        cue(0, 4000, "甲", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(3900, 9000, "乙", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ]})
    fix_records = [record for record in records if record.rule_id.startswith("fix.")]
    assert fix_records and all(record.verdict == INFO for record in fix_records)
    assert not [record for record in records if "no_fixable_finding" in record.path]


def test_fix_mode_no_op_produces_skip():
    records = evaluate({"mode": "fix", "text": "洁净文本", "cues": []})
    assert [record for record in records if "no_fixable_finding" in record.path]


# ============================================================ H · 账本与端到端
def test_all_mode_composes_three_domains():
    subject = {"mode": "all", "cues": [
        cue(0, 500, "你好world"),
        cue(490, 4000, "再见。"),
    ]}
    found = set(rules(subject))
    assert any(rule.startswith("timing.") for rule in found)
    assert any(rule.startswith("readability.") for rule in found)
    assert any(rule.startswith("hygiene.") for rule in found)


def test_all_mode_with_text_fix_records():
    subject = {"mode": "all", "cues": [
        cue(0, 4000, "甲", source_line=1, end_line=3, time_line=2, index=1, format="srt",
            text_line_numbers=[3]),
        cue(3900, 9000, "乙", source_line=5, end_line=7, time_line=6, index=2, format="srt",
            text_line_numbers=[7]),
    ], "text": SRT_TWO}
    assert any(record.rule_id.startswith("fix.") for record in evaluate(subject))


def test_all_mode_with_bytes_decode_records():
    subject = {
        "mode": "all",
        "cues": [],
        "bytes_b64": base64.b64encode("你好".encode("gbk")).decode(),
    }
    assert "decode.gbk-fallback" in [record.rule_id for record in evaluate(subject)]


def test_bad_mode_input_error():
    with pytest.raises(ValueError):
        evaluate({"mode": "nope", "cues": []})


def test_missing_cues_input_error():
    with pytest.raises(ValueError):
        evaluate({"mode": "all"})


def test_cue_missing_start_input_error():
    with pytest.raises(ValueError):
        evaluate({"mode": "timing", "cues": [{"endMs": 1000}]})


def test_cue_non_numeric_start_input_error():
    with pytest.raises(ValueError):
        evaluate({"mode": "timing", "cues": [{"startMs": "0", "endMs": 1000}]})


def test_textlines_type_input_error():
    with pytest.raises(ValueError):
        evaluate({"mode": "hygiene", "cues": [{"startMs": 0, "endMs": 1000, "textLines": "x"}]})


def test_fix_mode_requires_text():
    with pytest.raises(ValueError):
        evaluate({"mode": "fix", "cues": []})


def test_decode_mode_requires_bytes():
    with pytest.raises(ValueError):
        evaluate({"mode": "decode"})


def test_report_json_deterministic():
    subject = {"mode": "all", "cues": [cue(0, 2000, "你好world"), cue(1990, 4000, "再见。")]}
    first = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="s.json",
                   records=evaluate(subject))
    second = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="s.json",
                    records=evaluate(subject))
    assert json.dumps(first.as_dict(), ensure_ascii=False) == json.dumps(second.as_dict(), ensure_ascii=False)


def test_blocking_exit_code_via_report():
    blocked = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="s",
                     records=evaluate({"mode": "timing", "cues": [cue(0, 2000, "甲"),
                                                                  cue(1990, 3000, "乙")]}))
    assert blocked.exit_code() == 1
    clean = Report(product="byteproof", organ=SLUG, organ_version=ORGAN_VERSION, subject="s",
                   records=evaluate({"mode": "hygiene", "cues": []}))
    assert clean.exit_code() == 0


def test_empty_subject_timing_still_explicit_skips():
    paths = [record.path for record in skips({"mode": "timing", "cues": []})]
    assert "skip:timing.past-media-end:media_duration_unknown" in paths
    assert "skip:timing.fps-drift:media_fps_unknown" in paths


def test_timing_rule_coverage():
    subjects = [
        {"mode": "timing", "cues": [cue(-100, 1000, "甲")]},
        {"mode": "timing", "cues": [cue(0, 0, "甲")]},
        {"mode": "timing", "cues": [cue(2000, 1500, "甲")]},
        {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(2050, 4000, "乙")]},
        {"mode": "timing", "cues": [cue(1000, 2000, "甲"), cue(500, 1500, "乙")]},
        {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(0, 2000, "甲")]},
        {"mode": "timing", "cues": [cue(0, 2000, "甲"), cue(1990, 4000, "乙")]},
        {"mode": "timing", "cues": [cue(0, 2000, "甲")], "declared": {"mediaDurationMs": 1000}},
        {"mode": "timing", "cues": [cue(5000, 6000, "甲"), cue(1000, 2000, "乙")]},
        {"mode": "timing", "cues": [cue(0, 1000, "甲")], "diagnostics": [
            {"code": "parse.unparsable-timecode", "line": 3},
            {"code": "parse.timecode-precision", "line": 4}]},
        {"mode": "timing", "cues": stretch(grid_cues(24, 23.976), TRUE_SCALE),
         "declared": {"declaredFps": 23.976}},
    ]
    found = set()
    for subject in subjects:
        found |= set(rules(subject))
    assert set(spec.TIMING_RULES) <= found, set(spec.TIMING_RULES) - found


def test_hygiene_rule_coverage():
    lines = [
        "你好world",
        "你好,世界",
        "你好。",
        "<i>斜体",
        "{" + chr(92) + "an8}顶部",
        "共 %s 项",
        '<font color="red">红</font>',
        "[music] 背景",
        "A" * 20,
        "你好！！！",
    ]
    cues = [cue(index * 3000, index * 3000 + 2000, line) for index, line in enumerate(lines)]
    found = set(rules({"mode": "hygiene", "cues": cues}))
    assert set(spec.HYGIENE_RULES) <= found, set(spec.HYGIENE_RULES) - found


def test_readability_rule_coverage():
    cues = [
        cue(0, 300, "一二三四五六七八九十一二三四五六七八九十", source_line=1),
        cue(400, 1900, "一" * 17, source_line=3),
        cue(2000, 9000, "一", "二", "三", source_line=5),
        cue(9100, 12000, "一二三", source_line=7),
        cue(12100, 12700, "一二三", source_line=9),
        cue(12800, 25000, "一二三", source_line=11),
        cue(25100, 30000, "一", source_line=13),
    ]
    found = set(rules({"mode": "readability", "cues": cues}))
    assert set(spec.READABILITY_RULES) <= found, set(spec.READABILITY_RULES) - found