"""器官 ``barcode-preflight``：条码印前参数 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``bpreflight`` 从生成参数直接判「这个条码印出来会不会扫不出」。四个模式：

* ``check`` —— 数据层（GS1 元素）+ 符号层（字符集/长度/编码计划/容量/校验位）+
  印刷层（静区/放大率/DPI/条高/颜色）+ 阈值三态 + ``fail_on`` 门禁；
* ``gs1`` —— 只跑数据层（元素解析 + 四个语义解释器）；
* ``symbol`` —— 只跑符号可行性；
* ``oracle`` —— 回读对照三态（不参与 verdict）。

**等级与阻断是两件事**：旧仓 ``check`` 的默认 ``--fail-on none`` 恒 rc 0，阻断只发生在
门禁上。finding 记录带 ``severity`` 证据但判决不高于 ``warn``；唯一 ``error`` 是
``bp-gate``。旧仓用 exit 2 区分「error 跨过门」，byteproof 只有 0/1——2→1 已登记为口径差。

**没有搬**：读 spec 文件与扩展名检查、JSON/Markdown 排版与固定落点写盘、``--with-timestamp``、
GS1 官方字典文件读取与 digest、GCP/GEPIR 查询、``keytool``/外部解码引擎探测、
图像采样与渲染。逐条处置见 ``docs/barcode-preflight.md`` §6。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import book as book_mod
from . import checks, gs1, oracle, spec, symbol
from .book import as_decimal, fixed


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
    """finding 判决：error/warn -> warn，info -> info（severity 保留在证据里）。"""
    return INFO if severity == "info" else WARN


def _finding_records(records, basis, findings):
    for index, finding in enumerate(findings):
        rule_id = finding["rule_id"]
        _emit(
            records,
            basis,
            rule_id,
            _finding_verdict(finding["severity"]),
            "%s（severity=%s）：%s" % (finding["id"], finding["severity"], finding["observed"]),
            "findings[%d]" % index,
            {
                "id": finding["id"],
                "severity": finding["severity"],
                "observed": finding["observed"],
                "target": finding["target"],
                "threshold_status": finding.get("threshold_status"),
                "module": finding.get("module"),
                "fix": finding.get("fix"),
                "evidence": finding.get("evidence", {}),
            },
        )


def _worst(findings) -> str:
    worst = "ok"
    for finding in findings:
        severity = finding["severity"]
        if spec.SEVERITY_ORDER[severity] > spec.SEVERITY_ORDER[worst]:
            worst = severity
    return worst


def _crossed(fail_on: str, worst: str) -> bool:
    if fail_on not in spec.FAIL_ON_CHOICES:
        raise ValueError("subject.fail_on 非法：%r（允许 none/warn/error）" % (fail_on,))
    if fail_on == "none":
        return False
    if fail_on == "warn":
        return spec.SEVERITY_ORDER[worst] >= spec.SEVERITY_ORDER["warn"]
    return spec.SEVERITY_ORDER[worst] >= spec.SEVERITY_ORDER["error"]


def _summary(records, basis, findings, skipped, extra=None):
    counts = {"ok": 0, "info": 0, "warn": 0, "error": 0}
    for finding in findings:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
    evidence = {
        "findings": len(findings),
        "by_severity": counts,
        "skipped": list(skipped),
        "worst_severity": _worst(findings),
        "verdict": _verdict(_worst(findings)),
    }
    if extra:
        evidence.update(extra)
    _emit(
        records,
        basis,
        spec.RULE_SUMMARY,
        INFO,
        "合计 %d 条 finding（error=%d warn=%d info=%d），verdict=%s"
        % (len(findings), counts["error"], counts["warn"], counts["info"], evidence["verdict"]),
        "summary",
        evidence,
    )


def _verdict(worst: str) -> str:
    if worst == "error":
        return spec.VERDICT_FAIL
    if worst == "warn":
        return spec.VERDICT_WARN
    return spec.VERDICT_PASS


def _gate(records, basis, findings, fail_on):
    worst = _worst(findings)
    if not _crossed(fail_on, worst):
        return
    _emit(
        records,
        basis,
        spec.RULE_GATE,
        ERROR,
        "达到 fail_on=%s 门禁（worst=%s）；旧仓退出码 %d 在本产品映射为 1"
        % (fail_on, worst, 2 if worst == "error" else 1),
        "gate",
        {
            "fail_on": fail_on,
            "worst_severity": worst,
            "source_exit_code": 2 if worst == "error" else 1,
        },
    )


# ================================================================== 阈值/输入
def _require_book(subject):
    return book_mod.Book(subject.get("thresholds"))


def _require_dict(subject):
    dictionary = subject.get("dictionary")
    if not isinstance(dictionary, dict):
        raise ValueError("subject.dictionary 必须是对象（AI -> 条目）")
    return dictionary


def _century(subject):
    value = subject.get("century_resolution") or {
        "reference_year_yy": 21,
        "century_window": 50,
        "centuries": {"high": 19, "mid": 20, "low": 21},
    }
    if not isinstance(value, dict):
        raise ValueError("subject.century_resolution 必须是对象")
    return value


def _dec(raw, field):
    return as_decimal(raw, field)


def _quiet_zone(raw):
    if isinstance(raw, dict):
        return {side: _dec(raw.get(side, 0), "quiet_zone_mm." + side) for side in spec.QUIET_ZONE_SIDES}
    value = _dec(raw, "quiet_zone_mm")
    return {side: value for side in spec.QUIET_ZONE_SIDES}


def _incomplete(missing):
    return checks.engineering(
        spec.RULE_PRINT_INCOMPLETE,
        "error",
        "missing: " + ", ".join(missing),
        "print:" + "|".join(missing),
        "data/README.md §8.9 G3",
        "输入参数不足以判定 -> 一条 input_incomplete，不得用默认值静默补齐",
        {
            "kind": "supply_missing_input",
            "to": " or ".join(missing),
            "unit": "field",
            "rationale": "没有输入就没有判定",
        },
        source_id="input_incomplete",
    )


def _print_layer(subject):
    """返回 ``(findings, skipped, judged)``。缺几何 -> 一条 incomplete，其余几何不判。"""
    if not any(subject.get(name) is not None for name in spec.PRINT_INPUT_FIELDS):
        return [], [], False
    findings = []
    skipped = []
    bar = subject.get("bar_color")
    space = subject.get("space_color")
    illumination = subject.get("illumination")
    if bar is not None and space is not None and illumination is not None:
        findings.extend(checks.color(_require_book(subject), bar, space, illumination))

    missing = [name for name in spec.PRINT_FIELDS if subject.get(name) is None]
    if missing:
        findings.append(_incomplete(missing))
        return findings, skipped, False
    symbol_name = subject.get("symbol")
    profiles = subject.get("profiles")
    if symbol_name is None:
        skipped.append("symbol_not_specified")
        return findings, skipped, False
    if not isinstance(profiles, dict) or symbol_name not in profiles:
        skipped.append("symbol_unsupported:" + str(symbol_name))
        return findings, skipped, False
    try:
        x_dimension = _dec(subject.get("x_dimension_mm"), "x_dimension_mm")
        dpi = _dec(subject.get("target_dpi"), "target_dpi")
        margins = _quiet_zone(subject.get("quiet_zone_mm"))
        height = _dec(subject.get("bar_height_mm"), "bar_height_mm") if subject.get("bar_height_mm") is not None else None
    except ValueError:
        findings.append(_incomplete(["usable value for the print parameters"]))
        return findings, skipped, False
    if x_dimension <= 0:
        findings.append(
            checks.engineering(
                spec.RULE_PRINT_INCOMPLETE,
                "error",
                "x_dimension_mm = %s" % fixed(x_dimension),
                "x_dimension",
                "data/README.md §8.3",
                "<= 0 -> error: x_dimension_missing；其余比值判据全部无法成立",
                {"kind": "set_x_dimension", "to": "> 0.000", "unit": "mm"},
                source_id="x_dimension_missing",
            )
        )
        return findings, skipped, False
    book = _require_book(subject)
    strict = bool(subject.get("strict_thresholds", False))
    findings.extend(checks.quiet_zone(book, symbol_name, margins, x_dimension, strict))
    findings.extend(checks.magnification(book, x_dimension, strict))
    findings.extend(checks.raster(book, x_dimension, dpi, strict))
    if height is not None:
        findings.extend(checks.bar_height(book, symbol_name, height, x_dimension, strict))
    return findings, skipped, True


# ================================================================== check
def _check(subject, basis):
    findings = []
    skipped = []
    if subject.get("gs1_element_string") is not None:
        elements, issues = gs1.parse_elements(subject["gs1_element_string"], _require_dict(subject))
        findings.extend(gs1.issue_findings(issues))
        validated, skipped = gs1.validate_elements(elements, _require_dict(subject), _century(subject))
        findings.extend(validated)
    elif subject.get("identifier") is not None:
        identifier = str(subject["identifier"])
        if not identifier.isdigit():
            findings.append(
                gs1._element_finding(
                    spec.RULE_GS1_CHARSET,
                    "error",
                    "identifier 必须是数字串",
                    "gs1.identifier",
                    {"identifier": identifier},
                )
            )
    else:
        skipped.append("data_not_provided")

    payload = subject.get("identifier")
    if subject.get("gs1_element_string") is not None:
        parsed, _issues = gs1.parse_elements(subject["gs1_element_string"], _require_dict(subject))
        payload = next((element["value"] for element in parsed if element["ai"] == "01"), subject.get("identifier"))

    symbol_name = subject.get("symbol")
    if symbol_name is not None:
        profiles = subject.get("profiles")
        symbol_findings, symbol_skipped, _evidence = symbol.assess(
            profiles if isinstance(profiles, dict) else {},
            symbol_name,
            value=payload,
            identifier=subject.get("identifier"),
            strict=bool(subject.get("strict_thresholds", False)),
        )
        findings.extend(symbol_findings)
        skipped.extend(symbol_skipped)
    else:
        skipped.append("symbol_not_specified")

    print_findings, print_skipped, judged = _print_layer(subject)
    findings.extend(print_findings)
    skipped.extend(print_skipped)

    for finding in list(findings):
        if finding.get("threshold_status") is None:
            finding["threshold_status"] = spec.THRESHOLD_NOT_APPLICABLE

    records = []
    _finding_records(records, basis, findings)
    _summary(records, basis, findings, skipped, {"print_judged": judged})
    _gate(records, basis, findings, subject.get("fail_on") or "none")
    return records


# ================================================================== gs1
def _gs1(subject, basis):
    dictionary = _require_dict(subject)
    elements, issues = gs1.parse_elements(subject.get("gs1_element_string"), dictionary)
    findings = gs1.issue_findings(issues)
    validated, skipped = gs1.validate_elements(elements, dictionary, _century(subject))
    findings.extend(validated)
    for finding in findings:
        finding["threshold_status"] = spec.THRESHOLD_NOT_APPLICABLE
    records = []
    _finding_records(records, basis, findings)
    _summary(records, basis, findings, skipped, {"elements": len(elements)})
    return records


# ================================================================== symbol
def _symbol_mode(subject, basis):
    profiles = subject.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("mode=symbol 需要 subject.profiles（对象）")
    symbol_name = subject.get("symbol")
    if not isinstance(symbol_name, str) or not symbol_name:
        raise ValueError("mode=symbol 需要 subject.symbol")
    findings, skipped, evidence = symbol.assess(
        profiles,
        symbol_name,
        value=subject.get("value", subject.get("identifier")),
        identifier=subject.get("identifier"),
        strict=bool(subject.get("strict_thresholds", False)),
    )
    records = []
    _finding_records(records, basis, findings)
    _summary(records, basis, findings, skipped, {"symbol": evidence})
    return records


# ================================================================== oracle
def _oracle(subject, basis):
    verdict = subject.get("m3_verdict")
    if verdict is None and isinstance(subject.get("findings"), list):
        verdict = oracle.m3_verdict(subject["findings"])
    if verdict is None:
        raise ValueError("mode=oracle 需要 subject.m3_verdict（或 findings[]）")
    if "decoded" not in subject:
        raise ValueError("mode=oracle 需要 subject.decoded（布尔）")
    decoded = bool(subject["decoded"])
    finding_ids = subject.get("finding_ids") or []
    agreement, known, bugs = oracle.classify(verdict, decoded, finding_ids)
    records = []
    if agreement == oracle.M3_LAXER:
        _emit(
            records,
            basis,
            spec.RULE_ORACLE_AGREEMENT,
            WARN,
            "oracle 解不出来而 M3 判干净：bug 通道，不许记入 known-disagreements",
            "oracle",
            {"agreement": agreement, "bugs": bugs, "m3_verdict": verdict, "decoded": decoded},
        )
    else:
        _emit(
            records,
            basis,
            spec.RULE_ORACLE_AGREEMENT,
            INFO,
            "oracle 三态：%s" % agreement,
            "oracle",
            {
                "agreement": agreement,
                "known_disagreements": known,
                "m3_verdict": verdict,
                "decoded": decoded,
                "finding_ids": sorted(finding_ids),
            },
        )
    return records


# ================================================================== 入口
def evaluate(subject, basis):
    mode = subject.get("mode")
    if mode not in spec.MODES:
        raise ValueError(
            "subject.mode 非法：%r（允许 %s）" % (mode, " / ".join(spec.MODES))
        )
    if mode == "check":
        return _check(subject, basis)
    if mode == "gs1":
        return _gs1(subject, basis)
    if mode == "symbol":
        return _symbol_mode(subject, basis)
    return _oracle(subject, basis)