# lifecycle: oneoff
# archived: 2026-10-10
# why: 与 `scripts/_probe_baseline.py` **功能完全重复** —— 后者接 argv 标的（`_probe_baseline.py NFLX`），
#      本文件把 NFLX 写死。同一职责两处实现 ⇒ 只留可复用的那份。
# serves: NFLX 基线探针
# 用途：确认 NFLX 当前美东时间 + 最近若干根日线，决定本轮分析基线（最新完整 bar）
from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf

et = ZoneInfo("America/New_York")
now_et = datetime.now(et)
print("now_et:", now_et.isoformat())
print("weekday:", now_et.strftime("%A"))
print("market_open:", now_et.hour * 60 + now_et.minute)

t = yf.Ticker("NFLX")
df = t.history(period="10d", interval="1d", auto_adjust=False)
print("bars:")
print(df[["Open", "High", "Low", "Close", "Volume"]].to_string())
print("last_bar_date:", df.index[-1])
print("last_bar_close:", df["Close"].iloc[-1])
