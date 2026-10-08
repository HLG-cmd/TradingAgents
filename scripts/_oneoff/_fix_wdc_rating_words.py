# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# 用途：WDC 2026-10-06 轮次——把 trader/aggressive/conservative/neutral 正文中的
#      英文档位词替换为中文，只保留结论块那一处（契约要求恰 1 处）。
# 背景：_lint_drafts.py 的 RATING_RE 同时匹配大写，且 trader 的结论块容差仅 head+5 行。
import io
import re
import sys

D = r"D:\Antigravity\TradingAgents\wb_analysis\drafts\WDC_2026-10-06"

FIXES = {
    "3_trading/trader.md": [
        ("### 一、我为什么落在 SELL 而不是 HOLD",
         "### 一、我为什么落在卖出方向而不是持有方向"),
        ("| BUY | 建仓或加仓 |", "| 买入方向 | 建仓或加仓 |"),
        ("| HOLD | 维持不动 | **不采纳**。HOLD 的语义是",
         "| 持有方向 | 维持不动 | **不采纳**。持有方向的语义是"),
        ("| **SELL** | **退出或避免建仓** |", "| **卖出方向** | **退出或避免建仓** |"),
        ("**⇒ 我采纳 SELL。但 SELL 在这里的确切含义需要被限定，见 §二。**",
         "**⇒ 我采纳卖出方向。但它在这里的确切含义需要被限定，见 §二。**"),
        ("### 二、★ SELL 的准确含义", "### 二、★ 卖出方向的准确含义"),
        ("**本提案的 SELL = 「退出或避免建仓」；", "**本提案的卖出方向 = 「退出或避免建仓」；"),
        ("### 三、支撑 SELL 的算术", "### 三、支撑该判断的算术"),
        ("**目标位（SELL 方向上", "**目标位（卖出方向上"),
        ("**弱一：SELL 与「无催化剂」之间存在张力。**",
         "**弱一：卖出方向与「无催化剂」之间存在张力。**"),
        ("**撤回 SELL，转 HOLD**", "**撤回卖出判断，转为持有**"),
        ("**转 HOLD 或更强**", "**转为持有或更强**"),
    ],
    "4_risk/aggressive.md": [
        ("- 我反对**交易员的 SELL**", "- 我反对**交易员的卖出提案**"),
        ("| 5 | **SELL 的执行纪律是对的** |", "| 5 | **卖出提案的执行纪律是对的** |"),
    ],
    "4_risk/conservative.md": [
        ("激进方给了 `Rating: Overweight` 与 6.0%~8.5% 的仓位",
         "激进方给了「增配偏向」与 6.0%~8.5% 的仓位"),
    ],
    "4_risk/neutral.md": [
        ("## §4 我的立场：维持（Hold），以及为什么它是唯一不依赖\"自选尺子\"的位置",
         "## §4 我的立场：维持（不增不减），以及为什么它是唯一不依赖\"自选尺子\"的位置"),
    ],
}

R = re.compile(
    r"(?<![A-Za-z])(Buy|Overweight|Underweight|Sell|Hold|BUY|OVERWEIGHT|UNDERWEIGHT|SELL|HOLD)(?![A-Za-z])"
)

rc = 0
for rel, pairs in FIXES.items():
    p = D + "\\" + rel.replace("/", "\\")
    s = io.open(p, encoding="utf-8").read()
    for a, b in pairs:
        n = s.count(a)
        if n == 0:
            print("  !! 未命中: %s :: %s" % (rel, a[:60]))
            rc = 1
            continue
        s = s.replace(a, b)
        print("  %-28s x%d  %s" % (rel, n, a[:52]))
    io.open(p, "w", encoding="utf-8", newline="").write(s)

print("\n=== 替换后复查：剩余英文档位词所在行 ===")
for rel in FIXES:
    p = D + "\\" + rel.replace("/", "\\")
    s = io.open(p, encoding="utf-8").read()
    bad = [(i, l.strip()[:90]) for i, l in enumerate(s.splitlines(), 1) if R.search(l)]
    print("--", rel, "剩余 %d 行" % len(bad))
    for i, l in bad:
        print("     L%-4d %s" % (i, l))
sys.exit(rc)
