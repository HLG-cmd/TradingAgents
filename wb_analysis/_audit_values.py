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

# ★ 2026-10-10：归档跳过表由 `wb_analysis/_paths.py` 提供单一来源
#   （此前本文件的 argparse 默认值与另三处各写一份 "_stale"/"_archive"）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wb_analysis._paths import SKIP_ARCHIVE_DIRS  # noqa: E402

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


#: 「分项 = 合计」句的自洽校验正则。
#:
#: ★ 2026-10-16 重写（原正则**恒不命中**，见下）。原式为：
#:     r"([\d.]+)\s*%\s*\+\s*([\d.]+)\s*%\s*(?:\+\s*([\d.]+)\s*%\s*)?"
#:     r"(?:\+\s*([\d.]+)\s*%\s*)?=\s*\*{0,2}([\d.]+)\s*%"
#:   它要求算式严格形如 `X% + Y% = Z%`：数值后必须紧跟 `%`、`+` 后只许有空白、
#:   且最多 4 项。而项目里真实写法是：
#:     「**十大合计 19.28%**（算式：2.71+2.55+…+1.56）」      ← 分项不带 %
#:     「合计仅约 45.7%（算式：8.79+7.16+…+2.54 = 45.54%）」  ← 10 项、分项不带 %
#:   实测：在 57 棵已封存报告树的全部 md 里，「含算式且含 =」的行共 **402 行**，
#:   原正则命中 **0 行** ⇒ 本脚本宣称的第 2 项能力（自洽校验）**完全失效**，
#:   2026-10-16 审计确认的 4 处「持仓合计」错误因此全部漏检。
#:
#: 设计要求（三边都验过，见 tests/test_audit_values_sumregex.py）：
#:   ① **必须命中**真实算式：分项可带/不带 `%`、可带千分位逗号、项数 2~40 不限；
#:   ② **必须支持加减混合**：项目里大量算式形如 `13.6496 − 5.2828 + 3.2 = 11.5668`
#:      （只认 `+` 会把 `5.2828 + 3.2` 截成 `8.48` 而误报）；兼容全角 `＋` 与各种减号。
#:   ③ **不得误吃日期**：`1982-1984=100`、`09-16=7.0bp` 这类日期/年份区间是常见干扰，
#:      必须整段跳过（`DATELIKE_RE`）。首版改宽后未做此排除，一次制造 700+ 条假阳性。
#:   项与项之间**只允许空白**（不允许夹股票名等文字），否则会把无关数字串成假算式。
EXPR_RE = re.compile(
    r"(?<![\d.\-−–—])"
    r"([\d,]+(?:\.\d+)?\s*%?"
    r"(?:\s*[+\-−–—＋]\s*[\d,]+(?:\.\d+)?\s*%?){1,39})"
    r"\s*[=＝]\s*\*{0,2}\s*"
    # ★ 2026-10-16 修（**剩余 34% 漏检**）：右侧原要求「纯数字」，而本项目真实写法
    #   大量是 `= +2.463` / `= −3.40`（带显式正负号）⇒ 整条算式不匹配。
    #   实测全库 272 处「数% op 数% = ±数」中有 93 处因此漏检（`check_sums` 从未校验它们，
    #   与铁律 16「分项之和必须等于自写合计」的守门职责直接相关）。
    #   ⇒ 右侧允许可选符号（含 Unicode 减号/全角加号），`check_sums` 侧归一化后取值。
    r"([+\-−–—＋]?\s*[\d,]+(?:\.\d+)?)\s*%?"
)

#: 从算式左侧逐项提取 (符号, 数值)。
_TERM_RE = re.compile(r"([+\-−–—＋]?)\s*([\d,]+(?:\.\d+)?)")
_MINUS = set("-\u2212\u2013\u2014")

#: 日期 / 年份区间形态（`2026-10-15` 的片段、`1982-1984`、`09-16`）——
#: 命中即整段跳过，避免把日期当算式。
DATELIKE_RE = re.compile(r"(?:\b\d{4}|\b\d{2})-(?:\d{4}|\d{2})\b")

# 兼容旧名（外部若已 import SUM_RE，仍可用；行为已指向新实现）。
SUM_RE = EXPR_RE




def parse_sums(line: str) -> list[tuple[int, float, float]]:
    """解析一行里的「A + B − C … = 合计」算式，返回 [(项数, 分项和, 所写合计)]。

    ★★ 2026-10-16 抽出为**纯函数**（无副作用、不读文件）—— 这是本文件的**唯一解析口径**。

    为什么必须抽出：原 `check_sums()` 把解析**内联**在自己的循环里，而测试文件
    `tests/test_audit_values_sumregex.py` 又**复制了一份**（`_sums()`）⇒
    产品侧改了口径（右侧允许显式符号），测试侧那份副本没跟上 ⇒ 3 项 FAIL，
    报 ValueError（无法把带 Unicode 减号的右侧字符串转成 float）。
    ⇒ 与 `_contract.py` 同一动机：**同一口径写两遍必然漂移**。
    现在测试改为 `from wb_analysis._audit_values import parse_sums`，
    「改产品 = 改测试口径」，物理上不可能再分叉。

    规则：不限分项个数、支持加减混合、每项 `%` 可省、支持千分位与全角/Unicode 减号；
    右侧允许**显式正负号**（`= +2.463` / `= −3.40`）；
    日期/年份区间（`1982-1984=100`、`09-16=7.0bp`）整段跳过。
    """
    out: list[tuple[int, float, float]] = []
    for m in EXPR_RE.finditer(line):
        lhs = m.group(1)
        if DATELIKE_RE.search(lhs):  # 日期/年份区间，不是算式
            continue
        terms = []
        for sign, val in _TERM_RE.findall(lhs):
            v = float(val.replace(",", ""))
            terms.append(-v if sign in _MINUS else v)
        if len(terms) < 2:
            continue
        # 右侧可能带显式符号（`= +2.463` / `= −3.40`）
        #   ⇒ 去空白 + Unicode 减号归一化后再转 float。
        _rhs = m.group(2).replace(",", "").replace(" ", "")
        for _ch in _MINUS:
            _rhs = _rhs.replace(_ch, "-")
        _rhs = _rhs.replace("＋", "+")
        out.append((len(terms), round(sum(terms), 2), float(_rhs)))
    return out


def check_sums(path: Path):
    """校验「A + B − C … = 合计」自洽（**解析走 `parse_sums()`，本函数只管比对**）。

    返回 [(行号, 分项数, 分项和, 所写合计, 行内容)]。
    ★ 2026-10-16：解析已抽到 `parse_sums()` —— 本函数只做「取数 → 比对 → 记录行号」，
      避免与测试各写一份口径（见 `parse_sums` 的 docstring）。
    """
    bad = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for n_terms, s, total in parse_sums(line):
            if abs(s - total) > 0.015:  # 容忍四舍五入
                bad.append((ln, n_terms, s, total, line.strip()))
    return bad


def main():
    ap = argparse.ArgumentParser(description="简报/草稿口径一致性审计")
    ap.add_argument("dir", help="待审计目录")
    ap.add_argument("--stale", required=True, help="旧值黑名单 JSON（{值: 说明}）")
    ap.add_argument("--new", help="新值清单 JSON（[[值, 说明], ...]，可选）")
    ap.add_argument("--exclude", nargs="*", default=list(SKIP_ARCHIVE_DIRS),
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
            for ln, n, s, total, line in bads:
                print(f"      L{ln:<5} {n} 项分项和 {s} ≠ 所写合计 {total}   {line[:88]}")

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
