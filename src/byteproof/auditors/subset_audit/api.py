"""编排层：``evaluate(subject, basis) -> Iterable[Record]``。

三模式 = 旧仓三个判定模块（license-gate 不迁：D1 排除词）。fontTools 解析与表读取全部
留输入层：subject 携带摊平事实（cmap 映射 / OS/2 位域 / nameID / 布局摊平 / OS2_UNICODE_RANGES
表 / 独立字形计数）。Finding 构造与排序口径（module → severity 序 → primary_key）经
``core.finding``/``core.sort_findings`` 保留；账本 verdict 按旧仓 severity 折算
（error→error、warn→warn、note→info、SKIPPED→info 显式记录）。

退出码映射：旧仓 0 无事故 / 1 有 error 级 finding / 2 输入非法（InputError）→
新 0 / 1 / 2（语义一致，无口径差）；SKIPPED 不是事故（info）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import core, spec
from .catalogue import Catalogue

_SEVERITY_RULE = {
    ("coverage-diff", spec.CODE_MISSING): ("sa-missing-in-source", "warn"),
    ("coverage-diff", spec.CODE_LOST): ("sa-lost-in-subset", "error"),
    ("layout-survival", spec.CODE_FEATURE_LOST): ("sa-layout-feature-lost", "error"),
    ("layout-survival", spec.CODE_LIGATURE_LOST): ("sa-layout-ligature-lost", "error"),
    ("layout-survival", spec.CODE_LIGATURE_RENAMED): ("sa-layout-ligature-renamed", "warn"),
}
_NAME_RULE = "sa-name-stripped"
_META_RULE = {
    spec.CODE_CODEPAGE_LATIN1: ("sa-codepage-latin1-overdeclared", ERROR),
    spec.CODE_UNICODE_OVER: ("sa-unicode-range-overdeclared", WARN),
    spec.CODE_MAXP_MISMATCH: ("sa-maxp-mismatch", ERROR),
    spec.CODE_CHAR_INDEX: ("sa-char-index-mismatch", WARN),
}
_SKIP_RULE = {
    ("coverage-diff", spec.REASON_NO_CMAP_TABLE): "sa-skip-no-cmap",
    ("coverage-diff", spec.REASON_NO_UNICODE_CMAP): "sa-skip-no-unicode-cmap",
    ("layout-survival", spec.REASON_NO_TABLES): "sa-skip-no-layout-tables",
    ("layout-survival", spec.REASON_ONE_SIDE): "sa-skip-layout-one-side",
    ("metadata", spec.REASON_NO_OS2): "sa-skip-no-os2",
    ("metadata", spec.REASON_NO_NAME): "sa-skip-no-name",
    ("metadata", spec.REASON_NO_CMAP_TABLE): "sa-skip-no-cmap",
    ("metadata", spec.REASON_NO_UNICODE_CMAP): "sa-skip-no-unicode-cmap",
    ("metadata", spec.REASON_NO_OUTLINE): "sa-skip-no-outline",
}
_SKIP_RULE_FALLBACK = "sa-skip-other"


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if mode not in spec.MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(spec.MODES), mode))
    catalog = Catalogue(basis)

    if mode == "coverage-diff":
        result = _coverage(subject)
    elif mode == "layout-survival":
        result = _layout(subject)
    else:
        result = _metadata(subject)

    records = _records(result, catalog)
    records.append(_summary_record(mode, result, records, basis))
    return records


# ---------------------------------------------------------------- 模式分发
def _coverage(subject: Mapping[str, Any]) -> Dict[str, Any]:
    required = core.from_text(subject.get("required_text") or "")
    required = required | set(subject.get("required") or [])
    findings, skips, summary = core.evaluate_coverage(
        required,
        subject.get("source_cmap") or {},
        subject.get("subset_cmap"),
        strict_source=bool((subject.get("options") or {}).get("strict_source")),
        source_cmap_facts=subject.get("source_cmap_facts"),
        subset_cmap_facts=subject.get("subset_cmap_facts"),
    )
    return {"module": "coverage-diff", "findings": findings, "skips": skips, "summary": summary}


def _layout(subject: Mapping[str, Any]) -> Dict[str, Any]:
    source_flat = subject.get("source_layout") or {"GSUB": None, "GPOS": None}
    subset_flat = subject.get("subset_layout") or {"GSUB": None, "GPOS": None}
    findings, skips, summary = core.compare_layout(source_flat, subset_flat)
    return {"module": "layout-survival", "findings": findings, "skips": skips, "summary": summary}


def _metadata(subject: Mapping[str, Any]) -> Dict[str, Any]:
    os2 = subject.get("os2")
    if not os2:
        return {"module": "metadata",
                "findings": [], "skips": [core.skipped("metadata", spec.REASON_NO_OS2,
                                                       "subset: 该字体没有 OS/2 表")],
                "summary": {}}
    codepoints = set(subject.get("codepoints") or [])
    unicode_ranges = subject.get("unicode_ranges") or []
    subset_ids = subject.get("subset_name_ids") or {}
    source_ids = subject.get("source_name_ids")
    findings: List[Dict[str, Any]] = []
    skips: List[Dict[str, Any]] = []

    _present, _missing, classes = core._name_state(subset_ids, source_ids)
    findings.extend(core._name_findings(classes))
    findings.extend(core.codepage_findings(os2, codepoints))
    ur, _unknown = core.unicode_range_findings(os2, codepoints, unicode_ranges)
    findings.extend(ur)
    maxp_f, measured = core.maxp_findings(os2.get("numGlyphs"), subject.get("measured_glyphs"))
    findings.extend(maxp_f)
    if measured is None:
        skips.append(core.skipped("metadata", spec.REASON_NO_OUTLINE,
                                  "subset: 既无 glyf/loca 也无 CFF，maxp 无独立量可比（其余判定照常）"))
    char_f, _judged = core.char_index_findings(os2, codepoints)
    findings.extend(char_f)

    summary = {"metadata": {
        "name": {"present": _present, "classes": {k: v for k, v in classes.items() if v}},
        "unicode_ranges": core.unicode_range_summary(os2, codepoints, unicode_ranges),
        "maxp": {"numGlyphs": os2.get("numGlyphs"), "measured": measured},
        "codepoints_total": len(codepoints),
    }}
    return {"module": "metadata", "findings": findings, "skips": skips, "summary": summary}


# ---------------------------------------------------------------- 记录构造
def _records(result: Mapping[str, Any], catalog: Catalogue) -> List[Record]:
    records: List[Record] = []
    strict_source = bool((result.get("summary") or {}).get("strict_source"))
    for f in core.sort_findings(result.get("findings") or []):
        rule, fallback_verdict = _rule_of(f)
        verdict = fallback_verdict
        if any(f["code"] == code for code, _spec in spec.NAME_CODES.values()):
            rule, verdict = _NAME_RULE, WARN
        if f["code"] in _META_RULE:
            rule, verdict = _META_RULE[f["code"]]
        if f["code"] == spec.CODE_MISSING:
            # MISSING_IN_SOURCE 默认 warn；strict_source → error（§六.2 级别随开关变）
            verdict = ERROR if strict_source else WARN
        records.append(Record(
            rule_id=rule,
            verdict=verdict,
            message=f["message"],
            basis=catalog.basis_ref(rule),
            path="%s:%s" % (f["module"], f["primary_key"]),
            evidence={"module": f["module"], "code": f["code"], "severity": f["severity"],
                      "spec_ref": f.get("spec_ref", ""), **(f.get("evidence") or {})},
        ))
    for s in result.get("skips") or []:
        rule = _SKIP_RULE.get((s["module"], s["reason"]), _SKIP_RULE_FALLBACK)
        records.append(Record(
            rule_id=rule,
            verdict=INFO,
            message="SKIPPED(%s): %s" % (s["reason"], s.get("detail", "")),
            basis=catalog.basis_ref(rule),
            path="%s:%s" % (s["module"], s["reason"]),
            evidence=dict(s)))
    return records


def _rule_of(f: Mapping[str, Any]) -> Any:
    got = _SEVERITY_RULE.get((f["module"], f["code"]))
    if got is not None:
        return got
    if f["severity"] == "error":
        return "sa-generic-error", ERROR
    if f["severity"] == "warn":
        return "sa-generic-warn", WARN
    return "sa-generic-note", INFO


def _summary_record(mode: str, result: Mapping[str, Any], records: List[Record],
                    basis: Basis) -> Record:
    errors = sum(1 for r in records if r.verdict == ERROR)
    warns = sum(1 for r in records if r.verdict == WARN)
    infos = sum(1 for r in records if r.verdict == INFO)
    return Record(
        rule_id="sa-summary",
        verdict=INFO,
        message="mode=%s：error=%d warn=%d info=%d" % (mode, errors, warns, infos),
        basis=basis.ref("sa-summary"),
        path="summary",
        evidence={"mode": mode, "error": errors, "warn": warns, "info": infos,
                  "summary": result.get("summary") or {}})
