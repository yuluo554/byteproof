"""编目源钉定清单入仓（`data/catalog-sources.json`）。

背景（二次迭代 D4）：抽源时刻的钉定值（repo ref / 网页 sha256 / fetched_at）原本只存在于
``_headers/SOURCES.json``，而 ``_headers/`` 被 `.gitignore` 封（本机原料目录）——钉定信息
困在本机，仓库里没有任何东西阻止「重跑 fetch 拿到上游新 commit、与 YAML 出处失配」。

判据四条：在位 / 仓库型源的 ref·sha256 形态 / fetched_at 写死（**这是防漂移的合法写死**
——它钉的是"抽源时刻"，不该随时间变）/ 与 ``_headers`` 原件逐字节一致（本机有原件时）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED = REPO_ROOT / "data" / "catalog-sources.json"
HEADERS = REPO_ROOT / "_headers" / "SOURCES.json"

#: 抽源时刻（2026-11-01）。写死是**判据的一部分**：这份清单钉的是历史事实，
#: 值变了 = 有人重跑过 fetch 或改写历史 —— 必须红。
FETCHED_AT = "2026-11-01T11:12:21Z"


def _sources() -> list[dict]:
    data = json.loads(PINNED.read_text(encoding="utf-8"))
    return data["sources"]


def test_catalog_sources_pinned_file_exists_with_seven_sources() -> None:
    assert PINNED.is_file(), "data/catalog-sources.json 不在仓 —— 钉定清单仍困在 _headers/（D4 未修）"
    assert len(_sources()) == 7, f"sources 应为 7 个（errno/signal/xnu/node/sysexits 全家），实测 {len(_sources())}"


@pytest.mark.parametrize("field, pattern", [("ref", re.compile(r"^[0-9a-f]{40}$")), ("sha256", re.compile(r"^[0-9a-f]{64}$"))])
def test_repo_sources_ref_and_sha256_are_full_hashes(field: str, pattern: "re.Pattern[str]") -> None:
    """仓库型源（repo 非空）必须钉**完整** 40 位 ref / 64 位 sha256 —— 前 8 位只配进文档表。"""
    bad: list[str] = []
    for src in _sources():
        if not src.get("repo"):
            continue
        value = src.get(field, "")
        if not pattern.fullmatch(value):
            bad.append(f"{src['id']}.{field}={value!r}")
    assert not bad, f"仓库型源的 {field} 不是完整十六进制钉定值：{bad}"


def test_repo_sources_fetched_at_non_empty_and_all_pinned() -> None:
    fetched = [src.get("fetched_at", "") for src in _sources()]
    assert all(fetched), f"fetched_at 有空值：{[(s['id'], s.get('fetched_at')) for s in _sources()]}"
    drifted = [s["id"] for s, f in zip(_sources(), fetched) if f != FETCHED_AT]
    assert not drifted, f"fetched_at 漂离抽源时刻 {FETCHED_AT}：{drifted} —— 钉定清单被改写（防漂移判据）"


@pytest.mark.skipif(not HEADERS.is_file(), reason="本机原料 _headers/SOURCES.json 不存在（.gitignore 封）。跑 tools/fetch_sources.py --out _headers 后可验")
def test_pinned_copy_matches_headers_original_byte_for_byte() -> None:
    """入仓副本必须与 _headers 原件**逐字节一致** —— 不是重新序列化后的「语义相同」。"""
    assert PINNED.read_bytes() == HEADERS.read_bytes(), (
        "data/catalog-sources.json 与 _headers/SOURCES.json 字节不一致 —— "
        "复制后被本地重新生成/改写过，出处失配"
    )
