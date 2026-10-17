# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_nul_file.py
"""核实根目录 `nul` 残留是否真实存在（评估报告说"已删"、正文说"未处置"，需实测裁定）。

## 为什么要用落盘脚本
`nul` 是 **Windows 保留设备名**，读取它需要**扩展路径前缀**（`\\\\?\\`），
而该前缀含反斜杠 —— 内联进 heredoc 会被 shell 静默吞掉（本项目铁律 21/22/29）。
⇒ 凡涉反斜杠字面量，一律落盘 .py 再执行。

## 判据
- `os.listdir` / `Path.iterdir()` **都不枚举** `nul`（OS 层特例）；
- `os.path.exists('nul')` 在 Windows 上**恒为 True**（它解析成设备）⇒ **不能作存在性判据**；
- 唯一可靠判据：用扩展路径**尝试打开并读取**它 —— 能读出内容即「真实文件存在」。
"""
from __future__ import annotations

import os

BACKSLASH = chr(92)          # 避免 f-string/转义歧义
UNC_PREFIX = BACKSLASH * 2 + "?" + BACKSLASH   # \\?\  → 主机的扩展路径前缀


def main() -> int:
    print("=" * 76)
    print("核实根目录 nul 残留")
    print("=" * 76)

    print(f"os.path.exists('nul')  = {os.path.exists('nul')}   ← Windows 上恒 True，非判据")
    print(f"os.path.isfile('nul')  = {os.path.isfile('nul')}")
    try:
        print(f"'nul' in listdir('.')  = {'nul' in os.listdir('.')}   ← 不枚举（OS 特例）")
    except OSError as e:
        print(f"listdir 异常：{e}")

    target = UNC_PREFIX + os.path.abspath("nul")
    print(f"\n扩展路径：{target}")
    try:
        with open(target, "rb") as f:
            data = f.read()
        print(f"  ✓ 能打开 ⇒ **nul 作为普通文件真实存在**")
        print(f"  内容长度：{len(data)} 字节")
        print(f"  内容：{data[:120]!r}")
        return 0
    except FileNotFoundError as e:
        print(f"  · 打不开（该文件不存在）：{e}")
        return 1
    except OSError as e:
        print(f"  ⚠ 打开异常：{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
