"""器官 ``media-trace``：MP4 时间轴语义审计账本（迁自 target-map ② 行，Go 源）。

旧仓 ``mediatrace`` 审计一个 MP4 内部多条时间轴口径是否互相自洽。本器官接收输入层
解析好的**事实**（``subject.facts``），照搬五个模块的判定：

* M1 结构：盒子尺寸/越界/截断、重复 moov/mdat、stco 越界、ftyp 品牌；
* M2 时长：mvhd/tkhd/mdhd/elst 互比（1 tick 容差）、elst 速率/次序/空 edit、首帧 PTS；
* M3 时间戳：stts 零时长/位宽/回退、tfdt 回退、极小时基、VFR；
* M4 偏移：priming 声明/匹配、起点裁剪、roll distance、无 edts 的非零起点；
* M5 显示：矩阵正交性、旋转宽高、SAR/DAR、colr 多实例、HDR 元数据。

**没有搬**：ISO BMFF 盒子解析、字节读取、真实文件 I/O、报告排版、CLI。
**等级与阻断分离**：finding 带 ``fail``/``gray`` 三态证据，判决不高于 warn；
唯一 error 是 ``mt-gate``（fail>=1 或 gray>=1）。旧仓 1/2 都映射为 1（已登记口径差）。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import judge, spec


def _emit(records, basis, rule_id, verdict, message, path, evidence=None):
    records.append(
        Record(
            rule_id=rule_id,
            verdict=verdict,
            message=message,
            basis=basis.ref(rule_id),
            path=path,
            evidence=evidence or {},
        )
    )


def _finding_verdict(status: str) -> str:
    return INFO if status == "info" else WARN


def _finding_records(records, basis, findings):
    for index, item in enumerate(findings):
        _emit(
            records,
            basis,
            item["rule_id"],
            _finding_verdict(item["status"]),
            "%s（%s/%s）：%s" % (item["code"], item["status"], item["module"], item["message"]),
            "findings[%d]" % index,
            {
                "code": item["code"],
                "status": item["status"],
                "module": item["module"],
                "values": item["values"],
                "delta": item["delta"],
                "offset": item["offset"],
                "path": item["path"],
            },
        )


def _summary(records, basis, findings):
    fails = sum(1 for item in findings if item["status"] == spec.STATUS_FAIL)
    grays = sum(1 for item in findings if item["status"] == spec.STATUS_GRAY)
    exit_code = 1 if fails else (2 if grays else 0)
    verdict = "fail" if fails else ("inconclusive" if grays else "pass")
    _emit(
        records,
        basis,
        spec.RULE_SUMMARY,
        INFO,
        "fail=%d gray=%d → %s（旧仓退出码 %d）" % (fails, grays, verdict, exit_code),
        "summary",
        {"fail": fails, "gray": grays, "total": len(findings), "verdict": verdict, "source_exit_code": exit_code},
    )
    return fails, grays


def _gate(records, basis, fails, grays):
    if not fails and not grays:
        return
    source_exit = 1 if fails else 2
    _emit(
        records,
        basis,
        spec.RULE_GATE,
        ERROR,
        "阻断：fail=%d gray=%d（旧仓退出码 %d 映射为 1）" % (fails, grays, source_exit),
        "gate",
        {"fail": fails, "gray": grays, "source_exit_code": source_exit},
    )


def _facts(subject):
    facts = subject.get("facts")
    if not isinstance(facts, dict):
        raise ValueError("subject.facts 必须是对象")
    return facts


def _modules(subject):
    modules = subject.get("modules")
    if modules is None:
        return list(spec.MODULES)
    if not isinstance(modules, list) or not all(item in spec.MODULES for item in modules):
        raise ValueError("subject.modules 必须是 M1..M5 的子集")
    return modules


def evaluate(subject, basis):
    mode = subject.get("mode", "audit")
    if mode != "audit":
        raise ValueError("subject.mode 必须是 audit（收到 %r）" % (mode,))
    facts = _facts(subject)
    findings = judge.audit(facts, _modules(subject))
    records = []
    _finding_records(records, basis, findings)
    fails, grays = _summary(records, basis, findings)
    _gate(records, basis, fails, grays)
    return records