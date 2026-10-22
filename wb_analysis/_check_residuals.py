# lifecycle: reusable
# created: 2026-10-02
# usage: ./.venv/Scripts/python.exe wb_analysis/_check_residuals.py <草稿目录>
#        ./.venv/Scripts/python.exe wb_analysis/_check_residuals.py --all
"""订正残留检查：防止「改了上游、忘了回头清下游」。

## 为什么需要它

本项目允许（且鼓励）上游订正——简报写错、代码措辞写错、算术手滑，都会被下游发现。
但**订正只改一处，下游已经落盘的文件不会自动跟着变**。实测已发生 3 次：

| # | 订正位置 | 残留位置 |
|---|---|---|
| 1 | `0_brief.md` §1.4「MACD 跌破零轴」→「下穿信号线」 | `1_analysts/sentiment.md` §6.1 |
| 2 | 同上 | `1_analysts/news.md` §5 |
| 3 | `0_brief.md` §1.1「跳空 −5.02%」→「−5.365%」 | `1_analysts/sentiment.md` §3.1 |

**为什么门禁抓不到**：`_lint_drafts.py` 检查的是契约（评级词/截断/篇幅/可溯源数字），
**不检查「这个数字/措辞是否已被上游推翻」**。而对不上的那个值往往本身是"可溯源"的
（它确实在某一版的简报里写过）。

## 机制

每个草稿目录下维护一个 `_corrections.json`：

```json
{
  "corrections": [
    {"old": "−5.02%", "new": "−5.365%",
     "note": "简报 §1.1 跳空幅度订正（71.27 ÷ 75.31 − 1）", "fixed_in": ["0_brief.md"]}
  ]
}
```

本脚本扫描该目录下**所有 `.md`**（排除 `_stale`/`_archive`），报告每一个 `old` 的命中：

- 命中文件在 `fixed_in` 里 ⇒ **豁免**（那是订正后的正文，括号里为了留痕本来就会写旧值）。
- 命中文件不在 `fixed_in` 里 ⇒ **告警**（十有八九是未同步的下游残留）。

⚠️ **留痕文本会天然包含旧值**。所以判定基准是「**在哪个文件里命中**」而不是「命中几次」——
`fixed_in` 的写法就是用来区分「刻意留痕」与「忘记清理」的。若某文件的留痕段需要引用旧值，
把它也加进 `fixed_in`。

## 退出码
0 = 无未同步残留；1 = 有（阻断交付，与 `_lint_drafts.py` 同语义）。
"""
import io
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ★ 2026-10-10：归档跳过表原为本地字面量，与 `_lint_drafts` / `_audit_values` /
#   `_check_role_files` 各持一份 ⇒ 单一来源 `wb_analysis/_paths.py`。
from wb_analysis._paths import SKIP_ARCHIVE_DIRS  # noqa: E402

SKIP_DIRS = SKIP_ARCHIVE_DIRS
SKIP_NAMES = ("_constraints.md", "_corrections.json")

# ⚠️ 2026-10-02 二次修正（判别力）：首版只看「哪个文件命中」，于是把
#    熊派/研究经理在**登记订正**时对旧值的**引用**误判为「未同步残留」。
#    实测：GOOG bear.md 的 CF-2 行、GOOG manager.md 的 CF-2/CF-4 行、
#    NFLX manager.md 的冲突登记段，全部含旧值但全部是合法留痕。
#    ⇒ 改为**按行判别**：命中行若带订正标记 ⇒ 归为「引用」；否则 ⇒ 归为「疑似残留」。
#    只有「疑似残留」才阻断。这样既不会静默放过，也不会把留痕当违规。
MARK_RE = re.compile(
    r"订正|修正|原写|原为|原值|残留|旧值|旧表述|已改为|口径差异|标记为错|"
    r"🔧|CF-\d|不复述|沿用|未更新|应订正|为错"
)


def _classify(line: str) -> str:
    return "引用" if MARK_RE.search(line) else "疑似残留"



def check(draft: Path) -> int:
    reg = draft / "_corrections.json"
    if not reg.exists():
        print(f"[残留检查] {draft.name}: 无 _corrections.json ⇒ 跳过（本目录未登记任何订正）")
        return 0
    data = json.loads(reg.read_text(encoding="utf-8"))
    items = data.get("corrections", [])
    if not items:
        print(f"[残留检查] {draft.name}: 订正表为空 ⇒ 通过")
        return 0

    files = [p for p in sorted(draft.rglob("*.md"))
             if not any(s in p.as_posix() for s in SKIP_DIRS) and p.name not in SKIP_NAMES]
    bad_total = 0
    print(f"[残留检查] {draft.name}: {len(items)} 条订正 × {len(files)} 个文件")
    for it in items:
        old, new, note = it.get("old", ""), it.get("new", ""), it.get("note", "")
        fixed_in = set(it.get("fixed_in", []))
        residual, quoted = [], []
        for f in files:
            rel = f.relative_to(draft).as_posix()
            for ln, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
                if old and old in line:
                    # ★ 2026-10-15 修：原写 `if (rel in fixed_in or _classify(line))`，
                    #   而 `_classify(line)` 返回非空字符串 `"疑似残留"`，在布尔上下文中恒为 True，
                    #   导致任何残留都被判为「引用」（100% 假阴性空转）。改为显式比对 `== "引用"`。
                    kind = "引用" if (rel in fixed_in or _classify(line) == "引用") else "疑似残留"
                    (quoted if kind == "引用" else residual).append(
                        (rel, ln, line.strip()[:96]))
        if residual:
            bad_total += len(residual)
            print(f"  ✗ 「{old}」→「{new}」  疑似残留 {len(residual)} 处（命中行无订正标记）：")
            for rel, ln, snippet in residual:
                print(f"      {rel}:L{ln}  {snippet}")
        else:
            print(f"  ✓ 「{old}」→「{new}」  无未同步残留"
                  f"（引用性命中 {len(quoted)} 处，均已识别为留痕/登记）")
            for rel, ln, _ in quoted[:4]:
                print(f"      · {rel}:L{ln}（引用）")
        if note:
            print(f"      订正说明：{note}")

    if bad_total:
        print(f"  ⇒ ✗ 存在 {bad_total} 处**未同步的下游残留**（退出码 1）")
        return 1
    print("  ⇒ ✓ 无未同步残留")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "--all":
        dirs = [d for d in sorted((ROOT / "wb_analysis/drafts").iterdir())
                if d.is_dir() and d.name != "_oneoff"]
    else:
        dirs = [(ROOT / a).resolve() if not Path(a).is_absolute() else Path(a) for a in args]

    worst = 0
    for d in dirs:
        if not d.is_dir():
            print(f"[残留检查] {d} 不是目录 ⇒ 跳过")
            continue
        worst = max(worst, check(d))
        print()
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
