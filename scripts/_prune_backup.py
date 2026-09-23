# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe scripts/_prune_backup.py [--apply]
"""清理 `.workbuddy/backup/` 里的回滚包：**按前缀各留最新 N 个**。

## 为什么不能「全局留最近 N 个」
2026-09-23 实测踩坑：最初写「保留最近 3 个」，结果把**最大的那个回滚包**
（1.35 MB、覆盖 134 个文件的删除）挤掉了，却留下了**两个内容完全相同的重复包**。
⇒ 保留策略必须**按类别**（前缀），否则重要的大回滚包会被小的最新包顶掉。

## 顺带做的两件事
  · 去掉内容完全相同的重复包（同一命令被执行两次会留下重复包）
  · 去掉空壳包（0 条目），那是中断留下的垃圾

用法:
  ./.venv/Scripts/python.exe scripts/_prune_backup.py            # dry-run
  ./.venv/Scripts/python.exe scripts/_prune_backup.py --apply
"""
import argparse
import hashlib
import zipfile
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
BK = ROOT / ".workbuddy" / "backup"
KEEP_PER_PREFIX = 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    all_zips = sorted(BK.glob("*.zip"))
    drop: list[tuple[Path, str]] = []

    def _sig(q: Path) -> dict[str, tuple[int, int]]:
        """条目标识：名字 -> (CRC, 大小)。只读 zip 中央目录，**不解压**。"""
        with zipfile.ZipFile(q) as z:
            return {i.filename: (i.CRC, i.file_size) for i in z.infolist()}

    # ---- 规则 1：损坏包 / 空壳包 ----
    sigs: dict[Path, dict[str, tuple[int, int]]] = {}
    for p in all_zips:
        try:
            sigs[p] = _sig(p)
        except Exception:                                        # noqa: BLE001
            drop.append((p, "压缩包损坏"))
            continue
        if len(sigs[p]) == 0:
            # ⚠️ 判据是 **0 条目**，不是「≤1」。
            # 原实现写成 `n <= 1`，与本文档自己的说明（"去掉空壳包（0 条目）"）不符，
            # 且会误删**只有 1 个文件的合法回滚包** —— 实测命中两个：
            #   `tidytool_20260923.zip`（scripts/_tidy_scripts.py）
            #   `prunefix_PRE_20260923.zip`（scripts/_prune_backup.py）
            # 备份管理工具误删备份，是这一层里最不该出现的失败。
            drop.append((p, "空壳包（0 条目）"))

    # ---- 规则 2：与另一个包内容完全相同（同一命令被执行两次的产物）----
    seen: dict[str, Path] = {}
    for p in all_zips:
        if p in {d for d, _ in drop}:
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h in seen:
            drop.append((p, f"与 {seen[h].name} 内容完全相同"))
        else:
            seen[h] = p

    # ---- 规则 3：被另一个包**严格包含** ⇒ 删子集（信息不丢）----
    # ★★ 必须在「按前缀限数」**之前**跑，否则等于没修。
    # 2026-09-23 实测踩坑（复现铁律 31⑤）：`deleted_20260923_FULL183.zip`（183 条目）与
    #   `deleted_20260923_000116_reports_cleanup.zip`（134 条目）是同一次删除的两次执行产物，
    #   134 那份**逐条目被 183 那份包含**（名字 + CRC + 大小全一致）。
    #   先按 mtime「留最新 2 个」⇒ **删掉更完整的那份、留下不完整的那份**。
    # ⇒ 判据与时间无关、可证明安全：x 的每个文件都在 y 里、且 y 条目更多 ⇒ 删 x。
    dropped = {d for d, _ in drop}
    for x in all_zips:
        if x not in sigs or x in dropped:
            continue
        for y in all_zips:
            if x is y or y not in sigs or y in dropped:
                continue
            sx, sy = sigs[x], sigs[y]
            if len(sx) < len(sy) and sx.items() <= sy.items():
                drop.append((x, f"被 {y.name} 严格包含（{len(sx)} ⊂ {len(sy)} 条目，逐条 CRC 一致）"))
                break

    # ---- 规则 4：按前缀各留最新 N 个（只在**幸存**的包上计算）----
    groups: dict[str, list[Path]] = defaultdict(list)
    for p in all_zips:
        if p in {d for d, _ in drop}:
            continue
        groups[p.name.split("_")[0]].append(p)
    for prefix, ps in sorted(groups.items()):
        ps.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        for p in ps[KEEP_PER_PREFIX:]:
            drop.append((p, f"{prefix}：超出保留数（留最新 {KEEP_PER_PREFIX} 个）"))

    # 去重：同一个包可能命中多条规则（下面 unlink 是按条执行的）
    seen_drop: set[Path] = set()
    uniq: list[tuple[Path, str]] = []
    for p, why in drop:
        if p in seen_drop:
            continue
        seen_drop.add(p)
        uniq.append((p, why))
    drop = uniq

    keep = sorted({p for p in BK.glob("*.zip")} - {p for p, _ in drop})
    print("=" * 84)
    print(f".workbuddy/backup 清理（{'APPLY' if args.apply else 'DRY-RUN'}）")
    print("=" * 84)
    total = 0
    for p, why in drop:
        print(f"  ✗ {p.name:52s} {p.stat().st_size/1024:7.0f} KB  ← {why}")
        total += p.stat().st_size
        if args.apply:
            p.unlink()
    print(f"\n  保留 {len(keep)} 个 / 清理 {len(drop)} 个（释放 {total/1024/1024:.2f} MB）")
    for p in keep:
        with zipfile.ZipFile(p) as z:
            n = len(z.namelist())
        print(f"  ✓ {p.name:52s} {n:4d} 条目")
    if not args.apply and drop:
        print("\n[DRY-RUN] 加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
