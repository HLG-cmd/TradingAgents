# lifecycle: reusable
# created: 2026-10-03
# usage: ./.venv/Scripts/python.exe wb_analysis/_gen_meta.py GOOG_2026-10-01 [NDX_2026-10-01 ...]
"""为草稿目录生成 `meta.json`（`assemble.py --from-dir` 的可选但**实际必需**输入）。

## 为什么需要它

`assemble.py::load_from_dir()` 对 `meta.json` 的处理是「可选」：
缺了它，`ticker` 会从目录名兜底推导，但 **`as_of` 与 `ratings` 会静默变成空值**
（源码：`"as_of": meta.get("as_of", "")` / `"ratings": meta.get("ratings", {})`）。

后果：渲染出的 `RUN.json` 里**数据基准日为空、评级链为空**，
而 `_precheck.py` 的「报告树反读」一项正是拿它们与草稿目录对账 ⇒ 会失据。
**静默降级、不报错**，属于本项目反复出现的那一类失败（铁律 3）。

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
        "notes": ("本轮期权维度整体不可用（类别 S，盘前采集）；"
                  "详见 wb_analysis/evidence/%s_%s.gaps.json 与 0_brief.md 的缺口台账。" % (ticker, as_of)),
    }
    out = d / "meta.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"  ⇒ 写入 {out.relative_to(ROOT)}（{out.stat().st_size} 字节）")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    worst = 0
    for dirname in sys.argv[1:]:
        print(f"===== {dirname}")
        worst = max(worst, build(dirname))
        print()
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
