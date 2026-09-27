# lifecycle: oneoff
# created: 2026-09-27
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_avgo_valuation_selfcalc.py
"""探针：用「价格序列 + EDGAR 股数 + 报表」自算 AVGO 的 point-in-time 估值指标，
并与 vendor supplement 的实时快照对照 —— 判断 §3 缺口能否被等价补齐。

关键点：自算的数据来源全部具有**明确的披露时点**，因此是真正的 point-in-time，
而不是「当下值」。若两者接近，则现有分析的估值锚站得住；若差异大，则必须重跑下游角色。
"""
import json
import pathlib
import sys

import pandas as pd

HOME = pathlib.Path.home() / ".tradingagents"
CACHE = HOME / "cache"
EDGAR = HOME / "edgar" / "facts_AVGO_2026Q3.json"
AS_OF = "2026-09-25"
OUT = pathlib.Path(r"wb_analysis/_oneoff/_probe_avgo_valuation_selfcalc.txt")

lines: list[str] = []


def p(s: str = "") -> None:
    lines.append(s)
    print(s)


# ---------- 1. 价格序列（到基准日） ----------
cands = sorted(CACHE.glob("AVGO-YFin-data-*.csv"))
p(f"[价格源] {[c.name for c in cands]}")
px = None
for c in cands:
    df = pd.read_csv(c, parse_dates=["Date"])
    df = df[df["Date"] <= AS_OF].sort_values("Date").reset_index(drop=True)
    if len(df) > 0:
        px = df
        p(f"[采用] {c.name}  到基准日的有效行 = {len(df)}")
        break
if px is None:
    p("!! 无可用价格")
    sys.exit(1)

close = float(px["Close"].iloc[-1])
p(f"[基准日收盘] {px['Date'].iloc[-1].date()}  close = {close:.4f}")

# 52 周区间（252 个交易日）
w52 = px.tail(252)
hi52, lo52 = float(w52["High"].max()), float(w52["Low"].min())
p(f"[52周区间·自算]  高 {hi52:.2f}  低 {lo52:.2f}  (窗口 {w52['Date'].iloc[0].date()} ~ {w52['Date'].iloc[-1].date()}, {len(w52)} 根)")
p(f"   距高 {close/hi52*100-100:+.3f}%   距低 {close/lo52*100-100:+.3f}%")

# 均线
ma50 = float(px["Close"].tail(50).mean())
ma200 = float(px["Close"].tail(200).mean())
p(f"[均线·自算] 50SMA {ma50:.2f}  200SMA {ma200:.2f}")

# 年化波动率（近 252 日对数收益）
import numpy as np
r = np.diff(np.log(px["Close"].tail(253).to_numpy()))
vol = float(np.std(r, ddof=1) * np.sqrt(252))
p(f"[年化波动率·自算·252日] {vol*100:.2f}%")

# ---------- 2. EDGAR 股数（point-in-time） ----------
d = json.loads(EDGAR.read_text(encoding="utf-8"))
facts = d["facts"]

def latest_before(tax: str, tag: str, unit: str, as_of: str):
    arr = facts[tax][tag]["units"][unit]
    ok = [r for r in arr if r.get("end", "") <= as_of]
    if not ok:
        return None
    r = max(ok, key=lambda x: (x["end"], x.get("filed", "")))
    return r

sh = latest_before("dei", "EntityCommonStockSharesOutstanding", "shares", AS_OF)
p(f"[EDGAR 股数] end={sh['end']} val={sh['val']:,} form={sh['form']} filed={sh['filed']}")
dil = latest_before("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares", AS_OF)
p(f"[EDGAR 稀释加权股数] end={dil['end']} val={dil['val']:,} form={dil['form']} filed={dil['filed']}")

# ---------- 3. 自算市值 ----------
mc_shares = close * sh["val"]
mc_dil = close * dil["val"]
p(f"[市值·自算 用已发行股数]  {mc_shares/1e9:.1f}B")
p(f"[市值·自算 用稀释加权]    {mc_dil/1e9:.1f}B")

# ---------- 4. 报表口径的估值 ----------
# 来自 §4 三大报表（FY2025）与 supplement 的 TTM
FY_REV, FY_NI, FY_EQ, FY_EPS = 63.9e9, 23.1e9, 81.3e9, 4.77
TTM_NI, TTM_REV, TTM_EPS = 38.265e9, 89.104e9, 7.85
p()
p("[自算估值·FY2025 口径]")
p(f"   PE(市值/净利) = {mc_shares/FY_NI:.2f}")
p(f"   PS            = {mc_shares/FY_REV:.2f}")
p(f"   PB            = {mc_shares/FY_EQ:.2f}")
p(f"   PE(价格/EPS)  = {close/FY_EPS:.2f}")
p("[自算估值·TTM 口径（净利/营收取自 §4 之外的补充）]")
p(f"   PE(TTM)       = {mc_shares/TTM_NI:.2f}")
p(f"   PS(TTM)       = {mc_shares/TTM_REV:.2f}")
p(f"   PE(价格/TTM EPS) = {close/TTM_EPS:.2f}")

# ---------- 5. 与 vendor supplement 对照 ----------
sup = pathlib.Path("wb_analysis/evidence/AVGO_2026-09-25.supplement.md")
# 从审计包读（已封存，evidence/ 为空）
import zipfile
zp = pathlib.Path("reports/AVGO/AVGO_20260927_002003/_source.zip")
vendor = {}
if zp.exists():
    z = zipfile.ZipFile(zp)
    for n in z.namelist():
        if n.endswith("supplement.md"):
            txt = z.read(n).decode("utf-8")
            import re
            for k in ("Market Cap", "PE Ratio (TTM)", "Forward PE", "Price to Book",
                      "Price to Sales (TTM)", "EPS (TTM)", "52 Week High", "52 Week Low",
                      "50 Day Average", "200 Day Average", "Beta"):
                m = re.search(rf"{re.escape(k)}\s+([\d.]+)", txt)
                if m:
                    vendor[k] = float(m.group(1))
            break

p()
p("========== 自算 vs vendor 快照（关键差异即「口径差异」） ==========")
p(f"{'指标':<22}{'自算':>14}{'vendor':>14}{'差异':>12}")
rows = [
    ("市值(B)", mc_shares/1e9, vendor.get("Market Cap", float("nan"))/1e9),
    ("PE(TTM)", mc_shares/TTM_NI, vendor.get("PE Ratio (TTM)", float("nan"))),
    ("PB", mc_shares/FY_EQ, vendor.get("Price to Book", float("nan"))),
    ("PS(TTM)", mc_shares/TTM_REV, vendor.get("Price to Sales (TTM)", float("nan"))),
    ("EPS(TTM)", TTM_EPS, vendor.get("EPS (TTM)", float("nan"))),
    ("52周高", hi52, vendor.get("52 Week High", float("nan"))),
    ("52周低", lo52, vendor.get("52 Week Low", float("nan"))),
    ("50日均价", ma50, vendor.get("50 Day Average", float("nan"))),
    ("200日均价", ma200, vendor.get("200 Day Average", float("nan"))),
]
for name, a, b in rows:
    if b != b:  # nan
        p(f"{name:<22}{a:>14.3f}{'—':>14}{'':>12}")
    else:
        d_ = (a/b - 1) * 100 if b else float("nan")
        p(f"{name:<22}{a:>14.3f}{b:>14.3f}{d_:>11.2f}%")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"\n→ {OUT}")
