# lifecycle: oneoff
# created: 2026-09-23
# serves: ERP 离线降级（FRED 不可达时）
# usage: ./.venv/Scripts/python.exe wb_analysis/_erp_offline.py
"""ERP 分位的离线重算（FRED 不可达时的降级路径）。

背景：2026-09-17 15:40 起 api.stlouisfed.org 与 fred.stlouisfed.org 全部超时
（同日 14:39 的采集仍能取到 FRED 数据，属瞬时性中断），erp_context.py 无法完成。

降级口径（所有输入均可追溯，无任何凭印象填写）：
  - 历史分布：wb_analysis/evidence/erp_history_sp500.json —— 2026-09-16 成功运行留下的
    442 个月度观测（1990-01 ~ 2026-09）。剔除 2 条 2026-09 的观测
    （其 DGS10 用的是不完整的 9 月均值 4.83，会污染分布），剩 440 条作为参照分布。
  - 当期分子（标普500 TTM PE）：26.04（multpl，2026-09-14 估值）→ 盈利收益率 3.84%。
  - 当期分母（DGS10 9 月均值）：由**今日证据包**中的 FRED 日度 DGS10 重算，
    9/1~9/15 共 10 个交易日；再叠加 9/16 决议后的 5.021%（外部核验）作为第二种口径。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = json.loads((ROOT / "wb_analysis/evidence/erp_history_sp500.json").read_text(encoding="utf-8"))

# 参照分布：剔除 2026-09 的两条（DGS10 口径不完整）
ref = [r for r in rows if r["date"] < "2026-09-01"]
vals = sorted(r["erp_pp"] for r in ref)
n = len(vals)

sep_daily_through_15 = [4.79, 4.79, 4.77, 4.78, 4.80, 4.83, 4.95, 4.96, 4.97, 5.00]  # 证据包 FRED DGS10
sep_daily_through_16 = sep_daily_through_15 + [5.021]                              # + 决议后收盘

mean_15 = round(sum(sep_daily_through_15) / len(sep_daily_through_15), 3)
mean_16 = round(sum(sep_daily_through_16) / len(sep_daily_through_16), 3)

pe = 26.04
ey = 100.0 / pe


def pctile(v: float) -> float:
    return round(sum(1 for x in vals if x < v) / n * 100, 1)


print(f"参照分布: {n} 个月度观测 ({ref[0]['date']} ~ {ref[-1]['date']})")
print(f"  中位数 {sorted(vals)[n // 2]:.2f} pp | 均值 {sum(vals) / n:.2f} pp | "
      f"最小 {min(vals):.2f} ({min(ref, key=lambda r: r['erp_pp'])['date']}) | "
      f"最大 {max(vals):.2f} ({max(ref, key=lambda r: r['erp_pp'])['date']})")
for p in (5, 10, 25, 75, 90, 95):
    print(f"  第 {p:>2} 百分位 {vals[max(0, min(n - 1, int(round(p / 100 * (n - 1)))))]:.2f} pp")
neg = [r for r in ref if r["erp_pp"] < 0]
print(f"  历史负 ERP 月份: {len(neg)} / {n} = {len(neg) / n * 100:.1f}%  |  最近一次 {neg[-1]['date']}")
print()
print(f"标普500 TTM PE {pe} -> 盈利收益率 {ey:.2f}%")
for label, rf in (("9/1~9/15 均值", mean_15), ("9/1~9/16 均值", mean_16), ("9/16 决议后即期", 5.021)):
    erp = round(ey - rf, 2)
    print(f"  DGS10 {label:<14} {rf:>6}%  ->  ERP {erp:>6} pp  ->  历史分位 {pctile(erp):>5}%")
print()
prev = [r for r in rows if r["date"] == "2026-08-01"][0]["erp_pp"]
print(f"对照：2026-08 读数 {prev} pp")
