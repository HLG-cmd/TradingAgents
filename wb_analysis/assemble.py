# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/assemble.py
"""报告树组装器 —— 把分析层产出的 JSON 渲染成与上游同构的报告树。

产物目录结构与章节标题逐字段对齐
``tradingagents/reporting.py::write_report_tree``，因此本流水线生成的报告
可以被任何读取原报告树的下游工具直接消费（无缝替代）。

用法：
    python wb_analysis/assemble.py NVDA
    python wb_analysis/assemble.py wb_analysis/analysis/NVDA_2026-09-15.json
    python wb_analysis/assemble.py NVDA --date 2026-09-15 --out reports

输入：
    wb_analysis/analysis/<TICKER>_<YYYY-MM-DD>.json   （见 FRAMEWORK.md 第 4 节）

输出：
    <out>/<TICKER>/<TICKER>_<YYYYmmdd_HHMMSS>/{1_analysts,2_research,3_trading,4_risk,5_portfolio}/
    <out>/<TICKER>/<TICKER>_<YYYYmmdd_HHMMSS>/complete_report.md
（旧布局：加 --flat 则仍写 <out>/<TICKER>_<YYYYMMdd_HHMMSS>/）
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 契约常量（评级词三/五档、交易员末行正则）的**唯一来源** —— 见 `_contract.py` 抬头的漂移史。
# ⚠️ 2026-10-10：此前这里硬编码了 `RATINGS_5_TIER` / `TRADER_ACTIONS`，注释写「与上游逐字一致」，
#    但它既没 import 上游、也没进 `_selftest.py` 的 CONSUMERS 名单 ⇒ **完全无人看管**；
#    一旦上游加词（如 `Strong Buy`）或项目侧改白名单，这里静默分叉。
#    项目侧统一以 `_contract` 为准；「项目侧 == 上游」由 `_selftest.py` 的断言锁住。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wb_analysis import _clock  # noqa: E402
from wb_analysis._contract import (  # noqa: E402
    FIVE_LEVELS as RATINGS_5_TIER,
    PROPOSAL_STRICT_RE as _TRADER_STOP_LINE,
    THREE_LEVELS as TRADER_ACTIONS,
)

ANALYSIS_DIR = PROJECT_ROOT / "wb_analysis" / "analysis"

# 分析师在合并报告中的呈现顺序与文件名，与 reporting.py 完全一致
ANALYST_SECTIONS = (
    ("Market Analyst", "market", "market.md"),
    ("Sentiment Analyst", "sentiment", "sentiment.md"),
    ("News Analyst", "news", "news.md"),
    ("Fundamentals Analyst", "fundamentals", "fundamentals.md"),
)

# （交易员末行正则 `_TRADER_STOP_LINE` 已由顶部从 `_contract` import，此处不再本地定义）


def _safe_component(text: str) -> str:
    """把 ticker 清洗成安全的路径片段（上游也有同名工具）。"""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", str(text).strip())
    return cleaned or "UNKNOWN"


class MetaMissingError(RuntimeError):
    """`--from-dir` 需要一份**可用**的 `meta.json`，但它缺失 / 不可解析 / 缺必备字段。"""


def load_from_dir(draft_dir: Path, strict: bool = True) -> dict:
    """从「草稿目录」读取分析结果。

    ★ 2026-10-10：`meta.json` 由「可选」改为 **strict 下必需**。
    历史坑：缺它时 `as_of` / `ratings` 会**静默**退化为 `""` / `{}`（源码里是 `meta.get(..., 默认值)`），
    渲染出的报告树外观正常、`data_date` 与三档评级却全空 ⇒ 属铁律 3「静默失败」，
    下游 `_precheck`「报告树反读」直接失据。
    现在 strict=True（默认）时，**缺 `meta.json` / 解析失败 / 缺 `as_of`+`ratings` 字段**
    一律抛 `MetaMissingError`，由 `main()` 转成退出码 2；只有显式传 `strict=False`
    才回到旧的宽松行为（供个别排障场景使用）。

    草稿目录与最终报告树同构，每个角色一个 .md 文件，外加可选的 ``meta.json``：

        meta.json                      {"ticker": "...", "as_of": "...", "ratings": {...}, "notes": "..."}
        1_analysts/market.md
        1_analysts/sentiment.md
        1_analysts/news.md
        1_analysts/fundamentals.md
        2_research/bull.md
        2_research/bear.md
        2_research/manager.md
        3_trading/trader.md
        4_risk/aggressive.md
        4_risk/conservative.md
        4_risk/neutral.md
        4_risk/portfolio_manager.md

    相比把大段中文塞进 JSON 字符串，这种布局更易读、易改、可 diff。
    """
    draft_dir = Path(draft_dir)

    def read(rel: str) -> str:
        p = draft_dir / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    meta_path = draft_dir / "meta.json"
    if not meta_path.exists():
        if strict:
            raise MetaMissingError(f"缺少 {meta_path.name}（{meta_path}）")
        meta = {}
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise MetaMissingError(f"{meta_path.name} 解析失败：{exc!r}") from exc
        if not isinstance(meta, dict):
            raise MetaMissingError(f"{meta_path.name} 不是 JSON 对象（实为 {type(meta).__name__}）")

    if strict:
        missing = [k for k in ("as_of", "ratings") if not meta.get(k)]
        if missing:
            raise MetaMissingError(f"{meta_path.name} 缺必备字段：{', '.join(missing)}")

    ticker = meta.get("ticker")
    if not ticker:
        # 从草稿目录名兜底推导，如 NVDA_2026-09-15 -> NVDA
        stem = draft_dir.name
        ticker = stem.split("_")[0] if stem else "UNKNOWN"

    return {
        "ticker": ticker,
        "as_of": meta.get("as_of", ""),
        "ratings": meta.get("ratings", {}),
        "analysts": {
            "market": read("1_analysts/market.md"),
            "sentiment": read("1_analysts/sentiment.md"),
            "news": read("1_analysts/news.md"),
            "fundamentals": read("1_analysts/fundamentals.md"),
        },
        "research": {
            "bull": read("2_research/bull.md"),
            "bear": read("2_research/bear.md"),
            "manager": read("2_research/manager.md"),
        },
        "trading": {"trader": read("3_trading/trader.md")},
        "risk": {
            "aggressive": read("4_risk/aggressive.md"),
            "conservative": read("4_risk/conservative.md"),
            "neutral": read("4_risk/neutral.md"),
            "portfolio_manager": read("4_risk/portfolio_manager.md"),
        },
        "notes": meta.get("notes", ""),
    }


def _upstream_extract_rating(text: str) -> str | None:
    """调用上游解析器提取评级；不可用时返回 None（降级为跳过该检查）。"""
    try:
        from tradingagents.agents.utils.rating import extract_rating

        return extract_rating(text)
    except Exception:  # noqa: BLE001
        return None


def crosscheck_with_upstream(data: dict) -> list[str]:
    """用上游 rating.py 解析器反读本产物，校验评级是否与声明一致。

    这是一个真实的坑：``extract_rating`` 会优先找 ``Rating: X`` 形式的标签，
    找不到时退化为**扫描全文取遇到的第一个五档英文词**。因此如果研究报告在
    ``Recommendation`` 之前出现裸的英文评级词（例如叙述中写「（Underweight）」），
    解析器会取到那个词而不是真正的结论。

    本检查把渲染后的正文交给上游解析器，若结果与 ``ratings`` 声明不符即告警。
    """
    warns: list[str] = []
    ratings = data.get("ratings") or {}

    pairs = [
        ("research_manager", (data.get("research") or {}).get("manager")),
        ("portfolio_manager", (data.get("risk") or {}).get("portfolio_manager")),
    ]
    for key, text in pairs:
        declared = ratings.get(key)
        if not declared or not text:
            continue
        actual = _upstream_extract_rating(text)
        if actual != declared:
            warns.append(
                f"上游解析器把 {key} 读成 {actual!r}，与声明的 {declared!r} 不一致 —— "
                "通常是结论块之前出现了裸的英文评级词，请把结论块前移或改用中文表述"
            )

    trader_text = ((data.get("trading") or {}).get("trader") or "")
    if trader_text:
        m = _TRADER_STOP_LINE.search(trader_text)
        declared_action = ratings.get("trader_action")
        if m and declared_action and m.group(1).capitalize() != declared_action:
            warns.append(
                f"交易员收尾行解析为 {m.group(1).upper()}，与声明的 trader_action="
                f"{declared_action!r} 不一致"
            )

    return warns


def validate(data: dict) -> list[str]:
    """校验分析结果的格式契约，返回告警列表（不阻断渲染）。

    这些检查对应上游 `rating.py` 的解析要求：评级词必须是英文五档，
    交易员报告必须以 ``FINAL TRANSACTION PROPOSAL: **X**`` 收尾，
    否则下游解析器会取不到评级而退化成 REVIEW。
    """
    warns: list[str] = []
    ratings = data.get("ratings") or {}

    for key, allowed in (
        ("research_manager", RATINGS_5_TIER),
        ("portfolio_manager", RATINGS_5_TIER),
        ("trader_action", TRADER_ACTIONS),
    ):
        val = ratings.get(key)
        if val is None:
            warns.append(f"ratings.{key} 缺失")
        elif val not in allowed:
            warns.append(f"ratings.{key}={val!r} 不在允许集合 {allowed}")

    for group, keys in (
        ("analysts", ("market", "sentiment", "news", "fundamentals")),
        ("research", ("bull", "bear", "manager")),
        ("risk", ("aggressive", "conservative", "neutral", "portfolio_manager")),
    ):
        section = data.get(group) or {}
        for k in keys:
            if not (section.get(k) or "").strip():
                warns.append(f"{group}.{k} 为空")

    trader_md = ((data.get("trading") or {}).get("trader") or "").strip()
    if not trader_md:
        warns.append("trading.trader 为空")
    elif not _TRADER_STOP_LINE.search(trader_md):
        warns.append("trading.trader 缺少 'FINAL TRANSACTION PROPOSAL: **X**' 收尾行")

    # 情绪报告的头部是结构化契约的一部分
    sentiment = ((data.get("analysts") or {}).get("sentiment") or "")
    if sentiment and "Overall Sentiment" not in sentiment:
        warns.append("analysts.sentiment 缺少 'Overall Sentiment' 结构化头部")

    return warns


def _field(text: str, label: str) -> str | None:
    """从角色稿里取 `**Label**: value` 的单行值（只取第一处）。"""
    m = re.search(rf"\*\*{re.escape(label)}\*\*\s*[:：]\s*([^\n]+)", text or "")
    return m.group(1).strip() if m else None


def _price(text: str, label: str) -> str | None:
    """取绝对价格：认字段内第一个数字（`28.75` / `1,234.50` / `第一目标 1.5272（MA10）`），忽略百分比与区间。

    ★ 2026-10-24 修：此前用 `re.match`（行首锚定），PM 稿写「第一目标 1.5272（MA10），
       第二目标 1.5961」这类**中文前缀+数字**的合规字段时匹配失败 ⇒ 决策卡「目标价」显示
       「—」、盈亏比随之缺失（实测 512400.SS 轮：卡片与正文结论不一致）。改为 `re.search`
       取字段内第一个数字；对本来就以数字开头的字段行为不变。
    """
    raw = _field(text, label)
    if not raw:
        return None
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)", raw)
    return m.group(1).replace(",", "") if m else None


def build_decision_card(data: dict) -> str:
    """一屏决策卡：评级链 + 入场/止损/目标/盈亏比/仓位/周期。

    ★ 2026-10-19 新增：完整报告 7 万字符，入场价/止损/目标散落在第 III–V 节，
      实盘要翻半天。本卡只做**提取**，不新增任何判断 —— 每个数字都来自角色稿原文，
      取不到就写「—」，绝不推算。
    """
    r = data.get("ratings") or {}
    trader = ((data.get("trading") or {}).get("trader") or "")
    pm = ((data.get("risk") or {}).get("portfolio_manager") or "")
    # 入场/止损/目标：**终审优先，交易员兜底**。
    # ★ 2026-10-20 实测：终审把交易员的单点入场改成两档拆分后，卡片仍显示交易员的 1.4852 与
    #   由其算出的 4.96:1，而实际方案是加权 1.4931、赔率 3.79:1 ⇒ 首屏把赔率高估了 31%。
    #   卡片是读者第一眼看到的东西，口径必须跟终审走。
    entry = _price(pm, "Entry Price") or _price(trader, "Entry Price")
    stop = _price(pm, "Stop Loss") or _price(trader, "Stop Loss")
    target = _price(pm, "Price Target")
    # 仓位：**终审优先**。交易员方案与组合经理裁定可以不一致（PM 有权收紧仓位），
    # 卡片若取交易员值，就会出现「卡片 3% / 结论 2%」的自相矛盾（实测 512400.SS）。
    # 取不到 PM 的口径时退回交易员；两者都没有才写「—」。**绝不推算。**
    pos = _field(pm, "Position Sizing") or _field(trader, "Position Sizing")
    horizon = _field(pm, "Time Horizon")
    rr = "—"
    try:
        e, s, t = float(entry), float(stop), float(target)
        if e > s and t > e:
            rr = f"{(t - e) / (e - s):.2f}:1"
    except (TypeError, ValueError):
        pass

    rows = [
        ("数据基准日", str(data.get("as_of") or "—")),
        ("研究经理", str(r.get("research_manager") or "—")),
        ("交易员", str(r.get("trader_action") or "—")),
        ("组合经理", str(r.get("portfolio_manager") or "—")),
        ("入场价", entry or "—"),
        ("止损价", stop or "—"),
        ("目标价", target or "—"),
        ("盈亏比", rr),
        ("仓位", pos or "—"),
        ("时间跨度", horizon or "—"),
    ]
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return (
        "## 决策卡（一屏）\n\n"
        "| 项 | 值 |\n|---|---|\n" + body + "\n\n"
        "> 本卡为角色稿的**提取**（不新增判断）；论证见下方各节，数字出处见 `_source.zip`。"
    )


def render_report_tree(data: dict, save_path: Path) -> Path:
    """复刻 reporting.py::write_report_tree 的目录结构与章节标题。"""
    ticker = data.get("ticker", "UNKNOWN")
    save_path = Path(save_path)
    save_path.mkdir(parents=True, exist_ok=True)

    sections: list[str] = []
    analysts = data.get("analysts") or {}
    research = data.get("research") or {}
    trading = data.get("trading") or {}
    risk = data.get("risk") or {}

    # 1. 分析师团队
    analyst_parts: list[tuple[str, str]] = []
    for display, key, filename in ANALYST_SECTIONS:
        text = (analysts.get(key) or "").strip()
        if not text:
            continue
        d = save_path / "1_analysts"
        d.mkdir(exist_ok=True)
        (d / filename).write_text(text, encoding="utf-8")
        analyst_parts.append((display, text))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. 研究团队
    research_parts: list[tuple[str, str]] = []
    for display, key, filename in (
        ("Bull Researcher", "bull", "bull.md"),
        ("Bear Researcher", "bear", "bear.md"),
        ("Research Manager", "manager", "manager.md"),
    ):
        text = (research.get(key) or "").strip()
        if not text:
            continue
        d = save_path / "2_research"
        d.mkdir(exist_ok=True)
        (d / filename).write_text(text, encoding="utf-8")
        research_parts.append((display, text))
    if research_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
        sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. 交易团队
    trader_text = (trading.get("trader") or "").strip()
    if trader_text:
        d = save_path / "3_trading"
        d.mkdir(exist_ok=True)
        (d / "trader.md").write_text(trader_text, encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{trader_text}")

    # 4. 风控团队 + 5. 组合经理（上游把第 5 节嵌在第 4 节的条件块内）
    risk_parts: list[tuple[str, str]] = []
    for display, key, filename in (
        ("Aggressive Analyst", "aggressive", "aggressive.md"),
        ("Conservative Analyst", "conservative", "conservative.md"),
        ("Neutral Analyst", "neutral", "neutral.md"),
    ):
        text = (risk.get(key) or "").strip()
        if not text:
            continue
        d = save_path / "4_risk"
        d.mkdir(exist_ok=True)
        (d / filename).write_text(text, encoding="utf-8")
        risk_parts.append((display, text))
    if risk_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
        sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        pm_text = (risk.get("portfolio_manager") or "").strip()
        if pm_text:
            # ★ 2026-10-11（O8）：**草稿名与渲染名刻意不同**，别当成 bug 去"修"。
            #   草稿：`4_risk/portfolio_manager.md`（与 3 个风险分析师同目录）
            #   渲染：`5_portfolio/decision.md`（独立成第 5 个目录）
            #   理由：组合经理不是「第 4 个风险分析师」，它是**最终决策**，
            #         与三份风险意见并列会误导读者（且 §V 在合成报告里单独成章）。
            #   ⇒ 下游读渲染树请一律用 `5_portfolio/decision.md`
            #     （`_verify_report.py` / `_reports_index.py` 均已如此）。
            d = save_path / "5_portfolio"
            d.mkdir(exist_ok=True)
            (d / "decision.md").write_text(pm_text, encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{pm_text}")

    # 合并报告
    header = (
        f"# Trading Analysis Report: {ticker}\n\n"
        f"Generated: {_clock.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    )
    notes = (data.get("notes") or "").strip()
    card = build_decision_card(data)
    body = card + "\n\n" + "\n\n".join(sections)
    if notes:
        body += f"\n\n## 附：数据缺口与说明\n\n{notes}"
    (save_path / "complete_report.md").write_text(header + body, encoding="utf-8")

    return save_path / "complete_report.md"


def resolve_input(target: str, date: str | None) -> Path:
    """解析输入为分析结果 JSON 路径。"""
    p = Path(target)
    if p.suffix.lower() == ".json" and p.exists():
        return p
    if p.exists() and p.is_file():
        return p
    day = date or _clock.now().strftime("%Y-%m-%d")
    guess = ANALYSIS_DIR / f"{target.upper()}_{day}.json"
    return guess


def check_completeness(data: dict) -> list[str]:
    """返回**正文为空**的必需小节列表（空列表表示 12 个角色全部有内容）。

    为什么单列一个门禁（2026-09-19 实测的血泪）：
      `collect.py` 会写一个**空占位 JSON**（评级预填 Hold、12 段正文全空串）到
      `wb_analysis/analysis/<TICKER>_<date>.json`。若用 ticker 入口渲染，会走到这个骨架。
      `validate()` 只把这些报成 **[WARN]**，随后仍然打印 **[OK] 报告树已生成**，
      于是产出一份 **188 字节、只有标题与附注、评级全 Hold** 的"报告"。
      这是本项目最危险的失败形态 —— **报成功 + 外观正常 + 实际是空壳**。

    ⇒ 因此把「必需小节为空」从**警告**升级为**硬门禁**：宁可拒绝渲染，也不产出假报告。
    """
    REQUIRED = (
        ("analysts", ("market", "sentiment", "news", "fundamentals")),
        ("research", ("bull", "bear", "manager")),
        ("trading", ("trader",)),
        ("risk", ("aggressive", "conservative", "neutral", "portfolio_manager")),
    )
    empty: list[str] = []
    for group, keys in REQUIRED:
        section = data.get(group) or {}
        for k in keys:
            if not (section.get(k) or "").strip():
                empty.append(f"{group}.{k}")
    return empty


def code_revision() -> dict:
    """渲染时的代码版本：commit / 是否 dirty / 分支。

    为什么写进 RUN.json：报告是审计产物，`_source.zip` 存了草稿与证据但**不存代码**，
    而代码行为直接决定报告里的数字（例如 `_price` 用 `re.match` 还是 `re.search`，
    决定决策卡目标价是 `1.5272` 还是 `—`）。没有这条绑定，
    「这棵树是哪版代码跑的」只能靠时间戳猜。

    `dirty=True` 表示渲染时工作区有未提交改动 ⇒ 报告可能来自改了一半的代码，
    `_seal_run.py` 会据此提醒。非 git 环境返回全 None，不报错。
    """
    def _git(*args: str) -> str | None:
        try:
            r = subprocess.run(
                ["git", *args], cwd=str(PROJECT_ROOT), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    commit = _git("rev-parse", "--short", "HEAD")
    if not commit:
        return {"commit": None, "dirty": None, "branch": None}
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="把分析结果渲染成 TradingAgents 同构报告树")
    ap.add_argument("target", nargs="?", help="ticker（如 NVDA）或分析结果 JSON 路径")
    ap.add_argument("--from-dir", help="从草稿目录读取（12 个 .md + **必备** meta.json），优先于 target")
    ap.add_argument("--date", default=None, help="基准日期 YYYY-MM-DD，用于定位 JSON")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "reports"), help="报告输出根目录")
    ap.add_argument("--stamp", default=None, help="自定义时间戳 YYYYmmdd_HHMMSS（默认取当前时间）")
    ap.add_argument("--flat", action="store_true",
                    help="使用旧布局：直接写 <out>/<TICKER>_<stamp>/，不再按标的分子目录")
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="跳过「正文不得为空」硬门禁（仅在明确知道自己在做什么时使用）")
    ap.add_argument("--allow-no-meta", action="store_true",
                    help="允许 --from-dir 缺 meta.json 渲染（**会静默产生空 as_of/ratings**，仅排障用）")
    args = ap.parse_args()

    if args.from_dir:
        src = Path(args.from_dir)
        if not src.is_dir():
            print(f"✗ 草稿目录不存在: {src}", file=sys.stderr)
            return 1
        try:
            data = load_from_dir(src, strict=not args.allow_no_meta)
        except MetaMissingError as exc:
            print(f"✗ 拒绝渲染：meta.json 不可用 —— {exc}", file=sys.stderr)
            print(
                "\n  `--from-dir` 需要草稿目录里有一份**可用**的 meta.json：\n"
                "    {\"ticker\": \"NVDA\", \"as_of\": \"2026-10-09\", \"ratings\": {...}, \"notes\": \"...\"}\n"
                "  缺它时报告树会**静默**渲染成 data_date:\"\"、ratings:{}（外观正常、评级却全空），\n"
                "  下游门禁无从察觉 —— 属铁律 3「静默失败」，故此处**硬阻断**（退出码 2）。\n"
                "\n  正确做法（任选其一）：\n"
                "    1) 先跑 $VENV wb_analysis/_gen_meta.py <T>_<date> 自动生成 meta.json\n"
                "    2) 按上面结构手工补写 meta.json\n"
                "    3) 确需无 meta 渲染时，显式加 --allow-no-meta（自担静默降级风险）\n",
                file=sys.stderr,
            )
            return 2
        source_desc = str(src)
    else:
        if not args.target:
            print("✗ 需要提供 ticker / JSON 路径，或用 --from-dir 指定草稿目录", file=sys.stderr)
            return 1
        src = resolve_input(args.target, args.date)
        if not src.exists():
            print(f"✗ 找不到分析结果: {src}", file=sys.stderr)
            print("  请按 FRAMEWORK.md 第 4 节的契约写出该 JSON，或用 --from-dir 指定草稿目录。", file=sys.stderr)
            return 1
        data = json.loads(src.read_text(encoding="utf-8"))
        source_desc = str(src)

    ticker = data.get("ticker") or "UNKNOWN"
    print(f"[输入] {source_desc}")

    # ★ 硬门禁一：正文不得为空（拦截 collect.py 写的空占位骨架）
    empty_sections = check_completeness(data)
    if empty_sections and not args.allow_incomplete:
        print(f"\n✗ 拒绝渲染：{len(empty_sections)} 个必需角色小节正文为空。", file=sys.stderr)
        for s in empty_sections:
            print(f"    - {s}", file=sys.stderr)
        print(
            "\n  这通常意味着你命中了 `wb_analysis/analysis/<TICKER>_<date>.json` 的**空占位骨架**\n"
            "  （`collect.py` 产出：评级预填 Hold、12 段正文全空）。直接渲染会产出一份\n"
            "  「只有标题、评级全 Hold」的假报告，且外观与真实报告无异。\n"
            "\n  正确做法（任选其一）：\n"
            "    1) 用草稿目录渲染：--from-dir wb_analysis/drafts/<TICKER>_<date>\n"
            "    2) 先把真实分析回写成该 JSON，再走 ticker 入口\n"
            "    3) 确实需要渲染空壳时，显式加 --allow-incomplete\n",
            file=sys.stderr,
        )
        return 2

    warns = validate(data)
    warns += crosscheck_with_upstream(data)
    if warns:
        print("[契约校验] 发现以下问题（仍会渲染，但建议修正）：")
        for w in warns:
            print(f"  [WARN] {w}")
    else:
        print("[契约校验] 通过：格式与上游解析器兼容，且评级可被正确提取。")

    stamp = args.stamp or _clock.now().strftime("%Y%m%d_%H%M%S")
    # ★ 2026-09-23 起：默认按**标的分子目录**落盘 —— `reports/<TICKER>/<TICKER>_<stamp>/`
    #   旧行为是把所有报告树平铺在 `reports/` 顶层，跑几十次后就分不清哪个是哪个。
    #   需要旧布局时加 `--flat`。
    ticker_dir = _safe_component(ticker)
    save_path = (Path(args.out) / f"{ticker_dir}_{stamp}" if args.flat
                 else Path(args.out) / ticker_dir / f"{ticker_dir}_{stamp}")
    complete = render_report_tree(data, save_path)

    # ★ 2026-10-10 新增：渲染单页自包含 HTML 报告（吸收上游 report_html 亮点）
    #   提供暗黑模式、自适应排版、纯离线内联 CSS、支持一键打印 PDF。
    try:
        from wb_analysis._report_html import render_html_report
        html_content = render_html_report(data)
        html_path = save_path / "complete_report.html"
        html_path.write_text(html_content, encoding="utf-8", newline="\n")
        print(f"  [HTML] 自包含单页 HTML 报告已生成: {html_path.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] HTML 报告生成异常（不阻断交付）: {exc!r}")

    # ★ 2026-09-23 新增：**运行清单（RUN.json）** —— 把一次运行的四个命名空间显式串起来。
    #   动机：产物分散在 evidence / drafts / analysis / reports 四处，且只有 reports 带时间戳，
    #   重跑时三处被覆盖、一处堆积 ⇒ 事后无法判断「哪棵树对应哪批草稿」，孤儿产物只能靠猜。
    #   写入本清单后，`_reports_index.py` 可据此精确关联，孤儿与错配会**自动暴露**。
    try:
        _src = locals().get("src")
        ev_files = sorted(
            p.name for p in (PROJECT_ROOT / "wb_analysis" / "evidence").glob(f"{ticker}_*")
            if p.is_file() and p.stat().st_mtime <= save_path.stat().st_mtime + 1
        )
        role_n = len([p for p in save_path.rglob("*.md") if p.is_file()])
        run = {
            "ticker": ticker,
            "stamp": stamp,
            "data_date": data.get("as_of", ""),
            "rendered_at": _clock.now().isoformat(timespec="seconds"),
            "source_drafts": str(Path(_src).resolve()) if _src else "",
            "evidence": ev_files,
            "ratings": data.get("ratings", {}),
            "role_files": role_n,
            "layout": "flat" if args.flat else "nested",
            "code": code_revision(),
        }
        (save_path / "RUN.json").write_text(
            json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        _code = run["code"]
        _tag = ""
        if _code.get("commit"):
            _tag = f"，代码 {_code['commit']}" + ("（**dirty**：有未提交改动）" if _code.get("dirty") else "")
        print(f"  [清单] RUN.json 已写入（数据基准日 {run['data_date'] or '未知'}，"
              f"来源 {run['source_drafts'] or '—'}{_tag}）")
    except Exception as exc:  # noqa: BLE001
        # 清单是辅助产物，写失败不应阻断交付 —— 但**必须出声**，不能静默。
        print(f"  [WARN] RUN.json 写入失败（不阻断交付）: {exc!r}")

    ratings = data.get("ratings") or {}
    print(f"\n[OK] 报告树已生成: {save_path}")
    print(f"  完整报告: {complete}")
    if ratings:
        print(f"  评级: 研究经理={ratings.get('research_manager')}"
              f" / 交易员={ratings.get('trader_action')}"
              f" / 组合经理={ratings.get('portfolio_manager')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
