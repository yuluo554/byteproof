"""模型 / 身份 / 框架识别 / JUnit 解析（迁自 10-19-testdeck 的 ``model`` / ``identity`` /
``framework`` / ``junit``）。

**输入边界**：``parse_xml_text`` 收**文本**、``parse_xml_bytes`` 收**字节**
（输入层读文件；器官零文件 IO）。两者都先过安全护栏：超过 ``spec.MAX_XML_CHARS`` 或含
``<!DOCTYPE`` / ``<!ENTITY`` 一律拒（``bad_xml`` + ``detail=oversize|dtd_forbidden``）——
旧仓直接 ``ET.iterparse`` 不可信产物，本器官把实体扩展面显式关掉（见 docs §7）。

纪律沿用旧仓：``bad_*`` 原因码逐文件显式、单项降级（``bad_time`` / ``missing_name`` /
``started_at_missing`` / ``bad_commit``）不整文件报废；身份键缺 ``name`` 的用例不落库
**但仍计入元素重数**；``commit_sha`` 非 40 位十六进制记空串并降级；框架判不出写
``unknown``（不猜）。
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import spec

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_ENCODING_RE = re.compile(rb"""<\?xml[^>]*encoding=["']([A-Za-z0-9._\-]+)["']""")


# ============================================================ model
def seconds_to_ms(value: Any) -> Optional[int]:
    """XML 十进制秒 → 整数毫秒（ROUND_HALF_UP）；缺失 → ``None``；非法 → ``ValueError``。"""
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        seconds = Decimal(text)
    except InvalidOperation:
        raise ValueError("not a decimal number: %r" % (value,))
    if not seconds.is_finite():
        raise ValueError("not a finite number: %r" % (value,))
    return int((seconds * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def is_counted(status: str) -> bool:
    """该状态是否进入 fail_rate / flaky_score 的统计面。"""
    return status in spec.COUNTED_STATUSES


def validate_status(status: str) -> str:
    if status not in spec.STATUSES:
        raise ValueError("unknown status: %r" % (status,))
    return status


def as_fraction(value: Any) -> Fraction:
    """十进制字符串 / ``Decimal`` → 精确 ``Fraction``；**float 一律拒绝**。"""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        raise TypeError("阈值不得用 float 传入（浮点会让边界判定掷硬币）")
    return Fraction(str(value))


def render_exact(value: Any) -> Optional[str]:
    """``Fraction`` → 终止十进制串；不终止用 ``p/q``；``None`` → ``None``。"""
    if value is None:
        return None
    if not isinstance(value, Fraction):
        value = as_fraction(value)
    if value.denominator == 1:
        return str(value.numerator)
    reduced = value.denominator
    for prime in spec.TERMINATING_PRIMES:
        while reduced % prime == 0:
            reduced //= prime
    if reduced != 1:
        return "%d/%d" % (value.numerator, value.denominator)
    from decimal import localcontext

    with localcontext() as ctx:
        ctx.prec = spec.RENDER_PRECISION
        dec = Decimal(value.numerator) / Decimal(value.denominator)
    return format(dec, "f")


def mean_fraction(total: int, count: int) -> Optional[Fraction]:
    """``total / count``；``count == 0`` → ``None``（0/0 无定义，不当 0）。"""
    if not count:
        return None
    return Fraction(int(total), int(count))


# ============================================================ identity
@dataclass(frozen=True, order=True)
class RunIdentity:
    """run 身份 = ``(branch, commit_sha, ci_run_id)``；未知值写空串（NULL 会绕过 upsert）。"""

    branch: str = ""
    commit_sha: str = ""
    ci_run_id: str = ""

    def __post_init__(self):
        for name in ("branch", "commit_sha", "ci_run_id"):
            if getattr(self, name) is None:
                raise ValueError("%s must be a string (use '' for unknown)" % name)
        if self.commit_sha and not _HEX40_RE.match(self.commit_sha):
            raise ValueError(
                "commit_sha must be 40 lowercase hex chars or '' (got %r)" % (self.commit_sha,)
            )

    @property
    def key(self):
        return (self.branch, self.commit_sha, self.ci_run_id)


@dataclass(frozen=True, order=True)
class CaseIdentity:
    """用例身份 = ``(suite_name, classname, name)``；参数化用例保留完整参数串。"""

    suite_name: str = ""
    classname: str = ""
    name: str = ""

    def __post_init__(self):
        for name in ("suite_name", "classname", "name"):
            if getattr(self, name) is None:
                raise ValueError("%s must be a string (use '' for unknown)" % name)
        if not self.name:
            raise ValueError("case name must not be empty")

    @property
    def key(self):
        return (self.suite_name, self.classname, self.name)

    @property
    def display(self):
        parts = [part for part in (self.suite_name, self.classname, self.name) if part]
        return " :: ".join(parts)


# ============================================================ framework
def _match_hint(text: str, hints: Sequence[Tuple[str, str]]) -> Optional[str]:
    lowered = (text or "").lower()
    if not lowered:
        return None
    for needle, name in hints:
        if needle in lowered:
            return name
    return None


def detect_framework(file_name: str = "", names: Sequence[str] = (),
                     properties: Sequence[str] = ()) -> str:
    """框架识别（suite/根 name → properties → 文件名，短路）；判不出 ``unknown``。"""
    for value in names:
        hit = _match_hint(value, spec.NAME_HINTS)
        if hit:
            return hit
    for value in properties:
        hit = _match_hint(value, spec.PROPERTY_HINTS)
        if hit:
            return hit
    base = str(file_name).replace("\\", "/").rsplit("/", 1)[-1]
    return _match_hint(base, spec.FILENAME_HINTS) or spec.FRAMEWORK_UNKNOWN


# ============================================================ junit
def _localname(tag: Any) -> str:
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.rsplit("}", 1)[-1]
    return str(tag)


def _first_attr(elem, names: Sequence[str]) -> str:
    for name in names:
        raw = elem.get(name)
        if raw:
            return str(raw).strip()
    return ""


def _stack_first_line(child) -> str:
    text = child.text or ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _case_kind(children) -> Tuple[str, str, str, str, str]:
    """一个 testcase 的子元素 → ``(kind, status, failure_type, message, stack)``。

    ``kind`` 是元素标签（``failure`` / ``error`` 分桶），四态把它们合并成 ``fail``——
    元素重数按标签算，否则与框架声明值对不上。
    """
    by_tag = {"failure": spec.STATUS_FAIL, "error": spec.STATUS_FAIL, "skipped": spec.STATUS_SKIP}
    for child in children:
        tag = _localname(child.tag)
        if tag not in by_tag:
            continue
        return (
            tag,
            by_tag[tag],
            (child.get("type") or "").strip(),
            child.get("message") or "",
            _stack_first_line(child),
        )
    return "", spec.STATUS_PASS, "", "", ""


def _blank_outcome(display_path: str, reason: str = "", detail: str = "") -> Dict[str, Any]:
    return {
        "display_path": display_path,
        "framework": spec.FRAMEWORK_UNKNOWN,
        "reason": reason,
        "detail": detail,
        "branch": "",
        "commit_sha": "",
        "ci_run_id": "",
        "started_at": "",
        "suites": [],
        "degraded": {},
    }


def _count_degraded(outcome: Dict[str, Any], reason: str, how_many: int = 1) -> None:
    outcome["degraded"][reason] = outcome["degraded"].get(reason, 0) + how_many


def _absorb_metadata(outcome: Dict[str, Any], elem) -> None:
    if not outcome["branch"]:
        outcome["branch"] = _first_attr(elem, ("branch",))
    if not outcome["commit_sha"]:
        outcome["commit_sha"] = _first_attr(elem, ("commit", "commit_sha"))
    if not outcome["ci_run_id"]:
        outcome["ci_run_id"] = _first_attr(elem, ("ci_run_id", "ci_run-id", "run_id"))
    if not outcome["started_at"]:
        outcome["started_at"] = _first_attr(elem, ("timestamp",))


def _new_suite(elem, outcome: Dict[str, Any]) -> Dict[str, Any]:
    suite = {"name": (elem.get("name") or "").strip(), "tests": 0, "failures": 0,
             "errors": 0, "skipped": 0, "time_ms": None, "cases": []}
    raw_time = elem.get("time")
    if raw_time not in (None, ""):
        try:
            suite["time_ms"] = seconds_to_ms(raw_time)
        except ValueError:
            _count_degraded(outcome, spec.DEGRADED_BAD_TIME)
    return suite


def _absorb_case(elem, outcome: Dict[str, Any], suite_name: str):
    kind, status, failure_type, failure_message, stack = _case_kind(list(elem))
    name = elem.get("name")
    if not name:
        _count_degraded(outcome, spec.DEGRADED_MISSING_NAME)
        return None, kind
    raw_time = elem.get("time")
    time_ms = None
    if raw_time not in (None, ""):
        try:
            time_ms = seconds_to_ms(raw_time)
        except ValueError:
            _count_degraded(outcome, spec.DEGRADED_BAD_TIME)
            time_ms = None
    case = {
        "suite_name": suite_name,
        "classname": (elem.get("classname") or "").strip(),
        "name": name,
        "status": status,
        "time_ms": time_ms,
        "failure_type": failure_type,
        "failure_message": failure_message,
        "stack_first_line": stack,
    }
    return case, kind


def _guard(text: str) -> Optional[str]:
    """解析前护栏：长度上限 + 拒 DTD/ENTITY（实体扩展防护）。返回 detail 或 ``None``。"""
    if len(text) > spec.MAX_XML_CHARS:
        return spec.OVERSIZE
    upper = text[:4096].upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in text.upper():
        return spec.DTD_REJECTED
    return None


def parse_xml_text(text: str, file_name: str = "", display_path: str = "") -> Dict[str, Any]:
    """解析 JUnit XML **文本**（永不抛解析异常；失败留原因码 + detail）。"""
    display = display_path or file_name or "<xml>"
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串（字节走 parse_xml_bytes）")
    if text.strip() == "":
        return _blank_outcome(display, spec.NO_TESTSUITE)
    blocked = _guard(text)
    if blocked:
        return _blank_outcome(display, spec.BAD_XML, blocked)
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return _blank_outcome(display, spec.BAD_XML)

    root_tag = _localname(root.tag)
    if root_tag not in ("testsuites", "testsuite"):
        return _blank_outcome(display, spec.NO_TESTSUITE)
    outcome = _blank_outcome(display)
    names: List[str] = []
    properties: List[str] = []
    if root_tag == "testsuites":
        names.append((root.get("name") or "").strip())
        _absorb_metadata(outcome, root)
        suite_elems = [child for child in list(root) if _localname(child.tag) == "testsuite"]
    else:
        suite_elems = [root]

    for elem in suite_elems:
        suite = _new_suite(elem, outcome)
        names.append(suite["name"])
        _absorb_metadata(outcome, elem)
        for child in list(elem):
            tag = _localname(child.tag)
            if tag == "properties":
                for prop in list(child):
                    if _localname(prop.tag) == "property":
                        properties.append(prop.get("name") or "")
            elif tag == "testcase":
                case, kind = _absorb_case(child, outcome, suite["name"])
                suite["tests"] += 1
                if kind == "failure":
                    suite["failures"] += 1
                elif kind == "error":
                    suite["errors"] += 1
                elif kind == "skipped":
                    suite["skipped"] += 1
                if case is not None:
                    suite["cases"].append(case)
        outcome["suites"].append(suite)

    if not outcome["suites"]:
        return _blank_outcome(display, spec.NO_TESTSUITE)
    outcome["framework"] = detect_framework(
        file_name=file_name, names=names, properties=properties)
    if outcome["commit_sha"] and not _HEX40_RE.match(outcome["commit_sha"]):
        _count_degraded(outcome, spec.DEGRADED_BAD_COMMIT)
        outcome["commit_sha"] = ""
    if not outcome["started_at"]:
        _count_degraded(outcome, spec.DEGRADED_STARTED_AT)
    return outcome


def parse_xml_bytes(data: bytes, file_name: str = "", display_path: str = "") -> Dict[str, Any]:
    """字节输入：先按 XML 声明（缺省 UTF-8）严格解码；失败即 ``bad_encoding``（不猜编码）。"""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("输入必须是 bytes / bytearray")
    payload = bytes(data)
    display = display_path or file_name or "<bytes>"
    if payload.strip() == b"":
        return _blank_outcome(display, spec.NO_TESTSUITE)
    if len(payload) > spec.MAX_XML_CHARS:
        return _blank_outcome(display, spec.BAD_XML, spec.OVERSIZE)
    encoding = "utf-8"
    match = _ENCODING_RE.search(payload[:256])
    if match:
        encoding = match.group(1).decode("ascii", "replace")
    try:
        text = payload.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError):
        return _blank_outcome(display, spec.BAD_ENCODING)
    return parse_xml_text(text, file_name=file_name, display_path=display)


def outcome_totals(outcome: Mapping[str, Any]) -> Dict[str, int]:
    """元素重数（定义上就是文件里有什么；框架声明值另有一条通道）。"""
    totals = dict.fromkeys(spec.COUNT_FIELDS, 0)
    for suite in outcome.get("suites", []):
        for name in spec.COUNT_FIELDS:
            totals[name] += int(suite.get(name, 0))
    return totals