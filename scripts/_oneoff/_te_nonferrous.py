# lifecycle: oneoff
# created: 2026-10-16
# -*- coding: utf-8 -*-
"""跟踪误差代理计算：同指数 ETF 日收益互偏法。

指数点位不可取（kline/quote 均无），故用**同指数组内互偏**作为 TE_proxy：
同指数 ETF 之间本应日收益一致，互偏的方差几乎全部来自各自跟踪误差。
TE_proxy = std(ETF日收益 − 组中位数日收益) × √242（年化，%）
另报：近1年累计跟踪差（复合）、组内排名。
"""
import sys

sys.path.insert(0, ".")
import math

from wb_analysis._westock import run_westock, parse_md_table

GROUPS = {
    "稀土产业": ["sh516150", "sz159713", "sh516780"],
    "中证有色": ["sz159876", "sz159871", "sz159881"],
    "细分有色": ["sh516650", "sz159652"],
    "CS稀金属": ["sh562800", "sh561800"],
}
SOLO = ["sh512400", "sh560860"]
START, END = "2025-10-15", "2026-10-15"


def daily_ret(code):
    h, b = parse_md_table(run_westock(
        ["kline", code, "--period", "day", "--start", START, "--end", END]))
    if not h or not b:
        return {}
    i_d, i_c = h.index("date"), h.index("last")
    pts = [(r[i_d], float(r[i_c])) for r in b]
    pts.reverse()
    out = {}
    for i in range(1, len(pts)):
        if pts[i - 1][1] > 0:
            out[pts[i][0]] = pts[i][1] / pts[i - 1][1] - 1
    return out


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


print(f"{'组':<10}{'代码':<10}{'名称':<18}{'TE_proxy(年化%)':>14}{'近1年累计跟踪差%':>16}")
print("-" * 72)
results = {}
for gname, codes in GROUPS.items():
    series = {c: daily_ret(c) for c in codes}
    names = {}
    for c in codes:
        h, b = parse_md_table(run_westock(["quote", c]))
        names[c] = dict(zip(h, b[0])).get("name", c) if h and b else c
    common = sorted(set.intersection(*[set(s) for s in series.values()]))
    if len(common) < 60:
        print(f"{gname}: 共同交易日不足({len(common)})，跳过")
        continue
    # 组中位数日收益
    med = {d: median([series[c].get(d, 0) for c in codes]) for d in common}
    group = []
    for c in codes:
        diffs = [series[c][d] - med[d] for d in common if d in series[c]]
        te = (sum(x * x for x in diffs) / len(diffs)) ** 0.5 * math.sqrt(242) * 100
        cum = 0.0
        for d in common:
            if d in series[c]:
                cum = (1 + cum) * (1 + series[c][d] - med[d]) - 1
        group.append((c, names[c], te, cum * 100))
        print(f"{gname:<10}{c:<10}{names[c]:<18}{te:>14.2f}{cum * 100:>16.2f}")
    results[gname] = group
    print("-" * 72)

for c in SOLO:
    h, b = parse_md_table(run_westock(["quote", c]))
    n = dict(zip(h, b[0])).get("name", c) if h and b else c
    print(f"{'—':<10}{c:<10}{n:<18}{'无同指数对手':>14}{'TE不可测':>16}")
print()
print("注：TE_proxy 为组内互偏年化（同指数 ETF 间差异≈各自跟踪误差），非对指数本身的绝对 TE。")
