# lifecycle: oneoff
"""清理 NDX 2026-09-21 的两棵并存报告树中的旧树 + drafts 散件。

判据（先校验后删）：
  旧树 NDX_20260922_100651 与 新树 NDX_20260923_161011 同基准日 2026-09-21，
  新树评级完整、口径单一；旧树 ratings 为空且 inferred/backfilled。
  散件 4_risk/aggressive.md 的 md5 已在审计包 alternates/ 内留存。

流程：打包 → 逐项校验（zip 内每文件 md5 与磁盘一致）→ 校验通过才删 → 写 DELETED 清单。
校验不通过即中止，不删任何东西。
"""
from __future__ import annotations
import hashlib
import json
import pathlib
import sys
import zipfile
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKUP = ROOT / ".workbuddy" / "backup"
ARCHIVE = ROOT / "reports" / "_archive"

OLD_TREE = ROOT / "reports" / "NDX" / "NDX_20260922_100651"
STRAY = ROOT / "wb_analysis" / "drafts" / "NDX_2026-09-21" / "4_risk" / "aggressive.md"

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def collect(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def main() -> int:
    targets: list[pathlib.Path] = []
    if OLD_TREE.exists():
        targets += collect(OLD_TREE)
    if STRAY.exists():
        targets.append(STRAY)
    if not targets:
        print("无待清对象，已干净。")
        return 0

    print(f"待清文件 {len(targets)} 个：")
    for p in targets:
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size}")

    # --- 1. 打包 ---
    BACKUP.mkdir(parents=True, exist_ok=True)
    zip_path = BACKUP / f"deleted_{stamp}_ndx_dup_tree.zip"
    manifest: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in targets:
            data = p.read_bytes()
            arc = p.relative_to(ROOT).as_posix()
            zf.writestr(arc, data)
            manifest[arc] = {"md5": md5(data), "size": len(data)}
    print(f"\n[1/3] 已打包 → {zip_path.relative_to(ROOT)}  ({zip_path.stat().st_size} 字节)")

    # --- 2. 逐项校验 ---
    ok = True
    with zipfile.ZipFile(zip_path) as zf:
        inner = set(zf.namelist())
        for arc, meta in manifest.items():
            if arc not in inner:
                print(f"  !! 包内缺 {arc}")
                ok = False
                continue
            d = md5(zf.read(arc))
            if d != meta["md5"]:
                print(f"  !! md5 不符 {arc}: 包内 {d} vs 清单 {meta['md5']}")
                ok = False
        if len(inner) != len(manifest):
            print(f"  !! 条目数不符: 包内 {len(inner)} vs 清单 {len(manifest)}")
            ok = False
    if not ok:
        print("\n[2/3] 校验失败 ⇒ 中止，不删除任何文件。回滚包保留在 backup/。")
        return 1
    print(f"[2/3] 校验通过：{len(manifest)}/{len(manifest)} 条目 md5 与磁盘一致")

    # --- 3. 删除（先文件后空目录，自深到浅） ---
    for p in targets:
        p.unlink()
    for d in sorted({p.parent for p in targets}, key=lambda x: len(x.parts), reverse=True):
        cur = d
        while cur != ROOT and cur.exists():
            if any(cur.iterdir()):
                break
            cur.rmdir()
            cur = cur.parent
    print(f"[3/3] 已删除 {len(targets)} 个文件（含清空的空目录）")

    # 留清单
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    listing = ARCHIVE / f"DELETED_{stamp}_ndx_dup_tree.txt"
    lines = [
        f"# 删除时间: {datetime.now().isoformat(timespec='seconds')}",
        f"# 原因: NDX 2026-09-21 两棵报告树并存，旧树信息被新树完全覆盖",
        f"# 回滚包: .workbuddy/backup/{zip_path.name}",
        f"# 条目数: {len(targets)}",
        "",
    ]
    for arc, meta in manifest.items():
        lines.append(f"{meta['size']:>10}  {meta['md5']}  {arc}")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n清单 → {listing.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
