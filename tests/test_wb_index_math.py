"""wb_analysis/index_math.py 的测试 —— 纯金融工程数学，零 IO。

BSM 这类公式最怕「看着对、系数错了」，所以这里不逐项对照实现，
而是用**不依赖实现的恒等式**来验：

* 买卖权平价：``C − P = S·e^{−qT} − K·e^{−rT}``（同行权价、同参数）
* Delta 平价：``Δcall − Δput = e^{−qT}``
* 反解往返：给一个波动率定价、再反解，必须回到原值

参数取 ETF 代理的实测量级（现价 704.72、638 天 LEAPS），不是随手编的数。
"""
from __future__ import annotations

import math

import pytest

from wb_analysis.index_math import _bs_delta, _bs_price, _implied_vol, _norm_cdf

S, K, T, R, Q = 704.72, 700.0, 638 / 365, 0.042, 0.012


def test_norm_cdf_anchors():
    assert _norm_cdf(0.0) == pytest.approx(0.5)
    assert _norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-9)
    assert _norm_cdf(10.0) == pytest.approx(1.0)
    assert _norm_cdf(-1.0) + _norm_cdf(1.0) == pytest.approx(1.0)


@pytest.mark.parametrize("vol", [0.05, 0.15, 0.35, 0.80])
def test_put_call_parity_holds(vol):
    """含股息率的 BSM 必须满足买卖权平价 —— 系数错一个就会破。"""
    c = _bs_price(S, K, T, vol, R, Q, True)
    p = _bs_price(S, K, T, vol, R, Q, False)
    assert c - p == pytest.approx(S * math.exp(-Q * T) - K * math.exp(-R * T), abs=1e-9)


@pytest.mark.parametrize("vol", [0.15, 0.35])
def test_delta_parity_holds(vol):
    assert _bs_delta(S, K, T, vol, R, Q, True) - _bs_delta(S, K, T, vol, R, Q, False) \
        == pytest.approx(math.exp(-Q * T), abs=1e-12)


def test_call_delta_positive_put_delta_negative():
    assert _bs_delta(S, K, T, 0.3, R, Q, True) > 0
    assert _bs_delta(S, K, T, 0.3, R, Q, False) < 0


def test_price_is_increasing_in_vol():
    prev = -1.0
    for vol in (0.05, 0.10, 0.20, 0.40, 0.80):
        cur = _bs_price(S, K, T, vol, R, Q, True)
        assert cur > prev
        prev = cur


def test_zero_time_or_vol_falls_back_to_intrinsic():
    assert _bs_price(704.72, 700.0, 0.0, 0.3, R, Q, True) == pytest.approx(4.72)
    assert _bs_price(704.72, 750.0, 0.0, 0.3, R, Q, False) == pytest.approx(45.28)
    # 无内在价值的虚值期权归零，不能是负数
    assert _bs_price(704.72, 900.0, 0.0, 0.3, R, Q, True) == 0.0
    assert _bs_delta(S, K, 0.0, 0.3, R, Q, True) == 0.0


@pytest.mark.parametrize("is_call", [True, False])
@pytest.mark.parametrize("vol", [0.08, 0.20, 0.55])
def test_implied_vol_round_trip(vol, is_call):
    """定价 → 反解必须回到原波动率，call/put 两侧都要成立。"""
    mid = _bs_price(S, K, T, vol, R, Q, is_call)
    assert _implied_vol(mid, S, K, T, R, Q, is_call) == pytest.approx(vol, abs=1e-6)


def test_implied_vol_rejects_price_at_or_below_intrinsic():
    """报价 <= 内在价值 ⇒ 报价不可信，必须拒绝而不是硬解出一个数。"""
    assert _implied_vol(200.0, 900.0, 700.0, T, R, Q, True) is None


def test_implied_vol_rejects_absurd_price():
    assert _implied_vol(1e6, S, K, T, R, Q, True) is None


def test_implied_vol_rejects_result_above_band():
    """上界定为 120%：低波动宽基 ETF 反解出 >120% 只能是报价陈旧。"""
    mid = _bs_price(S, K, T, 1.5, R, Q, True)
    assert _implied_vol(mid, S, K, T, R, Q, True) is None


def test_implied_vol_rejects_result_below_band():
    mid = _bs_price(S, K, T, 0.005, R, Q, True)
    assert _implied_vol(mid, S, K, T, R, Q, True) is None
