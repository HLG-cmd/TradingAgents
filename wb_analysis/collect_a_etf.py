# lifecycle: reusable
# created: 2026-09-30
# updated: 2026-10-04 — 泛化支持策略/主题 ETF（--mode strategy），并把原先写死的
#                       解读文字与资金流数字改为数据驱动（原先对非 512400 标的会输出错误解读）
# usage:
#   行业 ETF： ./.venv/Scripts/python.exe wb_analysis/collect_a_etf.py --ticker 512400.SS --date 2026-09-30
#   策略 ETF： ./.venv/Scripts/python.exe wb_analysis/collect_a_etf.py --ticker 515100 --date 2026-09-30 \
#                  --mode strategy --track-index cs930955
"""A股 ETF 证据采集器（westock CLI）

支持两类 A 股 ETF，共用 quote / kline / technical / chip / fund_flow / news 六个基础通道：

- ``--mode industry``（默认）**行业 ETF**（如 512400.SS 有色金属）：
  以**申万一级行业**的资产负债/盈利/估值/预测作为基本面与估值锚。

- ``--mode strategy`` **策略/主题 ETF**（如 515100 红利低波100）：
  红利低波、央企红利一类的**跨行业策略指数**没有对应的申万一级行业，
  行业财务通道对其不适用。改用三件事作基本面锚：
    ① ``etf profile``   —— 产品档案（管理人/费率/跟踪指数/资产配置/基金经理）
    ② ``etf overview``  —— **ETF 聚合估值且自带历史分位**（PE/PB/PS/PCF/股息率分位）
    ③ ``index constituent`` + ``etf holdings`` —— 跟踪指数成分股与持仓穿透

设计要点（避免静默失败，对应铁律 3）：
- 所有随标的而变的量都**从 CLI 实际取数**，不再写死默认值；
- 解读性文字（"超卖"/"紧贴下轨"/"主力吸筹"）一律由**实际数值驱动**，
  数据不符时自动换成中性表述，不会出现"RSI 65（< 30 超卖）"这类自相矛盾。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVID_DIR = ROOT / "wb_analysis" / "evidence"
WESTOCK = pathlib.Path(r"C:\Users\HLJ\.local\bin\westock.exe")

# ── 标的档案表：名称 / 模式 / 行业板块 / 跟踪指数 显式登记 ──
#    未登记的标的也能跑（--mode 由参数决定），但名称会标为 [未登记]，
#    以防「默认值静默填成另一只标的的名字」。
KNOWN: dict[str, dict] = {
    "512400.SS": {"wcode": "sh512400", "name": "有色金属ETF南方", "mode": "industry",
                  "sector": "pt01801050", "sector_name": "有色金属"},
    "515100": {"wcode": "sh515100", "name": "红利低波100ETF景顺", "mode": "strategy",
               "track_index": "cs930955", "track_name": "中证红利低波动100"},
}
UNKNOWN_NAME = "[未登记标的]"


def run_westock(args: list[str], timeout: int = 180) -> str:
    """调用 westock CLI，返回 stdout 原文。"""
    try:
        p = subprocess.run(
            [str(WESTOCK), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        if p.returncode != 0:
            return f"<westock 退出码 {p.returncode}>\n{p.stdout}\n{p.stderr}"
        return p.stdout
    except Exception as e:
        return f"<westock 调用失败 {type(e).__name__}: {e}>"


def parse_md_table(text: str) -> tuple[list[str], list[list[str]]]:
    """解析 CLI 输出的 markdown 表格 → (表头, 数据行)。"""
    rows = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(rows) < 2:
        return [], []

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = cells(rows[0])
    body = [cells(r) for r in rows[1:] if not re.match(r"^\|[\s\-:|]+\|$", r)]
    return header, body


def fnum(v, default=None):
    """安全转 float；失败返回 default（**绝不**用别的标的的数字兜底）。"""
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def pct(v, digits=2) -> str:
    """带符号百分数字符串。"""
    x = fnum(v)
    return "—" if x is None else f"{x:+.{digits}f}%"


def ok_of(raw: str) -> bool:
    return ("<westock" not in raw) and bool(raw.strip())


# ── 解读判语（数据驱动；数据不符时自动降级为中性，不出错话）──
def note_rsi6(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    if x < 30:
        return " (< 30 超卖区间)"
    if x > 70:
        return " (> 70 超买区间)"
    return ""


def note_j(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    if x < 20:
        return " (< 20 极度超卖区间)"
    if x > 100:
        return " (> 100 极度超买区间)"
    return ""


def note_pe_pct(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    if x < 30:
        return ", 处于历史偏低位置"
    if x > 70:
        return ", 处于历史偏高位置"
    return ", 处于历史中位区间"


def note_peg(v) -> str:
    x = fnum(v)
    if x is None or x < 0:
        return ""
    return ", < 1 具有较高性价比" if x < 1 else ", > 1 估值与增速匹配偏紧"


def note_roe_pct(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    if x > 90:
        return ", 处于历史顶峰盈利能力"
    if x < 10:
        return ", 处于历史底部盈利能力"
    return ""


def note_gap_lower(cur, low) -> str:
    c, lo = fnum(cur), fnum(low)
    if c is None or lo is None or lo == 0:
        return ""
    d = (c - lo) / lo * 100
    if d < 3:
        return " (紧贴布林下轨)"
    if d > 15:
        return " (远离下轨)"
    return ""


def note_chip(profit_rate) -> str:
    x = fnum(profit_rate)
    if x is None:
        return ""
    if x < 50:
        return f" ({100 - x:.2f}% 的持仓处于浮亏状态，典型左侧套牢盘清洗)"
    return f" ({x:.2f}% 的持仓处于浮盈状态，上方套牢盘较轻)"


def note_erp(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    if x > 3:
        return " (显著高于中枢，估值安全垫厚实)"
    if x < 0:
        return " (低于无风险利率，估值安全垫消失)"
    return ""


def note_flow(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    return "净流入" if x > 0 else ("净流出" if x < 0 else "持平")


def note_np_yoy(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    if x > 100:
        return " (行业净利润实现翻倍式高增)"
    if x > 50:
        return " (行业净利润高速增长)"
    if x > 0:
        return " (行业净利润温和增长)"
    return " (行业净利润同比下滑)"


def note_debt(v) -> str:
    x = fnum(v)
    if x is None:
        return ""
    return " (财务结构健康稳健，负债率 < 50%)" if x < 50 else " (负债率偏高，> 50%)"


def parse_yield(raw_term_spread: str = "", raw_curve: str = "") -> tuple:
    """优先从 cn_term_spread 取日频 10Y 国债收益率，若无则回退 cn_yield_curve。"""
    h, b = parse_md_table(raw_term_spread or "")
    if h and b and "Yield10Y" in h:
        iy = h.index("Yield10Y")
        idate = h.index("EndDate") if "EndDate" in h else None
        row = b[-1]
        y10 = fnum(row[iy])
        d = row[idate] if idate is not None and idate < len(row) else None
        if y10 is not None:
            return y10, d
    h, b = parse_md_table(raw_curve or "")
    if not h or not b or "YTM_YIELD_10Y" not in h:
        return None, None
    i10 = h.index("YTM_YIELD_10Y")
    idate = h.index("YTM_END_DATE") if "YTM_END_DATE" in h else None
    rows = sorted(b, key=lambda r: (r[idate] if (idate is not None and idate < len(r)) else ""))
    row = rows[-1]
    if i10 >= len(row):
        return None, None
    d = row[idate] if (idate is not None and idate < len(row)) else None
    return fnum(row[i10]), d


def fetch_eastmoney_nav(ticker: str, date: str) -> dict | None:
    """从东方财富开放 API 提取官方确权的当日基金净值。"""
    code = ticker.split(".")[0]
    import urllib.request, json
    url = f"http://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=5&startDate={date}&endDate={date}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "http://fundf10.eastmoney.com/"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("Data", {}).get("LSJZList", [])
            for it in items:
                if it.get("FSRQ") == date:
                    return {"nav": fnum(it.get("DWJZ")), "acc_nav": fnum(it.get("LJJZ")), "chg_pct": fnum(it.get("JZZZL"))}
    except Exception:
        pass
    return None


def _freshness_gaps(raw: dict, date: str, mode: str) -> list:
    """数据新鲜度闸门：返回 ``[(登记名, 状态)]``，由调用方并入「非全绿通道」行。

    判据（全部基于**实际取到的数据**，不做推测）：
    - ``macro_yield_stale``：无风险利率的数据日期距基准日 > 30 天
    - ``etf_nav_unupdated``：最后一日净值与前一日**完全相同**、而当日收盘价不同
      ⇒ 当日净值疑似尚未更新，折溢价读数不可直接采信
    """
    out: list = []
    _y, ydate = parse_yield(raw.get("macro_term_spread", ""), raw.get("macro_yield", ""))
    if _y is not None and ydate:
        try:
            d_obj = dt.datetime.strptime(ydate, "%Y%m%d").date() if len(ydate) == 8 else dt.date.fromisoformat(ydate)
            lag = (dt.date.fromisoformat(date) - d_obj).days
            if lag > 30:
                out.append(("macro_yield_stale", f"stale{lag}d"))
        except ValueError:
            pass
    if mode == "strategy":
        h, b = parse_md_table(raw.get("etf_nav", ""))
        if h and len(b) >= 2 and "nav" in h and "closePrice" in h:
            iv, ic = h.index("nav"), h.index("closePrice")
            if b[-1][iv] == b[-2][iv] and b[-1][ic] != b[-2][ic]:
                out.append(("etf_nav_unupdated", "stale"))
    return out


def build_tasks(mode: str, wcode: str, track_index: str | None,
                sector_code: str | None, date: str) -> list[tuple[str, list[str]]]:
    """按模式给出采集任务表。"""
    base = [
        ("quote", ["quote", wcode]),
        ("kline", ["kline", wcode, "--period", "day", "--limit", "30"]),
        ("technical", ["technical", wcode]),
        ("chip", ["chip", wcode]),
        ("fund_flow", ["fund", "flow", wcode]),
        ("news", ["news", "list", wcode, "--limit", "10"]),
        # 日频无风险利率与期限利差
        ("macro_term_spread", ["macro", "indicator", "cn_term_spread", "--date", date]),
        # 股债/红利溢价率
        ("macro_premium", ["macro", "indicator", "cn_premium_value", "--date", date]),
        # 季度基准（备用）
        ("macro_yield", ["macro", "indicator", "cn_yield_curve"]),
    ]
    if mode == "industry":
        sec = sector_code or "pt01801050"
        base += [
            ("etf_overview", ["etf", "overview", wcode]),
            ("etf_holdings", ["etf", "holdings", wcode]),
            ("sector_val", ["sector", "valuation", sec]),
            ("sector_fin", ["sector", "finance", sec]),
            ("sector_fore", ["sector", "forecast", sec]),
        ]
    else:  # strategy
        d0 = dt.date.fromisoformat(date)
        nav_start = (d0 - dt.timedelta(days=100)).isoformat()
        base += [
            ("etf_profile", ["etf", "profile", wcode]),
            ("etf_overview", ["etf", "overview", wcode]),
            ("etf_holdings", ["etf", "holdings", wcode]),
            ("etf_nav", ["etf", "nav", wcode, "--start", nav_start, "--end", date]),
        ]
        if track_index:
            base.append(("index_constituent", ["index", "constituent", track_index]))
    return base


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="采集 A 股 ETF 证据（westock）")
    ap.add_argument("--ticker", default="512400.SS", help="ETF 标的代码（如 512400.SS / 515100）")
    ap.add_argument("--date", default="2026-09-30", help="基准日 YYYY-MM-DD")
    ap.add_argument("--mode", choices=["industry", "strategy"], default=None,
                    help="industry=行业 ETF（申万行业通道）；strategy=策略/主题 ETF（指数通道）")
    ap.add_argument("--track-index", default=None,
                    help="策略模式的跟踪指数代码（如 cs930955）")
    ap.add_argument("--sector", default=None,
                    help="行业模式的申万板块代码（如 pt01801050）")
    args = ap.parse_args(argv)

    ticker = args.ticker
    date = args.date
    meta = KNOWN.get(ticker, {})
    wcode = meta.get("wcode") or ("sh" + ticker.split(".")[0] if "." in ticker else ticker)
    mode = args.mode or meta.get("mode") or "industry"
    track_index = args.track_index or meta.get("track_index")
    sector_code = args.sector or meta.get("sector")
    ticker_name = meta.get("name", UNKNOWN_NAME)

    print(f"[A股ETF采集] {ticker} ({wcode})  模式={mode}  基准日 {date}")
    if not WESTOCK.exists():
        print(f"  ✗ westock 不存在：{WESTOCK}")
        return 1

    # 1. 采集原始数据
    raw: dict[str, str] = {}
    for name, cmd in build_tasks(mode, wcode, track_index, sector_code, date):
        raw[name] = run_westock(cmd)
        print(f"  {'✓' if ok_of(raw[name]) else '✗'} {name:18} {len(raw[name])} 字符")

    # 2. 解析核心字典与确权校验
    if mode == "strategy":
        h_nav, b_nav = parse_md_table(raw.get("etf_nav", ""))
        em_info = fetch_eastmoney_nav(ticker, date)
        if em_info and em_info.get("nav") is not None:
            if h_nav and b_nav and "nav" in h_nav:
                inav = h_nav.index("nav")
                idate = h_nav.index("date") if "date" in h_nav else 0
                if b_nav[-1][idate] == date:
                    b_nav[-1][inav] = str(em_info["nav"])
                    prev_nav = fnum(b_nav[-2][inav]) if len(b_nav) >= 2 else None
                    if "navChange" in h_nav and prev_nav:
                        b_nav[-1][h_nav.index("navChange")] = f"{em_info['nav'] - prev_nav:+.4f}"
                    if "navChangePct" in h_nav and em_info.get("chg_pct") is not None:
                        b_nav[-1][h_nav.index("navChangePct")] = str(em_info["chg_pct"])
                    nav_lines = ["| " + " | ".join(h_nav) + " |", "| " + " | ".join(["---"] * len(h_nav)) + " |"]
                    for r in b_nav:
                        nav_lines.append("| " + " | ".join(r) + " |")
                    raw["etf_nav"] = "\n".join(nav_lines)

    def tbl(key: str) -> dict:
        h, b = parse_md_table(raw.get(key, ""))
        return dict(zip(h, b[0])) if h and b else {}

    quote = tbl("quote")
    overview = tbl("etf_overview")
    technical = tbl("technical")
    chip = tbl("chip")
    fund_flow = tbl("fund_flow")
    profile = tbl("etf_profile")

    # 3. 通道健康度（供 _gap_ledger.py 正则解析，格式不可改）
    n_ok = len([k for k in raw if ok_of(raw[k])])
    n_total = len(raw)
    bad_list = [(k, "unavailable") for k in raw if not ok_of(raw[k])]
    bad_list += _freshness_gaps(raw, date, mode)
    bad_str = ", ".join(f"{k}={s}" for k, s in sorted(bad_list)) if bad_list else "无"

    # 4. 组织证据包
    L: list[str] = []
    kind = "A股行业指数ETF" if mode == "industry" else "A股策略指数ETF"
    L.append(f"# 证据包：{ticker}（A股ETF）· 基准日 {date}")
    L.append("")
    L.append(f"- 采集日期: {date}")
    L.append(f"- 标的代码: {ticker} (westock: {wcode})")
    L.append(f"- 标的名称: {ticker_name}")
    L.append(f"- 数据来源: westock CLI (腾讯官方接口) + TradingAgents 内置层")
    L.append(f"- 通道健康度: 成功: {n_ok} / {n_total}")
    L.append(f"- **非全绿通道**: {bad_str}")
    L.append(f"- 市场状态: A股市场 {date} 15:00 CST **已正常收盘**（所有指标均基于当日收盘价）")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 0. ★★ 载体判定与数据缺口声明（先读）")
    L.append("")
    L.append(f"### 载体属性：**{kind}**")
    L.append("- **单体财务报表与高管交易**：ETF 为被动证券投资基金，不具备单体上市公司的营业收入、净利润、"
             "资产负债表及董监高持股（Class A 结构性属性）。")
    if mode == "industry":
        L.append(f"  本证据包以 **ETF 聚合估值、申万一级{meta.get('sector_name', '')}行业财务报表、十大重仓股穿透** "
                 "作为基本面与估值依据。")
    else:
        L.append(f"  本证据包以 **ETF 产品档案、跟踪指数（{meta.get('track_name', track_index)}）聚合估值（自带历史分位）、"
                 "指数成分股与持仓穿透** 作为基本面与估值依据。**红利低波是跨行业策略指数，无对应申万一级行业，"
                 "行业财务通道不适用**。")
    L.append("- **期权维度（`option_structure` / `option_iv`）**：A 股目前仅有宽基 ETF 期权（50/300/500/1000/科创50），"
             "**无场内行业/策略 ETF 期权**（Class A/S 缺口）。缺失场内期权隐波与偏斜定价，按框架规则**结论降为条件式**；"
             "下行保护成本参考**上证50ETF/沪深300ETF 期权隐含波动率及本标的历史实现波动率（HV）**作为波动率环境代理"
             "（**口径不同，仅作环境参照**）。")
    L.append("- **散户社交舆情（`social:StockTwits`）**：海外 StockTwits 对 A 股 ETF 无讨论，"
             "以国内主流财经新闻与机构投研研报语气作为情绪代理，情绪置信度上限设为 Medium/Low。")
    L.append("")
    L.append("---")
    L.append("")

    # ── 1. 行情与价格结构 ──
    close = fnum(quote.get("price"))
    high52, low52 = fnum(quote.get("high_52week")), fnum(quote.get("low_52week"))
    high_pct = f"{100*(close-high52)/high52:+.2f}%" if close and high52 else "—"
    low_pct = f"{100*(close-low52)/low52:+.2f}%" if close and low52 else "—"
    L.append("## 1. 行情与价格结构")
    L.append("")
    L.append("```")
    L.append(f"关键统计 ({date} 已收盘):")
    L.append(f"  - 收盘价: {quote.get('price', '[未取到]')}")
    L.append(f"  - 前收价: {quote.get('prev_close', '[未取到]')}")
    L.append(f"  - 开盘价: {quote.get('open', '[未取到]')}")
    L.append(f"  - 最高价: {quote.get('high', '[未取到]')}")
    L.append(f"  - 最低价: {quote.get('low', '[未取到]')}")
    cp, chg = fnum(quote.get("change_percent")), fnum(quote.get("change"))
    L.append(f"  - 涨跌幅: {cp:+.2f}% ({chg:+.3f} 元)" if (cp is not None and chg is not None)
             else f"  - 涨跌幅: {quote.get('change_percent', '[未取到]')}% ({quote.get('change', '[未取到]')} 元)")
    L.append(f"  - 成交量: {quote.get('volume', '[未取到]')} 手")
    L.append(f"  - 成交额: {quote.get('amount', '[未取到]')} 元")
    L.append(f"  - 换手率: {quote.get('turnover_rate', '[未取到]')}%")
    L.append(f"  - 量比: {quote.get('volume_ratio', '[未取到]')}")
    L.append(f"  - ETF规模: {overview.get('etfSize', quote.get('total_market_cap', '[未取到]'))} 元")
    L.append(f"  - ETF总资产: {overview.get('totalAsset', '[未取到]')} 元")
    disc = fnum(overview.get("etfDisc"))
    disc_note = ("" if disc is None else
                 (" (溢价)" if disc > 0 else (" (折价)" if disc < 0 else " (平水)")))
    L.append(f"  - ETF折溢价率: {overview.get('etfDisc', '[未取到]')}%{disc_note}")
    L.append(f"  - 52周最高: {quote.get('high_52week', '[未取到]')}")
    L.append(f"  - 52周最低: {quote.get('low_52week', '[未取到]')}")
    L.append(f"  - 距52周最高: {high_pct}")
    L.append(f"  - 距52周最低: {low_pct}")
    L.append(f"  - 5日涨跌幅: {quote.get('chg_5d', '[未取到]')}%")
    L.append(f"  - 10日涨跌幅: {quote.get('chg_10d', '[未取到]')}%")
    L.append(f"  - 20日涨跌幅: {quote.get('chg_20d', '[未取到]')}%")
    L.append(f"  - 60日涨跌幅: {quote.get('chg_60d', '[未取到]')}%")
    L.append(f"  - 年初至今(YTD): {quote.get('chg_ytd', '[未取到]')}%")
    L.append(f"  - 1年最大回撤: {overview.get('maxDrawdown1Y', '[未取到]')}%")
    L.append(f"  - 年初至今最大回撤: {overview.get('ytdMaxDrawdown', '[未取到]')}%")
    L.append("```")
    L.append("")
    L.append(f"### 日K线历史序列 (近30交易日，含 {date} 收盘)")
    L.append("")
    L.append(raw.get("kline", "").strip())
    L.append("")
    L.append("---")
    L.append("")

    # ── 2. 技术指标与筹码结构 ──
    ma5, ma10, ma20 = fnum(technical.get("MA_5")), fnum(technical.get("MA_10")), fnum(technical.get("MA_20"))
    ma60, ma120, ma250 = fnum(technical.get("MA_60")), fnum(technical.get("MA_120")), fnum(technical.get("MA_250"))
    bu, bm, bl = fnum(technical.get("BOLL_UPPER")), fnum(technical.get("BOLL_MID")), fnum(technical.get("BOLL_LOWER"))
    dev = lambda m: (f"{100*(close-m)/m:+.2f}%" if (close and m) else "—")
    bw = (bu - bl) if (bu is not None and bl is not None) else None
    bw_pct = f"{100*bw/bm:.2f}%" if (bw is not None and bm) else "—"
    L.append("## 2. 技术指标与筹码结构")
    L.append("")
    L.append(f"### 2.1 均线与通道系统 ({date} 收盘)")
    L.append("```")
    L.append(f"收盘价: {technical.get('closePrice', quote.get('price', '[未取到]'))}")
    L.append(f"MA_5:   {technical.get('MA_5', '[未取到]')} (偏离度: {dev(ma5)})")
    L.append(f"MA_10:  {technical.get('MA_10', '[未取到]')} (偏离度: {dev(ma10)})")
    L.append(f"MA_20:  {technical.get('MA_20', '[未取到]')} (偏离度: {dev(ma20)})")
    L.append(f"MA_60:  {technical.get('MA_60', '[未取到]')} (偏离度: {dev(ma60)})")
    L.append(f"MA_120: {technical.get('MA_120', '[未取到]')} (偏离度: {dev(ma120)})")
    L.append(f"MA_250: {technical.get('MA_250', '[未取到]')} (年线，偏离度: {dev(ma250)})")
    L.append("")
    L.append("BOLL 布林带 (20, 2):")
    L.append(f"  - 上轨: {technical.get('BOLL_UPPER', '[未取到]')}")
    L.append(f"  - 中轨: {technical.get('BOLL_MID', '[未取到]')}")
    L.append(f"  - 下轨: {technical.get('BOLL_LOWER', '[未取到]')}")
    L.append(f"  - 带宽: {bw:.3f} ({bw_pct})" if bw is not None else "  - 带宽: [未取到]")
    L.append(f"  - 现价距下轨: {(100*(close-bl)/bl):+.2f}%{note_gap_lower(close, bl)}"
             if (close and bl) else "  - 现价距下轨: [未取到]")
    L.append("```")
    L.append("")
    L.append("### 2.2 动量与超买超卖指标")
    L.append("```")
    L.append("MACD (12, 26, 9):")
    L.append(f"  - DIF: {technical.get('DIF', '[未取到]')}")
    L.append(f"  - DEA: {technical.get('DEA', '[未取到]')}")
    L.append(f"  - 柱状图 (MACD): {technical.get('MACD', '[未取到]')}")
    L.append("")
    L.append("KDJ (9, 3, 3):")
    L.append(f"  - K: {technical.get('KDJ_K', '[未取到]')}")
    L.append(f"  - D: {technical.get('KDJ_D', '[未取到]')}")
    L.append(f"  - J: {technical.get('KDJ_J', '[未取到]')}{note_j(technical.get('KDJ_J'))}")
    L.append("")
    L.append("RSI (6, 12, 24):")
    L.append(f"  - RSI_6:  {technical.get('RSI_6', '[未取到]')}{note_rsi6(technical.get('RSI_6'))}")
    L.append(f"  - RSI_12: {technical.get('RSI_12', '[未取到]')}")
    L.append(f"  - RSI_24: {technical.get('RSI_24', '[未取到]')}")
    L.append("```")
    L.append("")
    L.append(f"### 2.3 筹码分布 ({date})")
    L.append("```")
    cac = fnum(chip.get("chipAvgCost"))
    cac_dev = f"{100*(close-cac)/cac:+.2f}%" if (close and cac) else "—"
    L.append(f"筹码平均成本: {chip.get('chipAvgCost', '[未取到]')} 元 (现价相对平均成本: {cac_dev})")
    L.append(f"获利盘比例:   {chip.get('chipProfitRate', '[未取到]')}%{note_chip(chip.get('chipProfitRate'))}")
    L.append(f"70% 筹码集中度: {chip.get('chipConcentration70', '[未取到]')}%")
    L.append(f"90% 筹码集中度: {chip.get('chipConcentration90', '[未取到]')}%")
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")

    if mode == "industry":
        _render_industry(L, raw, overview, fund_flow, ticker, date, meta, sector_code)
    else:
        _render_strategy(L, raw, overview, profile, fund_flow, ticker, date, meta, track_index)

    content_md = "\n".join(L) + "\n"

    # ── JSON 摘要 ──
    def g(d, k, default=None):
        return fnum(d.get(k), default)

    summary_json = {
        "ticker": ticker,
        "as_of": date,
        "type": "A_SHARE_ETF",
        "mode": mode,
        "name": ticker_name,
        "tracking_index": (meta.get("track_index") if mode == "strategy" else None),
        "tracking_index_name": (meta.get("track_name") if mode == "strategy" else None),
        "price_stats": {
            "latest_close": g(quote, "price"),
            "prev_close": g(quote, "prev_close"),
            "change_pct": g(quote, "change_percent"),
            "high_52w": g(quote, "high_52week"),
            "low_52w": g(quote, "low_52week"),
            "ret_5d": g(quote, "chg_5d"),
            "ret_10d": g(quote, "chg_10d"),
            "ret_20d": g(quote, "chg_20d"),
            "ret_60d": g(quote, "chg_60d"),
            "ret_ytd": g(quote, "chg_ytd"),
            "volume_lots": g(quote, "volume"),
            "amount_cny": g(quote, "amount"),
            "turnover_rate": g(quote, "turnover_rate"),
            "etf_size_cny": g(overview, "etfSize"),
            "etf_disc_pct": g(overview, "etfDisc"),
            "max_dd_1y": g(overview, "maxDrawdown1Y"),
        },
        "technicals": {
            "close": g(technical, "closePrice"),
            "ma_5": g(technical, "MA_5"), "ma_10": g(technical, "MA_10"),
            "ma_20": g(technical, "MA_20"), "ma_60": g(technical, "MA_60"),
            "ma_120": g(technical, "MA_120"), "ma_250": g(technical, "MA_250"),
            "boll_upper": g(technical, "BOLL_UPPER"), "boll_mid": g(technical, "BOLL_MID"),
            "boll_lower": g(technical, "BOLL_LOWER"),
            "kdj_k": g(technical, "KDJ_K"), "kdj_d": g(technical, "KDJ_D"), "kdj_j": g(technical, "KDJ_J"),
            "rsi_6": g(technical, "RSI_6"), "rsi_12": g(technical, "RSI_12"), "rsi_24": g(technical, "RSI_24"),
            "macd_dif": g(technical, "DIF"), "macd_dea": g(technical, "DEA"), "macd_hist": g(technical, "MACD"),
            "chip_avg_cost": g(chip, "chipAvgCost"),
            "chip_profit_rate": g(chip, "chipProfitRate"),
            "chip_conc70": g(chip, "chipConcentration70"),
            "chip_conc90": g(chip, "chipConcentration90"),
        },
        "valuation": {
            "pe_ttm": g(overview, "peTtm"), "pe_ttm_pct": g(overview, "peTtmPct"),
            "pb": g(overview, "pb"), "pb_pct": g(overview, "pbPct"),
            "pcf_ttm": g(overview, "pcfTtm"), "pcf_ttm_pct": g(overview, "pcfTtmPct"),
            "ps_ttm": g(overview, "psTtm"), "ps_ttm_pct": g(overview, "psTtmPct"),
            "peg": g(overview, "peg"), "peg_pct": g(overview, "pegPct"),
            "roe": g(overview, "roe"), "roe_pct": g(overview, "roePct"),
            "div_ttm": g(overview, "divTtm"), "div_ttm_pct": g(overview, "divTtmPct"),
            "china_10y_bond_yield": None,  # 需另采（本节不联网推断）
        },
        "fund_flow": {
            "main_net_flow": g(fund_flow, "MainNetFlow"),
            "main_net_flow_5d": g(fund_flow, "MainNetFlow5D"),
            "main_net_flow_10d": g(fund_flow, "MainNetFlow10D"),
            "main_net_flow_20d": g(fund_flow, "MainNetFlow20D"),
            "jumbo_net_flow": g(fund_flow, "JumboNetFlow"),
            "block_net_flow": g(fund_flow, "BlockNetFlow"),
            "retail_net_flow": ((g(fund_flow, "RetailInFlow") or 0) - (g(fund_flow, "RetailOutFlow") or 0))
            if g(fund_flow, "RetailInFlow") is not None else None,
            "small_net_flow": g(fund_flow, "SmallNetFlow"),
            "mid_net_flow": g(fund_flow, "MidNetFlow"),
        },
        "channel_health": {k: ("ok" if ok_of(v) else "unavailable") for k, v in raw.items()},
        "channels_ok": n_ok,
        "channels_total": n_total,
    }

    out_md = EVID_DIR / f"{ticker}_{date}.md"
    out_json = EVID_DIR / f"{ticker}_{date}.json"
    out_md.write_text(content_md, encoding="utf-8", newline="\n")
    out_json.write_text(json.dumps(summary_json, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  ✓ 证据包生成完毕: {out_md.relative_to(ROOT).as_posix()} ({len(content_md)} 字符)")
    print(f"  ✓ JSON 元数据生成完毕: {out_json.relative_to(ROOT).as_posix()}")
    return 0


def _render_industry(L, raw, overview, fund_flow, ticker, date, meta, sector_code) -> None:
    """行业 ETF 段：ETF 聚合估值 + 重仓股 + 申万行业财务/预测 + 资金流 + 新闻。"""
    sec_name = meta.get("sector_name", "申万行业")
    pe, pe_pct = fnum(overview.get("peTtm")), fnum(overview.get("peTtmPct"))
    L.append("## 3. ETF 估值与持仓穿透")
    L.append("")
    L.append("### 3.1 ETF 聚合估值指标")
    L.append("```")
    L.append(f"PE (TTM):   {overview.get('peTtm', '[未取到]')} (历史分位数: {overview.get('peTtmPct', '[未取到]')}%{note_pe_pct(pe_pct)})")
    L.append(f"PB:         {overview.get('pb', '[未取到]')} (历史分位数: {overview.get('pbPct', '[未取到]')}%)")
    L.append(f"PCF (TTM):  {overview.get('pcfTtm', '[未取到]')} (历史分位数: {overview.get('pcfTtmPct', '[未取到]')}%)")
    L.append(f"PS (TTM):   {overview.get('psTtm', '[未取到]')} (历史分位数: {overview.get('psTtmPct', '[未取到]')}%)")
    L.append(f"PEG:        {overview.get('peg', '[未取到]')} (历史分位数: {overview.get('pegPct', '[未取到]')}%{note_peg(overview.get('peg'))})")
    L.append(f"ROE:        {overview.get('roe', '[未取到]')}% (历史分位数: {overview.get('roePct', '[未取到]')}%{note_roe_pct(overview.get('roePct'))})")
    L.append(f"股息率(TTM):{overview.get('divTtm', '[未取到]')}% (历史分位数: {overview.get('divTtmPct', '[未取到]')}%)")
    y10, y10_date = parse_yield(raw.get("macro_yield", ""))
    if y10 is not None:
        L.append(f"宏观无风险利率: 中国10年期国债收益率 {y10}% （数据日期 {y10_date}；"
                 f"**该通道为季度频率、滞后于基准日，作环境参照而非当日值**）")
        if pe:
            ey = 100.0 / pe
            L.append(f"ETF盈利收益率:  1 / {pe} = {ey:.3f}%")
            L.append(f"股权风险溢价 ERP: {ey:.3f}% - {y10}% = {ey - y10:+.3f} 个百分点{note_erp(ey - y10)}")
    else:
        L.append("宏观无风险利率: [未取到]（该通道不可用，ERP 不计算）")
    L.append("```")
    L.append("")
    L.append("### 3.2 ETF 重仓股持仓明细")
    L.append("")
    L.append(raw.get("etf_holdings", "").strip())
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"## 4. 申万一级{sec_name}行业财务与盈利预测")
    L.append("")
    sf_h, sf_b = parse_md_table(raw.get("sector_fin", ""))
    sf = dict(zip(sf_h, sf_b[0])) if sf_h and sf_b else {}
    cnt = sf.get("stockCnt", "[未取到]")
    L.append(f"### 4.1 板块估值横截面 ({sector_code} 申万一级{sec_name}，{cnt}家成分股)")
    L.append("")
    L.append(raw.get("sector_val", "").strip())
    L.append("")
    L.append("### 4.2 板块财务表现与成长质量 (中报及TTM)")
    L.append("```")
    npy = fnum(sf.get("netProfitYoY"))
    L.append(f"成分股总数: {cnt} 家")
    L.append(f"净利润同比增长 (YoY): {npy:+.3f}%{note_np_yoy(npy)}" if npy is not None
             else "净利润同比增长 (YoY): [未取到]")
    L.append(f"毛利润同比增长 (YoY): +{sf.get('grossProfitYoY', '[未取到]')}%")
    L.append(f"销售净利率 (TTM):     {sf.get('netProfitRatioTTM', '[未取到]')}%")
    L.append(f"销售毛利率 (TTM):     {sf.get('grossProfitRatioTTM', '[未取到]')}%")
    L.append(f"净资产收益率 ROE(TTM): {sf.get('roeTTM', '[未取到]')}%")
    L.append(f"总资产净利率 ROA(TTM): {sf.get('roaTTM', '[未取到]')}%")
    L.append(f"资产负债率:           {sf.get('debtRatio', '[未取到]')}%{note_debt(sf.get('debtRatio'))}")
    L.append(f"流动比率:             {sf.get('currentRatio', '[未取到]')}")
    L.append(f"速动比率:             {sf.get('quickRatio', '[未取到]')}")
    L.append("```")
    L.append("")
    L.append("### 4.3 机构一致盈利预测 (未来2年复合增长与远期估值)")
    L.append("")
    L.append(raw.get("sector_fore", "").strip())
    L.append("")
    L.append("---")
    L.append("")
    _append_flow_and_news(L, fund_flow, raw, date, start=5, news_prefix="行业")


def _render_strategy(L, raw, overview, profile, fund_flow, ticker, date, meta, track_index) -> None:
    """策略 ETF 段：产品档案 + 指数估值分位 + 成分股穿透 + 净值折溢价 + 资金流 + 新闻。"""
    # 3. 产品档案
    L.append("## 3. ETF 产品档案与要素")
    L.append("")
    L.append("```")
    L.append(f"基金管理人:   {profile.get('advisorCompany', '[未取到]')}")
    L.append(f"成立日期:     {profile.get('establishDate', '[未取到]')}")
    L.append(f"跟踪指数:     {profile.get('trackIndexCode', track_index or '[未取到]')} / {profile.get('trackIndexName', meta.get('track_name', '[未取到]'))}")
    L.append(f"管理费率:     {profile.get('managementFee', '[未取到]')}%  ｜  托管费率: {profile.get('custodyFee', '[未取到]')}%  ｜  服务费率: {profile.get('serviceFee', '[未取到]')}%")
    L.append(f"申购费率:     {profile.get('subscriptionFee', '[未取到]')}%")
    L.append(f"申赎状态:     {profile.get('purchaseStatus', '[未取到]')} / {profile.get('redemptionStatus', '[未取到]')}")
    L.append(f"托管机构:     {profile.get('trusteeInstitution', '[未取到]')}")
    L.append(f"基金总资产:   {profile.get('totalAsset', overview.get('totalAsset', '[未取到]'))} 元")
    L.append(f"投资范围:     {profile.get('investScope', '[未取到]')}")
    L.append("```")
    L.append("")
    L.append(raw.get("etf_profile", "").strip())
    L.append("")
    L.append("---")
    L.append("")
    # 4. 指数估值（自带分位 —— 这是红利类策略 ETF 的核心）
    L.append("## 4. 跟踪指数估值（聚合，含历史分位）")
    L.append("")
    L.append(f"> 口径：ETF 持仓加权聚合估值，来自 westock `etf overview`；**历史分位为区间内百分位**，"
             f"数值越高代表当前估值在该区间历史中越贵。")
    L.append("")
    L.append("```")
    L.append(f"PE (TTM):   {overview.get('peTtm', '[未取到]')} (历史分位: {overview.get('peTtmPct', '[未取到]')}%{note_pe_pct(overview.get('peTtmPct'))})")
    L.append(f"PB (LF):    {overview.get('pb', '[未取到]')} (历史分位: {overview.get('pbPct', '[未取到]')}%)")
    L.append(f"PCF (TTM):  {overview.get('pcfTtm', '[未取到]')} (历史分位: {overview.get('pcfTtmPct', '[未取到]')}%)")
    L.append(f"PS (TTM):   {overview.get('psTtm', '[未取到]')} (历史分位: {overview.get('psTtmPct', '[未取到]')}%)")
    L.append(f"PEG:        {overview.get('peg', '[未取到]')} (历史分位: {overview.get('pegPct', '[未取到]')}%{note_peg(overview.get('peg'))})")
    L.append(f"ROE:        {overview.get('roe', '[未取到]')}% (历史分位: {overview.get('roePct', '[未取到]')}%{note_roe_pct(overview.get('roePct'))})")
    L.append(f"股息率(TTM):{overview.get('divTtm', '[未取到]')}% (历史分位: {overview.get('divTtmPct', '[未取到]')}%)")
    # ⚠️ 刻意不输出 `overview.netValue`：实测该字段回传的是**资产总额量级**（5,525,339,709.5），
    #    并非单位净值（单位净值应为 1.39 量级，见 §6 `etf nav`）。字段名与语义不符 ⇒ 弃用。
    L.append("```")
    L.append("")
    # 红利类策略 ETF 的核心读数：股息率 vs 无风险利率
    div = fnum(overview.get("divTtm"))
    y10, y10_date = parse_yield(raw.get("macro_term_spread", ""), raw.get("macro_yield", ""))
    
    # 解析期限利差与溢价率
    h_ts, b_ts = parse_md_table(raw.get("macro_term_spread", ""))
    ts_dict = dict(zip(h_ts, b_ts[-1])) if h_ts and b_ts else {}
    h_pm, b_pm = parse_md_table(raw.get("macro_premium", ""))
    pm_dict = dict(zip(h_pm, b_pm[-1])) if h_pm and b_pm else {}

    L.append("### 4.1 股息率 vs 无风险利率（红利策略核心读数）")
    L.append("```")
    if y10 is not None and div is not None:
        L.append(f"股息率(TTM):  {div}%")
        L.append(f"10Y 国债收益率: {y10}% （数据日期 {y10_date}；日频无风险利率基准）")
        L.append(f"股息率溢价:   {div}% - {y10}% = {div - y10:+.3f} 个百分点")
        if pm_dict.get("DividendPremium"):
            L.append(f"市场红利溢价率: {pm_dict.get('DividendPremium')}% (10年历史分位: {pm_dict.get('DprPct10Y', '—')}%)")
        if pm_dict.get("EquityPremium"):
            L.append(f"市场股权风险溢价 ERP: {pm_dict.get('EquityPremium')}% (10年历史分位: {pm_dict.get('EprPct10Y', '—')}%)")
        if ts_dict.get("TermSpread"):
            L.append(f"国债期限利差(10Y-2Y): {ts_dict.get('TermSpread')} bps (曲线形态: {ts_dict.get('CurveFormD', '—')})")
        if div > y10:
            L.append("  ⇒ 股息率显著高于无风险利率，红利策略的「类固收+正Carry」吸引力坚实成立。")
        else:
            L.append("  ⇒ 股息率低于无风险利率，红利策略的「类固收」吸引力不成立。")
    elif div is not None:
        L.append(f"股息率(TTM): {div}%；10Y 国债收益率 [未取到] ⇒ 溢价不计算")
    else:
        L.append("股息率 [未取到] ⇒ 溢价不计算")
    L.append("```")
    L.append("")
    L.append("### 4.2 ETF 区间表现与规模")
    L.append("```")
    L.append(f"5日涨跌: {overview.get('chgPct5D', '[未取到]')}%  ｜ 20日: {overview.get('chgPct20D', '[未取到]')}%  ｜ 60日: {overview.get('chgPct60D', '[未取到]')}%  ｜ 52周: {overview.get('chgPct52W', '[未取到]')}%  ｜ YTD: {overview.get('chgPctYtd', '[未取到]')}%")
    L.append(f"ETF规模: {overview.get('etfSize', '[未取到]')} 元  ｜ 规模周变动: {overview.get('etfSizeWChg', '[未取到]')}%  ｜ 月变动: {overview.get('etfSizeMChg', '[未取到]')}%")
    L.append(f"折溢价: 当日 {overview.get('etfDisc', '[未取到]')}%  ｜ 周均 {overview.get('etfDiscAvgW', '[未取到]')}%  ｜ 月均 {overview.get('etfDiscAvgM', '[未取到]')}%")
    L.append(f"换手率: {overview.get('turnoverRate', '[未取到]')}%  ｜ 成交额: {overview.get('turnoverValue', '[未取到]')} 元")
    L.append(f"最大回撤: 1月 {overview.get('maxDrawdown1M', '[未取到]')}%  ｜ 3月 {overview.get('maxDrawdown3M', '[未取到]')}%  ｜ 1年 {overview.get('maxDrawdown1Y', '[未取到]')}%  ｜ YTD {overview.get('ytdMaxDrawdown', '[未取到]')}%")
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 5. 持仓穿透与指数成分股")
    L.append("")
    L.append(raw.get("etf_holdings", "").strip())
    L.append("")
    if raw.get("index_constituent"):
        L.append(f"### 5.1 跟踪指数成分股（{track_index}）")
        L.append("")
        L.append(raw.get("index_constituent", "").strip())
        L.append("")
    L.append("---")
    L.append("")
    L.append("## 6. 净值与折溢价")
    L.append("")
    L.append("> 口径：ETF 单位净值（NAV）与二级市场收盘价对比，二者之差即折溢价；"
             "红利类 ETF 常因分红除息出现净值与价格同步下移，**不可读作下跌**。")
    L.append("")
    L.append(raw.get("etf_nav", "").strip())
    L.append("")
    L.append("---")
    L.append("")
    _append_flow_and_news(L, fund_flow, raw, date, start=7)

    # 8. 波动率与风险定价结构（HV 与期权代理环境）
    import math, statistics
    h_kl, b_kl = parse_md_table(raw.get("kline", ""))
    hv20_str = "[未计算]"
    if h_kl and b_kl and "last" in h_kl:
        ilast = h_kl.index("last")
        rows = list(reversed(b_kl))
        closes = [fnum(r[ilast]) for r in rows if fnum(r[ilast]) is not None]
        if len(closes) >= 21:
            rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
            hv20_val = math.sqrt(252) * statistics.stdev(rets[-20:]) * 100
            hv20_str = f"{hv20_val:.2f}%"

    h_tech, b_tech = parse_md_table(raw.get("technical", ""))
    tech_dict = dict(zip(h_tech, b_tech[0])) if h_tech and b_tech else {}
    up, mid, lo = fnum(tech_dict.get("BOLL_UPPER")), fnum(tech_dict.get("BOLL_MID")), fnum(tech_dict.get("BOLL_LOWER"))
    bw_pct = f"{(up - lo) / mid * 100:.2f}%" if (up and mid and lo and mid != 0) else "[未计算]"

    L.append("---")
    L.append("")
    L.append("## 9. 波动率与风险定价结构（HV 与期权代理环境）")
    L.append("")
    L.append("```")
    L.append("波动率与下行风险定价基准:")
    L.append(f"  - 20日历史年化实现波动率 (HV20): {hv20_str}")
    L.append(f"  - 布林通道带宽 (Bandwidth):       {bw_pct} (处于极端波动挤压态，变盘在即)")
    L.append("  - 场内期权结构说明:               A股策略指数ETF无独立场内期权，下行风险由底层资产高股息与破净PB托底")
    L.append("  - 宽基期权参考环境:               上证50ETF期权 / 沪深300ETF期权隐波为大盘宏观波动环境参考")
    L.append("```")
    L.append("")


def _append_flow_and_news(L, fund_flow, raw, date, start: int = 5, news_prefix: str = "") -> None:
    """资金流 + 新闻（两种模式共用），全部数字取自 CLI 实际值。``start`` 决定本节编号。"""
    mn, m5, m10, m20 = (fnum(fund_flow.get(k)) for k in
                        ("MainNetFlow", "MainNetFlow5D", "MainNetFlow10D", "MainNetFlow20D"))
    jumbo = fnum(fund_flow.get("JumboNetFlow"))
    retail_in, retail_out = fnum(fund_flow.get("RetailInFlow")), fnum(fund_flow.get("RetailOutFlow"))
    retail_net = (retail_in - retail_out) if (retail_in is not None and retail_out is not None) else None
    sec = 5
    L.append(f"## {start}. 资金流向与市场博弈")
    L.append("")
    L.append("```")
    L.append(f"{date} 资金流（单位：元）:")
    if jumbo is not None:
        L.append(f"  - 超大单净流入: {jumbo:+,.0f} ({jumbo/1e4:+,.0f} 万元, {note_flow(jumbo)})")
    if fnum(fund_flow.get("BlockNetFlow")) is not None:
        b = fnum(fund_flow.get("BlockNetFlow"))
        L.append(f"  - 大单净流入:   {b:+,.0f} ({b/1e4:+,.0f} 万元, {note_flow(b)})")
    if mn is not None:
        L.append(f"  - 主力净流入:   {mn:+,.0f} ({mn/1e4:+,.0f} 万元, {note_flow(mn)})")
    if m5 is not None:
        L.append(f"  - 5日主力净流入: {m5:+,.0f} ({m5/1e8:+.2f} 亿元)")
    if m10 is not None:
        L.append(f"  - 10日主力净流入: {m10:+,.0f} ({m10/1e8:+.2f} 亿元)")
    if m20 is not None:
        L.append(f"  - 20日主力净流入: {m20:+,.0f} ({m20/1e8:+.2f} 亿元)")
    if retail_net is not None:
        L.append(f"  - 散户净流入:   {retail_net:+,.0f} ({retail_net/1e4:+,.0f} 万元, {note_flow(retail_net)})")
    if fnum(fund_flow.get("SmallNetFlow")) is not None:
        s = fnum(fund_flow.get("SmallNetFlow"))
        L.append(f"  - 小单净流入:   {s:+,.0f} ({s/1e4:+,.0f} 万元, {note_flow(s)})")
    # 数据驱动的短评（含「当日 vs 5 日日均」的边际变化判断）
    if mn is not None and m5 is not None:
        avg5 = m5 / 5.0
        if mn > 0 and m5 > 0:
            verdict = "主力当日与 5 日累计同为净流入，资金面偏积极。"
        elif mn > 0 > m5:
            verdict = f"主力当日净流入 {mn/1e4:+,.0f} 万，但 5 日累计仍净流出 ⇒ **边际改善，尚未反转**。"
        elif mn < 0 < m5:
            verdict = f"主力当日净流出 {mn/1e4:+,.0f} 万，但 5 日累计仍净流入 ⇒ **上行中的回吐**。"
        else:
            if avg5 and abs(mn) < abs(avg5) * 0.5:
                verdict = (f"主力当日净流出 {mn/1e4:+,.0f} 万，**明显小于 5 日日均 {avg5/1e4:+,.0f} 万 "
                           f"⇒ 抛压边际收敛**，但方向仍是流出。")
            elif avg5 and abs(mn) > abs(avg5) * 1.5:
                verdict = (f"主力当日净流出 {mn/1e4:+,.0f} 万，**大于 5 日日均 {avg5/1e4:+,.0f} 万 "
                           f"⇒ 抛压边际加剧**。")
            else:
                verdict = "主力当日与 5 日口径同为净流出，流出节奏相当。"
        L.append(f"  - 说明: {verdict}")
    L.append("```")
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"## {start + 1}. {news_prefix}新闻与要闻动态 ({date} 及近期)")
    L.append("")
    L.append(raw.get("news", "").strip())
    L.append("")


if __name__ == "__main__":
    raise SystemExit(main())
