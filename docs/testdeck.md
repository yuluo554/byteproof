# 器官 `testdeck`

> 来源：迁自 target-map ② 行（旧仓 `10-19-testdeck`，**Python 源**，v0.1.1，终端工作台）。
> 迁入版本：`1`。契约见 [`byteproof.md`](byteproof.md)；本页只写这个器官自己的那一列。

一句话：**跨 run 的测试历史判定层**——JUnit 解析（四原因码 + 四降级 + 框架三态 + 身份键）、
入库幂等（同身份不新增行）、四类分型（精确 `Fraction`；零计数不判 stable）、p50/p95 线性插值
与回归三态（**判不了 ≠ 无回归**）、两次 run 的 diff 三类（`fixed` 必须 `after==pass`）、
失败优先树与 summary 六字段、门禁退出码、呈现降级两条。

**SQLite 读写与 CLI/TUI/导出留输入层与宿主**（D1 逐文件处置见 §6.2）：账本在内存行集合
（runs / suites / cases / occurrences）上重算，不碰磁盘、不读时钟。旧仓"精确有理数、禁 float"
的纪律原样保留：阈值以十进制字符串存 `spec`，取用时转 `Fraction`。

## 1. 输入（工件）

`mode` 必填 ∈ `junit` / `ingest` / `flaky` / `slow` / `diff` / `views` / `gate`（缺省 `views`）。

| 模式 | subject 键 | 说明 |
|---|---|---|
| `junit` | `xml` 或 `bytes_b64` + `file_name` / `display_path` | 单文件解析：元素重数 / 四态 / 降级 / 原因码 / 框架 |
| `ingest` | `files[]`（每项 `xml` 或 `bytes_b64` + `display_path`）+ 可选 `existing_facts` / `missing_paths` | 一批产物 → run 分组 → 内存 upsert → 摘要行 |
| `flaky` | `histories[]`（`{case_id, name, series:[[run,status],…], rules?}`） | 四类分型 + 精确比率 |
| `slow` | `cases[]`（`{case_id, …, timings:[ms|null], split, rules?}`） | p50/p95 + 回归三态 + 样本量降级 |
| `diff` | `rows[]`（`{case_id, status_before, status_after}`） | 三类 + 兜底桶 |
| `views` | `facts`（runs / suites / cases / occurrences）+ `run_id` / `window` | 树 / summary / 矩阵 / 慢画像 / 与上一棒 diff |
| `gate` | `fail_on` ∈ `flaky`/`new-failures`/`regressions` + 对应模式的入参 | 门禁命中即 error（退出码 1） |

行集合的字段与旧仓四表同名（`run_id` / `suite_id` / `case_id` / `status` / `time_ms` …）；
`status` ∈ `pass`/`fail`/`skip`/`missing`，缺行用 `None` 而不是造状态。

## 2. 判定与等级

| 判定面 | 判什么 | verdict |
|---|---|---|
| `td-junit-file-reason` | 文件级原因码：`bad_xml` / `bad_encoding` / `no_testsuite` / `unreadable`（该文件未入库） | **error** |
| `td-junit-degraded` | 单项降级：`bad_time`（→`None`，不补 0）/ `missing_name`（不落库但计入重数）/ `started_at_missing` / `bad_commit` | warn |
| `td-junit-framework` | 框架三态：`pytest` / `gotestsum` / `playwright` / `unknown`（不猜） | info |
| `td-flaky-label` | 四类：`broken`（rate=1）/ `stable`（rate=0）/ `flaky`（0.05≤rate≤0.95 且 transitions≥3）/ `watch`（**窗口不足或零计数**） | info |
| `td-slow-regression` | `ratio≥1.2` **且** `delta≥200ms`（边界计入）；`None` = 判不了（`missing_window`/`undefined_base`） | info |
| `td-slow-sample-label` | `insufficient_history`（0 样本或某侧空）/ `single_sample`（1 样本） | warn |
| `td-diff-class` | `new-failures` / `fixed`（**必须 after==pass**）/ `still-failing` / `unchanged` | info |
| `td-ingest-missing` | 路径不存在（输入层列出） | **error** |
| `td-gate` | `--fail-on` 命中（new-failures / flaky / regressions） | **error** |
| `td-tree-order` / `td-view-summary` / `td-diff-summary` / `td-flaky-summary` / `td-slow-summary` / `td-ingest-report` | 排序与计数摘要（形状面） | info |
| `td-view-degrade` / `td-keys-single-source` / `td-store-upsert` | 降级阈值 / 键位单点 / upsert 幂等 | info |

**不静默**：文件级原因码逐条 error；`skipped_reasons` / `degraded_counts` 进 `td-ingest-report`
evidence；`None`（判不了 / 没得数）一律写出来，不当 0、不当 False。

**位置**：`file` / `degraded:<reason>` / `skipped:<reason>` / `missing:<path>` / `case:<id>` /
`sample:<id>` / `tree:<suite_id>` / `slow:<id>` / `diff:<id>` / `gate:<fail_on>` / `report`；
重复 id 自动加 `#n` 消歧。

## 3. 输出

```console
$ byteproof check testdeck --input samples/testdeck.minimal.json
byteproof :: testdeck 1 :: testdeck.minimal.json
[info] td-diff-class — 分类 unchanged（pass→pass） :: diff:1 (td-diff-class@1)
[info] td-diff-class — 分类 new-failures（pass→fail） :: diff:2 (td-diff-class@1)
[info] td-diff-summary — diff 计数：new-failures=1, fixed=0, still-failing=0, unchanged=1 :: report (td-diff-summary@1)
[info] td-slow-regression — 回归命中：test_slow（ratio=14/9(>=) delta=500ms(>=)） :: slow:1 (td-slow-regression@1)
[info] td-summary — testdeck 汇总（views 模式）：7 条记录，阻断 0 条 :: report (td-summary@1)
[info] td-tree-order — suite pytest：失败 1 / 用例 2 :: tree:2 (td-tree-order@1)
[info] td-view-degrade — 呈现降级：单栏阈值 80 列 / 无颜色按 NO_COLOR 与 tty :: view (td-view-degrade@1)
[info] td-view-summary — summary：total=2, fail=1, skip=0, flaky=0, broken=0, slow=1 :: summary (td-view-summary@1)
合计 8 条，阻断 0 条（error=0 warn=0 info=8）
```

退出码：旧仓 0 达标 / 1 门禁触发 / 2 用法错误 / 3 依赖缺失 / 4 未实现（M0）。账本侧
0 无阻断 / 1 有 error（文件级原因码、缺失入参、门禁命中）/ 2 输入不合法 / 3 契约违约。

## 4. 参数

规则包三份（旧仓 `src/testdeck/rules/*.json`）逐键镜像到 `spec`：

| 包 | 键 |
|---|---|
| `flaky` | `min_fail_rate="0.05"` / `max_fail_rate="0.95"` / `min_transitions=3` / `min_runs_for_flaky=2` / `fallback_label="watch"` / `labels` |
| `slow` | `slow_ms=1000` / `regression_ratio="1.2"` / `regression_delta_ms=200` / `waterfall_width=40` / `p50="0.50"` / `p95="0.95"` |
| `view` | `sparkline_runs=20` / `min_width_single_column=80` / `summary_fields` 六字段 / `tree_sort` / `formats` / `fail_on` / `json_indent=2` / `write_generated_at=false` |

`testdeck.thresholds.json` 是上述三份 + 四态 / 字形 / 退出码 / 原因码 / 键位的**快照**
（测试双向断言逐键相等）。单用例可用 `rules` 覆盖个别键（测试与调用方口径实验用）。

## 5. 依据包

`src/byteproof/data/testdeck.basis.json`：**19 条**（文件原因码 / 四降级 / 框架 / 四类分型 /
两个分型与慢测试摘要 / 回归三态 / 样本量降级 / diff 三类与计数 / ingest 摘要与缺失入参 /
失败优先树 / summary / 门禁 / 呈现降级 / 键位单点 / upsert 幂等 / 账本汇总）。
漏 basis → rc 3。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 **22 文件** pytest 实跑 **X = 332 passed**（`332 passed in 15.98s`）+ Go fixture **3 条 Test pass 事件**（1 skip / 1 故意失败，`go test` rc 1）→ **X = 335** / 新仓实跑 **346 passed** | ✅ 过（346 ≥ 335；两段分别记） |
| 2 | README 示例命令 rc 相同 | 旧 `py -3.12 -m testdeck ingest <pytest/gotestsum/playwright fixtures> --db %TEMP%/td-demo.db` → rc **0**，摘要行 `ingest: files=3 runs=1 cases=18 occurrences=18 skipped=0 framework=gotestsum,playwright,pytest`；新 `check testdeck`（ingest 模式，同三份产物）→ rc **0**，**摘要行逐字节相同** | ✅ 过（0=0，摘要行一致） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **2 文件** / 旧 **22 文件**；函数数**按条计** → 新 **346**（AST `test_`）/ 旧 **276**（22 文件 AST `test_`）+ Go **5**（`Test*`）= **281** | ✅ 过（346 ≥ 281） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`testdeck.basis.json`（7158 B / 19 条）+ `.thresholds.json`（4127 B）在包内；wheel 总条目 **250**；解包 `list` = **25 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>   # 10-19-testdeck（只读）
PYTHONPATH=src py -3.12 -m pytest tests/test_db.py tests/test_demo_gif.py tests/test_diff.py \
  tests/test_exit_codes.py tests/test_flaky.py tests/test_framework.py tests/test_identity.py \
  tests/test_ingest.py tests/test_junit.py tests/test_keys_single_source.py tests/test_layering.py \
  tests/test_manifest_coverage.py tests/test_model.py tests/test_no_network.py \
  tests/test_no_rule_literals.py tests/test_paths.py tests/test_queries.py tests/test_readme_gate.py \
  tests/test_rules.py tests/test_slow.py tests/test_tui_pilot.py tests/test_view.py \
  -o addopts="" -q -p no:cacheprovider
```

输出原文（py 3.12.10）：

```
332 passed in 15.98s
```

逐文件 pass 数（22 文件）：`db 12` / `demo_gif 9` / `diff 24` / `exit_codes 20` / `flaky 26` /
`framework 9` / `identity 8` / `ingest 21` / `junit 28` / `keys_single_source 7` /
`layering 6` / `manifest_coverage 1` / `model 17` / `no_network 6` / `no_rule_literals 9` /
`paths 11` / `queries 22` / `readme_gate 8` / `rules 11` / `slow 34` / `tui_pilot 15` /
`view 28` = **332**。

**Go 段（单列，按队列要求）**：

```
cd <来源仓>/bench/fixtures/gotestsum
GOCACHE=%TEMP%/gocache-testdeck GOPATH=%TEMP%/gopath-testdeck \
  $(go env GOROOT 由 PATH 提供) go test -v -count=1 ./...
```

输出原文（go1.24.5 windows/amd64）：

```
=== RUN   TestAdd
--- PASS: TestAdd (0.00s)
=== RUN   TestDivByZero
--- PASS: TestDivByZero (0.00s)
=== RUN   TestIsEven
--- PASS: TestIsEven (0.00s)
=== RUN   TestNotImplementedYetSubtract
--- SKIP: TestNotImplementedYetSubtract (0.00s)
=== RUN   TestDeliberateFailureFixture
--- FAIL: TestDeliberateFailureFixture (0.00s)
FAIL	example.com/demo-lib	0.803s
```

退出码 **1**（fixture 故意留一条失败）；**X 只计 `Test` 非空的 pass 事件 = 3**
（`TestAdd` / `TestDivByZero` / `TestIsEven`；包级 `PASS`/`FAIL` 行不计，skip 与故意失败不计）。
GOCACHE/GOPATH 全部定向 `%TEMP%`，来源仓 `git status --porcelain` 全程 **0 行**
（HEAD `14527f0` 与队列一致）。

> **D1 机械口径（22 文件）**：旧仓 `tests/` 共 **30** 个 `test_*.py`（另有 `conftest.py`），
> 按文件名正则（`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|
> generat|docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`）
> 剔除 **8** 件（逐词见 §6.2）→ **30 − 8 = 22 文件**进分母。旧层 AST `test_` 函数 **276**
> （22 文件 ast 计数）；Go fixture 的 `Test*` **5**（3 pass + 1 skip + 1 故意失败）。
> **Go 段路径含 `bench`**：按路径正则会被剔；队列（用户工单）明确要求"Go 那 1 条按测试框架
> 实跑、两段都要记"，故**单列为一段**并如实标注路径词，不与 22 文件混合计数。

### 6.2 D1+D18 逐文件处置表（判定层 22 文件 / 旧层 276 函数）

| 旧仓测试文件 | 命中词 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|---|
| `test_db.py`（12） | — | **已迁（判定面）** | 四表 upsert 幂等语义 → `facts.Store`（内存行集合）；SQLite 读写留输入层。 |
| `test_demo_gif.py`（9） | — | **已迁（形状面）** | GIF 录屏产物（帧数/时长确定性）属旧仓工具面；账本等价物 = 输出确定性（同输入两次字节一致）。 |
| `test_diff.py`（24） | — | **已迁（判定全）** | 三类 + 兜底桶 + `fixed` 必须 after==pass + 缺行不等于任何状态。 |
| `test_exit_codes.py`（20） | — | **已迁（判定面）** | 0/1/2/3/4 常量与门禁命中语义（`td-gate`）。 |
| `test_flaky.py`（26） | — | **已迁（判定全）** | 分母只含 pass/fail、transitions 跳过 skip/missing、两条降级、分型顺序。 |
| `test_framework.py`（9） | — | **已迁（判定全）** | 三态识别 + 线索短路顺序 + `unknown` 不猜。 |
| `test_identity.py`（8） | — | **已迁（判定全）** | 两条身份键的单点定义与校验（40 位小写十六进制、空串表未知）。 |
| `test_ingest.py`（21） | — | **已迁（判定面）** | run 分组（三元组只从 XML 读）、摘要行、skipped/degraded 计数；路径发现（glob）留输入层。 |
| `test_junit.py`（28） | — | **已迁（判定全）** | 元素重数 / 四态 / 失败字段 / 毫秒 / 四降级 / 四原因码 / 命名空间。 |
| `test_keys_single_source.py`（7） | — | **已迁（形状面）** | 键位表单点（`BINDINGS`/`KEYS`/`description_for`）与"别处不写字面量"的架构断言。 |
| `test_layering.py`（6） | — | **已迁（形状面）** | 依赖方向（判定层不 import 编排层/呈现层）→ 本仓模块切分与架构断言（无 IO/time 导入）。 |
| `test_manifest_coverage.py`（1） | — | **已迁（形状面）** | 打包清单覆盖 → 判据 4 的进包清单（basis + thresholds 在包内）。 |
| `test_model.py`（17） | — | **已迁（判定全）** | 四态 / 字形 / ROUND_HALF_UP 毫秒 / 精确有理数渲染 / 0/0 无定义。 |
| `test_no_network.py`（6） | — | **已迁（形状面）** | 无网络/无遥测 → 器官零网络（本仓架构断言：无 socket/requests 导入）。 |
| `test_no_rule_literals.py`（9） | — | **已迁（形状面）** | 规则字面量扫描 → thresholds 快照双向断言 + 模块常量单点。 |
| `test_paths.py`（11） | — | **已迁（判定面）** | 正斜杠归一 / 相对扫描根 / 跨盘符回落 / `--db` 空值不静默；`$XDG_DATA_HOME` 由调用方给（不读 env）。 |
| `test_queries.py`（22） | — | **已迁（判定全）** | 失败优先排序单点 / suite 组内 suite_id / summary 六字段 / 矩阵行序 / 窗口中点切分 / diff 原始状态对。 |
| `test_readme_gate.py`（8） | — | **已迁（形状面）** | README 数字 ↔ 实测一致性属旧仓文档装订；本仓由判据 2 摘要行对账 + 测试计数断言承担。 |
| `test_rules.py`（11） | — | **已迁（判定面）** | 规则包校验（缺键即错、密钥域、`write_generated_at=false` 强制）+ 十进制阈值精确性。 |
| `test_slow.py`（34） | — | **已迁（判定全）** | 线性插值分位 / 缺失剔除 / 回归三态 / 样本量降级 / 瀑布条整数四舍五入。 |
| `test_tui_pilot.py`（15） | — | **已迁（形状面）** | Textual Pilot（按键导航）留宿主；纯函数侧的降级两条（单栏/无颜色）与键位表已迁。 |
| `test_view.py`（28） | — | **已迁（判定面）** | 降级两条 / markup 转义与剥离 / 耗时 `—` / sparkline 只画计数项 / summary `None` 不冒充 0。 |
| `test_bench_refimpl.py`（28） | **bench** | 剔除 | 参照实现逐值对账（基准侧不得 import 生产模块）——基准工具面。 |
| `test_bench_suites.py`（40） | **bench** | 剔除 | 四套件基准运行器（`bench/run_all.py`）——工具面。 |
| `test_bench_synth.py`（23） | **bench** | 剔除 | 合成语料生成器——旧仓数据装订。 |
| `test_export.py`（26） | **export** | 剔除 | 导出（md/json）渲染与格式——宿主报告层。 |
| `test_export_determinism.py`（7） | **export** | 剔除 | 导出逐字节一致——渲染层；账本侧由 `test_report_deterministic` 承接。 |
| `test_report_model.py`（8） | **report** | 剔除 | 报告模型（summary/总计结构）——宿主报告层。 |
| `test_selftest.py`（13） | **selftest** | 剔除 | 自检命令（`selftest`）——CLI 面。 |
| `test_version_pointer.py`（6） | **version** | 剔除 | 版本指针一致性——打包面由本仓 `pyproject`/wheel 承接。 |

被剔除 8 件实跑合计 **151 pass**（28+40+23+26+7+8+13+6）；30 文件 = 22 判定层 + 8 剔除，
旧仓全量 `pytest tests` = 332 + 151 = **483 passed**。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/testdeck.basis.json` | 7158（19 条） |
| `byteproof/data/testdeck.thresholds.json` | 4127 |

wheel 总条目 **250**（#40 收口 241 + 本器官 9 件：`auditors/testdeck/` 7 个 .py + data 2 件）；
解包 `list` = **25 器官**、仓样例 `check` rc **0**（views 样例无 error 级 finding——
判定内容为 diff/flaky/slow 的 info 记录）。构建树来自暂存区 tree 对象（`git write-tree`），
**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **SQLite 读写 → 输入层**（`db.py`）：器官在内存行集合上重算；upsert 幂等语义移植为
   `facts.Store` 的 dict 更新（同 run 三元组 / 同用例身份不新增行，同 (run,case) 覆盖）。
2. **CLI / TUI / 导出 → 宿主**（D1 排除词 `cli` / `export` / `report`）：`argparse` 面、
   Textual 三栏、md/json 渲染均不迁；判定与计数逐条进账本（summary 六字段、矩阵、慢画像）。
3. **文件发现（glob）→ 输入层**：旧仓 `discover` 的目录展开与去重不迁；`ingest` 模式收
   **产物内容清单**（每项带 `display_path`），路径不存在由调用方经 `missing_paths` 显式列出。
4. **时钟**：旧仓 `ingested_at` 是唯一读时钟处（元数据，不进导出/diff）；器官**不读时钟**，
   `Store` 把该字段留空，由调用方需要时补。
5. **XML 安全护栏（新增，非旧仓行为）**：旧仓直接 `ET.iterparse` 不可信产物；本器官解析前
   拒绝 `<!DOCTYPE` / `<!ENTITY`（`detail=dtd_forbidden`）并限制输入 8 MiB（`detail=oversize`）——
   **实体扩展面显式关掉**。这是对旧仓的加严，不改变正常产物的判定。
6. **`test_tui_pilot` 的机械计入**：按文件名正则它不含排除词（`tui`/`pilot`），故计入 X；
   但其判定主体是 Textual 按键导航（宿主面）。处置表如实写"形状面：纯函数侧降级两条 +
   键位表单点已迁，Pilot 本体留宿主"。
7. **Python GBK/编码面**：`bad_encoding` 只在字节输入可达（文本输入已解码）；XML 声明编码
   用 Python codec 严格解码（旧仓 `codecs` 增量解码同语义）。
8. **树/矩阵/慢画像的承载层**：旧仓经 SQL 取数（`ORDER BY` 在 SQL 里）；账本在行集合上用
   **同一套排序键**重算（失败优先 `(fail_count>0, secondary)`；矩阵 `-flaky_score, identity`；
   慢行 `-time_ms, identity`）。判定内容一致，取数层不同。
9. **`summary` 的 `None` 面**：`fields` 里出现未实现的键时账本保留 `None`（不猜 0）；
   旧仓 M5 起六字段全实装，本器官同。