# -*- coding: utf-8 -*-
"""文献审计判定内核（器官迁移：``10-7-thesis-audit-workbench/code/src/taw``）。

唯一对外入口::

    evaluate(mode, subject) -> [{"rule_id","verdict","message","path","evidence"}]

七个 mode 与旧仓模块的对应关系：

====================  ====================================================
mode                  旧仓来源（判定函数逐条迁入，逻辑保持）
====================  ====================================================
``refcheck``           ``cards`` + ``refcheck``（必著录项 / 标识 / 著者阈值 /
                      页码 / 编码制 / 标准换版 / 一致性 / 标点）
``cite``              ``refcite``（标记解析 / 悬空 / 幽灵 / 乱序断档 / 著者-年份）
``dedup``             ``refdedup``（三级判据 / 误合并率 0 / 合并建议）
``fake``              ``reffake``（六信号 / 风险分级 / 体检分）
``rec``               ``refrec``（BM25 库内推荐 / 插入删除 / 编辑矩阵，
                      连同它调用的 ``renumber`` 内核一并折入本模块）
``library``           ``reflib``（内容指纹 / 清单 / 篡改检测）
``review``            ``reviewcl``（TF-IDF 聚类 / 纯度 / 时间线 / 研究空白）
====================  ====================================================

**纯函数纪律**：不 import ``os`` / ``sys`` / ``pathlib`` / ``json`` / ``time`` /
``datetime`` / ``random`` / ``sqlite3``；不读文件、不读环境变量、不读时钟、不打印。
旧仓的 docx / SQLite / 规则包文件读取一律留在调用方，规则数据以模块常量或
subject 显式事实传入。``hashlib`` / ``math`` / ``re`` / ``copy`` 只做确定性计算。

**判定口径（旧三级 → 新三级）**：旧 ``pass|fail|manual_confirm`` 折算为
``error|warn|info``：

* 文件级 / 不可解释的结构破损 → ``error``；
* 可疑但可解释（同形歧义、版本口径、风格残留、编号顺序） → ``warn``；
* 统计 / 提示 / 重排计划 → ``info``。

逐规则落点：``taw-ref-card`` / ``taw-ref-field-required`` / ``taw-ref-type-marker`` /
``taw-ref-author-threshold`` / ``taw-ref-page-range`` / ``taw-ref-consistency`` =
error（``taw-ref-author-threshold`` 的「恰 3 位带等」歧义 = warn，``taw-ref-punct``
与 ``taw-ref-standard-currency`` = warn，``taw-ref-citation-style`` = error）；
``taw-cite-marker`` 悬空 = error、著者-年份不匹配 = warn；``taw-cite-uncited`` = warn；
``taw-cite-order`` 首个引用降序 = warn、文献表编号空档 = error；
``taw-dedup-pair`` = error、``taw-dedup-merge-conflict`` = warn；
``taw-fake-signal`` 结构性信号（high）= error、弱信号（medium）= warn；
``taw-fake-health`` / ``taw-rec-hint`` / ``taw-review-cluster`` / ``taw-review-gap``
= info；``taw-lib-tamper`` 增删改 = error、未变 = info。

**subject 扩展键**（不在最小契约里、给了才生效）：``refcheck`` 的 ``doc_name`` /
``replacements``（替代关系表，缺省用模块常量），``fake`` 的 ``doc_name``，
``cite`` 的 ``doc_name`` / ``markers``（与 ``text`` 二选一）。

**迁移口径差（如实登记）**：

1. ``reffake.load_known_prefixes`` / ``load_fake_isbn_ranges``（读
   ``data/knowledge/doi_fake_prefixes.json``）改为模块常量
   ``KNOWN_DOI_PREFIXES`` / ``DEFAULT_FAKE_ISBN_RANGES``；subject 显式传入时**替换**
   默认集合（旧仓是「基础集 + 白名单增量」，本模块不做增量合并）。
2. ``reflib`` 的指纹编码：旧仓 ``json.dumps(sort_keys=True)`` 不可用（纯函数面不
   import ``json``），改为控制字符分隔的规范文本；哈希值与旧仓**不互通**，但排除面
   （evidence / flags / confidence / card_id）与「输入顺序无关」保持一致。
3. ``reviewcl`` 的条目文本：旧仓用 ``venue`` / ``keywords`` / ``authors``；新 subject
   多了 ``abstract``（入词项），年份不入词项（同旧仓）。
4. ``refrec`` 依赖的 ``taw.renumber`` 内核折入本模块（``renumber`` /
   ``verify_plan``），否则 ``insert_reference`` / ``delete_reference`` 无法纯函数化。
5. ``refdedup._pair_verdict`` 的「标题模糊接近且无冲突」自动合并分支在旧仓实现里
   **不可达**：标题归一不同必然先被 ``_field_conflicts`` 记成 title 冲突，故模糊对
   一律 ``manual_confirm``。本模块忠实保留该行为（误合并率 0）。
6. ``cite`` 幽灵文献：旧仓只要出现任何数字标记就统计；本模块要求至少一条标记真的
   落到文献表，否则全是悬空引用时整张表都会被报「未被引用」（同一缺陷重复计数）。
7. ``taw-ref-card`` 增加「题名必填」（旧 ``validate_ref_card`` 未查 title；器官 api
   契约把缺 title 视为卡片级破损）。
8. 旧 ``cards.make_finding`` 的三级状态 ``pass|fail|manual_confirm`` 折算为
   ``error|warn|info``；维修 ``fix`` 挂在 ``evidence.fix``（finding 固定五键）。
9. ``reffake`` 的 ``YEAR_UPPER`` / ``YEAR_LOWER`` 是模块常量（纯函数不读时钟）；
   旧仓 ``profile_refs`` 的 ``TAW-hallu-signal-01`` 门控在 ``fake`` mode 恒为生效
   （subject 未给 ruleset 入口）。
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from itertools import combinations
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# ============================================================ 契约常量
MODES: Tuple[str, ...] = ("refcheck", "cite", "dedup", "fake", "rec", "library", "review")
VERDICTS: Tuple[str, ...] = ("error", "warn", "info")

#: ``rule_id`` 白名单（对外只准出现这些；多一个都不行）。
RULE_IDS: Tuple[str, ...] = (
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
_RULE_ID_SET = frozenset(RULE_IDS)

#: 旧三级状态 → 新 verdict（只在迁移映射处使用；新 findings 不出现旧状态）。
STATUS_VERDICT: Dict[str, str] = {
    "pass": "info",
    "fail": "error",
    "manual_confirm": "warn",
}

# ============================================================ 参数卡 schema（cards.py）
REF_ENTRY_TYPES: Tuple[str, ...] = ("J", "C", "D", "M", "R", "N", "P", "S", "A", "DB", "OL")
DOC_OBJECT_KINDS: Tuple[str, ...] = ("figure", "table", "equation", "chapter", "citation_marker")
FINDING_STATUS: Tuple[str, ...] = ("pass", "fail", "manual_confirm")

REF_SOURCE_FIELDS: Tuple[str, ...] = (
    "container", "year", "volume", "issue", "pages",
    "publisher", "city", "edition", "report_no",
)
REF_IDENTIFIER_FIELDS: Tuple[str, ...] = ("doi", "isbn", "url")
#: 新 subject 用 ``source.journal``；旧卡用 ``source.container``，迁移层等价。
SOURCE_ALIASES: Dict[str, str] = {"journal": "container"}

#: 字段 → 中文名（报告用）。
FIELD_ZH: Dict[str, str] = {
    "year": "年份", "pages": "页码", "volume": "卷号", "issue": "期号",
    "publisher": "出版社", "city": "出版地", "container": "刊名/书名",
    "edition": "版次", "report_no": "报告号",
}

#: 类型 → 缺项池（旧仓 refcheck.REQUIRED_POOL 原样）。
REQUIRED_POOL: Dict[str, Tuple[str, ...]] = {
    "J": ("year", "pages", "volume"),
    "C": ("year", "publisher", "pages"),
    "D": ("year", "city"),
    "M": ("year", "publisher", "pages"),
    "R": ("year", "city"),
}
#: 解析噪声 flag：带这些 flag 时不据此判缺项（year 豁免）。
RISKY_FLAGS: Tuple[str, ...] = (
    "linebreak_repaired", "hyphen_repaired", "space_collapsed", "cjk_space_collapsed",
)
YEAR_EXEMPT = "year"
#: 著者阈值判定的载体可见性（ris 逐条列出全部著者，不做该判定）。
AUTHOR_VISIBLE_FORMATS: Tuple[str, ...] = ("txt", "csv", "bib")

BIB_KEY_SIG: Tuple[Tuple[str, str], ...] = (
    ("journal", "J"), ("booktitle", "C"), ("school", "D"),
    ("isbn", "M"), ("edition", "M"), ("institution", "R"), ("number", "R"),
)
RIS_TAG_SIG: Tuple[Tuple[str, str], ...] = (
    ("JO", "J"), ("JF", "J"), ("T2", "C"), ("SN", "M"), ("NO", "R"),
)

#: 旧仓 ``refparse`` 的结构分支正则（本模块只搬 ``_infer_type`` 用到的五条）。
_REPORT_NO_TAIL = re.compile(r"[.,]?\s*([A-Z]{1,6}\s*-\s*\d{2,4}\s*-\s*\d{1,4})\s*\.?\s*$")
_EDITION_SEG = re.compile(r"^(\d+)\s*(?:\u7248|ed)\.?$")
_SEG_VOL_ISSUE = re.compile(r"^(\d+)\((\d+)\)$")
_SEG_ISSUE = re.compile(r"^\((\d+)\)$")
_SEG_VOL = re.compile(r"^(\d+)$")

# ============================================================ 规则包（默认全 active）
#: 内置规则包：旧仓四层叠加后的**生效子集**（status 一律 pending = 条款待核对，
#: activation=active = 检测运行，口径同旧仓 engine.M3_RULE_ACTIVATION）。
#: ``rule_id`` 直接用新白名单 id；旧 id（GBT7714-*）在 comments 里保留对照。
DEFAULT_RULESET: Dict[str, Any] = {
    "standard_year": "2025",
    "profile": "default",
    "rules": (
        # GBT7714-fieldreq-{J,C,D,M,R}-01
        {"rule_id": "taw-ref-field-required", "check_type": "field_required",
         "activation": "active", "status": "pending"},
        # GBT7714-punct-01
        {"rule_id": "taw-ref-punct", "check_type": "punct",
         "activation": "active", "status": "pending"},
        # GBT7714-author-01
        {"rule_id": "taw-ref-author-threshold", "check_type": "author_threshold",
         "activation": "active", "status": "pending"},
        # GBT7714-marker-01
        {"rule_id": "taw-ref-type-marker", "check_type": "type_marker",
         "activation": "active", "status": "pending"},
        # GBT7714-pagerange-01
        {"rule_id": "taw-ref-page-range", "check_type": "page_range",
         "activation": "active", "status": "pending"},
        # GBT7714-consistency-01
        {"rule_id": "taw-ref-consistency", "check_type": "consistency",
         "activation": "active", "status": "pending"},
        # GBT7714-currency-01
        {"rule_id": "taw-ref-standard-currency", "check_type": "standard_currency",
         "activation": "active", "status": "pending"},
        # GBT7714-citestyle-01
        {"rule_id": "taw-ref-citation-style", "check_type": "citation_style",
         "activation": "active", "status": "pending"},
        # GBT7714-cite-dangling-01 / ghost-01 / order-01 / ay-01
        {"rule_id": "taw-cite-marker", "check_type": "dangling_citation",
         "activation": "active", "status": "pending"},
        {"rule_id": "taw-cite-uncited", "check_type": "ghost_reference",
         "activation": "active", "status": "pending"},
        {"rule_id": "taw-cite-order", "check_type": "order_gap",
         "activation": "active", "status": "pending"},
        {"rule_id": "taw-cite-marker", "check_type": "author_year_mismatch",
         "activation": "active", "status": "pending"},
        # GBT7714-dedup-01（dedup mode 无 ruleset 入口，保留常量与门控语义）
        {"rule_id": "taw-dedup-pair", "check_type": "duplicate_entry",
         "activation": "active", "status": "pending"},
        # TAW-hallu-signal-01
        {"rule_id": "taw-fake-signal", "check_type": "hallucination_signal",
         "activation": "active", "status": "pending"},
    ),
}

#: 双标尺替代关系（旧仓 data/knowledge/standard_replacements.json 的 verified 子集，
#: compact 后随模块分发；无出处的条目在 ``_norm_replacements`` 里被剔除）。
DEFAULT_STANDARD_REPLACEMENTS: Tuple[Dict[str, Any], ...] = (
    {"old": "GB/T 7714-2015", "new": "GB/T 7714-2025",
     "new_implement_date": "2026-07-01", "identity_status": "verified",
     "source": "std.samr.gov.cn"},
    {"old": "GB/T 7713.1-2006", "new": "GB/T 7713.1-2025",
     "new_implement_date": "2026-02-01", "identity_status": "verified",
     "source": "std.samr.gov.cn"},
)

# ============================================================ 引用标记（refcite.py）
_NUM_BRACKET = re.compile(r"\[\s*(\d{1,3}(?:\s*[,\-\u2013\u2014\uff0d\uff0c]\s*\d{1,3})*)\s*\]")
_NUM_PART = re.compile(r"(\d{1,3})(?:\s*[-\u2013\u2014\uff0d]\s*(\d{1,3}))?")
_AY_PAREN = re.compile(
    r"[(（]\s*([A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff .&]*?)"
    r"(?:\s*(?:等|et al\.?))?\s*[,，]\s*((?:19|20)\d{2})\s*[)）]")
_AY_INLINE = re.compile(
    r"([A-Za-z\u4e00-\u9fff][A-Za-z\u4e00-\u9fff .&]{0,20}?)"
    r"(?:\s*(?:等|et al\.?))?\s*[（(]\s*((?:19|20)\d{2})\s*[)）]")

# ============================================================ 去重（refdedup.py）
_PUNCT = re.compile(
    r"[\u3000\s\-\u2013\u2014\uff0d_.,\uff0c\u3002:\uff1a;\uff1b!\uff01?\uff1f"
    r"()\uff08\uff09\[\]\u3010\u3011\"'\u201c\u201d\u2018\u2019/\\]+")

# ============================================================ 幻觉画像（reffake.py）
#: 已知注册 DOI 前缀（旧仓 KNOWN_DOI_PREFIXES）+ 合成数据白名单 10.9999。
KNOWN_DOI_PREFIXES: Tuple[str, ...] = (
    "10.1000", "10.1002", "10.1016", "10.1038", "10.1109",
    "10.1145", "10.1007", "10.1088", "10.1080", "10.1093",
    "10.1063", "10.1111", "10.1049", "10.1149", "10.1051",
    "10.9999",
)
#: 合成数据专用 ISBN 出版者段（旧仓 doi_fake_prefixes.json 的 ranges）。
DEFAULT_FAKE_ISBN_RANGES: Tuple[str, ...] = (
    "978-7-0487", "978-7-0652", "978-7-1283", "978-7-1621", "978-7-3619",
    "978-7-3772", "978-7-3941", "978-7-4038", "978-7-4836", "978-7-5246",
    "978-7-5649", "978-7-7553", "978-7-7987", "978-7-8206", "978-7-8622",
)
SIGNAL_WEIGHT: Dict[str, int] = {
    "doi_prefix_unknown": 30,
    "isbn_checksum_invalid": 25,
    "year_out_of_range": 20,
    "page_range_inverted": 15,
    "impossible_field_combo": 25,
    "self_referential_title": 10,
}
STRUCTURAL_SIGNALS: Tuple[str, ...] = (
    "page_range_inverted", "impossible_field_combo", "isbn_checksum_invalid",
)
WEAK_SIGNALS: Tuple[str, ...] = (
    "doi_prefix_unknown", "year_out_of_range", "self_referential_title",
)
#: 年份合理区间（旧仓常量；纯函数不读时钟，基准年由调用方的口径决定）。
YEAR_UPPER = 2026
YEAR_LOWER = 1900

# ============================================================ 检索 / 综述（refrec / reviewcl）
_CJK = r"\u4e00-\u9fff"
_TOKEN_EN = re.compile(r"[A-Za-z][A-Za-z\-]*|\d+(?:\.\d+)?")
_TOKEN_CJK = re.compile("[{}]+".format(_CJK))
THRESHOLD = 0.30          # 余弦聚类阈值（旧仓 reviewcl.THRESHOLD）

# ============================================================ finding 构造
def make_finding(rule_id: str, verdict: str, message: str, path: str,
                 evidence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """构造一条对外 finding（五键定长；白名单与 verdict 在这里硬断言）。"""
    if rule_id not in _RULE_ID_SET:
        raise ValueError("rule_id 不在白名单: {!r}".format(rule_id))
    if verdict not in VERDICTS:
        raise ValueError("verdict 非法: {!r}".format(verdict))
    if not isinstance(message, str) or not message:
        raise ValueError("message 必须是非空字符串")
    if not isinstance(path, str) or not path:
        raise ValueError("path 必须是非空字符串")
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence 必须是 dict")
    return {"rule_id": rule_id, "verdict": verdict, "message": message,
            "path": path, "evidence": dict(evidence)}


def summarize(findings: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """报告概览：总数 / 按 verdict / 按 rule_id（确定性：键排序）。"""
    by_verdict: Dict[str, int] = {}
    by_rule: Dict[str, int] = {}
    for f in findings:
        by_verdict[f["verdict"]] = by_verdict.get(f["verdict"], 0) + 1
        by_rule[f["rule_id"]] = by_rule.get(f["rule_id"], 0) + 1
    return {"total": len(findings),
            "by_verdict": dict(sorted(by_verdict.items())),
            "by_rule": dict(sorted(by_rule.items()))}


# ============================================================ 参数卡（cards.py 迁移）
def make_author(raw: Optional[str], family: Optional[str] = None,
                given: Optional[str] = None) -> Dict[str, Any]:
    """著者项：raw 为文献表原文写法；family/given 拆不出时为 None（宁缺）。"""
    return {"family": family, "given": given, "raw": raw}


def _strip_ws(value: Any) -> Any:
    return "".join(value.split()) if isinstance(value, str) else value


def make_ref_card(entry_type, authors, title, source=None, identifiers=None,
                  evidence=None, confidence=1.0, flags=None,
                  card_id=None) -> Dict[str, Any]:
    """RefCard 构造器（旧仓签名）：缺槽位补 None；DOI/ISBN/页码/报告号去内部空白。"""
    src = dict.fromkeys(REF_SOURCE_FIELDS)
    if source:
        for key in REF_SOURCE_FIELDS:
            if key in source:
                src[key] = source[key]
        if src["container"] is None and source.get("journal") is not None:
            src["container"] = source["journal"]
    ids = dict.fromkeys(REF_IDENTIFIER_FIELDS)
    if identifiers:
        for key in REF_IDENTIFIER_FIELDS:
            if key in identifiers:
                ids[key] = identifiers[key]
    for key in ("doi", "isbn"):
        ids[key] = _strip_ws(ids[key])
    for key in ("pages", "report_no"):
        src[key] = _strip_ws(src[key])
    ev = {"src": None, "ordinal": None, "label": None, "raw": None}
    if evidence:
        ev.update(evidence)
    card = {
        "card_id": card_id,
        "entry_type": entry_type,
        "authors": list(authors or []),
        "title": title,
        "source": src,
        "identifiers": ids,
        "evidence": ev,
        "confidence": round(float(confidence), 3),
        "flags": list(flags or []),
    }
    validate_ref_card(card)
    return card


def validate_ref_card(card: Mapping[str, Any]) -> None:
    """RefCard 契约校验；违反 → ``ValueError``（旧仓同口径，键缺失也显式报）。"""
    if not isinstance(card, Mapping):
        raise ValueError("card 必须是 dict")
    for key in ("entry_type", "authors", "title", "source", "identifiers",
                "evidence", "confidence", "flags"):
        if key not in card:
            raise ValueError("卡片缺字段: {}".format(key))
    if card["entry_type"] is not None and card["entry_type"] not in REF_ENTRY_TYPES:
        raise ValueError("entry_type 非法: {!r}".format(card["entry_type"]))
    if not 0.0 <= card["confidence"] <= 1.0:
        raise ValueError("confidence 越界: {!r}".format(card["confidence"]))
    for author in card["authors"]:
        if "raw" not in author or not author["raw"]:
            raise ValueError("author 项缺 raw: {!r}".format(author))
    if card["evidence"]["src"] is None:
        raise ValueError("evidence.src 必填（证据链纪律：无出处不落卡）")


def make_doc_object(kind, label, anchor, mentions=None, caption=None,
                    card_id=None) -> Dict[str, Any]:
    """DocObjectCard 构造器（旧仓签名；caption 为单段题注位置）。"""
    card = {
        "card_id": card_id,
        "kind": kind,
        "label": label,
        "anchor": {"para_index": anchor.get("para_index"),
                   "style": anchor.get("style"),
                   "is_ref_field": bool(anchor.get("is_ref_field", False))},
        "mentions": list(mentions or []),
        "caption": caption,
    }
    validate_doc_object(card)
    return card


def validate_doc_object(card: Mapping[str, Any]) -> None:
    if card["kind"] not in DOC_OBJECT_KINDS:
        raise ValueError("kind 非法: {!r}".format(card["kind"]))
    if not card["label"]:
        raise ValueError("label 必填（归一化标签）")
    if card["anchor"]["para_index"] is None:
        raise ValueError("anchor.para_index 必填")


# ============================================================ subject 归一（调用方显式事实）
def _norm_author(raw: Any, index: int, pos: int) -> Dict[str, Any]:
    if isinstance(raw, str):
        return make_author(raw)
    if not isinstance(raw, Mapping):
        raise ValueError("cards[{}].authors[{}] 必须是 dict 或 str".format(index, pos))
    family, given, rawtext = raw.get("family"), raw.get("given"), raw.get("raw")
    for key, value in (("family", family), ("given", given), ("raw", rawtext)):
        if value is not None and not isinstance(value, str):
            raise ValueError("cards[{}].authors[{}].{} 必须是字符串".format(index, pos, key))
    if not rawtext:
        rawtext = " ".join(part for part in (given, family) if part) or (family or "")
    return make_author(rawtext, family, given)


def _norm_card(raw: Any, index: int = 0, doc_name: Optional[str] = None) -> Dict[str, Any]:
    """旧卡 / 新 subject 卡 → 规范卡（``card_id`` + ``source.container`` 形态）。

    只做**类型**校验（类型不对 → ValueError）；语义破损（未知 entry_type、
    confidence 越界、缺 raw、缺 src）留给 ``taw-ref-card`` 上报。
    """
    if not isinstance(raw, Mapping):
        raise ValueError("cards[{}] 必须是 dict".format(index))
    card_id = raw.get("card_id")
    if card_id in (None, ""):
        card_id = raw.get("id")
    if card_id in (None, ""):
        card_id = raw.get("entry_id")
    if card_id is None or (isinstance(card_id, str) and not card_id.strip()):
        raise ValueError("cards[{}] 缺 id".format(index))
    if isinstance(card_id, bool) or not isinstance(card_id, (str, int)):
        raise ValueError("cards[{}].id 必须是字符串".format(index))
    card_id = str(card_id)

    entry_type = raw.get("entry_type")
    if entry_type is not None and not isinstance(entry_type, str):
        raise ValueError("cards[{}].entry_type 必须是字符串或 None".format(index))
    title = raw.get("title")
    if title is not None and not isinstance(title, str):
        raise ValueError("cards[{}].title 必须是字符串".format(index))

    authors_raw = raw.get("authors") or []
    if isinstance(authors_raw, (str, bytes)) or not isinstance(authors_raw, Sequence):
        raise ValueError("cards[{}].authors 必须是列表".format(index))
    authors = [_norm_author(a, index, pos) for pos, a in enumerate(authors_raw)]

    source_raw = raw.get("source") or {}
    if not isinstance(source_raw, Mapping):
        raise ValueError("cards[{}].source 必须是 dict".format(index))
    source_map: Dict[str, Any] = dict(source_raw)
    for alias, canonical in SOURCE_ALIASES.items():
        if source_map.get(canonical) is None and alias in source_map:
            source_map[canonical] = source_map[alias]
    source = dict.fromkeys(REF_SOURCE_FIELDS)
    for key in REF_SOURCE_FIELDS:
        value = source_map.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise ValueError("cards[{}].source.{} 类型不对".format(index, key))
            value = str(value)
        source[key] = value
    for key in ("pages", "report_no"):
        source[key] = _strip_ws(source[key])

    ids_raw = raw.get("identifiers") or {}
    if not isinstance(ids_raw, Mapping):
        raise ValueError("cards[{}].identifiers 必须是 dict".format(index))
    identifiers = dict.fromkeys(REF_IDENTIFIER_FIELDS)
    for key in REF_IDENTIFIER_FIELDS:
        value = ids_raw.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("cards[{}].identifiers.{} 必须是字符串".format(index, key))
        identifiers[key] = value
    for key in ("doi", "isbn"):
        identifiers[key] = _strip_ws(identifiers[key])

    evidence_raw = raw.get("evidence") or {}
    if not isinstance(evidence_raw, Mapping):
        raise ValueError("cards[{}].evidence 必须是 dict".format(index))
    evidence = {"src": None, "ordinal": None, "label": None, "raw": None}
    for key in evidence:
        if key in evidence_raw and evidence_raw[key] is not None:
            evidence[key] = evidence_raw[key]
    if evidence["src"] is None:
        evidence["src"] = raw.get("src") or doc_name
    if evidence["raw"] is None:
        evidence["raw"] = raw.get("raw")
    if evidence["label"] is None:
        evidence["label"] = raw.get("label")
    if evidence["ordinal"] is None:
        evidence["ordinal"] = raw.get("ordinal")
    for key in ("src", "raw", "label"):
        if evidence[key] is not None and not isinstance(evidence[key], str):
            raise ValueError("cards[{}].evidence.{} 必须是字符串".format(index, key))
    if evidence["ordinal"] is not None and (
            isinstance(evidence["ordinal"], bool)
            or not isinstance(evidence["ordinal"], int)):
        raise ValueError("cards[{}].evidence.ordinal 必须是整数".format(index))

    confidence = raw.get("confidence", 1.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("cards[{}].confidence 必须是数字".format(index))

    flags_raw = raw.get("flags") or []
    if isinstance(flags_raw, (str, bytes)) or not isinstance(flags_raw, Sequence):
        raise ValueError("cards[{}].flags 必须是列表".format(index))
    flags = []
    for flag in flags_raw:
        if not isinstance(flag, str):
            raise ValueError("cards[{}].flags 必须是字符串列表".format(index))
        flags.append(flag)

    return {
        "card_id": card_id,
        "entry_type": entry_type,
        "authors": authors,
        "title": title,
        "source": source,
        "identifiers": identifiers,
        "evidence": evidence,
        "confidence": round(float(confidence), 3),
        "flags": flags,
    }


def _cards(subject: Mapping[str, Any], key: str = "cards",
           doc_name: Optional[str] = None) -> List[Dict[str, Any]]:
    raw = subject.get(key)
    if raw is None:
        raise ValueError("subject.{} 必填".format(key))
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence):
        raise ValueError("subject.{} 必须是列表".format(key))
    return [_norm_card(card, idx, doc_name) for idx, card in enumerate(raw)]


# ============================================================ 参数卡自检（taw-ref-card）
def _check_card(cards: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for card in cards:
        cid = card["card_id"]
        seen[cid] = seen.get(cid, 0) + 1
        if seen[cid] == 2:
            findings.append(make_finding(
                "taw-ref-card", "error",
                "卡片 {} 重复（同 id 出现多次）".format(cid),
                "card:{}".format(cid),
                {"card_id": cid, "duplicate": True}))
        if not card["title"]:
            findings.append(make_finding(
                "taw-ref-card", "error",
                "卡片缺题名（title 必填）",
                "card:{}/title".format(cid),
                {"card_id": cid, "field": "title"}))
        if card["entry_type"] is not None and card["entry_type"] not in REF_ENTRY_TYPES:
            findings.append(make_finding(
                "taw-ref-card", "error",
                "entry_type {!r} 不在 RefCard 允许类型内".format(card["entry_type"]),
                "card:{}/entry_type".format(cid),
                {"card_id": cid, "field": "entry_type",
                 "value": card["entry_type"], "allowed": list(REF_ENTRY_TYPES)}))
        confidence = card["confidence"]
        if not 0.0 <= confidence <= 1.0:
            findings.append(make_finding(
                "taw-ref-card", "error",
                "confidence {} 越界 [0, 1]".format(confidence),
                "card:{}/confidence".format(cid),
                {"card_id": cid, "field": "confidence", "value": confidence}))
        for pos, author in enumerate(card["authors"]):
            if not author.get("raw"):
                findings.append(make_finding(
                    "taw-ref-card", "error",
                    "著者项缺 raw（第 {} 位）".format(pos + 1),
                    "card:{}/authors".format(cid),
                    {"card_id": cid, "field": "authors", "position": pos}))
        if card["evidence"]["src"] is None:
            findings.append(make_finding(
                "taw-ref-card", "error",
                "evidence.src 缺失（无出处不落卡）",
                "card:{}/evidence".format(cid),
                {"card_id": cid, "field": "evidence.src"}))
    return findings


# ============================================================ refcheck（refcheck.py 迁移）
def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", value or "")


def _carrier_fields(cards: Sequence[Mapping[str, Any]]) -> set:
    """本批次卡片实际出现过的字段集合（载体可表达性校准）。"""
    present = set()
    for card in cards:
        for key, value in card["source"].items():
            if value:
                present.add(key)
    return present


def _carrier_aware(pool: Sequence[str], carrier: set) -> List[str]:
    return [field for field in pool if field in carrier]


def _infer_type(card: Mapping[str, Any], fmt: Optional[str],
                raw_block: Optional[str]) -> Optional[str]:
    """载体原生结构签名 → 类型；签名不唯一/缺失 → None（保守，不判）。"""
    if fmt == "bib":
        blob = _compact(raw_block)
        hits = set()
        for key, entry_type in BIB_KEY_SIG:
            if (key + "={") in blob:
                hits.add(entry_type)
        # number 在 J(期号) 与 R(报告号) 共用：有 journal 时归 J
        if "J" in hits and "R" in hits and "booktitle" not in blob:
            hits.discard("R")
        return hits.pop() if len(hits) == 1 else None
    if fmt == "ris":
        blob = _compact(raw_block)
        hits = set()
        for tag, entry_type in RIS_TAG_SIG:
            if re.search(re.escape(tag) + r"-", blob):
                hits.add(entry_type)
        return hits.pop() if len(hits) == 1 else None
    # txt / csv（以及未声明载体）：用清洗后 raw 的结构分支（旧仓 _walk_body 同口径）
    raw = card["evidence"]["raw"] or ""
    body = (raw.split("]", 1)[-1] if "]" in raw else raw).strip().lstrip(".\u3002\uff0c, ").strip()
    if not body:
        return None
    if body.startswith("//"):
        return "C"
    if _REPORT_NO_TAIL.search(body):
        return "R"
    segments = body.split(", ")
    if segments and segments[0] and _EDITION_SEG.match(segments[0]):
        return "M"
    for segment in segments:
        if (_SEG_VOL_ISSUE.match(segment) or _SEG_ISSUE.match(segment)
                or _SEG_VOL.match(segment)):
            return "J"
    return None


def _raw_blocks(fmt: Optional[str], src_text: Optional[str]) -> Dict[int, Any]:
    """原始文本 → {序位/标签: 块文本}（bib 按 @ 块、ris 按 TY..ER、txt 按 [n] 标签）。"""
    if src_text is None:
        return {}
    text = src_text.replace("\r\n", "\n")
    blocks: Dict[Any, Any] = {}
    if fmt == "bib":
        index = 0
        for block in re.split(r"\n(?=@)", text):
            if "@" not in block:
                continue
            index += 1
            blocks[index] = block
        return blocks
    if fmt == "ris":
        index = 0
        current = None
        for line in text.split("\n"):
            if line.strip().startswith("TY"):
                index += 1
                current = [line]
                blocks[index] = current
            elif current is not None:
                current.append(line)
        return {key: "\n".join(value) for key, value in blocks.items()}
    if fmt == "txt":
        current = None
        label_to_block: Dict[str, List[str]] = {}
        for line in text.split("\n"):
            if not line.strip():
                continue
            match = re.match(r"^\[\s*(\d{1,3}(?:\s+\d{1,3})*)\s*\]\s*", line.strip())
            if match:
                current = re.sub(r"\s+", "", match.group(1))
                label_to_block[current] = [line.strip()[match.end():]]
            elif current is not None:
                label_to_block[current].append(line)
        return label_to_block
    return {}


def _lookup_raw(fmt: Optional[str], blocks: Mapping[Any, Any],
                card: Mapping[str, Any]) -> Optional[str]:
    """按 card 的标签（txt）/序位（bib/ris）取原始块；取不到给 None。"""
    if not blocks:
        return None
    if fmt == "txt":
        return "".join(blocks.get(card["evidence"]["label"] or "", [])) or None
    return blocks.get(card["evidence"]["ordinal"])


def _effective_type(card: Mapping[str, Any], fmt: Optional[str],
                    blocks: Mapping[Any, Any]) -> Optional[str]:
    """该卡片用于缺项判定的类型：结构签名优先（与 type_marker 判据一致）。"""
    inferred = _infer_type(card, fmt, _lookup_raw(fmt, blocks, card) or "")
    return inferred if inferred is not None else card["entry_type"]


def _check_field_required(cards: Sequence[Mapping[str, Any]], doc_name: str,
                          carrier: set, entry_type: Optional[str] = None
                          ) -> List[Dict[str, Any]]:
    """缺项：类型池 + 载体可表达性 + 噪声门控（year 豁免）。"""
    findings: List[Dict[str, Any]] = []
    for card in cards:
        active_type = entry_type if entry_type is not None else card["entry_type"]
        pool = REQUIRED_POOL.get(active_type)
        if pool is None:
            continue
        risky = bool(set(card["flags"]) & set(RISKY_FLAGS))
        for field in _carrier_aware(pool, carrier):
            if risky and field != YEAR_EXEMPT:
                continue
            if card["source"].get(field):
                continue
            field_zh = FIELD_ZH.get(field, field)
            findings.append(make_finding(
                "taw-ref-field-required", "error",
                "{} 条目缺少{}".format(active_type, field_zh),
                "card:{}/{}".format(card["card_id"], field),
                {"card_id": card["card_id"], "field": field,
                 "field_zh": field_zh, "entry_type": active_type,
                 "carrier_fields": sorted(carrier),
                 "risky_flags": sorted(set(card["flags"]) & set(RISKY_FLAGS))}))
    return findings


def _check_type_marker(cards: Sequence[Mapping[str, Any]], doc_name: str,
                       fmt: Optional[str], blocks: Mapping[Any, Any]
                       ) -> List[Dict[str, Any]]:
    """标识错误：声明标识 vs 载体原生结构签名不符（签名唯一才判）。"""
    findings: List[Dict[str, Any]] = []
    for card in cards:
        declared = card["entry_type"]
        inferred = _infer_type(card, fmt, _lookup_raw(fmt, blocks, card) or "")
        if inferred is None or declared is None or inferred == declared:
            continue
        findings.append(make_finding(
            "taw-ref-type-marker", "error",
            "声明标识 [{}] 与载体结构（{} 型）不符".format(declared, inferred),
            "card:{}/entry_type".format(card["card_id"]),
            {"card_id": card["card_id"], "declared": declared,
             "inferred": inferred, "fmt": fmt,
             "fix": {"type": "auto", "field": "entry_type",
                     "before": declared, "after": inferred}}))
    return findings


def _check_author_threshold(cards: Sequence[Mapping[str, Any]], doc_name: str,
                            fmt: Optional[str], strict: bool = False
                            ) -> List[Dict[str, Any]]:
    """>3 未截断 / <3 误加'等' → error；恰 3 带等（严格模式）→ warn 人工复核。"""
    if fmt not in AUTHOR_VISIBLE_FORMATS:
        return []
    findings: List[Dict[str, Any]] = []
    for card in cards:
        count = len(card["authors"])
        truncated = "authors_truncated" in card["flags"]
        path = "card:{}/authors".format(card["card_id"])
        if count > 3 and not truncated:
            listed = [author["raw"] for author in card["authors"]]
            western = bool(listed) and not re.search(r"[\u4e00-\u9fff]", " ".join(listed))
            findings.append(make_finding(
                "taw-ref-author-threshold", "error",
                "列出 {} 位著者未按'前三+等'截断".format(count),
                path,
                {"card_id": card["card_id"], "authors_listed": count,
                 "truncated": False,
                 "fix": {"type": "auto", "field": "authors", "before": listed,
                         "after": listed[:3] + ["et al" if western else "等"]}}))
        elif truncated and count < 3:
            findings.append(make_finding(
                "taw-ref-author-threshold", "error",
                "仅 {} 位著者却使用'等'".format(count),
                path,
                {"card_id": card["card_id"], "authors_listed": count,
                 "truncated": True,
                 "fix": {"type": "auto", "field": "authors",
                         "before": [author["raw"] for author in card["authors"]] + ["等"],
                         "after": [author["raw"] for author in card["authors"]]}}))
        elif truncated and count == 3 and strict:
            findings.append(make_finding(
                "taw-ref-author-threshold", "warn",
                "恰列出 3 位著者且带'等'：原著者数可能恰为 3（误加），也可能 >3（正确截断）",
                path,
                {"card_id": card["card_id"], "authors_listed": count,
                 "truncated": True, "ambiguous": True}))
    return findings


def _check_page_range(cards: Sequence[Mapping[str, Any]], doc_name: str
                      ) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for card in cards:
        pages = card["source"].get("pages")
        if not pages:
            continue
        match = re.match(r"^(\d+)\s*-\s*(\d+)$", pages)
        if not match:
            continue
        start, end = int(match.group(1)), int(match.group(2))
        if start > end:
            findings.append(make_finding(
                "taw-ref-page-range", "error",
                "页码倒置 {}-{}".format(start, end),
                "card:{}/pages".format(card["card_id"]),
                {"card_id": card["card_id"], "pages": pages,
                 "start": start, "end": end,
                 "fix": {"type": "auto", "field": "pages", "before": pages,
                         "after": "{}-{}".format(end, start)}}))
    return findings


def _check_citation_style(cards: Sequence[Mapping[str, Any]], doc_name: str
                          ) -> List[Dict[str, Any]]:
    """编码制混用：文件级 finding（无 [n] 标签的著者-出版年制条目混入）。"""
    mixed = [card for card in cards
             if card["evidence"]["label"] is None
             and "author_year_form" in card["flags"]]
    if not mixed:
        return []
    return [make_finding(
        "taw-ref-citation-style", "error",
        "文献表混入 {} 条著者-出版年制条目（顺序编码制表中无 [n] 编号）".format(len(mixed)),
        "report",
        {"doc": doc_name, "mixed_count": len(mixed),
         "mixed_ids": [card["card_id"] for card in mixed]})]


def _norm_replacements(replacements: Optional[Sequence[Mapping[str, Any]]]
                       ) -> List[Dict[str, Any]]:
    """替代关系归一（旧仓 load_replacements：只收 verified 且有出处的条目）。"""
    if replacements is None:
        replacements = DEFAULT_STANDARD_REPLACEMENTS
    if isinstance(replacements, (str, bytes)) or not isinstance(replacements, Sequence):
        raise ValueError("replacements 必须是列表")
    out: List[Dict[str, Any]] = []
    for item in replacements:
        if not isinstance(item, Mapping):
            raise ValueError("replacements 条目必须是 dict")
        if not isinstance(item.get("old"), str) or not isinstance(item.get("new"), str):
            raise ValueError("replacements 条目必须含 old/new 字符串")
        if item.get("identity_status") not in (None, "verified"):
            continue
        if not item.get("source"):
            continue
        out.append(dict(item))
    return out


def _check_standard_currency(cards: Sequence[Mapping[str, Any]], doc_name: str,
                             replacements: Optional[Sequence[Mapping[str, Any]]] = None
                             ) -> List[Dict[str, Any]]:
    """双标尺：条目引用的标准若已被新版替代 → warn（可解释：按旧版年份著录）。"""
    table = _norm_replacements(replacements)
    if not table:
        return []
    by_old = {item["old"]: item for item in table}
    findings: List[Dict[str, Any]] = []
    for card in cards:
        text = " ".join(filter(None, [card.get("title"),
                                      card["source"].get("container"),
                                      card["source"].get("report_no")]))
        for old in sorted(by_old):
            if old not in text:
                continue
            replacement = by_old[old]
            implement = replacement.get("new_implement_date") or "已实施"
            findings.append(make_finding(
                "taw-ref-standard-currency", "warn",
                "引用的标准 {} 已废止（{} 于 {} 实施替代）".format(
                    old, replacement["new"], implement),
                "card:{}/standard_ref".format(card["card_id"]),
                {"card_id": card["card_id"], "old": old,
                 "new": replacement["new"],
                 "new_implement_date": replacement.get("new_implement_date"),
                 "fix": {"type": "suggest", "field": "standard_ref",
                         "before": old, "after": replacement["new"]}}))
    return findings


def _check_consistency(cards: Sequence[Mapping[str, Any]], doc_name: str
                       ) -> List[Dict[str, Any]]:
    """结构矛盾：DOI 年份段与出版年不一致（年份必须规范 4 位才判）。"""
    findings: List[Dict[str, Any]] = []
    for card in cards:
        doi = card["identifiers"].get("doi")
        year = card["source"].get("year")
        if not doi or not year or not re.match(r"^(?:19|20)\d{2}$", str(year)):
            continue
        match = re.search(r"/(?:[a-z]+\.)?((?:19|20)\d{2})\.", doi)
        if not match:
            continue
        doi_year = match.group(1)
        if doi_year != year:
            findings.append(make_finding(
                "taw-ref-consistency", "error",
                "DOI 年份段 {} 与出版年 {} 矛盾".format(doi_year, year),
                "card:{}/doi".format(card["card_id"]),
                {"card_id": card["card_id"], "doi": doi,
                 "doi_year": doi_year, "year": year}))
    return findings


def _check_punct(cards: Sequence[Mapping[str, Any]], doc_name: str,
                 fmt: Optional[str], blocks: Mapping[Any, Any]
                 ) -> List[Dict[str, Any]]:
    """标点：清洗已归一全角，故在残留 flag / 原文 / bib 字段行上判。"""
    findings: List[Dict[str, Any]] = []
    for card in cards:
        raw_clean = card["evidence"]["raw"] or ""
        raw_orig = _lookup_raw(fmt, blocks, card)
        detail = None
        if fmt in ("txt", "csv"):
            if "authors_title_separator_missing" in card["flags"]:
                detail = "题名前著录分隔（'. '）缺失"
            else:
                match = re.search(r"[\u4e00-\u9fff],(?=[\u4e00-\u9fff])", raw_clean)
                if match:
                    detail = "中文逗号残留（应为', '）"
                elif re.search(r"[,.]\s*[,.]\s*$", raw_clean.rstrip()):
                    detail = "条目末尾多余标点"
                elif raw_orig is not None and re.search(r"[\uff0c\uff1a]", raw_orig):
                    detail = "著录标点使用全角（，/：）"
        elif fmt == "bib" and raw_orig is not None:
            for line in raw_orig.replace("\r", "").split("\n"):
                if re.match(r"^\s*auth?or\s*=", line):
                    stripped = line.rstrip()
                    if stripped.endswith("}") and not stripped.endswith("},"):
                        detail = "著者字段行末缺逗号"
                    break
        if detail:
            findings.append(make_finding(
                "taw-ref-punct", "warn", detail,
                "card:{}/punctuation".format(card["card_id"]),
                {"card_id": card["card_id"], "detail": detail, "fmt": fmt}))
    return findings


def is_active(rule: Mapping[str, Any]) -> bool:
    """规则生效门控（旧仓 engine.is_active：显式 activation 优先，缺省回退 verified）。"""
    activation = rule.get("activation")
    if activation is not None:
        return activation == "active"
    return rule.get("status") == "verified"


def _resolve_ruleset(ruleset: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if ruleset is None:
        return DEFAULT_RULESET
    if not isinstance(ruleset, Mapping):
        raise ValueError("subject.ruleset 必须是 dict")
    rules = ruleset.get("rules")
    if rules is None:
        rules = ()
    if isinstance(rules, (str, bytes)) or not isinstance(rules, Sequence):
        raise ValueError("ruleset.rules 必须是列表")
    out: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, Mapping):
            raise ValueError("ruleset.rules 条目必须是 dict")
        rule_id, check_type = rule.get("rule_id"), rule.get("check_type")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError("rule_id 缺失")
        if not isinstance(check_type, str) or not check_type:
            raise ValueError("check_type 缺失：{}".format(rule_id))
        out.append(dict(rule))
    return {"rules": tuple(out)}


def _rule_for(ruleset: Mapping[str, Any], check_type: str
              ) -> Optional[Mapping[str, Any]]:
    for rule in ruleset.get("rules", ()):
        if rule.get("check_type") == check_type and is_active(rule):
            return rule
    return None


def check_format(cards: Sequence[Mapping[str, Any]], ruleset=None, fmt=None,
                 src_text=None, doc_name=None, replacements=None
                 ) -> Dict[str, Any]:
    """REF-02 主入口（旧仓 check_format）→ {findings, fixes, summary}。"""
    resolved = _resolve_ruleset(ruleset)
    if fmt is not None and fmt not in ("bib", "ris", "txt", "csv"):
        raise ValueError("fmt 非法: {!r}".format(fmt))
    if src_text is not None and not isinstance(src_text, str):
        raise ValueError("src_text 必须是字符串")
    if doc_name is not None and not isinstance(doc_name, str):
        raise ValueError("doc_name 必须是字符串")
    doc_name = doc_name or (cards[0]["evidence"]["src"] if cards else "refs")
    blocks = _raw_blocks(fmt, src_text)
    carrier = _carrier_fields(cards)
    findings: List[Dict[str, Any]] = []

    if _rule_for(resolved, "field_required") is not None:
        # 每条卡片只在一个有效类型池下判（标识与结构不符时以结构签名为准）
        for entry_type in REQUIRED_POOL:
            subset = [card for card in cards
                      if _effective_type(card, fmt, blocks) == entry_type]
            if subset:
                findings.extend(_check_field_required(
                    subset, doc_name, carrier, entry_type=entry_type))

    checks = (
        ("type_marker", _check_type_marker, {"fmt": fmt, "blocks": blocks}),
        ("author_threshold", _check_author_threshold, {"fmt": fmt}),
        ("page_range", _check_page_range, {}),
        ("consistency", _check_consistency, {}),
        ("citation_style", _check_citation_style, {}),
        ("punct", _check_punct, {"fmt": fmt, "blocks": blocks}),
    )
    for check_type, function, kwargs in checks:
        if _rule_for(resolved, check_type) is None:
            continue
        findings.extend(function(cards, doc_name, **kwargs))

    if _rule_for(resolved, "standard_currency") is not None:
        findings.extend(_check_standard_currency(cards, doc_name, replacements))

    return {
        "findings": findings,
        "fixes": [finding["evidence"]["fix"] for finding in findings
                  if finding["evidence"].get("fix")],
        "summary": summarize(findings),
    }


def apply_fix(card: Mapping[str, Any], fix: Mapping[str, Any]) -> Dict[str, Any]:
    """把一条字段级 fix 落到卡片副本（供逐条接受/回退），并同步派生标志。"""
    new = copy.deepcopy(card)
    field = fix["field"]
    if field == "entry_type":
        new["entry_type"] = fix["after"]
    elif field == "pages":
        new["source"]["pages"] = fix["after"]
    elif field == "authors":
        built: List[Dict[str, Any]] = []
        truncated = bool(fix.get("after")) and fix["after"][-1] in ("等", "et al")
        for raw in fix["after"]:
            if raw in ("等", "et al"):
                prev = built[-1]
                built[-1] = make_author(prev["raw"] + ", " + raw,
                                        prev["family"], prev["given"])
            else:
                built.append(make_author(raw))
        new["authors"] = built
        if truncated and "authors_truncated" not in new["flags"]:
            new["flags"] = sorted(set(new["flags"]) | {"authors_truncated"})
        elif not truncated and "authors_truncated" in new["flags"]:
            new["flags"] = [flag for flag in new["flags"] if flag != "authors_truncated"]
    return new


# ============================================================ cite（refcite.py 迁移）
def expand_numbers(spec: str) -> List[int]:
    """``2,5-7`` → [2, 5, 6, 7]（区间升序展开；单值原样）。"""
    out: List[int] = []
    for part in re.split(r"[,\uff0c]", spec):
        part = part.strip()
        if not part:
            continue
        match = _NUM_PART.fullmatch(part)
        if not match:
            continue
        start = int(match.group(1))
        if match.group(2) is None:
            out.append(start)
        else:
            end = int(match.group(2))
            low, high = (start, end) if start <= end else (end, start)
            out.extend(range(low, high + 1))
    return out


def _sentence_of(text: str, pos: int) -> str:
    start = max(text.rfind(char, 0, pos) for char in "。！？.!?；;\n") + 1
    end = min([index for index in (text.find(char, pos) for char in "。！？.!?；;\n")
               if index != -1] or [len(text)])
    return text[start:end].strip()


def parse_markers(text: str, doc_name: str = "body") -> List[Dict[str, Any]]:
    """正文 → [marker]；marker = {kind, numbers|author,year, label, para, pos, context}."""
    if not isinstance(text, str):
        raise ValueError("text 必须是字符串")
    markers: List[Dict[str, Any]] = []
    for para_index, para in enumerate(text.split("\n")):
        for match in _NUM_BRACKET.finditer(para):
            numbers = expand_numbers(match.group(1))
            if not numbers:
                continue
            markers.append({"kind": "numeric", "numbers": numbers,
                            "label": re.sub(r"\s+", "", match.group(1)),
                            "para": para_index, "pos": match.start(),
                            "doc": doc_name,
                            "context": _sentence_of(para, match.start())})
        for pattern in (_AY_PAREN, _AY_INLINE):
            for match in pattern.finditer(para):
                markers.append({"kind": "author_year",
                                "author": match.group(1).strip().rstrip(".,，"),
                                "year": match.group(2), "para": para_index,
                                "pos": match.start(), "doc": doc_name,
                                "context": _sentence_of(para, match.start())})
    return markers


def _refs_by_label(cards: Sequence[Mapping[str, Any]]) -> Dict[int, Mapping[str, Any]]:
    """RefCard → {int(label): card}（label 形如 '1,2' 的合并编号取首值）。"""
    out: Dict[int, Mapping[str, Any]] = {}
    for card in cards:
        label = card["evidence"].get("label")
        if not label:
            continue
        numbers = expand_numbers(str(label))
        if numbers:
            out[numbers[0]] = card
    return out


def _author_key(name: Optional[str]) -> str:
    """人名归一：取姓（中文首字 / 西文首 token），小写。"""
    name = (name or "").strip()
    if not name:
        return ""
    if re.search(r"[\u4e00-\u9fff]", name):
        return name[0]
    return name.split()[0].lower().rstrip(".,")


def reconcile(cards: Sequence[Mapping[str, Any]], markers: Sequence[Mapping[str, Any]],
              ruleset=None, doc_name: str = "body") -> Dict[str, Any]:
    """REF-04 主入口（旧仓 reconcile）→ {findings, cited_numbers, table_numbers}。"""
    resolved = _resolve_ruleset(ruleset)
    by_label = _refs_by_label(cards)
    findings: List[Dict[str, Any]] = []
    cited_numbers: set = set()

    def marker_path(marker: Mapping[str, Any]) -> str:
        doc = marker.get("doc") or doc_name
        return "marker:{}@{}".format(doc, marker.get("pos", 0))

    rule = _rule_for(resolved, "dangling_citation")
    if rule is not None:
        for marker in markers:
            if marker["kind"] != "numeric":
                continue
            for number in marker["numbers"]:
                cited_numbers.add(number)
                if number not in by_label:
                    findings.append(make_finding(
                        "taw-cite-marker", "error",
                        "正文引用 [{}] 在文献表中不存在".format(number),
                        marker_path(marker),
                        {"kind": "numeric", "ref_no": number,
                         "numbers": list(marker["numbers"]),
                         "label": marker.get("label"),
                         "para": marker.get("para")}))

    rule = _rule_for(resolved, "ghost_reference")
    # 至少一条正文标记真的落到文献表时才统计幽灵文献：若全是悬空引用，
    # 整张表都会"未被引用"，那是同一缺陷的重复计数（口径调整见模块 docstring）。
    if rule is not None and (cited_numbers & set(by_label)):
        for number in sorted(by_label):
            if number in cited_numbers:
                continue
            card = by_label[number]
            findings.append(make_finding(
                "taw-cite-uncited", "warn",
                "文献表条目 [{}] 在正文中从未被引用".format(number),
                "card:{}".format(card["card_id"]),
                {"ref_no": number, "label": card["evidence"].get("label"),
                 "card_id": card["card_id"]}))

    rule = _rule_for(resolved, "order_gap")
    if rule is not None:
        first_seen: List[int] = []
        for marker in markers:
            if marker["kind"] != "numeric":
                continue
            for number in marker["numbers"]:
                if number not in first_seen:
                    first_seen.append(number)
        descending = [(a, b) for a, b in zip(first_seen, first_seen[1:]) if b < a]
        if descending:
            findings.append(make_finding(
                "taw-cite-order", "warn",
                "首次引用顺序非升序：{}（如 {} 先于 {}）".format(
                    first_seen, descending[0][0], descending[0][1]),
                "report",
                {"first_seen": first_seen, "descending_pair": list(descending[0]),
                 "doc": doc_name}))
        if by_label:
            high = max(by_label)
            missing = [number for number in range(1, high + 1) if number not in by_label]
            if missing:
                findings.append(make_finding(
                    "taw-cite-order", "error",
                    "文献表编号存在空档：缺 {}".format(missing),
                    "report",
                    {"missing": missing, "max_label": high, "doc": doc_name}))

    rule = _rule_for(resolved, "author_year_mismatch")
    if rule is not None:
        for marker in markers:
            if marker["kind"] != "author_year":
                continue
            key = _author_key(marker["author"])
            candidates = [card for card in cards
                          if any(_author_key(author.get("family") or author["raw"]) == key
                                 for author in card["authors"])]
            if not candidates:
                findings.append(make_finding(
                    "taw-cite-marker", "error",
                    "正文引用 '{}（{}）' 在文献表中无同著者条目".format(
                        marker["author"], marker["year"]),
                    marker_path(marker),
                    {"kind": "author_year", "author": marker["author"],
                     "year": marker["year"], "para": marker.get("para")}))
                continue
            if not any(card["source"].get("year") == marker["year"]
                       for card in candidates):
                findings.append(make_finding(
                    "taw-cite-marker", "warn",
                    "正文 '{}（{}）' 与文献表年份不符（表内为 {}）".format(
                        marker["author"], marker["year"],
                        sorted({str(card["source"].get("year")) for card in candidates})),
                    marker_path(marker),
                    {"kind": "author_year", "author": marker["author"],
                     "year": marker["year"],
                     "table_years": sorted({str(card["source"].get("year"))
                                            for card in candidates})}))

    return {"findings": findings,
            "cited_numbers": sorted(cited_numbers),
            "table_numbers": sorted(by_label),
            "summary": summarize(findings)}


# ============================================================ dedup（refdedup.py 迁移）
def norm_title(title: Optional[str]) -> str:
    """标题归一：全角转半角、小写、去标点与空白。空标题 → ''。"""
    if not title:
        return ""
    out = []
    for char in title:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif char == "\u3000":
            out.append(" ")
        else:
            out.append(char)
    return _PUNCT.sub("", "".join(out).lower())


def norm_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    return re.sub(r"\s+", "", doi).lower().rstrip(".")


def _author_families(card: Mapping[str, Any]) -> set:
    families = set()
    for author in card["authors"]:
        family = author.get("family") or author.get("raw") or ""
        family = re.sub(r"\s+", "", family).lower()
        if family:
            families.add(family)
    return families


def _levenshtein(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, char_left in enumerate(left, 1):
        current = [i]
        for j, char_right in enumerate(right, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (char_left != char_right)))
        previous = current
    return previous[-1]


def _field_conflicts(a: Mapping[str, Any], b: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """两卡片的冲突字段：同字段都有值且不等（含 source/identifiers）。"""
    conflicts: List[Dict[str, Any]] = []
    value_a, value_b = a.get("title"), b.get("title")
    if value_a and value_b and value_a != value_b:
        conflicts.append({"field": "title", "a": value_a, "b": value_b})
    for group in ("source", "identifiers"):
        for key in sorted(set(a[group]) | set(b[group])):
            value_a, value_b = a[group].get(key), b[group].get(key)
            if value_a and value_b and str(value_a) != str(value_b):
                conflicts.append({"field": key, "a": value_a, "b": value_b})
    families_a, families_b = _author_families(a), _author_families(b)
    if families_a and families_b and not (families_a & families_b):
        conflicts.append({"field": "authors", "a": sorted(families_a),
                          "b": sorted(families_b)})
    return conflicts


def _pair_verdict(a: Mapping[str, Any], b: Mapping[str, Any], edit_threshold: int = 2
                  ) -> Tuple[Optional[str], Optional[str], List[Dict[str, Any]]]:
    """两卡片关系判定 → (verdict, reason, conflicts)；verdict ∈ duplicate/manual_confirm/None。"""
    doi_a, doi_b = norm_doi(a["identifiers"].get("doi")), norm_doi(b["identifiers"].get("doi"))
    title_a, title_b = norm_title(a.get("title")), norm_title(b.get("title"))
    conflicts = _field_conflicts(a, b)

    if doi_a and doi_b and doi_a == doi_b:
        return ("duplicate", "DOI 精确匹配", conflicts)
    if title_a and title_b and title_a == title_b:
        families_a, families_b = _author_families(a), _author_families(b)
        year_a, year_b = a["source"].get("year"), b["source"].get("year")
        if conflicts:
            return ("manual_confirm", "标题归一相同但存在冲突字段", conflicts)
        if (families_a and families_b and (families_a & families_b)
                and (not year_a or not year_b or year_a == year_b)):
            return ("duplicate", "标题归一相同 + 著者交集 + 年份一致", conflicts)
        return ("manual_confirm", "标题归一相同但著者/年份证据不足", conflicts)
    if title_a and title_b and _levenshtein(title_a, title_b) <= edit_threshold:
        families_a, families_b = _author_families(a), _author_families(b)
        container_a, container_b = a["source"].get("container"), b["source"].get("container")
        positive = bool(families_a & families_b) or bool(
            container_a and container_b and container_a == container_b)
        year_a, year_b = a["source"].get("year"), b["source"].get("year")
        if positive and not conflicts and families_a & families_b and year_a and year_b \
                and year_a == year_b:
            return ("duplicate", "标题模糊接近 + 著者交集 + 年份一致", [])
        if positive:
            return ("manual_confirm", "标题模糊接近但证据不足以硬合", conflicts)
        return (None, None, [])
    return (None, None, [])


def _empty_slots(card: Mapping[str, Any]) -> int:
    count = 0
    if not card.get("title"):
        count += 1
    for value in card["source"].values():
        if not value:
            count += 1
    for value in card["identifiers"].values():
        if not value:
            count += 1
    return count


def _uniq_conflicts(conflicts: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for conflict in conflicts:
        key = (conflict["field"], str(conflict["a"]), str(conflict["b"]))
        if key not in seen:
            seen.add(key)
            out.append(conflict)
    return out


def _label_of(card: Mapping[str, Any]) -> str:
    label = card["evidence"].get("label")
    return "[{}]".format(label) if label else "[?]"


def find_duplicates(cards: Sequence[Mapping[str, Any]], edit_threshold: int = 2
                    ) -> Dict[str, Any]:
    """→ {clusters, manual_pairs, findings}（误合并率 0：冲突一律转人工确认）。"""
    if isinstance(edit_threshold, bool) or not isinstance(edit_threshold, int) \
            or edit_threshold < 0:
        raise ValueError("edit_threshold 必须是非负整数")
    count = len(cards)
    parent = list(range(count))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            parent[root_y] = root_x

    dup_pairs: List[Tuple[int, int, str, List[Dict[str, Any]]]] = []
    manual_pairs: List[Tuple[int, int, str, List[Dict[str, Any]]]] = []
    for i, j in combinations(range(count), 2):
        verdict, reason, conflicts = _pair_verdict(cards[i], cards[j], edit_threshold)
        if verdict == "duplicate":
            union(i, j)
            dup_pairs.append((i, j, reason or "", conflicts))
        elif verdict == "manual_confirm":
            manual_pairs.append((i, j, reason or "", conflicts))

    clusters: Dict[int, List[int]] = {}
    for index in range(count):
        clusters.setdefault(find(index), []).append(index)

    clusters_out: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    for _root, members in sorted(clusters.items()):
        if len(members) < 2:
            continue
        keep = min(members, key=lambda member: (_empty_slots(cards[member]), member))
        drop = [member for member in members if member != keep]
        conflicts: List[Dict[str, Any]] = []
        for i, j, _reason, pair_conflicts in dup_pairs:
            if i in members and j in members:
                conflicts.extend(pair_conflicts)
        uniq = _uniq_conflicts(conflicts)
        cluster = {
            "entry_ids": [cards[member]["card_id"] for member in members],
            "labels": [cards[member]["evidence"].get("label") for member in members],
            "keep": cards[keep]["card_id"],
            "drop": [cards[member]["card_id"] for member in drop],
            "verdict": "duplicate",
            "reason": next((reason for i, j, reason, _ in dup_pairs
                            if i in members and j in members), ""),
            "conflicts": uniq,
        }
        clusters_out.append(cluster)
        for member in drop:
            findings.append(make_finding(
                "taw-dedup-pair", "error",
                "重复条目 {} / {}（{}）；保留 {}，合并 {}".format(
                    _label_of(cards[keep]), _label_of(cards[member]),
                    cluster["reason"], cards[keep]["card_id"], cards[member]["card_id"]),
                "pair:{}:{}".format(cards[keep]["card_id"], cards[member]["card_id"]),
                {"keep": cards[keep]["card_id"], "drop": cards[member]["card_id"],
                 "cluster": cluster, "conflict_count": len(uniq)}))

    manual_out: List[Dict[str, Any]] = []
    for i, j, reason, conflicts in manual_pairs:
        if find(i) == find(j):
            continue
        entry = {
            "entry_ids": [cards[i]["card_id"], cards[j]["card_id"]],
            "labels": [cards[i]["evidence"].get("label"),
                       cards[j]["evidence"].get("label")],
            "verdict": "manual_confirm",
            "reason": reason,
            "conflicts": _uniq_conflicts(conflicts),
        }
        manual_out.append(entry)
        findings.append(make_finding(
            "taw-dedup-merge-conflict", "warn",
            "疑似重复 {} / {}（{}）；冲突 {} 项，未自动合并".format(
                _label_of(cards[i]), _label_of(cards[j]), reason,
                len(entry["conflicts"])),
            "pair:{}:{}".format(cards[i]["card_id"], cards[j]["card_id"]),
            {"a": cards[i]["card_id"], "b": cards[j]["card_id"],
             "reason": reason, "conflicts": entry["conflicts"]}))

    return {"clusters": clusters_out, "manual_pairs": manual_out, "findings": findings}


def merge_cluster(cards: Sequence[Mapping[str, Any]], cluster: Mapping[str, Any]
                  ) -> Dict[str, Any]:
    """按簇生成合并建议（不修改入参）：保留 keep，吸收 drop 中 keep 缺失的字段。"""
    by_id = {card["card_id"]: card for card in cards}
    keep = by_id[cluster["keep"]]
    merged = {"card_id": keep["card_id"], "title": keep["title"],
              "authors": list(keep["authors"]),
              "source": dict(keep["source"]),
              "identifiers": dict(keep["identifiers"]),
              "absorbed_from": [], "conflicts": list(cluster.get("conflicts") or [])}
    for drop_id in cluster["drop"]:
        drop = by_id[drop_id]
        if not merged["title"] and drop["title"]:
            merged["title"] = drop["title"]
        if not merged["authors"] and drop["authors"]:
            merged["authors"] = list(drop["authors"])
        for group in ("source", "identifiers"):
            for key, value in drop[group].items():
                if not merged[group].get(key) and value:
                    merged[group][key] = value
        merged["absorbed_from"].append(drop_id)
    return merged


# ============================================================ fake（reffake.py 迁移）
def doi_prefix(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    match = re.match(r"^\s*(10\.\d{4,9})/", doi)
    return match.group(1) if match else None


def _isbn_publisher_range(isbn: Optional[str]) -> Optional[str]:
    """取 ISBN-13 出版者段（978-7-XXXX）。"""
    digits = re.sub(r"[^0-9Xx]", "", isbn or "")
    if len(digits) != 13:
        return None
    return "{}-{}-{}".format(digits[0:3], digits[3], digits[4:8])


def _isbn_checksum_ok(isbn: Optional[str]) -> Optional[bool]:
    """ISBN-10 / ISBN-13 校验位（GB/T 5792 算法）；长度不对 → None（不判）。"""
    digits = re.sub(r"[^0-9Xx]", "", isbn or "")
    if len(digits) == 10:
        total = 0
        for i, char in enumerate(digits):
            total += (10 - i) * (10 if char in "Xx" else int(char))
        return total % 11 == 0
    if len(digits) == 13:
        total = 0
        for i, char in enumerate(digits):
            total += int(char) * (1 if i % 2 == 0 else 3)
        return total % 10 == 0
    return None


def _impossible_combo(card: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    """类型-字段矩阵：期刊条目不得有 ISBN；图书条目不得带卷/期。"""
    entry_type = card["entry_type"]
    source = card["source"]
    identifiers = card["identifiers"]
    if entry_type == "J" and identifiers.get("isbn"):
        return ("isbn", "期刊条目不应著录 ISBN")
    if entry_type == "M" and (source.get("volume") or source.get("issue")):
        return ("volume", "图书条目不应著录卷/期")
    if entry_type in ("D", "R") and identifiers.get("isbn"):
        return ("isbn", "{} 条目不应著录 ISBN".format(entry_type))
    return None


def _self_referential(card: Mapping[str, Any]) -> bool:
    title = card.get("title") or ""
    container = card["source"].get("container") or ""
    if not title or not container:
        return False
    if title.strip() == container.strip():
        return True
    return container.strip() in title.strip() and len(container.strip()) >= 4


def _grade(signals: Sequence[Mapping[str, Any]]) -> str:
    if any(signal["type"] in STRUCTURAL_SIGNALS for signal in signals):
        return "high"
    if signals:
        return "medium"
    return "low"


def _known_set(known_prefixes: Any) -> frozenset:
    if known_prefixes is None:
        return frozenset(KNOWN_DOI_PREFIXES)
    if isinstance(known_prefixes, Mapping):
        values = list(known_prefixes.keys())
    elif isinstance(known_prefixes, (str, bytes)):
        raise ValueError("known_prefixes 必须是 dict/列表")
    elif isinstance(known_prefixes, (set, frozenset, Sequence)):
        values = list(known_prefixes)
    else:
        raise ValueError("known_prefixes 必须是 dict/列表")
    for value in values:
        if not isinstance(value, str):
            raise ValueError("known_prefixes 只能含字符串")
    if not values:
        raise ValueError("known_prefixes 为空（配置错误）")
    return frozenset(values)


def _str_set(values: Any, name: str, default=None) -> set:
    if values is None:
        values = default or ()
    if isinstance(values, Mapping):
        items = list(values.keys())
    elif isinstance(values, (str, bytes)):
        raise ValueError("{} 必须是列表".format(name))
    elif isinstance(values, (set, frozenset, Sequence)):
        items = list(values)
    else:
        raise ValueError("{} 必须是列表".format(name))
    for item in items:
        if not isinstance(item, str):
            raise ValueError("{} 只能含字符串".format(name))
    return set(items)


def profile_entry(card: Mapping[str, Any], known_prefixes=None,
                  fake_isbn_ranges=None) -> Dict[str, Any]:
    """单条目 → {signals, risk, penalty}（六信号与旧仓一一对应）。"""
    signals: List[Dict[str, Any]] = []
    known = _known_set(known_prefixes)
    ranges = _str_set(fake_isbn_ranges, "fake_isbn_ranges",
                       DEFAULT_FAKE_ISBN_RANGES)

    doi = card["identifiers"].get("doi")
    if doi:
        prefix = doi_prefix(doi)
        if prefix and prefix not in known:
            signals.append({"type": "doi_prefix_unknown", "field": "doi",
                            "detail": "DOI 前缀 {} 不在已知注册前缀/白名单内".format(prefix)})

    isbn = card["identifiers"].get("isbn")
    if isbn:
        publisher_range = _isbn_publisher_range(isbn)
        if not (publisher_range and publisher_range in ranges):
            checksum = _isbn_checksum_ok(isbn)
            if checksum is False:
                signals.append({"type": "isbn_checksum_invalid", "field": "isbn",
                                "detail": "ISBN {} 校验位不合法".format(isbn)})

    year = card["source"].get("year")
    if year and re.match(r"^\d{4}$", str(year)):
        numeric = int(year)
        if numeric > YEAR_UPPER or numeric < YEAR_LOWER:
            signals.append({"type": "year_out_of_range", "field": "year",
                            "detail": "年份 {} 超出合理范围 [{}, {}]".format(
                                numeric, YEAR_LOWER, YEAR_UPPER)})

    pages = card["source"].get("pages")
    if pages:
        match = re.match(r"^(\d+)-(\d+)$", pages)
        if match and int(match.group(1)) > int(match.group(2)):
            signals.append({"type": "page_range_inverted", "field": "pages",
                            "detail": "起页 {} > 止页 {}".format(
                                match.group(1), match.group(2))})

    combo = _impossible_combo(card)
    if combo:
        signals.append({"type": "impossible_field_combo", "field": combo[0],
                        "detail": combo[1]})

    if _self_referential(card):
        signals.append({"type": "self_referential_title", "field": "title",
                        "detail": "题名与载体名相同或题名内嵌载体名"})

    return {"signals": signals, "risk": _grade(signals),
            "penalty": sum(SIGNAL_WEIGHT.get(signal["type"], 0) for signal in signals)}


def health_score(profiles: Sequence[Mapping[str, Any]]) -> float:
    """文献表体检分（0-100）：100 - 平均扣减，下限 0。"""
    if not profiles:
        return 100.0
    total = sum(profile["penalty"] for profile in profiles)
    return max(0.0, round(100.0 - total / len(profiles), 1))


def profile_refs(cards: Sequence[Mapping[str, Any]], known_prefixes=None,
                 fake_isbn_ranges=None, doc_name=None) -> Dict[str, Any]:
    """REF-06 主入口（旧仓 profile_refs）→ {findings, profiles, health_score, summary}。"""
    known = _known_set(known_prefixes)
    ranges = _str_set(fake_isbn_ranges, "fake_isbn_ranges",
                       DEFAULT_FAKE_ISBN_RANGES)
    profiles: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    for card in cards:
        profile = profile_entry(card, known, ranges)
        profile["entry_id"] = card["card_id"]
        profile["label"] = card["evidence"].get("label")
        profiles.append(profile)
        if not profile["signals"]:
            continue
        verdict = "error" if profile["risk"] == "high" else "warn"
        for signal in profile["signals"]:
            findings.append(make_finding(
                "taw-fake-signal", verdict,
                "[{}] {}".format(signal["type"], signal["detail"]),
                "card:{}/{}".format(card["card_id"], signal["field"]),
                {"card_id": card["card_id"], "signal": signal["type"],
                 "detail": signal["detail"], "risk": profile["risk"],
                 "weight": SIGNAL_WEIGHT.get(signal["type"], 0),
                 "label": card["evidence"].get("label")}))
    score = health_score(profiles)
    by_signal: Dict[str, int] = {}
    for profile in profiles:
        for signal in profile["signals"]:
            by_signal[signal["type"]] = by_signal.get(signal["type"], 0) + 1
    findings.append(make_finding(
        "taw-fake-health", "info",
        "文献表体检分 {:.1f}（{} 条，扣减合计 {}）".format(
            score, len(profiles),
            sum(profile["penalty"] for profile in profiles)),
        "report",
        {"doc": doc_name, "health_score": score, "n_entries": len(profiles),
         "by_signal": dict(sorted(by_signal.items()))}))
    return {"findings": findings, "profiles": profiles,
            "health_score": score, "summary": summarize(findings)}


# ============================================================ 检索与重排（refrec + renumber）
def tokenize(text: Optional[str]) -> List[str]:
    """文本 → 词项（西文词 + CJK 单字与 bigram）；确定性、纯本地。"""
    if not text:
        return []
    out = [token.lower() for token in _TOKEN_EN.findall(text)]
    for run in _TOKEN_CJK.findall(text):
        out.extend(list(run))
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
    return out


class BM25:
    """自实现 BM25（k1/b 可调；小语料无需外部依赖）。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: List[Tuple[str, List[str]]] = []
        self.df: Dict[str, int] = {}
        self.avgdl = 0.0

    def fit(self, docs: Sequence[Tuple[str, str]]) -> "BM25":
        self.docs = [(doc_id, tokenize(text)) for doc_id, text in docs]
        self.df = {}
        for _doc_id, tokens in self.docs:
            for token in set(tokens):
                self.df[token] = self.df.get(token, 0) + 1
        count = len(self.docs)
        self.avgdl = (sum(len(tokens) for _doc, tokens in self.docs) / count) if count else 0.0
        return self

    def _idf(self, term: str) -> float:
        count = len(self.docs)
        frequency = self.df.get(term, 0)
        return math.log(1.0 + (count - frequency + 0.5) / (frequency + 0.5))

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """→ [{doc_id, score, hits}]，按 score 降序（同分按 doc_id 稳定排序）。"""
        query_tokens = tokenize(query)
        if not query_tokens or not self.docs:
            return []
        results = []
        for doc_id, tokens in self.docs:
            length = len(tokens) or 1
            tf_map: Dict[str, int] = {}
            for token in tokens:
                tf_map[token] = tf_map.get(token, 0) + 1
            score = 0.0
            hits = []
            for term in set(query_tokens):
                frequency = tf_map.get(term)
                if not frequency:
                    continue
                idf = self._idf(term)
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * length / (self.avgdl or 1))
                contribution = idf * frequency * (self.k1 + 1) / denominator
                score += contribution
                hits.append({"term": term, "tf": frequency, "idf": round(idf, 4),
                             "contrib": round(contribution, 4)})
            if score > 0:
                hits.sort(key=lambda hit: (-hit["contrib"], hit["term"]))
                results.append({"doc_id": doc_id, "score": round(score, 4),
                                "hits": hits})
        results.sort(key=lambda result: (-result["score"], str(result["doc_id"])))
        return results[:top_k]


def _entry_text(card: Mapping[str, Any]) -> str:
    """文献卡 → 检索文本（题名 + 刊名/书名 + 著者 + 年份）。"""
    source = card.get("source") or {}
    parts = [card.get("title") or "", source.get("container") or "",
             " ".join(author.get("raw") or "" for author in card.get("authors", [])),
             str(source.get("year") or "")]
    return " ".join(part for part in parts if part)


def build_index(cards: Sequence[Mapping[str, Any]]) -> BM25:
    """已审计库内文献 → BM25 索引（doc_id = card_id）。"""
    return BM25().fit([(card["card_id"], _entry_text(card)) for card in cards])


def recommend(cards: Sequence[Mapping[str, Any]], sentence: str, top_k: int = 5,
              index: Optional[BM25] = None) -> List[Dict[str, Any]]:
    """句子 → 库内 Top-K 推荐（附命中证据；返回 card_id 恒为入参子集）。"""
    if not isinstance(sentence, str):
        raise ValueError("sentence 必须是字符串")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k 必须是正整数")
    if index is None:
        index = build_index(cards)
    by_id = {card["card_id"]: card for card in cards}
    out: List[Dict[str, Any]] = []
    for result in index.search(sentence, top_k=top_k):
        card = by_id.get(result["doc_id"])
        if card is None:
            continue                      # 结构防幻觉：库外 id 一律丢弃
        out.append({"card_id": result["doc_id"],
                    "label": card["evidence"].get("label"),
                    "title": card.get("title"),
                    "year": card["source"].get("year"),
                    "score": result["score"], "hits": result["hits"],
                    "in_library": True})
    return out


def _norm_items(items: Any) -> List[Dict[str, Any]]:
    if isinstance(items, (str, bytes, Mapping)) or not isinstance(items, Sequence):
        raise ValueError("items 必须是列表")
    out: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise ValueError("items[{}] 必须是 dict".format(index))
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("items[{}] 缺 item_id".format(index))
        markers = item.get("markers") or []
        if isinstance(markers, (str, bytes)) or not isinstance(markers, Sequence):
            raise ValueError("items[{}].markers 必须是列表".format(index))
        clean_markers = []
        for marker in markers:
            if not isinstance(marker, Mapping):
                raise ValueError("items[{}].markers 条目必须是 dict".format(index))
            clean_markers.append(dict(marker))
        out.append({"item_id": item_id, "markers": clean_markers})
    return out


def _index_of(sequence: Sequence[Mapping[str, Any]], item_id: Any) -> Optional[int]:
    for index, item in enumerate(sequence):
        if item["item_id"] == item_id:
            return index
    return None


def renumber(items: Sequence[Mapping[str, Any]], edits: Sequence[Mapping[str, Any]]
             ) -> Dict[str, Any]:
    """编号重排内核（旧仓 renumber 折入；REF-07 插入/删除与矩阵共用）。"""
    clean_items = _norm_items(items)
    if isinstance(edits, (str, bytes, Mapping)) or not isinstance(edits, Sequence):
        raise ValueError("edits 必须是列表")
    sequence = [{"item_id": item["item_id"],
                 "markers": [dict(marker) for marker in item["markers"]]}
                for item in clean_items]
    diagnostics: List[Dict[str, Any]] = []
    for edit in edits:
        if not isinstance(edit, Mapping):
            raise ValueError("edits 条目必须是 dict")
        edit_type = edit.get("type")
        target = edit.get("target")
        index = _index_of(sequence, target)
        if edit_type == "insert":
            new_id = edit.get("new_item_id")
            if new_id is None:
                diagnostics.append({"kind": "insert_missing_new_item_id", "edit": dict(edit)})
                continue
            if index is None:
                sequence.append({"item_id": new_id,
                                 "markers": [dict(marker)
                                             for marker in (edit.get("markers") or ())]})
                diagnostics.append({"kind": "insert_target_missing_appended",
                                    "target": target})
                continue
            position = index if edit.get("before") else index + 1
            sequence.insert(position, {"item_id": new_id,
                                       "markers": [dict(marker)
                                                   for marker in (edit.get("markers") or ())]})
        elif edit_type == "delete":
            if index is None:
                diagnostics.append({"kind": "delete_target_missing", "target": target})
                continue
            sequence.pop(index)
        else:
            diagnostics.append({"kind": "unknown_edit_type", "edit": dict(edit)})

    old_no = {item["item_id"]: position + 1
              for position, item in enumerate(clean_items)}
    mappings = []
    seen_new: Dict[str, List[int]] = {}
    for new_index, item in enumerate(sequence, 1):
        seen_new.setdefault(item["item_id"], []).append(new_index)
    for new_index, item in enumerate(sequence, 1):
        for marker in item["markers"]:
            mappings.append({"marker_id": marker.get("marker_id"),
                             "item_id": item["item_id"],
                             "old_no": old_no.get(item["item_id"]),
                             "new_no": new_index})

    duplicates = sorted(key for key, value in seen_new.items() if len(value) > 1)
    if duplicates:
        diagnostics.append({"kind": "duplicate_item_id_after_edits",
                            "items": duplicates})
    marker_owner: Dict[Any, str] = {}
    marker_dup = []
    for item in sequence:
        for marker_id in [marker.get("marker_id") for marker in item["markers"]]:
            if marker_id is None:
                continue
            if marker_id in marker_owner and marker_owner[marker_id] != item["item_id"]:
                marker_dup.append(marker_id)
            marker_owner[marker_id] = item["item_id"]
    if marker_dup:
        diagnostics.append({"kind": "marker_claimed_by_multiple_items",
                            "markers": marker_dup})

    consistent = not duplicates and not marker_dup
    return {"mappings": mappings, "consistent": consistent,
            "new_order": [item["item_id"] for item in sequence],
            "n_items": len(sequence), "diagnostics": diagnostics}


def verify_plan(plan: Mapping[str, Any]) -> bool:
    """独立复核 RenumberPlan（不信任构造期自报的 consistent）。"""
    order = plan["new_order"]
    count = len(order)
    if sorted(set(order)) != sorted(order):
        return False                      # item_id 重复
    position = {item_id: index + 1 for index, item_id in enumerate(order)}
    seen: Dict[Any, str] = {}
    for mapping in plan["mappings"]:
        if mapping["new_no"] != position.get(mapping["item_id"]):
            return False                  # 映射与位置不符
        if not 1 <= mapping["new_no"] <= count:
            return False
        marker_id = mapping["marker_id"]
        if marker_id is None:
            continue
        if marker_id in seen:
            return False                  # 标记重号
        seen[marker_id] = mapping["item_id"]
    if count and sorted(position.values()) != list(range(1, count + 1)):
        return False
    return bool(plan["consistent"])


def insert_reference(items: Sequence[Mapping[str, Any]],
                     cards: Sequence[Mapping[str, Any]], new_card_id: str,
                     before: bool = False) -> Dict[str, Any]:
    """一键插入（默认末位）；``new_card_id`` 必须在已审计库内。"""
    clean_items = _norm_items(items)
    if new_card_id not in {card["card_id"] for card in cards}:
        raise ValueError("插入目标必须是已审计库内文献：{}".format(new_card_id))
    if not clean_items:
        return renumber([{"item_id": new_card_id, "markers": []}], [])
    anchor = clean_items[0]["item_id"] if before else clean_items[-1]["item_id"]
    edits = [{"type": "insert", "new_item_id": new_card_id,
              "target": anchor, "before": bool(before)}]
    return renumber(clean_items, edits)


def delete_reference(items: Sequence[Mapping[str, Any]], target_id: str) -> Dict[str, Any]:
    """删除编号项 → RenumberPlan（与插入同一内核）。"""
    return renumber(items, [{"type": "delete", "target": target_id}])


def edit_matrix(n_items: int, max_edits: int = 2
                ) -> Tuple[List[str], List[Tuple[List[Dict[str, Any]], str]]]:
    """生成插入/删除矩阵：``→ (base_ids, [(edits, 描述)])``。"""
    if isinstance(n_items, bool) or not isinstance(n_items, int) or n_items < 1:
        raise ValueError("n_items 必须是正整数")
    if isinstance(max_edits, bool) or not isinstance(max_edits, int) or max_edits < 1:
        raise ValueError("max_edits 必须是正整数")
    base_ids = ["it{}".format(index + 1) for index in range(n_items)]
    cases: List[Tuple[List[Dict[str, Any]], str]] = []
    for index, item_id in enumerate(base_ids):
        cases.append(([{"type": "delete", "target": item_id}], "delete@{}".format(index)))
    for position in range(n_items + 1):
        cases.append(([{"type": "insert", "new_item_id": "new{}".format(position),
                        "target": base_ids[min(position, n_items - 1)],
                        "before": position == 0}], "insert@{}".format(position)))
    if max_edits >= 2:
        for i, first in enumerate(base_ids):
            for j, second in enumerate(base_ids):
                if i == j:
                    continue
                cases.append(([{"type": "delete", "target": first},
                               {"type": "delete", "target": second}],
                              "delete@{}+{}".format(i, j)))
        for position in range(n_items + 1):
            for i, item_id in enumerate(base_ids):
                if position == i:
                    continue
                cases.append(([{"type": "insert", "new_item_id": "xa{}".format(position),
                                "target": item_id, "before": True},
                               {"type": "delete",
                                "target": base_ids[(position + 1) % n_items]}],
                              "ins@{}del@{}".format(position, i)))
    return base_ids, cases


# ============================================================ library（reflib.py 迁移）
SCHEMA_VERSION = 1


def _squash(value: Optional[str]) -> str:
    return re.sub(r"\s+", "", value or "")


def _scalar(value: Any) -> str:
    return "" if value is None else str(value)


def _norm_for_fingerprint(card: Mapping[str, Any]) -> str:
    """指纹归一：只取语义字段，剔除证据/flag/置信度与顺序噪声。

    旧仓用 ``json.dumps(sort_keys=True)``；纯函数面禁用 ``json``，改用控制字符分隔的
    规范文本（同语义、同排除面；哈希值不与旧仓互通，见模块口径差说明）。
    """
    authors = "\x1e".join(sorted(_squash(author.get("raw") or "")
                                 for author in card.get("authors", [])))
    group = "\x1f"
    source = group.join(key + "=" + _scalar(card["source"].get(key))
                        for key in sorted(card["source"]))
    identifiers = group.join(key + "=" + _scalar(card["identifiers"].get(key))
                             for key in sorted(card["identifiers"]))
    return "\x1d".join([
        "entry_type=" + _scalar(card.get("entry_type")),
        "title=" + _squash(card.get("title") or ""),
        "authors=" + authors,
        "source=" + source,
        "identifiers=" + identifiers,
    ])


def entry_fingerprint(card: Mapping[str, Any]) -> str:
    """单条指纹 = 语义字段归一的 SHA-256 前 16 位。

    **先归一（``_norm_card``）再取语义字段**：``build_manifest`` 与 ``detect_tampering``
    必须对「同一张卡的任何 dict 形态」给出同一指纹，否则出现"同卡被报增/删/改"的假红
    （实测修：旧实现两条路径一个吃原始卡、一个吃归一卡）。
    """
    normalized = _norm_card(dict(card))
    return hashlib.sha256(_norm_for_fingerprint(normalized).encode("utf-8")).hexdigest()[:16]


def manifest_fingerprint(cards: Sequence[Mapping[str, Any]]) -> str:
    """文献表指纹 = 逐条指纹排序后再哈希（与输入顺序无关）。"""
    parts = sorted(entry_fingerprint(card) for card in cards)
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("ascii"))
    return digest.hexdigest()


def build_manifest(cards: Sequence[Mapping[str, Any]], doc_name=None) -> Dict[str, Any]:
    """指纹清单：{doc, count, fingerprint, entries:[{card_id,fingerprint,title,label}]}。"""
    entries = [{"card_id": card["card_id"], "fingerprint": entry_fingerprint(card),
                "title": card.get("title"), "label": card["evidence"].get("label")}
               for card in cards]
    return {"schema_version": SCHEMA_VERSION, "doc": doc_name,
            "count": len(cards), "fingerprint": manifest_fingerprint(cards),
            "entries": entries}


def detect_tampering(old_manifest: Mapping[str, Any],
                     new_cards: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """篡改检测 → {unchanged, added, removed, modified, intact, manifest_changed}。"""
    old = {str(entry["card_id"]): entry["fingerprint"]
           for entry in old_manifest.get("entries", [])}
    new = {card["card_id"]: entry_fingerprint(card) for card in new_cards}
    old_fps = set(old.values())
    new_fps = set(new.values())
    unchanged = len(old_fps & new_fps)
    added = sorted(new_fps - old_fps)
    removed = sorted(old_fps - new_fps)
    modified = []
    for card_id in sorted(new):
        fingerprint = new[card_id]
        if card_id in old and old[card_id] != fingerprint \
                and fingerprint not in old_fps:
            modified.append({"card_id": card_id, "old": old[card_id],
                             "new": fingerprint})
    return {"unchanged": unchanged, "added": added, "removed": removed,
            "modified": modified,
            "intact": not added and not removed and not modified,
            "manifest_changed": manifest_fingerprint(new_cards)
            != old_manifest.get("fingerprint")}


# ============================================================ review（reviewcl.py 迁移）
def _review_text(entry: Mapping[str, Any]) -> str:
    """综述条目 → 聚类文本（题名 + 摘要 + 刊名 + 关键词 + 著者；年份不入词项）。"""
    parts = [entry.get("title") or "", entry.get("abstract") or "",
             entry.get("venue") or ""]
    parts.extend(entry.get("keywords") or [])
    parts.extend(entry.get("authors") or [])
    return " ".join(str(part) for part in parts if part)


def tfidf_vectors(entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """条目 → [{entry_id, vector{term: weight}, norm}]（TF-IDF，L2 归一）。"""
    docs = [(entry["entry_id"], tokenize(_review_text(entry))) for entry in entries]
    count = len(docs)
    df: Dict[str, int] = {}
    for _doc_id, tokens in docs:
        for token in set(tokens):
            df[token] = df.get(token, 0) + 1
    vectors = []
    for doc_id, tokens in docs:
        tf: Dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        vector: Dict[str, float] = {}
        for term, frequency in tf.items():
            idf = math.log((count + 1.0) / (df.get(term, 0) + 1.0)) + 1.0
            vector[term] = (frequency / len(tokens)) * idf if tokens else 0.0
        norm = math.sqrt(sum(weight * weight for weight in vector.values())) or 1.0
        vectors.append({"entry_id": doc_id, "vector": vector, "norm": norm})
    return vectors


def cosine(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    """两个 {term: weight} 向量的余弦相似度。"""
    vector_a, vector_b = a["vector"], b["vector"]
    if len(vector_a) > len(vector_b):
        vector_a, vector_b = vector_b, vector_a
    dot = 0.0
    for term, weight in vector_a.items():
        if term in vector_b:
            dot += weight * vector_b[term]
    return dot / (a["norm"] * b["norm"]) if a["norm"] and b["norm"] else 0.0


def cluster(entries: Sequence[Mapping[str, Any]], threshold: float = THRESHOLD
            ) -> List[Dict[str, Any]]:
    """余弦阈值聚类（single-linkage 贪心，确定性）→ [{cluster_id, entry_ids}]。"""
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) \
            or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold 必须在 [0, 1]")
    vectors = tfidf_vectors(entries)
    order = sorted(vectors, key=lambda vector: vector["entry_id"])
    groups: List[List[int]] = []
    for index, vector in enumerate(order):
        placed = False
        for members in groups:
            if any(cosine(vector, order[member]) >= threshold for member in members):
                members.append(index)
                placed = True
                break
        if not placed:
            groups.append([index])
    out = []
    for cluster_index, members in enumerate(groups):
        ids = sorted(order[member]["entry_id"] for member in members)
        out.append({"cluster_id": "c{}".format(cluster_index), "entry_ids": ids})
    out.sort(key=lambda item: (-len(item["entry_ids"]), item["cluster_id"]))
    return out


def cluster_purity(clusters: Sequence[Mapping[str, Any]],
                   by_entry=None,
                   truth_groups: Optional[Mapping[str, Sequence[str]]] = None
                   ) -> Dict[str, Any]:
    """簇纯度：每簇取多数真值组，占比加权平均（无真值组 → 0.0，旧仓同口径）。"""
    group_of: Dict[str, str] = {}
    for group, ids in (truth_groups or {}).items():
        for entry_id in ids:
            group_of[entry_id] = group
    details = []
    total = 0
    correct = 0
    for cluster_item in clusters:
        sizes: Dict[str, int] = {}
        for entry_id in cluster_item["entry_ids"]:
            group = group_of.get(entry_id)
            if group is None:
                continue
            sizes[group] = sizes.get(group, 0) + 1
        if not sizes:
            continue
        majority = sorted(sizes.items(), key=lambda item: (-item[1], item[0]))[0]
        size = len(cluster_item["entry_ids"])
        total += size
        correct += majority[1]
        details.append({"cluster_id": cluster_item["cluster_id"], "size": size,
                        "majority": majority[0],
                        "purity": round(majority[1] / size, 4)})
    return {"purity": round(correct / total, 4) if total else 0.0,
            "clusters": details}


def timeline(entries: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    """年代时间线：{group → {year: count}}（键排序，确定性）。"""
    out: Dict[str, Dict[str, int]] = {}
    for entry in entries:
        group = entry.get("group") or "(unspecified)"
        out.setdefault(group, {})
        year = str(entry.get("year"))
        out[group][year] = out[group].get(year, 0) + 1
    return {group: dict(sorted(years.items())) for group, years in sorted(out.items())}


def research_gaps(entries: Sequence[Mapping[str, Any]], now_year: int,
                  recent_years: int = 3) -> List[Dict[str, Any]]:
    """规则可判研究空白：主题内最近年份 < now_year-recent_years+1 → 无新增。"""
    if isinstance(recent_years, bool) or not isinstance(recent_years, int) \
            or recent_years < 1:
        raise ValueError("recent_years 必须是正整数")
    groups: Dict[str, List[int]] = {}
    for entry in entries:
        group = entry.get("group") or "(unspecified)"
        groups.setdefault(group, []).append(entry.get("year") or 0)
    cutoff = now_year - recent_years + 1
    out = []
    for group, years in sorted(groups.items()):
        latest = max(years) if years else 0
        if latest and latest < cutoff:
            out.append({"group": group, "latest_year": latest,
                        "reason": "主题'{}'库内最近年份 {}，近 {} 年（{} 起）无新增".format(
                            group, latest, recent_years, cutoff)})
    return out


def build_review(entries: Sequence[Mapping[str, Any]], now_year: Optional[int] = None,
                 recent_years: int = 3, threshold: float = THRESHOLD) -> Dict[str, Any]:
    """FULL-05 主入口（旧仓 build_review）→ {clusters, purity, timeline, gaps, now_year}。

    主题归属口径：条目自带 ``group`` 时沿用（旧仓）；没有时用聚类簇号顶上——
    否则所有条目落进 ``(unspecified)``，研究空白提示恒为空。
    """
    working = [dict(entry) for entry in entries]
    clusters = cluster(working, threshold=threshold)
    truth_groups: Dict[str, List[str]] = {}
    for entry in working:
        if entry.get("group"):
            truth_groups.setdefault(entry["group"], []).append(entry["entry_id"])
    purity = cluster_purity(clusters, None, truth_groups)
    cluster_of = {}
    for cluster_item in clusters:
        for entry_id in cluster_item["entry_ids"]:
            cluster_of[entry_id] = cluster_item["cluster_id"]
    for entry in working:
        if not entry.get("group"):
            entry["group"] = cluster_of.get(entry["entry_id"], "(unspecified)")
    years = [entry["year"] for entry in working if entry.get("year")]
    if now_year is None:
        now_year = max(years) if years else 0
    return {"clusters": clusters, "cluster_count": len(clusters),
            "purity": purity, "timeline": timeline(working),
            "research_gaps": research_gaps(working, now_year, recent_years),
            "now_year": now_year}


# ============================================================ subject 校验与 mode 实现
def _opt_int(subject: Mapping[str, Any], key: str) -> Optional[int]:
    value = subject.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("subject.{} 必须是整数".format(key))
    return value


def _opt_str(subject: Mapping[str, Any], key: str) -> Optional[str]:
    value = subject.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("subject.{} 必须是字符串".format(key))
    return value


def _norm_markers(markers: Sequence[Any]) -> List[Dict[str, Any]]:
    if isinstance(markers, (str, bytes)) or not isinstance(markers, Sequence):
        raise ValueError("subject.markers 必须是列表")
    out: List[Dict[str, Any]] = []
    for index, marker in enumerate(markers):
        if not isinstance(marker, Mapping):
            raise ValueError("markers[{}] 必须是 dict".format(index))
        kind = marker.get("kind")
        para = marker.get("para")
        if kind not in ("numeric", "author_year"):
            raise ValueError("markers[{}].kind 非法".format(index))
        if isinstance(para, bool) or not isinstance(para, int) or para < 0:
            raise ValueError("markers[{}].para 必须是非负整数".format(index))
        pos = marker.get("pos", index)
        if isinstance(pos, bool) or not isinstance(pos, int) or pos < 0:
            raise ValueError("markers[{}].pos 必须是非负整数".format(index))
        item = {"kind": kind, "para": para, "pos": pos,
                "doc": marker.get("doc") or "body",
                "context": marker.get("context") or ""}
        if kind == "numeric":
            numbers = marker.get("numbers")
            if isinstance(numbers, (str, bytes)) or not isinstance(numbers, Sequence) \
                    or not numbers:
                raise ValueError("markers[{}].numbers 必须是非空列表".format(index))
            clean_numbers = []
            for number in numbers:
                if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                    raise ValueError("markers[{}].numbers 必须为正整数".format(index))
                clean_numbers.append(number)
            item["numbers"] = clean_numbers
            item["label"] = str(marker.get("label") or "")
        else:
            author = marker.get("author")
            year = marker.get("year")
            if not isinstance(author, str) or not author:
                raise ValueError("markers[{}].author 必须是非空字符串".format(index))
            if not isinstance(year, (str, int)) or isinstance(year, bool):
                raise ValueError("markers[{}].year 类型不对".format(index))
            item["author"] = author
            item["year"] = str(year)
        out.append(item)
    return out


def _impl_refcheck(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    doc_name = _opt_str(subject, "doc_name")
    fmt = _opt_str(subject, "fmt")
    if fmt is not None and fmt not in ("bib", "ris", "txt", "csv"):
        raise ValueError("subject.fmt 非法: {!r}".format(fmt))
    src_text = subject.get("src_text")
    if src_text is not None and not isinstance(src_text, str):
        raise ValueError("subject.src_text 必须是字符串")
    replacements = subject.get("replacements")
    cards = _cards(subject, doc_name=doc_name)
    findings = _check_card(cards)
    findings.extend(check_format(cards, subject.get("ruleset"), fmt, src_text,
                                 doc_name, replacements)["findings"])
    return findings


def _impl_cite(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    doc_name = _opt_str(subject, "doc_name") or "body"
    cards = _cards(subject)
    text = subject.get("text")
    raw_markers = subject.get("markers")
    if text is not None and raw_markers is not None:
        raise ValueError("subject.text 与 subject.markers 只能给一个")
    if text is not None:
        if not isinstance(text, str):
            raise ValueError("subject.text 必须是字符串")
        markers = parse_markers(text, doc_name)
    elif raw_markers is not None:
        markers = _norm_markers(raw_markers)
    else:
        raise ValueError("subject.text 或 subject.markers 必填")
    return reconcile(cards, markers, subject.get("ruleset"), doc_name)["findings"]


def _impl_dedup(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    edit_threshold = subject.get("edit_threshold")
    if edit_threshold is None:
        edit_threshold = 2
    cards = _cards(subject)
    return find_duplicates(cards, edit_threshold)["findings"]


def _impl_fake(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    doc_name = _opt_str(subject, "doc_name")
    cards = _cards(subject)
    return profile_refs(cards, subject.get("known_prefixes"),
                        subject.get("fake_isbn_ranges"), doc_name)["findings"]


def _impl_rec(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    if "sentence" in subject:
        cards = _cards(subject)
        sentence = subject.get("sentence")
        if not isinstance(sentence, str):
            raise ValueError("subject.sentence 必须是字符串")
        top_k = subject.get("top_k")
        if top_k is None:
            top_k = 5
        hits = recommend(cards, sentence, top_k=top_k)
        for rank, hit in enumerate(hits, 1):
            findings.append(make_finding(
                "taw-rec-hint", "info",
                "库内推荐 Top{}：{}".format(rank, hit["title"]),
                "card:{}".format(hit["card_id"]),
                {"rank": rank, "card_id": hit["card_id"], "label": hit["label"],
                 "year": hit["year"], "score": hit["score"],
                 "hits": hit["hits"], "in_library": hit["in_library"]}))
        return findings

    if "new_card_id" in subject:
        if "items" not in subject:
            raise ValueError("插入需要 subject.items")
        cards = _cards(subject)
        new_card_id = subject.get("new_card_id")
        if not isinstance(new_card_id, str) or not new_card_id:
            raise ValueError("subject.new_card_id 必须是非空字符串")
        before = subject.get("before", False)
        if not isinstance(before, bool):
            raise ValueError("subject.before 必须是布尔值")
        plan = insert_reference(subject["items"], cards, new_card_id, before)
        anchor = (subject["items"][0]["item_id"] if before and subject["items"]
                  else (subject["items"][-1]["item_id"] if subject["items"] else None))
        position = plan["new_order"].index(new_card_id) + 1
        findings.append(make_finding(
            "taw-rec-hint", "info" if verify_plan(plan) else "error",
            "插入 {}（{} {}）→ 新编号 {}，共 {} 项".format(
                new_card_id, "before" if before else "after", anchor,
                position, plan["n_items"]),
            "item:{}".format(new_card_id),
            {"action": "insert", "card_id": new_card_id, "anchor": anchor,
             "before": before, "plan": plan}))
        for diagnostic in plan["diagnostics"]:
            findings.append(make_finding(
                "taw-rec-hint", "warn",
                "重排诊断：{}".format(diagnostic.get("kind")),
                "item:{}".format(diagnostic.get("target") or new_card_id),
                {"action": "insert", "diagnostic": diagnostic}))
        return findings

    if "delete_id" in subject:
        if "items" not in subject:
            raise ValueError("删除需要 subject.items")
        delete_id = subject.get("delete_id")
        if not isinstance(delete_id, str) or not delete_id:
            raise ValueError("subject.delete_id 必须是非空字符串")
        plan = delete_reference(subject["items"], delete_id)
        findings.append(make_finding(
            "taw-rec-hint", "info" if verify_plan(plan) else "error",
            "删除 {} → 共 {} 项".format(delete_id, plan["n_items"]),
            "item:{}".format(delete_id),
            {"action": "delete", "card_id": delete_id, "plan": plan}))
        for diagnostic in plan["diagnostics"]:
            findings.append(make_finding(
                "taw-rec-hint", "warn",
                "重排诊断：{}".format(diagnostic.get("kind")),
                "item:{}".format(diagnostic.get("target") or delete_id),
                {"action": "delete", "diagnostic": diagnostic}))
        return findings

    if "n_items" in subject:
        n_items = subject.get("n_items")
        max_edits = subject.get("max_edits")
        if max_edits is None:
            max_edits = 2
        base_ids, cases = edit_matrix(n_items, max_edits)
        base_items = [{"item_id": item_id, "markers": []} for item_id in base_ids]
        results = []
        for edits, description in cases:
            plan = renumber(base_items, edits)
            ok = verify_plan(plan)
            results.append({"case": description, "consistent": ok})
            if not ok:
                findings.append(make_finding(
                    "taw-rec-hint", "error",
                    "编辑矩阵用例不一致：{}".format(description),
                    "matrix:{}".format(description),
                    {"case": description, "edits": edits, "plan": plan}))
        bad = sum(1 for result in results if not result["consistent"])
        findings.insert(0, make_finding(
            "taw-rec-hint", "info" if bad == 0 else "error",
            "编辑矩阵 {} 例：{}".format(
                len(cases), "全部一致" if bad == 0 else "{} 例不一致".format(bad)),
            "report",
            {"action": "matrix", "n_items": len(base_ids),
             "max_edits": max_edits, "cases": results}))
        return findings

    raise ValueError("rec 需要 sentence / new_card_id / delete_id / n_items 之一")


def _impl_library(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if "old_manifest" in subject:
        old_manifest = subject.get("old_manifest")
        if not isinstance(old_manifest, Mapping):
            raise ValueError("subject.old_manifest 必须是 dict")
        entries = old_manifest.get("entries")
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
            raise ValueError("old_manifest.entries 必须是列表")
        old_ids: Dict[str, List[str]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ValueError("old_manifest.entries 条目必须是 dict")
            if not isinstance(entry.get("card_id"), (str, int)) \
                    or isinstance(entry.get("card_id"), bool):
                raise ValueError("old_manifest.entries 缺 card_id")
            if not isinstance(entry.get("fingerprint"), str):
                raise ValueError("old_manifest.entries 缺 fingerprint")
            old_ids.setdefault(entry["fingerprint"], []).append(str(entry["card_id"]))
        new_cards = _cards(subject, key="new_cards")
        report = detect_tampering(old_manifest, new_cards)
        new_ids: Dict[str, List[str]] = {}
        for card in new_cards:
            new_ids.setdefault(entry_fingerprint(card), []).append(card["card_id"])
        for fingerprint in report["added"]:
            findings.append(make_finding(
                "taw-lib-tamper", "error",
                "新增条目指纹 {}".format(fingerprint),
                "entry:{}".format(fingerprint),
                {"change": "added", "fingerprint": fingerprint,
                 "card_ids": new_ids.get(fingerprint, [])}))
        for fingerprint in report["removed"]:
            findings.append(make_finding(
                "taw-lib-tamper", "error",
                "条目被移除（指纹 {}）".format(fingerprint),
                "entry:{}".format(fingerprint),
                {"change": "removed", "fingerprint": fingerprint,
                 "card_ids": old_ids.get(fingerprint, [])}))
        for change in report["modified"]:
            findings.append(make_finding(
                "taw-lib-tamper", "error",
                "条目内容被改写（{}）".format(change["card_id"]),
                "card:{}".format(change["card_id"]),
                {"change": "modified", "card_id": change["card_id"],
                 "old": change["old"], "new": change["new"]}))
        if report["intact"]:
            findings.append(make_finding(
                "taw-lib-tamper", "info",
                "指纹清单未变化（{} 条，manifest_changed={}）".format(
                    len(new_cards), report["manifest_changed"]),
                "report",
                {"change": "none", "unchanged": report["unchanged"],
                 "n_entries": len(new_cards),
                 "manifest_changed": report["manifest_changed"]}))
        return findings

    doc_name = _opt_str(subject, "doc_name")
    cards = _cards(subject)
    manifest = build_manifest(cards, doc_name)
    findings.append(make_finding(
        "taw-lib-tamper", "info",
        "文献表指纹 {}（{} 条，doc={}）".format(
            manifest["fingerprint"], manifest["count"], manifest["doc"]),
        "report",
        {"change": "built", "manifest": manifest}))
    return findings


def _entries(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = subject.get("entries")
    if raw is None:
        raise ValueError("subject.entries 必填")
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence):
        raise ValueError("subject.entries 必须是列表")
    out: List[Dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise ValueError("entries[{}] 必须是 dict".format(index))
        entry_id = entry.get("id")
        if entry_id in (None, ""):
            entry_id = entry.get("ref_id")
        if entry_id in (None, ""):
            entry_id = entry.get("entry_id")
        if entry_id is None or (isinstance(entry_id, str) and not entry_id.strip()):
            raise ValueError("entries[{}] 缺 id/ref_id".format(index))
        if isinstance(entry_id, bool) or not isinstance(entry_id, (str, int)):
            raise ValueError("entries[{}].id 类型不对".format(index))
        title = entry.get("title")
        if not isinstance(title, str):
            raise ValueError("entries[{}].title 必须是字符串".format(index))
        abstract = entry.get("abstract")
        if abstract is not None and not isinstance(abstract, str):
            raise ValueError("entries[{}].abstract 必须是字符串".format(index))
        keywords = entry.get("keywords") or []
        if isinstance(keywords, (str, bytes)) or not isinstance(keywords, Sequence):
            raise ValueError("entries[{}].keywords 必须是列表".format(index))
        for keyword in keywords:
            if not isinstance(keyword, str):
                raise ValueError("entries[{}].keywords 只能含字符串".format(index))
        year = entry.get("year")
        if year is not None:
            if isinstance(year, bool):
                raise ValueError("entries[{}].year 类型不对".format(index))
            if isinstance(year, str) and re.match(r"^(?:19|20)\d{2}$", year):
                year = int(year)
            elif not isinstance(year, int):
                raise ValueError("entries[{}].year 类型不对".format(index))
        group = entry.get("group")
        if group is not None and not isinstance(group, str):
            raise ValueError("entries[{}].group 必须是字符串".format(index))
        venue = entry.get("venue")
        if venue is not None and not isinstance(venue, str):
            raise ValueError("entries[{}].venue 必须是字符串".format(index))
        authors = entry.get("authors") or []
        if isinstance(authors, (str, bytes)) or not isinstance(authors, Sequence):
            raise ValueError("entries[{}].authors 必须是列表".format(index))
        out.append({"entry_id": str(entry_id), "title": title,
                    "abstract": abstract, "keywords": list(keywords),
                    "year": year, "group": group, "venue": venue,
                    "authors": list(authors)})
    return out


def _impl_review(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    entries = _entries(subject)
    now_year = _opt_int(subject, "now_year")
    recent_years = _opt_int(subject, "recent_years")
    if recent_years is None:
        recent_years = 3
    threshold = subject.get("threshold")
    if threshold is None:
        threshold = THRESHOLD
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("subject.threshold 必须是数字")
    result = build_review(entries, now_year, recent_years, float(threshold))
    findings: List[Dict[str, Any]] = []
    for cluster_item in result["clusters"]:
        findings.append(make_finding(
            "taw-review-cluster", "info",
            "簇 {}：{} 条（{}）".format(
                cluster_item["cluster_id"], len(cluster_item["entry_ids"]),
                ", ".join(cluster_item["entry_ids"])),
            "cluster:{}".format(cluster_item["cluster_id"]),
            {"cluster_id": cluster_item["cluster_id"],
             "entry_ids": cluster_item["entry_ids"],
             "size": len(cluster_item["entry_ids"])}))
    for gap in result["research_gaps"]:
        findings.append(make_finding(
            "taw-review-gap", "info", gap["reason"],
            "cluster:{}".format(gap["group"]),
            {"group": gap["group"], "latest_year": gap["latest_year"],
             "now_year": result["now_year"], "recent_years": recent_years}))
    findings.append(make_finding(
        "taw-review-cluster", "info",
        "综述聚类：{} 条文献 → {} 簇（簇纯度 {}）".format(
            len(entries), result["cluster_count"], result["purity"]["purity"]),
        "report",
        {"cluster_count": result["cluster_count"],
         "purity": result["purity"]["purity"], "now_year": result["now_year"],
         "timeline": result["timeline"],
         "gap_groups": [gap["group"] for gap in result["research_gaps"]]}))
    return findings


# ============================================================ 唯一对外入口
_MODE_IMPL = {
    "refcheck": _impl_refcheck,
    "cite": _impl_cite,
    "dedup": _impl_dedup,
    "fake": _impl_fake,
    "rec": _impl_rec,
    "library": _impl_library,
    "review": _impl_review,
}


def _checked(finding: Any) -> Dict[str, Any]:
    """输出面复核：五键定长 / 白名单 / verdict / 类型（防内部漏改）。"""
    if not isinstance(finding, Mapping):
        raise ValueError("finding 必须是 dict")
    expected = {"rule_id", "verdict", "message", "path", "evidence"}
    if set(finding) != expected:
        raise ValueError("finding 键集必须恰为 {}，实际 {}".format(
            sorted(expected), sorted(finding)))
    if finding["rule_id"] not in _RULE_ID_SET:
        raise ValueError("rule_id 不在白名单: {!r}".format(finding["rule_id"]))
    if finding["verdict"] not in VERDICTS:
        raise ValueError("verdict 非法: {!r}".format(finding["verdict"]))
    if not isinstance(finding["message"], str) or not finding["message"]:
        raise ValueError("message 必须是非空字符串")
    if not isinstance(finding["path"], str) or not finding["path"]:
        raise ValueError("path 必须是非空字符串")
    if not isinstance(finding["evidence"], Mapping):
        raise ValueError("evidence 必须是 dict")
    return {"rule_id": finding["rule_id"], "verdict": finding["verdict"],
            "message": finding["message"], "path": finding["path"],
            "evidence": dict(finding["evidence"])}


def evaluate(mode: str, subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """文献审计唯一入口：``mode`` 指定判定面，``subject`` 是全显式事实。"""
    if mode not in MODES:
        raise ValueError("未知 mode: {!r}（允许: {}）".format(mode, ", ".join(MODES)))
    if not isinstance(subject, Mapping):
        raise ValueError("subject 必须是 dict")
    return [_checked(finding) for finding in _MODE_IMPL[mode](subject)]