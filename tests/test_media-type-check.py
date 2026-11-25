"""``media-type-check`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**判定仍然在、规则 ID 仍然指向同一条条款**。
规则 ID（``MC-H07`` 等）与 severity 原样保留；``class`` 三值（hard/diff/gray）不搬 ——
它描述的是"证据强度"，而账本要的是"阻不阻断"（severity -> verdict 的唯一翻译点在 ``spec``）。

**没迁的部分逐条写在 ``docs/media-type-check.md`` 的处置表里**（raw 字节扫描层、mbox 容器变体、
``MC-B06`` 两棵候选树分歧、报告渲染、CLI、golden 夹具、打包门）。

判定层口径（ORGAN-PLAYBOOK §3.0）：旧仓 17 个判定层文件实跑 **X = 562 passed（+1 skipped）**。
"""

from __future__ import annotations

import ast
import io
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES  # noqa: E402
from byteproof.auditors.media_type_check import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    detectors,
    spec,
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
    Record,
    RuleMissing,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "media-type-check"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "media_type_check"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "media-type-check.basis.json"
THRESHOLDS_PATH = DATA_DIR / "media-type-check.thresholds.json"

BASIS = Basis.from_json(str(BASIS_PATH))


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _part(path="0", content_type="text/plain", boundary=None, headers=(), body=""):
    return {
        "path": path,
        "content_type": content_type,
        "boundary": boundary,
        "headers": [{"name": name, "value": value} for name, value in headers],
        "body": body,
    }


def _evaluate(parts, basis=None, **params):
    payload = {"parts": parts}
    if params:
        payload["params"] = params
    return tuple(audit.evaluate(payload, BASIS if basis is None else basis))


def _with_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


def _rule_ids(records):
    return sorted({record.rule_id for record in records})


def _iter_floats(node, path="$"):
    if isinstance(node, float):
        yield path
        return
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_floats(value, "%s.%s" % (path, key))
        return
    if isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            yield from _iter_floats(value, "%s[%d]" % (path, index))


def _ew(size):
    """一个长度可控的 encoded-word（B 编码，encoded-text 为 ``A`` × size）。"""
    return "=?utf-8?B?%s?=" % ("A" * size)


# ---------------------------------------------------------------------------
# 随包静态数据
# ---------------------------------------------------------------------------
class TestShippedTables:
    def test_the_basis_file_parses_with_a_version(self):
        assert BASIS.version == "1"
        assert len(BASIS) == len(spec.RULE_IDS)

    def test_the_basis_covers_every_rule_the_organ_can_emit(self):
        assert sorted(set(spec.RULE_IDS) - set(BASIS.rule_ids())) == []

    def test_the_basis_has_no_rule_the_organ_never_uses(self):
        assert sorted(set(BASIS.rule_ids()) - set(spec.RULE_IDS)) == []

    def test_every_rule_carries_a_clause_and_a_detector_sentence(self):
        for rule_id in BASIS.rule_ids():
            rule = BASIS.rule(rule_id)
            assert rule.title and rule.source and rule.text, rule_id

    def test_a_rule_without_a_clause_says_none_by_design(self):
        # 旧仓 D8：rfc 不得为空；"没有条款"必须显式写出来
        for rule_id in spec.RULE_IDS:
            assert spec.RFC_BY_RULE[rule_id].strip()

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_cites_a_clause_or_none_by_design(self, rule_id):
        source = spec.RFC_BY_RULE[rule_id]
        assert source == "none-by-design" or source.startswith("RFC ")

    def test_the_rule_ids_are_sorted_in_the_basis_file(self):
        payload = json.loads(BASIS_PATH.read_text(encoding="utf-8"))
        ids = [item["rule_id"] for item in payload["rules"]]
        assert ids == sorted(ids)

    def test_the_thresholds_file_pins_the_defaults(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["params"] == spec.resolve_params()

    def test_the_thresholds_file_pins_the_severity_and_verdict_tables(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["severity"] == spec.SEVERITY_BY_RULE
        assert payload["verdicts"] == spec.VERDICT_BY_RULE
        assert payload["verdict_by_severity"] == spec.VERDICT_BY_SEVERITY

    def test_the_thresholds_file_pins_the_versions(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["params_version"] == spec.PARAMS_VERSION
        assert payload["rules_version"] == spec.RULES_VERSION
        assert payload["quant_decimals"] == spec.QUANT_DECIMALS

    def test_the_data_files_are_declared_as_package_data(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert '"data/*.json"' in text
        assert BASIS_PATH.is_file() and THRESHOLDS_PATH.is_file()

    def test_the_organ_is_in_the_builtin_manifest(self):
        assert "media_type_check" in BUILTIN_MODULES
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_the_pack_declares_the_artifact_field(self):
        assert PACK.slug == SLUG
        assert PACK.version == ORGAN_VERSION
        assert PACK.input_fields == ("parts",)

    def test_the_pack_is_queryable_from_the_registry(self):
        assert get(SLUG) is PACK

    def test_the_rule_ids_keep_the_upstream_namespace(self):
        # 旧仓规则 ID 是 data/rfc-ledger.json 的索引键，改名会断掉"账本反查条款"这条链
        for rule_id in spec.RULE_IDS:
            assert rule_id.startswith("MC-")
            assert rule_id[3] in "BHTAC"


class TestSeverityMapping:
    """severity -> verdict 的**唯一**翻译点。"""

    @pytest.mark.parametrize("severity,verdict", sorted(spec.VERDICT_BY_SEVERITY.items()))
    def test_the_mapping_is_the_documented_one(self, severity, verdict):
        assert spec.VERDICT_BY_SEVERITY[severity] == verdict

    def test_blocker_and_major_both_block(self):
        assert spec.VERDICT_BY_SEVERITY["blocker"] == ERROR
        assert spec.VERDICT_BY_SEVERITY["major"] == ERROR

    def test_minor_is_a_warning_and_note_is_a_trace(self):
        assert spec.VERDICT_BY_SEVERITY["minor"] == WARN
        assert spec.VERDICT_BY_SEVERITY["note"] == INFO

    def test_every_severity_maps_into_the_three_verdicts(self):
        assert set(spec.VERDICT_BY_SEVERITY.values()) == {ERROR, WARN, INFO}

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_derives_its_verdict_from_its_severity(self, rule_id):
        assert spec.verdict_for(rule_id) == spec.VERDICT_BY_SEVERITY[spec.severity_for(rule_id)]

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_has_one_of_the_four_severities(self, rule_id):
        assert spec.severity_for(rule_id) in ("blocker", "major", "minor", "note")

    def test_an_unknown_rule_has_no_verdict(self):
        with pytest.raises(ValueError):
            spec.verdict_for("MC-Z99")

    def test_an_unknown_rule_has_no_severity(self):
        with pytest.raises(ValueError):
            spec.severity_for("MC-Z99")


# ---------------------------------------------------------------------------
# 规则 × 触发 / 静默 / 等级 / 依据
# ---------------------------------------------------------------------------
TRIGGERS = {
    "MC-B01": (_part(content_type="multipart/mixed"), {}),
    "MC-B02": (_part(content_type="multipart/mixed", boundary="b" * 71), {}),
    "MC-B09": (_part(path="0.1.2"), {"max_depth": 2}),
    "MC-H01": (_part(headers=(("Subject", _ew(70)),)), {}),
    "MC-H02": (_part(headers=(("Subject", _ew(6) + "b" * 60),)), {}),
    "MC-H03": (_part(headers=(("Subject", "=?utf-8?B?AA AA?="),)), {}),
    "MC-H07": (_part(headers=(("X-Long", "x" * 1000),)), {}),
    "MC-H08": (_part(headers=(("Subject", "中文标题"),)), {}),
    "MC-T02": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJD==="), {}),
    "MC-T03": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJDQ"), {}),
    "MC-T04": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QU$D"), {}),
    "MC-T05": (_part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="A" * 77), {}),
    "MC-T06": (_part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="abc="), {}),
    "MC-T07": (_part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="a=ZZ"), {}),
    "MC-T08": (_part(headers=(("Content-Transfer-Encoding", "x-unknown"),), body="abc"), {}),
    "MC-T09": (_part(headers=(("Content-Transfer-Encoding", "7bit"),), body="A" * 999), {}),
    "MC-T10": (_part(body="héllo"), {}),
    "MC-A02": (
        _part(
            content_type="text/plain; name=\"a.txt\"",
            headers=(
                ("Content-Type", "text/plain; name=\"a.txt\""),
                ("Content-Disposition", "attachment; filename=\"b.txt\""),
            ),
        ),
        {},
    ),
    "MC-A03": (_part(headers=(("Content-Disposition", "attachment"),)), {}),
    "MC-A07": (_part(headers=(("Content-Disposition", "inline"),)), {}),
}

QUIETS = {
    "MC-B01": (_part(content_type="multipart/mixed", boundary="b1"), {}),
    "MC-B02": (_part(content_type="multipart/mixed", boundary="b" * 70), {}),
    "MC-B09": (_part(path="0.1"), {"max_depth": 2}),
    "MC-H01": (_part(headers=(("Subject", _ew(6)),)), {}),
    "MC-H02": (_part(headers=(("Subject", _ew(6)),)), {}),
    "MC-H03": (_part(headers=(("Subject", _ew(6)),)), {}),
    "MC-H07": (_part(headers=(("X-Long", "x" * 900),)), {}),
    "MC-H08": (_part(headers=(("Subject", "plain ascii"),)), {}),
    "MC-T02": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJD"), {}),
    "MC-T03": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJDRA=="), {}),
    "MC-T04": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJDRA=="), {}),
    "MC-T05": (_part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="A" * 76), {}),
    "MC-T06": (
        _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="abc=\n"),
        {},
    ),
    "MC-T07": (_part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="a=3D"), {}),
    "MC-T08": (_part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJD"), {}),
    "MC-T09": (_part(headers=(("Content-Transfer-Encoding", "7bit"),), body="A" * 998), {}),
    "MC-T10": (_part(headers=(("Content-Transfer-Encoding", "7bit"),), body="hello"), {}),
    "MC-A02": (
        _part(
            content_type="text/plain; name=\"a.txt\"",
            headers=(
                ("Content-Type", "text/plain; name=\"a.txt\""),
                ("Content-Disposition", "attachment; filename=\"a.txt\""),
            ),
        ),
        {},
    ),
    "MC-A03": (_part(headers=(("Content-Disposition", "attachment; filename=\"a.txt\""),)), {}),
    "MC-A07": (
        _part(
            headers=(
                ("Content-Disposition", "inline; filename=\"a.png\""),
                ("Content-ID", "<a@example.com>"),
            )
        ),
        {},
    ),
}


class TestRuleMatrix:
    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_has_a_trigger_case(self, rule_id):
        assert rule_id in TRIGGERS

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_has_a_quiet_case(self, rule_id):
        assert rule_id in QUIETS

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_the_rule_fires_on_its_trigger(self, rule_id):
        part, params = TRIGGERS[rule_id]
        assert _with_rule(_evaluate([part], **params), rule_id), rule_id

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_the_rule_stays_silent_on_its_quiet_case(self, rule_id):
        part, params = QUIETS[rule_id]
        assert _with_rule(_evaluate([part], **params), rule_id) == [], rule_id

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_the_rule_reports_its_documented_verdict(self, rule_id):
        part, params = TRIGGERS[rule_id]
        for record in _with_rule(_evaluate([part], **params), rule_id):
            assert record.verdict == spec.verdict_for(rule_id)

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_the_rule_cites_its_own_basis(self, rule_id):
        part, params = TRIGGERS[rule_id]
        for record in _with_rule(_evaluate([part], **params), rule_id):
            assert record.basis.rule_id == rule_id
            assert record.basis.source == spec.RFC_BY_RULE[rule_id]
            assert record.basis.rule_version == BASIS.version

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_the_evidence_carries_the_severity_and_the_part(self, rule_id):
        part, params = TRIGGERS[rule_id]
        for record in _with_rule(_evaluate([part], **params), rule_id):
            assert record.evidence["severity"] == spec.severity_for(rule_id)
            assert record.evidence["part_path"] == part["path"]
            assert record.evidence["content_type"] == part["content_type"]


# ---------------------------------------------------------------------------
# 数值边界
# ---------------------------------------------------------------------------
class TestHeaderWidthBoundary:
    @pytest.mark.parametrize("size", (994, 995, 996, 997, 998, 999, 1000))
    def test_the_header_line_limit_is_where_the_rule_says(self, size):
        # 行 = "X-Long" + ": " + value -> 8 + size octets
        part = _part(headers=(("X-Long", "x" * (size - 8)),))
        hits = _with_rule(_evaluate([part]), "MC-H07")
        assert len(hits) == (1 if size > 998 else 0)

    @pytest.mark.parametrize("size", (6, 20, 40, 60, 65, 66, 70))
    def test_the_encoded_word_limit(self, size):
        part = _part(headers=(("Subject", _ew(size)),))
        hits = _with_rule(_evaluate([part]), "MC-H01")
        # len("=?utf-8?B?" + text + "?=") = 10 + size + 2
        assert len(hits) == (1 if 12 + size > 75 else 0)

    @pytest.mark.parametrize("pad", (0, 10, 54, 58, 60))
    def test_the_encoded_header_line_limit(self, pad):
        part = _part(headers=(("Subject", _ew(6) + "b" * pad),))
        line = len("Subject") + 2 + len(_ew(6)) + pad
        hits = _with_rule(_evaluate([part]), "MC-H02")
        assert len(hits) == (1 if line > 76 else 0)

    def test_a_wide_line_does_not_also_produce_encoded_word_findings(self):
        # 旧仓纪律：MC-H07 先于 encoded-word 检查
        part = _part(headers=(("Subject", _ew(1000)),))
        records = _evaluate([part])
        assert _with_rule(records, "MC-H07")
        assert _with_rule(records, "MC-H01") == []

    def test_the_header_limit_can_be_lowered_by_a_parameter(self):
        part = _part(headers=(("X-Long", "x" * 60),))
        assert _with_rule(_evaluate([part], max_header_line_octets=1000), "MC-H07") == []
        assert _with_rule(_evaluate([part], max_header_line_octets=50), "MC-H07") != []


class TestBoundaryWidth:
    @pytest.mark.parametrize("length", (1, 40, 68, 69, 70, 71, 72))
    def test_the_boundary_limit(self, length):
        part = _part(content_type="multipart/mixed", boundary="b" * length)
        assert len(_with_rule(_evaluate([part]), "MC-B02")) == (1 if length > 70 else 0)

    @pytest.mark.parametrize("depth,limit", ((1, 1), (2, 1), (2, 2), (3, 2), (3, 3), (4, 3)))
    def test_the_depth_limit(self, depth, limit):
        path = ".".join(["0"] * depth)
        part = _part(path=path)
        assert len(_with_rule(_evaluate([part], max_depth=limit), "MC-B09")) == (
            1 if depth > limit else 0
        )

    @pytest.mark.parametrize("path", ("0", "0.1", "0.1.2", "msg#3/0.1", "msg#3/0.1.2.3"))
    def test_the_depth_of_a_container_path(self, path):
        expected = {"0": 1, "0.1": 2, "0.1.2": 3, "msg#3/0.1": 2, "msg#3/0.1.2.3": 4}[path]
        assert detectors._depth_of(path) == expected


class TestEncodedWordBoundary:
    @pytest.mark.parametrize("payload", ("AA BB", "AA\tBB", " AA", "AA ", "A A A"))
    def test_whitespace_inside_an_encoded_word_is_flagged(self, payload):
        part = _part(headers=(("Subject", "=?utf-8?B?%s?=" % payload),))
        assert _with_rule(_evaluate([part]), "MC-H03") != []

    @pytest.mark.parametrize("payload", ("AAAA", "QUJDRA==", "AAAABBBB"))
    def test_whitespace_free_encoded_words_are_clean(self, payload):
        part = _part(headers=(("Subject", "=?utf-8?B?%s?=" % payload),))
        assert _with_rule(_evaluate([part]), "MC-H03") == []

    @pytest.mark.parametrize(
        "value", ("=?utf-8?B?QUJD?=", "plain", "=?utf-8?Q?abc?=", "=?iso-8859-1?B?QUJD?=")
    )
    def test_encoded_words_are_recognised(self, value):
        assert len(detectors._encoded_words(value)) == (0 if value == "plain" else 1)

    @pytest.mark.parametrize("count", (1, 2, 3, 4))
    def test_multiple_encoded_words_are_all_counted(self, count):
        value = " ".join([_ew(6)] * count)
        assert len(detectors._encoded_words(value)) == count

    @pytest.mark.parametrize("codepoint", (0x80, 0x4E2D, 0x1F600))
    def test_unencoded_non_ascii_is_flagged(self, codepoint):
        part = _part(headers=(("Subject", "x" + chr(codepoint)),))
        hits = _with_rule(_evaluate([part]), "MC-H08")
        assert hits and hits[0].evidence["first_codepoint"] == codepoint

    def test_an_encoded_non_ascii_is_not_flagged(self):
        part = _part(headers=(("Subject", "=?utf-8?B?5Lit5paH?="),))
        assert _with_rule(_evaluate([part]), "MC-H08") == []


class TestBase64Rules:
    @pytest.mark.parametrize(
        "body,padding_ok",
        (
            ("QUJD", True),
            ("QUJDRA==", True),
            ("QUJDREVG", True),
            ("QUJD===", False),
            ("QUJD====", False),
            ("QU=JD", False),
        ),
    )
    def test_the_padding_rule(self, body, padding_ok):
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body=body)
        assert (not _with_rule(_evaluate([part]), "MC-T02")) == padding_ok

    @pytest.mark.parametrize("length", (4, 8, 12, 16, 20, 3, 5, 6, 7))
    def test_the_length_rule(self, length):
        body = "A" * length
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body=body)
        assert len(_with_rule(_evaluate([part]), "MC-T03")) == (1 if length % 4 else 0)

    @pytest.mark.parametrize("char", ("$", "-", "_", ".", "中", "!"))
    def test_the_alphabet_rule(self, char):
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body="QU%sD" % char)
        assert _with_rule(_evaluate([part]), "MC-T04") != []

    @pytest.mark.parametrize("char", ("+", "/", "="))
    def test_the_alphabet_accepts_the_documented_extras(self, char):
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body="QU%sD" % char)
        assert _with_rule(_evaluate([part]), "MC-T04") == []

    def test_whitespace_in_base64_is_ignored(self):
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body="QUJD\nRA==")
        assert _with_rule(_evaluate([part]), "MC-T04") == []
        assert _with_rule(_evaluate([part]), "MC-T03") == []

    def test_a_non_alphabet_character_stops_the_padding_and_length_checks(self):
        # 旧仓纪律：T04 命中后不再用它的字节数去推"填充错没错"
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body="QU$D===")
        records = _evaluate([part])
        assert _with_rule(records, "MC-T04")
        assert _with_rule(records, "MC-T02") == []
        assert _with_rule(records, "MC-T03") == []


class TestQuotedPrintableRules:
    @pytest.mark.parametrize("length", (70, 75, 76, 77, 80))
    def test_the_line_width_rule(self, length):
        part = _part(
            headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="A" * length
        )
        assert len(_with_rule(_evaluate([part]), "MC-T05")) == (1 if length > 76 else 0)

    @pytest.mark.parametrize("tail", ("abc=", "abc=\n", "abc", "="))
    def test_the_dangling_soft_break_rule(self, tail):
        part = _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body=tail)
        fired = bool(_with_rule(_evaluate([part]), "MC-T06"))
        assert fired == (tail == "abc=" or tail == "=")

    @pytest.mark.parametrize("escapes,bad", (("=3D", False), ("=0A", False), ("=zz", True), ("=Z", True), ("=3", True)))
    def test_the_escape_rule(self, escapes, bad):
        part = _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body=escapes)
        assert bool(_with_rule(_evaluate([part]), "MC-T07")) == bad

    def test_a_soft_break_at_the_end_of_a_line_is_not_an_invalid_escape(self):
        body = "abc=\ndef"
        part = _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body=body)
        assert _with_rule(_evaluate([part]), "MC-T07") == []

    def test_a_line_with_an_invalid_escape_is_not_also_measured_for_width(self):
        body = "=" * 100
        part = _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body=body)
        records = _evaluate([part])
        assert _with_rule(records, "MC-T07")
        assert _with_rule(records, "MC-T05") == []


class TestTransferEncodingRules:
    @pytest.mark.parametrize(
        "value", ("7bit", "8bit", "binary", "quoted-printable", "base64", "BASE64")
    )
    def test_a_known_cte_is_accepted(self, value):
        part = _part(headers=(("Content-Transfer-Encoding", value),), body="abc")
        assert _with_rule(_evaluate([part]), "MC-T08") == []

    @pytest.mark.parametrize("value", ("x-uuencode", "9bit", "quoted_printable", "b64", ""))
    def test_an_unknown_cte_is_a_trace_only(self, value):
        part = _part(headers=(("Content-Transfer-Encoding", value),), body="abc")
        hits = _with_rule(_evaluate([part]), "MC-T08")
        assert len(hits) == 1
        assert hits[0].verdict == INFO

    @pytest.mark.parametrize("body", ("hello", "abc", "ASCIIDOC"))
    def test_ascii_without_a_cte_is_clean(self, body):
        part = _part(body=body)
        assert _with_rule(_evaluate([part]), "MC-T10") == []

    @pytest.mark.parametrize("body", ("héllo", "中文", "caf\u00e9"))
    def test_eight_bit_without_a_cte_is_a_trace(self, body):
        part = _part(body=body)
        assert _with_rule(_evaluate([part]), "MC-T10") != []

    def test_a_declared_cte_silences_the_eight_bit_rule(self):
        part = _part(headers=(("Content-Transfer-Encoding", "8bit"),), body="中文")
        assert _with_rule(_evaluate([part]), "MC-T10") == []


class TestAttributionRules:
    @pytest.mark.parametrize(
        "name,filename,bad",
        (
            ("a.txt", "a.txt", False),
            ("a.txt", "b.txt", True),
            (None, "a.txt", False),
            ("a.txt", None, False),
        ),
    )
    def test_the_name_vs_filename_rule(self, name, filename, bad):
        type_value = 'text/plain; name="%s"' % name if name else "text/plain"
        disposition = 'attachment; filename="%s"' % filename if filename else "attachment"
        part = _part(
            content_type=type_value,
            headers=(("Content-Type", type_value), ("Content-Disposition", disposition)),
        )
        assert bool(_with_rule(_evaluate([part]), "MC-A02")) == bad

    @pytest.mark.parametrize(
        "disposition,present",
        (
            ("attachment", True),
            ("inline", True),
            ("attachment; filename=\"a.txt\"", False),
            ("inline; filename=\"a.png\"", False),
        ),
    )
    def test_the_missing_filename_rule(self, disposition, present):
        part = _part(headers=(("Content-Disposition", disposition),))
        assert bool(_with_rule(_evaluate([part]), "MC-A03")) == present

    @pytest.mark.parametrize(
        "disposition,content_id,present",
        (
            ("inline", None, True),
            ("inline", "<a@example.com>", False),
            ("attachment", None, False),
        ),
    )
    def test_the_inline_without_content_id_rule(self, disposition, content_id, present):
        headers = [("Content-Disposition", disposition)]
        if content_id:
            headers.append(("Content-ID", content_id))
        part = _part(headers=tuple(headers))
        assert bool(_with_rule(_evaluate([part]), "MC-A07")) == present


# ---------------------------------------------------------------------------
# 语料矩阵：每个语料是一个完整的多部件工件
# ---------------------------------------------------------------------------
def _corpus_clean():
    return [
        _part(path="0", content_type="multipart/mixed", boundary="b1",
              headers=(("Content-Type", "multipart/mixed; boundary=b1"),)),
        _part(path="0.1", headers=(("Content-Type", "text/plain"), ("Content-Transfer-Encoding", "7bit")), body="hello"),
        _part(path="0.2", headers=(("Content-Type", "text/plain"),), body="world"),
    ]


CORPORA = (
    ("clean", _corpus_clean, (), ()),
    (
        "no_boundary",
        lambda: [_part(path="0", content_type="multipart/mixed")],
        ("MC-B01",),
        (ERROR,),
    ),
    (
        "long_boundary",
        lambda: [_part(path="0", content_type="multipart/mixed", boundary="b" * 80)],
        ("MC-B02",),
        (WARN,),
    ),
    (
        "wide_header",
        lambda: [_part(headers=(("X-Long", "x" * 1200),))],
        ("MC-H07",),
        (ERROR,),
    ),
    (
        "bad_escape",
        lambda: [
            _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="a=ZZ")
        ],
        ("MC-T07",),
        (ERROR,),
    ),
    (
        "unknown_cte",
        lambda: [_part(headers=(("Content-Transfer-Encoding", "b64x"),), body="abc")],
        ("MC-T08",),
        (INFO,),
    ),
    (
        "mixed",
        lambda: [
            _part(path="0", content_type="multipart/mixed", boundary="b" * 80),
            _part(path="0.1", headers=(("X-Long", "x" * 1200),)),
            _part(path="0.2", headers=(("Content-Transfer-Encoding", "base64"),), body="QU$D"),
        ],
        ("MC-B02", "MC-H07", "MC-T04"),
        (WARN, ERROR, INFO),
    ),
    (
        "two_series_like_parts",
        lambda: [
            _part(path="0", headers=(("X-Long", "x" * 1200),)),
            _part(path="1", headers=(("X-Long", "x" * 1200),)),
        ],
        ("MC-H07",),
        (ERROR, ERROR),
    ),
)


class TestCorpusMatrix:
    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_the_expected_rules_appear(self, case_id, make_parts, expected_rules, expected_verdicts):
        assert tuple(_rule_ids(_evaluate(make_parts()))) == expected_rules, case_id

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_the_expected_verdicts_match_the_rules(self, case_id, make_parts, expected_rules, expected_verdicts):
        records = _evaluate(make_parts())
        assert tuple(record.verdict for record in records) == expected_verdicts, case_id

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_ids_are_unique(self, case_id, make_parts, expected_rules, expected_verdicts):
        ids = [record.id for record in _evaluate(make_parts())]
        assert len(ids) == len(set(ids)), case_id

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_every_record_cites_a_complete_basis(self, case_id, make_parts, expected_rules, expected_verdicts):
        for record in _evaluate(make_parts()):
            assert record.basis is not None and record.basis.complete, case_id

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_no_record_carries_a_raw_float(self, case_id, make_parts, expected_rules, expected_verdicts):
        for record in _evaluate(make_parts()):
            assert list(_iter_floats(record.as_dict())) == [], case_id

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_the_ledger_is_stable_across_two_runs(self, case_id, make_parts, expected_rules, expected_verdicts):
        assert [record.id for record in _evaluate(make_parts())] == [
            record.id for record in _evaluate(make_parts())
        ]

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_the_ledger_survives_a_json_roundtrip(self, case_id, make_parts, expected_rules, expected_verdicts):
        payload = json.loads(json.dumps({"parts": make_parts()}, ensure_ascii=False))
        assert [record.id for record in _evaluate(make_parts())] == [
            record.id for record in audit.evaluate(payload, BASIS)
        ]

    @pytest.mark.parametrize("case_id,make_parts,expected_rules,expected_verdicts", CORPORA)
    def test_the_part_order_does_not_change_the_rule_set(self, case_id, make_parts, expected_rules, expected_verdicts):
        forward = _rule_ids(_evaluate(make_parts()))
        backward = _rule_ids(_evaluate(list(reversed(make_parts()))))
        assert forward == backward, case_id


class TestLabelUniqueness:
    @pytest.mark.parametrize("count", (2, 3, 5))
    def test_repeated_hits_in_one_part_get_their_own_label(self, count):
        headers = tuple(("X-Long", "x" * 1200) for _index in range(count))
        records = _with_rule(_evaluate([_part(headers=headers)]), "MC-H07")
        assert len(records) == count
        assert [record.path for record in records] == ["0#%d" % index for index in range(1, count + 1)]

    @pytest.mark.parametrize("path", ("0", "0.1", "msg#3/0.1"))
    def test_the_label_carries_the_part_path(self, path):
        for record in _evaluate([_part(path=path, headers=(("X-Long", "x" * 1200),))]):
            assert record.path.startswith(path + "#")


# ---------------------------------------------------------------------------
# 参数面
# ---------------------------------------------------------------------------
class TestParamSurface:
    @pytest.mark.parametrize("name", [entry[0] for entry in spec.PARAM_FIELDS])
    def test_every_declared_parameter_has_a_default(self, name):
        assert spec.resolve_params()[name] == spec.DEFAULT_PARAMS[name]

    @pytest.mark.parametrize("name", [entry[0] for entry in spec.PARAM_FIELDS])
    def test_every_parameter_accepts_an_override(self, name):
        assert spec.resolve_params({name: 7})[name] == 7

    @pytest.mark.parametrize("name", [entry[0] for entry in spec.PARAM_FIELDS])
    def test_every_parameter_accepts_an_integral_float(self, name):
        assert spec.resolve_params({name: 9.0})[name] == 9

    @pytest.mark.parametrize("name", [entry[0] for entry in spec.PARAM_FIELDS])
    def test_every_parameter_rejects_a_fraction(self, name):
        with pytest.raises(ValueError):
            spec.resolve_params({name: 1.5})

    @pytest.mark.parametrize("name", [entry[0] for entry in spec.PARAM_FIELDS])
    def test_every_parameter_rejects_null(self, name):
        with pytest.raises(ValueError):
            spec.resolve_params({name: None})

    @pytest.mark.parametrize("name", [entry[0] for entry in spec.PARAM_FIELDS])
    def test_every_parameter_rejects_zero(self, name):
        with pytest.raises(ValueError):
            spec.resolve_params({name: 0})

    def test_an_unknown_key_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"nope": 1})

    def test_params_must_be_an_object(self):
        with pytest.raises(ValueError):
            spec.resolve_params([])

    def test_the_dumped_form_is_all_integers(self):
        assert all(isinstance(value, int) for value in spec.dump_params(spec.resolve_params()).values())

    def test_the_dumped_form_carries_no_float(self):
        assert list(_iter_floats(spec.dump_params(spec.resolve_params()))) == []


# ---------------------------------------------------------------------------
# 信封
# ---------------------------------------------------------------------------
ENVELOPE_ERRORS = (
    ("parts_is_object", {"parts": {}}),
    ("parts_is_string", {"parts": "x"}),
    ("parts_is_empty", {"parts": []}),
    ("part_is_string", {"parts": ["x"]}),
    ("missing_path", {"parts": [{"content_type": "text/plain", "body": ""}]}),
    ("blank_path", {"parts": [{"path": "  ", "content_type": "text/plain", "body": ""}]}),
    ("missing_content_type", {"parts": [{"path": "0", "body": ""}]}),
    ("blank_content_type", {"parts": [{"path": "0", "content_type": "  ", "body": ""}]}),
    ("bad_boundary_type", {"parts": [{"path": "0", "content_type": "text/plain", "boundary": 3, "body": ""}]}),
    ("headers_not_list", {"parts": [{"path": "0", "content_type": "text/plain", "headers": {}, "body": ""}]}),
    (
        "header_not_object",
        {"parts": [{"path": "0", "content_type": "text/plain", "headers": ["x"], "body": ""}]},
    ),
    (
        "header_blank_name",
        {"parts": [{"path": "0", "content_type": "text/plain", "headers": [{"name": "", "value": "v"}], "body": ""}]},
    ),
    (
        "header_missing_value",
        {"parts": [{"path": "0", "content_type": "text/plain", "headers": [{"name": "X"}], "body": ""}]},
    ),
    ("missing_body", {"parts": [{"path": "0", "content_type": "text/plain"}]}),
    ("body_wrong_type", {"parts": [{"path": "0", "content_type": "text/plain", "body": 1}]}),
    (
        "duplicate_part_path",
        {
            "parts": [
                {"path": "0", "content_type": "text/plain", "body": ""},
                {"path": "0", "content_type": "text/plain", "body": ""},
            ]
        },
    ),
    ("params_is_list", {"parts": [{"path": "0", "content_type": "text/plain", "body": ""}], "params": []}),
    (
        "params_unknown",
        {"parts": [{"path": "0", "content_type": "text/plain", "body": ""}], "params": {"nope": 1}},
    ),
)


class TestEnvelopeMatrix:
    @pytest.mark.parametrize("case_id,payload", ENVELOPE_ERRORS)
    def test_a_bad_envelope_is_an_input_error(self, case_id, payload):
        with pytest.raises(ValueError):
            audit.evaluate(payload, BASIS)

    @pytest.mark.parametrize("case_id,payload", ENVELOPE_ERRORS)
    def test_a_bad_envelope_exits_two_through_the_cli(self, case_id, payload, tmp_path, capsys):
        target = tmp_path / "input.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_INPUT, case_id

    def test_a_null_body_is_read_as_empty(self):
        assert _evaluate([{"path": "0", "content_type": "text/plain", "body": None}]) == ()

    def test_a_non_object_subject_is_an_input_error(self):
        with pytest.raises(ValueError):
            audit.evaluate(["x"], BASIS)


class TestBasisWiring:
    def test_a_missing_rule_is_a_rule_missing_violation(self):
        with pytest.raises(RuleMissing):
            _evaluate([_part(headers=(("X-Long", "x" * 1200),))], basis=Basis(version="9", rules=()))

    def test_the_shipped_basis_satisfies_every_rule(self):
        for rule_id in spec.RULE_IDS:
            assert BASIS.ref(rule_id).rule_version == BASIS.version


#: ``Content-Type`` 取值解析矩阵：(原文, 主类型, 参数表)。
MEDIA_TYPES = (
    ("text/plain", "text/plain", {}),
    ("TEXT/PLAIN", "text/plain", {}),
    (" text/plain ", "text/plain", {}),
    ("text/plain; charset=utf-8", "text/plain", {"charset": "utf-8"}),
    ('text/plain; charset="utf-8"', "text/plain", {"charset": "utf-8"}),
    ("multipart/mixed; boundary=b1", "multipart/mixed", {"boundary": "b1"}),
    ('multipart/mixed; boundary="b 1"', "multipart/mixed", {"boundary": "b 1"}),
    (
        "text/plain; charset=utf-8; format=flowed",
        "text/plain",
        {"charset": "utf-8", "format": "flowed"},
    ),
    ('application/pdf; name="a.pdf"', "application/pdf", {"name": "a.pdf"}),
    ("image/png; name=x.png", "image/png", {"name": "x.png"}),
    (
        "multipart/related; boundary=a; type=text/html",
        "multipart/related",
        {"boundary": "a", "type": "text/html"},
    ),
    ("message/rfc822", "message/rfc822", {}),
    ("application/octet-stream", "application/octet-stream", {}),
    ("Text/HTML; Charset=UTF-8", "text/html", {"charset": "UTF-8"}),
)


class TestMediaTypeParsing:
    """``Content-Type`` / ``Content-Disposition`` 是同一套语法，同一个解析点。"""

    @pytest.mark.parametrize("value,main,params", MEDIA_TYPES)
    def test_the_main_type_is_lowercased_and_stripped(self, value, main, params):
        assert detectors._split_media_type(value)[0] == main

    @pytest.mark.parametrize("value,main,params", MEDIA_TYPES)
    def test_the_parameters_are_extracted(self, value, main, params):
        assert detectors._split_media_type(value)[1] == params

    @pytest.mark.parametrize("value,main,params", MEDIA_TYPES)
    def test_the_parse_is_stable_across_calls(self, value, main, params):
        assert detectors._split_media_type(value) == detectors._split_media_type(value)


class TestEvidenceCarriesTheParams:
    """一条账本的证据必须说清"当时用的是哪组阈值"。"""

    PARAM_PROBES = {
        # 每一条探针在**默认阈值下也会命中**，这样同一份工件能同时验"默认"与"覆盖"两侧。
        "max_depth": (_part(path=".".join(["0"] * 33)), 2),
        "max_boundary_chars": (_part(content_type="multipart/mixed", boundary="b" * 71), 60),
        "max_header_line_octets": (_part(headers=(("X-Long", "x" * 1010),)), 1000),
        "max_encoded_word_chars": (_part(headers=(("Subject", _ew(70)),)), 60),
        "max_encoded_header_line": (_part(headers=(("Subject", _ew(6) + "b" * 60),)), 50),
        "max_qp_line_octets": (
            _part(headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="A" * 90),
            80,
        ),
        "max_body_line_octets": (
            _part(headers=(("Content-Transfer-Encoding", "7bit"),), body="A" * 1000),
            900,
        ),
    }

    @pytest.mark.parametrize("name", sorted(PARAM_PROBES))
    def test_the_effective_value_is_recorded(self, name):
        part, value = self.PARAM_PROBES[name]
        records = _evaluate([part], **{name: value})
        assert records
        for record in records:
            assert record.evidence["params"][name] == value

    @pytest.mark.parametrize("name", sorted(PARAM_PROBES))
    def test_the_default_value_is_recorded_when_not_overridden(self, name):
        part, _value = self.PARAM_PROBES[name]
        records = _evaluate([part])
        assert records
        for record in records:
            assert record.evidence["params"][name] == spec.DEFAULT_PARAMS[name]


class TestWiderBoundarySweeps:
    @pytest.mark.parametrize("size", (990, 992, 996, 1002, 1010))
    def test_more_header_line_sizes(self, size):
        part = _part(headers=(("X-Long", "x" * (size - 8)),))
        assert len(_with_rule(_evaluate([part]), "MC-H07")) == (1 if size > 998 else 0)

    @pytest.mark.parametrize("length", (66, 67, 73, 74, 75))
    def test_more_boundary_lengths(self, length):
        part = _part(content_type="multipart/mixed", boundary="b" * length)
        assert len(_with_rule(_evaluate([part]), "MC-B02")) == (1 if length > 70 else 0)

    @pytest.mark.parametrize("length", (9, 11, 13, 15, 17))
    def test_more_base64_lengths(self, length):
        part = _part(headers=(("Content-Transfer-Encoding", "base64"),), body="A" * length)
        assert len(_with_rule(_evaluate([part]), "MC-T03")) == (1 if length % 4 else 0)

    @pytest.mark.parametrize("length", (72, 74, 78, 82))
    def test_more_qp_widths(self, length):
        part = _part(
            headers=(("Content-Transfer-Encoding", "quoted-printable"),), body="A" * length
        )
        assert len(_with_rule(_evaluate([part]), "MC-T05")) == (1 if length > 76 else 0)

    @pytest.mark.parametrize("size", (10, 30, 50, 63, 64, 65))
    def test_more_encoded_word_sizes(self, size):
        part = _part(headers=(("Subject", _ew(size)),))
        assert len(_with_rule(_evaluate([part]), "MC-H01")) == (1 if 12 + size > 75 else 0)


# ---------------------------------------------------------------------------
# 器官契约门
# ---------------------------------------------------------------------------
BANNED_NAMES = frozenset(
    ("exp", "log", "pow", "sqrt", "sin", "cos", "tan", "round", "open", "print", "input", "exec", "eval")
)
BANNED_MODULES = frozenset(
    (
        "random",
        "statistics",
        "numpy",
        "datetime",
        "time",
        "argparse",
        "os",
        "pathlib",
        "shutil",
        "subprocess",
        "sys",
        "socket",
        "urllib",
        "requests",
        "sqlite3",
        "base64",
        "quopri",
        "email",
    )
)


def _python_sources(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in ("__pycache__",)]
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                found.append(os.path.join(dirpath, filename))
    return found


def scan_python(path, root):
    with io.open(path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    relative = os.path.relpath(path, root).replace("\\", "/")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    hits.append((relative, node.lineno, "import %s" % alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in BANNED_MODULES:
                hits.append((relative, node.lineno, "from %s import" % node.module))
            for alias in node.names or ():
                if alias.name in BANNED_NAMES:
                    hits.append((relative, node.lineno, alias.name))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            hits.append((relative, node.lineno, "**"))
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
            hits.append((relative, node.lineno, node.attr))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
            hits.append((relative, node.lineno, node.func.id))
    return hits


def scan_tree(root):
    hits = []
    for path in _python_sources(root):
        hits.extend(scan_python(path, root))
    return sorted(hits)


class TestNoClockNoSideEffects:
    def test_the_scope_is_the_whole_organ_package(self):
        names = sorted(os.path.basename(path) for path in _python_sources(ORGAN_DIR))
        assert len(names) >= 4, names
        for expected in ("__init__.py", "audit.py", "detectors.py", "spec.py"):
            assert expected in names, names

    def test_the_organ_package_is_clean(self):
        assert scan_tree(ORGAN_DIR) == []

    def test_the_scanner_reads_a_real_file(self, tmp_path):
        target = tmp_path / "sample.py"
        target.write_text("import math\nVALUE = math.floor(1.5)\n", encoding="utf-8")
        assert scan_python(str(target), str(tmp_path)) == []
        target.write_text("print('x')\n", encoding="utf-8")
        assert scan_python(str(target), str(tmp_path)) == [("sample.py", 1, "print")]

    def test_a_clock_import_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "import time\n")
        assert any(hit[2] == "import time" for hit in scan_tree(root))

    def test_the_email_module_is_caught(self, tmp_path):
        # 判定不许借标准库的 email 解析器：那会把"我们判什么"变成"库怎么实现"
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "detectors.py"), "import email\n")
        assert any(hit[2] == "import email" for hit in scan_tree(root))

    def test_a_print_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "print('x')\n")
        assert any(hit[2] == "print" for hit in scan_tree(root))

    def test_a_file_open_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "HANDLE = open('x')\n")
        assert any(hit[2] == "open" for hit in scan_tree(root))

    def test_the_organ_returns_only_records(self):
        result = audit.evaluate({"parts": [_part()]}, BASIS)
        assert isinstance(result, tuple)
        assert all(isinstance(record, Record) for record in result)


def _copy_package(tmp_path):
    target = tmp_path / "media-type-check"
    shutil.copytree(ORGAN_DIR, str(target), ignore=shutil.ignore_patterns("__pycache__"))
    return str(target)


def _inject(path, line):
    with io.open(path, "a", encoding="utf-8") as handle:
        handle.write("\n" + line)


# ---------------------------------------------------------------------------
# 唯一入口
# ---------------------------------------------------------------------------
class TestCli:
    def test_the_shipped_basis_is_found_without_a_flag(self):
        assert cli.shipped_basis_path(SLUG) == str(BASIS_PATH)

    def test_a_clean_artifact_exits_zero(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"parts": _corpus_clean()}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_OK
        assert "合计" in capsys.readouterr().out

    def test_a_blocking_artifact_exits_one(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"parts": [_part(path="0", content_type="multipart/mixed")]}), encoding="utf-8"
        )
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_BLOCKED

    def test_a_warning_only_artifact_exits_zero(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"parts": [_part(content_type="multipart/mixed", boundary="b" * 80)]}),
            encoding="utf-8",
        )
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_OK

    def test_the_json_output_is_byte_identical_across_runs(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"parts": _corpus_clean() + [_part(path="1", headers=(("X-Long", "x" * 1200),))]}), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        first = capsys.readouterr().out
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        assert capsys.readouterr().out == first

    def test_the_json_envelope_has_the_spec_fields(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"parts": [_part()]}), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"product", "organ", "organ_version", "subject", "summary", "records"}
        assert payload["organ"] == SLUG

    def test_the_output_has_no_absolute_path(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"parts": [_part()]}), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        out = capsys.readouterr().out
        assert str(ROOT) not in out and "ProgramData" not in out

    def test_stdin_is_labelled(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"parts": [_part()]})))
        assert cli.main(["check", SLUG, "--input", "-", "--json"]) == EXIT_OK
        assert json.loads(capsys.readouterr().out)["subject"] == "<stdin>"

    def test_an_empty_basis_is_a_contract_error(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"parts": [_part(headers=(("X-Long", "x" * 1200),))]}), encoding="utf-8"
        )
        basis = tmp_path / "rules.json"
        basis.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target), "--basis", str(basis)]) == EXIT_CONTRACT
        assert "RuleMissing" in capsys.readouterr().err

    def test_a_missing_input_file_is_an_input_error(self, tmp_path):
        assert cli.main(["check", SLUG, "--input", str(tmp_path / "nope.json")]) == EXIT_INPUT

    def test_the_required_field_is_enforced_by_the_kernel(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_INPUT
        assert "parts" in capsys.readouterr().err

    def test_the_list_json_carries_the_input_fields(self, capsys):
        assert cli.main(["list", "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        entry = [item for item in payload if item["slug"] == SLUG][0]
        assert entry["input_fields"] == ["parts"]
        assert entry["version"] == ORGAN_VERSION