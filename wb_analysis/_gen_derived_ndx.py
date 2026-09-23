# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_gen_derived_ndx.py
"""把 _derive_ndx.py 的 stdout 落盘（避免 shell 重定向写中文 + /tmp 路径问题）。

产物:
  wb_analysis/evidence/<IDX>_<date>.derived.raw.txt
  wb_analysis/drafts/<IDX>_<date>/0_derived.md   （包成 md 代码块，主模型直接引用）

用法: ./.venv/Scripts/python.exe wb_analysis/_gen_derived_ndx.py NDX 2026-09-21
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")


def main() -> int:
    idx = sys.argv[1] if len(sys.argv) > 1 else "NDX"
    date = sys.argv[2]
    proc = subprocess.run(
        [PY, str(ROOT / "wb_analysis" / "_derive_ndx.py"), date, "--index", idx],
        cwd=str(ROOT),
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode

    raw = proc.stdout.decode("utf-8", "replace")
    if len(raw.strip()) < 300:
        print("[gen] stdout 过短，疑似失败：")
        print(raw)
        print(proc.stderr.decode("utf-8", "replace"))
        return 1

    ev = ROOT / "wb_analysis" / "evidence"
    raw_path = ev / f"{idx}_{date}.derived.raw.txt"
    raw_path.write_text(raw, encoding="utf-8", newline="\n")

    drafts = ROOT / "wb_analysis" / "drafts" / f"{idx}_{date}"
    drafts.mkdir(parents=True, exist_ok=True)
    md_path = drafts / "0_derived.md"
    body = raw.rstrip("\n")
    out = f"# {idx} 派生指标（由 wb_analysis/_derive_ndx.py 生成，可直接引用）\n\n```\n{body}\n```\n"
    md_path.write_text(out, encoding="utf-8", newline="\n")

    back = out.split("```\n", 1)[1].rsplit("\n```", 1)[0] + "\n"
    assert back == raw, "roundtrip mismatch"

    print(f"wrote {len(out.encode('utf-8'))} bytes -> {md_path}")
    print(f"raw  {len(raw.encode('utf-8'))} bytes -> {raw_path}")
    print("roundtrip ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
