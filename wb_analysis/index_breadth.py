# lifecycle: reusable
# created: 2026-10-21
"""指数成分股市场宽度（Market Breadth）计算模块。

负责分块拉取成分股 1 年日线，计算：
- 站上 50 日 / 200 日均线比例（50SMA / 200SMA Breadth）
- 20日 / 60日 / 120日 动量分布与中位数
- 等权收益与离散度
"""
from __future__ import annotations

import time

__all__ = ["_download_close_chunked", "compute_breadth"]


def _download_close_chunked(tickers: list[str], period: str = "1y",
                            chunk: int = 20, retries: int = 2):
    """分块下载成分股收盘价矩阵，对失败代码做整轮重试。

    **为什么不能一次性传 101 个代码**：实测（2026-09-16）单次 ``yf.download`` 传全量
    101 只时，会稳定出现约 27 只返回 ``possibly delisted; no price data found``——
    其中包含 AAPL / AMZN / COST 这类不可能退市的代码，实为**批量请求限流**。
    后果是广度样本从 95 只缩到 70~72 只（覆盖率约 70%），且因样本变小而波动
    （同一份数据两次采集得出 52.9% 与 55.6% 两个不同的 200SMA 覆盖率）。

    改为每批 20 只、失败代码整轮重试 2 次，覆盖率可接近全量，结果可复现。

    返回 ``None`` 表示全部失败。
    """
    import pandas as pd
    import yfinance as yf

    frames: list = []
    pending = list(tickers)
    for _ in range(retries + 1):
        if not pending:
            break
        failed: list[str] = []
        for i in range(0, len(pending), chunk):
            batch = pending[i: i + chunk]
            try:
                data = yf.download(batch, period=period, progress=False,
                                   auto_adjust=False, threads=False)
            except Exception:  # noqa: BLE001
                failed.extend(batch)
                continue
            if data is None or getattr(data, "empty", True):
                failed.extend(batch)
                continue
            try:
                c = data["Close"]
            except Exception:  # noqa: BLE001
                failed.extend(batch)
                continue
            if isinstance(c, pd.Series):
                c = c.to_frame(name=batch[0])
            got = [t for t in batch if t in c.columns and c[t].notna().any()]
            if got:
                frames.append(c[got])
            failed.extend(t for t in batch if t not in got)
        pending = failed
        if pending:
            time.sleep(1.0)

    if not frames:
        return None
    close = pd.concat(frames, axis=1)
    return close.loc[:, ~close.columns.duplicated()]


def compute_breadth(tickers: list[str]) -> dict:
    """用成分股 1 年日线计算广度指标与等权/加权背离。"""
    import pandas as pd

    close = _download_close_chunked(tickers)
    if close is None:
        return {"error": "成分股价格下载全部失败"}

    recs = []
    for tk in tickers:
        if tk not in close.columns:
            continue
        c = close[tk].dropna()
        if len(c) < 180:
            continue
        last = float(c.iloc[-1])
        sma50 = float(c.rolling(50).mean().iloc[-1])
        sma200 = float(c.rolling(200).mean().iloc[-1])
        recs.append(
            {
                "ticker": tk,
                "last": last,
                "above_200": last > sma200,
                "above_50": last > sma50,
                "ret20": (last / float(c.iloc[-21]) - 1) * 100 if len(c) > 21 else None,
                "ret60": (last / float(c.iloc[-61]) - 1) * 100 if len(c) > 61 else None,
                "ret120": (last / float(c.iloc[-121]) - 1) * 100 if len(c) > 121 else None,
            }
        )

    if not recs:
        return {"error": "无有效成分股价格数据"}

    df = pd.DataFrame(recs)
    n = len(df)

    def _pct(series) -> float:
        return round(float(series.mean()) * 100, 1)

    return {
        "n_universe": len(tickers),
        "n_valid": n,
        "pct_above_200sma": _pct(df["above_200"]),
        "pct_above_50sma": _pct(df["above_50"]),
        "pct_up_20d": _pct(df["ret20"] > 0),
        "pct_up_60d": _pct(df["ret60"] > 0),
        "pct_up_120d": _pct(df["ret120"] > 0),
        "median_ret20": round(float(df["ret20"].median()), 2),
        "median_ret60": round(float(df["ret60"].median()), 2),
        "equal_weight_ret20": round(float(df["ret20"].mean()), 2),
        "equal_weight_ret60": round(float(df["ret60"].mean()), 2),
        "dispersion_ret20": round(float(df["ret20"].std()), 2),
        "candidates": df.to_dict(orient="records"),
    }
