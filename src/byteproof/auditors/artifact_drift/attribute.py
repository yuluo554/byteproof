"""归因引擎（旧仓 ``internal/attribute`` + ``normalize`` + ``minimize`` 的判定子集）。

- 分类法 T1–T12 的触发条件与优先级照搬 ``attribute.classifyFact``；
- **T4 先于逐条目比对**：两侧公共根前缀不同先记一条树级差异；
- **T5 仅在条目集合与内容哈希完全一致时判**（否则顺序不可比）；
- 内容字节只在**没有任何 T1–T11 解释**时落 T12；
- ``residue_bytes`` = 归一化（T1–T11）后 entry_stream 逐字节比对的差异之和；
- 最小原因集：|S| 升序、同基数按 T1→T11 顺序枚举，命中即停；``[]`` = 完全一致，
  ``None`` = 无解。

**简化（已在 docs 登记）**：不解析 ELF/PE/Mach-O 节字节。T8–T11 命中时把条目
``data`` 置空作为规范形（相当于「该条目的内容差异已被工具链/构建目录解释」），
而不是只重写相关节。
"""

from __future__ import annotations

import hashlib
import itertools

from .align import common_dir_prefix
from .spec import (
    METADATA_RULES,
    RULE_IDS,
    T1,
    T2,
    T3,
    T4,
    T5,
    T6,
    T7,
    T8,
    T9,
    T10,
    T11,
    T12,
)


def count_diff(left, right):
    n = min(len(left), len(right))
    different = sum(1 for index in range(n) if left[index] != right[index])
    different += abs(len(left) - len(right))
    return different


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def section_of(key):
    prefix = "elf.section."
    if not key.startswith(prefix):
        return None
    rest = key[len(prefix):]
    index = rest.rfind(".")
    if index < 0:
        return None
    return rest[:index]


def zip_perm(value):
    try:
        return (int(value) >> 16) & 0o7777
    except (TypeError, ValueError):
        return 0


def zip_other(value):
    try:
        return int(value) & ~(0o7777 << 16)
    except (TypeError, ValueError):
        return 0


def classify_fact(key, left_value, right_value, left_present, right_present):
    """返回 ``(rule, multi, ignore)``；优先级 T1→T12。"""
    section = section_of(key)
    if section is not None:
        if left_present != right_present:
            if section == ".sig":
                return T10, False, False
            if section in (".note.gnu.build-id", ".debug_info", ".debug_abbrev", ".debug_str"):
                return T9, False, False
            if section == ".comment":
                return T8, False, False
            return T12, False, False
        if section == ".sig":
            return T10, False, False
        if section == ".note.gnu.build-id":
            return T9, False, False
        return "", False, True

    if key in ("tar.mtime", "zip.mtime", "gzip.mtime"):
        return T1, False, False
    if key in ("tar.uid", "tar.gid", "tar.uname", "tar.gname"):
        return T2, False, False
    if key == "tar.mode":
        return T3, False, False
    if key == "zip.external_attr":
        if zip_perm(left_value) != zip_perm(right_value):
            return T3, zip_other(left_value) != zip_other(right_value), False
        if zip_other(left_value) != zip_other(right_value):
            return T7, False, False
        return T12, False, False
    if key in ("gzip.xfl", "gzip.os"):
        return T6, False, False
    if key in ("raw_header_sha256", "zip.create_system"):
        return T7, False, False
    if key in ("elf.comment", "elf.producer"):
        return T8, False, False
    if key == "elf.build_id":
        return T9, False, False
    if key == "elf.comp_dir":
        return T11, False, False
    if key == "tar.size":
        return "", False, True  # 派生字段：内容长度变了它必然跟着变
    return T12, False, False


def explains_content(key):
    if key in ("elf.comment", "elf.producer", "elf.build_id", "elf.comp_dir"):
        return True
    section = section_of(key)
    return section in (
        ".sig", ".note.gnu.build-id", ".debug_info", ".debug_abbrev", ".debug_str", ".comment"
    )


def _left_prefix(entries):
    return common_dir_prefix([entry["path"] for entry in entries])


def attribute(left_entries, right_entries):
    """返回 ``{counts, diffs, residue_bytes, notes, minimal_cause_set}``。"""
    left_prefix = _left_prefix(left_entries)
    right_prefix = _left_prefix(right_entries)

    def view(entries, prefix):
        return {
            (entry["path"][len(prefix):] if prefix and entry["path"].startswith(prefix) else entry["path"]): entry
            for entry in entries
        }

    left = view(left_entries, left_prefix)
    right = view(right_entries, right_prefix)
    counts = {rule: 0 for rule in RULE_IDS}
    counts["total"] = 0

    def add(rule):
        counts[rule] += 1
        counts["total"] += 1

    diffs = []
    notes = []

    left_prefix = _left_prefix(left_entries)
    right_prefix = _left_prefix(right_entries)
    if left_prefix != right_prefix:
        diffs.append(
            {"path": "", "key": "relpath.prefix", "rule_id": T4, "left": left_prefix, "right": right_prefix, "bytes_delta": 0}
        )
        add(T4)

    same_set = (
        set(left) == set(right)
        and all(left[path]["sha256"] == right[path]["sha256"] for path in left)
    )

    overlap = False
    for path in sorted(set(left) | set(right), key=lambda value: value.encode("utf-8")):
        le = left.get(path)
        re = right.get(path)
        if re is None:
            diffs.append({"path": path, "key": "content", "rule_id": T12, "left": _digest(le["data"]), "right": "", "bytes_delta": len(le["data"])})
            add(T12)
            continue
        if le is None:
            diffs.append({"path": path, "key": "content", "rule_id": T12, "left": "", "right": _digest(re["data"]), "bytes_delta": len(re["data"])})
            add(T12)
            continue

        if same_set and le["index"] != re["index"]:
            diffs.append({"path": path, "key": "index", "rule_id": T5, "left": str(le["index"]), "right": str(re["index"]), "bytes_delta": 0})
            add(T5)

        explained = False
        for key in sorted(set(le["facts"]) | set(re["facts"])):
            left_present = key in le["facts"]
            right_present = key in re["facts"]
            lv = le["facts"].get(key, "")
            rv = re["facts"].get(key, "")
            if left_present == right_present and lv == rv:
                continue
            rule, multi, ignore = classify_fact(key, lv, rv, left_present, right_present)
            if ignore:
                continue
            if multi:
                overlap = True
            if rule != T12 and explains_content(key):
                explained = True
            diffs.append({"path": path, "key": key, "rule_id": rule, "left": lv, "right": rv, "bytes_delta": 0})
            add(rule)

        if le["data"] != re["data"] and not explained:
            diffs.append(
                {
                    "path": path,
                    "key": "content",
                    "rule_id": T12,
                    "left": _digest(le["data"]),
                    "right": _digest(re["data"]),
                    "bytes_delta": count_diff(le["data"], re["data"]),
                }
            )
            add(T12)

    if overlap:
        notes.append("rule_overlap")
    diffs.sort(key=lambda diff: (diff["path"].encode("utf-8"), diff["key"], diff["rule_id"]))

    residue = residue_bytes(left_entries, right_entries)
    cause = minimal_cause_set(left_entries, right_entries)
    return {
        "counts": counts,
        "diffs": diffs,
        "residue_bytes": residue,
        "notes": notes,
        "minimal_cause_set": cause,
    }


def _apply_facts(entry, ops):
    facts = dict(entry["facts"])
    explained = False

    fact_rules = {
        T1: ("tar.mtime", "zip.mtime", "gzip.mtime"),
        T2: ("tar.uid", "tar.gid", "tar.uname", "tar.gname"),
        T3: ("tar.mode", "zip.external_attr"),
        T6: ("gzip.xfl", "gzip.os"),
        T7: ("raw_header_sha256", "zip.create_system"),
        T8: ("elf.comment", "elf.producer"),
        T9: ("elf.build_id",),
        T11: ("elf.comp_dir",),
    }
    for rule, keys in fact_rules.items():
        if rule not in ops:
            continue
        for key in keys:
            if key in facts:
                facts.pop(key, None)
                if rule in (T8, T9, T11):
                    explained = True

    section_rules = {
        ".comment": T8,
        ".note.gnu.build-id": T9,
        ".debug_info": T9,
        ".debug_abbrev": T9,
        ".debug_str": T9,
        ".sig": T10,
    }
    for key in list(facts):
        rule = section_rules.get(section_of(key))
        if rule is not None and rule in ops:
            facts.pop(key, None)
            if rule in (T8, T9, T10):
                explained = True

    data = b"" if explained else entry["data"]
    if "tar.size" in facts:
        facts["tar.size"] = str(len(data))
    return facts, data


def normalize_entries(entries, ops, prefix):
    normalized = []
    for entry in entries:
        facts, data = _apply_facts(entry, set(ops))
        path = entry["path"]
        if T4 in ops and prefix and path.startswith(prefix):
            path = path[len(prefix):]
        index = 0 if T5 in ops else entry["index"]
        normalized.append({"path": path, "index": index, "facts": facts, "data": data})
    return normalized


def entry_stream(entry):
    chunks = [str(entry["index"]).encode("utf-8"), b"\x00"]
    for key in sorted(entry["facts"]):
        chunks.append(key.encode("utf-8"))
        chunks.append(b"\x00")
        chunks.append(entry["facts"][key].encode("utf-8"))
        chunks.append(b"\x0a")
    chunks.append(b"\x00")
    chunks.append(entry["data"])
    return b"".join(chunks)


def tree_digest(entries):
    hasher = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"].encode("utf-8")):
        hasher.update(entry["path"].encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(_digest(entry_stream(entry)).encode("ascii"))
        hasher.update(b"\x0a")
    return hasher.hexdigest()


def _normalized_pair(left_entries, right_entries, ops):
    return (
        normalize_entries(left_entries, ops, _left_prefix(left_entries)),
        normalize_entries(right_entries, ops, _left_prefix(right_entries)),
    )


def minimal_cause_set(left_entries, right_entries):
    for size in range(len(METADATA_RULES) + 1):
        for combo in itertools.combinations(METADATA_RULES, size):
            left_norm, right_norm = _normalized_pair(left_entries, right_entries, combo)
            if tree_digest(left_norm) == tree_digest(right_norm):
                return list(combo)
    return None


def residue_bytes(left_entries, right_entries):
    left_norm, right_norm = _normalized_pair(left_entries, right_entries, METADATA_RULES)
    left_map = {entry["path"]: entry for entry in left_norm}
    right_map = {entry["path"]: entry for entry in right_norm}
    total = 0
    for path in sorted(set(left_map) | set(right_map), key=lambda value: value.encode("utf-8")):
        le = left_map.get(path)
        re = right_map.get(path)
        if le is not None and re is not None:
            total += count_diff(entry_stream(le), entry_stream(re))
        elif le is not None:
            total += len(entry_stream(le))
        else:
            total += len(entry_stream(re))
    return total