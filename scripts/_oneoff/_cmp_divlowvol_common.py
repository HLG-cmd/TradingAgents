# lifecycle: oneoff
# created: 2026-10-16
"""红利低波 ETF：**统一窗口**年化总收益（后复权）+ 费率 → 综合排名。

★ 为什么必须统一窗口：各标的成立日从 2018-12 到 2024-05 不等，
  「成立以来年化」不可横向比较（实测同一指数两只标的因窗口不同差出 1.08pp）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wb_analysis._westock import run_westock, parse_md_table  # noqa: E402

CODES = [
    ("sh512890", "红利低波ETF华泰柏瑞"), ("sh563020", "红利低波ETF易方达"),
    ("sh515450", "红利低波50ETF南方"), ("sh515100", "红利低波100ETF景顺"),
    ("sh515300", "300红利低波ETF嘉实"), ("sz159547", "红利低波ETF华夏"),
    ("sz159549", "红利低波ETF天弘"), ("sz159525", "红利低波ETF富国"),
    ("sh560520", "红利低波100ETF大成"),
]
# 统一窗口：晚于最晚成立日（2024-05-07）的第一个月末
W_START = "2024-05-31"
W_END = "2026-10-15"


def monthly_hfq(code, start):
    h, b = parse_md_table(run_westock(
        ["kline", code, "--period", "month", "--fq", "hfq", "--start", start, "--end", W_END]))
    if not h or not b:
        return []
    i_d, i_v = h.index("date"), h.index("last")
    pts = [(r[i_d], float(r[i_v])) for r in b]
    pts.reverse()
    return pts


def ann(p):
    if len(p) < 2 or p[0][1] <= 0:
        return None, None
    y = (int(p[-1][0][:4]) - int(p[0][0][:4])) + (int(p[-1][0][5:7]) - int(p[0][0][5:7])) / 12.0
    if y <= 0.4:
        return None, None
    return ((p[-1][1] / p[0][1]) ** (1 / y) - 1) * 100, y


rows = []
for code, name in CODES:
    prof, _, _ = parse_md_table(run_westock(["etf", "profile", code])), None, None
    h, b = parse_md_table(run_westock(["etf", "profile", code]))
    d = dict(zip(h, b[0])) if h and b else {}
    fee = float(d.get("managementFee") or 0) + float(d.get("custodyFee") or 0) + float(d.get("serviceFee") or 0)
    p = monthly_hfq(code, W_START)
    a, y = ann(p)
    rows.append({"code": code, "name": name, "fee": fee, "ann": a, "yrs": y,
                 "track": d.get("trackIndexName", "—"), "track_code": d.get("trackIndexCode", ""),
                 "size": float(d.get("totalAsset") or 0) / 1e8, "est": str(d.get("establishDate", ""))[:10],
                 "first": p[0][0] if p else "—"})

print(f"统一窗口 {W_START} → {W_END}（后复权，含分红）")
print(f"{'代码':<10}{'名称':<20}{'费率%':>6}{'年化总收益%':>12}{'净收益(年化-费率)':>18}"
      f"{'规模(亿)':>10}{'跟踪指数':<16}{'成立':<12}")
print("-" * 130)
for r in sorted(rows, key=lambda x: -(x["ann"] or -99)):
    net = (r["ann"] - r["fee"]) if r["ann"] is not None else None
    print(f"{r['code']:<10}{r['name']:<20}{r['fee']:>6.2f}"
          f"{(r['ann'] if r['ann'] is not None else float('nan')):>12.2f}"
          f"{(net if net is not None else float('nan')):>18.2f}"
          f"{r['size']:>10.2f}  {str(r['track'])[:14]:<16}{r['est']:<12}")
