# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_statements_edgar.py
"""用 SEC EDGAR（XBRL，独立第三方）复核证据包 §4 三大报表的**年度（FY2025）**科目。

用户要求：「财报基本面都要数据来源精准」⇒ 不能只依赖单一数据源（yfinance）。
`edgar_fundamentals.get_point_in_time()` 给的是 **TTM**，无法直接对账年度报表；
`CONCEPT_CHAINS` 也只覆盖 6 个概念（revenue / net_income / assets / equity / liabilities / shares）。
故本脚本直接用模块底层的 `_series` 按 **tag** 取数，并施加与模块一致的约束：
  · 时长 ∈ DUR_ANNUAL（340~400 天，排除季度与半年累计）
  · `filed <= as_of`（point-in-time，不用当时尚未公布的数据）
  · 同 end 去重后取最新 end

用法: ./.venv/Scripts/python.exe wb_analysis/_verify_statements_edgar.py NFLX
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant import edgar_fundamentals as ef

AS_OF = "2026-09-21"
TICKER = "NFLX"
# 证据包 §4 的四列是「最新期在前」，最新一期是 FY2025 ⇒ 期末日应为 2025-12-31。
# 存量科目若直接取「最新 instant」会落到 2026-06-30（2026 年 Q2），与 FY2025 列**期间不匹配**，
# 会得到「假的差 4.88% / 11.73%」。故锁定目标期末日。
TARGET_END = "2025-12-31"

# (证据包 §4 标签, EDGAR tag 候选链, unit, 是否存量科目)
ITEMS = [
    ("Total Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"], "USD", False),
    ("Cost Of Revenue", ["CostOfRevenue"], "USD", False),
    ("Gross Profit", ["GrossProfit"], "USD", False),
    ("Operating Income", ["OperatingIncomeLoss"], "USD", False),
    ("Net Income", ["NetIncomeLoss"], "USD", False),
    ("Diluted EPS", ["EarningsPerShareDiluted"], "USD/shares", False),
    ("Total Assets", ["Assets"], "USD", True),
    ("Stockholders Equity", ["StockholdersEquity"], "USD", True),
    ("Total Debt", ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"], "USD", True),
    ("Operating Cash Flow",
     ["NetCashProvidedByUsedInOperatingActivities",
      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], "USD", False),
    ("Capital Expenditure",
     ["PaymentsToAcquirePropertyPlantAndEquipment",
      "PaymentsToAcquireProductiveAssets"], "USD", False),
]


def pick(facts, tags, unit, instant: bool):
    """返回 (val, end) 或 (None, None)。"""
    best = (None, None)
    for tag in tags:
        rows = ef._series(facts, tag, unit)
        if not rows:
            continue
        if not instant:
            rows = [r for r in rows
                    if r.get("dur") is not None and ef.DUR_ANNUAL[0] <= r["dur"] <= ef.DUR_ANNUAL[1]]
        rows = ef._known(rows, AS_OF)
        if not rows:
            continue
        dedupe = ef._dedupe_by_end(rows)
        if TARGET_END in dedupe:
            end = TARGET_END
        else:
            end = max(dedupe)
        if best[1] is None or end > best[1]:
            best = (dedupe[end]["val"], end)
    return best


def parse_evidence() -> dict[str, float]:
    ev = ROOT / "wb_analysis" / "evidence" / f"{TICKER}_{AS_OF}.md"
    text = ev.read_text(encoding="utf-8")
    out: dict[str, float] = {}
    for line in text.split("\n"):
        if "," not in line or line.startswith("#") or line.startswith("`"):
            continue
        parts = line.split(",")
        label = parts[0].strip()
        if not label or " " not in label:
            continue
        try:
            out.setdefault(label, float(parts[1]))
        except (ValueError, IndexError):
            continue
    return out


def main() -> int:
    facts = ef.fetch_facts(TICKER)
    ev = parse_evidence()
    print("=" * 100)
    print(f"SEC EDGAR 年度科目复核（{TICKER}，point-in-time as_of {AS_OF}，只取已申报数据）")
    print("=" * 100)

    ok = diff = na = 0
    for ev_label, tags, unit, instant in ITEMS:
        a = ev.get(ev_label)
        b, end = pick(facts, tags, unit, instant)
        if a is None:
            verdict = "证据包无此科目"
        elif b is None:
            verdict = "EDGAR 无此标签"
            na += 1
        else:
            d = (a - b) / b * 100 if b else float("nan")
            if abs(d) < 0.5:
                verdict = "✓ 一致"
                ok += 1
            else:
                verdict = f"✗ 差 {d:+.2f}%"
                diff += 1
        a_s = f"{a:,.2f}" if isinstance(a, (int, float)) else "—"
        b_s = f"{b:,.2f}" if isinstance(b, (int, float)) else "—"
        print(f"   {ev_label:22s} 证据包={a_s:>20s}  EDGAR={b_s:>20s}  "
              f"{('期末 ' + str(end)) if end else '':22s} {verdict}")

    print(f"\n[汇总] 一致 {ok} / 不一致 {diff} / EDGAR 无标签 {na}")
    print("说明：证据包 §4 的四列是「最新期在前」，本脚本比对的是**最新一期（FY2025，期末 2025-12-31）**。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
