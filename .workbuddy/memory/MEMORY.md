# TradingAgents 项目长期记忆

> 本文件只存**每次都要遵守的**：架构 / 命令 / 12 角色契约 / **铁律单行索引** / 校验器硬约束 / 用户偏好。
> ★★ **开工第一件事：完整读 `.workbuddy/memory/IRONLAWS.md`（铁律 1–37 全文，约 44KB）** ——
> 本文件只放**索引**，索引会丢细节；**只照索引办事而没读全文 = 没读**。
> 备份：`_backup/MEMORY_20260922_pre-slim.md`、`backup/MEMORY_PRE_slim_20260926.md`（各次精简前原文）。

## 记忆与文档体例（改任何文件前先读）

**同一口径只在「该放它的那个文件」里写一遍** —— 写两遍必然漂移，**漂移的工具比没有工具更危险**。

| 文件 | 放什么 | 何时读 |
|---|---|---|
| `MEMORY.md`（本文件） | 索引 + 每次都要遵守的硬约束 | 自动注入 |
| **`IRONLAWS.md`** | **全部铁律全文**（判据 / 阈值 / 陷阱） | **开工先读** |
| `DOMAINS.md` | 按标的·子系统（指数聚合 / ERP / 黄金 / 非美股 / 量化选股 / A股 等） | 碰到该领域时读 |
| `SKILL.md` | 只放**怎么做**（步骤/命令/顺序/检查点），陷阱**指向**上两个 | 执行时读 |
| `docs/WORKFLOW.md` / `docs/SCREENER.md` | 运行手册（不收设计论证） | 操作前读 |
| `FRAMEWORK.md` | 12 角色输出契约（子智能体读它） | 下发角色时 |
| `docs/PROJECT_MAP.md` | **项目地图：每个目录干什么（第一入口）** | 看不懂结构时 |
| `README.md` / `CHANGELOG.md` | 上游归属+架构一句话 / 版本索引（一行一版） | — |
| `YYYY-MM-DD.md` | 当日流水。**归档到 `_backup/` 即止，不强行提炼** | — |

⚠️ 宿主按**字节**截断本文件（≈15,000）⇒ 必须 < 15KB，否则尾部**用户偏好**静默丢失。
**两条原则**：① 能靠代码根除的写进代码（`_precheck.py`/`_selftest.py`），不靠「记得注意」；② 改未被 git 跟踪的文档（`docs/**`、`.workbuddy/**`）前**必须先备份**。

## 性质与架构（不可动摇）

TauricResearch 多智能体框架中文定制版 + 自建量化选股层（`screener_engine.py` / `smart_screener.py` / `stock_pools.py`）。
**用户不付 LLM API 费** ⇒ 架构 = 免费数据层 + WorkBuddy 顶层模型推理：
采集（`wb_analysis/collect*.py`）→ 12 角色推理（按 `FRAMEWORK.md` 手写 md）→ 渲染（`assemble.py`）。
**不要建议加 `TRADINGAGENTS_LLM_PROVIDER`。**

## 路径与命令

- 隔离环境：`./.venv/Scripts/python.exe`（项目自带，勿换）
- 证据/草稿/分析：`wb_analysis/{evidence,drafts,analysis}/<T>_<date>*`
- ★ 报告树 `reports/<TICKER>/<TICKER>_<YYYYmmdd_HHMMSS>/`（**按标的分子目录**；旧布局加 `assemble.py --flat`）
  · 每棵树含 `RUN.json`（数据基准日/来源草稿/证据/评级）⇒ 四个命名空间由此精确关联
  · `_datasets/` 数据产品｜`_other/` 非 12 角色专题｜`_archive/` 归档+删除清单｜`_audit/` 审计｜`QUALITY.csv` 质量记分卡
  · `reports/INDEX.md` 自动索引（`wb_analysis/_reports_index.py`，`--check` 可作卫生门禁）
- ★ **自建代码在 `quant/` 包**（根目录无 `.py`）：库 4 个 ⇒ `from quant.xxx import yyy`；入口 5 个 ⇒ `python quant/xxx.py`；入口自带 sys.path 引导
  · 改后必跑回归基线 + **凭证断言** `from quant import edgar_fundamentals as ef; ef.SEC_USER_AGENT`（防 `.env` 静默失效）
- ★ **项目地图**：`docs/PROJECT_MAP.md`（**看不懂目录名时的第一入口**）；`docs/` 放全部手册；各关键目录自带 `README.md`
- ★ **产物封存** `wb_analysis/_seal_run.py`（`--plan`/`--all --apply`/`--unseal`/`--orphans`）⇒ 一轮产物 = 树内 `_source.zip`+`SOURCE_MANIFEST.json`
  ⇒ `{evidence,drafts,analysis}` 与 `_oneoff/` **空是正常态**；删前必校验，不通过即中止
- ★ **共享缓存** `wb_analysis/_cache/`（ERP 序列、黄金面板等，**不属于任何一轮**，勿放 evidence/）
- ★ **回滚包保留＝按前缀各留 N 个**（不能全局取最新，否则大包被小包顶掉）；`scripts/_prune_backup.py` 清理；**宣布"备份不完整"前先查回收站**
- ★ **数据缺口台账**：`wb_analysis/_gap_ledger.py <T> <date> [--check <草稿目录>]`
  · 每轮产出 `evidence/<T>_<date>.gaps.json`（登记 `cls` A/B/C/S · `decisive` · `blocks` · `remedy` · `fallback`）
  · **决定性缺口未写进 `0_brief.md` ⇒ 门禁 FAIL**（`_precheck.py` 第 2 项）；新通道须登记进 `RULES` 表，否则标 `?` 要求人工归类
- ★ **脚本生命周期**：每个 `.py` 头部必须声明 `# lifecycle: reusable|maintenance|oneoff`
  （`__init__.py`/`conftest.py` 豁免）；`oneoff` 归同级 `_oneoff/`（**审计线索，不删**）；新探针 `_tidy_scripts.py --new <名字> --serves <标的> <日期>`
- ★ **新文件放哪儿**（顺序问）：跑分析会用到→`wb_analysis/`；只在改代码排障用→`scripts/`；被调用的引擎→`quant/`；产出→`reports/`。**验收＝同一职责只在一处**
- ★ **回归基线**：`pytest tests/ -q -k "not DeepSeekLive"` ⇒ **724 passed/1 skipped**（**须排除真实 API 测试**，否则没余额时 402 假红）；已进门禁
- ★ **质量记分卡** `wb_analysis/_scorecard.py [--trend]` ⇒ `reports/QUALITY.csv`＝**「越用越好」的唯一度量**
- ★ **一条命令看项目状态**：`scripts/_health.py`（检查项以脚本输出为准 —— **此处不抄清单，抄了必漂移**）
- ★ `pyproject.toml` 的 `packages.find` 含 `"quant*"`；`.gitignore` 覆盖瞬态目录与 `.workbuddy/backup/`
- ★ 运行卫生工具（`scripts/`）：**全部工具与用法见 `docs/TOOLS.md`**（自动生成）；共性铁律＝**删前先打包、逐项校验不过即中止**

```bash
VENV=./.venv/Scripts/python.exe
$VENV wb_analysis/collect.py AMD --date 2026-09-18                     # 个股/ETF，35~37 通道
$VENV wb_analysis/collect_index.py --date 2026-09-18 --index NDX|SPX   # 指数专用
$VENV wb_analysis/_gen_derived_stock.py AMD 2026-09-18                 # 二级指标，分析前必跑，会落盘
$VENV wb_analysis/assemble.py --from-dir wb_analysis/drafts/<P>_<date> # 草稿目录须为嵌套结构
$VENV wb_analysis/_audit_gaps.py NDX <date>
$VENV wb_analysis/erp_context.py --start 1990-01-01 --append
```
- `_derive_stock.py` **只打印到 stdout、不落盘** ⇒ 用 `_gen_derived_stock.py <T> <date>` 包装落盘
  （产物 `evidence/<T>_<date>.derived.raw.txt` + `.derived.md`，含往返自校验）。

### ★ 交付前校验：只跑这一条
```bash
$VENV wb_analysis/_precheck.py wb_analysis/drafts/<P>_<date> \
    --evidence wb_analysis/evidence/<P>_<date>.md --report reports/<树>/
```
**7 项**：运行卫生 → 数据缺口台账 → 评级词/契约 → 口径一致性 → 数字溯源 → 时序新鲜度 → 报告树反读；输出 FAIL（阻断）/ WARN（过目）/ INFO。
- **判读规则已写进代码**：mtime 时序告警固定为 INFO（已知假阳性，判据应是内容比对）；需要阻断加 `--strict-freshness`。
- 单项工具可单独调用，但**别用它们的退出码做总体判断**（约定互不一致）。

### ★★ 先跑门禁自检

```bash
$VENV wb_analysis/_selftest.py      # 退出码 0 = 全过（双向夹具自检）
```
**没有自检的门禁只是更隐蔽的静默失败源** —— 门禁自己坏掉时的症状恰是「一切正常」。

### 退出码语义（不要凭直觉假设）

| 工具 | 退出码 |
|---|---|
| `_lint_drafts.py` | 0 无违规；**2 有契约违规（阻断）**；未溯源数字属顾问性，不阻断 |
| `_verify_ratings.py` | 0/1；必需 12 个角色文件，`0_*.md`/`_constraints.md` 缺只提示 |
| `_audit_values.py` / `_verify_report.py` | 0/1 |
| `_check_freshness.py` | 0 新鲜；1 有时序告警（**可能假阳性**） |

## 12 角色与契约

market / fundamentals / news / sentiment → bull ⇄ bear → manager → trader → aggressive ⇄ conservative ⇄ neutral → portfolio manager。
**依赖顺序不可破坏**（bear 逐条反驳 bull；trader 读 manager；3 风险读 trader；PM 读全部）。**可并行**：4 分析师之间、3 风险之间。

**评级词契约**：五档 `Buy`/`Overweight`/`Hold`/`Underweight`/`Sell`；交易员三档；情绪六档。
`extract_rating` 先找 `Rating: X` 标签，退化后扫描全文取**第一个**五档英文词。

---

## 铁律索引（全文见 `IRONLAWS.md` —— 只当索引用）

| # | 一句话判据 |
| 1 | **时点闸门**：期权链只在美东 09:30–16:00 刷新；判据＝**双边报价 ∩ 新鲜成交**（只看 lastTradeDate 会误判） |
| 2 | 三道闸门顺序不可颠倒：**时点 → 时间戳 → 数值** |
| 3 | **静默失败**：报成功+外观正常+读到合规文本；全绿≠完整，必须打开通道看 |
| 4 | **当日 bar 滞后 ⇒ 双口径**：指标 T−1、最新价/估值/spot 用 T；`PE×EPS≠close` 属正确 |
| 5 | 盘中快照与采集时点需求相反；波动率代理未走剔除闸门 |
| 6 | **汇总必须回原始样本重数**；分清「主体」与「顺带提及」；写「缺失」前先数总数 |
| 7 | 时序校验用**内容比对**（md5/diff），**不要信 mtime** |
| 8 | 结论块之外的裸五档英文词会**污染评级解析** |
| 9 | 空骨架陷阱 ⇒ 已由 `assemble.py::check_completeness()` 封堵（退出码 2） |
| 10 | **缺口三分类** A 上游未发布 / B 阈值误伤 / C 采集器 bug；设阈值先测三个数 |
| 11 | **聚合口径**：`Σ(市值/比率)` 的分母必须设合理区间，单只坏值能摧毁全表 |
| 12 | **25Δ 偏斜两个口径不可混用**；OI 不承担论证重量；IV 上界 120% |
| 13 | FRED 间歇中断；Reddit RSS 429；VIX 是前瞻 IV（不可线性换算） |
| 14 | **子智能体硬约束七条**（白名单/落盘/禁裸评级词/绝对价格/主动列反证/禁合规声明） |
| 15 | 本机工具链：无 `sort`；safe-delete 钩子；**`wc -m` 数的是字节**（长度用 `len()`） |
| 16 | **分项之和 ≠ 自写合计 ⇒ 分项被反向编造**；自相矛盾比偏差硬 |
| 17 | **cashtag 主体判定取「第一个」**；未打标签的消息不得赋方向计入多空比 |
| 18 | 同目录可能有 CRLF/LF 两种行尾 ⇒ 编辑前探测、编辑后回读 |
| 19 | 子智能体报「网络失败」可能是假失败 ⇒ **先验产物再决定重跑** |
| 20 | 审计工具必须有「文档描述 vs 真实污染」判别力；**豁免表改后双边必测** |
| 21 | **禁止 shell 重定向写含中文的文件**（追加却不变大即是报警） |
| 22 | **禁止在 shell/heredoc 里内联含反斜杠的正则**；「0 命中」不是通过 |
| 23 | **股数双口径**：`impliedSharesOutstanding` vs `sharesOutstanding` 可差 1.71 倍 |
| 24 | **短历史标的的伪指标**：窗口不足时数据源会编一个看着正常的数 ⇒ 先数 K 线根数 |
| 25 | **子智能体会编造数据**：判据是「能不能写出算式」，写不出即编造 |
| 26 | **快照字段间的序关系/恒等式校验**（单字段看着都合法） |
| 27 | **E 不可测量时仓位公式保持沉默**；「信息不足」推不出「零仓位」 |
| 28 | **阈值型质量门槛的盲区**：一次性税收收益同时顶高净利率与 ROE ⇒ 查利润来源 |
| 29 | `python -c "..."` 写含反引号文本会静默丢失 ⇒ 落盘 .py 再执行 |
| 30 | **财报要打到 SEC 原值**：slim 缓存只有 8 个标签；须锁期末日、处理现金流符号 |
| 31 | **目录 mtime 不可作时间锚点**；两段计划不可共享快照；备份须与清单逐项校验 |
| 32 | **缺数据不可怕、缺口没被下游看见才可怕**：台账化＋决定性缺口必须写进简报＋结论改条件式 |
| 33 | **代码搬家五条规程**：先校验后写盘 · 保缩进 · 表达式内不加注释 · `__file__` 上移 · 别用字节数当护栏 |
| 34 | **判「是否当日」一律用市场所在时区**（不用本机时区）；缓存文件名不得含 `start`/`end` |
| 35 | **判「某节正文是否为空」必须先剔 `Link:`/URL/围栏/分隔线**；「0 命中」是待验证不是通过 |
| 36 | 期权信号会被**采集时点**反向改写（跨时点不可比）；配额耗尽时**换模型档位**是合法维度 |
| 37 | **角色文件名 / 草稿目录结构 / JSON 大小写**三处契约常量必须下发前双源核对（零前缀、嵌套目录、`trader_action='Hold'`） |

## 契约与校验器的硬约束（**全文见 `IRONLAWS.md` 尾部**）

- `trader.md` = 首行 `**Reasoning**` + 末行 `FINAL TRANSACTION PROPOSAL: **HOLD**`（串全文恰 1 次）
- 五档英文词白名单 **6 席**：manager / portfolio_manager / trader / aggressive / conservative / neutral（**结论块外出现即阻断**）
- 「自我合规声明」会命中自己的正则；`_lint_drafts.py` 已知假阳性见代码内注释

## 用户偏好

中文报告（评级词保留英文）；**必须显式标注数据缺口，禁止臆测填充**；抵触额外付费 API；
偏好结构化表格与显式推理；**愿意以时间换质量**；关心的不只是单次结论，还有**方案的耐久性**。
`reports/` **2026-09-23 起按标的分子目录**（`<标的>/<标的>_<时间戳>/`），旧版/数据不全的**可清理**（用户已授权，但须先打包回滚包 + 逐文件清单）；`_datasets/` 放数据产品、`_other/` 放非 12 角色专题报告；**未经允许不擅自改动自动化**。
**「思考强度拉满 + 多 agent 并行 + 数据来源真实性不能缺」** ⇒ 证据包之外必须做**独立第三方核验**，
并把核验结果写进简报（逐条标注「已核验 / 同源不可独立核验 / 不可得」），不要只说「N/N 全绿」。
**不看重流水式记忆**：**已被代码/门禁固化的结论不必抄进铁律**。
