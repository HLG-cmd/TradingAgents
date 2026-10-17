# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/smart_screener.py
# Smart Screener v2.0: Multi-Factor GARP Radar + TradingAgents Adversarial Debate
from __future__ import annotations

import os
import sys
import datetime
import argparse
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent  # quant/ 的上一级才是项目根
# ── 包内引导（2026-09-23 收进 quant/ 时加入）──────────────────────────────
# 直接运行本文件时（python quant/smart_screener.py）sys.path[0] 是 quant/，
# **项目根不在路径里** ⇒ `from quant.xxx import ...` 会报 No module named 'quant'。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
import questionary

from quant.stock_pools import (
    SP_500_CORE,
    get_latest_nasdaq_100,
    get_latest_sp500,
)
from quant.screener_engine import (
    FACTOR_WEIGHTS,
    run_quant_screening,
    export_radar_csv,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# rich 在非 TTY（管道/批处理/重定向）下会退化到 80 列，13 列的多因子表会被
# 全部截断成「…」，输出不可读。这里显式放宽宽度，保证脚本化运行时也完整。
console = Console(width=max(200, os.environ.get("COLUMNS") and int(os.environ["COLUMNS"]) or 200))


def main():
    parser = argparse.ArgumentParser(description="TradingAgents Smart Screener v2.0")
    parser.add_argument(
        "--pool",
        choices=["nasdaq", "sp500", "sp500_core", "custom"],
        help="股票池: nasdaq, sp500(全量动态), sp500_core(99只核心), 或 custom",
    )
    parser.add_argument("--tickers", help="自定义股票代码，逗号分隔 (如 NVDA,AAPL,GOOGL)")
    parser.add_argument("--top", type=int, default=3, help="深度会诊的候选股票数量 (默认 3)")
    parser.add_argument("--rounds", type=int, choices=[1, 2, 3], help="对抗辩论轮数 (默认 2)")
    parser.add_argument("--provider", choices=["google", "deepseek"], help="LLM 服务商")
    parser.add_argument("--skip-agent", action="store_true", help="仅执行量化初筛，跳过智能体会诊")
    parser.add_argument("--force-refresh", action="store_true", help="强制重新下载数据，不读取本地日内缓存")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold cyan]TradingAgents 智能选股雷达与终审系统 (v2.0 升级版)[/bold cyan]\n"
        "[green]四维 GARP 多因子初筛 (质量+估值+成长+动量) + 多智能体多轮对抗会诊[/green]",
        border_style="cyan"
    ))

    choice = args.pool
    if not choice and not args.tickers:
        choice = questionary.select(
            "请选择选股目标池:",
            choices=[
                questionary.Choice("1. 纳斯达克 100 成分股 (科技/成长龙头, 支持动态同步)", "nasdaq"),
                questionary.Choice("2. 标普 500 全量成分股 (约 503 只, 支持动态同步)", "sp500"),
                questionary.Choice("3. 标普 500 核心成分股 (99 只精选大盘核心)", "sp500_core"),
                questionary.Choice("4. 自定义股票池 (手动输入多只代码)", "custom"),
            ]
        ).ask()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        pool_name = "自定义股票池"
        pool_key = "custom"
    elif choice == "nasdaq":
        tickers = get_latest_nasdaq_100()
        pool_name = "纳斯达克100"
        pool_key = "nasdaq"
    elif choice == "sp500":
        tickers = get_latest_sp500()
        pool_name = "标普500全量"
        pool_key = "sp500"
    elif choice == "sp500_core":
        tickers = SP_500_CORE
        pool_name = "标普500核心"
        pool_key = "sp500_core"
    else:
        raw_input = questionary.text("请输入股票代码 (逗号分隔，如 NVDA, AAPL, GOOGL, TSLA, MSFT):").ask()
        tickers = [t.strip().upper() for t in raw_input.split(",") if t.strip()]
        pool_name = "自定义股票池"
        pool_key = "custom"

    if not tickers:
        console.print("[red]未提供有效股票代码，退出。[/red]")
        return

    console.print(f"\n[bold yellow]=== 阶段一：{pool_name} 四维 GARP 多因子量化扫描 ===[/bold yellow]")
    res = run_quant_screening(tickers, top_n=10, pool_name=pool_key, force_refresh=args.force_refresh, return_details=True)

    if isinstance(res, dict):
        top_10 = res["top_df"]
        failed_records = res.get("failed_records", [])
        metadata = res.get("metadata", {})
    else:
        top_10 = res.head(10)
        failed_records = getattr(res, "failed_records", getattr(res, "attrs", {}).get("failed_records", []))
        metadata = getattr(res, "metadata", getattr(res, "attrs", {}).get("metadata", {}))

    if top_10.empty:
        console.print("[red]未能获取到有效的量化行情数据，请检查网络或代理后重试。[/red]")
        return

    # 1. 渲染主榜单表格 (四维多因子雷达)
    table = Table(title=f"[Top 10] {pool_name} 四维 GARP 多因子雷达天梯榜", border_style="green")
    table.add_column("排名", justify="center", style="bold")
    table.add_column("代码", justify="center", style="bold cyan")
    table.add_column("现价", justify="right")
    table.add_column("综合分", justify="right", style="bold magenta")
    table.add_column("质量分", justify="right", style="cyan")
    table.add_column("估值分", justify="right", style="green")
    table.add_column("成长分", justify="right", style="yellow")
    table.add_column("动量分", justify="right", style="blue")
    table.add_column("市盈率PE", justify="right")
    table.add_column("ROE%", justify="right")
    table.add_column("净利率%", justify="right")
    table.add_column("营收增速%", justify="right")
    table.add_column("60日%", justify="right")

    for idx, row in top_10.iterrows():
        table.add_row(
            str(idx + 1),
            row["Ticker"],
            f"{row['Price']:.2f}",
            f"{row['综合量化分']:.1f}",
            f"{row['quality_score']:.1f}",
            f"{row['val_score']:.1f}",
            f"{row['growth_score']:.1f}",
            f"{row['trend_score']:.1f}",
            str(row["PE"]),
            str(row["ROE%"]),
            str(row["净利率%"]),
            str(row["营收增速%"]),
            f"{row['60日涨幅%']:+.1f}%"
        )
    console.print(table)

    # 2. 渲染被排除或异常的标的列表 (透明度展示)
    if failed_records:
        console.print(f"\n[yellow][!] 本次扫描共有 {len(failed_records)} 只标的因数据缺失/退市/停牌被安全剔除：[/yellow]")
        fail_table = Table(title="异常/剔除标的审计清单", border_style="yellow")
        fail_table.add_column("标的代码", justify="center", style="bold red")
        fail_table.add_column("剔除原因", justify="left")
        for rec in failed_records[:8]:
            fail_table.add_row(rec["ticker"], rec["reason"])
        if len(failed_records) > 8:
            fail_table.add_row("...", f"等其余 {len(failed_records)-8} 只标的")
        console.print(fail_table)

    # 3. 导出全量量化结果为 CSV（与是否启动终审无关，--skip-agent 也要产出）
    #    必须用 UTF-8 BOM，否则中文表头在中文 Windows 的 Excel 里会被按 GBK 解析，
    #    显示成「20鏃ユ定骞�%」这类乱码。
    #
    #    命名故意用**日期**而非时间戳：量化结果按天走日内缓存，同一天重复运行
    #    产出的是逐字节相同的数据，用时间戳会不断堆出重复文件。
    #    报告（.md）仍用时间戳 —— 它记录的是「这一次会诊了谁」，有历史价值。
    try:
        src_df = res.get("full_df") if isinstance(res, dict) else res
        if src_df is not None and not src_df.empty:
            reports_dir = PROJECT_ROOT / "reports" / "_datasets"   # 数据产品统一落 _datasets/
            reports_dir.mkdir(parents=True, exist_ok=True)
            csv_file = reports_dir / f"radar_{pool_key}_{datetime.date.today().isoformat()}.csv"
            export_radar_csv(src_df, str(csv_file))
            console.print(f"\n[green][OK] 量化明细已导出（UTF-8 BOM，Excel 可直接打开）: {csv_file.name}[/green]")
    except Exception as exc:
        console.print(f"\n[yellow][WARN] CSV 导出失败: {exc}[/yellow]")

    # 4. 候选标的确认与辩论轮数配置
    top_n_cand = args.top if args.top else 3
    candidates = list(top_10["Ticker"].head(top_n_cand))
    console.print(f"\n[bold cyan]阶段一优胜前 {len(candidates)} 名决赛候选：[/bold cyan] [bold yellow]{', '.join(candidates)}[/bold yellow]")

    if args.skip_agent:
        console.print("[yellow]已指定 --skip-agent，完成第一阶段量化筛选，跳过多智能体终审。[/yellow]")
        return

    do_agent = True
    if args.rounds is None and not args.provider:
        do_agent = questionary.confirm(
            f"是否立即启动 TradingAgents 多智能体团队，对这 {len(candidates)} 只优选标的进行【终审多空对抗会诊】？",
            default=True
        ).ask()

    if not do_agent:
        console.print("[yellow]已完成第一阶段量化筛选，未启动多智能体终审。[/yellow]")
        return

    debate_choice = args.rounds
    if debate_choice is None:
        debate_choice = questionary.select(
            "请选择多智能体对抗辩论轮数 (解决一轮流无反驳问题):",
            choices=[
                questionary.Choice("2 轮对抗辩论 (推荐：牛熊充分交锋挑刺，结论客观扎实)", 2),
                questionary.Choice("1 轮快速会诊 (省时/极速体验)", 1),
                questionary.Choice("3 轮深度博弈 (极致严谨，多空全面攻防)", 3),
            ],
            default=2
        ).ask()

    provider = args.provider or os.getenv("TRADINGAGENTS_LLM_PROVIDER")
    if not provider:
        provider = questionary.select(
            "请选择会诊使用的模型:",
            choices=[
                questionary.Choice("Google Gemini (免费/速度极快)", "google"),
                questionary.Choice("DeepSeek (官方推理/中文犀利)", "deepseek"),
            ]
        ).ask()

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = provider
    if provider == "google":
        config["quick_think_llm"] = "gemini-2.5-flash"
        config["deep_think_llm"] = "gemini-2.5-flash"
    elif provider == "deepseek":
        config["quick_think_llm"] = "deepseek-chat"
        config["deep_think_llm"] = "deepseek-chat"

    config["max_debate_rounds"] = int(debate_choice)
    config["max_risk_discuss_rounds"] = int(debate_choice)
    config["output_language"] = "Chinese"

    trade_date = datetime.date.today().strftime("%Y-%m-%d")
    console.print(f"\n[bold magenta]=== 阶段二：启动 TradingAgents 终极会诊 (基准日期: {trade_date}，辩论轮数: {debate_choice}轮) ===[/bold magenta]")
    
    final_results = []
    ta = TradingAgentsGraph(debug=False, config=config)

    for i, ticker in enumerate(candidates, start=1):
        console.print(f"\n[bold cyan][{i}/{len(candidates)}] 正在会诊标的: {ticker}...[/bold cyan]")
        try:
            state, signal = ta.propagate(ticker, trade_date)
            decision_text = str(signal)
            
            full_decision = state.get("final_trade_decision") or "无终审决策内容"
            trader_plan = state.get("trader_investment_plan") or ""
            research_plan = state.get("investment_plan") or ""
            
            summary = full_decision[:150].replace("\n", " ") + "..."
            
            final_results.append({
                "Ticker": ticker,
                "Signal": decision_text,
                "Summary": summary,
                "FullDecision": full_decision,
                "TraderPlan": trader_plan,
                "ResearchPlan": research_plan,
            })
            console.print(f"[green][OK] {ticker} 会诊完成！评级: {decision_text}[/green]")
        except Exception as e:
            console.print(f"[red][FAIL] {ticker} 会诊出现异常: {e}[/red]")
            final_results.append({
                "Ticker": ticker,
                "Signal": "ERR",
                "Summary": str(e)[:100],
                "FullDecision": str(e),
                "TraderPlan": "",
                "ResearchPlan": "",
            })

    console.print("\n" + "="*60)
    console.print(Panel("[bold green][Top Ranking] 多智能体终审决断对比总榜[/bold green]", border_style="green"))
    
    final_table = Table(title="候选股终审裁决对比", border_style="cyan")
    final_table.add_column("标的代码", justify="center", style="bold cyan")
    final_table.add_column("AI 投资评级", justify="center", style="bold yellow")
    final_table.add_column("核心策略与逻辑摘要", justify="left")

    for res in final_results:
        sig = res["Signal"]
        style = "green" if "BUY" in sig.upper() else ("yellow" if "HOLD" in sig.upper() else "red")
        final_table.add_row(
            res["Ticker"],
            f"[{style}]{sig}[/{style}]",
            res["Summary"]
        )
    console.print(final_table)

    # 4. 生成完整研报 Markdown
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    reports_dir = PROJECT_ROOT / "reports" / "_other"      # 非 12 角色的专题报告统一落 _other/
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_file = reports_dir / f"screener_{pool_key}_{timestamp}.md"
    
    w_str = (
        f"质量 {FACTOR_WEIGHTS['quality']*100:.0f}% + "
        f"估值 {FACTOR_WEIGHTS['value']*100:.0f}% + "
        f"成长 {FACTOR_WEIGHTS['growth']*100:.0f}% + "
        f"趋势 {FACTOR_WEIGHTS['trend']*100:.0f}%"
    )
    md_content = f"# {pool_name} 智能量化漏斗与终审报告 (v2.0)\n\n"
    md_content += f"- **生成时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    md_content += f"- **多因子模型**: 四维 GARP ({w_str})\n"
    md_content += f"- **辩论轮数**: {debate_choice} 轮对抗交锋\n\n"
    md_content += "## 一、四维 GARP 多因子初筛 Top 10\n\n"
    try:
        md_content += top_10.to_markdown(index=False) + "\n\n"
    except Exception:
        md_content += top_10.to_string(index=False) + "\n\n"

    if failed_records:
        md_content += f"### [!] 异常/剔除标的清单 ({len(failed_records)} 只)\n\n"
        for rec in failed_records:
            md_content += f"- **{rec['ticker']}**: {rec['reason']}\n"
        md_content += "\n"

    md_content += "## 二、多智能体深度会诊裁决与策略详情\n\n"
    for res in final_results:
        md_content += f"### 【{res['Ticker']}】AI 评级: {res['Signal']}\n\n"
        md_content += "#### 1. 投资组合经理终审决策 (Portfolio Decision)\n\n"
        md_content += f"{res.get('FullDecision', res['Summary'])}\n\n"
        if res.get("TraderPlan"):
            md_content += "#### 2. 交易员执行与建仓方案 (Trader Proposal)\n\n"
            md_content += f"{res['TraderPlan']}\n\n"
        if res.get("ResearchPlan"):
            md_content += "#### 3. 研究经理多空裁定方案 (Research Plan)\n\n"
            md_content += f"{res['ResearchPlan']}\n\n"
        
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(md_content)

    console.print(f"\n[bold green][OK] 完整选股研报已保存至:[/bold green] {report_file.resolve()}")


if __name__ == "__main__":
    main()
