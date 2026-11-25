"""设置面 + 规则表 + 定点化（旧仓 ``docdedupe/config.py`` 的判定子集）。

旧仓把所有可调数字集中在一处，理由只有一条：**同一个阈值同时决定判定与报告**。
本器官保留这个纪律 —— 阈值表随包分发在
``src/byteproof/data/duplicate-docs.thresholds.json``，运行期常量必须与它逐项相等。

**没有搬**：``DB_SCHEMA_VERSION`` / ``EXTRACTOR_VERSION`` / ``FINGERPRINT_VERSION``
（缓存与抽取层）、``minhash_num_perm`` / ``lsh_bands`` / ``lsh_rows`` / ``simhash_max_hamming``
/``size_ratio_window``（候选召回与预筛：只减少候选，不改变判定）、
``template_*``（模板族判定本轮未迁）、``ignore_dirs`` / ``indexed_suffixes``（扫描层）。
逐条写在 ``docs/duplicate-docs.md`` 的处置表里。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from byteproof.core.ledger import ERROR, INFO, WARN

#: 账本证据的定点小数位（与内核其余器官同一口径）。
QUANT_DECIMALS = 6

#: 归一化管线的版本。改任一 stage -> 改它（旧仓 ``NORMALIZE_VERSION`` 的同一纪律）。
NORMALIZE_VERSION = "1"
PARAMS_VERSION = "1"


@dataclass(frozen=True)
class Settings:
    """一次判定的全部可调数字。默认值取自旧仓 ``config.Settings`` 的判定子集。"""

    shingle_size: int = 3
    min_text_chars: int = 80
    near_duplicate_threshold: float = 0.8
    header_footer_max_chars: int = 40
    header_footer_min_repeats: int = 2


DEFAULT_SETTINGS = Settings()

#: 参数面与类型（账本与阈值表共用这张表）。
SETTING_FIELDS = (
    ("shingle_size", "int"),
    ("min_text_chars", "int"),
    ("near_duplicate_threshold", "decimal"),
    ("header_footer_max_chars", "int"),
    ("header_footer_min_repeats", "int"),
)

# ── 规则 ─────────────────────────────────────────────────────────────────
RULE_EMPTY_TEXT = "dd-empty-text"
RULE_TOO_SHORT = "dd-too-short"
RULE_DUPLICATE_PATH = "dd-duplicate-path"
RULE_EXACT_DUPLICATE = "dd-exact-duplicate"
RULE_NEAR_DUPLICATE = "dd-near-duplicate"

RULE_IDS = (
    RULE_DUPLICATE_PATH,
    RULE_EMPTY_TEXT,
    RULE_EXACT_DUPLICATE,
    RULE_NEAR_DUPLICATE,
    RULE_TOO_SHORT,
)

#: 规则 -> 等级。``error`` 只在"两条工件抢同一个位置"时出现 —— 位置不唯一，
#: 任何指向它的结论都无法复核。重复**内容**不阻断发布，所以要 warn。
VERDICT_BY_RULE = {
    RULE_DUPLICATE_PATH: ERROR,
    RULE_EMPTY_TEXT: WARN,
    RULE_TOO_SHORT: INFO,
    RULE_EXACT_DUPLICATE: WARN,
    RULE_NEAR_DUPLICATE: WARN,
}


def verdict_for(rule_id):
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))


# ── 参数强制 ──────────────────────────────────────────────────────────────
def _coerce(value, kind, label):
    if kind == "decimal":
        if value is None:
            raise ValueError("%s 必须是数字，不能是 null" % (label,))
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                raise ValueError("%s 必须是数字，得到 %r" % (label, value))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s 必须是数字，得到 %r" % (label, value))
        return float(value)
    if value is None:
        raise ValueError("%s 必须是整数，不能是 null" % (label,))
    if isinstance(value, str):
        value = float(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("%s 必须是整数，得到 %r" % (label, value))
    if float(value) != int(value):
        raise ValueError("%s 必须是整数值，得到 %r" % (label, value))
    return int(value)


def resolve_params(params=None) -> Settings:
    """把调用方参数叠在默认值上，逐项强制类型；未知键 -> ``ValueError``（退出码 2）。"""
    resolved = {
        name: getattr(DEFAULT_SETTINGS, name) for name, _kind in SETTING_FIELDS
    }
    if params is not None and not isinstance(params, Mapping):
        raise ValueError("params 必须是 JSON 对象")
    if params:
        unknown = sorted(set(params) - set(resolved))
        if unknown:
            raise ValueError("未知的 params 键：%s" % ", ".join(unknown))
        resolved.update(params)
    for name, kind in SETTING_FIELDS:
        resolved[name] = _coerce(resolved[name], kind, name)
    if resolved["shingle_size"] < 1:
        raise ValueError("shingle_size 必须 >= 1")
    if resolved["min_text_chars"] < 1:
        raise ValueError("min_text_chars 必须 >= 1")
    return Settings(**resolved)


# ── 定点化 ────────────────────────────────────────────────────────────────
def _power_of_ten(decimals):
    scale = 1
    for _step in range(int(decimals)):
        scale = scale * 10
    return scale


def quantize(value, decimals=QUANT_DECIMALS):
    """半到偶定点量化（与 ``timeseries-anomaly`` 同一实现口径）。"""
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


def dump_params(settings: Settings) -> dict:
    """落盘形态：整数，小数一律定点字符串（账本里不出现原始 float）。"""
    document = {}
    for name, kind in SETTING_FIELDS:
        value = getattr(settings, name)
        document[name] = fixed_to_str(quantize(value), QUANT_DECIMALS) if kind == "decimal" else int(value)
    document["normalize_version"] = NORMALIZE_VERSION
    return document