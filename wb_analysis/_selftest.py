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
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

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
    "4_risk/aggressive.md": "# 激进派\n\n主张放大敞口。\n",
    "4_risk/conservative.md": "# 保守派\n\n主张收缩敞口。\n",
    "4_risk/neutral.md": "# 中性派\n\n给出条件化中间路径。\n",
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
    p.write_text("# 保守派\n\n当前估值为 99.99 倍。\n", encoding="utf-8", newline="\n")
    return d


def rc(cmd: list[str], cwd: Path) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
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

        # ---- 7. 健康检查的「编译缓存」检测器（双边；防再次退化成恒 PASS）----
        # 实测过一次真实缺陷（2026-09-23）：判据写成 `any(s in d.parts for s in SKIP)`，
        # 而 `rglob` 迭代出来的目录本身就叫 `__pycache__`、`SKIP` 里也含 `"__pycache__"`
        # ⇒ **条件恒真 ⇒ 检测器恒 PASS**，82 个 .pyc 却报「无编译缓存残留」。
        # 这正是本文件存在的理由：**看着在工作、其实什么也没检**。
        # ⇒ 双边夹具：有 .pyc 必报 WARN；无 .pyc 必 PASS；且被排除目录里的 .pyc 不得计数。
        try:
            h = load_module("_health_h", str(HERE.parent / "scripts" / "_health.py"))
            fake = tmp / "fakeproj"
            (fake / "pkg" / "__pycache__").mkdir(parents=True)
            (fake / "pkg" / "__pycache__" / "mod.cpython-313.pyc").write_bytes(b"\x00")
            # 被排除目录里的缓存：不得计入（否则 .venv 会让它永远变红）
            (fake / ".venv" / "lib" / "__pycache__").mkdir(parents=True)
            (fake / ".venv" / "lib" / "__pycache__" / "lib.pyc").write_bytes(b"\x00")

            orig_root = h.ROOT
            h.ROOT = fake
            lvl_bad, msg_bad = h.chk_pycache()
            (fake / "pkg" / "__pycache__" / "mod.cpython-313.pyc").unlink()
            lvl_ok, msg_ok = h.chk_pycache()
            h.ROOT = orig_root

            check("health: 检出 .pyc（不再恒 PASS）", lvl_bad == "WARN" and "1 个" in msg_bad,
                  f"{lvl_bad} / {msg_bad}")
            check("health: 无 .pyc 时 PASS，且 .venv 被排除", lvl_ok == "PASS",
                  f"{lvl_ok} / {msg_ok}")
        except Exception as e:                                   # noqa: BLE001
            check("health: chk_pycache 双边", False, f"加载失败 {e}")

        if args.verbose:
            print("\n----- lint 好夹具输出 -----\n" + g_out[-800:])
            print("\n----- lint 坏夹具输出 -----\n" + b_out[-800:])

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
