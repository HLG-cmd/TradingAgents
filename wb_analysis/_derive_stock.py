# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_derive_stock.py
"""个股派生指标计算器：从个股证据包导出所有「需要算术推导」的二级指标。

与 `_derive_ndx.py` 对应，但面向个股：多出财务报表比率（增速、利润率、
现金流质量、资产负债健康度）这一整块。全部输入来自
`wb_analysis/evidence/<TICKER>_<date>.md`，不产生任何新数据。

用法：
    python wb_analysis/_derive_stock.py GOOG 2026-09-16 [GOOGL 2026-09-16 ...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "wb_analysis" / "evidence"


def parse_statement(md: str, idx: int) -> dict[str, list[float | None]]:
    """从 §4.x 的代码块里解析报表为 {行名: [各期数值]}（列序与表头一致，新期在前）。"""
    m = re.search(rf"## 4\.{idx} .*?\n\n```\n(.*?)\n```", md, re.S)
    if not m:
        return {}
    rows: dict[str, list[float | None]] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split(",")
        name = parts[0].strip()
        if not name or name.startswith("20") or set(name) <= set("0123456789-"):
            continue  # 期间表头行
        vals: list[float | None] = []
        for p in parts[1:]:
            p = p.strip()
            try:
                vals.append(float(p))
            except ValueError:
                vals.append(None)
        if vals:
            rows[name] = vals
    return rows


def g(rows: dict, name: str, i: int = 0):
    v = (rows.get(name) or [None] * (i + 1))
    return v[i] if i < len(v) else None


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return (a / b - 1) * 100


def bn(x, unit="B"):
    return "n/a" if x is None else f"{x / 1e9:,.1f}{unit}"


def report(ticker: str, date: str) -> None:
    p = EV / f"{ticker}_{date}.md"
    if not p.exists():
        print(f"✗ 找不到 {p}")
        return
    md = p.read_text(encoding="utf-8")
    print("=" * 78)
    print(f"{ticker}  基准日 {date}")
    print("=" * 78)

    # ---------- 行情与指标 ----------
    def stat(key: str):
        m = re.search(rf"-\s*{key}:\s*([-\d.]+)", md)
        return float(m.group(1)) if m else None

    close = stat("latest_close")

    def series(name: str) -> list[tuple[str, float]]:
        m = re.search(rf"### {re.escape(name)}\n```\n(.*?)\n```", md, re.S)
        if not m:
            return []
        out = []
        for line in m.group(1).splitlines():
            mm = re.match(r"^(\d{4}-\d{2}-\d{2}):\s*(-?[\d.]+)$", line.strip())
            if mm:
                out.append((mm.group(1), float(mm.group(2))))
        return out

    ind_latest_date = series("close_50_sma")
    ind_latest_date = ind_latest_date[0][0] if ind_latest_date else "?"

    # ★★ 2026-09-23 修**贴错标签 + 用过时字段**两处缺陷：
    #   ① 原写法 `收盘 {close} @ {date}` 里 `date` 是**命令行基准日**，不是该收盘价真实日期；
    #   ② `close` 取证据包 L16 的 `latest_close`，而它**持有的是日线末日（可能已过时）的收盘**，
    #      不等于 §13「最新交易日实时收盘补充」里的 `regularMarketPrice`。
    #   实测 GOOG_2026-09-22：latest_close=350.87（实为 9/21），§13 regularMarketPrice=347.41（9/22 收盘），
    #   而 §13 的 regularMarketPreviousClose 正是 350.87 —— 三方印证 latest_close 属 9/21。
    #   ⇒ 必须同时打印「日线末日收盘」与「最新交易日实时收盘」两个数，并显式告警，交由下游选择。
    m_rt = re.search(r"regularMarketPrice`?\*{0,2}\s*=\s*\*{0,2}([\d.]+)", md)
    m_rtd = re.search(r"实时字段所属常规交易时段：\*{0,2}(\d{4}-\d{2}-\d{2})", md)
    rt_px = float(m_rt.group(1)) if m_rt else None
    rt_date = m_rtd.group(1) if m_rtd else None
    print(f"\nA. 价格位置（日线末日收盘 {close} @ {ind_latest_date}；指标最新 {ind_latest_date}）")
    if rt_px is not None and rt_date:
        delta = (rt_px / close - 1) * 100 if close else 0.0
        print(f"   ★ 最新交易日（§13 实时字段）：{rt_date} 收盘 **{rt_px}**（相对日线末日 {close} 为 {delta:+.2f}%）")
        if rt_date != ind_latest_date:
            print(f"   ⚠️ **口径提示**：日线末日（{ind_latest_date}）比最新交易日（{rt_date}）**旧 1 个交易日**。")
            print(f"      ⇒ **价格类引用（现价/涨跌/赔率/止损）用 {rt_px}（{rt_date}）**；"
                  f"**技术指标用日线末日（{ind_latest_date}）口径**。两者**不可混用**（铁律 4）。")
            print(f"      ⇒ 下表「距现价」一列**按日线末日 {close} 计算**；若要用最新价，请以 ({rt_px} ÷ 指标值 − 1) 自行重算。")
    if ind_latest_date != date:
        print(f"   ⚠️ 日线末日（{ind_latest_date}）≠ 命令行基准日（{date}）：该收盘价属于 **{ind_latest_date}**。")
    IND = {k: (series(k)[0][1] if series(k) else None) for k in
           ("close_50_sma", "close_200_sma", "close_10_ema", "vwma", "boll", "boll_ub", "boll_lb")}
    for k, v in IND.items():
        if v:
            print(f"  {k:<13} {v:>9.2f}   距现价 {(close / v - 1) * 100:+.3f}%")
    for k, key in (("52W HIGH", "high_52w"), ("52W LOW", "low_52w")):
        v = stat(key)
        if v:
            print(f"  {k:<13} {v:>9.2f}   距现价 {(close / v - 1) * 100:+.3f}%")

    bu, bm, bl = IND["boll_ub"], IND["boll"], IND["boll_lb"]
    if bu and bl and bm:
        band = bu - bl
        print(f"\n  布林带宽 {band:.2f} = {band / bm * 100:.3f}%（中轨口径）")
        print(f"  现价在带内位置 {(close - bl) / band * 100:.2f}%（0=下轨 100=上轨）")
        print(f"  距下轨 {close - bl:+.2f}（{(close / bl - 1) * 100:+.3f}%）| "
              f"距上轨 {bu - close:+.2f}（{(close / bu - 1) * 100:+.3f}%）")
    atr = IND.get("atr") or (series("atr")[0][1] if series("atr") else None)
    if atr:
        print(f"  ATR {atr:.2f} = 现价的 {atr / close * 100:.3f}%")
    print(f"  收益 5日 {stat('ret_5d')}% | 20日 {stat('ret_20d')}% | "
          f"60日 {stat('ret_60d')}% | 120日 {stat('ret_120d')}%")

    print("\nB. 最近 3 根 K 线")
    rows = []
    for line in md.splitlines():
        mm = re.match(r"^(\d{4}-\d{2}-\d{2})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)$",
                      line.strip())
        if mm:
            rows.append((mm.group(1), *[float(x) for x in mm.groups()[1:]]))
    prev = rows[-4][4] if len(rows) >= 4 else None
    for d, o, h, lo, c, v in rows[-3:]:
        rng = h - lo
        chg = f"{(c / prev - 1) * 100:+.2f}%" if prev else " n/a"
        print(f"  {d} 收 {c:>8.2f} 日涨跌 {chg:>7} 振幅 {rng:>6.2f} "
              f"收盘位于日内 {(c - lo) / rng * 100:>5.1f}%  量 {v / 1e6:>7.2f}M")
        prev = c
    av = stat("avg_vol_20d")
    if av:
        print(f"  20 日均量 {av / 1e6:.2f}M")

    print("\nC. 均线斜率 / MACD / RSI")
    for nm in ("close_50_sma", "close_200_sma", "close_10_ema"):
        s = series(nm)
        if len(s) >= 2:
            n = len(s) - 1
            print(f"  {nm:<13} {s[-1][0]} {s[-1][1]:>9.2f} → {s[0][0]} {s[0][1]:>9.2f}"
                  f"  变化 {s[0][1] - s[-1][1]:+.2f} / {n} 交易日 = {(s[0][1] - s[-1][1]) / n:+.2f}/日")
    m_, s_, h_ = series("macd"), series("macds"), series("macdh")
    for i in range(len(m_) - 1, -1, -1):
        print(f"  {m_[i][0]}  MACD {m_[i][1]:>8.3f}  Signal {s_[i][1]:>8.3f}  Hist {h_[i][1]:>8.3f}")
    if m_:
        print(f"  → MACD {'已跌破零轴' if m_[0][1] < 0 else '在零轴上方'}"
              f"（{m_[-1][1]:+.3f} → {m_[0][1]:+.3f}）")
    rs = series("rsi")
    if rs:
        print("  RSI: " + " | ".join(f"{d[5:]} {v:.2f}" for d, v in reversed(rs)))

    # ---------- 基本面快照 ----------
    print("\nD. 估值快照（§3）+ 口径校验")
    snap = {}
    for key in ("Market Cap", "PE Ratio (TTM)", "Forward PE", "PEG Ratio", "Price to Book",
                "EPS (TTM)", "Forward EPS", "Dividend Yield", "Beta", "Revenue (TTM)",
                "Net Income", "Profit Margin", "Operating Margin", "Return on Equity",
                "Return on Assets", "Debt to Equity", "Current Ratio", "Book Value",
                "Free Cash Flow", "Gross Profit"):
        m = re.search(rf"^{re.escape(key)}:\s*([-\d.]+)", md, re.M)
        if m:
            snap[key] = float(m.group(1))
    for k, v in snap.items():
        print(f"  {k:<22} {v:,.4f}")
    if snap.get("PE Ratio (TTM)") and snap.get("EPS (TTM)"):
        print(f"  ⇒ PE(TTM) × EPS(TTM) = "
              f"{snap['PE Ratio (TTM)'] * snap['EPS (TTM)']:.2f}（应≈收盘 {close}）")
    if snap.get("PE Ratio (TTM)") and snap.get("Forward PE"):
        print(f"  ⇒ Forward PE {'高于' if snap['Forward PE'] > snap['PE Ratio (TTM)'] else '低于'}"
              f" PE(TTM) —— 前瞻{'更贵' if snap['Forward PE'] > snap['PE Ratio (TTM)'] else '更便宜'}")

    # ---------- 财务报表 ----------
    print("\nE. 三大报表（FY，最新期在前）")
    inc = parse_statement(md, 1)
    bal = parse_statement(md, 2)
    cfs = parse_statement(md, 3)
    if inc:
        print("  利润表:")
        for name, fmt in (("Total Revenue", bn), ("Cost Of Revenue", bn), ("Gross Profit", bn),
                          ("Research And Development", bn), ("Operating Income", bn),
                          ("Pretax Income", bn), ("Net Income", bn),
                          ("Diluted EPS", lambda x: "n/a" if x is None else f"{x:.2f}")):
            v0, v1 = g(inc, name, 0), g(inc, name, 1)
            if v0 is not None:
                print(f"    {name:<34} {fmt(v0):>12}   YoY {pct(v0, v1) if pct(v0, v1) is None else f'{pct(v0, v1):+.2f}%'}")
        rev0 = g(inc, "Total Revenue", 0)
        gp0, oi0, ni0 = g(inc, "Gross Profit", 0), g(inc, "Operating Income", 0), g(inc, "Net Income", 0)
        if rev0:
            print(f"    毛利率 {gp0 / rev0 * 100:.2f}%  营业利润率 {oi0 / rev0 * 100:.2f}%  "
                  f"净利率 {ni0 / rev0 * 100:.2f}%")
    if bal:
        print("  资产负债表:")
        ta, tl_c, tl_nc = g(bal, "Total Assets", 0), g(bal, "Current Liabilities", 0), \
            g(bal, "Total Non Current Liabilities Net Minority Interest", 0)
        eq = g(bal, "Stockholders Equity", 0)
        for name in ("Total Assets", "Current Assets", "Cash And Cash Equivalents",
                     "Cash Cash Equivalents And Short Term Investments", "Accounts Receivable",
                     "Net PPE", "Goodwill", "Current Liabilities",
                     "Total Non Current Liabilities Net Minority Interest",
                     "Long Term Debt", "Total Debt", "Stockholders Equity",
                     "Retained Earnings", "Working Capital"):
            v0, v1 = g(bal, name, 0), g(bal, name, 1)
            if v0 is not None:
                print(f"    {name:<50} {bn(v0):>12}   YoY {pct(v0, v1) if pct(v0, v1) is None else f'{pct(v0, v1):+.2f}%'}")
        if ta and tl_c is not None and tl_nc is not None and eq:
            tl = tl_c + tl_nc
            print(f"    ⇒ 总负债 {bn(tl)}，资产负债率 {tl / ta * 100:.2f}%，"
                  f"权益 {bn(eq)}  →  L+E = {bn(tl + eq)} vs 总资产 {bn(ta)}"
                  f"（差 {abs(tl + eq - ta) / ta * 100:.3f}%，≈0 即报表自洽）")
            print(f"    ⇒ 负债/权益 = {tl / eq:.3f} 倍（若快照的 Debt to Equity 是百分数需除以 100 对照）")
    if cfs:
        print("  现金流量表:")
        for name in ("Operating Cash Flow", "Capital Expenditure", "Free Cash Flow",
                     "Net Income From Continuing Operations", "Repurchase Of Capital Stock",
                     "Cash Dividends Paid", "Issuance Of Debt", "Repayment Of Debt",
                     "End Cash Position"):
            v0, v1 = g(cfs, name, 0), g(cfs, name, 1)
            if v0 is not None:
                print(f"    {name:<44} {bn(v0):>12}   YoY {pct(v0, v1) if pct(v0, v1) is None else f'{pct(v0, v1):+.2f}%'}")
        ocf, capex, fcf = (g(cfs, "Operating Cash Flow", 0), g(cfs, "Capital Expenditure", 0),
                           g(cfs, "Free Cash Flow", 0))
        ni0 = g(inc, "Net Income", 0) if inc else None
        if ocf and ni0:
            print(f"    ⇒ 现金流质量 OCF/净利 = {ocf / ni0:.3f}（>1 说明利润有现金支撑）")
        if fcf and ni0:
            print(f"    ⇒ FCF/净利 = {fcf / ni0:.3f}")
        if capex and ocf:
            print(f"    ⇒ 资本开支/OCF = {abs(capex) / ocf * 100:.1f}%")

    # ---------- 内部人 ----------
    print("\nF. 内部人交易")
    ins = re.search(r"## 8\. 内部人交易\n(.*?)(?=\n## |\Z)", md, re.S)
    if ins:
        body = ins.group(1).strip()
        print("\n".join("  " + l.strip() for l in body.splitlines()[:22] if l.strip()))
    else:
        print("  (无该章节)")

    # ---------- 通道健康度 ----------
    h = re.search(r"## 通道健康度\n(.*?)$", md, re.S)
    if h:
        print("\nG. " + h.group(1).strip().replace("\n", "\n"))
    print("=" * 78)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    pairs = [(sys.argv[1], sys.argv[2])]
    if len(sys.argv) >= 5:
        pairs.append((sys.argv[3], sys.argv[4]))
    for t, d in pairs:
        report(t, d)
