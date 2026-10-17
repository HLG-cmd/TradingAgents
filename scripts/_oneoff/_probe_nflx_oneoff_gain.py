# lifecycle: oneoff
"""探针：定位 NFLX 非经营项目与一次性收益（$2.8B 华纳分手费）。
只读本地缓存 companyfacts。"""
import json
from pathlib import Path
from datetime import date

CACHE = Path(r"C:\Users\HLJ\.tradingagents\edgar_raw\NFLX_companyfacts.json")
d = json.loads(CACHE.read_text(encoding="utf-8"))
gaap = d["facts"].get("us-gaap", {})


def _days(e):
    s, en = e.get("start"), e.get("end")
    if not s or not en:
        return None
    y1, m1, dd1 = map(int, s.split("-"))
    y2, m2, dd2 = map(int, en.split("-"))
    return (date(y2, m2, dd2) - date(y1, m1, dd1)).days


def q(tag):
    rows = {}
    f = gaap.get(tag)
    if not f:
        return []
    for unit, arr in f["units"].items():
        for e in arr:
            nd = _days(e)
            if nd is None or not (80 <= nd <= 100):
                continue
            if e.get("form") not in ("10-Q", "10-K"):
                continue
            k = e["end"]
            if k not in rows or e["filed"] > rows[k]["filed"]:
                rows[k] = e
    return sorted(rows.values(), key=lambda x: x["end"])


# 1) 找所有含 income / gain / other / tax / termination 的 tag（看有无分手费）
print("=== tags containing keywords ===")
kw = ("other", "gain", "nonoperat", "incomebefore", "tax", "terminat", "litigat", "restructur")
cands = [t for t in gaap if any(k in t.lower() for k in kw)]
print(len(cands), "candidates")
for t in sorted(cands):
    if any(k in t.lower() for k in ("nonoperat", "otherincome", "gain", "terminat")):
        print("   ", t)

print()
print("=== quarterly Pretax / Other income series ===")
for tag in ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "NonoperatingIncomeExpense",
            "OtherNonoperatingIncomeExpense",
            "IncomeLossFromEquityMethodInvestments",
            "InvestmentIncomeInterest",
            "OtherNonoperatingExpense"):
    qs = q(tag)
    if not qs:
        print(f"  [MISS] {tag}")
        continue
    print(f"  {tag}")
    for e in qs[-6:]:
        print(f"     {e['start']}~{e['end']}  {e['val']/1e9:>9.4f}B  {e['form']} filed={e['filed']}")

print()
print("=== 全部含 'Gain' 或 'Terminat' 的 tag（含 instant/duration）===")
hit = 0
for t in sorted(gaap):
    lt = t.lower()
    if "gain" in lt or "terminat" in lt or "breakup" in lt or "fee" in lt:
        print("  ", t)
        hit += 1
print("  total:", hit)

print()
print("=== quarterly tax provision ===")
for e in q("IncomeTaxExpenseBenefit")[-6:]:
    print(f"   {e['start']}~{e['end']}  {e['val']/1e9:>9.4f}B  filed={e['filed']}")
