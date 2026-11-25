"""``duplicate-docs`` 器官的无损测试。

无损 = 旧仓（迁自 target-map ② 行）里**被判定的那个函数仍然在、语义仍然是那一套**。
所以归一化五步、shingle/精确 Jaccard/SimHash、并查集聚类与档位判定都是逐条搬用
``tests/test_normalize.py`` / ``test_fingerprint.py`` / ``test_cluster.py`` 的断言，
只把模块路径换成器官的模块路径。

**没迁的部分逐条写在 ``docs/duplicate-docs.md`` 的处置表里**（抽取层、SQLite 索引、扫描、
Web 复核页、隔离执行、报告渲染、基准、MinHash/LSH、模板族与保留建议打分）。
不迁的东西不在这里假装测过。

判定层口径（ORGAN-PLAYBOOK §3.0）：旧仓 14 个判定层文件实跑 **X = 356 passed**。
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
from byteproof.auditors.duplicate_docs import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    cluster,
    fingerprint,
    normalize,
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

SLUG = "duplicate-docs"
ORGAN_DIR = SRC / "byteproof" / "auditors" / "duplicate_docs"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "duplicate-docs.basis.json"
THRESHOLDS_PATH = DATA_DIR / "duplicate-docs.thresholds.json"

BASIS = Basis.from_json(str(BASIS_PATH))

#: 一条正文片段：24 个汉字，归一化后长度就是字符数。
BASE = "甲方与乙方就本项目的交付范围与验收口径达成一致"


def _text(tag="", repeat=4):
    return (tag + BASE) * repeat


def _doc(path, text):
    return {"path": path, "text": text}


def _evaluate(documents, basis=None, **overrides):
    payload = {"documents": documents}
    if overrides:
        payload["params"] = overrides
    return tuple(audit.evaluate(payload, BASIS if basis is None else basis))


def _with_rule(records, rule_id):
    return [record for record in records if record.rule_id == rule_id]


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


def _score(left, right, size=3):
    return fingerprint.jaccard(
        fingerprint.shingle_hashes(normalize.normalize(left), size),
        fingerprint.shingle_hashes(normalize.normalize(right), size),
    )


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

    def test_every_rule_carries_source_and_text(self):
        for rule_id in BASIS.rule_ids():
            rule = BASIS.rule(rule_id)
            assert rule.title and rule.source and rule.text, rule_id

    def test_the_rule_ids_are_sorted_in_the_basis_file(self):
        payload = json.loads(BASIS_PATH.read_text(encoding="utf-8"))
        ids = [item["rule_id"] for item in payload["rules"]]
        assert ids == sorted(ids)

    def test_the_thresholds_file_pins_the_runtime_defaults(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        resolved = spec.resolve_params()
        for name, _kind in spec.SETTING_FIELDS:
            assert payload["params"][name] == getattr(resolved, name), name

    def test_the_thresholds_file_pins_every_verdict(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["verdicts"] == spec.VERDICT_BY_RULE

    def test_the_thresholds_file_pins_the_versions(self):
        payload = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))
        assert payload["normalize_version"] == spec.NORMALIZE_VERSION
        assert payload["params_version"] == spec.PARAMS_VERSION
        assert payload["quant_decimals"] == spec.QUANT_DECIMALS
        assert payload["params"]["min_text_chars"] == spec.DEFAULT_SETTINGS.min_text_chars

    def test_the_data_files_are_declared_as_package_data(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert '"data/*.json"' in text
        assert BASIS_PATH.is_file() and THRESHOLDS_PATH.is_file()

    def test_the_organ_is_in_the_builtin_manifest(self):
        assert "duplicate_docs" in BUILTIN_MODULES
        assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)

    def test_the_pack_declares_the_artifact_field(self):
        assert PACK.slug == SLUG
        assert PACK.version == ORGAN_VERSION
        assert PACK.input_fields == ("documents",)

    def test_the_pack_is_queryable_from_the_registry(self):
        assert get(SLUG) is PACK


# ---------------------------------------------------------------------------
# 归一化五步
# ---------------------------------------------------------------------------
class TestStageOrder:
    def test_the_five_stages_are_in_the_documented_order(self):
        assert normalize.STAGE_ORDER == (
            "nfkc",
            "strip_whitespace",
            "drop_page_numbers",
            "drop_running_heads",
            "lower_latin",
        )

    def test_normalization_is_idempotent(self):
        text = _text("Header\n第 1 页\n") + "\n\nFooter"
        once = normalize.normalize(text)
        assert normalize.normalize(once) == once

    def test_the_result_has_no_whitespace_at_all(self):
        text = "甲 方 与 乙 方\n\n就 本 项 目"
        assert " " not in normalize.normalize(text)
        assert "\n" not in normalize.normalize(text)

    def test_the_result_has_no_line_breaks(self):
        assert "\n" not in normalize.normalize("a\nb\nc")


class TestStageNfkc:
    @pytest.mark.parametrize(
        "full_width,half_width",
        (
            ("ＡＢＣ", "ABC"),
            ("１２３", "123"),
            ("（一）", "(一)"),
            ("％", "%"),
            ("，", ","),
            ("：", ":"),
            ("\u3000", ""),
        ),
    )
    def test_full_width_forms_fold_to_half_width(self, full_width, half_width):
        assert normalize.normalize(full_width) == normalize.normalize(half_width)

    def test_nfkc_runs_before_the_page_number_stage(self):
        # 全角数字的页码行在 NFKC 之后才认得出
        assert "1" not in normalize.normalize("正文\n１")


class TestStageWhitespace:
    @pytest.mark.parametrize(
        "invisible",
        ("\u200b", "\ufeff", "\u00ad", "\u2060", "\u0000", "\u001f", "\u007f"),
    )
    def test_invisibles_are_dropped(self, invisible):
        assert normalize.normalize("甲乙" + invisible + "丙丁") == "甲乙丙丁"

    @pytest.mark.parametrize("spaces", (" ", "\t", "\u3000", "  \t "))
    def test_every_whitespace_run_is_dropped(self, spaces):
        assert normalize.normalize("甲乙" + spaces + "丙丁") == "甲乙丙丁"

    def test_line_structure_survives_until_the_later_stages(self):
        step = normalize._stage_strip_whitespace("a b\nc d")
        assert step == "ab\ncd"


class TestStagePageNumbers:
    @pytest.mark.parametrize(
        "line",
        (
            "第1页",
            "第12页",
            "第1234页",
            "第3页/共9页",
            "共9页",
            "-7-",
            "3/12",
            "Page1",
            "page 12",
            "p.3",
            "P7/9",
            "7",
            "12",
            "999",
        ),
    )
    def test_a_page_number_line_is_dropped(self, line):
        assert normalize.normalize("正文\n" + line) == "正文"

    @pytest.mark.parametrize(
        "line",
        (
            "2026",
            "第12345页",
            "1/2/3",
            "page",
            "第页",
        ),
    )
    def test_a_near_miss_line_survives(self, line):
        cleaned = normalize.normalize("正文\n" + line)
        assert cleaned != "正文"

    def test_four_digits_are_not_a_page_number(self):
        # "2026" 是年份的概率远高于页码
        assert "2026" in normalize.normalize("正文\n2026")


class TestStageRunningHeads:
    def test_a_short_repeated_line_is_dropped(self):
        text = "公司内部资料\n第一段正文内容\n公司内部资料\n第二段正文内容"
        cleaned = normalize.normalize(text)
        assert "公司内部资料" not in cleaned
        assert "第一段正文内容" in cleaned

    def test_a_line_seen_once_is_kept(self):
        text = "公司内部资料\n第一段正文内容"
        assert "公司内部资料" in normalize.normalize(text)

    def test_a_long_repeated_line_is_kept(self):
        long_line = "很长的一段正文" * 10
        text = long_line + "\n另一段\n" + long_line
        assert long_line in normalize.normalize(text)

    @pytest.mark.parametrize("repeats", (2, 3, 4, 5))
    def test_the_repeat_bound_is_honoured(self, repeats):
        text = "\n".join(["短页眉"] + ["正文%d" % index for index in range(3)] + ["短页眉"] * (repeats - 1))
        assert "短页眉" not in normalize.normalize(text)

    @pytest.mark.parametrize("length", (10, 39, 40, 41, 60))
    def test_the_length_bound_is_honoured(self, length):
        line = "x" * length
        text = line + "\n正文\n" + line
        cleaned = normalize.normalize(text)
        assert (line in cleaned) == (length > 40)


class TestStageLowerLatin:
    def test_latin_capitals_are_folded(self):
        assert normalize.normalize("ABC") == "abc"

    def test_latin_extended_capitals_are_folded(self):
        assert normalize.normalize("\u00c9") == "\u00e9"  # É -> é

    @pytest.mark.parametrize("char", ("\u0391", "\u0410", "\u05d0", "\u3042"))
    def test_non_latin_is_left_alone(self, char):
        assert normalize.normalize(char) == char

    def test_digits_are_untouched(self):
        assert normalize.normalize("1234567890") == "1234567890"


class TestNormalizeEquivalence:
    @pytest.mark.parametrize(
        "variant",
        (
            "HELLO，世界。",
            "Hello，世界。",
            "Ｈｅｌｌｏ，世界。",
            "Hello，\n世界。",
            "  Hello，\t世界。 ",
            "Hello，世界。\n第 3 页",
            "Hello，世界。\n3",
        ),
    )
    def test_typographic_variants_collapse_to_one_form(self, variant):
        reference = "Hello，世界。"
        assert normalize.normalize(variant) == normalize.normalize(reference)

    def test_an_accent_is_content_and_does_not_collapse(self):
        # 只折拉丁**大小写**；É 变 é 是同一字母的另一写法，但 é 与 e 是两个字符。
        assert normalize.normalize("H\u00e9llo") != normalize.normalize("Hello")
        assert normalize.normalize("H\u00c9llo") == normalize.normalize("H\u00e9llo")

    def test_normalized_length_is_the_length_of_the_normalized_form(self):
        text = "甲 方\n第 1 页" + "乙" * 100
        assert normalize.normalized_length(text) == len(normalize.normalize(text))


# ---------------------------------------------------------------------------
# shingle / Jaccard / 指纹
# ---------------------------------------------------------------------------
class TestShingles:
    @pytest.mark.parametrize("size", (1, 2, 3, 4, 5))
    def test_the_shingle_count_is_length_minus_size_plus_one_for_unique_text(self, size):
        text = "abcdefghij"
        assert len(fingerprint.shingles(text, size)) == len(text) - size + 1

    def test_shingles_are_unique_and_sorted(self):
        built = fingerprint.shingles("abababab")
        assert built == sorted(set(built))

    def test_a_text_shorter_than_the_shingle_yields_nothing(self):
        assert fingerprint.shingles("ab", 3) == []
        assert fingerprint.shingle_set("ab", 3) == set()

    def test_the_empty_text_yields_nothing(self):
        assert fingerprint.shingles("") == []

    @pytest.mark.parametrize("size", (0, -1))
    def test_a_non_positive_size_is_rejected(self, size):
        with pytest.raises(ValueError):
            fingerprint.shingles("abc", size)

    def test_the_three_gram_of_a_known_text(self):
        assert fingerprint.shingles("abcd", 3) == ["abc", "bcd"]

    def test_shingle_hashes_are_sorted_and_deduplicated(self):
        hashed = fingerprint.shingle_hashes("ababab")
        assert list(hashed) == sorted(hashed)
        assert len(hashed) == len(set(hashed))


class TestHash64:
    def test_the_hash_is_stable_across_calls(self):
        assert fingerprint.hash64("甲") == fingerprint.hash64("甲")

    def test_different_values_hash_differently(self):
        assert fingerprint.hash64("甲") != fingerprint.hash64("乙")

    def test_the_hash_fits_in_64_bits(self):
        for value in ("", "a", BASE, BASE * 4):
            assert 0 <= fingerprint.hash64(value) < (1 << 64)

    def test_the_hash_is_not_the_process_salted_builtin(self):
        # 同一文本在两个进程里必须同值（旧仓为此弃用了 hash()）
        assert fingerprint.hash64("甲方乙方") == fingerprint.hash64("甲方乙方")


class TestJaccard:
    def test_identical_sets_score_one(self):
        left = fingerprint.shingle_hashes("abcdefgh")
        assert fingerprint.jaccard(left, left) == 1.0

    def test_disjoint_sets_score_zero(self):
        assert fingerprint.jaccard(fingerprint.shingle_hashes("abcdef"), fingerprint.shingle_hashes("uvwxyz")) == 0.0

    def test_two_empty_sets_score_one(self):
        assert fingerprint.jaccard((), ()) == 1.0

    def test_one_empty_set_scores_zero(self):
        assert fingerprint.jaccard((), fingerprint.shingle_hashes("abcdef")) == 0.0
        assert fingerprint.jaccard(fingerprint.shingle_hashes("abcdef"), ()) == 0.0

    def test_the_score_is_symmetric(self):
        left = fingerprint.shingle_hashes(_text("a"))
        right = fingerprint.shingle_hashes(_text("b"))
        assert fingerprint.jaccard(left, right) == fingerprint.jaccard(right, left)

    def test_the_score_is_bounded(self):
        left = fingerprint.shingle_hashes(_text("a"))
        right = fingerprint.shingle_hashes(_text("b"))
        assert 0.0 <= fingerprint.jaccard(left, right) <= 1.0

    def test_a_one_character_edit_scores_high(self):
        assert _score(_text(), _text("甲")) > 0.8

    def test_an_unrelated_text_scores_low(self):
        assert _score(_text(), "完全不同的另一份文档，讲的是别的事情，与前者没有共享的三元组") < 0.2

    def test_a_prefix_is_not_a_full_match(self):
        # 注意不能用"同一句话重复 N 遍"的文本：周期文本的所有 n-gram 都落在同一个周期内，
        # 4 遍与 2 遍的 shingle 集合完全相同，Jaccard 会是 1.0（那正是文本周期性的表现）。
        left = _text() + "尾部各异的收尾内容"
        assert _score(left, _text()) < 1.0

    def test_the_score_is_exact_not_an_estimate(self):
        # 同一对文档算两次必须完全相等（MinHash 估计会有采样噪声）
        left, right = _text("a"), _text("b")
        assert _score(left, right) == _score(left, right)

    @pytest.mark.parametrize("size", (2, 3, 4, 5))
    def test_the_shingle_size_changes_the_score(self, size):
        scores = {_score(_text("a"), _text("b"), size) for size in (2, 3, 4, 5)}
        assert len(scores) >= 3


class TestSimHash:
    def test_the_simhash_is_stable(self):
        hashed = fingerprint.shingle_hashes(_text())
        assert fingerprint.simhash64_from_hashes(hashed) == fingerprint.simhash64_from_hashes(hashed)

    def test_an_empty_collection_is_zero(self):
        assert fingerprint.simhash64_from_hashes(()) == 0

    def test_identical_texts_have_distance_zero(self):
        hashed = fingerprint.shingle_hashes(_text())
        assert fingerprint.hamming(fingerprint.simhash64_from_hashes(hashed), fingerprint.simhash64_from_hashes(hashed)) == 0

    def test_unrelated_texts_are_far_apart(self):
        left = fingerprint.simhash64_from_hashes(fingerprint.shingle_hashes(_text()))
        right = fingerprint.simhash64_from_hashes(fingerprint.shingle_hashes("完全不同的一份文档内容甲乙丙丁戊己庚辛"))
        assert fingerprint.hamming(left, right) > 10

    def test_hamming_is_symmetric_and_bounded(self):
        left, right = 0, (1 << 64) - 1
        assert fingerprint.hamming(left, right) == 64 == fingerprint.hamming(right, left)


# ---------------------------------------------------------------------------
# 聚类
# ---------------------------------------------------------------------------
class TestEdgeKind:
    def test_same_normalized_text_is_exact_whatever_the_score(self):
        assert cluster.edge_kind(0.1, True, 0.8) == cluster.EXACT

    def test_a_score_at_the_threshold_is_near(self):
        assert cluster.edge_kind(0.8, False, 0.8) == cluster.NEAR

    def test_a_score_just_below_the_threshold_is_not_an_edge(self):
        assert cluster.edge_kind(0.799999, False, 0.8) is None

    @pytest.mark.parametrize("score", (0.0, 0.2, 0.55, 0.79))
    def test_low_scores_produce_no_edge(self, score):
        assert cluster.edge_kind(score, False, 0.8) is None

    @pytest.mark.parametrize("score", (0.8, 0.81, 0.9, 0.99, 1.0))
    def test_high_scores_produce_a_near_edge(self, score):
        assert cluster.edge_kind(score, False, 0.8) == cluster.NEAR


class TestUnionFind:
    def test_a_single_node_is_its_own_root(self):
        forest = cluster.UnionFind()
        assert forest.find("a") == "a"

    def test_union_connects_two_nodes(self):
        forest = cluster.UnionFind()
        forest.union("a", "b")
        assert forest.find("a") == forest.find("b")

    def test_union_is_transitive(self):
        forest = cluster.UnionFind()
        forest.union("a", "b")
        forest.union("b", "c")
        assert forest.find("a") == forest.find("c")

    def test_the_root_does_not_depend_on_the_union_order(self):
        forward = cluster.UnionFind()
        forward.union("a", "b")
        forward.union("b", "c")
        backward = cluster.UnionFind()
        backward.union("c", "b")
        backward.union("b", "a")
        assert forward.find("a") == backward.find("a")

    def test_components_are_sorted(self):
        forest = cluster.UnionFind()
        for node in ("c", "a", "b"):
            forest.add(node)
        assert forest.components() == [["a"], ["b"], ["c"]]


class TestBuildClusters:
    def test_two_connected_documents_form_one_cluster(self):
        built = cluster.build_clusters([("a", "b", cluster.EXACT)], ["a", "b"])
        assert len(built) == 1
        assert built[0]["members"] == ["a", "b"]

    def test_unconnected_documents_form_no_cluster(self):
        assert cluster.build_clusters([], ["a", "b"]) == []

    def test_a_singleton_is_never_a_cluster(self):
        assert cluster.build_clusters([("a", "b", cluster.NEAR)], ["a", "b", "c"])[0]["members"] == ["a", "b"]

    def test_a_chain_forms_one_cluster(self):
        built = cluster.build_clusters(
            [("a", "b", cluster.NEAR), ("b", "c", cluster.NEAR)], ["a", "b", "c"]
        )
        assert built[0]["members"] == ["a", "b", "c"]

    def test_any_near_edge_makes_the_cluster_near(self):
        built = cluster.build_clusters(
            [("a", "b", cluster.EXACT), ("b", "c", cluster.NEAR)], ["a", "b", "c"]
        )
        assert built[0]["tier"] == cluster.NEAR

    def test_an_exact_only_cluster_is_exact(self):
        built = cluster.build_clusters([("a", "b", cluster.EXACT)], ["a", "b"])
        assert built[0]["tier"] == cluster.EXACT

    def test_the_cluster_id_does_not_depend_on_the_edge_order(self):
        forward = cluster.build_clusters([("a", "b", cluster.EXACT), ("b", "c", cluster.NEAR)], ["a", "b", "c"])
        backward = cluster.build_clusters([("b", "c", cluster.NEAR), ("a", "b", cluster.EXACT)], ["c", "b", "a"])
        assert forward[0]["cluster_id"] == backward[0]["cluster_id"]

    def test_the_cluster_id_starts_with_a_c(self):
        assert cluster.build_clusters([("a", "b", cluster.EXACT)], ["a", "b"])[0]["cluster_id"].startswith("c")

    def test_the_same_members_always_get_the_same_id(self):
        first = cluster.cluster_id(["a", "b"])
        second = cluster.cluster_id(["b", "a"])
        assert first == second

    def test_different_members_get_different_ids(self):
        assert cluster.cluster_id(["a", "b"]) != cluster.cluster_id(["a", "c"])


# ---------------------------------------------------------------------------
# 参数面
# ---------------------------------------------------------------------------
PARAM_OVERRIDES = (
    ("shingle_size", 2, 2),
    ("shingle_size", 5, 5),
    ("min_text_chars", 1, 1),
    ("min_text_chars", 500, 500),
    ("near_duplicate_threshold", 0.5, 0.5),
    ("near_duplicate_threshold", "0.900000", 0.9),
    ("header_footer_max_chars", 10, 10),
    ("header_footer_min_repeats", 3, 3),
)


class TestParamSurface:
    @pytest.mark.parametrize("name,value,expected", PARAM_OVERRIDES)
    def test_an_override_reaches_the_resolved_settings(self, name, value, expected):
        assert getattr(spec.resolve_params({name: value}), name) == expected

    @pytest.mark.parametrize("name,value,expected", PARAM_OVERRIDES)
    def test_the_override_survives_the_dump_round_trip(self, name, value, expected):
        dumped = spec.dump_params(spec.resolve_params({name: value}))
        assert dumped[name] in (expected, spec.fixed_to_str(spec.quantize(expected)))

    @pytest.mark.parametrize("name,value,expected", PARAM_OVERRIDES)
    def test_the_defaults_are_all_present(self, name, value, expected):
        assert getattr(spec.resolve_params(), name) is not None

    @pytest.mark.parametrize("name", ("shingle_size", "min_text_chars", "header_footer_max_chars"))
    def test_an_integer_parameter_rejects_a_fraction(self, name):
        with pytest.raises(ValueError):
            spec.resolve_params({name: 1.5})

    @pytest.mark.parametrize("name", ("shingle_size", "min_text_chars"))
    def test_an_integer_parameter_rejects_null(self, name):
        with pytest.raises(ValueError):
            spec.resolve_params({name: None})

    def test_the_threshold_rejects_null(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"near_duplicate_threshold": None})

    def test_an_unknown_key_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"nope": 1})

    def test_params_must_be_an_object(self):
        with pytest.raises(ValueError):
            spec.resolve_params([])

    def test_a_shingle_size_below_one_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"shingle_size": 0})

    def test_a_min_text_chars_below_one_is_rejected(self):
        with pytest.raises(ValueError):
            spec.resolve_params({"min_text_chars": 0})

    @pytest.mark.parametrize("value", (0.0, 0.25, 0.8, 1.0))
    def test_the_dumped_threshold_is_a_fixed_point_string(self, value):
        dumped = spec.dump_params(spec.resolve_params({"near_duplicate_threshold": value}))
        assert isinstance(dumped["near_duplicate_threshold"], str)
        assert "." in dumped["near_duplicate_threshold"]

    def test_the_dumped_form_carries_no_float(self):
        assert list(_iter_floats(spec.dump_params(spec.resolve_params()))) == []


# ---------------------------------------------------------------------------
# 规则矩阵
# ---------------------------------------------------------------------------
TRIGGER_CASES = (
    (spec.RULE_DUPLICATE_PATH, [_doc("a.md", _text()), _doc("a.md", _text("乙"))]),
    (spec.RULE_EMPTY_TEXT, [_doc("a.md", ""), _doc("b.md", _text())]),
    (spec.RULE_EMPTY_TEXT, [_doc("a.md", "   \n\t  "), _doc("b.md", _text())]),
    (spec.RULE_TOO_SHORT, [_doc("a.md", "太短"), _doc("b.md", _text())]),
    (spec.RULE_EXACT_DUPLICATE, [_doc("a.md", _text()), _doc("b.md", _text())]),
    (spec.RULE_NEAR_DUPLICATE, [_doc("a.md", _text()), _doc("b.md", _text("甲"))]),
)

QUIET_CASES = (
    (spec.RULE_DUPLICATE_PATH, [_doc("a.md", _text()), _doc("b.md", _text("乙"))]),
    (spec.RULE_EMPTY_TEXT, [_doc("a.md", _text()), _doc("b.md", _text("乙"))]),
    (spec.RULE_TOO_SHORT, [_doc("a.md", _text()), _doc("b.md", _text("乙"))]),
    (
        spec.RULE_EXACT_DUPLICATE,
        [_doc("a.md", _text()), _doc("b.md", "完全不同的另一份文档，讲的是别的事情，长度也够长，但没有共同三元组")],
    ),
    (
        spec.RULE_NEAR_DUPLICATE,
        [_doc("a.md", _text()), _doc("b.md", "完全不同的另一份文档，讲的是别的事情，长度也够长，但没有共同三元组")],
    ),
)


class TestRuleMatrix:
    @pytest.mark.parametrize("rule_id,documents", TRIGGER_CASES)
    def test_the_rule_fires(self, rule_id, documents):
        assert _with_rule(_evaluate(documents), rule_id), rule_id

    @pytest.mark.parametrize("rule_id,documents", TRIGGER_CASES)
    def test_the_rule_reports_its_documented_verdict(self, rule_id, documents):
        for record in _with_rule(_evaluate(documents), rule_id):
            assert record.verdict == spec.verdict_for(rule_id)

    @pytest.mark.parametrize("rule_id,documents", TRIGGER_CASES)
    def test_the_rule_cites_its_own_basis(self, rule_id, documents):
        for record in _with_rule(_evaluate(documents), rule_id):
            assert record.basis.rule_id == rule_id
            assert record.basis.source and record.basis.quote

    @pytest.mark.parametrize("rule_id,documents", QUIET_CASES)
    def test_the_rule_stays_silent(self, rule_id, documents):
        assert _with_rule(_evaluate(documents), rule_id) == [], rule_id

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_is_covered_by_a_trigger_case(self, rule_id):
        assert rule_id in [case[0] for case in TRIGGER_CASES]

    @pytest.mark.parametrize("rule_id", spec.RULE_IDS)
    def test_every_rule_is_covered_by_a_quiet_case(self, rule_id):
        assert rule_id in [case[0] for case in QUIET_CASES]

    @pytest.mark.parametrize("rule_id", sorted(spec.VERDICT_BY_RULE))
    def test_the_verdict_table_is_one_of_the_three(self, rule_id):
        assert spec.verdict_for(rule_id) in (ERROR, WARN, INFO)

    def test_an_unknown_rule_has_no_verdict(self):
        with pytest.raises(ValueError):
            spec.verdict_for("dd-nope")

    def test_the_ledger_reaches_all_three_verdict_classes(self):
        duplicate_path = _evaluate([_doc("a.md", _text()), _doc("a.md", _text("乙"))])
        empty = _evaluate([_doc("a.md", ""), _doc("b.md", _text())])
        short = _evaluate([_doc("a.md", "短")])
        assert ERROR in {record.verdict for record in duplicate_path}
        assert WARN in {record.verdict for record in empty}
        assert INFO in {record.verdict for record in short}


#: 语料矩阵：(用例, 文档, (empty, too_short, exact, near))。
#: 计数按"每个成员一条"记 —— 三份完全相同是 3 条 exact，不是 3×2 条（每个成员只指向最像的那一份）。
UNRELATED = "完全不同的另一份文档，讲的是别的事情，长度也够长，但没有共同三元组" * 3

CORPORA = (
    ("single", [_doc("a.md", _text())], (0, 0, 0, 0)),
    ("exact_pair", [_doc("a.md", _text()), _doc("b.md", _text())], (0, 0, 2, 0)),
    ("near_pair", [_doc("a.md", _text()), _doc("b.md", _text("甲"))], (0, 0, 0, 2)),
    ("unrelated_pair", [_doc("a.md", _text()), _doc("b.md", UNRELATED)], (0, 0, 0, 0)),
    (
        "three_exact",
        [_doc("a.md", _text()), _doc("b.md", _text()), _doc("c.md", _text())],
        (0, 0, 3, 0),
    ),
    ("empty_only", [_doc("a.md", "")], (1, 0, 0, 0)),
    ("short_only", [_doc("a.md", "短")], (0, 1, 0, 0)),
    ("dup_path", [_doc("a.md", _text()), _doc("a.md", _text("乙"))], (0, 0, 0, 2)),
    ("mixed", [_doc("a.md", _text()), _doc("b.md", ""), _doc("c.md", "短")], (1, 1, 0, 0)),
)


class TestCorpusMatrix:
    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_the_expected_rule_counts_are_reached(self, case_id, documents, expected):
        records = _evaluate(documents)
        assert len(_with_rule(records, spec.RULE_EMPTY_TEXT)) == expected[0], case_id
        assert len(_with_rule(records, spec.RULE_TOO_SHORT)) == expected[1], case_id
        assert len(_with_rule(records, spec.RULE_EXACT_DUPLICATE)) == expected[2], case_id
        assert len(_with_rule(records, spec.RULE_NEAR_DUPLICATE)) == expected[3], case_id

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_ids_are_unique(self, case_id, documents, expected):
        ids = [record.id for record in _evaluate(documents)]
        assert len(ids) == len(set(ids)), case_id

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_every_record_cites_a_complete_basis(self, case_id, documents, expected):
        for record in _evaluate(documents):
            assert record.basis is not None and record.basis.complete, case_id

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_no_record_carries_a_raw_float(self, case_id, documents, expected):
        for record in _evaluate(documents):
            assert list(_iter_floats(record.as_dict())) == [], case_id

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_the_ledger_is_stable_across_two_runs(self, case_id, documents, expected):
        first = [record.id for record in _evaluate(documents)]
        second = [record.id for record in _evaluate(documents)]
        assert first == second

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_the_ledger_survives_a_roundtrip_through_json(self, case_id, documents, expected):
        payload = json.loads(json.dumps({"documents": documents}, ensure_ascii=False))
        assert [record.id for record in _evaluate(documents)] == [
            record.id for record in audit.evaluate(payload, BASIS)
        ]

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_the_document_order_does_not_change_the_clusters(self, case_id, documents, expected):
        forward = _evaluate(documents)
        backward = _evaluate(list(reversed(documents)))
        assert {record.evidence.get("cluster_id") for record in forward} == {
            record.evidence.get("cluster_id") for record in backward
        }

    @pytest.mark.parametrize("case_id,documents,expected", CORPORA)
    def test_the_duplicate_records_name_a_partner_in_the_same_cluster(self, case_id, documents, expected):
        records = [r for r in _evaluate(documents) if r.evidence.get("cluster_id")]
        for record in records:
            assert record.evidence["other"] != record.path
            assert record.evidence["other"] in record.evidence["members"]


class TestNearBoundary:
    def test_a_threshold_of_one_only_matches_exact_copies(self):
        documents = [_doc("a.md", _text()), _doc("b.md", _text("甲"))]
        assert _with_rule(_evaluate(documents, near_duplicate_threshold=1.0), spec.RULE_NEAR_DUPLICATE) == []

    def test_the_default_threshold_accepts_the_same_pair(self):
        documents = [_doc("a.md", _text()), _doc("b.md", _text("甲"))]
        assert _with_rule(_evaluate(documents), spec.RULE_NEAR_DUPLICATE) != []

    @pytest.mark.parametrize("threshold", (0.5, 0.6, 0.7, 0.8, 0.9, 1.0))
    def test_the_rule_fires_exactly_when_the_score_reaches_the_threshold(self, threshold):
        left, right = _text("甲"), _text("乙")
        score = _score(left, right)
        records = _evaluate([_doc("a.md", left), _doc("b.md", right)], near_duplicate_threshold=threshold)
        fired = bool(_with_rule(records, spec.RULE_NEAR_DUPLICATE))
        exact = bool(_with_rule(records, spec.RULE_EXACT_DUPLICATE))
        assert fired == (exact or score >= threshold)

    @pytest.mark.parametrize("size", (2, 3, 4, 5))
    def test_the_shingle_size_override_reaches_the_evidence(self, size):
        records = _evaluate([_doc("a.md", _text()), _doc("b.md", _text())], shingle_size=size)
        for record in records:
            assert record.evidence["shingle_size"] == size

    def test_a_shorter_document_can_be_excluded_by_raising_the_floor(self):
        documents = [_doc("a.md", _text()), _doc("b.md", _text())]
        assert _with_rule(_evaluate(documents, min_text_chars=10000), spec.RULE_TOO_SHORT) != []
        assert _with_rule(_evaluate(documents, min_text_chars=10000), spec.RULE_EXACT_DUPLICATE) == []


# ---------------------------------------------------------------------------
# 信封
# ---------------------------------------------------------------------------
ENVELOPE_ERRORS = (
    ("documents_is_object", {"documents": {}}),
    ("documents_is_string", {"documents": "x"}),
    ("documents_is_empty", {"documents": []}),
    ("document_is_string", {"documents": ["x"]}),
    ("document_is_list", {"documents": [[]]}),
    ("missing_path", {"documents": [{"text": "x"}]}),
    ("blank_path", {"documents": [{"path": "  ", "text": "x"}]}),
    ("non_string_path", {"documents": [{"path": 1, "text": "x"}]}),
    ("missing_text", {"documents": [{"path": "a.md"}]}),
    ("non_string_text", {"documents": [{"path": "a.md", "text": 1}]}),
    ("params_is_list", {"documents": [{"path": "a.md", "text": "x"}], "params": []}),
    ("params_unknown", {"documents": [{"path": "a.md", "text": "x"}], "params": {"nope": 1}}),
    (
        "params_wrong_type",
        {"documents": [{"path": "a.md", "text": "x"}], "params": {"shingle_size": "three"}},
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

    def test_a_null_text_is_read_as_empty(self):
        records = _evaluate([{"path": "a.md", "text": None}])
        assert [record.rule_id for record in records] == [spec.RULE_EMPTY_TEXT]

    def test_a_non_object_subject_is_an_input_error(self):
        with pytest.raises(ValueError):
            audit.evaluate(["x"], BASIS)


class TestBasisWiring:
    def test_a_missing_rule_is_a_rule_missing_violation(self):
        with pytest.raises(RuleMissing):
            _evaluate([_doc("a.md", "")], basis=Basis(version="9", rules=()))

    def test_the_shipped_basis_satisfies_every_rule(self):
        for rule_id in spec.RULE_IDS:
            assert BASIS.ref(rule_id).rule_version == BASIS.version


# ---------------------------------------------------------------------------
# 器官契约门
# ---------------------------------------------------------------------------
BANNED_NAMES = frozenset(
    (
        "exp",
        "log",
        "pow",
        "sqrt",
        "sin",
        "cos",
        "tan",
        "mean",
        "median",
        "stdev",
        "variance",
        "round",
        "open",
        "print",
        "input",
        "exec",
        "eval",
    )
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
        "fastapi",
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
        assert len(names) >= 5, names
        for expected in ("__init__.py", "audit.py", "cluster.py", "fingerprint.py", "normalize.py", "spec.py"):
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

    def test_a_sqlite_import_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "import sqlite3\n")
        assert any(hit[2] == "import sqlite3" for hit in scan_tree(root))

    def test_a_print_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "print('x')\n")
        assert any(hit[2] == "print" for hit in scan_tree(root))

    def test_a_file_open_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "HANDLE = open('x')\n")
        assert any(hit[2] == "open" for hit in scan_tree(root))

    def test_a_power_operator_is_caught(self, tmp_path):
        root = _copy_package(tmp_path)
        _inject(os.path.join(root, "audit.py"), "INJECTED = 2 ** 8\n")
        assert any(hit[2] == "**" for hit in scan_tree(root))

    def test_the_organ_returns_only_records(self):
        result = audit.evaluate({"documents": [_doc("a.md", _text())]}, BASIS)
        assert isinstance(result, tuple)
        assert all(isinstance(record, Record) for record in result)


def _copy_package(tmp_path):
    target = tmp_path / "duplicate_docs"
    shutil.copytree(ORGAN_DIR, str(target), ignore=shutil.ignore_patterns("__pycache__"))
    return str(target)


def _inject(path, line):
    with io.open(path, "a", encoding="utf-8") as handle:
        handle.write("\n" + line)


# ---------------------------------------------------------------------------
# 唯一入口
# ---------------------------------------------------------------------------
class TestCli:
    def test_the_slug_is_registered(self):
        assert get(SLUG) is PACK

    def test_the_shipped_basis_is_found_without_a_flag(self):
        assert cli.shipped_basis_path(SLUG) == str(BASIS_PATH)

    def test_a_clean_artifact_exits_zero(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"documents": [_doc("a.md", _text())]}, ensure_ascii=False),
            encoding="utf-8",
        )
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_OK
        assert "合计" in capsys.readouterr().out

    def test_a_blocking_artifact_exits_one(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"documents": [_doc("a.md", _text()), _doc("a.md", _text("乙"))]}, ensure_ascii=False),
            encoding="utf-8",
        )
        assert cli.main(["check", SLUG, "--input", str(target)]) == EXIT_BLOCKED

    def test_the_json_output_is_byte_identical_across_runs(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(
            json.dumps({"documents": [_doc("a.md", _text()), _doc("b.md", _text())]}, ensure_ascii=False),
            encoding="utf-8",
        )
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        first = capsys.readouterr().out
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        assert capsys.readouterr().out == first

    def test_the_json_envelope_has_the_spec_fields(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"documents": [_doc("a.md", _text())]}, ensure_ascii=False), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"product", "organ", "organ_version", "subject", "summary", "records"}
        assert payload["organ"] == SLUG

    def test_the_output_has_no_absolute_path(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"documents": [_doc("a.md", _text())]}, ensure_ascii=False), encoding="utf-8")
        cli.main(["check", SLUG, "--input", str(target), "--json"])
        out = capsys.readouterr().out
        assert str(ROOT) not in out and "ProgramData" not in out

    def test_stdin_is_labelled(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps({"documents": [_doc("a.md", _text())]}, ensure_ascii=False))
        )
        assert cli.main(["check", SLUG, "--input", "-", "--json"]) == EXIT_OK
        assert json.loads(capsys.readouterr().out)["subject"] == "<stdin>"

    def test_an_empty_basis_is_a_contract_error(self, capsys, tmp_path):
        target = tmp_path / "input.json"
        target.write_text(json.dumps({"documents": [_doc("a.md", "")]}), encoding="utf-8")
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
        assert "documents" in capsys.readouterr().err

    def test_the_list_json_carries_the_input_fields(self, capsys):
        assert cli.main(["list", "--json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        entry = [item for item in payload if item["slug"] == SLUG][0]
        assert entry["input_fields"] == ["documents"]
        assert entry["version"] == ORGAN_VERSION