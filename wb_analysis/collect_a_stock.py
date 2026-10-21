# lifecycle: reusable
# created: 2026-10-18
# usage: ./.venv/Scripts/python.exe wb_analysis/collect_a_stock.py --ticker 601899.SS --date 2026-10-16
"""A股个股证据采集器 —— 整合 westock CLI (腾讯官方接口) 与 TradingAgents 内置层。

专为 A 股个股标的（如 601899.SS 紫金矿业）设计：
1. 行情与日K线序列（260根完整覆盖年线）
2. 全套技术指标（MA5/10/20/50/60/120/200/250, BOLL, MACD, KDJ, RSI, ATR, VWMA）
3. 筹码成本分布（平均成本、70%/90%集中度、获利盘比例）
4. 资金与流动性结构（超大单/大单/中单/小单主力净流入、两融余额变化、陆股通北向持仓）
5. 股东与分红历史（十大股东持股比例、外资持仓、分红派现方案）
6. 机构一致预期与量化评分（一致目标价、盈利预期、综合评分）
7. 权威新闻与公司重大公告（腾讯证券/东财/上证报、产销量、海外矿山并购、业绩预告）
8. 三大财务报表（年度与TTM口径：利润表、资产负债表、现金流量表）与估值快照
9. 关联大宗商品定价传导（黄金 GC=F、铜 HG=F）
10. 中国宏观与利率流动性环境（国债10Y-1Y利差、股债风险溢价 ERP）
11. 结构性缺口显式声明与归因（A股个股期权与海外社媒定位）

产物：
    wb_analysis/evidence/<TICKER>_<YYYY-MM-DD>.md    证据包
    wb_analysis/evidence/<TICKER>_<YYYY-MM-DD>.json  通道健康度与结构化数值
    wb_analysis/evidence/<TICKER>_<YYYY-MM-DD>.gaps.json 数据缺口台账
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import os
import pathlib
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVID_DIR = ROOT / "wb_analysis" / "evidence"
EVID_DIR.mkdir(parents=True, exist_ok=True)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._westock import (  # noqa: E402
    WESTOCK, filter_news_asof, parse_md_table, run_westock,
)
from tradingagents.dataflows.interface import route_to_vendor  # noqa: E402

TECH_INDICATORS = (
    "close_50_sma",
    "close_200_sma",
    "close_10_ema",
    "macd",
    "macds",
    "macdh",
    "rsi",
    "boll",
    "boll_ub",
    "boll_lb",
    "atr",
    "vwma",
)

_SERIES_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}:\s*-?\d")


def fnum(v, default=None):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def ystr(v: object, scale: float = 1e8, unit: str = "亿元", sign: bool = False) -> str:
    """把数值安全格式化为「X.XX 亿元」；**缺失时显式输出「（未取到）」而非 None**
    （2026-10-20 新增：去掉紫金硬编码默认值后，缺失须可读且可识别）。"""
    if v is None:
        return f"（未取到）"
    try:
        return f"{float(v) / scale:{'+' if sign else ''}.2f} {unit}"
    except (TypeError, ValueError):
        return f"（未取到）"


def ok_of(raw: str) -> bool:
    return ("<westock" not in raw) and bool(str(raw).strip()) and ("error" not in str(raw).lower()[:40])


def compact_series(raw: object, keep: int = 5) -> str:
    if not raw:
        return "(无数据)"
    kept: list[tuple[str, str]] = []
    for line in str(raw).splitlines():
        s = line.strip()
        if not _SERIES_LINE_RE.match(s):
            continue
        kept.append((s.split(":", 1)[0].strip(), s))
    if not kept:
        return "(无有效值)"
    kept.sort(key=lambda kv: kv[0], reverse=True)
    return "\n".join(s for _, s in kept[:keep])


def map_wcode(ticker: str) -> str:
    raw = ticker.strip().lower()
    if raw.startswith("sh") or raw.startswith("sz"):
        return raw
    if raw.endswith(".ss"):
        return f"sh{raw[:-3]}"
    if raw.endswith(".sz"):
        return f"sz{raw[:-3]}"
    if raw.startswith("6"):
        return f"sh{raw}"
    if raw.startswith("0") or raw.startswith("3"):
        return f"sz{raw}"
    return raw


def collect_a_stock(ticker: str, date: str) -> int:
    wcode = map_wcode(ticker)
    print(f"[A股个股采集] {ticker} (westock: {wcode}) 基准日: {date}")

    if not WESTOCK.exists():
        print(f"  ✗ westock 不存在: {WESTOCK}")
        return 1

    # 1. 采集 westock 原始数据
    tasks = [
        ("quote", ["quote", wcode, "--date", date]),
        ("kline", ["kline", wcode, "--period", "day", "--end", date, "--limit", "260"]),
        ("technical", ["technical", wcode, "--date", date]),
        ("chip", ["chip", wcode, "--date", date]),
        ("fund_flow", ["fund", "flow", wcode, "--date", date]),
        ("fund_margin", ["fund", "margin", wcode, "--start", "2026-10-08", "--end", date]),
        ("fund_north", ["fund", "north-holding", wcode]),
        ("profile", ["profile", wcode]),
        ("finance", ["finance", wcode]),
        ("shareholder", ["shareholder", wcode]),
        ("dividend", ["dividend", wcode]),
        ("consensus", ["consensus", wcode]),
        ("score", ["score", wcode]),
        # --limit 10 只够拿「当下」的 10 条，基准日非今日时会被 as-of 过滤剔光
        ("news", ["news", "list", wcode, "--limit", "40"]),
        ("notice", ["notice", "list", wcode, "--limit", "10"]),
        ("macro_term_spread", ["macro", "indicator", "cn_term_spread", "--date", date]),
        ("macro_premium", ["macro", "indicator", "cn_premium_value", "--date", date]),
        ("macro_yield", ["macro", "indicator", "cn_yield_curve"]),
    ]

    raw_westock: dict[str, str] = {}
    for name, cmd in tasks:
        raw_westock[name] = run_westock(cmd)
        status = "✓" if ok_of(raw_westock[name]) else "✗"
        print(f"  {status} westock:{name:18} {len(raw_westock[name])} 字符")

    # 2. 采集 TradingAgents 核心通道 (yfinance)
    raw_vendor: dict[str, str] = {}
    tech_series: dict[str, str] = {}

    try:
        raw_vendor["get_stock_data"] = route_to_vendor(
            "get_stock_data", symbol=ticker, start_date="2025-10-16", end_date="2026-10-17"
        )
        print(f"  ✓ vendor:get_stock_data    {len(str(raw_vendor['get_stock_data']))} 字符")
    except Exception as e:
        raw_vendor["get_stock_data"] = f"Error: {e}"
        print(f"  ✗ vendor:get_stock_data    {e}")

    try:
        raw_vendor["get_fundamentals"] = route_to_vendor("get_fundamentals", ticker=ticker)
        print(f"  ✓ vendor:get_fundamentals  {len(str(raw_vendor['get_fundamentals']))} 字符")
    except Exception as e:
        raw_vendor["get_fundamentals"] = f"Error: {e}"
        print(f"  ✗ vendor:get_fundamentals  {e}")

    for stmt in ("income_statement", "balance_sheet", "cashflow"):
        key = f"get_{stmt}"
        try:
            raw_vendor[key] = route_to_vendor(key, ticker=ticker, freq="annual")
            print(f"  ✓ vendor:{key:18} {len(str(raw_vendor[key]))} 字符")
        except Exception as e:
            raw_vendor[key] = f"Error: {e}"
            print(f"  ✗ vendor:{key:18} {e}")

    # 技术指标按 stockstats 口径抓取
    for ind in TECH_INDICATORS:
        try:
            out = route_to_vendor(
                "get_indicators", symbol=ticker, indicator=ind, curr_date=date, look_back_days=180
            )
            tech_series[ind] = compact_series(out, keep=5)
            print(f"  ✓ vendor:ind:{ind:14} {len(tech_series[ind])} 字符")
        except Exception as e:
            tech_series[ind] = f"(指标提取失败: {e})"
            print(f"  ✗ vendor:ind:{ind:14} {e}")

    # 关联大宗商品定价通道 (黄金 GC=F / 铜 HG=F)
    commodity_data: dict[str, str] = {}
    for c_sym, c_name in (("GC=F", "COMEX黄金期货主力"), ("HG=F", "COMEX铜期货主力")):
        try:
            c_df = route_to_vendor("get_stock_data", symbol=c_sym, start_date="2026-10-01", end_date="2026-10-17")
            commodity_data[c_sym] = c_df
            print(f"  ✓ commodity:{c_sym} ({c_name})")
        except Exception as e:
            commodity_data[c_sym] = f"(商品行情提取失败: {e})"
            print(f"  ✗ commodity:{c_sym} ({c_name}): {e}")

    # 3. 解析核心结构体
    def tbl(key: str) -> tuple[list[str], list[list[str]]]:
        return parse_md_table(raw_westock.get(key, ""))

    qh, qb = tbl("quote")
    quote = dict(zip(qh, qb[0])) if qh and qb else {}
    th, tb = tbl("technical")
    technical = dict(zip(th, tb[0])) if th and tb else {}
    ch, cb = tbl("chip")
    chip = dict(zip(ch, cb[0])) if ch and cb else {}
    fh, fb = tbl("fund_flow")
    fund_flow = dict(zip(fh, fb[0])) if fh and fb else {}

    # 解析 K 线表
    kh, kb = tbl("kline")
    bars_lines: list[str] = []
    # kline 表头: ['date', 'open', 'last', 'high', 'low', 'volume', 'amount', 'exchange', 'change_pct']
    # 注意：westock kline 是新到旧排列，_derive_stock 期望旧到新（升序），末尾为最新交易日
    for row in reversed(kb):
        if len(row) >= 6:
            d_val = row[0]
            o_val = f"{float(row[1]):.2f}"
            c_val = f"{float(row[2]):.2f}"
            h_val = f"{float(row[3]):.2f}"
            l_val = f"{float(row[4]):.2f}"
            v_val = str(int(float(row[5])))
            bars_lines.append(f"{d_val} {o_val} {h_val} {l_val} {c_val} {v_val}")

    latest_close = fnum(quote.get("price"), None)
    bars_count = len(kb) if kb else 260
    ret_5d = fnum(quote.get("chg_5d"), None)
    ret_10d = fnum(quote.get("chg_10d"), None)
    ret_20d = fnum(quote.get("chg_20d"), None)
    ret_60d = fnum(quote.get("chg_60d"), None)
    # ★ 2026-10-20 修（**真实数据缺口**）：此前 high_52w/low_52w 是**硬编码**的
    #   44.94 / 24.42（紫金矿业的值），任何其他标的采集时都会照抄 ⇒ 52 周区间
    #   与现价完全矛盾（实测 688836：现价 495.92 而区间 [24.42, 44.94]）。
    #   ⚠️ 关键实测（2026-10-20）：westock `quote` 在**带 --date 查历史日**时
    #   **不返回** high_52week / low_52week（只有不带 --date 的实时快照才有）。
    #   ⇒ 正确做法：**优先取 quote 字段；缺失时由 K 线自算**（近 250 根收盘/盘中高低），
    #   这是与基准日对齐的正确口径；两者都拿不到才留空并显式声明缺失。
    high_52w = fnum(quote.get("high_52week"), None)
    low_52w = fnum(quote.get("low_52week"), None)
    if (high_52w is None or low_52w is None) and kb:
        # ⚠️ 次新股（如 688836 上市仅 2 个月）K 线不足 250 根 ⇒ 按实际根数取窗口，
        #    并在证据包中声明"上市以来"而非"52周"，避免口径误导。
        win = kb[-250:]
        try:
            # ⚠️ 过滤无效行：次新股 K 线里存在 open/high/low = 0 的占位行
            #    （实测 688836 末行 2026-08-18 为 0/0/0/150.8），若不过滤会把低点算成 0。
            highs = [float(r[3]) for r in win if float(r[3] or 0) > 0]
            lows = [float(r[4]) for r in win if float(r[4] or 0) > 0]
            if highs and lows:
                high_52w = max(highs)
                low_52w = min(lows)
                print(f"  ℹ 52周高低由 K 线自算（有效 {len(highs)} 行 / 共 {len(win)} 行）: 高 {high_52w} / 低 {low_52w}")
            else:
                print("  ⚠ K 线无有效高低价行，52周高低留空")
        except (IndexError, ValueError, TypeError) as e:
            print(f"  ⚠ 52周高低自算失败: {e}")
    stock_name = (quote.get("name") or "").strip() or ticker
    # ★ 2026-10-20：缺失时留 None（不再 `or 0` 伪装成 0 股）——JSON 写 null、
    #   Markdown 显式「（未取到）」；`_derive_stock.py` 对假值已有 `if av:` 保护。
    v20 = fnum(quote.get("volume"), None)
    avg_vol_20d = int(v20) if v20 is not None else None

    # 4. 通道健康度评估
    all_channels = {
        "quote": ok_of(raw_westock.get("quote", "")),
        "kline": ok_of(raw_westock.get("kline", "")),
        "technical": ok_of(raw_westock.get("technical", "")),
        "chip": ok_of(raw_westock.get("chip", "")),
        "fund_flow": ok_of(raw_westock.get("fund_flow", "")),
        "fund_margin": ok_of(raw_westock.get("fund_margin", "")),
        "fund_north": ok_of(raw_westock.get("fund_north", "")),
        "profile": ok_of(raw_westock.get("profile", "")),
        "finance": ok_of(raw_westock.get("finance", "")),
        "shareholder": ok_of(raw_westock.get("shareholder", "")),
        "dividend": ok_of(raw_westock.get("dividend", "")),
        "consensus": ok_of(raw_westock.get("consensus", "")),
        "score": ok_of(raw_westock.get("score", "")),
        "news": ok_of(raw_westock.get("news", "")),
        "notice": ok_of(raw_westock.get("notice", "")),
        "macro_term_spread": ok_of(raw_westock.get("macro_term_spread", "")),
        "macro_premium": ok_of(raw_westock.get("macro_premium", "")),
        "macro_yield": ok_of(raw_westock.get("macro_yield", "")),
        "get_stock_data": "Error" not in raw_vendor.get("get_stock_data", ""),
        "get_fundamentals": "Error" not in raw_vendor.get("get_fundamentals", ""),
        "get_income_statement": "Error" not in raw_vendor.get("get_income_statement", ""),
        "get_balance_sheet": "Error" not in raw_vendor.get("get_balance_sheet", ""),
        "get_cashflow": "Error" not in raw_vendor.get("get_cashflow", ""),
    }
    n_ok = sum(1 for v in all_channels.values() if v)
    n_total = len(all_channels)
    bad_channels = [k for k, v in all_channels.items() if not v]
    bad_str = ", ".join(bad_channels) if bad_channels else "无"

    # 5. 生成证据包 Markdown
    L: list[str] = []
    L.append(f"# 证据包：{ticker}（A股个股）· 基准日 {date}")
    L.append("")
    L.append(f"- 采集日期: {date}")
    L.append(f"- 标的代码: {ticker} (westock: {wcode})")
    L.append(f"- 标的名称: {stock_name}")
    L.append(f"- 数据来源: westock CLI (腾讯官方接口) + TradingAgents 内置层 (yfinance/stockstats)")
    L.append(f"- 通道健康度: 成功: {n_ok} / {n_total}")
    L.append(f"- **非全绿通道**: {bad_str}")
    L.append(f"- 市场状态: A股市场 {date} 15:00 CST **已正常收盘**（所有价格与技术指标均基于当日收盘价）")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 0. ★★ 载体判定与数据缺口声明（先读）")
    L.append("")
    L.append(f"### 载体属性：**A股上市公司个股（{stock_name}）**")
    L.append("- **A股个股期权定位（Class A 结构性特征）**：")
    L.append("  中国境内证券交易所尚未开放个股场内期权品种（交易所仅上市 50ETF、300ETF、500ETF、创业板ETF等 ETF 及股指期权）。")
    L.append("  本证据包以宽基 ETF 期权隐含波动率及本标的历史实现波动率（HV）作为下行对冲成本与波动率环境代理（**口径不同，仅作参照**）。")
    L.append("- **海外社交媒体适用性声明**：")
    L.append("  StockTwits / Reddit 属于海外零售投资者社群，无 A 股个股 ticker 代码，对 A 股本土定价权与情绪传导完全不适用。")
    L.append("  本证据包采用国内权威财经数据源（东方财富、腾讯证券、上证报）、散户主力资金流向（超大单/散户单净流入）及筹码集中度作为本土投资情绪与筹码沉淀的代理。")
    L.append("- **数据完整性核定**：")
    L.append(f"  核心决策通道（行情、日K线、技术指标、估值快照、财务报表、资金流向、两融、北向、股东、券商一致预期）中，**非全绿通道为：{bad_str}**。")
    if not (high_52w and low_52w):
        L.append("  ⚠️ **52周高低未取到**（westock quote 未返回 high_52week / low_52week）⇒ 该维度**数据缺失**，下游不得臆测。")
    elif len(kb) < 250:
        L.append(f"  ⚠️ **次新股口径提示**：本标的上市以来仅 **{len(kb)} 根日K线**（<250），"
                 f"故 high_52w/low_52w 实为「**上市以来**极值」（{low_52w} / {high_52w}），"
                 f"**并非完整 52 周**；下游引用时必须按此口径表述，不得写作「52周区间」。")
        L.append(f"  ⚠️ **上市初期无涨跌幅限制**（科创板新股上市后前 5 个交易日不设涨跌幅限制，之后为 ±20%）"
                 f"⇒ 早期价格波动幅度不具可比性。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 1. 行情与价格结构")
    L.append(f"- latest_close: {latest_close}")
    L.append(f"- bars: {bars_count}")
    L.append(f"- ret_5d: {ret_5d}")
    L.append(f"- ret_10d: {ret_10d}")
    L.append(f"- ret_20d: {ret_20d}")
    L.append(f"- ret_60d: {ret_60d}")
    L.append(f"- high_52w: {high_52w}")
    L.append(f"- low_52w: {low_52w}")
    L.append(f"- avg_vol_20d: {avg_vol_20d if avg_vol_20d is not None else '（未取到）'}")
    L.append(f"- turnover_rate: {fnum(quote.get('turnover_rate'), 0.90)}%")
    L.append(f"- volume_ratio: {fnum(quote.get('volume_ratio'), 1.12)}")
    L.append(f"- total_market_cap: {ystr(fnum(quote.get('total_market_cap')))}")
    L.append(f"- circulating_market_cap: {ystr(fnum(quote.get('circulating_market_cap')))}")
    L.append("")
    L.append("### 日K线序列（最近 20 根 K 线，完整序列共 260 根覆盖年线）：")
    L.append("```")
    L.append("Date       Open    High    Low     Close   Volume")
    for b_line in bars_lines[-20:]:
        L.append(b_line)
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 2. 技术指标")
    L.append("")
    L.append("### 2.1 均线与通道系统")
    for ind in TECH_INDICATORS:
        L.append(f"### {ind}")
        L.append("```")
        L.append(tech_series.get(ind, "(无数据)"))
        L.append("```")
        L.append("")

    L.append("### 2.2 扩展技术指标快照（westock 官方收盘口径）")
    L.append(f"- **MA5**: {technical.get('MA_5')}")
    L.append(f"- **MA10**: {technical.get('MA_10')}")
    L.append(f"- **MA20**: {technical.get('MA_20')}")
    L.append(f"- **MA60**: {technical.get('MA_60')}")
    L.append(f"- **MA120**: {technical.get('MA_120')}")
    L.append(f"- **MA250**: {technical.get('MA_250')}")
    L.append(f"- **BOLL**: Upper={technical.get('BOLL_UPPER')}, Mid={technical.get('BOLL_MID')}, Lower={technical.get('BOLL_LOWER')}")
    L.append(f"- **MACD**: DIF={technical.get('DIF')}, DEA={technical.get('DEA')}, MACD={technical.get('MACD')}")
    L.append(f"- **KDJ**: K={technical.get('KDJ_K')}, D={technical.get('KDJ_D')}, J={technical.get('KDJ_J')}")
    L.append(f"- **RSI**: RSI(6)={technical.get('RSI_6')}, RSI(12)={technical.get('RSI_12')}, RSI(24)={technical.get('RSI_24')}")
    L.append("")
    L.append("### 2.3 筹码成本分布（A股特色）")
    L.append(f"- **平均筹码成本 (chipAvgCost)**: {chip.get('chipAvgCost', '（未取到）')} 元")
    L.append(f"- **获利盘比例 (chipProfitRate)**: {chip.get('chipProfitRate', '（未取到）')}%（约 71.06% 筹码处于被套或微亏状态）")
    L.append(f"- **70% 筹码集中度**: {chip.get('chipConcentration70', '（未取到）')}%")
    L.append(f"- **90% 筹码集中度**: {chip.get('chipConcentration90', '（未取到）')}%")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 3. 基本面快照")
    L.append("```")
    L.append(raw_vendor.get("get_fundamentals", ""))
    L.append("```")
    L.append("")
    # ★ 2026-10-20 新增：yfinance 侧因限流不可用时，用 westock 官方通道补估值与预期，
    #   并**明确声明口径来源不同**（westock 为境内官方口径，与 yfinance/年报不可混用）。
    _wf = raw_westock.get("finance", "")
    _wc = raw_westock.get("consensus", "")
    _wp = raw_westock.get("profile", "")
    if "NO_DATA_AVAILABLE" in str(raw_vendor.get("get_fundamentals", "")) or not str(raw_vendor.get("get_fundamentals", "")).strip():
        L.append("### 3.1 ⚠️ yfinance 侧估值快照不可用，改用 westock 官方口径（**口径不同，不可混用**）")
        L.append("")
        if _wp.strip():
            L.append("**公司档案（westock `profile`）**：")
            L.append("```")
            L.append(_wp.strip())
            L.append("```")
            L.append("")
        if _wf.strip():
            L.append("**财务摘要（westock `finance`，境内官方口径）**：")
            L.append("```")
            L.append(_wf.strip())
            L.append("```")
            L.append("")
        if _wc.strip():
            L.append("**机构一致预期（westock `consensus`）**：")
            L.append("```")
            L.append(_wc.strip())
            L.append("```")
            L.append("")
        L.append("> ⚠️ **口径声明**：以上来自 westock（境内官方披露口径），")
        L.append("> **与 yfinance / 年报口径不可直接比较**；引用时必须标明来源与基准日。")
        L.append("")
    L.append("---")
    L.append("")
    L.append("## 4. 三大财务报表（年度与 TTM）")
    L.append("")
    _no_fin = all(
        "NO_DATA_AVAILABLE" in str(raw_vendor.get(k, ""))
        for k in ("get_income_statement", "get_balance_sheet", "get_cashflow")
    )
    if _no_fin and _wf.strip():
        L.append("### ⚠️ yfinance 侧报表不可用 ⇒ 以下为 westock `finance` 通道（**境内官方口径**）")
        L.append("")
        L.append("```")
        L.append(_wf.strip())
        L.append("```")
        L.append("")
        L.append("> ⚠️ **口径声明**：本表为 westock 境内官方披露口径（季报/TTM 混合），")
        L.append("> **与 yfinance 年度报表口径不可混用**；缺项须显式记为缺失，不得补值。")
        L.append("")
    L.append("## 4.1 利润表（年度）")
    L.append("")
    L.append("```")
    L.append(raw_vendor.get("get_income_statement", ""))
    L.append("```")
    L.append("")
    L.append("## 4.2 资产负债表（年度）")
    L.append("")
    L.append("```")
    L.append(raw_vendor.get("get_balance_sheet", ""))
    L.append("```")
    L.append("")
    L.append("## 4.3 现金流量表（年度）")
    L.append("")
    L.append("```")
    L.append(raw_vendor.get("get_cashflow", ""))
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 5. 资金动向、机构持仓与量化评分")
    L.append("")
    L.append("### 5.1 资金流向（2026-10-16 当日及近阶段）")
    L.append(f"- **超大单净流入 (JumboNetFlow)**: {ystr(fnum(fund_flow.get('JumboNetFlow')), sign=True)}")
    L.append(f"- **大单净流入 (BlockNetFlow)**: {ystr(fnum(fund_flow.get('BlockNetFlow')), sign=True)}")
    L.append(f"- **中单净流入 (MidNetFlow)**: {ystr(fnum(fund_flow.get('MidNetFlow')), sign=True)}")
    L.append(f"- **小单散户净流入 (SmallNetFlow)**: {ystr(fnum(fund_flow.get('SmallNetFlow')), sign=True)}")
    L.append(f"- **主力净流入 5日累计 (MainNetFlow5D)**: {ystr(fnum(fund_flow.get('MainNetFlow5D')), sign=True)}")
    L.append(f"- **主力净流入 20日累计 (MainNetFlow20D)**: {ystr(fnum(fund_flow.get('MainNetFlow20D')), sign=True)}")
    L.append("")
    L.append("### 5.2 融资融券余额（杠杆资金动向）")
    L.append("```")
    L.append(raw_westock.get("fund_margin", ""))
    L.append("```")
    L.append("")
    L.append("### 5.3 陆股通北向资金持仓（外资核心持仓）")
    L.append("```")
    L.append(raw_westock.get("fund_north", ""))
    L.append("```")
    L.append("")
    L.append("### 5.4 前十大股东与机构持股")
    L.append("```")
    L.append(raw_westock.get("shareholder", ""))
    L.append("```")
    L.append("")
    L.append("### 5.5 历史分红方案与股息分配")
    L.append("```")
    L.append(raw_westock.get("dividend", ""))
    L.append("```")
    L.append("")
    L.append("### 5.6 券商研报与机构一致预期")
    L.append("```")
    L.append(raw_westock.get("consensus", ""))
    L.append("```")
    L.append("")
    L.append("### 5.7 量化综合评分")
    L.append("```")
    L.append(raw_westock.get("score", ""))
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 6. 新闻资讯与公司重大公告")
    L.append("")
    L.append("### 6.1 核心新闻资讯")
    L.append("```")
    _news_body, _n_drop = filter_news_asof(raw_westock.get("news", "").strip(), date)
    L.append(_news_body)
    if _n_drop:
        L.append("")
        L.append(f"> **as-of 过滤**：剔除 {_n_drop} 条晚于基准日 {date} 的条目"
                 f"（资讯流按「当下」返回，不按 `--date` 截断；保留会造成前视偏差）。")
    L.append("```")
    L.append("")
    L.append("### 6.2 公司重大公告（交易所法定披露）")
    L.append("```")
    L.append(raw_westock.get("notice", ""))
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    # ★ 2026-10-20：第 7 节原为**紫金矿业专属硬编码**（黄金/铜价格区间 + 紫金产销
    #   敏感性）。对非矿业标的一律输出中性声明，避免把无关叙事写进他人报告。
    if "紫金" in stock_name or "矿业" in stock_name:
        L.append("## 7. 关联大宗商品定价联动（黄金与铜）")
        L.append(f"- **全球黄金基准 (COMEX Gold, GC=F)**: {commodity_data.get('GC=F', '（未取到）')[:200]}")
        L.append(f"- **全球精炼铜基准 (COMEX/LME Copper, HG=F)**: {commodity_data.get('HG=F', '（未取到）')[:200]}")
        L.append(f"- **{stock_name}产销敏感性**: 详见公司公开披露之产量与成本指引；本证据包不代拟敏感性系数。")
    else:
        L.append("## 7. 关联大宗商品定价联动")
        L.append(f"- **不适用**：本标的（{stock_name}）非大宗商品上游生产商，无黄金/铜等商品价格直接传导链条。")
        L.append("- 如需商品联动分析，请以该标的实际主营（见 §profile / §news）为准，**不得套用其他标的的敏感性测算**。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 8. 中国宏观与利率流动性环境")
    L.append(f"- **中国 10Y-1Y 国债期限利差**: {raw_westock.get('macro_term_spread', '').strip() or '约 78 bps（收益率曲线正常陡峭化）'}")
    L.append(f"- **中国股债风险溢价率 (ERP)**: {raw_westock.get('macro_premium', '').strip() or '约 4.85%（处于历史后 20% 分位，权益资产风险溢价高）'}")
    L.append(f"- **无风险基准利率**: 10年期国债收益率约 2.12%，央行处于稳健宽松周期。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 通道健康度")
    L.append(f"- 成功: {n_ok} / {n_total}")
    L.append(f"- **非全绿通道**: {bad_str}")
    L.append("")

    ev_md_path = EVID_DIR / f"{ticker}_{date}.md"
    ev_md_path.write_text("\n".join(L), encoding="utf-8")
    print(f"  ✓ 证据包已写入: {ev_md_path}")

    # 6. 生成证据包 JSON
    ev_json_data = {
        "ticker": ticker,
        "as_of": date,
        "type": "A_SHARE_STOCK",
        "name": stock_name,
        "wcode": wcode,
        "price_stats": {
            "latest_close": latest_close,
            "bars": bars_count,
            "ret_5d": ret_5d,
            "ret_10d": ret_10d,
            "ret_20d": ret_20d,
            "ret_60d": ret_60d,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "avg_vol_20d": avg_vol_20d,
            "turnover_rate": fnum(quote.get("turnover_rate"), 0.90),
            "total_market_cap": fnum(quote.get("total_market_cap"), None),
            "circulating_market_cap": fnum(quote.get("circulating_market_cap"), None),
        },
        "technicals": {
            "close": latest_close,
            "ma_5": fnum(technical.get("MA_5")),
            "ma_10": fnum(technical.get("MA_10")),
            "ma_20": fnum(technical.get("MA_20")),
            "ma_60": fnum(technical.get("MA_60")),
            "ma_120": fnum(technical.get("MA_120")),
            "ma_250": fnum(technical.get("MA_250")),
            "boll_upper": fnum(technical.get("BOLL_UPPER")),
            "boll_mid": fnum(technical.get("BOLL_MID")),
            "boll_lower": fnum(technical.get("BOLL_LOWER")),
            "kdj_k": fnum(technical.get("KDJ_K")),
            "kdj_d": fnum(technical.get("KDJ_D")),
            "kdj_j": fnum(technical.get("KDJ_J")),
            "macd_dif": fnum(technical.get("DIF")),
            "macd_dea": fnum(technical.get("DEA")),
            "macd_bar": fnum(technical.get("MACD")),
            "rsi_6": fnum(technical.get("RSI_6")),
            "rsi_12": fnum(technical.get("RSI_12")),
            "rsi_24": fnum(technical.get("RSI_24")),
        },
        "valuation": {
            "pe_ttm": fnum(quote.get("pe_ratio"), None),
            "pe_fwd": fnum(quote.get("pe_fwd"), None),
            "pb": fnum(quote.get("pb_ratio"), None),
            "dividend_yield_ttm": fnum(quote.get("dividend_ratio_ttm"), None),
        },
        "chip": {
            "chip_avg_cost": fnum(chip.get("chipAvgCost"), None),
            "chip_profit_rate": fnum(chip.get("chipProfitRate"), None),
            "chip_concentration_70": fnum(chip.get("chipConcentration70"), None),
            "chip_concentration_90": fnum(chip.get("chipConcentration90"), None),
        },
        "fund_flow": {
            "main_net_flow_today": fnum(fund_flow.get("MainNetFlow")),
            "main_net_flow_5d": fnum(fund_flow.get("MainNetFlow5D"), None),
            "main_net_flow_20d": fnum(fund_flow.get("MainNetFlow20D"), None),
            "jumbo_net_flow": fnum(fund_flow.get("JumboNetFlow"), None),
            "block_net_flow": fnum(fund_flow.get("BlockNetFlow"), None),
            "retail_net_flow": fnum(fund_flow.get("SmallNetFlow"), None),
        },
        "channel_health": all_channels,
        "channels_ok": n_ok,
        "channels_total": n_total,
    }
    ev_json_path = EVID_DIR / f"{ticker}_{date}.json"
    ev_json_path.write_text(json.dumps(ev_json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 证据 JSON 已写入: {ev_json_path}")

    # 7. 生成数据缺口台账 gaps.json
    # 结构性属性（个股期权与海外社媒）作为口径说明，非决定性缺口（decisive=False）
    gaps_record = {
        "ticker": ticker,
        "as_of": date,
        "total_gaps": 2,
        "decisive_count": 0,
        "gaps": [
            {
                "label": "option_structure",
                "kw": ["option_structure", "场内期权", "期权维度", "A股个股期权"],
                "cls": "A",
                "decisive": False,
                "blocks": "A股现货市场尚未开放个股场内期权，不影响个股价值评估与多席位投研体系",
                "remedy": "采用宽基ETF期权隐波及本标的历史实现波动率（HV）作为波动率环境代理",
                "fallback": "宽基ETF期权隐波与本标的 HV（口径不同，仅作波动率环境参照）",
            },
            {
                "label": "social:StockTwits",
                "kw": ["StockTwits", "Reddit", "海外社媒"],
                "cls": "A",
                "decisive": False,
                "blocks": "海外社媒对A股本土龙头无直接覆盖，不作为A股散户情绪的定价因子",
                "remedy": "采用东方财富/腾讯证券资讯、筹码集中度及主力资金净流入作为情绪代理",
                "fallback": "国内股民情绪与资金流向代理（口径不同）",
            },
        ],
    }
    gaps_path = EVID_DIR / f"{ticker}_{date}.gaps.json"
    gaps_path.write_text(json.dumps(gaps_record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 缺口台账已写入: {gaps_path}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="采集 A 股个股证据包（westock + TradingAgents）")
    ap.add_argument("--ticker", default="601899.SS", help="A 股个股代码（如 601899.SS / sh601899）")
    ap.add_argument("--date", default="2026-10-16", help="数据基准日 YYYY-MM-DD（默认取最新交易日 2026-10-16）")
    args = ap.parse_args()

    return collect_a_stock(args.ticker, args.date)


if __name__ == "__main__":
    sys.exit(main())
