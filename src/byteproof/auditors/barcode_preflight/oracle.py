"""M5：oracle 回读对照的三态分类（``consistent`` / ``m3_stricter`` / ``m3_laxer``）。

分类器不重算 M3，也不改 verdict：它只接收已经算好的 ``m3_verdict`` 与解码结果。
``m3_laxer`` 是 bug 通道，``m3_stricter`` 是 known-disagreements；两者永不合并。
"""

from __future__ import annotations

CONSISTENT = "consistent"
M3_STRICTER = "m3_stricter"
M3_LAXER = "m3_laxer"
AGREEMENTS = (CONSISTENT, M3_STRICTER, M3_LAXER)

NOTE_STRICTER = "M3 判有风险，oracle 却解得出来 —— 可能是假阳性，记入 known-disagreements"
NOTE_LAXER = "M3 判干净，oracle 解不出来 —— bug 通道：必须修 M3 判定，不许记入 known-disagreements"


def m3_verdict(findings):
    """只由 M3 findings 派生 verdict（``pass|warn|fail``）。"""
    levels = [finding.get("severity") for finding in findings if finding.get("module") == "M3"]
    if "error" in levels:
        return "fail"
    if "warn" in levels:
        return "warn"
    return "pass"


def risky_finding_ids(findings):
    levels = ("warn", "error")
    return sorted(
        {
            finding.get("id")
            for finding in findings
            if finding.get("module") == "M3" and finding.get("severity") in levels
        }
    )


def _entry(agreement, verdict, decoded, finding_ids, note):
    return {
        "agreement": agreement,
        "m3_verdict": verdict,
        "oracle": "decoded" if decoded else "not-decoded",
        "finding_ids": sorted(finding_ids),
        "note": note,
    }


def classify(verdict, decoded, finding_ids=()):
    """返回 ``(agreement, known_disagreements, bugs)``；每个组合恰好落一处。"""
    if verdict not in ("pass", "warn", "fail"):
        raise ValueError("m3_verdict 必须是 pass/warn/fail，收到 %r" % (verdict,))
    risky = verdict in ("warn", "fail")
    if decoded and risky:
        return M3_STRICTER, [_entry(M3_STRICTER, verdict, decoded, finding_ids, NOTE_STRICTER)], []
    if (not decoded) and not risky:
        return M3_LAXER, [], [_entry(M3_LAXER, verdict, decoded, finding_ids, NOTE_LAXER)]
    return CONSISTENT, [], []