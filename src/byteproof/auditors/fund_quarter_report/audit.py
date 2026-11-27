"""器官 ``fund-quarter-report``：基金季报工件 -> 缺陷账本。

迁自 target-map ② 行（旧仓 ``funddiff``）。搬过来的是**判定**：

1. Q/Q 持仓五态 + provider/computed 双口径冲突 + 失败季/缺失占比/异常行；
2. 基金经理变更四类（区间反向复算，标签漂移即错误）；
3. 规模六字段（单位读表头、缺失 null ≠ 真实 0、无上季基准不得补 0）；
4. 合规禁词扫描（词表由 subject 提供）；
5. 披露窗口（工作日截止日推导 + 已披露/待披露/无数据三态）。

**没有搬**：抓取（东财/巨潮/eid）、HTML 解析、配置文件加载与 MANIFEST 冻结、
自选清单存储、报告渲染（HTML/Markdown）、基准、系统时钟。
理由：它们要么是工具面（读文件、写产物、起网络），要么是产品级门禁；
器官只回答「工件哪里不对、依据是哪条规则」。
"""

from __future__ import annotations

from decimal import Decimal

from byteproof.core.ledger import Record

from . import compliance, holdings, managers, scale, window
from .spec import (
    BASIS_COMPUTED,
    CLASS_UNPARSED,
    DISCLOSED,
    NO_DATA,
    PENDING,
    RULE_CHANGE_TYPE_MISSING,
    RULE_COMPLIANCE_TERM,
    RULE_DISCLOSURE_NO_DATA,
    RULE_DISCLOSURE_PENDING,
    RULE_DISCLOSURE_UNVERIFIED,
    RULE_DUPLICATE_HOLDING,
    RULE_FAILED_QUARTER,
    RULE_INVALID_CODE,
    RULE_MANAGER_LABEL_DRIFT,
    RULE_MANAGER_UNPARSED,
    RULE_PERIOD_MISMATCH,
    RULE_PROVIDER_CONFLICT,
    RULE_RATIO_INVALID,
    RULE_RATIO_MISSING,
    RULE_SCALE_BASELINE_FLOW,
    RULE_SCALE_FIELD_MISSING,
    RULE_SCALE_NUMBER,
    RULE_SCALE_RATE,
    RULE_SCALE_SOURCE,
    RULE_SCALE_UNIT_MISSING,
    STATUS_EXIT,
    resolve_params,
    verdict_for,
)
from .holdings import HoldingsError


def _add(records, basis, rule_id, message, path, evidence=None):
    records.append(
        Record(
            rule_id=rule_id,
            verdict=verdict_for(rule_id),
            message=message,
            basis=basis.ref(rule_id),
            path=path,
            evidence=evidence or {},
        )
    )


def _check_period(subject, basis, records):
    period = subject.get("period")
    if not isinstance(period, str):
        raise ValueError("subject.period 必须是 YYYYQn")
    window.parse_period(period)
    prev_period = subject.get("prev_period") or window.previous_period(period)
    window.parse_period(prev_period)
    return period, prev_period


def _scan_rows(side, rows, records, basis):
    """逐行异常（占比缺失/非法、代码非法）与重复代码；返回是否存在非法占比。"""
    invalid_ratio = False
    duplicates = holdings.duplicate_codes(rows)
    for code, indexes in sorted(duplicates.items(), key=lambda item: str(item[0])):
        _add(
            records,
            basis,
            RULE_DUPLICATE_HOLDING,
            "同一季持仓里证券代码 %r 出现 %d 次（按字典建索引会静默丢弃前面的行）" % (code, len(indexes)),
            "holdings.%s.duplicate[%s]" % (side, code),
            {"side": side, "stock_code": code, "row_indexes": indexes, "count": len(indexes)},
        )

    for index, row in enumerate(rows):
        code = row.get("stock_code")
        if not holdings.is_valid_code(code):
            _add(
                records,
                basis,
                RULE_INVALID_CODE,
                "证券代码 %r 不是 6 位数字（这一行无法与另一季稳定对齐）" % (code,),
                "holdings.%s.rows[%d]" % (side, index),
                {"side": side, "stock_code": code, "row_index": index},
            )
        if row.get("ratio") is None:
            _add(
                records,
                basis,
                RULE_RATIO_MISSING,
                "持仓占比缺失（null ≠ 0，该证券只能记为待确认）",
                "holdings.%s.rows[%d]" % (side, index),
                {"side": side, "stock_code": code, "row_index": index, "ratio": None},
            )
        else:
            try:
                holdings.parse_ratio(row.get("ratio"), "holdings.%s.rows[%d].ratio" % (side, index))
            except HoldingsError as exc:
                invalid_ratio = True
                _add(
                    records,
                    basis,
                    RULE_RATIO_INVALID,
                    "持仓占比不是十进制数值：%r" % (row.get("ratio"),),
                    "holdings.%s.rows[%d]" % (side, index),
                    {"side": side, "stock_code": code, "row_index": index, "ratio": str(row.get("ratio")), "detail": str(exc)},
                )
    return invalid_ratio


def _check_holdings(subject, basis, records, settings, period, prev_period):
    section = subject.get("holdings")
    if section is None:
        return
    if not isinstance(section, dict):
        raise HoldingsError("holdings 必须是对象")
    prev = section.get("prev")
    cur = section.get("cur")
    if (prev is None) != (cur is None):
        raise HoldingsError("holdings.prev 与 holdings.cur 必须同时提供（缺一季快照不得当空仓算）")

    sides = (("prev", prev, prev_period), ("cur", cur, period))
    computed_ok = prev is not None and cur is not None

    for side, payload, expected_period in sides:
        rows = holdings.payload_rows(payload, side)
        if _scan_rows(side, rows, records, basis):
            computed_ok = False
        if payload is None:
            continue
        reported = (payload or {}).get("report_period")
        if reported is not None and reported != expected_period:
            _add(
                records,
                basis,
                RULE_PERIOD_MISMATCH,
                "工件报告期 %r 与请求的 %r 不一致（跨季错配不得算差额）" % (reported, expected_period),
                "holdings.%s.report_period" % side,
                {"side": side, "reported": reported, "expected": expected_period},
            )
            computed_ok = False
        status = holdings.payload_status(payload)
        if status == holdings.FUND_STATUS_FAILED:
            _add(
                records,
                basis,
                RULE_FAILED_QUARTER,
                "该季持仓抓取失败（不是空仓；整只基金的变动结论不可给出）",
                "holdings.%s" % side,
                {"side": side, "status": status},
            )
            computed_ok = False
        if status == holdings.FUND_STATUS_EMPTY:
            # 结构性空仓（ETF 联接等）是数据，不是缺陷；不产出五态结论。
            computed_ok = computed_ok and side == "cur"

    if not computed_ok:
        return

    result, conflicts = holdings.diff_fund(
        prev, cur, Decimal(settings.threshold), settings.mode
    )
    for conflict in conflicts:
        _add(
            records,
            basis,
            RULE_PROVIDER_CONFLICT,
            "上游标识 %r（%s）与两季占比自算 %r（Δ%s）不一致"
            % (
                conflict["provider_status"],
                conflict["provider_change_pct"],
                conflict["computed_status"],
                conflict["computed_delta"],
            ),
            "holdings.cur.rows[%s]" % conflict["stock_code"],
            {
                "stock_code": conflict["stock_code"],
                "provider_status": conflict["provider_status"],
                "provider_change_pct": conflict["provider_change_pct"],
                "computed_status": conflict["computed_status"],
                "computed_delta": conflict["computed_delta"],
                "prev_ratio": conflict["prev_ratio"],
                "cur_ratio": conflict["cur_ratio"],
                "mode": settings.mode,
            },
        )

    if settings.mode == BASIS_COMPUTED:
        # 与旧仓 detect_anomaly 同一覆盖面：退出行看上一季，其余看本期。
        prev_rows = holdings.payload_rows(prev, "prev")
        cur_rows = holdings.payload_rows(cur, "cur")
        prev_index = {row.get("stock_code"): i for i, row in enumerate(prev_rows)}
        cur_index = {row.get("stock_code"): i for i, row in enumerate(cur_rows)}
        for entry in result["entries"]:
            if "change_type_missing" not in entry["anomalies"]:
                continue
            side = "prev" if entry["status"] == STATUS_EXIT else "cur"
            index = (prev_index if side == "prev" else cur_index).get(entry["stock_code"])
            if index is None:  # pragma: no cover - 每个 entry 都来自两侧 rows
                continue
            _add(
                records,
                basis,
                RULE_CHANGE_TYPE_MISSING,
                "该持仓行没有上游变动标识（provider 口径不可用，只按占比自算）",
                "holdings.%s.rows[%d]" % (side, index),
                {"stock_code": entry["stock_code"], "row_index": index, "side": side, "status": entry["status"]},
            )


def _manager_records(subject):
    section = subject.get("managers")
    if section is None:
        return None
    if isinstance(section, dict):
        records = section.get("records", [])
    else:
        records = section
    if not isinstance(records, list):
        raise ValueError("managers 必须是列表（或含 records 列表的对象）")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError("managers[%d] 必须是对象" % index)
    return records


def _check_managers(subject, basis, records, settings, period):
    items = _manager_records(subject)
    if items is None:
        return
    for index, record in enumerate(items):
        path = "managers[%d]" % index
        if managers.is_unparsed(record):
            evidence = managers.snapshot(record.get("raw_text")) if record.get("raw_text") else {}
            evidence.update({"index": index, "change_class": record.get("change_class"), "reason": record.get("unparsed_reason")})
            _add(
                records,
                basis,
                RULE_MANAGER_UNPARSED,
                "经理变更记录无法解析（unparsed 不是无变更）",
                path,
                evidence,
            )
            continue
        drift = managers.label_drift(record, period, settings.quarter_ends)
        if drift:
            _add(
                records,
                basis,
                RULE_MANAGER_LABEL_DRIFT,
                "经理变更分类不可复核：%s" % drift,
                path,
                {
                    "index": index,
                    "name": record.get("name"),
                    "change_date": record.get("change_date"),
                    "change_class": record.get("change_class"),
                },
            )


def _check_scale(subject, basis, records):
    scale_obj = subject.get("scale")
    if scale_obj is None:
        return
    if not isinstance(scale_obj, dict):
        raise ValueError("scale 必须是对象")

    missing = scale.missing_fields(scale_obj)
    if missing:
        _add(
            records,
            basis,
            RULE_SCALE_FIELD_MISSING,
            "规模台账缺少必需字段：%s" % ", ".join(missing),
            "scale",
            {"missing": list(missing)},
        )

    problem = scale.bad_baseline(scale_obj)
    if problem:
        _add(records, basis, RULE_SCALE_FIELD_MISSING, problem, "scale.baseline", {"baseline": scale_obj.get("baseline")})

    problem = scale.unit_problem(scale_obj)
    if problem:
        _add(records, basis, RULE_SCALE_UNIT_MISSING, problem, "scale.units_from_header", {"units_from_header": scale_obj.get("units_from_header")})

    problem = scale.number_problem(scale_obj)
    if problem:
        _add(records, basis, RULE_SCALE_NUMBER, problem, "scale", {"detail": problem})

    problem = scale.rate_problem(scale_obj)
    if problem:
        _add(records, basis, RULE_SCALE_RATE, problem, "scale.share_change_rate", {"share_change_rate": str(scale_obj.get("share_change_rate"))})

    key, problem = scale.baseline_flow_problem(scale_obj)
    if problem:
        _add(
            records,
            basis,
            RULE_SCALE_BASELINE_FLOW,
            problem,
            "scale.%s" % key,
            {"baseline": scale_obj.get("baseline"), "key": key, "value": scale_obj.get(key)},
        )

    problem = scale.source_problem(scale_obj)
    if problem:
        _add(records, basis, RULE_SCALE_SOURCE, problem, "scale.source", {"source": scale_obj.get("source")})


def _check_compliance(subject, basis, records):
    text = subject.get("report_text")
    terms = subject.get("compliance_terms") or []
    if text is None:
        return
    if not isinstance(text, str) or not isinstance(terms, list):
        raise ValueError("report_text 必须是字符串，compliance_terms 必须是列表")
    for hit in compliance.scan_text(text, terms):
        _add(
            records,
            basis,
            RULE_COMPLIANCE_TERM,
            "季报正文第 %d 行命中禁词 %r" % (hit["line"], hit["term"]),
            "report_text[%d]#%s" % (hit["line"], hit["term"]),
            hit,
        )


def _check_disclosure(subject, basis, records, settings, period):
    section = subject.get("disclosure")
    if section is None:
        return
    if not isinstance(section, dict):
        raise ValueError("disclosure 必须是对象")
    info = window.window_for_period(period, settings.quarter_ends, section)
    if info["unverified"]:
        _add(
            records,
            basis,
            RULE_DISCLOSURE_UNVERIFIED,
            "披露截止日不可计算：%s（禁止近似冒充）" % info["unverified_reason"],
            "disclosure.deadline",
            {
                "report_period": period,
                "unverified_reason": info["unverified_reason"],
                "calendar_years": info["calendar_years"],
            },
        )
    available = section.get("metadata_available", True)
    if not isinstance(available, bool):
        raise ValueError("disclosure.metadata_available 必须是布尔值")
    status = window.disclosure_status(
        available,
        section.get("reports") or [],
        subject.get("fund_code"),
        period,
        section.get("as_of"),
    )
    if status == NO_DATA:
        _add(
            records,
            basis,
            RULE_DISCLOSURE_NO_DATA,
            "官方披露元数据不可用：无数据（不得与待披露合并）",
            "disclosure.status",
            {"status": status, "period": period},
        )
    elif status == PENDING:
        _add(
            records,
            basis,
            RULE_DISCLOSURE_PENDING,
            "本期报告尚未披露（对待披露状态只留痕，不冒充已披露）",
            "disclosure.status",
            {"status": status, "period": period, "as_of": section.get("as_of")},
        )
    elif status != DISCLOSED:  # pragma: no cover - 三态封闭
        raise AssertionError("unreachable")


def evaluate(subject, basis):
    """器官入口：``evaluate(subject, basis) -> Iterable[Record]``。"""
    settings = resolve_params(subject.get("params"))
    records = []
    period, prev_period = _check_period(subject, basis, records)
    _check_holdings(subject, basis, records, settings, period, prev_period)
    _check_managers(subject, basis, records, settings, period)
    _check_scale(subject, basis, records)
    _check_compliance(subject, basis, records)
    _check_disclosure(subject, basis, records, settings, period)
    return records