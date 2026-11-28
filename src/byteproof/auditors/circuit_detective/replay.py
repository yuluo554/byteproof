"""回放短码与揭示计划（照搬旧仓 ``replay.mjs`` + ``reveal.mjs``）。

短码：版本 + seed + 探测序列 + 提交网表 + CRC16，Base64url 编码；逐位确定，不含
时间戳与机器信息。解码失败（篡改/截断/版本不兼容/非法字符）直接抛错，绝不
"退而求其次"进普通关卡。揭示计划：按"从输入侧到输出侧"的层级切开隐藏网表。
"""

from __future__ import annotations

import base64
import struct
from typing import Dict, List, Tuple

from .netlist import gate_arity, topo_order
from .rng import normalize_seed
from .spec import GATE_TYPES, MAX_CODE_LENGTH, RECORD_VERSION, SIGNAL_BITS

MAX_GATES_ENCODE = 12


class CodeError(ValueError):
    """短码不可用（篡改/截断/版本不同/损坏）——UI 明确提示，不静默进别的关卡。"""


class CodeOverflow(CodeError):
    """短码超长（调用方据此走降级分享文案，而不是把它当成普通失败）。"""


class _BitWriter:
    def __init__(self) -> None:
        self.bytes: List[int] = []
        self.current = 0
        self.filled = 0

    def write(self, value: int, bits: int) -> None:
        for i in range(bits - 1, -1, -1):
            self.current = (self.current << 1) | ((value >> i) & 1)
            self.filled += 1
            if self.filled == 8:
                self.bytes.append(self.current)
                self.current = 0
                self.filled = 0

    def finish(self) -> List[int]:
        if self.filled > 0:
            self.bytes.append((self.current << (8 - self.filled)) & 0xFF)
            self.current = 0
            self.filled = 0
        return list(self.bytes)


class _BitReader:
    def __init__(self, data: List[int]) -> None:
        self.bytes = data
        self.offset = 0

    def read(self, bits: int) -> int:
        value = 0
        for _ in range(bits):
            byte_index = self.offset >> 3
            bit_index = 7 - (self.offset & 7)
            byte = self.bytes[byte_index] if byte_index < len(self.bytes) else 0
            value = (value << 1) | ((byte >> bit_index) & 1)
            self.offset += 1
        return value

    @property
    def exhausted(self) -> bool:
        return self.offset >= len(self.bytes) * 8


def _to_base64url(data: List[int]) -> str:
    return base64.urlsafe_b64encode(bytes(data)).decode("ascii").rstrip("=")


def _from_base64url(text: str) -> List[int]:
    import re

    if not re.fullmatch(r"[A-Za-z0-9_-]*", text):
        raise CodeError("短码含非法字符")
    padded = text.replace("-", "+").replace("_", "/")
    padded += "=" * ((4 - (padded % 4 if False else len(padded) % 4)) % 4)
    return list(base64.b64decode(padded))


def crc16(data) -> int:
    """CRC-16/CCITT-FALSE（与旧仓逐位一致）。"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _signal_index(netlist: dict, name: str) -> int:
    known = list(netlist["inputs"]) + [gate["id"] for gate in netlist["gates"]]
    index = known.index(name) if name in known else -1
    if index < 0 or index > 0xF:
        raise CodeError("信号不可编码: %s" % name)
    return index


def encode_record(record: dict) -> str:
    """{seed, probes, netlist} → Base64url 短码；超长抛 CodeOverflow。"""
    seed = normalize_seed(record["seed"])
    probe_count = len(record["probes"])
    netlist = record["netlist"]
    gate_count = len(netlist["gates"])
    if gate_count > MAX_GATES_ENCODE:
        raise CodeError("门数超过 %d，无法编码" % MAX_GATES_ENCODE)
    if probe_count > 255:
        raise CodeError("探测步数过多，无法编码")
    if len(netlist["inputs"]) != 4:
        raise CodeError("首期只支持 4 个输入端口")

    writer = _BitWriter()
    writer.write(RECORD_VERSION, 8)
    writer.write((seed >> 32) & 0xFFFFFFFF, 32)
    writer.write(seed & 0xFFFFFFFF, 32)
    writer.write(probe_count, 8)
    for vector in record["probes"]:
        writer.write(vector & 0xF, 4)
    writer.write(gate_count, 4)
    for gate in netlist["gates"]:
        writer.write(GATE_TYPES.index(gate["type"]), 2)
        writer.write(_signal_index(netlist, gate["in"][0]), SIGNAL_BITS)
        arity = gate_arity(gate["type"])
        writer.write(_signal_index(netlist, gate["in"][1]) if arity == 2 else 0, SIGNAL_BITS)
    for name in netlist["outputs"]:
        writer.write(_signal_index(netlist, netlist["outputsMap"][name]), SIGNAL_BITS)
    body = writer.finish()
    checksum = crc16(body)
    out = body + [checksum >> 8, checksum & 0xFF]
    code = _to_base64url(out)
    if len(code) > MAX_CODE_LENGTH:
        raise CodeOverflow("本次操作过长，无法生成短码（%d > %d 字符）" % (len(code), MAX_CODE_LENGTH))
    return code


def decode_record(code: str) -> dict:
    """短码 → {version, seed, seedText, probes, netlist}；失败抛 CodeError。"""
    if not isinstance(code, str) or len(code) == 0:
        raise CodeError("短码为空")
    if len(code) > MAX_CODE_LENGTH:
        raise CodeError("短码超长，不是本版本产物")
    data = _from_base64url(code)
    if len(data) < 3:
        raise CodeError("短码过短，无法解码")
    body = data[:-2]
    expected = (data[-2] << 8) | data[-1]
    if crc16(body) != expected:
        raise CodeError("短码校验失败（可能被篡改或截断）")

    reader = _BitReader(body)
    version = reader.read(8)
    if version != RECORD_VERSION:
        raise CodeError("版本不兼容：短码版本 %d，当前只支持 %d" % (version, RECORD_VERSION))
    high = reader.read(32)
    low = reader.read(32)
    seed = (high << 32) | low
    probe_count = reader.read(8)
    probes = [reader.read(4) for _ in range(probe_count)]

    gate_count = reader.read(4)
    inputs = ["i0", "i1", "i2", "i3"]
    raw_gates = []
    for _index in range(gate_count):
        gate_type = GATE_TYPES[reader.read(2)]
        in0 = reader.read(SIGNAL_BITS)
        in1 = reader.read(SIGNAL_BITS)
        raw_gates.append({"type": gate_type, "in0": in0, "in1": in1})
    outputs = ["o0", "o1", "o2", "o3"]
    output_indexes = [reader.read(SIGNAL_BITS) for _ in outputs]

    signals: List[str] = list(inputs)
    netlist: dict = {"inputs": inputs, "outputs": outputs, "gates": [], "outputsMap": {}}
    for index, raw in enumerate(raw_gates):
        gate_id = "g%02d" % (index + 1)
        arity = gate_arity(raw["type"])
        pins = [signals[raw["in0"]] if raw["in0"] < len(signals) else None]
        if arity == 2:
            pins.append(signals[raw["in1"]] if raw["in1"] < len(signals) else None)
        if any(not isinstance(pin, str) for pin in pins):
            raise CodeError("短码损坏：第 %d 个门引用了不存在的信号" % (index + 1))
        netlist["gates"].append({"id": gate_id, "type": raw["type"], "in": pins})
        signals.append(gate_id)
    for name, index in zip(outputs, output_indexes):
        src = signals[index] if index < len(signals) else None
        if not isinstance(src, str):
            raise CodeError("短码损坏：输出 %s 引用了不存在的信号" % name)
        netlist["outputsMap"][name] = src

    return {"version": version, "seed": seed, "seedText": str(seed), "probes": probes, "netlist": netlist}


# ------------------------------------------------------------------ reveal
def build_reveal_plan(netlist: dict) -> dict:
    """把隐藏网表按"从输入侧到输出侧"的层级切开。

    层级定义：直接吃输入信号的门为第 0 层；其余门的层 = 1 + 上游门的最大层；
    组合环成员单列到最后一层（不参与前向层级），保证层号严格递增。
    """
    order, cyclic = topo_order(netlist)
    gates = {gate["id"]: gate for gate in netlist["gates"]}
    cyclic_set = set(cyclic)
    layer_by_id: Dict[str, int] = {}

    for gate_id in order:
        gate = gates[gate_id]
        layer = 0
        for src in gate["in"]:
            if src in cyclic_set:
                continue  # 环成员不参与前向层级
            upstream = layer_by_id.get(src)
            if isinstance(upstream, int):
                layer = max(layer, upstream + 1)
        layer_by_id[gate_id] = layer

    max_layer = -1
    for gate_id in order:
        max_layer = max(max_layer, layer_by_id[gate_id])
    for gate_id in cyclic:
        layer_by_id[gate_id] = max_layer + 1

    total_layers = max_layer + 2 if cyclic else max_layer + 1
    layers: List[List[str]] = [[] for _ in range(max(0, total_layers))]
    for gate_id in list(order) + list(cyclic):
        index = layer_by_id.get(gate_id, 0)
        while len(layers) <= index:
            layers.append([])
        layers[index].append(gate_id)
    for layer in layers:
        layer.sort()

    revealed_order = list(order) + list(cyclic)
    order_index = {gate_id: index for index, gate_id in enumerate(revealed_order)}
    return {"order": revealed_order, "layers": layers, "layerById": layer_by_id, "orderIndex": order_index, "cyclic": list(cyclic)}


def reveal_progress(plan: dict, revealed_layers: int) -> dict:
    """终态（已揭示层数 = 总层数）时可见的门集合；步进由 UI 计时器驱动。"""
    revealed = set()
    layers = []
    for index, layer in enumerate(plan["layers"]):
        if index >= revealed_layers:
            continue
        layers.append(index)
        revealed.update(layer)
    return {"revealed": revealed, "layers": layers, "done": revealed_layers >= len(plan["layers"])}


def reveal_sequence(plan: dict) -> List[int]:
    """揭示序列（严格递增的层号），供动画与测试共用。"""
    return list(range(len(plan["layers"])))
