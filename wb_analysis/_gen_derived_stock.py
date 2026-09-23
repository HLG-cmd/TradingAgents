# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py
"""把 _derive_stock.py 的 stdout 落成证据包同级文件（避免 shell 重定向写中文）。

产物（与 MU 轮的历史约定一致）:
  wb_analysis/evidence/<TICKER>_<date>.derived.raw.txt   # 原始 stdout
  wb_analysis/evidence/<TICKER>_<date>.derived.md        # 包成 md 代码块，供主模型直接引用

用法: ./.venv/Scripts/python.exe wb_analysis/_gen_derived_stock.py GOOG 2026-09-21
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")


def main() -> int:
    ticker = sys.argv[1]
    date = sys.argv[2]
    proc = subprocess.run(
        [PY, str(ROOT / "wb_analysis" / "_derive_stock.py"), ticker, date],
        cwd=str(ROOT),
        capture_output=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode

    raw = proc.stdout.decode("utf-8", "replace")
    if len(raw.strip()) < 500:
        print("[gen] stdout 过短，疑似失败：")
        print(raw)
        return 1

    ev = ROOT / "wb_analysis" / "evidence"
    raw_path = ev / f"{ticker}_{date}.derived.raw.txt"
    md_path = ev / f"{ticker}_{date}.derived.md"
    raw_path.write_text(raw, encoding="utf-8", newline="\n")

    body = raw.rstrip("\n")
    out = f"# {ticker} 派生指标（由 wb_analysis/_derive_stock.py 生成，可直接引用）\n\n```\n{body}\n```\n"
    md_path.write_text(out, encoding="utf-8", newline="\n")

    # 往返自校验
    back = out.split("```\n", 1)[1].rsplit("\n```", 1)[0] + "\n"
    assert back == raw, "roundtrip mismatch"

    print(f"wrote {len(out.encode('utf-8'))} bytes -> {md_path}")
    print(f"raw  {len(raw.encode('utf-8'))} bytes -> {raw_path}")
    print("roundtrip ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
