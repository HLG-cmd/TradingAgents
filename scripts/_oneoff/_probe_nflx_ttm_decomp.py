# lifecycle: oneoff
# created: 2026-10-14
"""探针：分解 NFLX TTM 净利，查是否含一次性/非经营项目（铁律 40/43 复核）。

只读本地缓存 `<用户主目录>/.tradingagents/edgar_raw/NFLX_companyfacts.json`，
不联网。输出：季度净利序列 + TTM 求和 + 非常规项目标签扫描。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CACHE = Path.home() / ".tradingagents" / "edgar_raw" / "NFLX_companyfacts.json"
facts = json.loads(CACHE.read_text(encoding="utf-8"))
gaap = facts["facts"]["us-gaap"]

print("=== 1. 季度净利（NetIncomeLoss，按 end 升序） ===")
ni = gaap.get("NetIncomeLoss", {}).get("units", {}).get("USD", [])
# 只取 10-Q / 10-K 的季度或年度事实，按 (start,end) 去重
rows = {}
for r in ni:
    start, end = r.get("start"), r.get("end")
    if not start or not end:
        continue
    rows[(start, end)] = (r["val"], r.get("form"), r.get("filed"))
for (s, e) in sorted(rows, key=lambda x: x[1])[-12:]:
    val, form, filed = rows[(s, e)]
    print(f"  {s} ~ {e}  {val/1e9:>8.3f}B  form={form} filed={filed}")

print()
print("=== 2. 扫描非常规 / 非经营项目标签 ===")
KEYS = [
    "GainOnSaleOfBusiness", "GainLossOnSaleOfBusiness",
    "UnusualItems", "UnusualOrInfrequentItemNet",
    "SpecialIncomeCharges", "RestructuringCharges",
    "GainLossOnInvestments", "EquitySecuritiesFvNi",
    "EquitySecuritiesFvNiCurrentAndNoncurrent",
    "OtherNonoperatingIncomeExpense", "NonoperatingIncomeExpense",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
]
for k in KEYS:
    node = gaap.get(k)
    if not node:
        continue
    vals = node.get("units", {}).get("USD", [])
    if not vals:
        continue
    recent = sorted(vals, key=lambda x: (x.get("end", ""), x.get("filed", "")))[-4:]
    print(f"  [{k}]  ({len(vals)} 条)")
    for r in recent:
        print(f"     end={r.get('end')} start={r.get('start')} val={r['val']/1e9:>8.3f}B form={r.get('form')} filed={r.get('filed')}")

print()
print("=== 3. 季度营收（Revenues） ===")
rev = gaap.get("Revenues", {}).get("units", {}).get("USD", [])
rrows = {}
for r in rev:
    s, e = r.get("start"), r.get("end")
    if not s or not e:
        continue
    rrows[(s, e)] = (r["val"], r.get("form"), r.get("filed"))
for (s, e) in sorted(rrows, key=lambda x: x[1])[-10:]:
    val, form, filed = rrows[(s, e)]
    print(f"  {s} ~ {e}  {val/1e9:>8.3f}B  form={form} filed={filed}")
