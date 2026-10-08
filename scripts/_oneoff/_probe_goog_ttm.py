# lifecycle: oneoff
# serves: GOOG 2026-09-29 —— TTM 拆解探针
"""为什么需要这个探针：证据包 §3 基本面快照被时点闸门扣留，且只给了年度报表。

yfinance 的 trailingPE=17.49 / forwardPE=23.01 与年度报表算出的 PE 严重冲突：
  - FY2025 口径：337.32 / 10.81 = 31.21
  - yfinance TTM 口径：337.32 / 19.83 = 17.01
  - 前瞻口径：337.32 / 15.07 = 22.39
三个数差近一倍，必须拆开 TTM 才能判断哪个分母可信。

本探针：
  1) 拉季度利润表，手工滚动 TTM（4 个季度求和），与 yfinance 的 trailingEps 对账；
  2) 拆出「营业利润 vs 非经营损益 vs 一次性项目」，判断 TTM 高利润里有多少是
     不可持续的（铁律 28：一次性收益会同时顶高净利率与 ROE）；
  3) 拉分析师目标价与股息，用于交叉验证。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yfinance as yf  # noqa: E402

SHARES = 12_229_934_831  # impliedSharesOutstanding（A+B+C 合计，铁律 23 已裁定）
CLOSE_0929 = 337.32


def g(df, key):
    """从 yfinance 财报 DataFrame 安全取一行。"""
    if df is None or df.empty:
        return None
    for k in (key,):
        if k in df.index:
            return df.loc[k]
    return None


def show(df, keys, title):
    print(f"\n===== {title} =====")
    if df is None or df.empty:
        print("  <空>")
        return None
    cols = list(df.columns)
    print("  期数:", [str(c)[:10] for c in cols])
    out = {}
    for k in keys:
        if k in df.index:
            row = df.loc[k]
            vals = []
            for c in cols:
                v = row[c]
                try:
                    vals.append(None if v != v else float(v))
                except Exception:
                    vals.append(None)
            out[k] = vals
            print(f"  {k:42s} " + " | ".join(
                f"{v/1e9:>10.3f}B" if v is not None else f"{'—':>11s}" for v in vals))
    return out


def main() -> int:
    tk = yf.Ticker("GOOG")

    qis = None
    qcf = None
    qbs = None
    try:
        qis = tk.quarterly_income_stmt
    except Exception as e:
        print("[WARN] quarterly_income_stmt:", e)
    try:
        qcf = tk.quarterly_cashflow
    except Exception as e:
        print("[WARN] quarterly_cashflow:", e)
    try:
        qbs = tk.quarterly_balance_sheet
    except Exception as e:
        print("[WARN] quarterly_balance_sheet:", e)

    is_out = show(qis, [
        "Total Revenue", "Operating Income", "Pretax Income",
        "Tax Provision", "Net Income", "Other Income Expense",
        "Net Non Operating Interest Income Expense",
        "Total Unusual Items", "EBITDA", "Normalized EBITDA",
        "Diluted EPS", "Basic EPS", "Operating Revenue",
        "Research And Development", "Cost Of Revenue", "Gross Profit",
    ], "季度利润表（最新在前）")

    show(qcf, ["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow",
               "Repurchase Of Capital Stock", "Cash Dividends Paid"], "季度现金流量表")
    show(qbs, ["Total Assets", "Stockholders Equity", "Total Debt",
               "Cash Cash Equivalents And Short Term Investments",
               "Ordinary Shares Number"], "季度资产负债表")

    # ---- TTM 手工滚动 ----
    if is_out and "Net Income" in is_out:
        ni = [v for v in is_out["Net Income"] if v is not None]
        print(f"\n===== TTM 滚动校验 =====")
        print("  可用季度净利润(B):", [f"{v/1e9:.3f}" for v in ni[:8]])
        if len(ni) >= 4:
            ttm = sum(ni[:4])
            print(f"  TTM 净利润 = {ttm/1e9:.3f}B  （最近 4 季求和）")
            print(f"  TTM EPS   = {ttm/SHARES:.4f}   （股数 {SHARES/1e9:.4f}B）")
            print(f"  yfinance trailingEps = 19.83  →  偏离 {ttm/SHARES - 19.83:+.4f}")
            print(f"  以 2026-09-29 收盘 {CLOSE_0929} 计：滚动 TTM PE = {CLOSE_0929/(ttm/SHARES):.2f}")
            print(f"  对照：yfinance trailingPE 口径 PE = {CLOSE_0929/19.83:.2f}")
            op = [v for v in is_out.get("Operating Income", []) if v is not None]
            if len(op) >= 4:
                print(f"  TTM 营业利润 = {sum(op[:4])/1e9:.3f}B")
                print(f"  ⇒ 非经营/税前外项目占税前利润比重：")
            pt = [v for v in is_out.get("Pretax Income", []) if v is not None]
            if len(pt) >= 4 and len(op) >= 4:
                ttm_pt, ttm_op = sum(pt[:4]), sum(op[:4])
                print(f"     TTM 税前 {ttm_pt/1e9:.3f}B  营业 {ttm_op/1e9:.3f}B  "
                      f"非经营 { (ttm_pt-ttm_op)/1e9:.3f}B = 税前的 {(ttm_pt-ttm_op)/ttm_pt*100:.2f}%")
            un = [v for v in is_out.get("Total Unusual Items", []) if v is not None]
            if len(un) >= 4:
                print(f"     TTM 一次性项目合计 = {sum(un[:4])/1e9:.3f}B  "
                      f"（占税前 {sum(un[:4])/sum(pt[:4])*100:.2f}%）" if pt and len(pt) >= 4 else "")
            nb = [v for v in is_out.get("Normalized EBITDA", []) if v is not None]
            eb = [v for v in is_out.get("EBITDA", []) if v is not None]
            if len(nb) >= 4 and len(eb) >= 4:
                print(f"     TTM EBITDA {sum(eb[:4])/1e9:.3f}B vs 正常化 EBITDA {sum(nb[:4])/1e9:.3f}B "
                      f"→ 差 {sum(eb[:4]-nb[:4]) if False else (sum(eb[:4])-sum(nb[:4]))/1e9:.3f}B")

    # ---- 分析师目标价 / 股息 ----
    print("\n===== 分析师与股息 =====")
    try:
        info = tk.info or {}
        for k in ("targetMeanPrice", "targetHighPrice", "targetLowPrice",
                  "numberOfAnalystOpinions", "recommendationKey",
                  "dividendRate", "dividendYield", "trailingEps", "forwardEps",
                  "trailingPE", "forwardPE", "beta", "revenueGrowth",
                  "earningsGrowth", "profitMargins", "returnOnEquity"):
            print(f"  {k:28s} = {info.get(k)}")
    except Exception as e:
        print("  [WARN] info:", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
