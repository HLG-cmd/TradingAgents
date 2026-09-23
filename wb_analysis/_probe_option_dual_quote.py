# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_probe_option_dual_quote.py
"""判定期权链「有双边报价」与「新鲜成交」两个集合的交集（决定期权维度能否使用）。

背景：NFLX 在美东 02:52（盘前）采集时，采集器报告
「有双边报价合约 1659 个，但合格（≤5 天）样本 0，最新成交距今 47.5 天」⇒ IV 等级 NONE。
而只统计 `lastTradeDate` 的分布时，众数却是当日（513 条）。
⇒ 两个集合可能不相交：**当日成交的合约在盘前已无双边报价；有双边报价的都是远期冷门合约（最后成交在数周前）**。
本脚本把这两个集合分别数清楚，并给出交集，以确定结论该是「不可用」还是「采集器误判」。

用法: ./.venv/Scripts/python.exe wb_analysis/_probe_option_dual_quote.py NFLX
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import yfinance as yf

ET = timezone(timedelta(hours=-4))
MAX_AGE_DAYS = 5


def main() -> int:
    ticker = sys.argv[1]
    now = datetime.now(timezone.utc).astimezone(ET)
    print(f"[probe] 现在（美东）= {now:%Y-%m-%d %H:%M}  |  新鲜度阈值 {MAX_AGE_DAYS} 天")

    t = yf.Ticker(ticker)
    exps = list(t.options)
    print(f"[probe] 到期日 {len(exps)} 个")

    tot = dual = dual_fresh = 0
    dual_dates = Counter()
    fresh_dates = Counter()
    per_exp = []

    for exp in exps:
        try:
            ch = t.option_chain(exp)
        except Exception as exc:  # noqa: BLE001
            print(f"  {exp}: 拉取失败 {exc!r}")
            continue
        n_dual = n_dual_fresh = 0
        for df in (ch.calls, ch.puts):
            if df is None or len(df) == 0:
                continue
            for _, r in df.iterrows():
                tot += 1
                bid = float(r.get("bid") or 0)
                ask = float(r.get("ask") or 0)
                ltd = r.get("lastTradeDate")
                if hasattr(ltd, "to_pydatetime"):
                    ltd = ltd.to_pydatetime()
                if getattr(ltd, "tzinfo", None) is not None:
                    ltd = ltd.astimezone(ET)
                age = None
                if ltd is not None:
                    age = (now - ltd).total_seconds() / 86400.0
                    fresh_dates[ltd.date().isoformat()] += 1
                if bid > 0 and ask >= bid:
                    dual += 1
                    n_dual += 1
                    if ltd is not None:
                        dual_dates[ltd.date().isoformat()] += 1
                    if age is not None and age <= MAX_AGE_DAYS:
                        dual_fresh += 1
                        n_dual_fresh += 1
        per_exp.append((exp, n_dual, n_dual_fresh))

    print(f"\n[probe] 合约总数={tot}  有双边报价={dual}  其中有双边报价且成交≤{MAX_AGE_DAYS}天={dual_fresh}")

    print("\n[probe] 有双边报价的合约，其 lastTradeDate 分布（前 10）")
    for d, n in dual_dates.most_common(10):
        print(f"   {d}  {n}")
    if not dual_dates:
        print("   （无）")

    print("\n[probe] 全部合约的 lastTradeDate 分布（前 5，仅参考）")
    for d, n in fresh_dates.most_common(5):
        print(f"   {d}  {n}")

    print("\n[probe] 逐到期日：双边报价数 / 其中新鲜数（前 10 个到期日）")
    for exp, nd, nf in per_exp[:10]:
        print(f"   {exp}  双边 {nd:4d}  新鲜 {nf:4d}")

    verdict = "可用" if dual_fresh > 50 else "不可用（应声明为真实缺口）"
    print(f"\n[probe] 判定：期权维度 **{verdict}**（判据：双边报价 ∩ 新鲜成交的样本数）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
