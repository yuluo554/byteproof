"""器官主体：工件 -> 缺陷账本（``evaluate(subject, basis) -> Iterable[Record]``）。

四段流水线，每段只回答一个问题：

1. **行级**：这一行的时间戳读得出来吗？值是不是有限数？（读不出来就是 ``error``）
2. **时间轴**：重复时间戳/时间倒序是否超出本序列容差？（超了就是 ``error``）
3. **形状**：有没有断档？采样是不是偏离了主间隔？（断档 ``warn``，不规则 ``info``）
4. **信号**：四个检测器分别命中哪些点，按时间域合并成哪些 episode？（``warn``，
   可用 ``escalate_score_q`` 显式升级为 ``error``）

本模块只做编排 + 口径落地，算术与判定在各自模块里。**没有任何打印、文件读取、
环境变量、时钟**：这一条同时被 ``tests/test_<slug>.py::TestNoClockNoSideEffects``
（AST 扫描本包）和宿主内核的行为契约守着。
"""

from __future__ import annotations

from typing import Iterable, List, Mapping, Tuple

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, Record

from . import rules, shape
from .detect import (
    estimate_period,
    grid_positions,
    rolling_iqr,
    rolling_mad_z,
    rules as rule_detectors,
    stl_resid_z,
)
from .episodes import build_episodes
from .params import (
    QUANT_DECIMALS,
    dump_params,
    fixed_to_str,
    resolve_params,
    threshold_refs,
)
from .subject import parse_subject
from .timeline import epoch_ms_to_iso

#: 检测器 -> 人读标签的模板。参数值来自**生效的**参数块（不是默认值），
#: 这样一条 episode 的 message 与 evidence 说的是同一组数字。
_LABELS = {
    "rules.static_threshold": "绝对值静态阈值超限（static_threshold=%s）",
    "rules.pct_jump": "相邻点百分比跳变超阈（pct_jump=%s）",
    "rules.missing_run": "连续缺失段（长度 >= missing_run=%s）",
    "rules.zero_run": "连续零值段（长度 >= missing_run=%s）",
    "rules.cusum": "CUSUM 累计偏移超阈（cusum_k=%s, cusum_h=%s）",
}


def evaluate(subject: Mapping, basis: Basis) -> Iterable[Record]:
    """审一次工件。返回账本条目（顺序由内核 ``Report`` 再排一次，这里不必排）。"""
    if not isinstance(subject, Mapping):
        raise ValueError("输入必须是 JSON 对象")
    params = resolve_params(subject.get("params"))
    parsed = parse_subject(subject, params)

    records: List[Record] = []
    records.extend(_row_issue_records(parsed, basis))
    records.extend(_timeline_records(parsed, params, basis))
    records.extend(_shape_records(parsed, params, basis))
    records.extend(_signal_records(parsed, params, basis))
    return tuple(records)


def _record(rule_id, verdict, message, basis, path, evidence):
    """唯一构造点：每条账本都用 ``basis.ref`` 取依据，取不到就 ``RuleMissing`` 冒到 CLI。"""
    return Record(
        rule_id=rule_id,
        verdict=verdict,
        message=message,
        basis=basis.ref(rule_id),
        path=path,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# 1. 行级
# ---------------------------------------------------------------------------
def _row_issue_records(parsed, basis) -> List[Record]:
    built = []
    for issue in parsed.issues:
        built.append(
            _record(
                issue.rule_id,
                rules.verdict_for(issue.rule_id),
                "第 %d 行（%s）不可读：%s" % (issue.row_no, issue.series_id, issue.detail),
                basis,
                "%s#row=%d" % (issue.series_id, issue.row_no),
                {"row": issue.row_no, "series_id": issue.series_id, "detail": issue.detail},
            )
        )
    return built


# ---------------------------------------------------------------------------
# 2. 时间轴
# ---------------------------------------------------------------------------
def _timeline_records(parsed, params, basis) -> List[Record]:
    built = []
    duplicate_max = params["duplicate_timestamp_max"]
    monotonic_max = params["non_monotonic_max"]
    for series_id in parsed.series_order:
        rows = parsed.rows_by_series[series_id]
        for duplicate in shape.duplicate_timestamps(rows):
            repeated = duplicate["row_nos"][1 + duplicate_max :] if duplicate_max >= 0 else []
            for row_no in repeated:
                first_row = duplicate["row_nos"][0]
                built.append(
                    _record(
                        rules.RULE_DUPLICATE_TIMESTAMP,
                        rules.verdict_for(rules.RULE_DUPLICATE_TIMESTAMP),
                        "时间戳重复：第 %d 行与第 %d 行同为 %s（本序列容差 %d 次重复）"
                        % (
                            row_no,
                            first_row,
                            epoch_ms_to_iso(duplicate["epoch_ms"]),
                            duplicate_max,
                        ),
                        basis,
                        "%s#row=%d" % (series_id, row_no),
                        {
                            "row": row_no,
                            "first_row": first_row,
                            "epoch_ms": duplicate["epoch_ms"],
                            "extra_rows": duplicate["extra_rows"],
                            "duplicate_timestamp_max": duplicate_max,
                        },
                    )
                )
        backwards = shape.backwards_steps(rows)
        if len(backwards) > monotonic_max:
            for row_no, previous_row, delta in backwards[monotonic_max:]:
                built.append(
                    _record(
                        rules.RULE_NON_MONOTONIC,
                        rules.verdict_for(rules.RULE_NON_MONOTONIC),
                        "时间倒序：第 %d 行比第 %d 行早 %d ms（本序列容差 %d 步）"
                        % (row_no, previous_row, -delta, monotonic_max),
                        basis,
                        "%s#row=%d" % (series_id, row_no),
                        {
                            "row": row_no,
                            "previous_row": previous_row,
                            "delta_ms": delta,
                            "non_monotonic_max": monotonic_max,
                        },
                    )
                )
    return built


# ---------------------------------------------------------------------------
# 3. 形状
# ---------------------------------------------------------------------------
def _shape_records(parsed, params, basis) -> List[Record]:
    built = []
    for series_id in parsed.series_order:
        rows = parsed.rows_by_series[series_id]
        found_intervals = shape.intervals(rows)
        dominant = shape.dominant_interval(found_intervals)
        cadence = shape.cadence_summary(rows, params["gap_factor"])
        found_gaps = shape.gaps(rows, found_intervals, dominant, params["gap_factor"])

        for gap in found_gaps:
            built.append(
                _record(
                    rules.RULE_GAP,
                    rules.verdict_for(rules.RULE_GAP),
                    "采样断档：第 %d 行与第 %d 行相距 %d ms（主间隔 %d ms 的 %d 倍），缺 %d 个点"
                    % (
                        gap["prev_row"],
                        gap["row_no"],
                        gap["interval_ms"],
                        dominant,
                        gap["interval_ms"] // dominant,
                        gap["missing_points"],
                    ),
                    basis,
                    "%s@%s..%s"
                    % (
                        series_id,
                        epoch_ms_to_iso(gap["prev_ms"]),
                        epoch_ms_to_iso(gap["ms"]),
                    ),
                    {
                        "prev_row": gap["prev_row"],
                        "row": gap["row_no"],
                        "prev_ms": gap["prev_ms"],
                        "ms": gap["ms"],
                        "interval_ms": gap["interval_ms"],
                        "dominant_interval_ms": dominant,
                        "missing_points": gap["missing_points"],
                        "gap_factor": params["gap_factor"],
                    },
                )
            )

        # 主间隔之外的样本里，已经按断档落账的那部分不再重复报一次；
        # 剩下的才是"采样本身不齐"（info，不判断好坏）。
        off_grid = cadence["irregular_count"] - len(found_gaps)
        if off_grid > 0:
            built.append(
                _record(
                    rules.RULE_IRREGULAR_CADENCE,
                    rules.verdict_for(rules.RULE_IRREGULAR_CADENCE),
                    "采样不规则：%d 个间隔中 %d 个不是主间隔 %d ms（%d ppm；其中 %d 个已按断档落账）"
                    % (
                        cadence["n_intervals"],
                        cadence["irregular_count"],
                        cadence["dominant_interval_ms"],
                        cadence["irregular_ratio_ppm"],
                        len(found_gaps),
                    ),
                    basis,
                    "%s#cadence" % (series_id,),
                    dict(cadence, series_id=series_id, off_grid_intervals=off_grid),
                )
            )
    return built


# ---------------------------------------------------------------------------
# 4. 信号
# ---------------------------------------------------------------------------
def _run_detectors(parsed, params, period_points):
    """跑满四个检测器；返回 ``{(series_id, detector): [(epoch_ms, row_no, score)]}``。"""
    detections = {}
    for series_id in parsed.series_order:
        rows = parsed.rows_by_series[series_id]
        values = [row[2] for row in rows]
        positions = grid_positions(rows)

        def record(detector, hits, _series_id=series_id, _rows=rows):
            bucket = detections.setdefault((_series_id, detector), [])
            for index, score in hits:
                bucket.append((_rows[index][1], _rows[index][0], score))

        mad = params["rolling_mad_z"]
        record(
            "rolling_mad_z",
            rolling_mad_z(values, mad["window"], mad["k"], mad["min_valid"]),
        )
        iqr = params["rolling_iqr"]
        record(
            "rolling_iqr",
            rolling_iqr(values, iqr["window"], iqr["iqr_mult"], iqr["min_valid"]),
        )
        stl = params["stl_resid_z"]
        record(
            "stl_resid_z",
            stl_resid_z(
                values,
                positions,
                period_points,
                stl["inner"],
                stl["outer"],
                stl["window"],
                stl["k"],
                stl["min_valid"],
            ),
        )
        for index, score, rule_name in rule_detectors(values, params["rules"]):
            record("rules." + rule_name, [(index, score)])
    return detections


def _resolve_period(parsed, params) -> Tuple[int, str, List[dict]]:
    """生效的周期与它的来源：声明 / 估得 / 无周期缺省（旧仓 K8/D13）。"""
    if params["period_points"] is not None:
        return params["period_points"], "declared", []
    period_points, estimates = estimate_period(
        parsed.rows_by_series,
        parsed.series_order,
        params["period_reject_window"],
        params["period_reject_sigma"],
    )
    source = "estimated" if estimates else "no-cycle-default"
    described = [
        {"series_id": series_id, "period_points": value}
        for series_id, value in sorted(estimates)
    ]
    return period_points, source, described


def _label_for(detector, param_block, period_points):
    if detector in _LABELS:
        template = _LABELS[detector]
        if detector == "rules.cusum":
            return template % (param_block["cusum_k"], param_block["cusum_h"])
        if detector in ("rules.missing_run", "rules.zero_run"):
            return template % (param_block["missing_run"],)
        if detector == "rules.static_threshold":
            return template % (param_block["static_threshold"],)
        return template % (param_block["pct_jump"],)
    if detector == "rolling_mad_z":
        return "滚动 median/MAD 稳健 z 超阈（window=%d, k=%s, 周期 %d 点）" % (
            param_block["window"],
            param_block["k"],
            period_points,
        )
    if detector == "rolling_iqr":
        return "滚动 IQR 箱界越界（window=%d, iqr_mult=%s）" % (
            param_block["window"],
            param_block["iqr_mult"],
        )
    return "STL 残差稳健 z 超阈（window=%d, k=%s, 周期 %d 点）" % (
        param_block["window"],
        param_block["k"],
        period_points,
    )


def _signal_records(parsed, params, basis) -> List[Record]:
    period_points, period_source, _estimates = _resolve_period(parsed, params)
    detections = _run_detectors(parsed, params, period_points)
    episodes = build_episodes(
        parsed.rows_by_series, detections, params["max_gap_ms"], QUANT_DECIMALS
    )
    refs = threshold_refs(dump_params(params))
    escalate = params["escalate_score_q"]

    built = []
    for episode in episodes:
        detector = episode["detector"]
        rule_id = rules.SIGNAL_RULE_BY_DETECTOR[detector]
        verdict = rules.verdict_for(rule_id)
        param_block = refs[rules.DETECTOR_PARAM_KEY[detector]]
        peak_text = fixed_to_str(episode["peak_score_q"], QUANT_DECIMALS)
        if escalate is not None and episode["peak_score_q"] >= escalate:
            verdict = ERROR
        message = "%s：峰值分数 %s，%d 个点，时长 %d ms" % (
            _label_for(detector, param_block, period_points),
            peak_text,
            episode["n_points"],
            episode["duration_ms"],
        )
        if episode["run_length"] is not None:
            message = "%s，段长 %d" % (message, episode["run_length"])
        evidence = {
            "episode_id": episode["episode_id"],
            "series_id": episode["series_id"],
            "detector": detector,
            "start": episode["start"],
            "end": episode["end"],
            "start_ms": episode["start_ms"],
            "end_ms": episode["end_ms"],
            "duration_ms": episode["duration_ms"],
            "n_points": episode["n_points"],
            "start_row": episode["start_row"],
            "end_row": episode["end_row"],
            "peak_score_q": episode["peak_score_q"],
            "peak_score": peak_text,
            "period_points": period_points,
            "period_source": period_source,
            "max_gap_ms": params["max_gap_ms"],
            "threshold_ref": param_block,
        }
        if episode["run_length"] is not None:
            evidence["run_length"] = episode["run_length"]
        if escalate is not None:
            evidence["escalate_score_q"] = escalate
        built.append(
            _record(
                rule_id,
                verdict,
                message,
                basis,
                "%s@%s..%s" % (episode["series_id"], episode["start"], episode["end"]),
                evidence,
            )
        )
    return built