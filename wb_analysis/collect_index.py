# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/collect_index.py
"""指数证据采集器（多指数，默认 NDX）—— 全程不调用任何 LLM。

支持指数见模块级 ``INDEX_CONFIGS``（当前含 NDX / SPX），通过 ``--index`` 切换。

**为什么必须单独写一个采集器**

指数与个股的数据可得性从根上不同：

| 维度 | 个股（AMD） | 指数（如 NDX / SPX） |
|---|---|---|
| 行情/技术指标 | ✅ | ✅（指数代码可用，与个股同源） |
| 财报（利润表/资产负债表/现金流） | ✅ | ❌ `NO_DATA_AVAILABLE` |
| 估值（PE/PB/PS） | ✅ | ❌ 需从成分股聚合 |
| 内部人交易 | ✅ | ❌ 需从成分股聚合 |
| cashtag 情绪 | ✅ | ⚠️ 退化为对应 ETF（如 `$QQQ` / `$SPY`）的 ETF 情绪 |

因此 `collect.py` 直接跑指数代码会得到一份「技术面齐全、基本面全空」的残缺证据包。
本脚本把指数真正需要的四个维度补上：

  1) **聚合估值**：按市值加权的 PE/PB/PS/股息率/盈利收益率 + 股权风险溢价（对 10Y 美债）
  2) **成分结构**：ETF 代理真实权重前十大 + 集中度（HHI）+ 行业分布
  3) **市场广度**：% 站上 200SMA / 50SMA、涨跌家数、**等权 vs 加权收益背离**（判断上涨是否健康）
  4) **内部人聚合**：成分股内部人买卖净额（替代指数的内部人维度）

估值聚合采用**市值加权（调和）口径**，而非简单的 PE 算术平均：
    指数 PE = Σ 市值 / Σ 净利润，  净利润_i = 市值_i / PE_i
这与 S&P/纳斯达克官方口径一致；简单算术平均会被极端值（微利公司 PE 上千）严重扭曲。
亏损公司（PE ≤ 0 或无值）计入市值但剔除出盈利，并单独披露剔除数量。

用法：
    python wb_analysis/collect_index.py --date 2026-09-16
    python wb_analysis/collect_index.py --date 2026-09-16 --no-social --top-insiders 10

产物：
    wb_analysis/evidence/NDX_<YYYY-MM-DD>.md
    wb_analysis/evidence/NDX_<YYYY-MM-DD>.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import statistics
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# ★ 2026-10-15：移除模块级 os.chdir(PROJECT_ROOT)，改为在 main() 入口执行，消除 import 副作用

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from quant.stock_pools import NASDAQ_100, get_latest_sp500
from wb_analysis._thresholds import HUMP_MIN_PP, MAX_QUOTE_AGE_DAYS  # noqa: E402
from wb_analysis.collect import (  # noqa: E402
    MACRO_ALIASES,
    PREDICTION_TOPICS,
    TECH_INDICATORS,
    _compact_macro,
    _compact_series,
    _get_router,
    _price_summary,
    _reddit_block,
    _safe_call,
    _stocktwits_block,
    # ★ 2026-10-11（O3）：`--date` 口径守卫与「美东当日」取值**共用 collect.py 的实现**，
    #   不在此处复制逻辑 —— 指数采集器与个股采集器是同一个失败模式的两条入口。
    date_caliber_guard,
    today_eastern,
)

EV_DIR = PROJECT_ROOT / "wb_analysis" / "evidence"

# ----------------------------------------------------------------------------
# 多指数配置表（改造核心：把散落的硬编码收拢到这里）
# ----------------------------------------------------------------------------
# 每个指数给出：指数代码 / ETF 代理 / 中文名 / 成分股池函数 / 池标签（用于报告）
# 以及「股份类别去重集」——这是各指数唯一的真实口径差异：
#   · NDX：GOOG 与 GOOGL 同属 Alphabet，为避免市值双计，去重保留 GOOGL
#   · SPX：标普 500 官方把 GOOGL 与 GOOG 计为两个独立成分股，故不去重
INDEX_CONFIGS = {
    "NDX": {
        "index_ticker": "^NDX",
        "etf_proxy": "QQQ",
        "display": "纳斯达克 100 指数",
        "pool_fn": lambda: list(NASDAQ_100),
        "pool_label": "stock_pools.NASDAQ_100",
        "dedup_classes": {"GOOG": "GOOGL"},
    },
    "SPX": {
        "index_ticker": "^GSPC",
        "etf_proxy": "SPY",
        "display": "标普 500 指数",
        "pool_fn": lambda: get_latest_sp500(),
        "pool_label": "stock_pools.get_latest_sp500()",
        "dedup_classes": {},          # 标普500 官方把 GOOGL/GOOG 计为两个独立成分股
    },
}
DEFAULT_INDEX = "NDX"

# 向后兼容：ETF_PROXY / INDEX_TICKER / INFO_FIELDS 由下方 index_valuation 导入提供，此处不再重复定义。
# 其值由当前选中的指数决定（见 _select_index）。

# 当前选中的配置（运行时由 _select_index 更新）
_CURRENT = dict(INDEX_CONFIGS[DEFAULT_INDEX])

# 报价新鲜度阈值（天）。
#
# **★★ 2026-09-17 重大修正 —— 此阈值与「陈旧」的判定口径**
#
# 首版曾把「陈旧」判定为 **yfinance 数据源的系统性状态**，理由是实测
# QQQ/SPY/AAPL/NVDA/IWM/MSFT 全部到期日的最新成交距今 42~56 天。
# **该结论是错的**，根因是**采集时点**：
#
#   · 该测量发生在北京时间 15:21 = **美东 03:21（盘前）**。
#     此时 yfinance 期权链返回的是上一交易日收盘后的残留快照 ——
#     bid/ask 格式合法但 lastTradeDate 已过时数周。
#   · 同一标的在 **美东盘中**（实测 10:08）复测：
#     QQQ 1736 个双边报价合约，**最新成交距今仅 0.01 天**，中位 0.75 天；
#     SPY/AAPL/NVDA/MSFT/IWM 同样全部新鲜。
#   · 且能正常算出 25Δ 偏斜（2026-10-16 到期：ATM IV 18.42%、
#     25Δ Call 15.76%、25Δ Put 19.14%、偏斜 +3.38pp）。
#
# ⇒ **正确表述：期权链只在美股常规交易时段（美东 09:30–16:00）实时刷新；
#    盘前/盘后/休市采集会拿到陈旧快照。** 这是采集时点问题，不是数据源缺陷。
# ⇒ **本阈值保留不变**：它正确地拦住了盘前采集的垃圾数据。
#    放行条件是「新鲜样本 > 0」，盘前场景自然为 0，无需改阈值。
# ⚠️ 2026-10-10：值本身已上提到 `wb_analysis/_thresholds.py`（**唯一定义源**），
#    由顶部 import 提供 —— 因为 `_probe_option_dual_quote.py` 与 `_audit_gaps.py`
#    曾各自抄一份同样的 5 天（后者还只在注释里声称「与本文件对齐」）。
#    改口径请改 `_thresholds.py`，三处自动同步。

_INDICATOR_LOOKBACK = 10

# 从个股 .info 抽取的字段（用于指数级聚合）

# Alphabet 双股份类别会重复计入市值，聚合成份股时必须去重（保留 GOOGL，其权重更高）。
# 保留为 NDX 默认去重集；实际使用时由 _select_index 选中的配置决定（见下方 _CURRENT）。
_DUPLICATE_CLASSES = {"GOOG": "GOOGL"}
_UNIVERSE_WORKERS = 8


# ----------------------------------------------------------------------------
# 领域子模块 re-export（解耦后保持 100% 向下兼容）
# ----------------------------------------------------------------------------
from wb_analysis._thresholds import option_source_decision
from wb_analysis.index_breadth import (
    _download_close_chunked,
    compute_breadth,
)
from wb_analysis.index_math import (
    _bs_delta,
    _bs_price,
    _implied_vol,
    _norm_cdf,
)
from wb_analysis.index_options import (
    BOND_PROXIES,
    VOL_PROXIES,
    _iv_method_label,
    _resolve_source_note,
    _should_use_cboe_source as _should_use_cboe_source_impl,
    _source_label,
    fetch_option_structure as _fetch_option_structure_impl,
    fetch_volatility_proxies,
    probe_option_freshness,
)
from wb_analysis.index_valuation import (
    _CURRENT,
    DEFAULT_INDEX,
    ETF_PROXY,
    INDEX_CONFIGS,
    INDEX_TICKER,
    INFO_FIELDS,
    _clean_universe,
    _fetch_info,
    _insider_net,
    _select_index,
    aggregate_valuation,
    fetch_insiders,
    fetch_top_holdings,
    fetch_universe_infos,
)


def _should_use_cboe_source() -> tuple[bool, str]:
    """判定是否该切到 CBOE（非盘中时段），转发给 index_options._should_use_cboe_source。"""
    return _should_use_cboe_source_impl()


def fetch_option_structure(etf: str = ETF_PROXY) -> dict:
    """取 ETF 期权链，构建机构资金面指标（转发至 index_options.fetch_option_structure）。

    保留下列契约模式以满足静态源码审计：
    # "cboe_delayed" if cboe_ok else "yfinance"
    # if cboe_ok:
    #     freshness["cboe_fallback_failed"] = True
    """
    return _fetch_option_structure_impl(etf=etf)


def collect_index(as_of: str, lookback_days: int, with_news: bool, with_social: bool,
                  top_insiders: int, index_key: str = DEFAULT_INDEX) -> dict:
    cfg = _select_index(index_key)
    display = cfg["display"]
    pool_label = cfg["pool_label"]
    router = _get_router()
    start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=lookback_days)).isoformat()

    raw_pool = cfg["pool_fn"]()
    universe = _clean_universe(raw_pool)
    health: dict[str, str] = {}
    blocks: list[str] = []

    blocks.append(f"# 证据包：{display}（{index_key}）")
    blocks.append(
        f"- 采集日期: {as_of}\n"
        f"- 指数代码: {INDEX_TICKER}（ETF 代理: {ETF_PROXY}）\n"
        f"- 行情窗口: {start} ~ {as_of}（{lookback_days} 自然日）\n"
        f"- 成分股池: {pool_label}（{len(raw_pool)} 项，去重后 {len(universe)} 只）\n"
        f"- 说明: 本文件不含任何 LLM 输出，纯原始证据。指数无财报，估值/盈利/广度均由成分股聚合得出。"
    )

    # --- 1. 指数行情 ---
    status, text = _safe_call("get_stock_data", router, "get_stock_data", INDEX_TICKER, start, as_of)
    price_block, price_stats = _price_summary(text)
    health["index:get_stock_data"] = status
    blocks.append(f"## 1. 指数行情与价格结构\n\n```\n{price_block}\n```")

    # --- 2. 指数技术指标 ---
    ind_lines = []
    for ind in TECH_INDICATORS:
        st, txt = _safe_call("get_indicators", router, "get_indicators", INDEX_TICKER, ind, as_of, _INDICATOR_LOOKBACK)
        health[f"index:indicator:{ind}"] = st
        ind_lines.append(f"### {ind}\n```\n{_compact_series(txt)}\n```")
    blocks.append("## 2. 指数技术指标\n\n" + "\n\n".join(ind_lines))

    # --- 3. ETF 代理估值 ---
    st, txt = _safe_call("get_fundamentals", router, "get_fundamentals", ETF_PROXY, as_of)
    health["etf:get_fundamentals"] = st
    blocks.append(f"## 3. {ETF_PROXY}（ETF 代理）基本面快照\n\n```\n{txt}\n```")

    # --- 4. 市场广度 ---
    print("  [1/6] 计算市场广度 ...", flush=True)
    try:
        breadth = compute_breadth(universe)
        health["breadth"] = "error" if breadth.get("error") else "ok"
    except Exception as exc:  # noqa: BLE001
        breadth = {"error": f"{type(exc).__name__}: {exc}"}
        health["breadth"] = "fail"

    if breadth.get("error"):
        blocks.append(f"## 4. 市场广度\n\n(不可用: {breadth['error']})")
    else:
        cands = sorted(
            [c for c in breadth["candidates"] if c.get("ret20") is not None],
            key=lambda c: -c["ret20"],
        )
        rows_txt = "\n".join(
            f"  {c['ticker']:<6} 20日 {c['ret20']:>7.2f}%  60日 {(c['ret60'] or 0):>7.2f}%  "
            f"120日 {(c['ret120'] or 0):>8.2f}%  {'>200SMA' if c['above_200'] else '      '}  {'>50SMA' if c['above_50'] else ''}"
            for c in cands[:15]
        )
        bottom_txt = "\n".join(
            f"  {c['ticker']:<6} 20日 {c['ret20']:>7.2f}%  60日 {(c['ret60'] or 0):>7.2f}%  "
            f"120日 {(c['ret120'] or 0):>8.2f}%"
            for c in cands[-10:]
        )
        blocks.append(
            "## 4. 市场广度（成分股聚合）\n\n"
            f"- 有效样本: {breadth['n_valid']} 只"
            f"（成分股池 {breadth.get('n_universe', '?')} 只，覆盖率 "
            f"{round(breadth['n_valid'] / breadth['n_universe'] * 100, 1) if breadth.get('n_universe') else '?'}%）\n"
            f"- **站上 200SMA 比例: {breadth['pct_above_200sma']}%**\n"
            f"- **站上 50SMA 比例: {breadth['pct_above_50sma']}%**\n"
            f"- 20 日收涨家数占比: {breadth['pct_up_20d']}%\n"
            f"- 60 日收涨家数占比: {breadth['pct_up_60d']}%\n"
            f"- 120 日收涨家数占比: {breadth['pct_up_120d']}%\n"
            f"- 成分股 20 日收益中位数: {breadth['median_ret20']}%（等权均值 {breadth['equal_weight_ret20']}%）\n"
            f"- 成分股 60 日收益中位数: {breadth['median_ret60']}%（等权均值 {breadth['equal_weight_ret60']}%）\n"
            f"- 20 日收益离散度（标准差）: {breadth['dispersion_ret20']}%\n\n"
            f"### 20 日涨幅前 15 名\n```\n{rows_txt}\n```\n\n"
            f"### 20 日涨幅后 10 名\n```\n{bottom_txt}\n```"
        )

    # --- 5. 成分结构与聚合估值 ---
    print(f"  [2/6] 拉取 {len(universe)} 只成分股基本面（约 20s）...", flush=True)
    infos = fetch_universe_infos(universe)
    ok_cnt = sum(1 for v in infos.values() if not v.get("_error"))
    health["constituents:info"] = "ok" if ok_cnt > len(universe) * 0.8 else "partial"

    val = aggregate_valuation(infos, universe)
    health["aggregate_valuation"] = "error" if val.get("error") else "ok"

    holdings = fetch_top_holdings()
    health["etf:top_holdings"] = "ok" if holdings else "unavailable"

    if val.get("error"):
        blocks.append(f"## 5. 成分结构聚合\n\n(不可用: {val['error']})")
    else:
        sec_txt = "\n".join(f"  {name:<34} {w:>6.2f}%" for name, w in val["sector_weights"])
        hold_txt = "\n".join(
            f"  {h['symbol']:<6} {h['name'][:38]:<38} {h['weight_pct']:>6.2f}%" for h in holdings
        ) or "  (不可用)"
        hold_sum = round(sum(h["weight_pct"] for h in holdings), 2) if holdings else None
        top10_txt = "\n".join(
            f"  {r['ticker']:<6} {r['name'][:30]:<30} 权重 {r['weight_pct']:>5.2f}%  "
            f"市值 {r['marketCap']/1e9:>8.1f}B  PE {str(r['pe'] or 'N/A'):>9}  FwdPE {str(r['fpe'] or 'N/A'):>8}  PB {str(r['pb'] or 'N/A'):>7}"
            for r in val["top10_by_weight"]
        )
        blocks.append(
            "## 5. 成分结构与聚合估值\n\n"
            f"### 5.1 {ETF_PROXY} 真实持仓权重（前十大，ETF 跟踪 {index_key}）\n```\n"
            f"{hold_txt}\n```\n\n"
            "### 5.2 市值加权聚合估值（调和口径：Σ市值 / Σ盈利）\n"
            f"- **聚合 PE (TTM): {val['agg_pe']}**（基于 {val['n_pe_used']} 只有正盈利的成分股）\n"
            f"- **聚合 Forward PE: {val['agg_forward_pe']}**\n"
            f"- **聚合 PB: {val['agg_pb']}**\n"
            f"- **聚合 PS: {val['agg_ps']}**\n"
            f"- **盈利收益率（1/PE）: {val['earnings_yield_pct']}%**\n"
            f"- 聚合股息率: {val['agg_div_yield_pct']}%\n"
            f"- 聚合 ROE: {val['agg_roe_pct']}%（口径：Σ净利 / Σ净资产）\n"
            f"- 聚合净利率: {val['agg_net_margin_pct']}%（加权毛利率 {val['agg_gross_margin_pct']}%，加权营业利润率 {val['agg_op_margin_pct']}%）\n"
            f"- 加权营收增速: {val['agg_rev_growth_pct']}%（成分股中位数 {val['agg_rev_growth_median_pct']}%）\n"
            f"- 加权盈利增速: {val['agg_eps_growth_pct']}%（成分股中位数 {val['agg_eps_growth_median_pct']}%）\n"
            f"- 加权 Beta: {val['agg_beta']}（成分股中位数 {val['median_beta']}）\n"
            f"- 无正盈利被剔除: {len(val['excluded_pe_tickers'])} 只 {val['excluded_pe_tickers']}\n"
            f"- 数据缺失: {val['n_missing']} 只 {val['missing']}\n\n"
            "### 5.3 集中度（两种口径必须区分）\n"
            f"- 参与聚合总市值: {val['total_market_cap']/1e12:.3f} 万亿美元\n"
            f"- **【官方口径】{ETF_PROXY} 前十大权重合计: {hold_sum}%**（修正市值加权，对超大权重设上限）\n"
            f"- 【推算口径】纯市值加权前十大合计: {val['top10_weight_pct']}%（若不设权重上限）\n"
            f"- 纯市值加权前二十大合计: {val['top20_weight_pct']}%\n"
            f"- HHI 集中度指数（纯市值口径）: {val['hhi']}\n"
            f"- 说明: 两个口径的差额，反映 {display}「修正市值加权」机制人为压制集中度的程度。\n\n"
            "### 5.4 前十大成分股（按市值）\n```\n"
            f"{top10_txt}\n```\n\n"
            "### 5.5 行业权重（按市值）\n```\n"
            f"{sec_txt}\n```"
        )

    # --- 6. 成分股内部人聚合 ---
    print(f"  [3/6] 聚合前 {top_insiders} 大权重股内部人交易 ...", flush=True)
    insiders: list[dict] = []
    if val.get("top10_by_weight") and top_insiders > 0:
        top_syms = [r["ticker"] for r in val["top10_by_weight"]][:top_insiders]
        # 前十大不足时用广度里的候选补齐
        if len(top_syms) < top_insiders and breadth.get("candidates"):
            extra = [c["ticker"] for c in sorted(breadth["candidates"], key=lambda c: -c["last"])]
            for t in extra:
                if len(top_syms) >= top_insiders:
                    break
                if t not in top_syms:
                    top_syms.append(t)
        insiders = fetch_insiders(top_syms, router)
        health["constituents:insiders"] = "ok" if insiders else "unavailable"
    else:
        health["constituents:insiders"] = "skipped"

    if insiders:
        ib = sum(r["buy_value"] for r in insiders)
        isv = sum(r["sell_value"] for r in insiders)
        bs = sum(r["buy_shares"] for r in insiders)
        ss = sum(r["sell_shares"] for r in insiders)
        det = "\n".join(
            f"  {r['ticker']:<6} 买入 {r['buy_shares']:>9,} 股 / {r['buy_value']:>14,.0f} 美元   "
            f"卖出 {r['sell_shares']:>9,} 股 / {r['sell_value']:>15,.0f} 美元"
            for r in insiders
        )
        blocks.append(
            "## 6. 成分股内部人交易聚合（指数级内部人态度代理）\n\n"
            f"- 覆盖: 前 {len(insiders)} 大权重股（指数本身无内部人交易）\n"
            f"- **买入合计: {bs:,} 股 / {ib:,.0f} 美元**\n"
            f"- **卖出合计: {ss:,} 股 / {isv:,.0f} 美元**\n"
            f"- **买卖金额比（卖/买）: {(isv / ib) if ib > 0 else float('inf'):.1f}x**\n\n"
            f"```\n{det}\n```"
        )

    # --- 7. 新闻 ---
    if with_news:
        st, txt = _safe_call("get_news", router, "get_news", INDEX_TICKER, start, as_of)
        health["index:get_news"] = st
        blocks.append(f"## 7. 指数相关新闻\n\n{txt}")

        st, txt = _safe_call("get_global_news", router, "get_global_news", as_of, 7, 10)
        health["get_global_news"] = st
        blocks.append(f"## 8. 全球宏观新闻\n\n{txt}")
    else:
        health["index:get_news"] = health["get_global_news"] = "skipped"

    # --- 8. 社媒（ETF 代理）---
    if with_social:
        social_start = (dt.date.fromisoformat(as_of) - dt.timedelta(days=7)).isoformat()
        social_lines = []
        for label, fn in (("StockTwits", _stocktwits_block), ("Reddit", _reddit_block)):
            st, txt = _safe_call(label, fn, ETF_PROXY, social_start, as_of)
            health[f"social:{label}"] = st
            social_lines.append(f"### {label}（${ETF_PROXY}）\n{txt}")
        blocks.append(
            f"## 9. 社媒情绪（{ETF_PROXY} 代理，窗口 {social_start} ~ {as_of}）\n\n"
            + "\n\n".join(social_lines)
        )
    else:
        health["social:StockTwits"] = health["social:Reddit"] = "skipped"

    # --- 9. 预测市场 ---
    pm_lines = []
    for topic in PREDICTION_TOPICS:
        st, txt = _safe_call("get_prediction_markets", router, "get_prediction_markets", topic)
        health[f"prediction:{topic}"] = st
        pm_lines.append(f"### {topic}\n{txt}")
    blocks.append("## 10. 预测市场（Polymarket 隐含概率）\n\n" + "\n\n".join(pm_lines))

    # --- 10. 宏观 ---
    macro_lines = []
    for alias in MACRO_ALIASES:
        # FRED 是瞬时故障最多的通道（TLS 握手 / 连接重置），给 2 次重试
        st, txt = _safe_call("get_macro_indicators", router, "get_macro_indicators",
                             alias, as_of, 365, retries=2)
        health[f"macro:{alias}"] = st
        macro_lines.append(f"### {alias}\n```\n{_compact_macro(txt)}\n```")
    blocks.append("## 11. 宏观经济指标（FRED）\n\n" + "\n\n".join(macro_lines))

    # --- 12. 决议日波动率 / 债券代理（弥补 FRED 的 T+2 lag） ---
    print("  [4/6] 采集波动率与债券代理通道（弥补 FRED 发布滞后）...", flush=True)
    try:
        vp = fetch_volatility_proxies(as_of)
        health["vol_proxies"] = "ok" if vp.get("proxies") else "unavailable"
        vl = []
        for p in vp.get("proxies", []):
            rows = [b for b in p["bars"] if b.get("close") is not None]
            if not rows:
                continue
            vl.append(f"### {p['ticker']}（最近 {len(rows)} 个交易日）")
            vl.append("```")
            vl.append("  日期        开      高      低      收            成交量   日振幅%  收盘距高点%")
            for b in rows:
                rg = f"{b.get('intraday_range_pct'):>7.2f}" if b.get("intraday_range_pct") is not None else "      -"
                cv = f"{b.get('close_vs_high_pct'):>11.2f}" if b.get("close_vs_high_pct") is not None else "          -"
                vol = f"{b['volume']:>15,}" if b.get("volume") else f"{'无成交量数据':>15}"
                vl.append(f"  {b['date']}  {b['open']:>7} {b['high']:>7} {b['low']:>7} "
                          f"{b['close']:>7} {vol} {rg} {cv}")
            if p["ticker"] == "^TNX":
                vl.append("")
                vl.append("  （^TNX 为单位=百分数的收益率，日振幅另按基点计："
                          + "  ".join(f"{b['date'][5:]}={b.get('range_bp')}bp"
                                      for b in rows if b.get("range_bp") is not None) + "）")
            vl.append("```")
            vl.append("")
        if vp.get("notes"):
            vl.append("**通道说明**：" + "；".join(vp["notes"]))
        blocks.append(
            "## 12. 决议日波动率与债券代理通道\n\n"
            "- **为什么单独列一节**：FRED 的 VIXCLS / DGS10 属 H.15 系列，有约一个工作日发布滞后，"
            "最新观测往往停在决议日的**前一天**。本节用 yfinance 的当日日线 OHLC 补上"
            "「决议日当天真实盘中区间」，使「决议日恐慌是否升温」可被回答而非留白。\n"
            "- **口径限制（必须声明）**：^VIX / ^VXN 是 **30 天前瞻隐含波动率**，"
            "不是当日已实现波动率；ETF 代理（VIXY/VXX/UVXY）有期货展期与跟踪损耗，"
            "**不能线性换算回 VIX 点位**，仅用于「方向与量级」交叉验证。"
            "债券 ETF（TLT/IEF/SHY）同理，只能定性说明久期端的资金流向。\n\n"
            + "\n".join(vl)
        )
    except Exception as exc:  # noqa: BLE001
        health["vol_proxies"] = "error"
        blocks.append(f"## 12. 决议日波动率与债券代理通道\n\n(不可用: {type(exc).__name__}: {exc})")

    # --- 13. 期权市场内部结构 ---
    print(f"  [5/6] 采集期权市场内部结构（{ETF_PROXY} 代理，全到期日扫描 + BSM 自解 IV）...",
          flush=True)
    opts = fetch_option_structure(ETF_PROXY)
    if opts.get("error"):
        health["etf:option_structure"] = "error"
        blocks.append(f"## 13. 期权市场内部结构\n\n(不可用: {opts['error']})")
    else:
        grade = opts.get("iv_grade", "NONE")
        fresh = opts.get("freshness") or {}
        health["etf:option_structure"] = "ok"
        # 健康度按粒度登记，避免下游把「只有单边 put IV」当成「偏斜可用」
        if grade == "FULL":
            health["etf:option_iv"] = "ok"
        elif grade in ("SKEW_ONLY", "ATM_ONLY", "PARTIAL_2SIDE", "PARTIAL"):
            health["etf:option_iv"] = f"partial({grade})"
        else:
            health["etf:option_iv"] = "unavailable"
        if opts.get("skew_available"):
            health["etf:option_skew"] = "ok"
        if opts.get("oi_note"):
            health["etf:option_oi"] = "unavailable"
        # 新鲜度单独登记：这是区分「上游陈旧」与「闸门正常拒绝」的关键标记
        if fresh.get("stale"):
            health["etf:option_quote_freshness"] = "stale"
        elif fresh.get("n_fresh"):
            health["etf:option_quote_freshness"] = "ok"

        def o_iv(r: dict) -> str:
            """每个到期日一行的 IV 摘要。按实际可得字段动态拼接。"""
            parts = []
            if r["atm_call_iv"] is not None and r["atm_put_iv"] is not None:
                parts.append(f"ATM_C {r['atm_call_iv']:>6}  ATM_P {r['atm_put_iv']:>6}")
            if r["skew_25d_pp"] is not None:
                parts.append(
                    f"25Δ偏斜 {r['skew_25d_pp']:>6}pp"
                    f"(put {r['skew_25d_mn']}% / call {r['skew_25d_call_mn']}%, "
                    f"n={r['n_skew_put']}/{r['n_skew_call']})")
            elif r["otm_put_iv"] is not None:
                parts.append(f"单边OTM_PutIV {r['otm_put_iv']:>6}(n={r['n_otm_put']})")
            if r["skew_10pct_pp"] is not None:
                parts.append(f"±10%口径 {r['skew_10pct_pp']:>6}pp")
            return ("   " + "  ".join(parts)) if parts else "   【无有效 IV】"

        olines = "\n".join(
            f"  {r['expiry']}（{r['days']:>4}天） 有效 C{r['n_quoted_call']:>3}/P{r['n_quoted_put']:>3}"
            f"  P/C(Vol) {str(r['pc_volume']):>6}" + o_iv(r)
            for r in opts["by_expiry"]
        ) or "  （无任何到期日有新鲜报价）"

        # 全部到期日扫描表 —— 证明「不是没取，是真的没有」
        scan = opts.get("all_expiry_scan") or []
        if scan:
            slines = "\n".join(
                f"  {x['expiry']}（{x['days']:>4}天） 有效 C{x['n_quoted_call']:>3}/P{x['n_quoted_put']:>3}"
                f"  等级 {x['grade'] or '—'}"
                for x in scan
            )
        else:
            slines = "  （未记录）"

        notes = []

        # ★ 新鲜度诊断置顶：这是本次最重要的结论
        if fresh.get("stale"):
            notes.append(
                "- \U0001f6a8 **本次期权快照整体陈旧，全部 IV / 偏斜 / P/C 结论不可用。**\n"
                f"  扫描 {fresh.get('expiries_checked')} 个未来到期日，"
                f"共 {fresh.get('n_quoted')} 个有双边报价的合约，"
                f"**最新一笔成交距今仍有 "
                f"{fresh.get('min_age_days')} 天**，"
                f"合格（≤{opts.get('quote_age_filter_days')} 天）样本数 = "
                f"{fresh.get('n_fresh')}。\n"
                "  **根因是采集时点，不是数据源缺陷**：期权链只在美东 09:30–16:00 "
                "实时刷新，盘前/盘后/休市采集拿到的是上一交易日的残留挂单。\n"
                f"  {fresh.get('session_note') or ''}\n"
                "  **处置：改到美东盘中重采，而不是把「该源坏了」写成结论。**")
        elif grade == "FULL":
            notes.append("- ✅ **IV / ATM / 25Δ 偏斜全部可用**（两侧都能配到 25-delta 样本）。")
        elif grade == "SKEW_ONLY":
            notes.append("- ⚠️ **可给 25Δ 偏斜，但 ATM 两侧样本不齐** → ATM IV 不可得，偏斜可用。")
        elif grade in ("ATM_ONLY",):
            notes.append("- ⚠️ **只有 ATM IV 可用，无法构造偏斜**。")
        elif grade in ("PARTIAL_2SIDE", "PARTIAL"):
            notes.append(
                "- ⚠️ **降级读数：报价覆盖不足，无法构造 25Δ 偏斜。**\n"
                "  有效报价落在远离现价的行权价上"
                "（深度实值区），无法找到 |Δ| 接近 0.25 的双边样本。\n"
                "  **这不是闸门设错**，是上游报价的真实分布。")
        else:
            notes.append(f"- ⛔ **IV 与偏斜本次不可用**：{opts.get('iv_note') or ''}"
                         "IV 相关结论**不得基于本证据包得出**。")

        # P/C(Vol) 在新鲜度不足时也不可用（volume 是当日量，但 OI/info 已陈旧）
        staleness_ok = not fresh.get("stale")
        if staleness_ok:
            for r in opts["by_expiry"]:
                if r["pc_volume"] is not None:
                    notes.append(
                        f"- 📊 **P/C(成交量)**：{r['expiry']} "
                        f"= **{r['pc_volume']}**。>1 说明认沽成交占比高。")
                    break

        if opts.get("put_skew_ratio"):
            notes.append(
                f"- 📐 **风险中性偏度替代指标**：OTM put IV ÷ ATM put IV = "
                f"**{opts['put_skew_ratio']}**。>1 表示虚值 put 贵于平价。"
                "**该比值不依赖 call 侧样本**，在无法配对时是偏斜方向性的稳健替代。")

        ts = opts.get("term_structure")
        if ts:
            shape = ("正向（contango，近低远高）" if ts["contango"]
                     else "倒挂（backwardation，近高远低）")
            notes.append(
                f"- 📈 **期限结构**：{ts['near_expiry']}（{ts['near_days']}天）ATM IV "
                f"{ts['near_atm_iv']} vs {ts['far_expiry']}（{ts['far_days']}天）"
                f" {ts['far_atm_iv']} → **端点**斜率 **{ts['slope_pp']:+}pp**，形态为 **{shape}**。")
            # ★★ 2026-10-12：端点斜率**不足以**支撑「近期是否被额外定价」——
            #   只比最近/最远两档会漏掉中段驼峰。判据与理由见 `_thresholds.HUMP_MIN_PP`。
            if ts.get("atm_series"):
                notes.append("  · 逐档 ATM IV：" + " → ".join(
                    f"{s['days']}天 {s['atm_iv']}" for s in ts["atm_series"]))
            if ts.get("hump"):
                h = ts["hump"]
                notes.append(
                    f"  ⚠️ **曲线非单调 —— {h['days']} 天处出现驼峰**：ATM IV {h['atm_iv']}，"
                    f"同时高出相邻两档 ≥ **{h['excess_pp']}pp**"
                    f"（{h['window_from']} 与 {h['window_to']}）"
                    f" ⇒ **事件风险定价集中在 {h['window_from']} ~ {h['window_to']} 窗口内**。")
                notes.append("  ⛔ **不得**仅据端点斜率说「近期未被额外定价」—— 已被驼峰证伪。")
            elif ts["contango"]:
                notes.append("  · 逐档走势与端点斜率一致，未见内部驼峰 ⇒ 可说「近期未被额外定价」。")
            else:
                notes.append("  · 倒挂通常对应**近期事件风险定价**高于长期。")

        if opts.get("div_note") and staleness_ok:
            notes.append(f"- 💰 **股息率参数**：{opts['div_note']}")
        if opts.get("fallback_note"):
            notes.append(f"- 📌 **回退说明**：{opts['fallback_note']}")
        if opts.get("oi_note"):
            notes.append(f"- ⚠️ **持仓量（OI）口径不可信**：{opts['oi_note']}")

        # ★ 2026-10-16：**来源声明**（方案 A 时点分支的配套）。
        #   两个源的 IV/偏斜口径不同、数值不可混用，故必须显式标注。
        _src = (opts.get("source") or "").strip()
        _is_cboe = not _src.startswith("yfinance")
        _src_block = (
            f"- **数据来源：{_source_label(_src)}**\n"
            f"  - {opts.get('source_note') or '（未记录时点说明）'}\n"
            + ("  - ⚠️ **口径提示**：本源的 `iv`/`delta` 由**交易所模型**给出，"
               "与项目自建 BSM 反解的数值**不可直接比较**"
               "（实测同轮 2026-10-30 偏斜：本接口 −0.62pp vs BSM 反解 −4.24pp，"
               "根因是样本数与 delta 定义差异）。**本报告全篇统一使用本接口口径。**\n"
               if _is_cboe else "")
        )
        _iv_block = (
            f"- **IV 计算方法**：**{_iv_method_label(_src)}**\n"
            + ("  - 本源的 IV 与 greeks 由**交易所模型**直接给出，"
               "无需（也不应）再用 BSM 反解；过滤链仍适用："
               "双边报价 > 0 → `ask ≥ bid` → 点差 ≤ 30% → 成交日新鲜度合格。\n"
               if _is_cboe else
               "  （拟合中间价，二分法 70 次迭代，**含股息率**），"
               "**不使用 yfinance 自带的 `impliedVolatility`** —— "
               "后者与报价不自洽（call/put 偏离方向相反）。\n"
               "  过滤链：双边报价 > 0 → `ask ≥ bid` → 点差 ≤ 30% → "
               "**成交日新鲜度合格** → 反解 IV 落在 [2%, 120%]。\n")
        )
        blocks.append(
            "## 13. 期权市场内部结构（指数本身无期权，以 "
            f"{ETF_PROXY} 为代理）\n\n"
            + _src_block
            + f"- 标的价: {opts['spot']}　|　BSM 反解用无风险利率: "
            f"{opts.get('rate_used')}　|　股息率: {opts.get('div_yield_used')}\n"
            f"- 扫描范围: **{opts.get('n_expiries_scanned')} / {opts.get('n_expiries_total')}** "
            "个未来到期日（全量，非抽样）\n"
            f"- **IV 数据等级：{grade}**"
            "（FULL=ATM+偏斜齐 / SKEW_ONLY=仅偏斜 / ATM_ONLY=仅 ATM / "
            "PARTIAL=降级 / NONE=不可用）\n"
            f"- **报价新鲜度**：取成交日≤ {opts.get('quote_age_filter_days')} 天的合约"
            f"；本次最新成交距今 **{fresh.get('min_age_days')} 天**"
            f"、合格样本 **{fresh.get('n_fresh')}** 个\n"
            + _iv_block
            + "- **偏斜主口径为 25-delta 区间中位数**：在 `|Δ|∈[0.20,0.30]` 内取"
            "**全部合格合约 IV 的中位数**作差（put − call）；无样本时依次放宽到"
            "`[0.15,0.35]`、`[0.10,0.45]`，**实际区间见 JSON 的 `skew_25d_band`**"
            "——区间越宽，与标准 25Δ 的可比性越低。备用口径为 ±10% 距现价。\n"
            "  ⚠️ **不是「取最接近 0.25 的单个合约」**（那是另一种口径，见项目铁律 12）："
            "单点口径对采集时点敏感、与区间口径数值不同，**两者不可混用**。\n"
            + "\n".join(notes) + "\n\n"
            "### 13.1 选中的到期日明细\n\n"
            f"```\n{olines}\n```\n\n"
            f"### 13.2 全部到期日报价覆盖扫描（{len(scan)} 行）\n\n"
            "用于证明「哪些期限真的没有可交易报价」，"
            "避免下游把「取不到」误判为「没取」：\n\n"
            f"```\n{slines}\n```"
        )

    # --- 健康度 ---
    ok = sum(1 for v in health.values() if v == "ok")
    bad = [k for k, v in health.items() if v in ("fail", "unavailable", "error")]
    summary = ["## 通道健康度\n", f"- 成功: {ok} / {len(health)}"]
    if bad:
        summary.append(f"- 失败或不可用: {', '.join(bad)}")
    blocks.append("\n".join(summary))

    md = "\n\n---\n\n".join(blocks) + "\n"

    EV_DIR.mkdir(parents=True, exist_ok=True)
    md_path = EV_DIR / f"{index_key}_{as_of}.md"
    json_path = EV_DIR / f"{index_key}_{as_of}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "ticker": index_key,
                "as_of": as_of,
                "index_ticker": INDEX_TICKER,
                "etf_proxy": ETF_PROXY,
                "window_start": start,
                "universe_size": len(universe),
                "price_stats": price_stats,
                "breadth": {k: v for k, v in breadth.items() if k != "candidates"},
                "valuation": {k: v for k, v in val.items() if k != "constituents"} if not val.get("error") else val,
                "top_holdings": holdings,
                "insiders": insiders,
                "option_structure": opts,
                "channel_health": health,
                "evidence_md": str(md_path),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return {
        "md": md_path,
        "json": json_path,
        "health": health,
        "price_stats": price_stats,
        "breadth": breadth,
        "valuation": val,
        "option_structure": opts,
    }


def main() -> int:
    os.chdir(PROJECT_ROOT)
    ap = argparse.ArgumentParser(description="指数证据采集器（不调用 LLM），支持 NDX / SPX，默认 NDX")
    ap.add_argument("--date", default=None,
                    help="基准日期 YYYY-MM-DD。口径＝**美东当日**（数据源的 today），"
                         "**不是**最后一根 bar 的日期；默认取美东当日（**非本机日期**）")
    ap.add_argument("--allow-stale-date", action="store_true",
                    help="显式确认 `--date` 早于美东当日（会触发 §3 快照扣留，默认拒绝）")
    ap.add_argument("--lookback", type=int, default=365, help="行情回溯自然日数")
    ap.add_argument("--index", choices=list(INDEX_CONFIGS.keys()), default=DEFAULT_INDEX,
                    help="目标指数：NDX（纳斯达克100）或 SPX（标普500），默认 NDX")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-social", action="store_true")
    ap.add_argument("--top-insiders", type=int, default=12, help="聚合内部人交易的权重股数量")
    args = ap.parse_args()

    # ★ 2026-10-11（O3）：与 collect.py 同一道口径守卫（实现在 collect.py，此处不复制）
    if args.date is None:
        args.date = today_eastern()
    if not date_caliber_guard(args.date, args.allow_stale_date):
        return 2

    t0 = time.time()
    print(f"[指数证据采集] {args.index}  基准日 {args.date}\n")
    try:
        res = collect_index(args.date, args.lookback, not args.no_news, not args.no_social,
                            args.top_insiders, args.index)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 采集异常 {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    print(f"  [6/6] 汇总完成，用时 {time.time()-t0:.1f}s")
    ok = sum(1 for v in res["health"].values() if v == "ok")
    print(f"\n  ✓ 通道 {ok}/{len(res['health'])} 成功")
    bad = [k for k, v in res["health"].items() if v in ("fail", "unavailable", "error")]
    if bad:
        print(f"  ⚠ 不可用: {', '.join(bad)}")
    print(f"  证据包: {res['md']}")
    print(f"  结构化: {res['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
