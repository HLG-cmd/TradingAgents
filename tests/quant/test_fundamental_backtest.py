"""quant/fundamental_backtest.py 的单元测试。

测试核心契约：
- score_frame 截面百分位计算与行业中性化（同行业去均值、PE/PB 对数中性化）
- composite 多因子加权打分
- spearman 秩相关与 summarize 统计指标
- quintile_spread 五分位多空收益差
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import quant.fundamental_backtest as fbt


def test_score_frame_empty_or_too_small():
    raw = pd.DataFrame({"roe": [0.1, 0.2]})
    res = fbt.score_frame(raw, {})
    assert res.empty


def test_score_frame_without_neutralization():
    n = 15
    raw = pd.DataFrame({
        "roe": [0.05 + i * 0.02 for i in range(n)],
        "margin": [0.10 + i * 0.01 for i in range(n)],
        "rev_growth": [0.15 + i * 0.03 for i in range(n)],
        "rev_cagr3": [0.12 + i * 0.02 for i in range(n)],
        "pe": [15.0 + i * 2.0 for i in range(n)],
        "pb": [2.0 + i * 0.5 for i in range(n)],
    }, index=[f"TK{i}" for i in range(n)])

    scores = fbt.score_frame(raw, sector_map={}, neutral=False)
    assert not scores.empty
    expected_cols = {"quality_score", "growth_score", "cagr_score", "val_score", "val_pb_score", "val2_score"}
    assert expected_cols <= set(scores.columns)

    # roe 最高的质量分最高
    assert scores.loc["TK14", "quality_score"] > scores.loc["TK0", "quality_score"]
    # pe 越低估值分越高（便宜=高分）
    assert scores.loc["TK0", "val_score"] > scores.loc["TK14", "val_score"]


def test_score_frame_with_neutralization():
    n = 20
    # 前 10 只为科技板块（Tech），后 10 只为消费板块（Cons）
    tickers = [f"TK{i}" for i in range(n)]
    sector_map = {t: ("Tech" if i < 10 else "Cons") for i, t in enumerate(tickers)}

    raw = pd.DataFrame({
        "roe": [0.30 if i < 10 else 0.10 for i in range(n)],  # Tech 均值高，Cons 均值低
        "margin": [0.20 for _ in range(n)],
        "rev_growth": [0.15 for _ in range(n)],
        "rev_cagr3": [0.10 for _ in range(n)],
        "pe": [30.0 for _ in range(n)],
        "pb": [5.0 for _ in range(n)],
    }, index=tickers)

    # 改变 Tech 组内一只标的的 roe，让它在 Tech 内部更优
    raw.loc["TK0", "roe"] = 0.35

    scores = fbt.score_frame(raw, sector_map, neutral=True)
    assert not scores.empty
    # TK0 即使在全体科技高 ROE 下，也在同行业内领先
    assert scores.loc["TK0", "quality_score"] > scores.loc["TK1", "quality_score"]


def test_composite_weights():
    df = pd.DataFrame({
        "quality_score": [80.0, 50.0],
        "val_score": [70.0, 90.0],
        "growth_score": [90.0, 60.0],
    })
    w = {"quality": 0.4, "value": 0.3, "growth": 0.3}
    comp = fbt.composite(df, w)
    expected0 = 80.0 * 0.4 + 70.0 * 0.3 + 90.0 * 0.3
    assert round(comp.iloc[0], 2) == round(expected0, 2)


def test_spearman_and_summarize():
    x = pd.Series(range(10))
    y = pd.Series(range(10))
    assert round(fbt.spearman(x, y), 4) == 1.0

    ic = pd.Series([0.1, 0.15, -0.05, 0.2, 0.08, 0.12])
    res = fbt.summarize(ic)
    assert round(res["IC"], 4) == round(ic.mean(), 4)
    assert res["N"] == 6


def test_quintile_spread():
    f = pd.Series(range(20), index=[f"T{i}" for i in range(20)])
    fwd = pd.Series([i * 0.02 for i in range(20)], index=[f"T{i}" for i in range(20)])
    spread = fbt.quintile_spread(f, fwd)
    assert not np.isnan(spread)
    assert spread > 0
