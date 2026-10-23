# lifecycle: reusable
# created: 2026-10-19
# usage: ./.venv/Scripts/python.exe wb_analysis/collect_hk_stock.py 0700.HK 2026-10-16
"""港股个股**补充**采集器（westock CLI）—— 补主包的三类结构性缺口。

## 为什么需要它（2026-10-19）

`collect.py` 是美股口径的通用采集器：对港股个股能拿到行情/报表，但有三类通道天然拿不到：

| 缺口 | 现象（0700.HK 实测） | 本工具补什么 |
|---|---|---|
| 个股新闻 | `get_news` 返回 unavailable（§5 为空） | westock `news list`，20 条 |
| 港股特色资金 | 无南下、无卖空、无回购 | `fund south-holding` / `fund short` / `buyback` |
| 披露日历 | 只能推断财报日 | `disclosure`（给出确切日期） |
| 一致预期/评级 | 无 | `consensus` / `rating` |

产物：`wb_analysis/evidence/<T>_<date>.hk.md`（**补充包**，与主包并列，均作为 lint/precheck 的证据源）。

## 先决条件

主包 `<T>_<date>.md` 由 `collect.py` 生成（含 §1 行情、§3 快照、§4 三大报表）。
本工具**不替代**主包：它只补港股特色通道。主包缺失时会给出明确提示但继续采集
（补充包本身独立可用）。

## 退出码
0 = 补充包已写入；1 = 标的不是港股 / 补充包写入失败。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "wb_analysis" / "evidence"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._channel import ok_of  # noqa: E402
from wb_analysis._westock import filter_news_asof, run_westock  # noqa: E402

#: (章节标题, westock 子命令)
COMMANDS: list[tuple[str, list[str]]] = [
    ("1. 行情快照（基准日收盘）", ["quote"]),
    ("2. 技术指标（官方口径）", ["technical"]),
    ("3. 量化评分", ["score"]),
    ("4. 南下资金持仓", ["fund", "south-holding"]),
    ("5. 卖空数据", ["fund", "short"]),
    ("6. 公司回购（近期）", ["buyback"]),
    ("7. 业绩披露日历", ["disclosure"]),
    ("8. 券商一致预期", ["consensus"]),
    ("9. 机构评级与目标价", ["rating"]),
    ("10. 分红历史", ["dividend"]),
    ("11. 股东结构", ["shareholder"]),
    ("12. 港股个股新闻（近期）", ["news", "list"]),
]


def wcode(ticker: str) -> str:
    """`0700.HK` → `hk00700`；已带 hk 前缀则原样返回。"""
    t = ticker.strip().lower()
    if t.startswith("hk"):
        return t
    if t.endswith(".hk"):
        return "hk" + t[:-3].zfill(5)
    raise ValueError(f"不是港股代码：{ticker}（应形如 0700.HK）")


def collect(ticker: str, date: str) -> int:
    try:
        code = wcode(ticker)
    except ValueError as e:
        print(f"✗ {e}")
        return 1

    main = EVID / f"{ticker}_{date}.md"
    print(f"[港股补充采集] {ticker}（westock: {code}）基准日 {date}")
    if not main.exists():
        print(f"  ⚠ 主包不存在：{main.name}")
        print(f"    ⇒ 建议先跑：./.venv/Scripts/python.exe wb_analysis/collect.py {ticker} "
              f"--date {date} --allow-stale-date")
        print("    （本补充包可独立使用，但 §1/§3/§4 仍以主包为准）")

    parts = [
        f"# 港股补充证据包：{ticker} · 基准日 {date}",
        "",
        "> 来源：westock CLI（腾讯官方接口）。本文件补 `collect.py` 的港股结构性缺口：",
        "> ① 港股个股新闻（`get_news` 对 HK ticker 返回 unavailable）；",
        "> ② 港股特色资金结构（南下持仓 / 卖空 / 回购 / 机构持仓）；",
        "> ③ 业绩披露日历（确切日期）、一致预期、评级、分红。",
        "> 口径：港股，价格单位 HKD。**与主包并列，均为合法证据源。**",
        "",
    ]
    ok = 0
    failed: list[str] = []
    for title, cmd in COMMANDS:
        argv = cmd + [code]
        if cmd[0] == "quote":
            argv = ["quote", code, "--date", date]
        try:
            body = str(run_westock(argv)).strip()
        except Exception as e:  # noqa: BLE001
            body = f"(命令失败: {type(e).__name__}: {e})"
        good = ok_of(body)
        ok += good
        if not good:
            failed.append(title)
        # ★ 2026-10-20：新闻通道同样按 as-of 截断（与 A 股两个采集器共用同一实现）
        if cmd[0] == "news" and good:
            body, _n_drop = filter_news_asof(body, date)
            title = f"{title}（as-of {date}，晚于基准日者已剔除）"
            if _n_drop:
                body += "".join(["", "", f"> **as-of 过滤**：剔除 {_n_drop} 条晚于基准日 {date} 的条目。"])
        parts += [f"## {title}", "", body if body else "(空)", ""]

    out = EVID / f"{ticker}_{date}.hk.md"
    out.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    print(f"  ✓ {ok}/{len(COMMANDS)} 个通道有数据"
          + (f"；失败：{'、'.join(failed)}" if failed else ""))
    print(f"  ✓ 已写入 {out}（{out.stat().st_size:,} 字节）")
    print("  下一步：把该文件与主包一起传给 lint / precheck（--evidence 可多个）。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="港股个股补充采集器（westock）")
    ap.add_argument("ticker", help="港股代码，如 0700.HK")
    ap.add_argument("date", help="基准日，如 2026-10-16")
    a = ap.parse_args()
    return collect(a.ticker, a.date)


if __name__ == "__main__":
    raise SystemExit(main())
