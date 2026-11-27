# 器官 `config-drift`

> 来源：迁自 target-map ② 行（旧包 `cfgdelta`）。迁入版本：`1`。
> 契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把两份配置的差异条目当工件审，落一张「每条差异属于哪类影响、是否阻断」的
缺陷账本。** 搬过来的是判定（值族归一 + 六类影响分类 + semver 子类 + gate），
不是 YAML/TOML 解析器，也不是 config diff 工具。

## 1. 输入（工件）

```json
{
  "entries": [
    {
      "path": "/spec/template/spec/containers/0/resources/limits/memory",
      "kind": "changed",
      "left": {"family": "quantity", "raw": "1Gi"},
      "right": {"family": "quantity", "raw": "512Mi"}
    }
  ],
  "params": {"fail_on": ["资源·收缩"], "allow_indeterminate": false}
}
```

| 键 | 必填 | 含义 |
|---|---|---|
| `entries[].path` | 是 | JSON Pointer 风格路径（决定影响类） |
| `entries[].kind` | 是 | `changed` / `added` / `removed` / `cosmetic` / `indeterminate` |
| `entries[].left` / `right` | changed 时 | 值节点：`{family, raw}`；`family` ∈ quantity / duration / decimal / bool / null / string / unknown |
| `entries[].reason` | indeterminate 时 | 原因码（如 `ambiguous_unit_family` / `unevaluated_expression`） |
| `params.fail_on` | 否 | 只在列出的类命中时阻断；空 = 任一行为差异都阻断 |
| `params.allow_indeterminate` | 否 | 允许不可判定（不因 indeterminate 阻断） |

条目是**已结构对齐后**的差异（旧仓 `internal/diff` 的产物形状），不是原始 YAML。
格式解析、结构无关比较、默认值 profile 双侧施加属于工具面，器官不读文件、不联网、不读时钟。

## 2. 判定顺序与等级

**值族归一**（`value`）：

| 族 | 文法 | 精确形式 |
|---|---|---|
| quantity | K8s apimachinery：`Ki…Ei` = 1024ⁿ；`n u m k M G T P E` = 10ⁿ；指数与后缀互斥 | `Fraction` |
| duration | Go `time.ParseDuration`（`ns us µs μs ms s m h`，可组合） | 纳秒 `Fraction` |
| decimal | 精确十进制（`1.0 ≡ 1`、`1e3 ≡ 1000`） | `Fraction` |
| bool | YAML 1.1 plain 标量（`yes/on/TRUE/…`） | `true` / `false` |
| null | absent / explicit null / empty string 三态分开 | 状态 |
| unknown | HCL 表达式等不可求值 | `indeterminate(reason)` |

`MB` / `MiB` / `B` 等非 K8s 字节单位 -> `ambiguous_unit_family`，**绝不静默判等**；
`1Gi ≠ 1000M`。

**影响分类**（`classify`，顺序固定）：

| 类 | 触发 |
|---|---|
| 镜像·变更 | `image` 变化；纯数字点分标签给 major/minor/patch，其余 non-semver |
| 资源·收缩 | `resources/limits|requests` 同族变小；`replicas` 减少 |
| 部署·收缩 | `maxUnavailable` 变大 / `minReadySeconds` 变大 |
| 接口·暴露 | `/ports` `/serviceType` `/selector` /`/ingress` `/rules` `/host` `/http/paths`；`protocol` 除外 |
| 配置·新增·移除 | `env` / `data` / `stringData` / `envFrom` / `configMap` / `secret` |
| 纯书写 | kind=cosmetic，或 changed 两侧同族归一后相等（资源路径优先级更高，见 §7） |
| 兜底 | 其余变化 -> 配置·新增·移除 + `class_guess=true`（禁止归入纯书写） |

**Gate**：indeterminate 默认阻断；未列 `fail_on` 时任一行为差异阻断；列了则只看所列类。
未列出的行为差异**照常输出但不阻断**。

账本等级：五类行为差异与 indeterminate 记 `warn`；`cfg-gate` 命中记 `error`；
纯书写与汇总记 `info`。

## 3. 输出

纯书写样例（`1.0` vs `1`）：

```console
$ byteproof check config-drift --input samples/config-drift.minimal.json
byteproof :: config-drift 1 :: config-drift.minimal.json
[info] cfg-cosmetic — 归一后语义相同（纯书写，只计数） :: /metadata/annotations/revision (cfg-cosmetic@1)
[info] cfg-summary — total 1 · behavioral 0 · cosmetic 1 · indeterminate 0 :: <summary> (cfg-summary@1)
合计 2 条，阻断 0 条（error=0 warn=0 info=2）
```

资源收缩（`fail_on=["资源·收缩"]`）：

```console
[warn] cfg-resource-shrink — 资源·收缩 :: /spec/replicas (cfg-resource-shrink@1)
[error] cfg-gate — 门禁命中：资源·收缩（fail_on=['资源·收缩']…） :: <summary> (cfg-gate@1)
合计 … 阻断 1 条
```

`--json` 的单条账本：

```json
{
  "id": "cfg-resource-shrink@/spec/replicas",
  "rule_id": "cfg-resource-shrink",
  "verdict": "warn",
  "message": "资源·收缩",
  "basis_ref": {"rule_id": "cfg-resource-shrink", "rule_version": "1", "source": "…", "quote": "…"},
  "path": "/spec/replicas",
  "evidence": {"path": "/spec/replicas", "class": "资源·收缩", "subclass": "", "class_guess": false,
               "left": {"family": "decimal", "text": "3", "rat": "3"}, "right": {…}}
}
```

## 4. 参数（`params`）

| 键 | 默认 | 说明 |
|---|---|---|
| `fail_on` | `[]` | 只在列出的类命中时阻断（六个类名之一） |
| `allow_indeterminate` | `false` | 允许不可判定 |

未知参数键 / 未知类名 -> 退出码 2。阈值台账
`src/byteproof/data/config-drift.thresholds.json` 与运行期默认值逐项相等（测试钉住）。

## 5. 依据包

随包副本 `src/byteproof/data/config-drift.basis.json`（9 条规则，包版本 `1`）。
缺规则 -> `RuleMissing` -> 退出码 3。

## 6. §7.3 四项无损判据 · 实测

口径：`D1 + D18` —— **判据 1 的分母 = 旧仓「判定层」实跑用例数**。判定层 = 文件名不匹配
`cli|gui|packaging|audit|desensit|guard|bench|infra|export|version|license|generat|docs?_|health|release|selftest|smoke|parse|report|input|output|web|panel`
的 Go 测试文件；X = `go test` 实跑 passed（含子测试）。

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | **旧仓 6 个判定层包 `go test` 实跑 X = 79 passed（含子测试；顶层 66 个 `func Test`）** / 新仓实跑 **N = 163 passed** | ✅ 过（+84） |
| 2 | README 示例命令 rc 相同 | 旧仓 README 原文 `cfgdelta diff --profile k8s/v1.29 testdata/golden/testA/k1.yaml testdata/golden/testA/k2.yaml` 实跑 rc **0**（`total 2 · behavioral 0 · cosmetic 2 · indeterminate 0`）；新入口 `check config-drift --input samples/config-drift.minimal.json` rc **0** | ✅ 过（0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 6 文件；函数数**按条计** → 新 **123**（AST）/ 旧 **66**（`func Test`） | ✅ 过（123 ≥ 66） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（85 条目）；`byteproof/data/config-drift.basis.json` **3473B / 9 条规则** + `.thresholds.json` **433B** 均在包内；解包 `check` rc 0 | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
go test -count=1 ./internal/classify ./internal/diff ./internal/doc \
  ./internal/profile ./internal/value ./tests
# ok  github.com/yuluo554/10-20-cfgdelta/internal/classify
# ok  github.com/yuluo554/10-20-cfgdelta/internal/diff
# ok  github.com/yuluo554/10-20-cfgdelta/internal/doc
# ok  github.com/yuluo554/10-20-cfgdelta/internal/profile
# ok  github.com/yuluo554/10-20-cfgdelta/internal/value
# ok  github.com/yuluo554/10-20-cfgdelta/tests
go test -json -count=1 <同上> | 计数
# passed_events_incl_subtests 79 / top_level_passed 66 / failed 0 / skipped 0
```

`go version` = `go1.27.0 windows/amd64`；来源仓 `git status --porcelain` = **0 行**，
HEAD `357ca8e` 与队列一致。**`dist/` 整树副本与 `.tmp/` 副本已排除**（`go test ./...`
只跑 `internal/` 与 `tests/`，不含 `dist/`）。

### 6.2 D1 + D18 逐文件处置表（判定层 6 文件 / 66 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `internal/classify/classify_test.go` | 7 | **已迁（判定全）** | 六类分类、semver 子类、排序、汇总、gate；在 `classify.py`。 |
| `internal/diff/diff_test.go` | 12 | **部分迁** | 分类消费的 diff 条目契约已迁（changed/added/removed/cosmetic/indeterminate）；**结构无关比较**（keyed/set/ordered、RFC 6901 转义）属工具面。 |
| `internal/doc/doc_test.go` | 20 | **舍弃** | YAML/JSON/TOML/INI/.env/HCL 解析与适配器 = 输入层。 |
| `internal/profile/profile_test.go` | 8 | **舍弃** | 版本化默认值表与双侧抵消 = profile 层。 |
| `internal/value/helpers_test.go` | 0 | **舍弃** | 测试辅助函数（无 `func Test`）。 |
| `internal/value/value_test.go` | 12 | **已迁（判定全）** | quantity/duration/decimal/bool/null 文法、精确有理数、歧义单位 indeterminate；在 `value.py`。 |
| `tests/baseline_archive_test.go` | 2 | **舍弃** | 三家基线归档 = 发布留档。 |
| `tests/invariants_test.go` | 4 | **部分迁** | 「比较路径无浮点」由 `Fraction` 实现并以 AST/用例守住；源码不变量门不迁。 |
| `tests/readme_commands_test.go` | 1 | **舍弃** | README 命令退出码门 = 产品级文档门。 |

**D1+D18 机械剔除的包**：`internal/cli`（`cli`）。`internal/exitcode` / `internal/selftest` /
`internal/version` 无测试文件。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/config-drift.basis.json` | 3473 |
| `byteproof/data/config-drift.thresholds.json` | 433 |

wheel 总条目 **85**；解包后 `check config-drift` rc 0。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态变了**：旧仓从两份配置文件解析 + 结构无关 diff + 默认值 profile；本器官吃
   已对齐的差异条目。**输入不可逐字段重放**，判据 2 的「rc 相同」是等价工件上的相同。
2. **分类顺序的副作用**：`resources/limits|requests` 路径先判收缩/配置，**不再落到**
   「归一后相等 -> 纯书写」。因此 `1Gi` vs `1024Mi` 在 limits 下仍归「配置·新增·移除」
   （与旧仓同序，不是本器官的改动）。
3. **semver 的 tag 解析**：与旧仓 `tagOf` 一致 —— 只有带 `/` 的镜像引用才剥去 `:tag`
   之前的仓库名；`app:1.2.3`（无 `/`）按整体标签解析 -> `non-semver`。
4. **退出码映射**：旧仓 `0` 等价 / `1` 行为差异 / `2` 不可判定 / `3` 解析或用法错误；
   本产品 `0` 无阻断 / `1` 有阻断 / `2` 输入不合法 / `3` 契约违约。因此：
   - gate 命中（含默认的 indeterminate）→ 新 rc **1**（旧 1 或 2）；
   - 条目结构非法（缺 path/kind/未知族）→ 新 rc **2**；
   - 规则缺失 → 新 rc **3**。
   **不加兼容 rc**。
5. **`fail_on` 语义**照搬：未列出的行为差异仍落账（warn）但不阻断；空 fail-on = 任一行为
   差异阻断；`allow_indeterminate` 只抑制 indeterminate 导致的阻断。
6. **未迁的输出面**：CLI 子命令（normalize/diff/gate/selftest）、渲染、golden harness、
   默认值 profile 双侧施加、格式解析。