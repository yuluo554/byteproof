"""byteproof 内核契约测试（Stage 1 · 骨架）。

锁四件事：
1. 无规则依据不下 ``error``（构造即拦，不靠文档）；
2. 依据缺版本 -> 降级 ``info`` + message 写明缺失项（SKELETON-SPEC §4.2）；
3. 账本输出确定性（同一输入两次运行字节一致，无时间戳/绝对路径）；
4. 退出码 0/1/2/3 的边界（含「规则包缺失 -> 3」这条 §5 口径）。
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.core import (  # noqa: E402
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    WARN,
    Basis,
    ContractError,
    Pack,
    Record,
    Report,
    Rule,
    RuleMissing,
    RuleRef,
    all_packs,
    get,
    register,
)

REF = RuleRef(rule_id="demo-rule", rule_version="2026.1", source="示例规范 §1")


# --------------------------------------------------------------------------
# 注册表
# --------------------------------------------------------------------------
def _noop_evaluate(subject, basis):
    return ()


def test_register_and_get_pack():
    pack = Pack(
        slug="probe-alpha",
        version="0.0.1",
        summary="测试用器官",
        input_fields=("blob",),
        evaluate=_noop_evaluate,
    )
    assert register(pack) is pack
    assert get("probe-alpha") is pack
    slugs = [p.slug for p in all_packs()]
    assert slugs == sorted(slugs), "all_packs 必须按 slug 排序"
    assert "probe-alpha" in slugs


def test_duplicate_register_is_rejected():
    register(
        Pack(slug="probe-dup", version="1", summary="x", input_fields=("a",), evaluate=_noop_evaluate)
    )
    with pytest.raises(ValueError):
        register(
            Pack(
                slug="probe-dup",
                version="2",
                summary="重复",
                input_fields=("a",),
                evaluate=_noop_evaluate,
            )
        )


def test_pack_rejects_bad_slug_and_empty_fields():
    with pytest.raises(ValueError):
        Pack(slug="Bad Slug", version="1", summary="x", input_fields=("a",), evaluate=_noop_evaluate)
    with pytest.raises(ValueError):
        Pack(slug="probe-beta", version="1", summary="x", input_fields=(), evaluate=_noop_evaluate)
    with pytest.raises(ValueError):
        Pack(slug="probe-beta", version="", summary="x", input_fields=("a",), evaluate=_noop_evaluate)


def test_missing_pack_is_reported():
    from byteproof.core import PackMissing

    with pytest.raises(PackMissing):
        get("no-such-pack")


def test_builtin_manifest_is_sorted_and_loadable():
    """器官清单必须字典序（输出可复现），且 ``load_builtin()`` 不因空表报错。"""
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)
    load_builtin()


# --------------------------------------------------------------------------
# 账本：无依据不下 error + 缺版本降级
# --------------------------------------------------------------------------
def test_error_without_basis_is_contract_violation():
    with pytest.raises(ContractError):
        Record(rule_id="r1", verdict=ERROR, message="字节流不合法")


def test_warn_and_info_without_basis_are_allowed():
    warn = Record(rule_id="r1", verdict=WARN, message="可疑但未定级")
    info = Record(rule_id="r2", verdict=INFO, message="仅提示")
    assert warn.basis is None and info.basis is None


def test_illegal_verdict_is_rejected():
    with pytest.raises(ContractError):
        Record(rule_id="r1", verdict="maybe", message="x", basis=REF)


def test_rule_ref_rejects_empty_rule_id():
    with pytest.raises(ContractError):
        RuleRef(rule_id="", rule_version="2026.1")


def test_missing_rule_version_downgrades_to_info():
    """§4.2：依据在、但缺版本 -> 降级 info，且 message 必须写明缺失项。"""
    record = Record(
        rule_id="r1",
        verdict=ERROR,
        message="缺版本也要拦住",
        basis=RuleRef(rule_id="demo-rule", rule_version=""),
    )
    assert record.verdict == INFO
    assert "rule_version" in record.message
    assert "降级" in record.message


def test_record_id_is_derived_from_rule_and_path():
    first = Record(rule_id="r1", verdict=WARN, message="a", path="a.bin")
    second = Record(rule_id="r1", verdict=WARN, message="b", path="a.bin")
    third = Record(rule_id="r1", verdict=WARN, message="a", path="b.bin")
    assert first.id == "r1@a.bin" == second.id
    assert third.id == "r1@b.bin"
    assert Record(rule_id="r1", verdict=INFO, message="x").id == "r1@-"


def test_report_is_deterministic_and_sorted():
    records = (
        Record(rule_id="r2", verdict=WARN, message="第二条", basis=REF),
        Record(rule_id="r1", verdict=ERROR, message="第一条", basis=REF, path="x"),
    )
    report = Report(product="byteproof", organ="o", organ_version="1", subject="s", records=records)
    assert [r.rule_id for r in report.records] == ["r1", "r2"]
    first = json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=False)
    second = json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=False)
    assert first == second
    assert set(report.as_dict()) == {
        "product",
        "organ",
        "organ_version",
        "subject",
        "summary",
        "records",
    }


def test_report_exit_code_and_summary():
    blocking = Report(
        product="byteproof",
        organ="o",
        organ_version="1",
        subject="s",
        records=(Record(rule_id="r1", verdict=ERROR, message="x", basis=REF),),
    )
    assert blocking.exit_code() == EXIT_BLOCKED
    assert blocking.summary()["blocking"] == 1

    clean = Report(
        product="byteproof",
        organ="o",
        organ_version="1",
        subject="s",
        records=(
            Record(rule_id="r1", verdict=WARN, message="x", basis=REF),
            Record(rule_id="r2", verdict=INFO, message="y"),
        ),
    )
    assert clean.exit_code() == EXIT_OK, "warn/info 不阻断"
    assert clean.summary()["blocking"] == 0
    assert clean.summary()["verdicts"] == {ERROR: 0, WARN: 1, INFO: 1}


def test_report_rejects_duplicate_record_ids():
    record = Record(rule_id="r1", verdict=WARN, message="x", path="same")
    with pytest.raises(ContractError):
        Report(product="byteproof", organ="o", organ_version="1", subject="s", records=(record, record))


# --------------------------------------------------------------------------
# 规则包
# --------------------------------------------------------------------------
def test_basis_from_dict_and_ref():
    basis = Basis.from_dict(
        {
            "version": "2026.1",
            "rules": [{"rule_id": "demo-rule", "title": "示例规则", "source": "示例规范 §1"}],
        }
    )
    assert len(basis) == 1
    ref = basis.ref("demo-rule")
    assert ref.rule_version == "2026.1", "缺省版本应回落到规则包版本"
    assert ref.source == "示例规范 §1"


def test_rule_keeps_its_own_version():
    """规则可以独立于包版本演进：取依据时如实回报它自己的版本。"""
    basis = Basis(version="2026.1", rules=(Rule(rule_id="demo-rule", version="2025.3"),))
    assert basis.ref("demo-rule").rule_version == "2025.3"


def test_basis_missing_rule():
    basis = Basis.empty(version="2026.1")
    with pytest.raises(RuleMissing):
        basis.ref("demo-rule")


def test_basis_rejects_empty_version_and_duplicates():
    with pytest.raises(ContractError):
        Basis(version="")
    with pytest.raises(ContractError):
        Basis(version="2026.1", rules=(Rule(rule_id="c1"), Rule(rule_id="c1")))


def test_basis_as_dict_roundtrip():
    basis = Basis(version="2026.1", rules=(Rule(rule_id="c1", title="t"),))
    assert Basis.from_dict(basis.as_dict()).rule_ids() == ["c1"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _probe_evaluate(subject, basis):
    rule = basis.rule("demo-rule")
    if rule is None:
        return (Record(rule_id="demo-rule", verdict=INFO, message="规则包缺 demo-rule"),)
    hit = "BAD" in subject.get("blob", "")
    return (
        Record(
            rule_id="demo-rule",
            verdict=ERROR if hit else INFO,
            message="命中坏字节" if hit else "未命中坏字节",
            basis=basis.ref("demo-rule"),
            path=subject.get("path", ""),
            evidence={"matched": hit},
        ),
    )


def _strict_evaluate(subject, basis):
    """规则包是硬依赖：取不到规则就让 ``RuleMissing`` 冒到 CLI（退出码 3）。"""
    return (
        Record(
            rule_id="demo-rule",
            verdict=WARN,
            message="x",
            basis=basis.ref("demo-rule"),
        ),
    )


@pytest.fixture(scope="module", autouse=True)
def probe_pack():
    register(
        Pack(
            slug="demo-probe",
            version="0.0.1",
            summary="契约测试用器官（非真实规则）",
            input_fields=("blob",),
            evaluate=_probe_evaluate,
        )
    )
    register(
        Pack(
            slug="demo-strict",
            version="0.0.1",
            summary="硬依赖规则包的器官（取不到规则即违约）",
            input_fields=("blob",),
            evaluate=_strict_evaluate,
        )
    )


def test_cli_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert "byteproof" in capsys.readouterr().out


def test_cli_list(capsys):
    assert cli.main(["list"]) == EXIT_OK
    assert "demo-probe" in capsys.readouterr().out
    assert cli.main(["list", "--json"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)


def test_cli_unknown_pack_is_contract_error(capsys, tmp_path):
    target = tmp_path / "input.json"
    target.write_text(json.dumps({"blob": "x"}), encoding="utf-8")
    assert cli.main(["check", "no-such", "--input", str(target)]) == EXIT_CONTRACT
    assert "PackMissing" in capsys.readouterr().err


def test_cli_missing_input_file_is_input_error(capsys, tmp_path):
    assert cli.main(["check", "demo-probe", "--input", str(tmp_path / "nope.json")]) == EXIT_INPUT


def test_cli_missing_required_field_is_input_error(capsys, tmp_path):
    target = tmp_path / "input.json"
    target.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    assert cli.main(["check", "demo-probe", "--input", str(target)]) == EXIT_INPUT
    assert "blob" in capsys.readouterr().err


def test_cli_rule_missing_is_contract_error(capsys, tmp_path):
    """§5：规则包缺失（器官要的规则不在包里）-> 退出码 3，不是 2。"""
    target = tmp_path / "input.json"
    target.write_text(json.dumps({"blob": "BAD"}), encoding="utf-8")
    pack_path = tmp_path / "rules.json"
    pack_path.write_text(json.dumps({"version": "2026.1", "rules": []}), encoding="utf-8")
    assert (
        cli.main(["check", "demo-strict", "--input", str(target), "--basis", str(pack_path)])
        == EXIT_CONTRACT
    )
    assert "RuleMissing" in capsys.readouterr().err


def test_cli_basis_without_version_is_contract_error(capsys, tmp_path):
    target = tmp_path / "input.json"
    target.write_text(json.dumps({"blob": "BAD"}), encoding="utf-8")
    pack_path = tmp_path / "rules.json"
    pack_path.write_text(json.dumps({"rules": []}), encoding="utf-8")
    assert cli.main(["check", "demo-probe", "--input", str(target), "--basis", str(pack_path)]) == EXIT_CONTRACT
    assert "规则包版本为空" in capsys.readouterr().err


def test_cli_end_to_end_blocking_and_deterministic(capsys, tmp_path):
    target = tmp_path / "input.json"
    target.write_text(json.dumps({"blob": "BAD bytes"}), encoding="utf-8")
    pack_path = tmp_path / "rules.json"
    pack_path.write_text(
        json.dumps(
            {"version": "2026.1", "rules": [{"rule_id": "demo-rule", "source": "示例规范 §1"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert (
        cli.main(["check", "demo-probe", "--input", str(target), "--basis", str(pack_path), "--json"])
        == EXIT_BLOCKED
    )
    first = capsys.readouterr().out
    assert str(tmp_path) not in first, "输出不得含绝对路径"
    payload = json.loads(first)
    assert payload["summary"]["blocking"] == 1
    assert payload["records"][0]["basis_ref"]["rule_id"] == "demo-rule"
    assert payload["records"][0]["basis_ref"]["rule_version"] == "2026.1"

    cli.main(["check", "demo-probe", "--input", str(target), "--basis", str(pack_path), "--json"])
    assert capsys.readouterr().out == first, "同一输入两次运行必须字节一致"


def test_cli_stdin_input(capsys, tmp_path, monkeypatch):
    pack_path = tmp_path / "rules.json"
    pack_path.write_text(
        json.dumps({"version": "2026.1", "rules": [{"rule_id": "demo-rule"}]}), encoding="utf-8"
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"blob": "BAD"})))
    assert (
        cli.main(["check", "demo-probe", "--input", "-", "--basis", str(pack_path), "--json"])
        == EXIT_BLOCKED
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "<stdin>"


def test_cli_without_basis_degrades_to_info(capsys, tmp_path):
    target = tmp_path / "input.json"
    target.write_text(json.dumps({"blob": "BAD bytes"}), encoding="utf-8")
    assert cli.main(["check", "demo-probe", "--input", str(target)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "info" in out and "缺 demo-rule" in out