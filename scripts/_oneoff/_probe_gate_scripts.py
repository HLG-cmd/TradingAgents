# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_gate_scripts.py
"""对抗性实测：`wb_analysis/` 下**无测试覆盖**的门禁脚本能否被绕过。

## 覆盖对象（实测确认「无测试」的判据入口）
| 脚本 | 职责 | 假绿后果 |
|---|---|---|
| `_lint_drafts.py` | 契约合规 | 违规草稿流入交付 |
| `_verify_ratings.py` | 评级词位置 | 评级被误读 |
| `_verify_report.py` | 渲染树反读 | 报告不可被解析器消费 |
| `_check_freshness.py` | 时序新鲜度 | 陈旧数据冒充当日 |
| `_check_role_files.py` | 12 角色文件完整性 | 缺件不被发现 |
| `_scorecard.py` | 质量记分 | 退化不可见 |

## 判据（统一）
对每个脚本构造「**应该非零退出**」的坏输入。若它 `return 0` ⇒ **假绿（真 bug）**。

## 手法
用 `tmp_path` 造最小夹具（**不碰真实报告树/草稿**），跑脚本，比对退出码。
⚠️ 脚本可能需要真实项目环境（cwd/依赖）⇒ 一律用**项目 `.venv` + cwd=项目根**执行。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(args: list[str], timeout: int = 180) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       cwd=str(ROOT), timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    rows: list[tuple[str, str, int, bool]] = []

    def rec(script: str, scene: str, rc: int, suspicious: bool, note: str = "") -> None:
        rows.append((script, scene, rc, suspicious))
        flag = "✗ 可疑" if suspicious else "✓"
        print(f"  {flag} {script:26s} {scene:36s} rc={rc} {note}")

    print("=" * 100)
    print("对抗性实测：无测试覆盖的门禁脚本")
    print("=" * 100)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # ── ① _verify_ratings：空目录（应报缺件 → 非零）──
        print("\n▸ _verify_ratings.py")
        empty = tmp / "empty_draft"
        empty.mkdir()
        rc, out = run([PY, str(ROOT / "wb_analysis" / "_verify_ratings.py"), str(empty)])
        rec("_verify_ratings", "空草稿目录（应报缺 12 角色）", rc, rc == 0,
            "← 空目录竟判通过" if rc == 0 else "")

        # ── ② _check_role_files：空目录 ──
        print("\n▸ _check_role_files.py")
        rc2, out2 = run([PY, str(ROOT / "wb_analysis" / "_check_role_files.py"), str(empty)])
        rec("_check_role_files", "空草稿目录", rc2, rc2 == 0 if rc2 == 0 else False,
            "（该脚本可能默认扫全库，非目录参数）")

        # ── ③ _verify_report：不存在的树 ──
        print("\n▸ _verify_report.py")
        rc3, out3 = run([PY, str(ROOT / "wb_analysis" / "_verify_report.py"), str(tmp / "nope")])
        rec("_verify_report", "不存在的报告树", rc3, rc3 == 0,
            "← 不存在竟判通过" if rc3 == 0 else "")

        # ── ④ _lint_drafts：空目录 ──
        print("\n▸ _lint_drafts.py")
        rc4, out4 = run([PY, str(ROOT / "wb_analysis" / "_lint_drafts.py"), str(empty)])
        rec("_lint_drafts", "空草稿目录", rc4, rc4 == 0,
            "← 空目录竟判无违规" if rc4 == 0 else "")

        # ── ⑤ _check_freshness：空目录 ──
        print("\n▸ _check_freshness.py")
        rc5, out5 = run([PY, str(ROOT / "wb_analysis" / "_check_freshness.py"), str(empty)])
        rec("_check_freshness", "空草稿目录", rc5, rc5 == 0,
            "← 空目录竟判新鲜" if rc5 == 0 else "")

    # ── ⑥ _scorecard：只读工具，跑一次看是否异常 ──
    print("\n▸ _scorecard.py")
    rc6, out6 = run([PY, str(ROOT / "wb_analysis" / "_scorecard.py")])
    rec("_scorecard", "真实状态（基线）", rc6, False)

    print()
    print("=" * 100)
    susp = [r for r in rows if r[3]]
    print(f"共测 {len(rows)} 项；**可疑（假绿）{len(susp)} 项**")
    for s, scene, rc, _ in susp:
        print(f"  ✗ {s}：{scene} → rc={rc}")
    if not susp:
        print("  ✓ 未发现新的假绿")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
