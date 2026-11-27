"""判决层：方向 / 双重旋转 / 色彩 / 容器 / 消费者矩阵。

输入是输入层解析好的**事实**（``subject.facts``）：不解码像素、不读字节、不读时钟。
每条 finding = ``{rule_id, code, severity, confidence, message, evidence, module}``；
severity 用旧仓的 ``info/warning/error/unknown`` 词表，映射到账本判决时一律不高于 warn，
阻断只由 ``io-gate`` 表达。
"""

from __future__ import annotations

import re

from . import spec

_XMP_RES = tuple(re.compile(pattern) for pattern in spec.XMP_PATTERNS)


def finding(rule_id, code, severity, confidence, message, evidence, module):
    return {
        "rule_id": rule_id,
        "code": code,
        "severity": severity,
        "confidence": confidence,
        "message": message,
        "evidence": evidence,
        "module": module,
    }


# ------------------------------------------------------------------ 方向
def read_xmp_orientation(text):
    """从 XMP 文本读方向值；两种写法都认，非 1..8 返回 ``None``。"""
    if not isinstance(text, str):
        return None
    for regex in _XMP_RES:
        match = regex.search(text)
        if match:
            value = int(match.group(1))
            return value if value in spec.ORIENTATION_MATRIX else None
    return None


def transform_for(value):
    flip_h, flip_v, rotate, swap = spec.ORIENTATION_MATRIX[value]
    return {
        "flip_h": flip_h,
        "flip_v": flip_v,
        "rotate_cw_deg": rotate,
        "swap_wh": swap,
        "label": spec.ORIENTATION_LABELS[value],
    }


def effective_size(width, height, value):
    if value is not None and spec.ORIENTATION_MATRIX[value][3]:
        return height, width
    return width, height


def analyze_orientation(facts):
    findings = []
    sources = []
    for row in facts.get("exif") or []:
        if not isinstance(row, dict):
            raise ValueError("facts.exif 的每一项必须是对象")
        ifd = row.get("ifd", "ifd0")
        if row.get("type") != 3:
            findings.append(
                finding(
                    spec.RULE_ORIENTATION_TYPE,
                    "orientation_not_int16u",
                    "error",
                    "certain",
                    "%s 的 274 类型是 %r（需要 3/int16u）" % (ifd, row.get("type")),
                    {"ifd": ifd, "type": row.get("type"), "offset": row.get("offset")},
                    "orientation",
                )
            )
            sources.append({"source": "exif." + ifd, "value": None, "state": "not_int16u"})
            continue
        value = row.get("value")
        if value is None:
            sources.append({"source": "exif." + ifd, "value": None, "state": "absent"})
            continue
        if value not in spec.ORIENTATION_MATRIX:
            findings.append(
                finding(
                    spec.RULE_ORIENTATION_RANGE,
                    "orientation_out_of_range",
                    "error",
                    "certain",
                    "%s = %r，超出 1..8" % (ifd, value),
                    {"ifd": ifd, "value": value, "offset": row.get("offset")},
                    "orientation",
                )
            )
            sources.append({"source": "exif." + ifd, "value": value, "state": "out_of_range"})
            continue
        sources.append({"source": "exif." + ifd, "value": value, "state": "present"})

    xmp_value = read_xmp_orientation(facts.get("xmp"))
    if xmp_value is not None:
        sources.append({"source": "xmp.tiff:Orientation", "value": xmp_value, "state": "present"})

    primary = None
    for source in sources:
        if source["source"] == "exif.ifd0" and source["state"] == "present":
            primary = source["value"]
    if primary is None:
        primary = xmp_value

    if not any(source["source"] == "exif.ifd0" for source in sources):
        findings.append(
            finding(
                spec.RULE_ORIENTATION_ABSENT,
                "orientation_absent",
                "info",
                "certain",
                "容器没有 EXIF Orientation（absent 不等于 =1）",
                {"kind": facts.get("kind")},
                "orientation",
            )
        )
    if xmp_value is not None:
        findings.append(
            finding(
                spec.RULE_ORIENTATION_XMP,
                "orientation_xmp_present",
                "info",
                "certain",
                "XMP 携带 tiff:Orientation=%d" % xmp_value,
                {"value": xmp_value},
                "orientation",
            )
        )
    width, height = facts.get("width"), facts.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("facts.width / facts.height 必须是整数")
    effective = effective_size(width, height, primary)
    return {
        "findings": findings,
        "sources": sources,
        "primary": primary,
        "effective_width": effective[0],
        "effective_height": effective[1],
    }


# ------------------------------------------------------------------ 双重旋转
CONSUMER_CHAINS = (
    {
        "consumer": "jpegtran -copy all -rotate 90",
        "trigger": "jpegtran 不读方向；-copy all 时缩略图原样复制",
        "consequences": {1: "主图被转过而 IFD1 缩略图原样复制 → 缩略图仍按旧方向显示"},
    },
    {
        "consumer": "sharp.autoOrient()",
        "trigger": "只按 EXIF tag 274 归一",
        "consequences": {
            2: "EXIF 归 1 但 XMP 未改写 → 下游读 XMP 的软件再转一次",
            3: "像素已转正而 tag 未重置时，autoOrient() 会再转一次",
        },
    },
    {
        "consumer": "ImageMagick -auto-orient",
        "trigger": "读并重置 EXIF Orientation；已修正但 tag 未重置的图照转",
        "consequences": {
            2: "XMP 侧仍留旧值，可能被第二次旋转",
            3: "已修正但 tag 未重置，可能被第二次旋转",
        },
    },
)

CONDITION_CODES = {
    1: "double_rotate_ifd1_unsynced",
    2: "double_rotate_xmp_conflict",
    3: "double_rotate_bigedge_mismatch",
}
CONDITION_CONFIDENCE = {1: "certain", 2: "certain", 3: "gray-heuristic"}
CONDITION_SEVERITY = {1: "warning", 2: "warning", 3: "suspicion"}


def analyze_double_rotate(facts):
    base = analyze_orientation(facts)
    values = {source["source"]: source["value"] for source in base["sources"] if source["state"] == "present"}
    entries = []

    ifd0 = values.get("exif.ifd0")
    ifd1 = values.get("exif.ifd1")
    if ifd0 is not None and ifd1 is not None and ifd0 != ifd1:
        entries.append(_condition(1, "IFD0=%d 与 IFD1=%d 不一致" % (ifd0, ifd1), {"ifd0": ifd0, "ifd1": ifd1}))

    xmp = values.get("xmp.tiff:Orientation")
    if ifd0 is not None and xmp is not None and ifd0 != xmp:
        entries.append(_condition(2, "EXIF=%d 与 XMP=%d 不一致" % (ifd0, xmp), {"exif": ifd0, "xmp": xmp}))

    primary = base["primary"]
    width, height = facts.get("width"), facts.get("height")
    if primary in spec.ROTATING_VALUES and isinstance(width, int) and isinstance(height, int) and width > height:
        entries.append(
            _condition(3, "声明 %d（旋转类）但存储宽 > 高（%dx%d）" % (primary, width, height), {"value": primary, "width": width, "height": height})
        )

    verdicts = []
    for entry in entries:
        for chain in CONSUMER_CHAINS:
            consequence = chain["consequences"].get(entry["condition"])
            if consequence:
                verdicts.append(
                    {
                        "consumer": chain["consumer"],
                        "condition": entry["condition"],
                        "trigger_chain": chain["trigger"],
                        "consequence": consequence,
                    }
                )
    return {"findings": base["findings"] + entries, "sources": base["sources"], "primary": primary, "verdicts": verdicts, "base": base}


def _condition(number, message, evidence):
    entry = finding(
        {1: spec.RULE_DOUBLE_IFD1, 2: spec.RULE_DOUBLE_XMP, 3: spec.RULE_DOUBLE_BIGEDGE}[number],
        CONDITION_CODES[number],
        CONDITION_SEVERITY[number],
        CONDITION_CONFIDENCE[number],
        message,
        evidence,
        "double-rotate",
    )
    entry["condition"] = number
    return entry


# ------------------------------------------------------------------ 色彩
def _icc_findings(icc):
    findings = []
    if not icc:
        findings.append(finding(spec.RULE_COLOR_ICC, "icc_missing", "info", "certain", "没有 ICC profile", {"carrier": None}, "color"))
        return findings, {"present": False}

    findings.append(finding(spec.RULE_COLOR_ICC, "icc_present", "info", "certain", "ICC profile 存在（%s）" % icc.get("carrier"), {"carrier": icc.get("carrier")}, "color"))
    declared = icc.get("declared_segments")
    seen = icc.get("segments_seen") or []
    if isinstance(declared, int) and declared > 0 and sorted(seen) != list(range(1, declared + 1)):
        findings.append(
            finding(
                spec.RULE_COLOR_ICC_GAP,
                "icc_segment_gap",
                "error",
                "certain",
                "APP2 分片不连续：声明 %d 段，实际 %s" % (declared, sorted(seen)),
                {"declared": declared, "seen": sorted(seen)},
                "color",
            )
        )
    if icc.get("compressed"):
        findings.append(
            finding(
                spec.RULE_COLOR_ICC_UNKNOWN,
                "compressed_profile_not_inspected",
                "unknown",
                "gray",
                "PNG iCCP 压缩流未解压（首期硬约束）",
                {"carrier": icc.get("carrier")},
                "color",
            )
        )
        return findings, {"present": True, "inspected": False}

    header = icc.get("header")
    if not isinstance(header, dict):
        findings.append(finding(spec.RULE_COLOR_ICC_HEADER, "icc_header_truncated", "error", "certain", "ICC 头不足 128 字节", {}, "color"))
        return findings, {"present": True, "inspected": False}
    if header.get("signature") != "acsp":
        findings.append(finding(spec.RULE_COLOR_ICC_HEADER, "icc_bad_signature", "error", "certain", "ICC 签名不是 acsp", dict(header), "color"))
    size, declared_size = header.get("size"), header.get("declared_size")
    if isinstance(size, int) and isinstance(declared_size, int) and size != declared_size:
        findings.append(finding(spec.RULE_COLOR_ICC_HEADER, "icc_size_mismatch", "error", "certain", "ProfileSize=%d 与实际 %d 不符" % (size, declared_size), dict(header), "color"))
    klass = header.get("class")
    if klass in spec.KNOWN_CLASSES:
        findings.append(finding(spec.RULE_COLOR_ICC_CLASS, "icc_class_legal", "info", "certain", "ProfileClass=%r 在白名单内" % klass, dict(header), "color"))
    elif klass in spec.OTHER_LEGAL_CLASSES:
        findings.append(finding(spec.RULE_COLOR_ICC_CLASS, "icc_class_legal", "info", "certain", "ProfileClass=%r 合法但非首期白名单" % klass, dict(header), "color"))
    else:
        findings.append(finding(spec.RULE_COLOR_ICC_CLASS, "icc_unknown_class", "warning", "certain", "ProfileClass=%r 未知" % klass, dict(header), "color"))
    if header.get("space") not in spec.KNOWN_SPACES:
        findings.append(finding(spec.RULE_COLOR_ICC_SPACE, "icc_unknown_space", "warning", "certain", "ColorSpaceData=%r 未知" % header.get("space"), dict(header), "color"))
    if header.get("pcs") not in spec.KNOWN_SPACES:
        findings.append(finding(spec.RULE_COLOR_ICC_SPACE, "icc_unknown_space", "warning", "certain", "PCS=%r 未知" % header.get("pcs"), dict(header), "color"))
    intent = header.get("intent")
    if intent not in (0, 1, 2, 3):
        findings.append(finding(spec.RULE_COLOR_ICC_HEADER, "icc_bad_intent", "warning", "certain", "RenderingIntent=%r 不在 0..3" % (intent,), dict(header), "color"))
    return findings, {"present": True, "inspected": True}


def analyze_color(facts):
    findings, icc_facts = _icc_findings(facts.get("icc"))
    png = facts.get("png") or {}
    chunks = png.get("chunks") or []
    if "iCCP" in chunks and "sRGB" in chunks:
        findings.append(finding(spec.RULE_COLOR_ICCP_SRGB, "iccp_srgb_conflict", "warning", "certain", "iCCP 与 sRGB 同时存在", {"chunks": chunks}, "color"))
    markers = [name for name in ("gAMA", "cHRM", "sRGB", "iCCP") if name in chunks]
    if markers:
        findings.append(finding(spec.RULE_COLOR_MARKERS, "color_markers", "info", "certain", "色彩 chunk：%s" % ", ".join(markers), {"markers": markers}, "color"))
    depth = facts.get("bit_depth")
    if depth is None:
        findings.append(finding(spec.RULE_COLOR_BITDEPTH, "color_bit_depth_unknown", "unknown", "gray", "位深不在可读字段内", {"kind": facts.get("kind")}, "color"))
    else:
        findings.append(finding(spec.RULE_COLOR_BITDEPTH, "color_bit_depth", "info", "certain", "位深 %s bit" % depth, {"bit_depth": depth}, "color"))
    if facts.get("cmyk"):
        findings.append(finding(spec.RULE_COLOR_CMYK, "cmyk_jpeg", "warning", "certain", "四分量 JPEG（CMYK）", {"components": 4}, "color"))
    for row in spec.DEFAULT_ASSUMPTIONS:
        findings.append(finding(spec.RULE_COLOR_DEFAULTS, "color_default_assumption", "info", "certain", "%s 无 profile 时默认 %s" % (row["consumer"], row["assumption"]), dict(row), "color"))
    return {"findings": findings, "icc": icc_facts, "defaults": list(spec.DEFAULT_ASSUMPTIONS)}


# ------------------------------------------------------------------ 容器
_COLOR_BEFORE = ("cHRM", "cICP", "gAMA", "iCCP", "sBIT", "sRGB")
_PRE_IDAT = ("acTL", "eXIf", "pHYs", "sPLT")
_AFTER_PLTE_BEFORE_IDAT = ("bKGD", "hIST", "tRNS")


def _png_order_findings(chunks):
    findings = []

    def violation(rule, detail, index):
        findings.append(finding(spec.RULE_CONTAINER_PNG_ORDER, "png_chunk_order", "error", "certain", "%s（位置 %d）" % (detail, index), {"rule": rule, "index": index, "chunks": list(chunks)}, "container"))

    if not chunks:
        return findings
    if chunks[0] != "IHDR":
        violation("ihdr_first", "IHDR 不是首块", 0)
    if chunks[-1] != "IEND":
        violation("iend_last", "IEND 不是末块", len(chunks) - 1)
    if "PLTE" in chunks and "IDAT" in chunks and chunks.index("PLTE") > chunks.index("IDAT"):
        violation("plte_before_idat", "PLTE 在 IDAT 之后", chunks.index("PLTE"))
    idat_positions = [index for index, name in enumerate(chunks) if name == "IDAT"]
    if idat_positions and idat_positions != list(range(idat_positions[0], idat_positions[0] + len(idat_positions))):
        violation("idat_consecutive", "IDAT 不连续", idat_positions[0])
    first_idat = chunks.index("IDAT") if "IDAT" in chunks else len(chunks)
    for name in _COLOR_BEFORE:
        if name in chunks and chunks.index(name) > first_idat:
            violation("color_before_idat", "%s 在 IDAT 之后" % name, chunks.index(name))
    for name in _PRE_IDAT:
        if name in chunks and chunks.index(name) > first_idat:
            violation("pre_idat", "%s 在 IDAT 之后" % name, chunks.index(name))
    plte = chunks.index("PLTE") if "PLTE" in chunks else -1
    for name in _AFTER_PLTE_BEFORE_IDAT:
        if name in chunks:
            index = chunks.index(name)
            if plte >= 0 and index < plte:
                violation("after_plte", "%s 在 PLTE 之前" % name, index)
            if index > first_idat:
                violation("before_idat", "%s 在 IDAT 之后" % name, index)
    fctl = [index for index, name in enumerate(chunks) if name == "fcTL"]
    if fctl:
        before = [index for index in fctl if index < first_idat]
        after = [index for index in fctl if index > first_idat]
        if len(before) > 1:
            violation("fctl_before_idat", "IDAT 前出现多个 fcTL", before[1])
        if after and not before:
            violation("fctl_after_idat", "没有 IDAT 前的 fcTL", after[0])
    for index, name in enumerate(chunks):
        if name == "fdAT" and index < first_idat:
            violation("fdat_after_idat", "fdAT 在 IDAT 之前", index)
    return findings


def _frame_unit(kind):
    return {"gif": "1/100s", "png": "num/den", "webp": "ms", "avif": "not-in-band"}.get(kind, "ms")


def analyze_container(facts):
    findings = []
    kind = facts.get("kind")
    if not isinstance(kind, str):
        raise ValueError("facts.kind 必须是字符串")
    if kind == "png":
        findings.extend(_png_order_findings(facts.get("png", {}).get("chunks") or []))
        if facts.get("png", {}).get("crc_ok") is False:
            findings.append(finding(spec.RULE_CONTAINER_PNG_CRC, "png_crc_missing", "error", "certain", "PNG chunk 缺 CRC 或 CRC 不匹配", {"kind": kind}, "container"))
        fctl_sequences = facts.get("png", {}).get("fctl_sequences") or []
        if fctl_sequences:
            if fctl_sequences != list(range(len(fctl_sequences))):
                findings.append(finding(spec.RULE_CONTAINER_APNG, "apng_sequence", "error", "certain", "fcTL 序号不连续：%s" % fctl_sequences, {"sequences": fctl_sequences}, "container"))
    if kind == "webp" and facts.get("frames"):
        if "ANIM" not in (facts.get("chunks") or []):
            findings.append(finding(spec.RULE_CONTAINER_WEBP, "webp_anim_missing", "warning", "certain", "有帧但缺 ANIM 块", {"kind": kind}, "container"))
    if kind == "gif" and facts.get("frames"):
        if "GCE" not in (facts.get("gif_blocks") or []):
            findings.append(finding(spec.RULE_CONTAINER_GIF, "gif_gce_missing", "warning", "certain", "帧没有图形控制扩展", {"kind": kind}, "container"))
    for frame in facts.get("frames") or []:
        if not isinstance(frame, dict):
            raise ValueError("facts.frames 的每一项必须是对象")
        expected = _frame_unit(kind)
        raw_unit = frame.get("raw_unit")
        duration = frame.get("duration_ms")
        if raw_unit != expected:
            findings.append(
                finding(
                    spec.RULE_CONTAINER_FRAME,
                    "frame_unit",
                    "warning",
                    "certain",
                    "第 %s 帧单位 %r ≠ %s" % (frame.get("index"), raw_unit, expected),
                    {"index": frame.get("index"), "raw_unit": raw_unit, "expected": expected},
                    "container",
                )
            )
        if duration is None:
            findings.append(
                finding(
                    spec.RULE_CONTAINER_FRAME,
                    "frame_duration_unknown",
                    "unknown",
                    "gray",
                    "第 %s 帧时长不在样本内" % frame.get("index"),
                    {"index": frame.get("index")},
                    "container",
                )
            )
    if kind == "jpeg":
        markers = facts.get("jpeg_markers") or []
        if "APP1" in markers and "APP2" not in markers:
            findings.append(finding(spec.RULE_CONTAINER_JPEG, "jpeg_no_icc", "info", "certain", "JPEG 有 APP1 但没有 APP2", {"markers": markers}, "container"))
    return {"findings": findings, "kind": kind, "frames": len(facts.get("frames") or [])}


# ------------------------------------------------------------------ 消费者
def _risk_rows(facts):
    double = analyze_double_rotate(facts)
    conditions = {entry["code"] for entry in double["findings"] if entry.get("code", "").startswith("double_rotate")}
    rows = []
    for consumer in spec.MATRIX_ROWS:
        name = consumer["consumer"]
        if not conditions:
            risk = "low"
        elif name in ("sharp", "imagemagick"):
            risk = "high"
        elif consumer["confidence"] == "gray":
            risk = "unknown"
        else:
            risk = "medium"
        rows.append(
            {
                "consumer": name,
                "risk": risk,
                "severity": {v: k for k, v in spec.RISK_BY_SEVERITY.items()}.get(risk, "info"),
                "trigger": sorted(conditions),
                "confidence": consumer["confidence"],
            }
        )
    return rows


def validate_matrix(rows):
    """9 行 × 5 列；值域与置信度词表逐格校验。返回问题列表。"""
    problems = []
    if len(rows) != len(spec.CONSUMERS):
        problems.append("行数 %d ≠ %d" % (len(rows), len(spec.CONSUMERS)))
    seen = set()
    for row in rows:
        consumer = row.get("consumer")
        seen.add(consumer)
        for column in spec.COLUMNS:
            value = row.get(column)
            if column == "dropped_chunks":
                if not isinstance(value, list):
                    problems.append("%s.%s 必须是数组" % (consumer, column))
                continue
            allowed = spec.VALUE_VOCAB[column]
            if value not in allowed:
                problems.append("%s.%s=%r 不在词表内" % (consumer, column, value))
        if row.get("confidence") not in spec.CONFIDENCES:
            problems.append("%s.confidence=%r 不在词表内" % (consumer, row.get("confidence")))
    if seen != set(spec.CONSUMERS):
        problems.append("行集合与消费者集合不一致")
    return problems


def analyze_consumers(facts):
    findings = []
    problems = validate_matrix(spec.MATRIX_ROWS)
    rows = spec.MATRIX_ROWS
    if facts.get("matrix") is not None:
        rows = facts["matrix"]
        problems = validate_matrix(rows)
    if problems:
        findings.append(finding(spec.RULE_CONSUMERS_MATRIX, "consumers_matrix_invalid", "error", "certain", "消费者矩阵不合法：%s" % "; ".join(problems), {"problems": problems}, "consumers"))
    else:
        findings.append(finding(spec.RULE_CONSUMERS_MATRIX, "consumers_matrix", "info", "certain", "9×6 消费者矩阵（快照 2026-10-27）", {"rows": rows}, "consumers"))
    risks = _risk_rows(facts)
    for row in risks:
        if row["risk"] == "low":
            continue
        findings.append(
            finding(
                spec.RULE_CONSUMERS_RISK,
                "consumer_risk",
                row["severity"],
                "certain" if row["confidence"] == "certain" else "single-source",
                "%s 的双重旋转风险：%s" % (row["consumer"], row["risk"]),
                dict(row),
                "consumers",
            )
        )
    chunks = facts.get("chunks") or []
    for command, dropped in spec.PROCESSING_DROPS.items():
        gone = [name for name in dropped if name in chunks]
        findings.append(
            finding(
                spec.RULE_CONSUMERS_DIFF,
                "processing_diff",
                "info",
                "certain",
                "%s 会丢掉 %d 个 chunk" % (command, len(gone)),
                {"command": command, "dropped": gone, "kept": [name for name in chunks if name not in gone]},
                "consumers",
            )
        )
    return {"findings": findings, "matrix": rows, "risks": risks}