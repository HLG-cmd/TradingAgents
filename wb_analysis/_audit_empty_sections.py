# lifecycle: reusable
# created: 2026-09-27
# usage: ./.venv/Scripts/python.exe wb_analysis/_audit_empty_sections.py <evidence.md> [--strict]
"""审计证据包的「**小节正文为空**」—— 抓「通道全绿但内容是空」这类静默失败。

## 为什么需要它（2026-09-27 立，三次实证）

项目铁律 3 说「全绿 ≠ 完整」，但此前**没有任何自动检查**去落实它，于是同一类问题反复发生：

| 轮次 | 现象 | 当时的处理 |
|---|---|---|
| GOOG 9/23 | §6 宏观新闻 0/8 有正文 | 人工发现，判为「上游缺口」（**判错了**，见下） |
| AVGO 首次采集 | **报告 35/35 全绿**，但 §1 行情为空、§2 技术指标全无有效值 | 人工打开证据包才发现，重采 |
| AVGO 9/25 | §6 宏观新闻 0/6 有正文 | 人工发现；后查明是**取错通道**（Search 无 summary） |

⇒ **三次都是靠人眼**。而判据其实完全可自动化：
**「通道健康度全绿」+「某小节严格正文为 0」= 静默失败的充分信号。**

## 严格判据（铁律 35）

数「正文」前必须剔除：`Link:` 行、裸 URL、代码围栏、分隔线、空行。
不剔除会把结构行误计为正文 —— GOOG 那轮的「§6 有 1 条正文」正是把**分隔线**当成了正文。

## 退出码

0 = 无空小节；2 = 存在空小节（**阻断**，除非全部已登记进缺口台账）；1 = 调用错误。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STRIP_PREFIX = ("link:", "source:", "来源:", "url:", "- http", "http")


def _is_noise(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    low = s.lower()
    if low.startswith(STRIP_PREFIX):
        return True
    if s.startswith("```") or s.startswith("~~~"):
        return True
    # Markdown 标题行是**结构**不是正文 —— 证据包里 `### 标题` 是「条目标题」，
    # 一条新闻只有 `### 标题` + `Link:` 时，它的正文长度必须是 0。
    # （不剔标题会让「只有标题+链接」的空条目看起来有内容。）
    if s.startswith("#"):
        return True
    # 只由分隔符/空白组成（---, ===, ___ 等）
    return bool(len(set(s)) <= 2 and set(s) <= set("-=|_*· "))


def body_len(lines: list[str]) -> int:
    """严格正文长度：剔除 Link/URL/围栏/分隔线/空行后的字符数。"""
    return sum(len(l.strip()) for l in lines if not _is_noise(l))


def split_sections(text: str) -> list[tuple[str, list[str]]]:
    """按 `## ` 切分小节（`### ` 归入其父节）。返回 [(标题, 正文行)]。"""
    out: list[tuple[str, list[str]]] = []
    cur_title: str | None = None
    cur_body: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            if cur_title is not None:
                out.append((cur_title, cur_body))
            cur_title, cur_body = line[3:].strip(), []
        elif cur_title is not None:
            cur_body.append(line)
    if cur_title is not None:
        out.append((cur_title, cur_body))
    return out


def channels_health(text: str) -> tuple[int, int] | None:
    """从证据包里解析「通道健康度」的 (ok, total)；找不到返回 None。"""
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*通道", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def declared_gaps(evidence_path: pathlib.Path) -> list[str]:
    """读同目录的 `<stem>.gaps.json`（去掉 .md 后的 stem），返回已登记缺口的 label/kw。"""
    stem = evidence_path.name
    gaps = evidence_path.parent / (stem[:-3] + ".gaps.json" if stem.endswith(".md") else stem + ".gaps.json")
    if not gaps.exists():
        return []
    try:
        data = json.loads(gaps.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    keys: list[str] = []
    for g in data.get("gaps", []):
        keys.append(str(g.get("label", "")))
        keys.extend(str(k) for k in g.get("kw", []))
        keys.append(str(g.get("channel", "")))
    return [k for k in keys if k]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = pathlib.Path(argv[1])
    if not path.exists():
        print(f"✗ 证据包不存在：{path}")
        return 1
    text = path.read_text(encoding="utf-8")

    secs = split_sections(text)
    # 「父标题」识别（避免误报）：形如 `## 5. 个股新闻` 的**编号**小节若正文为空，
    # 而**紧随其后**的小节标题**不带编号**（如 `## AVGO News, from ...` ——
    # 那是通道输出自带的标题，与章节标题同级），则前者是父标题、内容挂在后者名下，不算空。
    empties: list[tuple[str, list[str]]] = []
    for i, (t, b) in enumerate(secs):
        if body_len(b) != 0:
            continue
        nxt = secs[i + 1] if i + 1 < len(secs) else None
        if nxt and not re.match(r"^\d+\.", nxt[0]) and body_len(nxt[1]) > 0:
            continue
        empties.append((t, b))

    health = channels_health(text)
    known = declared_gaps(path)

    print("=" * 72)
    print(f"小节正文审计：{path.name}")
    print("=" * 72)
    print(f"小节总数 {len(secs)}　严格正文为空 {len(empties)}")
    if health:
        ok, total = health
        print(f"通道健康度 {ok}/{total}" + ("（全绿）" if ok == total else "（有失败）"))

    if not empties:
        print("\n✓ 无空小节。")
        return 0

    print()
    for t, b in empties:
        raw = sum(len(x) for x in b)
        print(f"  · 【{t}】 原始 {raw} 字符 → 严格正文 0")

    # 「全绿 + 空小节」= 静默失败的充分信号
    suspicious = bool(health and health[0] == health[1])
    print()
    if suspicious:
        print("⚠️ **通道健康度全绿，但存在正文为空的小节** —— 这正是「静默失败」的特征")
        print("   （铁律 3：全绿 ≠ 完整）。")
    print("⇒ 请对每个空小节**逐条归因**，三种可能：")
    print("   ① 上游确实不提供 → 登记进缺口台账（`_gap_ledger.py`），并把结论改为条件式；")
    print("   ② **我们自己取错了接口/通道** → 修代码（2026-09-27 的 §6 即此类）；")
    print("   ③ 判据把内容误判为空 → 核对是否漏剔了 `Link:`/分隔线/围栏（铁律 35）。")
    print("   ⚠️ 未归因前不得直接当作「上游缺口」交付。")

    if known:
        print(f"\n（本案已登记缺口关键词：{', '.join(sorted(set(known))[:8])}）")
    else:
        print("\n（本案**未见** `.gaps.json` 缺口台账 ⇒ 空小节尚未登记）")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
