# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe scripts/_health.py [--quiet]
"""项目健康检查：**一条命令看整个项目状态**（把散落的各处门禁汇总成一个入口）。

## 为什么需要
此前有 5 个各自独立的检查，但要跑 5 条命令、看 5 种输出格式：
  `wb_analysis/_selftest.py` · `scripts/_tidy_scripts.py --check` ·
  `wb_analysis/_reports_index.py --check` · `wb_analysis/_seal_run.py --plan`
  · 以及"根目录有没有散落文件""版本库有没有漏配忽略"
⇒ 结果是**没人会每次全跑**，于是问题总是拖到累积之后才被发现。本工具把它们收成一条命令。

## 判读
  ✓ PASS  正常
  △ WARN  需要人工过目（不影响使用）
  ✗ FAIL  必须处理（退出码 1）

## 用法
  ./.venv/Scripts/python.exe scripts/_health.py          # 完整输出
  ./.venv/Scripts/python.exe scripts/_health.py --quiet  # 只印非 PASS 项
"""
import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SKIP = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}


def run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=str(ROOT))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 999, "超时"
    except Exception as exc:  # noqa: BLE001
        return 998, f"执行失败: {exc!r}"


def chk_selftest() -> tuple[str, str]:
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_selftest.py")])
    m = re.search(r"全部\s*(\d+)\s*项通过", out)
    if rc == 0 and m:
        return "PASS", f"门禁自检 {m.group(1)}/{m.group(1)} 项通过"
    tail = [l for l in out.splitlines() if l.strip().startswith(("✗", "✓"))]
    return "FAIL", (tail[-1][:70] if tail else "自检未通过")


def chk_lifecycle() -> tuple[str, str]:
    rc, out = run([PY, str(ROOT / "scripts" / "_tidy_scripts.py"), "--check"])
    if rc == 0:
        m = re.search(r"全部\s*(\d+)\s*个脚本", out)
        return "PASS", f"{m.group(1) if m else '?'} 个脚本均已声明生命周期"
    bad = [l.strip() for l in out.splitlines() if l.strip().startswith("    ")]
    return "FAIL", f"{len(bad)} 个脚本缺 lifecycle 声明"


def chk_reports() -> tuple[str, str]:
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_reports_index.py"), "--check"])
    n = sum(1 for l in out.splitlines() if l.strip().startswith("- ["))
    if n == 0:
        m = re.search(r"报告树\s*(\d+)\s*棵", out)
        return "PASS", f"报告树 {m.group(1) if m else '?'} 棵，无堆积问题"
    return "WARN", f"{n} 项待整理（孤儿/重复/散落）"


def chk_seal() -> tuple[str, str]:
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_seal_run.py"), "--plan"])
    m = re.search(r"待封存\s*(\d+)\s*轮", out)
    n = int(m.group(1)) if m else 0
    return ("PASS", "无待封存产物（瞬态目录已清）") if n == 0 else \
           ("WARN", f"{n} 轮产物待封存：跑 _seal_run.py --all --apply")


def chk_transient_empty() -> tuple[str, str]:
    """瞬态目录应为空 —— 这是「只留最终报告」政策的体检点。"""
    left = []
    for sub in ("evidence", "drafts", "analysis"):
        d = ROOT / "wb_analysis" / sub
        if d.exists():
            n = len([p for p in d.rglob("*") if p.is_file()])
            if n:
                left.append(f"{sub}={n}")
    return ("PASS", "evidence/drafts/analysis 均为空") if not left else \
           ("WARN", "瞬态目录非空：" + ", ".join(left))


def chk_gitignore() -> tuple[str, str]:
    f = ROOT / ".gitignore"
    if not f.exists():
        return "WARN", "无 .gitignore"
    t = f.read_text(encoding="utf-8", errors="replace")
    need = ["wb_analysis/evidence/", "wb_analysis/drafts/", "wb_analysis/analysis/",
            ".workbuddy/backup/"]
    miss = [n for n in need if n not in t]
    return ("PASS", "瞬态目录与回滚包均已忽略") if not miss else \
           ("WARN", f"未忽略：{', '.join(miss)}")


# 根目录允许的 .py：只有 pytest 配置（它必须放在根，否则不被识别）
ROOT_PY_ALLOWED = {"conftest.py"}


def chk_root_clean() -> tuple[str, str]:
    stray = sorted(p.name for p in ROOT.glob("*.py") if p.name not in ROOT_PY_ALLOWED)
    return ("PASS", "根目录无散落 .py") if not stray else \
           ("WARN", f"根目录有 {len(stray)} 个 .py：{', '.join(stray[:4])}")


def chk_quant() -> tuple[str, str]:
    code = ("import sys; sys.path.insert(0, r'%s');"
            "from quant import screener_engine, stock_pools, edgar_fundamentals, price_history;"
            "assert '1038421735@qq.com' in edgar_fundamentals.SEC_USER_AGENT, 'SEC 凭证失效';"
            "print('OK')" % str(ROOT))
    rc, out = run([PY, "-c", code])
    return ("PASS", "自建包可导入，且 .env 凭证读取正常") if "OK" in out else \
           ("FAIL", f"自建包或凭证异常：{out.strip().splitlines()[-1][:70] if out.strip() else rc}")


# ── 长期堆积预算 ──────────────────────────────────────────────────────────────
# 目标：项目**长期运行不积累没用的东西**。做法不是"天天清"，而是
#   ① 占用**可见**（PASS 消息也带各项尺寸）；② 每类堆积物有**预算**；③ 超预算时给出**明确出口**。
# 预算依据（2026-09-23 实测基线）：reports 10.0 / _cache 0.13 / backup 4.2 / memory 0.24 MB，
#   **外部缓存 ~/.tradingagents 591 MB**（prices 265 + cache 220 + edgar 101）——
#   它是全项目最大的堆积物、且在仓库之外，此前对任何检查都不可见。
# 预算取余量 ⇒ 正常增长不报警，只在"真积累"时说话（误报过多的闸门等于没有闸门）。
# 「磁盘占用」不是正确性问题 ⇒ 本检查永远不 FAIL。
DISK_BUDGETS: list[tuple[str, str, float, str]] = [
    # (显示名, 路径【绝对=项目外，相对=ROOT 下】, 预算 MB, 超预算时的处置)
    ("reports", "reports", 200.0, "旧版报告可清：scripts/_cleanup_reports.py（删前先打包回滚包）"),
    ("_cache", "wb_analysis/_cache", 50.0, "共享参考数据，可删后由 erp_context.py 等重采"),
    ("backup", ".workbuddy/backup", 30.0, "scripts/_prune_backup.py"),
    ("memory", ".workbuddy/memory", 10.0, "旧日志归档进 _backup/ 并精简"),
    ("外部缓存", str(Path.home() / ".tradingagents"), 1024.0,
     "quant/cleanup_cache.py --status 先看占用，再选 --keep-edgar / --yes"),
]
PYC_BUDGET_MB = 20.0  # .pyc 正常约 1 MB；超过 20 MB 属异常（不是"该清了"而是"哪里坏了"）


def _dir_mb(p: Path) -> float:
    t = 0
    if not p.is_dir():
        return 0.0
    for dp, _dn, fn in os.walk(p):
        for f in fn:
            try:
                t += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return t / 1024 / 1024


def _pyc_mb() -> float:
    """项目内 .pyc 总量（排除 .venv 等运行时目录）。

    ⚠️ 判据沿自 2026-09-23 修过的 bug：不能写 `any(s in d.parts for s in SKIP)`——
    `rglob` 迭代出的目录本身就叫 `__pycache__` 而 `SKIP` 里也含它，条件恒真、检测器恒 PASS
    （实测漏掉 82 个 .pyc 却报"无残留"）。必须只看 `__pycache__` **之上**的目录。
    """
    excluded = SKIP - {"__pycache__"}
    t = 0
    for d in ROOT.rglob("__pycache__"):
        if any(s in d.relative_to(ROOT).parts[:-1] for s in excluded):
            continue
        for f in d.glob("*.pyc"):
            try:
                t += f.stat().st_size
            except OSError:
                pass
    return t / 1024 / 1024


def chk_disk_budget() -> tuple[str, str]:
    """堆积预算体检（取代原「编译缓存」单项检查，2026-09-23）。

    为什么取代：.pyc 被 .gitignore 覆盖、每次运行必然重生 —— 逐个计数只会产出
    **永远黄的噪声闸门**。把它并进整体占用后，只在总量异常的量级上说话。
    路径支持绝对（项目外，如 ~/.tradingagents）与相对（ROOT 下）两种。
    """
    def _path(rel: str) -> Path:
        return Path(rel) if os.path.isabs(rel) else ROOT / rel

    sizes = [(name, _dir_mb(_path(rel))) for name, rel, _b, _r in DISK_BUDGETS]
    pyc = _pyc_mb()
    overview = " · ".join(f"{n} {v:.1f}MB" for n, v in sizes) + f" · pyc {pyc:.1f}MB"
    over = [
        f"{name} {v:.0f}MB 超预算 {b:.0f}MB ⇒ {remedy}"
        for (name, _rel, b, remedy), (_n, v) in zip(DISK_BUDGETS, sizes)
        if v > b
    ]
    if pyc > PYC_BUDGET_MB:
        over.append(f"pyc {pyc:.0f}MB 异常（正常 ≈1MB）⇒ 逐文件清理项目内 __pycache__")
    if over:
        return "WARN", "；".join(over)
    return "PASS", overview



def chk_memory_size() -> tuple[str, str]:
    """记忆体积门禁。

    宿主的注入是按**字节**截断的（实测 ≈15,000 字节），**超了就静默丢尾部**——
    而尾部恰好是「用户偏好」这类最不该丢的内容。靠"记得精简"必然失效 ⇒ 设成门禁。
    """
    p = ROOT / ".workbuddy" / "memory" / "MEMORY.md"
    if not p.exists():
        return "WARN", "未找到 MEMORY.md"
    n = len(p.read_bytes())
    tail_ok = "用户偏好" in p.read_text(encoding="utf-8")
    if n > 14800:
        return "FAIL", f"MEMORY.md 已达 {n} 字节（宿主 ≈15000 处截断）⇒ **必须精简**"
    if n > 14200:
        return "WARN", f"MEMORY.md {n} 字节，余量不足（建议压到 14200 以下）"
    if not tail_ok:
        return "FAIL", f"MEMORY.md 尾部内容缺失（可能已被截断）—— 当前 {n} 字节"
    return "PASS", f"MEMORY.md {n} 字节，尾部完好"


# ★ 确定性回归基线（2026-09-23 立）
#   为什么必须排除 `DeepSeekLive`：那是**真实 API 调用**测试，API 没余额时返回 402 ⇒ 假红。
#   实测过一次：全量跑出 `724 passed, 1 failed`，看起来像代码回归，实际是"余额不足"。
#   ⇒ **能让"改文件找 bug"失效的，不是测试少，而是基线不确定**。
#   基线数 = `python -m pytest tests/ -q -k "not DeepSeekLive"` 的 passed 数。
BASELINE_K = "not DeepSeekLive"
BASELINE_PASSED = 724


def chk_tests() -> tuple[str, str]:
    """回归门禁：与确定性基线比。少了 ⇒ 真回归（FAIL）；多了 ⇒ 有新测试没更新基线（WARN）。"""
    rc, out = run([PY, "-m", "pytest", "tests/", "-q", "--no-header", "-k", BASELINE_K], timeout=600)
    m = re.search(r"(\d+) passed", out)
    if not m:
        return "FAIL", "测试未能收集（语法/导入错误？）"
    n = int(m.group(1))
    if n < BASELINE_PASSED:
        return "FAIL", f"回归：{n} passed < 基线 {BASELINE_PASSED}（少 {BASELINE_PASSED - n} 个）"
    if n > BASELINE_PASSED:
        return "WARN", f"{n} passed > 基线 {BASELINE_PASSED} ⇒ 有新测试，请更新 BASELINE_PASSED"
    return "PASS", f"{n} passed，与确定性基线一致（已排除真实 API 测试）"


def chk_scorecard() -> tuple[str, str]:
    """记分卡覆盖度：「越用越好」要有度量，未打分的交付就是没度量。"""
    csv = ROOT / "reports" / "QUALITY.csv"
    n_trees = 0
    reports = ROOT / "reports"
    if reports.exists():
        for d in reports.iterdir():
            if d.is_dir() and not d.name.startswith("_"):
                n_trees += len([x for x in d.iterdir() if x.is_dir()])
    if not csv.exists():
        return ("WARN", f"{n_trees} 轮交付但无记分卡 ⇒ 跑 wb_analysis/_scorecard.py") if n_trees else \
               ("PASS", "尚无交付轮次")
    rows = [l for l in csv.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    if len(rows) < n_trees:
        return "WARN", f"记分卡 {len(rows)} 轮 / 交付 {n_trees} 轮 ⇒ 有新交付未打分，跑 _scorecard.py"
    return "PASS", f"记分卡覆盖 {len(rows)}/{n_trees} 轮（趋势看 _scorecard.py --trend）"


CHECKS = [
    ("门禁自检", chk_selftest),
    ("脚本生命周期", chk_lifecycle),
    ("报告卫生", chk_reports),
    ("待封存产物", chk_seal),
    ("瞬态目录", chk_transient_empty),
    ("自建包与凭证", chk_quant),
    ("版本库忽略", chk_gitignore),
    ("根目录整洁", chk_root_clean),
    ("堆积预算", chk_disk_budget),
    ("记忆体积", chk_memory_size),
    ("回归基线", chk_tests),
    ("质量记分卡", chk_scorecard),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="只印非 PASS 项")
    args = ap.parse_args()

    rows = [(name, *fn()) for name, fn in CHECKS]
    icon = {"PASS": "✓", "WARN": "△", "FAIL": "✗"}
    print("=" * 88)
    print("TradingAgents 项目健康检查")
    print("=" * 88)
    if not args.quiet:
        print(f"\n  {'检查项':16s} {'结果':6s} 说明")
        print("  " + "-" * 82)
    for name, level, msg in rows:
        if args.quiet and level == "PASS":
            continue
        print(f"  {name:16s} {icon[level]} {level:4s} {msg}")
    n_fail = sum(1 for _, lv, _ in rows if lv == "FAIL")
    n_warn = sum(1 for _, lv, _ in rows if lv == "WARN")
    n_pass = len(rows) - n_fail - n_warn
    print(f"\n  合计：✓ {n_pass} PASS · △ {n_warn} WARN · ✗ {n_fail} FAIL")
    if n_fail:
        print("  ⇒ 有阻断项，按上表逐条处理后重跑本命令。")
    elif n_warn:
        print("  ⇒ 无阻断项；WARN 项按需处理（不影响功能）。")
    else:
        print("  ⇒ 项目状态全绿。")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
