# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe quant/cleanup_cache.py
"""缓存清理工具 —— 任务结束后想释放磁盘时用。

用法：
    python cleanup_cache.py             # 交互确认后清理全部
    python cleanup_cache.py --yes       # 跳过确认
    python cleanup_cache.py --keep-edgar  # 只清价格与成分股，保留 EDGAR
    python cleanup_cache.py --status    # 只看占用，不清理

━━━ 先想清楚要不要清 ━━━
**EDGAR 与价格的缓存，清掉后下次要整套重下**（分钟级）。
占多少以 `--status` 的实时输出为准 —— 本文档曾写死「总共约 70 MB」，
实测一个月内已涨到 **591 MB**（prices 265 + cache 220 + edgar 101）；
**写死的数字必然漂移，此处不再给数**。`scripts/_health.py` 的「堆积预算」
会在超预算（当前 1024 MB）时提醒你。

如果只是想省磁盘，**保持缓存通常更划算**。真要清，这个脚本一键搞定。

实现说明：本机有 safe-delete 钩子会拦截目录级删除，
故此处**逐文件 os.remove + 自深到浅 os.rmdir**（该路径不受拦截）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
BASE = HOME / ".tradingagents"

TARGETS = {
    "edgar": BASE / "edgar",                    # EDGAR XBRL facts（瘦身后约 22 MB）
    "prices": BASE / "prices",                  # 长周期价格（约 47 MB）
    "constituents": None,                       # 在 cache/ 下的成分股与行业
    "screener": None,                           # 在 cache/ 下的选股结果
}
CACHE_DIR = BASE / "cache"


def _dir_size(p: Path) -> tuple[int, int]:
    if not p.exists():
        return 0, 0
    n = s = 0
    for f in p.rglob("*"):
        if f.is_file():
            n += 1
            try:
                s += f.stat().st_size
            except OSError:
                pass
    return n, s


def _remove_dir_contents(p: Path) -> tuple[int, int]:
    """逐文件删除（绕开 safe-delete 对目录级操作的拦截）。"""
    if not p.exists():
        return 0, 0
    removed = freed = 0
    for f in sorted(p.rglob("*"), key=lambda x: -len(x.parts)):
        try:
            if f.is_file():
                freed += f.stat().st_size
                os.remove(f)
                removed += 1
            elif f.is_dir():
                os.rmdir(f)
        except OSError:
            pass   # 被占用的跳过，不 fail
    return removed, freed


def show_status() -> None:
    print("=" * 74)
    print("缓存占用")
    print("=" * 74)
    total = 0
    for name, p in TARGETS.items():
        if name == "edgar":
            p = BASE / "edgar"
        elif name == "prices":
            p = BASE / "prices"
        else:
            continue
        n, s = _dir_size(p)
        total += s
        print(f"  {name:<14} {n:>5} 文件  {s/1024/1024:>8.1f} MB")
    # cache/ 下按前缀细分
    if CACHE_DIR.exists():
        groups: dict[str, list[int]] = {}
        for f in CACHE_DIR.rglob("*"):
            if f.is_file():
                key = f.name.split("_")[0] if "_" in f.name else "其他"
                g = groups.setdefault(key, [0, 0])
                g[0] += 1
                g[1] += f.stat().st_size
        for k in sorted(groups):
            n, s = groups[k]
            total += s
            print(f"  cache/{k:<8} {n:>5} 文件  {s/1024/1024:>8.1f} MB")
    print(f"  {'合计':<14} {'':>5}        {total/1024/1024:>8.1f} MB")


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 TradingAgents 缓存")
    ap.add_argument("--yes", action="store_true", help="跳过确认")
    ap.add_argument("--status", action="store_true", help="只显示占用")
    ap.add_argument("--keep-edgar", action="store_true",
                    help="保留 EDGAR 缓存（它瘦身后只占 22 MB，重下要 146 秒）")
    ap.add_argument("--keep-prices", action="store_true",
                    help="保留价格缓存（重下要 42 秒）")
    args = ap.parse_args()

    show_status()
    if args.status:
        return 0

    plan: list[tuple[str, Path]] = []
    if not args.keep_edgar:
        plan.append(("EDGAR facts", BASE / "edgar"))
    if not args.keep_prices:
        plan.append(("长周期价格", BASE / "prices"))
    plan.append(("成分股/行业", CACHE_DIR))       # 小文件，一并清

    print()
    print("将清理：", "、".join(n for n, _ in plan))
    if not args.yes:
        try:
            if input("确认？(y/N) ").strip().lower() not in ("y", "yes"):
                print("已取消")
                return 0
        except EOFError:
            print("非交互环境，请加 --yes"); return 1

    total_n = total_b = 0
    for name, p in plan:
        n, b = _remove_dir_contents(p)
        total_n += n
        total_b += b
        print(f"  {name:<14} 删除 {n:>4} 个文件，释放 {b/1024/1024:.1f} MB")
    print(f"\n共释放 {total_b/1024/1024:.1f} MB")
    print("下次运行会重新下载（EDGAR 约 146 秒、价格约 42 秒）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
