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

RATING = re.compile(r"\b(Buy|Overweight|Hold|Underweight|Sell)\b")
THREE = __import__("re").compile(r"\*\*(BUY|HOLD|SELL)\*\*")  # 交易员的大写三档
RATING_OK = {  # 只允许出现 1 次五档词的席位（结论块那处）
    "manager.md", "portfolio_manager.md", "trader.md",
    "aggressive.md", "conservative.md", "neutral.md",
}
REQUIRED_SECTION = {
    "market.md": ["### 趋势", "### 动量", "### 波动率", "### 量能", "### 关键价位"],
    "sentiment.md": ["**Overall Sentiment:**", "**Confidence:**"],
    "manager.md": ["**Recommendation**", "**Rationale**", "**Strategic Actions**"],
    "portfolio_manager.md": ["**Rating**", "**Executive Summary**", "**Investment Thesis**"],
}
FTP = "FINAL TRANSACTION PROPOSAL"


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
                 if not p.name.startswith("0_") and not p.name.startswith("_")]
        if not files:
            print("  （尚无角色文件）")
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
                hits3 = THREE.findall(t)
                if not hits3 and not hits:
                    flags.append("缺结论档位（交易员应在末行表态）")
                elif len(hits3) > 1 or len(hits) > 1:
                    flags.append(f"档位词过多（三档 {len(hits3)} + 五档 {len(hits)}，只允许 1 处）")
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
            miss = [s for s in REQUIRED_SECTION.get(f.name, []) if s not in t]
            if miss:
                flags.append(f"缺小节 {miss}")
            status = "OK " if not flags else "!! "
            print(f"  {status}{rel:44s} len={len(t):6d}  五档={len(hits)}  FTP={ftp}")
            for x in flags:
                print(f"        - {x}")
                bad += 1
        print()
    print(f"总计问题项: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
