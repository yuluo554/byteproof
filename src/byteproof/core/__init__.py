"""byteproof 内核：缺陷账本 + 规则包 + 器官注册表。

三条内核约束（违反即 ``ContractError``，进程退出码 3）：
1. 无规则依据不得下 ``error``；
2. 器官不带自己的 CLI / 配置文件 / 输出排版；
3. 输出确定性：无时间戳、无绝对路径、字段顺序固定。
"""

from byteproof.core.basis import Basis, Rule, RuleMissing
from byteproof.core.ledger import (
    BLOCKING_VERDICTS,
    ERROR,
    EXIT_BLOCKED,
    EXIT_CONTRACT,
    EXIT_INPUT,
    EXIT_OK,
    INFO,
    VERDICTS,
    WARN,
    ContractError,
    Record,
    Report,
    RuleRef,
)
from byteproof.core.registry import Pack, PackMissing, all_packs, get, load_entry_points, register

__all__ = [
    "Basis",
    "Rule",
    "RuleMissing",
    "RuleRef",
    "Record",
    "Report",
    "ContractError",
    "Pack",
    "PackMissing",
    "register",
    "get",
    "all_packs",
    "load_entry_points",
    "ERROR",
    "WARN",
    "INFO",
    "VERDICTS",
    "BLOCKING_VERDICTS",
    "EXIT_OK",
    "EXIT_BLOCKED",
    "EXIT_INPUT",
    "EXIT_CONTRACT",
]