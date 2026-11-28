# 器官 `circuit-detective`

> 来源：迁自 target-map ② 行（旧仓 `10-19-circuit-detective`，**Node/mjs 源**，core 11 模块）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**黑盒电路侦探的整颗 core**——屏幕上只有一个黑色芯片盒，拨开关、看灯亮灭，
反推盒子里最少用了哪几个逻辑门；答案由内置求解器现场复算，关卡由种子确定性生成，
探测序列可回放。Node/mjs 的 core 用 Python 逐位重写；Canvas/DOM/构建产物留输入层。

## 1. 输入（工件）

`mode` 必填。`mode` ∈ `judge`（缺省：draft 对 level 的提交判定）/ `simulate`（探测重算）/
`generate`（seed 生成关卡）/ `replay`（短码解码 + 探测一致性）/ `solve`（最优门数复核）/
`audit`（reveal 计划 + simulate + judge 一次跑完）。

| 键 | 用途 | 形态 |
|---|---|---|
| `level` | judge/simulate/solve/audit | `{seed, label, inputs, outputs, netlist, optimal}`；netlist = `{inputs, outputs, gates[{id,type,in}], outputsMap}` |
| `draft` | judge | 门编辑器草稿 `{inputs, outputs, gates[{id,type,in,x,y}], outputsMap}`（位置不参与判定） |
| `probes` | simulate/audit | 探测向量整数数组（4 bit，MSB = i0） |
| `seed` | generate | 整数或字符串（字符串走 FNV-1a，如 `"2026-01-19"`） |
| `code` / `observed` | replay | Base64url 短码 / 可选的探测结果序列（一致性复核） |
| `options` | generate/judge | `{inputCount, outputCount, gateBudget, maxGates, minOptimal}` / `{maxGates, probes}` |

## 2. 判定顺序与等级

旧仓是纯前端游戏（无 CLI 退出码）；「提交通过/不通过」映射为本账本
**0（无阻断）/ 1（存在阻断）**：accepted 且探测回放一致 = 无阻断；结构无效 /
不稳定 / 有未知 / 真值表不匹配 / 回放不一致 = 存在阻断。短码损坏 = 输入不合法
（ValueError → rc2，明确提示，绝不静默进别的关卡）。

| 模块 | 判什么 | 规则与等级 |
|---|---|---|
| 提交判定 | 草稿 → 结算 | 结构校验（一次列全：没摆零件/输出未接/引脚未接/未知信号/锥内环）→ 无 X 稳定 → 16 行全表逐输出比对（不抽样）→ 门数与差值 |
| `cd-draft-invalid` | 结构无效 | **error**：只有「输出锥内」的零件参与校验与计分，未使用零件不惩罚不计分 |
| `cd-mismatch` | 真值表不匹配 | **error**：报第一处不一致（哪一行开关组合、哪盏灯、应亮多少、实际多少） |
| `cd-settlement` | 结算/最优门数 | info：门数按每个灯单独计（输出锥内按引用展开求和）；最优 = NOT/AND/OR 门基 16 位掩码精确 DP（可证明最小值）；`counted ≥ optimal` 恒成立 |
| `cd-sim-diagnostic` | 仿真诊断 | info：组合环成员恒 X（X 传递：AND 见 0 得 0 / OR 见 1 得 1 / NOT(X)=X）；超限未稳定按全 X 处理 |
| `cd-probes-replay` | 探测重算/回放 | 探测序列重算逐项相同；短码 = 版本+seed+探测+网表+CRC16（Base64url 逐位确定）；`observed` 与重算不一致 → **error** |
| `cd-level-generation` | 关卡生成 | info/**error**（失败）：同 seed 字节级相同；拒绝恒等冗余门/含 X/单 outputs；难度带 easy≤2 / normal≤4 / hard≤12；64 次重抽失败显式报错不换 seed |
| `cd-reveal-plan` | 逐层点亮 | info：直接吃输入的门为第 0 层，层 = 1 + 上游最大层；环成员单列最后一层；同层按门 id 升序 |

## 3. 输出

`evidence` 逐段：草稿错误（code/message/gateId/pin）、mismatch（row/input/output/expected/actual）、
结算（yourGates/optimalGates/difference/probes/basisLabel）、探测重算 steps、生成（完整 level + 固定键序
JSON）、揭示计划（layers/layerById/cyclic）、汇总（mode/blocking）。

跨语言对撞锚点（旧仓 node 实跑值直接内联为断言）：`fnv1a64("2026-01-19") =
18100102244837192254`；`createRng(1)` 前三个 `next_u32` = 2559615116 / 2443280914 /
3555056611；`crc16([1,2,3]) = 44461`；`generateLevel("2026-01-19")` 的关卡 JSON
**逐字节一致**（attempts=2）。

输出示例（`samples/circuit-detective.minimal.json`，solve 复核，rc 0）：

```console
$ byteproof check circuit-detective --input samples/circuit-detective.minimal.json
[info] cd-settlement — 最优门数复算一致：7（{'o0': 1, 'o1': 1, 'o2': 3, 'o3': 2}） :: solve.optimal
[info] cd-summary — mode=solve：阻断 0 条（旧仓「提交通过/不通过」映射为账本 0/1） :: summary
合计 2 条，阻断 0 条（error=0 warn=0 info=2）
```

退出码映射：accepted / 生成成功 / 回放一致 → **0**；不通过 / 生成失败 / 回放不一致 →
**1**；短码损坏 / 输入不合法 → **2**；无依据 error / 规则缺失 → **3**（产品契约）。

## 4. 参数

`options`（generate）：`inputCount=4` / `outputCount=4` / `gateBudget=8` / `maxGates=12` /
`minOptimal=2`（旧仓 generator 默认档照搬）。`options`（judge）：`maxGates=12`、
`probes`（结算回显）。常量（阈值册同步快照）：`MAX_SOLVER_GATES=12` / `MAX_SIGNALS=16` /
`SIGNAL_BITS=4` / `RECORD_VERSION=1` / `MAX_CODE_LENGTH=64` / `MAX_REDRAWS=64` /
`GRID=32` / `X=2`。

## 5. 依据包

`src/byteproof/data/circuit-detective.basis.json`：8 条规则（结算/不匹配/草稿无效/
探测回放/关卡生成/仿真诊断/揭示计划/汇总），每条带 `source` 与 40+ 字口径文本。
`circuit-detective.thresholds.json` 同步快照 verdict 表、门基与元数、X 值、难度带、
全部常量与结算口径串——运行期常量必须与它逐项相等（测试断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 19 文件 `node --test` 实跑 **X = 121**（`ℹ pass 121 / fail 0`）/ 新仓实跑 **129 passed** | ✅ 过（129 ≥ 121） |
| 2 | README 示例命令 rc 相同 | 旧 `node tools/verify.mjs` rc **0**（全绿）→ 新干净样例 rc **0**；判定语义「通过→0 / 不通过→1」已登记为新契约（旧仓无退出码，见 §7.1） | ✅ 过（0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 19 文件（8 个目录域）；函数数**按条计** → 新 **129**（AST）/ 旧 **124**（`test(` 调用数） | ✅ 过（129 ≥ 124） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`byteproof/data/circuit-detective.basis.json` **4852B / 8 条** + `.thresholds.json` **970B** 均在包内；解包 `list` = **17 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
node --test tests/build.test.mjs tests/copy-gate.test.mjs tests/dist-scan.test.mjs \
  tests/editor.test.mjs tests/generator.test.mjs tests/handoff-gate.test.mjs \
  tests/judge.test.mjs tests/netlist.test.mjs tests/readme-gate.test.mjs \
  tests/replay.test.mjs tests/reveal.test.mjs tests/rng.test.mjs tests/share.test.mjs \
  tests/sim-cross.test.mjs tests/sim.test.mjs tests/solver.test.mjs \
  tests/source-hygiene.test.mjs tests/sprint-layout.test.mjs tests/test-manifest.test.mjs
```

输出原文（Node v24.15.0）：`ℹ tests 121 / ℹ pass 121 / ℹ fail 0`。

逐文件 pass：build 4 / copy-gate 8 / dist-scan 4 / editor 10 / generator 5 /
handoff-gate 4 / judge 12 / netlist 7 / readme-gate 4 / replay 8 / reveal 9 / rng 5 /
share 9 / sim-cross 3 / sim 9 / solver 9 / source-hygiene 2 / sprint-layout 4 /
test-manifest 5 = **121**。被剔除文件（D1+D18）：`tests/cli.test.mjs`（cli）、
`tests/release-gate.test.mjs`（release）。新器官 `tests/test_circuit-detective.py`
实跑 **129 passed**、AST `test_` 函数 **129**。

### 6.2 D1+D18 逐文件处置表（判定层 19 文件 / 旧层 124 函数）

| 旧仓测试文件 | pass | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `build.test.mjs` | 4 | **部分迁** | 关卡 JSON 固定键序 / 确定性已迁（`netlist.level_to_json` + 生成器逐字节对撞）；单文件 HTML 构建产物本身不迁（构建面）。 |
| `copy-gate.test.mjs` | 8 | **部分迁** | 分享短码的编码语义（encode/decode/CRC）迁入 `replay`；分享**文案**（ui/copy.mjs，D1 单点）不迁。 |
| `dist-scan.test.mjs` | 4 | **舍弃（构建面）** | dist/ 产物静态扫描属发布构建面，器官无产物。 |
| `editor.test.mjs` | 10 | **已迁（判定全）** | 草稿校验一次性列全、输出锥口径、环检测、未使用零件豁免；在 `judge.validate_draft`。 |
| `generator.test.mjs` | 5 | **已迁（判定全）** | 种子确定性、难度带、重抽上限；在 `generator`（含与 node 的逐字节关卡对撞）。 |
| `handoff-gate.test.mjs` | 4 | **舍弃（产品级）** | 交接单/方法论门属旧仓装订；产品仓 `tools/check_sprint_layout.py` 同责。 |
| `judge.test.mjs` | 12 | **已迁（判定全）** | 提交四步判定、结算口径、探测重算与一致性；在 `judge`。 |
| `netlist.test.mjs` | 7 | **已迁（判定全）** | 结构校验全表、拓扑排序、环识别、固定键序 JSON；在 `netlist`。 |
| `readme-gate.test.mjs` | 4 | **舍弃（产品级）** | README 命令一致性门属产品仓文档门。 |
| `replay.test.mjs` | 8 | **已迁（判定全）** | 位写入/读取对齐、CRC16、seed 64 位还原、篡改/截断/版本报错；在 `replay`。 |
| `reveal.test.mjs` | 9 | **已迁（判定全）** | 层级定义、环成员单列、同层排序、进度/序列；在 `replay.build_reveal_plan`。 |
| `rng.test.mjs` | 5 | **已迁（判定全）** | xorshift128+ 序列、FNV-1a、normalizeSeed、pick_distinct（node 参考值对撞）；在 `rng`。 |
| `share.test.mjs` | 9 | **已迁（语义）** | sharePayload/decodeReplay 的判定语义迁入（字符串 seed 走 FNV 同旧仓）；分享文案降级面不迁。 |
| `sim-cross.test.mjs` | 3 | **已迁（语义）** | 三值仿真与第二实现交叉验证的语义由 `sim` + node 参考值承担；第二实现本身不迁（器官单实现）。 |
| `sim.test.mjs` | 9 | **已迁（判定全）** | 三值语义、unit-delay、环恒 X、全表、掩码；在 `sim`。 |
| `solver.test.mjs` | 9 | **已迁（判定全）** | 成本表 DP、门数口径（锥内按引用展开）、公式展开自证；在 `solver`。 |
| `source-hygiene.test.mjs` | 2 | **舍弃（产品级）** | 源码卫生静态门（禁 Math.random/Date.now）由产品仓静态门承担。 |
| `sprint-layout.test.mjs` | 4 | **舍弃（产品级）** | 方法论布局门属产品仓 `tools/check_sprint_layout.py`。 |
| `test-manifest.test.mjs` | 5 | **舍弃（产品级）** | 测试清单完整性门属仓级测试基建。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/circuit-detective.basis.json` | 4852 |
| `byteproof/data/circuit-detective.thresholds.json` | 970 |

wheel 总条目 **174**；解包后 `byteproof list` = **17 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **退出码是新契约**：旧仓无 CLI 退出码（纯前端游戏，「通过/不通过」是 UI 状态）；
   本账本把 accepted→0、不通过→1 定为映射口径（账本退出码契约 §5 要求 0/1/2/3 有唯一
   语义），已在 basis `cd-summary` 写明。
2. **Canvas/DOM/构建面不迁**：关卡选择、拨杆交互、逐层点亮动画、单文件 HTML 构建、
   `tools/serve.mjs`、静态扫描门都不迁；器官收 `level` / `draft` 纯数据。
3. **字符串 seed 的编码语义照搬**：`encodeRecord` 的 seed 走 `normalizeSeed`——字符串
   seed 先 FNV-1a 再编码，解码回的是数字串（旧仓同语义，node 对撞证实）；UI 侧传
   `level.seed`（数字串）时回放 seedText 与原关卡 seed 不同——这是旧仓既有行为，
   未"修复"。
4. **solver 的 16 位补语义照搬**：NOT 在成本表里是 16 位补，2 输入关卡的有效函数只占
   低 4 位——单独的低 4 位掩码（如 `0b0011`）在表里不可达（-1），XOR 最优 4 门；
   与旧仓 node 实跑逐值一致，未按"4 行语义"改写。
5. **sim-cross 的第二实现不迁**：旧仓维护两份仿真实现做交叉验证；器官单实现，
   三值语义由 `sim` 测试 + node 参考值承担。
6. **`observed` 探测一致性是可选项**：旧仓回放强制重算一致（UI 驱动）；器官在
   subject 给出 `observed` 时比对（不一致记 error），不给时只重算并记录。
