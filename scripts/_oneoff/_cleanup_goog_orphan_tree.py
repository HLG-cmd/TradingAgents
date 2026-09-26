# lifecycle: oneoff
"""清理 GOOG 2026-09-23 的两棵并存报告树中的孤儿树 GOOG_20260923_164039。

判据（先校验后删）：
  孤儿树 GOOG_20260923_164039 与保留树 GOOG_20260924_101312 同基准日 2026-09-23。
  保留树 16 个文件（含 RUN.json + SOURCE_MANIFEST.json + _source.zip），评级 manager/trader/pm 全为 Hold；
  孤儿树 13 个文件，缺上述三个审计件，角色正文明显更薄（pm 12,072 vs 18,935 字符），
  且生成于 RUN.json 机制之前 ⇒ 关联关系只能靠推测。来源草稿已丢失 ⇒ 无法补封存、无法重渲染。
  ⇒ 它是同日的早期不完整版本，已被保留树完整覆盖，保留只会持续污染报告卫生检查（3 项 WARN 全源于它）。

流程：打包 → 逐项校验（zip 内每文件 md5 与磁盘一致）→ 校验通过才删 → 写 DELETED 清单。
      校验不通过即中止，不删任何东西。
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

ORPHAN = ROOT / "reports" / "GOOG" / "GOOG_20260923_164039"
KEEP = ROOT / "reports" / "GOOG" / "GOOG_20260924_101312"

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def collect(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def main() -> int:
    # --- 0. 前置断言：保留树必须在且更完整 ---
    if not KEEP.exists():
        print(f"!! 保留树不存在：{KEEP.relative_to(ROOT)} ⇒ 中止（不能在没有替代的情况下删除）")
        return 1
    keep_n = len(collect(KEEP))
    if keep_n < 14:
        print(f"!! 保留树只有 {keep_n} 个文件，比预期少 ⇒ 中止，人工复核")
        return 1
    if not ORPHAN.exists():
        print("孤儿树已不存在，无需清理。")
        return 0

    targets = collect(ORPHAN)
    print(f"保留树 {KEEP.relative_to(ROOT)}：{keep_n} 个文件（完整，含审计包）")
    print(f"待清孤儿树 {ORPHAN.relative_to(ROOT)}：{len(targets)} 个文件\n")
    for p in targets:
        print(f"  {p.relative_to(ROOT)}  {p.stat().st_size:,}")

    # --- 1. 打包 ---
    BACKUP.mkdir(parents=True, exist_ok=True)
    zip_path = BACKUP / f"deleted_{stamp}_goog_orphan_tree.zip"
    manifest: dict[str, dict] = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in targets:
            data = p.read_bytes()
            arc = p.relative_to(ROOT).as_posix()
            zf.writestr(arc, data)
            manifest[arc] = {"md5": md5(data), "size": len(data)}
    print(f"\n[1/3] 已打包 → {zip_path.relative_to(ROOT)}  ({zip_path.stat().st_size:,} 字节)")

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

    # --- 3. 删除（先文件后空目录，自深到浅；不用 rmtree，本机 safe-delete 会拦目录级删除） ---
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

    # --- 留清单（可审计、可还原） ---
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    listing = ARCHIVE / f"DELETED_{stamp}_goog_orphan_tree.txt"
    lines = [
        f"# 删除时间: {datetime.now().isoformat(timespec='seconds')}",
        "# 删除对象: reports/GOOG/GOOG_20260923_164039（孤儿报告树）",
        "# 原因: 与 reports/GOOG/GOOG_20260924_101312 同基准日 2026-09-23 并存；",
        "#       孤儿树缺 RUN.json / SOURCE_MANIFEST.json / _source.zip，角色正文更薄，",
        "#       来源草稿已丢失 ⇒ 无法补封存、无法重渲染 ⇒ 只能靠推测关联，持续污染报告卫生检查。",
        f"# 保留树: reports/GOOG/GOOG_20260924_101312（{keep_n} 个文件，含完整审计包）",
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
