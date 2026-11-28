"""口径面：判定态、退出码语义、阈值常量与条件集。

数值口径照搬旧仓 ``src/contract.mjs``（唯一镜像，``data/README.md`` §5 为唯一定义）。
规则 id 前缀 ``dp-``；旧仓五判定态原样保留（不翻译成账本三值 —— 判定态进
``evidence.status``，账本 verdict 由「问题态/算不了/只记录」三族决定，见 ``api``）。
"""

from __future__ import annotations

ORGAN_VERSION = "1"

#: 旧仓 CLI 的六个子命令（``src/contract.mjs`` COMMANDS）。
#: ``selftest`` / ``bench`` 是仓级脚手架命令（D1 排除词 selftest|bench），
#: ``scan`` / ``snapshot`` 输出引用点与依赖面清单（报告面），器官只收 check / drift。
COMMANDS = ("check", "snapshot", "scan", "drift", "selftest", "bench")

#: 器官收下的两个模式（subject.mode）。
MODES = ("check", "drift")
DEFAULT_MODE = "check"

#: 五判定态（``src/contract.mjs`` STATUS，冻结）。
STATUS = {
    "RESOLVED": "RESOLVED",
    "MISSING_EXPORT": "MISSING-EXPORT",
    "ESM_CJS_MISMATCH": "ESM-CJS-MISMATCH",
    "NOT_EXPORTED_SUBPATH": "NOT-EXPORTED-SUBPATH",
    "AMBIGUOUS": "AMBIGUOUS",
}

#: 非判定态：仅 drift 用，表示"没有离线指纹，不猜"。
NO_BASELINE = "NO-BASELINE"

#: 版本行为漂移判定态。
DRIFT = "VERSION-BEHAVIOR-DRIFT"

#: 会进 problems 的判定态（旧仓 PROBLEM_STATUSES：判定顺序的尾部三态）+ drift。
PROBLEM_STATUSES = (
    "MISSING-EXPORT",
    "ESM-CJS-MISMATCH",
    "NOT-EXPORTED-SUBPATH",
)
PROBLEM_STATUSES_WITH_DRIFT = PROBLEM_STATUSES + (DRIFT,)

#: 解析失败态（不是"发现问题"，是"算不了"→ 旧仓进 gaps、退出码 3）。
UNPARSEABLE = "UNPARSEABLE"

#: 引用点种类（``src/contract.mjs`` KIND；``AMBIGUOUS`` 是一种 kind，也是同名判定态）。
KIND = (
    "import",
    "export-from",
    "require",
    "dynamic-import",
    "jest-mock",
    "string-literal",
    "ambiguous",
)

#: 默认扫描的源码扩展名（``data/README.md`` §5 首期范围）。收集遍历在输入层，这里留档。
SOURCE_EXTENSIONS = (".js", ".cjs", ".mjs", ".ts", ".tsx", ".vue")

#: 默认跳过的目录名（收集遍历在输入层，这里留档）。
SKIP_DIRS = ("node_modules", ".git", "dist", "build", "coverage", ".cache")

# 阈值（``data/README.md`` §5.3 唯一定义；``.thresholds.json`` 快照由测试双向断言）。
#: ``exports`` 子路径键数上限；超限整包记 ``UNPARSEABLE``（进 gaps），**不得截断静默**。
EXPORTS_KEYS_LIMIT = 4096
#: 单文件 UTF-8 字节上限；超限降级为字符串兜底扫描并记 ``LARGE_FILE_DOWNGRADED``。
SOURCE_FILE_BYTES = 524288

#: 降级扫描的 gap 种类（不是"发现问题"，是"覆盖率有折损"，必须显式出现）。
LARGE_FILE_DOWNGRADED = "LARGE_FILE_DOWNGRADED"

#: 本工具名（输出与契约共用一处）。
TOOL = "depcheck-live"

#: Node 条件集（实测口径，``src/resolve.mjs`` CONDITIONS；``default`` 由匹配逻辑单独处理）。
CONDITIONS = {
    "import": ("node", "import", "module-sync", "node-addons"),
    "require": ("node", "require", "module-sync", "node-addons"),
}

#: 判定顺序（``plan/03`` §4.4，首个成立者胜）：AMBIGUOUS → NOT-EXPORTED-SUBPATH →
#: ESM-CJS-MISMATCH → UNPARSEABLE → MISSING-EXPORT → RESOLVED；顺序由 check 模块实现。
