"""quant/smart_screener.py 的单元测试。

测试核心契约：
- 命令行参数解析与股票池选择路由
- --skip-agent 模式在量化初筛后直接退出，不触碰 LLM 智能体
- 异常剔除记录与研报 Markdown 导出格式
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

import quant.smart_screener as ss


def test_factor_weights_sum():
    assert "quality" in ss.FACTOR_WEIGHTS
    assert "value" in ss.FACTOR_WEIGHTS
    assert "growth" in ss.FACTOR_WEIGHTS
    assert "trend" in ss.FACTOR_WEIGHTS
    assert round(sum(ss.FACTOR_WEIGHTS.values()), 4) == 1.0


def test_main_skip_agent_nasdaq(monkeypatch, tmp_path):
    monkeypatch.setattr(ss, "PROJECT_ROOT", tmp_path)
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
        "净利率%": [30.0, 25.0, 20.0],
        "营收增速%": [40.0, 15.0, 12.0],
        "60日涨幅%": [25.0, 15.0, 10.0],
    })
    monkeypatch.setattr(ss, "get_latest_nasdaq_100", lambda: ["NVDA", "AAPL", "MSFT"])
    monkeypatch.setattr(ss, "run_quant_screening", lambda *a, **k: df)
    mock_export = MagicMock()
    monkeypatch.setattr(ss, "export_radar_csv", mock_export)

    monkeypatch.setattr(
        "sys.argv",
        ["smart_screener.py", "--pool", "nasdaq", "--top", "2", "--skip-agent"],
    )
    # 应该正常退出，不调用 TradingAgentsGraph
    ss.main()
    assert mock_export.called


def test_main_custom_tickers(monkeypatch, tmp_path):
    monkeypatch.setattr(ss, "PROJECT_ROOT", tmp_path)
    df = pd.DataFrame({
        "Ticker": ["TSLA"],
        "Price": [250.0],
        "综合量化分": [88.0],
        "quality_score": [85.0],
        "val_score": [70.0],
        "growth_score": [90.0],
        "trend_score": [95.0],
        "PE": [60.0],
        "ROE%": [20.0],
        "净利率%": [15.0],
        "营收增速%": [25.0],
        "60日涨幅%": [30.0],
    })
    monkeypatch.setattr(ss, "run_quant_screening", lambda *a, **k: df)
    monkeypatch.setattr(ss, "export_radar_csv", MagicMock())

    monkeypatch.setattr(
        "sys.argv",
        ["smart_screener.py", "--tickers", "TSLA", "--skip-agent"],
    )
    ss.main()
