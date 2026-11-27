"""口径面：严重级别、退出码矩阵、规则表与字符集。

级别序与 verdict 派生照搬旧仓 ``severity.py`` / ``exitcodes.py``：
``ok < info < warn < error``；``fail_on`` 为 ``none | warn | error``。
本器官的阻断只由 ``bp-gate``（一条 error 记录）表达，finding 自身只带 severity 证据，
这样 ``check`` 默认 ``fail_on=none`` 的 rc 0 语义得以保留。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN

ORGAN_VERSION = "1"

MODES = ("check", "gs1", "symbol", "oracle")

OK = "ok"
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_ERROR = "error"
SEVERITY_ORDER = {OK: 0, SEV_INFO: 1, SEV_WARN: 2, SEV_ERROR: 3}

VERDICT_PASS = "pass"
VERDICT_WARN = "warn"
VERDICT_FAIL = "fail"

FAIL_ON_CHOICES = ("none", "warn", "error")

THRESHOLD_VERIFIED = "verified"
THRESHOLD_UNVERIFIED = "unverified"
THRESHOLD_NOT_APPLICABLE = "not-applicable"

BASIS_GEN_SPEC = "gen-spec"
BASIS_ENGINEERING = "engineering-heuristic"

SUPPORTED_SYMBOLS = ("code128", "gs1-128", "ean13", "ean8", "upca", "datamatrix", "qr", "code39")
ILLUMINATIONS = ("white", "red", "ir")

PRINT_FIELDS = ("symbol", "x_dimension_mm", "target_dpi", "quiet_zone_mm")
PRINT_INPUT_FIELDS = (
    "x_dimension_mm",
    "target_dpi",
    "quiet_zone_mm",
    "bar_height_mm",
    "magnification_pct",
    "bar_color",
    "space_color",
    "illumination",
)
PRINT_COLOR_FIELDS = ("bar_color", "space_color", "illumination")
QUIET_ZONE_SIDES = ("left", "right", "top", "bottom")

CSET_NUMERIC = "0123456789"
CSET_82 = "!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz"
CSET_39 = "#-/0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CSET_BASE64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

CHARSETS = {
    "N": ("CSET_NUMERIC", CSET_NUMERIC),
    "X": ("CSET_82", CSET_82),
    "Y": ("CSET_39", CSET_39),
    "Z": ("CSET_BASE64URL", CSET_BASE64URL),
}

DATE_LINTERS = ("yymmd0", "yymmdd", "yyyymmd0", "yyyymmdd")
INTERPRETED_LINTERS = ("csum",) + DATE_LINTERS

# ------------------------------------------------------------------ 规则
RULE_GS1_CHECKSUM = "bp-gs1-checksum"
RULE_GS1_UNKNOWN_AI = "bp-gs1-unknown-ai"
RULE_GS1_MALFORMED = "bp-gs1-malformed"
RULE_GS1_CHARSET = "bp-gs1-charset"
RULE_GS1_LENGTH = "bp-gs1-length"
RULE_GS1_DATE = "bp-gs1-date"
RULE_GS1_REQUIRED = "bp-gs1-required"
RULE_GS1_EXCLUSIVE = "bp-gs1-exclusive"
RULE_GS1_SKIPPED = "bp-gs1-skipped"
RULE_SYMBOL_UNSUPPORTED = "bp-symbol-unsupported"
RULE_SYMBOL_CHARSET = "bp-symbol-charset"
RULE_SYMBOL_LENGTH = "bp-symbol-length"
RULE_SYMBOL_PLAN = "bp-symbol-plan"
RULE_SYMBOL_CAPACITY = "bp-symbol-capacity"
RULE_SYMBOL_CHECKSUM = "bp-symbol-checksum"
RULE_PRINT_INCOMPLETE = "bp-print-incomplete"
RULE_QUIET_ZONE_ABSENT = "bp-print-quiet-zone-absent"
RULE_QUIET_ZONE = "bp-print-quiet-zone"
RULE_MAGNIFICATION = "bp-print-magnification"
RULE_RASTER = "bp-print-raster"
RULE_BAR_HEIGHT = "bp-print-bar-height"
RULE_COLOR = "bp-print-color"
RULE_UNMODELLED = "bp-print-unmodelled"
RULE_ORACLE_ABSENT = "bp-oracle-absent"
RULE_ORACLE_AGREEMENT = "bp-oracle-agreement"
RULE_SUMMARY = "bp-summary"
RULE_GATE = "bp-gate"

RULE_IDS = (
    RULE_GS1_CHECKSUM,
    RULE_GS1_UNKNOWN_AI,
    RULE_GS1_MALFORMED,
    RULE_GS1_CHARSET,
    RULE_GS1_LENGTH,
    RULE_GS1_DATE,
    RULE_GS1_REQUIRED,
    RULE_GS1_EXCLUSIVE,
    RULE_GS1_SKIPPED,
    RULE_SYMBOL_UNSUPPORTED,
    RULE_SYMBOL_CHARSET,
    RULE_SYMBOL_LENGTH,
    RULE_SYMBOL_PLAN,
    RULE_SYMBOL_CAPACITY,
    RULE_SYMBOL_CHECKSUM,
    RULE_PRINT_INCOMPLETE,
    RULE_QUIET_ZONE_ABSENT,
    RULE_QUIET_ZONE,
    RULE_MAGNIFICATION,
    RULE_RASTER,
    RULE_BAR_HEIGHT,
    RULE_COLOR,
    RULE_UNMODELLED,
    RULE_ORACLE_ABSENT,
    RULE_ORACLE_AGREEMENT,
    RULE_SUMMARY,
    RULE_GATE,
)

#: 名义等级（运行期仍由具体 finding 的 severity 决定）。
VERDICTS = {
    RULE_GS1_CHECKSUM: ERROR,
    RULE_GS1_UNKNOWN_AI: ERROR,
    RULE_GS1_MALFORMED: ERROR,
    RULE_GS1_CHARSET: ERROR,
    RULE_GS1_LENGTH: ERROR,
    RULE_GS1_DATE: ERROR,
    RULE_GS1_REQUIRED: ERROR,
    RULE_GS1_EXCLUSIVE: ERROR,
    RULE_GS1_SKIPPED: INFO,
    RULE_SYMBOL_UNSUPPORTED: WARN,
    RULE_SYMBOL_CHARSET: ERROR,
    RULE_SYMBOL_LENGTH: ERROR,
    RULE_SYMBOL_PLAN: INFO,
    RULE_SYMBOL_CAPACITY: ERROR,
    RULE_SYMBOL_CHECKSUM: ERROR,
    RULE_PRINT_INCOMPLETE: ERROR,
    RULE_QUIET_ZONE_ABSENT: ERROR,
    RULE_QUIET_ZONE: ERROR,
    RULE_MAGNIFICATION: WARN,
    RULE_RASTER: ERROR,
    RULE_BAR_HEIGHT: ERROR,
    RULE_COLOR: ERROR,
    RULE_UNMODELLED: INFO,
    RULE_ORACLE_ABSENT: INFO,
    RULE_ORACLE_AGREEMENT: WARN,
    RULE_SUMMARY: INFO,
    RULE_GATE: ERROR,
}