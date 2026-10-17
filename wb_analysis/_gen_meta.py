# lifecycle: reusable
# created: 2026-10-03
# usage: ./.venv/Scripts/python.exe wb_analysis/_gen_meta.py GOOG_2026-10-01 [NDX_2026-10-01 ...]
"""为草稿目录生成 `meta.json`（`assemble.py --from-dir` 的**必备**输入）。

## 为什么需要它

★ 2026-10-10 起，`assemble.py::load_from_dir()` 对 `meta.json` 改为 **strict 下必需**：
缺 `meta.json` / 解析失败 / 缺 `as_of`+`ratings` 字段 ⇒ 抛 `MetaMissingError`，
`assemble.py --from-dir` **退出码 2**（仅 `--allow-no-meta` 可显式放行）。

历史坑（正是本工具存在的理由）：此前它被当作「可选」——
缺了它，`ticker` 会从目录名兜底推导，但 **`as_of` 与 `ratings` 会静默变成空值**
（源码里是 `"as_of": meta.get("as_of", "")` / `"ratings": meta.get("ratings", {})`）。
渲染出的 `RUN.json` 里**数据基准日为空、评级链为空**，
而 `_precheck.py` 的「报告树反读」正是拿它们与草稿目录对账 ⇒ 直接失据。
**静默降级、不报错**，属本项目反复出现的那一类失败（铁律 3）——
故已在 `assemble.py` 侧**硬阻断**，本工具从「建议先跑」升级为「**必须先生成**」。

## 评级从哪里来（**不手抄**）

按项目契约定位于各角色的**结论块**，用 `_verify_ratings.py` 同源的规则提取：

| 字段 | 来源文件 | 取值方式 |
|---|---|---|
| `research_manager` | `2_research/manager.md` | 首个 `**Recommendation**: X` |
| `trader_action` | `3_trading/trader.md` | 首个 `**Action**: X` |
| `portfolio_manager` | `4_risk/portfolio_manager.md` | 首个 `**Rating**: X` |

⚠️ 只认结论块标签，**不做「扫描全文取第一个五档词」的退化解析** ——
退化解析正是铁律 8 警告的污染路径；这里宁可**报错**也不猜。

## 退出码
0 = 全部生成成功；1 = 有角色文件缺失或标签提取失败（**逐项列出，不静默跳过**）。
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "wb_analysis" / "drafts"

# ★ 2026-10-08：契约常量改为**唯一来源** import（见 `_contract.py` 抬头的漂移史）。
#   此前本文件自持一份大小写敏感的 FIVE 正则，与 `_lint_drafts.py` 的含大写变体不一致，
#   导致 `**Action**: SELL` 在本文件里"找不到结论块标签"、在 lint 里却合法 —— 两道门禁打架。
sys.path.insert(0, str(ROOT))
from wb_analysis._contract import LABEL_PATTERNS  # noqa: E402

SPEC = [
    ("research_manager", "2_research/manager.md", LABEL_PATTERNS["Recommendation"]),
    ("trader_action", "3_trading/trader.md", LABEL_PATTERNS["Action"]),
    ("portfolio_manager", "4_risk/portfolio_manager.md", LABEL_PATTERNS["Rating"]),
]


def _notes_from_gaps(ticker: str, as_of: str) -> str:
    """从**缺口台账派生** notes —— 绝不写死任何与特定轮次绑定的结论。

    历史坑（2026-10-10 发现）：此处曾硬编码
    「本轮期权维度整体不可用（类别 S，盘前采集）」。
    那是**某一轮盘前采集**的事实，却被复制进此后**每一轮**的 `RUN.json`，
    与该轮实际状态直接冲突（如收盘后采集、期权 FULL 级可用）。
    这与铁律 3「静默降级」同类：不报错、外观正常、内容是错的。
    """
    gp = ROOT / "wb_analysis" / "evidence" / f"{ticker}_{as_of}.gaps.json"
    tail = (f"详见 wb_analysis/evidence/{ticker}_{as_of}.gaps.json "
            f"与 0_brief.md 的缺口台账。")
    if not gp.exists():
        return f"⚠️ 未找到缺口台账（{gp.name} 不存在）⇒ 缺口状态未知，须先跑 _gap_ledger.py。" + tail
    try:
        g = json.loads(gp.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return f"⚠️ 缺口台账解析失败（{type(e).__name__}）⇒ 缺口状态未知。" + tail
    gaps = g.get("gaps") or []
    dec = [x for x in gaps if x.get("decisive")]
    ok, tot = g.get("channels_ok"), g.get("channels_total")
    if not gaps:
        return f"通道 {ok}/{tot}，**无登记缺口**。{tail}"
    names = "、".join((x.get("channel") or x.get("label") or "?") for x in dec) or "无"
    return (f"通道 {ok}/{tot}，登记缺口 {len(gaps)} 条（其中**决定性 {len(dec)} 条**：{names}）。"
            f"凡结论依赖决定性缺口者必须写成条件式。{tail}")


def build(dirname: str) -> int:
    d = DRAFTS / dirname
    if not d.is_dir():
        print(f"  ✗ 目录不存在: {d}")
        return 1
    ticker = dirname.split("_")[0]
    as_of = dirname.split("_", 1)[1] if "_" in dirname else ""

    ratings, bad = {}, 0
    for field, rel, pat in SPEC:
        p = d / rel
        if not p.exists():
            print(f"  ✗ {field:<18} 缺文件 {rel}")
            bad += 1
            continue
        m = pat.search(p.read_text(encoding="utf-8"))
        if not m:
            print(f"  ✗ {field:<18} {rel} 中未找到结论块标签（不退化解析）")
            bad += 1
            continue
        ratings[field] = m.group(1)
        print(f"  ✓ {field:<18} {m.group(1):<12} ← {rel}")

    if bad:
        print(f"  ⇒ {dirname}: {bad} 项失败，**不写盘**")
        return 1

    meta = {
        "ticker": ticker,
        "as_of": as_of,
        "ratings": ratings,
        "notes": _notes_from_gaps(ticker, as_of),
    }
    out = d / "meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ⇒ 写入 {out.relative_to(ROOT)}（{out.stat().st_size} 字节）")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2 if len(sys.argv) < 2 else 0
    worst = 0
    for dirname in sys.argv[1:]:
        print(f"===== {dirname}")
        worst = max(worst, build(dirname))
        print()
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
