#!/usr/bin/env python
# lifecycle: maintenance
"""第四轮：A1 log_gap 真实接线 + A4 collect_index 死定义清理 + A2 docstring 漂移。

设计要点：
  · A1 用 AST 定位 except 块（不用行号），插入点取「handler 体第一条语句」，
    通道名优先从 try 体里的 route_to_vendor/_safe_call 首参推导，退化到 `文件:函数`。
  · 只动 A1_FILES 白名单，且只动 `except Exception`（含 `as x` 与裸写两种）。
  · A4 只在「该名字确实被 index_valuation 再导入」时才删，避免删掉唯一来源。
  · 默认干跑，逐条打印将要发生的改动。

用法：
    ./.venv/Scripts/python.exe scripts/_apply_round4.py            # 干跑
    ./.venv/Scripts/python.exe scripts/_apply_round4.py --apply
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "wb_analysis" / "_log.py"
CIIDX = ROOT / "wb_analysis" / "collect_index.py"
TREAS = ROOT / "wb_analysis" / "collect_treasury.py"

A1_FILES = [
    ROOT / "wb_analysis" / "collect_a_stock.py",
    ROOT / "wb_analysis" / "collect_a_etf.py",
    ROOT / "wb_analysis" / "_verify_earnings_quality.py",
]
IMPORT_LINE = "from wb_analysis._log import log_gap"
VENDOR_FUNCS = {"route_to_vendor", "_safe_call", "get_macro_data", "urlopen"}
DEAD_NAMES = ("INDEX_TICKER", "ETF_PROXY", "INFO_FIELDS")
OLD_DOC_PATH = "wb_analysis/evidence/TREASURY_<date>.md"
NEW_DOC_PATH = "wb_analysis/fixtures/macro/TREASURY_<date>.md"


def read(p: Path) -> str:
    with p.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(p: Path, s: str) -> None:
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(s)


def nl_of(s: str) -> str:
    return "\r\n" if "\r\n" in s else "\n"


# ---------------- A1 ----------------

def _func_names(tree: ast.AST) -> dict:
    out: dict = {tree: ""}

    def walk(node, cur):
        for ch in ast.iter_child_nodes(node):
            nxt = ch.name if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)) else cur
            out[ch] = nxt
            walk(ch, nxt)

    walk(tree, "")
    return out


def _channel(try_node: ast.Try, stem: str, funcname: str) -> str:
    for n in ast.walk(try_node):
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name in VENDOR_FUNCS:
                if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    return f"vendor.{n.args[0].value}"
                break
    return f"{stem}.{funcname or 'module'}"


def plan_a1(path: Path):
    src = read(path)
    nl = nl_of(src)
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    fnames = _func_names(tree)
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            t = h.type
            if not (isinstance(t, ast.Name) and t.id == "Exception"):
                continue
            first = h.body[0]
            if "log_gap" in (ast.get_source_segment(src, first) or ""):
                continue
            ch = _channel(node, path.stem, fnames.get(node, ""))
            excvar = h.name
            hdr = lines[h.lineno - 1].rstrip("\r\n")
            if excvar is None:
                if ":" not in hdr:
                    edits.append(("skip", h.lineno, hdr, "裸 except 头部无法安全改写"))
                    continue
                new_hdr = re.sub(r"\bexcept\s+Exception\s*:", "except Exception as _gap_exc:", hdr, count=1)
                if new_hdr == hdr:
                    edits.append(("skip", h.lineno, hdr, "头部未改写成功，跳过"))
                    continue
                edits.append(("hdr", h.lineno, hdr, new_hdr))
                excvar = "_gap_exc"
            indent = " " * first.col_offset
            edits.append(("ins", first.lineno, "", f'{indent}log_gap("{ch}", {excvar}){nl}'))
    return src, edits


def apply_a1(path: Path, src: str, edits) -> str:
    """★ 先按原始行号落编辑，**最后**再插导入。

    历史坑（2026-10-22 实测踩过）：导入若先插入，其后所有行号 +1，而 edits 里存的
    仍是原始行号 —— 每条编辑都落到目标行的上一行：头部改写覆盖 try 体、插入语句
    跑到 except 之上，直接 IndentationError 并丢内容。
    """
    nl = nl_of(src)
    lines = src.splitlines(keepends=True)
    for kind, lineno, _old, new in sorted(edits, key=lambda e: -e[1]):
        if kind == "skip":
            continue
        if kind == "hdr":
            lines[lineno - 1] = new + nl
        else:
            lines.insert(lineno - 1, new)
    if IMPORT_LINE not in src:
        anchor = None
        for i, ln in enumerate(lines):
            if ln.strip() == "from __future__ import annotations":
                anchor = i
                break
        if anchor is None:
            raise SystemExit(f"[FAIL] {path.name}: 找不到 __future__ 锚点，不写入")
        lines.insert(anchor + 1, f"{IMPORT_LINE}{nl}")
    return "".join(lines)


# ---------------- A4 ----------------

def plan_a4():
    src = read(CIIDX)
    lines = src.splitlines(keepends=True)
    m = re.search(r"from wb_analysis\.index_valuation import \(([^)]*)\)", src)
    imported = m.group(1) if m else ""
    spans = []
    notes = []
    for name in DEAD_NAMES:
        if name not in imported:
            notes.append(f"[跳过] {name}：未出现在 index_valuation 的导入列表里，不敢动")
            continue
        idx = None
        for i, ln in enumerate(lines):
            if re.match(rf"^{name}\s*=", ln):
                idx = i
                break
        if idx is None:
            notes.append(f"[跳过] {name}：找不到模块级定义")
            continue
        end = idx
        body = lines[idx].rstrip("\r\n").rstrip()
        if body.endswith("("):
            depth = lines[idx].count("(") - lines[idx].count(")")
            j = idx
            while depth > 0 and j + 1 < len(lines):
                j += 1
                depth += lines[j].count("(") - lines[j].count(")")
            end = j
        spans.append((idx, end, name))
    return lines, spans, notes


def main() -> int:
    apply = "--apply" in sys.argv
    print(f"=== {'APPLY' if apply else 'DRY-RUN'} ===\n")

    # 0) log_gap 安全性侦察
    print("--- 0. log_gap 实现（确认无 run 上下文时是否安全）---")
    lsrc = read(LOG).splitlines()
    start = next((i for i, l in enumerate(lsrc) if l.startswith("def log_gap")), None)
    if start is None:
        print("  [FAIL] 没找到 def log_gap")
        return 1
    for i in range(start, min(start + 26, len(lsrc))):
        print(f"    {i + 1:>4}| {lsrc[i]}")

    # 1) A1
    print("\n--- 1. A1 log_gap 接线（AST 定位）---")
    a1_total = 0
    for p in A1_FILES:
        src, edits = plan_a1(p)
        real = [e for e in edits if e[0] == "ins"]
        a1_total += len(real)
        print(f"  {p.name}：{len(real)} 处")
        for kind, lineno, old, new in edits:
            if kind == "skip":
                print(f"      [跳过] L{lineno}: {new}")
            elif kind == "hdr":
                print(f"      L{lineno} 头改写: {old.strip()}  ->  {new.strip()}")
            else:
                print(f"      L{lineno} 插入: {new.strip()}")
        if apply and real:
            write(p, apply_a1(p, src, edits))
    print(f"  合计 {a1_total} 处")

    # 2) A4
    print("\n--- 2. A4 collect_index.py 死定义 ---")
    lines, spans, notes = plan_a4()
    for n in notes:
        print(f"  {n}")
    for idx, end, name in spans:
        print(f"  删 {name}：L{idx + 1}-{end + 1}")
        for i in range(idx, end + 1):
            print(f"      - {lines[i].rstrip()}")
    if apply and spans:
        drop = {i for idx, end, _ in spans for i in range(idx, end + 1)}
        kept = [ln for i, ln in enumerate(lines) if i not in drop]
        out = "".join(kept)
        out = re.sub(
            r"#[^\r\n]*向后兼容[^\r\n]*",
            "# 向后兼容：ETF_PROXY / INDEX_TICKER / INFO_FIELDS 由下方 "
            "index_valuation 导入提供，此处不再重复定义。",
            out,
            count=1,
        )
        write(CIIDX, out)

    # 3) A2 docstring 漂移
    print("\n--- 3. A2 collect_treasury.py docstring 漂移 ---")
    t = read(TREAS)
    if OLD_DOC_PATH in t:
        print(f"  [改] {OLD_DOC_PATH} -> {NEW_DOC_PATH}")
        if apply:
            write(TREAS, t.replace(OLD_DOC_PATH, NEW_DOC_PATH))
    else:
        print("  [已有] docstring 路径已更新")

    print("\n" + ("已写入。" if apply else "干跑结束，未改动。确认后加 --apply。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
