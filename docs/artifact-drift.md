# 器官 `artifact-drift`

> 来源：迁自 target-map ② 行（旧包 `bdiff`）。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把两份已产出的构建产物当工件审，落一张「这是哪一类差异、有几处、归一化后
还剩多少真差异、最少改哪几项」的缺陷账本。** 搬过来的是判定（结构对齐 + T1–T12 归因 +
残留字节 + 最小原因集 + budget 门禁），不是归档读取器，也不是报告生成器。

## 1. 输入（工件）

```json
{
  "left": {
    "kind": "tar",
    "entries": [
      {"path": "synthpkg-0.1.0/a.txt", "kind": "file", "index": 0,
       "data": "payload", "facts": {"tar.mtime": "1700000000", "tar.mode": "644"}}
    ]
  },
  "right": {"kind": "tar", "entries": ["…同形…"]}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `left` / `right` | 是 | 两侧已装载的工件；`entries` 每项含 `path` / `kind` / `index` / `data` / `facts` |
| `entries[].kind` | 否 | `file` / `dir` / `symlink`（默认 `file`）；目录内容强制为空、sha256 = 空串哈希 |
| `entries[].index` | 否 | 归档内序号（目录输入 = -1）；只有 T5 使用 |
| `entries[].data` | 否 | 条目内容（字符串）；符号链接传链接目标 |
| `entries[].facts` | 否 | 容器/格式事实（键值均为字符串），如 `tar.mtime` / `elf.comp_dir` / `elf.section..sig.size` |
| `params.budget` | 否 | 允许的 T1–T11 类别白名单；缺省为空 |

工件是**已装载**的条目与事实，不是 tar/zip/ELF 字节。归档读取、facts 抽取、ELF/PE/Mach-O
节解析属于工具面，器官不读文件、不联网、不读时钟。

## 2. 判定顺序与等级

**结构对齐**（`align`）：

| 状态 | 条件 |
|---|---|
| `SAME` | 同 relpath、同形态（内容差异交给归因层） |
| `RENAMED` | 仅单侧出现，且该 sha256 在两侧各恰好出现 1 次 |
| `REMOVED` / `ADDED` | 仅单侧出现（同 relpath 异形态会各记一条，不是改名） |

**归因**（`attribute`，优先级 T1→T12）：

| 规则 | 触发事实 | 等级 |
|---|---|---|
| `drift-t1` | `tar.mtime` / `zip.mtime` / `gzip.mtime` | `warn` |
| `drift-t2` | `tar.uid` / `tar.gid` / `tar.uname` / `tar.gname` | `warn` |
| `drift-t3` | `tar.mode` / `zip.external_attr` 权限位 | `warn` |
| `drift-t4` | 两侧公共根前缀不同（树级，先于逐条目） | `warn` |
| `drift-t5` | 条目集合与内容哈希一致、`index` 不同 | `warn` |
| `drift-t6` | `gzip.xfl` / `gzip.os` | `warn` |
| `drift-t7` | `raw_header_sha256` / `zip.create_system` / zip 非权限位 | `warn` |
| `drift-t8` | `elf.comment` / `elf.producer` / `.comment` 节 | `warn` |
| `drift-t9` | `elf.build_id` / `.note.gnu.build-id` / 调试节 | `warn` |
| `drift-t10` | `.sig` 节 | `warn` |
| `drift-t11` | `elf.comp_dir` | `warn` |
| `drift-t12` | 无 T1–T11 解释的内容字节差异 | `error` |
| `drift-unbudgeted` | 出现的 T1–T11 类别不在 `budget` 内 | `error` |
| `drift-cause` | 最小原因集 + 残留字节（只留痕） | `info` |

`tar.size` 是内容长度的派生字段，不单独记账。`zip.external_attr` 的权限位与非权限位
同时变化时同时命中 T3/T7（`notes` 记 `rule_overlap`）。

**残留字节** = 归一化（T1–T11）后两侧 `entry_stream` 逐字节比对的差异之和。
**最小原因集**：按基数升序、同基数按 T1→T11 顺序枚举子集，使树摘要相等即停；
`[]` = 完全一致，`null` = 无解（此时残留字节 > 0）。

## 3. 输出

完全一致（样例）：

```console
$ byteproof check artifact-drift --input samples/artifact-drift.minimal.json
byteproof :: artifact-drift 1 :: artifact-drift.minimal.json
[info] drift-cause — 最小原因集：空集（完全一致）；残留字节：0 :: <tree> (drift-cause@1)
合计 1 条，阻断 0 条（error=0 warn=0 info=1）
```

只有 mtime 差异且 `budget=["T1"]`：

```console
[info] drift-cause — 最小原因集：['T1']；残留字节：0 :: <tree> (drift-cause@1)
[warn] drift-t1 — 归档 mtime 差异（构建时刻痕迹，可归一化） :: a.txt (drift-t1@1)
合计 2 条，阻断 0 条（error=0 warn=1 info=1）
```

`--json` 的单条账本：

```json
{
  "id": "drift-t12@a.txt",
  "rule_id": "drift-t12",
  "verdict": "error",
  "message": "归一化后仍有内容字节差异（残留）",
  "basis_ref": {"rule_id": "drift-t12", "rule_version": "1", "source": "…", "quote": "…"},
  "path": "a.txt",
  "evidence": {"rule_id": "T12", "key": "content", "left": "…", "right": "…", "bytes_delta": 1}
}
```

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---|---|
| `budget` | `[]` | 允许的 T1–T11 类别；不在白名单的类别记 `drift-unbudgeted`（error） |

未知参数键 -> 退出码 2；`budget` 里出现 `T12` -> 退出码 2（残留不可预算）。

## 5. 依据包

随包副本 `src/byteproof/data/artifact-drift.basis.json`（14 条规则，包版本 `1`）。
缺规则 -> `RuleMissing` -> 退出码 3。

## 6. §7.3 四项无损判据 · 实测

口径：`D1 + D18` —— **判据 1 的分母 = 旧仓「判定层」实跑用例数**。判定层 = 文件名不匹配
`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`
的 Go 测试文件（`*_test.go`）；X = `go test` 实跑 passed（含子测试）。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓 7 个包 `go test` 实跑 X = 109 passed（含子测试；顶层 60 个 `func Test`）** / 新仓实跑 **N = 158 passed** | ✅ 过（+49） |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文「完全一致」场景 `./bdiff compare --left …/c01-mtime/pair/left/synthpkg-0.1.0.tar --right 同一文件` 实跑 rc **0**（`minimal_cause_set=[]`、`residue_bytes=0`）；新入口 `check artifact-drift --input samples/artifact-drift.minimal.json` rc **0** | ✅ 过（0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 7 文件；函数数**按条计** → 新 **126**（AST）/ 旧 **60**（`func Test`） | ✅ 过（126 ≥ 60） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（78 条目）；`byteproof/data/artifact-drift.basis.json` **4549B / 14 条规则** + `.thresholds.json` **476B** 均在包内；解包 `check` rc 0 | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
go test ./internal/align ./internal/attribute ./internal/minimize ./internal/normalize
# ok  github.com/yuluo554/10-20-build-diff-ledger/internal/align
# ok  github.com/yuluo554/10-20-build-diff-ledger/internal/attribute
# ok  github.com/yuluo554/10-20-build-diff-ledger/internal/minimize
# ok  github.com/yuluo554/10-20-build-diff-ledger/internal/normalize
go test -json ./internal/align ./internal/artifact ./internal/attribute ./internal/facts \
  ./internal/minimize ./internal/normalize ./tools/gen_fixtures
# passed_events_incl_subtests 109 / top_level_passed 60 / failed 0 / skipped 0
```

`go version` = `go1.27.0 windows/amd64`；来源仓 `git status --porcelain` = **0 行**，
HEAD `1aa8638` 与队列一致。

### 6.2 D1 + D18 逐文件处置表（判定层 7 文件 / 60 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `internal/align/align_test.go` | 7 | **已迁（判定全）** | 四态对齐、每哈希唯一改名、排序、同名异形态；在 `align.py`。 |
| `internal/artifact/artifact_test.go` | 10 | **舍弃** | tar/zip/gzip/whl/jar/OCI 装载与格式校验 = 输入层。 |
| `internal/attribute/attribute_test.go` | 7 | **已迁（判定全）** | T1–T12 分类、T4 先于条目、T5 条件、T12 残留、rule_overlap；在 `attribute.py`。 |
| `internal/facts/facts_test.go` | 9 | **舍弃** | ELF/PE/Mach-O 头与节表抽取 = 字节解析层。 |
| `internal/minimize/minimize_test.go` | 12 | **已迁（判定全）** | 子集枚举顺序、空集/无解语义、基数最小；在 `attribute.minimal_cause_set`。 |
| `internal/normalize/normalize_test.go` | 6 | **部分迁** | 事实级归一化 op、entry_stream、tree_digest 已迁；**ELF 节字节重写**不迁（见 §7）。 |
| `tools/gen_fixtures/gen_test.go` | 9 | **舍弃** | 合成样张生成与冻结校验 = 数据生成面。 |

**D1+D18 机械剔除的包**（不计入分母）：`internal/cli`（`cli`）、`internal/guard`（`guard`）、
`internal/report`（`report`）。分别测 CLI 参数面、源码哨兵、报告渲染。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/artifact-drift.basis.json` | 4549 |
| `byteproof/data/artifact-drift.thresholds.json` | 476 |

wheel 总条目 **78**；解包后 `check artifact-drift` rc 0。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态变了**：旧仓从目录/tar/zip/…装载条目并抽取 facts；本器官吃已装载的
   `entries` + `facts`。**输入不可逐字段重放**，判据 2 的「rc 相同」是等价工件上的相同。
2. **T8–T11 的归一化是简化形**：旧仓重写 ELF 相关节字节；本器官不解析字节，命中
   T8–T11 时把该条目 `data` 置空作为规范形。对「仅工具链/构建目录不同」的样张结论一致；
   对「同一节内既有工具链差异又有真实内容差异」的工件可能**过度归一化**（登记为残余风险）。
3. **退出码**：旧仓 `0` 完全一致/`2` 仅元数据/`3` 有残留/`1` 输入不可解析；本产品
   `0` 无阻断/`1` 有阻断/`2` 输入不合法/`3` 契约违约。因此：
   - 元数据差异且**不在 budget** → 旧 rc 2 / 新 rc **1**（阻断语义保留，码值按产品契约）；
   - 元数据差异且 budget 覆盖 → 旧 rc 0 / 新 rc 0（warn 不阻断）；
   - 残留 → 旧 rc 3 / 新 rc **1**；
   - 输入不可解析 → 旧 rc 1 / 新 rc **2**。
   **不加兼容 rc**（SKELETON-SPEC §5 的映射）。
4. **改名**只影响对齐计数（`evidence.alignment`），不单独落账；旧仓在报告里另有
   `renamed` 列表。本器官的账本以「差异点」为单位。
5. **`residual_items` 不单独输出**：残留以 T12 记录逐条落账（`path` + `bytes_delta`）。
6. **报告面不迁**：`report.json` / `report.md` 键序、`--budget` 的 CLI 参数、发布门、
   合成样张生成、归档装载与事实抽取。