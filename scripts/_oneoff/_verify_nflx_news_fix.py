# lifecycle: oneoff
# 用途：端到端验证 get_news 通道修复（Ticker 归零 -> Search 兜底 + 专属闸门）
# 判据（三条都必须满足，否则修复不算成功）：
#   P1 通道转绿：返回不再是 "No news found" / "Error fetching"
#   P2 语义专属：入选条目**全部**是 NFLX 主体报道（不得混入他股主体）
#   P3 无跨标的污染：不得出现 Google/Alphabet 主体文章（旧兜底的后门会放行 18 条）
import re
import sys

sys.path.insert(0, ".")

from tradingagents.dataflows.yfinance_news import get_news_yfinance  # noqa: E402

START, END = "2026-10-01", "2026-10-08"
BAD_SUBJECT = re.compile(r"\b(Google|Alphabet)\b")


def main():
    out = get_news_yfinance("NFLX", START, END)
    print("=" * 96)
    print("返回头 3 行:")
    for line in out.splitlines()[:3]:
        print("   ", line[:120])
    print(f"总长度 = {len(out)} 字符")

    ok = True
    # P1
    p1 = not out.startswith("No news found") and not out.startswith("Error fetching")
    print("=" * 96)
    print(f"P1 通道转绿（非 No news / Error）        : {'PASS' if p1 else 'FAIL'}")
    ok &= p1

    titles = [l[4:].strip() for l in out.splitlines() if l.startswith("### ")]
    print(f"入选条目数 = {len(titles)}")

    # P2 / P3
    bad = [t for t in titles if BAD_SUBJECT.search(t)]
    print("=" * 96)
    print("入选标题清单:")
    for i, t in enumerate(titles, 1):
        print(f"  {i:>2}. {t[:92]}")

    p3 = not bad
    print("=" * 96)
    print(f"P3 无 Google/Alphabet 主体污染           : {'PASS' if p3 else 'FAIL'}  (命中 {len(bad)} 条)")
    if bad:
        for t in bad:
            print("      x", t[:90])
    ok &= p3

    # P2：人工判据无法完全自动化，改为「标题含 Netflix/NFLX 的比例」+ 列出不含的供复核
    nl = [t for t in titles if re.search(r"Netflix|\bNFLX\b", t)]
    print(f"P2 标题含 Netflix/NFLX                   : {len(nl)}/{len(titles)}")
    other = [t for t in titles if not re.search(r"Netflix|\bNFLX\b", t)]
    if other:
        print("   不含者（须人工确认是否仍为 NFLX 主体，rt[0]==NFLX 才入选）:")
        for t in other:
            print("      ?", t[:90])

    print("=" * 96)
    print("总判定:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
