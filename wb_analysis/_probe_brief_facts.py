# lifecycle: reusable
# created: 2026-10-12
# usage: ./.venv/Scripts/python.exe wb_analysis/_probe_brief_facts.py <TICKER> <DATE> [小节...]
"""把证据包里「写简报所需的全部事实」压成一份短摘要（避免整包 60KB 进上下文）。

为什么不是 oneoff：**每一轮写简报都要用它**，且它只读证据包、不产出任何东西
⇒ 属可复用工具。用法：
    python wb_analysis/_probe_brief_facts.py SKHY 2026-10-11
    python wb_analysis/_probe_brief_facts.py SKHY 2026-10-11 5 7 8   # 只看指定小节

⚠️ 必须落盘执行：正则含反斜杠，内联进 shell 会被静默改写（铁律 22）。
⚠️ 切节判据必须锚定 `## <数字>.` —— 证据包里 `## GOOG News, …` / `## FRED: …`
   这类子标题也是 `## ` 开头，用任意 `## ` 作边界会把整节切没（铁律 35 同型）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "wb_analysis" / "evidence"

ticker = sys.argv[1] if len(sys.argv) > 1 else "SKHY"
date = sys.argv[2] if len(sys.argv) > 2 else "2026-10-11"
want = set(sys.argv[3:]) if len(sys.argv) > 3 else None

p = EVID / f"{ticker}_{date}.md"
if not p.exists():
    raise SystemExit(f"✗ 找不到证据包 {p}")
L = p.read_text(encoding="utf-8", errors="replace").splitlines()


def sect(n: str) -> list[str]:
    s = next((k for k, l in enumerate(L)
              if l.startswith(f"## {n}") and re.match(r"^## \d+\.", l)), -1)
    if s < 0:
        return []
    e = next((k for k in range(s + 1, len(L))
              if re.match(r"^## \d+\.", L[k]) or L[k].startswith("## 通道健康度")), len(L))
    return L[s:e]


def show(*nums: str, head: int = 18) -> None:
    for n in nums:
        if want is not None and n.rstrip(".") not in want:
            continue
        print(f"\n{'='*70}\n### §{n}\n{'='*70}")
        for l in sect(n)[:head]:
            print(l[:170])


# 通道健康度
print("### 通道健康度")
for l in L:
    if "成功:" in l or "非全绿通道" in l:
        print("  ", l.strip()[:120])

# §1 关键统计
print("\n### §1 关键统计")
for l in sect("1.")[:24]:
    print("  ", l[:150])

show("2.", head=6)
print("\n### §3 快照（全字段）")
for l in sect("3.")[:30]:
    print("  ", l[:120])

show("4.1", head=16)
show("4.2", head=8)
show("4.3", head=8)

# 新闻：只印标题行（省版面）
for n in ("5.", "6."):
    print(f"\n### §{n} 新闻标题")
    for l in sect(n):
        if l.startswith("### ") or l.startswith("## "):
            print("  ", l[:150])

show("7.", head=16)
show("9.", head=14)

# §8 内部人：计数 + 前 8 行
s8 = sect("8.")
rows = [l for l in s8 if re.match(r"^\d+,", l.strip())]
print(f"\n### §8 内部人  共 {len(rows)} 行 | 带价卖出 {sum('Sale at price' in l for l in rows)}"
      f" | 带价买入 {sum(('Buy at price' in l or 'Purchase' in l) for l in rows)}"
      f" | 赠与 {sum('Gift' in l for l in rows)}")
for l in rows[:8]:
    print("  ", l.strip()[:150])

show("10.", head=6)
print("\n### §10 各序列 Latest")
cur = None
for l in sect("10."):
    if l.startswith("## FRED:"):
        cur = l.strip("# ").strip()[:60]
    if l.strip().startswith("**Latest:**"):
        print(f"  {cur or '?':<58} {l.strip()[10:][:70]}")

# §11 期权
print("\n### §11 期权（IV 等级 / 偏斜 / 期限结构）")
for l in sect("11."):
    if re.search(r"IV 数据等级|报价新鲜度闸门|25Δ偏斜|期限结构|逐档 ATM|驼峰|不得仅据端点", l):
        print("  ", l.strip()[:210])

# §12 波动率代理：每个子块最后 2 行
print("\n### §12 波动率/债券代理（各子块末 2 行）")
blk = sect("12.")
idx = [i for i, l in enumerate(blk) if l.startswith("### ")] + [len(blk)]
for a, b in zip(idx[:-1], idx[1:]):
    seg = blk[a:b]
    rows = [r for r in seg if re.match(r"^\|?\s*20\d\d-\d\d-\d\d", r.strip())]
    print("  ---", seg[0][:60])
    for r in rows[-2:]:
        print("      ", r.strip()[:110])

# §13
print("\n### §13 最新交易日实时补充")
for l in sect("13.")[:10]:
    print("  ", l[:170])
