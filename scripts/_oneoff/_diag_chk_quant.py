# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_diag_chk_quant.py
"""查清：`chk_quant` 在 `.env` 被清空后仍 PASS —— 是产品 bug，还是**我的探针有缺陷**？

## 假设
`_health.py`（或它 import 的模块）在**导入时**调用了 `load_dotenv()`，
把 `SEC_USER_AGENT` 灌进了**父进程的 `os.environ`**。
于是 `chk_quant` 起子进程时（`env=dict(os.environ, ...)`）子进程**继承**了该变量
⇒ **清空 `.env` 对它无效** ⇒ 看起来像"假绿"，实为**探针缺陷**。

## 判据
导入 `_health` **前后**，`os.environ` 里该键的存在状态变化。
⚠️ 只打印「是否存在 / 长度」，**绝不打印真实值**（凭据不外泄）。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

KEY = "SEC_USER_AGENT"


def main() -> int:
    print("=" * 88)
    print("诊断：chk_quant 的 .env 注入为何无效")
    print("=" * 88)

    print("\n① 导入 _health **之前**")
    print(f"   os.environ 含 {KEY}: {KEY in os.environ}")

    spec = importlib.util.spec_from_file_location("_h_dbg", ROOT / "scripts" / "_health.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    print("\n② 导入 _health **之后**")
    present = KEY in os.environ
    print(f"   os.environ 含 {KEY}: {present}")
    if present:
        print(f"   长度: {len(os.environ[KEY])}（不打印值）")

    print("\n③ 结论")
    if present:
        print("   ⇒ 导入期已把凭证灌进 os.environ")
        print("   ⇒ chk_quant 的子进程会**继承**它 ⇒ 清空 .env 对该检查无效")
        print("   ⇒ 这是**我的探针缺陷**（测的是「环境变量已存在」场景），")
        print("     **不是 chk_quant 的产品 bug** —— 要真测它，必须同时清掉环境变量。")
        return 2
    print("   ⇒ 导入期未灌入 ⇒ 需继续查 chk_quant 本身")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
