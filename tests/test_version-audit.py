"""``version-audit`` 器官的无损测试（迁自 10-27-versionaudit，Node/mjs 源）。

无损 = 旧仓**被判定的那套函数仍然在、语义仍然是那一套**：semver 范围语义核心
（node-semver 7.8.5 的严格模式移植）、自研区间代数（A1–A21 逐条）、R1–R8、
M2 双向一致性四类 kind、M3 收敛可行性三态 + MUS 两条性质、M4 冲突最小集、
确定性（同输入两次运行逐字节一致）、退出码矩阵。

**没迁的部分逐条写在 ``docs/version-audit.md`` §6 的处置表里**（文件读取、v1/v2/v3
锁解析、报告排版、SARIF、Node 环境门、与 semver 库的差分自检）。不迁的东西不在这里
假装测过。差分向量的期望值（旧仓 fixtures/vectors 14 组）在本文件按行内联为
一致性表 —— 跨语言重写后没有第二实现，期望值就是判据。

判定层口径（D1 + D18）：旧仓 18 个测试文件剔除 ``lock-input``（input）与
``report``（report）后 14 文件实跑 ``node --test`` **X = 180 passed**
（旧层 ``test(`` 调用数 123；静态 baseline 记 0，以实跑为准）。
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
from byteproof.auditors.version_audit import (  # noqa: E402
    ORGAN_VERSION,
    PACK,
    audit,
    conflict,
    dedupe,
    graph,
    interval,
    lint,
    lockcheck,
    mus,
    semver_core,
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

SLUG = "version-audit"
DATA_DIR = SRC / "byteproof" / "data"
BASIS_PATH = DATA_DIR / "version-audit.basis.json"
THRESHOLDS_PATH = DATA_DIR / "version-audit.thresholds.json"
SAMPLE = ROOT / "samples" / "version-audit.minimal.json"

BASIS = Basis.from_json(str(BASIS_PATH))
SETTINGS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


# ================================================================== 夹具助手
def _manifest(deps=None, **extra):
    base = {
        "name": "f",
        "deps": {
            "dependencies": deps or {},
            "devDependencies": {},
            "optionalDependencies": {},
            "peerDependencies": {},
        },
        "overrides": {},
        "resolutions": {},
    }
    for kind, value in extra.items():
        base["deps"][kind] = value
    return base


def _lock(root_deps=None, packages=None, root_optional=None):
    return {
        "lockfile_version": 3,
        "packages": packages if packages is not None else [],
        "root_manifest_deps": root_deps or {},
        "root_optional_deps": root_optional or {},
    }


def _pkg(path, version, deps=None, **extra):
    entry = {"path": path, "name": path.rsplit("node_modules/", 1)[-1], "version": version, "deps": deps or {}}
    entry.update(extra)
    return entry


def _nested(parent, name, version, deps=None):
    return _pkg("node_modules/%s/node_modules/%s" % (parent, name), version, deps)


def _subject(mode="audit", manifest=None, lock=None, options=None):
    subject = {"mode": mode, "manifest": manifest or _manifest(), "lock": lock or _lock()}
    if options is not None:
        subject["options"] = options
    return subject


def _evaluate(subject, basis=None):
    return list(PACK.evaluate(subject, BASIS if basis is None else basis))


def _records(subject, rule_id=None):
    records = _evaluate(subject)
    if rule_id is None:
        return records
    return [record for record in records if record.rule_id == rule_id]


def _codes(subject):
    return [record.rule_id for record in _evaluate(subject)]


def _report(subject):
    return Report(
        product="byteproof",
        organ=SLUG,
        organ_version=ORGAN_VERSION,
        subject="test.json",
        records=tuple(_evaluate(subject)),
    )


def _lint(deps, **opts):
    """直连 R1–R8（不经 CLI），照搬旧仓 range-lint.test.mjs 的 lint() 形态。"""
    manifest = _manifest(deps)
    declarations = audit.flatten_declarations(manifest)
    return lint.run_range_lint(
        manifest,
        declarations,
        enable_r8=opts.pop("enable_r8", False),
        prerelease_targets=opts.pop("prerelease_targets", None),
    )


def _rules_for(findings, pkg):
    return [f["rule"] for f in findings if f["package"] == pkg]


def _findings_of(subject, section):
    return [r for r in _evaluate(subject) if r.path.startswith(section)]


def _assert_mus_properties(ranges, locked):
    """MUS 的两条性质（§7.2）——降级结果也必须满足。"""
    assert len(ranges) > 0, "MUS 不能为空集"
    for version in locked:
        assert not all(semver_core.satisfies(version, r) for r in ranges), "M 必须无解：%s" % (ranges,)
    for i in range(len(ranges)):
        rest = [r for j, r in enumerate(ranges) if j != i]
        assert any(
            all(semver_core.satisfies(v, r) for r in rest) for v in locked
        ), "移除 %s 后必须可满足（否则不是极小集）" % (ranges[i],)


# ================================================================== 接线
def test_pack_is_registered_under_the_slug():
    load_builtin()
    assert get(SLUG) is PACK
    assert PACK.slug == SLUG


def test_pack_declares_mode_field():
    assert PACK.input_fields == ("mode",)


def test_builtin_modules_include_the_organ():
    assert "version_audit" in BUILTIN_MODULES


def test_builtin_modules_stay_sorted():
    assert list(BUILTIN_MODULES) == sorted(BUILTIN_MODULES)


def test_organ_version_is_one():
    assert ORGAN_VERSION == "1"


def test_sample_is_a_clean_audit():
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    assert data["mode"] == "audit"
    records = _evaluate(data)
    assert [r.verdict for r in records] == [INFO]


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


def test_every_rule_has_a_nominal_verdict():
    assert set(spec.RULE_IDS) == set(spec.VERDICTS)


def test_thresholds_default_severity_matches_runtime():
    assert SETTINGS["default_severity"] == spec.SEVERITY_FALLBACK


def test_thresholds_verdicts_match_runtime():
    assert SETTINGS["verdicts"] == spec.VERDICTS


def test_thresholds_policy_matches_runtime():
    policy = SETTINGS["policy"]
    assert policy["max_requesters"] == spec.MAX_REQUESTERS
    assert policy["enable_r8"] is False
    assert policy["strict"] is False
    assert policy["ignore_peer"] is False
    assert policy["prefer"] is None


def test_thresholds_mus_reasons_match_runtime():
    assert SETTINGS["mus"]["degraded_reason"] == "requesters > max"
    assert SETTINGS["mus"]["fallback_reason"] == "fallback: full set"


def test_rule_ids_are_unique_and_kebab():
    assert len(set(spec.RULE_IDS)) == len(spec.RULE_IDS)
    for rule_id in spec.RULE_IDS:
        assert rule_id.startswith("va-")
        assert rule_id == rule_id.lower()


def test_basis_quotes_are_substantial():
    for rule_id in BASIS.rule_ids():
        assert len(BASIS.require(rule_id).text) >= 40, rule_id


# ================================================================== semver 核心：valid_range
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("^0.2.3", ">=0.2.3 <0.3.0-0"),
        ("^0.0.3", ">=0.0.3 <0.0.4-0"),
        ("^0.0", "<0.1.0-0"),
        ("^0.0.x", "<0.1.0-0"),
        ("^0.0.0", "<0.0.1-0"),
        ("^0", "<1.0.0-0"),
        ("^0.x", "<1.0.0-0"),
        ("^1.2.3", ">=1.2.3 <2.0.0-0"),
        ("^1.2.3-beta", ">=1.2.3-beta <2.0.0-0"),
        ("^1.2.3+build", ">=1.2.3 <2.0.0-0"),
    ],
)
def test_valid_range_caret_family(raw, expected):
    assert semver_core.valid_range(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("~0.2.3", ">=0.2.3 <0.3.0-0"),
        ("~0.0.3", ">=0.0.3 <0.1.0-0"),
        ("~0.0.0", "<0.1.0-0"),
        ("~0", "<1.0.0-0"),
        ("~0.x", "<1.0.0-0"),
        ("~1.2.3", ">=1.2.3 <1.3.0-0"),
        ("~1.2", ">=1.2.0 <1.3.0-0"),
    ],
)
def test_valid_range_tilde_family(raw, expected):
    assert semver_core.valid_range(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.0", ">=1.0.0 <1.1.0-0"),
        ("0.0", "<0.1.0-0"),
        ("1.x", ">=1.0.0 <2.0.0-0"),
        ("1", ">=1.0.0 <2.0.0-0"),
        ("x", "*"),
        ("X", "*"),
        ("*", "*"),
        ("", "*"),
        ("1.2.x", ">=1.2.0 <1.3.0-0"),
        (">=1.0.0 <=1.0.0", ">=1.0.0 <=1.0.0"),
        (">=1.2.0 <2.0.0", ">=1.2.0 <2.0.0"),
        ("1.0.0+build.1 || ^2.0.0", "1.0.0||>=2.0.0 <3.0.0-0"),
    ],
)
def test_valid_range_partial_and_wildcard(raw, expected):
    assert semver_core.valid_range(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3", "1.2.3"),
        ("=1.2.3", "1.2.3"),
        ("v1.2.3", "1.2.3"),
        ("latest", None),
        ("abc", None),
        ("1.2.3.4", None),
    ],
)
def test_valid_range_exact_and_tag(raw, expected):
    assert semver_core.valid_range(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3 - 2.3.4", ">=1.2.3 <=2.3.4"),
        ("1.2.3 - 2.3", ">=1.2.3 <2.4.0-0"),
        ("1.2.3 - 2", ">=1.2.3 <3.0.0-0"),
        ("1.2 - 2.3.4", ">=1.2.0 <=2.3.4"),
    ],
)
def test_valid_range_hyphen(raw, expected):
    assert semver_core.valid_range(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (">=1.2.0+build <2.0.0", ">=1.2.0 <2.0.0"),
        ("1.0.0+build.1", "1.0.0"),
        ("1.0.0-rc.1+build", "1.0.0-rc.1"),
    ],
)
def test_valid_range_build_metadata_stripped(raw, expected):
    assert semver_core.valid_range(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (">=0.0.0", "*"),
        (">=0.0.0 <1.0.0", "<1.0.0"),
    ],
)
def test_valid_range_gte0_simplifies_to_star(raw, expected):
    assert semver_core.valid_range(raw) == expected


# ================================================================== semver 核心：satisfies
@pytest.mark.parametrize(
    "version,rng,expected",
    [
        ("0.2.9", "^0.2.3", True),
        ("0.3.0", "^0.2.3", False),
        ("0.0.4", "^0.0.3", False),
        ("0.0.3", "^0.0.3", True),
        ("1.3.0", "~1.2.3", False),
        ("1.2.9", "~1.2.3", True),
    ],
)
def test_satisfies_caret_and_tilde(version, rng, expected):
    assert semver_core.satisfies(version, rng) is expected


@pytest.mark.parametrize(
    "version,rng,expected",
    [
        ("1.0.0-beta", "^1.0.0", False),
        ("1.5.0-beta", "^1.0.0", False),
        ("1.0.0-beta", "*", False),
        ("1.2.3-beta.2", "^1.2.3-beta", True),
        ("1.0.0-beta", ">=1.0.0-beta", True),
        ("1.0.0-alpha", ">=1.0.0-beta", False),
    ],
)
def test_satisfies_prerelease_rules(version, rng, expected):
    # A8/A9：预发布只被「同三元组且带预发布」的比较器放行
    assert semver_core.satisfies(version, rng) is expected


@pytest.mark.parametrize(
    "version,rng,expected",
    [
        ("1.0.0+build.1", "1.0.0", True),
        ("1.0.0", "1.0.0+build.1", True),
    ],
)
def test_satisfies_build_metadata_ignored(version, rng, expected):
    assert semver_core.satisfies(version, rng) is expected


@pytest.mark.parametrize(
    "version,rng,expected",
    [
        ("1.0.0", ">=1.0.0 <1.0.0", False),
        ("1.5.0", ">=1.0.0 <1.0.0", False),
        ("1.0.0", ">=1.0.0 <=1.0.0", True),
        ("1.0.1", ">=1.0.0 <=1.0.0", False),
        ("1.0.0", "1.0.0 <1.0.0", False),
        ("1.0.0", "1.0.0 >1.0.0", False),
        ("1.0.0", ">1.0.0 1.0.0", False),
    ],
)
def test_satisfies_empty_and_exact_exclusion_forms(version, rng, expected):
    # A11/A18/A21：端点开闭性决定一切
    assert semver_core.satisfies(version, rng) is expected


@pytest.mark.parametrize(
    "version,rng,expected",
    [
        ("1.2.4", "1.2.3", False),
        ("1.9.0", "1.x", True),
        ("2.0.0", "1.x", False),
        ("1.1.0", "1.0", False),
        ("0.0.9", "0.0", True),
        ("0.1.0", "0.0", False),
    ],
)
def test_satisfies_exact_and_partial(version, rng, expected):
    assert semver_core.satisfies(version, rng) is expected


def test_satisfies_invalid_range_is_false():
    assert semver_core.satisfies("1.0.0", "latest") is False
    assert semver_core.satisfies("1.0.0", "abc") is False


# ================================================================== semver 核心：subset / intersects
@pytest.mark.parametrize(
    "sub,dom,expected",
    [
        (">=1.2.0 <1.3.0-0", ">=1.0.0 <2.0.0-0", True),
        (">=1.0.0 <2.0.0-0", "*", True),
        (">=1.0.0 <2.0.0-0", ">=2.0.0 <3.0.0-0", False),
        (">=2.0.0 <3.0.0-0", ">=1.0.0 <2.0.0-0", False),
        (">=1.2.0 <2.0.0-0", ">=1.0.0 <2.0.0-0", True),
        ("*", ">=1.0.0", False),
        ("1.2.3", "1.2.3", True),
        ("1.2.3", "1.2.4", False),
        (">=1.2.3-beta", ">=1.0.0", False),
        ("^1.2.3-beta", ">=1.2.3-beta", True),
    ],
)
def test_subset_containment_table(sub, dom, expected):
    assert semver_core.subset(sub, dom) is expected


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("^1.0.0", "^2.0.0", False),
        ("^1.0.0", "^1.5.0", True),
        (">=1.0.0 <2.0.0", ">=2.5.0", False),
        ("1.0.0", ">=1.0.0", True),
        ("latest", "^1.0.0", False),
        (">=1.0.0 <1.0.0", "*", False),
    ],
)
def test_intersects_table(a, b, expected):
    assert semver_core.intersects(a, b) is expected


# ================================================================== semver 核心：compare / parse
@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("1.0.0", "2.0.0", -1),
        ("2.0.0", "1.0.0", 1),
        ("1.2.3", "1.2.3", 0),
        ("1.0.0-alpha", "1.0.0", -1),
        ("1.0.0-alpha", "1.0.0-alpha.1", -1),
        ("1.0.0-alpha.1", "1.0.0-beta", -1),
        ("1.0.0+build", "1.0.0", 0),
    ],
)
def test_compare_ordering(a, b, expected):
    assert semver_core.compare(a, b) == expected


@pytest.mark.parametrize(
    "raw,valid",
    [
        ("1.2.3", True),
        ("v1.2.3", True),
        ("1.2.3-rc.1", True),
        ("1.2", False),
        ("01.2.3", False),
        ("1.2.3.4", False),
    ],
)
def test_parse_strict_semantics(raw, valid):
    assert (semver_core.parse(raw) is not None) is valid


def test_sort_versions_numeric_not_lexicographic():
    assert interval.sort_versions(["10.0.0", "2.0.0", "1.0.0"]) == ["1.0.0", "2.0.0", "10.0.0"]


def test_sort_versions_invalid_last():
    assert interval.sort_versions(["2.0.0", "oops", "1.0.0"]) == ["1.0.0", "2.0.0", "oops"]


def test_sort_versions_prerelease_ordering():
    assert interval.sort_versions(["1.0.0", "1.0.0-rc.1"]) == ["1.0.0-rc.1", "1.0.0"]


# ================================================================== 区间代数
def test_normalize_range_expands_caret_zero():
    norm = interval.normalize_range("^0.2.3")
    assert norm["expanded_range"] == ">=0.2.3 <0.3.0-0"


def test_normalize_range_latest_is_null():
    assert interval.normalize_range("latest") is None


def test_range_is_empty_open_same_bound():
    assert interval.range_is_empty(">=1.0.0 <1.0.0") is True


def test_range_is_empty_closed_single_point():
    assert interval.range_is_empty(">=1.0.0 <=1.0.0") is False


def test_range_is_empty_exact_with_exclusion():
    assert interval.range_is_empty(">1.0.0 <=1.0.0") is True
    assert interval.range_is_empty("1.0.0 >1.0.0") is True
    assert interval.range_is_empty("1.0.0 <1.0.0") is True


def test_range_is_empty_plain_forms():
    assert interval.range_is_empty("1.2.3") is False
    assert interval.range_is_empty(">1.0.0") is False


def test_range_is_empty_latest_null():
    assert interval.range_is_empty("latest") is None


def test_intersect_ranges_multi_way():
    assert interval.intersect_ranges([">=1.0.0 <2.0.0", ">=1.5.0"])["empty"] is False
    assert interval.intersect_ranges([">=1.0.0 <2.0.0", ">=2.5.0"])["empty"] is True


def test_intersect_ranges_three_way():
    assert interval.intersect_ranges(["^1.0.0", "^1.2.0", "^2.0.0"])["empty"] is True


def test_intersect_ranges_or_branches():
    assert interval.intersect_ranges(["^1.0.0 || ^3.0.0", "^2.0.0"])["empty"] is True
    assert interval.intersect_ranges(["^1.0.0 || ^3.0.0", "^1.5.0"])["empty"] is False


def test_intersect_ranges_reports_culprit():
    result = interval.intersect_ranges(["^1.0.0", "latest"])
    assert result["empty"] is None
    assert result["invalid_range"] == "latest"


def test_evaluate_candidates_uses_actual_satisfaction():
    rows = interval.evaluate_candidates(["1.2.0", "1.5.0"], ["^1.0.0", "^1.5.0"], semver_core.satisfies)
    assert {row["version"]: row["satisfied"] for row in rows} == {"1.2.0": False, "1.5.0": True}


# ================================================================== M1 range-lint R1–R8
def test_r1_positive_unbounded():
    out = _lint({"pkg": ">=1.2.0"})
    assert "R1" in _rules_for(out, "pkg")


def test_r1_negative_bounded():
    out = _lint({"pkg": ">=1.2.0 <2.0.0"})
    assert "R1" not in _rules_for(out, "pkg")


def test_r2_positive_family():
    for rng in ["*", "", "x", "latest"]:
        out = _lint({"pkg": rng})
        assert "R2" in _rules_for(out, "pkg"), "%r 应报 R2" % rng


def test_r2_latest_is_not_a_range():
    out = _lint({"pkg": "latest"})
    hit = next(f for f in out if f["package"] == "pkg" and f["rule"] == "R2")
    assert hit["not_a_range"] is True
    assert hit["expanded_range"] is None


def test_r2_negative_caret():
    out = _lint({"pkg": "^1.0.0"})
    assert "R2" not in _rules_for(out, "pkg")


def test_r3_positive_two_shapes():
    out = _lint({"a": "^0.0.3", "b": "^0.2.3"})
    assert "R3" in _rules_for(out, "a")
    assert "R3" in _rules_for(out, "b")


def test_r3_negative_nonzero_major():
    out = _lint({"pkg": "^1.2.3"})
    assert "R3" not in _rules_for(out, "pkg")


def test_r4_prerelease_unreachable():
    targets = {"pkg": [{"version": "1.0.0-beta", "major": 1, "minor": 0, "patch": 0, "is_prerelease": True}]}
    out = _lint({"pkg": "^1.0.0"}, prerelease_targets=targets)
    hit = next(f for f in out if f["package"] == "pkg" and f["rule"] == "R4")
    assert "prerelease-unreachable" in hit["evidence"]


def test_r4_target_not_in_candidate():
    targets = {"pkg": [{"version": "2.0.0-beta", "major": 2, "minor": 0, "patch": 0, "is_prerelease": True}]}
    out = _lint({"pkg": "^1.0.0"}, prerelease_targets=targets)
    hit = next(f for f in out if f["package"] == "pkg" and f["rule"] == "R4")
    assert "target-not-in-candidate" in hit["evidence"]


def test_r4_reachable_is_not_reported():
    targets = {"pkg": [{"version": "1.2.3-beta.2", "major": 1, "minor": 2, "patch": 3, "is_prerelease": True}]}
    out = _lint({"pkg": "^1.2.3-beta"}, prerelease_targets=targets)
    assert "R4" not in _rules_for(out, "pkg")


def test_r5_positive_empty_forms():
    out = _lint({"a": ">=1.0.0 <1.0.0", "b": ">=2.0.0 <1.0.0"})
    assert "R5" in _rules_for(out, "a")
    assert "R5" in _rules_for(out, "b")
    assert all(f["severity"] == "error" for f in out if f["rule"] == "R5")


def test_r5_negative_nonempty():
    out = _lint({"pkg": ">=1.0.0 <2.0.0"})
    assert "R5" not in _rules_for(out, "pkg")


@pytest.mark.parametrize(
    "rng",
    ["^1.0.0 || ^1.2.0", "* || ^1.0.0"],
)
def test_r6_positive_subsumed(rng):
    out = _lint({"pkg": rng})
    assert "R6" in _rules_for(out, "pkg")


def test_r6_negative_disjoint_branches():
    out = _lint({"pkg": "^1.0.0 || ^2.0.0"})
    assert "R6" not in _rules_for(out, "pkg")


@pytest.mark.parametrize(
    "rng,expected",
    [
        ("1.0.0+build.1", "1.0.0"),
        (">=1.2.0+build <2.0.0", ">=1.2.0 <2.0.0"),
        ("^1.2.3+build", ">=1.2.3 <2.0.0-0"),
    ],
)
def test_r7_positive(rng, expected):
    out = _lint({"pkg": rng})
    assert "R7" in _rules_for(out, "pkg")
    hit = next(f for f in out if f["package"] == "pkg" and f["rule"] == "R7")
    assert hit["expanded_range"] == expected


def test_r7_negative_plain():
    out = _lint({"pkg": "1.0.0"})
    assert "R7" not in _rules_for(out, "pkg")


def test_r8_default_off():
    out = _lint({"pkg": "1.2.3"})
    assert "R8" not in _rules_for(out, "pkg")


def test_r8_enabled_reports_info():
    out = _lint({"pkg": "1.2.3"}, enable_r8=True)
    hit = next(f for f in out if f["package"] == "pkg" and f["rule"] == "R8")
    assert hit["severity"] == "info"
    assert "精确锁定" in hit["evidence"]
    assert "Cargo" in hit["evidence"]


def test_expanded_range_comes_from_core():
    out = _lint({"a": "^0.2.3", "b": "1.0", "c": ">=1.2.0"})
    for finding in out:
        assert finding["expanded_range"] == semver_core.valid_range(finding["raw_range"])


def test_lint_findings_sorted():
    out = _lint({"b": ">=1.0.0", "a": "*"})
    keys = [(f["rule"], f["package"], f["declaration"], f["raw_range"]) for f in out]
    assert keys == sorted(keys)


# ================================================================== M2 lock-manifest
def test_send_scenario_full_fields():
    subject = _subject(
        manifest=_manifest({"send": "^0.19.2"}),
        lock=_lock({"send": "^0.19.2"}, [_pkg("node_modules/send", "0.18.0")]),
    )
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_MANIFEST_NOT_SATISFIED]
    assert len(hits) == 1
    evidence = hits[0].evidence
    assert evidence["declaring_package"] == "f"
    assert evidence["declared_range"] == "^0.19.2"
    assert evidence["locked_version"] == "0.18.0"
    assert evidence["requester_path"] == ["<root>"]
    assert hits[0].verdict == ERROR


def test_missing_from_lock():
    subject = _subject(manifest=_manifest({"ghost": "^1.0.0"}), lock=_lock({"ghost": "^1.0.0"}, []))
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_MISSING_FROM_LOCK]
    assert len(hits) == 1
    assert hits[0].evidence["dependency"] == "ghost"
    assert hits[0].evidence["locked_version"] is None
    assert hits[0].verdict == ERROR


def test_optional_missing_is_not_error():
    subject = _subject(
        manifest=_manifest(optionalDependencies={"opt-dep": "^1.0.0"}),
        lock=_lock(root_optional={"opt-dep": "^1.0.0"}, packages=[]),
    )
    records = _evaluate(subject)
    assert not [r for r in records if r.rule_id == spec.RULE_MISSING_FROM_LOCK]


def test_manifest_changed_unsynced():
    subject = _subject(
        manifest=_manifest({"a": "^2.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.5.0")]),
    )
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_MANIFEST_CHANGED_UNSYNCED]
    assert len(hits) == 1
    assert hits[0].evidence["declared_range"] == "^2.0.0"
    assert hits[0].evidence["locked_version"] == "^1.0.0"
    assert hits[0].verdict == ERROR


def test_unsynced_removed_from_manifest():
    subject = _subject(
        manifest=_manifest({}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.5.0")]),
    )
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_MANIFEST_CHANGED_UNSYNCED]
    assert len(hits) == 1
    assert "manifest 已删除" in hits[0].message


def test_lock_extra_undeclared():
    subject = _subject(
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.0.0"), _pkg("node_modules/stray", "9.9.9")]),
    )
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_LOCK_EXTRA_UNDECLARED]
    assert len(hits) == 1
    assert hits[0].evidence["dependency"] == "stray"
    assert hits[0].verdict == WARN


def test_transitive_requester_path_chain():
    subject = _subject(
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock(
            {"a": "^1.0.0"},
            [_pkg("node_modules/a", "1.0.0", {"b": "^2.0.0"}), _nested("a", "b", "1.0.0")],
        ),
    )
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_MANIFEST_NOT_SATISFIED]
    assert len(hits) == 1
    assert hits[0].evidence["requester_path"] == ["<root>", "a@1.0.0"]


def test_strict_flag_lock_outdated():
    subject = _subject(
        mode="lock-manifest",
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.9.0")]),
        options={"strict": True},
    )
    hits = [r for r in _records(subject) if r.rule_id == spec.RULE_LOCK_OUTDATED]
    assert len(hits) == 1
    assert hits[0].verdict == WARN


def test_default_does_not_judge_lock_outdated():
    subject = _subject(
        mode="lock-manifest",
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.9.0")]),
    )
    assert not [r for r in _evaluate(subject) if r.rule_id == spec.RULE_LOCK_OUTDATED]


def test_lock_entry_without_version_degrades_not_fails():
    # A23：锁条目无 version（optional 占位形态）是"无法判定"，不是"不满足"
    subject = _subject(
        mode="lock-manifest",
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [{"path": "node_modules/a", "name": "a", "version": None}]),
    )
    records = _evaluate(subject)
    assert not [r for r in records if r.rule_id == spec.RULE_MANIFEST_NOT_SATISFIED]
    degradation = [r for r in records if r.rule_id == spec.RULE_LOCK_ENTRY_NO_VERSION]
    assert len(degradation) == 1
    assert degradation[0].verdict == INFO


def test_file_declaration_skips_satisfaction_check():
    # file:/link: 声明不是 semver 范围：不做满足性判定，也不制造降级
    subject = _subject(
        mode="lock-manifest",
        manifest=_manifest({"lib": "file:../lib"}),
        lock=_lock({"lib": "file:../lib"}, [{"path": "node_modules/lib", "name": "lib", "version": None, "link": True}]),
    )
    records = _evaluate(subject)
    assert not [r for r in records if r.rule_id == spec.RULE_MANIFEST_NOT_SATISFIED]
    assert not [r for r in records if r.rule_id == spec.RULE_LOCK_ENTRY_NO_VERSION]


def test_dist_tag_range_skips_satisfaction_check():
    subject = _subject(
        mode="lock-manifest",
        manifest=_manifest({"a": "latest"}),
        lock=_lock({"a": "latest"}, [_pkg("node_modules/a", "1.0.0")]),
    )
    records = _evaluate(subject)
    assert not [r for r in records if r.rule_id == spec.RULE_MANIFEST_NOT_SATISFIED]


def test_m2_findings_sorted():
    subject = _subject(
        manifest=_manifest({"send": "^0.19.2", "ghost": "^1.0.0"}),
        lock=_lock(
            {"send": "^0.19.2", "ghost": "^1.0.0"},
            [_pkg("node_modules/send", "0.18.0"), _pkg("node_modules/stray", "9.9.9")],
        ),
    )
    findings = [r for r in _evaluate(subject) if r.path.startswith("lock.")]
    keys = [(r.rule_id, r.path) for r in findings]
    assert keys == sorted(keys)


# ================================================================== M3 dedupe + MUS
def _ms_tree(deps_a="2.0.0", deps_b="2.1.3"):
    """真实树形态：debug 与 send 各自声明 ms 的不同版本。"""
    return _subject(
        mode="dedupe",
        manifest=_manifest({"debug": "2.6.9", "send": "0.18.0"}),
        lock=_lock(
            {"debug": "2.6.9", "send": "0.18.0"},
            [
                _pkg("node_modules/debug", "2.6.9", {"ms": deps_a}),
                _nested("debug", "ms", "2.0.0"),
                _pkg("node_modules/send", "0.18.0", {"ms": deps_b}),
                _nested("send", "ms", "2.1.3"),
            ],
        ),
    )


def _dedupe_result(subject, package):
    hits = [r for r in _evaluate(subject) if r.path == "dedupe.%s" % package]
    assert len(hits) == 1, "必须报 %s 的收敛判定" % package
    return hits[0]


def test_ms_exact_pins_not_convergible():
    record = _dedupe_result(_ms_tree(), "ms")
    evidence = record.evidence
    assert evidence["status"] == "NOT_CONVERGIBLE"
    assert evidence["locked_versions"] == ["2.0.0", "2.1.3"]
    assert evidence["reason"] == "empty-intersection"
    assert sorted(m["range"] for m in evidence["minimal_conflict_set"]) == ["2.0.0", "2.1.3"]
    assert all(len(m["requester_path"]) >= 2 for m in evidence["minimal_conflict_set"])
    assert record.verdict == ERROR


def test_ms_ranges_convergible_with_targets_proof():
    subject = _ms_tree(deps_a="^2.0.0", deps_b="^2.1.0")
    record = _dedupe_result(subject, "ms")
    evidence = record.evidence
    assert evidence["status"] == "CONVERGIBLE"
    assert [t["version"] for t in evidence["targets"]] == ["2.1.3"]
    for target in evidence["targets"]:
        for proof in target["proof"]:
            assert proof["satisfies"] == semver_core.satisfies(target["version"], proof["range"])
            assert proof["satisfies"] is True
    assert len(evidence["targets"][0]["proof"]) >= 2


def test_single_version_no_dedupe():
    subject = _subject(
        mode="dedupe",
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.0.0")]),
    )
    records = _evaluate(subject)
    assert not [r for r in records if r.path.startswith("dedupe.")]


def test_not_convergible_gives_mus():
    subject = _subject(
        mode="dedupe",
        manifest=_manifest({"x": "^1.0.0", "y": "^2.0.0"}),
        lock=_lock(
            {"x": "^1.0.0", "y": "^2.0.0"},
            [
                _pkg("node_modules/x", "1.0.0", {"pkg": "^1.0.0"}),
                _nested("x", "pkg", "1.0.0"),
                _pkg("node_modules/y", "1.0.0", {"pkg": "^2.0.0"}),
                _nested("y", "pkg", "2.0.0"),
            ],
        ),
    )
    record = _dedupe_result(subject, "pkg")
    assert record.evidence["status"] == "NOT_CONVERGIBLE"
    ranges = [m["range"] for m in record.evidence["minimal_conflict_set"]]
    assert len(ranges) >= 2
    _assert_mus_properties(ranges, record.evidence["locked_versions"])


def test_requires_override_with_ties():
    subject = _subject(
        mode="dedupe",
        manifest=_manifest({"a": "^1.0.0", "b": "^2.0.0", "c": "^3.0.0"}),
        lock=_lock(
            {"a": "^1.0.0", "b": "^2.0.0", "c": "^3.0.0"},
            [
                _pkg("node_modules/a", "1.0.0", {"shared": "^1.0.0"}),
                _nested("a", "shared", "1.2.0"),
                _pkg("node_modules/b", "1.0.0", {"shared": "^1.0.0"}),
                _nested("b", "shared", "1.5.0"),
                _pkg("node_modules/c", "1.0.0", {"shared": "^9.0.0"}),
                _nested("c", "shared", "9.0.0"),
            ],
        ),
    )
    record = _dedupe_result(subject, "shared")
    evidence = record.evidence
    assert evidence["status"] == "REQUIRES_OVERRIDE"
    assert record.verdict == WARN
    assert len(evidence["minimal_conflict_set"]) < evidence["requesters"]
    assert len(evidence["minimal_conflict_sets"]) == 2
    for mus_set in evidence["minimal_conflict_sets"]:
        assert len(mus_set) == 2
        assert any(m["range"] == "^9.0.0" for m in mus_set)
    assert evidence["suggestion"]["nature"] == "suggestion"


def test_prefer_latest_only_reorders():
    plain = _dedupe_result(_ms_tree(deps_a="^2.0.0", deps_b="^2.1.0"), "ms").evidence
    latest = _dedupe_result(
        _subject(
            mode="dedupe",
            manifest=_ms_tree(deps_a="^2.0.0", deps_b="^2.1.0")["manifest"],
            lock=_ms_tree(deps_a="^2.0.0", deps_b="^2.1.0")["lock"],
            options={"prefer": "latest"},
        ),
        "ms",
    ).evidence
    assert plain["status"] == latest["status"]
    assert sorted(t["version"] for t in plain["targets"]) == sorted(t["version"] for t in latest["targets"])
    assert latest["targets"][0]["preferred"] is True


def test_convergible_targets_complete():
    subject = _subject(
        mode="dedupe",
        manifest=_manifest({"a": "^1.0.0", "b": "^1.0.0"}),
        lock=_lock(
            {"a": "^1.0.0", "b": "^1.0.0"},
            [
                _pkg("node_modules/a", "1.0.0", {"shared": "^2.0.0"}),
                _nested("a", "shared", "2.0.0"),
                _pkg("node_modules/b", "1.0.0", {"shared": "^2.0.0"}),
                _nested("b", "shared", "2.1.3"),
            ],
        ),
    )
    record = _dedupe_result(subject, "shared")
    assert record.evidence["status"] == "CONVERGIBLE"
    assert [t["version"] for t in record.evidence["targets"]] == ["2.0.0", "2.1.3"]
    assert all(t["preferred"] is False for t in record.evidence["targets"])


def test_reason_no_locked_candidate():
    subject = _subject(
        mode="dedupe",
        manifest=_manifest({"a": "^1.0.0", "b": "^1.0.0"}),
        lock=_lock(
            {"a": "^1.0.0", "b": "^1.0.0"},
            [
                _pkg("node_modules/a", "1.0.0", {"shared": ">=1.0.0 <1.0.2"}),
                _nested("a", "shared", "1.0.0"),
                _pkg("node_modules/b", "1.0.0", {"shared": ">1.0.0 <=1.0.2"}),
                _nested("b", "shared", "1.0.2"),
            ],
        ),
    )
    record = _dedupe_result(subject, "shared")
    assert record.evidence["status"] == "NOT_CONVERGIBLE"
    assert record.evidence["reason"] == "no-locked-candidate"
    _assert_mus_properties(
        [m["range"] for m in record.evidence["minimal_conflict_set"]],
        record.evidence["locked_versions"],
    )


def _degraded_tree_subject(options=None):
    deps = {}
    packages = []
    for i in range(12):
        name = "p%02d" % i
        deps[name] = "^1.0.0"
        packages.append(_pkg("node_modules/%s" % name, "1.0.0", {"shared": "1.0.0"}))
        packages.append(_nested(name, "shared", "1.0.0"))
    deps["q"] = "^1.0.0"
    packages.append(_pkg("node_modules/q", "1.0.0", {"shared": "^1.5.0"}))
    packages.append(_nested("q", "shared", "1.5.0"))
    return _subject(
        mode="dedupe",
        manifest=_manifest(deps),
        lock=_lock(deps, packages),
        options=options,
    )


def test_max_requesters_degraded_path():
    record = _dedupe_result(_degraded_tree_subject(), "shared")
    evidence = record.evidence
    assert evidence["degraded"] is True
    assert evidence["degrade_reason"] == "requesters > max"
    assert evidence["requesters"] == 13
    _assert_mus_properties(
        [m["range"] for m in evidence["minimal_conflict_set"]],
        evidence["locked_versions"],
    )
    assert len(evidence["minimal_conflict_set"]) < evidence["requesters"]


def test_max_requesters_lowered_still_minimal():
    record = _dedupe_result(
        _subject(
            mode="dedupe",
            manifest=_degraded_tree_subject()["manifest"],
            lock=_degraded_tree_subject()["lock"],
            options={"max_requesters": 5},
        ),
        "shared",
    )
    assert record.evidence["degraded"] is True
    _assert_mus_properties(
        [m["range"] for m in record.evidence["minimal_conflict_set"]],
        record.evidence["locked_versions"],
    )


def test_untruncated_not_degraded():
    record = _dedupe_result(
        _subject(
            mode="dedupe",
            manifest=_degraded_tree_subject()["manifest"],
            lock=_degraded_tree_subject()["lock"],
            options={"max_requesters": 20},
        ),
        "shared",
    )
    evidence = record.evidence
    assert evidence["degraded"] is False
    assert evidence.get("degrade_reason") is None
    assert len(evidence["minimal_conflict_set"]) == 2


def test_mus_single_element_form():
    # 某个范围自己就无解（R5 形态）→ MUS 是单元素
    requesters = [{"id": "a|>=1.0.0 <1.0.0", "range": ">=1.0.0 <1.0.0"}]
    result = mus.find_minimal_conflict_set(requesters, ["1.0.0"], semver_core.satisfies)
    assert result["minimal"] == requesters
    assert result["degraded"] is False
    assert result["searched"] == 1


# ================================================================== M4 conflict
def _peer_tree_subject(options=None):
    return _subject(
        mode="conflict",
        manifest=_manifest({"react": "^18.0.0", "widget": "1.0.0"}),
        lock=_lock(
            {"react": "^18.0.0", "widget": "1.0.0"},
            [
                _pkg("node_modules/react", "18.2.0"),
                _pkg("node_modules/widget", "1.0.0", peer_deps={"react": "^17.0.0"}),
            ],
        ),
        options=options,
    )


def _conflict_result(subject, kind, package):
    hits = [r for r in _evaluate(subject) if r.path.startswith("conflicts.%s." % kind) and r.evidence["package"] == package]
    assert len(hits) == 1, "应报一条 %s/%s" % (kind, package)
    return hits[0]


def test_peer_conflict_minimal_set():
    record = _conflict_result(_peer_tree_subject(), "peer-conflict", "react")
    evidence = record.evidence
    assert evidence["locked_version"] == "18.2.0"
    assert len(evidence["minimal_set"]) == 2
    assert any(m["range"] == "^17.0.0" for m in evidence["minimal_set"])
    assert any(m["range"] == "^18.0.0" for m in evidence["minimal_set"])
    assert evidence["conflict_proof"]["intersects"] is False
    assert record.verdict == ERROR


def test_ignore_peer_downgrades_to_info():
    record = _conflict_result(_peer_tree_subject({"ignore_peer": True}), "peer-conflict", "react")
    assert record.verdict == INFO
    assert record.evidence["downgraded_by"] == "--ignore-peer"


def test_peer_unmet_absence():
    subject = _subject(
        mode="conflict",
        manifest=_manifest({"widget": "1.0.0"}),
        lock=_lock({"widget": "1.0.0"}, [_pkg("node_modules/widget", "1.0.0", peer_deps={"react": "^17.0.0"})]),
    )
    record = _conflict_result(subject, "peer-conflict", "react")
    assert record.evidence["locked_version"] is None
    assert record.evidence["conflict_proof"]["computed_by"] == "absence"


def test_version_conflict_removal_property():
    deps = {"a": "^1.0.0", "b": "^1.0.0", "c": "^1.0.0", "d": "^1.0.0"}
    packages = [
        _pkg("node_modules/a", "1.0.0", {"shared": "^1.0.0"}),
        _nested("a", "shared", "1.2.0"),
        _pkg("node_modules/b", "1.0.0", {"shared": "^1.5.0"}),
        _nested("b", "shared", "1.6.0"),
        _pkg("node_modules/c", "1.0.0", {"shared": "^1.8.0"}),
        _nested("c", "shared", "1.9.0"),
        _pkg("node_modules/d", "1.0.0", {"shared": "^3.0.0"}),
        _nested("d", "shared", "3.0.0"),
    ]
    subject = _subject(mode="conflict", manifest=_manifest(deps), lock=_lock(deps, packages))
    record = _conflict_result(subject, "version-conflict", "shared")
    minimal = record.evidence["minimal_set"]
    locked = ["1.2.0", "1.6.0", "1.9.0", "3.0.0"]
    _assert_mus_properties([m["range"] for m in minimal], locked)
    assert record.evidence["requesters"] == 4


def test_version_conflict_degraded_properties():
    record = _conflict_result(_conflict_degraded_subject(), "version-conflict", "shared")
    evidence = record.evidence
    assert evidence["requesters"] == 13
    assert evidence["degraded"] is True
    assert evidence["degrade_reason"] == "requesters > max"
    assert len(evidence["minimal_set"]) < evidence["requesters"]
    _assert_mus_properties([m["range"] for m in evidence["minimal_set"]], ["1.0.0", "1.6.0"])


def _conflict_degraded_subject(options=None):
    deps = {}
    packages = []
    for i in range(12):
        name = "p%02d" % i
        deps[name] = "^1.0.0"
        packages.append(_pkg("node_modules/%s" % name, "1.0.0", {"shared": "1.0.0"}))
        packages.append(_nested(name, "shared", "1.0.0"))
    deps["q"] = "^1.0.0"
    packages.append(_pkg("node_modules/q", "1.0.0", {"shared": "^1.5.0"}))
    packages.append(_nested("q", "shared", "1.6.0"))
    return _subject(mode="conflict", manifest=_manifest(deps), lock=_lock(deps, packages), options=options)


def test_version_conflict_untruncated_minimal_two():
    record = _conflict_result(_conflict_degraded_subject({"max_requesters": 20}), "version-conflict", "shared")
    evidence = record.evidence
    assert evidence["degraded"] is False
    assert evidence.get("degrade_reason") is None
    assert len(evidence["minimal_set"]) == 2
    _assert_mus_properties([m["range"] for m in evidence["minimal_set"]], ["1.0.0", "1.6.0"])


def test_no_conflict_clean_tree():
    subject = _subject(
        mode="conflict",
        manifest=_manifest({"a": "^1.0.0"}),
        lock=_lock({"a": "^1.0.0"}, [_pkg("node_modules/a", "1.2.0")]),
    )
    records = _evaluate(subject)
    assert not [r for r in records if r.path.startswith("conflicts.")]
    report = _report(subject)
    assert report.exit_code() == EXIT_OK


def test_conflict_proof_cross_checked_registered():
    # 差分对照（semver.intersects vs 区间代数）在单实现里退化为同一实现：
    # cross_checked 恒为 None 是登记过的口径差（docs §7），不许谎称双实现复核过。
    record = _conflict_result(_peer_tree_subject(), "peer-conflict", "react")
    assert record.evidence["conflict_proof"]["cross_checked"] is None


def test_conflicts_sorted():
    subject = _subject(
        mode="conflict",
        manifest=_manifest({"react": "^18.0.0", "widget": "1.0.0"}),
        lock=_lock(
            {"react": "^18.0.0", "widget": "1.0.0"},
            [
                _pkg("node_modules/react", "18.2.0"),
                _pkg("node_modules/widget", "1.0.0", peer_deps={"react": "^17.0.0"}),
            ],
        ),
    )
    conflicts = [r for r in _evaluate(subject) if r.path.startswith("conflicts.")]
    assert len(conflicts) == 1  # 本树只有 peer-conflict；version-conflict 无共同解才报


# ================================================================== 真实树等价夹具（20 包）
def _real_tree_subject():
    packages = [
        _pkg("node_modules/@fixture/bytes", "3.1.2"),
        _pkg("node_modules/debug", "2.6.9", {"ms": "2.0.0"}),
        _pkg("node_modules/@fixture/depd", "2.0.0"),
        _pkg("node_modules/@fixture/destroy", "1.2.0"),
        _pkg("node_modules/@fixture/ee-first", "1.1.1"),
        _pkg("node_modules/@fixture/encodeurl", "1.0.2"),
        _pkg("node_modules/@fixture/escape-html", "1.0.3"),
        _pkg("node_modules/@fixture/etag", "1.8.1"),
        _pkg("node_modules/@fixture/fresh", "0.5.2"),
        _pkg(
            "node_modules/@fixture/http-errors",
            "2.0.0",
            {
                "@fixture/depd": "2.0.0",
                "@fixture/inherits": "2.0.4",
                "@fixture/setprototypeof": "1.2.0",
                "@fixture/statuses": "2.0.1",
                "@fixture/toidentifier": "1.0.1",
            },
        ),
        _pkg("node_modules/@fixture/inherits", "2.0.4"),
        _pkg("node_modules/@fixture/mime", "1.6.0"),
        _pkg("node_modules/ms", "2.0.0"),
        _pkg("node_modules/@fixture/on-finished", "2.4.1", {"@fixture/ee-first": "1.1.1"}),
        _pkg("node_modules/@fixture/range-parser", "1.2.1"),
        _pkg(
            "node_modules/send",
            "0.18.0",
            {
                "debug": "2.6.9",
                "@fixture/depd": "2.0.0",
                "@fixture/destroy": "1.2.0",
                "@fixture/encodeurl": "~1.0.2",
                "@fixture/escape-html": "~1.0.3",
                "@fixture/etag": "~1.8.1",
                "@fixture/fresh": "0.5.2",
                "@fixture/http-errors": "2.0.0",
                "@fixture/mime": "1.6.0",
                "ms": "2.1.3",
                "@fixture/on-finished": "2.4.1",
                "@fixture/range-parser": "~1.2.1",
                "@fixture/statuses": "2.0.1",
            },
        ),
        _pkg("node_modules/send/node_modules/ms", "2.1.3"),
        _pkg("node_modules/@fixture/setprototypeof", "1.2.0"),
        _pkg("node_modules/@fixture/statuses", "2.0.1"),
        _pkg("node_modules/@fixture/toidentifier", "1.0.1"),
    ]
    root = {"@fixture/bytes": "3.1.2", "debug": "2.6.9", "send": "0.18.0"}
    return _subject(mode="audit", manifest=_manifest(root), lock=_lock(root, packages))


def test_real_tree_topology_not_flattened():
    subject = _real_tree_subject()
    assert len(subject["lock"]["packages"]) == 20
    ms_versions = [p for p in subject["lock"]["packages"] if p["name"] == "ms"]
    assert [p["version"] for p in ms_versions] == ["2.0.0", "2.1.3"]
    assert ms_versions[0]["path"] == "node_modules/ms"
    assert ms_versions[1]["path"] == "node_modules/send/node_modules/ms"


def test_real_tree_not_convergible_ms():
    record = _dedupe_result(_real_tree_subject(), "ms")
    evidence = record.evidence
    assert evidence["status"] == "NOT_CONVERGIBLE"
    assert evidence["reason"] == "empty-intersection"
    assert evidence["degraded"] is False
    assert evidence["requesters"] == 2
    assert evidence["targets"] == []
    assert len(evidence["minimal_conflict_set"]) == 2


def test_real_tree_minimal_set_matches_raw():
    record = _dedupe_result(_real_tree_subject(), "ms")
    # 原始 JSON 里的请求者：debug@2.6.9 → "2.0.0"、send@0.18.0 → "2.1.3"
    paths = sorted(tuple(m["requester_path"]) for m in record.evidence["minimal_conflict_set"])
    assert paths == [
        ("<root>", "debug@2.6.9"),
        ("<root>", "send@0.18.0"),
    ]
    assert sorted(m["range"] for m in record.evidence["minimal_conflict_set"]) == ["2.0.0", "2.1.3"]


def test_real_tree_mus_properties():
    record = _dedupe_result(_real_tree_subject(), "ms")
    _assert_mus_properties(
        [m["range"] for m in record.evidence["minimal_conflict_set"]],
        record.evidence["locked_versions"],
    )


def test_real_tree_no_false_positive_m2():
    records = _evaluate(_real_tree_subject())
    assert not [r for r in records if r.path.startswith("lock.")]
    assert not [r for r in records if r.path.startswith("manifest.deps.")]
    report = _report(_real_tree_subject())
    assert report.exit_code() == EXIT_BLOCKED  # ms 的 NOT_CONVERGIBLE + version-conflict 是 error


# ================================================================== 确定性
def _rich_subject():
    deps = {"send": "^0.19.2", "loose": ">=1.0.0", "wild": "*", "empty": ">=1.0.0 <1.0.0"}
    packages = [
        _pkg("node_modules/send", "0.18.0", {"ms": "2.1.3"}),
        _nested("send", "ms", "2.1.3"),
        _pkg("node_modules/loose", "1.5.0", {"ms": "2.0.0"}),
        _nested("loose", "ms", "2.0.0"),
        _pkg("node_modules/wild", "3.0.0"),
        _pkg("node_modules/empty", "1.0.0"),
    ]
    return _subject(mode="audit", manifest=_manifest(deps), lock=_lock(deps, packages))


def test_determinism_double_run_identical():
    report_a = _report(_rich_subject())
    report_b = _report(_rich_subject())
    assert json.dumps(report_a.as_dict(), ensure_ascii=False, sort_keys=True) == json.dumps(
        report_b.as_dict(), ensure_ascii=False, sort_keys=True
    )


def test_determinism_no_timestamps_or_paths():
    out = json.dumps(_report(_rich_subject()).as_dict(), ensure_ascii=False)
    import re

    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", out), "不得含 ISO 时间戳"
    # 盘符绝对路径不写字面量（脱敏门连测试源码一起扫）
    drive_marker = "%s%s" % ("D:", chr(92))
    assert drive_marker not in out and "/tmp/" not in out and "%TEMP%" not in out, "不得含绝对路径"


def test_determinism_records_stable_order():
    keys_a = [(r.rule_id, r.path) for r in _report(_rich_subject()).records]
    keys_b = [(r.rule_id, r.path) for r in _report(_rich_subject()).records]
    assert keys_a == keys_b


def test_determinism_rich_fixture_hits_all_sections():
    records = _evaluate(_rich_subject())
    assert [r for r in records if r.path.startswith("manifest.deps.")]
    assert [r for r in records if r.path.startswith("lock.")]
    assert [r for r in records if r.path.startswith("dedupe.")]
    assert [r for r in records if r.path.startswith("conflicts.")]
    assert [r for r in records if r.path == "summary"]


# ================================================================== 退出码矩阵
def _write_subject(tmp_path, subject):
    path = tmp_path / "subject.json"
    path.write_text(json.dumps(subject, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_exit_code_zero_clean(tmp_path):
    rc = cli.main(["check", SLUG, "--input", _write_subject(tmp_path, _subject())])
    assert rc == EXIT_OK


def test_exit_code_one_error_finding(tmp_path):
    subject = _subject(
        manifest=_manifest({"send": "^0.19.2"}),
        lock=_lock({"send": "^0.19.2"}, [_pkg("node_modules/send", "0.18.0")]),
    )
    rc = cli.main(["check", SLUG, "--input", _write_subject(tmp_path, subject)])
    assert rc == EXIT_BLOCKED


def test_exit_code_zero_warn_only(tmp_path):
    # 旧仓默认 --fail-on=error：仅 warning（R1 无上界）不改变退出码
    subject = _subject(
        manifest=_manifest({"a": ">=1.0.0"}),
        lock=_lock({"a": ">=1.0.0"}, [_pkg("node_modules/a", "1.2.0")]),
    )
    rc = cli.main(["check", SLUG, "--input", _write_subject(tmp_path, subject)])
    assert rc == EXIT_OK


def test_exit_code_two_invalid_input(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"mode": "audit"}), encoding="utf-8")
    rc = cli.main(["check", SLUG, "--input", str(path)])
    assert rc == EXIT_INPUT


def test_exit_code_two_broken_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ broken json", encoding="utf-8")
    rc = cli.main(["check", SLUG, "--input", str(path)])
    assert rc == EXIT_INPUT


def test_exit_code_three_missing_rule(tmp_path):
    basis_path = tmp_path / "empty.basis.json"
    basis_path.write_text(json.dumps({"version": "1", "rules": []}), encoding="utf-8")
    rc = cli.main(
        [
            "check",
            SLUG,
            "--input",
            _write_subject(tmp_path, _subject()),
            "--basis",
            str(basis_path),
        ]
    )
    assert rc == EXIT_CONTRACT


def test_exit_code_three_unknown_organ(tmp_path):
    rc = cli.main(["check", "no-such-organ", "--input", _write_subject(tmp_path, _subject())])
    assert rc == EXIT_CONTRACT


def test_exit_code_priority_rich_fixture():
    report = _report(_rich_subject())
    assert report.summary()["blocking"] >= 1
    assert report.exit_code() == EXIT_BLOCKED


# ================================================================== 模式分派
def _sections(records):
    prefixes = ("manifest.deps.", "lock.", "dedupe.", "conflicts.", "summary")
    return {p.rstrip(".") for p in prefixes if any(r.path.startswith(p) for r in records)}


def test_mode_range_lint_only_skips_other_sections():
    records = _evaluate(_subject(mode="range-lint", manifest=_manifest({"a": ">=1.0.0"})))
    assert _sections(records) == {"manifest.deps", "summary"}


def test_mode_lock_manifest_only():
    records = _evaluate(
        _subject(
            mode="lock-manifest",
            manifest=_manifest({"send": "^0.19.2"}),
            lock=_lock({"send": "^0.19.2"}, [_pkg("node_modules/send", "0.18.0")]),
        )
    )
    assert "lock" in _sections(records)
    assert not [r for r in records if r.path.startswith("manifest.deps.")]
    assert not [r for r in records if r.path.startswith("dedupe.")]


def test_mode_dedupe_only():
    records = _evaluate(_ms_tree())
    assert "dedupe" in _sections(records)
    assert not [r for r in records if r.path.startswith("lock.")]
    assert not [r for r in records if r.path.startswith("manifest.deps.")]


def test_mode_conflict_only():
    records = _evaluate(_peer_tree_subject())
    assert "conflicts" in _sections(records)
    assert not [r for r in records if r.path.startswith("dedupe.")]


def test_mode_audit_runs_all_four():
    records = _evaluate(_rich_subject())
    assert {"manifest.deps", "lock", "dedupe", "conflicts", "summary"} <= _sections(records)


def test_mode_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(mode="doctor"))


# ================================================================== 输入校验
def test_missing_manifest_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "lock": _lock()})


def test_missing_lock_rejected():
    with pytest.raises(ValueError):
        _evaluate({"mode": "audit", "manifest": _manifest()})


def test_manifest_range_non_string_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(manifest={"name": "f", "deps": {"dependencies": {"a": 3}}}))


def test_lock_entry_without_path_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(lock={"packages": [{"name": "a", "version": "1.0.0"}]}))


def test_root_marker_in_packages_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(lock=_lock(packages=[{"path": "<root>", "name": "f"}])))


def test_options_prefer_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(options={"prefer": "newest"}))


def test_options_max_requesters_invalid_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(options={"max_requesters": 0}))


def test_lock_entry_version_non_string_rejected():
    with pytest.raises(ValueError):
        _evaluate(_subject(lock={"packages": [{"path": "node_modules/a", "version": 1}]}))
