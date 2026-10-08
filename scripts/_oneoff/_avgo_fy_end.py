# -*- coding: utf-8 -*-
# lifecycle: oneoff
"""列出 AVGO 缓存的 companyfacts 里所有 10-K 的期末日，确定真实财年末。"""
import json
from pathlib import Path

p = Path.home() / ".tradingagents" / "edgar_raw" / "AVGO_companyfacts.json"
data = json.loads(p.read_text(encoding="utf-8"))
ns = data["facts"]["us-gaap"]
print(f"us-gaap 标签总数: {len(ns)}")

# 用 Revenues / Assets 两个常见标签列出 10-K 期末
for tag in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Assets", "NetIncomeLoss", "StockholdersEquity"):
    node = ns.get(tag)
    if not node:
        print(f"[{tag}] 无")
        continue
    ends = set()
    for unit, rows in (node.get("units") or {}).items():
        for r in rows:
            if r.get("form") == "10-K":
                ends.add((r.get("end"), r.get("fy"), r.get("fp"), r.get("filed")))
    print(f"\n[{tag}] 10-K 条目:")
    for e in sorted(ends, reverse=True)[:8]:
        print(f"   end={e[0]} fy={e[1]} fp={e[2]} filed={e[3]}")
