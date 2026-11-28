"""编排层（迁自 10-19-testdeck 的 ``queries`` / ``ingest`` 的判定面）。

**留输入层**：旧仓 ``db.py`` 的 SQLite 读写 → 账本在**内存行集合**上重算；入库幂等语义
（同 run 身份 / 同用例身份不新增行、同 (run, case) 覆盖）移植为 :class:`Store` 的纯 dict
更新（不碰磁盘、不读时钟）。查询函数只吃行集合，不再发 SQL——查询口径（失败优先排序单点、
矩阵行序 ``flaky_score`` 降序、窗口中点切分）1:1 保留。
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import core, judge, spec


# ============================================================ 失败优先排序（单点）
def fail_first_key(fail_count: int, secondary):
    """同父节点下 ``fail_count > 0`` 的子树在前，其余按 ``secondary``。"""
    return (0 if fail_count > 0 else 1, secondary)


def order_cases(cases: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return sorted(cases, key=lambda case: fail_first_key(
        1 if case.get("status") == spec.STATUS_FAIL else 0, case.get("name", "")))


def order_classes(groups: Sequence[Tuple[str, Sequence[Mapping[str, Any]]]]):
    return sorted(
        groups,
        key=lambda item: fail_first_key(
            sum(1 for case in item[1] if case.get("status") == spec.STATUS_FAIL), item[0]),
    )


# ============================================================ 行集合读取
def run_cases(facts: Mapping[str, Any], run_id: int) -> List[Dict[str, Any]]:
    by_id = {int(case["case_id"]): case for case in facts.get("cases", [])}
    rows = []
    for occurrence in facts.get("occurrences", []):
        if int(occurrence["run_id"]) != int(run_id):
            continue
        case = by_id.get(int(occurrence["case_id"]))
        if case is None:
            continue
        row = dict(case)
        row.update({
            "status": occurrence.get("status", spec.STATUS_MISSING),
            "time_ms": occurrence.get("time_ms"),
            "failure_type": occurrence.get("failure_type", ""),
            "failure_message": occurrence.get("failure_message", ""),
            "stack_first_line": occurrence.get("stack_first_line", ""),
        })
        rows.append(row)
    return sorted(rows, key=lambda row: (row["suite_name"], row["classname"], row["name"]))


def tree_rows(facts: Mapping[str, Any], run_id: int) -> List[Dict[str, Any]]:
    """失败优先树（suite → class → case，三层各自失败优先；suite 组内按 ``suite_id``）。"""
    pending: Dict[str, List[Dict[str, Any]]] = {}
    for case in run_cases(facts, run_id):
        pending.setdefault(case["suite_name"], []).append(case)
    suites = []
    for row in sorted(
        (suite for suite in facts.get("suites", []) if int(suite["run_id"]) == int(run_id)),
        key=lambda suite: suite["suite_id"],
    ):
        suite_cases = pending.pop(row["name"], [])
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for case in suite_cases:
            buckets.setdefault(case["classname"], []).append(case)
        ordered: List[Dict[str, Any]] = []
        for _name, group in order_classes(list(buckets.items())):
            ordered.extend(order_cases(group))
        suites.append({**row, "cases": ordered})
    for name in sorted(pending):
        group = order_cases(pending[name])
        suites.append({"suite_id": -1, "run_id": int(run_id), "name": name, "source_path": "",
                       "time_ms": None, "tests": len(group), "failures": 0, "errors": 0,
                       "skipped": 0, "cases": group})
    for suite in suites:
        suite["fail_count"] = sum(1 for case in suite["cases"]
                                   if case.get("status") == spec.STATUS_FAIL)
    return sorted(suites, key=lambda suite: fail_first_key(suite["fail_count"], suite["suite_id"]))


def window_runs(facts: Mapping[str, Any], run_id: int, window: int) -> List[Dict[str, Any]]:
    rows = [run for run in facts.get("runs", []) if int(run["run_id"]) <= int(run_id)]
    rows.sort(key=lambda run: run["run_id"])
    return rows[-int(window):]


def previous_run(facts: Mapping[str, Any], run_id: int) -> Optional[Dict[str, Any]]:
    rows = [run for run in facts.get("runs", []) if int(run["run_id"]) < int(run_id)]
    if not rows:
        return None
    return sorted(rows, key=lambda run: run["run_id"])[-1]


def history(facts: Mapping[str, Any], case_id: int, window: int) -> List[Tuple[int, str]]:
    """最近 ``window`` 次 run 的状态序列（``run_id`` 升序；ingest 顺序是稳定次序）。"""
    rows = [occ for occ in facts.get("occurrences", [])
            if int(occ["case_id"]) == int(case_id)]
    rows.sort(key=lambda occ: occ["run_id"])
    rows = rows[-int(window):]
    return [(int(occ["run_id"]), occ["status"]) for occ in rows]


def case_profiles(facts: Mapping[str, Any], run_id: int, window: int,
                  rules: Mapping[str, Any] = spec.FLAKY_RULES) -> Dict[int, Dict[str, Any]]:
    column_ids = {int(run["run_id"]) for run in window_runs(facts, run_id, window)}
    histories: Dict[int, List[Tuple[int, str]]] = {}
    for occ in sorted(facts.get("occurrences", []),
                      key=lambda occ: (int(occ["case_id"]), int(occ["run_id"]))):
        if int(occ["run_id"]) not in column_ids:
            continue
        histories.setdefault(int(occ["case_id"]), []).append(
            (int(occ["run_id"]), occ["status"]))
    return {case_id: judge.classify_flaky(seq, rules) for case_id, seq in histories.items()}


def matrix_rows(facts: Mapping[str, Any], run_id: int, window: int,
                rules: Mapping[str, Any] = spec.FLAKY_RULES):
    """test × run 矩阵：行序 = ``flaky_score`` 降序，同分按身份字典序（精确 Fraction 可排序）。"""
    columns = window_runs(facts, run_id, window)
    column_ids = [int(run["run_id"]) for run in columns]
    profiles = case_profiles(facts, run_id, window, rules)
    statuses: Dict[int, Dict[int, str]] = {}
    for occ in facts.get("occurrences", []):
        if int(occ["run_id"]) in column_ids:
            statuses.setdefault(int(occ["case_id"]), {})[int(occ["run_id"])] = occ["status"]
    rows = []
    for case in facts.get("cases", []):
        case_id = int(case["case_id"])
        profile = profiles.get(case_id)
        rows.append({
            "case_id": case_id,
            "suite_name": case["suite_name"],
            "classname": case["classname"],
            "name": case["name"],
            "statuses": tuple(statuses.get(case_id, {}).get(column) for column in column_ids),
            "profile": profile,
            "flaky_score": Fraction(0) if profile is None else profile["flaky_score"],
        })
    rows.sort(key=lambda row: (-row["flaky_score"], row["suite_name"], row["classname"], row["name"]))
    return columns, rows


def slow_profiles(facts: Mapping[str, Any], run_id: int, window: int,
                  rules: Mapping[str, Any] = spec.SLOW_RULES) -> Dict[int, Dict[str, Any]]:
    """窗口内每条用例的慢画像；切分点 = 窗口中点（编排层的取数决定，判定层不发明）。"""
    columns = window_runs(facts, run_id, window)
    column_ids = [int(run["run_id"]) for run in columns]
    split = len(column_ids) // 2
    timings: Dict[int, Dict[int, Optional[int]]] = {}
    current: Dict[int, Optional[int]] = {}
    for occ in facts.get("occurrences", []):
        case_id = int(occ["case_id"])
        if int(occ["run_id"]) in column_ids:
            timings.setdefault(case_id, {})[int(occ["run_id"])] = occ.get("time_ms")
        if int(occ["run_id"]) == int(run_id):
            current[case_id] = occ.get("time_ms")
    return {
        int(case["case_id"]): judge.profile_case(
            int(case["case_id"]), case["suite_name"], case["classname"], case["name"],
            current.get(int(case["case_id"])),
            [timings.get(int(case["case_id"]), {}).get(column) for column in column_ids],
            split, rules)
        for case in facts.get("cases", [])
    }


def slow_rows(facts: Mapping[str, Any], run_id: int, window: int,
              rules: Mapping[str, Any] = spec.SLOW_RULES) -> List[Dict[str, Any]]:
    """有耗时声明的用例，按耗时降序（同耗时按身份字典序）；``None`` 不出现。"""
    profiles = slow_profiles(facts, run_id, window, rules)
    rows = []
    for case in run_cases(facts, run_id):
        if case.get("time_ms") is None:
            continue
        rows.append({**case, "profile": profiles.get(int(case["case_id"]))})
    rows.sort(key=lambda row: (-int(row["time_ms"]), row["suite_name"],
                               row["classname"], row["name"]))
    return rows


def diff_rows(facts: Mapping[str, Any], run_before: int, run_after: int) -> List[Dict[str, Any]]:
    """两次 run 的原始状态对（任一侧缺行 → 该侧 ``None``）。"""
    before: Dict[int, str] = {}
    after: Dict[int, str] = {}
    for occ in facts.get("occurrences", []):
        if int(occ["run_id"]) == int(run_before):
            before[int(occ["case_id"])] = occ["status"]
        if int(occ["run_id"]) == int(run_after):
            after[int(occ["case_id"])] = occ["status"]
    rows = []
    for case in sorted(facts.get("cases", []),
                       key=lambda case: (case["suite_name"], case["classname"], case["name"])):
        case_id = int(case["case_id"])
        if case_id not in before and case_id not in after:
            continue
        rows.append({
            "case_id": case_id, "suite_name": case["suite_name"],
            "classname": case["classname"], "name": case["name"],
            "status_before": before.get(case_id), "status_after": after.get(case_id),
        })
    return rows


def summary(facts: Mapping[str, Any], run_id: int, window: int,
            fields: Sequence[str] = spec.SUMMARY_FIELDS) -> Dict[str, Optional[int]]:
    """summary 六字段：counts 由行集合直出；``flaky``/``broken``/``slow`` 由判定层填。"""
    counts = dict.fromkeys(spec.STATUSES, 0)
    for occ in facts.get("occurrences", []):
        if int(occ["run_id"]) == int(run_id):
            counts[occ["status"]] = counts.get(occ["status"], 0) + 1
    derived: Dict[str, Optional[int]] = {
        "total": sum(counts.values()),
        "fail": counts[spec.STATUS_FAIL],
        "skip": counts[spec.STATUS_SKIP],
    }
    profiles = case_profiles(facts, run_id, window)
    present = {int(occ["case_id"]) for occ in facts.get("occurrences", [])
               if int(occ["run_id"]) == int(run_id)}
    derived["flaky"] = sum(
        1 for case_id in present
        if case_id in profiles and profiles[case_id]["label"] == spec.LABEL_FLAKY)
    derived["broken"] = sum(
        1 for case_id in present
        if case_id in profiles and profiles[case_id]["label"] == spec.LABEL_BROKEN)
    derived["slow"] = sum(
        1 for occ in facts.get("occurrences", [])
        if int(occ["run_id"]) == int(run_id) and judge.is_slow(occ.get("time_ms")))
    return {name: derived.get(name) for name in fields}


# ============================================================ store / ingest
class Store:
    """内存台账（旧仓 ``db`` 的 upsert 幂等语义移植；不碰磁盘、不读时钟）。"""

    def __init__(self) -> None:
        self.runs: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self.suites: Dict[Tuple[int, str, str], Dict[str, Any]] = {}
        self.cases: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self.occurrences: Dict[Tuple[int, int], Dict[str, Any]] = {}
        self._next_run = 1
        self._next_suite = 1
        self._next_case = 1

    def upsert_run(self, identity: core.RunIdentity, started_at: str = "",
                   source_path: str = "", framework: str = "") -> int:
        row = self.runs.get(identity.key)
        if row is None:
            row = {"run_id": self._next_run, "branch": identity.branch,
                   "commit_sha": identity.commit_sha, "ci_run_id": identity.ci_run_id,
                   "started_at": started_at, "source_path": source_path,
                   "framework": framework, "ingested_at": ""}
            self.runs[identity.key] = row
            self._next_run += 1
        else:
            if started_at:
                row["started_at"] = started_at
            if source_path:
                row["source_path"] = source_path
            if framework:
                row["framework"] = framework
        return row["run_id"]

    def upsert_suite(self, run_id: int, name: str, source_path: str, tests: int,
                     failures: int, errors: int, skipped: int,
                     time_ms: Optional[int]) -> int:
        key = (int(run_id), name, source_path)
        row = self.suites.get(key)
        if row is None:
            row = {"suite_id": self._next_suite, "run_id": int(run_id), "name": name,
                   "source_path": source_path, "tests": tests, "failures": failures,
                   "errors": errors, "skipped": skipped, "time_ms": time_ms}
            self.suites[key] = row
            self._next_suite += 1
        else:
            row.update({"tests": tests, "failures": failures, "errors": errors,
                        "skipped": skipped, "time_ms": time_ms})
        return row["suite_id"]

    def upsert_case(self, identity: core.CaseIdentity) -> int:
        row = self.cases.get(identity.key)
        if row is None:
            row = {"case_id": self._next_case, "suite_name": identity.suite_name,
                   "classname": identity.classname, "name": identity.name}
            self.cases[identity.key] = row
            self._next_case += 1
        return row["case_id"]

    def upsert_occurrence(self, run_id: int, case_id: int, status: str,
                          time_ms: Optional[int], failure_type: str = "",
                          failure_message: str = "", stack_first_line: str = "") -> None:
        self.occurrences[(int(run_id), int(case_id))] = {
            "run_id": int(run_id), "case_id": int(case_id), "status": status,
            "time_ms": time_ms, "failure_type": failure_type,
            "failure_message": failure_message, "stack_first_line": stack_first_line,
        }

    def facts(self) -> Dict[str, Any]:
        return {
            "runs": sorted(self.runs.values(), key=lambda row: row["run_id"]),
            "suites": sorted(self.suites.values(), key=lambda row: row["suite_id"]),
            "cases": sorted(self.cases.values(), key=lambda row: row["case_id"]),
            "occurrences": sorted(self.occurrences.values(),
                                  key=lambda row: (row["run_id"], row["case_id"])),
        }


def aggregate_suites(suites: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """同一文件内**重名** suite 合并计（计数与耗时相加；不同文件同名各留一行）。"""
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for suite in suites:
        target = merged.get(suite["name"])
        if target is None:
            merged[suite["name"]] = {
                "name": suite["name"], "tests": suite["tests"], "failures": suite["failures"],
                "errors": suite["errors"], "skipped": suite["skipped"],
                "time_ms": suite.get("time_ms"), "cases": list(suite.get("cases", [])),
            }
            order.append(suite["name"])
            continue
        for name in spec.COUNT_FIELDS:
            target[name] += suite[name]
        if suite.get("time_ms") is not None:
            target["time_ms"] = (target["time_ms"] or 0) + suite["time_ms"]
        target["cases"].extend(suite.get("cases", []))
    return [merged[name] for name in order]


def ingest(files: Sequence[Mapping[str, Any]], store: Optional[Store] = None) -> Dict[str, Any]:
    """一批产物 → 解析 → 按 run 身份分组 → upsert → 摘要（不打印、不写盘）。"""
    store = store or Store()
    report: Dict[str, Any] = {
        "files": len(files), "runs": 0, "cases": 0, "occurrences": 0, "skipped": 0,
        "frameworks": [], "skipped_reasons": {}, "degraded_counts": {},
        "degraded_paths": {}, "missing_paths": [], "store": store,
    }
    parsed = []
    frameworks = set()
    for item in files:
        display = str(item.get("display_path") or item.get("file_name") or "")
        if item.get("xml") is not None:
            outcome = core.parse_xml_text(
                str(item["xml"]), file_name=item.get("file_name", ""), display_path=display)
        elif item.get("bytes") is not None:
            outcome = core.parse_xml_bytes(
                bytes(item["bytes"]), file_name=item.get("file_name", ""), display_path=display)
        else:
            raise ValueError("每个文件必须带 xml 或 bytes")
        if outcome["reason"]:
            report["skipped"] += 1
            report["skipped_reasons"].setdefault(outcome["reason"], []).append(display)
            continue
        parsed.append(outcome)
        frameworks.add(outcome["framework"])
        for reason, count in outcome["degraded"].items():
            report["degraded_counts"][reason] = report["degraded_counts"].get(reason, 0) + count
            bucket = report["degraded_paths"].setdefault(reason, [])
            if display not in bucket:
                bucket.append(display)
    report["frameworks"] = sorted(frameworks)

    groups: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str, str]] = []
    for outcome in parsed:
        key = (outcome["branch"], outcome["commit_sha"], outcome["ci_run_id"])
        group = groups.get(key)
        if group is None:
            group = {"key": key, "started_at": outcome["started_at"],
                     "source_path": outcome["display_path"], "frameworks": set(), "files": []}
            groups[key] = group
            order.append(key)
        group["frameworks"].add(outcome["framework"])
        group["files"].append(outcome)
    report["runs"] = len(groups)

    case_keys = set()
    occurrence_keys = set()
    for key in order:
        for outcome in groups[key]["files"]:
            for suite in outcome["suites"]:
                for case in suite["cases"]:
                    case_keys.add((case["suite_name"], case["classname"], case["name"]))
                    occurrence_keys.add(
                        key + (case["suite_name"], case["classname"], case["name"]))
    report["cases"] = len(case_keys)
    report["occurrences"] = len(occurrence_keys)

    for key in order:
        group = groups[key]
        run_id = store.upsert_run(
            core.RunIdentity(*key),
            started_at=group["started_at"],
            source_path=group["source_path"],
            framework=",".join(sorted(group["frameworks"])),
        )
        for outcome in group["files"]:
            for suite in aggregate_suites(outcome["suites"]):
                store.upsert_suite(
                    run_id, suite["name"], outcome["display_path"],
                    tests=suite["tests"], failures=suite["failures"],
                    errors=suite["errors"], skipped=suite["skipped"],
                    time_ms=suite.get("time_ms"),
                )
                for case in suite["cases"]:
                    case_id = store.upsert_case(core.CaseIdentity(
                        case["suite_name"], case["classname"], case["name"]))
                    store.upsert_occurrence(
                        run_id, case_id, case["status"], time_ms=case["time_ms"],
                        failure_type=case["failure_type"],
                        failure_message=case["failure_message"],
                        stack_first_line=case["stack_first_line"],
                    )
    return report


def summary_line(report: Mapping[str, Any]) -> str:
    """摘要首行（旧仓 ``summary_lines`` 的机读行）。"""
    return "ingest: files=%d runs=%d cases=%d occurrences=%d skipped=%d framework=%s" % (
        report["files"], report["runs"], report["cases"], report["occurrences"],
        report["skipped"], ",".join(report["frameworks"]),
    )