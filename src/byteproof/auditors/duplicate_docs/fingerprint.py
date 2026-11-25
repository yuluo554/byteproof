"""shingle、精确 Jaccard、64 位指纹（旧仓 ``docdedupe/fingerprint.py`` 的判定子集）。

搬过来四件：字符 n-gram shingle、BLAKE2b 64 位哈希、**精确** Jaccard、SimHash + Hamming。
没有搬 MinHash 与 LSH banding —— 它们是**候选召回**装置（先缩候选、再由精确 Jaccard 判定），
不改变"是不是近重复"这个结论；本器官对每对文档都算精确分数，没有采样噪声进判定。

为什么分数必须是精确值而不是 MinHash 估计（旧仓的实测理由，照抄）：
128 置换的签名估计 Jaccard 的标准误差约 ``sqrt(0.2*0.8/128) ~= 0.035``，
而语料里最弱的真阳性对坐在 0.81–0.83，离 0.80 阈值只有 0.01–0.03。用估计值判定
等于把采样噪声放在决策边界上。

为什么用 BLAKE2b 而不是 ``hash()``：后者按进程加盐，同一份文本两次扫描会得到不同签名。
"""

from __future__ import annotations

import hashlib
import unicodedata

_MASK64 = (1 << 64) - 1


def shingles(text: str, size: int = 3):
    """按字典序排好的字符 n-gram 去重列表。

    排序使结果跨运行可比、可断言；去重因为 Jaccard 定义在集合上。
    比 ``size`` 还短的文本没有 shingle —— 这也是"过短文档不参与比对"的依据，
    而不是把它当成"空 vs 空"去比。
    """
    if size < 1:
        raise ValueError("shingle 长度必须为正")
    if len(text) < size:
        return []
    return sorted({text[index : index + size] for index in range(len(text) - size + 1)})


def shingle_set(text: str, size: int = 3):
    if size < 1:
        raise ValueError("shingle 长度必须为正")
    if len(text) < size:
        return set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def hash64(value: str) -> int:
    """字符串的稳定 64 位哈希（BLAKE2b digest_size=8，大端整数）。"""
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def shingle_hashes(text: str, size: int = 3):
    """shingle 集合的 64 位哈希，升序（同一文本永远同一串，落盘即规范形态）。"""
    return tuple(sorted(hash64(value) for value in shingle_set(text, size)))


def jaccard_from_hash_sets(left, right):
    """两个哈希集合的精确 Jaccard。两边都空按 1.0（同一份空内容），只一边空按 0.0。"""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    return intersection / float(len(left) + len(right) - intersection)


def jaccard(left, right):
    """两个哈希序列的精确 Jaccard。"""
    return jaccard_from_hash_sets(set(left), set(right))


def simhash64_from_hashes(hashes):
    """``hashes`` 的 64 位 SimHash（每位按出现次数过半取 1）。

    空集合得 0 —— 是一个**不同的**指纹，而不是错误：由调用方决定这种文档能否进候选集。
    """
    ones = [0] * 64
    count = 0
    for hashed in hashes:
        count += 1
        value = hashed
        while value:
            lowest = value & -value
            ones[lowest.bit_length() - 1] += 1
            value ^= lowest
    if count == 0:
        return 0
    result = 0
    for bit in range(64):
        if ones[bit] * 2 > count:
            result |= 1 << bit
    return result & _MASK64


def hamming(left: int, right: int) -> int:
    """两个 64 位指纹的汉明距离。"""
    return int(bin((left ^ right) & _MASK64).count("1"))


def latin_fold_only(text: str):
    """只折拉丁大写（供测试断言"非拉丁不动"用）。"""
    table = {}
    for code in range(0x41, 0x250):
        char = chr(code)
        if unicodedata.name(char, "").startswith("LATIN CAPITAL LETTER"):
            lower = char.lower()
            if lower != char:
                table[code] = lower
    return text.translate(table)