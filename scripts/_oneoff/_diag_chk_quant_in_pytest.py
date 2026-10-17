# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_diag_chk_quant_in_pytest.py
"""诊断：为何 `chk_quant` 的修复在**直接跑时生效**、在 **pytest 里失效**？

## 假设
`chk_quant` 起子进程时用 `env=dict(os.environ, ...)` ⇒ **子进程继承父进程环境变量**。
pytest 会话会 import 大量模块，**其中某个在导入时调用了 `load_dotenv()`**，
把 `SEC_USER_AGENT` 灌进 `os.environ` ⇒ 测试里清空 `.env` **不再影响子进程**
⇒ 子进程仍拿到凭证 ⇒ `chk_quant` 报 PASS（**此时是对的**：凭证确实可用）。

⇒ 若成立，则**是测试缺陷**（假设「清空 .env ⇒ 凭证消失」，
   但忽略了环境变量这条路径），**不是产品 bug**。

## 判据
在「模拟 pytest 的导入环境」下，检查 `os.environ` 是否含该键。
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
    print("=" * 92)
    print("诊断：pytest 环境下 SEC_USER_AGENT 是否已被灌进 os.environ")
    print("=" * 92)

    print(f"\n① 裸解释器启动时：os.environ 含 {KEY} = {KEY in os.environ}")

    # 模拟 pytest 会话：import 一批项目模块（含可能的 load_dotenv 调用方）
    mods = ["quant.edgar_fundamentals", "quant.screener_engine", "quant.stock_pools",
            "quant.price_history", "wb_analysis._audit_values", "wb_analysis._contract"]
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:  # noqa: BLE001
            print(f"   （{m} 导入失败：{type(e).__name__}）")

    print(f"\n② import 项目模块后：os.environ 含 {KEY} = {KEY in os.environ}")
    if KEY in os.environ:
        print(f"   长度 = {len(os.environ[KEY])}（不打印值）")
        print("\n③ 结论")
        print("   ⇒ **环境变量路径存在** ⇒ 测试里清空 `.env` 不影响子进程")
        print("   ⇒ 子进程仍拿到凭证 ⇒ chk_quant 报 PASS **是正确的**")
        print("   ⇒ **这是测试缺陷**（假设不成立），不是产品 bug。")
        print("   ⇒ 修法：测试里用 monkeypatch 同时**删掉环境变量**，才能真正模拟「凭证缺失」。")
        return 2
    print("\n③ 结论：环境变量未被灌入 ⇒ 需继续查 pytest 特有点")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
