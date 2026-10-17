# lifecycle: oneoff
# created: 2026-10-15
"""探针：查 SKHY 季度利润表的 Total Unusual Items / Net Income，判断收益质量闸门报的
「非经营/净利 +30.0%（TTM 4Q）」是真实信号还是数据源失真。

背景：FY2025 年报的 Total Unusual Items = -8,516.3B（**负值**，压低净利），
而闸门按季度合计得到 **+30.0%**（正值，抬高净利）—— 方向相反，必须查清。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yfinance as yf  # noqa: E402

t = yf.Ticker("SKHY")

print("=== 季度利润表（原始，按列序）===")
q = t.quarterly_income_stmt
if q is None or q.empty:
    print("  (季度利润表为空)")
else:
    cols = list(q.columns)
    print(f"  列（最近 6 期）：{[str(c)[:10] for c in cols[:6]]}")
    for row in ["Total Unusual Items", "Net Income", "Net Income Common Stockholders",
                "Pretax Income", "Operating Income", "Total Revenue"]:
        if row in q.index:
            vals = [q.loc[row, c] for c in cols[:6]]
            shown = [f"{v/1e12:.3f}T" if v == v and v is not None else "NaN" for v in vals]
            print(f"  {row:34s} {shown}")
        else:
            print(f"  {row:34s} (该行不存在)")

print()
print("=== 闸门口径复算（前 4 季求和）===")
try:
    g = q.loc["Total Unusual Items"].iloc[:4]
    n = q.loc["Net Income"].iloc[:4]
    gs, ns = g.sum(), n.sum()
    print(f"  Total Unusual Items 4Q 合计 = {gs/1e12:.3f}T")
    print(f"  Net Income 4Q 合计          = {ns/1e12:.3f}T")
    print(f"  比值 = {gs/ns*100:.1f}%")
    print(f"  各季 Unusual: {[round(v/1e12,3) for v in g.tolist()]}")
    print(f"  各季 NetIncome: {[round(v/1e12,3) for v in n.tolist()]}")
except Exception as e:
    print("  复算失败:", e)

print()
print("=== 年报口径对照 ===")
a = t.income_stmt
if a is not None and not a.empty:
    for row in ["Total Unusual Items", "Net Income"]:
        if row in a.index:
            v = a.loc[row].iloc[0]
            print(f"  FY 最新 {row:24s} = {v/1e12:.3f}T")
