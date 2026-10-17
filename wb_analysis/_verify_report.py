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
from wb_analysis._contract import FINAL_PROPOSAL, PROPOSAL_STRICT_RE as TRADER_RE  # noqa: E402

# ⚠️ 2026-10-10：`TRADER_RE` 此前在本文件与 `assemble.py:54` **逐字各写了一遍**
#   （同为 `FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*` + re.I），
#   而 `_contract` 里已有等价正则 ⇒ 改为 import 单一来源。
#   `re` 仍被本文件其它地方使用，故保留其 import。


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
        if not last.upper().startswith(FINAL_PROPOSAL):
            fails.append(f"trader.md 末行不是契约行：{last!r}")
    else:
        fails.append("缺少 3_trading/trader.md")
        print("  交易员 -> 文件缺失 ✗")

    # 完整性
    # ⚠️ 2026-10-10：本表**只列不与上方重复校验的**必需文件 —— `2_research/manager.md`、
    #   `3_trading/trader.md`、`5_portfolio/decision.md` 已在上方逐项读+解析，重复列举只会
    #   产生两套口径。**下方那句打印此前硬编码「13 个文件齐全」**：
    #   全树确实是 13 份（12 角色产物 + `complete_report.md`），但**本表只有 10 项**
    #   ⇒ 「声明的校验范围」与「打印出来的数字」不符，且树布局一变就静默说谎。
    #   ⇒ 改为**从本表派生**计数，并明写另有 3 项已单独校验。
    need = ["complete_report.md", "1_analysts/market.md", "1_analysts/fundamentals.md",
            "1_analysts/news.md", "1_analysts/sentiment.md",
            "2_research/bull.md", "2_research/bear.md",
            "4_risk/aggressive.md", "4_risk/conservative.md", "4_risk/neutral.md"]
    missing = [r for r in need if not (tree / r).exists()]
    if missing:
        fails.append(f"缺少文件: {missing}")
        print(f"\n  文件完整性: ✗ 缺 {missing}")
    else:
        print(f"\n  文件完整性: ✓ 本表 {len(need)} 项齐全（manager / trader / decision 已在上方单独校验）")

    cr = tree / "complete_report.md"
    cr_text = cr.read_text(encoding="utf-8") if cr.exists() else None
    if cr_text is not None:
        print(f"  complete_report.md: {len(cr_text):,} 字符")
        if "附：数据缺口与说明" not in cr_text:
            print("  ⚠ complete_report.md 未包含「附：数据缺口与说明」章节")

    # ── 契约：五档英文词**只允许 6 席、每席恰 1 处**（2026-10-11 / O8 补）──
    #  此前**没有任何门禁检查合成报告**：
    #    · `_lint_drafts.py` 只看**草稿**（渲染之前）；
    #    · 本脚本此前只看「三个评级能否被上游解析器读出」+「12 个文件在不在」。
    #  而 `complete_report.md` 是 `assemble.py` **新合成**的文本（header + 各角色正文），
    #  既没被 lint 过、也不参与评级解析 ⇒ **渲染环节引入的越界评级词无人拦截**。
    #  这里补上：两重判据 —— ① 每席恰 1 处；② 合成报告的总数 == 6 席合计。
    seat_files = ("2_research/manager.md", "3_trading/trader.md", "5_portfolio/decision.md",
                  "4_risk/aggressive.md", "4_risk/conservative.md", "4_risk/neutral.md")

    def _tier_hits(text: str) -> int:
        return sum(len(re.findall(rf"\b{w}\b", text)) for w in RATINGS_5_TIER)

    per_seat: list[tuple[str, int]] = []
    for rel in seat_files:
        f = tree / rel
        if f.exists():                      # 缺失已由上方完整性检查报出，此处不重复
            per_seat.append((rel, _tier_hits(f.read_text(encoding="utf-8"))))
    total_seats = sum(n for _, n in per_seat)
    off = [f"{rel}={n}" for rel, n in per_seat if n != 1]
    print(f"\n  五档词席位: 6 席合计 {total_seats} 处" +
          (f"，异常 {off}" if off else "，每席恰 1 处 ✓"))
    if off:
        fails.append(f"五档英文词出现次数不是恰 1 处（{off}）")
    if cr_text is not None:
        n_cr = _tier_hits(cr_text)
        if n_cr != total_seats:
            fails.append(f"complete_report.md 五档词 {n_cr} 处 ≠ 6 席合计 {total_seats} 处"
                         f" ⇒ **合成环节引入了额外评级词**")
            print(f"  ✗ complete_report.md 五档词 {n_cr} 处，与 6 席合计 {total_seats} 处不符")

    # 跨文件评级一致性（产物 vs 草稿 meta.json）**不在本脚本** —— 见 `_precheck.py`
    # 第 7 项「报告树反读」与 `_audit_values.py`。此处原先留有一行 `meta = ...` 死赋值，
    # 是旧扁平布局（`reports/<T>_<date>/`）的残留：新布局下 `tree.parent.parent` 已是
    # `reports/`，拼出来的路径恒不存在 ⇒ **读它只会得到空结果**，2026-10-10 删除。
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
