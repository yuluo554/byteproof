"""网表结构与拓扑排序（照搬旧仓 ``netlist.mjs``）。网表是纯数据：门类型 + 输入引脚
引用 + 输出映射。这里不读时钟、随机数或环境信息。"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

from .spec import GATE_ARITY, GATE_TYPES


def gate_arity(gate_type: str) -> int:
    return GATE_ARITY.get(gate_type, 0)


def gate_map(netlist: dict) -> Dict[str, dict]:
    return {gate["id"]: gate for gate in netlist["gates"] if isinstance(gate, dict) and isinstance(gate.get("id"), str)}


def validate_netlist(netlist) -> Tuple[bool, List[str]]:
    """校验网表结构。返回 {ok, errors}，不抛异常，把坏数据挡在仿真之外。"""
    errors: List[str] = []
    if not isinstance(netlist, dict):
        return (False, ["网表必须是对象"])
    if not isinstance(netlist.get("inputs"), list) or len(netlist["inputs"]) == 0:
        errors.append("inputs 必须是非空数组")
    if not isinstance(netlist.get("outputs"), list) or len(netlist["outputs"]) == 0:
        errors.append("outputs 必须是非空数组")
    inputs = netlist.get("inputs") if isinstance(netlist.get("inputs"), list) else []
    outputs = netlist.get("outputs") if isinstance(netlist.get("outputs"), list) else []
    if len(set(inputs)) != len(inputs):
        errors.append("inputs 含重复端口名")
    if len(set(outputs)) != len(outputs):
        errors.append("outputs 含重复端口名")
    for name in outputs:
        if name in inputs:
            errors.append("输出端口不得与输入端口同名: %s" % name)

    gates = netlist.get("gates") if isinstance(netlist.get("gates"), list) else []
    if not isinstance(netlist.get("gates"), list):
        errors.append("gates 必须是数组")

    # 两遍：先收集全部信号名（允许前向引用，组合环靠拓扑排序识别），再校验引脚。
    known = set(inputs)
    ids = set()
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or len(gate_id) == 0:
            continue
        if gate_id in ids:
            errors.append("门 id 重复: %s" % gate_id)
        if gate_id in known:
            errors.append("门 id 与输入端口重名: %s" % gate_id)
        ids.add(gate_id)
        known.add(gate_id)

    for gate in gates:
        if not isinstance(gate, dict):
            errors.append("门必须是对象")
            continue
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or len(gate_id) == 0:
            errors.append("门缺少字符串 id")
            continue
        if gate.get("type") not in GATE_TYPES:
            errors.append("未知门类型: %s" % gate.get("type"))
            continue
        arity = gate_arity(gate["type"])
        pins = gate.get("in")
        if not isinstance(pins, list) or len(pins) != arity:
            errors.append("门 %s 的输入引脚数应为 %d" % (gate_id, arity))
            continue
        for src in pins:
            if src not in known:
                errors.append("门 %s 引用了未定义信号: %s" % (gate_id, src))

    out_map = netlist.get("outputsMap", netlist.get("out"))
    if not isinstance(out_map, dict):
        errors.append("outputsMap 必须存在")
    else:
        for name in outputs:
            src = out_map.get(name)
            if not isinstance(src, str):
                errors.append("输出端口 %s 未映射到信号" % name)
            elif src not in known:
                errors.append("输出端口 %s 引用了未定义信号: %s" % (name, src))
    return (len(errors) == 0, errors)


def topo_order(netlist: dict) -> Tuple[List[str], List[str]]:
    """Kahn 拓扑排序；同一层按门 id 字典序。cyclic = 覆盖不到的门（组合环成员）。"""
    gate_by_id = gate_map(netlist)
    indegree: Dict[str, int] = {}
    dependents: Dict[str, List[str]] = {}
    for gate in netlist["gates"]:
        gate_id = gate["id"]
        indegree[gate_id] = 0
        dependents[gate_id] = []
    for gate in netlist["gates"]:
        for src in gate["in"]:
            if src not in gate_by_id:
                continue
            indegree[gate["id"]] += 1
            dependents[src].append(gate["id"])

    ready = sorted(gid for gid, degree in indegree.items() if degree == 0)
    order: List[str] = []
    while ready:
        gate_id = ready.pop(0)
        order.append(gate_id)
        nexts = sorted(dependents[gate_id])
        for dependent in nexts:
            degree = indegree[dependent] - 1
            indegree[dependent] = degree
            if degree == 0:
                ready.append(dependent)
                ready.sort()

    ordered = set(order)
    cyclic = sorted(gate["id"] for gate in netlist["gates"] if gate["id"] not in ordered)
    return (order, cyclic)


def level_to_json(level: dict) -> str:
    """固定键顺序的关卡 JSON，字节级一致的前提。"""
    ordered = {
        "format": level["format"],
        "version": level["version"],
        "id": level["id"],
        "seed": level["seed"],
        "label": level["label"],
        "difficulty": level["difficulty"],
        "inputs": level["inputs"],
        "outputs": level["outputs"],
        "netlist": {
            "inputs": level["netlist"]["inputs"],
            "outputs": level["netlist"]["outputs"],
            "gates": [{"id": g["id"], "type": g["type"], "in": g["in"]} for g in level["netlist"]["gates"]],
            "outputsMap": level["netlist"]["outputsMap"],
        },
        "optimal": level["optimal"],
    }
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":"))
