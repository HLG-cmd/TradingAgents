"""wb_analysis/_contract.py 的契约测试。

这个模块的存在理由就是「同一个契约被 8 个文件各写一遍」导致门禁互相打架
（docstring 记着：`**Action**: SELL` 过得了 `_lint_drafts` 却过不了 `_gen_meta`）。
所以测试守两件事：

1. 各条正则的**语义边界** —— 尤其宽松版 / 严格版「不可互换」这条
2. 常量与**外部权威**的一致性 —— 情绪档位曾写成 7 档而与上游全不符
"""
from __future__ import annotations

import pytest

from wb_analysis import _contract as C

# ── 五档词：容忍 Title 与全大写，不容忍全小写 ──────────────────────────────

@pytest.mark.parametrize("text", [
    "**Action**: SELL", "**SELL**", "SELL，", "a Sell rating", "(Buy)", "Hold.",
])
def test_five_re_accepts_title_and_upper(text):
    assert C.FIVE_RE.search(text)


@pytest.mark.parametrize("text", [
    "They hold 5% of shares",
    "funds might sell quickly",
    "retail investors buy dips",
    "portfolio managers underweight cash",
    "overweight exposure is reduced",
])
def test_five_re_does_not_match_lowercase_english_prose(text):
    """小写英文是自然正文语法，不是评级词泄露（2026-10-22 收窄）。"""
    assert not C.FIVE_RE.search(text)


@pytest.mark.parametrize("text", [
    "Buyback program",   # 前缀不得抢先匹配
    "Selling pressure",  # 后缀不得被吞掉
    "Holding company",
    "Buyer",
])
def test_five_re_does_not_match_inside_words(text):
    assert not C.FIVE_RE.search(text)


def test_five_title_re_is_case_sensitive():
    assert C.FIVE_TITLE_RE.search("Sell")
    assert not C.FIVE_TITLE_RE.search("SELL")
    assert not C.FIVE_TITLE_RE.search("sell")


def test_three_bold_upper_re_is_upper_only():
    assert C.THREE_BOLD_UPPER_RE.search("FINAL: **HOLD**")
    assert not C.THREE_BOLD_UPPER_RE.search("**Hold**")


def test_alt_puts_longer_words_first():
    """docstring 明说长词优先 —— 锁住这个顺序，别被后人「顺手排序」改掉。"""
    assert C._alt(("Buy", "Overweight")) == "Overweight|Buy"
    assert C._alt(C.THREE_LEVELS).split("|")[0] in ("Hold", "Sell")


# ── 两条 PROPOSAL 正则：语义不同、不可互换 ────────────────────────────────

def test_proposal_loose_vs_strict_are_not_interchangeable():
    bad = "FINAL TRANSACTION PROPOSAL: **Foo**"
    assert C.PROPOSAL_RE.search(bad), "宽松版用于取值，任意 \\w+ 都要能抓到"
    assert not C.PROPOSAL_STRICT_RE.search(bad), "严格版用于校验，非三档判不合契约"
    for word in ("BUY", "HOLD", "SELL", "buy", "hold", "sell"):
        line = f"FINAL TRANSACTION PROPOSAL: **{word}**"
        assert C.PROPOSAL_STRICT_RE.search(line), word
        assert C.PROPOSAL_RE.search(line), word


# ── 标签正则：只认标签，不做退化解析 ──────────────────────────────────────

def test_label_patterns_only_accept_declared_labels():
    assert C.LABEL_PATTERNS["Recommendation"].search("**Recommendation**: Overweight")
    assert C.LABEL_PATTERNS["Rating"].search("**Rating**：Sell"), "全角冒号也要认"
    assert C.LABEL_PATTERNS["Action"].search("**Action**: Sell")
    assert C.LABEL_PATTERNS["Action"].search("**Action**: SELL")
    # 没有标签就不给取值 —— 退化解析正是铁律 8 警告的污染路径
    assert not C.LABEL_PATTERNS["Recommendation"].search("We recommend Overweight")
    assert set(C.LABEL_PATTERNS) == {"Recommendation", "Rating", "Action"}


# ── 白名单 ────────────────────────────────────────────────────────────────

def test_rating_allowed_files_is_the_six_declared_seats():
    assert C.RATING_ALLOWED_FILES == {
        "manager.md", "portfolio_manager.md", "trader.md",
        "aggressive.md", "conservative.md", "neutral.md",
    }
    assert C.allows_five("trader.md")
    assert not C.allows_five("news.md")
    assert C.FINAL_ALLOWED_FILES == {"trader.md"}


def test_non_tree_artifact_prefixes():
    assert C.is_non_tree_artifact("TREASURY_2026-10-09.json")
    assert C.is_non_tree_artifact("TREASURY_2026-10-09.md")
    assert not C.is_non_tree_artifact("AAPL_2026-10-09.json")
    assert C.NON_TREE_PREFIXES == ("TREASURY",)


# ── 常量之间的关系 ────────────────────────────────────────────────────────

def test_three_levels_subset_of_five_and_no_duplicates():
    assert set(C.THREE_LEVELS) <= set(C.FIVE_LEVELS)
    assert len(C.FIVE_LEVELS) == len(set(C.FIVE_LEVELS)) == 5


def test_sentiment_levels_match_upstream_authority():
    """曾写成 7 档（Very Bullish / Somewhat Bullish …）而与上游全不符 —— 守住不再漂移。"""
    from tradingagents.agents.schemas import SentimentBand

    values = getattr(SentimentBand, "__args__", None)
    if values is None:  # 若上游改成 Enum
        values = [m.value for m in SentimentBand]
    assert list(C.SENTIMENT_LEVELS) == list(values)
