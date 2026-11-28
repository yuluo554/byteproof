"""Catalogue adapter：旧仓 ``rules.py`` CATALOG 的 basis 化读取层。

旧仓判定层的措辞纪律（"the wording of every finding is read from the generated
catalogue, never written here"）原样保留：本器官的措辞唯一来源是随包
``byteproof/data/http-semantics.basis.json``（CATALOG 生成件逐字节迁入），器官通过
``Basis.require(code)`` 取规则登记——``Rule.text`` 是模板、``Rule.source`` 的
"出处："之后是 ``; `` 连接的 spec_ref 列表。规则缺失 = ``RuleMissing`` → 契约违约
rc 3（漏 basis 契约正确行为）。

阈值表（severity / vary_normalization / preflight_cache_key）不在 basis 里——
它们是运行期常量，快照在 ``http-semantics.thresholds.json``，由测试双向断言。
"""

from __future__ import annotations

from byteproof.core.basis import Basis

from . import spec


class Catalogue:
    """CATALOG 的 basis 化视图：``codes[code]`` 返回旧仓同构的记录字典。"""

    def __init__(self, basis: Basis, settings: dict):
        self._basis = basis
        self._settings = settings

    @property
    def settings(self) -> dict:
        return self._settings

    def codes(self, code: str) -> dict:
        rule = self._basis.require(code)
        source = rule.source or ""
        marker = "出处："
        spec_refs = source.split(marker, 1)[1].split("; ") if marker in source else []
        return {
            "meaning": rule.title,
            "spec_ref": spec_refs,
            "template": rule.text,
            "severity": self._settings["severity"][code],
        }

    def finding(self, code: str, **parameters) -> dict:
        """渲染一条 finding（与旧仓 ``_finding`` 同构：措辞来自 catalogue，不手写）。"""
        record = self.codes(code)
        return {
            "code": code,
            "spec_ref": record["spec_ref"],
            "detail": record["template"].format(**parameters),
        }

    def severity(self, code: str) -> str:
        return self._settings["severity"][code]

    def vary_normalization(self) -> dict:
        return self._settings["vary_normalization"]

    def preflight_cache_key(self) -> dict:
        return self._settings["preflight_cache_key"]

    def basis_ref(self, code: str):
        """给编排层用的取依据入口（RuleMissing = 契约违约 rc 3）。"""
        return self._basis.ref(code)

    def rule_ids(self):
        return sorted(self._basis.rule_ids())

    def mode_names(self):
        return spec.MODES
