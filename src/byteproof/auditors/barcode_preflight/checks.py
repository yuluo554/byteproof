"""M3：五项印刷检查（静区 / 放大率 / DPI 混叠 / 条高 / 颜色）。

两条纪律照搬旧仓：

1. **不补默认值**：静区 / X / DPI 缺任一 -> 一条 ``input_incomplete`` error，
   其余几何判据一条都不出；
2. **未核降级只作用于 gen-spec 的 error**：engineering-heuristic（DPI、颜色）
   永远不降级；``strict_thresholds`` 只恢复 gen-spec 的 error。
"""

from __future__ import annotations

from decimal import Decimal

from . import spec
from .book import as_decimal, fixed


def _finding(rule_id, severity, observed, target, evidence, threshold_status, fix, module="M3", source_id=None):
    return {
        "rule_id": rule_id,
        "id": source_id or rule_id,
        "severity": severity,
        "observed": observed,
        "target": target,
        "evidence": evidence,
        "threshold_status": threshold_status,
        "fix": fix,
        "module": module,
    }


def engineering(rule_id, severity, observed, target, ref, quote, fix, threshold=None, source_id=None):
    return _finding(
        rule_id,
        severity,
        observed,
        target,
        {"kind": "engineering-heuristic", "ref": ref, "quote": quote, "threshold": threshold},
        spec.THRESHOLD_NOT_APPLICABLE,
        fix,
        source_id=source_id,
    )


def gen_spec(book, rule_id, base_severity, observed, target, entry, ref, strict, fix, threshold, source_id=None):
    status = book.status_of(entry)
    severity = base_severity
    if base_severity == "error" and status == spec.THRESHOLD_UNVERIFIED and not strict:
        severity = "warn"
    return _finding(
        rule_id,
        severity,
        observed,
        target,
        {"kind": "vector", "ref": ref, "quote": entry.get("source", ""), "threshold": threshold},
        status,
        fix,
        source_id=source_id,
    )


# ------------------------------------------------------------------ C1 静区
def quiet_zone(book, symbol, margins, x_dimension_mm, strict):
    findings = []
    factor = as_decimal(book.engineering("quiet_zone_marginal_factor")["value"], "quiet_zone_marginal_factor")
    for side in spec.QUIET_ZONE_SIDES:
        entry = book.quiet_zone_entry(symbol, side)
        margin = margins[side]
        ref = "quiet_zone.json#symbols.%s.%s" % (symbol, side)
        if margin == 0:
            if entry.get("required"):
                findings.append(
                    _finding(
                        spec.RULE_QUIET_ZONE_ABSENT,
                        "error",
                        "0.000 mm on the %s side (this symbol requires a quiet zone there)" % side,
                        "quiet_zone.%s" % side,
                        {
                            "kind": "vector",
                            "ref": ref,
                            "quote": "required=true for this side; a zero margin is a structure failure",
                        },
                        spec.THRESHOLD_NOT_APPLICABLE,
                        {
                            "kind": "add_quiet_zone",
                            "min_delta": "1",
                            "unit": "module",
                            "rationale": "zero margin is a structure failure, not a threshold one",
                        },
                        source_id="quiet_zone_absent",
                    )
                )
            continue
        modules_min = as_decimal(entry["modules_min"], "modules_min")
        needed = modules_min * x_dimension_mm
        qz_modules = margin / x_dimension_mm
        if qz_modules < modules_min:
            findings.append(
                gen_spec(
                    book,
                    spec.RULE_QUIET_ZONE,
                    "error",
                    "%s modules (%.3f mm / %.3f mm X)" % (fixed(qz_modules), margin, x_dimension_mm),
                    "quiet_zone.%s" % side,
                    entry,
                    ref,
                    strict,
                    {
                        "kind": "increase_quiet_zone",
                        "to": fixed(needed),
                        "unit": "mm",
                        "from": fixed(margin),
                        "rationale": "modules_min x x_dimension",
                    },
                    threshold="%s modules" % entry["modules_min"],
                    source_id="quiet_zone_insufficient",
                )
            )
        elif margin < needed * factor:
            findings.append(
                gen_spec(
                    book,
                    spec.RULE_QUIET_ZONE,
                    "warn",
                    "%s modules (%.3f mm); the minimum is %s modules"
                    % (fixed(qz_modules), margin, entry["modules_min"]),
                    "quiet_zone.%s" % side,
                    entry,
                    ref,
                    strict,
                    {
                        "kind": "increase_quiet_zone",
                        "to": fixed(needed * factor),
                        "unit": "mm",
                        "from": fixed(margin),
                        "rationale": "clear the marginal band",
                    },
                    threshold="%s modules" % entry["modules_min"],
                    source_id="quiet_zone_marginal",
                )
            )
    return findings


# ------------------------------------------------------------------ C2 放大率
def magnification(book, x_dimension_mm, strict):
    nominal = as_decimal(book.gen_spec_entry("nominal_x_mm")["value"], "nominal_x_mm")
    min_entry = book.gen_spec_entry("magnification_min_pct")
    max_entry = book.gen_spec_entry("magnification_max_pct")
    percent = x_dimension_mm / nominal * Decimal(100)
    if percent < as_decimal(min_entry["value"], "min"):
        return [
            gen_spec(
                book,
                spec.RULE_MAGNIFICATION,
                "warn",
                "%.3f%% (%.3f mm / %.3f mm)" % (percent, x_dimension_mm, nominal),
                "magnification",
                min_entry,
                "gen_spec.json#values.magnification_min_pct",
                strict,
                {
                    "kind": "increase_x_dimension",
                    "to": fixed(nominal * as_decimal(min_entry["value"], "min") / Decimal(100)),
                    "unit": "mm",
                    "from": fixed(x_dimension_mm),
                },
                threshold=">= %s%%" % min_entry["value"],
                source_id="magnification_below_range",
            )
        ]
    if percent > as_decimal(max_entry["value"], "max"):
        return [
            gen_spec(
                book,
                spec.RULE_MAGNIFICATION,
                "warn",
                "%.3f%% (%.3f mm / %.3f mm)" % (percent, x_dimension_mm, nominal),
                "magnification",
                max_entry,
                "gen_spec.json#values.magnification_max_pct",
                strict,
                {
                    "kind": "decrease_x_dimension",
                    "to": fixed(nominal * as_decimal(max_entry["value"], "max") / Decimal(100)),
                    "unit": "mm",
                    "from": fixed(x_dimension_mm),
                },
                threshold="<= %s%%" % max_entry["value"],
                source_id="magnification_above_range",
            )
        ]
    return []


# ------------------------------------------------------------------ C3 DPI
def raster(book, x_dimension_mm, target_dpi, strict):
    rule = book.engineering("dots_per_module")
    dpi = as_decimal(target_dpi, "target_dpi")
    dots = x_dimension_mm / book.mm_per_inch * dpi
    error_below = as_decimal(rule["error_below"], "dots_per_module.error_below")
    warn_below = as_decimal(rule["warn_below"], "dots_per_module.warn_below")
    if dots < error_below:
        severity = "error"
    elif dots < warn_below:
        severity = "warn"
    else:
        return []
    needed = (warn_below * book.mm_per_inch / x_dimension_mm).to_integral_value(rounding="ROUND_CEILING")
    return [
        engineering(
            spec.RULE_RASTER,
            severity,
            "%.3f dots/module (%.3f mm X at %s dpi)" % (dots, x_dimension_mm, dpi),
            "raster",
            "gen_spec.json#engineering_heuristics.dots_per_module",
            "engineering probe: dots_per_module = x_mm / mm_per_inch * dpi",
            {
                "kind": "increase_target_dpi",
                "to": str(int(needed)),
                "unit": "dpi",
                "from": str(dpi),
            },
            threshold=">= %s dots/module" % rule["warn_below"],
            source_id="raster_alias_high_risk" if severity == "error" else "raster_alias_risk",
        )
    ]


# ------------------------------------------------------------------ C4 条高
def bar_height(book, symbol, bar_height_mm, x_dimension_mm, strict):
    key = "bar_height_modules_min_" + symbol.replace("-", "_")
    if key not in book.gen_spec.get("values", {}):
        return []
    entry = book.gen_spec_entry(key)
    modules = bar_height_mm / x_dimension_mm
    modules_min = as_decimal(entry["value"], key)
    if modules >= modules_min:
        return []
    return [
        gen_spec(
            book,
            spec.RULE_BAR_HEIGHT,
            "error",
            "%.3f modules (%.3f mm / %.3f mm X)" % (modules, bar_height_mm, x_dimension_mm),
            "bar_height",
            entry,
            "gen_spec.json#values.%s" % key,
            strict,
            {
                "kind": "increase_bar_height",
                "to": fixed(modules_min * x_dimension_mm),
                "unit": "mm",
                "from": fixed(bar_height_mm),
            },
            threshold=">= %s modules" % entry["value"],
            source_id="bar_height_insufficient",
        )
    ]


# ------------------------------------------------------------------ C5 颜色
_GAMMA_OFFSET = Decimal("0.055")
_GAMMA_DIVISOR = Decimal("1.055")
_GAMMA_EXPONENT = Decimal("2.4")
_LINEAR_CUTOFF = Decimal("0.03928")
_LINEAR_DIVISOR = Decimal("12.92")
_WEIGHTS = (Decimal("0.2126"), Decimal("0.7152"), Decimal("0.0722"))
_CHANNEL_MAX = Decimal(255)
_CHANNEL_INDEX = {"red": 0, "green": 1, "blue": 2}


def parse_color(raw):
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text.startswith("#"):
        return None
    try:
        octets = bytes.fromhex(text[1:])
    except ValueError:
        return None
    if len(octets) != 3:
        return None
    return tuple(octets)


def _linearise(channel):
    value = Decimal(channel) / _CHANNEL_MAX
    if value <= _LINEAR_CUTOFF:
        return value / _LINEAR_DIVISOR
    return ((value + _GAMMA_OFFSET) / _GAMMA_DIVISOR) ** _GAMMA_EXPONENT


def relative_luminance(rgb):
    r, g, b = (_linearise(channel) for channel in rgb)
    return _WEIGHTS[0] * r + _WEIGHTS[1] * g + _WEIGHTS[2] * b


def contrast_ratio(first, second):
    light, dark = relative_luminance(first), relative_luminance(second)
    if light < dark:
        light, dark = dark, light
    return (light + Decimal("0.05")) / (dark + Decimal("0.05"))


def channel_reflectance(rgb, channel):
    return Decimal(rgb[_CHANNEL_INDEX[channel]]) / _CHANNEL_MAX


def color(book, bar_color, space_color, illumination):
    bar_rgb = parse_color(bar_color)
    space_rgb = parse_color(space_color)
    if bar_rgb is None or space_rgb is None:
        bad = "bar_color" if bar_rgb is None else "space_color"
        value = bar_color if bar_rgb is None else space_color
        return [
            engineering(
                spec.RULE_UNMODELLED,
                "info",
                "%s %r is not an 8-bit #RRGGBB value" % (bad, value),
                "color",
                "color_cases.json",
                "materials outside the modelled probes get an info, never pass or fail",
                None,
                source_id="surface_effect_unmodeled",
            )
        ]
    model = book.illumination(illumination)
    if not model.get("modelled"):
        return [
            engineering(
                spec.RULE_UNMODELLED,
                "info",
                "illumination %r is outside the modelled probes" % (illumination,),
                "color",
                "color_cases.json",
                "modelled=false: no pass and no fail",
                None,
                source_id="surface_effect_unmodeled",
            )
        ]

    findings = []
    rule = book.engineering("contrast_ratio")
    ratio = contrast_ratio(bar_rgb, space_rgb)
    error_below = as_decimal(rule["error_below"], "contrast_ratio.error_below")
    warn_below = as_decimal(rule["warn_below"], "contrast_ratio.warn_below")
    if ratio < error_below:
        severity = "error"
    elif ratio < warn_below:
        severity = "warn"
    else:
        severity = None
    if severity is not None:
        findings.append(
            engineering(
                spec.RULE_COLOR,
                severity,
                "%.3f:1 (%s on %s)" % (ratio, bar_color, space_color),
                "color.luminance",
                "gen_spec.json#engineering_heuristics.contrast_ratio",
                "contrast_ratio = (L_light + .05) / (L_dark + .05)",
                {
                    "kind": "increase_luminance_contrast",
                    "min_delta": fixed(warn_below - ratio),
                    "unit": "contrast-ratio",
                },
                threshold=">= %s:1" % rule["warn_below"],
                source_id="insufficient_contrast" if severity == "error" else "low_contrast",
            )
        )

    channel = model.get("channel")
    if channel in _CHANNEL_INDEX:
        delta_rule = book.engineering("wavelength_reflectance_delta_min")
        delta_min = as_decimal(delta_rule["value"], "wavelength_reflectance_delta_min")
        bar_reflectance = channel_reflectance(bar_rgb, channel)
        space_reflectance = channel_reflectance(space_rgb, channel)
        delta = abs(space_reflectance - bar_reflectance)
        if delta < delta_min:
            findings.append(
                engineering(
                    spec.RULE_COLOR,
                    "error",
                    "%.3f %s-channel reflectance difference (bar %.3f, space %.3f)"
                    % (delta, channel, bar_reflectance, space_reflectance),
                    "color.wavelength",
                    "gen_spec.json#engineering_heuristics.wavelength_reflectance_delta_min",
                    model.get("source", ""),
                    {
                        "kind": "choose_ink_with_channel_contrast",
                        "to": "< %s in the %s channel" % (fixed(delta_min), channel),
                        "unit": "relative-reflectance",
                    },
                    threshold=">= %s relative reflectance" % delta_rule["value"],
                    source_id="wavelength_reflectance_collapse",
                )
            )
    return findings