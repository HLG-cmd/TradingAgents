# lifecycle: oneoff
# created: 2026-09-23
# archived: 2026-10-10
# why: 迁移已完成 —— `wb_analysis/_reports_index.py --check` 实测「报告树 34 棵；卫生问题 0 项」，
#      即**每一棵树都已有 `RUN.json`**（本文件 docstring 自述就是"一次性迁移"）。
# serves: 2026-09 迁入新布局之前的旧报告树
# usage: ./.venv/Scripts/python.exe scripts/_backfill_run_json.py
"""为**已存在的旧报告树**补写 `RUN.json`（一次性迁移）。

为什么需要：RUN.json 是今天才加的机制，此前的报告树没有它，索引只能靠「目录名里的运行时刻」
去猜关联关系，于是把同一标的的正常产物误报成「缺草稿 / 孤儿」。本脚本按下面的规则回填：

  数据基准日 = 同标的的草稿目录中，`0_brief.md` 修改时间**不晚于**报告树修改时间、且**最接近**的那一个，
              取其目录名里的日期；找不到则退回报告树目录名里的日期并标记 `inferred: false`。
  来源草稿   = 上述草稿目录的绝对路径（找不到则留空）。
  证据文件   = `wb_analysis/evidence/` 下同标的、mtime 不晚于报告树的前缀匹配文件。

用法: ./.venv/Scripts/python.exe scripts/_backfill_run_json.py [--apply]
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DRAFTS = ROOT / "wb_analysis" / "drafts"
EVID = ROOT / "wb_analysis" / "evidence"
ANALYSIS = ROOT / "wb_analysis" / "analysis"
SKIP = {"_datasets", "_other", "_archive", "_audit"}
APPLY = "--apply" in sys.argv


def tree_anchor(tr: Path) -> float:
    """报告树的时间锚点。

    ⚠️ 不能用 `tr.stat().st_mtime`：**目录 mtime 会在「往目录里写文件」时被刷新**，
    而本次重排是「逐文件复制」实现的，于是所有报告树的目录 mtime 都变成了复制时刻，
    关联推断会把老报告错配到最新的草稿目录（实测 GOOG_20260918 被错配到 2026-09-21 的草稿）。
    `shutil.copy2` 会**保留文件 mtime**，故改用树内最早生成的那个文件的 mtime 作锚点。
    """
    cand = tr / "complete_report.md"
    if cand.exists():
        return cand.stat().st_mtime
    files = [p for p in tr.rglob("*") if p.is_file()]
    return min(p.stat().st_mtime for p in files) if files else tr.stat().st_mtime


def infer_drafts(ticker: str, tree_mtime: float) -> tuple[Path | None, str]:
    best, best_dt = None, None
    for d in sorted(DRAFTS.iterdir()) if DRAFTS.exists() else []:
        if not d.is_dir() or not d.name.startswith(ticker + "_"):
            continue
        brief = d / "0_brief.md"
        t = (brief if brief.exists() else d).stat().st_mtime
        if t <= tree_mtime + 5:
            if best is None or t > best_dt:
                best, best_dt = d, t
    date = ""
    if best:
        parts = best.name.split("_", 1)
        if len(parts) == 2:
            date = parts[1]
    return best, date


def main() -> int:
    n_done = n_skip = 0
    for tk in sorted([d for d in REPORTS.iterdir() if d.is_dir() and d.name not in SKIP]):
        for tr in sorted([x for x in tk.iterdir() if x.is_dir()]):
            if (tr / "RUN.json").exists():
                n_skip += 1
                continue
            mt = tree_anchor(tr)
            drafts, date = infer_drafts(tk.name, mt)
            if not date:
                m = tr.name.rsplit("_", 2)
                date = f"{m[-2][:4]}-{m[-2][4:6]}-{m[-2][6:]}" if len(m) >= 2 else ""
            run = {
                "ticker": tk.name,
                "stamp": tr.name.rsplit("_", 2)[-2] + "_" + tr.name.rsplit("_", 1)[-1],
                "data_date": date,
                "rendered_at": datetime.fromtimestamp(mt).isoformat(timespec="seconds"),
                "source_drafts": str(drafts) if drafts else "",
                "evidence": sorted(
                    p.name for p in EVID.glob(f"{tk.name}_*")
                    if p.is_file() and p.stat().st_mtime <= mt + 5
                ),
                "ratings": {},
                "role_files": len([p for p in tr.rglob("*.md") if p.is_file()]),
                "layout": "nested",
                "backfilled": True,
                "inferred": bool(drafts),
            }
            mark = "推测" if not drafts else "匹配到草稿"
            print(f"  {tk.name:8s} {tr.name:26s} 基准日={date or '?':10s} 草稿={'有' if drafts else '无'}  ({mark})")
            if APPLY:
                (tr / "RUN.json").write_text(
                    json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
                )
            n_done += 1
    print(f"\n{'[已写入]' if APPLY else '[DRY-RUN]'} 需回填 {n_done} 棵，已有清单 {n_skip} 棵")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
