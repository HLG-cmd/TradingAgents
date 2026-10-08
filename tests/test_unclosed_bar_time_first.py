"""未收盘 bar 的剔除必须「时点优先」，不能让量比喧宾夺主（铁律 2）。

2026-09-30 事故（本测试的由来）
------------------------------
同一交易日内对 GOOG 做了两次采集，末根 bar 都是 2026-09-30：

    11:16 ET  量比 40.3%  → 旧判据剔除 ✓（碰巧对）
    13:32 ET  量比 60.3%  → 旧判据**不剔除** ✗（距 16:00 收盘还有 2.5 小时）

旧判据是 `ratio < 0.60 AND _session_in_progress(...)`：把**量比（数值）**放在了
主判据位置，时点只是附加条件。于是盘中晚段量一累积到 60% 以上，半截 K 线就被
当成收盘 bar 写进证据包 —— 证据包甚至明写「日线序列最后一根有效 bar：
2026-09-30 收盘 346.96」，而 9-30 当时根本没收盘。

后果是最新收盘价、全部技术指标、以及所有以收盘价为分母的比率**同时被污染**，
且**外观完全正常**（命令成功、字段存在、数值合规）—— 典型静默失败（铁律 3）。
更隐蔽的是该 bug **只在盘中晚段触发**，早盘量比必然 <60% 反而表现"正常"。

正确判据：**时点是定义性问题，不是概率问题**。只要该 bar 所属交易日尚未走完
美东 16:00，它在定义上就不是一个完整交易日的观测，无论量比多高都必须剔除。

反向约束（2026-09-22 事故，同样不能回退）
----------------------------------------
指数通道（^NDX 等）的当日 Volume 字段不完整，实测仅为 20 日均量的 20.5%，
而实际是完整交易日。若改回「只看量比」，已收盘 bar 会被误剔，导致最新收盘价
缺失。故「交易日已结束 + 量比低」必须**不剔除**，只提示字段不完整。
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from wb_analysis import collect


def _csv(last_volume: int, base_volume: int = 1_000_000, n: int = 25) -> str:
    """构造 n 根日线，前 n-1 根成交量为 base_volume，末根为 last_volume。

    末根日期写成 2026-09-30（实际值不影响断言：_session_in_progress 被打桩）。
    """
    rows = ["Date,Open,High,Low,Close,Volume"]
    for i in range(n - 1):
        d = pd.Timestamp("2026-09-01") + pd.Timedelta(days=i)
        rows.append(f"{d.date()},100,101,99,100,{base_volume}")
    rows.append(f"2026-09-30,100,101,99,100,{last_volume}")
    return "\n".join(rows) + "\n"


@pytest.fixture
def patch_session(monkeypatch):
    """把 _session_in_progress 打桩成固定返回值，使测试与真实时钟解耦。"""

    def _install(in_progress: bool):
        monkeypatch.setattr(
            collect, "_session_in_progress", lambda bar_date: in_progress
        )

    return _install


def test_drops_in_session_bar_even_when_volume_looks_full(patch_session):
    """事故场景：盘中 13:32，量比 80%（已超 60% 阈值）⇒ 仍必须剔除。"""
    patch_session(True)
    text, stats = collect._price_summary(_csv(last_volume=800_000))

    assert stats.get("unclosed_bar_dropped") is True
    assert stats["unclosed_bar_date"] == "2026-09-30"
    assert stats["unclosed_drop_reason"] == "session_in_progress"
    assert "已剔除未收盘 bar" in text
    # 最新收盘必须回退到前一根（100.0），而不是那根半截 bar 的价
    assert stats["latest_close"] == 100.0
    assert stats["bars"] == 24


def test_drops_in_session_bar_with_thin_volume(patch_session):
    """传统场景：盘中早段，量比 40% ⇒ 剔除（旧判据也对，行为保持不变）。"""
    patch_session(True)
    text, stats = collect._price_summary(_csv(last_volume=400_000))

    assert stats.get("unclosed_bar_dropped") is True
    assert stats["bars"] == 24


def test_keeps_settled_bar_with_thin_volume(patch_session):
    """2026-09-22 反向约束：交易日已结束 + 量比 40% ⇒ 不剔除（指数尤甚）。"""
    patch_session(False)
    text, stats = collect._price_summary(_csv(last_volume=400_000))

    assert stats.get("unclosed_bar_dropped") is not True
    assert "已剔除未收盘 bar" not in text
    assert "已过完美东 16:00" in text or "均量的 40.0%" in text
    assert stats["bars"] == 25


def test_keeps_settled_bar_with_full_volume(patch_session):
    """交易日已结束 + 量比充足 ⇒ 不剔除，且不应有任何剔除提示。"""
    patch_session(False)
    text, stats = collect._price_summary(_csv(last_volume=1_200_000))

    assert stats.get("unclosed_bar_dropped") is not True
    assert "已剔除未收盘 bar" not in text
    assert stats["bars"] == 25


def test_in_session_drop_is_independent_of_volume(monkeypatch):
    """时点优先的核心：盘中时，剔除决策不得随量比变化而翻转。"""
    outcomes = set()
    for vol in (100_000, 400_000, 590_000, 610_000, 900_000, 1_500_000):
        monkeypatch.setattr(collect, "_session_in_progress", lambda d: True)
        _, stats = collect._price_summary(_csv(last_volume=vol))
        outcomes.add(bool(stats.get("unclosed_bar_dropped")))

    assert outcomes == {True}, "盘中时无论量比多少都必须剔除，决策不应翻转"
