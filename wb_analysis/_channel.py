# lifecycle: reusable
# created: 2026-10-23
# usage: from wb_analysis._channel import ok_of   （库；被各采集器 import，不单独运行）
"""采集通道健康度判据的**唯一定义源**（Single source of truth for channel ok_of）。

## 为什么抽出这个模块（2026-10-23）

此前 `collect_a_etf.py` 与 `collect_a_stock.py` 各自维护一份 `ok_of(raw)`：
- `collect_a_etf.py` 在 2026-10-21 踩中 518880 黄金 ETF 假绿事故后，补齐了中文失败签名
  （`"查询"`、`"失败"`、`"service error"`、`"error_type="`）；
- 但 `collect_a_stock.py` 仍停留在旧判据 `("error" not in str(raw).lower()[:40])`，导致：
  1. **假绿**：westock 返回长中文错误文本（如 `"查询dayK线数据返回为空... [code=1620053001] msg=service error"`，
     `"error"` 出现在第 40 字符之后）时，`collect_a_stock.ok_of` 误判为 `True`；
  2. **假红**：正常文本前 40 字符内恰好含 `"error"` 字样（如注释 `# no error found`）时被误判为 `False`。

本模块将 `ok_of` 收敛为唯一实现，由 `collect_a_etf.py`、`collect_a_stock.py`、
`collect_hk_index.py`、`collect_hk_stock.py` 统一导入，彻底消除双判据漂移。

## 2026-10-23 二次修正：裸子串「失败」会造成系统性假红

收敛后统一沿用了 ETF 版判据，其中含**裸子串** `"查询"` / `"失败"`。实测发现两类误判：

1. **westock batch 通道的成功输出自带汇总行**：

       [Batch] 状态: success | 总数: 1 | 成功: 1 | 失败: 0

   `"失败" in text` 命中 `失败: 0` ⇒ 整条通道被判 `False`。
   真实证据：`reports/601899.SS/601899.SS_20261019_004657/_source.zip` 的 §5.2 融资融券小节
   （全库扫描 2 个证据包 / 2 处命中，全部在该小节），即 `fund_margin` 通道**恒定假红**。

2. **自由文本通道**（`news` / `notice` / `profile`）正文天然含「失败」「查询」这类普通词，
   例如新闻标题「海外并购项目因审批失败终止」会被判成通道故障。

⇒ 判据改为两层：**结构性签名**（与自然语言无关，命中即失败）+ **定向失败句式**
（只匹配「查询失败」「失败：[code=...」「失败: 3」这类真故障形态，不匹配「失败: 0」与正文用词）。
"""

from __future__ import annotations

import re

__all__ = ["FAILURE_PATTERNS", "FAILURE_SIGNATURES", "ok_of"]

#: 结构性失败签名：与自然语言无关，出现在**通道输出**里就说明调用没成功。
#:
#: ★ 刻意**不含**裸 `"失败"` / `"查询"` —— 那两个词在 batch 汇总行（`失败: 0`）和
#:   新闻正文里都会正常出现，详见模块 docstring 的 2026-10-23 二次修正。
FAILURE_SIGNATURES: tuple[str, ...] = (
    "数据为空",
    "(命令失败",
    "service error",
    "error_type=",
)

#: 定向失败句式（正则）。只认「真故障」形态，不认自然语言里的「失败」用词。
FAILURE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:查询|获取|调用|请求|接口)失败"),   # 「查询dayK线失败」
    re.compile(r"失败\s*[:：]\s*\["),                  # 「失败：[code=1620053001]」
    re.compile(r"失败\s*[:：]\s*[1-9]"),               # batch 汇总里的非零失败数
)


def ok_of(raw: object) -> bool:
    """判定采集通道是否真的取到了有效数据（**不是**「返回了非空文本」）。

    排除四类伪成功 / 失败文本：
    1. 空串或纯空白；
    2. `run_westock` 构造的 `<westock ...>` 哨兵错误串；
    3. 结构性失败签名（见 `FAILURE_SIGNATURES`）；
    4. 定向失败句式（见 `FAILURE_PATTERNS`）。

    ★ 不因正文出现「失败」「查询」等**普通用词**而判失败：`失败: 0`（batch 成功汇总）
      与新闻正文里的「并购失败」都属正常内容。
    """
    t = str(raw or "")
    if not t.strip() or "<westock" in t:
        return False
    if any(k in t for k in FAILURE_SIGNATURES):
        return False
    return not any(p.search(t) for p in FAILURE_PATTERNS)
