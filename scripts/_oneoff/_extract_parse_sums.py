# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_extract_parse_sums.py
"""把算式解析逻辑抽成**纯函数** `parse_sums()`，消除「实现与测试各写一份」。

## 为什么必须做（本次实测暴露的**更深问题**）
修好 `EXPR_RE` 的右侧符号缺口后，正式测试 `test_audit_values_sumregex.py` **3 项 FAIL**，
报 `ValueError: could not convert string to float: '−3.40'`。

**根因不在产品代码，而在测试自己**：该测试文件里的辅助函数 `_sums()` **重新实现了一遍**
解析逻辑（`float(m.group(2)...)`），**没有复用产品实现**。
⇒ 产品侧我已归一化右侧符号，但**测试侧那份副本没有** ⇒ 两侧口径分叉。

⇒ 这正是本项目反复强调的原则（`MEMORY.md`「同一口径只在『该放它的那个文件』写一遍 ——
  写两遍必然漂移」）在**测试代码里**的复现。与 `_contract.py` 的设立动机完全相同：
  **靠注释维系的一致性不是一致性。**

## 修法
1. 在 `_audit_values.py` 里新增纯函数 `parse_sums(line) -> list[tuple[n, s, total]]`
   （无副作用、不读文件 ⇒ 可被测试直接 import）；
2. `check_sums()` 改为**调用它**，不再内联解析；
3. 测试的 `_sums()` 改为 `return parse_sums(line)` —— **一份实现两处消费**。

这样「改产品 = 改测试的口径」，物理上不可能再分叉（与 `_contract.py` 同一手法）。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "wb_analysis" / "_audit_values.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_extract_parse_sums_20261016.py"

NEWLINE = chr(10)
BS = chr(92)   # 反斜杠字面量，避免转义歧义

OLD_BLOCK = (
    "def check_sums(path: Path):" + NEWLINE
    + '    """校验「A + B − C … = 合计」自洽。' + NEWLINE
    + NEWLINE
    + "    返回 [(行号, 分项数, 分项和, 所写合计, 行内容)]，**不限分项个数、支持加减混合**。" + NEWLINE
    + "    ★ 2026-10-16：原实现用 `m.groups()[:4]` 只取前 4 项，10 项算式会被静默截断；" + NEWLINE
    + "      且旧正则本就恒不命中（只认 `+`、要求每项带 `%`）。" + NEWLINE
    + "      现改为逐项提取并**按自带符号累加**，同时支持全角/Unicode 减号，" + NEWLINE
    + "      并跳过日期/年份区间形态（否则 `1982-1984=100` 会被误判成算式）。" + NEWLINE
    + '    """' + NEWLINE
    + "    bad = []" + NEWLINE
    + '    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):' + NEWLINE
    + "        for m in EXPR_RE.finditer(line):" + NEWLINE
    + "            lhs = m.group(1)" + NEWLINE
    + "            if DATELIKE_RE.search(lhs):  # 日期/年份区间，不是算式" + NEWLINE
    + "                continue" + NEWLINE
    + "            terms = []" + NEWLINE
    + "            for sign, val in _TERM_RE.findall(lhs):" + NEWLINE
    + '                v = float(val.replace(",", ""))' + NEWLINE
    + "                terms.append(-v if sign in _MINUS else v)" + NEWLINE
    + "            if len(terms) < 2:" + NEWLINE
    + "                continue" + NEWLINE
    + "            # ★ 2026-10-16：右侧可能带显式符号（`= +2.463` / `= −3.40`）" + NEWLINE
    + "            #   ⇒ 去掉空白 + Unicode 减号归一化后再转 float。" + NEWLINE
    + '            _rhs = m.group(2).replace(",", "").replace(" ", "")' + NEWLINE
    + "            for _m in _MINUS:" + NEWLINE
    + '                _rhs = _rhs.replace(_m, "-")' + NEWLINE
    + '            _rhs = _rhs.replace("＋", "+")' + NEWLINE
    + "            total = float(_rhs)" + NEWLINE
    + "            s = sum(terms)" + NEWLINE
    + "            if abs(s - total) > 0.015:  # 容忍四舍五入" + NEWLINE
    + "                bad.append((ln, len(terms), round(s, 2), total, line.strip()))" + NEWLINE
    + "    return bad"
)

NEW_BLOCK = (
    "def parse_sums(line: str) -> list[tuple[int, float, float]]:" + NEWLINE
    + '    """解析一行里的「A + B − C … = 合计」算式，返回 [(项数, 分项和, 所写合计)]。' + NEWLINE
    + NEWLINE
    + "    ★★ 2026-10-16 抽出为**纯函数**（无副作用、不读文件）—— 这是本文件的**唯一解析口径**。" + NEWLINE
    + NEWLINE
    + "    为什么必须抽出：原 `check_sums()` 把解析**内联**在自己的循环里，而测试文件" + NEWLINE
    + "    `tests/test_audit_values_sumregex.py` 又**复制了一份**（`_sums()`）⇒" + NEWLINE
    + "    产品侧改了口径（右侧允许显式符号），测试侧那份副本没跟上 ⇒ 3 项 FAIL，" + NEWLINE
    + "    报 ValueError（无法把带 Unicode 减号的右侧字符串转成 float）。" + NEWLINE
    + "    ⇒ 与 `_contract.py` 同一动机：**同一口径写两遍必然漂移**。" + NEWLINE
    + "    现在测试改为 `from wb_analysis._audit_values import parse_sums`，" + NEWLINE
    + "    「改产品 = 改测试口径」，物理上不可能再分叉。" + NEWLINE
    + NEWLINE
    + "    规则：不限分项个数、支持加减混合、每项 `%` 可省、支持千分位与全角/Unicode 减号；" + NEWLINE
    + "    右侧允许**显式正负号**（`= +2.463` / `= −3.40`）；" + NEWLINE
    + "    日期/年份区间（`1982-1984=100`、`09-16=7.0bp`）整段跳过。" + NEWLINE
    + '    """' + NEWLINE
    + "    out: list[tuple[int, float, float]] = []" + NEWLINE
    + "    for m in EXPR_RE.finditer(line):" + NEWLINE
    + "        lhs = m.group(1)" + NEWLINE
    + "        if DATELIKE_RE.search(lhs):  # 日期/年份区间，不是算式" + NEWLINE
    + "            continue" + NEWLINE
    + "        terms = []" + NEWLINE
    + "        for sign, val in _TERM_RE.findall(lhs):" + NEWLINE
    + '            v = float(val.replace(",", ""))' + NEWLINE
    + "            terms.append(-v if sign in _MINUS else v)" + NEWLINE
    + "        if len(terms) < 2:" + NEWLINE
    + "            continue" + NEWLINE
    + "        # 右侧可能带显式符号（`= +2.463` / `= −3.40`）" + NEWLINE
    + "        #   ⇒ 去空白 + Unicode 减号归一化后再转 float。" + NEWLINE
    + '        _rhs = m.group(2).replace(",", "").replace(" ", "")' + NEWLINE
    + "        for _ch in _MINUS:" + NEWLINE
    + '            _rhs = _rhs.replace(_ch, "-")' + NEWLINE
    + '        _rhs = _rhs.replace("＋", "+")' + NEWLINE
    + "        out.append((len(terms), round(sum(terms), 2), float(_rhs)))" + NEWLINE
    + "    return out" + NEWLINE
    + NEWLINE
    + NEWLINE
    + "def check_sums(path: Path):" + NEWLINE
    + '    """校验「A + B − C … = 合计」自洽（**解析走 `parse_sums()`，本函数只管比对**）。' + NEWLINE
    + NEWLINE
    + "    返回 [(行号, 分项数, 分项和, 所写合计, 行内容)]。" + NEWLINE
    + "    ★ 2026-10-16：解析已抽到 `parse_sums()` —— 本函数只做「取数 → 比对 → 记录行号」，" + NEWLINE
    + "      避免与测试各写一份口径（见 `parse_sums` 的 docstring）。" + NEWLINE
    + '    """' + NEWLINE
    + "    bad = []" + NEWLINE
    + '    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):' + NEWLINE
    + "        for n_terms, s, total in parse_sums(line):" + NEWLINE
    + "            if abs(s - total) > 0.015:  # 容忍四舍五入" + NEWLINE
    + "                bad.append((ln, n_terms, s, total, line.strip()))" + NEWLINE
    + "    return bad"
)

# 测试文件：把复制的解析逻辑换成 import
TEST = ROOT / "tests" / "test_audit_values_sumregex.py"
TEST_BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_test_use_parse_sums_20261016.py"

OLD_TEST_IMPORT = (
    "from wb_analysis._audit_values import EXPR_RE, DATELIKE_RE, _TERM_RE, _MINUS  # noqa: E402"
)
NEW_TEST_IMPORT = (
    "from wb_analysis._audit_values import (  # noqa: E402" + NEWLINE
    + "    EXPR_RE," + NEWLINE
    + "    parse_sums," + NEWLINE
    + ")"
)

OLD_TEST_SUMS = (
    "def _sums(line: str):" + NEWLINE
    + '    """复刻 check_sums 的判读逻辑，返回 [(项数, 分项和, 合计)]。"""' + NEWLINE
    + "    out = []" + NEWLINE
    + "    for m in EXPR_RE.finditer(line):" + NEWLINE
    + "        lhs = m.group(1)" + NEWLINE
    + "        if DATELIKE_RE.search(lhs):" + NEWLINE
    + "            continue" + NEWLINE
    + "        terms = []" + NEWLINE
    + "        for sign, val in _TERM_RE.findall(lhs):" + NEWLINE
    + '            v = float(val.replace(",", ""))' + NEWLINE
    + "            terms.append(-v if sign in _MINUS else v)" + NEWLINE
    + "        if len(terms) < 2:" + NEWLINE
    + "            continue" + NEWLINE
    + '        out.append((len(terms), round(sum(terms), 2), float(m.group(2).replace(",", ""))))' + NEWLINE
    + "    return out"
)

NEW_TEST_SUMS = (
    "def _sums(line: str):" + NEWLINE
    + '    """返回 [(项数, 分项和, 合计)]。' + NEWLINE
    + NEWLINE
    + "    ★★ 2026-10-16：**不再复刻解析逻辑**，直接复用产品实现 `parse_sums()`。" + NEWLINE
    + "    原先这里复制了一份解析代码，导致产品侧改口径（右侧允许显式符号）时" + NEWLINE
    + "    测试这份副本没跟上 ⇒ 3 项 FAIL。⇒ 与 `_contract.py` 同源：**写两遍必然漂移**。" + NEWLINE
    + '    """' + NEWLINE
    + "    return parse_sums(line)"
)

EDITS = [
    (TARGET, "抽出 parse_sums 纯函数 + check_sums 改为调用它", OLD_BLOCK, NEW_BLOCK),
    (TEST, "测试改为 import parse_sums（删掉复刻的那份）", OLD_TEST_IMPORT, NEW_TEST_IMPORT),
    (TEST, "测试 _sums 改为复用产品实现", OLD_TEST_SUMS, NEW_TEST_SUMS),
]


def main() -> int:
    for path, tag, old, new in EDITS:
        src = path.read_text(encoding="utf-8")
        if "parse_sums" in src and tag.startswith("测试 _sums"):
            print(f"  · 已改过（幂等跳过）：{tag}")
            continue
        if old not in src:
            print(f"  ✗ 未命中：{tag}（{path.name}）")
            print("     ⇒ 未做任何写入")
            return 1
        bak = BACKUP if path == TARGET else TEST_BACKUP
        bak.parent.mkdir(parents=True, exist_ok=True)
        if not bak.exists():
            shutil.copy2(path, bak)
            print(f"  ↺ 已备份 → {bak.name}")
        src = src.replace(old, new, 1)
        try:
            ast.parse(src)
        except SyntaxError as e:
            print(f"  ✗ ast 校验失败（{path.name}），未落盘：{e}")
            return 1
        path.write_text(src, encoding="utf-8", newline="\n")
        print(f"  ✓ {tag}")

    print("  ✓ 全部 ast 校验通过，已落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
