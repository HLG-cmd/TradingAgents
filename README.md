# TradingAgents（本地改造版）

> 本项目 **fork 自** 上游 [`TauricResearch/TradingAgents`](https://github.com/TauricResearch/TradingAgents)（多智能体 LLM 金融交易框架）。

## 与原框架的根本区别

上游框架的核心是用「LLM agent 链自动分析」。本项目 **已弃用该链路**——用户 **不付任何 LLM API 费**，也不配置 OpenAI / Anthropic / Google 等 provider。

实际架构（一句话）：

> **免费数据层采集**（`wb_analysis/collect.py` / `collect_index.py`）
> → **WorkBuddy 顶层模型手工推理**（12 个角色文件按 `wb_analysis/FRAMEWORK.md` 手写 markdown）
> → **脚本渲染**（`wb_analysis/assemble.py --from-dir`）
> → 报告树 `reports/<TICKER>/<TICKER>_<时间戳>/`

## 怎么在这台机器上跑

本机自带隔离 Python，**不要换成别的**：

```
./.venv/Scripts/python.exe
```

**第一次看这个项目，先读地图**：**[`docs/PROJECT_MAP.md`](docs/PROJECT_MAP.md)** ——
一页说明每个目录/文件是干什么的、哪些是上游自带的、跑一次会动到哪些地方。

详细手册：

- [`docs/WORKFLOW.md`](docs/WORKFLOW.md) —— 端到端运行手册：采集 → 12 角色手工推理 → 渲染 → 报告树。
- [`docs/SCREENER.md`](docs/SCREENER.md) —— 量化选股子系统手册：`screener_engine.py` / `smart_screener.py` / `stock_pools.py` / `edgar_fundamentals.py` / `factor_backtest.py` / `price_history.py`。

常用入口（务必用上面的隔离 Python 调用）：

```bash
# 1) 采集指数 / 个股的免费证据包 → wb_analysis/evidence/<TICKER>_<日期>.md
./.venv/Scripts/python.exe wb_analysis/collect_index.py --date <YYYY-MM-DD> --top-insiders 12
./.venv/Scripts/python.exe wb_analysis/collect.py <TICKER> --date <YYYY-MM-DD>

# 2) 派生指标 → 落盘为草稿目录的 0_derived.md
./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py <YYYY-MM-DD>

# 3) 渲染：--from-dir 接的是**草稿目录**（不是 reports/！）
./.venv/Scripts/python.exe wb_analysis/assemble.py --from-dir wb_analysis/drafts/<TICKER>_<日期>
```

⚠️ `--from-dir` 必须指向 `wb_analysis/drafts/<TICKER>_<日期>`；直接用 `<TICKER> --date` 会命中
`wb_analysis/analysis/` 下的空骨架 JSON，渲染出评级全 Hold、正文全空的假报告。

## 目录速查

- `wb_analysis/` —— 本地改造核心：`FRAMEWORK.md`（12 角色框架说明）、免费数据采集（`collect.py` / `collect_index.py`）、报告渲染（`assemble.py`）；`drafts/`、`analysis/`、`evidence/` 存放各角色手写草稿、成品与分析素材。
- `reports/` —— 渲染产出的报告树，按 `reports/<TICKER>/<TICKER>_<时间戳>/` 组织。
- `tradingagents/` —— 上游原始 LLM agent 框架包。本项目已弃用其自动分析链路，仅作依赖 / 参考保留。
- `tests/` —— 单元与回归测试。

## License

Apache License 2.0。版权归属上游作者（Yijia Xiao et al.），详见 [`LICENSE`](LICENSE)。

## Citation

请引用上游工作：

Xiao, Y., Sun, E., Luo, D., & Wang, W. (2025). *TradingAgents: Multi-Agents LLM Financial Trading Framework*. arXiv:2412.20138. https://arxiv.org/abs/2412.20138
