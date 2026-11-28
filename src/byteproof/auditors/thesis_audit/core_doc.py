# -*- coding: utf-8 -*-
"""论文审计器官的纯判定核（``thesis-audit`` / ``core_doc``）。

**迁移来源**（旧仓 ``10-7-thesis-audit-workbench/code/src/taw``，只读移植）：
``aigccheck`` / ``structcheck`` / ``termnum`` / ``figref``（编号断档与重排内核）/
``schoolfmt``（样式与模板求值）/ ``rng``（SplitMix64）。

**唯一对外入口**：``evaluate(mode, subject) -> list[dict]``。
每条结论固定五键：``rule_id`` / ``verdict`` / ``message`` / ``path`` / ``evidence``。

**纯函数纪律**：只 import ``re``；不读文件、环境与时钟；不打印；不改入参。
旧仓的 docx 读取（``_ensure_docx`` / ``read_doc_format``）与知识库装载
（``load_features`` / ``load_terminology``）留在调用方——subject 直接给摊平事实。

**迁入时的人工折算**（逐条见交付报告的口径差登记）：
1. 旧仓 ``engine.make_rule_finding`` 的证据链字段（clause/quote/severity/confidence）
   在本器官不落 finding——输出 schema 只有五键；规则内容由宿主 ``Pack`` 承载；
2. 旧仓「规则未激活则零产出」保留：subject 给了 ``ruleset`` 时按 ``check_type``
   找首条规则并按其 ``activation``/``status`` 门控；不给 ``ruleset`` 视为全开；
3. 旧仓 ``aigccheck`` 只在词汇型特征（aigc-02/03/04）越阈时产段落级 finding，
   aigc-01（句长 CV）只进全文分布——该口径原样保留；
4. ``figref.object_edit_matrix``（依赖 ``refrec.edit_matrix`` 的矩阵基准）未迁：
   ``evaluate`` 无消费面，重排内核本身（``renumber_objects``）已迁；
5. 旧仓术语扫描「段内多次出现只报一条」在代码里只对普通变体成立，空白变体用
   ``finditer`` 逐次产出——这里照**代码**移植（不照 docstring 的理想口径）。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- 契约
MODES = ("aigc", "structure", "terms", "figures", "school", "rng")

RULE_AIGC_BAND = "taw-aigc-band"
RULE_AIGC_DIST = "taw-aigc-dist"
RULE_STRUCT_HEADING = "taw-struct-heading"
RULE_STRUCT_ABSTRACT = "taw-struct-abstract"
RULE_STRUCT_CHAPTER = "taw-struct-chapter"
RULE_TERM_HIT = "taw-term-hit"
RULE_TERM_STRAY = "taw-term-stray"
RULE_TERM_NUMBER = "taw-term-number"
RULE_TERM_HEAT = "taw-term-heat"
RULE_FIG_XREF = "taw-fig-xref"
RULE_FIG_GAP = "taw-fig-gap"
RULE_FIG_RENUMBER = "taw-fig-renumber"
RULE_SCHOOL_STYLE = "taw-school-style"
RULE_SCHOOL_FORMAT = "taw-school-format"
RULE_RNG_DETERMINISM = "taw-rng-determinism"

RULE_IDS = (
    RULE_AIGC_BAND, RULE_AIGC_DIST,
    RULE_STRUCT_HEADING, RULE_STRUCT_ABSTRACT, RULE_STRUCT_CHAPTER,
    RULE_TERM_HIT, RULE_TERM_STRAY, RULE_TERM_NUMBER, RULE_TERM_HEAT,
    RULE_FIG_XREF, RULE_FIG_GAP, RULE_FIG_RENUMBER,
    RULE_SCHOOL_STYLE, RULE_SCHOOL_FORMAT,
    RULE_RNG_DETERMINISM,
)

VERDICTS = ("error", "warn", "info")

#: 每个 rule_id 的 verdict 由纪律固定（结构/格式违规 error；AIGC 分档与术语 warn；
#: 统计/重编号/确定性 info），构造后由 ``_finalize`` 再断言一次。
_RULE_VERDICT = {
    RULE_AIGC_BAND: "warn",
    RULE_AIGC_DIST: "info",
    RULE_STRUCT_HEADING: "error",
    RULE_STRUCT_ABSTRACT: "error",
    RULE_STRUCT_CHAPTER: "error",
    RULE_TERM_HIT: "warn",
    RULE_TERM_STRAY: "warn",
    RULE_TERM_NUMBER: "warn",
    RULE_TERM_HEAT: "info",
    RULE_FIG_XREF: "error",
    RULE_FIG_GAP: "error",
    RULE_FIG_RENUMBER: "info",
    RULE_SCHOOL_STYLE: "error",
    RULE_SCHOOL_FORMAT: "error",
    RULE_RNG_DETERMINISM: "info",
}


def evaluate(mode: str, subject: dict) -> list[dict]:
    """按 mode 判定 subject，返回 finding 列表（唯一对外入口）。"""
    if not isinstance(mode, str):
        raise ValueError("mode 必须是 str，得到 {!r}".format(type(mode).__name__))
    handler = _HANDLERS.get(mode)
    if handler is None:
        raise ValueError("未知 mode: {!r}（可选：{}）".format(mode, " / ".join(MODES)))
    if not isinstance(subject, dict):
        raise ValueError("subject 必须是 dict，得到 {!r}".format(type(subject).__name__))
    return _finalize(handler(subject))


def _finding(rule_id, message, path, evidence):
    return {"rule_id": rule_id, "verdict": _RULE_VERDICT[rule_id],
            "message": message, "path": path, "evidence": dict(evidence)}


def _finalize(findings):
    """输出 schema 守卫：白名单 rule_id / 固定 verdict / 五键齐全。"""
    out = []
    for f in findings:
        rule_id = f.get("rule_id")
        if rule_id not in RULE_IDS:
            raise ValueError("非白名单 rule_id: {!r}".format(rule_id))
        if f.get("verdict") != _RULE_VERDICT[rule_id]:
            raise ValueError("{} 的 verdict 必须是 {}，得到 {!r}".format(
                rule_id, _RULE_VERDICT[rule_id], f.get("verdict")))
        message = f.get("message")
        path = f.get("path")
        evidence = f.get("evidence")
        if not isinstance(message, str) or not message:
            raise ValueError("{}: message 必须是非空 str".format(rule_id))
        if not isinstance(path, str) or not path:
            raise ValueError("{}: path 必须是非空 str".format(rule_id))
        if not isinstance(evidence, dict):
            raise ValueError("{}: evidence 必须是 dict".format(rule_id))
        out.append({"rule_id": rule_id, "verdict": f["verdict"],
                    "message": message, "path": path, "evidence": dict(evidence)})
    return out


# ---------------------------------------------------------------- 输入守卫
def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _req_list(data, key, mode):
    if key not in data or data[key] is None:
        raise ValueError("{}: 缺少字段 {}".format(mode, key))
    value = data[key]
    if not isinstance(value, list):
        raise ValueError("{}: 字段 {} 必须是 list，得到 {}".format(
            mode, key, type(value).__name__))
    return value


def _req_int(data, key, mode, minimum=None):
    if key not in data or data[key] is None:
        raise ValueError("{}: 缺少字段 {}".format(mode, key))
    value = data[key]
    if not _is_int(value):
        raise ValueError("{}: 字段 {} 必须是 int，得到 {!r}".format(mode, key, value))
    if minimum is not None and value < minimum:
        raise ValueError("{}: 字段 {} 必须 >= {}，得到 {}".format(mode, key, minimum, value))
    return value


def _ruleset_of(subject, mode, required=False):
    """取 ruleset；None/缺省 → None（全开），给了就必须是 ``{"rules": [dict...]}``。"""
    raw = subject.get("ruleset")
    if raw is None:
        if required:
            raise ValueError("{}: 缺少字段 ruleset".format(mode))
        return None
    if not isinstance(raw, dict):
        raise ValueError("{}: ruleset 必须是 dict，得到 {}".format(
            mode, type(raw).__name__))
    rules = raw.get("rules")
    if not isinstance(rules, list):
        raise ValueError("{}: ruleset.rules 必须是 list".format(mode))
    for pos, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError("{}: ruleset.rules[{}] 必须是 dict".format(mode, pos))
    return {"rules": rules}


def _is_active(rule):
    """旧仓 ``engine.is_active``：显式 activation 优先，缺省回退 status == verified。"""
    activation = rule.get("activation")
    if activation is not None:
        return activation == "active"
    return rule.get("status") == "verified"


def _first_rule(ruleset, check_type):
    for rule in ruleset["rules"]:
        if rule.get("check_type") == check_type:
            return rule
    return None


def _rule_on(ruleset, check_type):
    """ruleset 为 None → 全开；给了 → 该 check_type 首条规则须 active。"""
    if ruleset is None:
        return True
    rule = _first_rule(ruleset, check_type)
    return rule is not None and _is_active(rule)


def _any_active(ruleset, check_type):
    if ruleset is None:
        return True
    return any(_is_active(r) for r in ruleset["rules"]
               if r.get("check_type") == check_type)


# ---------------------------------------------------------------- 样式树归一
#
# 接受四种摊平形态（旧仓 ``parse_structure`` 的输入/产物都被覆盖）：
#   [{"i": 0, "text": "...", "style": "Heading 1"}, ...]
#   {"paragraphs": [同左], "headings": [{"para": 0, "level": 1, "text": "..."}]}
#   {"style_tree": [同左]}
#   {"headings": [...]}（只有标题序列时）
# 段落按 ``i`` 稳定排序（文档序）；``headings`` 若给出即作为标题序列首选，
# 章节仍按「level == 1 且对应段落样式确为 Heading 1」筛选，避免把摘要伪标题
# 误算成章。
def _para_from_item(item, pos, mode):
    if isinstance(item, str):
        return {"i": pos, "text": item, "style": ""}
    if not isinstance(item, dict):
        raise ValueError("{}: paragraphs[{}] 必须是 str 或 dict".format(mode, pos))
    if "text" not in item:
        raise ValueError("{}: paragraphs[{}] 缺少字段 text".format(mode, pos))
    text = item["text"]
    if not isinstance(text, str):
        raise ValueError("{}: paragraphs[{}].text 必须是 str".format(mode, pos))
    index = item.get("i", item.get("index", pos))
    if not _is_int(index):
        raise ValueError("{}: paragraphs[{}].i 必须是 int".format(mode, pos))
    style = item.get("style", "")
    if not isinstance(style, str):
        raise ValueError("{}: paragraphs[{}].style 必须是 str".format(mode, pos))
    return {"i": index, "text": text, "style": style}


def _paras_from_list(raw, mode):
    if not isinstance(raw, list):
        raise ValueError("{}: paragraphs 必须是 list".format(mode))
    return sorted((_para_from_item(x, pos, mode) for pos, x in enumerate(raw)),
                  key=lambda p: p["i"])


def _normalize_headings(raw, mode):
    if not isinstance(raw, list):
        raise ValueError("{}: headings 必须是 list".format(mode))
    out = []
    for pos, head in enumerate(raw):
        if not isinstance(head, dict):
            raise ValueError("{}: headings[{}] 必须是 dict".format(mode, pos))
        text = head.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("{}: headings[{}].text 必须是非空 str".format(mode, pos))
        level = head.get("level")
        if not _is_int(level) or level < 1:
            raise ValueError("{}: headings[{}].level 必须是 >=1 的 int".format(mode, pos))
        para = head.get("para", head.get("i", head.get("index")))
        if not _is_int(para):
            raise ValueError("{}: headings[{}].para 必须是 int".format(mode, pos))
        out.append({"para": para, "level": level, "text": text.strip()})
    return out


def _style_tree_input(subject, mode):
    if "style_tree" not in subject or subject["style_tree"] is None:
        raise ValueError("{}: 缺少字段 style_tree".format(mode))
    raw = subject["style_tree"]
    headings = None
    if isinstance(raw, list):
        paragraphs = _paras_from_list(raw, mode)
    elif isinstance(raw, dict):
        if "paragraphs" in raw:
            paragraphs = _paras_from_list(raw["paragraphs"], mode)
        elif "style_tree" in raw:
            paragraphs = _paras_from_list(raw["style_tree"], mode)
        else:
            paragraphs = []
        if "headings" in raw and raw["headings"] is not None:
            headings = _normalize_headings(raw["headings"], mode)
    else:
        raise ValueError("{}: style_tree 必须是 list 或 dict，得到 {}".format(
            mode, type(raw).__name__))
    return paragraphs, headings


# ================================================================ AIGC
_TEMPLATE_CONNECTORS = ("首先", "其次", "再次", "最后", "第一，", "第二，", "第三，",
                        "值得注意的是", "需要注意的是", "不难发现", "众所周知")
_SUMMARY_CLICHES = ("综上所述", "总而言之", "总的来说", "综上", "由此可见",
                    "总之", "一言以蔽之")
_PARALLEL_MARKERS = ("不仅", "而且", "一方面", "另一方面", "既", "又", "不但")

_DETECTOR_IDS = ("aigc-01", "aigc-02", "aigc-03", "aigc-04")
_LEXICAL_FEATURES = ("aigc-02", "aigc-03", "aigc-04")
_DEFAULT_FEATURE_NAMES = {
    "aigc-01": "句长均匀性",
    "aigc-02": "模板连接词",
    "aigc-03": "总结套话",
    "aigc-04": "排比结构",
}


def _sentences(text):
    return [s for s in re.split(r"[。！？!?；;]", text) if s.strip()]


def _cv(values):
    """变异系数（总体标准差 / 均值）；样本不足 → None。"""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return (var ** 0.5) / mean


def _density(count, n_chars):
    if n_chars <= 0:
        return 0.0
    return count * 1000.0 / n_chars


def _count_markers(text, markers):
    n = 0
    for marker in markers:
        n += text.count(marker)
    return n


def sentence_length_cv(text):
    lengths = [len(s) for s in _sentences(text)]
    return {"sentences": len(lengths), "lengths": lengths, "cv": _cv(lengths)}


def template_connectors(text):
    count = _count_markers(text, _TEMPLATE_CONNECTORS)
    return {"count": count, "density": _density(count, len(text))}


def summary_cliches(text):
    count = _count_markers(text, _SUMMARY_CLICHES)
    return {"count": count, "density": _density(count, len(text))}


def parallel_structure(text):
    count = _count_markers(text, _PARALLEL_MARKERS)
    return {"count": count, "density": _density(count, len(text))}


def _detect(fid, text):
    if fid == "aigc-01":
        return sentence_length_cv(text)
    if fid == "aigc-02":
        return template_connectors(text)
    if fid == "aigc-03":
        return summary_cliches(text)
    return parallel_structure(text)


def _band(value, threshold):
    """旧仓 ``_band``：>= high → high，>= warn → warn，否则 None。"""
    if threshold is None:
        return None
    high = threshold.get("high")
    warn = threshold.get("warn")
    if high is not None and value >= high:
        return "high"
    if warn is not None and value >= warn:
        return "warn"
    return None


def _normalize_features(raw, mode):
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("{}: features 必须是 dict".format(mode))
    out = {}
    for fid in _DETECTOR_IDS:
        if fid not in raw:
            continue
        feat = raw[fid]
        if not isinstance(feat, dict):
            raise ValueError("{}: features.{} 必须是 dict".format(mode, fid))
        threshold = feat.get("threshold") or {}
        if not isinstance(threshold, dict):
            raise ValueError("{}: features.{}.threshold 必须是 dict".format(mode, fid))
        norm_th = {}
        for key in ("high", "warn"):
            value = threshold.get(key)
            if value is None:
                continue
            if not _is_num(value):
                raise ValueError("{}: features.{}.threshold.{} 必须是数值".format(
                    mode, fid, key))
            norm_th[key] = value
        weight = feat.get("weight", 0.0)
        if not _is_num(weight):
            raise ValueError("{}: features.{}.weight 必须是数值".format(mode, fid))
        name = feat.get("name", _DEFAULT_FEATURE_NAMES[fid])
        if not isinstance(name, str):
            raise ValueError("{}: features.{}.name 必须是 str".format(mode, fid))
        out[fid] = {"threshold": norm_th, "weight": float(weight), "name": name}
    return out


def _aigc_paragraphs(raw, mode):
    paras = _paras_from_list(raw, mode)
    return [{"i": p["i"], "text": p["text"], "style": p["style"]} for p in paras]


def _risk_score(row, features):
    total = 0.0
    for fid, feat in features.items():
        band = row["bands"].get(fid)
        if not band:
            continue
        total += feat["weight"] * (1.0 if band == "high" else 0.6)
    return round(min(total, 1.0), 4)


def profile_paragraphs(paragraphs, features):
    """逐段算四特征实测值 + 档位 + 风险分（旧仓 ``profile_paragraphs``）。"""
    out = []
    for p in paragraphs:
        text = p["text"]
        if not text.strip() or p["style"].startswith("Heading") or p["style"] in (
                "Title", "Caption"):
            continue
        row = {"para": p["i"], "style": p["style"], "n_chars": len(text)}
        bands = {}
        for fid in _DETECTOR_IDS:
            feat = features.get(fid, {})
            value = _detect(fid, text)
            row[fid] = value
            threshold = feat.get("threshold") or {}
            if fid == "aigc-01":
                cv = value.get("cv")
                # 均匀性判据：CV 越小风险越高，阈值语义为上限（旧仓同口径）
                if cv is None:
                    bands[fid] = None
                elif "high" in threshold and cv <= threshold["high"]:
                    bands[fid] = "high"
                elif "warn" in threshold and cv <= threshold["warn"]:
                    bands[fid] = "warn"
                else:
                    bands[fid] = None
            else:
                bands[fid] = _band(value.get("density", 0.0), threshold)
        row["bands"] = bands
        row["score"] = _risk_score(row, features)
        out.append(row)
    return out


def _feature_evidence(row, fid):
    value = row[fid]
    if fid == "aigc-01":
        return "句长 CV={}".format(value.get("cv"))
    if fid == "aigc-02":
        return "模板连接词 {} 次（密度 {:.1f}/千字）".format(value["count"], value["density"])
    if fid == "aigc-03":
        return "总结套话 {} 次（密度 {:.1f}/千字）".format(value["count"], value["density"])
    return "排比标记 {} 次（密度 {:.1f}/千字）".format(value["count"], value["density"])


def _distribution(rows):
    by_feature = {}
    for fid in _DETECTOR_IDS:
        by_feature[fid] = sum(1 for r in rows if r["bands"].get(fid) in ("warn", "high"))
    fired = [r for r in rows if any(r["bands"].get(f) in ("warn", "high")
                                   for f in _LEXICAL_FEATURES)]
    return {"paragraphs_scored": len(rows),
            "paragraphs_flagged": len(fired),
            "by_feature": by_feature,
            "max_score": max([r["score"] for r in rows] or [0.0]),
            "flagged_paras": [r["para"] for r in fired]}


def _eval_aigc(subject):
    paragraphs = _aigc_paragraphs(_req_list(subject, "paragraphs", "aigc"), "aigc")
    features = _normalize_features(subject.get("features"), "aigc")
    rows = profile_paragraphs(paragraphs, features)
    findings = []
    for row in rows:
        fired = [fid for fid in _LEXICAL_FEATURES
                 if row["bands"].get(fid) in ("warn", "high")]
        if not fired:
            continue
        band = "high" if any(row["bands"][f] == "high" for f in fired) else "warn"
        names = "、".join("{}（{}）".format(fid, features[fid].get("name", ""))
                         for fid in fired)
        findings.append(_finding(
            RULE_AIGC_BAND,
            "段落命中 AIGC 痕迹特征（{}，风险档 {}）：{}；"
            "注意，这是风险提示而非 AIGC 判定".format(
                ",".join(fired), band,
                "；".join(_feature_evidence(row, f) for f in fired)),
            "para:{}/{}".format(row["para"], fired[0]),
            {"para": row["para"], "n_chars": row["n_chars"], "band": band,
             "fired": fired, "names": names, "score": row["score"],
             "bands": dict(row["bands"]),
             "counts": {fid: row[fid].get("count", row[fid].get("cv"))
                        for fid in fired},
             "densities": {fid: row[fid].get("density") for fid in fired}},
        ))
    dist = _distribution(rows)
    findings.append(_finding(
        RULE_AIGC_DIST,
        "全文扫描 {} 段，命中 {} 段；各特征命中段数：{}".format(
            dist["paragraphs_scored"], dist["paragraphs_flagged"],
            "，".join("{}={}".format(fid, dist["by_feature"][fid])
                      for fid in _DETECTOR_IDS)),
        "report",
        {"paragraphs_scored": dist["paragraphs_scored"],
         "paragraphs_flagged": dist["paragraphs_flagged"],
         "by_feature": dist["by_feature"], "max_score": dist["max_score"],
         "flagged_paras": dist["flagged_paras"],
         "features_enabled": sorted(features)},
    ))
    return findings


# ================================================================ 结构
_ABSTRACT_ELEMENTS = {
    "purpose": ("针对", "目的", "旨在", "为了"),
    "method": ("方法", "提出", "设计", "构建", "采用"),
    "result": ("结果", "表明", "验证", "取得", "显示"),
    "conclusion": ("结论", "因此", "说明", "证明"),
}
_CHAPTER_KINDS = {
    "intro": ("绪论", "引言", "研究背景"),
    "related": ("相关工作", "文献综述", "研究现状"),
    "method": ("方法", "框架", "模型", "设计"),
    "experiment": ("实验", "结果", "分析", "验证"),
    "conclusion": ("总结", "结论", "展望"),
}
_CN_NUM = "一二三四五六七八九十"
_CHAPTER_HEAD = re.compile(r"^第\s*[%s\d]{1,3}\s*章" % _CN_NUM)
_KEYWORD_LINE = re.compile(r"^\s*关键词\s*[:：]\s*(.+)$")
_EN_KEYWORD_LINE = re.compile(r"^\s*Keywords\s*[:：]\s*(.+)$", re.I)
_ABSTRACT_HEAD = re.compile(r"^摘\s*要$")
_ABSTRACT_EN_HEAD = re.compile(r"^Abstract$", re.I)


def _heading_level(style):
    match = re.match(r"^Heading\s+(\d)$", style or "")
    return int(match.group(1)) if match else None


def _count_keywords(text):
    parts = [x.strip() for x in re.split(r"[；;，,、]", text) if x.strip()]
    return len(parts)


def _dedupe_headings(items):
    out, seen = [], set()
    for head in items:
        key = (head["para"], head["level"], head["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(head)
    return out


def parse_structure(paragraphs, headings=None):
    """样式树 → 结构模型（旧仓 ``parse_structure`` 的摊平版）。

    ``headings`` 给出时作为标题序列首选；否则按段落样式派生，并把「摘要」/
    「Abstract」伪标题按旧仓口径追加（level 1，但不进 chapters）。
    """
    keyword_counts = {"zh": None, "en": None}
    for p in paragraphs:
        text = p["text"].strip()
        match = _KEYWORD_LINE.match(text)
        if match:
            keyword_counts["zh"] = _count_keywords(match.group(1))
        match = _EN_KEYWORD_LINE.match(text)
        if match:
            keyword_counts["en"] = _count_keywords(match.group(1))
    by_index = {p["i"]: p for p in paragraphs}
    if headings is None:
        derived = []
        for p in paragraphs:
            text = p["text"].strip()
            level = _heading_level(p["style"])
            if level is not None:
                derived.append({"para": p["i"], "level": level, "text": text})
            if _ABSTRACT_HEAD.match(text):
                derived.append({"para": p["i"], "level": 1, "text": text})
            if _ABSTRACT_EN_HEAD.match(text):
                derived.append({"para": p["i"], "level": 1, "text": text})
        headings = _dedupe_headings(derived)
    chapters = []
    for head in headings:
        if head["level"] != 1:
            continue
        para = by_index.get(head["para"])
        if para is None or _heading_level(para["style"]) == 1:
            chapters.append({"para": head["para"], "text": head["text"]})
    return {"headings": headings, "chapters": chapters,
            "keyword_counts": keyword_counts}


def _abstract_text(paragraphs, headings):
    start = None
    for head in headings:
        if _ABSTRACT_HEAD.match(head["text"]):
            start = head["para"]
            break
    if start is None:
        return ""
    out = []
    for p in paragraphs:
        if p["i"] <= start:
            continue
        if _heading_level(p["style"]) is not None or _ABSTRACT_EN_HEAD.match(
                p["text"].strip()):
            break
        out.append(p["text"])
    return " ".join(out)


def _abstract_elements(text):
    return sorted(key for key, words in _ABSTRACT_ELEMENTS.items()
                  if any(word in text for word in words))


def _chapter_categories(chapters):
    cats = set()
    for chapter in chapters:
        text = chapter["text"]
        for cat, words in _CHAPTER_KINDS.items():
            if any(word in text for word in words):
                cats.add(cat)
    return cats


def _theme_words(text):
    runs = re.findall(r"[\u4e00-\u9fff]+", text or "")
    out = set()
    for run in runs:
        out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def _level_jumps(headings):
    out = []
    prev = None
    for head in headings:
        if prev is not None and head["level"] - prev["level"] >= 2:
            out.append({"para": head["para"], "text": head["text"],
                        "from": prev["level"], "to": head["level"]})
        prev = head
    return out


def _count_chapter_summaries(paragraphs, chapters):
    if len(chapters) < 2:
        return 0
    bounds = [c["para"] for c in chapters] + [len(paragraphs)]
    n = 0
    for i in range(len(chapters) - 1):
        seg = [p["text"] for p in paragraphs if bounds[i] < p["i"] < bounds[i + 1]]
        if any(re.search(r"(小结|本章|以上|由此可见|综上)", text) for text in seg):
            n += 1
    return n


def _has_chapter_summary(paragraphs, chapters):
    return _count_chapter_summaries(paragraphs, chapters) >= 1


def _echo_overlap(paragraphs, chapters, abstract_text):
    if not chapters:
        return 0
    last = chapters[-1]["para"]
    conclusion_text = " ".join(p["text"] for p in paragraphs if p["i"] > last)
    return len(_theme_words(conclusion_text) & _theme_words(abstract_text))


def _conclusion_echo(paragraphs, chapters, abstract_text):
    return _echo_overlap(paragraphs, chapters, abstract_text) >= 3


_STRUCT_ITEM_RULE = {
    "abstract_present": RULE_STRUCT_ABSTRACT,
    "abstract_elements": RULE_STRUCT_ABSTRACT,
    "keywords_count": RULE_STRUCT_ABSTRACT,
    "english_abstract": RULE_STRUCT_ABSTRACT,
    "chapters_complete": RULE_STRUCT_CHAPTER,
    "chapter_summary": RULE_STRUCT_CHAPTER,
    "conclusion_echo": RULE_STRUCT_CHAPTER,
    "heading_levels": RULE_STRUCT_HEADING,
}


def _abstract_heading_para(headings):
    for head in headings:
        if _ABSTRACT_HEAD.match(head["text"]):
            return head["para"]
    return None


def _eval_structure(subject):
    paragraphs, headings = _style_tree_input(subject, "structure")
    ruleset = _ruleset_of(subject, "structure")
    model = parse_structure(paragraphs, headings)
    heads = model["headings"]
    abstract_text = _abstract_text(paragraphs, heads)
    elements = _abstract_elements(abstract_text)
    chapters = model["chapters"]
    categories = _chapter_categories(chapters)
    degraded = [h for h in heads
                if _CHAPTER_HEAD.match(h["text"]) and h["level"] != 1]
    jumps = _level_jumps(heads)

    checklist = [
        {"id": "abstract_present", "name": "摘要存在",
         "ok": bool(abstract_text.strip()),
         "evidence": "摘要正文 {} 字".format(len(abstract_text))},
        {"id": "abstract_elements", "name": "摘要四要素（目的/方法/结果/结论）",
         "ok": len(elements) >= 3,
         "evidence": "命中要素：{}".format("、".join(elements) or "无")},
        {"id": "keywords_count", "name": "关键词数量（3-8）",
         "ok": model["keyword_counts"]["zh"] is not None
         and 3 <= model["keyword_counts"]["zh"] <= 8,
         "evidence": "关键词 {} 个".format(model["keyword_counts"]["zh"])},
        {"id": "english_abstract", "name": "英文摘要与 Keywords",
         "ok": model["keyword_counts"]["en"] is not None
         and any(_ABSTRACT_EN_HEAD.match(h["text"]) for h in heads),
         "evidence": "English keywords {} 个".format(model["keyword_counts"]["en"])},
        {"id": "chapters_complete", "name": "章节完整（绪论/方法/实验/结论）",
         "ok": {"intro", "method", "conclusion"} <= categories,
         "evidence": "识别章节类别：{}".format("、".join(sorted(categories)) or "无")},
        {"id": "chapter_summary", "name": "每章小结",
         "ok": _has_chapter_summary(paragraphs, chapters),
         "evidence": "小结段 {} 处".format(_count_chapter_summaries(paragraphs, chapters))},
        {"id": "conclusion_echo", "name": "结论与摘要呼应",
         "ok": _conclusion_echo(paragraphs, chapters, abstract_text),
         "evidence": "结论-摘要共现主题词 {}".format(
             _echo_overlap(paragraphs, chapters, abstract_text))},
        {"id": "heading_levels", "name": "章级标题层级（恒 Heading 1）",
         "ok": not degraded,
         "evidence": "降级章标题 {} 处".format(len(degraded))},
    ]

    findings = []
    if _rule_on(ruleset, "structure_order"):
        for head in degraded:
            findings.append(_finding(
                RULE_STRUCT_HEADING,
                "章标题 '{}' 使用 Heading {}，层级序列断档（章级应为 Heading 1）".format(
                    head["text"], head["level"]),
                "heading:{}".format(head["para"]),
                {"para": head["para"], "level": head["level"],
                 "text": head["text"], "issue": "degraded_chapter_heading"},
            ))
        for jump in jumps:
            findings.append(_finding(
                RULE_STRUCT_HEADING,
                "标题层级从 H{} 跳到 H{}（'{}'）".format(
                    jump["from"], jump["to"], jump["text"]),
                "heading:{}".format(jump["para"]),
                {"para": jump["para"], "from": jump["from"], "to": jump["to"],
                 "text": jump["text"], "issue": "level_jump"},
            ))
    if _rule_on(ruleset, "structure_checklist"):
        abstract_para = _abstract_heading_para(heads)
        for item in checklist:
            if item["ok"]:
                continue
            if item["id"] in ("abstract_elements", "conclusion_echo") and (
                    abstract_para is not None or chapters):
                if item["id"] == "abstract_elements" and abstract_para is not None:
                    path = "heading:{}".format(abstract_para)
                elif item["id"] == "conclusion_echo" and chapters:
                    path = "heading:{}".format(chapters[-1]["para"])
                else:
                    path = "report"
            else:
                path = "report"
            findings.append(_finding(
                _STRUCT_ITEM_RULE[item["id"]],
                "结构检查项未通过：{}（{}）".format(item["name"], item["evidence"]),
                path,
                {"item": item["id"], "name": item["name"],
                 "detail": item["evidence"]},
            ))
    return findings


# ================================================================ 术语与数字
_THOUSANDS = ",\uFF0C"
_REF_LABEL = re.compile(r"^\s*\[\s*\d{1,3}\s*\]")
_SEP_NUM = re.compile(r"\d{1,3}(?:[%s]\d{3})+" % _THOUSANDS)
_PLAIN_NUM = re.compile(r"\d{4,}")


def _norm_ws(text):
    return re.sub(r"\s+", "", text or "")


def _is_exempt(text, style):
    """豁免上下文：标题段（章节号）、参考文献条目、题注。"""
    if style and (style.startswith("Heading") or style in ("Title", "Caption")):
        return True
    return bool(_REF_LABEL.match(text))


def _normalize_terms(raw, mode):
    if not isinstance(raw, list):
        raise ValueError("{}: terms 必须是 list".format(mode))
    out = []
    for pos, term in enumerate(raw):
        if not isinstance(term, dict):
            raise ValueError("{}: terms[{}] 必须是 dict".format(mode, pos))
        canonical = term.get("canonical")
        if not isinstance(canonical, str) or not canonical:
            raise ValueError("{}: terms[{}].canonical 必须是非空 str".format(mode, pos))
        variants = term.get("variants")
        if not isinstance(variants, list) or not variants:
            raise ValueError("{}: terms[{}].variants 必须是非空 list".format(mode, pos))
        norm_variants = []
        for vpos, variant in enumerate(variants):
            if not isinstance(variant, str) or not variant:
                raise ValueError("{}: terms[{}].variants[{}] 必须是非空 str".format(
                    mode, pos, vpos))
            norm_variants.append(variant)
        kind = term.get("kind")
        if kind is not None and not isinstance(kind, str):
            raise ValueError("{}: terms[{}].kind 必须是 str".format(mode, pos))
        out.append({"term_id": term.get("term_id"), "canonical": canonical,
                    "variants": norm_variants, "kind": kind})
    return out


def scan_terms(paragraphs, terms):
    """全文扫术语变体（段内按变体去重；空白同形变体交给 stray 扫描）。"""
    hits = []
    for term in terms:
        canonical = term["canonical"]
        for variant in term["variants"]:
            if _norm_ws(variant) == _norm_ws(canonical):
                continue
            for p in paragraphs:
                if _is_exempt(p["text"], p["style"]):
                    continue
                if variant in p["text"]:
                    hits.append({"term_id": term.get("term_id"),
                                 "canonical": canonical, "variant": variant,
                                 "para": p["i"], "kind": term.get("kind")})
    return hits


def scan_stray_space_terms(paragraphs, terms):
    """空白型变体：按 canonical 字符序列（字符间允许任意空白）匹配，字面不等即报。"""
    hits = []
    for term in terms:
        canonical = term["canonical"]
        variants = [v for v in term["variants"]
                    if _norm_ws(v) == _norm_ws(canonical)]
        if not variants:
            continue
        pattern = re.compile(r"\s*".join(
            re.escape(ch) for ch in canonical if not ch.isspace()))
        for p in paragraphs:
            if _is_exempt(p["text"], p["style"]):
                continue
            for match in pattern.finditer(p["text"]):
                segment = match.group(0)
                if segment != canonical:
                    hits.append({"term_id": term.get("term_id"),
                                 "canonical": canonical, "variant": segment,
                                 "para": p["i"],
                                 "kind": term.get("kind", "stray_space_in_term"),
                                 "stray": True})
    return hits


def scan_number_usage(paragraphs, number_usage):
    """同一整数值带/不带千分位两形态并存 → 不一致。"""
    if not number_usage:
        return []
    groups = {}
    for p in paragraphs:
        text = p["text"]
        if _is_exempt(text, p["style"]):
            continue
        for match in _SEP_NUM.finditer(text):
            value = re.sub(r"[%s]" % _THOUSANDS, "", match.group(0))
            groups.setdefault(value, {"sep": [], "plain": []})
            groups[value]["sep"].append(p["i"])
        for match in _PLAIN_NUM.finditer(text):
            groups.setdefault(match.group(0), {"sep": [], "plain": []})
            groups[match.group(0)]["plain"].append(p["i"])
    out = []
    for value in sorted(groups):
        forms = groups[value]
        if forms["sep"] and forms["plain"]:
            out.append({"value": value,
                        "forms": {"sep": sorted(set(forms["sep"])),
                                  "plain": sorted(set(forms["plain"]))}})
    return out


def heat_zones(hits, paragraphs):
    """变体分布热区：按段落与按章节（段前最近的 Heading 1）统计。"""
    by_para = {}
    for hit in hits:
        by_para[hit["para"]] = by_para.get(hit["para"], 0) + 1
    chapter_of = {}
    current = None
    for p in sorted(paragraphs, key=lambda x: x["i"]):
        if p["style"] == "Heading 1" and p["text"].strip():
            current = p["text"].strip()
        chapter_of[p["i"]] = current
    by_chapter = {}
    for para, count in by_para.items():
        chapter = chapter_of.get(para) or "(篇首)"
        by_chapter[chapter] = by_chapter.get(chapter, 0) + count
    return {"by_para": dict(sorted(by_para.items())),
            "by_chapter": dict(sorted(by_chapter.items(), key=lambda kv: -kv[1]))}


def _eval_terms(subject):
    paragraphs, _headings = _style_tree_input(subject, "terms")
    terms = _normalize_terms(_req_list(subject, "terms", "terms"), "terms")
    number_usage = subject.get("number_usage")
    if number_usage is not None and not isinstance(number_usage, dict):
        raise ValueError("terms: number_usage 必须是 dict 或 None")
    ruleset = _ruleset_of(subject, "terms")
    enabled = _any_active(ruleset, "term_consistency")
    if enabled:
        hits = scan_terms(paragraphs, terms) + scan_stray_space_terms(paragraphs, terms)
        issues = scan_number_usage(paragraphs, number_usage)
    else:
        hits, issues = [], []

    findings = []
    for hit in hits:
        rule_id = (RULE_TERM_STRAY
                   if hit.get("stray") else RULE_TERM_HIT)
        findings.append(_finding(
            rule_id,
            "术语 '{}' 出现变体写法 '{}'（标准写法：{}）".format(
                hit["canonical"], hit["variant"], hit["canonical"]),
            "term:{}@para:{}".format(hit["variant"], hit["para"]),
            {"term_id": hit["term_id"], "canonical": hit["canonical"],
             "variant": hit["variant"], "kind": hit["kind"], "para": hit["para"]},
        ))
    for issue in issues:
        paras = sorted(set(issue["forms"]["sep"] + issue["forms"]["plain"]))
        for para in paras:
            other = (issue["forms"]["plain"] if para in issue["forms"]["sep"]
                     else issue["forms"]["sep"])
            findings.append(_finding(
                RULE_TERM_NUMBER,
                "数值 {} 写法不一致：本处与段落 {} 的千分位用法不同".format(
                    issue["value"], sorted(set(other))),
                "para:{}/number_form".format(para),
                {"value": issue["value"], "para": para,
                 "forms": {"sep": list(issue["forms"]["sep"]),
                           "plain": list(issue["forms"]["plain"])},
                 "other_paras": sorted(set(other))},
            ))
    heat = heat_zones(
        hits + [{"para": para}
                for issue in issues
                for para in issue["forms"]["sep"] + issue["forms"]["plain"]],
        paragraphs)
    findings.append(_finding(
        RULE_TERM_HEAT,
        "术语命中热区：{} 段，共 {} 次；涉及章节 {} 个".format(
            len(heat["by_para"]),
            sum(heat["by_para"].values()) if heat["by_para"] else 0,
            len(heat["by_chapter"])),
        "report",
        {"by_para": heat["by_para"], "by_chapter": heat["by_chapter"],
         "hits": len(hits), "number_issues": len(issues)},
    ))
    return findings


# ================================================================ 图表/公式/交叉引用
KIND_ZH = {"figure": "图", "table": "表", "equation": "式"}

_LABEL_NO = re.compile(r"^(?:图|表|式\()\s*(\d{1,2})[-\uFF0D\u2014\u2013]\s*(\d{1,2})\s*\)?$")
_LABEL_MENTION = re.compile(
    r"(图|表|式\()\s*(\d{1,2})\s*[-\uFF0D\u2014\u2013]\s*(\d{1,2})\s*\)?")
_CAPTION_STOP = re.compile(r"[,，。；;：:]")
_CAPTION_HEAD = re.compile(r"^(图|表)\s*\d{1,2}\s*[-\uFF0D\u2014\u2013]\s*\d{1,2}")


def parse_label_no(label):
    """'图3-1' / '表4-2' / '式(3-1)' → (chapter, number)；解析不出 → None。"""
    if not label:
        return None
    match = _LABEL_NO.match(label.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def number_gaps(objects):
    """同章同类对象的编号断档（章间各自重新起编，非从 1 起也报）。"""
    groups = {}
    for obj in objects:
        parsed = parse_label_no(obj.get("label"))
        if parsed is None:
            continue
        chapter, num = parsed
        groups.setdefault((obj["kind"], chapter), []).append((num, obj))
    out = []
    for (kind, chapter), items in sorted(groups.items()):
        nums = sorted(num for num, _obj in items)
        high = max(nums)
        missing = [n for n in range(1, high + 1) if n not in nums]
        if missing:
            sample = next(obj for num, obj in items if num == nums[0])
            out.append({"kind": kind, "chapter": chapter, "missing": missing,
                        "label": sample.get("label"),
                        "caption_para": sample.get("caption_para")})
    return out


def object_items(objects, markers):
    """对象 + 正文标记 → NumberedItem 序列（marker_id 全局唯一 ``mk-<oi>-<n>``）。"""
    by_label = {}
    for marker in markers:
        by_label.setdefault(marker["label"], []).append(marker)
    items = []
    for oi, obj in enumerate(objects):
        marks = by_label.get(obj["label"], [])
        items.append({"item_id": obj["label"],
                      "markers": [{"marker_id": "mk-{}-{}".format(oi, i),
                                   "para": m.get("para_index")}
                                  for i, m in enumerate(marks)]})
    return items


def _renumber(items, edits):
    """旧仓 ``renumber.renumber`` 的纯移植（不修改入参）。"""
    seq = [{"item_id": it["item_id"],
            "markers": [dict(m) for m in it.get("markers", [])]}
           for it in items]
    diagnostics = []
    for edit in edits:
        etype = edit.get("type")
        target = edit.get("target")
        idx = _index_of(seq, target)
        if etype == "insert":
            new_id = edit.get("new_item_id")
            if new_id is None:
                diagnostics.append({"kind": "insert_missing_new_item_id", "edit": edit})
                continue
            if idx is None:
                seq.append({"item_id": new_id,
                            "markers": [dict(m) for m in edit.get("markers", [])]})
                diagnostics.append({"kind": "insert_target_missing_appended",
                                    "target": target})
                continue
            pos = idx if edit.get("before") else idx + 1
            seq.insert(pos, {"item_id": new_id,
                             "markers": [dict(m) for m in edit.get("markers", [])]})
        elif etype == "delete":
            if idx is None:
                diagnostics.append({"kind": "delete_target_missing", "target": target})
                continue
            seq.pop(idx)
        else:
            diagnostics.append({"kind": "unknown_edit_type", "edit": edit})

    old_no = {it["item_id"]: i + 1 for i, it in enumerate(items)}
    mappings = []
    seen_new = {}
    for new_idx, it in enumerate(seq, 1):
        seen_new.setdefault(it["item_id"], []).append(new_idx)
    for new_idx, it in enumerate(seq, 1):
        for marker in it["markers"]:
            mappings.append({"marker_id": marker.get("marker_id"),
                             "item_id": it["item_id"],
                             "old_no": old_no.get(it["item_id"]),
                             "new_no": new_idx})
    duplicates = sorted(k for k, v in seen_new.items() if len(v) > 1)
    if duplicates:
        diagnostics.append({"kind": "duplicate_item_id_after_edits",
                            "items": duplicates})
    marker_owner = {}
    marker_dup = []
    for it in seq:
        for mid in [m.get("marker_id") for m in it.get("markers", [])]:
            if mid is None:
                continue
            if mid in marker_owner and marker_owner[mid] != it["item_id"]:
                marker_dup.append(mid)
            marker_owner[mid] = it["item_id"]
    if marker_dup:
        diagnostics.append({"kind": "marker_claimed_by_multiple_items",
                            "markers": marker_dup})
    consistent = not duplicates and not marker_dup
    return {"mappings": mappings, "consistent": consistent,
            "new_order": [it["item_id"] for it in seq],
            "n_items": len(seq), "diagnostics": diagnostics}


def _index_of(seq, item_id):
    for i, item in enumerate(seq):
        if item["item_id"] == item_id:
            return i
    return None


def verify_plan(plan):
    """独立复核 RenumberPlan（不信任构造期自报的 consistent）。"""
    order = plan["new_order"]
    n = len(order)
    if sorted(set(order)) != sorted(order):
        return False
    position = {item_id: i + 1 for i, item_id in enumerate(order)}
    seen = {}
    for mapping in plan["mappings"]:
        if mapping["new_no"] != position.get(mapping["item_id"]):
            return False
        if not 1 <= mapping["new_no"] <= n:
            return False
        key = mapping["marker_id"]
        if key is None:
            continue
        if key in seen:
            return False
        seen[key] = mapping["item_id"]
    if n and sorted(position.values()) != list(range(1, n + 1)):
        return False
    return bool(plan["consistent"])


def renumber_objects(objects, markers, edits):
    """对对象编号执行重排 → RenumberPlan（复用迁入内核）。"""
    return _renumber(object_items(objects, markers), edits)


def _norm_objects(raw):
    if raw is None:
        raise ValueError("figures: parsed 缺少 objects（摊平事实）")
    if not isinstance(raw, list):
        raise ValueError("figures: objects 必须是 list")
    out = []
    for pos, obj in enumerate(raw):
        if not isinstance(obj, dict):
            raise ValueError("figures: objects[{}] 必须是 dict".format(pos))
        label = obj.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError("figures: objects[{}].label 必须是非空 str".format(pos))
        kind = obj.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("figures: objects[{}].kind 必须是非空 str".format(pos))
        caption = obj.get("caption_para")
        if caption is not None and not _is_int(caption):
            raise ValueError("figures: objects[{}].caption_para 必须是 int 或 None".format(pos))
        out.append({"kind": kind, "label": label, "caption_para": caption})
    return out


def _norm_markers(raw, key):
    if not isinstance(raw, list):
        raise ValueError("figures: {} 必须是 list".format(key))
    out = []
    for pos, marker in enumerate(raw):
        if not isinstance(marker, dict):
            raise ValueError("figures: {}[{}] 必须是 dict".format(key, pos))
        label = marker.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError("figures: {}[{}].label 必须是非空 str".format(key, pos))
        para = marker.get("para_index")
        if para is not None and not _is_int(para):
            raise ValueError("figures: {}[{}].para_index 必须是 int 或 None".format(key, pos))
        out.append({"label": label, "para_index": para})
    return out


def _norm_dangling(raw):
    if not isinstance(raw, list):
        raise ValueError("figures: dangling 必须是 list")
    out = []
    for pos, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("figures: dangling[{}] 必须是 dict".format(pos))
        label = item.get("label")
        if not isinstance(label, str) or not label:
            raise ValueError("figures: dangling[{}].label 必须是非空 str".format(pos))
        norm = {"label": label, "kind": item.get("kind"),
               "raw": item.get("raw"), "para_index": item.get("para_index"),
               "target_bookmark": item.get("target_bookmark")}
        if norm["kind"] is not None and not isinstance(norm["kind"], str):
            raise ValueError("figures: dangling[{}].kind 必须是 str".format(pos))
        if norm["raw"] is not None and not isinstance(norm["raw"], str):
            raise ValueError("figures: dangling[{}].raw 必须是 str".format(pos))
        if norm["para_index"] is not None and not _is_int(norm["para_index"]):
            raise ValueError("figures: dangling[{}].para_index 必须是 int".format(pos))
        if norm["target_bookmark"] is not None and not isinstance(
                norm["target_bookmark"], str):
            raise ValueError("figures: dangling[{}].target_bookmark 必须是 str".format(pos))
        out.append(norm)
    return out


def _norm_ghosts(raw):
    if not isinstance(raw, list):
        raise ValueError("figures: ghosts 必须是 list")
    out = []
    for pos, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("figures: ghosts[{}] 必须是 dict".format(pos))
        label = item.get("label")
        kind = item.get("kind")
        if not isinstance(label, str) or not label:
            raise ValueError("figures: ghosts[{}].label 必须是非空 str".format(pos))
        if not isinstance(kind, str) or not kind:
            raise ValueError("figures: ghosts[{}].kind 必须是非空 str".format(pos))
        caption = item.get("caption_para")
        if caption is not None and not _is_int(caption):
            raise ValueError("figures: ghosts[{}].caption_para 必须是 int 或 None".format(pos))
        out.append({"kind": kind, "label": label, "caption_para": caption})
    return out


def _facts_from_parsed(parsed):
    if not isinstance(parsed, dict):
        raise ValueError("figures: parsed 必须是 dict")
    objects = _norm_objects(parsed.get("objects"))
    if "markers" in parsed:
        markers = _norm_markers(parsed["markers"], "markers")
        markers_present = True
    elif "mentions" in parsed:
        markers = _norm_markers(parsed["mentions"], "mentions")
        markers_present = True
    else:
        markers = []
        markers_present = False
    labels = {obj["label"] for obj in objects}
    if parsed.get("dangling") is not None:
        dangling = _norm_dangling(parsed["dangling"])
    elif markers_present:
        dangling = [{"label": m["label"], "kind": "typed", "raw": m["label"],
                     "para_index": m["para_index"], "target_bookmark": None}
                    for m in markers if m["label"] not in labels]
    else:
        dangling = []
    if parsed.get("ghosts") is not None:
        ghosts = _norm_ghosts(parsed["ghosts"])
    elif markers_present:
        # 旧仓口径：公式段自身即提及，故 equation 不参与幽灵推导
        mentioned = {m["label"] for m in markers}
        ghosts = [{"kind": obj["kind"], "label": obj["label"],
                   "caption_para": obj.get("caption_para")}
                  for obj in objects
                  if obj["label"] not in mentioned and obj["kind"] != "equation"]
    else:
        ghosts = []
    return {"objects": objects, "markers": markers,
            "dangling": dangling, "ghosts": ghosts}


def _kind_of_label(label):
    if label.startswith("图"):
        return "figure"
    if label.startswith("表"):
        return "table"
    if label.startswith("式"):
        return "equation"
    return "object"


def _label_key(label):
    parsed = parse_label_no(label)
    if parsed is None:
        return None
    return (_kind_of_label(label), parsed[0], parsed[1])


def _mention_key(match):
    kind = match.group(1)
    if kind.startswith("式"):
        return ("equation", int(match.group(2)), int(match.group(3)))
    return ({"图": "figure", "表": "table"}[kind],
            int(match.group(2)), int(match.group(3)))


def _mention_label(match):
    if match.group(1).startswith("式"):
        return "式({}-{})".format(match.group(2), match.group(3))
    return "{}{}-{}".format(match.group(1), match.group(2), match.group(3))


def _text_paragraphs(text, mode):
    if isinstance(text, str):
        lines = [line for line in text.splitlines() if line.strip()]
        return [{"i": i, "text": line, "style": ""} for i, line in enumerate(lines)]
    if isinstance(text, list):
        return _paras_from_list(text, mode)
    raise ValueError("figures: text 必须是 str 或 list")


def _is_caption_para(paragraph):
    text = paragraph["text"].strip()
    if paragraph["style"] == "Caption":
        return True
    if not _CAPTION_HEAD.match(text):
        return False
    return _CAPTION_STOP.search(text) is None


def _facts_from_labels_text(labels, text):
    if not isinstance(labels, list):
        raise ValueError("figures: labels 必须是 list")
    norm_labels = []
    for pos, label in enumerate(labels):
        if not isinstance(label, str) or not label:
            raise ValueError("figures: labels[{}] 必须是非空 str".format(pos))
        norm_labels.append(label.strip())
    paragraphs = _text_paragraphs(text, "figures")
    raw_text = " ".join(p["text"] for p in paragraphs)
    objects = [{"kind": _kind_of_label(label), "label": label,
                "caption_para": None} for label in norm_labels]
    label_keys = {_label_key(label) for label in norm_labels} - {None}
    label_set = set(norm_labels)

    mention_keys = set()
    dangling = []
    for p in paragraphs:
        for match in _LABEL_MENTION.finditer(p["text"]):
            key = _mention_key(match)
            if _is_caption_para(p) and p["text"].lstrip().startswith(
                    match.group(0).strip()):
                continue  # 题注段自身编号不算提及
            mention_keys.add(key)
            if key in label_keys:
                continue
            dangling.append({"label": _mention_label(match), "kind": "typed",
                             "raw": match.group(0).strip(),
                             "para_index": p["i"], "target_bookmark": None})
    ghosts = []
    for obj in objects:
        key = _label_key(obj["label"])
        if key is not None:
            if key in mention_keys:
                continue
        elif obj["label"] in raw_text:
            continue
        ghosts.append({"kind": obj["kind"], "label": obj["label"],
                       "caption_para": None})
    return {"objects": objects, "markers": [], "dangling": dangling,
            "ghosts": ghosts}


def _normalize_edits(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("figures: edits 必须是 list")
    out = []
    for pos, edit in enumerate(raw):
        if not isinstance(edit, dict):
            raise ValueError("figures: edits[{}] 必须是 dict".format(pos))
        etype = edit.get("type")
        if etype not in ("insert", "delete"):
            raise ValueError("figures: edits[{}].type 必须是 insert/delete".format(pos))
        target = edit.get("target")
        if not isinstance(target, str) or not target:
            raise ValueError("figures: edits[{}].target 必须是非空 str".format(pos))
        if etype == "insert":
            new_id = edit.get("new_item_id")
            if not isinstance(new_id, str) or not new_id:
                raise ValueError("figures: edits[{}].new_item_id 必须是非空 str".format(pos))
            markers = edit.get("markers", [])
            if not isinstance(markers, list):
                raise ValueError("figures: edits[{}].markers 必须是 list".format(pos))
            out.append({"type": "insert", "new_item_id": new_id,
                        "target": target, "before": bool(edit.get("before", False)),
                        "markers": markers})
        else:
            out.append({"type": "delete", "target": target})
    return out


def _eval_figures(subject):
    if "parsed" in subject:
        if subject["parsed"] is None:
            raise ValueError("figures: parsed 不能是 None")
        facts = _facts_from_parsed(subject["parsed"])
    elif "labels" in subject or "text" in subject:
        if "labels" not in subject or "text" not in subject:
            raise ValueError("figures: labels 与 text 必须同时给")
        facts = _facts_from_labels_text(subject["labels"], subject["text"])
    else:
        raise ValueError("figures: 需要 parsed 或 labels+text")
    edits = _normalize_edits(subject.get("edits"))
    ruleset = _ruleset_of(subject, "figures")

    findings = []
    if _rule_on(ruleset, "dangling_reference"):
        for item in facts["dangling"]:
            mode_text = "REF 域" if item.get("kind") == "ref_field" else "手打编号"
            raw = item.get("raw") or item["label"]
            detail = "正文{}提及 '{}'，全文不存在该对象".format(mode_text, raw)
            if item.get("kind") == "ref_field" and item.get("target_bookmark"):
                detail = "REF 域指向的书签 {} 在文档中不存在（显示为 '{}'）".format(
                    item["target_bookmark"], raw)
            findings.append(_finding(
                RULE_FIG_XREF, detail, "object:{}".format(item["label"]),
                {"mode": item.get("kind"), "label": item["label"], "raw": raw,
                 "target_bookmark": item.get("target_bookmark"),
                 "para_index": item.get("para_index"), "issue": "dangling_reference"},
            ))
    if _rule_on(ruleset, "ghost_object"):
        for item in facts["ghosts"]:
            findings.append(_finding(
                RULE_FIG_XREF,
                "对象 '{}' 存在但全文无任何提及".format(item["label"]),
                "object:{}".format(item["label"]),
                {"kind": item["kind"], "label": item["label"],
                 "caption_para": item.get("caption_para"), "ghost": True,
                 "issue": "ghost_object"},
            ))
    if _rule_on(ruleset, "xref_order"):
        for gap in number_gaps(facts["objects"]):
            findings.append(_finding(
                RULE_FIG_GAP,
                "{} 在'第{}章'的编号断档：缺 {}".format(
                    KIND_ZH.get(gap["kind"], gap["kind"]),
                    gap["chapter"], gap["missing"]),
                "object:{}".format(gap["label"]),
                {"kind": gap["kind"], "chapter": gap["chapter"],
                 "missing": gap["missing"], "caption_para": gap["caption_para"]},
            ))

    plan = _renumber(object_items(facts["objects"], facts["markers"]), edits)
    verified = verify_plan(plan)
    findings.append(_finding(
        RULE_FIG_RENUMBER,
        "编号重排内核自检：{} 个对象 / {} 个正文标记，锚定旧编号 {} 个；"
        "一致性 {}".format(
            len(facts["objects"]), len(facts["markers"]),
            sum(1 for m in plan["mappings"] if m["old_no"] is not None),
            "通过" if (plan["consistent"] and verified) else "不通过"),
        "report",
        {"n_items": plan["n_items"],
         "n_markers": len(plan["mappings"]),
         "consistent": plan["consistent"],
         "verified": verified,
         "new_order": plan["new_order"],
         "diagnostics": plan["diagnostics"],
         "edits": edits},
    ))
    return findings


# ================================================================ 学校格式
_CHAP_TITLE = re.compile(r"^第\s*\d{1,2}\s*章[\s\u3000]")
_SENT_END = "。！？!?"


def _is_caption(text):
    return bool(_CAPTION_HEAD.match(text)) and _CAPTION_STOP.search(text) is None


def check_style(paragraphs, ruleset):
    """样式核查：章标题层级 / 题注样式 / 正文误用标题样式（三条确定性判据）。"""
    if not _rule_on(ruleset, "style"):
        return []
    findings = []
    for p in paragraphs:
        text = p["text"].strip()
        style = p["style"]
        if not text:
            continue
        if _CHAP_TITLE.match(text) and style != "Heading 1":
            findings.append(_finding(
                RULE_SCHOOL_STYLE,
                "章标题使用 {}，应为 Heading 1".format(style),
                "para:{}/heading_level".format(p["i"]),
                {"para": p["i"], "style": style, "text": text,
                 "issue": "chapter_heading_style"},
            ))
            continue
        if _is_caption(text) and style != "Caption":
            findings.append(_finding(
                RULE_SCHOOL_STYLE,
                "题注段落使用 {} 样式，应为 Caption".format(style),
                "para:{}/caption_style".format(p["i"]),
                {"para": p["i"], "style": style, "text": text,
                 "issue": "caption_style"},
            ))
            continue
        if style.startswith("Heading") and text[-1] in _SENT_END:
            findings.append(_finding(
                RULE_SCHOOL_STYLE,
                "正文段落误用 {} 样式".format(style),
                "para:{}/body_style".format(p["i"]),
                {"para": p["i"], "style": style, "text": text,
                 "issue": "body_style"},
            ))
    return findings


def _dig(model, path):
    cur = model
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _eval_format(got, op, want, tolerance):
    """规则求值 → (通过?, detail)。模型缺字段视为不通过并如实说明。"""
    if got is None:
        return False, "文档缺少可判定的 {}（无法核对）".format(want)
    tol = 0.0 if tolerance is None else float(tolerance)
    if op == "present":
        ok = bool(got) is bool(want)
        return ok, "{}：要求 {}，实际 {}".format(
            "符合" if ok else "不符合",
            "存在" if want else "不存在",
            "存在" if got else "不存在")
    if op in ("eq", "gte", "lte") and _is_num(want):
        try:
            got_number = float(got)
        except (TypeError, ValueError):
            raise ValueError("format: 字段 {} 的实际值 {!r} 不是数值".format(want, got))
        if op == "eq":
            ok = abs(got_number - float(want)) <= tol
        elif op == "gte":
            ok = got_number + tol >= float(want)
        else:
            ok = got_number - tol <= float(want)
        return ok, "{}：要求 {} {}，实际 {}".format(
            "符合" if ok else "不符合", op, want, got)
    if op == "eq":
        ok = got == want
        return ok, "{}：要求为 {}，实际为 {}".format(
            "符合" if ok else "不符合", want, got)
    return False, "未知判定算子 {}（profile 配置错误）".format(op)


def check_format(doc_format, ruleset):
    """模板核查：逐条 active 的 format 规则求值，不符合 → finding。"""
    findings = []
    for rule in ruleset["rules"]:
        if rule.get("check_type") != "format":
            continue
        if not _is_active(rule):
            continue
        detect = rule.get("detect")
        if not isinstance(detect, dict):
            raise ValueError("school: format 规则缺少 detect")
        param = detect.get("param")
        if not isinstance(param, str) or not param:
            raise ValueError("school: format 规则 detect.param 必须是非空 str")
        op = detect.get("op", "eq")
        if not isinstance(op, str):
            raise ValueError("school: format 规则 detect.op 必须是 str")
        want = detect.get("value")
        tolerance = detect.get("tolerance")
        if tolerance is not None and not _is_num(tolerance):
            raise ValueError("school: format 规则 detect.tolerance 必须是数值")
        got = _dig(doc_format, param)
        ok, detail = _eval_format(got, op, want, tolerance)
        if ok:
            continue
        findings.append(_finding(
            RULE_SCHOOL_FORMAT, detail, "report",
            {"param": param, "op": op, "want": want, "got": got,
             "tolerance": tolerance, "source_rule_id": rule.get("rule_id"),
             "detail": detail},
        ))
    return findings


def _eval_school(subject):
    ruleset = _ruleset_of(subject, "school", required=True)
    has_style = "style_tree" in subject and subject["style_tree"] is not None
    has_format = "doc_format" in subject and subject["doc_format"] is not None
    if not has_style and not has_format:
        raise ValueError("school: 需要 style_tree 或 doc_format")
    findings = []
    if has_style:
        paragraphs, _headings = _style_tree_input(subject, "school")
        findings.extend(check_style(paragraphs, ruleset))
    if has_format:
        doc_format = subject["doc_format"]
        if not isinstance(doc_format, dict):
            raise ValueError("school: doc_format 必须是 dict")
        findings.extend(check_format(doc_format, ruleset))
    return findings


# ================================================================ 确定性 RNG
MASK64 = 0xFFFFFFFFFFFFFFFF
_GOLDEN = 0x9E3779B97F4A7C15
_U64_COUNT = 1 << 64


class SplitMix64:
    """splitmix64：state 每次 +GOLDEN，再三次混合（Steele/Lea/Batson）。"""

    def __init__(self, seed):
        self._state = seed & MASK64

    def next_u64(self):
        self._state = (self._state + _GOLDEN) & MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, n):
        if n <= 0:
            raise ValueError("below() 要求 n >= 1，得到 {}".format(n))
        return self.next_u64() % n

    def randrange(self, lo, hi):
        if hi <= lo:
            raise ValueError("randrange(lo, hi) 要求 hi > lo，得到 ({}, {})".format(lo, hi))
        return lo + self.below(hi - lo)

    def chance(self, p):
        if not 0.0 <= p <= 1.0:
            raise ValueError("chance() 概率必须在 [0, 1]，得到 {}".format(p))
        return self.next_u64() < int(p * _U64_COUNT)

    def choice(self, seq):
        return seq[self.below(len(seq))]

    def shuffle(self, items):
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]
        return items

    def sample(self, seq, k):
        if k > len(seq):
            raise ValueError("sample(k={}) 超过序列长度 {}".format(k, len(seq)))
        pool = list(seq)
        self.shuffle(pool)
        return pool[:k]


def _eval_rng(subject):
    seed = _req_int(subject, "seed", "rng")
    n = _req_int(subject, "n", "rng", minimum=0)
    upper = subject.get("max")
    if upper is not None:
        if not _is_int(upper):
            raise ValueError("rng: max 必须是 int 或 None")
        if upper <= 0:
            raise ValueError("rng: max 必须 >= 1，得到 {}".format(upper))

    def _draw():
        gen = SplitMix64(seed)
        if upper is None:
            return [gen.next_u64() for _ in range(n)]
        return [gen.below(upper) for _ in range(n)]

    values = _draw()
    repeat = _draw()
    deterministic = values == repeat
    findings = [_finding(
        RULE_RNG_DETERMINISM,
        "splitmix64 确定性自检：seed={} 连续 {} 个值，两次独立实例{}".format(
            seed, n, "逐值一致" if deterministic else "出现分歧"),
        "report",
        {"seed": seed, "seed_masked": seed & MASK64, "n": n, "max": upper,
         "values": values, "first": values[0] if values else None,
         "total": sum(values), "deterministic": deterministic,
         "runs": 2, "within_max": (upper is None or all(v < upper for v in values))},
    )]
    return findings


_HANDLERS = {
    "aigc": _eval_aigc,
    "structure": _eval_structure,
    "terms": _eval_terms,
    "figures": _eval_figures,
    "school": _eval_school,
    "rng": _eval_rng,
}