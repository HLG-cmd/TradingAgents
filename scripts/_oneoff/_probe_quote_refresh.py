# lifecycle: oneoff
"""GOOG / ^NDX 报价刷新探测（只读，不写证据包）。

用途：在 2026-09-29 基准日证据包已封存的前提下，探测 2026-09-30 这一交易日
当前处于什么状态（未开盘 / 盘中 / 已收盘），以及最新可得报价与技术指标。
本脚本不修改任何证据文件，只打印到 stdout。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import yfinance as yf  # noqa: E402


def probe(sym: str) -> None:
    print("=" * 72)
    print(f"### {sym}")
    t = yf.Ticker(sym)

    # 1) 日线最后 5 根 —— 判断 9-30 是否已收盘
    try:
        h = t.history(period="10d", interval="1d", auto_adjust=False)
        print(f"[daily] 共 {len(h)} 根，时区 {h.index.tz}")
        print(h.tail(5)[["Open", "High", "Low", "Close", "Volume"]].to_string())
    except Exception as e:  # noqa: BLE001
        print(f"[daily] 失败: {type(e).__name__} {e}")

    # 2) 1 分钟线最后 3 根 —— 看盘中最新价与当时戳
    try:
        m = t.history(period="1d", interval="1m", auto_adjust=False)
        if len(m):
            print(f"[1m] 共 {len(m)} 根，最后时间戳 {m.index[-1]}")
            last = m.iloc[-1]
            print(f"[1m] last O/H/L/C = {last['Open']:.4f}/{last['High']:.4f}/"
                  f"{last['Low']:.4f}/{last['Close']:.4f}  vol={last['Volume']}")
        else:
            print("[1m] 无数据")
    except Exception as e:  # noqa: BLE001
        print(f"[1m] 失败: {type(e).__name__} {e}")

    # 3) fast_info 快照
    try:
        fi = t.fast_info
        for k in ("last_price", "previous_close", "open", "day_high", "day_low",
                  "last_volume", "market_cap", "year_high", "year_low",
                  "fifty_day_average", "two_hundred_day_average"):
            v = getattr(fi, k, None)
            print(f"[fast_info] {k} = {v}")
    except Exception as e:  # noqa: BLE001
        print(f"[fast_info] 失败: {type(e).__name__} {e}")

    # 4) 期权到期日列表（看是否刷新到新的一天）
    try:
        exps = list(t.options or [])
        print(f"[options] 到期日 {len(exps)} 个：{exps[:4]} ... {exps[-2:]}")
    except Exception as e:  # noqa: BLE001
        print(f"[options] 失败: {type(e).__name__} {e}")
    print()


if __name__ == "__main__":
    for s in ("GOOG", "^NDX", "QQQ"):
        probe(s)
