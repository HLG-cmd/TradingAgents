# 工具索引（自动生成，勿手改）

- 生成时间：2026-10-21 23:25
- 覆盖目录：`quant/` · `wb_analysis/` · `scripts/`
- **每个 `.py` 头部必须声明 `# lifecycle: reusable | maintenance | oneoff`**；
  新增探针用 `scripts/_tidy_scripts.py --new <名字> --serves <标的> <日期>` 生成。

| 身份 | 含义 | 归位 |
|---|---|---|
| `reusable` | 每次分析都可能用到 | 留在原目录 |
| `maintenance` | 门禁 / 清理 / 索引 / 健康检查 | 留在原目录 |
| `oneoff` | 为某次结论临时写的探针（**审计线索，不删**） | 移入同级 `_oneoff/` |


## reusable —— 每次分析都可能用到

| 文件 | 用途 | 用法 / 服务于 |
|---|---|---|
| `quant/cleanup_cache.py` | 缓存清理工具 —— 任务结束后想释放磁盘时用。 | ./.venv/Scripts/python.exe quant/cleanup_cache.py |
| `quant/edgar_fundamentals.py` | SEC EDGAR 时点基本面（point-in-time fundamentals）—— 让 80% 的权重变得可回测。 | ./.venv/Scripts/python.exe quant/edgar_fundamentals.py |
| `quant/factor_backtest.py` | 因子有效性回测（时点严格 / point-in-time） | ./.venv/Scripts/python.exe quant/factor_backtest.py |
| `quant/fundamental_backtest.py` | 四因子时点回测 —— 用 SEC EDGAR 重建历史基本面，验证那 80% 的权重。 | ./.venv/Scripts/python.exe quant/fundamental_backtest.py |
| `quant/price_history.py` | 长周期价格历史（10~20 年）—— 解开长周期回测的硬瓶颈。 | ./.venv/Scripts/python.exe quant/price_history.py |
| `quant/screener_engine.py` | 多因子量化选股雷达引擎 (Multi-Factor GARP Screener Engine) | ./.venv/Scripts/python.exe quant/screener_engine.py |
| `quant/smart_screener.py` | （无文档字符串） | ./.venv/Scripts/python.exe quant/smart_screener.py |
| `quant/stock_pools.py` | 美股核心股票池定义与动态获取模块。 | ./.venv/Scripts/python.exe quant/stock_pools.py |
| `quant/wb_deep_dive.py` | 零成本深度投研流水线 —— 一站式自动化入口。 | ./.venv/Scripts/python.exe quant/wb_deep_dive.py |
| `scripts/_settlement.py` | 历史决策回溯结算工具（吸收上游 TauricResearch v0.6.0 settlement 思想） | ./.venv/Scripts/python.exe scripts/_settlement.py |
| `scripts/_verify_pack_tree.py` | 验证「交付树」与「审计包 _source.zip」**逐项内容一致**（通用版）。 | 任意标的 / 任意轮次 |
| `scripts/run_nasdaq_premarket_task.py` | 纳指100（NDX）盘前利好利空情报汇总与开盘走势预判自动化任务。 | ./.venv/Scripts/python.exe scripts/run_nasdaq_premarket_task.py [--date YYYY-MM-DD] |
| `wb_analysis/_audit_empty_sections.py` | 审计证据包的「**小节正文为空**」—— 抓「通道全绿但内容是空」这类静默失败。 | ./.venv/Scripts/python.exe wb_analysis/_audit_empty_sections.py <evidence.md> [--strict] |
| `wb_analysis/_check_residuals.py` | 订正残留检查：防止「改了上游、忘了回头清下游」。 | ./.venv/Scripts/python.exe wb_analysis/_check_residuals.py <草稿目录> |
| `wb_analysis/_check_role_files.py` | 角色文件体检：篇幅 / 裸五档英文词 / 越界 PROPOSAL / 合规声明 / 必需小节。 | ./.venv/Scripts/python.exe wb_analysis/_check_role_files.py |
| `wb_analysis/_clock.py` | 唯一时间源（Single source of truth for time）。 | — |
| `wb_analysis/_contract.py` | 12 角色输出契约的**唯一常量来源** —— 评级词、档位、白名单、正则全在这里定义一次。 | from wb_analysis._contract import ...   （库；被门禁们 import，不单独运行） |
| `wb_analysis/_crosscheck_nasdaq.py` | 用 Nasdaq 官方公开 API 独立复核证据包 §1 的日线 OHLC（数据来源真实性核验）。 | ./.venv/Scripts/python.exe wb_analysis/_crosscheck_nasdaq.py <标的> [基准日]\n#   · 个股/ETF：官方接口直接逐条核对 OHLC\n#   · 指数（NDX/SPX）：官方接口不支持指数（rCode=400）⇒ 自动改用 QQQ/SPY 代理，只核对**日涨跌幅一致性** |
| `wb_analysis/_derive_a_etf.py` | A股 ETF 派生指标计算器：从 A 股 ETF 证据包导出「需要算术推导」的二级指标。 | ./.venv/Scripts/python.exe wb_analysis/_derive_a_etf.py 515100 2026-10-13 |
| `wb_analysis/_derive_ndx.py` | 派生指标计算器：从指数证据包导出所有「需要算术推导」的二级指标（支持 NDX / SPX）。 | ./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py |
| `wb_analysis/_derive_stock.py` | 个股派生指标计算器：从个股证据包导出所有「需要算术推导」的二级指标。 | ./.venv/Scripts/python.exe wb_analysis/_derive_stock.py |
| `wb_analysis/_erp_retry.py` | ERP 计算的重试包装器。 | ./.venv/Scripts/python.exe wb_analysis/_erp_retry.py |
| `wb_analysis/_gen_derived_ndx.py` | 把 _derive_ndx.py 的 stdout 落盘（避免 shell 重定向写中文 + /tmp 路径问题）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_derived_ndx.py |
| `wb_analysis/_gen_derived_stock.py` | 把 _derive_stock.py 的 stdout 落成证据包同级文件（避免 shell 重定向写中文）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py |
| `wb_analysis/_gen_meta.py` | 为草稿目录生成 `meta.json`（`assemble.py --from-dir` 的**必备**输入）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_meta.py GOOG_2026-10-01 [NDX_2026-10-01 ...] |
| `wb_analysis/_gen_supplement.py` | 生成 `<TICKER>_<date>.supplement.md`：证据包 §3 被上游扣留时的**一等替代证据源**。 | ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py <TICKER> <YYYY-MM-DD> |
| `wb_analysis/_insider_agg.py` | 从证据包 §8 内部人交易 CSV 段落聚合买卖统计（回原始样本重数，不依赖任何摘要）。 | ./.venv/Scripts/python.exe wb_analysis/_insider_agg.py |
| `wb_analysis/_log.py` | 流水线日志与"降级留痕"。 | — |
| `wb_analysis/_nasdaq_official.py` | 拉 Nasdaq 官方 API 的日线并打印，用于人工对照 NDX 证据包 §1。 | ./.venv/Scripts/python.exe wb_analysis/_nasdaq_official.py |
| `wb_analysis/_net.py` | 统一的网络重试。 | — |
| `wb_analysis/_option_source.py` | 期权链数据源适配器：把 **CBOE 官方延迟报价** 适配成 yfinance ``Ticker`` 的接口形状。 | from wb_analysis._option_source import fetch_chain; （库，被采集器 import） |
| `wb_analysis/_paths.py` | `reports/` 布局与「草稿扫描跳过」的**唯一常量来源** —— 目录名 / 功能目录 / 顶层白名单 / 归档跳过表。 | from wb_analysis._paths import TREE_RE, FUNC_DIRS, ALLOWED_TOP, SKIP_ARCHIVE_DIRS, iter_report_trees |
| `wb_analysis/_probe_brief_facts.py` | 把证据包里「写简报所需的全部事实」压成一份短摘要（避免整包 60KB 进上下文）。 | ./.venv/Scripts/python.exe wb_analysis/_probe_brief_facts.py <TICKER> <DATE> [小节...] |
| `wb_analysis/_probe_option_dual_quote.py` | 判定期权链「有双边报价」与「新鲜成交」两个集合的交集（决定期权维度能否使用）。 | ./.venv/Scripts/python.exe wb_analysis/_probe_option_dual_quote.py |
| `wb_analysis/_probe_option_freshness.py` | 独立复核 GOOG 期权链的「快照新鲜度」。 | ./.venv/Scripts/python.exe wb_analysis/_probe_option_freshness.py |
| `wb_analysis/_report_html.py` | 单页自包含 HTML 报告渲染器（吸收上游 v0.6.0 设计） | — |
| `wb_analysis/_role_prompt.py` | 生成单个角色的**完整提示词** —— 用于跨平台、跨会话的子智能体拆分。 | ./.venv/Scripts/python.exe wb_analysis/_role_prompt.py 0700.HK 2026-10-16 bull [--out prompt.md] |
| `wb_analysis/_rv_and_adjust_probe.py` | GOOG 已实现波动率（RV）与「复权价 vs 未调整价」诊断。 | ./.venv/Scripts/python.exe wb_analysis/_rv_and_adjust_probe.py |
| `wb_analysis/_screen_pool.py` | 任意股票池的四维量化筛选 + 「高成长 x 低估值」交叉筛选。 | ./.venv/Scripts/python.exe wb_analysis/_screen_pool.py |
| `wb_analysis/_screen_sp500_full.py` | SP500 全量（503）四维量化筛选 + 「高成长 x 低估值」交叉筛选。 | ./.venv/Scripts/python.exe wb_analysis/_screen_sp500_full.py |
| `wb_analysis/_selfcalc_valuation.py` | 自算 point-in-time 估值 —— 独立于 vendor 实时快照的第二条估值通道。 | from wb_analysis import _selfcalc_valuation as sv; sv.selfcalc("AVGO", "2026-09-25") |
| `wb_analysis/_strip_stray_ratings.py` | 渲染前的契约清扫：把 manager.md 正文里的裸五档英文词改成中文表述。 | ./.venv/Scripts/python.exe wb_analysis/_strip_stray_ratings.py |
| `wb_analysis/_thresholds.py` | 跨工具共用的**判据常量**（数值阈值、市场时钟）—— 定义一次，多处引用。 | from wb_analysis._thresholds import MAX_QUOTE_AGE_DAYS   （库；被采集器/审计器/探针 import，不单独运行） |
| `wb_analysis/_verify_earnings_quality.py` | 收益质量验证器 —— 挡掉「报表净利被一次性项目抬高」这一类失真。 | ./.venv/Scripts/python.exe wb_analysis/_verify_earnings_quality.py |
| `wb_analysis/_verify_edgar_raw.py` | 直接从 SEC data.sec.gov 拉**完整** companyfacts（不走项目内的 slim 缓存），复核 FY2025  | ./.venv/Scripts/python.exe wb_analysis/_verify_edgar_raw.py |
| `wb_analysis/_verify_growth_edgar.py` | 用 SEC EDGAR 的**多年营收 CAGR** 复核量化榜单的「成长」维度。 | ./.venv/Scripts/python.exe wb_analysis/_verify_growth_edgar.py |
| `wb_analysis/_verify_snapshot_consistency.py` | 快照**内部自洽性**检测 —— 专门抓「通道报 ok，但数值与同一份快照的基点矛盾」。 | ./.venv/Scripts/python.exe wb_analysis/_verify_snapshot_consistency.py NVDA 2026-10-09 |
| `wb_analysis/_westock.py` | `westock` CLI 的统一接入层 —— 可执行文件定位 + 调用 + 表格解析。 | from wb_analysis._westock import WESTOCK, run_westock, parse_md_table   （库；不单独运行） |
| `wb_analysis/_wrap_derived.py` | （无文档字符串） | ./.venv/Scripts/python.exe wb_analysis/_wrap_derived.py |
| `wb_analysis/_writeback_analysis.py` | 把草稿目录的 12 个角色文件回写 `wb_analysis/analysis/<T>_<date>.json`。 | ./.venv/Scripts/python.exe wb_analysis/_writeback_analysis.py |
| `wb_analysis/assemble.py` | 报告树组装器 —— 把分析层产出的 JSON 渲染成与上游同构的报告树。 | ./.venv/Scripts/python.exe wb_analysis/assemble.py |
| `wb_analysis/collect.py` | 免费证据采集器 —— 全程不调用任何 LLM。 | ./.venv/Scripts/python.exe wb_analysis/collect.py |
| `wb_analysis/collect_a_etf.py` | A股 ETF 证据采集器（westock CLI） | #   行业 ETF： ./.venv/Scripts/python.exe wb_analysis/collect_a_etf.py --ticker 512400.SS --date 2026-09-30 |
| `wb_analysis/collect_a_stock.py` | A股个股证据采集器 —— 整合 westock CLI (腾讯官方接口) 与 TradingAgents 内置层。 | ./.venv/Scripts/python.exe wb_analysis/collect_a_stock.py --ticker 601899.SS --date 2026-10-16 |
| `wb_analysis/collect_hk_index.py` | 采集**港股指数**证据（westock CLI）—— 项目首个港股链路。 | ./.venv/Scripts/python.exe wb_analysis/collect_hk_index.py --index hkHSTECH |
| `wb_analysis/collect_hk_stock.py` | 港股个股**补充**采集器（westock CLI）—— 补主包的三类结构性缺口。 | ./.venv/Scripts/python.exe wb_analysis/collect_hk_stock.py 0700.HK 2026-10-16 |
| `wb_analysis/collect_index.py` | 指数证据采集器（多指数，默认 NDX）—— 全程不调用任何 LLM。 | ./.venv/Scripts/python.exe wb_analysis/collect_index.py |
| `wb_analysis/collect_treasury.py` | 采集**美债收益率曲线**（FRED）—— 项目首个宏观专题采集器（非 12 角色标的链路）。 | ./.venv/Scripts/python.exe wb_analysis/collect_treasury.py --date 2026-09-28 |
| `wb_analysis/erp_context.py` | 股权风险溢价（ERP）的历史分位计算器 —— 解决「ERP 是偏低还是极端」缺少基准的问题。 | ./.venv/Scripts/python.exe wb_analysis/erp_context.py |
| `wb_analysis/index_breadth.py` | 指数成分股市场宽度（Market Breadth）计算模块。 | — |
| `wb_analysis/index_math.py` | Black-Scholes-Merton 金融工程纯数学计算模块。 | — |
| `wb_analysis/index_options.py` | 指数与宽基 ETF 期权结构、波动率曲面与代理通道计算模块。 | — |
| `wb_analysis/index_valuation.py` | 指数成分股估值、盈利质量与内部人交易聚合模块。 | — |

## maintenance —— 项目维护（门禁 / 清理 / 索引）

| 文件 | 用途 | 用法 / 服务于 |
|---|---|---|
| `scripts/_apply_governance.py` | 治理落地脚本：补齐 lifecycle 头 + 收敛 pyproject.toml（默认干跑）。 | — |
| `scripts/_codemod_clock.py` | 一次性 codemod：把 wb_analysis 里的裸本地时间改为走 wb_analysis/_clock.py。 | — |
| `scripts/_diff_evidence_pack.py` | 证据包等价性比对——用于 collect_index.py 拆分子模块前后的行为回归。 | — |
| `scripts/_health.py` | 项目健康检查：**一条命令看整个项目状态**（把散落的各处门禁汇总成一个入口）。 | ./.venv/Scripts/python.exe scripts/_health.py [--quiet] |
| `scripts/_memory_index.py` | 为本地运行痕迹目录（`.workbuddy-ai/memory/`）生成**主题索引**（`_INDEX.md`）。 | ./.venv/Scripts/python.exe scripts/_memory_index.py [--check] |
| `scripts/_probe_baseline.py` | （无文档字符串） | — |
| `scripts/_prune_backup.py` | 清理本地回滚包目录（`.workbuddy-ai/backup/`）：**按前缀各留最新 N 个**。 | ./.venv/Scripts/python.exe scripts/_prune_backup.py [--apply] |
| `scripts/_scan_project.py` | 只读扫描整个项目的「产物堆积」情况（不修改任何文件）。 | ./.venv/Scripts/python.exe scripts/_scan_project.py |
| `scripts/_scan_reports.py` | 只读扫描 `reports/` 与 `wb_analysis/` 的产物堆积情况，输出分类清单（不修改任何文件）。 | ./.venv/Scripts/python.exe scripts/_scan_reports.py |
| `scripts/smoke_structured_output.py` | End-to-end smoke for structured-output agents against a real LLM pro | ./.venv/Scripts/python.exe scripts/smoke_structured_output.py |
| `wb_analysis/_audit_gaps.py` | 数据缺口审计：把证据包的每个通道逐条分类为「真实缺失 / 阈值误伤 / 采集器 bug」。 | ./.venv/Scripts/python.exe wb_analysis/_audit_gaps.py |
| `wb_analysis/_audit_values.py` | 简报/草稿「口径一致性」审计器 —— 把已作废的旧值当成黑名单扫全文。 | ./.venv/Scripts/python.exe wb_analysis/_audit_values.py |
| `wb_analysis/_check_freshness.py` | 流水线新鲜度校验 —— 防止「上游重采了、下游没重跑」造成的陈旧扩散。 | ./.venv/Scripts/python.exe wb_analysis/_check_freshness.py |
| `wb_analysis/_gap_ledger.py` | 数据缺口台账：把「缺什么」变成**可检查的结构化记录**，而不是散落在文字里的声明。 | ./.venv/Scripts/python.exe wb_analysis/_gap_ledger.py |
| `wb_analysis/_lint_drafts.py` | 草稿防伪与契约校验器 —— 在渲染前拦住「编造数据」与格式违规。 | ./.venv/Scripts/python.exe wb_analysis/_lint_drafts.py |
| `wb_analysis/_precheck.py` | 交付前统一门禁 —— 一条命令跑完全部校验，输出一张表。 | ./.venv/Scripts/python.exe wb_analysis/_precheck.py |
| `wb_analysis/_reports_index.py` | 生成 `reports/INDEX.md`，并检查产物是否又开始堆积（可作为交付门禁的一项）。 | ./.venv/Scripts/python.exe wb_analysis/_reports_index.py |
| `wb_analysis/_scorecard.py` | 报告质量记分卡：把「这一轮报告比上一轮好还是差」变成**可算的数字**。 | ./.venv/Scripts/python.exe wb_analysis/_scorecard.py [--trend] |
| `wb_analysis/_seal_run.py` | 把「一次运行的中间产物」封存进该次报告树，随后删除散落在项目里的副本。 | ./.venv/Scripts/python.exe wb_analysis/_seal_run.py |
| `wb_analysis/_selftest.py` | 门禁自检 —— 证明「检测器本身」还在正常工作。 | ./.venv/Scripts/python.exe wb_analysis/_selftest.py |
| `wb_analysis/_verify_ratings.py` | 评级词与契约字段的可靠扫描器（不依赖 shell 转义）。 | ./.venv/Scripts/python.exe wb_analysis/_verify_ratings.py |
| `wb_analysis/_verify_report.py` | 渲染后反读校验器 —— 用上游解析器验证报告树，不依赖 assemble 的「契约校验通过」。 | ./.venv/Scripts/python.exe wb_analysis/_verify_report.py |

## oneoff —— 为某次结论临时写的探针

> **`_oneoff/` 是收件箱**：探针服务的那一轮交付并封存后，会**随案卷进 `reports/<标的>/<时间戳>/_source.zip`**，`_oneoff/` 于是回到空 —— **看到它空是正常的**。

| 文件 | 用途 | 用法 / 服务于 |
|---|---|---|
| `scripts/_oneoff/_append_oss_assessment.py` | 把开源准备度评估追加进当日记忆（避免 heredoc 转义问题）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_append_oss_assessment.py |
| `scripts/_oneoff/_audit_evidence_sections.py` | （无文档字符串） | 通用（argv 传入 evidence.md） |
| `scripts/_oneoff/_avgo_edgar_tagprobe.py` | 核查 AVGO FY2025（期末 2025-11-02）的：回购标签、净利标签、权益标签、债务标签。 | — |
| `scripts/_oneoff/_avgo_fy_end.py` | 列出 AVGO 缓存的 companyfacts 里所有 10-K 的期末日，确定真实财年末。 | — |
| `scripts/_oneoff/_backfill_run_json.py` | 为**已存在的旧报告树**补写 `RUN.json`（一次性迁移）。 | 2026-09 迁入新布局之前的旧报告树 |
| `scripts/_oneoff/_check_macro_news_body.py` | （无文档字符串） | — |
| `scripts/_oneoff/_cleanup_deadweight_20261010.py` | 打包 → 逐项校验 → 删除：wb_analysis/scratch/ + wb_analysis/_verify_statements | 一次性清理死重（user 指示「没用的或有副作用的要么优化要么不要了」） |
| `scripts/_oneoff/_cleanup_dup_trees_20261010.py` | 清理 2026-10-10 卫生检查列出的 4 对「同基准日并存」报告树中**应淘汰的那一棵**。 | — |
| `scripts/_oneoff/_cleanup_dup_trees_20261014.py` | 清理 2026-10-14 卫生检查列出的「同基准日并存」报告树中**应淘汰的那一棵**。 | — |
| `scripts/_oneoff/_cleanup_ghost_entries.py` | 让 git 索引与磁盘一致：把 55 个「已跟踪但磁盘不存在」的幽灵条目 stage 删除。 | ./.venv/Scripts/python.exe scripts/_oneoff/_cleanup_ghost_entries.py [--apply] |
| `scripts/_oneoff/_cleanup_goog_orphan_tree.py` | 清理 GOOG 2026-09-23 的两棵并存报告树中的孤儿树 GOOG_20260923_164039。 | — |
| `scripts/_oneoff/_cleanup_ndx_dup.py` | 清理 NDX 2026-09-21 的两棵并存报告树中的旧树 + drafts 散件。 | — |
| `scripts/_oneoff/_cleanup_reports.py` | 报告/证据/草稿的「旧版与孤儿产物」清理器。 | 2026-09-16 ~ 09-19 期间的旧版/孤儿产物 |
| `scripts/_oneoff/_cmp_divlowvol_common.py` | 红利低波 ETF：**统一窗口**年化总收益（后复权）+ 费率 → 综合排名。 | — |
| `scripts/_oneoff/_cmp_divlowvol_etf.py` | A 股红利低波 ETF 综合对比：费率 + 年化总收益（后复权）+ 规模/流动性 + 估值分位。 | — |
| `scripts/_oneoff/_cmp_gold_etf.py` | A 股黄金 ETF 横向对比：费率 / 规模 / 流动性 / 跟踪指数（选标的用）。 | — |
| `scripts/_oneoff/_delete_erroneous_trees.py` | （无文档字符串） | — |
| `scripts/_oneoff/_diag_chk_quant.py` | 查清：`chk_quant` 在 `.env` 被清空后仍 PASS —— 是产品 bug，还是**我的探针有缺陷**？ | ./.venv/Scripts/python.exe scripts/_oneoff/_diag_chk_quant.py |
| `scripts/_oneoff/_diag_chk_quant2.py` | 精确定位：`.env` 清空后 `chk_quant` 为何仍 PASS。 | ./.venv/Scripts/python.exe scripts/_oneoff/_diag_chk_quant2.py |
| `scripts/_oneoff/_diag_chk_quant_in_pytest.py` | 诊断：为何 `chk_quant` 的修复在**直接跑时生效**、在 **pytest 里失效**？ | ./.venv/Scripts/python.exe scripts/_oneoff/_diag_chk_quant_in_pytest.py |
| `scripts/_oneoff/_diag_global_news_summary.py` | （无文档字符串） | — |
| `scripts/_oneoff/_diag_nflx_news.py` | （无文档字符串） | — |
| `scripts/_oneoff/_diag_nflx_search_quality.py` | （无文档字符串） | — |
| `scripts/_oneoff/_diag_nflx_search_variants.py` | （无文档字符串） | — |
| `scripts/_oneoff/_diag_nflx_specificity.py` | （无文档字符串） | — |
| `scripts/_oneoff/_diag_role_files_empty.py` | 甄别：`_check_role_files.py` 在「目录存在但无角色文件」时 rc=0 是否**真 bug**。 | ./.venv/Scripts/python.exe scripts/_oneoff/_diag_role_files_empty.py |
| `scripts/_oneoff/_diag_search_news.py` | （无文档字符串） | — |
| `scripts/_oneoff/_drop_superseded_avgo_tree.py` | 打包并移除被取代的 AVGO 报告树（183033）：先打包、逐项校验，通过再逐文件删除。 | — |
| `scripts/_oneoff/_extract_parse_sums.py` | 把算式解析逻辑抽成**纯函数** `parse_sums()`，消除「实现与测试各写一份」。 | ./.venv/Scripts/python.exe scripts/_oneoff/_extract_parse_sums.py |
| `scripts/_oneoff/_fix_checker_blindspots.py` | 修 `scripts/_health.py` 中两处**同族**判据缺陷（本日第 5、6 例）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_checker_blindspots.py |
| `scripts/_oneoff/_fix_chk_quant_token.py` | 修 `chk_quant` 的**假绿**（本日第 8 例，已精确复现）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_chk_quant_token.py |
| `scripts/_oneoff/_fix_chk_reports_crash.py` | 修 `chk_reports` 的**崩溃假绿**（本日第 7 例同族缺陷，已实测复现）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_chk_reports_crash.py |
| `scripts/_oneoff/_fix_doc_paths.py` | 把文档里的旧路径改成迁移后的真实路径，每处替换都断言命中数。 | 修复 docs/WORKFLOW.md 与 docs/SCREENER.md 的过时命令路径（quant/ 迁移后遗留） |
| `scripts/_oneoff/_fix_expr_re_rhs_sign.py` | 修 `EXPR_RE`（原 SUM_RE）未覆盖的形态：**右侧带显式正负号的算式**。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_expr_re_rhs_sign.py |
| `scripts/_oneoff/_fix_memory_index_check.py` | 修 `scripts/_memory_index.py` 的两处缺陷（本脚本用「读取替换块 → 精确替换」方式）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_memory_index_check.py |
| `scripts/_oneoff/_fix_nflx_lint.py` | 修正 NFLX 草稿中被 lint 判为契约违规的「裸五档英文词」（共 3 个文件 9 处）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_nflx_lint.py |
| `scripts/_oneoff/_fix_rating_words.py` | （无文档字符串） | 2026-09 期若干轮草稿 |
| `scripts/_oneoff/_fix_reports_layout.py` | 核对并按需修正 `reports/` 的目标布局（幂等；可反复运行）。 | 2026-09-23 一次性布局迁移（8 个标的） |
| `scripts/_oneoff/_fix_role_files_empty_pass.py` | 修 `_check_role_files.py`：**空草稿目录被判「通过」**（本日第 9 例，已实测复现）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_role_files_empty_pass.py |
| `scripts/_oneoff/_fix_trader_ratings.py` | （无文档字符串） | 把 GOOG / NFLX 交易员稿正文里的五档英文词改为中文，使 trader.md 全文恰含 1 个五档词 |
| `scripts/_oneoff/_fix_two_sided_fixture.py` | 修正双向验证夹具：原先我拿「算对的数」当错值（差 0.0005，在容差内）⇒ 误判为「未通过」。 | ./.venv/Scripts/python.exe scripts/_oneoff/_fix_two_sided_fixture.py |
| `scripts/_oneoff/_mk_divlowvol_report.py` | 生成《A 股红利低波 ETF 综合对比报告》桌面 HTML（与有色金属 ETF 报告同版式）。 | — |
| `scripts/_oneoff/_mk_nonferrous_report.py` | 生成《有色金属板块ETF综合对比报告.html》到桌面（v3：含分红修正年化 + 数据核验专节 + 12 只全量）。 | — |
| `scripts/_oneoff/_move_to_quant.py` | 把根目录 9 个自建 .py 收进 `quant/` 包，并同步修正所有导入点。 | 项目结构重构 2026-09-23 |
| `scripts/_oneoff/_nflx_key_numbers.py` | （无文档字符串） | — |
| `scripts/_oneoff/_oss_readiness_scan.py` | 开源准备度扫描：在**已跟踪文件**里找不该公开的内容。 | ./.venv/Scripts/python.exe scripts/_oneoff/_oss_readiness_scan.py |
| `scripts/_oneoff/_patch_output_dirs.py` | 把「散落产物」的输出目录统一到 `reports/_datasets/`（数据产品）与 `reports/_other/`（专题报告）。 | 2026-09-23 一次性写入点迁移 |
| `scripts/_oneoff/_probe_avgo_forward_pe.py` | 探查 AVGO 的 forwardPE/forwardEps 是否可信（铁律 26：字段间关系校验）。 | — |
| `scripts/_oneoff/_probe_avgo_latest.py` | 探测 AVGO 最新可用日线 bar 与期权链新鲜度，用于确定本轮基准日。 | — |
| `scripts/_oneoff/_probe_cache_health.py` | （无文档字符串） | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_cache_health.py |
| `scripts/_oneoff/_probe_checker_blindspots.py` | 对抗性实测：`scripts/_health.py` 各检查器**能否被绕过**（找出剩余「判据写窄」bug）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_checker_blindspots.py |
| `scripts/_oneoff/_probe_checker_blindspots2.py` | 对抗性实测（第二轮）：覆盖第一轮没打的检查器。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_checker_blindspots2.py |
| `scripts/_oneoff/_probe_chk_reports_crash.py` | 关键一测：`chk_reports` 在被调工具**完全崩溃**时，会不会假绿？ | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_chk_reports_crash.py |
| `scripts/_oneoff/_probe_date_nflx.py` | 探针：确定本轮基准日，并核对 NFLX 末根 bar / 期权链新鲜度。只读。 | — |
| `scripts/_oneoff/_probe_gate_scripts.py` | 对抗性实测：`wb_analysis/` 下**无测试覆盖**的门禁脚本能否被绕过。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_gate_scripts.py |
| `scripts/_oneoff/_probe_global_news_alt.py` | （无文档字符串） | — |
| `scripts/_oneoff/_probe_goog_shares.py` | Alphabet 的 GOOG(Class C) / GOOGL(Class A) 在 yfinance 上会给出不同口径的股数。 | GOOG 2026-09-29 —— Alphabet 三类股（A/B/C）股数双口径探针（铁律 23） |
| `scripts/_oneoff/_probe_goog_ttm.py` | 为什么需要这个探针：证据包 §3 基本面快照被时点闸门扣留，且只给了年度报表。 | GOOG 2026-09-29 —— TTM 拆解探针 |
| `scripts/_oneoff/_probe_goog_untraced.py` | 为什么需要这个探针：`_lint_drafts.py` 的「未溯源数字」清单**只打印前 25 个**， | GOOG 2026-09-29 —— 未溯源数字全量导出探针（数字溯源审计） |
| `scripts/_oneoff/_probe_health_all.py` | 对抗性实测：`_health.py` **全部 13 个检查器**逐个注入坏条件，看谁能被绕过。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_health_all.py |
| `scripts/_oneoff/_probe_ndx_formulas.py` | 逐条复算 6 份 NDX 草稿里显式写出的算式（a − b = c / a ÷ b = c / a × b = c），找出算错的数。 | — |
| `scripts/_oneoff/_probe_ndx_untraced.py` | 一次性探针：导出 NDX_2026-09-29 草稿的全部「未溯源数字」（带行号与原文）， | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_ndx_untraced.py |
| `scripts/_oneoff/_probe_nflx_baseline.py` | （无文档字符串） | NFLX 基线探针 |
| `scripts/_oneoff/_probe_nflx_oneoff_gain.py` | 探针：定位 NFLX 非经营项目与一次性收益（$2.8B 华纳分手费）。 | — |
| `scripts/_oneoff/_probe_nflx_q1_items.py` | 探针：扫描 NFLX 2026Q1 的全部 us-gaap 标签，定位那笔 2.852B 非经营收益的性质。 | — |
| `scripts/_oneoff/_probe_nflx_sec_ttm.py` | 探针：从 SEC companyfacts 直取 NFLX 分季营收/营业利润/净利，独立复算 TTM。 | — |
| `scripts/_oneoff/_probe_nflx_snapshot_caliber.py` | 探针：核对 NFLX 估值快照字段口径 —— 季度利润表 / 现金流，定位 FCF 25.388B 与 Op Margin 33.381 | — |
| `scripts/_oneoff/_probe_nflx_ttm_decomp.py` | 探针：分解 NFLX TTM 净利，查是否含一次性/非经营项目（铁律 40/43 复核）。 | — |
| `scripts/_oneoff/_probe_nul_file.py` | 核实根目录 `nul` 残留是否真实存在（评估报告说"已删"、正文说"未处置"，需实测裁定）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_nul_file.py |
| `scripts/_oneoff/_probe_quote_refresh.py` | GOOG / ^NDX 报价刷新探测（只读，不写证据包）。 | — |
| `scripts/_oneoff/_probe_risk_rating_scope.py` | （无文档字符串） | 评估「风险席位（aggressive/conservative/neutral）结论块之外出现五档英文词」 |
| `scripts/_oneoff/_probe_skhy_identity.py` | Probe yfinance identity for SK Hynix related tickers (SKHY / HXSCF / | — |
| `scripts/_oneoff/_probe_skhy_iv_incremental.py` | （无文档字符串） | — |
| `scripts/_oneoff/_probe_skhy_unusual.py` | 探针：查 SKHY 季度利润表的 Total Unusual Items / Net Income，判断收益质量闸门报的 | — |
| `scripts/_oneoff/_probe_sum_re_coverage.py` | 刻画 `EXPR_RE`（原 SUM_RE）的**命中边界**：找出「本项目真实写法」中命不中的形态。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_sum_re_coverage.py |
| `scripts/_oneoff/_quantify_sum_re_gap.py` | 量化「右侧带正负号算式」抓不到的影响面（先测规模再决定是否改正则）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_quantify_sum_re_gap.py |
| `scripts/_oneoff/_remove_empty_shell_dirs.py` | （无文档字符串） | — |
| `scripts/_oneoff/_reorg_reports.py` | 把 `reports/` 重排成「按标的分子目录」结构，并把非报告类产物分流到专门子目录。 | 2026-09-23 一次性 reports/ 布局重排 |
| `scripts/_oneoff/_scan_untracked_risk.py` | 扫描**未跟踪文件**的安全风险 —— 它们从未被检查过，一旦 `git add` 就会入库。 | ./.venv/Scripts/python.exe scripts/_oneoff/_scan_untracked_risk.py |
| `scripts/_oneoff/_selftest_dup_content_identity.py` | O2 双侧验证：内容身份重复检测。 | （门禁双侧自检，无标的） |
| `scripts/_oneoff/_selftest_edgar_gap.py` | O4 + O5 双侧验证。 | （门禁双侧自检，无标的） |
| `scripts/_oneoff/_selftest_ironlaw24_guard.py` | O1 双侧验证：铁律 24 守卫必须在「短历史」命中、在「长历史」静默。 | （门禁双侧自检，无标的） |
| `scripts/_oneoff/_selftest_report_contract.py` | O8 双侧验证：合成报告的契约门禁。 | （门禁双侧自检，无标的） |
| `scripts/_oneoff/_selftest_seal_stale_pack.py` | 回归夹具：`_seal_run.py` 的「审计包过期」检测（2026-10-12 修的那个数据销毁 bug）。 | （门禁双侧自检，无标的） |
| `scripts/_oneoff/_te_nonferrous.py` | 跟踪误差代理计算：同指数 ETF 日收益互偏法。 | — |
| `scripts/_oneoff/_verify_checker_fixes.py` | 双向验证 `chk_gitignore` / `chk_seal` 两处修复（坏输入必检出 / 好输入不误报）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_verify_checker_fixes.py |
| `scripts/_oneoff/_verify_currency_gate.py` | 双向夹具：验证 _fundamentals_sanity 的币种不一致检测（铁律 20：改检测器必须双边自测）。 | — |
| `scripts/_oneoff/_verify_expr_fix_inprod.py` | 验证 `EXPR_RE` 修复在**生产环境**真生效（用独立算法交叉核对，不复用被修的正则）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_verify_expr_fix_inprod.py |
| `scripts/_oneoff/_verify_expr_re_two_sided.py` | `EXPR_RE` 修复的**双向验证**（走完整 `check_sums` 路径，而非只看正则）。 | ./.venv/Scripts/python.exe scripts/_oneoff/_verify_expr_re_two_sided.py |
| `scripts/_oneoff/_verify_ghost_entries.py` | 逐项核实 55 个「已跟踪但磁盘不存在」的条目 —— 内容是否都能找回？ | ./.venv/Scripts/python.exe scripts/_oneoff/_verify_ghost_entries.py |
| `scripts/_oneoff/_verify_new_tests_have_teeth.py` | 验证新增测试**有判别力**：把修复回退成坏实现，测试必须 FAIL。 | ./.venv/Scripts/python.exe scripts/_oneoff/_verify_new_tests_have_teeth.py |
| `scripts/_oneoff/_verify_nflx_news_fix.py` | （无文档字符串） | — |
| `scripts/_oneoff/_verify_nvda_ttm.py` | NVDA 基准日 2026-10-09 —— 从 SEC 原始季报事实**自算 TTM**，交叉校验 yfinance 快照。 | ./.venv/Scripts/python.exe scripts/_oneoff/_verify_nvda_ttm.py |
| `scripts/_oneoff/_verify_tree_vs_draft_nflx.py` | 校验交付树 vs 草稿目录是否逐字一致（assemble 会剥掉文件末尾换行，故 norm 需 rstrip 一个换行）。 | — |
| `scripts/_oneoff/_verify_uber_brief_math.py` | 独立验算 0_brief.md 里 UBER 的每一个派生数字（铁律 25：能不能写出算式）。 | — |
| `scripts/_oneoff/_watch_nflx_analysts.py` | 守望：等待 4 个分析师产物落盘（最多 9 分钟），每 15s 打印一次大小。 | — |
| `scripts/_oneoff/build_full_wdc_report.py` | 全面重构并升级 WDC 2026-10-08 完整 12 角色深度推演研报： | ./.venv/Scripts/python.exe scripts/_oneoff/build_full_wdc_report.py |
| `scripts/_oneoff/build_wdc_full_12_roles_report.py` | 全面重构生成 WDC 2026-10-08 完整十二角色深度推演研报： | ./.venv/Scripts/python.exe scripts/_oneoff/build_wdc_full_12_roles_report.py |
| `scripts/_oneoff/fix_wdc_drafts_comprehensive.py` | 全面重构并修正 WDC 2026-10-08 草稿文件： | ./.venv/Scripts/python.exe scripts/_oneoff/fix_wdc_drafts_comprehensive.py |
| `wb_analysis/_oneoff/_audit_563020_consistency.py` | 563020 草稿一致性核对：把「同一事实在多处出现却数值不同」自动抓出来。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_audit_563020_consistency.py |
| `wb_analysis/_oneoff/_chk_563020_roles.py` | 一次性自检：列出 563020 草稿目录每个角色文件的字符数与「首个五档英文词」位置。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_chk_563020_roles.py |
| `wb_analysis/_oneoff/_cleanup_563020_failed_tree.py` | 清理 563020 首轮「反读 FAIL」的渲染树（133236）。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_cleanup_563020_failed_tree.py |
| `wb_analysis/_oneoff/_crosscheck_563020_delivered_values.py` | 交叉验证：**用独立算法**从交付树的 complete_report.md 里抽数字重算，验证内部自洽。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_crosscheck_563020_delivered_values.py |
| `wb_analysis/_oneoff/_derive_ndx_orig.py` | 派生指标计算器：从 NDX 证据包导出所有「需要算术推导」的二级指标。 | NDX 派生指标（已被 _derive_ndx.py 取代） |
| `wb_analysis/_oneoff/_derive_stock_gold.py` | 黄金专属二级派生指标 —— 品种驱动因素通道。 | GLD 2026-09-18 |
| `wb_analysis/_oneoff/_erp_offline.py` | ERP 分位的离线重算（FRED 不可达时的降级路径）—— 2026-09-17 事件的一次性记录。 | ERP 离线降级（FRED 不可达时）—— ★ **2026-09-17 那次事件的冻结记录，不是可复用工具** |
| `wb_analysis/_oneoff/_exhaustive_pct_563020.py` | 穷举式兜底：把交付报告里**每一个百分比**与底稿复算值比对，找出所有无法归因的。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_exhaustive_pct_563020.py |
| `wb_analysis/_oneoff/_fix_563020_denominator.py` | 彻底统一「距现价 x%」的分母口径 —— 修复上一轮只改一半造成的**新不一致**。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_fix_563020_denominator.py |
| `wb_analysis/_oneoff/_fix_563020_entry_denominator.py` | 统一「距入场 1.202」的止损距离口径（与「距现价」区分开）。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_fix_563020_entry_denominator.py |
| `wb_analysis/_oneoff/_fix_seal_bugs.py` | 修复 `_seal_run.py` 的两个实测 bug（本脚本用精确替换 + ast 校验 + 幂等）。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_fix_seal_bugs.py |
| `wb_analysis/_oneoff/_mk_derived_nflx.py` | （无文档字符串） | — |
| `wb_analysis/_oneoff/_mk_sector_report.py` | 有色金属板块全览：主流 ETF / 联接基金 费率与性价比对比报告（桌面交付）。 | — |
| `wb_analysis/_oneoff/_oneoff_append_premarket.py` | （无文档字符串） | — |
| `wb_analysis/_oneoff/_oneoff_append_skhy_premarket.py` | （无文档字符串） | — |
| `wb_analysis/_oneoff/_patch_563020_add_ladder.py` | 把「加仓阶梯」同步到 PM 终审与三个风险席位（保持辩论完整与口径一致）。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_patch_563020_add_ladder.py |
| `wb_analysis/_oneoff/_probe_avgo_valuation_selfcalc.py` | 探针：用「价格序列 + EDGAR 股数 + 报表」自算 AVGO 的 point-in-time 估值指标， | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_avgo_valuation_selfcalc.py |
| `wb_analysis/_oneoff/_probe_macro_news_sources.py` | 探针：§6 宏观新闻正文全缺 —— 测试能不能换通道抓到正文。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_macro_news_sources.py |
| `wb_analysis/_oneoff/_probe_manager_terms.py` | （无文档字符串） | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_probe_manager_terms.py |
| `wb_analysis/_oneoff/_probe_news_channel_fields.py` | 探针：精确对比 yf.Search() 与 yf.Ticker().news 两个通道的字段，锁定 §6 无正文的根因。 | ./.venv/Scripts/python.exe scripts/_oneoff/_probe_news_channel_fields.py |
| `wb_analysis/_oneoff/_probe_risk_terms.py` | （无文档字符串） | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_probe_risk_terms.py |
| `wb_analysis/_oneoff/_recheck_563020_delivered.py` | 独立复核：直接扫**交付树**（reports/563020/563020_20261016_133333/）里的最终产物， | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_recheck_563020_delivered.py |
| `wb_analysis/_oneoff/_repair_563020_seal.py` | 修复 `_seal_run.py --rebuild` 的**审计包不完整**问题。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_repair_563020_seal.py |
| `wb_analysis/_oneoff/_resync_563020_seal_meta.py` | 把封存元数据与审计包实际内容**重新对齐**（本轮发现三处过期）。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_resync_563020_seal_meta.py |
| `wb_analysis/_oneoff/_sweep_563020_old_values.py` | 全量扫描并（可选）**全局**替换本轮修复涉及的全部旧值。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_sweep_563020_old_values.py [--apply] |
| `wb_analysis/_oneoff/_test_seal_rebuild_nodrop.py` | 回归测试：验证 `_seal_run.py` 的「部分相同 + 部分不同」场景不再丢件。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_test_seal_rebuild_nodrop.py |
| `wb_analysis/_oneoff/_tmp_ndx_trader_calc.py` | （无文档字符串） | NDX 2026-09-29 第 6 环交易员稿的全部算式复算（跳空样本扫描、EMA 精确递推、 |
| `wb_analysis/_oneoff/_verify_563020_stale_by_content.py` | 按项目铁律 7：用**内容比对**判定 3 个「mtime 早于 0_brief」的角色文件是否需要重跑。 | ./.venv/Scripts/python.exe wb_analysis/_oneoff/_verify_563020_stale_by_content.py |
| `wb_analysis/_oneoff/_verify_cboe_e2e.py` | 端到端验证：非盘中时段能否用 CBOE 源重建完整期权结构。 | — |
| `wb_analysis/_oneoff/_verify_cboe_non_us.py` | 边界核实：非美股标的（指数 / A 股 ETF）在**盘前**走期权分支时，行为是否安全。 | — |
| `wb_analysis/_oneoff/_verify_cboe_pipeline.py` | 端到端验证（完整链）：注入盘前时钟 → `fetch_option_structure` 走 CBOE → 产出 IV/偏斜。 | — |
| `wb_analysis/_oneoff/_volstats_a_etf.py` | （无文档字符串） | — |
| `wb_analysis/_oneoff/gen_07552_evidence.py` | 生成 07552（南方两倍做空恒科）2026-10-08 完整证据包。 | — |

## 豁免（不是脚本，无需声明）

| 文件 | 原因 |
|---|---|
| `quant/__init__.py` | 包标记 / pytest 配置 |
| `wb_analysis/__init__.py` | 包标记 / pytest 配置 |

> 规则：探针若**第二次被复用**，就补文档 + `# usage:` 提升为 `reusable` —— **复用即升级**。

