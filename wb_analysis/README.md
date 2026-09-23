# wb_analysis/ —— 我们的流水线

**一句话**：从免费数据源采数据 → 算派生指标 → 写简报 → 12 个角色推理 → 渲染报告 → 过门禁。

## 代码（长期保留）

| 文件 | 作用 |
|---|---|
| `collect.py` / `collect_index.py` | 采集器：个股 / 指数，各约 35 项数据 |
| `_derive_stock.py` / `_derive_ndx.py` | 派生指标（均线、ATR、分位、聚合估值等） |
| `assemble.py` | 渲染器：12 个角色的 md → 报告树 |
| `_precheck.py` | **交付门禁**（7 项检查，交付前只跑这一条） |
| `_selftest.py` | 门禁自检（双向夹具，确认门禁本身没坏；项数以脚本自报为准） |
| `_gap_ledger.py` | 数据缺口台账（决定性缺口必须写进简报） |
| `_seal_run.py` | 产物封存：把一轮的中间产物打包进报告树 |
| `_reports_index.py` | 报告索引 + 卫生检查 |
| `FRAMEWORK.md` | 12 角色输出契约（子智能体读它） |

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

## 想改代码前

先读 `.workbuddy/memory/MEMORY.md` 与 `IRONLAWS.md`（铁律全文）；改完跑 `_selftest.py`。
