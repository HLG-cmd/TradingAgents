#!/usr/bin/env python
# lifecycle: maintenance
# created: 2026-10-21
"""一次性 codemod：把 wb_analysis 里的裸本地时间改为走 wb_analysis/_clock.py。

背景
----
collect.py 的 --date 默认值、_thresholds.py 的期权时点分支都因为"裸本地时间"出过问题；
而 collect_index.py（104KB，最大的采集器）/ collect_hk_index.py / collect_treasury.py /
assemble.py 等处仍然是裸 datetime.now() / date.today()。本脚本做一次**确定性**替换。

用法（在项目根目录执行）
------------------------
    ./.venv/Scripts/python.exe scripts/_codemod_clock.py            # 干跑（默认），只打印 diff
    ./.venv/Scripts/python.exe scripts/_codemod_clock.py --apply    # 实际写入

替换规则（幂等，可重复执行；只改零参数调用，带时区参数的代码不动）
----------------------------------------------------------------
    dt.date.today().isoformat()   ->  _clock.iso_today()
    dt.date.today()               ->  _clock.market_date()
    dt.datetime.now()             ->  _clock.now()              # 美股口径（纽约）
    datetime.now()                ->  _clock.now()
仅以下两个文件改用东八区（它们的时间戳显式标注"北京时间"）：
    collect_hk_index.py / collect_treasury.py  ->  _clock.now(_clock.CN_TZ)

故意不处理的文件
----------------
* ``_reports_index.py`` —— 它的 ``datetime.now() - datetime.fromtimestamp(mtime)``
  是"文件多少小时没更新"的计算。直接换成 ``_clock.now()`` 会变成
  aware - naive，抛 ``TypeError``。该处与数据时点无关，建议手工改成
  ``(time.time() - p.stat().st_mtime) / 3600``（两边都是 epoch 秒）。
* ``_oneoff/`` 下的一次性脚本。

跑完请
------
    1) pytest -q tests/test_no_naive_clock.py
    2) 把该测试里 KNOWN_FILES 中的已清理文件删掉（只剩 _reports_index.py）；
       若连它一起处理了，就把 KNOWN_FILES 改成 set()，门禁立刻变严格。
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "wb_analysis"
SKIP_PARTS = {"_oneoff", "_archive", "scratch", "__pycache__"}
SKIP_FILES = {"_clock.py", "_reports_index.py"}
CN_FILES = {"collect_hk_index.py", "collect_treasury.py"}
IMPORT_LINE = "from wb_analysis import _clock"


def _rules(use_cn_tz: bool) -> list[tuple[str, str]]:
    now_expr = "_clock.now(_clock.CN_TZ)" if use_cn_tz else "_clock.now()"
    return [
        (r"(?<![\w.])dt\.date\.today\(\)\.isoformat\(\)", "_clock.iso_today()"),
        (r"(?<![\w.])dt\.date\.today\(\)", "_clock.market_date()"),
        (r"(?<![\w.])dt\.datetime\.now\(\)", now_expr),
        (r"(?<![\w.])datetime\.now\(\)", now_expr),
    ]


def _ensure_import(src: str) -> str:
    """确保文件里有 from wb_analysis import _clock（插在导入区末尾）。"""
    if re.search(
        r"^\s*(from\s+wb_analysis\s+import\s+_clock|import\s+wb_analysis\._clock)",
        src,
        re.M,
    ):
        return src
    nl = "\r\n" if "\r\n" in src else "\n"
    lines = src.splitlines(keepends=True)
    last = -1
    paren_depth = 0
    for i, line in enumerate(lines[:120]):
        paren_depth += line.count("(") - line.count(")")
        if re.match(r"^(import|from)\s", line) or (last >= 0 and paren_depth > 0):
            last = i
    if last < 0:
        print(f"  !! 找不到导入区，未插入 import；请手工加：{IMPORT_LINE}")
        return src
    lines.insert(last + 1, IMPORT_LINE + nl)
    return "".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="把裸本地时间改为 wb_analysis/_clock.py")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认只干跑）")
    args = ap.parse_args()

    changed = 0
    total_hits = 0
    for path in sorted(TARGET_DIR.rglob("*.py")):
        if path.name in SKIP_FILES or SKIP_PARTS & set(path.parts):
            continue
        original = path.read_text(encoding="utf-8")
        src = original
        hits = 0
        for pattern, repl in _rules(path.name in CN_FILES):
            src, n = re.subn(pattern, repl, src)
            hits += n
        if not hits:
            continue
        src = _ensure_import(src)
        rel = path.relative_to(ROOT).as_posix()
        print(f"{'WRITE' if args.apply else 'DRY  '} {rel}: {hits} 处")
        if args.apply:
            path.write_text(src, encoding="utf-8", newline="")
        else:
            sys.stdout.writelines(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    src.splitlines(keepends=True),
                    fromfile=rel,
                    tofile=rel,
                )
            )
        changed += 1
        total_hits += hits

    verb = "已写入" if args.apply else "待改"
    print(f"\n共 {changed} 个文件 / {total_hits} 处{verb}")
    if changed and not args.apply:
        print("确认 diff 无误后执行：")
        print("  ./.venv/Scripts/python.exe scripts/_codemod_clock.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
