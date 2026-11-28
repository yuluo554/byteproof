"""模块 ② · 引用点抽取（1:1 移植自旧仓 ``src/scan.mjs`` 的词法级抽取）。

AST 优先，字符串字面量为兜底（旧仓 ``plan/03`` §3）。旧仓零第三方依赖，因此用
**手写词法级抽取**：能可靠覆盖静态字面量形态，抽不出一律落 ``AMBIGUOUS``。

核心纪律（旧仓 ``data/README.md`` §5、``plan/03`` §3）：
  **严禁把"解析不到"当"不存在"**——动态形态必须显式出现在结果里，不能被静默丢弃。
  这条比"抽得全"更重要：漏一个 AMBIGUOUS 就等于对用户撒了一次"没问题"。

行号纪律：必须指向**源行号**。CRLF 先归一成 LF 再切行（否则 Windows 上每行尾部多一个
``\\r``，且某些正则的 ``$`` 语义会变），但**归一不改变行数**，所以行号仍然准确。

文件收集（目录遍历 / 扩展名过滤 / 跳过目录）属输入层；本模块只对输入层给出的
**文本**做抽取，并对超大文件做降级记账。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .spec import KIND, LARGE_FILE_DOWNGRADED, SOURCE_FILE_BYTES

# 正则面与 JS 同构：``\w`` 一律写成显式 ASCII 类（JS \w 不含 Unicode，Python 默认含）。
STATIC_IMPORT = re.compile(
    r"(?:^|[\s;{(])import\s+(?:([A-Za-z0-9_$*{}\s,]+?)\s+from\s+)?([\"'])([^\"'\n]+)\2"
)
EXPORT_FROM = re.compile(r"(?:^|[\s;}])export\s+(?:\*|\{[^}]*\})\s+from\s+([\"'])([^\"'\n]+)\1")
REQUIRE_DESTRUCTURED = re.compile(
    r"(?:const|let|var)\s*\{([^}]*)\}\s*=\s*require\s*\(\s*([\"'])([^\"'\n]+)\2\s*\)"
)
JEST_MOCK = re.compile(
    r"\b(?:jest|vi)\s*\.\s*(?:mock|requireActual|importActual|doMock)\s*\(\s*([\"'])([^\"'\n]+)\1"
)
#: ``require(` ``/ ``import(`` 的**调用点**（参数内容由 :func:`_read_call_argument` 另行切分）。
CALL_SITE = re.compile(r"\b(require|import)\s*\(")
#: 纯字面量参数：单/双引号，或**不含插值**的模板串（`` `chalk` `` 是静态的，`` `./${x}` `` 不是）。
STATIC_ARG = re.compile(r"^(?:\"([^\"\n]+)\"|'([^'\n]+)'|`([^`$\n]+)`)$")

#: ``⚠️ 字符串兜底``：形似包名的裸字符串（旧仓 ``data/README.md`` §5.3 第 3 条）。
BARE_PACKAGE_NAME = re.compile(
    r"^(@[a-z0-9-~][a-z0-9-._~]*/)?[a-z0-9-~][a-z0-9-._~]*(/[^\s\"'`]*)?$"
)
#: 任意引号字符串字面量（单/双/反引号，不含换行，不含插值）。
ANY_STRING_LITERAL = re.compile(r"([\"'`])([^\"'`\n$\\]{2,120})\1")
_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def scan_text(text: str, file: str = "<inline>") -> List[Dict[str, Any]]:
    """从单个文件的文本抽取引用点。

    返回 ``[{file, line, kind, specifier, imported, note?}]``。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    found: List[Dict[str, Any]] = []
    for i, line in enumerate(lines):
        line_no = i + 1
        for point in _scan_line(line, file, line_no):
            found.append(point)
    return found


def _scan_line(line: str, file: str, line_no: int) -> List[Dict[str, Any]]:
    found: List[Tuple[int, Dict[str, Any]]] = []  # (pos, point) —— 同一行内按出现位置排序后再输出

    # ① import ... from "x" / import "x"
    for m in STATIC_IMPORT.finditer(line):
        clause = m.group(1)
        found.append((m.start(), {
            "file": file,
            "line": line_no,
            "kind": "import",
            "specifier": m.group(3),
            "imported": parse_import_clause(clause),
        }))
    # ② export ... from "x"
    for m in EXPORT_FROM.finditer(line):
        found.append((m.start(), {
            "file": file,
            "line": line_no,
            "kind": "export-from",
            "specifier": m.group(2),
            "imported": ["*"],
        }))

    # ③ require(...) / import(...) —— **一个调用点必定产出一个引用点**。
    #
    # 不再用"静态字面量正则 + 动态兜底正则"两条互补规则，而是先定位调用点、
    # 再对参数**分类**。原因（旧仓 M2 实测）：互补正则合起来并不构成全覆盖，
    # ``require("chalk" + suffix)`` / ``require("./" + x)`` / ``import("chalk" + s)``
    # 三条都同时落进两条正则的空隙，被**静默丢弃**——那正是本文件头部纪律明令禁止的
    # "把解析不到当不存在"。分类法对任何一种参数形态都只会落进两个桶之一：
    #   静态（可确定的字面量）→ kind = require / dynamic-import
    #   其余（变量、拼接、插值模板、表达式）→ kind = ambiguous，**显式出现在结果里**
    #
    # 解构形态额外记下被取用的符号。键 = 调用点自身的下标，不是整条
    # ``const {…} = require(…)`` 的起始下标（两者相差 ``"const {…} = "` 那一段；
    # 旧仓早期版本拿 ``m.index`` 当键，导致 imported 恒为空，判定层把红条目全判绿）。
    destructured: Dict[int, List[str]] = {}
    for m in REQUIRE_DESTRUCTURED.finditer(line):
        key = m.start() + m.group(0).index("require")
        destructured[key] = parse_destructured_names(m.group(1))
    for m in CALL_SITE.finditer(line):
        callee = m.group(1)
        arg = _read_call_argument(line, m.start() + len(m.group(0)) - 1)
        if arg is None:
            # 参数没闭合（跨行调用）：不能确定就显式记 ambiguous，不丢
            found.append((m.start(), {
                "file": file,
                "line": line_no,
                "kind": "ambiguous",
                "specifier": None,
                "imported": [],
                "note": "%s(…跨行…)" % callee,
            }))
            continue
        trimmed = arg.strip()
        static_match = STATIC_ARG.match(trimmed)
        if static_match:
            specifier = static_match.group(1) or static_match.group(2) or static_match.group(3)
            if callee == "require":
                found.append((m.start(), {
                    "file": file,
                    "line": line_no,
                    "kind": "require",
                    "specifier": specifier,
                    "imported": destructured.get(m.start(), []),
                }))
            else:
                found.append((m.start(), {
                    "file": file,
                    "line": line_no,
                    "kind": "dynamic-import",
                    "specifier": specifier,
                    "imported": ["*"],
                }))
            continue
        found.append((m.start(), {
            "file": file,
            "line": line_no,
            "kind": "ambiguous",
            "specifier": None,
            "imported": [],
            "note": "%s(%s)" % (callee, _truncate(trimmed)),
        }))

    # ④ jest.mock("x")
    for m in JEST_MOCK.finditer(line):
        found.append((m.start(), {
            "file": file,
            "line": line_no,
            "kind": "jest-mock",
            "specifier": m.group(2),
            "imported": [],
        }))

    found.sort(key=lambda pair: pair[0])  # 同行内按出现位置（确定性）
    return [point for _pos, point in found]


def _read_call_argument(line: str, open_index: int) -> Optional[str]:
    """从 ``(`` 的下标开始切出一对括号之间的参数文本（不递归解析语法，只做配平 + 跳过字符串）。

    同一行内找不到闭合括号时返回 ``None``（调用点跨行或写法极端）。
    """
    depth = 0
    quote = None
    i = open_index
    while i < len(line):
        ch = line[i]
        if quote is not None:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("\"", "'", "`"):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return line[open_index + 1: i]
        i += 1
    return None


def _truncate(s: str, n: int = 40) -> str:
    t = str(s).strip()
    return (t[:n] + "…") if len(t) > n else t


def parse_destructured_names(clause: Any) -> List[str]:
    """``const { a, b: c } = require("p")`` → ``["a","b"]``（取左侧的原名，不是本地别名）。"""
    names: List[str] = []
    for item in str(clause if clause is not None else "").split(","):
        raw = item.strip()
        if not raw:
            continue
        # 剥掉默认值与 rest
        cleaned = re.sub(r"^\.\.\.", "", raw).split("=")[0].strip()
        original = cleaned.split(":")[0].strip()
        if original and re.match(r"^[A-Za-z0-9_$]+$", original):
            names.append(original)
    return names


def parse_import_clause(clause: Any) -> List[str]:
    """解析 import 子句 → 导入符号表。

    ``import x from`` → ``["default"]``；``import {a, b as c}`` → ``["a","b"]``；
    ``import * as ns`` → ``["*"]``。
    """
    if not clause:
        return []
    parts: List[str] = []
    named = re.search(r"\{([^}]*)\}", clause)
    if named:
        for item in named.group(1).split(","):
            name = re.split(r"\s+as\s+", item)[0].strip()
            name = re.sub(r"^type\s+", "", name)
            if name:
                parts.append(name)
    if re.search(r"\*\s*as\s+[A-Za-z0-9_$]+", clause):
        parts.append("*")
    before_brace = clause.split("{")[0].strip()
    if before_brace and not before_brace.startswith("*"):
        default_part = re.sub(r",$", "", before_brace).strip()
        if default_part and not default_part.startswith("*"):
            parts.append("default")
    return parts


def find_bare_package_literals(text: str, dep_names: Optional[Set[str]]) -> List[Dict[str, Any]]:
    """字符串兜底扫描的**误报抑制**（旧仓 ``data/README.md`` §5.3 第 3 条：两条同时成立才计入）：

      ① 字符串形似包名（含 ``pkg/sub`` 形态）；
      ② 其包名部分命中已装依赖名集合。

    只满足 ① 的字符串（文案里的 ``"lodash"`` 而项目没装 lodash）**不计入**。

    ``text`` 源文件文本；``dep_names`` 已装依赖名（来自 package.json 的
    dependencies ∪ devDependencies）。返回 ``[{specifier, line}]``。
    """
    out: List[Dict[str, Any]] = []
    if not dep_names:
        return out
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # 被当作动态 specifier 用过的标识符（``require(name)`` / ``import(name)``）：
    # 它们的**声明右值**已经由调用点扫描器判成 AMBIGUOUS，兜底不得再计一次。
    # 反例（旧仓 M2 实测）：``const name = "chalk"; require(name)`` 会让第 2 行同时出现
    # AMBIGUOUS（调用点）与 RESOLVED "chalk"（初始化表达式）——同一个引用点两种结论。
    dynamic_idents: Set[str] = set()
    for line in lines:
        for m in CALL_SITE.finditer(line):
            arg = _read_call_argument(line, m.start() + len(m.group(0)) - 1)
            arg_text = arg.strip() if arg is not None else ""
            if not arg_text:
                continue
            if STATIC_ARG.match(arg_text):
                continue  # 静态字面量：没有参与拼装的标识符
            # 非静态参数：参数里出现的每个标识符都可能参与拼装 specifier
            for ident in _IDENT.finditer(arg_text):
                dynamic_idents.add(ident.group(0))
    for i, line in enumerate(lines):
        call_arg_spans = _call_argument_spans(line)
        for m in ANY_STRING_LITERAL.finditer(line):
            # 落在 ``require(…)`` / ``import(…)`` 参数区里的字面量归**调用点扫描器**管，
            # 兜底不得再计一次。反例（旧仓 M2 实测）：``require("chalk" + suffix)`` 的字面量
            # 前缀若被兜底计成 chalk 引用点，同一行会同时出现 RESOLVED 与 AMBIGUOUS。
            if any(from_ <= m.start() < to for from_, to in call_arg_spans):
                continue
            # 声明右值且标识符已被用作动态 specifier → 同上，已由调用点覆盖
            decl = re.match(r"^\s*(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=", line)
            if decl and decl.group(1) in dynamic_idents and m.start() >= line.find("="):
                continue
            raw = m.group(2).strip()
            if not BARE_PACKAGE_NAME.match(raw):
                continue
            if raw.startswith("@"):
                name_part = "/".join(raw.split("/")[:2])
            else:
                name_part = raw.split("/")[0]
            if name_part not in dep_names:
                continue
            out.append({"specifier": raw, "line": i + 1})
    return out


def _call_argument_spans(line: str) -> List[Tuple[int, int]]:
    """一行里所有 ``require(`` / ``import(`` 的参数区 ``[from, to)``（与 :func:`_read_call_argument` 同口径）。"""
    spans: List[Tuple[int, int]] = []
    for m in CALL_SITE.finditer(line):
        open_index = m.start() + len(m.group(0)) - 1
        arg = _read_call_argument(line, open_index)
        # 参数没闭合（跨行）时保守地取到行尾
        end = len(line) if arg is None else open_index + 1 + len(arg) + 1
        spans.append((open_index + 1, end))
    return spans


def is_known_kind(kind: str) -> bool:
    """kind 是否属于契约枚举（自检用：新增 kind 忘了进 spec 会被测试抓）。"""
    return kind in KIND


def scan_sources_texts(sources: Iterable[Mapping[str, Any]], dep_names: Optional[Set[str]] = None,
                       max_file_bytes: Optional[int] = None) -> Dict[str, Any]:
    """对输入层已收集的源码文本全量抽取（旧仓 ``scanSources`` 的文件面部分）。

    ``sources`` 是 ``[{file, text}]``（目录遍历/编码处理在输入层）；超大文件按
    UTF-8 字节数**降级为字符串兜底扫描并显式记账**，不静默跳过——用户必须看得见
    "这份文件没被完整分析"。
    """
    limit = SOURCE_FILE_BYTES if max_file_bytes is None else max_file_bytes
    points: List[Dict[str, Any]] = []
    gaps: List[Dict[str, Any]] = []
    files: List[str] = []
    for source in sources:
        rel = source["file"]
        text = source["text"]
        files.append(rel)
        size = len(text.encode("utf-8"))
        if size > limit:
            gaps.append({
                "kind": LARGE_FILE_DOWNGRADED,
                "file": rel,
                "detail": "%d 字节 > 上限 %d，降级为字符串兜底扫描" % (size, limit),
            })
        for p in scan_text(text, rel):
            points.append(p)
        # 字符串兜底（§5.3 第 3 条）：只在给了已装依赖名集合时才跑，双条件过滤后计入。
        # **必须去重**：``require("chalk")`` 里的 "chalk" 也是形似包名的字面量，
        # 但它已被 require 结构化抽取覆盖；再计一次就是同一引用点算两遍（假阳性）。
        if dep_names:
            for hit in find_bare_package_literals(text, dep_names):
                already = any(
                    p["file"] == rel and p["line"] == hit["line"] and p["specifier"] == hit["specifier"]
                    for p in points
                )
                if already:
                    continue
                points.append({
                    "file": rel,
                    "line": hit["line"],
                    "kind": "string-literal",
                    "specifier": hit["specifier"],
                    "imported": [],
                })
    points.sort(key=lambda p: (p["file"], p["line"]))
    files.sort()
    return {"files": files, "points": points, "gaps": gaps}
