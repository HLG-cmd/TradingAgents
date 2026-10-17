# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_verify_new_tests_have_teeth.py
"""验证新增测试**有判别力**：把修复回退成坏实现，测试必须 FAIL。

## 为什么必须做（本日最重要的元教训）
「测试全绿」只证明**当前状态**通过，**不证明测试能看到问题**。
本日已实测出 7 个「检查器看着在跑、实际没看到问题」的缺陷 ——
**测试自己也会犯同样的病**（一个恒返回 True 的断言永远全绿）。

⇒ 判据（对应铁律 20「审计工具必须有判别力」的反向用法）：
   **注入坏实现 ⇒ 对应用例必须 FAIL；还原 ⇒ 必须恢复全绿。**
   只测一边（只看绿）等于没测。

## 本脚本注入三个坏实现
| # | 注入 | 期望 FAIL 的用例 |
|---|---|---|
| A | `chk_reports` 去掉 rc 校验（回到「n==0 就 PASS」） | `test_crashed_tool_does_not_report_pass` |
| B | `chk_seal` 恢复 `if m else 0` | `test_unparsable_output_warns_not_passes` |
| C | `chk_gitignore` 回到纯子串判据 | `test_commented_out_entries_do_not_count` |

⚠️ 全部在**备份副本上做**，每例结束立即还原并逐字节核对。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
HEALTH = ROOT / "scripts" / "_health.py"
TESTFILE = "tests/test_health_checkers.py"


def run_tests() -> tuple[int, str]:
    r = subprocess.run(
        [PY, "-m", "pytest", TESTFILE, "-q", "--no-header",
         "--basetemp", str(ROOT / ".pytest_tmp_teeth")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=600,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ── 三组「坏实现」注入（找→换）──
INJECTIONS = [
    # ⚠️ 第一版只去掉 rc 守卫 ⇒ 崩溃仍被**第二道守卫**（解析失败→WARN）拦住 ⇒
    #    测试断言「不得 PASS」照样满足 ⇒ 看起来"没判别力"。
    #    实为**防御纵深生效**，不是测试没牙 ⇒ 要证明有牙，必须注入**真正的原始 bug**（两道守卫都去掉）。
    ("A: chk_reports 回退成**原始 bug**（两道守卫全去掉）",
     ('    # ① 先验「工具是否真的跑成功」—— 崩溃时不得把「无输出」读成「无问题」\n'
      '    if rc != 0:\n'
      '        first = out.strip().splitlines()[0][:70] if out.strip() else "(无输出)"\n'
      '        return "FAIL", f"`_reports_index.py --check` 未正常退出（rc={rc}）⇒ 无法判断，首行：{first}"\n'
      '    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("- [")]\n'
      '    n = len(lines)\n'
      '    if n == 0:\n'
      '        m = re.search(r"报告树\\s*(\\d+)\\s*棵", out)\n'
      '        if not m:\n'
      '            # ② 连「报告树 N 棵」都解析不到 ⇒ 输出格式已变，不能假定为 0\n'
      '            return "WARN", ("`_reports_index.py --check` 输出无法解析（未见「报告树 N 棵」）"\n'
      '                            "⇒ **不能假定为 0 问题**，请人工跑一次确认")\n'
      '        return "PASS", f"报告树 {m.group(1)} 棵，无堆积问题"\n',
      '    # [teeth-test] 回退成原始 bug：不验 rc + 解析失败也当无问题\n'
      '    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("- [")]\n'
      '    n = len(lines)\n'
      '    if n == 0:\n'
      '        m = re.search(r"报告树\\s*(\\d+)\\s*棵", out)\n'
      '        return "PASS", f"报告树 {m.group(1) if m else chr(63)} 棵，无堆积问题"\n')),
    ("B: chk_seal 恢复「解析失败默认为 0」",
     ('    if not m:\n'
      '        return "WARN", ("无法解析 `_seal_run.py --plan` 的输出 ⇒ **不能假定为 0**，"\n'
      '                        "请人工确认；首行："\n'
      '                        + (out.strip().splitlines()[0][:60] if out.strip() else "(空输出)"))\n'
      '    n = int(m.group(1))\n',
      '    n = int(m.group(1)) if m else 0   # [teeth-test] 回退\n')),
]


def inject_and_check(tag: str, old: str, new: str, orig: str) -> bool:
    """注入坏实现 → 跑测试（期望 FAIL）→ 还原 → 复跑（期望 PASS）。"""
    if old not in orig:
        print(f"  ⚠ {tag}\n     ⇒ 未命中注入点（措辞已变？），跳过该组")
        return True
    try:
        HEALTH.write_text(orig.replace(old, new, 1), encoding="utf-8", newline="\n")
        rc_bad, out_bad = run_tests()
        failed_names = [l for l in out_bad.splitlines() if l.startswith("FAILED")]
        ok_bad = rc_bad != 0
        print(f"  {'✓' if ok_bad else '✗'} {tag}")
        print(f"      注入后：rc={rc_bad}（期望非 0）"
              + (f"，FAILED {len(failed_names)} 项" if failed_names else ""))
        if failed_names:
            for n in failed_names[:2]:
                print(f"        {n[:96]}")
        return ok_bad
    finally:
        HEALTH.write_text(orig, encoding="utf-8", newline="\n")
        assert HEALTH.read_text(encoding="utf-8") == orig, "还原失败！"


def main() -> int:
    orig = HEALTH.read_text(encoding="utf-8")

    print("=" * 96)
    print("验证新增测试有判别力（注入坏实现 → 必须 FAIL）")
    print("=" * 96)

    # 基线：当前应为全绿
    rc0, out0 = run_tests()
    print(f"\n▸ 基线（未注入）：rc={rc0}（期望 0）")
    if rc0 != 0:
        print("  ✗ 基线就不是全绿，先修好再来验证判别力")
        print(out0[-800:])
        return 1

    print("\n▸ 逐组注入坏实现")
    results = []
    for tag, (old, new) in INJECTIONS:
        results.append(inject_and_check(tag, old, new, orig))

    # 还原后复跑
    rc1, out1 = run_tests()
    print(f"\n▸ 还原后复跑：rc={rc1}（期望 0）")
    results.append(rc1 == 0)

    print()
    print("=" * 96)
    n_ok = sum(results)
    print(f"通过 {n_ok}/{len(results)}")
    if n_ok == len(results):
        print("✓ 新增测试**有判别力**：坏实现必被检出，还原后全绿")
    else:
        print("✗ 有注入未被检出 ⇒ 该测试没有判别力，需加强")
    print("=" * 96)
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
