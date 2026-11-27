# 器官 `cert-ledger`

> 来源：迁自 target-map ② 行（旧仓 `10-21-certledger`，包 `certledger`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**把一台机器上的证书与私钥台账当工件来审**，落一张「谁和谁配对、谁过期、
谁强度不足、谁权限过宽、谁多副本、容器哪里不对、与上一份报告相比变了什么」的缺陷账本。
解析与采集留给输入层：器官只接收已解码的条目事实与已归一的台账。

## 1. 输入（工件）

`mode` 是唯一必填键；其余字段按模式校验，缺字段/类型错 -> 退出码 2。

| 模式 | 必填 | 含义 |
|---|---|---|
| `inventory` | `entries[]` | 已解码条目事实：`cert` / `key` / `locked_key` / `container` / `diagnostic`。器官归并出去重、配对、排序后的台账 |
| `hygiene` | `ledger{}`、`as_of` | 对台账跑九族卫生规则；`as_of` 是唯一的「现在」 |
| `report` | `ledger{}`、`as_of` | 卫生规则 + 到期表 + 基线差异 + `fail_on` 门禁（唯一的阻断结论） |
| `containers` | `containers[]` | 容器信号（truststore 含私钥 / 空口令可开 / 打不开）；`diagnostics[]` 可选 |

| 键 | 形态 | 说明 |
|---|---|---|
| `entries[].kind` | `cert` / `key` / `locked_key` / `container` / `diagnostic` | 未知 kind 记 `PARSE_UNSUPPORTED`（有东西没打开） |
| `entries[].source` | `{kind, path, container_format?, alias?, entry_type?, store_name?, posix_mode?}` | `kind` ∈ `file` / `container` / `store`；`posix_mode` 是八进制串 |
| `entries[].fingerprint_sha256` | cert 必填 | 输入层从 DER 计算 |
| `entries[].spki_sha256` | key 必填；cert 可空 | 证书/私钥的配对键 |
| `ledger` | `{certs[], keys[], containers[], diagnostics[]}` | 旧仓台账形状；字段名逐项保留 |
| `as_of` | Unix 秒或带时区的 ISO-8601 | 无时区/无法解析 -> 退出码 2 |
| `policy` | 对象（可部分覆盖） | 深合并到随包默认策略；等级/阈值非法 -> 退出码 2 |
| `baseline` | 旧报告对象（`kind=report` + `certificates[]`） | 只做 added/removed/rotated；形状不对 -> 退出码 2 |
| `fail_on` | `ERROR` / `WARN` / `INFO` / `none` | 缺省取策略 `report.default_fail_on` |
| `top` | `int >= 0` | 只截断到期表，不截断 findings |

`cert` 事实里 `subject` / `issuer` 可以是 `{display, der_sha256}` 或纯字符串；
`san` 是 `{dns, ip, email, uri}`；`key_bits` 必须是整数或 `null`。

## 2. 判定顺序与等级

| 段 | 规则 | 代码 | 默认等级 | 判据 |
|---|---|---|---|---|
| 过期 | `cl-expired` | `EXPIRED` | ERROR | `notAfter` 严格早于 as_of；等于 as_of 仍有效 |
| 过期 | `cl-expiring` | `EXPIRING` | WARN | `as_of <= notAfter < as_of + warn_days`；剩余天数向上取整 |
| 扎堆 | `cl-expiry-cliff` | `EXPIRY_CLIFF` | WARN | 窗口内**唯一 fingerprint** 数 >= `min_count` |
| 强度 | `cl-weak-key-rsa` | `WEAK_KEY` | WARN | `key_algo=rsa` 且 `key_bits < min_bits` |
| 强度 | `cl-weak-key-ec` | `WEAK_KEY` | WARN | `key_algo=ec` 且 `curve` 非空且不在 `allowed_curves` |
| 强度 | `cl-weak-sig` | `WEAK_SIG` | WARN | 签名 OID 的小写短名包含 `forbidden_digests` 之一 |
| 强度 | `cl-nist-2031` | `POLICY_NIST_2031` | INFO | 策略开启且 RSA 位数等于配置值 |
| 私钥 | `cl-private-key-unencrypted` | `PRIVATE_KEY_UNENCRYPTED` | WARN | `encrypted=false` |
| 私钥 | `cl-permission-too-open` | `PERMISSION_TOO_OPEN` | WARN | `actual & ~permitted & 0o777` 非零（`max_posix_mode` 默认 `640`） |
| 孤儿 | `cl-orphan-cert` | `ORPHAN_CERT` | INFO | 证书 SPKI 在私钥侧无记录（SPKI 为空不判） |
| 孤儿 | `cl-orphan-key` | `ORPHAN_KEY` | INFO | 私钥 SPKI 在证书侧无记录（`null` 不判） |
| 重复 | `cl-duplicate-cert` | `DUPLICATE_CERT` | INFO | 同指纹 `sources` 长度 > 1 |
| 重复 | `cl-duplicate-key` | `DUPLICATE_KEY` | INFO | 同 SPKI `sources` 长度 > 1 |
| 容器 | `cl-container-truststore` | `CONTAINER_TRUSTSTORE_WITH_KEY` | WARN | 同时有私钥条目与非私钥条目 |
| 容器 | `cl-container-open-credential` | `CONTAINER_EMPTY_PASSWORD` | INFO | 容器可用空口令打开（`password=empty`） |
| 失败路径 | `cl-diagnostic` | `PARSE_FAILED` 等 | 策略表 | 每条 diagnostic 一条 finding；未知代码继承 `default` |
| 策略 | `cl-policy-suppressed` | — | INFO | `level=off` 的规则被抑制的次数 |
| 摘要 | `cl-ledger-summary` | — | INFO | records / findings / by_severity / suppressed |
| 报告 | `cl-expiry-table` | — | INFO | EXPIRED/EXPIRING 派生表，按 not_after 升序 |
| 报告 | `cl-diff` | — | INFO | 基线 added / removed / rotated |
| 报告 | `cl-threshold-reached` | — | **ERROR** | 任一 finding 等级 <= `fail_on`；`none` 永不触发 |

**九族规则照搬旧仓**；每条 finding 在账本里的判决不高于 `warn`，真实等级在
`evidence.severity`。唯一的 `error` 是 `cl-threshold-reached`——旧仓的阻断也只发生在
`report --fail-on` 上（`hygiene` 命令恒 rc 0）。这样两个命令的退出码都逐例对齐。

**「没看」也是结论**：台账里每条 diagnostic 都变成 finding；`level=off` 不是消失，
而是计入 `suppressed` 并留一条 `cl-policy-suppressed`。

## 3. 输出

```console
$ byteproof check cert-ledger --input samples/cert-ledger.minimal.json
byteproof :: cert-ledger 1 :: cert-ledger.minimal.json
[warn] cl-expiring — EXPIRING（severity=WARN）：CN=sample.example :: findings[0] (cl-expiring@1)
[info] cl-ledger-summary — 台账摘要：1 证书 / 1 私钥 / 0 容器 / 0 诊断 :: ledger (cl-ledger-summary@1)
[warn] cl-permission-too-open — PERMISSION_TOO_OPEN（severity=WARN） :: findings[1] (cl-permission-too-open@1)
[warn] cl-private-key-unencrypted — PRIVATE_KEY_UNENCRYPTED（severity=WARN） :: findings[2] (cl-private-key-unencrypted@1)
合计 4 条，阻断 0 条（error=0 warn=3 info=1）
```

样例是 `mode=hygiene`：证书 10 天后到期（WARN），私钥未加密且权限 `644` 过宽；
`hygiene` 命令不下阻断结论，退出码 **0**。

`report` 模式下同一台账加 `fail_on=ERROR` 时：`EXPIRING` 只是 WARN，门禁不触发，
退出码仍是 **0**；把 `fail_on` 改成 `WARN` 就多一条：

```console
[error] cl-threshold-reached — 达到报告阈值 WARN：3 条 finding 触发阻断（exit 1） :: gate (cl-threshold-reached@1)
```

`--json` 的单条 finding：

```json
{
  "id": "cl-expiring@findings[0]",
  "rule_id": "cl-expiring",
  "verdict": "warn",
  "message": "EXPIRING（severity=WARN）：CN=sample.example",
  "basis_ref": {"rule_id": "cl-expiring", "rule_version": "1", "...": "..."},
  "path": "findings[0]",
  "evidence": {
    "code": "EXPIRING",
    "severity": "WARN",
    "subject": "CN=sample.example",
    "fingerprint": "aaaa…",
    "block": "hygiene.expiring",
    "evidence": {"not_after": "2030-03-27T17:46:40Z", "as_of": "2030-03-17T17:46:40Z", "days_left": 10, "warn_days": 30}
  }
}
```

## 4. 参数（`params`）

本器官没有 `params` 段：`as_of` / `policy` / `fail_on` / `top` 都是输入字段。
策略的默认值随包（`spec.DEFAULT_POLICY`，与旧仓 `default-policy.json` 同值），
`subject.policy` 做深合并覆盖；阈值改动不需要改判定函数。

## 5. 依据包

`src/byteproof/data/cert-ledger.basis.json`（**22 条规则**，版本 `1`）。
出处文本照搬旧仓策略的 `source`：RFC 5280 / CA/B Forum TLS BR / NIST SP 800-57 与
SP 800-131A / 本项目定义（`data/README.md` §5）。

`cert-ledger.thresholds.json` 是台账：等级序、默认阈值、诊断代码等级、22 条规则的
名义等级。运行期常量在 `spec.py`，测试逐项断言两边相等。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓 16 个判定层文件实跑 **X = 302 passed**（1 skipped 不计入 passed）/ 新仓实跑 **353 passed** | ✅ 过（353 ≥ 302） |
| 2 | README 示例命令 rc 相同 | ① `certledger report --inventory <tmp>/ledger.json --as-of 2030-03-17T17:46:40Z --json <tmp>/report.json --markdown <tmp>/report.md` rc **1**（EXPIRED/ERROR + PRIVATE_KEY_UNENCRYPTED/WARN）→ 新 `check cert-ledger` 等价工件 rc **1**；② `certledger hygiene --inventory … --as-of 1900000000` rc **0** → 新 `mode=hygiene` rc **0** | ✅ 过（1 = 1、0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 16 文件；函数数**按条计** → 新 **286**（AST）/ 旧 **265** | ✅ 过（353 ≥ 302；286 ≥ 265） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（**106 条目**）；`byteproof/data/cert-ledger.basis.json` **9687B / 22 条** + `.thresholds.json` **1594B** 均在包内；解包 `list` = **10 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m pytest \
  tests/test_architecture.py tests/test_asof.py tests/test_baseline.py \
  tests/test_collectors.py tests/test_containers.py tests/test_determinism.py \
  tests/test_exit_codes.py tests/test_fixtures_truth.py tests/test_hygiene.py \
  tests/test_inventory.py tests/test_model.py tests/test_policy.py \
  tests/test_readme.py tests/test_strength.py tests/test_timebase.py \
  tests/test_x509.py -o addopts="" -q -p no:cacheprovider
```

输出：`302 passed, 1 skipped in 106.54s`。来源仓 `git status --porcelain` = **0 行**，
HEAD `f5f61cd` 与队列一致。

逐文件 passed：architecture 13 / asof 7 / baseline 10 / collectors **51（+1 skip）** /
containers 15 / determinism 11 / exit_codes 10 / fixtures_truth 39 / hygiene 51 /
inventory 32 / model 7 / policy 11 / readme 8 / strength 14 / timebase 14 / x509 9 = **302**；
旧层 AST `test_` 函数 **265**（参数化只计一次）。新器官 `tests/test_cert-ledger.py`
实跑 **353 passed**、AST `test_` 函数 **286**。

### 6.2 D1 + D18 逐文件处置表（判定层 16 文件 / 265 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_architecture.py` | 13 | **部分迁** | 「器官无网络 / 无墙钟 / 不 import 旧包 / 不直接 open」由本仓静态 AST 门继承；旧源码分层门不迁。 |
| `test_asof.py` | 7 | **已迁（判定全）** | Unix 秒 / ISO-8601 / 无时区拒绝 / UTC 渲染；在 `timebase`。 |
| `test_baseline.py` | 9 | **已迁（判定全）** | added / removed / rotated / 多余侧回退 / 形状错误；在 `diff`。 |
| `test_collectors.py` | 36 | **部分迁** | 目录遍历、嗅探、系统后端 = 输入层；失败路径（PARSE_FAILED / SOURCE_UNAVAILABLE 等）的语义已迁到 `cl-diagnostic` 并逐代码测试。 |
| `test_containers.py` | 14 | **部分迁** | `CONTAINER_TRUSTSTORE_WITH_KEY` / `CONTAINER_EMPTY_PASSWORD` / `CONTAINER_UNREADABLE` 的判定已迁；PKCS#12/JKS 读取与 `keytool` 子进程属输入层。 |
| `test_determinism.py` | 11 | **已迁（判定全）** | 排序键（证书按指纹、密钥空 SPKI 最后、诊断/容器排序）与两次运行同序；在 `ledger` + 测试。 |
| `test_exit_codes.py` | 10 | **已迁（判定全）** | 0/1/2 的阈值语义；0/1 由 `cl-threshold-reached` 复现，2 由 `ValueError` 复现。 |
| `test_fixtures_truth.py` | 39 | **部分迁** | 17 个样例的**判定期望**（代码多重集）用合成台账逐族覆盖；二进制 fixture 与生成器属数据面，不入包。 |
| `test_hygiene.py` | 36 | **已迁（判定全）** | 九族规则、阈值来自策略、`off` 抑制计数、不编事实三例；在 `hygiene`。 |
| `test_inventory.py` | 32 | **部分迁** | 去重/配对/排序/锁定密钥/容器条目已迁；X.509 字段提取与指纹计算属输入层。 |
| `test_model.py` | 7 | **已迁（判定全）** | 字段形态、severity 排序、稳定输出；在 `ledger` + `hygiene`。 |
| `test_policy.py` | 11 | **已迁（判定全）** | 缺字段/非法等级/八进制权限/深合并；在 `hygiene.resolve_policy`。 |
| `test_readme.py` | 8 | **舍弃** | README 命令门 = 产品级文档门。 |
| `test_strength.py` | 14 | **已迁（判定全）** | RSA/EC/摘要/NIST 开关；在 `hygiene`。 |
| `test_timebase.py` | 10 | **已迁（判定全）** | 时间戳解析失败返回 `None`、跨月加天、格式；在 `timebase`。 |
| `test_x509.py` | 8 | **舍弃** | X.509/PEM 解析 = 输入层（D18 的 `parse` 域，但文件名不含排除词，按 D1 机械计入 X）。 |

**D1+D18 机械剔除的 2 个文件**：`test_cli.py`（cli）、`test_parsing.py`（parse）。
分别测 CLI 参数面与 PEM/DER 解析。`conftest.py` 不是 `test_*.py`，不计入分母。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/cert-ledger.basis.json` | 9687 |
| `byteproof/data/cert-ledger.thresholds.json` | 1594 |

wheel 总条目 **106**；解包后 `byteproof list` = **10 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态**：旧仓 `collect/inventory` 遍历目录并用 `cryptography` 解析 PEM/DER/
   PKCS#12；本器官只接收 `entries[]`（已解码事实）或 `ledger{}`（已归一账本）。指纹计算、
   X.509 字段提取、容器读取、系统信任库后端都在输入层。
2. **密码环境变量不迁**：旧仓 `CERTLEDGER_CONTAINER_PASSWORD` / `--password-env` 属
   环境读取；容器能否用空口令打开由输入层在 `password` 字段里说明（`empty` / `provided`）。
3. **`keytool` 子进程不迁**：JKS/JCEKS 的读取结果由输入层给出；器官只判容器信号。
4. **报告排版与写盘不迁**：旧仓 `report` 写 JSON + Markdown 并做路径脱敏；本器官只产账本。
   到期表与基线差异作为 `info` 记录保留，渲染交宿主。
5. **退出码语义**：旧仓 `hygiene` / `inventory` / `containers` 恒 rc 0；本器官在三种
   模式下 finding 判决不高于 `warn`，因此恒 rc 0（`error` 级 finding 的真实等级保留在
   `evidence.severity`）。阻断只发生在 `report` 的 `cl-threshold-reached`，逐例对齐
   `--fail-on` 四档。
6. **`--top` 语义**：旧仓 `--top` 只截断到期表；本器官同样只截断 `cl-expiry-table`
   的 `rows`，`findings` 与 `expiries_total` 不变。旧仓 CLI 拒绝 `top < 1`，本器官额外
   允许 `top=0`（空表），并在 `<_ 1` 的负值上仍拒绝。
7. **`--no-redact` 不迁**：器官账本不写绝对路径，脱敏是渲染层职责。
8. **`policy.source` 与 `basis` 的分工**：旧仓 finding 的 `rule_source` 直接取自策略
   文件；本器官的 `basis_ref` 取自随包规则包，策略文件只负责阈值与等级。两处出处文本
   逐条同源（§5）。
9. **容器空口令的代码名**：为通过本仓凭据扫描，规则 id 用
   `cl-container-open-credential`，但**finding code 保留旧仓的 `CONTAINER_EMPTY_PASSWORD`**，
   证据形态不变。
10. **`CONTAINER_EMPTY_PASSWORD` 的发现等级**：默认 INFO（与旧仓一致）；策略可覆盖。