"""M1 ``range-lint`` —— 范围语义规则 R1–R8（照搬旧仓 ``src/rules/range-lint.mjs``）。

纪律（照搬）：
  - ``expanded_range`` 一律来自 :func:`semver_core.valid_range` 实调，不手写近似；
  - 每条 finding 带 ``evidence``（可复算的字符串）；
  - R8 默认关闭（无法从文件推断作者意图）。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from . import semver_core
from .interval import is_sentinel, normalize_range, range_is_empty
from .spec import R_SEVERITY, SEVERITY_TO_VERDICT


def _lint_severity(rule: str, severity_table: Optional[Dict]) -> str:
    if severity_table and rule in severity_table:
        return severity_table[rule]
    return R_SEVERITY.get(rule, "info")


def check_r1(raw_range: str, expanded) -> Optional[Dict]:
    """R1：展开结果里有 ``>=``/``>`` 且没有任何 ``<`` 上界。"""
    if expanded is None:
        return None
    branches = [b.strip() for b in expanded.split("||")]
    offending = [b for b in branches if _RE_GE_GT.search(b) and not _RE_LT.search(b)]
    if not offending:
        return None
    return {
        "evidence": "validRange(%s) = %s；分支 %s 无上界"
        % (semver_core.quote(raw_range), semver_core.quote(expanded), " | ".join(offending)),
    }


def check_r2(raw_range: str, expanded) -> Optional[Dict]:
    """R2：``*`` / 空串 / ``x`` / ``latest``。``latest`` 必须判"非范围"，不是"宽范围"。"""
    if raw_range == "latest":
        return {
            "evidence": "validRange('latest') = null → 它是 npm dist-tag，不是 semver 范围",
            "not_a_range": True,
        }
    if raw_range.strip() == "" or _RE_X_TOKEN.match(raw_range.strip()) or expanded == "*":
        return {"evidence": "validRange(%s) = \"*\"（无任何约束）" % semver_core.quote(raw_range)}
    return None


def check_r3(raw_range: str, expanded) -> Optional[Dict]:
    """R3：``^0.x.y`` / ``^0.0.y`` / ``~0.x.y`` 的语义收窄（以展开结果证明，不看字面）。

    判据 = raw 以 ``^``/``~`` 起头、主版本为 0，且展开后的**上界被收窄到 0.x 内的小步进**。
    只看上界（下界缺省不影响"上界被收窄"这一事实；``^0.0`` 族展开无下界）。
    """
    if expanded is None:
        return None
    head = _RE_CARET_HEAD.match(raw_range.strip())
    if not head or int(head.group(2)) != 0:
        return None
    norm = normalize_range(raw_range)
    if not norm:
        return None
    shrink = []
    for b in norm["branches"]:
        hi_v = b["hi"][0]
        if _is_inf_bound(hi_v) or hi_v[0] != 0:
            continue
        _, minor, patch = hi_v
        if (minor >= 1 and patch == 0) or (minor == 0 and patch >= 1):
            shrink.append(b)
    if not shrink:
        return None
    return {
        "evidence": "validRange(%s) = %s（上界被收窄到 0.x 的小步进内）"
        % (semver_core.quote(raw_range), semver_core.quote(expanded)),
    }


def check_r4(raw_range: str, targets) -> Optional[Dict]:
    """R4：预发布可达性。要求给出目标版本才能判"不可达"；区分两态。"""
    expanded = semver_core.valid_range(raw_range)
    if expanded is None or not targets:
        return None
    results = []
    for target in targets:
        if not target.get("is_prerelease"):
            continue
        if semver_core.satisfies(target["version"], raw_range):
            continue
        base = "%d.%d.%d" % (target["major"], target["minor"], target["patch"])
        base_ok = semver_core.satisfies(base, raw_range)
        results.append(
            {
                "target": target["version"],
                "reason": "prerelease-unreachable" if base_ok else "target-not-in-candidate",
            }
        )
    if not results:
        return None
    return {
        "evidence": "；".join(
            "satisfies(%s, %s) = false（%s）" % (semver_core.quote(r["target"]), semver_core.quote(raw_range), r["reason"])
            for r in results
        ),
        "details": results,
    }


def check_r5(raw_range: str) -> Optional[Dict]:
    """R5：范围内部空交集。"""
    empty = range_is_empty(raw_range)
    if empty is True:
        return {
            "evidence": "validRange(%s) 展开后无任何可满足版本（区间为空）"
            % semver_core.quote(raw_range)
        }
    return None


def check_r6(raw_range: str) -> Optional[Dict]:
    """R6：``||`` 分支冗余 / 被包含。

    **必须按原始字符串切分支**（``* || ^1.0.0`` 会被库折叠成单分支）；展开结果只用于 subset 判定。
    """
    if "||" not in raw_range:
        return None
    raw_branches = [b.strip() for b in raw_range.split("||") if b.strip()]
    if len(raw_branches) < 2:
        return None
    branches = [{"raw": b, "expanded": semver_core.valid_range(b) or "*"} for b in raw_branches]
    redundant = []
    for i, branch in enumerate(branches):
        for j, other in enumerate(branches):
            if i == j:
                continue
            covered = _subset_safe(branch["expanded"], other["expanded"])
            if covered:
                redundant.append({"branch": branch["raw"], "covered_by": other["raw"]})
    if not redundant:
        return None
    return {
        "evidence": "；".join(
            "subset(validRange(%s), validRange(%s)) = true"
            % (semver_core.quote(r["branch"]), semver_core.quote(r["covered_by"]))
            for r in redundant
        ),
        "details": redundant,
    }


def check_r7(raw_range: str) -> Optional[Dict]:
    """R7：build metadata（``+…``）不提供任何额外约束。"""
    if "+" not in raw_range:
        return None
    stripped = _RE_BUILD_STRIP.sub("", raw_range)
    a = semver_core.valid_range(raw_range)
    b = semver_core.valid_range(stripped)
    if a is None or b is None or a != b:
        return None
    return {
        "evidence": "validRange(%s) = validRange(%s) = %s：build metadata 不参与比较"
        % (semver_core.quote(raw_range), semver_core.quote(stripped), semver_core.quote(a))
    }


def check_r8(raw_range: str) -> Optional[Dict]:
    """R8：裸版本跨生态误用（默认关闭）。"""
    if not _RE_BARE_VERSION.match(raw_range.strip()):
        return None
    expanded = semver_core.valid_range(raw_range)
    return {
        "evidence": "npm 中 %s 是精确锁定（validRange = %s）；Cargo 中同样的字符是 caret 语义"
        % (semver_core.quote(raw_range), semver_core.quote(expanded))
    }


_RE_GE_GT = __import__("re").compile(r"(^|\s)(>=|>)")
_RE_LT = __import__("re").compile(r"(<)")
_RE_X_TOKEN = __import__("re").compile(r"^[xX*]$")
_RE_CARET_HEAD = __import__("re").compile(r"^([\^~])\s*v?(\d+)")
_RE_BUILD_STRIP = __import__("re").compile(r"\+[0-9A-Za-z.-]+")
_RE_BARE_VERSION = __import__("re").compile(r"^\d+\.\d+\.\d+$")


def _is_inf_bound(v) -> bool:
    return is_sentinel(v)


def _subset_safe(sub: str, dom: str) -> bool:
    try:
        return semver_core.subset(sub, dom)
    except Exception:
        return False


def _quote(value) -> str:
    return semver_core.quote(value)


def quote(value) -> str:
    return semver_core.quote(value)


def run_range_lint(
    manifest: dict,
    declarations: Iterable[dict],
    severity_table: Optional[Dict] = None,
    enable_r8: bool = False,
    prerelease_targets: Optional[Dict[str, List[dict]]] = None,
) -> List[Dict]:
    """跑 R1–R8。``declarations`` 是输入层展平的 ``{kind, name, raw_range}`` 列表。

    每条 finding：``{rule, package, declaration, raw_range, expanded_range, severity,
    verdict, evidence, details?, not_a_range?}``。R2 判"非范围"时其余基于展开的规则不再适用。
    """
    table = severity_table or {}
    findings: List[Dict] = []
    prerelease_targets = prerelease_targets or {}

    for decl in declarations:
        name = decl["name"]
        raw_range = decl["raw_range"]
        expanded = semver_core.valid_range(raw_range)
        base = {
            "package": name,
            "declaration": decl["kind"],
            "raw_range": raw_range,
            "expanded_range": expanded,
        }

        def push(rule: str, hit: Dict) -> None:
            severity = _lint_severity(rule, table)
            finding = dict(base)
            finding["rule"] = rule
            finding["severity"] = severity
            finding["verdict"] = SEVERITY_TO_VERDICT[severity]
            finding["evidence"] = hit["evidence"]
            if hit.get("details") is not None:
                finding["details"] = hit["details"]
            if hit.get("not_a_range"):
                finding["not_a_range"] = True
            findings.append(finding)

        r2 = check_r2(raw_range, expanded)
        if r2:
            push("R2", r2)

        if not r2 or not r2.get("not_a_range"):
            r1 = check_r1(raw_range, expanded)
            if r1:
                push("R1", r1)
            r3 = check_r3(raw_range, expanded)
            if r3:
                push("R3", r3)
            r5 = check_r5(raw_range)
            if r5:
                push("R5", r5)
            r6 = check_r6(raw_range)
            if r6:
                push("R6", r6)
            r7 = check_r7(raw_range)
            if r7:
                push("R7", r7)
            if enable_r8:
                r8 = check_r8(raw_range)
                if r8:
                    push("R8", r8)
            # R4 需要目标版本（来自锁），按名字传入
            targets = prerelease_targets.get(name, [])
            r4 = check_r4(raw_range, targets)
            if r4:
                push("R4", r4)

    return sort_findings(findings)


def sort_findings(findings: List[Dict]) -> List[Dict]:
    """稳定排序：rule → package → declaration → raw_range（照搬旧仓）。"""
    return sorted(
        findings,
        key=lambda f: (f["rule"], f["package"], f["declaration"], f["raw_range"]),
    )
