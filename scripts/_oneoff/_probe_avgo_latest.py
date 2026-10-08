# -*- coding: utf-8 -*-
# lifecycle: oneoff
"""探测 AVGO 最新可用日线 bar 与期权链新鲜度，用于确定本轮基准日。"""
import datetime as dt
from zoneinfo import ZoneInfo

import yfinance as yf

ET = ZoneInfo("America/New_York")
now_et = dt.datetime.now(ET)
print(f"本机时间 : {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"美东时间 : {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}  ({'盘中' if 9 <= now_et.hour < 16 and now_et.weekday() < 5 else '非盘中'})")
print("=" * 70)

t = yf.Ticker("AVGO")
h = t.history(period="15d", auto_adjust=False)
print("最近 10 根日线（未复权）：")
print(h[["Open", "High", "Low", "Close", "Volume"]].tail(10).to_string())
print()
last = h.index[-1]
print(f"最后一根 bar 日期: {last.date()}  Volume={h['Volume'].iloc[-1]:,}")
# 判断末根是否未收盘（量能显著低于 20 日均量）
vol20 = h["Volume"].tail(20).mean()
print(f"末根量 / 20日均量 = {h['Volume'].iloc[-1] / vol20:.2%}")
print()

info = t.info
for k in ("regularMarketPrice", "previousClose", "regularMarketTime", "marketState"):
    v = info.get(k)
    if isinstance(v, (int, float)) and k == "regularMarketTime":
        v = dt.datetime.fromtimestamp(v, ET).strftime("%Y-%m-%d %H:%M:%S ET")
    print(f"  {k:22s} = {v}")
