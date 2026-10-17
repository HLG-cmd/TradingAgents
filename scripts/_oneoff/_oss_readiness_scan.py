# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_oss_readiness_scan.py
"""开源准备度扫描：在**已跟踪文件**里找不该公开的内容。

## 为什么用 Python 而不是 shell
`grep` 的 Windows 路径模式含反斜杠，内联进 shell 会被静默改写（本项目铁律 21/22/29）。
⇒ 凡含反斜杠/特殊字符的检索一律落盘执行。

## 扫什么（五类，按危害排序）
| 类 | 危害 | 判据 |
|---|---|---|
| ① 凭据 | **最高**（泄露即被盗用） | API key / token / 私钥块 / 密码赋值 |
| ② 个人信息 | 高（隐私） | 本机用户名、邮箱、绝对路径 |
| ③ 内部信息 | 中 | 内部主机名 / 内网地址 / 私有仓库地址 |
| ④ 大文件 | 低（仓库膨胀） | > 5 MB 的已跟踪文件 |
| ⑤ 机器特定配置 | 中（他人无法运行） | 硬编码的本机路径 |

⚠️ 只**报告**命中位置与**脱敏片段**，绝不打印疑似凭据的完整值。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: ① 凭据类
CRED = [
    ("OpenAI 风格 key", re.compile(r"sk-[A-Za-z0-9_\-]{20,}")),
    ("通用 api_key 赋值", re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{16,})")),
    ("Bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("私钥块", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("密码赋值", re.compile(r"(?i)(password|passwd|secret)\s*[:=]\s*['\"]?([^\s'\"]{8,})")),
    ("AWS key", re.compile(r"AKIA[0-9A-Z]{16}")),
]

#: ② 个人信息类
PII = [
    ("Windows 用户目录", re.compile(r"[A-Za-z]:\\+Users\\+([A-Za-z0-9_.\-]+)")),
    ("Unix 用户目录", re.compile(r"/Users/([A-Za-z0-9_.\-]+)/")),
    ("邮箱地址", re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")),
]

#: ③ 内部信息类
INTERNAL = [
    ("内网地址", re.compile(r"\b(?:10|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b")),
    ("私有仓库", re.compile(r"(?i)(gitlab|git\.[a-z0-9\-]+\.(?:local|internal|corp))")),
]

#: 允许出现的邮箱（上游作者 / 许可证 / 示例占位符）
ALLOW_EMAIL = re.compile(r"(?i)(admin@example\.com|example\.(com|org)|noreply@|@users\.noreply\.github\.com|"
                         r"yijia|xiaoyijia|@qq\.com$|你的名字)")


def tracked_files() -> list[str]:
    r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return [l for l in (r.stdout or "").splitlines() if l.strip()]


def redact(s: str) -> str:
    """脱敏：只保留前 4 字符。"""
    s = s.strip()
    return s[:4] + "…" if len(s) > 4 else "…"


def main() -> int:
    files = tracked_files()
    print("=" * 96)
    print(f"开源准备度扫描：{len(files)} 个已跟踪文件")
    print("=" * 96)

    hits: dict[str, list[str]] = {"① 凭据": [], "② 个人信息": [], "③ 内部信息": []}

    for rel in files:
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            if p.stat().st_size > 4_000_000:      # 超大文件跳过（另有一类检查）
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for label, rx in CRED:
            for m in rx.finditer(text):
                val = m.group(m.lastindex) if m.lastindex else m.group(0)
                hits["① 凭据"].append(f"{rel}  [{label}] {redact(val)}")
        for label, rx in PII:
            for m in rx.finditer(text):
                val = m.group(m.lastindex) if m.lastindex else m.group(0)
                if label == "邮箱地址" and ALLOW_EMAIL.search(val):
                    continue
                hits["② 个人信息"].append(f"{rel}  [{label}] {redact(val)}")
        for label, rx in INTERNAL:
            for m in rx.finditer(text):
                hits["③ 内部信息"].append(f"{rel}  [{label}] {redact(m.group(0))}")

    total = 0
    for cat, items in hits.items():
        uniq = sorted(set(items))
        total += len(uniq)
        print(f"\n▸ {cat}：{len(uniq)} 处")
        for x in uniq[:15]:
            print(f"    {x}")
        if len(uniq) > 15:
            print(f"    …另有 {len(uniq) - 15} 处")

    # ④ 大文件
    print("\n▸ ④ 已跟踪大文件（> 1 MB）")
    big = []
    for rel in files:
        p = ROOT / rel
        if p.is_file():
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            if sz > 1_000_000:
                big.append((sz, rel))
    big.sort(reverse=True)
    for sz, rel in big[:12]:
        print(f"    {sz/1e6:7.2f} MB  {rel}")
    if not big:
        print("    （无）")

    print()
    print("=" * 96)
    print(f"合计命中：{total} 处（逐条人工判定后决定是否保留）")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
