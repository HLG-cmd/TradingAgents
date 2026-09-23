# tradingagents/ —— 上游引擎本体

**上游 TauricResearch/TradingAgents 的框架代码**（多智能体 LLM 交易框架、数据源适配、图执行）。

⚠️ 本项目**只用它的数据源层**（`tradingagents/dataflows/`：行情、财报、新闻等免费通道），
**不用它的 LLM agent 链**（不付 API 费）。
⇒ **改本项目功能时不要动这里**；要动先想清楚能否跟上游同步。

依赖它的自建代码：`wb_analysis/collect*.py`（取数）、`quant/*`（回测取价）。
