# 器官 `barcode-preflight`

> 来源：迁自 target-map ② 行（旧仓 `10-27-barcodepreflight`，包 `bpreflight`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**从条码生成参数直接判「这个条码印出来会不会扫不出」**，落一张可复算的
缺陷账本：GS1 校验位与语义、符号可行性、静区/放大率/DPI/条高/颜色、阈值三态、
基线门禁。输入是参数不是图片；解析与数据文件读取留给输入层。

## 1. 输入（工件）

`mode` 是唯一必填键；其余字段按模式校验，缺字段/类型错 -> 退出码 2。

| 模式 | 必填 | 含义 |
|---|---|---|
| `check` | `identifier` 或 `gs1_element_string` | 数据层 + 符号层（若有 `symbol`）+ 印刷层（若有 `PRINT_INPUT_FIELDS`）+ 门禁 |
| `gs1` | `gs1_element_string`、`dictionary` | 只跑元素解析与四个语义解释器 |
| `symbol` | `symbol`、`profiles` | 只跑字符集/长度/编码计划/容量/校验位 |
| `oracle` | `m3_verdict`（或 `findings[]`）、`decoded` | 回读对照三态 |

| 键 | 形态 | 说明 |
|---|---|---|
| `gs1_element_string` | `"(01)…(17)…"` 或裸串（`\x1d` 分隔） | 括号串按 AI 定长切；裸串按字典宽度与 `fixed` 切 |
| `identifier` | 数字串 | `check` 的数据层载荷；retail-gtin 先按 `gtin_map` 去前导零 |
| `dictionary` | `AI -> {title, length, charset, linters, req, ex, fixed}` | 输入层从官方表解析后给出 |
| `century_resolution` | `{reference_year_yy, century_window, centuries}` | 缺省 `21 / 50 / {19,20,21}`；不读系统时钟 |
| `profiles` | `symbol -> profile` | `symbol_profiles.json` 的 `symbols` 段 |
| `thresholds` | `{gen_spec, quiet_zone, color_cases}` | 三份阈值册；gen-spec 项必须带 `source/status/verified_at` |
| `symbol` / `x_dimension_mm` / `target_dpi` / `quiet_zone_mm` | 印刷层几何四件 | 缺任一 -> 一条 `input_incomplete`，不出派生几何结论 |
| `bar_color` / `space_color` / `illumination` | 颜色三件 | 三者同时在才判颜色（可与几何缺失并存） |
| `strict_thresholds` | bool | 未核阈值派生 error 恢复为 error（默认降为 warn） |
| `fail_on` | `none` / `warn` / `error` | 缺省 `none`（只报告不拦） |
| `m3_verdict` / `decoded` / `finding_ids` | oracle 三件 | `decoded` 是外部引擎的回读结果 |

## 2. 判定顺序与等级

| 层 | 规则 | 代码 | 名义等级 | 判据 |
|---|---|---|---|---|
| GS1 | `bp-gs1-checksum` | `bp-gs1-checksum` | error | 权重由含校验位的总长度奇偶决定；只累加数据位 |
| GS1 | `bp-gs1-unknown-ai` | `bp-gs1-unknown-ai` | error | AI 不在字典内 |
| GS1 | `bp-gs1-malformed` | `bp-gs1-malformed` | error | 游离字符 / 定长不足 / 无 AI |
| GS1 | `bp-gs1-charset` | `bp-gs1-charset` | error | 字符不在 N/X/Y/Z 字符集内 |
| GS1 | `bp-gs1-length` | `bp-gs1-length` | error | 定长字段长度不符 |
| GS1 | `bp-gs1-date` | `bp-gs1-date` | error | 月/日/闰年；DD=00 表示当月最后一天 |
| GS1 | `bp-gs1-required` | `bp-gs1-required` | error | `req` 组间 OR、组内 AND |
| GS1 | `bp-gs1-exclusive` | `bp-gs1-exclusive` | error | `ex` 列表命中（不含自身） |
| GS1 | `bp-gs1-skipped` | — | info | linter 未实现 / 需要 GCP 查询 |
| 符号 | `bp-symbol-unsupported` | `symbol_unsupported` | warn | profile 表里没有该符号 |
| 符号 | `bp-symbol-charset` | `charset_not_covered` | error→warn | 字符超出全部字符集并集 |
| 符号 | `bp-symbol-length` | `length_out_of_range` / `gtin_length` | error→warn | exact/range / GTIN 映射 |
| 符号 | `bp-symbol-plan` | `encoding_plan` / `encoding_plan_unavailable` / `module_total` | info/error | 贪心模式切分 + 模块总数 |
| 符号 | `bp-symbol-capacity` | `capacity_exceeded` | error→warn | 数据码字 > 矩阵表容量 |
| 符号 | `bp-symbol-checksum` | `checksum_mismatch` | error→warn | `checksum.kind=gs1` 复算 |
| 印刷 | `bp-print-incomplete` | `input_incomplete` / `x_dimension_missing` | error | 缺几何/值不可用/X<=0 |
| 印刷 | `bp-print-quiet-zone-absent` | `quiet_zone_absent` | error | 必需侧静区为 0（结构失败，不降级） |
| 印刷 | `bp-print-quiet-zone` | `quiet_zone_insufficient` / `quiet_zone_marginal` | error→warn / warn | 低于最小 / 临界带 |
| 印刷 | `bp-print-magnification` | `magnification_below_range` / `above_range` | warn | 边界值在区间内 |
| 印刷 | `bp-print-raster` | `raster_alias_high_risk` / `raster_alias_risk` | error / warn | `<1.5` / `<2.0` dots/module（工程判据，不降级） |
| 印刷 | `bp-print-bar-height` | `bar_height_insufficient` | error→warn | 低于该符号阈值；无阈值则沉默 |
| 印刷 | `bp-print-color` | `insufficient_contrast` / `low_contrast` / `wavelength_reflectance_collapse` | error/warn/error | 双探针永不合并（工程判据） |
| 印刷 | `bp-print-unmodelled` | `surface_effect_unmodeled` | info | 非 #RRGGBB 或未建模照明 |
| oracle | `bp-oracle-agreement` | `consistent` / `m3_stricter` / `m3_laxer` | warn | 三态互斥完备，不参与 verdict |
| 摘要 | `bp-summary` | — | info | 计数 + worst + verdict |
| 门禁 | `bp-gate` | — | **error** | `fail_on` 被跨过；`none` 永不 |

**等级与阻断分离**：finding 记录带 `severity` 证据但判决不高于 `warn`；唯一 `error`
是 `bp-gate`。旧仓默认 `--fail-on none` 恒 rc 0，本器官照搬；跨门时旧仓 1/2 →
本产品 1（2→1 已登记为口径差）。

**未核降级只作用于 gen-spec 的 error**：`status=unverified` 且 `strict_thresholds`
关闭时 error→warn；engineering-heuristic（DPI、颜色）永远不降级。

## 3. 输出

```console
$ byteproof check barcode-preflight --input samples/barcode-preflight.minimal.json
byteproof :: barcode-preflight 1 :: barcode-preflight.minimal.json
[warn] bp-print-bar-height — bp-print-bar-height（severity=warn）：60.606 modules (20.000 mm / 0.330 mm X) :: findings[4] (bp-print-bar-height@1)
[warn] bp-print-quiet-zone — bp-print-quiet-zone（severity=warn）：11.000 modules (3.630 mm); the minimum is 11 modules :: findings[2] (bp-print-quiet-zone@1)
[warn] bp-print-quiet-zone — bp-print-quiet-zone（severity=warn）：7.000 modules (2.310 mm); the minimum is 7 modules :: findings[3] (bp-print-quiet-zone@1)
[info] bp-summary — 合计 5 条 finding（error=0 warn=3 info=2），verdict=warn :: summary (bp-summary@1)
[info] bp-symbol-plan — bp-symbol-plan（severity=info）：编码计划：retail-numeric(13) :: findings[0] (bp-symbol-plan@1)
[info] bp-symbol-plan — bp-symbol-plan（severity=info）：ean13 模块总数：95 :: findings[1] (bp-symbol-plan@1)
合计 6 条，阻断 0 条（error=0 warn=3 info=3）
```

样例：条高 20.00 mm（60.606 modules < 69.24）由未核阈值降级为 warn；静区左/右
都落在 `[modules_min, modules_min×1.2)` 临界带；颜色黑/白在白色照明下 21:1 通过。
`fail_on=none`（默认）⇒ rc **0**。

把 `fail_on` 改成 `warn` 时多一条：

```console
[error] bp-gate — 达到 fail_on=warn 门禁（worst=warn）；旧仓退出码 1 在本产品映射为 1 :: gate (bp-gate@1)
```

`--json` 的单条 finding：

```json
{
  "id": "bp-print-quiet-zone@findings[3]",
  "rule_id": "bp-print-quiet-zone",
  "verdict": "warn",
  "message": "bp-print-quiet-zone（severity=warn）：7.000 modules (2.310 mm); the minimum is 7 modules",
  "basis_ref": {"rule_id": "bp-print-quiet-zone", "rule_version": "1", "...": "..."},
  "path": "findings[3]",
  "evidence": {
    "id": "quiet_zone_marginal",
    "severity": "warn",
    "threshold_status": "unverified",
    "module": "M3",
    "fix": {"kind": "increase_quiet_zone", "to": "2.772", "unit": "mm", "from": "2.310"},
    "evidence": {"kind": "vector", "ref": "quiet_zone.json#symbols.ean13.right", "threshold": "7 modules"}
  }
}
```

## 4. 参数（`params`）

本器官没有 `params` 段：`strict_thresholds` / `fail_on` / `top` 都是输入字段；
阈值全部来自 `subject.thresholds`。缺字段不是「用默认值」而是输入错误（退出码 2）。

## 5. 依据包

`src/byteproof/data/barcode-preflight.basis.json`（**27 条规则**，版本 `1`）。
出处照搬旧仓 `data/README.md` §8 与 GenSpec / GS1 字典声明；工程判据（DPI、颜色）
在规则文本里写明「本项目工程判据」。

`barcode-preflight.thresholds.json` 是台账：字符集、支持符号、印刷字段、等级序、
27 条规则的名义等级。运行期常量在 `spec.py`，测试逐项断言两边相等。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓 12 个判定层文件实跑 **X = 223 passed** / 新仓实跑 **239 passed** | ✅ 过（239 ≥ 223） |
| 2 | README 示例命令 rc 相同 | README 基础示例 `bpreflight check --input spec.json`（`identifier=4006381333931`）rc **0**（VERDICT pass）→ 新 `mode=check` 等价工件 rc **0**；印刷示例 `--fail-on=error` rc **0**（VERDICT warn）→ 新等价工件 rc **0** | ✅ 过（0 = 0、0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 12 文件；函数数**按条计** → 新 **217**（AST）/ 旧 **209** | ✅ 过（239 ≥ 223；217 ≥ 209） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（**116 条目**）；`byteproof/data/barcode-preflight.basis.json` **11059B / 27 条** + `.thresholds.json` **1916B** 均在包内；解包 `list` = **11 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest \
  tests/test_checksum.py tests/test_color.py tests/test_exit_codes.py \
  tests/test_fix_contract.py tests/test_fixtures.py tests/test_gs1_semantics.py \
  tests/test_no_network.py tests/test_oracle.py tests/test_package_data.py \
  tests/test_pipeline_skeleton.py tests/test_symbols.py \
  tests/test_thresholds_manifest.py -o addopts="" -q -p no:cacheprovider
```

输出：`223 passed in 2.98s`。来源仓 `git status --porcelain` = **0 行**，
HEAD `9dee8de` 与队列一致。

逐文件 AST 函数：checksum 10 / color 19 / exit_codes 19 / fix_contract 7 /
fixtures 17 / gs1_semantics 28 / no_network 3 / oracle 28 / package_data 17 /
pipeline_skeleton 19 / symbols 24 / thresholds_manifest 18 = **209**（参数化只计一次）；
实跑 **223 passed**（参数化展开）。新器官 `tests/test_barcode-preflight.py`
实跑 **239 passed**、AST `test_` 函数 **217**。

### 6.2 D1 + D18 逐文件处置表（判定层 12 文件 / 209 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_checksum.py` | 10 | **已迁（判定全）** | 权重奇偶、官方向量、非数字拒绝；在 `gs1`。 |
| `test_color.py` | 19 | **已迁（判定全）** | 相对亮度/对比度、双探针不合并、未建模照明；在 `checks.color`。 |
| `test_exit_codes.py` | 19 | **已迁（判定全）** | 12 格矩阵 → `_crossed` + `bp-gate`；旧 1/2 映射为 1。 |
| `test_fix_contract.py` | 7 | **已迁（判定全）** | 每个几何/颜色 finding 的 `fix` 必填；在 `checks` 各分支与测试。 |
| `test_fixtures.py` | 17 | **部分迁** | 17 份 fixture 的**判定期望**用合成 spec 逐条覆盖；fixture 生成器与图像采样属数据面。 |
| `test_gs1_semantics.py` | 28 | **已迁（判定全）** | `req` / `ex` / 日期 / csum / 字符集 / 长度；在 `gs1`。 |
| `test_no_network.py` | 3 | **已迁（判定全）** | 无网络 import 的静态门；在本仓测试的 AST 门。 |
| `test_oracle.py` | 28 | **已迁（判定全）** | 三态矩阵、known-disagreements vs bug 通道、不参与 verdict；在 `oracle`。 |
| `test_package_data.py` | 17 | **部分迁** | 包数据进 wheel 由本仓判据 4 复验；字典 digest 校验属输入层。 |
| `test_pipeline_skeleton.py` | 19 | **部分迁** | 编排顺序（M1→M2→M3→verdict）已迁；spec 文件读取与扩展名检查属输入层。 |
| `test_symbols.py` | 24 | **已迁（判定全）** | 字符集并集、长度、贪心编码计划、容量、校验位；在 `symbol`。 |
| `test_thresholds_manifest.py` | 18 | **已迁（判定全）** | gen-spec 四字段、engineering 无 status、缺字段拒绝；在 `book`。 |

**D1+D18 机械剔除的 4 个文件**：`test_cli_contract.py`（cli）、`test_print_audit.py`（audit）、
`test_report_render.py`（report）、`test_reported_counts.py`（report）。
分别测 CLI 参数面、印刷层编排黑盒、报告排版与计数展示。
`conftest.py` 不是 `test_*.py`，不计入分母。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/barcode-preflight.basis.json` | 11059 |
| `byteproof/data/barcode-preflight.thresholds.json` | 1916 |

wheel 总条目 **116**；解包后 `byteproof list` = **11 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态**：旧仓读 `.json` spec 文件、拒绝其他扩展名、做 schema 检查；
   本器官只接收 subject 对象，文件读取/扩展名/UTF-8 校验属输入层。
2. **官方字典与 digest 不迁**：旧仓随包读取 `gs1-syntax-dictionary` 并校验 manifest
   digest；本器官接收输入层解析好的 `dictionary`（AI → 定长/字符集/linter/req/ex）。
3. **GCP/GEPIR 不迁**：需要联网与授权的 linter 记为 `bp-gs1-skipped`
   （`gcp_lookup_unavailable`），不伪造校验结论。
4. **外部解码引擎不迁**：旧仓探测 zxing/zbar；本器官的 `oracle` 模式只接收
   `decoded` 结果，缺引擎时由调用方给 `skipped: oracle_absent`（规则保留）。
5. **报告排版与写盘不迁**：旧仓 JSON/Markdown 双渲染、固定 `out/` 落点、
   `--with-timestamp`；本器官只产账本，渲染交宿主。
6. **退出码**：旧仓 0/1/2/3；本器官 0（未跨门）/1（跨门，含旧 1 与旧 2）/2（输入
   不合法）/3（契约违约）。**旧 2（error 跨门）→ 新 1 已登记为口径差**——
   byteproof 的 error 只表示「有阻断」，不再细分严重度；严重度在 `evidence.severity`
   与 `bp-gate.source_exit_code` 里保留。
7. **`--strict-thresholds` 语义**：只恢复 gen-spec 的 error；engineering-heuristic
   （DPI、颜色）永不改变等级，与旧仓 K8 一致。
8. **编码计划化简**：旧仓的切分器对 `min_run` / 整组约束有更细的搜索；本器官用
   「按 priority 贪心 + 同模式合并」的规范形，测试覆盖三种典型切分。计划是证据，
   不是唯一真相；容量与校验位仍按 profile 计算。
9. **矩阵容量表**：只使用 profile 提供的表；没有表或表为空时不做容量推断
   （不跨符号借数字）。
10. **颜色数学**：sRGB 相对亮度与 WCAG 常数是**定义**，不是阈值；16 位/命名色一律
    `surface_effect_unmodeled`，不给 pass/fail。