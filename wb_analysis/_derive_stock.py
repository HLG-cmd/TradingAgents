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

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "wb_analysis" / "evidence"

# ── 铁律 24 自检表：指标名 → 该指标**声称**的窗口长度（单位：K 线根数）──────
#   症状（2026-10-11 SKHY 实测，**第二次真阳性**；首次 AVGO）：
#   上市仅 65 个交易日，数据源仍返回 `close_200_sma = 167.35`，而该值恰等于
#   「全部 65 根收盘的算术均值」167.352923（误差 < 0.005）
#   ⇒ 所谓「200 日均线」实为「上市以来均价」——把 expanding mean 冒充固定窗口。
#   判据不是「值看起来怪」，而是**算术上不可能**：窗口 200 > 可用根数 65。
#   ⇒ 拿到新上市标的第一件事是数 K 线根数；本表把它变成机器动作。
#   ⚠️ 窗口值必须能从指标名直接读出，不得凭印象填：
#      close_50_sma / close_200_sma / close_10_ema 由名字给出 ⇒ 命中即「真阳性」；
#      boll 族与 vwma 取**源默认口径 20**，atr/rsi 取经典 14 ⇒ 命中只报「疑似」。
IND_WINDOW: dict[str, int] = {
    "close_50_sma": 50,
    "close_200_sma": 200,
    "close_10_ema": 10,
    "vwma": 20,
    "boll": 20,
    "boll_ub": 20,
    "boll_lb": 20,
    "atr": 14,
    "rsi": 14,
}
# 窗口由名字直接给出的指标：命中即为**确定**的伪指标，而非疑似
IND_WINDOW_HARD = {"close_50_sma", "close_200_sma", "close_10_ema"}


def parse_bars(md: str) -> list[tuple]:
    """从 K 线表解析 ``(date, open, high, low, close, volume)``。

    全文只解析一次（供铁律 24 自检与 B/C 段复用），避免多处扫描产生漂移。
    """
    rows: list[tuple] = []
    for line in md.splitlines():
        mm = re.match(
            r"^(\d{4}-\d{2}-\d{2})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)$",
            line.strip())
        if mm:
            rows.append((mm.group(1), *[float(x) for x in mm.groups()[1:]]))
    return rows


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

    # ★ K 线表只在全文解析一次（B/C 段与铁律 24 自检复用），避免多处扫描漂移
    rows = parse_bars(md)

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
            diff = close - v
            pct_diff = (close / v - 1) * 100
            print(f"  {k:<13} {v:>9.2f}   距现价 {diff:+8.2f} ({pct_diff:+.3f}%)")
    for k, key in (("52W HIGH", "high_52w"), ("52W LOW", "low_52w")):
        v = stat(key)
        if v:
            diff = close - v
            pct_diff = (close / v - 1) * 100
            print(f"  {k:<13} {v:>9.2f}   距现价 {diff:+8.2f} ({pct_diff:+.3f}%)")

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

    # ── 铁律 24 自检：可用 K 线根数 vs 指标窗口 ──────────────────────────
    #   ⚠️ 根数**必须**取自 §1 的 `- bars:` 字段，不能用 K 线表行数：
    #      证据包 §1 只显示「最近 20 根 K 线」，指标序列也只给最近 5 个点 ——
    #      拿表长当根数会让**所有**标的都误报（20 < 50/200）。
    #   ★ 2026-10-12 修：原实现「缺 `bars:` 字段就退回 `len(rows)`」是个**假阳性源** ——
    #      旧版证据包（如 GOOG_2026-10-10）确实没有该字段，而表恒为 20 行
    #      ⇒ 会对**长历史标的**报出「50 日线、200 日线都不存在」的假警报。
    #      故改为三态：有字段 ⇒ 用它；无字段但表带截断标记 ⇒ **无法判定，明确跳过**；
    #      无字段且无截断标记 ⇒ 才可用表长（视表为完整）。
    _barsf = stat("bars")
    _trunc = re.search(r"最近\s*(\d+)\s*根\s*K\s*线", md)
    n_bars: int | None
    if _barsf:
        n_bars = int(_barsf)
        _bars_src = "§1 `- bars:` 字段"
    elif _trunc and int(_trunc.group(1)) == len(rows):
        n_bars = None
        _bars_src = f"**不可判定**（缺 `bars:` 字段，且 K 线表被截断为 {len(rows)} 行）"
    else:
        n_bars = len(rows)
        _bars_src = f"K 线表行数 {len(rows)}（无截断标记，视为完整）"

    def _confirm_expanding_mean(name: str) -> tuple[int, bool] | None:
        """用 expanding-mean 反算校验：若序列是累加均值 E_n=S_n/n，则
        ``close_n = E_n·n − E_{n−1}·(n−1)``。反算出的收盘若与 K 线表吻合，
        即证实该序列是「上市以来均价」而非固定窗口均线。
        返回 (参与比对的点数, 是否全部吻合)，无法比对时返回 None。
        """
        s = series(name)          # 新 → 旧
        if len(s) < 2 or not rows:
            return None
        table = {r[0]: r[4] for r in rows}
        hits: list[tuple[float, float]] = []
        for i in range(len(s) - 1):
            n, m = n_bars - i, n_bars - i - 1
            if n <= 0 or m <= 0 or s[i][0] not in table:
                continue
            hits.append((s[i][1] * n - s[i + 1][1] * m, table[s[i][0]]))
        if not hits:
            return None
        ok = all(abs(a - b) <= max(0.02, abs(b) * 5e-4) for a, b in hits)
        return (len(hits), ok)

    _warned: list[str] = []
    print(f"\nA2. 铁律 24 自检（指标窗口 vs 可用 K 线根数；根数取自 {_bars_src}）")
    if n_bars is None:
        # 无法判定可用根数时**保持沉默**，不得用截断后的表长冒充真实根数
        # （那会把长历史标的一律误报成「指标不存在」）——比不报更危险。
        print("  ⚠ 跳过：可用 K 线根数不可判定 ⇒ 本次**不做**铁律 24 判定（不猜、不误报）。")
        print("     ⇒ 若需判定，请用当前版本 `collect.py` 重采（§1 会写 `- bars:` 字段）。")
    for _name, _win in IND_WINDOW.items():
        if n_bars is None:
            break
        _s = series(_name)
        _v = IND.get(_name)
        if _v is None and _s:
            _v = _s[0][1]
        if _v is None or n_bars >= _win:
            continue
        # 窗口 W 下、B 根 K 线最多能产出 max(0, B−W+1) 个值；B < W 时为 0。
        # ⇒ 只要取到了值，就**已经**在算术上不可能 ⇒ 直接判真阳性（硬窗口）。
        _possible = max(0, n_bars - _win + 1)
        _hard = _name in IND_WINDOW_HARD
        _lvl = "铁律 24 真阳性" if _hard else "疑似口径漂移（窗口为源默认值，非名字给出）"
        _warned.append(_name)
        print(f"  ⛔ [{_lvl}] {_name}：声称窗口 {_win} 根，但可用 K 线仅 **{n_bars}** 根"
              f" ⇒ 该窗口最多只能产出 {_possible} 个值，**该指标在算术上不存在**。")
        _cf = _confirm_expanding_mean(_name)
        if _cf:
            _n, _ok = _cf
            print(f"     最新值 {_v:.6f}；expanding-mean 反算校验：{_n} 个点"
                  + ("**全部与 K 线表吻合** ⇒ 确认为「上市以来累加均值」伪装成固定窗口均线。"
                     if _ok else "**与 K 线表不符** ⇒ 非累加均值，但窗口本身已不可能，仍不得引用。"))
        else:
            print(f"     最新值 {_v:.6f}；包内序列点数不足，无法反算均值（需用探针直取日线复算）。")
        print(f"     ⇒ 下游**禁止**把它当作「{_win} 日线」用于牛熊分界 / 长线支撑 / "
              f"机构成本线等任何论证（铁律 24）。")
    if n_bars is None:
        pass                       # 已在上面打印「跳过」，此处不再打印任何结论
    elif _warned:
        print(f"  ⛔ 自检命中 {len(_warned)} 项：{', '.join(_warned)}（可用 K 线 {n_bars} 根）"
              f" —— 这些指标必须在下游按「不可用」处理。")
    else:
        print(f"  ✓ 未命中：可用 K 线 {n_bars} 根，覆盖全部已声明指标窗口。")

    print("\nB. 最近 3 根 K 线")
    prev = rows[-4][4] if len(rows) >= 4 else None
    for d, o, h, lo, c, v in rows[-3:]:
        rng = h - lo
        chg = f"{(c / prev - 1) * 100:+.2f}%" if prev else " n/a"
        print(f"  {d} 收 {c:>8.2f} 日涨跌 {chg:>7} 振幅 {rng:>6.2f} "
              f"收盘位于日内 {(c - lo) / rng * 100:>5.1f}%  量 {v / 1e6:>7.2f}M")
        prev = c
    av = stat("avg_vol_20d")
    if av:
        v_latest = rows[-1][5] if rows else None
        ratio_str = f"（最新日量占 20 日均量 {v_latest / av * 100:.1f}%）" if v_latest else ""
        print(f"  20 日均量 {av / 1e6:.2f}M {ratio_str}")

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
        cur = m_[0][1]
        prev = m_[1][1] if len(m_) >= 2 else None
        if prev is not None and prev >= 0 > cur:
            state = "今日跌破零轴（由正转负）"
        elif prev is not None and prev <= 0 < cur:
            state = "今日上穿零轴（由负转正）"
        elif cur < 0:
            state = "位于零轴下方（本窗口内未发生穿越）"
        else:
            state = "位于零轴上方（本窗口内未发生穿越）"
        print(f"  → MACD {state}（{m_[-1][1]:+.3f} → {m_[0][1]:+.3f}）")
    rs = series("rsi")
    if rs:
        print("  RSI: " + " | ".join(f"{d[5:]} {v:.2f}" for d, v in reversed(rs)))
        # 背离检验：检查价格与 RSI 走势是否同向（严防强行叫底背离）
        if len(rows) >= 2 and len(rs) >= 2:
            p_curr, p_prev = rows[-1][4], rows[-2][4]
            r_curr, r_prev = rs[0][1], rs[1][1]
            if p_curr < p_prev and r_curr < r_prev:
                print(f"  ⚠️ 背离检验：价格创低 ({p_curr:.2f} < {p_prev:.2f}) 且 RSI 走低 ({r_curr:.2f} < {r_prev:.2f}) ⇒ **无底背离，属顺势下挫**！严禁误标底背离。")
            elif p_curr < p_prev and r_curr > r_prev:
                print(f"  ★ 背离检验：价格创低 ({p_curr:.2f} < {p_prev:.2f}) 但 RSI 抬高 ({r_curr:.2f} > {r_prev:.2f}) ⇒ 出现底背离反弹信号。")
            elif p_curr > p_prev and r_curr < r_prev:
                print(f"  ⚠️ 背离检验：价格走高 ({p_curr:.2f} > {p_prev:.2f}) 但 RSI 降低 ({r_curr:.2f} < {r_prev:.2f}) ⇒ 出现顶背离警告。")

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
            gp_s = f"{gp0 / rev0 * 100:.2f}%" if gp0 is not None else "n/a"
            oi_s = f"{oi0 / rev0 * 100:.2f}%" if oi0 is not None else "n/a"
            ni_s = f"{ni0 / rev0 * 100:.2f}%" if ni0 is not None else "n/a"
            print(f"    毛利率 {gp_s}  营业利润率 {oi_s}  净利率 {ni_s}")
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
        # ★★ 2026-10-08：这里**必须**声明自己截断过。
        #    血泪：本函数为省版面只打印前 22 行，却**没有任何"已截断"字样**，
        #    于是被当成了完整事实 —— 简报据此写「内部人只有 2 笔带价卖出」，
        #    而证据包 §8 实际有 **150 行 / 44 笔 / $77,494,297**（差 22 倍）。
        #    两位分析师各自独立复核后才发现 ⇒ 已作为铁律 6 的实例记档。
        #    ⇒ 凡是"截断输出"，都必须在**输出内**标明，不能靠读者猜到。
        lines = [l for l in body.splitlines() if l.strip()]
        LIMIT = 22
        print("\n".join("  " + l.strip() for l in lines[:LIMIT]))
        if len(lines) > LIMIT:
            print(f"  ... [TRUNCATED: 仅显示前 {LIMIT} 行，本节共 {len(lines)} 行]")
            print(f"  ... [完整内容见 {p.name} §8 —— **不要据本截断视图下结论**（本行的存在就是为了防这一点）]")
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
