# lifecycle: oneoff
"""校验交付树 vs 草稿目录是否逐字一致（assemble 会剥掉文件末尾换行，故 norm 需 rstrip 一个换行）。"""
from pathlib import Path

ROOT = Path(r"D:\Antigravity\TradingAgents")
DRAFT = ROOT / "wb_analysis/drafts/NFLX_2026-10-12"
TREE = ROOT / "reports/NFLX/NFLX_20261013_093534"

PAIRS = [
    ("1_analysts/market.md", "1_analysts/market.md"),
    ("1_analysts/fundamentals.md", "1_analysts/fundamentals.md"),
    ("1_analysts/news.md", "1_analysts/news.md"),
    ("1_analysts/sentiment.md", "1_analysts/sentiment.md"),
    ("2_research/bull.md", "2_research/bull.md"),
    ("2_research/bear.md", "2_research/bear.md"),
    ("2_research/manager.md", "2_research/manager.md"),
    ("3_trading/trader.md", "3_trading/trader.md"),
    ("4_risk/aggressive.md", "4_risk/aggressive.md"),
    ("4_risk/conservative.md", "4_risk/conservative.md"),
    ("4_risk/neutral.md", "4_risk/neutral.md"),
    ("4_risk/portfolio_manager.md", "5_portfolio/decision.md"),
]


def norm(t: str) -> str:
    return t.rstrip("\n")


bad = 0
for d_rel, t_rel in PAIRS:
    dp, tp = DRAFT / d_rel, TREE / t_rel
    if not tp.exists():
        print(f"  MISSING in tree: {t_rel}")
        bad += 1
        continue
    d = norm(dp.read_text(encoding="utf-8"))
    t = norm(tp.read_text(encoding="utf-8"))
    same = d == t
    if not same:
        bad += 1
    print(f"  {'OK ' if same else 'DIFF'} {d_rel:36s} draft={len(d):>6} tree={len(t):>6} delta={len(t)-len(d):>+4}")
print(f"\n不一致项：{bad}")
