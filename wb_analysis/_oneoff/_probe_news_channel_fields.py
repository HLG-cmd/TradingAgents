# lifecycle: oneoff
# created: 2026-09-27
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_news_channel_fields.py
"""探针：精确对比 yf.Search() 与 yf.Ticker().news 两个通道的字段，锁定 §6 无正文的根因。"""
import json
import pathlib

import yfinance as yf

OUT = pathlib.Path(r"wb_analysis/_oneoff/_probe_news_channel_fields.txt")
lines: list[str] = []


def p(s: str = "") -> None:
    lines.append(s)
    print(s)


def dump(item: dict, tag: str) -> None:
    nested = "content" in item
    c = item.get("content", item) if nested else item
    p(f"  [{tag}] nested={nested}  顶层键={sorted(item.keys())[:8]}")
    p(f"      content 内键={sorted(c.keys()) if nested else '—'}")
    p(f"      title   = {(c.get('title') or '')[:80]}")
    for k in ("summary", "description", "body", "providerPublishTime", "pubDate"):
        if k in c:
            v = c[k]
            if isinstance(v, dict):
                v = v.get("displayName") or list(v.keys())[:3]
            p(f"      {k:20}= {str(v)[:150]}")


p("=" * 72)
p("A. yf.Search(query)  —— 当前宏观新闻用的通道")
p("=" * 72)
try:
    s = yf.Search("stock market", news_count=5, enable_fuzzy_query=True)
    p(f"news 条数 = {len(s.news or [])}")
    for i, it in enumerate((s.news or [])[:3], 1):
        dump(it, f"Search#{i}")
        p()
except Exception as e:  # noqa: BLE001
    p(f"!! {type(e).__name__}: {e}")

p("=" * 72)
p("B. yf.Ticker(宽基指数).news  —— 个股新闻用的通道（含 summary）")
p("=" * 72)
for sym in ("^GSPC", "^TNX", "^VIX"):
    try:
        n = yf.Ticker(sym).news
        p(f"\n[{sym}] 条数 = {len(n or [])}")
        for i, it in enumerate((n or [])[:2], 1):
            dump(it, f"{sym}#{i}")
    except Exception as e:  # noqa: BLE001
        p(f"!! {sym}: {type(e).__name__}: {e}")

p("=" * 72)
p("C. 结论")
p("=" * 72)
p("若 A 的 summary 缺失/为空、而 B 的 summary 有内容 ⇒ 根因是「取错通道」，")
p("修法：宏观新闻优先走 Ticker(宽基指数).news，Search 作为兜底。")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ {OUT}")
