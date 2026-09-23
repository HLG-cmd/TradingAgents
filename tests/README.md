# tests/ —— 测试

| 位置 | 谁写的 |
|---|---|
| `tests/*.py`（61 个） | **上游自带**（LLM agent 链、数据源、配置等），本项目**已弃用该链路**，但这些测试保留用于跟上游同步 |
| `tests/quant/`（2 个） | **我们自建**：`test_screener_engine.py`、`test_edgar_fundamentals.py` |

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q                    # 全量（基线 725 passed / 1 skipped）
./.venv/Scripts/python.exe -m pytest tests/quant/ -q              # 只看自建部分
```
