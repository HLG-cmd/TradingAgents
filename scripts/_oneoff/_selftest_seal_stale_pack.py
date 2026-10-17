# lifecycle: oneoff
# created: 2026-10-12
# serves: （门禁双侧自检，无标的）
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_selftest_seal_stale_pack.py
"""回归夹具：`_seal_run.py` 的「审计包过期」检测（2026-10-12 修的那个数据销毁 bug）。

背景（真实事故）：封存工具原先**只按文件名**判断散件是否已在包内 ⇒
重跑时把**新**散件当「已在包内」删掉、**旧**包留着，还返回 0 ⇒
新版工作文件被销毁、交付树与审计包静默不一致。

三向夹具：
  ① 内容不同 + 不加 `--rebuild` ⇒ 必须返回 **1**、**不删任何散件**、包内仍是旧内容；
  ② 加 `--rebuild` ⇒ 返回 0、包内变为新内容、且**旧包已备份**；
  ③ 内容完全相同 ⇒ 返回 0、散件被清掉（这是原「幂等补完」的正当用途，不得误伤）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location("seal", ROOT / "wb_analysis" / "_seal_run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build(tmp: Path, pack_body: str, loose_body: str) -> tuple[object, Path, Path]:
    """返回 (模块, 树目录, 散件路径)。"""
    m = load()
    tree = tmp / "reports" / "AAA" / "AAA_20260101_000000"
    (tree).mkdir(parents=True)
    with zipfile.ZipFile(tree / "_source.zip", "w") as z:
        z.writestr("drafts/AAA_2026-01-01/1_analysts/market.md", pack_body)
    loose = tmp / "wb_analysis" / "drafts" / "AAA_2026-01-01" / "1_analysts" / "market.md"
    loose.parent.mkdir(parents=True)
    loose.write_bytes(loose_body.encode("utf-8"))
    for d in ("evidence", "analysis", "scripts/_oneoff"):
        (tmp / "wb_analysis" / d).mkdir(parents=True, exist_ok=True) if d != "scripts/_oneoff" \
            else (tmp / d).mkdir(parents=True, exist_ok=True)
    m.ROOT, m.REPORTS = tmp, tmp / "reports"
    m.EVID, m.DRAFTS = tmp / "wb_analysis" / "evidence", tmp / "wb_analysis" / "drafts"
    m.ANALYSIS, m.ONEOFF = tmp / "wb_analysis" / "analysis", tmp / "scripts" / "_oneoff"
    return m, tree, loose


def pack_of(tree: Path) -> str:
    with zipfile.ZipFile(tree / "_source.zip") as z:
        return z.read("drafts/AAA_2026-01-01/1_analysts/market.md").decode("utf-8")


fail = []
OLD, NEW = "OLD CONTENT\n", "NEW CONTENT（重跑后的新内容）\n"

# ── ① 内容不同 + 不加 --rebuild ──────────────────────────────────────
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    m, tree, loose = build(tmp, OLD, NEW)
    with redirect_stdout(io.StringIO()):
        rc = m.seal("AAA", "2026-01-01", tree, apply=True, force=True, rebuild=False)
    kept = loose.exists()
    still_old = pack_of(tree) == OLD
    ok = rc == 1 and kept and still_old
    print(f"① 内容不同/无 --rebuild : rc={rc} 散件保留={kept} 包内仍旧={still_old}  "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        fail.append("① 未正确拒绝并保留散件")

# ── ② 加 --rebuild ──────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    m, tree, loose = build(tmp, OLD, NEW)
    with redirect_stdout(io.StringIO()):
        rc = m.seal("AAA", "2026-01-01", tree, apply=True, force=True, rebuild=True)
    now_new = pack_of(tree) == NEW
    baks = sorted((tmp / ".workbuddy" / "backup").glob("source_AAA_*.zip"))
    backed = len(baks) == 1 and zipfile.ZipFile(baks[0]).read(
        "drafts/AAA_2026-01-01/1_analysts/market.md").decode("utf-8") == OLD
    ok = rc == 0 and now_new and backed
    print(f"② --rebuild            : rc={rc} 包内已更新={now_new} 旧包已备份={backed}  "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        fail.append("② --rebuild 未正确重建或未备份")

# ── ③ 内容完全相同（原「幂等补完」的正当用途）──────────────────────
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    m, tree, loose = build(tmp, OLD, OLD)
    with redirect_stdout(io.StringIO()):
        rc = m.seal("AAA", "2026-01-01", tree, apply=True, force=True, rebuild=False)
    gone = not loose.exists()
    ok = rc == 0 and gone
    print(f"③ 内容完全相同          : rc={rc} 冗余散件已清={gone}  {'PASS' if ok else 'FAIL'}")
    if not ok:
        fail.append("③ 相同内容时未正确清理冗余散件")

print()
print("=" * 62)
if fail:
    print("✗ 夹具失败：", "; ".join(fail))
    raise SystemExit(1)
print("✓ 三向夹具通过：过期必拒且不删、--rebuild 可重建并备份、同内容可清冗余")
