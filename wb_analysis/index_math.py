# lifecycle: reusable
# created: 2026-10-21
"""Black-Scholes-Merton 金融工程纯数学计算模块。

提供欧式期权理论定价、Delta 计算、隐含波动率（IV）二分法反解。
零外部 IO，零第三方复杂依赖（仅依赖标准库 math）。
"""
from __future__ import annotations

import math

__all__ = ["_norm_cdf", "_bs_price", "_bs_delta", "_implied_vol"]


def _norm_cdf(x: float) -> float:
    """标准正态 CDF（用 math.erf 精确计算，不引入 scipy 依赖）。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(spot: float, strike: float, t: float, vol: float,
              rate: float, div: float, is_call: bool) -> float:
    """Black-Scholes-Merton 欧式期权理论价（**含连续股息率**）。

    **为什么必须带股息率 ``div``**：ETF 代理是派息 ETF。实测对 638 天 LEAPS 做反解，
    令 q=0 会使反解 IV 相对报价自身隐含的水平系统性偏离；把 q 调到由 put-call
    parity 实测反解出的水平后，两侧报价才互相自洽。**股息率对长天期期权的
    影响不能忽略** —— 这正是旧实现（无股息近似）产出错误 IV 的直接原因。
    """
    if t <= 0 or vol <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    sq = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / sq
    d2 = d1 - sq
    fwd = spot * math.exp(-div * t)
    disc = math.exp(-rate * t)
    if is_call:
        return fwd * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
    return strike * disc * _norm_cdf(-d2) - fwd * _norm_cdf(-d1)


def _bs_delta(spot: float, strike: float, t: float, vol: float,
              rate: float, div: float, is_call: bool) -> float:
    """BS delta（带符号）：call 为正、put 为负。用于 25-delta 配对。"""
    if t <= 0 or vol <= 0:
        return 0.0
    sq = vol * math.sqrt(t)
    d1 = (math.log(spot / strike) + (rate - div + 0.5 * vol * vol) * t) / sq
    disc = math.exp(-div * t)
    call_delta = disc * _norm_cdf(d1)
    return call_delta if is_call else call_delta - disc


def _implied_vol(mid: float, spot: float, strike: float, t: float,
                 rate: float, div: float, is_call: bool) -> float | None:
    """从中间价反解 BSM 隐含波动率（二分法，70 次迭代到约 1e-8）。

    **为什么不用 yfinance 自带的 ``impliedVolatility``**：
    实测该字段与报价不自洽。对 ETF 代理的 LEAPS 合约，用 mid 反解得到的
    IV 与 yfinance 自报值系统性偏离，且 **call 侧与 put 侧的偏离方向相反**
    （call 侧自报偏高、put 侧自报偏低），说明不是统一的模型参数问题，
    而是该字段本身口径不明 —— 无报价时段它还会由**过期的 lastPrice**
    反解，产出 0.001%~0.4% 的垃圾值。

    用**买卖权平价**可以判定谁对：同一行权价同时有 call/put 报价时，
    ``C − P = S·e^{−qT} − K·e^{−rT}``。实测该恒等式在 12 个配对样本上
    隐含的 S0 中位数为 703.12，与实际现价 704.72 仅差 **−0.23%** ——
    **报价本身是自洽的真实报价**，因此问题出在 yfinance 的 IV 字段上。

    本函数自解 IV，保证「IV 一定来自我们看到的那个报价」，并可施加
    无套利边界（低于内在价值 ⇒ 拒绝）与合理区间（[2%, 300%]）。
    """
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
    if not (mid > intrinsic):
        return None                      # 低于/等于内在价值 ⇒ 报价不可信
    lo, hi = 1e-4, 5.0
    if _bs_price(spot, strike, t, hi, rate, div, is_call) < mid:
        return None                      # 5 倍波动率都解释不了 ⇒ 错价
    for _ in range(70):
        midv = 0.5 * (lo + hi)
        if _bs_price(spot, strike, t, midv, rate, div, is_call) < mid:
            lo = midv
        else:
            hi = midv
    iv = 0.5 * (lo + hi)
    # IV 上界定为 120%：ETF 代理是低波动宽基 ETF，近两年 VXN 区间为 15.15~43.25。
    # 反解出 >120% 的唯一可能是**报价本身陈旧** —— 深度实值合约的挂单残留了
    # 昨日的内在价值，反解器为了拟合这个「不可能的价格」把 vol 推到极限。
    # 实测 2026-09-30（13 天）call 侧 K=410 反解 251.78%、K=430 反解 224.62%，
    # 这些值不是波动率，是「报价失真」的量化标记，必须丢弃。
    return iv if 0.02 <= iv <= 1.20 else None
