# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_lint_drafts.py
"""草稿防伪与契约校验器 —— 在渲染前拦住「编造数据」与格式违规。

**为什么需要它（2026-09-17 血泪）**
GOOG 的分析里，有两轮子智能体在草稿中写入了**证据包里根本不存在的数字**
（例如「资本开支 131.86 亿」「FCF 134.48 亿」「TTM PE 26.23」「微软 PE 27.7」），
还把一个未经证实的监管事件当成事实。这些内容一旦进入报告树，
**外观上与真实数字毫无区别**，只有逐条与证据包对账才能发现。

本脚本做两件事：
  1. **数字溯源**：把草稿里的每个数值 token 与「证据源」（证据包 + 统一简报 + 派生指标）
     做匹配。凡是证据源中找不到的，全部列出来人工复核。
     —— 注意：派生量（如「隐含 PEG ≈ 0.61」）会合法地不在证据源里，因此本项输出是
     **待复核清单，不是判罪**；但**凭空出现的绝对金额/倍数/百分比若大量命中，即为编造信号**。
  2. **契约校验**：越界的 `FINAL TRANSACTION PROPOSAL` 行、裸英文评级词、
     sentiment 结构化头部、manager/PM 的结论块是否在文首。

用法：
    python wb_analysis/_lint_drafts.py <draft_dir> <evidence_md> [evidence_md ...]
例：
    python wb_analysis/_lint_drafts.py wb_analysis/drafts/GOOG_2026-09-16 \
        wb_analysis/evidence/GOOG_2026-09-16.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
RATING_RE = re.compile(
    r"(?<![A-Za-z])(Buy|Overweight|Underweight|Sell|Hold|BUY|OVERWEIGHT|UNDERWEIGHT|SELL|HOLD)(?![A-Za-z])"
)
# 合同允许出现五档英文词的位置
# ⚠️ 2026-09-17 修正：原先只列 manager/PM/trader，但**三个风险席位
# （aggressive / conservative / neutral）按 FRAMEWORK.md 契约也必须在
# 结论块中用一个五档词表态**，否则下游无法读取风险倾向。
# 首版白名单漏了它们，导致三份合规文件被误判为「正文出现五档英文词」。
RATING_ALLOWED_FILES = {
    "manager.md", "portfolio_manager.md", "trader.md",
    "aggressive.md", "conservative.md", "neutral.md",
}
# 交易员契约行只允许出现在 trader.md
FINAL_ALLOWED_FILES = {"trader.md"}

# 工作文档（不是角色产出、不被渲染进报告、也不被 extract_rating 解析）。
# ⚠️ 2026-09-19 修正：`_constraints.md` 必须**逐字写出五个英文词**才能"定义"评级词汇表
# （原文：「正文禁裸的英文评级词（Buy/Overweight/Hold/Underweight/Sell，含大写形式）」）。
# 这是**定义性引用**，不是违规。若不排除，它会把「契约违规」计数顶起来，
# 从而**淹没真正的违规**（正是本脚本要防的那类失败）。
# （`0_brief.md` / `0_derived.md` 已由下面的 `startswith("0_")` 跳过。）
DOC_FILES = {"_constraints.md"}

# 这些是通用/结构性数字，不参与溯源
STOP = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
    "0.0", "1.0", "2.0", "3.0", "100", "50", "200", "20", "60", "120", "5", "10",
}
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def norm(tok: str) -> str:
    return tok.replace(",", "").rstrip(".")


def expand(nums: set[str]) -> set[str]:
    """把证据源里出现的数值展开成多种等价写法（缩放 + 取整）。"""
    out: set[str] = set()
    for s in nums:
        try:
            v = float(s)
        except ValueError:
            continue
        out.add(s)
        for scale, suf in ((1e3, ""), (1e6, ""), (1e9, ""), (1e12, "")):
            if abs(v) >= scale:
                out.add(f"{v / scale:.4f}".rstrip("0").rstrip("."))
                out.add(f"{v / scale:.3f}".rstrip("0").rstrip("."))
                out.add(f"{v / scale:.2f}".rstrip("0").rstrip("."))
                out.add(f"{v / scale:.1f}".rstrip("0").rstrip("."))
        for r in (0, 1, 2, 3):
            out.add(f"{round(v, r):.{r}f}".rstrip("0").rstrip(".") or "0")
            out.add(str(round(v)))
    # 常见的整数近似
    out |= {f"{n}" for n in range(0, 101)}
    return out


def _split_excludes(argv: list[str]) -> tuple[list[str], list[str]]:
    """把 `--exclude <子串>` 从 argv 中摘出，返回 (排除列表, 其余位置参数)。

    为什么要这个（2026-09-19）：
      草稿目录下会有 `_stale_pre_brief_fix/` 这类**归档子目录**，里面是**故意保留的旧稿**
      （用于 md5 与内容比对）。`rglob("*.md")` 会把它们一起扫进来，
      于是每次都要在输出里人工剔除几十行噪音 —— 而噪音淹没真问题时，
      这个校验就等于失效。默认排除 `_stale` / `_archive`（与 `_audit_values.py` 同约定）。
    """
    excludes: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--exclude" and i + 1 < len(argv):
            excludes.append(argv[i + 1])
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return excludes, rest


def main() -> int:
    excludes, positional = _split_excludes(sys.argv[1:])
    if not excludes:
        excludes = ["_stale", "_archive"]
    if len(positional) < 2:
        print(__doc__)
        return 1
    draft_dir = Path(positional[0])
    sources = [Path(p) for p in positional[1:]]
    # 统一简报与派生指标一并作为「允许来源」
    for extra in ("0_brief.md", "0_derived.md"):
        p = draft_dir / extra
        if p.exists():
            sources.append(p)

    allowed_raw: set[str] = set()
    for p in sources:
        if not p.exists():
            print(f"⚠ 证据源不存在: {p}")
            continue
        allowed_raw |= {norm(t) for t in NUM_RE.findall(p.read_text(encoding="utf-8"))}
    allowed = expand(allowed_raw)
    print(f"[证据源] {len(sources)} 个文件，原始数值 {len(allowed_raw)} 个，展开后 {len(allowed)} 个\n")

    problems = 0
    scanned = 0
    hard_total = 0          # 契约违规数（✗）—— 只有它才阻断交付
    for f in sorted(draft_dir.rglob("*.md")):
        if f.name.startswith("0_"):
            continue
        if f.name in DOC_FILES:
            continue
        if any(k in str(f.relative_to(draft_dir)) for k in excludes):
            continue
        scanned += 1
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(draft_dir)
        issues: list[str] = []

        # --- 1. 数字溯源 ---
        unknown: list[str] = []
        for tok in sorted({norm(t) for t in NUM_RE.findall(text)}):
            if tok in STOP or YEAR_RE.match(tok) or tok in allowed:
                continue
            try:
                v = abs(float(tok))
            except ValueError:
                continue
            if v < 13:  # 小整数多为序数/编号
                continue
            unknown.append(tok)
        if unknown:
            issues.append(f"  未溯源数字 {len(unknown)} 个：{', '.join(unknown[:25])}"
                          + (" …" if len(unknown) > 25 else ""))

        # --- 2. 越界的交易员契约行 ---
        # ⚠️ 必须区分「真的写了这行」与「只是提到这个短语」。
        # 实测（2026-09-17）：各角色在文末常写「本稿未写 FINAL TRANSACTION PROPOSAL 行」
        # 以示遵守契约，若用朴素子串匹配会把这类**合规声明**误判为违规。
        real_fin, mentions = [], []
        for i, l in enumerate(text.splitlines(), 1):
            if "FINAL TRANSACTION PROPOSAL" not in l:
                continue
            if re.search(r"FINAL TRANSACTION PROPOSAL\s*[:：]\s*[\*`\s]*(BUY|HOLD|SELL)", l, re.I):
                real_fin.append(i)
            else:
                mentions.append(i)
        if real_fin and f.name not in FINAL_ALLOWED_FILES:
            issues.append(f"  ✗ 越界的 FINAL TRANSACTION PROPOSAL 行（L{real_fin}）"
                          f"——只允许出现在 trader.md")
        if mentions:
            issues.append(f"  · 提示：L{mentions} 仅『提到』该短语（多为合规声明），非违规")

        # --- 3. 裸英文评级词 ---
        hits = [(i, l.strip()[:70]) for i, l in enumerate(text.splitlines(), 1)
                if RATING_RE.search(l)]
        if f.name == "sentiment.md":
            hits = [(i, l) for i, l in hits if "Overall Sentiment" not in l]
        if f.name not in RATING_ALLOWED_FILES and hits:
            issues.append(f"  ✗ 正文出现五档英文词 {len(hits)} 处：{hits[:3]}")
        elif f.name in {"manager.md", "portfolio_manager.md"}:
            body = text.splitlines()
            head = next((i for i, l in enumerate(body, 1)
                         if l.strip().startswith(("**Recommendation**", "**Rating**"))), None)
            bad = [(i, l) for i, l in hits if head is None or i > head + 3]
            if bad:
                issues.append(f"  ✗ 结论块之外出现五档英文词 {len(bad)} 处：{bad[:3]}")

        # --- 4. 结构化契约 ---
        if f.name == "sentiment.md" and "Overall Sentiment" not in text:
            issues.append("  ✗ 缺少 'Overall Sentiment' 结构化头部")
        if f.name == "manager.md" and "**Recommendation**" not in text:
            issues.append("  ✗ 缺少 **Recommendation** 结论块")
        if f.name == "portfolio_manager.md" and "**Rating**" not in text:
            issues.append("  ✗ 缺少 **Rating** 结论块")
        if f.name == "trader.md":
            if not re.search(r"FINAL TRANSACTION PROPOSAL:\s*\*\*(BUY|HOLD|SELL)\*\*", text, re.I):
                issues.append("  ✗ trader.md 缺少 FINAL TRANSACTION PROPOSAL 收尾行")

        # --- 5. 篇幅 ---
        n = len(text)
        if n < 6000:
            issues.append(f"  ⚠ 篇幅偏短（{n:,} 字符）——各角色下限通常 6000~9000")

        # --- 6. 截断检测 ---
        # 实测（2026-09-17）：子智能体写文件时可能在句子中途停笔，
        # 落盘一个**结构完整但末尾断句**的文件（bull.md 曾停在「…更低」），
        # 外观上像是正常长文，只有检查末行才看得出来。
        #
        # ⚠️ 2026-09-17 二次修正：首版正则漏了「以加粗标记结尾」这一合法形态，
        # 导致大量**误报**——例如 trader.md 的契约末行
        # `FINAL TRANSACTION PROPOSAL: **Hold**` 以 `**` 收尾，
        # 以及各风险席位末尾的 `**评级：增持。主张：…**` 加粗汇总句。
        # 二者都是**要求**的格式，不是截断。故把 `*` / `_` 补入白名单。
        body_lines = [l.rstrip() for l in text.rstrip().splitlines() if l.strip()]
        if body_lines:
            last = body_lines[-1]
            # 完整收尾的合法形态：句末标点、加粗/斜体标记、表格行、代码块围栏、右括号
            ok_end = bool(re.search(r'[。！？；：\.\!\?\|`\)）】」』\*_]$', last))
            if not ok_end:
                issues.append(
                    f"  ✗ 疑似**截断**：末行不以句末标点结尾 → {last[:80]!r}"
                )

        status = "OK" if not issues else "需复核"
        print(f"{str(rel):<34} {n:>7,} 字符  {status}")
        for it in issues:
            print(it)
        if issues:
            problems += 1
        hard_total += sum(1 for it in issues if it.strip().startswith("✗"))

    print()
    print("=" * 70)
    print(f"共扫描 {scanned} 个文件（已排除含 {excludes} 的路径与工作文档 {sorted(DOC_FILES)}），"
          f"{problems} 个文件需复核，其中**契约违规 {hard_total} 处**。")
    print("「未溯源数字」需逐个人工判断：派生量属正常，"
          "凭空出现的绝对金额/倍数即为编造信号。")
    # ★ 退出码语义（2026-09-19 修正）：
    #   契约违规（✗：越界收尾行 / 裸英文评级词 / 缺结构化头部 / 结论块不在文首 / 截断）
    #   ⇒ 返回 2，**阻断交付**。此前这里恒返回 0 —— 于是「检出 8 处违规仍报成功」，
    #   任何自动化都无法依赖它，只能靠人眼读输出。这是同一类静默失败。
    #   「未溯源数字」属**顾问性**提示（派生量会合法地不在证据源里），不阻断 ⇒ 返回 0。
    if hard_total:
        print(f"\n✗ 存在 {hard_total} 处契约违规 ⇒ 退出码 2（阻断交付）。")
        return 2
    print("\n✓ 无契约违规 ⇒ 退出码 0。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
