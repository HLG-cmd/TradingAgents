# lifecycle: oneoff
# created: 2026-10-16
"""A 股红利低波 ETF 综合对比：费率 + 年化总收益（后复权）+ 规模/流动性 + 估值分位。

口径说明：
- **年化总收益**用 `kline --fq hfq`（后复权，含分红再投），非价格收益。
- **费率**取 etf profile 的 managementFee + custodyFee + serviceFee。
- **规模/流动性/回撤/股息率**取 etf overview 与 quote。
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wb_analysis._westock import run_westock, parse_md_table  # noqa: E402

CODES = [
    ("sh515100", "红利低波100ETF景顺"),
    ("sh512890", "红利低波ETF华泰柏瑞"),
    ("sh515450", "红利低波50ETF南方"),
    ("sh563020", "红利低波ETF易方达"),
    ("sh515300", "300红利低波ETF嘉实"),
    ("sz159547", "红利低波ETF华夏"),
    ("sh560520", "红利低波100ETF大成"),
    ("sz159525", "红利低波ETF富国"),
    ("sz159549", "红利低波ETF天弘"),
]
START = "2019-01-01"   # 足够早，覆盖全部标的上市以来
END = "2026-10-15"


def row1(cmd):
    h, b = parse_md_table(run_westock(cmd))
    return (dict(zip(h, b[0])) if h and b else {}), h, b


def num(d, k, default=None):
    v = d.get(k)
    if v in (None, "", "-", "—"):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


results = []
for code, name in CODES:
    prof, _, _ = row1(["etf", "profile", code])
    ov, _, _ = row1(["etf", "overview", code])
    q, _, _ = row1(["quote", code])

    mg = num(prof, "managementFee", 0.0)
    cu = num(prof, "custodyFee", 0.0)
    sv = num(prof, "serviceFee", 0.0)
    fee = (mg or 0) + (cu or 0) + (sv or 0)

    # 后复权月线 → 年化总收益（★ kline 返回**新→旧**，必须反转）
    kh, kb = parse_md_table(run_westock(
        ["kline", code, "--period", "month", "--fq", "hfq", "--start", START, "--end", END]))
    ann = yrs = None
    first_d = last_d = None
    ann3 = ann1 = None
    if kh and kb and "last" in kh and "date" in kh:
        il, idt = kh.index("last"), kh.index("date")
        pts = [(r[idt], num({k: r[i] for i, k in enumerate(kh)}, "last")) for r in kb]
        pts = [(d, v) for d, v in pts if v]
        pts.reverse()
        if len(pts) >= 2:
            first_d, last_d = pts[0][0], pts[-1][0]

            def annualized(sub):
                if len(sub) < 2:
                    return None
                (d0, v0), (d1, v1) = sub[0], sub[-1]
                yy = (int(d1[:4]) - int(d0[:4])) + (int(d1[5:7]) - int(d0[5:7])) / 12.0
                if yy <= 0.4 or v0 <= 0:
                    return None
                return ((v1 / v0) ** (1 / yy) - 1) * 100

            ann = annualized(pts)
            yrs = (int(last_d[:4]) - int(first_d[:4])) + (int(last_d[5:7]) - int(first_d[5:7])) / 12.0
            ann3 = annualized([p for p in pts if p[0] >= "2023-10-31"])
            ann1 = annualized([p for p in pts if p[0] >= "2025-10-31"])

    results.append({
        "code": code, "name": name,
        "fee": fee, "mg": mg, "cu": cu,
        "est": str(prof.get("establishDate", ""))[:10],
        "track": prof.get("trackIndexName", "—"),
        "size": num(ov, "etfSize"), "turnover": num(ov, "turnoverValue"),
        "div_pct": num(ov, "divTtmPct"),
        "chg52w": num(ov, "chgPct52W"), "chgytd": num(ov, "chgPctYtd"),
        "dd1y": num(ov, "maxDrawdown1Y"), "dd3y": num(ov, "maxDrawdown3Y"),
        "pe_pct": num(ov, "peTtmPct"), "pb_pct": num(ov, "pbPct"),
        "disc": num(ov, "etfDisc"),
        "ann": ann, "ann3": ann3, "ann1": ann1, "yrs": yrs, "first": first_d, "last": last_d,
    })

print(f"{'代码':<10}{'名称':<20}{'费率%':>6}{'成立':<12}{'年数':>5}"
      f"{'成立以来年化%':>14}{'近3年年化%':>12}{'近1年年化%':>12}"
      f"{'规模(亿)':>10}{'日成交(亿)':>10}{'股息率%':>8}")
print("-" * 140)


def g(v, w=12, p=2):
    return f"{v:>{w}.{p}f}" if v is not None else f"{'—':>{w}}"


for r in sorted(results, key=lambda x: (x["ann"] is None, -(x["ann"] or 0))):
    print(f"{r['code']:<10}{r['name']:<20}{r['fee']:>6.2f}{r['est']:<12}{(r['yrs'] or 0):>5.1f}"
          f"{g(r['ann'], 14)}{g(r['ann3'])}{g(r['ann1'])}"
          f"{(r['size'] or 0)/1e8:>10.2f}{(r['turnover'] or 0)/1e8:>10.2f}"
          f"{g(r['div_pct'], 8)}")

print()
print("=== 估值分位 / 区间收益 / 折溢价 ===")
print(f"{'代码':<10}{'名称':<20}{'PE分位%':>9}{'PB分位%':>9}{'52周%':>9}{'YTD%':>8}{'折溢价%':>9}{'近3年回撤%':>11}")
for r in sorted(results, key=lambda x: -(x["pe_pct"] or 0)):
    f = lambda v: (v if v is not None else float("nan"))
    print(f"{r['code']:<10}{r['name']:<20}{f(r['pe_pct']):>9.2f}{f(r['pb_pct']):>9.2f}"
          f"{f(r['chg52w']):>9.2f}{f(r['chgytd']):>8.2f}{f(r['disc']):>9.2f}{f(r['dd3y']):>11.2f}")
