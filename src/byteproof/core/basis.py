"""规则包：``rule_id`` + ``rule_version`` 的唯一来源。

规则包按版本登记。器官只能通过 ``Basis.ref(rule_id)`` 取依据；取不到就是
``RuleMissing``（规则包缺失 -> 契约违约，退出码 3），**不许自己编规则**。

与 clauseproof 的差别只在「一条依据长什么样」：那里是条文锚点
（``clause_id + path + version``），这里是规则登记（``rule_id + rule_version + source``）。
允许单条规则自带版本：规则可以独立于包版本演进，取依据时如实回报它自己的版本。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from byteproof.core.ledger import ContractError, RuleRef


class RuleMissing(Exception):
    """规则包里没有这条规则。"""


@dataclass(frozen=True)
class Rule:
    """一条规则登记。``version`` 为空表示「随包版本」（见 :class:`Basis`）。"""

    rule_id: str
    version: str = ""
    title: str = ""
    source: str = ""
    text: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id or not str(self.rule_id).strip():
            raise ContractError("规则字段为空：rule_id")

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "title": self.title,
            "source": self.source,
            "text": self.text,
        }


class Basis:
    """一个版本下的规则集合（= 规则包）。

    ``version`` 是规则包版本，**必须存在**：缺了它就是「依据包版本缺失」，
    按 SKELETON-SPEC §5 直接契约违约（退出码 3），不静默当成 v0 用。
    """

    def __init__(self, version: str, rules: Iterable[Rule] = ()) -> None:
        if not version or not str(version).strip():
            raise ContractError("规则包版本为空（依据包版本缺失）")
        self._version = version
        self._rules: Dict[str, Rule] = {}
        for rule in rules:
            if rule.rule_id in self._rules:
                raise ContractError("规则重复：%s" % rule.rule_id)
            if not rule.version:
                rule = Rule(
                    rule_id=rule.rule_id,
                    version=version,
                    title=rule.title,
                    source=rule.source,
                    text=rule.text,
                )
            self._rules[rule.rule_id] = rule

    # ------------------------------------------------------------------ 构造
    @classmethod
    def empty(cls, version: str = "0") -> "Basis":
        return cls(version=version, rules=())

    @classmethod
    def from_dict(cls, data: dict) -> "Basis":
        version = data.get("version")
        raw = data.get("rules", [])
        if not isinstance(raw, list):
            raise ContractError("rules 必须是数组")
        rules = [
            Rule(
                rule_id=item.get("rule_id", ""),
                version=item.get("version", ""),
                title=item.get("title", ""),
                source=item.get("source", ""),
                text=item.get("text", ""),
            )
            for item in raw
        ]
        return cls(version=version, rules=rules)

    @classmethod
    def from_json(cls, path: str) -> "Basis":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    # ------------------------------------------------------------------ 查询
    @property
    def version(self) -> str:
        return self._version

    def __len__(self) -> int:
        return len(self._rules)

    def rule_ids(self) -> List[str]:
        return sorted(self._rules)

    def rule(self, rule_id: str) -> Optional[Rule]:
        return self._rules.get(rule_id)

    def require(self, rule_id: str) -> Rule:
        rule = self.rule(rule_id)
        if rule is None:
            raise RuleMissing("规则包 %s 无此规则：%s" % (self._version, rule_id))
        return rule

    def ref(self, rule_id: str) -> RuleRef:
        """给器官用的唯一取依据入口。"""
        rule = self.require(rule_id)
        return RuleRef(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            source=rule.source,
            quote=rule.text,
        )

    def as_dict(self) -> dict:
        return {
            "version": self._version,
            "rules": [self._rules[key].as_dict() for key in sorted(self._rules)],
        }