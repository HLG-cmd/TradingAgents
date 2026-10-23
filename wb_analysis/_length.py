# lifecycle: reusable
# created: 2026-10-24
# usage: from wb_analysis._length import MIN_CHARS_ANALYST, MIN_CHARS_DECISION, MAX_CHARS   （库；不单独运行）
"""角色稿篇幅门禁的**唯一定义源**。

## 为什么单独成模块（2026-10-24）

此前 `_lint_drafts.py`（判据）与 `_role_prompt.py`（给角色的提示词文案）各写一份
「4,000 / 6,000」，改一处必漏另一处 —— 与 `ok_of` 双判据、quant 统计函数重复是同一类漂移。
抽成零依赖模块后，两边都从这里取。

## 为什么分档（实测依据，不是拍脑袋）

GOOG_2026-10-23 的 12 份稿全部落在 **4,151–4,797**，距 4,000 下限的**中位余量只有 401 字符（10%）**
—— 下限成了 binding，在**驱动长度**而不是信息驱动。

而 `manager.md` 的自然产出是 **3,226 字符**（判断型角色，不再铺一遍数据），
为过 4,000 硬补了 925 字；若无材料可补就会滑向复述，与铁律 53「篇幅看信息密度」自相矛盾。

⇒ 按职责分档：

| 档 | 角色 | 下限 | 建议区间 |
|---|---|---|---|
| 分析师 / 辩论 | market、fundamentals、news、sentiment、bull、bear | **4,000** | 4,000–4,800 |
| 决策类 | manager、trader、三风控、portfolio_manager | **3,000** | 3,000–3,800 |

上限统一 **5,000**（实测最大 4,797；原 6,000 等于没有上限）。
"""
from __future__ import annotations

__all__ = [
    "DECISION_ROLE_FILES",
    "MAX_CHARS",
    "MIN_CHARS_ANALYST",
    "MIN_CHARS_DECISION",
    "bounds_for",
]

#: 分析师 / 辩论席的下限（证据密度足够，实测都写得满）。
MIN_CHARS_ANALYST = 4000

#: 决策类下限（职责是「在既有证据上判断」，不是再铺一遍数据）。
MIN_CHARS_DECISION = 3000

#: 统一上限，超过判「偏长」。
MAX_CHARS = 5000

#: 决策类角色文件名（`manager` / `trader` / 三风控 / 组合经理）。
DECISION_ROLE_FILES = frozenset({
    "manager.md",
    "trader.md",
    "aggressive.md",
    "conservative.md",
    "neutral.md",
    "portfolio_manager.md",
})


def bounds_for(filename: str) -> tuple[int, int]:
    """按角色文件名返回 `(下限, 建议上限)`。

    `建议上限` = 下限 + 800（4,000→4,800 / 3,000→3,800），仅用于文案提示；
    真正的硬上限是 `MAX_CHARS`。
    """
    lo = MIN_CHARS_DECISION if filename in DECISION_ROLE_FILES else MIN_CHARS_ANALYST
    return lo, lo + 800
