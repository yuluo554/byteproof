"""口径面：规则 id、默认严重度表、阈值常量与模式集合。

数值口径照搬旧仓 ``src/rules/range-lint.mjs`` / ``src/checks/lock-manifest.mjs`` /
``src/checks/dedupe.mjs`` / ``src/checks/conflict.mjs`` 的 ``SEVERITY_FALLBACK``，
以及 ``src/mus/minimal-set.mjs`` 的默认 ``maxRequesters = 12``。
规则 id 前缀 ``va-``；严重度三值（error/warning/info）直接映射账本 verdict。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

#: 旧仓 CLI 的六个子命令；``doctor`` 是输入可读性诊断（输入层），器官不收。
MODES = ("audit", "range-lint", "lock-manifest", "dedupe", "conflict")
DEFAULT_MODE = "audit"

MAX_REQUESTERS = 12

#: R1–R8 默认严重度（旧仓 ``SEVERITY_FALLBACK``）。
R_SEVERITY = {
    "R1": "warning",
    "R2": "warning",
    "R3": "info",
    "R4": "warning",
    "R5": "error",
    "R6": "warning",
    "R7": "info",
    "R8": "info",
}

#: M2 双向一致性的默认严重度（旧仓 ``SEVERITY_FALLBACK``）。
LOCK_SEVERITY = {
    "manifest-not-satisfied": "error",
    "missing-from-lock": "error",
    "manifest-changed-unsynced": "error",
    "lock-extra-undeclared": "warning",
    "lock-outdated": "warning",
}

#: M3 三态的默认严重度。
DEDUPE_SEVERITY = {
    "CONVERGIBLE": "info",
    "NOT_CONVERGIBLE": "error",
    "REQUIRES_OVERRIDE": "warning",
}

#: M4 冲突的默认严重度。
CONFLICT_SEVERITY = {
    "peer-conflict": "error",
    "version-conflict": "error",
}

SEVERITY_FALLBACK = {}
SEVERITY_FALLBACK.update(R_SEVERITY)
SEVERITY_FALLBACK.update(LOCK_SEVERITY)
SEVERITY_FALLBACK.update(DEDUPE_SEVERITY)
SEVERITY_FALLBACK.update(CONFLICT_SEVERITY)

# ------------------------------------------------------------------ 规则
RULE_R1 = "va-r1-unbounded"
RULE_R2 = "va-r2-wildcard"
RULE_R3 = "va-r3-zero-shrink"
RULE_R4 = "va-r4-prerelease-unreachable"
RULE_R5 = "va-r5-empty-intersection"
RULE_R6 = "va-r6-branch-redundant"
RULE_R7 = "va-r7-build-metadata"
RULE_R8 = "va-r8-bare-version"

RULE_MANIFEST_NOT_SATISFIED = "va-manifest-not-satisfied"
RULE_MISSING_FROM_LOCK = "va-missing-from-lock"
RULE_MANIFEST_CHANGED_UNSYNCED = "va-manifest-changed-unsynced"
RULE_LOCK_EXTRA_UNDECLARED = "va-lock-extra-undeclared"
RULE_LOCK_OUTDATED = "va-lock-outdated"
RULE_LOCK_ENTRY_NO_VERSION = "va-lock-entry-no-version"

RULE_CONVERGIBLE = "va-convergible"
RULE_REQUIRES_OVERRIDE = "va-requires-override"
RULE_NOT_CONVERGIBLE = "va-not-convergible"

RULE_PEER_CONFLICT = "va-peer-conflict"
RULE_VERSION_CONFLICT = "va-version-conflict"

RULE_SUMMARY = "va-summary"

#: 旧仓 severity 三值词 -> 账本 verdict 三值词。
SEVERITY_TO_VERDICT = {"error": "error", "warning": "warn", "info": "info"}

#: 器官根标记（旧仓 lock-common.mjs 的 ROOT_MARKER）。
ROOT_MARKER = "<root>"

#: 每条规则 id -> 旧仓来源（默认严重度）。verdict 由 SEVERITY_FALLBACK 决定。
RULE_IDS = (
    RULE_R1,
    RULE_R2,
    RULE_R3,
    RULE_R4,
    RULE_R5,
    RULE_R6,
    RULE_R7,
    RULE_R8,
    RULE_MANIFEST_NOT_SATISFIED,
    RULE_MISSING_FROM_LOCK,
    RULE_MANIFEST_CHANGED_UNSYNCED,
    RULE_LOCK_EXTRA_UNDECLARED,
    RULE_LOCK_OUTDATED,
    RULE_LOCK_ENTRY_NO_VERSION,
    RULE_CONVERGIBLE,
    RULE_REQUIRES_OVERRIDE,
    RULE_NOT_CONVERGIBLE,
    RULE_PEER_CONFLICT,
    RULE_VERSION_CONFLICT,
    RULE_SUMMARY,
)

#: 规则 id -> 名义 verdict（severity 词经 SEVERITY_TO_VERDICT 折成账本三值）。
VERDICTS = {
    RULE_R1: SEVERITY_TO_VERDICT[R_SEVERITY["R1"]],
    RULE_R2: SEVERITY_TO_VERDICT[R_SEVERITY["R2"]],
    RULE_R3: SEVERITY_TO_VERDICT[R_SEVERITY["R3"]],
    RULE_R4: SEVERITY_TO_VERDICT[R_SEVERITY["R4"]],
    RULE_R5: SEVERITY_TO_VERDICT[R_SEVERITY["R5"]],
    RULE_R6: SEVERITY_TO_VERDICT[R_SEVERITY["R6"]],
    RULE_R7: SEVERITY_TO_VERDICT[R_SEVERITY["R7"]],
    RULE_R8: SEVERITY_TO_VERDICT[R_SEVERITY["R8"]],
    RULE_MANIFEST_NOT_SATISFIED: SEVERITY_TO_VERDICT[LOCK_SEVERITY["manifest-not-satisfied"]],
    RULE_MISSING_FROM_LOCK: SEVERITY_TO_VERDICT[LOCK_SEVERITY["missing-from-lock"]],
    RULE_MANIFEST_CHANGED_UNSYNCED: SEVERITY_TO_VERDICT[LOCK_SEVERITY["manifest-changed-unsynced"]],
    RULE_LOCK_EXTRA_UNDECLARED: SEVERITY_TO_VERDICT[LOCK_SEVERITY["lock-extra-undeclared"]],
    RULE_LOCK_OUTDATED: SEVERITY_TO_VERDICT[LOCK_SEVERITY["lock-outdated"]],
    RULE_LOCK_ENTRY_NO_VERSION: "info",
    RULE_CONVERGIBLE: SEVERITY_TO_VERDICT[DEDUPE_SEVERITY["CONVERGIBLE"]],
    RULE_REQUIRES_OVERRIDE: SEVERITY_TO_VERDICT[DEDUPE_SEVERITY["REQUIRES_OVERRIDE"]],
    RULE_NOT_CONVERGIBLE: SEVERITY_TO_VERDICT[DEDUPE_SEVERITY["NOT_CONVERGIBLE"]],
    RULE_PEER_CONFLICT: SEVERITY_TO_VERDICT[CONFLICT_SEVERITY["peer-conflict"]],
    RULE_VERSION_CONFLICT: SEVERITY_TO_VERDICT[CONFLICT_SEVERITY["version-conflict"]],
    RULE_SUMMARY: "info",
}

#: M1 规则号（R1–R8）到器官规则 id 的映射。
RULE_BY_LINT = {
    "R1": RULE_R1,
    "R2": RULE_R2,
    "R3": RULE_R3,
    "R4": RULE_R4,
    "R5": RULE_R5,
    "R6": RULE_R6,
    "R7": RULE_R7,
    "R8": RULE_R8,
}

#: M2 kind 到器官规则 id 的映射。
RULE_BY_LOCK = {
    "manifest-not-satisfied": RULE_MANIFEST_NOT_SATISFIED,
    "missing-from-lock": RULE_MISSING_FROM_LOCK,
    "manifest-changed-unsynced": RULE_MANIFEST_CHANGED_UNSYNCED,
    "lock-extra-undeclared": RULE_LOCK_EXTRA_UNDECLARED,
    "lock-outdated": RULE_LOCK_OUTDATED,
}
