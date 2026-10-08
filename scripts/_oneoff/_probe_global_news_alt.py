# lifecycle: oneoff
# 探测可行的「带 summary 的宏观新闻」主通道替代方案
import sys

sys.path.insert(0, r"D:\Antigravity\TradingAgents")
import yfinance as yf

def probe(label, fn):
    print("=" * 70)
    print(label)
    print("=" * 70)
    try:
        news = fn() or []
    except Exception as e:  # noqa: BLE001
        print(f"  失败: {type(e).__name__}: {e}")
        return
    print(f"  条目数: {len(news)}")
    for i, a in enumerate(news[:5]):
        if not isinstance(a, dict):
            print(f"  {i+1}. 非 dict: {type(a)}")
            continue
        nested = isinstance(a.get("content"), dict)
        s_nest = a["content"].get("summary", "") if nested else ""
        s_top = a.get("summary", "")
        title = a.get("title") or (a.get("content") or {}).get("title")
        print(f"  {i+1}. nested={nested} summ_top={len(s_top or '')} summ_nest={len(s_nest or '')} | {str(title)[:55]}")

probe("SPY Ticker().news", lambda: yf.Ticker("SPY").news)
probe("QQQ Ticker().news", lambda: yf.Ticker("QQQ").news)
probe("AAPL Ticker().news（对照：个股通道）", lambda: yf.Ticker("AAPL").news)
probe("Search('^GSPC')", lambda: yf.Search("^GSPC", news_count=8, enable_fuzzy_query=True).news)
