# lifecycle: reusable
# created: 2026-10-12
# serves: 任意标的 / 任意轮次
# usage: ./.venv/Scripts/python.exe scripts/_verify_pack_tree.py <报告树目录>
"""验证「交付树」与「审计包 _source.zip」**逐项内容一致**（通用版）。

★ 为什么要有通用版（2026-10-12 事故）：
原 `scripts/_oneoff/_verify_pack_matches_tree.py` 把 `TREE` **硬编码**为 GOOG 树，
**命令行传入的路径被完全忽略**。用它去校验 SKHY 时，它照样打印一排 ✓，
而那些 ✓ 全部是关于 GOOG 的 —— 一个**看起来全绿的假报告**。
这正是铁律 41「不要只说 N/N 全绿」的实测版本：**校验器本身会撒谎**。

⇒ 本版的两条硬约束：
  ① 树路径**只能**来自命令行参数，代码中**不得**出现任何标的/日期字面量；
  ② 草稿前缀（`drafts/<T>_<date>/`）从树内 `SEAL.json` 动态读出，不猜、不写死。

判据：包内每个 `drafts/.../<role>.md` 的内容（统一行尾后）必须与交付树对应角色文件
逐字节一致；且包内必须含该轮全部 evidence 副档。
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

# 草稿名 → 交付树名（组合经理在渲染时改名为 decision.md）
MAP: dict[str, str] = {
    "1_analysts/market.md": "1_analysts/market.md",
    "1_analysts/fundamentals.md": "1_analysts/fundamentals.md",
    "1_analysts/news.md": "1_analysts/news.md",
    "1_analysts/sentiment.md": "1_analysts/sentiment.md",
    "2_research/bull.md": "2_research/bull.md",
    "2_research/bear.md": "2_research/bear.md",
    "2_research/manager.md": "2_research/manager.md",
    "3_trading/trader.md": "3_trading/trader.md",
    "4_risk/aggressive.md": "4_risk/aggressive.md",
    "4_risk/conservative.md": "4_risk/conservative.md",
    "4_risk/neutral.md": "4_risk/neutral.md",
    "4_risk/portfolio_manager.md": "5_portfolio/decision.md",
}


def norm(b: bytes) -> str:
    """统一行尾 **并** 去掉末尾换行。

    ★ 为什么必须去末尾换行（2026-10-12 实测）：`assemble.py` 把草稿写进报告树时
    会**剥掉文件末尾的换行**，而 `_source.zip` 里存的是原始草稿（带末尾换行）。
    ⇒ 逐字节比对会对**全部 12 个角色**报「内容不一致」，而真实差异只有 1 个字节。
    一个把「格式差异」报成「内容差异」的校验器，比没有校验器更危险 ——
    它会让人去追一个不存在的 bug，同时掩盖真正的不一致。
    """
    return b.replace(b"\r\n", b"\n").decode("utf-8", errors="replace").rstrip("\n")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        print("用法: ./.venv/Scripts/python.exe scripts/_verify_pack_tree.py <报告树目录>")
        return 2
    tree = Path(argv[1]).resolve()
    zp = tree / "_source.zip"
    if not zp.exists():
        print(f"✗ 该树无审计包：{zp}")
        return 1

    with zipfile.ZipFile(zp) as z:
        seal = json.loads(z.read("SEAL.json").decode("utf-8"))
        names = set(z.namelist())
        ticker, date = seal["ticker"], seal["data_date"]
        prefix = f"drafts/{ticker}_{date}/"

        print("=" * 70)
        print(f"包↔树一致性校验：{tree.name}  （{ticker} / {date}，封存于 {seal['sealed_at']}）")
        print("=" * 70)

        bad: list[str] = []

        print("\n=== ① 草稿 ↔ 交付树 逐项一致（统一行尾后比对）===")
        for draft_rel, tree_rel in MAP.items():
            arc = prefix + draft_rel
            tpath = tree / tree_rel
            if arc not in names:
                print(f"  ✗ 包内缺 {arc}")
                bad.append(arc)
                continue
            if not tpath.exists():
                print(f"  ✗ 树内缺 {tree_rel}")
                bad.append(tree_rel)
                continue
            if norm(z.read(arc)) == norm(tpath.read_bytes()):
                print(f"  ✓ {draft_rel:32s} ↔ {tree_rel}")
            else:
                print(f"  ✗ 内容不一致：{draft_rel} ↔ {tree_rel}")
                bad.append(arc)

        print("\n=== ② 包内证据与副档齐全 ===")
        ev = sorted(n for n in names if n.startswith(f"evidence/{ticker}_{date}"))
        if not ev:
            print(f"  ✗ 包内无任何 evidence/{ticker}_{date}* 条目")
            bad.append("evidence")
        for n in ev:
            print(f"  ✓ {n}")

        print("\n=== ③ 包内草稿数 vs 声明条目数 ===")
        drafts = sorted(n for n in names if n.startswith(prefix))
        print(f"  包内草稿 {len(drafts)} 个；SEAL.json 声明 {seal['n_entries']} 项；包内总条目 {len(names)}")
        if len(drafts) < len(MAP):
            print(f"  ✗ 草稿少于 12 角色（{len(drafts)} < {len(MAP)}）")
            bad.append("drafts-count")

    print("\n" + "=" * 70)
    if bad:
        print(f"✗ 不一致 {len(bad)} 项：")
        for x in bad[:20]:
            print(f"    - {x}")
        return 1
    print(f"✓ 交付树与审计包逐项一致（{len(names)} 条目）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
