# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py
"""数据缺口台账：把「缺什么」变成**可检查的结构化记录**，而不是散落在文字里的声明。

## 要解决的问题
数据缺失会**改变最终结论**，但现在只有一个松散约定「缺了就声明」。后果有三个：
  ① **看不见**：缺口埋在几万字证据包里，角色可能没读到；
  ② **不对等**：缺一个社交源（次要）和缺整个期权维度（决定性）被同等对待；
  ③ **不落地**：声明完就完了，没有人说「这个缺口把哪个判断挡掉了」「怎么补」「能不能用代理」。

## 解法
每一轮生成 `wb_analysis/evidence/<T>_<date>.gaps.json`，每条缺口登记六个字段：

| 字段 | 含义 |
|---|---|
| `label` | 缺口名（用于在简报里做字符串校验） |
| `cls` | **A** 上游真缺 / **B** 阈值误伤 / **C** 采集器 bug / **S** 时点不对（可重采） |
| `decisive` | **是否影响结论方向**（True ⇒ 阻止给出方向性评级） |
| `blocks` | 它把哪个判断挡掉了（写清"因此无法回答……"） |
| `remedy` | 怎么补（换时点 / 换口径 / 换来源 / 修代码） |
| `fallback` | 能用的代理（**必须注明口径不同**） |

分类依据是**证据包里的客观信号**（通道健康度的 `成功 N/M` 与非全绿列表、章节是否被上游扣留），
再用一张**人工维护的规则表**给出 decisive/blocks/remedy/fallback —— 规则表里没有的通道
一律标 `cls="?"` 并**在原样输出里提示人工归类**（不静默忽略）。

## 用法
  ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py NFLX 2026-09-21          # 生成台账
  ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py NFLX 2026-09-21 --check wb_analysis/drafts/NFLX_2026-09-21
                                                                                # 门禁：决定性缺口必须在简报里声明
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "wb_analysis" / "evidence"

# ── 规则表：通道 → 缺口属性（人工维护；新增通道必须在这里登记，否则报 "?" 要求归类）──
RULES: dict[str, dict] = {
    "option_iv": {"kw": ["option_iv", "期权维度", "IV 等级", "期权链"], "cls": "S", "decisive": True,
                  "blocks": "无法回答「期权市场如何为下行风险定价」——IV 与偏斜缺失使下行保护成本不可评估",
                  "remedy": "改在美东 09:30–16:00 重采；或接受该维度缺失并把结论降为条件式",
                  "fallback": "^VIX / ^VXN（**30 天前瞻 IV，口径不同，不可线性换算回个股**）"},
    "option_skew": {"kw": ["option_skew", "偏斜"], "cls": "S", "decisive": True, "blocks": "无法判断看跌/看涨的相对贵贱",
                    "remedy": "同 option_iv", "fallback": "无可靠代理"},
    "option_oi": {"kw": ["option_oi", "持仓量"], "cls": "A", "decisive": False, "blocks": "—（持仓量本来就不承担论证重量）",
                  "remedy": "不需修；继续只用成交量口径的 P/C", "fallback": "P/C（成交量口径）"},
    "option_quote_freshness": {"kw": ["option_quote_freshness", "报价新鲜度", "新鲜度", "残留快照"], "cls": "S", "decisive": True, "blocks": "无法确认期权报价是否为当日快照 ⇒ 任何 IV 读数都不可用",
                               "remedy": "改在美东盘中重采", "fallback": "同 option_iv"},
    "option_quote": {"cls": "S", "decisive": True, "blocks": "同上", "remedy": "改在美东盘中重采", "fallback": "同 option_iv"},
    "social:StockTwits": {"kw": ["StockTwits"], "cls": "A", "decisive": False,
                          "blocks": "情绪缺少「散户一侧」的独立来源 ⇒ 置信度上限压到 Low",
                          "remedy": "换时点/换标签重试；仍无则如实降置信度", "fallback": "Yahoo 新闻语气（口径不同）"},
    "social:Reddit": {"kw": ["Reddit"], "cls": "A", "decisive": False,
                      "blocks": "情绪只剩单一来源 ⇒ 置信度上限压到 Low",
                      "remedy": "该通道对机房 IP 常返回 403/空；不要为它反复重试",
                      "fallback": "Yahoo 新闻语气（口径不同）"},
    "profile": {"kw": ["§3", "基本面快照", "快照被上游扣留", "vendor 拒答"], "cls": "A", "decisive": True,
                "blocks": "缺估值快照 ⇒ 市盈率/PB/市值/52 周区间全部不可用（除非另建替代源）",
                "remedy": "生成 `<T>_<date>.supplement.md`（直取当日快照 + 报表自算）",
                "fallback": "supplement（**与年报口径不同，须分别声明**）"},
    "verify_earnings_quality": {"cls": "?", "decisive": False, "blocks": "—", "remedy": "人工归类", "fallback": "—"},
}

BODY_NOTE = {"stale": "报价陈旧（超过新鲜度闸门）", "unavailable": "通道不可用", "missing": "无数据",
             "empty": "返回为空", "N/A": "上游未提供"}


def parse_evidence(ticker: str, date: str) -> dict:
    p = EVID / f"{ticker}_{date}.md"
    if not p.exists():
        return {"error": f"证据包不存在: {p.relative_to(ROOT).as_posix()}"}
    t = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"成功:\s*(\d+)\s*/\s*(\d+)", t)
    n_ok, n_tot = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    bad = re.search(r"非全绿通道\*\*?:\s*(.+)", t)
    channels = []
    if bad:
        for item in re.split(r"[、,，]", bad.group(1).strip().rstrip("。")):
            item = item.strip()
            if not item:
                continue
            name, _, status = item.partition("=")
            channels.append((name.strip(), status.strip() or "unavailable"))
    # §3 被上游扣留 = 事实上的 profile 缺口
    withheld = bool(re.search(r"Profile fundamentals are withheld", t))
    return {"n_ok": n_ok, "n_total": n_tot, "channels": channels, "profile_withheld": withheld,
            "path": p.relative_to(ROOT).as_posix()}


def build(ticker: str, date: str) -> dict:
    info = parse_evidence(ticker, date)
    if "error" in info:
        return info
    gaps = []
    for name, status in info["channels"]:
        rule = RULES.get(name)
        g = {"channel": name, "status": status,
             "cls": (rule or {}).get("cls", "?"),
             "decisive": bool((rule or {}).get("decisive", False)),
             "blocks": (rule or {}).get("blocks", "**未归类：请把该通道登记进 _gap_ledger.py 的 RULES 表**"),
             "remedy": (rule or {}).get("remedy", "人工归类"),
             "fallback": (rule or {}).get("fallback", "—"),
             "label": name, "kw": (rule or {}).get("kw", [name])}
        gaps.append(g)
    if info["profile_withheld"]:
        rule = RULES["profile"]
        gaps.append({"channel": "profile (§3 快照)", "status": "withheld", "cls": rule["cls"],
                     "decisive": rule["decisive"], "blocks": rule["blocks"], "remedy": rule["remedy"],
                     "fallback": rule["fallback"], "label": "profile", "kw": rule["kw"]})
    return {"ticker": ticker, "as_of": date, "evidence": info["path"],
            "channels_ok": info["n_ok"], "channels_total": info["n_total"],
            "gaps": gaps,
            "decisive_count": sum(1 for g in gaps if g["decisive"]),
            "unclassified": [g["channel"] for g in gaps if g["cls"] == "?"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("date")
    ap.add_argument("--check", default=None, help="给草稿目录，校验决定性缺口是否在简报里声明")
    args = ap.parse_args()

    led = build(args.ticker, args.date)
    if "error" in led:
        print(f"✗ {led['error']}")
        return 1

    out = EVID / f"{args.ticker}_{args.date}.gaps.json"
    out.write_text(json.dumps(led, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("=" * 100)
    print(f"数据缺口台账：{args.ticker} {args.date}　（通道 {led['channels_ok']}/{led['channels_total']}，"
          f"缺口 {len(led['gaps'])} 条，其中**决定性 {led['decisive_count']} 条**）")
    print("=" * 100)
    if not led["gaps"]:
        print("  ✓ 无缺口")
    for g in led["gaps"]:
        tag = "★决定性" if g["decisive"] else "        "
        print(f"\n  [{g['channel']}] 状态={g['status']}  类别={g['cls']}  {tag}")
        print(f"      挡掉了：{g['blocks']}")
        print(f"      怎么补：{g['remedy']}")
        print(f"      代理　：{g['fallback']}")
    if led["unclassified"]:
        print(f"\n  ⚠ 未归类通道 {led['unclassified']} —— 请登记进 RULES 表，否则「决定性」判断会漏")
    print(f"\n[台账] {out.relative_to(ROOT).as_posix()}")

    if args.check:
        draft = Path(args.check)
        brief = draft / "0_brief.md"
        if not brief.exists():
            print(f"\n✗ 简报不存在：{brief}")
            return 2
        text = brief.read_text(encoding="utf-8")
        decisive = [g for g in led["gaps"] if g["decisive"]]
        missing = [g for g in decisive
                   if not any(k in text for k in (g.get("kw") or [g["label"]]))]
        print(f"\n[门禁] 决定性缺口 {len(decisive)} 条，简报中未声明 {len(missing)} 条")
        for g in missing:
            print(f"    ✗ 未声明：{g['channel']}（它挡掉了：{g['blocks'][:40]}…）")
        if missing:
            print("  ⇒ **决定性缺口必须在简报里逐条声明**：缺它的后果是「下游角色不知道这里有洞」，"
                  "可能凭空补出一个方向性结论。")
            return 1
        if decisive:
            print("  ✓ 全部决定性缺口已在简报中声明")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
