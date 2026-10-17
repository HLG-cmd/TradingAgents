# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_probe_checker_blindspots2.py
"""对抗性实测（第二轮）：覆盖第一轮没打的检查器。

## 本轮要打的（全部**静态判读 + 动态注入**双路）
- `chk_reports`：`_reports_index.py --check` 的输出格式变了会怎样？
- `chk_tests`：pytest 汇总行缺失时是否静默 PASS？
- `chk_lifecycle`：`_tidy_scripts.py --check` 的解析兜底。
- `chk_doc_drift`：已由 `_selftest` 覆盖（跳过）。
- `chk_memory_size`：第二轮已验（能检出超量）。
- `chk_scorecard` / `chk_disk_budget` / `chk_quant` / `chk_selftest`：静态判读。

判据统一：**解析失败 / 工具崩溃 / 输出格式变化时，检查器是否会给出「假绿 PASS」**。
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def load_health():
    spec = importlib.util.spec_from_file_location("_h_probe2", ROOT / "scripts" / "_health.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


#: 「解析失败 → 默认值」的可疑模式（这些地方失败会被当成正常）
FALLBACK_PATTERNS = [
    (r"if\s+m\s+else\s+0\b", "正则失配默认成 0（可能被当成『无问题』）"),
    (r"if\s+m\s+else\s+'?'", "正则失配默认成 '?'（仅影响文案）"),
    (r"if\s+not\s+m\s*:", "正则失配走某分支（需看该分支判定）"),
    (r"\.get\(\s*[\"'][^\"']+[\"']\s*,\s*0\s*\)", "dict 取值默认 0"),
    (r"except\s+.*:\s*$", "裸 except（可能吞掉失败）"),
]


def main() -> int:
    h = load_health()
    src = (ROOT / "scripts" / "_health.py").read_text(encoding="utf-8")

    print("=" * 96)
    print("对抗性排查（第二轮）：解析兜底模式 + 动态注入")
    print("=" * 96)

    # ── 静态：把每个 chk_ 函数切出来，找「解析失败 → 默认值」模式 ──
    funcs = re.split(r"^def (chk_\w+)", src, flags=re.M)
    findings: list[str] = []
    print("\n▸ 各检查器的「解析失败兜底」扫描")
    for i in range(1, len(funcs), 2):
        name, body = funcs[i], funcs[i + 1]
        # 只取函数体（到下一个顶层 def 之前已由 split 保证）
        hits = []
        for pat, desc in FALLBACK_PATTERNS:
            if re.search(pat, body, re.M):
                hits.append(desc)
        if hits:
            print(f"  · {name:26s} {len(hits)} 处：" + "；".join(hits))
            for d in hits:
                findings.append(f"{name}: {d}")

    # ── 动态：注入「工具崩溃」场景，看各检查器是否假绿 ──
    print("\n▸ 动态注入：让被调工具返回不可解析输出")
    # chk_reports 依赖 _reports_index.py 的输出里有「报告树 N 棵」
    #   ⇒ 若输出变了，n==0 分支会走 `m.group(1) if m else '?'`，但仍返回 PASS
    idx = ROOT / "wb_analysis" / "_reports_index.py"
    orig_idx = idx.read_text(encoding="utf-8")
    try:
        tampered = re.sub(r"报告树\s*\{[^}]*\}\s*棵", "TREES_X", orig_idx, count=1)
        if tampered != orig_idx:
            idx.write_text(tampered, encoding="utf-8", newline="\n")
            st, msg = h.chk_reports()
            print(f"    chk_reports（注入后）：{st} — {msg[:74]}")
            if st == "PASS":
                findings.append("chk_reports: 解析失配仍 PASS（文案显示 '?'）")
        else:
            print("    chk_reports：未能注入（输出措辞未匹配）")
    finally:
        idx.write_text(orig_idx, encoding="utf-8", newline="\n")
        assert idx.read_text(encoding="utf-8") == orig_idx

    # chk_lifecycle：让 _tidy_scripts 输出不含「全部 N 个脚本」
    print("\n▸ chk_lifecycle 的解析兜底（静态确认）")
    m = re.search(r"def chk_lifecycle.*?return \"PASS\".*?\n", src, re.S)
    if m and ("if m else" in m.group(0)):
        findings.append("chk_lifecycle: 计数解析失败仍 PASS（但 rc 是主判据，风险低）")
        print("    ⚠ 计数解析失配仍 PASS —— 但主判据是 rc（退出码），风险较低")
    else:
        print("    ✓ 主判据为 rc，无解析假绿")

    print()
    print("=" * 96)
    print(f"共 {len(findings)} 条记录")
    for f in findings:
        print(f"  · {f}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
