"""wb_analysis/_thresholds.py 的测试 —— 时段判据与跨工具阈值。

这个模块的立身之本就是「同一个判据不许写在多处」，所以测试重点在**边界**：
开盘 09:30 / 收盘 16:00 是「含起点不含终点」，换季（EDT↔EST）不能错一小时。

时钟可注入（`now=` 参数）是后来才补的 —— 在那之前期权时点分支根本无法被测试，
所以这里把每个分支都钉住。
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from wb_analysis import _thresholds as th

ET = ZoneInfo("America/New_York")


def _et(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=ET)


# ── 时段边界（含起点不含终点）────────────────────────────────────────────

@pytest.mark.parametrize("t,expected", [
    (_et(2026, 10, 22, 3, 0), "pre_market"),
    (_et(2026, 10, 22, 9, 29), "pre_market"),
    (_et(2026, 10, 22, 9, 30), "in_session"),      # 开盘含起点
    (_et(2026, 10, 22, 12, 0), "in_session"),
    (_et(2026, 10, 22, 15, 59), "in_session"),
    (_et(2026, 10, 22, 16, 0), "after_hours"),     # 收盘不含终点
    (_et(2026, 10, 22, 23, 30), "after_hours"),
])
def test_session_phase_boundaries(t, expected):
    assert th.market_session_phase(t) == expected


def test_weekend_is_closed_day():
    assert th.market_session_phase(_et(2026, 10, 24, 12)) == "closed_day"   # 周六
    assert th.market_session_phase(_et(2026, 10, 25, 12)) == "closed_day"   # 周日


def test_naive_datetime_is_read_as_eastern_not_utc():
    """裸 datetime 一律按美东解释；若误当 UTC，会整体错 4~5 小时。"""
    assert th.market_session_phase(dt.datetime(2026, 10, 22, 12, 0)) == "in_session"


def test_aware_datetime_is_converted_to_eastern():
    """UTC 15:00 = 美东 11:00（EDT）⇒ 盘中。"""
    utc = dt.datetime(2026, 10, 22, 15, 0, tzinfo=dt.timezone.utc)
    assert th.market_session_phase(utc) == "in_session"


def test_winter_utc_offset_is_not_hardcoded():
    """冬季 EST = UTC−5。若有人硬编码 UTC−4，下面第二条就会误判成盘中。"""
    # 14:45 UTC = 09:45 美东 ⇒ 盘中
    assert th.market_session_phase(
        dt.datetime(2026, 12, 15, 14, 45, tzinfo=dt.timezone.utc)) == "in_session"
    # 14:00 UTC = 09:00 美东 ⇒ 盘前（按 UTC−4 会算成 10:00 而误判）
    assert th.market_session_phase(
        dt.datetime(2026, 12, 15, 14, 0, tzinfo=dt.timezone.utc)) == "pre_market"


# ── 期权源选择 ────────────────────────────────────────────────────────────

def test_option_source_in_session_uses_yfinance():
    use_cboe, note = th.option_source_decision(_et(2026, 10, 22, 11))
    assert use_cboe is False
    assert "yfinance" in note


@pytest.mark.parametrize("t,label", [
    (_et(2026, 10, 22, 8), "盘前"),
    (_et(2026, 10, 22, 20), "盘后"),
    (_et(2026, 10, 24, 12), "非交易日"),
])
def test_option_source_off_session_switches_to_cboe(t, label):
    use_cboe, note = th.option_source_decision(t)
    assert use_cboe is True
    assert "CBOE" in note
    assert label in note
    assert "上一时段收盘快照" in note, "必须声明拿到的不是实时报价"


def test_option_source_note_carries_the_injected_time():
    _use, note = th.option_source_decision(_et(2026, 10, 22, 11, 5))
    assert "2026-10-22 11:05" in note


# ── 已知缺口：工作日休市日 ────────────────────────────────────────────────

def test_weekday_market_holiday_is_closed_day():
    """美股公休日（2024–2027）在工作日必须返回 closed_day，防止切到盘中 yfinance 主源。"""
    thanksgiving = _et(2026, 11, 26, 11)          # 周四，美股休市
    assert th.market_session_phase(thanksgiving) == "closed_day"
    good_friday = _et(2025, 4, 18, 10)           # 周五，耶稣受难日
    assert th.market_session_phase(good_friday) == "closed_day"
    christmas_observed = _et(2027, 12, 24, 14)   # 周五，圣诞观察日（25日周六前移）
    assert th.market_session_phase(christmas_observed) == "closed_day"


def test_us_market_holidays_contains_expected_anchors():
    """锁定 2024–2027 公休日覆盖率与规则。"""
    assert len(th.US_MARKET_HOLIDAYS) == 40
    assert "2024-03-29" in th.US_MARKET_HOLIDAYS  # Good Friday 2024
    assert "2025-04-18" in th.US_MARKET_HOLIDAYS  # Good Friday 2025
    assert "2026-07-03" in th.US_MARKET_HOLIDAYS  # 独立日前移
    assert "2027-07-05" in th.US_MARKET_HOLIDAYS  # 独立日后移



# ── 跨工具阈值 ────────────────────────────────────────────────────────────

def test_shared_thresholds_keep_their_documented_values():
    """这些值改动会让采集器、探针、缺口审计器**同时**换口径 —— 不是随手调的常数。"""
    assert th.MAX_QUOTE_AGE_DAYS == 5.0
    assert th.HUMP_MIN_PP == 2.0
    assert th.MARKET_TZ_NAME == "America/New_York"
    assert th.REGULAR_SESSION_OPEN_HOUR == 9.5
    assert th.REGULAR_SESSION_CLOSE_HOUR == 16.0
    assert th.REGULAR_SESSION_OPEN_HOUR < th.REGULAR_SESSION_CLOSE_HOUR
