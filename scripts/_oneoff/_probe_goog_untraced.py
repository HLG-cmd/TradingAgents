# lifecycle: oneoff
# serves: GOOG 2026-09-29 —— 未溯源数字全量导出探针（数字溯源审计）
"""为什么需要这个探针：`_lint_drafts.py` 的「未溯源数字」清单**只打印前 25 个**，
而 fundamentals.md 一份就有 123 个。审计员看不到完整清单 = 看不到问题（静默失败）。

本探针复用 lint 的同一套判定逻辑（NUM_RE / STOP / YEAR_RE / expand），
但把结果**逐条落到行级**：文件名 + 行号 + 行内容 + 命中的数值 token，
全量导出到 `wb_analysis/analysis/GOOG_2026-09-29.untraced.md` 的「原始清单」章节，
供后续 A/B/C 三类人工判定使用。

本脚本**只做导出，不做判定**。判定由审计员写入同文件的判定章节。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# —— 与 _lint_drafts.py 保持逐字一致的判定逻辑 ——
NUM_RE = re.compile(r"\d[\d,]*\.?\d*")
STOP = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
    "0.0", "1.0", "2.0", "3.0", "100", "50", "200", "20", "60", "120", "5", "10",
}
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def norm(tok: str) -> str:
    return tok.replace(",", "").rstrip(".")


def expand(nums: set[str]) -> set[str]:
    out: set[str] = set()
    for s in nums:
        try:
            v = float(s)
        except ValueError:
            continue
        out.add(s)
        for scale in (1e3, 1e6, 1e9, 1e12):
            if abs(v) >= scale:
                out.add(f"{v / scale:.4f}".rstrip("0").rstrip("."))
                out.add(f"{v / scale:.3f}".rstrip("0").rstrip("."))
                out.add(f"{v / scale:.2f}".rstrip("0").rstrip("."))
                out.add(f"{v / scale:.1f}".rstrip("0").rstrip("."))
        for r in (0, 1, 2, 3):
            out.add(f"{round(v, r):.{r}f}".rstrip("0").rstrip(".") or "0")
            out.add(str(round(v)))
    out |= {f"{n}" for n in range(0, 101)}
    return out


def main() -> int:
    draft_dir = PROJECT_ROOT / "wb_analysis" / "drafts" / "GOOG_2026-09-29"
    ev_dir = PROJECT_ROOT / "wb_analysis" / "evidence"
    sources = [
        ev_dir / "GOOG_2026-09-29.md",
        ev_dir / "GOOG_2026-09-29.supplement.md",
        ev_dir / "GOOG_2026-09-29.derived.md",
    ]
    for extra in ("0_brief.md", "0_derived.md"):
        p = draft_dir / extra
        if p.exists():
            sources.append(p)

    allowed_raw: set[str] = set()
    for p in sources:
        if not p.exists():
            print(f"[WARN] 证据源不存在: {p}")
            continue
        allowed_raw |= {norm(t) for t in NUM_RE.findall(p.read_text(encoding="utf-8"))}
    allowed = expand(allowed_raw)
    print(f"[证据源] {len(sources)} 个，原始 {len(allowed_raw)}，展开后 {len(allowed)}")

    targets = [
        draft_dir / "1_analysts" / "market.md",
        draft_dir / "1_analysts" / "fundamentals.md",
        draft_dir / "1_analysts" / "news.md",
        draft_dir / "1_analysts" / "sentiment.md",
    ]

    out_dir = PROJECT_ROOT / "wb_analysis" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "GOOG_2026-09-29.untraced.md"

    lines: list[str] = []
    lines.append("<!-- 本文件由 scripts/_oneoff/_probe_goog_untraced.py 生成（原始清单），")
    lines.append("     判定章节由审计员 goog-auditor 手写。lifecycle: oneoff -->")
    lines.append("")
    lines.append("# GOOG 2026-09-29 未溯源数字审计 —— 原始清单 + A/B/C 判定")
    lines.append("")
    lines.append("- 基准日：2026-09-29（收盘 337.32）")
    lines.append("- 判定标准：**A 类** 合法派生（须写算式）／**B 类** 跨源引用（须指源文件）／**C 类** 可疑或编造")
    lines.append("- 铁律：写不出算式就不算 A 类")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、原始清单（行级，全量）")
    lines.append("")

    total = 0
    per_file: dict[str, list[str]] = {}
    for f in targets:
        if not f.exists():
            print(f"[WARN] 草稿不存在: {f}")
            continue
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(PROJECT_ROOT).as_posix()
        rows: list[str] = []
        seen_tokens: set[str] = set()
        hits = 0
        for i, line in enumerate(text.splitlines(), 1):
            toks = []
            for t in NUM_RE.findall(line):
                nt = norm(t)
                if nt in STOP or YEAR_RE.match(nt) or nt in allowed:
                    continue
                try:
                    v = abs(float(nt))
                except ValueError:
                    continue
                if v < 13:
                    continue
                if nt in seen_tokens:
                    continue  # 同一 token 只在首次出现处列出
                seen_tokens.add(nt)
                toks.append(t)
            if toks:
                hits += len(toks)
                rows.append(f"| {i} | {'、'.join(f'`{t}`' for t in toks)} | {line.strip()[:120]} |")
        total += hits
        per_file[rel] = rows
        lines.append(f"### {rel}")
        lines.append("")
        lines.append(f"未溯源数字（去重后）**{len(rows)} 行 / {hits} 个 token**")
        lines.append("")
        lines.append("| 行 | 未溯源数字 | 原文 |")
        lines.append("| --- | --- | --- |")
        lines.extend(rows)
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"**合计未溯源 token：{total} 个**")
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] 已导出 {total} 个未溯源 token → {out_path}")
    for rel, rows in per_file.items():
        print(f"  {rel}: {len(rows)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
