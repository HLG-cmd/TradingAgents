# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_chk_quant_token.py
"""修 `chk_quant` 的**假绿**（本日第 8 例，已精确复现）。

## 复现（实测，`.env` 清空后）
```
子进程 rc = 1                     ← 断言失败（凭证缺失）
输出含 Traceback
但 `'OK' in out` → True           ← 判据被**源码回显**骗了
chk_quant() → PASS：「自建包可导入，且 .env 凭证读取正常」
```

## 根因
判据是 `if "OK" in out`，而被执行代码的最后一句是 `print('OK')`。
**Python 断言失败时，traceback 会回显整行源码** —— 那行源码里就含 `print('OK')`
⇒ 子串命中 ⇒ **失败被读成成功**。

## 为什么这条特别严重
它是**凭证检查**：`SEC_USER_AGENT` 缺失时本应报警（否则 EDGAR 会 403），
假绿意味着「体检说凭证正常，实际抓取全失败」——正是铁律 3「静默失败」的典型。

## 修法
**先验 rc，再看输出**（与第 7 例同一手法）。
并补一条**结构性防护**：把成功标记改成**不会出现在源码回显里**的形式 ——
即让 `print` 的**字面量**与判据用的子串**不同形**（源码回显的是 `print('OK')`，
判据改查一个只在**运行时**才产生、源码里不出现的串）。
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "scripts" / "_health.py"
BACKUP = ROOT / ".workbuddy-ai" / "backup" / "PRE_fix_chk_quant_token_20261016.py"

OLD = '''    code = ("import sys; sys.path.insert(0, r'%s');"
            "from quant import screener_engine, stock_pools, edgar_fundamentals, price_history;"
            "ua = edgar_fundamentals.SEC_USER_AGENT;"
            "assert '@' in ua and 'admin@example.com' not in ua, f'SEC 凭证未配置或为默认占位符: {ua}';"
            "print('OK')" % str(ROOT))
    rc, out = run([PY, "-c", code])
    if "OK" in out:
        return "PASS", "自建包可导入，且 .env 凭证读取正常"
    if "No module named" in out or "ModuleNotFoundError" in out:
        mod = out.strip().splitlines()[-1]
        return "WARN", f"当前解释器缺运行依赖（{mod}）⇒ 请用项目 .venv 运行"
    return "FAIL", f"自建包或凭证异常：{out.strip().splitlines()[-1][:70] if out.strip() else rc}"'''

NEW = '''    # ★★ 2026-10-16 修（本日第 8 例「检查器判据缺陷」，**已精确复现**）：
    #   原判据是 `if "OK" in out`，而被执行代码末句是 `print('OK')`。
    #   **断言失败时 traceback 会回显整行源码**，那行里就含 `print('OK')`
    #   ⇒ 子串命中 ⇒ 实测「`.env` 清空（凭证失效）时仍报 PASS」= **假绿**。
    #   这是**凭证检查**，假绿意味着「体检说凭证正常、实际 EDGAR 会 403」——
    #   铁律 3「静默失败」的典型。
    #   ⇒ 两条修法：① **先验 rc**（真正的判据是退出码，不是输出里有无某串）；
    #     ② 成功标记改成**源码回显里不出现**的形式（见 `_MARK`：它由 chr() 拼出，
    #        源码里没有该字面量 ⇒ 失败回显时不会误命中）。
    _MARK = chr(79) + chr(75)   # == "OK"，但源码中无此字面量
    code = ("import sys; sys.path.insert(0, r'%s');"
            "from quant import screener_engine, stock_pools, edgar_fundamentals, price_history;"
            "ua = edgar_fundamentals.SEC_USER_AGENT;"
            "assert '@' in ua and 'admin@example.com' not in ua, f'SEC 凭证未配置或为默认占位符: {ua}';"
            "print(%r)" % (str(ROOT), _MARK))
    rc, out = run([PY, "-c", code])
    if rc == 0 and _MARK in out:
        return "PASS", "自建包可导入，且 .env 凭证读取正常"
    if "No module named" in out or "ModuleNotFoundError" in out:
        mod = out.strip().splitlines()[-1]
        return "WARN", f"当前解释器缺运行依赖（{mod}）⇒ 请用项目 .venv 运行"
    first = out.strip().splitlines()[-1][:70] if out.strip() else f"(无输出, rc={rc})"
    return "FAIL", f"自建包或凭证异常（rc={rc}）：{first}"'''

EDITS = [("chk_quant：先验 rc + 成功标记不在源码回显中出现", OLD, NEW)]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "_MARK = chr(79)" in src:
        print("  · 已修过（幂等跳过）")
        return 0

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    print(f"  ↺ 已备份 → {BACKUP.name}")

    for tag, old, new in EDITS:
        if old not in src:
            print(f"  ✗ 未命中：{tag}")
            print("     ⇒ 未做任何写入")
            return 1
        src = src.replace(old, new, 1)
        print(f"  ✓ {tag}")

    try:
        ast.parse(src)
    except SyntaxError as e:
        print(f"  ✗ ast 校验失败，未落盘：{e}")
        return 1
    TARGET.write_text(src, encoding="utf-8", newline="\n")
    print("  ✓ ast 校验通过，已落盘")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
