# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_writeback_analysis.py
"""把草稿目录的 12 个角色文件回写 `wb_analysis/analysis/<T>_<date>.json`。

用途（项目铁律 9）：`collect*.py` 只生成**空骨架** JSON，`assemble.py --from-dir` 走的是草稿目录；
若不回写，`assemble.py <TICKER> --date <date>` 这个入口就会命中空骨架、渲染出「评级全 Hold 且正文空」的报告。
本脚本把真实分析回写，使该入口也可用。

用法: ./.venv/Scripts/python.exe wb_analysis/_writeback_analysis.py GOOG 2026-09-21 [NDX 2026-09-21 ...]
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

MAP = {
    "analysts": {
        "market": "1_analysts/market.md",
        "sentiment": "1_analysts/sentiment.md",
        "news": "1_analysts/news.md",
        "fundamentals": "1_analysts/fundamentals.md",
    },
    "research": {
        "bull": "2_research/bull.md",
        "bear": "2_research/bear.md",
        "manager": "2_research/manager.md",
    },
    "trading": {"trader": "3_trading/trader.md"},
    "risk": {
        "aggressive": "4_risk/aggressive.md",
        "conservative": "4_risk/conservative.md",
        "neutral": "4_risk/neutral.md",
        "portfolio_manager": "4_risk/portfolio_manager.md",
    },
}


def write_one(ticker: str, date: str) -> int:
    draft = ROOT / "wb_analysis" / "drafts" / f"{ticker}_{date}"
    out_path = ROOT / "wb_analysis" / "analysis" / f"{ticker}_{date}.json"
    meta = json.loads((draft / "meta.json").read_text(encoding="utf-8"))

    obj = {
        "ticker": ticker,
        "as_of": date,
        "ratings": meta.get("ratings", {}),
        "analysts": {},
        "research": {},
        "trading": {},
        "risk": {},
        "notes": meta.get("notes", ""),
    }
    missing = []
    for section, files in MAP.items():
        for key, rel in files.items():
            p = draft / rel
            if not p.exists():
                missing.append(rel)
                obj[section][key] = ""
            else:
                obj[section][key] = p.read_text(encoding="utf-8")
    if missing:
        print(f"  ✗ {ticker}_{date}: 缺文件 {missing} —— 拒绝回写（避免写入半成品）")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    empty = [f"{s}.{k}" for s, d in MAP.items() for k in d if not obj[s][k].strip()]
    print(
        f"  ✓ {out_path.name}  字节 {len(out_path.read_bytes())}  "
        f"评级 {obj['ratings']}  空小节 {empty or '无'}"
    )
    return 0 if not empty else 1


def main() -> int:
    args = sys.argv[1:]
    if len(args) % 2:
        print("用法: _writeback_analysis.py <TICKER> <YYYY-MM-DD> [<TICKER> <DATE> ...]")
        return 2
    rc = 0
    for i in range(0, len(args), 2):
        rc |= write_one(args[i], args[i + 1])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
