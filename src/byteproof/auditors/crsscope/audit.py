"""器官 ``crsscope``：空间参考语义审计账本（迁自 10-27-crsscope）。

回答三个问题：**这批坐标是哪个坐标系**（decl 五项）、**会不会整体偏几百米**
（detect 假设评分 + 三段残差）、**有没有混用**（xdiff 跨实现差分 / geojson 结构 /
tiles 轴序）。判定核逐字移植；文件读取（GeoJSON/GPX/CSV/掩膜 JSON）与报告渲染留输入层。

**账本映射**：conflict/error → error（阻断）；warning（环方向 R1 默认档 / bbox 不一致 /
轴序 / crs 成员 / 精度）→ warn；undecidable（灰区）→ warn（旧 rc5 → 不阻断，语义在
evidence）；info/consistent → info。
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from byteproof.core.ledger import ERROR, INFO, WARN, Record

from . import declcheck, detectcore, geojsoncheck, tilescheck
from .finding import STATUS_CONFLICT, STATUS_ERROR, STATUS_UNDECIDABLE, STATUS_WARNING, outcome_code
from . import spec


def evaluate(subject: Mapping, basis) -> Iterable[Record]:
    """账本入口：subject = {mode, module payload…}。

    ``mode`` ∈ decl / detect / xdiff / geojson / tiles / report（多模块汇总）。
    输入层职责：文件读取 + GeoJSON 解析（**parse_float=Decimal**，精度检查读十进制指数）+
    GPX/CSV 解析 + 掩膜网格装载。
    """
    mode = _mode_of(subject)
    records: List[Record] = []
    if mode == "decl":
        records.extend(_decl_records(subject, basis))
    elif mode == "detect":
        records.extend(_detect_records(subject, basis))
    elif mode == "xdiff":
        records.extend(_xdiff_records(subject, basis))
    elif mode == "geojson":
        records.extend(_geojson_records(subject, basis))
    elif mode == "tiles":
        records.extend(_tiles_records(subject, basis))
    elif mode == "report":
        for section in subject.get("modules") or []:
            if not isinstance(section, dict):
                raise ValueError("report.modules 的每一项必须是对象（{mode: …}）")
            sub_mode = section.get("mode")
            if sub_mode == "decl":
                records.extend(_decl_records(section, basis, prefix="report"))
            elif sub_mode == "detect":
                records.extend(_detect_records(section, basis, prefix="report"))
            elif sub_mode == "xdiff":
                records.extend(_xdiff_records(section, basis, prefix="report"))
            elif sub_mode == "geojson":
                records.extend(_geojson_records(section, basis, prefix="report"))
            elif sub_mode == "tiles":
                records.extend(_tiles_records(section, basis, prefix="report"))
            else:
                raise ValueError("report.modules 每项的 mode 必须是本器官的五个模块之一")
    blocking = sum(1 for record in records if record.verdict == ERROR)
    warns = sum(1 for record in records if record.verdict == WARN)
    records.append(
        Record(
            rule_id=spec.RULE_SUMMARY,
            verdict=INFO,
            message="mode=%s：阻断 %d 条（conflict/error），提示 %d 条（warning/undecidable）"
                    % (mode, blocking, warns),
            basis=basis.ref(spec.RULE_SUMMARY),
            path="summary",
            evidence={"mode": mode, "blocking": blocking, "warn": warns},
        )
    )
    return records


# ------------------------------------------------------------------ 通用
def _emit(records: List[Record], basis, finding: dict, prefix: str, index: int, module: str) -> None:
    mapping = spec.RULE_BY_MODULE.get(module, {})
    rule_id = mapping.get(finding["check"], spec.RULE_CHECK)
    verdict = spec.STATUS_TO_VERDICT.get(finding["status"], INFO)
    records.append(
        Record(
            rule_id=rule_id,
            verdict=verdict,
            message="%s：%s（%s）" % (finding["check"], finding["detail"], finding["status"]),
            basis=basis.ref(rule_id),
            path="%s.findings[%d]" % (prefix, index),
            evidence=dict(finding.get("evidence") or {}, check=finding["check"], status=finding["status"], reason=finding.get("reason")),
        )
    )


def _structure_records(records: List[Record], basis, payload: dict, prefix: str) -> None:
    for index, issue in enumerate(payload.get("structure_issues") or []):
        records.append(
            Record(
                rule_id=spec.RULE_STRUCTURE,
                verdict=ERROR,
                message="structure：%s" % issue["detail"],
                basis=basis.ref(spec.RULE_STRUCTURE),
                path="%s.structure[%d]" % (prefix, index),
                evidence=dict(issue.get("evidence") or {}),
            )
        )


def _samples_of(subject) -> List[declcheck.Sample]:
    raw = subject.get("samples")
    if not isinstance(raw, list):
        raise ValueError("subject.samples 必须是数组（[{a, b}, …]，保持文件分量顺序）")
    samples = []
    for seq, pair in enumerate(raw, 1):
        if not isinstance(pair, dict) or not isinstance(pair.get("a"), (int, float)) or not isinstance(pair.get("b"), (int, float)):
            raise ValueError("samples 每项必须是 {a: 数值, b: 数值}")
        if isinstance(pair["a"], bool) or isinstance(pair["b"], bool):
            raise ValueError("samples 分量必须是数值")
        samples.append(declcheck.Sample(seq=seq, a=float(pair["a"]), b=float(pair["b"])))
    return samples


def _points_of(subject, key="points") -> List[Tuple[float, float]]:
    raw = subject.get(key)
    if not isinstance(raw, list):
        raise ValueError("subject.%s 必须是数组（[[lon, lat], …]）" % key)
    points = []
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("%s 每项必须是 [lon, lat]" % key)
        lon, lat = pair
        if isinstance(lon, bool) or isinstance(lat, bool) or not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise ValueError("%s 分量必须是数值" % key)
        points.append((float(lon), float(lat)))
    return points


def _mask_of(subject) -> "object":
    raw = subject.get("mask")
    if not isinstance(raw, dict):
        raise ValueError("subject.mask 必填（掩膜网格对象；掩膜缺失不得默认全陆地）")
    cells = {}
    for key, value in (raw.get("cells") or {}).items():
        lat_idx, lon_idx = str(key).split(",")
        cells[(int(lat_idx), int(lon_idx))] = str(value)
    return finding_mod.Mask(
        version=str(raw.get("version", "inline")),
        resolution_deg=float(raw["resolution_deg"]),
        lon_min=float(raw["lon_min"]),
        lat_min=float(raw["lat_min"]),
        n_lon=int(raw["n_lon"]),
        n_lat=int(raw["n_lat"]),
        cells=cells,
    )


from . import finding as finding_mod  # noqa: E402  （放底部避免循环）


# ------------------------------------------------------------------ decl
def _decl_records(subject, basis, prefix="decl") -> List[Record]:
    records: List[Record] = []
    payload = declcheck.run_decl(
        _samples_of(subject),
        subject.get("declared_crs"),
        subject.get("file_crs"),
        strict=bool(subject.get("strict")),
    )
    for index, finding in enumerate(payload["findings"]):
        _emit(records, basis, finding, prefix, index, "decl")
    records.append(
        Record(
            rule_id=spec.RULE_VERDICT,
            verdict=INFO,
            message="decl 判定：%s" % payload["verdict"],
            basis=basis.ref(spec.RULE_VERDICT),
            path="%s.verdict" % prefix,
            evidence={key: payload[key] for key in ("declared_crs", "declared_crs_source", "sample_counts", "candidates")},
        )
    )
    return records


# ------------------------------------------------------------------ detect
def _detect_records(subject, basis, prefix="detect") -> List[Record]:
    records: List[Record] = []
    payload = detectcore.run_detect(
        _points_of(subject),
        _mask_of(subject),
        subject.get("declared_crs"),
    )
    if payload["gray_reason"]:
        records.append(
            Record(
                rule_id=spec.RULE_UNDECIDABLE,
                verdict=WARN,
                message="detect 灰区：%s（置信 %s）——不硬判" % (payload["gray_reason"], payload["confidence"]),
                basis=basis.ref(spec.RULE_UNDECIDABLE),
                path="%s.gray" % prefix,
                evidence={"confidence": payload["confidence"], "gray_reason": payload["gray_reason"], "margin": payload["margin"]},
            )
        )
    winner = payload["winner"]
    if winner:
        records.append(
            Record(
                rule_id=spec.RULE_DETECT_WINNER,
                verdict=INFO,
                message="最优假设 %s（score=%s，中位偏移 %.1f m，方向 %s）"
                        % (winner["name"], winner["score"], winner["offset_m"], winner["direction"]),
                basis=basis.ref(spec.RULE_DETECT_WINNER),
                path="%s.winner" % prefix,
                evidence={"winner": winner, "hypotheses": payload["hypotheses"], "mask_note": payload["mask_note"]},
            )
        )
    for index, part in enumerate(payload["residual"]):
        records.append(
            Record(
                rule_id=spec.RULE_RESIDUAL,
                verdict=WARN if part["kind"] == "boundary_jump" and part["affected_points"] else INFO,
                message="残差 %s：影响 %d 个点——%s" % (part["kind"], part["affected_points"], part["detail"]),
                basis=basis.ref(spec.RULE_RESIDUAL),
                path="%s.residual[%d]" % (prefix, index),
                evidence=dict(part),
            )
        )
    return records


# ------------------------------------------------------------------ xdiff
def _xdiff_records(subject, basis, prefix="xdiff") -> List[Record]:
    records: List[Record] = []
    payload = detectcore.run_xdiff(_points_of(subject), subject.get("target") or "wgs84")
    for index, finding in enumerate(payload["findings"]):
        _emit(records, basis, finding, prefix, index, "xdiff")
    records.append(
        Record(
            rule_id=spec.RULE_VERDICT,
            verdict=INFO,
            message="xdiff 判定：%s" % payload["verdict"],
            basis=basis.ref(spec.RULE_VERDICT),
            path="%s.verdict" % prefix,
            evidence={"target": payload["target"], "pairwise": payload["pairwise"], "jumps": payload["jumps"]},
        )
    )
    return records


# ------------------------------------------------------------------ geojson
def _geojson_records(subject, basis, prefix="geojson") -> List[Record]:
    records: List[Record] = []
    documents = _geojson_documents_of(subject)
    payload = geojsoncheck.run_geojson(documents, strict_ring=bool(subject.get("strict_ring")))
    _structure_records(records, basis, payload, prefix)
    for index, finding in enumerate(payload["findings"]):
        _emit(records, basis, finding, prefix, index, "geojson")
    records.append(
        Record(
            rule_id=spec.RULE_VERDICT,
            verdict=INFO,
            message="geojson 判定：%s" % payload["verdict"],
            basis=basis.ref(spec.RULE_VERDICT),
            path="%s.verdict" % prefix,
            evidence={"counts": payload["counts"], "strict_ring": payload["strict_ring"]},
        )
    )
    return records


def _geojson_documents_of(subject) -> List[Tuple[str, Any]]:
    raw = subject.get("documents")
    if not isinstance(raw, list):
        raise ValueError("subject.documents 必须是数组（[{name, document}, …]）")
    out = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("document"), (dict, list)):
            raise ValueError("documents 每项必须是 {name, document}")
        out.append((str(item.get("name", "doc.json")), item["document"]))
    return out


# ------------------------------------------------------------------ tiles
def _tiles_records(subject, basis, prefix="tiles") -> List[Record]:
    records: List[Record] = []
    groups = _tile_groups_of(subject)
    kind = str(subject.get("input_kind", "tiles"))
    points = _points_of(subject, "points") if subject.get("points") is not None else []
    payload = tilescheck.run_tiles(groups, kind=kind, points=points)
    for index, finding in enumerate(payload["findings"]):
        _emit(records, basis, finding, prefix, index, "tiles")
    records.append(
        Record(
            rule_id=spec.RULE_VERDICT,
            verdict=INFO,
            message="tiles 判定：%s" % payload["verdict"],
            basis=basis.ref(spec.RULE_VERDICT),
            path="%s.verdict" % prefix,
            evidence={"kind": payload["kind"], "tms_note": payload["tms_note"]},
        )
    )
    return records


def _tile_groups_of(subject) -> List[tilescheck.TileGroup]:
    raw = subject.get("groups")
    if not isinstance(raw, list):
        raise ValueError("subject.groups 必须是数组（[{id, bbox?, tiles: [{z, x, y, wrap?, scheme?, bbox?}]}]）")
    groups = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("groups 每项必须是对象")
        tiles = []
        for tile in item.get("tiles") or []:
            if not isinstance(tile, dict):
                raise ValueError("tiles 每项必须是对象")
            z = tile.get("z")
            if not isinstance(z, int) or isinstance(z, bool) or z < 0:
                raise ValueError("瓦片 z 不能为负且必须是整数（实得 %r）" % (z,))
            tiles.append(
                tilescheck.Tile(
                    z=z,
                    x=int(tile["x"]),
                    y=int(tile["y"]),
                    wrap=tile.get("wrap") is True,
                    scheme=tile.get("scheme") if isinstance(tile.get("scheme"), str) else None,
                    bbox=tuple(tile["bbox"]) if isinstance(tile.get("bbox"), list) else None,
                )
            )
        bbox = tuple(item["bbox"]) if isinstance(item.get("bbox"), list) else None
        groups.append(tilescheck.TileGroup(id=str(item.get("id", "group")), tiles=tiles, bbox=bbox))
    return groups


# ------------------------------------------------------------------ 输入规整
def _mode_of(subject) -> str:
    mode = subject.get("mode", spec.DEFAULT_MODE)
    if not isinstance(mode, str) or mode not in spec.MODES:
        raise ValueError("subject.mode 必须是 %s 之一" % "|".join(spec.MODES))
    return mode
