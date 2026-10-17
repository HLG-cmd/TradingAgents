# lifecycle: oneoff
# created: 2026-09-23
# archived: 2026-10-10
# why: 写入点已全部改完（实测 6 个消费方现均写 `reports/_datasets/`，`reports/` 顶层只剩 `QUALITY.csv`）。
#      本文件是**对源码做精确字符串替换**的迁移器，重复运行必然「命中 0 处即报错」⇒ 归档。
# serves: 2026-09-23 一次性写入点迁移
# usage: ./.venv/Scripts/python.exe scripts/_patch_output_dirs.py [--apply]
"""把「散落产物」的输出目录统一到 `reports/_datasets/`（数据产品）与 `reports/_other/`（专题报告）。

背景：`reports/` 顶层之所以会被 CSV/HTML 塞满，根因是**多个脚本直接往 `reports/` 写文件**：
  · `wb_analysis/_screen_pool.py`        → reports/radar_<pool>_<date>.csv
  · `wb_analysis/_screen_sp500_full.py`  → reports/radar_sp500full_<date>.csv
  · `wb_analysis/_verify_growth_edgar.py`→ reports/growth_verify_edgar_<date>.csv
  · `factor_backtest.py`                 → reports/factor_backtest_<date>.csv（含历史累积文件）
  · `fundamental_backtest.py`            → reports/fundamental_backtest_<date>.csv
  · `smart_screener.py`                  → reports/radar_*.csv + reports/screener_*.md
⇒ 只搬一次文件是治标；**改写入点**才是治本（符合项目原则①：能靠代码根除的不靠「记得注意」）。

本脚本对每个文件做**精确字符串替换**，替换后回读验证；命中 0 处即报错，不静默通过。

用法: ./.venv/Scripts/python.exe scripts/_patch_output_dirs.py [--apply]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = "--apply" in sys.argv

# (文件, 旧串, 新串)
PATCHES = [
    ("wb_analysis/_screen_pool.py",
     '    out = ROOT / "reports" / f"radar_{label}_{dt.date.today().isoformat()}.csv"',
     '    out_dir = ROOT / "reports" / "_datasets"\n'
     '    out_dir.mkdir(parents=True, exist_ok=True)\n'
     '    out = out_dir / f"radar_{label}_{dt.date.today().isoformat()}.csv"'),
    ("wb_analysis/_screen_sp500_full.py",
     '    out = ROOT / "reports" / f"radar_sp500full_{dt.date.today().isoformat()}.csv"',
     '    out_dir = ROOT / "reports" / "_datasets"\n'
     '    out_dir.mkdir(parents=True, exist_ok=True)\n'
     '    out = out_dir / f"radar_sp500full_{dt.date.today().isoformat()}.csv"'),
    ("wb_analysis/_verify_growth_edgar.py",
     '    out = ROOT / "reports" / f"growth_verify_edgar_{dt.date.today().isoformat()}.csv"',
     '    out_dir = ROOT / "reports" / "_datasets"\n'
     '    out_dir.mkdir(parents=True, exist_ok=True)\n'
     '    out = out_dir / f"growth_verify_edgar_{dt.date.today().isoformat()}.csv"'),
    ("factor_backtest.py",
     '    out = PROJECT_ROOT / "reports" / f"factor_backtest_{as_of.replace(\'-\', \'\')}.csv"',
     '    _out_dir = PROJECT_ROOT / "reports" / "_datasets"\n'
     '    _out_dir.mkdir(parents=True, exist_ok=True)\n'
     '    out = _out_dir / f"factor_backtest_{as_of.replace(\'-\', \'\')}.csv"'),
    ("factor_backtest.py",
     '                               PROJECT_ROOT / "reports" / HISTORY_NAME)',
     '                               PROJECT_ROOT / "reports" / "_datasets" / HISTORY_NAME)'),
    ("fundamental_backtest.py",
     '    out = PROJECT_ROOT / "reports" / f"fundamental_backtest_{as_of.replace(\'-\', \'\')}.csv"',
     '    _out_dir = PROJECT_ROOT / "reports" / "_datasets"\n'
     '    _out_dir.mkdir(parents=True, exist_ok=True)\n'
     '    out = _out_dir / f"fundamental_backtest_{as_of.replace(\'-\', \'\')}.csv"'),
    ("smart_screener.py",
     '            reports_dir = PROJECT_ROOT / "reports"\n'
     '            reports_dir.mkdir(exist_ok=True)\n'
     '            csv_file = reports_dir / f"radar_{pool_key}_{datetime.date.today().isoformat()}.csv"',
     '            reports_dir = PROJECT_ROOT / "reports" / "_datasets"   # 数据产品统一落 _datasets/\n'
     '            reports_dir.mkdir(parents=True, exist_ok=True)\n'
     '            csv_file = reports_dir / f"radar_{pool_key}_{datetime.date.today().isoformat()}.csv"'),
    ("smart_screener.py",
     '    reports_dir = PROJECT_ROOT / "reports"\n'
     '    reports_dir.mkdir(exist_ok=True)\n'
     '    report_file = reports_dir / f"screener_{pool_key}_{timestamp}.md"',
     '    reports_dir = PROJECT_ROOT / "reports" / "_other"      # 非 12 角色的专题报告统一落 _other/\n'
     '    reports_dir.mkdir(parents=True, exist_ok=True)\n'
     '    report_file = reports_dir / f"screener_{pool_key}_{timestamp}.md"'),
]


def main() -> int:
    print("=" * 96)
    print("统一产物输出目录：reports/ → reports/_datasets/ 与 reports/_other/")
    print("=" * 96)
    cache: dict[Path, str] = {}
    hit = miss = 0
    for rel, old, new in PATCHES:
        p = ROOT / rel
        if not p.exists():
            print(f"  ✗ 文件不存在: {rel}")
            miss += 1
            continue
        t = cache.get(p) or p.read_text(encoding="utf-8")
        if old not in t:
            print(f"  ✗ 未命中（字符串不匹配，需人工核对）: {rel}")
            print(f"      期望: {old.strip()[:90]}")
            miss += 1
            continue
        t2 = t.replace(old, new, 1)
        cache[p] = t2
        hit += 1
        print(f"  ✓ {rel}")

    if APPLY:
        for p, t in cache.items():
            p.write_text(t, encoding="utf-8", newline="\n")
        print(f"\n[已写入] {len(cache)} 个文件")
        # 回读验证：不得再出现「直接写 reports 顶层」的模式
        bad = []
        for rel, old, _ in PATCHES:
            p = ROOT / rel
            if p.exists() and old in p.read_text(encoding="utf-8"):
                bad.append(f"{rel}: 仍残留旧写法")
        print(f"[回读] 残留 {len(bad)} 处" + ("" if not bad else "：" + "; ".join(bad)))
    else:
        print(f"\n[DRY-RUN] 命中 {hit} 处、未命中 {miss} 处。加 --apply 写入。")
    return 0 if miss == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
