# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_cleanup_563020_failed_tree.py
"""清理 563020 首轮「反读 FAIL」的渲染树（133236）。

## 为什么要清理
`_verify_report.py` 判定 `133236` 不合格（manager.md 全文有 3 处五档词，
而契约要求每个白名单席位**恰 1 处**）。修正后重新渲染得到 `133333`（反读全过）。
⇒ `133236` 是**同一轮次的失败渲染残留**，与 `133333` 并存会造成
「同一基准日两棵树」的歧义（与 512400.SS 那次同型）。

## 安全规程（项目铁律：删前先打包 + 逐项校验不过即中止）
1. 先把整棵树写入 `.workbuddy-ai/backup/` 的 zip；
2. 重新打开 zip，逐项比对「清单 vs 包内条目」与每个文件的字节数；
3. 校验全过才删除；任一项不符即中止，不动磁盘。
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / "reports" / "563020" / "563020_20261016_133236"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "deleted_20261016_133236_563020_failed_render.zip"


def main() -> int:
    if not TREE.exists():
        print(f"  · 目标不存在，无需清理：{TREE.relative_to(ROOT).as_posix()}")
        return 0

    files = sorted(p for p in TREE.rglob("*") if p.is_file())
    print(f"  待打包文件数：{len(files)}")

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BACKUP, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(TREE).as_posix())

    # ── 逐项校验 ──
    with zipfile.ZipFile(BACKUP) as z:
        inner = {i.filename: i.file_size for i in z.infolist()}
        expect = {f.relative_to(TREE).as_posix(): f.stat().st_size for f in files}
        if len(inner) != len(expect):
            print(f"  ✗ 中止：包内条目数 {len(inner)} ≠ 清单 {len(expect)}")
            return 1
        for name, size in expect.items():
            if name not in inner:
                print(f"  ✗ 中止：包内缺失 {name}")
                return 1
            if inner[name] != size:
                print(f"  ✗ 中止：{name} 字节数不符 包内={inner[name]} 磁盘={size}")
                return 1
    print(f"  ✓ 打包校验通过：{BACKUP.relative_to(ROOT).as_posix()} "
          f"（{len(files)} 项逐项一致）")

    # ── 逐文件删除，再自深到浅删目录 ──
    for f in files:
        f.unlink()
    dirs = sorted((p for p in TREE.rglob("*") if p.is_dir()),
                  key=lambda p: len(p.parts), reverse=True)
    for d in dirs:
        try:
            d.rmdir()
        except OSError as e:
            print(f"  ⚠ 目录未删（可能有占用）：{d.name} → {e}")
    try:
        TREE.rmdir()
    except OSError as e:
        print(f"  ⚠ 根目录未删：{e}")
        return 1
    print(f"  ✓ 已删除失败渲染树：{TREE.relative_to(ROOT).as_posix()}")
    left = sorted(p.name for p in (ROOT / "reports" / "563020").iterdir())
    print(f"  剩余树：{left}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
