"""判定层：台账 -> findings（旧仓 ``hygiene`` 的九族规则）。

四条纪律照搬：

1. 每条结论带规则出处（由 ``basis`` 提供，不是由策略文件）；
2. 阈值全部来自策略（``subject.policy`` 覆盖随包默认值），判定函数不写死；
3. **「没看」也是结论**：台账里每条 diagnostic 都变成 finding；
4. **不编事实**：解不出的密钥不判弱、锁住的密钥不判孤儿、不可解析的日期不判过期。

规则块与代码的对应见 ``spec.CODE_RULES``。
"""

from __future__ import annotations

from . import spec
from .timebase import AsOf, add_days, format_utc, parse_stamp

WEAK_KEY_ALGO_RULE = {"rsa": spec.RULE_WEAK_KEY_RSA, "ec": spec.RULE_WEAK_KEY_EC}


def _merge(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def resolve_policy(overrides=None) -> dict:
    """随包默认策略 + ``subject.policy`` 深合并；等级非法 -> ``ValueError``（退出码 2）。"""
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, dict):
        raise ValueError("subject.policy 必须是对象")
    policy = _merge(spec.DEFAULT_POLICY, overrides)
    for block in spec.RULE_BLOCKS:
        value = require(policy, "%s.level" % block)
        if value not in spec.LEVELS:
            raise ValueError("%s.level 非法：%r（允许 ERROR/WARN/INFO/off）" % (block, value))
    default = require(policy, "hygiene.diagnostics.default")
    if default not in spec.LEVELS:
        raise ValueError("hygiene.diagnostics.default 非法：%r" % (default,))
    for code, value in (get(policy, "hygiene.diagnostics.codes", {}) or {}).items():
        if value not in spec.LEVELS:
            raise ValueError("hygiene.diagnostics.codes.%s 非法：%r" % (code, value))
    fail_on = require(policy, "report.default_fail_on")
    if fail_on not in spec.FAIL_ON_VALUES:
        raise ValueError("report.default_fail_on 非法：%r" % (fail_on,))
    for dotted, minimum in (
        ("hygiene.expiring.warn_days", 0),
        ("hygiene.cliff.window_days", 1),
        ("hygiene.cliff.min_count", 1),
        ("hygiene.weak_key.rsa.min_bits", 1),
    ):
        value = require(policy, dotted)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError("%s 必须是 >= %d 的整数" % (dotted, minimum))
    curves = require(policy, "hygiene.weak_key.ec.allowed_curves")
    if not isinstance(curves, list) or not all(isinstance(item, str) for item in curves):
        raise ValueError("hygiene.weak_key.ec.allowed_curves 必须是字符串数组")
    digests = require(policy, "hygiene.weak_sig.forbidden_digests")
    if not isinstance(digests, list):
        raise ValueError("hygiene.weak_sig.forbidden_digests 必须是数组")
    mode = require(policy, "hygiene.permissions.max_posix_mode")
    try:
        int(str(mode), 8)
    except ValueError:
        raise ValueError("hygiene.permissions.max_posix_mode 必须是八进制字符串") from None
    return policy


def get(policy: dict, dotted: str, default=None):
    node = policy
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def require(policy: dict, dotted: str):
    value = get(policy, dotted, _MISSING)
    if value is _MISSING:
        raise ValueError("策略缺字段：%s" % dotted)
    return value


_MISSING = object()


class RuleSet:
    """读取策略等级、累计 findings；``off`` 计入 suppressed 而不是消失。"""

    def __init__(self, policy: dict) -> None:
        self.policy = policy
        self.findings: list = []
        self.suppressed: dict = {}

    def level(self, block: str) -> str:
        return str(require(self.policy, "%s.level" % block))

    def emit(self, *, block, code, subject, fingerprint, evidence, rule_id=None):
        level = self.level(block)
        if level == "off":
            self.suppressed[code] = self.suppressed.get(code, 0) + 1
            return
        self.findings.append(
            {
                "rule_id": rule_id or spec.CODE_RULES.get(code) or spec.BLOCK_RULE.get(block),
                "code": code,
                "severity": level,
                "subject": subject,
                "fingerprint": fingerprint,
                "evidence": evidence,
                "block": block,
            }
        )

    def emit_failure(self, *, code: str, evidence: dict):
        block = "hygiene.diagnostics"
        level = str(
            get(
                self.policy,
                "hygiene.diagnostics.codes.%s" % code,
                require(self.policy, "hygiene.diagnostics.default"),
            )
        )
        if level == "off":
            self.suppressed[code] = self.suppressed.get(code, 0) + 1
            return
        self.findings.append(
            {
                "rule_id": spec.RULE_DIAGNOSTIC,
                "code": code,
                "severity": level,
                "subject": "",
                "fingerprint": "",
                "evidence": evidence,
                "block": block,
            }
        )


def _display(value) -> str:
    if isinstance(value, dict):
        return str(value.get("display", ""))
    return str(value or "")


def _expiry_rules(rules: RuleSet, certs: list, as_of: AsOf) -> None:
    warn_days = int(require(rules.policy, "hygiene.expiring.warn_days"))
    warn_end = add_days(as_of.seconds, warn_days)
    for cert in certs:
        not_after = parse_stamp(cert.get("not_after", ""))
        if not_after is None:
            continue
        reference = str(cert.get("fingerprint_sha256", ""))
        if not_after < as_of.seconds:
            rules.emit(
                block="hygiene.expired",
                code="EXPIRED",
                subject=_display(cert.get("subject")),
                fingerprint=reference,
                evidence={
                    "not_after": cert.get("not_after", ""),
                    "as_of": as_of.iso,
                    "days_over": (as_of.seconds - not_after) // 86400,
                },
            )
        elif not_after < warn_end:
            rules.emit(
                block="hygiene.expiring",
                code="EXPIRING",
                subject=_display(cert.get("subject")),
                fingerprint=reference,
                evidence={
                    "not_after": cert.get("not_after", ""),
                    "as_of": as_of.iso,
                    "days_left": -(-(not_after - as_of.seconds) // 86400),
                    "warn_days": warn_days,
                },
            )


def _cliff_rule(rules: RuleSet, certs: list, as_of: AsOf) -> None:
    window_days = int(require(rules.policy, "hygiene.cliff.window_days"))
    min_count = int(require(rules.policy, "hygiene.cliff.min_count"))
    window_end = add_days(as_of.seconds, window_days)
    expiring: dict = {}
    for cert in certs:
        not_after = parse_stamp(cert.get("not_after", ""))
        if not_after is None:
            continue
        if as_of.seconds <= not_after < window_end:
            expiring[str(cert.get("fingerprint_sha256", ""))] = cert
    if len(expiring) < min_count:
        return
    rules.emit(
        block="hygiene.cliff",
        code="EXPIRY_CLIFF",
        subject="",
        fingerprint="",
        evidence={
            "window_start": as_of.iso,
            "window_end": format_utc(window_end),
            "window_days": window_days,
            "min_count": min_count,
            "count": len(expiring),
            "fingerprints": sorted(expiring),
        },
    )


def signature_name(dotted: str) -> str:
    """签名 OID -> 小写短名；未收录的 OID 保留点串（匹配不到摘要名，即「未知不判弱」）。"""
    if not dotted:
        return ""
    return spec.SIGNATURE_NAMES.get(dotted, dotted).lower()


def _strength_rules(rules: RuleSet, certs: list) -> None:
    rsa_min = int(require(rules.policy, "hygiene.weak_key.rsa.min_bits"))
    allowed = list(require(rules.policy, "hygiene.weak_key.ec.allowed_curves"))
    forbidden = [str(item).lower() for item in require(rules.policy, "hygiene.weak_sig.forbidden_digests")]
    nist_enabled = bool(require(rules.policy, "hygiene.nist_2031.enabled"))
    nist_bits = int(require(rules.policy, "hygiene.nist_2031.bits"))
    nist_statement = str(get(rules.policy, "hygiene.nist_2031.statement", ""))

    for cert in certs:
        display = _display(cert.get("subject"))
        fingerprint = str(cert.get("fingerprint_sha256", ""))
        algo = str(cert.get("key_algo", ""))
        bits = cert.get("key_bits")
        curve = cert.get("curve")

        if algo == "rsa" and isinstance(bits, int) and bits < rsa_min:
            rules.emit(
                block="hygiene.weak_key.rsa",
                code="WEAK_KEY",
                subject=display,
                fingerprint=fingerprint,
                rule_id=spec.RULE_WEAK_KEY_RSA,
                evidence={"key_algo": "rsa", "key_bits": bits, "min_bits": rsa_min},
            )
        elif algo == "ec" and curve is not None and curve not in allowed:
            rules.emit(
                block="hygiene.weak_key.ec",
                code="WEAK_KEY",
                subject=display,
                fingerprint=fingerprint,
                rule_id=spec.RULE_WEAK_KEY_EC,
                evidence={"key_algo": "ec", "curve": curve, "allowed_curves": allowed},
            )

        digest = signature_name(cert.get("sig_algo", ""))
        matched = next((name for name in forbidden if name in digest), None)
        if matched is not None:
            rules.emit(
                block="hygiene.weak_sig",
                code="WEAK_SIG",
                subject=display,
                fingerprint=fingerprint,
                evidence={
                    "sig_algo": cert.get("sig_algo", ""),
                    "sig_algo_name": digest,
                    "forbidden_digests": forbidden,
                },
            )

        if nist_enabled and algo == "rsa" and bits == nist_bits:
            rules.emit(
                block="hygiene.nist_2031",
                code="POLICY_NIST_2031",
                subject=display,
                fingerprint=fingerprint,
                evidence={
                    "key_algo": "rsa",
                    "key_bits": bits,
                    "statement": nist_statement,
                },
            )


def _key_hygiene_rules(rules: RuleSet, keys: list) -> None:
    permitted = int(str(require(rules.policy, "hygiene.permissions.max_posix_mode")), 8)
    for key in keys:
        spki = key.get("spki_sha256") or ""
        encrypted = bool(key.get("encrypted", False))
        if not encrypted:
            rules.emit(
                block="hygiene.private_key",
                code="PRIVATE_KEY_UNENCRYPTED",
                subject="",
                fingerprint=spki,
                evidence={"encrypted": False, "sources": len(key.get("sources") or [])},
            )
        for item in key.get("sources") or []:
            if not isinstance(item, dict):
                continue
            mode = item.get("posix_mode")
            if not mode:
                continue
            actual = int(str(mode), 8)
            if actual & ~permitted & 0o777:
                rules.emit(
                    block="hygiene.permissions",
                    code="PERMISSION_TOO_OPEN",
                    subject="",
                    fingerprint=spki,
                    evidence={
                        "path": item.get("path", ""),
                        "posix_mode": str(mode),
                        "max_posix_mode": str(
                            require(rules.policy, "hygiene.permissions.max_posix_mode")
                        ),
                    },
                )


def _pairing_rules(rules: RuleSet, certs: list, keys: list) -> None:
    key_spkis = {key["spki_sha256"] for key in keys if key.get("spki_sha256")}
    cert_spkis = {cert["spki_sha256"] for cert in certs if cert.get("spki_sha256")}

    for cert in certs:
        spki = cert.get("spki_sha256") or ""
        if not spki:
            continue
        if spki not in key_spkis:
            rules.emit(
                block="hygiene.orphans",
                code="ORPHAN_CERT",
                subject=_display(cert.get("subject")),
                fingerprint=str(cert.get("fingerprint_sha256", "")),
                rule_id=spec.RULE_ORPHAN_CERT,
                evidence={"spki_sha256": spki, "paired": False},
            )

    for key in keys:
        spki = key.get("spki_sha256")
        if not spki:
            continue
        if spki not in cert_spkis:
            rules.emit(
                block="hygiene.orphans",
                code="ORPHAN_KEY",
                subject="",
                fingerprint=spki,
                rule_id=spec.RULE_ORPHAN_KEY,
                evidence={"spki_sha256": spki, "paired": False},
            )


def _duplicate_rules(rules: RuleSet, certs: list, keys: list) -> None:
    for cert in certs:
        sources = cert.get("sources") or []
        if len(sources) > 1:
            rules.emit(
                block="hygiene.duplicates",
                code="DUPLICATE_CERT",
                subject=_display(cert.get("subject")),
                fingerprint=str(cert.get("fingerprint_sha256", "")),
                rule_id=spec.RULE_DUPLICATE_CERT,
                evidence={
                    "sources": len(sources),
                    "paths": [item.get("path", "") for item in sources if isinstance(item, dict)],
                },
            )
    for key in keys:
        sources = key.get("sources") or []
        if len(sources) > 1:
            rules.emit(
                block="hygiene.duplicates",
                code="DUPLICATE_KEY",
                subject="",
                fingerprint=key.get("spki_sha256") or "",
                rule_id=spec.RULE_DUPLICATE_KEY,
                evidence={
                    "sources": len(sources),
                    "paths": [item.get("path", "") for item in sources if isinstance(item, dict)],
                },
            )


def _container_rules(rules: RuleSet, containers: list) -> None:
    for container in containers:
        path = str(container.get("path", ""))
        entries = [item for item in container.get("entries") or [] if isinstance(item, dict)]
        unreadable = container.get("unreadable")
        if unreadable:
            rules.emit_failure(
                code="CONTAINER_UNREADABLE", evidence={"path": path, "reason": str(unreadable)}
            )
            continue
        has_key = bool(container.get("has_private_key")) or any(
            item.get("entry_type") == "privateKey" for item in entries
        )
        has_other = any(item.get("entry_type") != "privateKey" for item in entries)
        if has_key and has_other:
            rules.emit(
                block="hygiene.container_truststore",
                code="CONTAINER_TRUSTSTORE_WITH_KEY",
                subject="",
                fingerprint="",
                evidence={"path": path, "entries": len(entries)},
            )
        if container.get("password") == "empty":
            rules.emit(
                block="hygiene.container_password",
                code="CONTAINER_EMPTY_PASSWORD",
                subject="",
                fingerprint="",
                evidence={"path": path},
            )


def _diagnostic_rules(rules: RuleSet, diagnostics: list) -> None:
    for item in diagnostics:
        code = str(item.get("code", ""))
        if not code:
            continue
        rules.emit_failure(
            code=code,
            evidence={
                "path": item.get("path", ""),
                "stage": item.get("stage", ""),
                "detail": item.get("detail", ""),
            },
        )


def evaluate_findings(ledger: dict, policy: dict, as_of) -> dict:
    """对一份台账跑九族规则，返回 findings + suppressed + 计数（确定性排序）。"""
    if as_of is None:
        raise ValueError("as_of 必填：没有「当前时间」缺省值")
    if not isinstance(as_of, AsOf):
        as_of = AsOf(raw=str(as_of), seconds=int(as_of))
    rules = RuleSet(policy)

    certs = [item for item in ledger.get("certs", []) if isinstance(item, dict)]
    keys = [item for item in ledger.get("keys", []) if isinstance(item, dict)]
    diagnostics = [item for item in ledger.get("diagnostics", []) if isinstance(item, dict)]
    containers = [item for item in ledger.get("containers", []) if isinstance(item, dict)]

    _expiry_rules(rules, certs, as_of)
    _cliff_rule(rules, certs, as_of)
    _strength_rules(rules, certs)
    _key_hygiene_rules(rules, keys)
    _pairing_rules(rules, certs, keys)
    _duplicate_rules(rules, certs, keys)
    _container_rules(rules, containers)
    _diagnostic_rules(rules, diagnostics)

    findings = sorted(
        rules.findings,
        key=lambda item: (
            spec.SEVERITY_ORDER.get(item["severity"], 99),
            item["code"],
            item["subject"],
            item["fingerprint"],
            item["rule_id"],
        ),
    )
    by_severity = {"ERROR": 0, "WARN": 0, "INFO": 0}
    for finding in findings:
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
    return {
        "findings": findings,
        "suppressed": dict(sorted(rules.suppressed.items())),
        "summary": {
            "records": {
                "certs": len(certs),
                "keys": len(keys),
                "diagnostics": len(diagnostics),
            },
            "findings": len(findings),
            "by_severity": by_severity,
            "suppressed": sum(rules.suppressed.values()),
            "suppressed_by_code": dict(sorted(rules.suppressed.items())),
        },
    }


def threshold_reached(findings: list, threshold: str) -> bool:
    """旧仓 ``render._exit_code``：任一 finding 的等级 <= 阈值即阻断（``none`` 永不）。"""
    if threshold == "none":
        return False
    limit = spec.SEVERITY_ORDER[threshold]
    for finding in findings:
        if spec.SEVERITY_ORDER.get(str(finding.get("severity", "")), 99) <= limit:
            return True
    return False


def expiry_rows(findings: list) -> list:
    rows = []
    for finding in findings:
        if finding.get("code") not in ("EXPIRED", "EXPIRING"):
            continue
        evidence = finding.get("evidence") or {}
        days = evidence.get("days_over") if finding["code"] == "EXPIRED" else evidence.get("days_left")
        rows.append(
            {
                "not_after": str(evidence.get("not_after", "")),
                "state": finding["code"],
                "days": days,
                "subject": finding.get("subject", ""),
                "fingerprint": finding.get("fingerprint", ""),
            }
        )
    return sorted(rows, key=lambda row: (row["not_after"], row["fingerprint"]))