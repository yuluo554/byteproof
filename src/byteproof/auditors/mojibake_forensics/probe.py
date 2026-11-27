"""原始字节诊断（旧仓 ``file``）：BOM / UTF-16 错位 / ZIP 中央目录名 / CSV 候选。

输入是**已经读进内存的字节**（subject 里的十六进制串），因此本模块不打开任何文件、
不解压成员内容、不修改输入；两解并存时只列证据，不替读者选择。
"""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile

from .chain import hexdump

CSV_CODECS = ("cp1252", "gbk", "shift_jis")
CSV_DELIMITERS = (",", ";", "\t", "|")
PRESETS = (None, "csv-excel-win", "zip-names", "utf16")

# 最长前缀在前：UTF-32LE 以 UTF-16LE 的 BOM 开头。
BOMS = (
    ("utf-32-le", b"\xff\xfe\x00\x00"),
    ("utf-32-be", b"\x00\x00\xfe\xff"),
    ("utf-8", b"\xef\xbb\xbf"),
    ("utf-16-le", b"\xff\xfe"),
    ("utf-16-be", b"\xfe\xff"),
)


def decode_attempt(data: bytes, codec: str) -> dict:
    try:
        return {"decodable": True, "text": data.decode(codec)}
    except UnicodeDecodeError as exc:
        return {"decodable": False, "byte_offset": exc.start}


def sniff_bom(data: bytes) -> dict:
    for kind, bom in BOMS:
        if data.startswith(bom):
            return {
                "present": True,
                "kind": kind,
                "bytes_hex": hexdump(bom),
                "offset": 0,
                "byte_length": len(bom),
            }
    return {"present": False}


def bom_section(data: bytes, preset) -> dict:
    if preset == "zip-names":
        return {}
    bom = sniff_bom(data)
    section = {"bom": bom, "bom_conflict": False}
    if not bom["present"]:
        return section
    body = data[bom["byte_length"] :]
    declared = decode_attempt(body, bom["kind"])
    section["bom_conflict"] = not declared["decodable"]
    if section["bom_conflict"]:
        section["content"] = {
            "body_hex": hexdump(body),
            "as_utf8": decode_attempt(body, "utf-8"),
            "as_gb18030": decode_attempt(body, "gb18030"),
        }
    return section


def utf16_section(data: bytes, bom: dict):
    if bom.get("present"):
        return None
    if data[:4] == b"PK\x03\x04":
        return None
    if len(data) % 2 == 0 or len(data) < 3:
        return None
    for codec in ("utf-16-le", "utf-16-be"):
        try:
            data.decode(codec)
            continue
        except UnicodeDecodeError as exc:
            unshifted = {"decodable": False, "byte_offset": exc.start}
        try:
            shifted_text = data[1:].decode(codec)
        except UnicodeDecodeError:
            continue
        return {
            "byte_length": len(data),
            "odd_length": True,
            "unshifted": unshifted,
            "shift_offset": 1,
            "shifted_text": shifted_text,
            "reason": "odd_byte_count",
        }
    return None


def central_entries(data: bytes):
    start = data.rfind(b"PK\x05\x06")
    count = None
    offset = data.find(b"PK\x01\x02")
    if start != -1 and len(data) >= start + 20:
        count = struct.unpack("<H", data[start + 10 : start + 12])[0]
        offset = struct.unpack("<I", data[start + 16 : start + 20])[0]

    entries = []
    cursor = offset
    while cursor >= 0 and cursor + 46 <= len(data) and data[cursor : cursor + 4] == b"PK\x01\x02":
        if count is not None and len(entries) >= count:
            break
        flags = struct.unpack("<H", data[cursor + 8 : cursor + 10])[0]
        name_length = struct.unpack("<H", data[cursor + 28 : cursor + 30])[0]
        extra_length = struct.unpack("<H", data[cursor + 30 : cursor + 32])[0]
        comment_length = struct.unpack("<H", data[cursor + 32 : cursor + 34])[0]
        raw_name = data[cursor + 46 : cursor + 46 + name_length]
        entries.append((flags, raw_name))
        cursor += 46 + name_length + extra_length + comment_length
    return entries


def zip_section(data: bytes):
    if data[:4] != b"PK\x03\x04":
        return None
    names = []
    for flags, raw_name in central_entries(data):
        flag_utf8 = bool(flags & 0x0800)
        interpretations = {}
        for codec in ("utf-8", "cp437"):
            try:
                interpretations[codec] = raw_name.decode(codec)
            except UnicodeDecodeError:
                interpretations[codec] = None
        interpretation = "utf-8" if flag_utf8 else "cp437"
        other_codec = "cp437" if flag_utf8 else "utf-8"
        entry = {
            "raw_name_hex": hexdump(raw_name),
            "flag_bits": flags,
            "flag_utf8": flag_utf8,
            "interpretation": interpretation,
            "name": interpretations[interpretation],
            "alternatives": [],
        }
        if interpretations[other_codec] is not None:
            entry["alternatives"].append(
                {"codec": other_codec, "name": interpretations[other_codec]}
            )
            if not flag_utf8:
                entry["note"] = "two interpretations are listed; the tool does not choose"
        names.append(entry)

    section = {
        "zip_names": names,
        "archive_sha256": hashlib.sha256(data).hexdigest(),
    }
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            views = [
                {
                    "filename": info.filename,
                    "flag_bits": info.flag_bits,
                    "compress_type": info.compress_type,
                    "create_system": info.create_system,
                }
                for info in archive.infolist()
            ]
    except (zipfile.BadZipfile, IOError):
        views = []
    if views:
        section["zipfile_view"] = views[0] if len(views) == 1 else views
    return section


def csv_section(data: bytes, preset):
    if preset != "csv-excel-win":
        return None
    candidates = []
    for codec in CSV_CODECS:
        attempt = decode_attempt(data, codec)
        candidates.append({"codec": codec, "decodable": attempt["decodable"]})
    sample = data[:4096].decode("latin-1")
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    counts = dict((delimiter, first_line.count(delimiter)) for delimiter in CSV_DELIMITERS)
    best = None
    best_count = 0
    for delimiter in CSV_DELIMITERS:
        if counts[delimiter] > best_count:
            best, best_count = delimiter, counts[delimiter]
    return {
        "delimiter": best,
        "delimiter_counts": counts,
        "candidates": candidates,
    }


def inspect_bytes(data: bytes, preset=None) -> dict:
    """纯只读诊断；返回证据分节。不写回、不解压成员内容。"""
    if preset not in PRESETS:
        raise ValueError("preset 非法：%r（允许 csv-excel-win / zip-names / utf16 / 省略）" % (preset,))
    sections = {}
    bom_part = bom_section(data, preset)
    sections.update(bom_part)
    bom = sections.get("bom", {"present": False})

    if preset in (None, "utf16"):
        utf16 = utf16_section(data, bom)
        if utf16 is not None:
            sections["utf16_misalignment"] = utf16

    if preset in (None, "zip-names"):
        zip_part = zip_section(data)
        if zip_part is not None:
            sections.update(zip_part)

    if preset in (None, "csv-excel-win"):
        csv_part = csv_section(data, preset)
        if csv_part is not None:
            sections["csv_candidates"] = csv_part

    sections["mutates_input"] = False
    return sections