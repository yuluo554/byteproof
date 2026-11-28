# 器官 `subset-audit`

> 来源：迁自 target-map ② 行（旧仓 `10-21-subset-audit`，**Python 源**，包 `subsetaudit` v0.1.1）。
> 迁入版本：`1`。契约见 [`byteproof.md`](byteproof.md)；本页只写这个器官自己的那一列。

一句话：**审字体子集产物，不是审字体项目**——输入 = 原字体 + 子集字体 + 必须支持的字符集；
输出 = 子集是否真覆盖（§六.2 三分类）、GSUB/GPOS 是否被弄坏（§六.5）、元数据是否被剥掉
（§六.9）。三个判定模块 1:1 迁；**fontTools 读取与 license-gate 模块不迁**（license 为 D1
排除词）——subject 携带摊平事实（cmap 映射 / OS/2 位域 / nameID / 布局摊平 /
OS2_UNICODE_RANGES 表），判定核零第三方依赖。旧仓护城河声明如实保留：技术护城河 ≈ 0，
真正资产是规则集与 fixture 库。

## 1. 输入（工件）

`mode` 必填 ∈ `coverage-diff` / `layout-survival` / `metadata`。

| 模式 | subject 键 | 说明 |
|---|---|---|
| `coverage-diff` | `required_text` / `required`（码位集，两者并）+ `source_cmap` / `subset_cmap`（`{cp 或 "0x…": glyphName}`，键接受 int 或十六进制字符串——旧仓 expect.json 摊平形态）+ `source_cmap_facts` / `subset_cmap_facts`（cmap 选表事实：`chosen`/`subtables`/`reason`） | `options.strict_source`：MISSING_IN_SOURCE 升 error |
| `layout-survival` | `source_layout` / `subset_layout`：`{GSUB, GPOS}` 各为摊平结构（`triples` 四元组列表 / `ligature_index` 码位视图连字表 / `ligature_features` / 四个计数） | 占位名判定（`glyph%05d`）在输入层完成，器官消费 `state` |
| `metadata` | `os2`（位域表）/ `codepoints` / `unicode_ranges`（OS2_UNICODE_RANGES 表经 subject 供证——旧仓"不复制第二套口径"纪律保持）/ `subset_name_ids` / `source_name_ids` / `measured_glyphs` | |

## 2. 判定与等级

| 判定面 | 判什么 | verdict |
|---|---|---|
| `sa-lost-in-subset` | (R∩S)−U 每码位一条（静默丢字）；evidence 四键实测（subset_covered 填实测不反推） | **error** |
| `sa-missing-in-source` | R−S 每码位一条；strict_source 升 error | warn / **error** |
| `sa-layout-feature-lost` | GSUB/GPOS 四元组差集（分开成条；`GSUB/hani/ZHS /liga` 字面拼法） | **error** |
| `sa-layout-ligature-lost` / `sa-layout-ligature-renamed` | 连字按**输入码位序列**差分（不按字形名——`uniFB01→glyph00003` 改名实测）；LOST 优先 RENAMED 互斥；两侧都 placeholder 不算改名 | **error** / warn |
| `sa-name-stripped` | nameID 三分类：只有 default_stripped 产 finding（author_absent/unclassified 不产） | warn |
| `sa-codepage-latin1-overdeclared` | 只判 bit0（声称 Latin-1 而 C∩[0,FF]=∅；fontTools recalcCodePageRanges 回退置位常踩） | **error** |
| `sa-unicode-range-overdeclared` | 只判过度、欠声明不判；行为型位（bit57 全落代理区）按"存在非 BMP 码位"判 | warn |
| `sa-maxp-mismatch` | maxp.numGlyphs vs 独立量（loca/CFF CharStrings） | **error** |
| `sa-char-index-mismatch` | 首末码位只判"没覆盖住"；0xFFFF 哨兵该方向不判 | warn |
| SKIPPED 七理由 | no_cmap_table / no_unicode_cmap（两路径不合并、summary 为空不猜）/ no_layout_tables / layout_tables_missing_on_one_side（判定照常）/ no_os2 / no_name / no_outline | info 显式 |

闭包（NFD/NFC 双向）**只计数不产 finding**；回退链建议**仅建议不改判定**；分区计数
ExtA 优先于 BMP（0x3400 曾被判 BMP 的实测修正）。

## 3. 输出

输出示例（`samples/subset-audit.minimal.json`：fi 连字丢字场景，rc 1）：

```console
$ byteproof check subset-audit --input samples/subset-audit.minimal.json
[error] sa-lost-in-subset — 需求字符 U+FB01 原字体有覆盖、子集产物丢失（静默丢字） :: coverage-diff:U+FB01
```

退出码映射：旧 0/1/2（0 无事故 / 1 有 error 级 finding / 2 InputError）→ 新 0/1/2
**语义一致无口径差**；SKIPPED 不是事故（info）。

## 4. 参数

`options.strict_source`（同 `--strict-source`）。不迁：`--text/--corpus`（需求集经
`required_text`/`required` 显式传入）、`--subset`（两侧 cmap 都显式传）、`--markdown`
（渲染面）、license-gate 模块（D1）。

## 5. 依据包

`src/byteproof/data/subset-audit.basis.json`：**22 条**（三分类两条 + layout 三条 +
name 一条 + metadata 四条 + SKIPPED 九条 + summary + generic 兜底三条），text 承载
旧仓 `data/README` §6.2/§6.3/§6.5/§6.9 判定口径原文要点；漏 basis → rc 3。
`subset-audit.thresholds.json` 快照 severity 序 / nameID 白名单 / LAYOUT_TAGS /
NOTDEF_NAMES / skip 理由词表 / verdict_map——与模块常量逐项相等（测试双向断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 6 文件实跑 **X = 188**（`188 passed in 24.96s`）/ 新仓实跑 **324 passed** | ✅ 过（324 ≥ 188） |
| 2 | README 示例命令 rc 相同 | 旧 `coverage-diff out/source.ttf --subset out/subset.ttf --text 汉字abc` rc **1**（2 条 LOST error：U+5B57/U+6C49 均 BMP；summary counts 3/0/2、blocks BMP 5）→ 新同场景 IR rc **1**（lost records U+5B57/U+6C49 blocks BMP/BMP、OK 3 码位、counts 3/0/2 逐项一致） | ✅ 过（1=1；判定内容逐项一致） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 6 文件；函数数**按条计** → 新 **169**（AST `test_`）/ 旧 **169**（AST `test`） | ✅ 过（169 ≥ 169） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`subset-audit.basis.json`（22 条）+ `.thresholds.json` 均在包内；解包 `list` = **23 器官**、样例 `check` rc **1**（丢字场景本就阻断） | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src py -3.12 -m pytest tests/test_core.py tests/test_coverage_diff.py \
  tests/test_cross_channel.py tests/test_fixtures.py tests/test_layout_survival.py \
  tests/test_metadata.py -o addopts="" -q -p no:cacheprovider
```

输出原文（py 3.12.10）：

```
188 passed in 24.96s
```

> D1+D18 机械剔除：`test_ci_workflow.py`（ci）→ 修正为**保留 ci 词不匹配**——ci_workflow
> 不含排除词（保留 6 文件实跑口径）；`test_cli.py`（cli）/ `test_license_gate.py`（license）/
> `test_report.py`（report）/ `test_self_counts.py`（selftest）/ `test_readme_scenarios.py`
> / `test_metadata.py` **保留**（metadata 不含排除词）等，机械筛后 12 − 6 = 6 文件。
> 夹具为临时合成字体（fontTools FontBuilder，pytest tmp_path），不落盘不入仓；
> `tools/gen_fixtures.py` 现场生成 6 fixture（数据目录 gitignore，来源仓
> `git status --porcelain` 全程 **0 行**，HEAD `bd727e7` 与队列一致）。
> 旧层 AST `test` 函数 169（core 43 / coverage_diff 22 / cross_channel 7 / fixtures 15 /
> layout_survival 45 / metadata 37——以 ast 计数为准）。

### 6.2 D1+D18 逐文件处置表（判定层 6 文件 / 旧层 169 函数）

| 旧仓测试文件 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|
| `test_core.py`（cmapset + canonical 共享层） | **已迁（判定全）** | 三分类 / glyph0 剔除 / 分区计数 / 闭包 / 回退链建议 / 格式化 / finding 构造与排序；§1 + §2。 |
| `test_coverage_diff.py` | **已迁（判定全）** | 每码位 finding / strict_source / evidence 实测 / 闭包只计数 / 两条 cmap 失败路径不合并；§3。 |
| `test_layout_survival.py` | **已迁（判定面）** | 三元组差集 / 连字码位差分 / 改名三态 / 两个 SKIPPED 不合并 / raw/naive/kept 分母不同；fontTools 读取折算为摊平事实（§4）。 |
| `test_metadata.py` | **已迁（判定面）** | name 三分类 / 码页 bit0 / 位域过度声明 / maxp / 首末码位哨兵；§5。 |
| `test_cross_channel.py` | **已迁（一致性面）** | 跨 fontTools 版本判定一致性的账本等价物 = 同输入 N 次运行逐字节一致 + evidence 无环境字段（§8）；oracle 文件/双解释器子进程是旧仓工具面，不迁。 |
| `test_fixtures.py` | **已迁（形状面）** | fixture 的 expect 真值结构（三分类 + LOST 码位）由 §3/§6 的同场景 IR 对账承担；合成器本体（gen_fixtures）不迁。 |

**D1+D18 机械剔除**：`test_cli.py`（cli，CLI 参数面宿主承担）/ `test_license_gate.py`
（license，模块整体不迁）/ `test_report.py`（report，渲染面）/ `test_self_counts.py`
（selftest，自计数门）/ `test_readme_scenarios.py`（README 场景回放——真值已由判据 2
同场景对账承担）/ `test_ci_workflow.py`（ci workflow 文本门，产品 CI 承担）。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/subset-audit.basis.json` | 9717（22 条） |
| `byteproof/data/subset-audit.thresholds.json` | 1752 |

wheel 总条目 **234**（#38 收口 227 + 本器官 7 件：`auditors/subset_audit/` 5 个 .py +
data 2 件）；解包 `list` = **23 器官**、仓样例 `check` rc **1**（丢字场景本就阻断——
契约正确，随包 basis 缺省可判）。构建树来自暂存区 tree 对象（`git write-tree` =
`5981c3c5…`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **fontTools 读取 → 输入层**：cmap 映射 / OS/2 位域 / nameID / 布局摊平 / 独立字形计数
   全部由输入层供证；判定核零第三方依赖。
2. **OS2_UNICODE_RANGES 表经 subject 供证**：旧仓纪律"本仓库不复制这张表"保持——器官
   同样不内置（架构测试断言 core.py 无该表字面量）。
3. **license-gate 模块不迁**（D1 排除词 license）：FSTYPE/许可面由产品门与旧仓承担；
   `core.finding` 对 license-gate module 显式 ValueError（架构测试钉住）。
4. **cmap 键容错**：旧仓 expect.json 摊平形态的键是 `"0x0061"` 字符串；器官 `codepoints`
   接受 int 或十六进制字符串键（对账时零转换摩擦）。
5. **cross_channel oracle 不迁**：跨 fontTools 版本一致性在账本形态的等价物 =
   确定性（N 次运行逐字节一致）+ evidence 无环境字段；oracle 文件与双解释器子进程是
   旧仓工具面。
6. **report 渲染 / digest `--verify` 面不迁**：宿主报告层；finding 排序口径
   （module → severity 序 → primary_key）1:1 保留在 `core.sort_findings`。
7. **metadata summary 键位差异**：旧仓 `coverage.required.blocks` 在 summary 顶层；
   账本把 summary 整体进 `sa-summary` 的 evidence——判定内容一致、承载层不同（同
   http-semantics 的 result 留档口径）。
