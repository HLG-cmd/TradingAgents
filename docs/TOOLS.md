# 工具索引（自动生成，勿手改）

- 生成时间：2026-09-23 01:46
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
| `quant/wb_deep_dive.py` | WorkBuddy 深度投研流水线 —— 零 LLM 成本的一站式入口。 | ./.venv/Scripts/python.exe quant/wb_deep_dive.py |
| `wb_analysis/_check_role_files.py` | 角色文件体检：篇幅 / 裸五档英文词 / 越界 PROPOSAL / 合规声明 / 必需小节。 | ./.venv/Scripts/python.exe wb_analysis/_check_role_files.py |
| `wb_analysis/_crosscheck_nasdaq.py` | 用 Nasdaq 官方公开 API 独立复核证据包 §1 的日线 OHLC（数据来源真实性核验）。 | ./.venv/Scripts/python.exe wb_analysis/_crosscheck_nasdaq.py |
| `wb_analysis/_derive_ndx.py` | 派生指标计算器：从指数证据包导出所有「需要算术推导」的二级指标（支持 NDX / SPX）。 | ./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py |
| `wb_analysis/_derive_stock.py` | 个股派生指标计算器：从个股证据包导出所有「需要算术推导」的二级指标。 | ./.venv/Scripts/python.exe wb_analysis/_derive_stock.py |
| `wb_analysis/_erp_retry.py` | ERP 计算的重试包装器。 | ./.venv/Scripts/python.exe wb_analysis/_erp_retry.py |
| `wb_analysis/_gen_derived_ndx.py` | 把 _derive_ndx.py 的 stdout 落盘（避免 shell 重定向写中文 + /tmp 路径问题）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_derived_ndx.py |
| `wb_analysis/_gen_derived_stock.py` | 把 _derive_stock.py 的 stdout 落成证据包同级文件（避免 shell 重定向写中文）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py |
| `wb_analysis/_gen_supplement.py` | 生成 `<TICKER>_<date>.supplement.md`：证据包 §3 被上游扣留时的**一等替代证据源**。 | ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py |
| `wb_analysis/_insider_agg.py` | 从证据包 §8 内部人交易 CSV 段落聚合买卖统计（回原始样本重数，不依赖任何摘要）。 | ./.venv/Scripts/python.exe wb_analysis/_insider_agg.py |
| `wb_analysis/_nasdaq_official.py` | 拉 Nasdaq 官方 API 的日线并打印，用于人工对照 NDX 证据包 §1。 | ./.venv/Scripts/python.exe wb_analysis/_nasdaq_official.py |
| `wb_analysis/_probe_option_dual_quote.py` | 判定期权链「有双边报价」与「新鲜成交」两个集合的交集（决定期权维度能否使用）。 | ./.venv/Scripts/python.exe wb_analysis/_probe_option_dual_quote.py |
| `wb_analysis/_probe_option_freshness.py` | 独立复核 GOOG 期权链的「快照新鲜度」。 | ./.venv/Scripts/python.exe wb_analysis/_probe_option_freshness.py |
| `wb_analysis/_rv_and_adjust_probe.py` | GOOG 已实现波动率（RV）与「复权价 vs 未调整价」诊断。 | ./.venv/Scripts/python.exe wb_analysis/_rv_and_adjust_probe.py |
| `wb_analysis/_screen_pool.py` | 任意股票池的四维量化筛选 + 「高成长 x 低估值」交叉筛选。 | ./.venv/Scripts/python.exe wb_analysis/_screen_pool.py |
| `wb_analysis/_screen_sp500_full.py` | SP500 全量（503）四维量化筛选 + 「高成长 x 低估值」交叉筛选。 | ./.venv/Scripts/python.exe wb_analysis/_screen_sp500_full.py |
| `wb_analysis/_strip_stray_ratings.py` | 渲染前的契约清扫：把 manager.md 正文里的裸五档英文词改成中文表述。 | ./.venv/Scripts/python.exe wb_analysis/_strip_stray_ratings.py |
| `wb_analysis/_verify_earnings_quality.py` | 收益质量验证器 —— 挡掉「报表净利被一次性项目抬高」这一类失真。 | ./.venv/Scripts/python.exe wb_analysis/_verify_earnings_quality.py |
| `wb_analysis/_verify_edgar_raw.py` | 直接从 SEC data.sec.gov 拉**完整** companyfacts（不走项目内的 slim 缓存），复核 FY2025  | ./.venv/Scripts/python.exe wb_analysis/_verify_edgar_raw.py |
| `wb_analysis/_verify_growth_edgar.py` | 用 SEC EDGAR 的**多年营收 CAGR** 复核量化榜单的「成长」维度。 | ./.venv/Scripts/python.exe wb_analysis/_verify_growth_edgar.py |
| `wb_analysis/_verify_statements_edgar.py` | 用 SEC EDGAR（XBRL，独立第三方）复核证据包 §4 三大报表的**年度（FY2025）**科目。 | ./.venv/Scripts/python.exe wb_analysis/_verify_statements_edgar.py |
| `wb_analysis/_wrap_derived.py` | （无文档字符串） | ./.venv/Scripts/python.exe wb_analysis/_wrap_derived.py |
| `wb_analysis/_writeback_analysis.py` | 把草稿目录的 12 个角色文件回写 `wb_analysis/analysis/<T>_<date>.json`。 | ./.venv/Scripts/python.exe wb_analysis/_writeback_analysis.py |
| `wb_analysis/assemble.py` | 报告树组装器 —— 把分析层产出的 JSON 渲染成与上游同构的报告树。 | ./.venv/Scripts/python.exe wb_analysis/assemble.py |
| `wb_analysis/collect.py` | 免费证据采集器 —— 全程不调用任何 LLM。 | ./.venv/Scripts/python.exe wb_analysis/collect.py |
| `wb_analysis/collect_index.py` | 指数证据采集器（多指数，默认 NDX）—— 全程不调用任何 LLM。 | ./.venv/Scripts/python.exe wb_analysis/collect_index.py |
| `wb_analysis/erp_context.py` | 股权风险溢价（ERP）的历史分位计算器 —— 解决「ERP 是偏低还是极端」缺少基准的问题。 | ./.venv/Scripts/python.exe wb_analysis/erp_context.py |

## maintenance —— 项目维护（门禁 / 清理 / 索引）

| 文件 | 用途 | 用法 / 服务于 |
|---|---|---|
| `scripts/_backfill_run_json.py` | 为**已存在的旧报告树**补写 `RUN.json`（一次性迁移）。 | ./.venv/Scripts/python.exe scripts/_backfill_run_json.py |
| `scripts/_cleanup_reports.py` | 报告/证据/草稿的「旧版与孤儿产物」清理器。 | ./.venv/Scripts/python.exe scripts/_cleanup_reports.py |
| `scripts/_fix_reports_layout.py` | 核对并按需修正 `reports/` 的目标布局（幂等；可反复运行）。 | ./.venv/Scripts/python.exe scripts/_fix_reports_layout.py |
| `scripts/_health.py` | 项目健康检查：**一条命令看整个项目状态**（把散落的各处门禁汇总成一个入口）。 | ./.venv/Scripts/python.exe scripts/_health.py [--quiet] |
| `scripts/_patch_output_dirs.py` | 把「散落产物」的输出目录统一到 `reports/_datasets/`（数据产品）与 `reports/_other/`（专题报告）。 | ./.venv/Scripts/python.exe scripts/_patch_output_dirs.py |
| `scripts/_prune_backup.py` | 清理 `.workbuddy/backup/` 里的回滚包：**按前缀各留最新 N 个**。 | ./.venv/Scripts/python.exe scripts/_prune_backup.py [--apply] |
| `scripts/_reorg_reports.py` | 把 `reports/` 重排成「按标的分子目录」结构，并把非报告类产物分流到专门子目录。 | ./.venv/Scripts/python.exe scripts/_reorg_reports.py |
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
| `wb_analysis/_seal_run.py` | 把「一次运行的中间产物」封存进该次报告树，随后删除散落在项目里的副本。 | ./.venv/Scripts/python.exe wb_analysis/_seal_run.py |
| `wb_analysis/_selftest.py` | 门禁自检 —— 证明「检测器本身」还在正常工作。 | ./.venv/Scripts/python.exe wb_analysis/_selftest.py |
| `wb_analysis/_verify_ratings.py` | 评级词与契约字段的可靠扫描器（不依赖 shell 转义）。 | ./.venv/Scripts/python.exe wb_analysis/_verify_ratings.py |
| `wb_analysis/_verify_report.py` | 渲染后反读校验器 —— 用上游解析器验证报告树，不依赖 assemble 的「契约校验通过」。 | ./.venv/Scripts/python.exe wb_analysis/_verify_report.py |

## oneoff —— 为某次结论临时写的探针

> **`_oneoff/` 是收件箱**：探针服务的那一轮交付并封存后，会**随案卷进 `reports/<标的>/<时间戳>/_source.zip`**，`_oneoff/` 于是回到空 —— **看到它空是正常的**。

| 文件 | 用途 | 用法 / 服务于 |
|---|---|---|
| `scripts/_oneoff/_move_to_quant.py` | 把根目录 9 个自建 .py 收进 `quant/` 包，并同步修正所有导入点。 | 项目结构重构 2026-09-23 |
| `wb_analysis/_oneoff/_derive_ndx_orig.py` | 派生指标计算器：从 NDX 证据包导出所有「需要算术推导」的二级指标。 | NDX 派生指标（已被 _derive_ndx.py 取代） |
| `wb_analysis/_oneoff/_derive_stock_gold.py` | 黄金专属二级派生指标 —— 品种驱动因素通道。 | GLD 2026-09-18 |
| `wb_analysis/_oneoff/_erp_offline.py` | ERP 分位的离线重算（FRED 不可达时的降级路径）。 | ERP 离线降级（FRED 不可达时） |

## 豁免（不是脚本，无需声明）

| 文件 | 原因 |
|---|---|
| `quant/__init__.py` | 包标记 / pytest 配置 |
| `wb_analysis/__init__.py` | 包标记 / pytest 配置 |

> 规则：探针若**第二次被复用**，就补文档 + `# usage:` 提升为 `reusable` —— **复用即升级**。

