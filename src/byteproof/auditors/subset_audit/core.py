"""判定核（迁自 10-21-subset-audit 四模块的纯面：cmapset / coverage_diff /
layout_survival / metadata；fontTools 读取全部留输入层）。

subject 携带**摊平事实**：cmap 映射 ``{cp: glyphName}``、OS/2 位域表、nameID 映射、
布局三元组与连字码位视图、``unicode_ranges`` 表（fontTools ``OS2_UNICODE_RANGES``
原样传入——旧仓纪律"本仓库不复制这张表"保持：器官同样不内置，经 subject 供表）。
"""

from __future__ import annotations

import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import spec


# ---------------------------------------------------------------- canonical 面
def finding(module: str, code: str, severity: str, primary_key: str, message: str,
            evidence: Optional[Mapping[str, Any]] = None,
            spec_ref: str = "") -> Dict[str, Any]:
    """Finding 构造（旧仓 canonical.finding 同构：未知模块/严重度直接 ValueError）。"""
    if module not in ("coverage-diff", "layout-survival", "metadata"):
        raise ValueError("unknown module: " + module)
    if severity not in spec.SEVERITIES:
        raise ValueError("unknown severity: " + severity)
    return {
        "module": module,
        "code": code,
        "severity": severity,
        "primary_key": primary_key,
        "message": message,
        "evidence": dict(evidence or {}),
        "spec_ref": spec_ref,
    }


def skipped(module: str, reason: str, detail: str = "") -> Dict[str, Any]:
    return {"module": module, "skipped": True, "reason": reason, "detail": detail}


def sort_findings(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """排序键 ``(module, severity 序, primary_key)``（旧仓 canonical.sort_findings）。"""
    rank = {name: i for i, name in enumerate(spec.SEVERITIES)}
    return sorted((dict(x) for x in items),
                  key=lambda f: (f["module"], rank.get(f["severity"], 99), f["primary_key"]))


def u(cp: int) -> str:
    """``U+5B57``（大写、至少 4 位，§六.2）。"""
    return "U+%04X" % int(cp)


# ---------------------------------------------------------------- cmapset（§六.2/§六.4）
def codepoints(selected: Optional[Mapping[Any, str]]) -> set:
    """真实覆盖码位：映射到 .notdef 的视为缺（§六.2）。

    键接受 int 或 ``"0x…"`` 十六进制字符串（旧仓 expect.json 的摊平形态）。
    """
    if not selected:
        return set()
    out = set()
    for cp, glyph in selected.items():
        name = (glyph or "").strip()
        if name in spec.NOTDEF_NAMES:
            continue
        if isinstance(cp, str):
            cp = int(cp, 16) if cp.lower().startswith("0x") else int(cp)
        out.add(int(cp))
    return out


def classify(required, source, subset) -> Dict[str, List[int]]:
    """三分类（§六.2）：``MISSING_IN_SOURCE`` / ``LOST_IN_SUBSET`` / ``OK``，均码位升序。"""
    required = set(required)
    source = set(source)
    subset = set(subset) if subset is not None else None
    missing = required - source
    if subset is None:
        lost = set()
        ok = required & source
    else:
        lost = (required & source) - subset
        ok = required & source & subset
    return {
        "OK": sorted(ok),
        "MISSING_IN_SOURCE": sorted(missing),
        "LOST_IN_SUBSET": sorted(lost),
    }


def block_of(cp: int) -> str:
    """分区归属（§六.4）：**ExtA 优先于 BMP**（0x3400 曾被判成 BMP 的实测修正）。"""
    if spec.EXTA_LO <= cp <= spec.EXTA_HI:
        return "ExtA"
    if spec.EXTB_LO <= cp <= spec.EXTB_HI:
        return "ExtB+"
    if 0 <= cp <= spec.BMP_MAX:
        return "BMP"
    return "other"


def block_counts(cps: Iterable[int]) -> Dict[str, int]:
    counts = {"BMP": 0, "ExtA": 0, "ExtB+": 0, "other": 0}
    for cp in sorted(set(cps)):
        counts[block_of(cp)] += 1
    return counts


def closure(cps: Iterable[int]) -> Tuple[set, List[int]]:
    """组合字符闭包：NFD 分解与 NFC 合成（§六.2.1）。"""
    base = set(int(c) for c in cps)
    closed = set(base)
    for cp in sorted(base):
        ch = chr(cp)
        for form in ("NFD", "NFC"):
            try:
                mapped = unicodedata.normalize(form, ch)
            except (ValueError, TypeError):
                continue
            for out_ch in mapped:
                closed.add(ord(out_ch))
    return closed, sorted(closed - base)


def from_text(text: str) -> set:
    """文本 → 码位集合（去掉换行/制表等控制字符）。"""
    drop = {0x0A, 0x0D, 0x09}
    return set(ord(ch) for ch in text if ord(ch) not in drop)


def fallback_hint(lost, subset_cps) -> List[Dict[str, Any]]:
    """回退链建议（仅建议，不改判定）：按分区归组报子集可提供数量。"""
    lost = sorted(set(lost))
    subset_cps = set(subset_cps or ())
    if not lost:
        return []
    hints = []
    blocks = sorted(set(block_of(cp) for cp in lost))
    for block in blocks:
        avail = sum(1 for cp in subset_cps if block_of(cp) == block)
        hints.append({"block": block, "lost": sum(1 for cp in lost if block_of(cp) == block),
                      "subset_available_in_block": avail})
    return hints


def format_codepoints(cps, limit: int = 32) -> str:
    cps = list(cps)
    shown = ", ".join("U+%04X" % cp for cp in cps[:limit])
    if len(cps) > limit:
        shown += " …（共 %d 个）" % len(cps)
    return shown


# ---------------------------------------------------------------- coverage-diff（§六.2/§六.3）
def _evidence(cp: int, source_covered: bool, subset_covered) -> Dict[str, Any]:
    return {
        "codepoint": u(cp),
        "block": block_of(cp),
        "source_covered": bool(source_covered),
        "subset_covered": None if subset_covered is None else bool(subset_covered),
    }


def coverage_findings(result: Mapping[str, List[int]], subset_cps: set,
                      subset_present: bool, strict_source: bool) -> List[Dict[str, Any]]:
    """§六.2：每码位一条 finding；``MISSING_IN_SOURCE`` 级别随 strict_source 变。

    evidence 两个覆盖位都填**实测值**（不按分类反推）；``subset_covered`` 只在没给
    ``--subset`` 时是 None（该信息不存在，不猜）。
    """
    out = []
    missing_severity = "error" if strict_source else "warn"
    for cp in result["MISSING_IN_SOURCE"]:
        out.append(finding(
            "coverage-diff", spec.CODE_MISSING, missing_severity, u(cp),
            "需求字符 %s 在原字体里没有真实覆盖（映射到 .notdef 视同缺失）" % u(cp),
            evidence=_evidence(cp, False, None if not subset_present else cp in subset_cps),
            spec_ref=spec.COVERAGE_SPEC_REF))
    for cp in result["LOST_IN_SUBSET"]:
        out.append(finding(
            "coverage-diff", spec.CODE_LOST, "error", u(cp),
            "需求字符 %s 原字体有覆盖、子集产物丢失（静默丢字）" % u(cp),
            evidence=_evidence(cp, True, False),
            spec_ref=spec.COVERAGE_SPEC_REF))
    return out


def closure_summary(required0: set, source_cps: set, subset_cps: set,
                    subset_present: bool) -> Dict[str, Any]:
    """§六.2.1：闭包只计数、不产 finding；三分类仍只用 R0。"""
    _closed, added = closure(required0)
    added_set = set(added)
    missing = added_set - source_cps
    lost = (added_set & source_cps) - subset_cps if subset_present else set()
    return {
        "added": [u(cp) for cp in added],
        "added_codepoints": len(added),
        "missing_in_source": len(missing),
        "lost_in_subset": len(lost),
    }


def evaluate_coverage(required, source_cmap: Mapping[int, str],
                      subset_cmap: Optional[Mapping[int, str]] = None,
                      strict_source: bool = False,
                      source_cmap_facts: Optional[Mapping[str, Any]] = None,
                      subset_cmap_facts: Optional[Mapping[str, Any]] = None) -> Tuple[
        List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """覆盖差集：返回 ``(findings, skips, summary)``（旧仓 coverage_diff.evaluate 同构）。

    ``source_cmap``/``subset_cmap`` 是输入层摊平的 Unicode cmap 映射（尚剔 glyph0 前的
    ``{cp: glyphName}``）；两侧取不到 Unicode cmap 由输入层以 ``cmap_facts={"reason": ...}``
    显式传入 → SKIPPED 且 summary 为空（§六.3 两条失败路径不合并，不猜不给半份结论）。
    """
    required0 = set(int(cp) for cp in required)
    subset_present = subset_cmap is not None
    skips: List[Dict[str, Any]] = []
    source_stats = source_cmap_facts or {}
    subset_stats = subset_cmap_facts or {}
    for side, stats in (("source", source_stats), ("subset", subset_stats if subset_present else None)):
        reason = (stats or {}).get("reason") or ""
        if reason:
            detail = "%s: %s；subtables=%s" % (
                side,
                "字体没有 cmap 表" if reason == spec.REASON_NO_CMAP_TABLE
                else "cmap 表里没有 Unicode 子表（如仅 (1,0)/format 0）",
                [list(row) for row in (stats or {}).get("subtables", [])],
            )
            skips.append(skipped("coverage-diff", reason, detail))
    if skips:
        return ([], skips, {})

    source_cps = codepoints(source_cmap)
    subset_cps = codepoints(subset_cmap) if subset_present else None
    result = classify(required0, source_cps, subset_cps if subset_present else None)
    findings = coverage_findings(result, set(subset_cps or ()), subset_present, strict_source)

    blocks = {"required": block_counts(required0)}
    for key in spec.CATEGORIES:
        blocks[key] = block_counts(result[key])
    summary = {
        "required": {"count": len(required0), "blocks": blocks["required"]},
        "coverage": {
            "OK": [u(cp) for cp in result["OK"]],
            "MISSING_IN_SOURCE": [u(cp) for cp in result["MISSING_IN_SOURCE"]],
            "LOST_IN_SUBSET": [u(cp) for cp in result["LOST_IN_SUBSET"]],
            "counts": dict((key, len(result[key])) for key in spec.CATEGORIES),
            "blocks": dict((key, blocks[key]) for key in spec.CATEGORIES),
        },
        "closure": closure_summary(required0, set(source_cps), set(subset_cps or ()), subset_present),
        "fallback_hint": fallback_hint(result["LOST_IN_SUBSET"], subset_cps if subset_present else ()),
        "cmap": {
            "source_chosen": source_stats.get("chosen", []),
            "source_subtables": source_stats.get("subtables", []),
        },
        "strict_source": bool(strict_source),
        "subset_present": bool(subset_present),
    }
    if subset_present:
        summary["cmap"]["subset_chosen"] = subset_stats.get("chosen", [])
        summary["cmap"]["subset_subtables"] = subset_stats.get("subtables", [])
    return (findings, [], summary)


# ---------------------------------------------------------------- layout-survival（§六.5）
def _triple_key(table_tag: str, triple: Sequence[str]) -> str:
    """``GSUB/hani/ZHS /liga``（§六.5.1 排序键字面拼法）。"""
    script, langsys, feature = triple
    return "%s/%s/%s/%s" % (table_tag, script, langsys, feature)


def _is_renamed(source_target: Mapping[str, Any], subset_target: Mapping[str, Any]) -> bool:
    """§六.5.4 改名判定：两侧都 placeholder **不算**改名。"""
    src_state = source_target["state"]
    sub_state = subset_target["state"]
    if src_state == "named" and sub_state == "placeholder":
        return True
    if src_state == "named" and sub_state == "named":
        return source_target["glyph"] != subset_target["glyph"]
    return False


def _u_list(codepoints) -> List[str]:
    return ["U+%04X" % cp for cp in codepoints]


def _ligature_index(flat: Optional[Mapping[str, Any]]) -> Dict[Tuple[int, ...], Dict[str, Any]]:
    """``{inputs_codepoints: {"glyph", "state"}}`` —— 输入层已按码位视图摊平
    （§六.5.4 的反查与占位名判定在输入层做；同输入序列保留首次 = 最高优先级）。"""
    index: Dict[Tuple[int, ...], Dict[str, Any]] = {}
    if flat is None:
        return index
    for row in flat.get("ligature_index", []):
        key = tuple(int(cp) for cp in row["inputs"])
        if key in index:
            continue
        index[key] = {"glyph": row["glyph"], "state": row["state"]}
    return index


def _ligature_feature(flat: Optional[Mapping[str, Any]]) -> str:
    """连字规则归属 feature 标签（含 ``liga`` 取 liga，否则字母序最小）。"""
    labels = (flat or {}).get("ligature_features") or []
    if "liga" in labels:
        return "liga"
    if not labels:
        return "-"
    return labels[0]


def _feature_lost_findings(source_flat: Mapping[str, Any],
                           subset_flat: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """§六.5.3：四元组差集，每个丢失的三元组一条。"""
    out = []
    for table_tag in spec.LAYOUT_TAGS:
        src = source_flat[table_tag]
        if src is None:
            continue
        out_set = set(subset_flat[table_tag]["triples"]) if subset_flat[table_tag] else set()
        for triple in src["triples"]:
            if triple in out_set:
                continue
            out.append(finding(
                "layout-survival", spec.CODE_FEATURE_LOST, "error",
                _triple_key(table_tag, triple),
                "%s 的 %s/%s 布局三元组在产物里消失（原字体存在）" % (
                    table_tag, triple[0], triple[1]),
                evidence={
                    "table": table_tag,
                    "script": triple[0],
                    "langsys": triple[1],
                    "feature": triple[2],
                    "source_present": True,
                    "subset_present": False,
                },
                spec_ref=spec.LAYOUT_SPEC_REF))
    return out


def _ligature_findings(source_flat, subset_flat) -> Tuple[List[Dict[str, Any]], int, int]:
    """§六.5.4：连字规则差分（LOST 优先于 RENAMED，互斥）。"""
    findings = []
    renamed = 0
    lost = 0
    for table_tag in spec.LAYOUT_TAGS:
        src = source_flat[table_tag]
        if src is None or not src.get("ligature_index"):
            continue
        sub = subset_flat[table_tag]
        src_index = _ligature_index(src)
        sub_index = _ligature_index(sub)
        if not src_index:
            continue
        feature = _ligature_feature(src)
        for inputs_cps in sorted(src_index):
            target_src = src_index[inputs_cps]
            key = "%s/%s/%s" % (table_tag, feature, "+".join(_u_list(inputs_cps)))
            if inputs_cps not in sub_index:
                lost += 1
                findings.append(finding(
                    "layout-survival", spec.CODE_LIGATURE_LOST, "error", key,
                    "%s 连字规则 %s 在产物里消失" % (table_tag, "+".join(_u_list(inputs_cps))),
                    evidence={
                        "table": table_tag,
                        "feature": feature,
                        "inputs": _u_list(inputs_cps),
                        "ligature_source_glyph": target_src["glyph"],
                        "ligature_source_state": target_src["state"],
                        "ligature_subset_glyph": None,
                    },
                    spec_ref=spec.LAYOUT_SPEC_REF))
                continue
            target_out = sub_index[inputs_cps]
            if _is_renamed(target_src, target_out):
                renamed += 1
                findings.append(finding(
                    "layout-survival", spec.CODE_LIGATURE_RENAMED, "warn", key,
                    "%s 连字规则 %s 仍生效，但目标字形改名（%s → %s）" % (
                        table_tag, "+".join(_u_list(inputs_cps)),
                        target_src["glyph"], target_out["glyph"]),
                    evidence={
                        "table": table_tag,
                        "feature": feature,
                        "inputs": _u_list(inputs_cps),
                        "ligature_source_glyph": target_src["glyph"],
                        "ligature_source_state": target_src["state"],
                        "ligature_subset_glyph": target_out["glyph"],
                        "ligature_subset_state": target_out["state"],
                    },
                    spec_ref=spec.LAYOUT_SPEC_REF))
    return findings, lost, renamed


def _counts(flat: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """§六.5.2 的四个计数 + 直方图，按固定键序。"""
    if flat is None:
        return {
            "present": False, "lookups": 0, "subtables_raw": 0, "subtables_naive": 0,
            "extension_lookups": 0, "subtable_types": {},
            "ligature_rules_raw": 0, "ligature_rules_naive": 0, "feature_variations": 0,
        }
    return {
        "present": True,
        "lookups": flat["lookups"],
        "subtables_raw": flat["subtables_raw"],
        "subtables_naive": flat["subtables_naive"],
        "extension_lookups": flat["extension_lookups"],
        "subtable_types": dict((str(k), v) for k, v in sorted(flat["subtable_types"].items())),
        "ligature_rules_raw": flat["ligature_rules_raw"],
        "ligature_rules_naive": flat["ligature_rules_naive"],
        "feature_variations": flat["feature_variations"],
    }


def _triple_summary(flat: Mapping[str, Any]) -> Dict[str, Any]:
    out = {}
    for tag in spec.LAYOUT_TAGS:
        value = flat[tag]
        out[tag] = {"present": value is not None,
                    "count": len(value["triples"]) if value is not None else 0}
    return out


def _triple_delta(source_flat, subset_flat) -> Tuple[int, int]:
    """§六.5.2 的 kept/lost（跨两侧四元组量；lost + kept == |T_src|）。"""
    lost = 0
    kept = 0
    for tag in spec.LAYOUT_TAGS:
        src = source_flat[tag]
        if src is None:
            continue
        src_set = set(src["triples"])
        out_set = set(subset_flat[tag]["triples"]) if subset_flat[tag] is not None else set()
        lost += len(src_set - out_set)
        kept += len(src_set & out_set)
    return lost, kept


def compare_layout(source_flat, subset_flat) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """布局保真判定（旧仓 ``_compare``；字体对象摊平由输入层完成）。"""
    src_has = any(source_flat[tag] is not None for tag in spec.LAYOUT_TAGS)
    sub_has = any(subset_flat[tag] is not None for tag in spec.LAYOUT_TAGS)

    # §六.5.5：两侧都没有 → 显式跳过且 summary 为空（不猜）
    if not src_has and not sub_has:
        return (
            [],
            [skipped("layout-survival", spec.REASON_NO_TABLES,
                     "source: 无 GSUB/GPOS；subset: 无 GSUB/GPOS")],
            {},
        )

    skips = []
    if not src_has or not sub_has:
        side = "source" if not src_has else "subset"
        skips.append(skipped(
            "layout-survival", spec.REASON_ONE_SIDE,
            "%s: 该侧没有 GSUB/GPOS（另一侧有）→ 全量丢失去重报，不放弃整份判定" % side))

    findings = _feature_lost_findings(source_flat, subset_flat)
    lig_findings, lig_lost, lig_renamed = _ligature_findings(source_flat, subset_flat)
    findings.extend(lig_findings)
    lost_triples, kept_triples = _triple_delta(source_flat, subset_flat)

    summary = {
        "layout": {
            "spec_ref": spec.LAYOUT_SPEC_REF,
            "ligature_scope": spec.LIGATURE_SCOPE_ALL,
            "source": {"gsub": _counts(source_flat["GSUB"]), "gpos": _counts(source_flat["GPOS"]),
                       "triples": _triple_summary(source_flat)},
            "subset": {"gsub": _counts(subset_flat["GSUB"]), "gpos": _counts(subset_flat["GPOS"]),
                       "triples": _triple_summary(subset_flat)},
            "kept": {"triples": kept_triples},
            "lost": {"triples": lost_triples, "ligature_rules": lig_lost,
                     "ligature_renamed": lig_renamed},
        }
    }
    return (findings, skips, summary)


# ---------------------------------------------------------------- metadata（§六.9）
def _name_state(subset_ids: Mapping[int, str], source_ids: Optional[Mapping[int, str]]):
    """``(present, missing, classes)`` —— 分类需要两侧的 ID 集合（§六.9.1）。"""
    present = [nid for nid in spec.REQUIRED_NAME_IDS if subset_ids.get(nid)]
    missing = [nid for nid in spec.REQUIRED_NAME_IDS if not subset_ids.get(nid)]
    classes = {spec.CLASS_DEFAULT_STRIPPED: [], spec.CLASS_AUTHOR_ABSENT: [],
               spec.CLASS_UNCLASSIFIED: []}
    for nid in missing:
        if source_ids is None:
            classes[spec.CLASS_UNCLASSIFIED].append(nid)
        elif source_ids.get(nid):
            classes[spec.CLASS_DEFAULT_STRIPPED].append(nid)
        else:
            classes[spec.CLASS_AUTHOR_ABSENT].append(nid)
    return present, missing, classes


def _name_findings(classes: Mapping[str, List[int]]) -> List[Dict[str, Any]]:
    """只有「默认剥离」产 finding；author_absent / unclassified 都不产。"""
    out = []
    for nid in classes[spec.CLASS_DEFAULT_STRIPPED]:
        code, spec_ref = spec.NAME_CODES[nid]
        out.append(finding(
            "metadata", code, "warn", "nameID%d" % nid,
            "原字体有 nameID %d，产物里没有（默认 name_IDs 白名单把它剥掉了）" % nid,
            evidence={
                "nameID": nid,
                "source_present": True,
                "subset_present": False,
                "classification": spec.CLASS_DEFAULT_STRIPPED,
            },
            spec_ref=spec_ref))
    return out


def codepage_findings(os2: Mapping[str, Any], codepoints: Iterable[int]) -> List[Dict[str, Any]]:
    """**只判 bit0**（§六.9.2）：声称 Latin-1 而 ``C ∩ [U+0000, U+00FF] = ∅``。"""
    bits = (os2.get("codepage_bits") or [])
    if 0 not in bits:
        return []
    if any(cp <= spec.LATIN1_HI for cp in codepoints):
        return []
    return [finding(
        "metadata", spec.CODE_CODEPAGE_LATIN1, "error", "cp1:latin1",
        "ulCodePageRange1 bit0 声明支持 Latin-1，但 cmap 里没有任何 U+0000–U+00FF 码位"
        "（fontTools 的 recalcCodePageRanges 在无码页可用时回退置 bit0）",
        evidence={
            "ulCodePageRange1": os2.get("ulCodePageRange1", "0x00000001"),
            "claims_latin1": True,
            "latin1_codepoints": 0,
            "codepoints_total": len(list(codepoints)) if not isinstance(codepoints, (set, frozenset)) else len(codepoints),
        },
        spec_ref=spec.CODEPAGE_LATIN1_SPEC_REF)]


def is_behavioral_bit(bit: int, unicode_ranges: Sequence[Any]) -> bool:
    """该位是否**行为型**（§六.9.3：全部区间都落在代理区 = "含 BMP 之外的码位"）。"""
    ranges = _range_table_entry(bit, unicode_ranges)
    if not ranges:
        return False
    return all(0xD800 <= lo and hi <= 0xDFFF for lo, hi in ranges)


def _range_table_entry(bit: int, unicode_ranges: Sequence[Any]) -> Optional[List[Tuple[int, int]]]:
    if unicode_ranges is None or bit < 0 or bit >= len(unicode_ranges):
        return None
    return [tuple(rng) for _name, rng in unicode_ranges[bit]]


def _bit_satisfied(bit: int, codepoints: set, unicode_ranges) -> bool:
    if is_behavioral_bit(bit, unicode_ranges):
        return any(cp > 0xFFFF for cp in codepoints)
    ranges = _range_table_entry(bit, unicode_ranges)
    if not ranges:
        return False
    for lo, hi in ranges:
        for cp in codepoints:
            if lo <= cp <= hi:
                return True
    return False


def unicode_range_findings(os2: Mapping[str, Any], codepoints: set,
                           unicode_ranges: Sequence[Any]) -> Tuple[List[Dict[str, Any]], List[int]]:
    """§六.9.3：置位但 cmap 无该块码位 → warn（只判过度；欠声明**不判**）。"""
    bits = sorted(os2.get("unicode_range_bits") or [])
    unknown = []
    out = []
    for bit in bits:
        ranges = _range_table_entry(bit, unicode_ranges)
        if ranges is None:
            unknown.append(bit)
            continue
        if _bit_satisfied(bit, codepoints, unicode_ranges):
            continue
        out.append(finding(
            "metadata", spec.CODE_UNICODE_OVER, "warn", "ur:bit%d" % bit,
            "ulUnicodeRange 第 %d 位置位，但 cmap 在该位声明的 %s 里没有任何码位" % (
                bit, "非 BMP 码位" if is_behavioral_bit(bit, unicode_ranges) else "Unicode 块"),
            evidence={
                "bit": bit,
                "declared": True,
                "covered_codepoints": 0,
                "behavioral": is_behavioral_bit(bit, unicode_ranges),
                "blocks": [name for name, _rng in unicode_ranges[bit]],
            },
            spec_ref=spec.METADATA_SPEC_REF))
    return out, unknown


def unicode_range_summary(os2: Mapping[str, Any], codepoints: set,
                          unicode_ranges: Sequence[Any]) -> Dict[str, Any]:
    """declared / over_declared / under_declared 三个量都报（**只判过度**）。"""
    bits = sorted(os2.get("unicode_range_bits") or [])
    over = [b for b in bits
            if _range_table_entry(b, unicode_ranges) is not None
            and not _bit_satisfied(b, codepoints, unicode_ranges)]
    covered = set()
    for bit in range(len(unicode_ranges or [])):
        if _bit_satisfied(bit, codepoints, unicode_ranges):
            covered.add(bit)
    return {
        "declared": bits,
        "over_declared": over,
        # §六.9.3：欠声明不判（位是可选自我声明；实测欠声明率 91–254/559）
        "under_declared": sorted(covered - set(bits)),
        "declared_empty": not bits,
    }


def maxp_findings(declared, measured: Optional[int]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """§六.9.4：``maxp.numGlyphs`` vs 独立量（loca / CFF CharStrings）。"""
    if measured is None:
        return [], None
    if declared is None or int(declared) == measured:
        return [], measured
    return [finding(
        "metadata", spec.CODE_MAXP_MISMATCH, "error", "maxp",
        "maxp.numGlyphs = %d，但轮廓表的独立字形计数 = %d" % (declared, measured),
        evidence={"numGlyphs": int(declared), "measured": int(measured)},
        spec_ref=spec.METADATA_SPEC_REF)], measured


def char_index_findings(os2: Mapping[str, Any], codepoints: set) -> Tuple[List[Dict[str, Any]], bool]:
    """§六.9.5：只判"没覆盖住"方向；``0xFFFF`` 是哨兵（该方向不判）。"""
    bmp = [cp for cp in codepoints if cp <= spec.BMP_MAX]
    if not bmp:
        return [], False
    lo, hi = min(bmp), max(bmp)
    first = int(os2.get("usFirstCharIndex", 0xFFFF))
    last = int(os2.get("usLastCharIndex", 0xFFFF))
    out = []
    if first != 0xFFFF and lo < first:
        out.append(finding(
            "metadata", spec.CODE_CHAR_INDEX, "warn", "usFirstCharIndex",
            "usFirstCharIndex = 0x%04X，但 cmap 里存在更低的 BMP 码位 U+%04X" % (first, lo),
            evidence={"field": "usFirstCharIndex", "declared": "0x%04X" % first,
                      "measured_min": "U+%04X" % lo},
            spec_ref=spec.METADATA_SPEC_REF))
    if last != 0xFFFF and hi > last:
        out.append(finding(
            "metadata", spec.CODE_CHAR_INDEX, "warn", "usLastCharIndex",
            "usLastCharIndex = 0x%04X，但 cmap 里存在更高的 BMP 码位 U+%04X" % (last, hi),
            evidence={"field": "usLastCharIndex", "declared": "0x%04X" % last,
                      "measured_max": "U+%04X" % hi},
            spec_ref=spec.METADATA_SPEC_REF))
    if first != 0xFFFF and last != 0xFFFF and first > last:
        out.append(finding(
            "metadata", spec.CODE_CHAR_INDEX, "warn", "usFirstCharIndex",
            "usFirstCharIndex = 0x%04X 大于 usLastCharIndex = 0x%04X（区间为空）" % (first, last),
            evidence={"field": "usFirstCharIndex", "declared": "0x%04X" % first,
                      "usLastCharIndex": "0x%04X" % last},
            spec_ref=spec.METADATA_SPEC_REF))
    return out, True
