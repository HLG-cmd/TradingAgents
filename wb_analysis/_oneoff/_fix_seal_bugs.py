# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_fix_seal_bugs.py
"""修复 `_seal_run.py` 的两个实测 bug（本脚本用精确替换 + ast 校验 + 幂等）。

## Bug 1（全库性，51/52 命中）：`SEAL.json` 的 `n_entries` 恒少 1
- **现象**：全库 52 个 `_source.zip`，51 个的 `SEAL.n_entries` = 包内实际条目数 − 1。
- **根因**：写 SEAL 时用 `len(expected)` / `len(old_entries)`，**均未把 `SEAL.json` 自身算进去**；
  而 `MANIFEST.n_entries` 用 `len(got)`（`z.namelist()` 含 SEAL.json）⇒ **两处口径不一致**。
- **影响**：`scripts/_verify_pack_tree.py` 把两者并列打印，读者会看到"声明 19 项、实际 19 项"
  之外的自相矛盾；任何按 `n_entries` 做完整性判断的下游都会误判。
- **修法**：两处都改为 `+ 1`（统一为「含 SEAL.json 的总条目数」，与 MANIFEST 一致）。

## Bug 2（本轮实测）：`--rebuild` 会丢失「未变但必需」的文件
- **现象**：563020 本轮 `--rebuild` 后审计包只剩 13 项（正常 19 项），
  丢掉 evidence 3 件 + `0_derived.md` + `fundamentals.md` + `meta.json` 共 6 件。
- **为什么严重**：审计包的承诺是「报告里每个数字都能在包内溯源」；
  丢了证据包 ⇒ **最底层的溯源依据消失**，而外观完全正常（包能打开、校验也说"通过"）。
- **修法（护栏，不猜根因）**：重建前先读旧包，**把旧包里已有、而本次 `expected` 未覆盖的条目补入**
  ⇒ 保证 `新包 ⊇ 旧包`，并在输出里显式打印补入项数。这样无论根因是磁盘缺件还是收集遗漏，
  都不会再静默丢件（对应项目原则：把「会产生新目录/新文件的那段放最后 + 加幂等护栏」）。

⚠️ 本脚本只做**精确字符串替换**，每处替换前先断言命中；全部替换后做 `ast.parse` 校验再落盘。
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "wb_analysis" / "_seal_run.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_seal_bugs_20261016_seal_run.py"

# (说明, 旧串, 新串)
EDITS: list[tuple[str, str, str]] = [
    # ── Bug 1a：增量并入分支 ──
    ("Bug1a SEAL off-by-one（增量并入分支）",
     '''                zout.writestr("SEAL.json", json.dumps({
                    "ticker": ticker, "data_date": date,
                    "sealed_at": datetime.now().isoformat(timespec="seconds"),
                    "report_tree": tree.name, "n_entries": len(old_entries),
                }, ensure_ascii=False, indent=2) + "\\n")''',
     '''                # ★ 2026-10-16 修（全库 51/52 命中）：`n_entries` 必须**含 SEAL.json 自身**，
                #   否则与 SOURCE_MANIFEST（用 len(z.namelist())）口径不一致、恒少 1。
                zout.writestr("SEAL.json", json.dumps({
                    "ticker": ticker, "data_date": date,
                    "sealed_at": datetime.now().isoformat(timespec="seconds"),
                    "report_tree": tree.name, "n_entries": len(old_entries) + 1,
                }, ensure_ascii=False, indent=2) + "\\n")'''),

    # ── Bug 1b：主封存分支 ──
    ("Bug1b SEAL off-by-one（主封存分支）",
     '''        z.writestr("SEAL.json", json.dumps({
            "ticker": ticker, "data_date": date, "sealed_at": datetime.now().isoformat(timespec="seconds"),
            "report_tree": tree.name, "n_entries": len(expected),
        }, ensure_ascii=False, indent=2) + "\\n")''',
     '''        # ★ 2026-10-16 修：`+ 1` 是为了把 SEAL.json 自身计入（与 SOURCE_MANIFEST 同口径）。
        z.writestr("SEAL.json", json.dumps({
            "ticker": ticker, "data_date": date, "sealed_at": datetime.now().isoformat(timespec="seconds"),
            "report_tree": tree.name, "n_entries": len(expected) + 1,
        }, ensure_ascii=False, indent=2) + "\\n")'''),

    # ── Bug 2：rebuild 丢件护栏（在写包前，把旧包未被覆盖的条目补入）──
    ("Bug2 rebuild 丢件护栏",
     '''    zp = tree / "_source.zip"
    expected: dict[str, Path] = {_arcname(kind, f): f
                                 for kind, files in groups.items() for f in files}

    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, f in sorted(expected.items()):
            z.write(f, arc)''',
     '''    zp = tree / "_source.zip"
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
            z.writestr(arc, carried[arc])'''),

    # ── Bug 2 配套：收尾打印补入项数（让人看得见）──
    ("Bug2 配套：收尾打印补入项数",
     '''    print(f"      ✓ 已封存 {len(got)} 项（{zp.stat().st_size/1024:.0f} KB，sha256 {sha[:12]}…），删除散文件 {removed} 个")
    return 0''',
     '''    if carried:
        print(f"      ↺ 另从旧包补入 {len(carried)} 项（未变但必需，防丢件）："
              f"{', '.join(sorted(carried)[:3])}{'…' if len(carried) > 3 else ''}")
    print(f"      ✓ 已封存 {len(got)} 项（{zp.stat().st_size/1024:.0f} KB，sha256 {sha[:12]}…），删除散文件 {removed} 个")
    return 0'''),
]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")

    # 幂等：已修过则跳过
    if "len(expected) + 1" in src and "carried: dict[str, bytes]" in src:
        print("  · 两个 bug 均已修复（幂等跳过）")
        return 0

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    print(f"  ↺ 已备份 → {BACKUP.name}")

    miss = []
    for tag, old, new in EDITS:
        if old not in src:
            miss.append(tag)
            continue
        src = src.replace(old, new, 1)
        print(f"  ✓ {tag}")
    if miss:
        print(f"  ✗ 未命中：{miss}")
        print("     ⇒ 未做任何写入，文件保持原样")
        return 1

    # ── 先 ast 校验，通过才落盘（铁律 33：先校验再写盘）──
    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  ✗ ast 校验失败，未落盘：{e}")
        return 1
    TARGET.write_text(src, encoding="utf-8", newline="\n")
    print("  ✓ ast 校验通过，已落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
