"""口径面：模块、规则、策略常量与退出码。

数值口径照搬旧仓 ``internal/policy``：TickTolerance=1、TimescaleSuspectBelow=100、
MatrixOrthoTolerance=1、DTSRegressionTolerance=0。规则 id 与旧仓五个模块的
``RuleIDs`` 同名；``fail``/``gray`` 三态照搬 ``data/README.md`` §5.6。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN

ORGAN_VERSION = "1"

MODULES = ("M1", "M2", "M3", "M4", "M5")

TICK_TOLERANCE = 1
TIMESCALE_SUSPECT_BELOW = 100
MATRIX_ORTHO_TOLERANCE = 1
DTS_REGRESSION_TOLERANCE = 0
RATE_ONE = 0x00010000
Q16_ONE = 1 << 16
STTS_WIDTH_MAX = 2 ** 32 - 1
TFDT_V0_WIDTH_MAX = 2 ** 32 - 1

#: 已知 priming 的编码（旧仓 M4 表）：AAC 1024 等。
KNOWN_PRIMING = {"mp4a": 1024, "aac": 1024, "alac": 0, "opus": 0}
#: 需要 roll distance 的编码。
ROLL_DISTANCE_CODECS = {"ac-3", "ec-3", "dtsc", "dtsh", "dtsl"}

STATUS_FAIL = "fail"
STATUS_GRAY = "gray"

# ------------------------------------------------------------------ 规则
RULE_TOO_SMALL = "mt-too-small-size"
RULE_CHILD_OVERRUN = "mt-child-overruns-parent"
RULE_DUPLICATE_MOOV = "mt-duplicate-moov"
RULE_DUPLICATE_MDAT = "mt-duplicate-mdat"
RULE_STCO_OUT = "mt-stco-out-of-mdat"
RULE_TRUNCATED_MDAT = "mt-truncated-mdat"
RULE_FTYP_BRAND = "mt-ftyp-brand-mismatch"
RULE_MAX_DEPTH = "mt-max-depth-exceeded"
RULE_DURATION_MISMATCH = "mt-duration-mismatch"
RULE_ELST_RATE = "mt-elst-item-rate-not-one"
RULE_ELST_ORDER = "mt-elst-item-order-suspect"
RULE_EMPTY_EDIT = "mt-empty-edit"
RULE_FIRST_PTS_OUTSIDE = "mt-first-pts-outside-media"
RULE_DURATION_UNKNOWN = "mt-duration-unknown"
RULE_TFDT_REGRESSION = "mt-tfdt-regression"
RULE_ZERO_DURATION = "mt-zero-duration-entry"
RULE_DTS_OVERFLOW = "mt-dts-overflow-risk"
RULE_DTS_REGRESSION = "mt-dts-regression"
RULE_TIMESCALE_SUSPECT = "mt-timescale-suspect"
RULE_VFR = "mt-vfr-detected"
RULE_PRIMING_UNDECLARED = "mt-priming-undeclared"
RULE_START_TRIM = "mt-start-trim"
RULE_PRIMING_MISMATCH = "mt-priming-mismatch"
RULE_NO_ROLL = "mt-no-roll-distance"
RULE_NO_EDTS = "mt-no-edts-but-nonzero-start"
RULE_UNKNOWN_PRIMING = "mt-unknown-codec-priming"
RULE_MATRIX = "mt-matrix-not-orthogonal"
RULE_ROTATION_DIM = "mt-rotation-dimension-conflict"
RULE_SAR_DAR = "mt-sar-dar-conflict"
RULE_COLR_MULTI = "mt-colr-multi-instance"
RULE_HDR_MISSING = "mt-hdr-metadata-missing"
RULE_HDR_RANGE = "mt-hdr-range-suspect"
RULE_SUMMARY = "mt-summary"
RULE_GATE = "mt-gate"

RULE_IDS = (
    RULE_TOO_SMALL,
    RULE_CHILD_OVERRUN,
    RULE_DUPLICATE_MOOV,
    RULE_DUPLICATE_MDAT,
    RULE_STCO_OUT,
    RULE_TRUNCATED_MDAT,
    RULE_FTYP_BRAND,
    RULE_MAX_DEPTH,
    RULE_DURATION_MISMATCH,
    RULE_ELST_RATE,
    RULE_ELST_ORDER,
    RULE_EMPTY_EDIT,
    RULE_FIRST_PTS_OUTSIDE,
    RULE_DURATION_UNKNOWN,
    RULE_TFDT_REGRESSION,
    RULE_ZERO_DURATION,
    RULE_DTS_OVERFLOW,
    RULE_DTS_REGRESSION,
    RULE_TIMESCALE_SUSPECT,
    RULE_VFR,
    RULE_PRIMING_UNDECLARED,
    RULE_START_TRIM,
    RULE_PRIMING_MISMATCH,
    RULE_NO_ROLL,
    RULE_NO_EDTS,
    RULE_UNKNOWN_PRIMING,
    RULE_MATRIX,
    RULE_ROTATION_DIM,
    RULE_SAR_DAR,
    RULE_COLR_MULTI,
    RULE_HDR_MISSING,
    RULE_HDR_RANGE,
    RULE_SUMMARY,
    RULE_GATE,
)

VERDICTS = {rule_id: (ERROR if rule_id == RULE_GATE else INFO) for rule_id in RULE_IDS}

CODE_RULE = {
    "too_small_size": RULE_TOO_SMALL,
    "child_overruns_parent": RULE_CHILD_OVERRUN,
    "duplicate_moov": RULE_DUPLICATE_MOOV,
    "duplicate_mdat": RULE_DUPLICATE_MDAT,
    "stco_out_of_mdat": RULE_STCO_OUT,
    "truncated_mdat": RULE_TRUNCATED_MDAT,
    "ftyp_brand_mismatch": RULE_FTYP_BRAND,
    "max_depth_exceeded": RULE_MAX_DEPTH,
    "duration_mismatch": RULE_DURATION_MISMATCH,
    "elst_item_rate_not_one": RULE_ELST_RATE,
    "elst_item_order_suspect": RULE_ELST_ORDER,
    "empty_edit": RULE_EMPTY_EDIT,
    "first_pts_outside_media": RULE_FIRST_PTS_OUTSIDE,
    "duration_unknown": RULE_DURATION_UNKNOWN,
    "tfdt_regression": RULE_TFDT_REGRESSION,
    "zero_duration_entry": RULE_ZERO_DURATION,
    "dts_overflow_risk": RULE_DTS_OVERFLOW,
    "dts_regression": RULE_DTS_REGRESSION,
    "timescale_suspect": RULE_TIMESCALE_SUSPECT,
    "vfr_detected": RULE_VFR,
    "priming_undeclared": RULE_PRIMING_UNDECLARED,
    "start_trim": RULE_START_TRIM,
    "priming_mismatch": RULE_PRIMING_MISMATCH,
    "no_roll_distance": RULE_NO_ROLL,
    "no_edts_but_nonzero_start": RULE_NO_EDTS,
    "unknown_codec_priming": RULE_UNKNOWN_PRIMING,
    "matrix_not_orthogonal": RULE_MATRIX,
    "rotation_dimension_conflict": RULE_ROTATION_DIM,
    "sar_dar_conflict": RULE_SAR_DAR,
    "colr_multi_instance": RULE_COLR_MULTI,
    "hdr_metadata_missing": RULE_HDR_MISSING,
    "hdr_range_suspect": RULE_HDR_RANGE,
}

CODEC_BRANDS = {"avc1", "hvc1", "hev1", "mp4a", "vp09", "av01"}