# quant/ —— 自建量化与分析层

**一句话**：选股漏斗、因子回测、财报取数、价格历史这些"自建引擎"代码。
**2026-09-23 从项目根目录收进来** —— 之前 9 个 `.py` 散在根目录，看不出哪些是上游、哪些是我们写的。

## 库里有什么

| 文件 | 作用 | 角色 |
|---|---|---|
| `screener_engine.py` | 多因子打分与量化筛选引擎 | **库**（被上层入口与测试 import） |
| `stock_pools.py` | 股票池定义与成分拉取（NDX / SP500 / SP1500） | **库**（被选股、回测与指数采集器 import） |
| `edgar_fundamentals.py` | SEC EDGAR 财报取数（XBRL，含 point-in-time、TTM、多年 CAGR） | **库**（被基本面回测与增长复核 import） |
| `price_history.py` | 长周期价格历史加载（回测用，可拉到 2000 年） | **库**（被因子与基本面回测 import） |
| `smart_screener.py` | **入口**：四维 GARP 选股漏斗 + 对抗辩论 | 直接运行 |
| `wb_deep_dive.py` | **入口**：单标的深度尽调 | 直接运行 |
| `factor_backtest.py` | **入口**：因子逐年稳健性回测（`--watch` 看不重叠双样本 t 检验） | 直接运行 |
| `fundamental_backtest.py` | **入口**：基本面因子回测（可 `--pool` 换池） | 直接运行 |
| `cleanup_cache.py` | **入口**：清理数据缓存 | 直接运行 |

## 怎么用

```bash
# 库：被别人 import
from quant import screener_engine, stock_pools, edgar_fundamentals, price_history
from quant.stock_pools import NASDAQ_100, get_latest_sp500

# 入口：直接运行（**必须带 quant/ 前缀**）
./.venv/Scripts/python.exe quant/smart_screener.py
./.venv/Scripts/python.exe quant/factor_backtest.py --watch
```

`screen.bat` 已经指向 `quant/smart_screener.py`，双击即可。

## 两条必须知道的约束

1. **入口脚本自带 `sys.path` 引导**。
   `python quant/xxx.py` 时 `sys.path[0]` 是 `quant/`、**项目根不在路径里**，
   所以每个入口都先把自己所在包的父目录塞进 `sys.path`，否则 `from quant import ...` 会报
   `No module named 'quant'`（实测踩过）。
2. **包内不许用"裸模块名"导入**。
   `import stock_pools` 只在根目录时代能成立；包内一律写 `from quant import stock_pools`，
   否则从别的目录运行时会失败。

## 改代码前的回归清单

```bash
./.venv/Scripts/python.exe -m pytest tests/ -q -k "not DeepSeekLive"    # 全量确定性测试（基线以 scripts/_health.py 的 BASELINE_PASSED 为准）
./.venv/Scripts/python.exe -m pytest tests/quant/ -q                    # 只跑本包专属单元测试
./.venv/Scripts/python.exe -c "from quant import edgar_fundamentals as ef; print(ef.SEC_USER_AGENT)"     # 凭证仍从根 .env 读到
```
第三条是**防静默失效**的关键：`edgar_fundamentals` 按自己所在目录找 `.env`，
搬进 `quant/` 后若不改成 `parents[1]`，会去找 `quant/.env` ⇒ **读不到就走默认 UA，EDGAR 直接 403**。
