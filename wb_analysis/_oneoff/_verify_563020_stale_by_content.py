# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_verify_563020_stale_by_content.py
"""按项目铁律 7：用**内容比对**判定 3 个「mtime 早于 0_brief」的角色文件是否需要重跑。

## 为什么要写
`_precheck` 的「时序新鲜度」是 **mtime 判据**（项目已明确：该判据已知假阳性，
**真正的判据是内容比对**）。本轮我改过 `0_brief.md`（均线表述、规模算式、分母口径声明、
删去外部标的引用），故必须逐项核对：这 3 个文件里**是否引用了已变更的事实**。

判据：本轮 `0_brief.md` 的**净变更项**共 5 处，逐一在这 3 个文件里搜索其**旧值**；
旧值不存在 ⇒ 该文件与新简报**无冲突**，无需重跑（mtime 落后只是因为它没被改动）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "wb_analysis" / "drafts" / "563020_2026-10-15"

# 本轮 0_brief.md 的净变更：旧值 → 新值（旧值若残留即冲突）
CHANGES = [
    ("①均线硬伤", "六条均线全部位于现价下方", "五条均线（MA_10 及以上）在下方"),
    ("①均线硬伤", "六条均线全部在价格下方", "五条均线在下方"),
    ("①均线硬伤", "六条均线全在价格下方", "五条均线在下方"),
    ("①均线硬伤", "均线全部在价格下方", "五条均线在下方"),
    ("①均线硬伤", "价格在全部均线上方", "价格站在 MA_10 及以上全部均线上方"),
    ("②规模算式", "102.8791 亿份", "103.02 亿份"),
    ("③辩论计数", "熊派 7 条成立", "熊派 6 条成立"),
    ("④分母口径", "−4.47%", "−4.44%（现价口径）/ +4.65%（派生口径）"),
    ("④分母口径", "1.1859（距现价 −1.02%）", "−1.01%（现价口径）"),
    ("⑤错值", "−1.86%", "−1.89%"),
    ("⑤错值", "距 1.202 为 −1.02%", "−1.34%（距入场）"),
    ("⑥外部标的", "512400", "（已删，改为机制性说明）"),
    ("⑤语病", "一个未收盘的", "一个短周期均线的失守"),
]

TARGETS = ["1_analysts/fundamentals.md", "1_analysts/news.md", "1_analysts/sentiment.md"]


def main() -> int:
    print("=" * 92)
    print("铁律 7 内容比对：3 个「mtime 落后」文件是否引用了 0_brief 的**旧值**")
    print("=" * 92)
    bad_total = 0
    for rel in TARGETS:
        p = D / rel
        t = p.read_text(encoding="utf-8")
        hits = []
        for tag, old, new in CHANGES:
            if old in t:
                # 允许「修正语境」：同行含"已更正/误值/旧稿"等词时不判冲突
                for i, line in enumerate(t.splitlines(), 1):
                    if old in line and not any(
                        k in line for k in ("已更正", "误值", "旧值", "原写", "更正为", "不成立")
                    ):
                        hits.append((tag, i, old, line.strip()[:110]))
        print(f"\n▸ {rel}")
        if not hits:
            print("   ✓ 未引用任何旧值 ⇒ 与新简报**无内容冲突**，无需重跑")
        else:
            for tag, i, old, line in hits:
                print(f"   ✗ [{tag}] L{i}: 含旧值「{old}」 → {line}")
            bad_total += len(hits)
    print()
    print("=" * 92)
    print(f"结论：{'✓ 3 个文件均无内容冲突（mtime 落后属「未被改动」，非陈旧）' if bad_total == 0 else f'✗ 存在 {bad_total} 处内容冲突，必须修复'}")
    print("=" * 92)
    return 1 if bad_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
