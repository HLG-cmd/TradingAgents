# lifecycle: oneoff
"""Probe yfinance identity for SK Hynix related tickers (SKHY / HXSCF / 000660.KS)."""
import sys

import yfinance as yf

TICKERS = ["SKHY", "HXSCF", "000660.KS"]


def main() -> int:
    for t in TICKERS:
        print("=" * 70)
        print(f"TICKER: {t}")
        try:
            tk = yf.Ticker(t)
            fi = tk.fast_info
            print(f"  fast_info.last_price = {getattr(fi, 'last_price', 'N/A')}")
        except Exception as e:  # noqa: BLE001
            print(f"  fast_info ERROR: {type(e).__name__}: {e}")
        try:
            info = tk.info
            keys = [
                "longName", "shortName", "quoteType", "exchange", "fullExchangeName",
                "currency", "marketCap", "sharesOutstanding", "trailingPE", "forwardPE",
                "totalRevenue", "netIncomeToCommon", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
                "regularMarketPrice", "previousClose",
            ]
            for k in keys:
                print(f"  info.{k} = {info.get(k)}")
        except Exception as e:  # noqa: BLE001
            print(f"  info ERROR: {type(e).__name__}: {e}")
        try:
            h = tk.history(period="1y")
            print(f"  history rows(1y) = {len(h)}")
            if len(h):
                print(f"  history first = {h.index[0].date()} last = {h.index[-1].date()}")
                print(f"  last close = {h['Close'].iloc[-1]:.4f}")
        except Exception as e:  # noqa: BLE001
            print(f"  history ERROR: {type(e).__name__}: {e}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
