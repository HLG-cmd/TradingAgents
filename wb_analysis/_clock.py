# lifecycle: reusable
# created: 2026-10-21
"""唯一时间源（Single source of truth for time）。

背景
----
本项目是 point-in-time 研究流水线，"用哪一天"直接决定报告对错。历史上同一类 bug
已经修过两次：

* ``collect.py`` 的 ``--date`` 默认值原为 ``dt.date.today()``（＝本机日期），
  2026-10-11 修正为纽约时区；
* ``_thresholds.py`` 的期权时点分支曾把 ``datetime.now()`` 写死在函数体里，
  导致该分支**无法被测试**。

所以从今天起：**任何取数、报告、落盘时间都必须经过本模块**，
禁止在别处直接调用 ``datetime.now()`` / ``dt.datetime.now()`` / ``date.today()``。
``tests/test_no_naive_clock.py`` 会把这条约定变成可执行门禁（基线 + 禁止新增）。

区分两类时间
------------
* **数据时点**（as-of / market date）：决定"看到的是哪一天的市场"，必须用市场时区。
  用 :func:`market_date` / :func:`iso_today` / :func:`as_of_date`。
* **记录时刻**（stamp）：本次运行发生在什么时候，仅用于留痕，允许取当前真实时间，
  但同样要带时区，不要用本机裸时间。用 :func:`now` / :func:`stamp`。
"""

from __future__ import annotations

import datetime as dt
import zoneinfo

__all__ = [
    "MARKET_TZ",
    "CN_TZ",
    "now",
    "market_date",
    "iso_today",
    "stamp",
    "as_of_date",
]

# 美股：纽约时区。机器在哪儿、本机时钟设成什么，都不影响结果。
MARKET_TZ = zoneinfo.ZoneInfo("America/New_York")
# A 股 / 港股 / 中债：东八区。
CN_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def now(tz: dt.tzinfo = MARKET_TZ) -> dt.datetime:
    """带时区的当前时刻。默认纽约（美股口径）。"""
    return dt.datetime.now(tz)


def market_date(tz: dt.tzinfo = MARKET_TZ) -> dt.date:
    """当前**市场日期**。``--date`` 的缺省值只应该用它，不要用本机日期。"""
    return now(tz).date()


def iso_today(tz: dt.tzinfo = MARKET_TZ) -> str:
    """市场日期的 ISO 字符串。替代 ``dt.date.today().isoformat()``。"""
    return market_date(tz).isoformat()


def stamp(fmt: str = "%Y%m%d_%H%M%S", tz: dt.tzinfo = MARKET_TZ) -> str:
    """记录时刻字符串。用于备份名、``sealed_at`` 等留痕场景。"""
    return now(tz).strftime(fmt)


def as_of_date(explicit: str | None, tz: dt.tzinfo = MARKET_TZ) -> str:
    """解析 ``--date`` 参数：显式值优先，缺省取**市场日期**（不是本机日期）。"""
    if explicit:
        return explicit
    return iso_today(tz)
