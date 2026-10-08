# lifecycle: reusable
# created: 2026-09-29
# usage: ./.venv/Scripts/python.exe wb_analysis/collect_treasury.py --date 2026-09-28
"""采集**美债收益率曲线**（FRED）—— 项目首个宏观专题采集器（非 12 角色标的链路）。

## 为什么单独建

项目原有 FRED 通道（`collect.py` §10）只取 **5 个**宏观指标，其中美债**仅 10Y 一个期限**，
且它服务的是个股/指数的 ERP 计算，**做不了曲线分析**。本采集器补齐期限结构。

## 采集清单

| 类别 | FRED series |
|---|---|
| 收益率曲线（11 个期限） | DGS1MO / DGS3MO / DGS6MO / DGS1 / DGS2 / DGS3 / DGS5 / DGS7 / DGS10 / DGS20 / DGS30 |
| 期限利差 | T10Y2Y（10Y−2Y）｜T10Y3M（10Y−3M） |
| 实际收益率（TIPS） | DFII5 / DFII10 / DFII30 |
| 通胀预期 | T10YIE（10 年盈亏平衡）｜T5YIFR（5 年 5 年远期） |
| 政策利率 | EFFR（有效联邦基金，日度）｜DFF |

## 三个必须遵守的口径纪律

1. **★ 逐 series 记录「最新观测日」**：FRED 各序列发布节奏不同，**最新日期可能不一致**
   （实测 DGS5 停在 09-25、T10Y2Y 到 09-28）。**不得**默认它们同一天，必须逐条声明。
2. **★ H.15 系列发布滞后约 1 个工作日**：若最新日 < 基准日，属**正常滞后**而非缺数据，
   须在证据包中区分「滞后」与「缺失」。
3. **★ 绝对值与变化率分开写**：收益率是**百分点**量纲，**不得**表述为"涨幅百分比"而不注明基准
   （如 +0.49 在 4.49 的基数上是 +10.91%，但说"上涨 10.91%"容易被误读为收益率到 4.98% 的 10.91 倍）。

## 输出

`wb_analysis/evidence/TREASURY_<date>.md`（+ 同名 .json 结构化副本）
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tradingagents.dataflows import fred  # noqa: E402

OUT_DIR = ROOT / "wb_analysis" / "evidence"

# (FRED series, 中文名, 类别)
SERIES: list[tuple[str, str, str]] = [
    ("DGS1MO", "1 个月", "curve"),
    ("DGS3MO", "3 个月", "curve"),
    ("DGS6MO", "6 个月", "curve"),
    ("DGS1", "1 年", "curve"),
    ("DGS2", "2 年", "curve"),
    ("DGS3", "3 年", "curve"),
    ("DGS5", "5 年", "curve"),
    ("DGS7", "7 年", "curve"),
    ("DGS10", "10 年", "curve"),
    ("DGS20", "20 年", "curve"),
    ("DGS30", "30 年", "curve"),
    ("T10Y2Y", "10Y − 2Y 利差", "spread"),
    ("T10Y3M", "10Y − 3M 利差", "spread"),
    ("DFII5", "5 年实际收益率(TIPS)", "real"),
    ("DFII10", "10 年实际收益率(TIPS)", "real"),
    ("DFII30", "30 年实际收益率(TIPS)", "real"),
    ("T10YIE", "10 年盈亏平衡通胀", "inflation"),
    ("T5YIFR", "5年5年远期通胀预期", "inflation"),
    ("EFFR", "有效联邦基金利率", "policy"),
    ("DFF", "联邦基金利率(日度)", "policy"),
]

_CAT_TITLE = {
    "curve": "一、收益率曲线（11 个期限）",
    "spread": "二、期限利差",
    "real": "三、实际收益率（TIPS）",
    "inflation": "四、通胀预期",
    "policy": "五、政策利率",
}

# 从 FRED markdown 里抠「Latest: 4.98 (2026-09-25) | Change over window: +0.49 (+10.91%) from 4.49」
_LATEST = re.compile(r"\*\*Latest:\*\*\s*([-\d.]+)\s*\(([\d-]+)\)")
_CHANGE = re.compile(r"\*\*Change over window:\*\*\s*([+\-]?[\d.]+)\s*\(([+\-]?[\d.]+)%\)\s*from\s*([-\d.]+)")


def fetch(sid: str, date: str, lookback: int) -> dict:
    """取单个 series。返回 dict；失败时 status 记 error（不抛，保证整批可继续）。"""
    try:
        raw = fred.get_macro_data(sid, date, lookback)
    except Exception as e:  # noqa: BLE001
        return {"series": sid, "status": "error", "error": f"{type(e).__name__}: {e}"}
    if "<unavailable" in raw.lower():
        return {"series": sid, "status": "unavailable"}
    m_lat, m_chg = _LATEST.search(raw), _CHANGE.search(raw)
    if not m_lat:
        return {"series": sid, "status": "parse_failed", "raw_head": raw[:300]}
    val, obs_date = float(m_lat.group(1)), m_lat.group(2)
    rec = {"series": sid, "status": "ok", "latest": val, "latest_date": obs_date}
    if m_chg:
        rec.update(
            change=float(m_chg.group(1)),
            change_pct=float(m_chg.group(2)),
            from_val=float(m_chg.group(3)),
        )
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="采集美债收益率曲线（FRED）")
    ap.add_argument("--date", required=True, help="基准日 YYYY-MM-DD")
    ap.add_argument("--lookback", type=int, default=40, help="回溯自然日数（默认 40）")
    args = ap.parse_args(argv)
    date, lookback = args.date, args.lookback

    rows = []
    for sid, name, cat in SERIES:
        rec = fetch(sid, date, lookback)
        rec.update(cn=name, cat=cat)
        rows.append(rec)
        mark = "✓" if rec["status"] == "ok" else "✗"
        extra = (
            f"{rec['latest']} ({rec['latest_date']}) Δ{rec.get('change', '?')}"
            if rec["status"] == "ok"
            else rec["status"]
        )
        print(f"  {mark} {sid:8} {name:22} {extra}")

    ok = [r for r in rows if r["status"] == "ok"]
    by_series = {r["series"]: r for r in ok}

    # --- 曲线形态（仅在期限齐全时计算）---
    shape = {}
    ten, two = by_series.get("DGS10"), by_series.get("DGS2")
    if ten and two:
        shape["10y_minus_2y_manual"] = round(ten["latest"] - two["latest"], 4)
    if "T10Y2Y" in by_series:
        shape["10y_minus_2y_fred"] = by_series["T10Y2Y"]["latest"]
    if "T10Y3M" in by_series:
        shape["10y_minus_3m_fred"] = by_series["T10Y3M"]["latest"]
    if ten and "DGS3MO" in by_series:
        shape["10y_minus_3m_manual"] = round(ten["latest"] - by_series["DGS3MO"]["latest"], 4)
    if ten and "DFII10" in by_series and "T10YIE" in by_series:
        shape["dfii10_plus_t10yie"] = round(by_series["DFII10"]["latest"] + by_series["T10YIE"]["latest"], 4)
        shape["nominal_minus_breakeven_dfii10"] = round(ten["latest"] - shape["dfii10_plus_t10yie"], 4)

    # --- 各期限最新观测日是否一致（★ 口径纪律 1）---
    dates = {r["series"]: r["latest_date"] for r in ok}
    unique_dates = sorted(set(dates.values()))

    # --- 渲染 ---
    L: list[str] = []
    L.append(f"# 证据包：美债收益率曲线（FRED）· 基准日 {date}")
    L.append("")
    L.append(f"- 采集时刻：{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}（北京时间）")
    L.append(f"- 数据源：**FRED**（St. Louis Fed），`tradingagents.dataflows.fred` 封装，逐 series 原始取数")
    L.append(f"- 回溯窗口：{lookback} 自然日")
    L.append(f"- 通道健康度：**{len(ok)}/{len(rows)}**")
    L.append("")
    L.append("## 0. ★★ 先读本节：三条口径纪律")
    L.append("")
    L.append("**① 各 series 的最新观测日可能不同**（FRED 各序列发布节奏不一致）。")
    L.append(f"本次实测的最新观测日集合：`{unique_dates}`")
    if len(unique_dates) > 1:
        L.append(f"⇒ **存在 {len(unique_dates)} 个不同的最新日** ⇒ 跨序列比较时必须逐条注明日期，"
                 "**不得**默认它们同日。")
    L.append("")
    L.append("**② H.15 系列（DGS*/T10Y*）发布滞后约 1 个工作日** ⇒ 最新日 < 基准日属**正常滞后**，"
             "与「缺数据」是两回事，引用时须声明。")
    L.append("")
    L.append("**③ 收益率是「百分点」量纲** ⇒ 变化须写清绝对值与基数（如 `+0.49 个百分点，"
             "自 4.49 起`），**不得**只说「上涨 10.91%」而不给基准。")
    L.append("")
    L.append("## 1. 逐 series 原始读数")
    L.append("")
    L.append("| FRED | 名称 | 最新值(%) | 观测日 | 窗口变化(pp) | 起点值(%) | 状态 |")
    L.append("|---|---|---|---|---|---|---|")
    for r in rows:
        if r["status"] == "ok":
            L.append(
                f"| `{r['series']}` | {r['cn']} | **{r['latest']}** | {r['latest_date']} | "
                f"{r.get('change', '—')} | {r.get('from_val', '—')} | ✓ |"
            )
        else:
            L.append(f"| `{r['series']}` | {r['cn']} | — | — | — | — | ✗ {r['status']} |")
    L.append("")

    for cat, title in _CAT_TITLE.items():
        grp = [r for r in ok if r["cat"] == cat]
        if not grp:
            continue
        L.append(f"## {title}")
        L.append("")
        if cat == "curve":
            L.append("| 期限 | 收益率(%) | 观测日 | 窗口变化(pp) |")
            L.append("|---|---|---|---|")
            for r in grp:
                L.append(f"| {r['cn']} | **{r['latest']}** | {r['latest_date']} | {r.get('change', '—')} |")
            L.append("")
            L.append("**曲线形态**（相邻期限比较，全部用上表原始值）：")
            seq = [r for r in grp if r["latest"] is not None]
            for a, b in zip(seq, seq[1:]):
                d = round(b["latest"] - a["latest"], 4)
                flag = "↑" if d > 0 else ("↓" if d < 0 else "=")
                L.append(f"- {a['cn']} → {b['cn']}：{a['latest']} → {b['latest']}　**{flag} {d:+.4f} pp**")
        elif cat == "spread":
            for r in grp:
                L.append(f"- **{r['cn']}**（`{r['series']}`）：**{r['latest']}%**（{r['latest_date']}），"
                         f"窗口变化 {r.get('change', '—')} pp")
            L.append("")
            L.append("⇒ 利差为正 = 正常形态；为负 = **倒挂**。请以本表数值判断，不要凭记忆。")
        elif cat == "real":
            for r in grp:
                L.append(f"- **{r['cn']}**：**{r['latest']}%**（{r['latest_date']}），窗口变化 {r.get('change', '—')} pp")
        elif cat == "inflation":
            for r in grp:
                L.append(f"- **{r['cn']}**：**{r['latest']}%**（{r['latest_date']}），窗口变化 {r.get('change', '—')} pp")
            if "dfii10_plus_t10yie" in shape:
                L.append("")
                L.append("**费雪恒等式自检**（名义 ≈ 实际 + 通胀预期）：")
                L.append(f"- DFII10 {by_series['DFII10']['latest']} + T10YIE {by_series['T10YIE']['latest']}"
                         f" = **{shape['dfii10_plus_t10yie']}**")
                L.append(f"- DGS10 实测 **{ten['latest']}** ⇒ 差额 **{shape['nominal_minus_breakeven_dfii10']:+.4f} pp**")
                L.append("- ⚠️ 差额应接近 0（该恒等式在 TIPS 与盈亏平衡口径下近似成立）；"
                         "若偏差大，说明 **两者观测日不同**（见 §0 纪律①），不得当作矛盾。")
        else:
            for r in grp:
                L.append(f"- **{r['cn']}**：**{r['latest']}%**（{r['latest_date']}），窗口变化 {r.get('change', '—')} pp")
        L.append("")

    if shape:
        L.append("## 六、派生量（全部可复算）")
        L.append("")
        for k, v in shape.items():
            L.append(f"- `{k}` = **{v}**")
        L.append("")

    out_md = OUT_DIR / f"TREASURY_{date}.md"
    out_js = OUT_DIR / f"TREASURY_{date}.json"
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    out_js.write_text(
        json.dumps({"date": date, "ok": len(ok), "total": len(rows), "series": rows, "shape": shape,
                    "latest_dates": dates}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[输出] {out_md}")
    print(f"[输出] {out_js}")
    print(f"[通道] {len(ok)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
