# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_resync_563020_seal_meta.py
"""把封存元数据与审计包实际内容**重新对齐**（本轮发现三处过期）。

## 发现的不一致（修复后自查）
| 元数据 | 记录值 | 实际值 |
|---|---|---|
| `SEAL.json` 的 `n_entries` | 12 | 实际包内 19 项 |
| `SOURCE_MANIFEST.json` 的 `n_entries` | 13 | 19 |
| `SOURCE_MANIFEST.json` 的 `sha256` | be6bda8c…（13 项包的哈希） | 需重算 |

⇒ 根因：`--rebuild` 只封了 13 项并把 SEAL/MANIFEST 按 13 项写死；
   我的 `_repair` 脚本补齐了包内容，却**没有回写这两个元数据** ⇒ 元数据与实物不符。

## 本脚本做什么（幂等）
1. 读回 `_source.zip` 实际条目与字节，重算 sha256；
2. 重写包内 `SEAL.json`（n_entries = 实际条目数）；
3. 重写树内 `SOURCE_MANIFEST.json`（n_entries / bytes / sha256 / contents）；
4. 逐项校验：MANIFEST 的 contents 与包内条目**集合相等**，且 sha256 可复现。
⚠️ 改写 SEAL.json 会改变包字节 ⇒ 需**先写包、再算哈希、最后写 MANIFEST**（避免自指死循环）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / "reports" / "563020" / "563020_20261016_133333"
PKG = TREE / "_source.zip"
MANIFEST = TREE / "SOURCE_MANIFEST.json"
BACKUP_DIR = ROOT / ".workbuddy-ai" / "backup"


def zip_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not PKG.exists():
        print(f"✗ 找不到 {PKG.relative_to(ROOT)}")
        return 1

    # ── 0. 备份 ──
    bak = BACKUP_DIR / "source_563020_2026-10-15_20261016_145230_PRE_resync.zip"
    shutil.copy2(PKG, bak)
    if MANIFEST.exists():
        shutil.copy2(MANIFEST, BACKUP_DIR / "SOURCE_MANIFEST_563020_PRE_resync.json")
    print(f"  ↺ 已备份 → {bak.name}")

    # ── 1. 读入包内全部条目（除 SEAL.json 外）──
    with zipfile.ZipFile(PKG) as z:
        items = {n: z.read(n) for n in z.namelist() if n != "SEAL.json"}
    print(f"  包内（不含 SEAL.json）：{len(items)} 项")

    # ── 2. 重写 SEAL.json（n_entries = 含自身在内的总项数）──
    seal = {
        "ticker": "563020",
        "data_date": "2026-10-15",
        "sealed_at": "2026-10-16T14:52:30",
        "report_tree": TREE.name,
        "n_entries": len(items) + 1,
        "rebuilt_at": "2026-10-16T14:55:00",
        "note": "本轮为一致性修复后重建；--rebuild 只收录变更文件，已补齐证据包与未变文件至完整 19 项。",
    }
    with zipfile.ZipFile(PKG, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SEAL.json", json.dumps(seal, ensure_ascii=False, indent=2) + "\n")
        for n, b in sorted(items.items()):
            z.writestr(n, b)

    # ── 3. 重算哈希并写 MANIFEST ──
    with zipfile.ZipFile(PKG) as z:
        names = sorted(z.namelist())
    size = PKG.stat().st_size
    digest = zip_sha256(PKG)
    man = {
        "ticker": "563020",
        "data_date": "2026-10-15",
        "archive": "_source.zip",
        "n_entries": len(names),
        "bytes": size,
        "sha256": digest,
        "contents": names,
    }
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")

    # ── 4. 逐项校验（双向）──
    with zipfile.ZipFile(PKG) as z:
        inner = sorted(z.namelist())
        seal2 = json.loads(z.read("SEAL.json").decode("utf-8"))
    ok = True
    if inner != sorted(man["contents"]):
        print("  ✗ MANIFEST.contents 与包内条目不一致")
        ok = False
    if seal2["n_entries"] != len(inner):
        print(f"  ✗ SEAL.n_entries={seal2['n_entries']} ≠ 实际 {len(inner)}")
        ok = False
    if zip_sha256(PKG) != man["sha256"]:
        print("  ✗ sha256 不可复现")
        ok = False

    print()
    print(f"  SEAL.n_entries      = {seal2['n_entries']}")
    print(f"  MANIFEST.n_entries  = {man['n_entries']}")
    print(f"  MANIFEST.bytes      = {man['bytes']:,}")
    print(f"  MANIFEST.sha256     = {man['sha256'][:24]}…")
    print(f"  sha256 复现校验     = {'✓' if zip_sha256(PKG) == man['sha256'] else '✗'}")
    print()
    print("  ✓ 三处元数据已与包内实物一致" if ok else "  ✗ 仍有不一致，需人工检查")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
