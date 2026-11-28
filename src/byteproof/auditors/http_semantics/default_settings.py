"""运行期常量（旧仓 ``rules.py`` CATALOG 的 severity / vary_normalization /
preflight_cache_key 三节的代码侧镜像）。

随包 ``http-semantics.thresholds.json`` 是同一张表的快照，两者由测试双向断言
（改一处不改另一处会红）。器官不读文件：subject 未带 ``thresholds`` 时用本模块。
"""

from __future__ import annotations

#: 31 条规则的 severity（decisive = 决定结论 → 账本 error；informational → info）。
SEVERITY = {
    "CACHE_AGE_EXCEEDS_LIFETIME": "decisive",
    "CACHE_EXPIRES_IN_PAST": "decisive",
    "CACHE_HEURISTIC_FRESHNESS": "informational",
    "CACHE_INVALID_AGE": "informational",
    "CACHE_INVALID_MAX_AGE": "informational",
    "CACHE_MAX_AGE_ZERO": "informational",
    "CACHE_MUST_REVALIDATE_STALE": "decisive",
    "CACHE_NO_CACHE": "decisive",
    "CACHE_NO_STORE": "decisive",
    "CACHE_STALE_WHILE_REVALIDATE": "decisive",
    "COND_IF_MATCH_FAILED": "decisive",
    "COND_IF_MODIFIED_SINCE_NOT_MODIFIED": "decisive",
    "COND_IF_NONE_MATCH_MATCHED": "decisive",
    "COND_IF_UNMODIFIED_SINCE_FAILED": "decisive",
    "COND_IGNORED_INVALID_DATE": "informational",
    "COND_WEAK_COMPARISON_USED": "informational",
    "CORS_DISALLOWED_HEADER_NOT_EXPOSED": "decisive",
    "CORS_MISSING_ALLOW_CREDENTIALS": "decisive",
    "CORS_MISSING_ALLOW_HEADERS": "decisive",
    "CORS_MISSING_ALLOW_METHODS": "decisive",
    "CORS_MISSING_ALLOW_ORIGIN": "decisive",
    "CORS_MODE_OPAQUE": "informational",
    "CORS_NULL_ORIGIN": "informational",
    "CORS_ORIGIN_MISMATCH": "decisive",
    "CORS_PREFLIGHT_REQUIRED": "decisive",
    "CORS_REDIRECT_NOT_SAME_ORIGIN": "decisive",
    "CORS_WILDCARD_WITH_CREDENTIALS": "decisive",
    "VARY_DUPLICATE_FIELD": "informational",
    "VARY_FIELD_MISMATCH": "decisive",
    "VARY_FIELD_MISSING": "decisive",
    "VARY_STAR_NEVER_MATCHES": "decisive",
}

#: Vary 字段规范化策略表（旧仓 CATALOG['vary_normalization'] 逐字段照搬）。
VARY_NORMALIZATION = {
    "default": {"case_sensitive": True, "fold_whitespace": True, "sort_comma_segments": False, "trim": True},
    "fields": {
        "accept": {"case_sensitive": False, "fold_whitespace": True, "sort_comma_segments": True, "trim": True},
        "accept-encoding": {"case_sensitive": False, "fold_whitespace": True, "sort_comma_segments": True, "trim": True},
        "accept-language": {"case_sensitive": False, "fold_whitespace": True, "sort_comma_segments": True, "trim": True},
        "user-agent": {"case_sensitive": True, "fold_whitespace": False, "sort_comma_segments": False, "trim": True},
    },
}

#: preflight cache key 口径（旧仓 CATALOG['preflight_cache_key']）。
PREFLIGHT_CACHE_KEY = {
    "algorithm": "sha256",
    "canonical_url": "scheme://host[:port]",
    "hex_prefix": 16,
    "input": 'origin + "\\n" + canonical_url',
}

#: tool-face 错误码冻结枚举（errors.ERROR_CODES 的镜像）。
ERROR_CODES = (
    "INVALID_INPUT",
    "INVALID_TIME_FORMAT",
    "INVALID_HEADER_NAME",
    "INVALID_HEADER_VALUE",
    "UNSUPPORTED_METHOD",
)

SETTINGS = {
    "slug": "http-semantics",
    "severity": SEVERITY,
    "spec_ref": {},
    "vary_normalization": VARY_NORMALIZATION,
    "preflight_cache_key": PREFLIGHT_CACHE_KEY,
    "error_codes": list(ERROR_CODES),
}
