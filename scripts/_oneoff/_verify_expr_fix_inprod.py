# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_verify_expr_fix_inprod.py
"""验证 `EXPR_RE` 修复在**生产环境**真生效（用独立算法交叉核对，不复用被修的正则）。

## 为什么要独立算法
若用「我修的那个正则」去数它自己命中多少，是**循环论证**（自己验自己）。
⇒ 本脚本用**手工写的严格解析**（不 import EXPR_RE）扫全库报告，独立得出
「符合算式形态的行数」，再与产品实现的结果比对。

## 判据
- 独立算法数出的算式总数 == 产品 `parse_sums()` 数出的总数 ⇒ 无漏检；
- 若产品 < 独立 ⇒ 仍有缺口，打印差集样本。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from wb_analysis._audit_values import parse_sums  # noqa: E402

#: 独立算法：人工构造的「算式」识别（只认最保守的形态，宁可少算不可多算）
#: 形如「<数[%]> <op> <数[%]> ... = <±数[%]>」
INDEP_NUM = r"\d[\d,]*(?:\.\d+)?\s*%?"
INDEP_EXPR = re.compile(
    r"(?<![\d.,])"
    r"(?P<lhs>" + INDEP_NUM + r"(?:\s*[+\-\u2212\u2013\u2014\uff0b]\s*" + INDEP_NUM + r")+)"
    r"\s*[=\uff1d]\s*(?P<rhs>[+\-\u2212\u2013\u2014\uff0b]?\s*" + INDEP_NUM + r")"
)

#: 日期/年份区间（与产品同口径，独立实现）
INDEP_DATE = re.compile(r"(?:\b\d{4}|\b\d{2})-(?:\d{4}|\d{2})\b")


def independent_count(text: str) -> int:
    """独立数出「算式行」数量（每条算式算 1）。"""
    n = 0
    for line in text.splitlines():
        for m in INDEP_EXPR.finditer(line):
            if INDEP_DATE.search(m.group("lhs")):
                continue
            n += 1
    return n


def product_count(text: str) -> int:
    """产品实现数出的算式数量。"""
    n = 0
    for line in text.splitlines():
        n += len(parse_sums(line))
    return n


def main() -> int:
    reports = sorted(ROOT.glob("reports/**/complete_report.md"))
    print("=" * 92)
    print(f"生产环境验证：{len(reports)} 份报告，独立算法 vs 产品实现")
    print("=" * 92)

    tot_ind = tot_prod = 0
    gaps: list[tuple[str, int, int]] = []
    for f in reports:
        t = f.read_text(encoding="utf-8", errors="replace")
        i, p = independent_count(t), product_count(t)
        tot_ind += i
        tot_prod += p
        if p < i:
            gaps.append((f.parent.name, i, p))

    print(f"独立算法数出：{tot_ind}")
    print(f"产品实现数出：{tot_prod}")
    print(f"差集（产品漏检）：{tot_ind - tot_prod}")
    print()
    if gaps:
        print("仍有差异的文件（前 10）：")
        for name, i, p in gaps[:10]:
            print(f"  {name[:34]:34s} 独立={i:3d} 产品={p:3d} 漏 {i-p}")
    else:
        print("✓ 两者一致 ⇒ 修复在生产环境生效，无剩余漏检")
    print("=" * 92)
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
