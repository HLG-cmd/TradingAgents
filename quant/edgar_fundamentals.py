# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/edgar_fundamentals.py
"""SEC EDGAR 时点基本面（point-in-time fundamentals）—— 让 80% 的权重变得可回测。

━━━ 为什么需要它 ━━━
``yf.Ticker().info`` 只提供**当前快照**：今天的 ROE、今天的 PE，没有任何历史序列。
所以「2022 年这套公式赚不赚钱」根本无法验证 —— 这正是此前 SCREENER.md 里
那句「80% 的权重永远无法验证」的由来。

━━━ 为什么 EDGAR 能解决 ━━━
SEC 官方 XBRL ``companyfacts`` 接口每条记录都带 ``filed``（申报日）。
「在 T 日市场知道什么」= 所有 ``filed <= T`` 的记录里 ``end`` 最晚的那条。
配合 ``load_ohlcv`` 的历史价格，PE / ROE / 净利率 / 营收增速
全部可用**当时真实申报的数据**严格重建。

━━━ 三个必须避开的坑（均由实测发现，勿删注释）━━━

1. **利润表科目是「区间值」，必须用 ``start`` 判时长。**
   同一份 10-Q 里，同一个 ``end`` 会同时出现「单季（约 90 天）」与
   「年初至今累计（约 180/270 天）」两条记录，``fp`` 都是 ``Q3``。
   若只按 ``end`` 去重再滚动求和，会把累计值当季度值 ——
   实测 AAPL 的 TTM EPS 因此虚高到 14.92（真实约 6 美元）。
   ⇒ 流量类科目（营收/净利/EPS）一律按时长过滤：季度 80~100 天、年度 340~400 天。
   存量类科目（净资产/总资产）是**时点值**，没有 ``start``，不做时长过滤。

2. **回退链要按「覆盖最新」选，不是按「第一个有数据」。**
   同一概念各公司换用过多个 tag。若取链上第一个有数据的，会拿到公司
   早已停用的旧 tag —— 实测 NVDA 的营收因此四年卡在 269 亿（真实已超 1200 亿）。
   ⇒ 先算出每个候选 tag 在 ``as_of`` 前能取到的最晚 ``end``，取最晚者。

3. **EPS / 股本 与复权价格不在同一口径（拆股会错）。**
   EDGAR 的值是**申报时原值**，而 ``load_ohlcv`` 的价格是**拆股复权后**的。
   NVDA 2024 年 10:1 拆股 ⇒ 拆股前的口径会整体差 10 倍。

   ⚠️ 注意：**「市值 ÷ 净利润」并不能自动免疫** ——
   申报股本是拆股前原值，与复权价相乘反而放大偏差。
   实测未修正时 NVDA 2022-12 的 PE 为 6.6（真实约 66）。
   ⇒ 正确关系：``市值 = 复权价 × 申报股本 × F``，
     其中 ``F`` = **该时点之后**发生的累计拆股倍数（由 yfinance splits 提供）。
     修正后 NVDA 2022-12 得 66，与真实一致。

━━━ 设计取舍 ━━━
**本模块只服务于回测，不用于实时筛选。**
实时筛选继续用 ``yf.Ticker().info``（1 次请求拿当前值）；
EDGAR 每家公司约 4 MB，100 家 ≈ 400 MB。分工：
    实时当前值 -> .info     |     历史时点值 -> EDGAR

━━━ 已知边界 ━━━
- 仅美股（含在美上市外国公司；其 20-F 标签体系可能不同，链上已尽量覆盖）
- SEC 限速约 10 请求/秒，且**强制要求带联系方式的 User-Agent**
- 首次拉取需下载全部公司 facts，约 400 MB、耗时数分钟；之后按天缓存

用法：
    from edgar_fundamentals import get_point_in_time, pe_at, preload
    preload(["AAPL", "NVDA"])
    p = get_point_in_time("AAPL", "2022-06-30")   # 时点基本面
    pe = pe_at("AAPL", "2022-06-30", price=127.65*4)  # 时点 PE（传入复权价亦可）
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path

import requests

# ── 数据源配置 ────────────────────────────────────────────────────────────
CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# SEC 强制要求 User-Agent 含联系信息，否则 403。实测（2026-09-16）：
#   ✗ 'python-requests/2.34'                                    纯库名 -> 403
#   ✗ 'TradingAgents research (contact: set SEC_USER_AGENT env)' 占位符式 -> 403
#   ✓ 'TradingAgents research someone@qq.com'                   名称+邮箱 -> 200
#   ✓ 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'               浏览器式 -> 200
#
# SEC **不校验邮箱域名** —— 它要的是「出问题能找到人」，QQ/163 等邮箱完全可用。
# 优先从项目 .env 读取（该文件已被 .gitignore 忽略）。
# 请设成：SEC_USER_AGENT=你的名字 your@qq.com
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT", "TradingAgents research admin@example.com")
SEC_TIMEOUT = 30
MIN_REQUEST_INTERVAL = 0.15      # SEC 限速 ~10 req/s，留余量

CACHE_DIR = Path(os.path.expanduser("~")) / ".tradingagents" / "edgar"

# ── 缓存策略（2026-09-16 修正，原设计会撑爆磁盘）────────────────────────
# ❌ 原实现按**天**缓存 facts：`facts_<TICKER>_<YYYY-MM-DD>.json`。
#    而每套是 342 MB（102 家）⇒ 每天运行一次就多占 342 MB：
#      7 天 2.4 GB / 30 天 10 GB / 365 天 123 GB。
#    但 XBRL facts **只在季报/年报发布时变化** —— 按天缓存毫无意义。
# ✅ 改为按**季度**命名：满仓 342 MB，季度翻页时自然失效（一次性重下 146 秒）。
#    这正好与本项目文档里「每季度预热一次」的节奏一致。
CIK_TTL_DAYS = 30          # CIK 映射表很小（约 800 KB），按月刷新即可


def _quarter_key(d: dt.date | None = None) -> str:
    d = d or dt.date.today()
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _facts_cache_path(ticker: str) -> Path:
    tk = ticker.strip().upper().replace(".", "-")
    return CACHE_DIR / f"facts_{tk}_{_quarter_key()}.json"


def prune_cache(verbose: bool = True) -> int:
    """删除非当前季度的 facts 缓存。返回删除的文件数。

    为什么需要：季度翻页后旧文件不会再被读取，但会一直占盘。
    实测每套 342 MB，留 4 个季度就是 1.4 GB —— 该清。
    """
    if not CACHE_DIR.exists():
        return 0
    keep = _quarter_key()
    removed, freed = 0, 0
    for f in CACHE_DIR.glob("facts_*.json"):
        # 文件名形如 facts_<TICKER>_<YYYY>Q<n>.json；最后一段是季度键
        parts = f.stem.split("_")
        if len(parts) >= 3 and parts[-1] != keep:
            try:
                freed += f.stat().st_size
                f.unlink()
                removed += 1
            except OSError:
                pass
    if verbose and removed:
        print(f"[EDGAR] 已清理 {removed} 个过期季度缓存，释放 {freed/1024/1024:.1f} MB"
              f"（保留 {keep}）")
    return removed

# ── 时长阈值（天）────────────────────────────────────────────────────────
DUR_QUARTER = (80, 100)
DUR_ANNUAL = (340, 400)

# ── XBRL 概念回退链（顺序 = 优先级；实际选择还会按「覆盖最新」重排）──────
CONCEPT_CHAINS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "IncomeLossFromContinuingOperations",
    ],
    # 存量（时点）科目
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    # 股本：优先用申报封面页的期末股本（含拆股前原值，PE 口径需要）
    "shares": [
        "EntityCommonStockSharesOutstanding",       # dei 分类
        "CommonStockSharesOutstanding",             # us-gaap
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
}
FLOW_CONCEPTS = {"revenue", "net_income"}          # 需时长过滤
INSTANT_CONCEPTS = {"equity", "assets", "liabilities", "shares"}

# ── 缓存瘦身 ─────────────────────────────────────────────────────────────
# companyfacts 原始响应含 **500~627 个 tag**（每家约 3.3 MB），
# 而本模块只用到 17 个。实测压缩比 **15.6x**：341.5 MB -> 约 22 MB。
#
# 为什么不做"任务结束就清缓存"：清了下次要重下 146 秒。
# 22 MB 的稳态占用基本无感，保留它让二次运行从 146s 降到 3s。
# 若确实要清，用 cleanup_cache()。
_NEEDED_TAGS = {t for tags in CONCEPT_CHAINS.values() for t in tags}
# 只保留抽取逻辑真正读取的字段（见 _series），丢掉 accn / frame 等冗余
_SLIM_FIELDS = ("start", "end", "val", "filed", "form", "fy", "fp")


def slim_facts(data: dict) -> dict:
    """把 companyfacts 裁到只含用得到的 tag 与字段。

    ⚠️ 副作用：裁剪后**无法再用到 CONCEPT_CHAINS 之外的 tag**。
    如需新增概念，请在 CONCEPT_CHAINS 里加，然后删缓存重新拉。
    """
    out: dict = {"cik": data.get("cik"), "entityName": data.get("entityName"),
                 "facts": {}}
    for tax, node in (data.get("facts") or {}).items():
        kept_tags = {}
        for tag, body in (node or {}).items():
            if tag not in _NEEDED_TAGS:
                continue
            units = body.get("units") or {}
            kept_units = {
                u: [{k: r.get(k) for k in _SLIM_FIELDS if k in r} for r in rows]
                for u, rows in units.items() if rows
            }
            if kept_units:
                kept_tags[tag] = {"units": kept_units}
        if kept_tags:
            out["facts"][tax] = kept_tags
    return out

_last_request = [0.0]


def _throttle() -> None:
    gap = time.time() - _last_request[0]
    if gap < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - gap)
    _last_request[0] = time.time()


def _get(url: str) -> requests.Response:
    _throttle()
    resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT,
                                      "Accept-Encoding": "gzip, deflate"},
                        timeout=SEC_TIMEOUT)
    if resp.status_code in (401, 403):
        raise PermissionError(
            f"SEC 拒绝了当前 User-Agent（HTTP {resp.status_code}）。\n"
            f"  当前值: {SEC_USER_AGENT!r}\n"
            f"  SEC 要求 UA 含真实联系信息；纯库名（python-requests）与\n"
            f"  看起来未填写的占位符都会被判 403。\n"
            f"  修法: set SEC_USER_AGENT=\"YourName your@email.com\"")
    resp.raise_for_status()
    return resp


# ── CIK 映射 ─────────────────────────────────────────────────────────────

def load_cik_map(force: bool = False) -> dict[str, str]:
    """{TICKER: CIK(10位零填充)}。全市场一张表。

    单一文件 + TTL 刷新（不再按天命名——那样一年会留下 365 份 800 KB 的副本）。
    """
    p = CACHE_DIR / "cik_map.json"
    if not force and p.exists():
        age_days = (time.time() - p.stat().st_mtime) / 86400
        if age_days <= CIK_TTL_DAYS:
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    raw = _get(CIK_MAP_URL).json()
    out: dict[str, str] = {}
    for item in raw.values():
        tk = str(item.get("ticker", "")).strip().upper().replace(".", "-")
        cik = str(item.get("cik_str", "")).strip()
        if tk and cik:
            out.setdefault(tk, cik.zfill(10))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


def cik_for(ticker: str, cik_map: dict[str, str] | None = None) -> str | None:
    m = cik_map if cik_map is not None else load_cik_map()
    return m.get(ticker.strip().upper().replace(".", "-"))


# ── companyfacts ─────────────────────────────────────────────────────────

def fetch_facts(ticker: str, force: bool = False) -> dict:
    """拉取并缓存某公司的 XBRL 事实（**已瘦身**，约 260 KB）。

    缓存策略：
    - 按**季度**命名（不按天 —— 按天会让磁盘按 342 MB/天 增长）
    - 落盘前先 ``slim_facts()`` 裁剪（15.6x 压缩，全量 22 MB）
    """
    tk = ticker.strip().upper().replace(".", "-")
    p = _facts_cache_path(tk)
    if not force and p.exists():
        try:
            cached = json.loads(p.read_text(encoding="utf-8"))
            # 兼容未经瘦身的旧缓存（无 "slim" 标记则就地瘦身重写）
            if cached.get("slim"):
                return cached
            slim = slim_facts(cached)
            slim["slim"] = True
            try:
                p.write_text(json.dumps(slim), encoding="utf-8")
            except Exception:
                pass
            return slim
        except Exception:
            pass
    cik = cik_for(tk)
    if not cik:
        raise ValueError(f"EDGAR 中找不到 {tk} 的 CIK")
    raw = _get(FACTS_URL.format(cik=cik)).json()
    data = slim_facts(raw)
    data["slim"] = True
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return data


# ── 时点抽取 ─────────────────────────────────────────────────────────────

def _facts_ns(facts: dict, taxonomy: str) -> dict:
    return (facts.get("facts") or {}).get(taxonomy) or {}


def _units_lookup(facts: dict, tag: str) -> tuple[dict, str] | None:
    """在 us-gaap / dei 两个分类里找 tag，返回 (unit_map, taxonomy)。"""
    for tax in ("us-gaap", "dei"):
        node = _facts_ns(facts, tax).get(tag)
        if node and node.get("units"):
            return node["units"], tax
    return None


def _series(facts: dict, tag: str, unit: str) -> list[dict]:
    """抽出带 start/end/duration 的记录列表。filed 是时点键。"""
    hit = _units_lookup(facts, tag)
    if not hit:
        return []
    units, _ = hit
    rows = units.get(unit) or []
    if not rows:                      # 单位名有时不同（如 USD/shares vs USD）
        for u, rr in units.items():
            if rr:
                rows = rr
                break
    out = []
    for r in rows:
        if not r.get("filed") or not r.get("end") or r.get("val") is None:
            continue
        start, end = r.get("start"), r["end"]
        dur = None
        if start:
            try:
                dur = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
            except ValueError:
                dur = None
        out.append({"filed": r["filed"], "start": start, "end": end,
                    "val": r["val"], "form": r.get("form", ""),
                    "fy": r.get("fy"), "fp": r.get("fp"), "dur": dur})
    return out


def _known(series: list[dict], as_of: str) -> list[dict]:
    """只用 filed <= as_of 的记录 —— 这是时点纪律的核心。"""
    return [r for r in series if r["filed"] <= as_of]


def _dedupe_by_end(rows: list[dict]) -> dict[str, dict]:
    """同一 end 多次申报时取**最近一次申报**（当时最新的认知）。"""
    best: dict[str, dict] = {}
    for r in rows:
        cur = best.get(r["end"])
        if cur is None or r["filed"] > cur["filed"]:
            best[r["end"]] = r
    return best


def _pick_series(facts: dict, concept: str, unit: str = "USD",
                 duration: tuple[int, int] | None = None,
                 as_of: str | None = None) -> tuple[str, list[dict]]:
    """按「在 as_of 前能覆盖到最新期间」选 tag，而非「链上第一个有数据的」。

    这是 bug #2 的修复：NVDA 的营收曾因取到旧 tag 而四年不变。
    """
    best_tag, best_rows, best_end = "", [], ""
    for tag in CONCEPT_CHAINS.get(concept, []):
        rows = _series(facts, tag, unit)
        if not rows:
            continue
        if duration is not None:
            rows = [r for r in rows if r["dur"] is not None
                    and duration[0] <= r["dur"] <= duration[1]]
            if not rows:
                continue
        if as_of:
            rows = _known(rows, as_of)
            if not rows:
                continue
        latest = max(r["end"] for r in rows)
        if latest > best_end:
            best_tag, best_rows, best_end = tag, rows, latest
    return best_tag, best_rows


def _latest_annual(facts: dict, concept: str, as_of: str, unit: str = "USD"):
    tag, rows = _pick_series(facts, concept, unit, DUR_ANNUAL, as_of)
    if not rows:
        return None, tag
    return _dedupe_by_end(rows)[max(r["end"] for r in rows)], tag


def _latest_instant(facts: dict, concept: str, as_of: str, unit: str = "USD"):
    tag, rows = _pick_series(facts, concept, unit, None, as_of)
    if not rows:
        return None, tag
    return _dedupe_by_end(rows)[max(r["end"] for r in rows)], tag


def _ttm(facts: dict, concept: str, as_of: str, unit: str = "USD") -> tuple[float | None, str]:
    """季度滚动求和。已按**时长**过滤，避免把年初至今累计值当季度值（bug #1）。"""
    tag, rows = _pick_series(facts, concept, unit, DUR_QUARTER, as_of)
    if len(_dedupe_by_end(rows)) < 4:
        return None, tag
    picked = sorted(_dedupe_by_end(rows).values(), key=lambda r: r["end"], reverse=True)[:4]
    span = (dt.date.fromisoformat(picked[0]["end"])
            - dt.date.fromisoformat(picked[-1]["end"])).days
    if not (250 <= span <= 400):      # 四季应跨约一年，否则说明期间不连续
        return None, tag
    return float(sum(r["val"] for r in picked)), tag


def _annual_growth(facts: dict, concept: str, as_of: str, unit: str = "USD"):
    tag, rows = _pick_series(facts, concept, unit, DUR_ANNUAL, as_of)
    if not rows:
        return None, tag
    ends = sorted(_dedupe_by_end(rows), reverse=True)
    if len(ends) < 2:
        return None, tag
    gap = (dt.date.fromisoformat(ends[0]) - dt.date.fromisoformat(ends[1])).days
    cur, prev = _dedupe_by_end(rows)[ends[0]]["val"], _dedupe_by_end(rows)[ends[1]]["val"]
    if not prev or not (300 <= gap <= 430):
        return None, tag
    return cur / prev - 1.0, tag


def _annual_chain(facts: dict, concept: str, as_of: str, years: int,
                  unit: str = "USD"):
    """取最近 ``years+1`` 个**连续年度**观测（相邻间隔须 300~430 天）。

    为什么必须校验间隔：EDGAR 里同一 concept 可能缺失某一年（改 tag、间断申报），
    直接取「最近 N 条」会把间隔两年的两条当成相邻年，算出虚高的增长率。
    宁可返回空，也不要返回一个错的增长率。
    """
    tag, rows = _pick_series(facts, concept, unit, DUR_ANNUAL, as_of)
    if not rows:
        return None, tag, []
    by_end = _dedupe_by_end(rows)
    ends = sorted(by_end, reverse=True)
    chain = [ends[0]]
    for e in ends[1:]:
        gap = (dt.date.fromisoformat(chain[-1]) - dt.date.fromisoformat(e)).days
        if not (300 <= gap <= 430):
            break          # 序列不连续 ⇒ 停止，不再往后凑
        chain.append(e)
        if len(chain) == years + 1:
            break
    return tag, by_end, chain


def _annual_growth_n(facts: dict, concept: str, as_of: str, years: int = 3,
                     unit: str = "USD"):
    """N 年**营收 CAGR**（几何平均年增），比单期同比抗并购台阶与周期跳升。

    与 :func:`_annual_growth` 的区别：后者是「最新年 / 前一年 − 1」的**单期同比**，
    一起并购并表就会台阶式跳升；本函数跨 ``years`` 年求几何平均，
    把一次性台阶摊薄到多年，因而**更能反映内生增长**。
    """
    tag, by_end, chain = _annual_chain(facts, concept, as_of, years, unit)
    if len(chain) < years + 1:
        return None, tag, len(chain) - 1
    newest = by_end[chain[0]]["val"]
    oldest = by_end[chain[-1]]["val"]
    if not oldest or oldest <= 0 or newest is None or newest <= 0:
        return None, tag, len(chain) - 1
    span_years = (dt.date.fromisoformat(chain[0])
                  - dt.date.fromisoformat(chain[-1])).days / 365.25
    if span_years < years * 0.8:      # 实际跨度太短 ⇒ 不是真的 N 年
        return None, tag, len(chain) - 1
    return (newest / oldest) ** (1.0 / span_years) - 1.0, tag, len(chain) - 1


def _restrict_revenue_tag(facts: dict, tag: str) -> dict:
    """返回一份「只剩指定 revenue tag」的 facts 浅副本（其余概念不动）。

    这样下游 ``_ttm`` / ``_annual_growth`` / ``_annual_growth_n`` **不需要改签名**
    就会自动用上这个 tag —— 它们都是沿 ``CONCEPT_CHAINS`` 找营收的。
    """
    top = dict(facts)
    ns = dict(facts.get("facts", {}))
    us = dict(ns.get("us-gaap", {}))
    for t in CONCEPT_CHAINS["revenue"]:
        if t != tag:
            us.pop(t, None)
    ns["us-gaap"] = us
    top["facts"] = ns
    return top


def _plausible_revenue_tag(facts: dict, as_of: str, unit: str = "USD") -> str | None:
    """挑一个「与净利相容」的营收 tag；无可选则返回 None（不干预）。

    **背景（2026-09-20 实测）**：``RevenueFromContractWithCustomer*`` 对**银行**是错的口径 ——
    它只覆盖手续费等合同收入，**不含净利息收入**，于是出现「净利 > 营收」这种
    经济上不可能、却数值自洽的结果（实测 CATY/WAL/COLB/EBC/CFG 的净利率高达 120%~584%，
    并因此污染营收增长率）。银行正确口径是 ``Revenues`` 或 ``RevenuesNetOfInterestExpense``。

    ⇒ 沿链依次试，选第一个满足 ``net_income_ttm <= revenue_ttm`` 的。
    净利不可得或为负时**不做干预**（无从判据，避免误伤亏损公司）。
    """
    ni_ttm, _ = _ttm(facts, "net_income", as_of, unit)
    if ni_ttm is None or ni_ttm <= 0:
        return None

    def _rev_ttm_of(tag: str):
        hit = _units_lookup(facts, tag)
        if not hit:
            return None
        probe = {"facts": {"us-gaap": {tag: {"units": hit[0]}}}}
        v, _ = _ttm(probe, "revenue", as_of, unit)
        return v if (v is not None and v > 0) else None

    # 1) **默认选择（按「覆盖最新期间」）若已相容，原样保留** ——
    #    这一步不可省：链序 ≠ 最佳选择，按链序重挑会把本来正确的标的换坏
    #    （实测 JPM 净利率被从 33.8% 换成 70.7%）。
    default_tag, _ = _pick_series(facts, "revenue", unit, DUR_QUARTER, as_of)
    if default_tag:
        v = _rev_ttm_of(default_tag)
        if v is not None and ni_ttm <= v:
            return default_tag

    # 2) 不相容 ⇒ 沿链找替代口径（银行的合同收入 → Revenues / 含净利息收入口径）
    for tag in CONCEPT_CHAINS["revenue"]:
        if tag == default_tag:
            continue
        v = _rev_ttm_of(tag)
        if v is not None and ni_ttm <= v:
            return tag
    return None      # 全链都不相容 ⇒ 不干预，由调用方按 margin 标记


# ── 公开接口 ─────────────────────────────────────────────────────────────

def _ttm_is_suspect(facts: dict, concept: str, as_of: str, ttm_val: float | None,
                    unit: str = "USD") -> tuple[bool, str]:
    """检测**伪 TTM**：滚动窗口把「上一财年 Q4」与「本财年前三季度」拼在一起（铁律 38）。

    ## 为什么需要这个断言（2026-10-08 血泪）

    ``_ttm`` 的实现是「取最近 4 个季度」求和。这在多数公司没问题，
    但当季度序列**恰好停在某财年边界**时会拼出一个**伪 TTM**：

        实测 WDC（as_of=2026-10-06）：返回 net_income_ttm = 6,511.0M
        实为  6,229（FY2026 前 9 个月）+ 282（FY2025 Q4）
        —— 而 FY2026 全年 9,424M（filed 2026-08-14）当时**已经申报**了。

    看起来完全合法（就是个四位数的金额），只有反推才能发现它无视了更新的年报。

    ## 判据（★ 试过三版才对 —— 全过程记录在案，别再退回去）

    **已采用**：TTM 窗口里**最老的那个季度期末，恰好等于「上一个财年的期末」**。

    为什么这是正确的判别式 —— 它刻画的是**拼接的机械特征**：
    正常的 TTM 是「最近 4 个自然季度」，其最老一个的期末落在**财年中间**（随机）；
    而拼接产生的 TTM 其最老一个恰是**上一财年的 Q4**，期末**精确等于**财年末
    —— 因为它就是被人为拿来补齐 4 个季度的。

        实测 WDC：窗口 = [2025-06-27, 2025-10-03, 2026-01-02, 2026-04-03]
                  最老 = 2025-06-27 = FY2025 期末 ✅ 命中 ⇒ 判可疑
        对比 MSFT/GOOG/NVDA/AAPL 共 12 个 as-of 快照：最老季度均落在财年中间
                  ⇒ 全部 12/12 正确判为正常（假阳性为零）

    ⚠️ **前三版失败尝试（每一版都实测证伪，不要重蹈）**：
    - ①「窗口里同时存在财年前与财年后的季度」⇒ WDC 窗口中除起点外**全是财年后**的季度，
      该条件恒为假 ⇒ **永远不触发**（假阴性 100%）。
    - ②「窗口起点早于财年起点」⇒ WDC 只早 **6 天**（52/53 周财年的正常漂移量级），
      而 MSFT/GOOG/NVDA 也会同样抖动 ⇒ **假阳性满天飞**。
    - ③「最新季度末早于最新财年末」⇒ 实测**所有**公司都满足（EDGAR 年报 filed 天然晚于
      最后一个 10-Q）⇒ 同样假阳性（MSFT/GOOG/NVDA/AAPL 共 4 例误报）。
    - ⇒ 教训：**「日期先后」类判据在财年边界上噪声极大**；要抓的是**精确相等**
      这个机械特征，不是「早/晚」这种软关系。

    ## 返回
    ``(suspect, reason)`` —— 可疑时 reason 说明是哪两个财年被拼在一起。
    """
    if ttm_val is None:
        return False, ""
    tag, rows = _pick_series(facts, concept, unit, DUR_QUARTER, as_of)
    by_end = _dedupe_by_end(rows)
    if len(by_end) < 4:
        return False, ""
    picked = sorted(by_end.values(), key=lambda r: r["end"], reverse=True)[:4]
    oldest_q_end = picked[-1]["end"]

    # 年度序列：最新财年 + 上一财年
    a_tag, a_rows = _pick_series(facts, concept, unit, DUR_ANNUAL, as_of)
    ann = _dedupe_by_end(a_rows)
    if len(ann) < 2:
        return False, ""
    ann_ends = sorted(ann, reverse=True)
    latest_annual_end, prev_annual_end = ann_ends[0], ann_ends[1]

    # ★ 判据：窗口最老季度期末 **精确等于** 上一财年期末 ⇒ 人为拼接的机械特征。
    if oldest_q_end == prev_annual_end:
        return True, (
            f"TTM 拼接：窗口最老季度期末 {oldest_q_end} 恰为上一财年（FY 止于 "
            f"{prev_annual_end}）的 Q4，与最新财年（FY 止于 {latest_annual_end}，"
            f"值 {ann[latest_annual_end]['val']:,.0f}）的前三季度凑成 4 季 ⇒ "
            f"疑似伪 TTM，且最新财年数据已被晾在一边"
        )

    return False, ""


def get_point_in_time(ticker: str, as_of: str, facts: dict | None = None) -> dict:
    """在 ``as_of``（YYYY-MM-DD）当天，用**当时已申报**的数据计算基本面。

    缺失项一律为 None，绝不填默认值冒充数据。
    """
    f = facts if facts is not None else fetch_facts(ticker)
    out: dict = {"ticker": ticker.strip().upper().replace(".", "-"), "as_of": as_of}

    # 营收科目先做「与净利相容」校验：银行若被取到合同收入口径，会出现净利 > 营收
    # （见 _plausible_revenue_tag）。挑到相容 tag 后，下游营收/增速/CAGR 全部跟随。
    rev_pick = _plausible_revenue_tag(f, as_of)
    f_rev = _restrict_revenue_tag(f, rev_pick) if rev_pick else f

    # 流量类：TTM 优先（更贴近当期），并保留年度值
    ni_ttm, ni_tag = _ttm(f, "net_income", as_of)
    rev_ttm, rev_tag = _ttm(f_rev, "revenue", as_of)
    ni_a, ni_a_tag = _latest_annual(f, "net_income", as_of)
    rev_a, rev_a_tag = _latest_annual(f_rev, "revenue", as_of)

    out["net_income_ttm"], out["net_income_tag"] = ni_ttm, ni_tag or ni_a_tag
    out["revenue_ttm"], out["revenue_tag"] = rev_ttm, rev_tag or rev_a_tag

    # ★★ 2026-10-08：伪 TTM 断言（铁律 38）—— 不许把「跨财年拼凑」的数当 TTM 交付。
    #   实测 WDC：net_income_ttm 返回 6,511.0M，实为 6,229（FY2026 前 9 月）+ 282（FY2025 Q4），
    #   无视了 2026-08-14 已申报的 FY2026 年报。下游拿它算 PE 会把估值算错一倍。
    #   处理原则：**宁可降级到年度口径，也不给一个看着正常的错数**（与 `_annual_chain`
    #   的「宁可返回空，也不要返回一个错的增长率」同一立场）。
    ni_suspect, ni_why = _ttm_is_suspect(f, "net_income", as_of, ni_ttm)
    rev_suspect, rev_why = _ttm_is_suspect(f_rev, "revenue", as_of, rev_ttm)
    out["ttm_suspect"] = bool(ni_suspect or rev_suspect)
    out["ttm_suspect_reason"] = "; ".join(x for x in (ni_why, rev_why) if x) or None
    if out["ttm_suspect"]:
        # 降级：弃用可疑 TTM，改用年度值（并把 basis 标成 annual + suspect）
        out["net_income_ttm"], out["revenue_ttm"] = None, None
        ni_ttm, rev_ttm = None, None

    out["net_income"] = ni_ttm if ni_ttm is not None else (ni_a["val"] if ni_a else None)
    out["revenue"] = rev_ttm if rev_ttm is not None else (rev_a["val"] if rev_a else None)
    if out["ttm_suspect"]:
        out["basis"] = "annual(ttm_suspect)"
    else:
        out["basis"] = "ttm" if (ni_ttm is not None and rev_ttm is not None) else "annual"
    out["net_income_filed"] = (ni_a or {}).get("filed")
    out["revenue_filed"] = (rev_a or {}).get("filed")

    # 存量类：时点值
    for concept in ("equity", "assets", "liabilities", "shares"):
        rec, tag = _latest_instant(f, concept, as_of,
                                   unit="shares" if concept == "shares" else "USD")
        out[concept] = rec["val"] if rec else None
        out[f"{concept}_tag"] = tag or None
        out[f"{concept}_end"] = rec["end"] if rec else None

    # 派生指标
    ni, eq, rev = out["net_income"], out["equity"], out["revenue"]
    out["roe"] = (ni / eq) if (ni is not None and eq not in (None, 0)) else None
    out["margin"] = (ni / rev) if (ni is not None and rev not in (None, 0)) else None
    out["revenue_growth"], out["revenue_growth_tag"] = _annual_growth(f_rev, "revenue", as_of)

    # 多年 CAGR：抗「并购并表台阶」与「周期跳升」的增长率（见 _annual_growth_n）
    for n in (3, 5):
        cagr, tag_n, levels = _annual_growth_n(f_rev, "revenue", as_of, n)
        out[f"revenue_cagr_{n}y"] = cagr
        out[f"revenue_cagr_{n}y_tag"] = tag_n
        out[f"revenue_cagr_{n}y_levels"] = levels      # 实际用上的年度观测数

    # 口径可判定性：净利率 > 100% ⇒ 营收口径仍不相容（全链都试过仍不行），
    # 下游必须**拒绝**用它的增速，而不是把坏值当数据。
    out["revenue_tag_implausible"] = bool(out["margin"] is not None and out["margin"] > 1.0)
    return out


_SPLIT_CACHE: dict[str, "object"] = {}


def cumulative_split_factor(ticker: str, as_of: str) -> float:
    """``as_of`` **之后**发生的累计拆股倍数 F。

    为什么需要：EDGAR 的股本/EPS 是申报时原值，而价格是拆股复权后的。
    要把两者放回同一口径，必须补回拆股因子。
    yfinance 的 ``splits`` 给出 (日期 -> 比例)，比例 10.0 表示 10:1 拆股。
    取不到时返回 1.0（不调整），并在结果里由调用方可通过 note 察觉异常。
    """
    tk = ticker.strip().upper().replace(".", "-")
    if tk in _SPLIT_CACHE:
        s = _SPLIT_CACHE[tk]
    else:
        try:
            import yfinance as yf
            s = yf.Ticker(tk).splits          # pandas Series
        except Exception:
            s = None
        _SPLIT_CACHE[tk] = s
    # 注意：不能用 `if not s` —— pandas Series 的真值判断会抛
    # 「The truth value of a Series is ambiguous」
    if s is None or len(s) == 0:
        return 1.0
    f = 1.0
    try:
        for ts, ratio in s.items():
            if str(ts)[:10] > as_of and ratio and float(ratio) > 0:
                f *= float(ratio)
    except Exception:
        return 1.0
    return f


def market_cap_at(ticker: str, as_of: str, price: float,
                  facts: dict | None = None) -> float | None:
    """时点市值 = 复权价 × 申报股本 × 该时点之后的累计拆股倍数。

    ``price`` 必须是**复权价**（``load_ohlcv`` 的 Close）。详见模块头部 bug #3。
    """
    out = get_point_in_time(ticker, as_of, facts)
    sh = out.get("shares")
    if sh in (None, 0):
        return None
    return price * sh * cumulative_split_factor(ticker, as_of)


def pe_at(ticker: str, as_of: str, price: float,
          facts: dict | None = None) -> tuple[float | None, str]:
    """时点 PE = 市值 ÷ 净利润。

    **不要用 价格 ÷ EDGAR 的 EPS** —— 复权价与原值 EPS 不同口径，拆股后会错
    （见模块头部 bug #3）。这里用市值口径并补回拆股因子。

    返回 (pe, 说明)。亏损或数据缺失返回 (None, 原因)。
    """
    out = get_point_in_time(ticker, as_of, facts)
    ni = out.get("net_income")
    sh = out.get("shares")
    if sh in (None, 0):
        return None, "缺申报股本"
    if ni is None:
        return None, "缺净利润"
    if ni <= 0:
        return None, "亏损不计 PE"          # 与 screener_engine 口径一致
    f = cumulative_split_factor(ticker, as_of)
    return (price * sh * f) / ni, f"{out.get('basis', '')}·拆股因子{f:g}"


# ── 预热 ─────────────────────────────────────────────────────────────────

def preload(tickers: list[str], verbose: bool = True) -> dict[str, str]:
    """预热 CIK 映射与 facts 缓存。返回 {ticker: 状态}。

    结束时自动清理非当前季度的缓存（否则旧季度会一直占盘，每套 342 MB）。
    """
    load_cik_map()
    status: dict[str, str] = {}
    for i, tk in enumerate(tickers, 1):
        try:
            fetch_facts(tk)
            status[tk] = "ok"
            if verbose:
                print(f"  [{i}/{len(tickers)}] {tk} ✓")
        except Exception as exc:  # noqa: BLE001
            status[tk] = f"{type(exc).__name__}: {str(exc)[:60]}"
            if verbose:
                print(f"  [{i}/{len(tickers)}] {tk} ✗ {status[tk]}")
    prune_cache(verbose=verbose)
    return status


def cache_size_mb() -> float:
    """当前 EDGAR 缓存占用（MB）。用于监控磁盘增长。"""
    if not CACHE_DIR.exists():
        return 0.0
    return sum(f.stat().st_size for f in CACHE_DIR.rglob("*") if f.is_file()) / 1024 / 1024
