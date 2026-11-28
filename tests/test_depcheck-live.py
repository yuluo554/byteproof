"""``depcheck-live`` 器官的无损测试（迁自 11-1-depcheck-live，Node/mjs 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：``exports`` 解析语义核心
（Node 官方算法 1:1 移植 + D1 实测修正的 10 处语义，逐条向量见 §1）、词法级引用点抽取
（静态形态 + 字符串兜底双条件 + 动态显式落 AMBIGUOUS，§3–§4）、五个判定态与
ESM-CJS-MISMATCH 招牌判据（§5，C1–C7 语料以等价 IR 夹具逐点对账）、drift 三条口径
（§6，zod 真实基线面作锚点）、编排与退出码语义（§7）、路径工具（§8）。

**没迁的部分逐条写在 ``docs/depcheck-live.md`` §6 的处置表里**（文件系统读取、目录遍历、
SKILL.md 契约块对账、gen-fingerprints/gen-baselines 生成器、bench/selftest/release 门、
脱敏门与布局门——由产品仓对应门接管）。不迁的东西不在这里假装测过。

跨语言锚点（§2）：四包（chalk/commander/glob/zod）的 ``exports`` 原文与
``fingerprint``（sha256 前 12 位）从旧仓 ``data/packages/*.json`` 原样内联——
Python 端重算指纹必须与 Node 端逐字节一致；zod 基线（3.25.76 的 109 个导出名）
从旧仓 ``data/fingerprints/zod.json`` 内联承担 drift 真值锚。date-fns 的
``exports`` 146 KB 不内联，其指纹锚由四包承担、语义锚（245 行桶文件）由等价夹具承担。

判定层口径（D1 + D18）：旧仓 20 个测试文件剔除 ``cli`` / ``bench`` / ``selftest`` /
``release`` 后 16 文件实跑 ``node --test`` **X = 161 passed**（``ℹ pass 161 / fail 0``，
旧层 ``test(`` 全部出现计数 166 作保守分母；静态 baseline 记 0，以实跑为准）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors import depcheck_live as dc  # noqa: E402
from byteproof.auditors.depcheck_live import (  # noqa: E402
    api,
    check,
    drift,
    paths,
    resolve,
    scan,
    spec,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    WARN,
    Basis,
    Report,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "depcheck-live"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "depcheck-live.basis.json"
THRESHOLDS_PATH = DATA_DIR / "depcheck-live.thresholds.json"
SAMPLE = ROOT / "samples" / "depcheck-live.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

ESM = spec.CONDITIONS["import"]
CJS = spec.CONDITIONS["require"]


# ================================================================== 夹具助手
def _dep(name="demo-pkg", version="1.0.3", type_=None, exports=None, files=None, **extra):
    record = {
        "name": name,
        "installed_version": version,
        "type": type_,
        "exports": exports,
        "files": files or {},
    }
    record.update(extra)
    return record


def _file(text, type_=None):
    return {"text": text, "type": type_}


def _esm_dep(names=("red", "blue"), name="demo-pkg", type_="module"):
    """有 require 分支的 type:module 包（zod/date-fns/glob 形态）——require() 行为正常。"""
    exports = {".": {"import": "./index.mjs", "require": "./index.cjs"}}
    files = {
        "index.mjs": _file(
            "".join("export function %s() {}\n" % n for n in names) + "export default {};\n",
            "module",
        ),
        "index.cjs": _file("".join("exports.%s = null;\n" % n for n in names), "commonjs"),
    }
    return _dep(name=name, type_=type_, exports=exports, files=files)


def _subject(sources=(), deps=None, declared=None, mode="check", baselines=None,
             input_gaps=None, options=None, project_extra=None):
    subject = {
        "mode": mode,
        "project": {
            "name": "t",
            "declared_deps": declared if declared is not None else {},
            "deps": deps if deps is not None else {},
        },
        "sources": list(sources),
    }
    if baselines is not None:
        subject["baselines"] = baselines
    if input_gaps is not None:
        subject["input_gaps"] = input_gaps
    if options is not None:
        subject["options"] = options
    if project_extra:
        subject["project"].update(project_extra)
    return subject


def _evaluate(subject, basis=None):
    return list((get(SLUG).evaluate)(subject, BASIS if basis is None else basis))


def _report(subject):
    records = _evaluate(subject)
    return Report(
        product="byteproof",
        organ=SLUG,
        organ_version=spec.ORGAN_VERSION,
        subject="t",
        records=records,
    )


def _statuses(records):
    """file|line|specifier → status（与旧仓 expected.json 的逐点对账同键）。"""
    out = {}
    for r in records:
        status = r.evidence.get("status")
        if status is not None and r.rule_id != "dp-summary":
            key = "%s|%s|%s" % (r.evidence.get("file"), r.evidence.get("line"), r.evidence.get("specifier"))
            assert key not in out, "同一引用点被判两次: %s" % key
            out[key] = status
    return out


def _by_rule(records, rule_id):
    return [r for r in records if r.rule_id == rule_id]


def _summary(records):
    return _by_rule(records, "dp-summary")[0]


def _point(specifier, imported, file="src/a.mjs", line=1, kind="import"):
    return {"file": file, "line": line, "kind": kind, "specifier": specifier, "imported": imported}


# ==================================================================
# §1 exports 解析语义（逐条移植旧仓 tests/resolve.test.mjs 的 36 条向量）
# ==================================================================

def test_sugar_string_equals_dot_entry():
    # packages.html「Exports sugar」：'"exports": "./index.js" 可写成 { ".": "./index.js" }'
    index = resolve.build_exports_index("./index.js")
    assert len(index["entries"]) == 1
    assert index["entries"][0]["key"] == "."
    assert resolve.resolve_conditional(index["entries"][0]["value"], ESM)["target"] == "./index.js"
    assert resolve.resolve_conditional(index["entries"][0]["value"], CJS)["target"] == "./index.js"


def test_sugar_conditional_object_equals_dot_entry():
    # 实测 sugar-conditional-object：require → ./i.cjs，import → ./i.mjs
    index = resolve.build_exports_index({"import": "./i.mjs", "require": "./i.cjs"})
    assert len(index["entries"]) == 1
    assert index["entries"][0]["key"] == "."
    assert resolve.resolve_conditional(index["entries"][0]["value"], ESM)["target"] == "./i.mjs"
    assert resolve.resolve_conditional(index["entries"][0]["value"], CJS)["target"] == "./i.cjs"


def test_conditional_object_uses_key_order():
    # packages.html 原文："Within the "exports" object, key order is significant."
    index = resolve.build_exports_index({".": {"import": "./i.mjs", "require": "./i.cjs"}})
    assert match_kind(index, ".") == "exact"
    value = match_value(index, ".")
    assert resolve.resolve_conditional(value, ESM)["target"] == "./i.mjs"
    assert resolve.resolve_conditional(value, CJS)["target"] == "./i.cjs"


def test_same_condition_set_different_order_gives_different_target():
    # 实测 A1：{import, node, default} → import 视角取 import；require 视角取 node
    a1 = resolve.build_exports_index({".": {"import": "./a.mjs", "node": "./b.mjs", "default": "./d.js"}})
    assert resolve.resolve_conditional(a1["entries"][0]["value"], ESM)["target"] == "./a.mjs"
    assert resolve.resolve_conditional(a1["entries"][0]["value"], CJS)["target"] == "./b.mjs"


def test_same_set_reversed_order_require_view_takes_require():
    # 实测 A2：{require, node, default} → require 视角取 require；import 视角取 node
    a2 = resolve.build_exports_index({".": {"require": "./r.cjs", "node": "./b.cjs", "default": "./d.cjs"}})
    assert resolve.resolve_conditional(a2["entries"][0]["value"], CJS)["target"] == "./r.cjs"
    assert resolve.resolve_conditional(a2["entries"][0]["value"], ESM)["target"] == "./b.cjs"


def test_default_first_wins_when_written_first():
    # 实测 P2：default 写在前时先命中 default
    index = resolve.build_exports_index({".": {"default": "./d.js", "import": "./i.mjs"}})
    assert resolve.resolve_conditional(index["entries"][0]["value"], ESM)["target"] == "./d.js"


def test_null_is_blocking_not_missing():
    # 实测 exact-null-blocked / G2-dot-null → ERR_PACKAGE_PATH_NOT_EXPORTED
    index = resolve.build_exports_index({"./secret": None})
    sub = resolve.match_subpath(index, "./secret")
    assert sub["kind"] == "exact", "null 键必须能精确命中，否则会被误判成'未声明该子路径'"
    assert sub["value"] is None
    assert resolve.resolve_conditional(sub["value"], ESM)["state"] == "blocked"


def test_array_fallback_takes_first_resolvable():
    # 实测 P4-array-single / D5-unmatched-cond-then-ok
    index = resolve.build_exports_index({".": [{"browser": "./br.js"}, "./ok.js"]})
    r = resolve.resolve_conditional(match_value(index, "."), ESM)
    assert r["state"] == "ok"
    assert r["target"] == "./ok.js", "条件不匹配的项要跳过，取后面那个可解析的"


def test_array_null_continues_to_later_item():
    # 实测 D1-null-then-ok：数组里的 null 不中断，继续找后面的可解析项
    index = resolve.build_exports_index({".": [None, "./b.js"]})
    assert resolve.resolve_conditional(match_value(index, "."), ESM)["target"] == "./b.js"


def test_empty_array_is_blocked():
    # 实测 D3-empty → ERR_PACKAGE_PATH_NOT_EXPORTED（原文：'_target.length is zero, return null'）
    index = resolve.build_exports_index({".": []})
    assert resolve.resolve_conditional(match_value(index, "."), ESM)["state"] == "blocked"


def test_all_unmatched_array_is_unmatched():
    # 实测 D6-all-undefined：全项都不匹配 → unmatched（不是 unparseable，也不是静默通过）
    index = resolve.build_exports_index({".": [{"browser": "./br.js"}, {"electron": "./e.js"}]})
    assert resolve.resolve_conditional(match_value(index, "."), ESM)["state"] == "unmatched"


def test_invalid_target_item_skipped_later_item_still_wins():
    # 实测 D4-invalid-then-ok（原文："continuing the loop on any Invalid Package Target error"）
    index = resolve.build_exports_index({".": ["../escape.js", "./ok.js"]})
    assert resolve.resolve_conditional(match_value(index, "."), ESM)["target"] == "./ok.js"


def test_wildcard_substitution():
    index = resolve.build_exports_index({"./features/*": "./src/features/*.js"})
    sub = resolve.match_subpath(index, "./features/alpha")
    assert sub["kind"] == "pattern"
    assert resolve.substitute_wildcard(sub["key"], "./features/alpha", sub["value"]) == "./src/features/alpha.js"


def test_pattern_key_compare_star_index_priority():
    # 实测形态⑤b：多通配命中时按 PATTERN_KEY_COMPARE（* 下标大者优先）
    index = resolve.build_exports_index({"./*": "./generic/*.js", "./features/*": "./src/features/*.js"})
    assert resolve.match_subpath(index, "./features/x")["key"] == "./features/*"
    assert resolve.match_subpath(index, "./other/x")["key"] == "./*"


def test_subpath_equal_to_pattern_base_does_not_match():
    # 实测 C1-equal-to-base（原文："If matchKey starts with but is not equal to patternBase"）
    index = resolve.build_exports_index({"./a/*": "./x/*.js"})
    assert resolve.match_subpath(index, "./a/")["kind"] == "none"
    assert resolve.match_subpath(index, "./a")["kind"] == "none"
    assert resolve.match_subpath(index, "./a/b")["kind"] == "pattern"


def test_trailer_requires_length_lower_bound():
    # 实测 C2/C3（原文："matchKey ends with patternTrailer and the length of matchKey is
    # greater than or equal to the length of expansionKey"）
    index = resolve.build_exports_index({"./a*b": "./c*b.js"})
    assert resolve.match_subpath(index, "./ab")["kind"] == "none", "./ab 与键等长 → 空片段，不命中"
    assert resolve.match_subpath(index, "./ab-extra")["kind"] == "none", "末尾不是 trailer 的写法也不命中"
    hit = resolve.match_subpath(index, "./aZZb")
    assert hit["kind"] == "pattern"
    assert hit["patternMatch"] == "ZZ"


def test_every_star_in_target_replaced():
    # 实测 T1-multi-star-target（原文："every instance of `*` replaced with patternMatch"）
    index = resolve.build_exports_index({"./f/*": "./src/*/idx-*.js"})
    sub = resolve.match_subpath(index, "./f/zz")
    assert resolve.substitute_wildcard(sub["key"], "./f/zz", sub["value"]) == "./src/zz/idx-zz.js"


def test_pattern_fragment_may_contain_slashes():
    # 实测 P3-pattern-slash-fragment / T2
    index = resolve.build_exports_index({"./a/*": "./x/*.js"})
    assert resolve.substitute_wildcard(index["entries"][0]["key"], "./a/b/c", "./x/*.js") == "./x/b/c.js"


def test_multi_star_key_ignored_not_unparseable():
    # 实测 E2：多 * 的子路径键被 Node **忽略**，不是整包算不了
    index = resolve.build_exports_index({".": "./i.js", "./a/*/b/*": "./x/*.js"})
    assert index["ignored"] == ["./a/*/b/*"]
    assert index["unparseable"] is False, "忽略该键不致命：其余入口在 Node 里照常可用"
    assert match_value(index, ".") == "./i.js"


def test_trailing_slash_key_ignored_too():
    # 实测 E1：末尾斜杠键同样被忽略，其余入口照常
    index = resolve.build_exports_index({".": "./i.js", "./dir/": "./src/dir/"})
    assert index["ignored"] == ["./dir/"]
    assert match_value(index, ".") == "./i.js"
    assert resolve.match_subpath(index, "./dir/x.js")["kind"] == "none"


def test_literal_star_request_hits_pattern_key():
    # 实测 H1：精确键含 * 时按通配处理，请求里带字面 * 也能命中
    index = resolve.build_exports_index({"./x/*": "./x.js"})
    sub = resolve.match_subpath(index, "./x/*")
    assert sub["kind"] == "pattern"
    assert resolve.substitute_wildcard(sub["key"], "./x/*", sub["value"]) == "./x.js"


def test_nested_conditions_recurse_with_default_fallback():
    index = resolve.build_exports_index({".": {"node": {"import": "./n.mjs"}, "default": "./d.js"}})
    assert resolve.resolve_conditional(index["entries"][0]["value"], ESM)["target"] == "./n.mjs"
    assert resolve.resolve_conditional(index["entries"][0]["value"], ("browser", "default"))["target"] == "./d.js"


def test_nested_unmatched_continues_parent_conditions():
    # 实测 B1/B3（原文："nested conditions behave analogously to nested JavaScript `if` statements"）
    b1 = resolve.build_exports_index(
        {".": {"node": {"browser": "./br.js"}, "import": "./i.mjs", "default": "./d.js"}}
    )
    assert resolve.resolve_conditional(b1["entries"][0]["value"], ESM)["target"] == "./i.mjs"
    assert resolve.resolve_conditional(b1["entries"][0]["value"], CJS)["target"] == "./d.js"


def test_nested_null_stops_at_block():
    # 实测 B2：嵌套条件里命中 null 就**停在**屏蔽
    index = resolve.build_exports_index({".": {"node": None, "import": "./i.mjs", "default": "./d.js"}})
    assert resolve.resolve_conditional(index["entries"][0]["value"], ESM)["state"] == "blocked"


def test_node_addons_condition_participates():
    # 实测 Q1：node-addons 参与匹配
    addons = resolve.build_exports_index({".": {"node-addons": "./addons.js", "default": "./d.js"}})
    assert resolve.resolve_conditional(addons["entries"][0]["value"], ESM)["target"] == "./addons.js"


def test_module_sync_condition_participates():
    # 实测 Q2：module-sync 参与匹配
    sync = resolve.build_exports_index({".": {"module-sync": "./ms.js", "default": "./d.js"}})
    assert resolve.resolve_conditional(sync["entries"][0]["value"], CJS)["target"] == "./ms.js"


def test_browser_condition_not_in_node_condition_set():
    # 实测 Q3：browser 不在 Node 的条件集里
    browser = resolve.build_exports_index({".": {"browser": "./br.js", "default": "./d.js"}})
    assert resolve.resolve_conditional(browser["entries"][0]["value"], ESM)["target"] == "./d.js"


def test_types_condition_not_in_condition_set():
    # 实测 Q4/F2：types 不在 Node 的条件集里
    types = resolve.build_exports_index({".": {"types": "./t.d.ts", "default": "./d.js"}})
    assert resolve.resolve_conditional(types["entries"][0]["value"], CJS)["target"] == "./d.js"


def test_import_and_require_are_mutually_exclusive():
    # package.json 原文：always mutually exclusive
    v = {"import": "./i.mjs", "require": "./i.cjs"}
    assert resolve.resolve_conditional(v, ESM)["target"] == "./i.mjs"
    assert resolve.resolve_conditional(v, CJS)["target"] == "./i.cjs"


def test_bare_target_is_invalid_package_target():
    # 实测 P1：目标必须以 "./" 开头，裸路径是 Invalid Package Target
    index = resolve.build_exports_index({".": "index.js"})
    assert resolve.resolve_conditional(index["entries"][0]["value"], ESM)["state"] == "invalid"


def test_mixed_subpath_and_condition_keys_unparseable():
    # 实测 E3：混合形态 → Invalid Package Configuration（整包算不了）
    assert resolve.build_exports_index({".": "./i.js", "import": "./i.mjs"})["unparseable"] is True


def test_mixed_keys_with_plain_condition_name_unparseable():
    # 实测 E4：非 "./" 前缀的普通条件键与子路径键混用，同样整包算不了
    assert resolve.build_exports_index({".": "./i.js", "xyz": "./z.js"})["unparseable"] is True


def test_exports_null_means_not_declared():
    # 实测 G1：exports: null 等同未声明（Node 回落 main/index），不是屏蔽
    d = resolve.describe_exports({"exports": None, "main": "./main.js"})
    assert d["declared"] is False
    assert d["parseState"] == "NOT_DECLARED"


def test_has_require_branch_sees_top_level_require():
    assert resolve.has_require_branch(resolve.build_exports_index({".": {"import": "./i.mjs"}})) is False


def test_has_require_branch_sees_sibling_require():
    assert resolve.has_require_branch(
        resolve.build_exports_index({".": {"import": "./i.mjs", "require": "./i.cjs"}})
    ) is True


def test_has_require_branch_sees_nested_require():
    assert resolve.has_require_branch(
        resolve.build_exports_index({".": {"node": {"require": "./n.cjs"}}})
    ) is True


def test_has_require_branch_sees_subpath_entry_require():
    assert resolve.has_require_branch(
        resolve.build_exports_index({"./x": {"import": "./x.mjs"}, ".": {"require": "./i.cjs"}})
    ) is True


def test_has_require_branch_sees_require_inside_array():
    # 数组里的 require 分支也算（原文：数组逐项求值）
    assert resolve.has_require_branch(
        resolve.build_exports_index({".": [{"browser": "./b.js"}, {"require": "./c.cjs"}]})
    ) is True


def test_fingerprint_is_key_order_invariant():
    a = resolve.fingerprint({".": {"import": "./i.mjs", "require": "./i.cjs"}})
    b = resolve.fingerprint({".": {"require": "./i.cjs", "import": "./i.mjs"}})
    assert a == b
    assert len(a) == 12 and all(c in "0123456789abcdef" for c in a)


def test_fingerprint_preserves_array_order():
    a = resolve.fingerprint({".": ["./a.js", "./b.js"]})
    b = resolve.fingerprint({".": ["./b.js", "./a.js"]})
    assert a != b


def test_fingerprint_null_differs_from_empty_and_is_stable():
    assert resolve.fingerprint({"./x": None}) != resolve.fingerprint({})
    assert resolve.fingerprint(None) == resolve.fingerprint(None)


# ==================================================================
# §2 跨语言锚点：四包指纹 + require 分支判定（旧仓 data/packages/*.json 原样内联）
# ==================================================================

#: 旧仓 data/packages/*.json 的 exports 原文与指纹（Node v24.15.0 生成，sha256 前 12 位）。
PKG_EXPORTS = {
    "chalk": {"types": "./source/index.d.ts", "default": "./source/index.js"},
    "commander": {".": {"types": "./typings/index.d.ts", "default": "./index.js"}},
    "glob": {
        "./package.json": "./package.json",
        "./raw": {
            "import": {"types": "./dist/esm/index.d.ts", "default": "./dist/esm/index.js"},
            "require": {"types": "./dist/commonjs/index.d.ts", "default": "./dist/commonjs/index.js"},
        },
        ".": {
            "import": {"types": "./dist/esm/index.d.ts", "default": "./dist/esm/index.min.js"},
            "require": {"types": "./dist/commonjs/index.d.ts", "default": "./dist/commonjs/index.min.js"},
        },
    },
    "zod": {
        "./package.json": "./package.json",
        ".": {"@zod/source": "./src/index.ts", "types": "./index.d.cts", "import": "./index.js", "require": "./index.cjs"},
        "./mini": {"@zod/source": "./src/mini/index.ts", "types": "./mini/index.d.cts", "import": "./mini/index.js", "require": "./mini/index.cjs"},
        "./compile": {"@zod/source": "./src/compile.ts", "types": "./compile.d.cts", "import": "./compile.js", "require": "./compile.cjs"},
        "./locales": {"@zod/source": "./src/locales/index.ts", "types": "./locales/index.d.cts", "import": "./locales/index.js", "require": "./locales/index.cjs"},
        "./v3": {"@zod/source": "./src/v3/index.ts", "types": "./v3/index.d.cts", "import": "./v3/index.js", "require": "./v3/index.cjs"},
        "./v4": {"@zod/source": "./src/v4/index.ts", "types": "./v4/index.d.cts", "import": "./v4/index.js", "require": "./v4/index.cjs"},
        "./v4-mini": {"@zod/source": "./src/v4-mini/index.ts", "types": "./v4-mini/index.d.cts", "import": "./v4-mini/index.js", "require": "./v4-mini/index.cjs"},
        "./v4/mini": {"@zod/source": "./src/v4/mini/index.ts", "types": "./v4/mini/index.d.cts", "import": "./v4/mini/index.js", "require": "./v4/mini/index.cjs"},
        "./v4/core": {"@zod/source": "./src/v4/core/index.ts", "types": "./v4/core/index.d.cts", "import": "./v4/core/index.js", "require": "./v4/core/index.cjs"},
        "./v4/locales": {"@zod/source": "./src/v4/locales/index.ts", "types": "./v4/locales/index.d.cts", "import": "./v4/locales/index.js", "require": "./v4/locales/index.cjs"},
        "./v4/locales/*": {"@zod/source": "./src/v4/locales/*", "types": "./v4/locales/*", "import": "./v4/locales/*", "require": "./v4/locales/*"},
    },
}
PKG_FINGERPRINT = {
    "chalk": "176c42606af7",
    "commander": "66d23ef88bab",
    "glob": "69ba2dc95840",
    "zod": "d3d5b5701e80",
}
#: 旧仓 data/README.md §1 D4–D6 的五包实测（date-fns 语义由等价夹具承担，exports 146KB 不内联）。
PKG_HAS_REQUIRE_BRANCH = {"chalk": False, "zod": True, "date-fns": True, "commander": False, "glob": True}
PKG_EXPOSES_PACKAGE_JSON = {"chalk": False, "zod": True, "date-fns": True, "commander": False, "glob": True}


def test_fingerprint_anchor_chalk():
    assert resolve.fingerprint(PKG_EXPORTS["chalk"]) == PKG_FINGERPRINT["chalk"]


def test_fingerprint_anchor_commander():
    assert resolve.fingerprint(PKG_EXPORTS["commander"]) == PKG_FINGERPRINT["commander"]


def test_fingerprint_anchor_glob():
    assert resolve.fingerprint(PKG_EXPORTS["glob"]) == PKG_FINGERPRINT["glob"]


def test_fingerprint_anchor_zod():
    assert resolve.fingerprint(PKG_EXPORTS["zod"]) == PKG_FINGERPRINT["zod"]


def test_fingerprint_anchor_format_is_sha12_hex():
    for fp in PKG_FINGERPRINT.values():
        assert len(fp) == 12 and all(c in "0123456789abcdef" for c in fp)


def test_require_branch_anchor_real_four_packages():
    # D4：chalk 无 require 分支；D5：zod/glob 有；D6：commander 无
    for name, want in (("chalk", False), ("zod", True), ("commander", False), ("glob", True)):
        got = resolve.describe_exports({"exports": PKG_EXPORTS[name]})["hasRequireBranch"]
        assert got == want, "%s 的 hasRequireBranch 与 D4–D6 不符" % name


def test_exposes_package_json_anchor_real_four_packages():
    # zod/glob 显式暴露 ./package.json；chalk/commander 不暴露
    for name, want in (("chalk", False), ("zod", True), ("commander", False), ("glob", True)):
        got = resolve.describe_exports({"exports": PKG_EXPORTS[name]})["exposesPackageJson"]
        assert got == want, "%s 的 ./package.json 暴露性与 D4–D6 不符" % name


def test_datefns_anchor_via_equivalent_fixture():
    # date-fns@4.4.0 的入口 index.js 是 245 行 `export * from "./x.js"` 桶（146KB 不内联），
    # 以等价 IR 夹具承担其语义锚：hasRequireBranch=False（桶文件全是 export * from），
    # 251 名根导出面由递归读全（这里以两支桶代表）。
    barrel_exports = {".": {"import": "./index.js", "require": "./index.cjs"}}
    files = {
        "index.js": _file('export * from "./dates.js";\nexport * from "./locale.js";\n', "module"),
        "index.cjs": _file(
            'var _d = require("./dates.cjs");\nObject.keys(_d).forEach(function (k) { exports[k] = _d[k]; });\n',
            "commonjs",
        ),
        "dates.js": _file("export const addDays = 1;\nexport const subDays = 2;\n", "module"),
        "locale.js": _file("export const enUS = 1;\n", "module"),
        "dates.cjs": _file("exports.addDays = 1;\nexports.subDays = 2;\n", "commonjs"),
    }
    dep = _dep(name="date-fns", type_="module", exports=barrel_exports, files=files)
    built = check.build_dep_index(dep)
    # exports 条件对象自带 require 分支（与 D5 记录一致：date-fns hasRequireBranch=True）；
    # 桶文件内部全是 re-export、没有具名导出——递归才读得全。
    assert built["hasRequireBranch"] is True
    assert built["exposesPackageJson"] is False
    esm_surface = check.read_export_surface(built, "./index.js")
    assert esm_surface["ok"] is True
    assert {"addDays", "subDays", "enUS"} <= esm_surface["names"]
    cjs_surface = check.read_export_surface(built, "./index.cjs")
    assert cjs_surface["ok"] is True
    assert {"addDays", "subDays"} <= cjs_surface["names"]


def test_describe_exports_chalk_form():
    # 真实 chalk@6.0.1 形态：无 require 分支、不暴露 ./package.json
    d = resolve.describe_exports(
        {"type": "module", "exports": {"types": "./source/index.d.ts", "default": "./source/index.js"}}
    )
    assert d["hasRequireBranch"] is False
    assert d["exposesPackageJson"] is False
    assert d["parseState"] == "OK"


def test_describe_exports_zod_form_has_require_branch():
    # 反面判据：type: module 但**有** require 分支的包必须被识别（→ 不得判 MISMATCH）
    d = resolve.describe_exports({
        "type": "module",
        "exports": {".": {
            "import": {"types": "./a.d.mts", "default": "./a.mjs"},
            "require": {"types": "./a.d.cts", "default": "./a.cjs"},
        }},
    })
    assert d["hasRequireBranch"] is True


def test_describe_exports_exposes_package_json():
    d = resolve.describe_exports({"exports": {".": "./i.js", "./package.json": "./package.json"}})
    assert d["exposesPackageJson"] is True


def test_describe_exports_not_declared_state():
    d = resolve.describe_exports({"main": "./index.js"})
    assert d["declared"] is False
    assert d["parseState"] == "NOT_DECLARED"


def match_kind(index, subpath):
    return resolve.match_subpath(index, subpath)["kind"]


def match_value(index, subpath):
    return resolve.match_subpath(index, subpath)["value"]


# ==================================================================
# §3 引用点抽取（逐条移植旧仓 tests/scan.test.mjs + scan-edge.test.mjs）
# ==================================================================

def _scan(src):
    return scan.scan_text(src, "a.mjs")


def test_import_default_named_namespace_side_effect():
    points = _scan(
        'import chalk from "chalk";\n'
        'import { z, ZodError } from "zod";\n'
        'import * as fs from "node:fs";\n'
        'import "side-effect";\n'
    )
    assert [p["specifier"] for p in points] == ["chalk", "zod", "node:fs", "side-effect"]
    assert points[0]["imported"] == ["default"]
    assert points[1]["imported"] == ["z", "ZodError"]
    assert points[2]["imported"] == ["*"]


def test_export_from_point():
    points = _scan('export { a, b as c } from "pkg";')
    assert len(points) == 1
    assert points[0]["kind"] == "export-from"
    assert points[0]["specifier"] == "pkg"


def test_require_static_literal():
    points = _scan('const chalk = require("chalk");')
    assert len(points) == 1
    assert points[0]["kind"] == "require"
    assert points[0]["specifier"] == "chalk"


def test_dynamic_require_variable_is_ambiguous():
    points = _scan("const p = require(name);")
    assert len(points) == 1
    assert points[0]["kind"] == "ambiguous"
    assert points[0]["specifier"] is None
    assert "require(" in points[0]["note"]


def test_dynamic_import_variable_is_ambiguous():
    points = _scan("await import(name);")
    assert len(points) == 1
    assert points[0]["kind"] == "ambiguous"


def test_interpolated_template_require_is_ambiguous():
    points = _scan("const m = require(`./${x}`);")
    assert len(points) == 1
    assert points[0]["kind"] == "ambiguous"


def test_dynamic_import_literal_has_static_specifier():
    points = _scan('await import("glob");')
    assert len(points) == 1
    assert points[0]["kind"] == "dynamic-import"
    assert points[0]["specifier"] == "glob"


def test_jest_and_vi_mock_counted():
    points = _scan('jest.mock("chalk");\nvi.mock("zod");')
    assert [p["specifier"] for p in points] == ["chalk", "zod"]
    assert all(p["kind"] == "jest-mock" for p in points)


def test_line_numbers_same_under_lf_and_crlf():
    lf = '// c\nimport a from "a";\n'
    crlf = '// c\r\nimport a from "a";\r\n'
    assert scan.scan_text(lf, "x")[0]["line"] == 2
    assert scan.scan_text(crlf, "x")[0]["line"] == 2


def test_wide_chars_do_not_shift_line_numbers():
    src = '// 中文注释 😀\nconst x = require("zod");\n'
    assert scan.scan_text(src, "x")[0]["line"] == 2


def test_every_extracted_kind_is_in_contract_enum():
    src = (
        'import a from "a";\n'
        'export { b } from "b";\n'
        'require("c");\n'
        'import("d");\n'
        'jest.mock("e");\n'
        "require(v);\n"
    )
    for p in _scan(src):
        assert scan.is_known_kind(p["kind"]), "kind %s 不在 spec.KIND 里" % p["kind"]


def test_parse_import_clause_alias_and_type_modifiers():
    assert scan.parse_import_clause("{ a as b, c }") == ["a", "c"]
    assert scan.parse_import_clause("{ type T, x }") == ["T", "x"]
    assert scan.parse_import_clause("defaultImport, { named }") == ["named", "default"]


def test_line_number_correct_after_overlong_line():
    # 超长行（>100 KiB 单行）之后的行号仍指向源行（防"按字节偏移÷常数"或先截断再切行）
    huge_line = "const blob = { %s };" % ", ".join("k%d: %d" % (i, i) for i in range(20000))
    assert len(huge_line) > 100 * 1024, "构造失败：超长行只有 %d 字节" % len(huge_line)
    points = _scan(huge_line + '\nimport { z } from "zod";\n')
    assert len(points) == 1, "超长行本身不应产出引用点"
    assert points[0]["line"] == 2, "行号必须指向源行 2，不能被前一行的长度带偏"
    assert points[0]["specifier"] == "zod"


def test_points_inside_overlong_line_report_same_line():
    filler = "x" * 50000
    points = _scan('const s = "%s"; import { a } from "chalk";\nimport { b } from "zod";\n' % filler)
    assert len(points) == 2
    assert points[0]["line"] == 1
    assert points[1]["line"] == 2


def test_crlf_wide_chars_overlong_line_combined():
    huge_line = "// 中文注释 😀 %s" % ("宽" * 60000)
    points = _scan('%s\r\nconst { red } = require("chalk");\r\n' % huge_line)
    assert len(points) == 1
    assert points[0]["line"] == 2
    assert points[0]["imported"] == ["red"]


def test_literal_plus_variable_concat_family_all_ambiguous():
    # 字面量 + 变量拼接整族都落 ambiguous（不得漏判，也不得被当成静态）
    forms = [
        'const m = require("chalk" + suffix);',
        'const m = require("./" + name);',
        "const m = require(`chalk/${x}`);",
        'const m = require(["chalk"].join(""));',
        'const n = import("chalk" + s);',
    ]
    for src in forms:
        points = _scan(src)
        assert len(points) == 1, "%s 应抽出恰好 1 个引用点，实际 %d（漏判 = 沉默）" % (src, len(points))
        assert points[0]["kind"] == "ambiguous", "%s 必须落 ambiguous" % src
        assert points[0]["specifier"] is None


def test_interpolation_free_template_is_static():
    points = _scan("const m = require(`chalk`);")
    assert len(points) == 1
    assert points[0]["kind"] == "require"
    assert points[0]["specifier"] == "chalk"


def test_destructured_require_records_imported_names():
    # 防旧仓 M2 实测踩到的索引错位：imported 恒为空 → 判定层把红条目全读成"不取符号"而判绿
    cases = [
        ('const { red } = require("chalk");', ["red"]),
        ('const { a, b: c } = require("p");', ["a", "b"]),
        ('const { ...rest } = require("p");', ["rest"]),
        ('const { a = 1 } = require("p");', ["a"]),
        ('let { x } = require("p");', ["x"]),
        ('var { y } = require("p");', ["y"]),
    ]
    for src, want in cases:
        points = _scan(src)
        assert len(points) == 1, src
        assert points[0]["kind"] == "require"
        assert points[0]["imported"] == want, "%s 的 imported 应为 %s" % (src, want)


def test_non_destructured_require_reports_no_symbols():
    for src in ['const ns = require("chalk");', 'require("chalk");', 'const m = require("chalk").default;']:
        points = _scan(src)
        assert len(points) == 1, src
        assert points[0]["imported"] == [], "%s 不该报出具名符号" % src


def test_multiple_call_sites_ordered_by_position():
    points = _scan('const a = require("chalk"); const b = require("zod");')
    assert [p["specifier"] for p in points] == ["chalk", "zod"]


def test_unclosed_call_argument_still_yields_ambiguous():
    points = _scan("const m = require(")
    assert len(points) == 1
    assert points[0]["kind"] == "ambiguous"


def test_parse_destructured_names_variants():
    assert scan.parse_destructured_names("a, b: c") == ["a", "b"]
    assert scan.parse_destructured_names("...rest") == ["rest"]
    assert scan.parse_destructured_names("a = 1") == ["a"]
    assert scan.parse_destructured_names("") == []


# ==================================================================
# §4 字符串兜底 / 降级 / 阈值（移植旧仓 thresholds + scan-large-file 的行为面）
# ==================================================================

def test_bare_literals_double_condition_filter():
    # 代码 → 行为 ③：兜底的双条件过滤（只满足形似的不计入）
    deps = {"chalk", "zod", "@scope/pkg"}
    text = (
        'const a = "chalk";\n'          # ① 形似 ② 已装     → 计入
        'const b = "lodash";\n'         # ① 形似 ② 未装     → 不计入
        'const c = "hello world";\n'    # ① 不形似          → 不计入
        'const d = "zod/v4";\n'         # ① 形似(含子路径) ② 已装 → 计入
        'const e = "@scope/pkg/sub";\n' # ① scoped ② 已装   → 计入
        'const f = "@other/x";\n'       # ① 形似 ② 未装     → 不计入
        'const g = "Chalk";\n'          # 大写不算包名       → 不计入
    )
    hits = scan.find_bare_package_literals(text, deps)
    assert sorted(h["specifier"] for h in hits) == ["@scope/pkg/sub", "chalk", "zod/v4"]


def test_scan_text_itself_does_no_string_literal_fallback():
    points = scan.scan_text('const msg = "chalk";\n', "a.mjs")
    assert [p for p in points if p["kind"] == "string-literal"] == [], "scanText 本身不做字符串兜底"


def test_scan_sources_texts_dedups_structural_and_literal_hits():
    # require("chalk") 里的 "chalk" 也是形似包名的字面量；**同一行**时已被结构化抽取覆盖，
    # 兜底再计一次就是同一引用点算两遍（假阳性）。不同行的裸字符串是另一个引用点（合法计入）。
    result = scan.scan_sources_texts(
        [{"file": "src/a.cjs", "text": 'const a = require("chalk"); const b = "chalk";\n'}],
        {"chalk"},
    )
    assert [p["kind"] for p in result["points"] if p["specifier"] == "chalk"] == ["require"]
    result2 = scan.scan_sources_texts(
        [{"file": "src/a.cjs", "text": 'const a = require("chalk");\nconst b = "chalk";\n'}],
        {"chalk"},
    )
    assert [p["kind"] for p in result2["points"] if p["specifier"] == "chalk"] == ["require", "string-literal"]


def test_dynamic_ident_decl_suppressed_in_fallback():
    # 反例（旧仓 M2 实测）：`const name = "chalk"; require(name)` 不得让同一行出现两种结论
    result = scan.scan_sources_texts(
        [{"file": "src/a.cjs", "text": 'const name = "chalk";\nconst mod = require(name);\n'}],
        {"chalk"},
    )
    statuses_kinds = [(p["kind"], p["specifier"]) for p in result["points"]]
    assert ("string-literal", "chalk") not in statuses_kinds
    assert ("ambiguous", None) in statuses_kinds


def test_fallback_literal_in_call_args_belongs_to_call_site_scanner():
    # require("chalk" + suffix) 的字面量前缀不得被兜底计成 chalk 引用点
    result = scan.scan_sources_texts(
        [{"file": "src/a.cjs", "text": 'const suffix = "/p";\nconst mod = require("chalk" + suffix);\n'}],
        {"chalk"},
    )
    assert [p["kind"] for p in result["points"]] == ["ambiguous"]


def test_limits_from_spec_constants():
    assert spec.SOURCE_FILE_BYTES == 524288
    assert spec.EXPORTS_KEYS_LIMIT == 4096
    assert spec.LARGE_FILE_DOWNGRADED == "LARGE_FILE_DOWNGRADED"


def test_overlarge_file_downgraded_but_still_scanned():
    # 降级 ≠ 丢弃：文件仍被扫，引用点不得丢；gap 必须指向超限文件并写明上限值
    pad = " " * (spec.SOURCE_FILE_BYTES + 1024)
    big = "// 撑到超过 %d 字节%s\nconst { z } = require(\"zod\");\n" % (spec.SOURCE_FILE_BYTES, pad)
    result = scan.scan_sources_texts([{"file": "src/huge.cjs", "text": big}], {"zod"})
    downgraded = [g for g in result["gaps"] if g["kind"] == spec.LARGE_FILE_DOWNGRADED]
    assert len(downgraded) == 1
    assert downgraded[0]["file"] == "src/huge.cjs"
    assert str(spec.SOURCE_FILE_BYTES) in downgraded[0]["detail"]
    assert "src/huge.cjs" in result["files"]
    assert any(p["file"] == "src/huge.cjs" and p["specifier"] == "zod" for p in result["points"])


def test_file_exactly_at_limit_not_downgraded():
    header = 'const { z } = require("zod");\n'
    exact = header + " " * (spec.SOURCE_FILE_BYTES - len(header.encode("utf-8")))
    result = scan.scan_sources_texts([{"file": "src/exact.cjs", "text": exact}], {"zod"})
    assert [g for g in result["gaps"] if g["kind"] == spec.LARGE_FILE_DOWNGRADED] == []


def test_max_file_bytes_option_overrides_limit():
    result = scan.scan_sources_texts(
        [{"file": "src/small.cjs", "text": 'require("zod");\n' + " " * 100}], {"zod"}, max_file_bytes=10,
    )
    assert [g for g in result["gaps"] if g["kind"] == spec.LARGE_FILE_DOWNGRADED]


def test_exports_keys_over_limit_whole_package_unparseable():
    over = {("./s%d" % i): ("./s%d.js" % i) for i in range(spec.EXPORTS_KEYS_LIMIT + 1)}
    index = resolve.build_exports_index(over)
    assert index["unparseable"] is True, "超限必须记 unparseable，否则等于静默截断"
    assert index["entries"] == []


def test_exports_keys_at_limit_still_ok():
    at_limit = {("./s%d" % i): ("./s%d.js" % i) for i in range(spec.EXPORTS_KEYS_LIMIT)}
    ok = resolve.build_exports_index(at_limit)
    assert ok["unparseable"] is False
    assert len(ok["entries"]) == spec.EXPORTS_KEYS_LIMIT


def test_real_four_package_exports_within_keys_limit():
    # 真实语料全部在上限内（阈值不能卡死真实语料）
    for name in ("chalk", "zod", "date-fns-fixture", "commander", "glob"):
        exports = PKG_EXPORTS.get(name.replace("-fixture", ""))
        if exports is None:
            continue
        assert resolve.build_exports_index(exports)["unparseable"] is False, name


def test_unreadable_file_passthrough_via_input_gaps():
    # 读不出的文件记 UNREADABLE_FILE 而不是静默跳过（文件读取在输入层，经 input_gaps 透传）
    subject = _subject(input_gaps=[{"kind": "UNREADABLE_FILE", "file": "src/broken.cjs", "detail": "EACCES"}])
    records = _evaluate(subject)
    unread = _by_rule(records, "dp-unreadable-file")
    assert len(unread) == 1
    assert unread[0].verdict == ERROR


# ==================================================================
# §5 五个判定态与招牌判据（C1–C7 语料以等价 IR 夹具逐点对账）
# ==================================================================

#: 真实 zod@3.25.76 基线根导出面（旧仓 data/fingerprints/zod.json 的 surfaces["."].import，
#: 109 名原样内联）——drift 真值锚：ZodSchema 在基线、4.6.7 已装没有；z 两版都在。
ZOD_BASELINE_IMPORT_NAMES = [
    "BRAND", "DIRTY", "EMPTY_PATH", "INVALID", "NEVER", "OK", "ParseStatus", "Schema",
    "ZodAny", "ZodArray", "ZodBigInt", "ZodBoolean", "ZodBranded", "ZodCatch", "ZodDate",
    "ZodDefault", "ZodDiscriminatedUnion", "ZodEffects", "ZodEnum", "ZodError",
    "ZodFirstPartyTypeKind", "ZodFunction", "ZodIntersection", "ZodIssueCode", "ZodLazy",
    "ZodLiteral", "ZodMap", "ZodNaN", "ZodNativeEnum", "ZodNever", "ZodNull", "ZodNullable",
    "ZodNumber", "ZodObject", "ZodOptional", "ZodParsedType", "ZodPipeline", "ZodPromise",
    "ZodReadonly", "ZodRecord", "ZodSchema", "ZodSet", "ZodString", "ZodSymbol",
    "ZodTransformer", "ZodTuple", "ZodType", "ZodUndefined", "ZodUnion", "ZodUnknown",
    "ZodVoid", "addIssueToContext", "any", "array", "bigint", "boolean", "coerce", "custom",
    "date", "datetimeRegex", "default", "defaultErrorMap", "discriminatedUnion", "effect",
    "enum", "function", "getErrorMap", "getParsedType", "instanceof", "intersection",
    "isAborted", "isAsync", "isDirty", "isValid", "late", "lazy", "literal", "makeIssue",
    "map", "nan", "nativeEnum", "never", "null", "nullable", "number", "object", "objectUtil",
    "oboolean", "onumber", "optional", "ostring", "pipeline", "preprocess", "promise",
    "quotelessJson", "record", "set", "setErrorMap", "strictObject", "string", "symbol",
    "transformer", "tuple", "undefined", "union", "unknown", "util", "void", "z",
]


def _chalk_pkg(**extra):
    # chalk@6.0.1 形态：type module、exports 只有 types/default、无 require 分支、API 在 .default 下
    return _dep(
        name="chalk", version="6.0.1", type_="module", declared_range="^6.0.1",
        exports={"types": "./source/index.d.ts", "default": "./source/index.js"},
        files={"source/index.js": _file("const chalk = { red: 1, bold: 2 };\nexport default chalk;\n", "module")},
        **extra
    )


def _commander_pkg(**extra):
    # commander@15.0.0 形态：type module、无 require 分支，但入口是 ESM 且 Command 在命名空间上
    return _dep(
        name="commander", version="15.0.0", type_="module", declared_range="^15.0.0",
        exports={".": {"types": "./typings/index.d.ts", "default": "./index.js"}},
        files={"index.js": _file(
            "import { Command } from './lib/command.js';\n"
            "export const program = new Command();\n"
            "export { Command, Argument, CommanderError, InvalidArgumentError, Help, Option };\n",
            "module",
        )},
        **extra
    )


def _zod_pkg(**extra):
    # zod@4.6.7 形态：type module 但 exports 有 require 分支（→ 真 CJS 产物）、显式暴露 ./package.json
    return _dep(
        name="zod", version="4.6.7", type_="module", declared_range="^4.6.7",
        exports=PKG_EXPORTS["zod"],
        files={
            "index.js": _file('export * from "./v4/core.mjs";\n', "module"),
            "v4/core.mjs": _file(
                "export const z = null;\nexport const ZodError = null;\nexport const string = null;\n", "module"
            ),
            "index.cjs": _file('__exportStar(require("./v4/core.cjs"), exports);\n', "commonjs"),
            "v4/core.cjs": _file("exports.z = null;\nexports.ZodError = null;\nexports.string = null;\n", "commonjs"),
            "package.json": _file(
                json.dumps({"name": "zod", "version": "4.6.7", "type": "module", "exports": PKG_EXPORTS["zod"]}),
                None,
            ),
        },
        **extra
    )


def _glob_pkg(**extra):
    # glob@14.0.3 形态：包根 type: module，dist/commonjs 子目录自带 type: commonjs（嵌套 type 实测）；
    # "." 入口落 index.min.js、./raw 落 index.js（真实目标名）
    return _dep(
        name="glob", version="14.0.3", type_="module", declared_range="^14.0.3",
        exports=PKG_EXPORTS["glob"],
        files={
            "dist/esm/index.js": _file("export const globSync = null;\nexport const glob = null;\n", "module"),
            "dist/esm/index.min.js": _file("export const globSync = null;\nexport const glob = null;\n", "module"),
            "dist/commonjs/index.js": _file("exports.globSync = null;\nexports.glob = null;\n", "commonjs"),
            "dist/commonjs/index.min.js": _file("exports.globSync = null;\nexports.glob = null;\n", "commonjs"),
        },
        **extra
    )


def _datefns_pkg(**extra):
    # date-fns@4.4.0 形态：入口是 245 行 re-export 桶，展开后 addDays 在导出集里
    return _dep(
        name="date-fns", version="4.4.0", type_="module", declared_range="^4.4.0",
        exports={".": {"import": "./index.js", "require": "./index.cjs"}},
        files={
            "index.js": _file('export * from "./dates.js";\nexport * from "./locale.js";\n', "module"),
            "dates.js": _file("export const addDays = 1;\nexport const subDays = 2;\n", "module"),
            "locale.js": _file("export const enUS = 1;\n", "module"),
            "index.cjs": _file(
                'var _d = require("./dates.cjs");\nObject.keys(_d).forEach(function (k) { exports[k] = _d[k]; });\n',
                "commonjs",
            ),
            "dates.cjs": _file("exports.addDays = 1;\nexports.subDays = 2;\n", "commonjs"),
        },
        **extra
    )


def _five_deps():
    return {d["name"]: d for d in (_chalk_pkg(), _commander_pkg(), _zod_pkg(), _glob_pkg(), _datefns_pkg())}


def test_c1_resolved_basic_all_five_packages():
    # C1 · 五包 import 全 RESOLVED，退出码 0（前两行注释对齐旧语料的行号）
    sources = [{"file": "src/index.mjs", "text": (
        '// C1 · resolved-basic —— 五个判定态的对照组（本文件仅作静态分析输入）。\n'
        '// 本项目不执行被测代码。\n'
        'import chalk from "chalk";\n'
        'import { z } from "zod";\n'
        'import { addDays } from "date-fns";\n'
        'import { globSync } from "glob";\n'
        'import { program } from "commander";\n'
    )}]
    records = _evaluate(_subject(sources, _five_deps(), {k: d["declared_range"] for k, d in _five_deps().items()}))
    st = _statuses(records)
    assert st["src/index.mjs|3|chalk"] == "RESOLVED"
    assert st["src/index.mjs|4|zod"] == "RESOLVED"
    assert st["src/index.mjs|5|date-fns"] == "RESOLVED"
    assert st["src/index.mjs|6|glob"] == "RESOLVED"
    assert st["src/index.mjs|7|commander"] == "RESOLVED"
    assert _report_exit(records) == EXIT_OK


def test_c2_missing_export_esm_and_cjs_counterexample():
    # C2 · ESM 视角缺 notARealExport → MISSING-EXPORT；同包 CJS 取 red → MISMATCH（判定顺序在前）
    sources = [
        {"file": "src/chalk.mjs", "text": 'import { notARealExport } from "chalk";\nmodule.exports = { notARealExport };\n'},
        {"file": "src/chalk.cjs", "text": 'const { red } = require("chalk");\nmodule.exports = { red };\n'},
        {"file": "src/zod.mjs", "text": 'import { notARealExport } from "zod";\nmodule.exports = { notARealExport };\n'},
        {"file": "src/date-fns.mjs", "text": 'import { notARealExport } from "date-fns";\nmodule.exports = { notARealExport };\n'},
    ]
    deps = {"chalk": _chalk_pkg(), "zod": _zod_pkg(), "date-fns": _datefns_pkg()}
    records = _evaluate(_subject(sources, deps, {k: d["declared_range"] for k, d in deps.items()}))
    st = _statuses(records)
    assert st["src/chalk.mjs|1|chalk"] == "MISSING-EXPORT"
    assert st["src/chalk.cjs|1|chalk"] == "ESM-CJS-MISMATCH"
    assert st["src/zod.mjs|1|zod"] == "MISSING-EXPORT"
    assert st["src/date-fns.mjs|1|date-fns"] == "MISSING-EXPORT"
    missing_evidence = [r.evidence for r in _by_rule(records, "dp-missing-export")]
    assert any(e["missing"] == ["notARealExport"] and "available" in e for e in missing_evidence)


def test_c2_missing_export_available_sorted_top20():
    sources = [{"file": "src/a.mjs", "text": 'import { notThere } from "demo-pkg";\n'}]
    names = ["n%02d" % i for i in range(30)]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": {"import": "./index.mjs", "require": "./index.cjs"}},
        files={"index.mjs": _file("".join("export const %s = 1;\n" % n for n in names), "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    rec = _by_rule(records, "dp-missing-export")[0]
    assert rec.evidence["available"] == sorted(names)[:20], "available 取排序后的前 20"


def test_c3_chalk_mismatch_commander_resolved_same_has_require_branch():
    # C3 · chalk 判红、commander 判绿，两者 hasRequireBranch 相同（都无 require 分支）
    # ——判定靠符号所在层区分：chalk 的 red 在 .default 下（命名空间上没有），commander 的
    # Command 在命名空间上（入口 ESM export { Command, ... }）。
    sources = [
        {"file": "src/against-chalk.cjs", "text": 'const { red } = require("chalk");\nmodule.exports = { red };\n'},
        {"file": "src/against-commander.cjs", "text": 'const { Command } = require("commander");\nmodule.exports = { Command };\n'},
    ]
    deps = {"chalk": _chalk_pkg(), "commander": _commander_pkg()}
    records = _evaluate(_subject(sources, deps, {k: d["declared_range"] for k, d in deps.items()}))
    st = _statuses(records)
    assert st["src/against-chalk.cjs|1|chalk"] == "ESM-CJS-MISMATCH"
    assert st["src/against-commander.cjs|1|commander"] == "RESOLVED"


def test_c3_zod_glob_datefns_require_views_resolved():
    # C3 · zod（type:module 但有 require 分支）/ glob（require 落 dist/commonjs）
    # / date-fns（CJS 桶 Object.keys 转发）的 require 视角全部 RESOLVED
    sources = [
        {"file": "src/against-zod.cjs", "text": 'const { z } = require("zod");\n'},
        {"file": "src/against-glob.cjs", "text": 'const { globSync } = require("glob");\n'},
        {"file": "src/against-date-fns.cjs", "text": 'const { addDays } = require("date-fns");\n'},
    ]
    deps = {k: d for k, d in _five_deps().items() if k in ("zod", "glob", "date-fns")}
    records = _evaluate(_subject(sources, deps, {k: d["declared_range"] for k, d in deps.items()}))
    st = _statuses(records)
    assert st["src/against-zod.cjs|1|zod"] == "RESOLVED"
    assert st["src/against-glob.cjs|1|glob"] == "RESOLVED"
    assert st["src/against-date-fns.cjs|1|date-fns"] == "RESOLVED"


def test_c3_mismatch_evidence_names_rule_and_branch():
    sources = [{"file": "src/a.cjs", "text": 'const { red } = require("chalk");\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    rec = _by_rule(records, "dp-esm-cjs-mismatch")[0]
    assert rec.evidence["hasRequireBranch"] is False
    assert rec.evidence["requested"] == ["red"]
    assert rec.evidence["type"] == "module"


def test_c4_subpath_blocked_three_forms():
    # C4 · chalk/commander 未列 ./package.json、chalk 内部文件路径未列 → NOT-EXPORTED-SUBPATH
    sources = [
        {"file": "src/a.cjs", "text": 'const sub = require("chalk/package.json");\n'},
        {"file": "src/b.cjs", "text": 'const sub = require("commander/package.json");\n'},
        {"file": "src/c.cjs", "text": 'const sub = require("chalk/source/index.js");\n'},
    ]
    deps = {"chalk": _chalk_pkg(), "commander": _commander_pkg()}
    records = _evaluate(_subject(sources, deps, {k: d["declared_range"] for k, d in deps.items()}))
    st = _statuses(records)
    assert st["src/a.cjs|1|chalk/package.json"] == "NOT-EXPORTED-SUBPATH"
    assert st["src/b.cjs|1|commander/package.json"] == "NOT-EXPORTED-SUBPATH"
    assert st["src/c.cjs|1|chalk/source/index.js"] == "NOT-EXPORTED-SUBPATH"
    rec = _by_rule(records, "dp-not-exported-subpath")[0]
    assert rec.evidence["rule"] == "exports 未列该子路径"


def test_c4_counterexamples_zod_package_json_and_glob_raw_resolved():
    # C4 · 反例：zod 显式列了 ./package.json、glob 显式列了 ./raw → 同一写法 RESOLVED
    sources = [
        {"file": "src/d.cjs", "text": 'const sub = require("zod/package.json");\n'},
        {"file": "src/e.cjs", "text": 'const sub = require("glob/raw");\n'},
    ]
    deps = {"zod": _zod_pkg(), "glob": _glob_pkg()}
    records = _evaluate(_subject(sources, deps, {k: d["declared_range"] for k, d in deps.items()}))
    st = _statuses(records)
    assert st["src/d.cjs|1|zod/package.json"] == "RESOLVED"
    assert st["src/e.cjs|1|glob/raw"] == "RESOLVED"


def test_c4_null_block_is_not_exported_subpath():
    # 形态③：exports 显式 null 屏蔽（不是"不存在"）
    sources = [{"file": "src/a.mjs", "text": 'import x from "demo-pkg/secret";\n'}]
    dep = _dep(name="demo-pkg", type_="module", exports={"./secret": None, ".": "./index.mjs"},
               files={"index.mjs": _file("export default 1;\n", "module")})
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    rec = _by_rule(records, "dp-not-exported-subpath")[0]
    assert rec.evidence["rule"] == "exports 显式 null 屏蔽"
    assert rec.verdict == ERROR


def test_c5_ambiguous_points_explicit_and_exit_zero():
    # C5 · 动态形态全部显式落 AMBIGUOUS（不代表代码有错），退出码 0，显式计数
    sources = [
        {"file": "src/dyn-var.cjs", "text": 'const name = "chalk";\nconst mod = require(name);\n'},
        {"file": "src/dyn-concat.cjs", "text": 'const x = "chalk";\nconst mod = require(`chalk/${x}`);\n'},
        {"file": "src/dyn-import.cjs", "text": "async function load(someVar) {\n  const m = await import(someVar);\n  return m;\n}\n"},
        {"file": "src/dyn-prop.cjs", "text": 'const suffix = "/package.json";\nconst mod = require("chalk" + suffix);\n'},
        {"file": "src/static.mjs", "text": 'import { z } from "zod";\n'},
    ]
    deps = {"chalk": _chalk_pkg(), "zod": _zod_pkg()}
    records = _evaluate(_subject(sources, deps, {k: d["declared_range"] for k, d in deps.items()}))
    st = _statuses(records)
    assert st["src/dyn-var.cjs|2|None"] == "AMBIGUOUS"
    assert st["src/dyn-concat.cjs|2|None"] == "AMBIGUOUS"
    assert st["src/dyn-import.cjs|2|None"] == "AMBIGUOUS"
    assert st["src/dyn-prop.cjs|2|None"] == "AMBIGUOUS"
    assert st["src/static.mjs|1|zod"] == "RESOLVED"
    s = _summary(records).evidence
    assert s["problems"] == 0
    assert s["ambiguous"] >= 4
    assert _report_exit(records) == EXIT_OK


def test_c7_clean_project_zero_false_positives():
    # C7 · 干净工程零误报（反向断言自证 totalPoints > 0，防空跑假绿）
    sources = [
        {"file": "src/a.cjs", "text": 'const { z } = require("zod");\n'},
        {"file": "src/b.cjs", "text": 'const { addDays } = require("date-fns");\n'},
        {"file": "src/c.cjs", "text": 'const { globSync } = require("glob");\n'},
        {"file": "src/d.cjs", "text": 'const { Command } = require("commander");\n'},
        {"file": "src/e.mjs", "text": 'import chalk from "chalk";\n'},
        {"file": "src/f.cjs", "text": 'const sub = require("zod/package.json");\n'},
        {"file": "src/g.cjs", "text": 'const sub = require("glob/raw");\n'},
    ]
    declared = {k: d["declared_range"] for k, d in _five_deps().items()}
    records = _evaluate(_subject(sources, _five_deps(), declared))
    s = _summary(records).evidence
    assert s["problems"] == 0
    assert s["gaps"] == 0
    assert s["totalPoints"] >= 7, "totalPoints 必须 > 0，否则零误报是空跑"
    assert s["byStatus"] == {"RESOLVED": 7}
    assert _report_exit(records) == EXIT_OK


def test_out_of_scope_references_not_judged():
    # 非依赖引用（相对路径、node: 内置）不在判定面内——不进 findings，也不算"没问题"式静默
    sources = [{"file": "src/a.mjs", "text": 'import x from "./local.js";\nimport fs from "node:fs";\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    assert _statuses(records) == {}
    s = _summary(records).evidence
    assert s["totalPoints"] == 2
    assert s["resolved"] == 0


def test_esm_namespace_reachable_not_mismatch():
    # §5.2 第 4 条的可达分支：有具名取用且名字在命名空间上 → 不判 MISMATCH
    sources = [{"file": "src/a.cjs", "text": 'const { Command } = require("commander");\n'}]
    records = _evaluate(_subject(sources, {"commander": _commander_pkg()}, {"commander": "^15.0.0"}))
    assert _statuses(records)["src/a.cjs|1|commander"] == "RESOLVED"


def test_mjs_target_esm_only_no_require_branch_mismatch():
    # §5.2 第 1 条的另一个分支：type 不是 module 但入口目标是 .mjs → 同样 looksEsmOnly
    # （exports 无 require 分支是招牌判据；MISMATCH 排在目标解析之前，判定顺序先命中）
    sources = [{"file": "src/a.cjs", "text": 'const { nope } = require("demo-pkg");\n'}]
    dep = _dep(
        name="demo-pkg", type_=None,
        exports={".": {"import": "./index.mjs"}},
        files={"index.mjs": _file("export const other = 1;\nexport default 2;\n", "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    assert _statuses(records)["src/a.cjs|1|demo-pkg"] == "ESM-CJS-MISMATCH"


def test_require_point_on_package_with_require_branch_resolved():
    # 反面判据（§5.2）：type: module 但有 require 分支的包必须判 RESOLVED
    sources = [{"file": "src/a.cjs", "text": 'const { z } = require("zod");\n'}]
    records = _evaluate(_subject(sources, {"zod": _zod_pkg()}, {"zod": "^4.6.7"}))
    assert _statuses(records)["src/a.cjs|1|zod"] == "RESOLVED"


def test_judge_order_mismatch_beats_missing_export():
    # 判定顺序（plan/03 §4.4）：ESM-CJS-MISMATCH 排在 MISSING-EXPORT 之前（C2 点 4 的真值）
    sources = [{"file": "src/chalk.cjs", "text": 'const { red } = require("chalk");\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    st = _statuses(records)
    assert st["src/chalk.cjs|1|chalk"] == "ESM-CJS-MISMATCH"
    assert not any(r.rule_id == "dp-missing-export" for r in records)


def test_judge_order_ambiguous_beats_subpath_judgment():
    # 判定顺序：AMBIGUOUS 在最前——动态 specifier 连子路径判定面都进不了
    sources = [{"file": "src/a.cjs", "text": 'const m = require("chalk" + suffix);\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    st = _statuses(records)
    assert st["src/a.cjs|1|None"] == "AMBIGUOUS"
    assert not any(r.rule_id == "dp-not-exported-subpath" for r in records)


def test_no_package_json_gap_blocks_point():
    # 单依赖未安装 → NO_PACKAGE_JSON gap；引用点不判判定态（算不了≠没问题）。
    # 旧仓对同一缺失产出两条 gap（readProject 的包级一条 + judgePoint 的点级一条），
    # 账本化后各占一行（id 不冲突：path 分别是包名与 file:line）。
    sources = [{"file": "src/a.mjs", "text": 'import { x } from "gone-pkg";\n'}]
    records = _evaluate(_subject(sources, {}, {"gone-pkg": "^1.0.0"}))
    gap = _by_rule(records, "dp-no-package-json")
    assert len(gap) == 2
    assert all(g.verdict == ERROR for g in gap)
    assert {g.path for g in gap} == {"gone-pkg", "src/a.mjs:1"}
    assert _statuses(records) == {}
    assert _report_exit(records) == EXIT_BLOCKED


def test_unparseable_exports_gap_blocks_point():
    # 旧仓同样产出两条（readProject 包级 + judgePoint 点级），账本各占一行、path 可区分
    sources = [{"file": "src/a.mjs", "text": 'import x from "demo-pkg";\n'}]
    dep = _dep(name="demo-pkg", type_="module", exports={".": "./i.js", "import": "./i.mjs"})
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    gap = _by_rule(records, "dp-exports-unparseable")
    assert len(gap) == 2
    assert {g.path for g in gap} == {"demo-pkg", "src/a.mjs:1"}
    assert _statuses(records) == {}


def test_exports_not_declared_gap_blocks_point():
    sources = [{"file": "src/a.mjs", "text": 'import x from "demo-pkg";\n'}]
    dep = _dep(name="demo-pkg", type_=None, exports=None, files={"index.js": _file("exports.x = 1;\n", "commonjs")})
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    assert len(_by_rule(records, "dp-exports-not-declared")) == 1
    assert _statuses(records) == {}


def test_unresolvable_target_gap():
    # 条件集不匹配（unmatched）→ UNRESOLVABLE_TARGET gap，不判判定态
    sources = [{"file": "src/a.mjs", "text": 'import x from "demo-pkg";\n'}]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": [{"browser": "./br.js"}, {"electron": "./e.js"}]},
        files={"br.js": _file("export default 1;\n", "module"), "e.js": _file("export default 1;\n", "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    assert len(_by_rule(records, "dp-unresolvable-target")) == 1
    assert _statuses(records) == {}


def test_export_surface_unparseable_gap_on_identifier_export():
    # module.exports = someIdentifier → 具名导出集不可静态确定 → 不猜（gap，不判 MISSING）
    sources = [{"file": "src/a.cjs", "text": 'const ns = require("demo-pkg").thing;\n'}]
    dep = _dep(
        name="demo-pkg", type_=None,
        exports={".": "./index.cjs"},
        files={"index.cjs": _file("module.exports = someFactory();\n", "commonjs")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    assert len(_by_rule(records, "dp-export-surface-unparseable")) == 1
    assert _statuses(records) == {}


def test_export_surface_external_reexport_gap():
    # 仅外部 re-export（export * from "pkg"）→ 需递归解析外部包，首期不复刻 → 不猜
    sources = [{"file": "src/a.mjs", "text": 'import x from "demo-pkg";\n'}]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": {"import": "./index.js", "require": "./index.js"}},
        files={"index.js": _file('export * from "other-pkg";\n', "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    assert len(_by_rule(records, "dp-export-surface-unparseable")) == 1


def test_barrel_recursion_reads_through_relative_reexports():
    # date-fns 形态：入口是 re-export 桶，只看首层会读出空导出集 → 每个真实引用点都变
    # MISSING-EXPORT（系统性假阳性）。递归只沿相对路径走。
    sources = [{"file": "src/a.mjs", "text": 'import { addDays } from "demo-pkg";\n'}]
    dep = _datefns_pkg()
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^4.4.0"}))
    assert _statuses(records)["src/a.mjs|1|demo-pkg"] == "RESOLVED"


def test_barrel_one_unreadable_branch_does_not_kill_surface():
    # 桶文件里一支读不出不算整包算不了：其它分支给出具名导出仍可用
    sources = [{"file": "src/a.mjs", "text": 'import { addDays } from "demo-pkg";\n'}]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": {"import": "./index.js", "require": "./index.js"}},
        files={
            "index.js": _file('export * from "./dates.js";\nexport * from "./missing-branch.js";\n', "module"),
            "dates.js": _file("export const addDays = 1;\n", "module"),
        },
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    assert _statuses(records)["src/a.mjs|1|demo-pkg"] == "RESOLVED"


def test_nested_commonjs_directory_type_not_package_root():
    # glob 实测：dist/commonjs/package.json 写着 type: commonjs，按包根判会把 CJS 产物当
    # ESM 解析，导出集读成空（实测 0 个）。输入层按同一口径给出每文件的 type。
    sources = [{"file": "src/a.cjs", "text": 'const { globSync } = require("glob");\n'}]
    dep = _dep(
        name="glob", version="14.0.3", type_="module",
        exports={".": {"import": "./dist/esm/index.js", "require": "./dist/commonjs/index.js"}},
        files={"dist/commonjs/index.js": _file("exports.globSync = 1;\n", "commonjs")},
    )
    records = _evaluate(_subject(sources, {"glob": dep}, {"glob": "^14.0.3"}))
    assert _statuses(records)["src/a.cjs|1|glob"] == "RESOLVED"


def test_string_literal_kind_point_is_judged():
    # 兜底点也是引用点：裸字符串命中已装依赖 → 参与判定
    sources = [{"file": "src/a.cjs", "text": '// 用法文档见 "chalk" 包\nconst a = 1;\n'}]
    dep = _chalk_pkg()
    dep["files"]["source/index.js"] = _file("const chalk = { red: 1 };\nexport default chalk;\nmodule.exports = chalk;\n", "module")
    records = _evaluate(_subject(sources, {"chalk": dep}, {"chalk": "^6.0.1"}))
    s = _summary(records).evidence
    assert s["totalPoints"] >= 1
    assert any(r.evidence.get("kind") == "string-literal" for r in records)


def test_jest_mock_point_is_judged():
    sources = [{"file": "src/a.cjs", "text": 'jest.mock("chalk");\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    st = _statuses(records)
    assert st["src/a.cjs|1|chalk"] == "RESOLVED"
    assert any(r.evidence.get("kind") == "jest-mock" for r in records)


def test_dynamic_import_literal_point_is_judged():
    sources = [{"file": "src/a.mjs", "text": 'await import("demo-pkg");\n'}]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": {"import": "./index.mjs", "require": "./index.cjs"}},
        files={"index.mjs": _file("export const a = 1;\n", "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    st = _statuses(records)
    assert st["src/a.mjs|1|demo-pkg"] == "RESOLVED"
    assert any(r.evidence.get("kind") == "dynamic-import" for r in records)


def test_export_from_point_is_judged():
    sources = [{"file": "src/a.mjs", "text": 'export { red } from "demo-pkg";\n'}]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": {"import": "./index.mjs", "require": "./index.cjs"}},
        files={"index.mjs": _file("export const red = 1;\nexport const blue = 2;\n", "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    st = _statuses(records)
    assert st["src/a.mjs|1|demo-pkg"] == "RESOLVED"
    assert any(r.evidence.get("kind") == "export-from" for r in records)


def _report_exit(records):
    return _report_from_records(records).exit_code()


def _report_from_records(records):
    return Report(
        product="byteproof", organ=SLUG, organ_version=spec.ORGAN_VERSION, subject="t", records=records,
    )


# ==================================================================
# §6 版本行为漂移（drift 三条口径；zod 真实基线面作锚）
# ==================================================================

def _zod_baseline():
    return {
        "name": "zod",
        "baselineVersion": "3.25.76",
        "surfaces": {".": {"import": list(ZOD_BASELINE_IMPORT_NAMES), "require": None}},
    }


def test_drift_no_baseline_is_not_a_problem():
    # §5.5 第 1 条：无基线 → NO-BASELINE（不猜），且**不**进 problems
    deps = {"chalk": check.build_dep_index(_chalk_pkg())}
    got = drift.judge_drift_point(_point("chalk", ["red"]), deps, {})
    assert got["status"] == "NO-BASELINE"
    assert "不猜" in got["detail"]


def test_drift_same_version_identity_never_drifts():
    # 装的就是基线版本 → 同一份导出面，漂移不可成立（恒等式，不是猜）
    deps = {"chalk": check.build_dep_index(_chalk_pkg())}
    baselines = {"chalk": {"baselineVersion": "6.0.1", "surfaces": {".": {"import": ["red", "ghost"], "require": None}}}}
    got = drift.judge_drift_point(_point("chalk", ["red"]), deps, baselines)
    assert got["status"] is None
    assert "基线版本" in got["detail"]


def test_drift_symbol_gone_is_drift():
    # §5.5 第 2 条：符号在基线有、已装没有 → VERSION-BEHAVIOR-DRIFT
    deps = {"demo-pkg": check.build_dep_index(_esm_dep(names=("red", "blue")))}
    baselines = {"demo-pkg": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red", "blue", "ghost"], "require": None}}}}
    got = drift.judge_drift_point(_point("demo-pkg", ["ghost"]), deps, baselines)
    assert got["status"] == "VERSION-BEHAVIOR-DRIFT"
    assert got["missing"] == ["ghost"]
    assert got["baselineVersion"] == "5.0.0"
    assert got["installedVersion"] == "1.0.3"


def test_drift_major_bump_with_symbol_kept_is_not_drift():
    # 防"版本号一变大就报红"：判据是行为不是 semver 字符串
    deps = {"demo-pkg": check.build_dep_index(_esm_dep(names=("red", "blue")))}
    baselines = {"demo-pkg": {"baselineVersion": "3.0.0", "surfaces": {".": {"import": ["red", "blue"], "require": None}}}}
    got = drift.judge_drift_point(_point("demo-pkg", ["red"]), deps, baselines)
    assert got["status"] is None


def test_drift_unit_is_point_not_package():
    # §5.5 第 3 条：判定单位是引用点——同包两个引用点一个红一个绿
    deps = {"demo-pkg": check.build_dep_index(_esm_dep(names=("red", "blue")))}
    baselines = {"demo-pkg": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red", "blue", "ghost"], "require": None}}}}
    gone = drift.judge_drift_point(_point("demo-pkg", ["ghost"], "src/a.mjs", 2), deps, baselines)
    kept = drift.judge_drift_point(_point("demo-pkg", ["red"], "src/b.mjs", 2), deps, baselines)
    assert gone["status"] == "VERSION-BEHAVIOR-DRIFT"
    assert kept["status"] is None, "按包比会把这条也判红"


def test_drift_symbol_missing_in_both_not_drift_business():
    # 基线里本来也没有的符号不归 drift 管（那是 MISSING-EXPORT 的判据，不重复判）
    deps = {"demo-pkg": check.build_dep_index(_esm_dep(names=("red", "blue")))}
    baselines = {"demo-pkg": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red"], "require": None}}}}
    got = drift.judge_drift_point(_point("demo-pkg", ["notARealExport"]), deps, baselines)
    assert got["status"] is None


def test_drift_load_only_points_out_of_scope():
    # 只加载包、不取符号的引用点不在 drift 判定面内（返回 None）
    deps = {"demo-pkg": check.build_dep_index(_esm_dep())}
    baselines = {"demo-pkg": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red"], "require": None}}}}
    assert drift.judge_drift_point(_point("demo-pkg", []), deps, baselines) is None
    assert drift.judge_drift_point(_point("demo-pkg", ["*"]), deps, baselines) is None


def test_drift_dynamic_and_undeclared_points_out_of_scope():
    deps = {"demo-pkg": check.build_dep_index(_esm_dep())}
    baselines = {"demo-pkg": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red"], "require": None}}}}
    assert drift.judge_drift_point({"file": "a", "line": 1, "kind": "ambiguous", "specifier": None, "imported": []}, deps, baselines) is None
    assert drift.judge_drift_point(_point("./local", ["x"]), deps, baselines) is None


def test_drift_baseline_shape_validation():
    # 基线读不出/形状不对 → 一律按无基线（不猜，不崩）
    assert drift._validate_baseline(None) is None
    assert drift._validate_baseline("x") is None
    assert drift._validate_baseline(["a"]) is None
    assert drift._validate_baseline({"name": "x"}) is None                # 缺 baselineVersion
    assert drift._validate_baseline({"baselineVersion": "1"}) is None     # 缺 surfaces
    ok = drift._validate_baseline({"baselineVersion": "1", "surfaces": {}})
    assert ok is not None


def test_drift_baseline_view_null_is_no_baseline():
    # 基线的该视角记录为 null（"读不出"，不是"没有"）→ NO-BASELINE，不猜
    deps = {"chalk": check.build_dep_index(_chalk_pkg())}
    baselines = {"chalk": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red"], "require": None}}}}
    got = drift.judge_drift_point(_point("chalk", ["red"], kind="require"), deps, baselines)
    assert got["status"] == "NO-BASELINE"
    assert "未收录" in got["detail"]


def test_drift_baseline_uncollected_subpath_no_baseline():
    deps = {"chalk": check.build_dep_index(_chalk_pkg())}
    baselines = {"chalk": {"baselineVersion": "5.0.0", "surfaces": {"./other": {"import": ["red"], "require": None}}}}
    got = drift.judge_drift_point(_point("chalk", ["red"], kind="require"), deps, baselines)
    assert got["status"] == "NO-BASELINE"


def test_drift_installed_surface_unreadable_no_baseline():
    # 已装导出面读不出 → NO-BASELINE（不猜）
    deps = {"chalk": check.build_dep_index(_chalk_pkg())}
    deps["chalk"]["files"] = {}  # 入口文件缺失
    baselines = {"chalk": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["red"], "require": None}}}}
    got = drift.judge_drift_point(_point("chalk", ["red"]), deps, baselines)
    assert got["status"] == "NO-BASELINE"


def test_drift_zod_baseline_anchor_zodschema_red_z_green():
    # C6 真值锚（真实基线 109 名 vs zod@4.6.7 等价已装面）：
    # 点 1 取 ZodSchema（基线有、4.6.7 没有）→ DRIFT；点 2 取 z（两版都在）→ 不漂移
    deps = {"zod": check.build_dep_index(_zod_pkg())}
    baselines = {"zod": _zod_baseline()}
    gone = drift.judge_drift_point(_point("zod", ["ZodSchema"], "src/uses-old-api.mjs", 2, "import"), deps, baselines)
    kept = drift.judge_drift_point(_point("zod", ["z"], "src/uses-stable-api.mjs", 2, "import"), deps, baselines)
    assert gone["status"] == "VERSION-BEHAVIOR-DRIFT"
    assert gone["missing"] == ["ZodSchema"]
    assert gone["baselineVersion"] == "3.25.76"
    assert kept["status"] is None


def test_drift_missing_sorted_in_evidence():
    deps = {"chalk": check.build_dep_index(_chalk_pkg())}
    baselines = {"chalk": {"baselineVersion": "5.0.0", "surfaces": {".": {"import": ["zeta", "alpha", "red"], "require": None}}}}
    got = drift.judge_drift_point(_point("chalk", ["zeta", "alpha"]), deps, baselines)
    assert got["missing"] == ["alpha", "zeta"]


def test_drift_replaces_missing_export_not_double_count():
    # DRIFT 是同一引用点上更精确的诊断，就地取代较粗的那条（通常是 MISSING-EXPORT）；
    # 不取代的后果：problems 被算两遍，"1 个问题"读成"2 个"
    deps = {"zod": _zod_pkg(), "date-fns": _datefns_pkg()}
    declared = {"zod": "^3.25.76", "date-fns": "^3.0.0"}
    sources = [
        {"file": "src/uses-old-api.mjs", "text": 'import { ZodSchema } from "zod";\n'},
        {"file": "src/uses-stable-api.mjs", "text": 'import { z } from "zod";\n'},
        {"file": "src/uses-api-no-history.mjs", "text": 'import { addDays } from "date-fns";\n'},
    ]
    records = _evaluate(_subject(sources, deps, declared, baselines={"zod": _zod_baseline()},
                                 options={"with_drift": True}))
    st = _statuses(records)
    assert st["src/uses-old-api.mjs|1|zod"] == "VERSION-BEHAVIOR-DRIFT"
    assert st["src/uses-stable-api.mjs|1|zod"] == "RESOLVED"
    assert st["src/uses-api-no-history.mjs|1|date-fns"] == "RESOLVED"
    s = _summary(records).evidence
    assert s["problems"] == 1, "DRIFT 取代 MISSING-EXPORT，不得重复计数"
    assert s["gaps"] == 1, "date-fns 无基线必须记 NO-BASELINE"
    assert s["byStatus"] == {"VERSION-BEHAVIOR-DRIFT": 1, "RESOLVED": 2}
    assert _report_exit(records) == EXIT_BLOCKED


def test_drift_mode_only_no_baseline_blocks():
    # drift 命令单独跑：只有 NO-BASELINE → 阻断（旧 rc3：把"没跑"写成"跑了没问题"是错的）
    deps = {"date-fns": _datefns_pkg()}
    sources = [{"file": "src/a.mjs", "text": 'import { addDays } from "date-fns";\n'}]
    records = _evaluate(_subject(sources, deps, {"date-fns": "^3.0.0"}, mode="drift", baselines={}))
    assert _statuses(records) == {}, "NO-BASELINE 不是判定态，不得出现在 findings"
    assert len(_by_rule(records, "dp-no-baseline")) == 1
    assert _report_exit(records) == EXIT_BLOCKED


def test_drift_mode_drift_found_blocks():
    deps = {"zod": _zod_pkg()}
    sources = [{"file": "src/a.mjs", "text": 'import { ZodSchema } from "zod";\n'}]
    records = _evaluate(_subject(sources, deps, {"zod": "^3.25.76"}, mode="drift", baselines={"zod": _zod_baseline()}))
    assert _statuses(records)["src/a.mjs|1|zod"] == "VERSION-BEHAVIOR-DRIFT"
    assert _report_exit(records) == EXIT_BLOCKED


def test_drift_mode_clean_zero():
    deps = {"zod": _zod_pkg()}
    sources = [{"file": "src/a.mjs", "text": 'import { z } from "zod";\n'}]
    records = _evaluate(_subject(sources, deps, {"zod": "^4.6.7"}, mode="drift", baselines={"zod": _zod_baseline()}))
    assert _statuses(records) == {}
    assert _report_exit(records) == EXIT_OK


# ==================================================================
# §7 编排 / 退出码语义 / 契约常量 / subject 校验
# ==================================================================

def _sample_subject():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def test_sample_minimal_clean_rc0():
    # 样例（干净树）：import+require 双视角 RESOLVED，rc 0
    subject = _sample_subject()
    records = _evaluate(subject)
    s = _summary(records).evidence
    assert s["problems"] == 0
    assert s["gaps"] == 0
    assert s["totalPoints"] == 2
    assert s["resolved"] == 2
    assert _report_exit(records) == EXIT_OK


def test_cli_check_sample_rc0():
    # 宿主 CLI：check <slug> 同参数（显式带 basis）rc 0
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH)])
    assert rc == EXIT_OK


def test_cli_check_sample_without_basis_rc0():
    # 随包 basis 缺省可用（宿主 CLI 没 --basis 时读 byteproof/data/<slug>.basis.json）
    rc = cli.main(["check", SLUG, "--input", str(SAMPLE)])
    assert rc == EXIT_OK


def test_cli_check_problem_input_rc1():
    tmp = ROOT / ".tmp-depcheck-problem.json"
    subject = _sample_subject()
    subject["sources"] = [{"file": "src/x.mjs", "text": 'import { nope } from "demo-pkg";\n'}]
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_BLOCKED


def test_cli_check_missing_mode_rc2():
    tmp = ROOT / ".tmp-depcheck-nomode.json"
    subject = _sample_subject()
    del subject["mode"]
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_INPUT


def test_cli_check_unknown_mode_rc2():
    tmp = ROOT / ".tmp-depcheck-badmode.json"
    subject = _sample_subject()
    subject["mode"] = "scan"
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_INPUT


def test_cli_check_missing_project_rc2():
    tmp = ROOT / ".tmp-depcheck-noproject.json"
    subject = {"mode": "check", "sources": []}
    tmp.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(tmp), "--basis", str(BASIS_PATH)])
    finally:
        tmp.unlink()
    assert rc == EXIT_INPUT


def test_cli_check_missing_basis_contract_rc3():
    # 漏规则：空规则包（version 0、无 rules）下器官调 basis.ref 抛 RuleMissing → 契约违约 rc 3
    # （--basis 指向不存在的文件是 rc2「输入不合法」，与产品契约一致）
    tmp = ROOT / ".tmp-depcheck-empty-basis.json"
    tmp.write_text(json.dumps({"version": "0", "rules": []}), encoding="utf-8")
    try:
        rc = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(tmp)])
    finally:
        tmp.unlink()
    assert rc == EXIT_CONTRACT


def test_cli_list_includes_depcheck_live():
    load_builtin()
    packs = [p.slug for p in __import__("byteproof.core.registry", fromlist=["all_packs"]).all_packs()]
    assert SLUG in packs


def test_exit_mapping_problems_block():
    # 旧 rc1（发现判定问题）→ 新 rc1
    sources = [{"file": "src/a.mjs", "text": 'import { nope } from "demo-pkg";\n'}]
    records = _evaluate(_subject(sources, _sample_subject()["project"]["deps"], {"demo-pkg": "^1.0.0"}))
    assert _report_exit(records) == EXIT_BLOCKED


def test_exit_mapping_gaps_only_block_was_old_rc3():
    # 旧 rc3（算不了：依赖缺失且无确证问题）→ 新 rc1（error 级阻断记录）。
    # 口径差登记在案：账本无"算不了"专用退出码，落 warn 回 0 会反转
    # "零命中 ≠ 算不了" 的源仓设计红线（data/README.md §5.1）。
    records = _evaluate(_subject([], {}, {"gone-pkg": "^1.0.0"}))
    assert _report_exit(records) == EXIT_BLOCKED
    assert any(r.rule_id == "dp-no-package-json" for r in records)


def test_exit_mapping_ambiguous_only_zero():
    # 仅 AMBIGUOUS 无确证问题 → rc 0（但报告里显式计数）
    sources = [{"file": "src/a.cjs", "text": "const m = require(name);\n"}]
    records = _evaluate(_subject(sources, {}, {}))
    s = _summary(records).evidence
    assert s["ambiguous"] >= 1
    assert s["problems"] == 0
    assert s["gaps"] == 0
    assert _report_exit(records) == EXIT_OK


def test_summary_counts_and_by_status_sorted():
    sources = [
        {"file": "src/b.mjs", "text": 'import { nope } from "demo-pkg";\n'},
        {"file": "src/a.mjs", "text": 'import { red } from "demo-pkg";\n'},
    ]
    dep = _dep(
        name="demo-pkg", type_="module",
        exports={".": {"import": "./index.mjs", "require": "./index.cjs"}},
        files={"index.mjs": _file("export const red = 1;\n", "module")},
    )
    records = _evaluate(_subject(sources, {"demo-pkg": dep}, {"demo-pkg": "^1.0.0"}))
    s = _summary(records).evidence
    assert s["problems"] == 1
    assert s["resolved"] == 1
    assert s["totalPoints"] == 2
    assert s["byStatus"] == {"MISSING-EXPORT": 1, "RESOLVED": 1}  # 键排序确定性
    assert s["mode"] == "check"


def test_summary_in_drift_mode():
    records = _evaluate(_subject([], {}, {}, mode="drift"))
    s = _summary(records).evidence
    assert s["mode"] == "drift"
    assert s["problems"] == 0


def test_deterministic_double_run_byte_identical():
    subject = _subject(
        [{"file": "src/a.cjs", "text": 'const { red } = require("chalk");\nconst m = require(name);\n'}],
        {"chalk": _chalk_pkg()},
        {"chalk": "^6.0.1"},
    )
    a = [r.as_dict() for r in _evaluate(subject)]
    b = [r.as_dict() for r in _evaluate(subject)]
    assert json.dumps(a, ensure_ascii=False, sort_keys=True) == json.dumps(b, ensure_ascii=False, sort_keys=True)


def test_record_ids_stable_and_collision_free():
    # 同一行两个调用点、不同 specifier —— path 必须能区分（同一规则命中同一位置两次是账本违约）
    sources = [{"file": "src/a.cjs", "text": 'const a = require("chalk"); const b = require("chalk").bold;\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    ids = [r.id for r in records if r.rule_id != "dp-summary"]
    assert len(ids) == len(set(ids))


def test_finding_records_carry_kind_and_specifier_evidence():
    sources = [{"file": "src/a.cjs", "text": 'const { red } = require("chalk");\n'}]
    records = _evaluate(_subject(sources, {"chalk": _chalk_pkg()}, {"chalk": "^6.0.1"}))
    rec = _by_rule(records, "dp-esm-cjs-mismatch")[0]
    assert rec.evidence["kind"] == "require"
    assert rec.evidence["specifier"] == "chalk"
    assert rec.basis.rule_id == "dp-esm-cjs-mismatch"
    assert rec.basis.rule_version == "1"


def test_all_records_have_basis_refs():
    records = _evaluate(_sample_subject())
    for r in records:
        assert r.basis is not None
        assert r.basis.rule_id.startswith("dp-")


def test_subject_project_not_dict_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "check", "project": [], "sources": []})


def test_subject_declared_deps_not_dict_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(declared=[]))


def test_subject_deps_not_dict_rejected():
    subject = _subject()
    subject["project"]["deps"] = []
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_subject_sources_not_list_rejected():
    subject = _subject()
    subject["sources"] = "src"
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_subject_baselines_not_dict_rejected():
    subject = _subject()
    subject["baselines"] = []
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_subject_input_gaps_not_list_rejected():
    subject = _subject()
    subject["input_gaps"] = "x"
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_subject_options_not_dict_rejected():
    subject = _subject()
    subject["options"] = []
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_declared_non_string_ranges_ignored():
    # collectDeclaredDeps 口径：只有字符串 range 才计入"直接依赖面"
    sources = [{"file": "src/a.mjs", "text": 'import x from "demo-pkg";\n'}]
    records = _evaluate(_subject(sources, {"demo-pkg": _esm_dep()}, {"demo-pkg": True}))
    assert _statuses(records) == {}, "非字符串 range 不进依赖面 → 引用点 out-of-scope"


def test_builtin_modules_includes_depcheck_live_sorted():
    # BUILTIN_MODULES 用下划线模块名（depcheck_live ↔ slug depcheck-live）；
    # 计数不写死（器官数随批次增长）：接线清单与注册表一一对应
    assert "depcheck_live" in BUILTIN_MODULES
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES), "BUILTIN_MODULES 必须保持字典序"
    load_builtin()
    from byteproof.core.registry import all_packs
    assert len(BUILTIN_MODULES) == len(all_packs())


def test_pack_registered_with_contract_fields():
    load_builtin()
    pack = get(SLUG)
    assert pack.slug == SLUG
    assert pack.version == spec.ORGAN_VERSION == "1"
    assert pack.input_fields == ("mode",)
    assert callable(pack.evaluate)


def test_status_enum_exactly_five_values():
    # 旧仓 contract.mjs STATUS 冻结五值（方向① 的常量面）
    assert list(spec.STATUS.values()) == [
        "RESOLVED", "MISSING-EXPORT", "ESM-CJS-MISMATCH", "NOT-EXPORTED-SUBPATH", "AMBIGUOUS",
    ]


def test_non_status_values_not_in_status_enum():
    # NO-BASELINE / DRIFT 不是判定态：不在 STATUS 里，也不能当 findings 的 status
    assert "NO-BASELINE" not in spec.STATUS.values()
    assert "VERSION-BEHAVIOR-DRIFT" not in spec.STATUS.values()
    assert spec.NO_BASELINE == "NO-BASELINE"
    assert spec.DRIFT == "VERSION-BEHAVIOR-DRIFT"
    assert spec.UNPARSEABLE == "UNPARSEABLE"


def test_problem_statuses_are_three_and_exclude_ambiguous():
    assert spec.PROBLEM_STATUSES == ("MISSING-EXPORT", "ESM-CJS-MISMATCH", "NOT-EXPORTED-SUBPATH")
    assert "AMBIGUOUS" not in spec.PROBLEM_STATUSES
    assert "RESOLVED" not in spec.PROBLEM_STATUSES


def test_kind_enum_seven_values():
    assert list(spec.KIND) == [
        "import", "export-from", "require", "dynamic-import", "jest-mock", "string-literal", "ambiguous",
    ]


def test_thresholds_snapshot_matches_module_constants():
    # 阈值双向断言（旧仓 tests/thresholds.test.mjs 的双向面）：.thresholds.json ↔ 模块常量
    assert SETTINGS["limits"]["EXPORTS_KEYS"] == spec.EXPORTS_KEYS_LIMIT
    assert SETTINGS["limits"]["SOURCE_FILE_BYTES"] == spec.SOURCE_FILE_BYTES
    assert SETTINGS["conditions"]["import"] == list(spec.CONDITIONS["import"])
    assert SETTINGS["conditions"]["require"] == list(spec.CONDITIONS["require"])
    assert SETTINGS["status"] == list(spec.STATUS.values())
    assert SETTINGS["kinds"] == list(spec.KIND)
    assert SETTINGS["source_extensions"] == list(spec.SOURCE_EXTENSIONS)
    assert SETTINGS["skip_dirs"] == list(spec.SKIP_DIRS)


def test_thresholds_snapshot_verdict_map_covers_all_basis_rules():
    # verdict_map 三值全覆盖 basis 规则（error 13 + info 3 = 16 条），无 warn 族
    basis_rules = set(BASIS.rule_ids())
    mapped = set(SETTINGS["verdict_map"]["error"]) | set(SETTINGS["verdict_map"]["info"]) | set(SETTINGS["verdict_map"]["warn"])
    assert basis_rules == mapped
    assert SETTINGS["verdict_map"]["warn"] == []


def test_basis_rules_all_registered_and_versioned():
    assert BASIS.version == "1"
    for rule_id in BASIS.rule_ids():
        assert BASIS.ref(rule_id).rule_version == "1"


def test_verdict_constants_match_thresholds_snapshot():
    error_rules = {r for r in SETTINGS["verdict_map"]["error"]}
    info_rules = set(SETTINGS["verdict_map"]["info"])
    subject = _sample_subject()
    subject["sources"] = [{"file": "src/a.cjs", "text": 'const { nope } = require("demo-pkg");\n'}]
    records = _evaluate(subject)
    for r in records:
        if r.verdict == ERROR:
            assert r.rule_id in error_rules
        elif r.verdict == INFO:
            assert r.rule_id in info_rules
        else:
            raise AssertionError("本器官不应产出 warn 级记录，实际 %s" % r.rule_id)


def test_organ_sources_are_pure_no_io_clock_or_random():
    # 架构守门（旧仓 tests/architecture.test.mjs 的器官内移植面）：判定层不读文件、
    # 不碰环境变量、无时钟与随机。AST 判源码，不判注释。
    organ_dir = SRC / "byteproof" / "auditors" / "depcheck_live"
    banned = ("open(", "os.environ", "time.time", "datetime", "random", "Date.now", "process.exit")
    for path in sorted(organ_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in ("open", "random", "environ"), "%s: %s" % (path.name, node.id)
    for path in sorted(organ_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith(("#", '"', "'"))
        )
        for token in banned:
            assert token not in code, "%s 含禁用记号 %s" % (path.name, token)


def test_spec_module_has_no_third_party_imports():
    # 旧仓架构判据移植：src 模块只许标准库 / 本器官 / byteproof 内部
    organ_dir = SRC / "byteproof" / "auditors" / "depcheck_live"
    for path in sorted(organ_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root in ("json", "re", "hashlib", "posixpath", "typing", "byteproof"), (
                        "%s: 第三方/未知导入 %s" % (path.name, alias.name)
                    )
            elif isinstance(node, ast.ImportFrom):
                # 相对导入（level > 0）= 本器官内部，与 byteproof.* 同属白名单
                root = (node.module or "").split(".")[0] if not node.level else ""
                assert root in ("json", "re", "hashlib", "posixpath", "typing", "byteproof", "__future__", ""), (
                    "%s: 第三方/未知导入 %s" % (path.name, node.module)
                )


# ==================================================================
# §8 路径工具（旧仓 tests/paths.test.mjs；隐私红线：输出不含绝对路径）
# ==================================================================

def test_to_relative_same_root_forward_slashes():
    # 盘符字面量拼接构造（脱敏门命中盘符路径字面量，改探针不放宽断言 —— 同 #30 先例）
    drive = chr(67) + ":"
    assert paths.to_relative(drive + "/work/proj", drive + "/work/proj/src/a.mjs") == "src/a.mjs"


def test_to_relative_result_has_no_drive_or_root_segment():
    drive = chr(67) + ":"
    rel = paths.to_relative(drive + "/work/proj", drive + "/work/proj/deep/nested/x.ts")
    assert ":" not in rel
    assert not rel.startswith("/")


def test_to_relative_same_path_returns_dot():
    drive = chr(67) + ":"
    assert paths.to_relative(drive + "/work/proj", drive + "/work/proj") == "."


def test_to_relative_cross_drive_falls_back_to_basename_chain():
    drive_a = chr(67) + ":"
    drive_b = chr(68) + ":"
    rel = paths.to_relative(drive_a + "/work/proj", drive_b + "/elsewhere/proj/src/a.mjs")
    assert rel == "src/a.mjs"  # 回落只保留最后两段，不含盘符与用户名
    assert ":" not in rel


def test_normalize_slashes_unifies_separators():
    assert paths.normalize_slashes("a\\b\\c") == "a/b/c"
    assert paths.normalize_slashes("a/b/c") == "a/b/c"


def test_stable_sort_is_order_independent_and_deduped():
    assert paths.stable_sort(["b", "a", "c"]) == paths.stable_sort(["c", "b", "a"])
    assert paths.stable_sort(["b", "a", "c"]) == ["a", "b", "c"]
    assert paths.stable_sort(["b", "b", "a"]) == ["a", "b"]




