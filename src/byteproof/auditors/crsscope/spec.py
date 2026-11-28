"""口径面：规则 id、名义 verdict 与映射表（迁自 10-27-crsscope）。

账本映射：conflict/error → error（阻断，旧 rc1）；warning（R1 环方向默认档、bbox 不一致、
轴序、crs 成员、精度）与 undecidable（灰区，旧 rc5）→ warn（分级而非拒绝）；info/
consistent → info。规则 id 前缀 ``crs-``。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

MODES = ("decl", "detect", "xdiff", "geojson", "tiles", "report")
DEFAULT_MODE = "decl"

RULE_CHECK = "crs-check-finding"
RULE_STRUCTURE = "crs-structure-error"
RULE_VERDICT = "crs-module-verdict"
RULE_UNDECIDABLE = "crs-gray-zone"
RULE_DETECT_WINNER = "crs-detect-winner"
RULE_RESIDUAL = "crs-residual"
RULE_SUMMARY = "crs-summary"

#: 各模块检查项 → 器官规则 id（decl 五项 / geojson 七项 / tiles 五项 / xdiff 五项，一项一责）。
#: decl 与 geojson 都有名为 ``axis`` 的检查项——按模块分表，不共用一个平面字典。
RULE_BY_DECL = {
    "magnitude": "crs-decl-magnitude",
    "axis": "crs-decl-axis",
    "unit": "crs-decl-unit",
    "mixed": "crs-decl-mixed",
    "extent": "crs-decl-extent",
}

RULE_BY_GEOJSON = {
    "ring_order": "crs-geojson-ring-order",
    "axis": "crs-geojson-axis",
    "bbox": "crs-geojson-bbox",
    "nesting": "crs-geojson-nesting",
    "null_geometry": "crs-geojson-null-geometry",
    "crs_member": "crs-geojson-crs-member",
    "precision": "crs-geojson-precision",
}

RULE_BY_TILES = {
    "axis_flip": "crs-tiles-axis-flip",
    "y_range": "crs-tiles-y-range",
    "zoom_bbox": "crs-tiles-zoom-bbox",
    "wrap": "crs-tiles-wrap",
    "mixed_3857_4326": "crs-tiles-mixed",
}

RULE_BY_XDIFF = {
    "implementations": "crs-xdiff-implementations",
    "pairwise": "crs-xdiff-pairwise",
    "boundary_table": "crs-xdiff-boundary-table",
    "jumps": "crs-xdiff-jumps",
    "not_converged": "crs-xdiff-not-converged",
}

RULE_BY_MODULE = {
    "decl": RULE_BY_DECL,
    "geojson": RULE_BY_GEOJSON,
    "tiles": RULE_BY_TILES,
    "xdiff": RULE_BY_XDIFF,
}

#: 全部检查规则（兜底 RULE_CHECK 除外）。
CHECK_RULE_IDS = tuple(sorted({rule for mapping in RULE_BY_MODULE.values() for rule in mapping.values()} | {RULE_CHECK}))

#: 检查规则 = 四个模块映射的并集 + 兜底 RULE_CHECK。
CHECK_RULE_IDS = tuple(sorted({rule for mapping in RULE_BY_MODULE.values() for rule in mapping.values()} | {RULE_CHECK}))

RULE_IDS = (
    *CHECK_RULE_IDS,
    RULE_STRUCTURE,
    RULE_VERDICT,
    RULE_UNDECIDABLE,
    RULE_DETECT_WINNER,
    RULE_RESIDUAL,
    RULE_SUMMARY,
)

#: 状态 → 账本 verdict（undecidable → warn：灰区不阻断，但必须可见）。
STATUS_TO_VERDICT = {
    "conflict": "error",
    "error": "error",
    "warning": "warn",
    "undecidable": "warn",
    "info": "info",
    "consistent": "info",
}

#: 名义 verdict：检查项的实际级别由「状态 → verdict」映射逐条决定（同一检查项
#: 可以是 conflict→error 也可以是 consistent→info），名义档统一记 info。
VERDICTS = {rule_id: "info" for rule_id in RULE_IDS}
