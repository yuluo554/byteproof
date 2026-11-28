"""编排层：``evaluate(subject, basis) -> Iterable[Record]``。

七种模式（``spec.MODES``）：``junit`` / ``ingest`` / ``flaky`` / ``slow`` / ``diff`` /
``views`` / ``gate``。旧仓 ``pipeline`` 的编排面（解析 → 入库 → 查询 → 分型 → 门禁）在账本里
逐段可寻址；**入库面留输入层**（行集合由调用方给或由 ``ingest`` 在内存里生成）。

退出码：旧仓 0 达标 / 1 门禁触发 / 2 用法错误 / 3 依赖缺失 / 4 未实现（M0）。账本侧
0 无阻断 / 1 有 error（文件级原因码、缺失入参、门禁命中）/ 2 输入不合法 / 3 契约违约。
**判定内容不因承载层变化**：四类分型、p50/p95、回归三态、diff 三类逐条进账本。
"""

from __future__ import annotations

import base64
import binascii
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import core, facts, judge, spec
from .catalogue import Catalogue


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if mode not in spec.MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(spec.MODES), mode))
    catalogue = Catalogue(basis)
    records: List[Record] = []
    summary: Dict[str, Any] = {"mode": mode}

    if mode == "junit":
        outcome = _parse_subject(subject)
        records.extend(_junit_records(outcome, catalogue))
        totals = core.outcome_totals(outcome)
        summary.update({
            "file": outcome["display_path"], "reason": outcome["reason"],
            "detail": outcome["detail"], "framework": outcome["framework"],
            "totals": totals, "degraded": dict(outcome["degraded"]),
            "suites": len(outcome["suites"]),
            "cases": sum(len(suite["cases"]) for suite in outcome["suites"]),
        })
    elif mode == "ingest":
        report = facts.ingest(_files_of(subject), _store_of(subject))
        # 输入层解析不出的入参（路径不存在 / 不可读）由调用方显式列出——器官不 stat 文件
        missing = subject.get("missing_paths") or []
        if not isinstance(missing, list):
            raise ValueError("missing_paths 必须是数组")
        report["missing_paths"] = [str(item) for item in missing]
        records.extend(_ingest_records(report, catalogue))
        summary.update({
            "files": report["files"], "runs": report["runs"],
            "cases": report["cases"], "occurrences": report["occurrences"],
            "skipped": report["skipped"], "frameworks": list(report["frameworks"]),
            "skipped_reasons": {key: list(value)
                                for key, value in report["skipped_reasons"].items()},
            "degraded_counts": dict(report["degraded_counts"]),
            "summary_line": facts.summary_line(report),
        })
    elif mode == "flaky":
        profiles, per_case = _flaky_profiles(subject)
        records.extend(_flaky_records(per_case, catalogue))
        summary.update({
            "labels": judge.label_counts(profiles),
            "counts": len(per_case),
            "window": _window(subject),
        })
    elif mode == "slow":
        rendered = _slow_subject(subject)
        records.extend(_slow_records(rendered, catalogue))
        summary.update({
            "cases": len(rendered),
            "regressions": sum(1 for item in rendered if item["regression"] is True),
            "undecidable": sum(1 for item in rendered if item["regression"] is None),
            "labels": _count_labels(rendered),
        })
    elif mode == "diff":
        rows = _diff_subject(subject)
        classified = judge.classify_rows(rows)
        records.extend(_diff_records(classified, catalogue))
        counts = judge.diff_counts(classified)
        summary.update({"counts": counts, "new_failures": counts[spec.NEW_FAILURES]})
    elif mode == "gate":
        gate = _gate(subject)
        records.append(_record(
            spec.R_GATE, ERROR if gate["triggered"] else INFO, catalogue,
            "门禁 %s：%s" % (gate["fail_on"], gate["reason"]), "gate:" + gate["fail_on"],
            evidence=gate,
        ))
        summary.update(gate)
    else:  # views
        views = _views(subject)
        records.extend(_views_records(views, catalogue))
        summary.update({
            "run_id": views["run_id"],
            "tree_suites": len(views["tree"]),
            "summary": views["summary"],
            "matrix_rows": len(views["matrix"][1]),
            "slow_rows": len(views["slow_rows"]),
            "diff_counts": views["diff_counts"],
        })

    records = _dedupe(records)
    summary["blocking"] = sum(1 for record in records if record.verdict == ERROR)
    summary["total"] = len(records)
    records.append(_record(
        spec.R_SUMMARY_RULE, INFO, catalogue,
        "testdeck 汇总（%s 模式）：%d 条记录，阻断 %d 条"
        % (mode, summary["total"], summary["blocking"]),
        "report", evidence=summary,
    ))
    return records


# ---------------------------------------------------------------- subject 读取
def _parse_subject(subject: Mapping[str, Any]) -> Dict[str, Any]:
    file_name = str(subject.get("file_name") or "")
    if subject.get("xml") is not None:
        return core.parse_xml_text(str(subject["xml"]), file_name=file_name,
                                   display_path=str(subject.get("display_path") or file_name))
    if subject.get("bytes_b64") is not None:
        return core.parse_xml_bytes(_bytes(subject["bytes_b64"]), file_name=file_name,
                                     display_path=str(subject.get("display_path") or file_name))
    raise ValueError("junit 模式需要 xml 或 bytes_b64")


def _bytes(value: Any) -> bytes:
    if not isinstance(value, str):
        raise ValueError("bytes_b64 必须是 base64 字符串")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("bytes_b64 不是合法 base64：%s" % (exc,))


def _files_of(subject: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    files = subject.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("ingest 模式需要非空 files 数组")
    prepared = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("files 的元素必须是对象")
        entry = dict(item)
        if entry.get("bytes_b64") is not None:
            entry["bytes"] = _bytes(entry.pop("bytes_b64"))
        prepared.append(entry)
    return prepared


def _store_of(subject: Mapping[str, Any]) -> facts.Store:
    """可选：``existing_facts`` 预置行集合（测入库幂等 / 跨批）。"""
    store = facts.Store()
    existing = subject.get("existing_facts")
    if existing is None:
        return store
    for run in existing.get("runs", []):
        store.upsert_run(
            core.RunIdentity(run.get("branch", ""), run.get("commit_sha", ""),
                             run.get("ci_run_id", "")),
            started_at=run.get("started_at", ""), source_path=run.get("source_path", ""),
            framework=run.get("framework", ""))
    for case in existing.get("cases", []):
        store.upsert_case(core.CaseIdentity(case["suite_name"], case["classname"], case["name"]))
    for occurrence in existing.get("occurrences", []):
        store.upsert_occurrence(
            int(occurrence["run_id"]), int(occurrence["case_id"]), occurrence["status"],
            time_ms=occurrence.get("time_ms"),
            failure_type=occurrence.get("failure_type", ""),
            failure_message=occurrence.get("failure_message", ""),
            stack_first_line=occurrence.get("stack_first_line", ""))
    return store


def _window(subject: Mapping[str, Any]) -> int:
    window = subject.get("window", spec.VIEW_RULES["sparkline_runs"])
    if not isinstance(window, int) or window < 1:
        raise ValueError("window 必须是 >= 1 的整数")
    return window


def _flaky_profiles(subject: Mapping[str, Any]):
    histories = subject.get("histories")
    if not isinstance(histories, list) or not histories:
        raise ValueError("flaky 模式需要非空 histories 数组")
    per_case = []
    for index, item in enumerate(histories):
        if not isinstance(item, dict) or not isinstance(item.get("series"), list):
            raise ValueError("histories[%d] 需要 series 数组" % index)
        series = []
        for entry in item["series"]:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ValueError("series 的每一项必须是 [run, status]")
            run, status = entry
            if not isinstance(run, int):
                raise ValueError("series 的 run 必须是整数")
            core.validate_status(status)
            series.append((run, status))
        rules = dict(spec.FLAKY_RULES)
        if isinstance(item.get("rules"), dict):
            rules.update(item["rules"])
        profile = judge.classify_flaky(series, rules)
        profile["case_id"] = item.get("case_id", index + 1)
        profile["name"] = item.get("name", "")
        per_case.append(profile)
    return per_case, per_case


def _slow_subject(subject: Mapping[str, Any]) -> List[Dict[str, Any]]:
    cases = subject.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("slow 模式需要非空 cases 数组")
    rendered = []
    for index, item in enumerate(cases):
        if not isinstance(item, dict) or not isinstance(item.get("timings"), list):
            raise ValueError("cases[%d] 需要 timings 数组" % index)
        for value in item["timings"]:
            if value is not None and not isinstance(value, int):
                raise ValueError("timings 必须是整数毫秒或 null")
        rules = dict(spec.SLOW_RULES)
        if isinstance(item.get("rules"), dict):
            rules.update(item["rules"])
        rendered.append(judge.profile_case(
            item.get("case_id", index + 1),
            item.get("suite_name", ""), item.get("classname", ""), item.get("name", ""),
            item.get("time_ms"), item["timings"], item.get("split"), rules))
    return rendered


def _diff_subject(subject: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    rows = subject.get("rows")
    if not isinstance(rows, list):
        raise ValueError("diff 模式需要 rows 数组")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("rows[%d] 必须是对象" % index)
        for side in ("status_before", "status_after"):
            if row.get(side) is not None:
                core.validate_status(row[side])
    return rows


def _gate(subject: Mapping[str, Any]) -> Dict[str, Any]:
    fail_on = subject.get("fail_on")
    if fail_on not in spec.VIEW_RULES["fail_on"]:
        raise ValueError("fail_on 必须是 %s 之一" % ("/".join(spec.VIEW_RULES["fail_on"]),))
    counts = None
    if subject.get("rows") is not None:
        counts = judge.diff_counts(judge.classify_rows(_diff_subject(subject)))
    if fail_on == "new-failures":
        hit = int((counts or {}).get(spec.NEW_FAILURES, 0))
        reason = "new-failures=%d" % hit
    elif fail_on == "flaky":
        profiles, _per = _flaky_profiles(subject)
        hit = judge.label_counts(profiles).get(spec.LABEL_FLAKY, 0)
        reason = "flaky=%d" % hit
    else:  # regressions
        rendered = _slow_subject(subject)
        hit = len(judge.regression_list(rendered))
        reason = "regressions=%d" % hit
    return {"fail_on": fail_on, "hit": hit, "triggered": hit > 0, "reason": reason}


def _views(subject: Mapping[str, Any]) -> Dict[str, Any]:
    row_facts = subject.get("facts")
    if not isinstance(row_facts, dict) or not isinstance(row_facts.get("runs"), list):
        raise ValueError("views 模式需要 facts.runs 数组（输入层的行集合）")
    run_id = subject.get("run_id")
    if run_id is None:
        if not row_facts["runs"]:
            raise ValueError("facts.runs 为空且未给 run_id")
        run_id = max(int(run["run_id"]) for run in row_facts["runs"])
    run_id = int(run_id)
    window = _window(subject)
    tree = facts.tree_rows(row_facts, run_id)
    view_summary = facts.summary(row_facts, run_id, window)
    matrix = facts.matrix_rows(row_facts, run_id, window)
    slow = facts.slow_rows(row_facts, run_id, window)
    previous = facts.previous_run(row_facts, run_id)
    diff_counts = None
    classified: List[Mapping[str, Any]] = []
    if previous is not None:
        classified = judge.classify_rows(facts.diff_rows(row_facts, previous["run_id"], run_id))
        diff_counts = judge.diff_counts(classified)
    return {
        "run_id": run_id, "window": window, "tree": tree, "summary": view_summary,
        "matrix": matrix, "slow_rows": slow, "previous_run": previous,
        "diff_counts": diff_counts, "classified": classified,
    }


def _count_labels(items: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        label = item.get("label") or "(样本充分)"
        counts[label] = counts.get(label, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


# ---------------------------------------------------------------- 记录构造
def _record(rule_id: str, verdict: str, catalogue: Catalogue, message: str, path: str,
            evidence: Optional[Mapping[str, Any]] = None) -> Record:
    return Record(rule_id=rule_id, verdict=verdict, message=message,
                  basis=catalogue.basis_ref(rule_id), path=path,
                  evidence=dict(evidence or {}))


def _junit_records(outcome: Mapping[str, Any], catalogue: Catalogue) -> List[Record]:
    records: List[Record] = []
    if outcome["reason"]:
        records.append(_record(
            spec.R_JUNIT_FILE, ERROR, catalogue,
            "文件未入库：%s%s" % (outcome["reason"],
                                 "（%s）" % outcome["detail"] if outcome["detail"] else ""),
            "file", evidence={"reason": outcome["reason"], "detail": outcome["detail"],
                              "path": outcome["display_path"]},
        ))
        return records
    records.append(_record(
        spec.R_JUNIT_FRAMEWORK,
        INFO, catalogue,
        "框架识别：%s" % outcome["framework"], "framework",
        evidence={"framework": outcome["framework"], "unknown": outcome["framework"] == "unknown"},
    ))
    for reason in spec.DEGRADED_REASONS:
        count = outcome["degraded"].get(reason, 0)
        if count:
            records.append(_record(
                spec.R_JUNIT_DEGRADED, WARN, catalogue,
                "单项降级：%s × %d" % (reason, count), "degraded:" + reason,
                evidence={"reason": reason, "count": count},
            ))
    return records


def _ingest_records(report: Mapping[str, Any], catalogue: Catalogue) -> List[Record]:
    records: List[Record] = []
    for missing in report.get("missing_paths", []):
        records.append(_record(
            spec.R_INGEST_MISSING, ERROR, catalogue,
            "路径不存在：%s" % missing, "missing:" + str(missing), evidence={"path": missing},
        ))
    for reason in spec.REASONS:
        paths = report["skipped_reasons"].get(reason, [])
        if paths:
            records.append(_record(
                spec.R_JUNIT_FILE, ERROR, catalogue,
                "文件未入库（%s）× %d" % (reason, len(paths)), "skipped:" + reason,
                evidence={"reason": reason, "paths": sorted(paths)},
            ))
    for reason in spec.DEGRADED_REASONS:
        count = report["degraded_counts"].get(reason, 0)
        if count:
            records.append(_record(
                spec.R_JUNIT_DEGRADED, WARN, catalogue,
                "单项降级：%s × %d" % (reason, count), "degraded:" + reason,
                evidence={"reason": reason, "count": count,
                          "paths": sorted(report["degraded_paths"].get(reason, []))},
            ))
    records.append(_record(
        spec.R_INGEST_REPORT, INFO, catalogue,
        facts.summary_line(report), "report",
        evidence={
            "files": report["files"], "runs": report["runs"], "cases": report["cases"],
            "occurrences": report["occurrences"], "skipped": report["skipped"],
            "frameworks": list(report["frameworks"]),
        },
    ))
    return records


def _flaky_records(per_case: Sequence[Mapping[str, Any]], catalogue: Catalogue) -> List[Record]:
    records = []
    for profile in per_case:
        records.append(_record(
            spec.R_FLAKY, INFO, catalogue,
            "分型 %s（fail_rate=%s，transitions=%d，计数 %d）"
            % (profile["label"], profile["fail_rate_text"], profile["transitions"],
               profile["counted_runs"]),
            "case:%d" % int(profile["case_id"]),
            evidence={
                "label": profile["label"], "fail_rate": profile["fail_rate_text"],
                "flaky_score": profile["flaky_score_text"],
                "transitions": profile["transitions"], "passes": profile["passes"],
                "fails": profile["fails"], "counted_runs": profile["counted_runs"],
            },
        ))
    counts = judge.label_counts(per_case)
    records.append(_record(
        spec.R_FLAKY_SUMMARY, INFO, catalogue,
        "分型计数：%s" % ", ".join("%s=%d" % (key, counts[key]) for key in sorted(counts)),
        "report", evidence=counts,
    ))
    return records


def _slow_records(rendered: Sequence[Mapping[str, Any]], catalogue: Catalogue) -> List[Record]:
    records = []
    for profile in rendered:
        records.append(_record(
            spec.R_SLOW, INFO, catalogue,
            "回归=%s（%s）" % (profile["regression_text"], profile["note"]),
            "case:%d" % int(profile["case_id"]),
            evidence={
                "regression": profile["regression_text"], "note": profile["note"],
                "p50": profile["p50_text"], "p95": profile["p95_text"],
                "samples": profile["samples"], "base_samples": profile["base_samples"],
                "curr_samples": profile["curr_samples"],
            },
        ))
        if profile["label"]:
            records.append(_record(
                spec.R_SLOW_SAMPLE, WARN, catalogue,
                "样本量降级：%s（samples=%d，base=%d，curr=%d）"
                % (profile["label"], profile["samples"], profile["base_samples"],
                   profile["curr_samples"]),
                "sample:%d" % int(profile["case_id"]),
                evidence={"label": profile["label"], "samples": profile["samples"]},
            ))
    records.append(_record(
        spec.R_SLOW_SUMMARY, INFO, catalogue,
        "回归清单 %d 条（判不了 %d 条）"
        % (len(judge.regression_list(rendered)),
           sum(1 for item in rendered if item["regression"] is None)),
        "report",
        evidence={"regressions": len(judge.regression_list(rendered)),
                  "undecidable": sum(1 for item in rendered if item["regression"] is None),
                  "labels": _count_labels(rendered)},
    ))
    return records


def _diff_records(classified: Sequence[Mapping[str, Any]], catalogue: Catalogue) -> List[Record]:
    records = []
    for entry in classified:
        row = entry["row"]
        records.append(_record(
            spec.R_DIFF, INFO, catalogue,
            "分类 %s（%s→%s）" % (entry["kind"], row.get("status_before") or "(缺)",
                                 row.get("status_after") or "(缺)"),
            "case:%d" % int(row.get("case_id", 0)),
            evidence={"kind": entry["kind"],
                      "status_before": row.get("status_before"),
                      "status_after": row.get("status_after"),
                      "classname": row.get("classname", ""), "name": row.get("name", "")},
        ))
    counts = judge.diff_counts(classified)
    records.append(_record(
        spec.R_DIFF_SUMMARY, INFO, catalogue,
        "diff 计数：%s" % ", ".join("%s=%d" % (kind, counts[kind]) for kind in spec.CLASS_ORDER),
        "report", evidence=counts,
    ))
    return records


def _views_records(views: Mapping[str, Any], catalogue: Catalogue) -> List[Record]:
    records: List[Record] = []
    for suite in views["tree"]:
        records.append(_record(
            spec.R_TREE, INFO, catalogue,
            "suite %s：失败 %d / 用例 %d" % (suite["name"], suite["fail_count"],
                                            len(suite["cases"])),
            "tree:%d" % int(suite["suite_id"]),
            evidence={"suite_id": suite["suite_id"], "name": suite["name"],
                      "fail_count": suite["fail_count"], "cases": len(suite["cases"])},
        ))
    records.append(_record(
        spec.R_SUMMARY, INFO, catalogue,
        "summary：%s" % ", ".join("%s=%s" % (key, views["summary"][key])
                                 for key in views["summary"]),
        "summary", evidence=dict(views["summary"]),
    ))
    for row in views["slow_rows"]:
        profile = row.get("profile") or {}
        if profile.get("regression") is True:
            records.append(_record(
                spec.R_SLOW, INFO, catalogue,
                "回归命中：%s（%s）" % (row["name"], profile.get("note", "")),
                "slow:%d" % int(row["case_id"]),
                evidence={"p50": profile.get("p50_text"), "p95": profile.get("p95_text"),
                          "note": profile.get("note")},
            ))
    for entry in views["classified"]:
        row = entry["row"]
        records.append(_record(
            spec.R_DIFF, INFO, catalogue,
            "分类 %s（%s→%s）" % (entry["kind"], row.get("status_before") or "(缺)",
                                 row.get("status_after") or "(缺)"),
            "diff:%d" % int(row["case_id"]),
            evidence={"kind": entry["kind"]},
        ))
    if views["previous_run"] is None:
        records.append(_record(
            spec.R_DIFF_SUMMARY, INFO, catalogue,
            "没有上一棒 run，diff 不判（不猜）", "report",
            evidence={"previous_run": None},
        ))
    else:
        records.append(_record(
            spec.R_DIFF_SUMMARY, INFO, catalogue,
            "diff 计数：%s" % ", ".join("%s=%d" % (kind, views["diff_counts"][kind])
                                        for kind in spec.CLASS_ORDER),
            "report", evidence=dict(views["diff_counts"]),
        ))
    records.append(_record(
        spec.R_VIEW_DEGRADE, INFO, catalogue,
        "呈现降级：单栏阈值 %d 列 / 无颜色按 NO_COLOR 与 tty"
        % int(spec.VIEW_RULES["min_width_single_column"]),
        "view",
        evidence={"min_width_single_column": spec.VIEW_RULES["min_width_single_column"],
                  "sparkline_runs": spec.VIEW_RULES["sparkline_runs"]},
    ))
    return records


def _dedupe(records: List[Record]) -> List[Record]:
    seen: Dict[str, int] = {}
    out: List[Record] = []
    for record in records:
        key = record.id
        count = seen.get(key, 0) + 1
        seen[key] = count
        if count == 1:
            out.append(record)
        else:
            out.append(Record(rule_id=record.rule_id, verdict=record.verdict,
                              message=record.message, basis=record.basis,
                              path="%s#%d" % (record.path, count),
                              evidence=record.evidence))
    return out