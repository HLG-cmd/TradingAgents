# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/wb_deep_dive.py
"""WorkBuddy 深度投研流水线 —— 零 LLM 成本的一站式入口。

把原来的两阶段漏斗改造成「免费数据 + WorkBuddy 推理」：

    阶段一  量化多因子初筛（screener_engine，纯数学，零成本）
    阶段二  对优选标的采集全部免费证据（wb_analysis/collect，零 LLM）
    ────────  以上全部本地完成，不调用任何付费 API  ────────
    分析层  按 wb_analysis/FRAMEWORK.md 的 12 角色框架由 WorkBuddy 顶层模型完成
    渲染层  wb_analysis/assemble.py 生成与上游同构的报告树

用法：
    python quant/wb_deep_dive.py --pool nasdaq --top 3
    python quant/wb_deep_dive.py --pool sp500 --top 5
    python quant/wb_deep_dive.py --pool sp500_core --top 5
    python quant/wb_deep_dive.py --tickers NVDA,AMD,GOOG      # 跳过初筛，直接采证
    python quant/wb_deep_dive.py --pool nasdaq --top 3 --no-social   # 更快
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # quant/ 的上一级才是项目根
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.screener_engine import export_radar_csv, run_quant_screening
from quant.stock_pools import (
    NASDAQ_100,
    SP_500_CORE,
    get_latest_nasdaq_100,
    get_latest_sp500,
)
from wb_analysis.collect import collect_one  # noqa: E402

# ★ 2026-10-15：`sp500` 接入动态全量池 `get_latest_sp500()`（约 503 只），
#   原 99 只静态核心子集独立为 `sp500_core`，消除「池名 sp500 却只筛 99 只」的口径歧义。
POOLS = {"nasdaq": NASDAQ_100, "sp500": SP_500_CORE, "sp500_core": SP_500_CORE}


def _stage_one(pool_key: str | None, tickers: list[str], top: int):
    """阶段一：量化初筛。返回 (候选列表, 初筛明细文本)。"""
    if pool_key == "nasdaq":
        # 动态同步（当日缓存 -> Wikipedia -> 静态快照），失败会打印原因后降级
        universe = get_latest_nasdaq_100()
    elif pool_key == "sp500":
        universe = get_latest_sp500()
    else:
        universe = POOLS[pool_key] if pool_key else tickers
    label = {
        "nasdaq": "纳斯达克100",
        "sp500": "标普500全量",
        "sp500_core": "标普500核心(99只)",
    }.get(pool_key or "", "自定义")

    print(f"\n{'=' * 62}")
    print(f"阶段一：{label} 量化多因子初筛（{len(universe)} 只，零 LLM 成本）")
    print(f"{'=' * 62}")

    df = run_quant_screening(universe, top_n=top, pool_name=pool_key or "custom")
    if df.empty:
        return [], ""

    top_df = df.head(top)
    detail = top_df.to_string(index=False)

    print("\n四维 GARP 多因子雷达 Top 榜：")
    print(f"{'排名':<4}{'代码':<8}{'现价':>8}{'综合分':>7}{'质量分':>7}{'估值分':>7}{'成长分':>7}{'动量分':>7}{'PE':>8}{'ROE%':>8}{'60日%':>8}")
    for i, row in df.head(max(top, 10)).iterrows():
        mark = "→" if i < top else " "
        print(
            f"{mark}{i + 1:<3}{row['Ticker']:<8}{row['Price']:>8.2f}{row['综合量化分']:>7.1f}"
            f"{row.get('quality_score', 0):>7.1f}{row.get('val_score', 0):>7.1f}"
            f"{row.get('growth_score', 0):>7.1f}{row.get('trend_score', 0):>7.1f}"
            f"{str(row.get('PE', 'N/A')):>8}{str(row.get('ROE%', 'N/A')):>8}{row['60日涨幅%']:>8.1f}%"
        )

    failed = getattr(df, "failed_records", [])
    if failed:
        print(f"\n⚠️ 共有 {len(failed)} 只标的因数据缺失/退市被安全剔除 (如 {', '.join([f['ticker'] for f in failed[:5]])})")

    # 导出全量量化明细为 CSV —— 必须带 UTF-8 BOM，否则中文表头在中文 Windows 的
    # Excel 里会被按 GBK 解析，显示成「20鏃ユ定骞%」这类乱码。
    try:
        reports = PROJECT_ROOT / "reports" / "_datasets"
        reports.mkdir(parents=True, exist_ok=True)
        csv_path = reports / f"radar_{pool_key or 'custom'}_{dt.date.today().isoformat()}.csv"
        export_radar_csv(df, str(csv_path))
        print(f"\n量化明细已导出（UTF-8 BOM，Excel 可直接打开）: {csv_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n[WARN] CSV 导出失败: {type(exc).__name__}: {exc}")

    candidates = list(top_df["Ticker"])
    print(f"\n入选深度分析：{', '.join(candidates)}")
    return candidates, detail


def main() -> int:
    ap = argparse.ArgumentParser(description="WorkBuddy 深度投研流水线（零 LLM 成本）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pool", choices=sorted(POOLS), help="从股票池初筛（nasdaq / sp500 / sp500_core）")
    src.add_argument("--tickers", help="直接指定标的，逗号分隔，跳过初筛")
    ap.add_argument("--top", type=int, default=3, help="深度分析的标的数量（默认 3）")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="基准日期 YYYY-MM-DD")
    ap.add_argument("--lookback", type=int, default=365, help="行情/新闻回溯自然日数")
    ap.add_argument("--no-news", action="store_true", help="跳过新闻通道（更快）")
    ap.add_argument("--no-social", action="store_true", help="跳过 StockTwits/Reddit（更快）")
    args = ap.parse_args()

    if args.tickers:
        candidates = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        print(f"\n跳过初筛，直接分析指定标的：{', '.join(candidates)}")
    else:
        candidates, _ = _stage_one(args.pool, [], args.top)
        if not candidates:
            print("✗ 初筛未取得有效数据（检查网络/代理后重试）", file=sys.stderr)
            return 1

    print(f"\n{'=' * 62}")
    print(f"阶段二：采集免费证据包（{len(candidates)} 只，零 LLM 成本）")
    print(f"{'=' * 62}")

    results = []
    for i, tk in enumerate(candidates, 1):
        print(f"\n[{i}/{len(candidates)}] {tk}")
        try:
            res = collect_one(tk, args.date, args.lookback, not args.no_news, not args.no_social)
            ok = sum(1 for v in res["health"].values() if v == "ok")
            bad = [k for k, v in res["health"].items() if v in ("fail", "unavailable")]
            print(f"  [OK] 通道 {ok}/{len(res['health'])}  证据包: {res['md'].name}")
            if bad:
                print(f"  [WARN] 不可用: {', '.join(bad)}")
            results.append(res)
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] 采集失败: {type(exc).__name__}: {exc}")

    if not results:
        return 1

    print(f"\n{'=' * 62}")
    print("本地阶段完成。以下是需要 WorkBuddy 完成的推理部分：")
    print(f"{'=' * 62}")
    for res in results:
        print(f"\n【{res['ticker']}】")
        print(f"  证据包  : {res['md']}")
        if res.get("stub"):
            print(f"  待填分析: {res['stub']}")
        stats = res.get("stats") or {}
        if stats:
            bits = [f"最新收盘 {stats.get('latest_close')}"]
            for k in ("ret_20d", "ret_60d"):
                if k in stats:
                    bits.append(f"{k} {stats[k]:+.1f}%")
            print(f"  速览    : {' | '.join(bits)}")

    print(
        "\n下一步（由 WorkBuddy 顶层模型执行，无需任何付费 API）：\n"
        "  1. 读取上述证据包\n"
        "  2. 按 wb_analysis/FRAMEWORK.md 的 12 角色框架填写草稿目录\n"
        "  3. 运行 python wb_analysis/assemble.py --from-dir <草稿目录> 渲染报告树"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
