#!/usr/bin/env python
# lifecycle: maintenance
"""治理落地总执行器（默认干跑）。

一条命令完成五件事：
  1. 补 lifecycle 头（_clock / _log / _net / _codemod_clock）
  2. 收敛 pyproject.toml（依赖精简 / ruff 解除排除 / BLE / coverage 配置）
  3. .gitignore 追加忽略块（幂等，带 marker）
  4. 跑时钟 codemod（内部调用 scripts/_codemod_clock.py --apply）
  5. 按实际残留收紧 tests/test_no_naive_clock.py 的 KNOWN_FILES

用法：
    ./.venv/Scripts/python.exe scripts/_apply_governance.py            # 干跑，只看不改
    ./.venv/Scripts/python.exe scripts/_apply_governance.py --apply    # 真正写入

原子性：本脚本自己的文件改动（1/2/3/5）全部先在内存算完并通过校验后才落盘；
codemod（4）先跑，它失败则本脚本不写任何其它文件——不会再留下半完成状态。
读写保留原文件换行风格（CRLF/LF 不被改写）。
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
GITIGNORE = ROOT / ".gitignore"
GUARD = ROOT / "tests" / "test_no_naive_clock.py"
CODEMOD = ROOT / "scripts" / "_codemod_clock.py"

LIFECYCLE = {
    "wb_analysis/_clock.py": "reusable",
    "wb_analysis/_log.py": "reusable",
    "wb_analysis/_net.py": "reusable",
    "scripts/_codemod_clock.py": "maintenance",
}

GITIGNORE_MARKER = "# --- governance: 一次性脚本与数据快照 ---"
GITIGNORE_BLOCK = (
    GITIGNORE_MARKER + "\n"
    "scripts/_oneoff/\n"
    "wb_analysis/_oneoff/\n"
    "scripts/*.csv\n"
    "image*.png\n"
    "Claude-*.md\n"
)

DEPS_TO_DROP = [
    (r'^\s*"backtrader[^"]*",\r?\n', "移除运行时依赖 backtrader（全仓 0 引用）"),
    (r'^\s*"redis>=[^"]*",\r?\n', "移除运行时依赖 redis（全仓 0 引用）"),
    (r'^\s*"setuptools[^"]*",\r?\n', "移除运行时冗余 setuptools（build-system 已有）"),
]
DEV_MARKER = re.compile(r'^\s*"pytest-subtests[^"]*",', re.M)
DEV_ADD = '    "pytest-cov>=5.0.0",'
RUFF_IGNORE_BLOCK = (
    "[tool.ruff.lint.per-file-ignores]\n"
    '"wb_analysis/**" = ["E501", "BLE001"]\n'
    '"scripts/**" = ["E501", "BLE001"]\n'
)
COVERAGE_BLOCK = (
    "[tool.coverage.run]\n"
    "branch = true\n"
    'source = ["tradingagents", "quant"]\n'
    "\n"
    "[tool.coverage.report]\n"
    "show_missing = true\n"
    'exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:", "raise NotImplementedError"]\n'
)

SKIP_PARTS = {"_oneoff", "_archive", "scratch", "__pycache__", ".venv"}


def read(p: Path) -> str:
    with p.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(p: Path, s: str) -> None:
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(s)


# ------------------------------------------------------------ 1. lifecycle 头
def plan_lifecycle() -> list[tuple[Path, str, str]]:
    """返回 [(path, 新内容, 说明)]。"""
    plan, msgs = [], []
    for rel, kind in LIFECYCLE.items():
        p = ROOT / rel
        if not p.exists():
            msgs.append(f"[缺失] {rel} 不存在，请确认路径")
            continue
        text = read(p)
        if re.search(r"^#\s*lifecycle:", text, re.M):
            msgs.append(f"[已有] {rel}")
            continue
        lines = text.splitlines(keepends=True)
        ins = 1 if lines and lines[0].startswith("#!") else 0
        if len(lines) > ins and re.match(r"^#.*coding[:=]", lines[ins]):
            ins += 1
        lines.insert(ins, f"# lifecycle: {kind}{nl_of(text)}")
        plan.append((p, "".join(lines), f"[补头] {rel} -> # lifecycle: {kind}"))
    for _, _, m in plan:
        msgs.append(m)
    return plan, msgs


def nl_of(s: str) -> str:
    return "\r\n" if "\r\n" in s else "\n"


# ------------------------------------------------------------ 2. pyproject.toml
def _section_span(text: str, header: str):
    m = re.search(rf"^\[{re.escape(header)}\]\s*$", text, re.M)
    if not m:
        return None
    nxt = re.search(r"^\[", text[m.end():], re.M)
    return m.start(), (m.end() + nxt.start() if nxt else len(text))


def plan_pyproject():
    if not PYPROJECT.exists():
        return None, ["[缺失] pyproject.toml 不存在"]
    text = read(PYPROJECT)
    nl = nl_of(text)
    msgs: list[str] = []

    for pat, desc in DEPS_TO_DROP:
        new, n = re.subn(pat, "", text, count=1, flags=re.M)
        if n:
            text = new
            msgs.append(f"[改] {desc}")
        else:
            msgs.append(f"[跳过] {desc} —— 未匹配（可能已移除或写法不同，请手工确认）")

    if "pytest-cov" in text:
        msgs.append("[已有] pytest-cov 已在 dev")
    elif DEV_MARKER.search(text):
        text = DEV_MARKER.sub(lambda m: m.group(0) + nl + DEV_ADD, text, count=1)
        msgs.append("[改] dev 追加 pytest-cov>=5.0.0")
    else:
        msgs.append("[跳过] 未找到 dev 锚点 pytest-subtests，请手工追加 pytest-cov")

    span = _section_span(text, "project.optional-dependencies")
    if "quant =" in text or span is None:
        msgs.append("[已有] optional extras quant/redis")
    else:
        seg = text[span[0]:span[1]]
        lines = seg.splitlines(keepends=True)
        close = next((i for i, ln in enumerate(lines) if ln.strip() == "]"), None)
        if close is None:
            msgs.append("[跳过] optional-dependencies 里找不到 dev 数组收尾 ]，请手工加 extras")
        else:
            lines[close + 1:close + 1] = [
                f'quant = ["backtrader>=1.9.78.123"]{nl}',
                f'redis = ["redis>=6.2.0"]{nl}',
            ]
            text = text[:span[0]] + "".join(lines) + text[span[1]:]
            msgs.append("[改] 新增 optional extras: quant / redis")

    rspan = _section_span(text, "tool.ruff")
    if not rspan:
        msgs.append("[跳过] 未找到 [tool.ruff]，请手工调整 extend-exclude")
    else:
        seg = text[rspan[0]:rspan[1]]
        before = seg
        for name in ("wb_analysis", "scripts"):
            seg = re.sub(rf'^\s*"{name}",\r?\n', "", seg, count=1, flags=re.M)
        if seg != before:
            text = text[:rspan[0]] + seg + text[rspan[1]:]
            msgs.append("[改] [tool.ruff].extend-exclude 移除 wb_analysis / scripts")
        else:
            msgs.append("[跳过] extend-exclude 里没找到 wb_analysis/scripts 独立条目，请手工确认")

    if '"BLE"' in text or "'BLE'" in text:
        msgs.append("[已有] ruff select 已含 BLE")
    else:
        m = re.search(r"(?ms)^select\s*=\s*\[(.*?)\]", text)
        if m:
            inner = m.group(1).rstrip()
            add = '\n    "BLE",\n' if "\n" in inner else ', "BLE",'
            text = text[:m.start(1)] + inner + add + text[m.end(1):]
            msgs.append("[改] ruff select 追加 BLE")
        else:
            msgs.append("[跳过] 未找到 ruff select，请手工追加 BLE")

    if "[tool.ruff.lint.per-file-ignores]" in text:
        msgs.append("[已有] per-file-ignores 已存在（请确认含 wb_analysis/scripts 两条）")
    else:
        text = text.rstrip("\r\n") + nl + nl + RUFF_IGNORE_BLOCK.replace("\n", nl)
        msgs.append("[改] 追加 per-file-ignores（wb_analysis/**、scripts/**）")

    if "[tool.coverage.run]" in text:
        msgs.append("[已有] [tool.coverage.run] 已存在")
    else:
        text = text.rstrip("\r\n") + nl + nl + COVERAGE_BLOCK.replace("\n", nl)
        msgs.append("[改] 追加 coverage 配置（source 暂只含 tradingagents/quant）")
    msgs.append("[保持] addopts 未改动 —— --cov-fail-under 只放 CI 命令行")

    return text, msgs


def toml_ok(text: str):
    try:
        import tomllib
    except ModuleNotFoundError:
        return True, "（本机 py<3.11，跳过 TOML 校验）"
    try:
        tomllib.loads(text)
        return True, "TOML 校验通过"
    except Exception as e:  # noqa: BLE001
        return False, f"TOML 校验失败：{e}"


# ------------------------------------------------------------ 3. .gitignore
def plan_gitignore():
    if not GITIGNORE.exists():
        return None, ["[缺失] .gitignore 不存在"]
    text = read(GITIGNORE)
    if GITIGNORE_MARKER in text:
        return None, ["[已有] .gitignore 忽略块已存在"]
    nl = nl_of(text)
    new = text.rstrip("\r\n") + nl + nl + GITIGNORE_BLOCK.replace("\n", nl)
    return new, ["[改] .gitignore 追加：_oneoff/ + scripts/*.csv + image*.png + Claude-*.md"]


# ------------------------------------------------------------ 5. 门禁收紧
def scan_offenders() -> list[str]:
    hits = []
    for p in sorted((ROOT / "wb_analysis").rglob("*.py")):
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        if p.name == "_clock.py":
            continue
        try:
            tree = ast.parse(read(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute) or f.attr not in {"now", "today"}:
                continue
            if node.args or node.keywords:
                continue
            if "_clock" in ast.unparse(f):
                continue
            hits.append(str(p.relative_to(ROOT)).replace("\\", "/"))
            break
    return sorted(set(hits))


def plan_guard(offenders: list[str]):
    if not GUARD.exists():
        return None, ["[缺失] tests/test_no_naive_clock.py 不存在"]
    text = read(GUARD)
    pat = re.compile(r"KNOWN_FILES(?::\s*set\[str\])?\s*=\s*\{.*?\n\}", re.S)
    if not pat.search(text):
        return None, ["[跳过] 未找到 KNOWN_FILES 字面量块，请手工更新"]
    body = "".join(f'    "{f}",\n' for f in offenders)
    new = pat.sub(f"KNOWN_FILES: set[str] = {{\n{body}}}", text, count=1)
    if not offenders:
        new = pat.sub("KNOWN_FILES: set[str] = set()", text, count=1)
    return new, [f"[改] KNOWN_FILES 收紧为 {len(offenders)} 个残留文件"]


# ------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入（默认只干跑）")
    args = ap.parse_args()
    print(f"=== {'APPLY（写入）' if args.apply else 'DRY-RUN（只看不改）'} ===\n")

    lc_plan, lc_msgs = plan_lifecycle()
    pp_text, pp_msgs = plan_pyproject()
    gi_text, gi_msgs = plan_gitignore()

    print("--- 1. lifecycle 头 ---")
    for m in lc_msgs:
        print(" ", m)
    print("\n--- 2. pyproject.toml ---")
    for m in pp_msgs:
        print(" ", m)
    print("\n--- 3. .gitignore ---")
    for m in gi_msgs:
        print(" ", m)

    if pp_text is not None:
        ok, why = toml_ok(pp_text)
        print(f"\n  [{ 'OK' if ok else 'FAIL' }] {why}")
        if not ok:
            print("\nTOML 校验未通过，已中止，未写入任何文件。")
            return 1

    print("\n--- 4. 时钟 codemod ---")
    if not CODEMOD.exists():
        print("  [FAIL] 找不到 scripts/_codemod_clock.py，中止")
        return 1
    cmd = [sys.executable, str(CODEMOD)] + (["--apply"] if args.apply else [])
    print("  $ " + " ".join(cmd))
    rc = subprocess.run(cmd, cwd=str(ROOT)).returncode
    if rc != 0:
        print(f"  [FAIL] codemod 退出码 {rc}，本脚本不写入任何其它文件（避免半完成）")
        return 1
    print("  [OK] codemod 完成")

    if not args.apply:
        print("\n--- 5. 门禁收紧 ---")
        print("  （干跑不预判 codemod 后的残留，--apply 时自动收紧 KNOWN_FILES）")
        print("\n干跑结束，未改动任何文件。确认无误后加 --apply 重跑。")
        return 0

    for p, s, _ in lc_plan:
        write(p, s)
    if pp_text is not None:
        write(PYPROJECT, pp_text)
    if gi_text is not None:
        write(GITIGNORE, gi_text)

    offenders = scan_offenders()
    g_text, g_msgs = plan_guard(offenders)
    print("\n--- 5. 门禁收紧 ---")
    for m in g_msgs:
        print(" ", m)
    if g_text is not None:
        write(GUARD, g_text)

    print("\n--- 6. 自检 ---")
    ok = True
    pj = read(PYPROJECT)
    for cond, desc in [
        ("[tool.coverage.run]" in pj, "coverage 配置已落地"),
        ('"backtrader' not in pj, "backtrader 已移出运行时依赖"),
        ('"redis>=' not in pj, "redis 已移出运行时依赖"),
        (GITIGNORE_MARKER in read(GITIGNORE), ".gitignore 忽略块已写入"),
    ]:
        print(f"  [{'OK' if cond else 'FAIL'}] {desc}")
        ok = ok and cond
    left = scan_offenders()
    print(f"  [{'OK' if not left else 'WARN'}] 残留裸本地时间文件：{left or '无'}")

    print("\n--- 7. 还需要你手工执行的 git 命令（本脚本不碰 git）---")
    print("  git rm -r --cached scripts/_oneoff wb_analysis/_oneoff scripts/_wdc_mkt_windows.csv")
    print('  git rm --cached image*.png "Claude-Haiku-5.5-vs-DeepSeek-V4.1-Flash-1017.md"')
    print("  git ls-files --eol | sort -u     # 先看清仓库里存的是 LF 还是 CRLF，再决定 core.autocrlf")
    print("  ./.venv/Scripts/python.exe -m pytest -q")
    print("  ./.venv/Scripts/python.exe scripts/_health.py")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
