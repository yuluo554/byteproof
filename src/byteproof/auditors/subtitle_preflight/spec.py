"""口径面（迁自 10-19-subtitle-preflight 的 ``data/ruleset.v1.json`` 与七个判定模块常量）。

规则 id **原样保留**旧仓的 ``timing.*`` / ``readability.*`` / ``hygiene.*`` 命名（账本
``rule_id`` 与旧报告 ``ruleId`` 逐字一致，便于真值对账）；新增三条器官级规则：
``decode.*`` 诊断（旧仓 ``diagnostics[]`` 的 code 直接当规则 id）、``fix.*``（旧仓
``fixes[].ruleId``，其中行尾空白在旧仓是 ``ruleId: null``）、``sp-skipped`` /
``sp-summary``（旧仓 ``skipped[]`` / 报告 summary 的账本化承载）。

**阈值只有这一份**（旧仓 K1「阈值只在 data/README.md §4 定义一次」）：本文件的
``THRESHOLDS`` 是唯一可读来源，``byteproof/data/subtitle-preflight.thresholds.json``
是同一份的快照（测试双向断言逐键相等）；``core.py`` / ``api.py`` 不出现数值阈值字面量
（架构测试钉住）。
"""

from __future__ import annotations

from typing import Dict, Tuple

ORGAN_VERSION = "1"

#: 五种判定模式 + ``all``（= 旧仓 pipeline.runOne 的判定面组合）。
MODES = ("timing", "readability", "hygiene", "decode", "fix", "all")
DEFAULT_MODE = "all"

#: 旧仓 ``report.schemaVersion`` / ``report.rulesetVersion``（随包口径版本，进 summary）。
SCHEMA_VERSION = 2
RULESET_VERSION = 1

# ---------------------------------------------------------------- 规则清单
#: 时序 T01–T12（旧仓 ``core/rules/timing.js`` + ``core/rules/drift.js``）。
TIMING_RULES: Tuple[str, ...] = (
    "timing.overlap",
    "timing.zero-duration",
    "timing.negative-duration",
    "timing.gap-too-small",
    "timing.non-monotonic",
    "timing.duplicate-cue",
    "timing.negative-start",
    "timing.past-media-end",
    "timing.unparsable-timecode",
    "timing.file-order-mismatch",
    "timing.timecode-precision",
    "timing.fps-drift",
)

#: 可读性 R01–R07（旧仓 ``core/rules/readability.js``）。
READABILITY_RULES: Tuple[str, ...] = (
    "readability.cps",
    "readability.line-length",
    "readability.too-many-lines",
    "readability.too-few-chars",
    "readability.duration-short",
    "readability.duration-long",
    "readability.repeated-text",
)

#: 卫生 S01–S10（旧仓 ``core/rules/hygiene.js``）。
HYGIENE_RULES: Tuple[str, ...] = (
    "hygiene.cjk-latin-spacing",
    "hygiene.punctuation-width",
    "hygiene.trailing-punctuation",
    "hygiene.unclosed-tag",
    "hygiene.ass-override-residue",
    "hygiene.placeholder-residue",
    "hygiene.font-tag-residue",
    "hygiene.sdh-marker",
    "hygiene.all-caps",
    "hygiene.repeated-punctuation",
)

#: 编码面（旧仓 ``core/decode.js`` 的诊断 code 即规则 id）。
DECODE_RULES: Tuple[str, ...] = (
    "decode.invalid-utf8",
    "decode.invalid-utf16",
    "decode.gbk-fallback",
    "decode.lossy",
    "decode.mixed-eol",
)

#: 修复面（旧仓 ``core/fix.js``；行尾空白在旧仓 ``ruleId: null``，这里登记显式键）。
FIX_RULES: Tuple[str, ...] = (
    "fix.trim-overlap",
    "fix.fill-gap",
    "fix.strip-trailing-space",
    "fix.close-tag",
    "fix.renumber-index",
)

SUMMARY_RULE = "sp-summary"
SKIPPED_RULE = "sp-skipped"

ALL_RULES: Tuple[str, ...] = (
    TIMING_RULES + READABILITY_RULES + HYGIENE_RULES + DECODE_RULES + FIX_RULES
    + (SKIPPED_RULE, SUMMARY_RULE)
)

#: 旧仓 finding severity（``error`` / ``warn``）与修复记录（``info``）→ 账本 verdict。
SEVERITY: Dict[str, str] = {
    "timing.overlap": "error",
    "timing.zero-duration": "error",
    "timing.negative-duration": "error",
    "timing.gap-too-small": "error",
    "timing.non-monotonic": "error",
    "timing.duplicate-cue": "warn",
    "timing.negative-start": "error",
    "timing.past-media-end": "error",
    "timing.unparsable-timecode": "error",
    "timing.file-order-mismatch": "warn",
    "timing.timecode-precision": "warn",
    "timing.fps-drift": "warn",
    "readability.cps": "error",
    "readability.line-length": "error",
    "readability.too-many-lines": "error",
    "readability.too-few-chars": "error",
    "readability.duration-short": "warn",
    "readability.duration-long": "warn",
    "readability.repeated-text": "warn",
    "hygiene.cjk-latin-spacing": "warn",
    "hygiene.punctuation-width": "warn",
    "hygiene.trailing-punctuation": "warn",
    "hygiene.unclosed-tag": "error",
    "hygiene.ass-override-residue": "error",
    "hygiene.placeholder-residue": "error",
    "hygiene.font-tag-residue": "error",
    "hygiene.sdh-marker": "error",
    "hygiene.all-caps": "warn",
    "hygiene.repeated-punctuation": "warn",
    "decode.invalid-utf8": "warn",
    "decode.invalid-utf16": "warn",
    "decode.gbk-fallback": "warn",
    "decode.lossy": "error",
    "decode.mixed-eol": "info",
    "fix.trim-overlap": "info",
    "fix.fill-gap": "info",
    "fix.strip-trailing-space": "info",
    "fix.close-tag": "info",
    "fix.renumber-index": "info",
    SKIPPED_RULE: "info",
    SUMMARY_RULE: "info",
}

#: 旧仓 ``timing.js`` 的 ``IMPLEMENTED`` 集合（规则清单即实现清单，逐条可核）。
IMPLEMENTED: Dict[str, Tuple[str, ...]] = {
    "timing": TIMING_RULES,
    "readability": READABILITY_RULES,
    "hygiene": HYGIENE_RULES,
}

# ---------------------------------------------------------------- 计数单位
#: 千分字符换算基数（旧仓口径 §4.3 的**计数单位**，不是阈值）：全角 1000 / 半角 500。
FULL_MILLI = 1000
HALF_MILLI = 500

#: 全角码点区间（旧仓 ``FULL_RANGES`` 逐区间保留；区间外一律按半角计）。
FULL_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x1100, 0x115F),
    (0x2E80, 0x303E),
    (0x3041, 0x33FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xA000, 0xA4CF),
    (0xAC00, 0xD7A3),
    (0xF900, 0xFAFF),
    (0xFE30, 0xFE4F),
    (0xFF01, 0xFF60),
    (0xFFE0, 0xFFE6),
    (0x20000, 0x2FFFD),
    (0x30000, 0x3FFFD),
)

#: 假名区间（旧仓 ``KANA_RE``）。
KANA_LO, KANA_HI = 0x3041, 0x30FF

#: 卫生规则的 CJK / 汉字区间（旧仓 ``CJK`` / ``HAN``）。
CJK_RANGES: Tuple[Tuple[int, int], ...] = (
    (0x2E80, 0x303E),
    (0x3041, 0x33FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
)
HAN_LO, HAN_HI = 0x4E00, 0x9FFF

#: 旧仓 ``fix.js`` 的定点单位：毫秒 → 微毫秒。
MICRO_PER_MS = 1000
SCALE_UNIT = 1000000

# ---------------------------------------------------------------- 阈值（唯一来源）
#: 键名与旧仓 ``data/ruleset.v1.json`` **逐键对应**（快照测试双向断言）。
THRESHOLDS: Dict[str, object] = {
    "cps.zh": 9,
    "cps.en": 17,
    "cps.ja": 9,
    "line.maxWidthFull": 16,
    "line.maxWidthHalf": 42,
    "line.maxLines": 2,
    "line.minChars": 2,
    "duration.min": 800,
    "duration.max": 7000,
    "timing.gapMin": 80,
    "drift.offsetRange": [-30000, 30000],
    "drift.offsetStepCoarse": 100,
    "drift.offsetStepFine": 5,
    "drift.scaleRange": [0.9, 1.1],
    "drift.scaleStepCoarse": 0.001,
    "drift.scaleStepFine": 0.00005,
    "drift.residualMaxMs": 40,
    "drift.gridToleranceMs": 1,
    "drift.minSamples": 20,
    "hygiene.allCapsMinLength": 20,
    "hygiene.repeatPunctMin": 3,
}

#: 卫生白名单（旧仓 ``hygiene.whitelist``；命中次数进 summary，不静默）。
WHITELIST: Tuple[str, ...] = ("iPhone", "iPad", "macOS", "iOS", "e.g.", "i.e.", "etc.", "♪")

#: 旧仓 ``report.sortKeys``（finding 排序口径；账本另有确定性排序，见 docs §7）。
SORT_KEYS: Tuple[str, ...] = ("line", "ruleId")

#: skipped 理由词表（旧仓 ``skipped[].reason``；逐条进 info 记录，不静默）。
SKIP_REASONS: Tuple[str, ...] = (
    "media_duration_unknown",
    "media_fps_unknown",
    "samples_below_min",
    "drift_within_tolerance",
    "not_frame_grid",
    "applied",
    "no_fixable_finding",
)