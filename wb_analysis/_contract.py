# lifecycle: reusable
# created: 2026-10-08
# usage: from wb_analysis._contract import ...   （库；被门禁们 import，不单独运行）
"""12 角色输出契约的**唯一常量来源** —— 评级词、档位、白名单、正则全在这里定义一次。

## 为什么必须有这个文件（2026-10-08 血泪）

在它出现之前，**同一个契约被 8 个文件各自定义了一遍**：

| 文件 | 之前的定义 | 大小写容忍 |
|---|---|---|
| `_lint_drafts.py`   | 五档 + 大写变体 | Buy/Hold/… + BUY/HOLD/… |
| `_verify_ratings.py`| 五档（Title Case） | 仅 Buy/Hold/… |
| `_check_role_files.py` | 五档 + 独立的大写三档 | 分裂为两套 |
| `_gen_meta.py`      | 五档（Title Case） | 仅 Buy/Hold/… |
| `_strip_stray_ratings.py` | 五档（Title Case） | 仅 Buy/Hold/… |
| `_audit_values.py`  | （另有一处） | — |

**后果已经真实发生过**：因为 `_gen_meta.py` 的正则大小写敏感、而 `_lint_drafts.py` 的含大写，
同一个 `trader.md` 在两道门禁里被判定成**不同事实** ——
`**Action**: SELL` 过得了 `_lint_drafts` 却过不了 `_gen_meta`；
改成 `Sell` 后 `_check_role_files` 又开始报「档位词过多」。
**两道门禁互相打架，只能靠人来回试到收敛。** 这与本项目已经总结出的原则正相反：

    ★ 能靠代码根除的写进代码，不靠「记得注意」。

所以：**任何脚本要判评级词，都必须 import 本模块**，不许再自己写正则。
`_selftest.py` 有一条断言（"契约常量唯一来源"）会**遍历这些文件、确认它们没有另行定义**，
从而把「下一个人又手写一遍正则」这条路堵死。

## 契约速查（与 `FRAMEWORK.md` §Ⅲ 一致）

- **五档**（研究经理 / 组合经理 / 交易员的 `**Action**` / 三个风控席位）：
  `Buy` `Overweight` `Hold` `Underweight` `Sell`
- **交易员末行**：`FINAL TRANSACTION PROPOSAL: **SELL**`（**大写**，恰 1 次，且在末行）
- **情绪六档**：`Bullish` `Mildly Bullish` `Neutral` `Mixed`
  `Mildly Bearish` `Bearish`（sentiment.md 的结构化头部用）
  ⇒ ⚠️ **以 `tradingagents/agents/schemas.py::SentimentBand` 为准**（与 `FRAMEWORK.md` §六档逐字一致）。
- ⚠️ trader.md 的**结论块首行是 `**Action**: Sell`（Title Case）**，
  而**末行是 `**SELL**`（大写）** —— 同一个文件里大小写相反，这是契约本身，不是笔误。
"""

from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────────
# 1. 词汇表
# ─────────────────────────────────────────────────────────────────────────────

#: 五档评级（Title Case 为准；解析器同时容忍全大写形式）
FIVE_LEVELS: tuple[str, ...] = ("Buy", "Overweight", "Hold", "Underweight", "Sell")

#: 交易员三档（`**Action**:` 与末行 PROPOSAL 用）
THREE_LEVELS: tuple[str, ...] = ("Buy", "Hold", "Sell")

#: 情绪六档（`sentiment.md` 结构化头部）。
#: ★ 2026-10-10 修正：此前这里写的是 **7 档**（`Very Bullish` / `Somewhat Bullish` / …），
#:   与**上游 `tradingagents/agents/schemas.py::SentimentBand`、`FRAMEWORK.md` §六档、
#:   以及归档报告的实际取值**（NVDA 轮实测 `Mildly Bullish`）**全部不符** —— 属遗留草稿用词。
#:   该常量**无任何消费方**（全仓仅此处定义 + `__all__` 列出），故对齐到权威 6 档，消除漂移。
SENTIMENT_LEVELS: tuple[str, ...] = (
    "Bullish", "Mildly Bullish", "Neutral", "Mixed", "Mildly Bearish", "Bearish",
)

#: 交易员的契约行前缀（末行，恰 1 次）
FINAL_PROPOSAL = "FINAL TRANSACTION PROPOSAL"

# ─────────────────────────────────────────────────────────────────────────────
# 2. 正则（唯一来源 —— 别处不许再写）
# ─────────────────────────────────────────────────────────────────────────────


def _alt(words: tuple[str, ...]) -> str:
    """把词表拼成正则候选串，**长词优先**避免 `Buy` 抢先匹配 `Buyback` 一类前缀。"""
    return "|".join(sorted(words, key=len, reverse=True))


#: 五档词 —— 大小写不敏感（同时命中 `Buy` 与 `BUY`）。
#: 用 `(?<![A-Za-z])` / `(?![A-Za-z])` 做词边界，而不是 `\b`：
#: `\b` 在 `Overweight/Sell` 这种含非字母分隔的串上行为与直觉一致，但
#: `(?<!...)` 写法更严格，且对 `**SELL**` 与 `SELL，` 都成立。
FIVE_RE = re.compile(
    rf"(?<![A-Za-z])({_alt(FIVE_LEVELS)})(?![A-Za-z])", re.IGNORECASE
)
#: 五档词 —— **仅 Title Case**（用于「必须逐字写对大小写」的场合，如 `**Action**: Sell`）
FIVE_TITLE_RE = re.compile(rf"(?<![A-Za-z])({_alt(FIVE_LEVELS)})(?![A-Za-z])")
#: 交易员末行的**大写**三档：`**HOLD**`
THREE_BOLD_UPPER_RE = re.compile(r"\*\*(BUY|HOLD|SELL)\*\*")
#: 交易员末行整体：`FINAL TRANSACTION PROPOSAL: **SELL**`
#: ⚠️ 抓 `(\w+)`（宽松）：用于**读取**取值（`_reports_index` 抽 trader_action 时不在乎是否三档）。
PROPOSAL_RE = re.compile(rf"{FINAL_PROPOSAL}:\s*\*\*(\w+)\*\*")

#: 交易员末行整体 —— **严格版**：末行必须恰好是 `**BUY|HOLD|SELL**`（大小写不敏感）。
#: ⚠️ 两条正则**语义不同、不可互换**（2026-10-10 收敛）：
#:   · 宽松版抓 `(\w+)` ⇒ `**Foo**` 也能匹配，用于**取值**；
#:   · 严格版限定三档 ⇒ `**Foo**` 判为不合契约，用于**校验**（`assemble`/`_verify_report`）。
#: 此前这两条正则分别被 `assemble.py:54`、`_verify_report.py:29`、`_lint_drafts.py:233`
#: **逐字各抄一遍**（其中两处与严格版完全等价）⇒ 统一到这里，改一处即三处同步。
PROPOSAL_STRICT_RE = re.compile(rf"{FINAL_PROPOSAL}:\s*\*\*({_alt(THREE_LEVELS)})\*\*", re.I)

#: 结论块标签 → 取值正则。**只认标签，不做「扫全文取第一个五档词」的退化解析**
#: （退化解析正是铁律 8 警告的污染路径；宁可报错也不猜）。
LABEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "Recommendation": re.compile(rf"\*\*Recommendation\*\*\s*[:：]\s*\**\s*({_alt(FIVE_LEVELS)})"),
    "Rating": re.compile(rf"\*\*Rating\*\*\s*[:：]\s*\**\s*({_alt(FIVE_LEVELS)})"),
    "Action": re.compile(
        rf"\*\*Action\*\*\s*[:：]\s*\**\s*"
        rf"({'|'.join(THREE_LEVELS)}|{'|'.join(w.upper() for w in THREE_LEVELS)})"
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. 白名单（哪些席位允许在**结论块**用五档词表态）
# ─────────────────────────────────────────────────────────────────────────────

#: 允许在结论块出现**恰好 1 处**五档词的席位（其余席位正文出现即违规）。
#: ⚠️ 依据 `FRAMEWORK.md` §Ⅲ：三个风控席位同样需要表态，故共 6 席。
#: ⚠️ 「进白名单」≠「全篇任意位置可用」—— 它只是让该文件走「结论块 + 少量 slack 行」
#:    的判定分支（见 `_lint_drafts.py`）。
RATING_ALLOWED_FILES: frozenset[str] = frozenset({
    "manager.md", "portfolio_manager.md", "trader.md",
    "aggressive.md", "conservative.md", "neutral.md",
})

#: 允许出现 `FINAL TRANSACTION PROPOSAL` 的文件（**仅交易员**）。
FINAL_ALLOWED_FILES: frozenset[str] = frozenset({"trader.md"})

#: 工作文档：不是角色产出、不被渲染、也不被 `extract_rating` 解析。
#: 它们必须**逐字写出**档位词才能"定义"词汇表 —— 属合法的定义性引用。
DOC_FILES: frozenset[str] = frozenset({"0_brief.md", "0_derived.md", "_constraints.md"})

# ─────────────────────────────────────────────────────────────────────────────
# 4. 非 12 角色链路的专用通道（其产物以 `wb_analysis/evidence/` 为正规归宿）
# ─────────────────────────────────────────────────────────────────────────────

#: ★ 2026-10-10：本表由 `_reports_index.py` 上提为**唯一定义源**。
#:
#: 背景：这张豁免表原先只有 `_reports_index.py` 认识 —— 它的注释本来就写得很清楚：
#: 「不属于 12 角色链路、且**不产出报告树**的专用通道/过程产物 —— 它们**本就以
#: `evidence/` 为正规归宿**（如 `collect_treasury.py` 内建的 OUT_DIR）」。
#: 但 `_seal_run.py --orphans` 与 `scripts/_health.py` **都不认识它** ⇒ 三处判据打架：
#:   · `_reports_index.py` → 豁免 ⇒ 卫生检查 0 问题
#:   · `_seal_run.py`      → 判为孤儿 ⇒ **`--orphans --apply` 会真的把它删掉**（删除雷）
#:   · `_health.py`        → 只数文件数 ⇒ 恒报「瞬态目录非空」WARN
#: 这与「同一份契约被 8 个文件各写一遍」是同一类失败：**同一口径写在多处，必然漂移**。
#: ⇒ **新增此类通道时只改这里**，三个消费方自动同步（`_selftest.py` 有断言守住）。
#:
#: ⚠ **别把它和 `macro:10y_treasury` 搞混**（2026-10-10 记）——两者名字像、来源完全不同：
#:   · `macro:10y_treasury` = `collect.py` §10 里的**每股 FRED 通道**（只取 10Y 一根），
#:     服务个股/指数的 ERP；它**是** 12 角色链路的一环，已在 `_gap_ledger.RULES` 登记。
#:   · 本表 `TREASURY` 前缀 = `collect_treasury.py` 的**宏观专题曲线**（11 个期限 + 利差 +
#:     TIPS + 通胀预期），**不服务任何单一标的**，故豁免、不进审计包、不被 `--orphans` 清扫。
NON_TREE_PREFIXES: tuple[str, ...] = ("TREASURY",)


def is_non_tree_artifact(name: str) -> bool:
    """该 `evidence/` 文件名是否属于「非 12 角色链路、不产出报告树」的专用通道产物。

    这类产物**不是残留**：它服务任意标的（不是某一轮），以 `evidence/` 为正规归宿，
    既不进任何一轮的审计包，也**不允许**被 `--orphans` 清扫。
    """
    return name.startswith(NON_TREE_PREFIXES)


def allows_five(filename: str) -> bool:
    """该文件名是否属于「允许结论块用五档词」的席位。"""
    return filename in RATING_ALLOWED_FILES


__all__ = [
    "FIVE_LEVELS", "THREE_LEVELS", "SENTIMENT_LEVELS", "FINAL_PROPOSAL",
    "FIVE_RE", "FIVE_TITLE_RE", "THREE_BOLD_UPPER_RE", "PROPOSAL_RE",
    "PROPOSAL_STRICT_RE",
    "LABEL_PATTERNS", "RATING_ALLOWED_FILES", "FINAL_ALLOWED_FILES",
    "DOC_FILES", "allows_five",
    "NON_TREE_PREFIXES", "is_non_tree_artifact",
]
