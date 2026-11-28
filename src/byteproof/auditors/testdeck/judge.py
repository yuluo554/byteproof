"""判定层（迁自 10-19-testdeck 的 ``flaky`` / ``slow`` / ``diff`` + ``tui/view`` 的降级两条）。

纯函数：不碰 IO、不读时钟、不读环境变量（``style_mode`` 的 env 由调用方给）。
阈值 / 窗口 / 标签全部从 ``spec`` 读（规则包唯一来源），本文件不出现数值阈值字面量。

三条"缺失 ≠ 0"的纪律（旧仓 K28 / K34）：

1. ``slow.samples`` 剔掉 ``None``（缺失耗时不进样本、不补 0）；
2. ``slow.regression`` 判不了返回 ``None``（不是 ``False``——"判过了没回归"与"判不了"必须分开）；
3. ``flaky.classify`` 零计数样本一律兜底 ``watch``（**不得判 stable**）。
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import core, spec

# ============================================================ flaky
def classify_flaky(history: Sequence[Tuple[int, str]],
                   rules: Mapping[str, Any] = spec.FLAKY_RULES) -> Dict[str, Any]:
    """``[(run_seq, status)]`` 升序 → 四类分型 + 精确比率（fail_rate / flaky_score）。"""
    statuses = [status for _run, status in history]
    counted = [status for status in statuses if core.is_counted(status)]
    counted_runs = len(counted)
    passes = counted.count(spec.STATUS_PASS)
    fails = counted.count(spec.STATUS_FAIL)
    transitions = sum(1 for left, right in zip(counted, counted[1:]) if left != right)
    fail_rate = core.mean_fraction(fails, counted_runs)
    flaky_score = Fraction(transitions, counted_runs - 1) if counted_runs > 1 else Fraction(0)

    min_rate = core.as_fraction(rules["min_fail_rate"])
    max_rate = core.as_fraction(rules["max_fail_rate"])
    min_transitions = int(rules["min_transitions"])
    min_runs = int(rules["min_runs_for_flaky"])
    fallback = str(rules["fallback_label"])

    if len(statuses) < min_runs or counted_runs == 0:
        label = fallback
    elif fail_rate == 1:
        label = spec.LABEL_BROKEN
    elif fail_rate == 0:
        label = spec.LABEL_STABLE
    elif min_rate <= fail_rate <= max_rate and transitions >= min_transitions:
        label = spec.LABEL_FLAKY
    else:
        label = fallback

    return {
        "label": label,
        "counted_runs": counted_runs,
        "passes": passes,
        "fails": fails,
        "fail_rate": fail_rate,
        "transitions": transitions,
        "flaky_score": flaky_score,
        "fail_rate_text": core.render_exact(fail_rate),
        "flaky_score_text": core.render_exact(flaky_score),
    }


def label_counts(profiles: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for profile in profiles:
        counts[profile["label"]] = counts.get(profile["label"], 0) + 1
    return counts


# ============================================================ slow
def samples(timings: Iterable[Optional[int]]) -> List[int]:
    """缺失耗时（``None``）不进样本、不补 0。"""
    return [int(value) for value in timings if value is not None]


def percentile(values: Sequence[int], p: Any) -> Optional[Fraction]:
    """线性插值分位数：索引 ``(n - 1) * p``，floor / ceil 两点按小数部分插值。"""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return None
    if n == 1:
        return Fraction(ordered[0])
    index = Fraction(n - 1) * core.as_fraction(p)
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return Fraction(ordered[lo])
    frac = index - lo
    return Fraction(ordered[lo]) + (Fraction(ordered[hi]) - Fraction(ordered[lo])) * frac


def p50(timings: Sequence[Optional[int]],
        rules: Mapping[str, Any] = spec.SLOW_RULES) -> Optional[Fraction]:
    return percentile(samples(timings), rules["p50"])


def p95(timings: Sequence[Optional[int]],
        rules: Mapping[str, Any] = spec.SLOW_RULES) -> Optional[Fraction]:
    return percentile(samples(timings), rules["p95"])


def regression(base_p50, curr_p50, rules: Mapping[str, Any] = spec.SLOW_RULES):
    """``curr / base >= ratio`` **且** ``curr - base >= delta_ms``（两处边界都计入）。"""
    ratio = core.as_fraction(rules["regression_ratio"])
    delta = int(rules["regression_delta_ms"])
    if base_p50 is None or curr_p50 is None:
        return None, spec.NOTE_MISSING_WINDOW
    base = Fraction(base_p50)
    curr = Fraction(curr_p50)
    if base == 0:
        return None, spec.NOTE_UNDEFINED_BASE
    actual_ratio = curr / base
    actual_delta = curr - base
    hit = actual_ratio >= ratio and actual_delta >= delta
    note = "ratio=%s(%s) delta=%sms(%s)" % (
        core.render_exact(actual_ratio),
        ">=" if actual_ratio >= ratio else "<",
        core.render_exact(actual_delta),
        ">=" if actual_delta >= delta else "<",
    )
    return hit, note


def sample_label(total_samples: int, base_samples: int, curr_samples: int) -> str:
    """样本量降级：0 → ``insufficient_history``；1 → ``single_sample``；任一侧空 → 不足。"""
    if total_samples == 0:
        return spec.LABEL_INSUFFICIENT_HISTORY
    if total_samples <= 1:
        return spec.LABEL_SINGLE_SAMPLE
    if base_samples == 0 or curr_samples == 0:
        return spec.LABEL_INSUFFICIENT_HISTORY
    return ""


def is_slow(time_ms: Optional[int], rules: Mapping[str, Any] = spec.SLOW_RULES) -> bool:
    """是否达到慢门槛（``None`` 不算慢——缺失不等于 0，也不等于慢）。"""
    if time_ms is None:
        return False
    return int(time_ms) >= int(rules["slow_ms"])


def bar_width(time_ms: int, max_time_ms: int, width: int) -> int:
    """瀑布条宽度 = ``round(time_ms / max_time_ms * width)``，整数四舍五入（不用 round）。"""
    divisor = int(max_time_ms)
    if divisor == 0:
        return 0
    quotient, remainder = divmod(int(time_ms) * int(width), divisor)
    return quotient + (1 if remainder + remainder >= divisor else 0)


def profile_case(case_id: int, suite_name: str, classname: str, name: str,
                 time_ms: Optional[int], timings: Sequence[Optional[int]], split: Any,
                 rules: Mapping[str, Any] = spec.SLOW_RULES) -> Dict[str, Any]:
    """一条用例的慢测试画像；``split`` 由调用方给（不发明切分点）。"""
    window = list(timings)
    if isinstance(split, bool) or not isinstance(split, int) or split <= 0 or split >= len(window):
        base_timings: List[Optional[int]] = []
        curr_timings: List[Optional[int]] = []
        has_window = False
    else:
        base_timings = window[:split]
        curr_timings = window[split:]
        has_window = True
    base_p50 = p50(base_timings, rules) if has_window else None
    curr_p50 = p50(curr_timings, rules) if has_window else None
    hit, note = regression(base_p50, curr_p50, rules)
    total = len(samples(window))
    base_count = len(samples(base_timings))
    curr_count = len(samples(curr_timings))
    return {
        "case_id": case_id, "suite_name": suite_name, "classname": classname, "name": name,
        "time_ms": time_ms,
        "p50": p50(window, rules), "p95": p95(window, rules),
        "base_p50": base_p50, "curr_p50": curr_p50,
        "regression": hit, "note": note,
        "label": sample_label(total, base_count, curr_count),
        "samples": total, "base_samples": base_count, "curr_samples": curr_count,
        "p50_text": core.render_exact(p50(window, rules)),
        "p95_text": core.render_exact(p95(window, rules)),
        "regression_text": regression_text(hit),
    }


def regression_list(profiles: Iterable[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """只收 ``True``（判不了的 ``None`` 不进清单）。"""
    return [profile for profile in profiles if profile["regression"] is True]


def regression_text(value: Optional[bool]) -> str:
    """回归列三态渲染：``yes`` / ``no`` / ``?``。"""
    if value is None:
        return "?"
    return "yes" if value else "no"


# ============================================================ diff
def classify_status_pair(status_before: Optional[str], status_after: Optional[str]) -> str:
    """一对原始状态 → 三类 + 兜底桶（判定只由状态对决定，无阈值）。"""
    if status_after == spec.STATUS_FAIL and status_before != spec.STATUS_FAIL:
        return spec.NEW_FAILURES
    if status_before == spec.STATUS_FAIL and status_after == spec.STATUS_PASS:
        return spec.FIXED
    if status_before == spec.STATUS_FAIL and status_after == spec.STATUS_FAIL:
        return spec.STILL_FAILING
    return spec.UNCHANGED


def classify_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"kind": classify_status_pair(row.get("status_before"), row.get("status_after")),
         "row": row}
        for row in rows
    ]


def group_rows(classified: Sequence[Mapping[str, Any]]) -> Dict[str, List[Mapping[str, Any]]]:
    groups: Dict[str, List[Mapping[str, Any]]] = {kind: [] for kind in spec.CLASS_ORDER}
    for entry in classified:
        groups[entry["kind"]].append(entry)
    return groups


def diff_counts(classified: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    result = {kind: 0 for kind in spec.CLASS_ORDER}
    for entry in classified:
        result[entry["kind"]] = result.get(entry["kind"], 0) + 1
    return result


def new_failure_count(classified: Iterable[Mapping[str, Any]]) -> int:
    return diff_counts(classified)[spec.NEW_FAILURES]


# ============================================================ view（降级两条 + 结构）
def column_mode(width: int, view_rules: Mapping[str, Any] = spec.VIEW_RULES) -> str:
    return "single" if int(width) < int(view_rules["min_width_single_column"]) else "three"


def style_mode(env: Mapping[str, str], isatty: bool = True) -> str:
    """``NO_COLOR``（**按键存在与否**，不看取值）/ 非 tty / TERM=dumb / 无真彩 → ``mono``。"""
    if "NO_COLOR" in env:
        return "mono"
    if not isatty:
        return "mono"
    if (env.get("TERM") or "").strip().lower() in ("", "dumb"):
        return "mono"
    if (env.get("COLORTERM") or "").strip().lower() not in ("truecolor", "24bit"):
        return "mono"
    return "color"


def escape_markup(text: Any) -> str:
    return str(text).replace("[", r"\[")


def markup(text: Any, style: str, tone: str = "") -> str:
    body = escape_markup(text)
    if style == "mono" or not tone:
        return body
    return "[%s]%s[/]" % (tone, body)


def strip_markup(text: Any) -> str:
    import re

    return re.sub(r"(?<!\\)\[[^\[\]]*\]", "", str(text)).replace("\\[", "[")


def has_markup(text: Any) -> bool:
    import re

    return bool(re.search(r"(?<!\\)\[[^\[\]]*\]", str(text)))


def time_text(time_ms: Optional[int]) -> str:
    return "—" if time_ms is None else "%d ms" % int(time_ms)


def sparkline_series(history: Sequence[Tuple[int, str]]):
    """pass=1 / fail=0；skip/missing **不绘制**（与计数口径同源），并回报跳过次数。"""
    values: List[float] = []
    skipped = 0
    for _run_id, status in history:
        if status == spec.STATUS_PASS:
            values.append(1.0)
        elif status == spec.STATUS_FAIL:
            values.append(0.0)
        else:
            skipped += 1
    return values, skipped


def sparkline_text(history: Sequence[Tuple[int, str]], style: str = "mono") -> str:
    _values, skipped = sparkline_series(history)
    counted = sum(1 for _run, status in history if core.is_counted(status))
    note = "history: %d 次参与计数（pass/fail）" % counted
    if skipped:
        note += "，%d 次 skip/missing 未绘制" % skipped
    return markup(note, style, "dim")


def summary_text(summary: Mapping[str, Optional[int]], fields: Sequence[str],
                 style: str = "mono") -> str:
    """summary 面板：``None`` 显示 ``—`` 并显式列"待实装／无数据"（None 不是 0）。"""
    tones = {"fail": "bold red", "flaky": "yellow", "broken": "bold red"}
    chunks = []
    pending = []
    for name in fields:
        value = summary.get(name)
        if value is None:
            pending.append(name)
            chunks.append("%s %s" % (markup(name, style, "dim"), markup("—", style, "dim")))
            continue
        tone = tones.get(name, "") if value else ""
        chunks.append("%s %s" % (markup(name, style, "bold"), markup(str(value), style, tone)))
    line = "  ".join(chunks)
    if pending:
        line += "\n" + markup(
            "待实装／无数据：%s（None 不是 0：没得数时不猜）" % "/".join(pending), style, "dim")
    return line


# ============================================================ 键位表单点
_DESCRIPTIONS_BY_LABEL = {label: text for label, text in spec.KEYS}


def display_label(key: str) -> str:
    return spec.DISPLAY_LABELS.get(key, key)


def description_for(action: str) -> str:
    key = spec.BINDINGS.get(action, "")
    return _DESCRIPTIONS_BY_LABEL.get(display_label(key), "")