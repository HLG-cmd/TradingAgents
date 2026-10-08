# lifecycle: oneoff
# 续诊断：Search() 兜底通道是否可用、是否含 summary
import sys

sys.path.insert(0, r"D:\Antigravity\TradingAgents")
import yfinance as yf

print("=" * 70)
print("Search() 兜底通道探测")
print("=" * 70)
for q in ("stock market today", "S&P 500 Nasdaq"):
    try:
        s = yf.Search(query=q, news_count=8, enable_fuzzy_query=True)
        news = s.news or []
    except Exception as e:  # noqa: BLE001
        print(f"[{q}] 失败: {e}")
        continue
    print(f"\n[{q}] 条目数 {len(news)}")
    for i, a in enumerate(news[:4]):
        top = sorted(a.keys())
        has_content = "content" in a
        summ_top = len(a.get("summary", "") or "")
        summ_nested = 0
        if has_content and isinstance(a["content"], dict):
            summ_nested = len(a["content"].get("summary", "") or "")
        print(f"  {i+1}. content={has_content}  顶层summary={summ_top}  嵌套summary={summ_nested}")
        print(f"     键={top}")
        print(f"     标题={str(a.get('title') or (a.get('content') or {}).get('title'))[:60]}")
