# lifecycle: test
"""期权数据源回归测试 —— 锁住「非盘中自动切 CBOE、盘中不切」这条时点分支。

## 为什么必须测它

期权维度是本项目里**唯一按时间走两条互斥路径**的通道：

  · 美东 09:30–16:00 盘中 → yfinance 主源（实时，`lastTradeDate` 距今 0.0 天）
  · 其余时段（盘前/盘后/非交易日）→ CBOE 官方延迟报价（**上一时段收盘快照**）

而 yfinance 在非盘中只返回**上一交易日的残留挂单** —— `bid`/`ask` 格式完全合法、
`ask >= bid` 也成立，**只有 `lastTradeDate` 是陈旧的**。实测（NDX 2026-10-16 轮，
美东 08:29 盘前）：扫 29 个到期日、387 个有双边报价的合约，**最新成交距今 23.2 天、
合格样本 0** ⇒ IV 等级 NONE ⇒ 期权维度整体不可用，结论被迫降级为条件式。

⇒ 这条分支的失效形态是**静默的**：拿到的仍是「合法格式的期权链」，只是数据陈旧。
   不测它，就等于把「盘前采到垃圾」当成「采到了数据」。

## 测试策略

**全部离线**（`pytest.mark.unit`）：时点判定是纯函数，用**注入时钟**覆盖边界；
CBOE 解析用**构造的 JSON** 覆盖形状，不发真实请求。
真实网络只保留一个 `integration` 用例（默认不被基线跑，需显式 `-m integration`）。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._thresholds import (  # noqa: E402
    MARKET_TZ_NAME,
    REGULAR_SESSION_CLOSE_HOUR,
    REGULAR_SESSION_OPEN_HOUR,
    market_session_phase,
    option_source_decision,
)

ET = ZoneInfo(MARKET_TZ_NAME)


def _at(y, mo, d, hh, mm):
    """构造美东时点（用 IANA 名字，不用 UTC 偏移量 —— 换季时会静默错一小时）。"""
    return dt.datetime(y, mo, d, hh, mm, tzinfo=ET)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 时段边界（这是整条分支的判据基座）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSessionPhaseBoundaries:
    """边界必须**含起点、不含终点**：09:30 属盘中，16:00 属盘后。

    两端任一处闭区间化，都会造成静默错配：
      · 把 09:30 判成盘前 ⇒ 明明有实时数据却去取昨日快照（丢实时性）
      · 把 16:00 判成盘中 ⇒ 取到残留挂单（**拿到的是垃圾却以为拿到了数据**）
    """

    @pytest.mark.parametrize("hour, minute, expected", [
        (0, 0, "pre_market"),
        (4, 0, "pre_market"),
        (8, 29, "pre_market"),        # NDX 实测的盘前采集时点
        (9, 29, "pre_market"),        # 开盘前一分钟
        (9, 30, "in_session"),        # ★ 边界：含起点
        (12, 0, "in_session"),
        (15, 59, "in_session"),       # 收盘前一分钟
        (16, 0, "after_hours"),       # ★ 边界：不含终点
        (18, 0, "after_hours"),
        (23, 59, "after_hours"),
    ])
    def test_weekday_boundaries(self, hour, minute, expected):
        # 2026-10-16 是周五
        assert market_session_phase(_at(2026, 10, 16, hour, minute)) == expected

    @pytest.mark.parametrize("day", [17, 18])          # 周六、周日
    @pytest.mark.parametrize("hour", [8, 12, 20])
    def test_weekend_is_closed_day(self, day, hour):
        assert market_session_phase(_at(2026, 10, day, hour, 0)) == "closed_day"

    def test_naive_datetime_interpreted_as_market_tz(self):
        """裸 datetime 按美东解释，不静默当 UTC（否则会错 4~5 小时）。"""
        naive = dt.datetime(2026, 10, 16, 12, 0)
        assert market_session_phase(naive) == "in_session"

    def test_non_market_tz_input_is_converted(self):
        """传入别的时区的 aware datetime，必须先换算到美东再判。"""
        # 美东 12:00 == UTC 16:00（10 月是夏令时 EDT = UTC−4）
        utc_noon_et = dt.datetime(2026, 10, 16, 16, 0, tzinfo=dt.timezone.utc)
        assert market_session_phase(utc_noon_et) == "in_session"

    def test_constants_are_the_documented_values(self):
        assert REGULAR_SESSION_OPEN_HOUR == 9.5
        assert REGULAR_SESSION_CLOSE_HOUR == 16.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. 源选择（时点 → 走哪个源）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOptionSourceDecision:
    """盘中不切、非盘中切 —— 且切换时的说明必须写明「快照非实时」。"""

    @pytest.mark.parametrize("hour, minute", [(9, 30), (12, 0), (15, 59)])
    def test_in_session_uses_primary_source(self, hour, minute):
        use_cboe, note = option_source_decision(_at(2026, 10, 16, hour, minute))
        assert use_cboe is False
        assert "yfinance 主源" in note

    @pytest.mark.parametrize("hour, minute, label", [
        (8, 29, "盘前"),
        (16, 0, "盘后"),
        (20, 0, "盘后"),
    ])
    def test_off_session_switches_to_cboe(self, hour, minute, label):
        use_cboe, note = option_source_decision(_at(2026, 10, 16, hour, minute))
        assert use_cboe is True
        assert "CBOE" in note
        assert label in note

    def test_closed_day_switches_to_cboe(self):
        use_cboe, note = option_source_decision(_at(2026, 10, 17, 12, 0))
        assert use_cboe is True
        assert "非交易日" in note

    @pytest.mark.parametrize("hour, minute", [(8, 29), (16, 0), (20, 0)])
    def test_switch_note_must_declare_snapshot_not_realtime(self, hour, minute):
        """⚠️ 最关键的一条：说明里必须写明「上一时段收盘快照 / 非实时报价」。

        否则下游会把这个读数当「此刻的实时 IV」用 —— 这正是铁律 1 与铁律 36
        反复踩过的坑（期权信号会被采集时点反向改写）。
        """
        _use, note = option_source_decision(_at(2026, 10, 16, hour, minute))
        assert "上一时段收盘快照" in note
        assert "非实时报价" in note

    def test_decision_is_pure_wrt_injected_clock(self):
        """同一时点反复调用必须给出同一结论（不得依赖真实 now）。"""
        t = _at(2026, 10, 16, 8, 29)
        assert option_source_decision(t) == option_source_decision(t)


# ─────────────────────────────────────────────────────────────────────────────
# 3. CBOE 适配器（离线：构造 JSON，不发请求）
# ─────────────────────────────────────────────────────────────────────────────

SYNTH_CHAIN = {
    "data": {
        "current_price": 70.79,
        "iv30": 46.15,
        "last_trade_time": "2026-10-16T12:54:22",
        "options": [
            # 格式：<ROOT><YYMMDD><C|P><strike*1000 补零 8 位>
            {"option": "NFLX261030C00072000", "bid": 3.00, "ask": 3.10,
             "iv": 0.6182, "delta": 0.51, "open_interest": 1200, "volume": 88,
             "last_trade_price": 3.05, "last_trade_time": "2026-10-16T11:12:08"},
            {"option": "NFLX261030P00072000", "bid": 2.80, "ask": 2.95,
             "iv": 0.6301, "delta": -0.49, "open_interest": 900, "volume": 41,
             "last_trade_price": 2.87, "last_trade_time": "2026-10-16T10:03:00"},
            {"option": "NFLX261106C00075000", "bid": 0.0, "ask": 0.0,
             "iv": 0.0, "delta": 0.0, "open_interest": 0, "volume": 0,
             "last_trade_price": 0.0, "last_trade_time": "2026-09-01T10:00:00"},
        ],
    }
}


@pytest.mark.unit
class TestCboeSymbolParsing:
    """CBOE 内部符号解析 —— 解析不出必须返回 None（**不猜**）。"""

    def test_parses_call_and_put(self):
        from wb_analysis._option_source import parse_osym
        c = parse_osym("NFLX261030C00072000")
        assert c == {"root": "NFLX", "expiry": "2026-10-30", "cp": "C", "strike": 72.0}
        p = parse_osym("NFLX261030P00072000")
        assert p["cp"] == "P" and p["strike"] == 72.0

    @pytest.mark.parametrize("bad", [
        "", "NFLX", "NFLX261030X00072000", "NFLX261030C72", "NOTASYMBOL123",
    ])
    def test_unparsable_returns_none(self, bad):
        from wb_analysis._option_source import parse_osym
        assert parse_osym(bad) is None


@pytest.mark.unit
class TestCboeChainShape:
    """适配体必须与 yfinance 的 Options 同形（上游过滤逻辑直接消费这三个成员）。"""

    @pytest.fixture()
    def chain(self):
        from wb_analysis._option_source import CboeChain
        return CboeChain(symbol="NFLX", raw=SYNTH_CHAIN)

    def test_options_lists_expiries_sorted(self, chain):
        assert chain.options == ("2026-10-30", "2026-11-06")

    def test_spot_and_iv30_exposed(self, chain):
        assert chain.spot == pytest.approx(70.79)
        assert chain.iv30 == pytest.approx(46.15)

    def test_option_chain_returns_calls_and_puts(self, chain):
        ch = chain.option_chain("2026-10-30")
        assert len(ch.calls) == 1 and len(ch.puts) == 1
        assert ch.calls.iloc[0]["strike"] == 72.0

    def test_unknown_expiry_returns_empty_not_raise(self, chain):
        """未知到期日返回空表而不是抛异常 —— 上游按「扫全部到期日」遍历。"""
        ch = chain.option_chain("2099-01-01")
        assert len(ch.calls) == 0 and len(ch.puts) == 0

    def test_source_label_is_declared(self, chain):
        """来源标签必须可被下游读出来声明（口径不同不可混用）。"""
        assert chain.source == "cboe_delayed"

    def test_row_carries_both_last_trade_keys(self, chain):
        """yfinance 用 lastTradeDate、CBOE 用 last_trade_time ⇒ 两个键都要给。"""
        row = chain.option_chain("2026-10-30").calls.iloc[0]
        assert row["lastTradeDate"] == "2026-10-16T11:12:08"
        assert row["last_trade_time"] == "2026-10-16T11:12:08"

    def test_mid_computed_only_when_both_sides_quoted(self, chain):
        calls = chain.option_chain("2026-10-30").calls
        no_quote = chain.option_chain("2026-11-06").calls
        assert calls.iloc[0]["mid"] == pytest.approx(3.05)
        # bid/ask 归零的合约不得算出 mid（否则「IV>0」这类过滤会形同虚设）
        assert no_quote.iloc[0]["mid"] is None


@pytest.mark.unit
class TestCboeErrorSemantics:
    """取数失败必须抛错（**不返回空 dict**），调用方据此走「登记缺口」而不是当成功。"""

    def test_http_4xx_raises_without_retrying(self, monkeypatch):
        import urllib.error

        from wb_analysis import _option_source as osrc

        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, None)

        monkeypatch.setattr(osrc.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(osrc.OptionSourceError):
            osrc.fetch_chain("NDX")
        # 4xx 是「该标的无期权」（指数/A股ETF）⇒ 重试无意义
        assert calls["n"] == 1

    def test_transient_errors_are_retried_then_raise(self, monkeypatch):
        from wb_analysis import _option_source as osrc

        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            raise ConnectionResetError("boom")

        monkeypatch.setattr(osrc.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(osrc.time, "sleep", lambda *_: None)
        with pytest.raises(osrc.OptionSourceError):
            osrc.fetch_chain("NFLX")
        assert calls["n"] == osrc.MAX_TRIES      # 实测确有偶发连接失败 ⇒ 必须重试

    def test_available_returns_false_not_raise(self, monkeypatch):
        """`available()` 是前置判断，必须吞掉异常返回 False。"""
        import urllib.error

        from wb_analysis import _option_source as osrc

        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, None)

        monkeypatch.setattr(osrc.urllib.request, "urlopen", fake_urlopen)
        assert osrc.available("512400.SS") is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. 单一来源约束（判据不得在消费方本地重写）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSingleSourceOfTruth:
    """时段判据只在 `_thresholds.py` 定义一次；消费方只许转发。"""

    def test_collect_index_forwards_to_thresholds(self):
        src = (ROOT / "wb_analysis" / "collect_index.py").read_text(encoding="utf-8")
        assert "from wb_analysis._thresholds import option_source_decision" in src

    def test_collect_index_has_no_hardcoded_session_bounds(self):
        """消费方不得再写 `9.5 <= h` / `h < 16.0` 这类字面量边界（**注释留痕豁免**）。

        为什么豁免注释：本项目允许用注释记录「这里曾写死过 X，已收敛到 Y」——
        那是防止漂移复发的重要留痕（`_selftest.py` 的布局常量检测器用同一原则：
        「手抄值必检出 / 派生与注释留痕不误报」）。**只检查真正的代码 token**。
        """
        import io
        import tokenize

        src = (ROOT / "wb_analysis" / "collect_index.py").read_text(encoding="utf-8")
        # 只保留代码 token：剔除注释与字符串字面量（后者含文档化的格式说明）
        code_parts = []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            code_parts.append(tok.string)
        code = " ".join(code_parts)

        for literal in ("9.5", "16.0"):
            assert literal not in code, (
                f"时段边界字面量 `{literal}` 泄漏进消费方代码 —— "
                f"应改用 `_thresholds.REGULAR_SESSION_OPEN_HOUR/CLOSE_HOUR` 或 "
                f"`market_session_phase()`"
            )

    def test_gap_ledger_registers_the_fallback_category(self):
        """台账必须认得这条通道，否则下游看不见「昨日快照」这件事。"""
        from wb_analysis._gap_ledger import RULES
        rule = RULES.get("CBOE_fallback_used")
        assert rule is not None
        assert rule["cls"] == "B"          # 口径位移，非上游真缺（A）也非阈值误伤
        assert rule["decisive"] is True    # 挡掉「此刻/盘中」类论断
        assert "快照" in rule["blocks"]


@pytest.mark.unit
class TestSourceDeclarationHonesty:
    """`source` 必须反映**实际用了哪个源**，而不是「打算用哪个源」。

    ## 为什么单独测这一条（2026-10-17 实测发现的 bug）

    `use_cboe` 是**纯时间判据**（盘前/盘后即 True），而 CBOE 也可能取数失败
    （403 / 网络失败 ⇒ 退回 yfinance）。修复前 `source` 只看 `use_cboe`：

      · 盘前 + CBOE 403 + 退回 yfinance ⇒ `source` 仍写 `"cboe_delayed"`
      · `freshness.source` 也写 `"cboe_delayed"`，并声称「已切 CBOE 源，跳过探测」

    ⇒ **实际用的是 yfinance 的数据，却对外声明成 CBOE 口径。**
    证据包会据此打印「数据来源：CBOE 官方延迟报价」+「本源的 iv/delta 由交易所模型给出」，
    而数值其实来自项目自建 BSM 反解 —— 两个口径的偏斜差异实测可达数 pp。
    **声明错了比不声明更危险**：它会让下游以为拿到了独立第二信源。
    """

    def test_resolve_source_note_marks_fallback(self):
        from wb_analysis.collect_index import _resolve_source_note

        base = "2026-10-16 08:29 美东（盘前）⇒ 切 CBOE 官方延迟报价"

        # 盘中：原样返回
        assert _resolve_source_note(False, False, base) == base

        # 盘前且 CBOE 成功：原样返回（说明里已含「快照非实时」）
        assert _resolve_source_note(True, True, base) == base

        # 盘前但 CBOE 失败：必须显式写出降级
        out = _resolve_source_note(True, False, base)
        assert "回退 yfinance 主源" in out
        assert out.startswith(base)

    def test_source_field_driven_by_actual_success(self):
        """源码层面：`source` 字段由 `cboe_ok`（实际成功）驱动，不是 `use_cboe`（时间判据）。"""
        src = (ROOT / "wb_analysis" / "collect_index.py").read_text(encoding="utf-8")
        assert '"cboe_delayed" if cboe_ok else "yfinance"' in src
        assert '"cboe_delayed" if use_cboe else "yfinance"' not in src

    def test_freshness_block_also_gated_on_success(self):
        """`freshness` 块同样要按实际成功与否分流，并在降级时留痕。"""
        src = (ROOT / "wb_analysis" / "collect_index.py").read_text(encoding="utf-8")
        assert "if cboe_ok:" in src
        assert "cboe_fallback_failed" in src


# ─────────────────────────────────────────────────────────────────────────────
# 5. 真实网络（默认不跑：`pytest -m integration`）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_live_cboe_returns_usable_chain():
    """真实拉一次 CBOE，确认端点仍可用且形状未变。

    标记为 integration ⇒ **不进回归基线**（基线要求离线可重复）。
    运行：`./.venv/Scripts/python.exe -m pytest tests/test_option_source.py -m integration`
    """
    from wb_analysis._option_source import OptionSourceError, fetch_chain

    try:
        chain = fetch_chain("NFLX")
    except OptionSourceError as exc:      # 网络不可用时不判失败（环境问题，非代码问题）
        pytest.skip(f"CBOE 端点不可达：{exc}")

    assert len(chain.options) > 0
    assert chain.spot is not None and chain.spot > 0
