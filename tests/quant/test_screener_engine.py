"""Screener engine contract tests.

These lock in the behaviours that were wrong before the 2026-09-16 refactor, so
a future edit cannot silently reintroduce them:

* loss-making / PE-missing names must score **0** on valuation — the old code
  documented ``0`` but actually awarded ``10``, which ranked a loss-maker above
  the most expensive profitable company.
* the valuation percentile must not be capped, otherwise the cheapest bucket all
  ties at the cap and the factor loses all discriminating power.
* trend sub-signals must be normalised scores, not fixed additive bonuses — the
  fixed bonuses created a flat plateau where ranks 3..10 were decided by noise.
* the day-cache key must include the ticker list, otherwise editing the pool
  still serves yesterday's ranking.
* CSV export must carry a UTF-8 BOM, otherwise Excel on Chinese Windows reads
  the Chinese headers as GBK and shows mojibake.

All tests are offline — no network, no yfinance.
"""
from __future__ import annotations

import csv
import io
import json

import pandas as pd
import pytest

from quant import screener_engine as se


def _raw(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal frame shaped like the engine's internal record table."""
    base = {
        "Ticker": "X", "Price": 100.0, "Trend": "多头", "is_bull": True,
        "has_sma200": True, "mom20": 1.0, "mom60": 5.0, "rsi": 55.0,
        "vol_ratio": 1.0, "last_bar": "2026-09-15", "bars": 1254,
        "pe": 20.0, "roe": 0.2, "margin": 0.2, "rev_growth": 0.1,
        "debt_to_equity": 50.0,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


# ── valuation: loss-makers must not outrank expensive-but-profitable names ──

@pytest.mark.unit
def test_loss_making_name_scores_zero_on_valuation():
    """The old code gave 10.0 to a missing PE while the most expensive company
    got ~1.4 — i.e. losing money scored better than being expensive."""
    raw = _raw([
        {"Ticker": "LOSS", "pe": -3.0},
        {"Ticker": "MOST_EXPENSIVE", "pe": 330.0},
        {"Ticker": "CHEAPEST", "pe": 8.0},
    ])
    out = se._score(raw).set_index("Ticker")
    assert out.loc["LOSS", "val_score"] == 0.0
    assert out.loc["LOSS", "val_score"] < out.loc["MOST_EXPENSIVE", "val_score"]


@pytest.mark.unit
def test_missing_pe_is_flagged_and_scores_zero():
    raw = _raw([{"Ticker": "NA", "pe": None}, {"Ticker": "OK", "pe": 15.0}])
    out = se._score(raw).set_index("Ticker")
    assert out.loc["NA", "pe_missing"] is True or bool(out.loc["NA", "pe_missing"])
    assert out.loc["NA", "val_score"] == 0.0


@pytest.mark.unit
def test_valuation_percentile_is_not_capped():
    """A cap would make every cheap name tie; assert strictly distinct scores."""
    pes = [5.0, 8.0, 11.0, 15.0, 20.0, 40.0, 80.0, 150.0]
    raw = _raw([{"Ticker": f"T{i}", "pe": p} for i, p in enumerate(pes)])
    out = se._score(raw)
    assert out["val_score"].nunique() == len(pes)
    assert out["val_score"].max() > 80.0


# ── trend: normalised sub-scores, no fixed-bonus plateau ──

@pytest.mark.unit
def test_trend_score_spans_full_range_and_stays_bounded():
    rows = [{"Ticker": f"T{i}", "mom60": m, "is_bull": b, "rsi": r}
            for i, (m, b, r) in enumerate([
                (-40.0, False, 20.0), (-10.0, False, 30.0), (0.0, True, 50.0),
                (10.0, True, 55.0), (40.0, True, 65.0), (5.0, True, 90.0),
            ])]
    out = se._score(_raw(rows))
    assert out["trend_score"].between(0, 100).all()
    assert out["trend_score"].nunique() > 3, "plateau detected: scores collapsed"


@pytest.mark.unit
def test_band_score_peaks_inside_band_and_tapers_outside():
    assert se._band_score(55.0, 45.0, 68.0) == 100.0
    assert se._band_score(45.0, 45.0, 68.0) == 100.0
    assert se._band_score(68.0, 45.0, 68.0) == 100.0
    assert se._band_score(30.0, 45.0, 68.0) < 100.0
    assert se._band_score(85.0, 45.0, 68.0) < 100.0
    assert se._band_score(float("nan"), 45.0, 68.0) == 50.0


# ── weights are configurable (so re-calibration needs no code change) ──

@pytest.mark.unit
def test_weights_override_changes_composite_and_default_is_untouched():
    raw = _raw([
        {"Ticker": "HI_Q", "roe": 0.9, "margin": 0.9, "rev_growth": 0.0, "mom60": -30.0},
        {"Ticker": "HI_G", "roe": 0.02, "margin": 0.02, "rev_growth": 0.9, "mom60": 5.0},
        {"Ticker": "HI_T", "roe": 0.02, "margin": 0.02, "rev_growth": 0.0, "mom60": 90.0},
    ])
    default = se._score(raw, None).set_index("Ticker")
    quality_heavy = se._score(raw, {"quality": 1.0, "value": 0.0,
                                    "growth": 0.0, "trend": 0.0}).set_index("Ticker")
    trend_only = se._score(raw, {"quality": 0.0, "value": 0.0,
                                 "growth": 0.0, "trend": 1.0}).set_index("Ticker")

    assert quality_heavy["综合量化分"].idxmax() == "HI_Q"
    assert trend_only["综合量化分"].idxmax() == "HI_T"
    assert default["综合量化分"].idxmax() != "HI_T"
    # the module-level default must not be mutated by a per-call override
    assert se.FACTOR_WEIGHTS == {"quality": 0.30, "value": 0.25,
                                 "growth": 0.25, "trend": 0.20}


@pytest.mark.unit
def test_missing_fundamentals_get_neutral_rank_not_a_penalty():
    """A missing ROE/margin must land mid-pack: worse than a strong name, better
    than a weak one — i.e. 'unknown', not 'bad'.

    Needs >2 valid names for the percentile to have resolution: pandas'
    ``rank(pct=True)`` normalises by the count of *valid* values, so in a
    2-valid-name sample the weakest valid name also lands on 0.5 and becomes
    indistinguishable from the neutral fill. At the engine's real universe size
    (~96) the weakest name sits near 0.01, so no collision occurs.
    """
    rows = [{"Ticker": f"T{i}", "roe": v, "margin": v}
            for i, v in enumerate([0.30, 0.25, 0.20, 0.15, 0.10, 0.05])]
    rows.append({"Ticker": "MISS", "roe": None, "margin": None})
    out = se._score(_raw(rows)).set_index("Ticker")

    assert 0.0 < out.loc["MISS", "quality_score"] < 100.0
    assert out.loc["T0", "quality_score"] > out.loc["MISS", "quality_score"]
    assert out.loc["T5", "quality_score"] < out.loc["MISS", "quality_score"]


@pytest.mark.unit
def test_missing_fundamentals_are_not_dropped_from_the_ranking():
    """A name with unparseable fundamentals still gets scored, not silently lost."""
    rows = [{"Ticker": f"T{i}", "roe": 0.1 * i, "margin": 0.1 * i} for i in range(1, 6)]
    rows.append({"Ticker": "MISS", "roe": None, "margin": None})
    out = se._score(_raw(rows))
    assert "MISS" in set(out["Ticker"])
    assert out.set_index("Ticker").loc["MISS", "综合量化分"] > 0


# ── cache key must depend on the ticker list ──

@pytest.mark.unit
def test_pool_fingerprint_is_order_independent_and_content_sensitive():
    a = se._pool_fingerprint(["NVDA", "AAPL"])
    b = se._pool_fingerprint(["AAPL", "NVDA"])
    c = se._pool_fingerprint(["NVDA", "MSFT"])
    assert a == b, "reordering the pool must not invalidate the cache"
    assert a != c, "changing the pool MUST invalidate the cache"


@pytest.mark.unit
def test_cache_path_includes_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "CACHE_DIR", tmp_path)
    p1 = se._maybe_cache_path("nasdaq", "2026-09-16", ["NVDA", "AAPL"])
    p2 = se._maybe_cache_path("nasdaq", "2026-09-16", ["NVDA", "MSFT"])
    assert p1 != p2
    assert se._pool_fingerprint(["NVDA", "AAPL"]) in p1.name


# ── cache schema versioning ──
# Adding a metadata field once produced a KeyError on downstream consumers because
# a same-day cache written by the previous build was served as-is. The schema
# version makes such a cache a miss instead.

@pytest.mark.unit
def test_stale_cache_schema_is_treated_as_a_miss(tmp_path, monkeypatch):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({
        "records": [{"Ticker": "AAA"}], "metadata": {"stale": True}
    }), encoding="utf-8")   # deliberately no "schema" key

    monkeypatch.setattr(se, "_maybe_cache_path", lambda *a, **k: cache)
    calls = {"n": 0}

    def fake_price(tk, date):
        calls["n"] += 1
        return tk, None, "synthetic failure"

    monkeypatch.setattr(se, "_fetch_price", fake_price)
    monkeypatch.setattr(se, "_fetch_fundamental", lambda tk: (tk, {}, None))

    se.run_quant_screening(["AAA"], pool_name="t")
    assert calls["n"] >= 1, "a cache without the current schema must be refetched"


@pytest.mark.unit
def test_weights_apply_on_the_cached_path(tmp_path, monkeypatch):
    """The cache stores weight-independent sub-scores, so 综合量化分 must be
    recomputed with the caller's weights on read. Before this, every weight
    profile returned an identical ranking because the cached composite was
    reused verbatim."""
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({
        "schema": se.CACHE_SCHEMA_VERSION,
        "records": [
            {"Ticker": "QUALITY_NAME", "quality_score": 100.0, "val_score": 0.0,
             "growth_score": 0.0, "trend_score": 0.0, "综合量化分": 0.0},
            {"Ticker": "TREND_NAME", "quality_score": 0.0, "val_score": 0.0,
             "growth_score": 0.0, "trend_score": 100.0, "综合量化分": 100.0},
        ],
        "failed_records": [], "metadata": {"cached": False},
    }), encoding="utf-8")
    monkeypatch.setattr(se, "_maybe_cache_path", lambda *a, **k: cache)

    q_only = {"quality": 1.0, "value": 0.0, "growth": 0.0, "trend": 0.0}
    t_only = {"quality": 0.0, "value": 0.0, "growth": 0.0, "trend": 1.0}

    assert list(se.run_quant_screening(["X"], weights=q_only)["Ticker"])[0] == "QUALITY_NAME"
    assert list(se.run_quant_screening(["X"], weights=t_only)["Ticker"])[0] == "TREND_NAME"


@pytest.mark.unit
def test_weight_profiles_are_normalised_and_default_is_garp():
    for name, w in se.WEIGHT_PROFILES.items():
        assert set(w) == {"quality", "value", "growth", "trend"}, name
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-9), f"{name} does not sum to 1"
    assert se.FACTOR_WEIGHTS == se.WEIGHT_PROFILES["garp"]
    # the documented alternatives must actually differ from the default
    assert se.WEIGHT_PROFILES["quality"] != se.WEIGHT_PROFILES["garp"]
    assert se.WEIGHT_PROFILES["no_trend"]["trend"] == 0.0


@pytest.mark.unit
def test_composite_helper_matches_the_scorer():
    """_composite is shared by the fresh and cached paths — they must agree."""
    raw = _raw([{"Ticker": "A", "roe": 0.4, "margin": 0.4, "rev_growth": 0.3, "mom60": 20.0},
                {"Ticker": "B", "roe": 0.05, "margin": 0.05, "rev_growth": 0.05, "mom60": -20.0}])
    scored = se._score(raw)
    for w in (None, se.WEIGHT_PROFILES["quality"], se.WEIGHT_PROFILES["no_trend"]):
        assert se._composite(scored, w).tolist() == scored.assign(
            x=se._composite(scored, w))["x"].tolist()
        default = se._composite(scored, None).tolist()
        assert default == scored["综合量化分"].tolist()


@pytest.mark.unit
def test_matching_cache_schema_is_served_without_refetch(tmp_path, monkeypatch):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({
        "schema": se.CACHE_SCHEMA_VERSION,
        "records": [{"Ticker": "AAA", "综合量化分": 50.0,
                     "quality_score": 50.0, "val_score": 50.0,
                     "growth_score": 50.0, "trend_score": 50.0}],
        "failed_records": [],
        "metadata": {"validation": {"caveat": "cached caveat", "factors": {}},
                     "cached": False},
    }), encoding="utf-8")

    monkeypatch.setattr(se, "_maybe_cache_path", lambda *a, **k: cache)
    calls = {"n": 0}

    def fake_price(tk, date):
        calls["n"] += 1
        return tk, None, "should not be called"

    monkeypatch.setattr(se, "_fetch_price", fake_price)

    res = se.run_quant_screening(["AAA"], pool_name="t", return_details=True)
    assert calls["n"] == 0, "a current-schema cache must be served as-is"
    assert res["metadata"]["cached"] is True
    # The validation summary is recomputed for the caller's weights rather than
    # replayed from the cached payload, so a stale caveat string must not survive.
    assert res["metadata"]["validation"]["caveat"] != "cached caveat"
    assert res["metadata"]["validation"]["caveat"] == se.validation_summary()["caveat"]


# ── CSV export: BOM + fixed decimals ──

@pytest.mark.unit
def test_export_radar_csv_writes_bom_and_two_decimals(tmp_path):
    df = pd.DataFrame({
        "Ticker": ["SMCI", "AAPL"], "Price": [36.4, 329.74],
        "量比": [0.85, 1.1], "综合量化分": [29.5, 62.8],
    })
    out = tmp_path / "r.csv"
    se.export_radar_csv(df, str(out))

    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", "missing UTF-8 BOM — Excel will show mojibake"

    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[0][3] == "综合量化分"
    assert rows[1][1] == "36.40"      # trailing zero preserved
    assert rows[1][2] == "0.85"
    assert rows[2][2] == "1.10"
    # source frame must not be mutated (downstream does numeric work on it)
    assert df["Price"].tolist() == [36.4, 329.74]


# ── validation status is surfaced, and honest about what is unproven ──

@pytest.mark.unit
def test_validation_summary_reports_the_insignificant_share():
    """**四个因子都已回测过，但无一显著** —— 这才是该对外说的话。

    2026-09-20 修正：此前这里断言 ``unvalidated_weight_share == 0.80``，
    理由是 quality/value/growth「无法回测」。那个理由是**过时的**
    （EDGAR 提供时点键，`fundamental_backtest.py` 已能回测四个因子）。
    把「已验证无效」误报成「还没验证」会低估风险，故改为「不显著权重占比」。
    """
    s = se.validation_summary()
    # 四个因子 |t| 最大也只有 1.39 < 2 ⇒ 100% 的权重来自未获证实的因子
    assert s["insignificant_weight_share"] == pytest.approx(1.0, abs=1e-6)
    for k in ("quality", "value", "growth", "trend"):
        assert s["factors"][k]["validated"] is True, f"{k} 应标记为已回测"
        assert s["factors"][k]["significant"] is False, f"{k} 实测不显著"
    assert "无一统计显著" in s["caveat"]
    assert "未获证实" in s["caveat"]
    # 旧的误导性措辞不得回归
    assert "未经回测验证" not in s["caveat"]
    assert "unvalidated_weight_share" not in s


@pytest.mark.unit
def test_insignificant_share_tracks_a_custom_weighting():
    s = se.validation_summary({"quality": 0.5, "value": 0.5,
                               "growth": 0.0, "trend": 0.0})
    assert s["insignificant_weight_share"] == pytest.approx(1.0, abs=1e-6)


@pytest.mark.unit
def test_significance_requires_abs_t_at_least_two(monkeypatch):
    """**回归护栏**：|t| >= 2 的因子必须被算作「显著」，占比随之下降。

    这条防的是「验证状态与现实脱节」—— 若将来回测真的跑出显著结果，
    摘要必须跟着变，而不是继续声称全部不显著。
    """
    bumped = {k: dict(v) for k, v in se.FACTOR_VALIDATION.items()}
    bumped["quality"]["t"] = 2.5          # 假设质量档回测变显著了
    monkeypatch.setattr(se, "FACTOR_VALIDATION", bumped)
    s = se.validation_summary()
    assert s["factors"]["quality"]["significant"] is True
    # garp 里 quality 权重 0.30 ⇒ 不显著占比应从 1.0 降到 0.70
    assert s["insignificant_weight_share"] == pytest.approx(0.70, abs=1e-6)


@pytest.mark.unit
def test_missing_t_value_is_treated_as_not_significant(monkeypatch):
    """缺 t 值不得默认「显著」—— 宁可低估自己。"""
    monkeypatch.setattr(se, "FACTOR_VALIDATION", {"quality": {"validated": True}})
    s = se.validation_summary({"quality": 1.0})
    assert s["factors"]["quality"]["significant"] is False
    assert s["insignificant_weight_share"] == pytest.approx(1.0, abs=1e-6)


# ── technicals: do not fabricate a 200-day average ──

@pytest.mark.unit
def test_technical_marks_missing_sma200_instead_of_faking_it():
    dates = pd.bdate_range("2026-01-01", periods=120)
    short = pd.DataFrame({"Date": dates, "Close": range(100, 220),
                          "Volume": [1_000_000] * 120})
    t = se._technical_from_frame(short)
    assert t is not None
    assert t["has_sma200"] is False
    assert t["sma200_dist"] is None

    long = pd.DataFrame({"Date": pd.bdate_range("2024-01-01", periods=300),
                         "Close": range(100, 400), "Volume": [1_000_000] * 300})
    t2 = se._technical_from_frame(long)
    assert t2["has_sma200"] is True
    assert t2["sma200_dist"] is not None


@pytest.mark.unit
def test_technical_returns_none_when_history_too_short():
    short = pd.DataFrame({"Date": pd.bdate_range("2026-08-01", periods=10),
                          "Close": range(10), "Volume": [1] * 10})
    assert se._technical_from_frame(short) is None
