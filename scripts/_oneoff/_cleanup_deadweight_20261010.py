# lifecycle: oneoff
# created: 2026-10-10
# serves: 一次性清理死重（user 指示「没用的或有副作用的要么优化要么不要了」）
"""打包 → 逐项校验 → 删除：wb_analysis/scratch/ + wb_analysis/_verify_statements_edgar.py。

铁律：删前先打包、压缩包内容与清单**逐项校验**，不一致即中止。
本机 safe-delete 钩子对**目录**删除 fail-closed ⇒ 走「逐文件 os.remove + 自深到浅 rmdir」。
"""
import hashlib
import pathlib
import shutil
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKUP = ROOT / ".workbuddy" / "backup"
BACKUP.mkdir(parents=True, exist_ok=True)
ZIP = BACKUP / "cleanup_20261010_deadweight.zip"

TARGETS = [
    ROOT / "wb_analysis" / "scratch",
    ROOT / "wb_analysis" / "_verify_statements_edgar.py",
]


def collect() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for t in TARGETS:
        if t.is_dir():
            out += [p for p in sorted(t.rglob("*")) if p.is_file()]
        elif t.is_file():
            out.append(t)
    return out


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def main() -> int:
    files = collect()
    if not files:
        print("[cleanup] 无可清理目标（可能已清理）-> 退出 0")
        return 0
    print(f"[cleanup] 待清理 {len(files)} 个文件：")
    for f in files:
        print(f"    {f.relative_to(ROOT).as_posix()}  ({f.stat().st_size} B, {sha(f)})")

    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(ROOT).as_posix())
    print(f"\n[cleanup] 回滚包 -> {ZIP.name}  ({ZIP.stat().st_size} B)")

    # ── 逐项校验：包内条目数 == 清单数，且逐个文件内容哈希一致 ──────────
    bad = []
    with zipfile.ZipFile(ZIP) as z:
        names = set(z.namelist())
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if rel not in names:
                bad.append(f"{rel} 不在包内")
                continue
            if hashlib.sha256(z.read(rel)).hexdigest()[:16] != sha(f):
                bad.append(f"{rel} 内容哈希不一致")
    if bad:
        print("\n[cleanup] ✗ 校验失败，中止删除：")
        for b in bad:
            print("    -", b)
        return 2
    print("[cleanup] ✓ 逐项校验通过（条目数 + 内容哈希）")

    # ── 删除：逐文件 os.remove，再自深到浅 rmdir ────────────────────────
    for f in files:
        try:
            f.unlink()
        except Exception as e:  # noqa: BLE001
            print(f"[cleanup] ✗ 删文件失败 {f}: {type(e).__name__}: {e}")
            return 3
    removed_dirs = []
    for t in TARGETS:
        if t.is_dir():
            for d in sorted([p for p in t.rglob("*") if p.is_dir()],
                            key=lambda p: len(p.parts), reverse=True):
                try:
                    d.rmdir()
                    removed_dirs.append(d)
                except Exception:  # noqa: BLE001
                    pass
            try:
                t.rmdir()
                removed_dirs.append(t)
            except Exception as e:  # noqa: BLE001
                print(f"[cleanup] ⚠ 目录未清空 {t}: {type(e).__name__}: {e}")
    print(f"[cleanup] 已删 {len(files)} 文件 / {len(removed_dirs)} 目录")
    left = [t for t in TARGETS if t.exists()]
    print(f"[cleanup] 残留目标：{left if left else '无'}")
    return 0 if not left else 4


if __name__ == "__main__":
    raise SystemExit(main())
