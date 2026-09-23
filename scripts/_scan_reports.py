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
    meta = d / "meta.json"
    if meta.exists():
        try:
            ratings = json.loads(meta.read_text(encoding="utf-8")).get("ratings", {})
        except Exception:  # noqa: BLE001
            ratings = {"_error": "meta.json 解析失败"}
    return {
        "dir": d.name,
        "mtime": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
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

    dirs = sorted([d for d in REPORTS.iterdir() if d.is_dir()], key=lambda d: d.name)
    rows = []
    for d in dirs:
        if d.name.startswith("_"):
            continue
        if not re.search(r"_\d{8}_\d{6}$", d.name):
            # 非标准报告树（如 SCREEN_REVIEW_... / STORAGE_3WAY_...）
            info = {
                "dir": d.name, "mtime": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "n_files": len([p for p in d.rglob("*") if p.is_file()]),
                "size_kb": round(sum(p.stat().st_size for p in d.rglob("*") if p.is_file()) / 1024, 1),
                "complete_report_chars": 0, "roles_present": 0, "roles_missing": ["(非 12 角色报告树)"],
                "ratings": {}, "has_brief": False,
                "extra_top": sorted({p.name for p in d.iterdir() if p.is_file()}),
            }
            rows.append(info)
            continue
        rows.append(tree_info(d))

    print(f"\n共 {len(rows)} 个目录\n")
    print(f"{'目录':34s} {'修改时间':17s} {'文件':>5s} {'KB':>8s} {'完整报告字符':>12s} {'角色':>5s}  评级")
    print("-" * 118)
    dup = {}
    for r in rows:
        ticker = r["dir"].split("_")[0]
        dup.setdefault(ticker, []).append(r["dir"])
        flag = "" if r["roles_present"] == 12 else "  ← 不完整"
        rat = "/".join(str(v) for v in r["ratings"].values()) or "—"
        print(f"{r['dir']:34s} {r['mtime']:17s} {r['n_files']:5d} {r['size_kb']:8.1f} "
              f"{r['complete_report_chars']:12d} {r['roles_present']:5d}  {rat}{flag}")

    print("\n" + "=" * 100)
    print("★ 同一标的多次运行（候选：保留最新，其余归档）")
    print("=" * 100)
    for t, ds in sorted(dup.items()):
        if len(ds) > 1:
            print(f"  {t:12s} {len(ds)} 次：")
            for x in ds:
                print(f"      {x}")

    print("\n" + "=" * 100)
    print("★ 顶层散落文件（不在任何报告树内）")
    print("=" * 100)
    loose = [p for p in REPORTS.iterdir() if p.is_file()]
    for p in sorted(loose, key=lambda x: x.name):
        print(f"  {p.name:52s} {p.stat().st_size/1024:8.1f} KB  "
              f"{datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}")

    print("\n" + "=" * 100)
    print("★ 已存在的归档目录")
    print("=" * 100)
    for name in ("_archive", "_audit"):
        d = REPORTS / name
        if d.is_dir():
            n = len([p for p in d.rglob("*") if p.is_file()])
            print(f"  {name:12s} {n:4d} 个文件  {sum(p.stat().st_size for p in d.rglob('*') if p.is_file())/1024/1024:.1f} MB")
            for sub in sorted(d.iterdir())[:12]:
                print(f"      - {sub.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
