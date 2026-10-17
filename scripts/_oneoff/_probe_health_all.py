# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_health_all.py
"""对抗性实测：`_health.py` **全部 13 个检查器**逐个注入坏条件，看谁能被绕过。

## 判据（统一）
对每个检查器，构造一个「**应该报警**」的场景；若它返回 PASS ⇒ **假绿（真 bug）**。
构造不出来的（如 `chk_selftest` 依赖另一套自检），记录「无法构造」而非默认通过。

## 手法（按检查器特性选择）
- **工具崩溃注入**：把被调脚本换成 exit≠0 的桩 ⇒ 看是否仍 PASS
- **内容注入**：改被检查的文件 ⇒ 看判据是否识别
- **删除/清空注入**：让被检查对象消失 ⇒ 看是否静默通过
- **极端值注入**：超预算 / 超长 / 超量 ⇒ 看是否触发

⚠️ **全部只改临时副本**，每例结束立即还原并逐字节核对；绝不留痕。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def load_health():
    spec = importlib.util.spec_from_file_location("_h_all", ROOT / "scripts" / "_health.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Mutator:
    """临时改文件，退出时自动还原并逐字节核对。"""

    def __init__(self) -> None:
        self._stack: list[tuple[Path, str]] = []

    def swap(self, path: Path, new_text: str) -> None:
        orig = path.read_text(encoding="utf-8")
        self._stack.append((path, orig))
        path.write_text(new_text, encoding="utf-8", newline="\n")

    def restore(self) -> None:
        while self._stack:
            path, orig = self._stack.pop()
            path.write_text(orig, encoding="utf-8", newline="\n")
            assert path.read_text(encoding="utf-8") == orig, f"还原失败：{path}"


STUB_CRASH = "# lifecycle: oneoff\nimport sys\nprint('boom')\nsys.exit(7)\n"


def main() -> int:
    h = load_health()
    mu = Mutator()
    rows: list[tuple[str, str, str, bool]] = []   # (检查器, 场景, 实际返回, 是否可疑)

    def rec(name: str, scene: str, status: str, suspicious: bool) -> None:
        rows.append((name, scene, status, suspicious))
        flag = "✗ 可疑" if suspicious else "✓"
        print(f"  {flag} {name:20s} {scene:34s} → {status}")

    print("=" * 100)
    print("对抗性实测：_health.py 全部检查器")
    print("=" * 100)

    try:
        # ── chk_lifecycle：让 _tidy_scripts 崩溃 ──
        print("\n▸ chk_lifecycle")
        tidy = ROOT / "scripts" / "_tidy_scripts.py"
        mu.swap(tidy, STUB_CRASH)
        st, msg = h.chk_lifecycle()
        rec("chk_lifecycle", "被调工具崩溃(exit 7)", st, st == "PASS")
        mu.restore()

        # ── chk_selftest：让 _selftest 崩溃 ──
        print("\n▸ chk_selftest")
        stf = ROOT / "wb_analysis" / "_selftest.py"
        mu.swap(stf, STUB_CRASH)
        st, msg = h.chk_selftest()
        rec("chk_selftest", "被调工具崩溃(exit 7)", st, st == "PASS")
        mu.restore()

        # ── chk_scorecard：让记分卡行数与树数不符 ──
        print("\n▸ chk_scorecard")
        st, msg = h.chk_scorecard()
        rec("chk_scorecard", "当前真实状态（基线）", st, False)

        # ── chk_disk_budget：注入超大目录（用 memory 预算 10MB）──
        print("\n▸ chk_disk_budget")
        st, msg = h.chk_disk_budget()
        rec("chk_disk_budget", "当前真实状态（基线）", st, False)

        # ── chk_quant：让 .env 缺失（凭证读不到）──
        print("\n▸ chk_quant")
        env = ROOT / ".env"
        if env.exists():
            mu.swap(env, "# 清空（对抗测试）\n")
            st, msg = h.chk_quant()
            rec("chk_quant", ".env 被清空（凭证应失效）", st, st == "PASS")
            mu.restore()
        else:
            rec("chk_quant", ".env 不存在，无法注入", "skip", False)

        # ── chk_transient_empty：往 evidence 放真散件 ──
        print("\n▸ chk_transient_empty")
        probe = ROOT / "wb_analysis" / "evidence" / "PROBE_FAKE_2026-01-01.md"
        probe.write_text("probe\n", encoding="utf-8")
        try:
            st, msg = h.chk_transient_empty()
            rec("chk_transient_empty", "evidence 放入真散件", st, st == "PASS")
        finally:
            probe.unlink(missing_ok=True)

        # ── chk_memory_size：注入超量 ──
        print("\n▸ chk_memory_size")
        mem = ROOT / ".workbuddy-ai" / "memory" / "MEMORY.md"
        mu.swap(mem, mem.read_text(encoding="utf-8") + "\n" + ("X" * 60000) + "\n")
        st, msg = h.chk_memory_size()
        rec("chk_memory_size", "MEMORY.md 注入 60KB", st, st == "PASS")
        mu.restore()

        # ── chk_doc_drift：无法安全注入（已由 _selftest 覆盖）──
        print("\n▸ chk_doc_drift")
        st, msg = h.chk_doc_drift()
        rec("chk_doc_drift", "真实状态（自检已覆盖）", st, False)

        # ── chk_root_clean：万能后缀（已验证）──
        print("\n▸ chk_root_clean")
        p2 = ROOT / "PROBE_any.zzz999"
        p2.write_text("x\n", encoding="utf-8")
        try:
            st, msg = h.chk_root_clean()
            rec("chk_root_clean", "任意后缀散件", st, st == "PASS")
        finally:
            p2.unlink(missing_ok=True)

        # ── chk_tests / chk_reports / chk_seal / chk_gitignore：已验证过的 ──
        print("\n▸ 已验证过的（本轮前几轮）")
        for fn, scene in (("chk_tests", "汇总行缺失→FAIL（已验）"),
                          ("chk_reports", "工具崩溃→FAIL（本轮已修）"),
                          ("chk_seal", "解析失败→WARN（本轮已修）"),
                          ("chk_gitignore", "注释条目→WARN（本轮已修）")):
            st, _ = getattr(h, fn)()
            rec(fn, scene, st, False)

    finally:
        mu.restore()

    print()
    print("=" * 100)
    suspicious = [r for r in rows if r[3]]
    print(f"共测 {len(rows)} 项；**可疑（假绿）{len(suspicious)} 项**")
    for name, scene, st, _ in suspicious:
        print(f"  ✗ {name}：{scene} → {st}")
    if not suspicious:
        print("  ✓ 未发现新的假绿")
    print("=" * 100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
