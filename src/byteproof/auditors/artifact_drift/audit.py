"""器官 ``artifact-drift``：两份已产出工件 -> 缺陷账本。

迁自 target-map ② 行（旧仓 ``bdiff``）。搬过来的是**判定**：
结构对齐（SAME/ADDED/REMOVED/RENAMED）+ T1–T12 归因 + 残留字节 + 最小原因集 +
budget 门禁。归档装载（tar/zip/gzip/whl/jar/OCI）与 ELF/PE/Mach-O 字节解析属工具面，
不作为器官职责；subject 提供已装载条目与事实。

**没有搬**：归档读取、facts 抽取、报告渲染、CLI、发布门、合成样张生成。
"""

from __future__ import annotations

from byteproof.core.ledger import Record

from . import align, attribute
from .spec import (
    METADATA_RULES,
    RULE_CAUSE,
    RULE_DIFF,
    RULE_UNBUDGETED,
    T4,
    T5,
    T12,
    resolve_params,
    verdict_for,
)

MESSAGES = {
    "T1": "归档 mtime 差异（构建时刻痕迹，可归一化）",
    "T2": "属主/属组差异（构建环境身份，可归一化）",
    "T3": "权限位差异（可归一化）",
    "T4": "两侧公共根前缀不同（先于逐条目比对）",
    "T5": "归档内条目顺序不同（条目集合与哈希一致）",
    "T6": "gzip 头（xfl/os）差异（可归一化）",
    "T7": "容器头差异（raw header / zip create_system，可归一化）",
    "T8": "编译器注释/生产者字符串差异（可归一化）",
    "T9": "build-id / 调试节差异（可归一化）",
    "T10": "签名节差异（可归一化）",
    "T11": "编译目录（comp_dir）差异（可归一化）",
    "T12": "归一化后仍有内容字节差异（残留）",
}


def _add(records, basis, rule_id, message, path, evidence):
    records.append(
        Record(
            rule_id=rule_id,
            verdict=verdict_for(rule_id),
            message=message,
            basis=basis.ref(rule_id),
            path=path,
            evidence=evidence,
        )
    )


def evaluate(subject, basis):
    settings = resolve_params(subject.get("params"))
    left = align.normalize_side(subject.get("left"), "left")
    right = align.normalize_side(subject.get("right"), "right")
    rows, counts = align.align(left, right)
    result = attribute.attribute(left, right)

    records = []
    for diff in result["diffs"]:
        rule = diff["rule_id"]
        _add(
            records,
            basis,
            RULE_DIFF[rule],
            MESSAGES[rule],
            diff["path"] or "<tree>",
            {
                "rule_id": rule,
                "key": diff["key"],
                "left": diff["left"],
                "right": diff["right"],
                "bytes_delta": diff["bytes_delta"],
            },
        )

    present = sorted({diff["rule_id"] for diff in result["diffs"] if diff["rule_id"] in METADATA_RULES})
    unbudgeted = [rule for rule in present if rule not in settings.budget]
    if unbudgeted:
        _add(
            records,
            basis,
            RULE_UNBUDGETED,
            "差异类别不在 budget 白名单内：%s" % ", ".join(unbudgeted),
            "<tree>",
            {"present": present, "budget": list(settings.budget), "unbudgeted": unbudgeted},
        )

    _add(
        records,
        basis,
        RULE_CAUSE,
        "最小原因集：%s；残留字节：%d"
        % ("无解" if result["minimal_cause_set"] is None else (result["minimal_cause_set"] or "空集（完全一致）"), result["residue_bytes"]),
        "<tree>",
        {
            "minimal_cause_set": result["minimal_cause_set"],
            "residue_bytes": result["residue_bytes"],
            "counts": result["counts"],
            "alignment": counts,
            "notes": result["notes"],
        },
    )
    return records