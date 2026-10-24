# 工具索引（自动生成，勿手改）

- 生成时间：2026-10-24 11:33
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
| `quant/stats_utils.py` | 量化因子回测统计函数的**唯一定义源**（IC / ICIR / t-stat / 胜率 / 五分位收益差）。 | from quant.stats_utils import spearman, summarize, quintile_spread   （库；被回测脚本 import，不单独运行） |
| `quant/stock_pools.py` | 美股核心股票池定义与动态获取模块。 | ./.venv/Scripts/python.exe quant/stock_pools.py |
| `quant/wb_deep_dive.py` | 零成本深度投研流水线 —— 一站式自动化入口。 | ./.venv/Scripts/python.exe quant/wb_deep_dive.py |
| `scripts/_settlement.py` | 历史决策回溯结算工具（吸收上游 TauricResearch v0.6.0 settlement 思想） | ./.venv/Scripts/python.exe scripts/_settlement.py |
| `scripts/_verify_pack_tree.py` | 验证「交付树」与「审计包 _source.zip」**逐项内容一致**（通用版）。 | 任意标的 / 任意轮次 |
| `wb_analysis/_audit_empty_sections.py` | 审计证据包的「**小节正文为空**」—— 抓「通道全绿但内容是空」这类静默失败。 | ./.venv/Scripts/python.exe wb_analysis/_audit_empty_sections.py <evidence.md> [--strict] |
| `wb_analysis/_channel.py` | 采集通道健康度判据的**唯一定义源**（Single source of truth for channel ok_of）。 | from wb_analysis._channel import ok_of   （库；被各采集器 import，不单独运行） |
| `wb_analysis/_check_residuals.py` | 订正残留检查：防止「改了上游、忘了回头清下游」。 | ./.venv/Scripts/python.exe wb_analysis/_check_residuals.py <草稿目录> |
| `wb_analysis/_check_role_files.py` | 角色文件体检：篇幅 / 裸五档英文词 / 越界 PROPOSAL / 合规声明 / 必需小节。 | ./.venv/Scripts/python.exe wb_analysis/_check_role_files.py |
| `wb_analysis/_clock.py` | 唯一时间源（Single source of truth for time）。 | — |
| `wb_analysis/_contract.py` | 12 角色输出契约的**唯一常量来源** —— 评级词、档位、白名单、正则全在这里定义一次。 | from wb_analysis._contract import ...   （库；被门禁们 import，不单独运行） |
| `wb_analysis/_crosscheck_nasdaq.py` | 用 Nasdaq 官方公开 API 独立复核证据包 §1 的日线 OHLC（数据来源真实性核验）。 | ./.venv/Scripts/python.exe wb_analysis/_crosscheck_nasdaq.py <标的> [基准日]\n#   · 个股/ETF：官方接口直接逐条核对 OHLC\n#   · 指数（NDX/SPX）：官方接口不支持指数（rCode=400）⇒ 自动改用 QQQ/SPY 代理，只核对**日涨跌幅一致性** |
| `wb_analysis/_derive_a_etf.py` | A股 ETF 派生指标计算器：从 A 股 ETF 证据包导出「需要算术推导」的二级指标。 | ./.venv/Scripts/python.exe wb_analysis/_derive_a_etf.py 515100 2026-10-13 |
| `wb_analysis/_derive_ndx.py` | 派生指标计算器：从指数证据包导出所有「需要算术推导」的二级指标（支持 NDX / SPX）。 | ./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py |
| `wb_analysis/_derive_stock.py` | 个股派生指标计算器：从个股证据包导出所有「需要算术推导」的二级指标。 | ./.venv/Scripts/python.exe wb_analysis/_derive_stock.py |
| `wb_analysis/_erp_retry.py` | ERP 计算的重试包装器。 | ./.venv/Scripts/python.exe wb_analysis/_erp_retry.py |
| `wb_analysis/_fmt.py` | 采集/派生层共用的**纯格式化工具**（唯一定义源）。 | from wb_analysis._fmt import fnum, pct_str, ystr, wcode_of, compact_series   （库；不单独运行） |
| `wb_analysis/_gen_derived_ndx.py` | 把 _derive_ndx.py 的 stdout 落盘（避免 shell 重定向写中文 + /tmp 路径问题）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_derived_ndx.py |
| `wb_analysis/_gen_derived_stock.py` | 把 _derive_stock.py 的 stdout 落成证据包同级文件（避免 shell 重定向写中文）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py |
| `wb_analysis/_gen_meta.py` | 为草稿目录生成 `meta.json`（`assemble.py --from-dir` 的**必备**输入）。 | ./.venv/Scripts/python.exe wb_analysis/_gen_meta.py GOOG_2026-10-01 [NDX_2026-10-01 ...] |
| `wb_analysis/_gen_supplement.py` | 生成 `<TICKER>_<date>.supplement.md`：证据包 §3 被上游扣留时的**一等替代证据源**。 | ./.venv/Scripts/python.exe wb_analysis/_gen_supplement.py <TICKER> <YYYY-MM-DD> |
| `wb_analysis/_insider_agg.py` | 从证据包 §8 内部人交易 CSV 段落聚合买卖统计（回原始样本重数，不依赖任何摘要）。 | ./.venv/Scripts/python.exe wb_analysis/_insider_agg.py |
| `wb_analysis/_integrity.py` | 证据包**只读性**校验：采集时落一份 sha256 清单，交付门禁时比对。 | from wb_analysis._integrity import write_manifest, verify   （库；不单独运行） |
| `wb_analysis/_length.py` | 角色稿篇幅门禁的**唯一定义源**。 | from wb_analysis._length import MIN_CHARS_ANALYST, MIN_CHARS_DECISION, MAX_CHARS   （库；不单独运行） |
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
| `wb_analysis/_wrap_derived.py` | 把 _derive_ndx.py 的 stdout 包成 md 代码块，覆写 0_derived.md。 | ./.venv/Scripts/python.exe wb_analysis/_wrap_derived.py <src_path> <dst_path> |
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
| `scripts/_diff_evidence_pack.py` | 证据包等价性比对——用于 collect_index.py 拆分子模块前后的行为回归。 | — |
| `scripts/_health.py` | 项目健康检查：**一条命令看整个项目状态**（把散落的各处门禁汇总成一个入口）。 | ./.venv/Scripts/python.exe scripts/_health.py [--quiet] [--ci] |
| `scripts/_memory_index.py` | 为本地运行痕迹目录（`.workbuddy-ai/memory/`）生成**主题索引**（`_INDEX.md`）。 | ./.venv/Scripts/python.exe scripts/_memory_index.py [--check] |
| `scripts/_normalize_eol.py` | 把工作区里被误写成 CRLF 的**文本文件**恢复为 LF（.bat/.ps1 例外，规范要求 crlf）。 | python scripts/_oneoff/_normalize_eol.py   （把误写成 CRLF 的文本文件恢复为 LF） |
| `scripts/_probe_baseline.py` | （无文档字符串） | — |
| `scripts/_prune_backup.py` | 清理本地回滚包目录（`.workbuddy-ai/backup/`）：**按前缀各留最新 N 个**。 | ./.venv/Scripts/python.exe scripts/_prune_backup.py [--apply] |
| `scripts/_scan_project.py` | 只读扫描整个项目的「产物堆积」情况（不修改任何文件）。 | ./.venv/Scripts/python.exe scripts/_scan_project.py |
| `scripts/_scan_reports.py` | 只读扫描 `reports/` 与 `wb_analysis/` 的产物堆积情况，输出分类清单（不修改任何文件）。 | ./.venv/Scripts/python.exe scripts/_scan_reports.py |
| `scripts/_verify_all.py` | 治理落地验收（只读，不修改任何文件）。 | — |
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

> **`_oneoff/` 是本地审计收件箱（`.gitignore` 忽略，不入对外仓库）**：探针服务的那一轮交付并封存后，会**随案卷进 `reports/<标的>/<时间戳>/_source.zip`**，`_oneoff/` 于是回到空 —— **看到它空是正常的**。治理类一次性脚本（如 `_fix_round3.py`）同步留存于**历史 commit** 中；确需长期冷备份时放**项目外**（与仓库平级），不得在仓库内建备份目录。

| 文件 | 用途 | 用法 / 服务于 |
|---|---|---|
| （空） | — | — |

## 豁免（不是脚本，无需声明）

| 文件 | 原因 |
|---|---|
| `quant/__init__.py` | 包标记 / pytest 配置 |
| `wb_analysis/__init__.py` | 包标记 / pytest 配置 |

> 规则：探针若**第二次被复用**，就补文档 + `# usage:` 提升为 `reusable` —— **复用即升级**。

