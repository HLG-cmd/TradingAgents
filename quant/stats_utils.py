# lifecycle: reusable
# created: 2026-10-23
# usage: from quant.stats_utils import spearman, summarize, quintile_spread   （库；被回测脚本 import，不单独运行）
"""量化因子回测统计函数的**唯一定义源**（IC / ICIR / t-stat / 胜率 / 五分位收益差）。

## 为什么抽出这个模块（2026-10-23）

此前 `quant/factor_backtest.py` 与 `quant/fundamental_backtest.py` 各自复制了一份
`spearman`、`summarize`、`quintile_spread`。这三项正是 `WORKFLOW.md` 与 `SCREENER.md`
中跨档比较 IC / ICIR / t / 胜率的权威口径；两处维护极易因样本门槛（如 `<8` vs `<6`）
或分位点定义发生分叉，违反「同一口径只允许在一处定义」原则。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = ["quintile_spread", "spearman", "summarize"]


def spearman(x: pd.Series, y: pd.Series) -> float:
    """截面 Spearman 秩相关系数（有效样本 < 8 或零方差时返回 NaN）。"""
    m = x.notna() & y.notna()
    if m.sum() < 8:
        return np.nan
    rx = x[m].rank().values
    ry = y[m].rank().values
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def summarize(ic: pd.Series) -> dict:
    """汇总 IC 序列的均值、ICIR、t 统计量、胜率与期数 N（N < 6 时统计量返回 NaN）。"""
    ic = ic.dropna()
    n = len(ic)
    if n < 6:
        return {"IC": np.nan, "ICIR": np.nan, "t": np.nan, "胜率": np.nan, "N": n}
    mean, sd = ic.mean(), ic.std(ddof=1)
    return {
        "IC": mean,
        "ICIR": mean / sd if sd else np.nan,
        "t": mean / (sd / np.sqrt(n)) if sd else np.nan,
        "胜率": (ic > 0).mean(),
        "N": n,
    }


def quintile_spread(
    f: pd.DataFrame | pd.Series,
    fwd: pd.Series,
    col: str | None = None,
) -> float:
    """最高 20% 组 − 最低 20% 组的平均前瞻收益。

    同时兼容两种调用签名：
    - `quintile_spread(series, fwd)`（直接传因子 Series）
    - `quintile_spread(df, fwd, col)`（传因子 DataFrame 与列名）
    """
    series = f[col] if col is not None else f
    s = series.dropna()
    common = s.index.intersection(fwd.dropna().index)
    if len(common) < 10:
        return np.nan
    s = s[common]
    r = fwd[common]
    hi = s >= s.quantile(0.8)
    lo = s <= s.quantile(0.2)
    if hi.sum() == 0 or lo.sum() == 0:
        return np.nan
    return float(r[hi].mean() - r[lo].mean())
