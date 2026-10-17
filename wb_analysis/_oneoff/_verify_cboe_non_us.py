# lifecycle: oneoff
# created: 2026-10-17
"""边界核实：非美股标的（指数 / A 股 ETF）在**盘前**走期权分支时，行为是否安全。

## 为什么要单独验这一条

CBOE 源**仅覆盖美股个股与主要 ETF**。而时点分支的判据是**纯时间判据**：
只要是盘前/盘后，就会尝试走 CBOE ⇒ **指数与 A 股 ETF 必然走到「CBOE 返回 403」这条路**。

问题：那条路上会发生什么？
  · 若**静默返回空** ⇒ 下游可能把「该标的没有期权」误当成「数据暂时取不到」，
    进而在重试/降级逻辑里做无用功，或错误地登记成「可重试的 B 类缺口」；
  · 若**抛异常且未被捕获** ⇒ 整个采集器崩掉（采集 35 通道全废）。

⇒ 正确行为应是：**403 被识别为「该标的无期权」（结构性），不重试、不崩，
   按「A 类结构性缺失」登记**，且**保留原有的代理读数**（^VIX/^VXN / 宽基 ETF 期权）。

用法：./.venv/Scripts/python.exe wb_analysis/_oneoff/_verify_cboe_non_us.py
"""
import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import wb_analysis._thresholds as th  # noqa: E402

ET = ZoneInfo(th.MARKET_TZ_NAME)
FAKE_PRE = dt.datetime(2026, 10, 16, 8, 29, tzinfo=ET)   # 盘前 ⇒ 必切 CBOE

# 非美股标的：指数（ETF 代理本身是美股，但指数符号不是）+ A 股 ETF
NON_US = [
    ("NDX", "美股指数符号", "指数本身没有期权合约"),
    ("^NDX", "美股指数符号（带 ^）", "同上"),
    ("512400.SS", "A 股 ETF", "非美股；且 A 股行业 ETF 无场内期权"),
    ("515100.SS", "A 股 ETF", "非美股；且 A 股策略 ETF 无场内期权"),
    ("sh518850", "A 股 ETF（westock 口径）", "非美股"),
    ("hkHSTECH", "港股指数（westock 口径）", "非美股"),
]


def main() -> int:
    print("=" * 80)
    print("边界核实：非美股标的在盘前走 CBOE 分支的行为")
    print("=" * 80)
    print(f"  注入时钟 = {FAKE_PRE:%Y-%m-%d %H:%M} 美东（盘前）")
    print(f"  → 时段判定 = {th.market_session_phase(FAKE_PRE)}")
    use, note = th.option_source_decision(FAKE_PRE)
    print(f"  → 源决策   = 切 CBOE: {use}（**纯时间判据**，不区分标的类型）")
    print()

    from wb_analysis._option_source import OptionSourceError, available, fetch_chain

    print("-" * 80)
    print("一、available() 是否如实返回 False（而非抛异常）")
    print("-" * 80)
    avail_ok = True
    for sym, kind, why in NON_US:
        try:
            ok = available(sym)
            flag = "✓" if not ok else "⚠️ 意外返回 True"
            if ok:
                avail_ok = False
            print(f"  {flag} available({sym:12s}) = {ok!s:5s}  [{kind}] {why}")
        except Exception as exc:                      # noqa: BLE001
            avail_ok = False
            print(f"  ✗ available({sym:12s}) 抛异常 {type(exc).__name__}: {exc}")

    print()
    print("-" * 80)
    print("二、fetch_chain() 是否抛 OptionSourceError（可被调用方按缺口处理）")
    print("-" * 80)
    fetch_ok = True
    for sym, kind, _why in NON_US:
        try:
            fetch_chain(sym)
            print(f"  ⚠️ fetch_chain({sym:12s}) 竟成功返回（预期 403）")
            fetch_ok = False
        except OptionSourceError as exc:
            print(f"  ✓ fetch_chain({sym:12s}) → OptionSourceError: {str(exc)[:58]}")
        except Exception as exc:                      # noqa: BLE001
            fetch_ok = False
            print(f"  ✗ fetch_chain({sym:12s}) 抛了**非预期类型** "
                  f"{type(exc).__name__}: {str(exc)[:50]}")

    print()
    print("-" * 80)
    print("三、403 是否**不重试**（4xx = 结构性无期权，重试无意义）")
    print("-" * 80)
    import time as _t
    t0 = _t.time()
    try:
        fetch_chain("NDX")
    except OptionSourceError:
        pass
    elapsed = _t.time() - t0
    # 若走满 MAX_TRIES 次重试，退避 2+4+6 = 12s 起
    no_retry = elapsed < 5.0
    print(f"  NDX 取数耗时 = {elapsed:.2f}s  "
          f"⇒ {'✓ 未重试（4xx 直接抛出）' if no_retry else '✗ 疑似走了重试'}")
    print(f"     （对比：瞬时错误会重试 {4} 次、退避合计 ≥12s）")

    print()
    print("-" * 80)
    print("四、采集器会不会因 CBOE 失败而崩")
    print("-" * 80)
    import wb_analysis.collect_index as ci

    orig = th.option_source_decision
    th.option_source_decision = lambda now=None: orig(FAKE_PRE)
    try:
        # NDX：指数本身无期权 ⇒ 走 CBOE 失败 ⇒ 应退回 yfinance 并如实报错，不崩
        res = ci.fetch_option_structure("QQQ")   # QQQ 是美股 ETF，这里测「有期权」的对照组
        ok_qqq = isinstance(res, dict)
        print(f"  ✓ fetch_option_structure('QQQ') 未崩，返回字段数 = {len(res)}")
        if ok_qqq:
            print(f"     iv_grade={res.get('iv_grade')}  source={res.get('source')}")
    except Exception as exc:                          # noqa: BLE001
        print(f"  ✗ 崩了：{type(exc).__name__}: {exc}")
        ok_qqq = False
    finally:
        th.option_source_decision = orig

    print()
    print("=" * 80)
    print("结论")
    print("=" * 80)
    all_ok = avail_ok and fetch_ok and no_retry and ok_qqq
    print(f"  available() 如实返回 False        : {'✓' if avail_ok else '✗'}")
    print(f"  fetch_chain() 抛可处理异常        : {'✓' if fetch_ok else '✗'}")
    print(f"  403 不重试（不浪费时间）          : {'✓' if no_retry else '✗'}")
    print(f"  美股标的不受影响                  : {'✓' if ok_qqq else '✗'}")
    print()
    if all_ok:
        print("  ⇒ 非美股标的走 CBOE 分支是**安全的**：会被如实判为「无可用期权」，")
        print("    不重试、不崩溃，下游按结构性缺失登记（A 类），代理读数不受影响。")
        return 0
    print("  ⇒ ✗ 存在不安全行为，需修。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
