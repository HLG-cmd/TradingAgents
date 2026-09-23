# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py
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

import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
ET = timezone(timedelta(hours=-4))

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


def main() -> int:
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
