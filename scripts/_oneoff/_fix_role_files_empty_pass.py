# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_role_files_empty_pass.py
"""修 `_check_role_files.py`：**空草稿目录被判「通过」**（本日第 9 例，已实测复现）。

## 复现（实测）
```
① 造真实空目录 wb_analysis/drafts/ZZPROBE_EMPTY_2026-01-01
② _check_role_files.py → rc=0      输出：「（尚无角色文件）／总计问题项: 0」
③ _verify_ratings.py   → rc=1      输出：「结论：✗ 存在 12 项问题」（列出 12 个缺失角色文件）
```
⇒ **同一交付物，两个门禁给出相反结论。**

## 根因
`if not files: print("（尚无角色文件）")` —— 只提示、**不计入 `bad`**，
最后 `return 1 if bad else 0` ⇒ `bad == 0` ⇒ **rc=0（通过）**。
⇒ 后果：若调用方误用本脚本（或草稿被清空后误跑），**一个角色文件都没有也能过检**。

## 修法
「没有任何角色文件」**是缺陷，不是中性状态** —— 与 `_verify_ratings.py` 对齐，
计入 `bad`。同时把「空目录」与「目录不存在」都明确说清（后者原本已计入）。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "wb_analysis" / "_check_role_files.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_role_files_empty_pass_20261016.py"

OLD = '''        if not files:
            print("  （尚无角色文件）")'''

NEW = '''        if not files:
            # ★★ 2026-10-16 修（本日第 9 例「检查器判据缺陷」，**已实测复现**）：
            #   原实现只打印提示、**不计入 `bad`** ⇒ 末尾 `return 1 if bad else 0` 得到 0
            #   ⇒ **空草稿目录被判「通过」**。
            #   实测与 `_verify_ratings.py` 冲突：同一空目录
            #     · 本脚本            → rc=0（通过）
            #     · `_verify_ratings` → rc=1（列出 12 个缺失角色文件）
            #   ⇒ 「同一交付物、两个门禁结论相反」，正是本项目最反对的口径漂移。
            #   ⇒ 「零个角色文件」是**缺陷**而非中性状态：交付物本应含 12 个角色文件。
            print("  ✗ 无任何角色文件（交付物应含 12 个角色文件）")
            bad += 1
            continue'''

EDITS = [("空草稿目录：计入 bad（与 _verify_ratings 对齐）", OLD, NEW)]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "交付物应含 12 个角色文件" in src:
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
