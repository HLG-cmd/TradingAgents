"""quant/stock_pools.py 的回归测试。

重点是锁住 2026-09-16 那次修复的**判据**（模块 docstring 记了代价：
静态快照 96 只里 42 只是错的，等于一直用错误的股票池筛选）：
  · 请求超时必须留足余量 —— 原 ``timeout=5`` 太薄会偶发超时并静默回退
  · 成分股缓存必须单文件（按天命名会每天留一份副本）
  · 解析要认「列名 + 行数 + sanity 锚点」三重条件，防止抓到别的表
  · 无合格表时**抛错**而非返回空 —— 静默返回空正是「永远回退到过期快照」的成因

这里 stub 掉 ``requests.get`` 与 ``pd.read_html``：测的是**选择逻辑**，
不是 pandas 的 HTML 解析能力，因此不依赖 lxml/bs4，结果完全确定。
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

import quant.stock_pools as sp


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def test_cache_path_is_single_file_not_per_day(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "CACHE_DIR", tmp_path)
    p = sp._cache_path("nasdaq100")
    assert p.name == "constituents_nasdaq100.json"
    # 按天命名会每天留一份副本；文件名里不应出现日期（kind 名本身含数字是允许的）
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{8}", p.name)


def test_parser_picks_qualifying_table_and_normalizes(monkeypatch):
    too_small = pd.DataFrame({"Ticker": ["AAPL", "MSFT"]})              # 行数不足
    no_anchor = pd.DataFrame({"Ticker": [f"X{i}" for i in range(200)]})  # 无锚点
    good = pd.DataFrame({"Ticker": ["nvda", "AAPL", "BRK.B", "nvda"]})   # 合格
    seen: dict = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"], seen["timeout"] = url, timeout
        return _Resp("<html/>")

    monkeypatch.setattr(sp.requests, "get", fake_get)
    monkeypatch.setattr(sp.pd, "read_html", lambda *a, **k: [too_small, no_anchor, good])

    out = sp._fetch_wiki_tickers("https://example/x", ("Ticker",), 3)
    assert out == ["NVDA", "AAPL", "BRK-B"], "大写 + .→- + 保序去重"
    # 锁住 timeout=5 → 20 的修复：余量太薄会偶发超时并静默回退到过期快照
    assert seen["timeout"] == sp.WIKI_TIMEOUT
    assert seen["timeout"] > 5
    assert seen["url"] == "https://example/x"


def test_parser_raises_when_nothing_qualifies(monkeypatch):
    """无合格表必须抛错，不能静默返回空 —— 静默返回空会让调用方以为成功。"""
    monkeypatch.setattr(sp.requests, "get", lambda *a, **k: _Resp("<html/>"))
    monkeypatch.setattr(
        sp.pd, "read_html",
        lambda *a, **k: [pd.DataFrame({"Ticker": ["AAPL"]})],
    )
    with pytest.raises(ValueError):
        sp._fetch_wiki_tickers("https://example/x", ("Ticker",), 3)


def test_static_snapshots_are_nonempty_and_unique():
    """静态快照是动态同步失败时的兜底 —— 它自己不能有重复项。"""
    for name in ("NASDAQ_100", "SP_500_CORE"):
        pool = getattr(sp, name)
        assert pool, f"{name} 不应为空"
        assert len(pool) == len(set(pool)), f"{name} 有重复代码"
        assert all(t == t.upper() for t in pool), f"{name} 应全大写"


def test_sanity_anchors_are_present_in_nasdaq_snapshot():
    """锚点集合是解析判据的一部分，兜底快照至少应覆盖它们。"""
    assert sp.SANITY_ANCHORS <= set(sp.NASDAQ_100)
