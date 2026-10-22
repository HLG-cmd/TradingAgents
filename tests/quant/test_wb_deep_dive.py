"""quant/wb_deep_dive.py 的单元测试。

测试核心契约：
- POOLS 字典包含 nasdaq, sp500, sp500_core
- resolve_pool 正确路由到动态池解析器、静态核心子集或自定义代码列表
- _stage_one 量化初筛与导出流程
- main() 入口参数解析与流程装配
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

import quant.wb_deep_dive as wdd


def test_pools_dictionary_keys():
    assert "nasdaq" in wdd.POOLS
    assert "sp500" in wdd.POOLS
    assert "sp500_core" in wdd.POOLS


def test_resolve_pool_nasdaq(monkeypatch):
    monkeypatch.setattr(wdd, "get_latest_nasdaq_100", lambda: ["AAPL", "MSFT"])
    res = wdd.resolve_pool("nasdaq", [])
    assert res == ["AAPL", "MSFT"]


def test_resolve_pool_sp500(monkeypatch):
    monkeypatch.setattr(wdd, "get_latest_sp500", lambda: ["SP1", "SP2"])
    res = wdd.resolve_pool("sp500", [])
    assert res == ["SP1", "SP2"]


def test_resolve_pool_sp500_core():
    res = wdd.resolve_pool("sp500_core", [])
    assert res == wdd.SP_500_CORE


def test_resolve_pool_custom_tickers():
    custom = ["TSLA", "NVDA", "GOOG"]
    res = wdd.resolve_pool(None, custom)
    assert res == custom


def test_stage_one_empty_results(monkeypatch):
    monkeypatch.setattr(wdd, "run_quant_screening", lambda *a, **k: pd.DataFrame())
    cands, detail = wdd._stage_one("nasdaq", [], top=3)
    assert cands == []
    assert detail == ""


def test_stage_one_with_candidates(monkeypatch, tmp_path):
    monkeypatch.setattr(wdd, "PROJECT_ROOT", tmp_path)
    df = pd.DataFrame({
        "Ticker": ["NVDA", "AAPL", "MSFT"],
        "Price": [120.0, 220.0, 410.0],
        "综合量化分": [95.0, 90.0, 85.0],
        "quality_score": [90.0, 95.0, 80.0],
        "val_score": [70.0, 80.0, 75.0],
        "growth_score": [98.0, 85.0, 80.0],
        "trend_score": [90.0, 85.0, 80.0],
        "PE": [35.0, 30.0, 32.0],
        "ROE%": [45.0, 35.0, 30.0],
        "60日涨幅%": [25.0, 15.0, 10.0],
    })
    monkeypatch.setattr(wdd, "run_quant_screening", lambda *a, **k: df)
    monkeypatch.setattr(wdd, "export_radar_csv", MagicMock())

    cands, detail = wdd._stage_one("sp500_core", [], top=2)
    assert cands == ["NVDA", "AAPL"]
    assert "NVDA" in detail
    assert "AAPL" in detail


def test_main_with_tickers(monkeypatch):
    mock_collect = MagicMock(return_value={
        "ticker": "AAPL",
        "health": {"yf": "ok", "sec": "ok"},
        "md": MagicMock(name="AAPL_2026-10-22.md"),
        "stats": {"latest_close": 225.0, "ret_20d": 5.2},
    })
    monkeypatch.setattr(wdd, "collect_one", mock_collect)
    monkeypatch.setattr("sys.argv", ["wb_deep_dive.py", "--tickers", "AAPL,NVDA"])

    rc = wdd.main()
    assert rc == 0
    assert mock_collect.call_count == 2
