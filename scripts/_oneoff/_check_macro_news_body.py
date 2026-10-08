# lifecycle: oneoff
# 对照组检查：各标的证据包 §6 宏观新闻节的「正文 vs 仅标题」情况
import pathlib
import re
import sys

root = pathlib.Path(r"D:\Antigravity\TradingAgents\wb_analysis\evidence")
rows = []
for p in sorted(root.glob("*.md")):
    if p.name.endswith(".derived.md") or p.name.endswith(".supplement.md"):
        continue
    t = p.read_text(encoding="utf-8")
    m = re.search(r"## 6\. 全球宏观新闻(.*?)## 7\.", t, re.S)
    if not m:
        continue
    body = m.group(1)
    n_link = body.count("Link:")
    # 「正文」= 去掉 Link 行、URL、围栏、空行、分隔线、标题行之后剩下的字符
    stripped = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith("###") or s.startswith("Link:") or s.startswith("##") or s.startswith("---"):
            continue
        if s.startswith("http"):
            continue
        stripped.append(s)
    prose = "\n".join(stripped)
    rows.append((p.stem, len(body), n_link, len(prose)))

print(f"{'ticker_date':<28} {'节长':>7} {'Link数':>6} {'正文长':>7} {'判定'}")
print("-" * 70)
for name, bl, nl, pl in rows:
    verdict = "仅标题(正文空)" if pl == 0 else ("正文极短" if pl < 200 else "有正文")
    print(f"{name:<28} {bl:>7} {nl:>6} {pl:>7}  {verdict}")
