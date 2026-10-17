# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_verify_ghost_entries.py
"""逐项核实 55 个「已跟踪但磁盘不存在」的条目 —— 内容是否都能找回？

## 为什么要逐项核实（项目铁律：删前打包 + 逐项校验，不通过即中止）
本操作**不是删数据**（文件早已不在磁盘），而是**让 git 索引与磁盘现实一致**。
但判据仍须严格：**每个条目必须满足下列之一，否则中止**：
  A. **已搬迁**：同名文件存在于新路径（内容还在，只是 git 按路径追踪 ⇒ 显示为删除）；
  B. **在历史里**：`git show HEAD:<path>` 能取出内容（可从历史恢复）。

## 分三类（处理方式不同）
| 类 | 特征 | 处置 |
|---|---|---|
| ① 搬迁 | 磁盘同类名存在于新路径 | stage 删除（内容在新路径） |
| ② 真删除 | 磁盘无同名，但历史里有 | stage 删除（历史可回溯） |
| ③ 待查 | 两者都不满足 | **中止并报告** |
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    rc, out = git("ls-files", "--deleted")
    ghosts = [l for l in out.splitlines() if l.strip()]
    print("=" * 100)
    print(f"逐项核实 {len(ghosts)} 个幽灵条目")
    print("=" * 100)

    cat1, cat2, cat3 = [], [], []
    for g in ghosts:
        name = Path(g).name
        # A：磁盘同类名（排除 git 内部与 pycache）
        hits = [p for p in ROOT.rglob(name)
                if ".git" not in p.parts and "__pycache__" not in p.parts]
        if hits:
            cat1.append((g, hits[0].relative_to(ROOT).as_posix()))
            continue
        # B：git 历史可取
        rc2, content = git("show", f"HEAD:{g}")
        if rc2 == 0 and content.strip():
            cat2.append((g, len(content)))
            continue
        cat3.append(g)

    print(f"\n▸ ① 已搬迁（内容在新路径）：{len(cat1)} 个")
    for g, new in cat1:
        print(f"    {g[:62]:62s} → {new[:34]}")

    print(f"\n▸ ② 真删除（可从 git 历史恢复）：{len(cat2)} 个")
    for g, n in cat2:
        print(f"    {g[:62]:62s} 历史 {n} 字符")

    print(f"\n▸ ③ 无法确认可恢复：{len(cat3)} 个")
    for g in cat3:
        print(f"    ✗ {g}")

    print()
    print("=" * 100)
    if cat3:
        print(f"✗ 有 {len(cat3)} 个条目无法确认可恢复 ⇒ **中止**，不得继续")
        return 1
    print(f"✓ 全部可确认：{len(cat1)} 搬迁 + {len(cat2)} 历史可回溯 = {len(ghosts)}")
    print("  ⇒ 可安全让 git 索引与磁盘一致（stage 删除）")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
