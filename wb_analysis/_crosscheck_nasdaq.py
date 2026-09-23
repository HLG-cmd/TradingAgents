# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_crosscheck_nasdaq.py <标的> [基准日]\n#   · 个股/ETF：官方接口直接逐条核对 OHLC\n#   · 指数（NDX/SPX）：官方接口不支持指数（rCode=400）⇒ 自动改用 QQQ/SPY 代理，只核对**日涨跌幅一致性**
"""用 Nasdaq 官方公开 API 独立复核证据包 §1 的日线 OHLC（数据来源真实性核验）。

用法: ./.venv/Scripts/python.exe wb_analysis/_crosscheck_nasdaq.py GOOG 2026-09-18
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


# ★ 2026-09-23 修：原先硬编码 `assetclass=stocks` ⇒ **指数标的复核恒返回 0 行**
#   （实测 NDX 报「官方 API 无此日（未发布或非交易日）」，看起来像"数据源有问题"，其实是品类传错）。
#   教训：**复核工具"返回 0 行"时，先怀疑自己的请求参数，再怀疑上游。**
_INDEX = {"NDX", "SPX", "COMP", "DJI", "IXIC", "RUT", "VIX", "VXN"}
_ETF = {"QQQ", "SPY", "IWM", "GLD", "SLV", "TLT", "IEF", "SHY", "VXX", "UVXY", "VIXY",
        "SMH", "SOXX", "XLK", "XLE", "XLF", "XLV"}


def assetclass_of(symbol: str) -> str:
    s = symbol.upper().lstrip("^")
    if s in _INDEX:
        return "indexes"
    if s in _ETF:
        return "etf"
    return "stocks"


# ★★ 2026-09-23 实测结论（**这是上游接口的硬限制，不是本工具的 bug**）：
#   Nasdaq 官方 `historical` 接口**只服务 stocks 与 etf**，**指数一律 rCode=400**：
#       NDX/indexes=400 · NDX/stocks=400 · COMP/indexes=400 · IXIC/indexes=400
#       QQQ/etf=200 ✓ · SPY/etf=200 ✓
#   ⇒ 指数（NDX/SPX…）**无法用官方接口直接核对点位**。
#   ⇒ 退而求其次的合规做法：用**同标的的 ETF 代理**（NDX↔QQQ、SPX↔SPY）核对**日涨跌幅的一致性**
#      （代理≠点位，两者差约 40 倍；只能比"变化的百分比"，且必须声明这是代理校验）。
PROXY = {"NDX": "QQQ", "SPX": "SPY", "NDX100": "QQQ", "SP500": "SPY"}


def fetch(symbol: str, frm: str, to: str, limit: int = 30):
    url = (
        f"https://api.nasdaq.com/api/quote/{symbol}/historical"
        f"?assetclass={assetclass_of(symbol)}&fromdate={frm}&limit={limit}&todate={to}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def num(s: str) -> float:
    """Nasdaq 返回 '$344.41' / '34,108,870' 这类带符号字符串。"""
    return float((s or "0").replace("$", "").replace(",", "").strip() or 0)


def main() -> int:
    symbol = sys.argv[1]
    last = sys.argv[2]
    # 覆盖证据包 §1 的最近 20 根 K 线区间
    # ★ 指数走 ETF 代理（官方接口不服务指数）
    proxy = PROXY.get(symbol.upper().lstrip("^"))
    fetch_sym = proxy or symbol
    if proxy:
        print(f"[代理] {symbol} 官方接口不支持指数（rCode=400）⇒ 改用 {proxy} 做**日涨跌幅一致性**校验")
        print(f"       ⚠️ {proxy} ≠ {symbol} 点位（差约 40 倍），本校验**只能证明方向与幅度的相对一致**，不能证明点位")
    data = fetch(fetch_sym, "2026-08-15", "2026-09-25")
    rows = (data.get("data") or {}).get("tradesTable", {}).get("rows") or []
    print(f"[nasdaq] 官方 API 返回 {len(rows)} 行（{symbol}）")
    out = {}
    for r in rows:
        out[r["date"]] = r
    # 打印最近 10 行
    for r in rows[:10]:
        print(
            f"  {r['date']}  close={r['close']:>10}  open={r['open']:>10}  "
            f"high={r['high']:>10}  low={r['low']:>10}  vol={r['volume']:>14}"
        )

    # 与证据包 §1 对照
    ev = ROOT / "wb_analysis" / "evidence" / f"{symbol}_{last}.md"
    text = ev.read_text(encoding="utf-8")
    print(f"\n[nasdaq] 与 {ev.name} §1 逐行对照")
    prev_ev = prev_of = None
    ok_proxy = checked = 0
    max_dev = 0.0
    checked = 0
    for line in text.splitlines():
        if len(line) > 10 and line[:4] == "2026" and line[4] == "-":
            parts = line.split()
            if len(parts) != 6:
                continue
            d, o, h, lo, c, v = parts
            d_us = d[5:7] + "/" + d[8:10] + "/" + d[:4]
            ref = out.get(d_us)
            if not ref:
                print(f"  {d}: 官方 API 无此日（未发布或非交易日）")
                continue
            if proxy:
                # ★ 代理校验：**只比日涨跌幅**。代理点位与指数差约 40 倍，比绝对值毫无意义；
                #   但两者的日变化率应当高度一致（跟踪差通常 <0.3pp）。
                ev_c, of_c = float(c), num(ref["close"])
                if prev_ev is not None and prev_of:
                    ev_r = (ev_c / prev_ev - 1) * 100
                    of_r = (of_c / prev_of - 1) * 100
                    dev = abs(ev_r - of_r)
                    flag = "OK " if dev < 0.35 else "DIVERGE"
                    print(f"  {d}: {flag} 证据涨跌={ev_r:+.2f}%  {proxy}涨跌={of_r:+.2f}%  "
                          f"偏差={dev:.2f}pp")
                    ok_proxy += dev < 0.35
                    max_dev = max(max_dev, dev)
                    checked += 1
                prev_ev, prev_of = ev_c, of_c
                continue
            ok_c = abs(num(ref["close"]) - float(c)) < 0.005
            ok_v = (ref["volume"].replace(",", "").strip() == v)
            if num(ref["volume"]) != float(v):
                ok_v = abs(num(ref["volume"]) - float(v)) / max(float(v), 1) < 0.005
            flag = "OK " if (ok_c and ok_v) else "MISMATCH"
            print(f"  {d}: {flag} 证据close={c} 官方close={ref['close']} | 证据vol={v} 官方vol={ref['volume']}")
            checked += 1
    if proxy:
        print(f"\n[nasdaq] 代理校验完成：{ok_proxy}/{checked} 天日涨跌幅一致（偏差 <0.35pp），"
              f"最大偏差 {max_dev:.2f}pp")
        print(f"  ⇒ 结论：{symbol} 的**日涨跌幅序列**得到第三方独立佐证；"
              f"但**点位本身未获官方接口核验**（该接口不服务指数，rCode=400）")
    else:
        print(f"\n[nasdaq] 对照完成，共 {checked} 个交易日")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
