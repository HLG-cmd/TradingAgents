# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/collect_index.py
"""指数证据采集器（多指数，默认 NDX）—— 全程不调用任何 LLM。

支持指数见模块级 ``INDEX_CONFIGS``（当前含 NDX / SPX），通过 ``--index`` 切换。

**为什么必须单独写一个采集器**

指数与个股的数据可得性从根上不同：

| 维度 | 个股（AMD） | 指数（如 NDX / SPX） |
|---|---|---|
| 行情/技术指标 | ✅ | ✅（指数代码可用，与个股同源） |
| 财报（利润表/资产负债表/现金流） | ✅ | ❌ `NO_DATA_AVAILABLE` |
| 估值（PE/PB/PS） | ✅ | ❌ 需从成分股聚合 |
| 内部人交易 | ✅ | ❌ 需从成分股聚合 |
| cashtag 情绪 | ✅ | ⚠️ 退化为对应 ETF（如 `$QQQ` / `$SPY`）的 ETF 情绪 |

因此 `collect.py` 直接跑指数代码会得到一份「技术面齐全、基本面全空」的残缺证据包。
本脚本把指数真正需要的四个维度补上：

  1) **聚合估值**：按市值加权的 PE/PB/PS/股息率/盈利收益率 + 股权风险溢价（对 10Y 美债）
  2) **成分结构**：ETF 代理真实权重前十大 + 集中度（HHI）+ 行业分布
  3) **市场广度**：% 站上 200SMA / 50SMA、涨跌家数、**等权 vs 加权收益背离**（判断上涨是否健康）
  4) **内部人聚合**：成分股内部人买卖净额（替代指数的内部人维度）

估值聚合采用**市值加权（调和）口径**，而非简单的 PE 算术平均：
    指数 PE = Σ 市值 / Σ 净利润，  净利润_i = 市值_i / PE_i
这与 S&P/纳斯达克官方口径一致；简单算术平均会被极端值（微利公司 PE 上千）严重扭曲。
亏损公司（PE ≤ 0 或无值）计入市值但剔除出盈利，并单独披露剔除数量。

用法：
    python wb_analysis/collect_index.py --date 2026-09-16
    python wb_analysis/collect_index.py --date 2026-09-16 --no-social --top-insiders 10

产物：
    wb_analysis/evidence/NDX_<YYYY-MM-DD>.md
    wb_analysis/evidence/NDX_<YYYY-MM-DD>.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# ★ 2026-10-15：移除模块级 os.chdir(PROJECT_ROOT)，改为在 main() 入口执行，消除 import 副作用

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from quant.stock_pools import NASDAQ_100, get_latest_sp500
from wb_analysis._thresholds import HUMP_MIN_PP, MAX_QUOTE_AGE_DAYS  # noqa: E402
from wb_analysis.collect import (  # noqa: E402
    MACRO_ALIASES,
    PREDICTION_TOPICS,
    TECH_INDICATORS,
    _compact_macro,
    _compact_series,
    _get_router,
    _price_summary,
    _reddit_block,
    _safe_call,
    _stocktwits_block,
    # ★ 2026-10-11（O3）：`--date` 口径守卫与「美东当日」取值**共用 collect.py 的实现**，
    #   不在此处复制逻辑 —— 指数采集器与个股采集器是同一个失败模式的两条入口。
    date_caliber_guard,
    today_eastern,
)

EV_DIR = PROJECT_ROOT / "wb_analysis" / "evidence"

# ----------------------------------------------------------------------------
# 多指数配置表（改造核心：把散落的硬编码收拢到这里）
# ----------------------------------------------------------------------------
# 每个指数给出：指数代码 / ETF 代理 / 中文名 / 成分股池函数 / 池标签（用于报告）
# 以及「股份类别去重集」——这是各指数唯一的真实口径差异：
#   · NDX：GOOG 与 GOOGL 同属 Alphabet，为避免市值双计，去重保留 GOOGL
#   · SPX：标普 500 官方把 GOOGL 与 GOOG 计为两个独立成分股，故不去重
INDEX_CONFIGS = {
    "NDX": {
        "index_ticker": "^NDX",
        "etf_proxy": "QQQ",
        "display": "纳斯达克 100 指数",
        "pool_fn": lambda: list(NASDAQ_100),
        "pool_label": "stock_pools.NASDAQ_100",
        "dedup_classes": {"GOOG": "GOOGL"},
    },
    "SPX": {
        "index_ticker": "^GSPC",
        "etf_proxy": "SPY",
        "display": "标普 500 指数",
        "pool_fn": lambda: get_latest_sp500(),
        "pool_label": "stock_pools.get_latest_sp500()",
        "dedup_classes": {},          # 标普500 官方把 GOOGL/GOOG 计为两个独立成分股
    },
}
DEFAULT_INDEX = "NDX"

# 向后兼容：保留这两个模块级常量（其它引用处仍读取它们），
# 其值由当前选中的指数决定（见 _select_index）。
INDEX_TICKER = INDEX_CONFIGS[DEFAULT_INDEX]["index_ticker"]
ETF_PROXY = INDEX_CONFIGS[DEFAULT_INDEX]["etf_proxy"]

# 当前选中的配置（运行时由 _select_index 更新）
_CURRENT = dict(INDEX_CONFIGS[DEFAULT_INDEX])

# 报价新鲜度阈值（天）。
#
# **★★ 2026-09-17 重大修正 —— 此阈值与「陈旧」的判定口径**
#
# 首版曾把「陈旧」判定为 **yfinance 数据源的系统性状态**，理由是实测
# QQQ/SPY/AAPL/NVDA/IWM/MSFT 全部到期日的最新成交距今 42~56 天。
# **该结论是错的**，根因是**采集时点**：
#
#   · 该测量发生在北京时间 15:21 = **美东 03:21（盘前）**。
#     此时 yfinance 期权链返回的是上一交易日收盘后的残留快照 ——
#     bid/ask 格式合法但 lastTradeDate 已过时数周。
#   · 同一标的在 **美东盘中**（实测 10:08）复测：
#     QQQ 1736 个双边报价合约，**最新成交距今仅 0.01 天**，中位 0.75 天；
#     SPY/AAPL/NVDA/MSFT/IWM 同样全部新鲜。
#   · 且能正常算出 25Δ 偏斜（2026-10-16 到期：ATM IV 18.42%、
#     25Δ Call 15.76%、25Δ Put 19.14%、偏斜 +3.38pp）。
#
# ⇒ **正确表述：期权链只在美股常规交易时段（美东 09:30–16:00）实时刷新；
#    盘前/盘后/休市采集会拿到陈旧快照。** 这是采集时点问题，不是数据源缺陷。
# ⇒ **本阈值保留不变**：它正确地拦住了盘前采集的垃圾数据。
#    放行条件是「新鲜样本 > 0」，盘前场景自然为 0，无需改阈值。
# ⚠️ 2026-10-10：值本身已上提到 `wb_analysis/_thresholds.py`（**唯一定义源**），
#    由顶部 import 提供 —— 因为 `_probe_option_dual_quote.py` 与 `_audit_gaps.py`
#    曾各自抄一份同样的 5 天（后者还只在注释里声称「与本文件对齐」）。
#    改口径请改 `_thresholds.py`，三处自动同步。

_INDICATOR_LOOKBACK = 10

# 从个股 .info 抽取的字段（用于指数级聚合）
INFO_FIELDS = (
    "marketCap",
    "trailingPE",
    "forwardPE",
    "priceToBook",
    "priceToSalesTrailing12Months",
    "sector",
    "industry",
    "returnOnEquity",
    "profitMargins",
    "grossMargins",
    "operatingMargins",
    "revenueGrowth",
    "earningsGrowth",
    "dividendYield",
    "trailingEps",
    "forwardEps",
    "beta",
    "currentPrice",
)

# Alphabet 双股份类别会重复计入市值，聚合成份股时必须去重（保留 GOOGL，其权重更高）。
# 保留为 NDX 默认去重集；实际使用时由 _select_index 选中的配置决定（见下方 _CURRENT）。
_DUPLICATE_CLASSES = {"GOOG": "GOOGL"}
_UNIVERSE_WORKERS = 8


def _select_index(key: str = DEFAULT_INDEX) -> dict:
    """选定当前指数：同步更新模块级 INDEX_TICKER / ETF_PROXY / _CURRENT。

    返回被选中的配置字典。未知 key 时回退到 DEFAULT_INDEX，保证向后兼容。
    """
    global INDEX_TICKER, ETF_PROXY, _CURRENT
    cfg = INDEX_CONFIGS.get(key, INDEX_CONFIGS[DEFAULT_INDEX])
    INDEX_TICKER = cfg["index_ticker"]
    ETF_PROXY = cfg["etf_proxy"]
    _CURRENT = dict(cfg)
    return cfg


# ----------------------------------------------------------------------------
# 成分股数据获取
# ----------------------------------------------------------------------------
def _clean_universe(tickers: list[str], dedup: dict | None = None) -> list[str]:
    """剔除重复股份类别，返回参与聚合的成分股清单。

    dedup 缺省时取当前选中指数（_CURRENT）的去重集：
      · NDX → {"GOOG": "GOOGL"}（保留 GOOGL，剔除 GOOG）
      · SPX → {}（官方口径下 GOOGL/GOOG 为两个独立成分股，不去重）
    """
    if dedup is None:
        dedup = _CURRENT["dedup_classes"]
    out: list[str] = []
    for t in tickers:
        if t in dedup:
            continue
        if t not in out:
            out.append(t)
    return out


def _fetch_info(ticker: str) -> tuple[str, dict]:
    import yfinance as yf

    try:
        raw = yf.Ticker(ticker).info or {}
        data = {k: raw.get(k) for k in INFO_FIELDS}
        data["_name"] = raw.get("shortName") or raw.get("longName") or ticker
        return ticker, data
    except Exception as exc:  # noqa: BLE001
        return ticker, {"_error": f"{type(exc).__name__}: {exc}"}


def fetch_universe_infos(tickers: list[str]) -> dict[str, dict]:
    """并发拉取成分股 .info（单只约 1.1s，8 线程约 15s/99 只）。"""
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=_UNIVERSE_WORKERS) as pool:
        futs = {pool.submit(_fetch_info, t): t for t in tickers}
        for fut in as_completed(futs):
            tk, data = fut.result()
            out[tk] = data
    return out


def fetch_top_holdings() -> list[dict]:
    """取 ETF 代理（ETF_PROXY）前十大真实权重（ETF 跟踪对应指数，权重基本一致）。"""
    import yfinance as yf

    try:
        th = yf.Ticker(ETF_PROXY).funds_data.top_holdings
        if th is None or th.empty:
            return []
        rows = []
        for sym, row in th.iterrows():
            rows.append(
                {
                    "symbol": str(sym),
                    "name": str(row.get("Name", "")),
                    "weight_pct": round(float(row.get("Holding Percent", 0)) * 100, 2),
                }
            )
        return rows
    except Exception:  # noqa: BLE001
        return []


def _insider_net(ticker: str, router) -> dict:
    """聚合单只成分股的内部人买卖净额（近一年窗口内的全部记录）。"""
    import re

    st, txt = _safe_call("get_insider_transactions", router, "get_insider_transactions", ticker)
    if st != "ok":
        return {"ticker": ticker, "status": st, "buy_shares": 0, "sell_shares": 0, "buy_value": 0.0, "sell_value": 0.0}

    buy_s = sell_s = 0.0
    buy_v = sell_v = 0.0
    for line in str(txt).splitlines():
        low = line.lower()
        m = re.match(r"^\s*\d+,(\d+),([\d.]*),.*?,(.*?),([^,]*),([^,]*),,(\d{4}-\d{2}-\d{2})", line)
        if not m:
            continue
        shares = float(m.group(1) or 0)
        value = float(m.group(2) or 0)
        desc = low
        if "purchase" in desc and "at price" in desc:
            buy_s += shares
            buy_v += value
        elif "sale at price" in desc:
            sell_s += shares
            sell_v += value
    return {
        "ticker": ticker,
        "status": "ok",
        "buy_shares": int(buy_s),
        "sell_shares": int(sell_s),
        "buy_value": round(buy_v, 2),
        "sell_value": round(sell_v, 2),
    }


def fetch_insiders(tickers: list[str], router, workers: int = 6) -> list[dict]:
    out: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_insider_net, t, router) for t in tickers]
        for fut in as_completed(futs):
            try:
                out.append(fut.result())
            except Exception:  # noqa: BLE001
                continue
    return sorted(out, key=lambda r: -(r.get("sell_value") or 0))


# ----------------------------------------------------------------------------
# 期权市场内部结构（机构资金面代理）
# ----------------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    """标准正态 CDF（用 math.erf 精确计算，不引入 scipy 依赖）。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(spot: float, strike: float, t: float, vol: float,
              rate: float, div: float, is_call: bool) -> float:
    """Black-Scholes-Merton 欧式期权理论价（**含连续股息率**）。

    **为什么必须带股息率 ``div``**：ETF 代理是派息 ETF。实测对 638 天 LEAPS 做反解，
    令 q=0 会使反解 IV 相对报价自身隐含的水平系统性偏离；把 q 调到由 put-call
    parity 实测反解出的水平后，两侧报价才互相自洽。**股息率对长天期期权的
    影响不能忽略** —— 这正是旧实现（无股息近似）产出错误 IV 的直接原因。
    """
    if t <= 0 or vol <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    sq = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / sq
    d2 = d1 - sq
    fwd = spot * math.exp(-div * t)
    disc = math.exp(-rate * t)
    if is_call:
        return fwd * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - fwd * _norm_cdf(-d1)


def _bs_delta(spot: float, strike: float, t: float, vol: float,
              rate: float, div: float, is_call: bool) -> float:
    """BS delta（带符号）：call 为正、put 为负。用于 25-delta 配对。"""
    if t <= 0 or vol <= 0:
        return 0.0
    sq = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / sq
    disc = math.exp(-div * t)
    call_delta = disc * _norm_cdf(d1)
    return call_delta if is_call else call_delta - disc


def _implied_vol(mid: float, spot: float, strike: float, t: float,
                 rate: float, div: float, is_call: bool) -> float | None:
    """从中间价反解 BSM 隐含波动率（二分法，70 次迭代到约 1e-8）。

    **为什么不用 yfinance 自带的 ``impliedVolatility``**：
    实测该字段与报价不自洽。对 ETF 代理的 LEAPS 合约，用 mid 反解得到的
    IV 与 yfinance 自报值系统性偏离，且 **call 侧与 put 侧的偏离方向相反**
    （call 侧自报偏高、put 侧自报偏低），说明不是统一的模型参数问题，
    而是该字段本身口径不明 —— 无报价时段它还会由**过期的 lastPrice**
    反解，产出 0.001%~0.4% 的垃圾值。

    用**买卖权平价**可以判定谁对：同一行权价同时有 call/put 报价时，
    ``C − P = S·e^{−qT} − K·e^{−rT}``。实测该恒等式在 12 个配对样本上
    隐含的 S0 中位数为 703.12，与实际现价 704.72 仅差 **−0.23%** ——
    **报价本身是自洽的真实报价**，因此问题出在 yfinance 的 IV 字段上。

    本函数自解 IV，保证「IV 一定来自我们看到的那个报价」，并可施加
    无套利边界（低于内在价值 ⇒ 拒绝）与合理区间（[2%, 300%]）。
    """
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
    if not (mid > intrinsic):
        return None                      # 低于/等于内在价值 ⇒ 报价不可信
    lo, hi = 1e-4, 5.0
    if _bs_price(spot, strike, t, hi, rate, div, is_call) < mid:
        return None                      # 5 倍波动率都解释不了 ⇒ 错价
    for _ in range(70):
        midv = 0.5 * (lo + hi)
        if _bs_price(spot, strike, t, midv, rate, div, is_call) < mid:
            lo = midv
        else:
            hi = midv
    iv = 0.5 * (lo + hi)
    # IV 上界定为 120%：ETF 代理是低波动宽基 ETF，近两年 VXN 区间为 15.15~43.25。
    # 反解出 >120% 的唯一可能是**报价本身陈旧** —— 深度实值合约的挂单残留了
    # 昨日的内在价值，反解器为了拟合这个「不可能的价格」把 vol 推到极限。
    # 实测 2026-09-30（13 天）call 侧 K=410 反解 251.78%、K=430 反解 224.62%，
    # 这些值不是波动率，是「报价失真」的量化标记，必须丢弃。
    return iv if 0.02 <= iv <= 1.20 else None


def probe_option_freshness(etf: str = ETF_PROXY) -> dict:
    """扫描该标的**全部**到期日的报价成交日，判断快照是否整体陈旧。

    **为什么需要这个探针**：yfinance 的期权链在**非交易时段**（盘前/盘后/休市）
    会返回**上一交易日的残留挂单** —— 这些挂单的 ``bid``/``ask`` 都 > 0，
    格式上完全合法，但 ``lastTradeDate`` 可能是几周甚至几个月前。
    若只按 ``bid>0 & ask>0`` 过滤，会把陈旧价格当成当前市场观点。

    **★★ 2026-09-17 修正 —— 首版结论被推翻**
    首版文档字符串写的是「**所有美股标的的期权报价都快照级陈旧**（42~56 天），
    这是 yfinance 数据源的系统性状态」。**该结论是错的。**
    根因是**采集时点**：那次测量在美东 **03:21（盘前）**，拿到的是残留快照；
    同一批标的在美东**盘中**复测，最新成交距今仅 **0.01 天**，完全新鲜。

    ⇒ 正确表述：**期权链只在美东 09:30–16:00 实时刷新。**
    本探针的价值就在于**在采集前先判定时点是否可用**，避免把盘前快照写进证据包。

    返回 ``min_age_days``（最新一笔成交的年龄）、``n_fresh``（新鲜样本数）、
    ``stale``（是否整体不可用）、``in_session``（是否处于美股常规交易时段）。
    """
    import pandas as pd
    import yfinance as yf

    out = {"etf": etf, "expiries_checked": 0, "min_age_days": None,
           "n_fresh": 0, "n_quoted": 0, "stale": True, "ages_days": [],
           "in_session": None, "session_note": ""}

    # ★ 先判定采集时点 —— 这是比数值过滤更前置的一道闸门
    #   ⚠️ 2026-10-17：判据已收敛到 `_thresholds.market_session_phase()`（单一来源）。
    #   此前这里**又写了一份** `9.5 <= _h < 16.0` 字面量 —— 与 `_should_use_cboe_source()`
    #   各持一份边界，改一处忘一处就会出现「切了源但仍按旧口径判时段」的静默错配。
    #   措辞也已同步到 CBOE 回退后的现实：非盘中**不再是死路**（自动切 CBOE 快照），
    #   但仍须声明「拿的是上一时段快照」。
    try:
        import zoneinfo
        from wb_analysis._thresholds import market_session_phase

        _now_ny = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        _phase = market_session_phase(_now_ny)
        out["session_phase"] = _phase
        out["in_session"] = (_phase == "in_session")
        if out["in_session"]:
            out["session_note"] = (f"采集时点 {_now_ny:%Y-%m-%d %H:%M} 美东，"
                                   f"处于常规交易时段，期权链应实时刷新")
        else:
            _label = {"pre_market": "盘前", "after_hours": "盘后",
                      "closed_day": "非交易日"}[_phase]
            out["session_note"] = (
                f"采集时点 {_now_ny:%Y-%m-%d %H:%M} 美东，处于**{_label}**——"
                f"yfinance 此时只返回上一交易日的残留快照（lastTradeDate 可能过时数周），"
                f"故**期权自动改走 CBOE 官方延迟报价**（上一时段收盘快照，非实时报价）。")
    except Exception:  # noqa: BLE001
        pass

    try:
        t = yf.Ticker(etf)
        exps = list(getattr(t, "options", None) or [])
        now = pd.Timestamp.now(tz="UTC")
        for exp in exps:
            if (dt.date.fromisoformat(exp) - dt.date.today()).days <= 0:
                continue
            try:
                ch = t.option_chain(exp)
            except Exception:  # noqa: BLE001
                continue
            out["expiries_checked"] += 1
            for df in (ch.calls, ch.puts):
                d = df.copy()
                if "bid" not in d.columns or "ask" not in d.columns:
                    continue
                d["bid"] = pd.to_numeric(d["bid"], errors="coerce")
                d["ask"] = pd.to_numeric(d["ask"], errors="coerce")
                d = d[(d["bid"] > 0) & (d["ask"] > 0)]
                if d.empty or "lastTradeDate" not in d.columns:
                    continue
                ltd = pd.to_datetime(d["lastTradeDate"], errors="coerce", utc=True)
                ages = ((now - ltd).dt.total_seconds() / 86400.0).dropna()
                if ages.empty:
                    continue
                out["n_quoted"] += int(len(ages))
                out["ages_days"].extend([round(float(a), 1) for a in ages])
                mn = float(ages.min())
                if out["min_age_days"] is None or mn < out["min_age_days"]:
                    out["min_age_days"] = round(mn, 1)
        out["n_fresh"] = sum(1 for a in out["ages_days"] if a <= MAX_QUOTE_AGE_DAYS)
        out["stale"] = out["n_fresh"] == 0
        if out["ages_days"]:
            out["ages_days"] = sorted(out["ages_days"])[:60]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _source_label(src: str | None) -> str:
    """期权来源标签（供证据包声明用）。未知来源如实标注，不美化。"""
    return {
        "yfinance": "yfinance（第三方聚合器，盘中实时刷新）",
        "cboe_delayed": "CBOE 官方延迟报价（`cdn.cboe.com/api/global/delayed_quotes/options/`，"
                        "免密钥，**15 分钟延迟**；非盘中时段提供**上一时段收盘快照**）",
    }.get((src or "").strip(), f"未标注（{src or '缺失'}）")


def _iv_method_label(src: str | None) -> str:
    """IV 计算方法标签（随来源变化）。"""
    return ("自建 Black-Scholes-Merton 反解"
            if (src or "").startswith("yfinance")
            else "交易所模型直出（CBOE 官方，无需反解）")


def _should_use_cboe_source() -> tuple[bool, str]:
    """判定是否该切到 CBOE（非盘中时段），返回 (是否切换, 说明)。

    ★ 2026-10-17：**判据已上移到 `wb_analysis/_thresholds.py` 的 `option_source_decision()`**
    —— 时段边界是全局判据（同时决定「走哪个源」），不得在消费方本地重写。
    本函数只做转发，保留原签名以免影响既有调用点与测试。
    """
    from wb_analysis._thresholds import option_source_decision
    try:
        return option_source_decision()
    except Exception:  # noqa: BLE001
        # 判定失败时**保守选择主源**（不静默切到另一口径）
        return False, "时点判定失败 ⇒ 保守用 yfinance 主源"


def _resolve_source_note(use_cboe: bool, cboe_ok: bool, session_note: str) -> str:
    """拼出「本次实际用了哪个源」的人读说明。

    **必须区分「打算用」与「真的用上了」**：`use_cboe` 是纯时间判据（盘前/盘后即 True），
    而 `cboe_ok` 才代表 CBOE 真的返回了数据。二者不一致时（403 / 网络失败 ⇒ 退回 yfinance），
    说明里必须**显式写出这层降级** —— 否则证据包会声明成 CBOE 口径，
    而数值其实来自自建 BSM 反解，两个口径的偏斜差异可达数 pp。

    返回给证据包渲染，形如：
      · 盘中：`…（常规交易时段）⇒ 用 yfinance 主源`
      · 盘前且 CBOE 成功：`…（盘前）⇒ 切 CBOE 官方延迟报价（拿的是**上一时段收盘快照**，非实时报价）`
      · 盘前但 CBOE 失败：上一句 + `｜⚠️ **但 CBOE 取数未成功，本轮回退 yfinance 主源**…`
    """
    if not use_cboe or cboe_ok:
        return session_note
    return (session_note
            + "｜⚠️ **但 CBOE 取数未成功，本轮回退 yfinance 主源**"
              "（该标的可能无可用期权，如指数符号 / A 股 ETF）")


def fetch_option_structure(etf: str = ETF_PROXY) -> dict:
    """取 ETF 期权链，构建机构资金面指标 —— 填补「无期权/资金面证据」的缺口。

    **2026-09-17 彻底重写（v3）**。旧版（v1/v2）的四个问题及本版对策：

    | 旧问题 | 后果 | v3 对策 |
    |---|---|---|
    | 直接信任 yfinance ``impliedVolatility`` | 该字段与报价不自洽，call/put 偏离方向还相反 | **自建 BSM 反解**，含股息率 |
    | BS 反解用无股息近似 | 长天期 LEAPS 上反解 IV 系统性失真 | **``div`` 由 put-call parity 实测反解** |
    | 只盯 14/35/95 天三个到期日 | 近月本就没有报价，直接判「整段不可用」 | **全到期日扫描**，按质量分级选样 |
    | 偏斜用「固定距现价 ±10%」定义 | 该档位常整段无报价 ⇒ 误报为「数据缺失」 | **改用 25-delta 配对**（业界标准） |

    **核心方法论修正 —— 偏斜必须按 delta 配对，而不是按距现价百分比。**
    期权链的实际报价格点是**固定行权价**（ETF 代理间隔 1 或 5 美元），
    「距现价 ±10%」会随现价漂移；当现价恰好落在某档行权价附近时，
    一个方向可能有密集报价、另一个方向整段为空。旧实现遇到这种情况直接
    放弃，**等于把「档位错配」误报成「数据缺失」**。按 |Δ|≈0.25 配对则
    **天然同 |Δ|**，与现价无关 —— 这是 CBOE 与业界通行的 skew 口径。

    覆盖的指标：
      - **Put/Call 比**（成交量口径；OI 口径有自检闸门）
      - **ATM 隐含波动率**（|Δ| ≈ 0.5 区间中位数）
      - **25-delta 偏斜**（`|Δ|∈[0.20,0.30]` 内 IV 中位数：put − call，**主口径**；
        无样本时逐步放宽并记录实际区间，见 JSON 的 `skew_25d_band`）
      - **±10% 偏斜**（传统口径，两侧都有样本时才给）
      - **期限结构**（近月 vs 远月 ATM IV 斜率，判断事件定价）
      - **风险中性偏度替代**（OTM put IV ÷ ATM put IV，无配对时的稳健替代）

    说明：指数本身没有期权合约，故用跟踪该指数的 ETF（对应 ETF_PROXY）作为代理。
    """
    import pandas as pd
    import yfinance as yf

    # 报价新鲜度阈值见模块级 MAX_QUOTE_AGE_DAYS 的注释块（含 2026-09-17 口径修正）。
    # 简言之：盘前/盘后采集会拿到上一交易日的残留快照，其 mid 常低于当前内在价值，
    # 反解 IV 会飙到 150%~250% —— 那不是波动率，是「报价失真」。
    # **必须按成交日过滤**，否则会把陈旧价格当成当前市场观点。

    try:
        # ★★ 2026-10-16 新增：**时点分支**（方案 A：主源 + 回退）
        #   问题：yfinance 的期权链只在美东 09:30–16:00 实时刷新；盘前/盘后它只返回
        #   **上一交易日的残留挂单**（bid/ask 格式合法但 lastTradeDate 陈旧数周）。
        #   实测（NDX 2026-10-16 轮，美东 08:29 盘前）：扫 29 个到期日、387 个有双边报价
        #   合约，最新成交距今 **23.2 天**、合格样本 **0** ⇒ IV 等级 NONE ⇒ 维度整体不可用。
        #
        #   对策：非盘中时段自动切换 **CBOE 官方延迟报价**（免密钥，robots.txt 未禁止）。
        #   它是**做市商报价链**（远月覆盖率 100%），不依赖「当天有没有成交」
        #   ⇒ 盘前/盘后拿到的是**完整的上一时段快照**。
        #   实证：只保留「上一交易日成交」的合约，31 个到期日全部可算 ATM IV。
        #
        #   ⚠️ 两条纪律：
        #     ① **盘中不切换** —— 原路径已验证新鲜（距今 0.0 天），避免回归风险；
        #     ② **口径不同不可混用** —— CBOE 的 iv/delta 是交易所模型，与项目自建 BSM
        #        反解数值不同（同轮 2026-10-30 偏斜：CBOE −0.62pp vs 项目 −4.24pp）。
        #        故返回值带 `source`，由渲染层在证据包里显式声明来源。
        use_cboe, session_note = _should_use_cboe_source()
        t = None
        # ★ 2026-10-17：**必须区分「打算用 CBOE」与「真的用上了 CBOE」**。
        #   此前 `source` 只看 `use_cboe`（纯时间判据）⇒ 一旦 CBOE 取数失败、退回 yfinance，
        #   返回的 `source` 仍写 "cboe_delayed"，freshness 块也写 "已切 CBOE 源，跳过探测"
        #   ⇒ **实际用的是 yfinance 的数据，却对外声明成 CBOE 口径**。
        #   这会污染下游：证据包会打印「数据来源：CBOE 官方延迟报价」以及
        #   「口径提示：本源的 iv/delta 由交易所模型给出」——而数值其实来自 BSM 反解。
        #   两个源的口径本就不可混用（偏斜差异可达数 pp），声明错了比不声明更危险。
        #   ⇒ 改用 `cboe_ok`（**实际**成功取到 CBOE 数据）驱动声明。
        cboe_ok = False
        if use_cboe:
            try:
                from wb_analysis._option_source import fetch_chain
                t = fetch_chain(etf)
                exps = list(t.options or [])
                if not exps:
                    t = None                      # 退回 yfinance（虽然预期也拿不到）
                else:
                    cboe_ok = True
            except Exception:                     # noqa: BLE001
                t = None                          # CBOE 不可用 ⇒ 退回原路径并如实登记
        if t is None:
            t = yf.Ticker(etf)
        exps = list(getattr(t, "options", None) or [])
        if not exps:
            return {"error": "无期权链数据"}

        # spot：CBOE 用顶层 current_price；yfinance 用 fast_info / history
        spot = None
        _cboe_spot = getattr(t, "spot", None)
        if _cboe_spot:
            spot = float(_cboe_spot)
        if not spot:
            try:
                spot = t.fast_info["lastPrice"]
            except Exception:  # noqa: BLE001
                pass
        if not spot:
            try:
                hist = t.history(period="5d")
                spot = float(hist["Close"].iloc[-1]) if len(hist) else None
            except Exception:  # noqa: BLE001
                pass
        if not spot:
            return {"error": "无法取得标的价格"}
        spot = float(spot)

        # 无风险利率：用 10Y 国债（ETF 期权最长约 2.3 年，用 10Y 贴现足够）
        rate = 0.045
        try:
            tnx = yf.Ticker("^TNX").history(period="5d")
            if len(tnx):
                rate = float(tnx["Close"].iloc[-1]) / 100.0
        except Exception:  # noqa: BLE001
            pass
        rate = max(0.0, min(rate, 0.15))

        today = dt.date.today()
        future = [e for e in exps if (dt.date.fromisoformat(e) - today).days > 0]
        if not future:
            return {"error": "无未到期期权"}

        # --- 股息率：由 put-call parity 实测反解，而不是照抄任一字段 ---
        # 平价关系 C − P = S·e^{−qT} − K·e^{−rT} 可解出 q：
        #     q = −ln( (C − P + K·e^{−rT}) / S ) / T
        # 为什么必须自解：yfinance 的三个股息字段互相矛盾 ——
        #     dividendYield = 0.42（疑似百分数语义）
        #     trailingAnnualDividendYield = 0.0025
        #     trailingAnnualDividendRate = 1.77
        # 三者相差最大 168 倍，直接取任何一个都会把 IV 算错。
        div_yield = None
        div_note = None
        try:
            probe = max(future, key=lambda e: (dt.date.fromisoformat(e) - today).days)
            ttm_p = (dt.date.fromisoformat(probe) - today).days / 365.0
            chp = t.option_chain(probe)
            cm = chp.calls.copy()
            pm = chp.puts.copy()
            for d in (cm, pm):
                for c in ("bid", "ask", "strike"):
                    d[c] = pd.to_numeric(d[c], errors="coerce")
            cm = cm[(cm["bid"] > 0) & (cm["ask"] > 0)].copy()
            pm = pm[(pm["bid"] > 0) & (pm["ask"] > 0)].copy()
            # 同样要排除陈旧报价：否则平价关系的配对样本会用到几个月前的价格
            for _df in (cm, pm):
                if "lastTradeDate" in _df.columns:
                    _ltd = pd.to_datetime(_df["lastTradeDate"], errors="coerce", utc=True)
                    _age = (pd.Timestamp.now(tz="UTC") - _ltd).dt.total_seconds() / 86400.0
                    _df.drop(_df.index[~(_age <= MAX_QUOTE_AGE_DAYS).fillna(False)],
                             inplace=True)
            if cm.empty or pm.empty:
                raise ValueError("平价反解无新鲜报价")
            cm["_cm"] = (cm["bid"] + cm["ask"]) / 2
            pm["_pm"] = (pm["bid"] + pm["ask"]) / 2
            j = cm.merge(pm, on="strike", suffixes=("_c", "_p"))
            qs = []
            for _, rr in j.iterrows():
                # 行权价须落在现价附近，避免深度实值的杠杆放大误差
                if abs(rr["strike"] / spot - 1) > 0.35:
                    continue
                fwd = rr["_cm"] - rr["_pm"] + rr["strike"] * math.exp(-rate * ttm_p)
                if fwd <= 0:
                    continue
                q = -math.log(fwd / spot) / ttm_p
                if -0.05 < q < 0.10:
                    qs.append(q)
            if qs:
                div_yield = round(float(statistics.median(qs)), 4)
                div_note = (
                    f"股息率由 **put-call parity 实测反解**（在 {probe} 到期日的 "
                    f"{len(qs)} 个同价配对样本上取中位数），**未使用 yfinance 的 "
                    "dividendYield 字段** —— 该字段口径自相矛盾（`dividendYield`=0.42、"
                    "`trailingAnnualDividendYield`=0.0025、"
                    "`trailingAnnualDividendRate`=1.77，三者最大相差约 168 倍）。"
                )
        except Exception:  # noqa: BLE001
            pass
        if div_yield is None:
            div_yield = 0.006       # 兜底：ETF 代理近年实际派息率量级
            div_note = ("⚠️ put-call parity 反解股息率失败，**采用兜底值 0.60%**。"
                        "该假设对近月 IV 影响可忽略，对 2 年期 LEAPS 有约 1~2pp 影响。")

        def _prep(df, exp: str, is_call: bool):
            """把原始链整理成带 ``_mn`` / ``_iv`` / ``_adelta`` 的 DataFrame。

            过滤链（每一步都对应一个实测踩过的坑）：
              1. ``bid > 0 且 ask > 0`` —— yfinance 无报价时全置 0，
                 **必须先挡掉**，否则「IV>0」条件形同虚设（垃圾值恰好 >0）。
              2. ``ask >= bid`` —— 剔除倒挂报价。
              3. 相对点差 ≤ 30% —— 剔除流动性极差的挂单
                 （ETF 代理主力合约点差通常 <5%，30% 已是宽松上界）。
              4. ``_iv`` 由 mid 自解（含股息率），且落在 [2%, 300%]。
            """
            if df is None or df.empty:
                return pd.DataFrame()
            d = df.copy()
            for col in ("bid", "ask", "strike"):
                if col not in d.columns:
                    return pd.DataFrame()
                d[col] = pd.to_numeric(d[col], errors="coerce")
            d = d[(d["bid"] > 0) & (d["ask"] > 0) & (d["ask"] >= d["bid"])].copy()
            if d.empty:
                return d

            # 报价新鲜度过滤：按 lastTradeDate 剔除陈旧挂单。
            # 实测该字段是判断「报价是否还代表当前市场」的唯一可靠依据。
            if "lastTradeDate" in d.columns:
                ltd = pd.to_datetime(d["lastTradeDate"], errors="coerce", utc=True)
                age_days = (pd.Timestamp.now(tz="UTC") - ltd).dt.total_seconds() / 86400.0
                fresh = age_days <= MAX_QUOTE_AGE_DAYS
                d = d[fresh.fillna(False)].copy()
                if d.empty:
                    return d
            d["_mid"] = (d["bid"] + d["ask"]) / 2.0
            d["_spread"] = (d["ask"] - d["bid"]) / d["_mid"]
            d = d[d["_spread"] <= 0.30].copy()
            if d.empty:
                return d
            ttm = max((dt.date.fromisoformat(exp) - today).days, 1) / 365.0
            d["_mn"] = (d["strike"] / spot - 1) * 100      # 过滤后再赋值，勿用 assign
            d["_iv"] = [
                _implied_vol(m, spot, k, ttm, rate, div_yield, is_call)
                for m, k in zip(d["_mid"], d["strike"])
            ]
            d = d[d["_iv"].notna()].copy()
            if d.empty:
                return d
            d["_adelta"] = [
                abs(_bs_delta(spot, k, ttm, v, rate, div_yield, is_call))
                for k, v in zip(d["strike"], d["_iv"])
            ]
            return d

        def _pick_delta(d, lo: float, hi: float):
            """在 |Δ| 落在 [lo, hi] 的合约里，取 ``_iv`` 中位数（25Δ 口径核心）。"""
            if d is None or d.empty:
                return None, 0, None
            s = d[(d["_adelta"] >= lo) & (d["_adelta"] <= hi)]
            if s.empty:
                return None, 0, None
            return (round(float(s["_iv"].median()) * 100, 2), len(s),
                    round(float(s["_mn"].median()), 1))

        def _pick_mn(d, lo: float, hi: float):
            """在距现价 [lo%, hi%] 区间取 ``_iv`` 中位数（±10% 传统口径）。"""
            if d is None or d.empty:
                return None, 0
            s = d[(d["_mn"] >= lo) & (d["_mn"] <= hi)]
            if s.empty:
                return None, 0
            return round(float(s["_iv"].median()) * 100, 2), len(s)

        def _chain_profile(exp: str) -> dict:
            ch = t.option_chain(exp)
            c_raw, p_raw = ch.calls, ch.puts
            c = _prep(c_raw, exp, True)
            p = _prep(p_raw, exp, False)
            days = (dt.date.fromisoformat(exp) - today).days

            def _sum(df, col):
                if col not in df.columns:
                    return 0.0
                return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

            c_oi, p_oi = _sum(c_raw, "openInterest"), _sum(p_raw, "openInterest")
            c_vol, p_vol = _sum(c_raw, "volume"), _sum(p_raw, "volume")

            # --- 主口径：25-delta 配对 ---
            # 先试窄区间 [0.20,0.30]（贴近标准 25Δ），无样本则逐步放宽，
            # 并记录实际区间宽度 —— 宽度越大，与标准 25Δ 的可比性越低。
            skew_25d = None
            skew_n = (0, 0)
            skew_mn = (None, None)
            skew_band = None
            for lo, hi in ((0.20, 0.30), (0.15, 0.35), (0.10, 0.45)):
                pv, pn, pmn = _pick_delta(p, lo, hi)
                cv, cn, cmn = _pick_delta(c, lo, hi)
                if pv is not None and cv is not None:
                    skew_25d = round(pv - cv, 2)
                    skew_n = (pn, cn)
                    skew_mn = (pmn, cmn)
                    skew_band = f"|Δ|∈[{lo},{hi}]"
                    break

            # --- 备用口径：±10% 距现价 ---
            otm_p, n_p = _pick_mn(p, -12.0, -8.0)
            otm_c, n_c = _pick_mn(c, 8.0, 12.0)
            skew_10pct = (round(otm_p - otm_c, 2)
                          if (otm_p is not None and otm_c is not None) else None)

            # ATM IV：优先 |Δ|∈[0.40,0.60]，退化到距现价 ±3%
            atm_c, n_atm_c, _ = _pick_delta(c, 0.40, 0.60)
            atm_p, n_atm_p, _ = _pick_delta(p, 0.40, 0.60)
            atm_basis = "delta" if (atm_c is not None or atm_p is not None) else None
            if atm_c is None:
                atm_c, n_atm_c = _pick_mn(c, -3.0, 3.0)
                atm_basis = atm_basis or "moneyness"
            if atm_p is None:
                atm_p, n_atm_p = _pick_mn(p, -3.0, 3.0)
                atm_basis = atm_basis or "moneyness"

            return {
                "expiry": exp,
                "days": days,
                "call_oi": int(c_oi),
                "put_oi": int(p_oi),
                "pc_oi": round(p_oi / c_oi, 3) if c_oi else None,
                "call_volume": int(c_vol),
                "put_volume": int(p_vol),
                "pc_volume": round(p_vol / c_vol, 3) if c_vol else None,
                "n_quoted_call": int(len(c)),
                "n_quoted_put": int(len(p)),
                "n_raw_call": int(len(c_raw)),
                "n_raw_put": int(len(p_raw)),
                "atm_call_iv": atm_c,
                "atm_put_iv": atm_p,
                "n_atm_call": n_atm_c,
                "n_atm_put": n_atm_p,
                "atm_basis": atm_basis,
                "otm_put_iv": otm_p,
                "otm_call_iv": otm_c,
                "n_otm_put": n_p,
                "n_otm_call": n_c,
                "skew_25d_pp": skew_25d,
                "skew_25d_band": skew_band,
                "n_skew_put": skew_n[0],
                "n_skew_call": skew_n[1],
                "skew_25d_mn": skew_mn[0],
                "skew_25d_call_mn": skew_mn[1],
                "skew_10pct_pp": skew_10pct,
                # 兼容字段：偏斜优先给 25-delta，其次 ±10%
                "skew_pp": skew_25d if skew_25d is not None else skew_10pct,
                "skew_basis": ("25delta" if skew_25d is not None
                               else ("10pct" if skew_10pct is not None else None)),
            }

        # --- 全到期日扫描（而不是只看 3 个目标日） ---
        # 旧实现只看 14/35/95 天，看不到就判「整段不可用」。实测近月报价极稀，
        # 而远月反而完整。这里对全部未来到期日取 profile，成本只是几十次 API 调用，
        # 换来的是「不把可得数据误报成缺口」。
        profiles: list[dict] = []
        for e in future:
            try:
                profiles.append(_chain_profile(e))
            except Exception:  # noqa: BLE001
                continue
        if not profiles:
            return {"error": "全部到期日均无法读取期权链"}

        def _grade_of(r: dict) -> str | None:
            """单个到期日的数据等级（取该到期日能达到的最高等级）。"""
            has_atm = r["atm_call_iv"] is not None and r["atm_put_iv"] is not None
            has_skew = r["skew_25d_pp"] is not None
            if has_atm and has_skew:
                return "FULL"                      # ATM + 25Δ 偏斜都齐
            if has_skew:
                return "SKEW_ONLY"                 # 有偏斜，无干净 ATM
            if has_atm:
                return "ATM_ONLY"
            if r["n_quoted_put"] >= 3 and r["n_quoted_call"] >= 3:
                return "PARTIAL_2SIDE"
            if r["n_quoted_put"] >= 3 or r["n_quoted_call"] >= 3:
                return "PARTIAL"
            return None

        # 选样优先级：FULL → SKEW_ONLY → ATM_ONLY → PARTIAL_2SIDE → PARTIAL；
        # 同级取距 14/35/95 天目标更近的（近月信息含量高）。
        TARGETS = (14, 35, 95)
        picked_rows: list[dict] = []
        grade = None
        for want in ("FULL", "SKEW_ONLY", "ATM_ONLY", "PARTIAL_2SIDE", "PARTIAL"):
            cands = [r for r in profiles if _grade_of(r) == want]
            if not cands:
                continue
            grade = want
            cands.sort(key=lambda r: min(abs(r["days"] - tg) for tg in TARGETS))
            picked_rows = cands[:3]
            break

        used_fallback = False
        fallback_note = None
        if not picked_rows:
            grade = "NONE"
            picked_rows = sorted(profiles, key=lambda r: -(r["n_quoted_call"] +
                                                           r["n_quoted_put"]))[:1]

        # 若选中的都不是近月（说明回退到了远月），显式提示期限错配
        near_hit = any(r["days"] <= 120 for r in picked_rows)
        if grade not in (None, "NONE") and not near_hit:
            used_fallback = True
            fallback_note = (
                "目标近月（14/35/95 天）**均无足够有效报价**，已回退到 "
                + "、".join(f"{r['expiry']}（{r['days']} 天）" for r in picked_rows)
                + f"。以上是全部 {len(future)} 个未来到期日中质量最高的。"
                "⚠️ **长天期读数不能代表近月情绪** —— 期限越长，尾部定价占比越高、"
                "对短期事件敏感度越低。"
            )

        # --- IV 全局闸门（二次保险） ---
        ivs = [r[k] for r in picked_rows
               for k in ("atm_call_iv", "atm_put_iv", "otm_put_iv", "otm_call_iv")
               if r.get(k) is not None]
        iv_sane = len(ivs) >= 2 and min(ivs) >= 5.0
        if not iv_sane:
            for r in picked_rows:
                for k in ("atm_call_iv", "atm_put_iv", "otm_put_iv", "otm_call_iv",
                          "skew_pp", "skew_25d_pp", "skew_10pct_pp"):
                    r[k] = None
            grade = "NONE"

        # --- 期限结构：最近的 ATM 可得日 vs 最远的 ATM 可得日 ---
        # ★★ 2026-10-12：**只有端点是不够的**。实测 GOOG（基准 2026-10-11）ATM IV 逐档为
        #    4天 36.59 → 11天 31.15 → **32天 36.29** → 95天 32.08，
        #    端点斜率仅 −1.98pp ⇒ 旧措辞断言「正向结构是常态，说明近期未被额外定价」，
        #    可**中段 32 天处比相邻两档高出 4~5pp** —— 那正是事件定价的形态
        #    （与 Alphabet Q3 财报落在 10 月底~11 月中吻合）。
        #    ⇒ 端点选择把方向带偏了。故补一个**局部驼峰**判据：
        #    某一档同时高出**左右相邻档** ≥ HUMP_MIN_PP ⇒ 事件定价集中在那个窗口。
        #    判据用「同时高于相邻两档」而非「与端点的差」，因为端点本身就有噪声
        #    （本例近端 4 天反而比 11 天高 5.4pp，纯端点比较无法区分噪声与信号）。
        term = None
        atm_rows = [r for r in profiles
                    if r["atm_put_iv"] is not None and r["atm_call_iv"] is not None]
        if len(atm_rows) >= 2:
            atm_rows.sort(key=lambda r: r["days"])
            near, far = atm_rows[0], atm_rows[-1]
            near_iv = round((near["atm_put_iv"] + near["atm_call_iv"]) / 2, 2)
            far_iv = round((far["atm_put_iv"] + far["atm_call_iv"]) / 2, 2)
            _series = [{"expiry": r["expiry"], "days": r["days"],
                        "atm_iv": round((r["atm_put_iv"] + r["atm_call_iv"]) / 2, 2)}
                       for r in atm_rows]
            hump = None
            for i in range(1, len(_series) - 1):
                cur, lo_, hi_ = _series[i], _series[i - 1], _series[i + 1]
                if (cur["atm_iv"] - lo_["atm_iv"] >= HUMP_MIN_PP
                        and cur["atm_iv"] - hi_["atm_iv"] >= HUMP_MIN_PP):
                    hump = {"expiry": cur["expiry"], "days": cur["days"], "atm_iv": cur["atm_iv"],
                            "excess_pp": round(min(cur["atm_iv"] - lo_["atm_iv"],
                                                   cur["atm_iv"] - hi_["atm_iv"]), 2),
                            "window_from": lo_["expiry"], "window_to": hi_["expiry"]}
                    break
            term = {
                "near_expiry": near["expiry"], "near_days": near["days"],
                "near_atm_iv": near_iv,
                "far_expiry": far["expiry"], "far_days": far["days"],
                "far_atm_iv": far_iv,
                "slope_pp": round(near_iv - far_iv, 2),
                "contango": near_iv < far_iv,
                "atm_series": _series,
                "hump": hump,
            }

        # --- 风险中性偏度替代：OTM put IV ÷ ATM put IV ---
        # 即使 call 侧样本不足，只要 put 侧与 ATM 可得，就能判断
        # 「下行保护相对平价的溢价」，是 skew 方向性的稳健替代。
        put_skew_ratio = None
        for r in picked_rows:
            if r["otm_put_iv"] is not None and r["atm_put_iv"]:
                put_skew_ratio = round(r["otm_put_iv"] / r["atm_put_iv"], 3)
                break

        # --- OI 一致性闸门 ---
        # 实测 yfinance 的 openInterest 在**同一时点**会返回两套相差约 400 倍的
        # 数值：同一张 2026-09-30 到期的合约，同一分钟内先返回 650、再返回
        # 267,390。行数稳定（非限流截断），属字段口径漂移。
        # 后果：任何基于 OI 的结论（P/C(OI)、机构持仓推断）可能错两个数量级，
        # 必须显式标注不可用，而不是静默引用。
        oi_note = None
        if picked_rows:
            tot_call_oi = sum(r["call_oi"] for r in picked_rows)
            tot_call_vol = sum(r["call_volume"] for r in picked_rows)
            if tot_call_vol > 0 and tot_call_oi * 100 < tot_call_vol:
                oi_note = (
                    f"OI 与成交量量级严重不符（CallOI 合计 {tot_call_oi:,} vs "
                    f"CallVol 合计 {tot_call_vol:,}，成交量是 OI 的 "
                    f"{tot_call_vol / max(tot_call_oi, 1):.0f} 倍）。"
                    "疑似 yfinance 在不同调用间返回不同口径的 OI。"
                    "**P/C(OI) 与任何持仓结构结论不可引用**；P/C(Vol) 口径不受影响。"
                )
                for r in picked_rows:
                    r["pc_oi"] = None
                    r["oi_unreliable"] = True

        # --- 新鲜度诊断：区分「闸门正常拒绝」与「上游整体陈旧」 ---
        # ★ 2026-10-16：切到 CBOE 时**跳过该探测**。
        #   原因：probe_option_freshness 走 yfinance，而其判据是「最新成交距今 ≤5 天」。
        #   CBOE 在盘前给的是**上一时段收盘快照**（按设计如此），若仍按该判据探测，
        #   要么走 yfinance 拿到陈旧的残留挂单（假 negative），
        #   要么即便探测 CBOE 也会因「昨日成交」被判 stale —— 两者都是误报。
        #   ⇒ 切源时不再做 stale 探测，改为记录来源与时段说明（见 source / source_note）。
        if cboe_ok:
            freshness = {
                "etf": etf, "expiries_checked": len(future), "min_age_days": None,
                "n_fresh": None, "n_quoted": None, "stale": False,
                "ages_days": [], "in_session": False, "session_note": session_note,
                "source": "cboe_delayed",
                "skipped_reason": "已切 CBOE 源，跳过 yfinance 口径的新鲜度探测",
            }
        else:
            freshness = probe_option_freshness(etf)
            if use_cboe:
                # 想切 CBOE 但没切成功（403 / 网络失败）⇒ 退回 yfinance 主源。
                # 必须**显式记录这层降级**，否则下游会以为走的是 CBOE。
                freshness["cboe_fallback_failed"] = True
                freshness["session_note"] = (
                    f"{session_note}｜⚠️ **但 CBOE 取数未成功，本轮回退 yfinance 主源**"
                    f"（该标的可能无可用期权，如指数符号 / A 股 ETF）"
                )
        stale_note = None
        if freshness.get("stale"):
            # ★ 2026-09-17 修正：此处原先把结论写成「yfinance 数据源的系统性状态」
            # （理由是全市场多标的同样陈旧 42~56 天）。**该归因已被推翻。**
            # 根因是**采集时点**：期权链只在美东 09:30–16:00 实时刷新，
            # 盘前/盘后/休市采集拿到的是上一交易日收盘后的残留挂单，
            # 其 lastTradeDate 已经隔了一整个交易日（在周末/长假后就是数十天）。
            # 同一批标的在美东盘中复测，最新成交距今仅 0.01 天，完全新鲜。
            # 因此 stale 的**正确解读**是「本次采集时点不可用」，而非「该源坏了」。
            stale_note = (
                f"**本次期权快照整体陈旧 ⇒ 全部 IV / 偏斜 / P-C 结论不可引用。**"
                f"扫描 {freshness.get('expiries_checked')} 个未来到期日，"
                f"共 {freshness.get('n_quoted')} 个有双边报价的合约，"
                f"其中**最新一笔成交距今仍有 {freshness.get('min_age_days')} 天**，"
                f"合格（≤{MAX_QUOTE_AGE_DAYS} 天）样本数 = 0。"
                f"**根因是采集时点，不是数据源缺陷**："
                f"{freshness.get('session_note') or ''}"
                " 期权链只在美东 09:30–16:00 实时刷新，盘前/盘后/休市拿到的是"
                "上一交易日的残留挂单。**解决办法是改到美东盘中重采，"
                "而不是把「该源不可用」写成结论。**"
                "本次 IV / 偏斜 / P/C 维度客观上不可得，报告须显式声明缺口。"
            )

        return {
            "etf": etf, "spot": round(spot, 2),
            # ★ 2026-10-16：来源声明（方案 A 时点分支）。下游**必须**在证据包里
            #   声明本轮的 IV/偏斜来自哪个源 —— 两者口径不同、数值不可混用。
            "source": ("cboe_delayed" if cboe_ok else "yfinance"),
            "source_note": _resolve_source_note(use_cboe, cboe_ok, session_note),
            "rate_used": round(rate, 4), "div_yield_used": div_yield,
            "div_note": div_note,
            "freshness": freshness,
            "stale_note": stale_note,
            "by_expiry": picked_rows,
            "n_expiries_scanned": len(profiles),
            "n_expiries_total": len(future),
            "iv_available": bool(iv_sane and grade != "NONE"),
            "iv_grade": grade,
            "atm_available": bool(iv_sane and any(
                r["atm_call_iv"] is not None and r["atm_put_iv"] is not None
                for r in picked_rows)),
            "skew_available": bool(iv_sane and any(
                r["skew_25d_pp"] is not None for r in picked_rows)),
            "skew_basis": next((r["skew_basis"] for r in picked_rows
                                if r["skew_basis"]), None),
            "one_sided_put_iv": next((r["otm_put_iv"] for r in picked_rows
                                      if r["otm_put_iv"] is not None), None),
            "put_skew_ratio": put_skew_ratio,
            "term_structure": term,
            "oi_note": oi_note,
            "used_fallback": used_fallback, "fallback_note": fallback_note,
            "iv_note": None if (iv_sane and grade != "NONE") else (
                "无有效双边报价，或自解 IV 落在垃圾区间，已屏蔽全部 IV/偏斜字段。"
            ),
            "quote_age_filter_days": MAX_QUOTE_AGE_DAYS,
            "all_expiry_scan": [
                {"expiry": r["expiry"], "days": r["days"],
                 "n_quoted_call": r["n_quoted_call"],
                 "n_quoted_put": r["n_quoted_put"],
                 "grade": _grade_of(r)}
                for r in sorted(profiles, key=lambda x: x["days"])
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


# ----------------------------------------------------------------------------
# 决议日波动率 / 债券代理通道（弥补 FRED 的 T+2 lag）
# ----------------------------------------------------------------------------
VOL_PROXIES = ("^VIX", "^VXN", "VIXY", "VXX", "UVXY")
BOND_PROXIES = ("TLT", "IEF", "SHY", "^TNX")


def fetch_volatility_proxies(as_of: str, days: int = 8) -> dict:
    """取 VIX/VXN 及其 ETF 代理、以及债券 ETF 的**日线 OHLC 区间**。

    **为什么需要这个通道**：FRED 的 ``VIXCLS`` 与 ``DGS10`` 属于 H.15 系列，
    有约一个工作日的发布滞后。实测 2026-09-17 20:0x（北京）时，FRED 上
    VIXCLS/DGS10 的最新观测仍是 **2026-09-15**，9/16 与 9/17 都不存在；
    而 9/16 恰是 FOMC 决议日（振幅放大 98%、量能 131.6%）。报告因此只能写
    「决议日真实波动率数据缺失」，把一个本可回答的问题留成缺口。

    实际上 yfinance 对 ``^VIX`` / ``^VXN`` 提供**当日日线 OHLC**（High/Low 区间），
    债券端还可用 TLT / IEF / SHY 的当日行情与成交量做交叉验证。
    这些都不是「决议日恐慌温度」的完美读数（VIX 本身是 30 天前瞻波动率，
    且 ETF 有跟踪损耗），但比「完全缺失」强得多，且可交叉验证。

    返回 dict：``{"proxies": [...], "as_of_bar": str, "notes": [...]}``
    """
    import yfinance as yf

    out: dict = {"proxies": [], "notes": []}
    tickers = list(VOL_PROXIES) + list(BOND_PROXIES)
    for tkr in tickers:
        try:
            h = yf.Ticker(tkr).history(period=f"{days}d")
            if h.empty:
                out["notes"].append(f"{tkr}: 无数据")
                continue
            rows = []
            for idx, r in h.tail(days).iterrows():
                rows.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": round(float(r["Open"]), 2) if r["Open"] == r["Open"] else None,
                    "high": round(float(r["High"]), 2) if r["High"] == r["High"] else None,
                    "low": round(float(r["Low"]), 2) if r["Low"] == r["Low"] else None,
                    "close": round(float(r["Close"]), 2) if r["Close"] == r["Close"] else None,
                    "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else None,
                })
            out["proxies"].append({"ticker": tkr, "bars": rows,
                                   "last_date": rows[-1]["date"] if rows else None})
        except Exception as exc:  # noqa: BLE001
            out["notes"].append(f"{tkr}: {type(exc).__name__}: {exc}")

    # 决议日盘中振幅（High/Low 刻画「当日恐慌峰值 vs 收盘」）。
    # 对**全部**代理都算，不只 VIX/VXN —— 债券端（TLT/IEF/SHY）的振幅与成交量
    # 一样是「决议当日久期端换手是否异常」的直接读数。
    for p in out["proxies"]:
        for b in p["bars"]:
            if b.get("high") and b.get("low") and b.get("low") > 0:
                b["intraday_range_pct"] = round((b["high"] - b["low"]) / b["low"] * 100, 2)
                # ^TNX 的数值是百分数（4.97 = 4.97%），振幅要按**基点变化**给，
                # 不能按相对百分比（4.94→5.01 是 +7bp，不是 +1.42%）。
                if p["ticker"] == "^TNX":
                    b["range_bp"] = round((b["high"] - b["low"]) * 100, 1)
            if b.get("high") and b.get("close"):
                b["close_vs_high_pct"] = round((b["close"] - b["high"]) / b["high"] * 100, 2)

    out["as_of_bar"] = as_of
    return out


# ----------------------------------------------------------------------------
# 市场广度
# ----------------------------------------------------------------------------
def _download_close_chunked(tickers: list[str], period: str = "1y",
                            chunk: int = 20, retries: int = 2):
    """分块下载成分股收盘价矩阵，对失败代码做整轮重试。

    **为什么不能一次性传 101 个代码**：实测（2026-09-16）单次 ``yf.download`` 传全量
    101 只时，会稳定出现约 27 只返回 ``possibly delisted; no price data found``——
    其中包含 AAPL / AMZN / COST 这类不可能退市的代码，实为**批量请求限流**。
    后果是广度样本从 95 只缩到 70~72 只（覆盖率约 70%），且因样本变小而波动
    （同一份数据两次采集得出 52.9% 与 55.6% 两个不同的 200SMA 覆盖率）。

    改为每批 20 只、失败代码整轮重试 2 次，覆盖率可接近全量，结果可复现。

    返回 ``None`` 表示全部失败。
    """
    import pandas as pd
    import yfinance as yf

    frames: list = []
    pending = list(tickers)
    for _ in range(retries + 1):
        if not pending:
            break
        failed: list[str] = []
        for i in range(0, len(pending), chunk):
            batch = pending[i: i + chunk]
            try:
                data = yf.download(batch, period=period, progress=False,
                                   auto_adjust=False, threads=False)
            except Exception:  # noqa: BLE001
                failed.extend(batch)
                continue
            if data is None or getattr(data, "empty", True):
                failed.extend(batch)
                continue
            try:
                c = data["Close"]
            except Exception:  # noqa: BLE001
                failed.extend(batch)
                continue
            if isinstance(c, pd.Series):
                c = c.to_frame(name=batch[0])
            got = [t for t in batch if t in c.columns and c[t].notna().any()]
            if got:
                frames.append(c[got])
            failed.extend(t for t in batch if t not in got)
        pending = failed
        if pending:
            time.sleep(1.0)

    if not frames:
        return None
    close = pd.concat(frames, axis=1)
    return close.loc[:, ~close.columns.duplicated()]


def compute_breadth(tickers: list[str]) -> dict:
    """用成分股 1 年日线计算广度指标与等权/加权背离。"""
    import pandas as pd

    close = _download_close_chunked(tickers)
    if close is None:
        return {"error": "成分股价格下载全部失败"}

    recs = []
    for tk in tickers:
        if tk not in close.columns:
            continue
        c = close[tk].dropna()
        if len(c) < 180:
            continue
        last = float(c.iloc[-1])
        sma50 = float(c.rolling(50).mean().iloc[-1])
        sma200 = float(c.rolling(200).mean().iloc[-1])
        recs.append(
            {
                "ticker": tk,
                "last": last,
                "above_200": last > sma200,
                "above_50": last > sma50,
                "ret20": (last / float(c.iloc[-21]) - 1) * 100 if len(c) > 21 else None,
                "ret60": (last / float(c.iloc[-61]) - 1) * 100 if len(c) > 61 else None,
                "ret120": (last / float(c.iloc[-121]) - 1) * 100 if len(c) > 121 else None,
            }
        )

    if not recs:
        return {"error": "无有效成分股价格数据"}

    df = pd.DataFrame(recs)
    n = len(df)

    def _pct(series) -> float:
        return round(float(series.mean()) * 100, 1)

    return {
        "n_universe": len(tickers),
        "n_valid": n,
        "pct_above_200sma": _pct(df["above_200"]),
        "pct_above_50sma": _pct(df["above_50"]),
        "pct_up_20d": _pct(df["ret20"] > 0),
        "pct_up_60d": _pct(df["ret60"] > 0),
        "pct_up_120d": _pct(df["ret120"] > 0),
        "median_ret20": round(float(df["ret20"].median()), 2),
        "median_ret60": round(float(df["ret60"].median()), 2),
        "equal_weight_ret20": round(float(df["ret20"].mean()), 2),
        "equal_weight_ret60": round(float(df["ret60"].mean()), 2),
        "dispersion_ret20": round(float(df["ret20"].std()), 2),
        "candidates": df.to_dict(orient="records"),
    }


# ----------------------------------------------------------------------------
# 聚合估值与盈利质量
# ----------------------------------------------------------------------------
def aggregate_valuation(infos: dict[str, dict], universe: list[str]) -> dict:
    """按市值加权聚合出指数级估值与盈利质量（调和口径）。"""
    rows = []
    missing = []
    for tk in universe:
        i = infos.get(tk) or {}
        mc = i.get("marketCap")
        if i.get("_error") or not mc:
            missing.append(tk)
            continue
        rows.append(
            {
                "ticker": tk,
                "name": i.get("_name", tk),
                "marketCap": float(mc),
                "sector": i.get("sector") or "Unknown",
                "pe": i.get("trailingPE"),
                "fpe": i.get("forwardPE"),
                "pb": i.get("priceToBook"),
                "ps": i.get("priceToSalesTrailing12Months"),
                "roe": i.get("returnOnEquity"),
                "net_margin": i.get("profitMargins"),
                "gross_margin": i.get("grossMargins"),
                "op_margin": i.get("operatingMargins"),
                "rev_growth": i.get("revenueGrowth"),
                "eps_growth": i.get("earningsGrowth"),
                "div_yield": i.get("dividendYield"),
                "beta": i.get("beta"),
            }
        )

    if not rows:
        return {"error": "无有效成分股基本面数据"}

    total_mc = sum(r["marketCap"] for r in rows)

    def _sector_sum():
        acc: dict[str, float] = {}
        for r in rows:
            acc[r["sector"]] = acc.get(r["sector"], 0.0) + r["marketCap"]
        return sorted(
            [(k, round(v / total_mc * 100, 2)) for k, v in acc.items()],
            key=lambda x: -x[1],
        )

    # --- 盈利型聚合：净利润 = 市值 / PE（仅取 PE > 0 的公司）---
    earn = [r for r in rows if isinstance(r["pe"], (int, float)) and r["pe"] and r["pe"] > 0]
    excl_pe = [r["ticker"] for r in rows if r not in earn]
    mc_earn = sum(r["marketCap"] for r in earn)
    net_income = sum(r["marketCap"] / r["pe"] for r in earn)
    agg_pe = round(mc_earn / net_income, 2) if net_income > 0 else None

    # --- 前瞻口径 ---
    fwd = [r for r in rows if isinstance(r["fpe"], (int, float)) and r["fpe"] and r["fpe"] > 0]
    mc_fwd = sum(r["marketCap"] for r in fwd)
    fwd_income = sum(r["marketCap"] / r["fpe"] for r in fwd)
    agg_fpe = round(mc_fwd / fwd_income, 2) if fwd_income > 0 else None

    # --- 净资产 / 营收 ---
    # ★★ 必须设「合理区间」，不能只判 > 0（2026-09-18 SPX 实测的血案）：
    #    `净资产 = Σ(市值 / PB)`。只要有**一只**成分股的 PB 是坏值（极小），
    #    它就能把 Σ净资产 放大若干数量级，同时毁掉 agg_pb 与 agg_roe —— 而且
    #    **两个数字都不会越界报警，看上去只是「偏得离谱」**。
    #    实测：BRK-B 的 priceToBook 返回 **0.000975** ⇒ 其隐含净资产 = 1117.9 万亿，
    #    占全样本 Σ净资产 的 **98.9%**，使 agg_pb 由正确的 **5.59 → 0.06**、
    #    agg_roe 由约 24% → **0.27%**。
    #    （NDX 101 只未触发，SPX 503 只才暴露 —— 样本越大越容易踩到坏值。）
    #    下界 0.2 = 净资产最多为市值的 5 倍；实测只剔除该坏值、市值留存 98.5%，
    #    且任何落在 (0.001, 0.81) 的阈值结果一致（PB 分位 P1=0.81），说明隔离稳健。
    PB_MIN, PB_MAX = 0.2, 1000.0
    PS_MIN, PS_MAX = 0.02, 5000.0

    def _ratio_ok(v, lo, hi) -> bool:
        return isinstance(v, (int, float)) and bool(v) and lo <= v <= hi

    bv = [r for r in rows if _ratio_ok(r["pb"], PB_MIN, PB_MAX)]
    mc_bv = sum(r["marketCap"] for r in bv)
    book = sum(r["marketCap"] / r["pb"] for r in bv)
    agg_pb = round(mc_bv / book, 2) if book > 0 else None

    rev = [r for r in rows if _ratio_ok(r["ps"], PS_MIN, PS_MAX)]
    mc_rev = sum(r["marketCap"] for r in rev)
    revenue = sum(r["marketCap"] / r["ps"] for r in rev)
    agg_ps = round(mc_rev / revenue, 2) if revenue > 0 else None

    # 被区间剔除的标的（供证据包披露，便于人工复核；正常应为空或极少）
    excl_pb = [
        f"{r['ticker']}({r['pb']:g})" for r in rows
        if isinstance(r.get("pb"), (int, float)) and r["pb"]
        and not (PB_MIN <= r["pb"] <= PB_MAX)
    ]
    excl_ps = [
        f"{r['ticker']}({r['ps']:g})" for r in rows
        if isinstance(r.get("ps"), (int, float)) and r["ps"]
        and not (PS_MIN <= r["ps"] <= PS_MAX)
    ]

    # --- 聚合 ROE 与净利率：Σ净利 / Σ净资产、Σ净利 / Σ营收 ---
    agg_roe = round(net_income / book * 100, 2) if book > 0 else None
    agg_net_margin = round(net_income / revenue * 100, 2) if revenue > 0 else None

    # --- 股息率：Σ股息 / Σ市值（dividendYield 为百分数）---
    div_sum = sum(r["marketCap"] * (r["div_yield"] / 100.0) for r in rows if isinstance(r["div_yield"], (int, float)))
    agg_div = round(div_sum / total_mc * 100, 2)

    # --- 增长与利润率：市值加权平均；beta 不是百分数，须单独处理 ---
    def _wavg(key, as_pct=True):
        vals = [(r["marketCap"], r[key]) for r in rows if isinstance(r[key], (int, float))]
        if not vals:
            return None
        tot = sum(w for w, _ in vals)
        if not tot:
            return None
        v = sum(w * x for w, x in vals) / tot
        return round(v * 100, 2) if as_pct else round(v, 2)

    def _median(key, as_pct=True):
        vals = [r[key] for r in rows if isinstance(r[key], (int, float))]
        if not vals:
            return None
        v = float(statistics.median(vals))
        return round(v * 100, 2) if as_pct else round(v, 2)

    agg_rev_growth = _wavg("rev_growth")
    agg_eps_growth = _wavg("eps_growth")
    agg_gross = _wavg("gross_margin")
    agg_op = _wavg("op_margin")
    agg_beta = _wavg("beta", as_pct=False)
    med_rev_growth = _median("rev_growth")
    med_eps_growth = _median("eps_growth")
    med_beta = _median("beta", as_pct=False)

    # --- 集中度 ---
    by_mc = sorted(rows, key=lambda r: -r["marketCap"])
    top10 = by_mc[:10]
    top10_share = round(sum(r["marketCap"] for r in top10) / total_mc * 100, 2)
    top20_share = round(sum(r["marketCap"] for r in by_mc[:20]) / total_mc * 100, 2)
    hhi = round(sum((r["marketCap"] / total_mc * 100) ** 2 for r in rows), 1)

    return {
        "n_total": len(rows),
        "n_missing": len(missing),
        "missing": missing,
        "total_market_cap": round(total_mc, 0),
        "agg_pe": agg_pe,
        "agg_forward_pe": agg_fpe,
        "agg_pb": agg_pb,
        "agg_ps": agg_ps,
        "agg_roe_pct": agg_roe,
        "agg_net_margin_pct": agg_net_margin,
        "agg_gross_margin_pct": agg_gross,
        "agg_op_margin_pct": agg_op,
        "agg_div_yield_pct": agg_div,
        "agg_rev_growth_pct": agg_rev_growth,
        "agg_eps_growth_pct": agg_eps_growth,
        "agg_rev_growth_median_pct": med_rev_growth,
        "agg_eps_growth_median_pct": med_eps_growth,
        "agg_beta": agg_beta,
        "median_beta": med_beta,
        "earnings_yield_pct": round(100.0 / agg_pe, 2) if agg_pe else None,
        "excluded_pe_tickers": excl_pe,
        "excluded_pb_range": excl_pb,
        "excluded_ps_range": excl_ps,
        "n_pe_used": len(earn),
        "sector_weights": _sector_sum(),
        "top10_by_weight": [
            {
                "ticker": r["ticker"],
                "name": r["name"],
                "marketCap": r["marketCap"],
                "weight_pct": round(r["marketCap"] / total_mc * 100, 2),
                "pe": r["pe"],
                "fpe": r["fpe"],
                "pb": r["pb"],
            }
            for r in top10
        ],
        "top10_weight_pct": top10_share,
        "top20_weight_pct": top20_share,
        "hhi": hhi,
        "constituents": rows,
    }


# ----------------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------------
def collect_index(as_of: str, lookback_days: int, with_news: bool, with_social: bool,
                  top_insiders: int, index_key: str = DEFAULT_INDEX) -> dict:
    cfg = _select_index(index_key)
    display = cfg["display"]
    pool_label = cfg["pool_label"]
    router = _get_router()
    start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=lookback_days)).isoformat()

    raw_pool = cfg["pool_fn"]()
    universe = _clean_universe(raw_pool)
    health: dict[str, str] = {}
    blocks: list[str] = []

    blocks.append(f"# 证据包：{display}（{index_key}）")
    blocks.append(
        f"- 采集日期: {as_of}\n"
        f"- 指数代码: {INDEX_TICKER}（ETF 代理: {ETF_PROXY}）\n"
        f"- 行情窗口: {start} ~ {as_of}（{lookback_days} 自然日）\n"
        f"- 成分股池: {pool_label}（{len(raw_pool)} 项，去重后 {len(universe)} 只）\n"
        f"- 说明: 本文件不含任何 LLM 输出，纯原始证据。指数无财报，估值/盈利/广度均由成分股聚合得出。"
    )

    # --- 1. 指数行情 ---
    status, text = _safe_call("get_stock_data", router, "get_stock_data", INDEX_TICKER, start, as_of)
    price_block, price_stats = _price_summary(text)
    health["index:get_stock_data"] = status
    blocks.append(f"## 1. 指数行情与价格结构\n\n```\n{price_block}\n```")

    # --- 2. 指数技术指标 ---
    ind_lines = []
    for ind in TECH_INDICATORS:
        st, txt = _safe_call("get_indicators", router, "get_indicators", INDEX_TICKER, ind, as_of, _INDICATOR_LOOKBACK)
        health[f"index:indicator:{ind}"] = st
        ind_lines.append(f"### {ind}\n```\n{_compact_series(txt)}\n```")
    blocks.append("## 2. 指数技术指标\n\n" + "\n\n".join(ind_lines))

    # --- 3. ETF 代理估值 ---
    st, txt = _safe_call("get_fundamentals", router, "get_fundamentals", ETF_PROXY, as_of)
    health["etf:get_fundamentals"] = st
    blocks.append(f"## 3. {ETF_PROXY}（ETF 代理）基本面快照\n\n```\n{txt}\n```")

    # --- 4. 市场广度 ---
    print("  [1/6] 计算市场广度 ...", flush=True)
    try:
        breadth = compute_breadth(universe)
        health["breadth"] = "error" if breadth.get("error") else "ok"
    except Exception as exc:  # noqa: BLE001
        breadth = {"error": f"{type(exc).__name__}: {exc}"}
        health["breadth"] = "fail"

    if breadth.get("error"):
        blocks.append(f"## 4. 市场广度\n\n(不可用: {breadth['error']})")
    else:
        cands = sorted(
            [c for c in breadth["candidates"] if c.get("ret20") is not None],
            key=lambda c: -c["ret20"],
        )
        rows_txt = "\n".join(
            f"  {c['ticker']:<6} 20日 {c['ret20']:>7.2f}%  60日 {(c['ret60'] or 0):>7.2f}%  "
            f"120日 {(c['ret120'] or 0):>8.2f}%  {'>200SMA' if c['above_200'] else '      '}  {'>50SMA' if c['above_50'] else ''}"
            for c in cands[:15]
        )
        bottom_txt = "\n".join(
            f"  {c['ticker']:<6} 20日 {c['ret20']:>7.2f}%  60日 {(c['ret60'] or 0):>7.2f}%  "
            f"120日 {(c['ret120'] or 0):>8.2f}%"
            for c in cands[-10:]
        )
        blocks.append(
            "## 4. 市场广度（成分股聚合）\n\n"
            f"- 有效样本: {breadth['n_valid']} 只"
            f"（成分股池 {breadth.get('n_universe', '?')} 只，覆盖率 "
            f"{round(breadth['n_valid'] / breadth['n_universe'] * 100, 1) if breadth.get('n_universe') else '?'}%）\n"
            f"- **站上 200SMA 比例: {breadth['pct_above_200sma']}%**\n"
            f"- **站上 50SMA 比例: {breadth['pct_above_50sma']}%**\n"
            f"- 20 日收涨家数占比: {breadth['pct_up_20d']}%\n"
            f"- 60 日收涨家数占比: {breadth['pct_up_60d']}%\n"
            f"- 120 日收涨家数占比: {breadth['pct_up_120d']}%\n"
            f"- 成分股 20 日收益中位数: {breadth['median_ret20']}%（等权均值 {breadth['equal_weight_ret20']}%）\n"
            f"- 成分股 60 日收益中位数: {breadth['median_ret60']}%（等权均值 {breadth['equal_weight_ret60']}%）\n"
            f"- 20 日收益离散度（标准差）: {breadth['dispersion_ret20']}%\n\n"
            f"### 20 日涨幅前 15 名\n```\n{rows_txt}\n```\n\n"
            f"### 20 日涨幅后 10 名\n```\n{bottom_txt}\n```"
        )

    # --- 5. 成分结构与聚合估值 ---
    print(f"  [2/6] 拉取 {len(universe)} 只成分股基本面（约 20s）...", flush=True)
    infos = fetch_universe_infos(universe)
    ok_cnt = sum(1 for v in infos.values() if not v.get("_error"))
    health["constituents:info"] = "ok" if ok_cnt > len(universe) * 0.8 else "partial"

    val = aggregate_valuation(infos, universe)
    health["aggregate_valuation"] = "error" if val.get("error") else "ok"

    holdings = fetch_top_holdings()
    health["etf:top_holdings"] = "ok" if holdings else "unavailable"

    if val.get("error"):
        blocks.append(f"## 5. 成分结构聚合\n\n(不可用: {val['error']})")
    else:
        sec_txt = "\n".join(f"  {name:<34} {w:>6.2f}%" for name, w in val["sector_weights"])
        hold_txt = "\n".join(
            f"  {h['symbol']:<6} {h['name'][:38]:<38} {h['weight_pct']:>6.2f}%" for h in holdings
        ) or "  (不可用)"
        hold_sum = round(sum(h["weight_pct"] for h in holdings), 2) if holdings else None
        top10_txt = "\n".join(
            f"  {r['ticker']:<6} {r['name'][:30]:<30} 权重 {r['weight_pct']:>5.2f}%  "
            f"市值 {r['marketCap']/1e9:>8.1f}B  PE {str(r['pe'] or 'N/A'):>9}  FwdPE {str(r['fpe'] or 'N/A'):>8}  PB {str(r['pb'] or 'N/A'):>7}"
            for r in val["top10_by_weight"]
        )
        blocks.append(
            "## 5. 成分结构与聚合估值\n\n"
            f"### 5.1 {ETF_PROXY} 真实持仓权重（前十大，ETF 跟踪 {index_key}）\n```\n"
            f"{hold_txt}\n```\n\n"
            "### 5.2 市值加权聚合估值（调和口径：Σ市值 / Σ盈利）\n"
            f"- **聚合 PE (TTM): {val['agg_pe']}**（基于 {val['n_pe_used']} 只有正盈利的成分股）\n"
            f"- **聚合 Forward PE: {val['agg_forward_pe']}**\n"
            f"- **聚合 PB: {val['agg_pb']}**\n"
            f"- **聚合 PS: {val['agg_ps']}**\n"
            f"- **盈利收益率（1/PE）: {val['earnings_yield_pct']}%**\n"
            f"- 聚合股息率: {val['agg_div_yield_pct']}%\n"
            f"- 聚合 ROE: {val['agg_roe_pct']}%（口径：Σ净利 / Σ净资产）\n"
            f"- 聚合净利率: {val['agg_net_margin_pct']}%（加权毛利率 {val['agg_gross_margin_pct']}%，加权营业利润率 {val['agg_op_margin_pct']}%）\n"
            f"- 加权营收增速: {val['agg_rev_growth_pct']}%（成分股中位数 {val['agg_rev_growth_median_pct']}%）\n"
            f"- 加权盈利增速: {val['agg_eps_growth_pct']}%（成分股中位数 {val['agg_eps_growth_median_pct']}%）\n"
            f"- 加权 Beta: {val['agg_beta']}（成分股中位数 {val['median_beta']}）\n"
            f"- 无正盈利被剔除: {len(val['excluded_pe_tickers'])} 只 {val['excluded_pe_tickers']}\n"
            f"- 数据缺失: {val['n_missing']} 只 {val['missing']}\n\n"
            "### 5.3 集中度（两种口径必须区分）\n"
            f"- 参与聚合总市值: {val['total_market_cap']/1e12:.3f} 万亿美元\n"
            f"- **【官方口径】{ETF_PROXY} 前十大权重合计: {hold_sum}%**（修正市值加权，对超大权重设上限）\n"
            f"- 【推算口径】纯市值加权前十大合计: {val['top10_weight_pct']}%（若不设权重上限）\n"
            f"- 纯市值加权前二十大合计: {val['top20_weight_pct']}%\n"
            f"- HHI 集中度指数（纯市值口径）: {val['hhi']}\n"
            f"- 说明: 两个口径的差额，反映 {display}「修正市值加权」机制人为压制集中度的程度。\n\n"
            "### 5.4 前十大成分股（按市值）\n```\n"
            f"{top10_txt}\n```\n\n"
            "### 5.5 行业权重（按市值）\n```\n"
            f"{sec_txt}\n```"
        )

    # --- 6. 成分股内部人聚合 ---
    print(f"  [3/6] 聚合前 {top_insiders} 大权重股内部人交易 ...", flush=True)
    insiders: list[dict] = []
    if val.get("top10_by_weight") and top_insiders > 0:
        top_syms = [r["ticker"] for r in val["top10_by_weight"]][:top_insiders]
        # 前十大不足时用广度里的候选补齐
        if len(top_syms) < top_insiders and breadth.get("candidates"):
            extra = [c["ticker"] for c in sorted(breadth["candidates"], key=lambda c: -c["last"])]
            for t in extra:
                if len(top_syms) >= top_insiders:
                    break
                if t not in top_syms:
                    top_syms.append(t)
        insiders = fetch_insiders(top_syms, router)
        health["constituents:insiders"] = "ok" if insiders else "unavailable"
    else:
        health["constituents:insiders"] = "skipped"

    if insiders:
        ib = sum(r["buy_value"] for r in insiders)
        isv = sum(r["sell_value"] for r in insiders)
        bs = sum(r["buy_shares"] for r in insiders)
        ss = sum(r["sell_shares"] for r in insiders)
        det = "\n".join(
            f"  {r['ticker']:<6} 买入 {r['buy_shares']:>9,} 股 / {r['buy_value']:>14,.0f} 美元   "
            f"卖出 {r['sell_shares']:>9,} 股 / {r['sell_value']:>15,.0f} 美元"
            for r in insiders
        )
        blocks.append(
            "## 6. 成分股内部人交易聚合（指数级内部人态度代理）\n\n"
            f"- 覆盖: 前 {len(insiders)} 大权重股（指数本身无内部人交易）\n"
            f"- **买入合计: {bs:,} 股 / {ib:,.0f} 美元**\n"
            f"- **卖出合计: {ss:,} 股 / {isv:,.0f} 美元**\n"
            f"- **买卖金额比（卖/买）: {(isv / ib) if ib > 0 else float('inf'):.1f}x**\n\n"
            f"```\n{det}\n```"
        )

    # --- 7. 新闻 ---
    if with_news:
        st, txt = _safe_call("get_news", router, "get_news", INDEX_TICKER, start, as_of)
        health["index:get_news"] = st
        blocks.append(f"## 7. 指数相关新闻\n\n{txt}")

        st, txt = _safe_call("get_global_news", router, "get_global_news", as_of, 7, 10)
        health["get_global_news"] = st
        blocks.append(f"## 8. 全球宏观新闻\n\n{txt}")
    else:
        health["index:get_news"] = health["get_global_news"] = "skipped"

    # --- 8. 社媒（ETF 代理）---
    if with_social:
        social_start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=7)).isoformat()
        social_lines = []
        for label, fn in (("StockTwits", _stocktwits_block), ("Reddit", _reddit_block)):
            st, txt = _safe_call(label, fn, ETF_PROXY, social_start, as_of)
            health[f"social:{label}"] = st
            social_lines.append(f"### {label}（${ETF_PROXY}）\n{txt}")
        blocks.append(
            f"## 9. 社媒情绪（{ETF_PROXY} 代理，窗口 {social_start} ~ {as_of}）\n\n"
            + "\n\n".join(social_lines)
        )
    else:
        health["social:StockTwits"] = health["social:Reddit"] = "skipped"

    # --- 9. 预测市场 ---
    pm_lines = []
    for topic in PREDICTION_TOPICS:
        st, txt = _safe_call("get_prediction_markets", router, "get_prediction_markets", topic)
        health[f"prediction:{topic}"] = st
        pm_lines.append(f"### {topic}\n{txt}")
    blocks.append("## 10. 预测市场（Polymarket 隐含概率）\n\n" + "\n\n".join(pm_lines))

    # --- 10. 宏观 ---
    macro_lines = []
    for alias in MACRO_ALIASES:
        # FRED 是瞬时故障最多的通道（TLS 握手 / 连接重置），给 2 次重试
        st, txt = _safe_call("get_macro_indicators", router, "get_macro_indicators",
                             alias, as_of, 365, retries=2)
        health[f"macro:{alias}"] = st
        macro_lines.append(f"### {alias}\n```\n{_compact_macro(txt)}\n```")
    blocks.append("## 11. 宏观经济指标（FRED）\n\n" + "\n\n".join(macro_lines))

    # --- 12. 决议日波动率 / 债券代理（弥补 FRED 的 T+2 lag） ---
    print("  [4/6] 采集波动率与债券代理通道（弥补 FRED 发布滞后）...", flush=True)
    try:
        vp = fetch_volatility_proxies(as_of)
        health["vol_proxies"] = "ok" if vp.get("proxies") else "unavailable"
        vl = []
        for p in vp.get("proxies", []):
            rows = [b for b in p["bars"] if b.get("close") is not None]
            if not rows:
                continue
            vl.append(f"### {p['ticker']}（最近 {len(rows)} 个交易日）")
            vl.append("```")
            vl.append("  日期        开      高      低      收            成交量   日振幅%  收盘距高点%")
            for b in rows:
                rg = f"{b.get('intraday_range_pct'):>7.2f}" if b.get("intraday_range_pct") is not None else "      -"
                cv = f"{b.get('close_vs_high_pct'):>11.2f}" if b.get("close_vs_high_pct") is not None else "          -"
                vol = f"{b['volume']:>15,}" if b.get("volume") else f"{'无成交量数据':>15}"
                vl.append(f"  {b['date']}  {b['open']:>7} {b['high']:>7} {b['low']:>7} "
                          f"{b['close']:>7} {vol} {rg} {cv}")
            if p["ticker"] == "^TNX":
                vl.append("")
                vl.append("  （^TNX 为单位=百分数的收益率，日振幅另按基点计："
                          + "  ".join(f"{b['date'][5:]}={b.get('range_bp')}bp"
                                      for b in rows if b.get("range_bp") is not None) + "）")
            vl.append("```")
            vl.append("")
        if vp.get("notes"):
            vl.append("**通道说明**：" + "；".join(vp["notes"]))
        blocks.append(
            "## 12. 决议日波动率与债券代理通道\n\n"
            "- **为什么单独列一节**：FRED 的 VIXCLS / DGS10 属 H.15 系列，有约一个工作日发布滞后，"
            "最新观测往往停在决议日的**前一天**。本节用 yfinance 的当日日线 OHLC 补上"
            "「决议日当天真实盘中区间」，使「决议日恐慌是否升温」可被回答而非留白。\n"
            "- **口径限制（必须声明）**：^VIX / ^VXN 是 **30 天前瞻隐含波动率**，"
            "不是当日已实现波动率；ETF 代理（VIXY/VXX/UVXY）有期货展期与跟踪损耗，"
            "**不能线性换算回 VIX 点位**，仅用于「方向与量级」交叉验证。"
            "债券 ETF（TLT/IEF/SHY）同理，只能定性说明久期端的资金流向。\n\n"
            + "\n".join(vl)
        )
    except Exception as exc:  # noqa: BLE001
        health["vol_proxies"] = "error"
        blocks.append(f"## 12. 决议日波动率与债券代理通道\n\n(不可用: {type(exc).__name__}: {exc})")

    # --- 13. 期权市场内部结构 ---
    print(f"  [5/6] 采集期权市场内部结构（{ETF_PROXY} 代理，全到期日扫描 + BSM 自解 IV）...",
          flush=True)
    opts = fetch_option_structure(ETF_PROXY)
    if opts.get("error"):
        health["etf:option_structure"] = "error"
        blocks.append(f"## 13. 期权市场内部结构\n\n(不可用: {opts['error']})")
    else:
        grade = opts.get("iv_grade", "NONE")
        fresh = opts.get("freshness") or {}
        health["etf:option_structure"] = "ok"
        # 健康度按粒度登记，避免下游把「只有单边 put IV」当成「偏斜可用」
        if grade == "FULL":
            health["etf:option_iv"] = "ok"
        elif grade in ("SKEW_ONLY", "ATM_ONLY", "PARTIAL_2SIDE", "PARTIAL"):
            health["etf:option_iv"] = f"partial({grade})"
        else:
            health["etf:option_iv"] = "unavailable"
        if opts.get("skew_available"):
            health["etf:option_skew"] = "ok"
        if opts.get("oi_note"):
            health["etf:option_oi"] = "unavailable"
        # 新鲜度单独登记：这是区分「上游陈旧」与「闸门正常拒绝」的关键标记
        if fresh.get("stale"):
            health["etf:option_quote_freshness"] = "stale"
        elif fresh.get("n_fresh"):
            health["etf:option_quote_freshness"] = "ok"

        def o_iv(r: dict) -> str:
            """每个到期日一行的 IV 摘要。按实际可得字段动态拼接。"""
            parts = []
            if r["atm_call_iv"] is not None and r["atm_put_iv"] is not None:
                parts.append(f"ATM_C {r['atm_call_iv']:>6}  ATM_P {r['atm_put_iv']:>6}")
            if r["skew_25d_pp"] is not None:
                parts.append(
                    f"25Δ偏斜 {r['skew_25d_pp']:>6}pp"
                    f"(put {r['skew_25d_mn']}% / call {r['skew_25d_call_mn']}%, "
                    f"n={r['n_skew_put']}/{r['n_skew_call']})")
            elif r["otm_put_iv"] is not None:
                parts.append(f"单边OTM_PutIV {r['otm_put_iv']:>6}(n={r['n_otm_put']})")
            if r["skew_10pct_pp"] is not None:
                parts.append(f"±10%口径 {r['skew_10pct_pp']:>6}pp")
            return ("   " + "  ".join(parts)) if parts else "   【无有效 IV】"

        olines = "\n".join(
            f"  {r['expiry']}（{r['days']:>4}天） 有效 C{r['n_quoted_call']:>3}/P{r['n_quoted_put']:>3}"
            f"  P/C(Vol) {str(r['pc_volume']):>6}" + o_iv(r)
            for r in opts["by_expiry"]
        ) or "  （无任何到期日有新鲜报价）"

        # 全部到期日扫描表 —— 证明「不是没取，是真的没有」
        scan = opts.get("all_expiry_scan") or []
        if scan:
            slines = "\n".join(
                f"  {x['expiry']}（{x['days']:>4}天） 有效 C{x['n_quoted_call']:>3}/P{x['n_quoted_put']:>3}"
                f"  等级 {x['grade'] or '—'}"
                for x in scan
            )
        else:
            slines = "  （未记录）"

        notes = []

        # ★ 新鲜度诊断置顶：这是本次最重要的结论
        if fresh.get("stale"):
            notes.append(
                "- \U0001f6a8 **本次期权快照整体陈旧，全部 IV / 偏斜 / P/C 结论不可用。**\n"
                f"  扫描 {fresh.get('expiries_checked')} 个未来到期日，"
                f"共 {fresh.get('n_quoted')} 个有双边报价的合约，"
                f"**最新一笔成交距今仍有 "
                f"{fresh.get('min_age_days')} 天**，"
                f"合格（≤{opts.get('quote_age_filter_days')} 天）样本数 = "
                f"{fresh.get('n_fresh')}。\n"
                "  **根因是采集时点，不是数据源缺陷**：期权链只在美东 09:30–16:00 "
                "实时刷新，盘前/盘后/休市采集拿到的是上一交易日的残留挂单。\n"
                f"  {fresh.get('session_note') or ''}\n"
                "  **处置：改到美东盘中重采，而不是把「该源坏了」写成结论。**")
        elif grade == "FULL":
            notes.append("- ✅ **IV / ATM / 25Δ 偏斜全部可用**（两侧都能配到 25-delta 样本）。")
        elif grade == "SKEW_ONLY":
            notes.append("- ⚠️ **可给 25Δ 偏斜，但 ATM 两侧样本不齐** → ATM IV 不可得，偏斜可用。")
        elif grade in ("ATM_ONLY",):
            notes.append("- ⚠️ **只有 ATM IV 可用，无法构造偏斜**。")
        elif grade in ("PARTIAL_2SIDE", "PARTIAL"):
            notes.append(
                "- ⚠️ **降级读数：报价覆盖不足，无法构造 25Δ 偏斜。**\n"
                f"  有效报价落在远离现价的行权价上"
                "（深度实值区），无法找到 |Δ| 接近 0.25 的双边样本。\n"
                "  **这不是闸门设错**，是上游报价的真实分布。")
        else:
            notes.append(f"- ⛔ **IV 与偏斜本次不可用**：{opts.get('iv_note') or ''}"
                         "IV 相关结论**不得基于本证据包得出**。")

        # P/C(Vol) 在新鲜度不足时也不可用（volume 是当日量，但 OI/info 已陈旧）
        staleness_ok = not fresh.get("stale")
        if staleness_ok:
            for r in opts["by_expiry"]:
                if r["pc_volume"] is not None:
                    notes.append(
                        f"- 📊 **P/C(成交量)**：{r['expiry']} "
                        f"= **{r['pc_volume']}**。>1 说明认沽成交占比高。")
                    break

        if opts.get("put_skew_ratio"):
            notes.append(
                f"- 📐 **风险中性偏度替代指标**：OTM put IV ÷ ATM put IV = "
                f"**{opts['put_skew_ratio']}**。>1 表示虚值 put 贵于平价。"
                "**该比值不依赖 call 侧样本**，在无法配对时是偏斜方向性的稳健替代。")

        ts = opts.get("term_structure")
        if ts:
            shape = ("正向（contango，近低远高）" if ts["contango"]
                     else "倒挂（backwardation，近高远低）")
            notes.append(
                f"- 📈 **期限结构**：{ts['near_expiry']}（{ts['near_days']}天）ATM IV "
                f"{ts['near_atm_iv']} vs {ts['far_expiry']}（{ts['far_days']}天）"
                f" {ts['far_atm_iv']} → **端点**斜率 **{ts['slope_pp']:+}pp**，形态为 **{shape}**。")
            # ★★ 2026-10-12：端点斜率**不足以**支撑「近期是否被额外定价」——
            #   只比最近/最远两档会漏掉中段驼峰。判据与理由见 `_thresholds.HUMP_MIN_PP`。
            if ts.get("atm_series"):
                notes.append("  · 逐档 ATM IV：" + " → ".join(
                    f"{s['days']}天 {s['atm_iv']}" for s in ts["atm_series"]))
            if ts.get("hump"):
                h = ts["hump"]
                notes.append(
                    f"  ⚠️ **曲线非单调 —— {h['days']} 天处出现驼峰**：ATM IV {h['atm_iv']}，"
                    f"同时高出相邻两档 ≥ **{h['excess_pp']}pp**"
                    f"（{h['window_from']} 与 {h['window_to']}）"
                    f" ⇒ **事件风险定价集中在 {h['window_from']} ~ {h['window_to']} 窗口内**。")
                notes.append("  ⛔ **不得**仅据端点斜率说「近期未被额外定价」—— 已被驼峰证伪。")
            elif ts["contango"]:
                notes.append("  · 逐档走势与端点斜率一致，未见内部驼峰 ⇒ 可说「近期未被额外定价」。")
            else:
                notes.append("  · 倒挂通常对应**近期事件风险定价**高于长期。")

        if opts.get("div_note") and staleness_ok:
            notes.append(f"- 💰 **股息率参数**：{opts['div_note']}")
        if opts.get("fallback_note"):
            notes.append(f"- 📌 **回退说明**：{opts['fallback_note']}")
        if opts.get("oi_note"):
            notes.append(f"- ⚠️ **持仓量（OI）口径不可信**：{opts['oi_note']}")

        # ★ 2026-10-16：**来源声明**（方案 A 时点分支的配套）。
        #   两个源的 IV/偏斜口径不同、数值不可混用，故必须显式标注。
        _src = (opts.get("source") or "").strip()
        _is_cboe = not _src.startswith("yfinance")
        _src_block = (
            f"- **数据来源：{_source_label(_src)}**\n"
            f"  - {opts.get('source_note') or '（未记录时点说明）'}\n"
            + ("  - ⚠️ **口径提示**：本源的 `iv`/`delta` 由**交易所模型**给出，"
               "与项目自建 BSM 反解的数值**不可直接比较**"
               "（实测同轮 2026-10-30 偏斜：本接口 −0.62pp vs BSM 反解 −4.24pp，"
               "根因是样本数与 delta 定义差异）。**本报告全篇统一使用本接口口径。**\n"
               if _is_cboe else "")
        )
        _iv_block = (
            f"- **IV 计算方法**：**{_iv_method_label(_src)}**\n"
            + ("  - 本源的 IV 与 greeks 由**交易所模型**直接给出，"
               "无需（也不应）再用 BSM 反解；过滤链仍适用："
               "双边报价 > 0 → `ask ≥ bid` → 点差 ≤ 30% → 成交日新鲜度合格。\n"
               if _is_cboe else
               "  （拟合中间价，二分法 70 次迭代，**含股息率**），"
               "**不使用 yfinance 自带的 `impliedVolatility`** —— "
               "后者与报价不自洽（call/put 偏离方向相反）。\n"
               "  过滤链：双边报价 > 0 → `ask ≥ bid` → 点差 ≤ 30% → "
               "**成交日新鲜度合格** → 反解 IV 落在 [2%, 120%]。\n")
        )
        blocks.append(
            "## 13. 期权市场内部结构（指数本身无期权，以 "
            f"{ETF_PROXY} 为代理）\n\n"
            + _src_block
            + f"- 标的价: {opts['spot']}　|　BSM 反解用无风险利率: "
            f"{opts.get('rate_used')}　|　股息率: {opts.get('div_yield_used')}\n"
            f"- 扫描范围: **{opts.get('n_expiries_scanned')} / {opts.get('n_expiries_total')}** "
            "个未来到期日（全量，非抽样）\n"
            f"- **IV 数据等级：{grade}**"
            "（FULL=ATM+偏斜齐 / SKEW_ONLY=仅偏斜 / ATM_ONLY=仅 ATM / "
            "PARTIAL=降级 / NONE=不可用）\n"
            f"- **报价新鲜度**：取成交日≤ {opts.get('quote_age_filter_days')} 天的合约"
            f"；本次最新成交距今 **{fresh.get('min_age_days')} 天**"
            f"、合格样本 **{fresh.get('n_fresh')}** 个\n"
            + _iv_block
            + "- **偏斜主口径为 25-delta 区间中位数**：在 `|Δ|∈[0.20,0.30]` 内取"
            "**全部合格合约 IV 的中位数**作差（put − call）；无样本时依次放宽到"
            "`[0.15,0.35]`、`[0.10,0.45]`，**实际区间见 JSON 的 `skew_25d_band`**"
            "——区间越宽，与标准 25Δ 的可比性越低。备用口径为 ±10% 距现价。\n"
            "  ⚠️ **不是「取最接近 0.25 的单个合约」**（那是另一种口径，见项目铁律 12）："
            "单点口径对采集时点敏感、与区间口径数值不同，**两者不可混用**。\n"
            + "\n".join(notes) + "\n\n"
            "### 13.1 选中的到期日明细\n\n"
            f"```\n{olines}\n```\n\n"
            f"### 13.2 全部到期日报价覆盖扫描（{len(scan)} 行）\n\n"
            "用于证明「哪些期限真的没有可交易报价」，"
            "避免下游把「取不到」误判为「没取」：\n\n"
            f"```\n{slines}\n```"
        )

    # --- 健康度 ---
    ok = sum(1 for v in health.values() if v == "ok")
    bad = [k for k, v in health.items() if v in ("fail", "unavailable", "error")]
    summary = ["## 通道健康度\n", f"- 成功: {ok} / {len(health)}"]
    if bad:
        summary.append(f"- 失败或不可用: {', '.join(bad)}")
    blocks.append("\n".join(summary))

    md = "\n\n---\n\n".join(blocks) + "\n"

    EV_DIR.mkdir(parents=True, exist_ok=True)
    md_path = EV_DIR / f"{index_key}_{as_of}.md"
    json_path = EV_DIR / f"{index_key}_{as_of}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "ticker": index_key,
                "as_of": as_of,
                "index_ticker": INDEX_TICKER,
                "etf_proxy": ETF_PROXY,
                "window_start": start,
                "universe_size": len(universe),
                "price_stats": price_stats,
                "breadth": {k: v for k, v in breadth.items() if k != "candidates"},
                "valuation": {k: v for k, v in val.items() if k != "constituents"} if not val.get("error") else val,
                "top_holdings": holdings,
                "insiders": insiders,
                "option_structure": opts,
                "channel_health": health,
                "evidence_md": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return {
        "md": md_path,
        "json": json_path,
        "health": health,
        "price_stats": price_stats,
        "breadth": breadth,
        "valuation": val,
        "option_structure": opts,
    }


def main() -> int:
    os.chdir(PROJECT_ROOT)
    ap = argparse.ArgumentParser(description="指数证据采集器（不调用 LLM），支持 NDX / SPX，默认 NDX")
    ap.add_argument("--date", default=None,
                    help="基准日期 YYYY-MM-DD。口径＝**美东当日**（数据源的 today），"
                         "**不是**最后一根 bar 的日期；默认取美东当日（**非本机日期**）")
    ap.add_argument("--allow-stale-date", action="store_true",
                    help="显式确认 `--date` 早于美东当日（会触发 §3 快照扣留，默认拒绝）")
    ap.add_argument("--lookback", type=int, default=365, help="行情回溯自然日数")
    ap.add_argument("--index", choices=list(INDEX_CONFIGS.keys()), default=DEFAULT_INDEX,
                    help="目标指数：NDX（纳斯达克100）或 SPX（标普500），默认 NDX")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-social", action="store_true")
    ap.add_argument("--top-insiders", type=int, default=12, help="聚合内部人交易的权重股数量")
    args = ap.parse_args()

    # ★ 2026-10-11（O3）：与 collect.py 同一道口径守卫（实现在 collect.py，此处不复制）
    if args.date is None:
        args.date = today_eastern()
    if not date_caliber_guard(args.date, args.allow_stale_date):
        return 2

    t0 = time.time()
    print(f"[指数证据采集] {args.index}  基准日 {args.date}\n")
    try:
        res = collect_index(args.date, args.lookback, not args.no_news, not args.no_social,
                            args.top_insiders, args.index)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 采集异常 {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    print(f"  [6/6] 汇总完成，用时 {time.time()-t0:.1f}s")
    ok = sum(1 for v in res["health"].values() if v == "ok")
    print(f"\n  ✓ 通道 {ok}/{len(res['health'])} 成功")
    bad = [k for k, v in res["health"].items() if v in ("fail", "unavailable", "error")]
    if bad:
        print(f"  ⚠ 不可用: {', '.join(bad)}")
    print(f"  证据包: {res['md']}")
    print(f"  结构化: {res['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
