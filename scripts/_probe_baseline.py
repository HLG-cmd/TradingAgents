# lifecycle: maintenance
# 用途：确认任意标的当前美东时间 + 最近若干根日线，决定本轮分析基线（最新完整 bar）
# 用法：python scripts/_probe_baseline.py WDC
import sys
from datetime import datetime

from zoneinfo import ZoneInfo

import yfinance as yf

TICKER = sys.argv[1] if len(sys.argv) > 1 else "WDC"

et = ZoneInfo("America/New_York")
now_et = datetime.now(et)
print("ticker:", TICKER)
print("now_et:", now_et.isoformat())
print("weekday:", now_et.strftime("%A"))
print("minutes_since_midnight_et:", now_et.hour * 60 + now_et.minute)

# 美东常规交易时段 09:30 - 16:00
mins = now_et.hour * 60 + now_et.minute
is_weekday = now_et.weekday() < 5
in_session = is_weekday and (570 <= mins < 960)
print("is_weekday:", is_weekday, "| in_regular_session:", in_session)

t = yf.Ticker(TICKER)
df = t.history(period="12d", interval="1d", auto_adjust=False)
print("bars:")
print(df[["Open", "High", "Low", "Close", "Volume"]].to_string())
print("last_bar_date:", df.index[-1])
print("last_bar_close:", df["Close"].iloc[-1])
print("last_bar_volume:", df["Volume"].iloc[-1])

# 成交量粗糙ieh consent heuristic：最后一根 bar 若处于盘中且成交量显著低于近 5 根中位 ⇒ 未完成
vol = df["Volume"].tolist()
if len(vol) >= 6:
    med = sorted(vol[-6:-1])[len(vol[-6:-1]) // 2]
    print("median_vol_prior5:", med)
    print("last_vs_median_ratio:", round(vol[-1] / med, 4) if med else None)
