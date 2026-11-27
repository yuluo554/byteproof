# 器官 `contract-drift`

> 来源：迁自 target-map ② 行（旧包 `contractcompat`）。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把一批契约差异事实当工件审，落一张「每条差异归哪条规则、当前 policy 下
是不是破例、随发布顺序砸谁」的缺陷账本。** 搬过来的是判定（R1–R7 规则 + 三值 severity +
七档方向矩阵 + 四态 blast_radius），不是 Avro / Protobuf / JSON Schema 解析器。

## 1. 输入（工件）

```json
{
  "differences": [
    {
      "kind": "field_removed",
      "format": "avro",
      "stable_path": "total_amount",
      "direction": "FORWARD_OK",
      "detail": null,
      "old": "long",
      "new": null,
      "number": null,
      "field": "total_amount"
    }
  ],
  "params": {"policy": "backward", "deploy_order": "consumers-first", "history": []}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `differences[].kind` | 是 | 差异事实（field_removed / type_changed / cardinality_changed / enum_* / field_number_reused / reserved_conflict / cross_message_reuse / oneof_moved / default_changed / field_added …） |
| `differences[].format` | 是 | `proto` / `avro` / `jsonschema` |
| `differences[].direction` | 是（可为 null） | `BACKWARD_OK` / `FORWARD_OK` / `BOTH_OK` / `NONE_OK` |
| `differences[].stable_path` | 否 | 字段号 / JSON Pointer / 字段名（账本位置） |
| `differences[].detail` | 否 | 事实细节（`union_widened` / `wire_compatible` / …） |
| `params.policy` | 否 | 七档之一（默认 `backward`） |
| `params.deploy_order` | 否 | 四档；缺省 -> `blast_radius=null` + `deploy_order_not_given` |
| `params.history` | 否 | 历史差异组；**只在 `*-transitive` 档可用** |

差异项是**已结构对齐后**的事实（旧仓 `policy.diff` 的产物形状），不是 schema 文件。
三格式解析、IR 归一、逐字段 diff、canonical/golden 属于工具面。

## 2. 判定顺序与等级

**规则映射**（一个事实只归一条规则）：

| 规则 | 事实 `kind` | 默认 severity | 修复动作 |
|---|---|---|---|
| R1 | `field_removed` | breaking | reserve |
| R2 | `type_changed` | breaking（detail 可改写） | bump-and-version |
| R3 | `cardinality_changed` / `requiredness_changed`；`field_added` 且 `direction=BACKWARD_OK` | breaking | add-default |
| R4 | `enum_narrowed/widened/renumbered/changed` | runtime-dependent | bump-and-version |
| R5 | `field_number_reused` / `reserved_conflict` / `cross_message_reuse` | breaking | reserve |
| R6 | `oneof_moved` | runtime-dependent | add-branch |
| R7 | `default_changed` | non-breaking | add-default |

**severity 三值相对 policy**：policy 接受该方向 -> `non-breaking`；否则按规则默认值，
R2 的 `union_widened` 改判 non-breaking，`wire_compatible / promotion / widened` 改判
runtime-dependent。**`field_added` 可选新增不是破例**（不进 R3、也不落规则行）。

**七档方向矩阵**：

| policy | 接受 |
|---|---|
| `backward` / `backward-transitive` | `BACKWARD_OK` / `BOTH_OK` |
| `forward` / `forward-transitive` | `FORWARD_OK` / `BOTH_OK` |
| `full` / `full-transitive` | `BOTH_OK` |
| `none` | 全部（不判定） |

任一差异方向不被接受 -> `verdict=breaking`（含 runtime-dependent）。`*-transitive`
必须给 `history`，否则退出码 2（不降级为单版本）。

**四态归因**：`consumers-first` -> `OLD_CONSUMER`；`producers-first` -> `NEW_CONSUMER`；
`simultaneous` -> `BOTH`；`replay` -> `REPLAY_ONLY`；缺省 -> `null` + note。

账本等级：breaking 命中 `error`；runtime-dependent `warn`；non-breaking `info`；
`contract-gate` 命中 `error`；汇总 `info`。`applies=false` 的格式槽位（Avro 的 R5/R6、
JSON Schema 的 R5）**显式出 N/A 行**（info），不得省略。

## 3. 输出

兼容样例（R7 默认值变化，policy 接受）：

```console
$ byteproof check contract-drift --input samples/contract-drift.minimal.json
byteproof :: contract-drift 1 :: contract-drift.minimal.json
[info] contract-r7 — R7：default_changed（non-breaking） :: message.User.field.name (contract-r7@1)
[info] contract-summary — verdict=compatible · policy=backward · findings 1（breaking 0 / runtime-dependent 0 / non-breaking 1） :: <summary> (contract-summary@1)
合计 2 条，阻断 0 条（error=0 warn=0 info=2）
```

Avro 删字段（README 示例的等价工件，policy=backward）：

```console
[error] contract-r1 — R1：field_removed（breaking） :: total_amount (contract-r1@1)
[info] contract-r5 — N/A：Avro 无字段号概念… :: <na:avro:R5> (contract-r5@1)
[info] contract-r6 — N/A：Avro 无 oneof 概念… :: <na:avro:R6> (contract-r6@1)
[error] contract-gate — verdict=breaking：field_removed 方向不被 policy=backward 接受 :: <verdict> (contract-gate@1)
```

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---|---|
| `policy` | `backward` | 七档之一 |
| `deploy_order` | `null` | 四档之一；缺省不猜 |
| `history` | `[]` | 历史差异组；仅 `*-transitive` 使用 |

未知参数 / 未知 policy / 未知 deploy_order / transitive 缺 history -> 退出码 2。

## 5. 依据包

随包副本 `src/byteproof/data/contract-drift.basis.json`（9 条规则，包版本 `1`）。
缺规则 -> `RuleMissing` -> 退出码 3。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓 13 个判定层文件实跑 **X = 248 passed** / 新仓实跑 **N = 248 passed** | ✅ 过（248 ≥ 248） |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文 `compat data/fixtures/avro/r1-field-removed-old.avsc data/fixtures/avro/r1-field-removed-new.avsc --policy backward` 实跑 rc **1**（verdict=breaking；R1 FORWARD_OK + R5/R6 N/A）；新入口等价工件（field_removed/avro/FORWARD_OK）rc **1** | ✅ 过（1 = 1） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 13 文件；函数数**按条计** → 新 **196**（AST）/ 旧 **181** | ✅ 过（196 ≥ 181） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（90 条目）；`byteproof/data/contract-drift.basis.json` **3618B / 9 条规则** + `.thresholds.json` **432B** 均在包内；解包 `check` rc 0 | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest \
  tests/test_architecture.py tests/test_blast.py tests/test_canonical.py \
  tests/test_coverage.py tests/test_fixtures.py tests/test_golden.py \
  tests/test_ir.py tests/test_negatives.py tests/test_policy.py \
  tests/test_readme_gate.py tests/test_rules.py tests/test_severity.py \
  tests/test_workflow.py -o addopts="" -q -p no:cacheprovider
```

输出：`248 passed`。来源仓 `git status --porcelain` = **0 行**，HEAD `0b3e546` 与队列一致。

### 6.2 D1 + D18 逐文件处置表（判定层 13 文件 / 181 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_architecture.py` | 6 | **部分迁** | 分层方向（判定层不 import report）由器官模块结构承担；源码不变量门不迁。 |
| `test_blast.py` | 20 | **已迁（判定全）** | 四态归因、deploy-order 校验、缺省 null + note；在 `audit`。 |
| `test_canonical.py` | 11 | **舍弃** | canonical JSON + digest = 报告序列化层。 |
| `test_coverage.py` | 3 | **舍弃** | 夹具/规则覆盖矩阵 = 数据面。 |
| `test_fixtures.py` | 13 | **舍弃** | fixture 扫描与位级复算 = 数据面。 |
| `test_golden.py` | 13 | **舍弃** | 92 份 golden 逐字节复算 = 数据面。 |
| `test_ir.py` | 21 | **舍弃** | IR 归一（三格式 -> ContractIR）= 输入层。 |
| `test_negatives.py` | 8 | **部分迁** | 「新增可选字段不是破例」由 `field_added` 特例守住；其余反例依赖 IR diff，不迁。 |
| `test_policy.py` | 31 | **已迁（判定全）** | 七档选择、allows/judge、方向事实、transitive 需要 history；在 `spec` + `audit.judge`。 |
| `test_readme_gate.py` | 7 | **舍弃** | README 命令门 = 产品级文档门。 |
| `test_rules.py` | 29 | **已迁（判定全）** | KIND→R1–R7、severity_by_detail、N/A 行、证据形态、修复动作；在 `audit`。 |
| `test_severity.py` | 12 | **已迁（判定全）** | 三值 severity 相对 policy；在 `audit.severity_of`。 |
| `test_workflow.py` | 7 | **舍弃** | CI workflow 结构门 = 产品级。 |

**D1+D18 机械剔除的 6 个文件**：`test_cli`（cli）、`test_parser_avro` / `test_parser_jsonschema` /
`test_parser_proto` / `test_parser_stability`（parse）、`test_report`（report）。
分别测 CLI 参数面、三格式解析、报告渲染。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/contract-drift.basis.json` | 3618 |
| `byteproof/data/contract-drift.thresholds.json` | 432 |

wheel 总条目 **90**；解包后 `check contract-drift` rc 0。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态变了**：旧仓从 `.avsc` / `.pb` / JSON Schema 解析 + IR 归一 + 逐字段 diff；
   本器官吃已对齐的差异事实。**输入不可逐字段重放**，判据 2 的「rc 相同」是等价工件上的相同。
2. **N/A 行**：Avro 的 R5/R6、JSON Schema 的 R5 照旧显式落 info 行；这是结论不是缺格。
3. **退出码映射**：旧仓 `0` 兼容 / `1` breaking / `2` 用法输入 / `3` 能力不满足；
   本产品 `0` 无阻断 / `1` 有阻断 / `2` 输入不合法 / `3` 契约违约。因此：
   - verdict=breaking → 新 rc **1**（与旧 1 相同）；
   - 差异项结构非法 / transitive 缺 history → 新 rc **2**；
   - 规则缺失 → 新 rc **3**。
4. **runtime-dependent 照旧计入阻断**（旧仓默认行为），不因新契约降级；未提供
   `--strict-runtime-dependent / --ignore-runtime-dependent` 的 CLI 开关（产品入口只有
   `check`；如需该开关，作为 params 扩展需另开裁决）。
5. **报告面不迁**：canonical JSON / digest / golden / 报告键序 / `--emit-ir` / `--explain-mapping`。
6. **IR 不可表达构造**（patternProperties / if-then-else / 递归 $ref / dependentSchemas）
   是解析层结论，本器官不重复判定。