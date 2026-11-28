"""模块 ③b · 判定层（招牌，1:1 移植自旧仓 ``src/check.mjs``）。

纯函数：输入事实（依赖面 + 引用点），输出判定态与证据。不碰退出码、不写文件、不读
文件系统（导出面读取所需的**包内文件文本**由输入层放进 subject，见 ``docs/depcheck-live.md`` §1）。

判定顺序写死（旧仓 ``plan/03`` §4.4，首个成立者胜）：
  AMBIGUOUS → NOT-EXPORTED-SUBPATH → ESM-CJS-MISMATCH → UNPARSEABLE → MISSING-EXPORT → RESOLVED
顺序本身有测试（同一输入只许出一条判定态）。

**误报比漏报代价高**：读不出导出集时记 UNPARSEABLE 进 gaps，**不判 MISSING-EXPORT**。
"""

from __future__ import annotations

import posixpath
import re
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .resolve import (
    CONDITIONS,
    match_subpath,
    resolve_conditional,
    substitute_wildcard,
)
from .spec import STATUS, UNPARSEABLE

_ESM_ORDER: Tuple[str, ...] = CONDITIONS["import"]
_CJS_ORDER: Tuple[str, ...] = CONDITIONS["require"]

#: 判定态简写
_RESOLVED = STATUS["RESOLVED"]
_MISSING_EXPORT = STATUS["MISSING_EXPORT"]
_ESM_CJS_MISMATCH = STATUS["ESM_CJS_MISMATCH"]
_NOT_EXPORTED_SUBPATH = STATUS["NOT_EXPORTED_SUBPATH"]
_AMBIGUOUS = STATUS["AMBIGUOUS"]


def judge_point(point: Mapping[str, Any], deps: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """对一个引用点求判定态。

    ``point`` 是 ``{file,line,kind,specifier,imported,note?}``；``deps`` 是
    包名 → 依赖面记录（由 :func:`build_dep_index` 建，带 ``index`` / ``files``）。
    返回 ``{status, evidence, gap?, outOfScope?}``；``status`` 为 ``None`` 时只出 gap
    或标记 out-of-scope（不进 findings）。
    """
    # ① 动态形态：不可静态判定。**不得当作"没问题"**。
    if point.get("kind") == "ambiguous" or point.get("specifier") is None:
        return {
            "status": _AMBIGUOUS,
            "evidence": {"file": point["file"], "line": point["line"], "note": point.get("note") or "动态 specifier"},
        }

    split = split_specifier(point["specifier"])
    if split is None:
        return {
            "status": _AMBIGUOUS,
            "evidence": {"file": point["file"], "line": point["line"], "note": "specifier 无法切分"},
        }
    # 非依赖引用（相对路径、node: 内置、绝对路径）不在判定面内 —— 显式标注，不进 findings
    if split["name"] not in deps:
        return {
            "status": None,
            "outOfScope": True,
            "evidence": {"file": point["file"], "line": point["line"], "note": "非已装依赖: %s" % split["name"]},
        }

    dep = deps[split["name"]]

    # ② 包本身不可用（node_modules 缺它 / exports 解析不了）→ 算不了，进 gaps
    if dep.get("parseState") == "NO_PACKAGE_JSON":
        return {
            "status": None,
            "gap": {"kind": "NO_PACKAGE_JSON", "pkg": split["name"], "detail": "依赖未安装或 package.json 不可解析"},
            "evidence": {"file": point["file"], "line": point["line"], "pkg": split["name"]},
        }
    if dep.get("parseState") == UNPARSEABLE:
        return {
            "status": None,
            "gap": {"kind": UNPARSEABLE, "pkg": split["name"], "detail": "exports 形态无法解析，该引用点不可静态判定"},
            "evidence": {"file": point["file"], "line": point["line"], "pkg": split["name"]},
        }
    # 包未声明 exports：Node 按 main/index 兜底，本项目不复刻整个文件系统解析 → 不猜
    if dep.get("parseState") == "NOT_DECLARED":
        return {
            "status": None,
            "gap": {"kind": "EXPORTS_NOT_DECLARED", "pkg": split["name"], "detail": "该包未声明 exports，首期不复刻 main 兜底解析"},
            "evidence": {"file": point["file"], "line": point["line"], "pkg": split["name"]},
        }

    sub = match_subpath(dep["index"], split["subpath"])

    # ③ 子路径不在 exports 里 → NOT-EXPORTED-SUBPATH
    if sub["kind"] == "none":
        return {
            "status": _NOT_EXPORTED_SUBPATH,
            "evidence": {
                "file": point["file"],
                "line": point["line"],
                "pkg": split["name"],
                "subpath": split["subpath"],
                "rule": "exports 未列该子路径",
                "exportsKeys": [e["key"] for e in dep["index"]["entries"]],
            },
        }

    # ③b ``null`` 屏蔽（含数组里落成 blocked 的形态）→ 也是 NOT-EXPORTED-SUBPATH，
    #     不是"不存在"（旧仓 ``data/README.md`` §5 形态③）。逐视角求值才能看见数组里的 null。
    is_require_point = point.get("kind") == "require"
    esm_resolved = _resolve_target(dep, sub, split["subpath"], _ESM_ORDER)
    own_resolved = _resolve_target(dep, sub, split["subpath"], _CJS_ORDER) if is_require_point else esm_resolved
    if own_resolved["state"] == "blocked" or esm_resolved["state"] == "blocked":
        return {
            "status": _NOT_EXPORTED_SUBPATH,
            "evidence": {
                "file": point["file"],
                "line": point["line"],
                "pkg": split["name"],
                "subpath": split["subpath"],
                "rule": "exports 显式 null 屏蔽",
                "exportsKeys": [e["key"] for e in dep["index"]["entries"]],
            },
        }

    # ④ ESM-CJS-MISMATCH：旧仓 ``data/README.md`` §5.2 的**四条同时成立**。
    #    核心判据是"exports 无 require 分支"，**不是** type 字段——zod/date-fns/glob 都是
    #    type: module 却有 require 分支，require() 行为正常，必须判 RESOLVED。
    if is_require_point:
        type_is_module = dep.get("type") == "module"
        no_require_branch = dep.get("hasRequireBranch") is False
        looks_esm_only = type_is_module or _is_mjs_target(esm_resolved["target"])
        if looks_esm_only and no_require_branch and esm_resolved["state"] == "ok":
            esm_surface = read_export_surface(dep, esm_resolved["target"])
            requested = [s for s in (point.get("imported") or []) if s != "*" and s != ""]
            # 第 4 条：被取用的 API 不在命名空间上、而在 `.default` 下。
            #   · 有具名取用且这些名字确实是命名空间上的具名导出 → 命名空间直取可达 → 不判 MISMATCH；
            #   · 其余（无取用信息 / 取的名字不在命名空间上 / 只有 default 出口）→ API 挂在 .default 下 → MISMATCH。
            reachable_on_namespace = (
                esm_surface["ok"]
                and len(requested) > 0
                and all(sym != "default" and sym in esm_surface["names"] for sym in requested)
            )
            if not reachable_on_namespace:
                return {
                    "status": _ESM_CJS_MISMATCH,
                    "evidence": {
                        "file": point["file"],
                        "line": point["line"],
                        "pkg": split["name"],
                        "type": dep.get("type"),
                        "hasRequireBranch": dep.get("hasRequireBranch"),
                        "requested": requested,
                        "rule": "exports 无 require 分支，require() 得到命名空间对象，API 在 .default 下",
                        "exportsKeys": [e["key"] for e in dep["index"]["entries"]],
                    },
                }

    # ⑤ 读导出集（静态）。读不出 → UNPARSEABLE（进 gaps，不判 MISSING）
    target = own_resolved
    if target["state"] != "ok":
        return {
            "status": None,
            "gap": {
                "kind": "UNRESOLVABLE_TARGET",
                "pkg": split["name"],
                "detail": "条件集不匹配或目标非法（视角=%s；state=%s）" % (
                    "require" if is_require_point else "import", target["state"],
                ),
            },
            "evidence": {"file": point["file"], "line": point["line"], "pkg": split["name"], "subpath": split["subpath"]},
        }

    surface = read_export_surface(dep, target["target"])
    if not surface["ok"]:
        return {
            "status": None,
            "gap": {
                "kind": "EXPORT_SURFACE_UNPARSEABLE",
                "pkg": split["name"],
                "detail": surface["reason"],
                "target": target["target"],
            },
            "evidence": {"file": point["file"], "line": point["line"], "pkg": split["name"], "subpath": split["subpath"]},
        }

    # ⑥ 符号检查：``*`` / 空 imported 视为"只加载包，不取符号"→ RESOLVED
    wanted = [s for s in (point.get("imported") or []) if s != "*" and s != ""]
    if len(wanted) == 0:
        return {
            "status": _RESOLVED,
            "evidence": {
                "file": point["file"], "line": point["line"], "pkg": split["name"],
                "subpath": split["subpath"], "target": target["target"],
            },
        }
    missing = [sym for sym in wanted if sym != "default" and sym not in surface["names"]]
    if len(missing) > 0:
        return {
            "status": _MISSING_EXPORT,
            "evidence": {
                "file": point["file"],
                "line": point["line"],
                "pkg": split["name"],
                "subpath": split["subpath"],
                "target": target["target"],
                "missing": missing,
                "available": sorted(surface["names"])[:20],
            },
        }
    return {
        "status": _RESOLVED,
        "evidence": {
            "file": point["file"], "line": point["line"], "pkg": split["name"],
            "subpath": split["subpath"], "target": target["target"],
        },
    }


def _is_mjs_target(target: Any) -> bool:
    return isinstance(target, str) and target.endswith(".mjs")


def _resolve_target(dep: Mapping[str, Any], sub: Mapping[str, Any], subpath: str,
                    conditions: Tuple[str, ...]) -> Dict[str, Any]:
    """按视角解析出目标文件。通配先替换再走条件解析。"""
    value = substitute_wildcard(sub["key"], subpath, sub["value"]) if sub["kind"] == "pattern" else sub["value"]
    return resolve_conditional(value, conditions)


def build_dep_index(record: Mapping[str, Any]) -> Dict[str, Any]:
    """从 subject 的依赖事实重建判定所需字段（旧仓 ``indexFor`` + ``describeExports``）。

    ``record`` 键：``installed_version`` / ``type`` / ``exports``（可缺省 = 未声明）/
    ``files``（包内文件文本）。**不读文件系统** —— 文件文本由输入层放进 subject。
    """
    files: Dict[str, Dict[str, Any]] = {}
    for rel, entry in (record.get("files") or {}).items():
        files[rel] = {"text": entry.get("text", ""), "type": entry.get("type")}
    return {
        "name": record.get("name"),
        "installedVersion": record.get("installed_version"),
        "declaredRange": record.get("declared_range"),
        "type": record.get("type"),
        "files": files,
        **describe_exports(record),
    }


def describe_exports(record: Mapping[str, Any]) -> Dict[str, Any]:
    """对 subject 依赖记录跑 ``exports`` 结构描述（走 ``resolve.describe_exports``）。

    ``exports`` 键缺失（JSON 无 undefined）由 ``resolve.ABSENT`` 哨兵语义处理：
    缺键与显式 ``null`` 都判 ``NOT_DECLARED``（原文 ⑩：``exports: null`` 等同未声明）。
    """
    from .resolve import describe_exports as _describe

    return _describe(record)


def read_export_surface(dep: Mapping[str, Any], target_rel: str) -> Dict[str, Any]:
    """静态读导出集（旧仓 ``plan/03`` §4.3）。读不出**不猜**——返回 ``ok: False`` 让调用方记 gap。

    三种可识别形态：CJS 赋值形 / ESM 声明形 / **相对 re-export 递归**。
    为什么必须递归：``date-fns@4.4.0`` 的入口 ``index.js`` 是 245 行
    ``export * from "./x.js"``，``zod@4.6.7`` 的 ``index.cjs`` 是
    ``__exportStar(require("./v4/…"), exports)``，只看首层会读出**空导出集**，
    于是每个真实引用点都变 MISSING-EXPORT（系统性假阳性）。
    递归只沿**相对**路径走；外部 re-export（``export * from "pkg"``）仍记 UNPARSEABLE，
    口径与旧仓 ``plan/03`` §4.3 一致。

    文本来自 ``dep["files"]``（输入层供给）；读不到的文件按"不可读"处理（首层 → 算不了，
    桶文件里一支 → 跳过并记 sawReexportExternal，不因此判整包算不了）。
    """
    seen: Set[str] = set()
    names: Set[str] = set()
    pending: List[str] = [target_rel]
    saw_reexport_external = False
    external_from = None
    depth = 0

    while pending:
        # 旧仓以 ``join(pkgDir, rel)`` 读文件：``./`` 前缀被路径归一化吃掉；
        # 器官的 files 键是包内相对路径，查找前先 normpath（等价归一，不读文件系统）
        rel = posixpath.normpath(pending.pop())
        if rel in seen:
            continue  # 环与重复桶：每个文件只读一次，递归天然收敛
        seen.add(rel)
        entry = dep["files"].get(rel)
        if entry is None:
            reason = "目标文件不可读: %s（missing）" % rel
            if len(seen) == 1:
                return {"ok": False, "reason": reason}
            saw_reexport_external = True
            if external_from is None:
                external_from = reason
            continue
        depth += 1
        text = entry["text"]
        is_esm = is_esm_file(dep, rel, entry.get("type"))
        r = _read_esm_surface(text) if is_esm else _read_cjs_surface(text)
        if not r["ok"]:
            # 首层读不出 → 真算不了；桶文件某一支读不出 → 记下来，最后若无其它证据仍算不了
            if len(seen) == 1:
                return r
            saw_reexport_external = True
            if external_from is None:
                external_from = r["reason"]
            continue
        names.update(r["names"])
        for nxt in r["relativeFrom"]:
            if not nxt.startswith("./") and not nxt.startswith("../"):
                saw_reexport_external = True
                if external_from is None:
                    external_from = "外部 re-export: %s" % nxt
                continue
            pending.append(_resolve_relative(rel, nxt))

    if len(names) == 0 and saw_reexport_external:
        return {"ok": False, "reason": external_from}
    return {"ok": True, "names": names}


def _resolve_relative(from_rel: str, specifier: str) -> str:
    """把 ``./x.js`` 从 ``from_rel`` 所在目录解析成包内相对路径（一律正斜杠，走 posix 语义）。"""
    return posixpath.normpath(posixpath.join(posixpath.dirname(from_rel), specifier))


def is_esm_file(dep: Mapping[str, Any], rel: str, file_type: Optional[str] = None) -> bool:
    """目标文件的模块类型判定。

    旧仓口径 = **最近的** ``package.json`` 的 ``type``（Node 的 Module Type 判定）——
    不能只看包根：``glob`` 的 ``dist/commonjs/package.json`` 写着 ``type: commonjs``，
    按包根判会把 CJS 产物当 ESM 解析，导出集读成空（实测 0 个）。
    "最近的 package.json" 是文件系统遍历，属输入层；输入层按同一口径给出每个文件的
    ``type``（无嵌套 package.json 时回落包根 ``type``），本函数只保留扩展名硬规则与比对。
    """
    if rel.endswith(".mjs"):
        return True
    if rel.endswith(".cjs"):
        return False
    return file_type == "module"


_RE_EXPORTS_DOT = re.compile(r"\bexports\s*\.\s*([A-Za-z0-9_$]+)\s*=")
_RE_EXPORTS_BRACKET = re.compile(r"\bexports\s*\[\s*[\"']([A-Za-z0-9_$]+)[\"']\s*\]\s*=")
_RE_DEFINE_PROP_EXPORTS = re.compile(r"\bObject\.defineProperty\s*\(\s*exports\s*,\s*[\"']([A-Za-z0-9_$]+)[\"']")
_RE_DEFINE_PROP_MODULE = re.compile(r"\bObject\.defineProperty\s*\(\s*module\.exports\s*,\s*[\"']([A-Za-z0-9_$]+)[\"']")
_RE_EXPORT_STAR_REQUIRE = re.compile(r"__exportStar\s*\(\s*require\s*\(\s*[\"']([^\"']+)[\"']\s*\)")
_RE_VAR_REQUIRE = re.compile(r"(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*require\s*\(\s*[\"']([^\"']+)[\"']\s*\)")
_RE_MODULE_EXPORTS_ASSIGN = re.compile(r"module\.exports\s*=\s*\{([\s\S]*?)\}\s*;?\s*$", re.MULTILINE)
_RE_HAS_MODULE_EXPORTS = re.compile(r"\bmodule\.exports\s*=")
_RE_DIRECT_NAME = re.compile(r"(?:^|,)\s*(?:(?:async|const|let|var|function)\s+)?([A-Za-z0-9_$]+)\s*(?:[:(,]|\Z)")
_RE_EXPORT_DECL = re.compile(r"\bexport\s+(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z0-9_$]+)")
_RE_EXPORT_BRACES = re.compile(r"\bexport\s*\{([^}]*)\}")
_RE_HAS_EXPORT_DEFAULT = re.compile(r"\bexport\s+default\b")
_RE_EXPORT_FROM = re.compile(r"\bexport\s+(?:\*|\{[^}]*\})\s+from\s+[\"']([^\"']+)[\"']")
_RE_EXPORT_STAR_AS = re.compile(r"\bexport\s+\*\s+as\s+[A-Za-z0-9_$]+\s+from\s+[\"']([^\"']+)[\"']")


def _read_cjs_surface(text: str) -> Dict[str, Any]:
    names: Set[str] = set()
    relative_from: List[str] = []
    # module.exports = { a, b } / exports.a = / exports["a"] = / Object.defineProperty(exports, "a", …)
    for m in _RE_EXPORTS_DOT.finditer(text):
        names.add(m.group(1))
    for m in _RE_EXPORTS_BRACKET.finditer(text):
        names.add(m.group(1))
    for m in _RE_DEFINE_PROP_EXPORTS.finditer(text):
        names.add(m.group(1))
    for m in _RE_DEFINE_PROP_MODULE.finditer(text):
        names.add(m.group(1))
    # 桶文件：``__exportStar(require("./x"), exports)``（zod 的 index.cjs 就是这一形态）
    for m in _RE_EXPORT_STAR_REQUIRE.finditer(text):
        relative_from.append(m.group(1))
    # 桶文件（另一种）：``var _index = require("./add.cjs"); Object.keys(_index).forEach(...)``
    # date-fns@4.4.0 的 index.cjs 是 245 组这种形态（共 8885 行）。
    # 判据不是"有 require"（普通引用也有），而是**同一文件里对该标识符做了 ``Object.keys(…)`` 枚举转发**。
    bound: Dict[str, str] = {}
    for m in _RE_VAR_REQUIRE.finditer(text):
        if m.group(2).startswith("."):
            bound[m.group(1)] = m.group(2)
    for ident, target in bound.items():
        if re.search(r"\bObject\.keys\s*\(\s*%s\s*\)" % re.escape(ident), text):
            relative_from.append(target)

    direct = _RE_MODULE_EXPORTS_ASSIGN.search(text)
    if direct:
        for m in _RE_DIRECT_NAME.finditer(direct.group(1)):
            names.add(m.group(1))
    if _RE_HAS_MODULE_EXPORTS.search(text) and len(names) == 0 and len(relative_from) == 0:
        # ``module.exports = someIdentifier`` / 函数 / 调用表达式：**读不出具名导出 → 不猜**
        return {"ok": False, "reason": "module.exports 为表达式/标识符，具名导出集不可静态确定", "relativeFrom": []}
    return {"ok": True, "names": names, "relativeFrom": relative_from}


def _read_esm_surface(text: str) -> Dict[str, Any]:
    names: Set[str] = set()
    relative_from: List[str] = []
    for m in _RE_EXPORT_DECL.finditer(text):
        names.add(m.group(1))
    for m in _RE_EXPORT_BRACES.finditer(text):
        for item in m.group(1).split(","):
            name = re.split(r"\s+as\s+", item).pop().strip()
            if name and not name.startswith("type "):
                names.add(name)
    if _RE_HAS_EXPORT_DEFAULT.search(text):
        names.add("default")
    for m in _RE_EXPORT_FROM.finditer(text):
        relative_from.append(m.group(1))
    for m in _RE_EXPORT_STAR_AS.finditer(text):
        relative_from.append(m.group(1))
    saw_reexport_external = any(not f.startswith(".") for f in relative_from)
    if saw_reexport_external and len(names) == 0 and all(not f.startswith(".") for f in relative_from):
        return {"ok": False, "reason": "仅外部 re-export，具名导出集需递归解析（首期不复刻）", "relativeFrom": []}
    return {"ok": True, "names": names, "relativeFrom": relative_from}


#: 依赖名解析：``@scope/name/sub`` → ``{name: "@scope/name", subpath: "./sub"}``；
#: ``pkg/sub`` → ``{name: "pkg", subpath: "./sub"}``（迁自旧仓 ``src/snapshot.mjs`` splitSpecifier）。
def split_specifier(specifier: Any) -> Optional[Dict[str, str]]:
    if not isinstance(specifier, str) or specifier == "":
        return None
    parts = specifier.split("/")
    if specifier.startswith("@"):
        if len(parts) < 2:
            return None
        name = "%s/%s" % (parts[0], parts[1])
        rest = "/".join(parts[2:])
        return {"name": name, "subpath": ("./%s" % rest) if rest else "."}
    name = parts[0]
    rest = parts[1:]
    return {"name": name, "subpath": ("./%s" % "/".join(rest)) if rest else "."}
