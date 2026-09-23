# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/erp_context.py
"""股权风险溢价（ERP）的历史分位计算器 —— 解决「ERP 是偏低还是极端」缺少基准的问题。

**为什么需要它**

2026-09-16 的 NDX 分析得出一条关键结论：纳指 100 的聚合盈利收益率为 3.56%，
而 10 年期美债为 4.96%，**股权风险溢价 = −1.40 个百分点**。
但报告只能说出「这是负的」，**无法回答「−1.40pp 在历史上处于什么位置」** ——
没有基准，就无法判断它是「需要立即修正的极端错价」还是「可持续的常见偏离」。

**数据来源（全部免费）**

  1) 标普 500 的 TTM PE 月度序列（1943 年至今，约 950 个观测）—— multpl.com 公开表格
  2) 10 年期美债收益率（FRED: DGS10）日度历史 —— FRED API（需 .env 中的 FRED_API_KEY）

**方法**

    ERP = 盈利收益率 − 无风险利率 = (1 / PE) × 100 − DGS10

将 PE 月度序列与 DGS10 的月度均值对齐后，即得到 ERP 的历史分布，
进而可定位当期值所处的百分位。

**必须声明的局限**

  - 本计算基于**标普 500**，作为纳指 100 的**代理基准**。两者的无风险利率项完全相同，
    但估值结构与盈利收益率不同（纳指 100 更贵、盈利收益率更低，因此其 ERP 通常更低）。
    代理的合理性在于：驱动 ERP 时序变化的主要是无风险利率与市场整体的估值水平，
    这两个因素在两个指数间高度共享。
  - **纳指 100 自身的前瞻 PE 历史序列不可重建** —— 一致预期数据没有历史存档。
    因此纳指 100 自己的 ERP 历史分位只能靠**自建累积**（见 collect_index.py 的 ERP 序列记录器），
    本脚本提供的是市场层面的参考锚点。
  - multpl 的 PE 为 **TTM 口径**，与本项目 NDX 报告中的「前瞻 PE」口径不同，
    故本脚本的 ERP 与报告中的 ERP 数值不可直接相减比较，只可用于判断**量级与分位**。

用法：
    python wb_analysis/erp_context.py
    python wb_analysis/erp_context.py --start 1990-01-01
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import statistics
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

_MULT_URL = "https://www.multpl.com/s-p-500-pe-ratio/table/by-month"
_FRED_URL = (
    "https://api.stlouisfed.org/fred/series/observations"
    "?series_id=DGS10&api_key={key}&file_type=json&observation_start={start}"
)


def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_sp500_pe() -> list[tuple[dt.date, float]]:
    """抓取标普 500 的 TTM PE 月度序列（multpl.com）。

    解析陷阱（2026-09-16 实测踩到）：值单元格里可能含 HTML 实体 ``&#x2002;``（en-space 占位），
    若直接对原始单元格做数字正则，会从 ``&#x2002;`` 中抠出 **2002** 这个假值 ——
    实测导致 2025-11 至 2026-06 共 8 个月的 PE 被读成 2002.0，进而使整条 ERP 分布严重失真。
    正确做法：先 ``html.unescape`` 再去标签，最后才提数字；并加 PE 合理区间校验兜底。
    """
    import html as _html

    html_txt = _get(_MULT_URL)
    out: list[tuple[dt.date, float]] = []
    suspect: list[tuple[dt.date, float]] = []
    # 形如 <td>Sep 14, 2026</td><td><abbr title="Estimate">†</abbr>\n26.04</td>
    pat = re.compile(
        r"<td>\s*([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})\s*</td>\s*<td>(.*?)</td>",
        re.DOTALL,
    )
    for mon, day, year, cell in pat.findall(html_txt):
        m = _MONTHS.get(mon)
        if not m:
            continue
        cleaned = _html.unescape(cell)          # &#x2002; -> U+2002，不再是数字
        cleaned = re.sub(r"<[^>]+>", "", cleaned)  # <abbr ...>†</abbr> -> †
        num = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if not num:
            continue
        try:
            d = dt.date(int(year), m, int(day))
            v = float(num.group(1))
        except Exception:  # noqa: BLE001
            continue
        # 合理性校验：1943 年以来的 TTM PE 合理区间约 5~130
        #（2009-05 因盈利崩塌曾达 123.73；危机外的常态在 10~45 之间）
        if 5.0 <= v <= 150.0:
            out.append((d, v))
        else:
            suspect.append((d, v))

    if suspect:
        print(f"  ⚠ 剔除 {len(suspect)} 个超出合理区间的 PE 读数（疑似解析异常）:")
        for d, v in suspect[:10]:
            print(f"      {d} -> {v}")
        if len(suspect) > 10:
            print(f"      ... 另有 {len(suspect) - 10} 个")
    # 去重并按日期升序
    seen: dict[dt.date, float] = {}
    for d, v in out:
        seen[d] = v
    return sorted(seen.items())


def fetch_dgs10(start: str) -> dict[str, float]:
    """从 FRED 取 10 年期美债收益率日度序列，返回 {(YYYY-MM): 月度均值}。"""
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("缺少 FRED_API_KEY，无法获取 DGS10 历史序列")
    raw = json.loads(_get(_FRED_URL.format(key=key, start=start)))
    buckets: dict[str, list[float]] = {}
    for obs in raw.get("observations", []):
        v = obs.get("value")
        if v in (None, "", "."):
            continue
        try:
            fv = float(v)
        except ValueError:
            continue
        buckets.setdefault(obs["date"][:7], []).append(fv)
    return {k: sum(v) / len(v) for k, v in buckets.items() if v}


def build_erp(start: str) -> list[dict]:
    """对齐 PE 与 DGS10，逐月计算 ERP。"""
    pe_series = fetch_sp500_pe()
    dgs = fetch_dgs10(start)
    rows: list[dict] = []
    for d, pe in pe_series:
        if d < dt.date.fromisoformat(start) or pe <= 0:
            continue
        ym = d.strftime("%Y-%m")
        rf = dgs.get(ym)
        if rf is None:
            continue
        ey = 100.0 / pe  # 盈利收益率 %
        rows.append(
            {
                "date": d.isoformat(),
                "pe": round(pe, 2),
                "earnings_yield_pct": round(ey, 2),
                "dgs10_pct": round(rf, 2),
                "erp_pp": round(ey - rf, 2),
            }
        )
    return rows


def percentile_of(rows: list[dict], value: float) -> float:
    vals = sorted(r["erp_pp"] for r in rows)
    n = len(vals)
    if n == 0:
        return float("nan")
    below = sum(1 for v in vals if v < value)
    return round(below / n * 100, 1)


def _append_series(path: Path, row: dict) -> bool:
    """把当期读数追加到累积序列（按日期去重）。

    存在的意义：纳指 100 的**前瞻 PE 历史序列不可重建**（一致预期数据没有历史存档），
    因此它自身的 ERP 历史分位只能靠**自建累积** —— 每次分析追加一条，长期形成真实分布。
    """
    import csv

    exists = path.exists()
    if exists:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("date") == row["date"]:
                    return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["date", "sp500_pe_ttm", "earnings_yield_pct", "dgs10_pct", "erp_pp"])
        w.writerow([row["date"], row["pe"], row["earnings_yield_pct"], row["dgs10_pct"], row["erp_pp"]])
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="计算标普500 股权风险溢价（ERP）的历史分位")
    ap.add_argument("--start", default="1990-01-01", help="起始日期（DGS10 自 1962 年起可用，默认 1990）")
    ap.add_argument(
        "--append",
        action="store_true",
        help="把当期读数追加到累积序列 wb_analysis/_cache/erp_series.csv（按日期去重）",
    )
    args = ap.parse_args()

    try:
        rows = build_erp(args.start)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 计算失败: {type(exc).__name__}: {exc}")
        return 1

    if not rows:
        print("✗ 未取得可用数据（可能是网络或数据源格式变化）")
        return 1

    cur = rows[-1]
    vals = [r["erp_pp"] for r in rows]
    print(f"=== 标普500 股权风险溢价（ERP）历史上下文 ===")
    print(f"口径: ERP = 盈利收益率(1/PE, TTM) − 10年期美债收益率(DGS10 月度均值)")
    print(f"样本: {len(rows)} 个月度观测，{rows[0]['date']} ~ {cur['date']}")
    print()
    print(f"--- 最新读数（{cur['date']}）---")
    print(f"  PE (TTM)        : {cur['pe']}")
    print(f"  盈利收益率      : {cur['earnings_yield_pct']}%")
    print(f"  10 年期美债     : {cur['dgs10_pct']}%")
    print(f"  ERP             : {cur['erp_pp']} pp")
    print(f"  → 历史分位      : {percentile_of(rows, cur['erp_pp'])}%（越低越贵）")
    print()
    print("--- 分布 ---")
    print(f"  中位数          : {round(statistics.median(vals), 2)} pp")
    print(f"  均值            : {round(statistics.mean(vals), 2)} pp")
    print(f"  最小值          : {min(vals)} pp（{min(rows, key=lambda r: r['erp_pp'])['date']}）")
    print(f"  最大值          : {max(vals)} pp（{max(rows, key=lambda r: r['erp_pp'])['date']}）")
    for p in (5, 10, 25, 75, 90, 95):
        sv = sorted(vals)
        idx = max(0, min(len(sv) - 1, int(round(p / 100 * (len(sv) - 1)))))
        print(f"  第 {p:>2} 百分位     : {round(sv[idx], 2)} pp")
    print()
    neg = sum(1 for v in vals if v < 0)
    print(f"--- 负 ERP（股票盈利收益率低于无风险利率）出现的月份 ---")
    print(f"  次数: {neg} / {len(vals)}（{round(neg / len(vals) * 100, 1)}%）")
    if neg:
        neg_dates = [r["date"] for r in rows if r["erp_pp"] < 0]
        print(f"  最近一次负 ERP: {neg_dates[-1]}")
    print()
    print("--- 最近 12 个月 ---")
    for r in rows[-12:]:
        print(f"  {r['date']}  PE {r['pe']:>6}  盈利收益率 {r['earnings_yield_pct']:>5}%  DGS10 {r['dgs10_pct']:>5}%  ERP {r['erp_pp']:>6} pp")

    out = PROJECT_ROOT / "wb_analysis" / "_cache" / "erp_history_sp500.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"序列已保存: {out}")

    if args.append:
        series_path = PROJECT_ROOT / "wb_analysis" / "_cache" / "erp_series.csv"
        series_path.parent.mkdir(parents=True, exist_ok=True)
        if _append_series(series_path, cur):
            print(f"已追加到累积序列: {series_path}")
        else:
            print("该日期已在累积序列中，跳过追加。")
    else:
        print("提示: 加 --append 可把当期读数写入累积序列，用于长期自建 ERP 历史。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
