# 器官 `fund-quarter-report`

> 来源：迁自 target-map ② 行（旧包 `funddiff`）。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把一份基金季报工件当字节工件审，落一张「这一季的持仓/经理/规模/正文/披露
哪里不可复核」的缺陷账本。** 搬过来的是判定（五态 diff + 双口径冲突 + 经理四类 +
规模六字段 + 合规扫描 + 披露窗口），不是抓取工具，也不是报告生成器。

## 1. 输入（工件）

```json
{
  "fund_code": "990001",
  "period": "2026Q3",
  "prev_period": "2026Q2",
  "holdings": {
    "prev": {"report_period": "2026Q2", "status": "ok", "rows": [
      {"stock_code": "600001", "ratio": "7.66"}
    ]},
    "cur": {"report_period": "2026Q3", "status": "ok", "rows": [
      {"stock_code": "600001", "ratio": "8.16", "change_type": "增持", "change_pct": "0.50"}
    ]}
  },
  "managers": [{"name": "样例经理甲", "change_date": "2026-08-15", "change_class": "in_period"}],
  "scale": {"report_period": "2026Q3", "subscribe": "1.20", "redeem": "0.80",
            "shares": "30.00", "net_assets": "45.00", "share_change_rate": "1.35%",
            "baseline": "available", "units_from_header": {"subscribe": "亿份", "net_assets": "亿元"},
            "source": "gmbd"},
  "report_text": "本季度持仓发生变化，详见明细。",
  "compliance_terms": ["保证收益"],
  "disclosure": {"metadata_available": true, "reports": [], "as_of": "2026-10-18"}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `period` / `prev_period` | `period` 是；`prev_period` 缺省 = 上一季 | `YYYYQn`；非法 -> 退出码 2 |
| `holdings.prev` / `holdings.cur` | 二者同时给或同时不给 | 已归一的持仓工件（旧仓 `funddiff/holdings@1` 的 `rows`/`status`/`report_period`） |
| `holdings.*.rows[].ratio` | 否 | 十进制字符串；`null` = 缺失（≠ 0）；非数字 = error |
| `holdings.*.rows[].change_type` | 否 | 上游变动标识（增持/减持/不变/新进/退出）；缺失只记 info |
| `holdings.*.status` | 否 | `ok` / `empty`（结构性空仓）/ `failed`（抓取失败）；失败季记 warn 并停止五态 |
| `managers` | 否 | 已解析的经理记录列表（或 `{"records": [...]}`）；`change_class` 缺省时按日期重算 |
| `scale` | 否 | 规模六字段对象；缺字段 / 单位 / 基准矛盾 -> error |
| `report_text` + `compliance_terms` | 否 | 报告正文与禁词表（词表由工件提供，器官不内置业务词表） |
| `disclosure` | 否 | `metadata_available` / `reports[]` / `as_of` / `rule` / `calendar` |
| `params` | 否 | `mode` / `threshold` / `disclosure_count` / `quarter_ends`（见 §4） |

工件是**已归一**的 JSON，不是东财/巨潮页面。抓取、HTML 表解析、配置包加载属于工具面，
器官不读文件、不联网、不读时钟。

## 2. 判定顺序与等级

| 段 | 规则 | 等级 | 判据 |
|---|---|---|---|
| 持仓 | `fq-duplicate-holding` | `error` | 同一季同一 `stock_code` 出现 ≥2 次（源按 dict 索引会静默覆盖） |
| 持仓 | `fq-ratio-invalid` | `error` | `ratio` 非 `null` 且不能被 `Decimal` 解析 |
| 持仓 | `fq-period-mismatch` | `error` | 快照 `report_period` ≠ 请求的报告期 |
| 持仓 | `fq-failed-quarter` | `warn` | 任一侧 `status=failed`（≠ `empty`） |
| 持仓 | `fq-ratio-missing` | `warn` | 任一侧 `ratio=null`，该证券五态记「待确认」 |
| 持仓 | `fq-invalid-code` | `warn` | `stock_code` 不是 6 位数字 |
| 持仓 | `fq-provider-conflict` | `warn` | 上游变动标识与两季占比自算结论不一致 |
| 持仓 | `fq-change-type-missing` | `info` | 该条目对应的持仓行没有上游变动标识 |
| 经理 | `fq-manager-label-drift` | `error` | `change_class` 与区间重算不一致 / 单条用 `none` / 日期不可解析 |
| 经理 | `fq-manager-unparsed` | `warn` | `change_class=unparsed`；附 `raw_text` + `sha256` 快照 |
| 规模 | `fq-scale-field-missing` | `error` | 六字段/基准/单位/来源缺键或 `baseline` 非法 |
| 规模 | `fq-scale-baseline-flow` | `error` | `baseline=no_prev_baseline` 时流量字段非 `null`（补 0） |
| 规模 | `fq-scale-unit-missing` | `error` | 表头单位缺 `subscribe` 或 `net_assets` |
| 规模 | `fq-scale-number` | `error` | 四个金额字段非 `null` 且不可解析 |
| 规模 | `fq-scale-rate` | `error` | `share_change_rate` 非 `null` 且不是 `-?\d+(\.\d+)?%` |
| 规模 | `fq-scale-source` | `error` | `source≠gmbd` 或 `raw_sha256` 非 64 位小写十六进制 |
| 正文 | `fq-compliance-term` | `error` | 命中禁词（NFKC + casefold + 空白折叠后子串匹配） |
| 披露 | `fq-disclosure-unverified` | `warn` | 所需年份日历未登记，截止日不可计算 |
| 披露 | `fq-disclosure-no-data` | `warn` | 官方元数据不可用（无数据 ≠ 待披露） |
| 披露 | `fq-disclosure-pending` | `info` | 本期报告尚未披露（含 `as_of` 回放未到发送日） |

五态判定（computed 口径）：

| 状态 | 条件 |
|---|---|
| 新进 | 本期有、上季无该代码 |
| 退出 | 上季有、本期无该代码 |
| 加仓 / 减仓 / 不变 | 两侧都有：`cur-prev > 0` / `< 0` / `|Δ| < threshold` |
| 待确认 | 两侧都有但任一侧 `ratio=null`（`insufficient_data`） |

provider 口径直接采信本期 `change_type`（增持→加仓、减持→减仓）与 `change_pct`；
两口径不一致的条目进冲突清单，**不静默合并、不猜谁对**。

## 3. 输出

```console
$ byteproof check fund-quarter-report --input samples/fund-quarter-report.minimal.json
byteproof :: fund-quarter-report 1 :: fund-quarter-report.minimal.json
[info] fq-change-type-missing — 该持仓行没有上游变动标识（provider 口径不可用，只按占比自算） :: holdings.cur.rows[3] (fq-change-type-missing@1)
[info] fq-change-type-missing — 该持仓行没有上游变动标识（provider 口径不可用，只按占比自算） :: holdings.cur.rows[4] (fq-change-type-missing@1)
[info] fq-change-type-missing — 该持仓行没有上游变动标识（provider 口径不可用，只按占比自算） :: holdings.cur.rows[5] (fq-change-type-missing@1)
[info] fq-change-type-missing — 该持仓行没有上游变动标识（provider 口径不可用，只按占比自算） :: holdings.prev.rows[3] (fq-change-type-missing@1)
[info] fq-disclosure-pending — 本期报告尚未披露（对待披露状态只留痕，不冒充已披露） :: disclosure.status (fq-disclosure-pending@1)
[warn] fq-invalid-code — 证券代码 'ABC123' 不是 6 位数字（这一行无法与另一季稳定对齐） :: holdings.cur.rows[5] (fq-invalid-code@1)
[warn] fq-manager-unparsed — 经理变更记录无法解析（unparsed 不是无变更） :: managers[1] (fq-manager-unparsed@1)
[warn] fq-ratio-missing — 持仓占比缺失（null ≠ 0，该证券只能记为待确认） :: holdings.cur.rows[4] (fq-ratio-missing@1)
[warn] fq-ratio-missing — 持仓占比缺失（null ≠ 0，该证券只能记为待确认） :: holdings.prev.rows[4] (fq-ratio-missing@1)
合计 9 条，阻断 0 条（error=0 warn=4 info=5）
```

样例的 `change_type` 缺失共 4 条 info：退出行看上一季，其余看本期，
与旧仓 `detect_anomaly` 的覆盖面一致。

`--json` 的单条账本：

```json
{
  "id": "fq-change-type-missing@holdings.cur.rows[3]",
  "rule_id": "fq-change-type-missing",
  "verdict": "info",
  "message": "该持仓行没有上游变动标识（provider 口径不可用，只按占比自算）",
  "basis_ref": {
    "rule_id": "fq-change-type-missing",
    "rule_version": "1",
    "source": "迁自 target-map ② 行 · 旧仓 diff.detect_anomaly(change_type_missing) / provider_status",
    "quote": "上游变动标识（PCTNVCHGTYPE）缺失时 provider 口径不可用……"
  },
  "path": "holdings.cur.rows[3]",
  "evidence": {"stock_code": "600005", "row_index": 3, "side": "cur", "status": "新进"}
}
```

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---|---|
| `mode` | `computed` | `computed` 两季占比自算 / `provider` 采信上游变动标识 |
| `threshold` | `"0.10"` | 十进制字符串；`|Δ| <` 它视为不变（必须 > 0） |
| `disclosure_count` | `15` | 季末次日起算的工作日数（法定期限） |
| `quarter_ends` | `{"Q1":"03-31",…}` | 四季季末月日；改它即改报告期区间 |

未知参数键 -> 退出码 2（不静默忽略）。阈值台账 `src/byteproof/data/fund-quarter-report.thresholds.json`
与运行期默认值逐项相等（测试钉住）。

## 5. 依据包

随包副本 `src/byteproof/data/fund-quarter-report.basis.json`（20 条规则，包版本 `1`）。
缺规则 -> `RuleMissing` -> 退出码 3。配置文件 `--basis` 优先，其次随包副本。

## 6. §7.3 四项无损判据 · 实测

口径：`D1 + D18` —— **判据 1 的分母 = 旧仓「判定层」实跑用例数**。判定层 = 文件名不匹配
`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`
的测试文件。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓 14 文件实跑 X = 184 passed** / 新仓实跑 **N = 293 passed** | ✅ 过（+109） |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文 `py -3.12 -X utf8 -m funddiff diff --period 2026Q3` 实跑 rc **0**（在 `%TEMP%` 副本里用 `--data-dir` 指向来源仓 `data/`，来源仓 0 改动）；新入口 `check fund-quarter-report --input samples/fund-quarter-report.minimal.json` rc **0** | ✅ 过（0 = 0；参数形态不同见 §7） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件**（容器数 ≠ 覆盖数）/ 旧 14 文件；函数数**按条计** → 新 **253**（AST）/ 旧 **167** | ✅ 过（253 ≥ 167） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 的暂存树（`git write-tree` + `git archive`）构建 `byteproof-0.1.0-py3-none-any.whl`（63 条目）；`byteproof/data/fund-quarter-report.basis.json` **9079B / 20 条规则** + `.thresholds.json` **1003B** 均在包内；解包 `list` = 4 器官、样例 rc 0 | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest \
  tests/test_compliance.py tests/test_config.py tests/test_diff.py tests/test_fetch.py \
  tests/test_fixtures.py tests/test_freeze_config.py tests/test_managers.py \
  tests/test_no_network.py tests/test_readme_gate.py tests/test_scale.py \
  tests/test_sentinels.py tests/test_serialize.py tests/test_store.py tests/test_window.py \
  -o addopts="" -q -p no:cacheprovider
```

输出：`184 passed in 19.74s`。来源仓 `git status --porcelain` = **0 行**，HEAD `61c8762` 与队列一致。

### 6.2 D1 + D18 逐文件处置表（判定层 14 文件 / 167 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_compliance.py` | 7 | **已迁（全）** | 禁词扫描（NFKC + casefold + 空白折叠 + 行号/摘录）在本器官 `compliance.py`；文件读取 `scan_files` 属工具面。 |
| `test_config.py` | 12 | **部分迁** | 本器官只校验 `params`（未知键/类型/阈值）并记 `ValueError`（rc 2）；配置包 schema / MANIFEST / 来源元数据属产品级门禁，不迁。 |
| `test_diff.py` | 14 | **已迁（判定全）** | 五态、Decimal、缺失 null、双口径冲突、失败季、排序、阈值来自参数均在 `holdings.py` + `audit.py`；CLI 退出码由 `tests/test_fund-quarter-report.py::TestCli` 覆盖。 |
| `test_fetch.py` | 25 | **舍弃** | 双通道抓取、URL 构造、失败隔离、限频退避 = 网络/工具面；器官不联网。归一化纪律（`%`/千分位/空白）由 subject 契约承担。 |
| `test_fixtures.py` | 13 | **舍弃** | 合成 fixtures 的冻结/MANIFEST/逐字节重生成 = 数据生成面。 |
| `test_freeze_config.py` | 7 | **舍弃** | 配置包 SHA256 冻结与 `--check` = 产品级门禁。 |
| `test_managers.py` | 14 | **已迁（判定全）** | 四类分类、区间来自参数、日期归一、unparsed 快照、标签漂移、确定性排序均在 `managers.py`；HTML 表解析属工具面。 |
| `test_no_network.py` | 5 | **舍弃** | 产品级「零网络」门（入口不发请求）；本器官以 AST 测试 `test_no_network_imports_in_organ_module` 守住无网络导入。 |
| `test_readme_gate.py` | 14 | **舍弃** | README 命令可跑性/文档计数门 = 产品级文档门；本仓由 `tests/test_docs.py` / `test_readme_commands.py` 接管。 |
| `test_scale.py` | 16 | **已迁（判定全）** | 六字段、单位读表头、0 vs null、无基准不补 0、零申赎判定均在 `scale.py`；`gmbd` 页面解析属工具面。 |
| `test_sentinels.py` | 8 | **部分迁** | 仓库哨兵（无删除路径、无外链等）属产品级不变量；本器官保留 AST 层的「无时钟 / 无网络」两条。 |
| `test_serialize.py` | 7 | **舍弃** | 确定性 JSON 写盘由内核 `Report`（字段顺序固定）承担。 |
| `test_store.py` | 11 | **舍弃** | 自选清单 SQLite/JSON 存储 = 工具面。 |
| `test_window.py` | 14 | **已迁（全）** | 报告期、工作日截止日、日历缺失 unverified、三态披露、as_of 回放均在 `window.py`；`today()` 缺省读时钟不迁（器官无时钟）。 |

**D1+D18 机械剔除的 3 个文件**（不计入分母）：

| 旧仓测试文件 | 剔除词 | 处置 |
|---|---|---|
| `test_cli.py` | `cli` | 舍弃：9 个子命令的参数面；本产品只有一个入口，由 `TestCli` 覆盖 0/1/2/3。 |
| `test_release_gate.py` | `release` | 舍弃：发布终态门（tag/附件/同源）。 |
| `test_report.py` | `report` | 舍弃：HTML/Markdown 报告渲染 = 输出排版，器官不得自带。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/fund-quarter-report.basis.json` | 9079 |
| `byteproof/data/fund-quarter-report.thresholds.json` | 1003 |

wheel 总条目 **63**；解包后 `byteproof list` = 4 器官，样例 `check` rc 0。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态变了**：旧仓从 `data/fixtures/` 读快照、从 `data/config/app.json` 读窗口与阈值；
   本器官吃一份自包含 subject（已归一 JSON + `params`）。**输入不可逐字段重放**，
   判据 2 的「rc 相同」是**等价工件上的相同**，不是同一份字节的相同。
2. **新增结构完整性规则** `fq-duplicate-holding`：旧仓 `rows` 建 dict 时重复代码被静默覆盖；
   本器官记 error。这是**新增**，不是「旧仓有这条判定」；已在 basis 的 `source` 与本表写明。
3. **change_type_missing 的覆盖面**：旧仓按 entry 的 `detect_anomaly`（退出行看上一季、
   其余看本期）汇总成 `anomalies` 列表；本器官按行落账（同一规则 + 行位置），
   因此一条 pending 条目可能对应两条 info（两侧都缺标识时）。
4. **退出码**：旧仓 `diff` 在「有异常行/失败季」时仍 rc 0（结论照给或置 insufficient_data）；
   本器官把结构性违约记 `error` -> rc 1。样例与 README 等价工件只有 warn/info，故 rc 0 = 0。
   若工件含重复代码/跨季错配/规模矛盾，rc 0→1 属**产品级语义差**（SKELETON-SPEC §5：
   `error` → 1），**不加兼容 rc**。
5. **披露状态**：旧仓 `window` 只有状态词；本器官把「待披露」记 info、「无数据」记 warn，
   「已披露」不落账（账本只记缺陷与留痕）。`as_of` 缺省时不读时钟：按「已发送即已披露」，
   与旧仓缺省读 `today()` 的行为不同（**器官无时钟**是契约）。
6. **配置面收窄**：`mode` / `threshold` / `disclosure_count` / `quarter_ends` 可由 subject 覆盖；
   配置包 schema、法规来源元数据、MANIFEST 冻结、报告合规词表内容不迁（词表由工件提供）。
7. **产品级门禁不迁**：抓取/限频/零网络/发布门/报告渲染/清单存储/基准；它们由产品 CI 与
   内核契约测试接管，逐条见 §6.2 处置表。