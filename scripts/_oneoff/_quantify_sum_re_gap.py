# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_quantify_sum_re_gap.py
"""量化「右侧带正负号算式」抓不到的影响面（先测规模再决定是否改正则）。

判据（铁律 10：设阈值前先测三个数）：
  · 真实写法总数
  · 当前正则抓到的数
  · 差集（缺口）—— 若为 0 则不是问题；若可观则值得修
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wb_analysis._audit_values import EXPR_RE  # noqa: E402

# 「形如算式但可能抓不到」：左侧 数% op 数% = ±数
LOOSE = re.compile(
    r"[\d.]+\s*%\s*[+\-\u2212\u2013\u2014]\s*[\d.]+\s*%\s*[=\uff1d]\s*[+\-\u2212\u2013\u2014]?\s*[\d.]+"
)


def main() -> int:
    total = 0
    missed: list[tuple[str, str]] = []
    reports = sorted(ROOT.glob("reports/**/complete_report.md"))
    print(f"扫描 {len(reports)} 份 complete_report.md")
    for f in reports:
        t = f.read_text(encoding="utf-8", errors="replace")
        for m in LOOSE.finditer(t):
            total += 1
            if not EXPR_RE.search(m.group(0)):
                missed.append((f.parent.name, m.group(0).strip()))
    print()
    print("=" * 84)
    print(f"① 「数% op 数% = ±数」形算式总数：{total}")
    print(f"② 其中 EXPR_RE 抓不到（缺口）：{len(missed)}")
    hit = total - len(missed)
    print(f"③ 抓到的：{hit}　⇒ 覆盖率 {(hit/total*100 if total else 0):.1f}%")
    print("=" * 84)
    if missed:
        print("\n缺口样本（前 12）：")
        for name, s in missed[:12]:
            print(f"  [{name[:24]:24s}] {s}")
        print()
        print("⇒ 缺口可观 ⇒ 值得修：`=` 后允许带显式正负号。")
    else:
        print("\n⇒ 无缺口，无需改动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
