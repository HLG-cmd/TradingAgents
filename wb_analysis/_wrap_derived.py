# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_wrap_derived.py <src_path> <dst_path>
"""把 _derive_ndx.py 的 stdout 包成 md 代码块，覆写 0_derived.md。"""
from __future__ import annotations

import sys
from pathlib import Path


def wrap_derived(src_path: str | Path, dst_path: str | Path) -> None:
    raw = Path(src_path).read_text(encoding="utf-8")
    body = raw.rstrip("\n")
    out = (
        "# NDX 派生指标（由 wb_analysis/_derive_ndx.py 生成，可直接引用）\n\n"
        "```\n" + body + "\n```\n"
    )
    Path(dst_path).write_text(out, encoding="utf-8", newline="\n")
    print(f"wrote {len(out.encode('utf-8'))} bytes -> {dst_path}")

    # 自校验：把 md 里的代码块剥回来，必须与原始 stdout 逐字节一致
    back = out.split("```\n", 1)[1].rsplit("\n```", 1)[0] + "\n"
    assert back == raw, "roundtrip mismatch"
    print("roundtrip ok")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("用法: python wb_analysis/_wrap_derived.py <src_path> <dst_path>", file=sys.stderr)
        return 2
    wrap_derived(args[0], args[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
