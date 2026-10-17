# lifecycle: oneoff
# created: 2026-10-09
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_verify_nvda_ttm.py
"""NVDA 基准日 2026-10-09 —— 从 SEC 原始季报事实**自算 TTM**，交叉校验 yfinance 快照。

独立于任何完整性的前提：本脚本不依赖任何重大推测，只用 SEC 已申报的期段事实做加减法。
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path.home() / ".tradingagents" / "edgar_raw" / "NVDA_companyfacts.json"

# yfinance 快照（证据包 §3，2026-10-10 00:49 取）
SNAP = {
    "market_cap": 5_542_460_784_640,
    "pe_ttm": 29.0177,
    "forward_pe": 14.4226055,
    "peg": 0.28,
    "pb": 24.204367,
    "eps_ttm": 7.91,
    "forward_eps": 15.9146,
    "net_income": 192_880_001_024,
    "revenue_ttm": 302_970_011_648,
    "fcf": 41_809_874_944,
    "diluted_shares_fy26": 24_514_000_000,
}


def load():
    return json.loads(CACHE.read_text(encoding="utf-8"))["facts"]["us-gaap"]


def pick(facts, tag, start, end, form="10-Q"):
    """取精确匹配期段 + 表单类型的事实值（精确相等，不做模糊回退）。"""
    rows = facts.get(tag, {}).get("units", {}).get("USD", [])
    hit = [r for r in rows if r.get("start") == start and r.get("end") == end and r.get("form") == form]
    if not hit:
        hit = [r for r in rows if r.get("start") == start and r.get("end") == end]
    return hit[-1]["val"] if hit else None


def main():
    f = load()
    print("=" * 96)
    print("NVDA · SEC 原始季报自算 TTM（all facts from data.sec.gov companyfacts，已申报口径）")
    print("=" * 96)

    # ---- NVDA 财年：FY2026 = 2025-01-27 ~ 2026-01-25；FY2027 进行中 ----
    FY26_FULL_START, FY26_END = "2025-01-27", "2026-01-25"
    FY26_H1_START, FY26_H1_END = "2025-01-27", "2025-07-27"
    FY27_H1_START, FY27_H1_END = "2026-01-26", "2026-07-26"
    FY27_Q1_START, FY27_Q1_END = "2026-01-26", "2026-04-26"
    FY27_Q2_START, FY27_Q2_END = "2026-04-27", "2026-07-26"

    tags = {
        "营收": "RevenueFromContractWithCustomerExcludingAssessedTax",
        "净利": "NetIncomeLoss",
        "经营现金流": "NetCashProvidedByUsedInOperatingActivities",
        "资本开支": "PaymentsToAcquirePropertyPlantAndEquipment",
    }

    print("\n【第一步】FY2027 上半年 + 分季（自增自洽校验）")
    v = {}
    for label, tag in tags.items():
        if tag not in f:
            print(f"  {label}: SEC 无此标签，跳入备用")
            continue
        q1 = pick(f, tag, FY27_Q1_START, FY27_Q1_END)
        q2 = pick(f, tag, FY27_Q2_START, FY27_Q2_END)
        h1 = pick(f, tag, FY27_H1_START, FY27_H1_END)
        v[label] = {"q1": q1, "q2": q2, "h1": h1}
        if q1 is not None and q2 is not None and h1 is not None:
            resid = h1 - (q1 + q2)
            flag = "✓ 加总自洽" if abs(resid) <= max(2, abs(h1) * 0.001) else f"✗ 残差 {resid:+,}"
            print(f"  {label:6s} Q1={q1:>16,}  Q2={q2:>16,}  合计={q1+q2:>16,}  H1报={h1:>16,}  {flag}")
        else:
            print(f"  {label:6s} 部分期段缺失 q1={q1} q2={q2} h1={h1}")

    print("\n【第二步】自算 TTM（FY2026 全年 − FY2026 H1 + FY2027 H1）")
    ttm = {}
    for label, tag in tags.items():
        if tag not in f:
            continue
        fy = pick(f, tag, FY26_FULL_START, FY26_END, form="10-K")
        h1_prev = pick(f, tag, FY26_H1_START, FY26_H1_END)
        h1_cur = pick(f, tag, FY27_H1_START, FY27_H1_END)
        if None in (fy, h1_prev, h1_cur):
            print(f"  {label:6s} 期段不全，跳过")
            continue
        h2_prev = fy - h1_prev
        val = h2_prev + h1_cur
        ttm[label] = val
        print(f"  {label:6s} FY26全年={fy:>16,} − FY26H1={h1_prev:>14,} = H2={h2_prev:>14,}  + FY27H1={h1_cur:>14,}  ⇒ TTM={val:>16,}")

    print("\n【第三步】与 yfinance 快照对账")
    checks = [
        ("TTM 净利", ttm.get("净利"), SNAP["net_income"]),
        ("TTM 营收", ttm.get("营收"), SNAP["revenue_ttm"]),
    ]
    for label, mine, snap in checks:
        if mine is None:
            print(f"  {label}: 不可得")
            continue
        d = (snap - mine) / mine * 100
        print(f"  {label:8s} SEC自算={mine:>18,}  yfinance={snap:>18,}  差 {d:+.3f}%")

    print("\n【第四步】多口径估值（分母全部来自 SEC 自算 TTM）")
    mc = SNAP["market_cap"]
    ni = ttm.get("净利")
    ocf = ttm.get("经营现金流")
    capex = ttm.get("资本开支")
    if ni:
        print(f"  市值/TTM 净利            = {mc/ni:>8.2f}x   ← 唯一经 SEC 自算核验的 PE")
        print(f"  隐含 TTM EPS             = {ni/SNAP['diluted_shares_fy26']:>8.4f}   （yfinance EPS(TTM) {SNAP['eps_ttm']}）")
        print(f"  快照 PE(TTM) {SNAP['pe_ttm']}  ⇒ 隐含净利 {mc/SNAP['pe_ttm']:>16,.0f}")
    if ocf:
        print(f"  市值/TTM 经营现金流      = {mc/ocf:>8.2f}x")
        if capex is not None:
            fcf = ocf - abs(capex)
            print(f"  TTM 自由现金流           = {fcf:>16,.0f}   （yfinance FCF 字段 {SNAP['fcf']:,.0f}）")
            print(f"  市值/TTM FCF             = {mc/fcf:>8.2f}x")

    print("\n【第五步】Forward EPS 可信度检验（关键）")
    imp_ni_fwd = mc / SNAP["forward_pe"]
    print(f"  Forward PE {SNAP['forward_pe']} ⇒ 隐含未来 12M 净利 = {imp_ni_fwd:>16,.0f}")
    if ni:
        print(f"  相对已核验 TTM 净利 {ni:,.0f} 的增幅 = {(imp_ni_fwd/ni-1)*100:+.1f}%")
        print(f"  Forward EPS/TTM EPS = {SNAP['forward_eps']/SNAP['eps_ttm']:.2f} 倍")
    if ttm.get("营收"):
        print(f"  隐含前瞻净利率 = {imp_ni_fwd/(mc/ (mc/ttm['营收']) )*100:.1f}%  ← 若显著高于当前 "
              f"{ni/ttm['营收']*100:.1f}%，则该 forward 不是「同一盈利能力的线性外推」")


if __name__ == "__main__":
    main()
