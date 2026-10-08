# -*- coding: utf-8 -*-
# lifecycle: oneoff
"""核查 AVGO FY2025（期末 2025-11-02）的：回购标签、净利标签、权益标签、债务标签。"""
import json
from pathlib import Path

p = Path.home() / ".tradingagents" / "edgar_raw" / "AVGO_companyfacts.json"
data = json.loads(p.read_text(encoding="utf-8"))
ns = data["facts"]["us-gaap"]
END = "2025-11-02"

KEYS = ["Repurchase", "Buyback", "TreasuryStock", "NetIncome", "ProfitLoss",
        "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "LongTermDebt", "Debt"]

def scan(substr, end=None, instant=False):
    hits = []
    for tag, node in ns.items():
        if substr.lower() not in tag.lower():
            continue
        for unit, rows in (node.get("units") or {}).items():
            for r in rows:
                if end and r.get("end") != end:
                    continue
                if r.get("form") != "10-K":
                    continue
                hits.append((tag, unit, r.get("start"), r.get("end"), r.get("val"), r.get("filed")))
    return hits

print("=" * 90)
print(f"① 回购相关标签（10-K，端={END}）")
seen = set()
for h in scan("Repurchase", END) + scan("TreasuryStock", END):
    k = (h[0], h[2], h[4])
    if k in seen:
        continue
    seen.add(k)
    print(f"  {h[0]:58s} start={h[2]} end={h[3]} val={h[4]:,} filed={h[5]}")

print()
print("=" * 90)
print(f"② 净利相关标签（10-K，端={END}）")
seen = set()
for h in scan("NetIncome", END) + scan("ProfitLoss", END):
    k = (h[0], h[2], h[4])
    if k in seen:
        continue
    seen.add(k)
    print(f"  {h[0]:58s} start={h[2]} end={h[3]} val={h[4]:,}")

print()
print("=" * 90)
print(f"③ 权益相关标签（10-K，instant，端={END}）")
for h in scan("StockholdersEquity", END):
    print(f"  {h[0]:58s} start={h[2]} end={h[3]} val={h[4]:,}")

print()
print("=" * 90)
print(f"④ 债务相关标签（10-K，instant，端={END}）")
for h in scan("Debt", END):
    if h[2] is None:  # instant
        print(f"  {h[0]:58s} end={h[3]} val={h[4]:,}")
