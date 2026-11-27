"""阈值册（旧仓 ``ThresholdBook``）：阈值来自 ``subject.thresholds``，不读文件。

三态纪律照搬（``data/README.md`` §8.2）：

* ``gen-spec`` 项必须带 ``source`` / ``status`` / ``verified_at``；未核项的 error
  默认降级为 warn（``strict_thresholds`` 恢复）；
* ``engineering-heuristic`` 项**没有** ``status``，不参与降级；
* 缺字段即 ``ValueError``（退出码 2）——不留无主阈值。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from . import spec


def as_decimal(raw, field):
    if isinstance(raw, bool) or raw is None:
        raise ValueError("%s 必须是数字，收到 %r" % (field, raw))
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise ValueError("%s 不是数字：%r" % (field, raw)) from None
    if not value.is_finite():
        raise ValueError("%s 必须是有限数：%r" % (field, raw))
    return value


def fixed(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.001"), rounding="ROUND_HALF_UP"))


class Book:
    """只读阈值快照。``thresholds`` = ``{gen_spec, quiet_zone, color_cases}``。"""

    def __init__(self, thresholds) -> None:
        if not isinstance(thresholds, dict):
            raise ValueError("subject.thresholds 必须是对象（gen_spec/quiet_zone/color_cases）")
        self.gen_spec = thresholds.get("gen_spec")
        self.quiet_zone = thresholds.get("quiet_zone")
        self.color_cases = thresholds.get("color_cases")
        for name, value in (
            ("gen_spec", self.gen_spec),
            ("quiet_zone", self.quiet_zone),
            ("color_cases", self.color_cases),
        ):
            if not isinstance(value, dict):
                raise ValueError("thresholds.%s 必须是对象" % name)
        self._validate_gen_spec()
        self.mm_per_inch = as_decimal(self.gen_spec.get("mm_per_inch", "25.4"), "mm_per_inch")

    def _validate_gen_spec(self) -> None:
        values = self.gen_spec.get("values")
        if not isinstance(values, dict):
            raise ValueError("gen_spec.values 必须是对象")
        for key, entry in values.items():
            if not isinstance(entry, dict) or "value" not in entry:
                raise ValueError("gen_spec.values.%s 缺少 value" % key)
            if entry.get("basis", spec.BASIS_GEN_SPEC) == spec.BASIS_GEN_SPEC:
                for field in ("source", "status", "verified_at"):
                    if field not in entry:
                        raise ValueError("gen_spec.values.%s 缺少 %s（无出处阈值不得装载）" % (key, field))
            as_decimal(entry["value"], "gen_spec.values.%s.value" % key)
        heuristics = self.gen_spec.get("engineering_heuristics")
        if not isinstance(heuristics, dict):
            raise ValueError("gen_spec.engineering_heuristics 必须是对象")

    def gen_spec_entry(self, key):
        try:
            return self.gen_spec["values"][key]
        except KeyError:
            raise ValueError(
                "gen_spec.values 缺 %s（已知：%s）"
                % (key, ", ".join(sorted(self.gen_spec.get("values", {}))))
            ) from None

    def engineering(self, key):
        try:
            return self.gen_spec["engineering_heuristics"][key]
        except KeyError:
            raise ValueError("gen_spec.engineering_heuristics 缺 %s" % key) from None

    def quiet_zone_entry(self, symbol, side):
        symbols = self.quiet_zone.get("symbols", {})
        if symbol not in symbols:
            raise ValueError("quiet_zone.symbols 缺 %r" % (symbol,))
        sides = symbols[symbol]
        if side not in sides:
            raise ValueError("quiet_zone.symbols.%s 缺 %r" % (symbol, side))
        entry = sides[side]
        if not isinstance(entry, dict) or "modules_min" not in entry:
            raise ValueError("quiet_zone.symbols.%s.%s 缺少 modules_min" % (symbol, side))
        return entry

    def illumination(self, name):
        illuminations = self.color_cases.get("illuminations", {})
        return illuminations.get(name) or {"modelled": False, "note": "unmodelled"}

    @staticmethod
    def status_of(entry) -> str:
        return str(entry.get("status") or spec.THRESHOLD_NOT_APPLICABLE)