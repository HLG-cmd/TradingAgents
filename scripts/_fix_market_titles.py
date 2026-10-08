# lifecycle: maintenance
# 用途：把 market.md 的五个维度标题改为「序号. 维度名：…」形式，使 _check_role_files 的维度正则命中
from pathlib import Path

P = Path("wb_analysis/drafts/NFLX_2026-10-05/1_analysts/market.md")

REP = [
    (
        "## §1 价格结构与趋势位置（口径 A：67.50 @ 2026-10-05）",
        "## 1. 趋势：价格结构与趋势位置（口径 A：67.50 @ 2026-10-05）",
    ),
    (
        "## §3 动量指标的内部矛盾（本文件必须两面都讲）",
        "## 3. 动量：指标的内部矛盾（本文件必须两面都讲）",
    ),
    (
        "## §4 波动率度量：ATR、真实波幅与布林带",
        "## 4. 波动率：度量 —— ATR、真实波幅与布林带",
    ),
    (
        "## §5 成交量结构：20 日均量的构成被单个事件 bar 扭曲",
        "## 5. 量能：成交量结构 —— 20 日均量的构成被单个事件 bar 扭曲",
    ),
    (
        "## §10 关键价位地图（**技术位，不是交易决策**）",
        "## 10. 关键价位地图（**技术位，不是交易决策**）",
    ),
]

t = P.read_text(encoding="utf-8")
for a, b in REP:
    if a in t:
        t = t.replace(a, b, 1)
        print("  ✓ 替换:", a[:28])
    else:
        print("  ✗ 未找到:", a[:28])
P.write_text(t, encoding="utf-8")
print("done")
