"""StockTwits public symbol-stream fetcher.

StockTwits exposes a per-symbol message stream at
``api.stocktwits.com/api/2/streams/symbol/{ticker}.json`` that requires no
API key, no OAuth, and no registration. Each message includes a
user-labeled sentiment field (``Bullish``/``Bearish``/null), the message
body, timestamp, and posting user.

The function is deliberately self-contained: short timeout, graceful
degradation on any HTTP or parse failure, and a string return type so
the calling agent gets a uniform interface regardless of whether the
network call succeeded.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import logging
from datetime import datetime
from urllib.request import Request, urlopen

from .date_window import in_window
from .symbol_utils import crypto_base

logger = logging.getLogger(__name__)

_API = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

# ★ 2026-09-17 修正：StockTwits 会对**非浏览器 User-Agent** 一律返回 403。
#
# 原值是 ``tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)``，
# 实测（2026-09-17 美东盘后，本机）：
#     tradingagents/0.2 (...)  → HTTP 403 Forbidden
#     Python-urllib/3.13       → HTTP 403 Forbidden
#     Mozilla/5.0 ... Chrome   → HTTP 200，返回 30 条带 Bullish/Bearish 标签的消息
#
# 后果极具迷惑性：``fetch_stocktwits_messages`` 按设计「优雅降级」返回占位串
# ``<stocktwits unavailable: HTTPError>``，**不抛异常**；而 collect.py 的 ``_safe_call``
# 只把 ``DATA_UNAVAILABLE`` 前缀判为不可用，于是这个通道被**静默记为 ok**，
# 证据包结尾照报「29 / 29 通道成功」—— 一个必需的证据源实际上整段缺失。
#
# 现在改用浏览器 UA；同时经实测**保留标识信息**并不解决问题（StockTwits 按 UA
# 白名单放行），故按对端要求发送浏览器 UA。调用方 ``_safe_call`` 已同步加固，
# 会识别占位串而不复现「假绿」。
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _within_window(messages, start_date, end_date):
    """Keep only messages published in [start_date, end_date] (look-ahead safe).

    No window (both None) leaves the list untouched for live callers. A message
    whose ``created_at`` (ISO 8601) is unparseable is dropped in a historical
    window, since we can't prove it isn't from after the as-of date (#1220).
    """
    if not (start_date and end_date):
        return messages
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    kept = []
    for m in messages:
        created = None
        raw = m.get("created_at")
        if raw:
            with contextlib.suppress(ValueError, TypeError):
                created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if in_window(created, start_dt, end_dt):
            kept.append(m)
    return kept


def _stocktwits_symbol(ticker: str) -> str:
    """Map a crypto pair to StockTwits' ``<BASE>.X`` convention.

    StockTwits lists crypto as ``BTC.X`` (Yahoo's ``BTC-USD`` form 404s), so any
    crypto symbol resolves to its base plus ``.X``; other symbols pass through
    upper-cased.
    """
    base = crypto_base(ticker)
    return f"{base}.X" if base else ticker.strip().upper()


def fetch_stocktwits_messages(
    ticker: str,
    limit: int = 30,
    timeout: float = 10.0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Fetch recent StockTwits messages for ``ticker`` and return them as a
    formatted plaintext block ready for prompt injection.

    When ``start_date``/``end_date`` (yyyy-mm-dd) are given, messages are trimmed
    to that window. The StockTwits public stream only serves recent messages, so
    for a historical run they all fall after the window and a clear placeholder
    is returned rather than leaking today's chatter into a backtest (#1220).

    Returns a placeholder string when the endpoint is unreachable, the
    symbol has no messages, or the response shape is unexpected — the
    caller never has to special-case None or exceptions.
    """
    url = _API.format(ticker=_stocktwits_symbol(ticker))
    req = Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        # OSError covers URLError/TimeoutError/connection resets; HTTPException
        # covers chunked-transfer errors (IncompleteRead/BadStatusLine, #1024).
        logger.warning("StockTwits fetch failed for %s: %s", ticker, exc)
        return f"<stocktwits unavailable: {type(exc).__name__}>"

    messages = data.get("messages", []) if isinstance(data, dict) else []
    messages = _within_window(messages, start_date, end_date)
    if not messages:
        if start_date and end_date:
            return (
                f"<no StockTwits messages for ${ticker.upper()} within "
                f"{start_date}..{end_date} (public stream serves only recent messages)>"
            )
        return f"<no StockTwits messages found for ${ticker.upper()}>"

    lines = []
    bullish = bearish = unlabeled = 0
    for m in messages[:limit]:
        created = m.get("created_at", "")
        user = (m.get("user") or {}).get("username", "?")
        entities = m.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        sentiment = sentiment_obj.get("basic") if isinstance(sentiment_obj, dict) else None
        body = (m.get("body") or "").replace("\n", " ").strip()
        if len(body) > 280:
            body = body[:280] + "…"

        if sentiment == "Bullish":
            bullish += 1
            tag = "Bullish"
        elif sentiment == "Bearish":
            bearish += 1
            tag = "Bearish"
        else:
            unlabeled += 1
            tag = "no-label"
        lines.append(f"[{created} · @{user} · {tag}] {body}")

    total = bullish + bearish + unlabeled
    bull_pct = round(100 * bullish / total) if total else 0
    bear_pct = round(100 * bearish / total) if total else 0
    summary = (
        f"Bullish: {bullish} ({bull_pct}%) · "
        f"Bearish: {bearish} ({bear_pct}%) · "
        f"Unlabeled: {unlabeled} · "
        f"Total: {total} most-recent messages"
    )
    return summary + "\n\n" + "\n".join(lines)
