"""正文归一化五步（旧仓 ``docdedupe/normalize.py``，一步不改，一步不并）。

输出就是所有相似度计算的对象，所以**顺序是契约**：NFKC -> 去空白/不可见字符 ->
去页码行 -> 去跨页高频短行 -> 拉丁小写。行结构在第三步与第四步之间必须活着（页码与
页眉是"按行"才能认出来），最后由 :func:`normalize` 把行拼成一条流，这样 shingle 不会跨过
被删掉的行边界。

为什么整条管线要拉这么长：中文没有空格，保留词边界的归一化在这里无用；但页码与页眉只能
**作为行**被认出来。页眉是最难的一档 —— 抽取层给回来的是一条纯文本流，没有版面几何，
"短行在文档内重复"是唯一可用的证据（旧仓 ``data/README.md`` 4.3 的「跨页高频短行」）。

只折叠拉丁字母：``str.lower`` 会把希腊/西里尔也折下去，那会静默改写非拉丁内容，
而契约写的是"只折拉丁"。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Optional

from .spec import DEFAULT_SETTINGS, Settings

#: 五步的名字与顺序（测试按这个元组断言，重排不可能悄悄发生）。
STAGE_ORDER = (
    "nfkc",
    "strip_whitespace",
    "drop_page_numbers",
    "drop_running_heads",
    "lower_latin",
)

_INVISIBLE_RE = re.compile(
    "["
    "\u0000-\u0008"
    "\u000b\u000c"
    "\u000e-\u001f"
    "\u007f-\u009f"
    "\u00ad"
    "\u200b-\u200f"
    "\u202a-\u202e"
    "\u2060-\u2064"
    "\ufeff"
    "\ufff9-\ufffb"
    "]"
)

_WHITESPACE_RE = re.compile(r"\s+")

#: 页码行：在**去空白之后**按整行匹配。裸 1-3 位数字是常见的"第 7 页"页脚；
#: 四位数字刻意不接受裸形 —— "2026" 是年份的概率远高于页码。
_PAGE_NUMBER_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"^第\d{1,4}页$",
        r"^第\d{1,4}页[／/]共\d{1,4}页$",
        r"^共\d{1,4}页$",
        r"^-\d{1,3}-$",
        r"^\d{1,3}[／/]\d{1,3}$",
        r"^\d{1,3}$",
    )
)
_PAGE_NUMBER_CASELESS = re.compile(
    r"^(?:page|p\.?)\d{1,4}(?:[／/]\d{1,4})?$", re.IGNORECASE
)


def _build_latin_lower_table():
    """只把拉丁大写映射到小写（ASCII + Latin-1/Extended-A/B）。"""
    table = {}
    for code in range(0x41, 0x250):
        char = chr(code)
        if unicodedata.name(char, "").startswith("LATIN CAPITAL LETTER"):
            lower = char.lower()
            if lower != char:
                table[code] = lower
    return table


_LATIN_LOWER_TABLE = _build_latin_lower_table()


def _stage_nfkc(text):
    """第一步：兼容分解（全角变半角）。"""
    return unicodedata.normalize("NFKC", text)


def _stage_strip_whitespace(text):
    """第二步：去不可见字符与**每一行内**的空白；行结构保留给后两步。"""
    cleaned = _INVISIBLE_RE.sub("", text)
    return "\n".join(_WHITESPACE_RE.sub("", line) for line in cleaned.splitlines())


def _stage_drop_page_numbers(text):
    """第三步：删掉"整行只是一个页码"的行。"""
    kept = []
    for line in text.splitlines():
        if not line:
            continue
        if _PAGE_NUMBER_CASELESS.match(line):
            continue
        if any(pattern.match(line) for pattern in _PAGE_NUMBER_PATTERNS):
            continue
        kept.append(line)
    return "\n".join(kept)


def _stage_running_heads(text, settings):
    """第四步：删掉文档内重复的**短行**（页眉/页脚的代理证据）。

    长度上限是这道工序的关键：它把"重复出现的正文句子"（罕见但可能）留在原地。
    """
    lines = [line for line in text.splitlines() if line]
    counts = Counter(lines)
    kept = [
        line
        for line in lines
        if len(line) > settings.header_footer_max_chars
        or counts[line] < settings.header_footer_min_repeats
    ]
    return "\n".join(kept)


def _stage_lower_latin(text):
    """第五步：只折拉丁字母。"""
    return text.translate(_LATIN_LOWER_TABLE)


def normalize(text, settings: Optional[Settings] = None) -> str:
    """比较形态：无空白、无页码、无重复页眉、无拉丁大写。"""
    cfg = settings or DEFAULT_SETTINGS
    value = _stage_nfkc(text)
    value = _stage_strip_whitespace(value)
    value = _stage_drop_page_numbers(value)
    value = _stage_running_heads(value, cfg)
    value = _stage_lower_latin(value)
    # 行只在第 3-4 步当结构用；比较形态是一条流。
    return "".join(value.splitlines())


def normalized_length(text, settings: Optional[Settings] = None) -> int:
    return len(normalize(text, settings))