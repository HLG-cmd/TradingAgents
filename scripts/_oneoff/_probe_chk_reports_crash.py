# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_chk_reports_crash.py
"""关键一测：`chk_reports` 在被调工具**完全崩溃**时，会不会假绿？

## 为什么这测值得单独做
`chk_reports` 的判定逻辑是：
```python
lines = [含 "- [" 的行]          # 这些是「卫生问题」条目
n = len(lines)
if n == 0:
    m = re.search(r"报告树 (\\d+) 棵", out)
    return "PASS", f"报告树 {m.group(1) if m else '?'} 棵，无堆积问题"
```
⇒ **`n == 0` 既可能是「真的没问题」，也可能是「工具崩了、一条都没输出」** ——
两者在判据上不可区分 ⇒ 若工具崩溃，检查器照报 PASS（**假绿**，与铁律 3 同族）。

## 本测怎么做
把 `_reports_index.py` 临时替换成「立刻崩溃 + 输出垃圾」的桩，
跑 `chk_reports()`，看它返回什么。结束即还原并逐字节核对。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def load_health():
    spec = importlib.util.spec_from_file_location("_h3", ROOT / "scripts" / "_health.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


STUB = """# lifecycle: oneoff
import sys
print("Traceback (most recent call last):")
print("  RuntimeError: 模拟工具崩溃")
sys.exit(3)
"""


def main() -> int:
    h = load_health()
    idx = ROOT / "wb_analysis" / "_reports_index.py"
    orig = idx.read_text(encoding="utf-8")

    print("=" * 92)
    print("关键一测：被调工具完全崩溃时，chk_reports 是否假绿")
    print("=" * 92)

    try:
        # ① 先看正常状态
        st0, msg0 = h.chk_reports()
        print(f"\n▸ 正常状态：{st0} — {msg0[:76]}")

        # ② 注入「崩溃桩」
        idx.write_text(STUB, encoding="utf-8", newline="\n")
        st1, msg1 = h.chk_reports()
        print(f"\n▸ 工具崩溃（exit 3 + 垃圾输出）：{st1} — {msg1[:76]}")

        verdict_real = st1 in ("FAIL", "WARN")
        if st1 == "PASS":
            print("   ✗ **假绿确认**：工具崩溃，检查器仍报 PASS")
        else:
            print(f"   ✓ 未假绿（返回 {st1}）")

    finally:
        idx.write_text(orig, encoding="utf-8", newline="\n")
        assert idx.read_text(encoding="utf-8") == orig, "还原失败！"
        print("\n（_reports_index.py 已还原并逐字节核对）")

    # ③ 还原后复跑，确认恢复
    st2, msg2 = h.chk_reports()
    print(f"\n▸ 还原后：{st2} — {msg2[:76]}")
    ok = (st2 == st0)

    print()
    print("=" * 92)
    print(f"结论：崩溃时{'假绿 ✗' if st1 == 'PASS' else '不假绿 ✓'}；还原后一致 {'✓' if ok else '✗'}")
    print("=" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
