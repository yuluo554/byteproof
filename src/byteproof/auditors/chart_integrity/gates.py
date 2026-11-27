"""窄缝门禁 G2 / G3（旧仓 ``chartaudit/gates.py`` 的判定子集）。

- **G2 样本量**：组内 n < n_min 且偏斜/多峰 -> 阻断；分布未判定 -> 警示；
  合规替代（散点叠加 / box / scatter）-> 提示。
- **G3 误差棒来源**：sd / sem / ci / n 四类声明的列名别名匹配、来源存在性、
  SEM 与 sd/sqrt(n) 的数值一致性、n 与组内计数一致性；未声明但存在可疑列 -> 提示。

阈值来自 ``spec.Settings``（随包 thresholds.json 的唯一出处）；别名表来自
``params.aliases``（旧仓 ``references/aliases.json`` 的同一结构）。
"""

from __future__ import annotations

import math
from fractions import Fraction

from .spec import (
    RULE_G2_ALTERNATIVE,
    RULE_G2_UNDETERMINED,
    RULE_G2_VIOLATION,
    RULE_G3_SOURCE,
    RULE_G3_UNDECLARED,
)


def header_index(dataset):
    return {name: index for index, name in enumerate(dataset["header"])}


def selected_rows(dataset, spec):
    conditions = []
    for channel_name in ("x", "y"):
        filter_obj = spec["encoding"].get(channel_name, {}).get("filter")
        if filter_obj:
            conditions.append((filter_obj["field"], filter_obj["equals"]))
    index = header_index(dataset)
    rows = []
    for row_index, row in enumerate(dataset["rows"]):
        if all(row[index[field]] == expected for field, expected in conditions):
            rows.append((row_index, row))
    return rows


def groups_of(dataset, spec):
    index = header_index(dataset)
    x_field = spec["encoding"]["x"]["field"]
    series_field = spec["encoding"].get("series", {}).get("field")
    groups = []
    index_by_key = {}
    for row_index, row in selected_rows(dataset, spec):
        series = row[index[series_field]] if series_field else None
        category = row[index[x_field]]
        key = (series, category)
        if key not in index_by_key:
            index_by_key[key] = len(groups)
            groups.append({"series": series, "category": category, "row_indices": [], "rows": []})
        group = groups[index_by_key[key]]
        group["row_indices"].append(row_index)
        group["rows"].append(row)
    return groups


def numeric_cell(cell):
    if cell == "":
        return None
    try:
        return Fraction(cell)
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def column_numeric_values(group, column, index):
    values = []
    for row in group["rows"]:
        value = numeric_cell(row[index[column]])
        if value is None:
            return None
        values.append(value)
    return values


def normalize(name, aliases):
    return name if aliases["case_sensitive"] else name.casefold()


def matches_alias(name, aliases_list, aliases):
    normalized = normalize(name, aliases)
    for alias in aliases_list:
        candidate = normalize(alias, aliases)
        if normalized == candidate or normalized.endswith(candidate):
            return True
    return False


def matching_columns(header, aliases_list, aliases):
    return [column for column in header if matches_alias(column, aliases_list, aliases)]


def sem_consistent(pairs, n, tolerance):
    tolerance_value = float(Fraction(str(tolerance)))
    for sem_value, sd_value in pairs:
        expected = float(sd_value) / math.sqrt(n)
        if abs(float(sem_value) - expected) > tolerance_value:
            return False
    return True


# ── G2 ──────────────────────────────────────────────────────────────────
def skew_g1(values, settings):
    n = len(values)
    if n < settings.skew_min_n:
        return None
    mean = Fraction(sum(values), n)
    m2 = sum((Fraction(value) - mean) ** 2 for value in values) / n
    if m2 == 0:
        return None
    m3 = sum((Fraction(value) - mean) ** 3 for value in values) / n
    return float(m3 / (m2 ** Fraction(3, 2)))


def bin_counts(values, settings):
    bins = settings.multimodal_bins
    n = len(values)
    if n < settings.multimodal_min_n:
        return None
    lo, hi = min(values), max(values)
    if hi == lo:
        return None
    width = Fraction(hi - lo, bins)
    counts = [0] * bins
    for value in values:
        idx = int((Fraction(value) - lo) / width)
        if idx == bins:
            idx = bins - 1
        counts[idx] += 1
    return counts


def is_multimodal(counts, n, settings):
    if counts is None:
        return None
    divisor = settings.multimodal_min_count_divisor
    threshold = max(settings.multimodal_min_count_floor, (n + divisor - 1) // divisor)
    maxima = []
    for index, count in enumerate(counts):
        if count < threshold:
            continue
        left = counts[index - 1] if index > 0 else None
        right = counts[index + 1] if index < len(counts) - 1 else None
        if left is not None and count <= left:
            continue
        if right is not None and count <= right:
            continue
        maxima.append(index)
    for first in range(len(maxima)):
        for second in range(first + 1, len(maxima)):
            if maxima[second] - maxima[first] >= 2:
                return True
    return False


def group_stats(values, settings):
    g1 = skew_g1(values, settings)
    counts = bin_counts(values, settings)
    multimodal = is_multimodal(counts, len(values), settings) if counts else None
    skewed = None if g1 is None else abs(g1) > settings.skew_abs_threshold
    return {
        "n": len(values),
        "n_below_min": len(values) < settings.n_min,
        "skewed": skewed,
        "multimodal": multimodal,
        "g1": None if g1 is None else round(g1, 6),
        "bin_counts": counts,
    }


def g2_applicable(spec):
    aggregate = spec["encoding"]["y"].get("aggregate")
    if spec["mark"] == "box":
        return True
    return aggregate == "group_mean"


def g2_alternative(spec):
    return bool(spec.get("overlay_scatter")) or spec["mark"] in ("box", "scatter")


def audit_g2(dataset, spec, settings):
    groups = []
    findings = []
    if not g2_applicable(spec):
        return groups, findings
    index = header_index(dataset)
    y_field = spec["encoding"]["y"]["field"]
    alternative = g2_alternative(spec)
    for group in groups_of(dataset, spec):
        values = [numeric_cell(row[index[y_field]]) for row in group["rows"]]
        if any(value is None for value in values):
            continue
        stats = group_stats(values, settings)
        status = "pass"
        if stats["n_below_min"]:
            if stats["skewed"] is True or stats["multimodal"] is True:
                status = "alternative" if alternative else "violation"
            elif stats["skewed"] is None or stats["multimodal"] is None:
                status = "undetermined"
        entry = {
            "series": group["series"],
            "category": group["category"],
            "n": stats["n"],
            "n_below_min": stats["n_below_min"],
            "skewed": stats["skewed"],
            "multimodal": stats["multimodal"],
            "g1": stats["g1"],
            "bin_counts": stats["bin_counts"],
            "status": status,
        }
        groups.append(entry)
        if status == "violation":
            findings.append(
                {
                    "rule_id": RULE_G2_VIOLATION,
                    "message": "组内样本量不足且分布偏斜/多峰：均值柱会掩盖分布",
                    "path": "encoding.y.aggregate",
                    "evidence": {
                        "gate_id": "G2_SMALL_N_MEAN_BAR",
                        "series": group["series"],
                        "category": group["category"],
                        "status": status,
                        "n": stats["n"],
                        "n_min": settings.n_min,
                        "skewed": stats["skewed"],
                        "multimodal": stats["multimodal"],
                        "g1": stats["g1"],
                        "bin_counts": stats["bin_counts"],
                    },
                }
            )
        elif status == "undetermined":
            findings.append(
                {
                    "rule_id": RULE_G2_UNDETERMINED,
                    "message": "组内样本量不足且分布无法判定（不得冒充安全）",
                    "path": "encoding.y.aggregate",
                    "evidence": {
                        "gate_id": "G2_SMALL_N_MEAN_BAR",
                        "series": group["series"],
                        "category": group["category"],
                        "status": status,
                        "n": stats["n"],
                        "n_min": settings.n_min,
                        "skewed": stats["skewed"],
                        "multimodal": stats["multimodal"],
                        "g1": stats["g1"],
                        "bin_counts": stats["bin_counts"],
                    },
                }
            )
        elif status == "alternative":
            findings.append(
                {
                    "rule_id": RULE_G2_ALTERNATIVE,
                    "message": "小样本且分布偏斜/多峰，但已声明合规替代（散点叠加/箱线图）",
                    "path": "encoding.y.aggregate",
                    "evidence": {
                        "gate_id": "G2_SMALL_N_MEAN_BAR",
                        "series": group["series"],
                        "category": group["category"],
                        "status": status,
                        "n": stats["n"],
                        "n_min": settings.n_min,
                        "skewed": stats["skewed"],
                        "multimodal": stats["multimodal"],
                        "g1": stats["g1"],
                        "bin_counts": stats["bin_counts"],
                    },
                }
            )
    return groups, findings


# ── G3 ──────────────────────────────────────────────────────────────────
def title_declared_type(title, aliases):
    text = title if aliases["case_sensitive"] else title.casefold()
    for type_name in aliases["type_order"]:
        for alias in aliases["types"][type_name]["title"]:
            candidate = alias if aliases["case_sensitive"] else alias.casefold()
            if candidate in text:
                return type_name
    return None


def suspicious_columns(dataset, spec, aliases):
    header = dataset["header"]
    index = header_index(dataset)
    selected = selected_rows(dataset, spec)
    suspicious = []
    for type_name in ("sd", "sem"):
        aliases_list = aliases["types"][type_name]["columns"]
        for column in matching_columns(header, aliases_list, aliases):
            if column in suspicious:
                continue
            if any(numeric_cell(row[index[column]]) is not None for _, row in selected):
                suspicious.append(column)
    return suspicious


def _finding(rule_id, message, path, evidence):
    return {"rule_id": rule_id, "message": message, "path": path, "evidence": evidence}


def check_sd(group, declared_column, header, index, aliases):
    aliases_list = aliases["types"]["sd"]["columns"]
    if declared_column:
        if not matches_alias(declared_column, aliases_list, aliases):
            return None, {"declared_column": declared_column, "matched": []}
        candidates = [declared_column]
    else:
        candidates = matching_columns(header, aliases_list, aliases)
    matched = []
    for column in candidates:
        values = column_numeric_values(group, column, index)
        if values is not None:
            matched.append({"column": column, "values_count": len(values)})
    if matched:
        return {"column": matched[0]["column"], "matched": matched}, None
    return None, {"declared_column": declared_column, "matched": []}


def check_sem(group, declared_column, header, index, aliases, settings):
    sem_aliases = aliases["types"]["sem"]["columns"]
    sd_aliases = aliases["types"]["sd"]["columns"]
    sd_columns = matching_columns(header, sd_aliases, aliases)
    if declared_column:
        if not matches_alias(declared_column, sem_aliases, aliases):
            return None, {"declared_column": declared_column, "reason": "列名不在 SEM 别名表"}
        sem_values = column_numeric_values(group, declared_column, index)
        if sem_values is None:
            return None, {"declared_column": declared_column, "reason": "组内无有效 SEM 数值"}
        sd_column = sd_columns[0] if sd_columns else None
        sd_values = column_numeric_values(group, sd_column, index) if sd_column else None
        if sd_values is not None:
            pairs = list(zip(sem_values, sd_values))
            if not sem_consistent(pairs, len(group["rows"]), settings.sem_tolerance_abs):
                return None, {
                    "declared_column": declared_column,
                    "sd_column": sd_column,
                    "reason": "SEM 与 sd/sqrt(n) 不符",
                }
        return {"column": declared_column, "source": "sem_column"}, None
    sem_columns = matching_columns(header, sem_aliases, aliases)
    for column in sem_columns:
        values = column_numeric_values(group, column, index)
        if values is not None:
            return {"column": column, "source": "sem_column"}, None
    for column in sd_columns:
        values = column_numeric_values(group, column, index)
        if values is not None:
            return {"column": column, "source": "sd_recompute"}, None
    return None, {"declared_column": None, "reason": "无 SEM 列且无可重算的 SD 列"}


def check_ci(group, declared_column, header, index, aliases):
    ci_cfg = aliases["types"]["ci"]
    lower_columns = matching_columns(header, ci_cfg["lower"], aliases)
    upper_columns = matching_columns(header, ci_cfg["upper"], aliases)
    if declared_column:
        return None, {"declared_column": declared_column, "reason": "CI 声明只给出单个列，缺少上下限成对来源"}
    lower_column = lower_columns[0] if lower_columns else None
    upper_column = upper_columns[0] if upper_columns else None
    if not lower_column or not upper_column:
        return None, {
            "declared_column": declared_column,
            "lower_column": lower_column,
            "upper_column": upper_column,
            "reason": "缺少 CI 下限或上限列",
        }
    for column in (lower_column, upper_column):
        values = column_numeric_values(group, column, index)
        if values is None:
            return None, {
                "declared_column": declared_column,
                "lower_column": lower_column,
                "upper_column": upper_column,
                "reason": "组内 CI 列存在缺失或非数值",
            }
    return {"lower_column": lower_column, "upper_column": upper_column}, None


def check_n(group, declared_column, header, index, aliases):
    aliases_list = aliases["types"]["n"]["columns"]
    if declared_column:
        if not matches_alias(declared_column, aliases_list, aliases):
            return None, {"declared_column": declared_column, "reason": "列名不在样本数别名表"}
        candidates = [declared_column]
    else:
        candidates = matching_columns(header, aliases_list, aliases)
    if not candidates:
        return None, {"declared_column": declared_column, "reason": "未提供样本数列"}
    column = candidates[0]
    values = column_numeric_values(group, column, index)
    if values is None:
        return None, {"declared_column": declared_column, "reason": "组内样本数存在缺失或非数值"}
    actual = len(group["rows"])
    mismatched = sorted({str(value) for value in values if value != actual})
    if mismatched:
        return None, {"declared_column": column, "declared_values": mismatched, "actual_n": actual}
    return {"column": column, "declared_n": actual}, None


def audit_g3(dataset, spec, settings):
    header = dataset["header"]
    index = header_index(dataset)
    findings = []
    declarations = []
    error_bar = spec["encoding"].get("error_bar")
    selected = selected_rows(dataset, spec)
    title_declared = None
    suspicious = []
    if error_bar is None:
        title_declared = title_declared_type(spec["title"], settings.aliases)
        if title_declared is not None:
            findings.append(
                _finding(
                    RULE_G3_SOURCE,
                    "标题以自由文本声明 %s，但规格未声明 error_bar 且数据无来源" % title_declared.upper(),
                    "title",
                    {"gate_id": "G3_%s_WITHOUT_SOURCE" % title_declared.upper(), "title": spec["title"], "declared_type": title_declared},
                )
            )
        else:
            suspicious = suspicious_columns(dataset, spec, settings.aliases)
            if suspicious and selected:
                findings.append(
                    _finding(
                        RULE_G3_UNDECLARED,
                        "未声明误差棒，但数据中存在可疑 SD/SEM 列",
                        "encoding.error_bar.column",
                        {"gate_id": "G3_ERRORBAR_UNDECLARED", "columns": suspicious},
                    )
                )
        return declarations, findings, title_declared, suspicious

    type_name = error_bar["type"]
    declared_column = error_bar.get("column")
    checks = {"sd": check_sd, "sem": check_sem, "ci": check_ci, "n": check_n}
    checker = checks[type_name]
    for group in groups_of(dataset, spec):
        if type_name == "sem":
            source, problem = checker(group, declared_column, header, index, settings.aliases, settings)
        else:
            source, problem = checker(group, declared_column, header, index, settings.aliases)
        declaration = {
            "type": type_name,
            "series": group["series"],
            "category": group["category"],
            "n": len(group["rows"]),
            "declared_column": declared_column,
            "status": "ok" if source is not None else "error",
        }
        if source is not None:
            declaration["source"] = source
        else:
            declaration["problem"] = problem
        declarations.append(declaration)
        if source is None:
            if type_name == "sem" and isinstance(problem, dict) and problem.get("reason") == "SEM 与 sd/sqrt(n) 不符":
                gate_id = "G3_SEM_MISMATCH"
            elif type_name == "n" and isinstance(problem, dict) and "actual_n" in problem:
                gate_id = "G3_N_MISMATCH"
            elif type_name == "n":
                gate_id = "G3_N_SOURCE_MISSING"
            elif type_name == "sd":
                gate_id = "G3_SD_SOURCE_MISSING"
            elif type_name == "sem":
                gate_id = "G3_SEM_SOURCE_MISSING"
            else:
                gate_id = "G3_CI_INCOMPLETE"
            findings.append(
                _finding(
                    RULE_G3_SOURCE,
                    "误差棒来源不成立：%s" % gate_id,
                    "encoding.error_bar.column",
                    {
                        "gate_id": gate_id,
                        "type": type_name,
                        "series": group["series"],
                        "category": group["category"],
                        "declared_column": declared_column,
                        "problem": problem,
                    },
                )
            )
    return declarations, findings, title_declared, suspicious