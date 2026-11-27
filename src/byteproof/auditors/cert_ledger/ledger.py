"""台账（inventory）：把**已解码的条目事实**归并成去重、配对、排序后的台账。

旧仓在 ``inventory`` 里用 ``cryptography`` 读 PEM/DER/PKCS#12 并计算指纹；本器官
只接收输入层给出的条目事实（``entries[]``），判定归并规则：

* 证书按 ``fingerprint_sha256`` 去重，``sources[]`` 追加并按 ``(kind, path, alias)`` 排序；
* 私钥按 ``spki_sha256`` 去重；打不开的加密私钥每条文件一条记录（``spki=None``，
  不用哨兵值合并——那会凭空造出一个身份）；
* 证书与私钥按 SPKI 配对，同 SPKI 多证书时取**最小指纹**（两次运行同序）；
* 容器本身始终入账：打不开是「这台机器上有个盒子没看」≠「盒子里没有东西」。

不读文件、不算指纹、不解析 X.509——那些属于输入层。
"""

from __future__ import annotations

from . import spec


def _source(raw, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("entries[%d].source 必须是对象" % index)
    kind = raw.get("kind", "file")
    if kind not in spec.SOURCE_KINDS:
        raise ValueError("entries[%d].source.kind 非法：%r" % (index, kind))
    path = raw.get("path", "")
    if not isinstance(path, str) or not path:
        raise ValueError("entries[%d].source.path 必须是非空字符串" % index)
    return {
        "kind": kind,
        "path": path,
        "container_format": raw.get("container_format"),
        "alias": raw.get("alias"),
        "entry_type": raw.get("entry_type"),
        "store_name": raw.get("store_name"),
        "posix_mode": raw.get("posix_mode"),
    }


def _sort_key(source: dict):
    return (
        spec.SOURCE_KIND_ORDER.get(source["kind"], 99),
        source["path"],
        source.get("alias") or "",
    )


def _merge_sources(existing: list, source: dict) -> list:
    return sorted(existing + [source], key=_sort_key)


def _text(value) -> str:
    return "" if value is None else str(value)


def _str_tuple(value) -> tuple:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("证书字段必须是字符串数组")
    return tuple(str(item) for item in value)


def _cert_record(entry: dict, source: dict) -> dict:
    fingerprint = entry.get("fingerprint_sha256")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("kind=cert 的条目必须有 fingerprint_sha256")
    subject = entry.get("subject")
    if isinstance(subject, dict):
        display = _text(subject.get("display"))
        der = _text(subject.get("der_sha256"))
    else:
        display = _text(subject)
        der = _text(entry.get("subject_der_sha256"))
    issuer = entry.get("issuer")
    if isinstance(issuer, dict):
        issuer_display = _text(issuer.get("display"))
        issuer_der = _text(issuer.get("der_sha256"))
    else:
        issuer_display = _text(issuer)
        issuer_der = _text(entry.get("issuer_der_sha256"))
    san = entry.get("san") if isinstance(entry.get("san"), dict) else {}
    bits = entry.get("key_bits")
    if bits is not None and (isinstance(bits, bool) or not isinstance(bits, int)):
        raise ValueError("key_bits 必须是整数或 null")
    return {
        "fingerprint_sha256": fingerprint,
        "spki_sha256": _text(entry.get("spki_sha256")),
        "subject": {"display": display, "der_sha256": der},
        "issuer": {"display": issuer_display, "der_sha256": issuer_der},
        "san": {
            "dns": list(_str_tuple(san.get("dns"))),
            "ip": list(_str_tuple(san.get("ip"))),
            "email": list(_str_tuple(san.get("email"))),
            "uri": list(_str_tuple(san.get("uri"))),
        },
        "not_before": _text(entry.get("not_before")),
        "not_after": _text(entry.get("not_after")),
        "key_algo": _text(entry.get("key_algo")),
        "key_bits": bits,
        "curve": entry.get("curve"),
        "sig_algo": _text(entry.get("sig_algo")),
        "key_usage": list(_str_tuple(entry.get("key_usage"))),
        "extended_key_usage": list(_str_tuple(entry.get("extended_key_usage"))),
        "is_ca": bool(entry.get("is_ca", False)),
        "subject_key_id": entry.get("subject_key_id"),
        "sources": [source],
    }


def _key_record(entry: dict, source: dict, encrypted: bool, spki) -> dict:
    return {
        "spki_sha256": spki,
        "key_algo": _text(entry.get("key_algo")),
        "key_bits": entry.get("key_bits"),
        "curve": entry.get("curve"),
        "encrypted": bool(encrypted),
        "paired_cert_fingerprint": None,
        "sources": [source],
    }


def _container_record(entry: dict, index: int) -> dict:
    path = entry.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("entries[%d] 容器条目必须有 path" % index)
    entries = entry.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("entries[%d].entries 必须是数组" % index)
    items = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("entries[%d].entries 的每一项必须是对象" % index)
        items.append(
            {
                "alias": item.get("alias"),
                "entry_type": _text(item.get("entry_type")),
                "fingerprint_sha256": item.get("fingerprint_sha256"),
                "spki_sha256": item.get("spki_sha256"),
            }
        )
    return {
        "path": path,
        "format": _text(entry.get("format")),
        "has_private_key": bool(entry.get("has_private_key", False)),
        "password": entry.get("password"),
        "unreadable": entry.get("unreadable"),
        "entries": items,
    }


def build_ledger(entries) -> dict:
    """归并条目事实，返回旧仓台账形状 ``{certs, keys, containers, diagnostics, summary}``。"""
    if not isinstance(entries, list):
        raise ValueError("subject.entries 必须是数组")

    certs: dict = {}
    keys: dict = {}
    locked: dict = {}
    containers: list = []
    diagnostics: list = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError("entries[%d] 必须是对象" % index)
        kind = entry.get("kind")
        if kind == "cert":
            source = _source(entry.get("source"), index)
            record = _cert_record(entry, source)
            fingerprint = record["fingerprint_sha256"]
            existing = certs.get(fingerprint)
            if existing is not None:
                existing["sources"] = _merge_sources(existing["sources"], source)
            else:
                certs[fingerprint] = record
        elif kind == "key":
            source = _source(entry.get("source"), index)
            spki = entry.get("spki_sha256")
            if not isinstance(spki, str) or not spki:
                raise ValueError("kind=key 的条目必须有 spki_sha256")
            existing = keys.get(spki)
            if existing is not None:
                existing["sources"] = _merge_sources(existing["sources"], source)
            else:
                keys[spki] = _key_record(entry, source, entry.get("encrypted", False), spki)
        elif kind == "locked_key":
            source = _source(entry.get("source"), index)
            identity = "\x00locked:%s:%s" % (source["kind"], source["path"])
            existing = locked.get(identity)
            if existing is not None:
                existing["sources"] = _merge_sources(existing["sources"], source)
            else:
                locked[identity] = _key_record(entry, source, True, None)
        elif kind == "container":
            record = _container_record(entry, index)
            containers.append(record)
            for item in entry.get("entries", []):
                alias = item.get("alias")
                if item.get("entry_type") == "privateKey" and item.get("spki_sha256"):
                    spki = item["spki_sha256"]
                    source = {
                        "kind": "container",
                        "path": record["path"],
                        "container_format": record["format"],
                        "alias": alias,
                        "entry_type": "privateKey",
                        "store_name": None,
                        "posix_mode": None,
                    }
                    existing = keys.get(spki)
                    if existing is not None:
                        existing["sources"] = _merge_sources(existing["sources"], source)
                    else:
                        keys[spki] = {
                            "spki_sha256": spki,
                            "key_algo": "",
                            "key_bits": None,
                            "curve": None,
                            "encrypted": True,
                            "paired_cert_fingerprint": None,
                            "sources": [source],
                        }
        elif kind == "diagnostic":
            diagnostics.append(
                {
                    "code": _text(entry.get("code")),
                    "path": _text(entry.get("path")),
                    "stage": _text(entry.get("stage")),
                    "detail": _text(entry.get("detail")),
                }
            )
        elif kind is None:
            raise ValueError("entries[%d] 缺少 kind" % index)
        else:
            diagnostics.append(
                {
                    "code": "PARSE_UNSUPPORTED",
                    "path": _text(entry.get("path")),
                    "stage": "container",
                    "detail": "%s 未展开（当前版本不读该容器）" % (kind,),
                }
            )

    paired = _pair_certs(keys, certs)
    for spki, record in keys.items():
        if spki in paired:
            record["paired_cert_fingerprint"] = paired[spki]
    for record in locked.values():
        record["paired_cert_fingerprint"] = None

    ordered_certs = sorted(certs.values(), key=lambda item: item["fingerprint_sha256"])
    ordered_keys = sorted(
        list(keys.values()) + list(locked.values()),
        key=lambda item: (item["spki_sha256"] is None, item["spki_sha256"] or ""),
    )
    ordered_diagnostics = sorted(
        diagnostics, key=lambda item: (item["code"], item["path"], item["stage"], item["detail"])
    )
    ordered_containers = sorted(containers, key=lambda item: item["path"])

    return {
        "schema_version": 1,
        "kind": spec.LEDGER_KIND,
        "certs": ordered_certs,
        "keys": ordered_keys,
        "containers": ordered_containers,
        "diagnostics": ordered_diagnostics,
        "summary": {
            "certs": len(ordered_certs),
            "keys": len(ordered_keys),
            "containers": len(ordered_containers),
            "diagnostics": len(ordered_diagnostics),
            "paired": len(paired),
        },
    }


def _pair_certs(keys: dict, certs: dict) -> dict:
    by_spki: dict = {}
    for record in certs.values():
        spki = record.get("spki_sha256")
        if not spki:
            continue
        current = by_spki.get(spki)
        if current is None or record["fingerprint_sha256"] < current:
            by_spki[spki] = record["fingerprint_sha256"]
    return {spki: fingerprint for spki, fingerprint in by_spki.items() if spki in keys}


def validate_ledger(ledger) -> dict:
    """校验已给出的台账（缺字段 -> 退出码 2）；只做形状检查，不重算事实。"""
    if not isinstance(ledger, dict):
        raise ValueError("subject.ledger 必须是对象")
    for field in ("certs", "keys"):
        value = ledger.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("ledger.%s 必须是对象数组" % field)
    for field in ("containers", "diagnostics"):
        value = ledger.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("ledger.%s 必须是对象数组" % field)
    return ledger