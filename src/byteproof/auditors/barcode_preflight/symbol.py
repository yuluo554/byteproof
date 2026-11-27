"""M2：符号可行性（字符集 ⊆ / 长度 ∈ / 模式可覆盖 / 容量 / 校验位）。

profile 由输入层给出（``subject.profiles`` = ``symbol_profiles.json`` 的 ``symbols``）。
三段判定照搬旧仓：字符集并集必须覆盖每个字符；长度必须落在声明区间；模式按
``priority`` 贪心切分（同模式合并）。容量与校验位按 profile 的 ``modules`` /
``checksum`` 声明计算。

未核降级：派生自 ``status=unverified`` 条目的 error 在 ``strict_thresholds`` 关闭时
降为 warn。
"""

from __future__ import annotations

from . import spec
from .gs1 import check_digit, is_valid


def _charset_chars(entry) -> set:
    if "characters" in entry:
        return set(str(entry["characters"]))
    chars = set()
    for low, high in entry.get("ranges") or []:
        for code in range(int(low), int(high) + 1):
            chars.add(chr(code))
    return chars


def coverage(profile) -> set:
    covered = set()
    for entry in (profile.get("charsets") or {}).values():
        covered |= _charset_chars(entry)
    return covered


def _status(entry) -> str:
    return str(entry.get("status") or spec.THRESHOLD_NOT_APPLICABLE)


def _downgrade(severity, entries, strict):
    if severity != "error":
        return severity
    if strict:
        return severity
    if any(_status(entry) == spec.THRESHOLD_UNVERIFIED for entry in entries):
        return "warn"
    return severity


def _finding(rule_id, severity, observed, target, evidence, fix=None, module="M2", source_id=None):
    return {
        "rule_id": rule_id,
        "id": source_id or rule_id,
        "severity": severity,
        "observed": observed,
        "target": target,
        "evidence": evidence,
        "threshold_status": (
            spec.THRESHOLD_UNVERIFIED
            if evidence.get("threshold_status") == spec.THRESHOLD_UNVERIFIED
            else spec.THRESHOLD_NOT_APPLICABLE
        ),
        "fix": fix,
        "module": module,
    }


def _modes_for(profile):
    return sorted(profile.get("modes") or [], key=lambda item: int(item.get("priority", 99)))


def _mode_covers(charsets, mode, char):
    entry = charsets.get(mode.get("charset"), {})
    return char in _charset_chars(entry)


def encoding_plan(text, profile):
    """贪心切分：按 priority 选第一个能覆盖当前位置的模式，同模式合并。"""
    charsets = profile.get("charsets") or {}
    modes = _modes_for(profile)
    segments = []
    cursor = 0
    while cursor < len(text):
        chosen = None
        take = 0
        for mode in modes:
            group = int(mode.get("group_size", 1))
            min_run = int(mode.get("min_run", 1))
            if not _mode_covers(charsets, mode, text[cursor]):
                continue
            available = len(text) - cursor
            if mode.get("requires_full_groups"):
                take = (available // group) * group
                if take < max(group, min_run):
                    continue
            else:
                run = 0
                while cursor + run < len(text) and _mode_covers(charsets, mode, text[cursor + run]):
                    run += 1
                take = run
                if take < min_run:
                    continue
            chosen = mode
            break
        if chosen is None:
            return None
        if segments and segments[-1]["mode"] == chosen["name"]:
            segments[-1]["text"] += text[cursor : cursor + take]
        else:
            segments.append({"mode": chosen["name"], "text": text[cursor : cursor + take]})
        cursor += take
    return segments


def _bits_for(segments, profile):
    modes = {mode["name"]: mode for mode in _modes_for(profile)}
    bits = 0
    for segment in segments:
        mode = modes[segment["mode"]]
        group = int(mode.get("group_size", 1))
        groups = (len(segment["text"]) + group - 1) // group
        bits += int(mode.get("header_bits", 0)) + int(mode.get("count_bits", 0))
        bits += groups * int(mode.get("group_bits", 8))
    return bits


def _codewords_for(segments, profile):
    modes = {mode["name"]: mode for mode in _modes_for(profile)}
    data = 0
    for segment in segments:
        mode = modes[segment["mode"]]
        group = max(1, int(mode.get("group_size", 1)))
        data += (len(segment["text"]) + group - 1) // group
    return data


def _retail_value(profile, value, identifier):
    gtin_map = profile.get("gtin_map")
    if not gtin_map:
        return value, None
    source = value if value is not None else identifier
    if source is None:
        return None, "retail-gtin 需要 identifier 或元素串里的 GTIN"
    target = int(gtin_map.get("target_length", 13))
    padding = int(gtin_map.get("zero_padding_width", 0))
    text = str(source)
    if len(text) == target:
        return text, None
    if len(text) == target + padding and text.startswith("0" * padding):
        return text[padding:], None
    return text, "GTIN 长度 %d 不能映射到 %d" % (len(text), target)


def assess(profiles, symbol, value=None, identifier=None, strict=False):
    """返回 ``(findings, skipped, evidence)``。``value`` 是数据层取到的载荷。"""
    if not isinstance(profiles, dict):
        raise ValueError("subject.profiles 必须是对象")
    if symbol not in profiles:
        return (
            [
                _finding(
                    spec.RULE_SYMBOL_UNSUPPORTED,
                    "warn",
                    "符号 %r 不在已装载的 profile 表内" % (symbol,),
                    "symbol.%s" % symbol,
                    {"skipped": "symbol_unsupported:%s" % symbol, "known": sorted(profiles)},
                    source_id="symbol_unsupported",
                )
            ],
            ["symbol_unsupported:" + str(symbol)],
            {},
        )
    profile = profiles[symbol]
    findings = []

    if profile.get("data_shape") == "retail-gtin":
        value, problem = _retail_value(profile, value, identifier)
        if problem:
            findings.append(
                _finding(
                    spec.RULE_SYMBOL_LENGTH,
                    "error",
                    problem,
                    "symbol.%s.gtin" % symbol,
                    {"symbol": symbol},
                    source_id="gtin_length",
                )
            )
            return findings, [], {}

    text = "" if value is None else str(value)
    charsets = profile.get("charsets") or {}
    covered = coverage(profile)
    for index, char in enumerate(text):
        if char not in covered:
            findings.append(
                _finding(
                    spec.RULE_SYMBOL_CHARSET,
                    _downgrade("error", list(charsets.values()), strict),
                    "字符 %r 不被 %s 的任何字符集覆盖" % (char, symbol),
                    "symbol.%s.charset" % symbol,
                    {"symbol": symbol, "offset": index, "char": char},
                    source_id="charset_not_covered",
                )
            )
            break

    length = profile.get("length") or {}
    kind = length.get("kind")
    if kind == "exact" and len(text) != int(length.get("exact", -1)):
        findings.append(
            _finding(
                spec.RULE_SYMBOL_LENGTH,
                _downgrade("error", [length], strict),
                "%s 需要恰好 %s 个字符，实际 %d" % (symbol, length.get("exact"), len(text)),
                "symbol.%s.length" % symbol,
                {"symbol": symbol, "expected": length.get("exact"), "observed": len(text)},
                source_id="length_out_of_range",
            )
        )
    elif kind == "range":
        low, high = int(length.get("min", 0)), int(length.get("max", 0))
        if len(text) < low or len(text) > high:
            findings.append(
                _finding(
                    spec.RULE_SYMBOL_LENGTH,
                    _downgrade("error", [length], strict),
                    "%s 的长度必须在 %d..%d，实际 %d" % (symbol, low, high, len(text)),
                    "symbol.%s.length" % symbol,
                    {"symbol": symbol, "min": low, "max": high, "observed": len(text)},
                    source_id="length_out_of_range",
                )
            )

    plan = encoding_plan(text, profile) if text else []
    if text and plan is None:
        findings.append(
            _finding(
                spec.RULE_SYMBOL_PLAN,
                "error",
                "无法用已声明的模式覆盖全部字符",
                "symbol.%s.plan" % symbol,
                {"symbol": symbol},
                source_id="encoding_plan_unavailable",
            )
        )
    elif plan:
        findings.append(
            _finding(
                spec.RULE_SYMBOL_PLAN,
                "info",
                "编码计划：%s" % " + ".join("%s(%d)" % (item["mode"], len(item["text"])) for item in plan),
                "symbol.%s.plan" % symbol,
                {"symbol": symbol, "segments": [{"mode": item["mode"], "text": item["text"]} for item in plan]},
                source_id="encoding_plan",
            )
        )

    modules = profile.get("modules") or {}
    module_kind = modules.get("kind")
    module_evidence = {"kind": module_kind}
    if module_kind == "fixed":
        module_evidence["total"] = modules.get("total")
    elif module_kind == "code128" and plan:
        data = _codewords_for(plan, profile)
        total = (
            int(modules.get("start_modules", 11))
            + int(modules.get("modules_per_codeword", 11)) * (data + 1)
            + int(modules.get("stop_modules", 13))
        )
        module_evidence.update({"data_codewords": data, "total": total})
    elif module_kind == "matrix" and plan:
        bits = _bits_for(plan, profile)
        bits_per = int(modules.get("bits_per_codeword", 8))
        needed = (bits + bits_per - 1) // bits_per
        table = sorted(modules.get("table") or [], key=lambda row: int(row.get("side", 0)))
        fit = next((row for row in table if int(row.get("data_codewords", 0)) >= needed), None)
        module_evidence.update({"bits": bits, "codewords": needed})
        if fit is None:
            findings.append(
                _finding(
                    spec.RULE_SYMBOL_CAPACITY,
                    _downgrade("error", [modules], strict),
                    "%s 容量不足：需要 %d 个数据码字，表内最大 %s"
                    % (symbol, needed, table[-1]["data_codewords"] if table else "-"),
                    "symbol.%s.capacity" % symbol,
                    {"symbol": symbol, "needed": needed, "table": table},
                    source_id="capacity_exceeded",
                )
            )
        else:
            module_evidence["side"] = fit["side"]

    checksum = profile.get("checksum") or {}
    checksum_kind = checksum.get("kind")
    if checksum_kind == "gs1" and text:
        try:
            ok = is_valid(text)
        except ValueError:
            ok = False
        if not ok:
            findings.append(
                _finding(
                    spec.RULE_SYMBOL_CHECKSUM,
                    "error",
                    "%s 的 GS1 校验位不正确（%r）" % (symbol, text),
                    "symbol.%s.checksum" % symbol,
                    {"symbol": symbol, "value": text},
                    source_id="checksum_mismatch",
                )
            )
    elif checksum_kind == "mod103" and text:
        total = 0
        for index, char in enumerate(text):
            total += (ord(char) + index + 1)
        module_evidence["mod103"] = total % 103
    elif checksum_kind in ("reedsolomon", "mod103"):
        module_evidence["checksum"] = checksum_kind

    if module_evidence.get("total") is not None:
        findings.append(
            _finding(
                spec.RULE_SYMBOL_PLAN,
                "info",
                "%s 模块总数：%s" % (symbol, module_evidence["total"]),
                "symbol.%s.modules" % symbol,
                {"symbol": symbol, "modules": module_evidence},
                source_id="module_total",
            )
        )
    return findings, [], {"symbol": symbol, "length": len(text), "plan": plan or [], "modules": module_evidence}