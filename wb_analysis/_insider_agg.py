# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_insider_agg.py
"""从证据包 §8 内部人交易 CSV 段落聚合买卖统计（回原始样本重数，不依赖任何摘要）。

用法: ./.venv/Scripts/python.exe wb_analysis/_insider_agg.py GOOG 2026-09-21
"""
import csv
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ticker, date = sys.argv[1], sys.argv[2]
    ev = ROOT / "wb_analysis" / "evidence" / f"{ticker}_{date}.md"
    text = ev.read_text(encoding="utf-8")

    # 定位 §8 的代码块
    m = re.search(r"## 8\. 内部人交易\s*```(.*?)```", text, re.S)
    if not m:
        print("未找到 §8 代码块")
        return 1
    block = m.group(1).strip("\n").split("\n")
    # 去掉以 # 开头的注释行
    rows = [ln for ln in block if ln.strip() and not ln.startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(rows)))
    print(f"[insider] CSV 列名 = {reader.fieldnames}")
    print(f"[insider] 首行 = {next(iter(rows[1:2]), '')[:160]}")

    buckets: dict[str, dict[str, float]] = {}
    window = []
    for r in reader:
        txn = (r.get("Transaction") or "").strip()
        text_f = (r.get("Text") or "").strip()
        d = (r.get("Start Date") or "").strip()
        shares = int(float(r.get("Shares") or 0))
        value = float(r.get("Value") or 0)
        kind = "Unknown"
        if text_f.startswith("Sale"):
            kind = "Sale"
        elif text_f.startswith("Stock Gift"):
            kind = "Gift"
        elif text_f.startswith("Stock Award") or text_f.startswith("Stock Award(Grant)"):
            kind = "Award"
        elif text_f.startswith("Purchase") or text_f.startswith("Buy"):
            kind = "Buy"
        elif text_f == "":
            kind = "Blank"
        b = buckets.setdefault(kind, {"n": 0, "shares": 0, "value": 0.0})
        b["n"] += 1
        b["shares"] += shares
        b["value"] += value
        if d:
            window.append(d)

    print(f"[insider] {ticker} §8 共 {sum(b['n'] for b in buckets.values())} 条记录")
    print(f"[insider] 日期窗口 {min(window)} ~ {max(window)}")
    for k in ("Buy", "Sale", "Gift", "Award", "Blank", "Unknown"):
        if k in buckets:
            b = buckets[k]
            print(f"  {k:8s} n={b['n']:4d}  shares={b['shares']:>12,}  value=${b['value']:>16,.0f}")

    mc = 4_291_117_187_072
    if "Sale" in buckets:
        print(f"  → 卖出金额 / 市值 = {buckets['Sale']['value'] / mc * 100:.4f}%")
    print(f"  → 公开市场买入笔数 = {buckets.get('Buy', {}).get('n', 0)}")

    # 逐人卖出排行
    reader = csv.DictReader(io.StringIO("\n".join(rows)))
    per: dict[str, dict[str, float]] = {}
    for r in reader:
        if not (r.get("Text") or "").strip().startswith("Sale"):
            continue
        k = (r.get("Insider") or "?").strip() or "?"
        p = per.setdefault(k, {"n": 0, "shares": 0, "value": 0.0})
        p["n"] += 1
        p["shares"] += int(float(r.get("Shares") or 0))
        p["value"] += float(r.get("Value") or 0)
    print("\n[insider] 卖出按人聚合（降序）")
    for k, p in sorted(per.items(), key=lambda kv: -kv[1]["value"]):
        print(f"  {k:34s} n={p['n']:3d} shares={p['shares']:>10,} value=${p['value']:>14,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
