# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_ratings.py
"""评级词与契约字段的可靠扫描器（不依赖 shell 转义）。

为什么需要它（2026-09-19 血泪）：
  在 bash heredoc 里内联正则时，**反斜杠会被 shell 层破坏** ——
  实测 `r"FINAL TRANSACTION PROPOSAL:\\s*\\*\\*(\\w+)\\*\\*"` 到达 Python 时变成了
  `'FINAL TRANSACTION PROPOSAL:/s*/*/*(/w+)/*/*'`（`\\s`→`/s`、`\\*`→`/*`、`\\w`→`/w`），
  于是 findall 返回 []，而**行明明存在**。
  ⇒ 同理，早前用 `grep -o -E '\\b(...)\\b'` 得到的「0 命中」也可能是被破坏的假阴性。

本脚本把正则写在**文件里**（不经 shell 转义），从而得到可信结果。

用法：
    python wb_analysis/_verify_ratings.py wb_analysis/drafts/NDX_2026-09-17
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ★ 2026-10-08：契约常量改为**唯一来源** import（见 `_contract.py` 抬头的漂移史）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wb_analysis._contract import (  # noqa: E402
    DOC_FILES,
    FINAL_PROPOSAL,
    FIVE_TITLE_RE as FIVE,
    PROPOSAL_RE as TRADER_LINE,
    RATING_ALLOWED_FILES,
)

REQUIRED_FIELDS = {
    "2_research/manager.md": ["Recommendation"],
    "4_risk/portfolio_manager.md": ["Rating"],
    "3_trading/trader.md": ["Action", FINAL_PROPOSAL],
}
ROLE_FILES = [
    "0_brief.md", "0_derived.md", "_constraints.md",
    "1_analysts/market.md", "1_analysts/fundamentals.md",
    "1_analysts/news.md", "1_analysts/sentiment.md",
    "2_research/bull.md", "2_research/bear.md", "2_research/manager.md",
    "3_trading/trader.md",
    "4_risk/aggressive.md", "4_risk/conservative.md",
    "4_risk/neutral.md", "4_risk/portfolio_manager.md",
]
# 五档词允许出现的文件 —— **直接由 `_contract.py` 派生**。
# ★ 2026-09-19 对齐：此前这里只列 3 个（manager/trader/PM），而 `_lint_drafts.py` 的
#   `RATING_ALLOWED_FILES` 列了 **6 个**（多出三个风控席位）。两个工具对
#   「风控席位能否在结论块用五档词表态」**判断相反** —— 同一份草稿会得到两种结论。
#   ⇒ 2026-10-08 起不再"手动对齐"，而是**同一份常量**，漂移在物理上不可能。
FIVE_ALLOWED = {f"2_research/{n}" for n in RATING_ALLOWED_FILES if n == "manager.md"}
FIVE_ALLOWED |= {f"3_trading/{n}" for n in RATING_ALLOWED_FILES if n == "trader.md"}
# ★ 2026-10-10：改为「**补集**」写法。此前这里硬列了 4 个名字
#   `{portfolio_manager.md, aggressive.md, conservative.md, neutral.md}` ——
#   于是往 `_contract.RATING_ALLOWED_FILES` 里**新增**一个 4_risk 席位后，
#   那个席位既不在 `2_research/`、也不在 `3_trading/`、更不在这个写死的 4 人名单里
#   ⇒ 它会掉进「违规」判定（正是 `_lint_drafts.py` 2026-10-01 那次门禁盲区的翻版）。
#   补集写法让它**自动**跟上白名单，漂移点消失。
FIVE_ALLOWED |= {f"4_risk/{n}" for n in RATING_ALLOWED_FILES
                 if n not in {"manager.md", "trader.md"}}
# 工作文档白名单 `DOC_FILES` 由 `_contract.py` 提供（见顶部 import）——
# ⚠️ 2026-10-10：此处此前**又本地定义了一份同值集合**，且顶部 `import ... as _DOC_ALL`
#    整个未使用 ⇒ 「import 了却又重写一遍」，而 `_selftest.py` 的守门断言只检查
#    「源码里出现过 `_contract import`」⇒ **断言被 import 语句骗过、漂移照样发生**。
#    已删除本地定义（同名 import 即可），并把守门断言升级为「不得本地重定义」。
# ★ 必需的是**12 个角色文件**；上面 3 份工作文档属"有则扫、无则只提示"。
#   （2026-09-19 自检发现：此前把它们与角色文件同等要求，会导致
#    「草稿目录没放 `_constraints.md`」被判成 ✗ 文件缺失 —— 一类纯粹的误报。）


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "wb_analysis/drafts/NDX_2026-09-17")
    print("=" * 72)
    print(f"评级词与契约扫描：{root}")
    print("=" * 72)

    problems = []
    for rel in ROLE_FILES:
        p = root / rel
        if not p.exists():
            if rel in DOC_FILES:
                # 工作文档缺失只提示，不计入 problems（它不是角色产出）
                print(f"\n{rel}\n   · 工作文档缺失（可选，不影响合规判定）")
                continue
            print(f"\n{rel}\n   ✗ 角色文件缺失")
            problems.append(rel)
            continue
        t = p.read_text(encoding="utf-8")
        five = [(t[: m.start()].count("\n") + 1, m.group(1)) for m in FIVE.finditer(t)]
        three = TRADER_LINE.findall(t)

        print(f"\n{rel}  （{len(t.encode('utf-8')):,} 字节）")
        if five:
            for ln, w in five:
                line = t.splitlines()[ln - 1]
                if rel in DOC_FILES:
                    flag = "○ 工作文档的定义性引用（合法）"
                elif rel in FIVE_ALLOWED:
                    flag = "✓ 契约/结论块"
                else:
                    flag = "✗ 违规"
                print(f"   五档词 {w:<12} L{ln:<5} {flag}  | {line.strip()[:70]}")
                if rel not in FIVE_ALLOWED and rel not in DOC_FILES:
                    problems.append(f"{rel}:L{ln}")
        else:
            print("   五档词：0 处 ✓")

        if rel in REQUIRED_FIELDS:
            for fld in REQUIRED_FIELDS[rel]:
                ok = f"**{fld}**" in t or (fld == FINAL_PROPOSAL and bool(three))
                print(f"   必需字段 **{fld}**：{'✓' if ok else '✗ 缺失'}")
                if not ok:
                    problems.append(f"{rel}:缺少 {fld}")

        if rel == "3_trading/trader.md":
            print(f"   FINAL 行解析：{three if three else '✗ 未匹配'}")

    print("\n" + "=" * 72)
    if problems:
        print(f"结论：✗ 存在 {len(problems)} 项问题 -> {problems}")
        return 1
    print("结论：✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
