"""器官 ``cert-ledger``：证书/私钥台账 -> 缺陷账本（迁自 target-map ② 行）。

旧仓 ``certledger`` 的四个判定面收敛成四个 ``subject.mode``：

* ``inventory`` —— 已解码条目事实 -> 去重/配对/排序后的台账（信息记录，含完整证据）；
* ``hygiene``   —— 台账 + ``as_of`` + 策略 -> 九族 findings；
* ``report``    —— findings + 到期表 + 基线差异 + ``fail_on`` 门禁（唯一的阻断结论）；
* ``containers``—— 容器信号（truststore 含私钥 / 空口令可开 / 打不开）。

**等级与阻断是两件事**：旧仓 ``hygiene`` 命令从不下阻断结论（恒 rc 0），阻断只发生在
``report`` 的 ``--fail-on`` 阈值上。本器官照搬：finding 记录带 ``severity`` 证据但判决
不高于 ``warn``；只有 ``cl-threshold-reached`` 是 ``error``（阻断），其出现与否完全由
``fail_on`` 与 findings 的等级决定。这样两种命令的退出码都逐例对齐。

**没有搬**：PEM/DER/PKCS#12/JKS 解析、``cryptography``、``keytool`` 子进程、系统信任库
后端、目录遍历、密码环境变量、报告 JSON/Markdown 排版与写盘、路径脱敏。逐条处置见
``docs/cert-ledger.md`` §6。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import diff, hygiene, ledger as ledger_mod, spec
from .timebase import AsOf, parse_as_of


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
    """finding 的判决：``INFO`` 保持 info，``ERROR``/``WARN`` 记 warn（severity 仍在证据里）。"""
    return INFO if severity == "INFO" else WARN


def _finding_records(records, basis, findings):
    for index, finding in enumerate(findings):
        _emit(
            records,
            basis,
            finding["rule_id"],
            _finding_verdict(finding["severity"]),
            "%s（severity=%s）%s"
            % (
                finding["code"],
                finding["severity"],
                "：%s" % finding["subject"] if finding["subject"] else "",
            ),
            "findings[%d]" % index,
            {
                "code": finding["code"],
                "severity": finding["severity"],
                "subject": finding["subject"],
                "fingerprint": finding["fingerprint"],
                "block": finding["block"],
                "evidence": finding["evidence"],
            },
        )


def _suppressed_record(records, basis, suppressed):
    if not suppressed:
        return
    _emit(
        records,
        basis,
        spec.RULE_POLICY_SUPPRESSED,
        INFO,
        "策略把 %d 类规则设为 off；被抑制的结论仍计数（静默不等于干净）" % len(suppressed),
        "policy",
        {"suppressed_by_code": dict(suppressed), "suppressed": sum(suppressed.values())},
    )


def _summary_record(records, basis, summary, containers=0):
    _emit(
        records,
        basis,
        spec.RULE_LEDGER_SUMMARY,
        INFO,
        "台账摘要：%d 证书 / %d 私钥 / %d 容器 / %d 诊断"
        % (
            summary["records"]["certs"],
            summary["records"]["keys"],
            containers,
            summary["records"]["diagnostics"],
        ),
        "ledger",
        {"summary": summary, "containers": containers},
    )


def _require_as_of(subject):
    if "as_of" not in subject:
        raise ValueError("mode=%s 需要 subject.as_of（没有「当前时间」缺省值）" % (subject.get("mode"),))
    return parse_as_of(subject.get("as_of"))


def _policy(subject):
    return hygiene.resolve_policy(subject.get("policy"))


def _ledger(subject):
    value = subject.get("ledger")
    if value is None:
        raise ValueError("mode=%s 需要 subject.ledger（台账对象）" % (subject.get("mode"),))
    return ledger_mod.validate_ledger(value)


# ================================================================== inventory
def _inventory(subject, basis):
    entries = subject.get("entries")
    if entries is None:
        raise ValueError("mode=inventory 需要 subject.entries（已解码条目事实数组）")
    built = ledger_mod.build_ledger(entries)
    records = []
    _emit(
        records,
        basis,
        spec.RULE_INVENTORY,
        INFO,
        "台账：%d 证书 / %d 私钥 / %d 容器 / %d 诊断"
        % (
            built["summary"]["certs"],
            built["summary"]["keys"],
            built["summary"]["containers"],
            built["summary"]["diagnostics"],
        ),
        "ledger",
        built,
    )
    return records


# ================================================================== hygiene
def _hygiene(subject, basis):
    ledger = _ledger(subject)
    as_of = _require_as_of(subject)
    policy = _policy(subject)
    result = hygiene.evaluate_findings(ledger, policy, as_of)
    records = []
    _summary_record(records, basis, result["summary"], len(ledger.get("containers") or []))
    _finding_records(records, basis, result["findings"])
    _suppressed_record(records, basis, result["suppressed"])
    return records


# ================================================================== report
def _report(subject, basis):
    ledger = _ledger(subject)
    as_of = _require_as_of(subject)
    policy = _policy(subject)
    result = hygiene.evaluate_findings(ledger, policy, as_of)
    records = []
    _summary_record(records, basis, result["summary"], len(ledger.get("containers") or []))
    _finding_records(records, basis, result["findings"])
    _suppressed_record(records, basis, result["suppressed"])

    rows = hygiene.expiry_rows(result["findings"])
    top = subject.get("top")
    if top is not None:
        if isinstance(top, bool) or not isinstance(top, int) or top < 0:
            raise ValueError("subject.top 必须是 >= 0 的整数")
        shown = rows[:top]
    else:
        shown = rows
    _emit(
        records,
        basis,
        spec.RULE_EXPIRY_TABLE,
        INFO,
        "到期表：%d 条（展示 %d 条，按 not_after 升序）" % (len(rows), len(shown)),
        "expiries",
        {"expiries_total": len(rows), "expiries_shown": len(shown), "rows": shown},
    )

    baseline = subject.get("baseline")
    if baseline is not None:
        difference = diff.diff_against(baseline, diff.certificate_rows(ledger))
        _emit(
            records,
            basis,
            spec.RULE_DIFF,
            INFO,
            "基线差异：新增 %d / 移除 %d / 轮换 %d"
            % (len(difference["added"]), len(difference["removed"]), len(difference["rotated"])),
            "diff",
            difference,
        )

    threshold = subject.get("fail_on") or str(
        hygiene.require(policy, "report.default_fail_on")
    )
    if threshold not in spec.FAIL_ON_VALUES:
        raise ValueError(
            "subject.fail_on 非法：%r（允许 %s）" % (threshold, " / ".join(spec.FAIL_ON_VALUES))
        )
    reached = hygiene.threshold_reached(result["findings"], threshold)
    if reached:
        crossed = [
            finding
            for finding in result["findings"]
            if spec.SEVERITY_ORDER.get(finding["severity"], 99)
            <= spec.SEVERITY_ORDER[threshold]
        ]
        _emit(
            records,
            basis,
            spec.RULE_THRESHOLD_REACHED,
            ERROR,
            "达到报告阈值 %s：%d 条 finding 触发阻断（exit 1）" % (threshold, len(crossed)),
            "gate",
            {
                "fail_on": threshold,
                "crossed": len(crossed),
                "codes": sorted({finding["code"] for finding in crossed}),
            },
        )
    return records


# ================================================================== containers
def _containers(subject, basis):
    containers = subject.get("containers")
    if not isinstance(containers, list) or not all(isinstance(item, dict) for item in containers):
        raise ValueError("mode=containers 需要 subject.containers（对象数组）")
    diagnostics = subject.get("diagnostics", [])
    if not isinstance(diagnostics, list) or not all(isinstance(item, dict) for item in diagnostics):
        raise ValueError("subject.diagnostics 必须是对象数组")
    policy = _policy(subject)
    result = hygiene.evaluate_findings(
        {"containers": containers, "diagnostics": diagnostics}, policy, AsOf(raw="", seconds=0)
    )
    records = []
    _summary_record(
        records,
        basis,
        {
            "records": {"certs": 0, "keys": 0, "diagnostics": len(diagnostics)},
            "findings": result["summary"]["findings"],
            "by_severity": result["summary"]["by_severity"],
            "suppressed": result["summary"]["suppressed"],
        },
        len(containers),
    )
    _finding_records(records, basis, result["findings"])
    _suppressed_record(records, basis, result["suppressed"])
    return records


# ================================================================== 入口
def evaluate(subject, basis):
    mode = subject.get("mode")
    if mode not in spec.MODES:
        raise ValueError(
            "subject.mode 非法：%r（允许 %s）" % (mode, " / ".join(spec.MODES))
        )
    if mode == "inventory":
        return _inventory(subject, basis)
    if mode == "hygiene":
        return _hygiene(subject, basis)
    if mode == "report":
        return _report(subject, basis)
    return _containers(subject, basis)