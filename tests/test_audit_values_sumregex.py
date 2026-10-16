# lifecycle: test
"""`_audit_values.check_sums` 的回归测试 —— 锁住 2026-10-16 修复的那个 bug。

## 为什么需要（血泪）
`check_sums()` 自称能查「分项被反向编造」，但它的正则 `SUM_RE` 要求算式严格形如
`X% + Y% = Z%`（每项必须带 `%`、最多 4 项、项间不许有文字）。而项目里真实写法是
「（算式：8.79+7.16+…+2.54 = 45.54%）」——不带 `%`、10 项。
⇒ 实测 57 棵报告树里 402 行算式，命中 **0 行**，该校验**完全失效**，
2026-10-16 审计发现的 4 处「持仓合计」错误全部漏检。

这个测试同时锁三边（防「改宽了就误报」和「改窄了就漏检」）：
  ① 真实写法必须命中；② 日期/年份区间不得被误当算式；③ 真错误必须被判不符。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis._audit_values import (  # noqa: E402
    EXPR_RE,
    parse_sums,
)


def _sums(line: str):
    """返回 [(项数, 分项和, 合计)]。

    ★★ 2026-10-16：**不再复刻解析逻辑**，直接复用产品实现 `parse_sums()`。
    原先这里复制了一份解析代码 ⇒ 产品侧改口径（右侧允许显式符号）时这份副本没跟上，
    导致 3 项 FAIL。⇒ 与 `_contract.py` 同源：**同一口径写两遍必然漂移**。
    """
    return parse_sums(line)


@pytest.mark.unit
class TestCheckSumsDetection:
    """① 真实写法必须命中（原 bug：命中 0）"""

    @pytest.mark.parametrize("line,n,expected", [
        # 本次审计里 512400 的真实写法：10 项、分项不带 %
        ("（算式：8.79+7.16+5.68+4.42+4.08+3.45+3.42+3.04+2.96+2.54 = 45.54%）", 10, 45.54),
        # 515100 的真实写法
        ("（算式：2.71+2.55+2.39+2.12+1.82+1.73+1.69+1.68+1.63+1.56 = 19.88）", 10, 19.88),
        # 带千分位、带负号
        ("102,718 − 42,779 + 74,421 = 134,360", 3, 134360.0),
        ("1,110 − 149 + 1,360 = 2,321", 3, 2321.0),
        # 教科书格式（旧正则唯一能命中的那种）仍须命中
        ("1.10% + 2.20% = 3.30%", 2, 3.30),
        # ★ 2026-10-16 补：**右侧带显式正负号** —— 本项目报告里最常见的形态，
        #   而 2026-10-16 那次「SUM_RE 重写」**未覆盖它**（实测全库 272 处此类算式中 93 处漏检）。
        #   根因：右侧捕获组原要求「纯数字」，而真实文本是 `= +2.463` / `= −3.40`。
        ("股息率溢价：4.1206% - 1.6571% = +2.463", 2, 2.463),
        ("净溢价：2.225% − 5.180% = −2.955", 2, -2.955),
        ("32.03% − 32.11% = −0.08", 2, -0.08),
    ])
    def test_real_writing_is_parsed(self, line, n, expected):
        got = _sums(line)
        assert got, f"未命中真实算式（原 bug 复现）: {line}"
        assert got[0][0] == n, f"项数应为 {n}，实得 {got[0][0]}"
        assert got[0][2] == pytest.approx(expected, abs=0.02)

    def test_all_terms_captured_not_truncated_to_four(self):
        """原实现用 m.groups()[:4] 硬截前 4 项 —— 10 项算式会被静默截断。"""
        line = "1+2+3+4+5+6+7+8+9+10 = 55"
        got = _sums(line)
        assert got and got[0][0] == 10, f"10 项算式被截断: {got}"
        assert got[0][1] == pytest.approx(55.0)


@pytest.mark.unit
class TestNoFalsePositives:
    """② 日期 / 年份区间不得被误当算式（改宽后的主要风险）"""

    @pytest.mark.parametrize("line", [
        "- Units: Index 1982-1984=100",
        "| CPI（1982-84=100） | 334.131 | 2026-08-01 |",
        "（^TNX 单位=百分数：09-16=7.0bp  09-17=2.0bp  09-18=4.0bp）",
        "- 2026-10-15 1.446 1.435 1.449 1.424",
        "收盘序列首尾：09-08 = 477.30 … 10-05 = 441.64",
        # ★ 2026-10-16 补：右侧允许符号后，日期的「= +数」形态也不得误报
        "- Units: Index 1982-1984=+100",
    ])
    def test_date_like_not_treated_as_expression(self, line):
        assert _sums(line) == [], f"日期被误当算式: {line}"


@pytest.mark.unit
class TestRealErrorsStillCaught:
    """③ 真错误必须被判『不符』"""

    @pytest.mark.parametrize("line,expect_sum,expect_total", [
        # 512400 的真实错误：算式算出 45.54 却写 45.7
        ("（算式：8.79+7.16+5.68+4.42+4.08+3.45+3.42+3.04+2.96+2.54 = 45.7%）", 45.54, 45.7),
        # 515100 的真实错误：算式算出 19.88 却写 19.28
        ("（算式：2.71+2.55+2.39+2.12+1.82+1.73+1.69+1.68+1.63+1.56 = 19.28）", 19.88, 19.28),
        # ★ 2026-10-16 补：右侧带符号时的**真错值**也要能判不符
        #   （真值 4.3684−1.6669 = 2.7015，却写 +3.10 ⇒ 差 0.40，明显不符）
        ("股息率溢价：4.3684% - 1.6669% = +3.10", 2.7015, 3.10),
        #   （真值 2.225−5.180 = −2.9550，却写 −3.40 ⇒ 差 0.445）
        ("净溢价：2.225% − 5.18% = −3.40", -2.9550, -3.40),
    ])
    def test_mismatch_detected(self, line, expect_sum, expect_total):
        got = _sums(line)
        assert got, f"未命中: {line}"
        _, s, t = got[0]
        assert s == pytest.approx(expect_sum, abs=0.02)
        assert t == pytest.approx(expect_total, abs=0.02)
        assert abs(s - t) > 0.015, "本该判为不符，却判成自洽"


@pytest.mark.unit
class TestBackwardCompat:
    def test_sum_re_alias_still_importable(self):
        from wb_analysis._audit_values import SUM_RE
        assert SUM_RE is EXPR_RE, "SUM_RE 应作为 EXPR_RE 的别名保留，避免破坏既有 import"
