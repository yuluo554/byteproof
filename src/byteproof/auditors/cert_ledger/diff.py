"""基线差异（旧仓 ``render._diff_against``）：added / removed / rotated。

**rotated** = 同名（``subject_der_sha256``）同公钥（``spki_sha256``）换了指纹：
密钥还在、证书换了，通常就是一次重签。公钥也换了的按 removed + added 计，
不叫 rotation——两张证书只剩一个显示字符串相同。
"""

from __future__ import annotations


def certificate_rows(ledger: dict) -> list:
    rows = []
    for record in ledger.get("certs") or []:
        if not isinstance(record, dict):
            continue
        subject = record.get("subject")
        display = subject.get("display", "") if isinstance(subject, dict) else str(subject or "")
        der = subject.get("der_sha256", "") if isinstance(subject, dict) else ""
        rows.append(
            {
                "fingerprint_sha256": str(record.get("fingerprint_sha256", "")),
                "spki_sha256": str(record.get("spki_sha256", "")),
                "subject": display,
                "subject_der_sha256": der,
            }
        )
    return sorted(rows, key=lambda row: row["fingerprint_sha256"])


def _as_row(value) -> dict:
    if not isinstance(value, dict):
        return {
            "fingerprint_sha256": "",
            "spki_sha256": "",
            "subject": "",
            "subject_der_sha256": "",
        }
    return {
        "fingerprint_sha256": str(value.get("fingerprint_sha256", "")),
        "spki_sha256": str(value.get("spki_sha256", "")),
        "subject": str(value.get("subject", "")),
        "subject_der_sha256": str(value.get("subject_der_sha256", "")),
    }


def diff_against(baseline, certificates: list) -> dict:
    """对一份旧报告做 added/removed/rotated；基线形状不对 -> ``ValueError``（退出码 2）。"""
    if not isinstance(baseline, dict):
        raise ValueError("subject.baseline 必须是对象（旧报告）")
    kind = baseline.get("kind")
    if kind not in (None, "report"):
        raise ValueError("subject.baseline.kind 必须是 report（收到 %r）" % (kind,))
    raw = baseline.get("certificates", [])
    if not isinstance(raw, list):
        raise ValueError("subject.baseline.certificates 必须是数组")
    before = [_as_row(row) for row in raw]
    after = list(certificates)

    before_by_fingerprint = {row["fingerprint_sha256"]: row for row in before}
    after_by_fingerprint = {row["fingerprint_sha256"]: row for row in after}

    added = [
        row
        for fingerprint, row in sorted(after_by_fingerprint.items())
        if fingerprint not in before_by_fingerprint
    ]
    removed = [
        row
        for fingerprint, row in sorted(before_by_fingerprint.items())
        if fingerprint not in after_by_fingerprint
    ]

    rotated = []
    removed_left = []
    added_used = set()

    removed_groups: dict = {}
    for row in removed:
        removed_groups.setdefault((row["subject_der_sha256"], row["spki_sha256"]), []).append(row)
    added_groups: dict = {}
    for row in added:
        added_groups.setdefault((row["subject_der_sha256"], row["spki_sha256"]), []).append(row)

    for group in sorted(removed_groups):
        gone = removed_groups[group]
        fresh = added_groups.get(group) or []
        if not fresh:
            removed_left.extend(gone)
            continue
        for old_row, new_row in zip(gone, fresh):
            rotated.append(
                {
                    "subject": new_row["subject"],
                    "subject_der_sha256": new_row["subject_der_sha256"],
                    "spki_sha256": new_row["spki_sha256"],
                    "from": old_row["fingerprint_sha256"],
                    "to": new_row["fingerprint_sha256"],
                }
            )
            added_used.add(new_row["fingerprint_sha256"])
        removed_left.extend(gone[len(fresh) :])

    added_left = [row for row in added if row["fingerprint_sha256"] not in added_used]
    return {
        "added": added_left,
        "removed": sorted(removed_left, key=lambda row: row["fingerprint_sha256"]),
        "rotated": sorted(rotated, key=lambda row: (row["subject_der_sha256"], row["to"])),
    }