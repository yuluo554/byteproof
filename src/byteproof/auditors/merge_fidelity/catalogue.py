"""Catalogue adapter：措辞唯一来源是随包 ``merge-fidelity.basis.json``。

器官不手写 finding 句子；``mf-*`` 规则登记的 ``text`` 是判定口径文本（不是模板——
本器官的 message 由结构化字段拼装，规则文本承担**判定口径**，与旧仓
``data/README.md`` §4.1–§4.6 的口径条目一一对应）。
"""

from __future__ import annotations

from byteproof.core.basis import Basis


class Catalogue:
    """basis 的只读视图 + 取依据入口（RuleMissing = 契约违约 rc 3）。"""

    def __init__(self, basis: Basis):
        self._basis = basis

    def basis_ref(self, rule_id: str):
        return self._basis.ref(rule_id)

    def rule(self, rule_id: str):
        return self._basis.rule(rule_id)

    def rule_ids(self):
        return sorted(self._basis.rule_ids())
