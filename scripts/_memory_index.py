# lifecycle: maintenance
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_memory_index.py [--check]
"""为本地运行痕迹目录（`.workbuddy-ai/memory/`）生成**主题索引**（`_INDEX.md`）。

> ⚠️ **目标目录不在对外仓库中**：`.workbuddy-ai/` 已被 `.gitignore` 忽略，
> 克隆本仓库后不存在 ⇒ 本脚本是**本地维护工具**，在公开克隆里运行会报「目录不存在」。
> 需要长期留存的判据已落在 `docs/RULES.md`（铁律全文）与 `docs/DOMAINS.md`（领域口径）。

## 为什么需要它
`memory/` 里的按天日志（`YYYY-MM-DD.md`）是**判例原始记录** —— 想知道
「当年怎么处理某个问题」，得逐个文件翻。实测 10-10 那份 56 KB，
11 个日志合起来 1.1 MB，**没有主题入口**。

已有的两份索引各管一段，覆盖不到按天日志：
  · `MEMORY.md`      —— 「何时读哪个文件」的体例表（不列具体主题）
  · `IRONLAWS.md`    —— 铁律全文 + 单行索引（只收已被提炼成铁律的；条数以该文件自报为准）
  ⇒ 缺口：**还没被提炼成铁律、但已经发生过的判例**，散落在日志里无从检索。
  （★ 这两份已于 2026-10-17 对外化为 `docs/RULES.md` / `docs/DOMAINS.md`；
    `memory/` 内的同名文件转为本地运行副本。）

## 它做什么
扫描 `memory/*.md`（**跳过 `_backup/`** —— 那里是历史快照，与正本重复），
抽出每个文件的 `##` 二级标题，按「文件 → 主题」列成索引表。

不产生任何新数据，只做汇总 ⇒ 可安全反复运行（幂等）。

## 为什么不做成「按主题聚类」
分类要靠人判断（「数据质量」与「口径漂移」经常是同一件事的两面），
写成规则必然误分。**保持「按日期 + 标题」的机械结构**，让 `grep` 去找语义 ——
索引的职责是**知道有什么**，不是**替你想在哪**。

用法：
    ./.venv/Scripts/python.exe scripts/_memory_index.py           # 生成/更新
    ./.venv/Scripts/python.exe scripts/_memory_index.py --check    # 只校验是否过期
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
MEM = ROOT / ".workbuddy-ai" / "memory"
INDEX = MEM / "_INDEX.md"

#: 参与索引的文件：正本（非 `_backup/`）的 md，排除索引自身与体例文件。
EXCLUDE_NAMES = {"_INDEX.md", "MEMORY.md", "IRONLAWS.md", "DOMAINS.md"}
H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
#: 标题里形如「§1 xxx」的序号前缀、以及「10-09 xxx」「2026-10-09 xxx」的日期前缀去掉，
#: 让索引更像主题（实测日志里有 `## -10-09 WDC…` 这类从文件名截断残留的前缀）。
SECTION_NUM = re.compile(r"^[§\s]*[\d.]+\s+")
DATE_PREFIX = re.compile(r"^[-\s]*(?:20\d\d-)?\d\d-\d\d\s+")


def collect() -> list[tuple[str, str, list[str]]]:
    """返回 [(文件名, 一行摘要, [二级标题, ...]), ...]，按文件名排序。"""
    rows: list[tuple[str, str, list[str]]] = []
    if not MEM.exists():
        return rows
    for p in sorted(MEM.glob("*.md")):
        if p.name in EXCLUDE_NAMES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        titles = []
        for t in H2.findall(text):
            t = SECTION_NUM.sub("", t).strip()
            t = DATE_PREFIX.sub("", t).strip()
            if t:
                titles.append(t)
        # 一行摘要：第一个非空正文段（跳过标题与引用块）
        summary = ""
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith(("#", ">", "|", "-", "*", "```")):
                continue
            summary = re.sub(r"[*`]", "", s)[:90]
            break
        rows.append((p.name, summary, titles))
    return rows


def render(rows) -> str:
    L = [
        "# 记忆索引（自动生成，勿手改）",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        "- 生成方式：`./.venv/Scripts/python.exe scripts/_memory_index.py`",
        "- 范围：`memory/*.md`（**不含 `_backup/`** —— 那里是历史快照，与正本重复）",
        "",
        "> 本文件只回答「**有哪些主题、在哪个文件**」。语义检索请直接 `grep` ——",
        "> 分类靠人判断（「数据质量」与「口径漂移」常是同一件事的两面），写成规则必然误分。",
        "",
        "## 一、按文件",
        "",
        "| 文件 | 主题数 | 一句话 |",
        "|---|---|---|",
    ]
    for name, summary, titles in rows:
        s = summary.replace("|", "\\|") if summary else "—"
        L.append(f"| [{name}]({name}) | {len(titles)} | {s} |")
    L += ["", "## 二、按主题", ""]
    for name, _summary, titles in rows:
        if not titles:
            continue
        L.append(f"**{name}**")
        L.append("")
        for t in titles:
            L.append(f"- {t}")
        L.append("")
    L += [
        "---",
        "",
        "## 相关索引（各管一段，互不重复）",
        "",
        "| 文件 | 管什么 |",
        "|---|---|",
        "| `MEMORY.md` | 每次开工都要遵守的硬约束 + 「何时读哪个文件」体例表 |",
        "| `IRONLAWS.md` | **铁律全文 + 单行索引**（已被提炼成判据的那部分；条数以该文件自报为准） |",
        "| `DOMAINS.md` | 按标的/子系统（指数聚合 / ERP / 黄金 / 非美股 / 量化选股 / A股） |",
        "| **本文件** | **按天日志的主题入口**（还没被提炼成铁律的判例） |",
        "",
    ]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 memory 主题索引")
    ap.add_argument("--check", action="store_true", help="只校验是否过期（不改文件）")
    args = ap.parse_args()

    rows = collect()
    if not rows:
        print("✗ 未找到任何记忆文件（memory/ 不存在或为空）")
        return 1
    content = render(rows)
    total_titles = sum(len(t) for _, _, t in rows)

    if args.check:
        if not INDEX.exists():
            print("✗ _INDEX.md 不存在 ⇒ 跑 `scripts/_memory_index.py` 生成")
            return 1
        # ★★ 2026-10-16 修（**检查器恒假**）：原判据是全等比较，而 content 含
        #   「生成时间：<now>」—— 时间戳每次都不同 ⇒ **刚生成完也恒报「已过期」**
        #   （实测：连续两次 render 相同，与磁盘差异只有时间戳那一行）。
        #   与铁律 49「检查器判据缺陷会伪装成没问题」同族，方向相反（这次是恒报错）。
        #   ⇒ 比较前剔除时间戳行；时间戳只作展示，不参与一致性判断。
        def _strip_ts(s: str) -> str:
            return "\n".join(
                line for line in s.splitlines()
                if not line.startswith("- 生成时间："))
        if _strip_ts(INDEX.read_text(encoding="utf-8")) != _strip_ts(content):
            print("✗ _INDEX.md 已过期（记忆有更新）⇒ 重跑 `scripts/_memory_index.py`")
            return 1
        print(f"✓ _INDEX.md 已是最新（{len(rows)} 个文件 / {total_titles} 个主题）")
        return 0

    INDEX.write_text(content, encoding="utf-8", newline="\n")
    print(f"✓ 已写入 {INDEX.relative_to(ROOT).as_posix()}"
          f"（{len(rows)} 个文件 / {total_titles} 个主题 / {len(content)} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
