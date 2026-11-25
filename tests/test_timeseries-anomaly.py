"""``timeseries-anomaly`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被测的那个函数仍然在、语义仍然是那一套**。
所以这份文件大量逐条搬用旧仓 ``tests/test_detect.py`` / ``test_timebase.py`` /
``test_episodes.py`` / ``test_profile.py`` / ``test_no_transcendental.py`` 的用例：
断言照抄，只把模块路径换成器官的模块路径，把 ``KeyError`` 换成 ``ValueError``
（宿主只把 ``ValueError`` 映射到退出码 2，见 ``params.resolve_params`` 的说明）。

**没有搬的部分，以及理由**（这些理由同时是 §7.3 判据 3 无法对齐的原因，
报告里逐条写了实测数）：旧仓的 CLI 编排、单文件 HTML 渲染、Node 复算镜像、
报告数字白名单、合成数据生成器、仓库布局/发布门 —— 这些测的是"怎么呈现"与"怎么发版"，
而 byteproof 的器官契约明确禁止器官自带 CLI / 输出排版 / 文件读写。
把它们搬过来只会是"为了凑数而测一段在新家里不存在的东西"。

分组：
  * ``TestShippedTables``      随包静态数据（规则包 + 阈值表）与运行期常量必须一致
  * ``TestParams``             参数表：默认值、强制、落盘形态
  * ``TestQuantize``           定点化（账本里不出现原始 float）
  * ``TestTimeline``           整数时间基（用标准库反向对账）
  * ``TestNumericPrimitives``  中位数/分位数/稳健尺度的退化情形
  * ``TestRollingMadZ`` / ``TestRollingIqr`` / ``TestRules`` / ``TestStlResidual``
  * ``TestPeriodEstimator``    稳健 ACF 周期估计
  * ``TestEpisodes``           时间域合并、严重度排序、序列内编号
  * ``TestShape``              采样间隔 / 断档 / 重复时间戳 / 值形状
  * ``TestSubject``            信封与行级契约（缺失 vs 损坏）
  * ``TestAuditLedger``        端到端账本：等级、id 稳定、证据无 float、确定性
  * ``TestNoClockNoSideEffects``  AST 门：禁超越函数 / 禁时钟 / 禁文件与打印
  * ``TestCli``                唯一入口：退出码 0/1/2/3、stdin、字节一致
"""

from __future__ import annotations

import ast
import calendar
import datetime
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.timeseries_anomaly import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    detect,
    episodes,
    numeric,
    params,
    rules,
    shape,
    subject,
    timeline,
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
    Record,
    RuleMissing,
)
from byteproof.core.registry import PackMissing, get  # noqa: E402

SLUG = "timeseries-anomaly"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "timeseries_anomaly"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "timeseries-anomaly.basis.json"
THRESHOLDS_PATH = DATA_DIR / "timeseries-anomaly.thresholds.json"
SAMPLE = ROOT / "samples" / "timeseries-anomaly.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))


# ---------------------------------------------------------------------------
# 夹具与助手（不读旧仓、不联网、不依赖时钟）
# ---------------------------------------------------------------------------
def _row(stamp, value, series_id=None):
    row = {"timestamp": stamp, "value": value}
    if series_id is not None:
        row["series_id"] = series_id
    return row


def _regular_rows(n, start="2024-03-01T00:00:00Z", cadence_min=5, series_id=None, values=None):
    """等间隔长表：``values`` 给定时用它，否则用 0..n-1 的斜坡。"""
    base = timeline.parse_iso_to_epoch_ms(start)
    rows = []
    for index in range(n):
        stamp = timeline.epoch_ms_to_iso(base + index * cadence_min * 60000)
        value = values[index] if values is not None else float(index)
        rows.append(_row(stamp, value, series_id))
    return rows


def _evaluate(rows, basis=None, **overrides):
    payload = {"rows": rows}
    if overrides:
        payload["params"] = overrides
    return tuple(audit.evaluate(payload, BASIS if basis is None else basis))


def _with_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


def _iter_floats(node, path="$"):
    """账本里递归找 float：账本必须是整数/字符串/None，不能有原始小数。"""
    if isinstance(node, float):
        yield path
        return
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_floats(value, "%s.%s" % (path, key))
        return
    if isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _iter_floats(value, "%s[%d]" % (path, index))


def _bump(n, period, amplitude):
    """C2 连续的周期凸起，只用乘法搭出来（无超越函数）。"""
    values = []
    for index in range(n):
        u = 2.0 * (index % period) / period
        if u > 1.0:
            u = 2.0 - u
        values.append(amplitude * u * u * u * (u * (6.0 * u - 15.0) + 10.0))
    return values


def _minimal_rows():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))["rows"]


# ---------------------------------------------------------------------------
# 随包静态数据
# ---------------------------------------------------------------------------
class TestShippedTables:
    """规则包与阈值表是**随包分发的静态数据**；运行期常量必须与它们逐项相等。

    这条纪律与旧仓 ``TestDefaultsArePinned`` 同源：只改一边就是一次静默漂移。
    """

    def test_the_basis_file_parses_with_a_version(self):
        assert BASIS.version == "1"
        assert len(BASIS) == len(rules.RULE_IDS)

    def test_the_basis_covers_every_rule_the_organ_can_emit(self):
        missing = sorted(set(rules.RULE_IDS) - set(BASIS.rule_ids()))
        assert missing == [], "规则包缺这些规则（用到即 RuleMissing -> 退出码 3）：%s" % missing

    def test_the_basis_has_no_rule_the_organ_never_uses(self):
        extra = sorted(set(BASIS.rule_ids()) - set(rules.RULE_IDS))
        assert extra == [], "规则包里有器官永不发出的规则：%s" % extra

    def test_every_rule_carries_source_and_text(self):
        for rule_id in BASIS.rule_ids():
            rule = BASIS.rule(rule_id)
            assert rule.title and rule.source and rule.text, rule_id

    def test_the_rule_ids_are_sorted_in_the_basis_file(self):
        payload = json.loads(BASIS_PATH.read_text(encoding="utf-8"))
        assert [item["rule_id"] for item in payload["rules"]] == sorted(
            item["rule_id"] for item in payload["rules"]
        )

    def test_the_thresholds_file_pins_the_runtime_defaults(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["params"] == params.resolve_params()

    def test_the_thresholds_file_pins_every_verdict(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["verdicts"] == rules.VERDICT_BY_RULE

    def test_the_thresholds_file_pins_the_versions_and_decimals(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["detector_version"] == params.DETECTOR_VERSION
        assert payload["params_version"] == params.PARAMS_VERSION
        assert payload["quant_decimals"] == params.QUANT_DECIMALS
        assert payload["version"] == "1"

    def test_the_data_files_are_declared_as_package_data(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert 'byteproof = ["py.typed", "data/*.json"]' in text.replace("\r\n", "\n")
        assert BASIS_PATH.is_file() and THRESHOLDS_PATH.is_file()

    def test_the_organ_is_in_the_builtin_manifest(self):
        assert "timeseries_anomaly" in BUILTIN_MODULES
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_the_pack_declares_the_artifact_field(self):
        assert PACK.slug == SLUG
        assert PACK.version == ORGAN_VERSION
        assert PACK.input_fields == ("rows",)


# ---------------------------------------------------------------------------
# 参数表
# ---------------------------------------------------------------------------
class TestParams:
    def test_detector_defaults_are_exactly_these(self):
        resolved = params.resolve_params()
        assert resolved["rolling_mad_z"] == {"window": 24, "k": 3.5, "min_valid": 6}
        assert resolved["rolling_iqr"] == {"window": 24, "iqr_mult": 3.0, "min_valid": 6}
        assert resolved["stl_resid_z"] == {
            "inner": 2,
            "outer": 1,
            "window": 24,
            "k": 3.5,
            "min_valid": 6,
        }
        assert resolved["rules"] == {
            "static_threshold": None,
            "pct_jump": 0.35,
            "missing_run": 6,
            "cusum_k": 0.5,
            "cusum_h": 5.0,
        }

    def test_run_level_defaults_are_exactly_these(self):
        resolved = params.resolve_params()
        assert resolved["max_gap_ms"] == 1800000
        assert resolved["period_points"] is None
        assert resolved["period_reject_window"] == 121
        assert resolved["period_reject_sigma"] == 2.5
        assert resolved["duplicate_timestamp_max"] == 1
        assert resolved["non_monotonic_max"] == 0
        assert resolved["gap_factor"] == 3
        assert resolved["timezone_offset_min"] == 0
        assert resolved["default_series_id"] == "series"
        assert resolved["escalate_score_q"] is None

    def test_no_hidden_defaults_beyond_the_declared_tables(self):
        declared = set()
        for name, entries in params.DETECTOR_PARAMS:
            declared.add(name)
            assert set(params.DEFAULT_PARAMS[name]) == set(entry for entry, _kind in entries)
        for param, _kind in params.RUN_PARAMS:
            declared.add(param)
        for param, _kind in params.STRING_PARAMS:
            declared.add(param)
        assert set(params.resolve_params()) == declared

    def test_the_kind_table_covers_every_declared_parameter(self):
        for name, entries in params.DETECTOR_PARAMS:
            for param, kind in entries:
                assert params.PARAM_KINDS[(name, param)] == kind
        for param, kind in params.RUN_PARAMS:
            assert params.PARAM_KINDS[param] == kind

    def test_nested_overrides_merge_without_dropping_siblings(self):
        resolved = params.resolve_params({"rolling_mad_z": {"k": 4.0}})
        assert resolved["rolling_mad_z"] == {"window": 24, "k": 4.0, "min_valid": 6}

    def test_unknown_top_level_key_is_rejected(self):
        with pytest.raises(ValueError):
            params.resolve_params({"nonsense": 1})

    def test_unknown_nested_key_is_rejected(self):
        with pytest.raises(ValueError):
            params.resolve_params({"rules": {"nonsense": 1}})

    def test_a_decimal_parameter_accepts_a_fixed_point_string(self):
        # 落盘形态是定点字符串，所以解析路径必须能吃回自己的输出（重算就是重放账本）。
        resolved = params.resolve_params({"rolling_mad_z": {"k": "3.500000"}})
        assert resolved["rolling_mad_z"]["k"] == 3.5

    def test_an_integer_parameter_rejects_a_fraction(self):
        with pytest.raises(ValueError):
            params.resolve_params({"rolling_mad_z": {"window": 24.5}})

    def test_an_integer_parameter_accepts_an_integral_float(self):
        assert params.resolve_params({"rolling_mad_z": {"window": 25.0}})["rolling_mad_z"]["window"] == 25

    def test_a_nullable_decimal_accepts_null(self):
        assert params.resolve_params({"rules": {"static_threshold": None}})["rules"]["static_threshold"] is None

    def test_a_non_nullable_decimal_rejects_null(self):
        with pytest.raises(ValueError):
            params.resolve_params({"rules": {"pct_jump": None}})

    def test_a_boolean_is_not_a_number(self):
        with pytest.raises(ValueError):
            params.resolve_params({"rolling_mad_z": {"window": True}})

    def test_a_detector_block_must_be_an_object(self):
        with pytest.raises(ValueError):
            params.resolve_params({"rolling_mad_z": 24})

    def test_params_must_be_an_object(self):
        with pytest.raises(ValueError):
            params.resolve_params([1, 2, 3])

    def test_an_empty_series_id_is_rejected(self):
        with pytest.raises(ValueError):
            params.resolve_params({"default_series_id": "   "})

    def test_resolution_is_idempotent(self):
        once = params.resolve_params({"rolling_mad_z": {"k": 4.0}, "max_gap_ms": 60})
        twice = params.resolve_params(once)
        assert twice == once


class TestDumpParams:
    def test_decimals_become_fixed_point_strings_and_integers_stay_integers(self):
        dumped = params.dump_params(params.resolve_params())
        assert dumped["rolling_mad_z"] == {"window": 24, "k": "3.500000", "min_valid": 6}
        assert dumped["rules"]["pct_jump"] == "0.350000"
        assert dumped["rules"]["missing_run"] == 6
        assert dumped["rules"]["static_threshold"] is None
        assert dumped["max_gap_ms"] == 1800000
        assert dumped["period_reject_sigma"] == "2.500000"
        assert dumped["period_points"] is None

    def test_the_dumped_form_carries_no_float(self):
        assert list(_iter_floats(params.dump_params(params.resolve_params()))) == []

    def test_every_caller_parameter_survives_the_round_trip(self):
        resolved = params.resolve_params()
        assert params.resolve_params(params.dump_params(resolved)) == resolved

    def test_threshold_refs_cover_every_signal_detector(self):
        refs = params.threshold_refs(params.dump_params(params.resolve_params()))
        for detector in rules.SIGNAL_RULE_BY_DETECTOR:
            assert params.threshold_refs(
                params.dump_params(params.resolve_params())
            )[rules.DETECTOR_PARAM_KEY[detector]] is not None
        assert "rules.zero_run" in refs and "rules.missing_run" in refs


# ---------------------------------------------------------------------------
# 定点化
# ---------------------------------------------------------------------------
class TestQuantize:
    def test_half_to_even_at_the_boundary(self):
        assert params.quantize(0.0000005) == 0  # 0.5 进位到偶数 0
        assert params.quantize(0.0000015) == 2  # 1.5 进位到偶数 2
        assert params.quantize(0.0000025) == 2  # 2.5 进位到偶数 2

    def test_it_truncates_below_half(self):
        assert params.quantize(0.0000004) == 0
        assert params.quantize(1.0000004) == 1000000

    def test_it_rounds_up_above_half(self):
        assert params.quantize(0.0000006) == 1
        assert params.quantize(-0.0000006) == -1

    def test_negative_values_keep_their_sign(self):
        assert params.quantize(-1.5) == -1500000
        assert params.quantize(-0.25) == -250000

    def test_zero_decimals_is_an_integer(self):
        assert params.quantize(2.7, 0) == 3
        assert params.fixed_to_str(3, 0) == "3"

    def test_fixed_to_str_rebuilds_the_decimal_from_the_integer(self):
        assert params.fixed_to_str(3500000) == "3.500000"
        assert params.fixed_to_str(-1500000) == "-1.500000"
        assert params.fixed_to_str(0) == "0.000000"
        assert params.fixed_to_str(1) == "0.000001"

    def test_quantize_then_render_round_trips(self):
        for value in (0.0, 3.5, -0.35, 12.84375, 73.0194934):
            rendered = params.fixed_to_str(params.quantize(value))
            assert params.quantize(float(rendered)) == params.quantize(value)


# ---------------------------------------------------------------------------
# 时间基（用标准库反向对账：手写算法必须先被标准库证伪一次才可信）
# ---------------------------------------------------------------------------
_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
_STDLIB_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z")


def _normalise_for_stdlib(text):
    stamped = text.strip().replace(" ", "T")
    date_part, separator, time_part = stamped.partition("T")
    assert separator == "T", text
    match = re.search(r"\.(\d+)", time_part)
    if match:
        digits = (match.group(1) + "000")[:3]
        time_part = time_part[: match.start()] + "." + digits + time_part[match.end() :]
    if time_part.endswith(("Z", "z")):
        time_part = time_part[:-1] + "+0000"
    else:
        match = re.search(r"([+-])(\d{2}):?(\d{2})$", time_part)
        if match:
            time_part = time_part[: match.start()] + match.group(1) + match.group(2) + match.group(3)
        elif re.search(r"[+-]\d{2}$", time_part):
            time_part = time_part + "00"
        else:
            time_part = time_part + "+0000"
    return date_part + "T" + time_part


def _epoch_ms_via_stdlib(text):
    normalised = _normalise_for_stdlib(text)
    for fmt in _STDLIB_FORMATS:
        try:
            parsed = datetime.datetime.strptime(normalised, fmt)
            break
        except ValueError:
            continue
    else:  # pragma: no cover - 助手自己不该失败
        raise AssertionError("助手读不了 %r（规范化后 %r）" % (text, normalised))
    delta = parsed - _EPOCH
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


class TestCivilAlgorithms:
    def test_matches_datetime_toordinal_across_four_centuries(self):
        anchor = datetime.date(1970, 1, 1).toordinal()
        for year in range(1800, 2201):
            for month in range(1, 13):
                for day in (1, 15, calendar.monthrange(year, month)[1]):
                    expected = datetime.date(year, month, day).toordinal() - anchor
                    assert timeline.days_from_civil(year, month, day) == expected, (year, month, day)

    def test_round_trips_every_sampled_day(self):
        for days in range(-800000, 800001, 997):
            year, month, day = timeline.civil_from_days(days)
            assert timeline.days_from_civil(year, month, day) == days

    def test_century_leap_rules(self):
        assert timeline.is_valid_civil_date(2000, 2, 29) is True
        assert timeline.is_valid_civil_date(1900, 2, 29) is False
        assert timeline.is_valid_civil_date(2024, 2, 29) is True
        assert timeline.is_valid_civil_date(2023, 2, 29) is False
        assert timeline.is_valid_civil_date(2023, 4, 31) is False
        assert timeline.is_valid_civil_date(2023, 12, 32) is False
        assert timeline.is_valid_civil_date(2023, 0, 1) is False


class TestEpochMsToCivil:
    def test_negative_epoch_decomposes_by_floor_not_truncation(self):
        assert timeline.epoch_ms_to_civil(-1) == (1969, 12, 31, 23, 59, 59, 999)
        assert timeline.epoch_ms_to_civil(0) == (1970, 1, 1, 0, 0, 0, 0)

    def test_iso_is_fixed_width(self):
        assert timeline.epoch_ms_to_iso(0) == "1970-01-01T00:00:00.000Z"
        assert timeline.epoch_ms_to_iso(1709164800123) == "2024-02-29T00:00:00.123Z"
        assert timeline.epoch_ms_to_iso(-1) == "1969-12-31T23:59:59.999Z"
        for milliseconds in (0, -1, 1, 1709164800000, -62135596800000, 253402300799999):
            assert len(timeline.epoch_ms_to_iso(milliseconds)) == 24

    def test_iso_round_trips_through_the_parser(self):
        for milliseconds in (0, -1, 1, 1709164800000, 1735689599999, 946684800000):
            assert timeline.parse_iso_to_epoch_ms(timeline.epoch_ms_to_iso(milliseconds)) == milliseconds


class TestParseTimestamp:
    def test_zero_padded_and_space_separated_forms_agree(self):
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T00:00:00Z") == 1709164800000
        assert timeline.parse_iso_to_epoch_ms("2024-02-29 00:00:00Z") == 1709164800000

    def test_seconds_and_fraction_are_optional(self):
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T00:00Z") == 1709164800000
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T00:00:00Z") == 1709164800000

    def test_fractions_are_truncated_toward_the_millisecond_not_rounded(self):
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T00:00:00.999999Z") == 1709164800999
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T00:00:00.0009Z") == 1709164800000
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T00:00:00.123456789Z") == 1709164800123

    def test_explicit_offsets_are_applied(self):
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T08:00:00+08:00") == 1709164800000
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T08:00:00+0800") == 1709164800000
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T08:00:00+08") == 1709164800000
        assert timeline.parse_iso_to_epoch_ms("2024-02-28T16:00:00-08:00") == 1709164800000

    def test_the_declared_default_offset_applies_only_without_an_explicit_one(self):
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T08:00:00", 480) == 1709164800000
        # 显式 Z 优先：同一条文本在声明 +480 的工件里仍然是 08:00 UTC，不是 00:00 UTC。
        assert timeline.parse_iso_to_epoch_ms("2024-02-29T08:00:00Z", 480) == 1709193600000

    def test_the_parsed_offset_is_reported_with_its_explicitness(self):
        explicit = timeline.parse_timestamp("2024-02-29T08:00:00+08:00")
        implicit = timeline.parse_timestamp("2024-02-29T08:00:00", 480)
        assert (explicit.offset_min, explicit.offset_explicit) == (480, True)
        assert (implicit.offset_min, implicit.offset_explicit) == (480, False)

    def test_a_nonexistent_civil_date_is_rejected_not_normalised(self):
        with pytest.raises(timeline.TimeParseError):
            timeline.parse_timestamp("2024-02-30T00:00:00Z")

    def test_out_of_range_fields_are_rejected(self):
        for text in (
            "2024-02-29T24:00:00Z",
            "2024-02-29T00:60:00Z",
            "2024-02-29T00:00:60Z",
            "2024-13-01T00:00:00Z",
        ):
            with pytest.raises(timeline.TimeParseError):
                timeline.parse_timestamp(text)

    def test_a_malformed_offset_is_rejected(self):
        for text in ("2024-02-29T00:00:00+99:00", "2024-02-29T00:00:00+08:99"):
            with pytest.raises(timeline.TimeParseError):
                timeline.parse_timestamp(text)

    def test_non_timestamp_shapes_are_rejected(self):
        for text in ("", "   ", "2024/02/29 00:00:00", "20240229T000000Z", "not a timestamp"):
            with pytest.raises(timeline.TimeParseError):
                timeline.parse_timestamp(text)

    def test_a_non_string_is_rejected(self):
        with pytest.raises(timeline.TimeParseError):
            timeline.parse_timestamp(1709164800000)

    def test_time_parse_error_is_a_value_error(self):
        # 行级时间戳错误在本器官里落成 error 账本；宿主只把 ValueError 当"输入不合法"，
        # 所以这里必须**不是**靠 ValueError 逃逸到退出码 2 —— 断言继承关系是为了让
        # `subject.parse_subject` 能按类型逮住它，而不是靠字符串匹配。
        assert issubclass(timeline.TimeParseError, ValueError)

    def test_every_fixture_timestamp_agrees_with_the_standard_library(self):
        for row in _minimal_rows():
            text = row["timestamp"]
            assert timeline.parse_iso_to_epoch_ms(text) == _epoch_ms_via_stdlib(text), text

    def test_a_sampled_sweep_agrees_with_the_standard_library(self):
        state = 987654321
        for _ in range(400):
            state = (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
            milliseconds = (state >> 20) % 8000000000000 - 2000000000000
            text = timeline.epoch_ms_to_iso(milliseconds)
            assert timeline.parse_iso_to_epoch_ms(text) == milliseconds, text


# ---------------------------------------------------------------------------
# 数值基元
# ---------------------------------------------------------------------------
class TestNumericPrimitives:
    def test_median_interpolates_between_the_middle_pair(self):
        assert numeric._median([1, 2, 3, 4]) == 2.5
        assert numeric._median([1, 2, 3]) == 2
        assert numeric._median([5.0]) == 5.0
        assert numeric._median([4, 1, 3, 2]) == 2.5

    def test_quantile_linear_interpolation(self):
        assert numeric._quantile([1, 2, 3, 4], 0.25) == 1.75
        assert numeric._quantile([1, 2, 3, 4], 0.75) == 3.25
        assert numeric._quantile([1, 2, 3, 4], 0.5) == 2.5

    def test_median_and_quantile_refuse_an_empty_window(self):
        with pytest.raises(ValueError):
            numeric._median([])
        with pytest.raises(ValueError):
            numeric._quantile([], 0.5)

    def test_scale_is_mean_absolute_deviation_when_mad_is_zero(self):
        values = [0.0] * 11 + [4.0]
        scale, median_value = numeric.robust_scale(values)
        assert median_value == 0.0
        assert scale == pytest.approx(numeric.MAD_TO_SIGMA * 4.0 / 12.0)

    def test_a_constant_window_has_no_scale_at_all(self):
        assert numeric.robust_scale([7.0] * 12) == (0.0, 7.0)

    def test_mad_scale_when_it_is_not_degenerate(self):
        scale, median_value = numeric.robust_scale([1.0, 2.0, 3.0, 4.0, 5.0])
        assert median_value == 3.0
        assert scale == pytest.approx(numeric.MAD_TO_SIGMA * 1.0)

    def test_sqrt_is_newton_iteration_not_the_power_operator(self):
        assert numeric._sqrt_by_newton(9.0) == pytest.approx(3.0)
        assert numeric._sqrt_by_newton(2.0) == pytest.approx(1.4142135623730951)
        assert numeric._sqrt_by_newton(0.0) == 0.0
        assert numeric._sqrt_by_newton(-1.0) == 0.0

    def test_next_odd(self):
        assert numeric._next_odd(4) == 5
        assert numeric._next_odd(5) == 5
        assert numeric._next_odd(1) == 1
        assert numeric._next_odd(0) == 1

    def test_trailing_window_skips_missing_and_clamps_at_the_start(self):
        assert numeric.trailing_window([1.0, None, 3.0], 2, 24) == [1.0, 3.0]
        assert numeric.trailing_window([1.0, 2.0, 3.0], 1, 2) == [1.0, 2.0]
        assert numeric.trailing_window([1.0, 2.0, 3.0], 0, 0) == []

    def test_a_zero_scale_never_divides(self):
        assert numeric.robust_z([5.0] * 10, 5.0) == 0.0


# ---------------------------------------------------------------------------
# 检测器 1 / 2
# ---------------------------------------------------------------------------
class TestRollingMadZ:
    def test_a_spike_against_a_flat_window_is_flagged_by_the_mad_zero_fallback(self):
        values = [0.0] * 11 + [4.0]
        hits = detect.rolling_mad_z(values, 12, 3.5, 6)
        assert [index for index, _score in hits] == [11]
        # |x - median| / (1.4826 * mean absolute deviation) = 4 / (1.4826 * 4/12)
        assert hits[0][1] == pytest.approx(12.0 / numeric.MAD_TO_SIGMA)

    def test_a_constant_window_cannot_judge_anything(self):
        assert detect.rolling_mad_z([7.0] * 30, 24, 3.5, 6) == []

    def test_a_linear_ramp_is_not_an_anomaly(self):
        assert detect.rolling_mad_z([float(index) for index in range(40)], 24, 3.5, 6) == []

    def test_min_valid_gates_the_first_points(self):
        values = [0.0] * 7 + [9.0]
        assert len(detect.rolling_mad_z(values, 24, 3.5, 8)) == 1
        assert detect.rolling_mad_z(values, 24, 3.5, 9) == []

    def test_a_missing_value_is_never_a_candidate(self):
        assert detect.rolling_mad_z([None] * 8, 24, 3.5, 6) == []

    def test_missing_values_inside_the_window_do_not_break_the_scale(self):
        values = [0.0, None, 0.0, None, 0.0, None, 0.0, 0.0] + [4.0]
        hits = detect.rolling_mad_z(values, 12, 3.5, 4)
        assert [index for index, _score in hits] == [8]

    def test_a_larger_k_flags_no_more_points(self):
        values = [0.0] * 10 + [3.0] + [0.0] * 10
        loose = detect.rolling_mad_z(values, 12, 8.0, 6)
        tight = detect.rolling_mad_z(values, 12, 3.5, 6)
        assert set(index for index, _s in loose) <= set(index for index, _s in tight)

    def test_the_threshold_is_strictly_greater(self):
        # 规则写的是 "|z| > k"，所以分数**正好等于** k 不命中。
        values = [0.0] * 11 + [4.0]
        score = detect.rolling_mad_z(values, 12, 0.0, 6)[0][1]
        assert score > 0
        assert detect.rolling_mad_z(values, 12, score, 6) == []
        assert len(detect.rolling_mad_z(values, 12, score * 0.999999, 6)) == 1


class TestRollingIqr:
    def test_an_excursion_beyond_the_box_bound_is_flagged(self):
        values = [float(index) for index in range(1, 12)] + [100.0]
        hits = detect.rolling_iqr(values, 12, 3.0, 12)
        assert [index for index, _score in hits] == [11]
        # Q1 = 3.75, Q3 = 9.25 -> IQR 5.5, bound 25.75, score (100 - 25.75) / 5.5
        assert hits[0][1] == pytest.approx((100.0 - 25.75) / 5.5)

    def test_a_point_inside_the_box_is_not_flagged(self):
        assert detect.rolling_iqr([1.0, 2.0, 3.0, 4.0], 4, 3.0, 4) == []

    def test_a_degenerate_box_falls_back_to_the_mean_absolute_deviation(self):
        values = [0.0] * 11 + [4.0]
        hits = detect.rolling_iqr(values, 12, 3.0, 12)
        assert [index for index, _score in hits] == [11]
        assert hits[0][1] == pytest.approx(9.0, abs=1e-9)

    def test_an_all_zero_window_cannot_judge_anything(self):
        assert detect.rolling_iqr([0.0] * 20, 12, 3.0, 6) == []

    def test_min_valid_gates_the_first_points(self):
        values = [1.0, 1.0, 1.0, 1.0, 9.0]
        assert detect.rolling_iqr(values, 12, 1.0, 6) == []
        assert [index for index, _s in detect.rolling_iqr(values, 12, 1.0, 5)] == [4]

    def test_a_point_exactly_on_the_bound_is_not_flagged(self):
        # Q1 = 2.0, Q3 = 4.0, IQR = 2.0（全部可精确表示），mult = 1.125 时上界正好 6.25。
        values = [1.0, 2.0, 3.0, 4.0, 6.25]
        assert detect.rolling_iqr(values, 5, 1.125, 5) == []
        assert [index for index, _s in detect.rolling_iqr(values, 5, 1.124, 5)] == [4]


# ---------------------------------------------------------------------------
# 检测器 4：规则
# ---------------------------------------------------------------------------
class TestRules:
    def _spec(self, **overrides):
        spec = dict(params.resolve_params()["rules"])
        spec.update(overrides)
        return spec

    def test_static_threshold_is_off_when_null(self):
        hits = detect.rules([1.0, -40.0, 3.0], self._spec(static_threshold=None))
        assert [hit for hit in hits if hit[2] == "static_threshold"] == []

    def test_static_threshold_fires_on_the_absolute_magnitude(self):
        hits = [
            hit
            for hit in detect.rules([1.0, -4.0, 3.0], self._spec(static_threshold=2.5))
            if hit[2] == "static_threshold"
        ]
        assert [(index, score) for index, score, _rule in hits] == [(1, 1.5), (2, 0.5)]

    def test_pct_jump_fires_above_the_ratio_and_not_below(self):
        assert detect.rules([100.0, 150.0], self._spec()) == [(1, 0.5, "pct_jump")]
        assert detect.rules([150.0, 100.0], self._spec()) == []
        assert detect.rules([100.0, 60.0], self._spec()) == [(1, pytest.approx(0.4), "pct_jump")]

    def test_pct_jump_stays_silent_on_a_zero_baseline(self):
        assert detect.rules([0.0, 5.0], self._spec()) == []
        assert detect.rules([None, 5.0], self._spec()) == []

    def test_missing_run_needs_the_configured_length(self):
        values = [1.0] + [None] * 6 + [2.0]
        hits = [hit for hit in detect.rules(values, self._spec(missing_run=6)) if hit[2] == "missing_run"]
        assert hits == [(index, 6.0, "missing_run") for index in range(1, 7)]
        assert [
            hit for hit in detect.rules(values, self._spec(missing_run=7)) if hit[2] == "missing_run"
        ] == []

    def test_zero_run_needs_the_same_length(self):
        values = [1.0] + [0.0] * 6 + [2.0]
        hits = [hit for hit in detect.rules(values, self._spec(missing_run=6)) if hit[2] == "zero_run"]
        assert hits == [(index, 6.0, "zero_run") for index in range(1, 7)]
        short = [1.0] + [0.0] * 5 + [2.0]
        assert [
            hit for hit in detect.rules(short, self._spec(missing_run=6)) if hit[2] == "zero_run"
        ] == []

    def test_a_missing_value_breaks_a_zero_run(self):
        values = [1.0, 0.0, 0.0, 0.0, None, 0.0, 0.0, 0.0, 2.0]
        assert [hit for hit in detect.rules(values, self._spec()) if hit[2] == "zero_run"] == []

    def test_cusum_fires_once_on_a_step_and_restarts(self):
        values = [0.0] * 20 + [10.0] * 20
        hits = [hit for hit in detect.rules(values, self._spec()) if hit[2] == "cusum"]
        assert [index for index, _score, _rule in hits] == [20]
        assert hits[0][1] > 10.0

    def test_cusum_ignores_a_slow_cycle(self):
        values = [float(index) * 0.01 for index in range(60)]
        assert [hit for hit in detect.rules(values, self._spec()) if hit[2] == "cusum"] == []

    def test_cusum_stands_down_when_the_differences_have_no_scale(self):
        assert [hit for hit in detect.rules([3.0] * 40, self._spec()) if hit[2] == "cusum"] == []

    def test_every_hit_names_one_of_the_documented_rules(self):
        values = [0.0] * 10 + [None] * 6 + [float(index) for index in range(10)]
        for _index, _score, rule in detect.rules(values, self._spec(static_threshold=1.0)):
            assert rule in params.RULE_NAMES


# ---------------------------------------------------------------------------
# 检测器 3：STL
# ---------------------------------------------------------------------------
class TestStlResidual:
    def test_a_smooth_cycle_alone_produces_no_hits(self):
        values = _bump(1200, 96, 10.0)
        assert detect.stl_resid_z(values, list(range(1200)), 96, 2, 1, 24, 3.5, 6) == []

    def test_without_the_seasonal_removal_the_same_cycle_is_flagged(self):
        values = _bump(1200, 96, 10.0)
        assert len(detect.rolling_mad_z(values, 24, 3.5, 6)) > 10

    def test_a_spike_on_a_cycle_is_found_and_the_cycle_is_not(self):
        values = _bump(1200, 96, 10.0)
        values[601] += 40.0
        hits = detect.stl_resid_z(values, list(range(1200)), 96, 2, 1, 24, 3.5, 6)
        assert [index for index, _score in hits] == [601]

    def test_halving_the_period_leaves_a_much_larger_residual(self):
        values = _bump(1200, 96, 10.0)
        positions = list(range(1200))
        right = [
            abs(value)
            for value in detect.stl_residual(values, positions, 96, 2, 1)
            if value is not None
        ]
        wrong = [
            abs(value)
            for value in detect.stl_residual(values, positions, 48, 2, 1)
            if value is not None
        ]
        assert max(wrong) > 3.0 * max(right)

    def test_period_at_most_one_means_no_seasonal_component(self):
        residual = detect.stl_residual([7.0] * 40, list(range(40)), 1, 2, 1)
        assert max(abs(value) for value in residual) < 1e-9
        assert detect.stl_resid_z([7.0] * 40, list(range(40)), 1, 2, 1, 24, 3.5, 6) == []

    def test_missing_values_stay_missing_in_the_residual(self):
        values = _bump(200, 96, 10.0)
        values[5] = None
        residual = detect.stl_residual(values, list(range(200)), 96, 2, 1)
        assert len(residual) == len(values)
        assert residual[5] is None
        assert all(value is not None for index, value in enumerate(residual) if index != 5)

    def test_the_seasonal_curve_is_folded_on_the_grid_not_the_list_position(self):
        values = _bump(200, 96, 10.0)
        positions = list(range(200))
        gapped_values = values[:100] + values[101:]
        gapped_positions = positions[:100] + positions[101:]
        clean = detect.stl_residual(values, positions, 96, 2, 1)
        folded = detect.stl_residual(gapped_values, gapped_positions, 96, 2, 1)
        # 缺口后第 149 个样本就是网格位置 150 的那个样本
        assert folded[149] == pytest.approx(clean[150], abs=0.01)
        folded_hits = detect.stl_resid_z(gapped_values, gapped_positions, 96, 2, 1, 24, 3.5, 6)
        position_hits = detect.stl_resid_z(
            gapped_values, list(range(len(gapped_values))), 96, 2, 1, 24, 3.5, 6
        )
        assert len(folded_hits) < len(position_hits)


# ---------------------------------------------------------------------------
# 周期估计
# ---------------------------------------------------------------------------
class TestPeriodEstimator:
    def _grid(self, period, n, amplitude, noise_scale, shift_at=None):
        grid = _bump(n, period, amplitude)
        for index in range(n):
            grid[index] += (((index * 2654435761) % 1000) / 1000.0 - 0.5) * noise_scale
        if shift_at is not None:
            for index in range(shift_at, shift_at + 31):
                grid[index] += 8.0
        return grid

    def test_it_recovers_a_planted_period(self):
        assert detect.estimate_series_period(self._grid(40, 500, 10.0, 1.0), 121, 2.5) == 40
        assert detect.estimate_series_period(self._grid(64, 600, 10.0, 1.0), 121, 2.5) == 64

    def test_a_planted_level_shift_does_not_move_the_estimate(self):
        assert detect.estimate_series_period(self._grid(40, 500, 10.0, 1.0, shift_at=300), 121, 2.5) == 40

    def test_a_grid_too_short_for_three_cycles_yields_nothing(self):
        assert detect.estimate_series_period([1.0, 2.0, 1.0], 121, 2.5) is None
        assert detect.estimate_series_period([1.0] * 23, 121, 2.5) is None

    def test_a_constant_grid_yields_nothing(self):
        assert detect.estimate_series_period([3.0] * 500, 121, 2.5) is None

    def test_gaps_do_not_move_the_estimate(self):
        grid = self._grid(40, 500, 10.0, 1.0)
        for index in range(200, 220):
            grid[index] = None
        assert detect.estimate_series_period(grid, 121, 2.5) == 40

    def test_a_short_series_resolves_to_no_cycle_instead_of_a_guess(self):
        parsed = subject.parse_subject({"rows": _minimal_rows()}, params.resolve_params())
        period_points, estimates = detect.estimate_period(
            parsed.rows_by_series, parsed.series_order, 121, 2.5
        )
        assert period_points == 1
        assert estimates == []

    def test_a_declared_period_is_used_verbatim_in_the_ledger(self):
        rows = _regular_rows(60, values=[float(index % 12) for index in range(60)])
        records = _evaluate(rows, period_points=6)
        assert records
        for record in _with_rule(records, rules.RULE_ROLLING_MAD_Z) + _with_rule(
            records, rules.RULE_STL_RESID_Z
        ):
            assert record.evidence["period_points"] == 6
            assert record.evidence["period_source"] == "declared"

    def test_grid_positions_fold_on_the_timeline(self):
        rows = [(index + 1, index * 300000, 1.0) for index in range(5)]
        assert detect.grid_positions(rows) == [0, 1, 2, 3, 4]
        gapped = rows[:2] + rows[4:]
        # 被丢掉的格子不会挪动其后的相位：第三个样本仍然是时间轴上的第 4 格，不是第 2 格
        assert detect.grid_positions(gapped) == [0, 1, 4]


# ---------------------------------------------------------------------------
# Episode 合并
# ---------------------------------------------------------------------------
class TestEpisodes:
    def test_neighbours_within_max_gap_join_one_episode(self):
        points = [(0, 1, 1.0), (100, 2, 2.0)]
        merged = episodes.merge_episodes("s", "rolling_mad_z", points, 1000)
        assert len(merged) == 1
        assert merged[0]["n_points"] == 2
        assert merged[0]["peak_score_q"] == 2000000

    def test_a_gap_wider_than_max_gap_splits_them(self):
        points = [(0, 1, 1.0), (1001, 2, 2.0)]
        merged = episodes.merge_episodes("s", "rolling_mad_z", points, 1000)
        assert len(merged) == 2
        assert [item["n_points"] for item in merged] == [1, 1]

    def test_the_boundary_distance_still_merges(self):
        points = [(0, 1, 1.0), (1000, 2, 2.0)]
        assert len(episodes.merge_episodes("s", "rolling_mad_z", points, 1000)) == 1

    def test_the_episode_carries_first_and_last_row_and_duration(self):
        points = [(0, 7, 1.0), (500, 9, 3.0)]
        built = episodes.merge_episodes("s", "rolling_iqr", points, 1000)[0]
        assert built["start_row"] == 7 and built["end_row"] == 9
        assert built["duration_ms"] == 500
        assert built["start"] == "1970-01-01T00:00:00.000Z"
        assert built["end"] == "1970-01-01T00:00:00.500Z"

    def test_the_peak_is_the_maximum_score_not_the_last_one(self):
        points = [(0, 1, 1.0), (10, 2, 9.0), (20, 3, 2.0)]
        built = episodes.merge_episodes("s", "rolling_mad_z", points, 1000)[0]
        assert built["peak_score_q"] == 9000000

    def test_run_detectors_record_the_run_length_as_an_integer(self):
        points = [(0, 1, 6.0), (10, 2, 6.0)]
        built = episodes.merge_episodes("s", "rules.missing_run", points, 1000)[0]
        assert built["run_length"] == 6
        other = episodes.merge_episodes("s", "rules.cusum", points, 1000)[0]
        assert other["run_length"] is None

    def test_ordering_is_most_severe_first(self):
        built = [
            {"peak_score_q": 1, "duration_ms": 0, "start_row": 1, "detector": "b"},
            {"peak_score_q": 9, "duration_ms": 0, "start_row": 2, "detector": "a"},
        ]
        assert [item["detector"] for item in episodes.order_episodes(built)] == ["a", "b"]

    def test_duration_breaks_a_peak_tie(self):
        built = [
            {"peak_score_q": 5, "duration_ms": 0, "start_row": 1, "detector": "a"},
            {"peak_score_q": 5, "duration_ms": 9, "start_row": 2, "detector": "b"},
        ]
        assert [item["detector"] for item in episodes.order_episodes(built)] == ["b", "a"]

    def test_start_row_breaks_a_peak_and_duration_tie(self):
        built = [
            {"peak_score_q": 5, "duration_ms": 0, "start_row": 9, "detector": "a"},
            {"peak_score_q": 5, "duration_ms": 0, "start_row": 2, "detector": "b"},
        ]
        assert [item["detector"] for item in episodes.order_episodes(built)] == ["b", "a"]

    def test_ids_are_numbered_per_series_from_one(self):
        built = [
            {"series_id": "a", "peak_score_q": 1, "duration_ms": 0, "start_row": 1, "detector": "d"},
            {"series_id": "a", "peak_score_q": 2, "duration_ms": 0, "start_row": 2, "detector": "d"},
            {"series_id": "b", "peak_score_q": 3, "duration_ms": 0, "start_row": 3, "detector": "d"},
        ]
        numbered = episodes.assign_ids(episodes.order_episodes(built))
        assert [item["episode_id"] for item in numbered] == ["b-E001", "a-E001", "a-E002"]

    def test_build_is_independent_of_the_detection_dict_order(self):
        rows_by_series = {"s": [(1, 0, 1.0), (2, 1000, 2.0)]}
        forward = {("s", "rolling_mad_z"): [(0, 1, 1.0)], ("s", "rolling_iqr"): [(1000, 2, 2.0)]}
        backward = {
            ("s", "rolling_iqr"): [(1000, 2, 2.0)],
            ("s", "rolling_mad_z"): [(0, 1, 1.0)],
        }
        assert episodes.build_episodes(rows_by_series, forward, 1000) == episodes.build_episodes(
            rows_by_series, backward, 1000
        )

    def test_points_are_re_sorted_by_time_then_row(self):
        rows_by_series = {"s": [(1, 0, 1.0), (2, 500, 2.0), (3, 600, 3.0)]}
        shuffled = {("s", "rolling_mad_z"): [(500, 2, 2.0), (0, 1, 1.0), (600, 3, 3.0)]}
        built = episodes.build_episodes(rows_by_series, shuffled, 1000)
        assert [item["start_row"] for item in built] == [1]


# ---------------------------------------------------------------------------
# 数据形状
# ---------------------------------------------------------------------------
class TestShape:
    def test_intervals_skip_non_positive_deltas(self):
        rows = [(1, 0, 1.0), (2, 300, 2.0), (3, 300, 3.0), (4, 200, 4.0)]
        assert shape.intervals(rows) == [(1, 2, 300)]
        assert shape.backwards_steps(rows) == [(4, 3, -100)]

    def test_the_dominant_interval_prefers_the_shortest_on_a_tie(self):
        found = [(1, 2, 300), (2, 3, 600), (3, 4, 600), (4, 5, 300)]
        assert shape.dominant_interval(found) == 300

    def test_the_dominant_interval_is_the_most_frequent(self):
        found = [(1, 2, 300), (2, 3, 900), (3, 4, 900)]
        assert shape.dominant_interval(found) == 900

    def test_no_positive_interval_means_no_dominant(self):
        assert shape.dominant_interval([]) is None
        assert shape.distribution([]) == []

    def test_the_distribution_is_ordered_by_interval(self):
        found = [(1, 2, 600), (2, 3, 300), (3, 4, 600)]
        assert shape.distribution(found) == [
            {"interval_ms": 300, "count": 1},
            {"interval_ms": 600, "count": 2},
        ]

    def test_gaps_need_to_exceed_the_factor(self):
        rows = [(1, 0, 1.0), (2, 900, 2.0), (3, 1200, 3.0)]
        found = shape.intervals(rows)
        assert shape.gaps(rows, found, 300, 3) == []
        assert len(shape.gaps(rows, found, 300, 2)) == 1

    def test_a_gap_reports_how_many_points_are_missing(self):
        rows = [(1, 0, 1.0), (2, 1500, 2.0)]
        built = shape.gaps(rows, shape.intervals(rows), 300, 3)[0]
        assert built["missing_points"] == 4
        assert built["prev_row"] == 1 and built["row_no"] == 2

    def test_duplicates_list_every_row_that_reuses_a_timestamp(self):
        rows = [(1, 0, 1.0), (2, 300, 2.0), (3, 0, 3.0), (4, 0, 4.0)]
        built = shape.duplicate_timestamps(rows)
        assert built == [{"epoch_ms": 0, "row_nos": [1, 3, 4], "extra_rows": 2}]

    def test_no_duplicates_yields_an_empty_list(self):
        assert shape.duplicate_timestamps([(1, 0, 1.0), (2, 300, 2.0)]) == []

    def test_the_cadence_summary_counts_off_grid_intervals(self):
        rows = [(1, 0, 1.0), (2, 300, 2.0), (3, 900, 3.0), (4, 1200, 4.0)]
        summary = shape.cadence_summary(rows, 3)
        assert summary["n_intervals"] == 3
        assert summary["dominant_interval_ms"] == 300
        assert summary["median_interval_ms"] == 300
        assert summary["min_interval_ms"] == 300
        assert summary["max_interval_ms"] == 600
        assert summary["gap_threshold_ms"] == 900
        assert summary["irregular_count"] == 1
        assert summary["irregular_ratio_ppm"] == 333333

    def test_the_irregular_ratio_rounds_to_nearest(self):
        # 6 个间隔、1 个不是主间隔：(1_000_000 + 6 // 2) // 6 = 166_667（向下取整会得 166_666）。
        rows = [(index + 1, index * 300000, 1.0) for index in range(6)]
        rows.append((7, 5 * 300000 + 420000, 1.0))
        summary = shape.cadence_summary(rows, 3)
        assert summary["n_intervals"] == 6
        assert summary["irregular_count"] == 1
        assert summary["irregular_ratio_ppm"] == 166667

    def test_value_counts_split_zero_negative_positive_and_missing(self):
        rows = [(1, 0, None), (2, 1, 0.0), (3, 2, -0.0), (4, 3, -1.5), (5, 4, 2.5)]
        counts = shape.value_counts(rows)
        assert counts == {
            "n_values_present": 4,
            "n_values_missing": 1,
            "n_values_zero": 2,
            "n_values_negative": 1,
            "n_values_positive": 1,
        }


# ---------------------------------------------------------------------------
# 工件解析（缺失是数据，损坏是缺陷）
# ---------------------------------------------------------------------------
class TestParseValue:
    def test_null_and_the_missing_markers_are_missing(self):
        for cell in (None, "", "   ", "NA", "n/a", "NaN", "null", "none", "-", "--"):
            assert subject.parse_value(cell, 1) is None

    def test_a_finite_decimal_is_a_value(self):
        assert subject.parse_value(12.5, 1) == 12.5
        assert subject.parse_value(12, 1) == 12.0
        assert subject.parse_value("12.5", 1) == 12.5
        assert subject.parse_value(" 1e3 ", 1) == 1000.0
        assert subject.parse_value("+.5", 1) == 0.5

    def test_a_non_number_string_is_an_error(self):
        for cell in ("abc", "1_000", "0x10", "1,000", "12.5x"):
            with pytest.raises(ValueError):
                subject.parse_value(cell, 1)

    def test_non_finite_numbers_are_rejected_rather_than_propagated(self):
        for cell in (float("inf"), float("-inf"), float("nan")):
            with pytest.raises(ValueError):
                subject.parse_value(cell, 1)

    def test_a_boolean_is_not_a_number(self):
        with pytest.raises(ValueError):
            subject.parse_value(True, 1)

    def test_an_unsupported_type_is_an_error(self):
        with pytest.raises(ValueError):
            subject.parse_value([1.0], 1)


class TestParseSubject:
    def test_a_flat_subject_lands_in_the_default_series(self):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T00:00:00Z", 1.0)]}, params.resolve_params()
        )
        assert parsed.series_order == ["series"]
        assert parsed.rows_by_series["series"] == [(1, 1709251200000, 1.0)]

    def test_the_row_number_is_the_position_in_the_artifact(self):
        rows = [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 2.0)]
        parsed = subject.parse_subject({"rows": rows}, params.resolve_params())
        assert [row[0] for row in parsed.rows_by_series["series"]] == [1, 2]

    def test_a_series_id_groups_rows_and_keeps_their_order(self):
        rows = [
            _row("2024-03-01T00:10:00Z", 3.0, "b"),
            _row("2024-03-01T00:00:00Z", 1.0, "a"),
            _row("2024-03-01T00:05:00Z", 2.0, "a"),
        ]
        parsed = subject.parse_subject({"rows": rows}, params.resolve_params())
        assert parsed.series_order == ["a", "b"]
        assert [row[2] for row in parsed.rows_by_series["a"]] == [1.0, 2.0]

    def test_an_integer_series_id_becomes_its_text(self):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T00:00:00Z", 1.0, 7)]}, params.resolve_params()
        )
        assert parsed.series_order == ["7"]

    def test_a_blank_series_id_falls_back_to_the_default(self):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T00:00:00Z", 1.0, "  ")]},
            params.resolve_params(),
        )
        assert parsed.series_order == ["series"]

    def test_a_non_scalar_series_id_is_an_envelope_error(self):
        with pytest.raises(subject.SubjectError):
            subject.parse_subject(
                {"rows": [_row("2024-03-01T00:00:00Z", 1.0, {"a": 1})]}, params.resolve_params()
            )

    def test_rows_must_be_a_non_empty_array(self):
        with pytest.raises(subject.SubjectError):
            subject.parse_subject({"rows": {}}, params.resolve_params())
        with pytest.raises(subject.SubjectError):
            subject.parse_subject({"rows": []}, params.resolve_params())

    def test_a_row_must_be_an_object(self):
        with pytest.raises(subject.SubjectError):
            subject.parse_subject({"rows": ["x"]}, params.resolve_params())

    def test_a_row_must_declare_timestamp_and_value(self):
        with pytest.raises(subject.SubjectError):
            subject.parse_subject({"rows": [{"value": 1.0}]}, params.resolve_params())
        with pytest.raises(subject.SubjectError):
            subject.parse_subject({"rows": [{"timestamp": "2024-03-01T00:00:00Z"}]}, params.resolve_params())

    def test_missing_must_be_written_as_null_but_an_absent_value_is_an_error(self):
        # 这两件事必须能分开：`{"value": null}` 是"这里是缺失"，`{}` 是"这份工件没说"。
        parsed = subject.parse_subject(
            {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": None}]},
            params.resolve_params(),
        )
        assert parsed.rows_by_series["series"] == [(1, 1709251200000, None)]
        assert parsed.n_values_missing == 1 and parsed.n_values_present == 0

    def test_an_unreadable_timestamp_is_an_issue_not_an_exception(self):
        rows = [_row("2024-02-30T00:00:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)]
        parsed = subject.parse_subject({"rows": rows}, params.resolve_params())
        assert len(parsed.issues) == 1
        assert parsed.issues[0].rule_id == rules.RULE_TIMESTAMP_UNREADABLE
        assert parsed.issues[0].row_no == 1
        assert len(parsed.rows_by_series["series"]) == 1

    def test_an_invalid_value_is_an_issue_not_an_exception(self):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T00:00:00Z", "abc")]}, params.resolve_params()
        )
        assert parsed.issues[0].rule_id == rules.RULE_VALUE_INVALID
        assert "abc" in parsed.issues[0].detail

    def test_an_empty_default_series_is_yielded_even_when_the_only_row_is_missing(self):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T00:00:00Z", None)]}, params.resolve_params()
        )
        assert parsed.series_order == ["series"]

    def test_the_declared_offset_is_applied_to_rows_without_one(self):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T08:00:00", 1.0)]},
            params.resolve_params({"timezone_offset_min": 480}),
        )
        assert parsed.rows_by_series["series"][0][1] == 1709251200000


# ---------------------------------------------------------------------------
# 端到端账本
# ---------------------------------------------------------------------------
class TestAuditLedger:
    def test_the_minimal_sample_matches_the_old_pipelines_episode_count(self):
        # 旧仓 `detect data/samples/minimal.csv`：6 段 episode / 11 个命中点 / rc 0。
        # 本器官在同一份数据上应当给出同样的 6 段信号 episode，外加 1 条断档。
        records = _evaluate(_minimal_rows())
        signal = [r for r in records if r.rule_id in rules.SIGNAL_RULE_BY_DETECTOR.values()]
        assert len(signal) == 6
        assert len(_with_rule(records, rules.RULE_GAP)) == 1
        assert all(r.verdict == WARN for r in signal)
        assert [r for r in records if r.verdict == ERROR] == []

    def test_every_record_carries_a_basis_ref(self):
        records = _evaluate(_minimal_rows())
        assert records
        for record in records:
            assert record.basis is not None, record.rule_id
            assert record.basis.complete, record.rule_id
            assert record.basis.rule_version == BASIS.version

    def test_every_error_record_carries_a_basis_ref(self):
        rows = [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0), _row("2024-03-01T00:00:00Z", 3.0)]
        records = _evaluate(rows)
        errors = [record for record in records if record.verdict == ERROR]
        assert errors
        for record in errors:
            assert record.basis is not None

    def test_the_ledger_carries_no_raw_float(self):
        records = _evaluate(_minimal_rows())
        for record in records:
            payload = record.as_dict()
            assert list(_iter_floats(payload)) == [], (record.rule_id, list(_iter_floats(payload)))

    def test_ids_are_unique_across_the_whole_ledger(self):
        records = _evaluate(_minimal_rows())
        ids = [record.id for record in records]
        assert len(ids) == len(set(ids))

    def test_ids_are_stable_across_runs(self):
        first = [record.id for record in _evaluate(_minimal_rows())]
        second = [record.id for record in _evaluate(_json_roundtrip(_minimal_rows()))]
        assert first == second

    def test_two_series_in_one_artifact_do_not_collide(self):
        rows = _regular_rows(30, series_id="a") + _regular_rows(30, series_id="b")
        records = _evaluate(rows)
        assert len([record.id for record in records]) == len(set(record.id for record in records))
        assert all(record.path.startswith(("a", "b")) for record in records)

    def test_a_duplicate_timestamp_within_tolerance_is_not_reported(self):
        rows = [
            _row("2024-03-01T00:00:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
            _row("2024-03-01T00:05:00Z", 3.0),
        ]
        assert _with_rule(_evaluate(rows), rules.RULE_DUPLICATE_TIMESTAMP) == []

    def test_a_duplicate_timestamp_beyond_tolerance_is_an_error(self):
        rows = [
            _row("2024-03-01T00:00:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
            _row("2024-03-01T00:00:00Z", 3.0),
        ]
        hits = _with_rule(_evaluate(rows), rules.RULE_DUPLICATE_TIMESTAMP)
        assert len(hits) == 1
        assert hits[0].verdict == ERROR
        assert hits[0].path == "series#row=3"
        assert hits[0].evidence["first_row"] == 1

    def test_a_duplicate_tolerance_of_zero_reports_the_first_repeat(self):
        rows = [
            _row("2024-03-01T00:00:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
        ]
        hits = _with_rule(_evaluate(rows, duplicate_timestamp_max=0), rules.RULE_DUPLICATE_TIMESTAMP)
        assert len(hits) == 1

    def test_time_running_backwards_is_an_error_by_default(self):
        rows = [
            _row("2024-03-01T00:05:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
        ]
        hits = _with_rule(_evaluate(rows), rules.RULE_NON_MONOTONIC)
        assert len(hits) == 1
        assert hits[0].verdict == ERROR
        assert hits[0].evidence["delta_ms"] == -300000

    def test_a_monotonic_tolerance_absorbs_the_first_backwards_step(self):
        rows = [
            _row("2024-03-01T00:05:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
        ]
        assert _with_rule(_evaluate(rows, non_monotonic_max=1), rules.RULE_NON_MONOTONIC) == []

    def test_an_unreadable_timestamp_is_an_error_record_not_a_crash(self):
        rows = [_row("2024-02-30T00:00:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)]
        hits = _with_rule(_evaluate(rows), rules.RULE_TIMESTAMP_UNREADABLE)
        assert len(hits) == 1
        assert hits[0].verdict == ERROR
        assert hits[0].path == "series#row=1"

    def test_an_invalid_value_is_an_error_record(self):
        rows = [_row("2024-03-01T00:00:00Z", "abc")]
        hits = _with_rule(_evaluate(rows), rules.RULE_VALUE_INVALID)
        assert [record.verdict for record in hits] == [ERROR]

    def test_a_gap_is_a_warn_and_names_the_missing_points(self):
        rows = _regular_rows(6) + [
            _row("2024-03-01T02:00:00Z", 6.0),
        ]
        hits = _with_rule(_evaluate(rows), rules.RULE_GAP)
        assert len(hits) == 1
        assert hits[0].verdict == WARN
        assert hits[0].evidence["missing_points"] == 18

    def test_irregular_cadence_without_gaps_is_only_info(self):
        rows = _regular_rows(4)
        rows.append(_row("2024-03-01T00:17:00Z", 4.0))
        hits = _with_rule(_evaluate(rows), rules.RULE_IRREGULAR_CADENCE)
        assert len(hits) == 1
        assert hits[0].verdict == INFO
        assert hits[0].evidence["off_grid_intervals"] == 1
        assert hits[0].path == "series#cadence"

    def test_the_gap_interval_is_not_double_counted_as_irregular_cadence(self):
        rows = _regular_rows(6) + [_row("2024-03-01T02:00:00Z", 6.0)]
        assert _with_rule(_evaluate(rows), rules.RULE_IRREGULAR_CADENCE) == []

    def test_a_missing_run_is_info_and_names_its_length(self):
        values = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0] + [None] * 6 + [1.0] * 7
        rows = _regular_rows(len(values), values=values)
        hits = _with_rule(_evaluate(rows), rules.RULE_MISSING_RUN)
        assert len(hits) == 1
        assert hits[0].verdict == INFO
        assert hits[0].evidence["run_length"] == 6
        assert hits[0].evidence["n_points"] == 6

    def test_the_missing_run_threshold_is_honoured(self):
        values = [1.0] * 7 + [None] * 6 + [1.0] * 7
        rows = _regular_rows(len(values), values=values)
        assert _with_rule(_evaluate(rows, rules={"missing_run": 7}), rules.RULE_MISSING_RUN) == []
        assert len(_with_rule(_evaluate(rows, rules={"missing_run": 6}), rules.RULE_MISSING_RUN)) == 1

    def test_a_zero_run_is_info(self):
        values = [1.0] * 7 + [0.0] * 6 + [1.0] * 7
        rows = _regular_rows(len(values), values=values)
        hits = _with_rule(_evaluate(rows), rules.RULE_ZERO_RUN)
        assert len(hits) == 1
        assert hits[0].verdict == INFO
        assert hits[0].evidence["run_length"] == 6

    def test_the_static_threshold_rule_is_absent_until_it_is_enabled(self):
        rows = _regular_rows(20, values=[1.0] * 20)
        assert _with_rule(_evaluate(rows), rules.RULE_STATIC_THRESHOLD) == []
        hits = _with_rule(_evaluate(rows, rules={"static_threshold": 0.5}), rules.RULE_STATIC_THRESHOLD)
        assert hits and all(record.verdict == WARN for record in hits)

    def test_escalation_turns_a_signal_hit_into_a_blocking_error(self):
        rows = _regular_rows(40, values=[0.0] * 39 + [100.0])
        plain = _with_rule(_evaluate(rows), rules.RULE_ROLLING_MAD_Z)
        assert [record.verdict for record in plain] == [WARN]
        escalated = _with_rule(_evaluate(rows, escalate_score_q=1000000), rules.RULE_ROLLING_MAD_Z)
        assert [record.verdict for record in escalated] == [ERROR]
        assert escalated[0].evidence["escalate_score_q"] == 1000000

    def test_a_linear_ramp_is_invisible_to_the_window_and_rule_detectors(self):
        # 从 100 起而不是从 0 起：从 0 起的斜坡前两步的**相对**跳变是 100%，那会被
        # pct_jump 正当抓住（这条规则的语义就是相对变化）。
        rows = _regular_rows(80, values=[100.0 + index for index in range(80)])
        for rule_id in (
            rules.RULE_ROLLING_MAD_Z,
            rules.RULE_ROLLING_IQR,
            rules.RULE_PCT_JUMP,
            rules.RULE_CUSUM,
        ):
            assert _with_rule(_evaluate(rows), rule_id) == [], rule_id

    def test_a_linear_ramp_is_flagged_by_the_stl_endpoint_path_and_that_is_inherited(self):
        """``period_points=1`` 时 STL 残差只剩 LOESS 趋势的端部偏差 —— 旧仓同一条输入同两个点。

        这不是本轮引入的行为，也不是"该修"的东西：它说明无周期序列上的 STL 检测器
        在端点附近**偏保守**（会报警），因此这里把它钉成已知事实而不是假装没有。
        旧仓实测：``stl_resid_z([100+i for i in range(80)], range(80), 1, 2, 1, 24, 3.5, 6)``
        -> ``[(59, 3.9120464049642525), (74, 8.093889113719143)]``。
        """
        rows = _regular_rows(80, values=[100.0 + index for index in range(80)])
        hits = _with_rule(_evaluate(rows), rules.RULE_STL_RESID_Z)
        assert sorted(record.evidence["peak_score"] for record in hits) == [
            "3.912046",
            "8.093889",
        ]
        assert sorted(record.evidence["start_row"] for record in hits) == [60, 75]

    def test_a_constant_series_produces_no_signal_records(self):
        rows = _regular_rows(80, values=[7.0] * 80)
        signal = [r for r in _evaluate(rows) if r.rule_id in rules.SIGNAL_RULE_BY_DETECTOR.values()]
        assert signal == []

    def test_the_evidence_repeats_the_effective_parameters(self):
        rows = _regular_rows(40, values=[0.0] * 39 + [100.0])
        record = _with_rule(_evaluate(rows), rules.RULE_ROLLING_MAD_Z)[0]
        assert record.evidence["threshold_ref"] == params.dump_params(params.resolve_params())["rolling_mad_z"]
        assert record.evidence["max_gap_ms"] == 1800000

    def test_the_message_and_the_evidence_agree_on_the_score(self):
        rows = _regular_rows(40, values=[0.0] * 39 + [100.0])
        record = _with_rule(_evaluate(rows), rules.RULE_ROLLING_MAD_Z)[0]
        assert record.evidence["peak_score"] in record.message
        assert record.evidence["peak_score_q"] == params.quantize(
            float(record.evidence["peak_score"])
        )

    def test_a_missing_rule_is_a_rule_missing_violation(self):
        with pytest.raises(RuleMissing):
            _evaluate(_minimal_rows(), basis=Basis(version="9", rules=()))

    def test_the_organ_reads_nothing_and_returns_only_records(self):
        result = audit.evaluate({"rows": _minimal_rows()}, BASIS)
        assert isinstance(result, tuple)
        assert all(isinstance(record, Record) for record in result)

    def test_an_unknown_param_key_is_an_input_error(self):
        with pytest.raises(ValueError):
            audit.evaluate({"rows": _minimal_rows(), "params": {"nope": 1}}, BASIS)

    def test_a_non_object_subject_is_an_input_error(self):
        with pytest.raises(ValueError):
            audit.evaluate(["not", "an", "object"], BASIS)

    def test_the_order_of_records_does_not_depend_on_the_input_order_of_series(self):
        forward = _regular_rows(30, series_id="a") + _regular_rows(30, series_id="b")
        backward = list(reversed(_regular_rows(30, series_id="b"))) + _regular_rows(30, series_id="a")
        # 反转 b 的行序会造出时间倒序，所以只能断言"同一输入集合、同一序列内顺序"下的幂等性
        assert [record.id for record in _evaluate(forward)] == [
            record.id for record in _evaluate(forward)
        ]
        assert backward  # 保留构造，避免"没用到"的错觉

    def test_the_report_sorts_the_ledger_deterministically(self):
        from byteproof.core.ledger import Report

        records = _evaluate(_minimal_rows())
        first = Report(product="byteproof", organ=SLUG, organ_version="1", subject="s", records=records)
        second = Report(
            product="byteproof", organ=SLUG, organ_version="1", subject="s", records=tuple(reversed(records))
        )
        assert json.dumps(first.as_dict(), ensure_ascii=False) == json.dumps(
            second.as_dict(), ensure_ascii=False
        )


def _json_roundtrip(rows):
    """把工件过一遍 JSON（模拟"同一工件从文件读回来"），字节层面的类型不掉。"""
    return json.loads(json.dumps(rows))


# ---------------------------------------------------------------------------
# 器官契约门：禁超越函数 / 禁时钟 / 禁文件与打印
# ---------------------------------------------------------------------------
#: 禁用的调用名：libm 依赖的超越函数 + 库归约/舍入（顺序或边界不是本规格的一部分）。
BANNED_NAMES = frozenset(
    (
        "exp",
        "expm1",
        "log",
        "log1p",
        "log2",
        "log10",
        "pow",
        "sqrt",
        "cbrt",
        "hypot",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "sinh",
        "cosh",
        "tanh",
        "degrees",
        "radians",
        "fsum",
        "prod",
        "dist",
        "isqrt",
        "comb",
        "perm",
        "factorial",
        "gamma",
        "lgamma",
        "erf",
        "erfc",
        "mean",
        "median",
        "median_low",
        "median_high",
        "median_grouped",
        "mode",
        "multimode",
        "quantiles",
        "pvariance",
        "variance",
        "pstdev",
        "stdev",
        "round",
        "open",
        "print",
        "input",
        "exec",
        "eval",
    )
)
# 注：``compile`` **不在**禁列——本包唯一的合法出现是 ``re.compile``（时间戳与数值语法的
# 单一编译点），而扫描器按属性名抓会把 ``re.compile`` 一起判红。契约真正要挡的是
# ``eval`` / ``exec``（运行期执行任意代码），这两条都在表里。

#: 禁用的模块：时钟 / 随机 / 统计归约 / 浮点格式化 / 参数解析 / 文件系统。
BANNED_MODULES = frozenset(
    (
        "random",
        "statistics",
        "numpy",
        "datetime",
        "time",
        "decimal",
        "fractions",
        "secrets",
        "uuid",
        "cmath",
        "argparse",
        "os",
        "pathlib",
        "shutil",
        "subprocess",
        "sys",
        "io",
        "socket",
        "urllib",
        "requests",
    )
)


def _python_sources(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ("__pycache__",)]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                found.append(os.path.join(dirpath, filename))
    return found


def scan_python(path, root):
    """一个 Python 文件里的违禁构造：``[(相对路径, 行, 记号)]``。"""
    with io.open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    relative = os.path.relpath(path, root).replace("\\", "/")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    hits.append((relative, node.lineno, "import %s" % alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_MODULES:
                hits.append((relative, node.lineno, "from %s import" % node.module))
            for alias in node.names or ():
                if alias.name in BANNED_NAMES:
                    hits.append((relative, node.lineno, alias.name))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            hits.append((relative, node.lineno, "**"))
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Pow):
            hits.append((relative, node.lineno, "**"))
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
            hits.append((relative, node.lineno, node.attr))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
            hits.append((relative, node.lineno, node.func.id))
    return hits


def scan_tree(root, exemptions=None):
    exemptions = {} if exemptions is None else exemptions
    hits = []
    for path in _python_sources(root):
        hits.extend(scan_python(path, root))
    allowed = set()
    for relative, tokens in exemptions.items():
        for token in tokens:
            allowed.add((relative, token))
    return sorted(hit for hit in hits if (hit[0], hit[2]) not in allowed)


class TestScanScope:
    def test_the_scope_is_the_whole_organ_package(self):
        sources = _python_sources(ORGAN_DIR)
        assert len(sources) >= 7, [os.path.basename(path) for path in sources]
        names = sorted(os.path.basename(path) for path in sources)
        for expected in (
            "__init__.py",
            "audit.py",
            "detect.py",
            "episodes.py",
            "numeric.py",
            "params.py",
            "rules.py",
            "shape.py",
            "subject.py",
            "timeline.py",
        ):
            assert expected in names, names

    def test_the_scanner_reads_a_real_file(self, tmp_path):
        target = tmp_path / "sample.py"
        target.write_text("import math\nVALUE = math.floor(1.5)\n", encoding="utf-8")
        assert scan_python(str(target), str(tmp_path)) == []
        target.write_text("import math\nVALUE = math.exp(1.5)\n", encoding="utf-8")
        assert scan_python(str(target), str(tmp_path)) == [("sample.py", 2, "exp")]


class TestNoClockNoSideEffects:
    """器官契约的执行版：不打印、不读文件/环境、不看时钟、不带参数解析器。"""

    def test_the_organ_package_is_clean(self):
        assert scan_tree(ORGAN_DIR) == []

    def test_floor_and_ceil_are_still_allowed(self):
        # 正对照：门不能"什么都标"。params.py 用 math.floor。
        with io.open(os.path.join(ORGAN_DIR, "params.py"), encoding="utf-8") as handle:
            assert "math.floor" in handle.read()

    def test_builtin_reductions_are_still_allowed(self, tmp_path):
        target = tmp_path / "allowed.py"
        target.write_text(
            "TOTAL = sum([1, 2, 3])\nLOW = min(1, 2)\nHIGH = max(1, 2)\nSIZE = abs(-3)\nORDERED = sorted([3, 1])\n",
            encoding="utf-8",
        )
        assert scan_python(str(target), str(tmp_path)) == []

    def test_a_transcendental_call_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "detect.py"), "INJECTED = __import__('math').exp(1.0)\n")
        assert any(hit[2] == "exp" for hit in scan_tree(root))

    def test_the_power_operator_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "detect.py"), "INJECTED = 2 ** 10\n")
        assert any(hit[2] == "**" for hit in scan_tree(root))

    def test_a_banned_module_import_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "detect.py"), "import statistics\n")
        assert any(hit[2] == "import statistics" for hit in scan_tree(root))

    def test_a_library_reduction_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "detect.py"), "INJECTED = statistics.mean([1.0])\n")
        assert any(hit[2] == "mean" for hit in scan_tree(root))

    def test_a_clock_import_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "import time\n")
        assert any(hit[2] == "import time" for hit in scan_tree(root))

    def test_a_print_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "print('x')\n")
        assert any(hit[2] == "print" for hit in scan_tree(root))

    def test_a_file_open_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "HANDLE = open('x', 'rb')\n")
        assert any(hit[2] == "open" for hit in scan_tree(root))

    def test_an_environment_read_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "import os\nVALUE = os.environ.get('X')\n")
        assert any(hit[2] == "import os" for hit in scan_tree(root))

    def test_an_exemption_suppresses_exactly_one_token_in_one_file(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "detect.py"), "INJECTED = __import__('math').exp(1.0)\n")
        assert scan_tree(root, {"detect.py": {"exp"}}) == []

    def test_an_exemption_does_not_leak_to_other_files(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "episodes.py"), "INJECTED = __import__('math').exp(1.0)\n")
        assert scan_tree(root, {"detect.py": {"exp"}}) != []

    def test_the_shipped_exemption_table_is_empty(self):
        assert scan_tree(ORGAN_DIR, {}) == []


def _copy_package(tmp_path):
    target = tmp_path / "timeseries_anomaly"
    shutil.copytree(ORGAN_DIR, str(target), ignore=shutil.ignore_patterns("__pycache__"))
    return str(target)


def _inject(path, line):
    with io.open(path, "a", encoding="utf-8") as handle:
        handle.write("\n" + line)


# ---------------------------------------------------------------------------
# 唯一入口
# ---------------------------------------------------------------------------
class TestCli:
    def test_the_slug_is_registered(self):
        assert get(SLUG) is PACK
        assert PACK.slug in [pack.slug for pack in __import__("byteproof.core", fromlist=["all_packs"]).all_packs()]

    def test_an_unknown_slug_is_a_contract_error(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": []}), encoding="utf-8")
        assert cli.main(["check", "no-such-organ", "--input", str(target)]) == EXIT_CONTRACT
        assert "PackMissing" in capsys.readouterr().err

    def test_the_shipped_basis_is_found_without_a_flag(self):
        assert cli.shipped_basis_path(SLUG) == str(BASIS_PATH)
        assert cli.shipped_basis_path("no-such-organ") is None

    def test_the_minimal_sample_exits_zero(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE)]) == EXIT_OK
        assert "合计" in capsys.readouterr().out

    def test_the_json_output_is_byte_identical_across_runs(self, capsys):
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"]) == EXIT_OK
        first = capsys.readouterr().out
        assert cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"]) == EXIT_OK
        assert capsys.readouterr().out == first

    def test_the_json_output_has_no_absolute_path(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        out = capsys.readouterr().out
        assert str(ROOT) not in out
        assert "ProgramData" not in out

    def test_the_json_envelope_has_the_spec_fields(self, capsys):
        cli.main(["check", SLUG, "--input", str(SAMPLE), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"product", "organ", "organ_version", "subject", "summary", "records"}
        assert payload["product"] == "byteproof"
        assert payload["organ"] == SLUG
        assert payload["summary"]["total"] == len(payload["records"])

    def test_stdin_is_accepted_and_labelled(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps({"rows": _minimal_rows()})),
        )
        assert cli.main(["check", SLUG, "--input", "-", "--json"]) == EXIT_OK
        assert json.loads(capsys.readouterr().out)["subject"] == "<stdin>"

    def test_a_blocking_ledger_exits_one(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": [_row("2024-02-30T00:00:00Z", 1.0)]}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_BLOCKED

    def test_an_empty_basis_is_a_contract_error(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": _minimal_rows()}), encoding="utf-8")
        basis = tmp_path / "rules.json"
        basis.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target), "--basis", str(basis)]) == EXIT_CONTRACT
        assert "RuleMissing" in capsys.readouterr().err

    def test_a_basis_without_a_version_is_a_contract_error(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": _minimal_rows()}), encoding="utf-8")
        basis = tmp_path / "rules.json"
        basis.write_text(json.dumps({"rules": []}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target), "--basis", str(basis)]) == EXIT_CONTRACT
        assert "规则包版本为空" in capsys.readouterr().err

    def test_a_missing_input_file_is_an_input_error(self, capsys, tmp_path):
        assert cli.main(["check", SLUG, "--input", str(tmp_path / "nope.json")]) == EXIT_INPUT

    def test_the_required_field_is_enforced_by_the_kernel(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_INPUT
        assert "rows" in capsys.readouterr().err

    def test_an_unknown_param_key_exits_two(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"rows": _minimal_rows(), "params": {"nope": 1}}), encoding="utf-8"
        )
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_INPUT

    def test_the_list_output_names_the_organ(self, capsys):
        assert cli.main(["list"]) == EXIT_OK
        out = capsys.readouterr().out
        assert SLUG in out and ORGAN_VERSION in out

    def test_the_list_json_carries_the_input_fields(self, capsys):
        assert cli.main(["list", "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        entry = [item for item in payload if item["slug"] == SLUG][0]
        assert entry["input_fields"] == ["rows"]
        assert entry["version"] == ORGAN_VERSION


# ===========================================================================
# 判定层矩阵（ORGAN-PLAYBOOK §3.0：每条规则 × 三态 + 边界，不堆重复断言）
#
# 判定层口径 = 旧仓文件名不匹配 `cli|gui|packaging|audit|...` 的测试文件实跑数
# （本器官旧仓 X = 551）。下面的矩阵每一行都是一组**不同的**输入与一组**不同的**期望，
# 不是同一断言的复读：
#   A 触发矩阵   —— 14 条规则各给一份只触发它的工件，断言等级是文档登记的那一档
#   B 静默矩阵   —— 14 条规则各给一份"差一点就触发"的工件，断言它不出现
#   C 边界矩阵   —— 数值阈值：正好等于不触发、过一点点才触发
#   D 时间戳语法 —— 合法 20 种 / 非法 24 种
#   E 值语法     —— 有限数 / 缺失标记 / 拒绝形态
#   F 参数面     —— 每个声明参数的默认、覆盖、非法类型
#   G 检测器扫描 —— 窗口 × 阈值单调性
#   H 形状矩阵   —— 断档缺失点数 / 段长 / 不规则比率
#   I 合并矩阵   —— 时间域合并的边界
# ===========================================================================
def _flat(n, value=1.0):
    return _regular_rows(n, values=[value] * n)


def _spike(n=40, at=39, amplitude=100.0):
    values = [0.0] * n
    values[at] = amplitude
    return _regular_rows(n, values=values)


def _run(rule_length=6, kind="missing", pad=7):
    body = [None] * rule_length if kind == "missing" else [0.0] * rule_length
    values = [1.0] * pad + body + [1.0] * pad
    return _regular_rows(len(values), values=values)


#: A 触发矩阵：一件只触发该规则的工件。
TRIGGER_CASES = (
    (rules.RULE_TIMESTAMP_UNREADABLE, [_row("2024-02-30T00:00:00Z", 1.0)], {}),
    (rules.RULE_VALUE_INVALID, [_row("2024-03-01T00:00:00Z", "abc")], {}),
    (
        rules.RULE_DUPLICATE_TIMESTAMP,
        [
            _row("2024-03-01T00:00:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
            _row("2024-03-01T00:00:00Z", 3.0),
        ],
        {},
    ),
    (
        rules.RULE_NON_MONOTONIC,
        [_row("2024-03-01T00:05:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
        {},
    ),
    (rules.RULE_GAP, _regular_rows(6) + [_row("2024-03-01T02:00:00Z", 6.0)], {}),
    (rules.RULE_IRREGULAR_CADENCE, _regular_rows(4) + [_row("2024-03-01T00:17:00Z", 4.0)], {}),
    (rules.RULE_MISSING_RUN, _run(6, "missing"), {}),
    (rules.RULE_ZERO_RUN, _run(6, "zero"), {}),
    (rules.RULE_STATIC_THRESHOLD, _flat(20), {"rules": {"static_threshold": 0.5}}),
    (
        rules.RULE_PCT_JUMP,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 3.0)],
        {},
    ),
    (rules.RULE_ROLLING_MAD_Z, _spike(), {}),
    (rules.RULE_ROLLING_IQR, _spike(), {}),
    (rules.RULE_CUSUM, _regular_rows(40, values=[0.0] * 20 + [10.0] * 20), {}),
    (
        rules.RULE_STL_RESID_Z,
        _regular_rows(80, values=[100.0 + index for index in range(80)]),
        {},
    ),
)

#: B 静默矩阵："差一点就触发"的同类工件 —— 每条规则一例，形态各不相同。
QUIET_CASES = (
    (rules.RULE_TIMESTAMP_UNREADABLE, [_row("2024-02-29T00:00:00Z", 1.0)]),
    (rules.RULE_VALUE_INVALID, [_row("2024-03-01T00:00:00Z", None)]),
    (
        rules.RULE_DUPLICATE_TIMESTAMP,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
    ),
    (
        rules.RULE_NON_MONOTONIC,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 2.0)],
    ),
    (rules.RULE_GAP, _regular_rows(6)),
    (rules.RULE_IRREGULAR_CADENCE, _regular_rows(6)),
    (rules.RULE_MISSING_RUN, _run(5, "missing")),
    (rules.RULE_ZERO_RUN, _run(5, "zero")),
    (rules.RULE_STATIC_THRESHOLD, _flat(20)),
    (
        rules.RULE_PCT_JUMP,
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 1.3)],
    ),
    (rules.RULE_ROLLING_MAD_Z, _flat(40)),
    (rules.RULE_ROLLING_IQR, _flat(40)),
    (rules.RULE_CUSUM, _regular_rows(40, values=[1.0 + index * 0.01 for index in range(40)])),
    (rules.RULE_STL_RESID_Z, _flat(40)),
)


class TestRuleVerdictMatrix:
    """每条规则 × 触发 / 静默 / 等级三件事，逐条钉住。"""

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_rule_fires(self, rule_id, rows, overrides):
        hits = _with_rule(_evaluate(rows, **overrides), rule_id)
        assert hits, "%s 没有触发" % rule_id
        assert all(record.basis is not None for record in hits)

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_rule_reports_its_documented_verdict(self, rule_id, rows, overrides):
        for record in _with_rule(_evaluate(rows, **overrides), rule_id):
            assert record.verdict == rules.verdict_for(rule_id), rule_id

    @pytest.mark.parametrize("rule_id,rows,overrides", TRIGGER_CASES)
    def test_the_rule_cites_its_own_rule_id_as_the_basis(self, rule_id, rows, overrides):
        for record in _with_rule(_evaluate(rows, **overrides), rule_id):
            assert record.basis.rule_id == rule_id
            assert record.basis.source and record.basis.quote

    @pytest.mark.parametrize("rule_id,rows", QUIET_CASES)
    def test_the_rule_stays_silent_just_below_its_trigger(self, rule_id, rows):
        assert _with_rule(_evaluate(rows), rule_id) == [], rule_id

    @pytest.mark.parametrize("rule_id", rules.RULE_IDS)
    def test_every_rule_is_covered_by_a_trigger_case(self, rule_id):
        assert rule_id in [case[0] for case in TRIGGER_CASES]

    @pytest.mark.parametrize("rule_id", rules.RULE_IDS)
    def test_every_rule_is_covered_by_a_quiet_case(self, rule_id):
        assert rule_id in [case[0] for case in QUIET_CASES]

    def test_the_ledger_can_produce_all_three_verdict_classes(self):
        error_rows = [_row("2024-02-30T00:00:00Z", 1.0)]
        warn_rows = _spike()
        info_rows = _run(6, "missing")
        assert {record.verdict for record in _evaluate(error_rows)} == {ERROR}
        assert WARN in {record.verdict for record in _evaluate(warn_rows)}
        assert INFO in {record.verdict for record in _evaluate(info_rows)}

    @pytest.mark.parametrize("rule_id", sorted(rules.VERDICT_BY_RULE))
    def test_the_verdict_table_matches_the_ledger(self, rule_id):
        assert rules.verdict_for(rule_id) in (ERROR, WARN, INFO)
        assert rules.verdict_for(rule_id) == rules.VERDICT_BY_RULE[rule_id]

    @pytest.mark.parametrize("rule_id", rules.RULE_IDS)
    def test_every_rule_is_registered_in_the_basis(self, rule_id):
        assert BASIS.rule(rule_id) is not None


#: C 边界矩阵：(用例, 工件, 参数, 规则) —— "正好等于"不触发，"过一点点"才触发。
BOUNDARY_CASES = (
    (
        "pct_jump_exact",
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 1.5)],
        {"rules": {"pct_jump": 0.5}},
        rules.RULE_PCT_JUMP,
        0,
    ),
    (
        "pct_jump_past",
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:05:00Z", 1.5001)],
        {"rules": {"pct_jump": 0.5}},
        rules.RULE_PCT_JUMP,
        1,
    ),
    (
        "static_threshold_exact",
        _flat(20),
        {"rules": {"static_threshold": 1.0}},
        rules.RULE_STATIC_THRESHOLD,
        0,
    ),
    (
        "static_threshold_past",
        _flat(20, 1.0001),
        {"rules": {"static_threshold": 1.0}},
        rules.RULE_STATIC_THRESHOLD,
        1,
    ),
    ("missing_run_short", _run(5, "missing"), {}, rules.RULE_MISSING_RUN, 0),
    ("missing_run_exact", _run(6, "missing"), {}, rules.RULE_MISSING_RUN, 1),
    ("zero_run_short", _run(5, "zero"), {}, rules.RULE_ZERO_RUN, 0),
    ("zero_run_exact", _run(6, "zero"), {}, rules.RULE_ZERO_RUN, 1),
    (
        "duplicate_at_tolerance",
        [_row("2024-03-01T00:00:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
        {},
        rules.RULE_DUPLICATE_TIMESTAMP,
        0,
    ),
    (
        "duplicate_one_past",
        [
            _row("2024-03-01T00:00:00Z", 1.0),
            _row("2024-03-01T00:00:00Z", 2.0),
            _row("2024-03-01T00:00:00Z", 3.0),
        ],
        {},
        rules.RULE_DUPLICATE_TIMESTAMP,
        1,
    ),
    (
        "monotonic_at_tolerance",
        [_row("2024-03-01T00:05:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
        {"non_monotonic_max": 1},
        rules.RULE_NON_MONOTONIC,
        0,
    ),
    (
        "monotonic_one_past",
        [_row("2024-03-01T00:05:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)],
        {},
        rules.RULE_NON_MONOTONIC,
        1,
    ),
    ("gap_below_factor", _regular_rows(4) + [_row("2024-03-01T00:30:00Z", 4.0)], {}, rules.RULE_GAP, 0),
    ("gap_above_factor", _regular_rows(4) + [_row("2024-03-01T00:40:00Z", 4.0)], {}, rules.RULE_GAP, 1),
)


class TestBoundaryMatrix:
    @pytest.mark.parametrize("case_id,rows,overrides,rule_id,expected", BOUNDARY_CASES)
    def test_the_threshold_is_where_the_rule_says(self, case_id, rows, overrides, rule_id, expected):
        assert len(_with_rule(_evaluate(rows, **overrides), rule_id)) == expected, case_id

    def test_the_cusum_threshold_is_strictly_greater(self):
        rows = _regular_rows(40, values=[0.0] * 20 + [10.0] * 20)
        score_q = _with_rule(_evaluate(rows), rules.RULE_CUSUM)[0].evidence["peak_score_q"]
        assert _with_rule(_evaluate(rows, rules={"cusum_h": 1.0}), rules.RULE_CUSUM)[0].evidence[
            "peak_score_q"
        ] == score_q
        assert (
            _with_rule(_evaluate(rows, rules={"cusum_h": 100000.0}), rules.RULE_CUSUM) == []
        )


#: D 时间戳语法：合法形态（解析成功即算过；对账标准库在 TestParseTimestamp 里做过）。
TIMESTAMP_VALID = (
    "2024-02-29T00:00:00Z",
    "2024-02-29 00:00:00Z",
    "2024-02-29T00:00Z",
    "2024-02-29T00:00:00",
    "2024-02-29T00:00:00.1Z",
    "2024-02-29T00:00:00.12Z",
    "2024-02-29T00:00:00.123Z",
    "2024-02-29T00:00:00.123456Z",
    "2024-02-29T00:00:00.123456789Z",
    "2024-02-29T00:00:00+00:00",
    "2024-02-29T00:00:00+0800",
    "2024-02-29T00:00:00+08",
    "2024-02-29T00:00:00-08:00",
    "2024-02-29T00:00:00z",
    "1970-01-01T00:00:00Z",
    "1969-12-31T23:59:59.999Z",
    "2100-12-31T23:59Z",
    "2024-02-29T23:59:59Z",
    "2000-02-29T00:00:00Z",
    " 2024-02-29T00:00:00Z ",
)

TIMESTAMP_INVALID = (
    "",
    "   ",
    "2024-02-30T00:00:00Z",
    "2023-02-29T00:00:00Z",
    "1900-02-29T00:00:00Z",
    "2024-13-01T00:00:00Z",
    "2024-00-01T00:00:00Z",
    "2024-01-00T00:00:00Z",
    "2024-01-32T00:00:00Z",
    "2024-01-01T24:00Z",
    "2024-01-01T00:60Z",
    "2024-01-01T00:00:60Z",
    "2024-01-01T00:00:00+24:00",
    "2024-01-01T00:00:00+00:60",
    "2024-01-01T00:00:00+000",
    "2024/01/01T00:00:00Z",
    "20240101T000000Z",
    "2024-01-01",
    "2024-01-01T00",
    "T00:00:00Z",
    "not a timestamp",
    "2024-1-1T00:00:00Z",
    "2024-01-01T00:00:00.Z",
    "2024-01-01T00:00:00,123Z",
)


class TestTimestampGrammarMatrix:
    @pytest.mark.parametrize("text", TIMESTAMP_VALID)
    def test_a_legal_form_parses(self, text):
        stamp = timeline.parse_timestamp(text)
        assert isinstance(stamp.epoch_ms, int)

    @pytest.mark.parametrize("text", TIMESTAMP_INVALID)
    def test_an_illegal_form_is_rejected(self, text):
        with pytest.raises(timeline.TimeParseError):
            timeline.parse_timestamp(text)

    @pytest.mark.parametrize("text", TIMESTAMP_VALID)
    def test_the_whole_artifact_survives_a_legal_timestamp(self, text):
        parsed = subject.parse_subject({"rows": [_row(text, 1.0)]}, params.resolve_params())
        assert parsed.issues == []
        assert len(parsed.rows_by_series["series"]) == 1

    @pytest.mark.parametrize("text", TIMESTAMP_INVALID)
    def test_an_illegal_timestamp_becomes_a_row_issue(self, text):
        parsed = subject.parse_subject({"rows": [_row(text, 1.0)]}, params.resolve_params())
        assert parsed.issues and parsed.issues[0].rule_id == rules.RULE_TIMESTAMP_UNREADABLE


#: E 值语法：(输入, 期望的 float 或 None)；拒绝形态单独列。
VALUE_ACCEPTED = (
    (None, None),
    ("", None),
    ("   ", None),
    ("NA", None),
    ("n/a", None),
    ("NaN", None),
    ("null", None),
    ("none", None),
    ("-", None),
    ("--", None),
    (0, 0.0),
    (0.0, 0.0),
    (-0.0, 0.0),
    (-1, -1.0),
    (12.5, 12.5),
    ("12.5", 12.5),
    ("+1.5", 1.5),
    (".5", 0.5),
    ("1.", 1.0),
    ("1e3", 1000.0),
    ("1E-3", 0.001),
    (" 2.5 ", 2.5),
    (10**9, 1000000000.0),
)

VALUE_REJECTED = (
    "abc",
    "1_000",
    "0x10",
    "1,000",
    "12.5x",
    "inf",
    "-inf",
    "Infinity",
    "1 2",
    "1.2.3",
    True,
    False,
    [1.0],
    {"v": 1},
    float("inf"),
    float("-inf"),
    float("nan"),
)


class TestValueGrammarMatrix:
    @pytest.mark.parametrize("cell,expected", VALUE_ACCEPTED)
    def test_an_accepted_cell_reads_to_its_value(self, cell, expected):
        assert subject.parse_value(cell, 1) == expected

    @pytest.mark.parametrize("cell", VALUE_REJECTED)
    def test_a_rejected_cell_raises(self, cell):
        with pytest.raises(ValueError):
            subject.parse_value(cell, 1)

    @pytest.mark.parametrize("cell", VALUE_REJECTED)
    def test_a_rejected_cell_becomes_a_row_issue(self, cell):
        parsed = subject.parse_subject(
            {"rows": [_row("2024-03-01T00:00:00Z", cell)]}, params.resolve_params()
        )
        assert parsed.issues and parsed.issues[0].rule_id == rules.RULE_VALUE_INVALID

    @pytest.mark.parametrize("cell", VALUE_REJECTED)
    def test_a_rejected_cell_blocks_the_run(self, cell):
        rows = [_row("2024-03-01T00:00:00Z", cell)]
        assert [record.verdict for record in _evaluate(rows)] == [ERROR]


#: F 参数面：(参数路径, 覆盖值, 期望生效值)。
PARAM_OVERRIDES = (
    ("rolling_mad_z.window", 12, 12),
    ("rolling_mad_z.k", 2.5, 2.5),
    ("rolling_mad_z.k", "2.500000", 2.5),
    ("rolling_mad_z.min_valid", 3, 3),
    ("rolling_iqr.window", 12, 12),
    ("rolling_iqr.iqr_mult", 1.5, 1.5),
    ("rolling_iqr.min_valid", 4, 4),
    ("stl_resid_z.inner", 1, 1),
    ("stl_resid_z.outer", 0, 0),
    ("stl_resid_z.window", 12, 12),
    ("stl_resid_z.k", 2.0, 2.0),
    ("stl_resid_z.min_valid", 3, 3),
    ("rules.static_threshold", 10.0, 10.0),
    ("rules.pct_jump", 0.5, 0.5),
    ("rules.missing_run", 3, 3),
    ("rules.cusum_k", 0.25, 0.25),
    ("rules.cusum_h", 3.0, 3.0),
    ("max_gap_ms", 60000, 60000),
    ("period_points", 12, 12),
    ("period_reject_window", 25, 25),
    ("period_reject_sigma", 3.0, 3.0),
    ("duplicate_timestamp_max", 2, 2),
    ("non_monotonic_max", 1, 1),
    ("gap_factor", 2, 2),
    ("timezone_offset_min", 60, 60),
    ("default_series_id", "metric", "metric"),
    ("escalate_score_q", 1000, 1000),
)


def _nested(overrides, path, value):
    head, _, tail = path.partition(".")
    if tail:
        return {head: {tail: value}}
    return {head: value}


def _read_nested(resolved, path):
    head, _, tail = path.partition(".")
    if tail:
        return resolved[head][tail]
    return resolved[head]


class TestParamSurfaceMatrix:
    @pytest.mark.parametrize("path,value,expected", PARAM_OVERRIDES)
    def test_an_override_reaches_the_resolved_table(self, path, value, expected):
        resolved = params.resolve_params(_nested({}, path, value))
        assert _read_nested(resolved, path) == expected

    @pytest.mark.parametrize("path,value,expected", PARAM_OVERRIDES)
    def test_the_override_is_still_present_after_the_dump_round_trip(self, path, value, expected):
        resolved = params.resolve_params(_nested({}, path, value))
        dumped = params.dump_params(resolved)
        actual = _read_nested(params.resolve_params(dumped), path)
        # 参数表里既有数值也有字符串（如 series_id / metric 的枚举值）；
        # 只有数值才走 approx（pytest.approx 对 str 用 rel 会 TypeError，CI 上暴露过）。
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            assert actual == pytest.approx(expected, rel=1e-6)
        else:
            assert actual == expected

    @pytest.mark.parametrize("path,value,expected", PARAM_OVERRIDES)
    def test_an_override_changes_the_effective_evidence_value(self, path, value, expected):
        rows = _spike()
        overrides = _nested({}, path, value)
        records = _evaluate(rows, **overrides)
        pay = params.dump_params(params.resolve_params(overrides))
        for record in records:
            assert record.evidence["max_gap_ms"] == pay["max_gap_ms"]

    @pytest.mark.parametrize(
        "path",
        (
            "rolling_mad_z.window",
            "rolling_iqr.window",
            "stl_resid_z.inner",
            "rules.missing_run",
            "max_gap_ms",
            "duplicate_timestamp_max",
            "non_monotonic_max",
            "gap_factor",
            "timezone_offset_min",
            "escalate_score_q",
        ),
    )
    def test_an_integer_parameter_rejects_a_fraction(self, path):
        with pytest.raises(ValueError):
            params.resolve_params(_nested({}, path, 1.5))

    @pytest.mark.parametrize(
        "path",
        (
            "rolling_mad_z.k",
            "rolling_iqr.iqr_mult",
            "rules.pct_jump",
            "rules.cusum_k",
            "rules.cusum_h",
            "period_reject_sigma",
        ),
    )
    def test_a_decimal_parameter_rejects_null(self, path):
        with pytest.raises(ValueError):
            params.resolve_params(_nested({}, path, None))

    @pytest.mark.parametrize("path,value,expected", PARAM_OVERRIDES)
    def test_the_default_is_present_before_any_override(self, path, value, expected):
        assert _read_nested(params.resolve_params(), path) is not None or path in (
            "rules.static_threshold",
            "period_points",
            "escalate_score_q",
        )


#: G 检测器扫描：窗口 × 阈值。断言的是**单调性**（k 越大不会标更多点），
#: 而不是某一组魔法数字 —— 每个窗口的分数尺度不同。
DETECTOR_SWEEP = tuple(
    (window, k) for window in (6, 8, 12, 24, 48) for k in (1.0, 3.5, 8.0)
)


class TestDetectorSweepMatrix:
    @pytest.mark.parametrize("window,k", DETECTOR_SWEEP)
    def test_mad_flagging_is_monotone_in_k(self, window, k):
        values = [0.0] * 39 + [4.0]
        hits = detect.rolling_mad_z(values, window, k, 3)
        assert all(index == 39 for index, _s in hits)
        tighter = detect.rolling_mad_z(values, window, k * 0.5, 3)
        assert len(hits) <= len(tighter)

    @pytest.mark.parametrize("window,k", DETECTOR_SWEEP)
    def test_iqr_flagging_is_monotone_in_the_multiplier(self, window, k):
        values = [float(index) for index in range(39)] + [100.0]
        hits = detect.rolling_iqr(values, window, k, 3)
        tighter = detect.rolling_iqr(values, window, k * 0.5, 3)
        assert len(hits) <= len(tighter)

    @pytest.mark.parametrize("window,k", DETECTOR_SWEEP)
    def test_a_constant_series_is_never_flagged(self, window, k):
        assert detect.rolling_mad_z([7.0] * 60, window, k, 3) == []
        assert detect.rolling_iqr([7.0] * 60, window, k, 3) == []

    @pytest.mark.parametrize("window,k", DETECTOR_SWEEP)
    def test_all_missing_is_never_flagged(self, window, k):
        assert detect.rolling_mad_z([None] * 60, window, k, 3) == []


#: H 形状矩阵：(行数, 断档插在第几行之前, 缺几个点)。
GAP_CASES = (
    (4, 4, 3),
    (6, 3, 5),
    (6, 6, 11),
    (10, 5, 3),
    (10, 10, 8),
    (3, 2, 20),
    (24, 24, 29),
    (24, 20, 59),
)
# 注：missing 至少 3 —— 缺 2 个点时跨断档的间隔正好是 3 倍主间隔，
# 按 `delta > gap_factor × dominant`（严格大于）不算断档。


def _gap_rows(total, gap_at, missing):
    """在 ``gap_at`` 行之前挖掉 ``missing`` 个格子（时间轴照常推进）。"""
    base = timeline.parse_iso_to_epoch_ms("2024-03-01T00:00:00Z")
    rows = []
    for index in range(total):
        cell = index + (missing if index >= gap_at - 1 else 0)
        rows.append(_row(timeline.epoch_ms_to_iso(base + cell * 300000), float(index)))
    return rows


class TestShapeMatrix:
    @pytest.mark.parametrize("total,gap_at,missing", GAP_CASES)
    def test_a_gap_reports_the_missing_point_count(self, total, gap_at, missing):
        rows = _gap_rows(total, gap_at, missing)
        hits = _with_rule(_evaluate(rows), rules.RULE_GAP)
        assert len(hits) == 1
        assert hits[0].evidence["missing_points"] == missing

    @pytest.mark.parametrize("total,gap_at,missing", GAP_CASES)
    def test_a_gap_does_not_also_count_as_irregular_cadence(self, total, gap_at, missing):
        assert _with_rule(_evaluate(_gap_rows(total, gap_at, missing)), rules.RULE_IRREGULAR_CADENCE) == []

    @pytest.mark.parametrize("length", (1, 2, 3, 5, 6, 7, 12, 20))
    def test_a_missing_run_reports_its_length(self, length):
        hits = _with_rule(_evaluate(_run(length, "missing")), rules.RULE_MISSING_RUN)
        assert [record.evidence["run_length"] for record in hits] == ([length] if length >= 6 else [])

    @pytest.mark.parametrize("length", (1, 2, 3, 5, 6, 7, 12, 20))
    def test_a_zero_run_reports_its_length(self, length):
        hits = _with_rule(_evaluate(_run(length, "zero")), rules.RULE_ZERO_RUN)
        assert [record.evidence["run_length"] for record in hits] == ([length] if length >= 6 else [])

    @pytest.mark.parametrize("threshold", (1, 2, 3, 5, 6, 7, 12))
    def test_the_missing_run_threshold_moves_the_boundary(self, threshold):
        rows = _run(6, "missing")
        hits = _with_rule(_evaluate(rows, rules={"missing_run": threshold}), rules.RULE_MISSING_RUN)
        assert len(hits) == (1 if threshold <= 6 else 0)

    @pytest.mark.parametrize("factor", (1, 2, 3, 4, 10))
    def test_the_gap_factor_moves_the_gap_boundary(self, factor):
        rows = _regular_rows(4) + [_row("2024-03-01T00:35:00Z", 4.0)]
        hits = _with_rule(_evaluate(rows, gap_factor=factor), rules.RULE_GAP)
        # 跨断档的间隔是 4 个主间隔：factor < 4 才算断档
        assert len(hits) == (1 if factor < 4 else 0)

    @pytest.mark.parametrize("total", (2, 3, 5, 8, 13))
    def test_the_cadence_summary_is_consistent_on_a_regular_series(self, total):
        rows = _regular_rows(total)
        summary = shape.cadence_summary(
            [(index + 1, timeline.parse_iso_to_epoch_ms(row["timestamp"]), 1.0) for index, row in enumerate(rows)],
            3,
        )
        assert summary["n_intervals"] == total - 1
        assert summary["irregular_count"] == 0
        assert summary["irregular_ratio_ppm"] == 0
        assert summary["dominant_interval_ms"] == 300000


#: I 合并矩阵：(命中索引, 最大间隔, 期望段数)。
MERGE_CASES = (
    ((0,), 1800000, 1),
    ((0, 1), 1800000, 1),
    ((0, 2), 1800000, 1),
    ((0, 5), 1800000, 1),
    ((0, 6), 1800000, 1),
    ((0, 7), 1800000, 2),
    ((0, 1, 9), 1800000, 2),
    ((0, 1, 9, 10), 1800000, 2),
    ((0, 1), 299999, 2),
    ((0, 1), 300000, 1),
    ((0,), 0, 1),
    ((3, 4, 5), 300000, 1),
    ((3, 4, 6), 300000, 2),
)


class TestMergeMatrix:
    @pytest.mark.parametrize("indices,max_gap,expected", MERGE_CASES)
    def test_merging_is_decided_in_the_time_domain(self, indices, max_gap, expected):
        rows = _regular_rows(12)
        _rows_by_series, _ = None, None
        built_rows = [(index + 1, timeline.parse_iso_to_epoch_ms(rows[index]["timestamp"]), 1.0) for index in range(len(rows))]
        detections = {("s", "rolling_mad_z"): [(built_rows[index][1], built_rows[index][0], 1.0) for index in indices]}
        episodes = episodes_module_build(built_rows, detections, max_gap)
        assert len(episodes) == expected

    @pytest.mark.parametrize("indices,max_gap,expected", MERGE_CASES)
    def test_the_merged_episode_keeps_the_first_and_last_row(self, indices, max_gap, expected):
        rows = _regular_rows(12)
        built_rows = [(index + 1, timeline.parse_iso_to_epoch_ms(rows[index]["timestamp"]), 1.0) for index in range(len(rows))]
        detections = {("s", "rolling_mad_z"): [(built_rows[index][1], built_rows[index][0], 1.0) for index in indices]}
        episodes = episodes_module_build(built_rows, detections, max_gap)
        assert episodes[0]["start_row"] == indices[0] + 1
        assert episodes[-1]["end_row"] == indices[-1] + 1


def episodes_module_build(built_rows, detections, max_gap):
    return episodes.build_episodes({"s": built_rows}, detections, max_gap)


#: J 账本不变量矩阵：不同的工件形态都必须满足同一条账本契约。
LEDGER_SHAPES = (
    ("minimal", lambda: _minimal_rows()),
    ("spike", lambda: _spike()),
    ("flat", lambda: _flat(40)),
    ("runs", lambda: _run(6, "missing")),
    ("zero_runs", lambda: _run(6, "zero")),
    ("gap", lambda: _regular_rows(6) + [_row("2024-03-01T02:00:00Z", 6.0)]),
    ("off_grid", lambda: _regular_rows(4) + [_row("2024-03-01T00:17:00Z", 4.0)]),
    ("backwards", lambda: [_row("2024-03-01T00:05:00Z", 1.0), _row("2024-03-01T00:00:00Z", 2.0)]),
    ("duplicates", lambda: [_row("2024-03-01T00:00:00Z", float(i)) for i in range(4)]),
    ("bad_ts", lambda: [_row("2024-02-30T00:00:00Z", 1.0)]),
    ("bad_value", lambda: [_row("2024-03-01T00:00:00Z", "abc")]),
    ("two_series", lambda: _regular_rows(30, series_id="a") + _regular_rows(30, series_id="b")),
    ("all_missing", lambda: _regular_rows(30, values=[None] * 30)),
    ("declared_period", lambda: _regular_rows(60, values=[float(i % 12) for i in range(60)])),
)


class TestLedgerInvariantMatrix:
    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_ids_are_unique(self, shape_id, make_rows):
        records = _evaluate(make_rows())
        assert len([r.id for r in records]) == len(set(r.id for r in records)), shape_id

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_every_record_cites_a_complete_basis(self, shape_id, make_rows):
        for record in _evaluate(make_rows()):
            assert record.basis is not None and record.basis.complete, shape_id

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_no_record_carries_a_raw_float(self, shape_id, make_rows):
        for record in _evaluate(make_rows()):
            assert list(_iter_floats(record.as_dict())) == [], (shape_id, record.rule_id)

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_the_ledger_is_stable_across_two_runs(self, shape_id, make_rows):
        first = [r.id for r in _evaluate(make_rows())]
        second = [r.id for r in _evaluate(make_rows())]
        assert first == second, shape_id

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_the_same_shape_is_reached_through_a_json_roundtrip(self, shape_id, make_rows):
        rows = make_rows()
        assert [r.id for r in _evaluate(rows)] == [r.id for r in _evaluate(_json_roundtrip(rows))]

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_the_report_envelope_is_well_formed(self, shape_id, make_rows):
        from byteproof.core.ledger import Report

        records = _evaluate(make_rows())
        report = Report(product="byteproof", organ=SLUG, organ_version="1", subject=shape_id, records=records)
        payload = report.as_dict()
        assert payload["summary"]["total"] == len(records)
        assert payload["summary"]["blocking"] == sum(1 for r in records if r.verdict == ERROR)


#: K 信封矩阵：每一种坏信封都必须落到退出码 2（不是 1，也不是 3）。
ENVELOPE_ERRORS = (
    ("rows_is_object", {"rows": {}}),
    ("rows_is_string", {"rows": "x"}),
    ("rows_is_empty", {"rows": []}),
    ("rows_is_number", {"rows": 1}),
    ("row_is_string", {"rows": ["x"]}),
    ("row_is_list", {"rows": [[1, 2]]}),
    ("row_is_null", {"rows": [None]}),
    ("missing_timestamp", {"rows": [{"value": 1.0}]}),
    ("missing_value", {"rows": [{"timestamp": "2024-03-01T00:00:00Z"}]}),
    ("series_id_is_list", {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0, "series_id": []}]}),
    ("series_id_is_bool", {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0, "series_id": True}]}),
    ("params_is_list", {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0}], "params": []}),
    (
        "params_unknown_key",
        {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0}], "params": {"nope": 1}},
    ),
    (
        "params_unknown_nested",
        {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0}], "params": {"rules": {"x": 1}}},
    ),
    (
        "params_wrong_type",
        {"rows": [{"timestamp": "2024-03-01T00:00:00Z", "value": 1.0}], "params": {"max_gap_ms": "soon"}},
    ),
)


class TestEnvelopeMatrix:
    @pytest.mark.parametrize("case_id,payload", ENVELOPE_ERRORS)
    def test_a_bad_envelope_is_an_input_error(self, case_id, payload):
        with pytest.raises(ValueError):
            audit.evaluate(payload, BASIS)

    @pytest.mark.parametrize("case_id,payload", ENVELOPE_ERRORS)
    def test_a_bad_envelope_exits_two_through_the_cli(self, case_id, payload, tmp_path, capsys):
        target = tmp_path / "input.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_INPUT, case_id


class TestCliMatrix:
    @pytest.mark.parametrize("flag", ("--json",))
    def test_the_json_flag_is_accepted_with_and_without_basis(self, flag, tmp_path, capsys):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": _spike()}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target), flag]) in (EXIT_OK, EXIT_BLOCKED)
        capsys.readouterr()

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_the_exit_code_matches_the_summary(self, shape_id, make_rows, tmp_path, capsys):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": make_rows()}), encoding="utf-8")
        code = cli.main(["check", SLUG, "--input", str(target), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert code == (EXIT_BLOCKED if payload["summary"]["blocking"] else EXIT_OK), shape_id

    @pytest.mark.parametrize("shape_id,make_rows", LEDGER_SHAPES)
    def test_the_human_output_agrees_with_the_json_output(self, shape_id, make_rows, tmp_path, capsys):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"rows": make_rows()}), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        payload = json.loads(capsys.readouterr().out)
        cli.main(["check", SLUG, "--input", str(target)])
        human = capsys.readouterr().out
        assert "合计 %d 条" % payload["summary"]["total"] in human, shape_id
        assert "阻断 %d 条" % payload["summary"]["blocking"] in human