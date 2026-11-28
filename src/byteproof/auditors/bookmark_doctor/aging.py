"""长期未访问画像（照搬旧仓 ``src/bookmark_doctor/aging.py``）。

口径（照搬）：浏览器不导出真实访问记录，以 ``add_date``（添加时间）**近似**
"未访问时长"——代理指标，报告必须显式注明，不得表述为实测。

- 分档阈值取 subject ``aging.tiers_days``（引擎零内联、零默认值：缺失/非法 →
  ``AgingConfigError``）；tiers_days = [365, 730, 1095] → "1年+ / 2年+ / 3年+"
  （其余为 1年内）；档位标签由阈值换算，不写死年份字面量；
- ``add_date=None`` 的条目**不参与分档**，单列 "添加时间未知" 计数（缺失不猜补）；
- 分档判定用 ``aging_date``（subject 提供的参考日期）与 add_date 的日历日差
  ——不用 ``time.time()``，保产物确定性。
"""

from __future__ import annotations

import datetime
from typing import List, Tuple

_AGING_KEY = "aging"
_TIERS_KEY = "tiers_days"

_TIER_LABEL_YEARS = "%d年+"
_TIER_LABEL_WITHIN = "1年内"


class AgingConfigError(ValueError):
    """分档阈值缺失/非法（引擎零默认值纪律）。"""


def load_aging_tiers(ruleset):
    """ruleset dict → 升序 int 分档天数列表（空/非升序/非正 int → AgingConfigError）。"""
    aging = ruleset.get(_AGING_KEY)
    if not isinstance(aging, dict):
        raise AgingConfigError("ruleset 缺少 aging 对象")
    tiers = aging.get(_TIERS_KEY)
    if not isinstance(tiers, list) or not tiers:
        raise AgingConfigError("ruleset 缺少 aging.tiers_days（非空列表）")
    for value in tiers:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AgingConfigError("aging.tiers_days 含非正整数项: %r" % (value,))
    if any(b <= a for a, b in zip(tiers, tiers[1:])):
        raise AgingConfigError("aging.tiers_days 必须严格升序: %r" % (tiers,))
    return list(tiers)


def _days_between(aging_date, add_date):
    """(date, epoch 秒) → 相差的整天数；add_date 早于参考日为正。"""
    moment = datetime.datetime.fromtimestamp(add_date, tz=datetime.timezone.utc).date()
    return (aging_date - moment).days


def _tier_label(tier_days: int, first_tier_days: int) -> str:
    """档位标签：N 年+（N 由阈值换算，非字面量内联）。"""
    years = tier_days // first_tier_days
    return _TIER_LABEL_YEARS % years


def build_aging_profile(bookmarks, tiers_days: List[int], aging_date):
    """UIR 条目 + 分档阈值 + 参考日 → 画像（计数 + 逐条分档归属）。"""
    if not isinstance(aging_date, datetime.date):
        raise TypeError("aging_date 须为 datetime.date（确定性参考日）")
    tiers = []
    for tier_days in tiers_days:
        tiers.append({"tier": _tier_label(tier_days, tiers_days[0]), "min_days": tier_days, "count": 0, "ids": []})
    within = {"tier": _TIER_LABEL_WITHIN, "count": 0, "ids": []}
    unknown = {"count": 0, "ids": []}
    for bookmark in bookmarks:
        add_date = bookmark.get("add_date")
        if add_date is None:
            unknown["count"] += 1
            unknown["ids"].append(bookmark["id"])
            continue
        if not isinstance(add_date, int) or isinstance(add_date, bool):
            raise ValueError("add_date 须为 epoch 秒 int 或 null: %r" % (bookmark["id"],))
        days = _days_between(aging_date, add_date)
        placed = False
        # 分档取"满足的最高档"（2年+ 的条目不得落 1年+）：从高档往低档判
        for index in range(len(tiers_days) - 1, -1, -1):
            if days >= tiers_days[index]:
                tiers[index]["count"] += 1
                tiers[index]["ids"].append(bookmark["id"])
                placed = True
                break
        if not placed:
            within["count"] += 1
            within["ids"].append(bookmark["id"])
    return {
        "as_of_date": aging_date.isoformat(),
        "tiers": tiers,
        "within": within,
        "unknown_add_date": unknown,
        "note": "以添加时间近似未访问；浏览器不导出真实访问记录",
    }


def aging_assignments(profile) -> List[Tuple[str, str, dict]]:
    """画像 → [(kind, key, tier_dict)] 供账本行生成（kind ∈ tier/within/unknown）。"""
    out = []
    for tier in profile["tiers"]:
        out.append(("tier", tier["tier"], tier))
    out.append(("within", profile["within"]["tier"], profile["within"]))
    out.append(("unknown", "unknown", profile["unknown_add_date"]))
    return out
