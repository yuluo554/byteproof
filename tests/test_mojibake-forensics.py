"""``mojibake-forensics`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那套函数仍然在、语义仍然是那一套**：
链枚举与反向逐字节复算、三层打分与冻结排序键、相对份额区间、不可逆四类判死、
逐步重放证明与第一处分叉、BOM/UTF-16/ZIP/CSV 字节诊断、逐行 K9 门禁。

**没迁的部分逐条写在 ``docs/mojibake-forensics.md`` §6 的处置表里**（真实文件读取、
目录遍历、`--out` 写盘、CLI 参数解析、输出排版、`--freq` 语言先验）。
不迁的东西不在这里假装测过。

判定层口径（D1 + D18）：旧仓 11 个判定层文件实跑 **X = 148 passed**（AST 函数 136）。
"""

from __future__ import annotations

import ast
import codecs
import io
import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from byteproof import cli  # noqa: E402
from byteproof.auditors import BUILTIN_MODULES, load_builtin  # noqa: E402
from byteproof.auditors.mojibake_forensics import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    chain,
    probe,
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
    Report,
    RuleMissing,
)
from byteproof.core.registry import get  # noqa: E402

SLUG = "mojibake-forensics"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "mojibake_forensics"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "mojibake-forensics.basis.json"
THRESHOLDS_PATH = DATA_DIR / "mojibake-forensics.thresholds.json"
SAMPLE = ROOT / "samples" / "mojibake-forensics.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

CLASSIC = "é›…"
CLASSIC_DOUBLE = "é›…é›…"
CLASSIC_TRUTH = "雅"


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id):
    return [record for record in _evaluate(subject) if record.rule_id == rule_id]


def _report(subject, basis=None):
    return Report(
        product="byteproof",
        organ=SLUG,
        organ_version=ORGAN_VERSION,
        subject="test.json",
        records=tuple(_evaluate(subject, basis)),
    )


def _chain(*pairs):
    return chain.Chain(
        steps=tuple(
            chain.Step(index=index + 1, op=op, codec=codec)
            for index, (op, codec) in enumerate(pairs)
        )
    )


def _attr(text, **extra):
    subject = {"mode": "attr", "text": text}
    subject.update(extra)
    return subject


def _recover(text, pick=1):
    return {"mode": "recover", "text": text, "pick": pick}


def _explain(text, **extra):
    subject = {"mode": "explain", "text": text}
    subject.update(extra)
    return subject


def _zip_bytes(name="café.txt", payload="x", utf8_flag=True):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, payload)
    data = bytearray(buffer.getvalue())
    if not utf8_flag:
        index = data.find(b"PK\x01\x02")
        struct.pack_into("<H", data, index + 8, 0)
    return bytes(data)


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG
    assert PACK.version == "1"


def test_pack_declares_only_mode_as_universal_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "mojibake_forensics" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_modes_are_the_five_source_subcommands():
    assert spec.MODES == ("attr", "explain", "recover", "file", "scan")


def test_sample_is_attr_of_the_readme_text():
    subject = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert subject == {"mode": "attr", "text": CLASSIC_DOUBLE}


# ================================================================== 规则包
def test_basis_has_every_declared_rule():
    assert set(BASIS.rule_ids()) == set(spec.RULE_IDS)


def test_basis_rule_ids_match_verdict_table():
    assert set(spec.RULE_IDS) == set(spec.VERDICTS)


def test_basis_rules_all_have_version_source_and_text():
    for rule_id in BASIS.rule_ids():
        rule = BASIS.require(rule_id)
        assert rule.version == "1", rule_id
        assert rule.source, rule_id
        assert rule.text, rule_id


def test_basis_rule_ids_are_sorted():
    assert BASIS.rule_ids() == sorted(BASIS.rule_ids())


def test_thresholds_verdicts_match_runtime_table():
    assert SETTINGS["verdicts"] == spec.VERDICTS


def test_thresholds_encoders_match_runtime():
    assert tuple(SETTINGS["encoders"]) == spec.ENCODERS


def test_thresholds_decoders_match_runtime():
    assert tuple(SETTINGS["decoders"]) == spec.DECODERS


def test_thresholds_depth_and_top_match_runtime():
    assert SETTINGS["max_depth"] == spec.MAX_DEPTH == 3
    assert SETTINGS["default_top"] == spec.DEFAULT_TOP == 5


def test_thresholds_weights_match_runtime():
    weights = SETTINGS["weights"]
    assert weights["readability"] == spec.W_READ
    assert weights["depth"] == spec.W_DEPTH
    assert weights["language"] == spec.W_LANG


def test_thresholds_scan_gates_match_runtime():
    scan = SETTINGS["scan"]
    assert scan["input_readability_below"] == spec.INPUT_READABILITY_BELOW
    assert scan["candidate_readability_at_least"] == spec.CANDIDATE_READABILITY_AT_LEAST
    assert scan["readability_gain_at_least"] == spec.READABILITY_GAIN_AT_LEAST


def test_thresholds_readability_classes_match_runtime():
    classes = SETTINGS["readability_classes"]
    assert classes["ascii_visible"] == spec.ASCII_VISIBLE
    assert classes["cjk"] == spec.CJK
    assert classes["latin_ext"] == spec.LATIN_EXT
    assert classes["halfwidth_katakana"] == spec.HALFWIDTH_KATAKANA
    assert classes["control"] == spec.CONTROL
    assert classes["pua"] == spec.PUA
    assert classes["replacement"] == spec.REPLACEMENT
    assert classes["other"] == spec.OTHER


# ================================================================== 编码集合
@pytest.mark.parametrize("codec", spec.ENCODERS)
def test_encoder_is_available(codec):
    assert codecs.lookup(codec) is not None


@pytest.mark.parametrize("codec", spec.DECODERS)
def test_decoder_is_available(codec):
    assert isinstance(b"abc".decode(codec), str)


def test_encoder_and_decoder_sets_are_frozen_values():
    assert spec.ENCODERS == (
        "utf-8",
        "gb18030",
        "gbk",
        "big5",
        "shift_jis",
        "euc-jp",
        "euc-kr",
        "cp1252",
        "latin-1",
        "cp437",
    )
    assert spec.DECODERS == (
        "utf-8",
        "gb18030",
        "big5",
        "shift_jis",
        "euc-kr",
        "cp1252",
        "latin-1",
    )


# ================================================================== hexdump / 解析
def test_hexdump_is_uppercase_single_spaced():
    assert chain.hexdump(b"\x65\xc3\x8b") == "65 C3 8B"


def test_parse_hex_accepts_spaced_and_compact_forms():
    assert chain.parse_hex("E9 9B 85") == b"\xe9\x9b\x85"
    assert chain.parse_hex("E99B85") == b"\xe9\x9b\x85"
    assert chain.parse_hex("e9 9b 85") == b"\xe9\x9b\x85"


def test_parse_hex_rejects_empty():
    with pytest.raises(ValueError):
        chain.parse_hex("")


def test_parse_hex_rejects_odd_length():
    with pytest.raises(ValueError):
        chain.parse_hex("E9 9")


def test_parse_hex_rejects_non_hex():
    with pytest.raises(ValueError):
        chain.parse_hex("ZZ")


def test_parse_hex_rejects_non_string():
    with pytest.raises(ValueError):
        chain.parse_hex(b"\xe9")


# ================================================================== 链与打分
def test_chain_depth_counts_decode_steps():
    assert _chain(("encode", "cp1252"), ("decode", "utf-8"), ("encode", "cp1252"), ("decode", "utf-8")).depth == 2


def test_path_string_is_canonical():
    built = _chain(("encode", "cp1252"), ("decode", "utf-8"))
    assert built.path_string == "encode:cp1252>decode:utf-8"
    assert built.path == [
        {"op": "encode", "codec": "cp1252"},
        {"op": "decode", "codec": "utf-8"},
    ]


def test_step_as_dict_keeps_recorded_states():
    step = chain.Step(index=1, op="encode", codec="cp1252", input_text="é", output_hex="E9")
    assert step.as_dict() == {
        "index": 1,
        "op": "encode",
        "codec": "cp1252",
        "input": "é",
        "output_hex": "E9",
    }


def test_validate_depth_rejects_zero():
    with pytest.raises(ValueError):
        chain.validate_depth(0)


def test_validate_depth_defaults_to_three():
    assert chain.validate_depth() == 3
    assert chain.validate_depth(2) == 2


def test_verify_lossless_accepts_truth_chain():
    text = "é›…"
    built = _chain(("encode", "cp1252"), ("decode", "utf-8"))
    assert chain.verify_lossless(text, built) is True
    assert chain.replay(text, built) == "雅"


def test_verify_lossless_rejects_mutated_chain():
    text = "é›…"
    built = _chain(("encode", "cp1252"), ("decode", "gb18030"))
    assert chain.verify_lossless(text, built) is False
    assert chain.replay(text, built) is None


def test_enumerate_chains_includes_truth_and_respects_depth():
    chains = chain.enumerate_chains(text="é›…", max_depth=2)
    results = [built.result for built in chains]
    assert "雅" in results
    assert all(built.depth <= 2 for built in chains)
    assert all(built.steps[0].op == "encode" for built in chains)
    assert all(built.steps[-1].op == "decode" for built in chains)
    assert all(built.result != "é›…" for built in chains)


def test_enumerate_chains_depth_one():
    chains = chain.enumerate_chains(text="é›…", max_depth=1)
    assert chains
    assert all(built.depth == 1 for built in chains)
    assert "encode:cp1252>decode:utf-8" in [built.path_string for built in chains]


def test_enumerate_chains_is_deterministic():
    first = chain.enumerate_chains(text="ä¸­æ–‡", max_depth=2)
    second = chain.enumerate_chains(text="ä¸­æ–‡", max_depth=2)
    assert [built.path_string for built in first] == [built.path_string for built in second]
    assert [built.result for built in first] == [built.result for built in second]


def test_collapse_by_result_keeps_one_chain_per_text():
    chains = chain.enumerate_chains(text="ä¸­æ–‡", max_depth=2)
    collapsed = chain.collapse_by_result(chains)
    results = [built.result for built in collapsed]
    assert len(results) == len(set(results))
    assert len(collapsed) <= len(chains)


def test_readability_classes():
    assert chain.readability("") == 0.0
    assert chain.readability("中文") == 1.0
    assert chain.readability("日本語") == 1.0
    assert chain.readability("한국어") == 1.0
    assert round(chain.readability("abc"), 6) == 0.2
    assert round(chain.readability("é"), 6) == 0.1
    assert round(chain.readability("…"), 6) == 0.0
    assert round(chain.readability("\ufffd"), 6) == -1.0
    assert round(chain.readability("\x00"), 6) == -1.0
    assert round(chain.readability("ｱ"), 6) == -0.5


def test_readability_clamps_to_documented_range():
    assert chain.readability("\ufffd\ufffd") == -1.0


def test_noncharacter_and_pua_are_penalized():
    assert chain.char_score("\ufdd0") == spec.PUA
    assert chain.char_score("\ue000") == spec.PUA
    assert chain.char_score("\ud800") == spec.PUA


def test_depth_score_is_shallow_first():
    assert chain.depth_score(0) == 1.0
    assert chain.depth_score(1) == 0.5
    assert round(chain.depth_score(2), 6) == round(1.0 / 3.0, 6)


def test_rank_uses_frozen_sort_key():
    shallow = chain.Chain(
        steps=(
            chain.Step(index=1, op="encode", codec="latin-1", output_text="中文"),
            chain.Step(index=2, op="decode", codec="utf-8", output_text="中文"),
        )
    )
    ranked = chain.rank([shallow])
    assert ranked[0]["rank"] == 1
    assert ranked[0]["score"]["readability"] == 1.0
    assert ranked[0]["score"]["depth"] == 0.5
    assert ranked[0]["score"]["language"] == 0.0
    assert ranked[0]["score"]["total"] == 1.25


def test_sort_key_ties_break_on_path_string():
    entries = [
        {"score_total": 1.0, "depth": 1, "path_string": "encode:utf-8>decode:latin-1"},
        {"score_total": 1.0, "depth": 1, "path_string": "encode:cp1252>decode:utf-8"},
    ]
    entries.sort(key=chain.sort_key)
    assert entries[0]["path_string"] == "encode:cp1252>decode:utf-8"


def test_sort_key_accepts_nested_score():
    entry = {"score": {"total": 0.5}, "depth": 1, "path_string": "x"}
    assert chain.sort_key(entry) == (-0.5, 1, "x")


def test_confidence_normalizes_over_the_full_set():
    intervals, note = chain.confidence([{"score_total": 3.0}, {"score_total": 1.0}])
    assert note is None
    assert round(intervals[0]["lower"], 12) == round(0.75 / 1.05, 12)
    assert round(intervals[1]["upper"], 12) == round(0.25 * 1.05, 12)


def test_confidence_is_null_when_no_positive_distribution_exists():
    intervals, note = chain.confidence(
        [{"score_total": -0.5}, {"score_total": 0.0}, {"score_total": -0.25}]
    )
    assert intervals == [None, None, None]
    assert note == "no_positive_score"


def test_confidence_single_candidate_is_one_with_note():
    intervals, note = chain.confidence([{"score_total": 1.0}])
    assert intervals == [{"lower": 1.0, "upper": 1.0}]
    assert note == "single_candidate_in_bounded_search"


def test_confidence_empty_is_empty():
    assert chain.confidence([]) == ([], None)


def test_search_rejects_non_string():
    with pytest.raises(ValueError):
        chain.search(b"bytes")


def test_search_rejects_empty_text():
    with pytest.raises(ValueError):
        chain.search("")


def test_search_rejects_codec_outside_frozen_set():
    with pytest.raises(ValueError):
        chain.search(CLASSIC, encoders=("cp932",))
    with pytest.raises(ValueError):
        chain.search(CLASSIC, decoders=("euc-jp",))


def test_search_subset_shrinks_the_search():
    full, _chains = chain.search(CLASSIC)
    subset, subset_chains = chain.search(CLASSIC, encoders=("cp1252",), decoders=("utf-8",))
    assert len(subset) < len(full)
    assert subset_chains <= _chains


# ================================================================== attr
def test_attr_candidates_are_records_with_evidence():
    records = _records(_attr(CLASSIC), spec.RULE_ATTR_CANDIDATE)
    assert records
    assert all(record.verdict == INFO for record in records)
    for record in records:
        assert set(record.evidence) >= {
            "rank",
            "result",
            "path",
            "path_string",
            "depth",
            "score",
            "confidence",
        }


def test_attr_reaches_the_classic_truth():
    results = [record.evidence["result"] for record in _records(_attr(CLASSIC), spec.RULE_ATTR_CANDIDATE)]
    assert CLASSIC_TRUTH in results


def test_attr_ranks_are_contiguous_from_one():
    ranks = [record.evidence["rank"] for record in _records(_attr(CLASSIC), spec.RULE_ATTR_CANDIDATE)]
    assert ranks == list(range(1, len(ranks) + 1))


def test_attr_confidence_is_an_interval():
    for record in _records(_attr(CLASSIC), spec.RULE_ATTR_CANDIDATE):
        confidence = record.evidence["confidence"]
        assert 0.0 <= confidence["lower"] <= confidence["upper"] <= 1.0


def test_attr_path_string_matches_path():
    for record in _records(_attr(CLASSIC), spec.RULE_ATTR_CANDIDATE):
        assert record.evidence["path_string"] == ">".join(
            "%s:%s" % (step["op"], step["codec"]) for step in record.evidence["path"]
        )


def test_attr_default_top_is_five():
    records = _records(_attr(CLASSIC), spec.RULE_ATTR_CANDIDATE)
    assert len(records) == 5


def test_attr_truncation_record_carries_full_counts():
    truncated = _records(_attr(CLASSIC), spec.RULE_ATTR_TRUNCATED)
    assert len(truncated) == 1
    assert truncated[0].evidence["shown"] == 5
    assert truncated[0].evidence["total_candidates"] > 5


def test_attr_top_does_not_change_total_candidates():
    one = _records(_attr(CLASSIC, top=1), spec.RULE_ATTR_TRUNCATED)[0].evidence
    full = _records(_attr(CLASSIC, top=10 ** 6), spec.RULE_ATTR_TRUNCATED)
    assert full == []
    assert one["total_candidates"] == _records(_attr(CLASSIC, top=10 ** 6), spec.RULE_ATTR_CANDIDATE)[-1].evidence["rank"]


def test_attr_single_candidate_is_one_with_note():
    records = _evaluate(_attr(CLASSIC, source_enc=["cp1252"], target_enc=["utf-8"]))
    candidates = [record for record in records if record.rule_id == spec.RULE_ATTR_CANDIDATE]
    assert len(candidates) == 1
    assert candidates[0].evidence["result"] == CLASSIC_TRUTH
    assert candidates[0].evidence["note"] == "single_candidate_in_bounded_search"
    assert candidates[0].evidence["confidence"] == {"lower": 1.0, "upper": 1.0}
    single = [record for record in records if record.rule_id == spec.RULE_ATTR_SINGLE_CANDIDATE]
    assert len(single) == 1


def test_attr_no_candidate_is_blocking():
    records = _evaluate(_attr("abc"))
    assert [record.rule_id for record in records] == [spec.RULE_ATTR_NO_CANDIDATE]
    assert records[0].verdict == ERROR
    assert records[0].evidence["notes"] == ["depth_limit_reached"]


def test_attr_no_candidate_report_is_blocked():
    assert _report(_attr("abc")).exit_code() == EXIT_BLOCKED


def test_attr_candidates_report_is_clean():
    assert _report(_attr(CLASSIC)).exit_code() == EXIT_OK


def test_attr_rejects_missing_text():
    with pytest.raises(ValueError):
        _evaluate({"mode": "attr"})


def test_attr_rejects_empty_text():
    with pytest.raises(ValueError):
        _evaluate(_attr(""))


def test_attr_rejects_non_integer_top():
    with pytest.raises(ValueError):
        _evaluate(_attr(CLASSIC, top=True))


def test_attr_rejects_zero_top():
    with pytest.raises(ValueError):
        _evaluate(_attr(CLASSIC, top=0))


def test_attr_rejects_unknown_codec_in_subject():
    with pytest.raises(ValueError):
        _evaluate(_attr(CLASSIC, source_enc=["cp932"]))


def test_attr_rejects_non_list_codec_subset():
    with pytest.raises(ValueError):
        _evaluate(_attr(CLASSIC, target_enc="utf-8"))


def test_attr_double_run_is_identical():
    first = _report(_attr(CLASSIC)).as_dict()
    second = _report(_attr(CLASSIC)).as_dict()
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )


# ================================================================== 逐步证明
def test_replay_chain_accepts_the_truth_chain():
    chains = chain.enumerate_chains(text="é›…", max_depth=1)
    truth = [built for built in chains if built.result == "雅"][0]
    replayed = chain.replay_chain(truth)
    assert replayed["verify"] is True
    assert replayed["failed_step"] is None
    assert replayed["output"] == "雅"


def test_replay_chain_records_step_inputs_and_outputs():
    chains = chain.enumerate_chains(text="é›…", max_depth=1)
    truth = [built for built in chains if built.result == "雅"][0]
    steps = chain.replay_chain(truth)["steps"]
    assert [step["op"] for step in steps] == ["encode", "decode"]
    assert steps[0]["output_hex"] == "E9 9B 85"
    assert steps[1]["output"] == "雅"


def test_replay_chain_catches_a_tampered_step():
    chains = chain.enumerate_chains(text="é›…", max_depth=1)
    truth = [built for built in chains if built.result == "雅"][0]
    tampered_step = chain.Step(
        index=2,
        op="decode",
        codec="utf-8",
        input_hex="E9 9B 84",
        output_text="雅",
    )
    tampered = chain.Chain(steps=(truth.steps[0], tampered_step))
    replayed = chain.replay_chain(tampered)
    assert replayed["verify"] is False
    assert replayed["failed_step"] == 2
    assert replayed["steps"][-1]["failure"]["reason"] == "input_mismatch"


def _proof(*steps):
    return {"steps": list(steps), "verify": True, "failed_step": None, "output": None}


def _encode_step(index=1, codec="cp1252", output_hex="E9"):
    return {"index": index, "op": "encode", "codec": codec, "output_hex": output_hex, "verify": True}


def _decode_step(index=2, codec="utf-8", output="雅"):
    return {"index": index, "op": "decode", "codec": codec, "output": output, "verify": True}


def test_compare_proofs_reports_step_difference():
    divergence = chain.compare_proofs(
        _proof(_encode_step(), _decode_step(codec="utf-8")),
        _proof(_encode_step(), _decode_step(codec="latin-1")),
        2,
        {"result": "x", "path_string": "p"},
    )
    assert divergence["kind"] == "step"
    assert divergence["at_step"] == 2


def test_compare_proofs_reports_byte_difference():
    divergence = chain.compare_proofs(
        _proof(_encode_step(output_hex="E9 9B 85")),
        _proof(_encode_step(output_hex="E9 9B 84")),
        2,
        {"result": "x", "path_string": "p"},
    )
    assert divergence["kind"] == "bytes"
    assert divergence["byte_offset"] == 2


def test_compare_proofs_reports_text_difference():
    divergence = chain.compare_proofs(
        _proof(_encode_step(), _decode_step(output="雅")),
        _proof(_encode_step(), _decode_step(output="雅雅")),
        2,
        {"result": "x", "path_string": "p"},
    )
    assert divergence["kind"] == "text"
    assert divergence["char_offset"] == 1


def test_compare_proofs_reports_depth_difference():
    divergence = chain.compare_proofs(
        _proof(_encode_step()),
        _proof(_encode_step(), _decode_step()),
        2,
        {"result": "x", "path_string": "p"},
    )
    assert divergence["kind"] == "depth"
    assert divergence["at_step"] == 2


def test_compare_proofs_reports_no_divergence():
    divergence = chain.compare_proofs(
        _proof(_encode_step(), _decode_step()),
        _proof(_encode_step(), _decode_step()),
        2,
        {"result": "x", "path_string": "p"},
    )
    assert divergence["kind"] == "none"
    assert "no divergence" in divergence["statement"]


# ================================================================== explain 模式
def test_explain_pick_verifies_and_diverges():
    records = _evaluate(_explain(CLASSIC, pick=1))
    assert [record.rule_id for record in records] == [
        spec.RULE_EXPLAIN_VERIFY,
        spec.RULE_EXPLAIN_DIVERGENCE,
    ]
    assert records[0].evidence["verify"] is True
    assert records[0].evidence["rank"] == 1
    assert records[1].evidence["vs_rank"] == 2


def test_explain_default_pick_is_one():
    records = _evaluate(_explain(CLASSIC))
    assert records[0].rule_id == spec.RULE_EXPLAIN_VERIFY
    assert records[0].evidence["rank"] == 1


def test_explain_vs_explicit_rank():
    records = _records(_explain(CLASSIC, pick=1, vs=3), spec.RULE_EXPLAIN_DIVERGENCE)
    assert records[0].evidence["vs_rank"] == 3


def test_explain_all_verifies_every_candidate():
    expected, _chains = chain.search(CLASSIC, encoders=("cp1252",), decoders=("utf-8",))
    records = _records(
        _explain(CLASSIC, source_enc=["cp1252"], target_enc=["utf-8"], all=True),
        spec.RULE_EXPLAIN_VERIFY,
    )
    assert records
    assert len(records) == len(expected)


def test_explain_single_candidate_has_no_second_note():
    records = _evaluate(_explain(CLASSIC, source_enc=["cp1252"], target_enc=["utf-8"]))
    divergence = [record for record in records if record.rule_id == spec.RULE_EXPLAIN_DIVERGENCE]
    assert divergence[0].evidence["note"] == "no_second_candidate"


def test_explain_no_candidate_is_blocking():
    records = _evaluate(_explain("abc"))
    assert records[0].rule_id == spec.RULE_ATTR_NO_CANDIDATE
    assert records[0].verdict == ERROR


def test_explain_pick_out_of_range_is_invalid_input():
    with pytest.raises(ValueError):
        _evaluate(_explain(CLASSIC, pick=10 ** 6))


def test_explain_vs_out_of_range_is_invalid_input():
    with pytest.raises(ValueError):
        _evaluate(_explain(CLASSIC, pick=1, vs=10 ** 6))


def test_explain_all_and_vs_are_mutually_exclusive():
    with pytest.raises(ValueError):
        _evaluate(_explain(CLASSIC, all=True, vs=2))


def test_explain_vs_equal_pick_is_invalid_input():
    with pytest.raises(ValueError):
        _evaluate(_explain(CLASSIC, pick=1, vs=1))


def test_explain_verify_failure_is_blocking(monkeypatch):
    broken = chain.Chain(
        steps=(
            chain.Step(index=1, op="encode", codec="cp1252", input_text="x", output_hex="FF"),
            chain.Step(index=2, op="decode", codec="utf-8", input_hex="FF", output_text="雅"),
        )
    )
    entry = {"rank": 1, "result": "雅", "path_string": "encode:cp1252>decode:utf-8", "depth": 1, "chain": broken}
    monkeypatch.setattr(audit.chain, "search", lambda *args, **kwargs: ([entry], 1))
    records = _evaluate(_explain(CLASSIC, pick=1))
    assert records[0].rule_id == spec.RULE_EXPLAIN_VERIFY_FAILED
    assert records[0].verdict == ERROR
    assert records[0].evidence["failed_step"] == 1


# ================================================================== recover 模式
@pytest.mark.parametrize(
    "text,status,reason",
    [
        ("\ufffd", spec.STATUS_LOST, spec.REASON_REPLACEMENT_CHAR),
        ("锟斤拷", spec.STATUS_LOST, spec.REASON_KUN_JIN_KAO),
        ("烫烫烫", spec.STATUS_NOT_MOJIBAKE, spec.REASON_MSVC_FILL),
        ("屯屯屯", spec.STATUS_NOT_MOJIBAKE, spec.REASON_MSVC_FILL),
        ("a?b", spec.STATUS_LOST, spec.REASON_ENCODE_TRUNCATED),
    ],
)
def test_recover_four_irreversible_classes(text, status, reason):
    records = _evaluate(_recover(text))
    assert len(records) == 1
    assert records[0].evidence["status"] == status
    assert records[0].evidence["reason"] == reason
    assert records[0].verdict == ERROR


def test_recover_replacement_char_reports_offset():
    record = _evaluate(_recover("ab\ufffd"))[0]
    assert record.evidence["loss"]["offset"] == 2
    assert record.evidence["loss"]["step"] == "decode"


def test_recover_kun_jin_kao_reports_repeat():
    record = _evaluate(_recover("锟斤拷锟斤拷"))[0]
    assert record.evidence["loss"]["repeat"] == 2
    assert record.evidence["loss"]["bytes_hex"] == "EF BF BD"


def test_recover_question_mark_reports_encode_step():
    record = _evaluate(_recover("a?b"))[0]
    assert record.evidence["loss"]["step"] == "encode"
    assert record.evidence["loss"]["offset"] == 1


def test_recover_never_invents_characters():
    for text in ("\ufffd", "锟斤拷", "烫烫烫", "a?b"):
        for record in _evaluate(_recover(text)):
            assert record.evidence["recovered"] is None
            assert record.evidence["verify"] is False


def test_recover_classic_text_is_recovered():
    record = _evaluate(_recover(CLASSIC, pick=1))[0]
    assert record.rule_id == spec.RULE_RECOVER_RECOVERED
    assert record.evidence["status"] == spec.STATUS_RECOVERED
    assert record.evidence["recovered"] == CLASSIC_TRUTH
    assert record.evidence["verify"] is True


def test_recover_is_deterministic():
    first = _report(_recover(CLASSIC, pick=1)).as_dict()
    second = _report(_recover(CLASSIC, pick=1)).as_dict()
    assert first == second


def test_recover_requires_pick():
    with pytest.raises(ValueError):
        _evaluate({"mode": "recover", "text": CLASSIC})


def test_recover_pick_out_of_range_is_invalid_input():
    with pytest.raises(ValueError):
        _evaluate(_recover(CLASSIC, pick=10 ** 6))


def test_recover_no_candidate_is_blocking():
    records = _evaluate(_recover("abc", pick=1))
    assert records[0].rule_id == spec.RULE_RECOVER_NO_CANDIDATE
    assert records[0].verdict == ERROR
    assert records[0].evidence["reason"] == spec.REASON_NO_CANDIDATE


def test_silent_drop_is_not_claimed_from_visible_text():
    records = _evaluate(_recover("ab", pick=1))
    assert all(record.evidence.get("reason") != spec.REASON_SILENT_DROP for record in records)


def test_recover_verify_failure_is_suppressed(monkeypatch):
    broken = chain.Chain(
        steps=(
            chain.Step(index=1, op="encode", codec="cp1252", input_text="x", output_hex="FF"),
            chain.Step(index=2, op="decode", codec="utf-8", input_hex="FF", output_text="雅"),
        )
    )
    entry = {"rank": 1, "result": "雅", "path_string": "encode:cp1252>decode:utf-8", "depth": 1, "chain": broken}
    monkeypatch.setattr(audit.chain, "search", lambda *args, **kwargs: ([entry], 1))
    records = _evaluate(_recover(CLASSIC, pick=1))
    assert records[0].rule_id == spec.RULE_EXPLAIN_VERIFY_FAILED
    assert records[0].evidence["recovered"] is None
    assert records[0].evidence["verify"] is False


# ================================================================== file 模式
def test_file_bom_present():
    record = _records({"mode": "file", "bytes_hex": "EF BB BF 61 62 63"}, spec.RULE_FILE_BOM)[0]
    assert record.evidence["present"] is True
    assert record.evidence["kind"] == "utf-8"
    assert record.evidence["byte_length"] == 3


def test_file_bom_absent_is_still_a_check():
    record = _records({"mode": "file", "bytes_hex": "61 62 63"}, spec.RULE_FILE_BOM)[0]
    assert record.evidence["present"] is False
    assert record.verdict == INFO


def test_file_bom_conflict_lists_both_readings():
    records = _evaluate({"mode": "file", "bytes_hex": "EF BB BF E9 9B"})
    conflict = [record for record in records if record.rule_id == spec.RULE_FILE_BOM_CONFLICT]
    assert len(conflict) == 1
    assert conflict[0].verdict == WARN
    assert conflict[0].evidence["as_utf8"]["decodable"] is False
    assert conflict[0].evidence["as_gb18030"]["decodable"] is True


def test_file_utf16_misalignment_is_evidence_only():
    record = _records({"mode": "file", "bytes_hex": "00 41 00"}, spec.RULE_FILE_UTF16_MISALIGNMENT)[0]
    assert record.evidence["odd_length"] is True
    assert record.evidence["shift_offset"] == 1
    assert record.evidence["unshifted"]["decodable"] is False


def test_file_utf16_even_length_is_silent():
    records = _records({"mode": "file", "bytes_hex": "00 41 00 42"}, spec.RULE_FILE_UTF16_MISALIGNMENT)
    assert records == []


def test_file_zip_name_uses_declared_utf8_flag():
    data = _zip_bytes("café.txt", utf8_flag=True)
    records = _evaluate({"mode": "file", "bytes_hex": chain.hexdump(data)})
    names = [record for record in records if record.rule_id == spec.RULE_FILE_ZIP_NAME]
    ambiguous = [record for record in records if record.rule_id == spec.RULE_FILE_ZIP_NAME_AMBIGUOUS]
    assert names[0].evidence["flag_utf8"] is True
    assert names[0].evidence["name"] == "café.txt"
    assert ambiguous == []


def test_file_zip_without_flag_lists_two_interpretations():
    data = _zip_bytes("café.txt", utf8_flag=False)
    records = _evaluate({"mode": "file", "bytes_hex": chain.hexdump(data)})
    names = [record for record in records if record.rule_id == spec.RULE_FILE_ZIP_NAME]
    ambiguous = [record for record in records if record.rule_id == spec.RULE_FILE_ZIP_NAME_AMBIGUOUS]
    assert names[0].evidence["interpretation"] == "cp437"
    assert len(ambiguous) == 1
    assert ambiguous[0].evidence["alternatives"][0]["codec"] == "utf-8"


def test_file_zip_never_extracts_member_content():
    data = _zip_bytes("café.txt", payload="member-content")
    sections = probe.inspect_bytes(data)
    assert "member-content" not in json.dumps(sections, ensure_ascii=False)


def test_file_csv_reports_candidates_and_delimiter():
    data = b"a,b,c\n1,2,3\n"
    record = _records(
        {"mode": "file", "bytes_hex": chain.hexdump(data), "preset": "csv-excel-win"},
        spec.RULE_FILE_CSV_CANDIDATE,
    )[0]
    assert record.evidence["delimiter"] == ","
    assert [item["codec"] for item in record.evidence["candidates"]] == [
        "cp1252",
        "gbk",
        "shift_jis",
    ]


def test_file_zip_preset_suppresses_other_sections():
    data = _zip_bytes("café.txt")
    sections = probe.inspect_bytes(data, preset="zip-names")
    assert "bom" not in sections
    assert "utf16_misalignment" not in sections
    assert "zip_names" in sections


def test_file_utf16_preset_suppresses_zip_and_csv():
    sections = probe.inspect_bytes(b"\x00\x41\x00", preset="utf16")
    assert "utf16_misalignment" in sections
    assert "zip_names" not in sections
    assert "csv_candidates" not in sections


def test_file_mutations_flag_is_false():
    assert probe.inspect_bytes(b"abc")["mutates_input"] is False


def test_file_rejects_unknown_preset():
    with pytest.raises(ValueError):
        probe.inspect_bytes(b"abc", preset="nope")


def test_file_requires_bytes_hex():
    with pytest.raises(ValueError):
        _evaluate({"mode": "file"})


def test_file_rejects_bad_hex():
    with pytest.raises(ValueError):
        _evaluate({"mode": "file", "bytes_hex": "ZZ"})


def test_file_bom_conflict_is_not_blocking():
    assert _report({"mode": "file", "bytes_hex": "EF BB BF E9 9B"}).exit_code() == EXIT_OK


# ================================================================== scan 模式
def _scan(files, baseline=None, existing=None):
    return {
        "mode": "scan",
        "files": files,
        "baseline": {"files": baseline or []},
        "existing_paths": existing if existing is not None else [item["path"] for item in files],
    }


def test_scan_clean_corpus_is_info_only():
    records = _evaluate(_scan([{"path": "clean/en-01.md", "text": "hello\nworld\n"}]))
    assert [record.rule_id for record in records] == [spec.RULE_SCAN_CLEAN]
    assert records[0].verdict == INFO
    assert records[0].evidence["files_scanned"] == 1


def test_scan_polluted_line_is_new_hit():
    records = _evaluate(_scan([{"path": "polluted/cn-01.md", "text": "hello\né›…é›…\n"}]))
    new = [record for record in records if record.rule_id == spec.RULE_SCAN_NEW]
    assert len(new) == 1
    assert new[0].path == "polluted/cn-01.md:2"
    assert new[0].verdict == ERROR
    assert "雅雅" in [item["result"] for item in new[0].evidence["candidates"]]


def test_scan_new_hit_is_blocking():
    assert _report(_scan([{"path": "a.md", "text": "é›…\n"}])).exit_code() == EXIT_BLOCKED


def test_scan_baselined_hit_is_not_new():
    files = [{"path": "polluted/cn-01.md", "text": "é›…\n"}]
    records = _evaluate(
        _scan(files, baseline=[{"path": "polluted/cn-01.md", "allowed_hits": []}])
    )
    assert [record.rule_id for record in records] == [spec.RULE_SCAN_BASELINED]
    assert records[0].verdict == INFO


def test_scan_stale_is_warn_and_not_blocking():
    files = [{"path": "clean/en-01.md", "text": "hello\n"}]
    subject = _scan(files, baseline=[{"path": "polluted/gone.md"}], existing=["clean/en-01.md"])
    records = _evaluate(subject)
    assert [record.rule_id for record in records] == [spec.RULE_SCAN_STALE]
    assert records[0].verdict == WARN
    assert _report(subject).exit_code() == EXIT_OK


def test_scan_empty_lines_are_skipped():
    records = _evaluate(_scan([{"path": "a.md", "text": "\n\n  \n"}]))
    assert [record.rule_id for record in records] == [spec.RULE_SCAN_CLEAN]


def test_scan_line_hit_thresholds():
    assert audit.line_hit("hello") is None
    hit = audit.line_hit(CLASSIC_DOUBLE)
    assert hit["input_readability"] < spec.INPUT_READABILITY_BELOW
    assert hit["candidates"]
    assert hit["candidates"][0]["readability"] >= spec.CANDIDATE_READABILITY_AT_LEAST


def test_scan_line_hit_is_none_for_blank():
    assert audit.line_hit("   ") is None


def test_scan_requires_files():
    with pytest.raises(ValueError):
        _evaluate({"mode": "scan", "baseline": {"files": []}, "existing_paths": []})


def test_scan_requires_baseline_object():
    with pytest.raises(ValueError):
        _evaluate({"mode": "scan", "files": [], "existing_paths": []})


def test_scan_requires_existing_paths():
    with pytest.raises(ValueError):
        _evaluate({"mode": "scan", "files": [], "baseline": {"files": []}})


def test_scan_rejects_malformed_file_entry():
    with pytest.raises(ValueError):
        _evaluate(_scan([{"path": "a.md"}]))


def test_scan_rejects_malformed_baseline_entry():
    subject = _scan([])
    subject["baseline"] = {"files": ["oops"]}
    with pytest.raises(ValueError):
        _evaluate(subject)


def test_scan_clean_and_stale_together_are_reported():
    subject = _scan(
        [{"path": "clean/a.md", "text": "ok\n"}],
        baseline=[{"path": "clean/gone.md"}],
        existing=["clean/a.md"],
    )
    assert [record.rule_id for record in _evaluate(subject)] == [spec.RULE_SCAN_STALE]


# ================================================================== 入口与契约
def test_unknown_mode_is_invalid_input():
    with pytest.raises(ValueError):
        _evaluate({"mode": "nope"})


def test_missing_mode_is_invalid_input():
    with pytest.raises(ValueError):
        _evaluate({"text": CLASSIC})


def test_missing_rule_in_basis_is_contract_violation():
    with pytest.raises(RuleMissing):
        _evaluate(_attr(CLASSIC), basis=Basis.empty("1"))


def test_report_ids_are_unique_for_attr():
    report = _report(_attr(CLASSIC))
    ids = [record.id for record in report.records]
    assert len(ids) == len(set(ids))


def test_report_ids_are_unique_for_scan():
    report = _report(_scan([{"path": "a.md", "text": "é›…é›…\né›…\n"}]))
    ids = [record.id for record in report.records]
    assert len(ids) == len(set(ids))


def test_every_record_has_a_complete_basis_ref():
    for subject in (
        _attr(CLASSIC),
        _explain(CLASSIC),
        _recover(CLASSIC),
        {"mode": "file", "bytes_hex": "EF BB BF 61"},
        _scan([{"path": "a.md", "text": "é›…\n"}]),
    ):
        for record in _evaluate(subject):
            assert record.basis is not None
            assert record.basis.rule_version == "1"


# ================================================================== CLI 退出码
def test_cli_sample_exits_zero(capsys):
    code = cli.main(["check", SLUG, "--input", str(SAMPLE), "--basis", str(BASIS_PATH), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert payload["organ"] == SLUG
    assert payload["summary"]["blocking"] == 0


def test_cli_recover_lost_exits_one(tmp_path, capsys):
    path = tmp_path / "lost.json"
    path.write_text(
        json.dumps({"mode": "recover", "text": "锟斤拷", "pick": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    code = cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_BLOCKED
    assert payload["summary"]["blocking"] == 1


def test_cli_unknown_mode_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "nope"}), encoding="utf-8")
    code = cli.main(["check", SLUG, "--input", str(path), "--basis", str(BASIS_PATH), "--json"])
    assert code == EXIT_INPUT


def test_cli_missing_rule_exits_three(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps({"mode": "attr", "text": CLASSIC}), encoding="utf-8")
    empty = tmp_path / "empty.basis.json"
    empty.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    code = cli.main(["check", SLUG, "--input", str(path), "--basis", str(empty), "--json"])
    assert code == EXIT_CONTRACT


def test_cli_basis_is_optional_and_uses_shipped_copy(tmp_path, capsys):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps({"mode": "attr", "text": CLASSIC}), encoding="utf-8")
    code = cli.main(["check", SLUG, "--input", str(path), "--json"])
    assert code == EXIT_OK


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


def test_organ_does_not_open_files_or_read_environment():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                hits.append((path.name, "open"))
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
                hits.append((path.name, node.attr))
            if isinstance(node, ast.Attribute) and node.attr in ("time", "now", "utcnow"):
                hits.append((path.name, node.attr))
    assert hits == []


def test_organ_does_not_import_the_old_package():
    hits = []
    for path in ORGAN_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "mojibake_forensics":
                        hits.append((path.name, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "mojibake_forensics":
                    hits.append((path.name, node.module))
    assert hits == []


def test_organ_data_lives_under_package_data_directory():
    assert BASIS_PATH.parent == DATA_DIR
    assert THRESHOLDS_PATH.parent == DATA_DIR
    assert not list(ORGAN_DIR.glob("*.json"))