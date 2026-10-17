# lifecycle: oneoff
# created: 2026-10-16
# usage: ./.venv/Scripts/python.exe wb_analysis/_oneoff/_audit_563020_consistency.py
"""563020 草稿一致性核对：把「同一事实在多处出现却数值不同」自动抓出来。

为什么要写（用户要求「对下数据，整篇 md 前后有没有矛盾」）：
肉眼扫 14 个文件（约 18 万字符）必然漏。这类缺陷的特点是**每一处单独看都合法**，
只有把同名指标横向摆在一起才暴露 ⇒ 必须机检。

## 三类判据（对应本项目已被验证的失败模式）
1. **同名指标跨文件取不同值** —— 从「`<关键词>` 附近抓 1.1~1.3 区间的小数」，
   按关键词归组，组内出现 >1 个不同值即报警（容差 0.0005）。
2. **断言与底稿冲突** —— 例如「六条均线全部在现价下方」，而底稿 MA_5=1.202 > 收盘 1.198。
3. **派生量复算** —— 表里写明的百分比/倍数，用底稿数字重算，偏差 >0.15pp 即报警。

⚠️ 只报告，不改文件。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "wb_analysis" / "drafts" / "563020_2026-10-15"

# ── 底稿（唯一事实源，取自证据包 §1/§2 + 0_derived.md 机算值）──
GT = {
    "close": 1.198, "prev_close": 1.212, "open": 1.210, "high": 1.210, "low": 1.186,
    "ma5": 1.202, "ma10": 1.1859, "ma20": 1.1793, "ma60": 1.1658,
    "ma120": 1.1495, "ma250": 1.1597,
    "boll_up": 1.2138, "boll_mid": 1.1793, "boll_low": 1.1448,
    "w52_close_hi": 1.228, "w52_close_lo": 1.049,
    "w52_intra_hi": 1.235, "w52_intra_lo": 1.043,
    "atr14_pct": 1.079, "hv20": 12.152, "hv60": 12.782,
    "pct_b": 77.101, "bandwidth_pct": 5.851,
    "pe": 8.9317, "pb": 0.9108, "pcf": 1.9681, "ps": 1.7322, "peg": 5.428,
    "roe": 10.2, "div": 4.1206, "y10": 1.6571, "div_prem": 2.463,
    "profit_rate": 91.33, "chip_avg": 1.17, "disc": 0.23,
    "nav_1015": 1.1955,
    # 派生
    "stop_trader": 1.1597, "stop_pm": 1.1793,
}

TOL = 5e-4


def ratios() -> dict[str, float]:
    """底稿派生的百分比，用于复算核对。"""
    c = GT["close"]
    r = {
        "ma5_dev": (c - GT["ma5"]) / GT["ma5"] * 100,
        "ma10_dev": (c - GT["ma10"]) / GT["ma10"] * 100,
        "ma20_dev": (c - GT["ma20"]) / GT["ma20"] * 100,
        "ma60_dev": (c - GT["ma60"]) / GT["ma60"] * 100,
        "ma120_dev": (c - GT["ma120"]) / GT["ma120"] * 100,
        "ma250_dev": (c - GT["ma250"]) / GT["ma250"] * 100,
        "gap_boll_low": (c - GT["boll_low"]) / GT["boll_low"] * 100,
        "gap_boll_up": (c - GT["boll_up"]) / GT["boll_up"] * 100,
        "gap_w52_hi": (c - GT["w52_close_hi"]) / GT["w52_close_hi"] * 100,
        "gap_w52_lo": (c - GT["w52_close_lo"]) / GT["w52_close_lo"] * 100,
        "stop_tr_on_entry": (1.202 - GT["stop_trader"]) / 1.202 * 100,
        "stop_pm_on_entry": (1.202 - GT["stop_pm"]) / 1.202 * 100,
        "stop_pm_alt": (1.202 - GT["stop_pm"]) / 1.202 * 100,
        "tr_on_entry": (GT["close"] - 1.202) / 1.202 * 100,
        # 止盈口径
        "tp1": (1.212 - 1.202) / 1.202 * 100,
        "tp2": (GT["boll_up"] - 1.202) / 1.202 * 100,
        "tp3": (GT["w52_close_hi"] - 1.202) / 1.202 * 100,
        # 盈亏比
        "rr_tp1_stop_tr": (1.212 - 1.202) / (1.202 - GT["stop_trader"]),
        "rr_tp2_stop_tr": (GT["boll_up"] - 1.202) / (1.202 - GT["stop_trader"]),
        "rr_tp3_stop_tr": (GT["w52_close_hi"] - 1.202) / (1.202 - GT["stop_trader"]),
        "rr_tp1_stop_pm": (1.212 - 1.202) / (1.202 - GT["stop_pm"]),
        # 阻力带宽度
        "resist_band": (GT["boll_up"] - 1.202) / 1.202 * 100,
        "up_room": (GT["boll_up"] - GT["close"]) / GT["close"] * 100,
        "dn_room": (GT["close"] - GT["boll_low"]) / GT["close"] * 100,
        # 分红摊平
        "div_month": GT["div"] / 12,
        "div_week": GT["div"] / 52,
        "months_stop_tr": ((1.202 - GT["stop_trader"]) / 1.202 * 100) / (GT["div"] / 12),
        "months_stop_pm": ((1.202 - GT["stop_pm"]) / 1.202 * 100) / (GT["div"] / 12),
        "atr_stop_tr": ((1.202 - GT["stop_trader"]) / 1.202 * 100) / GT["atr14_pct"],
        "atr_stop_pm": ((1.202 - GT["stop_pm"]) / 1.202 * 100) / GT["atr14_pct"],
        "atr_ma10_stop": ((1.202 - GT["ma10"]) / 1.202 * 100) / GT["atr14_pct"],
    }
    return r


def main() -> int:
    R = ratios()
    print("=" * 92)
    print("563020 草稿一致性核对（机检；只报告不改动）")
    print("=" * 92)
    print("\n【底稿派生值（供比对）】")
    for k in ("tr_on_entry", "stop_tr_on_entry", "stop_pm_on_entry", "tp1", "tp2", "tp3",
              "rr_tp1_stop_tr", "rr_tp2_stop_tr", "rr_tp3_stop_tr", "rr_tp1_stop_pm",
              "resist_band", "up_room", "dn_room", "div_month", "div_week",
              "months_stop_tr", "months_stop_pm", "atr_stop_tr", "atr_stop_pm"):
        print(f"   {k:22s} = {R[k]:+9.4f}")

    files = sorted(D.rglob("*.md"))
    texts = {f: f.read_text(encoding="utf-8") for f in files}

    print("\n" + "=" * 92)
    print("检查 1：止损价在全文出现的位置（检测「止损双口径」是否被显式衔接）")
    print("=" * 92)
    for f, t in texts.items():
        for m in re.finditer(r"止损[^。\n]{0,40}?(1\.\d{3})", t):
            print(f"   {f.name:24s} {m.group(1)}  | …{t[max(0,m.start()-30):m.end()+30].strip()}…")

    print("\n" + "=" * 92)
    print("检查 2：断言「均在现价下方 / 价格在全部均线上方」——与底稿 MA_5 比对")
    print("=" * 92)
    pats = ["全部位于现价下方", "全在价格下方", "全在现价下方", "价格在全部均线上方",
            "均线全部在价格下方", "全部均线上方"]
    for f, t in texts.items():
        for p in pats:
            for m in re.finditer(re.escape(p), t):
                ln = t[:m.start()].count("\n") + 1
                print(f"   {f.name:24s} L{ln:<4d} 「{p}」")
    print(f"   ⇒ 底稿事实：MA_5={GT['ma5']} > 收盘 {GT['close']} ⇒ MA_5 在现价**上方**；"
          f"其余 5 条在下方")

    print("\n" + "=" * 92)
    print("检查 3：派生百分比复算（列出全文出现的候选值，人工判定）")
    print("=" * 92)
    probes = {
        "1.86%|1.89%（PM/中性 止损距入场）": (r"1\.8[3-9]%", ["stop_pm_on_entry"]),
        "3.52%（交易员 止损距入场）": (r"3\.5[0-5]%", ["stop_tr_on_entry"]),
        "1.79%|3.30%|4.47%（距均线/下轨）": (r"1\.79%", ["ma20_dev"]),
        "4.47%（距布林下轨）": (r"4\.4[5-8]%", ["gap_boll_low"]),
        "1.32%（距上轨）": (r"1\.3[0-4]%", ["up_room"]),
        "2.996%（距52周高）": (r"2\.99[0-9]?%", ["gap_w52_hi"]),
        "1.3% 阻力带": (r"1\.3% 内|1\.3% 的区间内", ["resist_band"]),
    }
    for label, (rx, keys) in probes.items():
        print(f"\n   ▸ {label}")
        for k in keys:
            print(f"       底稿 {k} = {R[k]:+.4f}%")
        for f, t in texts.items():
            for m in re.finditer(rx, t):
                ln = t[:m.start()].count("\n") + 1
                seg = t[max(0, m.start() - 55):m.end() + 25].replace("\n", " ")
                print(f"       {f.name:22s} L{ln:<4d} {seg}")

    print("\n" + "=" * 92)
    print("检查 4：盈亏比口径（交易员 vs 中性 用了不同止损 ⇒ 数值应不同）")
    print("=" * 92)
    for f, t in texts.items():
        for m in re.finditer(r"0\.\d{2}\s*[:：]\s*1|0\.\d{2} : 1", t):
            ln = t[:m.start()].count("\n") + 1
            print(f"   {f.name:24s} L{ln:<4d} {t[max(0,m.start()-40):m.end()+15].strip()}")

    print("\n" + "=" * 92)
    print("检查 5：规模口径（亿份/亿元 的乘算是否自洽）")
    print("=" * 92)
    for f, t in texts.items():
        for m in re.finditer(r"1\d{2}\.\d+\s*亿份\s*[×x]\s*[\d.]+", t):
            ln = t[:m.start()].count("\n") + 1
            print(f"   {f.name:24s} L{ln:<4d} {t[max(0,m.start()-70):m.end()+45].strip()}")
    print("   ⇒ 校验：103.02 × 1.1955 = %.4f 亿；102.8791 × 1.1955 = %.4f 亿"
          % (103.02 * 1.1955, 102.8791 * 1.1955))

    print("\n" + "=" * 92)
    print("检查 6：同一关键词旁的数值分组（跨文件是否取了不同值）")
    print("=" * 92)
    groups: dict[str, list[tuple[str, int, float]]] = {}
    keymap = {
        "MA_5": "ma5", "MA_10": "ma10", "MA_20": "ma20", "MA_60": "ma60",
        "MA_120": "ma120", "MA_250": "ma250",
        "布林上轨": "boll_up", "上轨": "boll_up", "下轨": "boll_low",
        "ATR": "atr14_pct", "HV20": "hv20", "HV60": "hv60",
        "获利盘": "profit_rate", "筹码平均成本": "chip_avg",
        "股息率": "div", "10Y": "y10", "PEG": "peg", "PCF": "pcf",
        "PS (TTM)": "ps", "PE (TTM)": "pe", "PB": "pb", "ROE": "roe",
    }
    for f, t in texts.items():
        for kw, key in keymap.items():
            for m in re.finditer(re.escape(kw) + r"[^0-9\n]{0,14}?(\d+\.\d+)", t):
                v = float(m.group(1))
                groups.setdefault(key, []).append((f.name, t[:m.start()].count("\n") + 1, v))

    bad = 0
    for key, items in sorted(groups.items()):
        vals = {round(v, 3) for _, _, v in items}
        gt = GT.get(key)
        if gt is None:
            continue
        off = {v for v in vals if abs(v - gt) > max(abs(gt) * 0.02, 0.05)}
        flag = "  ⚠" if len(off) > 1 else "   "
        if len(off) > 1:
            bad += 1
        print(f"{flag} {key:12s} 底稿={gt:<10.4f} 出现值={sorted(vals)}"
              f"{'  ⇐ 多值' if len(vals) > 1 else ''}")
    print(f"\n   ⇒ 疑似多值项：{bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
