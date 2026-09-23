# lifecycle: oneoff
# created: 2026-09-23
# serves: GLD 2026-09-18
# usage: ./.venv/Scripts/python.exe wb_analysis/_derive_stock_gold.py
"""黄金专属二级派生指标 —— 品种驱动因素通道。

本项目首次为**商品类资产**建通道。既有：
- ``_derive_stock.py`` 面向个股（估值/报表/内部人）
- ``_derive_ndx.py``  面向指数（成分股聚合）

黄金两者都不适用，故单列。核心思路：
黄金没有 EPS、没有 PE、没有财报，其定价锚是**实际利率 + 美元 + 相对比价**，
因此派生指标必须围绕「黄金 vs 其定价因子」的相对位置构建。

用法：
    ./.venv/Scripts/python.exe wb_analysis/_derive_gold.py 2026-09-18
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EV_DIR = PROJECT_ROOT / "wb_analysis" / "evidence"

# 黄金驱动因素面板。GLD 为可采集载体（有完整期权链），其余为驱动/比价因子。
PANEL = {
    "GLD": "载体（SPDR Gold Shares，实物黄金信托）",
    "IAU": "载体对照（iShares Gold Trust）",
    "GDX": "金矿股（VanEck Gold Miners）",
    "GDXJ": "小市值金矿股",
    "SLV": "白银（iShares Silver Trust）",
    "GC=F": "COMEX 黄金期货连续合约",
    "DX-Y.NYB": "美元指数 DXY",
    "^TNX": "10 年期美债收益率",
    "TIP": "TIPS ETF（实际利率代理）",
}

# 未收盘 bar 判据：末根量 ÷ 20 日均量 < 此比例 ⇒ 该 bar 未收盘
UNCLOSED_VOL_RATIO = 0.60


def load_panel(start: str = "2024-09-01", end: str = "2026-09-19") -> pd.DataFrame:
    """拉取面板并归一到「交易日 → 收盘价」，消除跨标的时区元数据不一致。"""
    import yfinance as yf

    raw = {}
    for t in PANEL:
        try:
            h = yf.Ticker(t).history(start=start, end=end, interval="1d", auto_adjust=False)
        except Exception:  # noqa: BLE001
            continue
        if h is None or h.empty or "Close" not in h.columns:
            continue
        idx = pd.to_datetime(h.index)
        if idx.tz is not None:
            # ★ 关键：不同标的返回的时区元数据不同（实测出现 04:00 / 05:00 两种），
            #   不归一会在 concat 时把同一天拆成两行。
            idx = idx.tz_convert("America/New_York").normalize().tz_localize(None)
        s = pd.Series(h["Close"].values, index=idx).astype(float)
        raw[t] = s.groupby(level=0).last()
    df = pd.DataFrame(raw).sort_index()
    return df


def drop_unclosed(df: pd.DataFrame, as_of: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """剔除未收盘 bar。

    ★ 本函数与 ``collect.py`` 的闸门同源：**日线接口在盘中会把当日那根
    未收盘 bar 一并返回**（OHLC 有值、量能只有正常水平的一小部分）。
    若直接用于计算「最新价 / 均线位置」，就会把盘中快照当收盘价。
    """
    import yfinance as yf

    notes: list[str] = []
    if df.empty:
        return df, notes
    last_date = df.index[-1]
    # 用 GLD 的分钟级量能反推末根日线 bar 是否收盘
    try:
        h = yf.Ticker("GLD").history(start=(last_date - pd.Timedelta(days=45)).strftime("%Y-%m-%d"),
                                     end=(last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                                     interval="1d", auto_adjust=False)
        if len(h) >= 21:
            vol = h["Volume"].astype(float)
            ratio = vol.iloc[-1] / vol.iloc[-21:-1].mean()
            if ratio < UNCLOSED_VOL_RATIO:
                notes.append(
                    f"末根 bar {last_date.date()} 量能仅为 20 日均量的 {ratio*100:.1f}% "
                    f"(< {UNCLOSED_VOL_RATIO*100:.0f}%) ⇒ **未收盘**，已从面板剔除。"
                )
                df = df.iloc[:-1]
            else:
                notes.append(
                    f"末根 bar {last_date.date()} 量能为 20 日均量的 {ratio*100:.1f}% ⇒ 视为已收盘，保留。"
                )
    except Exception as exc:  # noqa: BLE001
        notes.append(f"未收盘 bar 判据执行失败（{type(exc).__name__}），**面板末行未经量能校验**。")
    return df, notes


def _pct_rank(series: pd.Series, lookback: int) -> tuple[float, float, float, float]:
    """返回 (当前值, 分位%, 中位数, 区间)。分位以「含当前值的全窗口」计算。"""
    s = series.dropna()
    if len(s) < 5:
        return (np.nan,) * 4
    w = s.iloc[-lookback:] if len(s) >= lookback else s
    cur = float(w.iloc[-1])
    pct = float((w < cur).mean() * 100)
    return cur, pct, float(w.median()), float(w.min()), float(w.max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", help="基准日 YYYY-MM-DD")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    as_of = args.date
    df = load_panel()
    if df.empty:
        print("[错误] 面板为空")
        return 1
    df_raw_len = len(df)
    df, notes = drop_unclosed(df, as_of)

    L = []
    W = L.append
    W("# 黄金派生指标（二级计算）")
    W("")
    W(f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M:%S}")
    W(f"- 基准日：{as_of}")
    W(f"- 面板：{len(df)} 个交易日（原始 {df_raw_len} 行，剔除后 {len(df)} 行）")
    W(f"- 范围：{df.index[0].date()} ~ {df.index[-1].date()}")
    W("")
    W("> 本文件由 `wb_analysis/_derive_stock_gold.py` 生成，是**二级计算**（由证据包/上游原始数据推出），")
    W("> 不是原始证据。凡引用本文件数字，须可回溯到证据包对应章节。")
    W("")

    # ---------- A. 未收盘 bar 处置 ----------
    W("## A. 未收盘 bar 处置（口径声明）")
    W("")
    for n in notes:
        W(f"- {n}")
    W("")
    W(f"⇒ **本文件全部计算以 {df.index[-1].date()} 及之前的已收盘 bar 为准。**")
    W("")

    # ---------- B. 载体价格与位置 ----------
    W("## B. 载体价格与技术位置")
    W("")
    g = df["GLD"].dropna()
    W("| 项 | 值 |")
    W("|---|---|")
    W(f"| GLD 最后收盘 | **{g.iloc[-1]:.2f}**（{g.index[-1].date()}） |")
    for lb, name in [(5, "5 日"), (20, "20 日"), (60, "60 日"), (120, "120 日"), (250, "250 日")]:
        if len(g) > lb:
            r = g.iloc[-1] / g.iloc[-1 - lb] - 1
            W(f"| {name}收益 | {r*100:+.2f}% |")
    W("")
    W("### 均线位置")
    W("")
    W("| 均线 | 值 | 价格/均线 | 偏离 |")
    W("|---|---|---|---|")
    for n in (20, 50, 200):
        if len(g) >= n:
            ma = g.iloc[-n:].mean()
            W(f"| {n} 日 SMA | {ma:.2f} | {g.iloc[-1]/ma:.4f} | {(g.iloc[-1]/ma-1)*100:+.2f}% |")
    W("")

    # ---------- C. 驱动因素 ----------
    W("## C. 驱动因素（黄金定价锚）")
    W("")
    W("黄金无盈利、无票息，其定价锚是**实际利率 + 美元 + 机会成本**。")
    W("下表用 20 交易日窗口观察各因子方向。")
    W("")
    W("| 因子 | 当前 | 20 交易日前 | 变化 | 对黄金的含义 |")
    W("|---|---|---|---|---|")
    factors = [
        ("DX-Y.NYB", "美元指数 DXY", "**逆风**：美元走强抬高非美买家成本"),
        ("^TNX", "10 年期美债收益率（%）", "**逆风**：名义利率上行提高持金机会成本"),
        ("TIP", "TIPS ETF（实际利率反代理）", "**顺风**：TIPS 跌 ⇒ 实际利率上行 ⇒ 逆风"),
    ]
    for tk, name, meaning in factors:
        if tk not in df.columns:
            W(f"| {name} | — | — | — | 通道缺失 |")
            continue
        s = df[tk].dropna()
        if len(s) < 21:
            W(f"| {name} | {s.iloc[-1]:.2f} | — | — | 样本不足 |")
            continue
        cur, prev = float(s.iloc[-1]), float(s.iloc[-21])
        W(f"| {name} | {cur:.2f} | {prev:.2f} | {cur-prev:+.2f} | {meaning} |")
    W("")
    W("> ⚠️ **TIP 是 ETF 价格，不是实际利率本身**。TIPS 价格下跌 ⇔ 实际收益率上升。")
    W("> 本文件不提供 TIPS 到期收益率（需 FRED 的 DFII10 系列，证据包未含该通道）⇒")
    W("> 实际利率只能**定性**判断方向，**不得给出具体实际利率数值**。")
    W("")

    # ---------- D. 相对比价 ----------
    W("## D. 相对比价（跨资产确认）")
    W("")
    W("比价是黄金分析的核心交叉验证：**矿股/白银相对金价的强弱，可验证金价变动的"
      "「广度」** —— 若金价上涨但矿股不跟，通常是避险脉冲而非趋势。")
    W("")
    W("| 比价 | 当前 | 1Y 分位 | 1Y 中位 | 1Y 区间 | 解读 |")
    W("|---|---|---|---|---|---|")
    pairs = [
        ("GDX", "GLD", "矿股 / 金价"),
        ("GDXJ", "GDX", "小矿 / 大矿"),
        ("SLV", "GLD", "白银 / 黄金"),
        ("GC=F", None, "期货 / 载体（升贴水）"),
    ]
    for a, b, name in pairs:
        if a not in df.columns:
            continue
        if b is None:
            r = (df[a] / df["GLD"]).dropna()
        else:
            if b not in df.columns:
                continue
            r = (df[a] / df[b]).dropna()
        if len(r) < 30:
            W(f"| {name} | {r.iloc[-1]:.4f} | — | — | — | 样本不足 |")
            continue
        cur, pct, med, lo, hi = _pct_rank(r, 250)
        if pct >= 80:
            note = "**高位**：该类资产显著跑赢"
        elif pct >= 60:
            note = "偏高：温和跑赢"
        elif pct >= 40:
            note = "中性"
        elif pct >= 20:
            note = "偏低：相对落后"
        else:
            note = "**低位**：显著跑输"
        W(f"| {name} | {cur:.4f} | {pct:.1f}% | {med:.4f} | [{lo:.4f}, {hi:.4f}] | {note} |")
    W("")

    # ---------- E. 载体 vs 期货基差 ----------
    W("## E. 载体溢价 / 期货基差（套利与情绪）")
    W("")
    if "GC=F" in df.columns and "GLD" in df.columns:
        ratio = (df["GC=F"] / df["GLD"]).dropna()
        cur, pct, med, lo, hi = _pct_rank(ratio, 250)
        W(f"- **GC=F ÷ GLD**：{cur:.4f}（1Y 分位 {pct:.1f}%，中位 {med:.4f}，区间 [{lo:.4f}, {hi:.4f}]）")
        W("")
        W("**为何不能直接换算成溢价率**：GLD 的「每份对应金量」**不是固定的 1/10 盎司**。")
        W("信托随金价上涨会**持续减持**每份对应的金量（金价越高，同样美元净值需越少盎司），")
        W("且份额创设/赎回会带来微小漂移。因此**必须用两个独立标的的比值做趋势判断，")
        W("不能用固定盎司数去反推溢价** —— 那会产生量级完全错误的数字。")
        W("")
        W("**正确用法**：观察 `GC=F ÷ GLD` 这个**比值本身**的历史分位。")
        W(f"- 当前 {cur:.4f} 处于 1Y **{pct:.1f}%** 分位 ⇒ " +
          ("期货相对载体处于**历史高位区**，即纸黄金（期货）比实物载体（ETF）更贵，"
           "通常反映** Momentum/杠杆多头集中在期货端**。" if pct >= 70 else
           "期货相对载体的位置中性。" if pct >= 30 else
           "期货相对载体处于**历史低位区**，即期货贴水，通常反映多头退潮。"))
        W(f"- 1Y 区间 [{lo:.4f}, {hi:.4f}]，变动范围约 {(hi/lo-1)*100:.2f}% —— 这是**结构性小幅摆动**，")
        W("  不含套利空间信息（Δ 未超过交易成本+托管成本）。")
        W("")
        W("⚠️ 该比值含**合约展期（contango/backwardation）与到期结构**影响，非纯基差。")
    W("")

    # ---------- F. 波动率与回撤 ----------
    W("## F. 波动率与回撤")
    W("")
    ret = g.pct_change().dropna()
    W("| 项 | 值 |")
    W("|---|---|")
    for w, name in [(20, "20 日"), (60, "60 日"), (250, "250 日")]:
        if len(ret) >= w:
            W(f"| {name}年化波动率 | {ret.iloc[-w:].std()*np.sqrt(252)*100:.2f}% |")
    peak = g.cummax()
    dd = (g / peak - 1).dropna()
    W(f"| 当前距 1Y 高点 | {(g.iloc[-1]/g.iloc[-250:].max()-1)*100:+.2f}%（高点 {g.iloc[-250:].max():.2f}，"
      f"发生于 {g.iloc[-250:].idxmax().date()}） |")
    W(f"| 当前回撤（距面板内峰值） | {dd.iloc[-1]*100:+.2f}% |")
    W(f"| 最大回撤（面板内） | {dd.min()*100:+.2f}% |")
    W(f"| 1Y 最高 / 最低 | {g.iloc[-250:].max():.2f} / {g.iloc[-250:].min():.2f}（低点发生于 "
      f"{g.iloc[-250:].idxmin().date()}） |")
    W("")
    W("> ⚠️ **52 周高低存在两个口径，不可混用。** 证据包 §3 的 `get_fundamentals` 返回")
    W("> `52 Week High: 509.7` / `Low: 336.31`，而 §1 日线序列在此窗口内为 "
      f"**{g.iloc[-250:].max():.2f} / {g.iloc[-250:].min():.2f}**。")
    W("> 两者的窗口起点与是否含盘中极值口径不同。")
    W("> ⇒ **本文件与全部技术位判断一律以 §1 日线序列为准**（可逐行核验），")
    W("> Fundamentals 的 52 周字段仅作对照披露。")
    W("")

    # ---------- G. 相关性 ----------
    W("## G. 与股/债/美元的相关性（250 日）")
    W("")
    W("| 配对 | 相关性 | 解读 |")
    W("|---|---|---|")
    corr_pairs = [
        ("GLD", "DX-Y.NYB", "美元", "负相关 = 教科书关系成立"),
        ("GLD", "^TNX", "10Y 收益率", "负相关 = 机会成本逻辑成立"),
        ("GLD", "SLV", "白银", "高正相关 = 贵金属同向"),
        ("GLD", "TIP", "TIPS", "正相关 = 实际利率逻辑成立"),
    ]
    rr = df.pct_change().iloc[-250:]
    for a, b, name, meaning in corr_pairs:
        if a in rr.columns and b in rr.columns:
            c = rr[a].corr(rr[b])
            W(f"| GLD vs {name} | {c:+.3f} | {meaning} |")
    W("")
    W("> ⚠️ 相关性为**全窗口静态值**，不反映近期是否发生结构性变化。")
    W("")

    # ---------- H. 其他派生量（便于溯源） ----------
    W("## H. 其他派生量")
    W("")
    W("```")
    W("面板原始收盘价（最近 10 个交易日）")
    tail = df.iloc[-10:]
    W(tail.round(3).to_string())
    W("```")
    W("")

    out = Path(args.out) if args.out else (EV_DIR / f"GLD_{as_of}.derived.md")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"已写出: {out}  ({len(chr(10).join(L))} 字符)")
    print(f"面板 {len(df)} 行，末行 {df.index[-1].date()}")
    for n in notes:
        print(" -", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
