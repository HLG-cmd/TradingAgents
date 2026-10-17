# lifecycle: oneoff
# created: 2026-10-11
# serves: （门禁双侧自检，无标的）
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_selftest_edgar_gap.py
"""O4 + O5 双侧验证。

O5：`missing_tag_verdict` 三种成因必须给出**三种不同**说法
    （结构性缺失 / 标签不存在 / 采集失败）—— 旧版把它们打印成同一种。
O4：`_gap_ledger.build` 必须能通过状态副档把 `edgar_raw` 缺口**发出来**；
    无副档时不产生该缺口（避免把「不适用」误报成「缺失」）。

用法：./.venv/Scripts/python.exe scripts/_oneoff/_selftest_edgar_gap.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
failures: list[str] = []


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ver = load("ver", "wb_analysis/_verify_edgar_raw.py")
gl = load("gl", "wb_analysis/_gap_ledger.py")

# ── O5：三种成因三套说法 ─────────────────────────────────────────────
print("═══ O5：SEC 侧取不到值的三种成因 ═══")
ffd_only = {"ffd": {"NetFeeAmt": {"units": {"USD": [{}]}}}}
with_gaap = {"us-gaap": {"Assets": {}, "Revenues": {}}}
cases = [
    ("SKHY 型：只有 ffd 税种", None, ffd_only, False, "结构性缺失"),
    ("常规：有 us-gaap，缺个别 tag", None, with_gaap, True, "SEC 无该标签"),
    ("网络失败：缓存为空", "ConnectionError: timed out", {}, False, "未核验（采集失败）"),
]
verdicts = []
for label, err, tax, has_fin, expect in cases:
    v = ver.missing_tag_verdict(err, tax, has_fin)
    verdicts.append(v)
    ok = expect in v
    print(f"  {label:32s} → {v}   {'PASS' if ok else 'FAIL'}")
    if not ok:
        failures.append(f"O5 分支错误：{label}")
if len(set(verdicts)) != 3:
    failures.append("O5：三种成因未给出三套不同说法")
    print("  ✗ 三种成因未区分开")
else:
    print("  ✓ 三种成因三套说法，互不混淆")

# ── O4：副档驱动台账 ─────────────────────────────────────────────────
print("\n═══ O4：状态副档 → 台账缺口 ═══")
EVID_MD = """# 证据包：ZZZ

- 采集日期: {d}

## 1. 行情与价格结构

```
关键统计:
- latest_close: 10.00
- bars: 250
```

## 通道健康度

- 成功: 35 / 35
- 非全绿通道: 无
"""


def gap_of(sidecar: dict | None, ticker="ZZZ", date="2026-10-10") -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        ev = Path(tmp)
        (ev / f"{ticker}_{date}.md").write_bytes(EVID_MD.format(d=date).encode("utf-8"))
        if sidecar is not None:
            (ev / f"{ticker}_{date}.edgar.json").write_text(
                json.dumps(sidecar, ensure_ascii=False), encoding="utf-8")
        gl.EVID = ev
        gl.ROOT = ev          # parse_evidence 会做 relative_to(ROOT)，必须一并指向夹具
        return gl.build(ticker, date).get("gaps", [])


for status, want_cls, want_dec in [("taxonomy_missing", "A", True),
                                   ("mismatch", "C", True),
                                   ("fetch_failed", "B", False),
                                   ("partial", "A", False)]:
    gs = [g for g in gap_of({"status": status, "detail": "夹具"}) if g["channel"] == "edgar_raw"]
    got = (gs[0]["cls"], gs[0]["decisive"]) if gs else (None, None)
    ok = got == (want_cls, want_dec)
    print(f"  status={status:18s} → cls={got[0]} decisive={got[1]}  期望 ({want_cls}, {want_dec})  "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        failures.append(f"O4 映射错误：{status}")

# verified → 登记为 resolved，不得算作缺口
gs = [g for g in gap_of({"status": "verified", "detail": "全一致"}) if g["channel"] == "edgar_raw"]
ok = len(gs) == 1 and gs[0]["status"] == "resolved" and not gs[0]["decisive"]
print(f"  status=verified → {'resolved 且非决定性' if ok else '异常'}   {'PASS' if ok else 'FAIL'}")
if not ok:
    failures.append("O4 verified 映射错误")

# 无副档 → 不产生 edgar_raw 缺口（指数/ETF 不适用，不得误报）
gs = [g for g in gap_of(None) if g["channel"] == "edgar_raw"]
ok = not gs
print(f"  无副档 → {'不产生缺口' if ok else '误报缺口'}   {'PASS' if ok else 'FAIL'}")
if not ok:
    failures.append("O4 无副档时误报")

print("\n" + "=" * 60)
if failures:
    print("✗ 双侧验证失败：", "; ".join(failures))
    sys.exit(1)
print("✓ 双侧验证通过：O5 三分支可分、O4 副档驱动且不误报")
