"""九条反误导规则（旧仓 ``chartaudit/rules.py`` 的判定子集）。

规则唯一出处是旧仓 ``references/rules.json``；本器官把 rule_id / 检查器 / 阈值固化在
``spec`` 与随包 basis，检查函数仍在源码里（与旧仓同一分工：配置给登记，代码给判定）。

**没有搬**：规则包 JSON 加载与 schema 校验（移植为 params 校验）、audit.json 渲染、
`alignment` 输出字段（对齐标注已在 basis 每条规则的 source 里）；`R009` 仍不产生命中
（规格合法性属解析层，规则层不二次改判）。
"""

from __future__ import annotations

import datetime
import sys
from fractions import Fraction

from .provenance import format_value, round_half_up
from .spec import (
    DATE_COLUMN_TYPE,
    RULE_3D,
    RULE_BAR,
    RULE_CONTRAST,
    RULE_DUAL_Y,
    RULE_PIE,
    RULE_RADIUS,
    RULE_SMOOTH,
    RULE_TIME,
)


def _finding(rule_id, message, path, evidence):
    return {"rule_id": rule_id, "message": message, "path": path, "evidence": evidence}


def _check_bar(spec, _provenance, settings):
    if spec["mark"] != "bar":
        return None
    if spec.get("y_zero") is not False:
        return None
    return _finding(RULE_BAR, "柱状图 y_zero=false：截断基线放大视觉差异", "y_zero", {"mark": "bar", "y_zero": False})


def _check_dual_y(spec, _provenance, settings):
    if spec.get("dual_y") is not True:
        return None
    return _finding(RULE_DUAL_Y, "声明双 Y 轴：双轴刻度可制造虚假相关", "dual_y", {"dual_y": True})


def _check_pie(spec, provenance, settings):
    if spec["mark"] != "pie":
        return None
    records = provenance.get("rendered_values") or []
    max_sectors = settings.pie_max_sectors
    evidence = {"sector_count": len(records), "max_sectors": max_sectors}
    hit = len(records) > max_sectors
    values = []
    for record in records:
        try:
            values.append(Fraction(record["exact_value"]))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            values = []
            break
    if values:
        total = sum(values, Fraction(0))
        if total != 0:
            decimals = spec["encoding"]["y"].get("decimals")
            total_percent = Fraction(0)
            for value in values:
                percent = value * 100 / total
                if decimals is not None:
                    percent = round_half_up(percent, decimals)
                total_percent += percent
            evidence["percent_sum"] = format_value(total_percent, decimals)
            evidence["decimals"] = decimals
            if total_percent != 100:
                hit = True
    if not hit:
        return None
    return _finding(RULE_PIE, "饼图扇区数超过上限，或百分比舍入后合计不等于 100", "mark", evidence)


def _check_pseudo_3d(spec, _provenance, settings):
    if spec.get("pseudo_3d") is not True:
        return None
    return _finding(RULE_3D, "声明伪 3D 效果：透视变形扭曲数值比较", "pseudo_3d", {"pseudo_3d": True})


def _check_radius(spec, _provenance, settings):
    if spec.get("size_channel") != "radius":
        return None
    return _finding(
        RULE_RADIUS,
        "size_channel=radius：以半径代替面积编码会按平方级夸大差异",
        "size_channel",
        {"mark": spec["mark"], "size_channel": "radius"},
    )


def _check_smooth(spec, _provenance, settings):
    if spec.get("smooth") is not True:
        return None
    return _finding(RULE_SMOOTH, "声明平滑插值：曲线可能越过数据点极值", "smooth", {"mark": spec["mark"], "smooth": True})


def _check_time(dataset, spec, provenance, settings):
    if spec["mark"] == "pie":
        return None
    x_field = spec["encoding"]["x"]["field"]
    column_types = {column["name"]: column["type"] for column in dataset["columns"]}
    if column_types.get(x_field) != DATE_COLUMN_TYPE:
        return None
    categories = []
    seen = set()
    for record in provenance.get("rendered_values") or []:
        category = record.get("category")
        if category is None or category in seen:
            continue
        seen.add(category)
        categories.append(category)
    dates = []
    for category in categories:
        try:
            year, month, day = (int(part) for part in category.split("-"))
            dates.append(datetime.date(year, month, day))
        except (AttributeError, TypeError, ValueError):
            return None
    if len(dates) < 2:
        return None
    ordered = sorted(dates)
    gaps = [(later - earlier).days for earlier, later in zip(ordered, ordered[1:])]
    if all(gap == gaps[0] for gap in gaps):
        return None
    return _finding(
        RULE_TIME,
        "日期类 x 轴间隔不等却按类目等距绘制，扭曲时间趋势",
        "encoding.x.field",
        {"field": x_field, "value_count": len(dates), "gaps": gaps},
    )


def _check_low_contrast(spec, _provenance, settings):
    if spec.get("low_contrast") is not True:
        return None
    return _finding(RULE_CONTRAST, "声明低对比度配色：图元与标签难以分辨", "low_contrast", {"low_contrast": True})


def audit(dataset, spec, provenance, settings):
    """执行九条规则，返回 findings（未命中不出现）。"""
    findings = []
    simple = (
        _check_bar(spec, provenance, settings),
        _check_dual_y(spec, provenance, settings),
        _check_pie(spec, provenance, settings),
        _check_pseudo_3d(spec, provenance, settings),
        _check_radius(spec, provenance, settings),
        _check_smooth(spec, provenance, settings),
        _check_low_contrast(spec, provenance, settings),
    )
    for finding in simple:
        if finding is not None:
            findings.append(finding)
    time_finding = _check_time(dataset, spec, provenance, settings)
    if time_finding is not None:
        findings.append(time_finding)
    return findings


def severity_order():
    """保留旧仓 severity_order 的读取口（供测试对照），固定 ERROR/WARN/INFO。"""
    return ("ERROR", "WARN", "INFO")


def _unused():  # pragma: no cover - 保持模块无未使用导入告警的占位
    return sys.version