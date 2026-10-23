# lifecycle: reusable
# created: 2026-10-23
# usage: from wb_analysis._fmt import fnum, pct_str, ystr, wcode_of, compact_series   （库；不单独运行）
"""采集/派生层共用的**纯格式化工具**（唯一定义源）。

## 为什么抽出这个模块（2026-10-23）

同一批小工具此前在 3~4 个文件里各写一份，且**已经分叉**（不是"风格重复"，是行为不一致）：

| 工具 | 原重复处 | 分叉情况 |
|---|---|---|
| `fnum` | `collect_a_stock` / `collect_a_etf`（两份逐字相同）+ `_derive_a_etf`（**语义不同**） | 前两者「整串转 float」；后者「取第一个数值 token」。`"1.424 (偏离度: +0.56%)"` 只有后者能解析 |
| `wcode_of` | `collect_a_stock.map_wcode` / `collect_a_etf._wcode_of` | 个股版不认 `5/9` 开头与 `.SH` 后缀 ⇒ 把 `518880` 原样传给 westock（正是 2026-10-21 那次假绿的成因）；ETF 版不认已带 `sh/sz` 前缀的输入 |
| `compact_series` | `collect.py._compact_series` / `collect_a_stock.compact_series` | 后者**缺少未收盘 bar 剔除**（铁律 2） |

## ⚠️ 两个**不能合并**的同名函数（合并即口径事故）

* `_derive_a_etf.fnum`（取首个数值 token）—— 已就地改名 `first_num`，语义与 `fnum` 不同；
* `_derive_stock.pct(a, b)`（算变动率）—— 与这里的 `pct_str`（格式化）无关。

## `compact_series` 的市场参数（为什么不是无脑合并）

未收盘 bar 剔除依赖「收盘时刻」：美股 16:00 ET、A股 15:00 CST。因此：

* `tz=None`（默认）⇒ **只压缩、不剔除**，纯格式化，行为与旧 `compact_series` 逐字相同；
* 传 `tz` + `close_hour` ⇒ 启用剔除（`collect.py` 传 `MARKET_TZ / 16.0 / "美东"`，输出与旧实现逐字一致）。

A股调用方目前**刻意传 `tz=None`**：把「A股要不要剔除未收盘 bar」留成显式决策（涉及证据包内容变化，
需一次真实跑批确认），而不是在重构里顺手改掉。见文件末 TODO。
"""
from __future__ import annotations

import re

from wb_analysis._log import log_gap

__all__ = [
    "SERIES_LINE_RE",
    "compact_series",
    "fnum",
    "pct_str",
    "wcode_of",
    "ystr",
]

#: 技术指标序列里「真数据行」的形状：`YYYY-MM-DD: 数值`。
#: 排除休市日的 `N/A: Not a trading day` 与尾部的指标说明提示词。
SERIES_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}:\s*-?\d")


def fnum(v, default=None):
    """整串转 float（容忍千分位与百分号）；失败返回 default（**绝不用别的标的兜底**）。"""
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def pct_str(v, digits: int = 2) -> str:
    """带符号百分数字符串；取不到值时返回 `—`（不是 0，也不是空）。"""
    x = fnum(v)
    return "—" if x is None else f"{x:+.{digits}f}%"


def ystr(v: object, scale: float = 1e8, unit: str = "亿元", sign: bool = False) -> str:
    """把数值格式化为「X.XX 亿元」；缺失时显式输出「（未取到）」而非 None。"""
    if v is None:
        return "（未取到）"
    try:
        return f"{float(v) / scale:{'+' if sign else ''}.2f} {unit}"
    except (TypeError, ValueError):
        return "（未取到）"


def wcode_of(ticker: str) -> str:
    """把标的代码规范成 westock 的 `sh`/`sz` 前缀形式（两份旧实现的**并集**）。

    判据顺序：
    1. 已带 `sh`/`sz` 前缀 ⇒ 原样（小写）；
    2. 带显式后缀 ⇒ `.SS`/`.SH` → `sh`，`.SZ` → `sz`；
    3. 无后缀 ⇒ 按首位推断：`5/6/9` = 上交所，`0/1/2/3` = 深交所；
    4. 无法判定 ⇒ 小写原样返回（交给 westock 报错，不臆造）。
    """
    t = str(ticker).strip()
    low = t.lower()
    if low.startswith(("sh", "sz")):
        return low
    if "." in t:
        code, _, suf = t.partition(".")
        s = suf.upper()
        if s in ("SS", "SH"):
            return "sh" + code
        if s == "SZ":
            return "sz" + code
        return low
    if t[:1] in ("5", "6", "9"):
        return "sh" + t
    if t[:1] in ("0", "1", "2", "3"):
        return "sz" + t
    return low


def compact_series(
    raw: object,
    keep: int = 5,
    *,
    tz=None,
    close_hour: float | None = None,
    tz_label: str = "美东",
) -> str:
    """把指标输出压成「最近 keep 个有效值」，可选剔除未收盘 bar。

    ⚠️ **顺序陷阱（2026-09-16 定位并修复）**

    ``get_indicators`` 的输出是 **新 → 旧** 排列（标题行之后的**第一行就是最新交易日**）。
    原实现直接 ``kept[-keep:]`` 取列表尾部，等于取走了窗口里**最旧**的 5 个交易日。
    实测（``^NDX``，基准日 2026-09-16）：接口对 2026-09-15 有 ``close_50_sma = 29178.31``，
    而证据包只收录到 2026-09-14 的 29193.51。现改为**按日期显式降序后取前 keep 个**。

    ★ 未收盘 bar 剔除（2026-09-17 新增，仅在传 `tz` 时启用）

    盘中采集时接口会为**当天尚未收盘的 bar** 也算一个指标值，该值基于盘中瞬时价，
    与收盘口径不可比。实测（^NDX 2026-09-17 盘中）：RSI 44.02 → 52.30、ATR 376.16 → 382.79，
    足以把「中性偏弱」改写成「中性偏强」。

    判据：末根值所属日期 == 当地今天，且当地时刻 < `close_hour`。因本函数只拿到序列、
    拿不到成交量，故用**日期判定**；价格侧的严格量能判据见 ``collect._price_summary``。
    """
    if not raw:
        return "(无数据)"
    kept: list[tuple[str, str]] = []
    for line in str(raw).splitlines():
        s = line.strip()
        if not SERIES_LINE_RE.match(s):
            continue
        kept.append((s.split(":", 1)[0].strip(), s))
    if not kept:
        return "(无有效值)"
    kept.sort(key=lambda kv: kv[0], reverse=True)

    if tz is not None and close_hour is not None:
        try:
            now = _clock_now(tz)
            today = now.date().isoformat()
            closed = (now.hour + now.minute / 60.0) >= close_hour
            if kept and kept[0][0] == today and not closed:
                dropped_date = kept[0][0]
                kept = kept[1:]
                if kept:
                    return ("\n".join(s for _, s in kept[:keep])
                            + f"\n⚠ 已剔除未收盘 bar（{dropped_date}，{tz_label}尚未收盘）")
        except Exception as exc:  # noqa: BLE001 — 时钟异常不得让证据包整体失败
            log_gap("collect.compact_series_unclosed_bar", exc)

    return "\n".join(s for _, s in kept[:keep])


def _clock_now(tz):
    """延迟取时钟：让测试能 monkeypatch `wb_analysis._clock.now`。"""
    from wb_analysis import _clock

    return _clock.now(tz)


# TODO(2026-10-23，需领域确认后再做)：`collect_a_stock.compact_series` 历史实现**没有**
#   未收盘 bar 剔除，本次收敛为「只压缩不剔除」（tz=None）以保持证据包逐字不变。
#   A股收盘是 15:00 CST，要启用须传 `tz=CN_TZ, close_hour=15.0, tz_label="A股"`，
#   并先用一次盘中真实采集确认「westock technical 是否真的返回当日未收盘值」。
