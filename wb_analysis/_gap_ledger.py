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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    # ⚠️ remedy_file：补救产物一旦落地，该缺口即降级为「口径说明」而不再计为决定性缺口。
    #    否则台账会永远把「采集时缺过、事后已补齐」的通道报成未解决 —— 那会让简报被迫
    #    反复声明一个已不存在的问题（2026-10-03 NFLX 轮实测：§3 快照已由 supplement 补全，
    #    但台账仍报「决定性缺口 1 条」，导致 12 个角色文件里出现 40+ 处重复缺口声明）。
    "profile": {"kw": ["§3", "基本面快照", "快照被上游扣留", "vendor 拒答"], "cls": "A", "decisive": True,
                "blocks": "缺估值快照 ⇒ 市盈率/PB/市值/52 周区间全部不可用（除非另建替代源）",
                "remedy": "生成 `<T>_<date>.supplement.md`（直取当日快照 + 报表自算）",
                "fallback": "supplement（**与年报口径不同，须分别声明**）",
                "remedy_file": "supplement.md"},
    "verify_earnings_quality": {"cls": "?", "decisive": False, "blocks": "—", "remedy": "人工归类", "fallback": "—"},
    "etf:option_iv": {"kw": ["option_iv", "期权维度", "IV 等级", "期权链", "SPY 期权"], "cls": "S", "decisive": True,
                      "blocks": "无法回答「期权市场如何为下行风险定价」——IV 与偏斜缺失使下行保护成本不可评估",
                      "remedy": "改在美东 09:30–16:00 重采；或接受该维度缺失并把结论降为条件式",
                      "fallback": "^VIX / ^VXN（**30 天前瞻 IV，口径不同，不可线性换算**）"},
    "etf:option_skew": {"kw": ["option_skew", "偏斜"], "cls": "S", "decisive": True, "blocks": "无法判断看跌/看涨的相对贵贱",
                        "remedy": "同 etf:option_iv", "fallback": "无可靠代理"},
    # ⚠️ 2026-10-02 补登记：NDX 采集时报出 `etf:option_oi` 未归类（规则表漏了带前缀的 OI 通道，
    #    只有无前缀的 `option_oi`），导致台账标 cls="?" 并提示人工归类。
    #    语义与 `option_oi` 完全一致（持仓量不承担论证重量），只是通道名带 `etf:` 前缀。
    "etf:option_oi": {"kw": ["option_oi", "持仓量", "未平仓"], "cls": "A", "decisive": False,
                      "blocks": "—（持仓量本来就不承担论证重量）",
                      "remedy": "不需修；继续只用成交量口径的 P/C", "fallback": "P/C（成交量口径）"},
    "etf:option_quote_freshness": {"kw": ["option_quote_freshness", "报价新鲜度", "新鲜度", "残留快照"], "cls": "S", "decisive": True,
                                   "blocks": "无法确认期权报价是否为当日快照 ⇒ 任何 IV 读数都不可用",
                                   "remedy": "改在美东盘中重采", "fallback": "同 etf:option_iv"},
    # ⚠️ 2026-10-04 泛化：A 股 ETF 分「行业 ETF」（512400）与「策略/主题 ETF」（515100 红利低波）两类，
    #    两类均无场内期权。原措辞只提"行业ETF"，对策略 ETF 不准确，故改为"A股行业/策略 ETF"。
    "option_structure": {"kw": ["option_structure", "期权", "期权维度", "场内期权"], "cls": "A", "decisive": True,
                         "blocks": "无法回答「期权市场如何为下行风险定价」——A 股行业/策略 ETF 均无场内期权，"
                                   "下行保护成本不可评估",
                         "remedy": "A 股行业/策略 ETF 无场内期权（结构性缺失）；接受该维度缺失并把结论降为条件式",
                         "fallback": "上证50ETF / 沪深300ETF 期权隐含波动率（宽基口径）+ 本标的历史 HV"
                                     "（**口径不同，仅作波动率环境代理**）"},
    # ⚠️ 2026-10-04 新增（A 股 ETF 轮）：下面两条属「数据陈旧」而非「通道失败」——
    #    通道**取到了值**，但值的时间戳与基准日不符。登记它们是为了让下游看见，
    #    否则会被当成基准日当日值使用（铁律 26 快照不得脱离时间戳 / 铁律 32 缺口须被下游看见）。
    "macro_yield_stale": {"kw": ["macro_yield_stale", "国债收益率", "无风险利率"], "cls": "B", "decisive": False,
                          "blocks": "无风险利率不是基准日当日值 ⇒ ERP / 股息率溢价的绝对水平只能作量级参照，"
                                    "不可用于跨日或跨标的比较",
                          "remedy": "`cn_yield_curve` 为季度频率，滞后是常态；用最新可得值并**同时披露其数据日期**",
                          "fallback": "以最新可得值替代，口径注明「滞后 N 天」"},
    "etf_nav_unupdated": {"kw": ["etf_nav_unupdated", "净值未更新", "NAV"], "cls": "B", "decisive": False,
                          "blocks": "当日单位净值疑似未更新 ⇒ 由 NAV 与收盘价反算的折溢价不可直接采信",
                          "remedy": "当日净值通常 T+1 公布；改用 `etf overview` 的 `etfDisc` 字段（IOPV 口径）",
                          "fallback": "`etfDisc`（交易所 IOPV 口径，与 NAV 口径不同，须分别声明）"},
    "macro:10y_treasury": {"kw": ["10y_treasury", "国债", "DGS10", "^TNX"], "cls": "A", "decisive": False,
                           "blocks": "—", "remedy": "重试", "fallback": "^TNX"},
    # ⚠️ 2026-10-05 新增（NFLX 轮实测）：`realtime_close` 是 §13「最新交易日实时收盘补充」通道，
    #    作用是当日线接口尚未发布当日 bar 时，用实时字段 + 1 分钟 bar 把「最新交易日」补回来。
    #    实测缺失成因为 **yfinance 限流**（`YFRateLimitError: Too Many Requests`）
    #    ⇒ 属 **B 类（限流/阈值误伤）**，不是 C 类采集器 bug，也不是 A 类上游真缺。
    #    未登记时台账会标 `cls="?"` 并提示「决定性判断会漏」——故补录。
    "realtime_close": {"kw": ["realtime_close", "实时收盘", "最新交易日实时"], "cls": "B", "decisive": False,
                       "blocks": "取不到「最新交易日」的实时价 ⇒ **口径 B（盘中价）不可用**，"
                                 "「实时时段比日线末日新 N 个交易日」的对比无法进行；"
                                 "**主口径（最后完整 bar）不受影响**",
                       "remedy": "多为 yfinance 限流（YFRateLimitError）；等数分钟后重跑，或接受缺失",
                       "fallback": "以上一个完整交易日收盘价为准（口径 A），并显式声明「本轮无盘中口径 B」"},
    # ⚠️ 2026-10-08 新增（GOOG 轮实测）：§6 全球宏观新闻「仅标题无正文」。
    #    根因（实测）：yfinance 1.7.0 两条新闻通道**都不保证正文** ——
    #      ① `Ticker().news` / `get_news()` 设计上含 summary，但该端点在 2026-10-08
    #         对**所有 symbol**（^GSPC/SPY/AAPL/GOOG…）一律返回 0 条 ⇒ 上游降级；
    #      ② 兜底 `Search().news` 为平铺结构，顶层键并集固定 8 个，
    #         **不含 summary/content/description** ⇒ 结构性无正文。
    #    ⇒ 这不是「取错接口」（铁律 35 的形态），主通道选型是对的、只是上游失效；
    #      兜底接口则**历史上就不带正文**。两者叠加 ⇒ 宏观新闻恒剩「标题 + Link」。
    #    修法：采集层新增**按需正文回填**（抓新闻页 → 限 `article-body` 容器取 `<p>`）。
    #    ⚠️ 不得在全页匹配 `<p>`：Yahoo 页面后半段有编码混淆脚本，实测首段会变乱码。
    #    回填上限 8 篇、单篇截断 1200 字符、失败静默降级 ⇒ **非 100% 成功**，
    #    故仍需登记：拿到正文的是常态，个别条目仍可能只有标题。
    "global_news_body": {"kw": ["全球宏观新闻", "宏观新闻", "Global Market News", "仅有标题", "无正文"],
                         "cls": "B", "decisive": False,
                         "blocks": "宏观新闻可能只剩「标题 + Link」⇒ 无法从正文提取事件细节与语气，"
                                   "只能按标题做粗粒度定性（**但标题与量化数据仍可用**）",
                         "remedy": "采集层已加按需正文回填（`backfill_missing_summaries`）；"
                                   "个别条目仍可能抓取失败 ⇒ 如实声明该条仅有标题",
                         "fallback": "标题本身（真实、可用）+ FRED 实测值补足宏观量化"},
    # ⚠️ 2026-10-08 新增（GOOG 轮实测）：个股新闻通道整体归零。
    #    实测 `Ticker().news` / `.get_news()` 对**所有 symbol**（含 GOOG/AAPL/SPY）
    #    一律返回 0 条 ⇒ 上游端点降级（非本仓 bug，非「取错接口」）。
    #    曾尝试 `Search(canonical)` 兜底，**已否决**，两条理由：
    #      ① 语义不专属：`Search("GOOG")` 返回泛科技/能源新闻，引进来是噪声；
    #      ② 窗口过滤后仍为空：Search() 只回最新快讯，回溯窗口下被 in_window 全部挡掉。
    #    ⇒ 当前选择「如实报空 + 台账声明降级」，不引入噪声源。属 B 类（上游降级）。
    #    ⚠️ 键名必须是**证据包「非全绿通道」里出现的通道名**（`get_news`），
    #       不是语义名 —— 台账按通道名查表，写错会标 `?` 并要求人工归类。
    "get_news": {"kw": ["个股新闻", "§5 个股新闻", "No news found"],
                 "cls": "B", "decisive": False,
                 "blocks": "无个股新闻 ⇒ 失去「公司层面的当期事件」这一证据类；"
                           "**但 §4 财报、§6 宏观、§3 快照均不受影响，估值/技术面论证照常可做**",
                 "remedy": "上游 `Ticker().news` 端点降级（全 symbol 0 条）；等端点恢复后重采即可，"
                           "不要用 Search() 兜底（语义不专属且窗口过滤后仍为空）",
                 "fallback": "§6 宏观新闻（含正文回填后，含大量个股级线索如 NVDA/AAPL 提及）；"
                             "§3/§4 基本面数据"},
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
    bad = re.search(r"(?:非全绿通道\*\*?|失败或不可用):\s*(.+)", t)
    channels = []
    if bad:
        for item in re.split(r"[、,，]", bad.group(1).strip().rstrip("。")):
            item = item.strip()
            if not item or item in ("无", "none", "None", "无（全绿）", "—"):
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
        # remedy_file：若补救产物已落地，则不再是「缺口」，降级为「口径说明」
        rf = rule.get("remedy_file")
        remedy_path = EVID / f"{ticker}_{date}.{rf}" if rf else None
        if remedy_path and remedy_path.exists():
            gaps.append({"channel": "profile (§3 快照)", "status": "resolved", "cls": rule["cls"],
                         "decisive": False, "blocks": rule["blocks"], "remedy": rule["remedy"],
                         "fallback": rule["fallback"], "label": "profile", "kw": rule["kw"],
                         "resolved_by": remedy_path.relative_to(ROOT).as_posix(),
                         "note": "采集时确缺该通道，但补救产物已落地 ⇒ 降级为「口径说明」，引用时标明口径即可"})
        else:
            gaps.append({"channel": "profile (§3 快照)", "status": "withheld", "cls": rule["cls"],
                         "decisive": rule["decisive"], "blocks": rule["blocks"], "remedy": rule["remedy"],
                         "fallback": rule["fallback"], "label": "profile", "kw": rule["kw"]})
    return {"ticker": ticker, "as_of": date, "evidence": info["path"],
            "channels_ok": info["n_ok"], "channels_total": info["n_total"],
            "gaps": gaps,
            "decisive_count": sum(1 for g in gaps if g["decisive"]),
            "resolved_count": sum(1 for g in gaps if g.get("status") == "resolved"),
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
    _res = led.get("resolved_count", 0)
    print(f"数据缺口台账：{args.ticker} {args.date}　（通道 {led['channels_ok']}/{led['channels_total']}，"
          f"未解决缺口 {len(led['gaps']) - _res} 条，其中**决定性 {led['decisive_count']} 条**；"
          f"已解决 {_res} 条）")
    print("=" * 100)
    if not led["gaps"]:
        print("  ✓ 无缺口")
    for g in led["gaps"]:
        if g.get("status") == "resolved":
            print(f"\n  [{g['channel']}] ✓ 已解决（降级为口径说明）")
            print(f"      补救产物：{g.get('resolved_by', '—')}")
            print(f"      须知　　：{g.get('note', '')}")
            continue
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
