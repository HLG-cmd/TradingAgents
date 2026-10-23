"""Unit tests for tradingagents.dataflows.nan_daily_fix (Iron Law 58 + look-ahead guard)."""
from __future__ import annotations

import pandas as pd
import pytest

from tradingagents.dataflows import nan_daily_fix as ndf


def _make_1m_bars() -> pd.DataFrame:
    """Create synthetic 1m bars spanning pre-market (09:00), regular session (09:30, 15:59), and after-hours (16:15) ET."""
    idx = pd.DatetimeIndex(
        [
            "2026-05-07 09:00:00",
            "2026-05-07 09:30:00",
            "2026-05-07 12:00:00",
            "2026-05-07 15:59:00",
            "2026-05-07 16:15:00",
        ],
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "Open": [90.0, 100.0, 102.0, 104.0, 110.0],
            "High": [95.0, 103.0, 106.0, 105.0, 115.0],
            "Low": [88.0, 99.0, 101.0, 103.0, 109.0],
            "Close": [92.0, 101.0, 104.0, 105.5, 112.0],
            "Volume": [500, 1000, 2000, 1500, 800],
        },
        index=idx,
    )


@pytest.mark.unit
class TestAgg1mDaily:
    def test_equity_filters_to_regular_session(self, monkeypatch):
        bars = _make_1m_bars()

        class _FakeTicker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, **kwargs):
                return bars

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", _FakeTicker)

        row = ndf.agg_1m_daily("AAPL", "2026-05-07")
        assert row is not None
        assert row["Open"] == 100.0
        assert row["High"] == 106.0
        assert row["Low"] == 99.0
        assert row["Close"] == 105.5
        assert row["Volume"] == 4500

    def test_futures_aggregates_all_sessions(self, monkeypatch):
        bars = _make_1m_bars()

        class _FakeTicker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, **kwargs):
                return bars

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", _FakeTicker)

        row = ndf.agg_1m_daily("GC=F", "2026-05-07")
        assert row is not None
        assert row["Open"] == 90.0
        assert row["High"] == 115.0
        assert row["Low"] == 88.0
        assert row["Close"] == 112.0
        assert row["Volume"] == 5800

    def test_invalid_date_returns_none(self):
        assert ndf.agg_1m_daily("AAPL", "not-a-date") is None


@pytest.mark.unit
class TestPatchNanOhlcv:
    def test_as_of_prevents_future_lookahead_and_handles_datetime_column(self, monkeypatch):
        """Regression test:
        1) Passing as_of='2026-05-08' must bound the 5-day missing-row scan at 2026-05-08
           (never probing real wall-clock dates after 2026-05-08).
        2) Appending a missing row into a DataFrame whose 'Date' column is datetime64
           must not fail with TypeError on sort_values(by='Date').
        """
        queried_dates: list[str] = []

        def _fake_agg(canonical: str, date_str: str):
            queried_dates.append(date_str)
            if date_str == "2026-05-07":
                return {"Open": 100.0, "High": 105.0, "Low": 99.0, "Close": 104.0, "Volume": 3000}
            return None

        monkeypatch.setattr(ndf, "agg_1m_daily", _fake_agg)

        df = pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-05-04", "2026-05-05", "2026-05-06"]),
                "Open": [95.0, 96.0, 97.0],
                "High": [96.0, 97.0, 98.0],
                "Low": [94.0, 95.0, 96.0],
                "Close": [95.5, 96.5, 97.5],
                "Volume": [1000, 1100, 1200],
            }
        )

        patched_df, notes = ndf.patch_nan_ohlcv(df, "AAPL", as_of="2026-05-08")
        assert all(d < "2026-05-08" for d in queried_dates)
        assert len(patched_df) == 4
        assert pd.api.types.is_datetime64_any_dtype(patched_df["Date"])
        assert patched_df["Date"].dt.strftime("%Y-%m-%d").tolist() == [
            "2026-05-04",
            "2026-05-05",
            "2026-05-06",
            "2026-05-07",
        ]
        assert float(patched_df["Close"].iloc[-1]) == 104.0
        assert any("缺失整行日线的日期 2026-05-07" in n for n in notes)

    def test_nan_row_patched_on_datetime_index_and_skips_as_of_day(self, monkeypatch):
        def _fake_agg(canonical: str, date_str: str):
            return {"Open": 200.0, "High": 210.0, "Low": 195.0, "Close": 205.0, "Volume": 5000}

        monkeypatch.setattr(ndf, "agg_1m_daily", _fake_agg)

        idx = pd.DatetimeIndex(["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"])
        df = pd.DataFrame(
            {
                "Open": [190.0, 191.0, 192.0, float("nan"), float("nan")],
                "High": [192.0, 193.0, 194.0, float("nan"), float("nan")],
                "Low": [189.0, 190.0, 191.0, float("nan"), float("nan")],
                "Close": [191.0, 192.0, 193.0, float("nan"), float("nan")],
                "Volume": [100, 100, 100, 50, 10],
            },
            index=idx,
        )

        patched_df, notes = ndf.patch_nan_ohlcv(df, "AAPL", as_of="2026-05-08")
        # 2026-05-07 (< as_of) must be patched; 2026-05-08 (== as_of) must remain NaN
        assert float(patched_df.loc["2026-05-07", "Close"]) == 205.0
        assert pd.isna(patched_df.loc["2026-05-08", "Close"])
        assert any("2026-05-07" in n for n in notes)


@pytest.mark.unit
class TestPatchDownloadNan:
    def test_multiindex_download_nan_patched_in_place(self, monkeypatch):
        monkeypatch.setattr(
            ndf,
            "_agg_multi_1m",
            lambda tickers, d: {
                "AAPL": {"Open": 150.0, "High": 155.0, "Low": 149.0, "Close": 154.0, "Volume": 9000}
            },
        )
        idx = pd.DatetimeIndex(["2026-05-06", "2026-05-07"])
        cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], ["AAPL"]])
        df = pd.DataFrame(100.0, index=idx, columns=cols)
        df.loc["2026-05-07", ("Close", "AAPL")] = float("nan")

        out, notes = ndf.patch_download_nan(df, ["AAPL"])
        assert float(out.loc["2026-05-07", ("Close", "AAPL")]) == 154.0
        assert len(notes) == 1
