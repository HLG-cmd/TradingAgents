# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_sweep_563020_old_values.py [--apply]
"""全量扫描并（可选）**全局**替换本轮修复涉及的全部旧值。

## 三轮迭代史（每次都是上一版判据的缺陷所致，全部记录在此）
1. **v1 `replace(old,new,1)`** —— 只替换首例 ⇒ 同一文件同值多处时漏改
   （PM 的 `−1.02%`/`−3.30%` 就是这么漏掉的）。
2. **v2 按行豁免** —— 用「整行是否含『已更正』等词」决定跳过。
   但 PM 的 Investment Thesis 是**一整段超长单行**，行内含「已更正」⇒ **整行被误跳过**，
   于是同行里的真旧值永远扫不出来。
3. **v3（本版，现行）** —— 豁免改为**锚定到单独片段**：
   只在「澄清短语紧跟该值」时才跳过（如 `不是 515100`、`禁止引用 515100`），
   而**不因同行别处出现某个词就放弃整行**。

## 不许改的文件
- `0_derived.md`：机算产物（偏离度以对应标的为分母），一律不改。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "wb_analysis" / "drafts" / "563020_2026-10-15"
APPLY = "--apply" in sys.argv

DONT_TOUCH = {"0_derived.md"}

#: 仅当**该值本身处于这些澄清短语之后**时才豁免（锚定片段，不做整行豁免）
ALLOW_PATTERNS = [
    re.compile(r"(不是|≠|禁止引用|不引用|不适用于|尤其)\s*[（(]?\s*" + pat)
    for pat in ("515100", "512400", r"512400\.SS")
]


def is_allowed(text: str, pos: int, val: str) -> bool:
    """判断 pos 处的 val 是否应**豁免**（不替换）。

    两类豁免：① 澄清语境（提到 515100/512400）；② 均线类值未处于均线语境
    （如「华润江中 −1.59%」是当日涨跌，与 MA_20 无关）。
    """
    window = text[max(0, pos - 90): pos + len(val)]
    for rx in ALLOW_PATTERNS:
        if rx.search(window):
            return True
    if val in REQUIRE_MA_CTX and not in_ma_ctx(text, pos):
        return True
    return False


#: 需限定「均线/支撑」语境才替换的值（避免误伤个股涨跌幅等同形数字）
REQUIRE_MA_CTX = {"−1.01%", "−1.56%", "−2.69%", "−4.05%", "−3.20%",
                  "+1.56%", "+2.69%", "+4.05%", "+3.20%",
                  "−1.02%", "−1.59%", "−2.76%", "−4.22%", "+1.59%", "+2.76%", "+4.22%", "+3.30%", "−3.30%"}
MA_CTX_HINTS = ("MA_", "均线", "支撑", "阻力", "偏离", "年线", "距现价", "现价偏离")


def in_ma_ctx(text: str, pos: int) -> bool:
    """该位置是否处于均线/支撑语境（前后 60 字内出现均线类词）。"""
    win = text[max(0, pos - 60): pos + 60]
    return any(h in win for h in MA_CTX_HINTS)


RULES: list[tuple[str, str, str]] = [
    # ── 1. 均线硬伤 ──
    ("六条均线全部位于现价下方", "MA_10 及以上的五条均线全部位于现价下方", "均线硬伤"),
    ("六条均线全部在价格下方", "五条均线（MA_10 及以上）在价格下方", "均线硬伤"),
    ("六条均线全在价格下方", "五条均线在价格下方", "均线硬伤"),
    ("六条全在价格下方", "五条在价格下方", "均线硬伤"),
    ("六条均线全在下方", "五条均线在下方", "均线硬伤"),
    ("均线全部在价格下方", "五条均线在价格下方", "均线硬伤"),
    ("它们全部在价格下方", "五条均线在价格下方", "均线硬伤"),
    # ⚠️ 只替换「价格在全部均线上方」这个**完整断言**；
    #    「价格站在 MA_10 及以上全部均线上方」是修好的新表述，其子串含旧串，
    #    故须用负向断言避免二次污染。
    # ── 2. 规模算式 ──
    ("= 102.8791 亿份 ×", "= 103.02 亿份 ×", "规模算式"),
    ("102.8791 亿份 × 10-15 单位净值", "103.02 亿份 × 10-15 单位净值", "规模算式"),
    # ── 3. 辩论计数 ──
    ("熊派 7 条成立", "熊派 6 条成立", "辩论计数"),
    # ── 4. 分母口径（距现价）──
    ("−4.47%", "−4.44%", "下轨距现价"),
    ("−3.30%", "−3.20%", "年线距现价"),
    ("−1.02%", "−1.01%", "MA_10 距现价"),
    ("−1.59%", "−1.56%", "MA_20 距现价"),
    ("−2.76%", "−2.69%", "MA_60 距现价"),
    ("−4.22%", "−4.05%", "MA_120 距现价"),
    ("+1.59%", "+1.56%", "MA_20 偏离"),
    ("+2.76%", "+2.69%", "MA_60 偏离"),
    ("+4.22%", "+4.05%", "MA_120 偏离"),
    ("+3.30%", "+3.20%", "MA_250 偏离"),
    # ── 5. 错值 ──
    ("−1.86%", "−1.89%", "止损距入场"),
    ("一个未收盘的", "一个短周期均线的失守", "语病"),
    # ── 6. 外部标的（简报 L226）──
    ("显著低于宽基（该项目此前对 512400.SS 测得 HV20 31.969%）；",
     "该量级显著低于权益类资产常见的年化波动区间（12% 属偏低水平）；", "外部标的"),
]

#: 「价格在全部均线上方」必须单独处理：需排除已被修好的新表述
FIX_ASSERT_OLD = "价格在全部均线上方"
FIX_ASSERT_NEW = "价格站在 MA_10 及以上全部均线上方"


def apply_globally(files: list[Path], old: str, new: str) -> int:
    """全局替换（不带 count），但对每个匹配位置做豁免判定。"""
    n = 0
    for f in files:
        t = f.read_text(encoding="utf-8")
        if old not in t:
            continue
        out, idx = [], 0
        for m in re.finditer(re.escape(old), t):
            seg = t[idx:m.start()]
            out.append(seg)
            # 豁免判定：若该处是「已修好的新表述」或「澄清语境」则原样保留
            kept = is_allowed(t, m.start(), old)
            if old == FIX_ASSERT_OLD:
                ctx = t[max(0, m.start() - 24): m.start()]
                if "MA_10 及以上" in ctx or "及以上" in ctx:
                    kept = True
            out.append(old if kept else new)
            idx = m.end()
            if not kept:
                n += 1
        out.append(t[idx:])
        f.write_text("".join(out), encoding="utf-8", newline="\n")
    return n


def main() -> int:
    files = sorted(p for p in D.rglob("*.md") if p.name not in DONT_TOUCH)
    print("=" * 96)
    print(f"{'【替换模式】' if APPLY else '【仅扫描】'} 全量旧值核对（v3 锚定片段豁免 + 全局替换）")
    print("=" * 96)

    # 先扫描（含片段级豁免判定）
    total = 0
    for old, new, tag in RULES:
        hits = []
        for f in files:
            t = f.read_text(encoding="utf-8")
            for m in re.finditer(re.escape(old), t):
                if is_allowed(t, m.start(), old):
                    continue
                ln = t[:m.start()].count("\n") + 1
                hits.append((f.name, ln))
        if old == FIX_ASSERT_OLD:
            hits = []
            for f in files:
                t = f.read_text(encoding="utf-8")
                for m in re.finditer(re.escape(old), t):
                    ctx = t[max(0, m.start() - 24): m.start()]
                    if "及以上" in ctx:
                        continue
                    ln = t[:m.start()].count("\n") + 1
                    hits.append((f.name, ln))
        if hits:
            total += len(hits)
            print(f"  ▸ [{tag}] 「{old}」× {len(hits)} → 「{new}」")
            for name, ln in hits[:5]:
                print(f"      {name} L{ln}")

    print(f"\n合计待处理：{total} 处")

    if APPLY:
        print("\n执行全局替换…")
        done = 0
        for old, new, tag in RULES:
            done += apply_globally(files, old, new)
        print(f"已替换 {done} 处")

        print("\n复查残留（片段级豁免判据）…")
        left = 0
        for old, new, tag in RULES:
            for f in files:
                t = f.read_text(encoding="utf-8")
                for m in re.finditer(re.escape(old), t):
                    if is_allowed(t, m.start(), old):
                        continue
                    if old == FIX_ASSERT_OLD:
                        ctx = t[max(0, m.start() - 24): m.start()]
                        if "及以上" in ctx:
                            continue
                    ln = t[:m.start()].count("\n") + 1
                    print(f"   ✗ [{tag}] {f.name} L{ln}: {old}")
                    left += 1
        print(f"残留：{left} 处 {'✓ 已清零' if left == 0 else '✗'}")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
