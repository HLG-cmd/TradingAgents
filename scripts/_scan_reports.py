# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe scripts/_scan_reports.py
"""只读扫描 `reports/` 与 `wb_analysis/` 的产物堆积情况，输出分类清单（不修改任何文件）。

用途：为「报告归档 / 目录瘦身」提供**可复核的清单**。按项目铁律，
**扫描阶段只读**——生成清单后必须由用户确认具体文件，才允许进入归档/删除阶段。

判定「不完整」的判据（本项目 `assemble.py::check_completeness()` 的同一套口径）：
  12 个必需角色小节任一缺失/为空 ⇒ 不完整。

用法: ./.venv/Scripts/python.exe scripts/_scan_reports.py
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from wb_analysis._paths import FUNC_DIRS, TREE_RE, iter_report_trees  # noqa: E402

REPORTS = ROOT / "reports"

# assemble.py 的 12 角色必需文件（相对报告树）
ROLE_FILES = [
    "1_analysts/market.md", "1_analysts/sentiment.md", "1_analysts/news.md",
    "1_analysts/fundamentals.md",
    "2_research/bull.md", "2_research/bear.md", "2_research/manager.md",
    "3_trading/trader.md",
    "4_risk/aggressive.md", "4_risk/conservative.md", "4_risk/neutral.md",
    "5_portfolio/decision.md",
]
# 旧版报告可能用的路径
ALT = {
    "5_portfolio/decision.md": ["5_portfolio/decision.md", "4_risk/portfolio_manager.md"],
}

EARLY_MARKERS = re.compile(r"不完整|旧版|较早|早期|v1|草稿|未完成")


def tree_info(d: Path) -> dict:
    files = [p for p in d.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    present, missing = [], []
    for rel in ROLE_FILES:
        cands = ALT.get(rel, [rel])
        hit = next((c for c in cands if (d / c).exists()), None)
        if hit and (d / hit).stat().st_size > 200:
            present.append(hit)
        else:
            missing.append(rel)
    cr = d / "complete_report.md"
    cr_chars = len(cr.read_text(encoding="utf-8")) if cr.exists() else 0
    ratings = {}
    for mf in ("RUN.json", "meta.json"):
        mp = d / mf
        if mp.exists():
            try:
                ratings = json.loads(mp.read_text(encoding="utf-8")).get("ratings", {})
                if ratings:
                    break
            except Exception:  # noqa: BLE001
                ratings = {"_error": f"{mf} 解析失败"}
    m = TREE_RE.match(d.name)
    ticker = m.group(1) if m else d.parent.name
    return {
        "ticker": ticker,
        "dir": d.name,
        "mtime": datetime.fromtimestamp((cr if cr.exists() else d).stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        "n_files": len(files),
        "size_kb": round(size / 1024, 1),
        "complete_report_chars": cr_chars,
        "roles_present": len(present),
        "roles_missing": missing,
        "ratings": ratings,
        "has_brief": (d / "0_brief.md").exists() or any(p.name == "0_brief.md" for p in files),
        "extra_top": sorted({p.name for p in d.iterdir() if p.is_file()}),
    }


def main() -> int:
    print("=" * 100)
    print("reports/ 只读盘点（不修改任何文件）")
    print("=" * 100)

    # ★ 2026-10-15 修：使用 `iter_report_trees(REPORTS)` 扫描二级目录 `reports/<标的>/<树>/`，
    #   修复此前按旧扁平布局扫描顶层导致全部标的目录被误判为「非 12 角色报告树」的缺陷。
    rows = [tree_info(tr) for _tk, tr in iter_report_trees(REPORTS)]

    print(f"\n共 {len(rows)} 棵报告树\n")
    print(f"{'目录':34s} {'修改时间':17s} {'文件':>5s} {'KB':>8s} {'完整报告字符':>12s} {'角色':>5s}  评级")
    print("-" * 118)
    dup = {}
    for r in rows:
        ticker = r["ticker"]
        dup.setdefault(ticker, []).append(r["dir"])
        flag = "" if r["roles_present"] == 12 else "  ← 不完整"
        rat = "/".join(str(v) for v in r["ratings"].values()) or "—"
        print(f"{r['dir']:34s} {r['mtime']:17s} {r['n_files']:5d} {r['size_kb']:8.1f} "
              f"{r['complete_report_chars']:12d} {r['roles_present']:5d}  {rat}{flag}")

    print("\n" + "=" * 100)
    print("★ 同一标的多次运行（按历史轮次排列）")
    print("=" * 100)
    for t, ds in sorted(dup.items()):
        if len(ds) > 1:
            print(f"  {t:12s} {len(ds)} 次：")
            for x in ds:
                print(f"      {x}")

    print("\n" + "=" * 100)
    print("★ 顶层散落文件（不在任何报告树内）")
    print("=" * 100)
    loose = [p for p in REPORTS.iterdir() if p.is_file()] if REPORTS.exists() else []
    for p in sorted(loose, key=lambda x: x.name):
        print(f"  {p.name:52s} {p.stat().st_size/1024:8.1f} KB  "
                  f"{datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}")

    print("\n" + "=" * 100)
    print("★ 已存在的功能/归档目录")
    print("=" * 100)
    for name in sorted(FUNC_DIRS):
        d = REPORTS / name
        if d.is_dir():
            n = len([p for p in d.rglob("*") if p.is_file()])
            print(f"  {name:12s} {n:4d} 个文件  {sum(p.stat().st_size for p in d.rglob('*') if p.is_file())/1024/1024:.1f} MB")
            for sub in sorted(d.iterdir())[:12]:
                print(f"      - {sub.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
