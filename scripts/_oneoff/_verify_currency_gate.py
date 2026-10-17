# lifecycle: oneoff
# created: 2026-10-15
"""双向夹具：验证 _fundamentals_sanity 的币种不一致检测（铁律 20：改检测器必须双边自测）。

正例：currency=USD / financialCurrency=KRW（SKHY 实况）⇒ 必须命中币种告警。
反例：currency=USD / financialCurrency=USD（美股本土）⇒ 必须**不**命中币种告警。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wb_analysis.collect import _fundamentals_sanity  # noqa: E402

# --- 正例：SKHY 实况（币种不一致） ---
POS = """# Company Fundamentals for SKHY
# Data retrieved on: 2026-10-15 16:39:28

Name: SK hynix Inc.
Sector: Technology
Industry: Semiconductors
Currency: USD
Financial Currency: KRW
Market Cap: 1049191907328
PE Ratio (TTM): 10.016973
Forward PE: 4.2797914
PEG Ratio: 0.23
Price to Book: 5.3602414
EPS (TTM): 14.73
Forward EPS: 34.47598
Beta: 2.391
Revenue (TTM): 189170609815552
Net Income: 161965397770240
Profit Margin: 0.85619
Operating Margin: 0.76328003
Return on Equity: 0.92679
Debt to Equity: 8.037
"""

# --- 反例：美股本土（币种一致） ---
NEG = """# Company Fundamentals for GOOG
# Data retrieved on: 2026-10-15 16:39:28

Name: Alphabet Inc.
Sector: Communication Services
Industry: Internet Content & Information
Currency: USD
Financial Currency: USD
Market Cap: 2500000000000
PE Ratio (TTM): 26.5
Forward PE: 22.1
Price to Book: 7.2
EPS (TTM): 9.5
Forward EPS: 11.4
Revenue (TTM): 380000000000
Net Income: 100000000000
Profit Margin: 0.263
Operating Margin: 0.32
Return on Equity: 0.30
Debt to Equity: 12.0
"""

KEY = "币种不一致"

pos_out = _fundamentals_sanity(POS)
neg_out = _fundamentals_sanity(NEG)

pos_hit = KEY in pos_out
neg_hit = KEY in neg_out

print("=" * 70)
print(f"正例（USD/KRW）命中币种告警: {pos_hit}   -> 期望 True")
print(f"反例（USD/USD）命中币种告警: {neg_hit}   -> 期望 False")
print("=" * 70)
if pos_hit:
    print("[正例输出节选]")
    for ln in pos_out.splitlines():
        if "币种" in ln or "不可用" in ln or "仍可用" in ln:
            print("   " + ln.strip()[:110])

ok = pos_hit and not neg_hit
print()
print("双边夹具结果:", "✓ 通过" if ok else "✗ 失败")
raise SystemExit(0 if ok else 1)
