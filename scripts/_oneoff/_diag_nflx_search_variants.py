# lifecycle: oneoff
# 用途：查清现网那段「Alphabet 兜底」为何返回空。
#   现网写法：yf.Search(q, news_count=article_limit*2)  +  except Exception: pass
#   假设：① 裸 except 吞掉了真实异常；② 未开 enable_fuzzy_query 导致结果为空/很少
# 方法：逐变体实测，异常**打印**而非吞掉。
import sys

sys.path.insert(0, ".")

import yfinance as yf  # noqa: E402

CANON = "NFLX"
LIMIT = 20


def show(label, fn):
    try:
        s = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"  {label:<52} EXC {type(exc).__name__}: {str(exc)[:120]}")
        return
    news = getattr(s, "news", None) or []
    print(f"  {label:<52} n={len(news)}")
    if news:
        print(f"      first: {str(news[0].get('title'))[:80]}")


def main():
    print("Search 签名:")
    import inspect

    try:
        print("   ", inspect.signature(yf.Search.__init__))
    except Exception as exc:  # noqa: BLE001
        print("    sig probe failed:", exc)

    print("=" * 96)
    print("变体实测（现网用的正是第一种）:")
    show("Search('NFLX', news_count=40)", lambda: yf.Search(CANON, news_count=LIMIT * 2))
    show("Search(query='NFLX', news_count=40)", lambda: yf.Search(query=CANON, news_count=LIMIT * 2))
    show("Search('NFLX', news_count=40, fuzzy=True)",
         lambda: yf.Search(CANON, news_count=LIMIT * 2, enable_fuzzy_query=True))
    show("Search('Alphabet NFLX', news_count=40)",
         lambda: yf.Search(f"Alphabet {CANON}", news_count=LIMIT * 2))
    show("Search('Alphabet NFLX', news_count=40, fuzzy=True)",
         lambda: yf.Search(f"Alphabet {CANON}", news_count=LIMIT * 2, enable_fuzzy_query=True))
    show("Search(query='NFLX', news_count=50, fuzzy=True)",
         lambda: yf.Search(query=CANON, news_count=50, enable_fuzzy_query=True))

    print("=" * 96)
    print("复现现网过滤逻辑（弱判据 + Alphabet/Google 后门）会放行什么:")
    try:
        s = yf.Search(f"Alphabet {CANON}", news_count=LIMIT * 2, enable_fuzzy_query=True)
        news = getattr(s, "news", None) or []
    except Exception as exc:  # noqa: BLE001
        print("  EXC", exc)
        news = []
    hit = 0
    for item in news:
        title = item.get("title", "") or ""
        related = item.get("relatedTickers") or []
        if CANON in related or CANON in title or "Alphabet" in title or "Google" in title:
            hit += 1
            why = "Google/Alphabet后门" if ("Alphabet" in title or "Google" in title) and CANON not in title and CANON not in related else "正常"
            print(f"   [{why}] {title[:80]}")
    print(f"  放行 {hit}/{len(news)}")


if __name__ == "__main__":
    main()
