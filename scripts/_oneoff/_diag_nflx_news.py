# lifecycle: oneoff
# 用途：诊断 2026-10-08 get_news 通道归零的根因（A 上游真缺 / B 阈值误伤 / C 采集器 bug）
# 背景：NFLX 采集 34/35，唯一未绿通道 = get_news(unavailable)
# 做法：对同一 symbol 并行实测 yfinance 的三条新闻通道，看哪条能拿到条目
import json
import sys

sys.path.insert(0, ".")

import yfinance as yf  # noqa: E402

SYMS = ["NFLX", "^GSPC", "AAPL"]
LIMIT = 20


def probe(label, fn):
    try:
        val = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"  {label:<34} EXC  {type(exc).__name__}: {exc}")
        return None
    n = len(val) if isinstance(val, list) else -1
    print(f"  {label:<34} n={n}")
    if isinstance(val, list) and val:
        a = val[0]
        keys = sorted(a.keys())
        nested = "content" in a
        print(f"      nested={nested} top_keys={keys}")
        holder = a.get("content") if nested else a
        if isinstance(holder, dict):
            print(f"      title  = {str(holder.get('title'))[:90]}")
            has_sum = bool(holder.get("summary"))
            print(f"      summary_present={has_sum}  len={len(holder.get('summary') or '')}")
    return val if isinstance(val, list) else None


def main():
    print("yfinance version:", yf.__version__)
    for sym in SYMS:
        print("=" * 96)
        print(f"SYMBOL {sym}")
        t = yf.Ticker(sym)
        probe("Ticker().news", lambda s=sym: yf.Ticker(s).news)
        probe("Ticker().get_news()", lambda t=t: t.get_news())
        probe(f"Ticker().get_news(count={LIMIT})", lambda t=t: t.get_news(count=LIMIT))
        try:
            probe(f"Search('{sym}').news", lambda s=sym: yf.Search(s).news)
        except Exception as exc:  # noqa: BLE001
            print(f"  Search unavailable: {type(exc).__name__}: {exc}")

    # 配置里的 article_limit
    print("=" * 96)
    try:
        from tradingagents.dataflows.config import get_config

        cfg = get_config()
        print("news_article_limit =", cfg.get("news_article_limit"))
        print("tool_vendors.get_news =", (cfg.get("tool_vendors") or {}).get("get_news"))
    except Exception as exc:  # noqa: BLE001
        print("config probe failed:", exc)


if __name__ == "__main__":
    main()
