# lifecycle: maintenance
# 用途：确认任意标的当前美东时间 + 最近若干根日线，决定本轮分析基线（最新完整 bar）
# 用法：python scripts/_probe_baseline.py WDC
from __future__ import annotations

import sys
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from wb_analysis import _clock  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    ticker = args[0] if args else "WDC"

    now_et = _clock.now()
    print("ticker:", ticker)
    print("now_et:", now_et.isoformat())
    print("weekday:", now_et.strftime("%A"))
    print("minutes_since_midnight_et:", now_et.hour * 60 + now_et.minute)

    # 美东常规交易时段 09:30 - 16:00
    mins = now_et.hour * 60 + now_et.minute
    is_weekday = now_et.weekday() < 5
    in_session = is_weekday and (570 <= mins < 960)
    print("is_weekday:", is_weekday, "| in_regular_session:", in_session)

    t = yf.Ticker(ticker)
    df = t.history(period="12d", interval="1d", auto_adjust=False)
    print("bars:")
    print(df[["Open", "High", "Low", "Close", "Volume"]].to_string())
    print("last_bar_date:", df.index[-1])
    print("last_bar_close:", df["Close"].iloc[-1])
    print("last_bar_volume:", df["Volume"].iloc[-1])

    # 成交量粗糙启发式辅助观察（主判据见铁律 2：美东交易时段时点优先）
    vol = df["Volume"].tolist()
    if len(vol) >= 6:
        med = sorted(vol[-6:-1])[len(vol[-6:-1]) // 2]
        print("median_vol_prior5:", med)
        print("last_vs_median_ratio:", round(vol[-1] / med, 4) if med else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
