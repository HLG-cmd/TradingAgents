"""quant/factor_backtest.py 的单元测试。

测试核心契约：
- spearman(x, y) 秩相关：样本数门槛 (<8 返回 NaN)、零方差保护、正负秩相关准确性
- summarize(ic) 统计指标：N<6 保护、IC、ICIR、t-stat、胜率计算
- composite_trend_score 趋势打分：动量分位(60%) + 均线形态(25%) + RSI区间(15%)
- quintile_spread 五分位多空收益差计算
- factors_at 时点因子截面计算（不足 210 日返回空）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import quant.factor_backtest as fb


def test_spearman_sample_size_threshold():
    # 样本量 < 8 返回 NaN
    x = pd.Series([1, 2, 3, 4, 5, 6, 7])
    y = pd.Series([7, 6, 5, 4, 3, 2, 1])
    assert np.isnan(fb.spearman(x, y))


def test_spearman_zero_variance():
    # 零方差（常数序列）保护
    x = pd.Series([1.0] * 10)
    y = pd.Series(range(10))
    assert np.isnan(fb.spearman(x, y))


def test_spearman_perfect_correlation():
    x = pd.Series(range(10))
    y = pd.Series(range(10))
    assert round(fb.spearman(x, y), 4) == 1.0

    y_inv = pd.Series(range(9, -1, -1))
    assert round(fb.spearman(x, y_inv), 4) == -1.0


def test_summarize_sample_size_threshold():
    ic = pd.Series([0.05, 0.08, -0.02, 0.04])
    s = fb.summarize(ic)
    assert np.isnan(s["IC"])
    assert s["N"] == 4


def test_summarize_metrics():
    # 构造确定性的 10 个月度 IC
    ic = pd.Series([0.10, 0.12, 0.08, 0.14, 0.06, 0.10, -0.05, 0.09, 0.11, 0.05])
    s = fb.summarize(ic)
    assert round(s["IC"], 4) == round(ic.mean(), 4)
    assert s["N"] == 10
    assert s["胜率"] == 0.9  # 9个大于0，1个小于0
    assert not np.isnan(s["ICIR"])
    assert not np.isnan(s["t"])


def test_composite_trend_score_weights():
    # 验证打分各维度贡献
    df = pd.DataFrame({
        "mom60": [0.1, 0.2, 0.3, 0.4],
        "is_bull": [1.0, 1.0, 0.0, 0.0],
        "rsi": [55.0, 60.0, 20.0, 80.0],  # 55/60 在 45~68 区间内得分 100
    })
    scores = fb.composite_trend_score(df)
    assert len(scores) == 4
    # 动量最大且多头且RSI舒适区的一定最高
    assert scores.iloc[1] > scores.iloc[0]
    assert scores.iloc[0] > scores.iloc[2]


def test_quintile_spread():
    # 构造 20 只股票，因子和前瞻收益完全正相关
    f = pd.DataFrame({
        "mom": range(20),
    }, index=[f"T{i}" for i in range(20)])
    fwd = pd.Series([i * 0.01 for i in range(20)], index=[f"T{i}" for i in range(20)])

    spread = fb.quintile_spread(f, fwd, "mom")
    assert not np.isnan(spread)
    assert spread > 0


def test_factors_at_history_too_short():
    C = pd.DataFrame({"AAPL": range(100)})
    V = pd.DataFrame({"AAPL": [1000] * 100})
    res = fb.factors_at(C, V, 50)
    assert res.empty
