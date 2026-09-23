import re
from datetime import date

# Tickers can contain letters, digits, dot, dash, underscore, caret
# (index symbols like ^GSPC), equals (futures like GC=F), and plus
# (forex/CFD symbols like XAUUSD+). None of these enable directory
# traversal, so the value never escapes a containing directory when
# interpolated into a path. Anything else is rejected.
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^=+]+$")


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Validate ``value`` is safe to interpolate into a filesystem path.

    Tickers come from user CLI input or from LLM tool calls, both of which
    can be influenced by attacker-controlled content (e.g. prompt injection
    embedded in fetched news). Without validation, a value like
    ``"../../../etc/foo"`` flows into ``os.path.join`` / ``Path /`` and
    escapes the configured cache, checkpoint, or results directory.

    Returns ``value`` unchanged when it matches the allowed pattern; raises
    ``ValueError`` otherwise.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"ticker must be a non-empty string, got {value!r}")
    if len(value) > max_len:
        raise ValueError(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        raise ValueError(
            f"ticker contains characters not allowed in a filesystem path: {value!r}"
        )
    # The regex above allows '.', so values like '.', '..', '...' would pass,
    # and as a path component they traverse the parent directory. Reject any
    # value that's only dots.
    if set(value) == {"."}:
        raise ValueError(f"ticker cannot consist solely of dots: {value!r}")
    return value


def get_current_date():
    """当前**美股日历日**（美东时区），失败时回退到本机日期。

    **★ 2026-09-17 修正：原实现是 ``date.today()``（本机时区），语义错误。**

    本函数被 ``date_window.withhold_live_profile`` 用于判断「请求的 as_of 是不是
    过去日期」：若 ``curr_date < today`` 就扣留 yfinance 的 ``Ticker.info`` 快照，
    理由是「vendor 只有今日值、没有历史 vintage，喂进历史回填会前视」。

    该理由成立，但**参照系必须是美股日历日，而不是用户本机日期**。实测踩坑
    （本机在北京时区，2026-09-18 08:51）：
      · 美东此刻是 **2026-09-17 20:51**，9/17 那个交易日**已经收盘**
      · 请求 ``as_of = 2026-09-17`` —— 这正是「当前」的美股交易日
      · 但 ``date.today()`` 返回 **2026-09-18**，于是 ``2026-09-17 < 2026-09-18``
        被判为历史回填，**整块估值快照被扣留**
        （市值 / PE / Forward PE / PB / Beta / 52 周区间 / TTM 收入全部消失）

    后果的严重性在于它**只在北京时间凌晨到上午复现**（美东仍在前一日），
    且表现为「通道 ok 但内容是合规声明」，极易被当成正常结果放过去 ——
    与铁律「时点闸门」是同一类错误：**参照系选错，闸门就会在正确的时间误伤。**

    修正后：以美东日历日为参照。北京时间 9/18 上午请求 9/17 的美股分析，
    判定为「当前」，快照正常提供；请求 9/16 及更早，仍按历史回填扣留。
    """
    try:
        import datetime as _dt
        import zoneinfo

        return _dt.datetime.now(zoneinfo.ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        # 缺 tzdata / 平台不支持时退回本机日期，至少不比原来更差
        return date.today().strftime("%Y-%m-%d")
