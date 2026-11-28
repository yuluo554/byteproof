"""编排层：``evaluate(subject, basis) -> Iterable[Record]``。

十三个模式由两个判定核分工（见 ``spec.REF_MODES`` / ``spec.DOC_MODES``）：
``core_ref.evaluate(mode, subject)`` 与 ``core_doc.evaluate(mode, subject)`` 各返回
``[{rule_id, verdict, message, path, evidence}]``；本层只做三件事：

1. 校验 mode / subject（输入不合法 → ``ValueError`` → 退出码 2）；
2. 校验 ``rule_id`` 在白名单内（未登记 → ``ValueError``，不许临时编规则）；
3. 挂 ``basis.ref`` 成 ``Record``，并追加一条 ``taw-summary``（计数 + 本模式关键量）。

判定核不读文件/环境/时钟（旧仓的 docx / SQLite / CLI 面留输入层与宿主）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, Record

from . import core_doc, core_ref, spec
from .catalogue import Catalogue


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    if not isinstance(subject, Mapping):
        raise ValueError("输入必须是 JSON 对象")
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if mode not in spec.MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(spec.MODES), mode))
    catalogue = Catalogue(basis)
    if mode in spec.REF_MODES:
        raw = core_ref.evaluate(mode, dict(subject))
    else:
        raw = core_doc.evaluate(mode, dict(subject))
    if not isinstance(raw, list):
        raise ValueError("判定核必须返回数组（mode=%s）" % (mode,))

    records: List[Record] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("判定核返回项必须是对象（mode=%s）" % (mode,))
        rule_id = item.get("rule_id")
        if rule_id not in spec.ALL_RULES:
            raise ValueError("未登记的规则：%r（mode=%s）" % (rule_id, mode))
        verdict = item.get("verdict")
        if verdict not in spec.VERDICTS:
            raise ValueError("非法结论：%r（rule=%s）" % (verdict, rule_id))
        path = str(item.get("path") or "report")
        records.append(Record(
            rule_id=rule_id,
            verdict=verdict,
            message=str(item.get("message") or ""),
            basis=catalogue.basis_ref(rule_id),
            path=path,
            evidence=dict(item.get("evidence") or {}),
        ))
    records = _dedupe(records)
    counts = {verdict: 0 for verdict in spec.VERDICTS}
    for record in records:
        counts[record.verdict] += 1
    records.append(Record(
        rule_id=spec.SUMMARY_RULE,
        verdict=INFO,
        message="论文审计汇总（%s 模式）：%d 条记录，阻断 %d 条"
        % (mode, len(records), counts[ERROR]),
        basis=catalogue.basis_ref(spec.SUMMARY_RULE),
        path="report",
        evidence={
            "mode": mode,
            "total": len(records),
            "by_verdict": counts,
            "by_rule": _by_rule(records),
        },
    ))
    return records


def _by_rule(records: Iterable[Record]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for record in records:
        counts[record.rule_id] = counts.get(record.rule_id, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


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
            out.append(Record(rule_id=record.rule_id, verdict=record.verdict,
                              message=record.message, basis=record.basis,
                              path="%s#%d" % (record.path, count),
                              evidence=record.evidence))
    return out