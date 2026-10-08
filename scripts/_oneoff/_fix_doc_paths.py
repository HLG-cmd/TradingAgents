# lifecycle: oneoff
# created: 2026-10-08
# serves: 修复 docs/WORKFLOW.md 与 docs/SCREENER.md 的过时命令路径（quant/ 迁移后遗留）
"""把文档里的旧路径改成迁移后的真实路径，每处替换都断言命中数。

背景（2026-10-08）：2026-09-23 自建代码全部移入 `quant/` 包，但 WORKFLOW.md / SCREENER.md
里的**示例命令没有跟着改** —— 照文档抄会直接 ImportError / file not found。
本脚本逐项替换并断言命中数，命中数为 0 即中止（防止"改了但没命中"的静默失败）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (文件, 旧串, 新串, 期望命中数)
RULES = [
    # ── WORKFLOW.md ──
    ("docs/WORKFLOW.md", "`python wb_deep_dive.py --pool nasdaq --top 10`",
     "`python quant/wb_deep_dive.py --pool nasdaq --top 10`", 1),
    ("docs/WORKFLOW.md", "`python wb_deep_dive.py --tickers NVDA,MU,SNDK`",
     "`python quant/wb_deep_dive.py --tickers NVDA,MU,SNDK`", 1),
    ("docs/WORKFLOW.md", "`python factor_backtest.py --watch`<br>`python fundamental_backtest.py --watch --neutral`",
     "`python quant/factor_backtest.py --watch`<br>`python quant/fundamental_backtest.py --watch --neutral`", 1),
    ("docs/WORKFLOW.md", 'python -c "from stock_pools import get_latest_nasdaq_100 as g; from edgar_fundamentals import preload; preload(g())"',
     'python -c "from quant.stock_pools import get_latest_nasdaq_100 as g; from quant.edgar_fundamentals import preload; preload(g())"', 1),
    ("docs/WORKFLOW.md", 'python -c "from stock_pools import get_latest_nasdaq_100 as g; from price_history import preload_prices; preload_prices(g())"',
     'python -c "from quant.stock_pools import get_latest_nasdaq_100 as g; from quant.price_history import preload_prices; preload_prices(g())"', 2),
    ("docs/WORKFLOW.md", "python wb_deep_dive.py --pool nasdaq --top 10",
     "python quant/wb_deep_dive.py --pool nasdaq --top 10", 2),
    ("docs/WORKFLOW.md", "python smart_screener.py --pool nasdaq --skip-agent",
     "python quant/smart_screener.py --pool nasdaq --skip-agent", 1),
    ("docs/WORKFLOW.md", "from screener_engine import run_quant_screening, WEIGHT_PROFILES",
     "from quant.screener_engine import run_quant_screening, WEIGHT_PROFILES", 1),
    ("docs/WORKFLOW.md", "python wb_deep_dive.py --tickers NVDA,MU,SNDK            # 从第 1 层候选里挑 1~3 只",
     "python quant/wb_deep_dive.py --tickers NVDA,MU,SNDK      # 从第 1 层候选里挑 1~3 只", 1),
    ("docs/WORKFLOW.md", "python wb_deep_dive.py --tickers NVDA --no-news --no-social   # 想更快：跳过新闻与社媒（约 30 秒/只）",
     "python quant/wb_deep_dive.py --tickers NVDA --no-news --no-social   # 想更快：跳过新闻与社媒（约 30 秒/只）", 1),
    ("docs/WORKFLOW.md", "python factor_backtest.py --watch                    # 价格类因子（权重 20%）",
     "python quant/factor_backtest.py --watch              # 价格类因子（权重 20%）", 1),
    ("docs/WORKFLOW.md", "python fundamental_backtest.py --watch --neutral      # 基本面类（权重 80%，EDGAR）",
     "python quant/fundamental_backtest.py --watch --neutral  # 基本面类（权重 80%，EDGAR）", 1),
    ("docs/WORKFLOW.md", "python fundamental_backtest.py --forward 252 --rebalance 12 --neutral --start 2009-01",
     "python quant/fundamental_backtest.py --forward 252 --rebalance 12 --neutral --start 2009-01", 1),
    ("docs/WORKFLOW.md", "python fundamental_backtest.py --neutral              # 月度调仓 + 1 个月前瞻",
     "python quant/fundamental_backtest.py --neutral        # 月度调仓 + 1 个月前瞻", 1),
    ("docs/WORKFLOW.md", "python factor_backtest.py --watch                      # 价格类因子",
     "python quant/factor_backtest.py --watch                # 价格类因子", 1),
    ("docs/WORKFLOW.md", "from edgar_fundamentals import cache_size_mb, prune_cache",
     "from quant.edgar_fundamentals import cache_size_mb, prune_cache", 1),
    # ── SCREENER.md ──
    ("docs/SCREENER.md", "python smart_screener.py --pool nasdaq --skip-agent",
     "python quant/smart_screener.py --pool nasdaq --skip-agent", 1),
    ("docs/SCREENER.md", "python wb_deep_dive.py  --pool nasdaq --top 3 --no-social",
     "python quant/wb_deep_dive.py  --pool nasdaq --top 3 --no-social", 1),
    ("docs/SCREENER.md", "python factor_backtest.py\n", "python quant/factor_backtest.py\n", 1),
    ("docs/SCREENER.md", "python factor_backtest.py --watch            # 有告警时退出码=2，可接 CI",
     "python quant/factor_backtest.py --watch      # 有告警时退出码=2，可接 CI", 1),
    ("docs/SCREENER.md", "python factor_backtest.py --watch    # 退出码 2 = 有告警，需要看一眼",
     "python quant/factor_backtest.py --watch   # 退出码 2 = 有告警，需要看一眼", 1),
    ("docs/SCREENER.md", "from screener_engine import run_quant_screening, WEIGHT_PROFILES",
     "from quant.screener_engine import run_quant_screening, WEIGHT_PROFILES", 1),
    ("docs/SCREENER.md", "from screener_engine import run_quant_screening",
     "from quant.screener_engine import run_quant_screening", 1),
]


def main() -> int:
    bad = 0
    cache: dict[str, str] = {}
    for rel, old, new, expect in RULES:
        p = ROOT / rel
        if rel not in cache:
            cache[rel] = p.read_text(encoding="utf-8")
        n = cache[rel].count(old)
        if n != expect:
            print(f"  ✗ {rel}: 期望 {expect} 命中，实际 {n} —— {old[:60]!r}")
            bad += 1
            continue
        cache[rel] = cache[rel].replace(old, new)
        print(f"  ✓ {rel} ×{n}  {old[:52]}")
    if bad:
        print(f"\n✗ {bad} 项未命中，**未写盘**（防止半改状态）")
        return 1
    for rel, txt in cache.items():
        (ROOT / rel).write_text(txt, encoding="utf-8", newline="\n")
        print(f"\n已写入 {rel}（{len(txt)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
