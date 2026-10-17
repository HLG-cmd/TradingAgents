# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_diag_role_files_empty.py
"""甄别：`_check_role_files.py` 在「目录存在但无角色文件」时 rc=0 是否**真 bug**。

## 疑点（来自对抗性实测）
传一个**空目录**给它 → rc=0（判通过），而 `_verify_ratings.py` 对同类输入 rc=1（判失败）。
⇒ **两个检查器对同一输入给出相反结论** = 本项目最反对的「同一口径两处写、必然漂移」。

## 但先要排除探针缺陷
上一轮我传的是**临时绝对路径**。`Path(DRAFTS) / "<绝对路径>"` 在 pathlib 里会**变成那个绝对路径**
⇒ `is_dir()` 为真 ⇒ 走「目录存在但无文件」分支 ⇒ rc=0。
这**不是**我误传导致的，而是**真实行为**：目录存在但空，它就判通过。

## 判据
用**真实 `drafts/` 下的空子目录**复现（而非临时路径），确认行为一致 ⇒ 判为真 bug。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
DRAFTS = ROOT / "wb_analysis" / "drafts"


def run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT), timeout=180)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    name = "ZZPROBE_EMPTY_2026-01-01"
    d = DRAFTS / name

    print("=" * 92)
    print("甄别：空草稿目录下两个检查器结论是否相反")
    print("=" * 92)

    try:
        d.mkdir(parents=True, exist_ok=True)
        print(f"\n① 造真实空目录：{d.relative_to(ROOT)}")

        rc1, o1 = run([PY, str(ROOT / "wb_analysis" / "_check_role_files.py"), name])
        print(f"\n② _check_role_files.py → rc={rc1}")
        print("   输出尾部：", " | ".join(o1.strip().splitlines()[-3:])[:200])

        rc2, o2 = run([PY, str(ROOT / "wb_analysis" / "_verify_ratings.py"), str(d)])
        print(f"\n③ _verify_ratings.py  → rc={rc2}")
        print("   输出尾部：", " | ".join(o2.strip().splitlines()[-3:])[:200])

        print("\n④ 判定")
        if rc1 == 0 and rc2 != 0:
            print("   ✗ **真 bug（口径不一致）**：")
            print("      · `_check_role_files` 对空草稿判「通过」（rc=0）")
            print("      · `_verify_ratings`  对同一输入判「失败」（rc≠0）")
            print("      ⇒ 同一交付物，两个门禁给出**相反结论**。")
            print("      ⇒ 风险：误用 `_check_role_files` 时，**一个角色文件都没有的草稿也能过检**。")
            return 2
        print("   ⇒ 结论一致或均合理，非 bug")
        return 0
    finally:
        # 清理：自深到浅 rmdir
        if d.exists():
            for sub in sorted([x for x in d.rglob("*") if x.is_dir()],
                              key=lambda x: len(x.parts), reverse=True):
                try:
                    sub.rmdir()
                except OSError:
                    pass
            try:
                d.rmdir()
                print(f"\n（已清理探针目录 {name}）")
            except OSError as e:
                print(f"\n⚠ 清理失败：{e}")


if __name__ == "__main__":
    raise SystemExit(main())
