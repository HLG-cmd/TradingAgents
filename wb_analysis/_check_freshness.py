# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_check_freshness.py
"""流水线新鲜度校验 —— 防止「上游重采了、下游没重跑」造成的陈旧扩散。

**为什么需要这个脚本**（2026-09-18 血的教训）

NDX 报告曾出现：证据包在 22:25 为修「未收盘 bar」被**重新采集**，
但派生指标 `0_derived.md` 停在 17:33（用旧证据生成），
简报又在 22:30 沿用了旧派生值 —— 于是 **Forward PE 20.89 / 站上 50SMA 32.3%
等一整代陈旧数字被下发给全部 12 个角色**，扩散 270+ 处。

这是纯流程缺陷：`_derive_*.py` 每次运行都会重读证据包，
**只要重跑就能得到正确值**；问题在于「该重跑的步骤被跳过了，且没有任何提示」。

本脚本把「时间顺序」变成可机检的断言：
    证据包  ≤  派生指标  ≤  统一简报  ≤  全部角色文件

用法：
    ./.venv/Scripts/python.exe wb_analysis/_check_freshness.py wb_analysis/drafts/NDX_2026-09-17
    ./.venv/Scripts/python.exe wb_analysis/_check_freshness.py wb_analysis/drafts/SPX_2026-09-18

退出码：0 = 全部新鲜；1 = 存在陈旧环节（会在 stdout 指出是哪一个）。
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import sys

# ★ 必须用**绝对路径**解析（2026-09-19 修正）。
#   此前写的是相对路径 `pathlib.Path("wb_analysis") / "evidence"`，
#   于是本脚本的行为**取决于从哪里调用**：在项目根跑正常，
#   从别的目录调用就会报「证据包缺失」—— 一个纯粹的 cwd 依赖 bug，
#   而且症状（"证据包缺失"）极易被误读成真的缺数据。
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
EVID = PROJECT_ROOT / "wb_analysis" / "evidence"

# 角色文件所在子目录（渲染器消费的就是这些）
ROLE_DIRS = ("1_analysts", "2_research", "3_trading", "4_risk")

# 「空骨架」特征：外部工具/宿主可能预先落一份占位草稿，内含**预填的假评级**，
# 一旦被渲染就会产出「看起来正常、实际全是 Hold」的假报告。
# 注意：这类文件若是在简报之后生成的，**mtime 检查抓不到**，必须按内容判定。
STUB_SIZE_LIMIT = 200          # 正常角色报告都是数十 KB
STUB_MARKERS = (
    "FINAL TRANSACTION PROPOSAL: **HOLD**",
    "Overall Sentiment: Neutral",
)


def _is_stub(p: pathlib.Path) -> str | None:
    """返回命中原因；不是骨架则返回 None。"""
    try:
        size = p.stat().st_size
    except OSError:
        return None
    if size <= STUB_SIZE_LIMIT:
        return f"仅 {size} 字节（疑似占位骨架）"
    try:
        head = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for mk in STUB_MARKERS:
        if mk in head and len(head) < 2000:
            return f"含预填骨架标记「{mk}」"
    return None


def _mt(p: pathlib.Path) -> float:
    return p.stat().st_mtime


def _fmt(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("%m-%d %H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(description="检查分析流水各环节的时间顺序是否自洽")
    ap.add_argument("draft_dir", help="草稿目录，如 wb_analysis/drafts/NDX_2026-09-17")
    ap.add_argument("--evidence", default=None,
                    help="证据包前缀（默认取草稿目录名的前缀，如 NDX）")
    ap.add_argument("--date", default=None,
                    help="证据包日期（默认取草稿目录名的日期部分）")
    args = ap.parse_args()

    d = pathlib.Path(args.draft_dir)
    if not d.is_dir():
        print(f"✗ 草稿目录不存在：{d}")
        return 1

    stem = d.name                      # 形如 NDX_2026-09-17
    prefix = args.evidence or stem.split("_")[0]
    date = args.date or "_".join(stem.split("_")[1:])

    ev_md = EVID / f"{prefix}_{date}.md"
    ev_json = EVID / f"{prefix}_{date}.json"
    derived = d / "0_derived.md"
    brief = d / "0_brief.md"

    problems: list[str] = []
    order: list[tuple[str, float]] = []

    # ── 1) 证据包存在性 ──────────────────────────────────────────────
    if not ev_md.exists():
        problems.append(f"证据包缺失：{ev_md}")
    else:
        order.append(("证据包", max(_mt(ev_md),
                                    _mt(ev_json) if ev_json.exists() else _mt(ev_md))))

    for label, p in (("派生指标 0_derived.md", derived), ("统一简报 0_brief.md", brief)):
        if not p.exists():
            problems.append(f"{label} 缺失")
        else:
            order.append((label, _mt(p)))

    # ── 2) 单调性检查 ────────────────────────────────────────────────
    if len(order) >= 3:
        names = [n for n, _ in order]
        times = [t for _, t in order]
        for i in range(len(order) - 1):
            if times[i] > times[i + 1]:
                problems.append(
                    f"时间顺序颠倒：{names[i]}（{_fmt(times[i])}）"
                    f" 晚于 {names[i+1]}（{_fmt(times[i+1])}）"
                    f" ⇒ **{names[i+1]} 是上一代产物，必须重跑**")

    # ── 3) 角色文件：是否为占位骨架 + 是否晚于简报 ──────────────────
    brief_t = _mt(brief) if brief.exists() else 0.0
    stale_roles: list[tuple[str, str]] = []
    stub_roles: list[tuple[str, str]] = []
    role_count = 0
    for sub in ROLE_DIRS:
        sd = d / sub
        if not sd.is_dir():
            continue
        for p in sorted(sd.glob("*.md")):
            role_count += 1
            reason = _is_stub(p)
            if reason:
                stub_roles.append((str(p.relative_to(d)), reason))
            if _mt(p) < brief_t:
                stale_roles.append((str(p.relative_to(d)), _fmt(_mt(p))))

    if stub_roles:
        problems.append(
            f"★ {len(stub_roles)}/{role_count} 个角色文件是**占位骨架**（含预填假评级）"
            f" ⇒ 渲染会产出假报告，必须先写真实内容："
            + "；".join(f"{n}（{r}）" for n, r in stub_roles))

    if stale_roles:
        problems.append(
            f"{len(stale_roles)}/{role_count} 个角色文件早于 0_brief.md（{_fmt(brief_t)}）"
            f" ⇒ 需按 A→B→C→D→E→F→G 整链重跑："
            + "、".join(f"{n}({t})" for n, t in stale_roles))

    # ── 输出 ────────────────────────────────────────────────────────
    print("=" * 74)
    print(f"新鲜度校验：{d}")
    print("=" * 74)
    for n, t in order:
        print(f"  {n:<26} {_fmt(t)}")
    print(f"  角色文件 {role_count} 个：早于简报 {len(stale_roles)} 个、"
          f"占位骨架 {len(stub_roles)} 个")
    print("-" * 74)
    if problems:
        for p in problems:
            print(f"✗ {p}")
        print()
        print("⇒ 结论：**上游已变、下游未跟上**。先重跑派生指标，再重写简报，最后整链重跑。")
        return 1
    print("✓ 全部新鲜：证据包 ≤ 派生指标 ≤ 简报 ≤ 全部角色文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
