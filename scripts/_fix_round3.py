#!/usr/bin/env python
# lifecycle: maintenance
"""第三轮收口：修 _thresholds.py 的注解未定义名、修 round2 的 CI 双补丁覆盖 bug、摊开 collect_index.py 的 F811 现场。

用法：
    ./.venv/Scripts/python.exe scripts/_fix_round3.py            # 干跑
    ./.venv/Scripts/python.exe scripts/_fix_round3.py --apply
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THR = ROOT / "wb_analysis" / "_thresholds.py"
R2 = ROOT / "scripts" / "_apply_round2.py"
CIIDX = ROOT / "wb_analysis" / "collect_index.py"

FUTURE = "from __future__ import annotations"
TC_BLOCK = ("\nfrom typing import TYPE_CHECKING\n"
            "\nif TYPE_CHECKING:  # 只为字符串注解提供名字，运行时不导入\n"
            "    import datetime\n")
OLD_CALL = '    cov1, cov1_msgs = patch_cov(CI_YML, "ci.yml")'
NEW_CALL = '''    if ci_text is not None:
        _tmp = ROOT / ".ci_tmp.yml"
        write(_tmp, ci_text)
        cov1, cov1_msgs = patch_cov(_tmp, "ci.yml")
        _tmp.unlink()
    else:
        cov1, cov1_msgs = patch_cov(CI_YML, "ci.yml")'''
OLD_LOOP = "        for p, s in [(CI_YML, ci_text), (CI_YML, cov1), (CI_WIN, cov2),"
NEW_LOOP = "        for p, s in [(CI_YML, cov1), (CI_WIN, cov2),"


def read(p: Path) -> str:
    with p.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(p: Path, s: str) -> None:
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(s)


def main() -> int:
    apply = "--apply" in sys.argv
    print(f"=== {'APPLY' if apply else 'DRY-RUN'} ===\n")

    # 1) _thresholds.py：字符串注解里的 datetime 补一个仅类型检查期的导入
    t = read(THR)
    if "TYPE_CHECKING" in t:
        print("  [已有] _thresholds.py 已含 TYPE_CHECKING 块")
    elif FUTURE not in t:
        print("  [FAIL] _thresholds.py 没找到 `from __future__ import annotations`")
    else:
        t = t.replace(FUTURE, FUTURE + "\n" + TC_BLOCK.strip("\n"), 1)
        print("  [改] _thresholds.py 加 TYPE_CHECKING 导入（修 2 处 F821）")
        if apply:
            write(THR, t)

    # 2) _apply_round2.py：CI 双补丁覆盖 bug
    r2 = read(R2)
    if NEW_CALL in r2:
        print("  [已有] _apply_round2.py 已修")
    elif OLD_CALL in r2 and OLD_LOOP in r2:
        r2 = r2.replace(OLD_CALL, NEW_CALL, 1).replace(OLD_LOOP, NEW_LOOP, 1)
        print("  [改] _apply_round2.py：cov1 改为基于 ci_text 计算")
        if apply:
            write(R2, r2)
    else:
        print("  [FAIL] _apply_round2.py 锚点未匹配")

    # 3) 摊开 collect_index.py 的 F811 现场（只读）
    print("\n--- collect_index.py 198-212（F811 现场）---")
    lines = read(CIIDX).splitlines()
    for i in range(197, min(212, len(lines))):
        print(f"    {i + 1:>4}| {lines[i]}")

    print("\n" + ("已写入。" if apply else "干跑结束，未改动。加 --apply 写入。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
