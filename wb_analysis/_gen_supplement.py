# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py <TICKER> <YYYY-MM-DD>
"""生成 `<TICKER>_<date>.supplement.md`：证据包 §3 被上游扣留时的**一等替代证据源**。

背景（项目铁律 3「静默失败」的已知形态之一）：
yfinance 的 point-in-time 接口对**历史日期**会拒答 profile fundamentals（§3 整节变成一段声明），
但通道健康度仍记为 ok ⇒ 「全绿 ≠ 完整」。
此时按项目规程生成 supplement：直接用 `yfinance.Ticker(...).info` 取**当日**快照，
并同时用 §4 三大报表自算关键比率，两者互相校验。

⚠️ 未来信息检查：本脚本会打印采集时刻的美东时间；若采集发生在**当日开盘前**，
则「当日」快照在事实上等于**上一交易日收盘**口径，不引入未来信息。
若采集发生在盘中/盘后，必须在简报里声明快照带有的时点偏差。

用法: ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py NFLX 2026-09-21
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
# ⚠️ 2026-10-10：`timezone(timedelta(hours=-4))` 只在夏令时（EDT）成立，冬季应为 UTC−5 ⇒ 改用 IANA 时区名。
ET = ZoneInfo("America/New_York")

FIELDS = [
    ("Market Cap", "marketCap"),
    ("PE Ratio (TTM)", "trailingPE"),
    ("Forward PE", "forwardPE"),
    ("PEG Ratio", "pegRatio"),
    ("Price to Book", "priceToBook"),
    ("Price to Sales (TTM)", "priceToSalesTrailing12Months"),
    ("EPS (TTM)", "trailingEps"),
    ("Forward EPS", "forwardEps"),
    ("Dividend Yield", "dividendYield"),
    ("Beta", "beta"),
    ("52 Week High", "fiftyTwoWeekHigh"),
    ("52 Week Low", "fiftyTwoWeekLow"),
    ("50 Day Average", "fiftyDayAverage"),
    ("200 Day Average", "twoHundredDayAverage"),
    ("Revenue (TTM)", "totalRevenue"),
    ("Gross Profit", "grossProfits"),
    ("EBITDA", "ebitda"),
    ("Net Income (TTM)", "netIncomeToCommon"),
    ("Profit Margin", "profitMargins"),
    ("Operating Margin", "operatingMargins"),
    ("Gross Margin", "grossMargins"),
    ("Return on Equity", "returnOnEquity"),
    ("Return on Assets", "returnOnAssets"),
    ("Debt to Equity", "debtToEquity"),
    ("Current Ratio", "currentRatio"),
    ("Book Value", "bookValue"),
    ("Free Cash Flow", "freeCashflow"),
    ("Operating Cash Flow", "operatingCashflow"),
    ("Total Cash", "totalCash"),
    ("Total Debt", "totalDebt"),
    ("Shares Outstanding", "sharesOutstanding"),
    ("Implied Shares Outstanding", "impliedSharesOutstanding"),
    ("Enterprise Value", "enterpriseValue"),
]


def _selfcalc_section(ticker: str, date: str, info: dict, fi: dict) -> str:
    """自算 point-in-time 估值章节 —— 独立于 vendor 实时快照的**第二条通道**。

    为什么必须并列这一节：vendor 快照是「当下值」，严格说带时点偏差；
    而本节的输入（价格序列 + EDGAR 股数）**各自都有明确的披露/交易日时点**，
    因此是真正的 point-in-time。两源并列可互校，**差异处即口径差异**。
    （2026-09-27 立：此前 §3 扣留只靠 vendor 快照兜底，未做独立自算。）
    """
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from wb_analysis import _selfcalc_valuation as sv

        vendor = {
            "Market Cap": info.get("marketCap") or fi.get("marketCap"),
            "PE Ratio (TTM)": info.get("trailingPE"),
            "Price to Book": info.get("priceToBook"),
            "Price to Sales (TTM)": info.get("priceToSalesTrailing12Months"),
            "52 Week High": info.get("fiftyTwoWeekHigh"),
            "52 Week Low": info.get("fiftyTwoWeekLow"),
            "50 Day Average": info.get("fiftyDayAverage"),
            "200 Day Average": info.get("twoHundredDayAverage"),
        }
        vendor = {k: v for k, v in vendor.items() if v}
        sc = sv.selfcalc(
            ticker, date,
            ttm_net_income=info.get("netIncomeToCommon"),
            ttm_revenue=info.get("totalRevenue"),
        )
        body = sv.render_markdown(sc, vendor)
        body += (
            "\n**报表类比率（PE/PB/PS）的补法**：若上表的 PE/PS 为空，是因为分母需要**报表项**。"
            "请用证据包 §4 的报表值调用 "
            "`_selfcalc_valuation.selfcalc(t, d, fy_net_income=…, fy_revenue=…, fy_equity=…, "
            "ttm_net_income=…, ttm_revenue=…)`，即可得到与报表自洽的 PE/PB/PS。\n"
        )
        return body
    except Exception as e:  # noqa: BLE001
        return (
            "## 自算 point-in-time 估值（独立于 vendor 实时快照）\n\n"
            f"> ⚠️ 自算通道不可用：{type(e).__name__}: {e}\n"
            "> 请检查 `wb_analysis/_selfcalc_valuation.py` 是否存在、"
            "以及 `~/.tradingagents/cache/` 下是否有该标的的价格序列。\n"
        )


def main() -> int:
    # ★ 2026-10-20：无参时原来直接抛 IndexError 裸 traceback（实测踩到），
    #   与「usage 必须自解释」的项目约定不符 ⇒ 缺参给出用法并以 2 退出。
    if len(sys.argv) < 3:
        print("用法: ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py <TICKER> <YYYY-MM-DD>")
        return 2
    ticker = sys.argv[1]
    date = sys.argv[2]
    now_et = datetime.now(timezone.utc).astimezone(ET)
    t = yf.Ticker(ticker)
    info = t.info or {}
    fi = {}
    try:
        fi = dict(t.fast_info)
    except Exception:  # noqa: BLE001
        pass

    lines = []
    lines.append(f"# 补充证据包：{ticker}（§3 被上游扣留时的一等替代源）")
    lines.append("")
    lines.append(f"- 标的：{ticker}　基准日：{date}")
    lines.append(f"- 采集时刻：{now_et:%Y-%m-%d %H:%M} 美东（北京时间 {now_et.astimezone(timezone(timedelta(hours=8))):%Y-%m-%d %H:%M}）")
    lines.append("- 来源：`yfinance.Ticker(...).info`（实时快照）+ `fast_info`")
    lines.append("")
    lines.append("## 0. 为什么需要本文件")
    lines.append("")
    lines.append("证据包 §3 的原文是一段**上游拒答声明**（point-in-time profile fundamentals are withheld），")
    lines.append("而通道健康度仍记为 ok ⇒ 属项目铁律 3「静默失败」的已知形态。")
    lines.append("本节按项目规程补上替代源，并**同时用 §4 三大报表自算**关键比率，两者互校。")
    lines.append("")
    lines.append("⚠️ **未来信息检查**：若上面的采集时刻早于美东 09:30，则「当日」快照在事实上等于")
    lines.append("**上一交易日收盘**口径（当日尚未开盘、无新成交），**不引入未来信息**；")
    lines.append("若采集发生在盘中或盘后，则快照含该时点的价格变动，**引用时必须声明时点偏差**。")
    lines.append("")
    lines.append("## 1. 实时快照字段（原文照抄，未做任何加工）")
    lines.append("")
    lines.append("```")
    for label, key in FIELDS:
        v = info.get(key)
        if v is None:
            v = fi.get(key)
        lines.append(f"{label:<28} {v}")
    lines.append("```")
    lines.append("")
    lines.append("## 2. fast_info 原始字段")
    lines.append("")
    lines.append("```")
    for k, v in sorted(fi.items()):
        lines.append(f"{k:<28} {v}")
    lines.append("```")
    lines.append("")
    lines.append("## 3. 口径自检（单字段看着都合法，坏值只能靠字段间关系识别）")
    lines.append("")
    mc = info.get("marketCap")
    px = fi.get("last_price") or fi.get("lastPrice")
    sh = info.get("sharesOutstanding")
    ish = info.get("impliedSharesOutstanding")
    lines.append("```")
    lines.append(f"市值                          {mc}")
    lines.append(f"最新价(fast_info)              {px}")
    lines.append(f"sharesOutstanding             {sh}")
    lines.append(f"impliedSharesOutstanding      {ish}")
    if mc and px:
        lines.append(f"市值 ÷ 最新价 = 隐含股数        {mc / px:,.0f}")
    if mc and sh:
        lines.append(f"市值 ÷ sharesOutstanding       {mc / sh:,.2f}（应≈最新价）")
    if mc and ish:
        lines.append(f"市值 ÷ impliedSharesOutstanding {mc / ish:,.2f}（应≈最新价）")
    pe, eps = info.get("trailingPE"), info.get("trailingEps")
    if pe and eps:
        lines.append(f"PE × EPS =                     {pe * eps:,.4f}（应≈最新价：市值/股数口径需一致）")
    lines.append("```")
    lines.append("")

    # --- 自算 point-in-time 估值：独立于 vendor 快照的第二条通道 ---
    lines.append(_selfcalc_section(ticker, date, info, fi))

    out = ROOT / "wb_analysis" / "evidence" / f"{ticker}_{date}.supplement.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"[supplement] 已写入 {out}（{out.stat().st_size} 字节）")

    # 关键字段打到 stdout 便于主模型直接取用
    print("\n[关键字段]")
    for label, key in FIELDS:
        v = info.get(key)
        if v is not None:
            print(f"  {label:<28} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
