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
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from wb_analysis._contract import is_non_tree_artifact  # noqa: E402
# ★ 2026-10-10：功能目录集原为本地字面量（与 `_reports_index` / `_scorecard` 逐字重复）
#   ⇒ 单一来源 `wb_analysis/_paths.py`。
from wb_analysis._paths import FUNC_DIRS, TREE_RE  # noqa: E402
from wb_analysis import _clock

REPORTS = ROOT / "reports"
EVID = ROOT / "wb_analysis" / "evidence"
DRAFTS = ROOT / "wb_analysis" / "drafts"
ANALYSIS = ROOT / "wb_analysis" / "analysis"
ONEOFF = ROOT / "scripts" / "_oneoff"
SKIP_DIRS = FUNC_DIRS
BACKUP_DIR = Path(tempfile.gettempdir()) / "tradingagents_backup"


def _oneoff_dirs() -> list[Path]:
    """返回需要扫描的一次性探针目录（兼容单测只替换 `ONEOFF` 的情形）。"""
    wb_oneoff = EVID.parent / "_oneoff"
    out = [ONEOFF]
    if wb_oneoff != ONEOFF and wb_oneoff.exists():
        out.append(wb_oneoff)
    return out


def runs_in_reports() -> dict[tuple[str, str], list[Path]]:
    """扫描报告树，按 (标的, 数据基准日) 归类；优先读 RUN.json 的 data_date。"""
    out: dict[tuple[str, str], list[Path]] = {}
    if not REPORTS.exists():
        return out
    for tk in sorted(d for d in REPORTS.iterdir() if d.is_dir() and d.name not in SKIP_DIRS):
        for tr in sorted(x for x in tk.iterdir() if x.is_dir() and TREE_RE.match(x.name)):
            rj = tr / "RUN.json"
            date = None
            if rj.exists():
                try:
                    date = json.loads(rj.read_text(encoding="utf-8")).get("data_date") or None
                except Exception:  # noqa: BLE001
                    date = None
            if not date:
                m = TREE_RE.match(tr.name)
                if m:
                    ymd = m.group(2)
                    date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
            if date:
                out.setdefault((tk.name, date), []).append(tr)
    return out


def artifacts_for(ticker: str, date: str) -> dict[str, list[Path]]:
    ev = sorted(p for p in EVID.glob(f"{ticker}_{date}*") if p.is_file()) if EVID.exists() else []
    dr = sorted(p for p in (DRAFTS / f"{ticker}_{date}").rglob("*") if p.is_file()) \
        if (DRAFTS / f"{ticker}_{date}").exists() else []
    an = [ANALYSIS / f"{ticker}_{date}.json"] if (ANALYSIS / f"{ticker}_{date}.json").exists() else []
    one = []
    for od in _oneoff_dirs():
        if not od.exists():
            continue
        for p in sorted(od.glob("*.py")):
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


def _arcname(kind: str, f: Path) -> str:
    """散件 → 审计包内的归档名（**唯一定义源**）。

    ★ 2026-10-12：原实现在**三处**各写了一遍同样的 if/elif 链（本函数内的补完分支、
    重建分支、以及 `--plan` 的预演），改一处必漏两处 ⇒ 收敛到此。
    """
    if kind == "evidence":
        return f"evidence/{f.name}"
    if kind == "analysis":
        return f"analysis/{f.name}"
    if kind == "oneoff":
        return f"oneoff/{f.name}"
    return f"drafts/{f.relative_to(DRAFTS).as_posix()}"


def _refresh_scorecard() -> None:
    """封存后刷新 `reports/QUALITY.csv`。

    ★ 2026-10-19 实测：两轮新树封存后都没进 QUALITY.csv，只有手工跑 `_scorecard.py`
      才补上 —— 记分卡永远落后一轮，等于「质量趋势」这项长期指标是断的。
      放在封存末尾（而非门禁里），因为它写报告目录、属维护动作，不是判据。
    """
    sc = ROOT / "wb_analysis" / "_scorecard.py"
    if not sc.exists():
        return
    try:
        p = subprocess.run([sys.executable, str(sc)], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0:
            print("      ↻ 已刷新 reports/QUALITY.csv（_scorecard.py）")
        else:
            print(f"      ⚠ 记分卡刷新失败（rc={p.returncode}）："
                  f"{(p.stdout or p.stderr or '').strip()[:80]}")
    except Exception as e:  # noqa: BLE001
        print(f"      ⚠ 记分卡刷新异常：{type(e).__name__}")


def seal(ticker: str, date: str, tree: Path, apply: bool, force: bool = False,
         rebuild: bool = False) -> int:
    d = DRAFTS / f"{ticker}_{date}"
    q = _quiet_check(d)
    if apply and q < QUIET_SECONDS and not force:
        print(f"  ✗ 拒绝封存：{d.relative_to(ROOT).as_posix()} 最近 {q:.0f} 秒内仍有写入 "
              f"（静默期要求 {QUIET_SECONDS} 秒）")
        print("     ⇒ 两种情况：① 子智能体仍在写；② 你自己刚做完最后一次编辑（最常见）。")
        print("       等静默期满再跑；确认无并发写入可加 --force 明确承担风险。")
        print("     （事故记录：2026-09-23 因过早封存导致交付树与审计包不一致）")
        return 3
    groups = artifacts_for(ticker, date)
    total = sum(len(v) for v in groups.values())
    if total == 0:
        print(f"  - {ticker} {date}：工作目录已无产物（可能已封存过）")
        return 0
    if (tree / "_source.zip").exists() and not rebuild:
        # ★ 已封存 ≠ 无事可做。首版这里是「直接跳过」，结果**首次执行被中断时残留的散文件永远清不掉**
        #   （实测 GOOG_2026-09-17 的 drafts/ 与 analysis/ 就因此留了下来）。
        #   ⇒ 改为**幂等补完**：逐个检查当前散文件是否已在包内，在则删掉散件；不在则报告（不覆盖审计包）。
        # ★★ 2026-10-12 修（血泪，本工具最危险的一处）：
        #   原实现**只按文件名**判断「散件是否已在包内」，于是**内容变了也认不出** ⇒
        #   重跑（重采 → 重渲染 → 再封存）时它会把**新**散件当作「已在包内」**直接删掉**、
        #   把**旧**包原样留着，并返回 0（看起来成功）。
        #   净效果 = **交付树与审计包静默不一致**，且**新版工作文件被销毁**。
        #   实测 2026-10-12 GOOG 轮：重采+重渲染后用 `--apply`，新版简报 / 市场分析 /
        #   派生指标 / 新证据包被删除，树内 `_source.zip` 仍是 02:39 的旧版，
        #   而 `complete_report.md` 已是 03:04 的新版 —— 正是本文件上面那句拒绝信息里
        #   记的那起事故（「交付树与审计包不一致」），被幂等逻辑重新引入了。
        #   ⇒ 判据必须落到**内容**上：大小 + sha256 **都相同**才可删散件；
        #     任一不同 ⇒ 报「审计包已过期」并返回 1（**不删任何东西**），
        #     要重建请显式加 `--rebuild`（会先把旧包备份到系统临时目录）。
        with zipfile.ZipFile(tree / "_source.zip") as z:
            pack = {i.filename: i.file_size for i in z.infolist()}
            pack_sha = {n: hashlib.sha256(z.read(n)).hexdigest() for n in pack}
        same = changed = uncovered = 0
        modified, missing = [], []
        same_files: list[Path] = []   # ★ 2026-10-16：待删的"逐字节一致"散件（判断阶段只收集，不删）
        for kind, files in groups.items():
            for f in files:
                arc = _arcname(kind, f)
                if arc not in pack:
                    uncovered += 1
                    missing.append(arc)
                    continue
                try:
                    b = f.read_bytes()
                except OSError:
                    continue
                if pack[arc] == len(b) and pack_sha[arc] == hashlib.sha256(b).hexdigest():
                    # ★★ 2026-10-16 修（**真根因**，比"丢件"本身更重要）：
                    #   原实现**在判断阶段就 `f.unlink()`**，即「比对函数带副作用」。
                    #   后果：当一批散件"部分相同、部分不同"时，相同的**已被当场删掉**，
                    #   随后 changed>0 走「审计包已过期」分支 → 保留剩下的并 return 1；
                    #   调用者按提示加 `--rebuild` 重跑时，`artifacts_for()` 只能看到
                    #   **尚未被删的那些** ⇒ 期望集变小 ⇒ 新包丢件（实测 19→13 项）。
                    #   ⇒ 判据阶段**只标记、不删除**；删除一律推迟到"确认全同"之后。
                    same += 1
                    same_files.append(f)
                else:
                    changed += 1
                    modified.append(arc)
        # 全同 ⇒ 散件是包内的冗余副本，可安全清掉（原「幂等补完」的正当用途）
        if changed == 0 and uncovered == 0:
            print(f"  - {ticker} {date}：已有审计包，{same} 个散件与包内**逐字节一致** ⇒ 已清理冗余散件")
            if apply:
                # ★ 2026-10-16：删除推迟到这里 —— 只有确认"全同"（changed==0 且 uncovered==0）
                #   才清理冗余散件。部分相同时**一件都不删**，保证 --rebuild 能看到完整源。
                for _f in same_files:
                    try:
                        _f.unlink()
                    except OSError:
                        pass
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
            return 0
        # ★ 2026-10-15 新增：若包内原有证据/草稿分毫无变（changed == 0），且未覆盖项**全部**是
        #   事后归位到 `_oneoff/` 的探针（`oneoff/*`），则在 `--apply` 下安全增量并入 `_source.zip`
        #   （先备份旧包、重写并逐项校验，通过再删散件），解决事后打 `# serves:` 标签导致的「待封存死锁」。
        if changed == 0 and uncovered > 0 and all(m.startswith("oneoff/") for m in missing):
            missing_files = [(_arcname("oneoff", f), f) for f in groups.get("oneoff", [])
                             if _arcname("oneoff", f) in missing]
            if not apply:
                print(f"  ● {ticker} {date}：已有审计包，待增量并入 {uncovered} 个事后归位的 oneoff 探针")
                return uncovered
            zp = tree / "_source.zip"
            bdir = BACKUP_DIR
            bdir.mkdir(parents=True, exist_ok=True)
            bak = bdir / f"source_{ticker}_{date}_{_clock.now():%Y%m%d_%H%M%S}.zip"
            import shutil as _sh
            _sh.copy2(zp, bak)
            with zipfile.ZipFile(zp, "r") as zin:
                old_entries = {n: zin.read(n) for n in zin.namelist() if n != "SEAL.json"}
            for arc, f in missing_files:
                old_entries[arc] = f.read_bytes()
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zout:
                for arc in sorted(old_entries):
                    zout.writestr(arc, old_entries[arc])
                # ★ 2026-10-16 修（全库 51/52 命中）：`n_entries` 必须**含 SEAL.json 自身**，
                #   否则与 SOURCE_MANIFEST（用 len(z.namelist())）口径不一致、恒少 1。
                zout.writestr("SEAL.json", json.dumps({
                    "ticker": ticker, "data_date": date,
                    "sealed_at": _clock.now().isoformat(timespec="seconds"),
                    "report_tree": tree.name, "n_entries": len(old_entries) + 1,
                }, ensure_ascii=False, indent=2) + "\n")
            with zipfile.ZipFile(zp) as zchk:
                got = set(zchk.namelist())
            if not (set(old_entries) <= got):
                _sh.copy2(bak, zp)
                print(f"      ✗ 增量并入校验失败，已恢复备份 {bak.name}")
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
            for _arc, f in missing_files:
                try:
                    f.unlink()
                except OSError:
                    pass
            print(f"      ✓ 已增量并入 {len(missing_files)} 个 oneoff 探针并更新 SOURCE_MANIFEST.json")
            return 0
        print(f"  ✗ {ticker} {date}：**审计包已过期**（{changed} 个同名但内容不同，"
              f"{uncovered} 个未覆盖）—— 已**保留全部散件**，未删任何文件")
        for u in (modified + missing)[:8]:
            print(f"        {'[内容已变]' if u in modified else '[包内缺失]'} {u}")
        print("     ⇒ 交付树（新）与审计包（旧）不一致。要重建审计包请加 `--rebuild`"
              "（旧包会先备份到系统临时目录）。")
        return 1

    if (tree / "_source.zip").exists():
        # ★ 2026-10-12：`--rebuild` 走到这里 ⇒ 先把**旧包备份**再覆盖。
        #   备份的理由与「先打包再删」同源：重建会覆盖唯一的审计包，
        #   而旧包记录的是**上一版交付**（当初可能已对外发布）⇒ 必须可回溯。
        old = tree / "_source.zip"
        bdir = BACKUP_DIR
        bdir.mkdir(parents=True, exist_ok=True)
        bak = bdir / f"source_{ticker}_{date}_{_clock.now():%Y%m%d_%H%M%S}.zip"
        if apply:
            import shutil as _sh
            _sh.copy2(old, bak)
            print(f"  ↺ 已备份旧审计包 → {bak.as_posix()}"
                  f"（{bak.stat().st_size / 1024:.0f} KB）")

    print(f"  ● {ticker} {date} → {tree.relative_to(ROOT).as_posix()}")
    for k, v in groups.items():
        if v:
            print(f"      {k}: {len(v)} 个")
    if not apply:
        return total

    zp = tree / "_source.zip"
    expected: dict[str, Path] = {_arcname(kind, f): f
                                 for kind, files in groups.items() for f in files}

    # ★★ 2026-10-16 修（本轮实测的丢件 bug）：重建时**不能只写当前 expected**。
    #   实测 563020 本轮 `--rebuild` 后包内只剩 13 项（正常 19 项），
    #   丢掉了 evidence 3 件 + 0_derived + fundamentals + meta.json ——
    #   而审计包的承诺是「报告里每个数字都能在包内溯源」，丢了证据包等于**最底层依据消失**，
    #   且外观完全正常（包能打开、校验也"通过"）。
    #   ⇒ 护栏：把**旧包已有、而本次 expected 未覆盖**的条目原样补入 ⇒ 保证 `新包 ⊇ 旧包`。
    #     只在 `--rebuild` 且有旧包时生效；补入项会显式打印，便于人工判断是否为残留。
    carried: dict[str, bytes] = {}
    if rebuild and zp.exists():
        with zipfile.ZipFile(zp) as zold:
            for nm in zold.namelist():
                if nm == "SEAL.json" or nm in expected:
                    continue
                carried[nm] = zold.read(nm)

    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, f in sorted(expected.items()):
            z.write(f, arc)
        for arc in sorted(carried):
            z.writestr(arc, carried[arc])
        # ★ 2026-10-16 修：`+ 1` 是为了把 SEAL.json 自身计入（与 SOURCE_MANIFEST 同口径）。
        z.writestr("SEAL.json", json.dumps({
            "ticker": ticker, "data_date": date, "sealed_at": _clock.now().isoformat(timespec="seconds"),
            "report_tree": tree.name, "n_entries": len(expected) + 1,
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
    if carried:
        print(f"      ↺ 另从旧包补入 {len(carried)} 项（未变但必需，防丢件）："
              f"{', '.join(sorted(carried)[:3])}{'…' if len(carried) > 3 else ''}")
    print(f"      ✓ 已封存 {len(got)} 项（{zp.stat().st_size/1024:.0f} KB，sha256 {sha[:12]}…），删除散文件 {removed} 个")
    return 0


def orphans(apply: bool) -> int:
    """工作目录里没有任何报告树的产物（**不含**非 12 角色专用通道，见 `_contract.NON_TREE_PREFIXES`）。"""
    known = set(runs_in_reports())
    found: list[tuple[str, str, dict]] = []
    if EVID.exists():
        for p in sorted(EVID.glob("*.md")):
            if "derived" in p.name or "supplement" in p.name or ".pre_" in p.name:
                continue
            # ★ 2026-10-10：非 12 角色专用通道以 evidence/ 为**正规归宿**，不是孤儿。
            #   此前无此豁免 ⇒ `--orphans --apply` 会真的删掉 `TREASURY_<date>.*`
            #   （宏观专题通道，服务任意标的，不是任何一轮的附件）——一颗删除雷。
            if is_non_tree_artifact(p.name):
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
    # ★ 2026-10-10：此处原有**逐字节相同的第二段 ANALYSIS 块**（原 L277–282）——
    #   第一段已把每个命中项 append 进 found，故第二段的 `if not any(...)` 恒为 False，
    #   是纯死代码。删掉以免将来只改一处而分叉（同一判据写在两处的经典陷阱）。
    if not found:
        print("  ✓ 无孤儿产物")
        return 0
    zp = BACKUP_DIR / f"orphans_{_clock.now():%Y%m%d_%H%M%S}.zip"
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
    # ★ 2026-10-20：回滚包固定落在 `BACKUP_DIR`（系统临时目录），**不在 ROOT 之下**，
    #   `zp.relative_to(ROOT)` 必抛 ValueError 且掩盖「已删除成功」的结果——
    #   只在 ROOT 内时用项目相对路径显示，否则回退为绝对路径。
    disp = zp.relative_to(ROOT).as_posix() if str(zp).startswith(str(ROOT)) else zp.as_posix()
    print(f"  ✓ 已删除 {n} 个孤儿文件；回滚包 {disp}")
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
    ap.add_argument("--rebuild", action="store_true",
                    help="重建审计包（当散件内容与包内不一致时用；旧包先备份到系统临时目录）")
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
        rc = seal(tk, dt, max(trees), args.apply, args.force, args.rebuild)
        if rc == 0 and args.apply:
            _refresh_scorecard()
        return rc

    runs = runs_in_reports()
    if not runs:
        print("（没有已交付的报告树）")
        return 0
    pending = 0
    print(f"\n共 {len(runs)} 轮已交付：\n")
    print(f"  {'标的':8s} {'数据基准日':12s} {'报告树':30s}  待封存产物")
    print("  " + "-" * 84)
    for (tk, dt), trs in sorted(runs.items()):
        tree = sorted(trs)[-1]
        g = artifacts_for(tk, dt)
        n = sum(len(v) for v in g.values())
        sealed = (tree / "_source.zip").exists()
        manifest_only = (not sealed) and (tree / "SOURCE_MANIFEST.json").exists()
        if n and sealed:
            with zipfile.ZipFile(tree / "_source.zip") as _z:
                _pk = {i.filename: i.file_size for i in _z.infolist()}
                _sh = {k: hashlib.sha256(_z.read(k)).hexdigest() for k in _pk}
            _chg = _unc = 0
            for _kd, _fs in g.items():
                for _f in _fs:
                    _a = _arcname(_kd, _f)
                    if _a not in _pk:
                        _unc += 1
                    else:
                        _b = _f.read_bytes()
                        if _pk[_a] != len(_b) or _sh[_a] != hashlib.sha256(_b).hexdigest():
                            _chg += 1
            if _chg or _unc:
                status = (f"✗ **审计包过期**（{_chg} 项已改 / {_unc} 项未入包）"
                          f" ⇒ 跑 `--run {tk} {dt} --rebuild --apply`")
            else:
                status = f"已封存（另有 {n} 个同内容散件待清）"
        else:
            status = "✓ 已封存" if sealed else (
                "✓ 已封存（轻量清单态）" if (manifest_only and n == 0) else (
                    f"{n} 个待封存" if n else "无散文件"
                )
            )
        if n:
            pending += 1
        print(f"  {tk:8s} {dt:12s} {tree.name:30s}  {status}")
    print(f"\n  待封存 {pending} 轮。加 --all --apply 执行（先打包并逐项校验，通过才删）。")
    if args.all and args.apply:
        rc = 0
        for (tk, dt), trs in sorted(runs.items()):
            tree = sorted(trs)[-1]
            r = seal(tk, dt, tree, True, args.force, args.rebuild)
            if r != 0:
                rc = r
        if rc == 0:
            _refresh_scorecard()
        return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
