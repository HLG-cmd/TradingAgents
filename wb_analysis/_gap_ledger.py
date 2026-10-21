# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py
"""数据缺口台账：把「缺什么」变成**可检查的结构化记录**，而不是散落在文字里的声明。

## 要解决的问题
数据缺失会**改变最终结论**，但现在只有一个松散约定「缺了就声明」。后果有三个：
  ① **看不见**：缺口埋在几万字证据包里，角色可能没读到；
  ② **不对等**：缺一个社交源（次要）和缺整个期权维度（决定性）被同等对待；
  ③ **不落地**：声明完就完了，没有人说「这个缺口把哪个判断挡掉了」「怎么补」「能不能用代理」。

## 解法
每一轮生成 `wb_analysis/evidence/<T>_<date>.gaps.json`，每条缺口登记六个字段：

| 字段 | 含义 |
|---|---|
| `label` | 缺口名（用于在简报里做字符串校验） |
| `cls` | **A** 上游真缺 / **B** 阈值误伤 / **C** 采集器 bug / **S** 时点不对（可重采） |
| `decisive` | **是否影响结论方向**（True ⇒ 阻止给出方向性评级） |
| `blocks` | 它把哪个判断挡掉了（写清"因此无法回答……"） |
| `remedy` | 怎么补（换时点 / 换口径 / 换来源 / 修代码） |
| `fallback` | 能用的代理（**必须注明口径不同**） |

分类依据是**证据包里的客观信号**（通道健康度的 `成功 N/M` 与非全绿列表、章节是否被上游扣留），
再用一张**人工维护的规则表**给出 decisive/blocks/remedy/fallback —— 规则表里没有的通道
一律标 `cls="?"` 并**在原样输出里提示人工归类**（不静默忽略）。

## 用法
  ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py NFLX 2026-09-21          # 生成台账
  ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py NFLX 2026-09-21 --check wb_analysis/drafts/NFLX_2026-09-21
                                                                                # 门禁：决定性缺口必须在简报里声明
"""
import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "wb_analysis" / "evidence"

# ── 规则表：通道 → 缺口属性（人工维护；新增通道必须在这里登记，否则报 "?" 要求归类）──
RULES: dict[str, dict] = {
    "option_iv": {"kw": ["option_iv", "期权维度", "IV 等级", "期权链"], "cls": "S", "decisive": True,
                  "blocks": "无法回答「期权市场如何为下行风险定价」——IV 与偏斜缺失使下行保护成本不可评估",
                  "remedy": "改在美东 09:30–16:00 重采；或接受该维度缺失并把结论降为条件式",
                  "fallback": "^VIX / ^VXN（**30 天前瞻 IV，口径不同，不可线性换算回个股**）"},
    "option_skew": {"kw": ["option_skew", "偏斜"], "cls": "S", "decisive": True, "blocks": "无法判断看跌/看涨的相对贵贱",
                    "remedy": "同 option_iv", "fallback": "无可靠代理"},
    "option_oi": {"kw": ["option_oi", "持仓量"], "cls": "A", "decisive": False, "blocks": "—（持仓量本来就不承担论证重量）",
                  "remedy": "不需修；继续只用成交量口径的 P/C", "fallback": "P/C（成交量口径）"},
    "option_quote_freshness": {"kw": ["option_quote_freshness", "报价新鲜度", "新鲜度", "残留快照"], "cls": "S", "decisive": True, "blocks": "无法确认期权报价是否为当日快照 ⇒ 任何 IV 读数都不可用",
                               "remedy": "改在美东盘中重采", "fallback": "同 option_iv"},
    "option_quote": {"cls": "S", "decisive": True, "blocks": "同上", "remedy": "改在美东盘中重采", "fallback": "同 option_iv"},
    "social:StockTwits": {"kw": ["StockTwits"], "cls": "A", "decisive": False,
                          "blocks": "情绪缺少「散户一侧」的独立来源 ⇒ 置信度上限压到 Low",
                          "remedy": "换时点/换标签重试；仍无则如实降置信度", "fallback": "Yahoo 新闻语气（口径不同）"},
    "social:Reddit": {"kw": ["Reddit"], "cls": "A", "decisive": False,
                      "blocks": "情绪只剩单一来源 ⇒ 置信度上限压到 Low",
                      "remedy": "该通道对机房 IP 常返回 403/空；不要为它反复重试",
                      "fallback": "Yahoo 新闻语气（口径不同）"},
    # ⚠️ remedy_file：补救产物一旦落地，该缺口即降级为「口径说明」而不再计为决定性缺口。
    #    否则台账会永远把「采集时缺过、事后已补齐」的通道报成未解决 —— 那会让简报被迫
    #    反复声明一个已不存在的问题（2026-10-03 NFLX 轮实测：§3 快照已由 supplement 补全，
    #    但台账仍报「决定性缺口 1 条」，导致 12 个角色文件里出现 40+ 处重复缺口声明）。
    "profile": {"kw": ["§3", "基本面快照", "快照被上游扣留", "vendor 拒答"], "cls": "A", "decisive": True,
                "blocks": "缺估值快照 ⇒ 市盈率/PB/市值/52 周区间全部不可用（除非另建替代源）",
                "remedy": "生成 `<T>_<date>.supplement.md`（直取当日快照 + 报表自算）",
                "fallback": "supplement（**与年报口径不同，须分别声明**）",
                "remedy_file": "supplement.md"},
    "verify_earnings_quality": {"cls": "?", "decisive": False, "blocks": "—", "remedy": "人工归类", "fallback": "—"},

    # ⚠️ 2026-10-09 NVDA 轮补登记：**「通道报 ok 但数值不自洽」这一类缺口此前完全漏检**。
    #    既有门禁（channel_health / _PLACEHOLDER_MARKERS / _audit_empty_sections）全部只看
    #    「调用是否成功、内容是否非空」，而 NVDA 的 Forward EPS 15.9146 = EPS(TTM) 7.91 的 2.01 倍
    #    （隐含未来 12M 净利 +99.2%，与其 SEC 自算 TTM 192,880M 严重冲突）—— 通道照报 ok。
    #    ⇒ clss 判为 **C**：不是上游没发布，也不是阈值误伤，而是 vendor 的**派生字段不可信**。
    #    ⇒ decisive=True：据此算出的 Forward PE 14.4x / PEG 0.28 是整份报告里最强的多头论据，
    #      一旦它为假，「NVDA 很便宜」这个结论就没有立足点 —— 与 UBER 轮「假便宜 PE」同类。
    #    ⇒ 自动检出由 `_verify_snapshot_consistency.py` 负责；本条目只提供六要素。
    "forward_eps": {"kw": ["forward_eps", "Forward EPS", "前瞻 EPS", "前瞻每股"], "cls": "C", "decisive": True,
                    "blocks": "无法确认「前瞻盈利」是否可信 ⇒ Forward PE / PEG 均不可用作估值锚点，"
                              "也就无法回答「当前股价相对其成长性是否便宜」",
                    "remedy": "用 SEC 已申报季报自算 TTM（本项目已有 `scripts/_oneoff/_verify_nvda_ttm.py` 范式）；"
                              "在拿到独立的分析师一致预期前，不得引用 forward 系列字段",
                    "fallback": "市值 / SEC 自算 TTM 净利、市值 / TTM 经营现金流（**口径不同，须分别声明**）"},
    "forward_pe": {"kw": ["forward_pe", "Forward PE", "前瞻市盈率", "PEG"], "cls": "C", "decisive": True,
                   "blocks": "同 forward_eps：前瞻市盈率与 PEG 均建立在未经验证的分母上",
                   "remedy": "同 forward_eps",
                   "fallback": "同为 SEC 自算 TTM 口径的倍数"},
    # ★ 2026-10-15 新增：币种不一致（外国发行人 ADR 的**根因级**失真）。
    #   实测 SKHY（SK 海力士美股 ADR）：`currency=USD` 而 `financialCurrency=KRW`
    #   ⇒ 快照把美元价格/市值与韩元财报混算，产出「净利率 85.6%」「Forward EPS 34.48」。
    #   它同时**解释了** forward_eps / forward_pe 两条可疑 ⇒ 判 C（vendor 派生字段不可信），非 A。
    "currency_mismatch": {"kw": ["currency_mismatch", "币种", "Financial Currency", "汇率", "混算"],
                          "cls": "C", "decisive": True,
                          "blocks": "快照把**价格/市值口径**与**财报口径**的两套币种混算 ⇒ 一切跨币种的倍数"
                                    "（PE / Forward PE / PEG / PB）与带币种的绝对金额"
                                    "（市值 / 营收 / 净利 / FCF / EBITDA）**全部不可信**，"
                                    "「贵 / 便宜」类论断在换算到同一币种之前不成立",
                          "remedy": "改用 §4 财务报表口径（同币种、内部自洽）自行复算；或先做汇率换算再计算倍数",
                          "fallback": "**纯比率**（毛利率 / 净利率 / 营业利润率 / ROE / ROA / 流动比率）—— "
                                      "分子分母同币种，比值与币种无关，可继续使用"},
    "etf:option_iv": {"kw": ["option_iv", "期权维度", "IV 等级", "期权链", "SPY 期权"], "cls": "S", "decisive": True,
                      "blocks": "无法回答「期权市场如何为下行风险定价」——IV 与偏斜缺失使下行保护成本不可评估",
                      "remedy": "改在美东 09:30–16:00 重采；或接受该维度缺失并把结论降为条件式",
                      "fallback": "^VIX / ^VXN（**30 天前瞻 IV，口径不同，不可线性换算**）"},
    "etf:option_skew": {"kw": ["option_skew", "偏斜"], "cls": "S", "decisive": True, "blocks": "无法判断看跌/看涨的相对贵贱",
                        "remedy": "同 etf:option_iv", "fallback": "无可靠代理"},
    # ⚠️ 2026-10-02 补登记：NDX 采集时报出 `etf:option_oi` 未归类（规则表漏了带前缀的 OI 通道，
    #    只有无前缀的 `option_oi`），导致台账标 cls="?" 并提示人工归类。
    #    语义与 `option_oi` 完全一致（持仓量不承担论证重量），只是通道名带 `etf:` 前缀。
    "etf:option_oi": {"kw": ["option_oi", "持仓量", "未平仓"], "cls": "A", "decisive": False,
                      "blocks": "—（持仓量本来就不承担论证重量）",
                      "remedy": "不需修；继续只用成交量口径的 P/C", "fallback": "P/C（成交量口径）"},
    "etf:option_quote_freshness": {"kw": ["option_quote_freshness", "报价新鲜度", "新鲜度", "残留快照"], "cls": "S", "decisive": True,
                                   "blocks": "无法确认期权报价是否为当日快照 ⇒ 任何 IV 读数都不可用",
                                   "remedy": "改在美东盘中重采", "fallback": "同 etf:option_iv"},
    # ⚠️ 2026-10-04 泛化：A 股 ETF 分「行业 ETF」（512400）与「策略/主题 ETF」（515100 红利低波）两类，
    #    两类均无场内期权。原措辞只提"行业ETF"，对策略 ETF 不准确，故改为"A股行业/策略 ETF"。
    # ⚠️ 2026-10-19 修正：原文案写死「A 股行业/策略 ETF 均无场内期权」，港股个股
    #    （0700.HK）跑出来也照报这句 —— 市场口径错配，会误导角色以为「港股没有股票期权」。
    #    改为市场无关表述，并分别给出 A 股/港股/美股的处置口径。
    "option_structure": {"kw": ["option_structure", "期权", "期权维度", "场内期权"], "cls": "A", "decisive": True,
                         "blocks": "无法回答「期权市场如何为下行风险定价」——本证据包无可用期权链数据，"
                                   "下行保护成本不可评估",
                         "remedy": "按市场处理：A 股个股/行业与策略 ETF 无场内期权（结构性缺失）；"
                                   "港股虽有股票期权但本采集器未接期权链；美股可改在美东盘中重采。"
                                   "三者均须把结论降为条件式",
                         "fallback": "A 股→宽基 ETF 期权 IV；港股→恒指波幅指数；美股→^VIX"
                                     "（**均为前瞻 IV，口径不同，不可线性换算**）+ 本标的历史 HV"},
    # ⚠️ 2026-10-04 新增（A 股 ETF 轮）：下面两条属「数据陈旧」而非「通道失败」——
    #    通道**取到了值**，但值的时间戳与基准日不符。登记它们是为了让下游看见，
    #    否则会被当成基准日当日值使用（铁律 26 快照不得脱离时间戳 / 铁律 32 缺口须被下游看见）。
    "macro_yield_stale": {"kw": ["macro_yield_stale", "国债收益率", "无风险利率"], "cls": "B", "decisive": False,
                          "blocks": "无风险利率不是基准日当日值 ⇒ ERP / 股息率溢价的绝对水平只能作量级参照，"
                                    "不可用于跨日或跨标的比较",
                          "remedy": "`cn_yield_curve` 为季度频率，滞后是常态；用最新可得值并**同时披露其数据日期**",
                          "fallback": "以最新可得值替代，口径注明「滞后 N 天」"},
    "etf_nav_unupdated": {"kw": ["etf_nav_unupdated", "净值未更新", "NAV"], "cls": "B", "decisive": False,
                          "blocks": "当日单位净值疑似未更新 ⇒ 由 NAV 与收盘价反算的折溢价不可直接采信",
                          "remedy": "当日净值通常 T+1 公布；改用 `etf overview` 的 `etfDisc` 字段（IOPV 口径）",
                          "fallback": "`etfDisc`（交易所 IOPV 口径，与 NAV 口径不同，须分别声明）"},
    # ⚠️ 2026-10-13 新增（512400.SS 有色金属轮实测）。**这条不是「取不到」，而是「取到了但不可信」**：
    #    `sector finance pt01801050` 回传 `stockCnt=1`（申万一级有色金属实际成分股远大于 1），
    #    且行业级 TTM 毛利率 **−9.22%**、净利率 **−56.74%**、ROE **−103.27%**、
    #    经营现金流占收入 **−37.12%**，**而同一行 `netProfitYoY = +30.14%`** ——
    #    「行业净利同比 +30%」与「行业毛利率为负」在逻辑上互斥，不可能同时为真。
    #    ⇒ 判 **C 类（上游聚合退化）**：不是 A（上游真缺）、不是 B（阈值误伤）、不是 S（时点不对）。
    #    ⇒ decisive=True：它挡掉的是「申万行业财务质量」这一整条腿。若不登记，下游会把
    #      「行业毛利率为负、ROE −103%」当成本标的/行业的基本面证据，从而得出与事实相反的方向
    #      —— 这正是本轮实测差点发生的事（证据包照报「成功 14/14」，通道全绿）。
    #    ⇒ 检测器 = `collect_a_etf.py::_sector_fin_gaps()`。**键名必须是通道名** `sector_fin_degenerate`
    #      （不是语义名），否则台账会标 `?` 并要求人工归类。
    "sector_fin_degenerate": {"kw": ["sector_fin_degenerate", "sector_fin", "申万行业财务", "行业财务",
                                    "毛利率为负", "成分股数", "聚合退化"],
                              "cls": "C", "decisive": True,
                              "blocks": "申万一级行业聚合财务退化为单一成分股口径（stockCnt=1）且盈亏互斥"
                                        " ⇒「行业毛利率 / ROE / 现金流质量」这一整条腿不可用；"
                                        "任何「行业盈利质量恶化」或「行业在亏损」的论断都失去依据",
                              "remedy": "上游 sector finance 聚合退化（非本仓 bug，亦非标的经营真的差）⇒ "
                                        "改用 ETF 聚合估值 + 板块估值横截面 + 机构一致盈利预测 + 持仓穿透"
                                        "作为基本面锚，并**弃用该通道的绝对值**",
                              "fallback": "ETF `etf overview` 聚合估值（PE/PB/PEG/ROE 及历史分位）"
                                          "+ `sector valuation` 横截面 + `sector forecast` 两年复合增长"
                                          "（**口径不同，须分别声明**）"},
    # ⚠️ 2026-10-13：A 股 ETF 的 `option_structure` 与 `social:StockTwits` 两条**早就登记在 RULES 里**
    #    （见下方与上方条目），但此前**从没有发射方** —— 它们只以散文形式写在证据包 §0，
    #    而台账靠正则抓「非全绿通道」行 ⇒ 永不被登记。现由 `collect_a_etf.py::_structural_gaps()`
    #    统一发射（只往登记行追加，不影响 `成功 N/M` 的分子分母）。
    "macro:10y_treasury": {"kw": ["10y_treasury", "国债", "DGS10", "^TNX"], "cls": "A", "decisive": False,
                           "blocks": "—", "remedy": "重试", "fallback": "^TNX"},
    # ⚠️ 2026-10-05 新增（NFLX 轮实测）：`realtime_close` 是 §13「最新交易日实时收盘补充」通道，
    #    作用是当日线接口尚未发布当日 bar 时，用实时字段 + 1 分钟 bar 把「最新交易日」补回来。
    #    实测缺失成因为 **yfinance 限流**（`YFRateLimitError: Too Many Requests`）
    #    ⇒ 属 **B 类（限流/阈值误伤）**，不是 C 类采集器 bug，也不是 A 类上游真缺。
    #    未登记时台账会标 `cls="?"` 并提示「决定性判断会漏」——故补录。
    # ⚠️ 2026-10-20 新增（688836 轮实测）：A股个股 `get_stock_data` / `get_fundamentals`
    #    / 三大报表 / 长周期指标在 yfinance 侧失败。根因实测为 **YFRateLimitError:
    #    Too Many Requests**（短时间多次调用触发限流）⇒ 属 **B 类（限流/阈值误伤）**，
    #    不是 C 类采集器 bug，也不是 A 类上游真缺。
    #    ⚠️ 关键：westock 侧通道（quote/kline/technical/chip/…）**不受影响**，
    #    A股个股的主口径数据（价、量、均线、KDJ/RSI/MACD、筹码）来自 westock，
    #    故该缺口**不阻断交付**，但须在简报中声明「估值快照与年报口径缺失」。
    "get_stock_data": {"kw": ["get_stock_data", "yfinance", "YFRateLimit", "估值快照", "限流"],
                       "cls": "B", "decisive": False,
                       "blocks": "yfinance 侧（估值快照 / 三大报表 / MA60-250 等长周期指标）取不到 ⇒ "
                                 "**市盈率、PB、年报财务、年线**该轮不可用；"
                                 "**westock 侧主口径（价、量、短中期均线、KDJ/RSI/MACD、筹码、资金流）不受影响**",
                       "remedy": "等待数分钟让限流窗口重置后重跑 `collect_a_stock.py`；"
                                 "或用 westock 的 `profile` / `finance` 通道人工补齐",
                       "fallback": "westock `technical`（MA5/10/20、BOLL、MACD、KDJ、RSI）+ `finance` 口径"
                                   "（**与年报口径不同，须分别声明**）"},
    "realtime_close": {"kw": ["realtime_close", "实时收盘", "最新交易日实时"], "cls": "B", "decisive": False,
                       "blocks": "取不到「最新交易日」的实时价 ⇒ **口径 B（盘中价）不可用**，"
                                 "「实时时段比日线末日新 N 个交易日」的对比无法进行；"
                                 "**主口径（最后完整 bar）不受影响**",
                       "remedy": "多为 yfinance 限流（YFRateLimitError）；等数分钟后重跑，或接受缺失",
                       "fallback": "以上一个完整交易日收盘价为准（口径 A），并显式声明「本轮无盘中口径 B」"},
    # ⚠️ 2026-10-08 新增（GOOG 轮实测）：§6 全球宏观新闻「仅标题无正文」。
    #    根因（实测）：yfinance 1.7.0 两条新闻通道**都不保证正文** ——
    #      ① `Ticker().news` / `get_news()` 设计上含 summary，但该端点在 2026-10-08
    #         对**所有 symbol**（^GSPC/SPY/AAPL/GOOG…）一律返回 0 条 ⇒ 上游降级；
    #      ② 兜底 `Search().news` 为平铺结构，顶层键并集固定 8 个，
    #         **不含 summary/content/description** ⇒ 结构性无正文。
    #    ⇒ 这不是「取错接口」（铁律 35 的形态），主通道选型是对的、只是上游失效；
    #      兜底接口则**历史上就不带正文**。两者叠加 ⇒ 宏观新闻恒剩「标题 + Link」。
    #    修法：采集层新增**按需正文回填**（抓新闻页 → 限 `article-body` 容器取 `<p>`）。
    #    ⚠️ 不得在全页匹配 `<p>`：Yahoo 页面后半段有编码混淆脚本，实测首段会变乱码。
    #    回填上限 8 篇、单篇截断 1200 字符、失败静默降级 ⇒ **非 100% 成功**，
    #    故仍需登记：拿到正文的是常态，个别条目仍可能只有标题。
    "global_news_body": {"kw": ["全球宏观新闻", "宏观新闻", "Global Market News", "仅有标题", "无正文"],
                         "cls": "B", "decisive": False,
                         "blocks": "宏观新闻可能只剩「标题 + Link」⇒ 无法从正文提取事件细节与语气，"
                                   "只能按标题做粗粒度定性（**但标题与量化数据仍可用**）",
                         "remedy": "采集层已加按需正文回填（`backfill_missing_summaries`）；"
                                   "个别条目仍可能抓取失败 ⇒ 如实声明该条仅有标题",
                         "fallback": "标题本身（真实、可用）+ FRED 实测值补足宏观量化"},
    # ⚠️ 2026-10-08 新增（GOOG 轮实测）：个股新闻通道整体归零。
    #    实测 `Ticker().news` / `.get_news()` 对**所有 symbol**（含 GOOG/AAPL/SPY）
    #    一律返回 0 条 ⇒ 上游端点降级（非本仓 bug，非「取错接口」）。
    #    曾尝试 `Search(canonical)` 兜底，**已否决**，两条理由：
    #      ① 语义不专属：`Search("GOOG")` 返回泛科技/能源新闻，引进来是噪声；
    #      ② 窗口过滤后仍为空：Search() 只回最新快讯，回溯窗口下被 in_window 全部挡掉。
    #    ⇒ 当前选择「如实报空 + 台账声明降级」，不引入噪声源。属 B 类（上游降级）。
    #    ⚠️ 键名必须是**证据包「非全绿通道」里出现的通道名**（`get_news`），
    #       不是语义名 —— 台账按通道名查表，写错会标 `?` 并要求人工归类。
    "get_news": {"kw": ["个股新闻", "§5 个股新闻", "No news found"],
                 "cls": "B", "decisive": False,
                 "blocks": "无个股新闻 ⇒ 失去「公司层面的当期事件」这一证据类；"
                           "**但 §4 财报、§6 宏观、§3 快照均不受影响，估值/技术面论证照常可做**",
                 "remedy": "上游 `Ticker().news` 端点降级（全 symbol 0 条）；等端点恢复后重采即可，"
                           "不要用 Search() 兜底（语义不专属且窗口过滤后仍为空）",
                 "fallback": "§6 宏观新闻（含正文回填后，含大量个股级线索如 NVDA/AAPL 提及）；"
                             "§3/§4 基本面数据"},
    # ⚠️ 2026-10-11 新增（SKHY 轮实测）。**注意这一条与其它条目的结构不同**：
    #    `edgar_raw` **不是采集通道** —— 它既不出现在证据包的「通道健康度」里，
    #    也不在 `_verify_snapshot_consistency` 的覆盖内 ⇒ 上面那条
    #    `for name, status in info["channels"]` 循环**永远碰不到它**，
    #    **光在这里登记规则是够不着的**（这正是 O4 的实质发现）。
    #    ⇒ 唯一的发射方是 `_verify_edgar_raw.py` 落的状态副档
    #      `evidence/<T>_<date>.edgar.json`（消费逻辑见 build() 末尾）。
    #    实测：SKHY 的 CIK 0002120882 的 companyfacts **只含 `ffd` 税种 5 个概念**
    #    （全是**申报费披露**），**无 us-gaap / ifrs-full** ⇒ 外国私人发行人无
    #    US-GAAP XBRL，13 项核心科目**全部无法独立核验** ⇒ 每个财务数字都是单一来源。
    "edgar_raw": {"kw": ["edgar_raw", "SEC 核验", "独立核验", "单一来源", "结构性缺失"],
                  "cls": "A", "decisive": True,
                  "blocks": "全部财务数字**只有单一来源**（供应商快照）而无法独立核验 ⇒ "
                            "任何「利润 / 负债 / 现金流」类论断都缺少第二信源背书",
                  "remedy": "跑 `_verify_edgar_raw.py <T> <date>`；若为外国私人发行人，"
                            "必须打开 companyfacts 缓存看**税种键**（无 us-gaap 即结构性不可得，"
                            "反复重试无意义）",
                  "fallback": "交易所 / 供应商口径（**与快照同源，不构成独立核验**）；"
                              "公司 IR 原始财报（人工核验）"},
    # ⚠️ 2026-10-12 新增（GOOG 轮）。与 `edgar_raw` **同族**：都是「**手工触发的一步**，
    #    结论原本只存在于终端输出里」⇒ 简报作者忘写，就没有任何门禁能发现。
    #    发射方 = `_verify_earnings_quality.py --tickers <T> --as-of <date>` 落的
    #    `evidence/<T>_<date>.earnings.json`（消费逻辑见 build() 末尾）。
    #    实测 GOOG：非经营/非常规收益占 TTM 净利 **60.9%** ⇒ 报表 PE(TTM) 17.4x
    #    被抬到经营性 **44.6x**（这正是铁律 40 记录的 GOOG 事件）。
    #    注意：这不是「数据缺失」，而是**报表数字本身被扭曲** ⇒ 与 `forward_eps` 同类，
    #    判 **C**（vendor 派生字段不可信），而不是 A（上游真缺）。
    "earnings_quality": {"kw": ["earnings_quality", "收益质量", "非经营", "经营性 PE", "浮盈"],
                         "cls": "C", "decisive": True,
                         "blocks": "报表净利被一次性 / 非经营项目抬高 ⇒ **报表 PE 不是可信的"
                                   "估值锚点**，「便宜」类论断在改用经营性口径重算前不成立",
                         "remedy": "跑 `_verify_earnings_quality.py --tickers <T> --as-of <date>`；"
                                   "判 FAIL 时必须扣非、重算经营性 PE 之后再与同业比较",
                         "fallback": "经营性 PE = 市值 ÷（TTM 净利 − TTM 非经营 / 非常规收益）"
                                     "（**与报表 PE 口径不同，引用须分别声明**）"},

    # ⚠️ 2026-10-17 新增（CBOE 期权源接入配套）。**这一条不是「数据缺失」，而是「口径位移」。**
    #    背景：yfinance 的期权链只在美东 09:30–16:00 实时刷新，盘前/盘后只返回上一交易日的
    #    残留挂单（`bid`/`ask` 格式合法但 `lastTradeDate` 陈旧数周）⇒ 期权维度整体不可用。
    #    对策：非盘中时段自动切 **CBOE 官方延迟报价**（做市商报价链，不依赖「当天有没有成交」）
    #    ⇒ 盘前仍能重建完整期限结构（实测 17/17 个到期日可算 ATM IV）。
    #    ⚠️ 但它**拿的是上一时段收盘快照，不是实时报价**：
    #      · CBOE 延长时段（GTH 20:15–09:25）仅覆盖 SPX/SPXW/XSP，**不含股票与 ETF 期权**
    #        ⇒ 盘前拿到的成交**必然止于上一交易日**（市场本身没成交，非接口缺陷）；
    #      · 接口本身还有 **15 分钟延迟**（路径即 `delayed_quotes`）。
    #    ⇒ 判 **B 类**（非上游真缺、非阈值误伤，而是受「采集时点」影响的口径位移），
    #      但 **decisive=True** —— 因为它挡掉的是「此刻/盘中」这一类论断：期权读数相对
    #      报告基准日的价格数据**旧一个交易日**，跨时点不可比（铁律 1、铁律 36）。
    #      凡引用 IV / 偏斜 / 期限结构，**必须写明来源为 CBOE 延迟报价并标注其快照时点**。
    #    ⇒ 检测源 = 证据包「采集时点」行（`_should_use_cboe_source()` 写入的 session_note）
    #      中含「切 CBOE 官方延迟报价」⇒ 无需新增副档，避免副档与证据包各自漂移。
    "CBOE_fallback_used": {
        "kw": ["CBOE", "CBOE_fallback_used", "官方延迟报价", "delayed_quotes",
               "上一时段收盘快照", "交易所模型"],
        "cls": "B", "decisive": True,
        "blocks": "期权 IV / 偏斜 / 期限结构来自 **CBOE 官方延迟报价的上一时段收盘快照**"
                  "（非实时报价）⇒ **不可用于「此刻 / 盘中」的任何期权论断**，"
                  "也不得与盘中 yfinance 口径的 IV 跨轮直接比较（跨时点不可比）；"
                  "**收盘级分析（下行保护成本、事件定价位置）仍可用**",
        "remedy": "若必须拿到实时期权读数，改在美东 09:30–16:00 常规时段重采（走 yfinance 主源）；"
                  "否则接受「上一时段快照」并在简报中声明来源与快照时点",
        "fallback": "收盘级 IV / 偏斜 / 期限结构（**CBOE 交易所模型口径，"
                    "与项目自建 BSM 反解数值不可混用**）；波动率环境代理 ^VIX / ^VXN"},
}

# ★ 2026-10-20 NFLX 轮实测：美股采集器（`collect.py`）的通道名是 **`get_fundamentals`**，
#   而 §3 扣留的六要素只登记在语义键 `profile` 下；台账按**通道名精确查表**
#   （`RULES.get(name)`）⇒ 未登记时 cls 被判成 `?`、decisive 漏判，
#   并打印「未归类：请把该通道登记进 RULES 表」。
#   与 2026-10-13 `sector_fin_degenerate` 的教训同源（键名必须是通道名）。
#   ⇒ 不复制第二份六要素（两处写必漂移），直接**别名**到 `profile`；
#     `remedy_file` 也随之生效：supplement 一旦落地，该通道自动降级为「已解决（口径说明）」。
RULES["get_fundamentals"] = RULES["profile"]

# ★ 2026-10-21 新增：盘前/盘后（扩展时段）通道。取不到时不阻断方向判断
#   （常规时段收盘与日线已覆盖决策所需价格），但必须让下游看见「事件反应未知」。
RULES["extended_hours"] = {
    "kw": ["extended_hours", "盘前", "盘后", "扩展时段", "prepost"],
    "cls": "A", "decisive": False,
    "blocks": "无法观察事件在扩展时段的第一反应（盘前/盘后成交）⇒ 「事件后开盘跳空」只能从常规时段推断",
    "remedy": "yfinance 1 分钟 bar 带 prepost=True 重采；该标的若无扩展时段成交则接受缺失",
    "fallback": "常规时段首根 15 分钟 bar 的开盘缺口（口径不同：只反映集合竞价结果）",
}

BODY_NOTE = {"stale": "报价陈旧（超过新鲜度闸门）", "unavailable": "通道不可用", "missing": "无数据",
             "empty": "返回为空", "N/A": "上游未提供"}


def parse_evidence(ticker: str, date: str) -> dict:
    p = EVID / f"{ticker}_{date}.md"
    if not p.exists():
        return {"error": f"证据包不存在: {p.relative_to(ROOT).as_posix()}"}
    t = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"成功:\s*(\d+)\s*/\s*(\d+)", t)
    n_ok, n_tot = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    bad = re.search(r"(?:非全绿通道\*\*?|失败或不可用):\s*(.+)", t)
    channels = []
    if bad:
        for item in re.split(r"[、,，]", bad.group(1).strip().rstrip("。")):
            item = item.strip()
            if not item or item in ("无", "none", "None", "无（全绿）", "—"):
                continue
            name, _, status = item.partition("=")
            channels.append((name.strip(), status.strip() or "unavailable"))
    # §3 被上游扣留 = 事实上的 profile 缺口
    withheld = bool(re.search(r"Profile fundamentals are withheld", t))
    # ★ 2026-10-17：期权是否走了 CBOE 延迟报价回退（非盘中采集）。
    #   判据是采集器写进证据包的「采集时点」行 —— **不新增副档**，避免副档与证据包各自漂移。
    cboe_fallback = bool(re.search(r"切\s*CBOE\s*官方延迟报价", t))
    return {"n_ok": n_ok, "n_total": n_tot, "channels": channels, "profile_withheld": withheld,
            "cboe_fallback": cboe_fallback, "path": p.relative_to(ROOT).as_posix()}


def build(ticker: str, date: str) -> dict:
    info = parse_evidence(ticker, date)
    if "error" in info:
        return info
    gaps = []
    for name, status in info["channels"]:
        rule = RULES.get(name)
        g = {"channel": name, "status": status,
             "cls": (rule or {}).get("cls", "?"),
             "decisive": bool((rule or {}).get("decisive", False)),
             "blocks": (rule or {}).get("blocks", "**未归类：请把该通道登记进 _gap_ledger.py 的 RULES 表**"),
             "remedy": (rule or {}).get("remedy", "人工归类"),
             "fallback": (rule or {}).get("fallback", "—"),
             "label": name, "kw": (rule or {}).get("kw", [name])}
        # ★ 2026-10-20：`remedy_file` 此前只在 `profile` 分支生效；通道级条目
        #   （如美股 `get_fundamentals=withheld`）即便 supplement 已落地仍报「未解决」。
        #   改为**通用判据**：规则声明了补救产物且文件存在 ⇒ 降级为已解决、decisive=False。
        rf = (rule or {}).get("remedy_file")
        if rf:
            remedy_path = EVID / f"{ticker}_{date}.{rf}"
            if remedy_path.exists():
                g.update({"status": "resolved", "decisive": False,
                          "resolved_by": remedy_path.relative_to(ROOT).as_posix(),
                          "note": "采集时确缺该通道，但补救产物已落地 ⇒ 降级为「口径说明」，引用时标明口径即可"})
        gaps.append(g)
    if info["profile_withheld"]:
        rule = RULES["profile"]
        # remedy_file：若补救产物已落地，则不再是「缺口」，降级为「口径说明」
        rf = rule.get("remedy_file")
        remedy_path = EVID / f"{ticker}_{date}.{rf}" if rf else None
        if remedy_path and remedy_path.exists():
            gaps.append({"channel": "profile (§3 快照)", "status": "resolved", "cls": rule["cls"],
                         "decisive": False, "blocks": rule["blocks"], "remedy": rule["remedy"],
                         "fallback": rule["fallback"], "label": "profile", "kw": rule["kw"],
                         "resolved_by": remedy_path.relative_to(ROOT).as_posix(),
                         "note": "采集时确缺该通道，但补救产物已落地 ⇒ 降级为「口径说明」，引用时标明口径即可"})
        else:
            gaps.append({"channel": "profile (§3 快照)", "status": "withheld", "cls": rule["cls"],
                         "decisive": rule["decisive"], "blocks": rule["blocks"], "remedy": rule["remedy"],
                         "fallback": rule["fallback"], "label": "profile", "kw": rule["kw"]})

    # —— 快照内部自洽性（2026-10-09 新增）——
    # 上面那条循环只覆盖「通道健康度」里明确报 failed 的项。还有一类失真它永远抓不到：
    # **调用成功、内容非空、格式合法，但数值与同一份快照的基点互相矛盾**（NVDA 的 Forward EPS）。
    # 这是铁律 26（序关系/恒等式）在「估值快照」侧的对应物，必须由独立检测器来做。
    # ⇒ 放在这里，使每一轮、每一个标的都自动受检，而不是靠人记得跑一次。
    try:
        from _verify_snapshot_consistency import check as _check_snapshot
    except ImportError:  # 以包方式被导入时的回退
        from wb_analysis._verify_snapshot_consistency import check as _check_snapshot
    for f in _check_snapshot(ticker, date):
        rule = RULES.get(f["label"], {})
        gaps.append({
            "channel": f"snapshot:{f['label']}",
            "status": f["severity"],
            "cls": rule.get("cls", "C"),
            "decisive": bool(rule.get("decisive", True)),
            "blocks": rule.get("blocks", f["detail"]),
            "remedy": rule.get("remedy", "用 SEC 自算 TTM 交叉验证后再决定是否引用"),
            "fallback": rule.get("fallback", "SEC 自算 TTM 口径的倍数"),
            "label": f["label"],
            "kw": rule.get("kw", [f["label"]]),
            "note": f["detail"],
        })

    # —— SEC 独立核验状态（2026-10-11 新增，O4）——
    # `edgar_raw` 不是采集通道 ⇒ 上面两个循环都覆盖不到它（见 RULES 里的长注释）。
    # 唯一的发射方是 `_verify_edgar_raw.py` 落的状态副档；**副档不存在时按「未执行」处理
    # 且不产生缺口** —— 因为对指数 / ETF 这类标的 EDGAR 本就不适用，
    # 强行报缺口会把「不适用」误报成「缺失」。
    _sc = EVID / f"{ticker}_{date}.edgar.json"
    if _sc.exists():
        try:
            _st = json.loads(_sc.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 副档坏掉不该阻断台账
            _st = None
        if _st and _st.get("status") != "verified":
            _rule = RULES["edgar_raw"]
            _stat = _st.get("status")
            # status → (cls, decisive)：数字对不上是 C 类硬伤；结构性不可得是 A 类；
            # 采集失败是 B 类（可重试）；部分缺失是 A 类但不阻断方向。
            _cls, _dec = {
                "mismatch": ("C", True),
                "taxonomy_missing": ("A", True),
                "partial": ("A", False),
                "fetch_failed": ("B", False),
            }.get(_stat, ("A", False))
            gaps.append({
                "channel": "edgar_raw", "status": _stat,
                "cls": _cls, "decisive": _dec,
                "blocks": _rule["blocks"], "remedy": _rule["remedy"],
                "fallback": _rule["fallback"], "label": "edgar_raw", "kw": _rule["kw"],
                "note": _st.get("detail", ""),
            })
        elif _st:
            # verified：登记为**已解决**，使「核验过了」在台账里也有一行可查
            _rule = RULES["edgar_raw"]
            gaps.append({
                "channel": "edgar_raw", "status": "resolved", "cls": _rule["cls"],
                "decisive": False, "blocks": _rule["blocks"], "remedy": _rule["remedy"],
                "fallback": _rule["fallback"], "label": "edgar_raw", "kw": _rule["kw"],
                "resolved_by": _sc.relative_to(ROOT).as_posix(),
                "note": _st.get("detail", ""),
            })

    # —— 收益质量闸门状态（2026-10-12 新增，与 edgar_raw 同族）———————
    # Q5 是手工触发的一步，其结论原本只在终端里 ⇒ 必须由副档发射进台账，
    # 否则「报表 PE 被浮盈抬高」这件会**改写结论方向**的事可以无声漏掉。
    _eq = EVID / f"{ticker}_{date}.earnings.json"
    if _eq.exists():
        try:
            _eqst = json.loads(_eq.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _eqst = None
        if _eqst and _eqst.get("status") in ("FAIL", "WARN"):
            _rule = RULES["earnings_quality"]
            _is_fail = _eqst.get("status") == "FAIL"
            gaps.append({
                "channel": "earnings_quality", "status": _eqst.get("status"),
                "cls": _rule["cls"], "decisive": _is_fail,
                "blocks": _rule["blocks"], "remedy": _rule["remedy"],
                "fallback": _rule["fallback"], "label": "earnings_quality",
                "kw": _rule["kw"], "note": _eqst.get("detail", ""),
            })
    # —— CBOE 延迟报价回退（2026-10-17 新增，CBOE 期权源接入配套）——
    # 这一条与 `edgar_raw` / `earnings_quality` 同族：都是「**不在通道健康度里表达的**」
    # 信息，必须由独立发射方送进台账，否则下游看不见。
    # 为什么 case 是「有缺口」而不是「无缺口」：CBOE 回退拿的是**上一时段收盘快照**，
    # 不是实时报价 ⇒ 期权读数与报告基准日的价格数据**旧一个交易日**，属**跨时点口径位移**。
    # 若不在台账里出现一行，下游就会把「昨日快照」当作「此刻读数」引用 —— 这正是铁律 1/36
    # 反复踩过的那类错误（铁律 36：期权信号会被采集时点反向改写）。
    if info.get("cboe_fallback"):
        _rule = RULES["CBOE_fallback_used"]
        gaps.append({
            "channel": "CBOE_fallback_used", "status": "used",
            "cls": _rule["cls"], "decisive": _rule["decisive"],
            "blocks": _rule["blocks"], "remedy": _rule["remedy"],
            "fallback": _rule["fallback"], "label": "CBOE_fallback_used", "kw": _rule["kw"],
            "note": "非盘中采集 ⇒ 期权走 CBOE 官方延迟报价；"
                    "所取 IV / 偏斜 / 期限结构为**上一时段收盘快照**（15 分钟延迟），"
                    "与项目自建 BSM 反解口径**不可混用**。",
        })

    return {"ticker": ticker, "as_of": date, "evidence": info["path"],
            "channels_ok": info["n_ok"], "channels_total": info["n_total"],
            "gaps": gaps,
            "decisive_count": sum(1 for g in gaps if g["decisive"]),
            "resolved_count": sum(1 for g in gaps if g.get("status") == "resolved"),
            "unclassified": [g["channel"] for g in gaps if g["cls"] == "?"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("date")
    ap.add_argument("--check", default=None, help="给草稿目录，校验决定性缺口是否在简报里声明")
    # ★ 2026-10-19：门禁（_precheck）调用本工具时不应改动仓库状态 ——
    #   铁律 50「判据函数不得带副作用」。此前 `--check` 也会重写 gaps.json，
    #   导致「跑一次门禁 = 改一次台账」，resolved 状态在检查过程中被刷新。
    ap.add_argument("--no-write", action="store_true",
                    help="只计算不落盘（门禁调用时使用）")
    args = ap.parse_args()

    led = build(args.ticker, args.date)
    if "error" in led:
        print(f"✗ {led['error']}")
        return 1

    out = EVID / f"{args.ticker}_{args.date}.gaps.json"
    if not args.no_write:
        out.write_text(json.dumps(led, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    print("=" * 100)
    _res = led.get("resolved_count", 0)
    print(f"数据缺口台账：{args.ticker} {args.date}　（通道 {led['channels_ok']}/{led['channels_total']}，"
          f"未解决缺口 {len(led['gaps']) - _res} 条，其中**决定性 {led['decisive_count']} 条**；"
          f"已解决 {_res} 条）")
    print("=" * 100)
    if not led["gaps"]:
        print("  ✓ 无缺口")
    for g in led["gaps"]:
        if g.get("status") == "resolved":
            print(f"\n  [{g['channel']}] ✓ 已解决（降级为口径说明）")
            print(f"      补救产物：{g.get('resolved_by', '—')}")
            print(f"      须知　　：{g.get('note', '')}")
            continue
        tag = "★决定性" if g["decisive"] else "        "
        print(f"\n  [{g['channel']}] 状态={g['status']}  类别={g['cls']}  {tag}")
        print(f"      挡掉了：{g['blocks']}")
        print(f"      怎么补：{g['remedy']}")
        print(f"      代理　：{g['fallback']}")
    if led["unclassified"]:
        print(f"\n  ⚠ 未归类通道 {led['unclassified']} —— 请登记进 RULES 表，否则「决定性」判断会漏")
    print(f"\n[台账] {out.relative_to(ROOT).as_posix()}")

    if args.check:
        draft = Path(args.check)
        brief = draft / "0_brief.md"
        if not brief.exists():
            print(f"\n✗ 简报不存在：{brief}")
            return 2
        text = brief.read_text(encoding="utf-8")
        decisive = [g for g in led["gaps"] if g["decisive"]]
        missing = [g for g in decisive
                   if not any(k in text for k in (g.get("kw") or [g["label"]]))]
        print(f"\n[门禁] 决定性缺口 {len(decisive)} 条，简报中未声明 {len(missing)} 条")
        for g in missing:
            print(f"    ✗ 未声明：{g['channel']}（它挡掉了：{g['blocks'][:40]}…）")
        if missing:
            print("  ⇒ **决定性缺口必须在简报里逐条声明**：缺它的后果是「下游角色不知道这里有洞」，"
                  "可能凭空补出一个方向性结论。")
            return 1
        if decisive:
            print("  ✓ 全部决定性缺口已在简报中声明")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
