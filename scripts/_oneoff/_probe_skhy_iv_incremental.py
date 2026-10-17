# lifecycle: oneoff
# SKHY 2026-10-11：期权 ATM IV 期限结构的「增量方差」分解
# 目的：把「18 天驼峰」从定性判据升级为可引用的日均 sigma 数字，
#       供中性风险席位独立引用（铁律 42：核验断言必须自己复算）。
#
# 方法：sigma(T)^2 * T/252 = 到 T 天的累计方差；
#       相邻两档之差 ÷ 天数差 = 该区间内的日均方差（区间 sigma）。
#       该法只在同一张快照内部做差，不跨快照比较，故不受铁律 12/36 约束。

import math

# ATM IV 期限结构（简报 §3.5 原值：天数 -> IV，小数形式）
IV = [(4, 0.5993), (11, 0.5204), (18, 0.5963), (25, 0.5706), (32, 0.5683), (830, 0.6033)]
PX = 169.03          # 2026-10-09 收盘（测点）
ATR = 8.42
BOLL_LB = 167.77
SUPPORT_LO = 167.21

TRADING_DAYS = 252


def cum_var(tau_days: int, iv: float) -> float:
    """到 tau_days 为止的累计（总）方差。"""
    return iv * iv * tau_days / TRADING_DAYS


print("=" * 78)
print("SKHY ATM IV 增量方差分解 —— 基准日 2026-10-11 / 数据日 2026-10-09")
print("=" * 78)

# 基线：0 ~ 11 天（视为「无事件的近期常态」）
t0, iv0 = 11, dict(IV)[11]
base_var = cum_var(t0, iv0)
base_daily_var = base_var / t0
base_sigma = math.sqrt(base_daily_var)
print(f"\n[基线] 0~{t0} 天：ATM IV {iv0*100:.2f}%")
print(f"   累计方差 {base_var:.6f} / {t0} 天")
print(f"   日均 sigma = {base_sigma*100:.3f}%   = {base_sigma*PX:.2f} 美元")
print(f"   对照：ATR {ATR} = 现价 {ATR/PX*100:.3f}%")

print("\n[增量] 相邻档之间（区间日均 sigma）")
print(f"{'区间':>10} {'天数差':>7} {'累计方差差':>11} {'区间日均σ':>10} {'/基线':>7} {'折美元':>8}")
rows = []
for (t1, iv1), (t2, iv2) in zip(IV, IV[1:]):
    d = t2 - t1
    dv = cum_var(t2, iv2) - cum_var(t1, iv1)
    if dv <= 0:
        continue
    s = math.sqrt(dv / d)
    ratio = s / base_sigma
    rows.append((t1, t2, d, dv, s, ratio))
    print(f"{t1:>4}->{t2:<4} {d:>7} {dv:>11.6f} {s*100:>9.3f}% {ratio:>6.2f}x {s*PX:>7.2f}")

print("\n[解读] 事件窗口 vs 结构距离")
evt = max(rows, key=lambda r: r[4])
t1, t2, d, dv, s, ratio = evt
print(f"   峰值区间 = {t1}->{t2} 天（{d} 天）  区间日均 sigma = {s*100:.3f}% = {ratio:.2f}x 基线 = {s*PX:.2f} 美元")
print(f"   距布林下轨 {BOLL_LB} = {PX-BOLL_LB:.2f} 美元 = 事件日均 sigma 的 {(PX-BOLL_LB)/(s*PX):.3f} 倍")
print(f"   距近20根最低 {SUPPORT_LO} = {PX-SUPPORT_LO:.2f} 美元 = 事件日均 sigma 的 {(PX-SUPPORT_LO)/(s*PX):.3f} 倍")
print(f"   基线日均 sigma {base_sigma*PX:.2f} 美元 已相当于 到下轨距离的 {(PX-BOLL_LB)/(base_sigma*PX):.3f} 倍倒数"
      f"（即下轨距离仅为基线日 sigma 的 {(PX-BOLL_LB)/(base_sigma*PX):.3f}）")

# 尾部区间（18->32 天）应回落到基线附近，证明「驼峰」是局部而非全局
tail = [r for r in rows if r[0] == 18][0]
print(f"\n[对照] {tail[0]}->{tail[1]} 天区间日均 sigma = {tail[4]*100:.3f}% = {tail[5]:.2f}x 基线"
      f" ⇒ 事件溢价{'集中' if tail[5] < 1.15 else '扩散'}于 {t1}~{t2} 天档，非全局抬升")

# 与 ATR 对照
print(f"\n[交叉校验] ATR 口径日振幅 = {ATR/PX*100:.3f}%")
print(f"   基线 sigma {base_sigma*100:.3f}% / ATR {ATR/PX*100:.3f}% = {base_sigma*PX/ATR:.3f}")
print(f"   事件 sigma {s*100:.3f}% / ATR {ATR/PX*100:.3f}% = {s*PX/ATR:.3f}")
print("   ⇒ ATR 与 IV 属不同口径（已实现振幅 vs 前瞻 IV），仅作量级参照，不可互相换算（铁律 13）")
print("=" * 78)
