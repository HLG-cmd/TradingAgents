# TradingAgents（本地改造版）

> 本项目 **fork 自** 上游 [`TauricResearch/TradingAgents`](https://github.com/TauricResearch/TradingAgents)（多智能体 LLM 金融交易框架）。

## 与原框架的根本区别

上游框架的核心是用「LLM agent 链自动分析」。本项目 **已弃用该链路**——用户 **不付任何 LLM API 费**，也不配置 OpenAI / Anthropic / Google 等 provider。

实际架构（一句话）：

> **免费数据层采集**（`wb_analysis/collect.py` / `collect_index.py`）
> → **多智能体 12 角色分工研判与推理**（按 `wb_analysis/FRAMEWORK.md` 进行多角色对抗研判）
> → **脚本渲染**（`wb_analysis/assemble.py --from-dir`）
> → 报告树 `reports/<TICKER>/<TICKER>_<时间戳>/`

### ⚠️ 与上游的能力差异（**双向**，别只看「更好」的那一半）

**权威版本见 [`wb_analysis/FRAMEWORK.md`](wb_analysis/FRAMEWORK.md) §5.2** —— 本节只放结论。

| 维度 | 结论 |
|---|---|
| **同一水平** | 五档评级机制（Buy/Overweight/Hold/Underweight/Sell）—— 同词表、同结构，实测可用**上游原生解析器**逐棵读出，可无缝替代 |
| **本项目多** | 量化因子回测、因子有效性**诚实标注**、数据缺口台账 + 门禁、报告质量记分卡、**零 LLM API 费** |
| ⚠️ **本项目少** | **决策记忆 / 反思机制未接入** |

**关于「少」的那一项**（容易被「越用越好」这句话误导）：

- **上游有**：`agents/utils/memory.py` + `graph/reflection.py`，`default_config.py` 里**设了默认路径**
  ⇒ 上游每轮 `store_decision` 写入决策，并把历史反思经 `get_past_context`
  **重新注入后续 prompt** —— 这是**真正的跨轮学习回路**。
- **本项目没有**：`wb_analysis/` 与 `quant/` 全库**零调用** `TradingMemoryLog` / `Reflector`。
- **替代方案不等价**：本项目用「记分卡 + `RULES.md` / `DOMAINS.md` 沉淀」替代，
  但记分卡只衡量**报告质量**、**不回流进角色 prompt**；RULES/DOMAINS 靠**人工沉淀**、非自动注入。

⇒ **不要让「越用越好」暗示本项目已具备上游那种自动跨轮学习。**

## 怎么在这台机器上跑

本机自带隔离 Python，**不要换成别的**：

```
./.venv/Scripts/python.exe
```

**第一次看这个项目，先读地图**：**[`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md)** ——
一页说明每个目录/文件是干什么的、哪些是上游自带的、跑一次会动到哪些地方。

详细手册与规范：

- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) —— 端到端运行手册：采集 → 12 角色研判推理 → 渲染 → 报告树。
- [`docs/SCREENER.md`](docs/SCREENER.md) —— 量化选股子系统手册：多因子漏斗、选股引擎与回测体系。
- [`docs/RULES.md`](docs/RULES.md) —— 核心量化开发与门禁铁律全文（时点闸门、双口径计算、SEC 原值核验与避坑指南；条数以文档自报为准）。
- [`docs/DOMAINS.md`](docs/DOMAINS.md) —— 领域口径与金融指标定义（指数加权、ERP 风险溢价、期权曲面、美债期限利差）。

### ★★ 冷启动清单（上下文为零时，严格按这六步走）

> 这一节是给**第一次接触本项目、没有任何历史上下文**的执行者（人或模型）看的。
> 每一步都有对应的硬门禁；**跳步不会立刻报错，但会在最后一道门禁或下一轮暴露**。

| # | 动作 | 跳过的后果 | 拦你的门禁 |
|---|---|---|---|
| 1 | `scripts/_health.py` 确认基线全绿 | 带着坏基线开工，后面所有判断都不可信 | 体检 14 项 |
| 2 | **认标的** → 选对采集器（见下表五条链路） | 用错采集器 ⇒ 全通道报错或取到错口径 | 采集器自带 `--date` 口径守卫 |
| 3 | 采集 → 派生 → 写 `0_brief.md` | 没有简报，角色会各自编事实 | `_role_prompt.py` 缺 brief 直接返回 1 |
| 4 | **12 角色必须在各自独立的上下文里写**（见 `docs/AGENT_PROTOCOL.md`） | 牛熊变自问自答，**报告照样能过所有门禁** ← 最危险 | `_precheck` 的「辩论独立性」（>70% 重合率告警） |
| 5 | `_gen_meta.py` → `assemble.py --from-dir <草稿目录>` | 直接给 ticker 会命中空骨架 | `assemble.py` 硬门禁：正文为空拒绝渲染（返回 2） |
| 6 | 四道校验 → `_seal_run.py --apply` → 再跑一次 `_health.py` | 中间产物堆在 `wb_analysis/`，下一轮会互相污染 | 「待封存产物」「瞬态目录」 |

**三个最容易跑偏的点（都不是语法错误，是判断错误）**：

1. **把 12 个角色塞进一个上下文**：形式全合规、评级也对，但牛熊论证高度同质 —— 这是唯一
   「能过全部门禁却实质失效」的失败模式。判据：`_precheck` 会算牛熊引用数字的重合率，
   >70% 即告警（协议判据见 `docs/AGENT_PROTOCOL.md` §4）。
2. **改证据包来迁就结论**：角色把某个数字改成自己想引用的值，`_lint_drafts` 的数字溯源
   会以被改后的证据包为基准 ⇒ **自我印证**。现在采集时会写 `<T>_<date>.md.integrity.json`
   （sha256），`_precheck` 比对不一致直接 FAIL。
3. **把 `_precheck` 的 WARN 当成 PASS**：WARN 是「待人工过目」，不是「没问题」。
   典型是「同字段多值未在简报声明」（如 52 周高低有两个数据源）与「未溯源数字」。

**日期口径（最容易错的一条）**：美股 `--date` ＝ **美东当日**（不是本机日期、也不是末根 bar 日期）；
A 股/港股取该市场交易日。盘中采集会拿到半日快照，采集器会按铁律 2 剔除未收盘 bar 并在证据包里声明。

### ★★ 五条链路（先认标的，再选采集器）

**判据：这条标的属于哪一类 → 用哪个采集器。选错采集器是新手最常见的错。**

| 标的类型 | 采集器 | 派生脚本 |
|---|---|---|
| **美股个股 / ETF**（`NVDA`、`AVGO`…） | `wb_analysis/collect.py <TICKER>`（多通道免费数据） | `_gen_derived_stock.py <TICKER> <日期>` |
| **美股指数**（`NDX` / `SPX`） | `wb_analysis/collect_index.py --index NDX` | `_gen_derived_ndx.py <IDX> <日期>` |
| **A 股 ETF**（`512400.SS`、`515100`…） | `wb_analysis/collect_a_etf.py --ticker <代码>`（westock CLI） | `_derive_a_etf.py <TICKER> <日期>`（**自行落盘**） |
| **A 股个股**（`601899.SS` 紫金矿业…） | `wb_analysis/collect_a_stock.py --ticker <代码>`（westock CLI） | `_gen_derived_stock.py <TICKER> <日期>` |
| **港股指数**（`hkHSTECH`…） | `wb_analysis/collect_hk_index.py --index hkHSTECH --date <日期>` | **无专属派生脚本**（估值由采集器内部聚合） |

```bash
# ── 链路 A：美股个股（例：AMD）──
./.venv/Scripts/python.exe wb_analysis/collect.py AMD --date <美东当日>
./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py AMD <日期>

# ── 链路 B：美股指数（NDX / SPX）──
./.venv/Scripts/python.exe wb_analysis/collect_index.py --date <美东当日> --index NDX
./.venv/Scripts/python.exe wb_analysis/_gen_derived_ndx.py NDX <日期>

# ── 链路 C：A 股 ETF（行业 / 策略 / 商品三种模式）──
#   未登记的标的会自动按 mode 推断；商品型（黄金/白银）会由名称自动判定
./.venv/Scripts/python.exe wb_analysis/collect_a_etf.py --ticker 512400.SS --date <A股交易日>
./.venv/Scripts/python.exe wb_analysis/_derive_a_etf.py 512400.SS <日期>   # 直接写 drafts 的 0_derived.md

# ── 链路 D：A 股个股（行情/K线/技术指标/筹码/资金流/两融/北向/股东/公告/三大报表/大宗联动）──
#   ★ 与 A 股 ETF 是**两个不同采集器**：个股走 collect_a_stock.py，ETF 走 collect_a_etf.py
./.venv/Scripts/python.exe wb_analysis/collect_a_stock.py --ticker 601899.SS --date <A股交易日>
./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py 601899.SS <日期>

# ── 链路 E：港股指数 ──
./.venv/Scripts/python.exe wb_analysis/collect_hk_index.py --index hkHSTECH --date <港股交易日>
```

**⚠️ 日期口径各不相同，别混用**：
- 美股链路的 `--date` ＝ **美东当日**（不是本机日期、也不是末根 bar 日期）；
- A 股 / 港股链路的 `--date` 取**该市场的交易日**；盘中采集会拿到半日快照 ⇒
  **复盘历史基准日时务必确认采集器已透传日期**（`collect_a_etf.py` 已修）。

### 采集之后的四步（三条链路通用）

```bash
# 1) 写简报（唯一事实源，12 角色都只读它）
#    路径：wb_analysis/drafts/<TICKER>_<日期>/0_brief.md
# 2) 写 12 角色草稿（按 wb_analysis/FRAMEWORK.md 的角色契约）
#    wb_analysis/drafts/<TICKER>_<日期>/{1_analysts,2_research,3_trading,4_risk}/
# 3) 生成运行清单（缺它渲染会退出码 2）
./.venv/Scripts/python.exe wb_analysis/_gen_meta.py <TICKER>_<日期>

# 4) 渲染 → reports/<TICKER>/<TICKER>_<时间戳>/
./.venv/Scripts/python.exe wb_analysis/assemble.py --from-dir wb_analysis/drafts/<TICKER>_<日期>
```

⚠️ `--from-dir` 必须指向 `wb_analysis/drafts/<TICKER>_<日期>`；直接用 `<TICKER> --date` 会命中
`wb_analysis/analysis/` 下的空骨架 JSON，渲染出评级全 Hold、正文全空的假报告。

### 交付前必跑的校验（顺序不可颠倒）

```bash
# ① 契约合规（结论块外不得有裸英文评级词）
./.venv/Scripts/python.exe wb_analysis/_lint_drafts.py wb_analysis/drafts/<T>_<日期> wb_analysis/evidence/<T>_<日期>.md
# ② 评级词位置（每个白名单席位全文恰 1 处）
./.venv/Scripts/python.exe wb_analysis/_verify_ratings.py wb_analysis/drafts/<T>_<日期>
# ③ 交付门禁（唯一总入口，项数以脚本自报为准）
./.venv/Scripts/python.exe wb_analysis/_precheck.py wb_analysis/drafts/<T>_<日期> \
    --evidence wb_analysis/evidence/<T>_<日期>.md --report reports/<T>/<树>/
# ④ 反读（渲染后的树能否被解析器正确读出评级）
./.venv/Scripts/python.exe wb_analysis/_verify_report.py reports/<T>/<树>/
# ⑤ 封存（把中间产物收进树内审计包；需等静默期通过）
./.venv/Scripts/python.exe wb_analysis/_seal_run.py --run <T> <日期> --apply
```

**判断"我有没有跑对"的一句话判据**：跑完后 `wb_analysis/{evidence,drafts,analysis}` 应当**变空**
（产物已收进 `_source.zip`）；若还堆着东西，说明第 ⑤ 步没做完。

## 目录速查

- `wb_analysis/` —— 本地改造核心：`FRAMEWORK.md`（12 角色框架说明）、免费数据采集
  （`collect.py` 美股个股 / `collect_index.py` 美股指数 / `collect_a_etf.py` A股ETF /
  `collect_hk_index.py` 港股指数 / `collect_treasury.py` 美债专题）、报告渲染（`assemble.py`）；
  `drafts/`、`analysis/`、`evidence/` 存放各角色手写草稿、成品与分析素材（**均为瞬态，跑完即封存**）。
  · ★ **`_option_source.py`** —— 期权数据源适配器（CBOE 官方延迟报价）：**盘前/盘后自动启用**，
    拿的是「上一时段收盘快照」而非实时报价；**仅美股个股与主要 ETF 有效**，指数符号与 A 股 ETF
    不覆盖（详见 [`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md) §3.1）。
- `reports/` —— 渲染产出的报告树，按 `reports/<TICKER>/<TICKER>_<时间戳>/` 组织。
- `quant/` —— 量化引擎（选股漏斗 / 因子回测 / 财报取数 / 价格历史），详见 `docs/SCREENER.md`。
- `tradingagents/` —— 上游原始 LLM agent 框架包。本项目已弃用其自动分析链路，仅作依赖 / 参考保留。
- `docs/RULES.md` —— **工程铁律全文**（时点闸门、双口径计算、SEC 原值核验等；条数以文档自报为准）。
  ★ 开工前先读它，**只读索引会丢细节**。
- `docs/DOMAINS.md` —— **领域口径与指标定义**（指数加权、ERP、期权曲面、美债期限利差），碰到该领域时读。
- `docs/TOOLS.md` —— **自动生成的工具索引**（所有脚本 + 用途 + 用法），想知道"有没有现成工具"就查它。
- `tests/` —— 单元与回归测试。

> ⚠️ 仓库里另有 `.workbuddy-ai/`（**本地运行痕迹**：按天日志、回滚包、主题索引）。
> 它已被 `.gitignore` 忽略、**不在对外仓库中** ⇒ 克隆后看不到它是正常的。
> 需要长期留存的判据与领域知识，已分别落在 `docs/RULES.md` 与 `docs/DOMAINS.md`。

## License

Apache License 2.0。版权归属上游作者（Yijia Xiao et al.），详见 [`LICENSE`](LICENSE)。

## Citation

请引用上游工作：

Xiao, Y., Sun, E., Luo, D., & Wang, W. (2025). *TradingAgents: Multi-Agents LLM Financial Trading Framework*. arXiv:2412.20138. https://arxiv.org/abs/2412.20138
