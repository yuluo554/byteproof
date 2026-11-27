"""判决层：五个模块（结构 / 时长 / 时间戳 / 偏移 / 显示）的纯函数。

输入是输入层解析好的**事实**（``subject.facts``）：盒子树、mdat 区间、stco、
电影/轨道头、stts/elst/ctts、分片 tfdt、display matrix/SAR/colr/HDR。
不做 I/O、不读时钟、不解码、不联网。

每条 finding = ``{rule_id, code, status, message, module, values, delta, offset, path}``；
status ∈ ``fail`` / ``gray``。BLOCKING 只由 ``mt-gate`` 表达。
"""

from __future__ import annotations

from . import spec


def finding(code, status, message, module, values=None, delta=None, offset=None, path=""):
    return {
        "rule_id": spec.CODE_RULE[code],
        "code": code,
        "status": status,
        "message": message,
        "module": module,
        "values": values or [],
        "delta": delta,
        "offset": offset,
        "path": path,
    }


def _fail(code, message, module, **extra):
    return finding(code, spec.STATUS_FAIL, message, module, **extra)


def _gray(code, message, module, **extra):
    return finding(code, spec.STATUS_GRAY, message, module, **extra)


# ================================================================== M1
def audit_structure(facts):
    findings = []
    for anomaly in facts.get("anomalies") or []:
        if anomaly.get("kind") == "too_small_size":
            findings.append(
                _fail(
                    "too_small_size",
                    "box %r 声明 size %s（< 8 字节最小头）" % (anomaly.get("box_type"), anomaly.get("declared")),
                    "M1",
                    values=[{"name": "declared_size", "value": anomaly.get("declared")}],
                    offset=anomaly.get("offset"),
                    path=anomaly.get("parent_path", ""),
                )
            )
        elif anomaly.get("kind") == "max_depth":
            findings.append(
                _fail(
                    "max_depth_exceeded",
                    "盒子嵌套达到深度 %s（上限 %s）" % (anomaly.get("depth"), anomaly.get("max_depth", 32)),
                    "M1",
                    values=[{"name": "observed_depth", "value": anomaly.get("depth")}],
                    offset=anomaly.get("offset"),
                )
            )
    file_size = facts.get("file_size")
    boxes = facts.get("boxes") or []
    mdats = []
    for box in boxes:
        if not isinstance(box, dict):
            raise ValueError("facts.boxes 的每一项必须是对象")
        offset, size = box.get("offset"), box.get("size")
        if not isinstance(offset, int) or not isinstance(size, int):
            raise ValueError("box.offset / box.size 必须是整数")
        if box.get("type") == "mdat":
            mdats.append({"offset": offset, "size": size})
        if box.get("type") == "mdat" and box.get("depth") == 1 and isinstance(file_size, int) and offset + size > file_size:
            findings.append(
                _fail(
                    "truncated_mdat",
                    "顶层 mdat 声明长度越过文件尾（需要 %d 字节，实际 %d）" % (size, file_size - offset),
                    "M1",
                    values=[{"name": "declared_size", "value": size}],
                    delta=offset + size - file_size,
                    offset=offset,
                    path=box.get("path", "mdat"),
                )
            )
            continue
        parent_end = box.get("parent_end")
        if isinstance(parent_end, int) and offset + size > parent_end:
            findings.append(
                _fail(
                    "child_overruns_parent",
                    "子盒 %r 越过父盒末端（父末端 %d，子末端 %d）" % (box.get("type"), parent_end, offset + size),
                    "M1",
                    values=[{"name": "child_end", "value": offset + size}],
                    delta=offset + size - parent_end,
                    offset=offset,
                    path=box.get("path", box.get("type", "")),
                )
            )
    if facts.get("moov_count", 0) > 1:
        findings.append(_fail("duplicate_moov", "文件出现 %d 个 moov" % facts["moov_count"], "M1"))
    elif len(mdats) > 1:
        findings.append(_fail("duplicate_mdat", "文件出现 %d 个 mdat" % len(mdats), "M1"))
    else:
        for offset in facts.get("stco") or []:
            if not isinstance(offset, int):
                raise ValueError("facts.stco 的每一项必须是整数")
            if not any(mdat["offset"] <= offset < mdat["offset"] + mdat["size"] for mdat in mdats):
                findings.append(
                    _fail(
                        "stco_out_of_mdat",
                        "stco 偏移 %d 不在任何 mdat 内" % offset,
                        "M1",
                        values=[{"name": "chunk_offset", "value": offset}],
                        offset=offset,
                    )
                )
                break
    ftyp = facts.get("ftyp") or {}
    major = ftyp.get("major")
    brands = ftyp.get("compatible_brands") or []
    if major in spec.CODEC_BRANDS and not any(brand in ("isom", "iso2", "mp41", "mp42") for brand in brands):
        findings.append(
            _fail(
                "ftyp_brand_mismatch",
                "major_brand=%r 是编码品牌，但兼容品牌里没有通用容器品牌" % major,
                "M1",
                values=[{"name": "major_brand", "value": major}],
            )
        )
    return findings


# ================================================================== M2
def _movie_ticks(track, movie_timescale):
    if not track.get("timescale") or not movie_timescale:
        return 0
    return int(track.get("duration", 0)) * int(movie_timescale) // int(track["timescale"])


def _presentation_ticks(track, movie_timescale):
    values = [int(track.get("tkhd_duration", 0)), _movie_ticks(track, movie_timescale)]
    elst = track.get("elst") or []
    if elst:
        values.append(sum(int(item.get("segment_duration", 0)) for item in elst))
    return max(values)


def _elst_intervals(track, movie_timescale):
    intervals = []
    start = 0
    for item in track.get("elst") or []:
        seg = int(item.get("segment_duration", 0))
        media = int(item.get("media_time", 0))
        if media >= 0:
            intervals.append((start, start + seg, media, media + seg))
        start += seg
    return intervals


def audit_duration(facts):
    movie = facts.get("movie")
    if not isinstance(movie, dict):
        raise ValueError("facts.movie 必须是对象")
    tracks = movie.get("tracks") or []
    duration = int(movie.get("duration", 0))
    movie_timescale = int(movie.get("timescale", 0))
    findings = []
    if duration == 0 and not any(track.get("stts") or track.get("fragments") for track in tracks):
        findings.append(_gray("duration_unknown", "mvhd.duration=0 且没有可推导样本时长", "M2"))
        return findings
    presentation = max((_presentation_ticks(track, movie_timescale) for track in tracks), default=0)
    if tracks and abs(duration - presentation) > spec.TICK_TOLERANCE:
        findings.append(
            _fail(
                "duration_mismatch",
                "mvhd.duration %d 与放映时长 %d 相差 %d tick（容差 %d）"
                % (duration, presentation, abs(duration - presentation), spec.TICK_TOLERANCE),
                "M2",
                values=[{"name": "mvhd_duration", "value": duration}, {"name": "presentation", "value": presentation}],
                delta=duration - presentation,
            )
        )
    for track in tracks:
        _edit_rules(findings, track, movie_timescale)
    return findings


def _edit_rules(findings, track, movie_timescale):
    elst = track.get("elst") or []
    if not elst:
        return
    seen_media = False
    start = 0
    for index, item in enumerate(elst):
        rate = int(item.get("rate", spec.RATE_ONE))
        if rate != spec.RATE_ONE:
            findings.append(
                _fail(
                    "elst_item_rate_not_one",
                    "elst 第 %d 条 media_rate=%d（16.16）≠ 1.0" % (index, rate),
                    "M2",
                    values=[{"name": "elst_item", "value": index}, {"name": "media_rate", "value": rate}],
                    delta=rate - spec.RATE_ONE,
                )
            )
        media = int(item.get("media_time", 0))
        seg = int(item.get("segment_duration", 0))
        if media < 0:
            if seen_media or seg == 0:
                why = "空 edit 出现在媒体段之后" if seen_media else "空 edit 的 segment_duration 为 0"
                findings.append(
                    _fail(
                        "empty_edit",
                        "空 edit（media_time=-1）：%s" % why,
                        "M2",
                        values=[{"name": "elst_item", "value": index}, {"name": "segment_duration", "value": seg}],
                        delta=seg,
                    )
                )
        else:
            seen_media = True
        start += seg
    intervals = _elst_intervals(track, movie_timescale)
    first_pts = track.get("first_pts")
    if first_pts is None or not intervals:
        return
    first_index = next((index for index, item in enumerate(elst) if int(item.get("media_time", 0)) >= 0), None)
    if first_index is None:
        return
    for index, (lo, hi, media_lo, media_hi) in enumerate(intervals):
        if index == 0:
            continue
        if media_lo <= first_pts < media_hi:
            findings.append(
                _fail(
                    "elst_item_order_suspect",
                    "首帧 PTS %d 落在第 %d 段而非首个媒体段" % (first_pts, index),
                    "M2",
                    values=[{"name": "first_pts", "value": first_pts}, {"name": "containing_item", "value": index}],
                    delta=index,
                )
            )
            return
    span = sum(hi - lo for lo, hi, _ml, _mh in intervals)
    media_duration = int(track.get("duration", 0))
    media_movie = media_duration * movie_timescale // int(track.get("timescale", 1) or 1)
    if abs(span - media_movie) <= spec.TICK_TOLERANCE:
        return
    if not any(media_lo <= first_pts < media_hi for _lo, _hi, media_lo, media_hi in intervals):
        lo, hi = intervals[0][2], intervals[0][3]
        findings.append(
            _fail(
                "first_pts_outside_media",
                "首帧 PTS %d 不在任何编辑媒体区间内（期望 [%d,%d)）" % (first_pts, lo, hi),
                "M2",
                values=[{"name": "first_pts", "value": first_pts}, {"name": "media_start", "value": lo}],
                delta=lo - first_pts if first_pts < lo else first_pts - hi + 1,
            )
        )


# ================================================================== M3
def audit_timestamps(facts):
    findings = []
    for track in (facts.get("movie") or {}).get("tracks") or []:
        entries = track.get("stts") or []
        cum = 0
        overflowed = False
        nominal = next((int(item[1]) for item in entries if int(item[1]) != 0), 0)
        for index, entry in enumerate(entries):
            count, delta = int(entry[0]), int(entry[1])
            end = cum + count * delta
            if end > spec.STTS_WIDTH_MAX:
                findings.append(
                    _fail(
                        "dts_overflow_risk",
                        "stts 第 %d 条累计 DTS %d 越过 32 位上限 %d" % (index, end, spec.STTS_WIDTH_MAX),
                        "M3",
                        values=[{"name": "cumulative_dts", "value": end}],
                        delta=end - spec.STTS_WIDTH_MAX,
                    )
                )
                overflowed = True
                break
            if delta == 0:
                findings.append(
                    _fail(
                        "zero_duration_entry",
                        "stts 第 %d 条声明 duration=0（%d 个样本落在同一时刻）" % (index, count),
                        "M3",
                        values=[{"name": "samples", "value": count}, {"name": "nominal", "value": nominal}],
                        delta=nominal,
                    )
                )
            cum = end
        if len(entries) > 1:
            findings.append(_gray("vfr_detected", "stts 有 %d 条，恒帧率推断不可用" % len(entries), "M3"))
        timescale = track.get("timescale")
        if isinstance(timescale, int) and 0 < timescale < spec.TIMESCALE_SUSPECT_BELOW and not overflowed:
            findings.append(
                _gray(
                    "timescale_suspect",
                    "mdhd.timescale %d 低于精度下限 %d（溢出风险前兆）" % (timescale, spec.TIMESCALE_SUSPECT_BELOW),
                    "M3",
                )
            )
        previous = None
        for fragment in track.get("fragments") or []:
            tfdt = int(fragment.get("tfdt", 0))
            if previous is not None and tfdt < previous - spec.DTS_REGRESSION_TOLERANCE:
                findings.append(
                    _fail(
                        "tfdt_regression",
                        "分片 #%s 的 tfdt %d 回退到 %d 之前" % (fragment.get("index"), tfdt, previous),
                        "M3",
                        values=[{"name": "tfdt", "value": tfdt}, {"name": "previous", "value": previous}],
                        delta=previous - tfdt,
                    )
                )
            if not fragment.get("version") and tfdt + int(fragment.get("duration", 0)) > spec.TFDT_V0_WIDTH_MAX:
                findings.append(
                    _fail("dts_overflow_risk", "tfdt v0 与分片时长越过 32 位上限", "M3")
                )
            previous = tfdt
    return findings


# ================================================================== M4
def audit_offset(facts):
    findings = []
    for track in (facts.get("movie") or {}).get("tracks") or []:
        codec = track.get("codec", "")
        expected = spec.KNOWN_PRIMING.get(codec)
        declared = track.get("declared_priming")
        if codec and expected is None:
            findings.append(_gray("unknown_codec_priming", "编码 %r 的 priming 未知" % codec, "M4"))
        elif expected is not None:
            if declared is None and expected > 0 and not track.get("has_edts"):
                findings.append(
                    _fail(
                        "priming_undeclared",
                        "%s 的 priming 应为 %d，但未声明且没有 edts" % (codec, expected),
                        "M4",
                        values=[{"name": "expected_priming", "value": expected}],
                    )
                )
            elif declared is not None and int(declared) != expected:
                findings.append(
                    _fail(
                        "priming_mismatch",
                        "%s 声明 priming %d，期望 %d" % (codec, declared, expected),
                        "M4",
                        values=[{"name": "declared", "value": declared}, {"name": "expected", "value": expected}],
                        delta=int(declared) - expected,
                    )
                )
        elst = track.get("elst") or []
        first_media = next((item for item in elst if int(item.get("media_time", 0)) > 0), None)
        if first_media is not None:
            findings.append(
                _fail(
                    "start_trim",
                    "编辑表从 media_time=%d 开始（起点裁剪）" % first_media["media_time"],
                    "M4",
                    values=[{"name": "media_time", "value": first_media["media_time"]}],
                )
            )
        if codec in spec.ROLL_DISTANCE_CODECS and track.get("roll_distance") is None:
            findings.append(_gray("no_roll_distance", "%s 没有 roll_distance" % codec, "M4"))
        if int(track.get("start_time", 0)) != 0 and not track.get("has_edts"):
            findings.append(
                _gray(
                    "no_edts_but_nonzero_start",
                    "start_time=%d 但没有 edts" % track["start_time"],
                    "M4",
                )
            )
    return findings


# ================================================================== M5
def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def audit_display(facts):
    findings = []
    for track in (facts.get("movie") or {}).get("tracks") or []:
        display = track.get("display")
        if not isinstance(display, dict):
            continue
        matrix = display.get("matrix")
        if isinstance(matrix, list) and len(matrix) == 9:
            values = [int(item) for item in matrix]
            row0, row1 = values[0:3], values[3:6]
            dot = _dot(row0, row1)
            norm0 = _dot(row0, row0)
            if abs(dot) > spec.MATRIX_ORTHO_TOLERANCE * spec.Q16_ONE or abs(norm0 - spec.Q16_ONE * spec.Q16_ONE) > spec.MATRIX_ORTHO_TOLERANCE * spec.Q16_ONE:
                findings.append(
                    _fail(
                        "matrix_not_orthogonal",
                        "display matrix 非正交（点积 %d，范数 %d）" % (dot, norm0),
                        "M5",
                        values=[{"name": "dot", "value": dot}, {"name": "norm", "value": norm0}],
                        delta=dot,
                    )
                )
            a, _b, _u = row0
            c, d, _v = row1
            rotation = abs(a) < spec.MATRIX_ORTHO_TOLERANCE and abs(d) < spec.MATRIX_ORTHO_TOLERANCE and (
                abs(abs(_b) - spec.Q16_ONE) <= spec.MATRIX_ORTHO_TOLERANCE
                and abs(abs(c) - spec.Q16_ONE) <= spec.MATRIX_ORTHO_TOLERANCE
            )
            if rotation:
                width, height = display.get("width"), display.get("height")
                stored = (display.get("stored_width"), display.get("stored_height"))
                if isinstance(width, int) and isinstance(height, int) and stored == (width, height) and width != height:
                    findings.append(
                        _fail(
                            "rotation_dimension_conflict",
                            "±90° 旋转但呈现宽高未互换（%dx%d）" % (width, height),
                            "M5",
                            values=[{"name": "width", "value": width}, {"name": "height", "value": height}],
                        )
                    )
        sar = display.get("sar")
        if isinstance(sar, list) and len(sar) == 2:
            h, v = int(sar[0]), int(sar[1])
            if h <= 0 or v <= 0:
                findings.append(_fail("sar_dar_conflict", "SAR %r 含非正数" % (sar,), "M5"))
        if display.get("dar_conflict"):
            findings.append(_fail("sar_dar_conflict", "SAR 与 DAR 不一致", "M5"))
        colr = display.get("colr") or []
        if len(colr) > 1:
            findings.append(
                _fail(
                    "colr_multi_instance",
                    "colr 出现 %d 次（%s）" % (len(colr), ", ".join(str(item.get("type", "?")) for item in colr)),
                    "M5",
                    values=[{"name": "colr_count", "value": len(colr)}],
                )
            )
        if display.get("hdr") and not display.get("hdr_metadata"):
            findings.append(_gray("hdr_metadata_missing", "HDR 标记存在但缺少 HDR 元数据", "M5"))
        if display.get("hdr") and display.get("hdr_range_ok") is False:
            findings.append(_fail("hdr_range_suspect", "HDR 范围字段可疑", "M5"))
    return findings


# ================================================================== 入口
def audit(facts, modules):
    if not isinstance(facts, dict):
        raise ValueError("subject.facts 必须是对象")
    selected = modules or list(spec.MODULES)
    if not isinstance(selected, list) or not all(item in spec.MODULES for item in selected):
        raise ValueError("subject.modules 必须是 M1..M5 的子集")
    findings = []
    if "M1" in selected:
        findings.extend(audit_structure(facts))
    if "M2" in selected:
        findings.extend(audit_duration(facts))
    if "M3" in selected:
        findings.extend(audit_timestamps(facts))
    if "M4" in selected:
        findings.extend(audit_offset(facts))
    if "M5" in selected:
        findings.extend(audit_display(facts))
    return findings