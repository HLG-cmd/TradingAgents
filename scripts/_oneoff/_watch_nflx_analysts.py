# lifecycle: oneoff
"""守望：等待 4 个分析师产物落盘（最多 9 分钟），每 15s 打印一次大小。"""
import time
from pathlib import Path

D = Path(r"D:\Antigravity\TradingAgents\wb_analysis\drafts\NFLX_2026-10-12\1_analysts")
FILES = ["market.md", "fundamentals.md", "news.md", "sentiment.md"]
DEADLINE = time.time() + 540

last = {}
while time.time() < DEADLINE:
    done = []
    for f in FILES:
        p = D / f
        if p.exists():
            n = len(p.read_text(encoding="utf-8", errors="replace"))
            if last.get(f) != n:
                print(f"  {f:18s} {n:>8} chars", flush=True)
                last[f] = n
            if n > 500:
                done.append(f)
    if len(done) == len(FILES):
        print("ALL 4 PRESENT", flush=True)
        break
    time.sleep(15)

print("--- final ---")
for f in FILES:
    p = D / f
    print(f"  {f:18s} exists={p.exists()} chars={len(p.read_text(encoding='utf-8', errors='replace')) if p.exists() else 0}")
