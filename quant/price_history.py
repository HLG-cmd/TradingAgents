# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/price_history.py
"""长周期价格历史（10~20 年）—— 解开长周期回测的硬瓶颈。

━━━ 为什么需要它 ━━━
上游的 ``load_ohlcv`` 用**固定 5 年**窗口做缓存（``today - 5y``）。
做长周期因子回测时会撞墙：实测 ``--forward 252 --rebalance 12``（不重叠的
12 个月口径）在 5 年历史下**只能得到 3 个观测点**，统计上等于零。

而 EDGAR 的基本面数据已回溯到 2009 年 —— **瓶颈在价格侧**：
基本面能看 15 年，价格只有 5 年，两者对不上。

本模块补上这一侧：按票缓存**全量**历史（默认自 2000 年起），
让「不重叠的长周期 IC 检验」第一次成为可能。

━━━ 为什么不改 load_ohlcv ━━━
它是上游共享组件（``tradingagents/dataflows/stockstats_utils.py``），
5 年窗口与其缓存文件名绑定，改动会牵动既有缓存与全部调用方。
故此处**独立实现**，只服务回测。

━━━ 与 load_ohlcv 的口径一致性 ━━━
- 同样用 ``auto_adjust=True``（复权价），否则与 EDGAR 原值股本/EPS 口径不符
- 同样按票落盘缓存，避免重复下载
- 同样遵守限流（实测并发上限约 5）

用法：
    from price_history import load_prices_long, preload_prices
    preload_prices(["NVDA", "AAPL"])            # 预热
    df = load_prices_long("NVDA")               # 全量历史
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(os.path.expanduser("~")) / ".tradingagents" / "prices"

# 实测：并发 >5 会触发 Yahoo 限流（与 screener_engine 的结论一致）
MAX_WORKERS = 5
DEFAULT_START = "2000-01-01"


def _cache_file(ticker: str) -> Path:
    safe = "".join(c for c in ticker.upper() if c.isalnum() or c in "-.")
    return CACHE_DIR / f"{safe}.csv"


def load_prices_long(ticker: str, start: str = DEFAULT_START,
                     force: bool = False, max_age_days: int = 1) -> pd.DataFrame:
    """取单只标的的全量历史日线（复权）。

    按票缓存到 ``~/.tradingagents/prices/<TICKER>.csv``。
    缓存 ``max_age_days`` 天内视为新鲜，直接复用（历史行不可变，只需补最新）。
    """
    tk = ticker.strip().upper().replace(".", "-")
    p = _cache_file(tk)

    if not force and p.exists():
        age = (time.time() - p.stat().st_mtime) / 86400
        if age <= max_age_days:
            try:
                df = pd.read_csv(p, parse_dates=["Date"])
                if not df.empty and "Close" in df.columns:
                    return df
            except Exception:
                pass

    raw = yf.Ticker(tk).history(start=start, auto_adjust=True)
    if raw is None or raw.empty:
        # 缓存一个空文件会让下游一直看到"无数据"，所以不写盘，直接返回空
        return pd.DataFrame()
    raw = raw.reset_index()
    raw["Date"] = pd.to_datetime(raw["Date"]).dt.tz_localize(None)
    keep = [c for c in ("Date", "Open", "High", "Low", "Close", "Volume")
            if c in raw.columns]
    out = raw[keep].sort_values("Date").reset_index(drop=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        out.to_csv(p, index=False)
    except Exception:
        pass
    return out


def load_many(tickers: list[str], start: str = DEFAULT_START,
              force: bool = False) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """并发取多只标的的收盘价宽表。返回 (宽表, 失败明细)。"""
    closes, failed = {}, []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(load_prices_long, t, start, force): t for t in tickers}
        for fut in as_completed(futs):
            tk = futs[fut]
            try:
                df = fut.result()
            except Exception as exc:  # noqa: BLE001
                failed.append((tk, f"{type(exc).__name__}: {str(exc)[:60]}"))
                continue
            if df.empty:
                failed.append((tk, "无数据"))
                continue
            closes[tk] = df.set_index("Date")["Close"]
    if not closes:
        return pd.DataFrame(), failed
    return pd.DataFrame(closes).sort_index(), failed


def preload_prices(tickers: list[str], start: str = DEFAULT_START,
                   verbose: bool = True) -> dict[str, str]:
    """预热全量价格缓存。返回 {ticker: 状态}。"""
    status: dict[str, str] = {}
    t0 = time.time()
    for i, tk in enumerate(tickers, 1):
        try:
            df = load_prices_long(tk, start, force=True)
            if df.empty:
                status[tk] = "无数据"
            else:
                status[tk] = f"ok({len(df)}行)"
        except Exception as exc:  # noqa: BLE001
            status[tk] = f"{type(exc).__name__}: {str(exc)[:50]}"
        if verbose and (i % 10 == 0 or i == len(tickers)):
            ok = sum(1 for v in status.values() if v.startswith("ok"))
            print(f"  [{i}/{len(tickers)}] 成功 {ok}  已用 {time.time()-t0:.0f}s", flush=True)
    return status
