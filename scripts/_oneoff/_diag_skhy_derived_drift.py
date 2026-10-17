# lifecycle: oneoff
# created: 2026-10-11
# serves: SKHY 2026-10-10
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_diag_skhy_derived_drift.py
"""诊断：O1 改了 `_derive_stock.py` 后，SKHY 封存包里的 `derived.md` 快照是否还能复现。

判据（决定要不要重跑重封）：
  · 若新旧差异**纯属新增行**（旧文本整体是新文本的子序列）⇒ 旧快照里的**每一个数字
    都仍然成立**，封存报告不缺任何证据 ⇒ **不需重封**，把「隐患」降级为「记录」。
  · 若存在**被改写/删除**的旧行 ⇒ 快照里的数字可能已被工具修正 ⇒ 必须重跑重封。

用法：./.venv/Scripts/python.exe scripts/_oneoff/_diag_skhy_derived_drift.py
"""
from __future__ import annotations

import difflib
import importlib.util
import io
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZIP = ROOT / "reports" / "SKHY" / "SKHY_20261011_102533" / "_source.zip"

spec = importlib.util.spec_from_file_location("ds", ROOT / "wb_analysis" / "_derive_stock.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)

with zipfile.ZipFile(ZIP) as z:
    ev_md = z.read("evidence/SKHY_2026-10-10.md").decode("utf-8")
    old_raw = z.read("evidence/SKHY_2026-10-10.derived.md").decode("utf-8")

# 旧快照的正文（去掉 md 包装）
old_body = old_raw.split("```\n", 1)[1].rsplit("\n```", 1)[0] + "\n"

# 新工具的 stdout（证据包按字节落盘，避免 CRLF 翻译破坏 series() 解析）
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "SKHY_2026-10-10.md").write_bytes(ev_md.encode("utf-8"))
    ds.EV = Path(tmp)
    buf = io.StringIO()
    with redirect_stdout(buf):
        ds.report("SKHY", "2026-10-10")
    new_body = buf.getvalue()

old_lines = old_body.splitlines()
new_lines = new_body.splitlines()

# 判据一：旧行是否**全部**在新输出中按原顺序出现（= 纯新增）
sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
ops = sm.get_opcodes()
only_insert = all(tag in ("equal", "insert") for tag, *_ in ops)
deleted = [old_lines[i1:i2] for tag, i1, i2, *_ in ops if tag in ("delete", "replace")]

print(f"旧快照 {len(old_lines)} 行 → 新输出 {len(new_lines)} 行（差 {len(new_lines) - len(old_lines):+d}）")
print(f"opcodes: {[t for t, *_ in ops]}")
print()
if only_insert:
    print("✓ 差异**纯属新增**：旧快照的每一行都原样保留在新输出中")
    print("  ⇒ 封存报告引用的**每一个数字都仍然成立**，不缺任何证据。")
    print("  ⇒ 结论：**不需要重跑重封**；「不可复现」仅指多了一段告警，不是数字漂移。")
else:
    print(f"✗ 存在被改写/删除的旧行（{len(deleted)} 段）：")
    for seg in deleted[:10]:
        for l in seg[:6]:
            print("   -", l)
    print("  ⇒ 旧快照的数字可能已被工具修正，**必须重跑重封**。")

print("\n—— 新增段预览 ——")
added = [new_lines[i1:i2] for tag, _, _, i1, i2 in ops if tag == "insert"]
for seg in added:
    for l in seg[:8]:
        print("   +", l)
sys.exit(0 if only_insert else 1)
