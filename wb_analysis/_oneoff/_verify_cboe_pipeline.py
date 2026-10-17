# lifecycle: oneoff
# created: 2026-10-17
"""端到端验证（完整链）：注入盘前时钟 → `fetch_option_structure` 走 CBOE → 产出 IV/偏斜。

与同目录 `_verify_cboe_e2e.py` 的区别：那份验证「CBOE 原始数据能否重建期限结构」，
本份验证**采集器的完整解析链**（过滤 → 选样 → IV → 偏斜 → 分级）在 CBOE 分支下能否跑通，
以及 `source` / `source_note` 两个声明字段是否被正确写出（下游靠它们渲染证据包）。

用法：./.venv/Scripts/python.exe wb_analysis/_oneoff/_verify_cboe_pipeline.py NFLX
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
FAKE_PRE = dt.datetime(2026, 10, 16, 8, 29, tzinfo=ET)


def main() -> int:
    sym = sys.argv[1] if len(sys.argv) > 1 else "NFLX"
    print("=" * 78)
    print(f"完整链端到端：{sym}（强制走 CBOE 分支）")
    print("=" * 78)

    # 1) 注入时钟：把 option_source_decision 钉在「盘前」
    orig = th.option_source_decision
    th.option_source_decision = lambda now=None: orig(FAKE_PRE)
    import wb_analysis.collect_index as ci
    use, note = ci._should_use_cboe_source()
    print(f"  注入时钟 → _should_use_cboe_source() = {use}")
    print(f"  {note}")

    # 2) 跑完整解析链
    print()
    print("  调用 fetch_option_structure()（真实网络 + 完整解析链）...")
    res = ci.fetch_option_structure(sym)

    if "error" in res:
        print(f"  ✗ 返回 error: {res['error']}")
        return 2

    print()
    print("=" * 78)
    print("结果")
    print("=" * 78)
    print(f"  iv_grade       = {res.get('iv_grade')}")
    print(f"  iv_available   = {res.get('iv_available')}")
    print(f"  source         = {res.get('source')}")
    print(f"  source_note    = {str(res.get('source_note'))[:100]}")
    print(f"  spot           = {res.get('spot')}")
    print(f"  div_yield      = {res.get('div_yield')}")
    print()
    rows = res.get("by_expiry") or []
    print(f"  选中到期日 {len(rows)} 个：")
    hdr = f"    {'到期':12s} {'天':>4s} {'C/P':>7s} {'P/C':>7s} {'ATM_C':>8s} {'ATM_P':>8s} {'25Δ偏斜':>9s}"
    print(hdr)
    for r in rows:
        print(f"    {r.get('expiry'):12s} {r.get('days'):>4} "
              f"{r.get('n_quoted_call')}/{r.get('n_quoted_put')!s:>3s} "
              f"{str(r.get('pc_volume')):>7s} "
              f"{str(r.get('atm_call_iv')):>8s} {str(r.get('atm_put_iv')):>8s} "
              f"{str(r.get('skew_25d_pp')):>9s}")

    # 3) 断言关键声明字段
    print()
    print("=" * 78)
    checks = [
        ("source 必须标为 cboe_delayed", res.get("source") == "cboe_delayed"),
        ("source_note 必须写明快照非实时",
         "上一时段收盘快照" in str(res.get("source_note"))),
        ("iv_grade 不得为 NONE（说明数据可用）", res.get("iv_grade") not in (None, "NONE")),
        ("iv_available 必须为 True", res.get("iv_available") is True),
        ("选中到期日为 1~3 个（设计：TARGETS 近月优先，picked_rows[:3]）", 1 <= len(rows) <= 3),
        ("全体扫描面 >= 10 个到期日", len(res.get("all_expiry_scan") or []) >= 10),
        ("至少一个到期日算出 25Δ 偏斜或 ATM IV",
         any(r.get("skew_25d_pp") is not None or r.get("atm_call_iv") is not None
             for r in rows)),
    ]
    failed = 0
    for name, ok in checks:
        mark = "✓" if ok else "✗"
        if not ok:
            failed += 1
        print(f"  {mark} {name}")

    th.option_source_decision = orig
    print()
    if failed:
        print(f"✗ {failed} 项未通过")
        return 1
    print("✓ 全部通过：CBOE 分支端到端可用，声明字段齐备。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
