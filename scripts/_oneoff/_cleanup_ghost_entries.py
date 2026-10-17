# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_cleanup_ghost_entries.py [--apply]
"""让 git 索引与磁盘一致：把 55 个「已跟踪但磁盘不存在」的幽灵条目 stage 删除。

## 本操作**不删任何数据**
这些文件**早已不在磁盘上**（是 `.workbuddy/` → `.workbuddy-ai/` 改名、
以及脚本归位到 `_oneoff/` 之后遗留的索引条目）。
本操作只是**让 git 知道它们不在了**，从而：
  · 别人克隆后不再出现「已删除未提交」的满屏红；
  · `git status` 恢复干净。

## 安全规程（项目铁律：删前打包 + 逐项校验，不通过即中止）
1. **先记录清单**（`.workbuddy-ai/backup/ghost_entries_<date>.json`）：
   每项记录 `path` + 分类 + **内容长度**（搬迁类记新路径，真删除类从历史取长度）；
2. **逐项校验**：清单条目数 == `git ls-files --deleted` 数；每项可恢复；
3. **通过才执行** `git rm --cached`（只改索引，不动磁盘）；
4. 执行后**复查** `git ls-files --deleted` 应为 0。

⚠️ 用 `git rm --cached` 而非 `git rm`：后者会尝试删文件，而这些文件本就不存在。
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLY = "--apply" in sys.argv
BACKUP = ROOT / ".workbuddy-ai" / "backup"


def git(*args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def build_manifest(ghosts: list[str]) -> list[dict]:
    items = []
    for g in ghosts:
        name = Path(g).name
        hits = [p for p in ROOT.rglob(name)
                if ".git" not in p.parts and "__pycache__" not in p.parts]
        if hits:
            items.append({"path": g, "kind": "moved",
                          "new_path": hits[0].relative_to(ROOT).as_posix()})
        else:
            rc, content = git("show", f"HEAD:{g}")
            items.append({"path": g, "kind": "deleted",
                          "hist_len": len(content) if rc == 0 else -1})
    return items


def main() -> int:
    rc, out = git("ls-files", "--deleted")
    ghosts = [l for l in out.splitlines() if l.strip()]
    print("=" * 96)
    print(f"幽灵条目清理：{len(ghosts)} 个")
    print("=" * 96)
    if not ghosts:
        print("  · 无幽灵条目（幂等跳过）")
        return 0

    # ── ① 记录清单 ──
    man = build_manifest(ghosts)
    BACKUP.mkdir(parents=True, exist_ok=True)
    mpath = BACKUP / f"ghost_entries_{datetime.now():%Y%m%d_%H%M%S}.json"
    mpath.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8", newline="\n")
    n_moved = sum(1 for x in man if x["kind"] == "moved")
    n_del = sum(1 for x in man if x["kind"] == "deleted")
    print(f"\n① 清单已记录 → {mpath.name}")
    print(f"   搬迁 {n_moved} ｜ 真删除 {n_del}")

    # ── ② 逐项校验 ──
    print("\n② 逐项校验")
    bad = []
    if len(man) != len(ghosts):
        bad.append(f"清单 {len(man)} ≠ 幽灵 {len(ghosts)}")
    for x in man:
        if x["kind"] == "moved":
            if not (ROOT / x["new_path"]).exists():
                bad.append(f"搬迁目标不存在：{x['new_path']}")
        else:
            if x.get("hist_len", -1) <= 0:
                bad.append(f"历史不可取或为空：{x['path']}")
    if bad:
        print(f"   ✗ 校验失败 {len(bad)} 项 ⇒ **中止**，未改索引")
        for b in bad[:8]:
            print(f"      {b}")
        return 1
    print(f"   ✓ 全部通过（{len(man)} 项均可恢复到已知位置/历史）")

    if not APPLY:
        print("\n（未加 --apply：仅预演，未改索引）")
        return 0

    # ── ③ 执行（只改索引）──
    print("\n③ 执行 git rm --cached（只改索引，不动磁盘）")
    rc2, out2 = git("rm", "--cached", "--quiet", *ghosts)
    if rc2 != 0:
        print(f"   ✗ 执行失败：{out2.strip()[:200]}")
        return 1
    print(f"   ✓ 已 stage 删除 {len(ghosts)} 项")

    # ── ④ 复查 ──
    rc3, out3 = git("ls-files", "--deleted")
    left = [l for l in out3.splitlines() if l.strip()]
    print(f"\n④ 复查：剩余幽灵条目 {len(left)} 个 {'✓' if not left else '✗'}")
    for l in left[:5]:
        print(f"      {l}")
    return 0 if not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
