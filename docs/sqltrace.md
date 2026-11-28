# 器官 `sqltrace`

> 来源：迁自 target-map ② 行（旧仓 `10-20-sqltrace`，**Python 源**，包 `sqltrace` v0.1.2）。
> 迁入版本：`1`。契约见 [`byteproof.md`](byteproof.md)；本页只写这个器官自己的那一列。

一句话：**SQL 值/控制双通道列级血缘 + 写入者普查 + lineage diff 闸门**。三个切口：
①`SUM(x) OVER (PARTITION BY k) AS w` → `w←x`(value) + `w←k`(control)；②每张表被谁写过、
谁在读、孤儿表、多写冲突；③diff 闸门阻断破坏性变更。纪律：**value 边精确率 100%**
（宁可 unknown 不得假边）；**零静默**（每条写语句有边或有诊断）；同输入两次运行
字节级一致。**sqlglot 解析留输入层**——subject 携带解析后的泛型 AST 树，判定核零第三方
依赖（旧仓 `_Resolver` 判定面 1:1 移植）。

## 1. 输入（工件）

`mode` 必填 ∈ `lineage` / `census` / `diff`。

| subject 键 | 形态 | 说明 |
|---|---|---|
| `statements` | `[{file, index, statement_id, dialect, sql_text, ast}]` | 输入层 `sqlglot.parse` 后按泛型树 dump（`{"t":"e","c":<类名>,"args":{...},"name"/"alias"}`）；解析失败形态 = `ParseErrorStub`（显式传入，零静默） |
| `loader_diagnostics` | `[{file, statement_index, reason_code, message, approximate}]`（可选） | 输入层 loader 诊断（如 `dialect_defaulted`）原样透传 |
| `base_edges` | `[{target, source, kind}]`（diff 必填） | 基线边集（旧仓 `diff --base` 的基线） |

泛型树约定：`node_name` 读顶层 `name`（dump 属性），回退 `Table→Identifier→字符串` 两层；
`Column.this` 为 `Star` 时列名 = `*`。

## 2. 判定与等级

| 记录面 | 判什么 | verdict |
|---|---|---|
| `st-edge-value` | 目标列的值来自源列：直接列引用 / 聚合参数（带 aggregation 标注）/ 表达式参数；CTE/子查询按输出列逐层回溯到基表 | info |
| `st-edge-control` | 窗口 PARTITION BY / ORDER BY 参数（`w←k`：决定分组与次序语义，不是被聚合的值） | info |
| `st-edge-unknown` | AST 定不了：星号（unknown_wildcard）、限定名解析不到（unknown_type）——带 reason code + approximate=true，**绝不猜边** | warn |
| `st-zero-silence` | unsupported_write_statement（UPDATE/DELETE/TRUNCATE/COPY/Command/Execute）、parse_error、no_source_columns——任何静默丢弃都是失败 | **error** |
| `st-diag-approximate` | 降级档（dialect_defaulted 等）——降级显式不静默 | warn |
| `st-census-writer` / `st-census-conflict` / `st-census-orphan` | 普查五节：每表被谁写过 / 多写冲突（>1 writer） / 只读不写 | info / warn / info |
| `st-diff-destructive` / `st-diff-added` | 基线有而当前没有的边（下游列失去来源）/ 新增边 | **error** / info |

**INSERT 列对齐是位置语义**：`INSERT INTO stage_g3 (c2, c1) SELECT a, b` → `c2←a`、`c1←b`
（不是按名字找）。窗口强制口径：`SUM(x) OVER (PARTITION BY k ORDER BY t)` →
`(w,value,x) + (w,control,k) + (w,control,t)`。

## 3. 输出

输出示例（`samples/sqltrace.minimal.json` = golden g1 同参，rc 0，4 条 info）：

```console
$ byteproof check sqltrace --input samples/sqltrace.minimal.json
byteproof :: sqltrace 1 :: sqltrace.minimal.json
[info] st-edge-control — stage_w.w ←(control) ← raw_w.k (k; window) :: ...
[info] st-edge-value — stage_w.w ← raw_w.x (x) :: ...
[info] st-edge-value — stage_w.id ← raw_w.id (id) :: ...
[info] st-edge-value — stage_w.x ← raw_w.x (x) :: ...
[info] st-summary — mode=lineage：error=0 warn=0 info=4 :: summary (st-summary@1)
```

退出码映射：旧 0（无阻断）/ 1（diff 破坏性）/ 2（输入不合法）/ 4（零静默失败）→
新 0 / 1 / 2 / 3（零静默与 destructive → error；漏 basis → rc 3；`5` 旧为环境不满足，
账本无环境面）。**golden 对账即判据 2**：旧 `sqltrace lineage data/golden --json` 输出
17 边 + 8 诊断，新器官逐边相等。

## 4. 参数

无 CLI 灰区开关：三模式的全部输入面 = subject。不迁：`--json/--md`（渲染面）、
`--base <git ref>`（git 解析留输入层，`base_edges` 显式传入）、`golden` 命令壳
（golden 真值由夹具 + 逐边对账承担）、`impact` 命令（反向穿透 = 图可达性，测试面覆盖）。

## 5. 依据包

`src/byteproof/data/sqltrace.basis.json`：**11 条**（`st-edge-value` / `st-edge-control` /
`st-edge-unknown` / `st-zero-silence` / `st-diag-approximate` / `st-census-writer` /
`st-census-conflict` / `st-census-orphan` / `st-diff-destructive` / `st-diff-added` /
`st-summary`），每条 text 承载旧仓 `data/README.md` §4.1–§4.2 的判定口径原文要点；
漏 basis → rc 3。`sqltrace.thresholds.json` 快照 reason code 词表 / unsupported 类清单 /
verdict_map——与模块常量逐项相等（测试双向断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 5 文件实跑 **X = 107**（`107 passed in 3.36s`）/ 新仓实跑 **137 passed** | ✅ 过（137 ≥ 107） |
| 2 | README 示例命令 rc 相同 | 旧 `lineage data/golden --json` rc **0**（17 边 / 8 诊断）/ `golden data/golden` rc **0** → 新同语料 IR rc **0**，**边集 ``(target, source, kind)`` 逐边相等、诊断计数相等**（夹具 = 输入层对 golden 17 语句 sqlglot dump，入仓 `tests/fixtures/sqltrace-ast/`） | ✅ 过（0=0；判定面逐边对账） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 5 文件；函数数**按条计** → 新 **109**（AST `test_`）/ 旧 **103**（AST `test`） | ✅ 过（109 ≥ 103） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`sqltrace.basis.json`（11 条）+ `.thresholds.json` 均在包内；解包 `list` = **22 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src py -3.12 -m pytest tests/test_m1_loader.py tests/test_m2_core.py \
  tests/test_m3_fallback.py tests/test_m4_census.py tests/test_m5_diffgate.py \
  -o addopts="" -q -p no:cacheprovider
```

输出原文（py 3.12.10）：

```
107 passed in 3.36s
```

> D1+D18 机械剔除：`test_license_metadata.py`（license）/ `test_smoke.py`（smoke）/
> `test_version_pointer.py`（version）/ `test_output_stream.py`（output）4 件不进分母；
> 9 − 4 = 5 文件。旧层 AST `test` 函数 103（m1 12 / m2 15 / m3 28 / m4 16 / m5 32）。
> 来源仓 `git status --porcelain` 全程 **0 行**，HEAD `e8e0746` 与队列一致；旧 CLI 输出
> 定向 `%TEMP%`。golden 对账锚（旧 `lineage --json` 摘录）：
> `stage_w.w←raw_w.k(control)`、`stage_g3.c1←raw_g3.b(value)`（位置对齐）、
> `stage_star.*←null(unknown, unknown_wildcard)`；诊断 8 条 =
> dialect_defaulted×7 + unknown_wildcard×1。

### 6.2 D1+D18 逐文件处置表（判定层 5 文件 / 旧层 103 函数）

| 旧仓测试文件 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|
| `test_m1_loader.py`（12） | **部分迁（透传面）** | 语料装载（SQL 文本→语句→AST）= **输入层**（sqlglot 解析不迁）；`dialect_defaulted` 等 loader 诊断经 `loader_diagnostics` 透传并测试。 |
| `test_m2_core.py`（15） | **已迁（判定全）** | §4.1 分型 / CTE 回溯 / 窗口强制口径 / 位置对齐 / 关系收集；§1 golden 逐边 + §7 单元矩阵。 |
| `test_m3_fallback.py`（28） | **已迁（判定面）** | 零静默门 / reason code 封闭枚举 / unsupported 全类显式 / unknown 边带 reason / 负控 rc0；§5 + §7。 |
| `test_m4_census.py`（16） | **已迁（判定面）** | 普查五节 / 多写冲突 / 孤儿表；§4。 |
| `test_m5_diffgate.py`（32） | **已迁（判定面）** | diff 三态分类 / destructive 阻断 / impact 图穿透 / 确定性；git-base 与 CLI/渲染面不迁（宿主层）。 |

**D1+D18 机械剔除**：`test_license_metadata.py`（license，SPDX 元数据门）/
`test_smoke.py`（smoke，CLI 冒烟）/ `test_version_pointer.py`（version，版本指针门）/
`test_output_stream.py`（output，输出流 CRLF/渲染面——字节级一致由账本确定性测试承担）。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/sqltrace.basis.json` | 5220（11 条） |
| `byteproof/data/sqltrace.thresholds.json` | 1245 |

wheel 总条目 **227**（#37 收口 220 + 本器官 7 件：`auditors/sqltrace/` 5 个 .py +
data 2 件）；解包 `list` = **22 器官**、仓样例 `check` rc **0**（5 条 info：4 边 + summary）。
构建树来自暂存区 tree 对象（`git write-tree` = `1b246b85…`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **sqlglot 解析 → 输入层**：旧仓运行期依赖 sqlglot（只当解析器）；器官零第三方依赖，
   subject 携带泛型 AST dump。解析失败以 `ParseErrorStub` 显式传入（零静默面不缺位）。
2. **`dialect_defaulted` 诊断经 subject 透传**：方言缺省是 loader 事实，器官不重判。
3. **`golden` 命令壳不迁**：五条 golden 的真值（期望边/计数）由旧锚内联进测试断言，
   逐边对账替代命令回放。
4. **`impact` 命令面不迁**：反向穿透 = 边图可达性（测试 §4 覆盖算法面）；图构建属报告层。
5. **`st-edge-unknown` 双记录**：一条 unknown 边 + 一条 wildcard 诊断同 rule 各成行
   （账本 path 可区分）；旧仓同事实也是边 + 诊断两处输出。
6. **diff 阻断面收敛**：旧 rc1 仅由 destructive 触发、added 不阻断——账本同构
   （`st-diff-added` info）。
7. **`test_output_stream` 的 CRLF 纪律**：由账本记录确定性（双跑逐字节）承担；CLI 渲染
   的换行面属宿主。
