"""共享输入规范化（1:1 移植自旧仓 ``judgement/normalise.py``）。

Deliberately pure string work：判定层不碰磁盘、时钟、网络、进程与环境。
只依赖 ``re`` 与 ``hashlib``，都是参数的确定性函数。

规范化规则（旧仓 ``data/README.md`` §4.3 / plan/03 §0.1）：

* header 名小写化、去首尾 OWS，再对照 RFC 9110 token 字符集；
* header 值保留内部空白与大小写，仅去两端 OWS；
* origin 缩减为 ``scheme://host[:port]``，scheme/host 小写、默认端口丢弃——
  无 path、无 query、无尾斜杠。
"""

from __future__ import annotations

import re
from hashlib import sha256

from .errors import JudgementError, invalid_header_name, invalid_input, unsupported_method

__all__ = [
    "METHOD_NAMES",
    "OWS",
    "NULL_ORIGIN",
    "normalise_header_name",
    "normalise_headers",
    "normalise_method",
    "serialise_origin",
    "origin_key",
    "split_comma_list",
    "first_value",
    "header_name_list",
    "sha256_prefix",
]

# Optional whitespace, RFC 9110 section 5.6.3.
OWS = " \t"

NULL_ORIGIN = "null"

# 本器官识别的方法集合；集合外的值被拒而不是透传（旧仓 plan/03 §0.1 item 4）。
METHOD_NAMES = (
    "GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "CONNECT", "TRACE",
)

DEFAULT_PORTS = {"http": 80, "https": 443}

# RFC 9110 section 5.6.2: tchar.
TOKEN = re.compile(r"^[a-z0-9!#$%&'*+.^_`|~-]+$")


def normalise_header_name(name, field):
    """Lowercase + trim + token check. Raises for anything that is not a name."""
    if not isinstance(name, str):
        raise invalid_header_name(field, name)
    lowered = name.strip(OWS).lower()
    if not lowered or TOKEN.fullmatch(lowered) is None:
        raise invalid_header_name(field, name)
    return lowered


def normalise_headers(headers, field):
    """Return ``{lowercase_name: [values...]}``，保留值序。

    输入可以是字符串（单值）或数组（重复 header）。名按大小写不敏感合并；
    名的顺序不可观测——每个消费方都走排序视图。
    """
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise invalid_input(field, "expected an object of header name -> string or array")
    collected = {}
    for raw_name in sorted(headers):
        name = normalise_header_name(raw_name, field + "." + str(raw_name))
        raw_value = headers[raw_name]
        if isinstance(raw_value, str):
            values = [raw_value]
        elif isinstance(raw_value, list):
            values = []
            for item in raw_value:
                if not isinstance(item, str):
                    raise invalid_input(field + "." + name, "header values must be strings")
                values.append(item)
        else:
            raise invalid_input(field + "." + name, "header value must be a string or an array")
        collected.setdefault(name, []).extend(values)
    return collected


def normalise_method(method, field="method"):
    if not isinstance(method, str):
        raise invalid_input(field, "method must be a string")
    upper = method.strip(OWS).upper()
    if not upper:
        raise invalid_input(field, "method must not be empty")
    if upper not in METHOD_NAMES:
        raise unsupported_method(field, method)
    return upper


def _split_url(url, field):
    """Return ``(scheme, host, port)`` from ``scheme://host[:port]``。"""
    if not isinstance(url, str):
        raise invalid_input(field, "url must be a string")
    text = url.strip(OWS)
    marker = text.find("://")
    if marker <= 0:
        raise invalid_input(field, "url must be scheme://host[:port]")
    scheme = text[:marker].lower()
    if scheme not in DEFAULT_PORTS:
        raise invalid_input(field, "only http and https are supported")
    rest = text[marker + 3:]
    for delimiter in ("/", "?", "#"):
        cut = rest.find(delimiter)
        if cut >= 0:
            rest = rest[:cut]
    if not rest:
        raise invalid_input(field, "url has no host")
    port = DEFAULT_PORTS[scheme]
    host = rest
    if ":" in rest:
        host, _, port_text = rest.rpartition(":")
        if not port_text.isdigit():
            raise invalid_input(field, "url port must be numeric")
        port = int(port_text)
        if not 0 < port < 65536:
            raise invalid_input(field, "url port is out of range")
        if not host:
            raise invalid_input(field, "url has no host")
    return scheme, host.lower(), port


def serialise_origin(url, field="url"):
    """Reduce a URL to its origin form, dropping the default port."""
    scheme, host, port = _split_url(url, field)
    if port == DEFAULT_PORTS[scheme]:
        return scheme + "://" + host
    return scheme + "://" + host + ":" + str(port)


def origin_key(value, field="origin"):
    """Normalise a request Origin。

    未提供（None）= 同源请求的表达方式；字面 ``"null"`` = opaque origin；
    其余按 ``scheme://host[:port]`` 规范化。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_input(field, "origin must be a string or null")
    text = value.strip(OWS)
    if text.lower() == NULL_ORIGIN:
        return NULL_ORIGIN
    try:
        return serialise_origin(text, field)
    except JudgementError:
        raise invalid_input(field, "origin must be scheme://host[:port] or the literal null")


def split_comma_list(values):
    """Split repeated comma-separated header values, trimming OWS and empties."""
    pieces = []
    for value in values:
        for piece in value.split(","):
            trimmed = piece.strip(OWS)
            if trimmed:
                pieces.append(trimmed)
    return pieces


def first_value(headers, name):
    """First value of a header, OWS-trimmed, or ``None`` when absent."""
    values = headers.get(name)
    if not values:
        return None
    return values[0].strip(OWS)


def header_name_list(names):
    """Lowercase, de-duplicate, sort -- name 列表的唯一排序规则。"""
    cleaned = []
    for name in names:
        if not name:
            continue
        stripped = name.strip(OWS).lower()
        if stripped:
            cleaned.append(stripped)
    return sorted(set(cleaned))


def sha256_prefix(text, length):
    """First ``length`` hex characters of the SHA-256 of ``text`` (UTF-8)。"""
    return sha256(text.encode("utf-8")).hexdigest()[:length]
