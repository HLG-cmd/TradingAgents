# 深度投研分析框架规范 (Framework)

本文件是「**用顶级大模型多智能体分工协同替代单体推理**」的提示词与输出契约，
提炼自上游 `tradingagents/agents/**` 的提示词与 `agents/schemas.py` 的结构化契约。
配合 `collect*.py`（免费证据采集，零 LLM）与 `assemble.py`（渲染）使用，
即可在**不调用任何付费 API** 的前提下产出与原系统同构的报告。

---

## 0. 流水线顺序

```
证据包（collect.py 产出，免费）
   ↓
Ⅰ 分析师团队（4 位，独立作业，各自读证据包）
   market / fundamentals / news / sentiment
   ↓
Ⅱ 多空辩论（牛派 ⇄ 熊派，逐轮对辩）
   ↓ 研究经理裁定 → ResearchPlan
Ⅲ 交易员 → TraderProposal
   ↓
Ⅳ 风险辩论（激进 ⇄ 保守 ⇄ 中性）
   ↓ 组合经理终审 → PortfolioDecision
```

上游的等价节点连线见 `tradingagents/graph/setup.py::setup_graph`。
⚠️ **「社媒分析师」已不存在**（上游 `agents/analysts/social_media_analyst.py` 现为兼容壳），
其职责已并入情绪分析师 ⇒ **LLM 节点共 12 个**：4 分析师 + 牛 + 熊 + 研究经理 + 交易员 + 3 风险 + 组合经理。

---

## 1. 全局纪律（不可违反）

1. **只用证据包里的数字**。任何价格、比率、财务数值都必须能在证据包里找到出处。
   证据包缺失的通道（如无 `FRED_API_KEY` 时的宏观）**必须显式声明"该项数据缺失"**，
   绝不允许编造或凭印象填充。原系统对此的处理是输出
   `DATA_UNAVAILABLE: ... Proceed without it; do not fabricate values.`
2. **区分事实与推断**。事实引用具体数值；推断必须标注为推断。
3. **不因"要显得果断"而硬给方向**。证据平衡/冲突/不足时，明确选 Hold。
   这是原系统在 Research Manager 与 Portfolio Manager 两处都强调的规则。
4. **逐角色独立判断**。后续角色可以反驳前面角色，不得简单复述。
5. 报告正文用中文（`TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese`），
   但**评级词汇必须用英文原词**，因为下游解析器
   （`tradingagents/agents/utils/rating.py`）只认英文五档词。
6. **结论块必须置于文首，叙述中禁止出现裸的英文评级词。**（实测踩坑，务必遵守）

   `extract_rating` 是两段式解析：先找 `Rating: X` 形式的标签（第二段才退化为
   **扫描全文取遇到的第一个五档英文词**）。因此若研究报告在
   `**Recommendation**: Hold` 之前出现「（Underweight）」「（Buy）」这类裸词，
   解析器会取到**那个词**而不是真正的结论。

   实测案例：`2_research/manager.md` 的叙述里写了「熊派主张减持（Underweight），
   牛派主张建仓（Buy）」，位于 `**Recommendation**: Hold` 之前，
   结果上游解析器读出 `Underweight`，与实际结论 `Hold` 相反。

   **规避方式**：把 `**Recommendation**: / **Rationale**: / **Strategic Actions**:`
   结论块放在文档最前面；叙述中只用中文表述（「减持」「建仓」「持有」），
   不要写英文评级词。`assemble.py` 的 `crosscheck_with_upstream()` 会自动检出
   这类不一致并告警。

7. **篇幅看信息密度，不看字数。** 按职责分档（唯一定义源：`wb_analysis/_length.py`）：
   - 分析师 4 席 + 牛熊：**4,000–4,800 字符**（硬下限 4,000）；
   - 决策类（manager / trader / 三风控 / 组合经理）：**3,000–3,800 字符**（硬下限 3,000）；
   - 统一上限 **5,000**，超过判「偏长」。
   **每句话都要承载信息**：不得复述结论、不得同一句写两遍、不得用「综上所述」凑段。
   数字不够就写「该项数据缺失」，不要用形容词填长度。
   检查器：`_lint_drafts.py` 4d 节（重复句）、5 节（篇幅）。

---

## 2. 评级词汇表（严格）

### 五档仓位评级（Research Manager / Portfolio Manager / 三个风险辩论席位）
`Buy` / `Overweight` / `Hold` / `Underweight` / `Sell`

| 档位 | 含义 |
|---|---|
| Buy | 强信心建仓或加仓 |
| Overweight | 看好，逐步增加敞口 |
| Hold | 维持现有仓位，不动 |
| Underweight | 谨慎，减持部分获利 |
| Sell | 退出或避免建仓 |

### 三档交易动作（Trader）
`Buy` / `Hold` / `Sell`

### 六档情绪（Sentiment Analyst）
`Bullish` / `Mildly Bullish` / `Neutral` / `Mixed` / `Mildly Bearish` / `Bearish`

情绪分值 0–10（0 极度看空，5 中性，10 极度看多）。与档位的对应参考：
Bullish ≈ 6.5–10，Mildly Bullish ≈ 5.5–6.4，Neutral/Mixed ≈ 4.5–5.5，
Mildly Bearish ≈ 3.5–4.4，Bearish ≈ 0–3.4。

### 置信度
`low` / `medium` / `high`。当某通道缺失或样本点少于 5 个时用 `low`。

---

## 3. 各角色职责与输出契约

### Ⅰ-1 市场分析师（Market Analyst）
**职责**：技术面。从证据包 `## 1 行情与价格结构` 与 `## 2 技术指标` 出发。
**必须覆盖**：趋势方向（价格 vs 50/200 SMA，金叉/死叉状态）、动量（MACD 三线
的相对位置与收敛/发散，RSI 位置及背离）、波动率（ATR、布林带宽度与价格在带内的
位置）、量能（成交量相对 20 日均值、VWMA 与价格的偏离）。
**必须给出**：具体支撑/阻力价位（可引用布林上下轨、均线、近 20 日高低点、
52 周高低点）。
**输出**：自由格式 markdown，但需以 `### 趋势` `### 动量` `### 波动率`
`### 量能` `### 关键价位` 分节。数据缺失的指标要标注。

### Ⅰ-2 基本面分析师（Fundamentals Analyst）
**职责**：估值与财务质量。读 `## 3 基本面快照` 与 `## 4 三大财务报表`。
**必须覆盖**：估值水平（PE、Forward PE、PEG、PB，并与自身历史或行业常识对照）、
盈利能力（毛利率/净利率/ROE 及其趋势）、成长性（营收与净利同比）、
资产负债健康度（负债结构、现金与现金流）、股东回报（分红、回购）。
**必须明确回答**：当前估值相对其成长性是否合理。给出结论性判断而非罗列数字。

### Ⅰ-3 新闻分析师（News Analyst）
**职责**：读 `## 5 个股新闻` 与 `## 6 全球宏观新闻`。
**必须覆盖**：个股层面的事件（财报、产品、监管、诉讼、管理层变动、分析师评级）、
宏观层面的传导（利率路径、行业政策、地缘、供应链）。
**必须区分**：已实现的事实 vs 预期/传闻。给出对股价的可能影响方向与量级判断。

### Ⅰ-4 情绪分析师（Sentiment Analyst）
**职责**：聚合三类情绪来源——Yahoo Finance 新闻语气、StockTwits cashtag 流、
Reddit 帖文（原「社媒分析师」的职责已并入此处）。
证据包中这两类通道若缺失（`reddit` / `stocktwits`），
**必须显式声明缺失并据此下调 `Confidence`，不得臆测**。
**输出契约**（对应 `SentimentReport`）：
```
**Overall Sentiment:** **<档位>** (Score: <n.n>/10)
**Confidence:** <Low|Medium|High>

<narrative>
```
`narrative` 必须依次覆盖：(1) 逐来源拆解并引用具体证据（引用消息数、多空比、
值得注意的帖子）；(2) 来源间的分歧与一致；(3) 主导叙事主题；
(4) 数据揭示的催化剂与风险；(5) 一张汇总关键情绪信号、方向、来源、
支撑证据的 markdown 表格。
`Confidence` 规则：某来源返回占位内容或样本点少于 5 个 → `low`；
数据存在但稀疏 → `medium`；三个来源都有实质数据 → `high`。

### Ⅱ 多空辩论（Bull ⇄ Bear）
**牛派职责**：构建看好该标的的证据链，重点在成长潜力、竞争优势、正面指标，
并**逐条反驳熊派的具体论点**（要引用熊派用过的数据）。
**熊派职责**：构建看空证据链，重点在估值风险、竞争侵蚀、财务隐患、宏观逆风，
并**逐条反驳牛派的具体论点**。
**风格要求**：对话式辩论，直接交锋，不是列数据清单。
**轮次**：按配置轮数（默认 1 轮）交替发言，每轮必须回应对方上一轮的具体论点。

### Ⅱ-裁定 研究经理（Research Manager）→ ResearchPlan
评判辩论，权衡双方论证质量（**与发言顺序无关**），产出：
```
**Recommendation**: <五档之一>
**Rationale**: <对话式总结双方要点，说明哪些论点决定了该建议>
**Strategic Actions**: <给交易员的具体步骤，含与评级一致的仓位建议>
```
**⚠️ 这一块必须放在文档最前面**（先结论后论证）。原因见第 1 节第 6 条：
解析器会取全文第一个五档英文词，若结论块之前出现裸词，评级会被读错。
论证过程写在结论块之后的分节里，且只用中文表述评级倾向。

### Ⅲ 交易员（Trader）→ TraderProposal
把投资计划落成具体交易方案。**入场价与止损必须是绝对价格数字**
（如 `218.5`），**不得写百分比或区间**——这是原系统踩过的坑
（`_coerce_optional_float` 会丢弃百分比，导致字段为空）。
价位需锚定市场分析师给出的真实价格结构（当前价、支撑阻力、ATR）。
```
**Action**: <Buy|Hold|Sell>
**Reasoning**: <2–4 句，锚定分析师报告与研究计划>
**Entry Price**: <绝对价格，可省略>
**Stop Loss**: <绝对价格，可省略>
**Position Sizing**: <如 5% of portfolio，可省略>

FINAL TRANSACTION PROPOSAL: **<BUY|HOLD|SELL>**
```
最后一行是给下游 grep 用的，必须保留。

### Ⅳ 风险辩论（激进 / 保守 / 中性）
**激进**：主张放大敞口，强调错失成本，攻击保守方的过度谨慎。
**保守**：主张收缩敞口，强调本金保护与尾部风险，攻击激进方的风险低估。
**中性**：主张平衡配置，指出双方各自的盲点，给出条件化的中间路径。
三者必须就**交易员方案的具体价位与仓位**展开争论，而非泛泛谈风险。
每个风控席位可在文首放置 1 次五档表态（正文禁止再出现裸英文评级词）：
```
**Rating**: <五档之一>
```

### Ⅳ-终审 组合经理（Portfolio Manager）→ PortfolioDecision
综合风险辩论，产出终局决定。证据明确支持某方向时才给方向性评级；
证据平衡/冲突/不足时选 Hold。**在论证质量上评判各分析师，与发言顺序无关。**
```
**Rating**: <五档之一>
**Executive Summary**: <2–4 句行动方案：入场策略、仓位、关键风险位、时间跨度>
**Investment Thesis**: <锚定分析师辩论中具体证据的详细论证>
**Price Target**: <可选，报价货币绝对价格>
**Time Horizon**: <可选，如 3-6 months>
```

---

## 4. 输出 JSON 契约（供 assemble.py 消费）

分析层把 12 个角色的产出写成如下 JSON，`assemble.py` 据此渲染出与
`tradingagents/reporting.py::write_report_tree` 完全同构的报告树：

```json
{
  "ticker": "NVDA",
  "as_of": "2026-09-15",
  "ratings": {
    "research_manager": "Hold",
    "trader_action": "Hold",
    "portfolio_manager": "Hold"
  },
  "analysts": {
    "market": "<markdown>",
    "sentiment": "<markdown，含 Overall Sentiment/Confidence 头>",
    "news": "<markdown>",
    "fundamentals": "<markdown>"
  },
  "research": {
    "bull": "<markdown>",
    "bear": "<markdown>",
    "manager": "<markdown，含 Recommendation/Rationale/Strategic Actions>"
  },
  "trading": {
    "trader": "<markdown，末行须为 FINAL TRANSACTION PROPOSAL: **X**>"
  },
  "risk": {
    "aggressive": "<markdown>",
    "conservative": "<markdown>",
    "neutral": "<markdown>",
    "portfolio_manager": "<markdown，含 Rating/Executive Summary/Investment Thesis>"
  },
  "notes": "<可选：数据缺口与免责说明>"
}
```

落盘位置：`wb_analysis/analysis/<TICKER>_<YYYY-MM-DD>.json`

---

## 5. 与上游的一致性

| 项 | 上游实现 | 本框架 |
|---|---|---|
| 五档评级词 | `agents/utils/rating.py::RATINGS_5_TIER` | 第 2 节，逐字一致 |
| 情绪六档 | `agents/schemas.py::SentimentBand` | 第 2 节，逐字一致 |
| 结构化契约 | `agents/schemas.py` 的 `render_*` | 第 3 节，逐字段对齐 |
| 报告树 | `reporting.py::write_report_tree` | `assemble.py` 同构复刻 |
| 无数据容忍 | `DATA_UNAVAILABLE` 前缀 | 第 1 节第 1 条 |

⇒ 产物与原系统报告**无缝替代**（目录结构、章节标题、评级词汇全部一致），
可被任何读取原报告树的下游工具直接消费。

### 5.1 ★ 交叉验证实测（2026-10-18）

上表是**声明**。本节是**实测**：用**上游自己的解析器**逐棵反读本项目全部报告树。

```python
from tradingagents.agents.utils.rating import extract_rating, RATINGS_5_TIER
# 对 reports/<标的>/<树>/{2_research/manager.md, 5_portfolio/decision.md} 逐棵抽取
```

| 结果 | 数值 |
|---|---|
| 上游解析器可正确读出评级 | **全部通过（0 失败）** ✅ |

**怎么复算**（**不写死数字** —— 报告树会持续增加，写死必然漂移）：

```python
from pathlib import Path
from wb_analysis._paths import iter_report_trees
from tradingagents.agents.utils.rating import extract_rating, RATINGS_5_TIER

ok = bad = 0
for _tk, tr in iter_report_trees(Path("reports")):
    vals = [extract_rating((tr / rel).read_text(encoding="utf-8")) if (tr / rel).exists() else None
            for rel in ("2_research/manager.md", "5_portfolio/decision.md")]
    if all(v in RATINGS_5_TIER for v in vals):
        ok += 1
    else:
        bad += 1
        print("FAIL:", tr)
print(f"通过 {ok} / 失败 {bad}")
# 2026-10-18 实测：通过 63 / 失败 0
# 2026-10-19 复算：通过 65 / 失败 0（报告树持续增加，通过数随之增长 = 正常）
```

**五档词全部真实出现过**（非只输出 Hold）：`Buy`（601899.SS、TSM）、
`Overweight`（MU/NFLX/NVDA/WDC）、`Underweight`（AVGO/GOOG/NFLX/NDX/NVDA/WDC）、
`Hold` 多数；`Sell` 未出现（极端看空罕见，属正常）。

⚠️ **复现提示**：遍历时不要用 `reports/*/*_2*` 这类通配符 —— 会把 `reports/_audit/` 下的
审计文档误当成报告树（少 1 棵、多 1 个 FAIL）。必须走 `wb_analysis/_paths.py::iter_report_trees`。

### 5.2 ★ 与上游的能力差异（**双向**如实记录）

| 维度 | 上游 | 本项目 |
|---|---|---|
| **五档评级机制** | LLM 研判（组合经理读辩论后定档） | **同一机制**，逐字同词表 |
| **量化因子回测 / IC 验证** | ❌ **无**（全仓库无 IC / backtest / walk-forward） | ✅ 有（311 期月频 + 17 期年度） |
| **因子有效性诚实标注** | ❌ 无此概念 | ✅ `screener_engine.FACTOR_VALIDATION` |
| **数据缺口台账 + 门禁** | ❌ 无（仅 prompt 里一句 `DATA_UNAVAILABLE` 前缀） | ✅ 台账 + 未声明即 **FAIL** |
| **报告质量记分卡** | ❌ 无 | ✅ 逐轮 9 项代理指标 |
| **LLM 付费** | 需配置 OpenAI / Anthropic / Google 等 provider | ❌ **不付任何 LLM API 费** |
| **数据时点管控** | 有 `DATA_UNAVAILABLE` 容忍 | ✅ 另加时点闸门（铁律 7）与缺口条件式结论 |
| **决策记忆 / 反思** | ✅ `agents/utils/memory.py` + `graph/reflection.py`；默认路径 `~/.tradingagents/memory/trading_memory.md`（`default_config.py` 已设默认值，**上游跑一次就会写入**） | ⚠️ **未接入**：`wb_analysis/` 与 `quant/` 全库零调用（`grep TradingMemoryLog\|Reflector` 无命中）；该文件在本机存在但为 **0 字节** |

**结论口径（不许夸大）**：

1. **评级能力与上游同一水平** —— 同词表、同结构、63/63 实测可互换，**不是更强**。
2. **量化验证层是上游没有的** —— 但它的结论是「**尚未证明有选股能力**」
   （见 `docs/SCREENER.md` §3.1），是**如实标注局限**，不是「选股更准」。
3. ⚠️ **记忆/反思机制本项目未接入** —— 上游的 `Reflector` 会把历史决策的反思
   **重新注入后续 prompt**（真正的跨轮学习回路）；本项目以「记分卡 + RULES/DOMAINS 沉淀」替代。
   这两者**不等价**：记分卡只衡量报告质量、**不回流进角色 prompt**，
   而 RULES/DOMAINS 靠人工沉淀、非自动注入。
   ⇒ **不要让「越用越好」暗示本项目已具备上游那种自动跨轮学习。**

> **一句话**：评级同水平；验证更透明；跨轮学习**不如**上游（未启用）。


---

# 附录 · 数据缺口的处理契约（2026-09-23 新增，**所有角色必须遵守**）

数据缺失会**改变最终结论**。因此不允许只在正文里写一句「该项数据缺失」就过去，必须遵守下面四条。

## 1. 缺口是**台账**，不是散文
每轮由 `wb_analysis/_gap_ledger.py` 生成 `evidence/<T>_<date>.gaps.json`，每条缺口登记：
`label` / `cls`(A 上游真缺 · B 阈值误伤 · C 采集器 bug · S 时点不对) / `decisive`(是否影响结论方向) /
`blocks`(它挡掉了哪个判断) / `remedy`(怎么补) / `fallback`(可用代理，须注明口径不同)。

## 2. **决定性缺口必须出现在统一简报里**
`decisive=True` 的缺口，其关键词必须写进 `0_brief.md`。**未声明 = 交付门禁 FAIL**（不是提示）。
理由：角色会以为「证据包里没有这一项」等于「这一项无事发生」，于是凭空补出一个方向性结论。

## 3. 结论必须是**条件式**，不能是静默降级
若存在决定性缺口，组合经理与交易员**必须**在结论里写清两件事：
  ① 本结论被哪几条缺口约束；
  ② **如果补上该数据，结论会往哪个方向变**（例如「若期权面显示为下行额外定价，则倾向于下调一档」）。
⇒ 把「因为缺数据所以维持」升级为「**在缺口 A 未补齐前维持；若 A 补齐且读到 X，则改为 Y**」。

## 4. 代理必须声明口径
用替代读数时（如期权 IV 缺失 → 用 ^VXN），**必须同时写明**：它是前瞻 IV、周期不同、**不可线性换算**。
**禁止**「用了代理但不声明」，也**禁止**拿代理去支持它原本不能支持的结论。

> 检查工具：`_gap_ledger.py --check <草稿目录>`（退出码 1 = 有决定性缺口未声明）。
> 已接入 `_precheck.py` 的「数据缺口台账」一项，**FAIL 级**。

---

# 附录二 · 牛熊子智能体拆分协议（2026-10-19 新增）

## 为什么需要它

**子智能体不是另一个模型，而是同一模型的另一个上下文窗口。** 独立性来自「彼此看不到对方写了什么」，
不来自模型不同。此前 12 个角色由同一上下文一次写完（601899.SS / 0700.HK 两轮实测），
结果牛熊两派引用的证据高度重合（同一批 PE / ROE / 资金数字），所谓「逐条反驳」只是同一思路的自问自答。

## 执行协议（三轮）

| 轮次 | 执行者 | 输入 | 禁止 |
|---|---|---|---|
| R1 | 子智能体 A（牛派） | 证据包 + `0_brief.md` + `0_derived.md` + FRAMEWORK | 不得读熊派稿、不得读研究经理稿 |
| R1 | 子智能体 B（熊派） | 同上（**与 A 完全相同的输入集**） | 不得读牛派稿 |
| R2 | 研究经理（主上下文） | A、B 两份独立稿 + 证据 | 不得只读摘要，必须逐条比对分歧点 |
| R3 | 交易员 / 风控 / 组合经理 | R2 的裁定 + 全部前置稿 | 沿用原有契约 |

## 落地要点

1. **两个子智能体必须并行启动**，且 prompt 中**不得出现对方的存在**（避免「预判对方」导致同质化）。
2. 输出契约不变（仍写 `2_research/bull.md` / `bear.md`，≥4,000 字符，禁裸评级词）。
3. 研究经理必须显式列出「双方在哪些事实上一致、在哪些解释上分歧」——若发现两稿引用证据重合率 >70%，
   应判定本轮拆分失败，重跑 R1。
4. 子智能体只能读文件，不得改写证据包；落盘由主上下文统一执行（避免并发写冲突）。

## 与篇幅下限的关系

牛熊两稿下限仍为 **4,000 字符**（建议 4,000–4,800）。拆成子智能体后，两个上下文各自只写一份稿，
**不需要**用重复论述凑长度 —— 超过 5,000 字符会触发 `_lint_drafts.py` 的「篇幅偏长」提示。

