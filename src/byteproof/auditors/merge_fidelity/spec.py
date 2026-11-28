"""口径面（迁自 10-19-merge-fidelity 的模块级常量与状态枚举）。

规则 id 前缀 ``mf-``；判定态词表原样保留（SMUGGLED/DROPPED/RESOLUTION、
PRESENT/MISSING/MODIFIED、REVERT_*），账本 verdict 由三族决定：
事故类（gate 的 FAIL_ON 集合 + parity 的漏搬两态）→ error；
显式记录（RESOLUTION / 跳过 / THEN_REDONE / NO_SUCCESSOR）→ info；
判不了（UNVERIFIED / 交叉核对不一致）→ warn。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

#: 三种模式 = 旧仓三个扫描子命令的判定核（report/gate 的渲染与 TOML 基线面不迁）。
MODES = ("fidelity", "parity", "ledger")
DEFAULT_MODE = "fidelity"

#: fidelity 判定态与默认面（旧仓 fidelity.DEFAULT_KINDS / gate.FAIL_ON_KINDS）。
KIND_SMUGGLED = "SMUGGLED"
KIND_DROPPED = "DROPPED"
KIND_RESOLUTION = "RESOLUTION"
DEFAULT_KINDS = ("SMUGGLED", "DROPPED")
ALL_KINDS = ("SMUGGLED", "DROPPED", "RESOLUTION")

#: git 自带 merge driver；其余视为自定义 driver（fidelity.BUILTIN_MERGE_DRIVERS）。
BUILTIN_MERGE_DRIVERS = frozenset(["text", "binary", "union", "ours"])

#: parity 三态与 basis（旧仓 parity.py）。
STATUS_PRESENT = "PRESENT"
STATUS_MISSING = "MISSING"
STATUS_MODIFIED = "MODIFIED"
BASIS_PATCHID = "patchid"
BASIS_APPLY = "apply"
NOTE_ALREADY_PRESENT = "content_already_present"
NOTE_PARTIAL = "partial_or_context_conflict"
NOTE_OTHER_PATH = "content_equivalent_at_other_path"

#: ledger 三态（旧仓 ledger.py）。
STATUS_NO_SUCCESSOR = "REVERTED_NO_SUCCESSOR"
STATUS_THEN_REDONE = "REVERTED_THEN_REDONE"
STATUS_UNVERIFIED = "REVERT_UNVERIFIED"
REASON_GIT_TOO_OLD = "git_too_old"
CAPABILITY_FIND_OBJECT = "find-object"

#: 只认正文里 git revert 生成的那一行；7–64 位十六进制（短 OID / sha1 / sha256 都覆盖）。
REVERT_MARKER_PATTERN = r"^This reverts commit ([0-9a-f]{7,64})"
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"

#: finding id / digest 口径（旧仓 canonical.py）。
DIGEST_FIELD = "digest"
DIGEST_ALGORITHM = "sha256"
ID_SEPARATOR = "\x1f"

#: 旧仓 report 头的 config_overrides（gitobj.CONFIG_OVERRIDES，留档）。
CONFIG_OVERRIDES = (
    "merge.conflictStyle=diff3",
    "core.abbrev=40",
    "diff.renames=false",
    "diff.context=0",
    "diff.noprefix=false",
    "log.follow=false",
    "gc.auto=0",
    "commit.gpgsign=false",
    "tag.gpgsign=false",
    "core.editor=true",
)
