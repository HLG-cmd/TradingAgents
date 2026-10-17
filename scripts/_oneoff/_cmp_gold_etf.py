# lifecycle: oneoff
# created: 2026-10-16
"""A 股黄金 ETF 横向对比：费率 / 规模 / 流动性 / 跟踪指数（选标的用）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wb_analysis._westock import run_westock, parse_md_table  # noqa: E402

CODES = ["sh518880", "sh518800", "sz159934", "sz159937",
         "sz159812", "sz159830", "sh518850", "sh518860"]


def get(cmd: list[str]) -> tuple[list[str], list[list[str]]]:
    return parse_md_table(run_westock(cmd))


# 行情（规模/成交额/换手/量比/涨跌）
qh, qrows = get(["quote", ",".join(CODES)])
qi = {h: i for i, h in enumerate(qh)}
quote = {r[qi["code"]]: r for r in qrows}

ph, prows = get(["etf", "profile", ",".join(CODES)])
pi = {h: i for i, h in enumerate(ph)}
prof = {r[pi["code"]]: r for r in prows}

print(f"{'代码':<10}{'名称':<16}{'管理':>6}{'托管':>6}{'服务':>6}{'合计':>6}"
      f"{'规模(亿)':>11}{'成交额(亿)':>11}{'换手%':>7}{'量比':>6}  {'成立日':<12}{'跟踪指数'}")
print("-" * 118)
rows = []
for c in CODES:
    p, q = prof.get(c), quote.get(c)
    if not p or not q:
        print(f"  {c} 数据缺失")
        continue
    mg = float(p[pi["managementFee"]] or 0)
    cu = float(p[pi["custodyFee"]] or 0)
    sv = float(p[pi["serviceFee"]] or 0)
    ta = float(p[pi["totalAsset"]] or 0) / 1e8
    amt = float(q[qi["amount"]] or 0) / 1e8
    rows.append((c, q[qi["name"]], mg, cu, sv, mg + cu + sv, ta, amt,
                 float(q[qi["turnover_rate"]] or 0), float(q[qi["volume_ratio"]] or 0),
                 str(p[pi["establishDate"]])[:10], p[pi["trackIndexName"]]))

for c, n, mg, cu, sv, t, ta, amt, tr, vr, est, idx in sorted(rows, key=lambda x: -x[6]):
    print(f"{c:<10}{n:<16}{mg:>6.2f}{cu:>6.2f}{sv:>6.2f}{t:>6.2f}"
          f"{ta:>11.2f}{amt:>11.2f}{tr:>7.2f}{vr:>6.2f}  {est:<12}{idx}")

print()
print("=== 收益一致性（同一金价，应几乎相同）===")
print(f"{'代码':<10}{'5日%':>8}{'20日%':>8}{'60日%':>8}{'YTD%':>8}")
for c in CODES:
    q = quote.get(c)
    if not q:
        continue
    print(f"{c:<10}{float(q[qi['chg_5d']] or 0):>8.2f}{float(q[qi['chg_20d']] or 0):>8.2f}"
          f"{float(q[qi['chg_60d']] or 0):>8.2f}{float(q[qi['chg_ytd']] or 0):>8.2f}")
