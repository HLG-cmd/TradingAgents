# lifecycle: oneoff
# created: 2026-09-29
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_ndx_untraced.py
"""一次性探针：导出 NDX_2026-09-29 草稿的全部「未溯源数字」（带行号与原文），
并同时给出该数字在其它合法来源（跨源文件）中的命中情况，供人工判定 A/B/C 三类。

背景：_lint_drafts.py 默认只打印前 25 个 token，无法做完整的人工逐条复核；
本脚本复用它的 norm/expand 逻辑，输出全量清单到 wb_analysis/analysis/NDX_2026-09-29.untraced.md。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "wb_analysis"))

from _lint_drafts import NUM_RE, STOP, YEAR_RE, norm, expand  # noqa: E402

DRAFT_DIR = ROOT / "wb_analysis" / "drafts" / "NDX_2026-09-29"
TARGETS = [
    "1_analysts/market.md",
    "1_analysts/fundamentals.md",
    "1_analysts/news.md",
    "1_analysts/sentiment.md",
    "2_research/bull.md",
    "2_research/bear.md",
]
# lint 认可的证据源
EVIDENCE = [
    ROOT / "wb_analysis" / "evidence" / "NDX_2026-09-29.md",
    ROOT / "wb_analysis" / "evidence" / "NDX_2026-09-29.supplement.md",
    DRAFT_DIR / "0_brief.md",
]
# 跨源：本轮其它合法来源（用于判定 B 类）
CROSS = {
    "NDX.json": ROOT / "wb_analysis" / "evidence" / "NDX_2026-09-29.json",
    "NDX.gaps.json": ROOT / "wb_analysis" / "evidence" / "NDX_2026-09-29.gaps.json",
    "NDX.supplement.md": ROOT / "wb_analysis" / "evidence" / "NDX_2026-09-29.supplement.md",
    "GOOG.md": ROOT / "wb_analysis" / "evidence" / "GOOG_2026-09-29.md",
    "GOOG.derived.md": ROOT / "wb_analysis" / "evidence" / "GOOG_2026-09-29.derived.md",
    "GOOG.supplement.md": ROOT / "wb_analysis" / "evidence" / "GOOG_2026-09-29.supplement.md",
    "SPX.md": ROOT / "wb_analysis" / "evidence" / "SPX_2026-09-25.md",
    "NVDA.md": ROOT / "wb_analysis" / "evidence" / "NVDA_2026-09-28.md",
    "NVDA.derived.md": ROOT / "wb_analysis" / "evidence" / "NVDA_2026-09-28.derived.md",
    "TREASURY_09-28.md": ROOT / "wb_analysis" / "evidence" / "TREASURY_2026-09-28.md",
    "TREASURY_09-29.md": ROOT / "wb_analysis" / "evidence" / "TREASURY_2026-09-29.md",
    "TREASURY_09-30.md": ROOT / "wb_analysis" / "evidence" / "TREASURY_2026-09-30.md",
    "ERP缓存": ROOT / "wb_analysis" / "_cache" / "erp_history_sp500.json",
}


def load_tokens(path: Path) -> set[str]:
    if not path.exists():
        return set()
    txt = path.read_text(encoding="utf-8", errors="replace")
    return {norm(t) for t in NUM_RE.findall(txt)}


def main() -> int:
    allowed_raw: set[str] = set()
    for p in EVIDENCE:
        if p.exists():
            allowed_raw |= load_tokens(p)
    allowed = expand(allowed_raw)
    print(f"[证据源] {len([p for p in EVIDENCE if p.exists()])} 个，原始 {len(allowed_raw)} → 展开 {len(allowed)}")

    cross_exp: dict[str, set[str]] = {}
    for name, p in CROSS.items():
        raw = load_tokens(p)
        cross_exp[name] = expand(raw)
        print(f"[跨源] {name:<22} 原始 {len(raw):>5} → 展开 {len(cross_exp[name]):>6}"
              f"{'' if p.exists() else '  ⚠ 不存在'}")

    out_lines: list[str] = []
    total = 0
    for rel in TARGETS:
        f = DRAFT_DIR / rel
        if not f.exists():
            print(f"⚠ 草稿不存在: {f}")
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        hits: list[tuple[str, int, str, str]] = []
        for i, line in enumerate(lines, 1):
            for m in NUM_RE.finditer(line):
                tok = norm(m.group(0))
                if tok in STOP or YEAR_RE.match(tok) or tok in allowed:
                    continue
                try:
                    v = abs(float(tok))
                except ValueError:
                    continue
                if v < 13:
                    continue
                hits.append((tok, i, m.group(0), line.strip()))
        # 去重：同文件同一 token 只保留首次出现，但列出全部行号
        agg: dict[str, dict] = {}
        for tok, i, raw, line in hits:
            e = agg.setdefault(tok, {"raw": raw, "lines": [], "ctx": line})
            e["lines"].append(i)
        keys = sorted(agg, key=lambda s: (float(s) if s.replace(".", "").isdigit() else 0))
        out_lines.append(f"\n## {rel}　（未溯源 {len(keys)} 个 token，出现 {len(hits)} 次）\n")
        for tok in keys:
            e = agg[tok]
            cross = [n for n, s in cross_exp.items() if tok in s]
            tag = f"跨源命中: {', '.join(cross)}" if cross else "**跨源无命中**"
            ln = ", ".join(str(x) for x in e["lines"][:12]) + (" …" if len(e["lines"]) > 12 else "")
            out_lines.append(f"- `{tok}` (原文 `{e['raw']}`) L{ln}｜{tag}")
            out_lines.append(f"  - 上下文：{e['ctx'][:220]}")
        total += len(keys)

    outp = ROOT / "wb_analysis" / "analysis" / "NDX_2026-09-29.untraced.md"
    outp.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "# NDX 2026-09-29 草稿未溯源数字全量清单（探针原始输出）",
        "",
        f"> 生成器：`scripts/_oneoff/_probe_ndx_untraced.py`（lifecycle: oneoff）",
        f"> 判定用的证据源：`NDX_2026-09-29.md` + `.supplement.md` + `0_brief.md`",
        f"> 合计 **{total}** 个不同的未溯源 token（跨 6 份草稿）。",
        "",
        "---",
    ]
    outp.write_text("\n".join(header + out_lines) + "\n", encoding="utf-8")
    print(f"\n✓ 已写出 {outp}（{total} 个 token）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
