"""规则 ID → 等级的唯一映射表（器官侧口径，**不是**依据文本）。

依据文本（``title`` / ``source`` / ``text``）不在这里：它在随包分发的规则包里
（``src/byteproof/data/timeseries-anomaly.basis.json``），器官只能通过
``basis.ref(rule_id)`` 取。本模块只回答两件器官自己的事：

1. **哪条规则叫什么**（``rule_id``，账本与依据包共用同一个字符串，写歪一个就取不到依据 ->
   退出码 3，这是有意的硬失败）；
2. **它落到哪个等级**。等级的语义是 byteproof 的账本语义（``error`` 阻断 / ``warn`` 记录 /
   ``info`` 只留痕），不是旧仓的"离散程度"。

等级映射的理由写在这里，因为它就是口径本身：

* ``error`` = 这个工件的**时间轴或数值已经不可信**，后续任何结论都建立在不干净的数据上：
  时间戳读不出来、值不是有限数、重复时间戳超出容差、时间倒序超出容差。
* ``warn`` = 工件可信，但**有实质异常**：四个信号检测器命中，或采样断档到"这里缺了样本"。
* ``info`` = 值得留痕、但不构成缺陷：连续缺失段/零值段本身（缺失是数据，不是损坏）、
  采样不规则（比率而已，不判断好坏）。

``ts-*`` 前缀是本器官的命名空间，跨器官不会撞车（账本 id 由 ``rule_id@path`` 派生）。
"""

from __future__ import annotations

from byteproof.core.ledger import ERROR, INFO, WARN

# ── 工件结构（时间轴可不可信）────────────────────────────────────────────
RULE_TIMESTAMP_UNREADABLE = "ts-timestamp-unreadable"
RULE_VALUE_INVALID = "ts-value-invalid"
RULE_DUPLICATE_TIMESTAMP = "ts-duplicate-timestamp"
RULE_NON_MONOTONIC = "ts-non-monotonic"

# ── 数据形状（缺没缺、齐不齐）──────────────────────────────────────────────
RULE_GAP = "ts-gap"
RULE_IRREGULAR_CADENCE = "ts-irregular-cadence"

# ── 信号（四个检测器）────────────────────────────────────────────────────
RULE_ROLLING_MAD_Z = "ts-rolling-mad-z"
RULE_ROLLING_IQR = "ts-rolling-iqr"
RULE_STL_RESID_Z = "ts-stl-resid-z"
RULE_STATIC_THRESHOLD = "ts-static-threshold"
RULE_PCT_JUMP = "ts-pct-jump"
RULE_MISSING_RUN = "ts-missing-run"
RULE_ZERO_RUN = "ts-zero-run"
RULE_CUSUM = "ts-cusum"

#: 全部规则（字典序）。规则包里必须一条不缺，缺一条用到时就是 ``RuleMissing``。
RULE_IDS = (
    RULE_CUSUM,
    RULE_DUPLICATE_TIMESTAMP,
    RULE_GAP,
    RULE_IRREGULAR_CADENCE,
    RULE_MISSING_RUN,
    RULE_NON_MONOTONIC,
    RULE_PCT_JUMP,
    RULE_ROLLING_IQR,
    RULE_ROLLING_MAD_Z,
    RULE_STATIC_THRESHOLD,
    RULE_STL_RESID_Z,
    RULE_TIMESTAMP_UNREADABLE,
    RULE_VALUE_INVALID,
    RULE_ZERO_RUN,
)

#: 规则 -> 等级。``error`` 必须有依据，由内核 ``Record`` 在构造时强制。
VERDICT_BY_RULE = {
    RULE_TIMESTAMP_UNREADABLE: ERROR,
    RULE_VALUE_INVALID: ERROR,
    RULE_DUPLICATE_TIMESTAMP: ERROR,
    RULE_NON_MONOTONIC: ERROR,
    RULE_GAP: WARN,
    RULE_IRREGULAR_CADENCE: INFO,
    RULE_ROLLING_MAD_Z: WARN,
    RULE_ROLLING_IQR: WARN,
    RULE_STL_RESID_Z: WARN,
    RULE_STATIC_THRESHOLD: WARN,
    RULE_PCT_JUMP: WARN,
    RULE_MISSING_RUN: INFO,
    RULE_ZERO_RUN: INFO,
    RULE_CUSUM: WARN,
}

#: 检测器名 -> 规则 ID。``rules`` 家族的检测器名带 ``rules.`` 前缀（旧仓 ``run_detectors``
#: 的分桶键），这样一条 ``rules`` 命中不会和另一个检测器混进同一段 episode。
SIGNAL_RULE_BY_DETECTOR = {
    "rolling_mad_z": RULE_ROLLING_MAD_Z,
    "rolling_iqr": RULE_ROLLING_IQR,
    "stl_resid_z": RULE_STL_RESID_Z,
    "rules.static_threshold": RULE_STATIC_THRESHOLD,
    "rules.pct_jump": RULE_PCT_JUMP,
    "rules.missing_run": RULE_MISSING_RUN,
    "rules.zero_run": RULE_ZERO_RUN,
    "rules.cusum": RULE_CUSUM,
}

#: 检测器名 -> 参数块名（``threshold_refs`` 的键）。
DETECTOR_PARAM_KEY = {
    "rolling_mad_z": "rolling_mad_z",
    "rolling_iqr": "rolling_iqr",
    "stl_resid_z": "stl_resid_z",
    "rules.static_threshold": "rules.static_threshold",
    "rules.pct_jump": "rules.pct_jump",
    "rules.missing_run": "rules.missing_run",
    "rules.zero_run": "rules.zero_run",
    "rules.cusum": "rules.cusum",
}


def verdict_for(rule_id):
    """规则 -> 等级；未知规则说明器官自己的表坏了，直接抛（不是静默 warn）。"""
    try:
        return VERDICT_BY_RULE[rule_id]
    except KeyError:
        raise ValueError("器官规则表未登记这条规则的等级：%s" % (rule_id,))