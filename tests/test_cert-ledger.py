"""``cert-ledger`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那套函数仍然在、语义仍然是那一套**：
台账去重/配对/排序、九族卫生规则、失败路径、策略阈值、到期表、基线差异、
报告 ``--fail-on`` 门禁、容器信号。

**没迁的部分逐条写在 ``docs/cert-ledger.md`` §6 的处置表里**（PEM/DER/PKCS#12/JKS
解析、``cryptography``、``keytool``、系统信任库后端、目录遍历、密码环境变量、
报告排版与写盘）。不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 16 个判定层文件实跑 **X = 302 passed**（AST 函数 265）。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors.cert_ledger import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    diff,
    hygiene,
    ledger as ledger_mod,
    spec,
    timebase,
)
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    WARN,
    Basis,
    Report,
    RuleMissing,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "cert-ledger"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "cert_ledger"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "cert-ledger.basis.json"
THRESHOLDS_PATH = DATA_DIR / "cert-ledger.thresholds.json"
SAMPLE = ROOT / "samples" / "cert-ledger.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

AS_OF = 1900000000  # 2030-03-17T17:46:40Z
IN_WINDOW = "2030-03-27T17:46:40Z"  # +10 days
EXPIRED = "2030-03-01T00:00:00Z"
FAR = "2035-01-01T00:00:00Z"

FP = "a" * 64
SPKI = "b" * 64
SUBJECT_DER = "c" * 64


def _cert(fingerprint=FP, spki=SPKI, subject="CN=sample", not_after=IN_WINDOW, **extra):
    record = {
        "fingerprint_sha256": fingerprint,
        "spki_sha256": spki,
        "subject": {"display": subject, "der_sha256": SUBJECT_DER},
        "issuer": {"display": "CN=ca", "der_sha256": "d" * 64},
        "san": {"dns": [], "ip": [], "email": [], "uri": []},
        "not_before": "2029-01-01T00:00:00Z",
        "not_after": not_after,
        "key_algo": "rsa",
        "key_bits": 2048,
        "curve": None,
        "sig_algo": "1.2.840.113549.1.1.11",
        "key_usage": [],
        "extended_key_usage": [],
        "is_ca": False,
        "subject_key_id": None,
        "sources": [{"kind": "file", "path": "pki/a.pem", "posix_mode": "640"}],
    }
    record.update(extra)
    return record


def _key(spki=SPKI, encrypted=False, posix_mode="640", path="pki/a.key", **extra):
    record = {
        "spki_sha256": spki,
        "key_algo": "rsa",
        "key_bits": 2048,
        "curve": None,
        "encrypted": encrypted,
        "paired_cert_fingerprint": None,
        "sources": [{"kind": "file", "path": path, "posix_mode": posix_mode}],
    }
    record.update(extra)
    return record


def _ledger(certs=None, keys=None, containers=None, diagnostics=None):
    return {
        "schema_version": 1,
        "kind": "inventory",
        "certs": list(certs or []),
        "keys": list(keys or []),
        "containers": list(containers or []),
        "diagnostics": list(diagnostics or []),
    }


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _report(subject, basis=None):
    return Report(
        product="byteproof",
        organ=SLUG,
        organ_version=ORGAN_VERSION,
        subject="test.json",
        records=tuple(_evaluate(subject, basis)),
    )


def _hygiene(ledger, as_of=AS_OF, policy=None, **extra):
    subject = {"mode": "hygiene", "ledger": ledger, "as_of": as_of}
    if policy is not None:
        subject["policy"] = policy
    subject.update(extra)
    return subject


def _report_subject(ledger, as_of=AS_OF, **extra):
    subject = {"mode": "report", "ledger": ledger, "as_of": as_of}
    subject.update(extra)
    return subject


def _codes(subject):
    return [record.evidence.get("code") for record in _evaluate(subject) if record.evidence.get("code")]


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG
    assert PACK.version == "1"


def test_pack_declares_only_mode_as_universal_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "cert_ledger" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_modes_match_the_four_source_commands():
    assert spec.MODES == ("inventory", "hygiene", "report", "containers")


def test_sample_is_hygiene_at_the_readme_instant():
    subject = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert subject["mode"] == "hygiene"
    assert subject["as_of"] == AS_OF


# ================================================================== 规则包
def test_basis_has_every_declared_rule():
    assert set(BASIS.rule_ids()) == set(spec.RULE_IDS)


def test_basis_rules_all_have_version_source_and_text():
    for rule_id in BASIS.rule_ids():
        rule = BASIS.require(rule_id)
        assert rule.version == "1", rule_id
        assert rule.source, rule_id
        assert rule.text, rule_id


def test_basis_rule_ids_are_sorted():
    assert BASIS.rule_ids() == sorted(BASIS.rule_ids())


def test_rule_blocks_cover_all_hygiene_families():
    assert len(spec.RULE_BLOCKS) == 13
    assert set(spec.BLOCK_RULE) >= set(spec.RULE_BLOCKS) | {"hygiene.diagnostics"}


def test_code_rules_cover_every_finding_code():
    expected = {
        "EXPIRED",
        "EXPIRING",
        "EXPIRY_CLIFF",
        "WEAK_KEY",
        "WEAK_SIG",
        "POLICY_NIST_2031",
        "PRIVATE_KEY_UNENCRYPTED",
        "PERMISSION_TOO_OPEN",
        "ORPHAN_CERT",
        "ORPHAN_KEY",
        "DUPLICATE_CERT",
        "DUPLICATE_KEY",
        "CONTAINER_TRUSTSTORE_WITH_KEY",
        "CONTAINER_EMPTY_PASSWORD",
    }
    assert set(spec.CODE_RULES) == expected


def test_every_rule_id_has_a_nominal_verdict():
    assert set(spec.RULE_IDS) == set(spec.VERDICTS)


def test_nominal_verdicts_are_ledger_verdicts():
    assert set(spec.VERDICTS.values()) <= {ERROR, WARN, INFO}


def test_default_policy_has_a_level_for_every_block():
    for block in spec.RULE_BLOCKS:
        assert hygiene.require(spec.DEFAULT_POLICY, "%s.level" % block) in spec.LEVELS


def test_default_policy_diagnostics_codes_match_thresholds():
    assert hygiene.require(spec.DEFAULT_POLICY, "hygiene.diagnostics.default") == SETTINGS["defaults"]["diagnostics_default"]
    assert hygiene.get(spec.DEFAULT_POLICY, "hygiene.diagnostics.codes") == SETTINGS["diagnostics_codes"]


def test_thresholds_verdicts_match_runtime_table():
    assert SETTINGS["verdicts"] == spec.VERDICTS


def test_thresholds_severity_order_matches_runtime():
    assert SETTINGS["severity_order"] == spec.SEVERITY_ORDER


def test_thresholds_levels_and_fail_on_match_runtime():
    assert tuple(SETTINGS["levels"]) == spec.LEVELS
    assert tuple(SETTINGS["fail_on_values"]) == spec.FAIL_ON_VALUES


def test_thresholds_defaults_match_policy():
    defaults = SETTINGS["defaults"]
    assert defaults["expiring_warn_days"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.expiring.warn_days")
    assert defaults["cliff_window_days"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.cliff.window_days")
    assert defaults["cliff_min_count"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.cliff.min_count")
    assert defaults["rsa_min_bits"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.weak_key.rsa.min_bits")
    assert defaults["ec_allowed_curves"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.weak_key.ec.allowed_curves")
    assert defaults["weak_sig_forbidden_digests"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.weak_sig.forbidden_digests")
    assert defaults["permissions_max_posix_mode"] == hygiene.require(spec.DEFAULT_POLICY, "hygiene.permissions.max_posix_mode")
    assert defaults["default_fail_on"] == hygiene.require(spec.DEFAULT_POLICY, "report.default_fail_on")


def test_signature_names_include_the_forbidden_digests():
    sha1 = spec.SIGNATURE_NAMES["1.2.840.113549.1.1.5"].lower()
    md5 = spec.SIGNATURE_NAMES["1.2.840.113549.1.1.4"].lower()
    assert "sha1" in sha1
    assert "md5" in md5


def test_signature_names_do_not_mark_sha256_as_sha1():
    name = spec.SIGNATURE_NAMES["1.2.840.113549.1.1.11"].lower()
    assert "sha256" in name
    assert "sha1" not in name.replace("sha256", "")


# ================================================================== timebase
def test_epoch_is_parsed_verbatim():
    moment = timebase.parse_as_of("1900000000")
    assert moment.seconds == AS_OF
    assert moment.raw == "1900000000"


def test_negative_epoch_is_parsed():
    assert timebase.parse_as_of("-1").seconds == -1


@pytest.mark.parametrize(
    "text,seconds",
    [
        ("2030-03-17T17:46:40Z", AS_OF),
        ("2030-03-17T17:46:40z", AS_OF),
        ("2030-03-17T19:46:40+02:00", AS_OF),
        ("2030-03-17T12:46:40-05:00", AS_OF),
    ],
)
def test_iso_forms_are_parsed(text, seconds):
    assert timebase.parse_as_of(text).seconds == seconds


def test_naive_iso_is_rejected():
    with pytest.raises(ValueError):
        timebase.parse_as_of("2030-03-17T17:46:40")


def test_unparseable_as_of_is_rejected():
    with pytest.raises(ValueError):
        timebase.parse_as_of("not-a-time")


def test_missing_as_of_is_rejected():
    with pytest.raises(ValueError):
        timebase.parse_as_of(None)
    with pytest.raises(ValueError):
        timebase.parse_as_of("   ")


def test_as_of_iso_rendering_is_utc():
    assert timebase.parse_as_of("1900000000").iso == "2030-03-17T17:46:40Z"


def test_as_of_raw_keeps_the_input_spelling():
    assert timebase.parse_as_of("2030-03-17T17:46:40Z").raw == "2030-03-17T17:46:40Z"


def test_format_utc_is_fixed_width():
    assert timebase.format_utc(AS_OF) == "2030-03-17T17:46:40Z"
    assert timebase.format_utc(0) == "1970-01-01T00:00:00Z"


def test_add_days_crosses_month_boundaries():
    assert timebase.format_utc(timebase.add_days(AS_OF, 30)) == "2030-04-16T17:46:40Z"
    assert timebase.add_days(AS_OF, 0) == AS_OF


def test_parse_stamp_accepts_the_ledger_format():
    assert timebase.parse_stamp(IN_WINDOW) == AS_OF + 10 * 86400


def test_parse_stamp_returns_none_for_empty():
    assert timebase.parse_stamp("") is None
    assert timebase.parse_stamp(None) is None


def test_parse_stamp_returns_none_for_bad_text():
    assert timebase.parse_stamp("2030-03-17") is None
    assert timebase.parse_stamp("not-a-stamp") is None


def test_format_stamp_round_trips():
    assert timebase.format_stamp(AS_OF) == "2030-03-17T17:46:40Z"


# ================================================================== 策略
def test_policy_defaults_resolve():
    policy = hygiene.resolve_policy()
    assert policy["policy_version"] == "1.1.0"
    assert hygiene.require(policy, "hygiene.expired.level") == "ERROR"


def test_policy_overrides_a_level():
    policy = hygiene.resolve_policy({"hygiene": {"expired": {"level": "WARN"}}})
    assert hygiene.require(policy, "hygiene.expired.level") == "WARN"
    assert hygiene.require(policy, "hygiene.expiring.level") == "WARN"


def test_policy_override_is_a_deep_merge():
    policy = hygiene.resolve_policy({"hygiene": {"weak_key": {"rsa": {"min_bits": 4096}}}})
    assert hygiene.require(policy, "hygiene.weak_key.rsa.min_bits") == 4096
    assert hygiene.require(policy, "hygiene.weak_key.rsa.level") == "WARN"


def test_policy_adds_unknown_keys():
    policy = hygiene.resolve_policy({"custom": {"x": 1}})
    assert policy["custom"] == {"x": 1}


@pytest.mark.parametrize("level", ["error", "critical", "", None])
def test_invalid_level_is_rejected(level):
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"hygiene": {"expired": {"level": level}}})


def test_invalid_diagnostics_default_is_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"hygiene": {"diagnostics": {"default": "LOUD"}}})


def test_invalid_diagnostic_code_level_is_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"hygiene": {"diagnostics": {"codes": {"SKIP_X": "LOUD"}}}})


def test_invalid_fail_on_is_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"report": {"default_fail_on": "NEVER"}})


@pytest.mark.parametrize(
    "patch",
    [
        {"hygiene": {"expiring": {"warn_days": -1}}},
        {"hygiene": {"cliff": {"window_days": 0}}},
        {"hygiene": {"cliff": {"min_count": 0}}},
        {"hygiene": {"weak_key": {"rsa": {"min_bits": 0}}}},
    ],
)
def test_non_positive_thresholds_are_rejected(patch):
    with pytest.raises(ValueError):
        hygiene.resolve_policy(patch)


def test_non_list_curves_are_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"hygiene": {"weak_key": {"ec": {"allowed_curves": "secp256r1"}}}})


def test_non_list_digests_are_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"hygiene": {"weak_sig": {"forbidden_digests": "sha1"}}})


def test_bad_posix_mode_is_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy({"hygiene": {"permissions": {"max_posix_mode": "rw-r"}}})


def test_non_dict_policy_is_rejected():
    with pytest.raises(ValueError):
        hygiene.resolve_policy("policy.json")


def test_off_is_an_accepted_level():
    policy = hygiene.resolve_policy({"hygiene": {"orphans": {"level": "off"}}})
    assert hygiene.require(policy, "hygiene.orphans.level") == "off"


def test_get_returns_default_for_missing_path():
    assert hygiene.get({}, "a.b.c", 7) == 7


def test_get_walks_nested_dicts():
    assert hygiene.get({"a": {"b": 3}}, "a.b") == 3


def test_require_raises_for_missing_path():
    with pytest.raises(ValueError):
        hygiene.require({}, "a.b")


# ================================================================== 台账归并
def _entry_cert(fingerprint=FP, spki=SPKI, path="pki/a.pem", kind="file", **extra):
    entry = {
        "kind": "cert",
        "source": {"kind": kind, "path": path, "posix_mode": "640"},
        "fingerprint_sha256": fingerprint,
        "spki_sha256": spki,
        "subject": {"display": "CN=sample", "der_sha256": SUBJECT_DER},
        "issuer": {"display": "CN=ca", "der_sha256": "d" * 64},
        "not_after": IN_WINDOW,
    }
    entry.update(extra)
    return entry


def _entry_key(spki=SPKI, path="pki/a.key", **extra):
    entry = {"kind": "key", "source": {"kind": "file", "path": path, "posix_mode": "600"}, "spki_sha256": spki}
    entry.update(extra)
    return entry


def test_build_empty_entries_gives_empty_ledger():
    built = ledger_mod.build_ledger([])
    assert built["certs"] == []
    assert built["keys"] == []
    assert built["containers"] == []
    assert built["diagnostics"] == []
    assert built["summary"]["certs"] == 0


def test_build_counts_certs_and_keys():
    built = ledger_mod.build_ledger([_entry_cert(), _entry_key()])
    assert built["summary"]["certs"] == 1
    assert built["summary"]["keys"] == 1
    assert built["summary"]["paired"] == 1


def test_cert_is_deduped_by_fingerprint():
    built = ledger_mod.build_ledger([_entry_cert(path="pki/a.pem"), _entry_cert(path="pki/b.pem")])
    assert len(built["certs"]) == 1
    assert len(built["certs"][0]["sources"]) == 2


def test_cert_sources_are_sorted_by_kind_then_path():
    built = ledger_mod.build_ledger(
        [
            _entry_cert(path="pki/a.pem", kind="store"),
            _entry_cert(path="pki/b.pem", kind="file"),
        ]
    )
    assert [source["kind"] for source in built["certs"][0]["sources"]] == ["file", "store"]


def test_key_is_deduped_by_spki():
    built = ledger_mod.build_ledger([_entry_key(path="pki/a.key"), _entry_key(path="pki/b.key")])
    assert len(built["keys"]) == 1
    assert len(built["keys"][0]["sources"]) == 2


def test_locked_key_is_one_record_per_file():
    built = ledger_mod.build_ledger(
        [
            {"kind": "locked_key", "source": {"kind": "file", "path": "pki/a.key"}},
            {"kind": "locked_key", "source": {"kind": "file", "path": "pki/b.key"}},
        ]
    )
    assert len(built["keys"]) == 2
    assert all(record["spki_sha256"] is None for record in built["keys"])
    assert all(record["encrypted"] is True for record in built["keys"])


def test_locked_key_same_file_merges_sources():
    built = ledger_mod.build_ledger(
        [
            {"kind": "locked_key", "source": {"kind": "file", "path": "pki/a.key"}},
            {"kind": "locked_key", "source": {"kind": "file", "path": "pki/a.key", "alias": "dup"}},
        ]
    )
    assert len(built["keys"]) == 1
    assert len(built["keys"][0]["sources"]) == 2


def test_pairing_sets_paired_cert_fingerprint():
    built = ledger_mod.build_ledger([_entry_cert(), _entry_key()])
    assert built["keys"][0]["paired_cert_fingerprint"] == FP


def test_pairing_uses_lowest_fingerprint_when_several_certs_share_spki():
    built = ledger_mod.build_ledger(
        [_entry_cert(fingerprint="f" * 64), _entry_cert(fingerprint="0" * 64), _entry_key()]
    )
    assert built["keys"][0]["paired_cert_fingerprint"] == "0" * 64


def test_pairing_needs_both_sides():
    built = ledger_mod.build_ledger([_entry_cert()])
    assert built["summary"]["paired"] == 0


def test_container_is_recorded_even_when_empty():
    built = ledger_mod.build_ledger(
        [{"kind": "container", "path": "pki/store.jks", "format": "jks", "entries": []}]
    )
    assert built["containers"][0]["path"] == "pki/store.jks"
    assert built["containers"][0]["format"] == "jks"


def test_container_private_key_is_absorbed_encrypted():
    built = ledger_mod.build_ledger(
        [
            {
                "kind": "container",
                "path": "pki/store.p12",
                "format": "pkcs12",
                "entries": [{"alias": "a", "entry_type": "privateKey", "spki_sha256": SPKI}],
            }
        ]
    )
    assert len(built["keys"]) == 1
    assert built["keys"][0]["encrypted"] is True
    assert built["keys"][0]["sources"][0]["kind"] == "container"
    assert built["keys"][0]["sources"][0]["alias"] == "a"


def test_unknown_entry_kind_becomes_parse_unsupported():
    built = ledger_mod.build_ledger([{"kind": "pkcs7", "path": "pki/x.p7b"}])
    assert built["diagnostics"][0]["code"] == "PARSE_UNSUPPORTED"
    assert built["diagnostics"][0]["path"] == "pki/x.p7b"


def test_diagnostic_entries_pass_through():
    built = ledger_mod.build_ledger(
        [{"kind": "diagnostic", "code": "SKIP_FIFO", "path": "pki/fifo", "stage": "walk", "detail": "not a regular file"}]
    )
    assert built["diagnostics"][0]["code"] == "SKIP_FIFO"
    assert built["diagnostics"][0]["detail"] == "not a regular file"


def test_certs_are_sorted_by_fingerprint():
    built = ledger_mod.build_ledger(
        [_entry_cert(fingerprint="f" * 64, spki="1" * 64), _entry_cert(fingerprint="0" * 64, spki="2" * 64)]
    )
    assert [record["fingerprint_sha256"][0] for record in built["certs"]] == ["0", "f"]


def test_keys_are_sorted_with_locked_last():
    built = ledger_mod.build_ledger(
        [
            {"kind": "locked_key", "source": {"kind": "file", "path": "z.key"}},
            _entry_key(spki="0" * 64),
        ]
    )
    assert built["keys"][0]["spki_sha256"] == "0" * 64
    assert built["keys"][1]["spki_sha256"] is None


def test_diagnostics_are_sorted():
    built = ledger_mod.build_ledger(
        [
            {"kind": "diagnostic", "code": "B", "path": "z"},
            {"kind": "diagnostic", "code": "A", "path": "y"},
        ]
    )
    assert [item["code"] for item in built["diagnostics"]] == ["A", "B"]


def test_containers_are_sorted_by_path():
    built = ledger_mod.build_ledger(
        [
            {"kind": "container", "path": "b.jks", "entries": []},
            {"kind": "container", "path": "a.p12", "entries": []},
        ]
    )
    assert [item["path"] for item in built["containers"]] == ["a.p12", "b.jks"]


def test_build_rejects_non_list_entries():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger({"kind": "cert"})


def test_build_rejects_non_dict_entry():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger(["oops"])


def test_build_rejects_missing_kind():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([{"path": "x"}])


def test_build_rejects_cert_without_fingerprint():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([{"kind": "cert", "source": {"kind": "file", "path": "a"}}])


def test_build_rejects_key_without_spki():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([{"kind": "key", "source": {"kind": "file", "path": "a"}}])


def test_build_rejects_unknown_source_kind():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([_entry_cert(kind="ftp")])


def test_build_rejects_missing_source_path():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([{"kind": "cert", "source": {"kind": "file"}, "fingerprint_sha256": FP}])


def test_build_rejects_boolean_key_bits():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([_entry_cert(key_bits=True)])


def test_build_normalizes_string_subject_and_issuer():
    built = ledger_mod.build_ledger(
        [_entry_cert(subject="CN=plain", issuer="CN=ca-plain", subject_der_sha256="e" * 64)]
    )
    record = built["certs"][0]
    assert record["subject"] == {"display": "CN=plain", "der_sha256": "e" * 64}
    assert record["issuer"]["display"] == "CN=ca-plain"


def test_build_normalizes_san_lists():
    built = ledger_mod.build_ledger(
        [_entry_cert(san={"dns": ["a.example", "b.example"], "ip": ["192.0.2.1"]})]
    )
    assert built["certs"][0]["san"]["dns"] == ["a.example", "b.example"]
    assert built["certs"][0]["san"]["ip"] == ["192.0.2.1"]


def test_build_rejects_bad_container_entries():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([{"kind": "container", "path": "a.jks", "entries": "oops"}])


def test_build_rejects_container_without_path():
    with pytest.raises(ValueError):
        ledger_mod.build_ledger([{"kind": "container", "entries": []}])


def test_validate_ledger_accepts_an_empty_document():
    assert ledger_mod.validate_ledger({"certs": [], "keys": []}) == {"certs": [], "keys": []}


def test_validate_ledger_rejects_non_dict():
    with pytest.raises(ValueError):
        ledger_mod.validate_ledger([])


@pytest.mark.parametrize("field", ["certs", "keys", "containers", "diagnostics"])
def test_validate_ledger_rejects_non_list_field(field):
    with pytest.raises(ValueError):
        ledger_mod.validate_ledger({field: "oops"})


def test_validate_ledger_rejects_non_dict_items():
    with pytest.raises(ValueError):
        ledger_mod.validate_ledger({"certs": ["oops"]})


def test_build_does_not_mutate_input_entries():
    entry = _entry_cert()
    before = json.dumps(entry, sort_keys=True)
    ledger_mod.build_ledger([entry])
    assert json.dumps(entry, sort_keys=True) == before


# ================================================================== 过期
def test_expired_certificate_is_reported():
    records = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_EXPIRED)
    assert len(records) == 1
    assert records[0].evidence["code"] == "EXPIRED"
    assert records[0].verdict == WARN


def test_expired_boundary_is_strict():
    at_as_of = timebase.format_stamp(AS_OF)
    assert _records(_hygiene(_ledger(certs=[_cert(not_after=at_as_of)])), spec.RULE_EXPIRED) == []


def test_expiring_certificate_is_reported():
    records = _records(_hygiene(_ledger(certs=[_cert(not_after=IN_WINDOW)])), spec.RULE_EXPIRING)
    assert len(records) == 1
    assert records[0].evidence["code"] == "EXPIRING"


def test_expiring_window_end_is_exclusive():
    end = timebase.format_stamp(timebase.add_days(AS_OF, 30))
    assert _records(_hygiene(_ledger(certs=[_cert(not_after=end)])), spec.RULE_EXPIRING) == []


def test_expiring_just_inside_the_window():
    inside = timebase.format_stamp(timebase.add_days(AS_OF, 29))
    assert len(_records(_hygiene(_ledger(certs=[_cert(not_after=inside)])), spec.RULE_EXPIRING)) == 1


def test_unparseable_not_after_is_not_evidence():
    assert _records(_hygiene(_ledger(certs=[_cert(not_after="not-a-date")])), spec.RULE_EXPIRED) == []
    assert _records(_hygiene(_ledger(certs=[_cert(not_after="not-a-date")])), spec.RULE_EXPIRING) == []


def test_expired_evidence_days_over_floors():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_EXPIRED)[0]
    assert record.evidence["evidence"]["days_over"] == (AS_OF - timebase.parse_stamp(EXPIRED)) // 86400


def test_expiring_evidence_days_left_rounds_up():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=IN_WINDOW)])), spec.RULE_EXPIRING)[0]
    assert record.evidence["evidence"]["days_left"] == 10


def test_expired_keeps_true_severity_in_evidence():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_EXPIRED)[0]
    assert record.evidence["severity"] == "ERROR"


def test_expiring_keeps_warn_severity_in_evidence():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=IN_WINDOW)])), spec.RULE_EXPIRING)[0]
    assert record.evidence["severity"] == "WARN"


def test_expired_fingerprint_is_carried():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_EXPIRED)[0]
    assert record.evidence["fingerprint"] == FP


def test_subject_display_is_used():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED, subject="CN=显示名")])), spec.RULE_EXPIRED)[0]
    assert record.evidence["subject"] == "CN=显示名"


def test_warn_days_policy_override_changes_the_window():
    subject = _hygiene(
        _ledger(certs=[_cert(not_after=IN_WINDOW)]),
        policy={"hygiene": {"expiring": {"warn_days": 5}}},
    )
    assert _records(subject, spec.RULE_EXPIRING) == []


def test_off_suppresses_expired_but_counts_it():
    subject = _hygiene(
        _ledger(certs=[_cert(not_after=EXPIRED)]),
        policy={"hygiene": {"expired": {"level": "off"}}},
    )
    assert _records(subject, spec.RULE_EXPIRED) == []
    suppressed = _records(subject, spec.RULE_POLICY_SUPPRESSED)[0]
    assert suppressed.evidence["suppressed_by_code"] == {"EXPIRED": 1}


def test_expired_level_override_downgrades_evidence():
    subject = _hygiene(
        _ledger(certs=[_cert(not_after=EXPIRED)]),
        policy={"hygiene": {"expired": {"level": "INFO"}}},
    )
    record = _records(subject, spec.RULE_EXPIRED)[0]
    assert record.evidence["severity"] == "INFO"
    assert record.verdict == INFO


# ================================================================== 到期扎堆
def test_cliff_fires_at_min_count():
    certs = [_cert(fingerprint=char * 64, spki=str(index) * 64, not_after=IN_WINDOW) for index, char in enumerate("abc")]
    records = _records(_hygiene(_ledger(certs=certs)), spec.RULE_EXPIRY_CLIFF)
    assert len(records) == 1
    assert records[0].evidence["evidence"]["count"] == 3


def test_cliff_does_not_fire_below_min_count():
    certs = [_cert(fingerprint=char * 64, spki=str(index) * 64, not_after=IN_WINDOW) for index, char in enumerate("ab")]
    assert _records(_hygiene(_ledger(certs=certs)), spec.RULE_EXPIRY_CLIFF) == []


def test_cliff_counts_unique_fingerprints():
    certs = [_cert(fingerprint=FP, spki=str(index) * 64, not_after=IN_WINDOW) for index in range(3)]
    assert _records(_hygiene(_ledger(certs=certs)), spec.RULE_EXPIRY_CLIFF) == []


def test_cliff_window_is_exclusive_at_end():
    end = timebase.format_stamp(timebase.add_days(AS_OF, 30))
    certs = [_cert(fingerprint=char * 64, spki=str(index) * 64, not_after=end) for index, char in enumerate("abc")]
    assert _records(_hygiene(_ledger(certs=certs)), spec.RULE_EXPIRY_CLIFF) == []


def test_cliff_includes_already_expired_after_as_of():
    certs = [_cert(fingerprint=char * 64, spki=str(index) * 64, not_after=IN_WINDOW) for index, char in enumerate("abc")]
    record = _records(_hygiene(_ledger(certs=certs)), spec.RULE_EXPIRY_CLIFF)[0]
    assert record.evidence["evidence"]["window_days"] == 30
    assert record.evidence["evidence"]["window_start"] == "2030-03-17T17:46:40Z"


def test_cliff_min_count_override():
    subject = _hygiene(
        _ledger(certs=[_cert(fingerprint=char * 64, spki=str(index) * 64, not_after=IN_WINDOW) for index, char in enumerate("ab")]),
        policy={"hygiene": {"cliff": {"min_count": 2}}},
    )
    assert len(_records(subject, spec.RULE_EXPIRY_CLIFF)) == 1


def test_cliff_off_is_suppressed():
    certs = [_cert(fingerprint=char * 64, spki=str(index) * 64, not_after=IN_WINDOW) for index, char in enumerate("abc")]
    subject = _hygiene(_ledger(certs=certs), policy={"hygiene": {"cliff": {"level": "off"}}})
    assert _records(subject, spec.RULE_EXPIRY_CLIFF) == []
    assert _records(subject, spec.RULE_POLICY_SUPPRESSED)[0].evidence["suppressed_by_code"]["EXPIRY_CLIFF"] == 1


# ================================================================== 强度
def test_rsa_below_min_is_weak():
    record = _records(_hygiene(_ledger(certs=[_cert(key_bits=1024)])), spec.RULE_WEAK_KEY_RSA)[0]
    assert record.evidence["code"] == "WEAK_KEY"
    assert record.evidence["evidence"]["min_bits"] == 2048


def test_rsa_exactly_min_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(key_bits=2048)])), spec.RULE_WEAK_KEY_RSA) == []


def test_rsa_above_min_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(key_bits=4096)])), spec.RULE_WEAK_KEY_RSA) == []


def test_rsa_missing_bits_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(key_bits=None)])), spec.RULE_WEAK_KEY_RSA) == []


def test_ec_disallowed_curve_is_weak():
    record = _records(
        _hygiene(_ledger(certs=[_cert(key_algo="ec", key_bits=256, curve="secp256k1")])),
        spec.RULE_WEAK_KEY_EC,
    )[0]
    assert record.evidence["evidence"]["curve"] == "secp256k1"


def test_ec_allowed_curve_is_not_weak():
    assert (
        _records(
            _hygiene(_ledger(certs=[_cert(key_algo="ec", key_bits=256, curve="secp256r1")])),
            spec.RULE_WEAK_KEY_EC,
        )
        == []
    )


def test_ec_missing_curve_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(key_algo="ec", curve=None)])), spec.RULE_WEAK_KEY_EC) == []


def test_unknown_key_algo_is_not_weak():
    subject = _hygiene(_ledger(certs=[_cert(key_algo="", key_bits=512)]))
    assert _records(subject, spec.RULE_WEAK_KEY_RSA) == []
    assert _records(subject, spec.RULE_WEAK_KEY_EC) == []


def test_sha1_signature_is_weak():
    record = _records(
        _hygiene(_ledger(certs=[_cert(sig_algo="1.2.840.113549.1.1.5")])),
        spec.RULE_WEAK_SIG,
    )[0]
    assert record.evidence["evidence"]["sig_algo_name"] == "sha1withrsaencryption"


def test_md5_signature_is_weak():
    assert (
        len(
            _records(
                _hygiene(_ledger(certs=[_cert(sig_algo="1.2.840.113549.1.1.4")])),
                spec.RULE_WEAK_SIG,
            )
        )
        == 1
    )


def test_sha256_signature_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(sig_algo="1.2.840.113549.1.1.11")])), spec.RULE_WEAK_SIG) == []


def test_unknown_signature_oid_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(sig_algo="1.2.3.4.5")])), spec.RULE_WEAK_SIG) == []


def test_empty_signature_is_not_weak():
    assert _records(_hygiene(_ledger(certs=[_cert(sig_algo="")])), spec.RULE_WEAK_SIG) == []


def test_signature_name_lowercases():
    assert hygiene.signature_name("1.2.840.113549.1.1.5") == "sha1withrsaencryption"
    assert hygiene.signature_name("") == ""


def test_signature_name_keeps_unknown_dotted():
    assert hygiene.signature_name("1.2.3.4") == "1.2.3.4"


def test_nist_2031_is_off_by_default():
    assert _records(_hygiene(_ledger(certs=[_cert(key_bits=2048)])), spec.RULE_NIST_2031) == []


def test_nist_2031_fires_when_enabled():
    subject = _hygiene(
        _ledger(certs=[_cert(key_bits=2048)]),
        policy={"hygiene": {"nist_2031": {"enabled": True}}},
    )
    record = _records(subject, spec.RULE_NIST_2031)[0]
    assert record.evidence["evidence"]["key_bits"] == 2048


def test_nist_2031_ignores_other_bit_sizes():
    subject = _hygiene(
        _ledger(certs=[_cert(key_bits=3072)]),
        policy={"hygiene": {"nist_2031": {"enabled": True}}},
    )
    assert _records(subject, spec.RULE_NIST_2031) == []


def test_nist_2031_ignores_ec():
    subject = _hygiene(
        _ledger(certs=[_cert(key_algo="ec", curve="secp256r1")]),
        policy={"hygiene": {"nist_2031": {"enabled": True}}},
    )
    assert _records(subject, spec.RULE_NIST_2031) == []


def test_nist_2031_statement_is_carried():
    subject = _hygiene(
        _ledger(certs=[_cert(key_bits=2048)]),
        policy={"hygiene": {"nist_2031": {"enabled": True}}},
    )
    record = _records(subject, spec.RULE_NIST_2031)[0]
    assert "2031" in record.evidence["evidence"]["statement"]


def test_weak_key_rsa_uses_the_rsa_rule_id():
    assert (
        _records(_hygiene(_ledger(certs=[_cert(key_bits=1024)])), spec.RULE_WEAK_KEY_RSA)[0].evidence["code"]
        == "WEAK_KEY"
    )


def test_weak_key_ec_uses_the_ec_rule_id():
    assert (
        _records(
            _hygiene(_ledger(certs=[_cert(key_algo="ec", key_bits=256, curve="secp256k1")])),
            spec.RULE_WEAK_KEY_EC,
        )[0].evidence["code"]
        == "WEAK_KEY"
    )


# ================================================================== 私钥
def test_unencrypted_key_is_reported():
    record = _records(_hygiene(_ledger(keys=[_key()])), spec.RULE_PRIVATE_KEY_UNENCRYPTED)[0]
    assert record.evidence["evidence"]["encrypted"] is False


def test_encrypted_key_is_not_reported():
    assert _records(_hygiene(_ledger(keys=[_key(encrypted=True)])), spec.RULE_PRIVATE_KEY_UNENCRYPTED) == []


def test_unencrypted_evidence_counts_sources():
    record = _records(_hygiene(_ledger(keys=[_key()])), spec.RULE_PRIVATE_KEY_UNENCRYPTED)[0]
    assert record.evidence["evidence"]["sources"] == 1


def test_open_permissions_are_reported():
    record = _records(_hygiene(_ledger(keys=[_key(posix_mode="644")])), spec.RULE_PERMISSION_TOO_OPEN)[0]
    assert record.evidence["evidence"]["posix_mode"] == "644"


def test_600_permissions_are_fine():
    assert _records(_hygiene(_ledger(keys=[_key(posix_mode="600")])), spec.RULE_PERMISSION_TOO_OPEN) == []


def test_640_permissions_are_fine():
    assert _records(_hygiene(_ledger(keys=[_key(posix_mode="640")])), spec.RULE_PERMISSION_TOO_OPEN) == []


def test_group_read_permissions_are_too_open():
    assert len(_records(_hygiene(_ledger(keys=[_key(posix_mode="660")])), spec.RULE_PERMISSION_TOO_OPEN)) == 1


def test_other_read_permissions_are_too_open():
    assert len(_records(_hygiene(_ledger(keys=[_key(posix_mode="604")])), spec.RULE_PERMISSION_TOO_OPEN)) == 1


def test_missing_permissions_are_not_judged():
    assert _records(_hygiene(_ledger(keys=[_key(posix_mode=None)])), spec.RULE_PERMISSION_TOO_OPEN) == []


def test_each_source_is_judged():
    record = _key(posix_mode="644")
    record["sources"].append({"kind": "store", "path": "store", "posix_mode": "644"})
    assert len(_records(_hygiene(_ledger(keys=[record])), spec.RULE_PERMISSION_TOO_OPEN)) == 2


def test_permission_evidence_carries_path_and_limit():
    record = _records(_hygiene(_ledger(keys=[_key(posix_mode="644", path="pki/z.key")])), spec.RULE_PERMISSION_TOO_OPEN)[0]
    assert record.evidence["evidence"]["path"] == "pki/z.key"
    assert record.evidence["evidence"]["max_posix_mode"] == "640"


def test_locked_key_is_not_unencrypted():
    assert (
        _records(
            _hygiene(_ledger(keys=[_key(spki=None, encrypted=True, posix_mode="600")])),
            spec.RULE_PRIVATE_KEY_UNENCRYPTED,
        )
        == []
    )


def test_permissions_off_is_suppressed():
    subject = _hygiene(
        _ledger(keys=[_key(posix_mode="644")]),
        policy={"hygiene": {"permissions": {"level": "off"}}},
    )
    assert _records(subject, spec.RULE_PERMISSION_TOO_OPEN) == []
    assert _records(subject, spec.RULE_POLICY_SUPPRESSED)[0].evidence["suppressed_by_code"]["PERMISSION_TOO_OPEN"] == 1


def test_private_key_off_is_suppressed():
    subject = _hygiene(
        _ledger(keys=[_key()]),
        policy={"hygiene": {"private_key": {"level": "off"}}},
    )
    assert _records(subject, spec.RULE_PRIVATE_KEY_UNENCRYPTED) == []


# ================================================================== 孤儿
def test_orphan_certificate_is_reported():
    records = _records(_hygiene(_ledger(certs=[_cert()])), spec.RULE_ORPHAN_CERT)
    assert len(records) == 1


def test_paired_certificate_is_not_orphan():
    assert _records(_hygiene(_ledger(certs=[_cert()], keys=[_key()])), spec.RULE_ORPHAN_CERT) == []


def test_orphan_key_is_reported():
    records = _records(_hygiene(_ledger(keys=[_key()])), spec.RULE_ORPHAN_KEY)
    assert len(records) == 1


def test_locked_key_is_not_orphan():
    assert _records(_hygiene(_ledger(keys=[_key(spki=None, encrypted=True)])), spec.RULE_ORPHAN_KEY) == []


def test_cert_without_spki_is_not_orphan():
    assert _records(_hygiene(_ledger(certs=[_cert(spki="")])), spec.RULE_ORPHAN_CERT) == []


def test_key_without_spki_is_not_orphan():
    assert _records(_hygiene(_ledger(keys=[_key(spki="")])), spec.RULE_ORPHAN_KEY) == []


def test_both_sides_can_be_orphans():
    subject = _hygiene(_ledger(certs=[_cert(spki="1" * 64)], keys=[_key(spki="2" * 64)]))
    assert len(_records(subject, spec.RULE_ORPHAN_CERT)) == 1
    assert len(_records(subject, spec.RULE_ORPHAN_KEY)) == 1


def test_orphans_off_suppresses_both_codes():
    subject = _hygiene(
        _ledger(certs=[_cert(spki="1" * 64)], keys=[_key(spki="2" * 64)]),
        policy={"hygiene": {"orphans": {"level": "off"}}},
    )
    suppressed = _records(subject, spec.RULE_POLICY_SUPPRESSED)[0].evidence["suppressed_by_code"]
    assert suppressed == {"ORPHAN_CERT": 1, "ORPHAN_KEY": 1}


# ================================================================== 重复
def test_duplicate_certificate_is_reported():
    record = _cert()
    record["sources"].append({"kind": "store", "path": "store", "alias": "x"})
    found = _records(_hygiene(_ledger(certs=[record])), spec.RULE_DUPLICATE_CERT)[0]
    assert found.evidence["evidence"]["sources"] == 2


def test_single_source_certificate_is_not_duplicate():
    assert _records(_hygiene(_ledger(certs=[_cert()])), spec.RULE_DUPLICATE_CERT) == []


def test_duplicate_key_is_reported():
    record = _key()
    record["sources"].append({"kind": "store", "path": "store", "alias": "x"})
    assert len(_records(_hygiene(_ledger(keys=[record])), spec.RULE_DUPLICATE_KEY)) == 1


def test_single_source_key_is_not_duplicate():
    assert _records(_hygiene(_ledger(keys=[_key()])), spec.RULE_DUPLICATE_KEY) == []


def test_duplicate_certificate_carries_paths():
    record = _cert()
    record["sources"].append({"kind": "store", "path": "store", "alias": "x"})
    found = _records(_hygiene(_ledger(certs=[record])), spec.RULE_DUPLICATE_CERT)[0]
    assert found.evidence["evidence"]["paths"] == ["pki/a.pem", "store"]


def test_duplicates_off_is_suppressed():
    record = _cert()
    record["sources"].append({"kind": "store", "path": "store"})
    subject = _hygiene(_ledger(certs=[record]), policy={"hygiene": {"duplicates": {"level": "off"}}})
    assert _records(subject, spec.RULE_DUPLICATE_CERT) == []


# ================================================================== 容器
def _container(path="pki/store.p12", entries=None, **extra):
    record = {
        "path": path,
        "format": "pkcs12",
        "has_private_key": False,
        "password": None,
        "unreadable": None,
        "entries": list(entries or []),
    }
    record.update(extra)
    return record


def test_truststore_with_key_is_reported():
    container = _container(entries=[{"entry_type": "certificate"}, {"entry_type": "privateKey"}])
    assert len(_records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_TRUSTSTORE)) == 1


def test_truststore_with_key_uses_has_private_key_flag():
    container = _container(has_private_key=True, entries=[{"entry_type": "certificate"}])
    assert len(_records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_TRUSTSTORE)) == 1


def test_certificates_only_container_is_not_truststore_with_key():
    container = _container(entries=[{"entry_type": "certificate"}, {"entry_type": "certificate"}])
    assert _records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_TRUSTSTORE) == []


def test_key_only_container_is_not_truststore_with_key():
    container = _container(entries=[{"entry_type": "privateKey"}])
    assert _records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_TRUSTSTORE) == []


def test_container_open_with_empty_credential_is_reported():
    container = _container(password="empty")
    record = _records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_OPEN_CREDENTIAL)[0]
    assert record.evidence["code"] == "CONTAINER_EMPTY_PASSWORD"
    assert record.evidence["severity"] == "INFO"


def test_container_with_credential_is_not_reported():
    container = _container(password="provided")
    assert _records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_OPEN_CREDENTIAL) == []


def test_unreadable_container_becomes_a_diagnostic():
    container = _container(unreadable="bad credential")
    record = _records(_hygiene(_ledger(containers=[container])), spec.RULE_DIAGNOSTIC)[0]
    assert record.evidence["code"] == "CONTAINER_UNREADABLE"
    assert record.evidence["severity"] == "WARN"


def test_unreadable_container_skips_other_rules():
    container = _container(unreadable="bad", password="empty", has_private_key=True, entries=[{"entry_type": "certificate"}])
    subject = _hygiene(_ledger(containers=[container]))
    assert _records(subject, spec.RULE_CONTAINER_OPEN_CREDENTIAL) == []
    assert _records(subject, spec.RULE_CONTAINER_TRUSTSTORE) == []


def test_container_evidence_has_entry_count():
    container = _container(entries=[{"entry_type": "certificate"}, {"entry_type": "privateKey"}])
    record = _records(_hygiene(_ledger(containers=[container])), spec.RULE_CONTAINER_TRUSTSTORE)[0]
    assert record.evidence["evidence"]["entries"] == 2


def test_container_open_credential_off_is_suppressed():
    subject = _hygiene(
        _ledger(containers=[_container(password="empty")]),
        policy={"hygiene": {"container_password": {"level": "off"}}},
    )
    assert _records(subject, spec.RULE_CONTAINER_OPEN_CREDENTIAL) == []


# ================================================================== 诊断
def test_parse_failed_is_warn():
    record = _records(
        _hygiene(_ledger(diagnostics=[{"code": "PARSE_FAILED", "path": "a.pem"}])),
        spec.RULE_DIAGNOSTIC,
    )[0]
    assert record.evidence["severity"] == "WARN"


def test_parse_unsupported_is_info():
    record = _records(
        _hygiene(_ledger(diagnostics=[{"code": "PARSE_UNSUPPORTED", "path": "a.p7b"}])),
        spec.RULE_DIAGNOSTIC,
    )[0]
    assert record.evidence["severity"] == "INFO"


def test_source_unavailable_is_info():
    record = _records(
        _hygiene(_ledger(diagnostics=[{"code": "SOURCE_UNAVAILABLE", "path": "store"}])),
        spec.RULE_DIAGNOSTIC,
    )[0]
    assert record.evidence["severity"] == "INFO"


def test_unknown_diagnostic_code_gets_the_default():
    record = _records(
        _hygiene(_ledger(diagnostics=[{"code": "SKIP_FIFO", "path": "fifo"}])),
        spec.RULE_DIAGNOSTIC,
    )[0]
    assert record.evidence["severity"] == "INFO"


def test_diagnostic_code_level_override():
    subject = _hygiene(
        _ledger(diagnostics=[{"code": "SKIP_FIFO", "path": "fifo"}]),
        policy={"hygiene": {"diagnostics": {"codes": {"SKIP_FIFO": "WARN"}}}},
    )
    assert _records(subject, spec.RULE_DIAGNOSTIC)[0].evidence["severity"] == "WARN"


def test_empty_diagnostic_code_is_skipped():
    assert _records(_hygiene(_ledger(diagnostics=[{"code": "", "path": "x"}])), spec.RULE_DIAGNOSTIC) == []


def test_diagnostic_evidence_carries_stage_and_detail():
    record = _records(
        _hygiene(
            _ledger(
                diagnostics=[{"code": "PARSE_FAILED", "path": "a.pem", "stage": "parse", "detail": "bad der"}]
            )
        ),
        spec.RULE_DIAGNOSTIC,
    )[0]
    assert record.evidence["evidence"]["stage"] == "parse"
    assert record.evidence["evidence"]["detail"] == "bad der"


def test_diagnostics_default_off_suppresses_everything():
    subject = _hygiene(
        _ledger(diagnostics=[{"code": "SKIP_FIFO", "path": "fifo"}]),
        policy={"hygiene": {"diagnostics": {"default": "off"}}},
    )
    assert _records(subject, spec.RULE_DIAGNOSTIC) == []
    assert _records(subject, spec.RULE_POLICY_SUPPRESSED)[0].evidence["suppressed_by_code"] == {"SKIP_FIFO": 1}


def test_diagnostic_code_off_is_suppressed():
    subject = _hygiene(
        _ledger(diagnostics=[{"code": "PARSE_FAILED", "path": "a.pem"}]),
        policy={"hygiene": {"diagnostics": {"codes": {"PARSE_FAILED": "off"}}}},
    )
    assert _records(subject, spec.RULE_DIAGNOSTIC) == []


def test_findings_are_sorted_by_severity_then_code():
    ledger = _ledger(
        certs=[_cert(not_after=IN_WINDOW)],
        keys=[_key(posix_mode="644")],
        diagnostics=[{"code": "PARSE_FAILED", "path": "a"}],
    )
    result = hygiene.evaluate_findings(ledger, hygiene.resolve_policy(), timebase.AsOf(raw=str(AS_OF), seconds=AS_OF))
    codes = [(item["severity"], item["code"]) for item in result["findings"]]
    assert codes == sorted(codes, key=lambda item: (spec.SEVERITY_ORDER[item[0]], item[1]))


# ================================================================== 抑制与摘要
def test_suppressed_record_is_emitted():
    subject = _hygiene(_ledger(keys=[_key()]), policy={"hygiene": {"private_key": {"level": "off"}}})
    record = _records(subject, spec.RULE_POLICY_SUPPRESSED)[0]
    assert record.evidence["suppressed"] == 1


def test_no_suppressed_record_when_nothing_is_off():
    assert _records(_hygiene(_ledger(keys=[_key()])), spec.RULE_POLICY_SUPPRESSED) == []


def test_summary_counts_records_and_findings():
    subject = _hygiene(_ledger(certs=[_cert(not_after=IN_WINDOW)], keys=[_key()]))
    summary = _records(subject, spec.RULE_LEDGER_SUMMARY)[0].evidence["summary"]
    assert summary["records"] == {"certs": 1, "keys": 1, "diagnostics": 0}
    assert summary["findings"] >= 2


def test_by_severity_counts_are_named():
    subject = _hygiene(_ledger(certs=[_cert(not_after=EXPIRED)]))
    summary = _records(subject, spec.RULE_LEDGER_SUMMARY)[0].evidence["summary"]
    assert set(summary["by_severity"]) == {"ERROR", "WARN", "INFO"}


# ================================================================== 到期表与报告
def test_expiry_rows_include_expired_and_expiring():
    subject = _report_subject(_ledger(certs=[_cert(not_after=EXPIRED), _cert(fingerprint="e" * 64, spki="f" * 64, not_after=IN_WINDOW)]))
    record = _records(subject, spec.RULE_EXPIRY_TABLE)[0]
    assert record.evidence["expiries_total"] == 2
    assert [row["state"] for row in record.evidence["rows"]] == ["EXPIRED", "EXPIRING"]


def test_expiry_rows_are_sorted_by_not_after():
    subject = _report_subject(
        _ledger(
            certs=[
                _cert(fingerprint="e" * 64, spki="f" * 64, not_after=IN_WINDOW),
                _cert(fingerprint="1" * 64, spki="2" * 64, not_after=EXPIRED),
            ]
        )
    )
    rows = _records(subject, spec.RULE_EXPIRY_TABLE)[0].evidence["rows"]
    assert [row["not_after"] for row in rows] == [EXPIRED, IN_WINDOW]


def test_top_trims_display_only():
    certs = [
        _cert(fingerprint="e" * 64, spki="f" * 64, not_after=EXPIRED),
        _cert(fingerprint="1" * 64, spki="2" * 64, not_after=IN_WINDOW),
    ]
    record = _records(_report_subject(_ledger(certs=certs), top=1), spec.RULE_EXPIRY_TABLE)[0]
    assert record.evidence["expiries_total"] == 2
    assert record.evidence["expiries_shown"] == 1
    assert len(_records(_report_subject(_ledger(certs=certs), top=1), spec.RULE_EXPIRED)) == 1


def test_top_zero_shows_nothing():
    record = _records(_report_subject(_ledger(certs=[_cert(not_after=EXPIRED)]), top=0), spec.RULE_EXPIRY_TABLE)[0]
    assert record.evidence["expiries_shown"] == 0


def test_negative_top_is_rejected():
    with pytest.raises(ValueError):
        _evaluate(_report_subject(_ledger(), top=-1))


def test_gate_not_reached_for_expiring_at_error_threshold():
    assert _records(_report_subject(_ledger(certs=[_cert(not_after=IN_WINDOW)])), spec.RULE_THRESHOLD_REACHED) == []


def test_gate_reached_for_expired_at_error_threshold():
    record = _records(_report_subject(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_THRESHOLD_REACHED)[0]
    assert record.verdict == ERROR
    assert record.evidence["fail_on"] == "ERROR"


def test_gate_reached_for_expiring_at_warn_threshold():
    record = _records(
        _report_subject(_ledger(certs=[_cert(not_after=IN_WINDOW)]), fail_on="WARN"),
        spec.RULE_THRESHOLD_REACHED,
    )[0]
    assert record.evidence["fail_on"] == "WARN"


def test_gate_reached_for_info_at_info_threshold():
    record = _records(
        _report_subject(_ledger(keys=[_key(spki="1" * 64)]), fail_on="INFO"),
        spec.RULE_THRESHOLD_REACHED,
    )[0]
    assert record.evidence["fail_on"] == "INFO"


def test_gate_none_never_blocks():
    assert _records(_report_subject(_ledger(certs=[_cert(not_after=EXPIRED)]), fail_on="none"), spec.RULE_THRESHOLD_REACHED) == []


def test_gate_evidence_names_codes():
    record = _records(
        _report_subject(
            _ledger(certs=[_cert(not_after=EXPIRED)], keys=[_key(posix_mode="644")]),
            fail_on="INFO",
        ),
        spec.RULE_THRESHOLD_REACHED,
    )[0]
    assert set(record.evidence["codes"]) == {"EXPIRED", "PRIVATE_KEY_UNENCRYPTED", "PERMISSION_TOO_OPEN"}


def test_gate_reached_report_is_blocked():
    assert _report(_report_subject(_ledger(certs=[_cert(not_after=EXPIRED)]))).exit_code() == EXIT_BLOCKED


def test_gate_none_report_is_clean():
    assert (
        _report(_report_subject(_ledger(certs=[_cert(not_after=EXPIRED)]), fail_on="none")).exit_code()
        == EXIT_OK
    )


def test_fail_on_default_comes_from_policy():
    subject = _report_subject(_ledger(), policy={"report": {"default_fail_on": "WARN"}})
    subject["ledger"] = _ledger(certs=[_cert(not_after=IN_WINDOW)])
    assert len(_records(subject, spec.RULE_THRESHOLD_REACHED)) == 1


def test_invalid_fail_on_is_rejected():
    with pytest.raises(ValueError):
        _evaluate(_report_subject(_ledger(), fail_on="MAYBE"))


# ================================================================== 基线差异
def _row(fingerprint, spki, subject_der, subject="CN=x"):
    return {
        "fingerprint_sha256": fingerprint,
        "spki_sha256": spki,
        "subject": subject,
        "subject_der_sha256": subject_der,
    }


def test_diff_added():
    result = diff.diff_against({"certificates": []}, [_row("a" * 64, "b" * 64, "c" * 64)])
    assert len(result["added"]) == 1


def test_diff_removed():
    result = diff.diff_against({"certificates": [_row("a" * 64, "b" * 64, "c" * 64)]}, [])
    assert len(result["removed"]) == 1


def test_diff_rotated_when_name_and_key_survive():
    before = [_row("a" * 64, "b" * 64, "c" * 64)]
    after = [_row("d" * 64, "b" * 64, "c" * 64)]
    result = diff.diff_against({"certificates": before}, after)
    assert len(result["rotated"]) == 1
    assert result["rotated"][0]["from"] == "a" * 64
    assert result["rotated"][0]["to"] == "d" * 64


def test_diff_not_rotated_when_key_changes():
    before = [_row("a" * 64, "b" * 64, "c" * 64)]
    after = [_row("d" * 64, "e" * 64, "c" * 64)]
    result = diff.diff_against({"certificates": before}, after)
    assert result["rotated"] == []
    assert len(result["added"]) == 1
    assert len(result["removed"]) == 1


def test_diff_not_rotated_when_name_der_changes():
    before = [_row("a" * 64, "b" * 64, "c" * 64)]
    after = [_row("d" * 64, "b" * 64, "e" * 64)]
    result = diff.diff_against({"certificates": before}, after)
    assert result["rotated"] == []


def test_diff_surplus_falls_back_to_added():
    before = [_row("a" * 64, "b" * 64, "c" * 64)]
    after = [_row("d" * 64, "b" * 64, "c" * 64), _row("e" * 64, "b" * 64, "c" * 64)]
    result = diff.diff_against({"certificates": before}, after)
    assert len(result["rotated"]) == 1
    assert len(result["added"]) == 1
    assert len(result["removed"]) == 0


def test_diff_surplus_falls_back_to_removed():
    before = [_row("a" * 64, "b" * 64, "c" * 64), _row("f" * 64, "b" * 64, "c" * 64)]
    after = [_row("d" * 64, "b" * 64, "c" * 64)]
    result = diff.diff_against({"certificates": before}, after)
    assert len(result["rotated"]) == 1
    assert len(result["removed"]) == 1
    assert len(result["added"]) == 0


def test_diff_rejects_other_document_kinds():
    with pytest.raises(ValueError):
        diff.diff_against({"kind": "inventory", "certificates": []}, [])


def test_diff_rejects_non_list_certificates():
    with pytest.raises(ValueError):
        diff.diff_against({"certificates": "oops"}, [])


def test_diff_rejects_non_dict_baseline():
    with pytest.raises(ValueError):
        diff.diff_against([], [])


def test_diff_tolerates_missing_fields():
    result = diff.diff_against({"certificates": [{}]}, [])
    assert len(result["removed"]) == 1


def test_diff_is_deterministic():
    before = [_row("a" * 64, "b" * 64, "c" * 64)]
    after = [_row("d" * 64, "b" * 64, "c" * 64)]
    first = diff.diff_against({"certificates": before}, after)
    second = diff.diff_against({"certificates": before}, after)
    assert first == second


def test_report_emits_diff_record_when_baseline_given():
    subject = _report_subject(_ledger(certs=[_cert()]), baseline={"certificates": []})
    record = _records(subject, spec.RULE_DIFF)[0]
    assert len(record.evidence["added"]) == 1


def test_report_does_not_emit_diff_without_baseline():
    assert _records(_report_subject(_ledger(certs=[_cert()])), spec.RULE_DIFF) == []


# ================================================================== 模式入口
def test_inventory_mode_emits_the_built_ledger():
    record = _records({"mode": "inventory", "entries": [_entry_cert(), _entry_key()]}, spec.RULE_INVENTORY)[0]
    assert record.evidence["summary"]["certs"] == 1
    assert record.evidence["summary"]["keys"] == 1


def test_inventory_mode_requires_entries():
    with pytest.raises(ValueError):
        _evaluate({"mode": "inventory"})


def test_hygiene_mode_requires_ledger():
    with pytest.raises(ValueError):
        _evaluate({"mode": "hygiene", "as_of": AS_OF})


def test_hygiene_mode_requires_as_of():
    with pytest.raises(ValueError):
        _evaluate({"mode": "hygiene", "ledger": _ledger()})


def test_hygiene_mode_rejects_bad_as_of():
    with pytest.raises(ValueError):
        _evaluate(_hygiene(_ledger(), as_of="not-a-time"))


def test_hygiene_mode_validates_ledger_shape():
    with pytest.raises(ValueError):
        _evaluate(_hygiene({"certs": "oops"}))


def test_hygiene_mode_is_non_blocking_even_for_error_severity():
    assert _report(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)]))).exit_code() == EXIT_OK


def test_hygiene_mode_keeps_severity_in_evidence():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)]),), spec.RULE_EXPIRED)[0]
    assert record.evidence["severity"] == "ERROR"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "collect"})


def test_missing_mode_is_rejected():
    with pytest.raises(ValueError):
        _evaluate({"ledger": _ledger()})


def test_containers_mode_reports_truststore():
    subject = {
        "mode": "containers",
        "containers": [_container(entries=[{"entry_type": "certificate"}, {"entry_type": "privateKey"}])],
    }
    assert len(_records(subject, spec.RULE_CONTAINER_TRUSTSTORE)) == 1


def test_containers_mode_reports_open_credential():
    subject = {"mode": "containers", "containers": [_container(password="empty")]}
    assert len(_records(subject, spec.RULE_CONTAINER_OPEN_CREDENTIAL)) == 1


def test_containers_mode_includes_diagnostics():
    subject = {
        "mode": "containers",
        "containers": [],
        "diagnostics": [{"code": "SOURCE_UNAVAILABLE", "path": "macos"}],
    }
    assert len(_records(subject, spec.RULE_DIAGNOSTIC)) == 1


def test_containers_mode_requires_a_list():
    with pytest.raises(ValueError):
        _evaluate({"mode": "containers", "containers": {}})


def test_containers_mode_rejects_bad_diagnostics():
    with pytest.raises(ValueError):
        _evaluate({"mode": "containers", "containers": [], "diagnostics": "oops"})


def test_containers_mode_is_non_blocking():
    subject = {"mode": "containers", "containers": [_container(password="empty")]}
    assert _report(subject).exit_code() == EXIT_OK


def test_every_mode_has_a_summary_record():
    subjects = [
        _hygiene(_ledger()),
        _report_subject(_ledger()),
        {"mode": "containers", "containers": []},
        {"mode": "inventory", "entries": []},
    ]
    for subject in subjects:
        assert _records(subject, spec.RULE_LEDGER_SUMMARY) or _records(subject, spec.RULE_INVENTORY)


# ================================================================== CLI 与契约
def test_cli_sample_exits_zero(capsys):
    code = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["summary"]["blocking"] == 0


def test_cli_report_with_gate_exits_one(tmp_path, capsys):
    subject = _report_subject(_ledger(certs=[_cert(not_after=EXPIRED)]))
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    code = cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"])
    assert code == EXIT_BLOCKED


def test_cli_hygiene_with_error_severity_exits_zero(tmp_path, capsys):
    subject = _hygiene(_ledger(certs=[_cert(not_after=EXPIRED)]))
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_OK


def test_cli_unknown_mode_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "nope"}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"]) == EXIT_INPUT


def test_cli_missing_rule_exits_three(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_hygiene(_ledger()), ensure_ascii=False), encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--basis", str(empty), "--json"]) == EXIT_CONTRACT


def test_cli_basis_is_optional(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(_hygiene(_ledger()), ensure_ascii=False), encoding="utf-8")
    assert cli.main(["check", SLUG, "--input", str(path), "--json"]) == EXIT_OK


def test_cli_double_run_is_byte_identical(capsys):
    argv = ["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"]
    assert cli.main(argv) == EXIT_OK
    first = capsys.readouterr().out
    assert cli.main(argv) == EXIT_OK
    second = capsys.readouterr().out
    assert first == second


def test_cli_list_contains_the_organ(capsys):
    assert cli.main(["list"]) == EXIT_OK
    assert SLUG in capsys.readouterr().out


def test_record_ids_are_unique_in_report_mode():
    subject = _report_subject(
        _ledger(certs=[_cert(not_after=EXPIRED), _cert(fingerprint="e" * 64, spki="f" * 64, not_after=IN_WINDOW)])
    )
    ids = [record.id for record in _report(subject).records]
    assert len(ids) == len(set(ids))


def test_record_ids_are_unique_in_hygiene_mode():
    subject = _hygiene(_ledger(certs=[_cert(not_after=EXPIRED)], keys=[_key(posix_mode="644")]))
    ids = [record.id for record in _report(subject).records]
    assert len(ids) == len(set(ids))


def test_every_record_has_a_complete_basis_ref():
    for subject in (
        _hygiene(_ledger(certs=[_cert(not_after=EXPIRED)])),
        _report_subject(_ledger()),
        {"mode": "containers", "containers": [_container(password="empty")]},
        {"mode": "inventory", "entries": []},
    ):
        for record in _evaluate(subject):
            assert record.basis is not None
            assert record.basis.rule_version == "1"


def test_missing_rule_in_empty_basis_is_contract_violation():
    with pytest.raises(RuleMissing):
        _evaluate(_hygiene(_ledger()), basis=Basis.empty("1"))


def test_report_summary_is_deterministic():
    subject = _report_subject(_ledger(certs=[_cert(not_after=IN_WINDOW)], keys=[_key()]))
    first = _report(subject).as_dict()
    second = _report(subject).as_dict()
    assert first == second


# ================================================================== 器官契约（静态）
def _organ_sources():
    return sorted(path for path in ORGAN_DIR.glob("*.py"))


def test_organ_has_no_network_imports():
    forbidden = {"requests", "socket", "http", "urllib", "ftplib", "smtplib"}
    hits = []
    for path in _organ_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden:
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in forbidden:
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_does_not_import_cryptography():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "cryptography":
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "cryptography":
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_does_not_open_files_or_read_environment():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                hits.append((path.name, "open"))
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_read_the_wall_clock():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("now", "utcnow", "today", "time"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_spawn_subprocesses():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "subprocess":
                        hits.append((path.name, alias.name))
    assert hits == []


def test_organ_does_not_import_the_old_package():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "certledger":
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "certledger":
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_data_lives_under_package_data_directory():
    assert BASIS_PATH.parent == DATA_DIR
    assert THRESHOLDS_PATH.parent == DATA_DIR
    assert not list(ORGAN_DIR.glob("*.json"))


def test_organ_never_uses_lossy_codec_error_handlers():
    hits = []
    for path in _organ_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "errors"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value in ("replace", "ignore")
                ):
                    hits.append((path.name, keyword.value.value))
    assert hits == []


# ================================================================== 补充矩阵
@pytest.mark.parametrize(
    "block,expected",
    [
        ("hygiene.expired", "ERROR"),
        ("hygiene.expiring", "WARN"),
        ("hygiene.cliff", "WARN"),
        ("hygiene.weak_key.rsa", "WARN"),
        ("hygiene.weak_key.ec", "WARN"),
        ("hygiene.weak_sig", "WARN"),
        ("hygiene.nist_2031", "INFO"),
        ("hygiene.private_key", "WARN"),
        ("hygiene.permissions", "WARN"),
        ("hygiene.orphans", "INFO"),
        ("hygiene.duplicates", "INFO"),
        ("hygiene.container_truststore", "WARN"),
        ("hygiene.container_password", "INFO"),
    ],
)
def test_default_policy_levels(block, expected):
    assert hygiene.require(spec.DEFAULT_POLICY, "%s.level" % block) == expected


@pytest.mark.parametrize("code", sorted(spec.DIAGNOSTIC_CODES))
def test_default_diagnostic_codes_are_valid_levels(code):
    assert spec.DIAGNOSTIC_CODES[code] in spec.LEVELS


@pytest.mark.parametrize("code,severity", sorted(spec.DIAGNOSTIC_CODES.items()))
def test_diagnostic_code_severity_reaches_the_record(code, severity):
    record = _records(
        _hygiene(_ledger(diagnostics=[{"code": code, "path": "x"}])), spec.RULE_DIAGNOSTIC
    )[0]
    assert record.evidence["severity"] == severity


@pytest.mark.parametrize("mode", ["inventory", "hygiene", "report", "containers"])
def test_each_non_demo_mode_rejects_missing_required_fields(mode):
    with pytest.raises(ValueError):
        _evaluate({"mode": mode, "as_of": AS_OF})


@pytest.mark.parametrize("level,verdict", [("ERROR", WARN), ("WARN", WARN), ("INFO", INFO)])
def test_finding_verdict_mapping(level, verdict):
    assert audit._finding_verdict(level) == verdict


@pytest.mark.parametrize(
    "severity,threshold,expected",
    [
        ("ERROR", "ERROR", True),
        ("WARN", "ERROR", False),
        ("INFO", "ERROR", False),
        ("WARN", "WARN", True),
        ("INFO", "WARN", False),
        ("INFO", "INFO", True),
        ("WARN", "none", False),
        ("ERROR", "none", False),
    ],
)
def test_threshold_matrix(severity, threshold, expected):
    assert hygiene.threshold_reached([{"severity": severity}], threshold) is expected


@pytest.mark.parametrize(
    "term,offset",
    [
        (0, 0),
        (1, 86400),
        (10, 10 * 86400),
        (30, 30 * 86400),
    ],
)
def test_add_days_matrix(term, offset):
    assert timebase.add_days(AS_OF, term) == AS_OF + offset


@pytest.mark.parametrize("suffix", ["Z", "z", "+00:00", "-00:00"])
def test_iso_zero_offsets(suffix):
    assert timebase.parse_as_of("2030-03-17T17:46:40" + suffix).seconds == AS_OF


@pytest.mark.parametrize(
    "oid,name",
    [
        ("1.2.840.113549.1.1.2", "md2withrsaencryption"),
        ("1.2.840.113549.1.1.4", "md5withrsaencryption"),
        ("1.2.840.113549.1.1.5", "sha1withrsaencryption"),
        ("1.2.840.113549.1.1.11", "sha256withrsaencryption"),
        ("1.2.840.10045.4.1", "ecdsa-with-sha1"),
        ("1.2.840.10045.4.3.2", "ecdsa-with-sha256"),
    ],
)
def test_signature_name_matrix(oid, name):
    assert hygiene.signature_name(oid) == name


@pytest.mark.parametrize("mode", ["600", "640", "644", "660", "604"])
def test_permission_matrix(mode):
    records = _records(_hygiene(_ledger(keys=[_key(posix_mode=mode)])), spec.RULE_PERMISSION_TOO_OPEN)
    too_open = mode not in ("600", "640")
    assert bool(records) is too_open


@pytest.mark.parametrize("bits,weak", [(512, True), (1024, True), (2047, True), (2048, False), (3072, False), (4096, False)])
def test_rsa_bits_matrix(bits, weak):
    records = _records(_hygiene(_ledger(certs=[_cert(key_bits=bits)])), spec.RULE_WEAK_KEY_RSA)
    assert bool(records) is weak


@pytest.mark.parametrize("days_after,expiring", [(10, True), (20, True), (29, True), (30, False)])
def test_expiring_window_matrix(days_after, expiring):
    stamp = timebase.format_stamp(timebase.add_days(AS_OF, days_after))
    subject = _hygiene(_ledger(certs=[_cert(not_after=stamp)]))
    assert bool(_records(subject, spec.RULE_EXPIRING)) is expiring


@pytest.mark.parametrize("count,expected", [(1, False), (2, False), (3, True), (4, True)])
def test_cliff_count_matrix(count, expected):
    certs = [
        _cert(fingerprint=str(index) * 64, spki=str(index + 100) * 64, not_after=IN_WINDOW)
        for index in range(count)
    ]
    assert bool(_records(_hygiene(_ledger(certs=certs)), spec.RULE_EXPIRY_CLIFF)) is expected


def test_rule_ids_are_unique():
    assert len(spec.RULE_IDS) == len(set(spec.RULE_IDS))


def test_rule_ids_are_kebab_case():
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("cl-")
        assert rule_id == rule_id.lower()
        assert " " not in rule_id


def test_basis_sources_cite_a_recognisable_authority():
    allowed = ("RFC", "CA/B", "NIST", "SP 800", "本项目定义", "plan/", "target-map")
    for rule_id in BASIS.rule_ids():
        assert any(token in BASIS.require(rule_id).source for token in allowed), rule_id


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


def test_every_nominal_verdict_is_reachable():
    assert {spec.VERDICTS[rule_id] for rule_id in spec.RULE_IDS} == {ERROR, WARN, INFO}


def test_source_kind_order_is_declared():
    assert spec.SOURCE_KIND_ORDER == {"file": 0, "container": 1, "store": 2}


def test_severity_order_ranks_error_first():
    assert spec.SEVERITY_ORDER["ERROR"] < spec.SEVERITY_ORDER["WARN"] < spec.SEVERITY_ORDER["INFO"]


def test_diff_rows_are_sorted_by_fingerprint():
    ledger = _ledger(certs=[_cert(fingerprint="f" * 64, spki="1" * 64), _cert(fingerprint="0" * 64, spki="2" * 64)])
    rows = diff.certificate_rows(ledger)
    assert [row["fingerprint_sha256"][0] for row in rows] == ["0", "f"]


def test_diff_ignores_non_dict_certificates():
    assert diff.certificate_rows({"certs": ["oops", _cert()]}) != []


def test_report_summary_has_containers_count():
    record = _records(
        _report_subject(_ledger(containers=[_container()])), spec.RULE_LEDGER_SUMMARY
    )[0]
    assert record.evidence["containers"] == 1


def test_containers_mode_summary_counts_containers():
    record = _records(
        {"mode": "containers", "containers": [_container()]}, spec.RULE_LEDGER_SUMMARY
    )[0]
    assert record.evidence["containers"] == 1


def test_inventory_mode_does_not_judge_expiry():
    record = _records(
        {"mode": "inventory", "entries": [_entry_cert(not_after=EXPIRED)]}, spec.RULE_EXPIRED
    )
    assert record == []


def test_report_mode_without_expiring_certs_has_empty_table():
    record = _records(_report_subject(_ledger(certs=[_cert(not_after=FAR)])), spec.RULE_EXPIRY_TABLE)[0]
    assert record.evidence["expiries_total"] == 0


def test_expiry_table_rows_carry_fingerprint():
    record = _records(_report_subject(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_EXPIRY_TABLE)[0]
    assert record.evidence["rows"][0]["fingerprint"] == FP


def test_expired_and_expiring_can_coexist():
    certs = [
        _cert(fingerprint="a" * 64, spki="b" * 64, not_after=EXPIRED),
        _cert(fingerprint="c" * 64, spki="d" * 64, not_after=IN_WINDOW),
    ]
    subject = _hygiene(_ledger(certs=certs))
    assert len(_records(subject, spec.RULE_EXPIRED)) == 1
    assert len(_records(subject, spec.RULE_EXPIRING)) == 1


def test_hygiene_findings_carry_block_names():
    record = _records(_hygiene(_ledger(certs=[_cert(not_after=EXPIRED)])), spec.RULE_EXPIRED)[0]
    assert record.evidence["block"] == "hygiene.expired"


def test_containers_mode_does_not_judge_certificates():
    subject = {"mode": "containers", "containers": [_container()]}
    assert _records(subject, spec.RULE_EXPIRED) == []
    assert _records(subject, spec.RULE_ORPHAN_CERT) == []


def test_inventory_record_contains_the_ledger():
    record = _records({"mode": "inventory", "entries": [_entry_cert()]}, spec.RULE_INVENTORY)[0]
    assert record.evidence["certs"][0]["fingerprint_sha256"] == FP
    assert record.evidence["summary"]["paired"] == 0


def test_inventory_section_keys_are_the_ledger_contract():
    record = _records({"mode": "inventory", "entries": []}, spec.RULE_INVENTORY)[0]
    assert set(record.evidence) == {
        "schema_version",
        "kind",
        "certs",
        "keys",
        "containers",
        "diagnostics",
        "summary",
    }
    assert record.evidence["kind"] == "inventory"


def test_policy_version_is_carried_in_defaults():
    assert hygiene.require(spec.DEFAULT_POLICY, "policy_version") == SETTINGS["policy_version"]


def test_thresholds_modes_match_runtime():
    assert tuple(SETTINGS["modes"]) == spec.MODES


def test_thresholds_organ_name_matches_slug():
    assert SETTINGS["organ"] == SLUG