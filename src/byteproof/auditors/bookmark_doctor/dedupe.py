"""去重引擎（照搬旧仓 ``src/bookmark_doctor/dedupe.py``）。

口径（照搬）：
- 比较键 = ``normalize_url(url)``；观测有 ``final_url`` 时**优先**用 ``normalize(final_url)``；
- 保留策略（固定、可复现）：https 优先 > 无追踪参数 > add_date 最早 >
  文件序最早（UIR 条目序即 (来源声明顺序, 来源内文件序)）；
- **绝不自动删**：只出清单；
- 仅 fragment 不同的成员归入同组，组附 ``fragment_variant`` 标记；
- 未收录短链不猜。
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from .normalize import fragment_of, normalize_url

REASON_FRAGMENT_VARIANT = "fragment_variant"


def _has_tracked_param(url, tracked_params):
    exact = set(tracked_params.get("exact", []))
    prefixes = tuple(tracked_params.get("prefixes", []))
    query = urlsplit(url).query
    if not query:
        return False
    for name, _ in parse_qsl(query, keep_blank_values=True):
        if name in exact or name.startswith(prefixes):
            return True
    return False


def _keep_score(bookmark, tracked_params):
    """保留优先级键：越小越优先保留（固定策略）。"""
    scheme_https = 0 if urlsplit(bookmark["url"]).scheme.lower() == "https" else 1
    tracked = 1 if _has_tracked_param(bookmark["url"], tracked_params) else 0
    add_date = bookmark.get("add_date")
    date_rank = add_date if add_date is not None else float("inf")
    return (scheme_https, tracked, date_rank)


def build_duplicate_groups(bookmarks, tracked_params, check_records=None):
    """UIR 条目 + 规则包参数 → 重复组清单（绝不修改输入条目；仅清单）。"""
    final_by_url = {}
    for record in check_records or []:
        final = record.get("final_url")
        if final:
            final_by_url[record.get("url")] = final

    groups = {}
    order = []
    for index, bm in enumerate(bookmarks):
        url = bm["url"]
        # 比较键：final_url 优先（探测后真实落点），否则原文
        key_source = final_by_url.get(url, url)
        key = normalize_url(key_source, tracked_params)
        if key not in groups:
            groups[key] = {"index": [], "fragments": set()}
            order.append(key)
        groups[key]["index"].append(index)
        frag = fragment_of(url)
        if frag:
            groups[key]["fragments"].add(frag)

    duplicate_groups = []
    for group_id, key in enumerate(order, 1):
        members_index = groups[key]["index"]
        if len(members_index) < 2:
            continue
        members = [bookmarks[i] for i in members_index]
        # fragment_variant：以规范化键为基（追踪参数/尾斜杠/scheme 差异已被流水线
        # 吸收），fragment 互异才算
        bases = {normalize_url(bm["url"], tracked_params) for bm in members}
        fragments = set()
        for bm in members:
            fragments.add(fragment_of(bm["url"]) or "")
        fragment_variant = len(bases) == 1 and len(fragments) > 1
        keeper = min(members, key=lambda bm: _keep_score(bm, tracked_params))
        duplicate_groups.append(
            {
                "group_id": "dup-%04d" % group_id,
                "key": key,
                "fragment_variant": fragment_variant,
                "members": [
                    {"id": bm["id"], "url": bm["url"], "title": bm.get("title")}
                    for bm in members
                ],
                "keep": {"id": keeper["id"], "url": keeper["url"]},
            }
        )
    return duplicate_groups
