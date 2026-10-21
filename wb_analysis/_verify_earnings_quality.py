# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_earnings_quality.py
#!/usr/bin/env python
"""收益质量验证器 —— 挡掉「报表净利被一次性项目抬高」这一类失真。

**为什么需要它（2026-09-21 事件）**
筛子输出的 `pe` 被当成「便宜的证据」，但 DUOL 与 ACAD 两只得分最高的候选，
其报表净利都来自**负税**：
  - DUOL：有效税率 −127.0%，税项是税前利润的 127%，报表 PE 16.0x → **正常化 40.1x**
  - ACAD：有效税率 −181.5%，税项是税前利润的 181.5%，报表 PE 12.0x → **正常化 38.6x**
「ROE ≥ 20% / 净利率 ≥ 15%」这类阈值门槛**拦不住它** —— 一次性税收收益会同时
把净利率与 ROE 顶上去，两个门槛都会放行。**缺的不是更严的阈值，是检查利润来源。**

**判据（三闸门，都是单向的）**
  Q3 负税闸门      ：`Tax Provision < 0` 且 |税项| 与税前利润同量级 ⇒ FAIL
  Q4 正常化一致性  ：`正常化PE > tolerance x 报表PE` ⇒ FAIL（只挡「报表被高估」方向）
  Q5 非经营收益闸门 ：`Gain On Sale Of Security`（含权益证券公允价值变动）占净利比例过高 ⇒ FAIL
正常化净利 = 税前利润 x (1 − 历史有效税率中位数)，中位取最近 N 个正税期。

**为什么需要 Q5（2026-10-08 GOOG 事件）**
Q3/Q4 只看得见「税收」这一条扭曲路径。GOOG 的报表 PE(TTM) 17.3x 看着便宜，
实际拆开是：TTM 净利 244.2B 中 **136.0B（55.7%）来自 `Gain on equity securities, net`**
—— 即**未实现**的股权公允价值重估（SEC 10-Q 原值：Q2'26 单季 99,031M）。
经营性 TTM 净利只有 95.9B ⇒ **经营性 PE 44.1x**，是报表值的 2.5 倍。
现金流侧印证：OCF/净利 从 FY2025 的 1.25 掉到 0.76，且 FCF(TTM) 仅 22.7B。
**这一类失真 Q3/Q4 都拦不住**（税率正常、正常化PE≈报表PE），且它比负税更常见
—— 凡持有大额可交易股权（GOOG/META/BABA/软银式）或公允价值计价的标的都会命中。
⚠️ 归因说明：本闸门测的是「**报表净利中有多少不来自经营**」，不是「管理层是否操纵」。
   权益证券浮盈是**会计准则要求**的入账，不是造假。判定为 FAIL 的含义是
   「**报表 PE 不是可信的估值输入**」，必须改用经营性口径重算后再比较。

**用法**
    python wb_analysis/_verify_earnings_quality.py --from-radar reports/radar_sp1500_2026-09-20.csv --top 105
    python wb_analysis/_verify_earnings_quality.py --tickers DUOL,KNSL,ACAD
    python wb_analysis/_verify_earnings_quality.py --from-radar ... --top 105 --exit-on-fail   # CI: 有 FAIL 则退出码 2

**退出码**：0 = 无 FAIL；2 = 存在 FAIL（可接 CI）；1 = 参数/IO 错误。

**已知边界**
  - 金融业（保险/银行）无「经营利润」口径 ⇒ `SBC/经营利润`、`经营利润率` 记 `—`，不参与判定
  - `正常化 PE` 依赖历史有效税率，若历史期存在亏损或负税则被跳过；样本不足时记 `—`
  - 数据源为 yfinance 年报（非时点），存在期别错配风险；判定从严，不确定一律记 `—`
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wb_analysis._log import log_gap

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    print("需要 yfinance")
    raise SystemExit(1)

# ── 判定阈值 ────────────────────────────────────────────────────────────
#   硬闸门（FAIL）—— 事实层面确定被扭曲
TAX_BENEFIT_FAIL = 0.20   # 一次性税收收益占净利的比例上限
PE_TOLERANCE = 1.2        # 正常化 PE 超过报表 PE 的倍数上限
#   软警告（WARN）—— 需要人工判断的价值取舍
MIN_OI_MARGIN = 0.15      # 经营利润率下限（重资产行业天然偏低，故不硬性拒绝）
SBC_OI_WARN = 1.0         # SBC / 经营利润 的警告线
MC_FCF_SBC_WARN = 60.0    # 市值/(FCF−SBC) 的警告线
TAX_LOOKBACK = 4          # 历史有效税率取最近几期
#   Q5 非经营收益闸门（2026-10-08 立，GOOG 事件）
#   阈值怎么定的（按铁律 10「设阈值先测三个数」实测，不是拍的）：
#     GOOG（权益证券浮盈）：TTM 非经营/净利 = 55.7%  ⇒ 必须拦下
#     META（同类但量级小）：TTM 口径 = 个位数 %
#     普通工业股/银行（无该科目或极小）：< 5%
#   取 25% 作硬闸门 —— 落在 GOOG(55.7%) 与正常公司(<10%) 之间，两侧都有余量。
GAIN_SECURITY_FAIL = 0.25  # 「证券处置/公允价值变动」占净利的比例上限
GAIN_SECURITY_WARN = 0.10  # 10%~25% 之间只警告，不阻断（可能是正常经营附带）


def _series(df, *names):
    """按候选行名取整行（保留全部期）。"""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        for idx in df.index:
            if str(idx).strip().lower() == n.lower():
                try:
                    return df.loc[idx].astype(float)
                except Exception as _gap_exc:  # noqa: BLE001
                    log_gap("_verify_earnings_quality._series", _gap_exc)
                    return None
    return None


def _at(s, i=0):
    if s is None or i >= len(s):
        return None
    v = s.iloc[i]
    return None if pd.isna(v) else float(v)


def _quarterly_unreliable(q, inc) -> bool:
    """季度序列是否与年报对账失败（⇒ 不可作为 TTM 合计的基础）。

    ★ 2026-10-15 立（SKHY 事件）：`yfinance` 对**外国私人发行人**可能返回
    **累计（YTD）/ 错标期间**的「季度」数据。实测 SKHY：

        季度列 2026-06-30  营收 79.319T   ← 单季
        年报   FY2025      营收 97.147T   ← 全年
        ⇒ 单季 / 全年 = **81.6%**，结构上不可能

    若据此合计 4 季，会算出「非经营/净利 **+30.0%**」的**假 FAIL**
    —— 而年报口径实为 **−19.8%**（方向相反，按「只挡抬高方向」规则本不该触发）。

    判据（按铁律 10「设阈值先测三个数」）：
      · 正常离散季度：单季约占全年 20%~35%（季节性极端可到 40%）；
      · 错标 / 累计数据：单季可达全年的 60%~100%；
      ⇒ 取 **0.5** 落在两者之间（正常侧留 1.25 倍余量，异常侧留 1.2 倍余量）。
    另加一条更宽的兜底：4 季合计 > **1.8 ×** 年报 ⇒ 亦判不可用。
    """
    try:
        qr = _series(q, "Total Revenue", "Operating Revenue")
        ar = _series(inc, "Total Revenue", "Operating Revenue")
        a0 = _at(ar, 0)
        if qr is None or not a0 or a0 <= 0:
            return False
        vals = [v for v in (_at(qr, i) for i in range(4)) if v is not None]
        if not vals:
            return False
        if max(vals) > 0.5 * a0:
            return True
        return sum(vals) > 1.8 * a0
    except Exception as _gap_exc:  # noqa: BLE001
        log_gap("_verify_earnings_quality._quarterly_unreliable", _gap_exc)
        return False


def analyze_one(ticker: str, pe_tolerance: float = PE_TOLERANCE) -> dict:
    """返回该标的的收益质量指标与判定。任何抓取失败都返回 ok=False，不抛异常。"""
    rec: dict = {"ticker": ticker, "note": ""}
    try:
        tk = yf.Ticker(ticker)
        inc, cf, info = tk.income_stmt, tk.cashflow, tk.info

        rev = _at(_series(inc, "Total Revenue", "Operating Revenue"))
        oi = _at(_series(inc, "Operating Income"))
        pre = _at(_series(inc, "Pretax Income", "Income Before Tax"))
        tax = _at(_series(inc, "Tax Provision", "Income Tax Expense"))
        ni = _at(_series(inc, "Net Income", "Net Income Common Stockholders"))
        sbc = _at(_series(cf, "Stock Based Compensation"))
        ocf = _at(_series(cf, "Operating Cash Flow", "Total Cash From Operating Activities"))
        capex = _at(_series(cf, "Capital Expenditure"))
        mc = info.get("marketCap")

        # ── Q5 非经营收益闸门：TTM 口径（年报会漏掉年内才爆发的浮盈）──────────
        #   为什么必须用 TTM：GOOG FY2025 年报的 Gain On Sale 只有 24.2B（占比 18%，
        #   够不着 25% 阈值），但 H1 2026 单半年就 135.9B —— 只看年报**完全看不见**。
        #   降级链：季报合计 → 年报 → None（记 "—" 不判定，绝不猜）。
        gain_ttm = gain_ni_share = gain_src = None
        rec_ni_ttm = None
        try:
            q = tk.quarterly_income_stmt
            # ★ 2026-10-15：季度序列必须先与年报对账；不一致即整段降级到 FY 口径。
            #   否则外国发行人的累计/错标数据会造出假 FAIL（见 `_quarterly_unreliable`）。
            if _quarterly_unreliable(q, inc):
                raise ValueError("quarterly series unreconciled with annual revenue")
            gq = _series(q, "Total Unusual Items", "Gain On Sale Of Security",
                         "Gain On Sale Of Business", "Gain On Sale Of Security 1",
                         "Special Income Charges")
            nq = _series(q, "Net Income", "Net Income Common Stockholders")
            if gq is not None and nq is not None:
                g4 = [_at(gq, i) for i in range(4)]
                n4 = [_at(nq, i) for i in range(4)]
                g4 = [v for v in g4 if v is not None]
                n4 = [v for v in n4 if v is not None]
                if len(g4) >= 3 and len(n4) >= 3:
                    gain_ttm, ni_ttm_q = sum(g4), sum(n4)
                    if ni_ttm_q > 0:
                        gain_ni_share = gain_ttm / ni_ttm_q
                        gain_src = f"TTM({len(n4)}Q)"
                        rec_ni_ttm = ni_ttm_q   # 供 pe_ex_gain 用，与 gain 同口径
        except Exception as _gap_exc:  # noqa: BLE001
            log_gap("_verify_earnings_quality.analyze_one", _gap_exc)
            pass
        if gain_ttm is None:
            # 降级到年报（不聚合季度时至少能拦住常年性的浮盈）
            g_a = _at(_series(inc, "Total Unusual Items", "Gain On Sale Of Security",
                              "Gain On Sale Of Business", "Special Income Charges"))
            if g_a is not None and ni and ni > 0:
                gain_ttm, gain_ni_share, gain_src = g_a, g_a / ni, "FY"

        # 历史有效税率（跳过非正税前利润的期）
        pre_all, tax_all = _series(inc, "Pretax Income", "Income Before Tax"), _series(inc, "Tax Provision", "Income Tax Expense")
        etrs = []
        if pre_all is not None and tax_all is not None:
            for i in range(min(TAX_LOOKBACK, len(pre_all))):
                p, x = _at(pre_all, i), _at(tax_all, i)
                if p and p > 0 and x is not None:
                    etrs.append(x / p)
        med_etr = sorted(etrs)[len(etrs) // 2] if etrs else None

        fcf = (ocf + capex) if (ocf is not None and capex is not None) else None
        norm_ni = pre * (1 - med_etr) if (pre and med_etr is not None) else None

        rec.update(
            mc=mc, rev=rev, oi=oi, pre=pre, tax=tax, ni=ni, sbc=sbc, ocf=ocf, fcf=fcf,
            etr=(tax / pre if (pre and tax is not None) else None),
            med_etr=med_etr,
            oi_margin=(oi / rev if (oi and rev) else None),
            ni_margin=(ni / rev if (ni and rev) else None),
            sbc_oi=(sbc / oi if (sbc and oi and oi > 0) else None),
            pe_rep=(mc / ni if (mc and ni and ni > 0) else None),
            # ★★ 2026-10-12 新增（GOOG 轮实测）：**TTM 口径**的报表 PE。
            #   起因：下面的 `pe_ex_gain` 用的是 **TTM 净利**（`rec_ni_ttm`），
            #   而 `pe_rep` 用的是 **FY 净利** ⇒ 二者并排展示时**口径不同**，
            #   读者会把「报表PE 32.2x → 剥离浮盈后 44.6x」当成同一口径下的对比，
            #   而真实同口径对比是「PE(TTM) 17.4x → 44.6x」。
            #   这个口径错配恰好让本工具的输出与铁律 40 记录的
            #   「17.29x → 44.09x」对不上 —— 工具与人记的两个数不一致，根因在此。
            #   ⇒ `pe_rep` 继续保留 FY 口径（Q4 正常化一致性闸门的对照物 `pe_norm`
            #     也是 FY 口径，两者**必须同口径**才能比），
            #     另立 `pe_ttm` 专供「剥离浮盈」一侧做同口径比较。
            pe_ttm=(mc / rec_ni_ttm if (mc and rec_ni_ttm and rec_ni_ttm > 0) else None),
            pe_norm=(mc / norm_ni if (mc and norm_ni and norm_ni > 0) else None),
            mc_fcf_sbc=(mc / (fcf - sbc) if (mc and fcf and sbc is not None and (fcf - sbc) > 0) else None),
            gain_ttm=gain_ttm,
            gain_ni_share=gain_ni_share,
            gain_src=gain_src,
            # 经营性 PE：剥离「证券处置/公允价值变动」后的净利做分母。
            #   ★ 分子分母必须**同口径**：gain 来自 TTM 时，ni 也必须用 TTM，
            #     否则会拿 FY 净利减 TTM 浮盈 ⇒ 分母变负 ⇒ 指标报废（首版实测踩过）。
            #   与 mc_fcf_sbc 一样是**顾问性**指标 —— 回答「不靠浮盈的话，这价贵不贵」。
            pe_ex_gain=(mc / ((rec_ni_ttm or ni) - gain_ttm)
                        if (mc and gain_ttm is not None
                            and ((rec_ni_ttm or ni) is not None)
                            and ((rec_ni_ttm or ni) - gain_ttm) > 0) else None),
        )
    except Exception as e:  # noqa: BLE001
        log_gap("_verify_earnings_quality.analyze_one", e)
        rec["ok"] = False
        rec["note"] = f"抓取失败: {type(e).__name__}"
        return rec

    # ── 判定：硬闸门（FAIL，可接 CI）与软警告（WARN，人工过目）分开 ──────
    #   硬闸门只放「事实层面确定被扭曲」的项；阈值的价值判断留给软警告，
    #   否则工具会因误报过多而被无视。
    fails, warns = [], []

    # 硬 1：负税的**实质贡献**（不是「税率是否 < 0」——−0.1% 是噪声）
    tax, ni = rec.get("tax"), rec.get("ni")
    tax_share = None
    if tax is not None and tax < 0 and ni and ni > 0:
        tax_share = (-tax) / ni
        if tax_share >= TAX_BENEFIT_FAIL:
            fails.append(f"一次性税收收益占净利 {tax_share*100:.0f}%")
    # 硬 2：亏损（不符合「盈利且低估」的前提）
    if ni is not None and ni <= 0:
        fails.append("净利为负")
    # 硬 3：正常化 PE 显著高于报表 PE（只挡「报表被高估」方向）
    pe_rep, pe_norm = rec.get("pe_rep"), rec.get("pe_norm")
    if pe_rep and pe_norm and pe_norm > pe_rep * pe_tolerance:
        fails.append(f"正常化PE偏离 {pe_rep:.1f}x→{pe_norm:.1f}x")

    # 硬 4：非经营/非常规收益（证券处置/业务出售/重组等）占净利过高 —— Q5 闸门
    #   与硬 1~3 单向一致：只挡「报表被**抬高**」方向（gain 为正才算）。
    #   若 gain 为负（浮亏拖低净利），报表 PE 是**偏高**的，不属本闸门管辖。
    g_share, g_ttm, g_src = rec.get("gain_ni_share"), rec.get("gain_ttm"), rec.get("gain_src")
    if g_share is not None and g_ttm is not None and g_ttm > 0:
        if g_share >= GAIN_SECURITY_FAIL:
            fails.append(f"非经营/非常规收益占净利 {g_share*100:.0f}%（{g_src}）")
        elif g_share >= GAIN_SECURITY_WARN:
            rec.setdefault("_soft_gain", True)

    # 软警告：不阻断，但需人工判断
    oim = rec.get("oi_margin")
    if oim is not None and oim < MIN_OI_MARGIN:
        warns.append(f"经营利润率 {oim*100:.1f}%")
    soi = rec.get("sbc_oi")
    if soi is not None and soi >= SBC_OI_WARN:
        warns.append(f"SBC/经营利润 {soi*100:.0f}%")
    mfs = rec.get("mc_fcf_sbc")
    if mfs is not None and mfs > MC_FCF_SBC_WARN:
        warns.append(f"市值/(FCF−SBC) {mfs:.0f}x")
    if rec.pop("_soft_gain", False):
        warns.append(f"非经营/非常规收益占净利 {g_share*100:.0f}%（{g_src}，未达 {GAIN_SECURITY_FAIL*100:.0f}% 硬线）")

    rec["tax_share"] = tax_share
    rec["reasons"] = fails
    rec["warns"] = warns
    rec["ok"] = not fails
    return rec


def _fmt(v, pct=False, suf="x", nd=1):
    if v is None:
        return "—"
    return f"{v*100:+.{nd}f}%" if pct else f"{v:.{nd}f}{suf}"


#: PE / 市值倍数的**合理区间**。落在区间外**不是**「特别便宜/特别贵」，
#: 而是「**分子分母口径不一致**」的量化标记（铁律 11 的同型：
#: 坏值不越界，而是在逻辑上不成立）。
#:
#: ★ 2026-10-12 立（SKHY 实测）：`mc` 取自 `yfinance.info`（**美元**），
#: 而 `ni`/`rev` 取自报表（**韩元**）⇒ `mc/ni = 0.0074`，
#: 而旧版把它格式化成 **`0.0x`** —— 一个**看起来像真倍数的假数**，
#: 比报 `—` 危险得多（铁律 3「静默失败」：外观正常 + 数值不可用）。
#: ⇒ 落在区间外一律显示 `⚠口径异常`，并置 `pe_caliber_warn` 供下游识别。
PE_SANE: tuple[float, float] = (1.0, 1000.0)


def _fmt_pe(v) -> str:
    """PE 类倍数的显示：**区间外不显示数字**，显示口径异常的标记。"""
    if v is None:
        return "—"
    if not (PE_SANE[0] <= v <= PE_SANE[1]):
        return "⚠口径异常"
    return f"{v:.1f}x"


def _pe_bad(*vals) -> bool:
    """是否**任一** PE 类读数落在合理区间外（⇒ 分子分母口径不一致）。"""
    return any(v is not None and not (PE_SANE[0] <= v <= PE_SANE[1]) for v in vals)


def main() -> int:
    ap = argparse.ArgumentParser(description="收益质量验证器（负税 / 正常化偏离）")
    ap.add_argument("--from-radar", help="雷达 CSV 路径；配合 --top 取前 N 只")
    ap.add_argument("--top", type=int, default=None, help="按综合量化分取前 N 只")
    ap.add_argument("--tickers", help="逗号分隔的代码列表（与 --from-radar 二选一）")
    ap.add_argument("--pe-tolerance", type=float, default=PE_TOLERANCE,
                    help=f"正常化PE/报表PE 的容忍上限（默认 {PE_TOLERANCE}）")
    ap.add_argument("--exit-on-fail", action="store_true", help="存在 FAIL 时退出码 2（CI 用）")
    # ★ 2026-10-12 新增：把判定落成**状态副档** `evidence/<T>_<date>.earnings.json`，
    #   供 `_gap_ledger.py` 消费。起因与 edgar_raw 完全同族：
    #   Q5 是**手工触发**的一步，它的结论此前只存在于终端输出里 ——
    #   简报作者忘了写、门禁就永远抓不到，属于「检测器看着在工作、其实什么也没检」。
    #   给了 `--as-of` 才落盘（不传则行为不变，向后兼容）。
    ap.add_argument("--as-of", default=None, metavar="YYYY-MM-DD",
                    help="基准日；给了它就把每只的判定落成 evidence/<T>_<date>.earnings.json")
    args = ap.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.from_radar:
        p = Path(args.from_radar)
        if not p.exists():
            print(f"[错误] 找不到 {p}")
            return 1
        df = pd.read_csv(p)
        if "综合量化分" in df.columns:
            df = df.sort_values("综合量化分", ascending=False)
        tickers = df["Ticker"].dropna().astype(str).tolist()
        if args.top:
            tickers = tickers[: args.top]
    else:
        print("[错误] 需指定 --from-radar 或 --tickers")
        return 1

    print(f"[收益质量验证] {len(tickers)} 只 | 负税闸门 + 正常化一致性闸门 + 非经营收益闸门"
          f"（容忍 {PE_TOLERANCE}x，非经营硬线 {GAIN_SECURITY_FAIL*100:.0f}%）"
          f"| 经营利润率下限 {MIN_OI_MARGIN*100:.0f}%")
    print("=" * 122)

    recs = []
    for i, t in enumerate(tickers, 1):
        r = analyze_one(t, args.pe_tolerance)
        recs.append(r)
        if i % 20 == 0 or i == len(tickers):
            print(f"  ...已分析 {i}/{len(tickers)}", file=sys.stderr)

    # ⚠️ 两列 PE 口径不同、**不可互相比较**（2026-10-12 加标注）：
    #    `报表PE(FY)` 用年报净利（与 `正常化PE` 同口径，供 Q4 闸门比对）；
    #    `PE(TTM)` 用滚动四季净利（与「非经营/净利」同一口径）。
    hdr = (f"{'代码':7s}{'有效税率':>11s}{'税收/净利':>10s}{'非经营/净利':>12s}{'报表PE(FY)':>12s}"
           f"{'PE(TTM)':>10s}{'经营性PE':>10s}{'经营利润率':>11s}{'SBC/经营利润':>12s}{'市值/(FCF-SBC)':>15s}  判定")
    print()
    print(hdr)
    print("-" * 140)
    fails, warns = [], []
    for r in recs:
        if "reasons" not in r:
            print(f"{r['ticker']:7s} {r.get('note','')}")
            continue
        if r["reasons"]:
            fails.append(r)
        elif r["warns"]:
            warns.append(r)
        verdict = "FAIL: " + " / ".join(r["reasons"]) if r["reasons"] else (
            "WARN: " + " / ".join(r["warns"]) if r["warns"] else "通过")
        caliber_bad = _pe_bad(r.get("pe_rep"), r.get("pe_ttm"), r.get("pe_ex_gain"),
                              r.get("mc_fcf_sbc"))
        verdict2 = verdict + ("  ⚠ **PE 类读数口径异常**（市值与报表不同币种？）"
                              if caliber_bad and "PE" not in verdict else "")
        print(f"{r['ticker']:7s}{_fmt(r.get('etr'), True):>11s}{_fmt(r.get('tax_share'), True):>10s}"
              f"{_fmt(r.get('gain_ni_share'), True):>12s}{_fmt_pe(r.get('pe_rep')):>12s}"
              f"{_fmt_pe(r.get('pe_ttm')):>12s}"
              f"{_fmt_pe(r.get('pe_ex_gain')):>12s}{_fmt(r.get('oi_margin'), True):>11s}"
              f"{_fmt(r.get('sbc_oi'), True):>12s}{_fmt_pe(r.get('mc_fcf_sbc')):>15s}  {verdict2}")

    print("-" * 132)
    print(f"\n通过 {len(recs) - len(fails) - len(warns)} 只 | 仅警告 {len(warns)} 只 | "
          f"FAIL {len(fails)} 只（共分析 {len(recs)} 只）")
    if fails:
        print("\n=== FAIL 清单（硬闸门：必须剔除或改用经营性口径）===")
        for r in fails:
            extra = ""
            bad = _pe_bad(r.get("pe_rep"), r.get("pe_ttm"), r.get("pe_ex_gain"),
                          r.get("mc_fcf_sbc"))
            if bad:
                # ★ 口径异常时**不打印任何倍数** —— 打印出来的数字再"准确"也是无意义的，
                #   而读者会把它当成真实倍数（本轮 SKHY 实测：旧版印 `0.0x`）。
                extra = ("   ⚠ **PE 类倍数不可用**：市值（来自 info，美元）与报表（韩元）"
                         "**不同币种** ⇒ 分子分母口径不一致，一律**不得引用**。")
            else:
                if r.get("pe_rep") and r.get("pe_norm") and r.get("pe_norm") > r["pe_rep"]:
                    extra = (f"   报表PE(FY) {_fmt_pe(r['pe_rep'])}"
                             f" → 正常化 {_fmt_pe(r['pe_norm'])}（同口径）")
                if r.get("pe_ex_gain") and r.get("pe_ttm"):
                    extra += (f"   剥离浮盈后 PE {_fmt_pe(r['pe_ex_gain'])}"
                              f"（PE(TTM) {_fmt_pe(r['pe_ttm'])} → 同口径）")
            print(f"  {r['ticker']:7s} {' / '.join(r['reasons'])}{extra}")
    if warns:
        print("\n=== 仅警告清单（软指标，需人工判断；不阻断）===")
        for r in warns:
            print(f"  {r['ticker']:7s} {' / '.join(r['warns'])}")
    print("\n★ 提醒：本验证器只挡「报表净利被一次性/非经营项目抬高」"
          "（负税、异常税率、证券公允价值变动）。"
          "通过 ≠ 值得买，只表示**报表 PE 是一个可信的输入**。")

    # ── 落状态副档（供 _gap_ledger 消费）────────────────────────────────
    if args.as_of:
        ev = ROOT / "wb_analysis" / "evidence"
        if ev.exists():
            for r in recs:
                if "reasons" not in r:
                    continue
                status = "FAIL" if r["reasons"] else ("WARN" if r["warns"] else "OK")
                out = ev / f"{r['ticker']}_{args.as_of}.earnings.json"
                out.write_text(json.dumps({
                    "ticker": r["ticker"], "as_of": args.as_of, "status": status,
                    "reasons": r.get("reasons", []), "warns": r.get("warns", []),
                    "gain_ni_share": r.get("gain_ni_share"),
                    "gain_src": r.get("gain_src"),
                    "pe_rep_fy": r.get("pe_rep"), "pe_ttm": r.get("pe_ttm"),
                    "pe_ex_gain": r.get("pe_ex_gain"), "pe_norm": r.get("pe_norm"),
                    # ★ PE 类读数是否落在合理区间外（⇒ 分子分母口径不一致，一律不得引用）
                    "pe_caliber_warn": _pe_bad(r.get("pe_rep"), r.get("pe_ttm"),
                                               r.get("pe_ex_gain"), r.get("mc_fcf_sbc")),
                    "oi_margin": r.get("oi_margin"), "sbc_oi": r.get("sbc_oi"),
                    "mc_fcf_sbc": r.get("mc_fcf_sbc"),
                    "detail": (("收益质量闸门 FAIL：" + " / ".join(r["reasons"]))
                               if r["reasons"] else
                               ("收益质量闸门 WARN：" + " / ".join(r["warns"]))
                               if r["warns"] else "收益质量闸门通过")
                              + ("；⚠ **但 PE 类倍数一律不可用**：市值与报表**不同币种**"
                                 " ⇒ 本项的标准代理口径（经营性 PE）**在本标的上不成立**，"
                                 "只能改用「非经营收益占净利的比例」这一无量纲读数。"
                                 if _pe_bad(r.get("pe_rep"), r.get("pe_ttm"),
                                            r.get("pe_ex_gain"), r.get("mc_fcf_sbc")) else ""),
                }, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
                print(f"[earnings] 状态副档 -> {out.relative_to(ROOT).as_posix()}（status={status}）")
    return 2 if (fails and args.exit_on_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
