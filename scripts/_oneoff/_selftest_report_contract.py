# lifecycle: oneoff
# created: 2026-10-11
# serves: （门禁双侧自检，无标的）
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_selftest_report_contract.py
"""O8 双侧验证：合成报告的契约门禁。

- 阳性夹具：往 `complete_report.md` 注入一个越界五档词（模拟渲染环节引入）
            ⇒ 必须 FAIL（退出码 2，且报「≠ 6 席合计」）。
- 阴性夹具：干净树 ⇒ 必须 PASS（退出码 0）。

用法：./.venv/Scripts/python.exe scripts/_oneoff/_selftest_report_contract.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
CHECK = ROOT / "wb_analysis" / "_verify_report.py"
SRC_TREE = ROOT / "reports" / "SKHY" / "SKHY_20261011_102533"

failures: list[str] = []

if not SRC_TREE.is_dir():
    print(f"✗ 找不到基准树 {SRC_TREE}（本测试需要一个干净的真实交付树）")
    sys.exit(2)


def run_on(tree: Path) -> tuple[int, str]:
    p = subprocess.run([PY, str(CHECK), str(tree)], cwd=str(ROOT), capture_output=True)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace")


with tempfile.TemporaryDirectory() as tmp:
    # ── 阴性：干净副本 ──
    clean = Path(tmp) / "clean"
    shutil.copytree(SRC_TREE, clean)
    rc, out = run_on(clean)
    line = [l.strip() for l in out.splitlines() if "五档词席位" in l]
    print("═══ 阴性夹具：干净树 ═══")
    print("  " + (line[0] if line else "(未见席位行)"))
    ok = rc == 0
    print(f"  ⇒ 判定：{'PASS（通过）' if ok else f'FAIL（退出码 {rc}）'}")
    if not ok:
        failures.append(f"阴性夹具误报，退出码 {rc}")

    # ── 阳性：注入越界评级词（落在最后一行，不属于任何 6 席结论块）──
    dirty = Path(tmp) / "dirty"
    shutil.copytree(SRC_TREE, dirty)
    cr = dirty / "complete_report.md"
    cr.write_text(cr.read_text(encoding="utf-8") + "\n\n（渲染残留：本行不应出现 Buy 一词）\n",
                  encoding="utf-8", newline="\n")
    rc, out = run_on(dirty)
    print("\n═══ 阳性夹具：complete_report.md 注入越界 'Buy' ═══")
    hit = [l.strip() for l in out.splitlines() if "≠ 6 席合计" in l or "五档词席位" in l]
    for l in hit:
        print("  " + l)
    ok = rc == 2 and any("6 席合计" in l for l in hit)
    print(f"  ⇒ 判定：{'PASS（已阻断，退出码 2）' if ok else f'FAIL（退出码 {rc}）'}")
    if not ok:
        failures.append(f"阳性夹具未阻断，退出码 {rc}")

print("\n" + "=" * 60)
if failures:
    print("✗ 双侧验证失败：", "; ".join(failures))
    sys.exit(1)
print("✓ 双侧验证通过：越界词被阻断、干净树放行")
