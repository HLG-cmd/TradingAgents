# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_scan_untracked_risk.py
"""扫描**未跟踪文件**的安全风险 —— 它们从未被检查过，一旦 `git add` 就会入库。

## 为什么必须单独扫（本次评估的盲区）
上一轮开源扫描只跑了 `git ls-files`（**已跟踪**文件）。
而本次准备提交的 113 个**未跟踪**文件**从未经过任何检查**
⇒ 若其中含凭据/个人信息，`git add` 的瞬间就泄露了。
⇒ 判据：**入库前必须先扫**（这是「先检查再提交」原则的落地）。

## 扫三类
① 凭据（API key / token / 私钥 / 密码赋值）
② 个人信息（本机用户名、真实邮箱、绝对路径）
③ 大文件（> 1 MB，防仓库膨胀）
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CRED = [
    ("OpenAI 风格 key", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("通用 api_key 赋值", re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})")),
    ("Bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("密码赋值", re.compile(r"(?i)(password|passwd|secret)\s*[:=]\s*['\"]?([^\s'\"]{8,})")),
    ("AWS key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
]

PII = [
    ("Windows 用户目录", re.compile(r"[A-Za-z]:\\+Users\\+([A-Za-z0-9_.\-]+)")),
    ("Unix 用户目录", re.compile(r"/Users/([A-Za-z0-9_.\-]+)/")),
    ("真实邮箱", re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")),
]

#: 允许的占位符/示例邮箱
ALLOW = re.compile(r"(?i)(example\.(com|org)|your@|someone@|admin@example|noreply@|"
                   r"@qq\.com|@users\.noreply\.github\.com|@localhost)")


def untracked_files() -> list[str]:
    r = subprocess.run(["git", "status", "--short"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    out = []
    for line in (r.stdout or "").splitlines():
        if line.startswith("??"):
            out.append(line[3:].strip().strip('"'))
    return out


def main() -> int:
    files = untracked_files()
    print("=" * 96)
    print(f"扫描未跟踪文件：{len(files)} 项（从未被检查过）")
    print("=" * 96)

    cred_hits: list[str] = []
    pii_hits: list[str] = []
    big: list[tuple[int, str]] = []

    for rel in files:
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            sz = p.stat().st_size
        except OSError:
            continue
        if sz > 1_000_000:
            big.append((sz, rel))
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for label, rx in CRED:
            for m in rx.finditer(text):
                cred_hits.append(f"{rel}  [{label}]")
        for label, rx in PII:
            for m in rx.finditer(text):
                val = m.group(0)
                if label == "真实邮箱" and ALLOW.search(val):
                    continue
                pii_hits.append(f"{rel}  [{label}] {val[:6]}…")

    print(f"\n▸ ① 凭据：{len(cred_hits)} 处")
    for x in sorted(set(cred_hits))[:10]:
        print(f"    ✗ {x}")
    if not cred_hits:
        print("    ✓ 未发现")

    print(f"\n▸ ② 个人信息：{len(pii_hits)} 处")
    for x in sorted(set(pii_hits))[:15]:
        print(f"    {x}")
    if not pii_hits:
        print("    ✓ 未发现")

    print(f"\n▸ ③ 大文件（>1MB）：{len(big)} 个")
    for sz, rel in sorted(big, reverse=True)[:8]:
        print(f"    {sz/1e6:.2f} MB  {rel}")
    if not big:
        print("    ✓ 无")

    print()
    print("=" * 96)
    if cred_hits:
        print(f"✗ **发现 {len(cred_hits)} 处疑似凭据 ⇒ 必须先清理再提交**")
        return 1
    print(f"✓ 无凭据风险；个人信息 {len(set(pii_hits))} 处需人工判定（多为路径/占位符）")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
