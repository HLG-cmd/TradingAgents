# lifecycle: oneoff
# created: 2026-10-14
"""探针：扫描 NFLX 2026Q1 的全部 us-gaap 标签，定位那笔 2.852B 非经营收益的性质。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
CACHE = Path.home() / ".tradingagents" / "edgar_raw" / "NFLX_companyfacts.json"
gaap = json.loads(CACHE.read_text(encoding="utf-8"))["facts"]["us-gaap"]

Q1 = ("2026-01-01", "2026-03-31")
H1 = ("2026-01-01", "2026-06-30")

print("=== Q1 2026 区间内 |val| >= 0.3B 的全部 us-gaap 标签 ===")
hits = []
for tag, node in gaap.items():
    for r in node.get("units", {}).get("USD", []):
        if r.get("start") == Q1[0] and r.get("end") == Q1[1]:
            if abs(r["val"]) >= 0.3e9:
                hits.append((abs(r["val"]), tag, r["val"] / 1e9, r.get("form"), r.get("filed")))
for _, tag, v, form, filed in sorted(hits, reverse=True):
    print(f"  {v:>10.3f}B  {tag}  ({form} {filed})")

print()
print("=== 疑似一次性/投资类标签的全历史（找 Q1 2026 的异常跳升） ===")
SUS = [t for t in gaap if any(k in t for k in
        ["Gain", "Loss", "Unusual", "Special", "Restructur", "Impair",
         "Disposal", "Divest", "Settlement", "Litigation", "Legal"])]
for tag in sorted(SUS):
    vals = gaap[tag].get("units", {}).get("USD", [])
    q = [r for r in vals if r.get("start") == Q1[0] and r.get("end") == Q1[1]]
    if q and any(abs(r["val"]) >= 0.2e9 for r in q):
        for r in q:
            print(f"  Q1'26 {r['val']/1e9:>10.3f}B  {tag}  ({r.get('form')} {r.get('filed')})")
