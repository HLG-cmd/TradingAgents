# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe scripts/_oneoff/_fix_two_sided_fixture.py
"""修正双向验证夹具：原先我拿「算对的数」当错值（差 0.0005，在容差内）⇒ 误判为「未通过」。

## 教训（值得记）
**测试夹具自身也会错**，而错的夹具会伪装成「被测量对象的缺陷」。
本例：我把 `4.3684 − 1.6669 = +2.702` 当作错值，而真值是 2.7015 ⇒ 差仅 0.0005，
在 `check_sums` 的 0.015 容差内 ⇒ 它正确判为「自洽」，但**我的期望写了 True** ⇒ 报「未通过」。
⇒ 这正是铁律 20「审计工具必须双向验证」的镜像：**期望值本身也要复算**。
"""
from __future__ import annotations

from pathlib import Path

P = Path(__file__).resolve().parent / "_verify_expr_re_two_sided.py"

SUBS = [
    ('run_case("右侧带正号（错值）", "股息率溢价：4.3684% - 1.6669% = +2.702", True)',
     'run_case("右侧带正号（错值）", "股息率溢价：4.3684% - 1.6669% = +3.10", True)'),
    ('run_case("右侧带 Unicode 负号（错值）", "净溢价：2.225% − 5.18% = −2.955", True)',
     'run_case("右侧带 Unicode 负号（错值）", "净溢价：2.225% − 5.18% = −3.40", True)'),
]


def main() -> int:
    t = P.read_text(encoding="utf-8")
    n = 0
    for a, b in SUBS:
        if a in t:
            t = t.replace(a, b, 1)
            n += 1
        else:
            print(f"  ✗ 未命中：{a[:56]}")
    P.write_text(t, encoding="utf-8", newline="\n")
    print(f"  已修正 {n} 处夹具")
    print("  真值核算：4.3684-1.6669=2.7015 ⇒ 错值改用 +3.10（差 0.40）")
    print("            2.225-5.180 =-2.9550 ⇒ 错值改用 -3.40（差 0.445）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
