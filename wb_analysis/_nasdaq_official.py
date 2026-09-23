# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_nasdaq_official.py
"""拉 Nasdaq 官方 API 的日线并打印，用于人工对照 NDX 证据包 §1。

用法:
  ./.venv/Scripts/python.exe wb_analysis/_nasdaq_official.py NDX indexes 2026-08-15 2026-09-25
  ./.venv/Scripts/python.exe wb_analysis/_nasdaq_official.py QQQ etf 2026-08-15 2026-09-25
"""
import json
import sys
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


def main() -> int:
    symbol = sys.argv[1]
    assetclass = sys.argv[2] if len(sys.argv) > 2 else "stocks"
    frm = sys.argv[3] if len(sys.argv) > 3 else "2026-08-15"
    to = sys.argv[4] if len(sys.argv) > 4 else "2026-09-25"

    url = (
        f"https://api.nasdaq.com/api/quote/{symbol}/historical"
        f"?assetclass={assetclass}&fromdate={frm}&limit=40&todate={to}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[nasdaq] {symbol}/{assetclass} 拉取失败: {exc!r}")
        return 1

    dt = (data.get("data") or {})
    status = (data.get("status") or {}).get("rCode")
    rows = (dt.get("tradesTable") or {}).get("rows") or []
    print(f"[nasdaq] {symbol} assetclass={assetclass} status={status} rows={len(rows)}")
    if not rows:
        print("         （无数据；该 symbol 可能不在 Nasdaq 官方历史接口覆盖内）")
        return 0
    for r in rows[:14]:
        print(
            f"  {r['date']}  close={r['close']:>12}  open={r['open']:>12}  "
            f"high={r['high']:>12}  low={r['low']:>12}  vol={r['volume']:>16}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
