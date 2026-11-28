"""口径面：规则 id、名义 verdict、模式与常量（迁自 10-19-circuit-detective core）。

旧仓是纯前端游戏（无 CLI 退出码）；「提交判定」通过/不通过映射为本账本
0（无阻断）/ 1（存在阻断）——通过 = accepted 且探测回放一致；不通过 = 结构无效 /
不稳定 / 有未知 / 真值表不匹配。规则 id 前缀 ``cd-``。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

MODES = ("audit", "judge", "simulate", "generate", "replay", "solve")
DEFAULT_MODE = "judge"

MAX_SOLVER_GATES = 12
MAX_DRAFT_GATES = 12
MAX_SIGNALS = 16
SIGNAL_BITS = 4
RECORD_VERSION = 1
MAX_CODE_LENGTH = 64
MAX_REDRAWS = 64
DEFAULT_MAX_GATES = 12
LEVEL_FORMAT = "circuit-detective/level"
LEVEL_VERSION = 1
GATE_BASIS = ("NOT", "AND", "OR")
GATE_TYPES = ("NOT", "AND", "OR")
GATE_ARITY = {"NOT": 1, "AND": 2, "OR": 2}
X = 2
GRID = 32
DIFFICULTY_BANDS = (("easy", 2), ("normal", 4), ("hard", 12))

RULE_SETTLEMENT = "cd-settlement"
RULE_MISMATCH = "cd-mismatch"
RULE_DRAFT_INVALID = "cd-draft-invalid"
RULE_PROBES_REPLAY = "cd-probes-replay"
RULE_LEVEL_GENERATION = "cd-level-generation"
RULE_SIM_DIAGNOSTIC = "cd-sim-diagnostic"
RULE_REVEAL_PLAN = "cd-reveal-plan"
RULE_SUMMARY = "cd-summary"

RULE_IDS = (
    RULE_SETTLEMENT,
    RULE_MISMATCH,
    RULE_DRAFT_INVALID,
    RULE_PROBES_REPLAY,
    RULE_LEVEL_GENERATION,
    RULE_SIM_DIAGNOSTIC,
    RULE_REVEAL_PLAN,
    RULE_SUMMARY,
)

VERDICTS = {
    RULE_SETTLEMENT: "info",
    RULE_MISMATCH: "error",
    RULE_DRAFT_INVALID: "error",
    RULE_PROBES_REPLAY: "error",
    RULE_LEVEL_GENERATION: "info",
    RULE_SIM_DIAGNOSTIC: "info",
    RULE_REVEAL_PLAN: "info",
    RULE_SUMMARY: "info",
}

SETTLEMENT_BASIS_LABEL = "按每个灯单独计零件（共用的零件每个灯各算一次）"
