"""判定核（迁自 10-19-subtitle-preflight 的 ``core/decode`` / ``core/rules/*`` / ``core/fix``）。

七个判定面 **1:1 移植**（源仓出处见各函数 docstring）：

| 面 | 旧仓模块 | 面 | 旧仓模块 |
|---|---|---|---|
| 编码嗅探 | ``core/decode.js`` | 时序 T01–T12 | ``core/rules/timing.js`` |
| fps 漂移拟合 | ``core/rules/drift.js`` | 可读性 R01–R07 | ``core/rules/readability.js`` |
| 卫生 S01–S10 | ``core/rules/hygiene.js`` | 可逆修复 | ``core/fix.js`` |
| 编排/排序 | ``core/report.js``（排序口径） | | |

**parsing / report 渲染留输入层与宿主**（D1+D18 排除词 ``parse`` / ``report``）：
cue 序列由输入层解析后摊平传入（含 ``sourceLine`` / ``timeLine`` / ``textLineNumbers``），
器官不解析字幕文本、不渲染报告、不读文件 / 环境变量 / 时钟 / locale / 随机源。
阈值全部经 ``th`` 传入（唯一来源 ``spec.THRESHOLDS``；本文件不出现数值阈值字面量）。

定点纪律：漂移拟合全程用「微毫秒」整数（``MICRO_PER_MS``），``Math.round`` 以
``js_round`` 复刻（Python 内建 ``round`` 是银行家舍入，会改判定）。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import spec

# ============================================================ 公共小工具
#: JS ``\s`` 的等价字符集（Python ``\s`` 多出 \x1c-\x1f，会改"可见字符"计数）。
_WS = re.compile(
    "[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
)


def js_round(value: float) -> int:
    """``Math.round``（半数向上，负半数向 +∞）；Python ``round`` 是半数取偶，不能直接用。"""
    return int(math.floor(value + 0.5))


def _cue_text(cue: Mapping[str, Any]) -> str:
    lines = cue.get("textLines") or []
    return "\n".join(str(line) for line in lines)


def _source_line(cue: Mapping[str, Any]) -> int:
    value = cue.get("sourceLine", 0)
    return int(value) if isinstance(value, (int, float)) else 0


def _time_line(cue: Mapping[str, Any]) -> int:
    value = cue.get("timeLine", 0)
    return int(value) if isinstance(value, (int, float)) else 0


def _finding(
    rule_id: str,
    cue_index: int,
    cue: Mapping[str, Any],
    field: str,
    expected: Any,
    actual: Any,
    message: str,
    severity: Optional[str] = None,
) -> Dict[str, Any]:
    """旧仓 7 键 finding 形态（``ruleId/severity/line/field/expected/actual/message``）。"""
    return {
        "ruleId": rule_id,
        "severity": severity or spec.SEVERITY[rule_id],
        "line": _source_line(cue),
        "field": field,
        "expected": str(expected),
        "actual": str(actual),
        "message": message,
        # 账本位置（不进旧 7 键语义，只用于稳定 id 与证据）；cue 序号 1 起。
        "_cue": cue_index + 1,
        "_cueBased": True,
        "_timeLine": _time_line(cue),
    }


def sort_findings(findings: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """旧仓 ``report.compareFindings``：``(line, ruleId, field)`` 三段排序。"""
    return sorted(
        (dict(item) for item in findings),
        key=lambda item: (item.get("line", 0), item.get("ruleId", ""), item.get("field", "")),
    )


def is_full_width(ch: str) -> bool:
    """旧仓 ``readability.isFullWidth``：码点落在 13 个全角区间之一。"""
    cp = ord(ch)
    for lo, hi in spec.FULL_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def is_cjk(ch: str) -> bool:
    cp = ord(ch)
    for lo, hi in spec.CJK_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def is_han(ch: str) -> bool:
    return spec.HAN_LO <= ord(ch) <= spec.HAN_HI


def _is_latin_or_digit(ch: str) -> bool:
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9")


# ============================================================ 编码嗅探（core/decode.js）
#: 旧仓 ``stripBom`` 的三个 BOM 形态。
BOM_UTF8 = b"\xef\xbb\xbf"
BOM_UTF16LE = b"\xff\xfe"
BOM_UTF16BE = b"\xfe\xff"


def strip_bom(data: bytes) -> Tuple[Optional[str], bytes]:
    """剥离 BOM 并如实回报（``utf-8`` / ``utf-16le`` / ``utf-16be`` / ``None``）。"""
    if len(data) >= 3 and data[:3] == BOM_UTF8:
        return "utf-8", data[3:]
    if len(data) >= 2 and data[:2] == BOM_UTF16LE:
        return "utf-16le", data[2:]
    if len(data) >= 2 and data[:2] == BOM_UTF16BE:
        return "utf-16be", data[2:]
    return None, data


def detect_eol(text: str) -> str:
    """旧仓 ``detectEol``：COUNT 三类行尾，单类返回该类，多类 ``mixed``，无行尾 ``lf``。"""
    crlf = cr = lf = 0
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == "\r":
            if index + 1 < length and text[index + 1] == "\n":
                crlf += 1
                index += 2
                continue
            cr += 1
        elif ch == "\n":
            lf += 1
        index += 1
    kinds = sum(1 for count in (crlf, cr, lf) if count > 0)
    if kinds == 0:
        return "lf"
    if kinds > 1:
        return "mixed"
    if crlf > 0:
        return "crlf"
    if cr > 0:
        return "cr"
    return "lf"


def normalize_eol(text: str) -> str:
    """CRLF / CR → LF（归一不改变行数，旧仓测试钉住）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _try_decode(data: bytes, encoding: str, fatal: bool) -> Tuple[bool, str]:
    try:
        return True, data.decode(encoding, errors="strict" if fatal else "replace")
    except (UnicodeDecodeError, LookupError):
        return False, ""


def decode_bytes(data: bytes) -> Dict[str, Any]:
    """旧仓 ``decodeBytes``：BOM → UTF-8 严格 → GBK → UTF-8 替换（lossy），回退显式上报。"""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("输入必须是 bytes / bytearray")
    payload = bytes(data)
    bom, stripped = strip_bom(payload)
    diagnostics: List[Dict[str, str]] = []
    encoding = "utf-8"
    fallback = False
    lossy = False
    decoded: Optional[str] = None

    if bom == "utf-8":
        ok, text = _try_decode(stripped, "utf-8", True)
        if ok:
            decoded = text
        else:
            lossy = True
            decoded = _try_decode(stripped, "utf-8", False)[1]
            diagnostics.append({
                "code": "decode.invalid-utf8",
                "detail": "UTF-8 BOM 与内容不符，已按替换字符解码",
            })
    elif bom in ("utf-16le", "utf-16be"):
        encoding = bom
        ok, text = _try_decode(stripped, encoding, True)
        if ok:
            decoded = text
        else:
            lossy = True
            decoded = _try_decode(stripped, encoding, False)[1]
            diagnostics.append({
                "code": "decode.invalid-utf16",
                "detail": "UTF-16 内容解码失败，已降级",
            })
    else:
        ok, text = _try_decode(payload, "utf-8", True)
        if ok:
            decoded = text
        else:
            gbk_ok, gbk_text = _try_decode(payload, "gbk", True)
            if gbk_ok:
                encoding = "gbk"
                fallback = True
                decoded = gbk_text
                diagnostics.append({
                    "code": "decode.gbk-fallback",
                    "detail": "非 UTF-8 字节，已回退 GBK 解码",
                })
            else:
                lossy = True
                decoded = _try_decode(payload, "utf-8", False)[1]
                diagnostics.append({
                    "code": "decode.lossy",
                    "detail": "UTF-8 与 GBK 均严格解码失败，已按替换字符解码",
                })

    eol = detect_eol(decoded or "")
    if eol == "mixed":
        diagnostics.append({
            "code": "decode.mixed-eol",
            "detail": "文件混用 CRLF/CR/LF，已统一为 LF",
        })
    return {
        "text": normalize_eol(decoded or ""),
        "encoding": encoding,
        "bom": bom,
        "fallback": fallback,
        "lossy": lossy,
        "eol": eol,
        "diagnostics": diagnostics,
    }


# ============================================================ fps 漂移拟合（core/rules/drift.js）
def median_int(values: Sequence[int]) -> int:
    """整数中位数（偶数取中间两数的**下**中位，保证确定性）。"""
    ordered = sorted(values)
    mid = len(ordered) >> 1
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def clean_run_starts(cues: Sequence[Mapping[str, Any]], gap_min: int) -> List[int]:
    """「干净对」最长连续段的起点：个体合法 + 相邻对合法（旧仓 ``cleanRunStarts``）。"""
    valid: List[bool] = []
    for cue in cues:
        start = cue.get("startMs")
        end = cue.get("endMs")
        valid.append(
            not cue.get("unparsable", False)
            and isinstance(start, (int, float))
            and isinstance(end, (int, float))
            and math.isfinite(start)
            and math.isfinite(end)
            and start >= 0
            and end > start
        )
    best: List[int] = []
    run: List[int] = []
    for index, cue in enumerate(cues):
        if not valid[index]:
            run = []
            continue
        if not run:
            run = [index]
        else:
            prev = cues[run[-1]]
            gap = cue["startMs"] - prev["endMs"]
            clean_pair = (
                gap >= gap_min
                and cue["startMs"] >= prev["startMs"]
                and not (
                    cue["startMs"] == prev["startMs"]
                    and cue["endMs"] == prev["endMs"]
                    and _cue_text(cue) == _cue_text(prev)
                )
            )
            if clean_pair:
                run.append(index)
            else:
                run = [index]
        if len(run) > len(best):
            best = list(run)
    return [int(cues[index]["startMs"]) for index in best]


def drift_fit(starts_ms: Sequence[int], declared_fps: Any, th: Mapping[str, Any]) -> Dict[str, Any]:
    """旧仓 ``drift.fit``：粗搜 + ±1 粗步细搜的 2-D（scale × offset）整数拟合。

    报红条件不是残差（自由 scale 会把纯比例漂移吸收干净），而是
    ``|scale − 1| × 跨度 > residualMaxMs``，并用 ``gridToleranceMs`` 作"确实落在声明
    帧栅格上"的护栏：不落格即 ``not_frame_grid``（skipped，不报）。
    """
    samples = len(starts_ms)
    min_samples = th["drift.minSamples"]
    if not (isinstance(declared_fps, (int, float)) and math.isfinite(declared_fps) and declared_fps > 0):
        return {
            "ok": False,
            "skipped": {
                "kind": "rule",
                "ruleId": "timing.fps-drift",
                "reason": "media_fps_unknown",
                "samples": samples,
            },
        }
    if samples < min_samples:
        return {
            "ok": False,
            "skipped": {
                "kind": "rule",
                "ruleId": "timing.fps-drift",
                "reason": "samples_below_min",
                "samples": samples,
            },
        }

    micro = spec.MICRO_PER_MS
    unit = spec.SCALE_UNIT
    observed = [js_round(ms * micro) for ms in starts_ms]
    frame_micro = unit / float(declared_fps)

    offset_range = th["drift.offsetRange"]
    off_lo = offset_range[0] * micro
    off_hi = offset_range[1] * micro
    off_coarse = th["drift.offsetStepCoarse"] * micro
    off_fine = th["drift.offsetStepFine"] * micro

    scale_range = th["drift.scaleRange"]
    s_lo = js_round(scale_range[0] * unit)
    s_hi = js_round(scale_range[1] * unit)
    s_coarse = js_round(th["drift.scaleStepCoarse"] * unit)
    s_fine = js_round(th["drift.scaleStepFine"] * unit)

    def build_ref(scale_micro: int) -> List[int]:
        step = (scale_micro / unit) * frame_micro
        frames = [0]
        for index in range(1, samples):
            frames.append(frames[index - 1] + js_round((observed[index] - observed[index - 1]) / step))
        return [js_round(frame * frame_micro) for frame in frames]

    def predict(scale_micro: int, ref: Sequence[int]) -> List[int]:
        return [js_round((scale_micro * value) / unit) for value in ref]

    def evaluate_scale(scale_micro: int, ref: Sequence[int], step: int) -> Dict[str, int]:
        pred = predict(scale_micro, ref)
        diff = [observed[i] - pred[i] for i in range(samples)]
        off_u = js_round(median_int(diff) / step) * step
        if off_u < off_lo:
            off_u = off_lo
        if off_u > off_hi:
            off_u = off_hi
        residual = [abs(observed[i] - off_u - pred[i]) for i in range(samples)]
        return {"scaleU": scale_micro, "offsetU": off_u, "residualU": median_int(residual)}

    def better(cand: Mapping[str, int], best: Optional[Mapping[str, int]]) -> bool:
        if best is None:
            return True
        if cand["residualU"] != best["residualU"]:
            return cand["residualU"] < best["residualU"]
        if cand["offsetU"] != best["offsetU"]:
            return cand["offsetU"] < best["offsetU"]
        return cand["scaleU"] < best["scaleU"]

    best: Optional[Dict[str, int]] = None
    scale_u = s_lo
    while scale_u <= s_hi:
        cand = evaluate_scale(scale_u, build_ref(scale_u), off_coarse)
        if better(cand, best):
            best = cand
        scale_u += s_coarse
    assert best is not None

    fine = dict(best)
    s_from = max(s_lo, best["scaleU"] - s_coarse)
    s_to = min(s_hi, best["scaleU"] + s_coarse)
    scale_u = s_from
    while scale_u <= s_to:
        ref = build_ref(scale_u)
        pred = predict(scale_u, ref)
        o_from = max(off_lo, best["offsetU"] - off_coarse)
        o_to = min(off_hi, best["offsetU"] + off_coarse)
        off_u = o_from
        while off_u <= o_to:
            residual = [abs(observed[i] - off_u - pred[i]) for i in range(samples)]
            cand = {"scaleU": scale_u, "offsetU": off_u, "residualU": median_int(residual)}
            if better(cand, fine):
                fine = cand
            off_u += off_fine
        scale_u += s_fine

    span_u = observed[-1] - observed[0]
    drift_u = js_round((abs(fine["scaleU"] - unit) * span_u) / unit)
    grid_tolerance_u = th["drift.gridToleranceMs"] * micro
    residual_max_u = th["drift.residualMaxMs"] * micro

    on_grid = fine["residualU"] <= grid_tolerance_u
    drifted = drift_u > residual_max_u
    fires = on_grid and drifted

    detail = {
        "scale": fine["scaleU"] / unit,
        "offsetMs": fine["offsetU"] / micro,
        "residualMs": fine["residualU"] / micro,
        "spanMs": span_u / micro,
        "driftMs": drift_u / micro,
        "samples": samples,
        "declaredFps": declared_fps,
        "residualMaxMs": th["drift.residualMaxMs"],
        "gridToleranceMs": th["drift.gridToleranceMs"],
    }

    if not fires:
        return {
            "ok": False,
            "skipped": {
                "kind": "rule",
                "ruleId": "timing.fps-drift",
                "reason": "drift_within_tolerance" if on_grid else "not_frame_grid",
                "samples": samples,
            },
        }
    return {"ok": True, "fit": detail}


def drift_evaluate(cues: Sequence[Mapping[str, Any]], declared_fps: Any, th: Mapping[str, Any]) -> Dict[str, Any]:
    """旧仓 ``drift.evaluate``：干净段 → 拟合 → 一条 ``timing.fps-drift``（warn, line=1）。"""
    starts = clean_run_starts(cues, th["timing.gapMin"])
    outcome = drift_fit(starts, declared_fps, th)
    if not outcome["ok"]:
        return {"findings": [], "skipped": [outcome["skipped"]], "fit": None}
    fit = outcome["fit"]
    return {
        "findings": [
            {
                "ruleId": "timing.fps-drift",
                "severity": "warn",
                "line": 1,
                "field": "fit",
                "expected": "|scale - 1| × 跨度 <= %s ms" % (fit["residualMaxMs"],),
                "actual": "scale=%s offsetMs=%s 漂移=%sms"
                % (fit["scale"], fit["offsetMs"], fit["driftMs"]),
                "message": "整条时间轴等比漂移（疑似字幕帧率与素材帧率不一致）",
                "_cue": 0,
                "_cueBased": False,
                "_timeLine": 1,
            }
        ],
        "skipped": [],
        "fit": fit,
    }


# ============================================================ 时序 T01–T12（core/rules/timing.js）
def find_first_reversal(cues: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """文件顺序 ≠ 时间顺序：返回首个倒退 cue 的下标（整段只报一条）。"""
    for index in range(1, len(cues)):
        if cues[index]["startMs"] < cues[index - 1]["startMs"]:
            return index
    return None


def timing_findings(
    cues: Sequence[Mapping[str, Any]],
    th: Mapping[str, Any],
    declared: Optional[Mapping[str, Any]] = None,
    diagnostics: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """旧仓 ``timing.run``：逐 cue 的 T01–T10 + T12 诊断转 finding + T11 漂移。"""
    opts = dict(declared or {})
    findings: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    gap_min = th["timing.gapMin"]

    for index, cue in enumerate(cues):
        prev = cues[index - 1] if index > 0 else None
        start = cue["startMs"]
        end = cue["endMs"]

        if start < 0:
            findings.append(_finding(
                "timing.negative-start", index, cue, "startMs", ">= 0", start, "起点为负"))
        if end < start:
            findings.append(_finding(
                "timing.negative-duration", index, cue, "endMs", ">= startMs", end, "结束早于开始"))
        elif end == start:
            findings.append(_finding(
                "timing.zero-duration", index, cue, "endMs", "> startMs", end, "时长为 0"))

        if prev is not None:
            if start < prev["endMs"]:
                findings.append(_finding(
                    "timing.overlap", index, cue, "startMs", ">= %s" % (prev["endMs"],), start,
                    "本条起点早于上一条结束"))
            else:
                gap = start - prev["endMs"]
                if gap < gap_min:
                    findings.append(_finding(
                        "timing.gap-too-small", index, cue, "startMs",
                        ">= %s" % (prev["endMs"] + gap_min,), start, "与上一条的间隔小于口径下限"))
            if start < prev["startMs"]:
                findings.append(_finding(
                    "timing.non-monotonic", index, cue, "startMs", ">= %s" % (prev["startMs"],),
                    start, "起点相对上一条倒退"))
            if (
                start == prev["startMs"]
                and end == prev["endMs"]
                and _cue_text(cue) == _cue_text(prev)
            ):
                findings.append(_finding(
                    "timing.duplicate-cue", index, cue, "text", "唯一", "与上一条完全相同",
                    "重复 cue", "warn"))

    reversed_index = find_first_reversal(cues)
    if reversed_index is not None:
        cue = cues[reversed_index]
        findings.append(_finding(
            "timing.file-order-mismatch", reversed_index, cue, "startMs", "按时间升序排列",
            cue["startMs"], "文件顺序与时间顺序不一致", "warn"))

    media_duration = opts.get("mediaDurationMs", opts.get("media_duration_ms"))
    if (
        isinstance(media_duration, (int, float))
        and math.isfinite(media_duration)
        and media_duration > 0
    ):
        last_index = 0
        for index, cue in enumerate(cues):
            if cue["endMs"] > cues[last_index]["endMs"]:
                last_index = index
        if cues and cues[last_index]["endMs"] > media_duration:
            cue = cues[last_index]
            findings.append(_finding(
                "timing.past-media-end", last_index, cue, "endMs",
                "<= %s" % (media_duration,), cue["endMs"], "末条结束时间超过声明的媒体时长"))
    else:
        skipped.append({
            "kind": "rule",
            "ruleId": "timing.past-media-end",
            "reason": "media_duration_unknown",
        })

    for diagnostic in diagnostics:
        if diagnostic.get("code") == "parse.unparsable-timecode":
            # 旧仓该 finding 由解析层产出、pipeline 装配；账本按同一「诊断 → finding」法承接
            findings.append({
                "ruleId": "timing.unparsable-timecode",
                "severity": "error",
                "line": diagnostic.get("line", 0),
                "field": diagnostic.get("field") or "timecode",
                "expected": "时间码可解析",
                "actual": diagnostic.get("detail") or "无法解析",
                "message": "时间码无法解析（解析层诊断透传）",
                "_cue": 0,
                "_cueBased": False,
                "_timeLine": diagnostic.get("line", 0),
            })
        elif diagnostic.get("code") == "parse.timecode-precision":
            findings.append({
                "ruleId": "timing.timecode-precision",
                "severity": "warn",
                "line": diagnostic.get("line", 0),
                "field": diagnostic.get("field") or "timecode",
                "expected": "3 位毫秒 / 小时位 <= 2 位",
                "actual": diagnostic.get("detail") or "非标准精度",
                "message": "时间码精度不符合口径",
                "_cue": 0,
                "_cueBased": False,
                "_timeLine": diagnostic.get("line", 0),
            })

    declared_fps = opts.get("declaredFps", opts.get("declared_fps"))
    drift = drift_evaluate(cues, declared_fps, th)
    findings.extend(drift["findings"])
    skipped.extend(drift["skipped"])

    return {
        "findings": findings,
        "skipped": skipped,
        "implemented": sorted(spec.TIMING_RULES),
        "driftFit": drift["fit"],
    }


# ============================================================ 可读性 R01–R07（core/rules/readability.js）
#: 装饰剥离（旧仓 ``stripDecorations``：ASS 覆写块 / HTML 标签 / 方括号 / 圆括号 / 音符）。
_DECORATION_PATTERNS = (
    re.compile(r"\{[^}]*\}"),
    re.compile(r"<[^>]*>"),
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"（[^）]*）"),
    re.compile(r"\([^)]*\)"),
    re.compile("♪"),
)


def strip_decorations(line: str) -> str:
    """剥掉不计入可见字符的装饰（顺序与旧仓一致：ASS → HTML → [] → （） → () → ♪）。"""
    text = str(line)
    for pattern in _DECORATION_PATTERNS:
        text = pattern.sub("", text)
    return text


def line_width_milli(line: str) -> int:
    """一行 → 千分字符宽度（空白不计；全角 1000 / 半角 500）。"""
    milli = 0
    for ch in strip_decorations(line):
        if _WS.match(ch):
            continue
        milli += spec.FULL_MILLI if is_full_width(ch) else spec.HALF_MILLI
    return milli


def measure_cue(text_lines: Sequence[str]) -> Dict[str, int]:
    """一条 cue 的可见字符度量：总宽 / 最长行 / 可见行数。"""
    chars_milli = 0
    max_line_width_milli = 0
    visible_line_count = 0
    for line in text_lines or []:
        width = line_width_milli(line)
        if width > 0:
            visible_line_count += 1
        if width > max_line_width_milli:
            max_line_width_milli = width
        chars_milli += width
    return {
        "charsMilli": chars_milli,
        "maxLineWidthMilli": max_line_width_milli,
        "visibleLineCount": visible_line_count,
    }


def dominant_lang(text_lines: Sequence[str]) -> str:
    """主导文字类别 → 档位：全角 0 → en；假名过半 → ja；全角 ≥ 半角 → zh；否则 en。"""
    full = half = kana = 0
    for line in text_lines or []:
        for ch in strip_decorations(line):
            if _WS.match(ch):
                continue
            if is_full_width(ch):
                full += 1
                if spec.KANA_LO <= ord(ch) <= spec.KANA_HI:
                    kana += 1
            else:
                half += 1
    if full == 0:
        return "en"
    if kana * 2 >= full:
        return "ja"
    if full >= half:
        return "zh"
    return "en"


def _lang_label(lang: str) -> str:
    return "英" if lang == "en" else "日" if lang == "ja" else "中"


def readability_findings(
    cues: Sequence[Mapping[str, Any]], th: Mapping[str, Any]
) -> Dict[str, Any]:
    """旧仓 ``readability.run``：R01–R07 逐 cue 判定（档位由主导文字类别决定）。"""
    findings: List[Dict[str, Any]] = []
    cps_zh = th["cps.zh"]
    cps_en = th["cps.en"]
    cps_ja = th["cps.ja"]
    max_lines = th["line.maxLines"]
    min_chars_milli = th["line.minChars"] * spec.FULL_MILLI
    dur_min = th["duration.min"]
    dur_max = th["duration.max"]
    full_limit_milli = th["line.maxWidthFull"] * spec.FULL_MILLI
    half_limit_milli = th["line.maxWidthHalf"] * spec.HALF_MILLI

    def cps_limit_of(lang: str) -> int:
        if lang == "en":
            return cps_en
        if lang == "ja":
            return cps_ja
        return cps_zh

    def line_limit_milli(lang: str) -> int:
        return half_limit_milli if lang == "en" else full_limit_milli

    for index, cue in enumerate(cues):
        prev = cues[index - 1] if index > 0 else None
        text_lines = cue.get("textLines") or []
        lang = dominant_lang(text_lines)
        measured = measure_cue(text_lines)
        duration = cue["endMs"] - cue["startMs"]

        cps_limit = cps_limit_of(lang)
        if duration > 0 and measured["charsMilli"] > cps_limit * duration:
            findings.append(_finding(
                "readability.cps", index, cue, "cps",
                "<= %s cps（档位 %s）" % (cps_limit, lang),
                "charsMilli=%s / %sms" % (measured["charsMilli"], duration),
                "阅读速度超过口径上限（档位 %s，%s文）" % (lang, _lang_label(lang))))

        line_limit = line_limit_milli(lang)
        if measured["maxLineWidthMilli"] > line_limit:
            findings.append(_finding(
                "readability.line-length", index, cue, "maxLineWidthMilli",
                "<= %s 千分字符（档位 %s）" % (line_limit, lang),
                "最长行 %s" % (measured["maxLineWidthMilli"],),
                "单行长度超过该档行长上限（档位 %s，%s文）" % (lang, _lang_label(lang))))

        if measured["visibleLineCount"] > max_lines:
            findings.append(_finding(
                "readability.too-many-lines", index, cue, "visibleLineCount",
                "<= %s" % (max_lines,), measured["visibleLineCount"],
                "可见行数超过显示行数上限（档位 %s）" % (lang,)))

        if measured["charsMilli"] < min_chars_milli:
            findings.append(_finding(
                "readability.too-few-chars", index, cue, "charsMilli",
                ">= %s 千分字符" % (min_chars_milli,), measured["charsMilli"],
                "可见字符数低于口径下限（档位 %s）" % (lang,)))

        if duration < dur_min:
            findings.append(_finding(
                "readability.duration-short", index, cue, "durationMs",
                ">= %s ms" % (dur_min,), duration,
                "显示时长低于口径下限（档位 %s）" % (lang,), "warn"))

        if duration > dur_max:
            findings.append(_finding(
                "readability.duration-long", index, cue, "durationMs",
                "<= %s ms" % (dur_max,), duration,
                "显示时长超过口径上限（档位 %s）" % (lang,), "warn"))

        if (
            prev is not None
            and _cue_text(cue) == _cue_text(prev)
            and (cue["startMs"] != prev["startMs"] or cue["endMs"] != prev["endMs"])
        ):
            findings.append(_finding(
                "readability.repeated-text", index, cue, "text", "与上一条文本不同",
                "与上一条文本相同（时间不同）", "相邻 cue 文本重复（档位 %s）" % (lang,), "warn"))

    return {"findings": findings, "skipped": [], "implemented": list(spec.READABILITY_RULES)}


# ============================================================ 卫生 S01–S10（core/rules/hygiene.js）
_TAG_RE = re.compile(r"</?([ibu])\s*/?>", re.IGNORECASE)
_ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")
_PLACEHOLDER_RE = re.compile(r"%([0-9]+\$)?[sdf]")
_BRACE_INDEX_RE = re.compile(r"\{[0-9]+\}")
_BRACE_NAMED_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
_FONT_TAG_RE = re.compile(r"<font\b[^>]*>", re.IGNORECASE)
_SDH_BRACKET_RE = re.compile(r"\[music\]", re.IGNORECASE)
_SDH_PAREN_RE = re.compile(r"（[^）]*(?:笑声|掌声|音乐|歌唱|欢呼)[^）]*）")
_SONG_RE = re.compile(r"^♪[\s\S]*♪$")
_REPEATED_PUNCT_RE = re.compile(r"([,.;!?，。！？：；、])\1+")
_NUMERIC_RE = re.compile(r"[0-9]+\.[0-9]+")
_ELLIPSIS_RE = re.compile(r"\.\.\.")
_EN_FULLWIDTH_PUNCT_RE = re.compile(r"[，。！？：；（）]")
_ZH_HALFWIDTH_PUNCT_RE = re.compile(r"[,!?:;]")
_SINGLE_LETTER_BRACE = re.compile(r"^\{[a-z]\}$")

#: 每条规则的 ``field`` 与 severity（旧仓 ``checksFor`` 表；severity 与 spec 一致）。
_CHECK_ORDER: Tuple[Tuple[str, str, str], ...] = (
    ("hygiene.cjk-latin-spacing", "spacing", "warn"),
    ("hygiene.punctuation-width", "punctuation", "warn"),
    ("hygiene.trailing-punctuation", "textEnd", "warn"),
    ("hygiene.unclosed-tag", "tags", "error"),
    ("hygiene.ass-override-residue", "override", "error"),
    ("hygiene.placeholder-residue", "placeholder", "error"),
    ("hygiene.font-tag-residue", "fontTag", "error"),
    ("hygiene.sdh-marker", "sdh", "error"),
    ("hygiene.all-caps", "casing", "warn"),
    ("hygiene.repeated-punctuation", "punctuation", "warn"),
)

#: 报告文案（旧仓 ``COPY``：expected + message；actual 由判定式给出）。
_COPY: Dict[str, Tuple[str, str]] = {
    "hygiene.cjk-latin-spacing": ("CJK 与拉丁/数字之间留空格", "中日韩文字与拉丁/数字直接相邻（排版卫生）"),
    "hygiene.punctuation-width": ("标点宽度与语境一致（中文用全角 / 英文用半角）", "标点宽度与所在语境不符（排版卫生）"),
    "hygiene.trailing-punctuation": ("行尾不使用 。/.", "行尾出现句号（问号、感叹号不属口径范围）"),
    "hygiene.unclosed-tag": ("标签成对闭合且不交叉嵌套", "内联标签未闭合或交叉嵌套"),
    "hygiene.ass-override-residue": ("不含 ASS 覆写块", "残留 ASS 覆写块或花括号未闭合"),
    "hygiene.placeholder-residue": ("不含未替换占位符", "残留未替换的占位符"),
    "hygiene.font-tag-residue": ("不含 <font> 内联样式", "残留 <font> 内联样式标签"),
    "hygiene.sdh-marker": ("不含 SDH 标记", "残留听障辅助标记（方括号 / 圆括号情绪 / 音符）"),
    "hygiene.all-caps": ("非全大写（专有名词、缩写除外）", "整行全大写，超过口径长度下限"),
    "hygiene.repeated-punctuation": ("同类标点不连续重复", "同类标点连续重复达到口径下限"),
}


def cjk_latin_spacing(raw: str, whitelist: Sequence[str]) -> Optional[str]:
    """S01：CJK 与拉丁/数字直接相邻且该拉丁词不在白名单 → 返回该词。"""
    text = raw
    for index in range(len(text) - 1):
        a, b = text[index], text[index + 1]
        latin_start = -1
        if is_cjk(a) and _is_latin_or_digit(b):
            latin_start = index + 1
        elif _is_latin_or_digit(a) and is_cjk(b):
            latin_start = index
            while latin_start > 0 and _is_latin_or_digit(text[latin_start - 1]):
                latin_start -= 1
        if latin_start < 0:
            continue
        end = latin_start
        while end < len(text) and _is_latin_or_digit(text[end]):
            end += 1
        token = text[latin_start:end]
        if token in whitelist:
            continue
        return token
    return None


def punctuation_width(raw: str, whitelist: Sequence[str]) -> Optional[str]:
    """S02：中文语境半角 `, . ! ? : ;`，或英文语境全角标点 → 返回该标点。"""
    if any(is_han(ch) for ch in raw):
        text = raw
        for token in whitelist:
            text = text.replace(token, "")
        text = _NUMERIC_RE.sub("", text)
        text = _ELLIPSIS_RE.sub("", text)
        match = _ZH_HALFWIDTH_PUNCT_RE.search(text)
        return match.group(0) if match else None
    match = _EN_FULLWIDTH_PUNCT_RE.search(raw)
    return match.group(0) if match else None


def trailing_punctuation(raw: str, whitelist: Sequence[str]) -> Optional[str]:
    """S03：行尾 `。` / `.`（问号感叹号不报；省略号与白名单缩写不报）。"""
    text = str(raw).strip()
    if text.endswith("。"):
        return "。"
    if not text.endswith("."):
        return None
    if text.endswith("..."):
        return None
    for token in whitelist:
        if text.endswith(token):
            return None
    return "."


def unclosed_tag(raw: str) -> Optional[str]:
    """S04：`<i>/<b>/<u>` 未闭合或交叉嵌套；自闭合形态不报。"""
    stack: List[str] = []
    for match in _TAG_RE.finditer(raw):
        tag = match.group(1).lower()
        whole = match.group(0)
        if re.search(r"/\s*>$", whole) and not whole.startswith("</"):
            continue
        if whole.startswith("</"):
            if not stack or stack[-1] != tag:
                return whole
            stack.pop()
        else:
            stack.append(tag)
    if stack:
        return "<%s>" % stack[-1]
    return None


def ass_override_residue(raw: str) -> Optional[str]:
    """S05：非 ASS 输出含 `{\\...}` 覆写块，或花括号未闭合。"""
    match = _ASS_OVERRIDE_RE.search(raw)
    if match:
        return match.group(0)
    depth = 0
    for ch in raw:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            return "}"
    return "{" if depth != 0 else None


def placeholder_residue(raw: str) -> Optional[str]:
    """S06：残留 `%s` / `%1$s` / `{0}` / `{name}`；单字母 `{x}` 不报。"""
    match = _PLACEHOLDER_RE.search(raw)
    if match:
        return match.group(0)
    match = _BRACE_INDEX_RE.search(raw)
    if match:
        return match.group(0)
    for token in _BRACE_NAMED_RE.findall(raw):
        if not _SINGLE_LETTER_BRACE.match(token):
            return token
    return None


def font_tag_residue(raw: str) -> Optional[str]:
    """S07：残留 `<font ...>`。"""
    match = _FONT_TAG_RE.search(raw)
    return match.group(0) if match else None


def sdh_marker(raw: str) -> Optional[str]:
    """S08：SDH 标记 `[music]` / `（笑声）` 类 / `♪`；整条以 `♪` 起止的歌词语境不报。"""
    text = str(raw).strip()
    if len(text) > 2 and _SONG_RE.match(text):
        return None
    match = _SDH_BRACKET_RE.search(raw)
    if match:
        return match.group(0)
    match = _SDH_PAREN_RE.search(raw)
    if match:
        return match.group(0)
    return "♪" if "♪" in raw else None


def all_caps(raw: str, whitelist: Sequence[str], min_length: int) -> Optional[str]:
    """S09：全大写且可见长度 ≥ ``hygiene.allCapsMinLength``（半角字符数）。"""
    visible = re.sub(r"\s", "", strip_decorations(raw))
    if len(visible) < min_length:
        return None
    if not re.search(r"[A-Za-z]", visible):
        return None
    if visible != visible.upper():
        return None
    if visible in whitelist:
        return None
    return visible


def repeated_punctuation(raw: str, min_repeat: int) -> Optional[str]:
    """S10：同类标点连续 ≥ ``hygiene.repeatPunctMin`` 次。"""
    for match in _REPEATED_PUNCT_RE.finditer(raw):
        if len(match.group(0)) >= min_repeat:
            return match.group(0)
    return None


def hygiene_checks(line: str, th: Mapping[str, Any]) -> List[Tuple[str, Optional[str], str, str]]:
    """每条规则的判定式 → ``(rule_id, 命中详情|None, field, severity)``（旧仓 ``checksFor``）。"""
    whitelist = spec.WHITELIST
    details = {
        "hygiene.cjk-latin-spacing": cjk_latin_spacing(line, whitelist),
        "hygiene.punctuation-width": punctuation_width(line, whitelist),
        "hygiene.trailing-punctuation": trailing_punctuation(line, whitelist),
        "hygiene.unclosed-tag": unclosed_tag(line),
        "hygiene.ass-override-residue": ass_override_residue(line),
        "hygiene.placeholder-residue": placeholder_residue(line),
        "hygiene.font-tag-residue": font_tag_residue(line),
        "hygiene.sdh-marker": sdh_marker(line),
        "hygiene.all-caps": all_caps(line, whitelist, th["hygiene.allCapsMinLength"]),
        "hygiene.repeated-punctuation": repeated_punctuation(line, th["hygiene.repeatPunctMin"]),
    }
    return [(rule_id, details[rule_id], field, severity) for rule_id, field, severity in _CHECK_ORDER]


def count_whitelist(cues: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """白名单命中次数（按词计数，只列命中 > 0 的词，键按字典序）。"""
    counts: Dict[str, int] = {}
    for cue in cues:
        for line in cue.get("textLines") or []:
            text = str(line)
            for token in spec.WHITELIST:
                hits = text.count(token)
                if hits > 0:
                    counts[token] = counts.get(token, 0) + hits
    return {key: counts[key] for key in sorted(counts)}


def hygiene_findings(
    cues: Sequence[Mapping[str, Any]], th: Mapping[str, Any]
) -> Dict[str, Any]:
    """旧仓 ``hygiene.run``：逐 cue 逐行判定，同 cue 同规则只报一条。"""
    findings: List[Dict[str, Any]] = []
    for index, cue in enumerate(cues):
        seen = set()
        for line in cue.get("textLines") or []:
            for rule_id, detail, field, severity in hygiene_checks(str(line), th):
                if detail is None:
                    continue
                if rule_id in seen:
                    continue
                seen.add(rule_id)
                expected, message = _COPY[rule_id]
                findings.append(_finding(
                    rule_id, index, cue, field, expected, detail, message, severity))
    return {
        "findings": findings,
        "skipped": [],
        "implemented": list(spec.HYGIENE_RULES),
        "whitelist": count_whitelist(cues),
    }


# ============================================================ 可逆修复（core/fix.js）
_TC_SHAPE = re.compile(r"^([+\-]?)([0-9]{1,4}):([0-9]{1,2}):([0-9]{1,2})([,.])([0-9]{1,4})$")
_TC_FIND = re.compile(r"[+\-]?[0-9]{1,4}:[0-9]{1,2}:[0-9]{1,2}[,.]\d{1,4}")
_TRAILING_WS = re.compile(r"[ \t]+$")
_INDEX_LINE = re.compile(r"^\s*[0-9]+\s*$")
_INDEX_PARTS = re.compile(r"^(\s*)([0-9]+)(\s*)$")


def pad2(value: int) -> str:
    text = str(value)
    return text if len(text) >= 2 else "0" + text


def shape_of(token: str) -> Optional[Dict[str, Any]]:
    """时间码 token 的形态（小时位数 / 分隔符 / 小数位数），用于同形重写。"""
    match = _TC_SHAPE.match(token)
    if not match:
        return None
    return {"hourDigits": len(match.group(2)), "sep": match.group(5), "fracDigits": len(match.group(6))}


def format_ms(ms: int, shape: Mapping[str, Any]) -> str:
    """按原形态（小时位数 / 分隔符 / 小数位数）格式化毫秒值。"""
    absolute = abs(ms)
    hours = absolute // 3600000
    minutes = (absolute % 3600000) // 60000
    seconds = (absolute % 60000) // 1000
    frac = absolute % 1000
    frac_digits = shape["fracDigits"]
    if frac_digits == 1:
        frac_str = str(frac // 100)
    elif frac_digits == 2:
        frac_str = pad2(frac // 10)
    else:
        frac_str = str(frac).rjust(3, "0")
        while len(frac_str) < frac_digits:
            frac_str += "0"
    hours_str = str(hours).rjust(shape["hourDigits"], "0")
    return ("-" if ms < 0 else "") + hours_str + ":" + pad2(minutes) + ":" + pad2(seconds) + shape["sep"] + frac_str


def rewrite_time_line(line: str, start_ms: int, end_ms: int) -> Optional[str]:
    """保留原行的分隔符与小数位数，只换两个时间码的数值；找不到两个 token 返回 None。"""
    matches = [match for match in _TC_FIND.finditer(line)]
    if len(matches) < 2:
        return None
    shape_start = shape_of(matches[0].group(0))
    shape_end = shape_of(matches[1].group(0))
    if not shape_start or not shape_end:
        return None
    first = format_ms(start_ms, shape_start)
    second = format_ms(end_ms, shape_end)
    return (
        line[: matches[0].start()]
        + first
        + line[matches[0].end(): matches[1].start()]
        + second
        + line[matches[1].end():]
    )


def close_tags(line: str) -> Optional[str]:
    """补 `<i>/<b>/<u>` 闭合（只追加闭合标签）；交叉嵌套不可修 → None。"""
    stack: List[str] = []
    for match in _TAG_RE.finditer(line):
        tag = match.group(1).lower()
        whole = match.group(0)
        if re.search(r"/\s*>$", whole) and not whole.startswith("</"):
            continue
        if whole.startswith("</"):
            if not stack or stack[-1] != tag:
                return None
            stack.pop()
        else:
            stack.append(tag)
    if not stack:
        return None
    out = line
    for tag in reversed(stack):
        out += "</%s>" % tag
    return out


def strip_trailing_space(line: str) -> Optional[str]:
    """只删行尾空格/制表符；整行只剩空白时不动（避免改变块结构）。"""
    if not _TRAILING_WS.search(line):
        return None
    after = _TRAILING_WS.sub("", line)
    return None if after == "" else after


def plan_reorder(lines: Sequence[str], cues: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """SRT 序号重编的**保守前提**（不满足就不做）：全 SRT / 块不重叠 / 无块外非空行 / 序号行齐。

    返回 ``{"blocks": [...], "sorted": [...]}``；不满足返回 ``None``。
    """
    if not cues:
        return None
    if any(cue.get("format") != "srt" for cue in cues):
        return None
    blocks: List[Dict[str, Any]] = []
    for cue in cues:
        start = cue.get("sourceLine")
        end = cue.get("endLine", start)
        if end < start:
            end = start
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        if start < 1 or end > len(lines):
            return None
        blocks.append({"cue": cue, "start": start, "end": end})
    covered = [False] * (len(lines) + 1)
    for block in blocks:
        for number in range(block["start"], block["end"] + 1):
            if covered[number]:
                return None
            covered[number] = True
    for number in range(1, len(lines) + 1):
        if lines[number - 1].strip() != "" and not covered[number]:
            return None
    for block in blocks:
        if not _INDEX_LINE.match(lines[block["start"] - 1]):
            return None
    ordered = sorted(
        blocks,
        key=lambda block: (block["cue"]["startMs"], block["cue"].get("index", 0)),
    )
    return {"blocks": blocks, "sorted": ordered}


def apply_fix(
    text: str,
    cues: Sequence[Mapping[str, Any]],
    th: Mapping[str, Any],
    eol: Optional[str] = None,
) -> Dict[str, Any]:
    """旧仓 ``fix.apply``：①去重叠/修间隔 ②行尾空白 ③闭合标签 ④SRT 序号重编。

    纪律：只做白名单内的可逆无损动作；每条规则的违规数不得因修复而增加
    （缩时以 ``duration.min`` 作护栏）；不可修时不产任何记录。
    """
    gap_min = th["timing.gapMin"]
    duration_min = th["duration.min"]
    lines = str(text).split("\n")
    edited: Dict[int, str] = {}
    fixes: List[Dict[str, Any]] = []

    def current(number: Any) -> Optional[str]:
        if not isinstance(number, int) or number < 1 or number > len(lines):
            return None
        return edited[number] if number in edited else lines[number - 1]

    def set_line(number: int, content: str) -> None:
        edited[number] = content

    for index in range(1, len(cues)):
        prev, cur = cues[index - 1], cues[index]
        gap = cur["startMs"] - prev["endMs"]
        if gap >= gap_min:
            continue
        desired = cur["startMs"] - gap_min
        if not (desired > prev["startMs"] and desired < prev["endMs"]):
            continue
        if desired - prev["startMs"] < duration_min:
            continue
        before = current(prev.get("timeLine"))
        if before is None:
            continue
        after = rewrite_time_line(before, prev["startMs"], desired)
        if after is None or after == before:
            continue
        set_line(prev["timeLine"], after)
        overlap = gap < 0
        fixes.append({
            "ruleId": "fix.trim-overlap" if overlap else "fix.fill-gap",
            "line": prev["timeLine"],
            "action": "trim-overlap" if overlap else "fill-gap",
            "before": before,
            "after": after,
        })

    for number in range(1, len(lines) + 1):
        before = current(number)
        if before is None:
            continue
        after = strip_trailing_space(before)
        if after is None:
            continue
        set_line(number, after)
        fixes.append({
            "ruleId": "fix.strip-trailing-space",
            "line": number,
            "action": "strip-trailing-space",
            "before": before,
            "after": after,
        })

    for cue in cues:
        numbers = cue.get("textLineNumbers") or []
        texts = cue.get("textLines") or []
        for index, raw in enumerate(texts):
            number = numbers[index] if index < len(numbers) else None
            before = current(number)
            if before is None:
                continue
            after = close_tags(before)
            if after is None or after == before:
                continue
            set_line(number, after)
            fixes.append({
                "ruleId": "fix.close-tag",
                "line": number,
                "action": "close-tag",
                "before": before,
                "after": after,
            })

    edited_lines = [current(number) or "" for number in range(1, len(lines) + 1)]
    plan = plan_reorder(edited_lines, cues)
    out = edited_lines
    if plan:
        blocks, ordered = plan["blocks"], plan["sorted"]
        already_ordered = all(ordered[index] is blocks[index] for index in range(len(blocks)))
        index_ok = True
        for position, block in enumerate(blocks):
            parts = _INDEX_PARTS.match(edited_lines[block["start"] - 1])
            if not parts or int(parts.group(2)) != position + 1:
                index_ok = False
                break
        if not already_ordered or not index_ok:
            trailing_blanks = 0
            for index in range(len(edited_lines) - 1, -1, -1):
                if edited_lines[index] != "":
                    break
                trailing_blanks += 1
            rebuilt: List[str] = []
            moved: List[Dict[str, Any]] = []
            for position, block in enumerate(ordered):
                chunk = list(edited_lines[block["start"] - 1: block["end"]])
                parts = _INDEX_PARTS.match(chunk[0])
                old_number = int(parts.group(2)) if parts else None
                if parts:
                    chunk[0] = parts.group(1) + str(position + 1) + parts.group(3)
                if old_number != position + 1 or block["start"] != blocks[position]["start"]:
                    moved.append({"block": block, "oldNumber": old_number, "newNumber": position + 1})
                if position > 0:
                    rebuilt.append("")
                rebuilt.extend(chunk)
            rebuilt.extend([""] * trailing_blanks)
            out = rebuilt
            for entry in moved:
                fixes.append({
                    "ruleId": "fix.renumber-index",
                    "line": entry["block"]["start"],
                    "action": "renumber-index",
                    "before": edited_lines[entry["block"]["start"] - 1],
                    "after": "序号 %s → %s" % (entry["oldNumber"], entry["newNumber"]),
                })

    result = "\n".join(out)
    if eol == "crlf":
        result = result.replace("\n", "\r\n")
    return {"fixes": fixes, "text": result}


# ============================================================ 编排（旧仓 pipeline.runOne 判定面）
def run_all(
    cues: Sequence[Mapping[str, Any]],
    th: Mapping[str, Any],
    declared: Optional[Mapping[str, Any]] = None,
    diagnostics: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """一次体检的判定面组合：时序 + 可读性 + 卫生（finding 按 ``(line, ruleId, field)`` 排序）。"""
    timing = timing_findings(cues, th, declared, diagnostics)
    readability = readability_findings(cues, th)
    hygiene = hygiene_findings(cues, th)
    findings = sort_findings(
        list(timing["findings"]) + list(readability["findings"]) + list(hygiene["findings"])
    )
    skipped = list(timing["skipped"]) + list(readability["skipped"])
    return {
        "findings": findings,
        "skipped": skipped,
        "whitelist": hygiene["whitelist"],
        "driftFit": timing["driftFit"],
        "implemented": {
            "timing": timing["implemented"],
            "readability": readability["implemented"],
            "hygiene": hygiene["implemented"],
        },
    }