# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_verify_expr_re_two_sided.py
"""`EXPR_RE` 修复的**双向验证**（走完整 `check_sums` 路径，而非只看正则）。

## 为什么要单独做（不能只看单测）
修完正则后，我的探针显示「日期干扰仍被 EXPR_RE 匹配」—— 但那是**预期的**：
`check_sums()` 里还有一道 `DATELIKE_RE` 过滤。**单看正则会误判成回归**。
⇒ 判据必须落在**完整路径**上：构造真实文件，跑 `check_sums()`，看三个方向：

① **正例（原缺口）**：`= +2.463` / `= −3.40` 形态必须能被抓出「不符」；
② **反例（不得误报）**：日期/年份区间、自洽算式、除法式**不得**被判为不符；
③ **回归**：原有 5 种真实写法仍须命中。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wb_analysis._audit_values import check_sums  # noqa: E402


def run_case(label: str, line: str, expect_bad: bool) -> bool:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "probe.md"
        p.write_text(line + "\n", encoding="utf-8")
        bad = check_sums(p)
    got_bad = bool(bad)
    ok = got_bad == expect_bad
    mark = "✓" if ok else "✗"
    verdict = "判不符" if got_bad else "判自洽"
    want = "判不符" if expect_bad else "判自洽"
    print(f"  {mark} {label:38s} 期望{want}｜实际{verdict}   {line[:46]}")
    return ok


def main() -> int:
    print("=" * 96)
    print("EXPR_RE 修复的双向验证（走完整 check_sums 路径）")
    print("=" * 96)
    results: list[bool] = []

    print("\n▸ ① 正例：原缺口的两种形态 —— 必须能抓出「不符」")
    # 4.1206 - 1.6571 = 2.4635（真值），故意写 +2.702 ⇒ 应判不符
    results.append(run_case("右侧带正号（错值）", "股息率溢价：4.3684% - 1.6669% = +3.10", True))
    results.append(run_case("右侧带 Unicode 负号（错值）", "净溢价：2.225% − 5.18% = −3.40", True))

    print("\n▸ ② 正例：同形态但**算对**的 —— 必须判自洽（不得误报）")
    results.append(run_case("右侧带正号（值正确）", "股息率溢价：4.1206% - 1.6571% = +2.463", False))
    results.append(run_case("右侧带 Unicode 负号（值正确）", "净溢价：2.225% − 5.180% = −2.955", False))

    print("\n▸ ③ 反例：不得误报（日期 / 除法 / 带单位）")
    results.append(run_case("日期区间 1982-1984=100", "- Units: Index 1982-1984=100", False))
    results.append(run_case("日期 09-16=7.0bp", "- （^TNX：09-16=7.0bp  09-17=2.0bp）", False))
    results.append(run_case("除法式", "3.53 / 1.97 = 1.79", False))
    results.append(run_case("带单位（自洽）", "1.202 − 1.1793 = 0.0227 元", False))

    print("\n▸ ④ 回归：原有真实写法仍须命中")
    results.append(run_case("10 项持仓合计（错值）",
                            "（算式：8.79+7.16+5.68+4.42+4.08+3.45+3.42+3.04+2.96+2.54 = 45.7%）", True))
    results.append(run_case("10 项持仓合计（自洽）",
                            "（算式：8.79+7.16+5.68+4.42+4.08+3.45+3.42+3.04+2.96+2.54 = 45.54%）", False))
    results.append(run_case("千分位（自洽）", "102,718 − 42,779 + 74,421 = 134,360", False))

    print()
    print("=" * 96)
    n_ok = sum(results)
    print(f"通过 {n_ok}/{len(results)}")
    print("✓ 双向验证全过：缺口已补，且未引入误报" if n_ok == len(results)
          else "✗ 有未通过项，需复查")
    print("=" * 96)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
