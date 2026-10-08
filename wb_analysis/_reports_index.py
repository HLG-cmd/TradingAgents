# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_reports_index.py
"""生成 `reports/INDEX.md`，并检查产物是否又开始堆积（可作为交付门禁的一项）。

解决什么：产物分散在 **四个命名空间**，且只有 `reports/` 带时间戳 ⇒
  · `wb_analysis/evidence/<T>_<date>.*`
  · `wb_analysis/drafts/<T>_<date>/`
  · `wb_analysis/analysis/<T>_<date>.json`
  · `reports/<T>/<T>_<stamp>/`
同一天重跑同一标的时，前三个**被覆盖**、第四个**堆积**，于是出现「孤儿草稿 / 孤儿证据 /
对不上号的报告树」。本工具把四者按 **(标的, 基准日)** 关联起来，并列出异常，使「乱」一眼可见。

用法:
  ./.venv/Scripts/python.exe wb_analysis/_reports_index.py            # 生成 INDEX.md
  ./.venv/Scripts/python.exe wb_analysis/_reports_index.py --check    # 只检查，有问题退出码 1
"""
import argparse
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
EVID = ROOT / "wb_analysis" / "evidence"
DRAFTS = ROOT / "wb_analysis" / "drafts"
ANALYSIS = ROOT / "wb_analysis" / "analysis"
TREE_RE = re.compile(r"^([A-Za-z0-9.\-]+)_(\d{8})_(\d{6})$")
SKIP_DIRS = {"_datasets", "_other", "_archive", "_audit"}


def read_ratings(tree: Path) -> dict:
    """从渲染后的报告树里还原三个关键评级。"""
    def pick(rel: str) -> str:
        p = tree / rel
        if not p.exists():
            return "—"
        m = re.search(r"\*\*(?:Recommendation|Rating)\*\*:\s*\**(\w+)", p.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
        m = re.search(r"FINAL TRANSACTION PROPOSAL:\s*\*\*(\w+)\*\*", p.read_text(encoding="utf-8"))
        return m.group(1) if m else "—"
    return {"manager": pick("2_research/manager.md"),
            "trader": pick("3_trading/trader.md"),
            "pm": pick("5_portfolio/decision.md")}


def evidence_channels(ticker: str, date: str) -> str:
    p = EVID / f"{ticker}_{date}.md"
    if not p.exists():
        return "—"
    m = re.search(r"成功:\s*(\d+)\s*/\s*(\d+)", p.read_text(encoding="utf-8", errors="replace"))
    return f"{m.group(1)}/{m.group(2)}" if m else "?"


def read_run(tree: Path) -> dict | None:
    """读取渲染时写入的 RUN.json（运行清单）。老报告树没有该文件，返回 None。"""
    p = tree / "RUN.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def scan() -> tuple[list[dict], list[str]]:
    rows, issues = [], []
    trees: dict[tuple[str, str], list[dict]] = {}
    if REPORTS.exists():
        for d in sorted(REPORTS.iterdir()):
            if d.is_dir() and d.name not in SKIP_DIRS:
                for tr in sorted(d.iterdir()):
                    if not tr.is_dir():
                        continue
                    m = TREE_RE.match(tr.name)
                    if not m:
                        continue
                    ticker, ymd = m.group(1), m.group(2)
                    run_date = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
                    run = read_run(tr)
                    # RUN.json 用长键（research_manager/trader_action/portfolio_manager），
                    # 从报告树反读用短键（manager/trader/pm）—— 这里统一成短键。
                    rr = (run or {}).get("ratings") or {}
                    ratings = {
                        "manager": rr.get("research_manager") or rr.get("manager"),
                        "trader": rr.get("trader_action") or rr.get("trader"),
                        "pm": rr.get("portfolio_manager") or rr.get("pm"),
                    }
                    if not any(ratings.values()):
                        ratings = read_ratings(tr)
                    # ★ 关联键必须是「**数据基准日**」，而目录名里的是「**运行时刻**」——
                    #   两者通常差一天（例如基准日 9/21 的报告在 9/22 渲染）。
                    #   有 RUN.json 就以它为准；老报告树没有清单，退回目录名并标记 (legacy)。
                    date = (run or {}).get("data_date") or run_date
                    # ★ 2026-09-23：草稿可能已被**封存进报告树内的 _source.zip**（产物封存机制），
                    #   此时「工作目录里没有 drafts/」是**正常状态**，不是缺草稿。
                    #   判据必须是「散落目录存在 **或** 树内审计包含 drafts」。
                    def _sealed_with(zp: Path, prefix: str) -> bool:
                        if not zp.exists():
                            return False
                        try:
                            with zipfile.ZipFile(zp) as z:
                                return any(n.startswith(prefix) for n in z.namelist())
                        except Exception:  # noqa: BLE001
                            return False

                    if run and run.get("source_drafts"):
                        has_drafts = Path(run["source_drafts"]).exists() or _sealed_with(tr / "_source.zip", "drafts/")
                    else:
                        has_drafts = (DRAFTS / f"{ticker}_{date}").exists() or _sealed_with(tr / "_source.zip", "drafts/")
                    rows.append({
                        "ticker": ticker, "date": date, "tree": tr.name,
                        "path": tr.relative_to(ROOT).as_posix(),
                        "n_files": len([p for p in tr.rglob("*") if p.is_file()]),
                        "ratings": ratings,
                        "channels": evidence_channels(ticker, date),
                        "has_drafts": has_drafts,
                        "has_analysis": (ANALYSIS / f"{ticker}_{date}.json").exists(),
                        "has_run": run is not None,
                    })
                    trees.setdefault((ticker, date), []).append(rows[-1])

    # ── 异常一：同一 (标的, 基准日) 有多棵树 ⇒ 历史版本并存（不算错，但要标出来）
    for k, lst in sorted(trees.items()):
        if len(lst) > 1:
            issues.append(f"[历史版本并存] {k[0]} {k[1]}：{len(lst)} 棵报告树 "
                          f"（最新 {sorted(x['tree'] for x in lst)[-1]}）")
    # ── 异常二：报告树缺少对应草稿（无法再渲染）
    for r in rows:
        if not r["has_drafts"]:
            issues.append(f"[缺草稿] {r['ticker']} {r['date']} 的报告树既无散落草稿目录、"
                          f"审计包里也没有 drafts ⇒ 无法重新渲染：{r['tree']}")
    # ── 异常三：孤儿（有证据/草稿，却没有报告树）
    # 豁免：不属于 12 角色链路、且**不产出报告树**的专用通道/过程产物——
    # 它们本就以 evidence/ 为正规归宿（如 collect_treasury.py 内建的 OUT_DIR），
    # 「无报告树」是其设计预期而非堆积。新增此类通道时须同步登记到本表。
    NON_TREE_PREFIXES = ("TREASURY",)          # 非 12 角色专题通道（collect_treasury.py）
    have = {(r["ticker"], r["date"]) for r in rows}
    for d in sorted(EVID.glob("*.md")) if EVID.exists() else []:
        if "derived" in d.name or "supplement" in d.name or ".pre_" in d.name:
            continue
        if d.name.startswith(NON_TREE_PREFIXES):
            continue
        m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})", d.name)
        if m and (m.group(1), m.group(2)) not in have:
            issues.append(f"[孤儿证据] {d.name}：没有对应报告树")
    for d in sorted(DRAFTS.iterdir()) if DRAFTS.exists() else []:
        if not d.is_dir():
            continue
        m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})", d.name)
        if m and (m.group(1), m.group(2)) not in have:
            issues.append(f"[孤儿草稿] {d.name}/：没有对应报告树")
    # ── 异常四：顶层散落 / 修复前快照 / 无清单的旧报告树
    # reports/ 顶层允许存在的文件：自动索引与本目录说明（它们本就是"目录的门面"）
    ALLOWED_TOP = {"INDEX.md", "README.md", "QUALITY.csv"}   # 目录门面：索引 / 说明 / 质量记分卡
    for p in sorted(REPORTS.iterdir()):
        if p.is_file() and p.name not in ALLOWED_TOP:
            issues.append(f"[顶层散落] {p.name}：应归入 _datasets/ 或 _other/")
    for p in sorted(EVID.glob("*.pre_*")):
        issues.append(f"[修复前快照] {p.name}：属过程产物，宜清理")
    legacy = [r for r in rows if not r["has_run"]]
    if legacy:
        issues.append(f"[无运行清单] {len(legacy)} 棵报告树生成于 RUN.json 机制之前 "
                      f"（{', '.join(r['tree'] for r in legacy[:4])}…）⇒ 关联关系靠推测，建议重渲染一次以生成清单")
    return rows, issues


def write_index(rows: list[dict], issues: list[str]) -> Path:
    rows_sorted = sorted(rows, key=lambda r: (r["ticker"], r["date"]))
    cur: dict[str, dict] = {}
    for r in rows_sorted:
        t = r["ticker"]
        if t not in cur or r["tree"] > cur[t]["tree"]:
            cur[t] = r
    L = ["# 报告索引（自动生成，勿手改）", "",
         f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
         f"- 扫描范围：`reports/<标的>/<标的>_<时间戳>/`（12 角色报告树）",
         f"- 报告树总数：**{len(rows)}**，覆盖标的 **{len(cur)}** 个", "",
         "## 一、每个标的的最新报告", "",
         "| 标的 | 最新报告 | 基准日 | 研究经理 | 交易员 | 组合经理 | 证据包通道 | 有草稿 | 有分析JSON |",
         "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(cur):
        r = cur[t]
        L.append(f"| **{t}** | `{r['tree']}` | {r['date']} | {r['ratings']['manager']} | "
                 f"{r['ratings']['trader']} | {r['ratings']['pm']} | {r['channels']} | "
                 f"{'✓' if r['has_drafts'] else '✗'} | {'✓' if r['has_analysis'] else '✗'} |")
    L += ["", "## 二、全部历史版本", "",
          "| 标的 | 基准日 | 报告树 | 文件数 | 通道 | 角色评级(经理/交易员/组合) |",
          "|---|---|---|---|---|---|"]
    for r in rows_sorted:
        L.append(f"| {r['ticker']} | {r['date']} | `{r['tree']}` | {r['n_files']} | {r['channels']} | "
                 f"{r['ratings']['manager']}/{r['ratings']['trader']}/{r['ratings']['pm']} |")
    L += ["", "## 三、卫生检查", ""]
    if issues:
        L += [f"发现 **{len(issues)}** 项待处理：", ""]
        L += [f"- {x}" for x in issues]
    else:
        L.append("✓ 未发现堆积问题（无孤儿产物、无顶层散落、无缺草稿的报告树）。")
    L += ["", "## 四、目录约定（`reports/` 下划线开头为功能性目录）", "",
          "| 目录 | 放什么 |", "|---|---|",
          "| `_datasets/` | 雷达/回测/核验导出的 CSV、HTML 等**数据产品** |",
          "| `_other/` | **非 12 角色**的专题报告（筛选报告、多标的对比等） |",
          "| `_archive/` | 归档产物 + 删除/重排清单（可审计） |",
          "| `_audit/` | 审计类文档（数据缺口审计等） |",
          "| `<TICKER>/` | 该标的的 12 角色报告树，按时间戳并列 |", ""]
    out = REPORTS / "INDEX.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查不写索引；有问题退出码 1")
    args = ap.parse_args()
    rows, issues = scan()
    if not args.check:
        out = write_index(rows, issues)
        print(f"[索引] 已写入 {out.relative_to(ROOT).as_posix()}")
    print(f"[扫描] 报告树 {len(rows)} 棵；卫生问题 {len(issues)} 项")
    for x in issues:
        print(f"   - {x}")
    if args.check:
        return 1 if issues else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
