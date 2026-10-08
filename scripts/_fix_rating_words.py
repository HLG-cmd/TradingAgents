# lifecycle: maintenance
# 用途：把草稿中「结论块之外」的五档英文词改为中文，仅保留结论块标签行与 FINAL TRANSACTION PROPOSAL 行
import re
import sys
from pathlib import Path

MAP = {"Buy": "买入", "Overweight": "超配", "Hold": "持有", "Underweight": "低配", "Sell": "卖出"}

KEEP = [
    re.compile(r"\*\*Rating\*\*\s*[:：]\s*\**\s*(?:Buy|Overweight|Hold|Underweight|Sell)"),
    re.compile(r"\*\*Recommendation\*\*\s*[:：]\s*\**\s*(?:Buy|Overweight|Hold|Underweight|Sell)"),
    re.compile(r"\*\*Action\*\*\s*[:：]\s*\**\s*(?:Buy|Hold|Sell)"),
    re.compile(r"FINAL TRANSACTION PROPOSAL:\s*\*\*(?:BUY|HOLD|SELL)\*\*"),
]

# 同时把「**Rating: X**」这种把英文包在加粗内的写法规范成「**Rating**: X»
NORM = re.compile(r"\*\*(Rating|Recommendation|Action):\s*(Buy|Overweight|Hold|Underweight|Sell)\*\*")


def main() -> int:
    base = Path(sys.argv[1])
    files = sys.argv[2:]
    for rel in files:
        p = base / rel
        if not p.exists():
            print("  ✗ 缺文件", rel)
            continue
        txt = p.read_text(encoding="utf-8")
        txt = NORM.sub(r"**\1**: \2", txt)
        lines = txt.split("\n")
        out = []
        for ln in lines:
            if any(k.search(ln) for k in KEEP):
                out.append(ln)
            else:
                for en, zh in MAP.items():
                    ln = re.sub(r"\b%s\b" % en, zh, ln)
                out.append(ln)
        p.write_text("\n".join(out), encoding="utf-8")
        print("  ✓ 已规范化", rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
