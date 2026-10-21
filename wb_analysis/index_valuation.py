# lifecycle: reusable
# created: 2026-10-21
"""指数成分股估值、盈利质量与内部人交易聚合模块。

支持纳指 100（NDX）、标普 500（SPX）等成分股多维度聚合：
- 市值加权市盈率（PE）、前瞻 PE、市净率（PB）、市销率（PS）
- 调和口径净资产收益率（ROE）、净利率（Net Margin）
- 前十大成分股集中度（Top 10 Weight & HHI 赫芬达尔指数）
- 行业分布与内部人增减持（Insider Net Transactions）
"""
from __future__ import annotations

import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from quant.stock_pools import NASDAQ_100, get_latest_sp500
from wb_analysis.collect import _safe_call

__all__ = [
    "INDEX_CONFIGS",
    "DEFAULT_INDEX",
    "INFO_FIELDS",
    "_select_index",
    "_clean_universe",
    "fetch_universe_infos",
    "fetch_top_holdings",
    "fetch_insiders",
    "aggregate_valuation",
]

INDEX_CONFIGS: dict[str, dict[str, Any]] = {
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
        "dedup_classes": {},
    },
}
DEFAULT_INDEX = "NDX"

_CURRENT = dict(INDEX_CONFIGS[DEFAULT_INDEX])
INDEX_TICKER = _CURRENT["index_ticker"]
ETF_PROXY = _CURRENT["etf_proxy"]

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


def _clean_universe(tickers: list[str], dedup: dict | None = None) -> list[str]:
    """剔除重复股份类别，返回参与聚合的成分股清单。"""
    if dedup is None:
        dedup = _CURRENT.get("dedup_classes", {})
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


def fetch_top_holdings(etf_proxy: str | None = None) -> list[dict]:
    """取 ETF 代理前十大真实权重（ETF 跟踪对应指数，权重基本一致）。"""
    import yfinance as yf

    target_etf = etf_proxy or ETF_PROXY
    try:
        th = yf.Ticker(target_etf).funds_data.top_holdings
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

    agg_roe = round(net_income / book * 100, 2) if book > 0 else None
    agg_net_margin = round(net_income / revenue * 100, 2) if revenue > 0 else None

    div_sum = sum(r["marketCap"] * (r["div_yield"] / 100.0) for r in rows if isinstance(r["div_yield"], (int, float)))
    agg_div = round(div_sum / total_mc * 100, 2)

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
