"""口径面：方向矩阵、消费者矩阵、默认假设表、严重级别与规则表。

数值口径照搬旧仓 ``data/README.md`` §8：方向 8 元组、消费者 9×6 矩阵、
默认假设 7 行、severity → verdict。表体是**数据**，判定函数只做映射与取或。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN

ORGAN_VERSION = "1"

MODES = ("orientation", "double-rotate", "color", "container", "consumers")

SEVERITY_ORDER = {"info": 0, "suspicion": 0, "warning": 1, "error": 2, "unknown": 2}
RISK_BY_SEVERITY = {"info": "low", "suspicion": "low", "warning": "medium", "error": "high", "unknown": "unknown"}

#: (flip_h, flip_v, rotate_cw_deg, swap_wh) —— 旧仓 orientation.ORIENTATION_MATRIX。
ORIENTATION_MATRIX = {
    1: (False, False, 0, False),
    2: (True, False, 0, False),
    3: (False, False, 180, False),
    4: (False, True, 0, False),
    5: (True, False, 270, True),
    6: (False, False, 90, True),
    7: (True, False, 90, True),
    8: (False, False, 270, True),
}
ORIENTATION_LABELS = {
    1: "Horizontal (normal)",
    2: "Mirror horizontal",
    3: "Rotate 180",
    4: "Mirror vertical",
    5: "Mirror horizontal and rotate 270 CW",
    6: "Rotate 90 CW",
    7: "Mirror horizontal and rotate 90 CW",
    8: "Rotate 270 CW",
}
TAG_ORIENTATION = 274
ROTATING_VALUES = frozenset({5, 6, 7, 8})

#: XMP 方向属性的两种写法（唯一实现点；测试断言两式都认）。
XMP_PATTERNS = (
    r'tiff:Orientation\s*=\s*["\'](\d+)["\']',
    r"<tiff:Orientation>\s*(\d+)\s*</tiff:Orientation>",
)

#: 消费者矩阵（9 行，列 = 5 个能力列 + evidence）；值域见 VALUE_VOCAB。
CONSUMERS = ("chrome", "safari", "firefox", "macos_preview", "windows_photos", "imagemagick", "libvips", "sharp", "exiftran")
COLUMNS = ("applies_orientation", "applies_icc", "dropped_chunks", "double_rotate_risk", "frame_duration")
VALUE_VOCAB = {
    "applies_orientation": ("yes", "partial", "no", "unknown"),
    "applies_icc": ("yes", "no", "unknown"),
    "double_rotate_risk": ("low", "medium", "high", "unknown"),
    "frame_duration": ("per-container-unit", "unknown", "n/a"),
}
RISK_LEVELS = ("high", "medium", "low", "unknown")
CONFIDENCES = ("certain", "single-source", "gray")

MATRIX_ROWS = (
    {"consumer": "chrome", "applies_orientation": "partial", "applies_icc": "yes", "dropped_chunks": [], "double_rotate_risk": "medium", "frame_duration": "per-container-unit", "confidence": "single-source"},
    {"consumer": "safari", "applies_orientation": "partial", "applies_icc": "yes", "dropped_chunks": [], "double_rotate_risk": "medium", "frame_duration": "per-container-unit", "confidence": "single-source"},
    {"consumer": "firefox", "applies_orientation": "unknown", "applies_icc": "unknown", "dropped_chunks": [], "double_rotate_risk": "unknown", "frame_duration": "per-container-unit", "confidence": "gray"},
    {"consumer": "macos_preview", "applies_orientation": "unknown", "applies_icc": "unknown", "dropped_chunks": [], "double_rotate_risk": "unknown", "frame_duration": "unknown", "confidence": "gray"},
    {"consumer": "windows_photos", "applies_orientation": "partial", "applies_icc": "yes", "dropped_chunks": [], "double_rotate_risk": "medium", "frame_duration": "per-container-unit", "confidence": "single-source"},
    {"consumer": "imagemagick", "applies_orientation": "yes", "applies_icc": "yes", "dropped_chunks": [], "double_rotate_risk": "high", "frame_duration": "per-container-unit", "confidence": "certain"},
    {"consumer": "libvips", "applies_orientation": "yes", "applies_icc": "yes", "dropped_chunks": [], "double_rotate_risk": "medium", "frame_duration": "per-container-unit", "confidence": "certain"},
    {"consumer": "sharp", "applies_orientation": "yes", "applies_icc": "yes", "dropped_chunks": [], "double_rotate_risk": "high", "frame_duration": "unknown", "confidence": "certain"},
    {"consumer": "exiftran", "applies_orientation": "yes", "applies_icc": "no", "dropped_chunks": ["eXIf"], "double_rotate_risk": "low", "frame_duration": "unknown", "confidence": "certain"},
)

#: 默认假设表（7 行）：容器/软件无 profile 时各方的默认色彩空间。
DEFAULT_ASSUMPTIONS = (
    {"consumer": "chrome", "assumption": "sRGB", "source": "Chrome 色彩文档"},
    {"consumer": "safari", "assumption": "Display P3（未取到第一方文档）", "source": "single-source"},
    {"consumer": "firefox", "assumption": "unknown", "source": "未取到第一方文档"},
    {"consumer": "macos_preview", "assumption": "Display P3", "source": "Apple 文档"},
    {"consumer": "windows_photos", "assumption": "sRGB", "source": "Microsoft 文档"},
    {"consumer": "imagemagick", "assumption": "sRGB", "source": "ImageMagick 文档"},
    {"consumer": "libvips", "assumption": "不假设 sRGB（从内置 profile 选兼容者）", "source": "libvips icc_import"},
)

#: 加工命令 → 会丢掉的 chunk（机器可读副本；判定只做集合差）。
PROCESSING_DROPS = {
    "oxipng --strip safe": ("eXIf", "iCCP", "tEXt"),
    "jpegtran -copy none": ("APP1", "APP2"),
    "jpegtran -copy all": (),
    "exiftool -all=": ("APP1", "APP2", "eXIf", "iCCP"),
    "magick -strip": ("APP1", "APP2", "eXIf", "iCCP", "tEXt"),
    "sharp .withMetadata(false)": ("APP1", "APP2", "eXIf", "iCCP"),
}

#: ICC 头字段。
ICC_HEAD_MIN = 128
KNOWN_CLASSES = frozenset({"mntr", "scnr", "prtr"})
OTHER_LEGAL_CLASSES = frozenset({"spac", "abst", "nmcl"})
KNOWN_SPACES = frozenset({"RGB ", "CMYK", "GRAY", "XYZ ", "Lab "})

# ------------------------------------------------------------------ 规则
RULE_ORIENTATION = "io-orientation"
RULE_ORIENTATION_ABSENT = "io-orientation-absent"
RULE_ORIENTATION_TYPE = "io-orientation-type"
RULE_ORIENTATION_RANGE = "io-orientation-range"
RULE_ORIENTATION_XMP = "io-orientation-xmp"
RULE_DOUBLE_IFD1 = "io-double-ifd1"
RULE_DOUBLE_XMP = "io-double-xmp"
RULE_DOUBLE_BIGEDGE = "io-double-bigedge"
RULE_COLOR_ICC = "io-color-icc"
RULE_COLOR_ICC_GAP = "io-color-icc-gap"
RULE_COLOR_ICC_HEADER = "io-color-icc-header"
RULE_COLOR_ICC_CLASS = "io-color-icc-class"
RULE_COLOR_ICC_SPACE = "io-color-icc-space"
RULE_COLOR_ICC_UNKNOWN = "io-color-icc-unknown"
RULE_COLOR_ICCP_SRGB = "io-color-iccp-srgb"
RULE_COLOR_MARKERS = "io-color-markers"
RULE_COLOR_BITDEPTH = "io-color-bitdepth"
RULE_COLOR_CMYK = "io-color-cmyk"
RULE_COLOR_DEFAULTS = "io-color-defaults"
RULE_CONTAINER_PNG_ORDER = "io-container-png-order"
RULE_CONTAINER_PNG_CRC = "io-container-png-crc"
RULE_CONTAINER_APNG = "io-container-apng"
RULE_CONTAINER_FRAME = "io-container-frame"
RULE_CONTAINER_JPEG = "io-container-jpeg"
RULE_CONTAINER_WEBP = "io-container-webp"
RULE_CONTAINER_GIF = "io-container-gif"
RULE_CONSUMERS_MATRIX = "io-consumers-matrix"
RULE_CONSUMERS_RISK = "io-consumers-risk"
RULE_CONSUMERS_DIFF = "io-consumers-diff"
RULE_SUMMARY = "io-summary"
RULE_GATE = "io-gate"

RULE_IDS = (
    RULE_ORIENTATION,
    RULE_ORIENTATION_ABSENT,
    RULE_ORIENTATION_TYPE,
    RULE_ORIENTATION_RANGE,
    RULE_ORIENTATION_XMP,
    RULE_DOUBLE_IFD1,
    RULE_DOUBLE_XMP,
    RULE_DOUBLE_BIGEDGE,
    RULE_COLOR_ICC,
    RULE_COLOR_ICC_GAP,
    RULE_COLOR_ICC_HEADER,
    RULE_COLOR_ICC_CLASS,
    RULE_COLOR_ICC_SPACE,
    RULE_COLOR_ICC_UNKNOWN,
    RULE_COLOR_ICCP_SRGB,
    RULE_COLOR_MARKERS,
    RULE_COLOR_BITDEPTH,
    RULE_COLOR_CMYK,
    RULE_COLOR_DEFAULTS,
    RULE_CONTAINER_PNG_ORDER,
    RULE_CONTAINER_PNG_CRC,
    RULE_CONTAINER_APNG,
    RULE_CONTAINER_FRAME,
    RULE_CONTAINER_JPEG,
    RULE_CONTAINER_WEBP,
    RULE_CONTAINER_GIF,
    RULE_CONSUMERS_MATRIX,
    RULE_CONSUMERS_RISK,
    RULE_CONSUMERS_DIFF,
    RULE_SUMMARY,
    RULE_GATE,
)

VERDICTS = {rule_id: (ERROR if rule_id == RULE_GATE else INFO) for rule_id in RULE_IDS}