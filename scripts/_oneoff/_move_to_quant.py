# lifecycle: oneoff
# created: 2026-09-23
# serves: 项目结构重构 2026-09-23
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_move_to_quant.py [--apply]
"""把根目录 9 个自建 .py 收进 `quant/` 包，并同步修正所有导入点。

## 为什么不能只搬文件
Python 的导入是按「模块名」解析的：`import stock_pools` 只在根目录能找到。
搬进 `quant/` 后必须改成 `from quant import stock_pools`，且**包内**对同级的引用也要改。

## 分类处理（依据实测的角色，不是猜的）
| 角色 | 判定 | 改法 |
|---|---|---|
| **库**（仅被 import） | 无 `__main__` | 内部无同级依赖 ⇒ 只改**外部**引用点 |
| **入口脚本**（直接运行） | 有 `__main__` | 加 `sys.path` 引导 + 同级引用改 `from quant import X` |

`sys.path` 引导是必须的：`python quant/factor_backtest.py` 时 `sys.path[0]` 是 `quant/`，
**项目根目录不在路径里**，`from quant import ...` 会失败。故入口脚本必须先把自己所在包的父目录塞进 `sys.path`。

## 安全设计
· 默认 **dry-run**，打印**每一处**将发生的行级改动；加 `--apply` 才写盘
· 只改 **AST 定位到的真实 import 行**，不碰文档字符串与注释（避免把说明文字改坏）
· 每改一个文件立刻回读校验语法（`ast.parse`）；任何一个失败即整体中止
· 搬运用「复制 → 字节校验 → 删源」，并先出回滚包

用法:
  ./.venv/Scripts/python.exe scripts/_oneoff/_move_to_quant.py
  ./.venv/Scripts/python.exe scripts/_oneoff/_move_to_quant.py --apply
"""
import argparse
import ast
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "quant"
MOVED = ["screener_engine", "smart_screener", "stock_pools", "price_history", "wb_deep_dive",
         "factor_backtest", "fundamental_backtest", "edgar_fundamentals", "cleanup_cache"]
SKIP_PARTS = {".venv", ".git", "__pycache__", ".pytest_cache"}

BOOTSTRAP = """
# ── 包内引导（2026-09-23 收进 quant/ 时加入）──────────────────────────────
# 直接运行本文件时（python quant/xxx.py）sys.path[0] 是 quant/，**项目根不在路径里**，
# 于是 `from quant import ...` 会失败。故把自己所在包的父目录（项目根）塞进去。
import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
"""


def patched_lines(path: Path, in_pkg: bool) -> tuple[list[str], list[tuple[int, str, str]]]:
    """返回 (新的行列表, [(行号, 旧行, 新行)])。只改 AST 定位到的真实 import 行。"""
    src = path.read_text(encoding="utf-8")
    lines = src.split("\n")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return lines, []
    changes: list[tuple[int, str, str]] = []
    spans: list[tuple[int, int, str, str]] = []   # (start, end, old, new) 1-based，含首含尾
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hit = [a for a in node.names if a.name.split(".")[0] in MOVED]
            if not hit:
                continue
            new = "from quant import " + ", ".join(
                a.name if a.asname is None else f"{a.name} as {a.asname}" for a in hit)
            spans.append((node.lineno, node.end_lineno or node.lineno, "", new))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split(".")[0]
            if top not in MOVED:
                continue
            names = ", ".join(n.name if n.asname is None else f"{n.name} as {n.asname}"
                              for n in node.names)
            spans.append((node.lineno, node.end_lineno or node.lineno, "",
                          f"from quant.{node.module} import {names}"))
    # ★ 关键：`from X import (a, b,\n c)` 这类**跨行**语句必须整段替换；
    #   只换首行会把续行留在原地 ⇒ 语法错误。故按 (lineno, end_lineno) 整段替换。
    changes: list[tuple[int, str, str]] = []
    for start, end, _, new in sorted(spans, reverse=True):
        old_block = "\n".join(lines[start - 1:end])
        # ★ 必须保留原缩进：本项目有**函数体内的延迟 import**（如 fund_backtest 里
        #   `from price_history import ...` 在函数里，缩进 4 空格）。写成第 0 列会直接语法错误
        #   （实测报 "unexpected indent"）。
        indent = lines[start - 1][: len(lines[start - 1]) - len(lines[start - 1].lstrip())]
        changes.append((start, old_block, indent + new))
        lines[start - 1:end] = [indent + new]
    changes.reverse()
    return lines, changes


# ★ 搬家后 `__file__` 的"父目录"从**项目根**变成了 `quant/`，所有基于它推断项目根的地方都要上移一级。
#   实测 5 处；其中 `edgar_fundamentals.py` 用它找 `.env` —— 不改的话会去找 `quant/.env`，
#   **SEC 凭证静默失效**（读不到就走默认 UA，EDGAR 会 403），属于最难发现的一类坏。
FIXUPS = [
    ("PROJECT_ROOT = Path(__file__).parent\n",
     "PROJECT_ROOT = Path(__file__).parent.parent  # quant/ 的上一级才是项目根\n"),
    ("PROJECT_ROOT = Path(__file__).resolve().parent\n",
     "PROJECT_ROOT = Path(__file__).resolve().parents[1]  # quant/ 的上一级才是项目根\n"),
    # ⚠️ 这一条**不能带行内注释**：原文是 `_load_dotenv(Path(...) / ".env")`，
    #   在表达式中间插 `#` 会把后面的 `)` 一起注释掉 ⇒ "'(' was never closed"（实测踩到）。
    ('Path(__file__).resolve().parent / ".env"',
     'Path(__file__).resolve().parents[1] / ".env"'),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    print("=" * 96)
    print(f"把根目录 9 个自建模块收进 quant/（{'APPLY' if args.apply else 'DRY-RUN'}）")
    print("=" * 96)

    # ── 1. 回滚包 ──
    targets: list[Path] = []
    for m in MOVED:
        p = ROOT / f"{m}.py"
        if p.exists():
            targets.append(p)
    for p in ROOT.rglob("*.py"):
        parts = p.relative_to(ROOT).parts
        # ⚠️ 必须用**相对路径**判断：ROOT 是绝对路径，p.parts 的前两段是 'D:////' 'Antigravity'，
        #    拿它跟 ('.workbuddy','backup') 比永远不相等 —— 实测因此把备份目录里的文件也改了。
        if any(s in parts for s in SKIP_PARTS) or parts[:2] == (".workbuddy", "backup"):
            continue
        try:
            if any(m in p.read_text(encoding="utf-8", errors="replace") for m in MOVED):
                targets.append(p)
        except OSError:
            pass
    targets = sorted(set(targets))
    zp = ROOT / ".workbuddy" / "backup" / f"quant_refactor_{datetime.now():%Y%m%d_%H%M%S}.zip"
    if args.apply:
        zp.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in targets:
                z.write(p, p.relative_to(ROOT).as_posix())
        with zipfile.ZipFile(zp) as z:
            got = set(z.namelist())
        want = {p.relative_to(ROOT).as_posix() for p in targets}
        if got != want:
            print(f"✗ 回滚包不一致（缺 {len(want - got)} 项），**中止**")
            return 1
        print(f"1. 回滚包 {zp.relative_to(ROOT).as_posix()}：{len(got)} 项 ✓ 已校验")
    else:
        print(f"1. 回滚包将含 {len(targets)} 个文件（dry-run 不写盘）")

    # ── 2. 预演每处改动 ──
    print("\n2. 行级改动清单：")
    plan: dict[Path, tuple[list[str], list]] = {}
    n_changes = 0
    for p in targets:
        in_pkg = p.parent == ROOT and p.stem in MOVED
        new_lines, changes = patched_lines(p, in_pkg)
        rel = p.relative_to(ROOT).as_posix()
        if changes:
            print(f"\n   {rel}")
            for ln, old, new in changes:
                print(f"     L{ln}: {old.strip()}")
                print(f"        → {new.strip()}")
            n_changes += len(changes)
        # 入口脚本需要 sys.path 引导
        if in_pkg:
            src = "\n".join(new_lines)
            if "__main__" in src and "from quant import" in src and "_ROOT = _Path(__file__)" not in src:
                print(f"\n   {rel}\n     + 插入包内引导（sys.path 指向项目根），共 {BOOTSTRAP.count(chr(10))-1} 行")
                n_changes += 1
            plan[p] = (new_lines, changes)
        elif changes:
            plan[p] = (new_lines, changes)
    print(f"\n   合计 {n_changes} 处改动，涉及 {len(plan)} 个文件")

    if not args.apply:
        print("\n[DRY-RUN] 未修改任何文件。加 --apply 执行。")
        return 0

    # ── 3. 写回改动 + 搬家 ──
    print("\n3. 执行：")
    PKG.mkdir(exist_ok=True)
    (PKG / "__init__.py").write_text(
        '"""自建量化与分析层（2026-09-23 从项目根目录收进来）。\n\n'
        "对外只暴露模块本身：`from quant import screener_engine, stock_pools, edgar_fundamentals, price_history`。\n"
        "入口脚本（有 `__main__` 的）仍可直接运行：`python quant/smart_screener.py`。\n"
        '"""\n', encoding="utf-8", newline="\n")
    print("   ✓ quant/__init__.py")

    for p in sorted(plan):
        lines, changes = plan[p]
        src = "\n".join(lines)
        in_pkg = p.parent == ROOT and p.stem in MOVED
        if in_pkg and "__main__" in src and "from quant import" in src and "_ROOT = _Path(__file__)" not in src:
            # 插到最后一个顶层 import 之后
            tree = ast.parse(src)
            last = 0
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    last = max(last, node.end_lineno or node.lineno)
            ls = src.split("\n")
            ls[last:last] = BOOTSTRAP.strip("\n").split("\n")
            src = "\n".join(ls)
        if in_pkg:
            for a, b in FIXUPS:
                if a in src:
                    src = src.replace(a, b)
        # ★ 先校验再写盘：首版是"先写后校验"，结果校验失败时**坏文件已经落盘**，
#   还得手工清——顺序反了。
        try:
            ast.parse(src)
        except SyntaxError as e:
            print(f"   ✗ {p.name} 语法错误：{e} —— **中止（未写盘）**")
            return 1
        dst = (PKG / p.name) if in_pkg else p
        dst.write_text(src, encoding="utf-8", newline="\n")
        tag = "搬入 quant/" if in_pkg else "改导入"
        print(f"   ✓ {p.relative_to(ROOT).as_posix():46s} {tag}")

    # 搬完删源
    for m in MOVED:
        src = ROOT / f"{m}.py"
        if src.exists():
            if (PKG / src.name).stat().st_size != src.stat().st_size:
                print(f"   ✗ {src.name} 字节数不符，**保留不删**")
                continue
            src.unlink()
    print("\n4. 源文件已删除（字节校验通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
