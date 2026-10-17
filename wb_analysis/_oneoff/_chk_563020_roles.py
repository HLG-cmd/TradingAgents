# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_chk_563020_roles.py
"""一次性自检：列出 563020 草稿目录每个角色文件的字符数与「首个五档英文词」位置。

为什么要它：lint 只报「结论块之外出现五档词」，但不显示首个词在哪一行；
而 `extract_rating` 取的是**全文第一个**五档词 ⇒ 必须确认它就是结论块那一处。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from wb_analysis._contract import FIVE_RE  # noqa: E402

D = Path(__file__).resolve().parents[2] / "wb_analysis" / "drafts" / "563020_2026-10-15"


def main() -> int:
    print(f"{'文件':42s} {'字符':>7s} {'n':>3s}  首个五档词(行, 词)")
    worst = 0
    for f in sorted(D.rglob("*.md")):
        t = f.read_text(encoding="utf-8")
        hits = [(t[: m.start()].count("\n") + 1, m.group(0)) for m in FIVE_RE.finditer(t)]
        rel = str(f.relative_to(D)).replace("\\", "/")
        first = hits[0] if hits else None
        print(f"{rel:42s} {len(t):7d} {len(hits):3d}  {first}")
        if len(t) < 6200 and f.name not in ("0_brief.md", "0_derived.md"):
            worst = 1
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
