# 器官 `chart-integrity`

> 来源：迁自 target-map ② 行（旧包 `chartaudit`）。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把一张图表的工件（数据 + 规格 + 溯源）当字节工件审，落一张「这张图哪里
不可复核 / 哪里在误导」的缺陷账本。** 搬过来的是判定（九条反误导规则 + 逐值溯源 +
样本量门禁 + 误差棒来源），不是渲染器、也不是发布工具。

## 1. 输入（工件）

```json
{
  "dataset": {
    "header": ["月份", "值"],
    "columns": [{"name": "月份", "type": "date"}, {"name": "值", "type": "decimal"}],
    "rows": [["2026-01-01", "10.00"], ["2026-01-08", "12.50"]],
    "row_count": 2,
    "source": {"name": "monthly.csv", "sha256": "<64 hex>"}
  },
  "spec": {
    "spec_id": "spec-demo",
    "mark": "line",
    "title": "月度值（合成样例）",
    "encoding": {"x": {"field": "月份"}, "y": {"field": "值", "decimals": 2}}
  },
  "provenance": {
    "spec_id": "spec-demo",
    "source": {"name": "monthly.csv", "sha256": "<64 hex>"},
    "rendered_values": [{"rendered_value_id": "…", "sources": [], "transform_chain": []}]
  },
  "params": {}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `dataset.header` / `columns` / `rows` | 是 | 已解析的数据集；`row_count` 必须等于 `rows` 长度，每行列数等于 `header` |
| `dataset.source.sha256` | 是 | 源文件哈希；与 `provenance.source.sha256` 对账 |
| `spec` | 是 | normalized spec：`spec_id` / `mark` / `title` / `encoding.x.field` / `encoding.y.field`（+ 可选 `decimals` / `aggregate` / `series` / `filter` / `error_bar` / `y_zero` / `dual_y` / `pseudo_3d` / `size_channel` / `smooth` / `low_contrast` / `overlay_scatter` / `null_tokens`） |
| `provenance.rendered_values` | 是 | 每个渲染值恰一条溯源记录（`rendered_value_id` / sources / transform_chain / match …） |
| `params` | 否 | 阈值、别名表（见 §4） |

数据集是**已解析**的 JSON，不是 CSV；spec 是**已归一**的规格，不是原始输入。
CSV 解析、spec 合法性拦截、HTML 渲染属于工具面，器官不读文件、不联网、不读时钟。

## 2. 判定顺序与等级

| 段 | 规则 | 等级 | 判据 |
|---|---|---|---|
| 反误导 | `chart-bar-baseline` | `error` | bar + `y_zero=false`（截断基线） |
| 反误导 | `chart-dual-y` | `error` | `dual_y=true` |
| 反误导 | `chart-pie-sectors` | `error` | 饼图扇区 > `pie_max_sectors`，或百分比舍入后合计 ≠ 100 |
| 反误导 | `chart-pseudo-3d` | `error` | `pseudo_3d=true` |
| 反误导 | `chart-radius` | `error` | `size_channel=radius` |
| 反误导 | `chart-smooth` | `error` | `smooth=true` |
| 反误导 | `chart-time-axis` | `error` | date 类 x 轴、≥2 个可解析日期、相邻间隔不全相等 |
| 反误导 | `chart-low-contrast` | `error` | `low_contrast=true` |
| 反误导 | `chart-spec-invalid` | `error` | 永不产出：规格合法性由解析层（rc 2）拦截 |
| 溯源 | `chart-provenance-missing` | `error` | 按 spec 枚举出的渲染值缺记录 |
| 溯源 | `chart-provenance-unexpected` | `error` | 存在不属于当前 spec 的 `rendered_value_id` |
| 溯源 | `chart-provenance-malformed` | `error` | id 非 16 hex / 重复 / csv_line ≠ row+2 / 源哈希不符 |
| 溯源 | `chart-provenance-mismatch` | `error` | 行列不存在 / raw_cell 不符 / id 复算不符 / match 或重算标签不符 |
| G2 | `chart-g2-small-n` | `error` | n < `n_min` 且偏斜（\|g1\| > 阈值）或多峰，且无合规替代 |
| G2 | `chart-g2-undetermined` | `warn` | n < `n_min` 但分布不可判定（样本过小 / 全等值） |
| G2 | `chart-g2-alternative` | `info` | 小样本偏斜/多峰，但声明散点叠加 / 图型为 box / scatter |
| G3 | `chart-g3-source` | `error` | sd/sem/ci/n 声明来源缺失或数值矛盾（含标题自由文本声明） |
| G3 | `chart-g3-undeclared` | `info` | 未声明误差棒，但存在数值型 SD/SEM 别名列 |

G2 的多峰判定：固定 `multimodal_bins` 等宽直方图，局部极大 bin 计数 ≥
`max(floor, ceil(n/divisor))` 且两峰间隔 ≥ 1 个 bin。

G3 的列名匹配：`match_mode=suffix`，大小写由 `aliases.case_sensitive` 决定
（默认不敏感）；`CI` 必须同时具备上下限两列；`SEM` 声明列须与 `sd/sqrt(n)` 在
`sem_tolerance_abs` 内一致。

## 3. 输出

干净工件：

```console
$ byteproof check chart-integrity --input samples/chart-integrity.minimal.json
byteproof :: chart-integrity 1 :: chart-integrity.minimal.json
合计 0 条，阻断 0 条（error=0 warn=0 info=0）
```

命中一条规则时（示例：`bar` + `y_zero=false`）：

```console
$ byteproof check chart-integrity --input <工件.json>
byteproof :: chart-integrity 1 :: <工件.json>
[error] chart-bar-baseline — 柱状图 y_zero=false：截断基线放大视觉差异 :: y_zero (chart-bar-baseline@1)
合计 1 条，阻断 1 条（error=1 warn=0 info=0）
```

`--json` 的单条账本：

```json
{
  "id": "chart-g3-source@encoding.error_bar.column",
  "rule_id": "chart-g3-source",
  "verdict": "error",
  "message": "误差棒来源不成立：G3_SEM_MISMATCH",
  "basis_ref": {"rule_id": "chart-g3-source", "rule_version": "1", "source": "…", "quote": "…"},
  "path": "encoding.error_bar.column",
  "evidence": {"gate_id": "G3_SEM_MISMATCH", "type": "sem", "category": "A", "problem": {…}}
}
```

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---|---|
| `n_min` | 5 | G2 的小样本门槛 |
| `skew_abs_threshold` | 1.0 | \|g1\| 超过即偏斜 |
| `skew_min_n` | 3 | 少于它偏度不可判定 |
| `multimodal_bins` | 6 | 等宽直方图 bins |
| `multimodal_min_n` | 4 | 少于它多峰不可判定 |
| `multimodal_min_count_floor` | 2 | 峰计数下限 |
| `multimodal_min_count_divisor` | 6 | 峰计数下限 = ceil(n/divisor) |
| `sem_tolerance_abs` | `1e-12`（字符串） | SEM 与 sd/√n 的容差 |
| `pie_max_sectors` | 4 | 饼图扇区上限 |
| `aliases` | 见 thresholds | 误差棒别名表（case_sensitive / match_mode / type_order / types） |

未知参数键 -> 退出码 2。阈值台账 `src/byteproof/data/chart-integrity.thresholds.json`
与运行期默认值逐项相等（测试钉住）。

## 5. 依据包

随包副本 `src/byteproof/data/chart-integrity.basis.json`（18 条规则，包版本 `1`）。
缺规则 -> `RuleMissing` -> 退出码 3。`--basis` 优先，其次随包副本。

## 6. §7.3 四项无损判据 · 实测

口径：`D1 + D18` —— **判据 1 的分母 = 旧仓「判定层」实跑用例数**。判定层 = 文件名不匹配
`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`
的测试文件。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓 9 文件实跑 X = 222 passed** / 新仓实跑 **N = 243 passed** | ✅ 过（+21） |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文 `chartaudit check data/synthetic/synthetic_groups.csv data/synthetic/spec_clean_bar.json --out <dir>` 实跑 rc **0**（在 `%TEMP%` 里跑，输出也落 `%TEMP%`，来源仓 0 改动）；新入口 `check chart-integrity --input samples/chart-integrity.minimal.json` rc **0** | ✅ 过（0 = 0；参数形态不同见 §7） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 9 文件；函数数**按条计** → 新 **226**（AST）/ 旧 **122** | ✅ 过（226 ≥ 122） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树（`git write-tree` + `git archive`）构建 `byteproof-0.1.0-py3-none-any.whl`（71 条目）；`byteproof/data/chart-integrity.basis.json` **6367B / 18 条规则** + `.thresholds.json` **1719B** 均在包内；解包 `check` rc 0 | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=scripts PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest \
  tests/test_gates.py tests/test_gen_synthetic.py tests/test_provenance.py \
  tests/test_provenance_regression.py tests/test_render.py tests/test_rules.py \
  tests/test_rules_regression.py tests/test_serialize.py tests/test_whitelist.py \
  -o addopts="" -q -p no:cacheprovider
```

输出：`222 passed in 1.16s`。来源仓 `git status --porcelain` = **0 行**，HEAD `83fc6e5` 与队列一致。

### 6.2 D1 + D18 逐文件处置表（判定层 9 文件 / 122 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_gates.py` | 31 | **已迁（判定全）** | G2 偏度/多峰/合规替代、G3 sd/sem/ci/n 来源判定、别名表匹配、阈值来自配置；配置 schema 校验并入 `params` 校验。 |
| `test_gen_synthetic.py` | 7 | **舍弃** | 冻结数据生成与两层 MANIFEST 校验 = 数据生成面。 |
| `test_provenance.py` | 19 | **已迁（判定全）** | 白名单变换、ROUND_HALF_UP、ID 字段序、compile（identity/group_* / ratio）、G1 四形态与不变量。 |
| `test_provenance_regression.py` | 5 | **部分迁** | 真值图的逐值正例与独立重算由本器官的 compile/validate 矩阵承担；**冻结数据目录**与注入式回归不迁（数据面）。 |
| `test_render.py` | 25 | **舍弃** | HTML 渲染、几何包、零 CDN、发布门、SKILL 契约块 = **输出排版/发布面**（SKELETON-SPEC §2：器官不得自带输出排版）。 |
| `test_rules.py` | 23 | **已迁（判定全）** | 九条规则、规则包登记顺序、级别排序、饼图阈值来自配置；`alignment` 标注保留在 basis 的 `source` 文本里。 |
| `test_rules_regression.py` | 3 | **部分迁** | 真值图的规则期望改为本器官的规则矩阵；**冻结真值目录**不迁。 |
| `test_serialize.py` | 3 | **舍弃** | LF + 键排序的 JSON 写盘由内核 `Report` 承担。 |
| `test_whitelist.py` | 6 | **舍弃** | 假业务主题白名单（file/title/column 的业务命名门）= 产品级数据门。 |

**D1+D18 机械剔除的 4 个文件**（不计入分母）：

| 旧仓测试文件 | 剔除词 | 处置 |
|---|---|---|
| `test_bench.py` | `bench` | 舍弃：29 张真值图基准。 |
| `test_cli_skeleton.py` | `cli` | 舍弃：CLI 参数面；本产品唯一入口由 `TestCli` 覆盖 0/1/2/3。 |
| `test_parse.py` | `parse` | 舍弃：CSV 解析与 spec 校验（输入层）。 |
| `test_parse_regression.py` | `parse` | 舍弃：解析回归真值。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/chart-integrity.basis.json` | 6367 |
| `byteproof/data/chart-integrity.thresholds.json` | 1719 |

wheel 总条目 **71**；解包后 `byteproof list` = 5 器官，样例 `check` rc 0。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态变了**：旧仓从 CSV 解析 + spec 校验 + provenance 生成；本器官吃自包含
   subject（dataset + normalized spec + provenance）。**输入不可逐字段重放**，
   判据 2 的「rc 相同」是**等价工件上的相同**。
2. **规则包加载变 basis**：旧仓 `references/rules.json` 的 rule_id/级别/文案在运行期加载；
   本器官把 18 条规则登记进 basis，阈值进 `params`。`alignment` 字段不再输出为
   audit.json 字段，改为写在每条 basis 规则的 `source` 文本里（对齐标注仍在）。
3. **G1 的 ID 复算**：`rendered_value_id` 的字段序与 JSON 规范串接逐字保留；
   但「预期记录集合」由本器官的 `compile_records` 重新枚举（不读旧仓产物）。
4. **G3 的 gate_id** 保留在 `evidence.gate_id`（`G3_SEM_MISMATCH` 等），便于对账旧仓；
   findings 的 `severity` 由规则等级决定（source 的 `severity` 映射改为固定 verdict）。
5. **退出码**：旧仓 `check` 在无错误时 rc 0、有 ERROR 时 rc 1，与本器官一致；
   输入结构非法（缺 header / row 宽度不符）在旧仓是 rc 2，本器官同样 rc 2。
   本器官把「规则 error」映射为 rc 1（SKELETON-SPEC §5），不加兼容 rc。
6. **未迁的输出面**：HTML 渲染、几何包、零 CDN 扫描、发布门、SKILL 契约块、
   audit.json/gates.json 排版、bench、冻结数据生成、白名单业务门。
7. **`chart-spec-invalid` 永不命中**：与旧仓相同（R009 由解析层拦截，规则层不二次改判）。