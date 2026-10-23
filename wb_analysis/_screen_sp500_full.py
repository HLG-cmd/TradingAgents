# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_screen_sp500_full.py
"""SP500 全量（503）四维量化筛选 + 「高成长 x 低估值」交叉筛选。

为什么需要这个脚本
------------------
CLI 的 ``--pool sp500`` 取的是 **硬编码的 ``SP_500_CORE``（99 只人工精选子集）**，
而 ``stock_pools.get_latest_sp500()`` 能给出 **503 只**（Wikipedia 动态同步 + 两级备用源）。
两者相差 **406 只从未被筛到**。本脚本直接用后者。

用法
----
    ./.venv/Scripts/python.exe wb_analysis/_screen_sp500_full.py

产物
----
    reports/radar_sp500full_<YYYY-MM-DD>.csv   全部标的 + 全部单因子得分（utf-8-sig）

⚠️ 结论口径：``reports/fundamental_backtest_20260916.csv`` 的实测（17 个不重叠年度观测，
2009-2025，行业中性化）显示 value IC 均值 -0.0499、growth **-0.0013**、quality -0.0438
=> 本榜单**未被证明有选股能力**，只应作为「压缩研究范围」的漏斗。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from quant.screener_engine import export_radar_csv, run_quant_screening
from quant.stock_pools import get_latest_sp500
from wb_analysis import _clock

# ── 交叉筛选门槛（均为 0~100 的截面百分位得分）────────────────────────────
TIERS = [
    ("A 强双条件", 75.0, 75.0, 50.0),
    ("B 宽双条件", 60.0, 60.0, 50.0),
]
QUALITY_FLOOR = 50.0


def _num(row, key, default=None):
    try:
        v = float(row[key])
    except (KeyError, TypeError, ValueError):
        return default
    return v


def main() -> int:
    pool = get_latest_sp500()
    print(f"[screen] 全量池 {len(pool)} 只（get_latest_sp500），非 CLI 的 99 只核心")

    res = run_quant_screening(
        pool, top_n=30, pool_name="sp500full", return_details=True
    )
    full = res["full_df"]
    meta = res["metadata"]
    failed = res["failed_records"]

    out_dir = ROOT / "reports" / "_datasets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"radar_sp500full_{_clock.iso_today()}.csv"
    export_radar_csv(full, str(out))
    print(f"[screen] 明细已导出 {out.name}  （{len(full)} 只）")
    print(f"[screen] 扫描 {meta.get('scanned')} / 有效 {meta.get('valid')} / 失败 {meta.get('failed')}")
    if failed:
        for tk, why in list(failed.items())[:10]:
            print(f"          剔除 {tk}: {why}")

    # ── 数据质量闸门：短历史 / 畸形 PE ──────────────────────────────────
    warn = []
    for _, r in full.iterrows():
        tk = r["Ticker"]
        bars = _num(r, "bars", 0)
        pe = _num(r, "pe")
        if bars is not None and bars < 300:
            warn.append(f"{tk}: 历史仅 {int(bars)} 根 K 线（<300）→ 均线类指标为伪值")
        if pe is not None and 0 < pe < 3:
            warn.append(f"{tk}: PE={pe:.2f} 过低，需人工核验是否为坏值")
    print(f"\n[screen] 数据质量告警 {len(warn)} 条")
    for w in warn[:15]:
        print(f"          {w}")

    # ── 交叉筛选 ────────────────────────────────────────────────────────
    elig = full[~full["pe_missing"].astype(bool)].copy()
    print(f"\n[screen] 盈利且 PE 可得：{len(elig)} 只（剔除亏损/缺 PE {len(full) - len(elig)} 只）")

    for label, g_min, v_min, q_min in TIERS:
        sel = elig[
            (elig["growth_score"] >= g_min)
            & (elig["val_score"] >= v_min)
            & (elig["quality_score"] >= q_min)
        ].copy()
        if sel.empty:
            print(f"\n=== {label}（成长>={g_min:.0f} 估值>={v_min:.0f} 质量>={q_min:.0f}）: 0 只 ===")
            continue
        sel["双条件下限"] = sel[["growth_score", "val_score"]].min(axis=1)
        sel = sel.sort_values(["双条件下限", "quality_score"], ascending=False)
        print(f"\n=== {label}（成长>={g_min:.0f} 估值>={v_min:.0f} 质量>={q_min:.0f}）: {len(sel)} 只 ===")
        print(f"{'代码':<7}{'成长':>6}{'估值':>6}{'质量':>6}{'PE':>8}{'ROE%':>8}{'净利率%':>9}{'营收增%':>9}{'60日%':>8}")
        for _, r in sel.head(25).iterrows():
            print(
                f"{r['Ticker']:<7}{_num(r,'growth_score',0):>6.1f}{_num(r,'val_score',0):>6.1f}"
                f"{_num(r,'quality_score',0):>6.1f}{_num(r,'pe',0):>8.2f}"
                f"{_num(r,'ROE%',0):>8.1f}{_num(r,'净利率%',0):>9.1f}"
                f"{_num(r,'营收增速%',0):>9.1f}{_num(r,'60日涨幅%',0):>8.1f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
