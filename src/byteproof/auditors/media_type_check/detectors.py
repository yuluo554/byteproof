"""19 条规则的检测器（旧仓 ``media-type-check/headers.py`` / ``transfer.py`` / ``scan.py`` /
``attribution.py`` 的判定子集，规则 ID 与 severity 原样保留）。

每条检测器只做一件事：把一份**已解析**的 MIME 部件映射成若干 ``Finding``。
不做 IO、不做渲染、不去猜"责任方"。

可判定的前提是"工件已经是解析后的形态"（``parts[].headers`` / ``.content_type`` /
``.boundary`` / ``.body``）：raw 字节的扫描层（``scan.py``）是工具面，器官不读文件。

两条旧仓纪律照抄：

* ``MC-H07`` **先于** encoded-word 检查：头行一旦超过 998 octets，拆分它的是折行规则，
  再按 encoded-word 逐段报错只会把一条结论说三遍。
* ``MC-T04``（base64 出现字母表外字符）命中后**不再**判填充与长度：RFC 2045 6.8 要求
  解码器忽略字母表外字符，所以那既不是违规、也轮不到用它的字节数去推"填充错没错"。
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, NamedTuple

from . import spec

#: 一条命中：规则 + 位置 + 人读说明 + 机器可读证据（只有整数与字符串）。
Finding = NamedTuple(
    "Finding", [("rule_id", str), ("path", str), ("detail", str), ("evidence", dict)]
)

_ENCODED_WORD_RE = re.compile(r"=\?([^?]+)\?([BbQq])\?([^?]*)\?=")
_PARAM_RE = re.compile(r";\s*([A-Za-z0-9!#$%&'*+.^_`|~-]+)\s*=\s*(\"[^\"]*\"|[^;]*)")
_HEX = "0123456789ABCDEFabcdef"
_BASE64_ALPHABET = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
)
_KNOWN_CTE = frozenset({"7bit", "8bit", "binary", "quoted-printable", "base64"})


def _split_media_type(value):
    """``type/sub; a=b; c="d"`` -> ``(type/sub, {a: b, c: d})``（参数名小写，去引号）。"""
    main = value.split(";", 1)[0].strip().lower()
    params = {}
    for match in _PARAM_RE.finditer(value):
        name = match.group(1).strip().lower()
        raw = match.group(2).strip()
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        params[name] = raw
    return main, params


def _line_octets(name, value):
    """头行 octets：``Name + ": " + value``（不含 CRLF）。"""
    return len((name + ": " + value).encode("utf-8"))


def _encoded_words(value):
    return list(_ENCODED_WORD_RE.finditer(value))


def _strip_ew(value):
    """把 encoded-word 整段抹掉，剩下的是"裸"头值（供 MC-H08 判未编码非 ASCII）。"""
    return _ENCODED_WORD_RE.sub("", value)


def _header_map(headers):
    """同名头**全部保留**（重复 Content-Type 本身是事实，不能悄悄覆盖）。"""
    found = {}
    for header in headers:
        found.setdefault(header["name"].strip().lower(), []).append(header["value"])
    return found


# ---------------------------------------------------------------------------
# 头规则
# ---------------------------------------------------------------------------
def header_findings(part, params):
    """``MC-H01/02/03/07/08``：逐头判。"""
    built = []
    path = part["path"]
    for header in part["headers"]:
        name = header["name"]
        value = header["value"]
        octets = _line_octets(name, value)
        if octets > params["max_header_line_octets"]:
            built.append(
                Finding(
                    "MC-H07",
                    path,
                    "头行 %d octets 超过 %d：%s"
                    % (octets, params["max_header_line_octets"], name),
                    {
                        "header": name,
                        "octets": octets,
                        "max_header_line_octets": params["max_header_line_octets"],
                    },
                )
            )
            # 旧仓纪律：H07 先于 encoded-word 检查，命中后不再拆段报错。
            continue

        words = _encoded_words(value)
        for word in words:
            text = word.group(0)
            if len(text) > params["max_encoded_word_chars"]:
                built.append(
                    Finding(
                        "MC-H01",
                        path,
                        "encoded-word 长 %d 字符，超过 %d"
                        % (len(text), params["max_encoded_word_chars"]),
                        {
                            "header": name,
                            "encoded_word_chars": len(text),
                            "max_encoded_word_chars": params["max_encoded_word_chars"],
                        },
                    )
                )
        if words and len(name) + 2 + len(value) > params["max_encoded_header_line"]:
            built.append(
                Finding(
                    "MC-H02",
                    path,
                    "含 encoded-word 的头行长 %d，超过 %d"
                    % (len(name) + 2 + len(value), params["max_encoded_header_line"]),
                    {
                        "header": name,
                        "chars": len(name) + 2 + len(value),
                        "max_encoded_header_line": params["max_encoded_header_line"],
                    },
                )
            )
        for word in words:
            if re.search(r"\s", word.group(3)):
                built.append(
                    Finding(
                        "MC-H03",
                        path,
                        "encoded-word 的 encoded-text 内含空白：%r" % (word.group(0),),
                        {"header": name, "encoded_word": word.group(0)},
                    )
                )
        bare = _strip_ew(value)
        non_ascii = [char for char in bare if ord(char) > 0x7F]
        if non_ascii:
            built.append(
                Finding(
                    "MC-H08",
                    path,
                    "头值含 %d 个未编码的非 ASCII 字节（首个 U+%04X）"
                    % (len(non_ascii), ord(non_ascii[0])),
                    {
                        "header": name,
                        "non_ascii_count": len(non_ascii),
                        "first_codepoint": ord(non_ascii[0]),
                    },
                )
            )
    return built


# ---------------------------------------------------------------------------
# 传输编码规则
# ---------------------------------------------------------------------------
def _cte_of(headers_map):
    values = headers_map.get("content-transfer-encoding")
    if not values:
        return None
    return values[0].strip().lower()


def _decode_octets(body):
    """把 ``body`` 读成字节：允许 str（UTF-8）或 0..255 的整数列表（工件的原始字节）。"""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    raise ValueError("part.body 必须是字符串或字节数组")


def transfer_findings(part, params, headers_map):
    """``MC-T02/03/04/05/06/07/08/09/10``：按声明的 CTE 分别判。"""
    built = []
    path = part["path"]
    declared = _cte_of(headers_map)
    body = _decode_octets(part["body"])
    text = body.decode("utf-8", errors="replace")

    if declared is not None and declared not in _KNOWN_CTE:
        built.append(
            Finding(
                "MC-T08",
                path,
                "未知 CTE 取值 %r（无法做交叉校验）" % (declared,),
                {"content_transfer_encoding": declared},
            )
        )
        return built

    if declared is None and any(byte > 0x7F for byte in body):
        built.append(
            Finding(
                "MC-T10",
                path,
                "未声明 CTE（缺省 7bit）但正文含 %d 个 8bit 字节"
                % (sum(1 for byte in body if byte > 0x7F),),
                {"eight_bit_bytes": sum(1 for byte in body if byte > 0x7F)},
            )
        )

    if declared in ("7bit", "8bit"):
        for index, line in enumerate(text.splitlines(), 1):
            if len(line.encode("utf-8")) > params["max_body_line_octets"]:
                built.append(
                    Finding(
                        "MC-T09",
                        path,
                        "第 %d 行 %d octets 超过 %d"
                        % (index, len(line.encode("utf-8")), params["max_body_line_octets"]),
                        {
                            "line": index,
                            "octets": len(line.encode("utf-8")),
                            "max_body_line_octets": params["max_body_line_octets"],
                        },
                    )
                )

    if declared == "base64":
        cleaned = "".join(text.split())
        stripped = cleaned.rstrip("=")
        if any(char not in _BASE64_ALPHABET for char in cleaned):
            bad = sorted({char for char in cleaned if char not in _BASE64_ALPHABET})
            built.append(
                Finding(
                    "MC-T04",
                    path,
                    "base64 正文出现字母表外字符 %d 种（RFC 2045 §6.8 要求忽略）" % (len(bad),),
                    {"bad_chars": "".join(bad)},
                )
            )
            return built
        padding = len(cleaned) - len(stripped)
        if padding > 2 or "=" in stripped:
            built.append(
                Finding(
                    "MC-T02",
                    path,
                    "base64 填充非法（%d 个 '='，且必须只出现在末尾）" % (padding,),
                    {"padding": padding, "interior_padding": "=" in stripped},
                )
            )
        if len(cleaned) % 4 != 0:
            built.append(
                Finding(
                    "MC-T03",
                    path,
                    "base64 字符数 %d 不是 4 的倍数" % (len(cleaned),),
                    {"chars": len(cleaned)},
                )
            )

    if declared == "quoted-printable":
        lines = text.splitlines()
        for index, line in enumerate(lines, 1):
            if _has_invalid_escape(line, index == len(lines)):
                built.append(
                    Finding(
                        "MC-T07",
                        path,
                        "第 %d 行 QP 非法转义（'=' 后不是两位十六进制）" % (index,),
                        {"line": index, "text": line[:40]},
                    )
                )
                continue
            if len(line.encode("utf-8")) > params["max_qp_line_octets"]:
                built.append(
                    Finding(
                        "MC-T05",
                        path,
                        "第 %d 行 %d octets 超过 %d"
                        % (index, len(line.encode("utf-8")), params["max_qp_line_octets"]),
                        {
                            "line": index,
                            "octets": len(line.encode("utf-8")),
                            "max_qp_line_octets": params["max_qp_line_octets"],
                        },
                    )
                )
        if lines and lines[-1].endswith("=") and not text.endswith("\n"):
            built.append(
                Finding(
                    "MC-T06",
                    path,
                    "QP 末行以 '=' 结尾但已无下一行（悬空软换行）",
                    {"line": len(lines), "soft_break": True},
                )
            )
    return built


def _has_invalid_escape(line, is_last):
    """``=`` 后必须是两位十六进制；行尾的 ``=`` 在非末行是合法软换行。"""
    index = 0
    while index < len(line):
        if line[index] != "=":
            index += 1
            continue
        if index == len(line) - 1:
            if is_last:
                return False  # 末行悬空 '=' 由 MC-T06 负责，不重复判
            index += 1
            continue
        pair = line[index + 1 : index + 3]
        if len(pair) < 2 or any(char not in _HEX for char in pair):
            return True
        index += 3
    return False


# ---------------------------------------------------------------------------
# 容器 / 归属规则
# ---------------------------------------------------------------------------
def container_findings(part, params):
    """``MC-B01/02/09``：multipart 的结构与深度。"""
    built = []
    path = part["path"]
    content_type = part["content_type"].strip().lower()
    boundary = part.get("boundary")
    if content_type.startswith("multipart/") and not boundary:
        built.append(
            Finding(
                "MC-B01",
                path,
                "multipart/%s 缺 boundary 参数：树无法建立" % (content_type.split("/", 1)[1],),
                {"content_type": content_type, "boundary": None},
            )
        )
    if boundary and len(boundary) > params["max_boundary_chars"]:
        built.append(
            Finding(
                "MC-B02",
                path,
                "boundary 长 %d 字符，超过 %d" % (len(boundary), params["max_boundary_chars"]),
                {
                    "boundary_chars": len(boundary),
                    "max_boundary_chars": params["max_boundary_chars"],
                },
            )
        )
    depth = _depth_of(path)
    if depth > params["max_depth"]:
        built.append(
            Finding(
                "MC-B09",
                path,
                "嵌套深度 %d 超过 max_depth=%d（RFC 未规定上限，策略项）"
                % (depth, params["max_depth"]),
                {"depth": depth, "max_depth": params["max_depth"]},
            )
        )
    return built


def _depth_of(path):
    """``msg#3/0.1.2`` 的嵌套深度 = 末段的下标个数（``0`` 为 1 层）。"""
    if "/" in path:
        path = path.split("/", 1)[1]
    elif path.startswith("msg#"):
        path = ""
    if not path:
        return 1
    return len(path.split("."))


def attribution_findings(part, headers_map):
    """``MC-A02/03/07``：归属参数一致性。"""
    built = []
    path = part["path"]
    content_type = part["content_type"].strip().lower()
    _main, type_params = _split_media_type(part.get("content_type_header") or content_type)

    dispositions = headers_map.get("content-disposition")
    disposition = None
    disposition_params = {}
    if dispositions:
        disposition, disposition_params = _split_media_type(dispositions[0])

    name = type_params.get("name")
    filename = disposition_params.get("filename")
    if name and filename and name != filename:
        built.append(
            Finding(
                "MC-A02",
                path,
                "Content-Type 的 name=%r 与 Content-Disposition 的 filename=%r 不一致"
                % (name, filename),
                {"name": name, "filename": filename},
            )
        )
    if disposition is not None and not filename and not name:
        built.append(
            Finding(
                "MC-A03",
                path,
                "声明了 disposition=%r 却没有任何 filename / name 参数（下游显示 Noname）"
                % (disposition,),
                {"disposition": disposition},
            )
        )
    if disposition == "inline" and not headers_map.get("content-id"):
        built.append(
            Finding(
                "MC-A07",
                path,
                "disposition 是 inline 却没有 Content-ID：正文无法用 cid: 引用它",
                {"disposition": disposition},
            )
        )
    return built


def audit_part(part, params):
    """一个部件的全部命中（顺序固定，报告层再统一排序）。"""
    headers_map = _header_map(part["headers"])
    built: List[Finding] = []
    built.extend(header_findings(part, params))
    built.extend(transfer_findings(part, params, headers_map))
    built.extend(container_findings(part, params))
    built.extend(attribution_findings(part, headers_map))
    return built