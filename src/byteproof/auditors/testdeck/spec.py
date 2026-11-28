"""口径面（迁自 10-19-testdeck 的 ``model`` / ``rules/*.json`` / ``keys`` / ``exit_codes`` / ``junit`` 原因码）。

**阈值与规则只有这一份**（旧仓纪律：引擎零默认值，规则包缺失即 ``RulesError``）：
``FLAKY_RULES`` / ``SLOW_RULES`` / ``VIEW_RULES`` 是唯一可读来源，快照
``byteproof/data/testdeck.thresholds.json`` 由测试双向断言逐键相等；``core.py`` 不出现
数值阈值字面量（架构测试钉住）。

精确有理数纪律（旧仓「禁用 float」）：阈值以十进制字符串存放，取用时经
``core.as_fraction`` 转 ``Fraction``；``float`` 一律拒绝（浮点会让边界判定掷硬币）。
"""

from __future__ import annotations

from typing import Dict, List, Tuple

ORGAN_VERSION = "1"

#: 判定模式（旧仓模块面 + 编排面 + 门禁面）。
MODES = ("junit", "ingest", "flaky", "slow", "diff", "views", "gate")
DEFAULT_MODE = "views"

# ---------------------------------------------------------------- 四态与字形
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"
STATUS_MISSING = "missing"
STATUSES: Tuple[str, ...] = (STATUS_PASS, STATUS_FAIL, STATUS_SKIP, STATUS_MISSING)
#: 参与 fail_rate / flaky_score 计数的状态；skip / missing 既不进分母也不制造 transition。
COUNTED_STATUSES: Tuple[str, ...] = (STATUS_PASS, STATUS_FAIL)
#: 矩阵单元格图例（唯一来源）。
STATUS_GLYPHS: Dict[str, str] = {
    STATUS_PASS: "\u00b7",
    STATUS_FAIL: "\u2717",
    STATUS_SKIP: "-",
    STATUS_MISSING: "?",
}

# ---------------------------------------------------------------- 退出码
EXIT_OK = 0
EXIT_GATE = 1
EXIT_USAGE = 2
EXIT_DEPENDENCY = 3
EXIT_NOT_READY = 4

# ---------------------------------------------------------------- 解析原因码
BAD_XML = "bad_xml"
BAD_ENCODING = "bad_encoding"
NO_TESTSUITE = "no_testsuite"
UNREADABLE = "unreadable"
REASONS: Tuple[str, ...] = (BAD_XML, BAD_ENCODING, NO_TESTSUITE, UNREADABLE)

DEGRADED_BAD_TIME = "bad_time"
DEGRADED_MISSING_NAME = "missing_name"
DEGRADED_STARTED_AT = "started_at_missing"
DEGRADED_BAD_COMMIT = "bad_commit"
DEGRADED_REASONS: Tuple[str, ...] = (
    DEGRADED_BAD_TIME,
    DEGRADED_MISSING_NAME,
    DEGRADED_STARTED_AT,
    DEGRADED_BAD_COMMIT,
)

#: XML 输入上限（安全护栏，不是判定阈值）：超过即拒（见 ``core.parse_xml_text``）。
MAX_XML_CHARS = 8 * 1024 * 1024
#: 拒绝 DTD / ENTITY（实体扩展防护）；原因码落在 ``detail``，不新增文件级原因码。
DTD_REJECTED = "dtd_forbidden"
OVERSIZE = "oversize"

#: 元素重数字段（与旧仓 ``bench_ingest.COUNT_FIELDS`` 同口径）。
COUNT_FIELDS: Tuple[str, ...] = ("tests", "failures", "errors", "skipped")

#: 框架名与线索（顺序即短路顺序）。
FRAMEWORK_UNKNOWN = "unknown"
FRAMEWORKS: Tuple[str, ...] = ("pytest", "gotestsum", "playwright")
NAME_HINTS: Tuple[Tuple[str, str], ...] = (
    ("pytest", "pytest"),
    ("gotestsum", "gotestsum"),
    ("playwright", "playwright"),
)
PROPERTY_HINTS: Tuple[Tuple[str, str], ...] = (("go.version", "gotestsum"),)
FILENAME_HINTS: Tuple[Tuple[str, str], ...] = (
    ("gotestsum", "gotestsum"),
    ("playwright", "playwright"),
    ("junit", "pytest"),
)

# ---------------------------------------------------------------- 规则包（唯一来源）
FLAKY_RULES: Dict[str, object] = {
    "min_fail_rate": "0.05",
    "max_fail_rate": "0.95",
    "min_transitions": 3,
    "min_runs_for_flaky": 2,
    "fallback_label": "watch",
    "labels": {
        "broken": "fail_rate == 1",
        "stable": "fail_rate == 0",
        "flaky": "min_fail_rate <= fail_rate <= max_fail_rate and transitions >= min_transitions",
        "watch": "otherwise",
    },
}

SLOW_RULES: Dict[str, object] = {
    "slow_ms": 1000,
    "regression_ratio": "1.2",
    "regression_delta_ms": 200,
    "waterfall_width": 40,
    "p50": "0.50",
    "p95": "0.95",
    "index_formula": "(n - 1) * p",
}

VIEW_RULES: Dict[str, object] = {
    "sparkline_runs": 20,
    "min_width_single_column": 80,
    "summary_fields": ["total", "fail", "skip", "flaky", "broken", "slow"],
    "tree_sort": "fail_first_then_suite_order_then_lexical",
    "formats": ["md", "json"],
    "fail_on": ["flaky", "new-failures", "regressions"],
    "json_indent": 2,
    "json_ensure_ascii": False,
    "write_generated_at": False,
}

#: 分型稳定名（规则包 ``labels`` 表登记的是"有哪些标签"）。
LABEL_STABLE = "stable"
LABEL_FLAKY = "flaky"
LABEL_BROKEN = "broken"
LABEL_KEYS: Tuple[str, ...] = (LABEL_STABLE, LABEL_FLAKY, LABEL_BROKEN)

#: diff 三类 + 其余桶（固定展示顺序）。
NEW_FAILURES = "new-failures"
FIXED = "fixed"
STILL_FAILING = "still-failing"
UNCHANGED = "unchanged"
CLASS_ORDER: Tuple[str, ...] = (NEW_FAILURES, FIXED, STILL_FAILING, UNCHANGED)
RECONCILED_CLASSES: Tuple[str, ...] = (NEW_FAILURES, FIXED, STILL_FAILING)
CLASS_TITLES: Dict[str, str] = {
    NEW_FAILURES: "新增失败",
    FIXED: "修复",
    STILL_FAILING: "仍失败",
    UNCHANGED: "其余（未分类）",
}

#: 回归不可判的两个原因码。
NOTE_UNDEFINED_BASE = "undefined_base"
NOTE_MISSING_WINDOW = "missing_window"
#: 样本量降级两条。
LABEL_SINGLE_SAMPLE = "single_sample"
LABEL_INSUFFICIENT_HISTORY = "insufficient_history"

#: 渲染精度（只影响"终止小数有多长"，不影响判定）。
RENDER_PRECISION = 80
#: 判"终止小数"时要试除的素数。
TERMINATING_PRIMES: Tuple[int, ...] = (2, 5)

# ---------------------------------------------------------------- 键位表（单点）
BINDINGS: Dict[str, str] = {
    "down": "j",
    "up": "k",
    "first": "g",
    "last": "G",
    "enter": "enter",
    "flaky": "F",
    "slow": "S",
    "diff": "D",
    "search": "/",
    "export": "e",
    "help": "?",
    "back": "escape",
    "quit": "q",
}
KEYS: Tuple[Tuple[str, str], ...] = (
    ("j", "下一项（down）"),
    ("k", "上一项（up）"),
    ("g", "跳到首（first）"),
    ("G", "跳到尾（last）"),
    ("Enter", "展开 / 进入详情（enter）"),
    ("F", "flaky 矩阵"),
    ("S", "慢测试瀑布"),
    ("D", "两次 run diff"),
    ("/", "搜索"),
    ("e", "导出当前视图"),
    ("?", "帮助"),
    ("Esc", "返回三栏（back）"),
    ("q", "退出（quit）"),
)
DISPLAY_LABELS: Dict[str, str] = {"enter": "Enter", "escape": "Esc"}

# ---------------------------------------------------------------- 账本规则 id
R_JUNIT_FILE = "td-junit-file-reason"      # 文件级原因码（bad_xml/…）
R_JUNIT_DEGRADED = "td-junit-degraded"     # 单项降级（bad_time/…）
R_JUNIT_FRAMEWORK = "td-junit-framework"   # 框架识别三态（unknown 也显式）
R_FLAKY = "td-flaky-label"                 # 四类分型逐条
R_FLAKY_SUMMARY = "td-flaky-summary"
R_SLOW = "td-slow-regression"              # 回归三态逐条
R_SLOW_SAMPLE = "td-slow-sample-label"     # 样本量降级标注
R_SLOW_SUMMARY = "td-slow-summary"
R_DIFF = "td-diff-class"                   # 三类逐条
R_DIFF_SUMMARY = "td-diff-summary"
R_INGEST_REPORT = "td-ingest-report"       # ingest 摘要（含 skipped/degraded 计数）
R_INGEST_MISSING = "td-ingest-missing"     # 缺失入参（退出码 2）
R_TREE = "td-tree-order"                   # 失败优先树（形状面）
R_SUMMARY = "td-view-summary"
R_GATE = "td-gate"                         # --fail-on 门禁命中
R_VIEW_DEGRADE = "td-view-degrade"         # 单栏 / 无颜色两条降级
R_KEYS = "td-keys-single-source"
R_STORE = "td-store-upsert"                # 入库幂等（同身份不新增行）
R_SUMMARY_RULE = "td-summary"

ALL_RULES: Tuple[str, ...] = (
    R_JUNIT_FILE, R_JUNIT_DEGRADED, R_JUNIT_FRAMEWORK,
    R_FLAKY, R_FLAKY_SUMMARY, R_SLOW, R_SLOW_SAMPLE, R_SLOW_SUMMARY,
    R_DIFF, R_DIFF_SUMMARY, R_INGEST_REPORT, R_INGEST_MISSING, R_TREE,
    R_SUMMARY, R_GATE, R_VIEW_DEGRADE, R_KEYS, R_STORE, R_SUMMARY_RULE,
)

#: 规则 id → verdict（阻断面 = 文件级原因码 / 缺失入参 / 有损降级 / 门禁命中）。
SEVERITY: Dict[str, str] = {
    R_JUNIT_FILE: "error",
    R_JUNIT_DEGRADED: "warn",
    R_JUNIT_FRAMEWORK: "info",
    R_FLAKY: "info",
    R_FLAKY_SUMMARY: "info",
    R_SLOW: "info",
    R_SLOW_SAMPLE: "warn",
    R_SLOW_SUMMARY: "info",
    R_DIFF: "info",
    R_DIFF_SUMMARY: "info",
    R_INGEST_REPORT: "info",
    R_INGEST_MISSING: "error",
    R_TREE: "info",
    R_SUMMARY: "info",
    R_GATE: "error",
    R_VIEW_DEGRADE: "info",
    R_KEYS: "info",
    R_STORE: "info",
    R_SUMMARY_RULE: "info",
}

#: 默认扫描模式（目录入参按这些模式递归找产物）。
DEFAULT_GLOBS: Tuple[str, ...] = (
    "**/junit*.xml",
    "**/surefire-reports/*.xml",
    "**/build/test-results/**/*.xml",
)

#: 唯一允许的判定标签（四类分型名 + 兜底）。
FLAKY_LABELS: Tuple[str, ...] = (LABEL_STABLE, LABEL_FLAKY, LABEL_BROKEN) + ("watch",)

#: 跳过/降级理由词表（账本逐条显式，不静默）。
SKIP_REASONS: Tuple[str, ...] = REASONS + DEGRADED_REASONS + (
    "no_testsuite", "pending_bucket", "unchanged",
)

#: summary 六个字段（键序即展示序）。
SUMMARY_FIELDS: List[str] = list(VIEW_RULES["summary_fields"])