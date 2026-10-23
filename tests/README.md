# tests/ —— 测试

| 位置 | 覆盖范围 |
|---|---|
| `tests/test_*.py` | **上游框架测试**（LLM agent 链、数据源、配置等）+ **自建流水线与门禁测试**（`test_wb_*.py`、`test_nan_daily_fix.py`、`test_seal_run_safety.py` 等） |
| `tests/quant/` | **自建量化引擎测试**（`test_screener_engine.py`、`test_edgar_fundamentals.py`、回测与缓存清理等） |

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q -k "not DeepSeekLive"  # 全量确定性回归（基线以 scripts/_health.py 的 BASELINE_PASSED 为准）
./.venv/Scripts/python.exe -m pytest tests/quant/ -q                  # 只看量化子包测试
```
