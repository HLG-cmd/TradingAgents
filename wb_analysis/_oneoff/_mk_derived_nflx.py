# lifecycle: oneoff
# created: 2026-10-14
# 一次性探针：把 _derive_stock.py 的 stdout 包成草稿目录的 0_derived.md。
# （_wrap_derived.py 的标题写死为 NDX，非 NDX 标的不可用，故此处显式指定标题。）
import subprocess
import sys
import pathlib

TICKER, DATE = "NFLX", "2026-10-14"
r = subprocess.run([sys.executable, "wb_analysis/_derive_stock.py", TICKER, DATE],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
if r.returncode != 0 or not r.stdout.strip():
    print("derive 失败 rc=%s" % r.returncode)
    print(r.stdout[-2000:])
    print(r.stderr[-2000:])
    raise SystemExit(1)

FENCE = "`" * 3
body = r.stdout.rstrip("\n")
out = (f"# {TICKER} 派生指标（由 wb_analysis/_derive_stock.py 生成，可直接引用）\n\n"
       f"{FENCE}\n" + body + f"\n{FENCE}\n")
p = pathlib.Path(f"wb_analysis/drafts/{TICKER}_{DATE}/0_derived.md")
p.write_text(out, encoding="utf-8", newline="\n")

back = out.split(FENCE + "\n", 1)[1].rsplit("\n" + FENCE, 1)[0] + "\n"
assert back == r.stdout, "roundtrip mismatch"
print(f"wrote {len(out)} chars -> {p}  | roundtrip OK  | {len(body.splitlines())} lines")
