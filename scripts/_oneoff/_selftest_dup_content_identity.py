# lifecycle: oneoff
# created: 2026-10-11
# serves: （门禁双侧自检，无标的）
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_selftest_dup_content_identity.py
"""O2 双侧验证：内容身份重复检测。

- 阳性夹具：同标的、两棵树 `data_date` 标签不同（10-10 / 10-11），
            但末根 bar 与 bars 完全相同 ⇒ 必须报 [内容重复]。
- 阴性夹具：同标的、两棵树末根 bar 相同但 bars 不同（1 年窗 vs 2 年窗）
            ⇒ 属不同轮次，**不得**报重复。

用法：./.venv/Scripts/python.exe scripts/_oneoff/_selftest_dup_content_identity.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("ri", ROOT / "wb_analysis" / "_reports_index.py")
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)

EVID_TMPL = """# 证据包：{tk}

- 采集日期: {date}

## 1. 行情与价格结构

```
关键统计:
- latest_close: 169.03
- bars: {bars}

最近 20 根 K 线:
Date   Open   High    Low  Close   Volume
{lastbar} 174.93 179.90 174.59 175.63 20965200
```

## 通道健康度

- 成功: 35 / 35
"""

failures = []


def build(root: Path, cases: list[tuple[str, str, int]]) -> None:
    """cases: [(tree_stamp, data_date, bars)]，末根 bar 固定为 2026-10-09。"""
    for stamp, ddate, bars in cases:
        tk = "AAA"
        tr = root / "reports" / tk / f"{tk}_{stamp}"
        tr.mkdir(parents=True, exist_ok=True)
        (tr / "RUN.json").write_text(
            '{"ticker":"AAA","data_date":"%s","ratings":{}}' % ddate, encoding="utf-8")
        md = EVID_TMPL.format(tk=tk, date=ddate, bars=bars, lastbar="2026-10-09")
        with zipfile.ZipFile(tr / "_source.zip", "w") as z:
            z.writestr(f"evidence/{tk}_{ddate}.md", md)


def scan_of(cases: list[tuple[str, str, int]]) -> tuple[list[dict], list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build(root, cases)
        ri.ROOT, ri.REPORTS, ri.EVID = root, root / "reports", root / "wb_analysis" / "evidence"
        ri.DRAFTS, ri.ANALYSIS = root / "wb_analysis" / "drafts", root / "wb_analysis" / "analysis"
        return ri.scan()


print("═══ 阳性夹具：标签不同、底层数据相同 ═══")
rows_pos, pos = scan_of([("20261010_120000", "2026-10-10", 65),
                         ("20261011_120000", "2026-10-11", 65)])
print(f"  （扫到 {len(rows_pos)} 棵树）")
for r in rows_pos:
    print(f"   row: {r['ticker']} date={r['date']} last_bar={r['last_bar']} bars={r['bars']}")
for x in pos:
    print("  -", x)
hit = any("内容重复" in x for x in pos)
print(f"  ⇒ 判定：{'PASS（命中）' if hit else 'FAIL（未命中）'}")
if not hit:
    failures.append("阳性夹具未命中")

print("\n═══ 阴性夹具：末根 bar 相同但根数不同（不同轮次）═══")
rows_neg, neg = scan_of([("20261010_120000", "2026-10-10", 65),
                         ("20261011_120000", "2026-10-11", 250)])
print(f"  （扫到 {len(rows_neg)} 棵树）")
for x in neg:
    print("  -", x)
bad = any("内容重复" in x for x in neg)
print(f"  ⇒ 判定：{'PASS（未误报）' if not bad else 'FAIL（误报）'}")
if bad:
    failures.append("阴性夹具误报")

print("\n" + "=" * 60)
if failures:
    print("✗ 双侧验证失败：", "; ".join(failures))
    sys.exit(1)
print("✓ 双侧验证通过：同型重复命中、不同轮次不误报")
