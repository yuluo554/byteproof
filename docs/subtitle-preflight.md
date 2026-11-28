# 器官 `subtitle-preflight`

> 来源：迁自 target-map ② 行（旧仓 `10-19-subtitle-preflight`，**Node/mjs 源**，v0.1.1，单文件 HTML 工具）。
> 迁入版本：`1`。契约见 [`byteproof.md`](byteproof.md)；本页只写这个器官自己的那一列。

一句话：**字幕投放前体检的判定层**——时序 T01–T12（含 fps 帧栅格漂移拟合）、可读性
R01–R07（千分字符 + 主导文字档位）、卫生 S01–S10（十条判定式 + 白名单计数）、编码嗅探
（BOM → UTF-8 → GBK → lossy，**回退显式**）、可逆修复白名单（去重叠/修间隔 → 行尾空白 →
闭合标签 → SRT 序号重编）。旧仓的 SRT/VTT/ASS 解析与 PDF/Markdown/CSV 渲染不迁
（D1+D18 排除词 `parse` / `report`）：cue 序列由输入层摊平传入，器官零文件 IO。

跨语言重写：判定核为 Python，阈值唯一来源 `spec.THRESHOLDS`（快照
[`subtitle-preflight.thresholds.json`](../src/byteproof/data/subtitle-preflight.thresholds.json)
双向断言）；漂移拟合全程「微毫秒」整数 + `js_round` 复刻 `Math.round`（Python 内建
`round` 是银行家舍入，会改判定）。

## 1. 输入（工件）

`mode` 必填 ∈ `timing` / `readability` / `hygiene` / `decode` / `fix` / `all`（缺省 `all`）。

| 模式 | subject 键 | 说明 |
|---|---|---|
| `timing` | `cues` + 可选 `declared`（`mediaDurationMs` / `declaredFps`）+ `diagnostics` | 时序 12 条 + fps 漂移（干净对 < `drift.minSamples` → skipped 不报） |
| `readability` | `cues` | 可读性 7 条（档位由 cue 内主导文字类别决定） |
| `hygiene` | `cues` | 卫生 10 条（同 cue 同规则只报一条；白名单命中进 summary） |
| `decode` | `bytes_b64` | 原始字节（base64）→ 编码决策 + 五条诊断（回退/有损显式） |
| `fix` | `text` + `cues` + 可选 `eol`（`crlf`） | 修复白名单四个动作；不可修即不产记录 |
| `all` | `cues`（+ 可选 `text` / `bytes_b64` / `declared` / `diagnostics`） | 旧仓 `pipeline.runOne` 判定面组合 |

一条 cue 的摊平字段（输入层解析产出）：`startMs` / `endMs` / `textLines[]` /
`sourceLine`（文本类 finding 的 `line`）/ `timeLine`（时序 finding 的行号基准）/
`textLineNumbers[]` / `endLine` / `format`（`srt`/`vtt`/`ass`）/ `index` / `unparsable`。

## 2. 判定与等级

| 判定面 | 规则（账本 `rule_id` = 旧仓 `ruleId`） | verdict |
|---|---|---|
| 时序 | `timing.overlap` / `zero-duration` / `negative-duration` / `gap-too-small` / `non-monotonic` / `negative-start` / `past-media-end` | **error** |
| 时序（warn） | `timing.duplicate-cue` / `file-order-mismatch` / `timecode-precision` / `fps-drift` | warn |
| 时序（解析层透传） | `timing.unparsable-timecode`（诊断 `parse.unparsable-timecode` → finding） | **error** |
| 可读性 | `readability.cps` / `line-length` / `too-many-lines` / `too-few-chars` | **error** |
| 可读性（warn） | `readability.duration-short` / `duration-long` / `repeated-text` | warn |
| 卫生 | `hygiene.unclosed-tag` / `ass-override-residue` / `placeholder-residue` / `font-tag-residue` / `sdh-marker` | **error** |
| 卫生（warn） | `hygiene.cjk-latin-spacing` / `punctuation-width` / `trailing-punctuation` / `all-caps` / `repeated-punctuation` | warn |
| 编码 | `decode.lossy`（UTF-8 与 GBK 均严格失败） | **error** |
| 编码（其余） | `decode.invalid-utf8` / `decode.invalid-utf16` / `decode.gbk-fallback` / `decode.mixed-eol` | warn / info |
| 修复 | `fix.trim-overlap` / `fix.fill-gap` / `fix.strip-trailing-space` / `fix.close-tag` / `fix.renumber-index` | info |
| 显式未执行 | `sp-skipped`（媒体时长未知 / 帧率未知 / 样本不足 / 容差内 / 不落帧栅格 / 修复已应用 / 无可修项） | info |

**不静默**：旧仓 `skipped[]` 逐条进 `sp-skipped`（info）；`summary` 折算成 `sp-summary`
（info，evidence 承载 `total` / `by_severity` / `by_rule` / `whitelist` / `drift_fit`）。

**账本位置**：cue 类 finding 用 `cue:<n>`（1 起；`line` 留在 evidence），诊断类用
`line:<n>`，编码用 `bytes`，修复用 `line:<n>`，未执行项用 `skip:<规则>:<理由>`——
同一规则命中同一位置两次时自动加 `#n` 消歧（账本禁止重复 id）。

**排序**：finding 先按旧仓 `report.sortKeys` = `(line, ruleId, field)` 排序，账本再按
`(rule_id, verdict, path, message)` 固定排序（确定性，两次运行字节一致）。

## 3. 输出

```console
$ byteproof check subtitle-preflight --input samples/subtitle-preflight.minimal.json
byteproof :: subtitle-preflight 1 :: subtitle-preflight.minimal.json
[info] fix.trim-overlap — 可逆修复：trim-overlap（第 2 行） :: line:2 (fix.trim-overlap@1)
[warn] hygiene.cjk-latin-spacing — 中日韩文字与拉丁/数字直接相邻（排版卫生） :: cue:1 (hygiene.cjk-latin-spacing@1)
[warn] hygiene.trailing-punctuation — 行尾出现句号（问号、感叹号不属口径范围） :: cue:2 (hygiene.trailing-punctuation@1)
[info] sp-skipped — 未执行：fix（reason=applied） :: skip:fix:applied (sp-skipped@1)
[info] sp-skipped — 未执行：timing.fps-drift（reason=samples_below_min） :: skip:timing.fps-drift:samples_below_min (sp-skipped@1)
[info] sp-skipped — 未执行：timing.past-media-end（reason=media_duration_unknown） :: skip:timing.past-media-end:media_duration_unknown (sp-skipped@1)
[info] sp-summary — 体检汇总（all 模式）：7 条记录，阻断 1 条 :: report (sp-summary@1)
[error] timing.overlap — 本条起点早于上一条结束 :: cue:2 (timing.overlap@1)
合计 8 条，阻断 1 条（error=1 warn=2 info=5）
```

退出码：旧仓无 CLI（单文件 HTML + 自检门，门 0/1/2 语义）。账本侧：0 无阻断 / 1 有
error / 2 输入不合法 / 3 契约违约（缺 basis 规则）。**旧门 rc 0 是"期望与实际一致"，
新 rc 是"账本里有 error"**——见 §7 第 5 条。

## 4. 参数

阈值键与旧仓 `data/ruleset.v1.json` **逐键对应**（`cps.zh/en/ja`、`line.maxWidthFull/Half`、
`line.maxLines`、`line.minChars`、`duration.min/max`、`timing.gapMin`、
`drift.offsetRange/offsetStepCoarse/offsetStepFine/scaleRange/scaleStepCoarse/scaleStepFine/
residualMaxMs/gridToleranceMs/minSamples`、`hygiene.allCapsMinLength/repeatPunctMin`）；
白名单 8 词（`iPhone` / `iPad` / `macOS` / `iOS` / `e.g.` / `i.e.` / `etc.` / `♪`）。
可读性档位：全角 1000 / 半角 500 千分字符；假名过半 → ja，全角 ≥ 半角 → zh，否则 en。

## 5. 依据包

`src/byteproof/data/subtitle-preflight.basis.json`：**41 条**（12 时序 + 7 可读性 +
10 卫生 + 5 编码 + 5 修复 + skipped + summary），text 承载旧仓 `data/README.md` §4.2–§4.6
与 `core/decode.js` / `core/fix.js` 的判定口径原文要点。漏 basis → rc 3。
`subtitle-preflight.thresholds.json` 是阈值 / 白名单 / severity / skip 理由 / 规则清单的
**快照**（测试双向断言逐键相等）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 **13 文件** `node --test` 实跑 **X = 155 pass**（`ℹ pass 155 / ℹ fail 0`）/ 新仓实跑 **185 passed** | ✅ 过（185 ≥ 155） |
| 2 | README 示例命令 rc 相同 | 旧 `node tools/check-truth.mjs` rc **0**（42 样本 / 42 真值 / 326 cue / 109 期望项全绿）；同场景真值样本 `timing-clean-baseline.srt` 新侧 rc **0**（7 warn / 0 error）；`t11-fps-drift.srt` 新侧 rc **1**（24 error） | ✅ 过（clean 样本 0=0；t11 的 0→1 见 §7 第 5 条） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 **13 文件**；函数数**按条计** → 新 **185**（AST `test_`）/ 旧 **155**（`test(` 调用） | ✅ 过（185 ≥ 155） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树（`git write-tree` = `5be9ea59…`）构建；`subtitle-preflight.basis.json`（12265 B / 41 条）+ `.thresholds.json`（4062 B）在包内；wheel 总条目 **241**；解包 `list` = **24 器官**、样例 `check` rc **1**（重叠场景本就阻断） | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>   # 10-19-subtitle-preflight（只读）
node --test tests/architecture.test.mjs tests/artifact_e2e.test.mjs tests/build.test.mjs \
  tests/decode.test.mjs tests/drift_fit.test.mjs tests/fix_monotonic.test.mjs \
  tests/gates.test.mjs tests/hygiene_golden.test.mjs tests/readability_chars_duration.test.mjs \
  tests/readability_cps.test.mjs tests/readability_line.test.mjs tests/timing_rules.test.mjs \
  tests/truth.test.mjs
```

输出原文（Node v24.15.0）：

```
ℹ tests 155
ℹ suites 0
ℹ pass 155
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
ℹ duration_ms 2345.7694
```

逐文件 pass 数：`architecture 5` / `artifact_e2e 10` / `build 10` / `decode 8` /
`drift_fit 12` / `fix_monotonic 11` / `gates 5` / `hygiene_golden 11` /
`readability_chars_duration 24` / `readability_cps 12` / `readability_line 14` /
`timing_rules 24` / `truth 9` = **155**。

> **D1+D18 机械口径（13 文件）**：旧仓 `tests/` 共 24 个 `*.test.mjs`，按文件名正则
> （`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|
> docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`）
> 剔除 **11** 件（逐词见 §6.2）→ **24 − 11 = 13 文件**进分母。
> 旧层函数数 = 这 13 文件的 `test(` 调用 **155**（JS 口径：调用数，不是子测试数；
> 与 pass 数 1:1，无参数化展开）。
> 来源仓 `git status --porcelain` 全程 **0 行**（HEAD `f95cc5e` 与队列一致；临时产物
> 全部定向 `%TEMP%`）。

### 6.2 D1+D18 逐文件处置表（判定层 13 文件 / 旧层 155 函数）

| 旧仓测试文件 | 命中词 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|---|
| `architecture.test.mjs`（5） | — | **已迁（形状面）** | 架构扫描（源码零阈值字面量 / 无 DOM / 无网络）在账本里的等价物 = 本仓架构断言（无 IO 导入、阈值只从 `th` 读、`BUILTIN_MODULES` 字典序）。 |
| `artifact_e2e.test.mjs`（10） | — | **已迁（形状面）** | 产物端到端（打开 dist HTML 跑一遍）→ 账本等价物 = 同一 IR 两次运行逐字节一致 + 判据 2 的场景对账；浏览器面留旧仓。 |
| `build.test.mjs`（10） | — | **已迁（形状面）** | 单文件构建 / 内联清单 / 无远程引用属产品打包面，由本仓 `pip wheel` 进包清单（判据 4）承接；构建器本体不迁。 |
| `decode.test.mjs`（8） | — | **已迁（判定全）** | BOM 三态 / UTF-8 严格 / GBK 回退 / lossy / 换行归一与 mixed 诊断；§1 `decode` 模式。 |
| `drift_fit.test.mjs`（12） | — | **已迁（判定全）** | 帧栅格重建 / 粗+细 2-D 拟合 / 三条 skipped 理由 / 干净段最长连续段 / 阈值读自口径。 |
| `fix_monotonic.test.mjs`（11） | — | **已迁（判定全）** | 白名单修复四动作 + 单调性护栏（缩时不低于 `duration.min`）+ 不可修不产记录；§2 `fix.*`。 |
| `gates.test.mjs`（5） | — | **已迁（形状面）** | 口径门（`§4` ↔ ruleset 逐值一致）折算为 thresholds 快照双向断言；布局门属旧仓文档装订。 |
| `hygiene_golden.test.mjs`（11） | — | **已迁（判定全）** | 10 条判定式 + 白名单计数 + 同 cue 同规则只报一条；§2 卫生表。 |
| `readability_chars_duration.test.mjs`（24） | — | **已迁（判定全）** | 千分字符 / 主导档位 / 四项长度与时长规则。 |
| `readability_cps.test.mjs`（12） | — | **已迁（判定全）** | cps 三档上限 / 恰在限上不报 / 零时长不报 / 装饰剥离不计入。 |
| `readability_line.test.mjs`（14） | — | **已迁（判定全）** | 行长（全角 16 / 半角 42）/ 行数 / 可见字符下限。 |
| `timing_rules.test.mjs`（24） | — | **已迁（判定全）** | T01–T10 + T12 诊断透传 + 重叠不重复报 gap + 整段一条 file-order-mismatch。 |
| `truth.test.mjs`（9） | — | **已迁（形状面）** | 真值门（样本 ↔ 真值一一对应 / 覆盖度 / 禁用词 / 计数）是旧仓数据装订；账本等价物 = 判据 2 的 71/71 与 7/7 逐条对账 + `test_timing_rule_coverage` / `test_hygiene_rule_coverage` 的规则全覆盖。 |
| `bench_contract.test.mjs`（5） | **bench** | 剔除 | 性能基准（10MB / 5000 cue 墙钟）——非确定性判定面；器官不读时钟（K2）。 |
| `count_guard.test.mjs`（1） | **guard** | 剔除 | 自计数一致性守护（文档数字 ↔ 实测）；旧仓文档装订，本仓由测试计数断言承担。 |
| `desensitize_contract.test.mjs`（5） | **desensit** | 剔除 | 脱敏门（本仓 `tools/check_desensitized.py` 承接）。 |
| `parse_ass.test.mjs`（12） | **parse** | 剔除 | ASS 解析 → **输入层**：cue 摊平字段由调用方给出，器官不解析字幕文本。 |
| `parse_srt.test.mjs`（21） | **parse** | 剔除 | SRT 解析 → 输入层（同上）。 |
| `parse_vtt.test.mjs`（11） | **parse** | 剔除 | VTT 解析 → 输入层（同上）。 |
| `report_determinism.test.mjs`（12） | **report** | 剔除 | 报告确定性（同输入字节一致）——账本侧由 `test_report_json_deterministic` 承接；渲染器不迁。 |
| `report_formats.test.mjs`（9） | **report** | 剔除 | JSON/Markdown/CSV 三格式渲染——宿主报告层。 |
| `samples_generator.test.mjs`（16） | **generat** | 剔除 | 样本/真值确定性生成器——旧仓数据装订工具。 |
| `version_pointer.test.mjs`（7） | **version** | 剔除 | 版本指针一致性（package.json ↔ dist）——打包面由本仓 `pyproject`/wheel 承接。 |

被剔除 11 件实跑合计 **99 pass**（5+1+5+12+21+11+12+9+16+7）；24 文件 = 13 判定层 + 11 剔除，
`npm test` 全量 **254 pass** = 155 + 99。表格逐文件数字来自单文件复跑
（`node --test tests/<name>`），与合并跑一致。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/subtitle-preflight.basis.json` | 12265（41 条） |
| `byteproof/data/subtitle-preflight.thresholds.json` | 4062 |

wheel 总条目 **241**（#39 收口 234 + 本器官 7 件：`auditors/subtitle_preflight/` 5 个 .py +
data 2 件）；解包 `list` = **24 器官**、仓样例 `check` rc **1**（重叠场景本就阻断——
契约正确，随包 basis 缺省可判）。构建树来自暂存区 tree 对象（`git write-tree` =
`5be9ea59…`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **解析（SRT/VTT/ASS）→ 输入层**（D18 `parse`）：cue 携 `startMs`/`endMs`/
   `textLines`/`sourceLine`/`timeLine`/`textLineNumbers` 摊平传入；器官不解析字幕文本。
2. **报告渲染 → 宿主**（D18 `report`）：finding 仍是旧仓 7 键语义，但渲染 Markdown/CSV
   与 `summary` 排版在宿主；账本把 `summary` 折进 `sp-summary` evidence。
3. **单文件 HTML 构建 / 浏览器 e2e / 性能基准不迁**：产物形态与宿主打包面；器官不读时钟
   （旧仓 `perf.targetWallMs` 是基准口径，不是判定阈值）。
4. **`fixes[].ruleId` 的补登记**：旧仓行尾空白修复的 `ruleId` 是 `null`、SRT 序号重编
   借用解析层标签 `parse.index-mismatch`；账本要求每条记录有规则登记，故改登记为
   `fix.strip-trailing-space` / `fix.renumber-index`（**动作语义不变**，只换登记键）。
5. **退出码语义差**：旧仓没有 CLI，唯一"真示例"是其自检门 `node tools/check-truth.mjs`
   （rc 0 = 期望与实际一致）。新入口 rc 语义是账本阻断（有 error → 1）：
   - `timing-clean-baseline.srt`：旧门 rc **0** / 新 rc **0**（7 warn、0 error）——**相同**；
   - `t11-fps-drift.srt`：旧门 rc **0** / 新 rc **1**——**接受为口径差**（该样本含 24 条
     error 级 finding，旧门不按 finding 计退出码）。**判定内容逐条一致**（71/71
     `(ruleId, line, field)` 相同）。
6. **Python 文本编解码 vs 浏览器 `TextDecoder`**：GBK 严格解码在极少数非法双字节序上
   两栈的失败边界可能不同（旧仓测试用手工 GBK 表避开了宿主编码器）；本器官用
   `bytes.decode("gbk", errors="strict")`，`lossy` 分支用 `errors="replace"`（U+FFFD）。
   同一输入在两栈上 `encoding`/`fallback`/`lossy` 三面一致（样本 `你好`/`示例字幕` 实测）。
7. **`skipped[]` 与 `capabilities` 的承载层**：旧仓在报告顶层给 `skipped[]` 与静态
   `capabilities`；账本逐条落 `sp-skipped`、`capabilities` 折进 `sp-summary.evidence`
   （实现清单按域列）。内容一致、承载层不同。
8. **`unparsable-timecode` 的产出口**：旧仓该 finding 由解析层产出、`pipeline` 装配；
   账本按同一「诊断 → finding」法承接（subject 带 `parse.unparsable-timecode` 诊断），
   规则 id 与 `line` 口径不变。
9. **排序**：旧仓报告 findings 按 `(line, ruleId, field)`；账本先按同键排序，再按
   `(rule_id, verdict, path, message)` 固定排序（`Report` 层）。同一输入两次运行字节一致。