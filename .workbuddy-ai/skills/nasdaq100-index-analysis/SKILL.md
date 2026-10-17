---
name: nasdaq100-index-analysis
description: 为纳斯达克 100 指数（^NDX / QQQ）**或任一美股个股**跑完整的 12 角色分析流水线并渲染报告树。当用户要求分析纳指 100、NDX、QQQ 指数本身，或要求分析某只美股（如 GOOG / NVDA / AMD）、重跑/刷新已有报告时使用。覆盖证据采集、派生指标、统一简报、12 角色编排、草稿防伪校验、渲染与反读校验的全流程，并内置采集器的已知陷阱与「子智能体编造数据」的处置方法。
agent_created: true
---

# 纳斯达克 100 指数 / 美股个股 12 角色分析流水线

**适用**：两个指数（^NDX / ^GSPC）与个股。三者**共用同一套 12 角色框架与渲染/校验流程，只有采集器与派生脚本不同**：

| 标的类型 | 采集器 | 派生指标 |
|---|---|---|
| 纳指100（NDX） | `wb_analysis/collect_index.py --index NDX --date <D> --top-insiders 12` | `wb_analysis/_derive_ndx.py <D> --index NDX` |
| 标普500（SPX） | `wb_analysis/collect_index.py --index SPX --date <D> --top-insiders 12` | `wb_analysis/_derive_ndx.py <D> --index SPX` |
| 个股 | `wb_analysis/collect.py <TICKERS> --date <D>` | `wb_analysis/_derive_stock.py <T> <D>` |

> `--index` 默认 `NDX`，故原有 NDX 调用方式完全不变。
> **两个指数的实质差异**（成分池 / 去重 / 集中度 / 分红率）见 `.workbuddy-ai/memory/DOMAINS.md` → 「NDX vs SPX 不可串」。
> ⚠️ `get_latest_sp500()` 若回退到 99 只精选核心，**报告中必须声明** —— 否则广度与集中度结论严重失真。

**个股路径的额外注意点**：
- **财务报表**：`_compact_statement` 按优先级抽取关键行 —— 数据源 CSV 的**行序与重要性无关**，
  盲截会丢掉 Total Revenue / Total Assets。
- **快照口径混乱是常态**：TTM 与年报口径混在一起（常见「PE(TTM) 被非经常性收益抬高」），
  采集器生成的 `_fundamentals_sanity` 会把矛盾写进证据包 ⇒ **必须在报告中三口径并列**。
- **比率类字段先做「序关系 / 恒等式」检验**，再做数值区间检验（判据见 MEMORY 铁律 26）。
- **个股采集器含期权通道**（2026-09-17 起，勿再按旧版口径声明缺口）：产出
  §11 期权市场内部结构（标的自身期权链）/ §12 波动率与债券代理 / §13 最新交易日实时收盘补充，
  健康度基数 **35/35**。指数用 QQQ 代理，两者渲染函数不共用是**有意为之**。
- **双股份类别**：GOOG（Class C）与 GOOGL（Class A）经济利益相同、共享财报，分析其一即可，
  但应在报告中说明类别差异（投票权、价差、流动性）。

## 前置检查（每次必做）

1. 确认隔离环境存在：`D:\Antigravity\TradingAgents\.venv\Scripts\python.exe`
2. **确认采集时点**：北京 04:00–21:30（= 美东盘前/盘中）采集时，末根 K 线是**未完成 bar**，报告中必须声明。
   判据：**末根 K 线量 ÷ 20 日均量** —— 显著低于 100% 即未收盘。
3. 确认 `.env` 有 `FRED_API_KEY`（否则 5 项宏观通道全失败）。

## 执行步骤

### 第 1 步：采集证据（约 60~150 秒）

```bash
cd D:/Antigravity/TradingAgents
./.venv/Scripts/python.exe wb_analysis/collect_index.py --date <YYYY-MM-DD> --top-insiders 12
```

产出 `wb_analysis/evidence/NDX_<date>.md` 与 `.json`。

**必须核对通道健康度**，期望 **31/32**：
- `etf:option_iv` 在无报价时段（盘前/盘后）显示 `unavailable` —— **这是正确行为**，不是故障。
  此时**禁止在任何结论中使用期权 IV 或偏斜**。
- `breadth` 覆盖率低于 ~95% ⇒ `_download_close_chunked` 的重试仍失败，考虑再跑一次。

### 第 2 步：派生指标（几秒）

```bash
./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py <YYYY-MM-DD>               # NDX（默认）
./.venv/Scripts/python.exe wb_analysis/_derive_ndx.py <YYYY-MM-DD> --index SPX   # SPX
```

输出均线偏离、布林带内位置与带宽、均线斜率、MACD/RSI 路径、ERP 及其历史分位、广度背离、集中度差额。
**落盘为草稿目录的 `0_derived.md`**，让 12 个角色共用同一份口径。

#### ★★★ 顺序铁律：证据 → 派生 → 简报，一步都不能跳

**凡重新采集过证据包，必须立刻重跑本步，再写简报。**
`_derive_ndx.py` 每次都重读证据包，**重跑就正确** —— 错在「该重跑的步骤被跳过且毫无提示」，
曾导致一整代陈旧数字（Forward PE、站上 50SMA 覆盖率等）扩散到 12 个角色共 270+ 处。

```bash
./.venv/Scripts/python.exe wb_analysis/_check_freshness.py wb_analysis/drafts/<PREFIX>_<date>
```
断言链条单调性：**证据包 ≤ 派生指标 ≤ 统一简报 ≤ 全部角色文件**，退出码非 0 即存在陈旧环节。

> **分工**：本节管「**证据**变了，派生与简报没重跑」；下一节管「**简报**变了，下游角色没重跑」。
> 两者是同一类错误的两端，都要查。

### 第 3 步：写统一简报 `0_brief.md`

整条流水线的**唯一事实来源**，必须包含：

§0 时点与事件窗（北京时间/美东时间、美股开盘、关键事件倒计时）·
价格与技术（收盘价、全部指标最新值及现价相对位置、布林带内位置与带宽、MACD/RSI 路径）·
估值与 ERP（含历史分位与「负 ERP 是常态」的校正）·
市场广度（含**指数 vs 中位成分股**的 20 日/60 日背离）·
成分结构与集中度（官方口径 vs 纯市值口径）· 内部人聚合 ·
新闻（严格分「已实现事实 / 宏观传导 / 未经证实的传言」三类）· 社媒情绪 + 预测市场 ·
宏观（FRED 各序列及各自的最新日期）· **数据缺口清单（逐条）** · 输出契约。

### 第 4 步：12 角色编排

```
批 A（4 并行）：market / fundamentals / news / sentiment → 1_analysts/
批 B：bull                                              → 2_research/
批 C：bear（须逐条反驳 bull，故必须在 bull 之后）        → 2_research/
批 D：研究经理 → manager.md                              → 2_research/
批 E：交易员   → trader.md                               → 3_trading/
批 F（3 并行）：aggressive / conservative / neutral      → 4_risk/
批 G：组合经理 → portfolio_manager.md                    → 4_risk/
```

**每个子智能体的提示词必须含以下约束，缺一即出错**（完整 7 条见 MEMORY 铁律 14）：
① 只准读 `0_brief.md` + `0_derived.md` + 证据包 + `FRAMEWORK.md`，
　**严禁引用其他报告、外部记忆或印象中的数据，禁止上网检索**；
② 明确产出文件路径、用 Write 落盘、**不回吐全文**；
③ **正文禁裸的英文评级词**（Buy/Overweight/Hold/Underweight/Sell）—— 上游 `extract_rating` 取全文**第一个**五档词；
④ 交易员的**入场价与止损必须是绝对价格数字**，不得写百分比或区间；
⑤ **必须主动列出对自己结论不利的证据**，否则报告退化成单向宣传。

**从源文件核对下发参数。** 曾把交易员的「首仓 ≤2.5%、总敞口 ≤5%」误写成「5% / 15–20%」下发 ——
虽然子智能体回溯原文自行纠正，但不该发生。

### ★★★ 重跑前必须校验「简报定稿时间」—— 用内容比对，不要信 mtime

`0_brief.md` 一旦修订（补缺口、改口径、推翻某节结论），**所有早于它的角色文件全部作废**，
必须按 A→B→…→G 的依赖顺序**整链重跑，不能只重跑其中几个** ——
跳着重跑会得到「用新事实论证旧结论」的缝合怪。
**典型症状**：同一文件里并存两种互斥口径（如「期权整体不可用」与「无报价时段」）。

**⛔ 不要用 mtime 判定**：mtime 会被读取、复制等操作意外刷新。曾出现
`bear.md` / `bull.md` / `trader.md` 的 mtime 看似晚于简报，而 **md5 与归档旧稿逐字节相同**
⇒ B~G 七个批次其实从未重跑，基于 mtime 的判定给出了相反结论。

**✅ 正确做法：与归档旧稿做 md5 逐字节比对**

```bash
./.venv/Scripts/python.exe - <<'PY'
import hashlib, pathlib
root = pathlib.Path('wb_analysis/drafts/NDX_<date>'); arch = root/'_stale_pre_brief_fix'
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
for f in sorted(arch.rglob('*.md')):          # 归档名形如 2_research__bear.md
    sub, _, base = f.stem.partition('__'); cur = root/sub/(base+'.md')
    print(('✗ 未重跑（与归档相同）' if cur.exists() and md5(f)==md5(cur) else '✓ 已重跑'), f.name)
PY
```
凡出现 `✗ 未重跑`，该文件及其**所有下游**都必须重跑。
**若归档目录不存在**，说明还没归档过旧稿 —— 先把当前在用的旧稿归档到 `_stale_pre_brief_fix/` 再改。

**★ 第二件必查的事：内容层面的作废数值**（比 mtime 更能说明问题）。
把本轮作废的具体数值列成黑名单，在草稿目录检索是否仍被引用。
⚠️ **注意误报** —— 修正后的文件会**主动声明「严禁引用 XXX」**，这类合规声明本身会命中扫描，
**必须逐条看上下文**，区分「引用」与「禁令」。

### 第 5 步：越界内容清洗（**必做，容易漏**）

```bash
./.venv/Scripts/python.exe - <<'PY'
import re, pathlib
root = pathlib.Path('wb_analysis/drafts/NDX_<date>')
pat = re.compile(r'(?<![A-Za-z])(Buy|Overweight|Underweight|Sell|Hold|BUY|OVERWEIGHT|UNDERWEIGHT|SELL|HOLD)(?![A-Za-z])')
for p in sorted(root.rglob('*.md')):
    if p.name.startswith('0_'): continue
    lines = p.read_text(encoding='utf-8').splitlines()
    print(p.name, '评级词', [(i,l.strip()[:70]) for i,l in enumerate(lines,1) if pat.search(l)])
    print('  FINAL 行', [i for i,l in enumerate(lines,1) if 'FINAL TRANSACTION PROPOSAL' in l])
PY
```

**bull / bear / fundamentals / portfolio_manager 四个角色都会自作主张补上
`FINAL TRANSACTION PROPOSAL: **X**`** —— 那是交易员独有的契约（bear 会写 SELL、bull 会写 BUY），
会让下游 grep 读到矛盾信号。**必须删掉，只保留 `3_trading/trader.md` 里的。**
同时把正文里的裸英文评级词改成中文。

**★★ 结论块之后也不得再出现裸评级词**：`manager.md` / `portfolio_manager.md` **允许**在
**文首结论块**出现评级词，所以上面的扫描会放过它们 —— 但结论块**之后**再出现仍属契约违规
（实测两处：`manager.md` 的「弱项：Hold 在…情形下可能是回避」、`portfolio_manager.md` 的「Rating = Hold。」）。

**⇒ 交付前逐文件跑一次评级解析复核，确认「首个五档词」恰好就是结论块那一处：**

```bash
./.venv/Scripts/python.exe - <<'PY'
import pathlib, re
RAT = r'\b(Buy|Overweight|Hold|Underweight|Sell)\b'
root = pathlib.Path('wb_analysis/drafts/NDX_<date>')
for p in sorted(root.rglob('*.md')):
    if p.name.startswith('_') or '_stale' in str(p): continue
    hits = ['%d:%s' % (i, m.group(1)) for i, l in
            enumerate(p.read_text(encoding='utf-8').splitlines(), 1) for m in re.finditer(RAT, l)]
    print('%-24s 首词=%-12s 全部=%s' % (p.name, hits[0].split(':')[1] if hits else '(无)', ','.join(hits[:5])))
PY
```
**期望结果**：4 位分析师 + bull + bear + conservative + neutral **全部 `(无)`**；
`manager.md` / `trader.md` / `portfolio_manager.md` **首词即结论块**（行号 1 / 10 / 10）。

### 第 5.5 步：交付前统一门禁（**必做，渲染前最后一道**）

```bash
./.venv/Scripts/python.exe wb_analysis/_precheck.py \
    wb_analysis/drafts/NDX_<date> \
    --evidence wb_analysis/evidence/NDX_<date>.md \
    --report reports/NDX_<stamp>          # 交付后连报告树一起反读
```

一次跑完**评级词/契约字段 → 口径一致性 → 数字溯源 → 时序新鲜度 → 报告树反读**。
分级判读规则**写死在代码里**，不再靠人记：

| 级别 | 含义 | 覆盖检查 |
|---|---|---|
| **FAIL**（阻断交付） | 必须修正后重跑 | 评级词/契约字段、口径一致性、契约违规、报告树反读 |
| **WARN**（不阻断） | 需人工过目 | 未溯源数字（派生量属正常；**凭空出现的绝对金额才是编造信号**）|
| **INFO**（固定提示） | **永不阻断** | mtime 时序告警 —— **已知假阳性**（简报加一条纯增补的注释也会触发）；判据应是内容比对；需要它阻断时加 `--strict-freshness` |

**为什么要有这一步**：校验原先分散在 6 个脚本里，各有各的参数与**互不一致的退出码约定**，
「跑完检查」本身成了**不可复现的手工仪式** —— 顺序靠记、判读靠眼、漏一步就漏一类缺陷。

#### ★★ 交付前先跑门禁自检（防止门禁本身被改坏）

```bash
./.venv/Scripts/python.exe wb_analysis/_selftest.py     # 退出码 0 = 全过
```
用**合成夹具**（临时目录现造，不依赖真实草稿）双向验证每个检测器：
**坏夹具必被检出、好夹具必不误报**，并含一条 **cwd 无关性**断言。
**门禁自己坏掉时的症状恰恰也是「一切正常」** —— 没有自检的门禁，只是一个更隐蔽的静默失败源。

#### 单项工具（可单独调用，但**别用它们的退出码做总体判断**）
`_lint_drafts.py`（0 无违规 / **2 有契约违规**）· `_verify_ratings.py`（0/1；必需的是 12 个角色文件，
`0_*.md` 与 `_constraints.md` 属工作文档，缺失只提示）· `_audit_values.py`（0/1）·
`_check_freshness.py`（0/1，**可能假阳性**）· `_verify_report.py`（0/1）。

`_audit_values.py` 查三项：① 旧值黑名单零残留 ② **分项求和自洽**（抓「反向编造」）③ 新值已就位。
**为什么必做**：草稿一旦带旧值渲染出去，报告看起来**完全正常**
（数字合法、格式合规、评级解析成功），**没有任何机制会报警**。

⚠️ **默认跳过**：归档子目录（`--exclude` 为子串匹配，已含 `_stale` / `_archive`）、
工作文档（`_constraints.md` —— 它必须逐字写出五个英文词才能定义评级词汇表）、
**子版目录**（`scripts/`、`skills/` 下的模板等，常含**示例性的旧数值**）。

### 第 6 步：写 `meta.json` 并渲染

```json
{"ticker":"NDX","as_of":"<date>",
 "ratings":{"research_manager":"...","trader_action":"...","portfolio_manager":"..."},
 "notes":"【适用范围】【数据源健康度】【口径提示若干】【数据缺口清单】【最大限制】"}
```
`notes` 会作为「## 附：数据缺口与说明」追加到 `complete_report.md` 末尾。

```bash
./.venv/Scripts/python.exe wb_analysis/assemble.py --from-dir wb_analysis/drafts/NDX_<date>
```

**务必用 `--from-dir`。** 直接用 `NDX` 会命中 `wb_analysis/analysis/` 下的**空骨架 JSON**
（评级预填 Hold、正文全空），渲染出一份假报告。
**★ 已加装硬门禁**：`assemble.py` 检查 12 个必需小节是否全部非空，
**任一为空即拒绝渲染并返回退出码 2**，同时打印三条正解（用 `--from-dir` / 回写真实 JSON / `--allow-incomplete`）。
⇒ 若看到 `[OK] 报告树已生成` 但 `complete_report.md` 只有几百字节，**立即怀疑命中了空骨架**。

**★ 更好的做法：把真实分析回写成契约 JSON，从根上消除空骨架陷阱**：
渲染通过后，把草稿目录的 12 个 `.md` + `meta.json` 组装成 `wb_analysis/analysis/<T>_<date>.json`
（键：`ticker` / `as_of` / `ratings` / `analysts{market,sentiment,news,fundamentals}` /
`research{bull,bear,manager}` / `trading{trader}` /
`risk{aggressive,conservative,neutral,portfolio_manager}` / `notes`；
用 `json.dumps(data, ensure_ascii=False, indent=2)` 写出）。
这样 `--from-dir` 与 `<TICKER> --date` **两条入口都可用**，且不会有人误命中空骨架。

**★ 二次渲染用同一个 `--stamp` 覆盖**（从树目录名取），就地覆盖同一棵树；
否则 `reports/` 会留下「修正前 / 修正后」两份同名报告，易误读。

### 第 7 步：渲染后反读校验（`assemble` 的「契约校验通过」只覆盖格式）

```bash
./.venv/Scripts/python.exe wb_analysis/_verify_report.py reports/<TREE>
```
用**上游** `extract_rating` 重新读产物（manager / decision / 交易员末行）+ 文件完整性 +
`complete_report` 是否含「附：数据缺口与说明」。

**为什么必须单独做**：`assemble.py` 打印的「契约校验通过」比较的是**它自己声明的评级**与
**它自己渲染的内容**，属自洽检查，**不能替代**「把产物交回上游解析器读一遍」。

**三处评级必须与 `meta.json` 的声明一致**，且交易员末行必须是 `FINAL TRANSACTION PROPOSAL: **X**`。

---

## 陷阱与口径 → 一律看 `MEMORY.md` / `DOMAINS.md`，本文件不重复

本 skill 只管**怎么做**（步骤、命令、顺序、检查点）。
**该记住什么**（口径、判据、阈值、陷阱）在 `.workbuddy-ai/memory/IRONLAWS.md`（铁律 1–51 全文 + 索引）与
`.workbuddy-ai/memory/MEMORY.md`（每次都要遵守的硬约束）与
`DOMAINS.md`（按标的 / 子系统查阅）。**不在本文件重复** —— 两处各写一遍的结果是两边会漂移，
而漂移的工具比没有工具更危险。

**按症状查：**

| 症状 | 去哪儿 |
|---|---|
| 期权报价有 bid/ask 但全是上季度的；IV 出现 150%~250% | MEMORY 铁律 1、2、5 |
| 健康度报「全绿」但某通道其实是空的；§3 整节为空 | 铁律 3 |
| 估值快照被扣留成一段「Profile … withheld」声明 | 铁律 3 |
| StockTwits 恒为 `unavailable: HTTPError` | 铁律 3 |
| 技术指标比价格晚一个交易日；`PE×EPS ≠ latest_close` | 铁律 4 |
| 社媒多空比与直觉相反 | 铁律 6、17 |
| 下游文件集体引用同一组不存在的数 | 铁律 7 |
| 结论块之后又出现裸五档英文词 | 铁律 8 |
| 缺数据要先分类再写「缺失」 | 铁律 10 |
| 聚合 PB / ROE 明显离谱 | 铁律 11 |
| 25Δ 偏斜两个数值对不上 | 铁律 12 |
| FRED 的 VIXCLS / DGS10 只到昨天 | 铁律 13 |
| 子智能体越界补 PROPOSAL / 报失败但产物完整 | 铁律 14、19 |
| 分项加起来**不等于**自己写的合计 | 铁律 16 |
| 编辑 md 回报「成功」但内容没变 | 铁律 18 |
| 写中文进 md 后内容错乱 / 丢字节 | 铁律 21 |
| 检测脚本报「0 命中」但目标明明存在 | 铁律 22 |
| 某个比率字段离谱（营业利润率高于毛利率…）| 铁律 26 |
| 新标的通道数明显偏少（非美股）| DOMAINS → 非美国上市标的 |
| 期权面 / 入场方向 / 仓位公式的裁定 | DOMAINS → 通用分析手法 |

**已由代码封堵、无需人工注意的**（不要再当成「要小心的事」）：
空骨架渲染（`assemble.py` 硬门禁）、`_lint_drafts.py` 退出码、两处五档词白名单不一致、
evidence 相对路径依赖 —— 均已由 `_precheck.py` / `_selftest.py` 兜住。

**改动本 skill 的步骤或任何校验脚本后，先跑 `_selftest.py` 确认门禁仍工作。**

---

## 必须写进报告的数据缺口（本指数的固有缺口）

1. 期权 IV 与偏斜在无报价时段不可用 → 尾部保护成本维度缺失
2. 期权 OI 口径不稳（曾观测同一到期日 CallOI 8 分钟内变 4.5 倍）
3. VIX 与 DGS10 的 FRED 序列通常滞后一日
4. StockTwits 有标签样本常不足 10 条、Reddit 无热度量化 → 情绪置信度不得为 high
5. 加权增速被极端值放大（营收约 3x、盈利约 5x 于中位数）→ 不可外推
6. 成分股池是静态快照，非官方实时成分
7. 纳指 100 前瞻 PE 历史不可重建 → ERP 分位用标普 500 代理
8. 内部人为计划性申报汇总，卖买比不能读作管理层看空
