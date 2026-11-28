"""口径面（迁自 10-7-thesis-audit-workbench 的 ``registry``/``engine`` 规则面与各模块常量）。

**规则 id 白名单**是器官与判定核之间的契约：``core_ref.evaluate`` / ``core_doc.evaluate``
只准产出这里登记的 ``rule_id``；api 对未登记的 id 一律 ``ValueError``（退出码 2），
不让"临时编一条规则"混进账本。

阈值与词表随判定核（``core_ref`` / ``core_doc``）的模块常量走——旧仓是
``data/`` 下的 ruleset JSON + 词表，本器官不读文件，故以常量内联并在这份
``thresholds.json`` 快照里留档（测试双向断言）。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

ORGAN_VERSION = "1"

#: 判定核分工：引用面（core_ref）与文档面（core_doc）。
REF_MODES: Tuple[str, ...] = ("refcheck", "cite", "dedup", "fake", "rec", "library", "review")
DOC_MODES: Tuple[str, ...] = ("aigc", "structure", "terms", "figures", "school", "rng")
MODES: Tuple[str, ...] = REF_MODES + DOC_MODES
DEFAULT_MODE = "refcheck"

#: 规则 id 白名单（引用面 20 条 + 文档面 15 条 + 账本汇总 1 条）。
REF_RULES: Tuple[str, ...] = (
    "taw-ref-card",
    "taw-ref-field-required",
    "taw-ref-type-marker",
    "taw-ref-author-threshold",
    "taw-ref-page-range",
    "taw-ref-citation-style",
    "taw-ref-standard-currency",
    "taw-ref-consistency",
    "taw-ref-punct",
    "taw-cite-marker",
    "taw-cite-uncited",
    "taw-cite-order",
    "taw-dedup-pair",
    "taw-dedup-merge-conflict",
    "taw-fake-signal",
    "taw-fake-health",
    "taw-rec-hint",
    "taw-lib-tamper",
    "taw-review-cluster",
    "taw-review-gap",
)
DOC_RULES: Tuple[str, ...] = (
    "taw-aigc-band",
    "taw-aigc-dist",
    "taw-struct-heading",
    "taw-struct-abstract",
    "taw-struct-chapter",
    "taw-term-hit",
    "taw-term-stray",
    "taw-term-number",
    "taw-term-heat",
    "taw-fig-xref",
    "taw-fig-gap",
    "taw-fig-renumber",
    "taw-school-style",
    "taw-school-format",
    "taw-rng-determinism",
)
SUMMARY_RULE = "taw-summary"
ALL_RULES: Tuple[str, ...] = REF_RULES + DOC_RULES + (SUMMARY_RULE,)

#: 每条规则的缺省等级（登记值 = 判定核的常态结论；个别分支可升级，例如
#: ``taw-cite-order`` 的文献表编号空档判 error。api 只校验 verdict 取值，不比对本表）。
SEVERITY: Dict[str, str] = {
    "taw-ref-card": "error",
    "taw-ref-field-required": "error",
    "taw-ref-type-marker": "error",
    "taw-ref-author-threshold": "error",
    "taw-ref-page-range": "error",
    "taw-ref-citation-style": "error",
    "taw-ref-standard-currency": "warn",
    "taw-ref-consistency": "error",
    "taw-ref-punct": "warn",
    "taw-cite-marker": "error",
    "taw-cite-uncited": "warn",
    "taw-cite-order": "warn",
    "taw-dedup-pair": "error",
    "taw-dedup-merge-conflict": "warn",
    "taw-fake-signal": "error",
    "taw-fake-health": "info",
    "taw-rec-hint": "info",
    "taw-lib-tamper": "error",
    "taw-review-cluster": "info",
    "taw-review-gap": "info",
    "taw-aigc-band": "warn",
    "taw-aigc-dist": "info",
    "taw-struct-heading": "error",
    "taw-struct-abstract": "error",
    "taw-struct-chapter": "error",
    "taw-term-hit": "warn",
    "taw-term-stray": "warn",
    "taw-term-number": "warn",
    "taw-term-heat": "info",
    "taw-fig-xref": "error",
    "taw-fig-gap": "error",
    "taw-fig-renumber": "info",
    "taw-school-style": "error",
    "taw-school-format": "error",
    "taw-rng-determinism": "info",
    SUMMARY_RULE: "info",
}

VERDICTS: Tuple[str, ...] = ("error", "warn", "info")

#: 旧仓 ``reffake`` / ``refdedup`` 的默认口径（判定核默认参数的同名快照）。
EDIT_THRESHOLD = 2
#: 旧仓 ``refcheck`` 的作者阈值（超过即要求 et al./等）。
AUTHOR_THRESHOLD = 3
#: 旧仓 ``aigccheck`` 的分档边界（0..1 风险分）：低/中/高。
AIGC_BANDS: Tuple[float, float] = (0.34, 0.67)
#: 旧仓 ``termnum`` 的重复标点/空格口径留档。
REPEAT_SPACE_LIMIT = 1

#: 规则清单（发到 basis 与 thresholds 快照，测试双向断言）。
RULE_IDS: List[str] = list(ALL_RULES)