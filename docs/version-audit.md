# 器官 `version-audit`

> 来源：迁自 target-map ② 行（旧仓 `10-27-versionaudit`，**Node/mjs 源**，包 `versionaudit`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**npm 的版本范围当一等公民——范围语义风险（R1–R8）、锁与 manifest 的双向不一致
（带请求者路径）、重复版本收敛可行性的证明与最小冲突集、冲突的最小解释**。
Node/mjs 的逻辑用 Python 重写：semver 范围语义核心照搬 `node_modules/semver` **7.8.5**
（来源仓钉死的唯一实现，MIT）的严格模式，自研区间代数 1:1 移植；输入是输入层规整好的
**IR**（`subject.manifest` / `subject.lock`），不读文件、不联网、不读环境变量、不读时钟。

## 1. 输入（工件）

`mode` 必填（缺省值 `audit` 由器官补）；`manifest` / `lock` 必填（除 `mode=range-lint`
外都会用到 `lock`）。`mode` ∈ `audit`（四个判定模块一次跑完）/ `range-lint` /
`lock-manifest` / `dedupe` / `conflict`；`options` 可选。

| `manifest` 键 | 形态 | 说明 |
|---|---|---|
| `name` | 字符串 \| null | 根包名不是判定依据（私包常无 name），缺字段记 null 而不是编一个 |
| `deps` | `{dependencies, devDependencies, optionalDependencies, peerDependencies}` | 每类都是 `{name: range}` 字符串映射；缺类按空处理 |
| `overrides` / `resolutions` | `{name: range}` | 是**声明**不是"实际装了什么"，进 R1–R8 的展平遍历 |

| `lock` 键 | 形态 | 说明 |
|---|---|---|
| `lockfile_version` | 1 \| 2 \| 3 | 仅留档；器官不解析 v1/v2/v3 原始结构（输入层职责） |
| `packages[]` | `{path, name, version, deps, dev_deps, peer_deps, optional_deps, link}` | 路径键形态的锁条目 IR；不含根条目（根声明以 manifest 为准） |
| `root_manifest_deps` / `root_optional_deps` | `{name: range}` | 根条目的声明键（`packages[""]` 的 dependencies/optionalDependencies），只用于 M2 的基线对照 |

| `options` 键 | 默认 | 说明 |
|---|---|---|
| `enable_r8` | false | R8 默认关闭（无法从文件推断作者意图） |
| `strict` | false | 把"锁中版本 ≠ 声明下界"判为 `lock-outdated`（默认档是策略不是事实） |
| `ignore_peer` | false | peer 冲突降为 info（降级不等于不报） |
| `max_requesters` | 12 | 超限降级为删除法 MUS 并显式 `degraded: true` |
| `prefer` | null | `latest` / `min-change`，只改排序与标注，不改可行性 |

**IR 从哪来**：`package.json` / `package-lock.json` 的文件读取与 v1/v2/v3 → IR 的解析
留在输入层（D18 排除词 `input|parse` 覆盖的对象）。样例 `samples/version-audit.minimal.json`
是一份手写的干净 v3 IR。

## 2. 判定顺序与等级

等级词表 = 账本三值（`error` / `warn` / `info`）；旧仓 severity 三值
（`error` / `warning` / `info`）按
`error→error`、`warning→warn`、`info→info` 折算。verdict 由 basis 的规则登记支撑，
每条记录带 `basis_ref`（rule_id + version 1）。

| 模块 | 判什么 | 规则与默认等级 |
|---|---|---|
| M1 `range-lint` | 逐条声明跑 R1–R8 | R1 无上界 warn / R2 宽范围·非范围 warn / R3 0.x 收窄 info / R4 预发布可达性 warn / **R5 空交集 error** / R6 分支冗余 warn / R7 build metadata info / R8 裸版本跨生态 info（默认关） |
| M2 `lock-manifest` | 双向一致性 | **manifest-not-satisfied / missing-from-lock / manifest-changed-unsynced = error**；lock-extra-undeclared / lock-outdated = warn；锁条目无 version = info 降级（`va-lock-entry-no-version`，不阻断） |
| M3 `dedupe` | 收敛可行性三态 | CONVERGIBLE info / REQUIRES_OVERRIDE warn / **NOT_CONVERGIBLE error**；判定顺序固定（K3）：先实算满足性，再求 MUS |
| M4 `conflict` | 冲突最小解释 | **peer-conflict / version-conflict = error**（`ignore_peer` 只把 peer 降为 info） |

核心承诺（照搬旧仓 plan/03）：M2 的每条 finding 带 `declaring_package` /
`declared_range` / `locked_version` / `requester_path`——`npm ci` 只给目标版本，
范围与来源都没有。M3/M4 的 `minimal_conflict_set` 满足两条**可机械校验**的性质
（M 无解 + 移除任一元素后有解），降级结果也必须满足——降级的只是"基数最小/平局全列"，
不是"是不是真冲突"。

## 3. 输出

人读格式由宿主 CLI 排版；`--json` 机器可读且确定性（无时间戳、无绝对路径、无随机）。
记录顺序由账本统一排序（rule_id → verdict → path → message）。

`evidence` 字段（逐段）：

| 段 | 字段 |
|---|---|
| M1 | `rule` / `package` / `declaration` / `raw_range` / `expanded_range` / `severity`（R4/R6 另带 `details`） |
| M2 | `kind` / `declaring_package` / `declaring_path` / `dependency` / `declared_range` / `locked_version` / `requester_path` / `severity`；降级条目只带 `degraded: true` |
| M3 | `package` / `status` / `locked_versions` / `requesters` / `targets[]`（每条带逐请求者 `proof`） / `minimal_conflict_set` / `minimal_conflict_sets`（平局全列） / `reason`（`empty-intersection` \| `no-locked-candidate`） / `degraded` / `degrade_reason` / `suggestion` |
| M4 | `kind` / `package` / `locked_version` / `minimal_set` / `requesters` / `conflict_proof` / `degraded` / `downgraded_by` |
| 汇总 | `mode` / `error` / `warn` / `info` / `blocking` |

输出示例（`samples/version-audit.minimal.json`，干净树，rc 0）：

```console
$ byteproof check version-audit --input samples/version-audit.minimal.json
byteproof :: version-audit 1 :: version-audit.minimal.json
[info] va-summary — mode=audit：error=0 warn=0 info=0（阻断 0 条，旧仓默认 --fail-on=error 语义） :: summary (va-summary@1)
合计 1 条，阻断 0 条（error=0 warn=0 info=1）
```

退出码映射：旧 `0→0`；旧 `1`（error 级 finding）→ `1`；旧 `2`（仅 warning 且
`--fail-on=warning`）→ `0`（`--fail-on` 开关不迁，warning 在本产品恒不阻断）；旧 `3`
（输入不可解析）→ `2`（subject 不是合法 IR / JSON 坏）；旧 `4`（内部不一致）与旧 `5`
（Node 环境门）无对应物，见 §7。

## 4. 参数（`options`）

旧仓 CLI 的灰区开关与 organ 的 `options` 对照：`--enable-r8`→`enable_r8`、
`--strict`→`strict`、`--ignore-peer`→`ignore_peer`、`--max-requesters`→`max_requesters`、
`--prefer`→`prefer`。不迁：`--format` / `--out` / `--fail-on` / `--severity-map` /
`--verbose-paths`（输出排版与报告面属宿主 CLI；severity 表固定为旧仓 fallback 档，
见 basis 各规则的"默认等级"）。

## 5. 依据包

`src/byteproof/data/version-audit.basis.json`：20 条规则（`va-r1…va-r8`、
`va-manifest-not-satisfied` 等 M2 四类 kind + 无版本降级、M3 三态、M4 两类冲突、
`va-summary`），
每条带 `source`（旧仓模块出处）与 40+ 字的判定口径文本。随包分发；宿主 CLI 不带
`--basis` 时读它。`version-audit.thresholds.json` 同步快照默认 severity 表、verdict 表、
policy 默认值与 MUS 口径串——运行期常量必须与它逐项相等（测试断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 14 文件 `node --test` 实跑 **X = 180**（`ℹ pass 180 / fail 0`）/ 新仓实跑 **220 passed** | ✅ 过（220 ≥ 180） |
| 2 | README 示例命令 rc 相同 | `node bin/versionaudit.mjs doctor <tmp>/clean` rc **0**；`audit` 干净树 rc **0** / send 失配树 rc **1**（manifest-not-satisfied error）→ 新 `check version-audit` 干净样例 rc **0** / 等价工件 rc **1** | ✅ 过（0 = 0、1 = 1） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 14 文件（7 个目录域）；函数数**按条计** → 新 **133**（AST `test_`）/ 旧 **123**（`test(` 调用数） | ✅ 过（133 ≥ 123） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（条目数见 §6.3）；`byteproof/data/version-audit.basis.json` **11091B / 20 条** + `.thresholds.json` **1704B** 均在包内；解包 `list` = **14 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
node --test tests/checks/lock-manifest.test.mjs tests/determinism/double-run.test.mjs \
  tests/exit-codes/inconsistency.test.mjs tests/exit-codes/matrix.test.mjs \
  tests/policy/engines-contract.test.mjs tests/policy/node-floor.test.mjs \
  tests/proof/m3-dedupe.test.mjs tests/proof/m4-minimality.test.mjs \
  tests/proof/real-tree.test.mjs tests/rules/range-diff.test.mjs \
  tests/rules/range-lint.test.mjs tests/semver/interval.test.mjs \
  tests/tools/run-tests.test.mjs tests/vectors/vectors.test.mjs
```

输出原文（Node v24.15.0）：

```
ℹ tests 180
ℹ pass 180
ℹ fail 0
ℹ cancelled 0
ℹ skipped 0
ℹ todo 0
```

> 旧仓 README 的 `npm test` 走 `tools/run-tests.mjs`（201 条全量），因为"目录形态在
> Node 22+ 已失效"；本批按队列口径逐文件喂给 `node --test`，两形态等价（文件由
> D1+D18 先筛）。**X = 实跑 passed 180**，静态 baseline 记 0（JS 嵌套/参数化用例
> 静态数不出），以实跑为准。

逐文件 pass 数：`checks/lock-manifest` 13 / `determinism/double-run` 6 /
`exit-codes/inconsistency` 5 / `exit-codes/matrix` 11 / `policy/engines-contract` 1 /
`policy/node-floor` 4 / `proof/m3-dedupe` 12 / `proof/m4-minimality` 10 /
`proof/real-tree` 5 / `rules/range-diff` 50 / `rules/range-lint` 20 /
`semver/interval` 22 / `tools/run-tests` 4 / `vectors/vectors` 17 = **180**。
被剔除文件：`exit-codes/lock-input`（9）与 `report/report`（12）不进分母。

新器官 `tests/test_version-audit.py` 实跑 **220 passed**、AST `test_` 函数 **133**。

### 6.2 D1+D18 逐文件处置表（判定层 14 文件 / 旧层 123 函数）

| 旧仓测试文件 | 实跑 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `tests/checks/lock-manifest.test.mjs` | 13 | **已迁（判定全）** | 四类 kind、请求者链、optional 豁免、逐类根对照、树外/link 跳过、降级；在 `lockcheck` 与 `graph`。 |
| `tests/determinism/double-run.test.mjs` | 6 | **已迁（语义）** | 同输入两次运行一致、无时间戳/路径、顺序稳定迁为器官级断言；三格式字节对照属宿主报告面（SKELETON-SPEC §6 由产品 `test_report.py` 接管）。 |
| `tests/exit-codes/inconsistency.test.mjs` | 5 | **舍弃** | 退出码 4 = 工具结论与 `semver` 库差分不一致。跨语言重写后器官内只有**一套**实现，差分对照无第二实现；语义保真由 14 组差分向量期望值承担（见 `range-diff` 行）。 |
| `tests/exit-codes/matrix.test.mjs` | 11 | **部分迁** | 0/1/2/3 的账本化映射已迁（error→1、warn-only→0、输入坏→2、缺规则→3）；`--fail-on=warning→旧 2` 与用法错误（未知选项→旧 2）属宿主 CLI 参数面，不迁。 |
| `tests/policy/engines-contract.test.mjs` | 1 | **舍弃（产品级）** | "package.json 声明 == 运行时下限 == 入口真拒"的三段契约属产品仓自身装订；产品 `tests/test_version_floor.py` 接管。 |
| `tests/policy/node-floor.test.mjs` | 4 | **舍弃（环境面）** | 读 `process.versions.node` 并按 `engines.node` 下限拒跑 = 器官禁读环境变量（SKELETON-SPEC §2）。 |
| `tests/proof/m3-dedupe.test.mjs` | 12 | **已迁（判定全）** | 三态判定、MUS 两条性质、平局全列、超限降级、`reason` 两态不合并；在 `dedupe` + `mus`。 |
| `tests/proof/m4-minimality.test.mjs` | 10 | **已迁（判定全）** | peer/version 两类冲突、`--ignore-peer` 降级、最小集属性、降级路径性质；在 `conflict` + `mus`。 |
| `tests/proof/real-tree.test.mjs` | 5 | **已迁（等价夹具）** | 20 包真实树（`npm 11.12.1` 离线产物，只改了包名）的拓扑、双 ms 嵌套、不可收敛结论、MUS 核对、零误报；以等价 IR 夹具迁入测试。 |
| `tests/rules/range-diff.test.mjs` | 50 | **已迁（期望值）** | 14 组差分向量 + 真实树跑 CLI 断言；跨语言重写后期望值内联为 organ 级一致性表（valid_range/satisfies/subset/R1–R8/M2/M3/退出码）。 |
| `tests/rules/range-lint.test.mjs` | 20 | **已迁（判定全）** | R1–R8 全族正反例 + `expandedRange` 来自核心调用 + 排序稳定；在 `lint`。 |
| `tests/semver/interval.test.mjs` | 22 | **已迁（判定全）** | 区间代数 A1–A19 逐条 + 多路求交 + `||` 分支；在 `interval`。 |
| `tests/tools/run-tests.test.mjs` | 4 | **舍弃（仓级脚手架）** | 测的是测试 runner 本身（空匹配退出非 0）；产品仓测试基建接管。 |
| `tests/vectors/vectors.test.mjs` | 17 | **已迁（期望值）** | 夹具跑者的断言语义（mustContain/mustNotContain/exitCode）折进一致性表与退出码矩阵；fixture 文件树不迁（IR 由输入层给）。 |

**D1+D18 机械剔除**（文件名含排除词）：`tests/exit-codes/lock-input.test.mjs`（9 条，
`input`——文件读取/JSON 语法/结构混用检查由产品 CLI 的 rc 2 接管）与
`tests/report/report.test.mjs`（12 条，`report`——报告 schema/三格式一致/原子写由
宿主报告面接管）。helpers（`assertions.mjs` / `fixtures.mjs`）不是测试文件，不进分母。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/version-audit.basis.json` | 11091 |
| `byteproof/data/version-audit.thresholds.json` | 1704 |

wheel 总条目 **141**；解包后 `byteproof list` = **14 器官**、
样例 `check` rc **0**（随包 basis 缺省可用）。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **跨语言重写**：semver 语义核心按 `node-semver 7.8.5` 严格模式逐条改写（`internal/re.js`
   → Python 正则、`replaceCaret/replaceTilde/replaceXRange/hyphenReplace` 逐分支、
   `Range.test` 的预发布同三元组规则、`subset.js` 全量）；loose 模式与
   `includePrerelease` 选项不迁（器官全程默认档）。差分对照（旧仓 `range-diff` /
   `self-check` 的"工具 vs 库"）在重写后无第二实现，改为**向量期望值内联**，
   `conflictProof.crossChecked` 恒为 null（不再声称双实现复核）。
2. **输入面不迁**（D18 `input|parse`）：文件读取、JSON 语法、v1/v2/v3 结构混用检查、
   `doctor` 的可读性诊断都留在输入层；subject 必须是规整好的 IR。旧 rc 3 → 新 rc 2。
3. **输出面不迁**（D18 `report`）：`--format text/json/sarif`、SARIF 2.1.0 官方 schema
   校验、`--out` 原子写、`--severity-map` 覆盖表不迁；severity 固定 fallback 档。
   旧 `--fail-on=warning` 的 rc 2 → 新 rc 0（产品账本 warn 恒不阻断）。
4. **环境面不迁**：`node-floor`（读 `process.versions.node` 按 `engines.node` 拒跑，
   旧 rc 5）与器官契约冲突（禁读环境变量），无对应物。
5. **退出码 4（内部不一致）**：差分自检（旧仓 rc 4 的唯一来源）无第二实现，无对应物；
   向量期望值承担语义保真。
6. **MUS 删除法的去重步省略**：旧仓删除法先按引用去重再删除；器官的 requesters 由
   id 去重后才进 MUS，等价（重复 id 在上游已不可能）。
7. **新增 `va-lock-entry-no-version`**：旧仓把"锁条目无 version"放进 `degradations`
   数组随报告附带；器官把它显式化为 info 级账本行（降级可见），不阻断。
