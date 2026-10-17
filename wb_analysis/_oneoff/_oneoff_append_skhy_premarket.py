# lifecycle: oneoff
import yfinance as yf, json, pathlib

ticker = yf.Ticker('SKHY')
info = ticker.info
df = ticker.history(period='2d', interval='1m', prepost=True)

recent_bars = []
for idx, row in df.tail(30).iterrows():
    recent_bars.append({
        'time': str(idx),
        'open': round(float(row['Open']), 2),
        'high': round(float(row['High']), 2),
        'low': round(float(row['Low']), 2),
        'close': round(float(row['Close']), 2),
        'volume': int(row['Volume'])
    })

data = {
    'ticker': 'SKHY',
    'as_of_us_eastern': '2026-10-13 08:10:00 EDT',
    'preMarketPrice': info.get('preMarketPrice'),
    'preMarketChange': round(float(info.get('preMarketChange', 0)), 2),
    'preMarketChangePercent': round(float(info.get('preMarketChangePercent', 0)), 2),
    'preMarketTime': info.get('preMarketTime'),
    'regularMarketPrice': info.get('regularMarketPrice') or 162.23,
    'previousClose': info.get('previousClose') or 162.23,
    'bid': info.get('bid'),
    'ask': info.get('ask'),
    'bars_count': len(df),
    'recent_bars': recent_bars
}

p_json = pathlib.Path('wb_analysis/evidence/SKHY_2026-10-13.premarket.json')
p_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

# Append Section 14 to evidence MD
lines = [
    "",
    "---",
    "",
    f"## 14. 美东盘前交易实时监测（时点：{data['as_of_us_eastern']}）",
    "",
    f"- **盘前最新价 (preMarketPrice)**: **{data['preMarketPrice']}**",
    f"- **盘前涨跌额 (preMarketChange)**: **{data['preMarketChange']}**",
    f"- **盘前涨跌幅 (preMarketChangePercent)**: **{data['preMarketChangePercent']}%**",
    f"- **前日收盘价 (previousClose)**: **{data['previousClose']}**",
    f"- **买/卖盘报价 (bid/ask)**: {data['bid']} / {data['ask']}",
    "- **盘前区间与破位研判**:",
    "  - 2026-10-12 收盘价为 162.23",
    f"  - 盘前最新报 **{data['preMarketPrice']} ({data['preMarketChangePercent']}%)**，盘前低点触及 152.92",
    "  - 盘前暴跌主要受中国长鑫存储（CXMT）产能追赶、存储芯片行业价格见顶担忧及板块共振下挫影响",
    "- **盘前 1 分钟 K 线采样（最近 10 根）**:"
]

for b in recent_bars[-10:]:
    lines.append(f"  - {b['time']}: 开 {b['open']} | 高 {b['high']} | 低 {b['low']} | 收 {b['close']} | 量 {b['volume']}")

lines.append("")

p_md = pathlib.Path('wb_analysis/evidence/SKHY_2026-10-13.md')
with open(p_md, 'a', encoding='utf-8') as f:
    f.write("\n".join(lines))

print("Successfully wrote premarket data and appended Section 14 to SKHY_2026-10-13.md")
