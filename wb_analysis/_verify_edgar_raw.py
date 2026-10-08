# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_edgar_raw.py
"""直接从 SEC data.sec.gov 拉**完整** companyfacts（不走项目内的 slim 缓存），复核 FY2025 科目。

为什么需要它：`edgar_fundamentals.fetch_facts()` 返回的是 `slim_facts()` 精简后的结果，
`us-gaap` 命名空间**只保留 8 个标签**（Assets / Liabilities / Revenues / NetIncomeLoss /
StockholdersEquity / CommonStockSharesOutstanding / WeightedAverageNumberOfDilutedSharesOutstanding /
NetIncomeLossAvailableToCommonStockholdersBasic）。
⇒ **营业利润、毛利率、EPS、经营现金流、资本开支、长期债务这几项无法用现有缓存核验**，
但它们恰恰是「财报基本面」的核心科目。故本脚本直连 SEC 官方接口取全量 facts。

用法: ./.venv/Scripts/python.exe wb_analysis/_verify_edgar_raw.py NFLX [2025-12-31]
"""
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant import edgar_fundamentals as ef

CACHE = Path.home() / ".tradingagents" / "edgar_raw"

# 复用判据：文件 mtime 距今 < TTL 才复用，否则重下并覆盖。**导出为常量**，
# 让「判据」与「清理」共用同一个数 —— 两处各写一遍必然漂移。
TTL_SECONDS = 86400


def _purge_expired(cache_dir: Path) -> int:
    """删掉**已过 TTL** 的 companyfacts —— 它们永远不会再被复用。

    为什么需要它：`get_facts` 过期即重下，但**只有被再次访问的那一只**才会被覆盖；
    其余过期文件会永久留在盘上（每个约 4 MB，实测 5 只占 20.3 MB）。
    这是「按日期累积」之外的另一种只增不减 —— 清理必须在写入路径上自动发生，
    否则又会退化成「攒多了再手工清」。
    """
    removed = 0
    for f in cache_dir.glob("*_companyfacts.json"):
        try:
            if time.time() - f.stat().st_mtime >= TTL_SECONDS:
                f.unlink()
                removed += 1
        except OSError:      # 被占用等 ⇒ 跳过，不阻断
            pass
    return removed

# (证据包 §4 标签, us-gaap tag 候选链, 目标期末日)
ITEMS = [
    ("Total Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"], "2025-12-31"),
    ("Cost Of Revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"], "2025-12-31"),
    ("Operating Income", ["OperatingIncomeLoss"], "2025-12-31"),
    ("Net Income", ["NetIncomeLoss"], "2025-12-31"),
    ("Pretax Income",
     ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
     "2025-12-31"),
    ("Diluted EPS", ["EarningsPerShareDiluted"], "2025-12-31"),
    ("Total Assets", ["Assets"], "2025-12-31"),
    ("Stockholders Equity", ["StockholdersEquity"], "2025-12-31"),
    ("Long Term Debt", ["LongTermDebtNoncurrent", "LongTermDebt"], "2025-12-31"),
    ("Total Debt", ["__DERIVED_LTD_PLUS_CURRENT__"], "2025-12-31"),
    ("Operating Cash Flow",
     ["NetCashProvidedByUsedInOperatingActivities",
      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], "2025-12-31"),
    ("Capital Expenditure",
     ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
      "PaymentsToAcquireOtherPropertyPlantAndEquipment"], "2025-12-31"),
    ("Repurchase Of Capital Stock",
     ["PaymentsForRepurchaseOfCommonStock"], "2025-12-31"),
]


def get_facts(ticker: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    _purge_expired(CACHE)          # 先清已过 TTL 的，避免它们随访问次数只增不减
    p = CACHE / f"{ticker}_companyfacts.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < TTL_SECONDS:
        return json.loads(p.read_text(encoding="utf-8"))
    cik = ef.cik_for(ticker)
    if not cik:
        raise SystemExit(f"取不到 {ticker} 的 CIK")
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
    print(f"[edgar-raw] 拉取 {url}")
    r = requests.get(url, headers={"User-Agent": ef.SEC_USER_AGENT}, timeout=60)
    r.raise_for_status()
    data = r.json()
    p.write_text(json.dumps(data), encoding="utf-8")
    print(f"[edgar-raw] 已缓存 {p.stat().st_size/1e6:.1f} MB -> {p}")
    return data


def annual_value(data: dict, tag: str, target_end: str, unit_pref=("USD", "USD/shares")):
    ns = (data.get("facts") or {}).get("us-gaap") or {}
    node = ns.get(tag)
    if not node:
        return None, None, None
    for unit, rows in (node.get("units") or {}).items():
        if unit not in unit_pref:
            continue
        cands = [r for r in rows
                 if r.get("end") == target_end
                 and r.get("form") in ("10-K",)
                 and r.get("fp") == "FY"
                 and r.get("start") is not None]
        if not cands:
            # EPS 等可能没有 start
            cands = [r for r in rows if r.get("end") == target_end and r.get("form") == "10-K"]
        if cands:
            cands.sort(key=lambda r: (r.get("filed", ""), -len(str(r.get("val")))))
            return cands[-1]["val"], unit, cands[-1].get("filed")
    return None, None, None


def parse_evidence(ticker: str, as_of: str) -> dict:
    ev = ROOT / "wb_analysis" / "evidence" / f"{ticker}_{as_of}.md"
    text = ev.read_text(encoding="utf-8")
    out = {}
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
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NFLX"
    target = sys.argv[2] if len(sys.argv) > 2 else "2025-12-31"
    as_of = sys.argv[3] if len(sys.argv) > 3 else "2026-09-28"
    data = get_facts(ticker)
    ev = parse_evidence(ticker, as_of)

    print("=" * 104)
    print(f"SEC data.sec.gov 全量 companyfacts 复核（{ticker}，目标期末 {target}，仅 10-K / FY）")
    print("=" * 104)
    ok = diff = na = 0
    for ev_label, tags, end in ITEMS:
        end_date = target if target else end
        a = ev.get(ev_label)
        b = unit = filed = None
        used = None
        for t in tags:
            if t == "__DERIVED_LTD_PLUS_CURRENT__":
                # 「总债务」在 XBRL 里没有单一标签 ⇒ 用「长期债务（非流动）」+「长期债务（流动部分）」自算
                ltd, _, f1 = annual_value(data, "LongTermDebtNoncurrent", end_date)
                cur, _, f2 = annual_value(data, "LongTermDebtCurrent", end_date)
                if ltd is None:
                    ltd, _, f1 = annual_value(data, "LongTermDebt", end_date)
                if ltd is not None and cur is not None:
                    b, used, filed = ltd + cur, "LongTermDebtNoncurrent + LongTermDebtCurrent", f1 or f2
                continue
            b, unit, filed = annual_value(data, t, end_date)
            if b is not None:
                used = t
                break
        if a is None:
            verdict = "证据包无此科目"
        elif b is None:
            verdict = "SEC 无该标签"
            na += 1
        else:
            d = (a - b) / b * 100 if b else float("nan")
            same_abs = abs(abs(a) - abs(b)) / abs(b) < 0.005 if b else False
            if abs(d) < 0.5:
                verdict = "✓ 一致"
                ok += 1
            elif same_abs:
                verdict = "✓ 一致（仅符号约定差异：SEC 报绝对流出额）"
                ok += 1
            else:
                verdict = f"✗ 差 {d:+.2f}%"
                diff += 1
        a_s = f"{a:,.2f}" if isinstance(a, (int, float)) else "—"
        b_s = f"{b:,.2f}" if isinstance(b, (int, float)) else "—"
        print(f"   {ev_label:24s} 证据包={a_s:>20s}  SEC={b_s:>20s}  "
              f"{(used or '—'):46s} {(filed or ''):12s} {verdict}")
    print(f"\n[汇总] 一致 {ok} / 不一致 {diff} / SEC 无标签 {na}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
