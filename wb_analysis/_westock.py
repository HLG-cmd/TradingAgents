# lifecycle: reusable
# created: 2026-10-10
# usage: from wb_analysis._westock import WESTOCK, run_westock, parse_md_table   （库；不单独运行）
"""`westock` CLI 的统一接入层 —— 可执行文件定位 + 调用 + 表格解析。

## 为什么抽出这个模块（2026-10-10，全项目扫描发现）

`collect_a_etf.py`（A 股 ETF）与 `collect_hk_index.py`（港股指数）曾各自**逐字复制**一份
`run_westock()` + `parse_md_table()`（逻辑完全相同，只有 docstring 措辞差几个字），
并各自硬编码了同一个可执行文件路径：

    WESTOCK = pathlib.Path(r"<用户目录>\\.local\\bin\\westock.exe")

⇒ 两个问题：
1. **机器特定**：路径写死了本机用户名与安装位置。换机器 / 换用户 ⇒ A 股与港股采集**双双失效**。
2. **同一逻辑两份**：改超时、改错误串格式、改表格解析规则时要改两处，漏一处即两套证据包格式分叉
   （而下游解析器只有一套）。

## 定位顺序（`resolve_westock`）

1. 环境变量 `WESTOCK_BIN`（显式指定，最高优先）
2. `shutil.which("westock")`（在 PATH 里就自己找得到）
3. 本机既有约定路径 `~/.local/bin/westock.exe` / `~/.local/bin/westock`

⇒ **找不到就返回该路径并让调用方报错**，绝不静默降级成「采集成功但没有数据」
（本项目铁律 3：报成功 + 外观正常，是最危险的一类失败）。
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess


#: westock 可执行文件路径（按「环境变量 → PATH → 本机约定路径」顺序解析一次）。
def resolve_westock() -> pathlib.Path:
    """按「环境变量 → PATH → 本机约定路径」顺序定位 westock（不含副作用）。"""
    env = os.environ.get("WESTOCK_BIN")
    if env:
        return pathlib.Path(env)
    found = shutil.which("westock")
    if found:
        return pathlib.Path(found)
    return pathlib.Path.home() / ".local" / "bin" / "westock.exe"


#: 模块导入时解析一次；调用方用 `WESTOCK.exists()` 判断可用性并**明确报错**。
WESTOCK: pathlib.Path = resolve_westock()


def run_westock(args: list[str], timeout: int = 180) -> str:
    """调用 westock CLI，返回 stdout 原文（失败时返回带标注的错误串）。"""
    try:
        p = subprocess.run(
            [str(WESTOCK), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        if p.returncode != 0:
            return f"<westock 退出码 {p.returncode}>\n{p.stdout}\n{p.stderr}"
        return p.stdout
    except Exception as e:  # noqa: BLE001
        return f"<westock 调用失败 {type(e).__name__}: {e}>"


def parse_md_table(text: str) -> tuple[list[str], list[list[str]]]:
    """解析 CLI 输出的 markdown 表格 → (表头, 数据行)。非表格返回空。"""
    rows = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(rows) < 2:
        return [], []

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = cells(rows[0])
    body = [cells(r) for r in rows[1:] if not re.match(r"^\|[\s\-:|]+\|$", r)]
    return header, body


def filter_news_asof(news_text: str, as_of: str) -> tuple[str, int]:
    """剔除**晚于基准日**的新闻条目，返回 (过滤后文本, 剔除条数)。

    ★ 2026-10-20 新增（实测踩坑）：`news list` 返回的是「当下」的资讯流，**不按 --date 截断**。
      基准日 2026-10-19 的证据包里混进了 10-20 的盘中消息（「洛阳钼业跌超 7%」
      「ETF 最新价创 120 日新低」），若下游照常引用，就是**用未来信息解释过去的价格**
      （前视偏差），与「基准日」这套口径自相矛盾。且它不会报错：数据看起来更「新」，
      反而更受欢迎 —— 典型的静默失败（铁律 3）。

    本函数是**唯一实现**：`collect_a_etf.py` / `collect_a_stock.py` / `collect_hk_stock.py`
    均从此处导入，避免三份拷贝各自漂移（同一口径只允许一处定义）。

    只处理 markdown 表格行（`| ... | 2026-10-20 10:30:49 | ... |`）。
    无日期的行**原样保留**（宁可留一条可疑条目，也不静默删掉整段）。
    """
    kept, dropped = [], 0
    for line in news_text.splitlines():
        if line.lstrip().startswith("|"):
            m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", line)
            if m and f"{m.group(1)}-{m.group(2)}-{m.group(3)}" > as_of:
                dropped += 1
                continue
        kept.append(line)
    return "\n".join(kept), dropped
