# byteproof · 内核契约（Stage 1）

> 本页是**内核**（`src/byteproof/core/` 与 `src/byteproof/cli.py`）的唯一说明处。
> 每个器官另有一页 `docs/<slug>.md`（输入 / 规则 / 输出示例），内核页不复述它们。
> 契约字段、退出码、目录形状与 `clauseproof` / `speccalc` / `traceproof` 共用一份
> `SKELETON-SPEC`；本页只写 **byteproof 自己的那一列**（缺陷账本 + 规则登记）。

## 1. 这个产品回答什么

给定一个工件（字节流、配置、依赖清单、归档……）和一份带版本的规则包，
输出**缺陷账本**：每条结论 = 一个位置 + 一条规则依据 + 一个等级。

它不做的事：不带自己的 CLI、不读时钟、不联网、不修改输入工件。
器官（auditor）只声明规则怎么判，不决定怎么打印。

## 2. 唯一入口

```text
byteproof list                          # 列出器官（slug / 版本 / 摘要）
byteproof check <slug> --input <file>   # 跑一个器官
byteproof check <slug> --input -        # stdin
byteproof --version
```

器官签名固定：

```python
evaluate(subject: Mapping, basis: Basis) -> Iterable[Record]
```

- `subject`：输入 JSON 对象（器官在自己的 `input_fields` 里声明必填键）；
- `basis`：规则包（`Basis`），器官只能通过 `basis.ref(rule_id)` 取依据。

## 3. 缺陷账本（本产品的 record 类型）

| 字段 | 含义 |
|---|---|
| `id` | 稳定键：`<rule_id>@<path>`，同一缺陷重复跑得到同一个 id |
| `verdict` | `error` / `warn` / `info` |
| `message` | 人读结论；降级时必须写明缺失项 |
| `basis_ref` | `{rule_id, rule_version, source, quote}`；无依据为 `null` |
| `path` | 缺陷在工件里的位置（文件路径 / JSON 指针 / 偏移区间） |
| `evidence` | 机器可读证据（命中片段、期望值、实际值……） |

`error` 是唯一阻断级；`warn` / `info` 只记录。

## 4. 三条内核约束（违反即退出码 3）

1. **无依据不下 `error`**：`error` 且 `basis_ref` 为空 → `ContractError`（不是警告）。
2. **依据缺版本就降级**：`rule_version` 为空 → 结论降级为 `info`，`message` 追加
   「依据缺版本……」；规则包自身缺版本 → 直接契约违约。
3. **输出确定性**：`--json` 无时间戳、无绝对路径、字段顺序固定；同一输入两次运行字节一致。

## 5. 退出码

| 码 | 含义 | 本产品的触发点 |
|---|---|---|
| 0 | 无阻断性结论 | 全部 `warn` / `info`（含全 `info` 降级） |
| 1 | 存在阻断性结论 | 至少一条 `error` |
| 2 | 输入不合法 | 输入文件缺失/非法 JSON/缺 `input_fields` 声明键/器官参数键未知 |
| 3 | 契约违约 | 无依据下 `error`、规则包版本缺失、规则缺失（`RuleMissing`）、器官不存在 |

> **与 clauseproof 的一处口径差**：clauseproof 当前把「条文库缺该条款」归到退出码 2
> （输入问题），本产品按 `SKELETON-SPEC` §5 把「规则包缺失」归到 3。待 clauseproof
> 器官迁移时一并对齐，届时本注记删除。

**规则包从哪来**（迁入第一个器官时定下，后续器官同一条）：

1. `--basis <file>` 给了就用它，**只用**它；
2. 没给就找随包分发的 `byteproof/data/<slug>.basis.json`（器官自己的规则包）；
3. 两者都没有才是空规则包 —— 此时器官调 `basis.ref` 会抛 `RuleMissing`（退出码 3）。

这条解析放在 CLI 而不是器官里：器官不读文件是契约，而 §2 把
`<product> check <slug> --input <file>` 定成唯一调用形态（它没有 `--basis`），
所以"不带额外参数也该能审"必须由宿主保证。

## 6. 加一个器官

```text
src/byteproof/auditors/<slug>/__init__.py   # register(Pack(slug=..., version=..., summary=...,
                                            #              input_fields=(...), evaluate=...))
src/byteproof/auditors/__init__.py          # 把模块名加进 BUILTIN_MODULES（显式清单）
tests/test_<slug>.py                        # 该器官的无损测试
docs/<slug>.md                              # 输入 / 规则 / 输出示例
src/byteproof/data/<slug>.basis.json        # 规则包（rule_id + 依据文本 + 版本）
src/byteproof/data/<slug>.thresholds.json   # 阈值/等级台账（与运行期常量逐项相等）
```

**显式清单而不是扫描**：扫描式加载会把「器官忘了登记」变成静默空跑。
**规则包必须随包分发**：`pip wheel` 后包里 `data/` 为空就等于"装上了但审不了"。

## 7. 示例（已迁入 3 个器官）

```console
$ byteproof list
duplicate-docs                   1          文档工件缺陷账本：正文归一化后按精确 Jaccard 判同源重复
media-type-check                 1          MIME 工件缺陷账本：头宽/编码字/传输编码/容器/归属五域的条款一致性
timeseries-anomaly               1          时序工件缺陷账本：时间轴完整性 + 采样形状 + 四个确定性检测器命中段

$ byteproof check no-such --input samples/timeseries-anomaly.minimal.json
PackMissing: 未注册的器官：no-such          # 退出码 3
```

| 器官 | 版本 | 文档 |
|---|---|---|
| `duplicate-docs` | 1 | [`duplicate-docs.md`](duplicate-docs.md) |
| `media-type-check` | 1 | [`media-type-check.md`](media-type-check.md) |
| `timeseries-anomaly` | 1 | [`timeseries-anomaly.md`](timeseries-anomaly.md) |

器官表按 `_workspace/target-map-20261125.tsv` 的 ②byteproof 行逐个补齐。