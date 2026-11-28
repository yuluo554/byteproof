# 器官 `merge-fidelity`

> 来源：迁自 target-map ② 行（旧仓 `10-19-merge-fidelity`，**Python 源**，包 `mergefidelity` v0.1.0）。
> 迁入版本：`1`。契约见 [`byteproof.md`](byteproof.md)；本页只写这个器官自己的那一列。

一句话：**对每一次 merge，用 git 自己的合并引擎复算"机械合并应该得到什么"，与实际记录的树
逐 blob 对比**——夹带（SMUGGLED）、静默吞掉（DROPPED）、冲突解（RESOLUTION）、跨分支漏搬
（PARITY_MISSING / PARITY_MODIFIED）、revert/复活账本（REVERT_* 三态）。**判定面全迁、
git 子进程面留输入层**：diffparse / canonical / 三模块判定核 1:1 移植；`rev-list` /
`merge-tree` / `git patch-id --stable` / worktree `apply --check` 由输入层执行，subject
携带预抽取事实。不读文件、不联网、不读环境变量、不读时钟（`as_of` 必填）。

## 1. 输入（工件）

`mode` 必填 ∈ `fidelity` / `parity` / `ledger`；`as_of` 必填（`YYYY-MM-DD`，输入层从提交
事实推导——旧仓由范围内最新提交时间推导、零时钟，器官改为显式传入）。

| 模式 | subject 键 | 说明 |
|---|---|---|
| `fidelity` | `merges[]`：`{merge_oid, parents, merge_base, recorded_tree, mechanical_tree, mechanical_conflict, recorded_blobs, mechanical_blobs, tree_diff_text, payload_text, gitattributes_text}` + 顶层 `patch_ids`（`sha256(diff 文本) → git patch-id` 绑定）与 `later_patch_ids`（path → 后续提交 patch-id 列表） | blob 映射 = `git cat-file` 产物；`tree_diff_text` = `git diff -U0 机械树 记录树`；`payload_text` = `git log --remerge-diff` 输出 |
| `parity` | `side[]`（A 侧逐提交 `{commit, diff_u0_text, patch_id, paths}`）、`candidates[]`（候选 + `apply{available, reverse_check, forward_check}`）、`worktree`、`warnings` | apply 布尔 = 输入层在 A 侧临时 worktree 上的 `apply --check`（-U3）结果 |
| `ledger` | `revert_bodies[]`（`git log --grep='^This reverts commit'` 正文块）、`commit_facts`（revert/被回滚提交的 `-U0` patch-id 与取反 patch-id）、`later_facts`（revert 之后提交的 patch-id）、`find_object_available` | patch-id 全部输入层预计算 |

## 2. 判定与等级

| 判定态 | 规则 | verdict |
|---|---|---|
| SMUGGLED | tree diff 含 `+` 行且无冲突标记（按 hunk 自身形态归类，方向唯一） | **error** |
| DROPPED | 只含 `-` 行且删除未被重引入（合成反向新增探针 patch-id ∈ 后续同路径 patch-id 集） | **error** |
| RESOLUTION | hunk 含冲突标记（默认不显示，不 fail-on） | info |
| PARITY_MISSING / PARITY_MODIFIED | 三态优先级：patchid 相等→PRESENT；apply reverse 成功→PRESENT(apply)；forward 成功→MISSING；皆失败→MODIFIED；无 apply 证据→MODIFIED(patchid)（不猜 MISSING） | **error** |
| PRESENT | 不是事故；账本 info 显式记录（含 equivalent_source） | info |
| REVERTED_THEN_REDONE / NO_SUCCESSOR | 反向 patch-id 校验通过后按 successor 有无结论 | info |
| REVERT_UNVERIFIED | 校验不过（verified=false）或 find-object 不可用（unavailable=git_too_old）——判不了不猜 | warn |
| SKIPPED（octopus / custom_driver） | 父提交数>2 / .gitattributes 命中自定义 merge driver——显式记账不进分母 | info |
| CROSSCHECK_MISMATCH / CHERRY_COUNT_MISMATCH / PATCHID_UNBOUND | 交叉核对不一致 / 探针未绑定（保守不排除） | warn |

每条 finding 内容寻址：`id = sha1(merge_oid ‖ path ‖ old_range ‖ new_range ‖ kind)`
（分隔符 U+001F；SHA-1 在此是旧仓的**标识口径**，非安全原语；报告完整性 digest 用 SHA-256）。
区段 0 基（count>0 时 start=git 行号−1；count=0 直接取行号）；无对应侧写 `-`。

## 3. 输出

输出示例（`samples/merge-fidelity.minimal.json`，忠实 merge，rc 0）：

```console
$ byteproof check merge-fidelity --input samples/merge-fidelity.minimal.json
byteproof :: merge-fidelity 1 :: merge-fidelity.minimal.json
[info] mf-summary — mode=fidelity：error=0 warn=0 info=0 :: summary (mf-summary@1)
合计 1 条，阻断 0 条（error=0 warn=0 info=1）
```

退出码映射：旧 0（无事故）/ 1（有事故）/ 2（用法错误）/ 3（环境不满足）→ 新 0 / 1 / 2 / 3
（SMUGGLED/DROPPED/PARITY_MISSING/PARITY_MODIFIED → error → rc1；坏引用/坏 as_of → rc2；
漏 basis → rc3）。旧 `report`/`gate` 子命令的渲染与 TOML 基线面不迁（宿主报告层）。

## 4. 参数

`options.kinds`（默认 SMUGGLED+DROPPED，同旧仓 DEFAULT_KINDS）、`options.show_resolution`
（同 `--show-resolution`）。不迁：`--since/--until/--range`（rev 面在输入层）、
`--fail-on`（gate 面）、`--format md`（渲染面）、`--no-apply-fallback`（以
`apply.available=false` 表达同语义）。

## 5. 依据包

`src/byteproof/data/merge-fidelity.basis.json`：**15 条**（`mf-smuggled` / `mf-dropped` /
`mf-resolution` / `mf-parity-missing` / `mf-parity-modified` / `mf-parity-present` /
`mf-reverted-*` 三态 / `mf-skip-*` / `mf-warning-*` / `mf-patchid-unbound` / `mf-summary`），
每条 text 承载旧仓 `data/README.md` §4.1–§4.6 的**判定口径原文要点**；漏 basis → rc 3。
`merge-fidelity.thresholds.json` 快照 canonical 冻结参数 / FAIL_ON_KINDS / verdict_map /
BUILTIN_MERGE_DRIVERS——与模块常量逐项相等（测试双向断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 **10 文件**实跑 **X = 213**（`213 passed in 197.44s`）/ 新仓实跑 **227 passed** | ✅ 过（227 ≥ 213） |
| 2 | README 示例命令 rc 相同 | 旧 README 最小复现：`report … --verify docs/report-sample.json` rc **0**（verified）/ `gate … --baseline audit-baseline.toml` rc **0**（baselined=1）/ `fidelity scan` smuggled=1 dropped=0 resolution=1、blob_fidelity=0.5、finding SMUGGLED src/synthapp/core.py `-`→`7,1` → 新同场景 IR rc **1**（SMUGGLED→error），**finding_id 与旧仓 canonical.finding_id 逐字节一致**（`a387b28fd982ca83a26026a3774c550ada1b1492`） | ✅ 过（判定内容逐字段一致；rc 0→1 = 口径差：旧 report/gate 按基线算退出码，账本无基线面） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 **10 文件**；函数数**按条计** → 新 **164**（AST `test_`）/ 旧 **159**（AST `test`） | ✅ 过（164 ≥ 159） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`merge-fidelity.basis.json`（15 条）+ `.thresholds.json` 均在包内；解包 `list` = **21 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src py -3.12 -m pytest tests/test_canonical.py tests/test_counts.py \
  tests/test_fidelity.py tests/test_gate.py tests/test_gen_fixtures.py tests/test_gitobj.py \
  tests/test_ledger.py tests/test_parity.py tests/test_readme_gate.py tests/test_workflow.py \
  -o addopts="" -q -p no:cacheprovider
```

输出原文（py 3.12.10）：

```
213 passed in 197.44s
```

> **D1+D18 机械口径（10 文件）**：旧仓共 14 个测试文件，按文件名正则
> （`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`）
> 剔除 **4** 件：`test_bench_snapshot.py`（bench）/ `test_cli.py`（cli）/
> `test_diffparse.py`（**parse**）/ `test_report.py`（report）→ **14 − 4 = 10 文件**进分母。
> `test_gen_fixtures.py` 文件名 **不含** `generat`（是 `gen_fixtures`），**机械计入**——
> 其形状面（fixture 真值可重建、`--check` 位级一致）已迁入 §3/§6 的等价断言。
> 夹具仓库（21 个合成 repo）由 `tools/gen_fixtures.py --out data/fixtures` 现场生成
> （`.gitignore` 覆盖 `data/fixtures/`，来源仓 `git status --porcelain` 全程 **0 行**，
> HEAD `0a944f6` 与队列一致）。判据 2 的跨实现锚：旧仓
> `canonical.finding_id('8913b090…','src/synthapp/core.py','-','7,1','SMUGGLED')`
> = `a387b28fd982ca83a26026a3774c550ada1b1492`，新器官同场景 IR 输出同值。

### 6.2 D1+D18 逐文件处置表（判定层 10 文件 / 旧层 159 函数）

| 旧仓测试文件 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|
| `test_canonical.py` | **已迁（判定全）** | 幂等 / digest 键序不敏感 / finding_id 稳定与敏感 / range_str / 排序；§2。 |
| `test_counts.py` | **已迁（形状面）** | fixture/golden 计数断言折算为"报告摘要计数与 finding 集合一致"（§3/§6.1 同场景对账）；计数门本体属旧仓文档装订。 |
| `test_fidelity.py` | **已迁（判定面）** | gitattributes 匹配 / blob_fidelity / 三分类 / 重引入 / skipped；git 子进程面折算为 subject 事实（§3）。 |
| `test_gate.py` | **已迁（常量面）** | FAIL_ON_KINDS / 受限 TOML 的**基线面不迁**（宿主报告层）；退出码语义折算为账本 error 族。 |
| `test_gen_fixtures.py` | **已迁（形状面）** | fixture 真值可重建（`--check` 位级一致）折算为"夹具由生成器现场产出、真值断言可重放"；生成器本体不迁。 |
| `test_gitobj.py` | **已迁（口径面）** | git 子进程面不迁，但其**口径常量**（CONFIG_OVERRIDES / 对象格式 / 版本门槛）留档于 spec；patch-id 语义经跨实现锚对账（§6.1）。 |
| `test_ledger.py` | **已迁（判定面）** | 正文提取正则 / 反向校验 / 重放三态 / verified≠status 两件事；§5。 |
| `test_parity.py` | **已迁（判定面）** | 三态矩阵 / note / 计数 / worktree 纪律（挂 A 不挂 B 语义保留在 classify_apply 口径）；apply 检查折算为布尔事实。 |
| `test_readme_gate.py` | **舍弃（仓级）** | README 数字口径门——旧仓文档装订，由产品门与台账承担。 |
| `test_workflow.py` | **舍弃（仓级）** | CI workflow 文本门——产品 CI 承担。 |

**D1+D18 机械剔除（4 件，从 14 文件到 10 文件）**：`test_bench_snapshot.py`（bench，基准快照面）/
`test_cli.py`（cli，CLI 参数面由宿主 CLI 承担）/ **`test_diffparse.py`（parse，D18 剔除——
结构解析本身不做判定，其向量已迁入器官 `diffparse` 模块的 §1 测试，但**不进旧层分母**）**/
`test_report.py`（report，渲染与 digest `--verify` 面不迁——digest 算法本体已迁并测试）。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/merge-fidelity.basis.json` | 8781（15 条） |
| `byteproof/data/merge-fidelity.thresholds.json` | 1545 |

wheel 总条目 **220**（#36 收口 211 + 本器官 9 件：`auditors/merge_fidelity/` 7 个 .py +
data 2 件）；解包 `list` = **21 器官**、仓样例 `check` rc **0**（1 条 info：summary）。
构建树来自暂存区 tree 对象（`git write-tree` = `f20ed7e5…`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **git 子进程面 → 输入层**：`rev-list` / `merge-tree`（MechanicalMerge）/ `cat-file` /
   `git patch-id --stable` / 临时 worktree `apply --check` 全部由输入层执行；subject 携带
   预抽取事实。器官是纯函数，不碰文件系统与子进程。
2. **patch-id 查表绑定**：器官不实现 git patch-id 算法（实现漂移风险 > 查表成本）。输入层
   以 `sha256(逐字节 diff 文本) → patch-id` 映射供证；器官对**自己合成的**重引入探针文本
   重算 sha256 查表，查不到 → 记 `mf-patchid-unbound` warn 并保守地不排除 DROPPED
   （与旧仓空 diff patch_id=None 的保守路径同向：缺证不能排除吞掉）。
3. **退出码 0→1（事故类）**：旧 `report`/`gate` 的退出码按基线与 fail-on 计算（样例仓库
   baselined=1 → rc 0）；账本无基线面，每条事故类 finding error → rc 1。判定内容逐字段
   一致（跨实现锚）。
4. **parity findings 按候选聚合**：旧 `findings_of` 把候选的每个 path 展开成一条 finding；
   账本每候选一条（paths 进 evidence）。ID 口径不变（仍以首个 path 计算）。
5. **SHA-1 仅作内容寻址 ID**（旧仓 §4.5 标识口径）：非安全原语；报告完整性 digest 用
   SHA-256（与旧仓 canonical.digest_of 同构）。
6. **as_of 显式化**：旧仓 `--as-of` 可缺省（由提交事实推导）；器官必填（输入层算好传入），
   缺失按输入不合法 rc 2。`datetime.strptime` 仅作形态校验（不读时钟）。
7. **`report` 渲染 / `gate` TOML 基线不迁**：宿主报告层职责；判定态经账本行表达。
