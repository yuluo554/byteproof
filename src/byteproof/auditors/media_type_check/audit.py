"""器官主体：已解析的 MIME 工件 -> 缺陷账本。

工件形态（与另两个器官同一条原则：**解析层是工具面，工件是解析后的形态**）::

    {
      "parts": [
        {"path": "0", "content_type": "multipart/mixed", "boundary": "b1",
         "headers": [{"name": "Content-Type", "value": "multipart/mixed; boundary=b1"}],
         "body": ""}
      ],
      "params": {"max_depth": 32}
    }

账本等级 = 规则严重度的翻译（``blocker``/``major`` -> ``error``，``minor`` -> ``warn``，
``note`` -> ``info``），映射表在 :mod:`byteproof.auditors.media_type_check.spec` 的
``VERDICT_BY_SEVERITY``，**只有那一个翻译点**。

位置：``<part path>#<该部件内这条规则的第几次命中>``。同一条规则在一个部件上命中多次
（例如两行都超过 998 octets）时，不追加序号会让两条结论抢同一个账本 id ——
内核的 ``Report`` 会因此直接判契约违约（那是它该做的事，器官不该让它发生）。

本模块不打印、不读文件/环境、不看时钟、不带参数解析器。
"""

from __future__ import annotations

from typing import Iterable, List, Mapping

from byteproof.core.basis import Basis
from byteproof.core.ledger import Record

from . import detectors, spec


def evaluate(subject: Mapping, basis: Basis) -> Iterable[Record]:
    """审一次 MIME 工件。"""
    if not isinstance(subject, Mapping):
        raise ValueError("输入必须是 JSON 对象")
    params = spec.resolve_params(subject.get("params"))
    parts = _parse_parts(subject)
    dumped = spec.dump_params(params)

    records: List[Record] = []
    for part in parts:
        findings = detectors.audit_part(part, params)
        seen = {}
        for finding in findings:
            seen[finding.rule_id] = seen.get(finding.rule_id, 0) + 1
            label = "%s#%d" % (part["path"], seen[finding.rule_id])
            records.append(
                _record(finding, label, part, basis, dumped)
            )
    return tuple(records)


def _record(finding, label, part, basis, dumped):
    rule_id = finding.rule_id
    evidence = dict(finding.evidence)
    evidence["rule_id"] = rule_id
    evidence["severity"] = spec.severity_for(rule_id)
    evidence["part_path"] = part["path"]
    evidence["content_type"] = part["content_type"]
    evidence["params"] = dumped
    return Record(
        rule_id=rule_id,
        verdict=spec.verdict_for(rule_id),
        message=finding.detail,
        basis=basis.ref(rule_id),
        path=label,
        evidence=evidence,
    )


def _parse_parts(subject):
    """``parts`` 必须是对象数组；每个部件的结构在这里一次校验完。"""
    raw = subject.get("parts")
    if not isinstance(raw, list):
        raise ValueError("parts 必须是数组")
    if not raw:
        raise ValueError("parts 为空：没有可审的部件")
    parts = []
    seen_paths = set()
    for index, item in enumerate(raw):
        position = index + 1
        if not isinstance(item, Mapping):
            raise ValueError("parts[%d] 必须是对象" % (position,))
        path = item.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("parts[%d].path 必须是非空字符串" % (position,))
        path = path.strip()
        if path in seen_paths:
            raise ValueError("parts 里路径重复：%r（位置不唯一）" % (path,))
        seen_paths.add(path)
        content_type = item.get("content_type")
        if not isinstance(content_type, str) or not content_type.strip():
            raise ValueError("parts[%d].content_type 必须是非空字符串" % (position,))
        boundary = item.get("boundary")
        if boundary is not None and not isinstance(boundary, str):
            raise ValueError("parts[%d].boundary 必须是字符串或 null" % (position,))
        headers = item.get("headers", [])
        if not isinstance(headers, list):
            raise ValueError("parts[%d].headers 必须是数组" % (position,))
        cleaned_headers = []
        for header_index, header in enumerate(headers):
            if not isinstance(header, Mapping):
                raise ValueError(
                    "parts[%d].headers[%d] 必须是对象" % (position, header_index + 1)
                )
            name = header.get("name")
            value = header.get("value")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    "parts[%d].headers[%d].name 必须是非空字符串" % (position, header_index + 1)
                )
            if not isinstance(value, str):
                raise ValueError(
                    "parts[%d].headers[%d].value 必须是字符串" % (position, header_index + 1)
                )
            cleaned_headers.append({"name": name.strip(), "value": value})
        if "body" not in item:
            raise ValueError("parts[%d] 缺必填字段 body（无正文请显式写空串）" % (position,))
        body = item["body"]
        if body is None:
            body = ""
        if not isinstance(body, (str, bytes, list)):
            raise ValueError("parts[%d].body 必须是字符串 / 字节数组" % (position,))
        parts.append(
            {
                "path": path,
                "content_type": content_type.strip(),
                "content_type_header": item.get("content_type_header"),
                "boundary": boundary,
                "headers": cleaned_headers,
                "body": body,
            }
        )
    return parts