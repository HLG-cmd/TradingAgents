# lifecycle: oneoff
# 用途：检验「个股新闻走 Search() 兜底」是否可行
#   旧注释否决兜底的两条理由，这里逐条实测：
#     ① 语义不专属（GOOG 轮实测返回泛科技/能源噪声）
#     ② 窗口过滤后仍为空（Search 只回最新快讯，回溯窗口下会被 in_window 挡掉）
# 判据：看 relatedTickers 能否做专属校验 + 看有多少条能落进采集窗口 + 正文回填成功率
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

import yfinance as yf  # noqa: E402
from tradingagents.dataflows.yfinance_news import (  # noqa: E402
    _extract_article_data,
    backfill_missing_summaries,
)
from tradingagents.dataflows.date_window import in_window  # noqa: E402

SYM = "NFLX"
START = "2026-10-01"
END = "2026-10-08"


def main():
    start_dt = datetime.strptime(START, "%Y-%m-%d")
    end_dt = datetime.strptime(END, "%Y-%m-%d")

    for count in (20, 50):
        print("=" * 100)
        print(f"Search(query={SYM!r}, news_count={count})")
        try:
            s = yf.Search(query=SYM, news_count=count, enable_fuzzy_query=True)
            news = s.news or []
        except Exception as exc:  # noqa: BLE001
            print("  EXC", type(exc).__name__, exc)
            continue
        print(f"  n={len(news)}")

        rel_hits = 0
        in_win = 0
        for i, a in enumerate(news, 1):
            d = _extract_article_data(a)
            rt = a.get("relatedTickers") or []
            hit = SYM in rt
            rel_hits += 1 if hit else 0
            pd = d["pub_date"]
            ok = in_window(pd, start_dt, end_dt)
            in_win += 1 if ok else 0
            pds = pd.strftime("%Y-%m-%d %H:%M") if pd else "None"
            print(f"  {i:>2}. [{('IN ' if ok else 'OUT')}] {pds}  related={rt}")
            print(f"      {str(d['title'])[:100]}")
            print(f"      pub={d['publisher']}  link={str(d['link'])[:80]}")

        print(f"  -- 语义专属(relatedTickers 含 {SYM}) = {rel_hits}/{len(news)}")
        print(f"  -- 落在窗口 {START}~{END} 内        = {in_win}/{len(news)}")

    # 正文回填成功率（这是把「只有标题」升级成「可作定性依据」的关键）
    print("=" * 100)
    s = yf.Search(query=SYM, news_count=20, enable_fuzzy_query=True)
    news = list(s.news or [])
    filled = backfill_missing_summaries(news, limit=8)
    got = sum(1 for a in news if (_extract_article_data(a)["summary"] or "").strip())
    print(f"正文回填：filled={filled}  有正文条目={got}/{len(news)}")
    for a in news[:8]:
        d = _extract_article_data(a)
        print(f"   len={len(d['summary'] or ''):>5}  {str(d['title'])[:70]}")


if __name__ == "__main__":
    main()
