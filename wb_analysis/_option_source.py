# lifecycle: reusable
# created: 2026-10-16
# usage: from wb_analysis._option_source import fetch_chain; （库，被采集器 import）
"""期权链数据源适配器：把 **CBOE 官方延迟报价** 适配成 yfinance ``Ticker`` 的接口形状。

## 为什么需要它（问题）
`fetch_option_structure()` 依赖 yfinance 的期权链，而 yfinance 在**非交易时段**
（美东 09:30–16:00 之外）只返回**上一交易日的残留挂单** —— bid/ask 格式合法，
但 ``lastTradeDate`` 陈旧数周。实测（NDX 2026-10-16 轮，美东 08:29 盘前）：
扫 29 个到期日、387 个有双边报价合约，**最新成交距今 23.2 天、合格样本 0**
⇒ IV 等级 NONE ⇒ 期权维度整体不可用 ⇒ 结论被迫降级为条件式。

## 解法
**CBOE 官方延迟报价接口**（免密钥、robots.txt 未禁止）：

    https://cdn.cboe.com/api/global/delayed_quotes/options/<SYMBOL>.json

实测（2026-10-16）：
  · 单次返回 **万条级** 完整期权链（QQQ 10,954 条 / SPY 13,104 条 / NFLX 3,238 条）
  · 有双边报价覆盖率 **94.8%**，远月合约 **100%**（做市商持续报价链）
  · 含 ``iv`` / ``delta`` / ``gamma`` / ``vega`` / ``theta`` / ``rho`` / ``theo`` /
    ``open_interest`` / ``volume`` / ``last_trade_time``
  · 顶层含 ``current_price``（spot）与 ``iv30``（30 天 IV 指数）

**关键差异**：CBOE 发布的是**做市商报价链**，不依赖「该合约当天有没有成交」
⇒ 盘前/盘后也能拿到**完整的上一时段快照**。
已实证（`reports/_audit/2026-10-16_期权时段可用性实证.md`）：
只保留「上一交易日成交」的合约，**31 个到期日全部可算出 ATM IV**。

## 覆盖范围与边界（实测）
  ✅ 美股个股与主要 ETF：QQQ / SPY / NFLX / AAPL / TSLA / GOOG
  ❌ 指数符号（NDX / ^NDX）—— 指数本身无期权（**符合预期**）
  ❌ A 股 ETF —— 非美股
  ⚠️ 403 是**统一响应**，无法区分「无期权」与「代码错误」⇒ 一律登记为该标的无可用数据
  ⚠️ 该接口**不覆盖延长时段**（CBOE GTH 20:15–09:25 仅限 SPX/SPXW/XSP）；
     股票期权只在 09:30–16:00 交易 ⇒ 盘前拿到的最新成交必然止于**上一交易日**
  ⚠️ **接口不稳定**：实测 10 次连续请求 1 次 ConnectionError、单次实验曾 ConnectionReset
     ⇒ **必须重试**（本模块内置）
  ⚠️ 响应较慢：平均 **7.6 秒**（单次万条）

## 口径纪律（**最重要**）
CBOE 的 ``iv`` 与 ``delta`` 是**交易所模型**算的，与项目自建 BSM 反解**口径不同**：
  · spot 不同（CBOE 71.10 vs 项目 70.94，延迟 15 分钟所致）
  · **偏斜数值差异大**（同轮 2026-10-30：CBOE −0.62pp vs 项目 −4.24pp）——
    根因是样本数（3/3 vs 2/3）与 delta 定义
⇒ **不得把两个来源的偏斜值混用**。本适配器**统一透传 CBOE 口径**，
  并在返回值里带 ``source="cboe_delayed"``，供下游在证据包里声明。

## 用法
    from wb_analysis._option_source import fetch_chain, available
    if available("NFLX"):
        chain = fetch_chain("NFLX")   # 返回与 yfinance Ticker 同形的对象
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

#: CBOE 官方延迟报价端点（免密钥）。robots.txt 仅禁止 /book/ 与 volume_reports/。
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"

#: 重试预算。实测 10 次请求失败 1 次、且出现过 ConnectionReset ⇒ 必须重试。
MAX_TRIES = 4
BACKOFF_BASE = 2.0          # 秒；第 n 次退避 = BACKOFF_BASE * n
REQUEST_TIMEOUT = 40        # 秒；单次万条，实测最慢 9.91s，给足余量
_USER_AGENT = "Mozilla/5.0 (compatible; TradingAgents-research/1.0)"


class OptionSourceError(RuntimeError):
    """取数失败（含重试耗尽）。调用方应据此走「登记缺口」路径，而不是当成功。"""


def _get_json(sym: str) -> dict:
    """带重试地取一次 JSON。失败抛 OptionSourceError（**不返回空 dict**）。"""
    url = CBOE_URL.format(sym=sym.upper())
    last: Exception | None = None
    for attempt in range(1, MAX_TRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                if r.status != 200:
                    raise OptionSourceError(f"HTTP {r.status}")
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 4xx 多为「该标的无期权」⇒ 不值得重试
            if 400 <= e.code < 500:
                raise OptionSourceError(f"HTTP {e.code}（该标的无可用期权数据）") from e
            last = e
        except Exception as e:  # noqa: BLE001 （网络/超时/JSON 均重试）
            last = e
        if attempt < MAX_TRIES:
            time.sleep(BACKOFF_BASE * attempt)
    raise OptionSourceError(f"重试 {MAX_TRIES} 次仍失败：{type(last).__name__}: {last}")


#: CBOE option 符号：<ROOT><YYMMDD><C|P><strike*1000 补零 8 位>，如 NFLX261030C00072000
def parse_osym(osym: str) -> dict | None:
    """把 CBOE 内部符号解析成结构化字段。解析不出返回 None（不猜）。"""
    import re
    m = re.match(r"^([A-Z0-9]+?)(\d{6})([CP])(\d{8})$", osym)
    if not m:
        return None
    root, ymd, cp, k = m.groups()
    yy, mm, dd = int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6])
    return {
        "root": root,
        "expiry": f"20{yy:02d}-{mm:02d}-{dd:02d}",
        "cp": cp,
        "strike": int(k) / 1000.0,
    }


def available(sym: str) -> bool:
    """该标的是否有可用期权链（不抛异常，供调用方做前置判断）。"""
    try:
        d = _get_json(sym)
        return bool((d.get("data") or {}).get("options"))
    except OptionSourceError:
        return False


def _row_to_yf_shape(o: dict, meta: dict) -> dict | None:
    """把 CBOE 单条映射成 yfinance option_chain 的列名（尽力而为，不造字段）。"""
    p = parse_osym(o.get("option") or "")
    if not p:
        return None
    bid, ask = o.get("bid"), o.get("ask")
    mid = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
    return {
        "contractSymbol": o.get("option"),
        "strike": p["strike"],
        "lastPrice": o.get("last_trade_price"),
        # ★ 关键：CBOE 的 last_trade_time 是 ISO 字符串（如 2026-10-16T11:12:08），
        #   而 yfinance 是 lastTradeDate。上游过滤逻辑读的是后者 ⇒ 两者都提供。
        "lastTradeDate": o.get("last_trade_time"),
        "last_trade_time": o.get("last_trade_time"),
        "bid": bid,
        "ask": ask,
        "volume": o.get("volume"),
        "openInterest": o.get("open_interest"),
        "impliedVolatility": o.get("iv"),
        # 交易所模型 greeks（口径与项目自建 BSM 不同，见模块头「口径纪律」）
        "delta": o.get("delta"),
        "gamma": o.get("gamma"),
        "vega": o.get("vega"),
        "theta": o.get("theta"),
        "rho": o.get("rho"),
        "theo": o.get("theo"),
        "mid": mid,
        "_source": "cboe_delayed",
    }


@dataclass
class CboeChain:
    """与 yfinance ``Options`` 对象同形的最小适配体。

    只需实现 `fetch_option_structure` 实际用到的三个成员：
    `.options`（到期日列表）、`.option_chain(exp)`（单到期日链）、
    以及伪 ``fast_info`` / ``history``（供取 spot）。
    """
    symbol: str
    raw: dict
    source: str = "cboe_delayed"
    _by_exp: dict[str, tuple[list[dict], list[dict]]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        data = self.raw.get("data") or {}
        for o in (data.get("options") or []):
            p = parse_osym(o.get("option") or "")
            if not p:
                continue
            row = _row_to_yf_shape(o, data)
            if row is None:
                continue
            calls, puts = self._by_exp.setdefault(p["expiry"], ([], []))
            (calls if p["cp"] == "C" else puts).append(row)
        for _exp, (c, p) in self._by_exp.items():
            c.sort(key=lambda r: r["strike"])
            p.sort(key=lambda r: r["strike"])

    # --- yfinance 同形接口 ---
    @property
    def options(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_exp))

    def option_chain(self, expiry: str) -> Any:
        """返回 (calls, puts) 的 DataFrame 形状。无该到期日则返回空表（**不抛异常**）。"""
        import pandas as pd
        c, p = self._by_exp.get(str(expiry), ([], []))
        return _ChainFrame(pd.DataFrame(c), pd.DataFrame(p))

    @property
    def spot(self) -> float | None:
        """CBOE 快照的标的现价（ATM 选取与 BSM 反解的唯一基准）。

        ★ 2026-10-21 修（NFLX 10-20 盘后实测，**口径不匹配导致的静默失真**）：
          CBOE 的 ``current_price`` 是**含扩展时段的最后成交价**，而期权链的
          ``bid``/``ask`` 是**常规时段收盘快照**（本接口盘后返回上一时段快照）。
          两者混用 = 用「盘后已重定价的 spot」去反解「常规时段收盘的报价」——
          实测 NFLX 10-20：常规收盘 68.69，盘后因财报跌到 64.72（−5.78%），
          于是 ATM 按 64.72 选到远离真实价的合约，产出
          ATM_C IV 101.44% vs ATM_P 34.26%、25Δ 偏斜 **−41.78pp**（真实值应为正、量级 ~1pp），
          而 IV 等级仍报 FULL —— 典型的静默失败。

          ⇒ 判据：``current_price`` 与 ``close`` 偏离 >5% 时，视为**跨时段口径不匹配**
            （而非数据错误），改用 ``close`` 与期权报价的时点对齐；
            盘中两者本应接近（15 分钟延迟），此时保留 ``current_price``（更实时）。
            偏离超阈值时**打印警告**（不静默回退，便于审计）。
          ⚠️ 注意：``close`` 只是**期权反解的锚**，不代表「最新价」——盘后真实价格
            见证据包 §14（扩展时段），两者不可互相替代（铁律 4）。
        """
        data = self.raw.get("data") or {}
        try:
            cur = float(data["current_price"]) if data.get("current_price") is not None else None
            close = float(data["close"]) if data.get("close") is not None else None
        except (TypeError, ValueError):
            return None
        if cur is None or cur <= 0:
            return close
        if close is not None and close > 0 and abs(cur / close - 1.0) > 0.05:
            print(f"  ⚠ CBOE current_price {cur:.2f} 与 close {close:.2f} 偏离 "
                  f"{(cur / close - 1.0) * 100:+.1f}% > 5% ⇒ 改用 close 作 spot")
            return close
        return cur

    @property
    def iv30(self) -> float | None:
        v = (self.raw.get("data") or {}).get("iv30")
        return float(v) if v else None

    def market_time(self) -> str | None:
        return (self.raw.get("data") or {}).get("last_trade_time")


class _ChainFrame:
    """``option_chain()`` 的返回值：带 `.calls` / `.puts` 两个属性。"""

    def __init__(self, calls: Any, puts: Any) -> None:
        self.calls = calls
        self.puts = puts


def fetch_chain(sym: str) -> CboeChain:
    """取该标的的完整期权链（CBOE 口径）。失败抛 OptionSourceError。"""
    return CboeChain(symbol=sym.upper(), raw=_get_json(sym))
