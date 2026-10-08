# lifecycle: oneoff
# serves: GOOG 2026-09-29 —— Alphabet 三类股（A/B/C）股数双口径探针（铁律 23）
"""Alphabet 的 GOOG(Class C) / GOOGL(Class A) 在 yfinance 上会给出不同口径的股数。

铁律 23：impliedSharesOutstanding vs sharesOutstanding 可差 1.71 倍。
Alphabet 尤其危险：Class A+B+C 合计 vs 单类，市值会差出一整个数量级。
本探针把两个代码的所有股数字段并排列出，并用 close 反推交叉验证：
    implied  = marketCap / close
    shares   = 财报口径
两者不一致时必须说明采用哪个。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yfinance as yf  # noqa: E402

FIELDS = [
    "symbol", "longName", "currency", "exchange",
    "marketCap", "impliedSharesOutstanding", "sharesOutstanding",
    "floatShares", "regularMarketPrice", "previousClose",
    "trailingPE", "forwardPE", "priceToBook", "bookValue",
    "trailingEps", "forwardEps", "totalCash", "totalDebt",
    "enterpriseValue", "dividendYield", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
]


def main() -> int:
    out: dict[str, dict] = {}
    for t in ("GOOG", "GOOGL"):
        tk = yf.Ticker(t)
        info = {}
        try:
            info = tk.info or {}
        except Exception as e:  # pragma: no cover
            print(f"[WARN] {t} info failed: {e}")
        row = {k: info.get(k) for k in FIELDS}
        # 反推校验
        mc = info.get("marketCap")
        px = info.get("regularMarketPrice")
        imp = info.get("impliedSharesOutstanding")
        sh = info.get("sharesOutstanding")
        row["_check_implied_recomputed"] = (mc / px) if (mc and px) else None
        row["_check_ratio_sh_over_implied"] = (sh / imp) if (sh and imp) else None
        out[t] = row

    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))

    # 关键判据打印
    for t, r in out.items():
        mc, px, imp, sh = r["marketCap"], r["regularMarketPrice"], r["impliedSharesOutstanding"], r["sharesOutstanding"]
        if mc and px:
            print(f"\n[{t}] marketCap={mc/1e12:.4f}T  price={px}  => implied={mc/px/1e9:.4f}B")
        if imp:
            print(f"[{t}] impliedSharesOutstanding={imp/1e9:.4f}B")
        if sh:
            print(f"[{t}] sharesOutstanding         ={sh/1e9:.4f}B")
        if imp and sh:
            print(f"[{t}] ratio sharesOutstanding/implied = {sh/imp:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
