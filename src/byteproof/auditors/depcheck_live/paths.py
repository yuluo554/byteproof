"""路径工具（迁自旧仓 ``src/paths.mjs``）。

纪律：产物与日志中**不得出现用户绝对路径**（旧仓 ``plan/01`` §六 隐私红线）。
器官收到的 subject 文件键一律按此口径规整成相对路径 + 正斜杠，输出才可在
任何平台逐字节一致。纯字符串运算，不读文件。
"""

from __future__ import annotations

import posixpath
from typing import Iterable, List


def normalize_slashes(path: str) -> str:
    """把反斜杠统一成正斜杠。"""
    return str(path).replace("\\", "/")


def basename_chain(abs_path: str) -> str:
    """回落：只保留最后两段（已足够定位，且不含盘符与用户名）。"""
    parts = [p for p in normalize_slashes(abs_path).split("/") if p]
    chain = "/".join(parts[-2:])
    return chain or "<unresolved>"


def to_relative(root: str, abs_path: str) -> str:
    """把绝对路径相对化到 ``root``；跨盘符/不同根时回落到 basename 链。

    旧仓实测坑（Windows）：跨盘符 ``path.relative`` 会抛 ``ValueError``/返回绝对路径，
    显式回落，别让一次路径相对化把整条判定打挂。
    """
    try:
        rel = posixpath.relpath(normalize_slashes(abs_path), normalize_slashes(root))
    except ValueError:
        return basename_chain(abs_path)
    if rel == ".":
        return "."
    if rel.startswith("../") or rel == "..":
        # 相对化结果不是"根下的一段"（跨盘符/不同根）→ 回落，不留盘符与用户名
        return basename_chain(abs_path)
    return normalize_slashes(rel)


def stable_sort(items: Iterable[str]) -> List[str]:
    """输出去重 + 稳定排序（确定性：所有集合遍历前必须先排序）。"""
    return sorted(set(items))
