"""口径面：模式、冻结编码集合、可读性权重、扫描阈值与规则等级。

数值唯一来源是旧仓 ``data/README.md`` §4；本文件是**代码侧冻结点**，与
``src/byteproof/data/mojibake-forensics.thresholds.json`` 逐项相等（测试守门）。
器官不读该 JSON——它只是台账，运行期常量在这里。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN

ORGAN_VERSION = "1"

MODES = ("attr", "explain", "recover", "file", "scan")

# 旧仓 ``codecs_table``：编码器可向任意方向 encode，解码器只收保守集合。
ENCODERS = (
    "utf-8",
    "gb18030",
    "gbk",
    "big5",
    "shift_jis",
    "euc-jp",
    "euc-kr",
    "cp1252",
    "latin-1",
    "cp437",
)
DECODERS = (
    "utf-8",
    "gb18030",
    "big5",
    "shift_jis",
    "euc-kr",
    "cp1252",
    "latin-1",
)
MAX_DEPTH = 3
DEFAULT_TOP = 5

# 三层打分权重（旧仓 §4.4）：语言先验只在 --freq 开启，本器官不迁 --freq。
W_READ = 1.0
W_DEPTH = 0.5
W_LANG = 0.3

ASCII_VISIBLE = 0.2
CJK = 1.0
LATIN_EXT = 0.1
HALFWIDTH_KATAKANA = -0.5
CONTROL = -1.0
PUA = -1.0
REPLACEMENT = -1.5
OTHER = 0.0
REGULAR_WHITESPACE = ("\t", "\n", "\r")

# scan 命中判据（旧仓 K9 / §4.8）：三者同时成立才算命中。
INPUT_READABILITY_BELOW = 0.5
CANDIDATE_READABILITY_AT_LEAST = 0.8
READABILITY_GAIN_AT_LEAST = 0.3

# 不可逆五类里可由文本单独判定的四类（silent_drop 需要出处证据，CLI 面不伪造）。
REASON_REPLACEMENT_CHAR = "replacement_char"
REASON_KUN_JIN_KAO = "kun_jin_kao"
REASON_MSVC_FILL = "msvc_fill"
REASON_ENCODE_TRUNCATED = "encode_truncated"
REASON_SILENT_DROP = "silent_drop"
REASON_VERIFY_FAILED = "verify_failed"
REASON_NO_CANDIDATE = "no_candidate"

REPLACEMENT_CHAR = "\ufffd"  # U+FFFD
KUN_JIN_KAO = "\u951f\u65a4\u62f7"  # 锟斤拷
TANG_TANG = "\u70eb\u70eb\u70eb"  # 烫烫烫
TUN_TUN = "\u5c6f\u5c6f\u5c6f"  # 屯屯屯
KUN_JIN_KAO_BYTES_HEX = "EF BF BD"

STATUS_CANDIDATES = "candidates"
STATUS_NO_CANDIDATE = "no_candidate"
STATUS_RECOVERED = "recovered"
STATUS_LOST = "lost"
STATUS_NOT_MOJIBAKE = "not_mojibake"
STATUS_OK = "ok"

# ------------------------------------------------------------------ 规则表
RULE_ATTR_CANDIDATE = "mf-attr-candidate"
RULE_ATTR_NO_CANDIDATE = "mf-attr-no-candidate"
RULE_ATTR_CONFIDENCE_DEGENERATE = "mf-attr-confidence-degenerate"
RULE_ATTR_SINGLE_CANDIDATE = "mf-attr-single-candidate"
RULE_ATTR_TRUNCATED = "mf-attr-truncated"
RULE_EXPLAIN_VERIFY = "mf-explain-verify"
RULE_EXPLAIN_VERIFY_FAILED = "mf-explain-verify-failed"
RULE_EXPLAIN_DIVERGENCE = "mf-explain-divergence"
RULE_RECOVER_RECOVERED = "mf-recover-recovered"
RULE_RECOVER_LOST = "mf-recover-lost"
RULE_RECOVER_NOT_MOJIBAKE = "mf-recover-not-mojibake"
RULE_RECOVER_NO_CANDIDATE = "mf-recover-no-candidate"
RULE_FILE_BOM = "mf-file-bom"
RULE_FILE_BOM_CONFLICT = "mf-file-bom-conflict"
RULE_FILE_UTF16_MISALIGNMENT = "mf-file-utf16-misalignment"
RULE_FILE_ZIP_NAME = "mf-file-zip-name"
RULE_FILE_ZIP_NAME_AMBIGUOUS = "mf-file-zip-name-ambiguous"
RULE_FILE_CSV_CANDIDATE = "mf-file-csv-candidate"
RULE_SCAN_NEW = "mf-scan-new"
RULE_SCAN_BASELINED = "mf-scan-baselined"
RULE_SCAN_STALE = "mf-scan-stale"
RULE_SCAN_CLEAN = "mf-scan-clean"

RULE_IDS = (
    RULE_ATTR_CANDIDATE,
    RULE_ATTR_NO_CANDIDATE,
    RULE_ATTR_CONFIDENCE_DEGENERATE,
    RULE_ATTR_SINGLE_CANDIDATE,
    RULE_ATTR_TRUNCATED,
    RULE_EXPLAIN_VERIFY,
    RULE_EXPLAIN_VERIFY_FAILED,
    RULE_EXPLAIN_DIVERGENCE,
    RULE_RECOVER_RECOVERED,
    RULE_RECOVER_LOST,
    RULE_RECOVER_NOT_MOJIBAKE,
    RULE_RECOVER_NO_CANDIDATE,
    RULE_FILE_BOM,
    RULE_FILE_BOM_CONFLICT,
    RULE_FILE_UTF16_MISALIGNMENT,
    RULE_FILE_ZIP_NAME,
    RULE_FILE_ZIP_NAME_AMBIGUOUS,
    RULE_FILE_CSV_CANDIDATE,
    RULE_SCAN_NEW,
    RULE_SCAN_BASELINED,
    RULE_SCAN_STALE,
    RULE_SCAN_CLEAN,
)

VERDICTS = {
    RULE_ATTR_CANDIDATE: INFO,
    RULE_ATTR_NO_CANDIDATE: ERROR,
    RULE_ATTR_CONFIDENCE_DEGENERATE: WARN,
    RULE_ATTR_SINGLE_CANDIDATE: INFO,
    RULE_ATTR_TRUNCATED: INFO,
    RULE_EXPLAIN_VERIFY: INFO,
    RULE_EXPLAIN_VERIFY_FAILED: ERROR,
    RULE_EXPLAIN_DIVERGENCE: INFO,
    RULE_RECOVER_RECOVERED: INFO,
    RULE_RECOVER_LOST: ERROR,
    RULE_RECOVER_NOT_MOJIBAKE: ERROR,
    RULE_RECOVER_NO_CANDIDATE: ERROR,
    RULE_FILE_BOM: INFO,
    RULE_FILE_BOM_CONFLICT: WARN,
    RULE_FILE_UTF16_MISALIGNMENT: WARN,
    RULE_FILE_ZIP_NAME: INFO,
    RULE_FILE_ZIP_NAME_AMBIGUOUS: WARN,
    RULE_FILE_CSV_CANDIDATE: INFO,
    RULE_SCAN_NEW: ERROR,
    RULE_SCAN_BASELINED: INFO,
    RULE_SCAN_STALE: WARN,
    RULE_SCAN_CLEAN: INFO,
}

