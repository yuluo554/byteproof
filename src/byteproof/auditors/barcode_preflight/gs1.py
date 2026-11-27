"""M1：GS1 校验位、元素串解析与四个语义解释器。

字典由输入层给出（``subject.dictionary`` = ``AI -> {title, length, charset,
linters, req, ex, fixed}``）；本模块不读官方表、不联网、不查 GCP（GEPIR 是外部服务，
旧仓也把需要它的 linter 记为「不可判」）。
"""

from __future__ import annotations

import calendar
import re

from . import spec

_BRACKETED = re.compile(r"\(([0-9]{2,4})\)")
_AI_WIDTHS = (2, 3, 4)


# ------------------------------------------------------------------ checksum
def check_digit(data_digits: str) -> str:
    """GS1 校验位（全仓唯一实现）。非数字输入 -> ``ValueError``。"""
    text = _require_digits(data_digits)
    total_length = len(text) + 1
    first_weight = 3 if total_length % 2 == 0 else 1
    total = 0
    for index, char in enumerate(text):
        weight = first_weight if index % 2 == 0 else 4 - first_weight
        total += (ord(char) - ord("0")) * weight
    return str((10 - total % 10) % 10)


def is_valid(full: str) -> bool:
    text = _require_digits(full)
    if len(text) < 2:
        return False
    return check_digit(text[:-1]) == text[-1]


def _require_digits(value) -> str:
    if not isinstance(value, str):
        raise ValueError("需要数字字符串，收到 %r" % (type(value).__name__,))
    if not value:
        raise ValueError("需要非空数字串")
    for char in value:
        if char < "0" or char > "9":
            raise ValueError("非数字字符 %r" % (char,))
    return value


# ------------------------------------------------------------------ elements
def looks_bracketed(text: str) -> bool:
    return isinstance(text, str) and bool(_BRACKETED.search(text))


def _decode_ai(raw, dictionary):
    for width in _AI_WIDTHS:
        if len(raw) >= width and raw[:width] in dictionary:
            return raw[:width], raw[width:]
    return None, raw


def parse_elements(text, dictionary):
    """返回 ``(elements, issues)``；``elements`` = ``[{ai, value}]``。

    ``dictionary`` 的条目形状：``{title, length, charset, linters, req, ex, fixed}``。
    未知 AI / 结构不合法都进 issues，不中止整串（旧仓逐条报）。
    """
    if not isinstance(text, str) or not text:
        raise ValueError("元素串必须是非空字符串")
    if not isinstance(dictionary, dict):
        raise ValueError("subject.dictionary 必须是对象")
    if looks_bracketed(text):
        return _parse_bracketed(text, dictionary)
    return _parse_raw(text, dictionary)


def _parse_bracketed(text, dictionary):
    elements = []
    issues = []
    cursor = 0
    for match in _BRACKETED.finditer(text):
        if match.start() != cursor:
            issues.append({"issue": "malformed", "detail": "括号外出现游离字符", "offset": cursor})
            break
        ai = match.group(1)
        value_start = match.end()
        next_match = _BRACKETED.search(text, value_start)
        end = next_match.start() if next_match else len(text)
        segment = text[value_start:end]
        if ai not in dictionary:
            issues.append({"issue": "unknown_ai", "ai": ai, "value": segment})
        else:
            entry = dictionary[ai]
            length = entry.get("length")
            if entry.get("fixed") and isinstance(length, int) and len(segment) > length:
                issues.append(
                    {
                        "issue": "malformed",
                        "detail": "定长字段后有游离字符",
                        "ai": ai,
                        "offset": value_start + length,
                    }
                )
                segment = segment[:length]
            elements.append({"ai": ai, "value": segment})
        cursor = end
    if cursor != len(text):
        issues.append({"issue": "malformed", "detail": "尾部无法解析", "offset": cursor})
    if not elements and not issues:
        issues.append({"issue": "malformed", "detail": "没有识别到 AI", "offset": 0})
    return elements, issues


def _parse_raw(text, dictionary):
    elements = []
    issues = []
    cursor = 0
    while cursor < len(text):
        ai, rest = _decode_ai(text[cursor:], dictionary)
        if ai is None:
            issues.append({"issue": "unknown_ai", "ai": text[cursor : cursor + 4], "value": text[cursor:]})
            break
        entry = dictionary[ai]
        cursor += len(ai)
        fixed = entry.get("fixed", True)
        length = entry.get("length")
        if fixed and isinstance(length, int):
            value = text[cursor : cursor + length]
            if len(value) < length:
                issues.append({"issue": "malformed", "detail": "定长字段不足", "ai": ai, "offset": cursor})
                break
            cursor += length
        else:
            end = text.find("\x1d", cursor)
            if end < 0:
                end = len(text)
            value = text[cursor:end]
            cursor = end + 1 if end < len(text) else end
        elements.append({"ai": ai, "value": value})
    return elements, issues


# ------------------------------------------------------------------ 语义
def resolve_date(value, kind, century_resolution):
    """返回 ``(status, normalized, detail)``；status ∈ ``{ok, dd00, invalid_date}``。"""
    year_digits = 4 if kind.startswith("yyyy") else 2
    width = year_digits + 4
    if len(value) != width or not value.isdigit():
        return "invalid_date", None, "需要 %d 位数字（YYYYMMDD 形态）" % width
    year_text = value[:year_digits]
    month_text = value[year_digits : year_digits + 2]
    day_text = value[year_digits + 2 :]
    if year_digits == 2:
        year = _expand_two_digit_year(int(year_text), century_resolution)
    else:
        year = int(year_text)
    month = int(month_text)
    day = int(day_text)
    if month < 1 or month > 12:
        return "invalid_date", None, "月份 %02d 不在 01..12" % month
    allows_zero = kind in ("yymmd0", "yyyymmd0")
    max_day = calendar.monthrange(year, month)[1]
    if day == 0:
        if not allows_zero:
            return "invalid_date", None, "该日期类型不允许 DD=00"
        return "dd00", "%04d-%02d-%02d" % (year, month, max_day), "DD=00 表示当月最后一天"
    if day < 1 or day > max_day:
        return "invalid_date", None, "日期 %04d-%02d-%02d 不存在" % (year, month, day)
    return "ok", "%04d-%02d-%02d" % (year, month, day), ""


def _expand_two_digit_year(two_digit, resolution):
    reference = int(resolution["reference_year_yy"])
    window = int(resolution["century_window"])
    centuries = resolution["centuries"]
    offset = two_digit - reference
    if offset >= window + 1:
        century = int(centuries["high"])
    elif offset > -window:
        century = int(centuries["mid"])
    else:
        century = int(centuries["low"])
    return century * 100 + two_digit


def validate_elements(elements, dictionary, century_resolution):
    """逐元素做字符集 / 长度 / csum / 日期；返回 ``(findings, skipped)``。"""
    findings = []
    skipped = []
    for element in elements:
        ai = element["ai"]
        value = element["value"]
        entry = dictionary[ai]
        charset_code = entry.get("charset", "X")
        allowed = spec.CHARSETS.get(charset_code, spec.CHARSETS["X"])[1]
        for index, char in enumerate(value):
            if char not in allowed:
                findings.append(
                    _element_finding(
                        spec.RULE_GS1_CHARSET,
                        "error",
                        "字符 %r 不在 AI %s 的字符集 %s 内" % (char, ai, charset_code),
                        "gs1.ai.%s.charset" % ai,
                        {"ai": ai, "offset": index, "char": char, "charset": charset_code},
                    )
                )
                break
        length = entry.get("length")
        if isinstance(length, int) and len(value) != length:
            findings.append(
                _element_finding(
                    spec.RULE_GS1_LENGTH,
                    "error",
                    "AI %s 需要 %d 位，实际 %d 位" % (ai, length, len(value)),
                    "gs1.ai.%s.length" % ai,
                    {"ai": ai, "expected": length, "observed": len(value)},
                )
            )
        for linter in entry.get("linters") or []:
            if linter == "csum":
                try:
                    valid = is_valid(value)
                except ValueError:
                    valid = False
                if not valid:
                    findings.append(
                        _element_finding(
                            spec.RULE_GS1_CHECKSUM,
                            "error",
                            "AI %s 的校验位不正确（%r）" % (ai, value),
                            "gs1.ai.%s.value" % ai,
                            {"ai": ai, "value": value},
                        )
                    )
            elif linter in spec.DATE_LINTERS:
                status, normalized, detail = resolve_date(value, linter, century_resolution)
                if status == "invalid_date":
                    findings.append(
                        _element_finding(
                            spec.RULE_GS1_DATE,
                            "error",
                            "AI %s 的日期不合法：%s" % (ai, detail),
                            "gs1.ai.%s.value" % ai,
                            {"ai": ai, "value": value, "linter": linter, "detail": detail},
                        )
                    )
            elif linter in ("gcppos1", "gcppos2"):
                skipped.append({"linter": linter, "ai": ai, "reason": "gcp_lookup_unavailable"})
            else:
                skipped.append({"linter": linter, "ai": ai, "reason": "linter_not_implemented"})
    findings.extend(_relationship_findings(elements, dictionary))
    return findings, skipped


def _relationship_findings(elements, dictionary):
    findings = []
    present = {element["ai"] for element in elements}
    for element in elements:
        entry = dictionary[element["ai"]]
        req = entry.get("req") or []
        if req and not any(all(item in present for item in group) for group in req):
            findings.append(
                _element_finding(
                    spec.RULE_GS1_REQUIRED,
                    "error",
                    "AI %s 需要同时出现 %s 之一" % (element["ai"], " / ".join("+".join(group) for group in req)),
                    "gs1.ai.%s.req" % element["ai"],
                    {"ai": element["ai"], "required_groups": req, "present": sorted(present)},
                )
            )
        ex = entry.get("ex") or []
        conflicts = sorted((set(ex) & present) - {element["ai"]})
        if conflicts:
            findings.append(
                _element_finding(
                    spec.RULE_GS1_EXCLUSIVE,
                    "error",
                    "AI %s 不允许与 %s 同时出现" % (element["ai"], ", ".join(conflicts)),
                    "gs1.ai.%s.ex" % element["ai"],
                    {"ai": element["ai"], "conflicts": conflicts},
                )
            )
    return findings


def _element_finding(rule_id, severity, observed, target, evidence):
    return {
        "rule_id": rule_id,
        "id": rule_id,
        "severity": severity,
        "observed": observed,
        "target": target,
        "evidence": evidence,
        "threshold_status": spec.THRESHOLD_NOT_APPLICABLE,
        "fix": None,
        "module": "M1",
    }


def issue_findings(issues):
    findings = []
    for issue in issues:
        if issue["issue"] == "unknown_ai":
            findings.append(
                _element_finding(
                    spec.RULE_GS1_UNKNOWN_AI,
                    "error",
                    "未知 AI %r" % (issue.get("ai"),),
                    "gs1.ai",
                    dict(issue),
                )
            )
        else:
            findings.append(
                _element_finding(
                    spec.RULE_GS1_MALFORMED,
                    "error",
                    "元素串结构不合法：%s" % issue.get("detail", ""),
                    "gs1.element_string",
                    dict(issue),
                )
            )
    return findings