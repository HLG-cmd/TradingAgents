# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_rv_and_adjust_probe.py
"""GOOG 已实现波动率（RV）与「复权价 vs 未调整价」诊断。

用途：
  1. 给报告提供与 §11 期权 IV 对照的已实现波动率（10/20/30/60/90 日，年化）。
  2. 解释 Nasdaq 官方 close 与证据包 §1 close 之间那笔**恒定 0.22 美元**的差
     —— 验证它是否来自 yfinance `history()` 的默认 auto_adjust=True（股息复权）。

用法: ./.venv/Scripts/python.exe wb_analysis/_rv_and_adjust_probe.py GOOG
"""
import math
import sys

import yfinance as yf


def realized_vol(series, n):
    clean = series.dropna()
    closes = list(clean)[-(n + 1):]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "GOOG"
    t = yf.Ticker(ticker)

    adj = t.history(period="1y", interval="1d", auto_adjust=True)
    raw = t.history(period="1y", interval="1d", auto_adjust=False)

    print("[probe] ===== 1) 已实现波动率（基于复权收盘，年化）=====")
    for n in (10, 20, 30, 60, 90):
        v = realized_vol(adj["Close"], n)
        print(f"  RV{n:<3d} = {v:.2f}%" if v is not None else f"  RV{n}: 数据不足")
    print(f"  最后一根 bar 日期 = {adj.index[-1].date()}")

    print("\n[probe] ===== 2) 复权价 vs 未调整价（最近 12 个交易日）=====")
    joined = adj[["Close"]].join(raw[["Close"]], how="inner", lsuffix="_adj", rsuffix="_raw")
    print(f"{'date':>12} {'adj':>10} {'raw':>10} {'diff':>8}")
    for idx, row in joined.tail(12).iterrows():
        d = row["Close_adj"] - row["Close_raw"]
        print(f"{str(idx.date()):>12} {row['Close_adj']:>10.3f} {row['Close_raw']:>10.3f} {d:>+8.3f}")

    print("\n[probe] ===== 3) 分红记录（最近 6 次）=====")
    try:
        div = t.dividends
        if len(div) == 0:
            print("  （无分红记录）")
        else:
            for idx, val in div.tail(6).items():
                print(f"  {idx.date()}  {val}")
    except Exception as exc:  # noqa: BLE001
        print(f"  取分红失败: {exc!r}")

    print("\n[probe] ===== 4) 结论性判据 =====")
    diffs = (joined["Close_adj"] - joined["Close_raw"]).round(3)
    pos = diffs[diffs != 0]
    if len(pos) == 0:
        print("  复权价与未调整价完全一致 ⇒ 无股息复权影响")
    else:
        last_zero = diffs[diffs == 0]
        print(f"  存在差异的交易日 {len(pos)} 个；差异取值 = {sorted(set(pos.tolist()))}")
        print(f"  最后一次存在差异的日期 = {pos.index[-1].date()}")
        if len(last_zero) and last_zero.index[0] > pos.index[-1]:
            print(f"  此后首个一致日期 = {last_zero.index[0].date()} ⇒ 除息日应落在这两天之间")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
