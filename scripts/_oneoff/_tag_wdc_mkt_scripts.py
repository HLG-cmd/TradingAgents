# lifecycle: oneoff
# created: 2026-10-08
# serves: WDC 2026-10-06
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_tag_wdc_mkt_scripts.py
"""给 wdc-mkt-r1（技术面分析师）留下的 7 个自算脚本补 lifecycle 头，供 _tidy_scripts.py 归位。

背景：子智能体在 scripts/ 下写了 _wdc_mkt_calc.py ~ _wdc_mkt_calc7.py 未声明生命周期，
     导致 scripts/_health.py 的「脚本生命周期」项 FAIL。
处置：声明为 oneoff（审计线索，不删），随后由 _tidy_scripts.py --apply 移入 scripts/_oneoff/。
"""
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

HDR = (
    "# lifecycle: oneoff\n"
    "# created: 2026-10-08\n"
    "# serves: WDC 2026-10-06\n"
    "# usage: 一次性自算探针（由 wdc-mkt-r1 技术面分析师生成，保留作审计线索）\n"
)

rc = 0
names = ["_wdc_mkt_calc.py"] + [f"_wdc_mkt_calc{i}.py" for i in range(2, 8)]
for n in names:
    p = SCRIPTS / n
    if not p.exists():
        print("  !! 缺失:", n)
        rc = 1
        continue
    t = io.open(p, encoding="utf-8").read()
    if "# lifecycle:" in t[:2000]:
        print("  跳过（已有声明）:", n)
        continue
    io.open(p, "w", encoding="utf-8", newline="").write(HDR + t)
    print("  已补声明:", n)

# 给主模型写的两个 oneoff 脚本补 serves 行
for n in ["_fix_wdc_rating_words.py", "_harmonize_wdc.py"]:
    p = SCRIPTS / n
    if not p.exists():
        print("  !! 缺失:", n)
        rc = 1
        continue
    t = io.open(p, encoding="utf-8").read()
    if "# serves:" in t[:2000]:
        print("  跳过（已有 serves）:", n)
        continue
    t2 = t.replace("# lifecycle: oneoff\n",
                   "# lifecycle: oneoff\n# created: 2026-10-08\n# serves: WDC 2026-10-06\n", 1)
    if t2 == t:
        print("  !! 未找到 lifecycle 行:", n)
        rc = 1
        continue
    io.open(p, "w", encoding="utf-8", newline="").write(t2)
    print("  已补 serves:", n)

sys.exit(rc)
