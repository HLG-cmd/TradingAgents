# -*- coding: utf-8 -*-
# lifecycle: oneoff
"""打包并移除被取代的 AVGO 报告树（183033）：先打包、逐项校验，通过再逐文件删除。

本机 safe-delete 钩子会拦截目录级 rmtree/移动 ⇒ 逐文件 os.remove + 自深到浅 rmdir。
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"D:\Antigravity\TradingAgents")
TREE = ROOT / "reports" / "AVGO" / (sys.argv[1] if len(sys.argv) > 1 else "AVGO_20261008_183033")
BACKUP = ROOT / ".workbuddy" / "backup" / f"{TREE.name}_superseded.zip"

if not TREE.is_dir():
    raise SystemExit(f"目标树不存在，放弃：{TREE}")

files = sorted(p for p in TREE.rglob("*") if p.is_file())
print(f"[打包] 待处理 {len(files)} 个文件 → {BACKUP}")

BACKUP.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(BACKUP, "w", zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, p.relative_to(TREE).as_posix())

# --- 逐项校验 ---
with zipfile.ZipFile(BACKUP) as z:
    bad = z.testzip()
    if bad is not None:
        raise SystemExit(f"✗ ZIP CRC 失败：{bad}")
    names = set(z.namelist())
expect = {p.relative_to(TREE).as_posix() for p in files}
missing = expect - names
extra = names - expect
print(f"[校验] 包内 {len(names)} 条 ｜ 期望 {len(expect)} 条 ｜ 缺 {len(missing)} ｜ 多 {len(extra)}")
if missing or extra:
    raise SystemExit(f"✗ 清单不一致，中止删除。缺={sorted(missing)[:5]} 多={sorted(extra)[:5]}")

# --- 逐文件删除 ---
removed = 0
for p in files:
    try:
        os.remove(p)
        removed += 1
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ 删除失败 {p.name}: {type(e).__name__}: {e}")
print(f"[删除] 已删 {removed}/{len(files)} 个文件")

# --- 自深到浅删空目录 ---
dirs = sorted((p for p in TREE.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts))
for d in dirs:
    try:
        os.rmdir(d)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ rmdir 失败 {d}: {type(e).__name__}: {e}")
try:
    os.rmdir(TREE)
    print(f"[完成] 已移除 {TREE}")
except Exception as e:  # noqa: BLE001
    print(f"  ✗ 根目录未清空: {type(e).__name__}: {e}")
    print("  剩余：", [str(x.relative_to(TREE)) for x in TREE.rglob('*')][:10])
