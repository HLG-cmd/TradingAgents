# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_checker_blindspots.py
"""修 `scripts/_health.py` 中两处**同族**判据缺陷（本日第 5、6 例）。

## 本日「检查器判据缺陷」家族（全部已实测复现）
| # | 检查器 | 缺陷 | 方向 |
|---|---|---|---|
| 1 | `_audit_values.SUM_RE` | 正则恒不命中 | 假绿 |
| 2 | `chk_lifecycle` | `strip().startswith("    ")` 恒为假 | 假绿 |
| 3 | `chk_root_clean` | 后缀白名单把新类型挡在视野外 | 假绿 |
| 4 | `_memory_index --check` | 全等比较含时间戳 ⇒ 恒报过期 | 假红 |
| 5 | **`chk_gitignore`** | **纯子串判据：注释掉的条目也算「已忽略」** | **假绿** |
| 6 | **`chk_seal`** | **正则不命中时 `n=0` ⇒ 解析失败被当成「无待封存」** | **假绿** |

## 修法
**⑤ `chk_gitignore`**：判据从「子串是否出现」改为「**去掉注释后**是否仍作为有效规则存在」。
   **实证**：把 4 条必需项注释掉后 `git check-ignore` 返回 1（不再忽略），
   而原检查器仍报 PASS ⇒ 瞬态文件可能被 `git add` 进去。

**⑥ `chk_seal`**：解析失败**不得**默认成「0 轮」——
   改为**报 WARN 并要求人工确认**（`无法解析 _seal_run --plan 输出`）。
   原则：**「没解析到」≠「没问题」**（与铁律 3「静默失败」同源）。

⚠️ 只做精确替换 + `ast` 校验；改后必须双向实测（坏输入必检出 / 好输入不误报）。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "scripts" / "_health.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_checker_blindspots_20261016.py"

NL = chr(10)

# ── 修复 ⑤ chk_gitignore ──
OLD_GI = '''def chk_gitignore() -> tuple[str, str]:
    f = ROOT / ".gitignore"
    if not f.exists():
        return "WARN", "无 .gitignore"
    t = f.read_text(encoding="utf-8", errors="replace")
    need = ["wb_analysis/evidence/", "wb_analysis/drafts/", "wb_analysis/analysis/",
            ".workbuddy-ai/backup/"]
    miss = [n for n in need if n not in t]
    return ("PASS", "瞬态目录与回滚包均已忽略") if not miss else \\
           ("WARN", f"未忽略：{', '.join(miss)}")'''

NEW_GI = '''def chk_gitignore() -> tuple[str, str]:
    """瞬态目录与回滚包是否真被 git 忽略。

    ★★ 2026-10-16 修（本日第 5 例「检查器判据缺陷」，实测复现）：
    原判据是**纯子串** `n not in t`（`t` = 全文）⇒
    **把条目注释掉后，注释行里仍含该子串 ⇒ 照样报 PASS**。

    实证：把 4 条必需项全部写成 `# wb_analysis/evidence/` 后，
    `git check-ignore -v wb_analysis/evidence/x.md` 返回 **1（不再忽略）**
    —— 瞬态文件此时可被 `git add` 进去，而体检仍报「均已忽略」= **假绿**。

    ⇒ 判据改为：**先剥掉注释（`#` 之后）与空行，再逐条比对有效规则**。
      并额外用 `git check-ignore` 做一次**功能性断言**（真正的判据是 git 的行为，
      不是文本形态）—— 这是把「文本检查」升级为「行为检查」。
    """
    f = ROOT / ".gitignore"
    if not f.exists():
        return "WARN", "无 .gitignore"

    # ① 文本层：剥注释后逐条比对（注释行不算数）
    active: set[str] = set()
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            active.add(s)
    need = ["wb_analysis/evidence/", "wb_analysis/drafts/", "wb_analysis/analysis/",
            ".workbuddy-ai/backup/"]
    miss = [n for n in need if n not in active]
    if miss:
        return "WARN", f"未忽略（注释掉的不算）：{', '.join(miss)}"

    # ② 行为层：让 git 自己回答（真正的判据）—— 用一个必然匹配的探针路径
    probe = "wb_analysis/evidence/__probe__.md"
    # ⚠️ `run()` 已内置 `cwd=ROOT` 且签名不含 cwd ⇒ 不要多传。（多传会 TypeError）
    rc, out = run(["git", "check-ignore", "-v", probe])
    if rc != 0:
        return ("WARN", f"{len(need)} 条规则文本存在，但 `git check-ignore` 判定**未忽略**"
                       f"（rc={rc}）⇒ 规则可能被后面的 ! 反转或写法有误")
    return "PASS", "瞬态目录与回滚包均已忽略（文本规则 + git 行为双重确认）"'''

# ── 修复 ⑥ chk_seal ──
OLD_SEAL = '''def chk_seal() -> tuple[str, str]:
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_seal_run.py"), "--plan"])
    m = re.search(r"待封存\\s*(\\d+)\\s*轮", out)
    n = int(m.group(1)) if m else 0
    return ("PASS", "无待封存产物（瞬态目录已清）") if n == 0 else \\
           ("WARN", f"{n} 轮产物待封存：跑 _seal_run.py --all --apply")'''

NEW_SEAL = '''def chk_seal() -> tuple[str, str]:
    """是否有待封存产物。

    ★★ 2026-10-16 修（本日第 6 例「检查器判据缺陷」）：
    原判据 `n = int(m.group(1)) if m else 0` —— **正则不命中就当作「0 轮」**
    ⇒ 只要 `_seal_run.py --plan` 的输出格式一变（改措辞、加前缀、被警告截断），
    本检查就**静默报 PASS**，而实际可能堆着一批待封存产物。

    ⇒ 判据改为：**解析失败 ≠ 没问题**。取不到数字时报 WARN 并要求人工确认
    （与铁律 3「静默失败」同源：报成功 + 外观正常 ≠ 真的没问题）。
    """
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_seal_run.py"), "--plan"])
    m = re.search(r"待封存\\s*(\\d+)\\s*轮", out)
    if not m:
        return "WARN", ("无法解析 `_seal_run.py --plan` 的输出 ⇒ **不能假定为 0**，"
                        "请人工确认；首行："
                        + (out.strip().splitlines()[0][:60] if out.strip() else "(空输出)"))
    n = int(m.group(1))
    return ("PASS", "无待封存产物（瞬态目录已清）") if n == 0 else \\
           ("WARN", f"{n} 轮产物待封存：跑 _seal_run.py --all --apply")'''

EDITS = [
    ("⑤ chk_gitignore：剥注释 + git 行为双重判据", OLD_GI, NEW_GI),
    ("⑥ chk_seal：解析失败不再默认 0", OLD_SEAL, NEW_SEAL),
]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")

    if "文本规则 + git 行为双重确认" in src and "不能假定为 0" in src:
        print("  · 两处均已修（幂等跳过）")
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
