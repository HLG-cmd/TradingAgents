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
- **情绪六档**：`Very Bullish` `Bullish` `Somewhat Bullish` `Neutral`
  `Somewhat Bearish` `Bearish` `Very Bearish`（sentiment.md 的结构化头部用）
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

#: 情绪六/七档（`sentiment.md` 结构化头部）
SENTIMENT_LEVELS: tuple[str, ...] = (
    "Very Bullish", "Bullish", "Somewhat Bullish", "Neutral",
    "Somewhat Bearish", "Bearish", "Very Bearish",
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
PROPOSAL_RE = re.compile(rf"{FINAL_PROPOSAL}:\s*\*\*(\w+)\*\*")

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


def allows_five(filename: str) -> bool:
    """该文件名是否属于「允许结论块用五档词」的席位。"""
    return filename in RATING_ALLOWED_FILES


__all__ = [
    "FIVE_LEVELS", "THREE_LEVELS", "SENTIMENT_LEVELS", "FINAL_PROPOSAL",
    "FIVE_RE", "FIVE_TITLE_RE", "THREE_BOLD_UPPER_RE", "PROPOSAL_RE",
    "LABEL_PATTERNS", "RATING_ALLOWED_FILES", "FINAL_ALLOWED_FILES",
    "DOC_FILES", "allows_five",
]
