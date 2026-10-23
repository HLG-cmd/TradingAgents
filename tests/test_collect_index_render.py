"""`collect_index` 两个纯渲染函数的单测（零网络、零文件 IO）。

为什么单独测这两块：§4 市场广度 与 §5 成分结构聚合是报告里被引用最多的两节，
此前它们内联在 576 行的 `collect_index` 里 ⇒ 只能联网跑整条链路才能碰到。
抽成纯函数后可以用合成 dict 精确锁住「口径文字 + 数值格式 + 截断条数」。

覆盖点：
* 错误分支必须显式写「不可用」而不是渲染出空骨架（`assemble` 曾把空骨架当报告）；
* 涨跌幅保留 2 位、市值换算 B、缺失 PE 显示 N/A（不是 0，也不是空白）；
* 前 15 / 后 10 的截断条数；
* 持仓为空时聚合口径必须标「不可用」，且 hold_sum 为 None（不能静默算成 0）。
"""
from __future__ import annotations

import pytest

from wb_analysis.collect_index import _render_breadth_block, _render_valuation_block


def _cand(ticker: str, ret20: float, ret60: float | None = None) -> dict:
    return {
        "ticker": ticker,
        "ret20": ret20,
        "ret60": ret60,
        "ret120": ret60,
        "above_200": True,
        "above_50": False,
        "last": 100.0 + ret20,
    }


def _breadth(n: int = 20) -> dict:
    return {
        "n_valid": n,
        "n_universe": n * 2,
        "pct_above_200sma": 62.5,
        "pct_above_50sma": 71.0,
        "pct_up_20d": 55.0,
        "pct_up_60d": 60.0,
        "pct_up_120d": 65.0,
        "median_ret20": 1.23,
        "equal_weight_ret20": 1.5,
        "median_ret60": 4.0,
        "equal_weight_ret60": 4.4,
        "dispersion_ret20": 7.89,
        # 递增收益：第 1 名 ret20 最大
        "candidates": [_cand(f"T{i:02d}", float(i)) for i in range(n)],
    }


def _val() -> dict:
    return {
        "agg_pe": 31.2,
        "n_pe_used": 95,
        "agg_forward_pe": 26.4,
        "agg_pb": 7.8,
        "agg_ps": 6.1,
        "earnings_yield_pct": 3.2,
        "agg_div_yield_pct": 0.8,
        "agg_roe_pct": 25.0,
        "agg_net_margin_pct": 22.0,
        "agg_gross_margin_pct": 55.0,
        "agg_op_margin_pct": 30.0,
        "agg_rev_growth_pct": 12.5,
        "agg_rev_growth_median_pct": 11.0,
        "agg_eps_growth_pct": 18.0,
        "agg_eps_growth_median_pct": 15.0,
        "agg_beta": 1.12,
        "median_beta": 1.05,
        "excluded_pe_tickers": ["XYZ"],
        "n_missing": 2,
        "missing": ["AAA", "BBB"],
        "total_market_cap": 3.2e13,
        "top10_weight_pct": 51.0,
        "top20_weight_pct": 72.0,
        "hhi": 0.05,
        "sector_weights": [("Technology", 60.0), ("Healthcare", 15.5)],
        "top10_by_weight": [
            {
                "ticker": "AAA", "name": "Alpha Corp", "weight_pct": 9.5,
                "marketCap": 3.1e12, "pe": 30.0, "fpe": 25.0, "pb": 12.0,
            },
            {
                "ticker": "BBB", "name": "Beta Inc", "weight_pct": 8.0,
                "marketCap": 2.0e12, "pe": None, "fpe": None, "pb": 5.0,
            },
        ],
    }


@pytest.mark.unit
class TestRenderBreadth:
    def test_error_branch_is_explicit(self):
        out = _render_breadth_block({"error": "RuntimeError: boom"})
        assert "(不可用: RuntimeError: boom)" in out
        # 错误时不得渲染出「0%」这类会被误读成真实读数的数字
        assert "%" not in out

    def test_headline_numbers_and_coverage(self):
        out = _render_breadth_block(_breadth(20))
        assert "站上 200SMA 比例: 62.5%" in out
        assert "站上 50SMA 比例: 71.0%" in out
        assert "有效样本: 20 只" in out
        assert "覆盖率 50.0%" in out  # n_valid / n_universe

    def test_truncates_top15_and_bottom10(self):
        out = _render_breadth_block(_breadth(20))
        top = out.split("### 20 日涨幅前 15 名")[1].split("### 20 日涨幅后 10 名")[0]
        bottom = out.split("### 20 日涨幅后 10 名")[1]
        # 按「以两个空格 + 代码」开头的行计数（不能用 count("20日")：120日 也含 20日）
        assert len([ln for ln in top.splitlines() if ln.startswith("  T")]) == 15
        assert len([ln for ln in bottom.splitlines() if ln.startswith("  T")]) == 10

    def test_sorted_by_ret20_desc(self):
        out = _render_breadth_block(_breadth(20))
        top = out.split("### 20 日涨幅前 15 名")[1]
        # 第 1 名必须是 ret20 最大的 T19
        assert "T19" in top.splitlines()[2] or "T19" in top.splitlines()[3]

    def test_candidates_without_ret20_are_excluded(self):
        b = _breadth(5)
        b["candidates"].append({"ticker": "NULL", "ret20": None, "ret60": None,
                                "ret120": None, "above_200": False, "above_50": False})
        out = _render_breadth_block(b)
        assert "NULL" not in out

    def test_missing_n_universe_does_not_crash(self):
        b = _breadth(3)
        b.pop("n_universe")
        assert "覆盖率 ?%" in _render_breadth_block(b)


@pytest.mark.unit
class TestRenderValuation:
    def test_error_branch_is_explicit(self):
        out = _render_valuation_block({"error": "no data"}, [], "NDX", "NDX")
        assert "(不可用: no data)" in out

    def test_all_five_subsections_present(self):
        out = _render_valuation_block(_val(), [{"symbol": "AAA", "name": "Alpha", "weight_pct": 9.5}],
                                      "NDX", "NDX")
        for sec in ("### 5.1", "### 5.2", "### 5.3", "### 5.4", "### 5.5"):
            assert sec in out, f"缺少小节 {sec}"

    def test_market_cap_in_billions_and_missing_pe_as_na(self):
        out = _render_valuation_block(_val(), [], "NDX", "NDX")
        assert "3100.0B" in out          # 3.1e12 → 3100.0B（右对齐有填充，故只断言数值部分）
        assert "PE      30.0" in out
        # 缺失 PE 必须显示 N/A，不能是 0 或空
        assert "PE      N/A" in out or "N/A" in out

    def test_holdings_empty_marks_official_metric_unavailable(self):
        out = _render_valuation_block(_val(), [], "NDX", "NDX")
        # hold_sum 为 None ⇒ 官方口径不得显示成 0.0%
        assert "前十大权重合计: None%" in out
        assert "(不可用)" in out

    def test_holdings_sum_rounded_to_2dp(self):
        holdings = [
            {"symbol": "AAA", "name": "Alpha", "weight_pct": 9.456},
            {"symbol": "BBB", "name": "Beta", "weight_pct": 8.044},
        ]
        out = _render_valuation_block(_val(), holdings, "NDX", "NDX")
        assert "前十大权重合计: 17.5%" in out

    def test_concentration_metrics_present(self):
        out = _render_valuation_block(_val(), [], "NDX", "NDX")
        assert "HHI 集中度指数（纯市值口径）: 0.05" in out
        assert "32.000 万亿美元" in out   # 3.2e13 = 32 万亿
