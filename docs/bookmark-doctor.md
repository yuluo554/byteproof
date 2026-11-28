# 器官 `bookmark-doctor`

> 来源：迁自 target-map ② 行（旧仓 `10-16-bookmark-doctor`，包 `bookmark_doctor`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**收藏夹体检——失效检测三态（中文站点感知：反爬/风控绝不判死）+ URL 规范化
去重（绝不自动删）+ 长期未访问画像（添加时间代理）**。判定层逐字移植；把
Netscape/Chrome 解析、网络探测、HTML 报告、导回写盘、CLI 留在输入层/报告层。

## 1. 输入（工件）

`mode` 必填；`bookmarks` 必填（除 `mode=check` 外 `dedupe`/`aging` 也要用它）。
`mode` ∈ `audit`（check+dedupe+aging 一次跑完）/ `check` / `dedupe` / `aging`。

| 键 | 形态 | 说明 |
|---|---|---|
| `bookmarks[]` | `{id, title, url, add_date, folder, source}` | UIR 条目；`add_date` = epoch 秒 int \| null（缺失不猜补）；URL 原文永不改写 |
| `observations[]` | `{url, http_status, first_hop_status?, error_class?, final_url?}` | **输入层探测后的观测事实**（器官不发请求）；缺省 = 未探测 |
| `degrade_rules[]` | `{id, disposition, reason, match{host_suffix, http_status}, anchor{observation_id}}` | 降级规则（旧仓 ruleset 节） |
| `observations_ledger` | `{observations: [{id, check_status}]}` | 观测台账（锚点硬门用） |
| `tracked_query_params` | `{exact[], prefixes[]}` | 追踪参数名单（不写第二份） |
| `aging` | `{tiers_days: [365, 730, 1095]}` | 分档阈值（引擎零默认值，缺失/非升序即拒绝） |
| `options.aging_date` | `"YYYY-MM-DD"` | 画像参考日（必填于 aging 模式；器官不读时钟） |

## 2. 判定顺序与等级

三态口径（照搬冻结草案）：**失效（dead）= 唯一通用判死证据是 404/410**；网络不可达
（DNS/超时/TLS/连接失败/跳转异常）与 401/403/405/406/429/451 反爬、521/522/523 CDN
拦截、终态 3xx、语义不明 4xx 一律**待复核（review），绝不判失效**；终态 2xx → alive；
"未探测"按 `probe_incomplete` 待复核，不会被说成"存活"。

| 模块 | 判什么 | 规则与等级 |
|---|---|---|
| 锚点硬门 | 规则启用资格 | `bd-anchor-disabled` info：`anchor.observation_id` 必须解析到 `check_status=verified` 观测，否则拒启并显式列出（`anchor_missing` / `anchor_not_verified`） |
| 分类引擎 | 观测 → 三态 | 规则命中 > 通用映射；多规则冲突按保守序 `review > dead > alive` 取值并留备注（`bd-rule-conflict` warn）；映射结果 → `bd-link-dead` **error** / `bd-link-review` warn / `bd-link-alive` info |
| 去重引擎 | 比较键分组 | `bd-duplicate-group` warn：六步流水线比较键（final_url 优先）、保留策略 https > 无追踪参数 > add_date 最早 > 文件序、`fragment_variant` 标记、**只出清单不删除** |
| 画像分档 | 未访问时长 | `bd-aging-tier` info（取"满足的最高档"）、`bd-aging-unknown` info（add_date 缺失单列）；代理指标必须显式注明 |

规则匹配语义（照搬冻结口径）：`host_suffix`（== 或以 `.`+suffix 结尾，防近似域名）+
`http_status`，**首跳或终态任一命中**——风控链首跳 302、终态 200，只读终态则规则
永不命中。

## 3. 输出

`evidence` 逐段：

| 段 | 字段 |
|---|---|
| 链接判定 | `url` / `verdict`(dead\|review\|alive) / `reason` / `rule_id` / `http_status` / `first_hop_status` / `error_class` |
| 冲突 | `url` / `conflict`(rule_conflict:规则=原因 字典序) / `verdict` |
| 未启用规则 | `id` / `reason` / `observation_id` / `check_status?` |
| 重复组 | `group_id` / `key` / `fragment_variant` / `members[]` / `keep{id,url}` |
| 画像 | `tier` / `min_days`（within 档无此键）/ `count` / `ids[]` / `as_of_date` / `proxy` |

输出示例（`samples/bookmark-doctor.minimal.json`，干净树，rc 0）：

```console
$ byteproof check bookmark-doctor --input samples/bookmark-doctor.minimal.json
byteproof :: bookmark-doctor 1 :: bookmark-doctor.minimal.json
[info] bd-aging-tier — 1年内：2 条（as_of 2026-01-01，以添加时间近似未访问；浏览器不导出真实访问记录） :: aging.1年内 (bd-aging-tier@1)
[info] bd-aging-unknown — 1 条添加时间未知（缺失不猜补，不参与分档） :: aging.unknown (bd-aging-unknown@1)
[info] bd-link-alive — https://github.com/npm/semver：alive（http_2xx） :: observations[0] (bd-link-alive@1)
[info] bd-link-alive — https://github.com/npm/semver/releases：alive（http_2xx） :: observations[1] (bd-link-alive@1)
[info] bd-link-alive — https://www.gs1.org/standards/barcodes：alive（http_2xx） :: observations[2] (bd-link-alive@1)
[info] bd-summary — mode=audit：error=0 warn=0 info=5（error 档 = dead 链接，warn 档 = review/重复组） :: summary (bd-summary@1)
合计 6 条，阻断 0 条（error=0 warn=0 info=6）
```

退出码映射：旧 `import` / `dedupe` / `report` / `check` **完成即 0**（失效只入报告，
退出码 1 专属于 `--selftest` 失败、2 文件级失败）→ 新账本 dead=error → rc **1**
（结构性阻断 rc0→1，同 #20 处理）；旧 2 → 新 2。

## 4. 参数

无灰区开关：保留策略、冲突保守序、映射表全部冻结（旧仓 plan/04）。分档阈值与
追踪参数名单由 subject 提供（旧仓 ruleset 的对应节），引擎零内联零默认值。

## 5. 依据包

`src/byteproof/data/bookmark-doctor.basis.json`：9 条规则（三态链接判定 + 冲突 +
锚点硬门 + 重复组 + 画像两档 + 汇总），每条带 `source` 与 40+ 字口径文本。
`bookmark-doctor.thresholds.json` 同步快照 verdict 表、保守序、通用映射表、
反爬/CDN 状态区间、锚点原因码与保留策略——运行期常量必须与它逐项相等（测试断言）。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓判定层 9 文件 pytest 实跑 **X = 106**（`106 passed in 11.05s`）/ 新仓实跑 **109 passed** | ✅ 过（109 ≥ 106） |
| 2 | README 示例命令 rc 相同 | 旧 `tools/bench.py` rc **0**（离线全链 B1–B6）；旧 `import` rc **0**（27 条）+ `dedupe` rc **0**（4 重复组）→ 新 `check bookmark-doctor` 干净样例 rc **0**；新等价工件 dedupe-only rc **0** / 重复组 **4 = 4** | ✅ 过（0 = 0、组数相等） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 9 文件；函数数**按条计** → 新 **87**（AST）/ 旧 **86**（AST） | ✅ 过（87 ≥ 86） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建；`byteproof/data/bookmark-doctor.basis.json` **4803B / 9 条** + `.thresholds.json` **1232B** 均在包内；解包 `list` = **15 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest tests/test_classify.py \
  tests/test_data_gates.py tests/test_dedupe.py tests/test_encoding.py tests/test_m5.py \
  tests/test_meta.py tests/test_normalize.py tests/test_probe.py tests/test_zero_literals.py \
  -o addopts="" -q -p no:cacheprovider
```

输出原文：`106 passed in 11.05s`。

逐文件 passed：classify 30 / data_gates 7 / dedupe 10 / encoding 4 / m5 15 / meta 2 /
normalize 16 / probe 18 / zero_literals 4 = **106**。
被剔除文件（D1+D18）：`test_bench.py`（bench）、`test_check_cli.py` + `test_cli.py`
（cli）、`test_parse.py`（parse）。新器官 `tests/test_bookmark-doctor.py` 实跑
**109 passed**、AST `test_` 函数 **87**。

### 6.2 D1+D18 逐文件处置表（判定层 9 文件 / 旧层 86 函数）

| 旧仓测试文件 | passed/函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `tests/test_classify.py` | 30/12 | **已迁（判定全）** | 通用映射表、error_class、规则优先、host_suffix 边界、保守冲突、首跳/终态命中；在 `classify`。 |
| `tests/test_data_gates.py` | 7/7 | **部分迁** | 锚点硬门（3 条）迁入 `classify.apply_anchor_gate`；ruleset/fixtures 位一致、无 CR、台账 sha256 属数据正本门，由产品仓 `test_gates.py` 同类门接管。 |
| `tests/test_dedupe.py` | 10/10 | **已迁（判定全）** | 追踪参数合并、fragment_variant、保留策略四序、final_url 优先、不改输入、组 id 稳定；在 `dedupe`。 |
| `tests/test_encoding.py` | 4/4 | **舍弃（输入层）** | bookmarks.html 编码探测/UTF-8 守卫属文件读取面（D18 `input` 域），器官收解析后条目。 |
| `tests/test_m5.py` | 15/15 | **部分迁** | 画像三态与阈值校验（3 条）迁入 `aging`；报告零外链/转义/确定性、导回 roundtrip、CLI 开关与端到端（12 条）属报告面/编排面，不迁（SKELETON-SPEC §2）。 |
| `tests/test_meta.py` | 2/2 | **舍弃（产品级）** | 版本号/元数据一致性属产品仓门（`tests/test_pep561_marker.py` 等）。 |
| `tests/test_normalize.py` | 16/14 | **已迁（判定全）** | 六步流水线逐步双向样例、追踪参数 exact+prefix、短链映射不猜、原文不改写；在 `normalize`。 |
| `tests/test_probe.py` | 18/18 | **舍弃（网络面）** | 探测是网络 I/O（SKELETON-SPEC §2：器官不联网）；器官消费观测事实，探测语义由输入层承担。 |
| `tests/test_zero_literals.py` | 4/4 | **舍弃（产品级）** | 零字面量门（源码扫描）属产品仓静态门（`tests/test_gates.py`）。 |

**D1+D18 机械剔除**：`tests/test_bench.py`（`bench`）、`tests/test_check_cli.py` 与
`tests/test_cli.py`（`cli`）、`tests/test_parse.py`（`parse`）不进分母。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/bookmark-doctor.basis.json` | 4803 |
| `byteproof/data/bookmark-doctor.thresholds.json` | 1232 |

wheel 总条目 **150**；解包后 `byteproof list` = **15 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **网络面不迁**：探测（`probe.py` 的 HEAD→GET 降级、重试、跳转跟随）属网络 I/O，
   器官消费**观测事实**（`observations[]`），不发请求、不读网络。
2. **退出码语义**：旧 `check` 完成即 0（失效只入报告；rc1 专属 `--selftest`）→ 新账本
   `bd-link-dead` = error → rc1（结构性阻断 rc0→1，同 #20 `fund-quarter-report` 处理）；
   dead 是"收藏夹清理建议的直接依据"，在本产品契约里就是阻断性结论。
3. **锚点硬门的数据面**：观测台账/ruleset 正本文件读取不迁；subject 直接给
   `degrade_rules` + `observations_ledger`，硬门判定（enabled/disabled 清单）全迁。
4. **画像参考日**：旧 CLI 用 `--probe-date`；器官用 `options.aging_date`（必填于
   aging 模式）——同样不读系统时钟，缺了就是输入不合法（rc2），不猜"今天"。
5. **报告/导回/CLI 不迁**：report.html 排版、Netscape 导回、`run` 编排、`--apply-dedupe`
   /`--exclude-dead` 开关属输出面与编排面（SKELETON-SPEC §2），器官只出账本行。
6. **`va`/`bd` 规则面**：旧仓的 ruleset.json（站点降级规则）是**动态数据**，随 subject
   走；器官 basis 只登记**判定规则**（三态口径、硬门、保留策略），两者不混。
