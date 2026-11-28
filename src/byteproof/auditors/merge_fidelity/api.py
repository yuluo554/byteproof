"""编排层：``evaluate(subject, basis) -> Iterable[Record]``（账本化 + 模式分发）。

三种模式 = 旧仓三个扫描子命令的判定核（``fidelity scan`` / ``parity`` / ``ledger``）；
``report``（规范 JSON + digest + --verify 渲染）与 ``gate``（TOML 基线）不迁——渲染与
基线面属宿主报告层，判定态经账本行表达。git 子进程面（rev-list / cat-file /
merge-tree / patch-id / worktree apply --check）留输入层：subject 携带预抽取事实，
其中 patch-id 由输入层用 ``git patch-id --stable`` 计算，并以
``patch_ids: {sha256(diff 文本): pid}`` 映射绑定到文本（器官对**自己合成的**重引入
探针文本重算 sha256 查表，防"pid 与文本漂移"）。

退出码映射（旧仓 exitcodes：0 无事故 / 1 有事故 / 2 用法错误 / 3 环境不满足）：
fidelity 的 SMUGGLED/DROPPED 与 parity 的 MISSING/MODIFIED → error（旧 rc1 面）；
RESOLUTION / 跳过 / THEN_REDONE / NO_SUCCESSOR → info（显式记录，不阻断）；
REVERT_UNVERIFIED / 交叉核对不一致 / patch-id 探针未绑定 → warn（判不了，不静默）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Mapping, Tuple

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import canonical, diffparse, judge, spec
from .catalogue import Catalogue
from .spec import (
    DEFAULT_KINDS,
    DEFAULT_MODE,
    KIND_DROPPED,
    KIND_RESOLUTION,
    KIND_SMUGGLED,
    MODES,
)

#: 判定态 / 结论 → 规则 id（措辞来自随包 basis，器官不手写句子）。
_RULE = {
    "SMUGGLED": "mf-smuggled",
    "DROPPED": "mf-dropped",
    "RESOLUTION": "mf-resolution",
    "PRESENT": "mf-parity-present",
    "MISSING": "mf-parity-missing",
    "MODIFIED": "mf-parity-modified",
    "REVERTED_THEN_REDONE": "mf-reverted-then-redone",
    "REVERTED_NO_SUCCESSOR": "mf-reverted-no-successor",
    "REVERT_UNVERIFIED": "mf-revert-unverified",
    "skip-octopus": "mf-skip-octopus",
    "skip-custom-driver": "mf-skip-custom-driver",
    "CROSSCHECK_MISMATCH": "mf-warning-crosscheck",
    "CHERRY_COUNT_MISMATCH": "mf-warning-cherry-count",
    "PATCHID_UNBOUND": "mf-patchid-unbound",
}

_VERDICT = {
    "mf-smuggled": ERROR,
    "mf-dropped": ERROR,
    "mf-resolution": INFO,
    "mf-parity-present": INFO,
    "mf-parity-missing": ERROR,
    "mf-parity-modified": ERROR,
    "mf-reverted-then-redone": INFO,
    "mf-reverted-no-successor": INFO,
    "mf-revert-unverified": WARN,
    "mf-skip-octopus": INFO,
    "mf-skip-custom-driver": INFO,
    "mf-warning-crosscheck": WARN,
    "mf-warning-cherry-count": WARN,
    "mf-patchid-unbound": WARN,
}


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    mode = subject.get("mode", DEFAULT_MODE)
    if mode not in MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(MODES), mode))
    as_of = judge.validate_as_of(subject.get("as_of"))
    catalog = Catalogue(basis)

    records: List[Record] = []
    report: Dict[str, Any] = {"module": mode, "as_of": as_of}

    if mode == "fidelity":
        report, records = _fidelity(subject, catalog, basis, records)
    elif mode == "parity":
        report, records = _parity(subject, catalog, basis, records)
    else:
        report, records = _ledger(subject, catalog, basis, records)

    report["digest"] = canonical.digest_of(report)
    records.append(_summary_record(mode, report, records, basis))
    return records


def _ref(catalog: Catalogue, rule_id: str):
    return catalog.basis_ref(rule_id)


def _emit(catalog: Catalogue, records: List[Record], *, rule_id: str, path: str,
          message: str, evidence: Mapping[str, Any]) -> None:
    verdict = _VERDICT[rule_id]
    records.append(Record(
        rule_id=rule_id,
        verdict=verdict,
        message=message,
        basis=_ref(catalog, rule_id),
        path=path,
        evidence=dict(evidence),
    ))


# ---------------------------------------------------------------- fidelity
def _fidelity(subject: Mapping[str, Any], catalog: Catalogue, basis: Basis,
              records: List[Record]) -> Tuple[Dict[str, Any], List[Record]]:
    options = subject.get("options") or {}
    wanted = set(options.get("kinds") or DEFAULT_KINDS)
    if options.get("show_resolution"):
        wanted.add(KIND_RESOLUTION)
    patch_ids: Mapping[str, str] = subject.get("patch_ids") or {}

    def reintroduced(path: str, addition_text: str) -> bool:
        """重引入判定：器官合成探针文本 → sha256 查 subject.patch_ids → 与该路径
        的后续提交 patch-id 列表比对。查不到绑定 → 不能证重引入（保守），记 warn。"""
        text_sha = hashlib.sha256(addition_text.encode("utf-8")).hexdigest()
        pid = patch_ids.get(text_sha)
        if pid is None:
            _emit(catalog, records, rule_id=_RULE["PATCHID_UNBOUND"],
                  path=path,
                  message="重引入探针文本未绑定 patch-id（sha256=%s…），保守不排除" % text_sha[:12],
                  evidence={"kind": "PATCHID_UNBOUND", "sha256": text_sha, "path": path})
            return False
        for later_pid in (subject.get("later_patch_ids") or {}).get(path, []):
            if later_pid == pid:
                return True
        return False

    merges_report: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    for index, merge in enumerate(subject.get("merges") or []):
        oid = merge["merge_oid"]
        parents = list(merge.get("parents") or [])
        if len(parents) > 2:
            skipped.append({"merge_oid": oid, "reason": "octopus"})
            continue

        gitattributes = merge.get("gitattributes_text")
        hunks = diffparse.parse_unified_diff(merge.get("tree_diff_text") or "")
        payload_hunks = []
        payload_paths = set()
        payload_entry = diffparse.parse_remerge_log(merge.get("payload_text") or "")
        for entry in payload_entry:
            if entry.commit_oid == oid:
                payload_hunks = list(entry.hunks)
        payload_paths = set(h.path for h in payload_hunks)

        touched = set(h.path for h in hunks) | payload_paths
        excluded = judge.custom_driver_paths(gitattributes, touched)
        if excluded:
            skipped.append({"merge_oid": oid, "reason": "custom_driver", "paths": sorted(excluded)})

        fidelity = judge.blob_fidelity(
            merge.get("recorded_blobs"), merge.get("mechanical_blobs"), excluded=excluded)

        smuggled, dropped, resolution = judge.classify_hunks(
            hunks, excluded_paths=excluded, reintroduced=reintroduced)

        tree_paths = set(h.path for h in hunks)
        orphan = sorted(payload_paths - tree_paths - excluded)
        if orphan:
            warnings.append({"merge_oid": oid, "code": "CROSSCHECK_MISMATCH",
                             "payload_paths_not_in_tree_diff": orphan})

        listed = []
        for kind, group in ((KIND_SMUGGLED, smuggled), (KIND_DROPPED, dropped),
                            (KIND_RESOLUTION, resolution)):
            if kind in wanted:
                listed.extend(judge.render_hunk(h, kind) for h in group)

        merges_report.append({
            "merge_oid": oid,
            "parents": parents,
            "merge_base": merge.get("merge_base"),
            "recorded_tree": merge.get("recorded_tree"),
            "mechanical_tree": merge.get("mechanical_tree"),
            "mechanical_conflict": bool(merge.get("mechanical_conflict")),
            "counts": {"smuggled": len(smuggled), "dropped": len(dropped),
                       "resolution": len(resolution)},
            "hunks": listed,
            "blob_fidelity": fidelity["blob_fidelity"],
            "paths_total": fidelity["paths_total"],
            "paths_same": fidelity["paths_same"],
            "path_only_in_recorded": fidelity["path_only_in_recorded"],
            "path_only_in_mechanical": fidelity["path_only_in_mechanical"],
        })

        for hunk in listed:
            fid = canonical.finding_id(oid, hunk["path"], hunk["old_range"], hunk["new_range"], hunk["kind"])
            rule = _RULE[hunk["kind"]]
            _emit(catalog, records, rule_id=rule,
                  path="%s:%s:%s" % (oid[:12], hunk["path"], hunk["kind"]),
                  message="merge %s %s %s (%s..%s) finding=%s" % (
                      oid[:12], hunk["kind"], hunk["path"], hunk["old_range"], hunk["new_range"], fid),
                  evidence={"kind": hunk["kind"], "merge_oid": oid, "finding_id": fid,
                            "path": hunk["path"], "old_range": hunk["old_range"],
                            "new_range": hunk["new_range"]})

    for item in skipped:
        rule = _RULE["skip-custom-driver"] if item["reason"] == "custom_driver" else _RULE["skip-octopus"]
        _emit(catalog, records, rule_id=rule,
              path=str(item.get("merge_oid", "")),
              message="%s: %s%s" % (item["merge_oid"], item["reason"],
                                    (" " + ", ".join(item["paths"])) if item.get("paths") else ""),
              evidence={"kind": item["reason"], "merge_oid": item.get("merge_oid"),
                        "paths": item.get("paths", [])})
    for item in warnings:
        _emit(catalog, records, rule_id=_RULE.get(item["code"], _RULE["CROSSCHECK_MISMATCH"]),
              path=str(item.get("merge_oid", "")),
              message="%s: %s" % (item.get("merge_oid"), item["code"]),
              evidence={"kind": item["code"], **item})

    report = {
        "module": spec.MODES[0],
        "as_of": subject.get("as_of"),
        "kinds": sorted(wanted),
        "merges": merges_report,
        "skipped": skipped,
        "warnings": warnings,
        "summary": {
            "merges_total": len(merges_report) + len([s for s in skipped if s["reason"] == "octopus"]),
            "merges_scanned": len(merges_report),
            "smuggled": sum(m["counts"]["smuggled"] for m in merges_report),
            "dropped": sum(m["counts"]["dropped"] for m in merges_report),
            "resolution": sum(m["counts"]["resolution"] for m in merges_report),
            "skipped": len(skipped),
        },
    }
    return report, records


# ---------------------------------------------------------------- parity
def _parity(subject: Mapping[str, Any], catalog: Catalogue, basis: Basis,
            records: List[Record]) -> Tuple[Dict[str, Any], List[Record]]:
    options = subject.get("options") or {}
    apply_fallback = bool(options.get("apply_fallback", True))
    side_index = judge.build_side_index(subject.get("side") or [])
    rows = []
    for candidate in subject.get("candidates") or []:
        rows.append(judge.evaluate_candidate(candidate, side_index, apply_fallback=apply_fallback))
    counts = judge.parity_row_counts(rows)
    warnings = list(subject.get("warnings") or [])
    for row in rows:
        kind = "PARITY_%s" % row["status"]
        rule = _RULE[row["status"]]
        fid = canonical.finding_id(row["commit"], row["paths"][0] if row["paths"] else "-",
                                   "-", "-", kind)
        _emit(catalog, records, rule_id=rule,
              path="%s:%s" % (row["commit"][:12], row["status"]),
              message="parity %s %s (patchid=%s, basis=%s, note=%s) finding=%s" % (
                  row["commit"][:12], row["status"], row["u0_patchid"], row["basis"],
                  row["note"], fid),
              evidence={"kind": kind, "commit_oid": row["commit"], "finding_id": fid,
                        "status": row["status"], "basis": row["basis"], "note": row["note"],
                        "paths": row["paths"]})
    for item in warnings:
        _emit(catalog, records, rule_id=_RULE.get(item.get("code", "CHERRY_COUNT_MISMATCH"),
                                                  _RULE["CHERRY_COUNT_MISMATCH"]),
              path="crosscheck",
              message="crosscheck: %s" % item.get("code"),
              evidence={"kind": item.get("code"), **item})
    report = {
        "module": "parity",
        "as_of": subject.get("as_of"),
        "apply_fallback": apply_fallback,
        "commits": rows,
        "worktree": subject.get("worktree") or {"created": False, "reason": None},
        "warnings": warnings,
        **counts,
    }
    return report, records


# ---------------------------------------------------------------- ledger
def _ledger(subject: Mapping[str, Any], catalog: Catalogue, basis: Basis,
            records: List[Record]) -> Tuple[Dict[str, Any], List[Record]]:
    commit_facts = subject.get("commit_facts") or {}
    later_facts = subject.get("later_facts") or []
    find_object_available = bool(subject.get("find_object_available", False))
    entries = []
    for chunk in subject.get("revert_bodies") or []:
        entry = judge.ledger_entry(
            chunk.get("oid", ""), chunk.get("body", ""),
            commit_facts=commit_facts, later_facts=later_facts,
            find_object_available=find_object_available)
        if entry is not None:
            entries.append(entry)
    for entry in entries:
        rule = _RULE[entry["status"]]
        _emit(catalog, records, rule_id=rule,
              path=entry["revert_oid"][:12],
              message="revert %s → %s（verified=%s%s）" % (
                  entry["revert_oid"][:12], entry["status"], entry["verified"],
                  ("; unavailable=" + entry["unavailable"]) if entry.get("unavailable") else ""),
              evidence={"kind": entry["status"], "revert_oid": entry["revert_oid"],
                        "reverted_oid": entry["reverted_oid"], "verified": entry["verified"],
                        "unavailable": entry.get("unavailable"),
                        "successor": entry.get("successor")})
    report = {
        "module": "ledger",
        "as_of": subject.get("as_of"),
        "reverts": entries,
        "find_object_available": find_object_available,
    }
    return report, records


def _summary_record(mode: str, report: Mapping[str, Any], records: List[Record], basis: Basis) -> Record:
    errors = sum(1 for r in records if r.verdict == ERROR)
    warns = sum(1 for r in records if r.verdict == WARN)
    infos = sum(1 for r in records if r.verdict == INFO)
    summary = dict(report.get("summary") or {})
    if mode == "parity":
        summary = {k: report.get(k) for k in ("candidates", "present", "missing",
                                              "modified", "patch_parity")}
    if mode == "ledger":
        summary = {"reverts": len(report.get("reverts") or [])}
    return Record(
        rule_id="mf-summary",
        verdict=INFO,
        message="mode=%s：error=%d warn=%d info=%d" % (mode, errors, warns, infos),
        basis=basis.ref("mf-summary"),
        path="summary",
        evidence={"mode": mode, "error": errors, "warn": warns, "info": infos,
                  "summary": summary, "report_digest": report.get("digest")},
    )
