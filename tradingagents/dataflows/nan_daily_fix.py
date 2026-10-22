# lifecycle: reusable
# created: 2026-10-22
# usage: from tradingagents.dataflows.nan_daily_fix import agg_1m_daily, patch_nan_ohlcv
"""日线 NaN 行的 1 分钟聚合补救。

## 背景（2026-10-22 实测）

yfinance 日线聚合对 **2026-10-21**（最新已完成交易日）全天返回 NaN OHLC：
AAPL / MSFT / SPY / ^GSPC / ^NDX / QQQ 全部中招，且 `Ticker.history` 与
`yf.download` 两条路径一致；同日期权链与 1 分钟 bar 完好。特征是
**OHLC 四列全 NaN、仅剩 Volume 一列有值**（且该成交量本身也不可信）。

若不补救，下游会把「最新收盘」静默回退成 10-20（`dropna` 之后），
即**用陈旧一个交易日的价格冒充最新价** —— 典型静默降级（铁律 3）。

## 补救口径（必须随数据一起声明）

用**同日 1 分钟 bar** 聚合成日线一行：

  · 股票 / 指数 / 收益率指数：常规时段 **09:30–16:00 美东**，
    O=首根开、H=max、L=min、C=末根收、V=Σ1分钟量
  · 期货（代码以 `=F` 结尾）：近乎 23 小时连续交易，取**当日全部** 1 分钟 bar
    聚合（O=首根、C=当日最后一根）

补不动的日期**保留 NaN**，绝不编造。每次补救都返回 notes，由调用方写进
证据包 / CSV 头，保证口径可查。
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

__all__ = ["agg_1m_daily", "patch_nan_ohlcv", "patch_download_nan", "REGULAR_SESSION"]

#: 美东常规交易时段（美股股票 / 指数 / 收益率指数的日线口径）
REGULAR_SESSION = ("09:30", "16:00")

#: 单次补救最多回溯几天（防止上游大面积 NaN 时请求风暴）
MAX_PATCH_DAYS = 3


def _is_futures(canonical: str) -> bool:
    return str(canonical).strip().endswith("=F")


def agg_1m_daily(canonical: str, date_str: str) -> dict | None:
    """把某标的某日的 1 分钟 bar 聚合成日线一行；失败返回 None（不编造）。"""
    import yfinance as yf

    canonical = str(canonical).strip()
    try:
        d = dt.date.fromisoformat(date_str)
    except ValueError:
        return None
    try:
        h = yf.Ticker(canonical).history(
            start=date_str, end=(d + dt.timedelta(days=1)).isoformat(),
            interval="1m", auto_adjust=False)
    except Exception:  # noqa: BLE001 — 限流/网络异常都按「补不动」处理
        return None
    if h is None or getattr(h, "empty", True):
        return None

    idx = h.index
    if getattr(idx, "tz", None) is not None:
        h = h.copy()
        h.index = h.index.tz_convert("America/New_York")
        if not _is_futures(canonical):
            h = h.between_time(*REGULAR_SESSION)
    if h.empty:
        return None
    try:
        row = {
            "Open": float(h["Open"].iloc[0]),
            "High": float(h["High"].max()),
            "Low": float(h["Low"].min()),
            "Close": float(h["Close"].iloc[-1]),
        }
        if "Volume" in h.columns:
            v = pd.to_numeric(h["Volume"], errors="coerce").fillna(0).sum()
            row["Volume"] = int(v) if v == v else None
    except Exception:  # noqa: BLE001
        return None
    return row


def _date_of(v) -> str | None:
    """从索引值 / Date 列值取 YYYY-MM-DD。"""
    try:
        ts = pd.Timestamp(v)
    except Exception:  # noqa: BLE001
        return None
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _nan_dates(df: pd.DataFrame) -> list[str]:
    """DataFrame 中 Close 为 NaN 的日期（新→旧，最多 MAX_PATCH_DAYS 个）。"""
    if "Close" not in df.columns:
        return []
    close = pd.to_numeric(df["Close"], errors="coerce")
    bad = close.isna()
    if not bad.any():
        return []
    if isinstance(df.index, pd.DatetimeIndex):
        dates = [_date_of(v) for v in df.index[bad]]
    elif "Date" in df.columns:
        dates = [_date_of(v) for v in df.loc[bad, "Date"]]
    else:
        return []
    out = [d for d in dates if d]
    out = sorted(set(out), reverse=True)[:MAX_PATCH_DAYS]
    return out


def patch_nan_ohlcv(df: pd.DataFrame, canonical: str) -> tuple[pd.DataFrame, list[str]]:
    """补齐日线中 Close 为 NaN 的行。支持 DatetimeIndex 与 'Date' 列两种形态，原形态返回。

    只补**美东今天之前**的日期（当天未收盘的 bar 由调用方的未收盘逻辑处理，
    不在此处臆造）。返回 (df, notes)；无 NaN 时原样返回。
    """
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
        return df, []

    today_et = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")
    notes: list[str] = []
    patched: list[str] = []
    fut = _is_futures(canonical)
    calib = ("当日全部 1 分钟 bar（期货近乎 23 小时交易）" if fut
             else "常规时段 09:30–16:00 美东 1 分钟 bar 聚合")
    for d in _nan_dates(df):
        if d >= today_et:
            continue  # 当天未收盘：不是补救范围
        row = agg_1m_daily(canonical, d)
        if not row:
            continue
        mask = None
        if isinstance(df.index, pd.DatetimeIndex):
            mask = (df.index.strftime("%Y-%m-%d") == d)
        elif "Date" in df.columns:
            mask = (pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d") == d)
        if mask is None or not mask.any():
            continue
        for col in ("Open", "High", "Low", "Close", "Volume"):
            if col in df.columns and row.get(col) is not None:
                df.loc[mask, col] = row[col]
        patched.append(d)

    # 缺失整行检查（上游 yfinance 偶发整行漏掉而非置 NaN，如 2026-10-21 实测）
    existing_dates: set[str] = set()
    if isinstance(df.index, pd.DatetimeIndex):
        existing_dates = set(df.index.strftime("%Y-%m-%d"))
    elif "Date" in df.columns:
        existing_dates = set(pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d").dropna())

    today_dt = pd.Timestamp.now(tz="America/New_York").date()
    missing_patched: list[str] = []
    for i in range(1, 6):
        cand = today_dt - dt.timedelta(days=i)
        if not fut and cand.weekday() >= 5:
            continue
        c_str = cand.strftime("%Y-%m-%d")
        if c_str not in existing_dates:
            row = agg_1m_daily(canonical, c_str)
            if row and row.get("Close") is not None:
                if isinstance(df.index, pd.DatetimeIndex):
                    ts = pd.Timestamp(c_str).tz_localize(df.index.tz) if getattr(df.index, "tz", None) is not None else pd.Timestamp(c_str)
                    new_df = pd.DataFrame([row], index=[ts])
                    for col in df.columns:
                        if col not in new_df.columns:
                            new_df[col] = 0.0
                    df = pd.concat([df, new_df]).sort_index()
                elif "Date" in df.columns:
                    row_dict = dict(row)
                    row_dict["Date"] = c_str
                    new_df = pd.DataFrame([row_dict])
                    df = pd.concat([df, new_df], ignore_index=True)
                    df = df.sort_values(by="Date").reset_index(drop=True)
                missing_patched.append(c_str)
                existing_dates.add(c_str)

    if patched:
        notes.append(
            f"{canonical} 日线 OHLC 全 NaN 的日期 {', '.join(patched)} 已用同日 1 分钟 bar "
            f"聚合补齐（口径：{calib}；yfinance 日线聚合当日异常，非本项目编造）"
        )
    if missing_patched:
        notes.append(
            f"{canonical} 缺失整行日线的日期 {', '.join(sorted(missing_patched))} 已用同日 1 分钟 bar "
            f"聚合补齐（口径：{calib}；yfinance 日线聚合当日漏行，非本项目编造）"
        )
    return df, notes


def _agg_multi_1m(tickers: list[str], date_str: str) -> dict[str, dict]:
    """一次多代码 1 分钟请求聚合整批（breadth 补救用，避免 N 次单独请求触发限流）。"""
    import yfinance as yf

    out: dict[str, dict] = {}
    try:
        d = dt.date.fromisoformat(date_str)
        df = yf.download(list(tickers), start=date_str,
                         end=(d + dt.timedelta(days=1)).isoformat(),
                         interval="1m", progress=False, threads=False,
                         auto_adjust=False)
    except Exception:  # noqa: BLE001
        return out
    if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
        return out
    close = df["Close"]
    for tkr in tickers:
        if tkr not in close.columns:
            continue
        sub = df.xs(tkr, axis=1, level=1) if isinstance(df.columns, pd.MultiIndex) else None
        if sub is None or sub.empty:
            continue
        try:
            o = float(sub["Open"].iloc[0])
            hi = float(sub["High"].max())
            lo = float(sub["Low"].min())
            cl = float(sub["Close"].iloc[-1])
            vol = sub["Volume"].sum() if "Volume" in sub.columns else None
        except Exception:  # noqa: BLE001
            continue
        if any(v != v for v in (o, hi, lo, cl)):
            continue
        out[tkr] = {"Open": o, "High": hi, "Low": lo, "Close": cl,
                    "Volume": int(vol) if vol == vol else None}
    return out


def patch_download_nan(df: pd.DataFrame, tickers: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """修补 `yf.download` 多代码结果（MultiIndex 列 (字段, 代码)）里的 NaN 收盘。

    breadth 通道专用：yf.download 与 Ticker.history 走同一上游，NaN 形态一致。

    实现要点：`df.get(field)` 返回的是**副本切片**，在切片上 `loc` 赋值
    **不会写回父帧**（静默假绿：notes 说补齐、数据仍是 NaN）。因此这里
    先在父帧上定位所有 NaN 日期，按日期一次性批量 1 分钟聚合，最后统一
    `df.loc[mask, (field, tkr)] = 值` 写回父帧本体。
    """
    if df is None or getattr(df, "empty", True):
        return df, []
    if not isinstance(df.columns, pd.MultiIndex):
        return df, []  # 单代码帧走 patch_nan_ohlcv
    close = df["Close"] if ("Close" in df.columns.get_level_values(0)) else None
    if close is None:
        return df, []

    today_et = pd.Timestamp.now(tz="America/New_York").strftime("%Y-%m-%d")

    # 第一遍：收集 (日期 → 需要补的代码)，不碰数据
    need: dict[str, list[str]] = {}
    for tkr in tickers:
        if tkr not in close.columns:
            continue
        s = pd.to_numeric(close[tkr], errors="coerce")
        for d in s[s.isna()].index.strftime("%Y-%m-%d"):
            if d < today_et:  # 当天未收盘不是补救范围
                need.setdefault(d, []).append(tkr)

    # 第二遍：每个日期一次批量 1 分钟请求（避免 N×M 请求触发限流）
    notes: list[str] = []
    patched: list[tuple[str, str]] = []
    for d in sorted(need, reverse=True)[:MAX_PATCH_DAYS]:
        batch = _agg_multi_1m(need[d], d)
        for tkr in need[d]:
            row = batch.get(tkr) or agg_1m_daily(tkr, d)
            if not row:
                continue
            mask = df.index.strftime("%Y-%m-%d") == d
            if not mask.any():
                continue
            for field in ("Open", "High", "Low", "Close", "Volume"):
                if (field in df.columns.get_level_values(0)
                        and (field, tkr) in df.columns
                        and row.get(field) is not None):
                    df.loc[mask, (field, tkr)] = row[field]  # 写回父帧本体
            patched.append((tkr, d))

    for tkr, d in patched:
        notes.append(f"{tkr} {d} 日线 NaN 已用 1 分钟 bar 聚合补齐（口径同单代码补救）")
    return df, notes
