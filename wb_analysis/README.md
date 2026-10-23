# wb_analysis/ —— 我们的流水线

**一句话**：从免费数据源采数据 → 算派生指标 → 写简报 → 12 个角色推理 → 渲染报告 → 过门禁。

## 代码（长期保留）

| 文件 | 作用 |
|---|---|
| `collect.py` / `collect_index.py` / `collect_a_etf.py` / `collect_a_stock.py` / `collect_hk_index.py` | 采集器：美股个股 / 指数 / A 股 ETF / A 股个股 / 港股指数（精确通道数以证据包末尾健康度汇总为准） |
| `_option_source.py` | **期权数据源适配器**：CBOE 官方延迟报价 → yfinance 同形接口。**盘前/盘后自动启用**（拿的是「上一时段收盘快照」，非实时报价；**仅美股个股与主要 ETF 有效**） |
| `_derive_stock.py` / `_derive_ndx.py` / `_derive_a_etf.py`（落盘器：`_gen_derived_stock.py` / `_gen_derived_ndx.py`） | 派生指标（均线、ATR、分位、聚合估值、折溢价等） |
| `assemble.py` | 渲染器：12 个角色的 md → 报告树 |
| `_precheck.py` | **交付门禁**（项数以脚本自报为准；含缺口台账、小节正文、快照自洽、收益质量、评级契约、口径对账、数字溯源、时序、报告树反读） |
| `_selftest.py` | 门禁自检（双向夹具，确认门禁本身没坏；项数以脚本自报为准） |
| `_gap_ledger.py` | 数据缺口台账（决定性缺口必须写进简报） |
| `_role_prompt.py` | **单角色提示词生成器**：跨平台拆分 12 个角色（白名单/禁读/契约/篇幅/自验），见 `docs/AGENT_PROTOCOL.md` |
| `_seal_run.py` | 产物封存：把一轮的中间产物打包进报告树 |
| `_reports_index.py` | 报告索引 + 卫生检查 |
| `_scorecard.py` | 质量记分卡（写 `reports/QUALITY.csv`；封存后跑一次） |
| `FRAMEWORK.md` | 12 角色输出契约（子智能体读它） |

## 两条硬规矩（2026-10-19 起）

1. **篇幅看密度不看字数**：单角色 **4,000–4,800 字符**（硬下限 4,000，>6,000 判偏长）。
   每句话都要承载信息；重复句会被 `_lint_drafts.py` 4d 节点名（铁律 53）。
2. **算式必须可复算**：`a op b = c` 由 lint 4b 节重算；算错比算少更危险（铁律 54）。

## 产物（**瞬态** —— 跑完即封存，平时应为空）

| 目录 | 内容 | 正常状态 |
|---|---|---|
| `evidence/` | 证据包（原始事实清单） | 空 |
| `drafts/` | 草稿（12 角色 md + 简报 + 约束） | 空 |
| `analysis/` | 分析 JSON（给上游入口用） | 空 |

> **看到这三个目录是空的，是正常的**，说明上一轮已经封存进 `reports/<标的>/<时间戳>/_source.zip` 了。
> 如果堆了东西 → `_seal_run.py --plan` 看，再 `--all --apply` 封存。

## 缓存（长期）

`_cache/` —— 共享参考数据（ERP 历史序列、黄金面板等），不属于任何一轮运行。

先读 `docs/RULES.md`（铁律全文）、`docs/DOMAINS.md`（领域口径）与 `docs/AGENT_PROTOCOL.md`（子智能体拆分）；改完跑 `_selftest.py`。
