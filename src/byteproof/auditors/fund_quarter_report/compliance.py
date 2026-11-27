"""合规词扫描（旧仓 ``funddiff/compliance.py`` 的判定子集）。

纪律原样保留：匹配前做 NFKC + casefold + 空白折叠；命中给出 行号 / 命中词 / 原行摘录。
**词表不在器官里**：由 ``subject.compliance_terms`` 提供（旧仓从冻结配置读）。
文件读取与报告渲染属工具面，不在本器官。
"""

from __future__ import annotations

import unicodedata


def normalize_text(text):
    if not isinstance(text, str):
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(folded.split())


def scan_text(text, terms):
    """返回命中列表 ``[{line, term, excerpt}]``；行号从 1 开始。"""
    if not isinstance(text, str) or not text:
        return []
    hits = []
    normalized_terms = [(term, normalize_text(term)) for term in terms or []]
    normalized_terms = [(term, norm) for term, norm in normalized_terms if norm]
    for index, line in enumerate(text.splitlines(), start=1):
        normalized_line = normalize_text(line)
        for term, norm in normalized_terms:
            if norm in normalized_line:
                hits.append({"line": index, "term": term, "excerpt": line.strip()})
    return hits