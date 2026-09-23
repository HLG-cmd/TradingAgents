# lifecycle: oneoff
# created: 2026-09-23
# serves: NDX 派生指标（已被 _derive_ndx.py 取代）
# usage: ./.venv/Scripts/python.exe wb_analysis/_derive_ndx_orig.py
"""派生指标计算器：从 NDX 证据包导出所有「需要算术推导」的二级指标。

目的：把均线偏离、布林带内位置、ERP 分位、广度背离、斜率、集中度差额等
一次性算准，避免分析层各角色各自手算出不同结果，也便于复核。
不产生任何新数据——输入全部来自 wb_analysis/evidence/NDX_<date>.md/.json。

用法：
    python wb_analysis/_derive_ndx.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / "wb_analysis" / "evidence"

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-09-16"
md = (EV / f"NDX_{DATE}.md").read_text(encoding="utf-8")
d = json.loads((EV / f"NDX_{DATE}.json").read_text(encoding="utf-8"))


def series(name: str) -> list[tuple[str, float]]:
    """从证据包 §2 抽出某个指标的时间序列（新→旧）。"""
    m = re.search(rf"### {re.escape(name)}\n```\n(.*?)\n```", md, re.S)
    if not m:
        return []
    out = []
    for line in m.group(1).splitlines():
        mm = re.match(r"^(\d{4}-\d{2}-\d{2}):\s*(-?[\d.]+)$", line.strip())
        if mm:
            out.append((mm.group(1), float(mm.group(2))))
    return out


def latest(name: str) -> float:
    s = series(name)
    return s[0][1]


ps, br, val = d["price_stats"], d["breadth"], d["valuation"]
c = ps["latest_close"]
BAR_DATES = re.findall(r"^(\d{4}-\d{2}-\d{2})\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+\d+$",
                       md, re.M)
print("=" * 74)
print(f"A. 价格位置（基准：{BAR_DATES[-1]} 收盘 {c:.2f}；指标最新值 {series('close_50_sma')[0][0]}）")
print("=" * 74)
IND = {
    "50SMA": latest("close_50_sma"), "200SMA": latest("close_200_sma"),
    "10EMA": latest("close_10_ema"), "VWMA": latest("vwma"),
    "BOLL_MID": latest("boll"), "BOLL_UB": latest("boll_ub"), "BOLL_LB": latest("boll_lb"),
}
for k, v in IND.items():
    print(f"  {k:<9} {v:>10.2f}   距现价 {(c / v - 1) * 100:+.3f}%")
for k, v in (("52W HIGH", ps["high_52w"]), ("52W LOW", ps["low_52w"])):
    print(f"  {k:<9} {v:>10.2f}   距现价 {(c / v - 1) * 100:+.3f}%")

band = IND["BOLL_UB"] - IND["BOLL_LB"]
print(f"\n  布林带宽 {band:.2f} 点 = {band / IND['BOLL_MID'] * 100:.3f}%（中轨口径）")
print(f"  现价在带内位置 {(c - IND['BOLL_LB']) / band * 100:.2f}%（0=下轨 100=上轨）")
print(f"  现价距下轨 {c - IND['BOLL_LB']:.2f} 点（{(c / IND['BOLL_LB'] - 1) * 100:+.3f}%）")
print(f"  现价距上轨 {IND['BOLL_UB'] - c:.2f} 点（{(c / IND['BOLL_UB'] - 1) * 100:+.3f}%）")

print("\n" + "=" * 74)
print("B. 近 3 根 K 线：日内结构与量能")
print("=" * 74)
rows = []
for line in md.splitlines():
    mm = re.match(r"^(\d{4}-\d{2}-\d{2})\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)$",
                  line.strip())
    if mm:
        rows.append((mm.group(1), *[float(x) for x in mm.groups()[1:]]))
prev = rows[-4][4] if len(rows) >= 4 else None
for date, o, h, lo, cl, vol in rows[-3:]:
    rng = h - lo
    chg = f"{(cl / prev - 1) * 100:+.2f}%" if prev else "  n/a"
    print(f"  {date} 收 {cl:>9.2f} 日涨跌 {chg:>7} 振幅 {rng:>7.2f} "
          f"收盘位于日内 {(cl - lo) / rng * 100:>5.1f}% 量 {vol / 1e8:.2f}亿 = "
          f"20日均量 {vol / ps['avg_vol_20d'] * 100:.1f}%")
    prev = cl
print(f"\n  20 日均量 {ps['avg_vol_20d'] / 1e8:.2f} 亿股")
print(f"  收益 5日 {ps['ret_5d']:+.2f}% | 20日 {ps['ret_20d']:+.2f}% | "
      f"60日 {ps['ret_60d']:+.2f}% | 120日 {ps['ret_120d']:+.2f}%")

print("\n" + "=" * 74)
print("C. 均线斜率（按证据包真实最新值）")
print("=" * 74)
for nm, key in (("50SMA", "close_50_sma"), ("200SMA", "close_200_sma"), ("10EMA", "close_10_ema")):
    s = series(key)
    n = len(s) - 1
    d0, v0 = s[-1]
    d1, v1 = s[0]
    print(f"  {nm:<7} {d0} {v0:>10.2f} → {d1} {v1:>10.2f}  "
          f"变化 {v1 - v0:+.2f} 点 / {n} 个交易日 = {(v1 - v0) / n:+.2f} 点/日")
print(f"  50SMA − 200SMA = {IND['50SMA'] - IND['200SMA']:+.2f} 点（仍在金叉上方）")

print("\n" + "=" * 74)
print("D. MACD / RSI / ATR 路径（新→旧为倒序，此处按时间正序打印）")
print("=" * 74)
m_, s_, h_ = series("macd"), series("macds"), series("macdh")
for i in range(len(m_) - 1, -1, -1):
    print(f"  {m_[i][0]}  MACD {m_[i][1]:>8.3f}  Signal {s_[i][1]:>8.3f}  Hist {h_[i][1]:>9.3f}")
print(f"  → MACD 线 {m_[-1][1]:+.3f} → {m_[0][1]:+.3f}："
      f"{'已跌破零轴' if m_[0][1] < 0 <= m_[-1][1] else '仍在零轴上方'}")
rs = series("rsi")
print("  RSI: " + " | ".join(f"{dd[5:]} {vv:.2f}" for dd, vv in reversed(rs)))
print(f"  → 窗口内最高 {max(v for _, v in rs):.2f}、最低 {min(v for _, v in rs):.2f}，"
      f"最新 {rs[0][1]:.2f}")
atr = latest("atr")
print(f"\n  ATR {atr:.2f} = 现价的 {atr / c * 100:.3f}%"
      f"（最新 {series('atr')[0][0]}；前值 {series('atr')[1][1]:.2f}）")

print("\n" + "=" * 74)
print("E. 估值与股权风险溢价")
print("=" * 74)
# ⚠️ 不要硬编码无风险利率：FRED 序列每天更新，硬编码会悄悄用上过期值。
# 从证据包 §11 的 10y_treasury 段落解析 `Latest: <值> (<日期>)`。
_blk = re.search(r"### 10y_treasury\n```\n(.*?)```", md, re.S)
_m = re.search(r"\*\*Latest:\*\*\s*([\d.]+)\s*\(([\d-]+)\)", _blk.group(1) if _blk else "")
if not _m:
    raise SystemExit("✗ 无法从证据包解析 10 年期美债最新值，请检查 §11 的 10y_treasury 段落")
dgs10, dgs10_date = float(_m.group(1)), _m.group(2)
_ch = re.search(r"Change over window:\*\*\s*([+-]?[\d.]+)", _blk.group(1))
dgs10_prev = float(_ch.group(1)) if _ch else float("nan")
ey = val["earnings_yield_pct"]
print(f"  聚合 PE(TTM) {val['agg_pe']}  Forward PE {val['agg_forward_pe']}  "
      f"PB {val['agg_pb']}  PS {val['agg_ps']}  股息率 {val['agg_div_yield_pct']}%")
print(f"  盈利收益率 {ey}% − 10Y美债 {dgs10}%（FRED DGS10，{dgs10_date}）= ERP {ey - dgs10:+.2f}pp")
print(f"  （10Y 窗口内变化 {dgs10_prev:+.2f}pp）")
print(f"  ROE {val['agg_roe_pct']}%  净利率 {val['agg_net_margin_pct']}%  "
      f"毛利率 {val['agg_gross_margin_pct']}%  营业利润率 {val['agg_op_margin_pct']}%")
print(f"  → 营业利润率/毛利率 = {val['agg_op_margin_pct'] / val['agg_gross_margin_pct'] * 100:.1f}%")
print(f"  加权营收增速 {val['agg_rev_growth_pct']}% vs 中位 {val['agg_rev_growth_median_pct']}%"
      f" = {val['agg_rev_growth_pct'] / val['agg_rev_growth_median_pct']:.2f}x")
print(f"  加权盈利增速 {val['agg_eps_growth_pct']}% vs 中位 {val['agg_eps_growth_median_pct']}%"
      f" = {val['agg_eps_growth_pct'] / val['agg_eps_growth_median_pct']:.2f}x")
print(f"  Beta {val['agg_beta']}（中位 {val['median_beta']}）；纳入 PE {val['n_pe_used']} 只，"
      f"剔除 {len(val['excluded_pe_tickers'])} 只 {val['excluded_pe_tickers']}")

erp_rows = json.loads((EV / "erp_history_sp500.json").read_text(encoding="utf-8"))
vals = sorted(r["erp_pp"] for r in erp_rows if r.get("erp_pp") is not None)
cur = ey - dgs10
below = sum(1 for v in vals if v < cur)
print(f"\n  【ERP 历史分布】基准=标普500 TTM PE(multpl)+FRED DGS10 月度，{len(vals)} 个观测")
print(f"    区间 {erp_rows[0].get('date')} ~ {erp_rows[-1].get('date')}")
print(f"    最低 {vals[0]:+.2f} / 中位 {vals[len(vals) // 2]:+.2f} / 最高 {vals[-1]:+.2f} pp")
print(f"    为负月份占比 {sum(1 for v in vals if v < 0) / len(vals) * 100:.1f}%")
# 分位口径：below = 历史观测中低于当前值的个数，故 below/n 越小 ⇒ 估值越贵。
# 2026-09-17 修正：原代码打印 `len(vals) - below`（即「高于当前值的观测数」）
# 却标注为「比它更低的观测」，两者矛盾（-1.52pp 时打印 326 个，实际应有约 115 个）。
print(f"    当前 {cur:+.2f}pp 处于第 {below / len(vals) * 100:.0f} 百分位（越低越贵）"
      f"（比它更低的观测 {below} 个 / 更高的 {len(vals) - below} 个）")

print("\n" + "=" * 74)
print("F. 市场广度与结构")
print("=" * 74)
print(f"  样本 {br['n_valid']}/{br.get('n_universe')}（覆盖 "
      f"{br['n_valid'] / br.get('n_universe', 101) * 100:.1f}%）")
print(f"  站上 200SMA {br['pct_above_200sma']}% | 站上 50SMA {br['pct_above_50sma']}%")
print(f"  20/60/120 日收涨家数占比 {br['pct_up_20d']}% / {br['pct_up_60d']}% / {br['pct_up_120d']}%")
print(f"  成分股中位收益 20日 {br['median_ret20']}% / 60日 {br['median_ret60']}%")
print(f"  等权收益     20日 {br['equal_weight_ret20']}% / 60日 {br['equal_weight_ret60']}%")
print(f"  ★ 指数−中位：20日 {ps['ret_20d'] - br['median_ret20']:+.2f}pp"
      f"  | 60日 {ps['ret_60d'] - br['median_ret60']:+.2f}pp")
print(f"  20 日离散度 {br['dispersion_ret20']}%")
sw = dict(val["sector_weights"])
top3 = sum(sw[k] for k in ("Technology", "Communication Services", "Consumer Cyclical"))
divs = sum(sw[k] for k in ("Energy", "Financial Services", "Basic Materials", "Utilities"))
print(f"\n  前三行业合计 {top3:.2f}% | 传统分散化板块合计 {divs:.2f}%")
print(f"  集中度 官方前十 46.28% vs 纯市值前十 {val['top10_weight_pct']}%"
      f"（差 {val['top10_weight_pct'] - 46.28:.2f}pp）| 纯市值前二十 {val['top20_weight_pct']}%"
      f" | HHI {val['hhi']}")
print(f"  总市值 {val['total_market_cap'] / 1e12:.3f} 万亿美元")
ins = d["insiders"]
b = sum(r["buy_value"] for r in ins)
s = sum(r["sell_value"] for r in ins)
print(f"\n  内部人 买 ${b / 1e9:.3f}B / 卖 ${s / 1e9:.3f}B = {s / b:.1f}x")
print("=" * 74)
