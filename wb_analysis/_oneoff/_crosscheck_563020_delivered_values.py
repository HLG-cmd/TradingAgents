# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_crosscheck_563020_delivered_values.py
"""交叉验证：**用独立算法**从交付树的 complete_report.md 里抽数字重算，验证内部自洽。

## 与 _recheck 的分工
`_recheck_563020_delivered.py` 查「旧值是否还在」（字符串层）。
本脚本**不看旧值**，而是**从报告里抽出实际写的数字，用底稿独立复算**
——两者算法独立，共同通过才算可信（对应项目原则：审计工具要有判别力）。

## 三类独立校验
1. **均线偏离**：报告里的「现价偏离」各值，用 (1.198−均线)/1.198 复算。
2. **价位距离**：报告里的「距入场 / 距现价」各值，分别用两个分母复算。
3. **盈亏比与派生量**：0.44:1 / 3.4 倍 / ATR 倍数 / 摊平月数，全部重算。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "563020" / "563020_20261016_133333" / "complete_report.md"

C = 1.198        # 收盘
E = 1.202        # 条件入场
MA = {"1.202": 1.202, "1.1859": 1.1859, "1.1793": 1.1793, "1.1658": 1.1658,
      "1.1495": 1.1495, "1.1597": 1.1597}
BOLL = {"1.2138": 1.2138, "1.1448": 1.1448}
STOPS = {"1.1597": 1.1597, "1.1793": 1.1793, "1.1859": 1.1859, "1.1448": 1.1448}
ATR = 1.079
DIV = 4.1206
TOL = 0.06      # 允许 0.06pp（报告保留 2 位小数）


def dev_now(x: float) -> float:
    """距现价（现价为分母）。"""
    return (C - x) / C * 100


def dev_entry(x: float) -> float:
    """距入场（入场价为分母）。"""
    return (E - x) / E * 100


def main() -> int:
    t = REPORT.read_text(encoding="utf-8")
    fails: list[str] = []
    checked = 0

    print("=" * 96)
    print("交叉验证：从交付报告抽数，用底稿独立复算（不依赖任何旧值）")
    print("=" * 96)

    # ── 1. 均线偏离（报告表格里“均线 | 值 | 偏离%”形式）──
    print("\n▸ 1. 均线偏离（现价口径，期望 = (1.198−MA)/1.198）")
    for price, v in MA.items():
        want = dev_now(v)
        # 抓「1.1859 | +1.01%」这类配对
        for m in re.finditer(rf"{re.escape(price)}\s*\|\s*\**([−\-+]?\d+\.\d+)%", t):
            got = float(m.group(1).replace("−", "-"))
            checked += 1
            if abs(got - want) > TOL:
                tag = "✓(派生口径)" if abs(abs(got) - abs((C - v) / v * 100)) <= TOL else "✗"
                line = f"   {tag} {price}: 报告 {got:+.2f}% vs 现价口径 {want:+.2f}%"
                print(line)
                if tag == "✗":
                    fails.append(line)

    # ── 2. 布林上下轨 ──
    print("\n▸ 2. 布林通道距离")
    for price, v in BOLL.items():
        want_now = dev_now(v)          # 距现价
        want_other = (C - v) / v * 100  # 以该价位为分母（派生层口径）
        for m in re.finditer(rf"{re.escape(price)}[^\n]{{0,30}}?([−\-+]?\d+\.\d+)%", t):
            got = float(m.group(1).replace("−", "-"))
            if abs(abs(got) - abs(want_now)) <= TOL or abs(abs(got) - abs(want_other)) <= TOL:
                checked += 1
            else:
                line = f"   ✗ {price}: 报告 {got:+.2f}%，两口径均不符（现价 {want_now:+.2f}% / 自为分母 {want_other:+.2f}%）"
                print(line)
                fails.append(line)

    # ── 3. 止损距离（距入场口径）──
    print("\n▸ 3. 止损距入场（期望 = (1.202−止损)/1.202）")
    for price, v in STOPS.items():
        want = dev_entry(v)
        for m in re.finditer(rf"{re.escape(price)}[^\n]{{0,42}}?(?:距入场|距离)[^\n]{{0,12}}?([−\-+]?\d+\.\d+)%", t):
            got = float(m.group(1).replace("−", "-"))
            checked += 1
            if abs(abs(got) - abs(want)) > TOL:
                line = f"   ✗ {price}: 报告 {got:+.2f}% vs 期望 {want:+.2f}%"
                print(line)
                fails.append(line)

    # ── 4. 关键派生量 ──
    print("\n▸ 4. 关键派生量复算")
    derived = [
        ("盈亏比 0.44:1", 0.44, (1.212 - E) / (E - 1.1793)),
        ("盈亏比 0.24:1", 0.24, (1.212 - E) / (E - 1.1597)),
        ("盈亏比 0.61:1", 0.61, (1.228 - E) / (E - 1.1597)),
        ("空间比 3.4 倍", 3.4, abs(dev_now(1.1448)) / dev_now(1.2138)),
        ("ATR 倍数 1.7×", 1.7, abs(dev_entry(1.1793)) / ATR),
        ("ATR 倍数 3.3×", 3.3, abs(dev_entry(1.1597)) / ATR),
        ("ATR 倍数 1.2×", 1.2, abs(dev_entry(1.1859)) / ATR),
        ("每月分红 0.343%", 0.343, DIV / 12),
        ("摊平 10.3 个月", 10.3, abs(dev_entry(1.1597)) / (DIV / 12)),
        ("摊平 13.9 个月", 13.9, abs(dev_entry(1.1448)) / (DIV / 12)),
        ("股息率溢价 +2.463pp", 2.463, DIV - 1.6571),
        ("规模 123.16 亿", 123.16, 103.02 * 1.1955),
    ]
    for label, stated, calc in derived:
        checked += 1
        ok = abs(stated - calc) <= max(abs(calc) * 0.02, 0.06)
        mark = "✓" if ok else "✗"
        print(f"   {mark} {label:22s} 报告 {stated:>7.3f} ｜ 复算 {calc:>7.3f}")
        if not ok:
            fails.append(f"   ✗ {label}: 报告 {stated} vs 复算 {calc:.3f}")

    print()
    print("=" * 96)
    print(f"共校验 {checked} 处数值；不符 {len(fails)} 处")
    if fails:
        for f in fails:
            print(f)
    print("=" * 96)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
