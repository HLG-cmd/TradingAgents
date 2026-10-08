# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_seal_run.py
"""把「一次运行的中间产物」封存进该次报告树，随后删除散落在项目里的副本。

## 用户诉求
「整个流程跑下来，只留下来最终的报告就行了」——但中间产物（证据包 / 草稿 / 分析 JSON / 一次性探针）
**不能真的消失**：报告里每一个数字都靠证据包溯源，删了就无法验证、无法重渲染、无法复盘。
⇒ 正解不是「删掉」，而是「**收起来**」：一轮产物 = 1 份报告树 + 树内 1 个 `_source.zip`（审计包）。

## 封存后各目录的语义
  `reports/<T>/<T>_<stamp>/`    ← 人看的最终报告（+ 树内 `_source.zip` 审计包 + `SOURCE_MANIFEST.json`）
  `wb_analysis/evidence/`       ← **瞬态**：只放「还没封存」的那一轮
  `wb_analysis/drafts/`         ← 同上
  `wb_analysis/analysis/`       ← 同上
  `scripts/_oneoff/`            ← 只放「还没归档」的一次性探针；`# serves:` 命中哪一轮就随哪一轮进包

## 安全护栏（沿用项目铁律）
  · **先打包 → 逐项校验压缩包内容 → 校验通过才删**；不一致直接中止
  · 默认 `--dry-run`，加 `--apply` 才动手
  · `--orphans` 模式：删掉**没有任何报告树**的孤儿产物（同样先打包）

## 用法
  ./.venv/Scripts/python.exe wb_analysis/_seal_run.py --plan                    # 全项目盘点
  ./.venv/Scripts/python.exe wb_analysis/_seal_run.py --run NFLX 2026-09-21 --apply
  ./.venv/Scripts/python.exe wb_analysis/_seal_run.py --all --apply             # 把所有已交付的轮次封存
  ./.venv/Scripts/python.exe wb_analysis/_seal_run.py --orphans --apply         # 清理孤儿产物
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
EVID = ROOT / "wb_analysis" / "evidence"
DRAFTS = ROOT / "wb_analysis" / "drafts"
ANALYSIS = ROOT / "wb_analysis" / "analysis"
ONEOFF = ROOT / "scripts" / "_oneoff"
SKIP_DIRS = {"_datasets", "_other", "_archive", "_audit"}


def runs_in_reports() -> dict[tuple[str, str], list[Path]]:
    """扫描报告树，按 (标的, 数据基准日) 归类；优先读 RUN.json 的 data_date。"""
    out: dict[tuple[str, str], list[Path]] = {}
    if not REPORTS.exists():
        return out
    for tk in sorted(d for d in REPORTS.iterdir() if d.is_dir() and d.name not in SKIP_DIRS):
        for tr in sorted(x for x in tk.iterdir() if x.is_dir()):
            rj = tr / "RUN.json"
            date = None
            if rj.exists():
                try:
                    date = json.loads(rj.read_text(encoding="utf-8")).get("data_date") or None
                except Exception:  # noqa: BLE001
                    date = None
            if not date:
                m = re.match(r".*_(\d{4})(\d{2})(\d{2})_\d{6}$", tr.name)
                if m:
                    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            if date:
                out.setdefault((tk.name, date), []).append(tr)
    return out


def artifacts_for(ticker: str, date: str) -> dict[str, list[Path]]:
    ev = sorted(p for p in EVID.glob(f"{ticker}_{date}*") if p.is_file()) if EVID.exists() else []
    dr = sorted(p for p in (DRAFTS / f"{ticker}_{date}").rglob("*") if p.is_file()) \
        if (DRAFTS / f"{ticker}_{date}").exists() else []
    an = [ANALYSIS / f"{ticker}_{date}.json"] if (ANALYSIS / f"{ticker}_{date}.json").exists() else []
    one = []
    if ONEOFF.exists():
        for p in sorted(ONEOFF.glob("*.py")):
            head = p.read_text(encoding="utf-8", errors="replace")[:2000]
            m = re.search(r"^#\s*serves:\s*(.+)$", head, re.M)
            if m and ticker in m.group(1) and date in m.group(1).replace(".", "-"):
                one.append(p)
    return {"evidence": ev, "drafts": dr, "analysis": an, "oneoff": one}


# ★ 静默期：封存前要求 drafts 目录已"安静"这么久（秒）。
#   2026-09-23 实测事故：封存时**激进风险分析师仍在运行**（已跑 11m34s），
#   我在"看到 3 个 4_risk 文件存在"就判定三位风险席都完成了 —— **文件存在 ≠ 智能体结束**。
#   结果：drafts 在其写入前被清空，它的报告在封存后才落盘 ⇒ 交付树与审计包不一致，
#   事后不得不重建审计包并保留三个版本。⇒ 用**静默期**从机制上防止再发生。
QUIET_SECONDS = 180


def _quiet_check(draft_dir: Path) -> float:
    """返回 (现在 − 该目录内最新 mtime) 的秒数；目录不存在返回一个很大的数。"""
    if not draft_dir.exists():
        return 1e9
    fs = [p for p in draft_dir.rglob("*") if p.is_file()]
    if not fs:
        return 1e9
    import time
    return time.time() - max(p.stat().st_mtime for p in fs)


def seal(ticker: str, date: str, tree: Path, apply: bool, force: bool = False) -> int:
    d = DRAFTS / f"{ticker}_{date}"
    q = _quiet_check(d)
    if apply and q < QUIET_SECONDS and not force:
        print(f"  ✗ 拒绝封存：{d.relative_to(ROOT).as_posix()} 最近 {q:.0f} 秒内仍有写入 "
              f"（静默期要求 {QUIET_SECONDS} 秒）")
        print("     ⇒ 极可能有子智能体仍在运行。请等它结束，或加 --force 明确承担风险。")
        print("     （事故记录：2026-09-23 因过早封存导致交付树与审计包不一致）")
        return 3
    groups = artifacts_for(ticker, date)
    total = sum(len(v) for v in groups.values())
    if total == 0:
        print(f"  - {ticker} {date}：工作目录已无产物（可能已封存过）")
        return 0
    if (tree / "_source.zip").exists():
        # ★ 已封存 ≠ 无事可做。首版这里是「直接跳过」，结果**首次执行被中断时残留的散文件永远清不掉**
        #   （实测 GOOG_2026-09-17 的 drafts/ 与 analysis/ 就因此留了下来）。
        #   ⇒ 改为**幂等补完**：逐个检查当前散文件是否已在包内，在则删掉散件；不在则报告（不覆盖审计包）。
        with zipfile.ZipFile(tree / "_source.zip") as z:
            have = set(z.namelist())
        done = leftover = 0
        uncovered = []
        for kind, files in groups.items():
            for f in files:
                if kind == "evidence":
                    arc = f"evidence/{f.name}"
                elif kind == "analysis":
                    arc = f"analysis/{f.name}"
                elif kind == "oneoff":
                    arc = f"oneoff/{f.name}"
                else:
                    arc = f"drafts/{f.relative_to(DRAFTS).as_posix()}"
                if arc in have:
                    if apply:
                        try:
                            f.unlink()
                            done += 1
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        done += 1
                else:
                    leftover += 1
                    uncovered.append(arc)
        msg = f"  - {ticker} {date}：已有审计包；散文件已在包内 {done} 个" + (
            f"，**未覆盖 {leftover} 个**" if leftover else "")
        print(msg)
        for u in uncovered[:8]:
            print(f"        未覆盖: {u}")
        if leftover == 0 and apply:
            for d in [DRAFTS / f"{ticker}_{date}"]:
                if d.exists():
                    for sub in sorted([x for x in d.rglob("*") if x.is_dir()],
                                      key=lambda x: len(x.parts), reverse=True):
                        try:
                            sub.rmdir()
                        except OSError:
                            pass
                    try:
                        d.rmdir()
                    except OSError:
                        pass
        return 0 if leftover == 0 else 1

    print(f"  ● {ticker} {date} → {tree.relative_to(ROOT).as_posix()}")
    for k, v in groups.items():
        if v:
            print(f"      {k}: {len(v)} 个")
    if not apply:
        return total

    zp = tree / "_source.zip"
    expected: dict[str, Path] = {}
    for kind, files in groups.items():
        for f in files:
            if kind == "evidence":
                arc = f"evidence/{f.name}"
            elif kind == "analysis":
                arc = f"analysis/{f.name}"
            elif kind == "oneoff":
                arc = f"oneoff/{f.name}"
            else:
                arc = f"drafts/{f.relative_to(DRAFTS).as_posix()}"
            expected[arc] = f

    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, f in sorted(expected.items()):
            z.write(f, arc)
        z.writestr("SEAL.json", json.dumps({
            "ticker": ticker, "data_date": date, "sealed_at": datetime.now().isoformat(timespec="seconds"),
            "report_tree": tree.name, "n_entries": len(expected),
        }, ensure_ascii=False, indent=2) + "\n")

    with zipfile.ZipFile(zp) as z:
        got = set(z.namelist())
    missing = sorted(set(expected) - got)
    if missing:
        print(f"      ✗ 压缩包校验失败：缺 {len(missing)} 项，**中止删除**")
        for m in missing[:10]:
            print(f"         缺: {m}")
        zp.unlink(missing_ok=True)
        return 1

    sha = hashlib.sha256(zp.read_bytes()).hexdigest()
    (tree / "SOURCE_MANIFEST.json").write_text(json.dumps({
        "ticker": ticker, "data_date": date,
        "archive": "_source.zip", "n_entries": len(got),
        "bytes": zp.stat().st_size, "sha256": sha,
        "contents": sorted(got),
        "note": "本文件说明 _source.zip 里有什么。报告里的每个数字都可在包内证据包里溯源；"
                "需要重新渲染时，把 drafts/ 解出来即可。",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    removed = 0
    for f in expected.values():
        try:
            f.unlink()
            removed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"      ✗ 删除失败 {f.name}: {exc!r}")
    for d in sorted([p for p in DRAFTS.glob(f"{ticker}_{date}") if p.is_dir()], key=lambda x: len(x.parts), reverse=True):
        for sub in sorted([x for x in d.rglob("*") if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
            try:
                sub.rmdir()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass
    print(f"      ✓ 已封存 {len(got)} 项（{zp.stat().st_size/1024:.0f} KB，sha256 {sha[:12]}…），删除散文件 {removed} 个")
    return 0


def orphans(apply: bool) -> int:
    """工作目录里没有任何报告树的产物。"""
    known = set(runs_in_reports())
    found: list[tuple[str, str, dict]] = []
    if EVID.exists():
        for p in sorted(EVID.glob("*.md")):
            if "derived" in p.name or "supplement" in p.name or ".pre_" in p.name:
                continue
            m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})\.md$", p.name)
            if m and (m.group(1), m.group(2)) not in known:
                found.append((m.group(1), m.group(2), artifacts_for(m.group(1), m.group(2))))
    if DRAFTS.exists():
        for d in sorted(x for x in DRAFTS.iterdir() if x.is_dir()):
            m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})$", d.name)
            if m and (m.group(1), m.group(2)) not in known:
                if not any(k == m.group(1) and v == m.group(2) for k, v, _ in found):
                    found.append((m.group(1), m.group(2), artifacts_for(m.group(1), m.group(2))))
    if ANALYSIS.exists():
        for p in sorted(ANALYSIS.glob("*.json")):
            m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})\.json$", p.name)
            if m and (m.group(1), m.group(2)) not in known:
                if not any(k == m.group(1) and v == m.group(2) for k, v, _ in found):
                    found.append((m.group(1), m.group(2), artifacts_for(m.group(1), m.group(2))))
    if ANALYSIS.exists():
        for p in sorted(ANALYSIS.glob("*.json")):
            m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})\.json$", p.name)
            if m and (m.group(1), m.group(2)) not in known:
                if not any(k == m.group(1) and v == m.group(2) for k, v, _ in found):
                    found.append((m.group(1), m.group(2), artifacts_for(m.group(1), m.group(2))))
    if not found:
        print("  ✓ 无孤儿产物")
        return 0
    zp = ROOT / ".workbuddy" / "backup" / f"orphans_{datetime.now():%Y%m%d_%H%M%S}.zip"
    print(f"  发现 {len(found)} 组孤儿产物（无对应报告树）：")
    allf: dict[str, Path] = {}
    for tk, dt, groups in found:
        n = sum(len(v) for v in groups.values())
        print(f"      {tk} {dt}：{n} 个文件")
        for kind, files in groups.items():
            for f in files:
                arc = f"{kind}/{f.relative_to(ROOT).as_posix()}"
                allf[arc] = f
    if not apply:
        print("\n  [DRY-RUN] 未删除。")
        return 0
    zp.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, f in sorted(allf.items()):
            z.write(f, arc)
    with zipfile.ZipFile(zp) as z:
        got = set(z.namelist())
    if got != set(allf):
        print(f"  ✗ 回滚包校验失败（缺 {len(set(allf)-got)} 项），**中止删除**")
        return 1
    n = 0
    for f in allf.values():
        try:
            f.unlink()
            n += 1
        except Exception:  # noqa: BLE001
            pass
    for tk, dt, _ in found:
        d = DRAFTS / f"{tk}_{dt}"
        if d.exists():
            for sub in sorted([x for x in d.rglob("*") if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
                try:
                    sub.rmdir()
                except OSError:
                    pass
            try:
                d.rmdir()
            except OSError:
                pass
    print(f"  ✓ 已删除 {n} 个孤儿文件；回滚包 {zp.relative_to(ROOT).as_posix()}")
    return 0


def unseal(ticker: str, date: str, apply: bool) -> int:
    """把 `_source.zip` 解回工作目录（需要重渲染或重新跑门禁时用）。"""
    trees = runs_in_reports().get((ticker, date), [])
    if not trees:
        print(f"✗ 找不到 {ticker} {date} 的报告树")
        return 1
    zp = max(trees) / "_source.zip"
    if not zp.exists():
        print(f"✗ {zp.relative_to(ROOT).as_posix()} 不存在")
        return 1
    with zipfile.ZipFile(zp) as z:
        names = [n for n in z.namelist() if n != "SEAL.json"]
    print(f"  从 {zp.relative_to(ROOT).as_posix()} 解出 {len(names)} 项 → evidence/ drafts/ analysis/（oneoff 解到 scripts/_oneoff/）")
    if not apply:
        return 0
    for n in names:
        if n.startswith("evidence/"):
            dst = EVID / Path(n).name
        elif n.startswith("analysis/"):
            dst = ANALYSIS / Path(n).name
        elif n.startswith("oneoff/"):
            dst = ONEOFF / Path(n).name
        elif n.startswith("drafts/"):
            dst = DRAFTS / n[len("drafts/"):]
        else:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp) as z:
            dst.write_bytes(z.read(n))
    print("  ✓ 已还原")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs=2, metavar=("TICKER", "DATE"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--orphans", action="store_true")
    ap.add_argument("--unseal", nargs=2, metavar=("TICKER", "DATE"))
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--force", action="store_true", help="跳过静默期检查（明确承担并发写入风险）")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print("=" * 96)
    print("一次运行的**产物封存**：报告树 + 树内 _source.zip（审计包），工作目录转为瞬态")
    print("=" * 96)

    if args.unseal:
        return unseal(args.unseal[0], args.unseal[1], args.apply)

    if args.orphans:
        return orphans(args.apply)

    if args.run:
        tk, dt = args.run
        trees = runs_in_reports().get((tk, dt), [])
        if not trees:
            print(f"✗ 找不到 {tk} {dt} 的报告树")
            return 1
        return seal(tk, dt, max(trees), args.apply, args.force)

    runs = runs_in_reports()
    if not runs:
        print("（没有已交付的报告树）")
        return 0
    print(f"\n共 {len(runs)} 轮已交付：\n")
    print(f"  {'标的':8s} {'数据基准日':12s} {'报告树':28s} 待封存产物")
    print("  " + "-" * 84)
    todo = 0
    for (tk, dt), trees in sorted(runs.items()):
        g = artifacts_for(tk, dt)
        n = sum(len(v) for v in g.values())
        sealed = (max(trees) / "_source.zip").exists()
        mark = "已封存" if sealed else (f"{n} 个待封存" if n else "无散文件")
        if not sealed and n:
            todo += 1
        print(f"  {tk:8s} {dt:12s} {max(trees).name:28s} {mark}")
    print(f"\n  待封存 {todo} 轮。加 --apply 执行（先打包并逐项校验，通过才删）。")
    if args.all and args.apply:
        rc = 0
        for (tk, dt), trees in sorted(runs.items()):
            rc |= seal(tk, dt, max(trees), True, args.force)
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
