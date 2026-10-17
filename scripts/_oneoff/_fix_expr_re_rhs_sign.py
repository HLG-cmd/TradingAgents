# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_expr_re_rhs_sign.py
"""修 `EXPR_RE`（原 SUM_RE）未覆盖的形态：**右侧带显式正负号的算式**。

## 发现的缺口（实测，非推测）
评估报告称「SUM_RE 重写」已修好「正则恒不命中」。实测它确实比原版强，
但**仍有 34% 抓不到** —— 全库 272 处「数% op 数% = ±数」算式里 93 处漏检。

漏检形态（本项目报告里非常常见）：
    4.3684% - 1.6669% = +2.702        ← `=` 后带 `+`
    2.225% − 5.18% = −2.955           ← `=` 后带 Unicode 减号
    32.03% − 32.11% = −0.08

**根因**：正则右侧捕获组写作 `([\\d,]+(?:\\.\\d+)?)`（**不允许符号**），
而真实文本是 `= +2.463` / `= −3.40` ⇒ 整条算式不匹配。

**为什么这是同一类 bug**：`check_sums()` 是「分项之和 == 所写合计」的唯一守门人
（铁律 16）。它抓不到，就等于**这批算式从未被校验过** —— 与「正则恒不命中」同型，
只是范围从「全部」缩到「34%」。

## 修法
右侧捕获组允许可选符号：`([+\\-\\u2212\\u2013\\u2014\\uff0b]?\\s*[\\d,]+(?:\\.\\d+)?)`
并在 `check_sums` 里归一化（去掉空白、Unicode 减号 → `-`）后再 `float()`。

## 双向验证（改完必测）
① **真实写法必命中**：上列三种形态 + 原有 5 种；
② **不得引入假阳性**：日期/年份区间（`1982-1984=100`、`09-16=7.0bp`）仍须被跳过。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "wb_analysis" / "_audit_values.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_expr_re_rhs_sign_20261016.py"

OLD_RE = '''EXPR_RE = re.compile(
    r"(?<![\\d.\\-−–—])"
    r"([\\d,]+(?:\\.\\d+)?\\s*%?"
    r"(?:\\s*[+\\-−–—＋]\\s*[\\d,]+(?:\\.\\d+)?\\s*%?){1,39})"
    r"\\s*[=＝]\\s*\\*{0,2}\\s*([\\d,]+(?:\\.\\d+)?)\\s*%?"
)'''

NEW_RE = '''EXPR_RE = re.compile(
    r"(?<![\\d.\\-−–—])"
    r"([\\d,]+(?:\\.\\d+)?\\s*%?"
    r"(?:\\s*[+\\-−–—＋]\\s*[\\d,]+(?:\\.\\d+)?\\s*%?){1,39})"
    r"\\s*[=＝]\\s*\\*{0,2}\\s*"
    # ★ 2026-10-16 修（**剩余 34% 漏检**）：右侧原要求「纯数字」，而本项目真实写法
    #   大量是 `= +2.463` / `= −3.40`（带显式正负号）⇒ 整条算式不匹配。
    #   实测全库 272 处「数% op 数% = ±数」中有 93 处因此漏检（`check_sums` 从未校验它们，
    #   与铁律 16「分项之和必须等于自写合计」的守门职责直接相关）。
    #   ⇒ 右侧允许可选符号（含 Unicode 减号/全角加号），`check_sums` 侧归一化后取值。
    r"([+\\-−–—＋]?\\s*[\\d,]+(?:\\.\\d+)?)\\s*%?"
)'''

OLD_TOTAL = "            total = float(m.group(2).replace(\",\", \"\"))"
NEW_TOTAL = ("            # ★ 2026-10-16：右侧可能带显式符号（`= +2.463` / `= −3.40`）\n"
             "            #   ⇒ 去掉空白 + Unicode 减号归一化后再转 float。\n"
             "            _rhs = m.group(2).replace(\",\", \"\").replace(\" \", \"\")\n"
             "            for _m in _MINUS:\n"
             "                _rhs = _rhs.replace(_m, \"-\")\n"
             "            _rhs = _rhs.replace(\"＋\", \"+\")\n"
             "            total = float(_rhs)")

EDITS = [
    ("EXPR_RE 右侧允许显式正负号", OLD_RE, NEW_RE),
    ("check_sums 归一化右侧取值", OLD_TOTAL, NEW_TOTAL),
]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")

    if "右侧原要求「纯数字」" in src:
        print("  · 已修过（幂等跳过）")
        return 0

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    print(f"  ↺ 已备份 → {BACKUP.name}")

    for tag, old, new in EDITS:
        if old not in src:
            print(f"  ✗ 未命中：{tag}")
            print("     ⇒ 未做任何写入")
            return 1
        src = src.replace(old, new, 1)
        print(f"  ✓ {tag}")

    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  ✗ ast 校验失败，未落盘：{e}")
        return 1
    TARGET.write_text(src, encoding="utf-8", newline="\n")
    print("  ✓ ast 校验通过，已落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
