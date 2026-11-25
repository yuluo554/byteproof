"""PEP 561 类型标记：classifier 声称 ``Typing :: Typed``，仓里就得有让它是真话的东西。

判据来源：**PEP 561 – Distributing and Packaging Type Information**
（https://peps.python.org/pep-0561/）。类型检查器只认两条：

1. 包目录（或其父目录）里存在 ``py.typed`` 标记文件 —— 源码态对应
   ``src/errcode_atlas/py.typed``；
2. 标记文件必须作为**包数据**随 wheel 安装进 site-packages —— 对应
   ``pyproject.toml`` 的 ``[tool.setuptools.package-data]`` 声明；
   只进源码树、不进打包配置 = 装出来的包仍然是假 Typed。

第 2 条的**装态验证**（pip install 后 ``importlib.resources`` 能看到标记）不进常跑
套件：它要么触发构建隔离联网下载，要么 ``--no-build-isolation`` 依赖环境里恰好有
setuptools —— 两条都会把「离线 CI 边界」（三轮 CI 红换来的）捅破。它由两处执行期
验收覆盖并留痕：``pip wheel`` 产物内含 ``errcode_atlas/py.typed`` 的核对（二次迭代
批 1），以及干净 venv 安装后的中立目录复验（纪律条款 4）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / "src" / "errcode_atlas"


def _package_data_patterns() -> list[str]:
    """读 ``[tool.setuptools.package-data]`` 下 ``errcode_atlas`` 的模式表。

    ``tomllib`` 是 3.11+ 才有的标准库 —— 与 ``tests/test_version_floor.py`` 同款退化
    路径：读不了就按行解析（只认本项目 ``key = ["...", ...]`` 单行数组形态），
    读不出来就 FAIL，不静默跳过。
    """
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    try:
        import tomllib
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]

    if tomllib is not None:
        node = tomllib.loads(text)["tool"]["setuptools"]["package-data"]["errcode_atlas"]
        return node if isinstance(node, list) else [node]

    # 退化路径（3.8）：定位 section 后抓 errcode_atlas 行内的字符串字面量
    lines = text.split("\n")
    start = next(
        i for i, line in enumerate(lines) if line.strip() == "[tool.setuptools.package-data]"
    )
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("["):  # 进入下一个 section，没找到目标键
            break
        match = re.match(r'^errcode_atlas\s*=\s*\[(.*)\]\s*$', stripped)
        if match:
            return re.findall(r'"([^"]+)"', match.group(1))
    raise AssertionError("pyproject.toml 里读不到 package-data 的 errcode_atlas 模式表")


def test_py_typed_marker_exists_in_source_tree() -> None:
    """PEP 561 判据一：源码态包目录里有 ``py.typed`` 标记文件。"""
    marker = PKG / "py.typed"
    assert marker.is_file(), (
        "src/errcode_atlas/py.typed 不存在 —— classifier 声称 Typing::Typed 而无标记，"
        "类型检查器不会把本包当 Typed（PEP 561）"
    )


def test_package_data_declares_py_typed() -> None:
    """PEP 561 判据二：标记文件必须在打包配置里声明，否则 wheel 里没有它。"""
    patterns = _package_data_patterns()
    assert any("py.typed" in pattern for pattern in patterns), (
        f"[tool.setuptools.package-data] 未声明 py.typed（现值 {patterns!r}）—— "
        "标记进不了 wheel，装态仍然是假 Typed"
    )
