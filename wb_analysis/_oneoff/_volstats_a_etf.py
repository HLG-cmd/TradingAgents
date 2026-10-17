# lifecycle: oneoff
# created: 2026-10-14
# 一次性探针：量能机算（A股ETF）。用完即删，审计线索保留。
import re, statistics, pathlib, sys

def load(t):
    txt = (pathlib.Path("wb_analysis/evidence") / f"{t}_2026-10-13.md").read_text(encoding="utf-8")
    rows = []
    for l in txt.splitlines():
        m = re.match(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", l)
        if m:
            rows.append((m.group(1), float(m.group(3)), int(m.group(6)), int(m.group(7))))
    rows.reverse()
    return rows

for t in ["515100", "512400.SS"]:
    r = load(t)
    if not r:
        print(f"=== {t}: 解析到 0 行（正则或路径问题）")
        continue
    vols = [x[2] for x in r]
    amts = [x[3] for x in r]
    print(f"=== {t}: {len(r)} bars, {r[0][0]} ~ {r[-1][0]}")
    for w in (5, 10, 20, 60):
        if len(vols) >= w:
            print(f"   {w}日均量: {statistics.fmean(vols[-w:]):,.0f} 手 ｜ {w}日均额: {statistics.fmean(amts[-w:]):,.0f} 元")
    v20 = statistics.fmean(vols[-20:])
    print(f"   末日量: {vols[-1]:,} 手 = 20日均量的 {vols[-1]/v20*100:.1f}%")
    print(f"   近5日量: {[f'{v:,}' for v in vols[-5:]]}")
    print(f"   近5日收盘: {[f'{x[1]:.3f}' for x in r[-5:]]}")
    print(f"   近5日单日涨跌: {[f'{(r[i][1]/r[i-1][1]-1)*100:+.2f}%' for i in range(len(r)-5, len(r))]}")
    print(f"   全窗口量最大3日: {sorted([(v, d) for d, c, v, a in r], reverse=True)[:3]}")
