# lifecycle: reusable
# created: 2026-10-09
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_snapshot_consistency.py NVDA 2026-10-09
"""快照**内部自洽性**检测 —— 专门抓「通道报 ok，但数值与同一份快照的基点矛盾」。

## 为什么需要一个新检测器（2026-10-09 NVDA 轮）

既有门禁全部只看「通道是否成功」：
- `channel_health` 的 35 项 —— 只看调用成败；
- `_placeHOLDER_MARKERS` —— 只看返回是不是空态串；
- `_audit_empty_sections.py` —— 只看节里有没有正文。

**但有一类失真三者都抓不到：通道成功返回、内容非空、格式合法，
数值却与同一份快照里其它已核验的字段互相矛盾。**（与铁律 26「序关系/恒等式」同族，
区别是：铁律 26 查的是报表，本检测器查的是**估值快照的派生比率**。）

实测（NVDA 基准日 2026-10-09）：

| 字段 | 值 | 检验 |
|---|---|---|
| `EPS (TTM)` | 7.91 | 已由 SEC 季报自算精确核验（192,880M / 24,514M = 7.8682） |
| `Forward EPS` | 15.9146 | **是 TTM 的 2.01 倍** |
| `Forward PE` | 14.4226 | ⇒ 隐含未来 12M 净利 384.3B = 已核验 TTM 的 **+99.2%** |
| `PEG` | 0.28 | 完全建立在上面这个 forward 之上 |

而 `Forward PE 14.4x` / `PEG 0.28` 恰恰是整个多头叙事里最锋利的一把刀
—— **它不需要在工作、只需要「看起来工作」，就已经完成了误导。**

## 判据（只做比值，不做价值判断）

`forward_eps / eps_ttm` 超过 `MAX_FORWARD_RATIO`（默认 1.5）⇒ 报**可疑**。

阈值怎么定的（按铁律 10「设阈值先测三个数」）：
- **真该警惕的量级**：NVDA 2.01 倍（隐含净利翻倍）；
- **正常成长股的合理区间**：年增 20~40% ⇒ 1.2~1.4 倍；
- **周期股/扭亏股的低基数反弹**：可能到 2~3 倍，但它同时必然伴随 TTM EPS 极小。

⇒ 取 **1.5** 落在「正常成长」与「可疑翻倍」之间。
但如上所述，低基数场景会假阳性 ⇒ 因此本检测器**只报 WARN 不断言**，
并把最终裁决权交给「能否用 SEC 自算 TTM 交叉验证」。

⚠️ **本检测器不做的事**：不修改证据包、不删除字段、不改变评级。
   它只把可疑项结构化输出，让人能把它登记进缺口台账。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

# 正常成长 / 可疑翻倍 之间的间隙，见 docstring 的定标过程
MAX_FORWARD_RATIO = 1.5


def load_snapshot(ticker: str, date: str, ev_path: Path | None = None) -> dict[str, float]:
    """从证据包 §3「基本面快照」里解析 `Key: value` 形式的标量字段。"""
    out: dict[str, float] = {}
    for key, val in _load_snapshot_raw(ticker, date, ev_path).items():
        try:
            out[key] = float(val)
        except ValueError:
            continue
    return out


def _load_snapshot_raw(ticker: str, date: str, ev_path: Path | None = None) -> dict[str, str]:
    """解析 §3 快照的**全部** `Key: value`（含字符串字段，如 Currency / Financial Currency）。

    ⚠️ 字符串字段必须单独取 —— 旧版 `load_snapshot` 用 `float()` 过滤，
    `Currency: USD` 会被 `ValueError` 静默丢弃，币种检测就失去了唯一输入。
    """
    ev = ev_path if ev_path else (ROOT / "wb_analysis" / "evidence" / f"{ticker}_{date}.md")
    if not ev.exists():
        return {}
    text = ev.read_text(encoding="utf-8")
    m = re.search(r"## 3\. 基本面快照\s*```(.*?)```", text, re.S)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" not in line or line.strip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    return out


def check(ticker: str, date: str, max_ratio: float = MAX_FORWARD_RATIO, ev_path: Path | None = None) -> list[dict]:
    """返回可疑项列表。列表为空 ⇒ 未发现内部矛盾。"""
    snap = load_snapshot(ticker, date, ev_path)
    findings: list[dict] = []

    # ★★★ 2026-10-15 新增：币种一致性（**必须先于其它检查**）。
    #   实测 SKHY（SK 海力士美股 ADR）：`Currency: USD` 而 `Financial Currency: KRW`
    #   ⇒ 快照把美元价格/市值与韩元财报混算，产出「净利率 85.6%」「Forward EPS 34.48」。
    #   本项是**根因**，后面的 forward_eps / forward_pe 可疑往往是它的后果 ⇒ 排在首位。
    raw = _load_snapshot_raw(ticker, date, ev_path)
    cur = (raw.get("Currency") or "").strip().upper()
    fin_cur = (raw.get("Financial Currency") or "").strip().upper()
    if cur and fin_cur and cur != fin_cur:
        findings.append({
            "label": "currency_mismatch",
            "severity": "suspect",
            "currency": cur,
            "financial_currency": fin_cur,
            "detail": (
                f"快照的价格/市值口径为 {cur}，而财务报表口径为 {fin_cur} ⇒ 两套币种被**混算**。"
                f"跨币种推出的倍数与每股指标（PE / Forward PE / PEG / EPS / PB / Book Value）"
                f"以及一切带币种的绝对金额（Market Cap / Revenue / Net Income / FCF / EBITDA）"
                f"**全部不可信**；只有**纯比率**（Profit Margin / Operating Margin / ROE / ROA / Current Ratio）可用。"
            ),
        })

    eps_ttm = snap.get("EPS (TTM)")
    fwd_eps = snap.get("Forward EPS")
    if eps_ttm and fwd_eps and eps_ttm > 0:
        ratio = fwd_eps / eps_ttm
        if ratio > max_ratio:
            findings.append({
                "label": "forward_eps",
                "severity": "suspect",
                "eps_ttm": eps_ttm,
                "forward_eps": fwd_eps,
                "ratio": round(ratio, 3),
                "detail": (
                    f"Forward EPS {fwd_eps} 是 EPS(TTM) {eps_ttm} 的 {ratio:.2f} 倍，"
                    f"超过 {max_ratio} ⇒ 前瞻盈利隐含近乎翻倍的增长。"
                ),
            })

    # 同族：Forward PE 隐含的净利 vs 市值/PE(TTM) 隐含的净利
    mc = snap.get("Market Cap")
    pe_ttm = snap.get("PE Ratio (TTM)")
    fwd_pe = snap.get("Forward PE")
    if mc and pe_ttm and fwd_pe and pe_ttm > 0 and fwd_pe > 0:
        ni_ttm_implied = mc / pe_ttm
        ni_fwd_implied = mc / fwd_pe
        growth = ni_fwd_implied / ni_ttm_implied - 1
        if growth > 0.5:
            findings.append({
                "label": "forward_pe",
                "severity": "suspect",
                "growth_implied": round(growth, 4),
                "ni_ttm_implied": round(ni_ttm_implied),
                "ni_fwd_implied": round(ni_fwd_implied),
                "detail": (
                    f"Forward PE {fwd_pe} 隐含净利 {ni_fwd_implied:,.0f}，"
                    f"比 PE(TTM) 隐含的 {ni_ttm_implied:,.0f} 高 {growth*100:.1f}%。"
                ),
            })
    return findings


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="快照内部自洽性检测")
    ap.add_argument("ticker", help="标的代码")
    ap.add_argument("date", help="基准日期 YYYY-MM-DD")
    ap.add_argument("--evidence", default=None, help="证据包路径（可选）")
    ap.add_argument("--draft-dir", default=None, help="草稿目录（若指定则校验简报是否已声明归因）")
    args = ap.parse_args()

    ev_p = Path(args.evidence).resolve() if args.evidence else None
    findings = check(args.ticker, args.date, ev_path=ev_p)

    print("=" * 92)
    print(f"快照内部自洽性检测 · {args.ticker} · 基准日 {args.date}")
    print("=" * 92)
    if not findings:
        print("  ✓ 未发现快照字段间的内部矛盾或无快照段落。")
        return 0

    declared = False
    if args.draft_dir:
        draft = Path(args.draft_dir)
        brief = draft / "0_brief.md"
        if brief.exists():
            btext = brief.read_text(encoding="utf-8")
            # 判据：简报中是否提到了 Forward EPS 异常、翻倍、或前瞻/TTM 自算核验
            if any(k in btext for k in ("Forward EPS", "前瞻", "自算", "翻倍", "季报核验", "TTM核验")):
                declared = True

    for f in findings:
        print(f"\n  ⚠ [{f['severity']}] {f['label']}")
        for k, v in f.items():
            if k in ("label", "severity"):
                continue
            print(f"      {k:18s} {v}")

    if declared:
        print(f"\n  ✓ 虽有 {len(findings)} 项快照可疑，但简报 0_brief.md 中已声明并交叉比对。")
        return 0
    else:
        print(f"\n  ⇒ 共 {len(findings)} 项可疑未在简报中声明。**须在 0_brief.md 中归因或登记为缺口。**")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
