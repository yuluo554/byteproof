"""Catalogue adapter（措辞/口径唯一来源 = 随包 ``subset-audit.basis.json``）。"""

from __future__ import annotations

from byteproof.core.basis import Basis


class Catalogue:
    def __init__(self, basis: Basis):
        self._basis = basis

    def basis_ref(self, rule_id: str):
        return self._basis.ref(rule_id)

    def rule(self, rule_id: str):
        return self._basis.rule(rule_id)

    def rule_ids(self):
        return sorted(self._basis.rule_ids())
