"""wb_analysis/_strip_stray_ratings.py 的测试。

它的职责是渲染前把 manager.md 正文里的裸五档英文词换成中文表述（铁律 8：
`extract_rating` 扫全文取**第一个**五档词，正文残留就会污染评级解析），
换完还要回读验证。所以测试守两件事：

1. 结论块那一行**一个字都不能动** —— 它是契约本身，不是漏网的裸词
2. 回读验证的口径必须与它要防的门禁**一致** —— 门禁 `_lint_drafts` 用的是
   大小写不敏感的 `FIVE_RE`，验证用 Title-only 就会给出假的「已清干净」
"""
from __future__ import annotations

import pytest

from wb_analysis import _strip_stray_ratings as sr

REL = "2_research/manager.md"


@pytest.fixture()
def draft(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    d = tmp_path / "drafts" / "NDX_2026-09-21"
    (d / "2_research").mkdir(parents=True)
    return d


def _run(draft, monkeypatch):
    monkeypatch.setattr(sr.sys, "argv",
                        ["_strip_stray_ratings.py", "drafts/NDX_2026-09-21", REL])
    return sr.main()


def _body(draft):
    return (draft / REL).read_text(encoding="utf-8").split("\n")


def test_conclusion_block_line_is_never_touched(draft, monkeypatch):
    (draft / REL).write_text(
        "**Recommendation**: Overweight\n正文里也不该出现 Overweight 这种裸词。\n",
        encoding="utf-8")
    assert _run(draft, monkeypatch) == 0
    lines = _body(draft)
    assert lines[0] == "**Recommendation**: Overweight", "结论块必须逐字保留"
    assert "Overweight" not in lines[1]
    assert "增持档" in lines[1]


def test_trader_last_line_is_never_touched(draft, monkeypatch):
    p = draft / REL
    p.write_text("FINAL TRANSACTION PROPOSAL: **SELL**\n正文无裸词。\n", encoding="utf-8")
    assert _run(draft, monkeypatch) == 0
    assert _body(draft)[0] == "FINAL TRANSACTION PROPOSAL: **SELL**"


def test_known_phrasings_are_replaced(draft, monkeypatch):
    (draft / REL).write_text(
        "**Recommendation**: Hold\n评级从 Overweight/Buy 调整为 Underweight/Sell。\n",
        encoding="utf-8")
    assert _run(draft, monkeypatch) == 0
    body = _body(draft)[1]
    assert "Overweight/Buy" not in body
    assert "Underweight/Sell" not in body
    assert "上调档" in body and "下调档" in body


def test_clean_draft_returns_zero(draft, monkeypatch):
    (draft / REL).write_text("**Recommendation**: Hold\n正文只讲中文档位。\n",
                             encoding="utf-8")
    assert _run(draft, monkeypatch) == 0


def test_uppercase_stray_words_are_cleaned_and_verified(draft, monkeypatch):
    """★ 2026-10-22：清扫工具升级为自动替换大写裸词（**BUY** / SELL）。
    替换后正文不再残留大写五档词，回读验证确认 0 处并退出 0。
    """
    (draft / REL).write_text("**Recommendation**: Hold\n信号表：**BUY** / SELL 两列。\n",
                             encoding="utf-8")
    assert _run(draft, monkeypatch) == 0
    body = _body(draft)[1]
    assert "BUY" not in body
    assert "SELL" not in body
    assert "建仓档" in body
    assert "退出档" in body

