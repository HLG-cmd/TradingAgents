"""零成本深度投研流水线。

模块：
    collect        个股免费证据采集（复用 TradingAgents 数据层，不调用任何 LLM）
    collect_index  指数免费证据采集（自建聚合估值 / 成分结构 / 市场广度 / 内部人聚合）
    assemble       把分析结果（草稿目录或分析 JSON）渲染成与上游同构的报告树

适用对象区分（重要）：
    个股 → collect.py        有财报、PE/PB、内部人交易、cashtag 情绪
    指数 → collect_index.py  无财报与估值字段（^NDX 返回 NO_DATA_AVAILABLE），
                             四个维度必须从成分股聚合得出；指数也没有内部人交易，
                             须以成分股内部人净额作为代理。

框架规范见 FRAMEWORK.md；一站式入口见项目根的 wb_deep_dive.py。
"""
