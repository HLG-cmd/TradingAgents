# lifecycle: oneoff
# created: 2026-10-11
# serves: （门禁双侧自检，无标的）
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_selftest_ironlaw24_guard.py
"""O1 双侧验证：铁律 24 守卫必须在「短历史」命中、在「长历史」静默。

- 短历史夹具：SKHY（从封存报告树的 _source.zip 取证据包；65 根 K 线）
- 长历史夹具：wb_analysis/evidence/TSM_*.md（若存在）
用法：./.venv/Scripts/python.exe scripts/_oneoff/_selftest_ironlaw24_guard.py
"""
from __future__ import annotations

import importlib.util
import io
import re
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("ds", ROOT / "wb_analysis" / "_derive_stock.py")
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)


def run_on(md_text: str, ticker: str, date: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        # ⚠️ 必须按字节写入：证据包是 CRLF，若走 write_text 的换行翻译会变成
        #    \r\r\n，读回后多出一个空行，使 `### name\n``` ` 失配 ⇒ series() 返回空。
        (Path(tmp) / f"{ticker}_{date}.md").write_bytes(md_text.encode("utf-8"))
        ds.EV = Path(tmp)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ds.report(ticker, date)
        return buf.getvalue()


def guard_section(out: str) -> str:
    m = re.search(r"A2\. 铁律 24 自检.*?(?=\nB\. 最近)", out, re.S)
    return m.group(0) if m else "(未找到 A2 段)"


failures = []

# ── 短历史夹具 ──────────────────────────────────────────────────────
zip_path = ROOT / "reports" / "SKHY" / "SKHY_20261011_102533" / "_source.zip"
with zipfile.ZipFile(zip_path) as z:
    md_short = z.read("evidence/SKHY_2026-10-10.md").decode("utf-8")
out_short = guard_section(run_on(md_short, "SKHY", "2026-10-10"))
print("═══ 短历史（SKHY 65 根）═══")
print(out_short)
hit = "自检命中" in out_short and "close_200_sma" in out_short
print(f"  ⇒ 判定：{'PASS（已命中）' if hit else 'FAIL（未命中）'}")
if not hit:
    failures.append("短历史夹具未命中")

# ── 长历史夹具 ──────────────────────────────────────────────────────
cands = sorted((ROOT / "wb_analysis" / "evidence").glob("*_2*.md"))
cands = [c for c in cands if ".derived." not in c.name]
print("\n═══ 长历史夹具候选 ═══")
for c in cands:
    print("  -", c.name)
if cands:
    p = cands[0]
    tk, dt = p.stem.rsplit("_", 1)
    out_long = guard_section(run_on(p.read_text(encoding="utf-8"), tk, dt))
    print(f"\n═══ 长历史（{tk} {dt}）═══")
    print(out_long)
    silent = "未命中" in out_long
    print(f"  ⇒ 判定：{'PASS（静默）' if silent else 'FAIL（误报）'}")
    if not silent:
        failures.append(f"长历史夹具误报：{tk}")
else:
    print("  ⚠ 无长历史夹具可用（evidence/ 为空）—— 该方向未验证")
    failures.append("缺少长历史夹具")

# ── 第三向（2026-10-12 新增）：旧格式证据包必须「跳过」而非误报 ──────────
#   旧版 collect.py 不写 `- bars:` 字段，而 K 线表恒被截断为 20 行
#   ⇒ 若拿表长当根数，会把**长历史标的**判成「50 日线、200 日线都不存在」的假警报。
#   正确的行为是：无法判定 ⇒ 明确跳过，不猜、不误报。
LEGACY_MD = """# 证据包：LGCY

- 采集日期: 2026-10-10

## 1. 行情与价格结构

```
关键统计:
- latest_close: 344.86
- ret_5d: 1.23

最近 20 根 K 线:
Date   Open   High    Low  Close   Volume
2026-09-11 332.73 339.95 332.55 335.45 15820700
2026-09-14 339.11 346.45 338.74 345.71 22484400
2026-09-15 343.34 344.36 339.18 341.43 13361000
2026-09-16 341.29 344.05 340.32 343.05 11223300
2026-09-17 343.20 346.10 342.00 345.20 12131400
2026-09-18 345.10 347.00 344.00 344.86 13141500
2026-09-21 344.80 346.50 343.50 345.90 14151600
2026-09-22 346.00 348.00 345.00 347.10 15161700
2026-09-23 347.00 349.00 346.00 348.20 16171800
2026-09-24 348.20 350.00 347.00 349.30 17181900
2026-09-25 349.30 351.00 348.00 350.40 18192000
2026-09-28 350.40 352.00 349.00 351.50 19202100
2026-09-29 351.50 353.00 350.00 352.60 20212200
2026-09-30 352.60 354.00 351.00 353.70 21222300
2026-10-01 353.70 355.00 352.00 354.80 22232400
2026-10-02 354.80 356.00 353.00 355.90 23242500
2026-10-05 355.90 357.00 354.00 357.00 24252600
2026-10-06 344.64 345.67 341.70 344.59 13177400
2026-10-07 343.68 347.61 340.28 347.37 11344700
2026-10-08 349.64 353.53 343.51 344.86 13956400
```

### close_50_sma
```
2026-10-08: 350.11
2026-10-07: 349.22
```

### close_200_sma
```
2026-10-08: 338.44
2026-10-07: 337.90
```

## 通道健康度

- 成功: 35 / 35
- 非全绿通道: 无
"""
out_legacy = guard_section(run_on(LEGACY_MD, "LGCY", "2026-10-10"))
print("\n═══ 旧格式证据（无 `bars:` 字段 + 表被截断为 20 行）═══")
print(out_legacy)
skipped = "跳过" in out_legacy and "⛔" not in out_legacy
print(f"  ⇒ 判定：{'PASS（明确跳过、零误报）' if skipped else 'FAIL（误报）'}")
if not skipped:
    failures.append("旧格式证据未跳过（产生假警报）")

print("\n" + "=" * 60)
if failures:
    print("✗ 双侧验证失败：", "; ".join(failures))
    sys.exit(1)
print("✓ 三向验证通过：短历史命中、长历史静默、缺根数时明确跳过")