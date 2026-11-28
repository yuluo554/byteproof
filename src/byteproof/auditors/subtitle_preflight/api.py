"""编排层：``evaluate(subject, basis) -> Iterable[Record]``。

六种模式（``spec.MODES``）：``timing`` / ``readability`` / ``hygiene`` / ``decode`` /
``fix`` / ``all``。旧仓 ``pipeline.runOne`` 的判定面由 ``all`` 一次跑完：时序 + 可读性 +
卫生（+ 给了 ``text`` 就跑修复、给了 ``bytes_b64`` 就跑编码嗅探）。

**输入层契约**（D1+D18 排除 ``parse`` / ``report``）：cue 序列由输入层解析后摊平传入
（``startMs`` / ``endMs`` / ``textLines`` / ``sourceLine`` / ``timeLine`` /
``textLineNumbers`` / ``format`` / ``index``），器官不解析字幕文本、不渲染报告。
编码面例外需要原始字节，经 ``bytes_b64`` 传入（器官只做**决策**，不做文件 IO）。

账本映射（细则见 ``docs/subtitle-preflight.md`` §2）：

| 旧形态 | 账本 |
|---|---|
| finding ``severity=error`` | verdict **error**（阻断） |
| finding ``severity=warn`` | verdict warn |
| ``skipped[]`` | ``sp-skipped`` info（**不静默**） |
| ``fixes[]`` | ``fix.*`` info（动作/前/后进 evidence） |
| 报告 ``summary`` | ``sp-summary`` info（evidence 承载计数） |

退出码：旧仓无 CLI（页面 + 门），门 0/1/2 语义映射到账本 0/1/2（0 无阻断 / 1 有 error /
2 输入不合法；缺 basis 规则 → 3 契约违约）。
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from byteproof.core.basis import Basis
from byteproof.core.ledger import INFO, Record

from . import core, spec
from .catalogue import Catalogue


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if mode not in spec.MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(spec.MODES), mode))
    catalogue = Catalogue(basis)
    th = spec.THRESHOLDS

    records: List[Record] = []
    skipped: List[Mapping[str, Any]] = []
    summary: Dict[str, Any] = {"mode": mode}

    if mode == "decode":
        decoded = _decode(subject)
        records.extend(_decode_records(decoded, catalogue))
        summary["decode"] = _decode_summary(decoded)
    elif mode == "fix":
        cues, text = _require_cues(subject), _require_text(subject)
        fixed = core.apply_fix(text, cues, th, subject.get("eol") or (subject.get("options") or {}).get("eol"))
        records.extend(_fix_records(fixed, catalogue))
        summary["fixes"] = len(fixed["fixes"])
        summary["cues"] = len(cues)
        if fixed["fixes"]:
            skipped.append({"kind": "fix", "reason": "applied"})
        else:
            skipped.append({"kind": "fix", "reason": "no_fixable_finding"})
    elif mode == "timing":
        cues = _require_cues(subject)
        result = core.timing_findings(cues, th, subject.get("declared"), subject.get("diagnostics") or ())
        records.extend(_finding_records(result["findings"], catalogue))
        skipped.extend(result["skipped"])
        summary.update(_timing_summary(result, cues))
    elif mode == "readability":
        cues = _require_cues(subject)
        result = core.readability_findings(cues, th)
        records.extend(_finding_records(result["findings"], catalogue))
        skipped.extend(result["skipped"])
        summary["cues"] = len(cues)
        summary["implemented"] = result["implemented"]
    elif mode == "hygiene":
        cues = _require_cues(subject)
        result = core.hygiene_findings(cues, th)
        records.extend(_finding_records(result["findings"], catalogue))
        skipped.extend(result["skipped"])
        summary["cues"] = len(cues)
        summary["implemented"] = result["implemented"]
        summary["whitelist"] = result["whitelist"]
    else:  # all
        cues = _require_cues(subject)
        result = core.run_all(cues, th, subject.get("declared"), subject.get("diagnostics") or ())
        records.extend(_finding_records(result["findings"], catalogue))
        skipped.extend(result["skipped"])
        summary.update(_timing_summary(result, cues))
        summary["implemented"] = result["implemented"]
        summary["whitelist"] = result["whitelist"]
        if subject.get("bytes_b64") is not None:
            decoded = _decode(subject)
            records.extend(_decode_records(decoded, catalogue))
            summary["decode"] = _decode_summary(decoded)
        if subject.get("text") is not None:
            fixed = core.apply_fix(
                subject["text"], cues, th,
                subject.get("eol") or (subject.get("options") or {}).get("eol"),
            )
            records.extend(_fix_records(fixed, catalogue))
            summary["fixes"] = len(fixed["fixes"])
            skipped.append({
                "kind": "fix",
                "reason": "applied" if fixed["fixes"] else "no_fixable_finding",
            })

    for item in skipped:
        records.append(_skipped_record(item, catalogue))

    records = _dedupe(records)
    summary["blocking"] = sum(1 for record in records if record.verdict == "error")
    summary["total"] = len(records)
    summary["by_severity"] = _count_by(lambda record: record.verdict, records)
    summary["by_rule"] = _count_by(lambda record: record.rule_id, records)
    records.append(Record(
        rule_id=spec.SUMMARY_RULE,
        verdict=INFO,
        message="体检汇总（%s 模式）：%d 条记录，阻断 %d 条"
        % (mode, summary["total"], summary["blocking"]),
        basis=catalogue.basis_ref(spec.SUMMARY_RULE),
        path="report",
        evidence=summary,
    ))
    return records


# ---------------------------------------------------------------- subject 读取
def _require_cues(subject: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    cues = subject.get("cues")
    if cues is None:
        raise ValueError("输入缺少必填字段：cues（输入层摊平的 cue 序列）")
    if not isinstance(cues, list):
        raise ValueError("cues 必须是数组")
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise ValueError("cues[%d] 必须是对象" % index)
        for name in ("startMs", "endMs"):
            if name not in cue:
                raise ValueError("cues[%d] 缺少 %s" % (index, name))
            if not isinstance(cue[name], (int, float)):
                raise ValueError("cues[%d].%s 必须是数字" % (index, name))
        if "textLines" in cue and not isinstance(cue["textLines"], list):
            raise ValueError("cues[%d].textLines 必须是数组" % index)
    return cues


def _require_text(subject: Mapping[str, Any]) -> str:
    if "text" not in subject:
        raise ValueError("输入缺少必填字段：text（已归一化换行的原文）")
    if not isinstance(subject["text"], str):
        raise ValueError("text 必须是字符串")
    return subject["text"]


def _decode(subject: Mapping[str, Any]) -> Dict[str, Any]:
    raw = subject.get("bytes_b64")
    if raw is None:
        raise ValueError("输入缺少必填字段：bytes_b64（原始字节的 base64）")
    if not isinstance(raw, str):
        raise ValueError("bytes_b64 必须是 base64 字符串")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("bytes_b64 不是合法 base64：%s" % (exc,))
    return core.decode_bytes(data)


# ---------------------------------------------------------------- 记录构造
def _finding_records(
    findings: Sequence[Mapping[str, Any]], catalogue: Catalogue
) -> List[Record]:
    records: List[Record] = []
    for finding in findings:
        rule_id = finding["ruleId"]
        if rule_id not in spec.SEVERITY:
            raise ValueError("未登记的规则：%s" % (rule_id,))
        if finding.get("_cueBased"):
            path = "cue:%d" % (finding.get("_cue") or 0,)
        else:
            path = "line:%d" % (finding.get("line", 0),)
        evidence = {
            "line": finding.get("line", 0),
            "field": finding.get("field", ""),
            "expected": finding.get("expected", ""),
            "actual": finding.get("actual", ""),
            "severity": finding.get("severity", ""),
            "time_line": finding.get("_timeLine", 0),
        }
        records.append(Record(
            rule_id=rule_id,
            verdict=spec.SEVERITY[rule_id],
            message=finding["message"],
            basis=catalogue.basis_ref(rule_id),
            path=path,
            evidence=evidence,
        ))
    return records


def _decode_records(
    decoded: Mapping[str, Any], catalogue: Catalogue
) -> List[Record]:
    records: List[Record] = []
    for diagnostic in decoded.get("diagnostics", []):
        code = diagnostic.get("code", "")
        if code not in spec.DECODE_RULES:
            raise ValueError("未登记的编码诊断：%s" % (code,))
        records.append(Record(
            rule_id=code,
            verdict=spec.SEVERITY[code],
            message=diagnostic.get("detail", ""),
            basis=catalogue.basis_ref(code),
            path="bytes",
            evidence={
                "encoding": decoded.get("encoding", ""),
                "bom": decoded.get("bom"),
                "fallback": decoded.get("fallback"),
                "lossy": decoded.get("lossy"),
                "eol": decoded.get("eol", ""),
            },
        ))
    return records


def _decode_summary(decoded: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "encoding": decoded.get("encoding", ""),
        "bom": decoded.get("bom"),
        "fallback": decoded.get("fallback"),
        "lossy": decoded.get("lossy"),
        "eol": decoded.get("eol", ""),
        "text_sha256_len": len(decoded.get("text", "")),
    }


def _fix_records(fixed: Mapping[str, Any], catalogue: Catalogue) -> List[Record]:
    records: List[Record] = []
    for fix in fixed.get("fixes", []):
        rule_id = fix.get("ruleId", "")
        if rule_id not in spec.FIX_RULES:
            raise ValueError("未登记的修复规则：%s" % (rule_id,))
        records.append(Record(
            rule_id=rule_id,
            verdict=spec.SEVERITY[rule_id],
            message="可逆修复：%s（第 %d 行）" % (fix.get("action", ""), fix.get("line", 0)),
            basis=catalogue.basis_ref(rule_id),
            path="line:%d" % (fix.get("line", 0),),
            evidence={
                "action": fix.get("action", ""),
                "before": fix.get("before", ""),
                "after": fix.get("after", ""),
            },
        ))
    return records


def _skipped_record(item: Mapping[str, Any], catalogue: Catalogue) -> Record:
    reason = item.get("reason", "")
    if reason not in spec.SKIP_REASONS:
        raise ValueError("未登记的 skipped 理由：%s" % (reason,))
    rule_id = item.get("ruleId", item.get("kind", ""))
    return Record(
        rule_id=spec.SKIPPED_RULE,
        verdict=INFO,
        message="未执行：%s（reason=%s）" % (rule_id, reason),
        basis=catalogue.basis_ref(spec.SKIPPED_RULE),
        path="skip:%s:%s" % (rule_id, reason),
        evidence={"rule": rule_id, "reason": reason, "samples": item.get("samples")},
    )


def _timing_summary(result: Mapping[str, Any], cues: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "cues": len(cues),
        "implemented": result.get("implemented"),
        "drift_fit": result.get("driftFit"),
    }
    return summary


def _count_by(key, records: Iterable[Record]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        name = key(record)
        counts[name] = counts.get(name, 0) + 1
    return {name: counts[name] for name in sorted(counts)}


def _dedupe(records: List[Record]) -> List[Record]:
    """同一规则命中同一位置两次时给 id 加 ``#n`` 消歧（账本禁止重复 id）。"""
    seen: Dict[str, int] = {}
    out: List[Record] = []
    for record in records:
        key = record.id
        count = seen.get(key, 0) + 1
        seen[key] = count
        if count == 1:
            out.append(record)
        else:
            out.append(Record(
                rule_id=record.rule_id,
                verdict=record.verdict,
                message=record.message,
                basis=record.basis,
                path="%s#%d" % (record.path, count),
                evidence=record.evidence,
            ))
    return out