# lifecycle: maintenance
# created: 2026-10-24
# usage: python scripts/_oneoff/_normalize_eol.py   （把误写成 CRLF 的文本文件恢复为 LF）
"""把工作区里被误写成 CRLF 的**文本文件**恢复为 LF（.bat/.ps1 例外，规范要求 crlf）。

背景：本轮用 `Path.write_text(s)` 改文件，Windows 默认 newline 转换把 `\n` 写成 `\r\n`，
回退了项目当天的 LF 归一化（git 会警告 "CRLF will be replaced by LF"）。
"""
from __future__ import annotations

import pathlib
import subprocess

KEEP_CRLF = (".bat", ".ps1", ".cmd")

def _tracked_crlf() -> list[str]:
    """已跟踪文件里工作区为 CRLF/mixed 的。"""
    out = subprocess.run(["git", "ls-files", "--eol"], capture_output=True, text=True,
                         encoding="utf-8").stdout
    paths = []
    for line in out.splitlines():
        if "w/crlf" in line or "w/mixed" in line:
            paths.append(line.split("\t", 1)[1].strip())
    return paths


def _untracked_files() -> list[str]:
    """未跟踪且未被忽略的文件（新建文件同样是 write_text 写出来的，一样会带 CRLF）。"""
    out = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    return [x for x in out.splitlines() if x.strip()]


fixed, skipped = [], []
for path in _tracked_crlf() + _untracked_files():
    if path.endswith(KEEP_CRLF):
        skipped.append(path)
        continue
    p = pathlib.Path(path)
    if not p.is_file():
        continue
    data = p.read_bytes()
    if b"\r\n" not in data:
        continue
    p.write_bytes(data.replace(b"\r\n", b"\n"))
    fixed.append(path)

print("已归一化为 LF:", len(fixed))
for f in fixed:
    print("  -", f)
if skipped:
    print("按规范保留 crlf:", skipped)
