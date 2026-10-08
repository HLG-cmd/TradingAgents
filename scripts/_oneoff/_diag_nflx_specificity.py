# lifecycle: oneoff
# 用途：给 get_news 的 Search 兜底设计**语义专属判据**并实测命中率。
# 背景：_diag_nflx_search_quality.py 用「relatedTickers 含 NFLX」做专属判据，实测 49/49 全命中——
#       但抽查发现 MarketBeat Week in Review / Amazon AWS / Disney Stock 等**他股主体**文章
#       也被计入（relatedTickers 只是「提及」，不是「主体」）。
#       ⇒ 该判据是**弱判据**，会把噪声放行（铁律 6：分清主体与顺带提及）。
# 本脚本实测**强判据**三档，找出既挡噪声又留足条目的那条线。
import re
import sys
from datetime import datetime

sys.path.insert(0, ".")

import yfinance as yf  # noqa: E402
from tradingagents.dataflows.date_window import in_window  # noqa: E402

SYM = "NFLX"
START, END = "2026-10-01", "2026-10-08"
# 公司名也作主体育据（NFLX 官方名 Netflix）
NAME_PAT = re.compile(r"netflix", re.I)
TICK_PAT = re.compile(r"\bNFLX\b")


def related_of(a):
    rt = a.get("relatedTickers") or []
    return [str(x).strip() for x in rt if str(x).strip()]


def title_of(a):
    c = a.get("content")
    return str((c or a).get("title") or "")


def strong(title, rel):
    """强判据：标题含公司名或代码（主体出现在标题里）。"""
    return bool(NAME_PAT.search(title) or TICK_PAT.search(title))


def medium(title, rel):
    """中判据：强判据 OR relatedTickers 首位即本标的（Yahoo 常把主体排首位）。"""
    return strong(title, rel) or (len(rel) > 0 and rel[0] == SYM)


def main():
    start_dt = datetime.strptime(START, "%Y-%m-%d")
    end_dt = datetime.strptime(END, "%Y-%m-%d")
    s = yf.Search(query=SYM, news_count=50, enable_fuzzy_query=True)
    news = list(s.news or [])
    print(f"Search(query={SYM}, news_count=50) -> n={len(news)}")
    print(f"窗口 {START} ~ {END}")
    print("=" * 96)

    in_win = 0
    for a in news:
        if "content" in a:
            ts = a["content"].get("pubDate", "")
        else:
            ts = a.get("providerPublishTime")
        pub = None
        if isinstance(ts, str) and ts:
            try:
                pub = datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pub = None
        elif isinstance(ts, (int, float)) and ts:
            from datetime import timezone
            pub = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
        if pub and in_window(pub, start_dt, end_dt):
            in_win += 1

    cnt_weak = cnt_med = cnt_strong = 0
    rows = []
    for a in news:
        t, rel = title_of(a), related_of(a)
        w = SYM in rel
        m = medium(t, rel)
        st = strong(t, rel)
        cnt_weak += w
        cnt_med += m
        cnt_strong += st
        rows.append((st, m, w, t, rel))

    print(f"窗口内条数           : {in_win}/{len(news)}")
    print(f"弱判据(含于related)  : {cnt_weak}/{len(news)}   <- 放行噪声，不可用")
    print(f"中判据(标题|首位)    : {cnt_med}/{len(news)}")
    print(f"强判据(标题含名/码)  : {cnt_strong}/{len(news)}")
    print("=" * 96)
    print("【被中判据挡掉、但弱判据放行的条目】——这些正是要拦住的噪声：")
    for st, m, w, t, rel in rows:
        if w and not m:
            print(f"  x {t[:88]}")
            print(f"    related={rel[:8]}")
    print("=" * 96)
    print("【强判据保留的条目】——应全部是 NFLX 主体报道：")
    for st, m, w, t, rel in rows:
        if st:
            print(f"  o {t[:88]}")


if __name__ == "__main__":
    main()
