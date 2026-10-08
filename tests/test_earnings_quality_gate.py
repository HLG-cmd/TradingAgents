# lifecycle: reusable
# created: 2026-10-08
"""盈利质量验证器 —— Q5「非经营收益闸门」的**纯逻辑**单测（不联网）。

**为什么要有这一组测试**
2026-10-08 GOOG 轮发现：报表 PE(TTM) 17.3x 看着便宜，实际 TTM 净利里有 **55.7%
来自未实现的权益证券公允价值重估**（SEC 10-Q 原值 Q2'26 单季 99,031M），
剥离后经营性 PE 44.1x —— 报表值是它的 2.5 倍。
原先的两道闸门（负税 / 正常化PE）**都拦不住这一类**：税率正常、正常化PE≈报表PE。

新闸门 Q5 的判据必须能被**双向验证**（铁律 20）：
  - 坏夹具（浮盈占净利 61%）⇒ 必 FAIL
  - 好夹具（浮盈占净利 4%）⇒ 必不误报
缺任一边，闸门就退化成「恒 FAIL」或「恒通过」。

⚠️ 本文件刻意**不调用 network**：只测判定函数的纯逻辑。
   真实抓取路径由 `--tickers` 端到端覆盖（人工跑），不进 CI（避免外部依赖假红）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import wb_analysis._verify_earnings_quality as veq


def _verdict(gain_share: float | None, ni: float = 100.0, gain: float = 0.0):
    """复刻 analyze_one 中 Q5 的判定片段，隔离出纯逻辑以便不联网测试。"""
    fails, warns = [], []
    if gain_share is not None and gain > 0:
        if gain_share >= veq.GAIN_SECURITY_FAIL:
            fails.append("非经营证券收益过高")
        elif gain_share >= veq.GAIN_SECURITY_WARN:
            warns.append("非经营证券收益偏高")
    return fails, warns


class TestQ5GateBilateral:
    """坏夹具必检出 / 好夹具必不误报 —— 两边都要。"""

    def test_goog_like_monster_gain_fails(self):
        """GOOG 型：浮盈占净利 61%（实测值）⇒ 必须 FAIL。"""
        fails, warns = _verdict(gain_share=0.61, gain=1.0)
        assert fails, "浮盈占净利 61% 应触发硬闸门 —— 否则 GOOG 这一整类会被放行"
        assert not warns

    def test_normal_company_passes(self):
        """正常公司：浮盈占净利 4% ⇒ 不得报错（MSFT 实测 4.4%）。"""
        fails, warns = _verdict(gain_share=0.044, gain=1.0)
        assert not fails and not warns, "4% 属正常经营附带，误报会让工具被无视"

    def test_soft_band_warns_not_fails(self):
        """中间带：ORCL 实测 14.8% ⇒ 只警告，不阻断。"""
        fails, warns = _verdict(gain_share=0.148, gain=1.0)
        assert not fails, "15% 达不到 25% 硬线，不应阻断"
        assert warns, "10%~25% 应给出人工过目的提醒"

    def test_negative_gain_not_flagged(self):
        """浮亏（gain<0）不归本闸门管 —— 它是**压低**净利，报表 PE 只会偏高。"""
        fails, warns = _verdict(gain_share=-0.30, gain=-1.0)
        assert not fails and not warns, "负 gain 不是「报表被抬高」，不应命中"

    def test_missing_gain_is_silent(self):
        """取不到该科目 ⇒ 记 —，**不判定**（铁律 27：不可验证即沉默）。"""
        fails, warns = _verdict(gain_share=None, gain=0.0)
        assert not fails and not warns


class TestThresholdOrdering:
    """阈值本身的自洽：warn 线必须低于 fail 线，否则中间带为空。"""

    def test_warn_below_fail(self):
        assert veq.GAIN_SECURITY_WARN < veq.GAIN_SECURITY_FAIL

    def test_threshold_in_empirical_gap(self):
        """阈值应落在「正常公司（<5%）」与「GOOG（61%）」之间，两侧留余量。"""
        assert 0.05 < veq.GAIN_SECURITY_FAIL < 0.61, (
            f"硬线 {veq.GAIN_SECURITY_FAIL} 不在实测间隙内 ⇒ 要么误伤正常公司，要么漏掉 GOOG"
        )


class TestExistingGatesNotBroken:
    """新增闸门不得改变既有 Q3/Q4 的语义（回归保护）。"""

    def test_negative_tax_still_detected(self):
        """DUOL 型：有效税率 −127% ⇒ 仍须被 Q3 拦下。

        注意口径（首版写错过）：`tax_share = (-tax)/ni`，分子分母都是**同期绝对值**。
        税前利润 100、税项 −127（= 税前 × −127%）⇒ 净利 = 100 − (−127) = 227，
        故 tax_share = 127/227 ≈ 0.56，**不是** 0.127。
        """
        pretax, etr = 100.0, -1.27
        tax = pretax * etr          # = −127
        ni = pretax - tax           # = 227
        tax_share = (-tax) / ni
        assert tax_share >= veq.TAX_BENEFIT_FAIL, (
            f"DUOL 型负税应被拦下：tax_share={tax_share:.3f} 应 ≥ {veq.TAX_BENEFIT_FAIL}"
        )
        assert abs(tax_share - 127 / 227) < 1e-9

    def test_pe_tolerance_unchanged(self):
        assert veq.PE_TOLERANCE == 1.2

    def test_gain_gate_constants_present(self):
        for name in ("GAIN_SECURITY_FAIL", "GAIN_SECURITY_WARN"):
            assert hasattr(veq, name), f"缺常量 {name}"
