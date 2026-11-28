"""规范化器纯判定面（照搬旧仓 ``normalizer.py`` 的纯函数部分）。

sqlite 只读打开、schema 校验、文件读取属输入层（D18 `input` 域）；本模块只保留
字段契约、主机解析、去重键与规范化序。主机解析刻意不引 ``urllib.parse``：要的是
"固定、可复算、跨版本不漂移"的一小段规则。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

CANONICAL_FIELDS: Tuple[str, ...] = (
    "url",
    "title",
    "host",
    "visit_time_us",
    "source_browser",
    "source_profile",
    "transition",
    "visit_duration_us",
)

#: 规范化排序键 = visit 去重键（与 visits UNIQUE 约束同一组字段）。
CANONICAL_SORT_FIELDS: Tuple[str, ...] = (
    "visit_time_us",
    "url",
    "source_browser",
    "source_profile",
)

KNOWN_BROWSERS: Tuple[str, ...] = ("chrome", "edge")

_PROFILE_DIR_RE = re.compile(r"^(Default|Profile \d+|Guest Profile|System Profile)$")

DEFAULT_PROFILE = "Default"


class NormalizeError(ValueError):
    """输入不可用（继承 ValueError：CLI 统一转退出码 2）。"""


def host_of(url: str) -> str:
    """从 URL 字符串取主机名（小写；去 userinfo 与端口）。与生成侧是两份独立实现。"""
    if not isinstance(url, str) or not url:
        raise NormalizeError("url-shape", "url 必须是非空字符串，实际是 %r" % (url,))
    rest = url.split("://", 1)[1] if "://" in url else url
    authority = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return authority.rsplit("@", 1)[-1].split(":", 1)[0].strip().lower()


def profile_name_of(browser_dir_name: str) -> str:
    """由目录名推断 profile 名；不匹配已知模式时回落 Default 并由调用方说明。"""
    name = str(browser_dir_name)
    if _PROFILE_DIR_RE.match(name):
        return name
    return DEFAULT_PROFILE


def canonical_sort_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    return tuple(row[field] for field in CANONICAL_SORT_FIELDS)


def normalize_rows(rows: Iterable[Dict[str, Any]], *, on_duplicate: str = "dedupe") -> List[Dict[str, Any]]:
    """校验字段集合 + 处理重复去重键 + 按规范序排序。

    ``"dedupe"``（生产默认）：确定性保留规范序第一条 + 显式计数交调用方；
    ``"error"``（对撞/校验用）：直接报错——冻结数据出现重复键意味着口径坏了，
    不能被"去重"掩盖过去。
    """
    if on_duplicate not in ("dedupe", "error"):
        raise NormalizeError("normalize-mode", "未知的重复处理方式 %r" % (on_duplicate,))
    collected = list(rows)
    seen: Dict[Tuple[Any, ...], str] = {}
    unique: List[Dict[str, Any]] = []
    for row in collected:
        missing = [field for field in CANONICAL_FIELDS if field not in row]
        if missing:
            raise NormalizeError("row-shape", "行缺字段 %s：%r" % (", ".join(missing), row))
        key = canonical_sort_key(row)
        if key in seen:
            if on_duplicate == "error":
                raise NormalizeError(
                    "row-duplicate",
                    "规范化导出出现重复的 visit 去重键（会让归档幂等静默失效）：%s" % (key,),
                )
            continue
        seen[key] = str(row.get("url"))
        unique.append(row)
    unique.sort(key=canonical_sort_key)
    return unique
