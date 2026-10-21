# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_scorecard.py [--trend]
"""报告质量记分卡：把「这一轮报告比上一轮好还是差」变成**可算的数字**。

## 为什么需要
用户目标是「**越用越好**」。但此前每轮质量只取决于当轮的用心程度，
**没有任何对照** ⇒ 涨了跌了都不知道，"越来越好"只是一种说法而不是事实。
⇒ 本工具从**已交付的报告树**里抽出 9 个客观指标，逐轮记账，让趋势可见。

## 指标（全部可从报告树 + 树内审计包算出，**不需要重新跑分析**）
| 指标 | 含义 | 好的方向 |
|---|---|---|
| `n_files` | 报告树文件数（13 = 12 角色 + complete_report；+RUN.json/SOURCE_MANIFEST.json/_source.zip = **16**） | =16 |
| `report_chars` | 完整报告字符数 | 大（信息量） |
| `channels_ok` / `channels_total` | 证据包通道完整度 | 高 |
| `decisive_gaps` | **决定性缺口数** | 低 |
| `gap_declared` | 关键缺口是否写进简报（防止下游看不见洞） | 是 |
| `verif_marks` | 报告里命中的**独立核验来源类别数**（SEC/EDGAR · Nasdaq · 官方/交易所 · 自算 · FRED · 行情源 · 独立核验，共 7 类） | 高 |
| `honest_marks` | 显式"数据缺失/不可得/无法判定"声明数（诚实度） | 高 |
| `conditional` | 是否含**条件式结论**（"若…则…"） | 是 |
| `traceable` | 是否有 `RUN.json` + `_source.zip`（可追溯/可验证） | 是 |

> ⚠️ 这些是**代理指标**，不是绝对质量。但同一套口径逐轮比较，**趋势是有意义的**：
> 通道变差、决定性缺口变多、诚实声明变少 ⇒ 质量在退，必须查为什么。

## 用法
  ./.venv/Scripts/python.exe wb_analysis/_scorecard.py            # 重算并写 reports/QUALITY.csv
  ./.venv/Scripts/python.exe wb_analysis/_scorecard.py --trend    # 只看趋势
"""
import argparse
import csv as _csv
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# ★ 2026-10-10：`TREE_RE` / 功能目录集原为本地字面量，与 `_reports_index.py` 逐字重复
#   ⇒ 单一来源 `wb_analysis/_paths.py`。
from wb_analysis._paths import FUNC_DIRS, TREE_RE, iter_report_trees  # noqa: E402
from wb_analysis import _clock

REPORTS = ROOT / "reports"
CSV = REPORTS / "QUALITY.csv"
SKIP = FUNC_DIRS

# ★ 2026-10-10 复盘：此前是 8 个**字面短语**（"SEC EDGAR" / "Nasdaq 官方" …），
#   而各席位在正文里统一写 "SEC"、写 "自算" ⇒ 只命中 1/8：属**低判别力代理指标**
#   （假阴性 —— 明明引了 EDGAR，指标却几乎不动）。改为按「**关键词族**」计数：
#   同一来源的多种写法算作一类，输出 0–7 的**类别数**，逐轮趋势才有意义。
VERIF_FAMILIES = (
    ("SEC/EDGAR", re.compile(r"SEC|EDGAR|10-K|10-Q|8-K")),
    ("Nasdaq", re.compile(r"Nasdaq|NASDAQ|纳斯达克")),
    ("官方/交易所", re.compile(r"官方|交易所|exchange")),
    ("自算/机算", re.compile(r"自算|机算|computed|自行计算|自行复算|本工具")),
    ("FRED", re.compile(r"FRED")),
    ("行情源", re.compile(r"yfinance|Yahoo|行情源|数据源|东方财富|同花顺")),
    ("独立核验", re.compile(r"独立核验|第三方核验|独立来源|已核验|交叉核验")),
)
HONEST_WORDS = ("数据缺失", "不可得", "无法判定", "未提供", "不可估计", "缺失项", "不可用", "无数据")
COND_WORDS = ("若", "如果", "条件式", "则改为", "则倾向")


def _load_existing_csv(csv_path: Path) -> dict[str, dict[str, str]]:
    """读取已有 QUALITY.csv 作为 `_source.zip` 离线时的回退缓存（以 tree 名为键）。"""
    if not csv_path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    try:
        with csv_path.open(encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f):
                tr_name = (row.get("tree") or "").strip()
                if tr_name and TREE_RE.match(tr_name):
                    out[tr_name] = row
    except Exception:  # noqa: BLE001
        return {}
    return out


def read_zip_texts(zp: Path) -> tuple[str, dict]:
    """返回 (审计包内全部 md/json 合并文本, 关键文件字典)。"""
    if not zp.exists():
        return "", {}
    blob, key = [], {}
    try:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if n.endswith((".md", ".txt", ".json")):
                    try:
                        t = z.read(n).decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        continue
                    blob.append(t)
                    if n.endswith(".gaps.json") or "gaps" in n:
                        try:
                            key["gaps"] = json.loads(t)
                        except Exception:  # noqa: BLE001
                            pass
                    if "0_brief" in n:
                        key["brief"] = t
    except Exception:  # noqa: BLE001
        return "", {}
    return "\n".join(blob), key


def score_tree(tr: Path, prev_cache: dict[str, dict[str, str]] | None = None) -> dict:
    m = TREE_RE.match(tr.name)
    ticker = m.group(1) if m else tr.name.split("_")[0]
    files = [p for p in tr.rglob("*") if p.is_file()]
    cr = tr / "complete_report.md"
    report = cr.read_text(encoding="utf-8") if cr.exists() else ""
    run = {}
    if (tr / "RUN.json").exists():
        try:
            run = json.loads((tr / "RUN.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            run = {}
    zp = tr / "_source.zip"
    blob, key = read_zip_texts(zp)

    # 证据包通道完整度：从审计包里的证据 md 找「成功: N/M」
    ch = re.search(r"成功:\s*(\d+)\s*/\s*(\d+)", blob)
    gaps = key.get("gaps") or {}
    decisive = gaps.get("decisive_count")
    if decisive is None and zp.exists():
        decisive = len([g for g in (gaps.get("gaps") or []) if g.get("decisive")])
    # 关键缺口是否在简报里声明（用台账的 kw 校验，与门禁同一口径）
    gap_declared = ""
    brief = key.get("brief") or ""
    if decisive:
        dec = [g for g in (gaps.get("gaps") or []) if g.get("decisive")]
        if brief:
            miss = [g for g in dec if not any(k in brief for k in (g.get("kw") or [g.get("label", "")]))]
            gap_declared = "no" if miss else "yes"

    channels_ok: int | str = int(ch.group(1)) if ch else ""
    channels_total: int | str = int(ch.group(2)) if ch else ""
    traceable = "yes" if (tr / "RUN.json").exists() and (zp.exists() or (tr / "SOURCE_MANIFEST.json").exists()) else ""

    # 若当前为剔除二进制 `_source.zip` 的轻量归档副本，从既有 QUALITY.csv 或 RUN.json 回填审计包指标
    prev = (prev_cache or {}).get(tr.name) or {}
    if not zp.exists() and prev:
        if channels_ok == "" and prev.get("channels_ok", "").isdigit():
            channels_ok = int(prev["channels_ok"])
        if channels_total == "" and prev.get("channels_total", "").isdigit():
            channels_total = int(prev["channels_total"])
        if decisive is None and prev.get("decisive_gaps", "").isdigit():
            decisive = int(prev["decisive_gaps"])
        if not gap_declared and prev.get("gap_declared"):
            gap_declared = prev["gap_declared"]

    return {
        "ticker": ticker,
        "tree": tr.name,
        "data_date": run.get("data_date", ""),
        "n_files": len(files),
        "report_chars": len(report),
        "channels_ok": channels_ok,
        "channels_total": channels_total,
        "decisive_gaps": decisive if decisive is not None else "",
        "gap_declared": gap_declared,
        "verif_marks": sum(1 for _n, rx in VERIF_FAMILIES if rx.search(report)),
        "honest_marks": sum(1 for w in HONEST_WORDS if w in report),
        "conditional": "yes" if sum(1 for w in COND_WORDS if w in report) >= 2 else "",
        "traceable": traceable,
        "scored_at": _clock.now().strftime("%Y-%m-%d %H:%M"),
    }


COLS = ["ticker", "data_date", "tree", "n_files", "report_chars", "channels_ok", "channels_total",
        "decisive_gaps", "gap_declared", "verif_marks", "honest_marks", "conditional", "traceable",
        "scored_at"]


def collect() -> list[dict]:
    # ★ 2026-10-15 修：使用 `iter_report_trees(REPORTS)`（强制校验 `TREE_RE.match(tr.name)`），
    #   防止 `reports/SKHY/_archive` 等非报告树子目录被当成报告树打分并产生 `ticker=""` 的脏行。
    prev_cache = _load_existing_csv(CSV)
    rows = [score_tree(tr, prev_cache) for _tk, tr in iter_report_trees(REPORTS)]
    return sorted(rows, key=lambda r: (r["ticker"], r["data_date"], r["tree"]))


def write_csv(rows: list[dict]) -> None:
    lines = [",".join(COLS)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in COLS))
    CSV.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def show(rows: list[dict]) -> None:
    print("=" * 118)
    print("报告质量记分卡（指标为代理值；**同一口径逐轮比较**才有意义）")
    print("=" * 118)
    print(f"{'标的':8s} {'基准日':11s} {'文件':>4s} {'报告字符':>8s} {'通道':>7s} "
          f"{'决定性缺口':>10s} {'缺口已声明':>10s} {'核验源':>6s} {'诚实声明':>8s} {'条件式':>6s} {'可追溯':>6s}")
    print("-" * 118)
    for r in rows:
        ch = f"{r['channels_ok']}/{r['channels_total']}" if r["channels_ok"] != "" else "—"
        print(f"{r['ticker']:8s} {str(r['data_date']):11s} {r['n_files']:4d} {r['report_chars']:8d} "
              f"{ch:>7s} {str(r['decisive_gaps']):>10s} {r['gap_declared'] or '—':>10s} "
              f"{r['verif_marks']:>6d} {r['honest_marks']:>8d} {r['conditional'] or '—':>6s} {r['traceable'] or '—':>6s}")

    # 按标的看趋势（同一标的多轮才有意义）
    multi = {}
    for r in rows:
        multi.setdefault(r["ticker"], []).append(r)
    multi = {k: v for k, v in multi.items() if len(v) > 1}
    if multi:
        print("\n" + "=" * 118)
        print("同标的逐轮变化（这才是「越用越好」的判据）")
        print("=" * 118)
        for tk, rs in sorted(multi.items()):
            print(f"\n  {tk}：")
            prev = None
            for r in rs:
                if prev is None:
                    print(f"    {r['data_date']} {r['tree']:26s} 基准")
                else:
                    def d(k, better="up"):
                        a, b = prev.get(k), r.get(k)
                        if not isinstance(a, int) or not isinstance(b, int) or a == b:
                            return "="
                        good = (b > a) if better == "up" else (b < a)
                        return "↑好" if good else "↓差"
                    print(f"    {r['data_date']} {r['tree']:26s} "
                          f"报告{d('report_chars')} · 通道{d('channels_ok')} · "
                          f"决定缺口{d('decisive_gaps', 'down')} · 核验源{d('verif_marks')} · 诚实{d('honest_marks')}")
                prev = r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trend", action="store_true")
    args = ap.parse_args()
    rows = collect()
    if not rows:
        print("（没有已交付的报告树）")
        return 0
    if not args.trend:
        write_csv(rows)
        print(f"[记分卡] 已写入 {CSV.relative_to(ROOT).as_posix()}（{len(rows)} 轮）\n")
    show(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
