# lifecycle: oneoff
# created: 2026-10-11
# serves: SKHY 2026-10-10
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_skhy_earnings.py
"""复算 SKHY 的 Q5 非经营收益闸门（铁律 42：验证断言必须自行复算）。

闸门报「非经营/非常规收益占净利 30%（TTM(4Q)）」⇒ 必须回答：
  ① 最近 4 个季度的 `Total Unusual Items` 逐季是多少（含正负）；
  ② TTM 求和是否真的 = 净利的 30%；
  ③ FY2025 年报口径的净额是多少（FY 是 **-8,516.3B**，负值 = 减少利润）；
  ④ 净额化（非经营收入 − 非常规项）后占净利多少。

只读，不写项目文件。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

KEYS = ["Total Unusual Items", "Net Non Operating Interest Income Expense",
        "Pretax Income", "Operating Income", "Net Income"]


def dump(df, title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    if df is None or getattr(df, "empty", True):
        print("  <空>")
        return
    cols = [str(c) for c in df.columns]
    print("  列（新→旧）:", ", ".join(cols))
    for k in KEYS:
        if k in df.index:
            vals = [df.loc[k, c] for c in df.columns]
            pretty = []
            for v in vals:
                try:
                    pretty.append(f"{float(v) / 1e9:,.1f}B")
                except Exception:  # noqa: BLE001
                    pretty.append(str(v))
            print(f"  {k:<46s} " + "  ".join(pretty))
        else:
            print(f"  {k:<46s} <该行不存在>")


def main() -> int:
    import yfinance as yf
    tk = yf.Ticker("SKHY")

    q = tk.quarterly_income_stmt
    dump(q, "季报 quarterly_income_stmt")

    a = tk.income_stmt
    dump(a, "年报 income_stmt")

    # --- TTM(4Q) 复算 ---
    print(f"\n{'=' * 78}\nQ5 闸门复算（与 _verify_earnings_quality.py 同口径）\n{'=' * 78}")
    if q is not None and not q.empty:
        def s(*names):
            for n in names:
                if n in q.index:
                    return q.loc[n]
            return None
        g = s("Total Unusual Items", "Gain On Sale Of Security",
              "Gain On Sale Of Business", "Special Income Charges")
        n = s("Net Income", "Net Income Common Stockholders")
        if g is not None and n is not None:
            gv = [float(x) for x in g.iloc[:4] if x == x]
            nv = [float(x) for x in n.iloc[:4] if x == x]
            print(f"  近 4 季 Total Unusual Items = {[f'{v/1e9:,.1f}B' for v in gv]}")
            print(f"  近 4 季 Net Income          = {[f'{v/1e9:,.1f}B' for v in nv]}")
            if nv and sum(nv) > 0:
                print(f"  Σgain = {sum(gv)/1e9:,.1f}B   Σni = {sum(nv)/1e9:,.1f}B   "
                      f"占比 = {sum(gv)/sum(nv)*100:.1f}%")
        no = s("Net Non Operating Interest Income Expense")
        if no is not None:
            ov = [float(x) for x in no.iloc[:4] if x == x]
            print(f"  近 4 季 Net Non Operating Interest Income Expense = "
                  f"{[f'{v/1e9:,.1f}B' for v in ov]}")
            if nv and sum(nv) > 0:
                print(f"  非经营收入项单独占比 = {sum(ov)/sum(nv)*100:.1f}%")
                if g is not None:
                    net = sum(ov) + sum(gv)
                    print(f"  ★ 净额化（非经营收入 + 非常规项）= {net/1e9:,.1f}B  "
                          f"占净利 {net/sum(nv)*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
