# lifecycle: reusable
# created: 2026-10-19
# usage: ./.venv/Scripts/python.exe wb_analysis/_role_prompt.py 0700.HK 2026-10-16 bull [--out prompt.md]
"""生成单个角色的**完整提示词** —— 用于跨平台、跨会话的子智能体拆分。

## 为什么需要它（2026-10-19）

「子智能体」不是另一个模型，而是**同一模型的另一个上下文窗口**；独立性来自
「彼此看不到对方写了什么」，不来自模型不同。

各 agent 平台的子智能体 API 并不统一（有的有 Task/Agent 工具，有的只能开新会话，
有的干脆没有）。若把拆分写死成某个平台的调用方式，项目就绑死在一个平台上 ——
这违背「长期可用」。

本工具把「角色提示词」变成**纯文本产物**：任何平台、任何会话，把输出贴进去，
就是一个隔离的子智能体。平台只需要两个能力：**读文件、写文件**。

## 用法（三步）

1. 生成提示词：`python wb_analysis/_role_prompt.py <TICKER> <DATE> <ROLE> --out /tmp/p.md`
2. 在**新会话**里贴入 `/tmp/p.md` 的全部内容（不要带任何历史消息）。
3. 角色按提示词把稿子写到指定路径；回到主会话跑 `_lint_drafts.py` 校验。

## 角色与产物

| ROLE | 产物 |
|---|---|
| market / fundamentals / news / sentiment | `1_analysts/<role>.md` |
| bull / bear / manager | `2_research/<role>.md` |
| trader | `3_trading/trader.md` |
| aggressive / conservative / neutral / portfolio_manager | `4_risk/<role>.md` |

## 退出码
0 = 提示词已生成；1 = 角色未知或必需文件缺失（逐项列出，不静默）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ★ 2026-10-24：篇幅门禁的**唯一定义源**在 `wb_analysis/_length.py`，
#   此处只读不复制（此前两边各写一份 4,000/6,000，改一处必漏另一处）。
from wb_analysis._length import MAX_CHARS, bounds_for  # noqa: E402

DRAFTS = ROOT / "wb_analysis" / "drafts"
EVID = ROOT / "wb_analysis" / "evidence"

ROLE_FILES: dict[str, str] = {
    "market": "1_analysts/market.md",
    "fundamentals": "1_analysts/fundamentals.md",
    "news": "1_analysts/news.md",
    "sentiment": "1_analysts/sentiment.md",
    "bull": "2_research/bull.md",
    "bear": "2_research/bear.md",
    "manager": "2_research/manager.md",
    "trader": "3_trading/trader.md",
    "aggressive": "4_risk/aggressive.md",
    "conservative": "4_risk/conservative.md",
    "neutral": "4_risk/neutral.md",
    "portfolio_manager": "4_risk/portfolio_manager.md",
}

ROLE_DUTY: dict[str, str] = {
    "market": "技术面：趋势（均线/金叉死叉）、动量（MACD/RSI/KDJ）、波动率（ATR/布林带宽/带内位置）、"
              "量能（相对 20 日均量）、关键价位（支撑/阻力，全部绝对价）。分节：### 趋势 / ### 动量 / ### 波动率 / ### 量能 / ### 关键价位。",
    "fundamentals": "估值与财务质量：PE/Forward PE/PB/PEG（含口径校验）、盈利能力（毛利率/净利率/ROE 趋势）、"
                    "成长性（营收/净利同比）、资产负债健康度、股东回报。必须回答「当前估值相对成长性是否合理」，给结论而非罗列。",
    "news": "个股事件与宏观传导：区分**已发生的事实**与**预期/传闻**；给出方向与量级判断；"
            "财报/披露日历必须标为事实或推断；证据包未覆盖的政策/监管事件写「该项数据缺失」。",
    "sentiment": "情绪聚合：按来源逐项拆解并引用证据；说明来源间分歧与一致；主导叙事；催化剂与风险；"
                 "最后给一张汇总表。**首两行必须是**：`**Overall Sentiment:** **<六档>** (Score: n.n/10)` 与 `**Confidence:** <Low|Medium|High>`。",
    "bull": "构建看多证据链：成长、竞争优势、正面指标；**逐条反驳熊派的具体论点**（引用对方用过的数字）。"
            "对话式辩论，不是数据清单。",
    "bear": "构建看空证据链：估值风险、竞争侵蚀、财务隐患、宏观逆风；**逐条反驳牛派的具体论点**（引用对方用过的数字）。"
            "对话式辩论，不是数据清单。",
    "manager": "评判辩论质量（与发言顺序无关），产出研究计划。**文首必须是结论块**："
               "`**Recommendation**: <五档>` / `**Rationale**: ...` / `**Strategic Actions**: ...`，之后才是论证。",
    "trader": "把研究计划落成交易方案：入场价与止损必须是**绝对价格数字**（不得写百分比/区间）。"
              "**文首结论块**：`**Action**: <Buy|Hold|Sell>` / `**Reasoning**: ...` / `**Entry Price**: ...` / `**Stop Loss**: ...` / `**Position Sizing**: ...`；"
              "**末行必须是** `FINAL TRANSACTION PROPOSAL: **<BUY|HOLD|SELL>**`。",
    "aggressive": "主张放大敞口，强调错失成本，攻击保守方的过度谨慎。必须就交易员的**具体价位与仓位**争论。"
                  "**文首**：`**Rating**: <五档>`。",
    "conservative": "主张收缩敞口，强调本金保护与尾部风险，攻击激进方的风险低估。必须就交易员的**具体价位与仓位**争论。"
                    "**文首**：`**Rating**: <五档>`。",
    "neutral": "指出双方盲点，给出条件化的中间路径。必须就交易员的**具体价位与仓位**争论。"
               "**文首**：`**Rating**: <五档>`。",
    "portfolio_manager": "综合风险辩论做终局决定：证据明确才给方向，平衡/冲突/不足时选持有。"
                         "**文首结论块**：`**Rating**: <五档>` / `**Executive Summary**: ...` / `**Investment Thesis**: ...` / "
                         "`**Price Target**: ...` / `**Time Horizon**: ...`。",
}

RATING_RULE: dict[str, str] = {
    "market": "全文**禁止**出现五档英文词（Buy/Overweight/Hold/Underweight/Sell）与 BUY/SELL/HOLD 大写。",
    "fundamentals": "全文**禁止**出现五档英文词与 BUY/SELL/HOLD 大写。",
    "news": "全文**禁止**出现五档英文词与 BUY/SELL/HOLD 大写。",
    "sentiment": "只允许六档情绪词（Bullish/Mildly Bullish/Neutral/Mixed/Mildly Bearish/Bearish），且仅在 Overall Sentiment 行出现一次；"
                 "**禁止**五档评级词。",
    "bull": "全文**禁止**出现五档英文词与 BUY/SELL/HOLD 大写。",
    "bear": "全文**禁止**出现五档英文词与 BUY/SELL/HOLD 大写。",
    "manager": "五档词**只允许出现 1 次**，位于文首 `**Recommendation**:` 之后；正文一律中文（买入/增持/持有/减持/卖出）。",
    "trader": "五档词**只允许 1 次**（`**Action**:` 之后）；末行 FINAL 行另计。正文一律中文。",
    "aggressive": "五档词**只允许 1 次**，位于文首 `**Rating**:` 之后。",
    "conservative": "五档词**只允许 1 次**，位于文首 `**Rating**:` 之后。",
    "neutral": "五档词**只允许 1 次**，位于文首 `**Rating**:` 之后。",
    "portfolio_manager": "五档词**只允许 1 次**，位于文首 `**Rating**:` 之后。",
}


#: 各角色本轮**应当**读到的前轮稿件（相对草稿目录）。
#:
#: ★ 2026-10-23 补：此前 `_readable()` 对所有角色返回同一份白名单
#:   （brief / derived / evidence / FRAMEWORK），于是 manager / trader / 三风控 / PM 的
#:   提示词写着「评判辩论质量」，白名单里却**没有 bull.md / bear.md / trader.md** ——
#:   角色被要求评判自己读不到的东西。实测跑 GOOG_2026-10-23 时只能靠人工在子代理指令里
#:   补文件清单，属流程性缺陷。判据取自 FRAMEWORK §3 的输入关系。
#:
#: 仍**不**把分析师稿给 bull/bear：R1 要求两派只从证据出发、互不预判（AGENT_PROTOCOL §3）。
PRIOR_ROUND: dict[str, tuple[str, ...]] = {
    "manager": ("2_research/bull.md", "2_research/bear.md"),
    "trader": (
        "1_analysts/market.md", "1_analysts/fundamentals.md",
        "1_analysts/news.md", "1_analysts/sentiment.md",
        "2_research/manager.md",
    ),
    "aggressive": (
        "1_analysts/market.md", "2_research/bull.md",
        "2_research/manager.md", "3_trading/trader.md",
    ),
    "conservative": (
        "1_analysts/market.md", "2_research/bear.md",
        "2_research/manager.md", "3_trading/trader.md",
    ),
    "neutral": (
        "1_analysts/market.md", "2_research/bull.md", "2_research/bear.md",
        "2_research/manager.md", "3_trading/trader.md",
    ),
    "portfolio_manager": (
        "1_analysts/market.md", "1_analysts/fundamentals.md",
        "1_analysts/news.md", "1_analysts/sentiment.md",
        "2_research/bull.md", "2_research/bear.md", "2_research/manager.md",
        "3_trading/trader.md",
        "4_risk/aggressive.md", "4_risk/conservative.md", "4_risk/neutral.md",
    ),
}


def _readable(ticker: str, date: str, draft: Path, role: str = "") -> list[Path]:
    """该角色可读的文件（绝对路径，存在才列）。

    `role` 非空时追加该角色**本轮的前置稿件**（见 `PRIOR_ROUND`）—— 缺一份不报错，
    因为下游角色常在上一轮尚未写完时被提前生成提示词（那时白名单少几项是正常的）。
    """
    cands = [
        draft / "0_brief.md",
        draft / "0_derived.md",
        EVID / f"{ticker}_{date}.md",
        EVID / f"{ticker}_{date}.supplement.md",
        EVID / f"{ticker}_{date}.hk.md",
        EVID / f"{ticker}_{date}.derived.md",
        ROOT / "wb_analysis" / "FRAMEWORK.md",
    ]
    cands += [draft / rel for rel in PRIOR_ROUND.get(role, ())]
    seen: set[Path] = set()
    out: list[Path] = []
    for p in cands:
        if p.exists() and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _forbidden(role: str, draft: Path) -> list[Path]:
    """禁读清单：牛熊互斥；分析师不读研究/交易/风控；研究经理读全部。"""
    out: list[Path] = []
    if role == "bull":
        out.append(draft / "2_research" / "bear.md")
    elif role == "bear":
        out.append(draft / "2_research" / "bull.md")
    elif role in ("market", "fundamentals", "news", "sentiment"):
        out += [draft / "2_research" / n for n in ("bull.md", "bear.md", "manager.md")]
        out += [draft / "3_trading" / "trader.md"]
        out += [draft / "4_risk" / n for n in ("aggressive.md", "conservative.md", "neutral.md", "portfolio_manager.md")]
    elif role in ("aggressive", "conservative", "neutral"):
        pass  # 风控席位需要读全部前置稿
    return out


def build(ticker: str, date: str, role: str) -> tuple[int, str]:
    if role not in ROLE_FILES:
        print(f"✗ 未知角色: {role}（可选: {', '.join(ROLE_FILES)}）", file=sys.stderr)
        return 1, ""
    draft = DRAFTS / f"{ticker}_{date}"
    if not draft.is_dir():
        print(f"✗ 草稿目录不存在: {draft}（先跑 collect / _gen_derived / 写 0_brief）", file=sys.stderr)
        return 1, ""
    if not (draft / "0_brief.md").exists():
        print(f"✗ 缺 0_brief.md: {draft}（角色没有统一事实源）", file=sys.stderr)
        return 1, ""

    readable = _readable(ticker, date, draft, role)
    forbidden = _forbidden(role, draft)
    if role in ("bull", "bear"):
        # 对方稿件**始终列出**（即使尚未生成）—— 这条禁令不能依赖文件是否存在。
        forbidden = [p for p in forbidden if p.name in ("bull.md", "bear.md")]
    else:
        forbidden = [p for p in forbidden if p.exists()]
    out_path = draft / ROLE_FILES[role]

    L: list[str] = []
    L.append(f"# 角色任务：{role} · {ticker} · 基准日 {date}")
    L.append("")
    L.append("你是一个**隔离的子智能体**：只能使用下面列出的文件，不得联网、不得引用其他标的的报告、")
    L.append("不得引用任何历史会话或「上一轮」结论。你的产出会被独立校验，编造数字会被逐条揪出。")
    L.append("")
    L.append("## 1. 职责")
    L.append("")
    L.append(ROLE_DUTY[role])
    L.append("")
    L.append("## 2. 可读文件（白名单，绝对路径）")
    L.append("")
    for p in readable:
        L.append(f"- `{p}`")
    if not readable:
        L.append("- （无：请先确认证据包与简报已生成）")
    L.append("")
    L.append("## 3. 禁读（读到即违规）")
    L.append("")
    if forbidden:
        for p in forbidden:
            L.append(f"- `{p}`")
    else:
        L.append("- 无同轮禁读文件；但仍**不得**引用其他标的报告与历史会话。")
    L.append("")
    L.append("## 4. 输出契约")
    L.append("")
    L.append(f"- 落盘路径：`{out_path}`")
    L.append(f"- {RATING_RULE[role]}")
    L.append("- 价格一律**绝对价格、两位小数**，并写出来源（均线/布林/前高前低/成交密集区）；禁止「附近」「一带」。")
    L.append("- 每个数字必须能在白名单文件里逐字找到，或**写出算式**由其中的数字得到"
             "（示例：`<证据包里的价格> − <证据包里的支撑价> = <绝对价格>`；**示例数字一律从本轮证据包取，"
             "不写死任何具体数值**——硬编码会让上一轮标的的数字渗入本轮，正是本项目禁止的跨轮污染）。")
    L.append("- 必须单独列一节「不利证据」，至少 3 条，针对你自己的结论做反向检验。")
    L.append("- 结论必须**条件式**：写清「若 A 则 X；若 B 则 Y」，不得给无条件方向。")
    _lo, _hi = bounds_for(ROLE_FILES[role].rsplit("/", 1)[-1])
    _tier = "决策类" if _hi == _lo + 800 and _lo == 3000 else "分析师/辩论"
    L.append(f"- **篇幅 {_lo:,}–{_hi:,} 字符**（{_tier}硬下限 {_lo:,}，超过 {MAX_CHARS:,} 会被判「偏长」）。")
    L.append("- **每句话都必须承载信息**：不得复述结论、不得重复同一句、不得用「综上所述」凑段。")
    L.append("- 不得写免责声明、合规声明或「本报告不含某某词」这类元话语。")
    L.append("- 数据缺失写「该项数据缺失」，不得臆造。")
    L.append("")
    L.append("## 5. 完成前自验")
    L.append("")
    L.append("```")
    L.append(f"python -c \"import pathlib;t=pathlib.Path(r'{out_path}').read_text(encoding='utf-8');print(len(t))\"")
    L.append("```")
    L.append("")
    L.append(f"长度 <{_lo:,} 或 >{MAX_CHARS:,} 时，**删减/补充内容本身**，不要用重复句凑数。")
    return 0, "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成单角色提示词（跨平台子智能体）")
    ap.add_argument("ticker")
    ap.add_argument("date")
    ap.add_argument("role", help=f"可选: {', '.join(ROLE_FILES)}")
    ap.add_argument("--out", default=None, help="写入文件（默认打印到 stdout）")
    a = ap.parse_args()
    rc, text = build(a.ticker, a.date, a.role)
    if rc != 0:
        return rc
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"✓ 已写入 {a.out}（{len(text)} 字符）")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
