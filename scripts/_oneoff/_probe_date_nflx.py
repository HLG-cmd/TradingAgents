# lifecycle: oneoff
"""探针：确定本轮基准日，并核对 NFLX 末根 bar / 期权链新鲜度。只读。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd

# 市场时钟（项目自带）
sys.path.insert(0, str(ROOT / "wb_analysis"))
try:
    from wb_analysis._thresholds import _market_today_eastern  # type: ignore
    mt = _market_today_eastern()
    print("market_today_eastern =", mt)
except Exception as e:  # noqa
    print("market_today_eastern import failed:", repr(e))

now_local = pd.Timestamp.now()
now_et = pd.Timestamp.now(tz="US/Eastern")
print("local now            =", now_local)
print("US/Eastern now       =", now_et)
print("ET is a trading weekday:", now_et.dayofweek, "(0=Mon)")
print("ET hour (24h)        =", now_et.hour, "minute", now_et.minute)

import yfinance as yf

t = yf.Ticker("NFLX")
h = t.history(period="10d", interval="1d", auto_adjust=False)
print("\n--- NFLX last 10 daily bars (unadjusted) ---")
print(h[["Open", "High", "Low", "Close", "Volume"]].tail(10).to_string())

info = t.info
print("\nregularMarketPrice   =", info.get("regularMarketPrice"))
print("regularMarketTime    =", info.get("regularMarketTime"))
print("previousClose        =", info.get("previousClose"))
print("marketState          =", info.get("marketState"))
print("sharesOutstanding    =", info.get("sharesOutstanding"))
print("impliedSharesOutstanding =", info.get("impliedSharesOutstanding"))
