# lifecycle: oneoff
# created: 2026-09-29
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_nflx_lint.py
"""修正 NFLX 草稿中被 lint 判为契约违规的「裸五档英文词」（共 3 个文件 9 处）。

性质说明：**只做合规中文化，不改动任何分析内容、数字或结论**。
根因：多个角色在引用英文新闻标题 / 描述分析师评级时，直接保留了 Buy/Sell 等裸英文词，
会污染下游 extract_rating 的评级解析（项目铁律 8）。
"""
import pathlib
import re

BASE = pathlib.Path(r"wb_analysis/drafts/NFLX_2026-09-28")

# (文件, 旧串, 新串) —— 精确替换，保持语义
RULES = [
    # fundamentals.md
    ("1_analysts/fundamentals.md",
     '"1 Wall Street Analyst Just Called Netflix a Sell"',
     "「某华尔街分析师刚给 Netflix 打出卖出评级」"),
    # news.md 表格内的英文标题
    ("1_analysts/news.md",
     "1 Wall Street Analyst Just Called Netflix a Sell",
     "某华尔街分析师刚给 Netflix 打出卖出评级"),
    ("1_analysts/news.md",
     "Netflix and Paramount Skydance Are Both Down Over 20%. Here's the 1 to Buy",
     "Netflix 与 Paramount Skydance 均跌超 20%，二选一该买哪只"),
    ("1_analysts/news.md",
     "Walt Disney vs. Netflix: Which Stock Is a Better Buy in 2026?",
     "迪士尼 vs Netflix：2026 年哪只更值得买？"),
    ("1_analysts/news.md",
     "25 of 33 analysts still saying buy",
     "33 位分析师中 25 位仍看多"),
    ("1_analysts/news.md",
     "「Here's the 1 to Buy」",
     "「二选一该买哪只」"),
    ("1_analysts/news.md",
     '| 17 | 1 Wall Street Analyst Just Called Netflix',
     "| 17 | 某华尔街分析师刚给 Netflix"),
    # 中文句中夹带的英文评级词
    ("1_analysts/news.md", "1 位分析师给 Sell", "1 位分析师给卖出评级"),
    ("1_analysts/news.md", "明确给 Sell 的仅 1 位", "明确给卖出评级的仅 1 位"),
    ("2_research/bear.md", "1 位分析师给 Sell", "1 位分析师给卖出评级"),
]

PAT = re.compile(r"(?<![A-Za-z])(Buy|Overweight|Underweight|Sell|Hold)(?![A-Za-z])")


def main() -> int:
    total = 0
    for rel, old, new in RULES:
        p = BASE / rel
        raw = p.read_text(encoding="utf-8")
        if old not in raw:
            print(f"  [跳过] {rel}: 未找到 {old[:40]!r}")
            continue
        n = raw.count(old)
        raw = raw.replace(old, new)
        p.write_text(raw, encoding="utf-8", newline="\n")
        total += n
        print(f"  [替换 {n} 处] {rel}: {old[:45]!r}")
    print(f"\n共替换 {total} 处")

    print("\n=== 复检：全草稿树残留的裸五档英文词 ===")
    left = 0
    for p in sorted(BASE.rglob("*.md")):
        for i, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            for m in PAT.finditer(line):
                left += 1
                print(f"  {p.name}:{i} [{m.group(1)}] {line.strip()[:90]}")
    print("✓ 无残留" if left == 0 else f"✗ 仍有 {left} 处")
    return 0 if left == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
