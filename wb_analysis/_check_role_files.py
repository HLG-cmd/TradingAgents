# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_check_role_files.py
"""角色文件体检：篇幅 / 裸五档英文词 / 越界 PROPOSAL / 合规声明 / 必需小节。

用法: ./.venv/Scripts/python.exe wb_analysis/_check_role_files.py GOOG_2026-09-21 [NDX_2026-09-21 ...]
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "wb_analysis" / "drafts"

# ★ 2026-10-08：契约常量改为**唯一来源** import（见 `_contract.py` 抬头的漂移史）。
#   此前本文件持有**两套**正则：`RATING`（Title Case 五档）+ `THREE`（大写三档）。
#   实测事故：trader.md 末行 `**SELL**` 被 `THREE` 计入，而结论块 `**Action**: Sell`
#   若被写成大写 `**Action**: SELL` 又会同时命中 → 「档位词过多」的误报，
#   逼得正文档位词全部中文化才收敛。现在按契约精确匹配，不再靠人试。
sys.path.insert(0, str(ROOT))
from wb_analysis._contract import (  # noqa: E402
    FINAL_PROPOSAL,
    FIVE_TITLE_RE as RATING,
    LABEL_PATTERNS,
    PROPOSAL_RE,
    RATING_ALLOWED_FILES,
    THREE_BOLD_UPPER_RE as THREE,
)
from wb_analysis._paths import is_archived_path  # noqa: E402

RATING_OK = set(RATING_ALLOWED_FILES)  # 只允许出现 1 次五档词的席位（结论块那处）
REQUIRED_SECTION = {
    # ⚠️ 2026-10-02 修正（判别力 vs 形式主义）：原为**精确字符串**
    #    `["### 趋势", "### 动量", ...]`，等价于要求所有市场分析师都用同一个标题体例。
    #    实测事故（NDX 2026-10-01）：该稿把五个维度写成
    #    `## 1. 趋势：…` / `## 2. 动量：…` / `## 3. 波动率：…` / `## 4. 量能与 K 线结构` / `## 7. 关键价位（全部为绝对点位）`
    #    —— **五个维度全部有实质专节**，但因标题前缀不同被判「缺小节」。
    #    ⇒ 契约的**意图**是「必须覆盖这五个维度」，不是「标题必须恰好长这样」。
    #    改为**按维度名做正则**，容忍 `#`/`##`/`###` 层级与 `1.` 这类序号前缀。
    #    （GOOG 那份恰好含字面 `### 趋势` 等，改动后仍通过 —— 双边已验证。）
    "market.md": [
        ("趋势", r"^#{1,4}\s*\**\s*[\d一二三四五六七八九十]*[.、]?\s*趋势"),
        ("动量", r"^#{1,4}\s*\**\s*[\d一二三四五六七八九十]*[.、]?\s*动量"),
        ("波动率", r"^#{1,4}\s*\**\s*[\d一二三四五六七八九十]*[.、]?\s*波动率"),
        ("量能", r"^#{1,4}\s*\**\s*[\d一二三四五六七八九十]*[.、]?\s*量能"),
        ("关键价位", r"^#{1,4}\s*\**\s*[\d一二三四五六七八九十]*[.、]?\s*(关键价位|支撑与阻力|支撑/阻力)"),
    ],
    "sentiment.md": [("**Overall Sentiment:**", r"\*\*Overall Sentiment:\*\*"),
                     ("**Confidence:**", r"\*\*Confidence:\*\*")],
    "manager.md": [("**Recommendation**", r"\*\*Recommendation\*\*"),
                   ("**Rationale**", r"\*\*Rationale\*\*"),
                   ("**Strategic Actions**", r"\*\*Strategic Actions\*\*")],
    "portfolio_manager.md": [("**Rating**", r"\*\*Rating\*\*"),
                             ("**Executive Summary**", r"\*\*Executive Summary\*\*"),
                             ("**Investment Thesis**", r"\*\*Investment Thesis\*\*")],
}
FTP = FINAL_PROPOSAL  # ← 唯一来源，别再硬编码字面量。


def main() -> int:
    bad = 0
    for name in sys.argv[1:]:
        d = DRAFTS / name
        print("=" * 78)
        print(f"角色文件体检: {d}")
        print("=" * 78)
        if not d.is_dir():
            print("  ✗ 目录不存在")
            bad += 1
            continue
        files = [p for p in sorted(d.rglob("*.md"))
                 if not p.name.startswith("0_") and not p.name.startswith("_") and not p.name.startswith(".")
                 # ⚠️ 2026-10-02：与 `_lint_drafts.py` 对齐——排除 `_stale` / `_archive`。
                 #    被作废的旧稿不参与交付，却被本检查器计入「问题项」，制造了 6 条噪声
                 #    （manager_stale / trader_stale / 4 个风险席位 _stale）。
                 #    两套检查器对「哪些文件算交付物」的口径必须一致，否则问题数无法横向比较。
                 # ★ 2026-10-10：改走 `wb_analysis/_paths.py::is_archived_path()` 单一来源。
                 #   此前这里 `_stale` 只比 `p.name`、`_archive` 却比 `p.as_posix()` —— **同一件事
                 #   两种比法**，于是 `_stale*/` **子目录**里的角色稿会被误计入交付物，而
                 #   `_lint_drafts.py`（按子串比全路径）不会 ⇒ 两套检查器的问题数无法横向比较。
                 #   实测当前 `drafts/`+`evidence/` 下不存在任何 `_stale*`/`_archive*` 目录，
                 #   故本次对称化**可证为 no-op**，只是把未来的漏洞堵上。
                 and not is_archived_path(p)]
        if not files:
            # ★★ 2026-10-16 修（本日第 9 例「检查器判据缺陷」，**已实测复现**）：
            #   原实现只打印提示、**不计入 `bad`** ⇒ 末尾 `return 1 if bad else 0` 得到 0
            #   ⇒ **空草稿目录被判「通过」**。
            #   实测与 `_verify_ratings.py` 冲突：同一空目录
            #     · 本脚本            → rc=0（通过）
            #     · `_verify_ratings` → rc=1（列出 12 个缺失角色文件）
            #   ⇒ 「同一交付物、两个门禁结论相反」，正是本项目最反对的口径漂移。
            #   ⇒ 「零个角色文件」是**缺陷**而非中性状态：交付物本应含 12 个角色文件。
            print("  ✗ 无任何角色文件（交付物应含 12 个角色文件）")
            bad += 1
            continue
        for f in files:
            t = f.read_text(encoding="utf-8")
            rel = f.relative_to(d).as_posix()
            hits = RATING.findall(t)
            ftp = t.count(FTP)
            flags = []
            # ★ 2026-09-23 修**误报**：交易员的契约是**大写三档**（BUY/HOLD/SELL），
            #   而 RATING 只匹配 Title Case 的**五档**（Buy/Hold/…）⇒ 一个完全正确的交易员文件
            #   会被判「缺五档词」。实测 NDX 轮：末行 `FINAL TRANSACTION PROPOSAL: **HOLD**`、
            #   全文 HOLD 只出现 1 次，却被标 `!!` —— **惩罚正确的文件比漏报更有害**（会让人开始忽略门禁）。
            if f.name == "trader.md":
                # ★ 2026-10-08 重写判据：交易员的档位词出现在**两个契约位置** ——
                #   结论块首行 `**Action**: Sell`（Title Case）与末行
                #   `FINAL TRANSACTION PROPOSAL: **SELL**`（大写）。
                #   旧实现用 `THREE`（大写三档）找末行、`RATING`（Title Case 五档）找首行，
                #   再断言「两者各自 ≤1」——但只要有人把首行写成大写（契约允许的变体），
                #   同一个词就会被两套正则**各数一遍**，报出「档位词过多」的假阳性。
                #   ⇒ 现在按**位置**判定：首行取 `**Action**:` 行，末行取 PROPOSAL 行，
                #     其余任何位置出现档位词才算违规。
                body_wo_contract = PROPOSAL_RE.sub("", t)
                lines = body_wo_contract.split("\n")
                action_lines = [i for i, l in enumerate(lines) if LABEL_PATTERNS["Action"].search(l)]
                stray = list(RATING.findall(
                    "\n".join(l for i, l in enumerate(lines) if i not in action_lines)))
                if not action_lines and not PROPOSAL_RE.search(t):
                    flags.append("缺结论档位（交易员应在结论块首行或末行表态）")
                if len(action_lines) > 1:
                    flags.append(f"**Action** 行 {len(action_lines)} 处（只允许 1 处）")
                if stray:
                    flags.append(f"越界档位词 {stray}（只允许出现在 **Action** 行与末行 PROPOSAL）")
            elif f.name in RATING_OK:
                if len(hits) == 0:
                    flags.append("缺五档词（该席位应在结论块表态）")
                elif len(hits) > 1:
                    flags.append(f"五档词 {len(hits)} 处（只允许结论块 1 处）")
            else:
                if hits:
                    flags.append(f"越界五档词 {hits}")
            if ftp and f.name != "trader.md":
                flags.append(f"越界 PROPOSAL ×{ftp}")
            if f.name == "trader.md" and ftp != 1:
                flags.append(f"PROPOSAL 出现 {ftp} 次（应恰好 1 次且在末行）")
            # ⚠️ 「自我合规声明」只在**逐字列举五档词**时才真的违规 ——
            #    那个情形已被上面的 RATING.findall 捕获。
            #    不列举词、只写「本报告不含五档英文评级词」是无害的表述，
            #    **不要**在这里再判一次（会造成误报，而误报过多的检测器等于没有检测器）。
            if len(t) < 4000:
                flags.append(f"篇幅偏短 {len(t)}")
            miss = [lbl for lbl, pat in REQUIRED_SECTION.get(f.name, [])
                    if not re.search(pat, t, re.M)]
            if miss:
                flags.append(f"缺小节 {miss}")
            status = "OK " if not flags else "!! "
            print(f"  {status}{rel:44s} len={len(t):6d}  档位={len(hits)}  FTP={ftp}")
            for x in flags:
                print(f"        - {x}")
                bad += 1
        print()
    print(f"总计问题项: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
