"""URL 规范化（照搬旧仓 ``src/bookmark_doctor/normalize.py``）。

纪律（照搬）：
- **原始 URL 永不改写**——normalize 结果只作比较键；
- 追踪参数名单由 subject 提供（旧仓 ruleset ``tracked_query_params``），不写第二份；
- 未实测短链不猜：``shortlink_known`` 映射由 subject 注入，本模块不解析短链目标；
- 六步**固定顺序**：scheme → host/端口 → 路径 → 查询串 → fragment → final_url。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}  # 协议语义端口（非策略参数）


def _is_tracked(name, exact, prefixes):
    if name in exact:
        return True
    for prefix in prefixes:
        if name.startswith(prefix):
            return True
    return False


def normalize_url(url, tracked_params, shortlink_known=None):
    """URL 原文 → 比较键（六步流水线，固定顺序）。"""
    exact = list((tracked_params or {}).get("exact", []))
    prefixes = list((tracked_params or {}).get("prefixes", []))

    # 第 0 步（映射）：已实测短链 → 比较键用映射目标；未收录 → 不猜
    if shortlink_known and url in shortlink_known:
        url = shortlink_known[url]

    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    original_scheme = scheme
    if scheme == "http":
        scheme = "https"
    hostname = (parts.hostname or "").lower()
    port = parts.port
    if port is not None and DEFAULT_PORTS.get(original_scheme) == port:
        port = None
    netloc = hostname if port is None else "%s:%d" % (hostname, port)
    path = parts.path or ""
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracked(k, exact, prefixes)
    ]
    query_pairs.sort()
    query = urlencode(query_pairs)
    return urlunsplit((scheme, netloc, path, query, ""))


def fragment_of(url):
    """URL 原文的 fragment（不含 #；无 → None）。fragment_variant 标记用。"""
    parts = urlsplit(url)
    return parts.fragment or None
