# lifecycle: oneoff
"""逐条复算 6 份 NDX 草稿里显式写出的算式（a − b = c / a ÷ b = c / a × b = c），找出算错的数。

产出只用于人工复核，不写回任何草稿。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRAFTS = ROOT / "wb_analysis" / "drafts" / "NDX_2026-09-29"
FILES = [
    "1_analysts/market.md",
    "1_analysts/fundamentals.md",
    "1_analysts/news.md",
    "1_analysts/sentiment.md",
    "2_research/bull.md",
    "2_research/bear.md",
]

NUM = r"\d[\d,]*(?:\.\d+)?%?"
OPS = r"[+\-−/÷×*]"
EXPR_RE = re.compile(
    rf"(?<![\w.])(\d[\d,]*(?:\.\d+)?%?)((?:\s*{OPS}\s*\d[\d,]*(?:\.\d+)?%?)+)\s*(?:=|≈|==)\s*(-?\d[\d,]*(?:\.\d+)?)(%?)"
)


def val(s: str) -> float:
    return float(s.replace(",", ""))


def eval_chain(first: str, rest: str) -> float:
    """左结合求值：1 - 2 + 3 -> ((1-2)+3)"""
    tokens = re.split(rf"\s*({OPS})\s*", rest.strip())
    # tokens[0] 为空（因为 rest 以运算符开头）
    total = val(first)
    i = 0
    parts = [t for t in tokens if t]
    while i < len(parts):
        op = parts[i]
        num = val(parts[i + 1])
        if op == "+":
            total += num
        elif op in ("-", "−"):
            total -= num
        elif op in ("/", "÷"):
            total = total / num if num else float("nan")
        elif op in ("×", "*"):
            total *= num
        i += 2
    return total


def main() -> int:
    bad = []
    total = 0
    for rel in FILES:
        path = DRAFTS / rel
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in EXPR_RE.finditer(line):
                lhs_str = (m.group(1) + m.group(2)).strip()
                rhs_str = m.group(3) + m.group(4)
                op_sym = m.string[m.end(2):m.start(3)].strip()
                dec = len(m.group(3).split(".")[1]) if "." in m.group(3) else 0
                unit = 10 ** (-dec)
                try:
                    lhs = eval_chain(m.group(1), m.group(2))
                except Exception:
                    continue
                rhs = val(m.group(3))
                # 单位归一：操作数无 %、结果为 % ⇒ 结果需 ×100
                if m.group(4) == "%" and "%" not in (m.group(1) + m.group(2)):
                    lhs *= 100
                total += 1
                diff = abs(lhs - rhs)
                if op_sym.startswith("≈"):
                    tol = max(unit * 3, abs(rhs) * 0.003)
                else:
                    tol = max(unit * 3, min(abs(rhs) * 5e-5, unit * 30))
                if diff > tol:
                    bad.append((rel, lineno, lhs_str, f"{lhs:.6f}", rhs_str, f"{diff:.6f}"))
    print(f"共检出显式算式 {total} 条，其中不符 {len(bad)} 条\n")
    for rel, lineno, expr, lhs, rhs, diff in bad:
        print(f"[{rel}:{lineno}]  {expr} = {rhs}   实算 {lhs}   差 {diff}")
        src = (DRAFTS / rel).read_text(encoding="utf-8").splitlines()[lineno - 1]
        print(f"    原文: {src.strip()[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
