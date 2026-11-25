# 器官 `timeseries-anomaly`

> 来源：迁自 target-map ② 行（旧包 `anomaly_atlas`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)，
> 本页只写**这个器官自己的那一列**：它吃什么、按什么判、吐出来长什么样。

一句话：**把一份时序长表当工件审，落一张带规据的缺陷账本。**
搬过来的是判定，不是工具 —— 旧仓的 CLI、单文件 HTML 标注图、Node 复算镜像、
报告数字白名单、合成数据生成器全部留在旧仓（byteproof 的器官不许自带 CLI/排版/文件 IO）。

## 1. 输入（工件）

一份 JSON 长表。`series_id` 可省（缺省 / 空白都落到 `params.default_series_id`），
`value` 为 `null` 表示**缺失**。

```json
{
  "rows": [
    {"timestamp": "2024-03-01T00:00:00Z", "series_id": "temperature", "value": 12.4},
    {"timestamp": "2024-03-01T00:05:00Z", "series_id": "temperature", "value": null}
  ],
  "params": {}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `rows[].timestamp` | 是 | `YYYY-MM-DD[T ]HH:MM[:SS[.f{1,9}]][Z\|+HH:MM\|+HHMM\|+HH]`；亚秒位**截断**到毫秒；不存在的民用日期（`2024-02-30`）拒绝 |
| `rows[].value` | 是 | 有限十进制数，或 `null` / `""` / `NA` / `N/A` / `NaN` / `null` / `none` / `-` / `--`（= 缺失）；`inf`/`nan`/布尔/千分位/十六进制一律拒绝 |
| `rows[].series_id` | 否 | 字符串或整数；空白 -> 缺省序列 |
| `params` | 否 | 旧仓 run-spec 的同名字段（见 §4），未知键 -> 退出码 2 |

**行号 = 该行在 `rows` 里的 1 基下标**，是账本 `path` 与 `evidence` 里唯一的工件内坐标。

`value` 键必须显式存在：`{"value": null}` 是"这里是缺失"，`{}` 是"这份工件没说"，后者是信封错误。

## 2. 判定顺序与等级

四段，每段只回答一个问题。等级是 byteproof 的账本语义（`error` 阻断 / `warn` 记录 / `info` 留痕），
不是旧仓的"离散程度"。

| 段 | 规则 | 等级 | 判据（依据包里的原文见 §5） |
|---|---|---|---|
| 1 行级 | `ts-timestamp-unreadable` | `error` | 时间戳不合 §1 的语法 / 日期不存在 |
| 1 行级 | `ts-value-invalid` | `error` | 值不是有限十进制数 |
| 2 时间轴 | `ts-duplicate-timestamp` | `error` | 同一序列重复时间戳数 > `duplicate_timestamp_max`（默认 1） |
| 2 时间轴 | `ts-non-monotonic` | `error` | 同一序列时间倒退步数 > `non_monotonic_max`（默认 0） |
| 3 形状 | `ts-gap` | `warn` | 相邻间隔 > `gap_factor`×主间隔（默认 3） |
| 3 形状 | `ts-irregular-cadence` | `info` | 非主间隔数（扣除已按断档落账的）> 0，比率以 ppm 计 |
| 4 信号 | `ts-rolling-mad-z` | `warn` | 尾随窗 median/MAD 稳健 z > `k`（默认 3.5） |
| 4 信号 | `ts-rolling-iqr` | `warn` | 尾随窗 IQR 箱界越界（默认 `iqr_mult=3.0`） |
| 4 信号 | `ts-stl-resid-z` | `warn` | STL 残差再走同一套稳健 z |
| 4 信号 | `ts-static-threshold` | `warn` | `\|value\| > static_threshold`（默认 `null` = 该规则整条不参与） |
| 4 信号 | `ts-pct-jump` | `warn` | `\|current÷previous − 1\| > pct_jump`（默认 0.35；前驱为 0 时沉默） |
| 4 信号 | `ts-missing-run` | `info` | 连续缺失 ≥ `missing_run`（默认 6），段长即分数 |
| 4 信号 | `ts-zero-run` | `info` | 连续零值（含 `-0.0`）≥ `missing_run`，段长即分数 |
| 4 信号 | `ts-cusum` | `warn` | 差分上的两侧 CUSUM：任一侧 > `cusum_h`（默认 5.0） |

**为什么重复时间戳/时间倒序是 `error` 而不是 `warn`**：这两件事让时间轴不可信，
而时间轴是其余每一条判定的坐标系；在这个前提下产出的"干净"结论没有意义。
但它们仍是**工件缺陷**（账本里的 `error`，退出码 1），不是**信封缺陷**（退出码 2）——
分界线是：`rows` 不是数组、行不是对象、`timestamp`/`value` 键缺失 = 信封（2）；
行读不出时间戳或值 = 缺陷（1）。

### 信号 → 段（episode）

同一检测器的命中点按**时间域**合并：相邻命中时间戳相距 ≤ `max_gap_ms`（默认 1 800 000）即同一段。
不按点数距离合并 —— 断档的语义是"这里没有样本"，不是"这里什么都没发生"。
段内峰值分数定点化到 6 位小数存成整数（`peak_score_q`），账本里**不出现原始 float**。

## 3. 输出

人读（默认）：

```console
$ byteproof check timeseries-anomaly --input samples/timeseries-anomaly.minimal.json
byteproof :: timeseries-anomaly 1 :: timeseries-anomaly.minimal.json
[warn] ts-cusum — CUSUM 累计偏移超阈（cusum_k=0.500000, cusum_h=5.000000）：峰值分数 73.019493，2 个点，时长 300000 ms :: series@2024-03-01T00:25:00.000Z..2024-03-01T00:30:00.000Z (ts-cusum@1)
[warn] ts-cusum — CUSUM 累计偏移超阈（cusum_k=0.500000, cusum_h=5.000000）：峰值分数 29.402424，2 个点，时长 600000 ms :: series@2024-03-01T02:00:00.000Z..2024-03-01T02:10:00.000Z (ts-cusum@1)
[warn] ts-gap — 采样断档：第 7 行与第 8 行相距 4500000 ms（主间隔 300000 ms 的 15 倍），缺 14 个点 :: series@2024-03-01T00:30:00.000Z..2024-03-01T01:45:00.000Z (ts-gap@1)
[warn] ts-pct-jump — 相邻点百分比跳变超阈（pct_jump=0.350000）：峰值分数 2.496183，2 个点，时长 300000 ms :: series@2024-03-01T00:25:00.000Z..2024-03-01T00:30:00.000Z (ts-pct-jump@1)
[warn] ts-pct-jump — 相邻点百分比跳变超阈（pct_jump=0.350000）：峰值分数 1.000000，1 个点，时长 0 ms :: series@2024-03-01T02:00:00.000Z..2024-03-01T02:00:00.000Z (ts-pct-jump@1)
[warn] ts-rolling-iqr — 滚动 IQR 箱界越界（window=24, iqr_mult=3.000000）：峰值分数 12.843750，2 个点，时长 300000 ms :: series@2024-03-01T02:00:00.000Z..2024-03-01T02:05:00.000Z (ts-rolling-iqr@1)
[warn] ts-rolling-mad-z — 滚动 median/MAD 稳健 z 超阈（window=24, k=3.500000, 周期 1 点）：峰值分数 25.437937，2 个点，时长 300000 ms :: series@2024-03-01T02:00:00.000Z..2024-03-01T02:05:00.000Z (ts-rolling-mad-z@1)
合计 7 条，阻断 0 条（error=0 warn=7 info=0）
```

`--json`（机器可读、确定性、无时间戳/绝对路径）：

```json
{
  "id": "ts-gap@series@2024-03-01T00:30:00.000Z..2024-03-01T01:45:00.000Z",
  "rule_id": "ts-gap",
  "verdict": "warn",
  "message": "采样断档：第 7 行与第 8 行相距 4500000 ms（主间隔 300000 ms 的 15 倍），缺 14 个点",
  "basis_ref": {
    "rule_id": "ts-gap",
    "rule_version": "1",
    "source": "迁自 target-map ② 行 · data/README.md §4.1（采样网格与断档）",
    "quote": "主间隔取最常见的正间隔（并列取最短）……"
  },
  "path": "series@2024-03-01T00:30:00.000Z..2024-03-01T01:45:00.000Z",
  "evidence": {
    "prev_row": 7, "row": 8,
    "prev_ms": 1709253000000, "ms": 1709257500000,
    "interval_ms": 4500000, "dominant_interval_ms": 300000,
    "missing_points": 14, "gap_factor": 3
  }
}
```

`path` 的两种形态：

| 形态 | 用于 | 例子 |
|---|---|---|
| `<series_id>#row=<n>` | 单行缺陷 | `temperature#row=42` |
| `<series_id>#cadence` | 每序列一条 | `temperature#cadence` |
| `<series_id>@<起>..<止>` | 区段缺陷（断档 / 信号段） | `series@2024-03-01T00:25:00.000Z..2024-03-01T00:30:00.000Z` |

## 4. 参数（`params`）

全部有默认值；未知键直接 `ValueError` -> 退出码 2。字段名与旧仓 run-spec 一致，
所以旧的 `--spec` 文件内容可以原样搬进 `params`。

| 键 | 默认 | 说明 |
|---|---|---|
| `rolling_mad_z.window` / `.k` / `.min_valid` | 24 / 3.5 / 6 | 尾随窗（含被判点） |
| `rolling_iqr.window` / `.iqr_mult` / `.min_valid` | 24 / 3.0 / 6 | 同上 |
| `stl_resid_z.inner` / `.outer` / `.window` / `.k` / `.min_valid` | 2 / 1 / 24 / 3.5 / 6 | 内/外循环轮数 |
| `rules.static_threshold` | `null` | 给了才启用 |
| `rules.pct_jump` | 0.35 | |
| `rules.missing_run` | 6 | 缺失段**与**零值段共用 |
| `rules.cusum_k` / `.cusum_h` | 0.5 / 5.0 | |
| `max_gap_ms` | 1800000 | 段合并的时间域阈值 |
| `period_points` | `null` | 给了就声明，不给就估（撑不起周期时 `1`） |
| `period_reject_window` / `.period_reject_sigma` | 121 / 2.5 | 周期估计的清洗窗与拒绝尺度 |
| `duplicate_timestamp_max` / `non_monotonic_max` | 1 / 0 | 每序列容差 |
| `gap_factor` | 3 | 断档倍数 |
| `timezone_offset_min` | 0 | 无偏移时间戳的声明时区 |
| `default_series_id` | `"series"` | |
| `escalate_score_q` | `null` | 给了就把定点峰值 ≥ 它的信号段从 `warn` 升为 `error`（阻断） |

阈值表与规则包的落盘台账分别是
`src/byteproof/data/timeseries-anomaly.thresholds.json` 与
`...basis.json`；运行期常量必须与它们逐项相等（`tests/test_timeseries-anomaly.py::TestShippedTables`）。

## 5. 依据包

规则包的随包副本：`src/byteproof/data/timeseries-anomaly.basis.json`（14 条规则，包版本 `1`）。

```console
$ byteproof check timeseries-anomaly --input <工件>                    # 用随包规则包
$ byteproof check timeseries-anomaly --input <工件> --basis <规则包>    # 用指定规则包
```

给了 `--basis` 就**只**用它；规则包里缺某条规则且判定要用到它 -> `RuleMissing` -> 退出码 **3**
（不是"跳过这条规则"）。规则包自身缺 `version` -> 同样退出码 3。

## 6. 已知边界（继承自旧仓，逐条实测过）

1. **无周期序列上 STL 端点偏保守**：`period_points=1` 时季节项退化成均值，残差只剩 LOESS 趋势的
   端部偏差，所以一条纯线性斜坡会在两端各报一次 `ts-stl-resid-z`。
   旧仓同一条输入同两个点（`3.912046` / `8.093889`），本轮**照搬不改** —— 测这条是为了钉住
   "这是继承行为，不是新缺陷"，改它需要主对话拍板（改检测算术 = 改器官口径）。
2. **时间倒序会造出"怪间隔"**：行序就是采样序，一行倒退会让其后一个间隔变成负/超长，
   于是可能同时看到 `ts-non-monotonic`（error）和 `ts-gap`（warn）。这是有意的：
   两条结论说的不是同一件事（"时间轴坏了" vs "这里缺了样本"）。
3. **断档与不规则采样不重复记账**：主间隔之外的间隔先按断档落账，剩下的才计入
   `ts-irregular-cadence` 的 `off_grid_intervals`。

## 7. §7.3 四项无损判据 · 实测值与差异原因

口径：`ORGAN-PLAYBOOK` §3.0 —— **判据 1 的分母 = 旧仓「判定层」实跑用例数**。
判定层 = 文件名不匹配 `cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke`
的测试文件。旧仓该层 = **13 个文件 / 462 静态函数**，实跑 **X = 551 passed**。
实测环境：Windows 10.0.26200 x64 / CPython 3.12.10 / pytest 8.4.2；两仓均无 venv，一律 `PYTHONPATH=src`。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓判定层实跑 X = 551 / 新仓实跑 N = 1469 / 结论：过（差 +918）** | ✅ |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文命令 `profile data/samples/minimal.csv` / `detect data/samples/minimal.csv` 实跑 rc **0 / 0**；新入口 `check timeseries-anomaly --input samples/timeseries-anomaly.minimal.json` rc **0** | ✅ 过（失败路径见下） |
| 3 | 测试文件数 / 测试函数数 | **口径乙（2026-11-25 用户裁决）**：文件数**按域计** → 新 **2 文件**（`tests/test_timeseries-anomaly.py` 267 函数 / 910 用例 + `tests/test_timeseries_anomaly_extra.py` 51 函数 / 559 用例；增量文件原名 `test_timeseries_anomaly.py`，2026-11-25 已改名，避免与连字符文件同名混淆）/ 旧判定层 13 文件；函数数**按条计（AST）** → 新 **318** / 旧 **462** | ⚠️ **waiver**：函数数 318 < 462（缺口 144）。用户 2026-11-25 批准；理由：判据 1 用例数 **1469 ≥ 551** 已过；残余风险：函数级断言粒度变粗，回归定位需读用例参数。归档 `records/criterion-verdicts-20261125.md` |
| 4 | `pip wheel` 后 `data/` 进包 | wheel 内 `byteproof/data/` **2 个文件**（basis 6416 B + thresholds 1313 B）；装到中立目录后 `check` 仍 rc **0** | ✅ 过 |

> 判据 3 的"文件数/函数数"与 SKELETON-SPEC §1「每器官一个 `tests/test_<slug>.py`」直接冲突（旧层 13 个文件 / 462 个函数）。
> 轨AD 选定**口径乙（功能）**：文件数按域计、函数数按条计；**实跑用例数**由判据 1 承担。
> 本器官现状 = **2 文件 / 318 函数 / 1469 用例**；差旧层的 144 个 `def test_` 由 `@pytest.mark.parametrize`
> 矩阵承担（不是靠重复断言凑的），缺口已按用户 2026-11-25 裁决登记为 **waiver**，不冒充"已达标"。

### 7.1 脚手架测试处置表（旧仓被剔除的每个测试文件）

| 旧仓测试文件 | 函数数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_generator.py` | 39 | **舍弃**（不入判定层） | 测的是 `tools/gen_synthetic_series.py`（合成数据 + 真值生成器）。它是**夹具生产工具**，不是对工件的判定；byteproof 的器官不许读文件，也不负责造输入。生成器的冻结纪律由旧仓自己的 `--check` 守住；本器官改用 `samples/timeseries-anomaly.minimal.json`（手工可核对）+ 测试内联夹具。 |
| `test_selftest.py` | 16 | **舍弃**（不入判定层） | 测的是 `anomaly_atlas selftest` 子命令（六项自检 + 探针）。`selftest` 是旧仓的 CLI 面；SKELETON-SPEC §2 规定器官不得自带 CLI，byteproof 只有 `list` / `check` 两个子命令。同类职责在本仓由 `tests/test_timeseries-anomaly.py` 的 `TestShippedTables`（随包数据与常量一致）+ `TestNoClockNoSideEffects`（器官契约门）承担。 |

判定层内部、**有文件但不整文件迁**的两类，理由写在同一张表里（判据 1/3 的差值来源）：

| 旧仓测试文件 | 函数数 | 处置 | 理由 |
|---|---:|---|---|
| `test_render.py` / `test_layout.py` / `test_mirror.py` | 43 / 37 / 40 | 舍弃（非判定） | 单文件 HTML 排版、图形几何、Node 复算镜像 = 呈现层；器官不得自带输出排版。 |
| `test_report.py` / `test_facts.py` | 31 / 21 | 舍弃（非判定） | 报告数字白名单与报数台账 = 报告产物；byteproof 的落点是账本，不是报告。 |
| `test_skeleton.py` | 27 | 舍弃（非判定） | 旧仓仓库布局与发布门；本仓有 `tools/check_sprint_layout.py` 等自己的门。 |
| `test_csvio.py` / `test_profile.py` / `test_canon.py` | 41 / 33 / 21 | 部分迁 | 行级契约、形状规则、定点化已迁；CSV 文本读写、`profile.json` 装配、规范 JSON/哈希不迁（器官不读文件、不哈希）。 |

### 判据 2 的失败路径（口径差，已实测）

同一条"重复时间戳超出容差"的工件：

* 旧仓 `detect <csv>` -> 打印 `E_DUPLICATE_TIMESTAMP`，退出码 **2**（输入不合法）；
* 本器官 `check` -> 一条 `error` 账本，退出码 **1**（存在阻断性结论）。

这不是 rc 相同的反例，而是**两个产品对同一件事的分类不同**：旧仓把工件问题当"输入错误"，
byteproof 把工件问题当"缺陷"（信封问题才是 2）。已在 §2 写明分界线；若要改成 2，
需要先改 `SKELETON-SPEC §5` 的"输入不合法"定义。