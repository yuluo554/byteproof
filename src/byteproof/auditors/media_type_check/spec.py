"""设置面 + 规则台账 + 等级映射（旧仓 ``media-type-check/constants.py`` / ``rules/`` 的判定子集）。

旧仓把三值 ``class``（hard/diff/gray）、四档 ``severity``（blocker/major/minor/note）
与"没有条款就写 none-by-design"的纪律集中在 ``constants`` 与 ``rules/catalog.json``。
本器官保留同一套术语，只把它们翻译成 byteproof 的账本等级：

    blocker / major -> error      （阻断）
    minor           -> warn       （记录）
    note            -> info       （留痕）

这条映射是**产品级口径**，写在 ``data/media-type-check.thresholds.json`` 里，运行期常量必须与它逐项相等。

**规则 ID 原样保留**（``MC-H07`` 这类）：它们是旧仓 ``data/rfc-ledger.json`` 的索引键，
改一个名字就断掉了"这条账本能反查到 RFC 条款"这条链。
"""

from __future__ import annotations

import math

from byteproof.core.ledger import ERROR, INFO, WARN

QUANT_DECIMALS = 6
PARAMS_VERSION = "1"
RULES_VERSION = "1"

# ── 参数面 ────────────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    "max_depth": 32,  # 旧仓 --max-depth 默认
    "max_boundary_chars": 70,  # RFC 2046：boundary 不含前导 "--" 至多 70
    "max_header_line_octets": 998,  # RFC 5322 行宽上限（不含 CRLF）
    "max_encoded_word_chars": 75,  # RFC 2047 encoded-word 上限
    "max_encoded_header_line": 76,  # 含 encoded-word 的头行上限
    "max_qp_line_octets": 76,  # RFC 2045 6.7 QP 行宽
    "max_body_line_octets": 998,  # 7bit/8bit 正文行宽
}

PARAM_FIELDS = (
    ("max_depth", "int"),
    ("max_boundary_chars", "int"),
    ("max_header_line_octets", "int"),
    ("max_encoded_word_chars", "int"),
    ("max_encoded_header_line", "int"),
    ("max_qp_line_octets", "int"),
    ("max_body_line_octets", "int"),
)

# ── 规则表：rule_id -> (severity, rfc, 一句话判据) ─────────────────────────
# severity 四档沿用旧仓；rfc 是该规则引的条款（"没有条款"必须显式写 none-by-design）。
RULE_TABLE = {
    "MC-B01": ("blocker", "RFC 2046 §5.1.1", "multipart/* 缺少 boundary 参数，树无法建立"),
    "MC-B02": ("minor", "RFC 2046 §5.1.1", "boundary 长度 > max_boundary_chars"),
    "MC-B09": ("note", "none-by-design", "嵌套深度 > max_depth（RFC 未规定深度上限，策略项）"),
    "MC-H01": ("minor", "RFC 2047 §2", "encoded-word 长度 > max_encoded_word_chars"),
    "MC-H02": ("minor", "RFC 2047 §2", "含 encoded-word 的头行 > max_encoded_header_line"),
    "MC-H03": ("minor", "RFC 2047 §2", "encoded-word 内部出现空白"),
    "MC-H07": ("major", "RFC 5322 §2.1.1", "头行 > max_header_line_octets"),
    "MC-H08": ("note", "RFC 2047 §1", "头值含未编码的非 ASCII 字节（RFC 2047 是编码机制，不是禁令）"),
    "MC-T02": ("note", "none-by-design", "base64 填充非法"),
    "MC-T03": ("note", "none-by-design", "base64 字符数不是 4 的倍数"),
    "MC-T04": ("note", "RFC 2045 §6.8", "base64 出现字母表外字符（RFC 要求忽略它，故只留痕）"),
    "MC-T05": ("minor", "RFC 2045 §6.7", "QP 编码行 > max_qp_line_octets"),
    "MC-T06": ("minor", "RFC 2045 §6.7", "QP 行末 '=' 之后已无下一行（悬空转义）"),
    "MC-T07": ("major", "RFC 2045 §6.7", "QP 非法转义（'=' 后不是两位十六进制）"),
    "MC-T08": ("note", "none-by-design", "未知 CTE 取值（无法做交叉校验）"),
    "MC-T09": ("note", "none-by-design", "7bit/8bit 正文行 > max_body_line_octets"),
    "MC-T10": ("note", "none-by-design", "未声明 CTE（缺省 7bit）但正文含 8bit 字节"),
    "MC-A02": ("note", "none-by-design", "Content-Type 的 name 与 Content-Disposition 的 filename 不一致"),
    "MC-A03": ("note", "none-by-design", "声明了 disposition 却没有任何 filename / name 参数"),
    "MC-A07": ("note", "none-by-design", "disposition 是 inline 却没有 Content-ID"),
}

RULE_IDS = tuple(sorted(RULE_TABLE))

#: 等级映射（severity -> byteproof verdict）。**唯一**的翻译点。
VERDICT_BY_SEVERITY = {
    "blocker": ERROR,
    "major": ERROR,
    "minor": WARN,
    "note": INFO,
}

#: 规则 -> 账本等级（由 severity 派生，测试断言两者一致）。
VERDICT_BY_RULE = {rule_id: VERDICT_BY_SEVERITY[severity] for rule_id, (severity, _r, _d) in RULE_TABLE.items()}

SEVERITY_BY_RULE = {rule_id: severity for rule_id, (severity, _r, _d) in RULE_TABLE.items()}
RFC_BY_RULE = {rule_id: rfc for rule_id, (_s, rfc, _d) in RULE_TABLE.items()}
DETECTOR_BY_RULE = {rule_id: detail for rule_id, (_s, _r, detail) in RULE_TABLE.items()}


def verdict_for(rule_id):
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))


def severity_for(rule_id):
    try:
        return SEVERITY_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的严重度：%s" % (rule_id,))


def _coerce(value, kind, label):
    if value is None:
        raise ValueError("%s 必须是整数，不能是 null" % (label,))
    if isinstance(value, str):
        value = float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s 必须是整数，得到 %r" % (label, value))
    if float(value) != int(value):
        raise ValueError("%s 必须是整数值，得到 %r" % (label, value))
    if int(value) < 1:
        raise ValueError("%s 必须 >= 1，得到 %r" % (label, value))
    return int(value)


def resolve_params(params=None):
    """把调用方参数叠在默认值上并强制类型；未知键 -> ``ValueError``（退出码 2）。"""
    resolved = dict(DEFAULT_PARAMS)
    if params is not None and not isinstance(params, dict):
        raise ValueError("params 必须是 JSON 对象")
    if params:
        unknown = sorted(set(params) - set(resolved))
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        resolved.update(params)
    for name, kind in PARAM_FIELDS:
        resolved[name] = _coerce(resolved[name], kind, name)
    return resolved


def _power_of_ten(decimals):
    scale = 1
    for _step in range(int(decimals)):
        scale = scale * 10
    return scale


def quantize(value, decimals=QUANT_DECIMALS):
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
    quantized = int(quantized)
    decimals = int(decimals)
    sign = "-" if quantized < 0 else ""
    magnitude = abs(quantized)
    if decimals == 0:
        return sign + str(magnitude)
    scale = _power_of_ten(decimals)
    return "%s%d.%s" % (sign, magnitude // scale, str(magnitude % scale).zfill(decimals))


def dump_params(resolved):
    return {name: int(resolved[name]) for name, _kind in PARAM_FIELDS}