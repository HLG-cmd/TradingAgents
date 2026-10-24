# 项目地图

> 一页看懂这个项目：**每个目录是干什么的、哪些是上游自带的、哪些是我们自己加的、跑一次会动到哪些地方**。
> 看不懂目录名时先回到这一页。

---

## 1. 这个项目由两层拼起来

| 层 | 谁写的 | 在哪 | 要不要动 |
|---|---|---|---|
| **上游本体**（TauricResearch 的 TradingAgents） | 开源作者 | `tradingagents/`、`cli/`、`tests/`、`assets/`、大部分根目录配置文件 | **尽量不动**（要能跟上游同步） |
| **我们自建的分析层**（真正干活的部分） | 我们 | `wb_analysis/`、`scripts/`、`reports/`、`quant/` | 随便改 |

**一句话记忆**：`tradingagents/` 里是"别人的引擎"，`wb_analysis/` 里是"我们的流水线"。

---

## 2. 顶层目录速查

| 目录/文件 | 是什么 | 跑一次会不会动 |
|---|---|---|
| **`wb_analysis/`** | **我们的流水线**：采集数据、算指标、跑门禁、写简报 | 只动 `evidence/ drafts/ analysis/` 三个子目录 |
| **`quant/`** | **我们的量化引擎**：选股漏斗、因子回测、财报取数、价格历史 | 不动 |
| **`scripts/`** | **我们的工具**：核验、清理、体检类的小工具（含生命周期声明） | 不动 |
| **`reports/`** | **产出**：每个标的一个目录，里面是最终报告 + 审计包 | 新增一棵树 |
| `tradingagents/` | 上游引擎（多智能体框架本体） | 不动 |
| `cli/` | 上游的命令行界面 | 不动 |
| `tests/` | 单元测试（含上游框架与自建流水线/量化/门禁测试） | 不动 |
| `docs/` | **说明文档**（运行手册、选股手册、RULES.md 门禁准则、DOMAINS.md 领域口径规范） | 不动 |

### 自建代码都在 `quant/`（2026-09-23 起）
以前 9 个 `.py` 散在**项目根目录**，看不出哪些是上游自带的、哪些是我们写的；现已收进 `quant/` 包。

| 类型 | 文件 | 说明 |
|---|---|---|
| **库**（被别人 import） | `screener_engine.py` · `stock_pools.py` · `edgar_fundamentals.py` · `price_history.py` | 导入方式 `from quant.xxx import yyy`。⚠️ **引用次数刻意不写** —— 它会漂移且没人记得回来改（见下方 §2.5 的告诫） |
| **入口脚本**（直接运行） | `smart_screener.py` · `wb_deep_dive.py` · `factor_backtest.py` · `fundamental_backtest.py` · `cleanup_cache.py` | `python quant/xxx.py` |

> **项目根目录现在没有任何 `.py` 文件** —— 看到 `.py` 就知道它在某个包里，不在根目录瞎放。

### 两个启动器（每条链 = `.bat` → `.ps1` → 目标）
| 文件 | 作用 |
|---|---|
| `screen.bat` → `run_screener.ps1` → `quant/smart_screener.py` | 启动量化选股漏斗 |
| `start.bat` → `run_tradingagents.ps1` → 上游 CLI | 启动上游原版界面（我们基本不用） |

---

## 2.5 ★ 新文件该放哪儿（判据，遇到新东西按顺序问三句）

| 顺序 | 问题 | 答"是"就去 |
|---|---|---|
| 1 | **跑一次分析会用到它吗？**（采集 / 派生 / 渲染 / 核验 / 门禁 / 台账 / 封存） | **`wb_analysis/`** |
| 2 | 只在**改代码 / 排障 / 整理项目**时用？ | **`scripts/`** |
| 3 | 是**被上面两者调用的可复用引擎**？ | **`quant/`** |
| — | 是**产出**（报告、数据产品、专题）？ | **`reports/`** |

**验收标准：同一个职责只出现在一个地方。**
⇒ 新东西放进去后，跑 `scripts/_tidy_scripts.py --apply` 重生成 `docs/TOOLS.md`（索引里带目录列，错位一眼可见）。

### 现状（2026-09-23 按上述判据重归位后）

| 目录 | 装什么 | 判断一句话 |
|---|---|---|
| `wb_analysis/` | **跑一次分析要用的一切**：采集 / 派生 / 渲染 / 门禁 / 缺口台账 / 封存 / 报告索引 / **独立核验**（核验是流程的强制环节） | 跑报告时会碰到 |
| `scripts/` | **只在维护排障时用**：健康检查 / 生命周期管理 / 报告与项目清理重排 / 回滚包管理 | 只在"修东西"时碰到 |
| `quant/` | **引擎库**：选股 / 回测 / 财报取数 / 价格历史 | 被上面两者调用 |

> ⚠️ **本表刻意不写文件数量** —— 硬编码的数字必然漂移（本轮实测「38/11/10 个 .py」已全部与现状不符，
> 而没人会记得回来改）。**精确清单与数量以 `docs/TOOLS.md`（自动生成）为唯一口径**，手写文档只描述"装什么"。

> 重归位前：核验类工具**一半在 `wb_analysis/`、一半在 `scripts/`**（8:8）。
> 那种划分依据是"当时我把它放哪了"，不是"它是干什么的" ⇒ 已按判据纠正。

## 3. `wb_analysis/` 里面（最容易看不懂的地方）

| 子目录/文件 | 是什么 | 生命周期 |
|---|---|---|
| `collect.py` | **采集器**：美股个股 / ETF 多通道免费数据（精确通道数以证据包末尾健康度汇总为准） | 代码，长期 |
| `collect_index.py` | **采集器**：美股指数（`NDX` / `SPX`） | 代码，长期 |
| `collect_a_etf.py` | **采集器**：A 股 ETF（`--mode industry\|strategy\|commodity`，走 westock CLI） | 代码，长期 |
| `collect_a_stock.py` | **采集器**：A 股个股（`--ticker 601899.SS`，走 westock CLI） | 代码，长期 |
| `collect_hk_index.py` | **采集器**：港股指数（走 westock CLI） | 代码，长期 |
| `collect_treasury.py` | **采集器**：美债专题（宏观曲线，不服务单一标的） | 代码，长期 |
| `_option_source.py` | **期权数据源适配器**：把 CBOE 官方延迟报价适配成 yfinance 同形接口。**盘前/盘后自动启用**（见下方 §3.1） | 代码，长期 |
| `_derive_stock.py` / `_derive_ndx.py` / `_derive_a_etf.py` | **派生指标**：均线、ATR、分位等（分别对个股 / 指数 / A股ETF） | 代码，长期 |
| `_gen_derived_stock.py` / `_gen_derived_ndx.py` | **派生指标落盘器**（把上一步的 stdout 写成 `0_derived.md`；`_derive_a_etf.py` 自行落盘，无需此步） | 代码，长期 |
| `_gen_meta.py` | **运行清单生成**（缺 `meta.json` ⇒ 渲染退出码 2） | 代码，长期 |
| `assemble.py` | **渲染器**：把 12 个角色的 md 拼成报告树 | 代码，长期 |
| `_precheck.py` | **交付门禁**（唯一入口；项数以脚本自报为准，含缺口台账/小节正文/快照自洽/收益质量/评级契约/口径对账/数字溯源/时序/报告树反读） | 代码，长期 |
| `_selftest.py` | **门禁自检**（双向夹具，确认门禁本身没坏；项数以脚本自报为准） | 代码，长期 |
| `_gap_ledger.py` | **数据缺口台账** | 代码，长期 |
| `_role_prompt.py` | **单角色提示词生成器**：跨平台拆分 12 个角色（白名单/禁读/契约/篇幅/自验），见 `docs/AGENT_PROTOCOL.md` | 代码，长期 |
| `_seal_run.py` | **产物封存**：把一轮的中间产物打包进报告树 | 代码，长期 |
| `_reports_index.py` | **报告索引 + 卫生检查** | 代码，长期 |
| `FRAMEWORK.md` | **12 角色输出契约**（子智能体读它） | 文档 |
| `_contract.py` | **契约常量的唯一来源**（五档/三档词表、`Rating:`/`Action:` 标签、`FINAL TRANSACTION PROPOSAL` 都从这里取；门禁们 import 它，**勿再手写正则**） | 代码，长期 |
| `evidence/` | **证据包**：采集出来的原始事实清单 | ★ **瞬态**：跑完即封存，平时应为空 |
| `drafts/` | **草稿**：12 个角色写的 md + 简报 + 约束 | ★ **瞬态**：跑完即封存 |
| `analysis/` | **分析 JSON**：给上游入口用的汇总 | ★ **瞬态**：跑完即封存 |
| `_cache/` | 共享参考数据（ERP 历史序列、黄金面板等） | 长期缓存 |

> **"瞬态"的意思**：跑一轮时它们会有内容，`_seal_run.py` 封存后它们就空了。
> **看到它们空着是正常的，不是坏了。**

### 3.1 ★ 期权数据源随时点自动切换（2026-10-17 起）

**一句话**：盘中用 yfinance（实时）；**盘前 / 盘后 / 非交易日自动切 CBOE 官方延迟报价**。

| 采集时点（美东） | 走哪个源 | 拿到的是什么 |
|---|---|---|
| 09:30–16:00 | yfinance 主源 | 实时（`lastTradeDate` 距今 0.0 天） |
| 盘前 / 盘后 / 非交易日 | **CBOE 官方延迟报价** | **上一时段收盘快照**（15 分钟延迟） |

> ⚠️ 声明的是**实际用上的源**：若盘前 CBOE 取数失败（如指数 / A 股 ETF 返回 403），
> 会自动退回 yfinance 并在 `source_note` 里写明「回退 yfinance 主源」。
> 证据包里的「数据来源」行必须与这里的实际值一致。

**为什么需要它**：yfinance 的期权链只在常规时段实时刷新；盘前/盘后它只返回**上一交易日的
残留挂单** —— `bid`/`ask` 格式完全合法，只有 `lastTradeDate` 陈旧（实测 NDX 轮盘前：
扫 29 个到期日、387 个有双边报价合约、**合格样本 0**）。CBOE 是**做市商报价链**，
不依赖「该合约当天有没有成交」⇒ 盘前仍能重建完整期限结构。

⚠️ **这不是「解除时间限制」，是「降级可用」** —— 三条边界必须记住：

1. **拿的是上一时段快照，不是实时报价**。CBOE 延长时段（GTH 20:15–09:25）**只覆盖
   SPX / SPXW / XSP**，**不含股票与 ETF 期权** ⇒ 盘前拿到的成交**必然止于上一交易日**。
   这是市场本身没成交，**不是 bug**。
2. **不可用于「此刻 / 盘中」类论断**，也不得与盘中口径的 IV **跨轮直接比较**。
3. **两个源的 IV / 偏斜口径不同，数值不可混用**（CBOE 是交易所模型直出，与项目自建
   BSM 反解差异可达数 pp）⇒ 采用时全线统一口径并在证据包声明来源。

**覆盖范围（实测）**：

| 类型 | 可用 | 说明 |
|---|---|---|
| 美股个股 / 主要 ETF | ✅ | NFLX / GOOG / AVGO / NVDA / ORCL / SOFI / QQQ / SPY… |
| **指数符号**（NDX / ^NDX） | ❌ | 指数本身没有期权（**符合预期**，仍用 ETF 代理） |
| **A 股 ETF** | ❌ | 非美股；且 A 股行业/策略/商品型 ETF 本就无场内期权（**结构性缺失**，换源解决不了） |

**落地位置**：判据 = `_thresholds.option_source_decision()`（**唯一来源**，消费方只许转发）；
取数 = `_option_source.py`；台账 = `RULES["CBOE_fallback_used"]`（B 类 / 决定性）；
自检 = `_selftest.py`；回归 = `tests/test_option_source.py`。

---

## 4. `reports/` 里面

```
reports/
├── INDEX.md                 ← 自动生成的索引：哪个标的最新、评级、数据完整度
├── <标的>/
│   └── <标的>_<时间戳>/      ← 一次交付 = 一棵报告树
│       ├── 1_analysts/           4 位分析师
│       ├── 2_research/           多空辩论 + 研究经理裁定
│       ├── 3_trading/            交易员的执行方案
│       ├── 4_risk/               3 位风险席（激进/保守/中性）
│       └── 5_portfolio/          组合经理终审 ⇒ `decision.md`
│                                 ⚠️ **草稿名与渲染名不同**：草稿是 `4_risk/portfolio_manager.md`，
│                                    渲染后落到 `5_portfolio/decision.md`（刻意的，别当 bug 修）
│       ├── complete_report.md    ★ 想读报告只看这一个文件
│       ├── RUN.json              运行清单：数据基准日 / 来源草稿 / 证据文件 / 评级 / **代码版本**
│       └── _source.zip           审计包：证据包 + 草稿 + 分析 JSON（报告里每个数字都能在里面溯源）
├── _datasets/                   雷达表、回测表等数据产品
├── _other/                      非 12 角色的专题报告
├── _archive/                    归档 + 删除清单（可审计）
└── _audit/                      审计类文档
```

**读报告只需要看 `complete_report.md`。**
**想核对某个数字的来源，就打开同目录的 `_source.zip`（或看 `SOURCE_MANIFEST.json` 里列了包内有什么）。**

---

## 5. 跑一次会动到哪些地方

```
① 采集   → wb_analysis/evidence/<标的>_<日期>.{md,json}          （瞬态）
② 派生   → wb_analysis/evidence/<标的>_<日期>.derived.md          （瞬态）
③ 简报   → wb_analysis/drafts/<标的>_<日期>/0_brief.md            （瞬态）
④ 12 角色→ wb_analysis/drafts/<标的>_<日期>/{1_analysts..4_risk}/  （瞬态）
⑤ 渲染   → reports/<标的>/<标的>_<时间戳>/                         （留存）
⑥ 门禁   → 只读；顺手更新 reports/INDEX.md
⑦ 封存   → 把 ①~③ 打包进 reports/<标的>/<时间戳>/_source.zip，清空瞬态目录
```

**所以跑完之后，正常情况下：**
- `reports/` 多一棵树（含最终报告 + 审计包）
- `wb_analysis/evidence|drafts|analysis` **是空的**

如果你看到瞬态目录里堆了东西，说明**第 ⑦ 步没做**，跑一下：
```bash
./.venv/Scripts/python.exe wb_analysis/_seal_run.py --plan     # 看有哪些待封存
./.venv/Scripts/python.exe wb_analysis/_seal_run.py --all --apply
```

---

## 5.5 ★ 五条链路怎么跑（先认标的，再选采集器）

**判据：标的属于哪一类 → 用哪个采集器。选错采集器是新手最常见的错。**

| 标的类型 | 采集器 | 下一步 |
|---|---|---|
| **美股个股 / ETF** | `wb_analysis/collect.py <TICKER>` | `_gen_derived_stock.py <TICKER> <日期>` |
| **美股指数**（NDX/SPX） | `wb_analysis/collect_index.py --index NDX` | `_gen_derived_ndx.py <IDX> <日期>` |
| **A 股 ETF** | `wb_analysis/collect_a_etf.py --ticker <代码>` | `_derive_a_etf.py <TICKER> <日期>`（自落盘） |
| **A 股个股** | `wb_analysis/collect_a_stock.py --ticker <代码>` | `_gen_derived_stock.py <TICKER> <日期>` |
| **港股指数** | `wb_analysis/collect_hk_index.py --index <指数> --date <日期>` | 无专属派生（采集器内部聚合估值） |

```bash
# 美股个股
./.venv/Scripts/python.exe wb_analysis/collect.py AMD --date <美东当日>
# 美股指数
./.venv/Scripts/python.exe wb_analysis/collect_index.py --date <美东当日> --index NDX
# A 股 ETF（行业/策略/商品三模式自动判定）
./.venv/Scripts/python.exe wb_analysis/collect_a_etf.py --ticker 512400.SS --date <A股交易日>
# A 股个股（★ 与 A 股 ETF 是两个不同采集器，别混用）
./.venv/Scripts/python.exe wb_analysis/collect_a_stock.py --ticker 601899.SS --date <A股交易日>
./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py 601899.SS <A股交易日>
# 港股指数
./.venv/Scripts/python.exe wb_analysis/collect_hk_index.py --index hkHSTECH --date <港股交易日>
```

**⚠️ 日期口径各不相同**：美股链路 `--date` ＝ **美东当日**；A 股 / 港股链路取**该市场交易日**。

采集完之后的四步（写简报 → 写 12 角色 → `_gen_meta.py` → `assemble.py --from-dir`）
与交付前五道校验（`_lint_drafts` → `_verify_ratings` → `_precheck` → `_verify_report` → `_seal_run`），
**完整配方见 [`../README.md`](../README.md) 的「怎么在这台机器上跑」一节**（含每步的判据与常见错法）。

**一句话自检**：跑完后 `wb_analysis/{evidence,drafts,analysis}` 应当是**空的**（产物已收进 `_source.zip`）。

---

## 6. 常用的命令

```bash
# ★ 一条命令看整个项目状态（推荐每次开工/收工跑一次）
./.venv/Scripts/python.exe scripts/_health.py
#   预算类检查（堆积预算 / 长函数预算）只做两件事：让占用**可见**、让指标**只减不增**；
#   它们不追求「清零」—— 长函数要拆也得先有可测性，硬拆只会把风险从「难测」变成「易错」。
#   CI 上跑 `--ci`：只执行 7 项**仓库内生**检查（门禁自检/脚本生命周期/版本库忽略/
#   根目录整洁/换行归一化/长函数预算/文档漂移），不依赖本地 reports 与 .env。

# 工具索引（自动生成：所有脚本 + 用途 + 用法）
#   → docs/TOOLS.md

# 看报告层是否又有堆积、孤儿、缺草稿
./.venv/Scripts/python.exe wb_analysis/_reports_index.py

# 看「报告质量」是升还是降（同标的逐轮比较 —— 这是"越用越好"的唯一判据）
./.venv/Scripts/python.exe wb_analysis/_scorecard.py --trend

# 交付前门禁（唯一入口；项数以脚本自报为准）
./.venv/Scripts/python.exe wb_analysis/_precheck.py wb_analysis/drafts/<P>_<日期> \
    --evidence wb_analysis/evidence/<P>_<日期>.md --report reports/<标的>/<树>/

# 确认门禁本身没坏（双向夹具自检）
./.venv/Scripts/python.exe wb_analysis/_selftest.py

# 跑完清理：把中间产物收进报告树
./.venv/Scripts/python.exe wb_analysis/_seal_run.py --all --apply
```

---

## 7. 判断"这个东西能不能删"的三条规则

1. **在 `reports/` 里** → 是产出，删之前先想想有没有引用（`reports/INDEX.md` 会提示）。
2. **在 `wb_analysis/evidence|drafts|analysis` 里** → 瞬态，**先封存再删**：
   `_seal_run.py --all --apply`（它会先打包、逐项校验，通过才删）。
3. **`scripts/` 里带 `# lifecycle: oneoff` 的** → 一次性探针，已经躺在 `scripts/_oneoff/`，
   是"当时怎么得出结论"的审计线索，**可以留，别删**；真要清就用 `--orphans` 模式打包后清。

> 通用铁律：**删之前先打包 + 逐项校验**，校验不过就中止。项目里所有清理工具都遵守这条。
