"""并查集聚类 + 档位（旧仓 ``docdedupe/cluster.py`` 的判定子集）。

三件事，各占一个位置：

* **边分类**：一对文档要么 ``exact``（归一化后完全相同），要么 ``near``
  （精确 Jaccard ≥ ``near_duplicate_threshold``），要么**不是边**（只是相似，不足立案）。
  第三条同样重要 —— 两份文档可以有 0.56 的相似度而毫无关系，把它画成边就是伪造结论。
* **并查集**：簇 = 连通分量。
* **档位按最弱边定**：簇里有一条 ``near`` 边就是 ``near``，否则是 ``exact``。

**没有搬**：模板族档位（``template_evidence`` 的字段位置掩码）、保留建议的五维加权打分、
``template_field_diff_max``。它们回答的是"该留哪一份"（报告概念），
而 byteproof 的账本只回答"这一份和那一份是不是同一份内容"。
这条删减写在 ``docs/duplicate-docs.md`` 的处置表里，需要时再按旧仓口径补回。

确定性：``cluster_id`` 由排序后的成员路径派生，与读入顺序无关；成员与簇都按路径排序；
全程不读时钟。
"""

from __future__ import annotations

import hashlib

EXACT = "exact"
NEAR = "near"


def _pack(values):
    joined = "\x00".join(values)
    return joined.encode("utf-8")


def cluster_id(members):
    """排序后成员路径的 12 位十六进制摘要（与读入顺序无关）。"""
    ordered = sorted(members)
    return "c" + hashlib.blake2b(_pack(ordered), digest_size=6).hexdigest()


def edge_kind(jaccard_value, same_norm_text, threshold):
    """一对文档的边类型：``exact`` / ``near`` / ``None``（不是边）。"""
    if same_norm_text:
        return EXACT
    if jaccard_value >= threshold:
        return NEAR
    return None


class UnionFind:
    """最小并查集（路径减半 + 按秩合并），簇只关心连通性。"""

    def __init__(self):
        self._parent = {}

    def add(self, node):
        self._parent.setdefault(node, node)

    def find(self, node):
        self.add(node)
        root = node
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[node] != root:
            self._parent[node], node = root, self._parent[node]
        return root

    def union(self, left, right):
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        # 按字典序定根，簇代表与插入顺序无关
        if left_root <= right_root:
            self._parent[right_root] = left_root
        else:
            self._parent[left_root] = right_root

    def components(self):
        groups = {}
        for node in list(self._parent):
            groups.setdefault(self.find(node), []).append(node)
        return [sorted(members) for _root, members in sorted(groups.items())]


def build_clusters(edges, paths):
    """把合格边并成簇，返回 ``[{cluster_id, tier, members}]``（只返回 ≥2 成员的簇）。"""
    forest = UnionFind()
    for path in paths:
        forest.add(path)
    tiers = {}
    for left, right, kind in edges:
        forest.union(left, right)
        root = forest.find(left)
        if kind == NEAR:
            tiers[root] = NEAR
        else:
            tiers.setdefault(root, EXACT)
    clusters = []
    for members in forest.components():
        if len(members) < 2:
            continue
        root = forest.find(members[0])
        clusters.append(
            {
                "cluster_id": cluster_id(members),
                "tier": tiers.get(root, EXACT),
                "members": members,
            }
        )
    return sorted(clusters, key=lambda item: (item["tier"], item["members"][0]))