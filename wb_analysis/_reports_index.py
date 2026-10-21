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
import time
import zipfile
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from wb_analysis import _clock  # noqa: E402
from wb_analysis._contract import PROPOSAL_RE, is_non_tree_artifact  # noqa: E402
from wb_analysis._paths import ALLOWED_TOP, FUNC_DIRS, TREE_RE  # noqa: E402

REPORTS = ROOT / "reports"
EVID = ROOT / "wb_analysis" / "evidence"
DRAFTS = ROOT / "wb_analysis" / "drafts"
ANALYSIS = ROOT / "wb_analysis" / "analysis"
# ★ 2026-10-10：`TREE_RE` 与「功能目录集」原本在此**逐字定义**，而 `_scorecard.py`、
#   `_seal_run.py`、`scripts/_reorg_reports.py` 各持一份**完全相同**的拷贝
#   ⇒ 上提到 `wb_analysis/_paths.py`（`ALLOWED_TOP` 也一并从函数内局部提升为模块常量）。
SKIP_DIRS = FUNC_DIRS


def read_ratings(tree: Path) -> dict:
    """从渲染后的报告树里还原三个关键评级。"""
    def pick(rel: str) -> str:
        p = tree / rel
        if not p.exists():
            return "—"
        m = re.search(r"\*\*(?:Recommendation|Rating)\*\*:\s*\**(\w+)", p.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
        # 交易员末行正则取自 `_contract`（原名内联字面量，2026-10-10 收敛）；
        # 宽松版抓 `(\w+)`、只用于**取值**，与校验用的严格版语义不同、不可互换。
        m = PROPOSAL_RE.search(p.read_text(encoding="utf-8"))
        return m.group(1) if m else "—"
    return {"manager": pick("2_research/manager.md"),
            "trader": pick("3_trading/trader.md"),
            "pm": pick("5_portfolio/decision.md")}


def _zip_text(zp: Path, name: str) -> str | None:
    """从审计包 `_source.zip` 里读一个条目；不存在 / 坏包返回 None。

    ★ 2026-10-10 新增。此前本工具只认**散落目录**，而封存后
    `{evidence,drafts,analysis}` 被清空**本就是正常终态**（见 `_seal_run.py`），
    ⇒ 「证据包通道」列退化成 `—`、「有分析JSON」列退化成 `✗`，
    **看起来像缺数据，其实是判据太窄**（铁律 3 的同类：静默降级、外观正常）。
    更糟的是 `has_drafts` 早已用 `_sealed_with` 做了 zip 回退
    ⇒ **同一张表里三列判据不一致**：一列认审计包、两列不认。
    判据统一为「散落文件存在 **或** 树内审计包包含它」。
    """
    if not zp.exists():
        return None
    try:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if n == name or n.endswith("/" + name):
                    return z.read(n).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    return None


def _manifest_has(tree: Path, prefix: str) -> bool:
    """当轻量导出包剔除了二进制 `_source.zip` 时，回退核对同目录的 `SOURCE_MANIFEST.json`。"""
    mp = tree / "SOURCE_MANIFEST.json"
    if not mp.exists():
        return False
    try:
        contents = json.loads(mp.read_text(encoding="utf-8")).get("contents") or []
        return any(str(n).startswith(prefix) for n in contents)
    except Exception:  # noqa: BLE001
        return False


def evidence_facts(ticker: str, date: str, tree: Path | None = None) -> dict:
    """从证据包提取三项事实：通道健康度 / **末根 bar 日期** / **K 线根数**。

    ★ 2026-10-11 新增（O2）。`last_bar` + `bars` 构成一棵树的**内容身份**，
    用于识破「标签不同、底层数据相同」的重复渲染（见 `scan()` 异常一之补）。
    证据不可得时对应字段为 `None`（**不是 0 / "—"**，以免被当成真实值参与比较）。
    """
    name = f"{ticker}_{date}.md"
    p = EVID / name
    txt = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
    if txt is None and tree is not None:      # 已封存 ⇒ 回退到树内审计包
        txt = _zip_text(tree / "_source.zip", f"evidence/{name}")
    if txt is None:
        ch_fallback = "—"
        if tree is not None and (tree / "RUN.json").exists():
            try:
                notes = json.loads((tree / "RUN.json").read_text(encoding="utf-8")).get("notes") or ""
                mc = re.search(r"通道\s*(\d+\s*/\s*\d+)", notes)
                if mc:
                    ch_fallback = mc.group(1).replace(" ", "")
            except Exception:  # noqa: BLE001
                pass
        return {"channels": ch_fallback, "last_bar": None, "bars": None}
    m = re.search(r"成功:\s*(\d+)\s*/\s*(\d+)", txt)
    # ★ 2026-10-12 修：`bars` 行**可能带前导空格**（实测旧包内为 `  - bars: 65`，
    #   而新包内是行首 `- bars: 65`）⇒ 正则**不得锚定行首**，否则老包一律拿不到根数。
    #   旁证：`_derive_stock.py::stat()` 用的是**无锚点**的 `-\s*bars:`，所以它一直是对的；
    #   错的是本函数。此前这条 bug 让 GOOG 旧树报 `bars=None`，我据此误判成
    #   「旧采集器未写该字段」——**结论错了，根因是缩进**。
    mb = re.search(r"^[ \t]*-[ \t]*bars:[ \t]*(\d+)", txt, re.M)
    # ★★ 末根 bar —— **两条路径的排序相反，必须分别取值**（2026-10-12 修）：
    #    · §1 的 K 线表是**升序**（最旧 → 最新，表头写「最近 20 根 K 线」）
    #      ⇒ 末根 bar = **最后一条**匹配；
    #    · `### <指标>` 序列是**降序**（最新 → 最旧）
    #      ⇒ 末根 bar = **第一条**匹配。
    #    原实现两条路径都写 `re.search`（= 取第一条），于是 K 线表路径拿到的是
    #    **20 个交易日之前那一根**，字段名叫 `last_bar` 而值不是末根 —— 典型的
    #    「看着对、其实错」（该值在「同标的同根数的两棵树」之间恰好仍然一致，
    #    所以 O2 的重复检测碰巧仍能工作，掩蔽了错误）。实测证据：GOOG_20261010_024253
    #    的 K 线表首行 2026-09-11、末行 2026-10-08，旧实现返回 2026-09-11。
    kline = re.findall(
        r"^(\d{4}-\d{2}-\d{2})\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+\d+\s*$", txt, re.M)
    ind = re.search(r"^###\s+\S+\n```\n(\d{4}-\d{2}-\d{2}):", txt, re.M)
    if kline:
        last_bar = kline[-1]
    elif ind:
        last_bar = ind.group(1)
    else:
        last_bar = None
    return {"channels": f"{m.group(1)}/{m.group(2)}" if m else "?",
            "bars": int(mb.group(1)) if mb else None,
            "last_bar": last_bar}


def evidence_channels(ticker: str, date: str, tree: Path | None = None) -> str:
    return evidence_facts(ticker, date, tree)["channels"]


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
                        issues.append(f"[二级目录散落] {tr.relative_to(REPORTS).as_posix()}：标的目录下不应存放散落文件，应归入 _other/")
                        continue
                    m = TREE_RE.match(tr.name)
                    if not m:
                        issues.append(f"[二级非标准目录] {tr.relative_to(REPORTS).as_posix()}/：不符合报告树命名契约，应归入顶层 _other/")
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
                        if zp.exists():
                            try:
                                with zipfile.ZipFile(zp) as z:
                                    return any(n.startswith(prefix) for n in z.namelist())
                            except Exception:  # noqa: BLE001
                                return False
                        return _manifest_has(zp.parent, prefix)

                    if run and run.get("source_drafts"):
                        has_drafts = Path(run["source_drafts"]).exists() or _sealed_with(tr / "_source.zip", "drafts/")
                    else:
                        has_drafts = (DRAFTS / f"{ticker}_{date}").exists() or _sealed_with(tr / "_source.zip", "drafts/")
                    _facts = evidence_facts(ticker, date, tr)
                    rows.append({
                        "ticker": ticker, "date": date, "tree": tr.name,
                        "path": tr.relative_to(ROOT).as_posix(),
                        "n_files": len([p for p in tr.rglob("*") if p.is_file()]),
                        "ratings": ratings,
                        "channels": _facts["channels"],
                        "last_bar": _facts["last_bar"],
                        "bars": _facts["bars"],
                        "has_drafts": has_drafts,
                        "has_analysis": ((ANALYSIS / f"{ticker}_{date}.json").exists()
                                         or _sealed_with(tr / "_source.zip", f"analysis/{ticker}_{date}.json")),
                        "has_run": run is not None,
                    })
                    trees.setdefault((ticker, date), []).append(rows[-1])

    # ── 历史版本说明：同一标的/基准日按正常流程跑出的多棵树均属正规历史版本，
    #    统一在 INDEX.md 中按时间顺序完整保留与展示，不再作为卫生异常报警。

    # ── 异常二：报告树缺少对应草稿（无法再渲染）
    for r in rows:
        if not r["has_drafts"]:
            issues.append(f"[缺草稿] {r['ticker']} {r['date']} 的报告树既无散落草稿目录、"
                          f"审计包里也没有 drafts ⇒ 无法重新渲染：{r['tree']}")
    # ── 异常三：孤儿（有证据/草稿，却没有报告树）
    # 豁免：不属于 12 角色链路、且**不产出报告树**的专用通道/过程产物——
    # 它们本就以 evidence/ 为正规归宿（如 collect_treasury.py 内建的 OUT_DIR），
    # 「无报告树」是其设计预期而非堆积。
    # ★ 2026-10-10：豁免表已上提到 `wb_analysis/_contract.py`（唯一定义源），
    #   与 `_seal_run.py`、`scripts/_health.py` 共用 —— 此前三处各自为政，
    #   结果 `--orphans` 会把 TREASURY 当孤儿删掉。
    have = {(r["ticker"], r["date"]) for r in rows}

    def _age(p: Path) -> str:
        """★ 2026-10-11（O6）：孤儿消息必须带**滞留时长**。

        否则「在跑的轮次」（几分钟前刚写）与「已废弃的轮次」（挂了几小时）在报告里
        长得一模一样，操作者无从判断该等还是该清 —— 本机多会话并行时尤其致命。
        """
        try:
            hrs = (time.time() - p.stat().st_mtime) / 3600
        except OSError:
            return ""
        return f"（已滞留 {hrs:.1f} 小时）" if hrs >= 1 else f"（{hrs * 60:.0f} 分钟前，可能仍在写入）"

    for d in sorted(EVID.glob("*.md")) if EVID.exists() else []:
        if "derived" in d.name or "supplement" in d.name or ".pre_" in d.name:
            continue
        if is_non_tree_artifact(d.name):
            continue
        m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})", d.name)
        if m and (m.group(1), m.group(2)) not in have:
            issues.append(f"[孤儿证据] {d.name}：没有对应报告树{_age(d)}"
                          f" ⇒ 可一键处置 `_seal_run.py --orphans --apply`")
    for d in sorted(DRAFTS.iterdir()) if DRAFTS.exists() else []:
        if not d.is_dir():
            continue
        m = re.match(r"(.+?)_(\d{4}-\d{2}-\d{2})", d.name)
        if m and (m.group(1), m.group(2)) not in have:
            issues.append(f"[孤儿草稿] {d.name}/：没有对应报告树{_age(d)}"
                          f" ⇒ 可一键处置 `_seal_run.py --orphans --apply`")
    # ── 异常四：顶层散落 / 修复前快照 / 无清单的旧报告树
    # `ALLOWED_TOP`（目录门面：索引 / 说明 / 质量记分卡）已上提到 `wb_analysis/_paths.py`。
    if REPORTS.exists():
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
    rows_sorted = sorted(rows, key=lambda r: (r["ticker"], r["date"], r["tree"]))
    cur: dict[str, dict] = {}
    for r in rows_sorted:
        t = r["ticker"]
        if t not in cur or r["tree"] > cur[t]["tree"]:
            cur[t] = r
    L = ["# 报告索引（自动生成，勿手改）", "",
         f"- 生成时间：{_clock.now():%Y-%m-%d %H:%M:%S}",
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
          "| `_audit/` | 审计类文档（数据缺口审计等） |",
          "| `<TICKER>/` | 该标的的 12 角色报告树，按时间戳并列 |", ""]
    REPORTS.mkdir(parents=True, exist_ok=True)
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
