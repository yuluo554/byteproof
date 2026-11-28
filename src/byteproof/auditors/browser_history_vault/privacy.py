"""隐私门禁（照搬旧仓 ``privacy.py``：模块①–⑤共用的唯一生产侧实现点）。

两种语义刻意不同（照搬）：
- **私密（private）**：完全排除——输出零出现，**连统计都不进**（归档也不落库）；
- **敏感（sensitive）**：保留统计，仅**打码呈现**（归档保留，展示层掩码）。

匹配语义（K7）：``host == 项`` 或 ``host`` 以 ``"." + 项`` 结尾（子域一并命中）；
**不是子串匹配**。私密优先于敏感。私密主机走到输出面 = 门禁被绕过，**直接报错**
（掩码会把"私密泄漏"退化成"显示有点怪"，这里要的是当场红）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, List, Sequence, Tuple

PRIVATE = "private"
SENSITIVE = "sensitive"
PUBLIC = "public"


class PrivacyError(ValueError):
    """隐私分类的输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""


def host_matches_entry(host: str, entry: str) -> bool:
    """K7 的匹配语义；公开成函数是因为隐私分类与检索 --domain 两个消费者共用。"""
    normalized = str(entry).strip().lower()
    if not normalized:
        return False
    return host == normalized or host.endswith("." + normalized)


def classify_host(host: str, private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> str:
    """`private` / `sensitive` / `public`。私密优先于敏感。"""
    if not isinstance(host, str) or not host:
        raise PrivacyError("privacy-host", "host 必须是非空字符串，实际是 %r" % (host,))
    normalized = host.strip().lower()
    for entry in private_domains or ():
        if host_matches_entry(normalized, entry):
            return PRIVATE
    for entry in sensitive_domains or ():
        if host_matches_entry(normalized, entry):
            return SENSITIVE
    return PUBLIC


def is_excluded(kind: str) -> bool:
    return kind == PRIVATE


def keep_visible(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> List[Dict[str, Any]]:
    """过门禁后的可见行：私密剔除；敏感**保留**（只打码，不剔除）。"""
    visible: List[Dict[str, Any]] = []
    for row in rows:
        if classify_host(row["host"], private_domains, sensitive_domains) != PRIVATE:
            visible.append(row)
    return visible


def mask_host(host: str) -> str:
    """敏感主机掩码：保留最后两段，其余每段替换为 `***`；不足三段 → `***`。"""
    if not isinstance(host, str) or not host:
        raise PrivacyError("privacy-host", "host 必须是非空字符串，实际是 %r" % (host,))
    parts = host.strip().lower().split(".")
    if len(parts) < 3:
        return "***"
    return ".".join(["***"] * (len(parts) - 2) + parts[-2:])


def fingerprint(host: str) -> str:
    """稳定指纹（不可逆）：sha256 前 8 位纯函数，同输入永远同输出。"""
    return "h-" + hashlib.sha256(host.strip().lower().encode("utf-8")).hexdigest()[:8]


def redact_text(text: str, host: str, private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> str:
    """URL/标题里可能回显主机名的文本按主机分类处理；私密直接报错。"""
    kind = classify_host(host, private_domains, sensitive_domains)
    if kind == PRIVATE:
        raise PrivacyError("privacy-private-in-output", "私密主机 %r 走到了输出面（应先经 keep_visible 剔除）" % (host,))
    if kind == SENSITIVE:
        return str(text).replace(host, mask_host(host))
    return str(text)


def display_host(host: str, private_domains: Sequence[str], sensitive_domains: Sequence[str]) -> str:
    """输出面的主机呈现：公开原样小写；敏感掩码；私密直接报错。"""
    kind = classify_host(host, private_domains, sensitive_domains)
    if kind == PRIVATE:
        raise PrivacyError("privacy-private-in-output", "私密主机 %r 走到了输出面（应先经 keep_visible 剔除）" % (host,))
    if kind == SENSITIVE:
        return mask_host(host)
    return host.strip().lower()


def summarize(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Dict[str, Any]:
    """分类汇总（计数单位 = 访问记录数）：排除数 / 打码数 / 逐主机分布。"""
    excluded = 0
    masked = 0
    private_hosts: Dict[str, int] = {}
    sensitive_hosts: Dict[str, int] = {}
    for row in rows:
        host = row["host"]
        kind = classify_host(host, private_domains, sensitive_domains)
        if kind == PRIVATE:
            excluded += 1
            private_hosts[host] = private_hosts.get(host, 0) + 1
        elif kind == SENSITIVE:
            masked += 1
            sensitive_hosts[host] = sensitive_hosts.get(host, 0) + 1
    return {
        "excluded_visit_records": excluded,
        "masked_visit_records": masked,
        "private_host_counts": _sorted_counts(private_hosts),
        "sensitive_host_counts": _sorted_counts(sensitive_hosts),
    }


def classify_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    private_domains: Sequence[str],
    sensitive_domains: Sequence[str],
) -> Tuple[List[Dict[str, Any]], int]:
    """返回（可见行, 被排除的私密记录数）——归档器用的单点入口。"""
    visible: List[Dict[str, Any]] = []
    excluded = 0
    for row in rows:
        if classify_host(row["host"], private_domains, sensitive_domains) == PRIVATE:
            excluded += 1
        else:
            visible.append(row)
    return visible, excluded


def _sorted_counts(mapping: Dict[str, int]) -> Dict[str, int]:
    return {key: mapping[key] for key in sorted(mapping)}
