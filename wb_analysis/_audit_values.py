# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_audit_values.py
"""简报/草稿「口径一致性」审计器 —— 把已作废的旧值当成黑名单扫全文。

为什么需要它（2026-09-18 血泪）：
  简报与草稿是**分批手写**的，一旦某轮改了数值口径，**散落在各文件中的旧值不会自动消失**。
  实测 NDX 第三轮：简报有 30+ 处旧值、`market.md` 又引用了简报的旧行业分项。
  更隐蔽的是「**分项被反向编造**」：分项全错、合计全对，且分项求和连自己的合计都对不上。

本脚本做三件事：
  1. **黑名单扫描**：把「已作废的旧值」写成黑名单，扫指定目录下所有 md，
     命中即报（带行号），并可识别 MACD Hist 等**合法子串**造成的假阳性。
  2. **自洽校验**：对形如「A + B + C = 合计」的句子，**验证分项求和是否等于所写合计** ——
     不等即为「反向编造」的高置信信号。
  3. **新值就位**：确认目标新值确实出现（防止「删了旧值但忘了写新值」）。

用法：
    python wb_analysis/_audit_values.py <dir> --stale stale.json [--recursive]
    python wb_analysis/_audit_values.py wb_analysis/drafts/NDX_2026-09-17 \
        --stale wb_analysis/drafts/NDX_2026-09-17/_value_blacklist.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 合法子串白名单：这些值本身不是数据，但会包含黑名单里的数字
FALSE_POSITIVE_PATTERNS = [
    r"MACD", r"Signal", r"Hist",                  # MACD 三线数值（含表格行）
    r"^[|\s]*\d{4}-\d{2}-\d{2}",                   # 以日期开头的数据表格行（MACD 路径表）
    r"[−\-]\d+\.\d+",                              # 负号开头的数值（黑名单值均为正数口径，命中必为子串）
    r"→\s*[−\-]?\d+\.\d+",                         # 「→ −50.848」式序列
    r"布林[上下]?轨.*点",                            # 距离百分数
    r"禁用|严禁|不得引用|作废|已清除|原写|旧值|此前所有版本",
    # ★ 2026-09-22 补充：**「废弃 / 不可用 / 已剔除 / 不用」也是合法的警示语境**。
    #   实测（NFLX 轮）：简报与 _constraints 必须引用「已被判定废弃的字段值」来警示下游
    #   （如快照 FCF 25,387,552,768 > OCF 数学不成立、Debt to Equity 55.236 是百分数），
    #   原文用词是「**废弃**」而旧豁免表只认「作废」，于是产生 8 处假 FAIL。
    #   ⚠️ 改豁免表后必须**双边复测**：文档目录全绿 **且** 真实陈旧值仍被命中（见 tests / _selftest）。
    r"废弃|不可用|已剔除|不用|不采用|仅作警示|口径陷阱",  # 警示语境
    # 「X → Y」「X（实为 Y）」「写 X / 实为 Y」式**新旧对照**语境：
    # 这类句子必须同时提到旧值才说得通，属正常文档写法，不是口径污染。
    r"实为|应为|误值|实际是|误当|被误|修正为|改为",
    # 「旧稿 / 旧版 / 旧口径 / 非旧 / 无旧」式**指代或否定**语境（不再要求前面有括号——
    # 实测保守派写「无旧口径数值残留：…（非旧 28.77）」「该报告使用的旧口径」都不带括号）。
    r"旧稿|旧版|旧口径|非旧|无旧|stale",
    # 「实测：简报写 X / 误报 X」式**错误复盘**语境（skill 与 memory 文档的固定写法）
    r"`?\w*\.md`?\s*写|曾写|误报|错报|误以为|写的是",
    # ① **迁移对照表**：表格两列「陈旧值 | 正确值」并排，必然同时出现旧值与新值。
    #    结尾的变动标签是稳定特征（实测 bear.md 的 12 行对照表全部命中此类）。
    r"微调|同号|符号反转|量级修正|陈旧|对照表|迁移|旧值",
    # ② **排除声明**：明确声明「不引用 / 未使用 / 不存在于证据包」的合规行。
    r"本文不用|本方案不引用|未使用|未引用|不引用|不存在于证据包|禁止引用|明令禁止|错误读数",
    # ③ **补数巧合**：旧值恰好等于 `100 − 新值`（如新值 53.5% ⇒ 46.5%）。
    #    这类是合法的互补推导，不是引用了旧口径。
    r"跌破|尚未站上|脱队|其余|占比|仅过半|勉强过半",
]


def is_false_positive(line: str) -> bool:
    return any(re.search(p, line) for p in FALSE_POSITIVE_PATTERNS)


def scan_file(path: Path, blacklist: dict) -> list[tuple[int, str, str]]:
    """返回 [(行号, 命中值, 该行内容)]。"""
    hits = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # 若该行属白名单语境，跳过
        if is_false_positive(line):
            continue
        for val in blacklist:
            core = re.escape(val)
            if re.search(rf"(?<![\d.]){core}", line):
                hits.append((ln, val, line.strip()))
    return hits


SUM_RE = re.compile(
    r"([\d.]+)\s*%\s*\+\s*([\d.]+)\s*%\s*(?:\+\s*([\d.]+)\s*%\s*)?"
    r"(?:\+\s*([\d.]+)\s*%\s*)?"
    r"=\s*\*{0,2}([\d.]+)\s*%"
)


def check_sums(path: Path):
    """校验「A + B (+ C + D) = 合计」自洽。返回 [(行号, 分项和, 所写合计, 行内容)]。"""
    bad = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in SUM_RE.finditer(line):
            parts = [float(g) for g in m.groups()[:4] if g is not None]
            total = float(m.group(5))
            s = sum(parts)
            if abs(s - total) > 0.015:  # 容忍四舍五入
                bad.append((ln, round(s, 2), total, line.strip()))
    return bad


def main():
    ap = argparse.ArgumentParser(description="简报/草稿口径一致性审计")
    ap.add_argument("dir", help="待审计目录")
    ap.add_argument("--stale", required=True, help="旧值黑名单 JSON（{值: 说明}）")
    ap.add_argument("--new", help="新值清单 JSON（[[值, 说明], ...]，可选）")
    ap.add_argument("--exclude", nargs="*", default=["_stale", "_archive"],
                    help="跳过的子目录关键字")
    args = ap.parse_args()

    root = Path(args.dir)
    blacklist = json.loads(Path(args.stale).read_text(encoding="utf-8"))
    newvals = json.loads(Path(args.new).read_text(encoding="utf-8")) if args.new else []

    files = [p for p in root.rglob("*.md")
             if not any(k in str(p) for k in args.exclude)]
    files += [p for p in root.glob("*.md") if p not in files]  # 顶层
    files = sorted(set(files))

    print("=" * 76)
    print(f"口径审计：{root}  （{len(files)} 个文件，{len(blacklist)} 条黑名单）")
    print("=" * 76)

    all_hits = {}
    all_bad = {}
    for f in files:
        h = scan_file(f, blacklist)
        if h:
            all_hits[f] = h
        b = check_sums(f)
        if b:
            all_bad[f] = b

    # ① 旧值残留
    if not all_hits:
        print("\n✓ 无旧值残留")
    else:
        print(f"\n✗ 旧值残留（{len(all_hits)} 个文件）：")
        for f, hits in all_hits.items():
            print(f"\n  {f.relative_to(root)}")
            for ln, val, line in hits:
                print(f"      L{ln:<5} [{val}]  {line[:96]}")

    # ② 自洽性（★ 反向编造的硬证据）
    if not all_bad:
        print("\n✓ 所有「分项 = 合计」句自洽")
    else:
        print(f"\n✗★ 求和自洽性失败（{len(all_bad)} 个文件）—— 「分项被反向编造」的高置信信号：")
        for f, bads in all_bad.items():
            print(f"\n  {f.relative_to(root)}")
            for ln, s, total, line in bads:
                print(f"      L{ln:<5} 分项和 {s} ≠ 所写合计 {total}   {line[:88]}")

    # ③ 新值就位
    if newvals:
        blob = "\n".join(p.read_text(encoding="utf-8") for p in files)
        miss = [(v, d) for v, d in newvals if v not in blob]
        print()
        if miss:
            print("✗ 新值缺失：", ", ".join(f"{v}({d})" for v, d in miss))
        else:
            print(f"✓ {len(newvals)} 个新值均已出现")

    rc = 1 if (all_hits or all_bad) else 0
    print("\n" + "=" * 76)
    print("审计结论：" + ("✗ 存在问题，见上" if rc else "✓ 全部通过"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
