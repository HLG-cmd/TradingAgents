# lifecycle: oneoff
# created: 2026-09-23
# archived: 2026-10-10
# why: 迁移已完成（`reports/_other/` 已空、34 棵树全在 `<TICKER>/<TICKER>_<stamp>/`），
#      且**断言已失真**：本文件按「每棵树 13 个文件」判 ✓/✗，而封存后的树是 **16 个**
#      （13 必需 + RUN.json + SOURCE_MANIFEST.json + _source.zip；`wb_analysis/_scorecard.py`
#      已把这一区分写明）⇒ 现在跑它对**每一棵树都报 ✗**，还给早已不存在的 DUOL/GLD/SNDK 报「目录不存在」。
#      现役的布局门禁是 `wb_analysis/_reports_index.py --check`（已挂进 `scripts/_health.py`）。
# serves: 2026-09-23 一次性布局迁移（8 个标的）
# usage: ./.venv/Scripts/python.exe scripts/_fix_reports_layout.py
"""核对并按需修正 `reports/` 的目标布局（幂等；可反复运行）。

目标布局：`reports/<TICKER>/<TICKER>_<stamp>/` 下每棵树必须 13 个文件
（12 角色 + complete_report.md）；`_other/` 下**不应**再有任何 `<TICKER>` 目录。

本脚本只做三件事：
  1. 若 `reports/<T>/` 缺失或文件数不足，而 `reports/_other/<T>/` 有完整副本 ⇒ 从副本恢复；
  2. 恢复后校验 md5 一致，再删除 `_other/<T>` 残留；
  3. 打印最终布局断言（每棵树 13 文件、顶层无散落文件、_other 内无标的目录）。

用法: ./.venv/Scripts/python.exe scripts/_fix_reports_layout.py [--apply]
"""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "reports"
TICKERS = ["DUOL", "GLD", "GOOG", "MU", "NDX", "NFLX", "SNDK", "SPCX"]
APPLY = "--apply" in sys.argv


def sig(d: Path) -> dict:
    if not d.exists():
        return {}
    return {p.relative_to(d).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()}


def copy_in(src: Path, dst: Path) -> int:
    n = 0
    for f in sorted(src.rglob("*")):
        if f.is_file():
            t = dst / f.relative_to(src)
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(f.read_bytes())
            n += 1
    return n


def rm_tree(d: Path) -> int:
    n = 0
    for f in sorted(d.rglob("*"), reverse=True):
        if f.is_file():
            try:
                f.unlink()
                n += 1
            except Exception:  # noqa: BLE001
                pass
    for sub in sorted([x for x in d.rglob("*") if x.is_dir()], key=lambda x: len(x.parts), reverse=True):
        try:
            sub.rmdir()
        except OSError:
            pass
    try:
        d.rmdir()
    except OSError:
        pass
    return n


def main() -> int:
    for t in TICKERS:
        top, alt = R / t, R / "_other" / t
        if alt.exists():
            st, sa = sig(top), sig(alt)
            print(f"{t:6s} 顶层 {len(st):3d} 文件 | _other 副本 {len(sa):3d} 文件", end="")
            if len(st) >= len(sa) and st:
                print("  ⇒ 顶层已完整，删除副本")
                if APPLY:
                    rm_tree(alt)
            else:
                if not APPLY:
                    print("  ⇒ 需从副本恢复（dry-run）")
                else:
                    n = copy_in(alt, top)
                    same = sig(top) == sa
                    print(f"  ⇒ 已恢复 {n} 文件，md5 一致={same}")
                    if same:
                        rm_tree(alt)
                    else:
                        print("     ✗ md5 不一致，保留副本待人工检查")
        else:
            st = sig(top)
            print(f"{t:6s} 顶层 {len(st):3d} 文件 | 无副本")

    # ── 最终断言 ─────────────────────────────────────────────
    print("\n" + "=" * 88)
    print("最终布局断言")
    print("=" * 88)
    bad = 0
    for t in TICKERS:
        d = R / t
        if not d.exists():
            print(f"  ✗ {t}: 目录不存在"); bad += 1; continue
        trees = [x for x in d.iterdir() if x.is_dir()]
        for tr in sorted(trees):
            n = len([p for p in tr.rglob("*") if p.is_file()])
            flag = "✓" if n == 13 else "✗"
            if n != 13:
                bad += 1
            print(f"  {flag} {t}/{tr.name}: {n} 文件")
    loose = [p.name for p in R.iterdir() if p.is_file()]
    print(f"  规整：顶层散落文件 {len(loose)} 个 {loose if loose else ''}")
    other_tk = [x.name for x in (R / "_other").iterdir() if x.is_dir() and x.name in TICKERS] if (R / "_other").exists() else []
    print(f"  规整：_other 内的标的目录 {len(other_tk)} 个 {other_tk if other_tk else ''}")
    bad += len(loose) + len(other_tk)
    print(f"\n[结论] 问题项 {bad} 个" + ("（布局正确）" if bad == 0 else "（需处理）"))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
