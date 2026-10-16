# TradingAgents 项目长期记忆

> 本文件只存**每次都要遵守的**：架构 / 命令 / 12 角色契约 / **铁律单行索引** / 校验器硬约束 / 用户偏好。
> ★★ **开工第一件事：完整读 `.workbuddy/memory/IRONLAWS.md`（铁律 1–48 全文）** —— 索引会丢细节，**只照索引办事而没读全文 = 没读**。
> 备份：`_backup/`（`ls` 看全部，带日期后缀）。

## 记忆与文档体例（改任何文件前先读）

**同一口径只在「该放它的那个文件」写一遍** —— 写两遍必然漂移，**漂移的工具比没有工具更危险**。

| 文件 | 放什么 | 何时读 |
|---|---|---|
| `MEMORY.md`（本文件） | 索引 + 每次都要遵守的硬约束 | 自动注入 |
| **`IRONLAWS.md`** | **全部铁律全文**（判据 / 阈值 / 陷阱） | **开工先读** |
| `DOMAINS.md` | 按标的·子系统（指数聚合 / ERP / 黄金 / 非美股 / 量化选股 / A股） | 碰到该领域时读 |
| `docs/WORKFLOW.md` / `docs/SCREENER.md` | 运行手册（不收设计论证） | 操作前读 |
| `FRAMEWORK.md` | 12 角色输出契约（子智能体读它） | 下发角色时 |
| `docs/PROJECT_MAP.md` | **项目地图（第一入口）** | 看不懂结构时 |
| `README.md` / `CHANGELOG.md` | 上游归属+架构一句话 / 版本索引（一行一版） | — |
| `YYYY-MM-DD.md` | 当日流水。**归档到 `_backup/` 即止，不提炼** | — |

⚠️ 宿主按**字节**截断本文件 ⇒ 由 `scripts/_health.py`「记忆体积」门禁守住（≤14200 PASS）。
**两条原则**：① 能靠代码根除的写进代码（`_precheck.py`/`_selftest.py`），不靠「记得注意」；② 改未被 git 跟踪的文档（`docs/**`、`.workbuddy/**`）前**必须先备份**。

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
- ★ **产物封存** `wb_analysis/_seal_run.py`（`--plan`/`--all --apply`/`--unseal`/`--orphans`）⇒ 一轮产物 = 树内 `_source.zip`+`SOURCE_MANIFEST.json`
  ⇒ `{evidence,drafts,analysis}` 与 `_oneoff/` **空是正常态**；删前必校验，不通过即中止
- ★ **共享缓存** `wb_analysis/_cache/`（ERP 序列、黄金面板等，**不属于任何一轮**，勿放 evidence/）
- ★ **回滚包保留＝按前缀各留 N 个**（不能全局取最新）；`scripts/_prune_backup.py` 清理；**宣布"备份不完整"前先查回收站**
- ★ **数据缺口台账**：`wb_analysis/_gap_ledger.py <T> <date> [--check <草稿目录>]`
  · 每轮产出 `evidence/<T>_<date>.gaps.json`（登记 `cls` A/B/C/S · `decisive` · `blocks` · `remedy` · `fallback`）
  · **决定性缺口未写进 `0_brief.md` ⇒ 门禁 FAIL**（`_precheck.py` 第 2 项）；**新通道须登记进 `RULES` 表**（键名＝通道名，非语义名）
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
$VENV wb_analysis/collect.py AMD --date 2026-09-18                     # 个股/ETF，35~37 通道
$VENV wb_analysis/collect_index.py --date 2026-09-18 --index NDX|SPX   # 指数专用
$VENV wb_analysis/_gen_derived_stock.py AMD 2026-09-18                 # 二级指标，分析前必跑，会落盘
$VENV wb_analysis/_gen_meta.py <P>_<date>                              # ★ 渲染前必跑！否则 as_of/ratings 静默为空
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

## 铁律索引（全文见 `IRONLAWS.md`，只当索引用）

| # | 一句话判据 |
|---|---|
| 1 | **时点闸门**：期权链只在美东 09:30–16:00 刷新；判据＝双边报价 ∩ 新鲜成交 |
| 2 | 三道闸门顺序：**时点 → 时间戳 → 数值** |
| 3 | **静默失败**：报成功+外观正常≠完整，须打开通道看真实数据 |
| 4 | **当日 bar 滞后 ⇒ 双口径**：指标 T−1、最新价/spot 用 T |
| 5 | 盘中快照与采集时点需求相反；波动率代理未走剔除闸门 |
| 6 | **汇总须回原始样本重数**；分清「主体」与「顺带提及」 |
| 7 | 时序校验用内容比对（md5/diff），不要信 mtime |
| 8 | 结论块之外的裸五档英文词会污染评级解析 |
| 9 | 空骨架已由 assemble.py::check_completeness() 封堵（退出码 2） |
| 10 | **缺口三分类** A 上游未发布 / B 阈值误伤 / C 采集器 bug |
| 11 | **聚合口径**：Σ(市值/比率) 分母设合理区间，单只坏值能摧毁全表 |
| 12 | **25Δ 偏斜两个口径不可混用**；OI 不承担论证重量；IV 上界 120% |
| 13 | FRED 间歇中断；Reddit RSS 429；VIX 是前瞻 IV（不可线性换算） |
| 14 | **子智能体硬约束七条**（白名单/落盘/禁裸评级词/绝对价格/列反证/禁合规声明） |
| 15 | 本机工具链：无 sort；safe-delete 钩子；wc -m 数的是字节 |
| 16 | **分项之和 ≠ 自写合计 ⇒ 分项被反向编造**；自相矛盾比偏差硬 |
| 17 | **cashtag 主体判定取第一个**；未打标签消息不得赋方向计入多空比 |
| 18 | 同目录可能混 CRLF/LF ⇒ 编辑前探测、编辑后回读 |
| 19 | 子智能体报「网络失败」可能是假失败 ⇒ 先验产物再决定重跑 |
| 20 | 审计工具须有判别力；豁免表改后双边必测 |
| 21 | 禁止 shell 重定向写含中文的文件 |
| 22 | 禁止在 shell/heredoc 里内联含反斜杠的正则 |
| 23 | **股数双口径**：impliedSharesOutstanding vs sharesOutstanding |
| 24 | **短历史标的伪指标**：窗口不足时会编造 ⇒ 先数 K 线根数 |
| 25 | **子智能体会编造数据**：判据是能否写出算式，写不出即编造 |
| 26 | 快照字段间的序关系/恒等式校验 |
| 27 | E 不可测量时仓位公式保持沉默；信息不足≠零仓位 |
| 28 | **阈值型质量门槛盲区**：一次性税收收益顶高净利率与 ROE ⇒ 查利润来源 |
| 29 | python -c 写反引号会静默丢失 ⇒ 落盘 .py 执行 |
| 30 | **财报打到 SEC 原值**：slim 缓存仅 8 标签；锁期末日、处理现金流符号 |
| 31 | 目录 mtime 不作时间锚点；两段计划不共享快照；备份逐项校验 |
| 32 | 台账化＋决定性缺口写进简报＋结论改条件式 |
| 34 | 判当日用市场所在时区；缓存文件名不得含 start/end |
| 35 | 判正文为空先剔 Link/URL/分隔线；双小节空警惕上游降级 |
| 36 | 期权信号受采集时点改写；配额耗尽换模型档位 |
| 37 | 角色文件名/草稿目录结构/JSON 大小写下发前双源核对 |
| 38 | get_point_in_time 的 *_ttm 是伪 TTM：须反推能否拼成完整财年 |
| 39 | 判人为拼接抓精确相等；\\b 在 CJK 边界不可靠 |
| 40 | **未实现公允价值重估**打低报表 PE；须用 TTM 聚合 |
| 41 | **空内容≠抛异常** ⇒ 假绿。空态串登记进 _PLACEHOLDER_MARKERS |
| 42 | **已验证/精确勾稽等断言不可跨报告直接引用，必须自行复算** |
| 43 | **业务出售/非常规利得粉饰（Q5 闸门升级）**：业务出售与非常规利得须剔除；非经营利得≥20% 触发 FAIL，重算正常化 PE |
| 44 | **派生指标底层机算硬绑定，杜绝心算与盘中残留**：均线偏离、布林真实位置、量比一律由 _derive_stock.py 机算 |
| 45 | **背离判定严防多头偏见与伪底背离**：价格创低且 RSI 走低属顺势空头下挫，严禁误标看涨底背离 |
| 46 | **财报日历跳空风险与真实盈亏比下限**：财报日前 10 天跳空穿透止损；第一目标盈亏比 < 2:1 禁左侧买入，强制 Hold |
| 47 | **流水线中途禁跑 `pytest`**：teardown 清空 `evidence/`+`drafts/`；落盘后必自验 `EXISTS`+`len()` |
| 48 | **`safe-delete` bulk 50 条/轮会中止工具收尾**：判据＝stderr 有 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` |

**★ 拿到异常低 PE，先查来源四件套**（铁律 28 + 40 + 43）：① 税项是否为负且占净利比例大；② `Other income` / 证券投资有无大额公允价值变动；③ **有无业务出售或分立重组利得（`Gain On Sale Of Business` / `Total Unusual Items`）**；④ 经营利润率 vs 净利率倒挂。**四项都清白，低 PE 才是真的低。**

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
