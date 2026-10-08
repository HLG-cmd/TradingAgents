# lifecycle: maintenance
# 用途：WDC 2026-10-06 基线估值自算（§3 快照被上游 withheld ⇒ 不可用厂商估值倍数）
# 原则：所有数字给出算式，可直接复算；多口径并列，不用单一口径冒充"那个"估值。
PRICE = 411.04  # 2026-10-06 收盘（口径 A，日线最后一根完整 bar）

# ---- 股数三口径（铁律 23）----
SH = {
    "ordinary_361M(主锚)": 361.0,
    "basic_avg_345M(报表EPS反算吻合)": 345.0,
    "diluted_avg_383M(保守边界)": 383.0,
}
NI = 9298.0            # Net Income FY2026（2026-06-30）
NI_C = 9424.0          # Net Income From Continuing Operations
OPINC = 4599.0         # Operating Income（不含 Other Income/Expense 的干净口径）
REV = 12919.0
GP = 6311.0
EBITDA_REP = 10445.0
EBITDA_NORM = 4638.0
EBIT_REP = 10070.0
UNUSUAL = 5807.0
OTHER_INC = 5420.0
OCF = 3929.0
FCF = 3511.0
CAPEX = -418.0
DA = 375.0
SBC = 204.0
DWC = -658.0
EQ = 8864.0
EQ_PREV = 5540.0
TBV = 4543.0
TA = 13861.0
DEBT = 1052.0
CASH = 1579.0
TAX_RATE_VENDOR = 0.05
TAX_RATE_EFF = 481.0 / 9905.0
TAX_RATE_PREV = 0.2557

print("=" * 78)
print("WDC 估值自算  基线收盘 %.2f @2026-10-06" % PRICE)
print("=" * 78)

print("\n--- 0. 有效税率三口径 ---")
print("  vendor Tax Rate For Calcs FY2026 : %.4f%%" % (TAX_RATE_VENDOR * 100))
print("  实际有效税率 481/9905            : %.4f%%" % (TAX_RATE_EFF * 100))
print("  FY2025 有效税率(更代表性)         : %.4f%%" % (TAX_RATE_PREV * 100))

print("\n--- 1. EPS 口径交叉校验（报的 Diluted EPS=26.92 到底用哪个股数）---")
for k, v in SH.items():
    print("  NI(NI-common 9286)/%7.1f = %8.4f  |  NI_cont 9424/%7.1f = %8.4f"
          % (v, 9286.0 / v, v, NI_C / v))
print("  ⇒ 厂商标注 'Diluted EPS 26.92' 实际等于 9286/345=%.4f（Basic 股数），" % (9286.0 / 345.0))
print("     与 Diluted 383M 口径 %.4f 不符 ⇒ 引用时必须声明用哪个。" % (9286.0 / 383.0))

print("\n--- 2. 市值 / EV 三口径 ---")
debt_net = CASH - DEBT
print("  Total Debt %.1f  Cash %.1f  ⇒ 净现金 %.1f（表内 Net Debt 字段为空，实为净现金）"
      % (DEBT, CASH, debt_net))
mc = {}
ev = {}
for k, v in SH.items():
    mc[k] = PRICE * v
    ev[k] = mc[k] - debt_net
    print("  %-38s 市值 %10.1fM  EV %10.1fM" % (k, mc[k], ev[k]))

MAIN = "ordinary_361M(主锚)"
MC, EVv = mc[MAIN], ev[MAIN]
print("  ⇒ 主锚采用 %s：市值 %.1fM，EV %.1fM" % (MAIN, MC, EVv))

print("\n--- 3. 报告口径倍数（含一次性，'便宜陷阱'）---")
print("  P/E(报的EPS 26.92)        = %.2f / %.2f          = %6.2fx" % (PRICE, 26.92, PRICE / 26.92))
print("  P/E(NI/361M=%.4f)        = %.2f / %.4f        = %6.2fx"
      % (NI / 361.0, PRICE, NI / 361.0, PRICE / (NI / 361.0)))
print("  EV/EBITDA(reported %.0f)  = %.1f / %.0f      = %6.2fx" % (EBITDA_REP, EVv, EBITDA_REP, EVv / EBITDA_REP))
print("  EV/EBIT(reported %.0f)    = %.1f / %.0f      = %6.2fx" % (EBIT_REP, EVv, EBIT_REP, EVv / EBIT_REP))
print("  EV/Revenue               = %.1f / %.0f      = %6.2fx" % (EVv, REV, EVv / REV))
print("  EV/FCF                   = %.1f / %.0f       = %6.2fx" % (EVv, FCF, EVv / FCF))
print("  EV/(One-off-included) vs EV/FCF 差距 ⇒ EBITDA 便宜度被一次性项目撑起 %.2f 倍"
      % ((EBITDA_REP / EBITDA_NORM)))
print("  盈利收益率(报告)          = %.2f%%" % (100 * 26.92 / PRICE))
print("  FCF 收益率                = %.2f%%" % (100 * FCF / MC))

print("\n--- 4. 正常化（扣除一次性）---")
print("  EBITDA: reported %.0f − unusual %.0f = normalized %.0f  ✓ 与表内 Normalized EBITDA %.0f 一致"
      % (EBITDA_REP, UNUSUAL, EBITDA_REP - UNUSUAL, EBITDA_NORM))
pretax_norm = 9905.0 - UNUSUAL
print("  Pretax: 9905 − %.0f = %.1f" % (UNUSUAL, pretax_norm))
scenarios = {
    "S1 一次性按 0% 计税(非应税处置/重估)": 0.0,
    "S2 按 FY2026 实际有效税率 %.2f%%" % (TAX_RATE_EFF * 100): TAX_RATE_EFF,
    "S3 按 FY2025 有效税率 %.2f%%" % (TAX_RATE_PREV * 100): TAX_RATE_PREV,
    "S4 按法定 21%": 0.21,
}
print("  正常化净利情景（Pretax %.1f × (1−税率)）:" % pretax_norm)
for k, r in scenarios.items():
    v = pretax_norm * (1 - r)
    epsc = v / 361.0
    print("    %-40s NI=%8.1fM  EPS(361M)=%7.3f  P/E=%6.2fx"
          % (k, v, epsc, PRICE / epsc))
lo = pretax_norm * (1 - 0.21) / 361.0
hi = pretax_norm / 361.0
print("  ⇒ 正常化 P/E 区间: %.2fx ~ %.2fx（股数 361M）" % (PRICE / hi, PRICE / lo))
print("  EV/Normalized EBITDA = %.1f / %.0f = %.2fx" % (EVv, EBITDA_NORM, EVv / EBITDA_NORM))
print("  EV/Operating Income  = %.1f / %.0f = %.2fx" % (EVv, OPINC, EVv / OPINC))

print("\n--- 5. 账面与回报率（铁律 28：一次性同时顶高净利率与 ROE）---")
print("  BVPS  = %.0f / 361 = %.3f  ⇒ P/B   = %.2fx" % (EQ, EQ / 361.0, PRICE / (EQ / 361.0)))
print("  TBVPS = %.0f / 361 = %.3f  ⇒ P/TBV = %.2fx" % (TBV, TBV / 361.0, PRICE / (TBV / 361.0)))
avg_eq = (EQ + EQ_PREV) / 2
print("  ROE(报,期末权益) = %.0f / %.0f = %.2f%%" % (NI, EQ, 100 * NI / EQ))
print("  ROE(报,平均权益) = %.0f / %.1f = %.2f%%" % (NI, avg_eq, 100 * NI / avg_eq))
sc = pretax_norm * (1 - TAX_RATE_EFF)
print("  ROE(正常化S2,平均权益) = %.1f / %.1f = %.2f%%" % (sc, avg_eq, 100 * sc / avg_eq))
print("  ROA(报) = %.0f / %.0f = %.2f%% | ROA(正常化S2) = %.1f / %.0f = %.2f%%"
      % (NI, TA, 100 * NI / TA, sc, TA, 100 * sc / TA))
print("  净利率(报) = %.0f/%.0f = %.2f%% | 营业利润率 = %.0f/%.0f = %.2f%% | 毛利率 = %.0f/%.0f = %.2f%%"
      % (NI, REV, 100 * NI / REV, OPINC, REV, 100 * OPINC / REV, GP, REV, 100 * GP / REV))
print("  商誉占总资产 = %.0f / %.0f = %.2f%%" % (4321.0, TA, 100 * 4321.0 / TA))

print("\n--- 6. 现金流质量（核心地雷）---")
print("  OCF / 净利 = %.0f / %.0f = %.4f   ⇒ %.2f%% 的净利未转化为经营现金流"
      % (OCF, NI, OCF / NI, 100 * (1 - OCF / NI)))
print("  FCF / 净利 = %.0f / %.0f = %.4f" % (FCF, NI, FCF / NI))
print("  OCF / Operating Income = %.0f / %.0f = %.4f  ⇒ 连不含一次性的营业利润都只覆盖 %.2f%%"
      % (OCF, OPINC, OCF / OPINC, 100 * OCF / OPINC))
print("  CAPEX / OCF = %.0f / %.0f = %.2f%%" % (abs(CAPEX), OCF, 100 * abs(CAPEX) / OCF))
print("  D&A / Revenue = %.0f / %.0f = %.2f%%（对硬件制造偏低）" % (DA, REV, 100 * DA / REV))

print("\n--- 7. 现金流量表残差 pursuit（推断项，非报表科目）---")
known = NI_C + DA + SBC + DWC
plug = OCF - known
print("  CFO %.0f − (NI_cont %.0f + D&A %.0f + SBC %.0f + ΔWC %.0f) = %.0f - %.1f = %.1f"
      % (OCF, NI_C, DA, SBC, DWC, OCF, known, plug))
print("  |残差| %.1f  vs  Other Income Expense %.1f  ⇒ 差 %.1f（%.4f%%）"
      % (abs(plug), OTHER_INC, abs(abs(plug) - OTHER_INC),
         100 * abs(abs(plug) - OTHER_INC) / OTHER_INC))
print("  ⇒ 推断：存在约 %.0fM 的非现金转回，量级与 Other Income Expense 吻合。" % abs(plug))
print("     投资活动现金流 = -429.0M（净流出）⇒ 无大额处置收款佐证。")
print("  ⚠️ 反向对照 FY2025：NI_cont 1889 + D&A 451 + SBC 265 + ΔWC -1031 = %.1f，CFO 1691 ⇒ 残差 %+.1f"
      % (1889.0 + 451.0 + 265.0 - 1031.0, 1691.0 - (1889.0 + 451.0 + 265.0 - 1031.0)))
print("     FY2025 残差 %+.1f 与当年 Other Income Expense -688.0 不吻合 ⇒ FY2026 的吻合是高度提示，非证明。"
      % (1691.0 - (1889.0 + 451.0 + 265.0 - 1031.0)))

print("\n--- 8. 债务变动未解释部分 ---")
print("  Total Debt FY2025 4711 → FY2026 1052，变动 %.1f" % (1052.0 - 4711.0))
print("  融资活动: 发债 1946 − 还债 2884 = %.1f" % (1946.0 - 2884.0))
print("  缺口 %.1fM 未在给定科目中解释（可能含转换/汇兑/其他融资科目）⇒ 登记为待查项"
      % ((1052.0 - 4711.0) - (1946.0 - 2884.0)))

print("\n--- 9. 营运资本效率 ---")
for yr, ar, rev, inv, cogs in [("FY2026", 2026.0, REV, 1511.0, 6608.0), ("FY2025", 1486.0, 9520.0, 1291.0, 5828.0)]:
    print("  %s DSO = %.0f/%.0f*365 = %.1f 天 | 存货天数 = %.0f/%.0f*365 = %.1f 天"
          % (yr, ar, rev, ar / rev * 365, inv, cogs, inv / cogs * 365))

print("\n--- 10. 与无风险利率对照 ---")
for rf_name, rf in [("^TNX 10-06 收盘 5.27%", 5.27), ("FRED DGS10(待核)", float("nan"))]:
    if rf == rf:
        print("  FCF 收益率 2.37%% vs %s ⇒ ERP = %+.0f bp" % (rf_name, 100 * (100 * FCF / MC - rf)))
        print("  盈利收益率(报) 6.55%% vs %s ⇒ ERP = %+.0f bp" % (rf_name, 100 * (100 * 26.92 / PRICE - rf)))
        print("  正常化盈利收益率(S2, %.3f/%.2f=%.2f%%) vs %s ⇒ ERP = %+.0f bp"
              % (sc / 361.0, PRICE, 100 * (sc / 361.0) / PRICE, rf_name,
                 100 * (100 * (sc / 361.0) / PRICE - rf)))
print("=" * 78)
