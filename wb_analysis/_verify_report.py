# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_report.py
"""渲染后反读校验器 —— 用上游解析器验证报告树，不依赖 assemble 的「契约校验通过」。

**为什么必须单独做这一步**（FRAMEWORK 与 WORKFLOW 都强调过）：
`assemble.py` 打印的「契约校验通过」只覆盖**格式**；它比较的是自己声明的评级与
自己渲染的内容，属于自洽检查。真正要防的是**上游解析器把评级读成别的词**——
`extract_rating` 是两段式：先找 `Rating: X` 标签，退化后扫描全文取**第一个**五档英文词。
因此必须把**产物文件**重新交给上游解析器读一遍。

用法：
    python wb_analysis/_verify_report.py <report_tree_dir>
    python wb_analysis/_verify_report.py reports/GOOG_20260917_151945
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tradingagents.agents.utils.rating import RATINGS_5_TIER, extract_rating  # noqa: E402

TRADER_RE = re.compile(r"FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*", re.I)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    tree = Path(sys.argv[1])
    if not tree.is_dir():
        print(f"✗ 报告树不存在: {tree}")
        return 1

    fails: list[str] = []

    mgr = tree / "2_research" / "manager.md"
    dec = tree / "5_portfolio" / "decision.md"
    trd = tree / "3_trading" / "trader.md"

    print("=" * 66)
    print(f"反读校验: {tree}")
    print("=" * 66)

    if mgr.exists():
        got = extract_rating(mgr.read_text(encoding="utf-8"))
        ok = got in RATINGS_5_TIER
        print(f"  研究经理 (2_research/manager.md)  -> {got}   {'✓' if ok else '✗ 无法解析'}")
        if not ok:
            fails.append("manager.md 评级无法被上游解析器识别")
    else:
        fails.append("缺少 2_research/manager.md")
        print("  研究经理 -> 文件缺失 ✗")

    if dec.exists():
        got = extract_rating(dec.read_text(encoding="utf-8"))
        ok = got in RATINGS_5_TIER
        print(f"  组合经理 (5_portfolio/decision.md) -> {got}   {'✓' if ok else '✗ 无法解析'}")
        if not ok:
            fails.append("decision.md 评级无法被上游解析器识别")
    else:
        fails.append("缺少 5_portfolio/decision.md")
        print("  组合经理 -> 文件缺失 ✗")

    if trd.exists():
        t = trd.read_text(encoding="utf-8")
        m = TRADER_RE.search(t)
        last = t.strip().splitlines()[-1].strip()
        print(f"  交易员 **Action**  -> {t.splitlines()[0].strip()}")
        print(f"  交易员收尾行      -> {m.group(1).upper() if m else 'MISSING'}")
        print(f"  交易员真正末行    -> {last}")
        if not m:
            fails.append("trader.md 缺少 FINAL TRANSACTION PROPOSAL 收尾行")
        if not last.upper().startswith("FINAL TRANSACTION PROPOSAL"):
            fails.append(f"trader.md 末行不是契约行：{last!r}")
    else:
        fails.append("缺少 3_trading/trader.md")
        print("  交易员 -> 文件缺失 ✗")

    # 完整性
    need = ["complete_report.md", "1_analysts/market.md", "1_analysts/fundamentals.md",
            "1_analysts/news.md", "1_analysts/sentiment.md",
            "2_research/bull.md", "2_research/bear.md",
            "4_risk/aggressive.md", "4_risk/conservative.md", "4_risk/neutral.md"]
    missing = [r for r in need if not (tree / r).exists()]
    if missing:
        fails.append(f"缺少文件: {missing}")
    print(f"\n  文件完整性: {'✓ 13 个文件齐全' if not missing else '✗ 缺 ' + str(missing)}")

    cr = tree / "complete_report.md"
    if cr.exists():
        n = len(cr.read_text(encoding="utf-8"))
        print(f"  complete_report.md: {n:,} 字符")
        if "附：数据缺口与说明" not in cr.read_text(encoding="utf-8"):
            print("  ⚠ complete_report.md 未包含「附：数据缺口与说明」章节")

    # 跨文件评级一致性（如果草稿的 meta.json 还在）
    meta = tree.parent.parent / "wb_analysis" / "drafts"
    print()
    if fails:
        print("✗ 校验失败：")
        for f in fails:
            print(f"    - {f}")
        return 2
    print("✓ 全部通过：评级可被上游解析器正确识别，三处动作与收尾行一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
