"""SEC EDGAR 时点基本面 —— 契约测试。

这些测试锁定 2026-09-16 实测发现的三个 bug，防止未来改动把它们带回来：

1. **流量科目必须按 ``start`` 判时长。** 同一份 10-Q 里同一个 ``end`` 会同时出现
   「单季（~90 天）」与「年初至今累计（~270 天）」两条记录，``fp`` 都是 ``Q3``。
   只按 ``end`` 去重会把累计值当季度值 —— 实测 AAPL 的 TTM EPS 因此虚高到 14.92
   （真实约 6 美元）。

2. **tag 回退链要按「覆盖最新期间」选，不是「链上第一个有数据的」。**
   实测 NVDA 的营收因此四年卡在 269 亿（真实已超 1200 亿）。

3. **时点 PE 必须补回拆股因子。** EDGAR 股本/EPS 是申报时原值，价格是复权后的。
   实测未修正时 NVDA 2022-12 的 PE 为 6.6（真实约 66）。

另含时点纪律（``filed <= as_of``）与去重规则的测试。

全部离线：用合成 facts，不联网。
"""
from __future__ import annotations

import pytest

from quant import edgar_fundamentals as ed


def _facts(us_gaap: dict | None = None, dei: dict | None = None) -> dict:
    return {"facts": {"us-gaap": us_gaap or {}, "dei": dei or {}}}


def _tag(rows: list[tuple], unit: str = "USD") -> dict:
    """rows: (start, end, val, filed) —— start=None 表示时点值。"""
    return {"units": {unit: [
        {"start": s, "end": e, "val": v, "filed": f, "form": "10-Q",
         "fy": int(f[:4]), "fp": "Q3"}
        for s, e, v, f in rows
    ]}}


# ── bug #1：时长过滤 ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_quarterly_series_excludes_year_to_date_cumulative():
    """同一 end 下的 ~270 天累计值不得进入季度序列。"""
    facts = _facts(us_gaap={"NetIncomeLoss": _tag([
        # 单季（90 天）
        ("2026-04-01", "2026-06-30", 100.0, "2026-07-30"),
        # 年初至今累计（181 天），同一 end，同样会被标成 Q2
        ("2026-01-01", "2026-06-30", 180.0, "2026-07-30"),
    ])})
    _, rows = ed._pick_series(facts, "net_income", "USD", ed.DUR_QUARTER, "2026-08-01")
    assert len(rows) == 1
    assert rows[0]["val"] == 100.0, "累计值未被剔除 —— bug #1 复发"
    assert ed.DUR_QUARTER[0] <= rows[0]["dur"] <= ed.DUR_QUARTER[1]


@pytest.mark.unit
def test_ttm_sums_four_quarters_and_rejects_year_to_date_values():
    q = [("2026-01-01", "2026-03-31", 100.0, "2026-04-25"),
         ("2026-04-01", "2026-06-30", 110.0, "2026-07-25"),
         ("2026-07-01", "2026-09-30", 120.0, "2026-10-25"),
         ("2026-10-01", "2026-12-31", 130.0, "2027-01-25"),
         # 混入一条 9 个月累计 —— 必须被忽略
         ("2026-01-01", "2026-09-30", 330.0, "2026-10-25")]
    facts = _facts(us_gaap={"NetIncomeLoss": _tag(q)})
    ttm, tag = ed._ttm(facts, "net_income", "2027-02-01")
    assert tag == "NetIncomeLoss"
    assert ttm == pytest.approx(460.0), "TTM 被累计值污染 —— bug #1 复发"


@pytest.mark.unit
def test_ttm_requires_contiguous_year_span():
    """四季必须跨约一年；否则说明期间不连续，宁可返回 None。"""
    facts = _facts(us_gaap={"NetIncomeLoss": _tag([
        ("2020-01-01", "2020-03-31", 1.0, "2020-04-25"),
        ("2020-04-01", "2020-06-30", 1.0, "2020-07-25"),
        ("2020-07-01", "2020-09-30", 1.0, "2020-10-25"),
        ("2026-10-01", "2026-12-31", 1.0, "2027-01-25"),
    ])})
    ttm, _ = ed._ttm(facts, "net_income", "2027-02-01")
    assert ttm is None


@pytest.mark.unit
def test_instant_facts_are_not_duration_filtered():
    """净资产是时点值（无 start），不能因为缺时长就被丢掉。"""
    facts = _facts(us_gaap={"StockholdersEquity": _tag([
        (None, "2025-12-31", 500.0, "2026-02-01"),
        (None, "2026-06-30", 560.0, "2026-08-01"),
    ])})
    rec, tag = ed._latest_instant(facts, "equity", "2026-09-01")
    assert tag == "StockholdersEquity"
    assert rec["val"] == 560.0


# ── bug #2：tag 选择 ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_tag_chain_prefers_the_tag_covering_the_latest_period():
    """链上第一个 tag 只有旧数据时，必须改用覆盖更新的 tag。"""
    facts = _facts(us_gaap={
        # 链上优先，但数据在 2022 年就断了
        "RevenueFromContractWithCustomerExcludingAssessedTax": _tag([
            ("2021-01-01", "2021-12-31", 100.0, "2022-02-01"),
        ]),
        # 链上靠后，但覆盖到最新
        "Revenues": _tag([
            ("2021-01-01", "2021-12-31", 100.0, "2022-02-01"),
            ("2025-01-01", "2025-12-31", 900.0, "2026-02-01"),
        ]),
    })
    tag, rows = ed._pick_series(facts, "revenue", "USD", ed.DUR_ANNUAL, "2026-06-30")
    assert tag == "Revenues", "仍选中了过期 tag —— bug #2 复发"
    assert max(r["end"] for r in rows) == "2025-12-31"


@pytest.mark.unit
def test_tag_chain_prefers_earlier_tag_when_coverage_ties():
    """覆盖期间相同时，仍按链上顺序（更精确的 tag 优先）。"""
    facts = _facts(us_gaap={
        "RevenueFromContractWithCustomerExcludingAssessedTax": _tag([
            ("2025-01-01", "2025-12-31", 100.0, "2026-02-01")]),
        "Revenues": _tag([("2025-01-01", "2025-12-31", 100.0, "2026-02-01")]),
    })
    tag, _ = ed._pick_series(facts, "revenue", "USD", ed.DUR_ANNUAL, "2026-06-30")
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax"


# ── 时点纪律 ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_filings_after_as_of_are_invisible():
    """as_of 之后才申报的数据，在当时不可能知道，必须看不见。"""
    facts = _facts(
        us_gaap={
            "NetIncomeLoss": _tag([("2025-01-01", "2025-12-31", 900.0, "2026-02-14")]),
            "StockholdersEquity": _tag([(None, "2025-12-31", 500.0, "2026-02-14")]),
        },
        dei={"EntityCommonStockSharesOutstanding": _tag(
            [(None, "2025-12-31", 1000.0, "2026-02-14")], unit="shares")},
    )
    before = ed.get_point_in_time("X", "2026-01-31", facts)
    after = ed.get_point_in_time("X", "2026-03-01", facts)
    assert before["net_income"] is None, "用到了尚未申报的数据"
    assert before["equity"] is None
    assert after["net_income"] == 900.0
    assert after["equity"] == 500.0


@pytest.mark.unit
def test_dedupe_by_end_prefers_the_latest_filing():
    """同期多次申报（如更正后重报）应取当时最近一次申报的值。"""
    facts = _facts(us_gaap={"StockholdersEquity": _tag([
        (None, "2025-12-31", 500.0, "2026-02-01"),
        (None, "2025-12-31", 520.0, "2026-05-01"),   # 更正后重报
    ])})
    rec, _ = ed._latest_instant(facts, "equity", "2026-06-01")
    assert rec["val"] == 520.0
    # 但在更正申报之前，市场只知道 500
    rec2, _ = ed._latest_instant(facts, "equity", "2026-03-01")
    assert rec2["val"] == 500.0


# ── bug #3：拆股因子 ─────────────────────────────────────────────────────

@pytest.mark.unit
def test_pe_applies_the_post_as_of_split_factor(monkeypatch):
    """未补拆股因子时 NVDA 2022-12 的 PE 会是 6.6（真实约 66）——必须补。"""
    facts = _facts(
        us_gaap={
            "NetIncomeLoss": _tag([("2021-02-01", "2022-01-31", 100.0, "2022-03-18")]),
            "StockholdersEquity": _tag([(None, "2022-01-31", 400.0, "2022-03-18")]),
        },
        dei={"EntityCommonStockSharesOutstanding": _tag(
            [(None, "2022-01-31", 1000.0, "2022-03-18")], unit="shares")},
    )
    monkeypatch.setattr(ed, "_SPLIT_CACHE", {"X": None})
    monkeypatch.setattr(ed, "cumulative_split_factor", lambda tk, d: 10.0)

    pe, note = ed.pe_at("X", "2022-12-30", price=1.0, facts=facts)
    # 市值 = 1.0 × 1000 × 10 = 10000；PE = 10000 / 100 = 100
    assert pe == pytest.approx(100.0)
    assert "10" in note


@pytest.mark.unit
def test_pe_returns_none_for_loss_makers():
    facts = _facts(
        us_gaap={
            "NetIncomeLoss": _tag([("2025-01-01", "2025-12-31", -50.0, "2026-02-01")]),
            "StockholdersEquity": _tag([(None, "2025-12-31", 100.0, "2026-02-01")]),
        },
        dei={"EntityCommonStockSharesOutstanding": _tag(
            [(None, "2025-12-31", 100.0, "2026-02-01")], unit="shares")},
    )
    pe, note = ed.pe_at("X", "2026-06-30", price=10.0, facts=facts)
    assert pe is None
    assert "亏损" in note


@pytest.mark.unit
def test_split_factor_is_one_when_no_splits_after_as_of(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(ed, "_SPLIT_CACHE",
                        {"X": pd.Series([10.0], index=pd.to_datetime(["2024-06-10"]))})
    assert ed.cumulative_split_factor("X", "2025-01-01") == pytest.approx(1.0)
    assert ed.cumulative_split_factor("X", "2022-01-01") == pytest.approx(10.0)


@pytest.mark.unit
def test_split_factor_handles_empty_series_without_crashing(monkeypatch):
    """pandas Series 的真值判断会抛异常 —— 必须用 len() 判空。"""
    import pandas as pd
    monkeypatch.setattr(ed, "_SPLIT_CACHE", {"X": pd.Series([], dtype=float)})
    assert ed.cumulative_split_factor("X", "2025-01-01") == pytest.approx(1.0)


# ── 派生指标 ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_derived_metrics_and_missing_values_stay_none():
    facts = _facts(
        us_gaap={
            "NetIncomeLoss": _tag([("2025-01-01", "2025-12-31", 100.0, "2026-02-01")]),
            "StockholdersEquity": _tag([(None, "2025-12-31", 400.0, "2026-02-01")]),
            "RevenueFromContractWithCustomerExcludingAssessedTax": _tag([
                ("2024-01-01", "2024-12-31", 800.0, "2025-02-01"),
                ("2025-01-01", "2025-12-31", 1000.0, "2026-02-01"),
            ]),
        },
        dei={"EntityCommonStockSharesOutstanding": _tag(
            [(None, "2025-12-31", 100.0, "2026-02-01")], unit="shares")},
    )
    p = ed.get_point_in_time("X", "2026-06-30", facts)
    assert p["roe"] == pytest.approx(0.25)
    assert p["margin"] == pytest.approx(0.10)
    assert p["revenue_growth"] == pytest.approx(0.25)

    # 完全空的 facts 应全为 None，而不是填默认值冒充数据
    empty = ed.get_point_in_time("X", "2026-06-30", _facts())
    for k in ("net_income", "revenue", "equity", "roe", "margin", "revenue_growth"):
        assert empty[k] is None, f"{k} 被填了默认值"

# ── 缓存策略（2026-09-16：原按天缓存会撑爆磁盘）─────────────────────────
# 原实现 facts_<TICKER>_<YYYY-MM-DD>.json，每套 342 MB（102 家）。
# 每天运行一次就多占 342 MB ⇒ 30 天 10 GB、365 天 123 GB。
# 但 XBRL facts 只在季报/年报发布时变化，按天缓存毫无意义。
# 现改为按季度命名，并在预热后清理旧季度。

@pytest.mark.unit
def test_quarter_key_format_and_rollover():
    import datetime as dt
    assert ed._quarter_key(dt.date(2026, 1, 1)) == "2026Q1"
    assert ed._quarter_key(dt.date(2026, 3, 31)) == "2026Q1"
    assert ed._quarter_key(dt.date(2026, 4, 1)) == "2026Q2"
    assert ed._quarter_key(dt.date(2026, 12, 31)) == "2026Q4"


@pytest.mark.unit
def test_facts_cache_filename_is_quarterly_not_daily(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CACHE_DIR", tmp_path)
    p = ed._facts_cache_path("AAPL")
    name = p.name
    assert ed._quarter_key() in name, f"缓存名应含季度键，实际 {name}"
    # 不得出现 YYYY-MM-DD 形式的日期（那正是会撑爆磁盘的旧格式）
    import re
    assert not re.search(r"\d{4}-\d{2}-\d{2}", name), f"仍是按天命名: {name}"


@pytest.mark.unit
def test_prune_cache_removes_other_quarters_and_keeps_current(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CACHE_DIR", tmp_path)
    keep = ed._quarter_key()
    (tmp_path / f"facts_AAPL_{keep}.json").write_text("{}", encoding="utf-8")
    (tmp_path / "facts_NVDA_2020Q1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "facts_MSFT_2019Q4.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cik_map.json").write_text("{}", encoding="utf-8")

    removed = ed.prune_cache(verbose=False)
    assert removed == 2
    remaining = {f.name for f in tmp_path.iterdir()}
    assert f"facts_AAPL_{keep}.json" in remaining, "当前季度被误删"
    assert "cik_map.json" in remaining, "CIK 映射被误删"
    assert "facts_NVDA_2020Q1.json" not in remaining


@pytest.mark.unit
def test_prune_cache_on_missing_dir_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CACHE_DIR", tmp_path / "does_not_exist")
    assert ed.prune_cache(verbose=False) == 0


@pytest.mark.unit
def test_cache_size_mb_reports_and_handles_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ed, "CACHE_DIR", tmp_path / "nope")
    assert ed.cache_size_mb() == 0.0
    monkeypatch.setattr(ed, "CACHE_DIR", tmp_path)
    (tmp_path / "a.json").write_text("x" * 1000, encoding="utf-8")
    assert ed.cache_size_mb() > 0


# ── 多年营收 CAGR：抗「并购并表台阶」与「年度序列缺口」────────────────────
# 2026-09-20 新增。动机：yfinance 的 revenueGrowth 是**单季总营收同比**，
# 并购并表会台阶式跳升（实测 COF 单季 +1111% vs EDGAR 3 年 CAGR +14.2%），
# 周期股的一次性反弹也会被当成成长（SM 单期 +17.5% 但 3 年 CAGR −2.1%）。

_REV_TAG = "RevenueFromContractWithCustomerExcludingAssessedTax"


def _annual_rev(pairs: list[tuple[int, float]]) -> dict:
    """pairs: (财年, 营收) —— 生成跨 1/1~12/31 的年度期间（跨度 365 天）。"""
    rows = []
    for year, val in pairs:
        rows.append((f"{year}-01-01", f"{year}-12-31", val, f"{year + 1}-02-15"))
    return _facts(us_gaap={_REV_TAG: _tag(rows)})


@pytest.mark.unit
def test_revenue_cagr_3y_from_four_consecutive_annual_periods():
    """4 个连续年度 ⇒ 3 年 CAGR = (133.1/100)^(1/3) − 1 = 10%。"""
    facts = _annual_rev([(2022, 100.0), (2023, 110.0), (2024, 121.0), (2025, 133.1)])
    cagr, tag, levels = ed._annual_growth_n(facts, "revenue", "2026-06-30", 3)
    assert tag == _REV_TAG
    assert levels == 3, "应串起 4 个年度观测（levels = 间隔数 = 3）"
    assert cagr == pytest.approx(0.10, abs=1e-4)


@pytest.mark.unit
def test_revenue_cagr_rejects_gap_in_annual_series():
    """**核心护栏**：年度序列缺一年时，必须返回 None，不得把间隔两年的两条当相邻年。

    若不做间隔校验，(2025 vs 2023) 会被算成「1 年翻倍」⇒ 虚高成 +74%/年。
    """
    facts = _annual_rev([(2022, 100.0), (2023, 110.0), (2025, 133.1)])   # 缺 2024
    cagr, _, levels = ed._annual_growth_n(facts, "revenue", "2026-06-30", 3)
    assert cagr is None
    assert levels == 0, "链上只应剩最新一条"


@pytest.mark.unit
def test_revenue_cagr_rejects_nonpositive_base():
    """基年营收 <= 0 时无法取几何平均 ⇒ None（不填默认值冒充）。"""
    facts = _annual_rev([(2022, 0.0), (2023, 110.0), (2024, 121.0), (2025, 133.1)])
    cagr, _, _ = ed._annual_growth_n(facts, "revenue", "2026-06-30", 3)
    assert cagr is None


@pytest.mark.unit
def test_revenue_cagr_requires_enough_levels():
    """只有 2 个年度观测时，取不到 3 年 CAGR ⇒ None（宁缺勿错）。"""
    facts = _annual_rev([(2024, 121.0), (2025, 133.1)])
    cagr, _, levels = ed._annual_growth_n(facts, "revenue", "2026-06-30", 3)
    assert cagr is None
    assert levels == 1


@pytest.mark.unit
def test_revenue_cagr_is_exposed_via_point_in_time():
    """契约：``get_point_in_time`` 必须输出 3y/5y CAGR 及其 levels。"""
    facts = _annual_rev([(2021, 90.0), (2022, 100.0), (2023, 110.0),
                         (2024, 121.0), (2025, 133.1)])
    out = ed.get_point_in_time("TEST", "2026-06-30", facts)
    assert out["revenue_cagr_3y"] == pytest.approx(0.10, abs=1e-4)
    assert out["revenue_cagr_3y_levels"] == 3
    assert out["revenue_cagr_3y_tag"] == _REV_TAG
    # 只有 5 个年度观测，而 5 年 CAGR 需要 6 个 ⇒ 必须如实返回 None，
    # 不得退化成「最近的 4 年」冒充 5 年（levels 记录实际用上几个年度）。
    assert out["revenue_cagr_5y"] is None
    assert out["revenue_cagr_5y_levels"] == 4


# ── 营收科目必须与净利相容（银行易取到「合同收入」窄口径）──────────────────
# 2026-09-20 实测：CATY/WAL/COLB/EBC/CFG 的净利率高达 120%~584% ——
# `RevenueFromContractWithCustomer*` 对银行只覆盖手续费，不含净利息收入。

_QUARTERS = [
    ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"),
    ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31"),
]


def _qtag(vals: list[float], filed: str = "2026-02-15") -> dict:
    return _tag([(s, e, v, filed) for (s, e), v in zip(_QUARTERS, vals)])


@pytest.mark.unit
def test_revenue_tag_switches_when_net_income_exceeds_revenue():
    """净利 > 营收（合同收入窄口径）⇒ 必须换到相容口径 ``Revenues``。"""
    facts = _facts(us_gaap={
        "NetIncomeLoss": _qtag([25.0, 25.0, 25.0, 25.0]),          # 合计 100
        _REV_TAG: _qtag([5.0, 5.0, 5.0, 5.0]),                     # 合计 20 ⇒ 不相容
        "Revenues": _qtag([100.0, 100.0, 100.0, 100.0]),           # 合计 400 ⇒ 相容
    })
    out = ed.get_point_in_time("BANK", "2026-06-30", facts)
    assert out["revenue_tag"] == "Revenues"
    assert out["margin"] == pytest.approx(100.0 / 400.0, abs=1e-6)
    assert out["revenue_tag_implausible"] is False


@pytest.mark.unit
def test_revenue_tag_keeps_default_when_already_plausible():
    """**回归护栏**：默认选择已相容时**不得**换口径。

    否则会按「链序」重挑，把本来正确的标的换坏 —— 实测 JPM 的净利率
    曾被从 33.8% 换成 70.7%（不同的 bank 口径量级完全不同）。
    """
    facts = _facts(us_gaap={
        "NetIncomeLoss": _qtag([25.0, 25.0, 25.0, 25.0]),          # 合计 100
        _REV_TAG: _qtag([100.0, 100.0, 100.0, 100.0]),             # 合计 400 ⇒ 已相容
        "Revenues": _qtag([25.0, 25.0, 25.0, 25.0]),               # 合计 100 ⇒ 另一个口径
    })
    out = ed.get_point_in_time("CORP", "2026-06-30", facts)
    assert out["revenue_tag"] == _REV_TAG, "默认口径已相容，不应被换掉"
    assert out["margin"] == pytest.approx(100.0 / 400.0, abs=1e-6)


@pytest.mark.unit
def test_revenue_tag_implausible_flag_when_no_compatible_tag_exists():
    """全链都不相容 ⇒ 不臆造：如实打 ``revenue_tag_implausible`` 标记。"""
    facts = _facts(us_gaap={
        "NetIncomeLoss": _qtag([25.0, 25.0, 25.0, 25.0]),
        _REV_TAG: _qtag([5.0, 5.0, 5.0, 5.0]),                     # 只有这一条且不相容
    })
    out = ed.get_point_in_time("BANK2", "2026-06-30", facts)
    assert out["revenue_tag_implausible"] is True
