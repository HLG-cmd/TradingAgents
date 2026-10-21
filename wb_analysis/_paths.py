# lifecycle: reusable
# created: 2026-10-10
# usage: from wb_analysis._paths import TREE_RE, FUNC_DIRS, ALLOWED_TOP, SKIP_ARCHIVE_DIRS, iter_report_trees
"""`reports/` 布局与「草稿扫描跳过」的**唯一常量来源** —— 目录名 / 功能目录 / 顶层白名单 / 归档跳过表。

## 为什么要有这个文件（2026-10-10）

同一份约定此前被 **11 处**各写一遍。这不是风格问题，**已经造成过真实的不一致**：
`scripts/_health.py` 的「瞬态目录」检查曾只数文件数、不认豁免表，于是它与
`_reports_index.py` / `_seal_run.py` 对**同一份文件**给出相反结论（一个说残留、一个说豁免）。

本项目原则：**同一口径只允许在一处定义** —— 写两遍必然漂移，而**漂移的工具比没有工具更危险**。

| 常量 | 原重复处数 | 消费方 |
|---|---|---|
| `TREE_RE` | 3 | `_reports_index` · `_scorecard` · `scripts/_reorg_reports` |
| `FUNC_DIRS` | 4 | `_reports_index` · `_scorecard` · `_seal_run` · `scripts/_reorg_reports` |
| `ALLOWED_TOP` | 1（函数内局部字面量） | `_reports_index` |
| `SKIP_ARCHIVE_DIRS` | 4 | `_audit_values` · `_check_residuals` · `_check_role_files` · `_lint_drafts` |

⚠️ **别把 `FUNC_DIRS` 和 `SKIP_ARCHIVE_DIRS` 搞混** —— 两者名字像、**管的目录完全不同**：
  · `FUNC_DIRS` 管 **`reports/` 顶层**（哪些子目录不算报告树）；
  · `SKIP_ARCHIVE_DIRS` 管 **`<草稿>/` 内部**（哪些历史归档子目录/文件名要跳过）。
  把其中一个用于另一个场景，检查器会静默地少扫或多扫 —— 正是铁律 3 的形态。
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 1. 报告树目录名
# ─────────────────────────────────────────────────────────────────────────────

#: 报告树目录名：`<TICKER>_<YYYYmmdd>_<HHMMSS>`（例：`NVDA_20261010_110109`）。
#:
#: ★ 刻意分成 **3 个组**（ticker / 日期 / 时刻），**不要合并成一个时间组**：
#:   消费方需要 `ymd` 单独参与「数据基准日」比较（目录名里是**运行时刻**，两者通常差一天）。
#: ★ 与旧的 2 组写法 `^([A-Za-z0-9.\-]+)_(\d{8}_\d{6})$` **实测等价**：
#:   25 个名字（含 `512400.SS_…` / `hkHSTECH_…` / `515100_…` 及 12 个反例）
#:   的**匹配集合与 `group(1)` 完全一致**，且 `g2+"_"+g3` 逐字复现旧 `group(2)` ⇒ 可安全互换。
TREE_RE = re.compile(r"^([A-Za-z0-9.\-]+)_(\d{8})_(\d{6})$")

# ─────────────────────────────────────────────────────────────────────────────
# 2. `reports/` 顶层约定
# ─────────────────────────────────────────────────────────────────────────────

#: `reports/` 下**不是报告树**的功能目录：数据产品 / 非 12 角色专题 / 归档+删除清单 / 审计。
FUNC_DIRS: frozenset[str] = frozenset({"_datasets", "_other", "_archive", "_audit"})

#: `reports/` **顶层允许存在的散落文件**（目录门面：索引 / 说明 / 质量记分卡）。
#: 其余顶层文件即卫生问题。
ALLOWED_TOP: frozenset[str] = frozenset({"INDEX.md", "README.md", "QUALITY.csv"})


def iter_report_trees(reports_dir: Path) -> Iterator[tuple[Path, Path]]:
    """枚举 `reports/<标的>/<报告树>/` 下所有符合 `TREE_RE` 的有效报告树，产出 `(标的目录, 报告树目录)`。

    ★ 2026-10-15 新增：此前 `_scorecard.py` 与 `scripts/_health.py::chk_scorecard()` 遍历二级目录时
    漏掉了 `TREE_RE.match(tr.name)` 过滤，导致 `reports/SKHY/_archive` 被当成报告树写进 `QUALITY.csv`
    （产出 `ticker=""` 的幽灵行），且两处错误计数刚好相等（50/50）形成「假绿」。
    统一走此生成器可从物理上根除各工具遍历口径不一致的问题。
    """
    if not reports_dir.exists():
        return
    for tk in sorted(d for d in reports_dir.iterdir() if d.is_dir() and d.name not in FUNC_DIRS):
        for tr in sorted(x for x in tk.iterdir() if x.is_dir() and TREE_RE.match(x.name)):
            yield tk, tr

# ─────────────────────────────────────────────────────────────────────────────
# 3. 草稿 / 证据扫描的归档跳过表
# ─────────────────────────────────────────────────────────────────────────────

#: 扫描**草稿 / 证据**目录时要跳过的归档关键字。
#: 语义＝**子串命中**（`any(s in path_posix for s in SKIP_ARCHIVE_DIRS)`），与 `_lint_drafts.py`
#: 的 `--exclude` 约定一致 —— 这样 `<draft>/_stale_pre_brief_fix/` **目录**与被作废的
#: `manager_stale.md` / `trader_stale.md` **文件**都能被同一张表挡住。
#:
#: ⚠️ 2026-10-10 收敛：`_check_role_files.py` 此前只把 `_stale` 比对 `p.name`、把 `_archive`
#:    比对 `p.as_posix()`（**同一件事两种比法**）⇒ `_stale*/` **子目录**里的角色稿会被误计入
#:    交付物，而 `_lint_drafts.py` 却不会 ⇒ 两套检查器的问题数无法横向比较。
#:    实测当前 `drafts/`+`evidence/` 下**不存在**任何 `_stale*`/`_archive*` 目录，
#:    故本次对称化**可证为 no-op**，只是把未来的漏洞堵上。
SKIP_ARCHIVE_DIRS: tuple[str, ...] = ("_stale", "_archive")


def is_archived_path(p: object) -> bool:
    """该路径（PosixPath / str / 任何有 `as_posix()` 或 `__str__` 的对象）是否属于归档留痕。

    判据＝**路径串里含 `SKIP_ARCHIVE_DIRS` 任一关键字**（子串），与四个消费方同约定。
    """
    s = p.as_posix() if hasattr(p, "as_posix") else str(p)  # type: ignore[union-attr]
    return any(k in s for k in SKIP_ARCHIVE_DIRS)


def any_archived(paths: Iterable[object]) -> bool:
    """任一命中即真（给 `[p for p in ... if not any_archived(...)]` 之外的场景用）。"""
    return any(is_archived_path(p) for p in paths)


__all__ = [
    "TREE_RE",
    "FUNC_DIRS",
    "ALLOWED_TOP",
    "SKIP_ARCHIVE_DIRS",
    "iter_report_trees",
    "is_archived_path",
    "any_archived",
]
