# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_repair_563020_seal.py
"""修复 `_seal_run.py --rebuild` 的**审计包不完整**问题。

## 发现的问题（本轮实测）
加 `--rebuild` 重建审计包后，新包只有 **13 项**，而旧包是 **19 项**。
缺的 6 项恰好是**内容未变**的那些：
    evidence/563020_2026-10-15.md / .json / .gaps.json
    drafts/563020_2026-10-15/0_derived.md
    drafts/563020_2026-10-15/1_analysts/fundamentals.md
    drafts/563020_2026-10-15/meta.json

⇒ 根因：`--rebuild` 的收集逻辑疑似只纳入「相对旧包内容有变」的文件，
  而审计包的语义是「**这一轮的完整可溯源快照**」——
  **未变的文件同样必须入包**，否则「报告里每个数字都能在包里溯源」这条承诺失效。
  （本轮修复只动了 8 个草稿 + 0_derived 之外的文件，若照 13 项封存，
   则证据包不在包内 ⇒ 反读溯源会缺最底层依据。）

## 本脚本做什么
按「**旧包全量 + 新包覆盖**」的并集重建：以旧包为基础，用新包内容覆盖，
再把当前散件（若还在）补齐 ⇒ 19 项完整包。旧包先备份。
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TREE = ROOT / "reports" / "563020" / "563020_20261016_133333"
PKG = TREE / "_source.zip"
BACKUP_DIR = ROOT / ".workbuddy-ai" / "backup"
OLD = BACKUP_DIR / "source_563020_2026-10-15_20261016_145230.zip"

EVID = ROOT / "wb_analysis" / "evidence"
DRAFTS = ROOT / "wb_analysis" / "drafts" / "563020_2026-10-15"

# 应入包的完整清单（与首轮 19 项一致）
EXPECT = [
    "SEAL.json",
    "drafts/563020_2026-10-15/0_brief.md",
    "drafts/563020_2026-10-15/0_derived.md",
    "drafts/563020_2026-10-15/1_analysts/fundamentals.md",
    "drafts/563020_2026-10-15/1_analysts/market.md",
    "drafts/563020_2026-10-15/1_analysts/news.md",
    "drafts/563020_2026-10-15/1_analysts/sentiment.md",
    "drafts/563020_2026-10-15/2_research/bear.md",
    "drafts/563020_2026-10-15/2_research/bull.md",
    "drafts/563020_2026-10-15/2_research/manager.md",
    "drafts/563020_2026-10-15/3_trading/trader.md",
    "drafts/563020_2026-10-15/4_risk/aggressive.md",
    "drafts/563020_2026-10-15/4_risk/conservative.md",
    "drafts/563020_2026-10-15/4_risk/neutral.md",
    "drafts/563020_2026-10-15/4_risk/portfolio_manager.md",
    "drafts/563020_2026-10-15/meta.json",
    "evidence/563020_2026-10-15.gaps.json",
    "evidence/563020_2026-10-15.json",
    "evidence/563020_2026-10-15.md",
]


def norm(name: str) -> str:
    """把包内路径统一成「相对项目根」形式，便于与磁盘对齐。"""
    return name.replace("\\", "/")


def main() -> int:
    if not OLD.exists():
        print(f"✗ 找不到旧包 {OLD.relative_to(ROOT)}")
        return 1

    # ── 1. 先看当前各件在哪：新包 / 旧包 / 磁盘散件 ──
    with zipfile.ZipFile(PKG) as z:
        cur = {norm(n): z.read(n) for n in z.namelist()}
    with zipfile.ZipFile(OLD) as z:
        old = {norm(n): z.read(n) for n in z.namelist()}

    disk: dict[str, bytes] = {}
    for rel in EXPECT:
        if rel == "SEAL.json":
            continue
        if rel.startswith("drafts/"):
            p = DRAFTS / rel[len("drafts/563020_2026-10-15/"):]
        elif rel.startswith("evidence/"):
            p = EVID / Path(rel).name
        else:
            continue
        if p.exists():
            disk[rel] = p.read_bytes()

    print(f"新包 {len(cur)} 项 ｜ 旧包 {len(old)} 项 ｜ 磁盘散件 {len(disk)} 项")

    # ── 2. 逐项决定来源：磁盘散件（最新） > 新包 > 旧包 ──
    rebuilt: dict[str, bytes] = {}
    src_stat: dict[str, str] = {}
    for rel in EXPECT:
        if rel in disk:
            rebuilt[rel] = disk[rel]
            src_stat[rel] = "磁盘(最新)"
        elif rel in cur:
            rebuilt[rel] = cur[rel]
            src_stat[rel] = "新包"
        elif rel in old:
            rebuilt[rel] = old[rel]
            src_stat[rel] = "旧包(未变)"
        else:
            print(f"  ✗ 缺失且无处可取：{rel}")
            return 1

    # ── 3. 备份当前（不完整）包，再写重建包 ──
    bad_backup = BACKUP_DIR / "source_563020_2026-10-15_20261016_145230_INCOMPLETE13.zip"
    shutil.copy2(PKG, bad_backup)
    print(f"  ↺ 已备份不完整包 → {bad_backup.name}")

    with zipfile.ZipFile(PKG, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in EXPECT:
            z.writestr(rel, rebuilt[rel])

    # ── 4. 逐项校验 ──
    with zipfile.ZipFile(PKG) as z:
        inner = {norm(n): z.read(n) for n in z.namelist()}
    if set(inner) != set(EXPECT):
        miss = set(EXPECT) - set(inner)
        extra = set(inner) - set(EXPECT)
        print(f"  ✗ 校验失败：缺失 {sorted(miss)} 多余 {sorted(extra)}")
        return 1
    for rel in EXPECT:
        if inner[rel] != rebuilt[rel]:
            print(f"  ✗ 校验失败：{rel} 内容不一致")
            return 1

    print(f"  ✓ 重建校验通过：{len(inner)} 项，逐项内容一致")
    print()
    print("  各件来源：")
    for rel in EXPECT:
        print(f"    {src_stat.get(rel,'—'):12s} {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
