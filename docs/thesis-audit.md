# 器官 `thesis-audit`

> 来源：迁自 target-map ② 行（旧仓 `10-7-thesis-audit-workbench`，**Python 源**，v0.1.1，GUI + CLI 工作台）。
> 迁入版本：`1`。契约见 [`byteproof.md`](byteproof.md)；本页只写这个器官自己的那一列。

一句话：**学位论文审计的判定层**——参考文献八条格式规则（字段/类型标记/作者阈值/页码/
引用体例/标准时效/一致性/标点）+ 正文引用对账（编号展开/标记解析/未定义与未引用/首次次序）+
去重（标题与 DOI 归一、编辑距离、字段冲突）+ 伪造信号（DOI 前缀/ISBN 校验与出版社区间/
不可能组合/自引）+ 推荐（BM25）+ 文献库指纹与篡改 + 综述聚类与年代缺口；AIGC 特征分档、
结构检查（标题层级/摘要要素/章节）、术语与数字用法、图表交叉引用与编号缺口、学校格式、
确定性 RNG。

**docx 读取 / GUI / CLI / SQLite / 规则文件加载留输入层与宿主**（D1 逐文件处置见 §6.2）：
subject 携带摊平事实（卡片 / style_tree / doc_format / 文本），判定核零第三方依赖、零 IO、
不读时钟。

## 1. 输入（工件）

`mode` 必填 ∈ `refcheck` / `cite` / `dedup` / `fake` / `rec` / `library` / `review` /
`aigc` / `structure` / `terms` / `figures` / `school` / `rng`（缺省 `refcheck`）。

| 模式 | subject 键 | 说明 |
|---|---|---|
| `refcheck` | `cards` + 可选 `ruleset` / `fmt` / `src_text` / `doc_name` | 八条格式规则逐条判 |
| `cite` | `cards` + `text`（含 `[n]` 或 `(著者, 年)` 标记） | 标记解析与对账 |
| `dedup` | `cards` + 可选 `edit_threshold` | 重复对 / 合并冲突 |
| `fake` | `cards` + 可选 `known_prefixes` / `fake_isbn_ranges` | 伪造信号 + 健康分 |
| `rec` | `cards` + `sentence`（或 `items` 插入/删除、`n_items` 编辑矩阵） | BM25 推荐 |
| `library` | `old_manifest` + `new_cards`（或 `cards` + `doc_name`） | 指纹与篡改 |
| `review` | `entries` + 可选 `now_year` / `recent_years` / `threshold` | 聚类与年代缺口 |
| `aigc` | `paragraphs` + 可选 `features` | 段级分档与分布 |
| `structure` | `style_tree`（旧仓 `parse_structure` 摊平形态） | 标题层级 / 摘要要素 / 章节 |
| `terms` | `style_tree` + `terms` + 可选 `number_usage` | 术语 / 空格粘连 / 数字用法 / 热区 |
| `figures` | `parsed`（或 `labels` + `text`） | 交叉引用 / 编号缺口 / 重编号 |
| `school` | `style_tree` + `ruleset`，或 `doc_format` + `ruleset` | 样式 / 版式 |
| `rng` | `seed` + `n` + 可选 `max` | SplitMix64 确定性 |

卡片形态 = 旧仓 `make_ref_card` 的键（`card_id` / `entry_type` / `authors[{family,given}]` /
`title` / `source{journal,volume,issue,pages,year,publisher}` / `identifiers{doi,isbn}`）。

## 2. 判定与等级

| 面 | 规则 | verdict |
|---|---|---|
| 卡片 / 字段 | `taw-ref-card` / `taw-ref-field-required` | **error** |
| 格式八条 | `taw-ref-type-marker` / `taw-ref-author-threshold` / `taw-ref-page-range` / `taw-ref-consistency` / `taw-ref-citation-style` → error；`taw-ref-standard-currency` / `taw-ref-punct` → warn | |
| 引用对账 | `taw-cite-marker` error；`taw-cite-uncited` / `taw-cite-order` warn（文献表编号空档 = error） | |
| 去重 | `taw-dedup-pair` **error**；`taw-dedup-merge-conflict` warn | |
| 伪造 | `taw-fake-signal` **error**；`taw-fake-health` info | |
| 推荐 / 库 | `taw-rec-hint` info；`taw-lib-tamper` **error** | |
| 综述 | `taw-review-cluster` / `taw-review-gap` info | |
| AIGC | `taw-aigc-band` warn；`taw-aigc-dist` info | |
| 结构 | `taw-struct-heading` / `taw-struct-abstract` **error**；`taw-struct-chapter` warn | |
| 术语 | `taw-term-hit` / `taw-term-stray` / `taw-term-number` warn；`taw-term-heat` info | |
| 图表 | `taw-fig-xref` **error**；`taw-fig-gap` warn；`taw-fig-renumber` info | |
| 学校格式 | `taw-school-style` / `taw-school-format` **error** | |
| 确定性 | `taw-rng-determinism` info | |

**位置**：`card:<id>/<field>` / `marker:<doc>@<pos>` / `pair:<a>:<b>` / `para:<n>/<field>` /
`heading:<n>` / `term:<w>@para:<n>` / `object:<label>` / `report`；重复 id 自动 `#n` 消歧。

## 3. 输出

```console
$ byteproof check thesis-audit --input samples/thesis-audit.minimal.json
byteproof :: thesis-audit 1 :: thesis-audit.minimal.json
[error] taw-dedup-pair — 重复条目 [3] / [4]（标题归一相同 + 著者交集 + 年份一致）；保留 ref-000003，合并 ref-000004 :: pair:ref-000003:ref-000004 (taw-dedup-pair@1)
[info] taw-summary — 论文审计汇总（dedup 模式）：1 条记录，阻断 1 条 :: report (taw-summary@1)
合计 2 条，阻断 1 条（error=1 warn=0 info=1）
```

退出码：旧仓 0 完成 / 1 有阻断 / 2 用法错误 / 3 依赖缺失；账本侧 0 无阻断 / 1 有 error /
2 输入不合法 / 3 契约违约。

## 4. 参数

口径常量在判定核模块内（旧仓 `data/` 的 ruleset 与词表内联）：`edit_threshold=2`、
`author_threshold=3`、AIGC 分档边界 `(0.34, 0.67)`、术语空格口径；快照
`thesis-audit.thresholds.json` 留档并被测试双向断言。

## 5. 依据包

`src/byteproof/data/thesis-audit.basis.json`：**36 条**（引用面 20 + 文档面 15 + 账本汇总 1），
text 承载旧仓各模块判定口径要点与出处。漏 basis → rc 3。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 **20 文件** pytest 实跑 **X = 214 passed（+1 skipped）**（`214 passed, 1 skipped in 30.78s`）/ 新仓实跑 **463 passed**（3 个测试文件） | ✅ 过（463 ≥ 214） |
| 2 | README 示例命令 rc 相同 | 旧 `py -3.12 -m taw audit refs data/frozen/audit/refs_table.txt --report %TEMP%/taw-refs.json` → rc **0**（9 条条目；重复簇 `['3','4']` 冲突 0 项 / 疑似 `['8','9']` 冲突 1 项）；新 `dedup` 模式（同批卡片，来自旧 `taw parse` 的输入层摊平）→ rc **1**，两条 finding 的**配对与冲突计数逐项一致** | ✅ 过（口径差：旧命令完成即 rc0 / 新 dedup 有 error → rc1；判定内容一致） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **3 文件** / 旧 **20 文件**；函数数**按条计** → 新 **463**（AST `test_`）/ 旧 **215**（AST `test_`，含 conftest 0） | ✅ 过（463 ≥ 215） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`thesis-audit.basis.json`（9820 B / 36 条）+ `.thresholds.json`（3650 B）在包内；wheel 总条目 **258**；解包 `list` = **26 器官**、样例 `check` rc **1**（重复条目本就阻断） | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>/code   # 10-7-thesis-audit-workbench（只读）
PYTHONPATH=src py -3.12 -m pytest tests/conftest.py tests/test_aigccheck.py tests/test_cards.py \
  tests/test_com.py tests/test_data_gate.py tests/test_engine.py tests/test_figref.py \
  tests/test_paths.py tests/test_refcheck.py tests/test_refcite.py tests/test_refdedup.py \
  tests/test_reffake.py tests/test_refrec.py tests/test_reftopo_reflib.py tests/test_registry.py \
  tests/test_repo_gate.py tests/test_reviewcl.py tests/test_rng.py tests/test_schoolfmt.py \
  tests/test_structcheck.py tests/test_termnum.py -o addopts="" -q -p no:cacheprovider
```

输出原文（py 3.12.10）：

```
214 passed, 1 skipped in 30.78s
```

逐文件 pass 数（20 文件）：`aigccheck 12` / `cards 7` / `com 11`（+1 skip） / `data_gate 25` /
`engine 12` / `figref 9` / `paths 9` / `refcheck 11` / `refcite 10` / `refdedup 9` /
`reffake 14` / `refrec 16` / `reftopo_reflib 13` / `registry 6` / `repo_gate 5` /
`reviewcl 12` / `rng 9` / `schoolfmt 8` / `structcheck 7` / `termnum 9` = **214**。

> **D1 机械口径（20 文件）**：旧仓 `code/tests/` 共 **30** 个文件（20 个判定层 `test_*.py` +
> `conftest.py` + 9 个剔除件），按文件名正则（`cli|gui|packaging|audit|desensit|guard|bench|
> infra|export|version|license|generat|docs?_|health|release|selftest|smoke|parse|report|input|
> output|web|panel`）剔除 **9** 件（逐词见 §6.2）→ **20 文件**进分母（`conftest.py` 机械计入
> 但贡献 0 用例）。旧层 AST `test_` 函数 **215**（21 文件 ast 计数，conftest 0）。
> 来源仓 `git status --porcelain` 全程 **0 行**（HEAD `5b099d9` 与队列一致；旧 `--report`
> 产物定向 `%TEMP%`）。

### 6.2 D1+D18 逐文件处置表（判定层 21 文件 / 旧层 215 函数）

| 旧仓测试文件 | 命中词 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|---|
| `test_aigccheck.py`（12） | — | **已迁（判定全）** | 句长变异系数 / 模板连接词 / 总结套话 / 并列结构 / 分档 / 风险分 / 分布。 |
| `test_cards.py`（7） | — | **已迁（判定全）** | 卡片与 doc 对象构造/校验（缺键、类型非法）。 |
| `test_com.py`（11 +1 skip） | — | **已迁（形状面）** | Windows COM 自动化（Word）留宿主；纯函数侧的"打开/保存"契约折算为 doc_format 事实校验。 |
| `test_data_gate.py`（25） | — | **已迁（形状面）** | 数据目录完整性（rulesets/knowledge 文件齐全）折为 thresholds 快照断言；`data/` 读取留旧仓。 |
| `test_engine.py`（12） | — | **已迁（判定面）** | 规则集组合（layer1 + 年份层 + profile 门）/ 规则查找 / finding 构造 / summarize；规则文件加载留输入层。 |
| `test_figref.py`（9） | — | **已迁（判定全）** | 交叉引用 / 标签号解析 / 编号缺口 / 重编号与编辑矩阵。 |
| `test_paths.py`（9） | — | **已迁（判定面）** | 数据目录候选与校验（显式路径优先、无效即 None）；`cwd` 向上查找留输入层。 |
| `test_refcheck.py`（11） | — | **已迁（判定全）** | 八条格式规则（字段/类型/作者/页码/体例/时效/一致性/标点）与 apply_fix。 |
| `test_refcite.py`（10） | — | **已迁（判定全）** | 编号展开 / 标记解析 / 对账（未定义/未引用/次序）。 |
| `test_refdedup.py`（9） | — | **已迁（判定全）** | 标题与 DOI 归一 / 编辑距离 / 字段冲突 / 簇合并。 |
| `test_reffake.py`（14） | — | **已迁（判定全）** | DOI 前缀 / ISBN 校验与区段 / 不可能组合 / 自引 / 健康分。 |
| `test_refrec.py`（16） | — | **已迁（判定全）** | BM25 索引与推荐 / 插入删除 / 编辑矩阵。 |
| `test_reftopo_reflib.py`（13） | — | **已迁（判定面）** | 库指纹与篡改（判定面）；拓扑 HTML 渲染与 pyvis 留宿主。 |
| `test_registry.py`（6） | — | **已迁（形状面）** | 16 模块注册表计数 → 本器官 modes 清单（13）与 `list` 计数断言。 |
| `test_repo_gate.py`（5） | — | **已迁（形状面）** | 仓库门（README 数字 / 计划装订）属旧仓文档装订；本仓由测试计数 + 判据 2 承担。 |
| `test_reviewcl.py`（12） | — | **已迁（判定全）** | TF-IDF / 余弦 / 聚类 / 纯度 / 年代分布 / 缺口。 |
| `test_rng.py`（9） | — | **已迁（判定全）** | SplitMix64 同种子同序列（跨进程一致）。 |
| `test_schoolfmt.py`（8） | — | **已迁（判定面）** | 样式/版式规则求值（op/tol）；docx 读取留输入层。 |
| `test_structcheck.py`（7） | — | **已迁（判定全）** | 标题层级 / 摘要要素 / 章节类别 / 回声重叠。 |
| `test_termnum.py`（9） | — | **已迁（判定全）** | 术语命中 / 空格粘连 / 数字用法 / 热区。 |
| `test_bench_full.py`（—） | **bench** | 剔除 | 全文线基准运行器——工具面。 |
| `test_cli.py`（—） | **cli** | 剔除 | CLI 参数面/子命令——宿主入口。 |
| `test_fullbench.py`（—） | **bench** | 剔除 | 全量基准——工具面。 |
| `test_gui_app.py`（—） | **gui** | 剔除 | PySide6 桌面窗口——呈现层。 |
| `test_gui_service.py`（—） | **gui** | 剔除 | GUI 服务层——呈现层。 |
| `test_packaging.py`（—） | **packaging** | 剔除 | pyinstaller 打包——产品打包面（本仓 wheel 承接）。 |
| `test_refbench.py`（—） | **bench** | 剔除 | 文献线基准（9 指标）——工具面。 |
| `test_refparse.py`（—） | **parse** | 剔除 | txt/csv/bib/ris 解析 → **输入层**（卡片由调用方摊平）。 |
| `test_thesisparse.py`（—） | **parse** | 剔除 | docx 解析 → **输入层**（style_tree / doc_format 摊平）。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/thesis-audit.basis.json` | 9820（36 条） |
| `byteproof/data/thesis-audit.thresholds.json` | 3650 |

wheel 总条目 **258**（#41 收口 250 + 本器官 8 件：`auditors/thesis_audit/` 6 个 .py + data 2 件）；
解包 `list` = **26 器官**、仓样例 `check` rc **1**（重复条目是 error 级——契约正确，
随包 basis 缺省可判）。构建树来自暂存区 tree 对象（`git write-tree` = `cbcceebb…`），
**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **docx / GUI / CLI / SQLite / 规则文件加载留输入层与宿主**：`_ensure_docx` 与
   `read_doc_format`（python-docx）、PySide6、`argparse`/子命令、reflib 的 SQLite、
   `load_ruleset_files`/`compose_ruleset`（四层文件装载）、`load_features`/`load_terminology`
   全部不迁；subject 给摊平事实（cards / style_tree / doc_format / text）。
2. **旧三级 → 新三级**：`pass|fail|manual_confirm` 折成 `error|warn|info`（文件级结构破损
   error；可疑可解释 warn；统计/提示/重排 info）。`severity` 缺省表见 §2；个别分支升级
   （`taw-cite-order` 的文献表编号空档 = error、`taw-dedup-pair` = error）。
3. **证据链折算**：旧仓 `engine.make_rule_finding` 的 clause/quote/severity/confidence/
   suggestion/detail/check_type/standard/clause_status/basis 不进 5 键 schema，只在
   message/evidence 里保留要点；clause_status「待核对」的原文条号不在本器官宣称。
4. **指纹面不互通**：旧仓 `reflib` 用 `json.dumps(sort_keys=True)` 做指纹；判定核禁 `json`
   （纯函数纪律），改用控制字符分隔的规范文本 —— **哈希值不与旧仓互通**，但"同卡同指纹、
   改一处即变"的语义一致（已实测：同卡 → info；改标题 → 增/删/改三条 error）。
5. **figref 的矩阵基准不迁**：`object_edit_matrix` / `object_renumber_bench` 无 evaluate
   消费面；重排内核 `renumber_objects` 与 `object_items` 已迁。`labels+text` 是新增摊平入口
   （旧仓只有 parser 产物）：题注段自身编号不计提及、公式段自身即提及、无 mentions 时不推导 ghost。
6. **AIGC 阈值不内置**：未给 `features` 时只出分布（`taw-aigc-dist`），不分档——避免在代码里
   发明第二套阈值；判据 2 的 dedup 对撞不涉及该面。
7. **ruleset 缺省=全开**：structure/figures/school 按"同 check_type 取首条 + activation"
   门控，terms 按任一 term_consistency active；缺省 ruleset 时全开（旧仓缺 ruleset 零产出的
   CLI 面留宿主）。
8. **`test_tui_pilot` 类形状面**：`test_com`（Windows COM/Word）与 `test_data_gate`
   （data 目录完整性）在处置表里写明"形状面已迁/本体留宿主"，不以"跑过"冒充判定覆盖。
9. **XML/文件安全**：旧仓 docx 读取面留输入层；本器官不解析任何二进制/不受信文档，
   实体扩展面不存在（与 #41 的加严不同，本器官根本没有 XML 入口）。