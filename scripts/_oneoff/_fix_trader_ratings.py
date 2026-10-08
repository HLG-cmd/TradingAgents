# lifecycle: oneoff
# serves: 把 GOOG / NFLX 交易员稿正文里的五档英文词改为中文，使 trader.md 全文恰含 1 个五档词
#         （文首 **Action** 行）。触发原因：2026-10-02 补全 _lint_drafts.py 的 trader.md 检查后
#         报出 GOOG 11 处 / NFLX 5 处正文裸词。**纯词汇替换，不改任何数字/价位/算式/结论方向。**
#         原稿已备份于 .workbuddy/backup/20261002_trader_ratings/。
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (ticker, 行号, 原文片段, 替换为)  —— 逐条精确匹配，命中不到即报错中止（不静默跳过）
RULES = [
    ("GOOG", 19, "`Buy` / `Hold` / `Sell`", "买入 / 维持 / 退出"),
    ("GOOG", 40, "三档 = Hold；", "三档 = 维持；"),
    ("GOOG", 453, "「结构僵持」：维持 Hold，但", "「结构僵持」：维持不动，但"),
    ("GOOG", 568, "本席三档 = `**Action**: Hold`，", "本席三档 = 维持（见文首 **Action** 行），"),
    ("GOOG", 626, "三档取值是 `Hold`（维持既有敞口", "三档取值是「维持档」（维持既有敞口"),
    ("GOOG", 679, "本节把本席的 `Hold` 写成", "本节把本席的「维持」写成"),
    ("GOOG", 701, "（维持 Hold）", "（维持不动）"),
    ("GOOG", 713, "不改变 Hold，", "不改变维持档，"),
    ("GOOG", 718, "本席维持 `Hold`（不新建、不减持）", "本席维持既有敞口（不新建、不减持）"),
    ("GOOG", 842, "本席的 `Hold` 不是", "本席的「维持」不是"),
    ("NFLX", 536, "（Hold → Sell 方向）", "（维持档 → 退出档方向）"),
    ("NFLX", 816, "（Hold → Sell 方向）", "（维持档 → 退出档方向）"),
    ("NFLX", 831, "（Hold → Buy 方向）", "（维持档 → 买入档方向）"),
    ("NFLX", 859, "（Sell 方向）", "（退出档方向）"),
    ("NFLX", 977, "本方案取 **Hold**；改判路径为 F1/F2 → **Sell** 方向，F3 → **Buy** 方向",
     "本方案取 **维持**；改判路径为 F1/F2 → **退出档** 方向，F3 → **买入档** 方向"),
]


def main() -> int:
    by_file = {}
    for t, ln, old, new in RULES:
        by_file.setdefault(t, []).append((ln, old, new))

    rc = 0
    for ticker, rules in by_file.items():
        p = ROOT / "wb_analysis" / "drafts" / f"{ticker}_2026-10-01" / "3_trading" / "trader.md"
        lines = io.open(p, encoding="utf-8").read().split("\n")
        print(f"===== {ticker}  {p.name}  共 {len(lines)} 行")
        for ln, old, new in rules:
            idx = ln - 1
            if old not in lines[idx]:
                print(f"  ✗ L{ln} 未命中，原文不含 {old!r}")
                rc = 1
                continue
            if lines[idx].count(old) != 1:
                print(f"  ✗ L{ln} 命中 {lines[idx].count(old)} 次（应恰 1 次），跳过")
                rc = 1
                continue
            lines[idx] = lines[idx].replace(old, new)
            print(f"  ✓ L{ln}  {old[:44]!r} → {new[:44]!r}")
        if rc:
            print("  ⇒ 有未命中项，**不写盘**")
            continue
        p.write_text("\n".join(lines), encoding="utf-8", newline="\n")
        back = io.open(p, encoding="utf-8").read()
        print(f"  ⇒ 已写盘；字符数 {len(back)}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
