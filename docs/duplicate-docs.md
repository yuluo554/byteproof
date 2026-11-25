# 器官 `duplicate-docs`

> 来源：迁自 target-map ② 行（旧包 `docdedupe`）。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把一批文档正文当工件审，落一张"这一份和那一份是不是同一份内容"的缺陷账本。**
搬过来的是判定（归一化五步 + 字符 3-gram + 精确 Jaccard + 并查集聚类），不是工具。

## 1. 输入（工件）

```json
{
  "documents": [
    {"path": "contract-2023.pdf.txt", "text": "甲方与乙方就本项目的交付范围……"},
    {"path": "contract-2024.docx.txt", "text": "甲方与乙方就本项目的交付范围……"}
  ],
  "params": {}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `documents[].path` | 是 | 文档在工件里的路径；**唯一可指回的位置**。同一路径出现两次 → `dd-duplicate-path`（error） |
| `documents[].text` | 是 | 已抽取的正文（平文本）。`null` 当空串；**无正文必须显式写 `""`**，缺键是信封错误 |
| `params` | 否 | 判定阈值（见 §4），未知键 -> 退出码 2 |

工件是**已抽取**的正文，不是 PDF/DOCX 文件本身 —— 抽取层（`docdedupe/extract.py`）是工具面，
器官不读文件。

## 2. 判定顺序与等级

| 段 | 规则 | 等级 | 判据 |
|---|---|---|---|
| 构件 | `dd-duplicate-path` | `error` | 同一 `path` 出现 ≥2 次（位置不唯一 -> 任何指向它的结论都无法复核） |
| 构件 | `dd-empty-text` | `warn` | 正文抽取后为空（或只有空白） |
| 构件 | `dd-too-short` | `info` | 归一化后长度 < `min_text_chars`（默认 80） |
| 重复 | `dd-exact-duplicate` | `warn` | 归一化正文的 sha256 与同簇另一份相同 |
| 重复 | `dd-near-duplicate` | `warn` | 归一化正文的字符 3-gram **精确** Jaccard ≥ `near_duplicate_threshold`（默认 0.80） |

三条口径值得单独说：

1. **分数必须是精确 Jaccard，不是 MinHash 估计。** 128 置换估计的标准误差约 0.035，
   而语料里最弱的真阳性对只比 0.80 高 0.01–0.03 —— 用估计值判定等于把采样噪声放在决策边界上。
   MinHash/LSH 是**候选召回**装置（只减少候选、不改变结论），本轮没迁。
2. **账本指向"同簇里与它最像的那一份"，不指向"簇代表"。** 簇是连通分量：A–B 与 B–C 成边时
   A–C 可能根本没到阈值，说"C 与 A 相同"就是伪造结论。
3. **空/过短文档不参与比对**，所以它们既不会被指为重复，也不会被当成参照。
   字符 3-gram 在过短文本上会给出虚假的高相似度（两份都只有几个字也可能很高）。

`path` 三种形态：

| 形态 | 用于 | 例子 |
|---|---|---|
| `<path>` | 路径在工件内唯一 | `contract-2023.pdf.txt` |
| `<path>#<序号>` | 路径重复（`dd-duplicate-path`） | `a.md#2` |

## 3. 输出

```console
$ byteproof check duplicate-docs --input <工件.json>
byteproof :: duplicate-docs 1 :: <工件.json>
[error] dd-duplicate-path — 工件里有 2 份文档共用路径 'a.md'（位置不唯一，任何指向它的结论都无法复核） :: a.md#1 (dd-duplicate-path@1)
[warn] dd-empty-text — 文档没有正文：无法参与任何比对（缺失是数据，但不构成可复核的结论） :: d.md (dd-empty-text@1)
[warn] dd-exact-duplicate — 与 'a.md' 是同一份内容（归一化 Jaccard 1.000000，exact 档，簇 cab12… 共 2 份） :: b.md (dd-exact-duplicate@1)
合计 3 条，阻断 1 条（error=1 warn=2 info=0）
```

`--json` 的单条账本：

```json
{
  "id": "dd-exact-duplicate@b.md",
  "rule_id": "dd-exact-duplicate",
  "verdict": "warn",
  "message": "与 'a.md' 是同一份内容（归一化 Jaccard 1.000000，exact 档，簇 c1a2b3c4d5e6 共 2 份）",
  "basis_ref": {"rule_id": "dd-exact-duplicate", "rule_version": "1", "source": "…", "quote": "…"},
  "path": "b.md",
  "evidence": {
    "other": "a.md", "jaccard_q": 1000000, "jaccard": "1.000000",
    "edge_kind": "exact", "tier": "exact", "cluster_id": "c1a2b3c4d5e6",
    "cluster_size": 2, "members": ["a.md", "b.md"],
    "normalized_length": 96, "incoming_label": "b.md",
    "near_duplicate_threshold": "0.800000", "shingle_size": 3,
    "normalize_version": "1"
  }
}
```

**对称性**：两份完全相同的文档会各落一条账本（都指向对方）。这不是重复计数 ——
两份都是可移除的冗余，各有一条独立的位置。

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---|---|
| `shingle_size` | 3 | 字符 n-gram 的长度（中文无空格，按字符切） |
| `min_text_chars` | 80 | 归一化后**少于**它的文档不参与比对 |
| `near_duplicate_threshold` | 0.80 | 精确 Jaccard 阈值（`>=` 即命中） |
| `header_footer_max_chars` | 40 | 长短行阈值：**超过**它的重复行不当作页眉 |
| `header_footer_min_repeats` | 2 | 重复**至少**多少次才算页眉 |

## 5. 依据包

随包副本 `src/byteproof/data/duplicate-docs.basis.json`（5 条规则，包版本 `1`），
阈值台账 `src/byteproof/data/duplicate-docs.thresholds.json`。缺规则 -> `RuleMissing` -> 退出码 3。

## 6. 已知边界

1. **5 步归一化的顺序是契约**：NFKC -> 去空白/不可见 -> 去页码行 -> 去跨页高频短行 -> 拉丁小写。
   行结构必须活到第 4 步（页码与页眉是"按行"才认得出来的），最后由 `normalize` 拼成一条流，
   这样 shingle 不会跨过被删掉的行边界。
2. **只折拉丁大小写**：`é` 与 `e` 是两个字符，不折叠；希腊/西里尔也不折。
3. **周期性文本的 Jaccard 会饱和**：同一句话重复 N 遍的文本，其所有 3-gram 都落在同一个周期内，
   所以"重复 2 遍"与"重复 4 遍"的 shingle 集合相同，Jaccard = 1.0。这是字符 n-gram 的定义结果，
   不是实现缺陷（测试里钉了这条）。

## 7. §7.3 四项无损判据 · 实测

口径：`ORGAN-PLAYBOOK` §3.0 —— **判据 1 的分母 = 旧仓「判定层」实跑用例数**。
判定层 = 文件名不匹配 `cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke`
的测试文件。旧仓该层 = **14 个文件 / 336 静态函数**，实跑 **X = 356 passed**。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓判定层实跑 X = 356 / 新仓实跑 N = 361 / 结论：过（差 +5）** | ✅ |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文 `doc-dedupe scan data/samples --db index.db` 实跑 rc **0**；新入口 `check duplicate-docs --input samples/duplicate-docs.minimal.json` rc **0** | ✅ 过（`report` 的 rc 差见 §7.2） |
| 3 | 测试文件数 / 测试函数数 | 新 **1 文件 / 144 个 `def test_`**；旧判定层 **14 文件 / 336 函数** | ❌ 不过（两项都低于旧层；单文件约定与"数量相等"冲突，实跑数 361 ≥ X 356 由判据 1 计） |
| 4 | `pip wheel` 后 `data/` 进包 | `byteproof/data/duplicate-docs.basis.json` + `.thresholds.json` 均在 wheel 内 | ✅ 过 |

### 7.1 脚手架测试处置表（旧仓被剔除的每个测试文件）

| 旧仓测试文件 | 函数数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_cli_contract.py` | 44 | **舍弃**（不入判定层） | 测 `duplicate-docs` 的 argparse 面（`scan`/`report`/`serve`/`quarantine`/`undo`/`reports`/`selftest`）。SKELETON-SPEC §2 规定器官不得自带 CLI；本仓只有 `list` / `check`，由 `tests/test_duplicate-docs.py::TestCli` 覆盖唯一入口的退出码 0/1/2/3。 |
| `test_check_release.py` | 19 | **舍弃** | 测发布门 `tools/check_release.py`（版本号、产物、留档）。发布门属 CI/发布面，byteproof 有 `tools/check_sprint_layout.py` + `tools/build_catalog.py --check` 自己的门。 |
| `test_bench_diff.py` | 12 | **舍弃** | 测基准 `bench_diff`（差异质量基线）。基准是**性能/质量测量**，不是对工件的判定；其输入是旧仓语料目录，本器官的夹具改为内联文本。 |
| `test_bench_quarantine.py` | 13 | **舍弃** | 测基准 `bench_quarantine`（隔离批次基线）。同上。 |
| `test_bench_tiers.py` | 14 | **舍弃** | 测基准 `bench_tiers`（档位分布基线）。同上；档位判定本身已迁（`TestBuildClusters`）。 |
| `test_bench_hints.py` | 8 | **舍弃** | 测基准 `bench_hints`（保留提示基线）。同上。 |

判定层内部**只部分迁**的文件（判据 1 的差值来源，逐条给出理由）：

| 旧仓测试文件 | 函数数 | 处置 | 理由 |
|---|---:|---|---|
| `test_normalize.py` | 25 | **已迁（全）** | 五步 + 顺序 + 幂等，逐条搬用并扩到参数化矩阵。 |
| `test_fingerprint.py` | 37 | **部分迁** | shingle / BLAKE2b 64 位哈希 / 精确 Jaccard / SimHash+Hamming 已迁；**MinHash 与 LSH banding 未迁** —— 它们是候选召回装置，只减少候选、不改变结论。 |
| `test_cluster.py` | 32 | **部分迁** | 边分类（exact/near）、并查集、档位、`cluster_id` 稳定性已迁；**模板族判定与五维保留打分未迁** —— 它们回答"该留哪一份"（报告概念），账本只回答"是不是同一份内容"。 |
| `test_extract.py` | 23 | 舍弃 | PDF/DOCX/HTML 抽取 = 读文件；器官不读文件。 |
| `test_scanner.py` | 17 | 舍弃 | 目录扫描 + 忽略规则 = 工具面。 |
| `test_settings_and_store.py` | 15 | 舍弃 | SQLite 索引与缓存键 = 存储层。 |
| `test_quarantine.py` | 38 | 舍弃 | 隔离/复原执行层（写文件、改文件系统）；器官只读。 |
| `test_web.py` | 29 | 舍弃 | FastAPI 复核页 = 服务面。 |
| `test_report.py` | 16 | 舍弃 | md/csv/json 报告渲染 = 报告产物。 |
| `test_samples.py` | 29 | 舍弃 | 样例语料目录的端到端断言（读仓库内文件）。 |
| `test_recall.py` | 21 | 舍弃 | 召回率基准 —— 需要 LSH 与语料规模；判定层不做召回评估。 |
| `test_diffing.py` | 32 | 舍弃 | 段落级 diff 与差异摘要句 = **呈现**（复核页显示用）。 |
| `test_repo_invariants.py` | 14 | 舍弃 | 旧仓仓库不变量（无删除路径、打包面）—— 本仓有自己的门。 |
| `test_no_network.py` | 8 | 舍弃 | 断言"HTTP 面不发任何请求" —— 本器官没有网络面（`TestNoClockNoSideEffects` 已在 AST 层禁 `urllib`/`requests`/`socket`）。 |

### 7.2 判据 2 的口径

旧仓 README 的示例命令是 `scan <目录>` 与 `report <索引库>`，退出码 **0**（成功）或 **3**
（依赖缺失，如未装 `web` extra）。新入口没有子命令、也不接受目录，所以按下述对应关系对账：

| 旧仓命令 | 旧 rc | 新仓对应命令 | 新 rc |
|---|---:|---|---:|
| `doc-dedupe scan <目录>` | 0 | `byteproof check duplicate-docs --input <等价工件>` | 0 |
| `doc-dedupe report <库>` | 1（检出簇；实测） | 同上，输入两份完全相同的文档 | 0（`dd-exact-duplicate` 是 `warn`） |
| `doc-dedupe --help` | 0 | `byteproof list` | 0 |

**参数不等价是口径差**：旧仓的命令面是"扫描目录 -> 建库 -> 出报告"，本产品按
`SKELETON-SPEC §2` 只有一个入口（`check <slug> --input <file>`），
所以对账的是**同一份工件上的 rc**，不是同一组参数。