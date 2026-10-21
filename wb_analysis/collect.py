# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/collect.py
"""免费证据采集器 —— 全程不调用任何 LLM。

复用 ``tradingagents.dataflows.interface.route_to_vendor`` 把 TradingAgents
喂给 12 个智能体的**全部数据通道**独立拉取出来，压成一份结构化证据包。
数据部分零 API 成本，推理部分交给分析层（多智能体 / 顶层模型协同）完成，
从而把原系统里最贵的 LLM 调用段整段省掉。

用法：
    python wb_analysis/collect.py NVDA AMD
    python wb_analysis/collect.py NVDA --lookback 180
    python wb_analysis/collect.py NVDA --no-news

产物：
    wb_analysis/evidence/<TICKER>_<YYYY-MM-DD>.md    证据包（供人/模型阅读）
    wb_analysis/evidence/<TICKER>_<YYYY-MM-DD>.json  通道健康度与关键数值
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import math
import os
import re
import sys
import time
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# ★ 2026-10-15：移除模块级 os.chdir(PROJECT_ROOT)，改为在 main() 入口执行，消除 import 副作用

from dotenv import load_dotenv
from wb_analysis import _clock

load_dotenv(PROJECT_ROOT / ".env")

EV_DIR = PROJECT_ROOT / "wb_analysis" / "evidence"
ANALYSIS_DIR = PROJECT_ROOT / "wb_analysis" / "analysis"

# market_analyst 提示词里列出的有效指标名（stockstats 口径）
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

# 三大报表要保留的**关键行**（精确行名，按重要性排序）。
# 数据源返回的报表有 50~80 行且行序与重要性无关，必须按此表抽取，
# 否则会像修复前那样把 Total Revenue / Total Assets 全部截掉。详见 _compact_statement。
_STATEMENT_PRIORITY: dict[str, tuple[str, ...]] = {
    "income": (
        "Total Revenue", "Operating Revenue", "Cost Of Revenue", "Gross Profit",
        "Research And Development", "Selling General And Administration",
        "Selling And Marketing Expense", "General And Administrative Expense",
        "Operating Expense", "Operating Income", "Total Operating Income As Reported",
        "Net Non Operating Interest Income Expense", "Interest Expense",
        "Other Income Expense", "Pretax Income", "Tax Provision",
        "Net Income", "Net Income Common Stockholders",
        "Net Income Continuous Operations", "Net Income From Continuing Operation Net Minority Interest",
        "Diluted EPS", "Basic EPS", "Diluted Average Shares", "Basic Average Shares",
        "EBITDA", "EBIT", "Normalized EBITDA", "Reconciled Depreciation",
        "Total Unusual Items", "Tax Rate For Calcs",
    ),
    "balance": (
        "Total Assets", "Current Assets", "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments", "Accounts Receivable",
        "Inventory", "Other Current Assets", "Total Non Current Assets",
        "Net PPE", "Gross PPE", "Construction In Progress",
        "Goodwill", "Goodwill And Other Intangible Assets",
        "Investments And Advances", "Investmentin Financial Assets",
        "Total Liabilities Net Minority Interest", "Current Liabilities",
        "Total Non Current Liabilities Net Minority Interest",
        "Accounts Payable", "Payables And Accrued Expenses",
        "Current Debt And Capital Lease Obligation", "Long Term Debt And Capital Lease Obligation",
        "Long Term Debt", "Total Debt", "Net Debt",
        "Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest",
        "Retained Earnings", "Working Capital", "Tangible Book Value",
        "Share Issued", "Ordinary Shares Number",
    ),
    "cashflow": (
        "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
        "Capital Expenditure", "Free Cash Flow",
        "Net Income From Continuing Operations", "Depreciation And Amortization",
        "Change In Working Capital", "Stock Based Compensation",
        "Investing Cash Flow", "Financing Cash Flow",
        "Repurchase Of Capital Stock", "Cash Dividends Paid",
        "Issuance Of Debt", "Repayment Of Debt",
        "Changes In Cash", "End Cash Position", "Beginning Cash Position",
    ),
}

# 默认跟踪的宏观指标别名（FRED），缺 FRED_API_KEY 时会整体降级
MACRO_ALIASES = (
    "fed_funds_rate",
    "10y_treasury",
    "cpi",
    "unemployment",
    "vix",
)

# 默认跟踪的预测市场命题（Polymarket，免密钥）
PREDICTION_TOPICS = (
    "Fed rate cut",
    "US recession",
)

_INDICATOR_LOOKBACK = 10

#: 走网络的数据通道的**默认重试次数**（`_safe_call` 的退避 = 1.5×(n+1) 秒）。
#:
#: ★★ 2026-10-11 新增。起因：NFLX 采集时 yfinance **整片 403**，35 通道险些全废。
#: 归因结论（实测，务必别再误判）：
#:   · 本机出网走 v2rayN 代理（**Tun 模式** ⇒ 改 `NO_PROXY`/直连都没用，出口 IP 不变）；
#:   · **代理节点会间歇性抽风**，不是 Yahoo 对 IP 的永久封禁 ——
#:     同一 URL 连打：第 1 次 `HTTP 403`、第 2 次 `HTTP 200`；
#:     `query1/query2/finance.yahoo.com` 首页三者同时 403；
#:     同一时段 Nasdaq 官方端点先 200、几分钟后 `502 Bad Gateway`。
#:   · ⇒ 判据是「**重试能否穿透**」，而不是「换个 UA 或换台主机」。
#: 原实现只给 FRED 传了 `retries=2`，其余 yfinance 通道全 `retries=0` ——
#: **一次抖动就静默丢掉一个通道**，整包从 35/35 掉成 N/35，
#: 而汇总只写「非全绿通道: get_stock_data=fail」，看起来像上游真缺数据（假缺口）。
#: ⇒ 凡走网络的通道一律给足重试；这是**单一口径**，不要再在调用点各写各的数字。
_NET_RETRIES: int = 3

# 通道「优雅降级」时写进证据包的占位串（大小写不敏感匹配）。
# 被 ``_safe_call`` 用于把「返回了占位串的通道」判为 unavailable 而非 ok —— 见其文档。
_PLACEHOLDER_MARKERS = (
    "<stocktwits unavailable",
    "<reddit unavailable",
    "<unavailable",
    "this is not an absence of posts",
    # ⚠️ 2026-10-08 新增（GOOG 轮实测）：**「内容为空」也是失败**。
    #    新闻通道按设计不抛异常，拿不到内容时返回人类可读的空态串。
    #    原实现只认占位串前缀 ⇒ `No news found for GOOG` 被记为 **ok**，
    #    健康度照报「32 / 35 成功」，但 §5 实际整节为空。
    #    这与 2026-09-17 修 StockTwits 假绿是**同一类漏洞的不同面**：
    #    那次是「失败返回占位串」，这次是「失败返回自然语言空态」。
    #    ⚠️ 匹配串必须**足够长**以避免误伤真数据（例如真有标题含 "no global news"）。
    "no news found for",
    "no global news found",
)
# 注意：正文回填后宏观新闻可能个别条目仍只有标题，这不影响该通道判 ok ——
# 只要**至少有一条**内容，就该算成功。故这里只匹配「整段为空」的空态串。

# 只认「YYYY-MM-DD: 数值」形式的真数据行。排除两类噪声：
# 休市日的 ``N/A: Not a trading day``，以及尾部的指标说明提示词。
_SERIES_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}:\s*-?\d")


def _get_router():
    """延迟导入，避免无关调用时的加载开销与循环导入。"""
    from tradingagents.dataflows.interface import route_to_vendor

    return route_to_vendor


def _compact_series(raw: object, keep: int = 5) -> str:
    """把指标输出压成「最近 keep 个有效值」。

    原始输出混杂两类噪声：每个休市日一行 ``N/A: Not a trading day``，
    以及尾部附带的一段指标说明文字（那是给 LLM 的提示词，不是数据）。
    这里只保留形如 ``YYYY-MM-DD: 数值`` 的真数据行。

    ⚠️ **顺序陷阱（2026-09-16 定位并修复）**

    ``get_indicators`` 的输出是 **新 → 旧** 排列（标题行
    ``## close_50_sma values from A to B`` 之后的**第一行就是最新交易日**）。
    原实现直接 ``kept[-keep:]`` 取列表尾部，等于取走了窗口里**最旧**的 5 个交易日，
    把最新值（以及倒数第二新值）丢在 keep 之外。

    后果极具迷惑性：证据包里**所有**技术指标都比价格序列晚一个交易日，
    看起来就像「stockstats 只用已完成 K 线」的固有行为，因而长期未被怀疑。
    实测（``^NDX``，基准日 2026-09-16）：接口对 2026-09-15 明明有
    ``close_50_sma = 29178.31``，而证据包只收录到 2026-09-14 的 29193.51。

    现改为**按日期显式降序后取前 keep 个**，与来源的物理排序解耦；
    无论上游改为升序还是降序，取到的都是最近若干个交易日。
    """
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

    # --- ★ 未收盘 bar 剔除（2026-09-17 新增）---
    # 盘中采集时，``get_indicators`` 会为**当天尚未收盘的 bar** 也算一个指标值。
    # 该值基于盘中瞬时价，与收盘口径不可比。实测（^NDX 2026-09-17 盘中）：
    #   RSI   44.02（9/16 收盘） → 52.30（9/17 盘中，未收盘）
    #   ATR   376.16            → 382.79
    #   50SMA 29173.75          → 29176.87
    # 一个未收盘 bar 就能把「中性偏弱」改写成「中性偏强」，足以改变分析结论。
    #
    # 判据：末根值所属日期 == 今天（美东日期），且今天尚未收盘（美东 < 16:00）。
    # 因本函数只拿到序列本身、拿不到成交量，故用**日期判定**而非量能判定；
    # 价格侧的严格量能判据见 ``_price_summary``。二者互为补充。
    try:
        import zoneinfo
        _now_ny = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        _today_ny = _now_ny.date().isoformat()
        _closed = (_now_ny.hour + _now_ny.minute / 60.0) >= 16.0
        if kept and kept[0][0] == _today_ny and not _closed:
            dropped_date = kept[0][0]
            kept = kept[1:]
            if kept:
                return ("\n".join(s for _, s in kept[:keep])
                        + f"\n⚠ 已剔除未收盘 bar（{dropped_date}，美东尚未收盘）")
    except Exception:  # noqa: BLE001
        pass

    return "\n".join(s for _, s in kept[:keep])


def _compact_statement(raw: object, key: str, max_rows: int = 34) -> str:
    """保留报表表头 + **关键行**（按重要度排序），而不是盲截前 N 行。

    ⚠️ **盲截是个严重的坑（2026-09-16 定位并修复）**

    ``get_income_statement`` / ``get_balance_sheet`` / ``get_cashflow`` 返回的是 CSV，
    **行序由数据源决定，与重要性无关**。原实现 ``splitlines()[:22]`` 恰好把最关键的
    条目全部切掉。实测 GOOG（2026-09-16）：

    | 报表 | 总行数 | 关键行所在位置 | 原实现是否保留 |
    |---|---|---|---|
    | 利润表 | 51 | **Total Revenue 在第 50 行**、Gross Profit 第 48、Operating Income 第 41、Diluted EPS 第 24 | ❌ 全部丢失 |
    | 资产负债表 | 79 | **Total Assets 在第 48 行**、Current Assets 第 69 | ❌ 全部丢失 |
    | 现金流量表 | — | Operating Cash Flow / Capex 同样靠后 | ❌ 部分丢失 |

    ⇒ 基本面分析师拿到的是一份**没有营收、没有毛利、没有营业利润、没有总资产**的
    「三大报表」。现改为按预设优先级精确抽取关键行；命中不足时用原顺序补齐。

    说明：本函数按行名**精确匹配**（非前缀），因为报表里存在
    ``Total Debt`` 与 ``Total Debt And Capital Lease Obligation`` 这类高度相似的条目。
    """
    if not raw:
        return "(无数据)"
    lines = [ln.rstrip("\n") for ln in str(raw).splitlines()]
    if not lines:
        return "(无数据)"

    want = _STATEMENT_PRIORITY.get(key, ())
    # 前 4 行是「标题 / 取数时间 / 空行 / 期间表头」，必须原样保留
    preamble: list[str] = []
    body: list[str] = []
    for ln in lines:
        if not body and (ln.startswith("#") or not ln.strip() or ln.lstrip().startswith(",")):
            preamble.append(ln)
        else:
            body.append(ln)
    if not preamble and body:  # 报文格式变化时的兜底
        preamble, body = body[:1], body[1:]

    by_name = {ln.split(",", 1)[0].strip(): ln for ln in body}
    picked = [by_name[n] for n in want if n in by_name]
    truncated = 0
    if len(picked) < 8:  # 优先级表未命中（数据源改名）→ 退回原顺序
        if len(body) > max_rows:
            truncated = len(body) - max_rows
        picked = body[:max_rows]
    else:
        if len(picked) > max_rows:
            truncated = len(picked) - max_rows
        picked = picked[:max_rows]

    out = "\n".join(preamble + picked)
    # ★ 2026-10-08：截断**必须在输出内声明**（同类事故见 `_derive_stock.py` 内部人一节 ——
    #   那里静默只打印前 22 行，被当成完整事实，导致内部人笔数写错 22 倍）。
    #   不加这行 ⇒ 下游无法区分「报表就这么短」与「被我们切短了」。
    if truncated:
        out += f"\n# ... [TRUNCATED: 本节另有 {truncated} 行未显示；完整报表见证据包原始返回]"
    return out


def _fundamentals_sanity(text: object) -> str:
    """对 §3 基本面快照做内部一致性校验，返回告警块（无问题时返回 ""）。

    实测（GOOG，2026-09-16）快照存在两类会直接误导分析的问题：

    ① **派生比率互相矛盾**（不同口径混在一起）
       - 净利率 54.771% × 营收 445.866B ⇒ 净利 **244.1B**
       - ROE 48.676% × 股东权益 415.265B ⇒ 净利 **202.1B**
       - 而年度利润表的 2025 财年净利是 **132.17B**（另一口径）
       三个数字对不上，说明快照混合了 TTM / 财年 / 不同分母，**不可交叉引用**。

    ② **单位陷阱**：``Debt to Equity = 18.859`` 显然是**百分数**（即 18.859%），
       若按「倍」引用会得出「负债是权益的 18.9 倍」这种荒谬结论。

    ③ **币种不一致**（2026-10-15 新增）：外国发行人 ADR 的 ``currency``（价格/市值口径）
       与 ``financialCurrency``（财报口径）可能不同（实测 SKHY：USD vs KRW）
       ⇒ 快照把两套币种混算，产出「净利率 85.6%」这类荒谬值。
       此时**跨币种倍数（PE 系列）与绝对金额不可用**，但**纯比率仍可用**。

    本函数把这三类问题显式写进证据包，避免分析角色把无法对账的数字当事实用。
    """
    if not text:
        return ""

    def num(label: str):
        m = re.search(rf"^{re.escape(label)}:\s*([-\d.]+)", str(text), re.M)
        return float(m.group(1)) if m else None

    def txt(label: str):
        m = re.search(rf"^{re.escape(label)}:\s*(\S+)", str(text), re.M)
        return m.group(1) if m else None

    rev, ni = num("Revenue (TTM)"), num("Net Income")
    net_margin, roe = num("Profit Margin"), num("Return on Equity")
    mcap, pb = num("Market Cap"), num("Price to Book")
    pe, fpe = num("PE Ratio (TTM)"), num("Forward PE")
    eps, feps = num("EPS (TTM)"), num("Forward EPS")
    de = num("Debt to Equity")
    cur, fin_cur = txt("Currency"), txt("Financial Currency")

    warns: list[str] = []

    # ★★★ 2026-10-15 新增：币种一致性（外国发行人 ADR 的静默失真）。
    #   实测 SKHY（SK 海力士美股 ADR）：`currency=USD` 而 `financialCurrency=KRW`
    #   ⇒ 快照把美元价格/市值与韩元财报**混算**，产出「净利率 85.6%」「Forward EPS 34.48」
    #   这类荒谬值；而既有的「净利多口径不一致」只报「差距 100%」，**不点出根因**。
    #   这是铁律 3 的典型静默失败：字段外观正常、不触发任何缺失检查。
    if cur and fin_cur and cur.strip().upper() != fin_cur.strip().upper():
        warns.append(
            f"- **⚠️ 币种不一致（关键，优先于本块其它条目）**：快照的**价格 / 市值口径为 {cur}**，"
            f"而**财务报表口径为 {fin_cur}** ⇒ 快照把两套币种混算。\n"
            f"  · **不可用**：一切**跨币种推出的倍数与每股指标** —— `PE Ratio (TTM)` / `Forward PE` / "
            f"`PEG Ratio` / `EPS (TTM)` / `Forward EPS` / `Price to Book` / `Book Value`；\n"
            f"  · **不可用**：带币种的**绝对金额**（`Market Cap` / `Revenue (TTM)` / `Net Income` / "
            f"`Free Cash Flow` / `EBITDA` / `Gross Profit`）—— 它们与 {cur} 计价的价格不同币种；\n"
            f"  · **仍可用**：**纯比率**（`Profit Margin` / `Operating Margin` / `Return on Equity` / "
            f"`Return on Assets` / `Current Ratio`）—— 分子分母同币种，比值与币种无关。\n"
            f"  ⇒ 估值倍数请**改用 §4 财务报表口径自行复算**（或先做汇率换算再计算），"
            f"**禁止直接引用快照的 PE 系列**。"
        )

    # 用 市值/PB 反推**总**账面价值。
    # ⚠️ 不能用快照里的 `Book Value`——那是**每股**账面价值（GOOG 为 50.896 美元/股），
    # 拿去乘 ROE 会得到 0 量级的荒谬结果。
    equity_pb = (mcap / pb) if (mcap and pb) else None
    ni_margin = (rev * net_margin) if (rev and net_margin) else None
    ni_roe = (roe * equity_pb) if (roe and equity_pb) else None
    ni_pe = (mcap / pe) if (mcap and pe) else None

    cands = [("净利率×营收", ni_margin), ("ROE×(市值/PB)", ni_roe), ("市值/PE", ni_pe)]
    vals = [(k, v) for k, v in cands if v]
    if len(vals) >= 2:
        lo = min(v for _, v in vals)
        hi = max(v for _, v in vals)
        gap = (hi - lo) / hi * 100
        detail = "；".join(f"{k} = {v / 1e9:.1f}B" for k, v in vals)
        if gap > 15:
            warns.append(
                f"- **净利多口径不一致**：{detail}，最大差距 {gap:.0f}%。"
                "快照混合了不同期与不同分母的比率，**不可交叉引用**；"
                "如需净利，请以 §4.1 利润表的 `Net Income` 为准。"
            )
        else:
            warns.append(f"- 净利口径自洽（{detail}，差距 {gap:.0f}%）。")

    if pe and eps:
        warns.append(
            f"- 隐含股价校验：PE(TTM) {pe} × EPS(TTM) {eps} = {pe * eps:.2f}"
            "（应与 §1 的 latest_close 吻合；偏差大说明快照价格已更新而 EPS 滞后，"
            "引用倍数时须注明口径）。"
        )

    if pe and fpe and eps and feps and fpe > pe and feps < eps:
        warns.append(
            f"- **前瞻 EPS 低于 TTM EPS**（{feps} < {eps}，降幅 "
            f"{(1 - feps / eps) * 100:.1f}%），故 Forward PE {fpe} > PE(TTM) {pe}。"
            "市场预期盈利**下降**——这是一个需要正面解释的事实，不要默认「前瞻更便宜」。"
        )

    if de is not None and abs(de) > 5:
        warns.append(
            f"- **单位陷阱**：Debt to Equity = {de}。该字段是**百分数**"
            f"（即 {de}% ≈ {de / 100:.3f} 倍），按「倍」引用会得到荒谬结论"
            "（实测 GOOG 若按倍引用，会得出「负债是权益的 18.9 倍」）。"
        )

    if not warns:
        return ""
    return "\n【快照口径校验（由采集器自动生成，务必阅读）】\n" + "\n".join(warns) + "\n"


def _compact_macro(raw: object, keep_obs: int = 26, max_chars: int = 2200) -> str:
    """压缩一段 FRED 宏观输出：保留标题/口径说明/最新值，表格只留**最近**的观测。

    ⚠️ **截断方向搞反了（2026-09-16 修复）**：原实现是 ``txt[:700]``——直接切前 700 字符。
    但 FRED 的报文是**升序**（``showing the most recent 40 of 249 observations`` 之后
    从旧到新排列），所以切掉的恰好是**最新的那些观测**，留下的表格在「最新值」上
    与顶部 ``**Latest:**`` 行互相矛盾，而且最后一行常被切成 ``| 2`` 这种残行。

    现改为：完整保留前置说明与 ``**Latest:**`` 行，表格保留表头 + **最近 keep_obs 行**，
    并在超长时明确标注省略了多少行。
    """
    if not raw:
        return "(无数据)"
    lines = [ln.rstrip() for ln in str(raw).splitlines()]
    if not lines:
        return "(无数据)"

    head: list[str] = []          # 标题 / Units / Frequency / Window / Latest
    tbl: list[str] = []           # markdown 表格行
    for ln in lines:
        if ln.strip().startswith("|"):
            tbl.append(ln)
        elif not tbl:
            head.append(ln)

    if not tbl:
        out = "\n".join(lines)
        return out if len(out) <= max_chars else out[:max_chars] + "\n…(已截断)"

    sep_idx = 1 if len(tbl) > 1 and set(tbl[1].replace("|", "").strip()) <= set("-: ") else 0
    header_part, body = tbl[: sep_idx + 1], tbl[sep_idx + 1:]
    kept = body[-keep_obs:]
    omitted = len(body) - len(kept)

    note = f"\n_(本表共 {len(body)} 行，仅显示最近 {len(kept)} 行)" + (
        f"，省略较早的 {omitted} 行_" if omitted else "_"
    )
    out = "\n".join(head).rstrip() + "\n\n" + "\n".join(header_part + kept) + note
    return out if len(out) <= max_chars else out[:max_chars] + "\n…(已截断)"


def _session_in_progress(bar_date: object) -> bool:
    """该 bar 所在交易日的**美东常规时段**是否仍在进行中（在 ⇒ 才需要按未收盘剔除）。

    ★ 2026-09-22 新增，修「量能闸门对指数误伤」：
    yfinance 对 **^NDX 等指数**的**当日 Volume 字段不完整**（实测 2026-09-21 仅
    20 日均量的 **20.5%**，而当日实为完整交易日：1 分钟 bar 覆盖 09:30–15:59 ET、
    OHLC 与 QQQ 代理比值互证成立）。仅凭量比会把一根**已收盘**的 bar 判为未收盘并剔除，
    导致「最新收盘价」缺失、且 §1 与 §2 的口径互相矛盾
    （§2 的技术指标其实**包含**该 bar —— 已用 250 日序列重算 50SMA/200SMA 逐位核对）。

    ⇒ 判据改为「时点」优先：**交易日已过完美东 16:00 ⇒ 该 bar 视为已收盘，不剔除**；
    只有在同一交易日的 16:00 之前，才回退到原有的量能判据。
    解析不出日期时返回 True（保守：维持旧行为）。
    """
    import zoneinfo

    try:
        d = dt.date.fromisoformat(str(bar_date).strip()[:10])
    except Exception:  # noqa: BLE001
        return True
    now = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    if d > now.date():
        return True
    if d < now.date():
        return False
    return (now.hour, now.minute) < (16, 0)


def _price_summary(csv_text: object) -> tuple[str, dict]:
    """把 OHLCV CSV 压成「关键统计 + 最近 20 根 K 线」，并回传结构化统计。

    **★★ 2026-09-17 新增：未收盘 bar 剔除**

    盘中采集时，yfinance 会把**当天尚未收盘的那根 K 线**一并返回。
    它的 Close 是瞬时价、Volume 只是开盘至今的累计量 —— 二者都不是
    「一个交易日的观测」，却会被下游当成正常 bar 使用，后果是：

      · 价格：盘中价被当作「收盘价」，与前一日的收盘价做对比
      · 成交量：只有全天的零头（实测 9/17 盘中仅 4.1%），量能判据全错
      · **技术指标被污染**：实测 RSI 从 44.02 跳到 52.30、ATR 376.16 → 382.79

    判据（项目铁律第 1 条）：**末根 K 线量 ÷ 20 日均量 显著 < 100% → 该 bar 未收盘。**
    实测样本：53%、6.3%、4.1% 均判定正确。阈值取 **60%**——
    真实全天量极少低于 20 日均量的 60%（除非极端缩量），
    而未收盘 bar 在早盘远低于此。

    ⚠️ 期权链**必须**在盘中采集（否则是上一交易日的残留快照），
    但价格的「收盘口径」**必须**基于已收盘 bar。两者需求相反，
    故本函数承担「把盘中 bar 摘掉」的职责，使**盘中采集也能得到干净的收盘序列**。
    """
    import pandas as pd

    if not csv_text:
        return "(无数据)", {}
    text = str(csv_text)
    if text.startswith("DATA_UNAVAILABLE") or text.startswith("Error"):
        return text, {}

    try:
        df = pd.read_csv(io.StringIO(text), comment="#")
    except Exception as exc:  # noqa: BLE001
        return f"(行情解析失败: {exc})", {}

    if df.empty or "Close" not in df.columns:
        return "(行情为空)", {}

    df = df.dropna(subset=["Close"])
    if df.empty:
        return "(行情无有效收盘价)", {}

    # --- ★ 未收盘 bar 检测（时点优先）---
    #
    # ★★ 2026-09-30 事故修复：旧判据是 `ratio < 0.60 AND _session_in_progress(...)`，
    # 把**量比（数值）当成了主判据**、时点只作附加条件 —— 违反铁律 2
    # 「时点 → 时间戳 → 数值，顺序不可颠倒」。
    #
    # 实测同一交易日内的两次采集：
    #   11:16 ET 量比 40.3%  → 剔除 ✓（碰巧对）
    #   13:32 ET 量比 60.3%  → **不剔除 ✗**（距 16:00 收盘还有 2.5 小时）
    # 后果：9-30 的半截 K 线被当成收盘 bar 写进证据包，证据包明写
    # 「日线序列最后一根有效 bar：2026-09-30 收盘 346.96」，而 9-30 根本没收盘
    # ⇒ 最新收盘价、全部技术指标、以及所有以收盘价为分母的比率**同时被污染**，
    # 且**外观完全正常**（命令成功、字段存在、数值合规）—— 典型静默失败（铁律 3）。
    # 更隐蔽的是该 bug **只在盘中晚段触发**：早盘量比必 <60% 反而"正常"。
    #
    # ⇒ 正确判据：**时点是定义性问题，不是概率问题**。只要该 bar 所属交易日
    # 尚未走完美东 16:00，它在定义上就不是一个完整交易日的观测，
    # **无论量比多高都必须剔除**；量比只在"交易日已结束"时用于提示字段不完整。
    unclosed_note = ""
    unclosed_info: dict = {}
    if "Volume" in df.columns and len(df) >= 21:
        try:
            vol = pd.to_numeric(df["Volume"], errors="coerce")
            last_vol = float(vol.iloc[-1])
            avg20 = float(vol.iloc[-21:-1].mean())   # 前 20 日（不含末根）
            ratio = (last_vol / avg20) if avg20 > 0 else float("nan")
            _last_date = (
                df["Date"].iloc[-1] if "Date" in df.columns else df.index[-1]
            )
            if _session_in_progress(_last_date):
                # 时点优先：交易日未走完 ⇒ 无条件剔除，不看量比
                dropped = df.tail(1)
                d0 = dropped.iloc[0]
                unclosed_info = {
                    "unclosed_bar_date": str(d0.get("Date", "?")),
                    "unclosed_bar_close": round(float(d0["Close"]), 2),
                    "unclosed_bar_dropped": True,
                    "unclosed_drop_reason": "session_in_progress",
                }
                if not math.isnan(ratio):
                    unclosed_info["unclosed_volume_ratio"] = round(ratio * 100, 1)
                _ratio_txt = (
                    f"，量为 20 日均量的 {ratio * 100:.1f}%"
                    if not math.isnan(ratio) else "（该通道无有效成交量字段）"
                )
                unclosed_note = (
                    f"⚠ 已剔除未收盘 bar：{d0.get('Date','?')} "
                    f"(瞬时价 {float(d0['Close']):.2f}{_ratio_txt})。\n"
                    f"   判据：**时点优先** —— 该 bar 所属交易日尚未走完美东 16:00，\n"
                    f"   它在定义上就不是一个完整交易日的观测，故**无论量比多高**都剔除。\n"
                    f"   （2026-09-30 事故：盘中 13:32 量比已达 60.3%，旧判据因而漏剔。）\n"
                    f"   本证据包的价格与技术指标均基于**已收盘** bar。\n"
                )
                df = df.iloc[:-1]
            elif not math.isnan(ratio) and ratio < 0.60:
                unclosed_note = (
                    f"ℹ️ 末根 bar {_last_date} 的量为 20 日均量的 {ratio*100:.1f}%，"
                    f"但其交易日已过完美东 16:00 ⇒ 判为**已收盘**，不剔除。\n"
                    f"   量比偏低属该通道当日 volume 字段不完整（指数尤甚），"
                    f"OHLC 需另用 1 分钟 bar / ETF 代理比值核验。\n"
                )
        except Exception:  # noqa: BLE001
            pass

    close = df["Close"]
    last = float(close.iloc[-1])
    stats: dict = {"latest_close": round(last, 2), "bars": int(len(df))}
    stats.update(unclosed_info)

    for label, n in (("ret_5d", 5), ("ret_20d", 20), ("ret_60d", 60), ("ret_120d", 120)):
        if len(close) > n:
            stats[label] = round((last / float(close.iloc[-1 - n]) - 1) * 100, 2)

    if len(close) >= 200:
        stats["high_52w"] = round(float(df["High"].tail(252).max()), 2)
        stats["low_52w"] = round(float(df["Low"].tail(252).min()), 2)
    if "Volume" in df.columns:
        stats["avg_vol_20d"] = int(df["Volume"].tail(20).mean())

    cols = [c for c in ("Date", "Open", "High", "Low", "Close", "Volume") if c in df.columns]
    recent = df[cols].tail(20).to_string(index=False)

    lines = ["关键统计:"]
    for k, v in stats.items():
        lines.append(f"  - {k}: {v}")
    lines.append("")
    if unclosed_note:
        lines.append(unclosed_note.rstrip())
        lines.append("")
    lines.append("最近 20 根 K 线:")
    lines.append(recent)
    if unclosed_note:
        lines.append("")
        lines.append("注：上表为已收盘 bar。当日未收盘 bar 已按**时点优先**判据剔除"
                     "（所属交易日未走完美东 16:00 ⇒ 无论量比多少都剔除；"
                     "2026-09-30 起取代旧的「量 < 20 日均量 60%」判据，"
                     "后者在盘中晚段量比升破 60% 时会漏剔）。")
    return "\n".join(lines), stats


def _extended_hours_block(ticker: str, as_of: str) -> tuple[str, dict]:
    """盘前 / 盘后（扩展时段）分钟级汇总 —— 补 §13 未覆盖的 04:00–09:30 与 16:00–20:00 ET。

    ★ 2026-10-21 新增（用户要求：盘前盘后数据必须收集）：
      事件驱动的价格发现大量发生在扩展时段（尤其**盘后**），而 §13 只覆盖
      常规时段 09:30–16:00 ⇒ 事件的第一反应被整段漏掉。实测 NFLX 10-20：
      常规收盘 68.69，盘后成交仍继续，若只报常规收盘，读者会误以为「当天就此定格」。

    口径（必须声明，写进证据包）：
      - 数据源 = yfinance 1 分钟 bar（``prepost=True``），美东时区；
      - 盘前 = 04:00–09:30 ET，盘后 = 16:00–20:00 ET；
      - **扩展时段流动性低、点差宽，成交价不代表常规时段可成交价** ⇒
        只能作「事件反应 / 情绪」证据，**不得用于止损 / 目标 / 估值锚定**。
    """
    import zoneinfo

    import pandas as pd
    import yfinance as yf

    et = zoneinfo.ZoneInfo("America/New_York")
    now_et = pd.Timestamp.now(tz=et)
    df = yf.Ticker(ticker).history(interval="1m", period="5d", prepost=True)
    if df is None or df.empty:
        return ("(不可用: 1 分钟 bar 为空 —— 该标的可能无扩展时段成交)", {"sessions": 0})
    df = df.tz_convert(et)

    # 常规收盘（扩展时段变动的参照）：取日线序列，避免与 1 分钟 bar 的口径混用
    closes: dict[dt.date, float] = {}
    try:
        daily = yf.Ticker(ticker).history(period="10d")
        if daily is not None and not daily.empty:
            if getattr(daily.index, "tz", None) is not None:
                daily = daily.tz_convert(et)
            for ts, r in daily.iterrows():
                c = r.get("Close")
                if c is not None and pd.notna(c):
                    closes[ts.date()] = float(c)
    except Exception:  # noqa: BLE001 — 参照收盘取不到不阻断本节
        pass

    rows: list[dict] = []
    for day in sorted({d for d in df.index.date}, reverse=True)[:4]:
        g = df[df.index.date == day]
        segs = (
            ("盘前", g[(g.index.time >= dt.time(4, 0)) & (g.index.time < dt.time(9, 30))]),
            ("盘后", g[(g.index.time >= dt.time(16, 0)) & (g.index.time < dt.time(20, 0))]),
        )
        prev_days = sorted(d for d in closes if d < day)
        for label, seg in segs:
            if seg.empty:
                continue
            o, h, l, c = (float(seg["Open"].iloc[0]), float(seg["High"].max()),
                          float(seg["Low"].min()), float(seg["Close"].iloc[-1]))
            vol = float(seg["Volume"].sum()) if "Volume" in seg else 0.0
            ref = closes.get(day) if label == "盘后" else (closes.get(prev_days[-1]) if prev_days else None)
            chg = (c / ref - 1.0) * 100.0 if ref else None
            rows.append({"day": day.isoformat(), "label": label, "open": o, "high": h,
                         "low": l, "last": c, "volume": vol, "bars": int(len(seg)),
                         "ref_close": ref, "chg_pct": chg})

    if not rows:
        return ("(不可用: 窗口内无盘前/盘后成交)", {"sessions": 0})

    lines = [
        f"- 采集时点：{now_et:%Y-%m-%d %H:%M} 美东（{'常规交易时段内' if dt.time(9, 30) <= now_et.time() < dt.time(16, 0) else '非常规交易时段'}）",
        "- 数据源：yfinance **1 分钟 bar**（`prepost=True`），美东时区",
        "- 时段定义：**盘前 = 04:00–09:30 ET**；**盘后 = 16:00–20:00 ET**（盘前参照**前一交易日收盘**，盘后参照**当日常规收盘**）",
        "- ⚠️ **口径限制**：扩展时段流动性低、点差宽，成交价**不代表常规时段可成交价** ⇒ 只作「事件反应 / 情绪」证据，"
        "**不得用于止损 / 目标 / 估值锚定**。",
        "",
        "| 交易日 | 时段 | 开 | 高 | 低 | 末 | 分钟数 | 成交量 | 参照收盘 | 相对变动 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows[:8]:
        chg = f"{r['chg_pct']:+.2f}%" if r["chg_pct"] is not None else "—"
        ref = f"{r['ref_close']:.2f}" if r["ref_close"] else "—"
        lines.append(f"| {r['day']} | {r['label']} | {r['open']:.2f} | {r['high']:.2f} | "
                     f"{r['low']:.2f} | **{r['last']:.2f}** | {r['bars']} | {r['volume']:,.0f} | "
                     f"{ref} | **{chg}** |")
    latest = rows[0]
    lines += ["", f"**最新扩展时段读数**：{latest['day']} {latest['label']}末价 **{latest['last']:.2f}**"
                  + (f"（相对参照收盘 {latest['ref_close']:.2f} 为 **{latest['chg_pct']:+.2f}%**）"
                     if latest["chg_pct"] is not None else "") + "。"]
    stats_out = {"sessions": len(rows), "latest": latest, "rows": rows[:8],
                 "collected_at_et": f"{now_et:%Y-%m-%d %H:%M}"}
    return "\n".join(lines), stats_out


def _realtime_close_block(ticker: str, as_of: str) -> tuple[str, dict]:
    """补充「最新交易日」的收盘快照 —— 解决 yfinance **日线接口的当日滞后**。

    **为什么需要这一节（2026-09-17 实测）**

    yfinance 的 ``history(interval="1d")`` 在**当日收盘后数小时内**
    仍会返回一根 ``Open/High/Low/Close`` 全为 ``NaN``、仅 ``Volume`` 有值的残缺 bar，
    随后由 TradingAgents 的数据层剔除（日志：``N trailing bar(s) ... have no closing
    price; using <前一日> as the latest close``）。

    实测（本机 2026-09-17 美东 20:47，收盘后约 4.8 小时，GOOG）：

      · 日线序列最后一根有效收盘 = **2026-09-16 339.36**，9/17 那根 Close 为 NaN
      · 但同一标的的**实时字段** ``regularMarketPrice`` = **343.68**（9/17 收盘），
        ``regularMarketPreviousClose`` = 339.36（与日线自洽）
      · **1 分钟 bar** 完整提供 9/17 全天 390 根（09:30–15:59 ET），
        末根收 343.74，日内高 345.96 / 低 340.50

    ⇒ 只依赖日线，会把「最新价」写错**一整个交易日**（本例差 4.32 美元 = +1.27%），
      而技术指标（RSI/MACD/ATR/布林）也都停在 9/16。
      本节把该缺口补齐，并**显式声明两套口径**：指标口径止于日线末日，价格口径含最新交易日。

    ⚠️ 本节**不重算技术指标** —— 自算一套指标会与 §2 的来源口径不一致，
    反而制造第二个不可对账的数字。指标一律以 §2 为准，差距在下方显式列出。
    """
    import zoneinfo

    import pandas as pd
    import yfinance as yf

    stats: dict = {}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as exc:  # noqa: BLE001
        return f"(不可用: {type(exc).__name__}: {exc})", stats

    ny = zoneinfo.ZoneInfo("America/New_York")
    now_ny = dt.datetime.now(ny)

    # --- 实时字段所属的常规交易时段日期 ---
    sess_date = None
    try:
        rt = info.get("regularMarketTime")
        if rt:
            sess_ny = dt.datetime.fromtimestamp(int(rt), tz=dt.timezone.utc).astimezone(ny)
            sess_date = sess_ny.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        pass

    # --- 日线序列的最后一根有效 bar ---
    daily_last, daily_close = None, None
    try:
        h = t.history(period="15d", interval="1d")
        h = h.dropna(subset=["Close"])
        # ★ 时点优先（与 _price_summary 同一判据，铁律 2）：末根 bar 若属于「尚未走完
        # 美东 16:00」的交易日，它在定义上不是完整交易日的观测 ⇒ 无论量比多少都剔除。
        # 不剔除的后果（2026-09-30 事故）：本节会把盘中价写成「9-30 收盘 346.72」，
        # 而 §1/§2 已正确回退到 9-29 的 337.32 —— 同一份证据包前后自相矛盾。
        if len(h) and _session_in_progress(h.index[-1].strftime("%Y-%m-%d")):
            h = h.iloc[:-1]
        if len(h):
            daily_last = h.index[-1].strftime("%Y-%m-%d")
            daily_close = round(float(h["Close"].iloc[-1]), 2)
    except Exception:  # noqa: BLE001
        pass

    rt_price = info.get("regularMarketPrice")
    prev_close = info.get("regularMarketPreviousClose")
    day_hi, day_lo = info.get("regularMarketDayHigh"), info.get("regularMarketDayLow")
    day_vol = info.get("regularMarketVolume")

    # --- 盘中 1 分钟 bar：用于独立复核「实时字段」并给出日内区间 ---
    intraday: dict = {}
    try:
        m = t.history(period="2d", interval="1m")
        if len(m):
            m.index = m.index.tz_convert(ny) if m.index.tz is not None else m.index
            last_day = m.index[-1].strftime("%Y-%m-%d")
            reg = m[m.index.strftime("%Y-%m-%d") == last_day].between_time("09:30", "16:00")
            if len(reg):
                intraday = {
                    "session": last_day,
                    "n_bars": int(len(reg)),
                    "first_ts": reg.index[0].strftime("%H:%M"),
                    "last_ts": reg.index[-1].strftime("%H:%M"),
                    "open": round(float(reg["Open"].iloc[0]), 2),
                    "high": round(float(reg["High"].max()), 2),
                    "low": round(float(reg["Low"].min()), 2),
                    "last_close": round(float(reg["Close"].iloc[-1]), 2),
                    "volume_sum": int(reg["Volume"].sum()),
                }
    except Exception:  # noqa: BLE001
        pass

    # --- 未收盘 bar 判据（复用于实时那一日）---
    vol_ratio = None
    try:
        h = t.history(period="30d", interval="1d")
        v = pd.to_numeric(h["Volume"], errors="coerce")
        if len(v) >= 21 and v.iloc[-1] == v.iloc[-1]:
            avg20 = float(v.iloc[-21:-1].mean())
            if avg20 > 0:
                vol_ratio = round(float(v.iloc[-1]) / avg20 * 100, 1)
    except Exception:  # noqa: BLE001
        pass

    stats.update({
        "daily_last_bar": daily_last,
        "daily_last_close": daily_close,
        "realtime_session": sess_date,
        "realtime_price": rt_price,
        "realtime_prev_close": prev_close,
        "realtime_day_high": day_hi,
        "realtime_day_low": day_lo,
        "realtime_day_volume": day_vol,
        "realtime_lag_days": (
            None if not (sess_date and daily_last)
            else (dt.date.fromisoformat(sess_date) - dt.date.fromisoformat(daily_last)).days
        ),
        "intraday": intraday,
        "realtime_vol_ratio_pct": vol_ratio,
    })

    newer = bool(sess_date and daily_last and sess_date > daily_last)
    lines: list[str] = []
    lines.append("【本节用途】yfinance 的**日线接口**在当日收盘后数小时内不发布当日 bar"
                 "（仅 Volume 有值、OHLC 为 NaN），会被上游数据层剔除。"
                 "本节用**实时字段 + 1 分钟 bar** 把「最新交易日」补回来。")
    lines.append("")
    lines.append(f"- 采集时点：{now_ny:%Y-%m-%d %H:%M} 美东"
                 f"（{'常规交易时段内' if (now_ny.weekday() < 5 and 9.5 <= now_ny.hour + now_ny.minute / 60 < 16) else '非交易时段'}）")
    lines.append(f"- **日线序列最后一根有效 bar**：{daily_last}　收盘 **{daily_close}**"
                 "（§1 与 §2 的价格/指标口径**止于此日**）")
    lines.append(f"- 实时字段所属常规交易时段：**{sess_date}**　"
                 f"`regularMarketPrice` = **{rt_price}**　"
                 f"`regularMarketPreviousClose` = {prev_close}")
    # ★ 时点优先（铁律 2）：盘中 ⇒ 实时价是「盘中价」，**不是**收盘价。
    # 旧文案无条件写「{sess_date} 收盘」，在盘中采集时等于把一个未收盘的瞬时价
    # 冒充收盘价（2026-09-30 事故：13:42 ET 写「9-30 收盘 346.72」）。
    sess_in_progress = _session_in_progress(sess_date) if sess_date else False
    rt_kind = "盘中价（**非收盘**）" if sess_in_progress else "收盘"
    if newer:
        lines.append(f"- ⇒ **实时时段比日线末日新 {stats['realtime_lag_days']} 个交易日**："
                     f"最新价按 **{rt_price}**（{sess_date} {rt_kind}）计，"
                     f"相对日线末日 {daily_close} 变化 "
                     f"{(rt_price / daily_close - 1) * 100:+.2f}%。"
                     "**两者口径不同，不可混用**：技术指标必须用日线末日，"
                     "「最新价」用实时字段")
        lines[-1] += ("；且该最新价**不是收盘价，不得用作止损/目标/估值锚点**（铁律 4）。"
                      if sess_in_progress else "。")
    if intraday:
        lines.append(f"- 1 分钟 bar 复核（{intraday['session']}，"
                     f"{intraday['n_bars']} 根，{intraday['first_ts']}–{intraday['last_ts']} ET）："
                     f"开 {intraday['open']} / 高 {intraday['high']} / "
                     f"低 {intraday['low']} / 末根收 {intraday['last_close']}，"
                     f"分钟级成交量合计 {intraday['volume_sum']:,}")
        if rt_price:
            d = abs(intraday["last_close"] - float(rt_price))
            lines.append(f"  - 与 `regularMarketPrice` 的差 = {d:.2f} 美元"
                         "（收盘集合竞价成交价与最后一根分钟 bar 的正常差异）")
    if vol_ratio is not None:
        # ★ 时点优先（铁律 2：时点 → 时间戳 → 数值）：
        # 盘中 ⇒ 无条件判未收盘，量比再高也不改判；量比只在交易日已结束时作辅助信息。
        if sess_in_progress:
            verdict = (f"该 bar **未收盘** —— 其所属交易日 {sess_date} 尚未走完美东 16:00"
                       f"（采集时点 {now_ny:%H:%M} ET）。**时点判据优先于量比**，"
                       f"故量比 {vol_ratio}% 即使已过 60% 也不改判。")
        elif vol_ratio >= 60:
            verdict = f"该 bar **已收盘**（交易日 {sess_date} 已过美东 16:00；量比 {vol_ratio}% ≥ 60%）"
        else:
            verdict = (f"该 bar **已收盘**（交易日 {sess_date} 已过美东 16:00）；"
                       f"量比仅 {vol_ratio}% < 60%，属该通道当日 volume 字段不完整"
                       f"（指数尤甚），**不是**未收盘。")
        lines.append(f"- 量能判据（§1 铁律）：最新那根日线 bar 量 ÷ 20 日均量 = "
                     f"**{vol_ratio}%** ⇒ {verdict}")
    lines.append("")
    lines.append("⚠️ **本节不重算技术指标**。§2 的 RSI / MACD / ATR / 布林 / 均线"
                 "一律以**日线最后一根有效 bar**为准；若实时时段更新，"
                 "则这些指标**尚未反映最新一个交易日**——引用时必须声明该滞后。")
    return "\n".join(lines), stats


def _render_option_block(ticker: str, opts: dict) -> str:
    """把 ``fetch_option_structure`` 的结果渲染成证据包章节。

    与 ``collect_index.py`` 的同名区块共用 ``fetch_option_structure``，
    但**标题与口径声明按「标的自身期权链」写**（指数报告里那节是 ETF 代理）。
    这里刻意不复制 collect_index 的渲染函数：那节绑定在 QQQ 代理的语境上，
    共用反而会让「GOOG 用的是 GOOG 自己的期权链」这一事实被模糊掉。
    """
    if opts.get("error"):
        return f"(不可用: {opts['error']})"

    grade = opts.get("iv_grade", "NONE")
    fresh = opts.get("freshness") or {}
    d = opts.get("div_yield_used")
    lines: list[str] = []
    lines.append(f"- 标的价（BSM 反解用的 spot）: **{opts.get('spot')}**"
                 f"　|　无风险利率: {opts.get('rate_used')}"
                 f"　|　股息率: {d}")
    lines.append(f"- 扫描范围: **{opts.get('n_expiries_scanned')} / "
                 f"{opts.get('n_expiries_total')}** 个未来到期日（全量，非抽样）")
    lines.append(f"- **IV 数据等级：{grade}**（FULL=ATM+偏斜齐 / SKEW_ONLY=仅偏斜 / "
                 "ATM_ONLY=仅 ATM / PARTIAL=降级 / NONE=不可用）")
    # ★ 2026-10-21：切 CBOE 源时 freshness 的 min_age_days/n_fresh/n_quoted 按设计为 None
    #   （见 collect_index 的 cboe_ok 分支：不做 yfinance 口径的新鲜度探测）。
    #   原实现直接渲染成「None 天 / None 个」，读者会误以为「数据没取到」——
    #   实测 NFLX 10-20 盘后轮：明明 CBOE 全链 3136 个合约、IV 等级 FULL，却显示 None。
    #   ⇒ 显式写「不适用」并给出原因，不让占位符冒充数据。
    if fresh.get("min_age_days") is None and fresh.get("source") == "cboe_delayed":
        lines.append(f"- **报价新鲜度闸门**：**不适用**（{fresh.get('skipped_reason') or '已切 CBOE 源'}）；"
                     f"CBOE 延迟报价为**上一时段收盘快照**，按设计不做 yfinance 口径的成交日探测")
    else:
        lines.append(f"- **报价新鲜度闸门**：只接受 ``lastTradeDate`` ≤ "
                     f"{opts.get('quote_age_filter_days')} 天的合约；"
                     f"本次最新成交距今 **{fresh.get('min_age_days')} 天**，"
                     f"合格样本 **{fresh.get('n_fresh')}** 个"
                     f"（扫描到有双边报价的合约 {fresh.get('n_quoted')} 个）")
    lines.append(f"- **采集时点**：{fresh.get('session_note') or '未记录'}")
    # ★ 2026-10-16：**来源声明**（方案 A 时点分支的配套，与 collect_index 同步）。
    #   两个源的 IV/偏斜口径不同、数值不可混用，故必须显式标注。
    _src = (opts.get("source") or "").strip()
    _is_cboe = not _src.startswith("yfinance")
    from wb_analysis.collect_index import _source_label, _iv_method_label
    lines.append(f"- **数据来源：{_source_label(_src)}**")
    lines.append(f"  - {opts.get('source_note') or '（未记录时点说明）'}")
    if _is_cboe:
        lines.append("  - ⚠️ **口径提示**：本源的 `iv`/`delta` 由**交易所模型**给出，"
                     "与项目自建 BSM 反解的数值**不可直接比较**"
                     "（实测同轮偏斜差异可达数 pp，根因是样本数与 delta 定义）。"
                     "**本报告全篇统一使用本接口口径。**")
    lines.append("- **IV 算法**："
                 + ("**交易所模型直出（CBOE 官方，无需反解）**。"
                    "过滤链：双边报价 > 0 → `ask ≥ bid` → 点差 ≤ 30% → 成交日新鲜度合格。"
                    if _is_cboe else
                    "**自建 Black-Scholes-Merton 反解**"
                    "（拟合中间价，含股息率），**不使用 yfinance 的 "
                    "``impliedVolatility``** —— 后者与报价不自洽。"
                    "过滤链：双边报价 > 0 → `ask ≥ bid` → 点差 ≤ 30% → "
                    "**成交日新鲜度合格** → 反解 IV 落在 [2%,120%]。"))
    lines.append("- **偏斜主口径 = 25-delta 配对**（put IV(−25Δ) − call IV(+25Δ)）；"
                 "±10% 距现价为备用口径。**两个口径数值不同，不可混用。**")
    lines.append("")
    lines.append("**选中到期日明细**")
    lines.append("```")
    for r in opts.get("by_expiry", []):
        parts = [f"  {r['expiry']}（{r['days']:>4}天） 有效 C{r['n_quoted_call']:>3}/"
                 f"P{r['n_quoted_put']:>3}  P/C(Vol) {str(r['pc_volume']):>6}"]
        if r["atm_call_iv"] is not None and r["atm_put_iv"] is not None:
            parts.append(f"ATM_C {r['atm_call_iv']:>6}  ATM_P {r['atm_put_iv']:>6}")
        if r["skew_25d_pp"] is not None:
            parts.append(f"25Δ偏斜 {r['skew_25d_pp']:>6}pp"
                         f"(put {r['skew_25d_mn']}% / call {r['skew_25d_call_mn']}%, "
                         f"区间 {r['skew_25d_band']}, n={r['n_skew_put']}/{r['n_skew_call']})")
        elif r["otm_put_iv"] is not None:
            parts.append(f"单边OTM_PutIV {r['otm_put_iv']:>6}(n={r['n_otm_put']})")
        if r["skew_10pct_pp"] is not None:
            parts.append(f"±10%口径 {r['skew_10pct_pp']:>6}pp")
        lines.append("".join(parts))
    if not opts.get("by_expiry"):
        lines.append("  （无任何到期日有新鲜报价）")
    lines.append("```")
    lines.append("")
    lines.append("**全部未来到期日扫描结果（证明「不是没取，是真的没有」）**")
    lines.append("```")
    for x in opts.get("all_expiry_scan", []):
        lines.append(f"  {x['expiry']}（{x['days']:>4}天） 有效 C{x['n_quoted_call']:>3}/"
                     f"P{x['n_quoted_put']:>3}  等级 {x['grade'] or '—'}")
    lines.append("```")
    lines.append("")
    lines.append("**口径说明（必须随结论一并引用）**")

    if fresh.get("stale"):
        lines.append(
            "- 🚨 **本次期权快照整体陈旧 ⇒ 全部 IV / 偏斜 / P-C 结论不可引用。**\n"
            f"  扫描 {fresh.get('expiries_checked')} 个未来到期日、"
            f"{fresh.get('n_quoted')} 个有双边报价的合约，"
            f"**最新一笔成交距今仍有 {fresh.get('min_age_days')} 天**，"
            f"合格（≤{opts.get('quote_age_filter_days')} 天）样本数 = 0。\n"
            "  根因是**采集时点**：期权链只在美东 09:30–16:00 实时刷新，"
            "盘前/盘后/休市采集拿到的是上一交易日的残留挂单。"
            "**这是采集时点问题，不是数据源缺陷**（同一标的盘中复测即新鲜）。")
    elif grade == "FULL":
        lines.append("- ✅ **IV / ATM / 25Δ 偏斜全部可用**（put 与 call 两侧都能配到 25-delta 样本）。")
    elif grade == "SKEW_ONLY":
        lines.append("- ⚠️ **可给 25Δ 偏斜，但 ATM 两侧样本不齐** ⇒ ATM IV 不可得，偏斜可用。")
    elif grade == "ATM_ONLY":
        lines.append("- ⚠️ **只有 ATM IV 可用，无法构造偏斜**。")
    elif grade in ("PARTIAL_2SIDE", "PARTIAL"):
        lines.append("- ⚠️ **降级读数：有效报价覆盖不足，无法构造 25Δ 偏斜。**")
    else:
        lines.append(f"- ⛔ **IV 与偏斜本次不可用**：{opts.get('iv_note') or ''}")

    for r in opts.get("by_expiry", []):
        if r.get("pc_volume") is not None:
            lines.append(f"- 📊 **P/C（成交量口径）**：{r['expiry']} = **{r['pc_volume']}**"
                         "（>1 表示认沽成交占比高于认购）。")
            break
    if opts.get("put_skew_ratio"):
        lines.append(f"- 📐 **风险中性偏度替代指标**：OTM put IV ÷ ATM put IV = "
                     f"**{opts['put_skew_ratio']}**（>1 表示虚值 put 贵于平价）。"
                     "该比值**不依赖 call 侧样本**，无法配对时是方向性的稳健替代。")
    ts = opts.get("term_structure")
    if ts:
        lines.append(f"- 📈 **期限结构**：{ts['near_expiry']}（{ts['near_days']}天）ATM IV "
                     f"{ts['near_atm_iv']} vs {ts['far_expiry']}（{ts['far_days']}天）"
                     f" {ts['far_atm_iv']} → **端点**斜率 **{ts['slope_pp']:+}pp**，"
                     f"形态为 **{'正向（近低远高）' if ts['contango'] else '倒挂（近高远低）'}**。")
        if ts.get("atm_series"):
            lines.append("  · 逐档 ATM IV：" + " → ".join(
                f"{s['days']}天 {s['atm_iv']}" for s in ts["atm_series"]))
        # ★★ 2026-10-12：端点斜率**不足以**支撑「近期是否被额外定价」的判断 ——
        #   只比最近与最远两档会漏掉中段驼峰（实测 GOOG：32 天处比相邻档高 4~5pp，
        #   而端点斜率反而显示"正常的正向结构"）。有驼峰时必须把它说出来，
        #   并**禁止**下游沿用旧的「近期未被额外定价」措辞。
        if ts.get("hump"):
            h = ts["hump"]
            lines.append(f"  ⚠️ **曲线非单调 —— {h['days']} 天处出现驼峰**：ATM IV {h['atm_iv']}，"
                         f"同时高出相邻两档 ≥ **{h['excess_pp']}pp**"
                         f"（{h['window_from']} 与 {h['window_to']}）"
                         f" ⇒ **事件风险定价集中在 {h['window_from']} ~ {h['window_to']} 窗口内**。")
            lines.append("  ⛔ **不得**仅据端点斜率说「近期未被额外定价」—— 该结论已被驼峰证伪。")
        elif ts["contango"]:
            lines.append("  · 逐档走势与端点斜率一致，未见内部驼峰 ⇒ 可说「近期未被额外定价」。")
        else:
            lines.append("  · 倒挂通常对应**近期事件风险定价**高于长期。")
    if opts.get("fallback_note"):
        lines.append(f"- 📌 **回退说明**：{opts['fallback_note']}")
    if opts.get("oi_note"):
        lines.append(f"- ⚠️ **持仓量（OI）口径不可信**：{opts['oi_note']}")
    lines.append("- ⛔ **本证据包不含期权偏斜的历史序列**（yfinance 不提供历史期权链）"
                 "⇒ **不得**把本次偏斜描述为「极端」「异常偏高」或「已回落」，"
                 "只能说「方向性溢价存在且跨期限一致」。")
    return "\n".join(lines)


def _render_vol_proxy_block(vp: dict) -> str:
    """渲染波动率 / 债券代理的日线 OHLC（弥补 FRED 的约一个工作日发布滞后）。"""
    vl: list[str] = []
    for p in vp.get("proxies", []):
        rows = [b for b in p["bars"] if b.get("close") is not None]
        if not rows:
            continue
        vl.append(f"### {p['ticker']}（最近 {len(rows)} 个交易日）")
        vl.append("```")
        vl.append("  日期        开      高      低      收            成交量   日振幅%  收盘距高点%")
        for b in rows:
            rg = (f"{b.get('intraday_range_pct'):>7.2f}"
                  if b.get("intraday_range_pct") is not None else "      -")
            cv = (f"{b.get('close_vs_high_pct'):>11.2f}"
                  if b.get("close_vs_high_pct") is not None else "          -")
            vol = f"{b['volume']:>15,}" if b.get("volume") else f"{'无成交量数据':>15}"
            vl.append(f"  {b['date']}  {b['open']:>7} {b['high']:>7} {b['low']:>7} "
                      f"{b['close']:>7} {vol} {rg} {cv}")
        if p["ticker"] == "^TNX":
            vl.append("")
            vl.append("  （^TNX 单位为百分数的收益率，日振幅另按基点计："
                      + "  ".join(f"{b['date'][5:]}={b.get('range_bp')}bp"
                                  for b in rows if b.get("range_bp") is not None) + "）")
        vl.append("```")
        vl.append("")
    if vp.get("notes"):
        vl.append("**通道说明**：" + "；".join(vp["notes"]))
    return "\n".join(vl) if vl else "(无数据)"


def _retry(fn, *args, retries: int = _NET_RETRIES, delay: float = 1.5):
    """给**不走 `_safe_call` 的网络块**（期权 / 波动率代理 / 实时收盘）同一套退避重试。

    为什么需要第二个重试入口：§11/§12/§13 是直接 `try/except` 调用的
    （它们返回结构化 dict，不是文本，塞不进 `_safe_call` 的「占位串识别」契约）。
    但它们同样走 yfinance，同样会被**代理抖动**打成 403 ——
    若只修 `_safe_call` 路径，这三节仍会在抖动时整段变成 `(不可用: ...)`。

    与 `_safe_call` 保持**同一退避口径**（1.5×(n+1) 秒），避免两处漂移。
    """
    from wb_analysis._net import retry as _net_retry

    return _net_retry(fn, *args, retries=retries, delay=delay, retryable=Exception)


def _safe_call(name: str, fn, *args, retries: int = _NET_RETRIES) -> tuple[str, str]:
    """调用一个数据通道，返回 (状态, 文本)。状态为 ok / unavailable / fail。

    ``retries`` **默认即 `_NET_RETRIES`**（2026-10-11 改）—— 理由见 `_NET_RETRIES`
    的注释：本机出网经代理，节点会间歇抽风，而「每个调用点自己记得传 retries」
    这种约定**必然漂移**（原实现 30+ 个通道里只有 FRED 传了）。
    凡是读接口都可安全重试，故把重试设为**默认行为**，要关须显式写 ``retries=0``。

    历史沿革：``retries`` 最早是为 FRED 瞬时故障引入的。实测（2026-09-16，GOOG）：
    FRED 的 5 个宏观通道在一次采集里有 1 个因 ``SSLV3_ALERT_HANDSHAKE_FAILURE``
    失败，而紧接着单独重试即成功——**单次 TLS 抖动不该静默丢掉一个宏观指标**。

    **★★ 2026-09-17 新增：占位串识别（堵住「假绿」）**

    有些通道（StockTwits / Reddit）按设计**不抛异常**，失败时返回占位字符串，
    以便调用方无论成败都拿到统一的字符串类型。但原实现只把 ``DATA_UNAVAILABLE``
    前缀判为不可用 —— 于是 ``<stocktwits unavailable: HTTPError>`` 这类占位串
    被记为 **ok**，通道健康度照报「29 / 29 成功」。

    实测后果（2026-09-17 采集 GOOG）：StockTwits 因 403 整段缺失，
    却被统计为成功；若不做人工复核，报告会把「无情绪数据」误当成「情绪中性」。
    现在按占位串前缀显式降级为 ``unavailable``。
    """
    last: tuple[str, str] = ("fail", "未执行")
    for attempt in range(retries + 1):
        try:
            out = fn(*args)
            text = str(out)
            if text.startswith("DATA_UNAVAILABLE"):
                return "unavailable", text
            low = text.lower()
            if any(marker in low for marker in _PLACEHOLDER_MARKERS):
                return "unavailable", text
            return "ok", text
        except Exception as exc:  # noqa: BLE001
            last = "fail", f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    return last


def _stocktwits_block(ticker: str, start: str, end: str) -> str:
    """StockTwits cashtag 流（sentiment_analyst 的同款调用）。"""
    from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages

    return fetch_stocktwits_messages(ticker, limit=30, start_date=start, end_date=end)


def _reddit_block(ticker: str, start: str, end: str) -> str:
    """Reddit 相关讨论帖（sentiment_analyst 的同款调用）。"""
    from tradingagents.dataflows.reddit import fetch_reddit_posts

    return fetch_reddit_posts(ticker, start_date=start, end_date=end)


def _emit_stub(ticker: str, as_of: str, evidence_md: Path, health: dict) -> Path | None:
    """若尚无分析结果，写一份符合 FRAMEWORK.md 第 4 节契约的骨架 JSON。

    已存在则不覆盖——避免把已完成的深度分析冲掉。骨架里的评级预填 ``Hold``，
    仅仅是为了让下游解析器不报错；真正分析时必须逐项改写。
    """
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    stub_path = ANALYSIS_DIR / f"{ticker}_{as_of}.json"
    if stub_path.exists():
        return None

    missing = [k for k, v in health.items() if v in ("fail", "unavailable", "skipped", "withheld")]
    notes = f"证据包: {evidence_md}\n"
    if missing:
        notes += f"以下通道在本次采集中不可用，分析时须显式声明缺口、不得臆测: {', '.join(missing)}\n"

    stub = {
        "ticker": ticker,
        "as_of": as_of,
        "ratings": {
            "research_manager": "Hold",
            "trader_action": "Hold",
            "portfolio_manager": "Hold",
        },
        "analysts": {"market": "", "sentiment": "", "news": "", "fundamentals": ""},
        "research": {"bull": "", "bear": "", "manager": ""},
        "trading": {"trader": ""},
        "risk": {
            "aggressive": "",
            "conservative": "",
            "neutral": "",
            "portfolio_manager": "",
        },
        "notes": notes,
    }
    stub_path.write_text(json.dumps(stub, ensure_ascii=False, indent=2), encoding="utf-8")
    return stub_path


def collect_one(
    ticker: str, as_of: str, lookback_days: int, with_news: bool, with_social: bool = True,
    with_options: bool = True,
) -> dict:
    """采集单只标的的全部免费证据，写出 .md 与 .json。"""
    route = _get_router()
    ticker = ticker.upper()

    start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=lookback_days)).isoformat()
    health: dict[str, str] = {}
    stats: dict = {}
    blocks: list[str] = []

    blocks.append(f"# 证据包：{ticker}")
    blocks.append(
        f"- 采集日期: {as_of}\n"
        f"- 行情窗口: {start} ~ {as_of}（{lookback_days} 自然日）\n"
        f"- 数据来源: TradingAgents 内置数据层（免费通道）\n"
        f"- 说明: 本文件不含任何 LLM 输出，纯原始证据。"
    )

    # --- 1. 行情 ---
    status, text = _safe_call("get_stock_data", route, "get_stock_data", ticker, start, as_of)
    price_block, stats = _price_summary(text)
    health["get_stock_data"] = status
    blocks.append(f"## 1. 行情与价格结构\n\n```\n{price_block}\n```")

    # --- 2. 技术指标 ---
    ind_lines = []
    for ind in TECH_INDICATORS:
        st, txt = _safe_call("get_indicators", route, "get_indicators", ticker, ind, as_of, _INDICATOR_LOOKBACK)
        health[f"indicator:{ind}"] = st
        ind_lines.append(f"### {ind}\n```\n{_compact_series(txt)}\n```")
    blocks.append("## 2. 技术指标\n\n" + "\n\n".join(ind_lines))

    # --- 3. 基本面 ---
    st, txt = _safe_call("get_fundamentals", route, "get_fundamentals", ticker, as_of)
    # ★ 2026-10-19：vendor 对**历史基准日**会「拒答」§3（正文是一段 withheld 声明），
    #   但 _safe_call 只看调用是否抛错，仍判 ok ⇒ 健康度照报全绿（铁律 3 的通道级形态）。
    #   0700.HK 实测：健康度 29/32，§3 实际不可用，只有缺口台账发现。
    #   ⇒ 正文命中 withheld/拒答 时把状态降为 withheld，让健康度与非全绿清单如实反映。
    if st == "ok" and re.search(r"withheld|拒答|point-in-time fundamentals", str(txt), re.I):
        st = "withheld"
    health["get_fundamentals"] = st
    sanity = _fundamentals_sanity(txt)
    # 注意：不要把校验结果写进 health —— 它是「提示」不是「通道」，
    # 写进去会让分母 +1（如 29/30），看起来像掉了一个通道。
    blocks.append(
        f"## 3. 基本面快照\n\n```\n{txt}\n```\n"
        + (f"\n```\n{sanity.strip()}\n```\n" if sanity else "")
    )

    # --- 4. 三大财务报表 ---
    for idx, (label, method, key) in enumerate(
        (
            ("利润表（年度）", "get_income_statement", "income"),
            ("资产负债表（年度）", "get_balance_sheet", "balance"),
            ("现金流量表（年度）", "get_cashflow", "cashflow"),
        ),
        1,
    ):
        st, txt = _safe_call(method, route, method, ticker, "annual")
        health[method] = st
        # 章节号必须细分（原实现三张表都写成 "## 4."，编号冲突）
        blocks.append(
            f"## 4.{idx} {label}\n\n```\n{_compact_statement(txt, key)}\n```"
        )

    # --- 5. 新闻 ---
    if with_news:
        st, txt = _safe_call("get_news", route, "get_news", ticker, start, as_of)
        health["get_news"] = st
        blocks.append(f"## 5. 个股新闻\n\n{txt}")

        st, txt = _safe_call("get_global_news", route, "get_global_news", as_of, 7, 10)
        health["get_global_news"] = st
        blocks.append(f"## 6. 全球宏观新闻\n\n{txt}")
    else:
        health["get_news"] = "skipped"
        health["get_global_news"] = "skipped"

    # --- 7. 社媒情绪（StockTwits + Reddit）---
    # 这两个来源由 sentiment_analyst 直接调用（不走 vendor 路由），
    # 且其内部窗口固定为最近 7 天，这里保持一致。
    if with_social:
        social_start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=7)).isoformat()
        social_lines = []
        for label, fn in (
            ("StockTwits", _stocktwits_block),
            ("Reddit", _reddit_block),
        ):
            st, txt = _safe_call(label, fn, ticker, social_start, as_of)
            health[f"social:{label}"] = st
            social_lines.append(f"### {label}\n{txt}")
        blocks.append(
            f"## 7. 社媒情绪（窗口 {social_start} ~ {as_of}）\n\n" + "\n\n".join(social_lines)
        )
    else:
        health["social:StockTwits"] = "skipped"
        health["social:Reddit"] = "skipped"

    # --- 8. 内部人交易 ---
    st, txt = _safe_call("get_insider_transactions", route, "get_insider_transactions", ticker)
    health["get_insider_transactions"] = st
    blocks.append(f"## 8. 内部人交易\n\n```\n{txt}\n```")

    # --- 9. 预测市场 ---
    pm_lines = []
    for topic in PREDICTION_TOPICS:
        st, txt = _safe_call("get_prediction_markets", route, "get_prediction_markets", topic)
        health[f"prediction:{topic}"] = st
        pm_lines.append(f"### {topic}\n{txt}")
    blocks.append("## 9. 预测市场（Polymarket 隐含概率）\n\n" + "\n\n".join(pm_lines))

    # --- 10. 宏观指标 ---
    macro_lines = []
    for alias in MACRO_ALIASES:
        # FRED 是瞬时故障最多的通道（TLS 握手 / 连接重置）。
        # 2026-10-11 起重试统一由 `_safe_call` 的默认值 `_NET_RETRIES` 提供，
        # 不再在此处写死数字（原先写死 2 ⇒ 与其它通道口径不一致）。
        st, txt = _safe_call("get_macro_indicators", route, "get_macro_indicators",
                             alias, as_of, 365)
        health[f"macro:{alias}"] = st
        macro_lines.append(f"### {alias}\n```\n{_compact_macro(txt)}\n```")
    blocks.append("## 10. 宏观经济指标（FRED）\n\n" + "\n\n".join(macro_lines))

    # --- 11/12. 2026-09-17 新增的两个补充通道 ---
    # 背景：上一轮 GOOG 报告（2026-09-16）在「数据缺口」里点名
    # 「个股采集器没有期权通道，少掉一整个维度」。本轮把该维度补上。
    if with_options:
        # --- 11. 期权市场内部结构（标的自身的期权链）---
        # ★★ 「时点闸门」前置检查（2026-09-18 新增）。
        #    期权链只在美东 09:30–16:00 实时刷新；盘前/盘后采到的是残留快照，
        #    整段 IV / 偏斜 / P-C 都会不可用。此前要**跑完整条采集**（个股数分钟、
        #    指数 10~16 分钟）才在末尾发现，白跑一次。现在把它提到调用之前。
        #    ⚠️ 这是「闸门在正确的时间误放/误伤」这一类问题的第四次复现
        #    （NDX×2 / SPX / SPCX），故改为入口即报。
        try:
            import zoneinfo
            _n = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
            _h = _n.hour + _n.minute / 60.0
            if _n.weekday() < 5 and 9.5 <= _h < 16.0:
                print(f"  ✓ 期权时点闸门：美东 {_n:%H:%M} 处常规交易时段，期权链应实时刷新")
            else:
                _phase = ("盘前" if _h < 9.5
                          else ("盘后" if _n.weekday() < 5 else "非交易日"))
                print(f"  ⚠️⚠️ 期权时点闸门：当前美东 {_n:%m-%d %H:%M} 属**{_phase}** —— "
                      f"期权链此时**不刷新**，本次采到的 IV / 偏斜大概率整体陈旧、等级为 `NONE`。"
                      f" **建议改在美东 09:30–16:00 重采。**")
        except Exception as _gate_exc:  # noqa: BLE001
            # ★ 不静默：闸门自身出错必须可见，否则等于没装
            #   （2026-09-18 实测：曾因 zoneinfo 未导入抛 NameError 被 pass 吞掉）
            print(f"  ⚠️ 期权时点闸门自身异常（{type(_gate_exc).__name__}: {_gate_exc}）"
                  f" —— 无法判定交易时段，请人工确认采集时点")
        try:
            from wb_analysis.collect_index import fetch_option_structure

            opts = _retry(fetch_option_structure, ticker)
            if opts.get("error"):
                health["option_structure"] = "error"
            else:
                grade = opts.get("iv_grade", "NONE")
                fresh = opts.get("freshness") or {}
                health["option_structure"] = "ok"
                health["option_iv"] = ("ok" if grade == "FULL"
                                       else (f"partial({grade})"
                                             if grade in ("SKEW_ONLY", "ATM_ONLY",
                                                          "PARTIAL_2SIDE", "PARTIAL")
                                             else "unavailable"))
                if opts.get("skew_available"):
                    health["option_skew"] = "ok"
                if opts.get("oi_note"):
                    health["option_oi"] = "unavailable"
                if fresh.get("stale"):
                    health["option_quote_freshness"] = "stale"
                elif fresh.get("n_fresh"):
                    health["option_quote_freshness"] = "ok"
            blocks.append(
                f"## 11. 期权市场内部结构（{ticker} 自身期权链）\n\n"
                + _render_option_block(ticker, opts)
            )
        except Exception as exc:  # noqa: BLE001
            health["option_structure"] = "fail"
            blocks.append(f"## 11. 期权市场内部结构（{ticker} 自身期权链）\n\n"
                          f"(不可用: {type(exc).__name__}: {exc})")

        # --- 12. 波动率与债券代理（弥补 FRED H.15 的约一工作日滞后）---
        try:
            from wb_analysis.collect_index import fetch_volatility_proxies

            vp = _retry(fetch_volatility_proxies, as_of)
            health["vol_proxies"] = "ok" if vp.get("proxies") else "unavailable"
            blocks.append(
                "## 12. 波动率与债券代理通道（弥补 FRED 发布滞后）\n\n"
                "- **为什么单独列一节**：FRED 的 ``VIXCLS`` / ``DGS10`` 属 H.15 系列，"
                "有约**一个工作日**的发布滞后，最新观测常停在采集日的前一两天。"
                "本节用 yfinance 的同标的日线 OHLC 补上最近几个交易日的"
                "**当日盘中区间与收盘位置**。\n"
                "- **口径限制（必须声明）**：``^VIX`` / ``^VXN`` 是 **30 天前瞻隐含波动率**，"
                "**不是当日已实现波动率**；ETF 代理（VIXY/VXX/UVXY）有期货展期与跟踪损耗，"
                "**不能线性换算回 VIX 点位**；债券 ETF（TLT/IEF/SHY）同理，"
                "只能定性说明久期端资金流向。\n\n"
                + _render_vol_proxy_block(vp)
            )
        except Exception as exc:  # noqa: BLE001
            health["vol_proxies"] = "fail"
            blocks.append("## 12. 波动率与债券代理通道（弥补 FRED 发布滞后）\n\n"
                          f"(不可用: {type(exc).__name__}: {exc})")

    # --- 13. 最新交易日实时收盘补充（日线接口的当日滞后）---
    try:
        rt_md, rt_stats = _retry(_realtime_close_block, ticker, as_of)
        stats["realtime"] = rt_stats
        health["realtime_close"] = "ok" if rt_stats.get("realtime_price") else "unavailable"
        blocks.append("## 13. 最新交易日实时收盘补充\n\n" + rt_md)
    except Exception as exc:  # noqa: BLE001
        health["realtime_close"] = "fail"
        blocks.append("## 13. 最新交易日实时收盘补充\n\n"
                      f"(不可用: {type(exc).__name__}: {exc})")

    # --- 14. 盘前 / 盘后（扩展时段）---
    # ★ 2026-10-21 新增：事件驱动的价格发现大量发生在扩展时段，§13 只覆盖常规时段。
    try:
        eh_md, eh_stats = _retry(_extended_hours_block, ticker, as_of)
        stats["extended_hours"] = eh_stats
        health["extended_hours"] = "ok" if eh_stats.get("sessions") else "unavailable"
        blocks.append("## 14. 盘前 / 盘后（扩展时段）\n\n" + eh_md)
    except Exception as exc:  # noqa: BLE001
        health["extended_hours"] = "fail"
        blocks.append("## 14. 盘前 / 盘后（扩展时段）\n\n"
                      f"(不可用: {type(exc).__name__}: {exc})")

    # --- 健康度汇总 ---
    # ⚠️ 判据是 ``!= "ok"`` 而不是白名单 ``in ("fail", "unavailable")``：
    # 2026-09-17 起健康度会登记 ``partial(...)`` / ``stale`` / ``error`` 等降级状态，
    # 若仍用白名单，这些状态会被排除在「失败清单」之外，汇总行照报「29 / 29 成功」
    # —— 那正是本项目反复踩过的「假绿」。
    ok = sum(1 for v in health.values() if v == "ok")
    bad = [k for k, v in health.items() if v != "ok"]
    summary = [
        f"## 通道健康度\n",
        f"- 成功: {ok} / {len(health)}",
    ]
    if bad:
        summary.append("- **非全绿通道**: " + "、".join(f"{k}={health[k]}" for k in bad))
        if any(k.startswith("macro:") for k in bad):
            summary.append(
                "- 提示: FRED 宏观通道需要免费的 FRED_API_KEY，"
                "见 https://fred.stlouisfed.org/docs/api/api_key.html"
            )
        summary.append(
            "- ⚠️ 「非全绿」不等于「数据缺口」：可能是**上游发布滞后**（可用替代通道补）、"
            "**采集时点不对**（如期权链只在美东盘中刷新）、或**上游真实未发布**。"
            "定性方法见项目铁律的「数据缺口三分类」（A 上游真缺 / B 阈值误伤 / C 采集器 bug）。"
        )
    blocks.append("\n".join(summary))

    md = "\n\n---\n\n".join(blocks) + "\n"

    EV_DIR.mkdir(parents=True, exist_ok=True)
    md_path = EV_DIR / f"{ticker}_{as_of}.md"
    json_path = EV_DIR / f"{ticker}_{as_of}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "ticker": ticker,
                "as_of": as_of,
                "window_start": start,
                "lookback_days": lookback_days,
                "price_stats": stats,
                "channel_health": health,
                "evidence_md": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    stub = _emit_stub(ticker, as_of, md_path, health)

    return {
        "ticker": ticker,
        "md": md_path,
        "json": json_path,
        "stub": stub,
        "health": health,
        "stats": stats,
    }


def today_eastern() -> str:
    """返回**美东当日**（数据源 `today` 的口径），而非本机日期。

    ★ 2026-10-11（O3）修正：`--date` 的默认值原为 `_clock.market_date()`＝**本机日期**。
    北京时区比美东早 12~13 小时 ⇒ 本机日期**天然比美东当日早一天**（例：
    本机 10-11 10:15 = 美东 10-10 22:15）。而数据源的 `today` 走美东日历
    ⇒ 默认值本身就是一个「未来日期」，会静默触发下面的 §3 扣留。
    """
    import zoneinfo
    return dt.datetime.now(zoneinfo.ZoneInfo("America/New_York")).date().isoformat()


def date_caliber_guard(date_str: str, allow_stale: bool) -> bool:
    """★ O3 守卫：`--date` 口径＝**美东当日**，不是「最后一根 bar 的日期」。

    血泪（2026-10-05 NFLX 轮实测）：传**早于**美东当日的日期时，数据源会
    **静默扣留 §3 估值快照**（PE / PB / 市值 / 52 周区间整段消失），而
    **通道健康度照读 35/35** —— 因为调用确实「成功」、返回的是一段**非空的
    拒答说明**，所以 channel_health / 空段落检测 / 占位符检测**全都抓不到**。
    这类「外观正常的数据缺失」正是本项目最贵的失败模式（铁律 3 同类）。

    返回 True 表示可继续采集。
    """
    import zoneinfo
    try:
        want = dt.date.fromisoformat(date_str)
    except ValueError:
        print(f"✗ --date 不是合法日期：{date_str!r}（应为 YYYY-MM-DD）")
        return False
    now_ny = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    today_ny = now_ny.date()
    print(f"[口径检查] --date={want} ｜ 美东当日={today_ny}"
          f"（采集时点 美东 {now_ny:%Y-%m-%d %H:%M %a}）")
    if want == today_ny:
        print("  ✓ 口径一致：--date 即美东当日。")
        return True
    if want > today_ny:
        print(f"  ✗ --date 晚于美东当日 {(want - today_ny).days} 天 —— 属未来日期，"
              f"数据源不可能存在该日数据 ⇒ 拒绝执行。")
        return False
    print(f"  ⚠️ --date 早于美东当日 {(today_ny - want).days} 天。"
          f"**这正是「§3 估值快照被静默扣留」的触发条件**（通道健康度仍会显示全绿）。")
    print(f"     ⇒ 若确为按历史基准日复盘，请加 `--allow-stale-date` 显式确认；"
          f"否则请改用 `--date {today_ny}` 重跑。")
    return bool(allow_stale)


def main() -> int:
    os.chdir(PROJECT_ROOT)
    ap = argparse.ArgumentParser(description="TradingAgents 免费证据采集器（不调用 LLM）")
    ap.add_argument("tickers", nargs="+", help="股票代码，可多个，如 NVDA AMD")
    ap.add_argument("--date", default=None,
                    help="基准日期 YYYY-MM-DD。口径＝**美东当日**（数据源的 today），"
                         "**不是**最后一根 bar 的日期；默认取美东当日（**非本机日期**）")
    ap.add_argument("--allow-stale-date", action="store_true",
                    help="显式确认 `--date` 早于美东当日（会触发 §3 快照扣留，默认拒绝）")
    ap.add_argument("--lookback", type=int, default=365, help="行情/新闻回溯自然日数")
    ap.add_argument("--no-news", action="store_true", help="跳过新闻通道（更快）")
    ap.add_argument("--no-social", action="store_true", help="跳过 StockTwits/Reddit 通道（更快）")
    ap.add_argument("--no-options", action="store_true",
                    help="跳过期权链/波动率代理通道（期权链需较长时间）")
    args = ap.parse_args()

    if args.date is None:
        args.date = today_eastern()
    if not date_caliber_guard(args.date, args.allow_stale_date):
        return 2

    print(f"[证据采集] 标的: {', '.join(t.upper() for t in args.tickers)}  基准日: {args.date}")
    results = []
    for tk in args.tickers:
        try:
            res = collect_one(tk, args.date, args.lookback, not args.no_news, not args.no_social,
                              not args.no_options)
            ok = sum(1 for v in res["health"].values() if v == "ok")
            n_bad = len(res["health"]) - ok
            flag = "" if n_bad == 0 else "  ⚠ 非全绿"
            print(f"  ✓ {res['ticker']}: {ok}/{len(res['health'])} 通道成功{flag} -> {res['md'].name}")
            results.append(res)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {tk}: 采集异常 {type(exc).__name__}: {exc}")
            traceback.print_exc()

    print(f"\n证据包目录: {EV_DIR}")
    for res in results:
        print(f"  {res['md']}")
        if res.get("stub"):
            print(f"  → 已生成分析骨架: {res['stub']}")
    if results:
        print(
            "\n下一步：按 wb_analysis/FRAMEWORK.md 第 4 节契约填写分析 JSON，"
            "然后运行 python wb_analysis/assemble.py <TICKER> 渲染报告树。"
        )
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
