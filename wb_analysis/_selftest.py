# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_selftest.py
"""门禁自检 —— 证明「检测器本身」还在正常工作。

━━━ 为什么必须有这个脚本 ━━━
本项目最贵的教训是一条规律：**静默失败比报错危险得多**。
它在本项目已经以多种面貌反复出现：通道报成功但内容是占位串、子智能体写出证据包里
不存在的数字、简报分项被反向编造、`assemble.py` 把空骨架渲染成"报告"、
`_lint_drafts.py` 检出 8 处违规却返回退出码 0……

于是我们给流程加了一堆门禁。**但门禁自己也会坏。** 而门禁坏掉时，症状恰恰是
「一切正常」—— 这与它要防的东西是同一类失败。所以：

    **没有自检的门禁，等于一个更隐蔽的静默失败源。**

本脚本用**合成夹具**（临时目录里现造，不依赖任何真实草稿）双向验证每个检测器的契约：

    坏夹具  → 必须被检出 + 退出码非零     （否则是「漏报」）
    好夹具  → 必须零违规 + 退出码为零     （否则是「误报」）

两个方向都要断言，缺一个都会退化：
只测坏夹具 → 检测器变成「永远报错」也能过；
只测好夹具 → 检测器变成「永远通过」也能过。

用法：
    python wb_analysis/_selftest.py            # 跑全部，退出码 0 = 全过
    python wb_analysis/_selftest.py -v         # 附上每个夹具的完整输出
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


# ─────────────────────────────────────────────────────────────────────────────
# 「契约常量不得被本地重写」的**静态检测器**（2026-10-10 新增）
#
# 背景：`_contract.py` 建好后，旧的守门断言只检查「消费方源码里出现过 `_contract import`
# 这一串字符串」。于是出现了一条**骗过断言的路径**：
#     `_verify_ratings.py` 顶部 `import DOC_FILES as _DOC_ALL`（**import 了**），
#     但正文**又本地定义了一份同值的 `DOC_FILES`** → 断言通过，漂移照样发生。
# 这与「同一份契约被 8 个文件各写一遍」是同一类失败，只是入口更隐蔽。
#
# ⇒ 判据升级为**语法级**：解析 AST，检查有没有「顶层 `X = <手写字面量>`」且 X 是受保护常量名。
#   · **违规**：`RATING_ALLOWED_FILES = {"manager.md", "trader.md"}`（手抄一份值）
#   · **合法**：`DOC_FILES = {f for f in _DOC_ALL if f.startswith("_")}`（**从常量派生**，有意收窄）
# ⇒ 关键区别是「值从哪来」，不是「名字存不存在」。派生是收窄口径，抄写是制造第二个来源。
# ─────────────────────────────────────────────────────────────────────────────

_LITERAL_WRAPPERS = {"frozenset", "set", "tuple", "list", "dict"}


def _is_handwritten_literal(node: ast.AST | None) -> bool:
    """右侧是不是「手写的值」？（常量，或由常量层层组成的容器/包装调用）"""
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_handwritten_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return (all(_is_handwritten_literal(k) for k in node.keys if k is not None)
                and all(_is_handwritten_literal(v) for v in node.values))
    # `frozenset({...})` / `tuple([...])` 一类包装：值仍然是手抄的 ⇒ 照样算违规
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _LITERAL_WRAPPERS and len(node.args) == 1):
        return _is_handwritten_literal(node.args[0])
    return False


def literal_redefinitions(src: str, protected: set[str]) -> list[tuple[int, str]]:
    """返回 [(行号, 常量名)] —— 源码里用**字面量**给受保护常量名赋值的位置。

    只扫**顶层**语句（函数内的局部变量不构成第二个"来源"）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[tuple[int, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            val = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            val = node.value
        else:
            continue
        if not _is_handwritten_literal(val):
            continue
        for nm in names:
            if nm in protected:
                out.append((node.lineno, nm))
    return out


# ── `reports/` 布局常量的同源守卫（2026-10-10）──────────────────────────────
# 背景：`TREE_RE` 与「功能目录集」各有 **3~4 份逐字拷贝**，归档跳过表又有 4 份 ——
# 它们已上提为 `wb_analysis/_paths.py`。本检测器把「下一个人又本地抄一遍」这条路堵死。
# 判据要求**同一行内**同时命中，且**整行注释直接跳过** —— 否则「告诫别人别这么写」的留痕
# 会被误判（假阳性正是本项目反复踩到的形态：告诫语与真违规长得一样）。
_FUNC_DIR_KEYS = ('"_datasets"', '"_other"', '"_archive"', '"_audit"')


def paths_literal_definitions(src: str) -> list[str]:
    """在一份源码文本里找出「又本地重写 `_paths` 常量」的行（纯函数 ⇒ 可被双边夹具调用）。"""
    out: list[str] = []
    for i, ln in enumerate(src.splitlines(), 1):
        if ln.strip().startswith("#"):
            continue
        if "re.compile" in ln and r"\d{8}" in ln and r"\d{6}" in ln:
            out.append(f"{i}:TREE_RE")
        elif all(k in ln for k in _FUNC_DIR_KEYS):
            out.append(f"{i}:FUNC_DIRS")
        elif '"_stale"' in ln and '"_archive"' in ln:
            out.append(f"{i}:SKIP_ARCHIVE_DIRS")
    return out

# 一份「合规」的最小十二角色草稿。
# 关键点：五个档位英文词**只允许**出现在结论块/契约块。
GOOD = {
    "1_analysts/market.md": "# 市场分析\n\n**基准日**：2026-01-01　收盘 **100.00**\n\n结构位 **99.00**。\n",
    "1_analysts/fundamentals.md": "# 基本面分析\n\n聚合 PE **20.00**。\n",
    "1_analysts/news.md": "# 新闻分析\n\n净影响中性。\n",
    "1_analysts/sentiment.md": "# 情绪分析\n\n**Overall Sentiment**: Neutral\n\n六档中的中性档。\n",
    "2_research/bull.md": "# 牛派\n\n**Stance**: **Bullish**\n\n看多理由。\n",
    "2_research/bear.md": "# 熊派\n\n**Stance**: **Bearish**\n\n看空理由。\n",
    "2_research/manager.md": "# 研究经理\n\n## 结论块（置于文首）\n\n**Recommendation**: Hold\n\n**Rationale**: 证据平衡。\n",
    "3_trading/trader.md": (
        "# 交易员\n\n## 结论块\n\n**Action**: Hold\n\n**Reasoning**: 观望。\n\n"
        "**Entry Price**: 100.00\n\n**Stop Loss**: 95.00\n\n"
        "正文一律用中文表述方向。\n\nFINAL TRANSACTION PROPOSAL: **HOLD**\n"
    ),
    "4_risk/aggressive.md": "# 激进派\n\n## 结论块\n\n**Rating**: Hold\n\n主张在条件满足时放大敞口。\n",
    "4_risk/conservative.md": "# 保守派\n\n## 结论块\n\n**Rating**: Hold\n\n主张收缩敞口。\n",
    "4_risk/neutral.md": "# 中性派\n\n## 结论块\n\n**Rating**: Hold\n\n给出条件化中间路径。\n",
    "4_risk/portfolio_manager.md": "# 组合经理\n\n## 结论块\n\n**Rating**: Hold\n\n**Executive Summary**: 维持中性档。\n",
}

BLACKLIST = '{"99.99": "示例旧值"}'


def build_fixture(root: Path, broken: bool) -> Path:
    """造一份夹具。broken=True 时注入若干**已知的**违规。"""
    d = root / ("bad" if broken else "good")
    for rel, body in GOOD.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="\n")

    (d / "_value_blacklist.json").write_text(BLACKLIST, encoding="utf-8", newline="\n")
    (root / "evidence.md").write_text("# 证据\n\n收盘 **100.00**。\n", encoding="utf-8", newline="\n")

    if not broken:
        return d

    # 违规 1：正文出现裸五档英文词（应为 0 处）
    p = d / "1_analysts/market.md"
    t = p.read_text(encoding="utf-8")
    p.write_text(t + "\n方向判断：Buy（本条为故意注入的违规）\n", encoding="utf-8", newline="\n")

    # 违规 2：manager 缺少契约要求的 **Recommendation** 字段
    p = d / "2_research/manager.md"
    t = p.read_text(encoding="utf-8").replace("**Recommendation**", "**Conclusion**")
    p.write_text(t, encoding="utf-8", newline="\n")

    # 违规 3：交易员的 FINAL 行不在**文件末行**（反读校验器的硬要求）
    p = d / "3_trading/trader.md"
    t = p.read_text(encoding="utf-8").replace("FINAL TRANSACTION PROPOSAL: **HOLD**\n", "")
    p.write_text(t + "\nFINAL TRANSACTION PROPOSAL: **HOLD**\n\n*这是一句把契约行挤走的收尾注。*\n",
                 encoding="utf-8", newline="\n")

    # 违规 4：引用了黑名单里的旧值（无任何豁免语境）
    p = d / "4_risk/conservative.md"
    p.write_text("# 保守派\n\n## 结论块\n\n**Rating**: Hold\n\n当前估值为 99.99 倍。\n", encoding="utf-8", newline="\n")
    return d


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def rc(cmd: list[str], cwd: Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def load_module(name: str, filename: str):
    """按文件路径 import 一个脚本模块（本目录的脚本不是包，只能这样加载）。"""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_assemble():
    return load_module("_asm", "assemble.py")


def main() -> int:
    ap = argparse.ArgumentParser(description="门禁自检")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印各夹具的完整输出")
    args = ap.parse_args()

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    with tempfile.TemporaryDirectory(prefix="wb_selftest_") as tmp:
        tmp = Path(tmp)
        good = build_fixture(tmp, broken=False)
        bad = build_fixture(tmp, broken=True)
        ev = tmp / "evidence.md"

        # ---- 1. 数字溯源 / 契约（lint）----
        g_rc, g_out = rc([PY, str(HERE / "_lint_drafts.py"), str(good), str(ev)], tmp)
        b_rc, b_out = rc([PY, str(HERE / "_lint_drafts.py"), str(bad), str(ev)], tmp)
        detail = (f"good_rc={g_rc} bad_rc={b_rc}")
        check("lint: 好夹具零违规且 rc=0", g_rc == 0 and "✗" not in g_out, detail)
        check("lint: 坏夹具被检出且 rc≠0", b_rc != 0 and "✗" in b_out, detail)

        # ---- 2. 评级词 / 契约字段 ----
        g_rc, g_out = rc([PY, str(HERE / "_verify_ratings.py"), str(good)], tmp)
        b_rc, b_out = rc([PY, str(HERE / "_verify_ratings.py"), str(bad)], tmp)
        check("verify_ratings: 好夹具 rc=0", g_rc == 0, f"good_rc={g_rc}")
        check("verify_ratings: 坏夹具 rc≠0", b_rc != 0, f"bad_rc={b_rc}")

        # ---- 3. 口径一致性 ----
        bl = str(bad / "_value_blacklist.json")
        g_rc, g_out = rc([PY, str(HERE / "_audit_values.py"), str(good), "--stale", bl], tmp)
        b_rc, b_out = rc([PY, str(HERE / "_audit_values.py"), str(bad), "--stale", bl], tmp)
        check("audit_values: 好夹具 rc=0", g_rc == 0, f"good_rc={g_rc}")
        check("audit_values: 坏夹具 rc≠0（检出旧值）", b_rc != 0, f"bad_rc={b_rc}")

        # ---- 3b. 订正残留检查器（_check_residuals 双边夹具）----
        try:
            cr_mod = load_module("_cr_mod", "_check_residuals.py")
            res_good = tmp / "res_good"
            res_bad = tmp / "res_bad"
            for d_r, line_txt in (
                (res_good, "订正说明：原写 -5.02% 已改为 -5.365%。\n"),
                (res_bad, "昨日跳空幅度为 -5.02%，显示恐慌。\n"),
            ):
                (d_r / "1_analysts").mkdir(parents=True, exist_ok=True)
                (d_r / "_corrections.json").write_text(json.dumps({
                    "corrections": [{"old": "-5.02%", "new": "-5.365%", "fixed_in": ["0_brief.md"]}]
                }), encoding="utf-8")
                (d_r / "1_analysts" / "sentiment.md").write_text(line_txt, encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_rg = cr_mod.check(res_good)
                rc_rb = cr_mod.check(res_bad)
            check("check_residuals: 留痕不误报(rc=0) / 真残留必检出(rc=1)",
                  rc_rg == 0 and rc_rb == 1, f"good_rc={rc_rg} bad_rc={rc_rb}")
        except Exception as e:  # noqa: BLE001
            check("check_residuals: 留痕不误报(rc=0) / 真残留必检出(rc=1)", False, f"加载失败 {e}")

        # ---- 4. 交付前统一门禁 ----
        g_rc, g_out = rc([PY, str(HERE / "_precheck.py"), str(good), "--evidence", str(ev)], tmp)
        b_rc, b_out = rc([PY, str(HERE / "_precheck.py"), str(bad), "--evidence", str(ev)], tmp)
        check("precheck: 好夹具 rc=0", g_rc == 0, f"good_rc={g_rc}")
        check("precheck: 坏夹具 rc=1", b_rc == 1, f"bad_rc={b_rc}")

        # ---- 4b. cwd 无关性（回归测试）----
        # 实测过一次真实缺陷：`_check_freshness.py` 把 evidence 目录写成**相对路径**，
        # 于是换个目录调用就误报「证据包缺失」。
        # ⇒ 钉一条断言：同一输入在**不同工作目录**下必须得到同样的结论。
        elsewhere = tmp / "elsewhere"
        elsewhere.mkdir()
        e_rc, e_out = rc([PY, str(HERE / "_precheck.py"), str(good), "--evidence", str(ev)], elsewhere)
        consistent = (e_rc == g_rc)
        check("precheck: 换工作目录后结论一致", consistent,
              f"根目录 rc={g_rc} / 其他目录 rc={e_rc}")
        if not consistent and args.verbose:
            print("\n----- 换目录后的输出 -----\n" + e_out[-800:])

        # ---- 5. 渲染器的空正文硬门禁（单元级）----
        asm = load_assemble()
        empty_skeleton = {"ticker": "X", "as_of": "2026-01-01", "ratings": {},
                          "analysts": {"market": "", "sentiment": "", "news": "", "fundamentals": ""},
                          "research": {"bull": "", "bear": "", "manager": ""},
                          "trading": {"trader": ""},
                          "risk": {"aggressive": "", "conservative": "", "neutral": "", "portfolio_manager": ""}}
        full = {"analysts": {"market": "a", "sentiment": "b", "news": "c", "fundamentals": "d"},
                "research": {"bull": "e", "bear": "f", "manager": "g"},
                "trading": {"trader": "h"},
                "risk": {"aggressive": "i", "conservative": "j", "neutral": "k", "portfolio_manager": "l"}}
        n_empty = len(asm.check_completeness(empty_skeleton))
        n_full = len(asm.check_completeness(full))
        check("assemble: 空骨架被识别（12 个空小节）", n_empty == 12, f"检出 {n_empty}")
        check("assemble: 完整数据不误报", n_full == 0, f"检出 {n_full}")

        # ---- 6. 两处「五档词白名单」必须一致（防漂移）----
        # 实测过一次真实不一致：`_lint_drafts.py` 允许 6 个席位用五档词，
        # 而 `_verify_ratings.py` 只允许 3 个 ⇒ **同一份草稿会得到两种结论**。
        # 这类「两个工具对同一契约判断相反」的漂移必须钉住。
        try:
            lint_mod = load_module("_lint2", "_lint_drafts.py")
            vr_mod = load_module("_vr2", "_verify_ratings.py")
            a = set(lint_mod.RATING_ALLOWED_FILES)
            b = {Path(x).name for x in vr_mod.FIVE_ALLOWED}
            check("白名单一致：lint 与 verify_ratings", a == b,
                  f"仅 lint 有={sorted(a - b)} 仅 vr 有={sorted(b - a)}")
        except Exception as e:                                   # noqa: BLE001
            check("白名单一致：lint 与 verify_ratings", False, f"加载失败 {e}")

        # ---- 7. 健康检查的「堆积预算」检测器（双边；防退化成恒 PASS 或恒 WARN）----
        # 前身是「编译缓存」单项检查 —— 2026-09-23 实测它曾因判据恒真而**恒 PASS**
        #（82 个 .pyc 报「无残留」），这正是本文件要防的「看着在工作、其实什么也没检」。
        # 现改为整体堆积预算 ⇒ 双边夹具改为：超预算必 WARN（且消息带处置命令）、
        # 预算内必 PASS（且消息带各项尺寸 —— **占用可见性本身是功能**，PASS 也不能只说"正常"）。
        # 夹具刻意用**合成预算表**（含相对 + 绝对两种路径），不依赖真实机器的磁盘状态——
        # 否则真实磁盘一旦合法超预算，自检会跟着假红。
        try:
            h = load_module("_health_h", str(HERE.parent / "scripts" / "_health.py"))
            fake = tmp / "fakeproj"
            (fake / ".workbuddy-ai" / "backup").mkdir(parents=True)
            (fake / ".workbuddy-ai" / "backup" / "b.zip").write_bytes(b"\x00" * 4096)

            orig_root, orig_budgets = h.ROOT, h.DISK_BUDGETS
            h.ROOT = fake
            # 反例：预算 0.001MB ⇒ 4096 字节的包也必须被拦下（相对路径命中）
            h.DISK_BUDGETS = [
                ("backup", ".workbuddy-ai/backup", 0.001, "scripts/_prune_backup.py"),
                ("外部缓存", str(fake / ".tradingagents"), 0.001, "quant/cleanup_cache.py"),
            ]
            lvl_bad, msg_bad = h.chk_disk_budget()
            # 正例：同一夹具、真实量级的预算 ⇒ 必须安静通过且报尺寸（绝对路径不存在的目录 ⇒ 0.0MB）
            h.DISK_BUDGETS = [
                ("backup", ".workbuddy-ai/backup", 30.0, "scripts/_prune_backup.py"),
                ("外部缓存", str(fake / ".tradingagents"), 1024.0, "quant/cleanup_cache.py"),
            ]
            lvl_ok, msg_ok = h.chk_disk_budget()
            h.ROOT, h.DISK_BUDGETS = orig_root, orig_budgets

            check("health: 超预算必 WARN 且带处置",
                  lvl_bad == "WARN" and "_prune_backup" in msg_bad,
                  f"{lvl_bad} / {msg_bad[:60]}")
            check("health: 预算内 PASS 且报尺寸",
                  lvl_ok == "PASS" and "backup" in msg_ok and "外部缓存" in msg_ok,
                  f"{lvl_ok} / {msg_ok[:60]}")
        except Exception as e:                                   # noqa: BLE001
            check("health: chk_disk_budget 双边", False, f"加载失败 {e}")

        # ---- 6.5 文档漂移检测器：扩面 + 行号规则（2026-10-10 新增）----
        # 背景：`chk_doc_drift` 原先只扫 `docs/*.md`（5 份），`.workbuddy-ai/memory/**` 与 skill 文档
        # **完全在门禁外** ⇒ 实测 13 处陈旧断言（IRONLAWS 的「8 个标签」、DOMAINS 的「21.5x」
        # 「collect.py:686」…）长期零告警。扩面后新增第 ④ 类规则「行号引用」。
        # 夹具**脱离真实文件系统**（检测逻辑已抽成纯函数 `scan_doc_text`）——
        # 否则真实文档一旦合法，自检会跟着假绿（这正是本文件存在的理由）。
        try:
            h2 = load_module("_health_dd", str(HERE.parent / "scripts" / "_health.py"))
            pkg = {"wb_deep_dive", "smart_screener"}
            bad = ("共 508 个单元测试。\n"
                   "见 `collect.py:686` 与 L459。\n"
                   "运行 python wb_deep_dive.py 即可。\n")
            good = ("> 历史教训：本表曾写「508 个单元测试」，早已过时。\n"
                    "⚠️ 正文里禁止写行号（`xxx.py:123` 必漂移）。\n"
                    "**刻意不写行号** —— 原文给的行号实测均已漂移。\n"
                    "运行 python quant/wb_deep_dive.py 即可。\n")
            hit_bad = h2.scan_doc_text("BAD.md", bad, pkg)
            hit_good = h2.scan_doc_text("GOOD.md", good, pkg)
            kinds = " ".join(hit_bad)
            check("doc_drift: 坏夹具必检出（计数+旧路径+行号）",
                  len(hit_bad) == 4 and "计数" in kinds and "旧路径" in kinds and "行号引用" in kinds,
                  f"命中 {len(hit_bad)}：{kinds[:70]}")
            check("doc_drift: 告诫语境与 quant/ 正路径不误报",
                  hit_good == [], f"命中 {len(hit_good)}：{str(hit_good)[:60]}")
            scope = {p.name for p in h2._doc_drift_scope()}
            check("doc_drift: 扫描面已含 memory/ 与 SKILL.md",
                  {"IRONLAWS.md", "DOMAINS.md", "MEMORY.md", "SKILL.md"} <= scope,
                  f"{len(scope)} 份：{sorted(scope)[:6]}")
        except Exception as e:                                   # noqa: BLE001
            check("doc_drift: 双边夹具", False, f"加载失败 {e}")

        # ---- 7. 契约常量的「唯一来源」没有被绕过（2026-10-08 新增）----
        # 背景：同一个契约曾被 8 个文件各自定义，大小写容忍度还不一致 ——
        # 于是同一个 trader.md 在两道门禁里被判成**不同事实**，只能靠人来回试到收敛。
        # `_contract.py` 建好后，**唯一的失败模式就是有人又手写一遍正则**。
        # 这条断言把那条路堵死：逐个扫描消费方，若发现它们**没有 import `_contract`**，
        # 就直接判失败（比"记得改同步"可靠得多 —— 纪律会忘，断言不会）。
        # ★ 2026-10-10 升级：名单**扩充**到所有实际持有契约常量的消费方
        #   （`assemble.py` / `_verify_report.py` / `_reports_index.py` 此前**完全不在守护范围内**），
        #   判据也从「字符串里有没有 import」升级为「**有没有用字面量重写**」——
        #   后者才是真判据：import 了再抄一份同样制造第二个来源。
        CONSUMERS = [
            "_lint_drafts.py", "_verify_ratings.py", "_gen_meta.py",
            "_check_role_files.py", "_strip_stray_ratings.py",
            "assemble.py", "_verify_report.py", "_reports_index.py",
        ]
        not_importing, redefined = [], []
        protected: set[str] = set()
        try:
            c0 = load_module("_contract_p", "_contract.py")
            protected = set(getattr(c0, "__all__", ()))
        except Exception:                                        # noqa: BLE001
            pass
        for fn in CONSUMERS:
            src = (HERE / fn).read_text(encoding="utf-8")
            if "_contract import" not in src and "from wb_analysis._contract" not in src:
                not_importing.append(fn)
            for ln, nm in literal_redefinitions(src, protected):
                redefined.append(f"{fn}:{ln}:{nm}")
        check("契约常量：消费方均 import _contract（防手写正则复发）", not not_importing,
              f"未 import 的={not_importing}" if not_importing else f"{len(CONSUMERS)}/{len(CONSUMERS)}")
        check("契约常量：消费方不得用**字面量**重写契约常量（防「import 了再抄一份」）",
              not redefined,
              "；".join(redefined) if redefined else f"0 处（受保护名 {len(protected)} 个）")

        # ---- 上述检测器的**双向夹具**（否则它可能是「恒通过」的空转检测器）----
        try:
            bad_src = 'RATING_ALLOWED_FILES = {"manager.md", "portfolio_manager.md", "x.md"}\n'
            bad2_src = 'DOC_FILES: frozenset = frozenset({"0_brief.md", "0_derived.md", "_c.md"})\n'
            good_src = ('from wb_analysis._contract import DOC_FILES as _DOC_ALL\n'
                        'DOC_FILES = {f for f in _DOC_ALL if f.startswith("_")}\n'
                        'FIVE = list(_DOC_ALL)\n'
                        'def f():\n    RATING_ALLOWED_FILES = {"x.md"}\n')
            hits_bad = literal_redefinitions(bad_src, protected)
            hits_bad2 = literal_redefinitions(bad2_src, protected)
            hits_good = literal_redefinitions(good_src, protected)
            check("契约重写检测器：手抄值必检出 / 派生与局部变量不误报",
                  len(hits_bad) == 1 and len(hits_bad2) == 1 and hits_good == [],
                  f"bad={hits_bad} / wrapped={hits_bad2} / good={hits_good}")
        except Exception as e:                                   # noqa: BLE001
            check("契约重写检测器：手抄值必检出 / 派生与局部变量不误报", False, f"加载失败 {e}")

        # ---- 项目侧契约 vs **上游**评级词表：必须逐字一致 ----
        # 背景：`_verify_report.py` 从上游 `tradingagents.agents.utils.rating` 取 `RATINGS_5_TIER`，
        # 而项目侧门禁用 `_contract.FIVE_LEVELS`。两者若分叉，同一份稿会在
        # 「上游解析器」与「项目门禁」之间得到不同评级 —— 正是 2026-10-08 那次漂移的翻版。
        try:
            sys.path.insert(0, str(HERE.parent))
            from tradingagents.agents.utils.rating import RATINGS_5_TIER as _UP  # noqa: E402
            same = tuple(_UP) == tuple(c0.FIVE_LEVELS) if protected else False
            check("契约常量：项目侧 FIVE_LEVELS == 上游 RATINGS_5_TIER",
                  same, f"upstream={tuple(_UP)} / contract={tuple(c0.FIVE_LEVELS)}"
                  if protected else "未能加载 _contract")
        except Exception as e:                                   # noqa: BLE001
            check("契约常量：项目侧 FIVE_LEVELS == 上游 RATINGS_5_TIER", False, f"加载失败 {e}")

        # ---- 8. `_contract` 内部自洽（词表 ↔ 正则 ↔ 白名单）----
        try:
            c = load_module("_contract_c", "_contract.py")
            problems = []
            # 8a. `FIVE_RE`（大小写不敏感）必须命中词表里每个词的大小写两种写法
            for w in c.FIVE_LEVELS:
                if not c.FIVE_RE.search(f" {w} ") or not c.FIVE_RE.search(f" {w.upper()} "):
                    problems.append(f"FIVE_RE 漏 {w}")
            # 8b. `FIVE_TITLE_RE` 必须**只**命中 Title Case（这是它与 FIVE_RE 的分工）
            if c.FIVE_TITLE_RE.search(" SELL ") or c.FIVE_TITLE_RE.search(" BUY "):
                problems.append("FIVE_TITLE_RE 误命中全大写")
            # 8c. 契约行正则必须能解析出末行档位
            if not c.PROPOSAL_RE.search("FINAL TRANSACTION PROPOSAL: **HOLD**"):
                problems.append("PROPOSAL_RE 解析失败")
            # 8d. `Action` 标签必须**同时**容忍 Title Case 与大写（这正是历史事故的修复点）
            for variant in ("**Action**: Sell", "**Action**: SELL"):
                if not c.LABEL_PATTERNS["Action"].search(variant):
                    problems.append(f"Action 标签漏掉 {variant}")
            # 8e. 五档标签用**长词优先**，`Overweight` 不能被 `Sell` 一类短词抢先截断
            m = c.LABEL_PATTERNS["Recommendation"].search("**Recommendation**: Underweight")
            if not m or m.group(1) != "Underweight":
                problems.append(f"长词优先失效：{m.group(1) if m else None}")
            check("契约常量：词表↔正则↔标签自洽", not problems,
                  "；".join(problems) if problems else "5 项检查通过")
        except Exception as e:                                   # noqa: BLE001
            check("契约常量：词表↔正则↔标签自洽", False, f"加载失败 {e}")

        # ---- 9. 非 12 角色专用通道的豁免：判据同源 + 双向判别力（2026-10-10 新增）----
        # 背景：豁免表原先只有 `_reports_index.py` 认识，而 `_seal_run.py --orphans`
        # 与 `_health.chk_transient_empty` 都不认识 ⇒ 三处对同一份 `TREASURY_<date>.*`
        # 给出相反结论，其中 `--orphans --apply` 会**真的把它删掉**（删除雷）。
        # 修法＝把豁免表上提为唯一定义源。**本断言守住「下一个人又本地重定义一遍」**——
        # 纪律会忘，断言不会（与第 7 节同一思路）。
        excl_consumers = [
            HERE / "_reports_index.py",
            HERE / "_seal_run.py",
            HERE.parent / "scripts" / "_health.py",
        ]
        excl_bad = []
        for p in excl_consumers:
            src = p.read_text(encoding="utf-8")
            if "is_non_tree_artifact" not in src:
                excl_bad.append(f"{p.name}:未用豁免工具")
            if re.search(r"^\s*NON_TREE_PREFIXES\s*=", src, re.M):
                excl_bad.append(f"{p.name}:又本地定义 NON_TREE_PREFIXES")
        check("豁免表同源：三消费方均用 _contract 且无本地重定义", not excl_bad,
              "；".join(excl_bad) if excl_bad else "3/3")

        try:
            ce = load_module("_contract_ex", "_contract.py")
            t_ok = ce.is_non_tree_artifact("TREASURY_2026-10-09.md") is True
            f_ok = ce.is_non_tree_artifact("NVDA_2026-10-09.md") is False
            check("is_non_tree_artifact：专用通道 True / 12 角色标的 False", t_ok and f_ok,
                  f"TREASURY→{ce.is_non_tree_artifact('TREASURY_2026-10-09.md')} / "
                  f"NVDA→{ce.is_non_tree_artifact('NVDA_2026-10-09.md')}")
        except Exception as e:                                   # noqa: BLE001
            check("is_non_tree_artifact：专用通道 True / 12 角色标的 False", False, f"加载失败 {e}")

        # `_health.chk_transient_empty` 双边：仅豁免件 ⇒ PASS；混入真散件 ⇒ WARN
        try:
            ht = load_module("_health_t", str(HERE.parent / "scripts" / "_health.py"))
            fx = tmp / "fakeproj_transient"
            evx = fx / "wb_analysis" / "evidence"
            evx.mkdir(parents=True)
            (evx / "TREASURY_2026-10-09.md").write_text("x", encoding="utf-8")
            orig_root = ht.ROOT
            ht.ROOT = fx
            lvl_a, msg_a = ht.chk_transient_empty()
            (evx / "FOO_2026-01-01.md").write_text("x", encoding="utf-8")
            lvl_b, msg_b = ht.chk_transient_empty()
            ht.ROOT = orig_root
            check("health 瞬态：仅豁免件 PASS（且报豁免数）/ 真散件 WARN",
                  lvl_a == "PASS" and "豁免" in msg_a and lvl_b == "WARN",
                  f"{lvl_a} / {lvl_b} :: {msg_a[:40]}")
        except Exception as e:                                   # noqa: BLE001
            check("health 瞬态：仅豁免件 PASS（且报豁免数）/ 真散件 WARN", False, f"加载失败 {e}")

        # `_seal_run.orphans` 双边：豁免件不得被判孤儿；真孤儿必须被检出（这是删除雷的对偶）
        try:
            so = load_module("_seal_o", "_seal_run.py")
            fy = tmp / "fakeproj_orphan"
            (fy / "wb_analysis" / "drafts").mkdir(parents=True)
            (fy / "wb_analysis" / "analysis").mkdir(parents=True)
            (fy / "reports").mkdir(parents=True)
            evy = fy / "wb_analysis" / "evidence"
            evy.mkdir(parents=True)
            (evy / "TREASURY_2026-10-09.md").write_text("x", encoding="utf-8")
            # ★ 连 `ROOT` 一起换：`orphans()` 用 `f.relative_to(ROOT)` 生成归档名（L294），
            #   只换 EVID/DRAFTS/... 而留 ROOT 指向真项目根 ⇒ 临时路径**不在 ROOT 之下**，
            #   `relative_to` 抛 ValueError（2026-10-10 首跑即撞此坑）。夹具＝模拟一个完整假项目根。
            saved = (so.ROOT, so.REPORTS, so.EVID, so.DRAFTS, so.ANALYSIS, so.ONEOFF)
            so.ROOT = fy
            so.REPORTS, so.EVID = fy / "reports", evy
            so.DRAFTS = fy / "wb_analysis" / "drafts"
            so.ANALYSIS = fy / "wb_analysis" / "analysis"
            so.ONEOFF = fy / "scripts" / "_oneoff"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                so.orphans(False)
            out_a = buf.getvalue()
            (evy / "FOO_2026-01-01.md").write_text("x", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                so.orphans(False)
            out_b = buf.getvalue()
            (so.ROOT, so.REPORTS, so.EVID,
             so.DRAFTS, so.ANALYSIS, so.ONEOFF) = saved
            check("seal --orphans：豁免件不报孤儿 / 真孤儿必被检出",
                  "无孤儿产物" in out_a and "发现 1 组孤儿" in out_b and "FOO" in out_b,
                  f"a={out_a.strip()[:24]} / b={out_b.strip()[:34]}")
        except Exception as e:                                   # noqa: BLE001
            check("seal --orphans：豁免件不报孤儿 / 真孤儿必被检出", False, f"加载失败 {e}")

        # ---- 10. `reports/` 布局常量同源（2026-10-10 新增）----
        # 背景：`TREE_RE` 3 份、功能目录集 4 份、`ALLOWED_TOP` 1 份（函数内局部字面量）、
        # 归档跳过表 4 份 —— 共 **11 处**各写一遍，已上提为 `wb_analysis/_paths.py`。
        # 本条守住「下一个人又本地抄一遍」。**纪律会忘，断言不会**（与第 7 / 9 节同一思路）。
        #
        # ★ 判据拆成两层，且**扫描面自动枚举**（不写死路径）：
        #   ① 全活跃面（`wb_analysis/*.py` + `scripts/*.py`）—— **任何**文件都不得用字面量
        #      重写这些常量。自动枚举 ⇒ 日后归档/新增脚本都不会让本条失效
        #      （首版写死 `scripts/_reorg_reports.py`，该文件一归档本条就 FileNotFoundError）。
        #   ② 显式消费方名单 —— 必须真的 `import _paths`（防「删了重写但也没接上单一来源」，
        #      即第 7 节所说「import 了再抄一份」的对偶形态）。
        #   ⚠️ 两个**自豁免**，二者都必要：
        #      · `_paths.py` = 常量定义处（本该有字面量）；
        #      · `_selftest.py` = **检测器自身** —— 它的 `_FUNC_DIR_KEYS` 与双边夹具里
        #        必然出现同样的字面量，自指检测器不排除自己就会恒红（首跑即撞此坑，30 项里红 1 项）。
        #        检测器「是不是活的」由后面的双边夹具证明，不靠扫自己。
        #   注：`_oneoff/**` **不扫** —— 那是冻结的历史快照，本就该保留当时的字面量。
        SELF_EXEMPT = {"_paths.py", "_selftest.py"}
        p_bad: list[str] = []
        live = [p for p in sorted(HERE.glob("*.py")) if p.name not in SELF_EXEMPT]
        live += sorted((HERE.parent / "scripts").glob("*.py"))
        for p in live:
            for hit in paths_literal_definitions(p.read_text(encoding="utf-8")):
                p_bad.append(f"{p.name}:{hit}")
        check(f"布局常量：全活跃面（{len(live)} 个 .py）无本地字面量重写", not p_bad,
              "；".join(p_bad[:4]) if p_bad else f"0 处（已豁免定义处 + 检测器自身）")

        p_consumers = [
            HERE / "_reports_index.py", HERE / "_scorecard.py", HERE / "_seal_run.py",
            HERE / "_audit_values.py", HERE / "_check_residuals.py",
            HERE / "_check_role_files.py", HERE / "_lint_drafts.py",
        ]
        p_miss = [p.name for p in p_consumers
                  if "_paths import" not in p.read_text(encoding="utf-8")]
        check("布局常量：7 消费方均真的 import _paths", not p_miss,
              f"未接上单一来源={p_miss}" if p_miss else f"{len(p_consumers)}/{len(p_consumers)}")

        try:
            pb = load_module("_paths_p", "_paths.py")
            same = (set(pb.FUNC_DIRS) == {"_datasets", "_other", "_archive", "_audit"}
                    and set(pb.ALLOWED_TOP) == {"INDEX.md", "README.md", "QUALITY.csv"}
                    and tuple(pb.SKIP_ARCHIVE_DIRS) == ("_stale", "_archive"))
            check("布局常量取值：功能目录 / 顶层白名单 / 归档跳过表均未漂移", same,
                  f"FUNC={sorted(pb.FUNC_DIRS)} / SKIP={tuple(pb.SKIP_ARCHIVE_DIRS)}")
        except Exception as e:                                   # noqa: BLE001
            check("布局常量取值：功能目录 / 顶层白名单 / 归档跳过表均未漂移", False, f"加载失败 {e}")

        try:
            bad_src = ('TREE_RE = re.compile(r"^([A-Za-z0-9.\\-]+)_(\\d{8})_(\\d{6})$")\n'
                       'SKIP_DIRS = {"_datasets", "_other", "_archive", "_audit"}\n'
                       'ap.add_argument("--exclude", default=["_stale", "_archive"])\n')
            good_src = ('from wb_analysis._paths import FUNC_DIRS, SKIP_ARCHIVE_DIRS\n'
                        'SKIP_DIRS = FUNC_DIRS\n'
                        'excludes = list(SKIP_ARCHIVE_DIRS)\n'
                        '# 历史：这里曾写 ["_stale", "_archive"]，已收敛到 _paths\n')
            hb = paths_literal_definitions(bad_src)
            hg = paths_literal_definitions(good_src)
            check("布局重写检测器：手抄值必检出 / 派生与注释留痕不误报",
                  len(hb) == 3 and hg == [], f"bad={hb} / good={hg}")
        except Exception as e:                                   # noqa: BLE001
            check("布局重写检测器：手抄值必检出 / 派生与注释留痕不误报", False, f"加载失败 {e}")

        # ---- 10b. `iter_report_trees` 与 `_scorecard` 排除二级 `_archive` 回归守卫 ----
        try:
            sc_mod = load_module("_sc_mod", "_scorecard.py")
            fake_rep = tmp / "fake_reports"
            (fake_rep / "SKHY" / "SKHY_20261013_204423").mkdir(parents=True)
            (fake_rep / "SKHY" / "_archive").mkdir(parents=True)
            orig_rep, orig_csv = sc_mod.REPORTS, sc_mod.CSV
            sc_mod.REPORTS = fake_rep
            sc_mod.CSV = fake_rep / "QUALITY.csv"
            sc_rows = sc_mod.collect()
            sc_mod.REPORTS, sc_mod.CSV = orig_rep, orig_csv
            check("scorecard: 二级 _archive 不入表（防空 ticker 幽灵行）",
                  len(sc_rows) == 1 and sc_rows[0]["ticker"] == "SKHY",
                  f"rows={[r['tree'] for r in sc_rows]}")
        except Exception as e:  # noqa: BLE001
            check("scorecard: 二级 _archive 不入表（防空 ticker 幽灵行）", False, f"加载失败 {e}")

        if args.verbose:
            print("\n----- lint 好夹具输出 -----\n" + g_out[-800:])
            print("\n----- lint 坏夹具输出 -----\n" + b_out[-800:])

    # ---- 11. 网络通道重试口径（2026-10-11 新增）----
    # 起因：NFLX 采集时 yfinance **整片 403**，35 通道险些全废。归因＝本机出网走代理、
    # 节点间歇抖动（同 URL 连打：一次 403、一次 200），**不是** IP 永久封禁。
    # 原实现把重试写成「调用点自己记得传」的约定 ⇒ 30+ 通道里**只有 FRED 传了**，
    # 一次抖动就静默丢通道，汇总只写「非全绿通道: get_stock_data=fail」，
    # 与「上游真缺数据」在观感上无法区分（**假缺口**）。
    # ⇒ 现在重试是 `_safe_call` 的**默认值**，且全项目只有 `_NET_RETRIES` 一个来源。
    # 这条守卫防的正是「有人把默认值改回 0」——那是本次事故的原始形态。
    try:
        cm = load_module("collect_retry_probe", "collect.py")
        _dflt = inspect.signature(cm._safe_call).parameters["retries"].default
        check("网络重试：_safe_call 默认 = _NET_RETRIES 且 ≥1",
              _dflt == cm._NET_RETRIES and cm._NET_RETRIES >= 1,
              f"_NET_RETRIES={cm._NET_RETRIES} / 默认={_dflt}")
    except Exception as e:                                       # noqa: BLE001
        check("网络重试：_safe_call 默认 = _NET_RETRIES 且 ≥1", False, f"加载失败 {e}")

    # 三个**直连**网络块绕开了 `_safe_call`（返回 dict，塞不进占位串契约），
    # 最容易成为「修了一半」的漏网点 —— 它们同样走 yfinance。
    try:
        csrc = (HERE / "collect.py").read_text(encoding="utf-8")
        _need = ("_retry(fetch_option_structure", "_retry(fetch_volatility_proxies",
                 "_retry(_realtime_close_block")
        _miss = [n for n in _need if n not in csrc]
        check("网络重试：期权/波动率代理/实时收盘三块均走 _retry", not _miss,
              f"漏={_miss}" if _miss else "3/3")
    except Exception as e:                                       # noqa: BLE001
        check("网络重试：期权/波动率代理/实时收盘三块均走 _retry", False, f"读取失败 {e}")

    # ---- 12. 期权时点分支（2026-10-17 新增，CBOE 期权源接入配套）----
    # 起因：yfinance 的期权链只在美东 09:30–16:00 实时刷新；盘前/盘后它只返回上一交易日的
    # 残留挂单（bid/ask 格式合法但 lastTradeDate 陈旧数周）⇒ 期权维度整体不可用（NVDX 08:29
    # 实测：扫 29 个到期日、387 个有双边报价合约、**合格样本 0**）。
    # 对策＝非盘中自动切 CBOE 官方延迟报价（做市商报价链，不依赖「当天有没有成交」）。
    #
    # **为什么必须在这里加夹具**：这条分支是**按时间**走的两条互斥路径，而它此前把
    # `datetime.now()` 写死在函数体里 ⇒ **非盘中那条路径永远无法被测试**，
    # 只能靠「某天恰好凌晨跑一次」来验证 —— 而这正是「靠记得注意」而非「靠代码根除」，
    # 违反本项目的两条原则。现在时钟可注入（`_thresholds.option_source_decision(now=...)`），
    # 于是**两条路径都能被夹具证明**。
    #
    # 双边夹具守的是「判据方向反了」这一类错误：
    #   · 好夹具：盘中 → 不切；盘前/盘后/非交易日 → 切（且说明里写明「上一时段收盘快照」）
    #   · 坏夹具：把边界写成 `9.0 <= h` 或 `h <= 16.0` 之类的**闭区间错位**
    #     ⇒ 09:30 会被误判成盘前而切到 CBOE（丢掉实时性），16:00 会被误判成盘中
    #     （拿到残留挂单）。两种方向都必须在夹具下现形。
    try:
        import datetime as _dt2
        from zoneinfo import ZoneInfo

        th = load_module("_thresholds_probe", "_thresholds.py")
        ET2 = ZoneInfo(th.MARKET_TZ_NAME)

        def _phase_at(y, mo, d, hh, mm):
            return th.market_session_phase(
                _dt2.datetime(y, mo, d, hh, mm, tzinfo=ET2))

        # —— 好夹具：五种时点，每一种都给出「期望的时段 + 期望是否切源」——
        _cases = [
            ((2026, 10, 16, 10, 30), "in_session", False, "周五盘中"),
            ((2026, 10, 16,  8, 29), "pre_market", True,  "周五盘前（NDX 实测时点）"),
            ((2026, 10, 16,  9, 30), "in_session", False, "周五开盘整（边界：含）"),
            ((2026, 10, 16, 16,  0), "after_hours", True, "周五收盘整（边界：不含）"),
            ((2026, 10, 17, 12,  0), "closed_day", True,  "周六"),
        ]
        _bad = []
        for (y, mo, d, hh, mm), want_ph, want_cboe, label in _cases:
            got_ph = _phase_at(y, mo, d, hh, mm)
            got_cboe, _note = th.option_source_decision(
                _dt2.datetime(y, mo, d, hh, mm, tzinfo=ET2))
            if got_ph != want_ph or got_cboe is not want_cboe:
                _bad.append(f"{label}: phase={got_ph}(期望{want_ph})/"
                            f"cboe={got_cboe}(期望{want_cboe})")
        check("期权时点分支：盘中不切 / 盘前盘后非交易日切（含 09:30、16:00 边界）",
              not _bad, "；".join(_bad) if _bad else f"{len(_cases)}/{len(_cases)} 时点全部符合")

        # —— 说明文案必须写明「拿的是上一时段快照」，否则下游会当实时用 ——
        _use, _note = th.option_source_decision(
            _dt2.datetime(2026, 10, 16, 8, 29, tzinfo=ET2))
        _ok_note = _use and ("上一时段收盘快照" in _note) and ("非实时报价" in _note)
        check("期权时点分支：切源说明必须写明「上一时段收盘快照 / 非实时」",
              _ok_note, f"note={_note[:70]}")

        # —— 坏夹具：把边界写成闭区间（`9.0 <= h <= 16.0`）必须能与正确实现区分 ——
        #    正确：09:30 属盘中（含起点）、16:00 属盘后（不含终点）
        #    错误：09:00–09:30 之间被误判盘中（丢实时性）；16:00 被误判盘中（拿到残留挂单）
        def _closed_interval(h: float) -> str:
            return "in_session" if 9.0 <= h <= 16.0 else "other"   # 刻意写错的两端

        _good_0930 = _phase_at(2026, 10, 16, 9, 30)
        _bad_0930 = _closed_interval(9.5)
        _good_1600 = _phase_at(2026, 10, 16, 16, 0)
        _bad_1600 = _closed_interval(16.0)
        # 09:00（正确=盘前 / 错误=盘中）与 16:00（正确=盘后 / 错误=盘中）两处必须被区分
        _good_0900 = _phase_at(2026, 10, 16, 9, 0)
        _distinct = (_closed_interval(9.0) != _good_0900) and (_bad_1600 != _good_1600)
        check("期权时点分支：闭区间错位夹具可被区分（证明检查是活的）",
              _distinct,
              f"09:00 正确={_good_0900}/错误={_closed_interval(9.0)}；"
              f"16:00 正确={_good_1600}/错误={_bad_1600}")

        # —— CBOE 适配器不得在本仓被写成可选依赖：模块必须可导入且形状齐全 ——
        _src = (HERE / "collect_index.py").read_text(encoding="utf-8")
        _forward = ("from wb_analysis._thresholds import option_source_decision" in _src
                    and "def _should_use_cboe_source" in _src)
        check("期权时点分支：collect_index 判据转发自 _thresholds（单一来源）",
              _forward, "已转发" if _forward else "判据未收敛到 _thresholds")

        _opt_src = (HERE / "_option_source.py").read_text(encoding="utf-8")
        _opt_ok = all(k in _opt_src for k in
                      ("delayed_quotes", "MAX_TRIES", "cboe_delayed", "option_chain"))
        check("期权源适配器：CBOE 端点/重试/来源标签/链接口齐备", _opt_ok,
              "齐备" if _opt_ok else "关键成员缺失")

        # —— 台账必须认得这个新通道（否则下游看不见「昨日快照」这件事）——
        _gl = load_module("_gap_ledger_probe", "_gap_ledger.py")
        _rule = _gl.RULES.get("CBOE_fallback_used")
        _rule_ok = bool(_rule) and _rule.get("decisive") is True and _rule.get("cls") == "B"
        check("期权时点分支：台账已登记 CBOE_fallback_used（B 类 / 决定性）",
              _rule_ok, f"cls={(_rule or {}).get('cls')} decisive={(_rule or {}).get('decisive')}")
    except Exception as e:                                       # noqa: BLE001
        check("期权时点分支：夹具执行", False, f"加载失败 {e}")

    # ---- 汇总 ----
    print("=" * 74)
    print("门禁自检")
    print("=" * 74)
    failed = 0
    for name, ok, detail in results:
        mark = "✓" if ok else "✗"
        if not ok:
            failed += 1
        print(f"  {mark} {name:<44} {detail}")
    print("-" * 74)
    if failed:
        print(f"✗ {failed}/{len(results)} 项自检失败 —— **检测器本身已不可信**，先修它，别交付。")
        return 1
    print(f"✓ 全部 {len(results)} 项通过：坏夹具必被检出，好夹具必不误报。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
