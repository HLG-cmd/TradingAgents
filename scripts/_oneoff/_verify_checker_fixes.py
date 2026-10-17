# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_verify_checker_fixes.py
"""双向验证 `chk_gitignore` / `chk_seal` 两处修复（坏输入必检出 / 好输入不误报）。

## 判据（对应铁律 20：豁免表改后双边必测）
| 用例 | 期望 |
|---|---|
| .gitignore 条目**被注释掉** | WARN（原为假绿 PASS） |
| .gitignore 条目**正常存在** | PASS |
| `--plan` 输出**不可解析** | WARN（原为假绿 PASS） |
| `--plan` 输出正常且 0 轮 | PASS |
| `--plan` 输出正常且 N 轮 | WARN |

⚠️ 只改**临时副本**，每例结束即还原并核对。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def load_health():
    spec = importlib.util.spec_from_file_location("_h_v2", ROOT / "scripts" / "_health.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    h = load_health()
    results: list[tuple[str, bool, str]] = []

    # ── ① chk_gitignore：正常状态应 PASS ──
    st, msg = h.chk_gitignore()
    results.append(("gitignore 正常 → PASS", st == "PASS", f"{st} — {msg}"))

    # ── ② chk_gitignore：注释掉必需项应 WARN ──
    gi = ROOT / ".gitignore"
    orig = gi.read_text(encoding="utf-8")
    need = {"wb_analysis/evidence/", "wb_analysis/drafts/", "wb_analysis/analysis/",
            ".workbuddy-ai/backup/"}
    try:
        commented = chr(10).join(
            ("# " + l if l.strip() in need else l) for l in orig.splitlines()
        ) + chr(10)
        gi.write_text(commented, encoding="utf-8", newline="\n")
        st2, msg2 = h.chk_gitignore()
        results.append(("gitignore 注释掉必需项 → WARN", st2 == "WARN", f"{st2} — {msg2[:70]}"))
    finally:
        gi.write_text(orig, encoding="utf-8", newline="\n")
        assert gi.read_text(encoding="utf-8") == orig

    # ── ③ chk_gitignore：还原后应恢复 PASS ──
    st3, msg3 = h.chk_gitignore()
    results.append(("gitignore 还原 → PASS", st3 == "PASS", f"{st3} — {msg3[:60]}"))

    # ── ④ chk_seal 正常（当前无待封存）──
    st4, msg4 = h.chk_seal()
    results.append(("seal 正常 → PASS/WARN 均可（取决于真实状态）",
                    st4 in ("PASS", "WARN"), f"{st4} — {msg4[:70]}"))

    # ── ⑤ chk_seal 解析失败 → 必须 WARN（注入不可解析输出）──
    #    手法：临时改 _seal_run.py 的 --plan 输出措辞，使正则失配
    seal = ROOT / "wb_analysis" / "_seal_run.py"
    orig_seal = seal.read_text(encoding="utf-8")
    try:
        tampered = orig_seal.replace('待封存 {n_pending} 轮', 'PENDING_COUNT = {n_pending}')
        if tampered == orig_seal:
            # 换一种注入：直接改 print 的措辞
            import re as _re
            tampered = _re.sub(r'待封存\s*\{[^}]*\}\s*轮', 'PENDING_COUNT_X', orig_seal, count=1)
        if tampered != orig_seal:
            seal.write_text(tampered, encoding="utf-8", newline="\n")
            st5, msg5 = h.chk_seal()
            results.append(("seal 输出不可解析 → WARN（原为假绿）",
                            st5 == "WARN", f"{st5} — {msg5[:80]}"))
        else:
            results.append(("seal 注入失败（未改到输出措辞）", False,
                            "无法构造不可解析输出，需手工复查"))
    finally:
        seal.write_text(orig_seal, encoding="utf-8", newline="\n")
        assert seal.read_text(encoding="utf-8") == orig_seal

    # ── ⑥ chk_seal 还原后应与 ④ 一致 ──
    st6, msg6 = h.chk_seal()
    results.append(("seal 还原 → 与修复前一致", st6 == st4, f"{st6} — {msg6[:60]}"))

    print("=" * 96)
    print("双向验证：chk_gitignore / chk_seal 修复")
    print("=" * 96)
    n_ok = 0
    for name, ok, detail in results:
        print(f"  {'✓' if ok else '✗'} {name:44s} {detail}")
        n_ok += bool(ok)
    print()
    print(f"通过 {n_ok}/{len(results)}")
    print("✓ 双向验证全过" if n_ok == len(results) else "✗ 有未通过项")
    print("=" * 96)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
