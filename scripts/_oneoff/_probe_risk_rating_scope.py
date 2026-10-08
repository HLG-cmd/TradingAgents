# lifecycle: oneoff
# serves: 评估「风险席位（aggressive/conservative/neutral）结论块之外出现五档英文词」
#         这条检查在 _lint_drafts.py 中是否真的执行。当前实现里三个风险席位同时命中
#         RATING_ALLOWED_FILES（走不到第一个分支）且不属于 {manager, portfolio_manager}
#         （走不到第二个分支）⇒ 该检查对它们**完全不运行**。
#         本探针只读，目的：在改门禁之前先量出「改了会不会误伤已有合规文件」。
# 用法: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_risk_rating_scope.py
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._lint_drafts import RATING_RE  # noqa: E402  复用同一条正则，避免漂移

RISK = ("aggressive.md", "conservative.md", "neutral.md")
HEAD_ALLOW = 3  # 与 manager/PM 的 head+3 保持同一口径

rows = []
for p in sorted(ROOT.glob("wb_analysis/drafts/*/4_risk/*.md")):
    if p.name not in RISK:
        continue
    lines = io.open(p, encoding="utf-8").read().split("\n")
    hits = [(i, l.strip()[:56]) for i, l in enumerate(lines, 1) if RATING_RE.search(l)]
    bad = [(i, s) for i, s in hits if i > HEAD_ALLOW]
    head = [s for i, s in hits if i <= HEAD_ALLOW]
    rows.append((str(p.relative_to(ROOT)), len(lines), hits, bad, head))

print(f"扫描到 {len(rows)} 个风险席位文件；若把检查扩展到风险席位（首 {HEAD_ALLOW} 行内视为结论块）：\n")
n_bad = 0
for rel, n, hits, bad, head in rows:
    flag = "✓ 通过" if not bad else f"✗ 将报 {len(bad)} 处"
    if bad:
        n_bad += 1
    print(f"{flag}  {rel}  行数 {n}")
    print(f"      首 {HEAD_ALLOW} 行命中: {head if head else '（无）'}")
    if bad:
        for i, s in bad:
            print(f"      L{i}: {s}")
    print()
print(f"⇒ 若启用该检查：{len(rows)} 个文件中 {n_bad} 个会报错。")
