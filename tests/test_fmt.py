"""`wb_analysis/_fmt.py` 的单元测试（纯函数，零网络、零文件 IO）。

覆盖三类契约：
1. **解析/格式化**：`fnum` / `pct_str` / `ystr` 的容错边界（缺失必须可识别，不能静默变 0）；
2. **代码规范化**：`wcode_of` 是两份旧实现的**并集** —— 尤其 `518880` 这类无后缀代码
   必须补 `sh`（2026-10-21 那次「全部通道 service error 却报 14/14」的成因）；
3. **序列压缩**：降序取最新 N 个 + 可选的未收盘 bar 剔除（仅在传 `tz` 时生效）。
"""
from __future__ import annotations

import datetime as dt

import pytest

from wb_analysis import _clock
from wb_analysis._fmt import compact_series, fnum, pct_str, wcode_of, ystr

ET = _clock.MARKET_TZ


@pytest.mark.unit
class TestFnum:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1,234.5", 1234.5),
            ("+12.30%", 12.30),
            ("  -3.5 ", -3.5),
            ("0", 0.0),
            (7, 7.0),
            (None, None),
            ("", None),
            ("—", None),
            ("1.424 (偏离度: +0.56%)", None),  # 整串转 float：带说明文字必须失败
        ],
    )
    def test_strict_parse(self, raw, expected):
        assert fnum(raw) == expected

    def test_default_is_returned_not_zero(self):
        # 关键契约：取不到就是 default，绝不静默变 0（否则会污染均值/分位）
        assert fnum("N/A", default=None) is None
        assert fnum("N/A", default=-1) == -1


@pytest.mark.unit
class TestPctStr:
    def test_signed_and_digits(self):
        assert pct_str(1.234) == "+1.23%"
        assert pct_str(-1.234) == "-1.23%"
        assert pct_str(1.2345, digits=1) == "+1.2%"

    def test_missing_renders_dash_not_zero(self):
        assert pct_str(None) == "—"
        assert pct_str("abc") == "—"


@pytest.mark.unit
class TestYstr:
    def test_scale_to_yi(self):
        assert ystr(123_450_000) == "1.23 亿元"

    def test_sign_and_unit(self):
        assert ystr(123_450_000, sign=True) == "+1.23 亿元"
        assert ystr(1_000_000, scale=1e4, unit="万元") == "100.00 万元"

    def test_missing_is_explicit(self):
        # 「（未取到）」是给人看的显式缺失标记，不是空串
        assert ystr(None) == "（未取到）"
        assert ystr("—") == "（未取到）"


@pytest.mark.unit
class TestWcodeOf:
    @pytest.mark.parametrize(
        "ticker,expected",
        [
            ("518880", "sh518880"),      # 旧个股版缺陷：原样返回 → westock 全通道报错
            ("512400.SS", "sh512400"),
            ("159915.SZ", "sz159915"),
            ("600519.SH", "sh600519"),
            ("600519.ss", "sh600519"),
            ("000001", "sz000001"),
            ("301001", "sz301001"),
            ("688981", "sh688981"),
            ("920001", "sh920001"),      # 9 开头按上交所
            ("sh600519", "sh600519"),    # 已带前缀：幂等
            ("SZ000001", "sz000001"),
            ("AAPL", "aapl"),            # 无法判定：小写原样（交给上游报错，不臆造）
        ],
    )
    def test_union_of_both_legacy_impls(self, ticker, expected):
        assert wcode_of(ticker) == expected

    def test_idempotent(self):
        for t in ("518880", "512400.SS", "sz000001"):
            assert wcode_of(wcode_of(t)) == wcode_of(t)


@pytest.mark.unit
class TestCompactSeries:
    RAW = (
        "## close_50_sma values from 2026-10-15 to 2026-10-22:\n\n"
        "2026-10-22: 104.0\n"
        "2026-10-20: 102.0\n"
        "2026-10-18: 100.0\n"
        "N/A: Not a trading day (weekend or holiday)\n"
        "\n50 SMA: A medium-term trend indicator.\n"
    )

    def test_sorted_desc_and_keeps_latest_n(self):
        # 顺序陷阱：输入已是「新→旧」，仍必须按日期显式降序取前 keep
        assert compact_series(self.RAW, keep=2) == "2026-10-22: 104.0\n2026-10-20: 102.0"

    def test_unsorted_input_is_normalized(self):
        raw = "2026-10-18: 100.0\n2026-10-22: 104.0\n2026-10-20: 102.0\n"
        assert compact_series(raw, keep=2) == "2026-10-22: 104.0\n2026-10-20: 102.0"

    def test_empty_and_no_valid_rows(self):
        assert compact_series("") == "(无数据)"
        assert compact_series(None) == "(无数据)"
        assert compact_series("N/A: Not a trading day\n50 SMA: 说明文字") == "(无有效值)"

    def test_no_tz_means_no_unsettled_bar_drop(self):
        # A股调用方目前走这条路径：只压缩、不剔除（保持证据包逐字不变）
        assert "104.0" in compact_series(self.RAW, keep=3)

    def test_drops_unsettled_bar_before_close(self, monkeypatch):
        # 美东 10:00（未收盘）⇒ 2026-10-22 那根是盘中瞬时值，必须剔除并留痕
        monkeypatch.setattr(
            _clock, "now",
            lambda tz=ET: dt.datetime(2026, 10, 22, 10, 0, tzinfo=ET),
        )
        out = compact_series(self.RAW, keep=3, tz=ET, close_hour=16.0, tz_label="美东")
        assert "2026-10-22" not in out.split("⚠")[0]
        assert "2026-10-20: 102.0" in out
        assert "⚠ 已剔除未收盘 bar（2026-10-22，美东尚未收盘）" in out

    def test_keeps_latest_bar_after_close(self, monkeypatch):
        monkeypatch.setattr(
            _clock, "now",
            lambda tz=ET: dt.datetime(2026, 10, 22, 17, 0, tzinfo=ET),
        )
        out = compact_series(self.RAW, keep=3, tz=ET, close_hour=16.0)
        assert out.startswith("2026-10-22: 104.0")
        assert "⚠" not in out

    def test_clock_failure_degrades_to_plain_compaction(self, monkeypatch):
        def boom(tz=ET):
            raise RuntimeError("clock down")

        monkeypatch.setattr(_clock, "now", boom)
        # 时钟异常不得让证据包整体失败（log_gap 留痕后按纯压缩返回）
        assert compact_series(self.RAW, keep=2, tz=ET, close_hour=16.0).startswith("2026-10-22")


@pytest.mark.unit
class TestIndicatorHealth:
    """指标通道「有正文、无数据」必须降级（2026-10-23 假绿修复）。

    实测：GOOG 2026-10-23 的 `close_50_sma` 整段 `(无有效值)`（bulk 计算瞬时失败后
    静默降级到 per-day），而 health 仍记 ok、健康度照报 36/36。
    """

    @pytest.mark.parametrize("compact", ["(无有效值)", "(无数据)"])
    def test_empty_series_downgrades_ok_to_unavailable(self, compact):
        from wb_analysis.collect import _indicator_health

        assert _indicator_health("ok", compact) == "unavailable"

    def test_non_empty_series_keeps_status(self):
        from wb_analysis.collect import _indicator_health

        assert _indicator_health("ok", "2026-10-22: 339.13") == "ok"

    def test_existing_failures_are_not_upgraded(self):
        from wb_analysis.collect import _indicator_health

        # 已经是 fail/unavailable 的不得被"修"成别的状态
        assert _indicator_health("fail", "(无有效值)") == "fail"
        assert _indicator_health("unavailable", "(无数据)") == "unavailable"
