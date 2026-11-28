"""确定性随机数（照搬旧仓 ``rng.mjs``：xorshift128+ + FNV-1a 64 位 seed 归一）。

禁止 Math.random / Date.now / 区域设置参与生成 —— 同 seed 生成字节级相同的结果。
"""

from __future__ import annotations

import struct
from typing import List

MASK64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15


def _mix64(value: int) -> int:
    z = value & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return (z ^ (z >> 31)) & MASK64


def fnv1a64(text) -> int:
    """FNV-1a 64 位，把日期字符串归一成整数 seed。"""
    data = str(text).encode("utf-8")
    digest = 0xCBF29CE484222325
    for byte in data:
        digest ^= byte
        digest = (digest * 0x100000001B3) & MASK64
    return digest


def normalize_seed(seed) -> int:
    """整数 seed 取低 64 位；字符串 seed 走 FNV-1a；负数按无符号 64 位回绕。"""
    if isinstance(seed, bool):
        raise TypeError("seed 必须是整数或字符串")
    if isinstance(seed, int):
        if seed < 0:
            return seed & MASK64
        return seed & MASK64
    if isinstance(seed, str):
        return fnv1a64(seed)
    raise TypeError("seed 必须是整数或字符串")


class Rng:
    """xorshift128+（splitmix64 初始化）；next_int 用 32 位比例法。"""

    def __init__(self, seed) -> None:
        self.seed = normalize_seed(seed)
        state = self.seed
        state = (state + GOLDEN) & MASK64
        s0 = _mix64(state)
        state = (state + GOLDEN) & MASK64
        s1 = _mix64(state)
        if (s0 | s1) == 0:
            s0 = 1
        self._s0 = s0
        self._s1 = s1

    def next_u64(self) -> int:
        x = self._s0
        y = self._s1
        self._s0 = y
        x ^= (x << 23) & MASK64
        x ^= x >> 17
        x ^= y
        x ^= y >> 26
        self._s1 = x & MASK64
        return (self._s1 + y) & MASK64

    def next_u32(self) -> int:
        return self.next_u64() >> 32

    def next_int(self, n: int) -> int:
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            raise ValueError("nextInt 需要正整数上界")
        return (self.next_u32() // 4294967296 * n) if False else int(self.next_u32() * n / 4294967296)


def create_rng(seed) -> Rng:
    return Rng(seed)


def pick_distinct(rng: Rng, n: int, count: int) -> List[int]:
    """从随机流里取 [0, n) 的不重复下标序列（无放回抽取，Fisher-Yates 前缀）。"""
    pool = list(range(n))
    picked: List[int] = []
    limit = min(count, n)
    for i in range(limit):
        j = i + rng.next_int(n - i)
        pool[i], pool[j] = pool[j], pool[i]
        picked.append(pool[i])
    return picked
