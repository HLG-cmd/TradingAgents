# lifecycle: oneoff
# created: 2026-09-27
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_macro_news_sources.py
"""探针：§6 宏观新闻正文全缺 —— 测试能不能换通道抓到正文。

背景：证据包 §6 的 6 条新闻**全部只有标题 + Link**，无 description。
本脚本逐源实测，判断这是「源本身不返回」还是「我们的取法丢了字段」。
"""
import json
import pathlib
import sys
import traceback

OUT = pathlib.Path(r"wb_analysis/_oneoff/_probe_macro_news_sources.txt")
lines: list[str] = []


def p(s: str = "") -> None:
    lines.append(s)
    print(s)


# ---------- 1. 看当前实现 ----------
p("=" * 70)
p("1. 当前实现（yfinance_news.get_global_news_yfinance）的源码")
p("=" * 70)
try:
    from tradingagents.dataflows import yfinance_news as yn
    import inspect
    src = inspect.getsource(yn.get_global_news_yfinance)
    p(src)
except Exception as e:  # noqa: BLE001
    p(f"!! 取源码失败: {type(e).__name__}: {e}")

# ---------- 2. 直接调 yfinance 的 Search/News ----------
p("=" * 70)
p("2. 直接调 yfinance 看原始返回（是否含 summary/description 字段）")
p("=" * 70)
try:
    import yfinance as yf
    p(f"yfinance {yf.__version__}")

    # 2a. 用 Ticker.news 取宏观相关
    for probe in ("^GSPC", "^TNX"):
        try:
            n = yf.Ticker(probe).news
            p(f"\n[Ticker('{probe}').news] 返回 {len(n) if n else 0} 条")
            for item in (n or [])[:3]:
                c = item.get("content", item)
                keys = sorted(c.keys()) if isinstance(c, dict) else type(c)
                p(f"  字段: {keys}")
                p(f"  title : {(c.get('title') or '')[:90]}")
                for k in ("summary", "description", "body", "providerPublishTime"):
                    if k in c:
                        v = str(c[k])[:160]
                        p(f"  {k}: {v}")
        except Exception as e:  # noqa: BLE001
            p(f"  !! Ticker('{probe}').news 失败: {type(e).__name__}: {str(e)[:120]}")

    # 2b. Search API
    try:
        from yfinance import Search
        s = Search("stock market", news_count=5)
        p(f"\n[Search('stock market')] news = {len(s.news or [])} 条")
        for item in (s.news or [])[:3]:
            c = item.get("content", item)
            p(f"  title: {(c.get('title') or '')[:90]}")
            p(f"  has summary: {'summary' in c} | has description: {'description' in c}")
            if c.get("summary"):
                p(f"  summary: {str(c['summary'])[:160]}")
    except Exception as e:  # noqa: BLE001
        p(f"  !! Search 失败: {type(e).__name__}: {str(e)[:160]}")
        p(traceback.format_exc()[:400])

except Exception as e:  # noqa: BLE001
    p(f"!! yfinance 导入/调用失败: {type(e).__name__}: {str(e)[:200]}")

# ---------- 3. 结果落盘 ----------
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ {OUT}")
