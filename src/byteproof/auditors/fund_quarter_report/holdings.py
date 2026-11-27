"""Q/Q 持仓五态判定（旧仓 ``funddiff/diff.py`` 的判定子集）。

原样保留的口径：

- **K3**：ratio/change_pct 是十进制字符串，一律 ``Decimal`` 运算；缺失 ``null`` ≠ 0；
- **五态**：新进 / 退出 / 加仓 / 减仓 / 不变；两侧都有但任一侧 ratio 缺失 -> 待确认；
- **双口径**：``computed`` 由两季 ratio 自算；``provider`` 采信本期变动标识与 change_pct；
  两者结论不一致 -> 冲突清单（不合并、不裁决）；
- **失败季**：任一季 ``failed`` -> 整只基金 ``insufficient_data``，与空仓 ``empty`` 严格区分；
- **确定性排序**：cur_ratio 降序（null 最后），再按 stock_code。

输入是**已归一**的持仓工件（旧仓 ``funddiff/holdings@1`` 的形状），不是 HTML；
页面解析属于工具面，器官不读文件。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .spec import (
    BASIS_COMPUTED,
    BASIS_INSUFFICIENT,
    BASIS_PROVIDER,
    FUND_INSUFFICIENT,
    FUND_STATUS_EMPTY,
    FUND_STATUS_FAILED,
    FUND_STATUS_OK,
    PENDING_LABEL,
    STATUS_DECREASE,
    STATUS_EXIT,
    STATUS_INCREASE,
    STATUS_LABELS,
    STATUS_NEW,
    STATUS_UNCHANGED,
)

PROVIDER_LABELS = {"增持": STATUS_INCREASE, "减持": STATUS_DECREASE}


class HoldingsError(ValueError):
    """持仓工件结构非法（输入不合法，退出码 2）。"""


def payload_rows(payload, side):
    if payload is None:
        return []
    if not isinstance(payload, dict):
        raise HoldingsError("holdings.%s 必须是对象" % side)
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise HoldingsError("holdings.%s.rows 必须是列表" % side)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise HoldingsError("holdings.%s.rows[%d] 必须是对象" % (side, index))
    return rows


def payload_status(payload):
    return (payload or {}).get("status") if isinstance(payload, dict) else None


def parse_ratio(value, where="ratio"):
    """字符串十进制 -> Decimal；缺失返回 None（null ≠ 0）；非法抛 HoldingsError。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise HoldingsError("非十进制数值 %r（%s）" % (value, where))


def format_delta(value):
    """差额统一两位小数字符串（与旧仓 fixtures 真值、显示精度一致）。"""
    return str(value.quantize(Decimal("0.01")))


def is_valid_code(value):
    return isinstance(value, str) and len(value) == 6 and value.isdigit()


def detect_anomalies(row):
    """逐行异常标记（与旧仓 fixtures 覆盖矩阵同名）。"""
    anomalies = []
    if row.get("ratio") is None:
        anomalies.append("ratio_null")
    if not is_valid_code(row.get("stock_code")):
        anomalies.append("invalid_stock_code")
    if row.get("change_type") is None:
        anomalies.append("change_type_missing")
    return anomalies


def provider_status(row):
    """上游变动标识 -> 五态标签；识别不了返回 None（交给 computed 口径）。"""
    change_type = row.get("change_type")
    if change_type is None:
        return None
    if change_type in PROVIDER_LABELS:
        return PROVIDER_LABELS[change_type]
    if change_type in (STATUS_NEW, STATUS_EXIT, STATUS_UNCHANGED):
        return change_type
    return None


def duplicate_codes(rows):
    """返回 ``{code: [出现下标...]}``，只保留出现 ≥2 次的代码。"""
    seen = {}
    for index, row in enumerate(rows):
        code = row.get("stock_code")
        seen.setdefault(code, []).append(index)
    return {code: indexes for code, indexes in seen.items() if len(indexes) > 1}


def _ratio_desc_key(entry):
    ratio = entry.get("cur_ratio")
    if ratio is None:
        return (1, Decimal(0))
    return (0, -Decimal(str(ratio)))


def sort_entries(entries):
    """确定性排序：cur_ratio 降序、null 最后，再按 stock_code。"""
    return sorted(entries, key=lambda entry: (_ratio_desc_key(entry), entry["stock_code"]))


def _computed_status(prev_ratio, cur_ratio, threshold):
    difference = Decimal(str(cur_ratio)) - Decimal(str(prev_ratio))
    if abs(difference) < threshold:
        return STATUS_UNCHANGED, difference
    if difference > 0:
        return STATUS_INCREASE, difference
    return STATUS_DECREASE, difference


def diff_fund(prev_payload, cur_payload, threshold, mode=BASIS_COMPUTED):
    """单只基金 Q/Q diff；返回 ``(fund_result, conflicts)``。

    ``threshold`` 是 Decimal。参数非法由调用方（spec）先拦下。
    """
    prev_rows = payload_rows(prev_payload, "prev")
    cur_rows = payload_rows(cur_payload, "cur")

    # 失败季：任一季 failed -> 整体 insufficient_data，与空仓（empty）严格区分。
    if payload_status(prev_payload) == FUND_STATUS_FAILED or payload_status(cur_payload) == FUND_STATUS_FAILED:
        return {
            "status": FUND_INSUFFICIENT,
            "entries": [],
            "summary": _empty_summary(),
        }, []

    prev_index = {row["stock_code"]: row for row in prev_rows}
    cur_index = {row["stock_code"]: row for row in cur_rows}

    entries = []
    conflicts = []
    for code in sorted(set(prev_index) | set(cur_index)):
        prev_row = prev_index.get(code)
        cur_row = cur_index.get(code)
        prev_ratio = prev_row.get("ratio") if prev_row else None
        cur_ratio = cur_row.get("ratio") if cur_row else None

        if prev_row is None and cur_row is not None:
            status, delta, basis = STATUS_NEW, None, BASIS_COMPUTED
            anomalies = detect_anomalies(cur_row)
        elif cur_row is None and prev_row is not None:
            status, delta, basis = STATUS_EXIT, None, BASIS_COMPUTED
            anomalies = detect_anomalies(prev_row)
        elif prev_ratio is None or cur_ratio is None:
            status, delta, basis = PENDING_LABEL, None, BASIS_INSUFFICIENT
            anomalies = detect_anomalies(prev_row or {}) + detect_anomalies(cur_row or {})
        else:
            status, difference = _computed_status(prev_ratio, cur_ratio, threshold)
            delta, basis = format_delta(difference), BASIS_COMPUTED
            anomalies = detect_anomalies(cur_row)
            if mode == BASIS_PROVIDER:
                label = provider_status(cur_row)
                if label is not None:
                    status = label
                    basis = BASIS_PROVIDER
                    delta = cur_row.get("change_pct")

        entry = {
            "stock_code": code,
            "stock_name": (cur_row or prev_row or {}).get("stock_name"),
            "industry": (cur_row or prev_row or {}).get("industry"),
            "prev_ratio": prev_ratio,
            "cur_ratio": cur_ratio,
            "delta": delta,
            "status": status,
            "basis": basis,
            "anomalies": anomalies,
            "source_quarters": {
                "prev": (prev_payload or {}).get("report_period"),
                "cur": (cur_payload or {}).get("report_period"),
            },
        }
        entries.append(entry)

        if (
            cur_row is not None
            and prev_row is not None
            and prev_ratio is not None
            and cur_ratio is not None
        ):
            label = provider_status(cur_row)
            if label is not None and label != status:
                computed_status, computed_difference = _computed_status(
                    prev_ratio, cur_ratio, threshold
                )
                conflicts.append(
                    {
                        "fund_code": (cur_payload or {}).get("fund_code"),
                        "stock_code": code,
                        "provider_status": label,
                        "provider_change_pct": cur_row.get("change_pct"),
                        "computed_status": computed_status,
                        "computed_delta": format_delta(computed_difference),
                        "prev_ratio": prev_ratio,
                        "cur_ratio": cur_ratio,
                    }
                )

    return {
        "status": FUND_STATUS_OK,
        "entries": sort_entries(entries),
        "summary": summarize(entries),
    }, conflicts


def summarize(entries):
    summary = {label: 0 for label in STATUS_LABELS}
    summary[PENDING_LABEL] = 0
    for entry in entries:
        summary[entry["status"]] = summary[entry["status"]] + 1
    return summary


def _empty_summary():
    summary = {label: 0 for label in STATUS_LABELS}
    summary[PENDING_LABEL] = 0
    return summary