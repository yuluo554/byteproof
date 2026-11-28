# 器官 `http-semantics`

> 来源：迁自 target-map ② 行（旧仓 `10-19-http-semantics-mcp`，**Python 源**，包 `http-semantics-mcp` 0.2.0）。
> **MCP 壳留旧仓**：JSON-RPC/stdio 传输、schemas、registry、server、协议门都不迁——只迁判定。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**HTTP 语义判定 oracle——CORS check（A1–A6/P1–P6 分支）、重定向链逐 hop 仿真
（occurrence-order events/hops）、RFC 9111 新鲜度（C1–C11）、前置条件优先级（E1–E5，
If-Match 强比较 / If-None-Match 弱比较）、Vary 缓存键（V1–V4，规范化策略是数据）**。
旧仓判定层（`judgement/` 六模块 + `canonical`）1:1 移植：**不联网、不读文件、不读环境
变量、不读时钟——`now` 是参数不是时钟读数**（旧仓决策 D7）。措辞唯一来源是随包
`http-semantics.basis.json`（旧仓 `rules.py` CATALOG 生成件逐字节迁入：模板 / 含义 /
spec_ref / severity 四元组 31 条 + `hs-summary`）。

## 1. 输入（工件）

`mode` 必填 = 旧仓五个 MCP 工具名之一；`arguments` 必填 = 旧仓 `tools/call` 的 arguments
对象（**逐字段同名**——判据 2 可以真的同参重跑）。

| `mode` | 判什么 | arguments 核心字段 |
|---|---|---|
| `cache_evaluate` | 存储响应能否不回源直出 | `now` / `response_headers` / `stored{stored_at, age, headers}` / `request_headers` |
| `conditional_evaluate` | 哪条前置条件决定状态码 | `method` / `request_headers` / `resource{etag, last_modified}` |
| `cors_evaluate` | 响应能否过 Fetch CORS check | `method` / `url` / `origin` / `credentials` / `request_headers` / `response{status, headers}` / `is_preflight` |
| `cors_simulate_fetch` | 重定向链逐 hop 会怎样 | 同上 + `mode`(cors/no-cors/same-origin) / `redirects[{status,url,headers}]` |
| `vary_match` | 存储条目能否复用于该请求 | `cached{vary, request_headers_at_store}` / `incoming{request_headers}` |

| 顶层键 | 形态 | 说明 |
|---|---|---|
| `thresholds` | 对象（可选） | severity / vary_normalization / preflight_cache_key 表；缺省用模块内联常量（与随包 `http-semantics.thresholds.json` 快照逐项相等，测试双向断言）。器官不读文件：这张表随 subject 传入或走代码常量 |

## 2. 判定与等级

账本 verdict 由旧仓 catalogue 的 **severity** 决定：`decisive`（22 条：block / revalidate /
miss 的决定性 finding）→ **error 阻断**；`informational`（9 条：启发式、坏 Age、忽略的坏
日期、opaque origin 等）→ **info**。本器官不产 warn。

| 模块 | 判什么 | 关键纪律（旧仓原文照搬） |
|---|---|---|
| `cors` | A1–A6 / P1–P6 | safelisted 判据是**值级**的（accept 字节集 / content-type essence / bytes=N-M 单区间）；`authorization` 永不 safelist、永不被 `*` 覆盖；notes 三键恒出现（缺了就没法逐字节比对） |
| `fetch_sim` | 逐 hop 判 | `events[]` 保序不排序（origin_set_to_null 先、credentials_dropped 后）；`hops[]` 记**被请求的** URL，occurrence order；same-origin 拒跨源、no-cors 不看 CORS 头（opaque） |
| `cache` | C1–C11 | 无时钟（now 是参数）；整数秒（10.5 是 unparsable 不是"略过期"）；stale 是严格 `<`（等于即过期）；no-store 短路；s-maxage > max-age > Expires−Date > 启发式（≤24h、÷10）；SWR 窗口 |
| `conditional` | E1–E5 | **顺序即答案**（首个适用者决定，后面的根本不读）；strong/weak 两套比较不是一套带旗标；坏资源字段=caller mistake、坏请求日期=忽略并进 explain；`*` 需要当前表示存在 |
| `vary` | V1–V4 | `Vary: *` 在字段比较**之前**决定 miss；"absent" 与 "present but empty" 归一同值但经 `VARY_FIELD_MISSING` 区分报告；字段重复报首个 |

输出（`evidence.result` = 旧仓工具结果**整体**）：`hs-summary` 一条 info 记录留档完整
result 对象；每条 finding 单独成账本行（rule_id=旧 code、message=模板渲染 detail、
evidence 带 spec_ref 与 severity）。fetch_sim 的 findings 藏在 `hops[].violations`，
path 取命中 hop 的 `hop[i]:<url>`。

## 3. 输出

人读格式由宿主 CLI 排版；`--json` 机器可读且确定性。`canonical.dumps`（sort_keys +
ensure_ascii=False + 紧凑分隔符 + 禁 NaN）随器官迁移，golden 对撞按它逐字节比对。

输出示例（`samples/http-semantics.minimal.json` = 旧仓 README 手算示例同参，rc 0）：

```console
$ byteproof check http-semantics --input samples/http-semantics.minimal.json
byteproof :: http-semantics 1 :: http-semantics.minimal.json
[info] hs-summary — mode=cache_evaluate：findings=0（decisive→error 0 / informational→info 0） :: summary (hs-summary@1)
合计 1 条，阻断 0 条（error=0 warn=0 info=1）
```

退出码映射（判据 2 实测见 §6.1 对撞）：

| 旧仓情形 | 旧 rc | 新账本 | 新 rc |
|---|---:|---|---:|
| 判定成功、无 decisive finding | 0 | info 级 | 0 |
| 判定成功、含 decisive finding | 0（MCP 恒 0） | decisive → error | **1（口径差）** |
| caller mistake（坏时间/坏头名/坏方法） | 0（isError 结构化结果） | 抛 ValueError | **2（口径差）** |
| 规则包缺失 | — | RuleMissing → 契约违约 | 3 |

## 4. 参数

无 CLI 灰区开关：五个工具的 arguments 就是全部输入面（旧仓工具也无旗标——"Modes are
explicit rather than inferred"）。`thresholds` 表可经 subject 覆盖（severity 行级覆盖，
测试覆盖 `VARY_FIELD_MISMATCH→informational` 折算演示）。不迁：MCP 传输参数、
`--version`（宿主 CLI）。

## 5. 依据包

`src/byteproof/data/http-semantics.basis.json`：**32 条**（31 条 = CATALOG 生成件逐字节
迁入——`rule_id`=旧 code、`title`=meaning、`source`="迁自…；出处：" + `; `.join(spec_ref)、
`text`=template；+1 条 `hs-summary` 汇总规则，同 `va-summary` 先例）。模板渲染走
`Basis.require(code)`——**措辞不在器官代码里**（旧仓"wording is read from the generated
catalogue, never written here"纪律原样保留）；漏 basis → RuleMissing → rc 3。
`http-semantics.thresholds.json` 快照 severity 表 / vary_normalization 四字段策略 /
preflight_cache_key（sha256 前 16 位）/ error_codes / redirect 状态集——与模块内联常量
逐项相等（测试双向断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 23 文件实跑 **X = 367**（`367 passed in 11.86s`）/ 新仓实跑 **476 passed** | ✅ 过（476 ≥ 367） |
| 2 | README 示例命令 rc 相同 | 旧 README 手算示例（printf 管线）rc **0**（structuredContent 与 golden cache-001 逐字节一致）/ 超期例旧 rc **0**（decisive finding 在结果里）/ 坏时间例旧 rc **0**（isError:true）→ 新：fresh rc **0**（result 逐字段一致）/ stale rc **1** / badtime rc **2**（同码同 detail）。两处 rc 差 = 口径差（接受，§7.1–7.2） | ✅ 过（0=0；两处按口径差逐字段对齐） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** + 87 份 golden 夹具 / 旧 23 文件；函数数**按条计** → 新 **270**（AST `test_`）/ 旧 **259**（AST `test`） | ✅ 过（270 ≥ 259） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`byteproof/data/http-semantics.basis.json`（32 条）+ `.thresholds.json` 均在包内；解包 `list` = **20 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
py -3.12 -m pytest tests/test_cache_golden.py tests/test_canonical.py tests/test_ci_workflow.py \
  tests/test_conditional_golden.py tests/test_cors_golden.py tests/test_coverage_matrix.py \
  tests/test_determinism.py tests/test_entry_point.py tests/test_gates.py tests/test_gen_codes.py \
  tests/test_golden.py tests/test_m1_gates.py tests/test_mirrors.py tests/test_protocol.py \
  tests/test_readme_count.py tests/test_readme_gate.py tests/test_registry.py \
  tests/test_schema_parity.py tests/test_server_transport.py tests/test_stdio_end_to_end.py \
  tests/test_stdio_process.py tests/test_vary_golden.py tests/test_wpt_ledger.py \
  -o addopts="" -q -p no:cacheprovider
```

输出原文（py 3.12.10，本机）：

```
367 passed in 11.86s
```

> D1+D18 机械剔除：`test_packaging.py`（packaging）/ `test_release_gate.py`（release）/
> `test_utf8_guard.py`（guard）3 件不进分母；26 - 3 = 23 文件。
> 旧层 AST `test` 函数 259（逐文件 ast 计数）。来源仓 `git status --porcelain` 全程 **0 行**，
> 旧 CLI 输出定向 stdout（无文件写入），HEAD `725d71a` 与队列一致。
>
> golden 87 份案例文件（80 工具 + 7 `_time`）从旧仓 `data/golden/` **原样复制**为
> `tests/fixtures/http-semantics-golden/`（case_id / source / spec_basis 保留，来源可追溯）；
> 逐案例三断言 = 结果逐字节 + 键集冻结 + 双跑一致（旧仓 test_cache_golden /
> test_golden OUTPUT_KEYS / test_determinism 三个聚合断言的逐案例展开）。

判据 2 对撞原文（旧侧；`PYTHONPATH=src py -3.12 -m http_semantics_mcp`，stdin 管线）：

```text
$ <initialize/initialized/tools/call cache_evaluate now=00:00:30> → rc 0
  structuredContent = {"action":"serve","current_age":30,"freshness_lifetime":60,"is_fresh":true,
    "must_revalidate":false,"reasons":[],"stale_while_revalidate_window":0}
$ <tools/call cache_evaluate now=00:01:00（超期边界）> → rc 0（MCP 恒 0）
  reasons = [{"code":"CACHE_AGE_EXCEEDS_LIFETIME","detail":"current_age=60 is not below freshness_lifetime=60",
    "spec_ref":["RFC9111 §4.2","RFC9111 §4.2.3"]}]
$ <tools/call cache_evaluate now="tomorrow"> → rc 0（isError:true）
  error = {"code":"INVALID_TIME_FORMAT","detail":"expected YYYY-MM-DDTHH:MM:SSZ or an HTTP-date, got 'tomorrow'","field":"now"}
```

新侧（同参 IR，显式带 basis）：

```text
$ byteproof check http-semantics --input <tmp>/hs-ir-fresh.json  --basis <basis> → rc 0（result 与旧 structuredContent 逐字段一致）
$ byteproof check http-semantics --input <tmp>/hs-ir-stale.json  --basis <basis> → rc 1（CACHE_AGE_EXCEEDS_LIFETIME error，detail 逐字节一致）
$ byteproof check http-semantics --input <tmp>/hs-ir-badtime.json --basis <basis> → rc 2（INVALID_TIME_FORMAT，同码同 detail）
```

### 6.2 D1+D18 逐文件处置表（判定层 23 文件 / 旧层 259 函数）

| 旧仓测试文件 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---|---|
| `test_cache_golden.py`（13 函数） | **已迁（判定全）** | 18 golden 逐字节 + 时间解析器 7 案例；§1 + §4 时间单元。 |
| `test_conditional_golden.py`（25） | **已迁（判定全）** | 19 golden（含 error 案例）+ 强/弱比较单元；§1 + §4。 |
| `test_cors_golden.py`（24 函数面） | **已迁（判定全）** | 24 golden + safelisted/notes/分支单元；§1 + §4。 |
| `test_vary_golden.py`（19） | **已迁（判定全）** | 9 golden + 策略表/成员/缺失语义单元；§1 + §4。 |
| `test_golden.py`（16） | **已迁（覆盖双向）** | 五工具 golden 组数断言（18/19/24/10/9）+ 键集冻结（OUTPUT_KEYS）逐案例断言。 |
| `test_coverage_matrix.py` | **已迁（覆盖双向）** | 每 code 被某案例发出（正向）+ 每工具配足案例（反向）。 |
| `test_determinism.py` | **已迁** | 双跑逐字节（每工具一例）+ 逐案例双跑（§1 三断言之一）。 |
| `test_canonical.py` | **已迁** | sort_keys/ensure_ascii/紧凑分隔/禁 NaN + loads 拒 NaN 常量。 |
| `test_protocol.py`（24） | **舍弃（MCP 面）** | JSON-RPC 2.0 帧序、initialize 握手、tools/list 形态 = **MCP 壳**，留旧仓（队列口径）。 |
| `test_server_transport.py` / `test_stdio_end_to_end.py` / `test_stdio_process.py` | **舍弃（MCP 面）** | stdio 传输/子进程生命周期 = MCP 壳，留旧仓。 |
| `test_registry.py` | **已迁（等价物）** | 工具表语义折算为器官注册面：`Pack` 契约字段、重复 slug 拒绝、all_packs 排序、BUILTIN_MODULES 20 项字典序（schema descriptors 是 MCP 面，不迁）。 |
| `test_gates.py` / `test_m1_gates.py`（37） | **已迁（器官内移植面）** | 判定层纯度（禁 io/clock/random/env/网络/print——tokenize 去注释后 AST/token 判源码）+ 目录三向一致；布局/脱敏/变异门由产品仓 `tools/check_*.py` 接管。 |
| `test_gen_codes.py`（15） | **已迁（对账面）** | 生成件对账改为 basis ↔ thresholds ↔ 模块常量三向一致（31 code 逐条）；`gen_codes --check` 本体不迁（旧仓工具面）。 |
| `test_schema_parity.py` | **已迁（键集面）** | 输出 schema ↔ 实际键集的奇偶性折算为逐案例键集断言（OUTPUT_KEYS 五工具冻结）；JSON Schema 文件本体是 MCP 面，不迁。 |
| `test_mirrors.py` | **舍弃（MCP 面）** | `schemas/tools` 双份逐字节镜像 = MCP 交付面，留旧仓。 |
| `test_wpt_ledger.py` | **舍弃（台账面）** | 旧仓 WPT 实测台账（`data/wpt/` CSV → code 计数）属旧仓依据台账；器官不带台账，golden 真值已冻结入仓。 |
| `test_entry_point.py` | **已迁（等价物）** | `python -m http_semantics_mcp` 入口折算为 `byteproof check http-semantics` 宿主入口 rc 断言（list/check/随包 basis 缺省）。 |
| `test_readme_count.py` / `test_readme_gate.py` | **舍弃（仓级文档门）** | README 数字口径门属旧仓文档装订；产品 README 器官行由产品门与台账承担。 |
| `test_ci_workflow.py` | **舍弃（仓级）** | 断言 .github/workflows 文本；产品 CI 由本仓 workflow 承担。 |

**D1+D18 机械剔除**（文件名含排除词）：

| 旧仓测试文件 | 剔除词 | 去向 |
|---|---|---|
| `test_packaging.py` | `packaging` | 打包面（wheel 文件清单）由产品判据 4 + `pyproject` 承担。 |
| `test_release_gate.py` | `release` | 发布门由产品发布流程承担（本批不涉 tag）。 |
| `test_utf8_guard.py` | `guard` | UTF-8 输出护栏属旧仓 Windows 面；产品仓 CI 以 `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` 承担。 |

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/http-semantics.basis.json` | 11460（32 条） |
| `byteproof/data/http-semantics.thresholds.json` | 5936 |

wheel 总条目 **211**（#35 收口 195 + 本器官 16 件：`auditors/http_semantics/` 14 个 .py +
data 2 件）；`byteproof/data/` 进包 40 件。解包后 `byteproof list` = **20 器官**、
仓样例 `check`（无 `--basis`，走解包树的随包 basis 解析）rc **0**（1 条 info：summary）。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **退出码：MCP 恒 0 → 账本 0/1/2**。旧 MCP 工具面把一切结论装进结构化结果（rc 0）；
   账本的退出码承载"有阻断结论"：decisive finding（block/revalidate/miss）→ error → rc 1，
   caller mistake → rc 2（同 D10 接受新契约的先例族）。逐字段对齐见 §6.1 对撞——
   finding 的 code/detail/spec_ref 与旧 structuredContent 逐字节一致，差的只是"承载层"。
2. **caller mistake 是异常不是结果**：旧工具面把 `JudgementError` 渲染为
   `isError:true` 的 result；器官让它沿 `ValueError` 冒泡 → 宿主 CLI「输入不合法」rc 2。
   code/field/detail 三元组逐字节保留（golden error 案例对账）。
3. **`_time` 不是工具**：时间解析器在旧仓是 golden 夹具但不在 tools/list（无对外工具面）；
   器官同样只作判定层内部函数（golden `_time` 7 案例直接对账 `parse_time`）。
4. **MCP 壳留旧仓**（队列口径）：传输/握手/schemas/registry/server/协议门全部不迁；
   工具表语义折算为器官注册面断言。descriptor（name/description/inputSchema）不迁——
   宿主 CLI 的参数面就是 `check <slug> --input`。
5. **`thresholds` 可经 subject 覆盖**：旧仓 severity 表是 CATALOG 常量（进程内不可覆盖）；
   器官允许 subject 带 thresholds 行级覆盖（缺省用与快照逐项相等的模块常量）——这是
   账本化的输入化改造，快照与常量的双向断言防止默认面漂移。
6. **WPT 台账不迁**：旧仓 `data/wpt/` 实测台账是旧仓依据面；器官只消费冻结 golden 真值。
7. **`hs-summary` 为账本化新增**（同 `va-summary` 先例）：工具结果整体进 evidence.result，
   计数信息进 message；不改变任何 finding 的语义。
