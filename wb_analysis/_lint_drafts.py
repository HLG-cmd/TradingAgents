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

# ★ 2026-10-08：契约常量改为**唯一来源** import —— 别再在本文件里写正则。
#   历史：本文件曾自持一份「五档 + 大写变体」的正则，而 `_gen_meta.py` 自持一份
#   大小写敏感的 → 同一个 trader.md 在两道门禁里被判定成不同事实（详见 `_contract.py` 抬头）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wb_analysis._contract import (  # noqa: E402
    DOC_FILES as _DOC_ALL,
    FINAL_ALLOWED_FILES,
    FINAL_PROPOSAL,
    FIVE_RE as RATING_RE,
    PROPOSAL_STRICT_RE,
    RATING_ALLOWED_FILES,
)

# ★ 2026-10-10：归档跳过表由 `wb_analysis/_paths.py` 提供单一来源
#   （此前本文件与 `_check_residuals` / `_audit_values` / `_check_role_files` 各写一份）。
from wb_analysis._paths import SKIP_ARCHIVE_DIRS  # noqa: E402

NUM_RE = re.compile(r"\d[\d,]*\.?\d*")

#: 二元算式：`a op b = c`（纯数字，不含 % / 单位 / 括号）。用于 4b 算式自洽校验。
_FORMULA_RE = re.compile(
    r"(?<![\d.])(-?\d[\d,]*(?:\.\d+)?)\s*([+\-−×xX*÷/])\s*(-?\d[\d,]*(?:\.\d+)?)\s*=\s*(-?\d[\d,]*(?:\.\d+)?)(?![\d.])"
)

# 工作文档（不是角色产出、不被渲染进报告、也不被 extract_rating 解析）。
# ⚠️ 2026-09-19 修正：`_constraints.md` 必须**逐字写出五个英文词**才能"定义"评级词汇表
# （原文：「正文禁裸的英文评级词（Buy/Overweight/Hold/Underweight/Sell，含大写形式）」）。
# 这是**定义性引用**，不是违规。若不排除，它会把「契约违规」计数顶起来，
# 从而**淹没真正的违规**（正是本脚本要防的那类失败）。
# （`0_brief.md` / `0_derived.md` 已由下面的 `startswith("0_")` 跳过。）
DOC_FILES = {f for f in _DOC_ALL if f.startswith("_")}

# 这些是通用/结构性数字，不参与溯源
STOP = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
    "0.0", "1.0", "2.0", "3.0", "100", "50", "200", "20", "60", "120",
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
        for scale, _suf in ((1e3, ""), (1e6, ""), (1e9, ""), (1e12, "")):
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
        excludes = list(SKIP_ARCHIVE_DIRS)
    if len(positional) < 2:
        print(__doc__)
        return 1
    draft_dir = Path(positional[0])
    sources = [Path(p) for p in positional[1:]]
    # 统一简报与派生指标一并作为「允许来源」
    for extra in ("0_brief.md", "0_derived.md"):
        p = draft_dir / extra
        if p.exists() and p not in sources:
            sources.append(p)

    # ★ 2026-10-15：自动将传入证据包同目录的 `.derived.md` 与 `.supplement.md` 纳入合法来源，
    #   消除 `_precheck.py` 只传 `--evidence <T>_<date>.md` 时把机算派生值/补充快照值误报为未溯源数字的断层。
    for s in list(sources):
        if s.name.endswith(".md") and not s.name.endswith((".derived.md", ".supplement.md")):
            stem = s.name[:-3]
            for suf in (".derived.md", ".supplement.md"):
                cand = s.parent / f"{stem}{suf}"
                if cand.exists() and cand not in sources:
                    sources.append(cand)

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
        # 隐藏工作文件（`.prompt_bull.md` 等）本身不是角色产出：
        # 它们**必须**逐字写出被禁的英文评级词才能定义契约（否则「禁止」无从谈起），
        # 不排除就会被当成角色稿判成契约违规 —— 与 DOC_FILES 同一类盲区。
        if f.name.startswith("."):
            continue
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
            # ★ 2026-10-19：25 个 → 12 个。实测单文件可列 30+ 个（多为合法派生量），
            #   全列出来是噪声，人眼反而漏掉真正可疑的那几个。全量清单用 --full 另行导出。
            issues.append(f"  未溯源数字 {len(unknown)} 个：{', '.join(unknown[:12])}"
                          + (" …" if len(unknown) > 12 else ""))

        # --- 2. 越界的交易员契约行 ---
        # ⚠️ 必须区分「真的写了这行」与「只是提到这个短语」。
        # 实测（2026-09-17）：各角色在文末常写「本稿未写 FINAL TRANSACTION PROPOSAL 行」
        # 以示遵守契约，若用朴素子串匹配会把这类**合规声明**误判为违规。
        # ⚠️ 契约前缀字符串也取自 `_contract.FINAL_PROPOSAL`（2026-10-10 收敛）——
        #    此前 4 处各自手写这个长字符串，改一处即 4 处不同步。
        #    下面的正则**故意比 `PROPOSAL_STRICT_RE` 宽松**（容忍全角冒号与反引号），
        #    因为它是「越界行检测器」：宁可宽一点抓出来，也不要漏掉。
        #    故只把**前缀字符串**换成常量，不动它的宽松量词。
        real_fin, mentions = [], []
        for i, l in enumerate(text.splitlines(), 1):
            if FINAL_PROPOSAL not in l:
                continue
            if re.search(rf"{FINAL_PROPOSAL}\s*[:：]\s*[\*`\s]*(BUY|HOLD|SELL)", l, re.I):
                real_fin.append(i)
            else:
                mentions.append(i)
        if real_fin and f.name not in FINAL_ALLOWED_FILES:
            issues.append(f"  ✗ 越界的 FINAL TRANSACTION PROPOSAL 行（L{real_fin}）"
                          f"——只允许出现在 trader.md")
        if mentions:
            issues.append(f"  · 提示：L{mentions} 仅『提到』该短语（多为合规声明），非违规")

        # --- 3. 裸英文评级词 ---
        # ⚠️ 必须排除 trader.md 的**契约末行** `FINAL TRANSACTION PROPOSAL: **HOLD**`：
        #    该行是**要求在场**的，内容本身就是大写三档词，而 RATING_RE 含大写变体，
        #    若不排除则每一份合规的 trader.md 都会被判违规（实测：NDX 交易员稿被判 1 处）。
        #    第 2 项检查已对「该行是否越界/是否恰一次」单独负责，此处不再重复计。
        fin_lines = set(real_fin) | set(mentions)
        hits = [(i, l.strip()[:70]) for i, l in enumerate(text.splitlines(), 1)
                if RATING_RE.search(l) and i not in fin_lines]
        if f.name == "sentiment.md":
            hits = [(i, l) for i, l in hits if "Overall Sentiment" not in l]
        # ⚠️ 2026-10-01 修正（门禁盲区）：三个风险席位原先**同时**满足
        #    「在 RATING_ALLOWED_FILES 里」与「不在 {manager, portfolio_manager} 里」，
        #    于是两个分支都进不去 ⇒ 这条检查对 aggressive/conservative/neutral **从未运行过**。
        #    症状是「自报零违规」，实为真空为真（同 `if v < 13: continue` 那一类）。
        #    实测：NDX 保守方 `**Sell**（五档中最保守一档）…` 写在 §7.1 正文里，
        #    而 lint 报 0 违规。现按 manager/PM 同一口径（结论块首行 + 3 行）对风险席位一并检查。
        #    注：检查的是「块**外**出现」；块内缺失（head is None 且 hits 非空）同样落入 bad。
        if f.name not in RATING_ALLOWED_FILES and hits:
            issues.append(f"  ✗ 正文出现五档英文词 {len(hits)} 处：{hits[:3]}")
        elif f.name in RATING_ALLOWED_FILES:
            # ⚠️ 2026-10-10：此处原先**硬列了 6 个文件名**，与 `_contract.RATING_ALLOWED_FILES`
            #    值相同却各写一遍 ⇒ 往 contract 里新增一个允许表态的席位时，
            #    上面的 if 分支会跳过它（因为它「在白名单里」），而这个写死的集合又不含它
            #    ⇒ 两个分支都进不去、**该席位的正文五档词永不被检查** ——
            #    这正是本条注释下面记录的 2026-10-01 / 2026-10-02 两次门禁盲区的**同一入口**。
            #    改为直接引用同名常量。
            # ⚠️ 不能用 `else:` 代替：if 分支还带 `and hits`，改成 else 会让
            #    「白名单外且零命中」也掉进本分支（行为改变）。
            # ⚠️ 2026-10-02 二次补漏：2026-10-02 早些时候把三个风险席位加进了本分支，
            #    但**漏了 trader.md** —— 它同样同时满足「在白名单里」与「不在原 {manager, PM} 集合里」，
            #    于是它的正文五档词也从未被本检查覆盖。
            #    实测：GOOG 交易员稿正文出现 12 处 `Hold`、NFLX 出现 10 处，
            #    本检查全程静默，只有另一套 `_check_role_files.py`（RATING_OK 期望恰 1 个）抓到了。
            #    trader.md 的结论块以 `**Action**` 打头（不是 Recommendation/Rating），故一并纳入前缀识别。
            body = text.splitlines()
            head = next((i for i, l in enumerate(body, 1)
                         if l.strip().startswith(("**Recommendation**", "**Rating**",
                                                  "**Action**"))), None)
            # 交易员的结论块有 5 个字段（Action/Reasoning/Entry/Stop/Position Sizing），
            # 比 manager/PM 的 3 行宽，故容差放宽到 +5。
            slack = 5 if f.name == "trader.md" else 3
            bad = [(i, l) for i, l in hits if head is None or i > head + slack]
            if bad:
                issues.append(f"  ✗ 结论块之外出现五档英文词 {len(bad)} 处：{bad[:3]}")

        # --- 4. 结构化契约 ---
        if f.name == "sentiment.md" and "Overall Sentiment" not in text:
            issues.append("  ✗ 缺少 'Overall Sentiment' 结构化头部")
        if f.name == "manager.md" and "**Recommendation**" not in text:
            issues.append("  ✗ 缺少 **Recommendation** 结论块")
        # ★ 2026-10-15 对齐：组合经理与三个风控席位均须包含 `**Rating**` 结论块，
        #   与 _check_role_files 契约保持一致，避免各自要求不同
        if f.name in {"portfolio_manager.md", "aggressive.md", "conservative.md", "neutral.md"} and "**Rating**" not in text:
            issues.append(f"  ✗ {f.name} 缺少 **Rating** 结论块")
        if f.name == "trader.md":
            # 交易员末行正则同样是 `_contract` 单一来源（2026-10-10 收敛，此前此处内联一份）。
            if not PROPOSAL_STRICT_RE.search(text):
                issues.append("  ✗ trader.md 缺少 FINAL TRANSACTION PROPOSAL 收尾行")
            # 铁律 #46：买入操作必须具备止损与目标位，且盈亏比必须 >= 2.0
            act_m = re.search(r"\*\*Action\*\*\s*[:：]\s*(Buy|Long)", text, re.I)
            if act_m:
                entry_m = re.search(r"\*\*(?:Entry Price|Entry)\*\*\s*[:：]\s*(\d+(?:\.\d+)?)", text, re.I)
                stop_m = re.search(r"\*\*(?:Stop Loss|Stop)\*\*\s*[:：]\s*(\d+(?:\.\d+)?)", text, re.I)
                tgt_m = re.search(r"(?:第一目标(?:位)?|Target\s*1?|Take\s*Profit)\D{0,15}(\d+(?:\.\d+)?)", text, re.I)
                if not entry_m or not stop_m:
                    issues.append("  ✗ 铁律 #46 违规：Buy 操作未明确声明 Entry Price 或 Stop Loss")
                elif entry_m and stop_m:
                    entry_val = float(entry_m.group(1))
                    stop_val = float(stop_m.group(1))
                    if stop_val >= entry_val:
                        issues.append(f"  ✗ 铁律 #46 违规：做多止损价 ({stop_val}) 大于或等于入场价 ({entry_val})")
                    elif tgt_m:
                        tgt_val = float(tgt_m.group(1))
                        if tgt_val > entry_val:
                            rr = (tgt_val - entry_val) / (entry_val - stop_val)
                            if rr < 1.99:
                                issues.append(f"  ✗ 铁律 #46 违规：第一目标真实盈亏比仅为 {rr:.2f}:1，低于 2.0:1 的风控红线")

        # 铁律 #45：顺势下挫跌破支撑时严禁臆造“底背离”逆势抄底
        if f.name in ("market.md", "technical.md", "trader.md"):
            if re.search(r"跌破.{0,15}(?:支撑|均线|下轨|前低)", text) and re.search(r"(?:底背离|左侧抄底|反转确认)", text):
                negations = ("无底背离", "并无底背离", "并非底背离", "严禁", "不构成底背离", "未出现底背离", "不可盲目抄底", "防守", "观望")
                if not any(neg in text for neg in negations):
                    issues.append("  ✗ 铁律 #45 违规：跌破支撑下行趋势中出现底背离/左侧抄底表述且无警示否定词")

        # --- 4b. 算式自洽（2026-10-19 新增）---
        # 实测两轮（601899.SS / 0700.HK）共 4 处「a op b = c」算错：FY2024 ROE 分母、
        # 金价 5% 折算（140 vs 136）、EPS 敏感性表口径、股本分母 —— 全部靠人眼回读才发现。
        # 此前 lint 只查「数字是否溯源」，不查「算式是否成立」。
        # 判据：只校验**纯数字**的二元算式（不含 % / 单位 / 括号），容差 max(0.02, |结果|×1%)。
        #
        # ★ 2026-10-19 首批实测（512400.SS）发现两个**误报源**，均已修：
        #   ① 百分比结果：`2.9013 ÷ 14.5158 = 19.987` 的右边是**百分数**，原判据拿它跟 0.19987 比
        #      ⇒ 一律报「算错」。中文投研稿里比率几乎都写成百分数，这是最高频形态，
        #      若不修，本检查会变成噪声源（最终被整体关掉 —— 那才是真事故）。
        #      修法：允许两种等价成立 —— `val == z` **或** `val×100 == z`。
        #   ② 链式算式：`J = 3K − 2D = 3×13.3304 − 2×14.6219 = 39.9912 − 29.2438 = 10.7474`
        #      里，正则会把中间的 `2×14.6219 = 39.9912` 单独抓出来判定。
        #      修法：匹配点**左侧**紧邻运算符 ⇒ 属于链式表达，跳过。
        _formula_bad: list[str] = []
        for _m in _FORMULA_RE.finditer(text):
            _a, _op, _b, _c = (_m.group(i) for i in (1, 2, 3, 4))
            # 链式守卫：左侧紧邻运算符 ⇒ 跳过（不构成独立二元算式）
            _head = text[max(0, _m.start() - 12):_m.start()]
            if _head and _head.rstrip()[-1:] in "=+-−×÷/*":
                continue
            try:
                _x, _y, _z = (float(s.replace(",", "")) for s in (_a, _b, _c))
            except ValueError:
                continue
            if _op in ("+",):
                _val = _x + _y
            elif _op in ("-", "−"):
                _val = _x - _y
            elif _op in ("×", "x", "X", "*"):
                _val = _x * _y
            else:  # ÷ /
                if _y == 0:
                    continue
                _val = _x / _y
            # 两种合法形态：直接值，或百分数（右边乘 100）
            # 容差：绝对下限 0.005（避免把四舍五入误判为算错），相对 1.5%。
            # ★ 原为 max(0.02, 1%)：0.02 的绝对下限对「元」级价格差（如 0.055 写成 0.55）太松，
            #   实测漏检 0.0409 × 1.525 = 0.064（真值 0.0624）。
            _tol = max(0.005, abs(_z) * 0.015)
            if abs(_val - _z) > _tol and abs(_val * 100 - _z) > _tol:
                _formula_bad.append(f"{_m.group(0)}（应为 {_val:.4g} / 若为百分数 {_val * 100:.4g}）")
        if _formula_bad:
            issues.append(f"  ⚠ 算式不成立 {len(_formula_bad)} 处：" + "；".join(_formula_bad[:3]))

        # --- 4c. 跨轮引用（2026-10-19 新增）---
        # 本轮实测：manager.md 曾写「上轮（A 股紫金）」，违反「不看跑过的报告」的用户约束。
        _cross = [w for w in ("上轮", "上一轮", "此前报告", "历史报告", "跑过的报告") if w in text]
        if _cross:
            issues.append(f"  ⚠ 出现跨轮引用：{'、'.join(_cross)}（本项目禁止引用历史报告）")

        # --- 4d. 重复表述（2026-10-19 新增）---
        # 「每句都要有对应价值」的可执行版本：同一句（≥20 字、以句末标点收尾）
        # 在一份稿里出现 ≥2 次，即为凑字数或自我复读。只查中文句子，不查表格与标题。
        _sents = re.findall(r"[^。！？\n]{20,}[。！？]", text)
        _cnt: dict[str, int] = {}
        for _s in _sents:
            _k = re.sub(r"\s+", "", _s)
            _cnt[_k] = _cnt.get(_k, 0) + 1
        _dup = [k for k, c in _cnt.items() if c >= 2]
        if _dup:
            issues.append(f"  ⚠ 重复表述 {len(_dup)} 处（同一句出现 ≥2 次）：{_dup[0][:40]}…")

        # --- 5. 篇幅 ---
        # ★ 2026-10-19 调整：下限 6000 → 4000（用户口径：4,000 已是上限要求）。
        #   6000 对中文角色稿过高 —— 实测两轮首稿各 11/12 份低于 6000、返工 3–4 轮，
        #   补进去的内容有相当比例是「把结论换个说法再列一遍」，密度反而下降。
        #   4,000 足以容纳 5 个必需小节 + 3 条反证 + 算式；超过 6,000 反向提示偏长。
        n = len(text)
        if n < 4000:
            issues.append(f"  ⚠ 篇幅偏短（{n:,} 字符）——各角色下限 4,000（建议 4,000–4,800）")
        elif n > 6000:
            issues.append(f"  ⚠ 篇幅偏长（{n:,} 字符）——超过 6,000 请自查是否重复论述")

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
