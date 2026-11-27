"""器官 ``chart-integrity``：图表工件 -> 缺陷账本。

迁自 target-map ② 行（旧仓 ``chartaudit``）。搬过来的是**判定**：

1. 九条反误导规则（柱基线/双轴/饼扇区/3D/半径/平滑/时间轴/对比度/规格合法性登记）；
2. 逐值溯源校验（每个渲染值恰一条记录、白名单变换、ID 复算、raw_cell 与重算一致）；
3. G2 样本量门禁（n_min + 偏度 g1 + 固定 bins 多峰 + 合规替代）；
4. G3 误差棒来源真实性（sd / sem / ci / n 的列名别名、来源、数值一致性、未声明可疑列）。

**没有搬**：CSV 解析、normalized spec 的合法性校验、HTML 渲染与几何包、发布门、
bench、冻结数据生成、报告排版。逐条见 ``docs/chart-integrity.md`` §6。
"""

from __future__ import annotations

from byteproof.core.ledger import Record

from . import gates, provenance, rules
from .spec import (
    ROW_INDEX_OFFSET,
    resolve_params,
    verdict_for,
)


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


def _validate_dataset(dataset):
    if not isinstance(dataset, dict):
        raise ValueError("dataset 必须是对象")
    header = dataset.get("header")
    rows = dataset.get("rows")
    columns = dataset.get("columns")
    source = dataset.get("source")
    if not isinstance(header, list) or not header:
        raise ValueError("dataset.header 必须是非空列表")
    if not isinstance(rows, list):
        raise ValueError("dataset.rows 必须是列表")
    if not isinstance(columns, list):
        raise ValueError("dataset.columns 必须是列表")
    if len(columns) != len(header):
        raise ValueError("dataset.columns 与 header 长度不一致")
    for column in columns:
        if not isinstance(column, dict) or "name" not in column or "type" not in column:
            raise ValueError("dataset.columns 每项必须含 name/type")
    if dataset.get("row_count", len(rows)) != len(rows):
        raise ValueError("dataset.row_count 与 rows 长度不一致")
    if not isinstance(source, dict) or not source.get("sha256"):
        raise ValueError("dataset.source.sha256 缺失")
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(header):
            raise ValueError("dataset.rows[%d] 与 header 列数不一致" % index)


def _validate_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("spec 必须是对象")
    for key in ("spec_id", "mark", "title", "encoding"):
        if key not in spec:
            raise ValueError("spec 缺少字段 %s" % key)
    encoding = spec["encoding"]
    if not isinstance(encoding, dict) or "x" not in encoding or "y" not in encoding:
        raise ValueError("spec.encoding 必须含 x / y")
    if not isinstance(encoding["x"], dict) or "field" not in encoding["x"]:
        raise ValueError("spec.encoding.x.field 缺失")
    if not isinstance(encoding["y"], dict) or "field" not in encoding["y"]:
        raise ValueError("spec.encoding.y.field 缺失")


def _validate_provenance(provenance_obj):
    if not isinstance(provenance_obj, dict):
        raise ValueError("provenance 必须是对象")
    source = provenance_obj.get("source")
    if not isinstance(source, dict):
        raise ValueError("provenance.source 必须是对象")


def evaluate(subject, basis):
    settings = resolve_params(subject.get("params"))
    dataset = subject.get("dataset")
    spec = subject.get("spec")
    prov = subject.get("provenance")
    _validate_dataset(dataset)
    _validate_spec(spec)
    _validate_provenance(prov)

    records = []

    for finding in rules.audit(dataset, spec, prov, settings):
        _add(records, basis, finding["rule_id"], finding["message"], finding["path"], finding["evidence"])

    issues, _checked = provenance.validate(prov, dataset, spec)
    for issue in issues:
        _add(records, basis, issue["rule_id"], issue["message"], issue["path"], issue["evidence"])

    _groups, g2_findings = gates.audit_g2(dataset, spec, settings)
    for finding in g2_findings:
        _add(records, basis, finding["rule_id"], finding["message"], finding["path"], finding["evidence"])

    _declarations, g3_findings, _title, _suspicious = gates.audit_g3(dataset, spec, settings)
    for finding in g3_findings:
        _add(records, basis, finding["rule_id"], finding["message"], finding["path"], finding["evidence"])

    return records