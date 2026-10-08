# -*- coding: utf-8 -*-
# lifecycle: oneoff
"""独立验算 0_brief.md 里 UBER 的每一个派生数字（铁律 25：能不能写出算式）。"""
from pathlib import Path

# ---- 原始输入（全部来自证据包 §1/§2/§4 与 supplement）----
close = 68.45
shares = 2_042_560_121
mcap = 139_813_000_000

rev25, rev24, rev23, rev22 = 52_017e6, 43_978e6, 37_281e6, 31_877e6
cogs25, gp25, gp24 = 31_338e6, 20_679e6, 17_327e6
opinc25, opinc24, opinc23, opinc22 = 5_565e6, 2_799e6, 1_110e6, -1_832e6
pretax25, pretax24 = 5_800e6, 4_125e6
tax25, tax24 = -4_346e6, -5_758e6
ni25, ni24 = 10_053e6, 9_856e6
eps25 = 4.73
ttm_ni, ttm_rev = 9_579e6, 55_227e6
ocf25, capex25, fcf25, sbc25 = 10_099e6, 336e6, 9_763e6, 1_826e6
equity25, re25 = 27_041e6, -10_628e6
ca, cl, ta, tl = 13_993e6, 12_320e6, 61_802e6, 33_719e6
gw, inv_fin = 8_931e6, 9_059e6
sma50, sma200, ema10, vwma, bmid, bub, blb = 73.0764, 74.5697, 69.0619, 69.3524, 69.9325, 72.8187, 67.0463
atr = 1.7392
hi52, lo52 = 100.69, 65.41

checks = []


def ck(label, got, want, tol=0.01):
    ok = abs(got - want) <= tol
    checks.append((ok, label, got, want))


# ---- §1 税收收益链 ----
ck("有效税率 %", tax25 / pretax25 * 100, -74.93, 0.02)
ck("税收收益/净利 %", -tax25 / ni25 * 100, 43.24, 0.02)
ck("净利/税前 (倍)", ni25 / pretax25, 1.733, 0.002)
ck("FY2024 税收/净利 %", -tax24 / ni24 * 100, 58.43, 0.02)
# ---- §1.2 序关系 ----
ck("FY2025 毛利率 %", gp25 / rev25 * 100, 39.75, 0.02)
ck("FY2025 营业利润率 %", opinc25 / rev25 * 100, 10.70, 0.02)
ck("FY2025 净利率 %", ni25 / rev25 * 100, 19.32, 0.02)
ck("FY2024 毛利率 %", gp24 / rev24 * 100, 39.40, 0.02)
ck("FY2024 营业利润率 %", opinc24 / rev24 * 100, 6.36, 0.02)
# ---- §1.4 PE 阶梯 ----
ck("PE(FY2025 报表)", mcap / ni25, 13.91, 0.01)
ck("PE(TTM)", mcap / ttm_ni, 14.60, 0.01)
ck("PE(税前 5,800M)", mcap / pretax25, 24.10, 0.02)
ck("PE(假设25%税率)", mcap / (pretax25 * 0.75), 32.14, 0.02)
ck("PB(报表自算)", mcap / equity25, 5.17, 0.01)
ck("PS(TTM)", mcap / ttm_rev, 2.53, 0.01)
ck("市值(元)", close * shares / 1e6, 139_813, 1)
# ---- §2 价格 ----
ck("距 52 周高 %", (close / hi52 - 1) * 100, -32.01, 0.02)
ck("距 52 周低 %", (close / lo52 - 1) * 100, 4.65, 0.02)
# ---- §3 技术距离 ----
for lbl, v, want in [("距 50SMA %", sma50, -6.33), ("距 200SMA %", sma200, -8.21),
                     ("距 10EMA %", ema10, -0.89), ("距 VWMA %", vwma, -1.30),
                     ("距布林中轨 %", bmid, -2.12), ("距布林上轨 %", bub, -6.00),
                     ("距布林下轨 %", blb, 2.09)]:
    ck(lbl, (close / v - 1) * 100, want, 0.02)
ck("ATR/价格 %", atr / close * 100, 2.541, 0.01)
ck("布林带内位置 %", (close - blb) / (bub - blb) * 100, 24.32, 0.02)
# ---- §4 vendor 交叉 ----
ck("vendor PB 隐含权益(亿)", mcap / 5.1120234 / 1e8, 273.62, 0.5)
ck("商誉/总资产 %", gw / ta * 100, 14.5, 0.1)
ck("投资资产/总资产 %", inv_fin / ta * 100, 14.7, 0.1)
# ---- §5 增长率与质量 ----
ck("营收 YoY %", (rev25 / rev24 - 1) * 100, 18.28, 0.02)
ck("营业利润 YoY %", (opinc25 / opinc24 - 1) * 100, 98.8, 0.1)
ck("流动比率(报表)", ca / cl, 1.136, 0.002)
ck("营运资本(百万)", (ca - cl) / 1e6, 1673, 1)
ck("净债/OCF (年)", 3_416e6 / ocf25, 0.338, 0.005)
ck("OCF/净利", ocf25 / ni25, 1.005, 0.003)
ck("FCF/净利", fcf25 / ni25, 0.971, 0.003)
ck("SBC/营业利润 %", sbc25 / opinc25 * 100, 32.81, 0.02)
ck("市值/(FCF-SBC)", mcap / (fcf25 - sbc25), 17.61, 0.02)
ck("capex/OCF %", capex25 / ocf25 * 100, 3.3, 0.05)
ck("L+E+少数股东 vs 总资产(百万)", (tl + equity25 + 1_042e6) / 1e6, ta / 1e6, 1)

bad = [c for c in checks if not c[0]]
for ok, label, got, want in checks:
    flag = "OK " if ok else "XX "
    print(f"{flag}{label:34s} 实算={got:>14,.4f}   简报={want:>14,.4f}")
print()
print(f"合计 {len(checks)} 项，通过 {len(checks) - len(bad)}，失败 {len(bad)}")
if bad:
    print("✗ 需修正：")
    for _, label, got, want in bad:
        print(f"   {label}: 实算 {got} vs 简报 {want}")
