# lifecycle: oneoff
import pathlib, json

p_json = pathlib.Path('wb_analysis/evidence/WDC_2026-10-13.premarket.json')
data = json.loads(p_json.read_text(encoding='utf-8'))

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
    "  - 2026-10-12 收盘价为 386.94",
    "  - 盘前低点下探至 **371.58**，最新报 **372.07 (-3.84%)**",
    "  - **严重跌破布林下轨**（boll_lb = 380.06，盘前距下轨进一步跌深 -2.10%）",
    "  - 距 50SMA（454.37）偏离扩大至 **-18.11%**",
    "  - 距 200SMA（406.75）偏离扩大至 **-8.53%**",
    "  - 距 10EMA（414.79）偏离扩大至 **-10.30%**",
    "- **盘前 1 分钟 K 线采样（最近 10 根）**:"
]

for b in data['recent_bars'][-10:]:
    lines.append(f"  - {b['time']}: 开 {b['open']} | 高 {b['high']} | 低 {b['low']} | 收 {b['close']} | 量 {b['volume']}")

lines.append("")

p_md = pathlib.Path('wb_analysis/evidence/WDC_2026-10-13.md')
with open(p_md, 'a', encoding='utf-8') as f:
    f.write("\n".join(lines))

print("Successfully appended Section 14 to WDC_2026-10-13.md")
