# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_strip_stray_ratings.py
"""渲染前的契约清扫：把 manager.md 正文里的裸五档英文词改成中文表述。

背景（铁律 8）：`extract_rating` 扫描全文取**第一个**五档英文词，所以除结论块那一处外，
正文出现裸五档词就会污染评级解析。`_lint_drafts.py` 会判为**契约违规（退出码 2，阻断交付）**。

本脚本只做**纯词汇替换**，不改变任何数字、结论或论证结构。
替换后必须回读验证：正文内五档词应为 0 处（结论块那处保留），且 md5 之外的内容未被改动。

用法:
  ./.venv/Scripts/python.exe wb_analysis/_strip_stray_ratings.py <草稿目录> <文件名>
  例：./.venv/Scripts/python.exe wb_analysis/_strip_stray_ratings.py wb_analysis/drafts/NDX_2026-09-21 2_research/manager.md
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ★ 2026-10-08：契约常量改为**唯一来源** import（见 `_contract.py` 抬头的漂移史）。
sys.path.insert(0, str(ROOT))
# ★ 2026-10-22：回读校验改用 `FIVE_RE`（大小写不敏感），与门禁 `_lint_drafts` 同口径。
#   此前用 `FIVE_TITLE_RE`（仅 Title Case）⇒ 正文残留 `**BUY**` 时报「0 处」并退出 0，
#   随后被 `_lint_drafts` 以退出码 2 拦下 —— 两道门禁对同一份文件给出相反结论。
from wb_analysis._contract import FINAL_PROPOSAL, FIVE_RE  # noqa: E402

# 顺序重要：先长后短，避免 "Overweight/Buy" 被拆坏
RULES = [
    ("Overweight/Buy", "上调档（增持/建仓）"),
    ("Underweight/Sell", "下调档（减持/退出）"),
    ("Buy/Overweight", "上调档（建仓/增持）"),
    ("Sell/Underweight", "下调档（退出/减持）"),
    ("上调至 Overweight", "上调一档"),
    ("下修至 Underweight", "下修一档"),
    ("上修至 Overweight", "上修一档"),
    ("至 Overweight", "一档至增持"),
    ("至 Underweight", "一档至减持"),
    ("Overweight（增持）", "增持档"),
    ("Underweight（减持）", "减持档"),
    # —— 以下为 2026-09-22 实测出现过的写法 ——
    ("「维持（Hold）」", "「维持」"),
    ("（Hold）", "（维持）"),
    ("Hold）", "维持）"),
    ("Hold 方案", "维持方案"),
    ("「退出/Sell」", "「退出」"),
    ("退出/Sell", "退出（减持档）"),
    ("Hold**（", "维持**（"),
]

#: 五档词（Title / 全大写）→ 中文表述。键一律小写，用 `FIVE_RE` 命中的原文查表。
#: ★ 2026-10-22：兜底改写改由 `_contract.FIVE_RE` 驱动，本表只负责「词 → 中文」，
#:   于是改写范围与门禁 `_lint_drafts` 的判定范围**永远同一个来源**。
FIVE_CN = {
    "buy": "建仓档",
    "overweight": "增持档",
    "hold": "维持",
    "underweight": "减持档",
    "sell": "退出档",
}


KEEP_LINE_PATTERNS = [
    re.compile(r"^\*\*(Recommendation|Rating)\*\*:"),      # 结论块
    re.compile(rf"^{FINAL_PROPOSAL}:"),
    re.compile(r"^\*\*Action\*\*:"),
]


def main() -> int:
    draft = (ROOT / sys.argv[1]).resolve()
    rel = sys.argv[2]
    p = draft / rel
    text = p.read_text(encoding="utf-8")
    before = text

    out_lines = []
    for _ln, line in enumerate(text.split("\n"), 1):
        if any(p.search(line) for p in KEEP_LINE_PATTERNS):
            out_lines.append(line)
            continue
        new = line
        for a, b in RULES:
            new = new.replace(a, b)
        # 兜底：仍残留的裸五档词按中文档位替换（只在非结论块行上执行）。
        # ★ 2026-10-22：改用 `_contract.FIVE_RE` 驱动 —— 它容忍 Title 与全大写两种形式，
        #   所以 `**BUY**` 这类残留也会被清掉（此前只认 Title Case，清不掉却报「0 处」）。
        #   小写（英文正文里的 `hold` / `sell`）按契约**不算**评级词，不动。
        new = FIVE_RE.sub(lambda m: FIVE_CN[m.group(0).lower()], new)
        out_lines.append(new)
    text = "\n".join(out_lines)

    if text == before:
        print("[strip] 未发生变化（可能规则未命中，请检查实际写法）")
    else:
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"[strip] 已写入 {p}；字符数 {len(before)} -> {len(text)}")

    # 回读验证
    back = p.read_text(encoding="utf-8")
    hits = []
    for ln, line in enumerate(back.split("\n"), 1):
        if any(p.search(line) for p in KEEP_LINE_PATTERNS):
            continue
        for m in FIVE_RE.finditer(line):
            hits.append((ln, m.group(0), line[:90]))
    print(f"[strip] 回读：结论块之外的裸五档词 = {len(hits)} 处")
    for h in hits:
        print("   ", h)
    return 0 if not hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
