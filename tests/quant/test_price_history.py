"""quant/price_history.py 的回归测试。

锁的是**模块文档里写明的契约**，不是实现细节：
  · 缓存按票单文件命名 ``~/.tradingagents/prices/<TICKER>.csv``，且代码路径不可逃逸
  · **空数据不写盘** —— 模块注释明说「缓存一个空文件会让下游一直看到『无数据』」
  · 缓存新鲜时不打网络；``force=True`` 绕过缓存
  · 取回的行情做 tz 剥离、按日期升序、只保留 OHLCV 列
"""
from __future__ import annotations

import pandas as pd
import pytest

import quant.price_history as ph


class _StubTicker:
    def __init__(self, df, calls):
        self._df = df
        self._calls = calls

    def history(self, start=None, auto_adjust=None):
        self._calls.append({"start": start, "auto_adjust": auto_adjust})
        return self._df


def _ohlcv(rows: int = 3) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=rows, freq="D", tz="UTC")
    idx.name = "Date"  # yfinance 的索引名就是 Date，reset_index 靠它
    return pd.DataFrame(
        {"Open": range(rows), "High": range(rows), "Low": range(rows),
         "Close": [10.0 + i for i in range(rows)], "Volume": [100] * rows,
         "Dividends": [0.0] * rows, "Stock Splits": [0.0] * rows},
        index=idx,
    )


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ph, "CACHE_DIR", tmp_path)
    return tmp_path


def test_cache_file_sanitizes_and_uppercases(cache):
    assert ph._cache_file("aapl").name == "AAPL.csv"
    assert ph._cache_file("brk.b").name == "BRK.B.csv"
    # 路径分隔符必须被剔除，不能逃出缓存目录
    p = ph._cache_file("../../etc/passwd")
    assert p.parent == cache
    assert "/" not in p.name and "\\" not in p.name


def test_download_normalizes_and_caches(cache, monkeypatch):
    calls = []
    monkeypatch.setattr(ph.yf, "Ticker", lambda tk: _StubTicker(_ohlcv(), calls))
    df = ph.load_prices_long("nvda")
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert df["Date"].is_monotonic_increasing
    assert df["Date"].dt.tz is None
    assert calls and calls[0]["auto_adjust"] is True
    assert (cache / "NVDA.csv").exists()


def test_empty_history_is_not_written_to_cache(cache, monkeypatch):
    """空数据写盘 ⇒ 下游永远读到「无数据」。这是模块注释里的明契约。"""
    monkeypatch.setattr(ph.yf, "Ticker", lambda tk: _StubTicker(pd.DataFrame(), []))
    assert ph.load_prices_long("nope").empty
    assert not (cache / "NOPE.csv").exists()


def test_fresh_cache_short_circuits_network(cache, monkeypatch):
    pd.DataFrame({"Date": pd.to_datetime(["2026-01-01"]), "Close": [1.0]}).to_csv(
        cache / "AAPL.csv", index=False
    )
    calls = []
    monkeypatch.setattr(ph.yf, "Ticker", lambda tk: _StubTicker(_ohlcv(), calls))
    df = ph.load_prices_long("AAPL")
    assert len(df) == 1
    assert calls == []


def test_force_bypasses_cache(cache, monkeypatch):
    pd.DataFrame({"Date": pd.to_datetime(["2026-01-01"]), "Close": [1.0]}).to_csv(
        cache / "AAPL.csv", index=False
    )
    calls = []
    monkeypatch.setattr(ph.yf, "Ticker", lambda tk: _StubTicker(_ohlcv(), calls))
    assert len(ph.load_prices_long("AAPL", force=True)) == 3
    assert len(calls) == 1


def test_load_many_reports_failures(monkeypatch):
    def fake(ticker, start=None, force=False, max_age_days=1):
        if ticker == "BAD":
            raise RuntimeError("boom")
        if ticker == "EMPTY":
            return pd.DataFrame()
        return pd.DataFrame({"Date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
                             "Close": [1.0, 2.0]})

    monkeypatch.setattr(ph, "load_prices_long", fake)
    wide, failed = ph.load_many(["OK", "BAD", "EMPTY"])
    assert list(wide.columns) == ["OK"]
    reasons = dict(failed)
    assert "boom" in reasons["BAD"]
    assert reasons["EMPTY"] == "无数据"
