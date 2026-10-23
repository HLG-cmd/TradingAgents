# lifecycle: reusable
# created: 2026-10-10
# usage: ./.venv/Scripts/python.exe scripts/_settlement.py
"""历史决策回溯结算工具（吸收上游 TauricResearch v0.6.0 settlement 思想）

功能：
1. 扫描 `reports/` 目录下所有已交付的投研报告树。
2. 提取标的代码、报告基准日、组合经理/交易员评级。
3. 针对已满 T+5 或 T+20 交易日的标的，拉取实际历史价格与 SPY 基准计算超额收益（Alpha）。
4. 输出全局胜率与 Alpha 战绩看板，防范任何「自我感觉良好但实盘亏损」的盲目自信。
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import logging

from wb_analysis._contract import LABEL_PATTERNS, PROPOSAL_RE  # noqa: E402
from wb_analysis._paths import TREE_RE, is_archived_path, iter_report_trees  # noqa: E402

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

try:
    import pandas as pd
    import yfinance as yf
except ImportError:
    print("需要 pandas 与 yfinance 进行历史行情结算")
    raise SystemExit(1) from None


def parse_report_meta(tree_dir: Path) -> dict | None:
    """从报告树中解析元数据。优先读取 RUN.json，若无则从文件和目录名解析。"""
    if is_archived_path(tree_dir):
        return None
    run_file = tree_dir / "RUN.json"
    if run_file.exists():
        try:
            d = json.loads(run_file.read_text(encoding="utf-8"))
            pm_rating = (d.get("ratings") or {}).get("portfolio_manager") or ""
            trader_act = (d.get("ratings") or {}).get("trader_action") or ""
            return {
                "ticker": d.get("ticker", ""),
                "date": d.get("data_date", ""),
                "pm_rating": pm_rating,
                "trader_action": trader_act,
                "path": tree_dir,
            }
        except Exception:  # noqa: BLE001
            pass

    # Fallback 从目录名解析
    m = TREE_RE.match(tree_dir.name)
    if not m:
        return None
    ticker, ymd = m.group(1), m.group(2)
    date_str = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"

    pm_rating, trader_act = "", ""
    trader_file = tree_dir / "3_trading" / "trader.md"
    if trader_file.exists():
        text = trader_file.read_text(encoding="utf-8")
        act_m = PROPOSAL_RE.search(text) or LABEL_PATTERNS["Action"].search(text)
        if act_m:
            trader_act = act_m.group(1)

    # ★ 2026-10-15 修：渲染后的报告树中组合经理文件为 `5_portfolio/decision.md`
    #   （原实现误写草稿名 `4_risk/portfolio_manager.md`，导致兜底路径恒为空）。
    for rel in ("5_portfolio/decision.md", "4_risk/portfolio_manager.md"):
        pm_file = tree_dir / rel
        if pm_file.exists():
            text = pm_file.read_text(encoding="utf-8")
            rat_m = LABEL_PATTERNS["Rating"].search(text)
            if rat_m:
                pm_rating = rat_m.group(1)
                break

    return {
        "ticker": ticker,
        "date": date_str,
        "pm_rating": pm_rating,
        "trader_action": trader_act,
        "path": tree_dir,
    }


TICKER_MAP = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "HKHSTECH": "3033.HK",
    "515100": "515100.SS",
    "512400": "512400.SS",
}

NON_US_PREFIXES = ("512", "515", "159", "HK", "000660")
_SERIES_CACHE: dict[str, pd.Series | None] = {}


def is_us_market(ticker: str) -> bool:
    t = ticker.upper()
    if t.endswith((".SS", ".SZ", ".HK", ".KS")):
        return False
    return not any(t.startswith(p) for p in NON_US_PREFIXES)


def _load_full_series(sym: str) -> pd.Series | None:
    """带内存缓存与本地价格缓存优先的收盘价序列读取，避免循环内对 SPY 发起几十次重复下载。"""
    if sym in _SERIES_CACHE:
        return _SERIES_CACHE[sym]

    # 1. 优先读本地长周期价格缓存（`~/.tradingagents/prices/`）
    try:
        from quant.price_history import load_prices_long
        df_local = load_prices_long(sym)
        if df_local is not None and not df_local.empty and "Close" in df_local.columns:
            s = df_local.set_index("Date")["Close"].dropna().sort_index()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            _SERIES_CACHE[sym] = s
            return s
    except Exception:  # noqa: BLE001
        pass

    # 2. 回退到单次 yfinance 下载并缓存
    try:
        df = yf.download(sym, period="1y", progress=False, ignore_tz=True)
        if df is not None and not df.empty and "Close" in df:
            closes = df["Close"]
            if hasattr(closes, "columns"):
                closes = closes.iloc[:, 0]
            s = closes.dropna().sort_index()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            _SERIES_CACHE[sym] = s
            return s
    except Exception:  # noqa: BLE001
        pass

    _SERIES_CACHE[sym] = None
    return None


def fetch_close_series(ticker: str, start_date: str, days: int = 40) -> pd.Series | None:
    """拉取自 start_date 起往后若干天的收盘价序列。"""
    start_dt = pd.Timestamp(start_date)
    end_dt = start_dt + timedelta(days=days)
    sym = TICKER_MAP.get(ticker.upper(), ticker)
    s = _load_full_series(sym)
    if s is None or s.empty:
        return None
    sub = s[(s.index >= start_dt) & (s.index <= end_dt)]
    return sub if not sub.empty else None


def evaluate_decision(ticker: str, trade_date: str, holding_bars: int = 5) -> dict | None:
    """计算标的在 holding_bars 交易日后的收益率；美股标的按同日对齐计算相对 SPY 的 Alpha。"""
    stock_closes = fetch_close_series(ticker, trade_date, days=round(holding_bars * 2.5) + 14)
    if stock_closes is None or len(stock_closes) <= holding_bars:
        return None  # 交易日尚未走满

    entry_ts = stock_closes.index[0]
    exit_ts = stock_closes.index[holding_bars]
    p0_stock = float(stock_closes.iloc[0])
    p1_stock = float(stock_closes.iloc[holding_bars])
    raw_ret = (p1_stock - p0_stock) / p0_stock

    bench_ret = None
    alpha = None
    if is_us_market(ticker):
        bench_all = _load_full_series("SPY")
        if bench_all is not None and not bench_all.empty:
            b_sub = bench_all[(bench_all.index >= entry_ts) & (bench_all.index <= exit_ts)]
            if len(b_sub) >= 2:
                p0_bench = float(b_sub.iloc[0])
                p1_bench = float(b_sub.iloc[-1])
                bench_ret = (p1_bench - p0_bench) / p0_bench
                alpha = raw_ret - bench_ret

    return {
        "entry_date": entry_ts.strftime("%Y-%m-%d"),
        "exit_date": exit_ts.strftime("%Y-%m-%d"),
        "entry_price": round(p0_stock, 2),
        "exit_price": round(p1_stock, 2),
        "raw_return": round(raw_ret * 100, 2),
        "bench_return": round(bench_ret * 100, 2) if bench_ret is not None else None,
        "alpha": round(alpha * 100, 2) if alpha is not None else None,
    }


def main() -> int:
    reports_root = PROJECT_ROOT / "reports"
    if not reports_root.exists():
        print(f"报告目录不存在: {reports_root}")
        return 1

    candidates = [tr for _tk, tr in iter_report_trees(reports_root)]
    if not candidates:
        print("未找到任何已归档的报告树。")
        return 0

    print("=" * 106)
    print(f"TradingAgents 历史投研决策回溯结算看板 (共发现 {len(candidates)} 份有效报告树)")
    print("=" * 106)

    hdr = f"{'标的':9s} {'基准日':12s} {'决策/建议':14s} {'结算日(T+5)':14s} {'入场价':9s} {'结算价':9s} {'标的涨跌':9s} {'SPY基准':9s} {'超额Alpha':9s} 评价"
    print(hdr)
    print("-" * 112)

    settled_count = 0
    pending_count = 0

    for tree in sorted(candidates, key=lambda x: x.name, reverse=True):
        meta = parse_report_meta(tree)
        if not meta or not meta["ticker"] or not meta["date"]:
            continue

        decision = meta["trader_action"] or meta["pm_rating"] or "—"
        res = evaluate_decision(meta["ticker"], meta["date"], holding_bars=5)

        if res is None:
            pending_count += 1
            print(f"{meta['ticker']:9s} {meta['date']:12s} {decision:14s} {'-- 交易日不足 --':14s} {'—':>9s} {'—':>9s} {'—':>9s} {'—':>9s} {'—':>9s} 观察中(Pending)")
        else:
            settled_count += 1
            raw_str = f"{res['raw_return']:+.2f}%"
            bench_str = f"{res['bench_return']:+.2f}%" if res["bench_return"] is not None else "—(非美股)"
            alpha_str = f"{res['alpha']:+.2f}%" if res["alpha"] is not None else "—(非美股)"
            metric = res["alpha"] if res["alpha"] is not None else res["raw_return"]

            d_up = decision.upper()
            if "BUY" in d_up or "OVERWEIGHT" in d_up:
                verdict = "✓ 胜出" if metric > 0 else "✗ 跑输"
            elif "HOLD" in d_up:
                verdict = "✓ 稳健观望" if abs(metric) < 3.0 else ("△ 踏空上行" if metric >= 3.0 else "✓ 成功避险")
            elif "SELL" in d_up or "UNDERWEIGHT" in d_up:
                verdict = "✓ 成功避险" if metric < 0 else "✗ 误判卖飞"
            else:
                verdict = "—"

            print(f"{meta['ticker']:9s} {meta['date']:12s} {decision:14s} {res['exit_date']:14s} "
                  f"{res['entry_price']:9.2f} {res['exit_price']:9.2f} {raw_str:>9s} {bench_str:>9s} {alpha_str:>9s} {verdict}")

    print("-" * 112)
    print(f"汇总：已结算 {settled_count} 轮 | 观察中 {pending_count} 轮")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
