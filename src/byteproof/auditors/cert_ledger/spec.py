"""口径面：规则块、默认策略、等级映射与报告阈值。

阈值不写死在判定函数里：``subject.policy`` 覆盖随包默认策略（本文件
``DEFAULT_POLICY``，与旧仓 ``default-policy.json`` 同值同源）。规则出处来自
``basis``（``cl-*`` 规则登记），不来自策略文件的 ``source`` 字段——器官只通过
``basis.ref`` 取依据。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN

ORGAN_VERSION = "1"

MODES = ("inventory", "hygiene", "report", "containers")

#: 旧仓 ``model.SEVERITY_ORDER``：等级越高越严重（数字越小）。
SEVERITY_ORDER = {"ERROR": 0, "WARN": 1, "INFO": 2}
LEVELS = ("ERROR", "WARN", "INFO", "off")
FAIL_ON_VALUES = ("ERROR", "WARN", "INFO", "none")

LEDGER_KIND = "inventory"
REPORT_KIND = "report"

#: 失败路径代码的默认等级表（旧仓 ``hygiene.diagnostics.codes``）。
DIAGNOSTIC_DEFAULT = "INFO"
DIAGNOSTIC_CODES = {
    "PARSE_FAILED": "WARN",
    "PARSE_UNSUPPORTED": "INFO",
    "CONTAINER_UNREADABLE": "WARN",
    "SOURCE_UNAVAILABLE": "INFO",
}

#: 规则块 -> 规则 id。每个块 = 一条 basis 规则。
RULE_BLOCKS = (
    "hygiene.expired",
    "hygiene.expiring",
    "hygiene.cliff",
    "hygiene.weak_key.rsa",
    "hygiene.weak_key.ec",
    "hygiene.weak_sig",
    "hygiene.nist_2031",
    "hygiene.private_key",
    "hygiene.permissions",
    "hygiene.orphans",
    "hygiene.duplicates",
    "hygiene.container_truststore",
    "hygiene.container_password",
)

RULE_INVENTORY = "cl-inventory"
RULE_EXPIRED = "cl-expired"
RULE_EXPIRING = "cl-expiring"
RULE_EXPIRY_CLIFF = "cl-expiry-cliff"
RULE_WEAK_KEY_RSA = "cl-weak-key-rsa"
RULE_WEAK_KEY_EC = "cl-weak-key-ec"
RULE_WEAK_SIG = "cl-weak-sig"
RULE_NIST_2031 = "cl-nist-2031"
RULE_PRIVATE_KEY_UNENCRYPTED = "cl-private-key-unencrypted"
RULE_PERMISSION_TOO_OPEN = "cl-permission-too-open"
RULE_ORPHAN_CERT = "cl-orphan-cert"
RULE_ORPHAN_KEY = "cl-orphan-key"
RULE_DUPLICATE_CERT = "cl-duplicate-cert"
RULE_DUPLICATE_KEY = "cl-duplicate-key"
RULE_CONTAINER_TRUSTSTORE = "cl-container-truststore"
RULE_CONTAINER_OPEN_CREDENTIAL = "cl-container-open-credential"
RULE_DIAGNOSTIC = "cl-diagnostic"
RULE_POLICY_SUPPRESSED = "cl-policy-suppressed"
RULE_THRESHOLD_REACHED = "cl-threshold-reached"
RULE_DIFF = "cl-diff"
RULE_EXPIRY_TABLE = "cl-expiry-table"
RULE_LEDGER_SUMMARY = "cl-ledger-summary"

BLOCK_RULE = {
    "hygiene.expired": RULE_EXPIRED,
    "hygiene.expiring": RULE_EXPIRING,
    "hygiene.cliff": RULE_EXPIRY_CLIFF,
    "hygiene.weak_key.rsa": RULE_WEAK_KEY_RSA,
    "hygiene.weak_key.ec": RULE_WEAK_KEY_EC,
    "hygiene.weak_sig": RULE_WEAK_SIG,
    "hygiene.nist_2031": RULE_NIST_2031,
    "hygiene.private_key": RULE_PRIVATE_KEY_UNENCRYPTED,
    "hygiene.permissions": RULE_PERMISSION_TOO_OPEN,
    "hygiene.orphans": RULE_ORPHAN_CERT,
    "hygiene.duplicates": RULE_DUPLICATE_CERT,
    "hygiene.container_truststore": RULE_CONTAINER_TRUSTSTORE,
    "hygiene.container_password": RULE_CONTAINER_OPEN_CREDENTIAL,
    "hygiene.diagnostics": RULE_DIAGNOSTIC,
}

#: ``hygiene.orphans`` 与 ``hygiene.duplicates`` 各自产生两个代码，规则 id 按代码细分。
CODE_RULES = {
    "EXPIRED": RULE_EXPIRED,
    "EXPIRING": RULE_EXPIRING,
    "EXPIRY_CLIFF": RULE_EXPIRY_CLIFF,
    "WEAK_KEY": {
        "rsa": RULE_WEAK_KEY_RSA,
        "ec": RULE_WEAK_KEY_EC,
    },
    "WEAK_SIG": RULE_WEAK_SIG,
    "POLICY_NIST_2031": RULE_NIST_2031,
    "PRIVATE_KEY_UNENCRYPTED": RULE_PRIVATE_KEY_UNENCRYPTED,
    "PERMISSION_TOO_OPEN": RULE_PERMISSION_TOO_OPEN,
    "ORPHAN_CERT": RULE_ORPHAN_CERT,
    "ORPHAN_KEY": RULE_ORPHAN_KEY,
    "DUPLICATE_CERT": RULE_DUPLICATE_CERT,
    "DUPLICATE_KEY": RULE_DUPLICATE_KEY,
    "CONTAINER_TRUSTSTORE_WITH_KEY": RULE_CONTAINER_TRUSTSTORE,
    "CONTAINER_EMPTY_PASSWORD": RULE_CONTAINER_OPEN_CREDENTIAL,
}

RULE_IDS = (
    RULE_INVENTORY,
    RULE_EXPIRED,
    RULE_EXPIRING,
    RULE_EXPIRY_CLIFF,
    RULE_WEAK_KEY_RSA,
    RULE_WEAK_KEY_EC,
    RULE_WEAK_SIG,
    RULE_NIST_2031,
    RULE_PRIVATE_KEY_UNENCRYPTED,
    RULE_PERMISSION_TOO_OPEN,
    RULE_ORPHAN_CERT,
    RULE_ORPHAN_KEY,
    RULE_DUPLICATE_CERT,
    RULE_DUPLICATE_KEY,
    RULE_CONTAINER_TRUSTSTORE,
    RULE_CONTAINER_OPEN_CREDENTIAL,
    RULE_DIAGNOSTIC,
    RULE_POLICY_SUPPRESSED,
    RULE_THRESHOLD_REACHED,
    RULE_DIFF,
    RULE_EXPIRY_TABLE,
    RULE_LEDGER_SUMMARY,
)

#: 规则的名义等级（= 默认策略里的 level）；运行期等级仍由 ``subject.policy`` 决定。
VERDICTS = {
    RULE_INVENTORY: INFO,
    RULE_EXPIRED: ERROR,
    RULE_EXPIRING: WARN,
    RULE_EXPIRY_CLIFF: WARN,
    RULE_WEAK_KEY_RSA: WARN,
    RULE_WEAK_KEY_EC: WARN,
    RULE_WEAK_SIG: WARN,
    RULE_NIST_2031: INFO,
    RULE_PRIVATE_KEY_UNENCRYPTED: WARN,
    RULE_PERMISSION_TOO_OPEN: WARN,
    RULE_ORPHAN_CERT: INFO,
    RULE_ORPHAN_KEY: INFO,
    RULE_DUPLICATE_CERT: INFO,
    RULE_DUPLICATE_KEY: INFO,
    RULE_CONTAINER_TRUSTSTORE: WARN,
    RULE_CONTAINER_OPEN_CREDENTIAL: INFO,
    RULE_DIAGNOSTIC: INFO,
    RULE_POLICY_SUPPRESSED: INFO,
    RULE_THRESHOLD_REACHED: ERROR,
    RULE_DIFF: INFO,
    RULE_EXPIRY_TABLE: INFO,
    RULE_LEDGER_SUMMARY: INFO,
}

#: 随包默认策略：与旧仓 ``src/certledger/data/default-policy.json`` 同值。
DEFAULT_POLICY = {
    "policy_version": "1.1.0",
    "hygiene": {
        "expired": {"level": "ERROR"},
        "expiring": {"warn_days": 30, "level": "WARN"},
        "cliff": {"window_days": 30, "min_count": 3, "level": "WARN"},
        "weak_key": {
            "rsa": {"min_bits": 2048, "level": "WARN"},
            "ec": {
                "allowed_curves": ["secp256r1", "secp384r1", "secp521r1"],
                "level": "WARN",
            },
        },
        "weak_sig": {"forbidden_digests": ["sha1", "md5"], "level": "WARN"},
        "nist_2031": {
            "enabled": False,
            "bits": 2048,
            "level": "INFO",
            "statement": "按 NIST 时间表，2031 年起不再允许用于施加保护（当前仍属可接受使用）。",
        },
        "private_key": {"level": "WARN"},
        "permissions": {"max_posix_mode": "640", "level": "WARN"},
        "orphans": {"level": "INFO"},
        "duplicates": {"level": "INFO"},
        "container_truststore": {"level": "WARN"},
        "container_password": {"level": "INFO"},
        "diagnostics": {
            "default": "INFO",
            "codes": {
                "PARSE_FAILED": "WARN",
                "PARSE_UNSUPPORTED": "INFO",
                "CONTAINER_UNREADABLE": "WARN",
                "SOURCE_UNAVAILABLE": "INFO",
            },
        },
    },
    "report": {"default_fail_on": "ERROR"},
}

#: 常见签名 OID -> 短名（旧仓用 ``cryptography`` 私有属性取名；本器官只用标准库）。
SIGNATURE_NAMES = {
    "1.2.840.113549.1.1.2": "md2WithRSAEncryption",
    "1.2.840.113549.1.1.4": "md5WithRSAEncryption",
    "1.2.840.113549.1.1.5": "sha1WithRSAEncryption",
    "1.2.840.113549.1.1.11": "sha256WithRSAEncryption",
    "1.2.840.113549.1.1.12": "sha384WithRSAEncryption",
    "1.2.840.113549.1.1.13": "sha512WithRSAEncryption",
    "1.2.840.10045.4.1": "ecdsa-with-SHA1",
    "1.2.840.10045.4.3.2": "ecdsa-with-SHA256",
    "1.2.840.10045.4.3.3": "ecdsa-with-SHA384",
    "1.2.840.10045.4.3.4": "ecdsa-with-SHA512",
}

SOURCE_KINDS = ("file", "container", "store")
SOURCE_KIND_ORDER = {"file": 0, "container": 1, "store": 2}