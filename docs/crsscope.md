# 器官 `crsscope`

> 来源：迁自 target-map ② 行（旧仓 `10-27-crsscope`，包 `crsscope`，v0.1.2）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**空间参考语义审计**——这批坐标是哪个坐标系（decl 五项）、会不会整体偏几百米
（detect 三假设评分 + 三段残差）、有没有混用（xdiff 跨实现差分 / geojson RFC 7946 结构
七项 / tiles 瓦片轴序五项）。判定核逐字移植；文件读取与报告渲染留输入层。

## 1. 输入（工件）

`mode` 必填。`mode` ∈ `decl` / `detect` / `xdiff` / `geojson` / `tiles` / `report`
（多模块汇总，`modules: [{mode: …}, …]`）。

| 模块 | subject 键 | 说明 |
|---|---|---|
| `decl` | `samples: [{a, b}]`（保持文件分量顺序）+ `declared_crs?` + `file_crs?` + `strict?` | 样本对直接给输入层解析后的坐标 |
| `detect` | `points: [[lon, lat]]` + `mask`（网格对象）+ `declared_crs?` | 掩膜缺失不得默认全陆地（§4.3）；步长 > 1° 拒绝 |
| `xdiff` | `points` + `target`（wgs84/gcj02/bd09/webmercator） | 输入被读作 target 系，每个实现转成 WGS84 |
| `geojson` | `documents: [{name, document}]` + `strict_ring?` | document 为解析后 JSON；精度检查读 Decimal 指数（输入层 `parse_float=Decimal`） |
| `tiles` | `groups: [{id, bbox?, tiles: [{z, x, y, wrap?, scheme?, bbox?}]}]` + `input_kind` + `points?` | z 负数即拒 |

## 2. 判定顺序与等级

| 模块 | 检查项（顺序固定，一项一责） | 等级折算 |
|---|---|---|
| decl | magnitude → axis → unit → mixed → extent | conflict → **error**；undecidable → warn；其余 info |
| detect | 三假设评分（score = 1−落水率 − 0.25×边界带 − 0.30×声明冲突；字典序破平局）→ 灰区 → 三段残差 | 灰区（可判定 <30 / 并列 / 覆盖差）→ warn（不硬判）；boundary_jump 有受影响点 → warn |
| xdiff | implementations → pairwise → boundary_table → jumps → not_converged | boundary 分歧 → warn；not_converged → warn；其余 info |
| geojson | ring_order → axis → bbox → nesting → null_geometry → crs_member → precision | 结构问题逐条 error；R1 违规默认 warning（级别由 R2 决定，`strict_ring` 是唯一升 error 路径）；axis/bbox/crs/precision 超限 → warning |
| tiles | y_range → axis_flip → zoom_bbox → wrap → mixed_3857_4326 | y 越界 → error；flip/wrap/嵌套/混用 conflict → **error** |

两套 `out_of_china` 边界（coordTransform_py 开区间 / gcoord 闭区间）**不合并、不取并集**
——差异本身就是审计发现点。逆向迭代超 100 次（容差 1e-6°）→ `converged=False` 必须报出。

## 3. 输出

每条 finding 一条账本行（rule_id 按 `spec.RULE_BY_MODULE` 逐模块映射）+ 每模块一条
verdict 行 + summary。`evidence` 带原 finding 的 check/status/reason 与完整证据
（bands/bbox/candidates/mask_header/pairwise 等）。

输出示例（`samples/crsscope.minimal.json`，decl 干净树，rc 0）：

```console
$ byteproof check crsscope --input samples/crsscope.minimal.json
[info] crs-decl-axis — axis：5 个可判定样本的第一分量越出纬度域 → 只能是经度，轴序呈 (lon, lat)（consistent） :: decl.findings[1]
[info] crs-module-verdict — decl 判定：声明与内容相容（五项检查均未命中） :: decl.verdict
[info] crs-summary — mode=decl：阻断 0 条（conflict/error），提示 0 条（warning/undecidable） :: summary
合计 7 条，阻断 0 条（error=0 warn=0 info=7）
```

退出码映射（§4.9 全序 `2→3→4→5→1→0` → 账本 0/1/2/3）：旧 `0→0`；旧 `1`（conflict/error
命中）→ `1`；旧 `5`（undecidable 灰区）→ `0`（warn 可见，**不阻断**——「没查」≠「查了
没问题」但也不硬判，已登记口径差）；旧 `2/3/4`（usage/environment/invalid）→ `2`
（subject 不是合法工件 / 掩膜超限）。

## 4. 参数

阈值全部照搬旧仓单点口径（thresholds.json 同步快照）：度域上限 180、米域下限 1e6、
轴序可判定下限 5 个、精度阈值 9 位小数、边界带 0.05°、权重 0.25/0.30、置信档界
0.15/0.05、可判定点下限 30、unknown+coastal 占比上限 0.8、掩膜步长上限 1°、
迭代容差 1e-6° / 上限 100 次。`--fail-on` / `--allow-undecidable` 开关不迁（见 §7）。

## 5. 依据包

`src/byteproof/data/crsscope.basis.json`：29 条规则（decl 五项 / geojson 七项 / tiles
五项 / xdiff 五项 / 检查兜底 / 结构错误 / 模块 verdict / 灰区 / detect-winner / 残差 /
汇总），每条带 `source` 与 40+ 字口径文本。`crsscope.thresholds.json` 同步快照
verdict 表、状态映射、阈值表与两套边界框（**不合并**）——运行期常量必须与它逐项相等。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 17 文件 pytest 实跑 **X = 268**（`268 passed, 2 skipped in 8.31s`）/ 新仓实跑 **330 passed** | ✅ 过（330 ≥ 268） |
| 2 | README 示例命令 rc 相同 | 旧 `py -3.12 -m crsscope decl <tmp>/clean.geojson --declared-crs 4326 --out-dir <tmp>` rc **0**；decl 米域数据 + `--allow-undecidable` rc **1** → 新干净样例 rc **0** / 等价米域工件 rc **1** | ✅ 过（0 = 0、1 = 1） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 17 文件；函数数**按条计** → 新 **213**（AST）/ 旧 **210**（AST） | ✅ 过（213 ≥ 210） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`byteproof/data/crsscope.basis.json` **13000B / 29 条** + `.thresholds.json` **2291B** 均在包内；解包 `list` = **18 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest tests/test_core.py \
  tests/test_decl.py tests/test_detect.py tests/test_determinism.py tests/test_fixtures.py \
  tests/test_geojson.py tests/test_io.py tests/test_layout_gate.py tests/test_no_network.py \
  tests/test_no_third_party.py tests/test_offline_runtime.py tests/test_python_floor.py \
  tests/test_readme_commands.py tests/test_tiles.py tests/test_unimplemented_contract.py \
  tests/test_wording.py tests/test_xdiff.py -o addopts="" -q -p no:cacheprovider
```

输出原文：`268 passed, 2 skipped in 8.31s`。

逐文件 passed：core 22 / decl 24 / detect 23 / determinism 7 / fixtures 44 / geojson 28 /
io 13 / layout_gate 8 / no_network 2 / no_third_party 3 / offline_runtime 6 /
python_floor 4 / readme_commands 17 / tiles 28 / unimplemented_contract 3(+2 skip) /
wording 8 / xdiff 28 = **268**。
被剔除文件（D1+D18）：`test_cli.py`（cli）、`test_release_gate.py`（release）、
`test_report.py` + `test_reported_counts.py`（report）、`test_version.py`（version）。
新器官 `tests/test_crsscope.py` 实跑 **330 passed**、AST `test_` 函数 **213**。

### 6.2 D1+D18 逐文件处置表（判定层 17 文件 / 旧层 210 函数）

| 旧仓测试文件 | passed/函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_core.py` | 22/20 | **已迁（判定全）** | algorithms 全族（两套边界不合并、前向/逆向、WebMercator）+ geodesy 单点；在 `algorithms` / `finding`。 |
| `test_decl.py` | 24/24 | **已迁（判定全）** | 五项检查逐项 + 声明归一/来源 + strict 语义；在 `declcheck`。 |
| `test_detect.py` | 23/20 | **已迁（判定全）** | 三假设评分/排序/置信灰区/三段残差/边界带；在 `detectcore`。 |
| `test_determinism.py` | 7/7 | **已迁（语义）** | 双跑一致由器官级 determinism 测试承担；报告时间戳面不迁。 |
| `test_fixtures.py` | 44/15 | **部分迁** | 合成数据的真值语义（偏移量级/边界形态）由等价行集在器官测试内联；夹具文件与生成器不迁（输入层）。 |
| `test_geojson.py` | 28/28 | **已迁（判定全）** | 七项检查 + 结构问题 + Decimal 精度 + R2 决定 R1 级别（变异靶子保留为测试）；在 `geojsoncheck`。 |
| `test_io.py` | 13/11 | **舍弃（输入层）** | GeoJSON/GPX/CSV/掩膜文件读取与解析（D18 `input` 域）；器官收解析后工件。 |
| `test_layout_gate.py` | 8/8 | **舍弃（产品级）** | 方法论布局门属产品仓 `tools/check_sprint_layout.py`。 |
| `test_no_network.py` | 2/2 | **舍弃（产品级）** | 零网络静态门属产品仓静态门 + CI offline docker 腿。 |
| `test_no_third_party.py` | 3/3 | **舍弃（产品级）** | 零第三方依赖门属产品仓打包面。 |
| `test_offline_runtime.py` | 6/4 | **舍弃（产品级）** | 离线运行时面属产品仓 CI offline 腿。 |
| `test_python_floor.py` | 4/3 | **舍弃（产品级）** | Python 版本下限门属产品仓 `tests/test_version_floor.py`。 |
| `test_readme_commands.py` | 17/3 | **舍弃（产品级）** | README 命令一致性门属产品仓文档门。 |
| `test_tiles.py` | 28/28 | **已迁（判定全）** | 五项检查 + 组审计事实收集；在 `tilescheck`。 |
| `test_unimplemented_contract.py` | 3/5 | **舍弃（产品级）** | 「未实现命令不得以 0 退出」属旧仓骨架期契约；本器官五模块全迁，无未实现面。 |
| `test_wording.py` | 8/7 | **已迁（措辞）** | 「不宣称发明 GCJ-02 / 不说已还原真值」的措辞纪律落在 residual 三段固定文案与两库边界表文案。 |
| `test_xdiff.py` | 28/22 | **已迁（判定全）** | 三实现口径差分、两两统计、两库边界表、跳变、未收敛灰区；在 `detectcore.run_xdiff`。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/crsscope.basis.json` | 13000 |
| `byteproof/data/crsscope.thresholds.json` | 2291 |

wheel 总条目 **185**；解包后 `byteproof list` = **18 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **文件读取面不迁**（D18 `input` 域）：GeoJSON（`parse_float=Decimal` 由输入层做）/
   GPX / CSV / 掩膜 JSON 的解析留输入层；器官收解析后工件。
2. **`--fail-on` / `--allow-undecidable` 开关不迁**：新账本 conflict/error → error、
   undecidable → warn（不阻断）、warning → warn——灰区语义固定为「可见不阻断」，等价于
   旧仓恒开 `--allow-undecidable` 的折算（判据 2 的米域对撞按此口径取 rc1）。
3. **旧 rc5 → 新 rc0**：undecidable（灰区）不阻断，语义在 evidence（已登记口径差）；
   旧 rc2/3/4 → 新 rc2（ValueError → 输入不合法）。
4. **报告渲染面不迁**：report.json / report.md 双轨渲染、`generated_at` 时间戳（唯一
   时钟入口，读 `SOURCE_DATE_EPOCH`）、scrub 去绝对路径属报告层；账本行本身确定性。
5. **退出码折算单点**：`outcome_code` 的 5→1→0 段照搬；2/3/4 段在账本里由
   ValueError → rc2 承接。
6. **`py` 默认解释器坑**：旧仓要求 Python ≥ 3.11，本机 `py` 默认落 3.8 会以
   `write_text(newline=)` TypeError 失败——判据 2 的对撞一律用 `py -3.12`（README 命令
   的可复现前提，与产品仓 AGENTS.md 的口径一致）。
