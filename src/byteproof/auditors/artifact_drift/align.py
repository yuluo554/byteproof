"""结构对齐（旧仓 ``internal/align`` 的判定子集）。

- 条目按 relpath 的 UTF-8 字节序排序；
- 同 relpath 同形态 -> SAME（内容差异交给归因层）；
- 同 relpath 异形态 -> 左侧 REMOVED + 右侧 ADDED（不是改名）；
- 改名**仅当**该 sha256 在两侧各恰好出现 1 次，且两侧各只有一条未匹配条目携带它；
- 不做相似度、模糊对齐、大小写折叠。
"""

from __future__ import annotations

import hashlib

from .spec import (
    EMPTY_SHA256,
    KIND_DIR,
    KIND_FILE,
    KIND_LINK,
    KINDS,
    STATUS_ADDED,
    STATUS_REMOVED,
    STATUS_RENAMED,
    STATUS_SAME,
)


class AlignError(ValueError):
    """条目结构非法（输入不合法，退出码 2）。"""


def digest(data):
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    return hashlib.sha256(str(data).encode("utf-8")).hexdigest()


def _bytes(data):
    if data is None:
        return b""
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    raise AlignError("entry.data 必须是字符串或字节")


def normalize_entry(raw, side):
    if not isinstance(raw, dict):
        raise AlignError("%s.entries 的每一项必须是对象" % side)
    path = raw.get("path")
    kind = raw.get("kind", KIND_FILE)
    if not isinstance(path, str):
        raise AlignError("%s.entries[].path 必须是字符串" % side)
    if kind not in KINDS:
        raise AlignError("%s.entries[].kind 必须是 %s" % (side, "/".join(KINDS)))
    index = raw.get("index")
    if index is None:
        index = -1
    if isinstance(index, bool) or not isinstance(index, int):
        raise AlignError("%s.entries[].index 必须是整数" % side)
    data = _bytes(raw.get("data"))
    facts = raw.get("facts") or {}
    if not isinstance(facts, dict):
        raise AlignError("%s.entries[].facts 必须是对象" % side)
    for key, value in facts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise AlignError("%s.entries[].facts 的键值必须是字符串" % side)
    if kind == KIND_DIR:
        data = b""
    return {
        "path": path,
        "kind": kind,
        "index": index,
        "data": data,
        "facts": dict(facts),
        "sha256": digest(data) if kind != KIND_DIR else EMPTY_SHA256,
        "size": 0 if kind == KIND_DIR else len(data),
    }


def normalize_side(side, label):
    if not isinstance(side, dict):
        raise AlignError("%s 必须是对象" % label)
    entries = side.get("entries")
    if not isinstance(entries, list):
        raise AlignError("%s.entries 必须是列表" % label)
    return [normalize_entry(raw, label) for raw in entries]


def _sort_key(entry):
    return (entry["relpath"].encode("utf-8"), entry["status"], entry["sha256"])


def align(left_entries, right_entries):
    """返回 ``entries``（四态行）与计数。"""
    left = {entry["path"]: entry for entry in left_entries}
    right = {entry["path"]: entry for entry in right_entries}

    rows = []
    removed_only = []
    added_only = []
    for path in sorted(set(left) | set(right), key=lambda value: value.encode("utf-8")):
        le = left.get(path)
        re = right.get(path)
        if le is not None and re is not None and le["kind"] == re["kind"]:
            rows.append(
                {
                    "relpath": path,
                    "status": STATUS_SAME,
                    "kind": re["kind"],
                    "size": re["size"],
                    "sha256": re["sha256"],
                }
            )
        elif le is not None and re is not None:
            rows.append({"relpath": path, "status": STATUS_REMOVED, "kind": le["kind"], "size": le["size"], "sha256": le["sha256"]})
            rows.append({"relpath": path, "status": STATUS_ADDED, "kind": re["kind"], "size": re["size"], "sha256": re["sha256"]})
        elif le is not None:
            removed_only.append(le)
        else:
            added_only.append(re)

    left_hash = {}
    for entry in left.values():
        left_hash[entry["sha256"]] = left_hash.get(entry["sha256"], 0) + 1
    right_hash = {}
    for entry in right.values():
        right_hash[entry["sha256"]] = right_hash.get(entry["sha256"], 0) + 1

    by_hash = {entry["sha256"]: entry for entry in removed_only if left_hash.get(entry["sha256"]) == 1}
    consumed = set()
    absorbed = set()
    for re in added_only:
        if right_hash.get(re["sha256"]) != 1 or left_hash.get(re["sha256"]) != 1:
            continue
        le = by_hash.get(re["sha256"])
        if le is None:
            continue
        consumed.add(le["path"])
        absorbed.add(re["path"])
        rows.append(
            {
                "relpath": re["path"],
                "status": STATUS_RENAMED,
                "kind": re["kind"],
                "size": re["size"],
                "sha256": re["sha256"],
                "renamed_from": le["path"],
            }
        )
        del by_hash[re["sha256"]]

    for le in removed_only:
        if le["path"] in consumed:
            continue
        rows.append({"relpath": le["path"], "status": STATUS_REMOVED, "kind": le["kind"], "size": le["size"], "sha256": le["sha256"]})
    for re in added_only:
        if re["path"] in absorbed:
            continue
        rows.append({"relpath": re["path"], "status": STATUS_ADDED, "kind": re["kind"], "size": re["size"], "sha256": re["sha256"]})

    rows.sort(key=_sort_key)
    counts = {
        STATUS_SAME: sum(1 for row in rows if row["status"] == STATUS_SAME),
        STATUS_ADDED: sum(1 for row in rows if row["status"] == STATUS_ADDED),
        STATUS_REMOVED: sum(1 for row in rows if row["status"] == STATUS_REMOVED),
        STATUS_RENAMED: sum(1 for row in rows if row["status"] == STATUS_RENAMED),
    }
    return rows, counts


def common_dir_prefix(paths):
    """所有路径的公共目录前缀（含结尾 ``/``）；要求每条路径前缀后仍有内容。"""
    if not paths:
        return ""
    segments = paths[0].split("/")
    prefix = []
    for index in range(len(segments) - 1):
        for path in paths:
            parts = path.split("/")
            if len(parts) <= index + 1 or parts[index] != segments[index]:
                return "/".join(prefix) + "/" if prefix else ""
        prefix.append(segments[index])
    return "/".join(prefix) + "/" if prefix else ""