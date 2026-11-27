"""器官 ``mojibake-forensics``：已解坏的文本/字节工件 -> 缺陷账本。

旧仓 ``forensics`` 回答「这个已经解坏的 str 是被哪一步 encode/decode 转坏的、还能不能
回去」；本器官把同一判定搬成账本：候选集 + 每步字节证明 + 不可逆判死 + 字节工件诊断。

五个模式（``subject.mode``）：

* ``attr``    —— 有界候选集 + 三层打分 + 相对份额区间；
* ``explain`` —— 对已排序候选逐步重放复算，并陈述与对照候选的第一处差异；
* ``recover`` —— 不可逆五类先判死，其余按 ``pick`` 重放，未经验证的修复不输出；
* ``file``    —— 原始字节诊断（BOM / UTF-16 错位 / ZIP 中央目录名 / CSV 候选）；
* ``scan``    —— 逐文件逐非空行的 CI 门禁（new / baselined / stale）。

**没有搬**：真实文件读取与目录遍历（输入层把文本/字节交给器官）、写 ``--out``、
``--file`` 路径解析、CLI 参数与输出排版、``python_version`` 等环境字段、``--freq``
语言先验（旧仓本就未实现）。逐条处置见 ``docs/mojibake-forensics.md`` §6。
"""

from __future__ import annotations

from byteproof.core.ledger import Record

from . import chain, probe, spec


def _add(records, basis, rule_id, message, path, evidence=None):
    records.append(
        Record(
            rule_id=rule_id,
            verdict=spec.VERDICTS[rule_id],
            message=message,
            basis=basis.ref(rule_id),
            path=path,
            evidence=evidence or {},
        )
    )


def _require_text(subject):
    text = subject.get("text")
    if not isinstance(text, str):
        raise ValueError("mode=%s 需要 subject.text（已解码字符串）" % (subject.get("mode"),))
    if text == "":
        raise ValueError("subject.text 为空，没有可归因的字符")
    return text


def _codec_list(subject, field):
    value = subject.get(field)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("subject.%s 必须是字符串数组" % field)
    return tuple(value)


def _positive_int(subject, field, default=None):
    value = subject.get(field, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("subject.%s 必须是 >= 1 的整数" % field)
    return value


def _confidence_label(note):
    if note == "single_candidate_in_bounded_search":
        return "有界搜索里只有一条无损候选，区间恒为 1.0（不代表唯一真相）"
    if note == "no_positive_score":
        return "全部候选总分 <= 0，份额区间不可定义（不编造分布）"
    return note


# ================================================================== attr
def _attr(subject, basis):
    text = _require_text(subject)
    top = _positive_int(subject, "top", spec.DEFAULT_TOP)
    ranked, total_chains = chain.search(
        text,
        encoders=_codec_list(subject, "source_enc"),
        decoders=_codec_list(subject, "target_enc"),
    )
    intervals, note = chain.confidence(ranked)
    records = []

    if not ranked:
        _add(
            records,
            basis,
            spec.RULE_ATTR_NO_CANDIDATE,
            "冻结编码集合与链深上限内没有无损候选（不返回空列表冒充成功）",
            "candidates",
            {
                "status": spec.STATUS_NO_CANDIDATE,
                "total_candidates": 0,
                "total_chains": total_chains,
                "max_depth": spec.MAX_DEPTH,
                "notes": ["depth_limit_reached"],
            },
        )
        return records

    for index, entry in enumerate(ranked[:top]):
        _add(
            records,
            basis,
            spec.RULE_ATTR_CANDIDATE,
            "有界候选：%r（路径 %s，链深 %d）" % (entry["result"], entry["path_string"], entry["depth"]),
            "candidates[%d]" % entry["rank"],
            {
                "rank": entry["rank"],
                "result": entry["result"],
                "path": entry["path"],
                "path_string": entry["path_string"],
                "depth": entry["depth"],
                "score": dict(entry["score"]),
                "confidence": intervals[index],
                "note": note,
            },
        )

    if note == "no_positive_score":
        _add(
            records,
            basis,
            spec.RULE_ATTR_CONFIDENCE_DEGENERATE,
            _confidence_label(note),
            "confidence",
            {"note": note, "total_candidates": len(ranked)},
        )
    elif note == "single_candidate_in_bounded_search":
        _add(
            records,
            basis,
            spec.RULE_ATTR_SINGLE_CANDIDATE,
            _confidence_label(note),
            "confidence",
            {"note": note, "total_candidates": len(ranked)},
        )

    if len(ranked) > top:
        _add(
            records,
            basis,
            spec.RULE_ATTR_TRUNCATED,
            "只展示前 %d 条；完整候选数 %d，不受 --top 影响" % (top, len(ranked)),
            "candidates",
            {
                "shown": top,
                "total_candidates": len(ranked),
                "total_chains": total_chains,
            },
        )
    return records


# ================================================================== explain
def _explain(subject, basis):
    text = _require_text(subject)
    ranked, total_chains = chain.search(
        text,
        encoders=_codec_list(subject, "source_enc"),
        decoders=_codec_list(subject, "target_enc"),
    )
    records = []
    if not ranked:
        _add(
            records,
            basis,
            spec.RULE_ATTR_NO_CANDIDATE,
            "没有可重放的候选（explain 不会重新枚举，也不会伪造证明）",
            "candidates",
            {"status": spec.STATUS_NO_CANDIDATE, "total_chains": total_chains},
        )
        return records

    all_candidates = bool(subject.get("all", False))
    vs = subject.get("vs")
    if vs is not None:
        vs = _positive_int(subject, "vs")
    if all_candidates and vs is not None:
        raise ValueError("mode=explain 的 all=true 与 vs 互斥（与旧仓 --vs 只配 --pick 一致）")

    if all_candidates:
        picked = list(range(1, len(ranked) + 1))
    else:
        pick = _positive_int(subject, "pick", 1)
        if pick > len(ranked):
            raise ValueError(
                "subject.pick=%d 越界（候选数 %d）；先看 attr 的候选集" % (pick, len(ranked))
            )
        picked = [pick]

    proofs = {}
    for rank in picked:
        entry = ranked[rank - 1]
        replayed = chain.replay_chain(entry["chain"])
        proofs[rank] = (entry, replayed)
        if replayed["verify"] and replayed["output"] == entry["result"]:
            _add(
                records,
                basis,
                spec.RULE_EXPLAIN_VERIFY,
                "逐步复算通过：%r 经 %s 可达（链深 %d）"
                % (entry["result"], entry["path_string"], entry["depth"]),
                "proofs[%d]" % rank,
                {
                    "rank": rank,
                    "result": entry["result"],
                    "path_string": entry["path_string"],
                    "depth": entry["depth"],
                    "verify": True,
                    "steps": replayed["steps"],
                },
            )
        else:
            failed = replayed["failed_step"]
            _add(
                records,
                basis,
                spec.RULE_EXPLAIN_VERIFY_FAILED,
                "逐步复算失败：第一个不一致处是第 %s 步（证明不可采信）" % (failed,),
                "proofs[%d].step[%s]" % (rank, failed),
                {
                    "rank": rank,
                    "result": entry["result"],
                    "path_string": entry["path_string"],
                    "verify": False,
                    "failed_step": failed,
                    "steps": replayed["steps"],
                },
            )

    if not all_candidates:
        rank = picked[0]
        entry, proof = proofs[rank]
        if vs is None:
            other = 2 if rank == 1 and len(ranked) >= 2 else 1
            if len(ranked) < 2:
                other = None
        else:
            if vs > len(ranked):
                raise ValueError("subject.vs=%d 越界（候选数 %d）" % (vs, len(ranked)))
            other = vs
        if other is None:
            _add(
                records,
                basis,
                spec.RULE_EXPLAIN_DIVERGENCE,
                "候选不足两条，没有可对照的分叉点",
                "divergence",
                {"note": "no_second_candidate", "vs_rank": None},
            )
        else:
            if other == rank:
                raise ValueError("subject.vs 不能等于 subject.pick")
            other_entry = ranked[other - 1]
            other_proof = chain.replay_chain(other_entry["chain"])
            divergence = chain.compare_proofs(proof, other_proof, other, other_entry)
            _add(
                records,
                basis,
                spec.RULE_EXPLAIN_DIVERGENCE,
                "与候选 %d 的第一处差异：%s" % (other, divergence["statement"]),
                "divergence",
                divergence,
            )
    return records


# ================================================================== recover
def _codepoint(char):
    return "U+%04X" % ord(char)


def _triage(text):
    """不可逆类固定顺序：U+FFFD -> 锟斤拷 -> MSVC 填充 -> '?' 截断。"""
    offsets = [index for index, char in enumerate(text) if char == spec.REPLACEMENT_CHAR]
    if offsets:
        return (
            spec.STATUS_LOST,
            spec.REASON_REPLACEMENT_CHAR,
            {
                "step": "decode",
                "offset": offsets[0],
                "replaced_with": _codepoint(spec.REPLACEMENT_CHAR),
                "cause": "errors=replace",
            },
            ["no_invented_characters"],
        )

    if spec.KUN_JIN_KAO in text:
        offset = text.index(spec.KUN_JIN_KAO)
        repeat = 1
        unit_len = len(spec.KUN_JIN_KAO)
        cursor = offset + unit_len
        while text[cursor : cursor + unit_len] == spec.KUN_JIN_KAO:
            repeat += 1
            cursor += unit_len
        return (
            spec.STATUS_LOST,
            spec.REASON_KUN_JIN_KAO,
            {
                "step": "decode",
                "codec": "gbk",
                "offset": offset,
                "repeat": repeat,
                "bytes_hex": spec.KUN_JIN_KAO_BYTES_HEX,
                "replaced_with": _codepoint(spec.REPLACEMENT_CHAR),
                "cause": "errors=replace bytes misread as gbk",
            },
            ["no_invented_characters"],
        )

    if spec.TANG_TANG in text or spec.TUN_TUN in text:
        return (
            spec.STATUS_NOT_MOJIBAKE,
            spec.REASON_MSVC_FILL,
            None,
            ["classified_not_mojibake_no_repair_attempted", "no_invented_characters"],
        )

    if "?" in text:
        offset = text.index("?")
        return (
            spec.STATUS_LOST,
            spec.REASON_ENCODE_TRUNCATED,
            {
                "step": "encode",
                "offset": offset,
                "replaced_with": "?",
                "cause": "errors=replace",
            },
            ["original_character_unrecoverable", "no_invented_characters"],
        )

    return None


def _recover(subject, basis):
    text = _require_text(subject)
    pick = _positive_int(subject, "pick", None)
    if pick is None:
        raise ValueError("mode=recover 需要 subject.pick（不猜最优候选）")

    records = []
    triage = _triage(text)
    if triage is not None:
        status, reason, loss, notes = triage
        rule_id = (
            spec.RULE_RECOVER_NOT_MOJIBAKE
            if status == spec.STATUS_NOT_MOJIBAKE
            else spec.RULE_RECOVER_LOST
        )
        _add(
            records,
            basis,
            rule_id,
            {
                spec.STATUS_LOST: "判死：不可逆（reason=%s），不输出未经验证的修复" % reason,
                spec.STATUS_NOT_MOJIBAKE: "分类为不是乱码（reason=%s），不尝试修复" % reason,
            }[status],
            "verdict",
            {
                "status": status,
                "reason": reason,
                "recovered": None,
                "verify": False,
                "loss": loss,
                "notes": list(notes),
            },
        )
        return records

    ranked, total_chains = chain.search(text)
    if not ranked:
        _add(
            records,
            basis,
            spec.RULE_RECOVER_NO_CANDIDATE,
            "没有候选可还原（reason=%s）" % spec.REASON_NO_CANDIDATE,
            "candidates",
            {
                "status": spec.STATUS_LOST,
                "reason": spec.REASON_NO_CANDIDATE,
                "recovered": None,
                "verify": False,
                "total_candidates": 0,
                "total_chains": total_chains,
                "notes": ["depth_limit_reached"],
            },
        )
        return records

    if pick > len(ranked):
        raise ValueError("subject.pick=%d 越界（候选数 %d）" % (pick, len(ranked)))

    entry = ranked[pick - 1]
    replayed = chain.replay_chain(entry["chain"])
    if not replayed["verify"] or replayed["output"] != entry["result"]:
        failed = replayed["failed_step"]
        _add(
            records,
            basis,
            spec.RULE_EXPLAIN_VERIFY_FAILED,
            "还原复算失败（第 %s 步）：未经验证的修复被抑制" % (failed,),
            "proofs[%d].step[%s]" % (pick, failed),
            {
                "status": spec.STATUS_LOST,
                "reason": spec.REASON_VERIFY_FAILED,
                "pick": pick,
                "recovered": None,
                "verify": False,
                "failed_step": failed,
                "steps": replayed["steps"],
            },
        )
        return records

    _add(
        records,
        basis,
        spec.RULE_RECOVER_RECOVERED,
        "确定性还原：%r 经 %s 可达（已逐步复算）"
        % (replayed["output"], entry["path_string"]),
        "verdict",
        {
            "status": spec.STATUS_RECOVERED,
            "pick": pick,
            "recovered": replayed["output"],
            "path_string": entry["path_string"],
            "depth": entry["depth"],
            "verify": True,
            "steps": replayed["steps"],
        },
    )
    return records


# ================================================================== file
def _file(subject, basis):
    raw = subject.get("bytes_hex")
    if not isinstance(raw, str):
        raise ValueError("mode=file 需要 subject.bytes_hex（十六进制串）")
    data = chain.parse_hex(raw)
    sections = probe.inspect_bytes(data, preset=subject.get("preset"))
    records = []

    bom = sections["bom"]
    _add(
        records,
        basis,
        spec.RULE_FILE_BOM,
        "BOM 检查：%s" % ("命中 " + bom["kind"] + "（偏移 0）" if bom["present"] else "无"),
        "bom",
        dict(bom),
    )
    if sections.get("bom_conflict"):
        content = sections.get("content") or {}
        _add(
            records,
            basis,
            spec.RULE_FILE_BOM_CONFLICT,
            "声明了 %s 的 BOM，但正文按该编码不可解码（两解并存，只列证据）" % bom["kind"],
            "bom.conflict",
            {
                "kind": bom["kind"],
                "body_hex": content.get("body_hex"),
                "as_utf8": content.get("as_utf8"),
                "as_gb18030": content.get("as_gb18030"),
            },
        )

    utf16 = sections.get("utf16_misalignment")
    if utf16 is not None:
        _add(
            records,
            basis,
            spec.RULE_FILE_UTF16_MISALIGNMENT,
            "UTF-16 字节数为奇数（%d），错位一字节才能解出；不自动纠正"
            % utf16["byte_length"],
            "utf16",
            utf16,
        )

    for index, entry in enumerate(sections.get("zip_names", [])):
        _add(
            records,
            basis,
            spec.RULE_FILE_ZIP_NAME,
            "ZIP 中央目录名（flag_bits=%d，按 %s 解释）：%r"
            % (entry["flag_bits"], entry["interpretation"], entry["name"]),
            "zip.names[%d]" % index,
            dict(entry),
        )
        if entry["alternatives"] and not entry["flag_utf8"]:
            _add(
                records,
                basis,
                spec.RULE_FILE_ZIP_NAME_AMBIGUOUS,
                "归档名未置 UTF-8 标志，CP437 与 UTF-8 两解并存（工具不选择）",
                "zip.names[%d].alternative" % index,
                {
                    "raw_name_hex": entry["raw_name_hex"],
                    "interpretation": entry["interpretation"],
                    "alternatives": list(entry["alternatives"]),
                },
            )

    csv_part = sections.get("csv_candidates")
    if csv_part is not None:
        _add(
            records,
            basis,
            spec.RULE_FILE_CSV_CANDIDATE,
            "CSV 候选编码 cp1252/gbk/shift_jis；首行分隔符嗅探 = %r"
            % (csv_part["delimiter"],),
            "csv",
            dict(csv_part),
        )
    return records


# ================================================================== scan
def line_hit(line: str):
    """一行是否命中（旧仓 K9）：输入可读性 < 0.5 且存在净值 >= 0.3、可读性 >= 0.8 的候选。"""
    if not line.strip():
        return None
    line_read = chain.readability(line)
    if line_read >= spec.INPUT_READABILITY_BELOW:
        return None
    ranked, total_chains = chain.search(line)
    qualifying = []
    for entry in ranked:
        result_read = entry["score"]["readability"]
        if result_read >= spec.CANDIDATE_READABILITY_AT_LEAST and (
            result_read - line_read >= spec.READABILITY_GAIN_AT_LEAST
        ):
            qualifying.append(
                {
                    "result": entry["result"],
                    "path_string": entry["path_string"],
                    "depth": entry["depth"],
                    "readability": result_read,
                }
            )
    if not qualifying:
        return None
    return {
        "input_readability": line_read,
        "candidates": qualifying,
        "total_chains": total_chains,
    }


def _scan(subject, basis):
    files = subject.get("files")
    if not isinstance(files, list):
        raise ValueError("mode=scan 需要 subject.files（[{path, text}]）")
    baseline = subject.get("baseline")
    if not isinstance(baseline, dict) or not isinstance(baseline.get("files", []), list):
        raise ValueError('mode=scan 需要 subject.baseline（对象且含 "files" 数组）')
    existing = subject.get("existing_paths")
    if not isinstance(existing, list) or not all(isinstance(item, str) for item in existing):
        raise ValueError(
            "mode=scan 需要 subject.existing_paths（基线路径的存在性由输入层提供，器官不读盘）"
        )

    allowed = {}
    baselined_paths = set()
    for entry in baseline.get("files", []):
        if not isinstance(entry, dict):
            raise ValueError("baseline.files 的每一项必须是对象")
        rel = entry.get("path")
        if not rel or not isinstance(rel, str):
            continue
        allowed[rel] = entry.get("allowed_hits") or []
        baselined_paths.add(rel)

    records = []
    hits = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("files 的每一项必须是 {path, text}")
        rel = item.get("path")
        text = item.get("text")
        if not isinstance(rel, str) or not isinstance(text, str):
            raise ValueError("files 的每一项必须是 {path: str, text: str}")
        for number, line in enumerate(text.splitlines(), 1):
            evidence = line_hit(line)
            if evidence is None:
                continue
            hits.append((rel, number, evidence))

    existing_set = set(existing)
    for rel, number, evidence in hits:
        if rel in allowed:
            _add(
                records,
                basis,
                spec.RULE_SCAN_BASELINED,
                "已登记命中（基线允许 %d 条记录），不阻断" % len(allowed[rel]),
                "%s:%d" % (rel, number),
                dict(evidence),
            )
        else:
            _add(
                records,
                basis,
                spec.RULE_SCAN_NEW,
                "新增命中：这一行在冻结集合内存在可读性更高的无损候选",
                "%s:%d" % (rel, number),
                dict(evidence),
            )

    stale = sorted(path for path in baselined_paths if path not in existing_set)
    for path in stale:
        _add(
            records,
            basis,
            spec.RULE_SCAN_STALE,
            "基线登记的文件已不在磁盘上（不影响阻断）",
            "baseline.stale[%s]" % path,
            {"path": path},
        )

    if not hits and not stale:
        _add(
            records,
            basis,
            spec.RULE_SCAN_CLEAN,
            "干净语料：%d 个文件全部零命中" % len(files),
            "scan",
            {
                "files_scanned": len(files),
                "new": 0,
                "baselined": 0,
                "stale": 0,
            },
        )
    return records


# ================================================================== 入口
def evaluate(subject, basis):
    mode = subject.get("mode")
    if mode not in spec.MODES:
        raise ValueError(
            "subject.mode 非法：%r（允许 %s）" % (mode, " / ".join(spec.MODES))
        )
    if mode == "attr":
        return _attr(subject, basis)
    if mode == "explain":
        return _explain(subject, basis)
    if mode == "recover":
        return _recover(subject, basis)
    if mode == "file":
        return _file(subject, basis)
    return _scan(subject, basis)