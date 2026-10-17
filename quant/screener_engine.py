# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/screener_engine.py
"""多因子量化选股雷达引擎 (Multi-Factor GARP Screener Engine)

四维 GARP 体系（2026-10-02 起趋势档降为残差 5%，理由见 FACTOR_WEIGHTS 上方注释）：
    质量 35%  ROE + 净利率 + 低负债
    估值 30%  PE 截面百分位（越便宜分越高）
    成长 30%  营收同比增速截面百分位
    趋势  5%  60日动量 + 均线形态 + RSI 区间（**曾占 20%，311 期实测 IC≈0**）

════════════════════════════════════════════════════════════════════════
数据层改用上游 load_ohlcv（2026-09-16 重构）
════════════════════════════════════════════════════════════════════════
不再使用 ``yf.download(tickers, ...)`` 一次性批量接口。实测（97 只标的）：

    策略                          可用      失败率     耗时
    A 一次性批量 + 多线程(原做法)   73/97     24.7%     14.2s
    B 一次性批量 + 单线程           96/97      1.0%     37.1s
    C 分块(10只) + 多线程           89/97      8.2%     25.9s
    D 逐票 history + 并发 5         96/97      1.0%      3.5s

失败原因是 **Yahoo 对高并发批量请求限流**，不是网络不通（单线程即可 99% 成功，
且失败标的单独拉取 23/24 完全正常）。原做法丢弃的恰是 NVDA/AAPL/AMZN 等超大市值票，
且失败随机——同一批重跑失败数在 24~51 之间波动，导致榜单不可复现。

现改用 ``tradingagents.dataflows.stockstats_utils.load_ohlcv``，它已具备：
  - 按票文件缓存（5 年窗口，投毒缓存防护）
  - ``yf_retry`` 指数退避重试（专治 HTTP 429 限流）
  - 陈旧数据检测（返回精确原因，而非误导性的 "possibly delisted"）
  - 防前视偏差（按 curr_date 截断）
并在此基础上加：受限并发(5) + 失败补拉一轮。
"""

from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import datetime as dt
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from tradingagents.dataflows.stockstats_utils import load_ohlcv
from tradingagents.dataflows.symbol_utils import NoMarketDataError

CACHE_DIR = Path(os.path.expanduser("~")) / ".tradingagents" / "cache"

# ⚠️ 缓存 schema 版本。**改动缓存 payload 的结构（增删 metadata 字段等）时必须 +1**，
#    否则当天已存在的缓存会以旧结构被读回，下游按新结构取值就会 KeyError。
#    读取时版本不匹配一律视为未命中并重新拉取，宁可多花一次数据成本。
CACHE_SCHEMA_VERSION = 2

# 实测最优并发度：5 路既在 Yahoo 限流阈值内，又比单线程快 10 倍
MAX_WORKERS = 5
# 失败标的补拉轮数。实测首轮约 7% 会被 yfinance 静默返回空帧（限流），
# 补拉一轮可救回其中约 86%；补拉用更低并发(2)，给两轮余量。
RETRY_PASSES = 2
# 计算技术指标所需的最少 K 线根数
MIN_BARS = 60

# ══════════════════════════════════════════════════════════════════════
# 因子权重（集中在此处，便于再校准 —— 不要散落在打分函数里）
# ══════════════════════════════════════════════════════════════════════
# ⚠️ 这些是**经验取值，会随市场状态衰减**，不是不变量。
#    请把这份权重当作「待监测的参数」，而非「已确定的真理」。
#    再校准时改这里即可，无需改动打分逻辑。
#
# ── 2026-10-02：趋势档 0.20 → 0.05（这是**收缩**，不是删除）──
#   依据：factor_backtest.py --watch 把样本由 49 期扩到 **311 期**
#   （2000-10 ~ 2026-08，26 年、101 只纳指100 成分），趋势档 IC=−0.0009 / t=−0.08，
#   IC 的标准误约 0.005 ⇒ 95% 置信区间约 [−0.011, +0.009]。
#   这**不是**「样本太小测不出来」，而是**被足够精确地测出的零** —— 可以排除
#   任何有经济意义的 IC。零 IC 因子在综合分里只贡献方差，故压到残差 0.05
#   （保留一点动量暴露，不做归零这种更激进的断言）。
#
#   ⇒ 此前「49 期统计功效不足，故不动默认权重」的**前提已被推翻**，故改默认。
#     原立场保留在 git 历史与本目录 WEIGHT_PROFILES 的说明里。
#
#   ⚠️ 本次**不是**用近期窗口反拟合：近期窗口的 trend IC 反而是**正的**
#      （近 12 期 +0.0096），按近期拟合应该**加**权。判据取自 26 年全样本。
#      任何后续再校准同样**不得**用「最近 N 期」反推（那是过拟合）。
#
#   ⚠️ 这**不**等于其余三档有效：quality / value / growth 仍只有 17 个不重叠
#      年度观测，t ≈ −0.5 ~ −1.1，置信区间宽到无法排除任何方向。四档**全都**
#      不显著（见 FACTOR_VALIDATION）。本次只降「唯一被足够精确测成零」的那一档。
FACTOR_WEIGHTS = {
    "quality": 0.35,   # ROE 40% + 净利率 40% + 低负债 20%
    "value":   0.30,   # PE 截面百分位
    "growth":  0.30,   # 营收同比增速百分位
    "trend":   0.05,   # 动量 60% + 均线 25% + RSI 15%（311 期实测 IC≈0 ⇒ 压到残差）
}
# 趋势档内部的子权重
TREND_SUB_WEIGHTS = {"mom60": 0.60, "ma": 0.25, "rsi": 0.15}
# 质量档内部的子权重
QUALITY_SUB_WEIGHTS = {"roe": 0.40, "margin": 0.40, "low_debt": 0.20}

# ══════════════════════════════════════════════════════════════════════
# 权重档案（预设）
# ══════════════════════════════════════════════════════════════════════
# 用法：run_quant_screening(tickers, weights=WEIGHT_PROFILES["no_trend"])
#
# ── 2026-10-02 变更：默认档由 garp（趋势 20%）改为 quality（趋势 5%）──
#   2026-09 的立场是「**不**默改 garp」，理由是「49 期样本统计功效不足，
#   拿一次不显著的测量去改默认权重正是回测警告过的过拟合陷阱」。**那个立场
#   在当时是对的**，不需要否定它 —— 但它自带失效条件：结论依赖「样本测不出」。
#   样本扩到 311 期 / 26 年后，趋势档 IC 的 95% CI 收到约 ±0.01，
#   前提由「测不出」变为「测出了零」，故改默认。原文见 git 历史。
#
#   ⚠️ 反过拟合的纪律**没有**放松：本次判据是 26 年全样本，不是近期窗口
#      （近期窗口 trend IC 反而是正的 +0.0096，按近期拟合会**加**权）。
#      无论谁再调这里，都不许用「最近 N 期」反推权重。
WEIGHT_PROFILES = {
    # ★ 现默认（= FACTOR_WEIGHTS）：趋势档压到残差。理由见 FACTOR_WEIGHTS 上方注释。
    "quality": {"quality": 0.35, "value": 0.30, "growth": 0.30, "trend": 0.05},
    # 旧默认（2026-09 及之前）：四维均衡、趋势 20%。
    # **已被 311 期证据降级**，保留作对照与一键回退：weights=WEIGHT_PROFILES["garp"]
    "garp": {"quality": 0.30, "value": 0.25, "growth": 0.25, "trend": 0.20},
    # 只依赖基本面：趋势档完全停用。适合「不想要任何动量暴露」的场景
    "no_trend": {"quality": 0.35, "value": 0.35, "growth": 0.30, "trend": 0.00},
}

# ══════════════════════════════════════════════════════════════════════
# 因子验证状态（诚实标注：回测说了什么）
# ══════════════════════════════════════════════════════════════════════
# **这不是装饰** —— 它决定了你该多大程度相信榜单。
#
# ⚠️ 2026-09-20 修正：此前这里把 quality / value / growth 标为 ``validated: False``，
#    理由是「时点基本面不可得，无法重建回测」。**那个理由是过时的** ——
#    `edgar_fundamentals.py` 提供带 ``filed`` 时点键的 XBRL 历史，
#    `fundamental_backtest.py` 已经能把四个因子都回测出来。三个因子不是「无法验证」，
#    而是「**已验证，且不显著**」—— 这是强得多、也更该被知道的结论。
#    旧措辞会让程序输出「80% 权重未经验证」，听起来像「还有救」，实际是「已验证无效」。
#
# 数据来源与口径（改这里之前先读）：
#   · 基本面三档：SEC EDGAR 时点基本面，2009-01 ~ 2025-01，
#     **17 个不重叠年度观测**（前瞻 252 日 = 调仓 252 日）、行业中性化。
#     两个宇宙都跑了，结论一致：纳指100（84 只截面）与标普500（436 只截面）。
#   · 趋势档：价格类因子，**2000-10 ~ 2026-08、311 期月频**（26 年，101 只纳指100 成分），
#     由 factor_backtest.py --watch 产出。（2026-10-02 由 49 期扩样，旧读数见 ic_prev）
#   · **口径警告**：回测用的是 EDGAR 时点值，而实时榜单用的是 yfinance 当前快照，
#     两者数据源不同 ⇒ 回测验证的是**因子概念**，不是逐字的线上输入。
#
# 更新方式：重跑 `fundamental_backtest.py --pool {nasdaq,sp500} --forward 252 --rebalance 12 --neutral --start 2009-01`
#          与 `factor_backtest.py --watch`，把新的 IC / t 抄回这里。
BACKTEST_PROVENANCE = (
    "EDGAR 时点基本面 / 2009-01~2025-01 / 17 个不重叠年度观测 / 行业中性化；"
    "纳指100 与标普500 两个宇宙结论一致"
)
SIGNIFICANT_T = 2.0        # |t| >= 2 才算统计显著
# ★ 2026-10-10：下面这档**只用于「分档描述」**（把某个 IC 归到「弱/边际」一栏），
#   **不得**用它下「显著」结论 —— 与 `SIGNIFICANT_T` 语义不同，不可互换。
#   统一的动机：这些值原本在 `factor_backtest.py` / `fundamental_backtest.py` 里
#   被硬编码 9 处（`2.0` / `1.5` / `1.0`），调档时需要人工同步多个文件。
#   ★ 同轮收敛：原 `WEAK_T = 1.0` 已删除 —— 它在 `factor_backtest.py` 印的 `~弱`
#     与 `MARGINAL_T` 在 `fundamental_backtest.py` 印的 `~ 弱` **是同一个标签**，
#     1.0 属漂移而非设计差异 ⇒ 统一到 1.5（更贴近「未达常规显著」的通常口径）。
MARGINAL_T = 1.5           # 次级档：弱/边际偏离（仅描述，非「显著」）

FACTOR_VALIDATION = {
    "quality": {
        "validated": True,
        "ic": -0.0301, "t": -0.92, "n_periods": 16, "universe": "标普500（436 只截面）",
        "ic_alt": -0.0436, "t_alt": -1.17, "universe_alt": "纳指100（84 只截面）",
        "verdict": "IC≈0，不显著。换宽宇宙复测结论一致（−0.0436 / t −1.17）",
    },
    "value": {
        "validated": True,
        "ic": -0.0344, "t": -1.08, "n_periods": 16, "universe": "标普500（436 只截面）",
        "ic_alt": -0.0503, "t_alt": -1.26, "universe_alt": "纳指100（84 只截面）",
        "verdict": "IC≈0，不显著。低 PB（−0.0533 / t −1.39）与 PE+PB 双低（−0.0532 / t −1.31）同样不显著",
    },
    "growth": {
        "validated": True,
        "ic": -0.0170, "t": -0.51, "n_periods": 16, "universe": "标普500（436 只截面）",
        "ic_alt": 0.0072, "t_alt": 0.24, "universe_alt": "纳指100（84 只截面）",
        "verdict": ("单季营收同比 IC≈0。改用 3 年营收 CAGR 后为 +0.0334 / t 0.94"
                    "（两个宇宙符号一致），方向稳定但**仍不显著**"),
    },
    "trend": {
        "validated": True,
        "ic": -0.0009, "t": -0.08, "n_periods": 311,
        "universe": "价格类因子 311 期月频（纳指100 当前成分，101 只）",
        "period": "2000-10 ~ 2026-08",
        # 旧 49 期读数保留：解释「为什么 2026-10-02 改了默认权重」
        "ic_prev": -0.0037, "t_prev": -0.11, "n_periods_prev": 49,
        "verdict": ("IC≈0，且是**被精确测出的零**（SE≈0.005 ⇒ 95% CI≈±0.01）；"
                    "近 6/12/18/24 期符号互不一致（近6期 −0.093 / 近12期 +0.010）⇒ 不稳健。"
                    "旧 49 期读数 −0.0037 / t −0.11，方向一致"),
    },
}


def _is_significant(entry: dict) -> bool:
    """|t| >= 2 才算显著。缺 t 值视为不显著（宁可低估自己）。"""
    t_val = entry.get("t")
    return isinstance(t_val, (int, float)) and abs(t_val) >= SIGNIFICANT_T


def insignificant_weight_share(weights: dict | None = None) -> float:
    """返回「**回测不显著**的因子」所占权重比 —— 输出里如实提示置信度用。

    为什么不是「未经验证」：四个因子现在都已回测过，区别只在于**显不显著**。
    旧的「未验证占比」会把「已验证无效」误报成「还没验证」。
    """
    w = FACTOR_WEIGHTS if weights is None else weights
    return round(sum(v for k, v in w.items()
                     if not _is_significant(FACTOR_VALIDATION.get(k, {}))), 4)


def validation_summary(weights: dict | None = None) -> dict:
    """给下游报告用的验证状态摘要。"""
    w = FACTOR_WEIGHTS if weights is None else weights
    share = insignificant_weight_share(w)
    return {
        "insignificant_weight_share": share,
        "backtest_provenance": BACKTEST_PROVENANCE,
        "factors": {
            k: {
                "weight": w.get(k),
                "validated": FACTOR_VALIDATION.get(k, {}).get("validated", False),
                "significant": _is_significant(FACTOR_VALIDATION.get(k, {})),
                "t": FACTOR_VALIDATION.get(k, {}).get("t"),
                "note": FACTOR_VALIDATION.get(k, {}).get("verdict", ""),
            } for k in w
        },
        "caveat": (
            f"本榜单四个因子**都已回测过**（{BACKTEST_PROVENANCE}），"
            f"但**无一统计显著**（|t| 均 < {SIGNIFICANT_T:.0f}）。"
            f"综合分中有 {share * 100:.0f}% 的权重来自**未获证实**的因子。"
            "请把榜单当作「压缩研究范围」的方向，而非统计上可靠的排序。"
            "⚠️ 回测用 EDGAR 时点值，线上榜单用 yfinance 当前快照 —— "
            "验证的是因子概念，不是逐字的线上输入。"
        ),
    }


def _pool_fingerprint(tickers: list[str]) -> str:
    """把标的列表压成短指纹——缓存键必须包含它，否则改了池子仍会读到旧结果。"""
    joined = ",".join(sorted(tickers))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]


def _maybe_cache_path(pool_name: str, date_str: str, tickers: list[str]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in pool_name if c.isalnum() or c in ("-", "_")).lower()
    return CACHE_DIR / f"screener_{safe}_{date_str}_{_pool_fingerprint(tickers)}.json"


def _purge_stale_screener_caches(keep: Path) -> int:
    """删掉**同一股票池**的旧日期缓存，只留本次这一份。

    缓存名里嵌了日期 ``screener_<pool>_<date>_<fp>.json``，而查找只用「今天」
    （``dt.date.today()``）⇒ 旧文件此后再也不会被命中，占用随运行天数**线性增长**。
    这与上游 ``_purge_sibling_cache_variants`` 修掉的价格缓存泄漏是同一类问题，
    故沿用同一套做法：写入前清掉旧变体。**这些是可随时重跑的再生数据，删除不丢信息。**

    实测 2026-10-03：清理前积了 4 个历史日期文件（1.87 MB，最旧的已放 13 天、永不命中）。
    """
    parts = keep.name.split("_")
    if len(parts) < 3:          # 非标准命名（测试里的桩路径）⇒ 一律不动
        return 0
    prefix = f"{parts[0]}_{parts[1]}_"
    removed = 0
    for f in keep.parent.glob(f"{prefix}*.json"):
        if f.name == keep.name:
            continue
        try:
            f.unlink()
            removed += 1
        except OSError:         # 被占用等 ⇒ 跳过，不阻断主流程
            pass
    return removed


# ────────────────────────────── 数据获取 ──────────────────────────────

def _fetch_price(ticker: str, date_str: str) -> tuple[str, pd.DataFrame | None, str | None]:
    """单只标的的行情。复用 load_ohlcv（自带缓存 + 429 重试 + 陈旧检测）。"""
    try:
        df = load_ohlcv(ticker, date_str)
    except NoMarketDataError as exc:
        return ticker, None, f"无行情数据：{exc}"
    except Exception as exc:  # noqa: BLE001
        return ticker, None, f"取数异常 {type(exc).__name__}: {exc}"
    if df is None or df.empty:
        return ticker, None, "行情为空"
    if len(df) < MIN_BARS:
        return ticker, df, f"K线不足 {MIN_BARS} 根（实际 {len(df)} 根）"
    return ticker, df, None


def _fetch_fundamental(ticker: str) -> tuple[str, dict, str | None]:
    """单只标的的核心财务指标。"""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001
        return ticker, {}, f"基本面取数失败 {type(exc).__name__}: {str(exc)[:60]}"

    def _num(key):
        v = info.get(key)
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        return None if (fv != fv or np.isinf(fv)) else fv   # 过滤 NaN / inf

    pe = _num("trailingPE")
    if pe is None or pe <= 0:
        pe = _num("forwardPE")

    return ticker, {
        "pe": pe,
        "roe": _num("returnOnEquity"),
        "margin": _num("profitMargins"),
        "rev_growth": _num("revenueGrowth"),
        "debt_to_equity": _num("debtToEquity"),
        "fwd_pe": _num("forwardPE"),
    }, None


def _concurrent_map(fn, tickers: list[str], workers: int):
    """受限并发执行，返回 {ticker: result}。"""
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, t): t for t in tickers}
        for fut in as_completed(futs):
            tk = futs[fut]
            try:
                out[tk] = fut.result()
            except Exception as exc:  # noqa: BLE001
                out[tk] = (tk, None, f"并发执行异常 {type(exc).__name__}: {exc}")
    return out


# ────────────────────────────── 技术指标 ──────────────────────────────

def _technical_from_frame(df: pd.DataFrame) -> dict | None:
    """从 OHLCV 帧计算技术指标。列名沿用上游：Date/Close/High/Low/Open/Volume。"""
    if "Close" not in df.columns:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < MIN_BARS:
        return None

    vol = pd.to_numeric(df["Volume"], errors="coerce").dropna() if "Volume" in df.columns else pd.Series(dtype=float)

    price = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else price
    # 不足 200 根时不假装有 200 日均线——直接标记为不可用，避免"多头"判断失真
    has_sma200 = len(close) >= 200
    sma200 = float(close.rolling(200).mean().iloc[-1]) if has_sma200 else float("nan")

    mom20 = float((close.iloc[-1] / close.iloc[-21] - 1) * 100) if len(close) >= 21 else 0.0
    mom60 = float((close.iloc[-1] / close.iloc[-61] - 1) * 100) if len(close) >= 61 else mom20

    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    rsi = float(100 - (100 / (1 + rs)).iloc[-1]) if len(close) >= 15 else 50.0

    if len(vol) >= 20:
        vol_ratio = float(vol.iloc[-5:].mean() / (vol.iloc[-20:].mean() + 1e-9))
    else:
        vol_ratio = 1.0

    # 200 日均线不可用时，退化为「价 > 50 日均线」这一弱判据，并在输出中标注
    if has_sma200:
        is_bull = bool(price > sma200 and sma50 > sma200)
    else:
        is_bull = bool(price > sma50)

    last_bar = df["Date"].iloc[-1] if "Date" in df.columns else None

    return {
        "Price": round(price, 2),
        "Trend": "多头" if is_bull else "偏弱",
        "is_bull": is_bull,
        "has_sma200": has_sma200,
        "sma200_dist": round((price / sma200 - 1) * 100, 2) if has_sma200 else None,
        "mom20": round(mom20, 2),
        "mom60": round(mom60, 2),
        "rsi": round(rsi, 2),
        "vol_ratio": round(vol_ratio, 4),
        "last_bar": str(last_bar)[:10] if last_bar is not None else None,
        "bars": len(close),
    }


# ────────────────────────────── 打分 ──────────────────────────────

def _band_score(value, lo, hi, soft=1.0):
    """区间型信号的连续打分：落在 [lo,hi] 给 100，越界按 soft 线性衰减到 0。"""
    if value is None or value != value:
        return 50.0
    if lo <= value <= hi:
        return 100.0
    span = (hi - lo) * soft if soft > 0 else 1.0
    dist = (lo - value) if value < lo else (value - hi)
    return float(max(0.0, 100.0 - dist / max(span, 1e-9) * 100.0))


def _composite(df: pd.DataFrame, weights: dict | None = None) -> pd.Series:
    """由四个**与权重无关**的子分数按权重合成综合分。

    抽成独立函数是为了让「新鲜计算」与「缓存读取」两条路径共用同一套合成逻辑 ——
    否则缓存里的综合分会是用旧权重算好的，改了 ``weights`` 也读不出来。
    """
    w = dict(FACTOR_WEIGHTS if weights is None else weights)
    return (
        df["quality_score"] * w["quality"]
        + df["val_score"] * w["value"]
        + df["growth_score"] * w["growth"]
        + df["trend_score"] * w["trend"]
    ).round(1)


def _score(raw: pd.DataFrame, weights: dict | None = None) -> pd.DataFrame:
    """截面百分位打分。所有单项因子统一归一化到 0~100。

    ``weights`` 可覆盖默认的 ``FACTOR_WEIGHTS``，便于在不改代码的前提下做再校准。
    """
    qw, tw = QUALITY_SUB_WEIGHTS, TREND_SUB_WEIGHTS
    out = raw.copy()

    # ── 质量：ROE + 净利率 + 低负债
    # 加入负债维度，降低 ROE 与净利率的共线性（实测两者秩相关 +0.725）
    roe_r = out["roe"].rank(pct=True).fillna(0.5) * 100
    mar_r = out["margin"].rank(pct=True).fillna(0.5) * 100
    # debt_to_equity 越小越好；负值（净资产为负）视为最差
    dte = out["debt_to_equity"].copy()
    dte = dte.where(dte > 0)
    dte_r = dte.rank(pct=True, ascending=False).fillna(0.5) * 100
    out["quality_score"] = (
        qw["roe"] * roe_r + qw["margin"] * mar_r + qw["low_debt"] * dte_r
    ).round(1)
    out["roe_rank"] = roe_r.round(1)
    out["margin_rank"] = mar_r.round(1)
    out["lowdebt_rank"] = dte_r.round(1)

    # ── 估值：PE 越低分越高
    # 修正点：亏损/缺失 PE 记 0（原代码注释写 0 但实际给 10，导致
    #         亏损公司估值分反而高于高 PE 盈利公司）；并取消原来的 80 分封顶
    #         （封顶使最便宜的一档全部同分，失去区分度）。
    pe = out["pe"]
    valid_pe = pe.where(pe > 0)
    out["pe_missing"] = pe.isna() | (pe <= 0)
    if valid_pe.notna().sum() >= 2:
        pe_r = valid_pe.rank(pct=True, ascending=False) * 100
    else:
        pe_r = pd.Series(np.nan, index=out.index)
    out["val_score"] = pe_r.fillna(0.0).round(1)

    # ── 成长：营收增速
    out["growth_score"] = (out["rev_growth"].rank(pct=True).fillna(0.5) * 100).round(1)

    # ── 趋势：动量 + 均线 + RSI 区间
    # 修正点：原实现是「动量百分位 + 固定加减分(±20/-10/+10/-15)」，
    #         固定加减分让第 3~10 名几乎同分（二值底 45 分），名次近乎随机。
    #         改为三个子分数各自归一化后加权，消除人工平台。
    # ⚠️ 实测该档 IC≈0 且逐年翻符号，见 factor_backtest.py
    mom_r = out["mom60"].rank(pct=True) * 100
    ma_score = out["is_bull"].apply(lambda b: 100.0 if b else 0.0)
    rsi_score = out["rsi"].apply(lambda v: _band_score(v, 45.0, 68.0, soft=1.5))
    out["trend_score"] = (
        tw["mom60"] * mom_r + tw["ma"] * ma_score + tw["rsi"] * rsi_score
    ).round(1)

    out["综合量化分"] = _composite(out, weights)
    return out


# ────────────────────────────── 主流程 ──────────────────────────────

def run_quant_screening(
    tickers: list[str],
    top_n: int = 5,
    pool_name: str = "custom",
    force_refresh: bool = False,
    return_details: bool = False,
    weights: dict | None = None,
) -> pd.DataFrame | dict:
    """执行四维多因子量化初筛。

    ``weights`` 可选覆盖 ``FACTOR_WEIGHTS``（如 ``{"trend": 0.0}`` 即停用趋势档），
    便于依据 factor_backtest.py 的回测结果做再校准而无需改动代码。
    """
    tickers = [t.strip().upper() for t in tickers if t.strip()]
    if not tickers:
        empty = pd.DataFrame()
        empty.attrs["failed_records"] = []
        empty.attrs["metadata"] = {"scanned": 0, "valid": 0, "failed": 0}
        return empty

    today = dt.date.today().isoformat()
    cache_file = _maybe_cache_path(pool_name, today, tickers)
    # 写入前清掉同池的旧日期缓存：它们永远不会再被命中（见函数文档）。
    _purge_stale_screener_caches(cache_file)

    # 1) 日内缓存（schema 版本不匹配则视为未命中）
    if not force_refresh and cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            if payload.get("schema") != CACHE_SCHEMA_VERSION:
                print(f"[Quant Radar] 缓存 schema 为 {payload.get('schema')!r}，"
                      f"当前需 {CACHE_SCHEMA_VERSION}，重新拉取")
                raise ValueError("cache schema mismatch")
            df = pd.DataFrame(payload["records"])
            failed = payload.get("failed_records", [])
            meta = payload.get("metadata", {})
            meta["cached"] = True

            # 缓存只存与权重无关的子分数；综合分必须用**当前**权重重算，
            # 否则调用方传了不同的 weights 仍会读到用旧权重算好的榜单。
            subs = {"quality_score", "val_score", "growth_score", "trend_score"}
            if subs <= set(df.columns) and not df.empty:
                df["综合量化分"] = _composite(df, weights)
                df = df.sort_values("综合量化分", ascending=False).reset_index(drop=True)
                meta["validation"] = validation_summary(weights)

            print(f"[Quant Radar] 命中日内缓存 {cache_file.name}（{len(df)} 只，综合分按当前权重重算）")
            # 验证提示在缓存命中的路径上同样要打印 —— 它是结论可信度的一部分
            if meta.get("validation", {}).get("caveat"):
                print(f"[Quant Radar] ⚠️ 验证状态：{meta['validation']['caveat']}")
            df.attrs["failed_records"] = failed
            df.attrs["metadata"] = meta
            if return_details:
                return {"top_df": df.head(top_n), "full_df": df,
                        "failed_records": failed, "metadata": meta}
            return df
        except Exception as exc:  # noqa: BLE001
            if not isinstance(exc, ValueError):
                print(f"[Quant Radar] 缓存不可用（{exc}），重新拉取")

    print(f"\n[Quant Radar] 逐票拉取 {len(tickers)} 只标的行情（并发 {MAX_WORKERS}）...")

    # 2) 行情：受限并发 + 失败补拉
    price_res = _concurrent_map(lambda t: _fetch_price(t, today), tickers, MAX_WORKERS)
    failed: dict[str, str] = {}
    good: dict[str, pd.DataFrame] = {}
    for tk, (_t, df, err) in price_res.items():
        if err:
            failed[tk] = err
        else:
            good[tk] = df

    for rnd in range(RETRY_PASSES):
        if not failed:
            break
        retry_list = list(failed)
        print(f"[Quant Radar] 第 {rnd + 1} 轮补拉 {len(retry_list)} 只失败标的...")
        retry_res = _concurrent_map(lambda t: _fetch_price(t, today), retry_list, 2)
        still = {}
        for tk, (_t, df, err) in retry_res.items():
            if err:
                still[tk] = err
            else:
                good[tk] = df
                failed.pop(tk, None)
        failed.update(still)

    valid = [t for t in tickers if t in good]
    print(f"[Quant Radar] 行情就绪 {len(valid)}/{len(tickers)}，并发获取基本面...")

    # 3) 基本面
    fund_res = _concurrent_map(_fetch_fundamental, valid, MAX_WORKERS)

    # 4) 组装
    records, tech_meta = [], {}
    for tk in valid:
        tech = _technical_from_frame(good[tk])
        if tech is None:
            failed[tk] = f"K线不足 {MIN_BARS} 根"
            continue
        tech_meta[tk] = tech
        f = fund_res.get(tk, (tk, {}, None))[1] or {}
        records.append({
            "Ticker": tk,
            "Price": tech["Price"],
            "Trend": tech["Trend"],
            "is_bull": tech["is_bull"],
            "has_sma200": tech["has_sma200"],
            "mom20": tech["mom20"],
            "mom60": tech["mom60"],
            "rsi": tech["rsi"],
            "vol_ratio": tech["vol_ratio"],
            "last_bar": tech["last_bar"],
            "bars": tech["bars"],
            "pe": f.get("pe"),
            "roe": f.get("roe"),
            "margin": f.get("margin"),
            "rev_growth": f.get("rev_growth"),
            "debt_to_equity": f.get("debt_to_equity"),
        })

    if not records:
        print("[Quant Radar] 未取得任何有效标的！")
        empty = pd.DataFrame()
        empty.attrs["failed_records"] = [{"ticker": k, "reason": v} for k, v in failed.items()]
        empty.attrs["metadata"] = {"scanned": len(tickers), "valid": 0, "failed": len(failed)}
        return empty

    raw = pd.DataFrame(records)
    out = _score(raw, weights)

    # 5) 展示字段
    out["ROE%"] = out["roe"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A")
    out["净利率%"] = out["margin"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A")
    out["营收增速%"] = out["rev_growth"].apply(lambda x: f"{x*100:.1f}%" if pd.notna(x) else "N/A")
    out["PE"] = out["pe"].apply(
        lambda x: f"{x:.1f}" if pd.notna(x) and x > 0 else ("亏损/NA" if pd.notna(x) else "N/A"))
    out["60日涨幅%"] = out["mom60"].round(1)
    out["20日涨幅%"] = out["mom20"].round(1)
    out["RSI"] = out["rsi"].round(1)
    out["量比"] = out["vol_ratio"].round(2)

    out = out.sort_values("综合量化分", ascending=False).reset_index(drop=True)

    failed_records = [{"ticker": k, "reason": v} for k, v in sorted(failed.items())]
    meta = {
        "cached": False,
        "date": today,
        "pool": pool_name,
        "scanned": len(tickers),
        "valid": len(out),
        "failed": len(failed_records),
        "dropped_pct": round(len(failed_records) / len(tickers) * 100, 1),
        "last_bar": sorted({r["last_bar"] for r in records if r["last_bar"]})[-1:],
        "validation": validation_summary(weights),
    }

    # 6) 缓存
    try:
        cache_file.write_text(json.dumps({
            "schema": CACHE_SCHEMA_VERSION,
            "date": today, "pool": pool_name, "metadata": meta,
            "records": out.to_dict(orient="records"), "failed_records": failed_records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[Quant Radar] 已缓存至 {cache_file.name}")
    except Exception as exc:  # noqa: BLE001
        print(f"[Quant Radar] 写缓存警告: {exc}")

    if meta["dropped_pct"] > 5.0:
        print(f"[Quant Radar] ⚠️ 剔除率 {meta['dropped_pct']}% 偏高，请检查 failed_records")

    print(f"[Quant Radar] ⚠️ 验证状态：{meta['validation']['caveat']}")

    out.attrs["failed_records"] = failed_records
    out.attrs["metadata"] = meta
    if return_details:
        return {"top_df": out.head(top_n), "full_df": out,
                "failed_records": failed_records, "metadata": meta}
    return out


def export_radar_csv(df: pd.DataFrame, path: str, decimals: dict | None = None) -> str:
    """导出为「Excel 友好」的 CSV。

    必须用 ``utf-8-sig``：本表含中文表头（20日涨幅% / 量比 / 综合量化分）。
    普通 UTF-8（无 BOM）在中文 Windows 的 Excel 里会被按 GBK 解析，
    中文显示成 ``20鏃ユ定骞�%`` 这类乱码。
    """
    out = df.copy()
    if decimals is None:
        decimals = {"Price": 2, "量比": 2}
    for col, nd in decimals.items():
        if col in out.columns:
            out[col] = out[col].map(lambda v: f"{float(v):.{nd}f}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(p, index=False, encoding="utf-8-sig", lineterminator="\r\n")
    return str(p)
