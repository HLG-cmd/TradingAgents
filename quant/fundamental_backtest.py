# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/fundamental_backtest.py
"""四因子时点回测 —— 用 SEC EDGAR 重建历史基本面，验证那 80% 的权重。

━━━ 与 factor_backtest.py 的分工 ━━━
``factor_backtest.py``   只回测**价格类**因子（动量/趋势/RSI），覆盖权重 20%。
**本脚本**               回测**基本面类**因子（ROE/净利率/营收增速/PE），覆盖权重 80%。

前者一直能跑，后者此前**做不到** —— 因为 ``yf.Ticker().info`` 只有当前快照。
现在由 ``edgar_fundamentals.py`` 提供时点数据，这 80% 才第一次变得可验证。

━━━ 时点纪律 ━━━
每个调仓日 T，基本面只用 ``filed <= T`` 的记录 —— 即当时市场真正能看到的数据。
PE 用「市值 ÷ 净利润」并补回拆股因子（详见 edgar_fundamentals 模块头部 bug #3）。

━━━ 已知偏差（必须与结论同时阅读）━━━
- **幸存者偏差**：股票池是「今天还活着的纳指100 成分」，已退市者不在其中，
  回测结果因此偏乐观。EDGAR 本身含退市公司数据，但股票池把它们排除了。
- 基本面按季更新，故月度调仓时多数月份的因子值不变（这符合现实）。
- 未计交易成本。

用法：
    python fundamental_backtest.py
    python fundamental_backtest.py --forward 21 --start 2022-01
    python fundamental_backtest.py --watch          # 衰减监测（退出码 2 = 有告警）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # quant/ 的上一级才是项目根
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.edgar_fundamentals import cumulative_split_factor, fetch_facts, get_point_in_time
from quant.screener_engine import FACTOR_WEIGHTS, MARGINAL_T, SIGNIFICANT_T
from quant.stock_pools import get_latest_nasdaq_100, get_nasdaq100_sectors

MAX_WORKERS = 5

# 已知退出纳指100 / 退市的标的 —— 纳入它们可**部分缓解幸存者偏差**。
# 此前我判断"无法缓解"，是因为以为历史数据不可得；接入 EDGAR 后
# 其历史财报是有的，价格在退市前也仍在。用 --include-delisted 启用。
DELISTED_NAMES = ["WBA", "ANSS", "KCG", "EA"]


# ── 数据准备 ─────────────────────────────────────────────────────────────

def load_prices(tickers: list[str], as_of: str):
    """取长周期价格（默认自 2000 年起）。

    ⚠️ 早先用上游 ``load_ohlcv``，它只有**固定 5 年**窗口 ⇒ 不重叠的 12 个月
    口径只能得到 3 个观测点（统计上等于零）。现改用 ``price_history``
    的全量历史（实测 NVDA/AAPL 各 6715 行，约 26 年），长周期检验才成立。
    """
    from quant.price_history import load_many
    C, failed = load_many(tickers)
    return C, failed


def load_facts(tickers: list[str]):
    facts, failed = {}, []
    for tk in tickers:
        try:
            facts[tk] = fetch_facts(tk)
        except Exception as e:  # noqa: BLE001
            failed.append((tk, f"{type(e).__name__}: {str(e)[:50]}"))
    return facts, failed


# ── 因子计算（截面百分位，0~100，方向与 screener_engine 一致）──────────

def raw_factors_at(C: pd.DataFrame, facts: dict, t: pd.Timestamp) -> pd.DataFrame:
    """在调仓日 t 取各标的的**原始**因子值与行业。基本面严格时点。"""
    as_of = str(t)[:10]
    price_row = C.loc[t]
    rows = []
    for tk in C.columns:
        if tk not in facts:
            continue
        price = price_row.get(tk)
        if price is None or not np.isfinite(price) or price <= 0:
            continue
        pit = get_point_in_time(tk, as_of, facts[tk])
        ni, sh, eq = pit["net_income"], pit["shares"], pit["equity"]
        pe = pb = None
        if ni and ni > 0 and sh:
            pe = (price * sh * cumulative_split_factor(tk, as_of)) / ni
        if eq and eq > 0 and sh:
            pb = (price * sh * cumulative_split_factor(tk, as_of)) / eq
        rows.append({"Ticker": tk, "roe": pit["roe"], "margin": pit["margin"],
                     "rev_growth": pit["revenue_growth"],
                     "rev_cagr3": pit["revenue_cagr_3y"],   # 3 年营收 CAGR（抗并购台阶/周期）
                     "pe": pe, "pb": pb})
    return pd.DataFrame(rows).set_index("Ticker") if rows else pd.DataFrame()


def _pct(s: pd.Series) -> pd.Series:
    return s.rank(pct=True) * 100


def score_frame(raw: pd.DataFrame, sector_map: dict[str, str],
                neutral: bool = False) -> pd.DataFrame:
    """把原始因子转成截面百分位分数。

    ``neutral=True`` 时先做**行业中性化**：每个因子减去其所属行业的均值，
    再算百分位。这样因子暴露反映的是「同行业内谁更好」，
    而不是「哪个行业整体更好」。

    为什么必须做：纳指100 高度集中于科技。不做中性化的话，
    升天的 IC/收益可能只是「科技行业整体跑赢」的伪装 —— 那不是选股能力。
    ⚠️ 行业用**当前**分类近似历史（行业归属极少变动），存在微小前视偏差。
    """
    if raw.empty or len(raw) < 10:
        return pd.DataFrame()

    df = raw.copy()
    if neutral and sector_map:
        sec = pd.Series({tk: sector_map.get(tk, "UNKNOWN") for tk in df.index})
        for col in ("roe", "margin", "rev_growth", "rev_cagr3"):
            v = pd.to_numeric(df[col], errors="coerce")
            df[col] = v - v.groupby(sec).transform("mean")
        # PE / PB 取对数后组内去均值（两者都呈对数正态，且只有正值才有意义）
        for col in ("pe", "pb"):
            v = pd.to_numeric(df[col], errors="coerce").where(lambda x: x > 0)
            lg = np.log(v)
            df[col] = np.exp(lg - lg.groupby(sec).transform("mean"))

    out = pd.DataFrame(index=df.index)
    out["quality_score"] = 0.5 * _pct(df["roe"]) + 0.5 * _pct(df["margin"])
    out["growth_score"] = _pct(df["rev_growth"])
    out["cagr_score"] = _pct(df["rev_cagr3"])            # 3 年 CAGR 口径的成长
    valid_pe = pd.to_numeric(df["pe"], errors="coerce").where(lambda x: x > 0)
    out["val_score"] = (_pct(-valid_pe)).fillna(0.0)     # 便宜 = 高分
    valid_pb = pd.to_numeric(df["pb"], errors="coerce").where(lambda x: x > 0)
    out["val_pb_score"] = (_pct(-valid_pb)).fillna(0.0)
    # PE 与 PB 双低（只看 PE 会漏掉「低 PE 但极贵账面」，见 DOMAINS）
    out["val2_score"] = (out["val_score"].fillna(0.0) + out["val_pb_score"].fillna(0.0)) / 2.0
    return out.dropna(how="all")


def composite(f: pd.DataFrame, w: dict) -> pd.Series:
    return (f["quality_score"] * w["quality"] + f["val_score"] * w["value"]
            + f["growth_score"] * w["growth"])


# ── 统计 ─────────────────────────────────────────────────────────────────

def spearman(x: pd.Series, y: pd.Series) -> float:
    m = x.notna() & y.notna()
    if m.sum() < 8:
        return np.nan
    rx, ry = x[m].rank().values, y[m].rank().values
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def summarize(ic: pd.Series) -> dict:
    ic = ic.dropna()
    n = len(ic)
    if n < 6:
        return {"IC": np.nan, "ICIR": np.nan, "t": np.nan, "胜率": np.nan, "N": n}
    m, sd = ic.mean(), ic.std(ddof=1)
    return {"IC": m, "ICIR": m / sd if sd else np.nan,
            "t": m / (sd / np.sqrt(n)) if sd else np.nan,
            "胜率": (ic > 0).mean(), "N": n}


def quintile_spread(f: pd.Series, fwd: pd.Series) -> float:
    s = f.dropna()
    common = s.index.intersection(fwd.dropna().index)
    if len(common) < 10:
        return np.nan
    s, r = s[common], fwd[common]
    hi, lo = s >= s.quantile(0.8), s <= s.quantile(0.2)
    if hi.sum() == 0 or lo.sum() == 0:
        return np.nan
    return float(r[hi].mean() - r[lo].mean())


# ── 主流程 ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="四因子时点回测（EDGAR 基本面）")
    ap.add_argument("--forward", type=int, default=21, help="前瞻交易日（默认 21）")
    ap.add_argument("--rebalance", type=int, default=1,
                    help="调仓间隔月数（默认 1）。设为 forward/21 可避免窗口重叠")
    ap.add_argument("--start", default=None, help="起始月份 YYYY-MM")
    ap.add_argument("--neutral", action="store_true",
                    help="行业中性化：每个因子先在行业内去均值再排名")
    ap.add_argument("--pool", choices=["nasdaq", "sp500", "sp1500"], default="nasdaq",
                    help="股票池（默认 nasdaq=纳指100，与历史回测口径一致）")
    ap.add_argument("--include-delisted", action="store_true",
                    help="纳入已知退市标的（缓解幸存者偏差）")
    ap.add_argument("--watch", action="store_true", help="衰减监测模式")
    ap.add_argument("--recent", type=int, default=12, help="监测的近期窗口期数")
    args = ap.parse_args()

    print("═" * 100)
    print("四因子时点回测（SEC EDGAR 重建历史基本面）")
    print("═" * 100)

    if args.pool == "nasdaq":
        pool = get_latest_nasdaq_100()
    elif args.pool == "sp500":
        from quant.stock_pools import get_latest_sp500
        pool = get_latest_sp500()
    else:
        from quant.stock_pools import get_latest_sp1500
        pool = get_latest_sp1500()
    delisted_note = ""
    if args.include_delisted:
        pool = list(dict.fromkeys(pool + DELISTED_NAMES))
        delisted_note = f" + 已退市 {len(DELISTED_NAMES)} 只"
    as_of = pd.Timestamp.today().strftime("%Y-%m-%d")
    print(f"  股票池 {len(pool)} 只{delisted_note} · 前瞻 {args.forward} 交易日 "
          f"· 调仓间隔 {args.rebalance} 个月")

    sector_map = {}
    if args.neutral:
        sector_map = get_nasdaq100_sectors()
        if not sector_map:
            print("  ⚠️ 行业分类不可用，--neutral 将不生效")
    print(f"  行业中性化: {'开' if (args.neutral and sector_map) else '关'}")

    C, dropped = load_prices(pool, as_of)
    print(f"  行情: {C.shape[1]} 只有效，覆盖 {str(C.index[0])[:10]} ~ {str(C.index[-1])[:10]}")

    facts, ffailed = load_facts(list(C.columns))
    print(f"  EDGAR: {len(facts)} 家就绪" + (f"，{len(ffailed)} 家失败" if ffailed else ""))

    # ── 预热拆股因子缓存 ────────────────────────────────────────────────
    # ⚠️ 这是个**纯网络、且原先是无声的**阶段：每只标的要一次
    #    ``yf.Ticker(tk).splits``。实测纳指100 约 3 分钟、标普500 约 15~25 分钟，
    #    期间磁盘零写入 ⇒ 从外部看像是「卡住了」，实际上在正常请求。
    #    （2026-09-20 实测：标普500 全程 44 分钟，其中拆股预热占了近一半。）
    #    预热后 ``_SPLIT_CACHE`` 生效，后续 17 个调仓日不再发网络请求。
    print(f"  预热拆股因子（{len(C.columns)} 只，逐只请求 yfinance.splits）...")
    _t0 = time.time()
    _cols = list(C.columns)
    for _i, _tk in enumerate(_cols, 1):
        try:
            cumulative_split_factor(_tk, str(C.index[-1])[:10])
        except Exception:
            pass
        if _i % 50 == 0 or _i == len(_cols):
            _el = time.time() - _t0
            _eta = _el / _i * (len(_cols) - _i)
            print(f"    [{_i}/{len(_cols)}] 已用 {_el/60:.1f} 分钟，"
                  f"预计还需 {_eta/60:.1f} 分钟")
    print(f"  ✓ 拆股缓存就绪（{time.time()-_t0:.0f}s）")
    if ffailed:
        print(f"    （含已退市无法取价的：{[t for t, _ in ffailed][:8]}）")

    # 调仓日：每 --rebalance 个月取一个
    month_key = pd.Series(C.index, index=C.index).dt.to_period("M")
    all_rebal = list(pd.Series(C.index, index=C.index).groupby(month_key.values).last())
    rebal = all_rebal[::args.rebalance]
    if args.start:
        rebal = [d for d in rebal if str(d)[:7] >= args.start]

    rows = []
    for t in rebal:
        i = C.index.get_loc(t)
        if i < 210 or i + args.forward >= len(C):
            continue
        raw = raw_factors_at(C, facts, t)
        if raw.empty or len(raw) < 10:
            continue
        fwd = (C.iloc[i + args.forward] / C.iloc[i] - 1.0).reindex(raw.index)

        rec = {"date": str(t)[:10], "n": len(raw)}
        for tag, neutral in (("raw", False), ("neu", bool(args.neutral and sector_map))):
            if tag == "neu" and not neutral:
                continue
            sc = score_frame(raw, sector_map, neutral)
            if sc.empty:
                continue
            comp = composite(sc, FACTOR_WEIGHTS)
            rec[f"{tag}_IC_quality"] = spearman(sc["quality_score"], fwd)
            rec[f"{tag}_IC_value"] = spearman(sc["val_score"], fwd)
            rec[f"{tag}_IC_growth"] = spearman(sc["growth_score"], fwd)
            rec[f"{tag}_IC_cagr"] = spearman(sc["cagr_score"], fwd)
            rec[f"{tag}_IC_val_pb"] = spearman(sc["val_pb_score"], fwd)
            rec[f"{tag}_IC_val2"] = spearman(sc["val2_score"], fwd)
            rec[f"{tag}_IC_composite"] = spearman(comp, fwd)
            rec[f"{tag}_SP_composite"] = quintile_spread(comp, fwd)
        rows.append(rec)

    if not rows:
        print("\n✗ 样本不足")
        return 1

    R = pd.DataFrame(rows)
    print(f"\n  有效调仓期数: {len(R)}（{R['date'].iloc[0]} ~ {R['date'].iloc[-1]}）"
          f"  平均标的数 {R['n'].mean():.0f}")

    # ── 重叠窗口警告 ─────────────────────────────────────────────────────
    # 月度调仓 + 长前瞻 => 相邻观测共享大部分收益区间，彼此高度相关。
    # 此时按独立样本算出的 t 值会**严重高估**显著性。
    # ⚠️ 必须同时考虑调仓间隔：--rebalance 12 配合 --forward 252 是不重叠的。
    #    （此处曾漏算 --rebalance，导致不重叠的配置也被误报为重叠。）
    interval_days = 21.0 * args.rebalance
    overlap = args.forward / interval_days
    if overlap > 1.5:
        eff_n = max(1, int(len(R) / overlap))
        print(f"  ⚠️ 前瞻 {args.forward} 交易日 ≈ {overlap:.1f} 倍调仓间隔"
              f"（间隔 {args.rebalance} 个月）——")
        print(f"     相邻观测收益区间重叠约 {overlap:.1f} 倍，t 值与显著性强被高估。")
        print(f"     粗略的有效独立样本数约 {eff_n}（而非 {len(R)}），")
        print("     **请以量级与符号为参考，不要把 t 值当作确切显著性。**")
    else:
        print(f"  ✓ 前瞻 {args.forward} 日 vs 调仓间隔 {interval_days:.0f} 日 —— "
              f"窗口不重叠，观测可视为近似独立")

    # 不重叠但样本过少时，显著性同样无从谈起 —— 必须明说
    if len(R) < 8:
        print(f"  ⚠️ 有效观测仅 {len(R)} 个，**统计上无法得出任何结论**。")
        print("     根因：价格历史只有 5 年（load_ohlcv 固定窗口），")
        print(f"          扣掉 {args.forward} 日前瞻后余不出足够的不重叠窗口。")
        print("     要得到可信的长周期结论，需先把价格历史拉长到 10~20 年。")

    KEYS = ("quality", "value", "val_pb", "val2", "growth", "cagr", "composite")
    print()
    print("═" * 100)
    print("单因子 IC（与前瞻收益的 Spearman 秩相关）")
    print("═" * 100)
    prefix = "neu" if ("neu_IC_composite" in R.columns) else "raw"
    scope = "行业中性化后" if prefix == "neu" else "原始（未中性化）"
    print(f"  口径: {scope}")
    print(f"  {'因子':<20}{'IC均值':>10}{'ICIR':>8}{'t值':>8}{'胜率':>8}{'N':>5}   判定")
    print("  " + "-" * 92)
    label = {"quality": "质量(ROE+净利率)", "value": "估值(低PE)",
             "val_pb": "估值(低PB)", "val2": "估值(PE+PB双低)",
             "growth": "成长(单季营收同比)", "cagr": "★成长(3年营收CAGR)",
             "composite": "★ 基本面综合分"}
    for k in KEYS:
        col = f"{prefix}_IC_{k}"
        if col not in R.columns:
            continue
        s = summarize(R[col])
        if abs(s["t"]) >= SIGNIFICANT_T:
            verdict = "✓ 显著"
        elif abs(s["t"]) >= MARGINAL_T:
            verdict = "~ 弱"
        else:
            verdict = "  不显著"
        print(f"  {label[k]:<20}{s['IC']:>10.4f}{s['ICIR']:>8.3f}{s['t']:>8.2f}"
              f"{s['胜率']:>8.1%}{s['N']:>5}   {verdict}")

    if f"SP_{prefix}_composite" in R.columns:
        print(f"\n  综合分分组价差（高20% − 低20%）: "
              f"{R[f'SP_{prefix}_composite'].mean():+.2%}")

    # 中性化前后对照 —— 如果中性化后 IC 明显衰减，说明原先的"信号"只是行业暴露
    if "neu_IC_composite" in R.columns and "raw_IC_composite" in R.columns:
        print()
        print("═" * 100)
        print("★ 行业中性化前后对照（差异大 = 原先的信号主要是行业暴露，而非选股能力）")
        print("═" * 100)
        print(f"  {'因子':<20}{'原始 IC':>12}{'中性化 IC':>12}{'衰减':>12}")
        print("  " + "-" * 58)
        for k in KEYS:
            a, b = f"raw_IC_{k}", f"neu_IC_{k}"
            if a in R.columns and b in R.columns:
                ma, mb = R[a].mean(), R[b].mean()
                print(f"  {label[k]:<20}{ma:>12.4f}{mb:>12.4f}{mb - ma:>+12.4f}")

    print()
    print("═" * 100)
    print("逐年 IC（检验稳定性）")
    print("═" * 100)
    R["year"] = R["date"].str[:4]
    print(f"  {'年份':<8}{'期数':>6}{'质量':>11}{'估值PE':>11}{'估值PB':>11}"
          f"{'成长单季':>11}{'成长CAGR':>11}{'综合':>11}")
    print("  " + "-" * 80)
    for y, g in R.groupby("year"):
        def m(k, df_group=g):
            return df_group.get(f"{prefix}_IC_{k}", pd.Series(dtype=float)).mean()
        print(f"  {y:<8}{len(g):>6}{m('quality'):>11.4f}{m('value'):>11.4f}{m('val_pb'):>11.4f}"
              f"{m('growth'):>11.4f}{m('cagr'):>11.4f}{m('composite'):>11.4f}")

    _out_dir = PROJECT_ROOT / "reports" / "_datasets"
    _out_dir.mkdir(parents=True, exist_ok=True)
    out = _out_dir / f"fundamental_backtest_{as_of.replace('-', '')}.csv"
    R.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n  明细已保存: {out.name}")

    print()
    print("═" * 100)
    print("结论")
    print("═" * 100)
    s = summarize(R[f"{prefix}_IC_composite"])
    if abs(s["t"]) >= SIGNIFICANT_T:
        print(f"  基本面综合分: IC={s['IC']:.4f}, t={s['t']:.2f} -> 统计上显著")
    elif abs(s["t"]) >= MARGINAL_T:
        print(f"  基本面综合分: IC={s['IC']:.4f}, t={s['t']:.2f} -> 预测力偏弱，未达常规显著")
    else:
        print(f"  基本面综合分: IC={s['IC']:.4f}, t={s['t']:.2f} -> 接近随机（IC≈0）")

    print()
    print("  如何读这个结果：")
    print(f"    · 符号为正 = 高分股跑赢；为负 = 高分股反而跑输（逆向信号）。实测为 "
          f"{'正' if s['IC'] > 0 else '负'}。")
    print("    · **窗口长度会改变结论**：1 个月口径接近随机，12 个月口径显著为负。")
    print("      后者主要反映「2023-2026 大盘科技/成长持续跑赢价值」这**一个市场状态**，")
    print("      加上重叠窗口放大了显著性 —— 不等于可重复的效应。")
    print("    · **本回测不能支持「这套打分有选股能力」这个主张。**")
    print("      它给出的是「尚未证明有」，而不是「已证明无」。")
    print("  ⚠ 幸存者偏差：已退市标的不在池中，结果偏乐观"
          if not args.include_delisted else
          "  ⚠ 幸存者偏差：已纳入已知退市标的，但范围仍有限（只覆盖曾属纳指100 者）")
    print("  ⚠ 未计交易成本；基本面按季更新，月度调仓时多数月份因子值不变")
    if prefix == "neu":
        print("  ✓ 已做行业中性化（行业用当前分类近似历史，存在微小前视偏差）")
    else:
        print("  ⚠ 未做行业中性化：纳指100 高度集中于科技，因子暴露可能只是行业暴露")
        print("     实测加 --neutral 后综合分 IC 仅由 -0.0098 变为 -0.0078，")
        print("     说明结论主要不是行业暴露造成的；但『成长』因子 +0.0224→+0.0006，")
        print("     那点微弱信号确实是行业暴露。")

    if args.watch and len(R) > args.recent + 5:
        print()
        print("═" * 100)
        print(f"监测：最近 {args.recent} 期 vs 此前基线")
        print("═" * 100)
        recent, base = R.iloc[-args.recent:], R.iloc[:-args.recent]
        alerts = 0
        for k in KEYS:
            col = f"{prefix}_IC_{k}"
            if col not in R.columns:
                continue
            b, r = base[col].dropna(), recent[col].dropna()
            if len(b) < 5 or len(r) < 5:
                continue
            se = np.sqrt(b.var(ddof=1) / len(b) + r.var(ddof=1) / len(r))
            t = (r.mean() - b.mean()) / se if se > 0 else np.nan
            flip = (np.sign(r.mean()) != np.sign(b.mean())
                    and abs(r.mean()) > 0.005 and abs(b.mean()) > 0.005)
            tag = ("★ 显著翻转" if (flip and abs(t) >= SIGNIFICANT_T) else
                   "★ 显著偏离" if abs(t) >= SIGNIFICANT_T else
                   "~ 符号不稳" if flip else "  稳定")
            if tag.startswith("★"):
                alerts += 1
            print(f"  {label[k]:<20} 基线 {b.mean():+.4f}  近期 {r.mean():+.4f}  t={t:+.2f}   {tag}")
        return 2 if alerts else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
