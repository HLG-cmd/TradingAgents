# -*- coding: utf-8 -*-
# lifecycle: oneoff
"""探查 AVGO 的 forwardPE/forwardEps 是否可信（铁律 26：字段间关系校验）。"""
import yfinance as yf

t = yf.Ticker("AVGO")
info = t.info
px = info.get("regularMarketPrice") or info.get("currentPrice")
print(f"现价                         {px}")
print(f"trailingPE                   {info.get('trailingPE')}")
print(f"trailingEps                  {info.get('trailingEps')}")
print(f"forwardPE                    {info.get('forwardPE')}")
print(f"forwardEps                   {info.get('forwardEps')}")
print(f"marketCap                    {info.get('marketCap'):,}")
print()
print("--- 交叉校验 ---")
tpe, teps = info.get("trailingPE"), info.get("trailingEps")
fpe, feps = info.get("forwardPE"), info.get("forwardEps")
if px and tpe:
    print(f"现价/trailingPE = 反推 EPS     {px / tpe:.4f}  (应≈ trailingEps {teps})")
if px and fpe:
    print(f"现价/forwardPE  = 反推 EPS     {px / fpe:.4f}  (应≈ forwardEps {feps})")
if teps and feps:
    print(f"forward/trailing EPS 倍数      {feps / teps:.3f}x   ← 若 >1.5 需警惕")
ni_ttm = info.get("netIncomeToCommon")
print(f"netIncomeToCommon(TTM)        {ni_ttm:,}" if ni_ttm else "netIncomeToCommon             None")
if ni_ttm and feps:
    sh = info.get("sharesOutstanding")
    print(f"按 forwardEps 反推净利         {feps * sh / 1e9:.2f}B  (TTM 净利 {ni_ttm / 1e9:.2f}B)")
print()
print("--- 分析师预期（若有）---")
for attr in ("earnings_estimate", "eps_trend", "eps_revisions", "growth_estimates"):
    try:
        v = getattr(t, attr)
        if v is not None and len(v) > 0:
            print(f"[{attr}]")
            print(v.to_string()[:1200])
            print()
    except Exception as e:  # noqa: BLE001
        print(f"[{attr}] 不可得: {type(e).__name__}")
