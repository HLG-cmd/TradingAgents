# lifecycle: oneoff
# created: 2026-10-12
# serves: SKHY 2026-10-10（旧树归档）
#
# 把**内容重复**的旧报告树 `reports/SKHY/SKHY_20261011_102533` 归档到
# `reports/SKHY/_archive/`（该目录被 `_reports_index.py` 的 SKIP_ARCHIVE_DIRS 跳过，
# 故归档后卫生 WARN 自然消失）。
#
# 共性铁律：**删前先打包、逐项校验不过即中止**。
#   ① 先按原相对路径打包成回滚包（`.workbuddy/backup/`）；
#   ② 校验回滚包：条目数 + 逐文件 sha256 全部吻合，否则**中止**（不删任何东西）；
#   ③ 复制到 `_archive/`，再校验一遍；
#   ④ 才逐文件删除原件，再自深到浅 rmdir 空壳。
# 任一步失败即中止，且**已复制的归档保留**（宁可重复、不可丢失）。
from __future__ import annotations

import hashlib
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / "reports" / "SKHY" / "SKHY_20261011_102533"
ARCHIVE = ROOT / "reports" / "SKHY" / "_archive" / "SKHY_20261011_102533"
BACKUP = ROOT / ".workbuddy" / "backup"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if not TREE.exists():
        print(f"✗ 源树不存在：{TREE}")
        return 1
    files = sorted(p for p in TREE.rglob("*") if p.is_file())
    if not files:
        print("✗ 源树无文件")
        return 1
    print(f"[源树] {TREE.relative_to(ROOT).as_posix()}  文件 {len(files)} 个，"
          f"{sum(p.stat().st_size for p in files):,} 字节")

    # ① 回滚包
    BACKUP.mkdir(parents=True, exist_ok=True)
    zp = BACKUP / f"rollback_SKHY_20261011_102533_{datetime.now():%Y%m%d_%H%M%S}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(TREE).as_posix())
    print(f"[① 回滚包] {zp.relative_to(ROOT).as_posix()}  {zp.stat().st_size:,} 字节")

    # ② 校验回滚包
    with zipfile.ZipFile(zp) as z:
        names = set(z.namelist())
        for p in files:
            rel = p.relative_to(TREE).as_posix()
            if rel not in names:
                print(f"✗ 回滚包缺 {rel} ⇒ 中止")
                return 1
            if hashlib.sha256(z.read(rel)).hexdigest() != sha(p):
                print(f"✗ 回滚包内容不符 {rel} ⇒ 中止")
                return 1
    print(f"[② 校验] 回滚包 {len(names)} 项，逐文件 sha256 全部吻合 ✓")

    # ③ 复制到 _archive/
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for p in files:
        dst = ARCHIVE / p.relative_to(TREE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    copied = sorted(p for p in ARCHIVE.rglob("*") if p.is_file())
    if len(copied) != len(files):
        print(f"✗ 归档文件数不符（{len(copied)} vs {len(files)}）⇒ 中止")
        return 1
    for p in files:
        d = ARCHIVE / p.relative_to(TREE)
        if sha(d) != sha(p):
            print(f"✗ 归档内容不符 {p.name} ⇒ 中止")
            return 1
    print(f"[③ 归档] {ARCHIVE.relative_to(ROOT).as_posix()}  {len(copied)} 个文件，sha256 全部吻合 ✓")

    # ④ 删除原件（逐文件 os.remove，再自深到浅 rmdir）
    ok = failed = 0
    for p in files:
        try:
            p.unlink()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"    ✗ 删除失败 {p.relative_to(TREE).as_posix()}: {type(exc).__name__} {exc}")
            failed += 1
    dirs = sorted([d for d in TREE.rglob("*") if d.is_dir()], key=lambda x: len(x.parts), reverse=True)
    dirs.append(TREE)
    for d in dirs:
        try:
            d.rmdir()
        except OSError:
            pass
    print(f"[④ 删除原件] 成功 {ok} 个，失败 {failed} 个；源树仍存在={TREE.exists()}")
    if failed:
        print("    ⇒ 原件未完全删除（归档与回滚包均在，不丢数据）；请人工处理后再跑索引。")
        return 1
    print("\n✓ 旧树已归档：数据完整保留（回滚包 + _archive/ 两份），原件已清空。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
