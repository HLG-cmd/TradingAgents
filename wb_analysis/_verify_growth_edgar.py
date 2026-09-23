# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_growth_edgar.py
"""用 SEC EDGAR 的**多年营收 CAGR** 复核量化榜单的「成长」维度。

为什么需要
----------
``screener_engine`` 的成长分来自 ``yf.Ticker().info["revenueGrowth"]``，那是
**单季总营收同比** —— 两个致命问题：

1. **并购并表会台阶式跳升**：COF 实测单季同比 **+1111%**，而 EDGAR 年度口径只有 **+36.3%**。
2. **周期股的一次性反弹被当成成长**：SM 单期 +17.5%，但 **3 年 CAGR 是 −2.1%**；
   DVN 单期 +5.4%，3 年 CAGR **−5.4%** —— 都在收缩。

EDGAR 有**带申报日的多年历史**（时点键），可以算真正的多年几何平均增长。

用法
----
    # 复核「宽双条件 + 过质检护栏」的候选（默认）
    ./.venv/Scripts/python.exe wb_analysis/_verify_growth_edgar.py \
        --from-radar reports/radar_sp1500_2026-09-20.csv

    # 只复核指定的标的
    ./.venv/Scripts/python.exe wb_analysis/_verify_growth_edgar.py --tickers FIS,INCY,EOG

产物
----
    reports/growth_verify_edgar_<YYYY-MM-DD>.csv

⚠️ 速率：EDGAR 限速 ~10 req/s，本模块每次请求间隔 0.15s，实测 **2.7~3.0s/家**。
   130 家约 6 分钟 —— 放后台跑。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import datetime as dt  # noqa: E402

import pandas as pd  # noqa: E402

from quant.edgar_fundamentals import get_point_in_time

# 判定门槛（年化）
STRONG = 0.08      # 3 年 CAGR >= 8% ⇒ 成长被证实
WEAK = 0.03        # <= 3% ⇒ 成长未被证实


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def select_candidates(radar: pd.DataFrame, g: float, v: float, q: float,
                      exclude_guards: bool, limit: int | None) -> list[str]:
    m = ~radar["pe_missing"].astype(str).str.lower().isin(["true", "1", "1.0"])
    d = radar[m].copy()
    sel = d[(d.growth_score.astype(float) >= g)
            & (d.val_score.astype(float) >= v)
            & (d.quality_score.astype(float) >= q)]
    if exclude_guards:
        keep = []
        for _, r in sel.iterrows():
            pe, roe = _f(r.get("pe")), _f(r.get("roe"))
            margin, rg = _f(r.get("margin")), _f(r.get("rev_growth"))
            pb = (pe * roe) if (pe and roe) else None
            if pb is not None and pb > 10:
                continue
            if roe and margin is not None and roe > 0 and (margin / roe) < 0.5:
                continue
            if rg is not None and rg > 1.0:
                continue
            keep.append(r["Ticker"])
        sel = sel[sel["Ticker"].isin(keep)]
    tickers = list(dict.fromkeys(sel["Ticker"].astype(str)))
    return tickers[:limit] if limit else tickers


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-radar", default="reports/radar_sp1500_2026-09-20.csv")
    ap.add_argument("--tickers", default=None, help="逗号分隔；给了就忽略 --from-radar")
    ap.add_argument("--growth-min", type=float, default=60.0)
    ap.add_argument("--value-min", type=float, default=60.0)
    ap.add_argument("--quality-min", type=float, default=50.0)
    ap.add_argument("--no-guards", action="store_true", help="不要排除质检护栏命中的标的")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--as-of", default=None, help="默认用雷达 CSV 的基准日")
    args = ap.parse_args()

    yf_growth: dict[str, float] = {}
    as_of = args.as_of or dt.date.today().isoformat()
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        radar = pd.read_csv(ROOT / args.from_radar, encoding="utf-8-sig")
        tickers = select_candidates(radar, args.growth_min, args.value_min,
                                    args.quality_min, not args.no_guards, args.limit)
        for _, r in radar.iterrows():
            g = _f(r.get("rev_growth"))
            if g is not None:
                yf_growth[str(r["Ticker"])] = g
    print(f"[verify] 待复核 {len(tickers)} 只，as_of={as_of}")
    print(f"[verify] 速率约 2.8s/家 ⇒ 预计 {len(tickers) * 2.8 / 60:.1f} 分钟\n")

    rows = []
    for i, tk in enumerate(tickers, 1):
        try:
            r = get_point_in_time(tk, as_of)
            rows.append({
                "Ticker": tk,
                "yf_单季同比%": None if tk not in yf_growth else round(yf_growth[tk] * 100, 1),
                "edgar_年度同比%": None if r["revenue_growth"] is None else round(r["revenue_growth"] * 100, 1),
                "edgar_3yCAGR%": None if r["revenue_cagr_3y"] is None else round(r["revenue_cagr_3y"] * 100, 1),
                "edgar_5yCAGR%": None if r["revenue_cagr_5y"] is None else round(r["revenue_cagr_5y"] * 100, 1),
                "年数": r["revenue_cagr_3y_levels"],
                "营收TTM(十亿)": None if not r["revenue_ttm"] else round(r["revenue_ttm"] / 1e9, 1),
                "净利率%": None if r["margin"] is None else round(r["margin"] * 100, 1),
                "tag": r["revenue_tag"],
                "口径不可用": bool(r.get("revenue_tag_implausible")),
            })
            print(f"  [{i}/{len(tickers)}] {tk:<6} 3yCAGR="
                  f"{rows[-1]['edgar_3yCAGR%'] if rows[-1]['edgar_3yCAGR%'] is not None else 'n/a'}")
        except Exception as exc:  # noqa: BLE001
            rows.append({"Ticker": tk, "yf_单季同比%": None, "edgar_年度同比%": None,
                         "edgar_3yCAGR%": None, "edgar_5yCAGR%": None, "年数": 0,
                         "营收TTM(十亿)": None, "净利率%": None,
                         "tag": f"ERR {type(exc).__name__}"})
            print(f"  [{i}/{len(tickers)}] {tk:<6} ✗ {type(exc).__name__}")

    df = pd.DataFrame(rows)
    out_dir = ROOT / "reports" / "_datasets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"growth_verify_edgar_{dt.date.today().isoformat()}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\r\n")
    print(f"\n[verify] 已导出 {out.name}")

    # ── 三分类裁定 ────────────────────────────────────────────────────
    def verdict(row):
        # 营收与净利不相容（银行取到合同收入窄口径）⇒ 增速不可采信，先于一切判定
        if row.get("口径不可用"):
            return "D 口径不可用（净利 > 营收）"
        c = row["edgar_3yCAGR%"]
        if c is None:
            return "D 无法判定（年度序列不足）"
        if c >= STRONG * 100:
            return "A 成长被证实"
        if c <= WEAK * 100:
            return "C 成长未获证实"
        return "B 弱增长"
    df["裁定"] = df.apply(verdict, axis=1)

    print("\n=== 裁定分布 ===")
    for k, n in df["裁定"].value_counts().sort_index().items():
        print(f"  {k:<28}{n:>4} 只  {n / len(df) * 100:>5.0f}%")

    implausible = df[df["裁定"].str.startswith("D")]
    if not implausible.empty:
        print(f"\n=== D 类：营收口径不可用（净利率 > 100%，增速不可采信）: {len(implausible)} 只 ===")
        print("  " + ", ".join(f"{r['Ticker']}({r['净利率%']:.0f}%, {str(r['tag'])[:34]})"
                               for _, r in implausible.iterrows()))

    ok = df[df["裁定"].str.startswith("A")]
    if not ok.empty:
        print(f"\n=== A 类：成长被 EDGAR 证实（3y CAGR >= {STRONG*100:.0f}%）: {len(ok)} 只 ===")
        print(f"{'代码':<7}{'yf单季%':>9}{'edgar年度%':>11}{'3yCAGR%':>9}{'5yCAGR%':>9}{'净利率%':>9}")
        for _, r in ok.sort_values("edgar_3yCAGR%", ascending=False).iterrows():
            c = lambda k, w=9: f"{'n/a':>{w}}" if pd.isna(r[k]) else f"{r[k]:>{w}.1f}"
            print(f"{r['Ticker']:<7}{c('yf_单季同比%')}{c('edgar_年度同比%',11)}"
                  f"{c('edgar_3yCAGR%')}{c('edgar_5yCAGR%')}{c('净利率%')}")

    # ── 背离清单：yf 单季 vs EDGAR 3 年 ──────────────────────────────
    d = df.dropna(subset=["yf_单季同比%", "edgar_3yCAGR%"]).copy()
    d["背离pp"] = d["yf_单季同比%"] - d["edgar_3yCAGR%"]
    big = d[d["背离pp"] >= 20].sort_values("背离pp", ascending=False)
    print(f"\n=== yf 单季比 EDGAR 3 年 CAGR 高 20pp 以上（成长被高估）: {len(big)} 只 ===")
    for _, r in big.head(15).iterrows():
        print(f"  {r['Ticker']:<7} yf {r['yf_单季同比%']:>8.1f}%   edgar 3y {r['edgar_3yCAGR%']:>7.1f}%"
              f"   差 {r['背离pp']:>7.1f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
