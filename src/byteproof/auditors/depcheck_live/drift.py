"""模块 ④ · 版本行为漂移（drift，1:1 移植自旧仓 ``src/drift.mjs``）。

判据（旧仓 ``plan/03`` §5 + ``data/README.md`` §5.5）：
  · 只在**有离线基线**时判定；无基线记 ``NO-BASELINE``，**不得猜测**；
  · ``NO-BASELINE`` 不是"发现问题"（不进 problems），但进 gaps（退出码 3，"基准缺失"）；
  · 基线来源 = 旧仓 ``data/fingerprints/<pkg>.json``（生成器 ``tools/gen-baselines.mjs`` 的产物），
    工具**不联网**、**不自己造历史版本**。基线文件由输入层读出放进 subject 的
    ``baselines`` 映射（键缺省或值为 null = 无基线/读不出，**不猜**）。

★ 两条口径，别改（改了旧仓 C6 必红，且都是实测结论）：

① **判据是行为，不是版本号。** ``drift`` = "代码引用的这个符号，基线版本里有、已装版本里没有"。
   装了更高 major 但符号还在 → **不是**漂移（防"版本号一变大就报红"）。

② **判定单位是引用点，不是整包。** 不能用"这个包有没有变"当判据：
   实测 date-fns 3.6.0 → 4.4.0 的根导出面 251 个名字**一个不少**（只加不减），
   而整份 ``exports`` 指纹必然不同——按包比指纹是**系统性假阳性**。
   同理 zod 4 移除了 ``ZodSchema`` 等 31 个符号，但同一包里 ``z``/``ZodError`` 仍在，
   按包比会把"用的是还在的符号"也判红。逐点判才判得出 1 红 1 绿。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .check import read_export_surface, split_specifier
from .resolve import CONDITIONS, match_subpath, resolve_conditional, substitute_wildcard
from .spec import DRIFT, NO_BASELINE


def drift_all(deps: Mapping[str, Mapping[str, Any]], points: List[Mapping[str, Any]],
              baselines: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """对引用点做漂移判定。

    ``deps`` 包名 → 依赖面记录（需带 ``index`` 与 ``files``）；``baselines`` 包名 →
    基线 JSON 值（无基线/读不出 = 键缺省或 None）。返回每条对应一个引用点的结论；
    不在判定面内的点（动态/非依赖/不取符号）不出现在结果里。
    """
    out: List[Dict[str, Any]] = []
    for point in points:
        judged = judge_drift_point(point, deps, baselines)
        if judged is None:
            continue  # 不在判定面内（动态/非依赖/不取符号）
        out.append(judged)
    return out


def judge_drift_point(point: Mapping[str, Any], deps: Mapping[str, Mapping[str, Any]],
                      baselines: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """单引用点的漂移判定。返回 ``None`` 表示"这个点不在 drift 判定面内"。"""
    # 动态形态：specifier 都抽不出，更谈不上"它引用的老 API 还在不在"
    if point.get("kind") == "ambiguous" or point.get("specifier") is None:
        return None
    split = split_specifier(point["specifier"])
    if split is None or split["name"] not in deps:
        return None

    record = deps[split["name"]]
    wanted = [s for s in (point.get("imported") or []) if s != "*" and s != ""]
    # 只加载包、不取符号 → drift 这一层无判据（"包还在不在"是 exports 解析层的事）
    if len(wanted) == 0:
        return None

    base = {"pkg": split["name"], "file": point["file"], "line": point["line"], "specifier": point["specifier"]}
    baseline = _validate_baseline(baselines.get(split["name"]))

    # ① 没有离线基线 → 不猜（进 gaps，退出码 3）
    if baseline is None:
        return {
            **base,
            "status": NO_BASELINE,
            "installedVersion": record.get("installedVersion"),
            "declaredRange": record.get("declaredRange"),
            "detail": "无离线基线（%s@%s），不猜" % (split["name"], record.get("installedVersion") or "<未安装>"),
            "why": "基线映射里没有该包的历史版本导出面（或文件读不出/形状不对）",
        }

    # ② 装的就是基线版本 → 同一份导出面，漂移不可成立（这不是"猜"，是恒等式）
    installed = record.get("installedVersion")
    if installed and baseline["baselineVersion"] == installed:
        return {
            **base,
            "status": None,
            "installedVersion": installed,
            "baselineVersion": baseline["baselineVersion"],
            "detail": "已装版本即基线版本 %s，无漂移可比" % baseline["baselineVersion"],
        }

    view = "require" if point.get("kind") == "require" else "import"
    baseline_names = _surface_names(baseline, split["subpath"], view)
    if baseline_names is None:
        # 基线的这个子路径/视角没有记录 → 比不了，记算不了（**不**当成"没变"）
        return {
            **base,
            "status": NO_BASELINE,
            "installedVersion": installed,
            "baselineVersion": baseline["baselineVersion"],
            "detail": "基线 %s 未收录 %s 的 %s 视角导出面，不猜" % (
                baseline["baselineVersion"], split["subpath"], view,
            ),
        }

    installed_names = _installed_surface_names(record, split["subpath"], view)
    if installed_names is None:
        return {
            **base,
            "status": NO_BASELINE,
            "installedVersion": installed,
            "baselineVersion": baseline["baselineVersion"],
            "detail": "已装 %s 的 %s（%s）导出面读不出，不猜" % (
                installed, split["subpath"], view,
            ),
        }

    # ③ 只判"基线里有、已装里没有"的那些**本点实际引用的**符号。
    #    基线里本来也没有的符号不归 drift 管（那是 MISSING-EXPORT 的判据，不重复判）。
    missing = [sym for sym in wanted if sym in baseline_names and sym not in installed_names]
    if len(missing) > 0:
        return {
            **base,
            "status": DRIFT,
            "installedVersion": installed,
            "baselineVersion": baseline["baselineVersion"],
            "declaredRange": record.get("declaredRange"),
            "subpath": split["subpath"],
            "missing": sorted(missing),
            "detail": "声明 range %s，基线 %s 有这些导出、已装 %s 没有了" % (
                record.get("declaredRange") or "<未声明>", baseline["baselineVersion"], installed,
            ),
            "rule": "旧仓 plan/03 §5：判据是符号行为，不是 semver 字符串",
        }

    return {
        **base,
        "status": None,
        "installedVersion": installed,
        "baselineVersion": baseline["baselineVersion"],
        "subpath": split["subpath"],
        "detail": "基线 %s 与已装 %s 都有本点引用的符号" % (baseline["baselineVersion"], installed),
    }


def _validate_baseline(value: Any) -> Optional[Dict[str, Any]]:
    """基线形状校验。**读不出/形状不对一律按无基线（不猜，不崩）**（旧仓 ``readBaseline``）。

    旧仓读文件后校验：非对象 / 缺 ``baselineVersion`` 字符串 / 缺 ``surfaces`` 对象 → null。
    文件缺失与 JSON 坏由输入层映射为 None。
    """
    if value is None or isinstance(value, (str, int, float, bool, list)):
        return None
    if not isinstance(value, dict):
        return None
    baseline_version = value.get("baselineVersion")
    surfaces = value.get("surfaces")
    if not isinstance(baseline_version, str):
        return None
    if not isinstance(surfaces, dict):
        return None
    return value


def _surface_names(baseline: Mapping[str, Any], subpath: str, view: str) -> Optional[frozenset]:
    """基线里某子路径某视角的符号集合；未收录或读不出返回 None。"""
    views = baseline.get("surfaces", {}).get(subpath) if isinstance(baseline.get("surfaces"), dict) else None
    if not views:
        return None
    names = views.get(view) if isinstance(views, dict) else None
    if names is None or not isinstance(names, list):
        # None = 该视角"读不出"（基线生成器如实记录），不是"没有符号"
        return None
    return frozenset(names)


def _installed_surface_names(record: Mapping[str, Any], subpath: str, view: str) -> Optional[frozenset]:
    """已装包某子路径某视角的符号集合；读不出返回 None（复用 check 的口径，不另写解析）。"""
    if "index" not in record or "files" not in record:
        return None
    sub = match_subpath(record["index"], subpath)
    if sub["kind"] == "none":
        return None
    value = substitute_wildcard(sub["key"], subpath, sub["value"]) if sub["kind"] == "pattern" else sub["value"]
    target = resolve_conditional(value, CONDITIONS[view])
    if target["state"] != "ok":
        return None
    surface = read_export_surface(record, target["target"])
    return surface["names"] if surface["ok"] else None
