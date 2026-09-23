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

**判据（两闸门，都是单向的）**
  Q3 负税闸门      ：`Tax Provision < 0` 且 |税项| 与税前利润同量级 ⇒ FAIL
  Q4 正常化一致性  ：`正常化PE > tolerance x 报表PE` ⇒ FAIL（只挡「报表被高估」方向）
正常化净利 = 税前利润 x (1 − 历史有效税率中位数)，中位取最近 N 个正税期。

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
import sys
from pathlib import Path

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


def _series(df, *names):
    """按候选行名取整行（保留全部期）。"""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        for idx in df.index:
            if str(idx).strip().lower() == n.lower():
                try:
                    return df.loc[idx].astype(float)
                except Exception:
                    return None
    return None


def _at(s, i=0):
    if s is None or i >= len(s):
        return None
    v = s.iloc[i]
    return None if pd.isna(v) else float(v)


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
            pe_norm=(mc / norm_ni if (mc and norm_ni and norm_ni > 0) else None),
            mc_fcf_sbc=(mc / (fcf - sbc) if (mc and fcf and sbc is not None and (fcf - sbc) > 0) else None),
        )
    except Exception as e:
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

    rec["tax_share"] = tax_share
    rec["reasons"] = fails
    rec["warns"] = warns
    rec["ok"] = not fails
    return rec


def _fmt(v, pct=False, suf="x", nd=1):
    if v is None:
        return "—"
    return f"{v*100:+.{nd}f}%" if pct else f"{v:.{nd}f}{suf}"


def main() -> int:
    ap = argparse.ArgumentParser(description="收益质量验证器（负税 / 正常化偏离）")
    ap.add_argument("--from-radar", help="雷达 CSV 路径；配合 --top 取前 N 只")
    ap.add_argument("--top", type=int, default=None, help="按综合量化分取前 N 只")
    ap.add_argument("--tickers", help="逗号分隔的代码列表（与 --from-radar 二选一）")
    ap.add_argument("--pe-tolerance", type=float, default=PE_TOLERANCE,
                    help=f"正常化PE/报表PE 的容忍上限（默认 {PE_TOLERANCE}）")
    ap.add_argument("--exit-on-fail", action="store_true", help="存在 FAIL 时退出码 2（CI 用）")
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

    print(f"[收益质量验证] {len(tickers)} 只 | 负税闸门 + 正常化一致性闸门"
          f"（容忍 {PE_TOLERANCE}x）| 经营利润率下限 {MIN_OI_MARGIN*100:.0f}%")
    print("=" * 122)

    recs = []
    for i, t in enumerate(tickers, 1):
        r = analyze_one(t, args.pe_tolerance)
        recs.append(r)
        if i % 20 == 0 or i == len(tickers):
            print(f"  ...已分析 {i}/{len(tickers)}", file=sys.stderr)

    hdr = (f"{'代码':7s}{'有效税率':>11s}{'税收/净利':>10s}{'正常化PE':>10s}{'报表PE':>9s}"
           f"{'经营利润率':>11s}{'SBC/经营利润':>12s}{'市值/(FCF-SBC)':>15s}  判定")
    print()
    print(hdr)
    print("-" * 122)
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
        print(f"{r['ticker']:7s}{_fmt(r.get('etr'), True):>11s}{_fmt(r.get('tax_share'), True):>10s}"
              f"{_fmt(r.get('pe_norm')):>10s}{_fmt(r.get('pe_rep')):>9s}{_fmt(r.get('oi_margin'), True):>11s}"
              f"{_fmt(r.get('sbc_oi'), True):>12s}{_fmt(r.get('mc_fcf_sbc')):>15s}  {verdict}")

    print("-" * 122)
    print(f"\n通过 {len(recs) - len(fails) - len(warns)} 只 | 仅警告 {len(warns)} 只 | "
          f"FAIL {len(fails)} 只（共分析 {len(recs)} 只）")
    if fails:
        print("\n=== FAIL 清单（硬闸门：必须剔除或改用正常化口径）===")
        for r in fails:
            extra = ""
            if r.get("pe_rep") and r.get("pe_norm"):
                extra = f"   报表PE {r['pe_rep']:.1f}x → 正常化 {r['pe_norm']:.1f}x"
            print(f"  {r['ticker']:7s} {' / '.join(r['reasons'])}{extra}")
    if warns:
        print("\n=== 仅警告清单（软指标，需人工判断；不阻断）===")
        for r in warns:
            print(f"  {r['ticker']:7s} {' / '.join(r['warns'])}")
    print("\n★ 提醒：本验证器只挡「报表净利被一次性项目抬高」。"
          "通过 ≠ 值得买，只表示**报表 PE 是一个可信的输入**。")
    return 2 if (fails and args.exit_on_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
