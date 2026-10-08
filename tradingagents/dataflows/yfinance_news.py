"""yfinance-based news data fetching functions."""

import contextlib
import logging
import re
import urllib.request
from datetime import datetime, timezone

import yfinance as yf
from dateutil.relativedelta import relativedelta

from .config import get_config
from .date_window import in_window
from .stockstats_utils import yf_retry
from .symbol_utils import normalize_symbol

logger = logging.getLogger(__name__)

# ── 新闻正文回填 ─────────────────────────────────────────────────────────────
#
# 背景（2026-10-08 GOOG 轮实测）：yfinance 1.7.0 有两条新闻通道，**都不保证正文**：
#   ① ``Ticker().news`` / ``Ticker().get_news()`` —— 条目嵌套在 ``content`` 里、**含
#      ``summary``**，设计上能带正文。但该端点在 2026-10-08 实测**对所有 symbol
#      （^GSPC / SPY / AAPL / GOOG …）一律返回 0 条** ⇒ 上游降级，主通道事实失效。
#   ② ``Search().news`` —— 平铺结构，顶层键并集固定为
#      ``{link, providerPublishTime, publisher, relatedTickers, thumbnail, title,
#      type, uuid}``，**不含 ``summary``/``content``/``description``** ⇒ 结构性无正文。
#   两条都拿不到正文时，宏观新闻只剩「标题 + Link」，下游只能按标题做粗粒度定性。
#
# 修法：**按需回填**。条目已带正文就直接用；缺正文且给了 link 时，抓一次新闻页，
# 从 ``article-body`` 容器里提取 ``<p>`` 段落（该容器内是常规 HTML，语义干净）。
# ⚠️ 不要在全页范围匹配 ``<p>`` —— Yahoo 页面后半段有编码混淆脚本，会污染提取结果
#    （实测首段会变成乱码）；**必须先把范围限定到 ``article-body`` 容器**。
#
# 为什么不在采集时无条件抓正文：每篇一次外网请求，会显著拖慢采集并放大限流风险。
# 故设 ``_BODY_FETCH_LIMIT`` 上限，且失败一律静默降级（保留标题，不中断采集）。
_NEWS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_BODY_FETCH_LIMIT = 8          # 每次调用最多回填几篇正文
_BODY_FETCH_TIMEOUT = 12       # 单篇抓取超时（秒）
_BODY_MAX_CHARS = 1200         # 单篇正文截断上限，避免证据包被单篇挤爆


def _extract_body_from_html(html: str) -> str:
    """从 Yahoo 新闻页 HTML 提取正文段落（限定在 ``article-body`` 容器内）。

    返回以空格连接的段落串（已截断）；提取不到返回空串。
    """
    anchor = html.find("article-body")
    if anchor < 0:
        return ""
    # 只在容器起始后的一段窗口内找段落，避免扫到页面尾部的混淆脚本。
    seg = html[anchor:anchor + 80000]
    paras: list[str] = []
    total = 0
    for raw in re.findall(r"<p[^>]*>(.*?)</p>", seg, re.S):
        text = re.sub(r"<[^>]+>", "", raw)
        text = re.sub(r"&\w+;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 60:
            continue
        paras.append(text)
        total += len(text)
        if total >= _BODY_MAX_CHARS:
            break
    return " ".join(paras)[:_BODY_MAX_CHARS]


def _fetch_article_body(url: str) -> str:
    """抓取单篇新闻页并提取正文；任何失败都返回空串（静默降级）。"""
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _NEWS_UA})
        with urllib.request.urlopen(req, timeout=_BODY_FETCH_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — 正文是加分项，抓不到不能中断采集
        return ""
    return _extract_body_from_html(html)


def backfill_missing_summaries(articles: list[dict], limit: int = _BODY_FETCH_LIMIT) -> int:
    """给缺正文的条目就地回填 ``summary``（最多 ``limit`` 篇）。

    原地修改 ``articles`` 中条目：``content.summary``（嵌套）或顶层 ``summary``。
    返回实际回填的篇数，便于调用方按需记录。
    """
    filled = 0
    for article in articles:
        if filled >= limit:
            break
        nested = "content" in article
        holder = article["content"] if nested else article
        if holder.get("summary"):
            continue                      # 已有正文，不必抓
        link = ""
        if nested:
            url_obj = holder.get("canonicalUrl") or holder.get("clickThroughUrl") or {}
            link = url_obj.get("url", "")
        else:
            link = holder.get("link", "")
        body = _fetch_article_body(link)
        if body:
            holder["summary"] = body
            filled += 1
    return filled


_SEARCH_NEWS_COUNT = 50         # Search() 兜底时请求条数（专属+窗口闸门后再截断到 article_limit）
_SUBJECT_MAX_RELATED = 3        # relatedTickers 超过此数即判为「多股榜单/综述」，不算主体报道


def _search_news_fallback(canonical: str) -> list[dict]:
    """``Search()`` 兜底通道 —— **仅在 Ticker 通道整体归零时**调用。

    为什么必须带「语义专属」闸门（2026-10-08 NFLX 轮实测）：

    * ``Ticker().news`` / ``Ticker().get_news()`` 对所有 symbol 一律返回 0 条
      （NFLX / ^GSPC / AAPL 实测均 n=0）⇒ 主通道上游降级，个股新闻事实失效。
    * ``Search(query=canonical).news`` 仍有数据（NFLX 实测 n=49），但它返回的是
      **泛相关**条目：实测 ``relatedTickers 含 NFLX`` 命中 49/49，其中混着
      *Amazon AWS / Google 估值 / Disney 股价 / MarketBeat 周报* 等**他股主体**文章。
      ⇒ 直接用等于把噪声当证据（铁律 6：分清「主体」与「顺带提及」）。

    闸门判据（二选一，命中即视为主体报道）：
      ① 标题含该代码（整词匹配）；
      ② ``relatedTickers`` 首位即该代码**且**总数 ≤ ``_SUBJECT_MAX_RELATED``
         —— 加长度上限是因为榜单/综述型文章会列一大串代码
         （实测 "3 Magnificent Stocks Near 52-Week Lows" 列了 4+ 个），
         本标的在其中只是顺带提及。

    实测（NFLX，Search 返回 49 条）：
      * 弱判据「relatedTickers 含 NFLX」放行 **49/49** —— 不可用，全是噪声；
      * 闸门放行 **20~33 条**（随上游返回波动），经逐条复核**全部为 NFLX 主体报道**，
        被拦下的确为 Amazon AWS / Google 估值 / Disney 股价 / MarketBeat 周报等他股主体。
      * 早期版本少了长度上限，"3 Magnificent Stocks…" 这类榜单会被误收，故补上条件 ② 的 ≤3。
    """
    try:
        search = yf_retry(lambda: yf.Search(
            query=canonical,
            news_count=_SEARCH_NEWS_COUNT,
            enable_fuzzy_query=True,
        ))
    except Exception as exc:  # noqa: BLE001 — 兜底通道自身失败不应中断采集
        # ⚠️ 不能静默吞掉：2026-10-09 实测连续大 news_count 查询会触发 429，
        # yf_retry 退避（2/4/8s）后仍失败即抛出，若此处 return [] 会让下游把
        # 「限流」误读成「确实没有新闻」，通道伪装成正常空结果（铁律 3 静默失败）。
        # ⇒ 至少留一条 WARNING，让「无新闻」与「拿不到」可被区分。
        logger.warning(
            "get_news Search fallback failed for %s (%s: %s) -> 该通道按「无新闻」处理，"
            "可能与限流有关，需人工复核",
            canonical, type(exc).__name__, exc,
        )
        return []

    tick_pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(canonical)}(?![A-Za-z0-9])")
    out: list[dict] = []
    for article in search.news or []:
        holder = article.get("content") or article
        title = str(holder.get("title") or "")
        raw_rel = holder.get("relatedTickers") or article.get("relatedTickers") or []
        rel = [str(x).strip() for x in raw_rel if str(x).strip()]
        # 榜单/综述型文章的 relatedTickers 会列一大串（实测 "3 Magnificent Stocks
        # Near 52-Week Lows" 列了 4+ 个），本标的只是顺带提及 ⇒ 用长度上限挡掉。
        is_subject = bool(tick_pat.search(title)) or (
            len(rel) > 0 and rel[0] == canonical and len(rel) <= _SUBJECT_MAX_RELATED
        )
        if is_subject:
            out.append(article)
    return out


def _extract_article_data(article: dict) -> dict:
    """Extract article data from yfinance news format (handles nested 'content' structure)."""
    # Handle nested content structure
    if "content" in article:
        content = article["content"]
        title = content.get("title", "No title")
        summary = content.get("summary", "")
        provider = content.get("provider", {})
        publisher = provider.get("displayName", "Unknown")

        # Get URL from canonicalUrl or clickThroughUrl
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        link = url_obj.get("url", "")

        # Get publish date
        pub_date_str = content.get("pubDate", "")
        pub_date = None
        if pub_date_str:
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))

        return {
            "title": title,
            "summary": summary,
            "publisher": publisher,
            "link": link,
            "pub_date": pub_date,
        }
    else:
        # Fallback for flat structure. Parse the epoch publish time so flat
        # articles are date-filterable too (otherwise they bypass the
        # historical window and leak future news, #992/#1007).
        pub_date = None
        ts = article.get("providerPublishTime")
        if ts:
            # Epoch seconds are UTC; parse them as UTC-aware so filtering does
            # not shift with the host timezone (#1126).
            with contextlib.suppress(ValueError, OSError, TypeError):
                pub_date = datetime.fromtimestamp(ts, tz=timezone.utc)
        return {
            "title": article.get("title", "No title"),
            "summary": article.get("summary", ""),
            "publisher": article.get("publisher", "Unknown"),
            "link": article.get("link", ""),
            "pub_date": pub_date,
        }


def get_news_yfinance(
    ticker: str,
    start_date: str,
    end_date: str,
) -> str:
    """
    Retrieve news for a specific stock ticker using yfinance.

    Args:
        ticker: Stock ticker symbol (e.g., "AAPL")
        start_date: Start date in yyyy-mm-dd format
        end_date: End date in yyyy-mm-dd format

    Returns:
        Formatted string containing news articles
    """
    article_limit = get_config()["news_article_limit"]
    # Query Yahoo with the canonical symbol, like every other yfinance path —
    # a raw broker/forex/crypto alias (XAUUSD, BTCUSD) otherwise silently
    # returns no news. Keep the user's ticker in the report header.
    canonical = normalize_symbol(ticker)
    resolved = "" if canonical == ticker else f" (resolved to {canonical})"
    try:
        stock = yf.Ticker(canonical)
        news = yf_retry(lambda: stock.get_news(count=article_limit))

        if not news:
            # 2026-10-09 修复：主通道（Ticker().news / .get_news()）上游降级归零时，
            # 走 `_search_news_fallback()` 的 Search() + 语义专属闸门。
            #
            # 【替换掉的旧兜底为什么必须删】此前这里写的是
            #     queries = [f"Alphabet {canonical}", f"{canonical}"]
            #     ... if (canonical in related or canonical in title
            #             or "Alphabet" in title or "Google" in title)
            # 三处硬伤：
            #   ① 把 GOOG 的公司名**硬编码进通用通道** —— 对任意标的都先搜一遍
            #      "Alphabet <TICKER>"；NFLX 轮实测该查询 n=0（开 fuzzy 后返回 37 条，
            #      但全是 Amazon / Google / Alphabet 报道）。
            #   ② **后门放行** —— "Google" in title 这一支会让 37 条里 **18 条 Google 新闻**
            #      通过过滤，直接写进 NFLX 的个股新闻节 ⇒ 跨标的污染。
            #   ③ `except Exception: pass` 把真实异常静默吞掉，故障不可观测。
            # ⇒ 判据统一收敛到 `_search_news_fallback()`，且与标的无关。
            news = _search_news_fallback(canonical)

        if not news:
            return f"No news found for {ticker}{resolved}"

        # 正文回填：Ticker().news 通常自带 summary，但上游降级时（2026-10-08 实测
        # 全 symbol 返回 0 条，改走 get_news 后才拿到条目）正文可能缺失 —— 缺则回填。
        backfill_missing_summaries(news[:article_limit])

        # Parse date range for filtering
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        news_str = ""
        filtered_count = 0

        for article in news:
            data = _extract_article_data(article)

            # Keep only articles within the requested window (look-ahead safe).
            if not in_window(data["pub_date"], start_dt, end_dt):
                continue

            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            filtered_count += 1

        if filtered_count == 0:
            return f"No news found for {ticker}{resolved} between {start_date} and {end_date}"

        return f"## {ticker}{resolved} News, from {start_date} to {end_date}:\n\n{news_str}"

    except Exception as e:
        return f"Error fetching news for {ticker}: {str(e)}"


# 宏观新闻的主通道：宽基指数的 ``Ticker().news``。
#
# 为什么不用 ``Search()``：yfinance 1.7.0 的 ``Search().news`` 返回的是**平铺结构**，
# 其顶层键只有 ``link / providerPublishTime / publisher / relatedTickers / thumbnail
# / title / type / uuid`` —— **不含 ``summary``**，于是宏观新闻每条只剩标题 + Link。
# 而 ``Ticker().news`` 的条目是**嵌套在 ``content`` 里**的，**含 ``summary``**。
# ⇒ 个股新闻（走 Ticker）一直有正文、宏观新闻（走 Search）一直没有，根因在此。
GLOBAL_NEWS_TICKERS = ("^GSPC", "^TNX", "^VIX")


def _fetch_global_via_tickers() -> list[dict]:
    """主通道：聚合几个宽基指数的 ``Ticker().news``（该通道提供 ``summary``）。

    单个指数失败不影响其余；全部失败时返回空列表，由调用方回退到 ``Search()``。
    """
    out: list[dict] = []
    for sym in GLOBAL_NEWS_TICKERS:
        try:
            news = yf_retry(lambda s=sym: yf.Ticker(s).news) or []
        except Exception:  # noqa: BLE001 — 单通道失败不应中断整体采集
            continue
        out.extend(news)
    return out


def get_global_news_yfinance(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """
    Retrieve global/macro economic news.

    Args:
        curr_date: Current date in yyyy-mm-dd format
        look_back_days: Number of days to look back. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Maximum number of articles to return. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string containing global news articles
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    search_queries = config["global_news_queries"]

    curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")

    all_news = []
    seen_titles = set()

    try:
        # ① 主通道：宽基指数的 Ticker().news —— 该通道的条目**含 summary**，
        #    这是宏观新闻能带正文的关键（Search() 不提供该字段）。
        for article in _fetch_global_via_tickers():
            data = _extract_article_data(article)
            # 主通道同样必须过窗口：Ticker().news 只回最新快讯，在回溯场景下
            # 它们往往整体落在窗口之外 —— 不过滤会把配额占满、挤掉兜底通道。
            if not in_window(data["pub_date"], start_dt, curr_dt):
                continue
            title = data["title"]
            if title and title != "No title" and title not in seen_titles:
                seen_titles.add(title)
                all_news.append(article)
                if len(all_news) >= limit:
                    break

        # ② 兜底：Search() —— 结构为平铺、无 summary，仅保证主通道全失效时仍有内容。
        for query in search_queries:
            if len(all_news) >= limit:
                break
            search = yf_retry(lambda q=query: yf.Search(
                query=q,
                news_count=limit,
                enable_fuzzy_query=True,
            ))

            if search.news:
                for article in search.news:
                    # Handle both flat and nested structures
                    if "content" in article:
                        data = _extract_article_data(article)
                        title = data["title"]
                    else:
                        title = article.get("title", "")

                    # Deduplicate by title
                    if title and title not in seen_titles:
                        seen_titles.add(title)
                        all_news.append(article)

            if len(all_news) >= limit:
                break

        if not all_news:
            return f"No global news found for {curr_date}"

        # ③ 正文回填：两条通道都不保证正文（见文件头说明）。此处按需抓取，
        #    把「仅有标题」升级为「标题 + 正文」，让宏观新闻可作定性依据。
        #    先按窗口过滤出真正会入选的条目，再对它们回填，避免抓了用不上的。
        _in_window = [a for a in all_news[:limit]
                      if in_window(_extract_article_data(a)["pub_date"], start_dt, curr_dt)]
        backfill_missing_summaries(_in_window)

        news_str = ""
        kept = 0
        for article in all_news[:limit]:
            # Extract uniformly (flat + nested) and apply the same look-ahead-safe
            # window filter, so flat articles can't leak future news (#1007).
            data = _extract_article_data(article)
            if not in_window(data["pub_date"], start_dt, curr_dt):
                continue
            news_str += f"### {data['title']} (source: {data['publisher']})\n"
            if data["summary"]:
                news_str += f"{data['summary']}\n"
            if data["link"]:
                news_str += f"Link: {data['link']}\n"
            news_str += "\n"
            kept += 1

        # All candidates fell outside the window -> say so rather than return an
        # empty-bodied report (#993).
        if kept == 0:
            return f"No global news found between {start_date} and {curr_date}"

        return f"## Global Market News, from {start_date} to {curr_date}:\n\n{news_str}"

    except Exception as e:
        return f"Error fetching global news: {str(e)}"
