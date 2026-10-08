# lifecycle: oneoff
# serves: NDX 2026-09-29 第 6 环交易员稿的全部算式复算（跳空样本扫描、EMA 精确递推、
#         首达概率恒等式 EV≡0 的六组合验证、RRR=1 临界入场价、日漂移后的结构价位）。
#         原文首 FINAL TRANSACTION PROPOSAL: **SELL**。保留以便第三方复核，不随产品线演进。
# -*- coding: utf-8 -*-
import math
from statistics import stdev

def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

P = 30339.33
ATR = 385.716955127195
ema10 = 30168.89920281546
sma50 = 29355.728125
bollub = 30949.86930636967
U52 = 30770.63

rows = [("2026-09-01", 29056.58, 29267.42, 28953.26, 29077.22),
        ("2026-09-02", 29016.00, 29165.62, 28971.90, 29143.33),
        ("2026-09-03", 29234.42, 29538.76, 29160.96, 29482.32),
        ("2026-09-04", 29539.57, 29655.22, 29440.15, 29544.15),
        ("2026-09-08", 29645.18, 29655.73, 29400.70, 29507.70),
        ("2026-09-09", 29431.94, 29563.60, 29334.40, 29421.55),
        ("2026-09-10", 29097.34, 29250.41, 29038.22, 29103.51),
        ("2026-09-11", 29331.48, 29473.12, 29313.51, 29368.44),
        ("2026-09-14", 28890.93, 29285.50, 28867.67, 29127.16),
        ("2026-09-15", 29100.16, 29142.80, 28899.43, 28937.84),
        ("2026-09-16", 29110.04, 29235.89, 28753.29, 28945.06),
        ("2026-09-17", 29401.54, 29494.95, 29305.90, 29446.98),
        ("2026-09-18", 29529.64, 29647.80, 29371.89, 29644.17),
        ("2026-09-21", 29947.16, 30557.34, 29933.22, 30482.35),
        ("2026-09-22", 30496.43, 30770.63, 30496.43, 30732.40),
        ("2026-09-23", 30706.23, 30706.23, 30353.88, 30470.29),
        ("2026-09-24", 30225.19, 30529.35, 30204.16, 30478.86),
        ("2026-09-25", 30517.46, 30667.56, 30413.59, 30608.13),
        ("2026-09-28", 30426.63, 30480.40, 30081.06, 30276.81),
        ("2026-09-29", 30412.29, 30429.97, 30235.66, 30339.33)]

print("=== 隔夜跳空（开 vs 前收）===")
gaps = []
for i in range(1, len(rows)):
    g = rows[i][1] - rows[i - 1][4]
    gaps.append((rows[i][0], round(g, 2), round(g / rows[i - 1][4] * 100, 3)))
for x in gaps:
    print(x)
down = [g for _, g, _ in gaps if g < 0]
up = [g for _, g, _ in gaps if g > 0]
print(f"向下跳空 {len(down)}/{len(gaps)} 次，均值 {sum(down)/len(down):.2f}，最大 {min(down):.2f} 点 = {min(down)/P*100:.3f}% = {abs(min(down))/ATR:.4f} ATR")
print(f"向上跳空均值 {sum(up)/len(up):.2f}")
print(f"向下跳空超过 0.25 ATR({0.25*ATR:.2f}) 的次数：{sum(1 for g in down if abs(g) > 0.25*ATR)}")

print("\n=== 首达概率与期望值恒等式（算术布朗运动，线性价格空间）===")
def pu(S, U, L):
    return (S - L) / (U - L)
for (U, L, tag) in [(U52, sma50, "上52周高/下50SMA"),
                    (bollub, P - ATR, "上布林上轨/下-1ATR"),
                    (U52, P - ATR, "上52周高/下-1ATR"),
                    (U52, ema10 - ATR, "上52周高/下10EMA-1ATR"),
                    (P + ATR, P - ATR, "上+1ATR/下-1ATR"),
                    (bollub, ema10 - ATR, "上布林上轨/下10EMA-1ATR")]:
    p = pu(P, U, L)
    ev = p * (U - P) - (1 - p) * (P - L)
    print(f"{tag:26s} p_up={p:.4f}  距离赔率={(U-P)/(P-L):.4f}  EV={ev:.6f}")

print("\n=== 预期首达时间 E[tau]=xu*xl/sigma^2（对数距离）===")
cl = [r[4] for r in rows]
r = [math.log(cl[i + 1] / cl[i]) for i in range(len(cl) - 1)]
sd = stdev(r)
sd5 = stdev(r[-5:])
print(f"sigma(19日)={sd:.6%}  sigma(近5日)={sd5:.6%}  ATR%={ATR/P:.6%}  VXN隐含日={22.07/math.sqrt(252):.4f}%")
for U, L, tag in [(U52, sma50, "52周高/50SMA"), (bollub, P - ATR, "布林上轨/-1ATR"), (U52, ema10 - ATR, "52周高/10EMA-1ATR")]:
    xu = math.log(U / P); xl = math.log(P / L)
    out = []
    for s, lab in [(sd, "s19"), (sd5, "s5"), (ATR / P, "ATR"), (22.07 / math.sqrt(252) / 100, "VXN")]:
        out.append(f"{lab}={xu*xl/(s*s):.3f}")
    print(f"{tag:20s} " + "  ".join(out))

print("\n=== 触及概率 2*Phi(-a/(sigma*sqrt(T))) ===")
for T in [5, 10, 21]:
    for s, lab in [(sd, "s19"), (sd5, "s5")]:
        line = [f"T={T:2d} {lab}"]
        for a, tag in [(ATR, "下1ATR"), (0.5 * ATR, "下0.5ATR"), (bollub - P, "上布林轨"), (U52 - P, "上52周高")]:
            z = a / (P * s * math.sqrt(T))
            line.append(f"{tag} z={z:.4f} P={2*ncdf(-z):.4f}")
        print("  ".join(line))

print("\n=== 10EMA 几何收敛 ===")
a = 2 / 11
gap = P - ema10
for frac in [0.5, 0.75, 0.9, 0.95, 0.99]:
    print(f"缺口收敛 {frac:.0%} 需 {math.log(1-frac)/math.log(1-a):.3f} 日")
for thr, lab in [(ATR * 0.5, "0.5ATR"), (ATR * 0.25, "0.25ATR"), (ATR * 0.1, "0.1ATR")]:
    print(f"缺口 ≤ {lab}({thr:.2f}) 需 {math.log(thr/gap)/math.log(1-a):.3f} 日")
e = ema10; out = []
for i in range(11):
    e = e + a * (P - e); out.append(round(e, 4))
print("冻结价下 10EMA D1-D10:", out)
lin = [ema10 + 73.2873 * i for i in range(1, 6)]
print("线性外推 D1-D5:", [round(x, 2) for x in lin])
print(f"D5 线性 vs 几何 差 = {lin[4]-out[4]:.4f}；线性外推越过固定价格所需 {gap/73.2873:.4f} 日（几何口径永不到达）")
atr5 = ATR - 5.3372 * 5
print(f"D5 ATR(线性漂移) = {atr5:.4f}；D5 的 10EMA-1ATR = {out[4]-atr5:.4f} vs 9-29 静态值 {ema10-ATR:.4f}，差 {out[4]-atr5-(ema10-ATR):.4f}")

print("\n=== 刷新后估值的情景重算 ===")
ey = 1 / 30.01 * 100
fey = 1 / 21.79 * 100
rf = 5.26
Et = 43.178 / 30.01
Ef = 43.178 / 21.79
print(f"1/PE={ey:.4f}%  TTM ERP={ey-rf:.4f}pp ; 1/FwdPE={fey:.4f}%  前瞻ERP={fey-rf:.4f}pp")
print(f"SigE(TTM)={Et:.5f}T  SigE(fwd)={Ef:.5f}T  增量={(Ef-Et)*10000:.1f}B  隐含增速={Ef/Et-1:.4%}")
s5 = (fey - 0.0202) / (1 - 0.0326)
print(f"情景5 剔除TSLA 前瞻收益率={s5:.4f}%  ERP={s5-rf:.4f}pp")
new6 = Et * 1.285
pe6 = 43.178 / new6
print(f"情景6 中位数增速28.5%: SigE={new6:.5f}T PE={pe6:.4f} 收益率={100/pe6:.4f}% ERP={100/pe6-rf:.4f}pp")
pe0 = 100 / rf
print(f"ERP=0 需 PE={pe0:.4f} ⇒ 价格 {P*pe0/30.01:.2f}（跌幅 {pe0/30.01-1:.4%}）；或 rf 下行 {rf-ey:.4f}pp")
print(f"混合口径 NVDA+MU 增量占刷新后增量之比 = 320.16/{(Ef-Et)*10000:.1f} = {320.16/((Ef-Et)*10000)*100:.2f}%")
alpha = 43.178 / 42.181
print(f"若成分同步按 alpha={alpha:.5f} 缩放，占比不变 = {320.16*alpha/(522.72*alpha)*100:.2f}%")
