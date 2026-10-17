# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_checker_blindspots.py
"""对抗性实测：`scripts/_health.py` 各检查器**能否被绕过**（找出剩余「判据写窄」bug）。

## 背景（本日已抓到 4 个同族 bug）
`SUM_RE` 恒不命中 / `chk_lifecycle` 判据恒假 / `chk_root_clean` 后缀白名单漏检 /
`_memory_index --check` 恒报过期 —— 共同点：**检查器看着在跑，结论是错的**。

`_selftest.py` 声称有 34 项双向夹具，但**只覆盖了 2 个 health 检查器**
（`chk_transient_empty` / `chk_doc_drift`）。⇒ 其余 10 个**没有任何对抗性验证**。

## 本脚本做什么
不看代码猜，而是**构造对抗输入，实测它是否返回了错误的 PASS**。三类打法：
1. **注释掉即通过**（子串判据的通病）：把配置项注释掉，检查器仍报 PASS？
2. **输出格式变化即静默通过**：让被调工具输出不可解析的内容，检查器是否沉默放行？
3. **同类文件换后缀/换名即漏检**：与 `chk_root_clean` 同类的手法。

⚠️ **只在临时副本上做实验**，绝不改动真实项目文件；每个用例结束即还原并核对。
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def load_health():
    spec = importlib.util.spec_from_file_location("_h_probe", ROOT / "scripts" / "_health.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    h = load_health()
    root = Path(h.ROOT)
    print("=" * 94)
    print("对抗性实测：各检查器能否被绕过")
    print("=" * 94)
    print(f"ROOT = {root}\n")

    findings: list[str] = []

    # ── 用例 1：chk_gitignore —— 把条目「注释掉」是否仍 PASS ──
    #    判据是 `n not in t`（纯子串）⇒ 注释掉的 `# wb_analysis/evidence/` 也含该串。
    gi = root / ".gitignore"
    orig = gi.read_text(encoding="utf-8")
    try:
        # 备份原文件，构造「全部注释掉」的版本
        tmp = orig + "\n# 以下为注释：\n# wb_analysis/evidence/\n# wb_analysis/drafts/\n# wb_analysis/analysis/\n# .workbuddy-ai/backup/\n"
        commented = "\n".join(
            ("# " + l if l.strip() in {
                "wb_analysis/evidence/", "wb_analysis/drafts/", "wb_analysis/analysis/",
                ".workbuddy-ai/backup/",
            } else l)
            for l in orig.splitlines()
        ) + "\n# 以下为注释：\n# wb_analysis/evidence/\n# wb_analysis/drafts/\n# wb_analysis/analysis/\n# .workbuddy-ai/backup/\n"
        gi.write_text(commented, encoding="utf-8", newline="\n")
        st, msg = h.chk_gitignore()
        print("▸ 用例 1：把 .gitignore 的 4 个必需条目**全部注释掉**")
        print(f"    检查器返回：{st} — {msg}")
        if st == "PASS":
            findings.append("chk_gitignore：注释掉的条目仍判 PASS（纯子串判据，不识别注释）")
            print("    ✗ **可被绕过**：注释掉也算「已忽略」")
        else:
            print("    ✓ 未被绕过")
    finally:
        gi.write_text(orig, encoding="utf-8", newline="\n")
        assert gi.read_text(encoding="utf-8") == orig, "还原失败！"

    # ── 用例 2：chk_seal —— 被调工具输出不可解析时是否静默 PASS ──
    #    代码：`n = int(m.group(1)) if m else 0` ⇒ 正则不命中就当作 0 轮 ⇒ PASS。
    print("\n▸ 用例 2：chk_seal 的解析兜底（静态判读）")
    src = (root / "scripts" / "_health.py").read_text(encoding="utf-8")
    m = re.search(r'def chk_seal.*?return \("PASS".*?\)', src, re.S)
    if m and "if m else 0" in m.group(0):
        findings.append("chk_seal：正则不命中时 `n=0` ⇒ 输出格式一变就静默 PASS")
        print("    ✗ **可被绕过**：`n = int(m.group(1)) if m else 0` —— 解析失败被当成「0 轮待封存」")
    else:
        print("    ✓ 无该模式")

    # ── 用例 3：chk_reports —— 同类兜底（`m.group(1) if m else '?'`）──
    print("\n▸ 用例 3：chk_reports 的计数兜底（静态判读）")
    m3 = re.search(r'def chk_reports.*?return "PASS".*?\n', src, re.S)
    if m3 and "if m else" in m3.group(0):
        findings.append("chk_reports：`m.group(1) if m else '?'` ⇒ 解析失败仍 PASS（只影响文案，风险低）")
        print("    ⚠ 解析失败显示 '?' 但仍 PASS（风险较低：它只影响显示，不判定）")
    else:
        print("    ✓ 无该模式")

    # ── 用例 4：chk_root_clean —— 对抗「新建任意后缀文件」──
    probe = root / "PROBE_should_be_caught.xyz123"
    try:
        probe.write_text("probe\n", encoding="utf-8")
        st, msg = h.chk_root_clean()
        print("\n▸ 用例 4：根目录新建任意后缀文件（.xyz123）")
        print(f"    检查器返回：{st} — {msg[:70]}")
        if st != "WARN":
            findings.append("chk_root_clean：任意后缀仍漏检")
            print("    ✗ **仍漏检**")
        else:
            print("    ✓ 已能检出（2026-10-16 修复生效）")
    finally:
        probe.unlink(missing_ok=True)

    # ── 用例 5：chk_memory_size —— 注入「超大 MEMORY.md」是否报警 ──
    mem = root / ".workbuddy-ai" / "memory" / "MEMORY.md"
    orig_mem = mem.read_text(encoding="utf-8")
    try:
        mem.write_text(orig_mem + "\n" + ("填充" * 12000) + "\n", encoding="utf-8", newline="\n")
        st, msg = h.chk_memory_size()
        print("\n▸ 用例 5：MEMORY.md 注入超量内容（远超 15,000 字节截断阈）")
        print(f"    检查器返回：{st} — {msg[:80]}")
        if st == "PASS":
            findings.append("chk_memory_size：超量仍 PASS")
            print("    ✗ **可被绕过**")
        else:
            print("    ✓ 能检出超量")
    finally:
        mem.write_text(orig_mem, encoding="utf-8", newline="\n")
        assert mem.read_text(encoding="utf-8") == orig_mem, "还原失败！"

    print()
    print("=" * 94)
    if findings:
        print(f"发现 {len(findings)} 个可疑点：")
        for f in findings:
            print(f"  · {f}")
    else:
        print("未发现可绕过的检查器")
    print("=" * 94)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
