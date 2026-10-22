"""wb_analysis/_selfcalc_valuation.py 的测试。

它是「独立于 vendor 实时快照的第二条估值通道」，卖点是**真正的 point-in-time**：
每个数字都要能说清来源与时点。所以测试守两件事：

1. 取不到就置 None 并记原因 —— 不许静默填 0（0 会读成「算出来就是 0」）
2. 时点口径按模块文档写的来 —— 但文档口径本身有一处可疑，见
   ``test_edgar_shares_takes_latest_end_before_as_of`` 里的 ⚠️ 注记
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from wb_analysis import _selfcalc_valuation as sv


@pytest.fixture()
def home(tmp_path, monkeypatch):
    (tmp_path / "cache").mkdir()
    (tmp_path / "edgar").mkdir()
    monkeypatch.setattr(sv, "PRICE_CACHE", tmp_path / "cache")
    monkeypatch.setattr(sv, "EDGAR_DIR", tmp_path / "edgar")
    return tmp_path


def _write_prices(home, ticker="AVGO", n=400, end="2026-09-25", close=100.0):
    idx = pd.bdate_range(end=end, periods=n)
    closes = np.full(n, float(close))
    df = pd.DataFrame({"Date": idx, "Open": closes, "High": closes * 1.05,
                       "Low": closes * 0.95, "Close": closes, "Volume": 1000})
    p = home / "cache" / f"{ticker}-YFin-data-2020-01-01-{end}.csv"
    df.to_csv(p, index=False)
    return p


def _write_facts(home, ticker="AVGO", entries=None):
    facts = {"facts": {
        "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": entries}}},
        "us-gaap": {"WeightedAverageNumberOfDilutedSharesOutstanding":
                    {"units": {"shares": entries}}},
    }}
    p = home / "edgar" / f"facts_{ticker}_2026-09-25.json"
    p.write_text(json.dumps(facts), encoding="utf-8")
    return p


# ── 价格序列 ──────────────────────────────────────────────────────────────

def test_price_frame_requires_200_bars(home):
    """少于 200 根无法算 200SMA，必须判为不可用，而不是凑合算。"""
    _write_prices(home, n=150)
    frame, src = sv._price_frame("AVGO", "2026-09-25")
    assert frame is None
    assert "未找到可用价格序列" in src


def test_price_frame_truncates_at_as_of(home):
    _write_prices(home, n=400, end="2026-09-25")
    frame, src = sv._price_frame("AVGO", "2026-06-30")
    assert frame is not None
    assert frame["Date"].max() <= pd.Timestamp("2026-06-30")
    assert "止于" in src, "来源说明必须带实际截止日，否则看不出用的是哪段历史"


def test_selfcalc_bails_out_with_reason_when_no_prices(home):
    out = sv.selfcalc("AVGO", "2026-09-25")
    assert "close" not in out, "价格都取不到就不该给出任何估值数字"
    assert any("价格序列不可用" in n for n in out["notes"])


# ── 自算估值 ──────────────────────────────────────────────────────────────

def test_selfcalc_market_cap_and_multiples(home):
    _write_prices(home, n=400, end="2026-09-25", close=100.0)
    _write_facts(home, entries=[
        {"end": "2026-06-30", "val": 1_000_000, "form": "10-Q", "filed": "2026-07-25"},
    ])
    out = sv.selfcalc("AVGO", "2026-09-25", fy_net_income=5e6,
                      fy_revenue=20e6, fy_equity=40e6)

    assert out["close"] == pytest.approx(100.0)
    assert out["market_cap"] == pytest.approx(100.0 * 1_000_000)
    assert out["pe_fy"] == pytest.approx(out["market_cap"] / 5e6)
    assert out["ps_fy"] == pytest.approx(out["market_cap"] / 20e6)
    assert out["pb_fy"] == pytest.approx(out["market_cap"] / 40e6)
    assert out["sources"]["price"] and out["sources"]["edgar"]
    # 常数序列 ⇒ 对数收益全 0 ⇒ 年化波动率为 0（而不是 NaN）
    assert out["vol_annual"] == pytest.approx(0.0)


def test_selfcalc_omits_multiples_when_inputs_missing(home):
    """没传报表项 ⇒ 对应倍数**不出现**，不能悄悄算成 0 或 inf。"""
    _write_prices(home, n=400, end="2026-09-25")
    _write_facts(home, entries=[
        {"end": "2026-06-30", "val": 1_000_000, "form": "10-Q", "filed": "2026-07-25"},
    ])
    out = sv.selfcalc("AVGO", "2026-09-25")
    for k in ("pe_fy", "ps_fy", "pb_fy", "pe_ttm", "ps_ttm"):
        assert k not in out, k


def test_selfcalc_notes_when_shares_missing(home):
    _write_prices(home, n=400, end="2026-09-25")
    out = sv.selfcalc("AVGO", "2026-09-25", fy_net_income=5e6)
    assert "market_cap" not in out
    assert "pe_fy" not in out, "没有市值就不能算 PE"
    assert any("股数" in n for n in out["notes"])


# ── EDGAR 股数的时点口径 ──────────────────────────────────────────────────

def test_edgar_shares_takes_latest_end_before_as_of(home):
    """口径（PIT 规范化）：取 ``end <= 基准日`` 且 ``filed <= 基准日`` 的最新一条披露。

    ★ 2026-10-22 拍板：彻底防范未来数据泄露（Look-ahead Bias）。
    基准日 2026-10-15 不得选中 2026-11-05 才向 SEC 申报的报表（虽然其季度末是 2026-09-30），
    必须选中申报日也在基准日之前的最新有效报表（2026-06-30 / filed 2026-07-25）。
    """
    _write_facts(home, entries=[
        {"end": "2026-06-30", "val": 1000, "form": "10-Q", "filed": "2026-07-25"},
        {"end": "2026-09-30", "val": 2000, "form": "10-Q", "filed": "2026-11-05"},
        {"end": "2027-03-31", "val": 3000, "form": "10-Q", "filed": "2027-05-01"},
    ])
    sh, _dil, src = sv._edgar_shares("AVGO", "2026-10-15")
    assert sh["val"] == 1000
    assert sh["filed"] == "2026-07-25", "申报日必须在基准日之前，保证真正的 Point-in-Time 语义"
    assert "facts_AVGO" in src


def test_edgar_shares_none_when_no_disclosure_before_as_of(home):
    _write_facts(home, entries=[
        {"end": "2027-03-31", "val": 3000, "form": "10-Q", "filed": "2027-05-01"},
    ])
    sh, dil, _src = sv._edgar_shares("AVGO", "2026-10-15")
    assert sh is None and dil is None


def test_edgar_shares_reports_missing_cache(home):
    sh, dil, src = sv._edgar_shares("AVGO", "2026-10-15")
    assert sh is None and dil is None
    assert "未找到 EDGAR 缓存" in src


# ── 渲染 ──────────────────────────────────────────────────────────────────

def test_render_markdown_marks_missing_and_computes_diff():
    out = {"ticker": "AVGO", "as_of": "2026-09-25",
           "sources": {"price": "p.csv", "edgar": "facts.json"},
           "close": 100.0, "close_date": "2026-09-25",
           "market_cap": 100e9, "high_52w": 110.0, "low_52w": 90.0,
           "ma50": 100.0, "ma200": 100.0, "vol_annual": 0.25}
    md = sv.render_markdown(out, {"Market Cap": 110e9, "52 Week High": 110.0})

    assert "| 市值 | 100.0B | 110.0B | -9.09% |" in md
    assert "| PE(TTM) | — | — | — |" in md, "缺值画「—」，不能画 0"
    assert "25.00%" in md
    assert "口径提示" in md
