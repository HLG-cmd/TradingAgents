# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_screen_pool.py
"""任意股票池的四维量化筛选 + 「高成长 x 低估值」交叉筛选。

为什么需要这个脚本
------------------
CLI 的 ``--pool sp500`` 取的是 **硬编码的 ``SP_500_CORE``（99 只人工精选子集）**，
而 ``stock_pools`` 实际能给出 **503（标普500全量）** 乃至 **1506（标普1500）**。
两者相差极大，但导出文件名都叫 ``radar_sp500_*``，极易误读。本脚本绕开 CLI，
直接指定真实宇宙。

标的池
------
    nasdaq  -> get_latest_nasdaq_100()   101 只（大盘科技为主）
    sp500   -> get_latest_sp500()        503 只（大盘）
    sp1500  -> get_latest_sp1500()      1506 只（大 + 中 + 小盘）
    custom  -> 配合 --tickers "A,B,C"

用法
----
    ./.venv/Scripts/python.exe wb_analysis/_screen_pool.py --pool sp1500
    ./.venv/Scripts/python.exe wb_analysis/_screen_pool.py --from-csv reports/radar_sp1500_x.csv

``--from-csv`` 用于**只改显示/门槛、不想重抓数据**的场景（重抓要几分钟到几十分钟）。

产物
----
    reports/radar_<pool>_<YYYY-MM-DD>.csv   全部标的 + 全部单因子得分（utf-8-sig）

⚠️ 两个坑（都踩过）
------------------
1. **显示列要自己换算。** ``run_quant_screening`` 的 ``roe`` / ``margin`` /
   ``rev_growth`` 是**小数**（``0.22507`` = 22.5%）。``ROE%`` 这类显示列是
   ``smart_screener.py`` 的展示层加的，**直接调引擎拿不到** —— 照抄会得到一列 0.0。
2. **本引擎的打分是截面百分位** ⇒ **换宇宙会改变每一个分数**。

⚠️ 结论口径（必须随榜单一并声明）
---------------------------------
``reports/fundamental_backtest_20260916.csv``（**跑在纳指100 池上**）实测：
17 个不重叠年度观测、2009-2025、行业中性化后，value IC 均值 -0.0499、
growth **-0.0013**、quality -0.0438、composite -0.0456。
=> 本榜单**未被证明有选股能力**，只应作为「压缩研究范围」的漏斗。
且该回测**不能直接挪用到标普1500**（截面百分位换宇宙后会变）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


import pandas as pd  # noqa: E402

from quant.screener_engine import export_radar_csv, run_quant_screening
from quant.stock_pools import get_latest_nasdaq_100, get_latest_sp500, get_latest_sp1500
from wb_analysis import _clock

# ── 交叉筛选门槛（均为 0~100 的截面百分位得分）────────────────────────────
TIERS = [
    ("A 强双条件", 75.0, 75.0, 50.0),
    ("B 宽双条件", 60.0, 60.0, 50.0),
]


def _num(value, default=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return default if v != v else v          # 过滤 NaN


def _row_num(row, key, default=None):
    return _num(row.get(key), default)


def _pct(row, key):
    """原始列是小数（0.22507），显示要转成百分数。"""
    v = _row_num(row, key)
    return None if v is None else v * 100.0


def resolve_pool(name: str) -> tuple[list[str], str]:
    if name == "nasdaq":
        return get_latest_nasdaq_100(), "nasdaq100"
    if name == "sp500":
        return get_latest_sp500(), "sp500"
    if name == "sp1500":
        return get_latest_sp1500(), "sp1500"
    raise SystemExit(f"未知池 {name}")


def analyze(full: pd.DataFrame, label: str, source: str) -> None:
    print(f"[screen] 宇宙 = {label}，{len(full)} 只  (来源: {source})")

    # ── 数据质量闸门：短历史 / 畸形 PE ──────────────────────────────────
    warn = []
    for _, r in full.iterrows():
        tk = r.get("Ticker")
        bars = _row_num(r, "bars", 0)
        pe = _row_num(r, "pe")
        if bars is not None and bars < 300:
            warn.append(f"{tk}: 历史仅 {int(bars)} 根 K 线（<300）→ 均线类指标为伪值")
        if pe is not None and 0 < pe < 3:
            warn.append(f"{tk}: PE={pe:.2f} 过低，需人工核验是否为坏值")
    print(f"[screen] 数据质量告警 {len(warn)} 条")
    for w in warn[:15]:
        print(f"          {w}")

    # ── 交叉筛选 ────────────────────────────────────────────────────────
    pe_missing = full["pe_missing"].astype(str).str.lower().isin(["true", "1", "1.0"])
    elig = full[~pe_missing].copy()
    print(f"\n[screen] 盈利且 PE 可得：{len(elig)} 只（剔除亏损/缺 PE {len(full) - len(elig)} 只）")

    # ── 质检护栏：三类「数值自洽但经济含义失真」的标的 ──────────────────
    #   PB 由恒等式反推：P/B = (P/E) x (E/B) = PE x ROE（WDC 实测 21.47 vs 实际 21.10）
    #   引擎只用 PE、不含 PB，所以「21 倍市净 + 16 倍市盈」会被判成便宜。
    flags: dict[str, list[str]] = {}
    for _, r in elig.iterrows():
        tk = r.get("Ticker")
        pe = _row_num(r, "pe")
        roe = _row_num(r, "roe")
        margin = _row_num(r, "margin")
        rg = _row_num(r, "rev_growth")
        why = []
        pb = pe * roe if (pe and roe) else None
        if pb is not None and pb > 10:
            why.append(f"PB≈{pb:.0f}（低 PE 但极贵账面）")
        if roe and margin is not None and roe > 0 and (margin / roe) < 0.5:
            why.append(f"权益缩水（净利率/ROE={margin/roe:.2f}）")
        if rg is not None and rg > 1.0:
            why.append(f"营收+{rg*100:.0f}%（疑并表/周期，非内生）")
        if why:
            flags[tk] = why

    print(f"[screen] 质检护栏命中 {len(flags)} 只（{len(flags)/max(len(elig),1)*100:.1f}%）"
          f"，下面另给「过护栏」清单")
    for tk in list(flags)[:5]:
        print(f"          {tk}: {'; '.join(flags[tk])}")

    for tier_label, g_min, v_min, q_min in TIERS:
        sel = elig[
            (elig["growth_score"].astype(float) >= g_min)
            & (elig["val_score"].astype(float) >= v_min)
            & (elig["quality_score"].astype(float) >= q_min)
        ].copy()
        head = f"=== {tier_label}（成长>={g_min:.0f} 估值>={v_min:.0f} 质量>={q_min:.0f}）"
        if sel.empty:
            print(f"\n{head}: 0 只 ===")
            continue
        sel["_min"] = sel[["growth_score", "val_score"]].astype(float).min(axis=1)
        sel = sel.sort_values(["_min", "quality_score"], ascending=False)
        print(f"\n{head}: {len(sel)} 只 ===")
        print(f"{'代码':<7}{'成长':>6}{'估值':>6}{'质量':>6}{'PE':>8}{'ROE%':>8}"
              f"{'净利率%':>9}{'营收增%':>9}{'60日%':>8}")
        for _, r in sel.head(30).iterrows():
            def f(k, nd=1, src=None):
                v = _row_num(r, src or k)
                return "   n/a" if v is None else f"{v:>{nd + 5}.{nd}f}"
            roe, mar, rg = (_pct(r, "roe"), _pct(r, "margin"), _pct(r, "rev_growth"))
            print(
                f"{str(r.get('Ticker')):<7}"
                f"{f('growth_score'):>6}{f('val_score'):>6}{f('quality_score'):>6}"
                f"{f('pe', 2):>8}"
                f"{'   n/a' if roe is None else f'{roe:>8.1f}'}"
                f"{'   n/a' if mar is None else f'{mar:>9.1f}'}"
                f"{'   n/a' if rg is None else f'{rg:>9.1f}'}"
                f"{f('mom60', 1):>8}"
            )

    # ── 过护栏清单：宽双条件里排除三类失真后的结果 ──────────────────────
    _, g_min, v_min, q_min = TIERS[-1]
    sel = elig[
        (elig["growth_score"].astype(float) >= g_min)
        & (elig["val_score"].astype(float) >= v_min)
        & (elig["quality_score"].astype(float) >= q_min)
    ].copy()
    clean = sel[~sel["Ticker"].isin(flags)].copy()
    print(f"\n=== C 过护栏（宽双条件 − {len(sel) - len(clean)} 只失真标的）: {len(clean)} 只 ===")
    if not clean.empty:
        clean["_min"] = clean[["growth_score", "val_score"]].astype(float).min(axis=1)
        clean = clean.sort_values(["_min", "quality_score"], ascending=False)
        print(f"{'代码':<7}{'成长':>6}{'估值':>6}{'质量':>6}{'PE':>8}{'PB≈':>7}"
              f"{'ROE%':>7}{'净利率%':>9}{'营收增%':>9}{'60日%':>8}")
        for _, r in clean.head(25).iterrows():
            pe = _row_num(r, "pe")
            roe = _row_num(r, "roe")
            pb = pe * roe if (pe and roe) else None
            vals = {
                "growth_score": _num(r.get("growth_score"), 0.0),
                "val_score": _num(r.get("val_score"), 0.0),
                "quality_score": _num(r.get("quality_score"), 0.0),
                "pe": _num(r.get("pe"), 0.0),
                "roe": _pct(r, "roe"), "margin": _pct(r, "margin"),
                "rev_growth": _pct(r, "rev_growth"), "mom60": _num(r.get("mom60"), 0.0),
            }
            def c(v, w, nd=1):
                return f"{'n/a':>{w}}" if v is None else f"{v:>{w}.{nd}f}"
            print(
                f"{str(r.get('Ticker')):<7}"
                f"{vals['growth_score']:>6.1f}{vals['val_score']:>6.1f}{vals['quality_score']:>6.1f}"
                f"{vals['pe']:>8.2f}"
                f"{'n/a' if pb is None else f'{pb:.1f}':>7}"
                f"{c(vals['roe'], 7)}{c(vals['margin'], 9)}{c(vals['rev_growth'], 9)}{c(vals['mom60'], 8)}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", choices=["nasdaq", "sp500", "sp1500"], default="sp1500")
    ap.add_argument("--top", type=int, default=30, help="保留的综合分前 N 名（明细里是全量）")
    ap.add_argument("--from-csv", default=None, help="跳过取数，直接分析已有明细 CSV")
    args = ap.parse_args()

    if args.from_csv:
        src = Path(args.from_csv)
        full = pd.read_csv(src, encoding="utf-8-sig")
        analyze(full, src.stem, str(src))
        return 0

    pool, label = resolve_pool(args.pool)
    print(f"[screen] 宇宙 = {label}，{len(pool)} 只")
    res = run_quant_screening(pool, top_n=args.top, pool_name=label, return_details=True)
    full, meta, failed = res["full_df"], res["metadata"], res["failed_records"]

    out_dir = ROOT / "reports" / "_datasets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"radar_{label}_{_clock.iso_today()}.csv"
    export_radar_csv(full, str(out))
    print(f"[screen] 明细已导出 {out.name}  （{len(full)} 只）")
    print(f"[screen] 扫描 {meta.get('scanned')} / 有效 {meta.get('valid')} / 失败 {meta.get('failed')}")
    # ⚠️ failed_records 是 **list**（不是 dict）；只有非零失败时才走到这里，
    #    故 503 轮（0 失败）没暴露这个分支 —— 1506 轮 6 个失败才炸出来。
    for item in list(failed)[:10]:
        print(f"          剔除 {item}")

    analyze(full, label, f"live:{label}")
    print(f"\n[meta] {meta.get('validation', {}).get('caveat', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
