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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SKIP = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}

# ★ 2026-10-10：非 12 角色专用通道的豁免表与 `_reports_index.py` / `_seal_run.py` **同源**
#   （唯一定义源＝`wb_analysis/_contract.py`）。此前本检查只数文件数、不认豁免，
#   于是对同一份 TREASURY 文件，`_reports_index` 报「0 问题」而这里报 WARN —— 判据打架。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from wb_analysis._contract import is_non_tree_artifact  # noqa: E402
from wb_analysis._paths import FUNC_DIRS, TREE_RE  # noqa: E402


def run(args: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, cwd=str(ROOT), env=env)
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
    # ★ 2026-10-16 修：原判据 `l.strip().startswith("    ")` 恒为 False
    #   —— `str.strip()` 已去掉前导空格，结果**永不可能**以 4 个空格开头。
    #   实测后果：健康检查显示「✗ FAIL 0 个脚本缺 lifecycle 或 serves 标记」，
    #   状态与计数自相矛盾，且真实文件名被掩盖（实际是 2 个 _oneoff 脚本）。
    #   改为「缩进 4 空格且非空」的原始行，与 `_tidy_scripts.py` 的输出格式对齐。
    bad = [l.strip() for l in out.splitlines()
           if l.startswith("    ") and l.strip()]
    detail = ("：" + "、".join(bad[:3]) + ("…" if len(bad) > 3 else "")) if bad else ""
    return "FAIL", f"{len(bad)} 个脚本缺 lifecycle 或 serves 标记{detail}"


def chk_reports() -> tuple[str, str]:
    """报告层是否有堆积 / 孤儿 / 缺草稿。

    ★★ 2026-10-16 修（本日第 7 例「检查器判据缺陷」，**已实测复现**）：
    原判据把「0 条问题条目」直接当成「无问题」，但 **`n == 0` 有两种含义**：
      · 真的没有卫生问题（正常）；
      · **工具崩了 / 没跑起来 ⇒ 一条问题条目都没输出（同样 n == 0）**。
    ⇒ 两者不可区分 ⇒ **工具崩溃被读成「无问题」= 假绿**。

    实测：把 `_reports_index.py` 换成「exit 3 + 打印垃圾」的桩后，
    本函数仍返回 `PASS — 报告树 ? 棵，无堆积问题`。

    与铁律 3「静默失败」同族；`test_precheck_gate.py` 已为 `_precheck` 守住
    「崩溃 ≠ 检出问题」，但 **本检查当时没有同样的保护**。

    ⇒ 修法：**先验 rc，再看内容**。`rc != 0` 一律不得进 PASS 分支。
    """
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_reports_index.py"), "--check"])
    # ① 先验「工具是否真的跑成功」—— 崩溃时不得把「无输出」读成「无问题」
    if rc != 0:
        first = out.strip().splitlines()[0][:70] if out.strip() else "(无输出)"
        return "FAIL", f"`_reports_index.py --check` 未正常退出（rc={rc}）⇒ 无法判断，首行：{first}"
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("- [")]
    n = len(lines)
    if n == 0:
        m = re.search(r"报告树\s*(\d+)\s*棵", out)
        if not m:
            # ② 连「报告树 N 棵」都解析不到 ⇒ 输出格式已变，不能假定为 0
            return "WARN", ("`_reports_index.py --check` 输出无法解析（未见「报告树 N 棵」）"
                            "⇒ **不能假定为 0 问题**，请人工跑一次确认")
        return "PASS", f"报告树 {m.group(1)} 棵，无堆积问题"
    # ★ 2026-10-11（O6）：告警必须**带可执行入口**。
    #   此前只报「N 项待整理（孤儿/重复/散落）」，操作者得自己猜到该跑
    #   `_seal_run.py --orphans` —— 而该入口**早就存在**且已是「先打包回滚、校验不过即中止」
    #   的完整链路。检测与处置之间缺的只是一句指路，于是 TSM 那类残留能挂十多个小时没人动。
    orphans = [l for l in lines if "孤儿" in l]
    parts = []
    if orphans:
        parts.append(f"孤儿 {len(orphans)} 项 → `_seal_run.py --orphans --apply`"
                     f"（先打包回滚、逐项校验不过即中止）")
    other = n - len(orphans)
    if other:
        parts.append(f"其它 {other} 项（重复/散落/缺草稿）→ `_reports_index.py --check` 看明细")
    return "WARN", f"{n} 项待整理（孤儿/重复/散落）：" + "；".join(parts)


def chk_seal() -> tuple[str, str]:
    """是否有待封存产物。

    ★★ 2026-10-16 修（本日第 6 例「检查器判据缺陷」）：
    原判据 `n = int(m.group(1)) if m else 0` —— **正则不命中就当作「0 轮」**
    ⇒ 只要 `_seal_run.py --plan` 的输出格式一变（改措辞、加前缀、被警告截断），
    本检查就**静默报 PASS**，而实际可能堆着一批待封存产物。

    ⇒ 判据改为：**解析失败 ≠ 没问题**。取不到数字时报 WARN 并要求人工确认
    （与铁律 3「静默失败」同源：报成功 + 外观正常 ≠ 真的没问题）。
    """
    rc, out = run([PY, str(ROOT / "wb_analysis" / "_seal_run.py"), "--plan"])
    m = re.search(r"待封存\s*(\d+)\s*轮", out)
    if not m:
        return "WARN", ("无法解析 `_seal_run.py --plan` 的输出 ⇒ **不能假定为 0**，"
                        "请人工确认；首行："
                        + (out.strip().splitlines()[0][:60] if out.strip() else "(空输出)"))
    n = int(m.group(1))
    return ("PASS", "无待封存产物（瞬态目录已清）") if n == 0 else \
           ("WARN", f"{n} 轮产物待封存：跑 _seal_run.py --all --apply")


def chk_transient_empty() -> tuple[str, str]:
    """瞬态目录应为空 —— 这是「只留最终报告」政策的体检点。

    ★ 2026-10-10：`evidence/` 里的**非 12 角色专用通道**产物（如 `collect_treasury.py`
    写的 `TREASURY_<date>.*`）**以 `evidence/` 为正规归宿**，不算「非空」。
    豁免表与 `_reports_index.py` / `_seal_run.py` 同源（`wb_analysis/_contract.py`）——
    此前本检查只数文件数、不认豁免，与另两处对同一份文件给出相反结论。
    """
    left = []
    exempt = 0
    for sub in ("evidence", "drafts", "analysis"):
        d = ROOT / "wb_analysis" / sub
        if not d.exists():
            continue
        n = 0
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if sub == "evidence" and is_non_tree_artifact(p.name):
                exempt += 1
                continue
            n += 1
        if n:
            left.append(f"{sub}={n}")
    tail = f"（豁免非 12 角色通道 {exempt} 个）" if exempt else ""
    return ("PASS", f"evidence/drafts/analysis 无待清产物{tail}") if not left else \
           ("WARN", "瞬态目录非空：" + ", ".join(left) + tail)


def _gitignore_dir_covered(need: str, active: set[str]) -> bool:
    """目录 `need`（形如 `wb_analysis/evidence/`）是否被某条**有效**规则覆盖。

    ★★ 2026-10-17 修（本日第 6 例「检查器判据缺陷」，由 TREASURY 入版本控制触发）：
    原判据是**精确等于** `n not in active` ⇒ 只认 `wb_analysis/evidence/` 这一种写法。
    但为把常驻宏观数据 TREASURY 纳入版本控制，`.gitignore` 被合理改写为：

        wb_analysis/evidence/*          ← 忽略目录下全部
        !wb_analysis/evidence/TREASURY* ← 白名单放行常驻数据

    这**在 git 语义下等价于（且优于）**原写法 —— 实测 `git check-ignore` 对
    普通探针仍返回「已忽略」，4 个目录的功能行为**全部正确**。
    然而文本层因 `wb_analysis/evidence/*` ≠ `wb_analysis/evidence/` 而误报 WARN，
    连带 `tests/test_health_checkers.py::test_normal_gitignore_passes` 失败
    —— 即**检查器把「写法不同」误判成「未忽略」**。

    ⇒ 判据放宽为「覆盖」而非「精确相等」，同时**坚持排除 `!` 白名单行**
      （白名单是放行，不是忽略；若把它算作忽略，注释/反转类假绿会重新出现）。

    **为什么仍保留文本层**：它是快速失败的前置检查，能在 git 不可用时（如
    CI 无 git、或 `check-ignore` 行为异常）仍给出判断；真正的判据仍是下面的行为层。
    """
    base = need.rstrip("/")           # wb_analysis/evidence
    for rule in active:
        if rule.startswith("!"):      # 白名单行 = 放行，不算「已忽略」
            continue
        r = rule.rstrip("/")
        # 接受的等价写法：`dir/`、`dir`、`dir/*`、`dir/**`、`/dir/`
        if r.lstrip("/") in (base, base + "/*", base + "/**"):
            return True
    return False


def _git_check_ignored(path: str) -> bool:
    """让 git 自己回答「该路径是否被忽略」（真正的判据：行为，不是文本形态）。"""
    # ⚠️ `run()` 已内置 `cwd=ROOT` 且签名不含 cwd ⇒ 不要多传。（多传会 TypeError）
    rc, _out = run(["git", "check-ignore", "-q", path])
    return rc == 0


def chk_gitignore() -> tuple[str, str]:
    """瞬态目录与回滚包是否真被 git 忽略。

    ★★ 2026-10-16 修（本日第 5 例「检查器判据缺陷」，实测复现）：
    原判据是**纯子串** `n not in t`（`t` = 全文）⇒
    **把条目注释掉后，注释行里仍含该子串 ⇒ 照样报 PASS**。

    实证：把 4 条必需项全部写成 `# wb_analysis/evidence/` 后，
    `git check-ignore -v wb_analysis/evidence/x.md` 返回 **1（不再忽略）**
    —— 瞬态文件此时可被 `git add` 进去，而体检仍报「均已忽略」= **假绿**。

    ⇒ 判据改为：**先剥掉注释（`#` 之后）与空行，再逐条比对有效规则**。
      并额外用 `git check-ignore` 做一次**功能性断言**（真正的判据是 git 的行为，
      不是文本形态）—— 这是把「文本检查」升级为「行为检查」。

    ★★ 2026-10-17 修（本日第 6 例，同族）：
      文本层从「精确相等」改为「覆盖」（见 `_gitignore_dir_covered`），
      行为层从**单个探针**改为**逐目录探针**。
      原因：原实现只探 `wb_analysis/evidence/__probe__.md` 一个路径 ⇒
      若另外 3 个目录的规则被破坏（如被 `!` 反转），行为层**看不见** ——
      与「后缀白名单把新类型文件挡在视野外」是同一类盲区。
    """
    f = ROOT / ".gitignore"
    if not f.exists():
        return "WARN", "无 .gitignore"

    # ① 文本层：剥注释后逐条比对（注释行不算数；白名单行不算「已忽略」）
    active: set[str] = set()
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            active.add(s)
    need = ["wb_analysis/evidence/", "wb_analysis/drafts/", "wb_analysis/analysis/",
            ".workbuddy-ai/backup/"]
    miss = [n for n in need if not _gitignore_dir_covered(n, active)]
    if miss:
        return "WARN", f"未忽略（注释掉的不算）：{', '.join(miss)}"

    # ② 行为层：让 git 自己回答（真正的判据）——**逐目录**探针，不漏任何一个
    probe_name = "__probe_transient__.md"
    not_ignored = [d for d in need if not _git_check_ignored(f"{d}{probe_name}")]
    if not_ignored:
        return ("WARN", f"{len(need)} 条规则文本存在，但 `git check-ignore` 判定这些目录"
                       f"**未忽略**：{', '.join(not_ignored)}"
                       f"（rc≠0）⇒ 规则可能被后面的 ! 反转或写法有误")
    return "PASS", f"{len(need)}/{len(need)} 个瞬态目录均已忽略（文本规则 + git 行为双重确认）"


# 根目录允许的 .py：只有 pytest 配置（它必须放在根，否则不被识别）
ROOT_PY_ALLOWED = {"conftest.py"}
ROOT_FILE_ALLOWED = {
    "conftest.py", "pyproject.toml", "README.md", "LICENSE",
    "screen.bat", "start.bat", ".env", ".env.example", ".gitignore",
    "requirements.lock.txt",          # 依赖锁定快照（2026-10-16 新增）
}


def chk_root_clean() -> tuple[str, str]:
    """根目录整洁：**除白名单外的任何文件**都算散件。

    ★ 2026-10-16 修（第三个「检查器静默失效」）。原判据是**双重白名单**：
        p.name not in ROOT_FILE_ALLOWED
        and (p.suffix.lower() in (".log",".tmp",".txt",".csv") or p.name.startswith("_"))
      即「不在文件名白名单」**且**「后缀在白名单内」。后果：`.png`、`nul` 这类
      **不在后缀白名单里**的文件**永远不会被检出**。

      实测：根目录躺着 4 张粘贴截图（`image*.png`）与 1 个名为 `nul` 的残留文件
      （内容是 `ERROR: Invalid pattern is specified in "path:pattern"`，
      某次命令把错误输出重定向到 Windows 保留设备名 `nul` 时误建的真实文件），
      而检查器照样报「✓ PASS 根目录无散落 .py 与临时日志」。

      ⇒ 这与同日修复的另两个属**同一类型**：
        · `_audit_values.SUM_RE`    正则恒不命中（402 行算式 0 命中）
        · `chk_lifecycle`           `strip().startswith("    ")` 恒为假
        · 本函数                     后缀白名单把新类型文件挡在视野外
      共同点：**检查器看着在跑、返回 PASS，实际根本没看到问题。**

      ⇒ 改为**单层判据**：除白名单外，根目录出现任何文件即 WARN。
        新增文件类型无需再打补丁（不必每来一种后缀就改一次代码）。
    """
    stray = sorted(p.name for p in ROOT.iterdir()
                   if p.is_file() and p.name not in ROOT_FILE_ALLOWED)
    if not stray:
        return "PASS", "根目录无散件（仅白名单文件）"
    head = ", ".join(stray[:5]) + (f" 等 {len(stray)} 个" if len(stray) > 5 else "")
    return "WARN", f"根目录有 {len(stray)} 个散件：{head}"


def chk_quant() -> tuple[str, str]:
    # ★★ 2026-10-16 修（本日第 8 例「检查器判据缺陷」，**已精确复现**）：
    #   原判据是 `if "OK" in out`，而被执行代码末句是 `print('OK')`。
    #   **断言失败时 traceback 会回显整行源码**，那行里就含 `print('OK')`
    #   ⇒ 子串命中 ⇒ 实测「`.env` 清空（凭证失效）时仍报 PASS」= **假绿**。
    #   这是**凭证检查**，假绿意味着「体检说凭证正常、实际 EDGAR 会 403」——
    #   铁律 3「静默失败」的典型。
    #   ⇒ 两条修法：① **先验 rc**（真正的判据是退出码，不是输出里有无某串）；
    #     ② 成功标记改成**源码回显里不出现**的形式（见 `_MARK`：它由 chr() 拼出，
    #        源码里没有该字面量 ⇒ 失败回显时不会误命中）。
    _MARK = chr(79) + chr(75)   # == "OK"，但源码中无此字面量
    code = ("import sys; sys.path.insert(0, r'%s');"
            "from quant import screener_engine, stock_pools, edgar_fundamentals, price_history;"
            "ua = edgar_fundamentals.SEC_USER_AGENT;"
            "assert '@' in ua and 'admin@example.com' not in ua, f'SEC 凭证未配置或为默认占位符: {ua}';"
            "print(%r)" % (str(ROOT), _MARK))
    rc, out = run([PY, "-c", code])
    if rc == 0 and _MARK in out:
        return "PASS", "自建包可导入，且 .env 凭证读取正常"
    if "No module named" in out or "ModuleNotFoundError" in out:
        mod = out.strip().splitlines()[-1]
        return "WARN", f"当前解释器缺运行依赖（{mod}）⇒ 请用项目 .venv 运行"
    first = out.strip().splitlines()[-1][:70] if out.strip() else f"(无输出, rc={rc})"
    return "FAIL", f"自建包或凭证异常（rc={rc}）：{first}"


# ── 长期堆积预算 ──────────────────────────────────────────────────────────────
# 目标：项目**长期运行不积累没用的东西**。做法不是"天天清"，而是
#   ① 占用**可见**（PASS 消息也带各项尺寸）；② 每类堆积物有**预算**；③ 超预算时给出**明确出口**。
# 预算依据（2026-09-23 实测基线）：reports 10.0 / _cache 0.13 / backup 4.2 / memory 0.24 MB，
#   **外部缓存 ~/.tradingagents**（prices + cache + edgar + edgar_raw + logs + memory）——
#   它是全项目最大的堆积物、且在仓库之外（`.gitignore` 管不到），此前对任何检查都不可见。
#   ⚠️ 此处**不写死数值**（写死必漂移）：首测 2026-09-23 为 591 MB，其中 cache 占 220 MB；
#      2026-09-26 复测 373 MB —— cache 已降至约 2.5 MB（"按天累积"的旧变体被清掉后不再增殖）。
#      ⇒ 要具体数字请跑 `quant/cleanup_cache.py --status`，不要抄这里的数。
# 预算取余量 ⇒ 正常增长不报警，只在"真积累"时说话（误报过多的闸门等于没有闸门）。
# 「磁盘占用」不是正确性问题 ⇒ 本检查永远不 FAIL。
DISK_BUDGETS: list[tuple[str, str, float, str]] = [
    # (显示名, 路径【绝对=项目外，相对=ROOT 下】, 预算 MB, 超预算时的处置)
    ("reports", "reports", 200.0, "旧版报告可清：先跑 wb_analysis/_reports_index.py --check 定位孤儿/重复，删前先打包回滚包"),
    ("_cache", "wb_analysis/_cache", 50.0, "共享参考数据，可删后由 erp_context.py 等重采"),
    ("backup", ".workbuddy-ai/backup", 40.0, "scripts/_prune_backup.py"),
    ("memory", ".workbuddy-ai/memory", 10.0, "旧日志归档进 _backup/ 并精简"),
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
    """记忆体积 + 索引新鲜度门禁。

    体积部分：宿主的注入是按**字节**截断的（实测 ≈15,000 字节），**超了就静默丢尾部**——
    而尾部恰好是「用户偏好」这类最不该丢的内容。靠"记得精简"必然失效 ⇒ 设成门禁。

    索引部分（2026-10-16 加）：`_INDEX.md` 是「按天日志的主题入口」，
    由 `scripts/_memory_index.py` 生成。**索引过期比没有索引更危险**——
    它会让人以为「就这些主题」，而实际新的判例没进去（与铁律 3 同型：静默失效）。
    """
    p = ROOT / ".workbuddy-ai" / "memory" / "MEMORY.md"
    if not p.exists():
        return "WARN", "未找到 MEMORY.md"
    n = len(p.read_bytes())
    tail_ok = "用户偏好" in p.read_text(encoding="utf-8")

    # 索引新鲜度（与体积合并成一项：同一职责「记忆可维护性」）
    idx_rc, idx_out = run([PY, str(ROOT / "scripts" / "_memory_index.py"), "--check"])
    idx_bad = idx_rc != 0
    idx_note = "；`_INDEX.md` 已过期 ⇒ 跑 `scripts/_memory_index.py`" if idx_bad else ""

    if n > 14800:
        return "FAIL", f"MEMORY.md 已达 {n} 字节（宿主 ≈15000 处截断）⇒ **必须精简**{idx_note}"
    if not tail_ok:
        return "FAIL", f"MEMORY.md 尾部内容缺失（可能已被截断）—— 当前 {n} 字节{idx_note}"
    if idx_bad:
        return "WARN", f"MEMORY.md {n} 字节；记忆索引已过期 ⇒ 跑 `scripts/_memory_index.py`"
    if n > 14200:
        return "WARN", f"MEMORY.md {n} 字节，余量不足（建议压到 14200 以下）{idx_note}"
    return "PASS", f"MEMORY.md {n} 字节，尾部完好；记忆索引最新"


# ★ 确定性回归基线（2026-09-23 立）
#   为什么必须排除 `DeepSeekLive`：那是**真实 API 调用**测试，API 没余额时返回 402 ⇒ 假红。
#   实测过一次：全量跑出 `724 passed, 1 failed`，看起来像代码回归，实际是"余额不足"。
#   ⇒ **能让"改文件找 bug"失效的，不是测试少，而是基线不确定**。
#   基线数 = `python -m pytest tests/ -q -k "not DeepSeekLive"` 的 passed 数。
BASELINE_K = "not DeepSeekLive"
# 2026-10-02：730 → 735。新增 `tests/test_unclosed_bar_time_first.py`（5 项），
#   锁定 `collect.py` 未收盘 bar 检测的「时点优先」修复（原实现以量比为主判据，违反铁律 2，
#   只在交易日盘中后段触发：同一半根 bar 在 11:16 ET 量比 40.3% 被剔除、13:32 ET 量比 60.3% 被写进证据包）。
#   该 WARN「735 > 基线 730」由另一会话发现但未改（不确定文件归属）⇒ 本次确认归属后更新。
# 2026-10-08：737 → 747。新增 `tests/test_earnings_quality_gate.py`（10 项），
#   锁定 `_verify_earnings_quality.py` 的 **Q5 非经营收益闸门**（GOOG 轮实测发现：
#   报表 PE(TTM) 17.3x 看着便宜，实际 55.7% 的 TTM 净利来自未实现权益证券浮盈，
#   剥离后经营性 PE 44.1x）。单测覆盖**双向**：坏夹具（浮盈 61%）必 FAIL、
#   好夹具（4%）必不误报、中间带（15%）只 WARN、负 gain 与缺失值保持沉默。
# 2026-10-15：747 → 752。`tests/test_earnings_quality_gate.py` 新增 5 项
#   `TestQuarterlyReconciliation`，锁定 `_verify_earnings_quality.py::_quarterly_unreliable`
#   —— SKHY（SK 海力士美股 ADR，外国私人发行人）事件：`quarterly_income_stmt` 返回
#   累计/错标期间数据（单季营收 79.319T = FY2025 全年 97.147T 的 81.6%），
#   据此合计 4 季会算出「非经营/净利 +30.0%」的**假 FAIL**（年报口径实为 −19.8%，
#   方向相反，按「只挡抬高方向」本不该触发）。修法：对账失败即强制降级到 FY 口径。
#   单测覆盖双向：坏夹具（单季 81.6% / 合计 1.84×）必命中、好夹具（正常季度 / 强季节性 42%）必不误报。
# 2026-10-16：752 → 766。新增 `tests/test_audit_values_sumregex.py`（14 项），
#   锁定 `_audit_values.py::check_sums` 的正则修复（原 `SUM_RE` 要求 `X% + Y% = Z%`，
#   而真实写法是「（算式：8.79+7.16+…+2.54 = 45.54%）」不带 %、10 项 ⇒ 402 行算式命中 0 行，
#   自洽校验完全失效，本次审计的 4 处「持仓合计」错误全部漏检）。
#   测试三边锁定：真实写法必命中（含加减混合/千分位/10 项）、日期区间不得误报
#   （`1982-1984=100`、`09-16=7.0bp`）、真错误必判不符。
# 2026-10-16（第二批）：766 → 829。新增 3 个文件共 63 项，覆盖「出错就丢数据/失去保护」
#   的三条关键路径（此前 11 个自建流水线脚本中 9 个无测试）：
#   · `tests/test_seal_run_safety.py`（18 项）—— `_seal_run.seal()` 会在校验通过后
#     **unlink 散件**，是全项目唯一「出错就丢东西」的环节。锁定：① 归档名映射（drafts
#     必须保留嵌套相对路径，否则同名文件在包内互相覆盖）；② 静默期拒绝封存（回归
#     2026-09-23「子智能体仍在写就封存」事故）且拒绝时不得动文件；③ **内容级幂等判据**
#     （逐字节一致才可删散件；回归 2026-10-12「只比文件名 ⇒ 删掉新版、留下旧包」事故，
#     含「等长但内容不同」用例，可同时抓出 size-only 与 name-only 两种坏判据）。
#   · `tests/test_derive_a_etf_parsing.py`（29 项）—— A 股 ETF 派生指标是 12 个角色
#     文件的算术前提。锁定解析层契约：`fnum` 取第一个数（不是最后一个）、`kv_from_block`
#     容忍 `- ` 前缀与全角冒号、**跨代码块合并**（回归「§2.1 与 §2.2 是两个独立块，
#     要求单块同时含 MA_5 与 RSI_6 会永远解空」）、以及「格式漂移时必须解出 0 字段
#     以便上层判为不可信」（防静默失败）。
#   · `tests/test_precheck_gate.py`（16 项）—— `_precheck` 是交付前唯一入口。
#     锁定 `crashed()` 能区分「工具崩了」与「工具检出了问题」：崩溃返非零会被误读成
#     「检出问题」、崩溃返零会被当成「通过」（**坏掉的检测器伪装成干净的检测器**，
#     与本日修复的三个 bug 同型）。另锁 `run()` 的 cwd 固定与 UTF-8 强制。
#   三者的「坏夹具必检出」均已实测：注入坏实现后对应用例 FAIL，还原后全绿。
# 2026-10-16（第三批）：829 → 852。新增 `tests/test_reports_index.py`（23 项），
#   覆盖 `_reports_index`（生成 INDEX.md + 报告卫生检查，也是 _health「报告卫生」的实现）。
#   锁定三处真实踩过坑的判据：① `_zip_text`/`_manifest_has` 的**封存后回退**
#   （散落目录被清空本就是正常终态；坏包/坏 JSON 必须返回 None 而非抛异常，
#    否则一处损坏会中断整个索引生成）；② `read_ratings` 的三个字段解析，
#    含 TRAder 列走 PROPOSAL_RE 兜底的**已知边界**（已文档化：pick() 不认 Action 标签，
#    但 scan() 对 47/51 棵有 RUN.json 的树走清单，故真实显示仍是 Title Case）；
#   ③ 报告树命名契约 TREE_RE 与功能目录 SKIP_DIRS。
BASELINE_PASSED = 929
# ★ 2026-10-17（第二次）：921 → 929。依据＝实测 `pytest tests/ -q` 输出「929 passed」，
#   增量 8 项全部来自 `tests/test_health_checkers.py::TestChkGitignoreCommentAware`：
#   锁定本日第 6 例「检查器判据缺陷」—— `chk_gitignore` 的文本层原用**精确相等**
#   （`n not in active`），只认 `wb_analysis/evidence/` 一种写法。而为把常驻宏观数据
#   TREASURY 纳入版本控制，`.gitignore` 被合理改写为 `wb_analysis/evidence/*`
#   + `!wb_analysis/evidence/TREASURY*` —— **git 行为完全正确**（4 个目录探针全部
#   「已忽略」），但文本层因 `dir/*` ≠ `dir/` 误报 WARN ⇒ 体检 FAIL、CI 红。
#   ⇒ 修复：判据放宽为「覆盖」（接受 `dir` / `dir/` / `dir/*` / `dir/**` / `/dir/`），
#     但**坚持排除 `!` 白名单行**（白名单是放行、不是忽略，否则注释/反转类假绿会复发）；
#     同时把行为层从**单个探针**改为**逐目录探针** —— 原实现只探 evidence 一个路径，
#     另 3 个目录的规则若被破坏，行为层**看不见**（与「后缀白名单把新类型文件挡在
#     视野外」是同族盲区）。
#   8 项锁定：5 种等价写法必判「已覆盖」+ 3 条反例（仅白名单 / 仅注释 / 无关目录）。
# ★ 2026-10-17：868 → 921。依据＝实测 `pytest tests/ -q` 输出「921 passed」，
#   增量 53 项全部来自新增 `tests/test_option_source.py`：
#   期权数据源随时点切换（盘中 yfinance / 非盘中 CBOE 官方延迟报价）这条分支此前**无法被测试**
#   —— 它把 `datetime.now()` 写死在函数体里，非盘中那条路径只能靠「某天恰好凌晨跑一次」验证。
#   现将时钟改为可注入（`_thresholds.option_source_decision(now=...)`），两条路径均可被夹具证明。
#   53 项覆盖：时段边界（09:30 含起点 / 16:00 不含终点，两端闭区间化都会静默错配）、
#   源选择与快照声明文案、CBOE 符号解析与同形接口、错误语义（4xx 不重试 / 瞬时错误必重试 /
#   `available()` 吞异常）、**来源声明诚实性**（`source` 由「实际成功」驱动而非「时间判据」——
#   修复前 CBOE 取数失败退回 yfinance 时仍错标成 CBOE 口径），
#   以及「判据不得在消费方本地重写」的单一来源约束（用 tokenize 剔除注释后检查，
#   避免把「这里曾写死过 X」的留痕误报成违规）。
# ★ 2026-10-16（第三次）：864 → 868。依据＝实测 `pytest tests/ -q -k "not DeepSeekLive"`
#   输出「868 passed」，增量 4 项来自新增 `tests/test_gate_false_green.py`：
#   锁定本日第 8/9 例『假绿』（chk_quant 凭证检查被源码回显骗过 /
#   _check_role_files 空草稿被判通过）。两者均已用『注入坏实现必 FAIL』验证测试有判别力。
# ★ 2026-10-16（第二次）：858 → 864。依据＝实测 `pytest tests/ -q -k "not DeepSeekLive"`
#   输出「864 passed」，增量 6 项来自新增 `tests/test_health_checkers.py`：
#   锁定本日第 5/6/7 例『检查器判据缺陷』（chk_gitignore 注释不算忽略 /
#   chk_seal 解析失败不得默认 0 / chk_reports 工具崩溃不得假绿），
#   并已用 `_verify_new_tests_have_teeth.py` 验证**测试本身有判别力**（注入坏实现必 FAIL）。
# ★ 2026-10-16：852 → 858。依据＝实测 `pytest tests/ -q -k "not DeepSeekLive"`
#   输出「858 passed」，增量 6 项来自 `test_audit_values_sumregex.py` 补齐的
#   「右侧带显式正负号」算式用例（EXPR_RE 剩余缺口修复的回归保护）。

# safe-delete 钩子的批量确认标记：出现它说明「删除被拦」而非「测试没收集」。
SAFE_DELETE_MARK = "SAFE_DELETE_BULK_CONFIRM_REQUIRED"


def chk_tests() -> tuple[str, str]:
    """回归门禁：与确定性基线比。少了 ⇒ 真回归（FAIL）；多了 ⇒ 有新测试没更新基线（WARN）。

    ★ 2026-10-10 修正：加 `--basetemp`（**每轮唯一**）。为什么值得写进代码：

    此前 pytest 用默认临时目录，会在会话结束时按保留策略**批量删除**旧的
    `pytest-of-<user>/garbage-*`。本机 safe-delete 钩子的 bulk 阈值是 **50 条/轮**，
    实测一次运行要删 **92** 项 ⇒ 钩子抛 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`
    并**直接中止 pytest 进程**。后果极其隐蔽：

      · 全部用例**其实已经跑完**（进度点打到 100%，实测 747 passed）；
      · 但汇总行 `N passed` 因进程被中止而**从未打印**；
      · ⇒ 本检查把**满绿的套件**报成 `✗ FAIL 测试未能收集（语法/导入错误？）`，
        把一个**根本没有的语法错误**写进健康表，并把退出码推成 1。

    「把绿报成红」和「把红报成绿」一样危险（铁律 3 的镜像）：
    前者会让人**不再相信门禁**，后者会让人**相信错的结论**。
    传一个**尚不存在**的 basetemp 会让 pytest 走 `given_basetemp` 分支、
    跳过那套垃圾回收，从而不再触发钩子。basetemp 带 pid 后缀以保证每轮都是新的。
    """
    import tempfile

    bt = Path(tempfile.gettempdir()) / f"ta-pytest-bt-{os.getpid()}"
    rc, out = run([PY, "-m", "pytest", "tests/", "-q", "--no-header", "-k", BASELINE_K,
                   "--basetemp", str(bt)], timeout=600)
    m = re.search(r"(\d+) passed", out)
    if not m:
        if SAFE_DELETE_MARK in out:
            return "FAIL", ("pytest 疑似已跑完但收尾被 safe-delete 钩子中止（未打印汇总行）—— "
                            "本检查已加 --basetemp，若仍出现请核查钩子阈值")
        if "No module named" in out or "ModuleNotFoundError" in out:
            return "WARN", "当前解释器未安装 pytest 或测试依赖 ⇒ 请用项目 .venv 运行"
        return "FAIL", "测试未能收集（语法/导入错误？）"
    n = int(m.group(1))
    if n < BASELINE_PASSED:
        return "FAIL", f"回归：{n} passed < 基线 {BASELINE_PASSED}（少 {BASELINE_PASSED - n} 个）"
    if n > BASELINE_PASSED:
        return "WARN", f"{n} passed > 基线 {BASELINE_PASSED} ⇒ 有新测试，请更新 BASELINE_PASSED"
    return "PASS", f"{n} passed，与确定性基线一致（已排除真实 API 测试）"


# ⚠️ **不要加 `\b`** —— 首版写成 `\b\d{2,}\s*个\s*(...)\b`，
#   而 `\b` 在「中文 ↔ 数字」边界上不可靠：`有 999 个单元测试` 实测**不匹配**，
#   于是注入的真漂移被漏掉（双边测试才发现）。CJK 场景下用 `\d{2,}` 直接起头即可。
_DOC_COUNT_RE = re.compile(r"\d{2,}\s*个\s*(单元测试|测试|脚本|\.py|通道)")
_DOC_BARE_CMD_RE = re.compile(r"\bpython\s+([A-Za-z_][A-Za-z0-9_]*)\.py")
_DOC_BARE_IMP_RE = re.compile(r"^\s*from\s+([A-Za-z_][A-Za-z0-9_]*)\s+import", re.M)
# ④ 行号引用 —— ★ 2026-10-10 新增。行号是**必然漂移**的引用方式：本轮实测 4 处
#   （`collect.py:686` / `wb_deep_dive.py:38` / `smart_screener.py:71` / `screener_engine.py` 的 L459）
#   全部在源码改动后失真，且**读到的人无从分辨真假**。项目原则：要引用就写**符号名**，
#   让读者自己 grep —— 判别力的代价是零，收益是整类失效被根除。
_DOC_LINE_REF_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.py:\d+"
                              r"|(?<![A-Za-z0-9_])L\d{2,}(?![0-9])")
_DOC_WARN_WORDS = ("不写", "禁止", "必漂移", "刻意", "历史教训", "实测", "已全部与现状不符", "别再")


def _doc_is_warning_context(t: str, pos: int) -> bool:
    """该位置是否处于「告诫别人别这么写」的语境。

    ⚠️ 判据必须**行内为主**：首版用「前后各 400 字符」的段落窗口，
    结果把注入在文档**末尾**的真漂移给漏掉了（远处恰好有告诫词）——
    窗口过宽 ⇒ 判别力退化。现改为：只看**本行**（± 上一行），
    加一个引用块判定。这正是铁律 20「豁免表改后双边必测」要防的退化。
    """
    line_start = t.rfind("\n", 0, pos) + 1
    line_end = t.find("\n", pos)
    line = t[line_start: line_end if line_end != -1 else len(t)]
    if line.lstrip().startswith(">"):          # Markdown 引用块
        return True
    # 再看紧邻的上一行（告诫常写在数字行的正上方，如 `> 历史教训：…`）
    prev_start = t.rfind("\n", 0, max(0, line_start - 1)) + 1
    prev_line = t[prev_start: max(0, line_start - 1)]
    return any(w in line or w in prev_line for w in _DOC_WARN_WORDS)


def scan_doc_text(name: str, text: str, pkg_mods: set[str]) -> list[str]:
    """扫一份文档文本，返回漂移命中列表（**纯函数** ⇒ 可被 `_selftest` 双边夹具直接调用）。

    ★ 2026-10-10 从 `chk_doc_drift` 内联逻辑抽出。抽出的理由就是本项目的自检原则：
    「没有自检的门禁只是更隐蔽的静默失败源」—— 检测器必须能脱离真实文件系统被双向验证。
    """
    hits: list[str] = []

    def _add(pos: int, msg: str) -> None:
        ln = text[:pos].count("\n") + 1
        hits.append(f"{name}:L{ln} {msg}")

    for m in _DOC_COUNT_RE.finditer(text):
        if not _doc_is_warning_context(text, m.start()):
            _add(m.start(), f"硬编码计数「{m.group(0).strip()}」")
    for m in _DOC_BARE_CMD_RE.finditer(text):
        if m.group(1) in pkg_mods and not _doc_is_warning_context(text, m.start()):
            _add(m.start(), f"旧路径 `python {m.group(1)}.py`（实际在 quant/）")
    for m in _DOC_BARE_IMP_RE.finditer(text):
        if m.group(1) in pkg_mods and not _doc_is_warning_context(text, m.start()):
            _add(m.start(), f"旧 import `from {m.group(1)} import`（实际在 quant/）")
    for m in _DOC_LINE_REF_RE.finditer(text):
        if not _doc_is_warning_context(text, m.start()):
            _add(m.start(), f"行号引用「{m.group(0)}」（行号必漂移 ⇒ 改写符号名，让读者自己 grep）")
    return hits


def _doc_drift_scope() -> list[Path]:
    """文档漂移检查的**扫描面**。

    ★ 2026-10-10 扩面：原先只扫 `docs/*.md` ⇒ **`.workbuddy-ai/memory/**` 完全不在门禁内**，
    这正是实测 13 处陈旧数字/漂移行号长期零告警的根因（`IRONLAWS.md` 的「8 个标签」、
    `DOMAINS.md` 的「21.5x」「collect.py:686」全在此列）。
    ⇒ 凡「会被当成权威口径引用」的 md 都纳入，**唯独当日流水除外** ——
    它是 append-only 的**历史记录**（写"当时实测是 L686"是如实留痕，改了反而失真）。
    """
    out: list[Path] = list((ROOT / "docs").glob("*.md"))
    mem = ROOT / ".workbuddy-ai" / "memory"
    if mem.exists():
        out += [p for p in mem.glob("*.md")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name)]
    sk = ROOT / ".workbuddy-ai" / "skills"
    if sk.exists():
        out += list(sk.glob("*/SKILL.md"))
    for nm in ("README.md", "CHANGELOG.md"):
        p = ROOT / nm
        if p.exists():
            out.append(p)
    fw = ROOT / "wb_analysis" / "FRAMEWORK.md"
    if fw.exists():
        out.append(fw)
    return sorted({p.resolve() for p in out})


def chk_doc_drift() -> tuple[str, str]:
    """文档里是否又写死了会漂移的数字 / 用了迁移前的旧命令路径。

    ★ 2026-10-08 新增。为什么值得单列一项：

    实测 `docs/WORKFLOW.md` 曾写「**508 个单元测试**」，而实际已 737 —— 差 229，
    却**无人察觉**，因为没人会记得回来改。更糟的是该文档有 **19 处命令用旧路径**
    （`python wb_deep_dive.py`、`from screener_engine import ...`），
    而自 2026-09-23 起这些代码已全部移入 `quant/` 包 ⇒ **照文档抄命令直接报错**。

    项目已有两条明确原则，本检查是把它们从"纪律"变成"代码"：
      · 「能靠代码根除的写进代码，不靠『记得注意』」
      · 「同一口径只在一个地方写一遍 —— 写两遍必然漂移」

    ⇒ 检测**四类**信号（命中即 WARN，不阻断交付，但必须处理）：
      ① 文档里出现 `N 个单元测试 / N 个脚本 / N 个 .py` 这类硬编码计数；
      ② 文档示例命令用了**根目录裸模块名**（`python xxx.py` 但该文件实际在 `quant/`）；
      ③ `from <模块> import` 而该模块实际在 `quant/` 包内；
      ④ **行号引用**（`xxx.py:123` 或裸 `L123`）—— 行号必漂移，要引用就写符号名。

    ★ **2026-10-10 扩面**：原先只扫 `docs/*.md`（5 份）⇒ `.workbuddy-ai/memory/**` 与 skill 文档
    **完全不在门禁内**，这正是实测 13 处陈旧断言长期零告警的根因 ⇒ 扫描面扩到 12 份
    （见 `_doc_drift_scope()`）；**唯独当日流水 `YYYY-MM-DD.md` 豁免**（它是 append-only 的历史记录）。

    ⚠️ **判别力要求（铁律 20）**：必须能区分「真的写死了数字」与「正在警告别人别写死数字」。
    实测首次运行就把 `WORKFLOW.md` / `PROJECT_MAP.md` 里**两处反例说明**误报为漂移 ——
    那两行恰恰是「本表刻意不写数量」的告诫本身。⇒ 加 `_is_warning_context()` 排除
    引用块（`>` 开头）、以及同段含「不写 / 刻意 / 历史教训 / 实测」等告诫词的场合。
    """
    docs = _doc_drift_scope()
    # `TOOLS.md` 由 `_tidy_scripts.py --apply` 自动重建，数字本就每次刷新 ⇒ 豁免。
    EXEMPT = {"TOOLS.md"}
    hits: list[str] = []

    # quant/ 包内真实存在的模块名（用于判「裸名其实在包里」）
    pkg_mods = {p.stem for p in (ROOT / "quant").glob("*.py") if p.stem != "__init__"}

    for d in sorted(docs):
        if d.name in EXEMPT:
            continue
        hits += scan_doc_text(d.name, d.read_text(encoding="utf-8"), pkg_mods)

    if hits:
        head = "；".join(hits[:3])
        more = f"（共 {len(hits)} 处）" if len(hits) > 3 else ""
        return "WARN", f"{len(hits)} 处文档漂移{more}：{head}"
    return "PASS", f"{len(docs)} 份文档无硬编码计数、无旧路径、无行号引用"


def chk_scorecard() -> tuple[str, str]:
    """记分卡覆盖度：「越用越好」要有度量，未打分的交付就是没度量。

    ★ 2026-10-15 修：使用 `TREE_RE` 与 `FUNC_DIRS` 过滤有效报告树，并校验 `QUALITY.csv`
      是否存在空 ticker 的脏行（此前 `reports/SKHY/_archive` 被两边同时计入，造成 50/50 假绿）。
    """
    csv = ROOT / "reports" / "QUALITY.csv"
    n_trees = 0
    reports = ROOT / "reports"
    if reports.exists():
        for d in reports.iterdir():
            if d.is_dir() and d.name not in FUNC_DIRS:
                n_trees += len([x for x in d.iterdir() if x.is_dir() and TREE_RE.match(x.name)])
    if not csv.exists():
        return ("WARN", f"{n_trees} 轮交付但无记分卡 ⇒ 跑 wb_analysis/_scorecard.py") if n_trees else \
               ("PASS", "尚无交付轮次")
    rows = [l for l in csv.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]
    bad_rows = [l for l in rows if l.startswith(",")]
    if bad_rows:
        return "WARN", f"记分卡含 {len(bad_rows)} 条非报告树脏记录 ⇒ 重跑 wb_analysis/_scorecard.py"
    if len(rows) != n_trees:
        return "WARN", f"记分卡 {len(rows)} 轮 ≠ 交付 {n_trees} 轮 ⇒ 跑 wb_analysis/_scorecard.py 同步"
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
    ("文档漂移", chk_doc_drift),
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
