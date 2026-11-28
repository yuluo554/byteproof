"""编排层：``evaluate(subject, basis) -> Iterable[Record]``（账本化 + 模式分发）。

五个模式 = 旧仓五个 MCP 工具的**同参**调用：subject.mode 是工具名，subject.arguments
是工具参数对象（与旧仓 ``tools/call`` 的 arguments 逐字段同名）。判定结果（result
对象）整体进 ``hs-summary`` 的 ``evidence.result``；每条 finding
（reasons / violations / explain / hops[].violations）按 catalogue severity 折算账本
verdict：decisive → error（阻断）、informational → info。

旧 MCP 工具面恒 rc0（caller mistake 渲染为 isError 结果）→ 新 0/1/2 的折算是登记在
案的口径差（``docs/http-semantics.md`` §7）：账本的退出码承载"有阻断结论"，decisive
finding 就是阻断结论。caller mistake（:class:`JudgementError`，``ValueError`` 子类）
→ 宿主 CLI「输入不合法」rc 2。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Tuple

from byteproof.core.basis import Basis
from byteproof.core.ledger import ERROR, INFO, Record

from . import cache as cache_mod
from . import conditional as conditional_mod
from . import cors as cors_mod
from . import fetch_sim as fetch_sim_mod
from . import vary as vary_mod
from .catalogue import Catalogue
from .default_settings import SETTINGS
from .spec import DEFAULT_MODE, MODES

#: 各模式结果对象里承载 finding 列表的键（与旧仓工具输出同构）。
_FINDING_KEY = {
    "cache_evaluate": "reasons",
    "conditional_evaluate": "explain",
    "cors_evaluate": "violations",
    "vary_match": "reasons",
}

_SUMMARY_PATH = "result"


def evaluate(subject: Mapping[str, Any], basis: Basis) -> Iterable[Record]:
    mode = subject.get("mode", DEFAULT_MODE)
    if mode not in MODES:
        raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(MODES), mode))
    arguments = subject.get("arguments")
    if not isinstance(arguments, dict):
        raise ValueError("arguments 必须是对象（工具参数，与旧仓 tools/call 的 arguments 同参）")

    settings = subject.get("thresholds")
    if settings is None:
        settings = SETTINGS
    if not isinstance(settings, dict):
        raise ValueError("thresholds 必须是对象（severity / vary_normalization / preflight_cache_key）")
    catalog = Catalogue(basis, settings)

    result = _dispatch(mode, arguments, catalog)
    records = _records(mode, result, catalog)
    records.append(_summary_record(mode, result, records, basis))
    return records


def _dispatch(mode: str, arguments: Mapping[str, Any], catalog: Catalogue) -> dict:
    if mode == "cache_evaluate":
        return cache_mod.evaluate_cache(arguments, catalog)
    if mode == "conditional_evaluate":
        return conditional_mod.evaluate_conditional(arguments, catalog)
    if mode == "cors_evaluate":
        return cors_mod.evaluate_cors(arguments, catalog)
    if mode == "cors_simulate_fetch":
        return fetch_sim_mod.evaluate_fetch(arguments, catalog)
    if mode == "vary_match":
        return vary_mod.evaluate_vary(arguments, catalog)
    raise ValueError("mode 必须是 %s 之一，实际 %r" % ("/".join(MODES), mode))


def _collect(mode: str, result: Mapping[str, Any]) -> List[Tuple[Mapping[str, Any], str]]:
    """统一抽出 ``(finding, path)`` 对。fetch_sim 的 findings 藏在 hops[].violations，
    path 取命中 hop 的 occurrence 序号 + URL；其余模式 path = ``result``。"""
    if mode == "cors_simulate_fetch":
        pairs: List[Tuple[Mapping[str, Any], str]] = []
        for index, hop in enumerate(result.get("hops", [])):
            for finding in hop.get("violations", []):
                pairs.append((finding, "hop[%d]:%s" % (index, hop.get("url", ""))))
        return pairs
    key = _FINDING_KEY[mode]
    return [(finding, _SUMMARY_PATH) for finding in result.get(key, [])]


def _records(mode: str, result: Mapping[str, Any], catalog: Catalogue) -> List[Record]:
    records: List[Record] = []
    counters: Dict[Tuple[str, str], int] = {}
    for finding, path in _collect(mode, result):
        code = finding["code"]
        detail = finding["detail"]
        verdict = ERROR if catalog.severity(code) == "decisive" else INFO
        count = counters.get((code, path), 0) + 1
        counters[(code, path)] = count
        if count > 1:
            path = "%s#%d" % (path, count)
        records.append(Record(
            rule_id=code,
            verdict=verdict,
            message=detail,
            basis=catalog.basis_ref(code),
            path=path,
            evidence={
                "mode": mode,
                "code": code,
                "detail": detail,
                "spec_ref": list(finding.get("spec_ref", [])),
                "severity": catalog.severity(code),
            },
        ))
    return records


def _summary_record(mode: str, result: Mapping[str, Any], records: List[Record], basis: Basis) -> Record:
    errors = sum(1 for r in records if r.verdict == ERROR)
    infos = sum(1 for r in records if r.verdict == INFO)
    return Record(
        rule_id="hs-summary",
        verdict=INFO,
        message="mode=%s：findings=%d（decisive→error %d / informational→info %d）"
                % (mode, len(records), errors, infos),
        basis=basis.ref("hs-summary"),
        path="summary",
        evidence={
            "mode": mode,
            "records": len(records),
            "error": errors,
            "info": infos,
            # 工具结果整体留档：golden 对撞按 canonical JSON 逐字节比对它
            "result": dict(result),
        },
    )
