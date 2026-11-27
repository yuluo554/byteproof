"""器官 ``image-oracle``：图像呈现预言机 -> 缺陷账本（迁自 target-map ② 行）。

五个模式 = 旧仓五个判决器：

* ``orientation`` —— 8 元方向矩阵、int16u 类型、1..8 范围、有效宽高；
* ``double-rotate`` —— IFD1 未同步 / XMP 冲突 / 大边启发式三条件；
* ``color`` —— ICC 载体与 128B 头、PNG iCCP↔sRGB、色彩 chunk、位深、CMYK、默认假设表；
* ``container`` —— PNG chunk 顺序 / CRC、APNG 序号、帧时长单位、WebP/GIF/JPEG 结构；
* ``consumers`` —— 9×6 消费者矩阵、风险清单、加工前后 chunk diff。

输入是输入层解析好的**事实**（``subject.facts``）：器官不解码像素、不读字节、不读时钟。

**等级与阻断分离**：finding 带旧仓的 ``severity``（info/warning/error/unknown）证据，
判决不高于 warn；唯一 error 是 ``io-gate``。旧仓 0/1/2 → 本产品 0/1/1（旧 1 与旧 2
都映射为 1，已登记为口径差）。``suspicion`` 不参与门禁（旧仓也不含它）。
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


def _finding_verdict(severity: str) -> str:
    return INFO if severity in ("info", "suspicion") else WARN


def _finding_records(records, basis, findings):
    for index, item in enumerate(findings):
        _emit(
            records,
            basis,
            item["rule_id"],
            _finding_verdict(item["severity"]),
            "%s（%s/%s）：%s" % (item["code"], item["severity"], item["confidence"], item["message"]),
            "findings[%d]" % index,
            {
                "code": item["code"],
                "severity": item["severity"],
                "confidence": item["confidence"],
                "module": item["module"],
                "evidence": item["evidence"],
            },
        )


def _worst(findings):
    worst = "info"
    for item in findings:
        if spec.SEVERITY_ORDER[item["severity"]] > spec.SEVERITY_ORDER[worst]:
            worst = item["severity"]
    return worst


def _summary(records, basis, findings, extra=None):
    counts = {}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    worst = _worst(findings)
    evidence = {"findings": len(findings), "by_severity": counts, "worst_severity": worst}
    if extra:
        evidence.update(extra)
    _emit(
        records,
        basis,
        spec.RULE_SUMMARY,
        INFO,
        "合计 %d 条 finding（warning=%d error=%d unknown=%d）"
        % (len(findings), counts.get("warning", 0), counts.get("error", 0), counts.get("unknown", 0)),
        "summary",
        evidence,
    )


def _gate(records, basis, findings):
    worst = _worst(findings)
    if spec.SEVERITY_ORDER[worst] < spec.SEVERITY_ORDER["warning"]:
        return
    source_exit = 2 if worst in ("error", "unknown") else 1
    _emit(
        records,
        basis,
        spec.RULE_GATE,
        ERROR,
        "最严重级别 %s 触发阻断（旧仓退出码 %d 映射为 1）" % (worst, source_exit),
        "gate",
        {"worst_severity": worst, "source_exit_code": source_exit},
    )


def _facts(subject):
    facts = subject.get("facts")
    if not isinstance(facts, dict):
        raise ValueError("subject.facts 必须是对象")
    return facts


def _orientation(subject, basis):
    result = judge.analyze_orientation(_facts(subject))
    records = []
    _finding_records(records, basis, result["findings"])
    _summary(
        records,
        basis,
        result["findings"],
        {
            "primary": result["primary"],
            "effective_width": result["effective_width"],
            "effective_height": result["effective_height"],
            "transform": judge.transform_for(result["primary"]) if result["primary"] else None,
        },
    )
    _gate(records, basis, result["findings"])
    return records


def _double_rotate(subject, basis):
    result = judge.analyze_double_rotate(_facts(subject))
    records = []
    _finding_records(records, basis, result["findings"])
    _summary(records, basis, result["findings"], {"verdicts": result["verdicts"], "primary": result["primary"]})
    _gate(records, basis, result["findings"])
    return records


def _color(subject, basis):
    result = judge.analyze_color(_facts(subject))
    records = []
    _finding_records(records, basis, result["findings"])
    _summary(records, basis, result["findings"], {"icc": result["icc"], "defaults": result["defaults"]})
    _gate(records, basis, result["findings"])
    return records


def _container(subject, basis):
    result = judge.analyze_container(_facts(subject))
    records = []
    _finding_records(records, basis, result["findings"])
    _summary(records, basis, result["findings"], {"kind": result["kind"], "frames": result["frames"]})
    _gate(records, basis, result["findings"])
    return records


def _consumers(subject, basis):
    result = judge.analyze_consumers(_facts(subject))
    records = []
    _finding_records(records, basis, result["findings"])
    _summary(records, basis, result["findings"], {"matrix": result["matrix"], "risks": result["risks"]})
    _gate(records, basis, result["findings"])
    return records


def evaluate(subject, basis):
    mode = subject.get("mode")
    if mode not in spec.MODES:
        raise ValueError(
            "subject.mode 非法：%r（允许 %s）" % (mode, " / ".join(spec.MODES))
        )
    if mode == "orientation":
        return _orientation(subject, basis)
    if mode == "double-rotate":
        return _double_rotate(subject, basis)
    if mode == "color":
        return _color(subject, basis)
    if mode == "container":
        return _container(subject, basis)
    return _consumers(subject, basis)