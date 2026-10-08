# lifecycle: oneoff
# 诊断：宏观新闻主通道（Ticker().news）是否真的提供 summary
# 以及为何 GOOG/WDC 的 §6 只剩标题
import json
import sys

sys.path.insert(0, r"D:\Antigravity\TradingAgents")

try:
    import yfinance as yf
except Exception as e:  # noqa: BLE001
    print("yfinance 不可用:", e)
    raise SystemExit

for sym in ("^GSPC", "^TNX", "^VIX"):
    print("=" * 70)
    print(f"Ticker({sym}).news")
    print("=" * 70)
    try:
        news = yf.Ticker(sym).news or []
    except Exception as e:  # noqa: BLE001
        print("  取失败:", e)
        continue
    print(f"  条目数: {len(news)}")
    for i, a in enumerate(news[:3]):
        print(f"  --- 第 {i+1} 条 ---")
        print(f"    顶层键: {sorted(a.keys())}")
        if "content" in a:
            c = a["content"]
            print(f"    content 键: {sorted(c.keys()) if isinstance(c, dict) else type(c)}")
            if isinstance(c, dict):
                summ = c.get("summary", "")
                print(f"    content.summary 长度: {len(summ)}")
                print(f"    content.title: {str(c.get('title'))[:70]}")
        else:
            summ = a.get("summary", "")
            print(f"    顶层 summary 长度: {len(summ)}  (顶层无 content 嵌套)")
            print(f"    顶层 title: {str(a.get('title'))[:70]}")
