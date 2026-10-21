# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_probe_option_freshness.py
"""独立复核 GOOG 期权链的「快照新鲜度」。

背景：铁律 1 说盘后采集的期权链可能是残留快照；本脚本用 lastTradeDate 的
**分布**（而不是单一最小值）判断整条链是否在最近一个交易日被刷新过。

判据：
  - 若快照确为 2026-09-21 收盘刷新，则 lastTradeDate 的**众数/中位数**应落在
    2026-09-21（或极少数挂在 09-18）。
  - 若为 09-17 的残留快照，则中位数会落在 2026-09-17 甚至更早。

用法: ./.venv/Scripts/python.exe wb_analysis/_probe_option_freshness.py GOOG
"""
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wb_analysis._thresholds import MARKET_TZ_NAME  # noqa: E402

# ⚠️ 2026-10-10：`timezone(timedelta(hours=-4))` 只在夏令时成立（冬季应为 UTC−5）⇒ 改用 IANA 时区名。
ET = ZoneInfo(MARKET_TZ_NAME)


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "GOOG"
    now_et = datetime.now(timezone.utc).astimezone(ET)
    print(f"[probe] 本地运行时刻 (美东) = {now_et:%Y-%m-%d %H:%M:%S}")

    t = yf.Ticker(ticker)
    expiries = list(t.options)
    print(f"[probe] 到期日数量 = {len(expiries)}")

    dates = Counter()
    per_expiry = []
    for exp in expiries[:8]:
        try:
            ch = t.option_chain(exp)
        except Exception as exc:  # noqa: BLE001
            print(f"  {exp}: 拉取失败 {exc!r}")
            continue
        rows = []
        for _side, df in (("C", ch.calls), ("P", ch.puts)):
            if "lastTradeDate" not in df.columns:
                continue
            for _, r in df.iterrows():
                ltd = r.get("lastTradeDate")
                if ltd is None:
                    continue
                if hasattr(ltd, "to_pydatetime"):
                    ltd = ltd.to_pydatetime()
                if getattr(ltd, "tzinfo", None) is not None:
                    ltd = ltd.astimezone(ET)
                dates[ltd.date().isoformat()] += 1
                rows.append(ltd)
        if rows:
            rows.sort()
            per_expiry.append((exp, min(rows).date().isoformat(), max(rows).date().isoformat(), len(rows)))

    print("\n[probe] lastTradeDate 日期分布（降序，前 15）")
    for d, n in dates.most_common(15):
        print(f"   {d}  {n:6d}")

    print("\n[probe] 每个到期日的 lastTradeDate 区间")
    for exp, lo, hi, n in per_expiry:
        print(f"   {exp}  min={lo}  max={hi}  n={n}")

    total = sum(dates.values())
    print(f"\n[probe] 样本合计 = {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
