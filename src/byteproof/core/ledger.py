"""缺陷账本：byteproof 的唯一输出模型（契约见 SKELETON-SPEC §3–§6）。

一条账本行 = 一个缺陷结论 + 一条规则依据。

两条约束不是文档约定，而是在 :class:`Record` 构造时就拦下的：

1. **无依据不下 error**：``error`` 且 ``basis_ref`` 为空 -> ``ContractError``（进程退出码 3）；
2. **依据缺版本就降级**：``rule_version`` 为空 -> 结论降级为 ``info``，并在 ``message``
   里写明缺失项（不许拿半个依据冒充完整依据）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

ERROR = "error"
WARN = "warn"
INFO = "info"
VERDICTS = (ERROR, WARN, INFO)
#: 会阻断的结论；``warn`` / ``info`` 只记录、不阻断。
BLOCKING_VERDICTS = (ERROR,)

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_INPUT = 2
EXIT_CONTRACT = 3


class ContractError(Exception):
    """契约违约：无规则依据下 error、依据字段为空、结论取值非法。"""


@dataclass(frozen=True)
class RuleRef:
    """规则登记引用：``rule_id`` + ``rule_version``（SKELETON-SPEC §3）。

    ``rule_version`` 允许为空——空值不是「合法依据」，而是 §4.2 的降级信号，
    由 :class:`Record` 负责把结论降成 ``info`` 并写明缺失项。
    """

    rule_id: str
    rule_version: str = ""
    source: str = ""
    quote: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id or not str(self.rule_id).strip():
            raise ContractError("规则引用字段为空：rule_id")

    @property
    def complete(self) -> bool:
        """版本是否齐备（缺版本的依据不得支撑 error）。"""
        return bool(self.rule_version and str(self.rule_version).strip())

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "source": self.source,
            "quote": self.quote,
        }


@dataclass(frozen=True)
class Record:
    """一条缺陷结论。

    ``basis`` 为 ``None`` 时只允许 ``warn`` / ``info``；``path`` 是该缺陷在工件里的
    位置（文件路径 / JSON 指针 / 偏移区间），与 ``rule_id`` 一起派生稳定的 ``id``。
    """

    rule_id: str
    verdict: str
    message: str
    basis: Optional[RuleRef] = None
    path: str = ""
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_id or not str(self.rule_id).strip():
            raise ContractError("rule_id 为空")
        if self.verdict not in VERDICTS:
            raise ContractError("非法结论：%s（允许 %s）" % (self.verdict, VERDICTS))
        if self.basis is None and self.verdict in BLOCKING_VERDICTS:
            raise ContractError("无规则依据不得下 error（rule=%s）" % (self.rule_id,))
        if self.basis is not None and not self.basis.complete:
            # §4.2：依据缺版本 -> 降级为 info，并在 message 里写明缺失项
            note = "（依据缺版本：rule_id=%s 无 rule_version，按契约降级为 info）" % (
                self.basis.rule_id,
            )
            object.__setattr__(self, "verdict", INFO)
            object.__setattr__(self, "message", ("%s %s" % (self.message, note)).strip())

    @property
    def id(self) -> str:
        """稳定 id：由规则 + 位置派生（同一缺陷重复跑得到同一个 id）。"""
        return "%s@%s" % (self.rule_id, self.path or "-")

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "verdict": self.verdict,
            "message": self.message,
            "basis_ref": self.basis.as_dict() if self.basis is not None else None,
            "path": self.path,
            "evidence": dict(self.evidence),
        }

    def as_line(self) -> str:
        where = "%s (%s@%s)" % (
            self.path or "无位置",
            self.basis.rule_id if self.basis else "-",
            self.basis.rule_version if self.basis else "-",
        )
        return "[%s] %s — %s :: %s" % (self.verdict, self.rule_id, self.message, where)


@dataclass(frozen=True)
class Report:
    """一次审计运行的完整账本。"""

    product: str
    organ: str
    organ_version: str
    subject: str
    records: Tuple[Record, ...] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("product", self.product),
            ("organ", self.organ),
            ("organ_version", self.organ_version),
            ("subject", self.subject),
        ):
            if not value or not str(value).strip():
                raise ContractError("账本头字段为空：%s" % name)
        records = tuple(self.records)
        dup = _duplicate_ids(records)
        if dup:
            raise ContractError("账本 id 冲突（同一规则命中同一位置两次）：%s" % sorted(dup))
        # 确定性排序：同一输入无论器官按什么顺序产出，账本顺序一致
        object.__setattr__(self, "records", tuple(sorted(records, key=_sort_key)))

    def blocking(self) -> Tuple[Record, ...]:
        return tuple(r for r in self.records if r.verdict in BLOCKING_VERDICTS)

    def summary(self) -> dict:
        counts = {verdict: 0 for verdict in VERDICTS}
        for record in self.records:
            counts[record.verdict] += 1
        return {"blocking": len(self.blocking()), "total": len(self.records), "verdicts": counts}

    def exit_code(self) -> int:
        return EXIT_BLOCKED if self.blocking() else EXIT_OK

    def as_dict(self) -> dict:
        return {
            "product": self.product,
            "organ": self.organ,
            "organ_version": self.organ_version,
            "subject": self.subject,
            "summary": self.summary(),
            "records": [record.as_dict() for record in self.records],
        }

    def as_lines(self) -> list:
        lines = ["%s :: %s %s :: %s" % (self.product, self.organ, self.organ_version, self.subject)]
        lines.extend(record.as_line() for record in self.records)
        summary = self.summary()
        lines.append(
            "合计 %d 条，阻断 %d 条（error=%d warn=%d info=%d）"
            % (
                summary["total"],
                summary["blocking"],
                summary["verdicts"][ERROR],
                summary["verdicts"][WARN],
                summary["verdicts"][INFO],
            )
        )
        return lines


def _sort_key(record: Record):
    return (record.rule_id, record.verdict, record.path, record.message)


def _duplicate_ids(records: Tuple[Record, ...]):
    seen, dup = set(), set()
    for record in records:
        if record.id in seen:
            dup.add(record.id)
        seen.add(record.id)
    return dup