# 运行手册（Runbook）—— 这套 Agent 流程该怎么跑

> 面向使用者，不是开发者。设计原理与能力边界见 `SCREENER.md`。
>
> ★ **只是想跑一只标的？** 直接看 **[`../README.md`](../README.md) 的「怎么在这台机器上跑」** ——
> 那里按「标的类型 → 用哪个采集器」给了四条链路的完整配方（美股个股 / 美股指数 / A股ETF / 港股指数）。
> 本文件讲的是**三层流程的整体设计与边界**，偏方法论。

---

## 0. 先读这一段（决定了你怎么用这套东西）

**量化打分未被证明有选股能力。** 实测（纳指100）：

| 档 | 权重 | 1 个月前瞻 IC |
|---|---|---|
| 质量（ROE+净利率） | 35% | −0.012 |
| 估值（低 PE） | 30% | −0.015 |
| 成长（营收增速） | 30% | +0.001 |
| 趋势（动量+均线+RSI） | 5% | −0.001 |
| **综合分** | 100% | **−0.008** ⚠️ 旧权重下测得 |

> 权重为 **2026-10-02** 起的默认值：趋势档由 20% 降为残差 5%（311 期月频回测
> IC −0.0009 / t −0.08，95% CI≈±0.01 ⇒ 区间已足以排除有意义的效果）。
> IC 列是各档**各自最近一次**回测读数，样本期与观测数不同 ⇒ **不要跨档比绝对值**。
> ⚠️ **综合分一行是改权重之前的读数**（它依赖 `FACTOR_WEIGHTS`）；要更新须重跑
> `fundamental_backtest.py`，否则别再引用它。权威数值见 `screener_engine.FACTOR_VALIDATION`。

加了行业中性化也一样。**所以这套流程的正确用法是：**

> 把量化打分当作**压缩研究范围**的漏斗，**不是**当作「买前几名就会赢」的排序。

它把 102 只压到 10 只、让你少看 90 份财报 —— 这是它的价值；它的价值**不是**替你决定买什么。

---

## 1. 三层流程总览

| 层 | 做什么 | 命令 |
|---|---|---|
| **1. 量化漏斗**（零成本、分钟级） | 102 只 → 10~20 只候选。**只做减法，不做判断**，只看范围不看名次 | `python quant/wb_deep_dive.py --pool nasdaq --top 10` |
| **2. 深度尽调**（零外部 API 费，多智能体 12 角色推理） | 逐只采证 → 12 角色分析 → 渲染报告树。**这才是产生结论的地方** | `python quant/wb_deep_dive.py --tickers NVDA,MU,SNDK` |
| **3. 定期验证**（季度，10 分钟） | 检查因子是否失效 / 翻转。已设为自动化，也可手动跑 | `python quant/factor_backtest.py --watch`<br>`python quant/fundamental_backtest.py --watch --neutral` |

第 1 层输出候选 → 第 2 层输出 `reports/<TICKER>_<时间戳>/`。

---

## 2. 第 1 层：量化漏斗

### 2.1 首次运行（需要建缓存，慢）

```bash
cd D:\Antigravity\TradingAgents

# 预热 EDGAR 基本面（仅首次 / 每季度重跑；102 家约 146 秒、缓存 342 MB）
python -c "from quant.stock_pools import get_latest_nasdaq_100 as g; from quant.edgar_fundamentals import preload; preload(g())"

# 预热长周期价格（仅首次；102 家约 42 秒、缓存 47 MB）
python -c "from quant.stock_pools import get_latest_nasdaq_100 as g; from quant.price_history import preload_prices; preload_prices(g())"

# 量化筛选并导出 CSV
python quant/wb_deep_dive.py --pool nasdaq --top 10
```

> 若只做日常筛选、不做回测，**长周期价格可以不预热**（它只服务回测）。

### 2.2 日常运行（约 20 秒）

```bash
python quant/wb_deep_dive.py --pool nasdaq --top 10
```

**产物**：`reports/radar_nasdaq_<日期>.csv`（全量量化明细，UTF-8 BOM，Excel 可直接开）

**看什么**：
- `failed_records` / 剔除率 —— 正常应为 **0**；突然升高先怀疑网络限流
- `last_bar` —— 确认数据到哪个交易日（**北京时间上午跑 = 美东盘中，末根 K 线未收盘**）
- 榜单本身 —— 只用来决定「看哪 10 只」

**不要做什么**：
- 不要因为某只排第 1 就买它（IC≈0）
- 不要在盘中（北京时间上午~中午）用这份数据下结论（末根 K 线是半场数据）

### 2.3 权重档案（可选）

```bash
python quant/smart_screener.py --pool nasdaq --skip-agent          # 默认 quality
```
```python
from quant.screener_engine import run_quant_screening, WEIGHT_PROFILES
run_quant_screening(tickers, weights=WEIGHT_PROFILES["no_trend"])
```
| 档案 | 趋势权重 | 用途 |
|---|---|---|
| `quality`（默认） | 0.05 | 趋势档压到残差（2026-10-02 起） |
| `garp`（旧默认） | 0.20 | 四维均衡；保留作对照/回退 |
| `no_trend` | 0.00 | 完全不要动量暴露 |

实测差异（纳指100，2026-09-30 快照按两套权重重算）：旧→新默认 秩相关 **0.93**、
**前 10 名换 2 个**、最大名次移动 **26 位**（NXPI 46→20）；趋势分高的被降
（WDAY 趋势 97 → 掉 20 位）、趋势分低的被升（NFLX 趋势 24 → 升 21 位）。
⇒ **改权重确实改榜单，不是空操作。**（早前记录：PLTR 随趋势档降权 #4 → #7 → 掉出前八。）

---

## 3. 第 2 层：深度尽调（真正产生结论的地方）

### 3.1 采证

```bash
# 美股个股（wb_deep_dive 是它的便捷入口；也可直接用 collect.py）
python quant/wb_deep_dive.py --tickers NVDA,MU,SNDK      # 从第 1 层候选里挑 1~3 只
python quant/wb_deep_dive.py --tickers NVDA --no-news --no-social   # 想更快：跳过新闻与社媒（约 30 秒/只）
```

⚠️ **`wb_deep_dive.py` 只覆盖「美股个股」。其他三类标的各有专用采集器**
（A股ETF / 港股指数 / 美股指数），**入口对照表见 [`../README.md`](../README.md)**。

**产物**：`wb_analysis/evidence/<TICKER>_<日期>.md`（+ `.json`）
**看什么**：结尾的**通道健康度**。全绿（30/30 左右）才说明证据完整；
有 `unavailable` 的项目要记进报告的「数据缺口」。
⚠️ **全绿 ≠ 数据完整** —— 有通道会「报 ok 但内容整节为空」，必须打开关键节实际确认。

### 3.2 推理（多智能体 12 角色执行）

让各智能体角色：读证据包 → 按 `wb_analysis/FRAMEWORK.md` 的 12 角色框架写
`wb_analysis/drafts/<TICKER>_<日期>/` 下的 12 个 `.md`。

**两条硬规矩**（否则报告会出错）：
1. **结论块放文首** —— `extract_rating` 取全文**第一个**五档英文词
2. **正文不要出现裸的 `Buy` / `Underweight` 等英文评级词** —— 会被误读成结论

### 3.3 渲染

```bash
# 必须用 --from-dir（走草稿目录）；直接用 TICKER 会命中空骨架 JSON！
python wb_analysis/assemble.py --from-dir wb_analysis/drafts/NVDA_2026-09-16
```
**产物**：`reports/<TICKER>/<TICKER>_<YYYYmmdd_HHMMSS>/` 报告树（**按标的分子目录**；
旧扁平布局 `reports/<TICKER>_<时间戳>/` 需 `assemble.py --flat`）

### 3.4 渲染后必须反读校验

```python
from tradingagents.agents.utils.rating import extract_rating
extract_rating(open('reports/<树>/2_research/manager.md', encoding='utf-8').read())
extract_rating(open('reports/<树>/5_portfolio/decision.md', encoding='utf-8').read())
```
assemble 的「契约校验通过」只覆盖格式，**不保证评级没被误读**。

---

## 4. 第 3 层：定期验证（季度）

```bash
python quant/factor_backtest.py --watch              # 价格类因子（权重 5%：trend 档）
python quant/fundamental_backtest.py --watch --neutral  # 基本面类（权重 95%，EDGAR）
```
（权重随 `screener_engine.FACTOR_WEIGHTS` 走，**本文不另写死**；2026-10-02 起 trend 已由 20% 降为 5%。）
**退出码 2 = 有告警。** 已配置季度自动化（下次 2026-10-01），到点会汇报。

---

## 5. 回测的正确跑法（重要，容易跑错）

### 5.1 最可信的一组（推荐直接用）

```bash
# 17 个不重叠年度观测，2009-2025，行业中性化 —— 目前口径最干净的一组
python quant/fundamental_backtest.py --forward 252 --rebalance 12 --neutral --start 2009-01
```

实测（详见 `SCREENER.md` 3.1）：四个因子的 IC **点估计全部为负**，综合分胜率仅 18.8%，
但**都未达显著** ⇒ 结论仍是「**尚未证明有选股能力**」。

### 5.2 其它口径

```bash
python quant/fundamental_backtest.py --neutral        # 月度调仓 + 1 个月前瞻
python quant/factor_backtest.py --watch                # 价格类因子
```

### 5.3 ⚠️ 两个必须知道的陷阱

**① 窗口重叠会虚高显著性。** 只要 `前瞻 > 1.5 × 调仓间隔`，脚本就会打印警告并给出「有效独立样本数」。
早期跑出的「12 个月 IC −0.10、t −7.5」就是重叠 12 倍的假显著，**已作废**。
⇒ **看到「有效独立样本数」远小于名义期数时，不要把 t 值当确切显著性。**

**② 价格历史必须够长。** 上游 `load_ohlcv` 只有**固定 5 年**，
实测 `--forward 252 --rebalance 12` 在 5 年数据下**只有 3 个观测点**（统计上等于零）。
已由 `price_history.py` 提供**自 2000 年（约 26 年）**的价格：

```bash
python -c "from quant.stock_pools import get_latest_nasdaq_100 as g; from quant.price_history import preload_prices; preload_prices(g())"   # 一次性预热，42 秒
```

⚠️ **但基本面受 EDGAR XBRL 覆盖限制，实际可用起点约 2009 年**（XBRL 强制披露自 2009 起）
⇒ 长周期回测是 **2009 至今**，不是价格文件的 2000 年。**这是数据源本身的边界。**

### 5.4 EDGAR 时点值为什么可信

每条 XBRL 记录都带 `filed`（申报日）——「在 T 日市场知道什么」= `filed <= T` 中 `end` 最晚的那条，
保证不会用到当时尚未公布的数据。**三个必须避开的坑**（`start` 字段时长过滤 / tag 回退链取覆盖最新期间 /
拆股口径 `市值 = 复权价 × 申报股本 × F`）见 `docs/DOMAINS.md` → 量化选股子系统 / SEC EDGAR，
回归测试见 `tests/quant/test_edgar_fundamentals.py`。

---

## 6. 频率建议

| 动作 | 频率 | 耗时 |
|---|---|---|
| 第 1 层量化筛选 | 每周或每月 | 20 秒 |
| EDGAR 预热 | 每季度 | 150 秒 |
| 第 2 层深度尽调 | 按需 | 采证 1~2 分/只，推理取决于你要多深 |
| 因子监测 | 每季度（已自动化） | 10 分钟 |
| 股票池核对 | 每年 12 月 + 每季度 | 自动同步，留意日志有无降级告警 |
| 回归测试 | 改动代码后 | 10 秒 |

---

## 6.5 磁盘与缓存

全部缓存位于 `~/.tradingagents/`，**稳态约 400 MB**。

| 目录 | 内容 | 策略 | 稳态 |
|---|---|---|---|
| `edgar/` | EDGAR XBRL facts | **按季度**命名，翻季自动失效，预热后清理旧季度 | **342 MB** |
| `prices/` | 长周期价格（2000 起） | 每票一个文件，原地刷新 | 47 MB |
| `cache/` | 成分股 / 行业 / 选股结果 | 单文件 + TTL；选股结果按天留存 | 14 MB |

⚠️ **缓存绝不可按天命名** —— EDGAR 一套就是 342 MB，按天留会以每天 342 MB 累积
（7 天 2.4 GB → 365 天 123 GB），而 XBRL facts **只在季报/年报发布时变化**，
按天缓存毫无意义。**凡是「按日期累积」的缓存都要改成单文件 + TTL / 按季度命名。**

```python
from quant.edgar_fundamentals import cache_size_mb, prune_cache
print(cache_size_mb())      # 当前占用（MB），可用于监控
prune_cache()               # 手动清理非当前季度
```
**季度翻页注意**：跨季度后首次预热会重下全套（约 146 秒），这是**预期行为，不是故障**。

---

## 7. 故障速查

| 症状 | 原因 / 处理 |
|---|---|
| 剔除率突然升高 | Yahoo 限流 → 把 `screener_engine.MAX_WORKERS` 从 5 降到 3 |
| 某标的持续「无行情数据」 | 多半已退市（错误信息会给出最后交易日） |
| `[Pool] ⚠️ 动态同步失败` | Wikipedia 不可达 → 会用静态快照，**留意快照会过期** |
| EDGAR `403` | `SEC_USER_AGENT` 不合格 → 设成 `"你的名字 your@email.com"` |
| Excel 里中文乱码 | CSV 必须带 UTF-8 BOM（用 `export_radar_csv` 导出的都对） |
| 报告评级全是 Hold 且正文空 | 命中了空骨架 JSON → 必须用 `assemble.py --from-dir` |
| 输出表格全被截成「…」 | 终端宽度；`smart_screener` 已固定为 200 列 |
| 磁盘突然涨到几 GB | EDGAR 缓存跨季度累积 → 跑 `prune_cache()`；稳态应约 400 MB |
| 季度翻页后首次预热要 146 秒 | **正常**：跨季度需重下全套 facts |

---

## 8. 投产状态与一句话总结

| 维度 | 状态 |
|---|---|
| 数据层 | ✅ 行情 26 年、基本面时点化（EDGAR）、成分股 + 行业动态同步 |
| 打分层 | ✅ 可用，但**未被证明有预测力**（见第 0 节） |
| 验证层 | ✅ 两套回测 + 衰减监测 + 季度自动化 |
| 保护层 | ✅ 两套「门禁自检」+ 契约常量单一来源（`_contract.py`）；测试数请跑 `pytest --collect-only` 或 `scripts/_health.py` 读，**本文不写死数字** |
| 运维层 | ✅ 缓存稳态 400 MB、季度轮换、失败可知 |
| 文档 | ✅ 本手册 + `SCREENER.md`（设计原理与能力边界） |
| **待办** | 标普500 全量池接入、季度监测纳入基本面回测、`SP_500_CORE` 接动态同步 |

> ⚠️ **本文档不写死「测试数 / 脚本数 / 通道数」这类会漂移的数字**（2026-10-08 起）。
> 历史教训：本表曾写「508 个单元测试」，而实际早已 737 —— 差 229 却无人察觉，
> 因为**没人会记得回来改**。凡是想引用这类数字，一律现场跑命令取当前值：
> `pytest tests/ -q --collect-only | tail -1`、`scripts/_health.py`、`docs/TOOLS.md`（自动生成）。

**前三层里，第 1 层只做减法，第 2 层才做判断，第 3 层负责告诉你前两层还值不值得信。**

它能可靠提供的：**干净的股票池、完整的免费证据包、结构化的分析框架、可追溯的验证**。
它**不能**提供的：**有统计依据的收益排序** —— 这正是反复验证后确认的结论。

**结论：可以投入使用，但要按第 0 节的定位用。**
