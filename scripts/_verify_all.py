#!/usr/bin/env python
# lifecycle: maintenance
"""治理落地验收（只读，不修改任何文件）。

用法：
    ./.venv/Scripts/python.exe scripts/_verify_all.py            # 全量（含全量 pytest）
    ./.venv/Scripts/python.exe scripts/_verify_all.py --quick    # 跳过全量 pytest，只看门禁与配置

输出是一张紧凑的 OK/WARN/FAIL 表，直接整段贴回来即可。
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
def _baseline() -> int:
    """从 scripts/_health.py 读回归基线，避免同一数字在多处硬编码。"""
    try:
        src = (ROOT / "scripts" / "_health.py").read_text(encoding="utf-8")
        m = re.search(r"^BASELINE_PASSED\s*=\s*(\d+)", src, re.M)
        return int(m.group(1)) if m else 0
    except Exception:  # noqa: BLE001
        return 0


BASELINE_PASSED = _baseline()
SKIP_PARTS = {"_oneoff", "_archive", "scratch", "__pycache__", ".venv"}
RESULTS: list[tuple[str, str, str]] = []


def rec(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))


def run(args: list[str], timeout: int = 1200):
    try:
        p = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -9, f"<超时 {timeout}s>"
    except FileNotFoundError as e:
        return -1, f"<无法执行: {e}>"


def read(p: Path) -> str:
    try:
        with p.open("r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except OSError:
        return ""


# ---------------------------------------------------------------- 1/2 pytest
def check_pytest(quick: bool) -> None:
    bt = Path(tempfile.gettempdir()) / f"ta-verify-bt-{os.getpid()}"
    rc, out = run([sys.executable, "-m", "pytest", "-q", "--basetemp", str(bt),
                   "tests/test_no_naive_clock.py", "tests/test_retry_behaviour.py"])
    n = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) (failed|error)", out)
    if rc == 0 and n:
        rec("OK", f"门禁测试：{n.group(1)} passed")
    else:
        rec("FAIL", "门禁测试未通过", (f.group(0) if f else f"rc={rc}") + " | " + out.strip()[-400:])

    if quick:
        rec("SKIP", "全量回归：--quick 跳过")


# ---------------------------------------------------------------- 3 时区扫描
def scan_offenders() -> list[str]:
    hits = []
    for p in sorted((ROOT / "wb_analysis").rglob("*.py")):
        if any(part in SKIP_PARTS for part in p.parts) or p.name == "_clock.py":
            continue
        try:
            tree = ast.parse(read(p))
        except (SyntaxError, ValueError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute) or fn.attr not in {"now", "today"}:
                continue
            if node.args or node.keywords or "_clock" in ast.unparse(fn):
                continue
            hits.append(f"{p.relative_to(ROOT)}:{node.lineno}")
            break
    return sorted(set(hits))


def check_clock() -> None:
    off = scan_offenders()
    rec("OK" if not off else "FAIL", f"wb_analysis 裸本地时间残留：{len(off)} 处",
        "; ".join(off[:8]) if off else "")
    g = read(ROOT / "tests" / "test_no_naive_clock.py")
    if "KNOWN_FILES: set[str] = set()" in g:
        rec("OK", "时区门禁为严格态（KNOWN_FILES 已清空）")
    else:
        rec("WARN", "时区门禁仍是记账态", "KNOWN_FILES 未清空，存量违规仍被豁免")
    uses = sum(1 for p in (ROOT / "wb_analysis").rglob("*.py")
               if "_oneoff" not in p.parts and "_clock." in read(p))
    rec("OK" if uses >= 10 else "WARN", f"已接入 _clock 的文件数：{uses}")


# ---------------------------------------------------------------- 4 pyproject
def check_pyproject() -> None:
    pj = read(ROOT / "pyproject.toml")
    if not pj:
        rec("FAIL", "pyproject.toml 读取失败")
        return
    try:
        import tomllib
        data = tomllib.loads(pj)
    except ModuleNotFoundError:
        data = None
        rec("WARN", "py 版本 <3.11，跳过结构化解析")
    except Exception as e:  # noqa: BLE001
        rec("FAIL", "pyproject.toml 不是合法 TOML", str(e)[:200])
        return

    for cond, name in [
        ("[tool.coverage.run]" in pj, "coverage 配置已写入"),
        ('"BLE"' in pj, "BLE 已在 ruff select"),
        ("pytest-cov" in pj, "pytest-cov 已在 dev"),
        (not re.search(r'^\s*"wb_analysis",\s*$', pj, re.M), "extend-exclude 不再排除 wb_analysis"),
        (not re.search(r'^\s*"scripts",\s*$', pj, re.M), "extend-exclude 不再排除 scripts"),
        ('"wb_analysis/**"' in pj, 'per-file-ignores 含 "wb_analysis/**"'),
        ('"scripts/**"' in pj, 'per-file-ignores 含 "scripts/**"'),
    ]:
        rec("OK" if cond else "WARN", name)

    if data:
        deps = data.get("project", {}).get("dependencies", [])
        left = [d for d in deps if d.split(">")[0].split("=")[0].strip() in
                {"backtrader", "redis", "setuptools"}]
        rec("OK" if not left else "FAIL", "运行时依赖已精简", "残留: " + ", ".join(left))
        extras = data.get("project", {}).get("optional-dependencies", {})
        for name in ("quant", "redis"):
            rec("OK" if name in extras else "WARN", f"optional extra: {name}",
                "" if name in extras else "缺失（脚本 B3 静默跳过，需确认）")


# ---------------------------------------------------------------- 5 gitignore / git 索引
def check_git() -> None:
    gi = read(ROOT / ".gitignore")
    rec("OK" if "governance: 一次性脚本与数据快照" in gi else "WARN", ".gitignore 忽略块已写入")
    rc, out = run(["git", "ls-files", "--", "scripts/_oneoff", "wb_analysis/_oneoff",
                   "scripts/_wdc_mkt_windows.csv"], timeout=60)
    if rc < 0:
        rec("SKIP", "git 索引检查（无法执行 git）", out.strip()[:120])
        return
    tracked = [x for x in out.splitlines() if x.strip()]
    rec("OK" if not tracked else "WARN",
        f"已跟踪的一次性产物：{len(tracked)} 个",
        "需 git rm --cached" if tracked else "")


# ---------------------------------------------------------------- 6 ruff
def check_ruff() -> None:
    rc, out = run([sys.executable, "-m", "ruff", "check", "wb_analysis", "scripts",
                   "--statistics"], timeout=300)
    if rc == -1:
        rec("SKIP", "ruff 未安装")
        return
    lines = [x for x in out.splitlines() if x.strip()]
    if rc == 0:
        rec("OK", "ruff check wb_analysis scripts：0 问题")
    else:
        head = " | ".join(lines[:6])
        rec("WARN", f"ruff 在自研代码上报告 {len(lines)} 类问题（预期，见建议）", head)


# ---------------------------------------------------------------- 7 health
def check_health() -> None:
    if not (ROOT / "scripts" / "_health.py").exists():
        rec("SKIP", "scripts/_health.py 不存在")
        return
    rc, out = run([sys.executable, "scripts/_health.py"], timeout=900)
    m_reg = re.search(r"回归基线\s+[✓△✗]\s+(PASS|WARN|FAIL)\s+([^\n]+)", out)
    if m_reg:
        lv, detail = m_reg.group(1), m_reg.group(2).strip()
        rec("OK" if lv == "PASS" else lv, "全量回归（复用 _health 回归基线）", detail)
    tail = [x for x in out.strip().splitlines() if x.strip()][-6:]
    rec("OK" if rc == 0 else "FAIL", f"_health.py 退出码 {rc}", " / ".join(tail)[:500])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="跳过全量 pytest")
    args = ap.parse_args()
    print("=== TradingAgents 治理验收（只读）===\n")
    check_pytest(args.quick)
    check_clock()
    check_pyproject()
    check_git()
    check_ruff()
    if not args.quick:
        check_health()
    print(f"{'结果':<6}{'检查项':<44}说明")
    print("-" * 100)
    for s, n, d in RESULTS:
        print(f"{s:<6}{n:<44}{d}")
    bad = [r for r in RESULTS if r[0] == "FAIL"]
    warn = [r for r in RESULTS if r[0] == "WARN"]
    print(f"\n=== 汇总：FAIL {len(bad)} / WARN {len(warn)} / 共 {len(RESULTS)} 项 ===")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
