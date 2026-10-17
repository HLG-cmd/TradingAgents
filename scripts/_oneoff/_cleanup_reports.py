# lifecycle: oneoff
# created: 2026-09-23
# archived: 2026-10-10
# why: 待删清单是**硬编码的 2026-09-16/18/19 期间路径**，实测 dry-run 报「待删清单：0 个文件」
#      ⇒ 已完全跑完、无任何作用。保留作审计线索（它同时是本项目「先打包回滚包 → 逐文件删除 →
#      自深到浅 rmdir」删除范式的样板）。
#      ⚠️ 将来需要**新的**报告清理时：先用 `wb_analysis/_reports_index.py --check` 定位孤儿/重复，
#      再照本文件的打包-校验-删除流程**另写一份带清单的 oneoff**（别改本文件、别复用这份旧清单）。
# serves: 2026-09-16 ~ 09-19 期间的旧版/孤儿产物
# usage: ./.venv/Scripts/python.exe scripts/_cleanup_reports.py
"""报告/证据/草稿的「旧版与孤儿产物」清理器。

设计原则（按项目铁律）：
  1. **先算清单，再动手** —— 默认 `--dry-run`，只打印不修改；加 `--apply` 才执行。
  2. **删除前先打包回滚** —— 默认把待删集合压成一个 zip，放 `.workbuddy/backup/`，
     并在 `reports/_archive/DELETED_*.txt` 写一份逐文件清单（可审计、可还原）。
  3. **同进同出** —— 一个 run 的产物分散在 evidence / drafts / analysis / reports 四个命名空间，
     必须一起处理；只删其中一处正是「越跑越乱」的成因。
  4. **逐文件删除 + 自深到浅 rmdir** —— 不用 rmtree（本机 safe-delete 钩子会拦目录级删除）。

判定删除范围的口径（与用户确认过的范围一致）：
  A. 旧工具链批次：证据包通道总数 < 35 的「早期采集器」时期产物（9-16 批次）
  B. 通道失败的标的：000660.KS（29/32）、SPX_2026-09-18（32/35）
  C. 孤儿产物：有 evidence 或 drafts，但既无对应报告树、也无配对草稿的半途运行
  D. 修复前快照：*.pre_* 备份文件

用法:
  ./.venv/Scripts/python.exe scripts/_cleanup_reports.py                # dry-run 清单
  ./.venv/Scripts/python.exe scripts/_cleanup_reports.py --apply        # 打包 + 删除
  ./.venv/Scripts/python.exe scripts/_cleanup_reports.py --apply --no-zip
"""
import argparse
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── 待删集合（相对 ROOT 的 POSIX 路径，逐项可审计）────────────────────────
TREES = [                      # 报告树
    "reports/AMD_20260916_000947",        # A: 29/29 通道（旧采集器）
    "reports/SPX_20260918_174444",        # B: 32/35，有 3 个通道失败
    "reports/000660.KS_20260919_181122",  # B: 29/32，社交与期权通道全挂
]
DRAFT_DIRS = [                 # 草稿目录
    "wb_analysis/drafts/AMD_2026-09-16",     # A + 对应报告树已删
    "wb_analysis/drafts/GOOG_2026-09-16",    # C: 孤儿（无报告树）
    "wb_analysis/drafts/NDX_2026-09-16",     # C: 孤儿
    "wb_analysis/drafts/NDX_2026-09-16_v2",  # C: 孤儿
    "wb_analysis/drafts/NVDA_2026-09-15",    # C: 孤儿
    "wb_analysis/drafts/MU_2026-09-18",      # C: 孤儿
    "wb_analysis/drafts/000660.KS_2026-09-18",   # B
    "wb_analysis/drafts/SPX_2026-09-18",         # B
]
EVIDENCE_PREFIXES = [          # 证据包前缀（匹配 evidence/<前缀>*）
    "AMD_2026-09-16", "AMD_2026-09-17",          # A / C（09-17 无草稿无报告）
    "GOOG_2026-09-16",                            # C
    "GOOGL_2026-09-16", "GOOGL_2026-09-17",       # A / C
    "NDX_2026-09-16",                             # A
    "NVDA_2026-09-16",                            # A + C
    "SPX_2026-09-16",                             # A
    "000660.KS_2026-09-18",                       # B
    "SPX_2026-09-18",                             # B
]
ANALYSIS_STEMS = [             # analysis/<stem>.json
    "AMD_2026-09-16", "GOOG_2026-09-16", "GOOGL_2026-09-16",
    "NDX_2026-09-16", "NVDA_2026-09-16", "SPX_2026-09-16",
    "000660.KS_2026-09-18", "SPX_2026-09-18",
]
PREFIX_BACKUPS = re.compile(r"\.pre_[a-z0-9_]+\.(md|json)$", re.I)   # D


def collect() -> list[Path]:
    out: list[Path] = []
    for rel in TREES + DRAFT_DIRS:
        p = ROOT / rel
        if p.exists():
            out += [q for q in sorted(p.rglob("*")) if q.is_file()]
    ev = ROOT / "wb_analysis" / "evidence"
    for pre in EVIDENCE_PREFIXES:
        out += [p for p in sorted(ev.glob(f"{pre}*")) if p.is_file()]
    out += [p for p in sorted(ev.glob("*.pre_*")) if p.is_file() and PREFIX_BACKUPS.search(p.name)]
    an = ROOT / "wb_analysis" / "analysis"
    for s in ANALYSIS_STEMS:
        p = an / f"{s}.json"
        if p.exists():
            out.append(p)
    # 去重 + 稳定排序
    return sorted(set(out), key=lambda p: p.as_posix())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正执行（默认只打印清单）")
    ap.add_argument("--no-zip", action="store_true", help="不做回滚包（危险）")
    args = ap.parse_args()

    files = collect()
    total = sum(p.stat().st_size for p in files)
    print("=" * 100)
    print(f"待删清单：{len(files)} 个文件，{total/1024:.1f} KB")
    print("=" * 100)
    bydir: dict[str, list[Path]] = {}
    for p in files:
        key = p.relative_to(ROOT).parts[:2]
        bydir.setdefault("/".join(key), []).append(p)
    for k in sorted(bydir):
        sz = sum(q.stat().st_size for q in bydir[k]) / 1024
        print(f"\n  {k}   （{len(bydir[k])} 文件，{sz:.1f} KB）")
        for q in bydir[k][:60]:
            print(f"      {q.relative_to(ROOT).as_posix()}")
        if len(bydir[k]) > 60:
            print(f"      …（略 {len(bydir[k])-60} 个）")

    if not args.apply:
        print("\n[DRY-RUN] 未修改任何文件。加 --apply 执行。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    expected = {p.relative_to(ROOT).as_posix() for p in files}
    zip_path = None
    if not args.no_zip:
        zp = ROOT / ".workbuddy" / "backup" / f"deleted_{stamp}_reports_cleanup.zip"
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in files:
                if p.exists():
                    z.write(p, p.relative_to(ROOT).as_posix())
        zip_path = zp
        # ★ 关键护栏（2026-09-23 补）：**打包结果必须与清单逐项一致，否则中止删除**。
        #   起因：一次实际运行里 `zip` 只写进了 134/183 条，而删除却照常执行 ⇒
        #   回滚包**静默地不完整**。这类「备份看着有、其实是残的」比没有备份更危险，
        #   因为它会在真正需要回滚时才暴露。故此处**先验证再删**，不允许「尽力而为」。
        with zipfile.ZipFile(zp) as z:
            got = set(z.namelist())
        missing = sorted(expected - got)
        extra = sorted(got - expected)
        print(f"\n[回滚包] {zp.relative_to(ROOT).as_posix()}  "
              f"{zp.stat().st_size/1024:.1f} KB  条目 {len(got)}/{len(expected)}")
        if missing or extra:
            print(f"  ✗ 回滚包与清单不一致：缺 {len(missing)} 条、多 {len(extra)} 条")
            for m in missing[:20]:
                print(f"      缺: {m}")
            for m in extra[:20]:
                print(f"      多: {m}")
            print("  ⇒ 已**中止删除**（不允许在备份不完整的情况下执行不可逆操作）。")
            print("     请检查磁盘空间/文件占用后重试；或显式加 --no-zip 自行承担风险。")
            return 2
        print("  ✓ 内容校验通过（逐项一致），继续执行删除")

    # 逐文件删除，再自深到浅清空壳目录
    removed = failed = 0
    for p in files:
        try:
            p.unlink()
            removed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ✗ 删除失败 {p.relative_to(ROOT).as_posix()}: {exc!r}")
    dirs = sorted({p for rel in TREES + DRAFT_DIRS for p in (ROOT / rel).rglob("*") if p.is_dir()},
                  key=lambda d: len(d.parts), reverse=True)
    for d in dirs:
        try:
            d.rmdir()
        except OSError:
            pass
    for rel in TREES + DRAFT_DIRS:
        try:
            (ROOT / rel).rmdir()
        except OSError:
            pass

    man = ROOT / "reports" / "_archive" / f"DELETED_{stamp}.txt"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(
        f"# 2026-09-22 报告清理：删除清单\n"
        f"# 回滚包：{(zip_path.relative_to(ROOT).as_posix() if zip_path else '（未生成）')}\n"
        f"# 删除文件数：{removed}（失败 {failed}）\n\n"
        + "\n".join(p.relative_to(ROOT).as_posix() for p in files) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"\n[清单] {man.relative_to(ROOT).as_posix()}")
    print(f"[结果] 删除 {removed} 个文件，失败 {failed} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
