"""模块 ③a · ``exports`` 解析（Node 官方语义，1:1 移植自旧仓 ``src/resolve.mjs``）。

判据来源：旧仓 ``data/README.md`` §1 D1 + §5.4（M1 逐条对照 Node 官方解析算法原文，
同轮用本机 Node 24.15.0 对每条规则做黑盒实测交叉验证）。

原文锚点（nodejs.org/api）：
  · packages.html#package-entry-points —— 六形态的**声明层**语义（sugar / 条件 / 子路径 /
    通配 / null 屏蔽 / 嵌套条件）
  · esm.html#resolution-algorithm-spec —— 解析的**算法层**：
    PACKAGE_EXPORTS_RESOLVE / PACKAGE_IMPORTS_EXPORTS_RESOLVE / PACKAGE_TARGET_RESOLVE /
    PATTERN_KEY_COMPARE

D1 核对结论（M1 实测，修正了 M0 骨架的 10 处偏差；逐条向量在旧仓 tests/resolve.test.mjs，
本器官在 ``tests/test_depcheck-live.py`` 内联同族向量）：
  ① 条件匹配顺序 = **目标对象自身的键序**，不是"条件优先级数组序"。
  ② 嵌套条件**无映射时继续父层的后续条件**（原文："nested conditions behave analogously to
     nested JavaScript `if` statements"）。
  ③ 条件集实测：import 视角 = ["node","import","module-sync","node-addons"]，
     require 视角 = ["node","require","module-sync","node-addons"]，``default`` 恒命中。
     ``types`` / ``browser`` / ``development`` / ``production`` **不在** Node 的条件集里。
  ④ 通配必须排除"等于 patternBase"；带 trailer 时还要 ``matchKey.length >= expansionKey.length``。
  ⑤ 通配优先级 = PATTERN_KEY_COMPARE：先比 ``*`` 的下标（大者优先），再比整键长度（长者在先）。
  ⑥ 通配目标里的 ``*`` **全部**替换（原文："every instance of `*`"）。
  ⑦ 数组回退：空数组 → 屏蔽；逐项求值，``invalid``/``unmatched`` 继续，``null`` 也继续。
  ⑧ 目标字符串必须以 ``"./"`` 开头，否则 Invalid Package Target。
  ⑨ 键形态：**混合子路径键与条件键** → Invalid Package Configuration（整包算不了）；
     末尾斜杠键、多 ``*`` 键 → Node **忽略该键**（不致命）。
  ⑩ ``exports: null`` 等同于未声明（Node 回落到 index/main），不是"屏蔽"。

三条纪律（错一处会让整族判定反转）：
  · 顺序与"最具体优先"是两条独立规则，**不得合并实现**；
  · ``null`` 是**屏蔽语义**（→ NOT-EXPORTED-SUBPATH），不是"不存在"；
  · 解析不了的一律 ``UNPARSEABLE`` + 进 gaps，**不得静默跳过**。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .spec import CONDITIONS, EXPORTS_KEYS_LIMIT, UNPARSEABLE

#: ``exports`` 字段缺省（JS ``undefined``）的哨兵：与显式 ``null``（屏蔽？不 —— 未声明）区分。
#: JSON 里没有 undefined，输入层"键不存在"映射到本哨兵。
ABSENT = object()

_COND_IMPORT: Tuple[str, ...] = CONDITIONS["import"]
_COND_REQUIRE: Tuple[str, ...] = CONDITIONS["require"]


def _is_object(value: Any) -> bool:
    return isinstance(value, dict)


def is_declared(exports_field: Any) -> bool:
    """``exports`` 字段是否为空（缺省）——缺省时 Node 按 main/index 兜底，本项目记 ``NOT_DECLARED``。

    ``ABSENT`` 与 ``None``（JSON null）都算未声明（原文 ⑩）。
    """
    return exports_field is not ABSENT and exports_field is not None


def build_exports_index(exports_field: Any) -> Dict[str, Any]:
    """把 ``exports`` 规范化成**子路径映射**（内部表示）。

    返回 ``{"entries": [{key, value}], "unparseable": bool, "ignored": [key]}``；
    ``ignored`` = 被 Node 忽略的键（末尾斜杠 / 多 ``*``），保留下来只为证据可追溯，
    **不参与匹配**。
    """
    # 形态① sugar：字符串 / 数组 都是"整包一个入口值"
    if isinstance(exports_field, str) or isinstance(exports_field, list):
        return {"entries": [{"key": ".", "value": exports_field}], "unparseable": False, "ignored": []}
    if not _is_object(exports_field):
        return {"entries": [], "unparseable": True, "ignored": []}

    keys = list(exports_field.keys())
    # 阈值（``data/README.md`` §5.3）：子路径键数超限 → 整包算不了，**不得截断静默**
    if len(keys) > EXPORTS_KEYS_LIMIT:
        return {"entries": [], "unparseable": True, "ignored": []}
    subpath_keys = [k for k in keys if k == "." or k.startswith("./")]
    condition_keys = [k for k in keys if k != "." and not k.startswith("./")]

    # ⑨ 混合形态（既有子路径键又有条件键）在 Node 里是 Invalid Package Configuration
    if subpath_keys and condition_keys:
        return {"entries": [], "unparseable": True, "ignored": []}
    # 形态② sugar：所有键都不是子路径 → 等价于 { ".": 值 }
    if not subpath_keys:
        return {"entries": [{"key": ".", "value": exports_field}], "unparseable": False, "ignored": []}

    entries: List[Dict[str, Any]] = []
    ignored: List[str] = []
    for key in keys:
        # ⑨ 末尾斜杠 / 多通配：Node 忽略该键，**不致命**（其余入口仍可用）
        if key.endswith("/") or key.count("*") > 1:
            ignored.append(key)
            continue
        entries.append({"key": key, "value": exports_field[key]})
    return {"entries": entries, "unparseable": False, "ignored": ignored}


def match_subpath(index: Mapping[str, Any], subpath: str) -> Dict[str, Any]:
    """子路径匹配 —— 逐条实现 PACKAGE_IMPORTS_EXPORTS_RESOLVE。

    返回 ``{"kind": "exact"|"pattern"|"none", "value", "key", "patternMatch"}``。
    """
    # 请求本身以 "/" 结尾 → 原文先抛 Invalid Module Specifier；本项目按"不导出"处理
    if subpath != "." and subpath.endswith("/"):
        return {"kind": "none", "value": None, "key": None, "patternMatch": None}

    # 精确匹配只认**不含** ``*`` 的键（原文：`is a key of matchObj and does not contain "*"`）
    for entry in index["entries"]:
        if entry["key"] == subpath and "*" not in entry["key"]:
            return {"kind": "exact", "value": entry["value"], "key": entry["key"], "patternMatch": None}

    # 通配候选按 PATTERN_KEY_COMPARE 降序（``*`` 下标大者优先，同则整键长者优先）
    expansions = [e for e in index["entries"] if e["key"].count("*") == 1]
    expansions.sort(key=lambda e: (-e["key"].index("*"), -len(e["key"])))

    for entry in expansions:
        key = entry["key"]
        star = key.index("*")
        base = key[:star]
        trailer = key[star + 1:]
        # ④ 必须 startsWith 且**不等于** patternBase
        if not subpath.startswith(base) or subpath == base:
            continue
        # ④ 带 trailer 时还要长度下界（``matchKey.length >= expansionKey.length``）
        if trailer != "":
            if not subpath.endswith(trailer):
                continue
            if len(subpath) < len(key):
                continue
        pattern_match = subpath[len(base): len(subpath) - len(trailer)]
        return {"kind": "pattern", "value": entry["value"], "key": key, "patternMatch": pattern_match}

    return {"kind": "none", "value": None, "key": None, "patternMatch": None}


def substitute_wildcard(pattern_key: str, subpath: str, target: Any) -> Any:
    """⑥ 通配目标里的 ``*`` **全部**换成实际片段（原文："every instance of `*`"）。"""
    if not isinstance(target, str) or "*" not in pattern_key:
        return target
    star = pattern_key.index("*")
    base = pattern_key[:star]
    trailer = pattern_key[star + 1:]
    middle = subpath[len(base): len(subpath) - len(trailer)]
    return target.replace("*", middle)


def resolve_conditional(value: Any, conditions: Tuple[str, ...]) -> Dict[str, Any]:
    """按 Node 语义解析出一个目标文件路径。

    ``conditions`` 传 ``CONDITIONS["import"]`` 或 ``CONDITIONS["require"]``（**视角**要能分别问）。
    返回 ``{"state": "ok"|"blocked"|"unmatched"|"invalid", "target", "matchedCondition"}``：
      · ``ok``        解析到目标
      · ``blocked``   ``null`` 屏蔽（→ NOT-EXPORTED-SUBPATH）
      · ``unmatched`` 条件/子路径没有映射（原文 Package Path Not Exported）
      · ``invalid``   目标非法（原文 Invalid Package Target → 算不了）
    """
    return _walk(value, conditions)


def _walk(value: Any, conditions: Tuple[str, ...]) -> Dict[str, Any]:
    if value is None:
        return {"state": "blocked", "target": None, "matchedCondition": None}

    if isinstance(value, str):
        # ⑧ 目标必须以 "./" 开头
        if not value.startswith("./"):
            return {"state": "invalid", "target": None, "matchedCondition": None}
        return {"state": "ok", "target": value, "matchedCondition": None}

    if isinstance(value, list):
        # ⑦ 数组回退：空数组 → 屏蔽；逐项求值，invalid/unmatched/null 一律继续
        if len(value) == 0:
            return {"state": "blocked", "target": None, "matchedCondition": None}
        saw_blocked = False
        for item in value:
            r = _walk(item, conditions)
            if r["state"] == "ok":
                return r
            if r["state"] == "blocked":
                saw_blocked = True
                continue
            # invalid / unmatched → 继续下一项（原文：continuing the loop on any Invalid Package Target error）
        if saw_blocked:
            return {"state": "blocked", "target": None, "matchedCondition": None}
        return {"state": "unmatched", "target": None, "matchedCondition": None}

    if _is_object(value):
        # ①② 按**目标对象自身键序**匹配；``default`` 恒命中
        for key in value.keys():
            if key != "default" and key not in conditions:
                continue
            r = _walk(value[key], conditions)
            # ② 嵌套无映射 → 继续父层的后续条件（不是直接判死）
            if r["state"] == "unmatched":
                continue
            return {"state": r["state"], "target": r["target"], "matchedCondition": key}
        return {"state": "unmatched", "target": None, "matchedCondition": None}

    return {"state": "invalid", "target": None, "matchedCondition": None}


def has_require_branch(index: Mapping[str, Any]) -> bool:
    """``exports`` 里**是否存在 ``require`` 条件分支**（含嵌套条件内部）。

    这是 ``ESM-CJS-MISMATCH`` 的**核心判据**（旧仓 ``data/README.md`` §5.2 第 2 条）——
    不是看 ``type`` 字段。``type: module`` 但有 require 分支的包（zod/date-fns/glob）
    必须判 RESOLVED。
    """
    return any(_contains_require(entry["value"]) for entry in index["entries"])


def _contains_require(value: Any) -> bool:
    if value is None or isinstance(value, str):
        return False
    if isinstance(value, list):
        return any(_contains_require(item) for item in value)
    if _is_object(value):
        for k, v in value.items():
            if k == "require":
                return True
            if _contains_require(v):
                return True
    return False


def _canonicalize(value: Any) -> str:
    """规范化序列化：对象键排序（同内容不同书写 → 同指纹）、数组保序、``null`` 保留为 ``null``。

    显式拼串，**跨机器逐字节一致**（旧仓 ``tools/gen-fingerprints.mjs --check`` 断言同构）。
    布尔按 JS 字面（``true``/``false``）；字符串用 JSON 转义（非 ASCII 不转义，与
    ``JSON.stringify`` 一致）。
    """
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonicalize(item) for item in value) + "]"
    if _is_object(value):
        keys = sorted(value.keys())
        return "{" + ",".join(
            "%s:%s" % (json.dumps(k, ensure_ascii=False), _canonicalize(value[k])) for k in keys
        ) + "}"
    return "null"


def fingerprint(exports_field: Any) -> str:
    """结构指纹 = ``exports`` 的**规范化序列化**后 sha256 前 12 位。

    ``ABSENT``（JS ``undefined``）按字符串 ``"<absent>"`` 序列化（旧仓同口径）。
    """
    canonical = _canonicalize("<absent>" if exports_field is ABSENT else exports_field)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def describe_exports(pkg_json: Mapping[str, Any]) -> Dict[str, Any]:
    """统一出口：一次拿到"这个包的 exports 结构"的全部事实（供快照与判定共用）。

    ``pkg_json`` 是输入层读出的依赖 ``package.json`` **值**；``exports`` 键缺失映射 ``ABSENT``。
    """
    if "exports" in pkg_json:
        field = pkg_json["exports"]
    else:
        field = ABSENT
    declared = is_declared(field)
    if not declared:
        return {
            "declared": False,
            "fingerprint": fingerprint(ABSENT),
            "hasRequireBranch": False,
            "exposesPackageJson": False,
            "parseState": "NOT_DECLARED",
            "index": {"entries": [], "unparseable": False, "ignored": []},
        }
    index = build_exports_index(field)
    pkg_json_subpath = match_subpath(index, "./package.json")
    exposes_package_json = pkg_json_subpath["kind"] != "none" and pkg_json_subpath["value"] is not None
    return {
        "declared": True,
        "fingerprint": fingerprint(field),
        "hasRequireBranch": has_require_branch(index),
        "exposesPackageJson": exposes_package_json,
        "parseState": UNPARSEABLE if index["unparseable"] else "OK",
        "index": index,
    }
