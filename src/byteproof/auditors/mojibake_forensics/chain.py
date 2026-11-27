"""链枚举 + 无损复算 + 三层打分 + 逐步证明（旧仓 ``paths`` / ``score`` / ``explain``）。

只做纯计算：给定**已解码的 str**，枚举「encode -> decode」链（链深 = decode 步数），
逐条反向复算，按冻结排序键排出有界候选；``explain`` 复用同一次排序结果逐步重放。
不读文件、不读时钟、不读环境变量、不联网。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from . import spec


@dataclass(frozen=True)
class Step:
    index: int
    op: str
    codec: str
    input_text: Optional[str] = None
    output_text: Optional[str] = None
    input_hex: Optional[str] = None
    output_hex: Optional[str] = None

    def as_dict(self) -> dict:
        payload = {"index": self.index, "op": self.op, "codec": self.codec}
        if self.input_text is not None:
            payload["input"] = self.input_text
        if self.output_text is not None:
            payload["output"] = self.output_text
        if self.input_hex is not None:
            payload["input_hex"] = self.input_hex
        if self.output_hex is not None:
            payload["output_hex"] = self.output_hex
        return payload


@dataclass(frozen=True)
class Chain:
    steps: Tuple[Step, ...]

    @property
    def depth(self) -> int:
        return sum(1 for step in self.steps if step.op == "decode")

    @property
    def path(self):
        return [{"op": step.op, "codec": step.codec} for step in self.steps]

    @property
    def path_string(self) -> str:
        return ">".join("%s:%s" % (step.op, step.codec) for step in self.steps)

    @property
    def result(self) -> Optional[str]:
        if not self.steps:
            return None
        return self.steps[-1].output_text


def hexdump(data) -> str:
    """大写十六进制，字节间单空格（账本证据的稳定形态）。"""
    return " ".join("%02X" % byte for byte in bytearray(data))


def parse_hex(text: str) -> bytes:
    """把 ``"E9 9B 85"`` 之类的证据串解析回字节（``file`` 模式的输入形态）。"""
    if not isinstance(text, str):
        raise ValueError("bytes_hex 必须是十六进制字符串")
    tokens = text.replace("\n", " ").replace("\t", " ").split()
    if not tokens:
        raise ValueError("bytes_hex 为空")
    if len(tokens) == 1:
        blob = tokens[0]
        if len(blob) % 2 != 0:
            raise ValueError("bytes_hex 长度为奇数，无法按字节解析")
        tokens = [blob[index : index + 2] for index in range(0, len(blob), 2)]
    out = bytearray()
    for token in tokens:
        if len(token) != 2:
            raise ValueError("bytes_hex 的每一段必须是两个十六进制字符：%r" % (token,))
        try:
            out.append(int(token, 16))
        except ValueError:
            raise ValueError("bytes_hex 含非十六进制字符：%r" % (token,))
    return bytes(out)


def _apply(state, op, codec):
    if op == "encode":
        return state.encode(codec)
    if op == "decode":
        return state.decode(codec)
    raise ValueError("未知链操作：%r" % (op,))


def replay(text: str, chain: Chain):
    """正向应用链，返回最终状态；任一步失败返回 ``None``。"""
    state = text
    try:
        for step in chain.steps:
            state = _apply(state, step.op, step.codec)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return state


def validate_depth(max_depth=None) -> int:
    depth = spec.MAX_DEPTH if max_depth is None else int(max_depth)
    if depth < 1:
        raise ValueError("max_depth 必须 >= 1")
    return depth


def verify_lossless(text: str, chain: Chain) -> bool:
    """正向重放记录中间态，再反向逐码复算；任一字节不等即非无损。"""
    states = [text]
    state = text
    try:
        for step in chain.steps:
            state = _apply(state, step.op, step.codec)
            states.append(state)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False

    state = states[-1]
    for index in range(len(chain.steps) - 1, -1, -1):
        step = chain.steps[index]
        inverse = "decode" if step.op == "encode" else "encode"
        try:
            state = _apply(state, inverse, step.codec)
        except (UnicodeEncodeError, UnicodeDecodeError):
            return False
        if state != states[index]:
            return False
    return state == text


def enumerate_chains(text, encoders=None, decoders=None, max_depth=None):
    """广度优先枚举无损、非恒等的候选链，按 ``(depth, path_string)`` 排序。"""
    encoders = tuple(spec.ENCODERS if encoders is None else encoders)
    decoders = tuple(spec.DECODERS if decoders is None else decoders)
    depth_limit = validate_depth(max_depth)

    results = []
    frontier = [(text, ())]
    for _level in range(1, depth_limit + 1):
        next_frontier = []
        for current, steps in frontier:
            for encoder in encoders:
                try:
                    raw = current.encode(encoder)
                except UnicodeEncodeError:
                    continue
                for decoder in decoders:
                    if decoder == encoder:
                        continue
                    try:
                        output = raw.decode(decoder)
                    except UnicodeDecodeError:
                        continue
                    new_steps = steps + (
                        Step(
                            index=len(steps) + 1,
                            op="encode",
                            codec=encoder,
                            input_text=current,
                            output_hex=hexdump(raw),
                        ),
                        Step(
                            index=len(steps) + 2,
                            op="decode",
                            codec=decoder,
                            input_hex=hexdump(raw),
                            output_text=output,
                        ),
                    )
                    chain = Chain(steps=new_steps)
                    if not verify_lossless(text, chain):
                        continue
                    if output == text:
                        continue
                    results.append(chain)
                    next_frontier.append((output, new_steps))
        frontier = next_frontier

    results.sort(key=lambda chain: (chain.depth, chain.path_string))
    return results


def collapse_by_result(chains):
    """每个不同结果只留一条代表链（最浅，其次 path_string 最小）。"""
    best = {}
    for chain in chains:
        result = chain.result
        if result is None:
            continue
        key = (chain.depth, chain.path_string)
        current = best.get(result)
        if current is None or key < (current.depth, current.path_string):
            best[result] = chain
    return [best[text] for text in sorted(best)]


# ------------------------------------------------------------------ 打字分
def _is_noncharacter(code: int) -> bool:
    if 0xFDD0 <= code <= 0xFDEF:
        return True
    return (code & 0xFFFE) == 0xFFFE


def char_score(char: str) -> float:
    code = ord(char)
    if code == 0xFFFD:
        return spec.REPLACEMENT
    if char in spec.REGULAR_WHITESPACE:
        return spec.ASCII_VISIBLE
    if 0x20 <= code <= 0x7E:
        return spec.ASCII_VISIBLE
    if 0x4E00 <= code <= 0x9FFF:
        return spec.CJK
    if 0x3040 <= code <= 0x30FF:
        return spec.CJK
    if 0xAC00 <= code <= 0xD7AF:
        return spec.CJK
    if 0x00A0 <= code <= 0x024F:
        return spec.LATIN_EXT
    if 0xFF61 <= code <= 0xFF9F:
        return spec.HALFWIDTH_KATAKANA
    if code < 0x20 or code == 0x7F:
        return spec.CONTROL
    if 0xE000 <= code <= 0xF8FF:
        return spec.PUA
    if 0xD800 <= code <= 0xDFFF:
        return spec.PUA
    if _is_noncharacter(code):
        return spec.PUA
    return spec.OTHER


def readability(text: str) -> float:
    if not text:
        return 0.0
    total = 0.0
    for char in text:
        total += char_score(char)
    normalized = total / float(len(text))
    if normalized < -1.0:
        return -1.0
    if normalized > 1.0:
        return 1.0
    return normalized


def depth_score(depth: int) -> float:
    return 1.0 / (1.0 + float(depth))


def sort_key(entry: dict):
    total = entry.get("score_total")
    if total is None:
        total = entry.get("score", {}).get("total", 0.0)
    return (-float(total), int(entry["depth"]), str(entry["path_string"]))


def rank(chains) -> list:
    entries = []
    for chain in chains:
        result = chain.result or ""
        read = readability(result)
        depth = depth_score(chain.depth)
        total = spec.W_READ * read + spec.W_DEPTH * depth + spec.W_LANG * 0.0
        entries.append(
            {
                "path": chain.path,
                "path_string": chain.path_string,
                "depth": chain.depth,
                "result": result,
                "score_total": total,
                "score": {
                    "readability": read,
                    "depth": depth,
                    "language": 0.0,
                    "total": total,
                },
                "chain": chain,
            }
        )
    entries.sort(key=sort_key)
    for position, entry in enumerate(entries, 1):
        entry["rank"] = position
    return entries


def search(text, encoders=None, decoders=None):
    """跑一次有界搜索；返回 ``(ranked, total_chains)``，供 attr / explain / recover 共用。"""
    if not isinstance(text, str):
        raise ValueError(
            "text 必须是已解码的 str；原始字节请用 file 模式（bytes_hex）"
        )
    if text == "":
        raise ValueError("text 为空，没有可归因的字符")
    encoders = tuple(spec.ENCODERS if encoders is None else encoders)
    decoders = tuple(spec.DECODERS if decoders is None else decoders)
    _check_subset(encoders, spec.ENCODERS, "source_enc")
    _check_subset(decoders, spec.DECODERS, "target_enc")
    chains = enumerate_chains(text, encoders=encoders, decoders=decoders)
    collapsed = collapse_by_result(chains)
    return rank(collapsed), len(chains)


def _check_subset(names, allowed, field: str) -> None:
    unknown = [name for name in names if name not in allowed]
    if unknown:
        raise ValueError(
            "%s 含冻结集合之外的编码名：%s（只允许在冻结集合内收窄，不能新增）"
            % (field, ", ".join(sorted(unknown)))
        )


def confidence(entries):
    """候选之间的相对份额区间（不是概率）；返回 ``(intervals, note)``。"""
    count = len(entries)
    if count == 0:
        return [], None
    if count == 1:
        return [{"lower": 1.0, "upper": 1.0}], "single_candidate_in_bounded_search"
    total = 0.0
    for entry in entries:
        total += entry["score_total"]
    if total <= 0.0:
        return [None] * count, "no_positive_score"
    spread = 0.05 * (count - 1)
    intervals = []
    for entry in entries:
        value = entry["score_total"] / total
        intervals.append(
            {
                "lower": value / (1.0 + spread),
                "upper": min(1.0, value * (1.0 + spread)),
            }
        )
    return intervals, None


# ------------------------------------------------------------------ 逐步证明
def bytes_from_hex(text):
    if text is None:
        return None
    return bytes(bytearray(int(token, 16) for token in text.split()))


def _first_byte_diff(left: bytes, right: bytes) -> int:
    for index in range(min(len(left), len(right))):
        if left[index] != right[index]:
            return index
    return min(len(left), len(right))


def _first_char_diff(left: str, right: str) -> int:
    for index in range(min(len(left), len(right))):
        if left[index] != right[index]:
            return index
    return min(len(left), len(right))


def codepoint(char) -> Optional[str]:
    if char is None:
        return None
    return "U+%04X" % ord(char)


def replay_chain(chain: Chain) -> dict:
    """逐步重放并独立复算；第一个不一致处停在 ``failed_step``（1 起）。"""
    steps = []
    failed_step = None
    state = chain.steps[0].input_text if chain.steps else None

    for step in chain.steps:
        entry = {"index": step.index, "op": step.op, "codec": step.codec}

        if step.op == "encode":
            if not isinstance(state, str):
                entry["verify"] = False
                entry["failure"] = {
                    "reason": "state_type",
                    "expected": "str",
                    "observed": type(state).__name__,
                }
                failed_step = step.index
                steps.append(entry)
                break
            entry["input"] = state
            if step.input_text is None:
                entry["verify"] = False
                entry["failure"] = {"reason": "missing_record"}
                failed_step = step.index
                steps.append(entry)
                break
            if state != step.input_text:
                entry["verify"] = False
                entry["failure"] = {
                    "reason": "input_mismatch",
                    "expected": step.input_text,
                    "observed": state,
                    "char_offset": _first_char_diff(step.input_text, state),
                }
                failed_step = step.index
                steps.append(entry)
                break
            try:
                raw = state.encode(step.codec)
            except UnicodeEncodeError as exc:
                entry["verify"] = False
                entry["failure"] = {"reason": "encode_error", "char_offset": exc.start}
                failed_step = step.index
                steps.append(entry)
                break
            entry["output_hex"] = hexdump(raw)
            expected = bytes_from_hex(step.output_hex)
            if expected is None:
                entry["verify"] = False
                entry["failure"] = {"reason": "missing_record"}
                failed_step = step.index
                steps.append(entry)
                break
            if raw != expected:
                entry["verify"] = False
                entry["failure"] = {
                    "reason": "mismatch",
                    "expected_hex": hexdump(expected),
                    "observed_hex": hexdump(raw),
                    "byte_offset": _first_byte_diff(expected, raw),
                }
                failed_step = step.index
                steps.append(entry)
                break
            entry["verify"] = True
            state = raw
        else:
            if not isinstance(state, (bytes, bytearray)):
                entry["verify"] = False
                entry["failure"] = {
                    "reason": "state_type",
                    "expected": "bytes",
                    "observed": type(state).__name__,
                }
                failed_step = step.index
                steps.append(entry)
                break
            state = bytes(state)
            entry["input_hex"] = hexdump(state)
            recorded_input = bytes_from_hex(step.input_hex)
            if recorded_input is None:
                entry["verify"] = False
                entry["failure"] = {"reason": "missing_record"}
                failed_step = step.index
                steps.append(entry)
                break
            if state != recorded_input:
                entry["verify"] = False
                entry["failure"] = {
                    "reason": "input_mismatch",
                    "expected_hex": hexdump(recorded_input),
                    "observed_hex": hexdump(state),
                    "byte_offset": _first_byte_diff(recorded_input, state),
                }
                failed_step = step.index
                steps.append(entry)
                break
            try:
                text = state.decode(step.codec)
            except UnicodeDecodeError as exc:
                entry["verify"] = False
                entry["failure"] = {"reason": "decode_error", "byte_offset": exc.start}
                failed_step = step.index
                steps.append(entry)
                break
            entry["output"] = text
            if step.output_text is None:
                entry["verify"] = False
                entry["failure"] = {"reason": "missing_record"}
                failed_step = step.index
                steps.append(entry)
                break
            if text != step.output_text:
                entry["verify"] = False
                entry["failure"] = {
                    "reason": "mismatch",
                    "expected": step.output_text,
                    "observed": text,
                    "char_offset": _first_char_diff(step.output_text, text),
                }
                failed_step = step.index
                steps.append(entry)
                break
            entry["verify"] = True
            state = text

        steps.append(entry)

    output = state if isinstance(state, str) else None
    return {
        "steps": steps,
        "verify": failed_step is None,
        "failed_step": failed_step,
        "output": output,
    }


def _step_divergence(left, right, at_step):
    return {
        "at_step": at_step,
        "kind": "step",
        "byte_offset": None,
        "char_offset": None,
        "left": {"op": left["op"], "codec": left["codec"]},
        "right": {"op": right["op"], "codec": right["codec"]},
        "statement": "step %d: op/codec differs: %s:%s vs %s:%s"
        % (at_step, left["op"], left["codec"], right["op"], right["codec"]),
    }


def compare_proofs(left_proof, right_proof, vs_rank, vs_entry) -> dict:
    """只陈述第一处差异（op/codec -> 字节 -> 字符 -> 链长），不判断谁更好。"""
    left_steps = left_proof["steps"]
    right_steps = right_proof["steps"]
    common = min(len(left_steps), len(right_steps))

    result = {
        "vs_rank": vs_rank,
        "vs_result": vs_entry["result"],
        "vs_path_string": vs_entry["path_string"],
        "at_step": None,
        "kind": "none",
        "byte_offset": None,
        "char_offset": None,
        "left": None,
        "right": None,
    }

    for index in range(common):
        left = left_steps[index]
        right = right_steps[index]
        at_step = index + 1

        if left["op"] != right["op"] or left["codec"] != right["codec"]:
            result.update(_step_divergence(left, right, at_step))
            return result

        if not left.get("verify") or not right.get("verify"):
            result.update(
                {
                    "at_step": at_step,
                    "kind": "failed_step",
                    "left": {
                        "verify": bool(left.get("verify")),
                        "failure": left.get("failure"),
                    },
                    "right": {
                        "verify": bool(right.get("verify")),
                        "failure": right.get("failure"),
                    },
                    "statement": "step %d: at least one proof fails verification there"
                    % at_step,
                }
            )
            return result

        if left["op"] == "encode":
            left_bytes = bytes_from_hex(left.get("output_hex"))
            right_bytes = bytes_from_hex(right.get("output_hex"))
            if left_bytes != right_bytes:
                offset = _first_byte_diff(left_bytes or b"", right_bytes or b"")
                left_byte = (
                    "%02X" % left_bytes[offset]
                    if left_bytes is not None and offset < len(left_bytes)
                    else None
                )
                right_byte = (
                    "%02X" % right_bytes[offset]
                    if right_bytes is not None and offset < len(right_bytes)
                    else None
                )
                result.update(
                    {
                        "at_step": at_step,
                        "kind": "bytes",
                        "byte_offset": offset,
                        "left": {"hex": left.get("output_hex"), "byte": left_byte},
                        "right": {"hex": right.get("output_hex"), "byte": right_byte},
                        "statement": "step %d: byte offset %d (0-based) differs: %s vs %s"
                        % (at_step, offset, left_byte, right_byte),
                    }
                )
                return result
        else:
            left_text = left.get("output")
            right_text = right.get("output")
            if left_text != right_text:
                offset = _first_char_diff(left_text or "", right_text or "")
                left_char = (
                    left_text[offset]
                    if left_text is not None and offset < len(left_text)
                    else None
                )
                right_char = (
                    right_text[offset]
                    if right_text is not None and offset < len(right_text)
                    else None
                )
                result.update(
                    {
                        "at_step": at_step,
                        "kind": "text",
                        "char_offset": offset,
                        "left": {"char": left_char, "codepoint": codepoint(left_char)},
                        "right": {"char": right_char, "codepoint": codepoint(right_char)},
                        "statement": "step %d: character offset %d (0-based) differs: %s vs %s"
                        % (
                            at_step,
                            offset,
                            codepoint(left_char),
                            codepoint(right_char),
                        ),
                    }
                )
                return result

    if len(left_steps) != len(right_steps):
        result.update(
            {
                "at_step": common + 1,
                "kind": "depth",
                "left": {"steps": len(left_steps)},
                "right": {"steps": len(right_steps)},
                "statement": "chain lengths differ after step %d: %d vs %d steps"
                % (common, len(left_steps), len(right_steps)),
            }
        )
        return result

    result["statement"] = "no divergence: same path and same outputs"
    return result