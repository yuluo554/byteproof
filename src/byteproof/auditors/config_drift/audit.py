"""器官 ``config-drift``：配置差异 -> 缺陷账本。

迁自 target-map ② 行（旧仓 ``cfgdelta``）。搬过来的是**判定**：
值族归一化（精确有理数）+ 六类影响分类 + semver 子类 + gate 语义
（fail-on / allow-indeterminate / indeterminate 默认阻断）。

**没有搬**：YAML/JSON/TOML/INI/.env/HCL 解析、结构无关 diff、默认值 profile 双侧施加、
CLI 子命令与渲染、golden harness。逐条处置见 ``docs/config-drift.md`` §6。
"""

from __future__ import annotations

from byteproof.core.ledger import Record

from . import classify, value
from .spec import (
    ALL_CLASSES,
    RULE_BY_CLASS,
    RULE_GATE,
    RULE_INDETERMINATE,
    RULE_SUMMARY,
    resolve_params,
    verdict_for,
)


def _canonical_evidence(canonical):
    if canonical is None:
        return None
    return {
        "family": canonical.family,
        "text": canonical.text,
        "rat": None if canonical.rat is None else str(canonical.rat),
        "ns": None if canonical.ns is None else str(canonical.ns),
        "bool": canonical.boolean,
        "state": canonical.state,
    }


def _add(records, basis, rule_id, message, path, evidence):
    records.append(
        Record(
            rule_id=rule_id,
            verdict=verdict_for(rule_id),
            message=message,
            basis=basis.ref(rule_id),
            path=path,
            evidence=evidence,
        )
    )


def _unique_paths(entries):
    counts = {}
    for entry in entries:
        counts[entry["path"]] = counts.get(entry["path"], 0) + 1
    seen = {}
    paths = []
    for entry in entries:
        path = entry["path"]
        if counts[path] > 1:
            index = seen.get(path, 0) + 1
            seen[path] = index
            paths.append("%s#%d" % (path, index))
        else:
            paths.append(path)
    return paths


def evaluate(subject, basis):
    settings = resolve_params(subject.get("params"))
    raw_entries = subject.get("entries")
    if not isinstance(raw_entries, list):
        raise classify.ClassifyError("entries 必须是列表")
    entries = [classify.normalize_entry(raw, index) for index, raw in enumerate(raw_entries)]

    result = classify.apply(entries)
    summary = result["summary"]
    paths = _unique_paths(result["entries"])

    records = []
    for path, entry in zip(paths, result["entries"]):
        if entry["kind"] == classify.KIND_INDETERMINATE:
            _add(
                records,
                basis,
                RULE_INDETERMINATE,
                "不可判定（%s）：%s" % (entry["reason"], entry["path"]),
                path,
                {"path": entry["path"], "reason": entry["reason"]},
            )
            continue
        rule = RULE_BY_CLASS[entry["class"]]
        evidence = {
            "path": entry["path"],
            "class": entry["class"],
            "subclass": entry["subclass"],
            "class_guess": entry["guess"],
            "kind": entry["kind"],
            "left": _canonical_evidence(entry["left"]),
            "right": _canonical_evidence(entry["right"]),
        }
        if entry["class"] == "纯书写":
            message = "归一后语义相同（纯书写，只计数）"
        elif entry["subclass"]:
            message = "%s（%s）" % (entry["class"], entry["subclass"])
        elif entry["guess"]:
            message = "%s（分类不确定：class_guess=true）" % entry["class"]
        else:
            message = entry["class"]
        _add(records, basis, rule, message, path, evidence)

    blocked, reason = classify.gate(summary, settings.fail_on, settings.allow_indeterminate)
    if blocked:
        _add(
            records,
            basis,
            RULE_GATE,
            "门禁命中：%s（fail_on=%s，allow_indeterminate=%s）"
            % (reason, list(settings.fail_on) or "未列（= 任一行为差异）", settings.allow_indeterminate),
            "<summary>",
            {
                "reason": reason,
                "fail_on": list(settings.fail_on),
                "allow_indeterminate": settings.allow_indeterminate,
                "summary": summary,
            },
        )

    _add(
        records,
        basis,
        RULE_SUMMARY,
        "total %d · behavioral %d · cosmetic %d · indeterminate %d"
        % (summary["total"], summary["behavioral"], summary["cosmetic"], summary["indeterminate"]),
        "<summary>",
        {"summary": summary, "blocked": blocked},
    )
    return records