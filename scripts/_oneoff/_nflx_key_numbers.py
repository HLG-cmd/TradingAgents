# lifecycle: oneoff
# 用途：NFLX 2026-10-08 轮的关键数字一次性算清（供 0_brief.md 引用，避免手算）
# 铁律：① 股数跨 10:1 拆股不可比，只比金额；② 双口径（收盘 69.70 / 盘中 71.015）不可混用
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EV = ROOT / "wb_analysis" / "evidence" / "NFLX_2026-10-08.md"

CLOSE = 69.70          # 2026-10-07 收盘（日线最后一根有效 bar）
RT = 71.015            # 2026-10-08 13:19 美东盘中价（非收盘）
PREV = 69.70
HIGH52, LOW52 = 124.86, 65.08
SMA50, SMA200 = 75.4248, 83.6831
EMA10 = 69.64231014169005
RSI = 41.0308630098061
MACD, MACDS, MACDH = -2.3850762429231906, -2.1163766536815034, -0.26869958924168724
BOLL, BOLL_UB, BOLL_LB = 72.24000091552735, 79.86538855506514, 64.61461327598956
ATR = 1.8395402677376014
VWMA = 70.24998930085934

# 快照（盘中口径）
MCAP_SNAP = 296_597_422_080.0
PE_TTM_SNAP, FWD_PE, PB = 22.399372, 18.71214, 9.837039
EPS_TTM, FWD_EPS, BV = 3.18, 3.80662, 7.241
REV_TTM, NI_TTM = 48_370_765_824.0, 13_649_642_496.0
NET_MARGIN, OPM = 0.28219, 0.33381
ROE, ROA = 0.49541, 0.16084999
DEBT2EQ_PCT, CURR_RATIO = 55.236, 1.142
FCF_SNAP = 25_387_552_768.0          # 快照口径 —— 与现金流量表冲突，见下

# FY2025 报表（SEC 已核验）
REV25, COGS25, OI25 = 45_183_036_000.0, 23_275_329_000.0, 13_326_603_000.0
PRETAX25, TAX25, NI25 = 12_722_552_000.0, 1_741_351_000.0, 10_981_201_000.0
OCF25, CAPEX25, FCF25 = 10_149_273_000.0, -688_220_000.0, 9_461_053_000.0
SBC25, BUYBACK25 = 368_449_000.0, -9_127_167_000.0
DA25 = 16_755_555_000.0
EQ25, ASSETS25 = 26_615_488_000.0, 55_596_993_000.0
GW25 = 32_778_392_000.0
TBV25 = -6_162_904_000.0
CURR_A25, CURR_L25 = 13_020_191_000.0, 10_980_930_000.0
TOTAL_DEBT25, NET_DEBT25 = 14_462_836_000.0, 5_429_155_000.0
SH_DIL25, SH_ORD25 = 4_343_863_000.0, 4_222_162_150.0
REV24, OI24, NI24 = 39_000_966_000.0, 10_417_614_000.0, 8_711_631_000.0
REV23, OI23, NI23 = 33_723_297_000.0, 6_954_003_000.0, 5_407_990_000.0

# 期权（13:18 采集）
SPOT_OPT = 71.06
ATM_C_14, ATM_P_14 = 58.69, 55.44
SKEW_14, SKEW_35, SKEW_98 = -4.27, -1.76, -1.33
ATM_7D, ATM_833D = 32.88, 44.41
PC_VOL_14 = 0.549
OTMPUT_ATMPUT = 0.968


def pct(x):
    return f"{x*100:.2f}%"


def money(x):
    return f"{x/1e9:.2f}B"


print("=" * 92)
print("一、双口径价格与位置")
print("=" * 92)
print(f"  收盘 2026-10-07            : {CLOSE}")
print(f"  盘中 2026-10-08 13:19 ET   : {RT}   （相对收盘 {pct(RT/CLOSE-1)}）")
print(f"  距 52 周高 {HIGH52}          : {pct(CLOSE/HIGH52-1)}   （盘中口径 {pct(RT/HIGH52-1)}）")
print(f"  距 52 周低 {LOW52}           : {pct(CLOSE/LOW52-1)}   （盘中口径 {pct(RT/LOW52-1)}）")
print(f"  距 50 日均 {SMA50}          : {pct(CLOSE/SMA50-1)}")
print(f"  距 200 日均 {SMA200}        : {pct(CLOSE/SMA200-1)}")
print(f"  50/200 关系                : SMA50 {SMA50:.2f} {'<' if SMA50<SMA200 else '>'} SMA200 {SMA200:.2f} -> "
      f"{'死叉（空头排列）' if SMA50 < SMA200 else '金叉'}")
print(f"  距 10 日 EMA {EMA10:.2f}       : {pct(CLOSE/EMA10-1)}")
print(f"  距 VWMA {VWMA:.2f}           : {pct(CLOSE/VWMA-1)}")

print()
print("=" * 92)
print("二、技术指标状态（一律以 2026-10-07 收盘为口径）")
print("=" * 92)
print(f"  RSI                        : {RSI:.2f}  -> {'中性偏弱（未超卖）' if 30 <= RSI < 50 else ('超卖' if RSI < 30 else '偏强')}")
print(f"  MACD / 信号 / 柱           : {MACD:.4f} / {MACDS:.4f} / {MACDH:.4f}")
print(f"    MACD < 信号              : {MACD < MACDS}  -> {'空头' if MACD < MACDS else '多头'}")
print(f"    柱状值走势（01->07）      : -0.738 -> -0.745 -> -0.667 -> -0.489 -> -0.269  -> 负值收敛（背离减弱）")
print(f"  布林 中/上/下              : {BOLL:.2f} / {BOLL_UB:.2f} / {BOLL_LB:.2f}")
bb = (CLOSE - BOLL_LB) / (BOLL_UB - BOLL_LB)
print(f"  布林带内位置               : ({CLOSE:.2f}-{BOLL_LB:.2f})/({BOLL_UB:.2f}-{BOLL_LB:.2f}) = {pct(bb)}")
print(f"  ATR                        : {ATR:.4f}  = {pct(ATR/CLOSE)} of close")
for k in (1.0, 1.5, 2.0):
    print(f"    ATR x {k:<4} 下沿           : {CLOSE - k*ATR:.2f}   上沿 {CLOSE + k*ATR:.2f}")

print()
print("=" * 92)
print("三、估值：双口径 + FCF 陷阱")
print("=" * 92)
print(f"  市值（快照，盘中口径）      : {money(MCAP_SNAP)}")
print(f"  隐含股价校验                : PE {PE_TTM_SNAP:.4f} x EPS {EPS_TTM} = {PE_TTM_SNAP*EPS_TTM:.2f}  "
      f"（vs 收盘 {CLOSE} -> 偏差 {pct(PE_TTM_SNAP*EPS_TTM/CLOSE-1)}）")
print(f"  => 快照价格已按盘中更新，PE 属盘中口径")
print()
mc_close = CLOSE * SH_ORD25
print(f"  按收盘口径重算市值          : {CLOSE} x {SH_ORD25/1e9:.4f}B 股 = {money(mc_close)}")
print(f"  PE 收盘 / 盘中              : {CLOSE/EPS_TTM:.2f}x  /  {PE_TTM_SNAP:.2f}x")
print(f"  PE(FY2025 净利) 收盘        : {mc_close/NI25:.2f}x   （盈利质量门禁用此口径 -> 报表 PE）")
print(f"  Forward PE（快照）          : {FWD_PE:.2f}x   （< TTM {PE_TTM_SNAP:.2f}x -> 隐含盈利增长）")
print(f"  PB                          : {PB:.2f}x  = 市值 / 权益 {money(EQ25)}")
print(f"  !! 有形账面价值             : {money(TBV25)}  —— 为负，PB 无资产含义")
print(f"     商誉+无形 {money(GW25)} / 总资产 {money(ASSETS25)} = {pct(GW25/ASSETS25)}")
print()
print(f"  【FCF 陷阱】快照 FCF         : {money(FCF_SNAP)}")
print(f"        现金流量表 FY2025 FCF  : {money(FCF25)}  （OCF {money(OCF25)} + capex {money(CAPEX25)} = {money(OCF25+CAPEX25)}，自洽 ✓）")
print(f"        两者之比               : {FCF_SNAP/FCF25:.2f}x  -> 快照字段不可信，采用现金流量表")
print(f"  市值/FCF（收盘）            : {mc_close/FCF25:.2f}x")
print(f"  市值/(FCF-SBC)（收盘）      : {mc_close/(FCF25-SBC25):.2f}x")
print(f"  市值/OCF（收盘）            : {mc_close/OCF25:.2f}x")
print(f"  FCF / 净利 FY2025           : {FCF25/NI25:.4f}  -> 现金流{'落后于' if FCF25<NI25 else '领先'}报表利润")
print(f"  SBC / 营业利润              : {pct(SBC25/OI25)}   （极低，NFLX 以现金薪酬为主）")
print(f"  回购 / FCF                  : {pct(-BUYBACK25/FCF25)}  -> 几乎全部 FCF 用于回购")

print()
print("=" * 92)
print("四、税率正常化（低于法定 21% 会抬高净利）")
print("=" * 92)
eff = TAX25 / PRETAX25
print(f"  有效税率 FY2025             : {money(TAX25)} / {money(PRETAX25)} = {pct(eff)}   （法定 21%）")
ni_norm = PRETAX25 * (1 - 0.21)
print(f"  按 21% 正常化净利           : {money(ni_norm)}  vs 报表 {money(NI25)}")
print(f"  报表净利被高估              : {pct(NI25/ni_norm-1)}   （硬线 20% -> "
      f"{'未越线，报表 PE 可用' if NI25/ni_norm-1 < 0.20 else '越线'}）")
print(f"  正常化 PE（收盘，FY25 口径）: {mc_close/ni_norm:.2f}x  vs 报表 {mc_close/NI25:.2f}x")

print()
print("=" * 92)
print("五、成长性与盈利质量")
print("=" * 92)
for name, r0, r1, o0, o1, n0, n1 in (
    ("FY2025/FY2024", REV24, REV25, OI24, OI25, NI24, NI25),
    ("FY2024/FY2023", REV23, REV24, OI23, OI24, NI23, NI24),
):
    print(f"  {name}: 营收 {pct(r1/r0-1)}  营业利润 {pct(o1/o0-1)}  净利 {pct(n1/n0-1)}")
print(f"  FY2025 毛利率               : {pct((REV25-COGS25)/REV25)}")
print(f"  FY2025 营业利润率           : {pct(OI25/REV25)}")
print(f"  FY2025 净利率               : {pct(NI25/REV25)}")
print(f"  净利率 vs 营业利润率        : {pct(NI25/REV25)} {'>' if NI25> OI25 else '<'} {pct(OI25/REV25)}"
      f"  -> {'异常！非经营项抬高' if NI25 > OI25 else '正常（净利<营业利润）'}")
print(f"  FY2025 利息费用净额         : {-604_051_000/1e6:.1f}M（净非经营利息为负=净支出）")
print(f"  ROE / ROA                   : {pct(ROE)} / {pct(ROA)}")
print(f"  资产负债率 D/E              : {DEBT2EQ_PCT}% = {DEBT2EQ_PCT/100:.3f} 倍  （快照字段是百分数，非倍）")
print(f"  流动比率（资产负债表算）    : {CURR_A25/CURR_L25:.3f}   （快照 {CURR_RATIO}）")
print(f"  净债务                      : {money(NET_DEBT25)}")

print()
print("=" * 92)
print("六、期权（2026-10-08 13:18 ET 采集，盘中）")
print("=" * 92)
print(f"  spot                        : {SPOT_OPT}   等级 FULL   16/16 到期日   1416 合格样本")
print(f"  ATM call / put（14天）      : {ATM_C_14} / {ATM_P_14}  -> ATM_P - ATM_C = {ATM_P_14-ATM_C_14:+.2f}pp")
print(f"  25Δ 偏斜 14/35/98 天        : {SKEW_14:+.2f} / {SKEW_35:+.2f} / {SKEW_98:+.2f} pp  -> "
      f"{'全部为负=认购侧更贵' if all(s < 0 for s in (SKEW_14, SKEW_35, SKEW_98)) else '不一致'}")
print(f"  P/C 成交量比（14天）        : {PC_VOL_14}  -> 认购成交约为认沽的 {1/PC_VOL_14:.2f}x")
print(f"  OTM put / ATM put           : {OTMPUT_ATMPUT}  (<1 -> 虚值认沽不贵于平价)")
print(f"  期限结构 7天 {ATM_7D} vs 833天 {ATM_833D}  : 斜率 {ATM_7D-ATM_833D:+.2f}pp（近低远高=正向）")
print()
print(f"  【14 天档为何异常高】7天 {ATM_7D} < 14天 {ATM_C_14} > 35天 45.28 > 98天 38.61 -> 非单调")
print(f"     与财报日 2026-10-20（距今 12 天）吻合：14 天档（10-23 到期）跨越财报")
import math
T = 14 / 365.0
em = 0.8 * (ATM_C_14 / 100.0) * math.sqrt(T) * SPOT_OPT
print(f"     跨财报 straddle 隐含波动 : 0.8 x {ATM_C_14/100:.4f} x sqrt({T:.5f}) x {SPOT_OPT} = "
      f"+/-{em:.2f} 美元 = +/-{pct(em/SPOT_OPT)}")
T2 = 7 / 365.0
em2 = 0.8 * (ATM_7D / 100.0) * math.sqrt(T2) * SPOT_OPT
print(f"     财报前 7 天档            : +/-{em2:.2f} 美元 = +/-{pct(em2/SPOT_OPT)}")
print(f"  !! 样本量极小：14 天档 25Δ 配对 n=2/2，35 天 n=3/3，98 天 n=4/5")
print(f"     12:58 与 13:18 两次采集 25Δ 偏斜：14天 -0.26 -> -4.27（20 分钟移动 4.01pp）")
print(f"     => 偏斜只能读方向，不能读数值")

print()
print("=" * 92)
print("七、内部人交易（解析证据包 §8）")
print("=" * 92)
txt = EV.read_text(encoding="utf-8")
seg = txt.split("## 8. 内部人交易")[1].split("## 9.")[0]
rows = []
for line in seg.splitlines():
    if not re.match(r"^\d+,", line.strip()):
        continue
    f = line.split(",")
    if len(f) < 10:
        continue
    try:
        shares = float(f[1]); val = float(f[2])
    except ValueError:
        continue
    rows.append({"shares": shares, "val": val, "text": f[4], "who": f[5],
                 "role": f[6], "date": f[8]})

sales = [r for r in rows if r["text"].startswith("Sale")]
buys = [r for r in rows if "Purchase" in r["text"] or r["text"].startswith("Buy")]
exer = [r for r in rows if r["text"].startswith("Conversion")]
gifts = [r for r in rows if "Gift" in r["text"]]
awards = [r for r in rows if "Award" in r["text"]]
print(f"  总行数 {len(rows)}  卖出 {len(sales)}  行权 {len(exer)}  赠与 {len(gifts)}  授予 {len(awards)}")
print(f"  !! 公开市场买入笔数         : {len(buys)}  -> {'零买入' if not buys else '有买入'}")
tot_sale = sum(r["val"] for r in sales)
print(f"  卖出总金额                  : {money(tot_sale)}")

def since(d):
    return [r for r in sales if r["date"] >= d]

for label, d in (("近 12 个月", "2025-10-08"), ("近 6 个月", "2026-04-08"), ("近 90 天", "2026-07-10")):
    s = since(d)
    print(f"  {label:<12} 卖出 {len(s):>3} 笔  合计 {money(sum(r['val'] for r in s))}")

print()
print("  按人汇总（全窗口，按卖出金额降序）:")
agg = {}
for r in sales:
    agg.setdefault(r["who"], {"n": 0, "v": 0.0})
    agg[r["who"]]["n"] += 1
    agg[r["who"]]["v"] += r["val"]
for who, d in sorted(agg.items(), key=lambda kv: -kv[1]["v"]):
    role = next((r["role"] for r in sales if r["who"] == who), "")
    print(f"    {who:<34} {role:<26} {d['n']:>3} 笔  {money(d['v'])}")

print()
print("  最近 8 笔卖出:")
for r in sorted(sales, key=lambda x: x["date"], reverse=True)[:8]:
    print(f"    {r['date']}  {r['who']:<34} {money(r['val']):>8}  {r['text'][:52]}")

print()
print("  !! 拆股提示：2025-11 成交价 ~1100 美元/股，2025-12 起 ~108 美元/股")
print("     => 期间发生 10:1 拆股，**股数不可跨期比较，只能用金额**")
