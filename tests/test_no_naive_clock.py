"""门禁：禁止裸本地时间（point-in-time 流水线的基本纪律）。

为什么要有这条
--------------
``wb_analysis`` 决定"看到的是哪一天的市场"，时间取错就是报告取错。历史上同一类 bug
已经修过两次：

* ``collect.py`` 的 ``--date`` 默认值原为 ``dt.date.today()``（＝本机日期），2026-10-11 修正；
* ``_thresholds.py`` 的期权时点分支曾把 ``datetime.now()`` 写死在函数体里，
  导致该分支**无法被测试**。

规则
----
**零参数的** ``.now()`` / ``.today()`` 调用 = 裸本地时间，禁止（``_clock`` 自己除外）。
带参数的调用（``datetime.now(zoneinfo.ZoneInfo(...))``、``datetime.now(ny)``）视为
已指定时区，放行。判定用 AST，不会把注释或 docstring 里的示例当成违规。

设计说明
--------
``KNOWN_FILES`` 是**存量违规的显式记账**（文件级粒度，抗行号漂移），测试断言
"违规文件 ⊆ KNOWN_FILES"：

* 现在：绿（存量问题被记账，不阻塞你）；
* 跑完 ``python scripts/_codemod_clock.py --apply`` 后：只剩 ``_reports_index.py``，
  把它从 ``KNOWN_FILES`` 里删掉仍然是绿；
* 把 ``KNOWN_FILES`` 改成 ``set()``：立刻变成严格门禁；
* 任何时候**新文件**里出现裸本地时间：红。
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("wb_analysis",)  # 先只扫核心流水线；quant / scripts 可后续加入
SKIP_PARTS = {"_oneoff", "_archive", "scratch", "__pycache__", ".venv"}
ALLOW_FILES = {"_clock.py"}  # 唯一允许直接调 datetime.now() 的地方

# 存量违规已全部清空，当前为严格门禁（任何文件都不允许出现裸本地时间）
KNOWN_FILES: set[str] = set()


def _naive_clock_lines(tree: ast.AST) -> list[int]:
    """返回裸本地时间调用的行号（AST 级判定）。"""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"now", "today"}:
            continue
        if node.args or node.keywords:  # 带了参数 → 视为已指定时区
            continue
        try:
            callee = ast.unparse(func)
        except Exception:  # noqa: BLE001 — unparse 失败时保守放行
            continue
        if "_clock" in callee:  # _clock.now() 是唯一合法来源
            continue
        hits.append(node.lineno)
    return hits


def _scan() -> dict[str, list[int]]:
    offenders: dict[str, list[int]] = {}
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name in ALLOW_FILES or SKIP_PARTS & set(path.parts):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            lines = _naive_clock_lines(tree)
            if lines:
                offenders[path.relative_to(ROOT).as_posix()] = lines
    return offenders


def test_no_new_naive_local_clock():
    offenders = _scan()
    new = sorted(set(offenders) - KNOWN_FILES)
    assert not new, (
        "以下文件新出现了裸本地时间，请改用 wb_analysis/_clock.py 的 "
        "now() / market_date() / iso_today()：\n"
        + "\n".join(f"  {f}: 行 {offenders[f]}" for f in new)
    )
