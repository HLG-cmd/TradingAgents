# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_memory_index_check.py
"""修 `scripts/_memory_index.py` 的两处缺陷（本脚本用「读取替换块 → 精确替换」方式）。

## Bug 1：`--check` 恒报「已过期」（检查器恒假）
**现象**：刚跑完生成命令，立刻 `--check` 仍报「已过期」。
**根因**：判据是 `INDEX.read_text() != content` **全等比较**，而 `content` 里含
「生成时间：<now>」—— 时间戳每次都不同 ⇒ **永远不可能相等**。
实测：连续两次 `render()` 输出完全相同，与磁盘文件的差异行**只有时间戳那一行**。
**修法**：比较前**剔除时间戳行**；时间戳只作展示，不参与一致性判断。

## Bug 2：硬编码「58 条铁律」与实际不符
铁律实际条数会随追加变化（现为 51）⇒ 硬编码计数必然漂移。
**修法**：改为「条数以该文件自报为准」，不再写死数字（项目原则：不写会漂移的数字）。

⚠️ 用落盘脚本而非 heredoc —— 补丁含 `\\n` 等转义，内联进 shell 会被静默改写（铁律 21/22/29）。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "scripts" / "_memory_index.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_memory_index_check_20261016.py"

NEWLINE = chr(10)

OLD_CHECK = (
    "    if args.check:" + NEWLINE
    + "        if not INDEX.exists():" + NEWLINE
    + '            print("✗ _INDEX.md 不存在 ⇒ 跑 `scripts/_memory_index.py` 生成")' + NEWLINE
    + "            return 1" + NEWLINE
    + '        if INDEX.read_text(encoding="utf-8") != content:' + NEWLINE
    + '            print("✗ _INDEX.md 已过期（记忆有更新）⇒ 重跑 `scripts/_memory_index.py`")' + NEWLINE
    + "            return 1"
)

NEW_CHECK = (
    "    if args.check:" + NEWLINE
    + "        if not INDEX.exists():" + NEWLINE
    + '            print("✗ _INDEX.md 不存在 ⇒ 跑 `scripts/_memory_index.py` 生成")' + NEWLINE
    + "            return 1" + NEWLINE
    + "        # ★★ 2026-10-16 修（**检查器恒假**）：原判据是全等比较，而 content 含" + NEWLINE
    + "        #   「生成时间：<now>」—— 时间戳每次都不同 ⇒ **刚生成完也恒报「已过期」**" + NEWLINE
    + "        #   （实测：连续两次 render 相同，与磁盘差异只有时间戳那一行）。" + NEWLINE
    + "        #   与铁律 49「检查器判据缺陷会伪装成没问题」同族，方向相反（这次是恒报错）。" + NEWLINE
    + "        #   ⇒ 比较前剔除时间戳行；时间戳只作展示，不参与一致性判断。" + NEWLINE
    + "        def _strip_ts(s: str) -> str:" + NEWLINE
    + '            return "' + NEWLINE.replace(NEWLINE, "\\n") + '".join(' + NEWLINE
    + "                line for line in s.splitlines()" + NEWLINE
    + '                if not line.startswith("- 生成时间："))' + NEWLINE
    + "        if _strip_ts(INDEX.read_text(encoding=\"utf-8\")) != _strip_ts(content):" + NEWLINE
    + '            print("✗ _INDEX.md 已过期（记忆有更新）⇒ 重跑 `scripts/_memory_index.py`")' + NEWLINE
    + "            return 1"
)

EDITS = [
    ("Bug1 --check 恒报过期（剔除时间戳后再比较）", OLD_CHECK, NEW_CHECK),
    ("Bug2a 文档串里的硬编码条数",
     "  · `IRONLAWS.md`    —— 58 条铁律的单行索引（只收已被提炼成铁律的）",
     "  · `IRONLAWS.md`    —— 铁律全文 + 单行索引（只收已被提炼成铁律的；条数以该文件自报为准）"),
    ("Bug2b 渲染输出里的硬编码条数",
     '        "| `IRONLAWS.md` | **58 条铁律全文 + 单行索引**（已被提炼成判据的那部分） |",',
     '        "| `IRONLAWS.md` | **铁律全文 + 单行索引**（已被提炼成判据的那部分；条数以该文件自报为准） |",'),
]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")

    if "_strip_ts" in src:
        print("  · 已修过（幂等跳过）")
        return 0

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    print(f"  ↺ 已备份 → {BACKUP.name}")

    for tag, old, new in EDITS:
        if old not in src:
            print(f"  ✗ 未命中：{tag}")
            print("     ⇒ 未做任何写入，文件保持原样")
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
