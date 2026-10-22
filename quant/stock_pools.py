# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/stock_pools.py
"""美股核心股票池定义与动态获取模块。

包含：
1. 纳斯达克 100 指数成分股（NASDAQ_100 静态快照 + 动态同步）
2. 标普 500 核心蓝筹成分股（SP_500_CORE 精选子集）
3. 全量标普 500 动态获取（get_latest_sp500）

━━━ 2026-09-16 重要修复 ━━━
原 ``get_latest_nasdaq_100()`` 有两个 bug，导致它**永远静默回退到静态快照**：

1. **抓错了页面。** 它请求 ``/wiki/Nasdaq-100``，但该页 18 张表里**没有一张
   超过 90 行**（最大 41 行）—— 成分股列表已迁到独立页面
   ``/wiki/List_of_NASDAQ-100_companies``（实测 102 行、列名就是 ``Ticker``）。
   原判定条件找不到 ``Ticker`` 列，于是每次都返回静态快照。

2. **超时太短。** 原先 ``timeout=5``，而该页面实测耗时 1.0~2.8s（网络波动时更长），
   余量太薄，偶发超时同样会静默回退。

**这两个 bug 的代价很大**：静态快照当时已过期约两年。与实时清单对比，
**96 只里有 42 只是错的（44%）** —— 缺 24 只（ASML/WMT/ADP/CMCSA/SHOP/MSTR/TTWO/
RKLB…）、多 18 只已非成分（MRNA/SMCI/TEAM/TTD/ZS/ILMN/LULU/BIIB…）。
等于一直在用**错误的股票池**做筛选。

另注：``en.wikipedia.org`` 在本机**可达**（实测 HTTP 200）。此前"大陆不可达"
的判断是未经实测的臆断，已证伪。
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

# ── 数据源配置 ────────────────────────────────────────────────────────────
WIKI_TIMEOUT = 20          # 实测该页 1.0~2.8s；5s 余量太薄会偶发超时
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
NASDAQ100_LIST_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
SP500_LIST_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

# ── 标普500 备用源（2026-09-18 新增）─────────────────────────────────────
# 实测 `en.wikipedia.org` 与 `raw.githubusercontent.com` 会被本机代理拦截
# （ProxyError / 502 Bad Gateway），而下列两个源可正常访问。
# 两个源在 2026-09-18 实测均返回 **503 只且交集 100%**，可交叉验证。
#   · ghfast.top 是 GitHub raw 的公共镜像；datasets/s-and-p-500-companies
#     维护成分股 CSV（含 Date added 列，实测最新 2026-08-18，非陈旧快照）
#   · stockanalysis.com 为实时页面
SP500_MIRROR_CSV_URL = (
    "https://ghfast.top/https://raw.githubusercontent.com/"
    "datasets/s-and-p-500-companies/main/data/constituents.csv"
)
SP500_STOCKANALYSIS_URL = "https://stockanalysis.com/list/sp-500-stocks/"

# ── 标普 400 / 600（2026-09-20 新增，用于把选池扩到标普 1500）────────────
SP400_LIST_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
SP600_LIST_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"

# 校验锚点：解析结果必须包含这些公认成分，否则视为解析失败（防止抓到别的表）
SANITY_ANCHORS = {"NVDA", "AAPL", "MSFT", "AMZN", "META"}

CACHE_DIR = Path(os.path.expanduser("~")) / ".tradingagents" / "cache"


# ── 静态快照（动态同步失败时的兜底）──────────────────────────────────────
# 2026-09-16 按 Wikipedia「List of NASDAQ-100 companies」全量刷新（102 只）。
# 注意：GOOG 与 GOOGL 是 Alphabet 的两个股份类别，两者都在指数内，故都保留 ——
#       做**指数聚合**时须去重，做**个股筛选**时视为两个独立标的。
# 注意：本清单含部分新纳入代码（ALAB/CRWV/FER/HONA/NBIS/RKLB/SPCX/SNDK 等）尚未在本地
#       验证过行情，首次运行若出现「无行情数据」属正常，看 failed_records 即可。
NASDAQ_100 = [
    'ADBE', 'AMD', 'ABNB', 'ALNY', 'GOOGL', 'GOOG', 'AMZN', 'AEP', 'AMGN', 'ADI', 'AAPL',
    'AMAT', 'APP', 'ARM', 'ASML', 'ALAB', 'ADSK', 'ADP', 'AXON', 'BKR', 'BKNG', 'AVGO',
    'CDNS', 'CTAS', 'CSCO', 'CCEP', 'CMCSA', 'CEG', 'CPRT', 'CRWV', 'COST', 'CRWD', 'CSX',
    'DDOG', 'DXCM', 'FANG', 'DASH', 'EXC', 'FAST', 'FER', 'FTNT', 'GEHC', 'GILD', 'HONA',
    'HON', 'IDXX', 'INTC', 'INTU', 'ISRG', 'KDP', 'KLAC', 'KHC', 'LRCX', 'LIN', 'LITE',
    'MAR', 'MRVL', 'MELI', 'META', 'MCHP', 'MU', 'MSFT', 'MSTR', 'MDLZ', 'MPWR', 'MNST',
    'NBIS', 'NFLX', 'NVDA', 'NXPI', 'ORLY', 'ODFL', 'PCAR', 'PLTR', 'PANW', 'PAYX', 'PYPL',
    'PDD', 'PEP', 'QCOM', 'REGN', 'RKLB', 'ROP', 'ROST', 'SNDK', 'STX', 'SHOP', 'SPCX',
    'SBUX', 'SNPS', 'TMUS', 'TTWO', 'TER', 'TSLA', 'TXN', 'TRI', 'VRTX', 'WMT', 'WBD',
    'WDC', 'WDAY', 'XEL',
]

# 静态快照：标普 500 精选核心（人工维护的权重股子集，非全量）。
# 需要全量标普 500 请用 get_latest_sp500()。
SP_500_CORE = [
    'NVDA', 'MSFT', 'AAPL', 'AMZN', 'META', 'GOOGL', 'BRK-B', 'AVGO', 'TSLA', 'JPM',
    'LLY', 'UNH', 'V', 'XOM', 'MA', 'COST', 'PG', 'HD', 'JNJ', 'WMT',
    'BAC', 'NFLX', 'ABBV', 'CRM', 'KO', 'MRK', 'CVX', 'AMD', 'ORCL', 'PEP',
    'LIN', 'TMO', 'ACN', 'MCD', 'CSCO', 'ABT', 'ADBE', 'IBM', 'GE', 'WFC',
    'QCOM', 'TXN', 'PM', 'CAT', 'ISRG', 'NOW', 'VZ', 'DIS', 'INTU', 'AMAT',
    'AXP', 'CMCSA', 'BKNG', 'UBER', 'PFE', 'GS', 'MS', 'RTX', 'SPGI', 'LOW',
    'T', 'HON', 'UNP', 'SYK', 'COP', 'BLK', 'AMGN', 'PGR', 'VRTX', 'TJX',
    'C', 'REGN', 'LRCX', 'ETN', 'BSX', 'PANW', 'MDT', 'BA', 'CB', 'CI',
    'FI', 'PLTR', 'DE', 'BMY', 'ADI', 'KLAC', 'MMC', 'MDLZ', 'MU', 'SCHW',
    'GILD', 'ADP', 'CVS', 'LMT', 'SNPS', 'CDNS', 'CRWD', 'AMT', 'EOG',
]


# ── 内部工具 ─────────────────────────────────────────────────────────────

def _cache_path(kind: str) -> Path:
    """**单一文件 + TTL**，不按日期命名。

    ⚠️ 原先按天命名（``constituents_<kind>_<date>.json``）会每天留一份副本。
    成分股清单只在指数重组时变化（纳指每年 12 月 + 季度再平衡），
    按天命名纯属累积垃圾。改为单文件覆盖，新鲜度由 TTL 控制。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"constituents_{kind}.json"


def _fetch_wiki_tickers(url: str, columns: tuple[str, ...], min_rows: int) -> list[str]:
    """从 Wikipedia 页面解析成分股代码。抛异常表示失败，由调用方决定兜底。"""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=WIKI_TIMEOUT)
    resp.raise_for_status()
    for tbl in pd.read_html(io.StringIO(resp.text)):
        if len(tbl) < min_rows:
            continue
        for col in columns:
            if col not in tbl.columns:
                continue
            raw = [str(x).strip().upper().replace(".", "-")
                   for x in tbl[col].dropna() if str(x).strip()]
            # 防止抓到行数够但内容无关的表
            if len(raw) >= min_rows and SANITY_ANCHORS & set(raw):
                seen, out = set(), []
                for t in raw:
                    if t not in seen:
                        seen.add(t)
                        out.append(t)
                return out
    raise ValueError(f"未找到合格成分股表（列候选={columns}, 最少 {min_rows} 行）")


def _normalize_tickers(raw: list[str]) -> list[str]:
    """统一代码格式并去重（``BRK.B`` -> ``BRK-B``，yfinance 用连字符）。

    保留原始顺序；``SANITY_ANCHORS`` 必须命中，否则视为抓错页面。
    """
    out, seen = [], set()
    for x in raw:
        t = str(x).strip().upper().replace(".", "-")
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _fetch_csv_tickers(url: str, column: str, min_rows: int) -> list[str]:
    """从 CSV 解析成分股代码（GitHub 镜像源用）。抛异常表示失败。"""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=WIKI_TIMEOUT)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    if column not in df.columns:
        raise ValueError(f"CSV 缺少列 {column}，实际列={list(df.columns)}")
    out = _normalize_tickers([x for x in df[column].dropna() if str(x).strip()])
    if len(out) < min_rows or not (SANITY_ANCHORS & set(out)):
        raise ValueError(f"CSV 内容不合格（{len(out)} 行，锚点未命中）")
    return out


def _fetch_stockanalysis_tickers(url: str, min_rows: int) -> list[str]:
    """从 stockanalysis.com 列表页抓代码（第二道备用源）。抛异常表示失败。"""
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=WIKI_TIMEOUT)
    resp.raise_for_status()
    hits = re.findall(r"/stocks/([A-Za-z0-9\.\-]{1,6})/", resp.text)
    out = _normalize_tickers([h for h in hits if not h.isdigit()])
    if len(out) < min_rows or not (SANITY_ANCHORS & set(out)):
        raise ValueError(f"页面内容不合格（{len(out)} 个候选，锚点未命中）")
    return out


def _load_cached(kind: str, max_age_days: float = 1.0) -> list[str] | None:
    """读缓存。超过 TTL 视为未命中（成分股每日刷新一次即可）。"""
    p = _cache_path(kind)
    if not p.exists():
        return None
    age_days = (time.time() - p.stat().st_mtime) / 86400
    if age_days > max_age_days:
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        tickers = data.get("tickers") or []
        return tickers if len(tickers) >= 90 else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_cached(kind: str, tickers: list[str], url: str) -> None:
    try:
        _cache_path(kind).write_text(json.dumps({
            "date": dt.date.today().isoformat(),
            "source": url,
            "count": len(tickers),
            "tickers": tickers,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass   # 缓存写不进去不该影响主流程


# ── 公开接口 ─────────────────────────────────────────────────────────────

def get_latest_nasdaq_100(force: bool = False) -> list[str]:
    """纳斯达克 100 成分股。

    顺序：当日缓存 -> Wikipedia 实时 -> 静态快照 NASDAQ_100。
    任一环节失败都会**打印原因**后降级，不再静默吞掉 ——
    静默降级正是这个函数此前长期失效却无人察觉的根本原因。
    """
    if not force:
        cached = _load_cached("nasdaq100")
        if cached:
            print(f"[Pool] 命中当日成分股缓存（{len(cached)} 只）")
            return cached
    try:
        tickers = _fetch_wiki_tickers(NASDAQ100_LIST_URL, ("Ticker", "Symbol"), 90)
        print(f"[Pool] 已从 Wikipedia 同步纳斯达克100：{len(tickers)} 只")
        _save_cached("nasdaq100", tickers, NASDAQ100_LIST_URL)
        return tickers
    except Exception as exc:  # noqa: BLE001
        print(f"[Pool] ⚠️ 动态同步失败（{type(exc).__name__}: {exc}），"
              f"回退到静态快照 {len(NASDAQ_100)} 只 —— 该快照可能已过期，请留意")
        return list(NASDAQ_100)


def get_latest_sp500(force: bool = False) -> list[str]:
    """全量标普 500 成分股（约 503 只）。

    顺序：当日缓存 -> Wikipedia -> GitHub 镜像 CSV -> stockanalysis -> 静态精选子集。

    **为什么需要这么多备用源**（2026-09-18 实测）：本机代理会拦截
    ``en.wikipedia.org`` 与 ``raw.githubusercontent.com``（ProxyError），
    而原实现只有 Wikipedia 一条路，失败后**静默回退到 99 只精选核心** ——
    那会让「全量标普500」悄悄退化成「市值前 99 名」，广度与集中度全部失真。
    故此处逐一尝试并**打印实际命中的源**。
    """
    if not force:
        cached = _load_cached("sp500")
        if cached:
            print(f"[Pool] 命中当日成分股缓存（{len(cached)} 只）")
            return cached

    sources = (
        ("Wikipedia", lambda: _fetch_wiki_tickers(SP500_LIST_URL, ("Symbol", "Ticker"), 400)),
        ("GitHub镜像", lambda: _fetch_csv_tickers(SP500_MIRROR_CSV_URL, "Symbol", 400)),
        ("stockanalysis", lambda: _fetch_stockanalysis_tickers(SP500_STOCKANALYSIS_URL, 400)),
    )
    failures: list[str] = []
    for name, fn in sources:
        try:
            tickers = fn()
            print(f"[Pool] 已从 {name} 同步标普500：{len(tickers)} 只")
            _save_cached("sp500", tickers, name)
            return tickers
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}({type(exc).__name__})")
            print(f"[Pool] ⚠️ {name} 同步失败：{type(exc).__name__}: {str(exc)[:120]}")

    print(f"[Pool] ⚠️⚠️ 标普500 全部动态源失败（{'、'.join(failures)}），"
          f"回退到精选核心 {len(SP_500_CORE)} 只 —— "
          f"**这不是全量标普500，广度/集中度结论会严重失真，报告中必须声明！**")
    return list(SP_500_CORE)


def _fetch_wiki_tickers_band(
    url: str, columns: tuple[str, ...], lo: int, hi: int
) -> list[str]:
    """按「行数落在 [lo, hi]」锁定成分股表。

    为什么不能复用 :func:`_fetch_wiki_tickers`：它用 ``SANITY_ANCHORS``
    （NVDA/AAPL/MSFT/AMZN/META —— 全是标普 500 的大票）判断是否抓对表，
    而**标普 400/600 与 500 是互斥名单**，锚点在这里**必然不命中**，
    用它会 100% 走到 ``raise``。故改用行数区间：
    同一页上还有一张「成分变动历史」表，行数与列名都不同，区间可把两者分开。
    """
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=WIKI_TIMEOUT)
    resp.raise_for_status()
    for tbl in pd.read_html(io.StringIO(resp.text)):
        if not (lo <= len(tbl) <= hi):
            continue
        for col in columns:
            if col not in tbl.columns:
                continue
            raw = _normalize_tickers(
                [x for x in tbl[col].dropna() if str(x).strip()]
            )
            if lo <= len(raw) <= hi:
                return raw
    raise ValueError(
        f"未找到行数在 [{lo}, {hi}] 的成分股表（列候选={columns}）"
    )


def get_latest_sp1500(force: bool = False) -> list[str]:
    """标普 1500 ＝ 500 + 400 + 600，约 1500 只（大 / 中 / 小盘）。

    **为什么选它而不是全市场**：「成长但被低估」在中盘与小盘里才常见，
    标普 500 内几乎不存在；而指数成分本身自带**流动性 / 可投资性过滤**，
    免去从全市场清单里剔 ETF / 权证 / 单位 / 优先股 / 空壳的麻烦。

    ⚠️ **两条必须一起声明的性质**：
    1. 本引擎的打分是**截面百分位** ⇒ **换宇宙会改变每一个分数**
       （「成长前 30%」在 503 只里和在 1500 只里不是同一件事）。
    2. 拿到的全是**当前**成分 ⇒ 回测存在**幸存者偏差**（见 SCREENER §3.4）。

    **不做静默降级**：三份里任何一份失败都会打印醒目警告，并回报实际组成
    （``parts``）；少于两份成功则直接抛异常 —— 宁可失败，也不要拿一个
    悄悄变小（或错配）的宇宙去筛选。
    """
    if not force:
        cached = _load_cached("sp1500", max_age_days=1.0)
        if cached and len(cached) >= 1200:
            print(f"[Pool] 命中当日成分股缓存（{len(cached)} 只）")
            return cached

    specs = (
        ("sp500", lambda: get_latest_sp500(force=force), 480, 520),
        ("sp400", lambda: _fetch_wiki_tickers_band(SP400_LIST_URL, ("Symbol",), 380, 420), 380, 420),
        ("sp600", lambda: _fetch_wiki_tickers_band(SP600_LIST_URL, ("Symbol",), 570, 640), 570, 640),
    )
    parts: dict[str, list[str]] = {}
    failures: list[str] = []
    for name, fn, lo, hi in specs:
        try:
            got = fn()
            if not (lo <= len(got) <= hi):
                raise ValueError(f"只数 {len(got)} 不在预期区间 [{lo}, {hi}]")
            parts[name] = got
            print(f"[Pool] 标普1500 组成 {name}: {len(got)} 只")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}({type(exc).__name__})")
            print(f"[Pool] ⚠️ 标普1500 的 {name} 获取失败：{type(exc).__name__}: {str(exc)[:120]}")

    if len(parts) < 2:
        raise RuntimeError(
            f"标普1500 只有 {len(parts)} 份成功（失败：{'、'.join(failures)}），"
            f"拒绝返回一个悄悄变小的宇宙"
        )
    if failures:
        print(f"[Pool] ⚠️⚠️ 标普1500 **不完整**（缺 {'、'.join(failures)}）——"
              f"实际只数 {sum(len(v) for v in parts.values())}，"
              f"截面百分位与广度结论都会受影响，报告中必须声明！")

    # 互斥性校验：标普 500 / 400 / 600 按定义两两不相交，
    # 相交说明某一张表抓错了（例如把「成分变动历史」当成成分表）。
    for a, b in (("sp500", "sp400"), ("sp500", "sp600"), ("sp400", "sp600")):
        if a in parts and b in parts:
            dup = set(parts[a]) & set(parts[b])
            if dup:
                print(f"[Pool] ⚠️ {a} 与 {b} 意外重叠 {len(dup)} 只：{sorted(dup)[:10]}"
                      f" —— 可能抓错表，请核对")

    merged: list[str] = []
    seen: set[str] = set()
    for name in ("sp500", "sp400", "sp600"):
        for t in parts.get(name, []):
            if t not in seen:
                seen.add(t)
                merged.append(t)
    print(f"[Pool] 标普1500 合计 {len(merged)} 只（{'+'.join(f'{n}:{len(parts[n])}' for n in parts)}）")
    _save_cached("sp1500", merged, "wikipedia:500+400+600")
    return merged


def get_nasdaq100_sectors(force: bool = False) -> dict[str, str]:
    """{TICKER: ICB 行业}。

    行业数据**和成分股在同一张 Wikipedia 表里**（列名 ``ICB Industry``），
    所以一次请求就够，不必逐票调 ``.info['sector']``（那是 102 次请求）。

    用途：**行业中性化**。纳指100 高度集中于科技，若不做中性化，
    测出的「因子暴露」很可能只是「行业暴露」—— 回测结论会失去意义。

    ⚠️ 这是**当前**行业分类。历史回测时用它做近似（行业归属极少变动），
       但严格来说存在微小的前视偏差，结论中应声明。
    """
    if not force:
        cached = _load_cached("nasdaq100_sectors_map")
        if cached:
            return cached
    try:
        resp = requests.get(NASDAQ100_LIST_URL,
                            headers={"User-Agent": USER_AGENT}, timeout=WIKI_TIMEOUT)
        resp.raise_for_status()
        for tbl in pd.read_html(io.StringIO(resp.text)):
            if len(tbl) < 90 or "Ticker" not in tbl.columns:
                continue
            sector_col = next((c for c in tbl.columns if "ICB Industry" in str(c)), None)
            if sector_col is None:
                continue
            out = {}
            for _, row in tbl.iterrows():
                tk = str(row["Ticker"]).strip().upper().replace(".", "-")
                sec = str(row[sector_col]).strip()
                if tk and sec and sec.lower() != "nan":
                    out[tk] = sec
            if len(out) >= 90 and SANITY_ANCHORS & set(out):
                print(f"[Pool] 已同步行业分类：{len(out)} 只，{len(set(out.values()))} 个行业")
                _save_cached("nasdaq100_sectors_map", out, NASDAQ100_LIST_URL)
                return out
    except Exception as exc:  # noqa: BLE001
        print(f"[Pool] ⚠️ 行业分类同步失败（{type(exc).__name__}: {exc}），"
              f"中性化将不可用")
    return {}

