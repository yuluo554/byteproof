# 器官 `browser-history-vault`

> 来源：迁自 target-map ② 行（旧仓 `10-18-browser-history-vault`，包 `browser_history_vault`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**浏览器历史长期档案的隐私门禁 + 行为洞察 + 主题聚类 + 检索**——浏览器只留
90 天历史然后静默删除（Chromium `kExpireDaysThreshold = 90` 源码可证），"长期趋势"
只能在自有档案库上回答。纯判定面移植；SQLite 快照/归档、文件 I/O、单文件 HTML 报告、
CLI 留在输入层/报告层。

## 1. 输入（工件）

`mode` 与 `rows` 必填；`options` 必填（数值口径唯一来源 = subject，器官**零默认值**，
任何键缺失即 rc2）。`mode` ∈ `audit`（normalize+report+cluster+search 一次跑完）/
`normalize` / `report` / `search` / `cluster`。

| 键 | 形态 | 说明 |
|---|---|---|
| `rows[]` | `{visit_id, url, title, host, visit_time_us, source_browser, source_profile, transition?, visit_duration_us?}` | 归档库的规范化行；1601 纪元微秒 |
| `options.privacy` | `{private_domains[], sensitive_domains[]}` | 私密=完全排除；敏感=保留统计只打码 |
| `options` 其余 | `timezone_utc_offset_minutes` / `session_gap_minutes` / `report_top_n` / `weekday_start` / `today_local_date` / `forgotten_*` 三阈值 / `cluster_*` 五阈值 / `search_ngram_n` / `search{}` | 阈值全部来自 subject（K2/K15） |

**禁真实用户数据**：测试与样例全部用合成 `*.test` 域名行集。

## 2. 判定顺序与等级

旧仓五个功能命令（report/search/cluster/archive/snapshot）**完成即 rc0**（洞察是辅助
参考，不阻断）→ 本账本**全部规则 info 级**，语义与阈值写进 evidence；私密主机走到
输出面 = 门禁被绕过，当场 ValueError（rc2，fail-closed）。

| 模块 | 判什么 | 规则 |
|---|---|---|
| 隐私门禁 | 逐主机分类 | `bh-privacy-private-excluded` / `bh-privacy-sensitive-masked` info（逐主机计数 + 不可逆指纹）；匹配 = host==项 或 `.`+项 结尾，私密优先 |
| 覆盖区间 | 档案覆盖缺口 | `bh-coverage-gap` info：按**口径时区本地日**统计，连续**缺失**日合并为缺口；<90 天提示；不补齐不插值；私密记录也计入覆盖 |
| 会话切分 | 行为段 | `bh-session-stats` info：按 (browser, profile) 分组、组内 (time,url) 升序、相邻间隔**严格大于**阈值才切 |
| 遗忘宝藏 | 四条件命中 | `bh-forgotten-treasure` info：天数严格大于 + 次数≥ + 跨本地日≥ + 主机公开；无数据 → `not_assessed`（『没查』≠『查了没问题』） |
| 主题聚类 | 词族分组 | `bh-topic-cluster` info：df 是文档频率；合并 = Jaccard≥阈值**且一方包含**（防链式吞并）；与私密主机同形的词不进词表 |
| 研究路径 | 会话跳转序列 | `bh-research-path` info：每步带 visit_id 可下钻 |
| 检索 | 字 n-gram | `bh-search-hit` info：检索面=标题∪URL；域名含子域过滤；分页稳定（-time, visit_id）；命中 URL/标题过 redact_text |
| 规范化 | 去重键 | `bh-normalize-duplicate` info：重复键确定性保留首条 + 显式计数 |

## 3. 输出

`evidence` 逐段：隐私（host/计数/fingerprint/掩码形态）、覆盖（区间/缺口/declaration/note）、
会话（split_rule/直方图/largest 带 visit_ids）、遗忘（definition/conditions/thresholds/items）、
聚类（terms/urls/visits/visit_ids/thresholds）、路径（steps[]）、检索（redacted 文档 +
matched 总数 + query 回显）、汇总（records/visible/private_excluded）。

输出示例（`samples/browser-history-vault.minimal.json`，干净树，rc 0）：

```console
$ byteproof check browser-history-vault --input samples/browser-history-vault.minimal.json
[info] bh-coverage-gap — 覆盖 …：2 天区间 / 2 天有访问 / 1 个缺口（…不补齐：缺口如实列出） :: coverage.summary
[info] bh-research-path — 研究路径 会话1（chrome@Default）：2 步 :: paths.session-1
[info] bh-search-hit — 命中 visit 1：使用指南（docs.example.test） :: search.hits[0]
[info] bh-topic-cluster — 簇 1：2 个 URL / 2 次访问（词：docs、docs.example.test） :: cluster.cluster-1
[info] bh-summary — mode=audit：记录 3 条（可见 3 / 私密排除 0）→ 账本行 7 条 …
合计 8 条，阻断 0 条（error=0 warn=0 info=8）
```

退出码映射：旧五命令完成即 0 → 新 rc **0**（无阻断；全 info）；旧 2（配置/输入不可用）
→ 新 2。

## 4. 参数

阈值全部来自 `options`（旧仓 config.py 的数值口径唯一来源原则照搬）：`cluster_min_df` /
`cluster_max_features` / `cluster_top_terms` / `cluster_similarity_threshold` /
`session_gap_minutes` / `forgotten_days_threshold` / `forgotten_min_visits` /
`forgotten_min_distinct_days` / `report_top_n` / `search_ngram_n` /
`timezone_utc_offset_minutes` / `weekday_start` / `today_local_date`（器官不读时钟）。
`random_seed` 仅回显（聚类不引随机初始化）。

## 5. 依据包

`src/byteproof/data/browser-history-vault.basis.json`：10 条规则（隐私两态/覆盖/会话/
遗忘/聚类/路径/检索/规范化/汇总），每条带 `source` 与 40+ 字口径文本。
`browser-history-vault.thresholds.json` 同步快照 canonical 字段契约、已知浏览器、
星期起算日、遗忘四条件、会话切分口径串与检索排序白名单——运行期常量必须与它逐项
相等（测试断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 15 文件 pytest 实跑 **X = 223**（`223 passed in 10.80s`）/ 新仓实跑 **226 passed** | ✅ 过（226 ≥ 223） |
| 2 | README 示例命令 rc 相同 | 旧 `selftest --data-root data` rc **0**（7/7 项 PASS，离线）；旧五功能命令完成即 0 → 新干净样例 rc **0** / 有缺口·有私密·有聚类的工件 rc **0**（语义在 evidence） | ✅ 过（0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 15 文件；函数数**按条计** → 新 **191**（AST）/ 旧 **183**（AST） | ✅ 过（191 ≥ 183） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`byteproof/data/browser-history-vault.basis.json` **6361B / 10 条** + `.thresholds.json` **1447B** 均在包内；解包 `list` = **16 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest tests/test_archive_idempotence.py \
  tests/test_canonical_parity.py tests/test_cluster_command.py tests/test_config_single_source.py \
  tests/test_line_endings.py tests/test_module_entrypoints.py tests/test_no_network.py \
  tests/test_privacy_gate.py tests/test_readme_gate.py tests/test_reference_isolation.py \
  tests/test_sdist_manifest.py tests/test_sessions_parity.py tests/test_snapshot_readonly.py \
  tests/test_synthetic_fixture.py tests/test_timeutil.py -o addopts="" -q -p no:cacheprovider
```

输出原文：`223 passed in 10.80s`。

逐文件 passed：archive_idempotence 16 / canonical_parity 10 / cluster_command 22 /
config_single_source 32 / line_endings 4 / module_entrypoints 4 / no_network 15 /
privacy_gate 18 / readme_gate 11 / reference_isolation 7 / sdist_manifest 3 /
sessions_parity 17 / snapshot_readonly 14 / synthetic_fixture 36 / timeutil 14 = **223**。
被剔除文件（D1+D18）：`bench`（test_bench_falsifiable）、`cli`（test_cli_exit_codes）、
`guard`（test_encoding_guard）、`generat`（test_generator_mutation）、`audit`
（test_network_audit）、`report`（test_report_html / test_report_insights）、
`release`（test_release_gate）、`selftest`（test_selftest_falsifiable /
test_selftest_fixtures）。新器官 `tests/test_browser-history-vault.py` 实跑
**226 passed**、AST `test_` 函数 **191**。

### 6.2 D1+D18 逐文件处置表（判定层 15 文件 / 旧层 183 函数）

| 旧仓测试文件 | passed/函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_archive_idempotence.py` | 16/16 | **舍弃（存储层）** | 归档幂等是 SQLite 写路径（重复归档不重复落库）；器官不写库，收规范化行。 |
| `test_canonical_parity.py` | 10/8 | **已迁（判定全）** | host_of 两份实现同口径、规范化序、去重键唯一；在 `norm`。 |
| `test_cluster_command.py` | 22/20 | **已迁（判定全）** | 词族分组+高同现合并、防链式吞并、同形词禁入词表、输入序无关；在 `cluster`。 |
| `test_config_single_source.py` | 32/17 | **部分迁** | 阈值消费与"零默认值"校验（缺键即拒）迁为 options 校验；config 文件加载/来源回显属输入层。 |
| `test_line_endings.py` | 4/4 | **舍弃（产品级）** | 仓级 LF 行尾门，由产品 `tools/check_sprint_layout.py` 同类静态门接管。 |
| `test_module_entrypoints.py` | 4/4 | **舍弃（产品级）** | 模块入口面（`python -m` 等价）属产品仓装订。 |
| `test_no_network.py` | 15/9 | **舍弃（产品级）** | netguard AST 零网络门属产品仓静态门；本仓 CI offline docker 腿 + `test_gates.py` 同责。 |
| `test_privacy_gate.py` | 18/10 | **已迁（判定全）** | 三态分类、匹配边界、掩码、指纹、redact_text、fail-closed；在 `privacy`。 |
| `test_readme_gate.py` | 11/11 | **舍弃（产品级）** | README 命令一致性门属产品仓文档门。 |
| `test_reference_isolation.py` | 7/7 | **舍弃（产品级）** | 参照实现隔离的 AST 白名单门属产品仓静态门（本器官单实现，无参照双份）。 |
| `test_sdist_manifest.py` | 3/3 | **舍弃（产品级）** | 打包清单门属产品仓打包面。 |
| `test_sessions_parity.py` | 17/15 | **已迁（判定全）** | 严格大于才切、来源/profile 分组、次键排序、session_id 编号、直方图；在 `sessions`。 |
| `test_snapshot_readonly.py` | 14/11 | **舍弃（I/O 层）** | 快照复制/WAL 折叠是文件 I/O（D18 `input` 域）；器官只读规范化行。 |
| `test_synthetic_fixture.py` | 36/34 | **部分迁** | 合成数据真值语义（隐私清单/会话/遗忘形态）由等价合成行集在器官测试内联；生成器与 68 条冻结真值文件不迁。 |
| `test_timeutil.py` | 14/14 | **已迁（判定全）** | 1601 纪元整数换算、固定偏移、星期起算日平移；在 `timeutil`。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/browser-history-vault.basis.json` | 6361 |
| `byteproof/data/browser-history-vault.thresholds.json` | 1447 |

wheel 总条目 **162**；解包后 `byteproof list` = **16 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **存储/快照面不迁**：SQLite 只读打开、schema 校验、WAL 折叠、增量归档幂等都是
   I/O（D18 `input` 域）；subject 直接给规范化行（含 visit_id）。
2. **全部 info 级**：旧五命令完成即 rc0 → 新账本无 error/warn；缺陷语义（缺口/私密
   排除数/遗忘命中）写进 evidence，rc 恒 0 对齐。
3. **阈值来源**：旧仓 config.json（文件）→ subject.options（工件内）；零默认值原则
   照搬——缺键即 rc2，不猜"合理值"。
4. **渲染面不迁**：单文件 HTML、sparkline 字符画（K16 渲染层禁算术）、CSV 写盘属
   报告层；`spark_level` 作为数据层口径保留（同一档案两次渲染必同等级）。
5. **参照双实现不迁**：旧仓 production/reference 两份实现 + AST 隔离门是仓内差分
   自证；器官单实现，语义保真由上述判定测试承担。
6. **`today_local_date` 显式化**：旧仓 CLI 注入"今天"；器官要求 subject 显式给参考日
   （ISO 串），不读系统时钟。
