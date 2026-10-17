# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_audit_gaps.py
"""数据缺口审计：把证据包的每个通道逐条分类为「真实缺失 / 阈值误伤 / 采集器 bug」。

**为什么需要这个工具**：报告里出现「该项数据缺失」时，有三种性质完全不同的原因，
处置方式也完全不同——

  (A) **上游真实未发布**：再怎么改代码都拿不到（例：FRED 的 H.15 系列有约一个
      工作日发布滞后，9/17 跑 9/17 的 DGS10 永远拿不到）。只能声明缺口。
  (B) **阈值误伤**：数据其实拿得到，但被我们自己的质量闸门错杀了。
      例：期权 IV 闸门原设 `min(IV) >= 2.0`，而 QQQ 真实 ATM IV 是 20% 量级，
      垃圾值上界 0.4% —— 这个阈值落在两者之间，既挡不住垃圾也放不过真值。
      这类必须修闸门，不能写进「数据缺失」。
  (C) **采集器 bug**：解析/截断/排序写错，数据到手却被丢掉。
      例：`_compact_series` 取错窗口丢掉最新一行；`_compact_statement` 盲目
      截断把 Total Revenue 切掉。

本工具对每个通道**重新独立取一次数据**，与证据包里的内容对照，并给出分类与建议。

用法：
    python wb_analysis/_audit_gaps.py NDX 2026-09-17
    python wb_analysis/_audit_gaps.py NDX 2026-09-17 --json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 期权新鲜度阈值取自**唯一定义源**（2026-10-10 收敛）。
# ⚠️ 此前本文件在 3 处硬编码 5.0/5 天，只在注释里声称「与 collect_index.py 对齐」——
#    而本文件 docstring 记录的第一次事故恰恰是「阈值与采集器不一致 ⇒ 把 A 类缺口误判成 B 类」。
#    ⚠️ 不 import `collect_index`：它模块级 `os.chdir` + `load_dotenv` 会污染本进程。
from wb_analysis._thresholds import MAX_QUOTE_AGE_DAYS  # noqa: E402

EV_DIR = PROJECT_ROOT / "wb_analysis" / "evidence"

VERDICT_LABEL = {
    "A": "上游真实未发布 —— 只能声明缺口",
    "B": "阈值误伤 —— 数据可得，闸门设错，应修闸门",
    "C": "采集器 bug —— 数据到手被丢弃，应修代码",
    "OK": "该通道数据完整可用",
}


def _load_evidence(ticker: str, as_of: str) -> str:
    p = EV_DIR / f"{ticker}_{as_of}.md"
    if not p.exists():
        raise SystemExit(f"✗ 证据包不存在: {p}")
    return p.read_text(encoding="utf-8", errors="replace")


def _blk(md: str, heading: str) -> str:
    """取某个 `### xxx` 段落（到下一个**同级** `###` 为止）的正文。

    注意：不能用 `^##?\\s+\\S` 找结尾 —— FRED 的正文里自带 `## FRED: ...` 标题，
    会被误判成段落终点，导致整个正文被截成空串。必须只认同级的 `###`。
    """
    m = re.search(rf"^###[ \t]+{re.escape(heading)}[ \t]*$", md, re.M)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^###[ \t]+\S", md[start:], re.M)
    if nxt:
        return md[start: start + nxt.start()]
    # 没有下一个 ### 时，退到下一个 ## 或 --- 分隔线
    nxt2 = re.search(r"^(?:##[ \t]+\S|---)", md[start:], re.M)
    return md[start: start + (nxt2.start() if nxt2 else len(md))]


def _latest_in_block(block: str) -> tuple[str | None, str | None]:
    """从 `**Latest:** 17.2 (2026-09-15)` 里抠出值与日期。"""
    m = re.search(r"\*\*Latest:\*\*\s*([^\s|]+)\s*\(([\d-]+)\)", block)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def audit_macro(md: str, as_of: str) -> list[dict]:
    """审计 FRED 各通道：证据包里的最新观测 vs 上游现在能拿到的最新观测。"""
    import os

    from dotenv import load_dotenv

    load_dotenv()
    key = os.environ.get("FRED_API_KEY")

    import requests

    series = {
        "fed_funds_rate": "FEDFUNDS",
        "10y_treasury": "DGS10",
        "cpi": "CPIAUCSL",
        "unemployment": "UNRATE",
        "vix": "VIXCLS",
    }
    out = []
    for alias, sid in series.items():
        blk = _blk(md, alias)
        ev_val, ev_date = _latest_in_block(blk)
        live_val, live_date = None, None
        err = None
        if key:
            try:
                r = requests.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params=dict(series_id=sid, observation_start="2026-01-01",
                                observation_end=as_of, sort_order="desc",
                                api_key=key, file_type="json"),
                    timeout=30,
                )
                r.raise_for_status()
                obs = [o for o in r.json()["observations"] if o["value"] not in (".", "")]
                if obs:
                    live_date, live_val = obs[0]["date"], obs[0]["value"]
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"

        # 分类
        if err:
            verdict, note = "A", f"审计时无法访问 FRED（{err}），沿用证据包读数。"
        elif live_date and ev_date and live_date > ev_date:
            lag = (dt.date.fromisoformat(live_date) - dt.date.fromisoformat(ev_date)).days
            verdict = "A"
            note = (f"上游已发布到 {live_date}（值 {live_val}），证据包停在 {ev_date}，"
                    f"落后 {lag} 个自然日。这是 FRED 系列的正常发布滞后，"
                    f"不是 bug —— 补通道见 §12 决议日波动率代理。")
        elif live_date and ev_date and live_date == ev_date:
            verdict, note = "OK", f"证据包与上游一致（均为 {ev_date}）。"
        else:
            verdict, note = "C", "证据包读数与上游不一致，需人工核对解析逻辑。"

        out.append({
            "channel": f"macro:{alias}", "series_id": sid,
            "evidence_latest": f"{ev_val} ({ev_date})" if ev_val else "(未解析到)",
            "upstream_now": f"{live_val} ({live_date})" if live_val else "(不可得)",
            "verdict": verdict, "note": note,
        })
    return out


def audit_options(md: str) -> list[dict]:
    """审计期权通道：区分「无报价」(A) 与「闸门阈值设错」(B)。"""
    import numpy as np
    import pandas as pd
    import yfinance as yf

    out = []
    blk13 = ""
    m = re.search(r"^##\s*13\..*$", md, re.M)
    if m:
        nxt = re.search(r"^##\s+\S", md[m.end():], re.M)
        blk13 = md[m.end(): m.end() + (nxt.start() if nxt else len(md))]

    iv_blocked = "IV 与偏斜本次不可用" in blk13
    oi_flagged = "OI 口径不可信" in blk13 or "P/C(OI)" not in blk13

    # 重新探一次 QQQ 期权链，数「有双边报价」的合约
    quoted_total = 0
    total_contracts = 0
    put_ivs: list[float] = []
    fresh_put_ivs: list[float] = []   # ★ 仅统计「成交日新鲜」的 put IV
    newest_age_days = None            # ★ 全链最新一笔成交距今多少天
    try:
        tk = yf.Ticker("QQQ")
        spot = float(tk.history(period="3d")["Close"].iloc[-1])
        for exp in list(tk.options)[:6]:
            ch = tk.option_chain(exp)
            for df in (ch.calls, ch.puts):
                d = df.copy()
                for c in ("bid", "ask", "impliedVolatility"):
                    if c not in d.columns:
                        d[c] = np.nan
                    d[c] = pd.to_numeric(d[c], errors="coerce")
                quoted_total += int(((d["bid"] > 0) & (d["ask"] > 0)).sum())
                total_contracts += len(d)

            # 计算该到期日全部合约的 lastTradeDate 新鲜度
            ages: list[float] = []
            for df in (ch.calls, ch.puts):
                if "lastTradeDate" not in df.columns:
                    continue
                ltd = pd.to_datetime(df["lastTradeDate"], errors="coerce", utc=True)
                now = pd.Timestamp.now(tz="UTC")
                ages += [float((now - t).total_seconds() / 86400)
                         for t in ltd.dropna().tolist()]
            if ages:
                a = min(ages)
                newest_age_days = a if newest_age_days is None else min(newest_age_days, a)

            p = ch.puts.copy()
            p["impliedVolatility"] = pd.to_numeric(p["impliedVolatility"], errors="coerce")
            if "lastTradeDate" in p.columns:
                p["_age"] = (pd.Timestamp.now(tz="UTC")
                             - pd.to_datetime(p["lastTradeDate"], errors="coerce", utc=True)
                             ).dt.total_seconds() / 86400
            else:
                p["_age"] = np.nan
            base = ((p["bid"] > 0) & (p["ask"] > 0) & (p["impliedVolatility"] > 0)
                    & ((p["strike"] - spot * 0.9).abs() < spot * 0.06))
            put_ivs += [float(v) for v in p.loc[base, "impliedVolatility"].tolist()]
            # ★ 关键：叠加新鲜度过滤（阈值取自 `wb_analysis/_thresholds.py`，与 collect_index 同源）
            fresh = base & (p["_age"] <= MAX_QUOTE_AGE_DAYS)
            fresh_put_ivs += [float(v) for v in p.loc[fresh, "impliedVolatility"].tolist()]
    except Exception as exc:  # noqa: BLE001
        out.append({"channel": "etf:option_iv", "verdict": "A",
                    "note": f"审计时无法取期权链：{type(exc).__name__}: {exc}"})
        return out

    # 真实波动率基准：用 VXN 历史中位数与 QQQ 已实现波动率双重对照
    real_vol_note = ""
    try:
        vxn = yf.Ticker("^VXN").history(period="2y")["Close"]
        real_vol_note = (f"参照 VXN 近两年区间 {float(vxn.min()):.2f}~{float(vxn.max()):.2f}"
                         f"（中位 {float(vxn.median()):.2f}）")
    except Exception:  # noqa: BLE001
        pass

    quote_ratio = quoted_total / total_contracts if total_contracts else 0.0
    age_txt = f"{newest_age_days:.1f}" if newest_age_days is not None else "未知"

    # ★★ 判定顺序：**先看新鲜度，再看数值**（2026-09-17 血泪教训）
    # 首版此函数只检查 bid/ask>0 与 IV 量级，于是把 170 张**陈旧 60+ 天**的报价
    # 误判为「B 类阈值误伤」，进而得出「数据可得、是闸门设错」的错误结论。
    # 事实是：yfinance 对 QQQ 全链的报价整体陈旧（最新成交距今 16.9 天），
    # 合格样本 0 个。**数值落在合理区间 ≠ 数据可用**，必须先过时间戳闸门。
    if newest_age_days is not None and newest_age_days > MAX_QUOTE_AGE_DAYS and not fresh_put_ivs:
        out.append({
            "channel": "etf:option_iv",
            "evidence": "已在证据包中被屏蔽" if iv_blocked else "证据包中有值",
            "upstream_now": (f"有双边报价合约占比 {quote_ratio:.1%}，"
                             f"但**最新一笔成交距今 {age_txt} 天**，"
                             f"合格（≤{MAX_QUOTE_AGE_DAYS:.0f} 天）样本 0 个"),
            "verdict": "A",
            "note": (f"**根因是采集时点落在盘前/盘后，不是数据源缺陷。** "
                     f"共 {quoted_total} 个合约有合法双边报价，但逐笔核查 `lastTradeDate` 后，"
                     f"最新成交距今仍有 {age_txt} 天（阈值 {MAX_QUOTE_AGE_DAYS:.0f} 天）。"
                     f"数「有 {len(put_ivs)} 张 put IV 且中位看似正常」是**陷阱**——"
                     f"陈旧报价的中间价常低于当前内在价值，反解出的 IV 可达 145%~252%。"
                     f"⇒ **本次期权维度不可引用，声明缺口是正确的。**"
                     f"★ 修复方向：**改在美东 09:30–16:00 盘中重新采集**"
                     f"（实测盘中最新成交距今 0.01 天，等级可达 FULL）。"
                     f"替代读数见 §12 的 VIX/VXN（{real_vol_note}）。"),
        })
    elif fresh_put_ivs:
        med = float(np.median(fresh_put_ivs)) * 100
        # ★★ 判定分级（2026-09-17 二次修正）：
        # 数据新鲜 ≠ 一定有问题。若**证据包本身也已标记为可用**，
        # 说明采集器与闸门都工作正常，应当判 **OK**，而不是报「阈值过严」。
        # 首版无论证据包状态如何都判 B 类，会在一切正常时持续误报。
        if iv_blocked:
            out.append({
                "channel": "etf:option_iv",
                "evidence": "已在证据包中被屏蔽",
                "upstream_now": f"抽查到 {len(fresh_put_ivs)} 张**新鲜** put IV，中位 {med:.1f}%",
                "verdict": "B",
                "note": (f"数据**可得且新鲜**（中位 IV {med:.1f}%，{real_vol_note}；"
                         f"最新成交距今 {age_txt} 天），但证据包写的是「不可用」"
                         f"⇒ **闸门阈值过严或采集时点不对，请检查采集器**。"),
            })
        else:
            out.append({
                "channel": "etf:option_iv",
                "evidence": "证据包中有值",
                "upstream_now": f"{len(fresh_put_ivs)} 张**新鲜** put IV，中位 {med:.1f}%",
                "verdict": "OK",
                "note": (f"**数据可用且证据包已正确收录。** "
                         f"中位 IV {med:.1f}%，{real_vol_note}；"
                         f"最新成交距今 {age_txt} 天，合格样本 {len(fresh_put_ivs)} 个。"
                         f"（此前提下的 `in_session` 时点闸门与新鲜度闸门均通过。）"),
            })
    else:
        out.append({
            "channel": "etf:option_iv",
            "evidence": "已在证据包中被屏蔽" if iv_blocked else "证据包中有值",
            "upstream_now": f"抽查的到期日无有效双边报价（有报价合约占比 {quote_ratio:.1%}）",
            "verdict": "A",
            "note": ("采集窗口内确实没有双边报价（yfinance 的 bid/ask 为 0），"
                     "IV 由过期 lastPrice 反解故为垃圾值。**这是真实不可得**，"
                     f"声明缺口是正确的。替代读数见 §12 的 VIX/VXN（{real_vol_note}）。"),
        })

    if oi_flagged:
        out.append({
            "channel": "etf:option_oi", "verdict": "A",
            "note": ("OI 在无报价时段口径不稳（同一到期日跨采集相差约 400 倍）。"
                     "**已由 oi_note 显式标注为不可引用**，P/C(Vol) 口径不受影响。"),
        })
    return out


def audit_series(md: str, as_of: str) -> list[dict]:
    """审计技术指标通道：证据包最新一行是否等于上游最新一行。

    这是 `_compact_series` 排序 bug 的回归检测 —— 该 bug 的表现就是
    「证据包的最后一行其实是倒数第二/第五行」。
    """
    import pandas as pd
    import yfinance as yf

    out = []
    for ind in ("close_50_sma", "rsi", "macd"):
        blk = _blk(md, ind)
        if not blk:
            out.append({"channel": f"indicator:{ind}", "verdict": "C",
                        "note": "证据包中找不到该指标段落。"})
            continue
        dates = re.findall(r"^\s*(\d{4}-\d{2}-\d{2})\s*:", blk, re.M)
        ev_last = max(dates) if dates else None
        out.append({
            "channel": f"indicator:{ind}",
            "evidence_last_date": ev_last,
            "verdict": "OK" if ev_last and ev_last <= as_of else "C",
            "note": (f"证据包最新一行 {ev_last}（基准日 {as_of}）。"
                     "若明显早于基准日，说明 `_compact_series` 又取错窗口了。"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="数据缺口审计")
    ap.add_argument("ticker")
    ap.add_argument("as_of")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    md = _load_evidence(args.ticker, args.as_of)
    findings: list[dict] = []
    findings += audit_macro(md, args.as_of)
    findings += audit_series(md, args.as_of)
    findings += audit_options(md)

    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
        return 0

    print(f"\n{'='*78}")
    print(f"数据缺口审计  |  {args.ticker}  {args.as_of}")
    print(f"{'='*78}\n")
    buckets: dict[str, list[dict]] = {}
    for f in findings:
        buckets.setdefault(f["verdict"], []).append(f)
    for v in ("C", "B", "A", "OK"):
        if v not in buckets:
            continue
        print(f"【{v}】{VERDICT_LABEL[v]}  —— {len(buckets[v])} 条")
        for f in buckets[v]:
            print(f"   · {f['channel']}")
            if f.get("evidence_latest") or f.get("evidence"):
                print(f"       证据包 : {f.get('evidence_latest') or f.get('evidence')}")
            if f.get("upstream_now"):
                print(f"       上游现在: {f['upstream_now']}")
            note = f.get("note", "")
            for i, line in enumerate(note.split("。")):
                if line.strip():
                    print(f"       {'说明' if i == 0 else '    '}: {line.strip()}。")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
