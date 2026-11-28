# 器官 `depcheck-live`

> 来源：迁自 target-map ② 行（旧仓 `11-1-depcheck-live`，**Node/mjs 源**，包 `depcheck-live` 0.1.1）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**源码里每一个对已装依赖的引用点，在「这份 node_modules」下是否真的可解析**——
`exports` 六形态解析语义（Node 官方算法 1:1 移植 + D1 实测修正的 10 处语义）、词法级引用点
抽取（静态形态 + 字符串兜底 + 动态显式落 `AMBIGUOUS`）、五个判定态、`ESM-CJS-MISMATCH`
招牌判据（看 exports 的 require 分支，**不看 `type` 字段**）、导出面静态读取（CJS/ESM/桶文件
递归）、按引用点判的版本行为漂移。Node/mjs 的逻辑用 Python 重写；输入是输入层规整好的
**IR**（依赖面事实 + 源码文本 + 包内文件文本），不读文件、不联网、不读环境变量、不读时钟。

## 1. 输入（工件）

`mode` 必填 ∈ `check`（五判定态 + 可选 drift）/ `drift`（只做漂移判定）。

| `project` 键 | 形态 | 说明 |
|---|---|---|
| `name` | 字符串 \| null | 留档；不是判定依据 |
| `declared_deps` | `{name: range}` | **dependencies ∪ devDependencies**，只有字符串 range 计入（peer/optional 首期不计入"直接依赖面"）；旧仓 `collectDeclaredDeps` 口径 |
| `deps` | `{name: record}` | 输入层从 `node_modules/<pkg>/package.json` 读出的依赖事实；**声明了但这里没有 = 未安装** → `NO_PACKAGE_JSON`（算不了） |

| `deps[name]` 键 | 形态 | 说明 |
|---|---|---|
| `installed_version` | 字符串 \| null | 快照留档 + drift 同版本恒等式判据 |
| `type` | `"module"` \| null | 包根 `package.json` 的 `type` |
| `exports` | 任意 JSON 值（可缺省） | 原样值：键缺失 = 未声明（ABSENT）、显式 `null` = 同未声明（Node 原文 ⑩：回落 main/index，不是屏蔽） |
| `files` | `{relpath: {text, type}}` | 包内文件**文本** + 每文件**最近的** `package.json` 的 `type`（Node 的 Module Type 判定口径；`glob` 的 `dist/commonjs/` 自带 `type: commonjs`，按包根判会把 CJS 产物当 ESM——实测 0 个）。文件读取与目录遍历是输入层职责，器官只做文本上的正则面 |

| 顶层键 | 形态 | 说明 |
|---|---|---|
| `sources` | `[{file, text}]` | 工程源码文本（收集遍历/扩展名过滤/跳过目录在输入层；`SOURCE_EXTENSIONS` / `SKIP_DIRS` 口径在 `spec` 留档） |
| `baselines` | `{name: value \| null}` | drift 基线（旧仓 `data/fingerprints/<pkg>.json` 的**值**）；键缺省或 `null` = 无基线/读不出/形状不对，**不猜** |
| `input_gaps` | `[{kind, file?, pkg?, detail}]` | 输入层独有事实的 gap（如 `UNREADABLE_FILE`），器官透传为阻断记录——旧仓任何 gap 都把退出码抬离 0 |
| `options` | 对象（可选） | `with_drift`（check 模式并跑 drift 层）、`max_file_bytes`（覆盖 512 KiB 默认值，输入层 stat 已由文本字节长度替代） |

## 2. 判定顺序与等级

等级词表 = 账本三值（`error` / `warn` / `info`）。旧仓的判定态不翻译——它们进
`evidence.status`；账本 verdict 由三族决定：**问题态 → error、算不了（gap）→ error（旧 rc3
族，见 §7 口径差）、只记录（RESOLVED / AMBIGUOUS / summary）→ info**。本器官不产 warn。

| 模块 | 判什么 | 规则与默认等级 |
|---|---|---|
| 抽取（`scan`） | 引用点七类 kind | import / export-from / require / dynamic-import / jest-mock 静态字面量；**变量、拼接、插值、跨行 → `AMBIGUOUS` 显式落点，不得静默丢弃**；字符串兜底双条件（形似包名 ∧ 命中已装依赖名）+ 与结构化抽取去重 |
| 解析（`resolve`） | `exports` 六形态 | sugar / 条件（**对象键序**）/ 子路径 / 通配（PATTERN_KEY_COMPARE）/ null 屏蔽 / 嵌套条件（无映射继续父层）；键形态致命性（混合键 → 整包 UNPARSEABLE、末尾斜杠与多 `*` 键仅 ignored） |
| 判定（`check`） | 首个成立者胜：AMBIGUOUS → NOT-EXPORTED-SUBPATH → ESM-CJS-MISMATCH → UNPARSEABLE → MISSING-EXPORT → RESOLVED | MISSING-EXPORT / ESM-CJS-MISMATCH / NOT-EXPORTED-SUBPATH = **error**；RESOLVED / AMBIGUOUS = info（AMBIGUOUS 显式计数，不代表代码有错）；`dp-missing-export` 带 `missing` + `available`（排序前 20） |
| 漂移（`drift`） | 按引用点判 | 基线有、已装没有、且本点实际引用 → **DRIFT = error**；无基线/未收录/读不出 → `NO-BASELINE` 阻断（不猜）；同版本恒等式不漂移；DRIFT 就地取代同点上更粗的 MISSING-EXPORT（不重复计数） |

`ESM-CJS-MISMATCH` 四条判据同时成立（旧仓 `data/README.md` §5.2）：① `type: module` 或
入口 `.mjs`；② exports 无 require 分支（含嵌套）；③ require 加载；④ 被取用的符号不在命名
空间上、而在 `.default` 下。反面判据：`type: module` 但**有** require 分支 → 必须判
RESOLVED（zod/date-fns/glob 实测）；具名取用且名字在命名空间上（commander 实测）→
判 RESOLVED。

## 3. 输出

人读格式由宿主 CLI 排版；`--json` 机器可读且确定性（无时间戳、无绝对路径、无随机）。
记录顺序由账本统一排序（rule_id → verdict → path → message）；同一引用点键上多个调用点
从第二条起 path 加 `#n` 序号（旧仓按列表输出，账本 id 必须唯一，排序稳定故序号确定）。

输出示例（`samples/depcheck-live.minimal.json`，干净树，rc 0）：

```console
$ byteproof check depcheck-live --input samples/depcheck-live.minimal.json
byteproof :: depcheck-live 1 :: depcheck-live.minimal.json
[info] dp-resolved — RESOLVED：该符号在声明的入口下确实导出 :: src/a.mjs:1:demo-pkg (dp-resolved@1)
[info] dp-resolved — RESOLVED：该符号在声明的入口下确实导出 :: src/b.cjs:1:demo-pkg (dp-resolved@1)
[info] dp-summary — mode=check：problems=0 gaps=0 resolved=2 ambiguous=0 totalPoints=2 :: summary (dp-summary@1)
合计 3 条，阻断 0 条（error=0 warn=0 info=3）
```

退出码映射（判据 2 实测见 §6.1 对撞表）：

| 旧仓情形 | 旧 rc | 新账本 | 新 rc |
|---|---:|---|---:|
| 无问题（含仅 AMBIGUOUS，显式计数） | 0 | 只有 info 级记录 | 0 |
| 发现判定问题（三问题态 / DRIFT） | 1 | 对应 error 级记录 | 1 |
| 算不了（依赖缺失 / exports 解析不了 / 基准缺失 / 降级记账，且无确证问题） | 3 | error 级阻断记录（`dp-no-package-json` 等族） | **1（口径差）** |
| 工程无 package.json / node_modules（输入层无法产出 IR） | 3 | CLI 输入不合法 | **2（口径差）** |
| 用法错误 | 4 | 宿主 CLI 参数面 | 2 |
| 2 保留不用 | — | 无对应物 | — |

## 4. 参数（`options`）

旧仓 CLI 的开关与 organ 的 `options` 对照：`--with-drift`→`with_drift`、
`--baseline-dir`→输入层解析后以 `baselines` 值传入、`--max-file-bytes`（scanSources 的
`maxFileBytes`）→`max_file_bytes`。不迁：`--json` / `--format` / `--out`（宿主报告面）、
`--version`（宿主 CLI）、`selftest` / `bench` / `scan` / `snapshot` 四个命令面（仓级脚手架
与引用点清单输出；判定函数本体已迁，见 §6.2）。

## 5. 依据包

`src/byteproof/data/depcheck-live.basis.json`：16 条规则（`dp-resolved` / `dp-ambiguous` /
`dp-summary` 三条 info；`dp-missing-export` / `dp-esm-cjs-mismatch` /
`dp-not-exported-subpath` / `dp-version-behavior-drift` 四条问题态 error；
`dp-no-package-json` / `dp-exports-unparseable` / `dp-exports-not-declared` /
`dp-unresolvable-target` / `dp-export-surface-unparseable` / `dp-no-baseline` /
`dp-large-file-downgraded` / `dp-unreadable-file` / `dp-input-gap` 九条「算不了」族 error），
每条带 `source`（旧仓模块出处）与判定口径文本。随包分发；宿主 CLI 不带 `--basis` 时读它。
漏 basis（空规则包）→ 器官调 `basis.ref` 抛 `RuleMissing` → 契约违约 rc 3（SKELETON-SPEC §5）。
`depcheck-live.thresholds.json` 同步快照 `LIMITS`（4096 / 524288）、条件集、五判定态、
kind 七类、扩展名/跳过目录与 verdict_map——运行期常量必须与它逐项相等（测试断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 16 文件 `node --test` 实跑 **X = 161**（`ℹ pass 161 / fail 0 / skipped 0`）/ 新仓实跑 **180 passed** | ✅ 过（180 ≥ 161） |
| 2 | README 示例命令 rc 相同 | 旧 `node bin/depcheck-live.mjs check <tmp>/clean` rc **0** / `check <tmp>/problem` rc **1**（MISSING-EXPORT notThere，available alpha,default）/ `check <tmp>/bare` rc **3**（工程无 package.json）→ 新 `check depcheck-live` 等价 IR：clean rc **0** / problem rc **1**（逐条同态）/ 依赖缺失 IR rc **1**（旧 3→新 1 口径差，登记）/ bare 形态由 CLI rc **2** 承接（输入层无法产出 IR） | ✅ 过（0=0、1=1；两处 rc 差按口径差接受，逐条同态） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 16 文件（7 个域）；函数数**按条计** → 新 **180**（AST `test_`）/ 旧 **166**（`test(` 全部出现计数，保守分母；行首调用 153） | ✅ 过（180 ≥ 166） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（条目数见 §6.3）；`byteproof/data/depcheck-live.basis.json` **16 条规则** + `.thresholds.json` 均在包内；解包 `list` = **19 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
node --test tests/architecture.test.mjs tests/baselines.test.mjs tests/contract.test.mjs \
  tests/drift.test.mjs tests/fingerprints.test.mjs tests/fixtures-layout.test.mjs \
  tests/fixtures-run.test.mjs tests/fixtures.test.mjs tests/gate-selfcheck.test.mjs \
  tests/handoff-pointer.test.mjs tests/paths.test.mjs tests/resolve.test.mjs \
  tests/scan-edge.test.mjs tests/scan-large-file.test.mjs tests/scan.test.mjs \
  tests/thresholds.test.mjs
```

输出原文（Node v24.15.0）：

```
ℹ tests 161
ℹ suites 0
ℹ pass 161
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
```

> 旧仓 README 的 `npm test` 是 20 文件全量（223 tests / 193 pass / 30 skipped——skip 需要
> 真实五包）；本仓 `node_modules/` 装了真实五包，实跑无 skip。**X = 实跑 passed 161**，
> 静态 baseline 记 0（JS 嵌套/参数化用例静态数不出），以实跑为准。

逐文件 pass 数：`architecture` 6 / `baselines` 8 / `contract` 13 / `drift` 12 /
`fingerprints` 6 / `fixtures-layout` 4 / `fixtures-run` 17 / `fixtures` 10 /
`gate-selfcheck` 4 / `handoff-pointer` 7 / `paths` 5 / `resolve` 36 / `scan-edge` 9 /
`scan-large-file` 5 / `scan` 12 / `thresholds` 7 = **161**。
D1+D18 机械剔除：`cli`（22）/ `bench`（17）/ `selftest`（9）/ `release`（14）不进分母；
161 + 62 = 223 与旧仓 README 全量一致。来源仓 `git status --porcelain` 全程 **0 行**，
旧 CLI 输出/临时工程定向 `%TEMP%`。

新器官 `tests/test_depcheck-live.py` 实跑 **180 passed**、AST `test_` 函数 **180**。

判据 2 对撞原文（旧侧；临时工程 `%TEMP%` 手写 `demo-dep` 依赖，不联网、不碰来源仓）：

```text
$ node bin/depcheck-live.mjs check <tmp>/clean  --json   → rc 0（problems=0 gaps=0 totalPoints=1 byStatus={RESOLVED:1}）
$ node bin/depcheck-live.mjs check <tmp>/problem --json → rc 1（MISSING-EXPORT notThere，available=[alpha,default]）
$ node bin/depcheck-live.mjs check <tmp>/bare   --json  → rc 3（reason=NO_PACKAGE_JSON：工程无 package.json）
```

新侧（同参等价 IR，显式带 basis）：

```text
$ byteproof check depcheck-live --input <tmp>/dpcheck-c2-ir-clean.json      --basis <basis> → rc 0（RESOLVED 1 条 + summary）
$ byteproof check depcheck-live --input <tmp>/dpcheck-c2-ir-problem.json    --basis <basis> → rc 1（dp-missing-export notThere，available alpha,default，逐条同态）
$ byteproof check depcheck-live --input <tmp>/dpcheck-c2-ir-missing-dep.json --basis <basis> → rc 1（dp-no-package-json 包级+点级两条；旧 rc3 族 → 新 rc1，§7 口径差）
```

### 6.2 D1+D18 逐文件处置表（判定层 16 文件 / 旧层 166 `test(`）

| 旧仓测试文件 | 实跑 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `tests/resolve.test.mjs` | 36 | **已迁（判定全）** | exports 六形态 + 条件集 + 通配优先级 + 数组回退 + require 分支存在性 + 指纹确定性；36 条向量逐条移植在 §1。 |
| `tests/scan.test.mjs` | 12 | **已迁（判定全）** | 七类 kind、import 子句解析、行号纪律（CRLF/宽字符）；在 `scan`。 |
| `tests/scan-edge.test.mjs` | 9 | **已迁（判定全）** | 超长行、拼接整族、解构符号、跨行参数；在 `scan`。 |
| `tests/scan-large-file.test.mjs` | 5 | **已迁（语义）** | 降级记账 + 降级≠丢弃 + 阈值边界；文件 stat 改由输入层文本字节长度承担（器官不读文件系统），真实五包超限用例（date-fns 837 KiB）留档在 basis 文本。 |
| `tests/thresholds.test.mjs` | 7 | **已迁（行为面）** | 阈值双向断言改为 `.thresholds.json` ↔ 模块常量 + 超限/边界行为；§5.3 文档行核对属旧仓 data/README 内部装订（产品 docs 承担）。 |
| `tests/contract.test.mjs` | 13 | **部分迁** | 枚举常量面（五判定态 / KIND / PROBLEM_STATUSES / 非判定态）迁为器官级断言；SKILL.md 契约块双向对账属旧仓交付形态（产品 `tests/test_byteproof_contract.py` 接管同族契约）。 |
| `tests/architecture.test.mjs` | 6 | **已迁（器官内移植面）** | 判定层不读文件/不碰环境变量/无时钟随机/无第三方导入 —— AST 静态判器官源码（§7.7）；分层架构本身由产品包结构承担。 |
| `tests/paths.test.mjs` | 5 | **已迁（判定全）** | `to_relative` / `normalize_slashes` / `stable_sort` 全量移植（隐私红线）；盘符字面量改拼接构造过脱敏门（改探针不放宽断言，同 #30 先例）。 |
| `tests/fingerprints.test.mjs` | 6 | **已迁（锚点面）** | 四包指纹锚（Node 生成 → Python 重算逐字节一致）+ require 分支/暴露性锚；`gen-fingerprints --check` 双跑属仓级生成器（舍弃，见 cli 行）。 |
| `tests/baselines.test.mjs` | 8 | **部分迁** | 基线形状校验 + surfaces 排序去重纪律迁为 `_validate_baseline` 断言；zod 真实基线（3.25.76 的 109 名）内联为 drift 锚；生成器 `--check`/`--list` 实跑属仓级脚手架（舍弃）。 |
| `tests/drift.test.mjs` | 12 | **已迁（判定全）** | 三条口径逐条移植（无基线不猜 / 行为不是版本号 / 判定单位是引用点）+ 基线形状 + 退出码；在 `drift`。 |
| `tests/fixtures.test.mjs` | 10 | **语义内迁** | 语料真值纪律（逐点 status + 证伪构造）以 C1–C7 等价 IR 夹具承担（§5）；语料文件本体不迁（输入层给 IR）。 |
| `tests/fixtures-layout.test.mjs` | 4 | **舍弃（仓级）** | 语料目录不塞 node_modules 的仓库纪律；产品仓无此语料形态，产品测试基建接管。 |
| `tests/fixtures-run.test.mjs` | 17 | **已迁（等价夹具）** | C1–C7 逐点真值对账 + C6 分层（check 层/drift 层）+ NO-BASELINE 不进 findings + problems 不重复计数 + 退出码真值；真实五包以等价 IR 夹具承担（chalk/commander/zod/glob/date-fns 五形态逐字对齐旧仓 expected.json 的判定）。 |
| `tests/gate-selfcheck.test.mjs` | 4 | **舍弃（产品级）** | 脱敏门与 .gitignore 的对齐纪律；产品仓 `tools/check_desensitized.py` 接管。 |
| `tests/handoff-pointer.test.mjs` | 7 | **舍弃（产品级）** | 交接单入口口径的自洽校验；产品仓 `tools/check_sprint_layout.py` 的 `LAYOUT.HANDOFFS` 接管。 |

**D1+D18 机械剔除**（文件名含排除词）：

| 旧仓测试文件 | 实跑 | 剔除词 | 去向 |
|---|---:|---|---|
| `tests/cli.test.mjs` | 22 | `cli` | 器官不得自带 CLI（SKELETON-SPEC §2）；宿主 `byteproof.cli` 的 `list`/`check`/退出码由产品 `tests/test_cli_exitcode.py` / `test_entry_surface.py` 接管。 |
| `tests/bench.test.mjs` | 17 | `bench` | bench 是旧仓基准命令（真实 node_modules 对账语料 C1–C6/C7）；其真值语义已由 C1–C7 等价夹具迁入（§5），基准脚手架本身不迁。 |
| `tests/selftest.test.mjs` | 9 | `selftest` | 现场造最小工程断言退出码 0/1/3/4 的自检命令；退出码语义由 §7 编排测试承担（器官不自带命令面）。 |
| `tests/release.test.mjs` | 14 | `release` | 发布面检查（npm pack 文件清单等）；产品发布由 `pip wheel` + 判据 4 承担。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/depcheck-live.basis.json` | 10630（16 条规则） |
| `byteproof/data/depcheck-live.thresholds.json` | 1697 |

wheel 总条目 **195**（#34 收口 185 + 本器官 10 件：`auditors/depcheck_live/` 8 个 .py +
data 2 件）；`byteproof/data/` 进包 38 件。解包后 `byteproof list` = **19 器官**、
仓样例 `check`（无 `--basis`，走解包树的随包 basis 解析）rc **0**（3 条 info：2 RESOLVED +
summary）。构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **跨语言重写**：JS 正则 → Python 正则逐条改写，`\w` 一律展开为显式 ASCII 类（JS `\w`
   不含 Unicode，Python 默认含）；`$` 的 JS 语义（非 multiline 时 ≡ `\Z`）逐处对应；
   `Object.keys` 键序依赖由 Python 3.7+ dict 保序承接。规范化指纹序列化逐字节对齐
   （四包真实指纹锚：chalk `176c42606af7` / commander `66d23ef88bab` / glob `69ba2dc95840`
   / zod `d3d5b5701e80`）。数值字面量在 canonical 序列化里与 JS `String()` 存在浮点
   表示差——`exports` 值域为字符串/数组/对象/null，不在实测语料中，留档为已知边界。
2. **退出码 3 → 新 1**：账本没有"算不了"专用退出码。把算不了落成不阻断的 warn 会回 0，
   直接反转旧仓设计红线（`data/README.md` §5.1：「零命中」与「算不了」必须落在不同退出码；
   NO-BASELINE 单条口径：用户显式跑了判定却什么都没比成，回 0 等于把「没跑」写成「跑了
   没问题」）。故「算不了」gap 族全部落成 **error 级阻断记录**（同 #22 build-diff-ledger
   先例：旧 rc 2/3 → 新 1），区分保留在 rule_id 族与 evidence 里。
3. **工程级不可算（无 package.json / 无 node_modules）→ 新 rc 2**：该形态下输入层无法
   产出依赖面 IR（subject 缺必需结构）→ CLI「输入不合法」承接；语义等价（旧 3 与新 2 都是
   非零、都表示"算不了"），零值假绿被两条路同时挡住。
4. **文件系统面 → 输入层**：目录收集（扩展名/跳过目录）、`package.json` 读取、包内文件
   读取、基线文件读取都留在输入层；器官对 `files` 文本做正则面（`readExportSurface` /
   `isEsmFile` 的"最近 package.json type"由输入层按同一口径算好放进文件条目）。
5. **`snapshot` / `scan` / `selftest` / `bench` / `doctor` 命令面不迁**：依赖面快照与引用点
   清单输出属报告面（SKELETON-SPEC §2 器官不得自带输出排版）；`selftest`/`bench` 是仓级
   脚手架（D1 排除词）。判定函数本体（`split_specifier` / `scan_text` / 判定顺序）全量迁移
   并测试。
6. **基线生成器不迁**：`tools/gen-baselines.mjs` / `gen-fingerprints.mjs`（连网取 tarball、
   离线指纹自检）属旧仓工具面；器官只消费基线**值**，基线的取数与自检纪律在旧仓
   `tests/baselines.test.mjs` 的语义（形状校验、surfaces 排序去重）由器官测试承担。
7. **同一引用点键多个调用点 → path `#n` 序号**：旧仓 findings/gaps 是列表（键可重复）；
   账本 id = rule@path 必须唯一，从同键第 2 条起加序号。排序稳定（file → line → status →
   原扫描序），序号分配确定。
8. **`exports` 值域的数值字面量**：canonical 序列化对浮点的 JS/Python 表示差留档
   （`exports` 值域实测只有字符串/数组/对象/null，不构成行为差）。
