# 器官 `image-oracle`

> 来源：迁自 target-map ② 行（旧仓 `10-27-imageoracle`，包 `imageoracle`）。
> 迁入版本：`1`。契约（账本字段 / 退出码 / 目录形状）见 [`byteproof.md`](byteproof.md)。
> 本页只写这个器官自己的那一列：它吃什么、按什么判、吐出来长什么样。

一句话：**在打开一张图之前，预言它在浏览器/预览器/工具里会显示成什么样**，
落一张可复核的缺陷账本。输入是输入层解析好的**事实**（`subject.facts`）：方向、
IFD、XMP 文本、ICC 头字段、chunk 名与 CRC、帧时长。器官不解码像素、不读字节、不读时钟。

## 1. 输入（工件）

`mode` 与 `facts` 必填；其余字段按模式校验，缺字段/类型错 -> 退出码 2。

| 模式 | 判什么 |
|---|---|
| `orientation` | 8 元方向矩阵、274 类型/范围、XMP 两式、有效宽高 |
| `double-rotate` | IFD1 未同步 / XMP 冲突 / 大边启发式三条件 + 消费者触发链 |
| `color` | ICC 载体与 128B 头、PNG iCCP↔sRGB、色彩 chunk、位深、CMYK、默认假设表 |
| `container` | PNG chunk 顺序/CRC、APNG 序号、帧时长单位、WebP/GIF/JPEG 结构 |
| `consumers` | 9×6 消费者矩阵、风险清单、加工前后 chunk diff |

| `facts` 键 | 形态 | 说明 |
|---|---|---|
| `kind` | `jpeg` / `png` / `webp` / `gif` / `tiff` / `avif` | 容器类型 |
| `width` / `height` | 整数 | **存储**宽高（不按方向交换） |
| `exif[]` | `{ifd, type, value, offset}` | `type` 必须是 3/int16u；`value` 可为 `null` |
| `xmp` | 字符串或 `null` | 两种 `tiff:Orientation` 写法都认 |
| `icc` | `{present, carrier, declared_segments, segments_seen, compressed, header}` | `header` 可为 `null` |
| `png.chunks` | `str[]`（出现顺序） | chunk 名；`png.crc_ok` / `png.fctl_sequences` 可选 |
| `frames[]` | `{index, duration_ms, raw_unit}` | 归一化毫秒 + 原始单位 |
| `jpeg_markers` / `gif_blocks` | `str[]` | 段/块事实 |
| `matrix` | 可选，9 行对象数组 | 覆盖内置消费者矩阵（用于逐格校验） |

## 2. 判定顺序与等级

| 模块 | 规则 | 代码 | 等级 |
|---|---|---|---|
| orientation | `io-orientation-type` | `orientation_not_int16u` | error |
| orientation | `io-orientation-range` | `orientation_out_of_range` | error |
| orientation | `io-orientation-absent` | `orientation_absent` | info |
| orientation | `io-orientation-xmp` | `orientation_xmp_present` | info |
| double | `io-double-ifd1` | `double_rotate_ifd1_unsynced` | warning / certain |
| double | `io-double-xmp` | `double_rotate_xmp_conflict` | warning / certain |
| double | `io-double-bigedge` | `double_rotate_bigedge_mismatch` | suspicion / gray |
| color | `io-color-icc` | `icc_missing` / `icc_present` | info |
| color | `io-color-icc-gap` | `icc_segment_gap` | error |
| color | `io-color-icc-header` | `icc_header_truncated` / `icc_bad_signature` / `icc_size_mismatch` / `icc_bad_intent` | error / warning |
| color | `io-color-icc-class` | `icc_class_legal` / `icc_unknown_class` | info / warning |
| color | `io-color-icc-space` | `icc_unknown_space` | warning |
| color | `io-color-icc-unknown` | `compressed_profile_not_inspected` | unknown |
| color | `io-color-iccp-srgb` | `iccp_srgb_conflict` | warning |
| color | `io-color-cmyk` | `cmyk_jpeg` | warning |
| color | `io-color-defaults` | `color_default_assumption` × 7 | info |
| container | `io-container-png-order` | `png_chunk_order` | error |
| container | `io-container-png-crc` | `png_crc_missing` | error |
| container | `io-container-apng` | `apng_sequence` | error |
| container | `io-container-frame` | `frame_unit` / `frame_duration_unknown` | warning / unknown |
| container | `io-container-webp` / `-gif` / `-jpeg` | 结构缺失/段事实 | warning / info |
| consumers | `io-consumers-matrix` | 9×6 矩阵合法性 | error / info |
| consumers | `io-consumers-risk` | 风险行 | high=error / medium=warning / unknown=unknown |
| consumers | `io-consumers-diff` | 每条加工命令的 chunk diff | info |
| 摘要 | `io-summary` | — | info |
| 门禁 | `io-gate` | — | **error** |

**等级与阻断分离**：finding 带旧仓 `severity`（info/warning/error/unknown）证据，
判决不高于 warn；唯一 `error` 是 `io-gate`。`suspicion` 不进门禁（旧仓也不含它）。
旧仓 0/1/2 → 本产品 0/1/1：旧 1（warning）与旧 2（error/unknown）都映射为 1，
细化等级保留在 `evidence.severity` 与 `io-gate.source_exit_code`。

## 3. 输出

```console
$ byteproof check image-oracle --input samples/image-oracle.minimal.json
byteproof :: image-oracle 1 :: image-oracle.minimal.json
[info] io-summary — 合计 0 条 finding（warning=0 error=0 unknown=0） :: summary (io-summary@1)
合计 1 条，阻断 0 条（error=0 warn=0 info=1）
```

样例是正常照片（EXIF IFD0=1、4000×3000）：无 findings，verdict 干净，rc **0**。

一张 IFD0=6、IFD1=1、XMP=3 的图（`mode=double-rotate`）会得到三条条件命中 +
消费者触发链；`mode=orientation` 遇 274=9 时：

```console
[warn] io-orientation-range — orientation_out_of_range（error/certain）：ifd0 = 9，超出 1..8 :: findings[0] (io-orientation-range@1)
[error] io-gate — 最严重级别 error 触发阻断（旧仓退出码 2 映射为 1） :: gate (io-gate@1)
```

`--json` 的单条 finding：

```json
{
  "id": "io-orientation-range@findings[0]",
  "rule_id": "io-orientation-range",
  "verdict": "warn",
  "message": "orientation_out_of_range（error/certain）：ifd0 = 9，超出 1..8",
  "path": "findings[0]",
  "evidence": {
    "code": "orientation_out_of_range",
    "severity": "error",
    "confidence": "certain",
    "module": "orientation",
    "evidence": {"ifd": "ifd0", "value": 9, "offset": 128}
  }
}
```

## 4. 参数（`params`）

本器官没有 `params` 段：五个模式各自读 `facts`，阈值/表体是冻结常量（§5）。
`matrix` 可由 subject 覆盖，但格子值域仍按 §2 校验。

## 5. 依据包

`src/byteproof/data/image-oracle.basis.json`（**31 条规则**，版本 `1`）。
出处照搬旧仓 `data/README.md` §8 与条款库：EXIF tag 274 / TIFF 字节序 / sharp /
jpegtran / ImageMagick 文档 / ICC 头偏移 / PNG-3 Table 7 / 消费者矩阵快照。

`image-oracle.thresholds.json` 是台账：方向 8 元组、消费者 9×6、值域词表、7 行默认
假设、6 条加工命令、帧单位表、31 条规则的名义等级。运行期常量在 `spec.py`，
测试逐项断言两边相等。

## 6. §7.3 四项无损判据 · 实测

| # | 判据 | 实测 | 结论 |
|---|---|---|---|
| 1 | 新仓该器官实跑用例数 ≥ X | 旧仓 11 个判定层文件实跑 **X = 200 passed** / 新仓实跑 **225 passed** | ✅ 过（225 ≥ 200） |
| 2 | README 示例命令 rc 相同 | `imageoracle orientation --json fixtures/out/m2_orient1_portrait.jpg` rc **0**（EXIF IFD0=1，无 findings）→ 新 `mode=orientation` 等价事实 rc **0** | ✅ 过（0 = 0） |
| 3 | 测试文件数 / 测试函数数 | 口径乙：文件数**按域计** → 新 **1 文件** / 旧 11 文件；函数数**按条计** → 新 **206**（AST）/ 旧 **200** | ✅ 过（225 ≥ 200；206 ≥ 200） |
| 4 | `pip wheel` 后 `data/` 进包 | `%TEMP%` 暂存树构建 `byteproof-0.1.0-py3-none-any.whl`（**122 条目**）；`byteproof/data/image-oracle.basis.json` **9783B / 31 条** + `.thresholds.json` **2663B** 均在包内；解包 `list` = **12 器官**、样例 `check` rc **0** | ✅ 过 |

### 6.1 判据 1 的实跑命令与输出原文（来源仓只读）

```
cd <来源仓>
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 py -3.12 -m unittest \
  tests.test_ci_workflow tests.test_fixtures tests.test_layering \
  tests.test_m1_manifest tests.test_m2_orientation tests.test_m3_double_rotate \
  tests.test_m4_color tests.test_m4_defaults tests.test_m5_container \
  tests.test_m6_consumers tests.test_specs
```

输出：`Ran 200 tests ... OK`。来源仓 `git status --porcelain` = **0 行**，
HEAD `3160c8b` 与队列一致。

逐文件：ci_workflow 8 / fixtures 7 / layering 7 / m1_manifest 11 /
m2_orientation 21 / m3_double_rotate 20 / m4_color 32 / m4_defaults 10 /
m5_container 32 / m6_consumers 42 / specs 10 = **200**；AST `test*` 方法同为 **200**。
新器官 `tests/test_image-oracle.py` 实跑 **225 passed**、AST `test_` 函数 **206**。

### 6.2 D1 + D18 逐文件处置表（判定层 11 文件 / 200 函数）

| 旧仓测试文件 | 函数 | 处置 | 由哪条产品门接管 / 舍弃理由 |
|---|---:|---|---|
| `test_ci_workflow.py` | 8 | **舍弃** | CI workflow 结构门 = 产品级。 |
| `test_fixtures.py` | 7 | **部分迁** | fixture 生成器与 manifest 属数据面；其判定语义（方向/双旋/色彩/容器）用合成 facts 逐条覆盖。 |
| `test_layering.py` | 7 | **部分迁** | 分层「判决层不读字节 / 不 zlib 解压 / 不解码像素」由本仓静态 AST 门继承；读者层字节实现不迁。 |
| `test_m1_manifest.py` | 11 | **舍弃** | 冻结产物与 manifest 的生成/校验属数据面。 |
| `test_m2_orientation.py` | 21 | **已迁（判定全）** | 8 元矩阵、类型/范围、XMP 两式、有效宽高；在 `judge.analyze_orientation`。 |
| `test_m3_double_rotate.py` | 20 | **已迁（判定全）** | 三条件、certain/gray 分列、触发链；在 `judge.analyze_double_rotate`。 |
| `test_m4_color.py` | 32 | **已迁（判定全）** | ICC 载体/头/分片、iCCP↔sRGB、CMYK、位深；PNG iCCP 不解压的硬约束保留。 |
| `test_m4_defaults.py` | 10 | **已迁（判定全）** | 7 行默认假设与出处；在 `spec.DEFAULT_ASSUMPTIONS` + `judge.analyze_color`。 |
| `test_m5_container.py` | 32 | **已迁（判定全）** | PNG 顺序/CRC、APNG 序号、帧单位、WebP/GIF/JPEG 结构；字节切块属输入层。 |
| `test_m6_consumers.py` | 42 | **已迁（判定全）** | 9×6 矩阵词表/置信度、风险词表、加工 diff；在 `judge.analyze_consumers`。 |
| `test_specs.py` | 10 | **部分迁** | 条款 ID 与原文出处进入 basis；条款库文件本身不随器官分发。 |

**D1+D18 机械剔除的 2 个文件**：`test_cli_contract.py`（cli）、
`test_reported_counts.py`（report）。分别测 CLI 参数面与计数展示。
`_helpers.py` / `__init__.py` 不是 `test_*.py`，不计入分母。

### 6.3 判据 4 的进包清单

| 文件 | 字节 |
|---|---:|
| `byteproof/data/image-oracle.basis.json` | 9783 |
| `byteproof/data/image-oracle.thresholds.json` | 2663 |

wheel 总条目 **122**；解包后 `byteproof list` = **12 器官**、样例 `check` rc **0**。
构建树来自暂存区 tree 对象（`git write-tree` + `git archive`），**不是脏工作树**。

## 7. 与旧仓口径差（如实登记）

1. **输入形态**：旧仓读文件字节、由 readers 切 chunk/EXIF/ICC；本器官只接收
   `facts`。字节读取、EXIF IFD 解析、ICC 分片拼接、PNG CRC 计算都在输入层。
2. **不解码像素是硬约束**：旧仓如此，本器官把这条写成结构（没有 PIL/numpy/zlib 解压），
   测试静态断言。
3. **PNG iCCP 不解压**：压缩 profile 一律 `unknown / compressed_profile_not_inspected`，
   不为「让坏样本报 error」而解压。
4. **消费者矩阵**是 2026-10-27 快照；值域/置信度按词表校验，但格子内容不重算。
   `matrix` 可由 subject 覆盖，校验规则不变。
5. **加工 diff**：只做「命令 → 会丢哪些 chunk」的集合差，不运行任何工具、不写文件；
   命令表是数据，新增命令需同时进 `PROCESSING_DROPS` 与 thresholds。
6. **退出码**：旧仓 0/1/2/3；本器官 0（info/suspicion）/1（warning、error、unknown）/
   2（输入不合法）/3（契约违约）。**旧 1 与旧 2 都映射为 1**（byteproof 只区分阻断与否），
   原始细分保留在 `evidence.severity` 与 `io-gate.source_exit_code`。
7. **`suspicion` 不阻断**：与旧仓 §8.5 一致；它也不参与 verdict（verdict 只由
   warning/error/unknown 派生）。
8. **条款库不随包**：旧仓 `specs/__init__.py` 的条款原文是代码常量；本器官把它们
   搬进 basis 的 `source`（规则登记），运行期只通过 `basis.ref` 取出处。
9. **fixture 不入包**：54 份样本与大 fixture 留在输入层；判据 4 只要求规则包进 wheel。