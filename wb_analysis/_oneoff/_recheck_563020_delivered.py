# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_recheck_563020_delivered.py
"""独立复核：直接扫**交付树**（reports/563020/563020_20261016_133333/）里的最终产物，
逐类验证此前报告的 6 类矛盾是否真的消失。

## 为什么必须扫交付树而不是草稿
用户问的是「这些问题还在吗」——判据只能是**用户最终拿到的那份文件**。
草稿修好 ≠ 交付树修好（本轮就发生过：草稿改了，但审计包与元数据没跟上）。
⇒ 故本脚本对 complete_report.md 与树内 12 个角色文件**同时**检查。

## 判据（每类都给「旧值应缺席」+「新值应在场」双向断言）
只做「旧值缺席」是单向的 —— 若整段被删掉也会"通过"。
故每类都双向：旧值 count 必须为 0，且新值 count 必须 > 0。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / "reports" / "563020" / "563020_20261016_133333"

CHECKS: list[tuple[str, str, list[str], list[str]]] = [
    # (类别, 说明, [必须缺席的旧值], [必须在场的新值/锚点])
    ("1-均线硬伤", "「六条均线全在下方」应缺席；「五条在下方」应在场",
     ["六条均线全部位于现价下方", "六条均线全部在价格下方", "六条均线全在价格下方",
      "均线全部在价格下方", "六条均线全在下方", "六条全在价格下方"],
     ["MA_10 及以上五条均线", "五条均线位于现价下方", "MA_5 已失守"]),
    ("2-规模算式", "102.8791 亿份的错算式应缺席；103.02 亿份应在场",
     ["102.8791"], ["103.02"]),
    ("3-辩论计数", "「熊派 7 条成立」应缺席；「熊派 6 条成立」应在场",
     ["熊派 7 条成立"], ["熊派 6 条成立"]),
    ("4-分母口径", "−4.47% 应缺席；−4.44% 应在场",
     ["−4.47%", "-4.47%"], ["−4.44%"]),
    ("5-错值A", "−1.86% 应缺席；−1.89% 应在场",
     ["−1.86%", "-1.86%"], ["−1.89%"]),
    ("5-错值B", "「距1.202为−1.02%」应缺席；「距入场…−1.34%」应在场",
     ["1.202 为 −1.02%", "1.202（MA_10，−1.02%"], ["−1.34%"]),
    ("5-语病", "「一个未收盘的」应缺席",
     ["一个未收盘的"], ["短周期均线"]),
    ("6-外部标的", "简报不应再引用 512400 的读数",
     ["512400.SS 测得", "512400 的 HV20"], []),
]

# 「禁止引用其他标的」这类**澄清语境**允许出现 515100/512400 字样，不计入违规
ALLOW_CTX = ("禁止引用", "不引用", "不是", "≠", "仅针对", "不适用于", "隔离", "尤其")


def scan(text: str) -> tuple[list[str], list[str]]:
    bad, good = [], []
    for line in text.splitlines():
        if any(k in line for k in ALLOW_CTX):
            continue
        bad.append(line)
    return bad, good


def main() -> int:
    targets = [TREE / "complete_report.md"]
    targets += sorted(p for p in TREE.rglob("*.md") if p.name != "complete_report.md")

    print("=" * 94)
    print("独立复核：交付树最终产物是否仍含 6 类矛盾")
    print("=" * 94)
    print(f"扫描对象：{len(targets)} 个文件（complete_report.md + 树内角色文件）\n")

    texts = {}
    for p in targets:
        rel = p.relative_to(TREE).as_posix()
        texts[rel] = p.read_text(encoding="utf-8")

    total_fail = 0
    for tag, desc, absent, present in CHECKS:
        print(f"▸ 【{tag}】{desc}")
        a_hits, p_hits = [], []
        for rel, t in texts.items():
            for old in absent:
                # 逐行判定，跳过澄清语境行
                for i, line in enumerate(t.splitlines(), 1):
                    if old in line and not any(k in line for k in ALLOW_CTX):
                        a_hits.append((rel, i, old, line.strip()[:100]))
            for new in present:
                if new in t:
                    p_hits.append((rel, new))
        ok_absent = not a_hits
        ok_present = (not present) or bool(p_hits)
        status = "✓" if (ok_absent and ok_present) else "✗"
        if status == "✗":
            total_fail += 1
        print(f"   旧值缺席 {'✓' if ok_absent else '✗'} ｜ 新值在场 {'✓' if ok_present else '✗'}  ⇒ {status}")
        for rel, i, old, line in a_hits[:6]:
            print(f"      ✗ 残留 {rel} L{i}: 「{old}」→ {line}")
        if present:
            hitfiles = sorted({r for r, _ in p_hits})
            print(f"      新值命中文件：{', '.join(hitfiles[:6])}{'…' if len(hitfiles) > 6 else ''}")
        print()

    # ── 额外：加仓阶梯是否真的进了交付树 ──
    print("▸ 【新增项】加仓阶梯是否已进入交付树")
    lad = [(r, t.count("加仓阶梯")) for r, t in texts.items() if "加仓阶梯" in t]
    for r, n in sorted(lad):
        print(f"   ✓ {r}: {n} 处")
    need = {"3_trading/trader.md", "5_portfolio/decision.md"}
    have = {r for r, _ in lad}
    miss = need - have
    print(f"   必需文件覆盖：{'✓' if not miss else '✗ 缺 ' + str(miss)}")
    if miss:
        total_fail += 1

    print()
    print("=" * 94)
    print(f"结论：{'✓ 6 类问题均已消失，加仓阶梯已就位' if total_fail == 0 else f'✗ 仍有 {total_fail} 类未通过'}")
    print("=" * 94)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
