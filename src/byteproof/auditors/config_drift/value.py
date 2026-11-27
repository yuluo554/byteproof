"""值族代数（旧仓 ``internal/value`` 的判定子集）。

- **精确有理数**（``Fraction``）参与所有比较，比较路径上不出现浮点；
- quantity：K8s apimachinery 文法（``Ki…Ei`` = 1024ⁿ；``n u m k M G T P E`` = 10ⁿ；指数与后缀互斥）；
  ``MB`` / ``MiB`` 这类非 K8s 字节单位 -> ``ambiguous_unit_family``（绝不静默判等）；
- duration：Go ``time.ParseDuration`` 文法（``ns us µs μs ms s m h``，可组合）；
- decimal：精确十进制（``1.0 ≡ 1``、``1e3 ≡ 1000``）；
- bool：YAML 1.1 plain 标量族；
- null：absent / explicit null / empty string 三态分开。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

FAMILY_QUANTITY = "quantity"
FAMILY_DURATION = "duration"
FAMILY_DECIMAL = "decimal"
FAMILY_BOOL = "bool"
FAMILY_NULL = "null"
FAMILY_STRING = "string"
FAMILY_UNKNOWN = "unknown"

REASON_AMBIGUOUS_UNIT = "ambiguous_unit_family"
REASON_UNEVALUATED = "unevaluated_expression"
REASON_UNKNOWN_FAMILY = "unknown_family"

BINARY_SUFFIX = {"Ki": 1, "Mi": 2, "Gi": 3, "Ti": 4, "Pi": 5, "Ei": 6}
DECIMAL_SUFFIX = {"n": -9, "u": -6, "m": -3, "": 0, "k": 3, "M": 6, "G": 9, "T": 12, "P": 15, "E": 18}
AMBIGUOUS_BYTES = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB")
DURATION_UNITS = {
    "ns": Fraction(1),
    "us": Fraction(1000),
    "µs": Fraction(1000),
    "μs": Fraction(1000),
    "ms": Fraction(1000000),
    "s": Fraction(1000000000),
    "m": Fraction(60000000000),
    "h": Fraction(3600000000000),
}
YAML11_BOOL = {
    "y": True, "yes": True, "on": True, "true": True,
    "n": False, "no": False, "off": False, "false": False,
}


class ValueError_(ValueError):
    """值无法按声明族解析（输入不合法，退出码 2）。"""


class Indeterminate(Exception):
    """一等结果：不可判定（携带原因码）。"""

    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Canonical:
    family: str
    text: str = ""
    rat: Optional[Fraction] = None
    ns: Optional[Fraction] = None
    boolean: Optional[bool] = None
    state: str = ""

    def key(self):
        return (self.family, self.rat, self.ns, self.boolean, self.state, self.text)


def _is_numeric(text):
    if not text:
        return False
    try:
        Fraction(text)
        return True
    except (ValueError, ZeroDivisionError):
        return False


def parse_quantity(text):
    raw = str(text).strip()
    if not raw:
        raise ValueError_("empty quantity")
    original = raw
    sign = 1
    if raw[0] in "+-":
        if raw[0] == "-":
            sign = -1
        raw = raw[1:]
    if not raw:
        raise ValueError_("quantity has sign but no number")
    for suffix in AMBIGUOUS_BYTES:
        if raw.endswith(suffix) and _is_numeric(raw[: len(raw) - len(suffix)]):
            raise Indeterminate(REASON_AMBIGUOUS_UNIT, raw)

    number = raw
    suffix = ""
    exponent = ""
    for index, char in enumerate(raw):
        if char in "eE":
            number = raw[:index]
            exponent = raw[index + 1:]
            break
    if not exponent:
        for candidate in sorted(BINARY_SUFFIX, key=len, reverse=True):
            if raw.endswith(candidate):
                number, suffix = raw[: len(raw) - len(candidate)], candidate
                break
        else:
            for candidate in sorted((item for item in DECIMAL_SUFFIX if item), key=len, reverse=True):
                if raw.endswith(candidate):
                    number, suffix = raw[: len(raw) - len(candidate)], candidate
                    break
    if exponent and suffix:
        raise ValueError_("exponent and suffix are mutually exclusive: " + str(text))
    try:
        value = Fraction(number) if number else Fraction(0)
    except (ValueError, ZeroDivisionError):
        raise ValueError_("bad quantity number: " + original)
    if exponent:
        try:
            exponent_value = int(exponent)
        except ValueError:
            raise ValueError_("bad exponent: " + str(text))
        value = value * (Fraction(10) ** exponent_value)
    elif suffix in BINARY_SUFFIX:
        value = value * (Fraction(1024) ** BINARY_SUFFIX[suffix])
    elif suffix in DECIMAL_SUFFIX:
        value = value * (Fraction(10) ** DECIMAL_SUFFIX[suffix])
    return sign * value


def parse_duration(text):
    raw = str(text).strip()
    if not raw:
        raise ValueError_("empty duration")
    sign = 1
    if raw[0] in "+-":
        if raw[0] == "-":
            sign = -1
        raw = raw[1:]
    if raw in ("0", "0s"):
        return Fraction(0)
    if not raw:
        raise ValueError_("duration has sign but no value")
    total = Fraction(0)
    index = 0
    while index < len(raw):
        start = index
        dot = False
        digits = 0
        while index < len(raw):
            char = raw[index]
            if char.isdigit():
                digits += 1
                index += 1
                continue
            if char == "." and not dot:
                dot = True
                index += 1
                continue
            break
        if digits == 0:
            raise ValueError_("duration: expected number at offset %d: %s" % (start, text))
        number = raw[start:index]
        unit_start = index
        while index < len(raw) and not raw[index].isdigit() and raw[index] != ".":
            index += 1
        unit = raw[unit_start:index]
        if unit not in DURATION_UNITS:
            raise ValueError_("duration: unknown unit %r in %s" % (unit, text))
        total += Fraction(number) * DURATION_UNITS[unit]
    return sign * total


def parse_decimal(text):
    try:
        return Fraction(str(text).strip())
    except (ValueError, ZeroDivisionError):
        raise ValueError_("bad decimal: %r" % (text,))


def parse_bool(text):
    value = YAML11_BOOL.get(str(text).strip().casefold())
    if value is None:
        raise ValueError_("bad bool: %r" % (text,))
    return value


def canonicalize(node, family=None):
    """把 subject 里的值节点 -> Canonical；不可判定抛 Indeterminate。"""
    if node is None:
        return Canonical(FAMILY_NULL, state="absent")
    if not isinstance(node, dict):
        raise ValueError_("值节点必须是对象或 null")
    declared = family or node.get("family")
    if declared == FAMILY_NULL:
        state = node.get("state", "null")
        if state not in ("absent", "null", "empty"):
            raise ValueError_("null 的 state 必须是 absent/null/empty")
        return Canonical(FAMILY_NULL, state=state)
    raw = node.get("raw")
    if raw is None:
        raw = node.get("value")
    if raw is None:
        raise ValueError_("值节点缺少 raw/value")
    if declared == FAMILY_UNKNOWN:
        raise Indeterminate(node.get("reason", REASON_UNKNOWN_FAMILY), str(raw))
    if declared == FAMILY_STRING:
        return Canonical(FAMILY_STRING, text=str(raw))
    if declared == FAMILY_QUANTITY:
        return Canonical(FAMILY_QUANTITY, text=str(raw), rat=parse_quantity(raw))
    if declared == FAMILY_DURATION:
        ns = parse_duration(raw)
        return Canonical(FAMILY_DURATION, text=str(raw), ns=ns)
    if declared == FAMILY_DECIMAL:
        return Canonical(FAMILY_DECIMAL, text=str(raw), rat=parse_decimal(raw))
    if declared == FAMILY_BOOL:
        return Canonical(FAMILY_BOOL, text=str(raw), boolean=parse_bool(raw))
    raise ValueError_("未知值族：%r" % (declared,))


def compare(left, right):
    """返回 ``(equal, indeterminate_reason)``；不可判定由 ``canonicalize`` 抛。"""
    if left.family != right.family:
        return False, None
    if left.family in (FAMILY_QUANTITY, FAMILY_DECIMAL):
        return left.rat == right.rat, None
    if left.family == FAMILY_DURATION:
        return left.ns == right.ns, None
    if left.family == FAMILY_BOOL:
        return left.boolean == right.boolean, None
    if left.family == FAMILY_NULL:
        return left.state == right.state, None
    return left.text == right.text, None