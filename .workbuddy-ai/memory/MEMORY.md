# TradingAgents 项目长期记忆

> 本文件只存**每次都要遵守的**：架构 / 命令 / 12 角色契约 / 校验器硬约束 / 用户偏好（**铁律全文与单行索引见 `IRONLAWS.md`**）。
> ★★ **开工第一件事：完整读 `.workbuddy-ai/memory/IRONLAWS.md`（铁律 1–51 全文）** —— 索引会丢细节，**只照索引办事而没读全文 = 没读**。
> 备份：`_backup/`（`ls` 看全部，带日期后缀）。
> ★ 2026-10-14 记忆合并：原 `.workbuddy/`（国内版）整体迁入 `.workbuddy-ai/`，全量打包存 `.workbuddy-ai/backup/domestic_workbuddy_20261014_full.zip`；代码内旧路径引用已同步切换，`.workbuddy/` 已不再存在。

## 记忆与文档体例（改任何文件前先读）

**同一口径只在「该放它的那个文件」写一遍** —— 写两遍必然漂移，**漂移的工具比没有工具更危险**。

| 文件 | 放什么 | 何时读 |
|---|---|---|
| `MEMORY.md`（本文件） | 索引 + 每次都要遵守的硬约束 | 自动注入 |
| **`IRONLAWS.md`** | **全部铁律全文 + 单行索引表**（判据 / 阈值 / 陷阱） | **开工先读** |
| `DOMAINS.md` | 按标的·子系统（指数聚合 / ERP / 黄金 / 非美股 / 量化选股 / A股） | 碰到该领域时读 |
| `docs/WORKFLOW.md` / `docs/SCREENER.md` | 运行手册（不收设计论证） | 操作前读 |
| `wb_analysis/FRAMEWORK.md` | 12 角色输出契约（子智能体读它；**根目录没有同名文件**） | 下发角色时 |
| `docs/PROJECT_MAP.md` | **项目地图（第一入口）** | 看不懂结构时 |
| `README.md` / `CHANGELOG.md` | 上游归属+架构一句话 / 版本索引（一行一版） | — |
| `YYYY-MM-DD.md` | 当日流水。**归档到 `_backup/` 即止，不提炼** | — |

⚠️ 宿主按**字节**截断本文件 ⇒ 由 `scripts/_health.py`「记忆体积」门禁守住（≤14200 PASS）。
★ **`chk_doc_drift` 已于 2026-10-10 扩面 + 加第 4 条规则**（该盲区**已关闭**）：
扫描面 = `docs/*.md` ＋ `memory/**`（**当日流水除外** —— 它是 append-only 历史留痕）＋ `.workbuddy-ai/skills/*/SKILL.md` ＋ 根 `README/CHANGELOG` ＋ `wb_analysis/FRAMEWORK.md`，共 **12 份**；
规则 = 硬编码计数 ／ 迁移前旧路径 ／ 旧 `import` ／ **行号引用**（命中即 WARN，`--strict` 可升级）。
⇒ 起因：此前只扫 `docs/*.md` ⇒ memory 里 **13 处**陈旧数字与漂移行号长期零告警；检测逻辑已抽成纯函数 `scan_doc_text()`，`_selftest.py` 有 3 条双向夹具守着。
⇒ ⚠️ 门禁只管**格式类**漂移（计数/路径/行号；告诫语境与行号禁令本身不误报）——**语义漂移（数字对不对）仍须自己对源码复算**，判据＝能不能从常量派生。
⇒ **正文里禁止写行号**（形如「`.py` ＋冒号＋数字」，或独立的 `L` 加两位以上数字）；要引用就写**符号名**，让读者自己 `grep`。
**两条原则**：① 能靠代码根除的写进代码（`_precheck.py`/`_selftest.py`），不靠「记得注意」；② 改未被 git 跟踪的文档（`docs/**`、`.workbuddy-ai/**`）前**必须先备份**。

## 性质与架构（不可动摇）

TauricResearch 多智能体框架中文定制版 + 自建量化选股层（详见下方 `quant/` 包说明）。
**用户不付 LLM API 费** ⇒ 架构 = 免费数据层 + WorkBuddy 顶层模型推理：
采集（`wb_analysis/collect*.py`）→ 12 角色推理（按 `FRAMEWORK.md` 手写 md）→ 渲染（`assemble.py`）。
**不要建议加 `TRADINGAGENTS_LLM_PROVIDER`。**
★ **标的独立原则（Ticker Isolation）**：跑每支股票时完全独立分析，严禁被其他股票的历史教训/输赢偏见或其它无关因素影响；主流程切断跨标的记忆污染（`isolate_ticker_memory=True`）。

## 路径与命令

- 隔离环境：`./.venv/Scripts/python.exe`（项目自带，勿换）
- 证据/草稿/分析：`wb_analysis/{evidence,drafts,analysis}/<T>_<date>*`
- ★ 报告树 `reports/<TICKER>/<TICKER>_<YYYYmmdd_HHMMSS>/`（**按标的分子目录**；旧布局加 `assemble.py --flat`）
  · 每棵树含 `RUN.json`（数据基准日/来源草稿/证据/评级）⇒ 四命名空间由此精确关联
  · `_datasets/` 数据产品｜`_other/` 非 12 角色专题｜`_archive/` 归档+删除清单｜`_audit/` 审计｜`QUALITY.csv` 记分卡
  · `reports/INDEX.md` 自动索引（`wb_analysis/_reports_index.py`，`--check` 可作卫生门禁）
- ★ **自建代码在 `quant/` 包**（根目录无 `.py`）：库 4 个 ⇒ `from quant.xxx import yyy`；入口 5 个 ⇒ `python quant/xxx.py`；入口自带 sys.path 引导
  · 改后必跑回归基线 + **凭证断言** `from quant import edgar_fundamentals as ef; ef.SEC_USER_AGENT`（防 `.env` 静默失效）
- ★ **`wb_analysis/` 的共享库**（都是**无副作用**模块，只放常量/纯函数，供多工具 import）：
  · `_contract.py` = 12 角色契约常量（评级词/正则/白名单）唯一来源｜`_paths.py` = `reports/` 布局常量（`TREE_RE`/`FUNC_DIRS`/`ALLOWED_TOP`/`SKIP_ARCHIVE_DIRS`）唯一来源｜`_thresholds.py` = 跨工具阈值+市场时钟｜`_westock.py` = westock CLI 接入层
  · ⚠️ **不得 import `collect_index.py` 取常量** —— 它模块级 `os.chdir`+`load_dotenv` 会污染导入方进程
  · ⚠️ **不得在消费方本地重写契约常量**（手抄值＝违规，从常量派生＝合法）；`_selftest.py` 有 AST 检测器 + 双向夹具守着
- ★ **产物封存** `wb_analysis/_seal_run.py`（`--plan`/`--all --apply`/`--unseal`/`--orphans`）⇒ 一轮产物 = 树内 `_source.zip`+`SOURCE_MANIFEST.json`
  ⇒ `{evidence,drafts,analysis}` 与 `_oneoff/` **空是正常态**；删前必校验，不通过即中止
- ★ **共享缓存** `wb_analysis/_cache/`（ERP 序列、黄金面板等，**不属于任何一轮**，勿放 evidence/）
- ★ **回滚包保留＝按前缀各留 N 个**（不能全局取最新）；`scripts/_prune_backup.py` 清理；**宣布"备份不完整"前先查回收站**
- ★ **数据缺口台账**：`wb_analysis/_gap_ledger.py <T> <date> [--check <草稿目录>]`
  · 每轮产出 `evidence/<T>_<date>.gaps.json`（登记 `cls` A/B/C/S · `decisive` · `blocks` · `remedy` · `fallback`）
  · **决定性缺口未写进 `0_brief.md` ⇒ 门禁 FAIL**（`_precheck.py` 第 2 项）；**新通道须登记进 `RULES` 表**（键名＝通道名，非语义名）
- ★ **期权数据源随时点切换**（2026-10-17 起）：盘中走 yfinance；**盘前/盘后/非交易日自动切 CBOE 官方延迟报价**
  · 判据唯一来源 = `_thresholds.option_source_decision()`（**消费方只许转发，不得本地重写时段边界**）
  · 取数 = `wb_analysis/_option_source.py`｜台账 = `RULES["CBOE_fallback_used"]`（B 类/决定性）
  · ⚠️ **非盘中拿的是「上一时段收盘快照」，不是实时报价**（CBOE 延长时段仅覆盖 SPX/SPXW/XSP，
    **不含股票/ETF 期权**）⇒ 不得用于「此刻」类论断，**与盘中口径跨轮不可比**；两个源的 IV/偏斜**不可混用**
  · 覆盖：✅ 美股个股与主要 ETF｜❌ **指数符号**（NDX/^NDX，无期权，仍用 ETF 代理）｜❌ **A 股 ETF**
  · 自检 = `_selftest.py` 期权时点分支夹具（**时钟可注入，两条路径均可被夹具证明**）；回归 = `tests/test_option_source.py`
- ★ **脚本生命周期**：每个 `.py` 头部必须声明 `# lifecycle: reusable|maintenance|oneoff`
  （`__init__.py`/`conftest.py` 豁免）；`oneoff` 归同级 `_oneoff/`（**审计线索，不删**）；新探针用 `_tidy_scripts.py --new` 登记
- ★ **新文件放哪儿**（顺序问）：跑分析会用到→`wb_analysis/`；只在改代码排障用→`scripts/`；被调用的引擎→`quant/`；产出→`reports/`。**验收＝同一职责只在一处**
- ★ **回归基线**：`pytest tests/ -q -k "not DeepSeekLive"` ⇒ **747 passed/1 skipped/1 deselected**（须排除真实 API 测试，否则 402 假红）
- ★ **质量记分卡** `wb_analysis/_scorecard.py [--trend]` ⇒ `reports/QUALITY.csv`＝**「越用越好」的唯一度量**
- ★ **一条命令看项目状态**：`scripts/_health.py`（检查项以脚本输出为准）
- ★ `pyproject.toml` 的 `"quant*"` / `.gitignore` 瞬态+回滚包 —— 由 health「版本库忽略」门禁守
- ★ 运行卫生工具（`scripts/`）：**工具与用法见 `docs/TOOLS.md`**（自动生成）；共性铁律＝**删前先打包、逐项校验不过即中止**

```bash
VENV=./.venv/Scripts/python.exe
$VENV wb_analysis/collect.py AMD --date <美东当日>                      # 个股/ETF，35~37 通道
$VENV wb_analysis/collect_index.py --date <美东当日> --index NDX|SPX    # 指数专用
# ★ `--date` 口径＝**美东当日**（数据源的 today；既非本机日期、亦非末根 bar 日），默认即取美东当日
#   传更早日期会被守卫挡下（退出码 2）—— 那会**静默扣留 §3 估值快照**而通道健康度仍显全绿；确需按历史基准日复盘加 `--allow-stale-date`
$VENV wb_analysis/_gen_derived_stock.py AMD 2026-09-18                 # 二级指标，分析前必跑，会落盘
$VENV wb_analysis/_gen_meta.py <P>_<date>                              # ★ 渲染前必跑（2026-10-10 起为硬门禁：缺 meta.json ⇒ assemble 退出码 2）
$VENV wb_analysis/assemble.py --from-dir wb_analysis/drafts/<P>_<date> # 草稿目录须为嵌套结构
$VENV wb_analysis/erp_context.py --start 1990-01-01 --append
```
- `_derive_stock.py` 只打印不落盘 ⇒ 用 `_gen_derived_stock.py <T> <date>` 落盘
- ★ 黑名单放 `<draft>/_value_blacklist.json`（缺 ⇒ `_precheck`「口径一致性」静默跳过）

### ★ 交付前校验：只跑这一条
```bash
$VENV wb_analysis/_precheck.py wb_analysis/drafts/<P>_<date> \
    --evidence wb_analysis/evidence/<P>_<date>.md --report reports/<树>/
```
**7 项**：运行卫生 → 数据缺口台账 → 评级词/契约 → 口径一致性 → 数字溯源 → 时序新鲜度 → 报告树反读；输出 FAIL（阻断）/ WARN（过目）/ INFO。
- **判读规则已写进代码**：mtime 时序告警固定 INFO（已知假阳性，判据应是内容比对）；要阻断加 `--strict-freshness`。
- 单项工具可单独调用，但**别用它们的退出码做总体判断**（约定互不一致）。

### ★★ 先跑门禁自检

```bash
$VENV wb_analysis/_selftest.py      # 退出码 0 = 全过（双向夹具自检）
```
**没有自检的门禁只是更隐蔽的静默失败源** —— 门禁坏掉时的症状恰是「一切正常」。

### 退出码语义（不要凭直觉假设）

| 工具 | 退出码 |
|---|---|
| `_lint_drafts.py` | 0 无违规；**2 有契约违规（阻断）**；未溯源数字属顾问性，不阻断 |
| `_verify_ratings.py` | 0/1；必需 12 个角色文件，`0_*.md`/`_constraints.md` 缺只提示 |
| `_audit_values.py` / `_verify_report.py` | 0/1 |
| `_check_freshness.py` | 0 新鲜；1 有时序告警（假阳性） |

## 12 角色与契约

market / fundamentals / news / sentiment → bull ⇄ bear → manager → trader → aggressive ⇄ conservative ⇄ neutral → portfolio manager。
**依赖顺序不可破坏**（bear 逐条反驳 bull；trader 读 manager；3 风险读 trader；PM 读全部）。**可并行**：4 分析师之间、3 风险之间。
**评级词契约**：五档 `Buy`/`Overweight`/`Hold`/`Underweight`/`Sell`；交易员三档；情绪六档。
`extract_rating` 先找 `Rating: X` 标签，退化后取**第一个**五档英文词。契约详见 `FRAMEWORK.md`。

---

## 铁律速查

**铁律 1–51 全文 ＋ 单行索引表 ＋「低 PE 来源四件套」速查，全部在 `.workbuddy-ai/memory/IRONLAWS.md`。**

> ★★ 开工第一件事＝**完整读 `IRONLAWS.md`**。索引会丢细节，**只照索引办事而没读全文 = 没读**。
> 索引表已于 2026-10-10 随全文一并移入该文件：本文件长期贴近宿主**按字节截断**阈值（≈15000 B），
> 尾部「用户偏好」有被静默切掉的风险，故不在此重复该表。

## 契约与校验器的硬约束（**全文见 `IRONLAWS.md` 尾部**）

- `trader.md`：结论块首行 `**Action**: Sell`（Title Case）＋末行 `FINAL TRANSACTION PROPOSAL: **SELL**`（大写，恰 1 次）—— **两处大小写相反**
- 五档英文词白名单 **6 席**：manager / portfolio_manager / trader / aggressive / conservative / neutral（**结论块外出现即阻断**）
- 「自我合规声明」会命中自己的正则；`_lint_drafts.py` 已知假阳性见代码内注释

## 用户偏好

中文报告（评级词保留英文）；**必须显式标注数据缺口，禁止臆测填充**；抵触额外付费 API；
偏好结构化表格与显式推理；**愿意以时间换质量**；关心的不只是单次结论，还有**方案的耐久性**。
★ **标的独立性**：每支股票独立分析，严禁跨标的教训、输赢偏见或无关历史干扰；没用的陈旧记忆定期重置清理。
`reports/` 旧版/数据不全的**可清理**（用户已授权，但须先打包回滚包 + 逐文件清单）；**未经允许不擅自改动自动化**。
**「思考强度拉满 + 多 agent 并行 + 数据来源真实性不能缺」** ⇒ 证据包之外必须做**独立第三方核验**并写进简报（逐条标注「已核验 / 同源不可独立核验 / 不可得」），**不要只说「N/N 全绿」**（**这正是铁律 41 的教训**）。
**不看重流水式记忆**：**已被代码/门禁固化的结论不必抄进铁律**。
