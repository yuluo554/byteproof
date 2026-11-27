"""逐值溯源（旧仓 ``chartaudit/provenance.py`` 的判定子集）。

原样保留的口径：

- 每个渲染数值有且仅有一条记录；记录由源单元格与**封闭白名单**变换链组成；
- 精确算术一律 ``Fraction``（禁 float 中转），舍入只在输出层做 ROUND_HALF_UP；
- ``rendered_value_id`` = SHA-256(字段序固定 JSON) 前 16 hex；
- ``row_index`` 0-based，``csv_line = row_index + 2``；
- G1 判定：缺记录 / 多余记录 / 结构非法 / 源哈希不符 / 行列不存在 /
  raw_cell 不符 / id 不复算 / match 与独立重算不一致。

**没有搬**：CSV 解析、normalized spec 的合法性校验（解析层）、HTML 渲染。
输入是已解析的 dataset + normalized spec + provenance 工件。
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction

from .spec import (
    AGGREGATE_TRANSFORMS,
    NUMERIC_COLUMN_TYPES,
    RULE_PROV_MALFORMED,
    RULE_PROV_MISMATCH,
    RULE_PROV_MISSING,
    RULE_PROV_UNEXPECTED,
    ROW_INDEX_OFFSET,
    TRANSFORM_WHITELIST,
)


class ProvenanceError(ValueError):
    """工件结构 / 变换非法（输入不合法，退出码 2）。"""


def round_half_up(value, decimals):
    if decimals is None:
        return value
    if not isinstance(decimals, int) or decimals < 0:
        raise ProvenanceError("decimals 必须是非负整数：%r" % (decimals,))
    factor = 10 ** decimals
    scaled = value * factor
    numerator = scaled.numerator
    denominator = scaled.denominator
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return Fraction(sign * quotient, factor)


def _exact_decimal_string(value):
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    numerator = abs(value.numerator)
    denominator = value.denominator
    twos = 0
    fives = 0
    reduced = denominator
    while reduced % 2 == 0:
        reduced //= 2
        twos += 1
    while reduced % 5 == 0:
        reduced //= 5
        fives += 1
    if reduced != 1:
        return "%s%d/%d" % (sign, numerator, denominator)
    places = max(twos, fives)
    scaled = numerator * (10 ** places) // denominator
    text = str(scaled)
    if places:
        text = text.rjust(places + 1, "0")
        text = text[:-places] + "." + text[-places:]
        text = text.rstrip("0").rstrip(".")
    return sign + text


def format_value(value, decimals):
    rounded = round_half_up(value, decimals)
    if decimals is None:
        return _exact_decimal_string(rounded)
    factor = 10 ** decimals
    scaled = rounded * factor
    if scaled.denominator != 1:
        raise ProvenanceError("内部错误：舍入结果不是有限小数")
    integer = scaled.numerator
    sign = "-" if integer < 0 else ""
    integer = abs(integer)
    if decimals == 0:
        return sign + str(integer)
    digits = str(integer).rjust(decimals + 1, "0")
    return sign + digits[:-decimals] + "." + digits[-decimals:]


def _median(values):
    ordered = sorted(values)
    count = len(ordered)
    if count % 2:
        return ordered[count // 2]
    return (ordered[count // 2 - 1] + ordered[count // 2]) / 2


def apply_transform(name, values, **params):
    if name not in TRANSFORM_WHITELIST:
        raise ProvenanceError("变换不在白名单：%r（允许 %s）" % (name, ", ".join(TRANSFORM_WHITELIST)))
    values = list(values)
    if name in ("identity", "filter"):
        return values
    if name == "group_sum":
        if not values:
            raise ProvenanceError("变换 group_sum 需要至少一个输入值")
        return [sum(values, Fraction(0))]
    if name == "group_mean":
        if not values:
            raise ProvenanceError("变换 group_mean 需要至少一个输入值")
        return [sum(values, Fraction(0)) / len(values)]
    if name == "group_median":
        if not values:
            raise ProvenanceError("变换 group_median 需要至少一个输入值")
        return [_median(values)]
    if name == "group_count":
        return [Fraction(len(values))]
    if name == "ratio":
        if len(values) != 1:
            raise ProvenanceError("ratio 需要恰好一个分子值")
        denominator = params.get("denominator")
        if denominator is None:
            raise ProvenanceError("ratio 缺少 denominator 参数")
        denominator_fraction = Fraction(str(denominator))
        if denominator_fraction == 0:
            raise ProvenanceError("ratio 的 denominator 不能为 0")
        return [values[0] / denominator_fraction]
    if name == "sort":
        return sorted(values)
    if name == "top_n":
        count = params.get("n")
        if not isinstance(count, int) or count <= 0:
            raise ProvenanceError("top_n 缺少正整数参数 n")
        return sorted(values, reverse=True)[:count]
    if name == "stack_offset":
        result = []
        running = Fraction(0)
        for value in values:
            running += value
            result.append(running)
        return result
    raise ProvenanceError("变换未实现：%r" % (name,))  # pragma: no cover


def canonical_id_payload(spec_id, mark_id, series, category, row_index, column, transform_chain):
    return json.dumps(
        [spec_id, mark_id, series, category, row_index, column, transform_chain],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def rendered_value_id(spec_id, mark_id, series, category, row_index, column, transform_chain):
    payload = canonical_id_payload(
        spec_id, mark_id, series, category, row_index, column, transform_chain
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _header_index(dataset):
    return {name: index for index, name in enumerate(dataset["header"])}


def _column_types(dataset):
    return {column["name"]: column["type"] for column in dataset["columns"]}


def _filters(spec):
    conditions = []
    for channel_name in ("x", "y"):
        filter_obj = spec["encoding"].get(channel_name, {}).get("filter")
        if filter_obj:
            conditions.append({"op": "filter", "field": filter_obj["field"], "equals": filter_obj["equals"]})
    return conditions


def _selected_rows(dataset, conditions):
    header_index = _header_index(dataset)
    selected = []
    for row_index, row in enumerate(dataset["rows"]):
        if all(row[header_index[condition["field"]]] == condition["equals"] for condition in conditions):
            selected.append((row_index, row))
    if not selected:
        raise ProvenanceError("过滤后没有数据行，无法产生渲染值")
    return selected


def _is_missing(cell, null_tokens):
    return cell == "" or cell in null_tokens


def _numeric_value(raw_cell, field, column_types, null_tokens):
    if _is_missing(raw_cell, null_tokens):
        raise ProvenanceError("渲染值来源单元格缺失：列 %r" % field)
    if column_types.get(field) not in NUMERIC_COLUMN_TYPES:
        raise ProvenanceError(
            "字段 %r 的列类型为 %r，不能作为渲染数值" % (field, column_types.get(field))
        )
    try:
        return Fraction(raw_cell)
    except (ValueError, ZeroDivisionError, TypeError):
        raise ProvenanceError("单元格无法按十进制字符串构造精确值：%r" % raw_cell)


def _aggregate_name(spec):
    mark = spec["mark"]
    aggregate = spec["encoding"]["y"].get("aggregate")
    if aggregate is None and mark == "pie":
        return "group_sum"
    if aggregate is None:
        return "identity"
    if aggregate in AGGREGATE_TRANSFORMS:
        return aggregate
    raise ProvenanceError(
        "y.aggregate=%r 不在变换白名单（或不能直接产生渲染值）" % (aggregate,)
    )


def _source(row_index, row, header_index, y_field, null_tokens, column_types):
    raw_cell = row[header_index[y_field]]
    value = _numeric_value(raw_cell, y_field, column_types, null_tokens)
    return {
        "row_index": row_index,
        "csv_line": row_index + ROW_INDEX_OFFSET,
        "column": y_field,
        "raw_cell": raw_cell,
        "parsed_value": _exact_decimal_string(value),
    }


def _record(spec, mark_id, series, category, sources, transform_chain, exact_value, decimals):
    sources = sorted(sources, key=lambda item: item["row_index"])
    recomputed = _recompute_exact(sources, transform_chain)
    rendered_label = format_value(exact_value, decimals)
    recomputed_label = format_value(recomputed, decimals)
    match = round_half_up(exact_value, decimals) == round_half_up(recomputed, decimals)
    representative = sources[0]
    return {
        "rendered_value_id": rendered_value_id(
            spec["spec_id"],
            mark_id,
            series,
            category,
            representative["row_index"],
            representative["column"],
            transform_chain,
        ),
        "mark_id": mark_id,
        "series": series,
        "category": category,
        "row_index": representative["row_index"],
        "csv_line": representative["csv_line"],
        "column": representative["column"],
        "raw_cell": representative["raw_cell"],
        "parsed_value": representative["parsed_value"],
        "transform_chain": transform_chain,
        "sources": sources,
        "exact_value": _exact_decimal_string(exact_value),
        "rendered_label": rendered_label,
        "recomputed_value": recomputed_label,
        "match": match,
    }


def _recompute_exact(sources, transform_chain):
    values = [Fraction(source["raw_cell"]) for source in sources]
    for transform in transform_chain:
        name = transform.get("op")
        params = {key: value for key, value in transform.items() if key != "op"}
        values = apply_transform(name, values, **params)
    if len(values) != 1:
        raise ProvenanceError("变换链必须收敛到恰好一个数值")
    return values[0]


def compile_records(dataset, spec):
    """按 spec 枚举全部渲染值，返回确定性记录列表（与旧仓同一算法）。"""
    y_channel = spec["encoding"]["y"]
    y_field = y_channel["field"]
    decimals = y_channel.get("decimals")
    if decimals is not None and (not isinstance(decimals, int) or decimals < 0):
        raise ProvenanceError("encoding.y.decimals 必须是非负整数")

    x_field = spec["encoding"]["x"]["field"]
    series_field = spec["encoding"].get("series", {}).get("field")
    header_index = _header_index(dataset)
    column_types = _column_types(dataset)
    null_tokens = spec.get("null_tokens", [])
    conditions = _filters(spec)
    selected = _selected_rows(dataset, conditions)
    aggregate = _aggregate_name(spec)
    mark = spec["mark"]

    if aggregate == "identity":
        transform_chain = list(conditions) + [{"op": "identity", "field": y_field}]
        records = []
        for row_index, row in selected:
            source = _source(row_index, row, header_index, y_field, null_tokens, column_types)
            records.append(
                _record(
                    spec,
                    mark,
                    row[header_index[series_field]] if series_field else None,
                    row[header_index[x_field]],
                    [source],
                    transform_chain,
                    Fraction(source["raw_cell"]),
                    decimals,
                )
            )
        return _sorted_records(records)

    groups = []
    group_by_key = {}
    for row_index, row in selected:
        series = row[header_index[series_field]] if series_field else None
        category = row[header_index[x_field]]
        key = (series, category)
        if key not in group_by_key:
            group_by_key[key] = len(groups)
            groups.append({"series": series, "category": category, "sources": [], "values": []})
        group = groups[group_by_key[key]]
        source = _source(row_index, row, header_index, y_field, null_tokens, column_types)
        group["sources"].append(source)
        group["values"].append(Fraction(source["raw_cell"]))

    denominator = None
    if aggregate == "ratio":
        denominator = sum((sum(group["values"], Fraction(0)) for group in groups), Fraction(0))
        if denominator == 0:
            raise ProvenanceError("ratio 的总分母为 0")

    records = []
    for group in groups:
        if aggregate == "ratio":
            transform_chain = list(conditions) + [
                {"op": "group_sum", "field": y_field},
                {"op": "ratio", "denominator": _exact_decimal_string(denominator)},
            ]
            exact_value = sum(group["values"], Fraction(0)) / denominator
        else:
            transform_chain = list(conditions) + [{"op": aggregate, "field": y_field}]
            exact_value = apply_transform(aggregate, group["values"])[0]
        records.append(
            _record(
                spec,
                mark,
                group["series"],
                group["category"],
                group["sources"],
                transform_chain,
                exact_value,
                decimals,
            )
        )
    return _sorted_records(records)


def _sorted_records(records):
    return sorted(
        records,
        key=lambda record: (
            record["row_index"],
            record["mark_id"],
            "" if record["series"] is None else record["series"],
            "" if record["category"] is None else record["category"],
            record["column"],
            canonical_id_payload(
                "",
                record["mark_id"],
                record["series"],
                record["category"],
                record["row_index"],
                record["column"],
                record["transform_chain"],
            ),
        ),
    )


def _issue(rule_id, path, message, evidence=None):
    return {"rule_id": rule_id, "path": path, "message": message, "evidence": evidence or {}}


def _record_index(index):
    return "provenance.rendered_values[%d]" % index


def _check_row_and_column(record, dataset, header_index):
    row_index = record.get("row_index")
    column = record.get("column")
    if not isinstance(row_index, int) or not (0 <= row_index < dataset["row_count"]):
        return "row_index=%r 超出数据行范围" % (row_index,)
    if column not in header_index:
        return "column=%r 不存在" % (column,)
    sources = record.get("sources")
    if not isinstance(sources, list) or not sources:
        return "sources 为空"
    for source in sources:
        source_row = source.get("row_index")
        source_column = source.get("column")
        if not isinstance(source_row, int) or not (0 <= source_row < dataset["row_count"]):
            return "source.row_index=%r 超出数据行范围" % (source_row,)
        if source_column not in header_index:
            return "source.column=%r 不存在" % (source_column,)
    return None


def _check_raw_cells(record, dataset, header_index):
    rows = dataset["rows"]
    row_index = record["row_index"]
    column = record["column"]
    if rows[row_index][header_index[column]] != record.get("raw_cell"):
        return "record.raw_cell 与源单元格不符"
    try:
        record_parsed = _exact_decimal_string(Fraction(record["raw_cell"]))
    except (ValueError, ZeroDivisionError, TypeError):
        return "record.raw_cell 不是数值"
    if record.get("parsed_value") != record_parsed:
        return "record.parsed_value 与源单元格不符"
    for position, source in enumerate(record["sources"]):
        cell = rows[source["row_index"]][header_index[source["column"]]]
        if cell != source.get("raw_cell"):
            return "sources[%d].raw_cell 与源单元格不符" % position
        try:
            parsed = _exact_decimal_string(Fraction(cell))
        except (ValueError, ZeroDivisionError, TypeError):
            return "sources[%d].raw_cell 不是数值" % position
        if source.get("parsed_value") != parsed:
            return "sources[%d].parsed_value 与源单元格不符" % position
    return None


def validate(provenance_obj, dataset, spec):
    """返回 ``(issues, checked_count)``；issues 带器官规则 id。"""
    issues = []
    records = provenance_obj.get("rendered_values")
    if not isinstance(records, list):
        records = []
        issues.append(_issue(RULE_PROV_MALFORMED, "provenance.rendered_values", "rendered_values 必须是数组"))
    if provenance_obj.get("spec_id") != spec["spec_id"]:
        issues.append(
            _issue(
                RULE_PROV_MALFORMED,
                "provenance.spec_id",
                "provenance spec_id=%r 与 normalized spec=%r 不符"
                % (provenance_obj.get("spec_id"), spec["spec_id"]),
            )
        )
    source = provenance_obj.get("source") or {}
    if source.get("sha256") != dataset["source"]["sha256"]:
        issues.append(
            _issue(
                RULE_PROV_MALFORMED,
                "provenance.source.sha256",
                "provenance 记录 %r 与源文件 %r 不符"
                % (source.get("sha256"), dataset["source"]["sha256"]),
            )
        )

    expected_records = compile_records(dataset, spec)
    expected_ids = {record["rendered_value_id"]: record for record in expected_records}

    seen = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            issues.append(_issue(RULE_PROV_MALFORMED, _record_index(index), "记录必须是对象"))
            continue
        record_id = record.get("rendered_value_id")
        if not isinstance(record_id, str) or len(record_id) != 16:
            issues.append(
                _issue(
                    RULE_PROV_MALFORMED,
                    _record_index(index),
                    "rendered_value_id 必须是 16 位 hex 字符串",
                )
            )
            continue
        seen.setdefault(record_id, []).append(index)

    for record_id in sorted(seen):
        indices = seen[record_id]
        if len(indices) > 1:
            issues.append(
                _issue(
                    RULE_PROV_MALFORMED,
                    _record_index(indices[1]),
                    "rendered_value_id %s 重复出现 %d 次" % (record_id, len(indices)),
                    {"rendered_value_id": record_id},
                )
            )

    for record_id in sorted(expected_ids):
        if record_id not in seen:
            expected = expected_ids[record_id]
            issues.append(
                _issue(
                    RULE_PROV_MISSING,
                    "provenance.rendered_values",
                    "缺少渲染值溯源：%s（%s/%s）"
                    % (record_id, expected["category"], expected["transform_chain"][-1]["op"]),
                    {"rendered_value_id": record_id, "category": expected["category"]},
                )
            )

    for record_id in sorted(seen):
        if record_id not in expected_ids:
            issues.append(
                _issue(
                    RULE_PROV_UNEXPECTED,
                    _record_index(seen[record_id][0]),
                    "存在不属于当前 spec 的渲染值：%s" % record_id,
                    {"rendered_value_id": record_id},
                )
            )

    header_index = _header_index(dataset)
    decimals = spec["encoding"]["y"].get("decimals")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        record_id = record.get("rendered_value_id")
        if record_id not in expected_ids:
            continue
        problem = _check_row_and_column(record, dataset, header_index)
        if problem:
            issues.append(_issue(RULE_PROV_MISMATCH, _record_index(index), problem, {"rendered_value_id": record_id}))
            continue
        problem = _check_raw_cells(record, dataset, header_index)
        if problem:
            issues.append(_issue(RULE_PROV_MISMATCH, _record_index(index), problem, {"rendered_value_id": record_id}))
            continue
        if record.get("csv_line") != record["row_index"] + ROW_INDEX_OFFSET:
            issues.append(
                _issue(
                    RULE_PROV_MALFORMED,
                    _record_index(index) + ".csv_line",
                    "csv_line 必须等于 row_index + %d" % ROW_INDEX_OFFSET,
                    {"rendered_value_id": record_id},
                )
            )
            continue
        expected_id = rendered_value_id(
            provenance_obj.get("spec_id"),
            record.get("mark_id"),
            record.get("series"),
            record.get("category"),
            record.get("row_index"),
            record.get("column"),
            record.get("transform_chain"),
        )
        if record_id != expected_id:
            issues.append(
                _issue(
                    RULE_PROV_MISMATCH,
                    _record_index(index),
                    "rendered_value_id 与字段重新计算不一致（期望 %s）" % expected_id,
                    {"rendered_value_id": record_id},
                )
            )
            continue
        try:
            recomputed = _recompute_exact(record["sources"], record["transform_chain"])
            recomputed_label = format_value(recomputed, decimals)
        except (ProvenanceError, KeyError, TypeError, ValueError) as exc:
            issues.append(
                _issue(
                    RULE_PROV_MISMATCH,
                    _record_index(index),
                    "重算失败：%s" % exc,
                    {"rendered_value_id": record_id},
                )
            )
            continue
        consistent = (
            record.get("match") is True
            and record.get("recomputed_value") == recomputed_label
            and record.get("rendered_label") == recomputed_label
        )
        if not consistent:
            issues.append(
                _issue(
                    RULE_PROV_MISMATCH,
                    _record_index(index),
                    "match/recomputed_value/rendered_label 与独立重算不一致（期望 %s）" % recomputed_label,
                    {"rendered_value_id": record_id},
                )
            )

    return issues, len(records)