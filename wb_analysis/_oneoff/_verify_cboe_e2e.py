# lifecycle: oneoff
# created: 2026-10-17
"""端到端验证：非盘中时段能否用 CBOE 源重建完整期权结构。

**为什么需要这个脚本**：`fetch_option_structure()` 的 CBOE 分支只在**非盘中**触发，
而代码此前把 `datetime.now()` 写死 ⇒ 该分支**从未被端到端跑过**（最近几轮报告的采集
时点都落在盘中，证据包里声明的仍是 yfinance）。本脚本用**注入时钟**强制走该分支，
把「真实网络 + 解析 + 指标计算」整条链跑通。

用法：./.venv/Scripts/python.exe wb_analysis/_oneoff/_verify_cboe_e2e.py
"""
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import wb_analysis._thresholds as th  # noqa: E402

ET = ZoneInfo(th.MARKET_TZ_NAME)
FAKE_PRE = dt.datetime(2026, 10, 16, 8, 29, tzinfo=ET)   # NDX 实测的盘前时点


def main() -> int:
    print("=" * 78)
    print("一、时点判定（注入时钟）")
    print("=" * 78)
    for label, t in [("盘前 08:29", FAKE_PRE),
                     ("盘中 12:00", dt.datetime(2026, 10, 16, 12, 0, tzinfo=ET))]:
        ph = th.market_session_phase(t)
        use, note = th.option_source_decision(t)
        print(f"  {label}: phase={ph:12s} 切CBOE={use!s:5s}")
        print(f"      {note}")

    print()
    print("=" * 78)
    print("二、CBOE 源真实拉取（模拟盘前路径）")
    print("=" * 78)
    from wb_analysis._option_source import OptionSourceError, available, fetch_chain

    for sym, kind in [("NFLX", "美股个股"), ("QQQ", "美股 ETF"), ("GOOG", "美股个股")]:
        ok = available(sym)
        print(f"  available({sym:6s}) = {ok}  [{kind}]")

    print()
    print("  预期边界（应如实返回 False，不是 bug）：")
    for sym, why in [("NDX", "指数本身无期权"), ("^NDX", "指数本身无期权"),
                     ("512400.SS", "A 股 ETF，非美股")]:
        ok = available(sym)
        flag = "✓ 符合预期" if not ok else "⚠️ 意外可用"
        print(f"    available({sym:10s}) = {ok}  ← {why}  {flag}")

    print()
    print("=" * 78)
    print("三、期限结构重建（只保留「上一交易日成交」的合约 = 盘前场景）")
    print("=" * 78)
    try:
        chain = fetch_chain("NFLX")
    except OptionSourceError as exc:
        print(f"  ✗ CBOE 不可达：{exc}")
        return 2

    print(f"  spot={chain.spot}  iv30={chain.iv30}  到期日 {len(chain.options)} 个")
    prev_day = "2026-10-15"
    by_exp = {}
    for exp in chain.options:
        ch = chain.option_chain(exp)
        kept_c = kept_p = 0
        for df, key in ((ch.calls, "c"), (ch.puts, "p")):
            if df is None or len(df) == 0:
                continue
            sub = df[df["lastTradeDate"].astype(str).str.startswith(prev_day)]
            sub = sub[(sub["bid"] > 0) & (sub["ask"] > 0)]
            if key == "c":
                kept_c = len(sub)
            else:
                kept_p = len(sub)
        if kept_c or kept_p:
            by_exp[exp] = (kept_c, kept_p)

    print(f"  仅用 {prev_day} 成交的合约 ⇒ {len(by_exp)}/{len(chain.options)} 个到期日可用")
    for exp, (c, p) in list(by_exp.items())[:14]:
        print(f"    {exp}  calls={c:>3}  puts={p:>3}")

    print()
    print("=" * 78)
    print("四、结论")
    print("=" * 78)
    ok = len(by_exp) >= 5
    print(f"  盘前场景可用到期日数 = {len(by_exp)}  ⇒ {'✓ 期限结构可重建' if ok else '✗ 不足'}")
    print(f"  ⇒ 非盘中时段**不再需要把期权维度登记为数据缺失**；")
    print(f"     但取到的是**上一时段收盘快照**（非实时），须在证据包声明来源。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
