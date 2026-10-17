# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_sum_re_coverage.py
"""刻画 `EXPR_RE`（原 SUM_RE）的**命中边界**：找出「本项目真实写法」中命不中的形态。

## 为什么查
评估报告称「SUM_RE 重写」已修好「正则恒不命中」。实测它**确实比原版强**（能命中
`1.202 − 1.1793 = 0.0227`），但我在真实报告里看到 **右侧带正号**的算式
（`4.1206% - 1.6571% = +2.463`）**命不中** —— 需要确认这是否是剩余缺口。

判据：正则要求 `=` 后紧跟数字，而真实文本是 `= +2.463`（`+` 在数字前）。

⚠️ 本脚本**只测不修**：先量化边界，再决定要不要改（避免§凭猜测改正则）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wb_analysis._audit_values import EXPR_RE  # noqa: E402

CASES = [
    # (说明, 文本, 是否期望命中)
    ("基本形态", "1.202 − 1.1793 = 0.0227", True),
    ("右侧带正号（本项目常见）", "4.1206% - 1.6571% = +2.463", True),
    ("右侧带正号+单位", "4.1206% - 1.6571% = +2.463 个百分点", True),
    ("左侧百分号", "1.5857% + 0.8571% = 2.4428%", True),
    ("日期干扰（须跳过）", "1982-1984=100", False),
    ("日期干扰2", "09-16=7.0bp", False),
    ("除法（非加减，不属算式）", "3.53 / 1.97 = 1.79", False),
]


def main() -> int:
    print("=" * 88)
    print("EXPR_RE 命中边界刻画")
    print("=" * 88)
    print(f"{'说明':32s} {'期望':4s} {'实际':4s} 结果")
    mismatch = []
    for desc, text, want in CASES:
        got = bool(EXPR_RE.search(text))
        ok = got == want
        if not ok:
            mismatch.append((desc, text, want, got))
        print(f"{desc:32s} {'✓' if want else '✗':4s} {'✓' if got else '✗':4s} "
              f"{'一致' if ok else '← 不一致'}   {text[:40]}")

    print()
    print("=" * 88)
    if mismatch:
        print(f"发现 {len(mismatch)} 处期望与实际不一致：")
        for desc, text, want, got in mismatch:
            print(f"  · {desc}：期望{'命中' if want else '不命中'}，实际{'命中' if got else '不命中'}")
            print(f"    文本：{text}")
    else:
        print("全部符合预期")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
