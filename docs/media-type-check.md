# 器官 `media-type-check`

> 来源：迁自 target-map ② 行。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列。

一句话：**把一封 MIME 消息的解析结构当工件审，逐部件判五个域的条款一致性，落一张带 RFC 出处的缺陷账本。**

规则 ID **原样保留**旧仓的 `MC-<B|H|T|A|C><两位>`，因为它们同时是旧仓
`data/rfc-ledger.json` 的索引键 —— 改名就断掉了"这条账本能反查到 RFC 条款"这条链。

## 1. 输入（工件）

工件是**已解析**的 MIME 结构（raw 字节扫描层 `scan.py` 是工具面，器官不读文件）：

```json
{
  "parts": [
    {"path": "0", "content_type": "multipart/mixed", "boundary": "b1",
     "headers": [{"name": "Content-Type", "value": "multipart/mixed; boundary=b1"}],
     "body": ""},
    {"path": "0.1", "content_type": "text/plain",
     "headers": [{"name": "Content-Type", "value": "text/plain"},
                 {"name": "Content-Transfer-Encoding", "value": "7bit"}],
     "body": "hello"}
  ],
  "params": {}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `parts[].path` | 是 | 树位置：`0` / `0.1` / `0.1.2`，或容器层 `msg#3/0.1`。**路径必须唯一**（重复 -> 退出码 2） |
| `parts[].content_type` | 是 | 主类型（可带参数；`name=` 参与 `MC-A02`） |
| `parts[].boundary` | 否 | multipart 的 boundary（`null` 表示没声明） |
| `parts[].headers[]` | 否 | `{name, value}` 数组；**同名头全部保留**（重复 Content-Type 本身是事实） |
| `parts[].body` | 是 | 正文。字符串按 UTF-8 取字节；**无正文必须显式写 `""`**，缺键是信封错误 |
| `params` | 否 | 阈值（见 §4），未知键 -> 退出码 2 |

嵌套深度由 `path` 的末段下标数决定：`0` = 1 层，`0.1.2` = 3 层，`msg#3/0.1` = 2 层。

## 2. 判定：等级 = 严重度

byteproof 的账本只有三档，旧仓有 `class` 三值 + `severity` 四档。翻译只发生在一个地方：

| 旧仓 severity | 账本 verdict | 含义 |
|---|---|---|
| `blocker` | `error` | 结构无法建立（阻断） |
| `major` | `error` | 违反明确条款且影响解码/呈现（阻断） |
| `minor` | `warn` | 违反行宽/编码字长度等硬性约束（记录） |
| `note` | `info` | 条款未录或 RFC 明确要求忽略（只留痕） |

旧仓的 `class`（hard/diff/gray，描述**证据强度**）不搬：账本要的是"阻不阻断"，
而证据强度已经在 `basis_ref` 的 RFC 出处里体现。这条删减见 §7.1。

### 2.1 迁入的 20 条规则

| 规则 | 域 | severity | 条款 | 判据 |
|---|---|---|---|---|
| `MC-B01` | 容器 | blocker | RFC 2046 §5.1.1 | multipart/* 缺 boundary，树无法建立 |
| `MC-B02` | 容器 | minor | RFC 2046 §5.1.1 | boundary 长度 > `max_boundary_chars`（70） |
| `MC-B09` | 容器 | note | none-by-design | 嵌套深度 > `max_depth`（策略项，RFC 未规定上限） |
| `MC-H01` | 头 | minor | RFC 2047 §2 | encoded-word 长度 > `max_encoded_word_chars`（75） |
| `MC-H02` | 头 | minor | RFC 2047 §2 | 含 encoded-word 的头行 > `max_encoded_header_line`（76） |
| `MC-H03` | 头 | minor | RFC 2047 §2 | encoded-word 内部出现空白 |
| `MC-H07` | 头 | major | RFC 5322 §2.1.1 | 头行 > `max_header_line_octets`（998） |
| `MC-H08` | 头 | note | RFC 2047 §1 | 头值含未编码的非 ASCII 字节 |
| `MC-T02` | 传输 | note | none-by-design | base64 填充非法（只允许末尾、至多 2 个） |
| `MC-T03` | 传输 | note | none-by-design | base64 字符数不是 4 的倍数 |
| `MC-T04` | 传输 | note | RFC 2045 §6.8 | base64 出现字母表外字符（RFC 要求忽略） |
| `MC-T05` | 传输 | minor | RFC 2045 §6.7 | QP 行 > `max_qp_line_octets`（76） |
| `MC-T06` | 传输 | minor | RFC 2045 §6.7 | QP 末行以 `=` 结尾但已无下一行 |
| `MC-T07` | 传输 | major | RFC 2045 §6.7 | QP 非法转义（`=` 后不是两位十六进制） |
| `MC-T08` | 传输 | note | none-by-design | 未知 CTE 取值 |
| `MC-T09` | 传输 | note | none-by-design | 7bit/8bit 正文行 > `max_body_line_octets`（998） |
| `MC-T10` | 传输 | note | none-by-design | 未声明 CTE 但正文含 8bit 字节 |
| `MC-A02` | 归属 | note | none-by-design | `name` 与 `filename` 不一致 |
| `MC-A03` | 归属 | note | none-by-design | 声明了 disposition 却无 filename/name |
| `MC-A07` | 归属 | note | none-by-design | `inline` 却没有 Content-ID |

三条顺序纪律（照抄旧仓，测试逐条钉住）：

1. **`MC-H07` 先于 encoded-word 检查**：头行一旦超过 998，再按 encoded-word 拆段报错，
   只会把一条结论说三遍。
2. **`MC-T04` 命中后不再判填充与长度**：RFC 2045 §6.8 要求解码器忽略字母表外字符，
   那既不是违规、也轮不到用它的字节数去推"填充错没错"。
3. **QP 含非法转义的行不记行宽**：一行同时"宽度超限"和"转义非法"时只报后者。

## 3. 输出

```console
$ byteproof check media-type-check --input <工件.json>
byteproof :: media-type-check 1 :: <工件.json>
[error] MC-B01 — multipart/related 缺 boundary 参数：树无法建立 :: 0.3#1 (MC-B01@1)
[info]  MC-A07 — disposition 是 inline 却没有 Content-ID：正文无法用 cid: 引用它 :: 0.3#1 (MC-A07@1)
[info]  MC-T04 — base64 正文出现字母表外字符 1 种（RFC 2045 §6.8 要求忽略） :: 0.2#1 (MC-T04@1)
合计 3 条，阻断 1 条（error=1 warn=0 info=2）
```

`path` = `<部件路径>#<该部件内这条规则的第几次命中>`。同一条规则在一个部件上命中多次
（例如两行都超过 998 octets）时**必须**追加序号，否则两条结论抢同一个账本 id。

`--json` 的单条账本：

```json
{
  "id": "MC-B01@0.3#1",
  "rule_id": "MC-B01",
  "verdict": "error",
  "message": "multipart/related 缺 boundary 参数：树无法建立",
  "basis_ref": {"rule_id": "MC-B01", "rule_version": "1",
                "source": "RFC 2046 §5.1.1", "quote": "…"},
  "path": "0.3#1",
  "evidence": {
    "content_type": "multipart/related", "boundary": null,
    "rule_id": "MC-B01", "severity": "blocker", "part_path": "0.3",
    "params": {"max_depth": 32, "max_body_line_octets": 998, "…": 0}
  }
}
```

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---:|---|
| `max_depth` | 32 | 嵌套深度上限（旧仓 `--max-depth` 默认；RFC 未规定） |
| `max_boundary_chars` | 70 | RFC 2046：boundary 不含前导 `--` 至多 70 |
| `max_header_line_octets` | 998 | RFC 5322 行宽上限（不含 CRLF） |
| `max_encoded_word_chars` | 75 | RFC 2047 encoded-word 上限 |
| `max_encoded_header_line` | 76 | 含 encoded-word 的头行上限 |
| `max_qp_line_octets` | 76 | RFC 2045 §6.7 QP 行宽 |
| `max_body_line_octets` | 998 | 7bit/8bit 正文行宽 |

全部参数都会写进每条账本的 `evidence.params` —— 一条结论要说清"当时用的是哪组阈值"。

## 5. 依据包

随包副本 `src/byteproof/data/media-type-check.basis.json`（20 条规则，包版本 `1`）；
阈值/严重度/等级台账在 `src/byteproof/data/media-type-check.thresholds.json`。
缺规则 -> `RuleMissing` -> 退出码 3。

**"没有条款"必须显式写 `none-by-design`**（旧仓 D8）：`rfc` 不得为空，
"RFC 没规定这件事"本身就是这条规则的证据。

## 6. 已知边界

1. **不做 raw 字节扫描**：本器官从"已解析的部件"开始，所以"delimiter 不在行首"、
   "缺 final boundary"、"preamble/epilogue"、"内层复用外层 boundary"（`MC-B06`）
   这些**需要看到原始字节与两棵候选树**的规则没有迁（处置见 §7.1）。
2. **不借标准库的 email 解析器**：器官契约门在 AST 层禁 `email` / `base64` / `quopri`
   （判什么必须是我们写的，不是库的实现）。
3. **同名头全部保留**：重复 `Content-Type` 是事实，不做去重、不做覆盖。

## 7. §7.3 四项无损判据 · 实测

判定层口径：`ORGAN-PLAYBOOK` §3.0。旧仓 17 个判定层文件（静态 232 函数）。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓判定层实跑 X = 562 / 新仓实跑 N = 610 / 结论：过（差 +48）** | ✅ |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文 `mimeconform audit data/golden/b-clean-nested/msg.eml --format json` rc **0**；新入口 `check media-type-check --input samples/media-type-check.minimal.json` rc **0**；major 件旧 **3** / 新 **1**（见 §7.2） | ✅ 过（clean 路径；严重度路径为口径差） |
| 3 | 测试文件数 / 测试函数数 | 新 1 文件 / **119** `def test_`；旧判定层 17 文件 / 232 | ❌ 不过（两项都低于旧层；单文件约定，实跑数 610 ≥ X 562 由判据 1 计） |
| 4 | `pip wheel` 后 `data/` 进包 | `media-type-check.basis.json` + `.thresholds.json` 在 wheel 内 | ✅ |

### 7.1 脚手架测试处置表（旧仓被剔除的每个测试文件）

| 旧仓测试文件 | 函数数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_cli_contract.py` | 32 | **舍弃** | 测 argparse 面（`audit`/`scan`/`selftest`/`--fail-on`/`--max-depth`）。SKELETON-SPEC §2：器官不得自带 CLI；本仓只有 `list`/`check`，由 `TestCli` 覆盖退出码 0/1/2/3。 |
| `test_engine_guards.py` | 11 | **舍弃** | 测 `EngineNotReady` 防腐层（未实现分支必须显式报错）。本器官没有"未实现分支"——20 条规则全部落地，不存在的检测器不会静默通过，因为规则不在依据包里就是 `RuleMissing`。 |
| `test_generator_check.py` | 14 | **舍弃** | 测 `tools/` 的目录生成器校验。工具面，不是判定。 |
| `test_packaging.py` | 7 | **舍弃** | 测 wheel 内容与安装面。本仓有 `pyproject.toml` 的 `package-data` 断言 + 判据 4 的实构建。 |
| `test_version_and_packaging.py` | 7 | **舍弃** | 测版本号一致性与打包元数据。发布门职责，本仓由 `tools/check_release.py` 一类属于 CI，不进器官。 |

判定层内部**只部分迁**的文件（差值来源）：

| 旧仓测试文件 | 函数数 | 处置 | 理由 |
|---|---:|---|---|
| `test_golden_engine_headers.py` | 30 | **部分迁** | 头域规则（H01/02/03/07/08）已迁；golden 夹具是"整封信 -> 缺陷集指纹"，需要 raw 字节层。 |
| `test_golden_engine_transfer.py` | 23 | **部分迁** | 传输规则（T02–T10）已迁；golden 指纹未迁（同上）。 |
| `test_golden_engine_container.py` | 18 | 部分迁 | B01/B02/B09 已迁；B03–B08（delimiter 位置、final boundary、preamble/epilogue、B06 双候选树）需要 raw 扫描层，**未迁**。 |
| `test_golden_engine.py` / `…_attribution.py` | 19 / 19 | 部分迁 | 归属 A02/A03/A07 已迁；A01/A04/A05/A06/A08 需要整棵树与 cid: 引用扫描，**未迁**。 |
| `test_catalog_gate.py` | 24 | 舍弃 | 测规则目录门禁（`ledger_key` 必须存在于 RFC 台账、hard 必须有原句）。本器官的对应门是 `TestShippedTables` + `test_every_rule_cites_a_clause_or_none_by_design`。 |
| `test_catalog_doc.py` / `test_catalog_consistency.py` | 7 / 6 | 舍弃 | 规则目录与文档的交叉一致性；本器官把规则表与文档表格分开维护，用 `TestShippedTables` 对账。 |
| `test_determinism.py` | 11 | 部分迁 | 双跑逐字节一致已迁（`TestCli` + `TestCorpusMatrix`）；`fingerprint`/`tree_digest` 两套摘要未迁（账本不哈希，见 organ 1 的同一条理由）。 |
| `test_exit_codes.py` | 11 | 舍弃 | 旧仓 `0/1/2/3` 的语义（`EXIT_MINOR=2`、`EXIT_MAJOR=3`）与本产品不同：byteproof 用 `0/1/2/3` 表示"无阻断/有阻断/输入不合法/契约违约"。映射见 §7.2。 |
| `test_ledger_invariants.py` | 22 | 部分迁 | 排序/唯一性/计数一致性已迁；`by_class`/`by_severity`/`none_by_design` 三个台账字段不迁（账本没有报告层）。 |
| `test_ledger_mirror.py` | 6 | 舍弃 | 台账镜像文件（`--emit-ledger`）—— 报告产物。 |
| `test_fixture_hygiene.py` | 6 | 舍弃 | 夹具目录卫生（无本机路径、无大文件）。本器官夹具全部内联在测试里。 |
| `test_ci_workflow.py` | 9 | 舍弃 | 测 `.github/workflows` 的 YAML。CI 面。 |
| `test_gates.py` | 12 | 舍弃 | 旧仓两道门（生成器冻结、目录门）。本仓有 `tools/check_sprint_layout.py` / `check_desensitized.py`。 |
| `test_readme_gate.py` | 6 | 舍弃 | 旧仓 README 数字门。 |
| `test_reported_counts.py` | 3 | 舍弃 | 报告中的计数断言 —— 报告层。 |

### 7.2 判据 2 的口径

| 旧仓命令 | 旧 rc | 新仓对应命令 | 新 rc |
|---|---:|---|---:|
| `mimeconform scan <文件>` | 0 / 3（有 major 时 3） | `byteproof check media-type-check --input <clean 工件>` | 0 |
| 同上（有 major/blocker） | 3 | `byteproof check media-type-check --input <有 blocker 的工件>` | 1 |

旧仓把"有 major"映射到 **3**，本产品把"有 `error`"映射到 **1**：
`SKELETON-SPEC §5` 的 3 专指**契约违约**（无依据下结论 / 规则缺失 / 包版本缺失），
而"工件有缺陷"是 1。这条口径差与另两个器官同源，已写进 `docs/byteproof.md` §5。