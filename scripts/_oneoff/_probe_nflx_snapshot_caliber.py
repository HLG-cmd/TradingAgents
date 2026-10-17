# lifecycle: oneoff
"""探针：核对 NFLX 估值快照字段口径 —— 季度利润表 / 现金流，定位 FCF 25.388B 与 Op Margin 33.381% 的来源。"""
import yfinance as yf
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)

t = yf.Ticker("NFLX")

print("=== quarterly income statement (yfinance) ===")
try:
    q = t.quarterly_income_stmt
    want = [w for w in ("Total Revenue", "Operating Income", "Net Income",
                        "Gross Profit", "Tax Provision", "Pretax Income",
                        "Net Non Operating Interest Income Expense", "EBITDA") if w in q.index]
    print(q.loc[want].to_string() if want else "(no rows)")
except Exception as e:
    print("FAIL", repr(e))

print("\n=== quarterly cashflow (yfinance) ===")
try:
    c = t.quarterly_cashflow
    want = [w for w in ("Operating Cash Flow", "Free Cash Flow", "Capital Expenditure",
                        "Repurchase Of Capital Stock") if w in c.index]
    print(c.loc[want].to_string() if want else "(no rows)")
except Exception as e:
    print("FAIL", repr(e))

print("\n=== info 关键字段 ===")
i = t.info
for k in ("marketCap", "trailingPE", "forwardPE", "trailingEps", "forwardEps",
          "priceToBook", "bookValue", "returnOnEquity", "operatingMargins",
          "profitMargins", "freeCashflow", "operatingCashflow", "totalRevenue",
          "netIncomeToCommon", "sharesOutstanding", "enterpriseValue",
          "ebitdaMargins", "grossMargins", "revenueGrowth", "earningsGrowth"):
    print(f"  {k:32s} = {i.get(k)}")
