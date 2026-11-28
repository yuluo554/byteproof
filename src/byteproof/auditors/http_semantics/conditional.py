"""T4 ``conditional_evaluate``（1:1 移植自旧仓 ``judgement/conditional.py``）。

Algorithm source: 旧仓 ``plan/03`` §4（steps E1-E5），following RFC 9110 §13.2.2
（Precedence of Preconditions）+ 13.1.1-13.1.4 + 8.8.3.2（comparison rules）。
措辞全部来自 catalogue（= 随包 basis）。

四条纪律（旧仓同款）：
* **Order is the answer.** 首个适用的前置条件决定结果，后面的根本不读。
* **Two comparison functions, not one with a flag.** ``strong_compare`` 给
  ``If-Match``（双方 strong 且逐字节相等），``weak_compare`` 给 ``If-None-Match``
  （``W/`` 标记在解析时剥掉）。
* **坏资源字段是 caller mistake；坏请求日期被忽略。**
* **``*`` 需要当前表示存在。**
"""

from __future__ import annotations

from . import spec
from .errors import JudgementError, invalid_header_value, invalid_input
from .normalise import OWS, first_value, normalise_headers, normalise_method
from .timeparse import parse_time

__all__ = ["evaluate_conditional", "strong_compare", "weak_compare"]

# ``rule_applied`` 值（旧仓 data/README.md §4.10：封闭枚举）。
RULE_NONE = spec.RULE_NONE
RULE_IF_MATCH = spec.RULE_IF_MATCH
RULE_IF_UNMODIFIED_SINCE = spec.RULE_IF_UNMODIFIED_SINCE
RULE_IF_NONE_MATCH = spec.RULE_IF_NONE_MATCH
RULE_IF_MODIFIED_SINCE = spec.RULE_IF_MODIFIED_SINCE

# A precondition that decides 304 is the pair of retrieval methods; a failed
# precondition on any other method is a 412（RFC 9110 §13.1.2）。
SAFE_METHODS = spec.SAFE_METHODS

STATUS_OK = spec.STATUS_OK
STATUS_NOT_MODIFIED = spec.STATUS_NOT_MODIFIED
STATUS_PRECONDITION_FAILED = spec.STATUS_PRECONDITION_FAILED

IF_MATCH = spec.IF_MATCH
IF_UNMODIFIED_SINCE = spec.IF_UNMODIFIED_SINCE
IF_NONE_MATCH = spec.IF_NONE_MATCH
IF_MODIFIED_SINCE = spec.IF_MODIFIED_SINCE

REQUEST_FIELDS = spec.REQUEST_FIELDS

NOT_A_TAG = "entity tag must be a quoted opaque-tag"
NOT_AN_UPPERCASE_WEAK_MARKER = "weak prefix must be exactly W/ (uppercase)"


def _sorted_findings(findings):
    unique = {}
    for finding in findings:
        unique[(finding["code"], finding["detail"])] = finding
    return [unique[key] for key in sorted(unique)]


def _result(rule, status, findings, weak_used):
    return {
        "explain": _sorted_findings(findings),
        "rule_applied": rule,
        "status": status,
        "weak_comparison_used": weak_used,
    }


def parse_entity_tag(raw, field):
    """Parse one ``entity-tag``（RFC 9110 §8.8.3），or raise.

    The ``W/`` prefix is accepted in exactly one spelling. A lowercase ``w/``
    is not a weak marker with a typo -- it is a different token, and reading it
    as weak would let a malformed request satisfy ``If-Match``（旧仓 cond-014
    冻结为工具错误而不是猜）。

    The opaque-tag keeps its quotes: comparison is byte-for-byte over the
    quoted form, which is why the quotes are part of the returned string.
    """
    text = raw.strip(OWS)
    weak = False
    if text[:2] in ("w/", "W/"):
        if text[:2] != "W/":
            raise invalid_header_value(field, NOT_AN_UPPERCASE_WEAK_MARKER)
        weak = True
        text = text[2:]
    if len(text) < 2 or text[0] != '"' or text[-1] != '"' or '"' in text[1:-1]:
        raise invalid_header_value(field, NOT_A_TAG)
    return {"weak": weak, "tag": text}


def parse_condition_value(raw, field):
    """Return ``(is_wildcard, tags)`` for one ``If-Match`` / ``If-None-Match``。

    ``*`` means "any current representation" only as the whole field value. A
    ``*`` inside a list is not an entity-tag and is rejected rather than
    dropped, because dropping it would silently change what the list asserts.
    An empty value carries no tags at all, which is not the same as ``*``.
    """
    text = raw.strip(OWS)
    if text == "*":
        return True, []
    tags = []
    for piece in text.split(","):
        piece = piece.strip(OWS)
        if not piece:
            continue
        tags.append(parse_entity_tag(piece, field))
    return False, tags


def strong_compare(left, right):
    """RFC 9110 §8.8.3.2 strong comparison: both strong, byte-equal."""
    return not left["weak"] and not right["weak"] and left["tag"] == right["tag"]


def weak_compare(left, right):
    """Weak comparison: the ``W/`` marker was dropped at parse time."""
    return left["tag"] == right["tag"]


def _read_resource(arguments):
    """Return ``(etag, last_modified_timestamp)``；两者都可为 ``None``。

    Both fields describe the *current* representation, so both are validated
    before any rule runs: a garbage date here is a caller mistake, not a
    condition to ignore（``If-Modified-Since: not a date`` 与
    ``resource.last_modified: not a date`` 的区别）。
    """
    resource = arguments.get("resource")
    if not isinstance(resource, dict):
        raise invalid_input("resource", "resource must be an object with etag and last_modified")

    etag = None
    raw_etag = resource.get("etag")
    if raw_etag is not None:
        if not isinstance(raw_etag, str):
            raise invalid_input("resource.etag", "etag must be a string or null")
        etag = parse_entity_tag(raw_etag, "resource.etag")

    modified = None
    raw_modified = resource.get("last_modified")
    if raw_modified is not None:
        _, modified = parse_time(raw_modified, "resource.last_modified")
    return etag, modified


def _header_date(raw, header, findings, catalog):
    """Parse a request-header date, or record that the condition is ignored.

    ``None`` is the signal that this condition must not be evaluated at all --
    not that the date was the epoch. RFC 9110 lets a malformed date be ignored,
    and 旧仓 plan/03 §4.2 chooses to say so in ``explain[]`` instead of failing.
    """
    try:
        _, value = parse_time(raw, REQUEST_FIELDS + "." + header)
    except JudgementError:
        findings.append(catalog.finding("COND_IGNORED_INVALID_DATE", header=header))
        return None
    return value


def _if_match_holds(wildcard, tags, etag):
    if etag is None:
        return False
    if wildcard:
        return True
    return any(strong_compare(tag, etag) for tag in tags)


def _if_none_match_holds(wildcard, tags, etag):
    if etag is None:
        return False
    if wildcard:
        return True
    return any(weak_compare(tag, etag) for tag in tags)


def evaluate_conditional(arguments, catalog):
    """Judge the preconditions of one request. Pure function."""
    method = normalise_method(arguments.get("method"), "method")
    if "request_headers" not in arguments:
        raise invalid_input(REQUEST_FIELDS, "request_headers is required")
    headers = normalise_headers(arguments.get(REQUEST_FIELDS), REQUEST_FIELDS)
    etag, modified = _read_resource(arguments)

    findings = []

    # E1: If-Match decides on its own, whether it passes or fails. Nothing
    # below it is even parsed.
    if_match = first_value(headers, IF_MATCH)
    if if_match is not None:
        wildcard, tags = parse_condition_value(if_match, REQUEST_FIELDS + "." + IF_MATCH)
        if not _if_match_holds(wildcard, tags, etag):
            findings.append(catalog.finding("COND_IF_MATCH_FAILED"))
            return _result(RULE_IF_MATCH, STATUS_PRECONDITION_FAILED, findings, False)
        return _result(RULE_IF_MATCH, STATUS_OK, findings, False)

    # E2: only reached when If-Match is absent. An unparsable date cancels this
    # condition and falls through to E3, leaving rule_applied at "none".
    if_unmodified = first_value(headers, IF_UNMODIFIED_SINCE)
    if if_unmodified is not None:
        limit = _header_date(if_unmodified, IF_UNMODIFIED_SINCE, findings, catalog)
        if limit is not None:
            if modified is not None and modified > limit:
                findings.append(catalog.finding("COND_IF_UNMODIFIED_SINCE_FAILED", date=if_unmodified))
                return _result(RULE_IF_UNMODIFIED_SINCE, STATUS_PRECONDITION_FAILED, findings, False)
            return _result(RULE_IF_UNMODIFIED_SINCE, STATUS_OK, findings, False)

    # E3: If-None-Match outranks If-Modified-Since, and it is the one condition
    # evaluated with weak comparison.
    if_none_match = first_value(headers, IF_NONE_MATCH)
    if if_none_match is not None:
        wildcard, tags = parse_condition_value(if_none_match, REQUEST_FIELDS + "." + IF_NONE_MATCH)
        findings.append(catalog.finding("COND_WEAK_COMPARISON_USED"))
        if _if_none_match_holds(wildcard, tags, etag):
            findings.append(catalog.finding("COND_IF_NONE_MATCH_MATCHED"))
            status = STATUS_NOT_MODIFIED if method in SAFE_METHODS else STATUS_PRECONDITION_FAILED
            return _result(RULE_IF_NONE_MATCH, status, findings, True)
        return _result(RULE_IF_NONE_MATCH, STATUS_OK, findings, True)

    # E4: the cache-validator rule, meaningful only for retrieval methods.
    if_modified = first_value(headers, IF_MODIFIED_SINCE)
    if if_modified is not None and method in SAFE_METHODS:
        limit = _header_date(if_modified, IF_MODIFIED_SINCE, findings, catalog)
        if limit is not None:
            if modified is not None and modified <= limit:
                findings.append(catalog.finding("COND_IF_MODIFIED_SINCE_NOT_MODIFIED", date=if_modified))
                return _result(RULE_IF_MODIFIED_SINCE, STATUS_NOT_MODIFIED, findings, False)
            return _result(RULE_IF_MODIFIED_SINCE, STATUS_OK, findings, False)

    # E5: no precondition applies (or the only one present was ignored).
    return _result(RULE_NONE, STATUS_OK, findings, False)
