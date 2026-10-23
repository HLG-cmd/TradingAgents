"""wb_analysis 核心模块（collect / assemble / _derive_stock）纯函数的离线单元测试。

针对无需联网的核心数据清洗、快照自洽校验、未收盘 bar 判定与报告树组装逻辑建立回归覆盖。
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from wb_analysis import _clock, _derive_stock, assemble, collect


@pytest.mark.unit
class TestCollectPureFunctions:
    """wb_analysis/collect.py 纯函数测试（零网络）。"""

    def test_compact_series_sorts_descending_and_keeps_top_n(self, monkeypatch):
        # 固定时钟为已收盘时点，验证无论输入升序还是降序，均按日期降序保留最新 keep 条
        monkeypatch.setattr(
            _clock,
            "now",
            lambda tz=_clock.MARKET_TZ: dt.datetime(2026, 10, 22, 18, 0, tzinfo=_clock.MARKET_TZ),
        )
        raw = (
            "## close_50_sma values\n"
            "2026-10-18: 100.0\n"
            "2026-10-22: 104.0\n"
            "2026-10-20: 102.0\n"
            "2026-10-21: 103.0\n"
            "Tail explanation line\n"
        )
        out = collect._compact_series(raw, keep=3)
        lines = out.splitlines()
        assert lines == [
            "2026-10-22: 104.0",
            "2026-10-21: 103.0",
            "2026-10-20: 102.0",
        ]

    def test_compact_series_drops_unclosed_intraday_bar(self, monkeypatch):
        # 盘中 11:00 ET：末根日期 == 美东今日 ⇒ 自动剔除并附带提示
        monkeypatch.setattr(
            _clock,
            "now",
            lambda tz=_clock.MARKET_TZ: dt.datetime(2026, 10, 22, 11, 0, tzinfo=_clock.MARKET_TZ),
        )
        raw = "2026-10-22: 52.30\n2026-10-21: 44.02\n2026-10-20: 43.10\n"
        out = collect._compact_series(raw, keep=2)
        assert "2026-10-22: 52.30" not in out
        assert "2026-10-21: 44.02" in out
        assert "已剔除未收盘 bar（2026-10-22" in out

    def test_session_in_progress_respects_1600_boundary(self, monkeypatch):
        monkeypatch.setattr(
            _clock,
            "now",
            lambda tz=_clock.MARKET_TZ: dt.datetime(2026, 10, 22, 15, 59, tzinfo=_clock.MARKET_TZ),
        )
        assert collect._session_in_progress("2026-10-22") is True
        assert collect._session_in_progress("2026-10-21") is False

        monkeypatch.setattr(
            _clock,
            "now",
            lambda tz=_clock.MARKET_TZ: dt.datetime(2026, 10, 22, 16, 0, tzinfo=_clock.MARKET_TZ),
        )
        assert collect._session_in_progress("2026-10-22") is False

    def test_fundamentals_sanity_flags_currency_mismatch_and_de_unit(self):
        snap = (
            "Currency: USD\n"
            "Financial Currency: KRW\n"
            "Debt to Equity: 18.859\n"
            "PE Ratio (TTM): 20.0\n"
            "EPS (TTM): 5.0\n"
        )
        warn = collect._fundamentals_sanity(snap)
        assert "币种不一致" in warn
        assert "单位陷阱" in warn
        assert "隐含股价校验：PE(TTM) 20.0 × EPS(TTM) 5.0 = 100.00" in warn

    def test_compact_statement_prioritizes_key_rows_and_declares_truncation(self):
        rows = ["# Income Statement", ""] + [f"Row_{i},100,90" for i in range(15)]
        raw = "\n".join(rows)
        out = collect._compact_statement(raw, "income", max_rows=5)
        assert "[TRUNCATED: 本节另有 10 行未显示" in out

    def test_compact_macro_keeps_most_recent_observations(self):
        header = "# CPI\n**Latest:** 300.5\n| Date | Value |\n|---|---|\n"
        body = "\n".join(f"| 2026-01-{i:02d} | {100 + i} |" for i in range(1, 11))
        out = collect._compact_macro(header + body, keep_obs=3)
        assert "2026-01-10" in out
        assert "2026-01-01" not in out
        assert "省略较早的 7 行" in out


@pytest.mark.unit
class TestAssembleAndDeriveStockPure:
    """wb_analysis/assemble.py 与 _derive_stock.py 纯函数测试。"""

    def test_safe_component_sanitizes_ticker(self):
        assert assemble._safe_component("BRK/B") == "BRK_B"
        assert assemble._safe_component("   ") == "UNKNOWN"

    def test_load_from_dir_strict_requires_meta_json(self, tmp_path):
        with pytest.raises(assemble.MetaMissingError, match="缺少 meta.json"):
            assemble.load_from_dir(tmp_path, strict=True)

    def test_load_from_dir_reads_valid_draft_dir(self, tmp_path):
        (tmp_path / "1_analysts").mkdir()
        (tmp_path / "1_analysts" / "market.md").write_text("# Market\nOK", encoding="utf-8")
        meta = {
            "ticker": "NVDA",
            "as_of": "2026-10-22",
            "ratings": {
                "research_manager": "Buy",
                "trader_action": "Buy",
                "portfolio_manager": "Buy",
            },
        }
        (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        data = assemble.load_from_dir(tmp_path, strict=True)
        assert data["ticker"] == "NVDA"
        assert data["analysts"]["market"] == "# Market\nOK"

    def test_derive_stock_parse_bars_extracts_ohlcv_tuples(self):
        md = (
            "Header text\n"
            "2026-10-21  100.00  105.00   99.50  104.25  1234567\n"
            "2026-10-22  104.50  108.00  103.00  107.50  2345678\n"
        )
        bars = _derive_stock.parse_bars(md)
        assert len(bars) == 2
        assert bars[1] == ("2026-10-22", 104.5, 108.0, 103.0, 107.5, 2345678)


class TestSnapshotConsistencyLayout:
    """§3 版式双边回归（2026-10-24）：标题与围栏之间的引用块不得令检测静默失效。

    旧正则要求围栏紧跟标题；collect.py 加入「口径提示」引用块后，快照解析返回空，
    币种/forward 两项检测全部静默失效（铁律 32：「检测器看着在工作，其实什么也没检」）。
    """

    @staticmethod
    def _write_evidence(tmp_path, snapshot_body, with_blockquote=True):
        ev = tmp_path / "TST_2026-10-24.md"
        note = "\n> **口径提示**：引用块版式回归。\n" if with_blockquote else ""
        ev.write_text(
            "## 1. 行情与价格结构\n\n```\nlatest_close: 100.0\n```\n\n"
            "## 3. 基本面快照\n" + note + "\n```\n" + snapshot_body + "\n```\n",
            encoding="utf-8",
        )
        return ev

    def test_currency_and_forward_flagged_with_blockquote_layout(self, tmp_path):
        from wb_analysis import _verify_snapshot_consistency as vsc

        ev = self._write_evidence(
            tmp_path,
            "Currency: USD\nFinancial Currency: KRW\nEPS (TTM): 10.0\nForward EPS: 20.0\n",
        )
        labels = {f["label"] for f in vsc.check("TST", "2026-10-24", ev_path=ev)}
        assert "currency_mismatch" in labels
        assert "forward_eps" in labels

    def test_clean_snapshot_not_flagged_with_blockquote_layout(self, tmp_path):
        from wb_analysis import _verify_snapshot_consistency as vsc

        ev = self._write_evidence(
            tmp_path,
            "Currency: USD\nFinancial Currency: USD\nEPS (TTM): 10.0\nForward EPS: 11.0\n",
        )
        assert vsc.check("TST", "2026-10-24", ev_path=ev) == []

    def test_legacy_layout_without_blockquote_still_parses(self, tmp_path):
        from wb_analysis import _verify_snapshot_consistency as vsc

        ev = self._write_evidence(
            tmp_path,
            "Currency: USD\nFinancial Currency: KRW\n",
            with_blockquote=False,
        )
        labels = {f["label"] for f in vsc.check("TST", "2026-10-24", ev_path=ev)}
        assert "currency_mismatch" in labels
