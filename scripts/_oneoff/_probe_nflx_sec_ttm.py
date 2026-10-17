# lifecycle: oneoff
"""探针：从 SEC companyfacts 直取 NFLX 分季营收/营业利润/净利，独立复算 TTM。
只读本地缓存 C:\\Users\\HLJ\\.tradingagents\\edgar_raw\\NFLX_companyfacts.json。"""
import json
from pathlib import Path
from datetime import date

CACHE = Path(r"C:\Users\HLJ\.tradingagents\edgar_raw\NFLX_companyfacts.json")
d = json.loads(CACHE.read_text(encoding="utf-8"))
facts = d["facts"]

QA = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
      "OperatingIncomeLoss", "NetIncomeLoss",
      "EarningsPerShareDiluted", "NetCashProvidedByUsedInOperatingActivities",
      "PaymentsToAcquirePropertyPlantAndEquipment"]


def _days(e):
    s, en = e.get("start"), e.get("end")
    if not s or not en:
        return None
    y1, m1, dd1 = map(int, s.split("-"))
    y2, m2, dd2 = map(int, en.split("-"))
    return (date(y2, m2, dd2) - date(y1, m1, dd1)).days


def series(tag):
    out = []
    f = facts.get("us-gaap", {}).get(tag)
    if not f:
        return out
    for unit, arr in f["units"].items():
        for e in arr:
            out.append(e)
    return out


def quarters(tag):
    """季度期段（80~100 天），按 end 去重取最新 filed。"""
    rows = {}
    for e in series(tag):
        nd = _days(e)
        if nd is None or not (80 <= nd <= 100):
            continue
        if e.get("form") not in ("10-Q", "10-K"):
            continue
        key = e["end"]
        prev = rows.get(key)
        if prev is None or e["filed"] > prev["filed"]:
            rows[key] = e
    return sorted(rows.values(), key=lambda x: x["end"])


def annual(tag):
    rows = {}
    for e in series(tag):
        nd = _days(e)
        if e.get("form") != "10-K" or e.get("fp") != "FY" or nd is None:
            continue
        if not (350 <= nd <= 380):
            continue
        key = e["end"]
        prev = rows.get(key)
        if prev is None or e["filed"] > prev["filed"]:
            rows[key] = e
    return sorted(rows.values(), key=lambda x: x["end"])


for tag in QA:
    print("=" * 72)
    print(tag)
    if tag in ("EarningsPerShareDiluted",):
        print("  [annual]")
        for e in annual(tag):
            print(f"    {e['start']}~{e['end']}  val={e['val']:>10}  form={e['form']} filed={e['filed']}")
        continue
    print("  [quarterly, last 10]")
    qs = quarters(tag)
    for e in qs[-10:]:
        print(f"    {e['start']}~{e['end']}  val={e['val']/1e9:>10.4f}B  form={e['form']:<5} fp={e.get('fp')} filed={e['filed']}")
    print("  [annual, last 6]")
    for e in annual(tag)[-6:]:
        print(f"    {e['start']}~{e['end']}  val={e['val']/1e9:>10.4f}B  filed={e['filed']}")

print("=" * 72)
print("TTM 复算（按 end 归并，取最近 4 个季度）")
for tag in ("Revenues", "OperatingIncomeLoss", "NetIncomeLoss"):
    qs = quarters(tag)
    last4 = qs[-4:]
    tot = sum(e["val"] for e in last4)
    print(f"  {tag}: 窗口 {last4[0]['start']}~{last4[-1]['end']}")
    for e in last4:
        print(f"      {e['start']}~{e['end']}  {e['val']/1e9:>8.4f}B")
    print(f"    TTM 合计 = {tot/1e9:.4f}B")
