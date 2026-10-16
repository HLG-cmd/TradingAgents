# lifecycle: reusable
# created: 2026-10-13
# usage: ./.venv/Scripts/python.exe wb_analysis/_derive_a_etf.py 515100 2026-10-13
"""A股 ETF 派生指标计算器：从 A 股 ETF 证据包导出「需要算术推导」的二级指标。

## 为什么单独写一个（而不是复用 `_derive_stock.py`）

`_derive_stock.py` 面向**美股个股**证据包（yfinance 格式：`close_50_sma` / `boll_ub` /
`atr` / `## 3 基本面快照`…），而 A 股 ETF 证据包是**另一套 schema**（westock 格式：
`MA_5`/`BOLL_UPPER`/`RSI_6`/`chipAvgCost`/`etf overview`…）。两者的指标名、章节号、
币种单位全都不同 ⇒ 硬套会静默解出空值（铁律 3 那类失败）。

## 它做什么

只做**算术推导**，不产生任何新数据（全部输入来自证据包）：

1. **铁律 24 自检**：对每个 `MA_N`，先判 N ≤ 可得 K 线根数；再用**最后 N 根收盘的算术均值**
   复算该均线。若声称值 ≈ 全部根数的均值 ⇒ 判「上市以来累加均值冒充固定窗口」。
2. **位置与通道**：%B（布林带内位置）、带宽占比、各均线偏离度。
3. **波动率**：ATR 代理（近 14/20 日平均日内振幅）、HV20 / HV60（对数收益率年化）。
4. **收益与回撤**：5/10/20/60/日累计收益（与 quote 的 chg_ 字段交叉核对）、
   全窗口与近 60 日最大回撤。
5. **筹码偏离 / 关键价位**（由 K 线表导出）。

## 证据包格式注意（2026-10-13 实测踩坑）

A 股 ETF 证据包的 §1 行情 / §2 技术 / §2.3 筹码都是**代码块里的 `key: value` 行**，
而**不是** markdown 表格（表格只有日 K 线 / 持仓 / 净值和新闻几张）。
首版按表格解析 ⇒ 全部解出空值却仍报「成功」—— 正是本项目禁止的静默失败，
故此处显式按代码块解析，并在 H 节打印「各通道解析到的字段数」供人验。

## 输出

`wb_analysis/drafts/<TICKER>_<date>/0_derived.md`（目录不存在则创建）。
"""
from __future__ import annotations

import argparse
import math
import re
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "wb_analysis" / "evidence"
DRAFTS = ROOT / "wb_analysis" / "drafts"

#: 声称的均线窗口（单位：K 线根数）。键名与证据包 `technical` 段的字段名一致。
MA_WINDOWS = {"MA_5": 5, "MA_10": 10, "MA_20": 20, "MA_60": 60, "MA_120": 120, "MA_250": 250}
NUM_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def fnum(v, default=None):
    """取字符串里**第一个**数值 token；`1.424 (偏离度: +0.56%)` → 1.424。"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = NUM_RE.search(str(v))
    if not m:
        return default
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return default


def parse_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            cells = [[c.strip() for c in l.strip().strip("|").split("|")] for l in block]
            if len(cells) >= 2:
                tables.append((cells[0], cells[1:]))
        else:
            i += 1
    return tables


def find_table(tables, *must_have):
    for h, b in tables:
        if all(k in h for k in must_have):
            return h, b
    return None, None


def parse_code_blocks(text: str) -> list[str]:
    return re.findall(r"```[a-zA-Z0-9_]*\n(.*?)```", text, re.S)


def kv_from_block(block: str) -> dict[str, str]:
    """从代码块里的 `key: value` 行抽 kv；容忍 `  - 上轨: 1.437` 这类前缀。"""
    out: dict[str, str] = {}
    for line in block.splitlines():
        m = re.match(r"^\s*(?:-\s*)?([^:|：]+?)\s*[:：]\s*(.+?)\s*$", line)
        if m and m.group(1).strip():
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def find_kv(blocks: list[dict[str, str]], *must_have: str) -> dict[str, str]:
    for kv in blocks:
        if all(k in kv for k in must_have):
            return kv
    return {}


def build(ticker: str, date: str) -> int:
    src = EV / f"{ticker}_{date}.md"
    if not src.exists():
        print(f"  ✗ 证据包不存在: {src.relative_to(ROOT).as_posix()}")
        return 1
    text = src.read_text(encoding="utf-8", errors="replace")

    tables = parse_tables(text)
    blocks = [kv_from_block(b) for b in parse_code_blocks(text)]
    quote = find_kv(blocks, "收盘价")
    # §2.1（均线/布林）与 §2.2（MACD/KDJ/RSI）是**两个独立代码块** ⇒ 必须合并，
    # 否则要求「单块同时含 MA_5 与 RSI_6」会永远解空（首版即此错）。
    tech = {**find_kv(blocks, "MA_5"), **find_kv(blocks, "RSI_6")}
    chip = find_kv(blocks, "筹码平均成本")

    # ---- K 线（唯一的 markdown 表格） ----
    h_k, b_k = find_table(tables, "date", "last", "high", "low")
    closes, highs, lows, dates = [], [], [], []
    if b_k:
        ilast, ihigh, ilow, idate = h_k.index("last"), h_k.index("high"), h_k.index("low"), h_k.index("date")
        for r in reversed(b_k):  # 表按时间倒序 ⇒ 反转为由旧到新
            c = fnum(r[ilast])
            if c is None:
                continue
            closes.append(c)
            dates.append(r[idate])
            hi, lo = fnum(r[ihigh]), fnum(r[ilow])
            if hi is not None:
                highs.append(hi)
            if lo is not None:
                lows.append(lo)

    close = fnum(quote.get("收盘价"))
    L: list[str] = []
    L.append(f"# {ticker} 派生指标（由 wb_analysis/_derive_a_etf.py 生成，可直接引用）")
    L.append("")
    L.append("```")
    L.append("=" * 78)
    L.append(f"{ticker}  基准日 {date}   （A股 ETF 派生层 · 全部为机算值）")
    L.append("=" * 78)
    L.append("")
    L.append("A. K 线基础与解析自检")
    L.append(f"   可得日线根数: {len(closes)}")
    if dates:
        L.append(f"   窗口: {dates[0]} ~ {dates[-1]}")
    if close is not None and closes:
        L.append(f"   最新收盘(quote): {close} ｜ K 线末根: {closes[-1]} ｜ "
                 f"{'一致' if abs(close - closes[-1]) < 1e-9 else '**不一致，须核对口径**'}")
    L.append(f"   解析字段数: quote={len(quote)} ｜ technical={len(tech)} ｜ chip={len(chip)}"
             f"（任一为 0 ⇒ 证据包格式已变，本文件不可信）")
    L.append("")

    # ---- B. 铁律 24 ----
    L.append("B. 铁律 24 自检（均线窗口 vs 可得 K 线根数；并逐条复算固定窗口均值）")
    ma: dict[str, float | None] = {}
    flagged: list[str] = []
    for name, win in MA_WINDOWS.items():
        claim = fnum(tech.get(name))
        ma[name] = claim
        if claim is None:
            L.append(f"   · {name} ({win}): 证据包未取到该字段")
            continue
        if win > len(closes):
            flagged.append(name)
            L.append(f"   ⛔ [铁律 24 真阳性] {name}：声称窗口 {win} > 可得 K 线 {len(closes)} 根 "
                     f"⇒ 算术上不可能 ⇒ 该指标作废")
            continue
        calc = statistics.fmean(closes[-win:])
        all_mean = statistics.fmean(closes)
        if abs(claim - calc) <= max(abs(calc) * 0.005, 1e-9):
            verdict = "✓ 与最后 N 根收盘均值一致 ⇒ 真固定窗口均线"
        elif len(closes) < win * 2 and abs(claim - all_mean) <= max(abs(all_mean) * 0.005, 1e-9):
            flagged.append(name)
            verdict = "⛔ 实为『全部可得 K 线均值』（上市以来累加均值冒充固定窗口）"
        else:
            verdict = "⚠ 与两种均值都不符（上游口径未知）⇒ 记**不可复算**，不作趋势锚"
        L.append(f"   · {name} ({win}): 声称 {claim:.6g} ｜ 固定窗口均值 {calc:.6g} ｜ {verdict}")
    L.append(f"   ⇒ 命中 {len(flagged)} 项" + (f"：{', '.join(flagged)}（禁止用于趋势/牛熊分界）"
                if flagged else "：全部可用均线均可由手边 K 线复算"))
    L.append("")

    # ---- C. 位置 ----
    L.append("C. 均线偏离 / 布林通道")
    if close is not None:
        for name in MA_WINDOWS:
            m = ma.get(name)
            if m:
                dead = "　⛔铁律24命中，一并作废" if name in flagged else ""
                L.append(f"   {name:8s} {m:<12.6g} 距现价 {(close - m) / m * 100:+7.3f}%{dead}")
    ts = {"上轨": None, "中轨": None, "下轨": None}
    for k in ts:
        ts[k] = fnum(tech.get(k))
    bu, bm, bl = ts["上轨"], ts["中轨"], ts["下轨"]
    if None not in (bu, bm, bl) and bu != bl:
        L.append(f"   布林: 上 {bu:.6g} / 中 {bm:.6g} / 下 {bl:.6g}")
        if close is not None:
            L.append(f"   %B（带内位置, 0=下轨 100=上轨）: {(close - bl) / (bu - bl) * 100:.3f}%")
            L.append(f"   现价距下轨: {(close - bl) / bl * 100:+.3f}% ｜ 距上轨: {(close - bu) / bu * 100:+.3f}%")
        L.append(f"   带宽（占中轨）: {(bu - bl) / bm * 100:.3f}%")
    L.append("")

    # ---- D. 波动率 ----
    L.append("D. 波动率（ATR 代理 / HV）")
    if close and len(highs) == len(lows) == len(closes):
        for w in (14, 20):
            if len(closes) >= w:
                atr = statistics.fmean([highs[i] - lows[i]
                                        for i in range(len(closes) - w, len(closes))])
                L.append(f"   近 {w} 日平均日内振幅（ATR 代理）: {atr:.6g} = 现价 {atr / close * 100:.3f}%")
    if len(closes) >= 21:
        rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        L.append(f"   HV20: {math.sqrt(252) * statistics.stdev(rets[-20:]) * 100:.3f}%")
        if len(rets) >= 60:
            L.append(f"   HV60: {math.sqrt(252) * statistics.stdev(rets[-60:]) * 100:.3f}%")
    L.append("")

    # ---- E. 收益与回撤 ----
    L.append("E. 累计收益（由 K 线复算；与 quote chg_ 字段交叉核对）")
    if len(closes) >= 2:
        for w in (5, 10, 20, 60):
            if len(closes) > w:
                r = (closes[-1] / closes[-(w + 1)] - 1) * 100
                q = fnum(quote.get(f"涨跌幅_{w}日") or quote.get(f"{w}日涨跌幅") or quote.get(f"chg_{w}d"))
                if q is None:
                    q = fnum(quote.get(f"{w}日涨跌幅"))
                cross = (f"  ｜ quote={q:+g}%  {'一致' if abs(q - r) < 0.6 else '**不一致**'}"
                         if q is not None else "")
                L.append(f"   近 {w:>3} 日: {r:+8.3f}%（{dates[-(w + 1)]} → {dates[-1]}）{cross}")
        peak, mdd, pk_d = closes[0], 0.0, dates[0]
        trough, tr_d = closes[0], dates[0]
        for i, c in enumerate(closes):
            if c > peak:
                peak, pk_d = c, dates[i]
            if c / peak - 1 < mdd:
                mdd, trough, tr_d = c / peak - 1, c, dates[i]
        L.append(f"   全窗口最大回撤: {mdd * 100:+.3f}%（峰 {pk_d} {peak:.6g} → 谷 {tr_d} {trough:.6g}）")
        if len(closes) >= 61:
            sub = closes[-60:]
            pk, m2 = sub[0], 0.0
            for c in sub:
                pk = max(pk, c)
                m2 = min(m2, c / pk - 1)
            L.append(f"   近 60 日最大回撤: {m2 * 100:+.3f}%")
    L.append("")

    # ---- F. 筹码 ----
    if chip:
        cac, pr = fnum(chip.get("筹码平均成本")), fnum(chip.get("获利盘比例"))
        c70, c90 = fnum(chip.get("70% 筹码集中度")), fnum(chip.get("90% 筹码集中度"))
        L.append("F. 筹码（取自证据包 chip 段，未复算）")
        if cac and close:
            L.append(f"   筹码平均成本: {cac:.6g}（现价相对 {(close - cac) / cac * 100:+.3f}%）")
        if pr is not None:
            L.append(f"   获利盘比例: {pr:.3f}%")
        L.append(f"   70%/90% 集中度: {c70:.3f}% / {c90:.3f}%" if None not in (c70, c90)
                 else f"   70%/90% 集中度: {chip.get('70% 筹码集中度', '—')} / {chip.get('90% 筹码集中度', '—')}")
        L.append("")

    # ---- G. 关键价位 ----
    L.append("G. 关键价位（由 K 线表导出，**非估值目标价**）")
    if closes:
        for w, tag in ((20, "近 20 日"), (60, "近 60 日")):
            if len(closes) >= w:
                seg = closes[-w:]
                L.append(f"   {tag}收盘 低/高: {min(seg):.6g} / {max(seg):.6g}（{dates[-w]} → {dates[-1]}）")
        if highs and lows:
            L.append(f"   全窗口盘中 低/高: {min(lows):.6g} / {max(highs):.6g}")
        # ★ 2026-10-16：52 周高低在 **历史日期模式** 下 quote 不返回（`--date` 只在当日快照里带
        #   `high_52week`/`low_52week`/`chg_ytd`，回看历史日时这三个字段整列缺失）。
        #   证据包 §1 因此显示 `[未取到]`，若不补，「距 52 周高低」这类关键价位判断会静默消失。
        #   ⇒ 由 K 线窗口机算补足（250 根 ≈ 52 周交易日），口径写清「按可得 K 线窗口」。
        if len(closes) >= 250:
            L.append(f"   近 250 根(≈52周)收盘 低/高: {min(closes[-250:]):.6g} / {max(closes[-250:]):.6g}"
                     f"（{dates[-250]} → {dates[-1]}）")
            if highs and lows and len(highs) >= 250:
                L.append(f"   近 250 根(≈52周)盘中 低/高: {min(lows[-250:]):.6g} / {max(highs[-250:]):.6g}")
                hi52, lo52 = max(highs[-250:]), min(lows[-250:])
                if close:
                    L.append(f"   现价距 52周高/低: {(close - hi52) / hi52 * 100:+.3f}% / "
                             f"{(close - lo52) / lo52 * 100:+.3f}%")
        else:
            L.append(f"   ⚠ 52 周高低未计算：可得 K 线仅 {len(closes)} 根 < 250 ⇒ 窗口不足（铁律 24）")
    L.append("")

    # ---- H. 口径 ----
    L.append("H. 口径与不可用项（下游引用前必读）")
    L.append(f"   · 铁律 24：{'命中 ' + ', '.join(flagged) + '（禁用）' if flagged else '无命中'}。")
    L.append("   · 证据包 kline 表 `exchange` 列实为**换手率(%)**（上游列名与语义不符），按换手率解。")
    L.append("   · 本文件只做算术推导；证据包未出现的数字（前瞻预测、一致预期明细、汇率折算）不得在此补。")
    L.append("```")
    L.append("")

    out_dir = DRAFTS / f"{ticker}_{date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "0_derived.md"
    content = "\n".join(L) + "\n"
    out.write_text(content, encoding="utf-8", newline="\n")
    print(f"  ⇒ 写入 {out.relative_to(ROOT).as_posix()}（{len(content)} 字符）")
    print(f"     K 线 {len(closes)} 根 ｜ quote={len(quote)} tech={len(tech)} chip={len(chip)} ｜ "
          f"铁律24 命中: {', '.join(flagged) if flagged else '无'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="A股 ETF 派生指标")
    ap.add_argument("pairs", nargs="*", help="<TICKER> <date> [TICKER date ...]")
    args = ap.parse_args()
    if len(args.pairs) < 2 or len(args.pairs) % 2:
        print(__doc__)
        return 2
    worst = 0
    for i in range(0, len(args.pairs), 2):
        print(f"===== {args.pairs[i]} {args.pairs[i + 1]}")
        worst = max(worst, build(args.pairs[i], args.pairs[i + 1]))
        print()
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
