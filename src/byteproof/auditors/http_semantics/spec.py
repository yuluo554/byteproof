"""口径面：模式、方法白名单、常量（迁自 10-19-http-semantics-mcp 的 spec 级常量）。

数值口径照搬旧仓 ``judgement/`` 各模块的模块级常量；规则措辞唯一来源是随包
``http-semantics.basis.json``（旧仓 ``rules.py`` CATALOG 生成件逐字节迁入）。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

#: 五个判定工具 = subject.mode（旧仓 tools/call 的 name）。
MODES = (
    "cache_evaluate",
    "conditional_evaluate",
    "cors_evaluate",
    "cors_simulate_fetch",
    "vary_match",
)
DEFAULT_MODE = "cache_evaluate"

#: 本器官收下的方法白名单（normalise.METHODS）。
METHOD_NAMES = (
    "GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "CONNECT", "TRACE",
)

#: cache 常量（RFC 9111 §4.2.2）。
MAX_HEURISTIC_SECONDS = 86400
HEURISTIC_DIVISOR = 10

#: conditional 常量（RFC 9110 §13.2.2）。
RULE_NONE = "none"
RULE_IF_MATCH = "if_match"
RULE_IF_UNMODIFIED_SINCE = "if_unmodified_since"
RULE_IF_NONE_MATCH = "if_none_match"
RULE_IF_MODIFIED_SINCE = "if_modified_since"
SAFE_METHODS = ("GET", "HEAD")
STATUS_OK = 200
STATUS_NOT_MODIFIED = 304
STATUS_PRECONDITION_FAILED = 412
IF_MATCH = "if-match"
IF_UNMODIFIED_SINCE = "if-unmodified-since"
IF_NONE_MATCH = "if-none-match"
IF_MODIFIED_SINCE = "if-modified-since"
REQUEST_FIELDS = "request_headers"

#: cors 常量（Fetch CORS protocol）。
SAFELISTED_METHODS = ("GET", "HEAD", "POST")
SAFELISTED_HEADERS = ("accept", "accept-language", "content-language", "content-type", "range")
SAFELISTED_CONTENT_TYPES = (
    "application/x-www-form-urlencoded", "multipart/form-data", "text/plain",
)
ALLOW_ORIGIN = "access-control-allow-origin"
ALLOW_CREDENTIALS = "access-control-allow-credentials"
ALLOW_METHODS = "access-control-allow-methods"
ALLOW_HEADERS = "access-control-allow-headers"

#: fetch_sim 常量（plan/03 §2）。
EVENTS = ("origin_set_to_null", "credentials_dropped")
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
FETCH_MODES = ("cors", "no-cors", "same-origin")
FINAL_TYPES = {"cors": "cors", "no-cors": "opaque", "same-origin": "basic"}
ALLOW_MAX_AGE = "access-control-max-age"
EXPOSE_HEADERS = "access-control-expose-headers"

#: vary 常量（RFC 9111 §4.1）。
MATCH_HIT = "hit"
MATCH_MISS = "miss"
WILDCARD = "*"

#: 时间解析两形态（data/README.md §4.4）。
ISO_FORM = "iso8601"
HTTP_DATE_FORM = "http-date"
