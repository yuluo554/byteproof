"""器官 ``contract-drift``：跨格式契约差异 -> 缺陷账本。

迁自 target-map ② 行（旧仓 ``contractcompat``）。搬过来的是**判定**：
差异事实 -> R1–R7 规则命中 -> 三值 severity（相对 policy）-> 七档方向判定 ->
四态 blast_radius（相对 deploy-order）。格式解析与 IR 构造属工具面。

**没有搬**：Avro / Protobuf / JSON Schema 解析、IR 归一、regex/IR diff 的逐字段比较、
canonical JSON 与 golden 校验、报告渲染。逐条处置见 ``docs/contract-drift.md`` §6。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from .spec import (
    BLAST_RADIUS,
    EVIDENCE,
    FORMATS,
    KIND_RULES,
    NOT_APPLICABLE,
    NOT_GIVEN_NOTE,
    RULE_FOR_ORGAN,
    RULE_GATE,
    RULE_META,
    RULE_SUMMARY,
    SEVERITY_BY_DETAIL,
    allows,
    resolve_params,
)

SEVERITY_TO_VERDICT = {
    "breaking": ERROR,
    "runtime-dependent": WARN,
    "non-breaking": INFO,
}


class ContractError_(ValueError):
    """差异项结构非法（输入不合法，退出码 2）。"""


def normalize_differences(items, label="differences"):
    if not isinstance(items, list):
        raise ContractError_("%s 必须是列表" % label)
    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContractError_("%s[%d] 必须是对象" % (label, index))
        kind = item.get("kind")
        fmt = item.get("format")
        if not isinstance(kind, str):
            raise ContractError_("%s[%d].kind 必须是字符串" % (label, index))
        if fmt not in FORMATS:
            raise ContractError_("%s[%d].format 必须是 %s" % (label, index, "/".join(FORMATS)))
        direction = item.get("direction")
        if direction is not None and direction not in (
            "BACKWARD_OK", "FORWARD_OK", "BOTH_OK", "NONE_OK"
        ):
            raise ContractError_("%s[%d].direction 非法：%r" % (label, index, direction))
        normalized.append(
            {
                "kind": kind,
                "format": fmt,
                "stable_path": item.get("stable_path") or "",
                "direction": direction,
                "detail": item.get("detail"),
                "old": item.get("old"),
                "new": item.get("new"),
                "number": item.get("number"),
                "field": item.get("field"),
            }
        )
    return normalized


def rule_of(item):
    if item["kind"] == "field_added":
        return "R3" if item.get("direction") == "BACKWARD_OK" else None
    return KIND_RULES.get(item["kind"])


def severity_of(item, rule_id, policy):
    if allows(policy, item.get("direction")):
        return "non-breaking"
    detail = item.get("detail")
    override = (SEVERITY_BY_DETAIL.get(rule_id) or {}).get(detail)
    if override:
        return override
    return RULE_META[rule_id]["default"]


def format_evidence(rule_id, fmt, kind, detail):
    slot = EVIDENCE.get(rule_id) or {}
    if rule_id == "R4":
        if kind == "enum_widened":
            return {"proto": "enum_value_added", "avro": "symbol_added", "jsonschema": "enum_list_widened"}.get(fmt, slot.get(fmt))
        if kind == "enum_renumbered":
            return {"proto": "enum_value_renumbered", "avro": "symbol_renumbered"}.get(fmt, slot.get(fmt))
        if kind == "enum_changed":
            return {"avro": "symbol_set_changed", "jsonschema": "enum_list_changed"}.get(fmt, slot.get(fmt))
    if rule_id == "R2" and detail == "wire_compatible":
        return "wire_compatible_type_change"
    if rule_id == "R2" and detail == "union_widened":
        return "union_branch_added"
    return slot.get(fmt)


def repair_hint(rule_id, item):
    action = RULE_META[rule_id]["repair_action"]
    if action == "reserve":
        return "reserved %s;   // 旧号永久保留，新字段用新号" % (item.get("number") or "{number}")
    if action == "bump-and-version":
        return "保留旧字段/类型，新版本承载新语义"
    if action == "add-default":
        return "补 default（读侧兼容）"
    if action == "add-branch":
        return "保留旧分支，用 anyOf / 新成员兼容"
    return ""


def judge(settings, groups):
    if settings.policy == "none":
        return "compatible", ""
    all_groups = list(groups) + [list(group) for group in settings.history]
    for group in all_groups:
        for item in group:
            if not allows(settings.policy, item.get("direction")):
                return "breaking", item.get("kind") or ""
    return "compatible", ""


def _unique_paths(entries):
    counts = {}
    for entry in entries:
        counts[entry[1]] = counts.get(entry[1], 0) + 1
    seen = {}
    paths = []
    for rule_id, path in entries:
        if counts[path] > 1:
            index = seen.get(path, 0) + 1
            seen[path] = index
            paths.append("%s#%d" % (path, index))
        else:
            paths.append(path)
    return paths


def evaluate(subject, basis):
    settings = resolve_params(subject.get("params"))
    differences = normalize_differences(subject.get("differences"))
    history = [normalize_differences(list(group), "history[%d]" % index) for index, group in enumerate(settings.history)]
    groups = [differences] + history

    records = []

    def add(rule_id, verdict, message, path, evidence):
        records.append(
            Record(
                rule_id=rule_id,
                verdict=verdict,
                message=message,
                basis=basis.ref(rule_id),
                path=path,
                evidence=evidence,
            )
        )

    findings = []
    for group in groups:
        for item in group:
            rule_id = rule_of(item)
            if rule_id is None:
                continue
            severity = severity_of(item, rule_id, settings.policy)
            findings.append((rule_id, item, severity))

    rule_paths = [(RULE_FOR_ORGAN[rule_id], item.get("stable_path") or "<%s>" % item["kind"]) for rule_id, item, _severity in findings]
    paths = _unique_paths(rule_paths)
    for path, (rule_id, item, severity) in zip(paths, findings):
        add(
            RULE_FOR_ORGAN[rule_id],
            SEVERITY_TO_VERDICT[severity],
            "%s：%s（%s）" % (rule_id, item["kind"], severity),
            path,
            {
                "rule_id": rule_id,
                "kind": item["kind"],
                "detail": item["detail"],
                "format": item["format"],
                "stable_path": item["stable_path"],
                "direction": item["direction"],
                "severity": severity,
                "format_evidence": format_evidence(rule_id, item["format"], item["kind"], item["detail"]),
                "repair_action": RULE_META[rule_id]["repair_action"],
                "repair_hint": repair_hint(rule_id, item),
                "old": item["old"],
                "new": item["new"],
                "blast_radius": BLAST_RADIUS.get(settings.deploy_order),
            },
        )

    for fmt in sorted({item["format"] for group in groups for item in group}):
        for rule_id, reason in sorted((NOT_APPLICABLE.get(fmt) or {}).items()):
            add(
                RULE_FOR_ORGAN[rule_id],
                INFO,
                "N/A：%s" % reason,
                "<na:%s:%s>" % (fmt, rule_id),
                {"rule_id": rule_id, "format": fmt, "reason": reason, "severity": None, "blast_radius": None},
            )

    verdict, reason = judge(settings, groups)
    notes = []
    if settings.deploy_order is None:
        notes.append(NOT_GIVEN_NOTE)
    if verdict == "breaking":
        add(
            RULE_GATE,
            ERROR,
            "verdict=breaking：%s 方向不被 policy=%s 接受" % (reason, settings.policy),
            "<verdict>",
            {"policy": settings.policy, "verdict": verdict, "direction_reason": reason},
        )

    counts = {"breaking": 0, "runtime-dependent": 0, "non-breaking": 0}
    for _rule_id, _item, severity in findings:
        counts[severity] += 1
    add(
        RULE_SUMMARY,
        INFO,
        "verdict=%s · policy=%s · findings %d（breaking %d / runtime-dependent %d / non-breaking %d）"
        % (verdict, settings.policy, len(findings), counts["breaking"], counts["runtime-dependent"], counts["non-breaking"]),
        "<summary>",
        {
            "verdict": verdict,
            "policy": settings.policy,
            "deploy_order": settings.deploy_order,
            "blast_radius": BLAST_RADIUS.get(settings.deploy_order),
            "notes": notes,
            "counts": counts,
        },
    )
    return records