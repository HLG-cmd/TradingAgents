# lifecycle: oneoff
# created: 2026-10-11
# serves: SKHY 2026-10-10
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_skhy_history.py
"""铁律 24 探针：核实 SKHY 的 K 线根数与「200 日均线」的真伪。

判据（铁律 24 原文）：**指标窗口 > 可用天数时，数据源会用不足的数据算出一个看着正常的数。**
本探针要回答三件事：
  ① SKHY 日线到底有多少根、起止日期是什么（判断 NASDAQ 上市日）；
  ② `close_200_sma = 167.35` 是否等于**全部可用收盘价的算术均值**（误差 0.000 = 伪值）；
  ③ 快照的「52 周高/低 199.87 / 124.8」是否等于**上市以来高/低**。

只读、不写任何项目文件。
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import yfinance as yf

    tk = yf.Ticker("SKHY")
    for label, period in (("1y", "1y"), ("2y", "2y"), ("max", "max")):
        try:
            h = tk.history(period=period, interval="1d", auto_adjust=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{label}] 取数失败: {e}")
            continue
        if h is None or h.empty:
            print(f"[{label}] 空")
            continue
        closes = h["Close"].dropna()
        n = len(closes)
        first, last = closes.index[0], closes.index[-1]
        mean_all = closes.mean()
        print(f"[{label}] bars={n}  首={first:%Y-%m-%d}  末={last:%Y-%m-%d}  "
              f"末收={closes.iloc[-1]:.2f}")
        print(f"        全窗口收盘均值 = {mean_all:.4f}  |  窗口内高={closes.max():.2f} 低={closes.min():.2f}")
        if label == "2y":
            pass

    # --- 铁律 24 判定：伪 200 日均线 ---
    h = tk.history(period="max", interval="1d", auto_adjust=True)
    if h is not None and not h.empty:
        c = h["Close"].dropna()
        n = len(c)
        print("\n=== 判定 ===")
        print(f"可用交易日数 n = {n}")
        if n < 200:
            m = c.mean()
            print(f"n < 200 ⇒ 无法计算真实 200 日均线；")
            print(f"  全部 {n} 根收盘均值 = {m:.6f}")
            print(f"  证据包 close_200_sma = 167.350000（近似值 167.35）")
            if abs(m - 167.35) < 0.005:
                print("  ⇒ **误差 < 0.005，判定：close_200_sma 就是「上市以来均价」伪装成的 200 日均线（铁律 24 真阳性）**")
            else:
                print(f"  ⇒ 与 167.35 差 {abs(m - 167.35):.4f}，不能判定为全窗口均值，需另找口径")
            print(f"\n  「52 周高/低」判定：上市以来高={c.max():.2f} 低={c.min():.2f}")
            print(f"  证据包 52W High=199.87  Low=124.8")
            print(f"  ⇒ 高差 {abs(c.max() - 199.87):.2f} / 低差 {abs(c.min() - 124.8):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
