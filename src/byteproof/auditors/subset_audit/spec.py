"""口径面（迁自 10-21-subset-audit 的常量与状态枚举）。

规则 id 前缀 ``sa-``；finding 代码与 severity 词表原样保留
（三分类 MISSING_IN_SOURCE/LOST_IN_SUBSET、LAYOUT_*、metadata 九类），
账本 verdict 由旧仓 severity 折算：error→error、warn→warn、note/skip→info。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

#: 三种模式 = 旧仓三个判定模块（license-gate 不迁，D1 排除词 license）。
MODES = ("coverage-diff", "layout-survival", "metadata")
DEFAULT_MODE = "coverage-diff"

#: 旧仓 canonical.SCHEMAS / 排序序。
SCHEMA = "subsetaudit/report@1"
SEVERITIES = ("error", "warn", "note")

#: cmapset（§六.2 / §六.4）。
NOTDEF_NAMES = frozenset([".notdef", "glyph00000", ""])
BMP_MAX = 0xFFFF
EXTA_LO, EXTA_HI = 0x3400, 0x4DBF
EXTB_LO, EXTB_HI = 0x20000, 0x2FA1F

#: coverage-diff（§六.2 / §六.3）。
COVERAGE_SPEC_REF = "data/README §6.2"
CODE_MISSING = "MISSING_IN_SOURCE"
CODE_LOST = "LOST_IN_SUBSET"
CATEGORIES = ("OK", "MISSING_IN_SOURCE", "LOST_IN_SUBSET")
BLOCKS = ("BMP", "ExtA", "ExtB+", "other")
REASON_NO_CMAP_TABLE = "no_cmap_table"
REASON_NO_UNICODE_CMAP = "no_unicode_cmap"

#: layout-survival（§六.5）。
LAYOUT_SPEC_REF = "data/README §6.5"
CODE_FEATURE_LOST = "LAYOUT_FEATURE_LOST"
CODE_LIGATURE_LOST = "LAYOUT_LIGATURE_LOST"
CODE_LIGATURE_RENAMED = "LAYOUT_LIGATURE_RENAMED"
REASON_NO_TABLES = "no_layout_tables"
REASON_ONE_SIDE = "layout_tables_missing_on_one_side"
LIGATURE_SCOPE_ALL = "all"
LAYOUT_TAGS = ("GSUB", "GPOS")

#: metadata（§六.9）。
METADATA_SPEC_REF = "data/README §6.9"
REASON_NO_OS2 = "no_os2_table"
REASON_NO_NAME = "no_name_table"
REASON_NO_OUTLINE = "no_outline_table"
REASON_NO_GLYF = "no_glyf_or_cff"
LATIN1_HI = 0x00FF
#: 必须存活的 nameID（§六.9.1 白名单）。
REQUIRED_NAME_IDS = (0, 1, 2, 3, 4, 6, 13, 14, 17)
CLASS_DEFAULT_STRIPPED = "default_stripped"
CLASS_AUTHOR_ABSENT = "author_absent"
CLASS_UNCLASSIFIED = "unclassified"
NAME_CODES = {
    0: ("NAME_COPYRIGHT_STRIPPED", "data/README §6.9.1"),
    1: ("NAME_FAMILY_STRIPPED", "data/README §6.9.1"),
    2: ("NAME_SUBFAMILY_STRIPPED", "data/README §6.9.1"),
    3: ("NAME_UNIQUE_ID_STRIPPED", "data/README §6.9.1"),
    4: ("NAME_FULL_NAME_STRIPPED", "data/README §6.9.1"),
    6: ("NAME_POSTSCRIPT_STRIPPED", "data/README §6.9.1"),
    13: ("NAME_LICENSE_STRIPPED", "data/README §6.9.1"),
    14: ("NAME_LICENSE_URL_STRIPPED", "data/README §6.9.1"),
    17: ("NAME_TYPOGRAPHIC_STRIPPED", "data/README §6.9.1"),
}
CODE_CODEPAGE_LATIN1 = "CODEPAGE_CLAIMS_LATIN1_WITHOUT_COVERAGE"
CODEPAGE_LATIN1_SPEC_REF = "data/README §6.9.2"
CODE_UNICODE_OVER = "UNICODE_RANGE_OVER_DECLARED"
CODE_MAXP_MISMATCH = "MAXP_NUM_GLYPHS_MISMATCH"
CODE_CHAR_INDEX = "CHAR_INDEX_MISMATCH"
#: OS/2 ulUnicodeRange 行为位（§六.9.3：默认剥离位 vs 行为位）。
BEHAVIORAL_BITS = frozenset()
