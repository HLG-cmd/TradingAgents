# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe scripts/_scan_project.py
"""只读扫描整个项目的「产物堆积」情况（不修改任何文件）。

目的：回答「为什么每跑一次项目就更乱」——需要先把**堆积点**数清楚。
覆盖：reports/ · wb_analysis/{evidence,drafts,analysis} · 项目根散落文件 · 脚本目录 · 缓存。

用法: ./.venv/Scripts/python.exe scripts/_scan_project.py
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from wb_analysis._paths import iter_report_trees  # noqa: E402

ROLE_MIN_CHARS = 400          # 认为「该小节有实质内容」的阈值
SECTION_RE = re.compile(r"^#{2,3} .+", re.M)


def hr(t):
    print("\n" + "=" * 100)
    print(t)
    print("=" * 100)


def dir_stat(d: Path):
    if not d.exists():
        return 0, 0.0
    fs = [p for p in d.rglob("*") if p.is_file()]
    return len(fs), sum(p.stat().st_size for p in fs) / 1024 / 1024


def main() -> int:
    hr("1. wb_analysis/ 各子目录规模")
    for sub in ("evidence", "drafts", "analysis"):
        d = ROOT / "wb_analysis" / sub
        n, mb = dir_stat(d)
        tk = Counter()
        for p in d.iterdir() if d.exists() else []:
            if p.is_dir() or p.is_file():
                tk[p.name.split("_")[0]] += 1
        print(f"  {sub:10s} {n:5d} 个文件  {mb:7.2f} MB   "
              f"标的分布 top8: {dict(tk.most_common(8))}")

    hr("2. wb_analysis/evidence 按标的 × 日期（看每个标的被留了几套证据包）")
    ev = ROOT / "wb_analysis" / "evidence"
    groups = defaultdict(list)
    for p in sorted(ev.glob("*")) if ev.exists() else []:
        if p.is_file():
            m = re.match(r"([A-Za-z0-9.\-]+)_(\d{4}-\d{2}-\d{2})", p.name)
            if m:
                groups[(m.group(1), m.group(2))].append(p.name)
    print(f"  共 {len(groups)} 个 (标的,日期) 组合，覆盖 {len({k[0] for k in groups})} 个标的")
    for (t, d), fs in sorted(groups.items()):
        print(f"    {t:12s} {d}  {len(fs)} 个文件: {', '.join(sorted(fs))}")

    hr("3. 项目根散落文件（非目录、非 git 跟踪的产物）")
    skip = {".git", ".venv", "node_modules", ".workbuddy", ".workbuddy-ai"}
    for p in sorted(ROOT.iterdir()):
        if p.is_dir() and p.name in skip:
            continue
        if p.is_file() and p.suffix.lower() in (".csv", ".html", ".txt", ".json", ".md", ".log"):
            print(f"  {p.name:46s} {p.stat().st_size/1024:8.1f} KB  "
                  f"{datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}")
    stray = [p for p in ROOT.glob("*.py") if p.is_file()]
    print(f"  根目录 .py 脚本 {len(stray)} 个：{', '.join(sorted(p.name for p in stray))}")

    hr("4. scripts/ 目录（可复用工具 vs 一次性探针）")
    sc = ROOT / "scripts"
    for p in sorted(sc.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        has_doc = '"""' in t[:500] or "'''" in t[:500]
        print(f"  {p.name:38s} {p.stat().st_size:7d} B  文档字符串={'有' if has_doc else '★无'}")

    hr("5. 缓存与临时目录")
    for rel in ("__pycache__", "wb_analysis/__pycache__", "tradingagents/__pycache__",
                ".workbuddy-ai/backup", "wb_analysis/_backup"):
        d = ROOT / rel
        if d.exists():
            n, mb = dir_stat(d)
            print(f"  {rel:32s} {n:5d} 个文件  {mb:7.2f} MB")

    hr("6. 报告树内容缺陷信号（空小节 / RUN.json 里的说明）")
    rep = ROOT / "reports"
    for _tk, d in iter_report_trees(rep):
        empty = []
        for f in sorted(d.rglob("*.md")):
            try:
                t = f.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            if len(t) < ROLE_MIN_CHARS:
                empty.append(f"{f.relative_to(d)}:{len(t)}")
        tag = "★ 有偏短文件" if empty else "OK"
        print(f"  {d.name:34s} {tag}  {('; '.join(empty))[:70]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
