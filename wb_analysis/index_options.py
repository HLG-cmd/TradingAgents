# lifecycle: reusable
# created: 2026-10-21
"""指数与宽基 ETF 期权结构、波动率曲面与代理通道计算模块。

覆盖：
- ETF 期权链抓取、盘前盘后 CBOE 延迟报价自动适配
- ATM 隐含波动率、25-delta 偏斜（Skew）、期限结构（Term Structure & 局部驼峰事件定价）
- 报价新鲜度探针（`probe_option_freshness`）与持仓/成交量比（P/C Ratio）
- 决议日波动率与债券代理（VIX, VXN, TLT, IEF, SHY, ^TNX）
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

from wb_analysis._clock import market_date
from wb_analysis._thresholds import (
    HUMP_MIN_PP,
    MAX_QUOTE_AGE_DAYS,
    market_session_phase,
    option_source_decision,
)
from wb_analysis.index_math import _bs_delta, _bs_price, _implied_vol

__all__ = [
    "VOL_PROXIES",
    "BOND_PROXIES",
    "probe_option_freshness",
    "_source_label",
    "_iv_method_label",
    "_should_use_cboe_source",
    "_resolve_source_note",
    "fetch_option_structure",
    "fetch_volatility_proxies",
]

VOL_PROXIES = ("^VIX", "^VXN", "VIXY", "VXX", "UVXY")
BOND_PROXIES = ("TLT", "IEF", "SHY", "^TNX")

ETF_PROXY_DEFAULT = "QQQ"


def probe_option_freshness(etf: str = ETF_PROXY_DEFAULT) -> dict:
    """扫描该标的**全部**到期日的报价成交日，判断快照是否整体陈旧。"""
    import pandas as pd
    import yfinance as yf

    out = {"etf": etf, "expiries_checked": 0, "min_age_days": None,
           "n_fresh": 0, "n_quoted": 0, "stale": True, "ages_days": [],
           "in_session": None, "session_note": ""}

    try:
        import zoneinfo

        _now_ny = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        _phase = market_session_phase(_now_ny)
        out["session_phase"] = _phase
        out["in_session"] = (_phase == "in_session")
        if out["in_session"]:
            out["session_note"] = (f"采集时点 {_now_ny:%Y-%m-%d %H:%M} 美东，"
                                   f"处于常规交易时段，期权链应实时刷新")
        else:
            _label = {"pre_market": "盘前", "after_hours": "盘后",
                      "closed_day": "非交易日"}[_phase]
            out["session_note"] = (
                f"采集时点 {_now_ny:%Y-%m-%d %H:%M} 美东，处于**{_label}**——"
                f"yfinance 此时只返回上一交易日的残留快照（lastTradeDate 可能过时数周），"
                f"故**期权自动改走 CBOE 官方延迟报价**（上一时段收盘快照，非实时报价）。")
    except Exception:  # noqa: BLE001
        pass

    try:
        t = yf.Ticker(etf)
        exps = list(getattr(t, "options", None) or [])
        now = pd.Timestamp.now(tz="UTC")
        for exp in exps:
            if (dt.date.fromisoformat(exp) - market_date()).days <= 0:
                continue
            try:
                ch = t.option_chain(exp)
            except Exception:  # noqa: BLE001
                continue
            out["expiries_checked"] += 1
            for df in (ch.calls, ch.puts):
                d = df.copy()
                if "bid" not in d.columns or "ask" not in d.columns:
                    continue
                d["bid"] = pd.to_numeric(d["bid"], errors="coerce")
                d["ask"] = pd.to_numeric(d["ask"], errors="coerce")
                d = d[(d["bid"] > 0) & (d["ask"] > 0)]
                if d.empty or "lastTradeDate" not in d.columns:
                    continue
                ltd = pd.to_datetime(d["lastTradeDate"], errors="coerce", utc=True)
                ages = ((now - ltd).dt.total_seconds() / 86400.0).dropna()
                if ages.empty:
                    continue
                out["n_quoted"] += int(len(ages))
                out["ages_days"].extend([round(float(a), 1) for a in ages])
                mn = float(ages.min())
                if out["min_age_days"] is None or mn < out["min_age_days"]:
                    out["min_age_days"] = round(mn, 1)
        out["n_fresh"] = sum(1 for a in out["ages_days"] if a <= MAX_QUOTE_AGE_DAYS)
        out["stale"] = out["n_fresh"] == 0
        if out["ages_days"]:
            out["ages_days"] = sorted(out["ages_days"])[:60]
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _source_label(src: str | None) -> str:
    """期权来源标签（供证据包声明用）。未知来源如实标注，不美化。"""
    return {
        "yfinance": "yfinance（第三方聚合器，盘中实时刷新）",
        "cboe_delayed": "CBOE 官方延迟报价（`cdn.cboe.com/api/global/delayed_quotes/options/`，"
                        "免密钥，**15 分钟延迟**；非盘中时段提供**上一时段收盘快照**）",
    }.get((src or "").strip(), f"未标注（{src or '缺失'}）")


def _iv_method_label(src: str | None) -> str:
    """IV 计算方法标签（随来源变化）。"""
    return ("自建 Black-Scholes-Merton 反解"
            if (src or "").startswith("yfinance")
            else "交易所模型直出（CBOE 官方，无需反解）")


def _should_use_cboe_source() -> tuple[bool, str]:
    """判定是否该切到 CBOE（非盘中时段），返回 (是否切换, 说明)。"""
    try:
        return option_source_decision()
    except Exception:  # noqa: BLE001
        return False, "时点判定失败 ⇒ 保守用 yfinance 主源"


def _resolve_source_note(use_cboe: bool, cboe_ok: bool, session_note: str) -> str:
    """拼出「本次实际用了哪个源」的人读说明。"""
    if not use_cboe or cboe_ok:
        return session_note
    return (session_note
            + "｜⚠️ **但 CBOE 取数未成功，本轮回退 yfinance 主源**"
              "（该标的可能无可用期权，如指数符号 / A 股 ETF）")


def fetch_option_structure(etf: str = ETF_PROXY_DEFAULT) -> dict:
    """取 ETF 期权链，构建机构资金面指标 —— 填补「无期权/资金面证据」的缺口。"""
    import pandas as pd
    import yfinance as yf

    try:
        use_cboe, session_note = _should_use_cboe_source()
        t = None
        cboe_ok = False
        if use_cboe:
            try:
                from wb_analysis._option_source import fetch_chain
                t = fetch_chain(etf)
                exps = list(t.options or [])
                if not exps:
                    t = None
                else:
                    cboe_ok = True
            except Exception:  # noqa: BLE001
                t = None
        if t is None:
            t = yf.Ticker(etf)
        exps = list(getattr(t, "options", None) or [])
        if not exps:
            return {"error": "无期权链数据"}

        spot = None
        _cboe_spot = getattr(t, "spot", None)
        if _cboe_spot:
            spot = float(_cboe_spot)
        if not spot:
            try:
                spot = t.fast_info["lastPrice"]
            except Exception:  # noqa: BLE001
                pass
        if not spot:
            try:
                hist = t.history(period="5d")
                spot = float(hist["Close"].iloc[-1]) if len(hist) else None
            except Exception:  # noqa: BLE001
                pass
        if not spot:
            return {"error": "无法取得标的价格"}
        spot = float(spot)

        rate = 0.045
        try:
            tnx = yf.Ticker("^TNX").history(period="5d")
            if len(tnx):
                rate = float(tnx["Close"].iloc[-1]) / 100.0
        except Exception:  # noqa: BLE001
            pass
        rate = max(0.0, min(rate, 0.15))

        today = market_date()
        future = [e for e in exps if (dt.date.fromisoformat(e) - today).days > 0]
        if not future:
            return {"error": "无未到期期权"}

        div_yield = None
        div_note = None
        try:
            probe = max(future, key=lambda e: (dt.date.fromisoformat(e) - today).days)
            ttm_p = (dt.date.fromisoformat(probe) - today).days / 365.0
            chp = t.option_chain(probe)
            cm = chp.calls.copy()
            pm = chp.puts.copy()
            for d in (cm, pm):
                for c in ("bid", "ask", "strike"):
                    d[c] = pd.to_numeric(d[c], errors="coerce")
            cm = cm[(cm["bid"] > 0) & (cm["ask"] > 0)].copy()
            pm = pm[(pm["bid"] > 0) & (pm["ask"] > 0)].copy()
            for _df in (cm, pm):
                if "lastTradeDate" in _df.columns:
                    _ltd = pd.to_datetime(_df["lastTradeDate"], errors="coerce", utc=True)
                    _age = (pd.Timestamp.now(tz="UTC") - _ltd).dt.total_seconds() / 86400.0
                    _df.drop(_df.index[~(_age <= MAX_QUOTE_AGE_DAYS).fillna(False)],
                             inplace=True)
            if cm.empty or pm.empty:
                raise ValueError("平价反解无新鲜报价")
            cm["_cm"] = (cm["bid"] + cm["ask"]) / 2
            pm["_pm"] = (pm["bid"] + pm["ask"]) / 2
            j = cm.merge(pm, on="strike", suffixes=("_c", "_p"))
            qs = []
            for _, rr in j.iterrows():
                if abs(rr["strike"] / spot - 1) > 0.35:
                    continue
                fwd = rr["_cm"] - rr["_pm"] + rr["strike"] * math.exp(-rate * ttm_p)
                if fwd <= 0:
                    continue
                q = -math.log(fwd / spot) / ttm_p
                if -0.05 < q < 0.10:
                    qs.append(q)
            if qs:
                div_yield = round(float(statistics.median(qs)), 4)
                div_note = (
                    f"股息率由 **put-call parity 实测反解**（在 {probe} 到期日的 "
                    f"{len(qs)} 个同价配对样本上取中位数），**未使用 yfinance 的 "
                    "dividendYield 字段** —— 该字段口径自相矛盾（`dividendYield`=0.42、"
                    "`trailingAnnualDividendYield`=0.0025、"
                    "`trailingAnnualDividendRate`=1.77，三者最大相差约 168 倍）。"
                )
        except Exception:  # noqa: BLE001
            pass
        if div_yield is None:
            div_yield = 0.006
            div_note = ("⚠️ put-call parity 反解股息率失败，**采用兜底值 0.60%**。"
                        "该假设对近月 IV 影响可忽略，对 2 年期 LEAPS 有约 1~2pp 影响。")

        def _prep(df, exp: str, is_call: bool):
            if df is None or df.empty:
                return pd.DataFrame()
            d = df.copy()
            for col in ("bid", "ask", "strike"):
                if col not in d.columns:
                    return pd.DataFrame()
                d[col] = pd.to_numeric(d[col], errors="coerce")
            d = d[(d["bid"] > 0) & (d["ask"] > 0) & (d["ask"] >= d["bid"])].copy()
            if d.empty:
                return d

            if "lastTradeDate" in d.columns:
                ltd = pd.to_datetime(d["lastTradeDate"], errors="coerce", utc=True)
                age_days = (pd.Timestamp.now(tz="UTC") - ltd).dt.total_seconds() / 86400.0
                fresh = age_days <= MAX_QUOTE_AGE_DAYS
                d = d[fresh.fillna(False)].copy()
                if d.empty:
                    return d
            d["_mid"] = (d["bid"] + d["ask"]) / 2.0
            d["_spread"] = (d["ask"] - d["bid"]) / d["_mid"]
            d = d[d["_spread"] <= 0.30].copy()
            if d.empty:
                return d
            ttm = max((dt.date.fromisoformat(exp) - today).days, 1) / 365.0
            d["_mn"] = (d["strike"] / spot - 1) * 100
            d["_iv"] = [
                _implied_vol(m, spot, k, ttm, rate, div_yield, is_call)
                for m, k in zip(d["_mid"], d["strike"])
            ]
            d = d[d["_iv"].notna()].copy()
            if d.empty:
                return d
            d["_adelta"] = [
                abs(_bs_delta(spot, k, ttm, v, rate, div_yield, is_call))
                for k, v in zip(d["strike"], d["_iv"])
            ]
            return d

        def _pick_delta(d, lo: float, hi: float):
            if d is None or d.empty:
                return None, 0, None
            s = d[(d["_adelta"] >= lo) & (d["_adelta"] <= hi)]
            if s.empty:
                return None, 0, None
            return (round(float(s["_iv"].median()) * 100, 2), len(s),
                    round(float(s["_mn"].median()), 1))

        def _pick_mn(d, lo: float, hi: float):
            if d is None or d.empty:
                return None, 0
            s = d[(d["_mn"] >= lo) & (d["_mn"] <= hi)]
            if s.empty:
                return None, 0
            return round(float(s["_iv"].median()) * 100, 2), len(s)

        def _chain_profile(exp: str) -> dict:
            ch = t.option_chain(exp)
            c_raw, p_raw = ch.calls, ch.puts
            c = _prep(c_raw, exp, True)
            p = _prep(p_raw, exp, False)
            days = (dt.date.fromisoformat(exp) - today).days

            def _sum(df, col):
                if col not in df.columns:
                    return 0.0
                return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())

            c_oi, p_oi = _sum(c_raw, "openInterest"), _sum(p_raw, "openInterest")
            c_vol, p_vol = _sum(c_raw, "volume"), _sum(p_raw, "volume")

            skew_25d = None
            skew_n = (0, 0)
            skew_mn = (None, None)
            skew_band = None
            for lo, hi in ((0.20, 0.30), (0.15, 0.35), (0.10, 0.45)):
                pv, pn, pmn = _pick_delta(p, lo, hi)
                cv, cn, cmn = _pick_delta(c, lo, hi)
                if pv is not None and cv is not None:
                    skew_25d = round(pv - cv, 2)
                    skew_n = (pn, cn)
                    skew_mn = (pmn, cmn)
                    skew_band = f"|Δ|∈[{lo},{hi}]"
                    break

            otm_p, n_p = _pick_mn(p, -12.0, -8.0)
            otm_c, n_c = _pick_mn(c, 8.0, 12.0)
            skew_10pct = (round(otm_p - otm_c, 2)
                          if (otm_p is not None and otm_c is not None) else None)

            atm_c, n_atm_c, _ = _pick_delta(c, 0.40, 0.60)
            atm_p, n_atm_p, _ = _pick_delta(p, 0.40, 0.60)
            atm_basis = "delta" if (atm_c is not None or atm_p is not None) else None
            if atm_c is None:
                atm_c, n_atm_c = _pick_mn(c, -3.0, 3.0)
                atm_basis = atm_basis or "moneyness"
            if atm_p is None:
                atm_p, n_atm_p = _pick_mn(p, -3.0, 3.0)
                atm_basis = atm_basis or "moneyness"

            return {
                "expiry": exp,
                "days": days,
                "call_oi": int(c_oi),
                "put_oi": int(p_oi),
                "pc_oi": round(p_oi / c_oi, 3) if c_oi else None,
                "call_volume": int(c_vol),
                "put_volume": int(p_vol),
                "pc_volume": round(p_vol / c_vol, 3) if c_vol else None,
                "n_quoted_call": int(len(c)),
                "n_quoted_put": int(len(p)),
                "n_raw_call": int(len(c_raw)),
                "n_raw_put": int(len(p_raw)),
                "atm_call_iv": atm_c,
                "atm_put_iv": atm_p,
                "n_atm_call": n_atm_c,
                "n_atm_put": n_atm_p,
                "atm_basis": atm_basis,
                "otm_put_iv": otm_p,
                "otm_call_iv": otm_c,
                "n_otm_put": n_p,
                "n_otm_call": n_c,
                "skew_25d_pp": skew_25d,
                "skew_25d_band": skew_band,
                "n_skew_put": skew_n[0],
                "n_skew_call": skew_n[1],
                "skew_25d_mn": skew_mn[0],
                "skew_25d_call_mn": skew_mn[1],
                "skew_10pct_pp": skew_10pct,
                "skew_pp": skew_25d if skew_25d is not None else skew_10pct,
                "skew_basis": ("25delta" if skew_25d is not None
                               else ("10pct" if skew_10pct is not None else None)),
            }

        profiles: list[dict] = []
        for e in future:
            try:
                profiles.append(_chain_profile(e))
            except Exception:  # noqa: BLE001
                continue
        if not profiles:
            return {"error": "全部到期日均无法读取期权链"}

        def _grade_of(r: dict) -> str | None:
            has_atm = r["atm_call_iv"] is not None and r["atm_put_iv"] is not None
            has_skew = r["skew_25d_pp"] is not None
            if has_atm and has_skew:
                return "FULL"
            if has_skew:
                return "SKEW_ONLY"
            if has_atm:
                return "ATM_ONLY"
            if r["n_quoted_put"] >= 3 and r["n_quoted_call"] >= 3:
                return "PARTIAL_2SIDE"
            if r["n_quoted_put"] >= 3 or r["n_quoted_call"] >= 3:
                return "PARTIAL"
            return None

        TARGETS = (14, 35, 95)
        picked_rows: list[dict] = []
        grade = None
        for want in ("FULL", "SKEW_ONLY", "ATM_ONLY", "PARTIAL_2SIDE", "PARTIAL"):
            cands = [r for r in profiles if _grade_of(r) == want]
            if not cands:
                continue
            grade = want
            cands.sort(key=lambda r: min(abs(r["days"] - tg) for tg in TARGETS))
            picked_rows = cands[:3]
            break

        used_fallback = False
        fallback_note = None
        if not picked_rows:
            grade = "NONE"
            picked_rows = sorted(profiles, key=lambda r: -(r["n_quoted_call"] +
                                                           r["n_quoted_put"]))[:1]

        near_hit = any(r["days"] <= 120 for r in picked_rows)
        if grade not in (None, "NONE") and not near_hit:
            used_fallback = True
            fallback_note = (
                "目标近月（14/35/95 天）**均无足够有效报价**，已回退到 "
                + "、".join(f"{r['expiry']}（{r['days']} 天）" for r in picked_rows)
                + f"。以上是全部 {len(future)} 个未来到期日中质量最高的。"
                "⚠️ **长天期读数不能代表近月情绪** —— 期限越长，尾部定价占比越高、"
                "对短期事件敏感度越低。"
            )

        ivs = [r[k] for r in picked_rows
               for k in ("atm_call_iv", "atm_put_iv", "otm_put_iv", "otm_call_iv")
               if r.get(k) is not None]
        iv_sane = len(ivs) >= 2 and min(ivs) >= 5.0
        if not iv_sane:
            for r in picked_rows:
                for k in ("atm_call_iv", "atm_put_iv", "otm_put_iv", "otm_call_iv",
                          "skew_pp", "skew_25d_pp", "skew_10pct_pp"):
                    r[k] = None
            grade = "NONE"

        term = None
        atm_rows = [r for r in profiles
                    if r["atm_put_iv"] is not None and r["atm_call_iv"] is not None]
        if len(atm_rows) >= 2:
            atm_rows.sort(key=lambda r: r["days"])
            near, far = atm_rows[0], atm_rows[-1]
            near_iv = round((near["atm_put_iv"] + near["atm_call_iv"]) / 2, 2)
            far_iv = round((far["atm_put_iv"] + far["atm_call_iv"]) / 2, 2)
            _series = [{"expiry": r["expiry"], "days": r["days"],
                        "atm_iv": round((r["atm_put_iv"] + r["atm_call_iv"]) / 2, 2)}
                       for r in atm_rows]
            hump = None
            for i in range(1, len(_series) - 1):
                cur, lo_, hi_ = _series[i], _series[i - 1], _series[i + 1]
                if (cur["atm_iv"] - lo_["atm_iv"] >= HUMP_MIN_PP
                        and cur["atm_iv"] - hi_["atm_iv"] >= HUMP_MIN_PP):
                    hump = {"expiry": cur["expiry"], "days": cur["days"], "atm_iv": cur["atm_iv"],
                            "excess_pp": round(min(cur["atm_iv"] - lo_["atm_iv"],
                                                   cur["atm_iv"] - hi_["atm_iv"]), 2),
                            "window_from": lo_["expiry"], "window_to": hi_["expiry"]}
                    break
            term = {
                "near_expiry": near["expiry"], "near_days": near["days"],
                "near_atm_iv": near_iv,
                "far_expiry": far["expiry"], "far_days": far["days"],
                "far_atm_iv": far_iv,
                "slope_pp": round(near_iv - far_iv, 2),
                "contango": near_iv < far_iv,
                "atm_series": _series,
                "hump": hump,
            }

        put_skew_ratio = None
        for r in picked_rows:
            if r["otm_put_iv"] is not None and r["atm_put_iv"]:
                put_skew_ratio = round(r["otm_put_iv"] / r["atm_put_iv"], 3)
                break

        oi_note = None
        if picked_rows:
            tot_call_oi = sum(r["call_oi"] for r in picked_rows)
            tot_call_vol = sum(r["call_volume"] for r in picked_rows)
            if tot_call_vol > 0 and tot_call_oi * 100 < tot_call_vol:
                oi_note = (
                    f"OI 与成交量量级严重不符（CallOI 合计 {tot_call_oi:,} vs "
                    f"CallVol 合计 {tot_call_vol:,}，成交量是 OI 的 "
                    f"{tot_call_vol / max(tot_call_oi, 1):.0f} 倍）。"
                    "疑似 yfinance 在不同调用间返回不同口径的 OI。"
                    "**P/C(OI) 与任何持仓结构结论不可引用**；P/C(Vol) 口径不受影响。"
                )
                for r in picked_rows:
                    r["pc_oi"] = None
                    r["oi_unreliable"] = True

        if cboe_ok:
            freshness = {
                "etf": etf, "expiries_checked": len(future), "min_age_days": None,
                "n_fresh": None, "n_quoted": None, "stale": False,
                "ages_days": [], "in_session": False, "session_note": session_note,
                "source": "cboe_delayed",
                "skipped_reason": "已切 CBOE 源，跳过 yfinance 口径的新鲜度探测",
            }
        else:
            freshness = probe_option_freshness(etf)
            if use_cboe:
                freshness["cboe_fallback_failed"] = True
                freshness["session_note"] = (
                    f"{session_note}｜⚠️ **但 CBOE 取数未成功，本轮回退 yfinance 主源**"
                    f"（该标的可能无可用期权，如指数符号 / A 股 ETF）"
                )
        stale_note = None
        if freshness.get("stale"):
            stale_note = (
                f"**本次期权快照整体陈旧 ⇒ 全部 IV / 偏斜 / P-C 结论不可引用。**"
                f"扫描 {freshness.get('expiries_checked')} 个未来到期日，"
                f"共 {freshness.get('n_quoted')} 个有双边报价的合约，"
                f"其中**最新一笔成交距今仍有 {freshness.get('min_age_days')} 天**，"
                f"合格（≤{MAX_QUOTE_AGE_DAYS} 天）样本数 = 0。"
                f"**根因是采集时点，不是数据源缺陷**："
                f"{freshness.get('session_note') or ''}"
                " 期权链只在美东 09:30–16:00 实时刷新，盘前/盘后/休市拿到的是"
                "上一交易日的残留挂单。**解决办法是改到美东盘中重采，"
                "而不是把「该源不可用」写成结论。**"
                "本次 IV / 偏斜 / P/C 维度客观上不可得，报告须显式声明缺口。"
            )

        return {
            "etf": etf, "spot": round(spot, 2),
            "source": ("cboe_delayed" if cboe_ok else "yfinance"),
            "source_note": _resolve_source_note(use_cboe, cboe_ok, session_note),
            "rate_used": round(rate, 4), "div_yield_used": div_yield,
            "div_note": div_note,
            "freshness": freshness,
            "stale_note": stale_note,
            "by_expiry": picked_rows,
            "n_expiries_scanned": len(profiles),
            "n_expiries_total": len(future),
            "iv_available": bool(iv_sane and grade != "NONE"),
            "iv_grade": grade,
            "atm_available": bool(iv_sane and any(
                r["atm_call_iv"] is not None and r["atm_put_iv"] is not None
                for r in picked_rows)),
            "skew_available": bool(iv_sane and any(
                r["skew_25d_pp"] is not None for r in picked_rows)),
            "skew_basis": next((r["skew_basis"] for r in picked_rows
                                if r["skew_basis"]), None),
            "one_sided_put_iv": next((r["otm_put_iv"] for r in picked_rows
                                      if r["otm_put_iv"] is not None), None),
            "put_skew_ratio": put_skew_ratio,
            "term_structure": term,
            "oi_note": oi_note,
            "used_fallback": used_fallback, "fallback_note": fallback_note,
            "iv_note": None if (iv_sane and grade != "NONE") else (
                "无有效双边报价，或自解 IV 落在垃圾区间，已屏蔽全部 IV/偏斜字段。"
            ),
            "quote_age_filter_days": MAX_QUOTE_AGE_DAYS,
            "all_expiry_scan": [
                {"expiry": r["expiry"], "days": r["days"],
                 "n_quoted_call": r["n_quoted_call"],
                 "n_quoted_put": r["n_quoted_put"],
                 "grade": _grade_of(r)}
                for r in sorted(profiles, key=lambda x: x["days"])
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def fetch_volatility_proxies(as_of: str, days: int = 8) -> dict:
    """取 VIX/VXN 及其 ETF 代理、以及债券 ETF 的**日线 OHLC 区间**。"""
    import yfinance as yf

    out: dict = {"proxies": [], "notes": []}
    tickers = list(VOL_PROXIES) + list(BOND_PROXIES)
    for tkr in tickers:
        try:
            h = yf.Ticker(tkr).history(period=f"{days}d")
            if h.empty:
                out["notes"].append(f"{tkr}: 无数据")
                continue
            rows = []
            for idx, r in h.tail(days).iterrows():
                rows.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": round(float(r["Open"]), 2) if r["Open"] == r["Open"] else None,
                    "high": round(float(r["High"]), 2) if r["High"] == r["High"] else None,
                    "low": round(float(r["Low"]), 2) if r["Low"] == r["Low"] else None,
                    "close": round(float(r["Close"]), 2) if r["Close"] == r["Close"] else None,
                    "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else None,
                })
            out["proxies"].append({"ticker": tkr, "bars": rows,
                                   "last_date": rows[-1]["date"] if rows else None})
        except Exception as exc:  # noqa: BLE001
            out["notes"].append(f"{tkr}: {type(exc).__name__}: {exc}")

    for p in out["proxies"]:
        for b in p["bars"]:
            if b.get("high") and b.get("low") and b.get("low") > 0:
                b["intraday_range_pct"] = round((b["high"] - b["low"]) / b["low"] * 100, 2)
                if p["ticker"] == "^TNX":
                    b["range_bp"] = round((b["high"] - b["low"]) * 100, 1)
            if b.get("high") and b.get("close"):
                b["close_vs_high_pct"] = round((b["close"] - b["high"]) / b["high"] * 100, 2)

    out["as_of_bar"] = as_of
    return out
