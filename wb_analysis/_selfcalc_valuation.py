# lifecycle: reusable
# created: 2026-09-27
# usage: from wb_analysis import _selfcalc_valuation as sv; sv.selfcalc("AVGO", "2026-09-25")
"""自算 point-in-time 估值 —— 独立于 vendor 实时快照的第二条估值通道。

## 为什么需要它

证据包 §3（`get_fundamentals`）走 yfinance `Ticker.info`，该接口**只服务"当下值"、
没有历史 vintage**，因此对历史基准日会**整节拒答**（见 `date_window.withhold_live_profile`）。
此前项目把这类情况记为「A 类缺口 · 上游扣留」，并只用 `_gen_supplement.py` 的
**实时快照**作替代 —— 但快照是"当下"，严格说仍带时点偏差。

本模块提供**第三条路**：全部输入都有**明确的披露时点**，因此是真正的 point-in-time ——

| 输入 | 来源 | 时点保证 |
|---|---|---|
| 价格序列 | `~/.tradingagents/cache/<T>-YFin-data-*.csv` | 逐日 bar，截到基准日 |
| 股数 | `~/.tradingagents/edgar/facts_<T>_*.json` | 取 `end <= 基准日` **且 `filed <= 基准日`** 的最新披露 |
| 报表项（净利/营收/权益） | 调用方传入（来自证据包 §4） | 年报/季报期末 |

## 用法

    from wb_analysis import _selfcalc_valuation as sv
    out = sv.selfcalc("AVGO", "2026-09-25", fy_net_income=23.1e9, fy_revenue=63.9e9, fy_equity=81.3e9)

`out` 含 `market_cap` / `high_52w` / `low_52w` / `ma50` / `ma200` / `vol_annual` /
各口径 PE·PB·PS，以及每个数字的**来源与时间戳**（`sources`）。
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd

HOME = pathlib.Path.home() / ".tradingagents"
PRICE_CACHE = HOME / "cache"
EDGAR_DIR = HOME / "edgar"


def _price_frame(ticker: str, as_of: str) -> tuple[pd.DataFrame | None, str]:
    """取价格序列（截到 as_of 当日），返回 (frame, 来源说明)。"""
    cands = sorted(PRICE_CACHE.glob(f"{ticker}-YFin-data-*.csv"))
    for c in cands:
        try:
            df = pd.read_csv(c, parse_dates=["Date"])
        except Exception:  # noqa: BLE001
            continue
        df = df[df["Date"] <= as_of].sort_values("Date").reset_index(drop=True)
        if len(df) >= 200:  # 少于 200 根无法算 200SMA，视为不可用
            return df, f"{c.name}（{len(df)} 根，止于 {df['Date'].iloc[-1].date()}）"
    return None, f"未找到可用价格序列（候选 {len(cands)} 个）"


def _edgar_shares(ticker: str, as_of: str) -> tuple[dict | None, dict | None, str]:
    """取 EDGAR 的已发行股数与稀释加权股数（各自取 end <= as_of 的最新披露）。"""
    files = sorted(EDGAR_DIR.glob(f"facts_{ticker}_*.json"))
    if not files:
        return None, None, f"未找到 EDGAR 缓存（{EDGAR_DIR}）"
    f = files[-1]
    try:
        facts = json.loads(f.read_text(encoding="utf-8")).get("facts", {})
    except Exception as e:  # noqa: BLE001
        return None, None, f"EDGAR 解析失败：{type(e).__name__}"

    def pick(tax: str, tag: str, unit: str):
        try:
            arr = facts[tax][tag]["units"][unit]
        except KeyError:
            return None
        # ★ 2026-10-22：PIT 必须**同时**看披露日 —— 只看 `end` 会选到基准日之后才申报的
        #   报表（10-K 期末 10-31、申报 12-15，基准日 11-15 那天市场还看不到它）。
        #   量化上这叫 look-ahead bias，第一原则禁止。缺 `filed` 的条目从宽保留。
        ok = [r for r in arr
              if str(r.get("end", "")) <= as_of and str(r.get("filed", "")) <= as_of]
        if not ok:
            return None
        return max(ok, key=lambda x: (x["end"], x.get("filed", "")))

    sh = pick("dei", "EntityCommonStockSharesOutstanding", "shares")
    dil = pick("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", "shares")
    return sh, dil, f"{f.name}"


def selfcalc(
    ticker: str,
    as_of: str,
    *,
    fy_net_income: float | None = None,
    fy_revenue: float | None = None,
    fy_equity: float | None = None,
    ttm_net_income: float | None = None,
    ttm_revenue: float | None = None,
) -> dict:
    """自算 point-in-time 估值。返回 dict；任何一项取不到就置 None 并记录原因。"""
    ticker = ticker.upper()
    out: dict = {"ticker": ticker, "as_of": as_of, "sources": {}, "notes": []}

    px, px_src = _price_frame(ticker, as_of)
    out["sources"]["price"] = px_src
    if px is None:
        out["notes"].append("价格序列不可用 ⇒ 本模块无法自算，请退回 vendor 快照口径")
        return out

    close = float(px["Close"].iloc[-1])
    out["close"] = close
    out["close_date"] = str(px["Date"].iloc[-1].date())

    w = px.tail(252)
    out["high_52w"] = float(w["High"].max())
    out["low_52w"] = float(w["Low"].min())
    out["ma50"] = float(px["Close"].tail(50).mean())
    out["ma200"] = float(px["Close"].tail(200).mean())
    r = np.diff(np.log(px["Close"].tail(253).to_numpy()))
    out["vol_annual"] = float(np.std(r, ddof=1) * np.sqrt(252))

    sh, dil, edgar_src = _edgar_shares(ticker, as_of)
    out["sources"]["edgar"] = edgar_src
    if sh:
        out["shares_outstanding"] = sh["val"]
        out["shares_asof"] = f"{sh['end']}（{sh['form']}，filed {sh.get('filed','?')}）"
        out["market_cap"] = close * sh["val"]
    else:
        out["notes"].append("EDGAR 未提供已发行股数 ⇒ 市值不可自算")
    if dil:
        out["shares_diluted"] = dil["val"]
        out["shares_diluted_asof"] = f"{dil['end']}（{dil['form']}）"
        out["market_cap_diluted"] = close * dil["val"]

    mc = out.get("market_cap")
    if mc:
        if fy_net_income:
            out["pe_fy"] = mc / fy_net_income
        if fy_revenue:
            out["ps_fy"] = mc / fy_revenue
        if fy_equity:
            out["pb_fy"] = mc / fy_equity
        if ttm_net_income:
            out["pe_ttm"] = mc / ttm_net_income
        if ttm_revenue:
            out["ps_ttm"] = mc / ttm_revenue
    return out


def render_markdown(out: dict, vendor: dict | None = None) -> str:
    """把自算结果渲染成 markdown 片段；给了 vendor 快照则附**对照表**（差异＝口径差异）。"""
    L: list[str] = []
    L.append("## 自算 point-in-time 估值（独立于 vendor 实时快照）")
    L.append("")
    L.append("> **为什么另立一节**：§3 走的是 yfinance `Ticker.info`，该接口无历史 vintage，")
    L.append("> 对历史基准日整节拒答。本节的**全部输入都有明确披露时点**，因此是真正的 point-in-time，")
    L.append("> 不是「当下值」。两源并列可互相校验；**差异处即口径差异，必须分别声明**。")
    L.append("")
    L.append(f"- 标的 / 基准日：**{out['ticker']} / {out['as_of']}**")
    L.append(f"- 价格来源：{out['sources'].get('price')}")
    L.append(f"- 股数来源：{out['sources'].get('edgar')}")
    if out.get("close") is not None:
        L.append(f"- 基准日收盘：**{out['close']:.4f}**（{out.get('close_date')}）")
    if out.get("shares_asof"):
        L.append(f"- 已发行股数：**{out['shares_outstanding']:,}**（披露时点 {out['shares_asof']}）")
    if out.get("shares_diluted_asof"):
        L.append(f"- 稀释加权股数：**{out['shares_diluted']:,}**（{out['shares_diluted_asof']}）")
    L.append("")

    rows = [
        ("市值", out.get("market_cap"), vendor.get("Market Cap") if vendor else None, lambda v: f"{v/1e9:.1f}B"),
        ("52 周高", out.get("high_52w"), vendor.get("52 Week High") if vendor else None, lambda v: f"{v:.2f}"),
        ("52 周低", out.get("low_52w"), vendor.get("52 Week Low") if vendor else None, lambda v: f"{v:.2f}"),
        ("50 日均价", out.get("ma50"), vendor.get("50 Day Average") if vendor else None, lambda v: f"{v:.2f}"),
        ("200 日均价", out.get("ma200"), vendor.get("200 Day Average") if vendor else None, lambda v: f"{v:.2f}"),
        ("PE(TTM)", out.get("pe_ttm"), vendor.get("PE Ratio (TTM)") if vendor else None, lambda v: f"{v:.2f}"),
        ("PS(TTM)", out.get("ps_ttm"), vendor.get("Price to Sales (TTM)") if vendor else None, lambda v: f"{v:.2f}"),
        ("PB", out.get("pb_fy"), vendor.get("Price to Book") if vendor else None, lambda v: f"{v:.2f}"),
        ("PE(FY)", out.get("pe_fy"), None, lambda v: f"{v:.2f}"),
        ("PS(FY)", out.get("ps_fy"), None, lambda v: f"{v:.2f}"),
    ]
    L.append("| 指标 | 自算 | vendor 快照 | 差异 |")
    L.append("|---|---|---|---|")
    for name, a, b, fmt in rows:
        sa = fmt(a) if a is not None else "—"
        sb = fmt(b) if b is not None else "—"
        if a is not None and b:
            diff = f"{(a/b - 1) * 100:+.2f}%"
        else:
            diff = "—"
        L.append(f"| {name} | {sa} | {sb} | {diff} |")
    L.append("")
    if out.get("vol_annual") is not None:
        L.append(f"- 自算年化波动率（252 日对数收益）：**{out['vol_annual']*100:.2f}%**")
    L.append("")
    L.append("**口径提示**：")
    L.append("- 自算市值用**已发行股数**（EDGAR `EntityCommonStockSharesOutstanding`），"
             "与 vendor 的 `impliedSharesOutstanding` 口径可能不同；若两者一致则无歧义。")
    L.append("- 自算 **PB** 的分母是**报表权益**（FY 期末）。vendor 的 `priceToBook` 可能用不同权益基数 —— "
             "**差异大时以报表自算为准**（报表口径可追溯到具体期末日）。")
    L.append("- 自算 **PE/PS** 的分母由调用方传入（来自证据包 §4 的报表值），不是 vendor 的 TTM 口径。")
    if out.get("notes"):
        L.append("")
        L.append("**降级/说明**：")
        for n in out["notes"]:
            L.append(f"- {n}")
    return "\n".join(L) + "\n"
