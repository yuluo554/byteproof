"""器官参数表：默认值、类型强制、定点化（口径搬家，不是重新发明）。

口径来源是旧仓 ``anomaly_atlas/detect.py``（``DETECTOR_PARAMS`` / ``RUN_PARAMS`` /
``DEFAULT_SPEC`` / ``_coerce`` / ``resolve_spec`` / ``dump_spec``）与 ``canon.py``
（``quantize`` / ``fixed_to_str``）。搬过来的理由只有一条：**同一份参数表同时决定
「检测行为」与「账本证据里的数字」**，拆成两份写迟早对不上。

阈值表随包分发在 ``src/byteproof/data/timeseries-anomaly.thresholds.json``。
那个文件是**给读者与测试**看的台账；器官本身不读文件（契约：器官不读文件/环境/时钟），
运行期唯一来源是本模块的常量，``TestShippedTables`` 逐项比对两者 —— 改一处必须改两处，
和旧仓 ``TestDefaultsArePinned`` 是同一条纪律。

定点化的意义：账本要"同一输入两次运行字节一致"，原始 float 在证据里既不可读也不可对账。
``quantize`` 全部用整数运算收尾（只允许一次 float 乘法），``fixed_to_str`` 只从整数
拼字符串 —— 这是旧仓 K2/K3 的口径，照搬。
"""

from __future__ import annotations

import math

#: 证据里定点小数的位数（旧仓 ``detect._QUANT_DECIMALS``）。
QUANT_DECIMALS = 6

#: 参数表与检测算术的版本。改检测行为 -> 改它；只改呈现 -> 不动。
DETECTOR_VERSION = "1"
PARAMS_VERSION = "1"

#: MAD 到 sigma 的换算（正态一致）。
MAD_TO_SIGMA = 1.4826
#: 窗口内最少有效样本数：少于它就"没有尺度可言"，不判点。
MIN_VALID = 6
DEFAULT_MAX_GAP_MS = 1800000  # 30 分钟
DEFAULT_PERIOD_REJECT_WINDOW = 121
DEFAULT_PERIOD_REJECT_SIGMA = 2.5

#: 差分尺度相对系列自身稳健尺度的下限：低于它就是"没有短期噪声"（直线），
#: 标准化只会把最后一位二进制小数放大成"巨大跳变"，规则在此停手。
DECIMAL_RESOLUTION_FRACTION = 0.000001

#: 检测器参数面：(检测器, ((参数, 类型), ...))。类型决定强制与落盘形态。
DETECTOR_PARAMS = (
    ("rolling_mad_z", (("window", "int"), ("k", "decimal"), ("min_valid", "int"))),
    ("rolling_iqr", (("window", "int"), ("iqr_mult", "decimal"), ("min_valid", "int"))),
    (
        "stl_resid_z",
        (
            ("inner", "int"),
            ("outer", "int"),
            ("window", "int"),
            ("k", "decimal"),
            ("min_valid", "int"),
        ),
    ),
    (
        "rules",
        (
            ("static_threshold", "nullable-decimal"),
            ("pct_jump", "decimal"),
            ("missing_run", "int"),
            ("cusum_k", "decimal"),
            ("cusum_h", "decimal"),
        ),
    ),
)

#: 运行级参数（不属于任何单个检测器）。
RUN_PARAMS = (
    ("timezone_offset_min", "int"),
    ("max_gap_ms", "int"),
    ("period_points", "nullable-int"),
    ("period_reject_window", "int"),
    ("period_reject_sigma", "decimal"),
    ("duplicate_timestamp_max", "int"),
    ("non_monotonic_max", "int"),
    ("gap_factor", "int"),
    ("escalate_score_q", "nullable-int"),
)

#: 字符串参数（不做数值强制，只校验非空）。
STRING_PARAMS = (("default_series_id", "str"),)

DEFAULT_PARAMS = {
    "rolling_mad_z": {"window": 24, "k": 3.5, "min_valid": MIN_VALID},
    "rolling_iqr": {"window": 24, "iqr_mult": 3.0, "min_valid": MIN_VALID},
    "stl_resid_z": {"inner": 2, "outer": 1, "window": 24, "k": 3.5, "min_valid": MIN_VALID},
    "rules": {
        "static_threshold": None,
        "pct_jump": 0.35,
        "missing_run": 6,
        "cusum_k": 0.5,
        "cusum_h": 5.0,
    },
    "max_gap_ms": DEFAULT_MAX_GAP_MS,
    "timezone_offset_min": 0,
    "period_points": None,
    "period_reject_window": DEFAULT_PERIOD_REJECT_WINDOW,
    "period_reject_sigma": DEFAULT_PERIOD_REJECT_SIGMA,
    "duplicate_timestamp_max": 1,
    "non_monotonic_max": 0,
    "gap_factor": 3,
    "escalate_score_q": None,
    "default_series_id": "series",
}

#: `rules` 检测器的命中名（旧仓 ``RULE_NAMES``），一个名字一条规则、一条账本依据。
RULE_NAMES = ("static_threshold", "pct_jump", "missing_run", "zero_run", "cusum")


def _coerce(value, kind, label):
    """把一个参数值强制成声明类型；反例一律 ``ValueError``（-> 退出码 2）。"""
    if kind in ("decimal", "nullable-decimal"):
        if value is None:
            if kind == "nullable-decimal":
                return None
            raise ValueError("%s 必须是数字，不能是 null" % (label,))
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                raise ValueError("%s 必须是数字，得到 %r" % (label, value))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s 必须是数字，得到 %r" % (label, value))
        return float(value)
    if kind in ("int", "nullable-int"):
        if value is None:
            if kind == "nullable-int":
                return None
            raise ValueError("%s 必须是整数，不能是 null" % (label,))
        if isinstance(value, str):
            value = float(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s 必须是整数，得到 %r" % (label, value))
        if float(value) != int(value):
            raise ValueError("%s 必须是整数值，得到 %r" % (label, value))
        return int(value)
    if kind == "str":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s 必须是非空字符串，得到 %r" % (label, value))
        return value
    raise ValueError("未知参数类型 %r" % (kind,))


def _kind_of():
    table = {}
    for name, params in DETECTOR_PARAMS:
        for param, kind in params:
            table[(name, param)] = kind
    for param, kind in RUN_PARAMS:
        table[param] = kind
    for param, kind in STRING_PARAMS:
        table[param] = kind
    return table


PARAM_KINDS = _kind_of()


def resolve_params(params=None):
    """把调用方参数叠在默认值上，再逐项强制类型。

    未知键 -> ``ValueError``（不是静默忽略）。旧仓这里是 ``KeyError``，宿主
    ``cli.main`` 只把 ``ValueError`` 映射到退出码 2，所以在这里就换成 ``ValueError``：
    **同一个判定，落到同一个退出码**，不靠调用方认识两种异常。
    """
    resolved = {}
    for name, _params in DETECTOR_PARAMS:
        resolved[name] = dict(DEFAULT_PARAMS[name])
    for param, _kind in RUN_PARAMS:
        resolved[param] = DEFAULT_PARAMS[param]
    for param, _kind in STRING_PARAMS:
        resolved[param] = DEFAULT_PARAMS[param]

    if params is not None and not isinstance(params, dict):
        # 空列表/空串是**假值**，`if params:` 会把它们静默当成"没给参数"；
        # 工件里写了 `"params": []` 是明确的错误，不是"没写"。
        raise ValueError("params 必须是 JSON 对象")
    if params:
        unknown = sorted(set(params) - set(resolved))
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        for key, value in params.items():
            if isinstance(resolved[key], dict):
                if not isinstance(value, dict):
                    raise ValueError("params.%s 必须是对象" % (key,))
                extra = sorted(set(value) - set(resolved[key]))
                if extra:
                    raise ValueError(
                        "未知的 params.%s 参数：%s" % (key, ", ".join(extra))
                    )
                resolved[key].update(value)
            else:
                resolved[key] = value

    for name, params in DETECTOR_PARAMS:
        for param, kind in params:
            resolved[name][param] = _coerce(
                resolved[name][param], kind, "%s.%s" % (name, param)
            )
    for param, kind in RUN_PARAMS:
        resolved[param] = _coerce(resolved[param], kind, param)
    for param, kind in STRING_PARAMS:
        resolved[param] = _coerce(resolved[param], kind, param)
    return resolved


def _power_of_ten(decimals):
    """10^decimals：重复乘法（``**`` 在数值口径上是被禁的形态）。"""
    scale = 1
    for _step in range(int(decimals)):
        scale = scale * 10
    return scale


def quantize(value, decimals=QUANT_DECIMALS):
    """半到偶的定点量化到整数：一次 float 乘法之后全是整数运算。

    不用 ``format`` / ``round``：两者的边界行为不是跨运行时承诺的一部分，
    账本指纹不能建立在"某个平台的舍入"上。
    """
    scale = _power_of_ten(decimals)
    scaled = float(value) * scale
    floored = math.floor(scaled)
    frac = scaled - floored
    if frac > 0.5:
        return floored + 1
    if frac < 0.5:
        return floored
    return floored + 1 if floored % 2 else floored


def fixed_to_str(quantized, decimals=QUANT_DECIMALS):
    """只从定点整数拼出小数字符串（证据里人读的那一面）。"""
    quantized = int(quantized)
    decimals = int(decimals)
    sign = "-" if quantized < 0 else ""
    magnitude = abs(quantized)
    if decimals == 0:
        return sign + str(magnitude)
    scale = _power_of_ten(decimals)
    return "%s%d.%s" % (
        sign,
        magnitude // scale,
        str(magnitude % scale).zfill(decimals),
    )


def _dump_value(value, kind):
    if value is None:
        return None
    if kind in ("decimal", "nullable-decimal"):
        return fixed_to_str(quantize(value), QUANT_DECIMALS)
    if kind == "str":
        return str(value)
    return int(value)


def dump_params(resolved):
    """参数的落盘形态：整数，小数一律定点字符串（账本里不出现原样 float）。"""
    document = {}
    for name, params in DETECTOR_PARAMS:
        block = {}
        for param, kind in params:
            block[param] = _dump_value(resolved[name][param], kind)
        document[name] = block
    for param, kind in RUN_PARAMS:
        document[param] = _dump_value(resolved[param], kind)
    for param, kind in STRING_PARAMS:
        document[param] = _dump_value(resolved[param], kind)
    return document


def threshold_refs(dumped):
    """``检测器 -> 生效参数块``：episode 的证据里带上它当时用的那一份参数。

    ``rules`` 家族按 ``rules.<命中名>`` 各登记一份，这样一条 episode 的
    ``threshold_ref`` 直接说清"是哪条规则用哪组阈值判的"。
    """
    refs = {}
    for name, _params in DETECTOR_PARAMS:
        refs[name] = dumped[name]
        if name == "rules":
            for rule in RULE_NAMES:
                refs["rules." + rule] = dumped[name]
    return refs