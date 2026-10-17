# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe scripts/_tidy_scripts.py [--check|--apply|--new 名字 --serves 标的 日期]
"""全项目脚本生命周期管理：覆盖 `quant/` · `wb_analysis/` · `scripts/` 三个代码目录。

## 要解决的问题
临时探针与长期工具**从文件名和内容上看不出区别**，于是目录只增不减、没人敢删。
本工具让每个 `.py` 都必须声明自己的身份，并按身份归位。

## 生命周期（写在文件头部注释里，`ast` 解析不受影响）
    # lifecycle: reusable | maintenance | oneoff
    # created: YYYY-MM-DD
    # serves: <标的> <日期>      （仅 oneoff 需要）
    # usage: <命令行>

| 身份 | 含义 | 归位 |
|---|---|---|
| `reusable` | 每次分析都可能用到 | 留在原目录 |
| `maintenance` | 门禁 / 清理 / 索引 / 健康检查 | 留在原目录 |
| `oneoff` | 为某次结论临时写的探针（**是审计线索，不删**） | 移入同级 `_oneoff/` |

**豁免**：`__init__.py`（包标记）与 `conftest.py`（pytest 配置）不是脚本 ⇒ 显式豁免并在输出里标注，**不静默跳过**。

## 用法
  ./.venv/Scripts/python.exe scripts/_tidy_scripts.py --check      # 门禁：有未声明即失败
  ./.venv/Scripts/python.exe scripts/_tidy_scripts.py --report     # 打印分布
  ./.venv/Scripts/python.exe scripts/_tidy_scripts.py --apply       # 归位 + 生成 docs/TOOLS.md
  ./.venv/Scripts/python.exe scripts/_tidy_scripts.py --new 探针名 --serves NFLX 2026-09-21
"""
import argparse
import ast
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 三个代码目录都参与生命周期管理（原先只覆盖 scripts/ ⇒ 那是"半套机制"）
DIRS = [ROOT / "quant", ROOT / "wb_analysis", ROOT / "scripts"]
SELF = Path(__file__).name
VALID = {"reusable", "maintenance", "oneoff"}
EXEMPT = {"__init__.py", "conftest.py"}
INDEX = ROOT / "docs" / "TOOLS.md"

TEMPLATE = '''"""__PURPOSE__

lifecycle: oneoff
created: __DATE__
serves: __SERVES__
"""
# lifecycle: oneoff
# created: __DATE__
# serves: __SERVES__
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/__NAME__ <参数>

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    print("[oneoff] __NAME__ 尚未实现")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def read_header(p: Path) -> dict:
    t = p.read_text(encoding="utf-8", errors="replace")[:2000]
    out = {}
    for key in ("lifecycle", "created", "serves", "usage"):
        m = re.search(rf"^#\s*{key}:\s*(.+)$", t, re.M)
        if m:
            out[key] = m.group(1).strip()
    return out


def scan() -> tuple[list[tuple[Path, dict]], list[Path], list[Path]]:
    tagged, untagged, exempt = [], [], []
    for d in DIRS:
        if not d.is_dir():
            continue
        for p in sorted(list(d.glob("*.py")) + list((d / "_oneoff").glob("*.py"))):
            if p.name == SELF:
                continue
            if p.name in EXEMPT:
                exempt.append(p)
                continue
            h = read_header(p)
            (tagged if h.get("lifecycle") in VALID else untagged).append(
                (p, h) if h.get("lifecycle") in VALID else p)
    tagged = [(p, h) for p, h in tagged]        # type: ignore[misc]
    untagged = [p for p in untagged if isinstance(p, Path)]
    return tagged, untagged, exempt


def doc_first_line(p: Path) -> str:
    try:
        d = ast.get_docstring(ast.parse(p.read_text(encoding="utf-8", errors="replace")))
    except Exception:  # noqa: BLE001
        return "（无法解析）"
    return (d or "（无文档字符串）").split("\n")[0][:68]


def write_index(tagged: list[tuple[Path, dict]], exempt: list[Path]) -> Path:
    groups: dict[str, list[tuple[Path, dict]]] = {"reusable": [], "maintenance": [], "oneoff": []}
    for p, h in tagged:
        groups[h["lifecycle"]].append((p, h))
    L = ["# 工具索引（自动生成，勿手改）", "",
         f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
         "- 覆盖目录：" + " · ".join(f"`{d.name}/`" for d in DIRS),
         "- **每个 `.py` 头部必须声明 `# lifecycle: reusable | maintenance | oneoff`**；",
         "  新增探针用 `scripts/_tidy_scripts.py --new <名字> --serves <标的> <日期>` 生成。", "",
         "| 身份 | 含义 | 归位 |", "|---|---|---|",
         "| `reusable` | 每次分析都可能用到 | 留在原目录 |",
         "| `maintenance` | 门禁 / 清理 / 索引 / 健康检查 | 留在原目录 |",
         "| `oneoff` | 为某次结论临时写的探针（**审计线索，不删**） | 移入同级 `_oneoff/` |", ""]
    for key, title, note in (
        ("reusable", "reusable —— 每次分析都可能用到", ""),
        ("maintenance", "maintenance —— 项目维护（门禁 / 清理 / 索引）", ""),
        ("oneoff", "oneoff —— 为某次结论临时写的探针",
         "> **`_oneoff/` 是收件箱**：探针服务的那一轮交付并封存后，会**随案卷进 "
         "`reports/<标的>/<时间戳>/_source.zip`**，`_oneoff/` 于是回到空 —— **看到它空是正常的**。"),
    ):
        L += ["", f"## {title}", ""]
        if note:
            L += [note, ""]
        L += ["| 文件 | 用途 | 用法 / 服务于 |", "|---|---|---|"]
        items = sorted(groups[key], key=lambda x: x[0].as_posix())
        if not items:
            L.append("| （空） | — | — |")
        for p, h in items:
            extra = h.get("serves") or h.get("usage") or "—"
            L.append(f"| `{p.relative_to(ROOT).as_posix()}` | {doc_first_line(p)} | {extra} |")
    L += ["", "## 豁免（不是脚本，无需声明）", "", "| 文件 | 原因 |", "|---|---|"]
    for p in sorted(exempt):
        L.append(f"| `{p.relative_to(ROOT).as_posix()}` | 包标记 / pytest 配置 |")
    L += ["", "> 规则：探针若**第二次被复用**，就补文档 + `# usage:` 提升为 `reusable` —— **复用即升级**。", ""]
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    return INDEX


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--new", default=None, metavar="NAME")
    ap.add_argument("--serves", default="")
    args = ap.parse_args()

    if args.new:
        d = ROOT / "scripts" / "_oneoff"
        d.mkdir(parents=True, exist_ok=True)
        name = args.new if args.new.endswith(".py") else f"{args.new}.py"
        p = d / name
        if p.exists():
            print(f"✗ 已存在：{p.relative_to(ROOT).as_posix()}")
            return 1
        p.write_text(
            TEMPLATE.replace("__NAME__", name).replace("__DATE__", datetime.now().strftime("%Y-%m-%d"))
                    .replace("__SERVES__", args.serves or "（待填）")
                    .replace("__PURPOSE__", "一行说明这个探针要回答什么问题。"),
            encoding="utf-8", newline="\n")
        print(f"✓ 已生成 {p.relative_to(ROOT).as_posix()}")
        return 0

    tagged, untagged, exempt = scan()
    misplaced = [p for p, h in tagged if h["lifecycle"] == "oneoff" and p.parent.name != "_oneoff"]
    if args.check:
        if untagged:
            print(f"✗ {len(untagged)} 个脚本缺少 `# lifecycle:` 声明：")
            for p in untagged:
                print(f"    {p.relative_to(ROOT).as_posix()}")
            print("  ⇒ 补声明（reusable / maintenance / oneoff）后重试。")
            return 1
        if misplaced:
            print(f"✗ {len(misplaced)} 个 oneoff 脚本尚未移入 `_oneoff/` 目录：")
            for p in misplaced:
                print(f"    {p.relative_to(ROOT).as_posix()}")
            print("  ⇒ 跑 `scripts/_tidy_scripts.py --apply` 归位。")
            return 1
        print(f"✓ 全部 {len(tagged)} 个脚本均已声明生命周期"
              f"（豁免 {len(exempt)}：{', '.join(p.name for p in exempt)}）")
        return 0

    by_dir: dict[str, dict[str, int]] = {}
    for p, h in tagged:
        d = p.relative_to(ROOT).parts[0]
        by_dir.setdefault(d, {})
        by_dir[d][h["lifecycle"]] = by_dir[d].get(h["lifecycle"], 0) + 1
    print("=" * 88)
    print("脚本生命周期分布")
    print("=" * 88)
    for d in sorted(by_dir):
        print(f"  {d:14s} " + " · ".join(f"{k}={v}" for k, v in sorted(by_dir[d].items())))
    print(f"  豁免 {len(exempt)}：{', '.join(p.name for p in exempt)}")
    if untagged:
        print(f"\n  ★ 未声明 {len(untagged)} 个：")
        for p in untagged:
            print(f"      {p.relative_to(ROOT).as_posix()}")

    if args.apply:
        moved = 0
        for p, h in tagged:
            if h["lifecycle"] == "oneoff" and p.parent.name != "_oneoff":
                dst_dir = p.parent / "_oneoff"
                dst_dir.mkdir(exist_ok=True)
                dst = dst_dir / p.name
                shutil.copy2(p, dst)
                if dst.stat().st_size == p.stat().st_size:
                    p.unlink()
                    moved += 1
                    print(f"  → 移入 {dst.relative_to(ROOT).as_posix()}")
        if moved == 0:
            print("  （无需移动：oneoff 都已在 _oneoff/ 或不存在）")
        tagged2, _, exempt2 = scan()
        out = write_index(tagged2, exempt2)
        print(f"\n[索引] 已写入 {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
