# 器官 `mojibake-forensics`

> 来源：迁自 target-map ② 行（旧仓 `10-20-mojibake-forensics`，包 `mojibake_forensics`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把「已经解坏的 str 是被哪一步 encode/decode 转坏的、还能不能回去」当成字节工件来审**，
落一张可复算的缺陷账本。旧仓五个子命令收敛成五个 `subject.mode`：
`attr`（有界候选）/ `explain`（每步字节证明）/ `recover`（判死或确定性还原）/
`file`（原始字节诊断）/ `scan`（逐行 CI 门禁）。

器官只回答判定，**不读文件、不遍历目录、不写 `--out`、不读环境变量与时钟、不联网**。

## 1. 输入（工件）

```json
{"mode": "attr", "text": "é›…é›…"}
```

`mode` 是唯一必填键；其余字段按模式校验，缺字段/类型错 -> 退出码 2。

| 模式 | 必填 | 可选 | 含义 |
|---|---|---|---|
| `attr` | `text` | `top`（默认 5）、`source_enc[]`、`target_enc[]` | 有界候选集；编码子集只能在冻结集合内收窄 |
| `explain` | `text` | `pick`（默认 1）、`all`、`vs`、`source_enc[]`、`target_enc[]` | 对已排序候选逐步重放；`all=true` 与 `vs` 互斥 |
| `recover` | `text`、`pick` | — | 先判不可逆类，再按 `pick` 重放；`pick` 必填（不猜最优） |
| `file` | `bytes_hex` | `preset`（`csv-excel-win` / `zip-names` / `utf16`） | 已读进内存的原始字节；十六进制串可带空格 |
| `scan` | `files[]`、`baseline{}`、`existing_paths[]` | — | 文件文本与基线由输入层提供；存在性也由输入层提供 |

| 键 | 形态 | 说明 |
|---|---|---|
| `text` | 已解码 `str` | 非空；原始字节属于 `file` 模式 |
| `top` | `int >= 1` | 只影响展示；`total_candidates` 始终完整 |
| `source_enc` / `target_enc` | `str[]` | 子集，不得新增冻结集合之外的编码名 |
| `pick` / `vs` | `int >= 1` | 越界 -> 退出码 2 |
| `bytes_hex` | `"E9 9B 85"` / `"E99B85"` | 奇数长度或非十六进制 -> 退出码 2 |
| `files[]` | `{path: str, text: str}` | `text` 是 UTF-8 解码后的行文本（非 UTF-8 文件由输入层跳过） |
| `baseline` | `{files: [{path, allowed_hits?}]}` | 只按路径登记，不改变命中判据 |
| `existing_paths` | `str[]` | 基线路径是否仍在磁盘上；器官不读盘，所以由输入层给 |

**为什么 `scan` 要 `existing_paths`**：旧仓 `stale` 桶靠 `os.path.exists`；器官零文件 IO，
存在性必须由输入层提供，否则只能静默丢掉 `stale`。

## 2. 判定顺序与等级

| 模式 | 规则 | 等级 | 判据 |
|---|---|---|---|
| attr | `mf-attr-candidate` | `info` | 每条展示候选：结果 + 路径 + 链深 + 三层打分 + 相对份额区间 |
| attr | `mf-attr-no-candidate` | `error` | 冻结集合与链深上限内零候选（不返回空列表冒充成功） |
| attr | `mf-attr-confidence-degenerate` | `warn` | 全部候选总分 <= 0，份额区间不可定义（记 `null`） |
| attr | `mf-attr-single-candidate` | `info` | 只有一条无损候选，区间 1.0 + note |
| attr | `mf-attr-truncated` | `info` | 展示被 `top` 截断，完整候选数另记 |
| explain | `mf-explain-verify` | `info` | 逐步从计算状态重放 encode/decode，与链记录逐项一致 |
| explain | `mf-explain-verify-failed` | `error` | 某步记录与复算不一致；停在 `failed_step`（1 起） |
| explain | `mf-explain-divergence` | `info` | 与对照候选的第一处差异（op/codec → 字节 → 字符 → 链长） |
| recover | `mf-recover-lost` | `error` | 不可逆判死：`replacement_char` / `kun_jin_kao` / `encode_truncated` |
| recover | `mf-recover-not-mojibake` | `error` | `msvc_fill`（烫烫烫/屯屯屯）——不是乱码，不尝试修复 |
| recover | `mf-recover-no-candidate` | `error` | 候选为空，记 `LOST(reason=no_candidate)` |
| recover | `mf-recover-recovered` | `info` | 按 `pick` 重放且 `verify=true` 才报已还原 |
| file | `mf-file-bom` | `info` | BOM 检查结论（命中类型/字节/偏移，或「无」） |
| file | `mf-file-bom-conflict` | `warn` | 声明了 BOM 但正文按该编码解不开；同时列 UTF-8/GB18030 双解 |
| file | `mf-file-utf16-misalignment` | `warn` | 奇数字节 + 错位一字节证据，不自动纠正 |
| file | `mf-file-zip-name` | `info` | 中央目录成员名：flag、原始字节、按声明编码的解释 |
| file | `mf-file-zip-name-ambiguous` | `warn` | 未置 UTF-8 标志且两解并存，工具不选择 |
| file | `mf-file-csv-candidate` | `info` | cp1252/gbk/shift_jis 候选 + 首行分隔符嗅探 |
| scan | `mf-scan-new` | `error` | 命中行所在文件不在基线里（新增命中） |
| scan | `mf-scan-baselined` | `info` | 命中行所在文件已在基线里 |
| scan | `mf-scan-stale` | `warn` | 基线路径已不在 `existing_paths` 里（旧仓不影响退出码） |
| scan | `mf-scan-clean` | `info` | 全部文件零命中且无过期项，写明 `files_scanned` |

**不可逆类固定顺序**（旧仓 `plan/03` §5.2）：`U+FFFD` → `锟斤拷` → `烫烫烫/屯屯屯` →
`?` 截断。先判死再重放；`silent_drop` 需要出处证据，本入口不伪造。

**链枚举口径**：链从 `encode` 开始、以 `decode` 结束；链深 = `decode` 步数（上限 3）；
恒等轮转（结果等于输入）不算候选；每条链必须通过反向逐字节复算。

**scan K9 判据**（三者同时成立）：输入行可读性 < 0.5；存在无损候选可读性 >= 0.8；
可读性增益 >= 0.3。

## 3. 输出

```console
$ byteproof check mojibake-forensics --input samples/mojibake-forensics.minimal.json
byteproof :: mojibake-forensics 1 :: mojibake-forensics.minimal.json
[info] mf-attr-candidate — 有界候选：'闆呴泤'（路径 encode:cp1252>decode:gb18030，链深 1） :: candidates[1] (mf-attr-candidate@1)
[info] mf-attr-candidate — 有界候选：'雅雅'（路径 encode:cp1252>decode:utf-8，链深 1） :: candidates[2] (mf-attr-candidate@1)
[info] mf-attr-candidate — 有界候选：'茅聸聟茅聸聟'（路径 encode:cp1252>decode:latin-1>encode:utf-8>decode:gb18030，链深 2） :: candidates[3] (mf-attr-candidate@1)
[info] mf-attr-candidate — 有界候选：'땠땠'（路径 encode:cp1252>decode:utf-8>encode:big5>decode:euc-kr，链深 2） :: candidates[4] (mf-attr-candidate@1)
[info] mf-attr-candidate — 有界候选：'懂懂'（路径 encode:cp1252>decode:utf-8>encode:big5>decode:gb18030，链深 2） :: candidates[5] (mf-attr-candidate@1)
[info] mf-attr-truncated — 只展示前 5 条；完整候选数 351，不受 --top 影响 :: candidates (mf-attr-truncated@1)
合计 6 条，阻断 0 条（error=0 warn=0 info=6）
```

样例实跑：**351 个不同结果 / 1029 条无损链**，展示前 5 条（退出码 **0**）。
其中 `雅雅` = `é›…é›…` 的经典修复（`encode:cp1252>decode:utf-8`）；排名第 1 的
`闆呴泤`（`encode:cp1252>decode:gb18030`）与 `雅雅` 同分，按冻结排序键
`(-score_total, depth, path_string)` 的 `path_string` 决胜——**工具不宣称哪个是真相**。

`--json` 的单条账本：

```json
{
  "id": "mf-attr-candidate@candidates[1]",
  "rule_id": "mf-attr-candidate",
  "verdict": "info",
  "message": "有界候选：'闆呴泤'（路径 encode:cp1252>decode:gb18030，链深 1）",
  "basis_ref": {
    "rule_id": "mf-attr-candidate",
    "rule_version": "1",
    "source": "迁自 target-map ② 行 · 旧仓 mojibake_forensics/attr.py + score.py（attr 子命令）",
    "quote": "候选 = 从输入文本出发、经「encode -> decode」链（链深上限 3）反向逐字节复算无损、且结果不同于输入的全部路径……"
  },
  "path": "candidates[1]",
  "evidence": {
    "rank": 1,
    "result": "闆呴泤",
    "path": [
      {"op": "encode", "codec": "cp1252"},
      {"op": "decode", "codec": "gb18030"}
    ],
    "path_string": "encode:cp1252>decode:gb18030",
    "depth": 1,
    "score": {"readability": 1.0, "depth": 0.5, "language": 0.0, "total": 1.25},
    "confidence": {"lower": 0.00040916856999045437, "upper": 0.140037943079233},
    "note": null
  }
}
```

其余模式的输出形态（同一账本模型）：

- `recover`：一条记录。`recovered` / `loss` / `verify` / `notes` 都在 `evidence` 里；
  `LOST` 的 `loss` 含 `step` / `offset` / `replaced_with` / `cause`（锟斤拷另带 `repeat` 与 `bytes_hex`）。
- `explain`：每条 `proofs[r]` 一条 `mf-explain-verify`（`steps[]` 逐步复算），外加一条
  `divergence`（含 `at_step` / `kind` / 偏移 / `statement`）。
- `file`：`bom`、`bom.conflict`、`utf16`、`zip.names[i]`、`zip.names[i].alternative`、`csv` 逐节成条。
- `scan`：每条命中 `path:line` 一条；`stale` 用 `baseline.stale[<path>]`；干净时一条 `scan`。

## 4. 参数（`params`）

本器官**没有** `params` 段：所有口径都是冻结常量（见 §5），`top` / `pick` / `vs` /
`preset` 是输入字段而不是可调策略。旧仓的 `--freq` 语言先验从未实现（`freq_not_implemented`），
不迁。

## 5. 依据包

`src/byteproof/data/mojibake-forensics.basis.json`（**22 条规则**，版本 `1`）。
每条规则带 `rule_id` / `title` / `source` / `text`；`source` 写明旧仓模块与迁移性质
（搬用 / 新增 / 保留证据面）。

`mojibake-forensics.thresholds.json` 是**台账**：编码集合、链深、默认 top、三层权重、
可读性分级、scan 三道阈值、22 条规则的等级。运行期常量在 `spec.py`，测试逐项断言两边相等。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓 11 个判定层文件实跑 **X = 148 passed** / 新仓实跑 **170 passed** | ✅ 过（170 ≥ 148） |
| 2 | README 示例命令 rc 相同 | ① `forensics attr --text "é›…é›…"` rc **0**（351 候选/1029 链）→ 新入口等价工件 rc **0**（6 条记录）；② `forensics recover --text "锟斤拷" --pick 1` rc **1**（status=lost / kun_jin_kao）→ 新入口等价工件 rc **1**（`mf-recover-lost`） | ✅ 过（0 = 0、1 = 1） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 11 文件；函数数**按条计** → 新 **151**（AST）/ 旧 **136** | ✅ 过（170 ≥ 148；151 ≥ 136） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（**97 条目**）；`byteproof/data/mojibake-forensics.basis.json` **8969B / 22 条** + `.thresholds.json` **1594B** 均在包内；解包 `list` = **9 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest \
  tests/test_architecture.py tests/test_attr.py tests/test_codecs_table.py \
  tests/test_explain.py tests/test_file.py tests/test_fixtures.py \
  tests/test_layout_gate.py tests/test_paths.py tests/test_recover.py \
  tests/test_scan.py tests/test_score.py -o addopts="" -q -p no:cacheprovider
```

输出：`148 passed in 3.68s`。来源仓 `git status --porcelain` = **0 行**，HEAD `c204604` 与队列一致。

逐文件 passed：architecture 7 / attr 22 / codecs_table 6 / explain 26 / file 11 /
fixtures 12 / layout_gate 7 / paths 11 / recover 26 / scan 15 / score 5 = **148**；
旧层 AST 同名 `test_` 函数 **136**（参数化只计一次）。新器官 `tests/test_mojibake-forensics.py`
实跑 **170 passed**、AST `test_` 函数 **151**。

### 6.2 D1 + D18 逐文件处置表（判定层 11 文件 / 136 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_architecture.py` | 7 | **部分迁** | 「无网络 import / 无 `errors=replace|ignore`」两条不变量由本仓测试的静态 AST 门继承；源码目录清单门不迁。 |
| `test_attr.py` | 19 | **已迁（判定全）** | 候选恒为列表、区间上下界、单候选/无候选/截断三 note、子集收窄、空输入、确定性；在 `chain` + `audit._attr`。 |
| `test_codecs_table.py` | 6 | **已迁（判定全）** | 冻结编码集合、链深 3、criteria 块稳定；在 `spec` + 测试。 |
| `test_explain.py` | 26 | **已迁（判定全）** | 逐步重放、篡改步定位、三类分叉、pick/all/vs 边界、no_candidate；在 `chain` + `audit._explain`。 |
| `test_file.py` | 11 | **已迁（判定全）** | BOM 冲突、UTF-16 错位、ZIP 名两解、CSV 候选、preset 抑制；在 `probe` + `audit._file`（字节由 subject 供）。 |
| `test_fixtures.py` | 12 | **部分迁** | 真值/期望的判定语义（五类不可逆、scan 阈值、合成语料命中）已迁；fixture 生成器与 `expect.json` 文件布局不迁（数据面）。 |
| `test_layout_gate.py` | 7 | **舍弃** | 旧仓方法论布局门/发布留档门 = 产品级文档门。 |
| `test_paths.py` | 11 | **已迁（判定全）** | hexdump、链深、canonical path、无损/变异链、枚举确定性、结果折叠；在 `chain`。 |
| `test_recover.py` | 26 | **已迁（判定全）** | 五类判死、无自造字符、pick 缺失/越界、无候选、verify 失败降级；在 `audit._recover`。 |
| `test_scan.py` | 15 | **已迁（判定全）** | 干净/污染/基线/stale 四桶、K9 阈值、路径锚；在 `audit._scan`（目录遍历由输入层供）。 |
| `test_score.py` | 5 | **已迁（判定全）** | 可读性分级、深度分、冻结排序键；在 `chain`。 |

**D1+D18 机械剔除的 3 个文件**：`test_bench.py`（bench）、`test_cli_skeleton.py`（cli）、
`test_report.py`（report）。分别测 57 例基准、CLI 参数面、JSON 报告排版。
辅助文件 `conftest.py` 与 `independent_replay.py` 不是 `test_*.py`，不计入分母；
后者的「用报告自身字段独立复算」语义已由 `test_replay_chain_*` 覆盖。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/mojibake-forensics.basis.json` | 8969 |
| `byteproof/data/mojibake-forensics.thresholds.json` | 1594 |

wheel 总条目 **97**；解包后 `byteproof list` = **9 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态**：旧仓 `attr/explain/recover` 接受 `--text` / `--file <path>`；本器官只接受
   `subject.text`。UTF-8 文件读取与「非 UTF-8 请用 `file`」的拒绝逻辑属于输入层，不迁。
   `scan` 的目录遍历、UTF-8 解码与非 UTF-8 跳过同理；`stale` 的存在性由
   `existing_paths` 提供——这是一条**新增的输入契约**，换来器官零文件 IO。
2. **`--out` 不迁**：旧仓 `recover --out` 写文件且拒绝覆盖输入；本器官只产出账本，
   写盘由宿主/调用方决定（器官不得做文件 IO）。
3. **报告信封不迁**：旧仓每份 JSON 带 `schema` / `tool_version` / `python_version` /
   `criteria`；本器官的确定性来自账本模型，账本里**没有**环境字段（SKELETON-SPEC §6：
   无时间戳、无绝对路径、无随机；`python_version` 属环境事实）。
   `criteria` 的冻结集合改由 `evidence` 的 `path` / `params` 与 §5 台账承载。
4. **退出码映射**：旧仓 `LOST` / `NOT_MOJIBAKE` / `no_candidate` / `scan new` 都是 rc 1，
   本器官映射为 `error`（阻断）→ rc 1，逐例实测对齐。
   `file` 的 `bom_conflict` / `utf16` / `zip` 两解在旧仓是 rc 0 的**证据级**结论，
   本器官映射为 `warn`（不阻断）→ rc 0，保持 rc 不变。
   `stale` 旧仓明确不影响退出码 → `warn` → rc 0。
5. **旧仓 rc 3（codec 不可用 / Python 版本过低）没有等价物**：本器官不探测运行环境；
   冻结集合在受支持解释器上均为标准库 codec。若真的缺失，会在枚举时抛 `LookupError`
   （不是账本结论），这属于环境故障而非输入缺陷。
6. **`--freq` 不迁**：旧仓该旗标直接 `freq_not_implemented`（rc 2），从未实现；
   本器官没有语言先验，`score.language` 恒为 0.0。
7. **旧 README 的示例 JSON 是示意值**：README「`attr` 输出字段」一节写 `323 candidates /
   888 chains`，是单字符 `é›…` 的一次实跑；README 命令示例用的是 `é›…é›…`，当前代码实跑为
   **351 / 1029**。本器官以**当前代码**为准（与来源仓实跑逐项一致），示例数字差异属来源文档
   漂移，不改变判定。
8. **`silent_drop` 保留为不可判定**：需要出处证据，旧仓 CLI 面不伪造；本器官同样不产出该结论
   （测试断言可见文本不会得出它）。
9. **ZIP 成员内容不解压**：只读中央目录名与 `zipfile` 元数据视图；旧仓也不解压成员内容，
   本器官沿用并在测试里断言成员正文不出现在证据里。