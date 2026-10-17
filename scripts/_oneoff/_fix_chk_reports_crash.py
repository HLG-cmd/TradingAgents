# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_chk_reports_crash.py
"""修 `chk_reports` 的**崩溃假绿**（本日第 7 例同族缺陷，已实测复现）。

## 复现（实测）
把 `_reports_index.py` 换成「exit 3 + 打印垃圾」的桩后：
```
▸ 正常状态：PASS — 报告树 51 棵，无堆积问题
▸ 工具崩溃：PASS — 报告树 ? 棵，无堆积问题   ← 假绿！
```

## 根因
判据是 `n = len(含 "- [" 的行)`；`n == 0` 就 `return PASS`。
但 **`n == 0` 有两种含义**：
  · 真的没有卫生问题（正常）；
  · 工具崩了 / 没跑起来 ⇒ 一条问题条目都没输出（**同样 n == 0**）。
⇒ 两者在判据上**不可区分**，于是崩溃被读成「无问题」。

与铁律 3「静默失败」、以及 `test_precheck_gate.py` 里那条
「`crashed()` 能区分『工具崩了』与『工具检出了问题』」**完全同源** ——
那条测试守住了 `_precheck`，但 **`_health.chk_reports` 没有同样的保护**。

## 修法
**先验 rc，再看内容**：`rc != 0` ⇒ 直接 FAIL/WARN 并回显输出首行，
**不得**进入「n == 0 ⇒ PASS」分支。同时把「报告树 N 棵」解析失败也降级为 WARN
（原先静默显示 `?` 却仍 PASS）。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "scripts" / "_health.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_chk_reports_crash_20261016.py"

OLD = '''def chk_reports() -> tuple[str, str]:
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_reports_index.py"), "--check"])
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("- [")]
    n = len(lines)
    if n == 0:
        m = re.search(r"报告树\\s*(\\d+)\\s*棵", out)
        return "PASS", f"报告树 {m.group(1) if m else '?'} 棵，无堆积问题"'''

NEW = '''def chk_reports() -> tuple[str, str]:
    """报告层是否有堆积 / 孤儿 / 缺草稿。

    ★★ 2026-10-16 修（本日第 7 例「检查器判据缺陷」，**已实测复现**）：
    原判据把「0 条问题条目」直接当成「无问题」，但 **`n == 0` 有两种含义**：
      · 真的没有卫生问题（正常）；
      · **工具崩了 / 没跑起来 ⇒ 一条问题条目都没输出（同样 n == 0）**。
    ⇒ 两者不可区分 ⇒ **工具崩溃被读成「无问题」= 假绿**。

    实测：把 `_reports_index.py` 换成「exit 3 + 打印垃圾」的桩后，
    本函数仍返回 `PASS — 报告树 ? 棵，无堆积问题`。

    与铁律 3「静默失败」同族；`test_precheck_gate.py` 已为 `_precheck` 守住
    「崩溃 ≠ 检出问题」，但 **本检查当时没有同样的保护**。

    ⇒ 修法：**先验 rc，再看内容**。`rc != 0` 一律不得进 PASS 分支。
    """
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_reports_index.py"), "--check"])
    # ① 先验「工具是否真的跑成功」—— 崩溃时不得把「无输出」读成「无问题」
    if rc != 0:
        first = out.strip().splitlines()[0][:70] if out.strip() else "(无输出)"
        return "FAIL", f"`_reports_index.py --check` 未正常退出（rc={rc}）⇒ 无法判断，首行：{first}"
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("- [")]
    n = len(lines)
    if n == 0:
        m = re.search(r"报告树\\s*(\\d+)\\s*棵", out)
        if not m:
            # ② 连「报告树 N 棵」都解析不到 ⇒ 输出格式已变，不能假定为 0
            return "WARN", ("`_reports_index.py --check` 输出无法解析（未见「报告树 N 棵」）"
                            "⇒ **不能假定为 0 问题**，请人工跑一次确认")
        return "PASS", f"报告树 {m.group(1)} 棵，无堆积问题"'''

EDITS = [("chk_reports：先验 rc + 解析失败降级为 WARN", OLD, NEW)]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "未正常退出（rc=" in src and "不能假定为 0 问题" in src:
        print("  · 已修过（幂等跳过）")
        return 0
    if "未正常退出（rc=" in src:
        print("  · 已修过（幂等跳过）")
        return 0

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    print(f"  ↺ 已备份 → {BACKUP.name}")

    for tag, old, new in EDITS:
        if old not in src:
            print(f"  ✗ 未命中：{tag}")
            print("     ⇒ 未做任何写入")
            return 1
        src = src.replace(old, new, 1)
        print(f"  ✓ {tag}")

    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  ✗ ast 校验失败，未落盘：{e}")
        return 1
    TARGET.write_text(src, encoding="utf-8", newline="\n")
    print("  ✓ ast 校验通过，已落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
