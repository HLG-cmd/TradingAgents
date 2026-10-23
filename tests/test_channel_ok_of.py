"""wb_analysis/_channel.py（采集通道健康度判据 ok_of）的单元测试。

锁定两类契约：
1. 双向判据（好夹具必 True、各类伪成功/错误文本必 False）；
2. 单一来源约束（各采集器统一从 `_channel` 导入 `ok_of`，不得本地重定义 `def ok_of`）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wb_analysis import collect_a_etf, collect_a_stock, collect_hk_index, collect_hk_stock
from wb_analysis._channel import ok_of

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        # 正常数据（含带 "error" 字样的正常注释，不应假红）
        ("date,open,high,low,close\n2026-10-22,10.1,10.5,10.0,10.4", True),
        ("date,close\n2026-10-22,10.4  # no error found", True),
        ("| code | name | price |\n|---|---|---|\n| sh601899 | 紫金矿业 | 18.50 |", True),
        # 空串 / 空白 / None
        ("", False),
        ("   \n\t  ", False),
        (None, False),
        # run_westock 哨兵错误串
        ("<westock 退出码 1>\nstderr", False),
        ("<westock 调用失败 TimeoutExpired: ...>", False),
        # westock 中文长错误文本（防止 >40 字符后才出现 error 导致假绿）
        (
            "查询dayK线数据返回为空，标的代码可能非法，请确认后重试：[code=1620053001] msg=service error",
            False,
        ),
        (
            "查询dayK线失败：[code=1620053001] error_type=2 suggest=3 msg=service error",
            False,
        ),
        ("数据为空", False),
        ("(命令失败: RuntimeError: boom)", False),
        # ── 2026-10-23 二次修正：真实语料夹具（此前 12 条全是构造串，漏掉了这两类）──
        # ① westock batch 成功汇总行自带「失败: 0」⇒ 不得判失败
        #    真实出处：reports/601899.SS/601899.SS_20261019_004657 的 §5.2 融资融券
        (
            "\n[Batch] 状态: success | 总数: 1 | 成功: 1 | 失败: 0\n\n"
            "#### sh601899 （6 个交易日）\n\n"
            "| code | name | date | closePrice |\n|---|---|---|---|\n"
            "| sh601899 | 紫金矿业 | 2026-10-17 | 18.50 |",
            True,
        ),
        # ② 新闻/公告正文含「失败」是内容，不是通道故障
        ("1. 紫金矿业：海外并购项目因审批失败终止\n2. 公司回应：以公告为准", True),
        ("投资者可在交易所网站查询公司公告全文", True),
        # ③ 但「查询失败」这类真故障句式仍须判失败
        ("查询失败，请稍后重试", False),
        ("失败：[code=1620053001]", False),
        # ④ batch 汇总里的**非零**失败数 = 真故障
        ("[Batch] 状态: partial | 总数: 2 | 成功: 1 | 失败: 1", False),
    ],
)
def test_ok_of_bidirectional_cases(raw, expected):
    assert ok_of(raw) is expected


@pytest.mark.unit
def test_collectors_share_identical_ok_of_object():
    """各采集器引用的 ok_of 必须是同一个函数对象（消除双判据漂移）。"""
    assert collect_a_etf.ok_of is ok_of
    assert collect_a_stock.ok_of is ok_of
    assert collect_hk_index.ok_of is ok_of
    assert collect_hk_stock.ok_of is ok_of


@pytest.mark.unit
def test_no_local_ok_of_redefinition_in_collectors():
    """源码层守卫：消费方不得再本地写 `def ok_of(`。"""
    for name in (
        "collect_a_etf.py",
        "collect_a_stock.py",
        "collect_hk_index.py",
        "collect_hk_stock.py",
    ):
        src = (ROOT / "wb_analysis" / name).read_text(encoding="utf-8")
        assert "def ok_of(" not in src, f"{name} 仍含本地定义的 def ok_of("
        assert "from wb_analysis._channel import ok_of" in src, f"{name} 未从 _channel 导入 ok_of"
