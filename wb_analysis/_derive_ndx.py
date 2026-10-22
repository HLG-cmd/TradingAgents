# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py
"""派生指标计算器：从指数证据包导出所有「需要算术推导」的二级指标（支持 NDX / SPX）。

目的：把均线偏离、布林带内位置、ERP 分位、广度背离、斜率、集中度差额等
一次性算准，避免分析层各角色各自手算出不同结果，也便于复核。
不产生任何新数据——输入全部来自 wb_analysis/evidence/<INDEX>_<date>.md/.json。

用法：
    python wb_analysis/_derive_ndx.py [YYYY-MM-DD] [--index {NDX,SPX}]
      默认 --index NDX，因此原调用 `python wb_analysis/_derive_ndx.py 2026-09-17`
      仍读 wb_analysis/evidence/NDX_2026-09-17.md/.json，行为与改造前完全一致。
"""
from __future__ import annotations

import argparse
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

# 各指数「官方发布的前十集中度」。
#   ★ 2026-10-16 修：**取消 NDX 的硬编码**。原代码为
#       OFFICIAL_TOP10 = {"NDX": 46.28}
#     把「官方口径前十」写成一个固定快照。实测 NDX_20261013 那轮的证据包里该值已是
#     **46.68%**（`top_holdings` 前 10 权重合计，逐日随行情/调样漂移），
#     但派生层仍写出 46.28% ⇒ 与真实值差 0.40pp，并被下游 11 个角色文件照抄引用
#     （`market.md` 的「官方 QQQ 口径前十大 46.28%」、差 21.63pp 等）。
#
#   现在统一改为：**一律从证据包的 `top_holdings` 实时求和**（与 SPX 分支同源、
#   与 `collect_index.py` 的 hold_sum 一致），并在取不到时才回退到常量。
#   这样「官方口径」不再是会漂移的魔法数，也消除了 NDX 与 SPX 两条代码路径的分歧。
OFFICIAL_TOP10_FALLBACK = {
    # 仅当证据包缺 `top_holdings` 时兜底；正常路径不读这里。
    "NDX": 46.28,
}

# 广度样本池缺省规模（仅当证据包未带 n_universe 时兜底）。
# NDX 去重后 101 只；SPX 不去重 503 只。
N_UNIVERSE_DEFAULT = {
    "NDX": 101,
    "SPX": 503,
}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="从指数证据包导出派生指标（支持 NDX / SPX，默认 NDX）")
    ap.add_argument("date", nargs="?", default="2026-09-16",
                    help="基准日期 YYYY-MM-DD（默认 2026-09-16，与改造前一致）")
    ap.add_argument("--index", choices=("NDX", "SPX"), default="NDX",
                    help="指数前缀 NDX（纳斯达克100）或 SPX（标普500），默认 NDX")
    return ap.parse_args(argv)


args = parse_args()
INDEX = args.index
DATE = args.date

md = (EV / f"{INDEX}_{DATE}.md").read_text(encoding="utf-8")
d = json.loads((EV / f"{INDEX}_{DATE}.json").read_text(encoding="utf-8"))

# 官方口径前十：一律从证据包 `top_holdings` 实时求和（NDX / SPX 同一路径）。
# ★ 2026-10-16 修：原为 `OFFICIAL_TOP10 = {"NDX": 46.28}` 硬编码快照，
#   实测 NDX_20261013 那轮证据包已是 46.68%，派生层仍写 46.28%（差 0.40pp），
#   并被下游 11 个角色文件照抄。⇒ 改为读证据包，常量只作取不到时的兜底。
_th = d.get("top_holdings") or []
if len(_th) >= 2:
    # 与 collect_index.py 的 hold_sum 同源：ETF 代理公布的真实前十大权重合计。
    OFFICIAL_TOP10_PCT = round(sum(h.get("weight_pct", 0.0) for h in _th[:10]), 2)
else:
    OFFICIAL_TOP10_PCT = OFFICIAL_TOP10_FALLBACK.get(INDEX, 0.0)
    print(f"  ⚠ 证据包缺 top_holdings ⇒ 官方前十回退到兜底常量 {OFFICIAL_TOP10_PCT}%"
          f"（该值可能已漂移，引用需声明）")

N_UNIVERSE = N_UNIVERSE_DEFAULT[INDEX]



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
for date, _o, h, lo, cl, vol in rows[-3:]:
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

# ★ 2026-09-23 修：ERP 历史序列是**共享缓存**（不属于任何一轮运行），已移到 `_cache/`。
#   此前读 `evidence/` ⇒ 搬缓存后此处直接 FileNotFoundError。
#   ⚠️ 教训：当年挪动共享文件时，用**字符串搜索**找消费者**漏掉了这种用变量拼路径的写法**。
_cache = EV.parent / "_cache"
_erp = (_cache if (_cache / "erp_history_sp500.json").exists()
        else EV) / "erp_history_sp500.json"
if not _erp.exists():
    raise SystemExit(f"缺少 ERP 历史序列：{_erp}\n"
                     f"（共享缓存应在 wb_analysis/_cache/；若缺失请跑 erp_context.py --append 重建）")
erp_rows = json.loads(_erp.read_text(encoding="utf-8"))
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
      f"{br['n_valid'] / br.get('n_universe', N_UNIVERSE) * 100:.1f}%）")
print(f"  站上 200SMA {br['pct_above_200sma']}% | 站上 50SMA {br['pct_above_50sma']}%")
print(f"  20/60/120 日收涨家数占比 {br['pct_up_20d']}% / {br['pct_up_60d']}% / {br['pct_up_120d']}%")
print(f"  成分股中位收益 20日 {br['median_ret20']}% / 60日 {br['median_ret60']}%")
print(f"  等权收益     20日 {br['equal_weight_ret20']}% / 60日 {br['equal_weight_ret60']}%")
print(f"  ★ 指数−中位：20日 {ps['ret_20d'] - br['median_ret20']:+.2f}pp"
      f"  | 60日 {ps['ret_60d'] - br['median_ret60']:+.2f}pp")
print(f"  20 日离散度 {br['dispersion_ret20']}%")
sw = dict(val["sector_weights"])
# ★ 前三行业改为「动态取实际权重最高的三个」，不再写死。
#   原先写死 (Technology / Communication Services / Consumer Cyclical) 是按纳指100 校准的
#   —— 纳指这三者恰好就是行业前三（实测 57.70 / 16.26 / 12.04），
#   故本改动对 NDX 的数值与输出格式**逐字不变**。
#   但标普500 的行业结构与纳指差异极大（金融、医疗权重高出一个量级），
#   写死的三元组对 SPX 既不是真正的前三，`sw[k]` 还会直接 KeyError。
_top3_keys = [k for k, _ in sorted(sw.items(), key=lambda kv: kv[1], reverse=True)[:3]]
top3 = sum(sw[k] for k in _top3_keys)
# 分散化/防守型板块：定义为固定篮子以便跨指数比较；用 .get 容错，缺项按 0 计。
divs = sum(sw.get(k, 0.0) for k in
           ("Energy", "Financial Services", "Basic Materials", "Utilities"))
print(f"\n  前三行业合计 {top3:.2f}% | 传统分散化板块合计 {divs:.2f}%")
print(f"  集中度 官方前十 {OFFICIAL_TOP10_PCT:.2f}% vs 纯市值前十 {val['top10_weight_pct']}%"
      f"（差 {val['top10_weight_pct'] - OFFICIAL_TOP10_PCT:.2f}pp）| 纯市值前二十 {val['top20_weight_pct']}%"
      f" | HHI {val['hhi']}")
print(f"  总市值 {val['total_market_cap'] / 1e12:.3f} 万亿美元")
ins = d["insiders"]
b = sum(r["buy_value"] for r in ins)
s = sum(r["sell_value"] for r in ins)
print(f"\n  内部人 买 ${b / 1e9:.3f}B / 卖 ${s / 1e9:.3f}B = {s / b:.1f}x")

print("\n" + "=" * 74)
print("G. 跨资产基准（NQ期货 / 原油 / 美债曲线）—— 最新性自检")
print("=" * 74)
# ★ 2026-10-22 新增：跨资产三通道（用户点名要求的基础数据）。
#   自检口径：每个代码最后一个**已收盘** bar 的日期必须等于指数自身最后一根已收盘
#   bar（采集器写入 JSON 的 cross_asset.ref_date）。不等 ⇒ 记 stale 并提示写进简报。
ca = d.get("cross_asset") or {}
proxies = {p["ticker"]: p for p in (ca.get("proxies") or [])}
ref = ca.get("ref_date") or DATE
if ca.get("error"):
    print(f"  ⚠ 证据包 cross_asset 段不可用（{ca['error']}）—— 跨资产维度缺失，须在 0_brief.md 声明")
elif not proxies:
    print("  ⚠ 证据包无 cross_asset 段（采集器版本过旧）—— 跨资产维度缺失，须在 0_brief.md 声明")
else:
    print(f"  新鲜度基准（指数最后已收盘 bar）: {ref}")
    for tkr, label in (("NQ=F", "纳指100期货"), ("CL=F", "WTI原油"), ("BZ=F", "布伦特原油"),
                       ("^TNX", "美债10Y"), ("^FVX", "美债5Y"), ("^TYX", "美债30Y")):
        p = proxies.get(tkr)
        if not p or not p.get("last_date"):
            print(f"  {tkr:<6} {label:<10} 缺失")
            continue
        flag = "✓=基准日" if p.get("fresh") else f"⚠ 陈旧{p.get('age_days')}天"
        chg = ""
        comp = [x for x in p["bars"] if x["date"] <= ref and x["close"] is not None]
        if len(comp) >= 2 and comp[-2]["close"]:
            chg = f"  日环比 {(p['last_close'] / comp[-2]['close'] - 1) * 100:+.2f}%"
        part = f"  （另有未收盘 bar: {', '.join(x['date'] for x in p.get('partial_bars', []))}）" \
            if p.get("partial_bars") else ""
        print(f"  {tkr:<6} {label:<10} 收 {p['last_close']:>10}  ({p['last_date']} {flag}){chg}{part}")
    nq = proxies.get("NQ=F")
    if nq and nq.get("last_close") and ps.get("latest_close"):
        basis = (nq["last_close"] / ps["latest_close"] - 1) * 100
        print(f"  NQ期货/指数 期现差 {basis:+.3f}%"
              f"（含展期与分红时点因素，**不等于精确理论基差**，只用于方向与量级）")
    y10 = (proxies.get("^TNX") or {}).get("last_close")
    y5 = (proxies.get("^FVX") or {}).get("last_close")
    y30 = (proxies.get("^TYX") or {}).get("last_close")
    if None not in (y10, y5, y30):
        print(f"  曲线 30Y−10Y = {y30 - y10:+.2f}pp | 10Y−5Y = {y10 - y5:+.2f}pp"
              f"（单位=百分点；ERP 用 FRED DGS10 口径见 E 节）")
    stale = [t for t, p in proxies.items() if p.get("last_date") and not p.get("fresh")]
    if stale:
        print(f"  ⚠ 非基准日收盘的代码：{stale} —— 该缺口必须写进 0_brief.md 并降条件式结论")
    else:
        print("  ✓ 全部代码均已收盘至基准日 —— 跨资产通道无缺口")
print("=" * 74)
