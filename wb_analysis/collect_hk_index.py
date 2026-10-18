# lifecycle: reusable
# created: 2026-09-30
# usage: ./.venv/Scripts/python.exe wb_analysis/collect_hk_index.py --index hkHSTECH
"""采集**港股指数**证据（westock CLI）—— 项目首个港股链路。

## 为什么单独建

- 项目 `collect_index.py` 只支持 **NDX / SPX**（美股）
- 项目代码对港股**零支持**（grep 零命中），DOMAINS.md 亦无港股章节
- westock CLI 支持港股指数（`hkHSSTECH` / `hkHSI` / `hkHSCEI`），但**项目侧无封装**

## ★★ 三条必须遵守的口径纪律

1. **指数本身没有 PE/PB**：`quote hkHSTECH` 的 `pe_ratio` / `pb_ratio` **恒为 0**（字段存在但无值）。
   ⇒ 估值必须**从成分股聚合**得到。聚合式（铁律 11）：`指数PE = Σ市值 / Σ净利润`，
   **绝不可对成分股 PE 做算术平均**。
2. **★ 负 PE / 亏损成分股必须剔除并单独披露**：实测美团 PE = **−10**（亏损）。
   若把负 PE 计入 `Σ(市值/PE)`，会算出**负的指数 PE**（荒谬）。
   ⇒ 聚合前必须过滤 `PE > 0`，并**记录被剔除的只数与其市值占比**。
3. **`fund flow` 对港股指数返回全 0**（字段存在、值为 0）⇒ 属"返回了但为空"的**静默失败**（铁律 3），
   **必须判为「不支持」**，不得表述为「资金流为零」。

## 采集清单

| 通道 | 命令 | 备注 |
|---|---|---|
| 指数行情 | `quote <index>` | 含 52 周区间、YTD、阶段收益 |
| 日线 | `kline <index> --period day --limit N` | |
| 技术指标 | `technical <index>` | 全套 MA/MACD/KDJ/RSI/BOLL |
| 成分股列表 | `index constituent <index>` | 含涨跌幅、成交额 |
| 成分股行情 | `quote <code1,code2,...>` | **批量**，取 PE/PB/市值 |
| 新闻 | `news list <index> --limit N` | 仅有标题 |
| 资金流 | `fund flow <index>` | ⚠️ 对港指**恒为 0** |

## 输出

`wb_analysis/evidence/<INDEX>_<date>.md`（+ .json）
**原始输出原样保留**（便于人工复核），聚合值另列一节并附算式。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "wb_analysis" / "evidence"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# westock CLI 的统一接入层（路径解析 + 调用 + 表格解析）。
# ★ 2026-10-10：本文件与 `collect_a_etf.py` 曾**逐字各存一份** run_westock/parse_md_table，
#   且各自硬编码 `<用户主目录>\.local\bin\westock.exe`（机器特定）⇒ 抽出共享模块。
from wb_analysis._westock import WESTOCK, parse_md_table, run_westock  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="采集港股指数证据（westock）")
    ap.add_argument("--index", default="hkHSTECH", help="指数代码，默认 hkHSTECH")
    ap.add_argument("--date", required=True, help="基准日 YYYY-MM-DD")
    ap.add_argument("--kline-n", type=int, default=20)
    ap.add_argument("--news-n", type=int, default=10)
    args = ap.parse_args(argv)
    idx, date = args.index, args.date

    print(f"[港股指数采集] {idx}  基准日 {date}")
    if not WESTOCK.exists():
        print(f"  ✗ westock 不存在：{WESTOCK}")
        return 1

    raw: dict[str, str] = {}
    for name, cmd in [
        ("quote", ["quote", idx]),
        ("kline", ["kline", idx, "--period", "day", "--limit", str(args.kline_n)]),
        ("technical", ["technical", idx]),
        ("constituent", ["index constituent", idx]),
        ("news", ["news list", idx, "--limit", str(args.news_n)]),
        ("fund_flow", ["fund flow", idx]),
    ]:
        sub = cmd[0].split() + cmd[1:] if " " in cmd[0] else cmd
        raw[name] = run_westock(sub)
        ok = "<westock" not in raw[name] and raw[name].strip()
        print(f"  {'✓' if ok else '✗'} {name:12} {len(raw[name])} 字符")

    # --- 指数行情 ---
    h, b = parse_md_table(raw["quote"])
    quote = dict(zip(h, b[0])) if h and b else {}

    # --- 成分股 ---
    codes = re.findall(r"hk\d{5}", raw["constituent"])
    codes = list(dict.fromkeys(codes))  # 去重保序
    cons_raw = run_westock(["quote", ",".join(codes)]) if codes else ""
    raw["constituent_quotes"] = cons_raw  # ★ 必须落盘：否则成分股级字段（如 chg_ytd）不可复算
    ch, cb = parse_md_table(cons_raw)
    cons = [dict(zip(ch, r)) for r in cb]

    # --- 指数级估值聚合（★ 铁律 11）---
    def f(x: str) -> float | None:
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    rows: list[dict] = []
    for c in cons:
        pe, pb, mv = f(c.get("pe_ratio", "")), f(c.get("pb_ratio", "")), f(c.get("total_market_cap", ""))
        rows.append({"code": c.get("code"), "name": c.get("name"), "price": f(c.get("price", "")),
                     "pe": pe, "pb": pb, "mktcap": mv, "chg_pct": c.get("change_percent"),
                     "chg_ytd": f(c.get("chg_ytd", "")), "chg_5d": f(c.get("chg_5d", "")),
                     "chg_20d": f(c.get("chg_20d", ""))})

    valid_pe = [r for r in rows if r["pe"] and r["pe"] > 0 and r["mktcap"]]
    dropped = [r for r in rows if r not in valid_pe]
    total_mv = sum(r["mktcap"] for r in rows if r["mktcap"])
    # Σ市值 / Σ(市值/PE) —— 等价于 Σ市值 / Σ净利润
    agg = {}
    if valid_pe:
        sum_mv = sum(r["mktcap"] for r in valid_pe)
        sum_earn = sum(r["mktcap"] / r["pe"] for r in valid_pe)
        agg["pe_aggregate"] = round(sum_mv / sum_earn, 2) if sum_earn > 0 else None
        agg["sum_mktcap_valid"] = round(sum_mv, 2)
        agg["sum_earnings_implied"] = round(sum_earn, 2)
    valid_pb = [r for r in rows if r["pb"] and r["pb"] > 0 and r["mktcap"]]
    if valid_pb:
        agg["pb_aggregate"] = round(
            sum(r["mktcap"] for r in valid_pb) / sum(r["mktcap"] / r["pb"] for r in valid_pb), 2)
        agg["pb_valid_count"] = len(valid_pb)
    agg["components_total"] = len(rows)
    agg["components_with_positive_pe"] = len(valid_pe)
    agg["dropped"] = [{"code": r["code"], "name": r["name"], "pe": r["pe"],
                       "mktcap": r["mktcap"]} for r in dropped]
    if total_mv:
        agg["dropped_mktcap_share_pct"] = round(
            sum(r["mktcap"] for r in dropped if r["mktcap"]) / total_mv * 100, 3)

    # --- 资金流是否真的可用（★ 纪律 3）---
    fh, fb = parse_md_table(raw["fund_flow"])
    fund_usable = False
    if fh and fb:
        fund_usable = any(f(v) not in (None, 0) for v in fb[0])

    # --- 渲染 ---
    L: list[str] = []
    L.append(f"# 证据包：{idx}（港股指数）· 基准日 {date}")
    L.append("")
    L.append(f"- 采集时刻：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}（北京时间）")
    L.append(f"- 数据源：**westock CLI**（腾讯自选股接口），逐通道原始取数")
    L.append(f"- 指数名称：{quote.get('name', '?')}")
    L.append("")
    L.append("## 0. ★★ 三条口径纪律（先读）")
    L.append("")
    L.append("**① 指数本身无 PE/PB**：`quote` 的 `pe_ratio`/`pb_ratio` 恒为 0 ⇒ 估值必须**从成分股聚合**。")
    L.append("   聚合式（铁律 11）：`指数PE = Σ市值 / Σ净利润`（净利_i = 市值_i / PE_i），**不可算术平均**。")
    L.append("")
    L.append("**② 负 PE / 亏损成分股必须剔除**：本表已过滤 `PE > 0`，被剔除者**单独列出**。")
    L.append(f"   ⇒ 本次剔除 **{len(dropped)} 只**，占成分总市值 **{agg.get('dropped_mktcap_share_pct', '?')}%**。")
    L.append("")
    L.append(f"**③ `fund flow` 对港股指数**：本次判定 **{'可用' if fund_usable else '★ 不可用（全 0，属静默失败）'}**。")
    L.append("")
    L.append("## 1. 指数行情")
    L.append("")
    if quote:
        for k in ("code", "name", "price", "prev_close", "open", "high", "low",
                  "change", "change_percent", "low_52week", "high_52week",
                  "chg_5d", "chg_10d", "chg_20d", "chg_60d", "chg_ytd", "time"):
            if k in quote:
                L.append(f"- {k}: **{quote[k]}**")
    else:
        L.append("（解析失败，见附录原始输出）")
    L.append("")
    if quote.get("price") and quote.get("low_52week") and quote.get("high_52week"):
        p_, lo, hi = f(quote["price"]), f(quote["low_52week"]), f(quote["high_52week"])
        if p_ and lo and hi:
            L.append(f"**区间位置**：距 52 周低 {lo} 为 **{(p_/lo-1)*100:+.2f}%**；"
                     f"距 52 周高 {hi} 为 **{(p_/hi-1)*100:+.2f}%**")
            L.append("")
    L.append("## 2. 技术指标（原始）")
    L.append("")
    L.append("```")
    L.append(raw["technical"].strip()[:1200])
    L.append("```")
    L.append("")
    L.append("## 3. 成分股（原始行情）")
    L.append("")
    L.append(f"- 成分股只数：**{len(rows)}**")
    L.append("")
    L.append("| 代码 | 名称 | 价格 | PE | PB | 市值(亿) | 当日涨跌% | **YTD%** | 5日% | 20日% |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        L.append(f"| {r['code']} | {r['name']} | {r['price']} | {r['pe']} | {r['pb']} | "
                 f"{r['mktcap']} | {r['chg_pct']} | **{r.get('chg_ytd')}** | "
                 f"{r.get('chg_5d')} | {r.get('chg_20d')} |")
    L.append("")
    L.append("## 4. ★ 指数级估值聚合（可复算）")
    L.append("")
    for k, v in agg.items():
        if k == "dropped":
            continue
        L.append(f"- `{k}` = **{v}**")
    L.append("")
    if valid_pe:
        L.append("**剔除明细**（PE ≤ 0 或市值缺失）：")
        for d in agg.get("dropped", []):
            L.append(f"  - {d['code']} {d['name']}：PE={d['pe']}，市值={d['mktcap']}")
        L.append("")
        L.append("**聚合算式**：")
        L.append(f"- Σ市值（有效 {len(valid_pe)} 只）= **{agg.get('sum_mktcap_valid')}**")
        L.append(f"- Σ净利润（= Σ 市值_i/PE_i）= **{agg.get('sum_earnings_implied')}**")
        L.append(f"- 指数 PE = {agg.get('sum_mktcap_valid')} ÷ {agg.get('sum_earnings_implied')}"
                 f" = **{agg.get('pe_aggregate')}**")
        L.append("")
    L.append("## 5. 新闻（仅标题）")
    L.append("")
    nh, nb = parse_md_table(raw["news"])
    if nh and nb:
        ti = nh.index("title") if "title" in nh else -1
        for r in nb:
            if 0 <= ti < len(r):
                L.append(f"- {r[ti]}")
    else:
        L.append("（无）")
    L.append("")
    L.append("## 6. 资金流")
    L.append("")
    L.append(f"⚠️ **判定：{'可用' if fund_usable else '不可用'}** —— 原始输出如下：")
    L.append("")
    L.append("```")
    L.append(raw["fund_flow"].strip()[:800])
    L.append("```")
    L.append("")
    L.append("## 7. 附录：原始输出（供人工复核）")
    L.append("")
    for name in ("quote", "kline", "constituent", "constituent_quotes"):
        L.append(f"### {name}")
        L.append("")
        L.append("```")
        L.append(raw[name].strip()[:2500])
        L.append("```")
        L.append("")

    out_md = OUT_DIR / f"{idx.upper()}_{date}.md"
    out_js = OUT_DIR / f"{idx.upper()}_{date}.json"
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    out_js.write_text(json.dumps(
        {"index": idx, "date": date, "quote": quote, "components": rows,
         "aggregate": agg, "fund_flow_usable": fund_usable, "raw": raw},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[输出] {out_md}")
    print(f"[聚合] 指数PE={agg.get('pe_aggregate')}  剔除 {len(dropped)} 只"
          f"（占市值 {agg.get('dropped_mktcap_share_pct')}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
