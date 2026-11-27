# 器官 `media-trace`

> 来源：迁自 target-map ② 行（旧仓 `10-27-mediatrace`，**Go 源**，包 `mediatrace`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**同一个 MP4 内部，多条时间轴口径是否互相自洽；不自洽时差在哪个盒子、
哪一字节、差多少**。Go 源的逻辑用 Python 重写；输入是输入层解析好的**事实**
（`subject.facts`），不解码、不联网、不读文件、不读时钟。

## 1. 输入（工件）

`mode` 与 `facts` 必填；`modules` 可选（缺省 M1–M5，给子集时只跑选中的模块）。

| 模块 | 判什么 |
|---|---|
| `M1` | 结构：盒子尺寸 < 8、子盒越界、顶层 mdat 截断、重复 moov/mdat、stco 越界、ftyp 品牌、嵌套深度 |
| `M2` | 时长：mvhd/tkhd/mdhd/elst 互比（1 tick 容差）、elst 速率/次序/空 edit、首帧 PTS、不可推导 |
| `M3` | 时间戳：stts 零时长/32 位越界/回退、tfdt 回退/v0 越界、极小时基、VFR |
| `M4` | 偏移：priming 声明/匹配、起点裁剪、roll distance、无 edts 的非零起点、未知编码 |
| `M5` | 显示：16.16 矩阵正交、±90° 与宽高、SAR/DAR、colr 多实例、HDR 元数据/范围 |

| `facts` 键 | 形态 | 说明 |
|---|---|---|
| `file_size` | 整数 | 用于判 mdat 截断 |
| `boxes[]` | `{type, offset, size, depth, parent_end?, path?}` | 盒子树由输入层给出；`offset + size` 是末端 |
| `anomalies[]` | `{kind, offset, box_type?, declared?, depth?}` | `too_small_size` / `max_depth` |
| `mdat[]` | `{offset, size}` | stco 偏移必须落在某个区间内 |
| `moov_count` / `stco[]` | 整数 / 整数数组 | 重复 moov 时跳过 stco 区间校验 |
| `ftyp` | `{major, compatible_brands[]}` | 编码品牌必须有通用容器品牌兜底 |
| `movie` | `{timescale, duration, tracks[]}` | 影片时基是互比的统一口径 |
| `tracks[]` | `timescale`/`duration`/`tkhd_duration`/`stts`/`elst`/`fragments`/`codec`/`display` … | 轨道事实，字段名与旧仓报告一致 |

`stts` = `[[count, delta], …]`；`elst` = `[{segment_duration, media_time, rate}, …]`；
`fragments` = `[{index, tfdt, duration, version}, …]`；`display.matrix` = 9 个 16.16 整数。

## 2. 判定顺序与等级

等级词表只有 `fail` 与 `gray`（对应旧仓三态里的两种非 pass）：

- `fail`：自洽性被明确破坏，必须修；
- `gray`：判不准（未知编码、VFR、极小时基、HDR 缺元数据…），**不默默给 0**。

| 模块 | 规则（旧仓 code） | 等级 |
|---|---|---|
| M1 | `too_small_size` / `child_overruns_parent` / `duplicate_moov` / `duplicate_mdat` / `stco_out_of_mdat` / `truncated_mdat` / `ftyp_brand_mismatch` / `max_depth_exceeded` | fail |
| M2 | `duration_mismatch` / `elst_item_rate_not_one` / `elst_item_order_suspect` / `empty_edit` / `first_pts_outside_media` | fail |
| M2 | `duration_unknown` | gray |
| M3 | `tfdt_regression` / `zero_duration_entry` / `dts_overflow_risk` / `dts_regression` | fail |
| M3 | `timescale_suspect` / `vfr_detected` | gray |
| M4 | `priming_undeclared` / `priming_mismatch` / `start_trim` | fail |
| M4 | `no_roll_distance` / `no_edts_but_nonzero_start` / `unknown_codec_priming` | gray |
| M5 | `matrix_not_orthogonal` / `rotation_dimension_conflict` / `sar_dar_conflict` / `colr_multi_instance` / `hdr_range_suspect` | fail |
| M5 | `hdr_metadata_missing` | gray |
| 摘要 | `mt-summary` | info |
| 门禁 | `mt-gate` | **error** |

**关键口径**：
- 时长互比统一在 `mvhd.timescale`（整数向下取整），容差 **1 tick**；
- `elst` 按文件内顺序编号，不排序；空 edit 必须在最前且时长非 0；
- `first_pts_outside_media` 只在编辑表跨度与媒体时长不一致时才判（合法裁剪不误报）；
- tfdt 回退容差 **0**；溢出后 wrap 造成的回退不再单报（同一根因合并）；
- 极小时基阈值 **100**，且未触发溢出时才报 gray；
- matrix 用 16.16 整数正交检查，容差 **1/65536**，不做浮点近似。

## 3. 输出

```console
$ byteproof check media-trace --input samples/media-trace.minimal.json
byteproof :: media-trace 1 :: media-trace.minimal.json
[info] mt-summary — fail=0 gray=0 → pass（旧仓退出码 0） :: summary (mt-summary@1)
合计 1 条，阻断 0 条（error=0 warn=0 info=1）
```

样例是一份干净 MP4 事实：moov/mdat 各一、stco 落在 mdat 内、mvhd 与放映时长都是
1000 tick、stts 只有一条、priming 已声明。

对旧仓夹具 `c2_stco_out_of_mdat.mp4` 的等价事实：

```console
[warn] mt-stco-out-of-mdat — stco_out_of_mdat（fail/M1）：stco 偏移 5208 不在任何 mdat 内 :: findings[0] (mt-stco-out-of-mdat@1)
[error] mt-gate — 阻断：fail=1 gray=0（旧仓退出码 1 映射为 1） :: gate (mt-gate@1)
[info] mt-summary — fail=1 gray=0 → fail（旧仓退出码 1） :: summary (mt-summary@1)
```

`--json` 的单条 finding：

```json
{
  "id": "mt-stco-out-of-mdat@findings[0]",
  "rule_id": "mt-stco-out-of-mdat",
  "verdict": "warn",
  "message": "stco_out_of_mdat（fail/M1）：stco 偏移 5208 不在任何 mdat 内",
  "path": "findings[0]",
  "evidence": {
    "code": "stco_out_of_mdat",
    "status": "fail",
    "module": "M1",
    "values": [{"name": "chunk_offset", "value": 5208}],
    "delta": null,
    "offset": 5208,
    "path": ""
  }
}
```

## 4. 参数（`params`）

本器官没有 `params` 段：阈值是冻结常量（§5），`modules` 是输入字段。
`modules` 给 M9 或类型错 -> 退出码 2。

## 5. 依据包

`src/byteproof/data/media-trace.basis.json`（**34 条规则**，版本 `1`）。
出处照搬旧仓每个模块的 `RuleIDs` 与 `data/README.md` §5 口径：
TickTolerance 1 / TimescaleSuspectBelow 100 / MatrixOrthoTolerance 1 /
DTSRegressionTolerance 0 / 16.16 rate 1.0。

`media-trace.thresholds.json` 是台账：五个模块、策略常量、priming 表、roll-distance
编码表、code→rule 映射。运行期常量在 `spec.py`，测试逐项断言两边相等。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓 10 个判定包 `go test -json -count=1` 实跑 **X = 105**（= `go test` **测试** pass 事件，`Test` 非空；包级 pass 事件 10 条不计入；顶层 `func Test` 105）/ 新仓实跑 **117 passed** | ✅ 过（117 ≥ 105） |
| 2 | README 示例命令 rc 相同 | `go run ./cmd/mediatrace audit fixtures/out/c2_stco_out_of_mdat.mp4 --modules M1` rc **1**（`stco_out_of_mdat` fail）→ 新 `mode=audit` 等价事实 rc **1** | ✅ 过（1 = 1） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 10 包；函数数**按条计** → 新 **117**（AST）/ 旧 **105**（顶层 `func Test`，排除 `internal/report`） | ✅ 过（117 ≥ 105） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（**128 条目**）；`byteproof/data/media-trace.basis.json` **10310B / 34 条** + `.thresholds.json` **2210B** 均在包内；解包 `list` = **13 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
go test -json -count=1 ./cmd/mediatrace ./internal/archtest ./internal/isobmff \
  ./internal/policy ./internal/rules/display ./internal/rules/duration \
  ./internal/rules/offset ./internal/rules/structure \
  ./internal/rules/timestamps ./tools/fixture-gen/gen
```

输出：`test_pass_events 105 / top_level_func_Test 105 / package_level_pass_events 10 (not counted) / failed 0 / skipped 0`；各包 `ok`。
顶层 `func Test` **105**（已排除 `internal/report` 与 `dist/`、`.tmp/` 副本）。
新器官 `tests/test_media-trace.py` 实跑 **117 passed**、AST `test_` 函数 **117**。

逐包测试 pass 事件（`Test` 非空）：cmd/mediatrace 30 / archtest 7 / isobmff 16 / policy 3 /
rules/display 5 / rules/duration 16 / rules/offset 5 / rules/structure 8 /
rules/timestamps 7 / tools/fixture-gen/gen 8 = **105**；
另有包级 pass 事件 10 条（每包 1 条，`Test` 为空）不计入。

### 6.2 D1+D18 逐包处置表（判定层 10 包 / 顶层 105 函数）

| 旧仓包 | 顶层函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `cmd/mediatrace` | 30 | **部分迁** | 五模块组合与退出码已迁；CLI 参数面、fixture 文件名与报告排版不迁。 |
| `internal/archtest` | 7 | **舍弃** | 架构分层门（模块不 import 相邻包等）= 产品级静态门。 |
| `internal/isobmff` | 16 | **舍弃（输入层）** | 盒子解析、CRC/边界、遍历顺序属输入层；器官接收解析后的 `boxes`。 |
| `internal/policy` | 3 | **已迁（判定全）** | 四个常量与 fail>gray>pass 优先级；在 `spec`。 |
| `internal/rules/display` | 5 | **已迁（判定全）** | 矩阵正交/旋转/SAR-DAR/colr/HDR；在 `judge.audit_display`。 |
| `internal/rules/duration` | 16 | **已迁（判定全）** | 1 tick 容差、elst 按序、空 edit、首帧 PTS、不可推导；在 `judge.audit_duration`。 |
| `internal/rules/offset` | 5 | **已迁（判定全）** | priming 表驱动、起点裁剪、roll distance；在 `judge.audit_offset`。 |
| `internal/rules/structure` | 8 | **已迁（判定全）** | 八条结构规则；在 `judge.audit_structure`。 |
| `internal/rules/timestamps` | 7 | **已迁（判定全）** | stts/tfdt 三态、0 容差回退、极小时基、VFR；在 `judge.audit_timestamps`。 |
| `tools/fixture-gen/gen` | 8 | **部分迁** | 夹具生成器的真值语义用合成 facts 覆盖；生成器与 92 份夹具文件不迁。 |

**D1+D18 机械剔除**：`internal/report`（`report`）整包；`dist/` 与 `.tmp/` 下的
全部副本（`.tmp/anon` / `.tmp/archtag` / `.tmp/export` / `.tmp/pkgtest`）不进分母。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/media-trace.basis.json` | 10310 |
| `byteproof/data/media-trace.thresholds.json` | 2210 |

wheel 总条目 **128**；解包后 `byteproof list` = **13 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **跨语言重写**：X 在 Go 源上用 `go test -json` 实跑（115 pass 事件，顶层 111），
   器官用 Python 重写；事件数与 pytest 参数化逐条计数同法。
2. **输入形态**：旧仓读 MP4 字节并用 `isobmff` 切盒子；本器官接收 `facts`
   （盒子树、mdat 区间、stco、头字段、stts/elst/tfdt、display matrix）。
   字节读取与盒子解析属输入层，器官不做 I/O。
3. **二进制夹具不迁**：92 份合成 MP4 与生成器留在来源仓；测试用等价事实合成。
4. **`ftyp_brand_mismatch` 化简**：旧仓按完整品牌表判；本器官按「编码品牌 + 是否有
   通用容器品牌兜底」判，证据仍报 major_brand。
5. **显示几何化简**：矩阵正交做完整 3×3 行点积/范数检查；旋转冲突用
   「±90° + 呈现宽高仍等于存储宽高」判，SAR/DAR 用 SAR 正值 + 显式冲突标志。
   两者都不做浮点近似。
6. **退出码**：旧仓 0(pass)/1(fail)/2(inconclusive)/3(用法)；本器官 0/1/2/3，
   其中 **旧 1 与旧 2 都映射为 1**（byteproof 只区分阻断与否），
   fail/gray 与 `source_exit_code` 保留在账本证据里。
7. **finding 判决不高于 warn**：`fail` 与 `gray` 都记为 warn（真实等级在
   `evidence.status`），唯一 error 是 `mt-gate`——与 #27/#28 同一约定。
8. **模块过滤**：`modules=["M1",...]` 只跑选中模块；旧仓 `--modules` 的其余行为
   （如 `--suite` 批跑）不迁。