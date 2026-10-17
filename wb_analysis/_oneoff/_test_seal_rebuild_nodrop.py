# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_test_seal_rebuild_nodrop.py
"""回归测试：验证 `_seal_run.py` 的「部分相同 + 部分不同」场景不再丢件。

## 复现的事故（本项目实测）
563020 本轮：`--rebuild` 后审计包从 19 项掉到 13 项，丢掉 6 个**未变**的文件
（evidence 3 件 + 0_derived + fundamentals + meta.json）。
根因 = 判据阶段带副作用（当场 unlink「相同」的散件），
导致 `--rebuild` 只能在**已被自己部分清空的目录**上重建。

## 本测试怎么做（合成夹具，不碰真实产物）
1. 造一个临时树 + 临时 drafts（用 `TESTSEAL_9999-01-01` 作 ticker/date，
   与任何真实产物无交集）；
2. 首次封存 → 得到基线包（N 项）；
3. **只改其中一个文件**，其余保持逐字节一致（制造"部分相同、部分不同"）；
4. 跑 `--rebuild --apply`；
5. 断言：重建后包内条目数 **== N**（不丢件），且被改的那个文件是新内容、
   未改的文件仍在包内。

⚠️ 全程在临时目录，结束后逐文件删除；不触碰 reports/ 下任何真实树。
"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

TICKER = "TESTSEAL"
DATE = "9999-01-01"
BACKUP_DIR = ROOT / ".workbuddy-ai" / "backup"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    import wb_analysis._seal_run as sr

    drafts = sr.DRAFTS / f"{TICKER}_{DATE}"
    evid = sr.EVID
    tree = ROOT / "reports" / TICKER / f"{TICKER}_test000000"
    created: list[Path] = []

    try:
        # ── 1. 造夹具：3 个 drafts + 1 个 evidence ──
        (drafts / "1_analysts").mkdir(parents=True, exist_ok=True)
        tree.mkdir(parents=True, exist_ok=True)
        files = {
            drafts / "0_brief.md": "brief v1\n",
            drafts / "1_analysts" / "market.md": "market v1\n",
            drafts / "1_analysts" / "news.md": "news v1\n",
            drafts / "meta.json": json.dumps({"ticker": TICKER, "as_of": DATE}),
            evid / f"{TICKER}_{DATE}.md": "evidence v1\n",
        }
        for p, c in files.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c, encoding="utf-8", newline="\n")
            created.append(p)

        # ── 2. 首次封存 ──
        rc = sr.seal(TICKER, DATE, tree, True, force=True)
        zp = tree / "_source.zip"
        with zipfile.ZipFile(zp) as z:
            base = sorted(z.namelist())
        print(f"  首次封存：{len(base)} 项（rc={rc}）")

        # ── 3. 只改 1 个文件（造"部分相同、部分不同"）──
        # ⚠️ 首次封存已把 drafts 目录整体删除 ⇒ 重写前必须先重建目录（这正是真实流程：
        #    再渲染时脚本会新建 drafts/<T>_<date>/）。
        drafts.mkdir(parents=True, exist_ok=True)
        (drafts / "0_brief.md").write_text("brief v2 CHANGED\n", encoding="utf-8", newline="\n")
        # 其余文件**重新写回**（模拟"再渲染后散件回到工作目录"）
        for p, c in files.items():
            if p.name == "0_brief.md":
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(c, encoding="utf-8", newline="\n")
        print("  已制造：1 个变更 + 4 个逐字节相同")

        # ── 4. 走"过期 → rebuild"两步（与真实使用一致）──
        rc1 = sr.seal(TICKER, DATE, tree, True, force=True)          # 应报"已过期" rc=1
        rc2 = sr.seal(TICKER, DATE, tree, True, force=True, rebuild=True)
        print(f"  过期检测 rc={rc1}（期望 1）｜ rebuild rc={rc2}（期望 0）")

        with zipfile.ZipFile(zp) as z:
            after = sorted(z.namelist())
            brief2 = z.read(f"drafts/{TICKER}_{DATE}/0_brief.md").decode("utf-8")
            news2 = z.read(f"drafts/{TICKER}_{DATE}/1_analysts/news.md").decode("utf-8")
            seal2 = json.loads(z.read("SEAL.json").decode("utf-8"))

        # ── 5. 断言 ──
        checks = [
            ("重建后条目数不丢件", len(after) == len(base), f"{len(base)} → {len(after)}"),
            ("变更文件已更新", "CHANGED" in brief2, brief2.strip()[:30]),
            ("未变文件仍在包内", "news v1" in news2, news2.strip()[:30]),
            ("SEAL.n_entries 与实际一致", seal2["n_entries"] == len(after),
             f"SEAL={seal2['n_entries']} 实际={len(after)}"),
        ]
        ok = True
        for name, cond, detail in checks:
            print(f"  {'✓' if cond else '✗'} {name}：{detail}")
            ok &= cond

        print()
        print("  结论：" + ("✓ 不丢件（修复生效）" if ok else "✗ 仍丢件"))
        return 0 if ok else 1

    finally:
        # ── 清理：逐文件删除，再自深到浅 rmdir ──
        for p in created:
            try:
                p.unlink()
            except OSError:
                pass
        for base_dir in (drafts, tree):
            if base_dir.exists():
                for sub in sorted([x for x in base_dir.rglob("*") if x.is_dir()],
                                  key=lambda x: len(x.parts), reverse=True):
                    try:
                        sub.rmdir()
                    except OSError:
                        pass
                try:
                    base_dir.rmdir()
                except OSError:
                    pass
        # 清掉本次实验的备份包
        for b in BACKUP_DIR.glob(f"source_{TICKER}_{DATE}_*.zip"):
            try:
                b.unlink()
            except OSError:
                pass
        print("  （夹具已清理）")


if __name__ == "__main__":
    raise SystemExit(main())
