# lifecycle: oneoff
"""清理 2026-10-14 卫生检查列出的「同基准日并存」报告树中**应淘汰的那一棵**。

## 本批对象（1 对）

  NFLX 2026-10-13：
    保留 `NFLX_20261014_101104`  —— **已封存**（含 `_source.zip` + `SOURCE_MANIFEST.json`），
                                    盘后采集（美东 10-13 收盘后），价格口径 70.46（正式收盘价）
    淘汰 `NFLX_20261014_094940`  —— **未封存**（无审计包），且**草稿目录已被对方封存时删除**
                                    ⇒ 无法补建审计包 ⇒ 无法满足本项目「报告内每个数字可溯源」的
                                    硬要求。盘中采集（13:23 ET），价格口径 70.605（当日 bar 未收盘）

判据（先校验后删）：**保留数据更完整者；完全对等时保留较新者。**
本例中两者并非重复渲染，而是**两个不同数据口径**；淘汰理由不是「较旧」，
而是**「未封存 ⇒ 不可溯源」+「基准日相同」**。用户在 2026-10-14 明确选择归档本棵。

## 流程

打包 → 逐项 md5 校验（zip 内 vs 磁盘）→ **通过才删** → 写 DELETED 清单。
**校验不通过即中止，不删任何东西。**

★ safe-delete 钩子有「50 条/轮」上限（铁律 48）⇒ 本批 15 个文件，单轮可执行。

用法：
  ./.venv/Scripts/python.exe scripts/_oneoff/_cleanup_dup_trees_20261014.py NFLX/NFLX_20261014_094940
"""
from __future__ import annotations
import hashlib
import pathlib
import sys
import zipfile
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKUP = ROOT / ".workbuddy" / "backup"
ARCHIVE = ROOT / "reports" / "_archive"

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    targets: list[pathlib.Path] = []
    for rel in argv:
        root = ROOT / "reports" / rel
        if not root.exists():
            print(f"  SKIP (不存在): {rel}")
            continue
        files = sorted(p for p in root.rglob("*") if p.is_file())
        print(f"  {rel}: {len(files)} 个文件")
        targets += files

    if not targets:
        print("无待清对象，已干净。")
        return 0
    if len(targets) > 50:
        print(f"✗ 本批 {len(targets)} 个文件 > safe-delete 上限 50 ⇒ 拒绝执行，请拆小批次（铁律 48）。")
        return 3

    print(f"\n待清文件合计 {len(targets)} 个")

    # --- 1. 打包 ---
    BACKUP.mkdir(parents=True, exist_ok=True)
    zip_path = BACKUP / f"dup_trees_{stamp}.zip"
    manifest: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in targets:
            data = p.read_bytes()
            arc = p.relative_to(ROOT).as_posix()
            zf.writestr(arc, data)
            manifest[arc] = {"md5": md5(data), "size": len(data)}
    print(f"[1/3] 已打包 → {zip_path.relative_to(ROOT)}  ({zip_path.stat().st_size} 字节)")

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
        if zf.testzip() is not None:
            print(f"  !! zip CRC 校验失败: {zf.testzip()}")
            ok = False
    if not ok:
        print("[2/3] 校验失败 ⇒ 中止，不删除任何文件。回滚包保留在 backup/。")
        return 1
    print(f"[2/3] 校验通过：{len(manifest)}/{len(manifest)} 条目 md5 与磁盘一致，CRC 干净")

    # --- 3. 删除（先文件后空目录，自深到浅） ---
    removed = 0
    for p in targets:
        try:
            p.unlink()
            removed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  !! 删除失败（fail-closed？）: {p} -> {e}")
    for d in sorted({p.parent for p in targets}, key=lambda x: len(x.parts), reverse=True):
        cur = d
        while cur != ROOT and cur.exists():
            try:
                if any(cur.iterdir()):
                    break
                cur.rmdir()
            except Exception:  # noqa: BLE001
                break
            cur = cur.parent
    print(f"[3/3] 已删除 {removed}/{len(targets)} 个文件（含清空的空目录）")

    # --- 留清单 ---
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    listing = ARCHIVE / f"DELETED_{stamp}_dup_trees.txt"
    lines = [
        f"# 删除时间: {datetime.now().isoformat(timespec='seconds')}",
        "# 原因: NFLX 2026-10-13 同基准日并存两棵报告树（报告卫生检查 2026-10-14 列出）。",
        "#       两者不是重复渲染，而是两个数据口径：保留棵为盘后采集（70.46 正式收盘），",
        "#       淘汰棵为盘中采集（70.605，当日 bar 未收盘）。",
        "#       淘汰规则＝保留数据更完整者：保留棵**已封存**（有 _source.zip 可溯源），",
        "#       淘汰棵未封存且草稿已被删除 ⇒ 无法补建审计包 ⇒ 不满足「数字可溯源」硬要求。",
        "#       用户于 2026-10-14 明确选择归档本棵。",
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
    sys.exit(main(sys.argv[1:]))
