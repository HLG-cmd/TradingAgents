# 自动化任务记忆：量化选股因子季度衰减监测

## 任务定义
对 TradingAgents 趋势档因子做衰减监测，汇报基线/近期 IC、符号翻转、窗口敏感性、退出码。

## 关键路径修正（重要）
- 任务的命令 `factor_backtest.py --watch`（根目录）**不存在**。
- 实际入口：`quant/factor_backtest.py`；正确命令
  `./.venv/Scripts/python.exe quant/factor_backtest.py --watch`
- IC 历史文件实际在 `reports/_datasets/factor_ic_history.csv`（非 `reports/` 根）。
- 明细落盘 `reports/_datasets/factor_backtest_<YYYYmmdd>.csv`。
- 权重档案在 `quant/screener_engine.py::WEIGHT_PROFILES`：`garp`(trend .20)/
  `quality`(trend .05)/`no_trend`(trend .00)；`run_quant_screening(weights=...)` 可覆盖。

## 执行历史
### 2026-10-01
- 命令：`quant/factor_backtest.py --watch`（前瞻 21 日 / min-history 210）
- 样本：101/102 只可用（AMD 剔除），6726 交易日，311 期（2000-10-31~2026-08-31）
- 全样本 IC：趋势综合分 -0.0009 (t=-0.08)；mom60 +0.0002 (t=0.02)；is_bull -0.0039 (t=-0.39)
- 监测（近 12 期 vs 此前 299 期）：三者均无 t≥2 显著翻转；is_bull 符号翻转但 t=0.39 不显著
- 窗口敏感性：mom60 / is_bull / trend_score **全部 ✗ 符号漂移**（近 6 期全负、近 12 期转正）
- **退出码 = 2**（触发原因＝3 个因子符号漂移 + 0 个强告警）
- 累积历史：factor_ic_history.csv 3 条记录
- 结论：趋势档不稳健，任一基于它的权重缺乏依据；建议降权（quality 档或 trend=0），
  警告不得用单一近期窗口反拟合权重（过拟合）。

## 稳定结论（跨轮可复用）
- 退出码 2 在本项目**主要由「窗口符号漂移」触发**，而非强告警；属常态而非异常。
- 该监测是「每季度看一眼」性质，结论预计长期保持「不稳健」——不要据此反复改权重。
