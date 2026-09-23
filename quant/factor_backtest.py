# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/factor_backtest.py
"""因子有效性回测（时点严格 / point-in-time）

目的：回答「这套打分到底有没有预测力」，以及「因子会不会失效」。

═══ 能力边界（必须先读） ═══
本脚本 **只能严格回测价格类因子**（动量 / 均线形态 / RSI），因为它们可由
``load_ohlcv`` 的 5 年日线完整重建，且不引入前视偏差。

基本面因子（ROE / 净利率 / 营收增速 / PE，合计权重 80%）**无法严格回测**：
  · ``yf.Ticker().info`` 只提供**当前快照**，没有历史序列
  · 年度利润表仅 5 期，扣掉披露延迟后只剩约 4 个可用截面 —— 统计上无意义
因此本回测覆盖权重 20% 的技术面一档；这是免费数据源的硬边界，不是偷懒。

═══ 方法 ═══
· 股票池：NASDAQ_100 当前成分（⚠️ 存在幸存者偏差：已退市的 WBA/ANSS/KCG/EA
  不在池中，回测结果因此偏乐观，需知悉）
· 调仓频率：月度（每月最后一个交易日）
· 时点纪律：t 日只用 ≤ t 的数据算因子；前瞻收益 = t+21 交易日的收益
· 指标：
    IC    —— 因子值与前瞻收益的 Spearman 秩相关（逐月计算后取均值）
    ICIR  —— IC 均值 / IC 标准差（信息比率）
    t值   —— IC 均值的显著性
    分组  —— 最高 20% 组 − 最低 20% 组的平均前瞻收益差

用法：
    python factor_backtest.py
    python factor_backtest.py --periods 60 --forward 21
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # quant/ 的上一级才是项目根
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.stock_pools import NASDAQ_100
from tradingagents.dataflows.stockstats_utils import load_ohlcv  # noqa: E402
from tradingagents.dataflows.symbol_utils import NoMarketDataError  # noqa: E402

MAX_WORKERS = 5


# ─────────────────────────── 数据准备 ───────────────────────────

def load_panel(tickers: list[str], as_of: str):
    """并发加载各标的的长周期日线，返回 (收盘价宽表, 成交量宽表)。

    ⚠️ 早先用 ``load_ohlcv``（固定 5 年）⇒ 只有 49 个不重叠度有限的月观测。
    现改用 ``price_history`` 的全量历史（约 26 年），
    使「近 6/12/18/24 期」这类窗口比较有了足够深的样本。
    """
    from quant.price_history import load_prices_long
    closes, volumes, dropped = {}, {}, []

    def one(tk):
        try:
            df = load_prices_long(tk)
        except Exception as exc:  # noqa: BLE001
            return tk, None, None, f"{type(exc).__name__}: {str(exc)[:50]}"
        if df is None or df.empty:
            return tk, None, None, "空"
        s = df.set_index("Date").sort_index()
        return tk, s["Close"], s.get("Volume"), None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for fut in as_completed([ex.submit(one, t) for t in tickers]):
            tk, c, v, err = fut.result()
            if err:
                dropped.append((tk, err))
            else:
                closes[tk] = c
                if v is not None:
                    volumes[tk] = v

    C = pd.DataFrame(closes).sort_index()
    V = pd.DataFrame(volumes).sort_index()
    return C, V, dropped


# ─────────────────────────── 因子计算 ───────────────────────────

def factors_at(C: pd.DataFrame, V: pd.DataFrame, i: int) -> pd.DataFrame:
    """在第 i 个交易日（含）截断历史，计算各标的因子。严格无前视。"""
    hist = C.iloc[: i + 1]
    volh = V.iloc[: i + 1] if not V.empty else None
    if len(hist) < 210:
        return pd.DataFrame()

    last = hist.iloc[-1]
    ma50 = hist.rolling(50).mean().iloc[-1]
    ma200 = hist.rolling(200).mean().iloc[-1]
    mom20 = hist.iloc[-1] / hist.iloc[-21] - 1.0
    mom60 = hist.iloc[-1] / hist.iloc[-61] - 1.0

    d = hist.diff()
    gain = d.where(d > 0, 0.0).rolling(14).mean().iloc[-1]
    loss = (-d.where(d < 0, 0.0)).rolling(14).mean().iloc[-1]
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    is_bull = (last > ma200) & (ma50 > ma200)

    if volh is not None and len(volh) >= 20:
        vr = volh.iloc[-5:].mean() / (volh.iloc[-20:].mean() + 1e-9)
    else:
        vr = pd.Series(np.nan, index=last.index)

    return pd.DataFrame({
        "mom20": mom20, "mom60": mom60, "rsi": rsi,
        "is_bull": is_bull.astype(float), "vol_ratio": vr,
    }).dropna(subset=["mom60"])


def composite_trend_score(f: pd.DataFrame) -> pd.Series:
    """复刻 screener_engine 的 trend_score：0.6*动量百分位 + 0.25*均线 + 0.15*RSI 区间。"""
    def band(v):
        if v != v:
            return 50.0
        if 45.0 <= v <= 68.0:
            return 100.0
        dist = (45.0 - v) if v < 45.0 else (v - 68.0)
        return float(max(0.0, 100.0 - dist / (23.0 * 1.5) * 100.0))

    mom_r = f["mom60"].rank(pct=True) * 100
    rsi_s = f["rsi"].apply(band)
    return 0.60 * mom_r + 0.25 * f["is_bull"] * 100 + 0.15 * rsi_s


# ─────────────────────────── 统计工具 ───────────────────────────

def spearman(x: pd.Series, y: pd.Series) -> float:
    m = x.notna() & y.notna()
    if m.sum() < 8:
        return np.nan
    rx = x[m].rank().values
    ry = y[m].rank().values
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan
    return float(np.corrcoef(rx, ry)[0, 1])


def summarize(ic: pd.Series) -> dict:
    ic = ic.dropna()
    n = len(ic)
    if n < 6:
        return {"IC": np.nan, "ICIR": np.nan, "t": np.nan, "胜率": np.nan, "N": n}
    mean, sd = ic.mean(), ic.std(ddof=1)
    return {
        "IC": mean,
        "ICIR": mean / sd if sd else np.nan,
        "t": mean / (sd / np.sqrt(n)) if sd else np.nan,
        "胜率": (ic > 0).mean(),
        "N": n,
    }


def quintile_spread(f: pd.DataFrame, fwd: pd.Series, col: str) -> float:
    """最高 20% 组 − 最低 20% 组的平均前瞻收益。"""
    s = f[col].dropna()
    common = s.index.intersection(fwd.dropna().index)
    if len(common) < 10:
        return np.nan
    s = s[common]
    r = fwd[common]
    hi = s >= s.quantile(0.8)
    lo = s <= s.quantile(0.2)
    if hi.sum() == 0 or lo.sum() == 0:
        return np.nan
    return float(r[hi].mean() - r[lo].mean())


# ─────────────────────────── 监测模式 ───────────────────────────

WATCH_FACTORS = ["mom60", "is_bull", "trend_score"]
HISTORY_NAME = "factor_ic_history.csv"


def watch_report(R: pd.DataFrame, recent_n: int, history_path: Path) -> int:
    """对比「最近 recent_n 期」与「此前全部期」的 IC，检测因子是否已衰减/翻转。

    用**非重叠双样本 t 检验**（近期窗口 vs 其前的样本），而不是拿近期均值
    与含它自身在内的全样本均值比 —— 后者会低估差异、掩盖真实衰减。

    返回告警条数，供调用方决定退出码。
    """
    print()
    print("═" * 96)
    print(f"监测模式：最近 {recent_n} 期 vs 此前基线（非重叠双样本检验）")
    print("═" * 96)

    if len(R) <= recent_n + 5:
        print(f"  ⚠ 总期数 {len(R)} 不足以切出非重叠窗口（需 > {recent_n + 5}），跳过监测")
        return 0

    recent = R.iloc[-recent_n:]
    base = R.iloc[:-recent_n]

    print(f"  基线窗口: {base['date'].iloc[0]} ~ {base['date'].iloc[-1]}（{len(base)} 期）")
    print(f"  近期窗口: {recent['date'].iloc[0]} ~ {recent['date'].iloc[-1]}（{len(recent)} 期）")
    print()
    print(f"  {'因子':<14}{'基线IC':>10}{'近期IC':>10}{'变化':>10}{'t值':>8}   判定")
    print("  " + "-" * 78)

    label = {"mom60": "60日动量", "is_bull": "均线多头", "trend_score": "趋势综合分"}
    alerts = []
    for col in WATCH_FACTORS:
        b = base[f"IC_{col}"].dropna()
        r = recent[f"IC_{col}"].dropna()
        if len(b) < 5 or len(r) < 5:
            print(f"  {label[col]:<14}{'样本不足':>10}")
            continue
        bm, rm = b.mean(), r.mean()
        se = np.sqrt(b.var(ddof=1) / len(b) + r.var(ddof=1) / len(r))
        t = (rm - bm) / se if se > 0 else np.nan
        flip = (np.sign(rm) != np.sign(bm)) and abs(rm) > 0.005 and abs(bm) > 0.005

        # 两级告警：符号翻转**且**显著才是强告警；仅翻转但 t 很小属噪声，只作提示。
        # （实测该样本上 t≈0.8，若一律强告警会持续误报。）
        if flip and abs(t) >= 2.0:
            verdict = "★ 显著翻转"
            alerts.append(("strong",
                           f"{label[col]}：IC 由 {bm:+.4f} 显著翻转为 {rm:+.4f}（t={t:.2f}）"))
        elif abs(t) >= 2.0:
            verdict = "★ 显著偏离"
            alerts.append(("strong",
                           f"{label[col]}：近期 {rm:+.4f} 相对基线 {bm:+.4f} 显著偏离（t={t:.2f}）"))
        elif flip:
            verdict = "~ 符号不稳"
            alerts.append(("weak",
                           f"{label[col]}：符号已翻转（{bm:+.4f}→{rm:+.4f}），但 t={t:.2f} 不显著"))
        elif abs(t) >= 1.5:
            verdict = "~ 轻度偏离"
        else:
            verdict = "  稳定"
        print(f"  {label[col]:<14}{bm:>10.4f}{rm:>10.4f}{rm - bm:>+10.4f}{t:>8.2f}   {verdict}")

    # ── 窗口敏感性检验：同一个因子，换不同回看窗口，符号是否一致？
    #    符号随窗口漂移 = 信号不稳健的直接证据（比单点 IC 更有说服力）。
    print()
    print("  窗口敏感性检验（同一因子在不同回看窗口下的 IC 符号）")
    print(f"  {'因子':<14}" + "".join(f"{f'近{w}期':>11}" for w in (6, 12, 18, 24)) + "   一致性")
    print("  " + "-" * 78)
    unstable = []
    unstable_map: dict[str, bool] = {}
    for col in WATCH_FACTORS:
        vals, signs = [], []
        for w in (6, 12, 18, 24):
            seg = R[f"IC_{col}"].iloc[-w:].dropna()
            v = seg.mean() if len(seg) >= 4 else np.nan
            vals.append(v)
            if v == v:
                signs.append(np.sign(v))
        consistent = len(set(signs)) <= 1 if signs else True
        unstable_map[col] = not consistent
        if not consistent:
            unstable.append(label[col])
        cells = "".join(f"{v:>+11.4f}" if v == v else f"{'—':>11}" for v in vals)
        print(f"  {label[col]:<14}{cells}   {'✓ 一致' if consistent else '✗ 符号漂移'}")

    print()
    strong = [a for lvl, a in alerts if lvl == "strong"]
    weak = [a for lvl, a in alerts if lvl == "weak"]
    if strong:
        print("  ⚠️ 强告警（统计显著）：")
        for a in strong:
            print(f"    · {a}")
    if weak:
        print("  · 提示（未达显著，可能是噪声，继续观察）：")
        for a in weak:
            print(f"    · {a}")
    if unstable:
        print(f"  · 符号随窗口漂移的因子：{', '.join(unstable)}")
        print("    → 换一个回看窗口结论就变号，说明该因子**不稳健**，")
        print("      任何基于它的权重都缺乏依据。")
    if strong or unstable:
        print()
        print("  → 因子不稳定通常源于市场状态切换（趋势市 ↔ 反转市）。")
        print("    这不是代码 bug，是因子本身的时变特性。建议：")
        print("      1) 用 run_quant_screening(weights={...}) 下调该档权重")
        print("      2) 或停用该档（如 {'trend': 0.0}）")
        print("      3) **不要**用单一近期窗口反拟合权重 —— 那是过拟合")
    if not strong and not weak and not unstable:
        print("  ✓ 未检测到显著衰减或符号漂移")

    # 累积历史（同一区间重复运行则覆盖，避免膨胀）
    key_cols = ["run_date", "span_start", "span_end", "recent_n", "factor"]
    row_base = {
        "run_date": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "span_start": R["date"].iloc[0],
        "span_end": R["date"].iloc[-1],
        "recent_n": recent_n,
    }
    new_rows = []
    for col in WATCH_FACTORS:
        b = base[f"IC_{col}"].dropna()
        r = recent[f"IC_{col}"].dropna()
        if len(b) < 5 or len(r) < 5:
            continue
        se = np.sqrt(b.var(ddof=1) / len(b) + r.var(ddof=1) / len(r))
        new_rows.append({
            **row_base, "factor": col,
            "baseline_ic": round(b.mean(), 5), "recent_ic": round(r.mean(), 5),
            "delta": round(r.mean() - b.mean(), 5),
            "t": round((r.mean() - b.mean()) / se, 3) if se > 0 else np.nan,
            "sign_unstable": bool(unstable_map.get(col, False)),
            "n_base": len(b), "n_recent": len(r),
        })
    if new_rows:
        hist = pd.DataFrame(new_rows)
        if history_path.exists():
            try:
                old = pd.read_csv(history_path, encoding="utf-8-sig")
                merged = pd.concat([old, hist], ignore_index=True)
                merged = merged.drop_duplicates(subset=key_cols, keep="last")
                hist = merged
            except Exception as exc:  # noqa: BLE001
                print(f"  (历史文件读取失败，将覆盖: {exc})")
        hist = hist.sort_values(["run_date", "factor"])
        hist.to_csv(history_path, index=False, encoding="utf-8-sig")
        print(f"\n  监测历史已累积: {history_path.name}（{len(hist)} 条记录，UTF-8 BOM）")

    # 退出码：仅强告警或符号漂移才算需要关注，避免在噪声上误报
    return len(strong) + (1 if unstable else 0)


# ─────────────────────────── 主流程 ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="因子有效性回测（时点严格）")
    ap.add_argument("--forward", type=int, default=21, help="前瞻收益交易日数（默认 21≈1个月）")
    ap.add_argument("--min-history", type=int, default=210, help="最少历史K线（默认 210）")
    ap.add_argument("--watch", action="store_true",
                    help="监测模式：对比近期与历史基线，检测因子衰减/翻转，并累积 IC 历史")
    ap.add_argument("--recent", type=int, default=12,
                    help="监测模式下的「近期」窗口期数（默认 12，约一年）")
    args = ap.parse_args()

    as_of = pd.Timestamp.today().strftime("%Y-%m-%d")
    print("═" * 96)
    print("因子有效性回测（point-in-time，价格类因子）")
    print("═" * 96)
    print(f"  股票池 {len(NASDAQ_100)} 只 · 前瞻 {args.forward} 交易日 · 基准日 {as_of}")

    C, V, dropped = load_panel(NASDAQ_100, as_of)
    print(f"  行情加载: {C.shape[1]}/{len(NASDAQ_100)} 只可用"
          f"，覆盖 {str(C.index[0])[:10]} ~ {str(C.index[-1])[:10]}（{len(C)} 个交易日）")
    if dropped:
        print(f"  剔除 {len(dropped)} 只: {[d[0] for d in dropped][:8]}")

    # 调仓点：每月最后一个交易日
    idx = C.index
    month_key = pd.Series(idx, index=idx).dt.to_period("M")
    rebal = pd.Series(idx, index=idx).groupby(month_key.values).last()

    rows = []
    for t in rebal:
        i = idx.get_loc(t)
        if i < args.min_history or i + args.forward >= len(idx):
            continue
        f = factors_at(C, V, i)
        if f.empty or len(f) < 10:
            continue
        fwd = C.iloc[i + args.forward] / C.iloc[i] - 1.0
        fwd = fwd.reindex(f.index)
        f["trend_score"] = composite_trend_score(f)

        rec = {"date": str(t)[:10], "n": len(f)}
        for col in ("mom20", "mom60", "rsi", "is_bull", "vol_ratio", "trend_score"):
            rec[f"IC_{col}"] = spearman(f[col], fwd)
            rec[f"SP_{col}"] = quintile_spread(f, fwd, col)
        rows.append(rec)

    if not rows:
        print("\n✗ 回测样本不足，请检查数据")
        return 1

    R = pd.DataFrame(rows)
    print(f"\n  有效调仓期数: {len(R)}（{R['date'].iloc[0]} ~ {R['date'].iloc[-1]}）")
    print(f"  每期平均标的数: {R['n'].mean():.0f}")

    print()
    print("═" * 96)
    print("单因子 IC（Spearman 秩相关，均值越大预测力越强）")
    print("═" * 96)
    print(f"  {'因子':<14}{'IC均值':>9}{'ICIR':>8}{'t值':>8}{'胜率':>8}{'N':>5}"
          f"{'  分组价差(高20%-低20%)':>22}")
    print("  " + "-" * 92)
    label = {"mom20": "20日动量", "mom60": "60日动量", "rsi": "RSI",
             "is_bull": "均线多头", "vol_ratio": "量比", "trend_score": "趋势综合分"}
    for col in ("mom20", "mom60", "rsi", "is_bull", "vol_ratio", "trend_score"):
        s = summarize(R[f"IC_{col}"])
        sp = R[f"SP_{col}"].mean()
        flag = ""
        if abs(s["t"]) >= 2.0:
            flag = "  ✓显著"
        elif abs(s["t"]) >= 1.0:
            flag = "  ~弱"
        print(f"  {label[col]:<14}{s['IC']:>9.4f}{s['ICIR']:>8.3f}{s['t']:>8.2f}"
              f"{s['胜率']:>8.1%}{s['N']:>5}{sp:>20.2%}{flag}")

    print()
    print("═" * 96)
    print("逐年 IC（检验因子是否稳定 / 会否失效）")
    print("═" * 96)
    R["year"] = R["date"].str[:4]
    print(f"  {'年份':<8}{'期数':>6}{'60日动量':>12}{'均线多头':>12}{'趋势综合分':>14}")
    print("  " + "-" * 54)
    for y, g in R.groupby("year"):
        print(f"  {y:<8}{len(g):>6}{g['IC_mom60'].mean():>12.4f}"
              f"{g['IC_is_bull'].mean():>12.4f}{g['IC_trend_score'].mean():>14.4f}")

    _out_dir = PROJECT_ROOT / "reports" / "_datasets"
    _out_dir.mkdir(parents=True, exist_ok=True)
    out = _out_dir / f"factor_backtest_{as_of.replace('-', '')}.csv"
    out.parent.mkdir(exist_ok=True)
    R.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n  明细已保存: {out.name}（UTF-8 BOM）")

    print()
    print("═" * 96)
    print("结论")
    print("═" * 96)
    ts = summarize(R["IC_trend_score"])
    if ts["t"] >= 2.0:
        verdict = "趋势档具备统计显著的正向预测力"
    elif ts["t"] >= 1.0:
        verdict = "趋势档预测力偏弱，未达常规显著水平"
    elif ts["t"] <= -1.0:
        verdict = "趋势档呈负向 —— 该区间动量实为反向指标"
    else:
        verdict = "趋势档接近随机（IC≈0）"
    print(f"  趋势综合分: IC={ts['IC']:.4f}, t={ts['t']:.2f} -> {verdict}")
    print(f"  ⚠ 幸存者偏差：已退市标的（WBA/ANSS/KCG/EA）不在池中，结果偏乐观")
    print(f"  ⚠ 基本面档（权重 80%）无法回测，本结论仅覆盖权重 20% 的动量档")

    if args.watch:
        n_alert = watch_report(R, args.recent,
                               PROJECT_ROOT / "reports" / "_datasets" / HISTORY_NAME)
        return 2 if n_alert else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
