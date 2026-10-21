# lifecycle: reusable
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_verify_edgar_raw.py
"""直接从 SEC data.sec.gov 拉**完整** companyfacts（不走项目内的 slim 缓存），复核 FY2025 科目。

为什么需要它：`edgar_fundamentals.fetch_facts()` 返回的是 `slim_facts()` 精简后的结果，
只保留 `CONCEPT_CHAINS` 里的 tag —— **实测共 17 个**（16 个 `us-gaap` + 1 个 `dei`；
revenue 6 / net_income 4 / equity 2 / shares 3 / assets 1 / liabilities 1）。
（⚠️ 2026-10-10 更正：本行原写「`us-gaap` 只保留 8 个标签」并逐字列了那 8 个 —— 已过时，
真值由 `quant/edgar_fundamentals.py::_NEEDED_TAGS` 派生，**任何地方都不得手抄**。）
⇒ **营业利润、毛利率、EPS、经营现金流、资本开支、长期债务这几项无法用现有缓存核验**，
但它们恰恰是「财报基本面」的核心科目。故本脚本直连 SEC 官方接口取全量 facts。

用法: ./.venv/Scripts/python.exe wb_analysis/_verify_edgar_raw.py NFLX [2025-12-31]
"""
import json
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quant import edgar_fundamentals as ef

CACHE = Path.home() / ".tradingagents" / "edgar_raw"

# 复用判据：文件 mtime 距今 < TTL 才复用，否则重下并覆盖。**导出为常量**，
# 让「判据」与「清理」共用同一个数 —— 两处各写一遍必然漂移。
TTL_SECONDS = 86400


def _purge_expired(cache_dir: Path) -> int:
    """删掉**已过 TTL** 的 companyfacts —— 它们永远不会再被复用。

    为什么需要它：`get_facts` 过期即重下，但**只有被再次访问的那一只**才会被覆盖；
    其余过期文件会永久留在盘上（每个约 4 MB，实测 5 只占 20.3 MB）。
    这是「按日期累积」之外的另一种只增不减 —— 清理必须在写入路径上自动发生，
    否则又会退化成「攒多了再手工清」。
    """
    removed = 0
    for f in cache_dir.glob("*_companyfacts.json"):
        try:
            if time.time() - f.stat().st_mtime >= TTL_SECONDS:
                f.unlink()
                removed += 1
        except OSError:      # 被占用等 ⇒ 跳过，不阻断
            pass
    return removed

# (证据包 §4 标签, us-gaap tag 候选链, 目标期末日)
ITEMS = [
    ("Total Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"], "2025-12-31"),
    ("Cost Of Revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"], "2025-12-31"),
    ("Operating Income", ["OperatingIncomeLoss"], "2025-12-31"),
    ("Net Income", ["NetIncomeLoss"], "2025-12-31"),
    ("Pretax Income",
     ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
     "2025-12-31"),
    ("Diluted EPS", ["EarningsPerShareDiluted"], "2025-12-31"),
    ("Total Assets", ["Assets"], "2025-12-31"),
    ("Stockholders Equity", ["StockholdersEquity"], "2025-12-31"),
    ("Long Term Debt", ["LongTermDebtNoncurrent", "LongTermDebt"], "2025-12-31"),
    ("Total Debt", ["__DERIVED_LTD_PLUS_CURRENT__"], "2025-12-31"),
    ("Operating Cash Flow",
     ["NetCashProvidedByUsedInOperatingActivities",
      "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], "2025-12-31"),
    ("Capital Expenditure",
     ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
      "PaymentsToAcquireOtherPropertyPlantAndEquipment"], "2025-12-31"),
    ("Repurchase Of Capital Stock",
     ["PaymentsForRepurchaseOfCommonStock"], "2025-12-31"),
]


def get_facts(ticker: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    _purge_expired(CACHE)          # 先清已过 TTL 的，避免它们随访问次数只增不减
    p = CACHE / f"{ticker}_companyfacts.json"
    if p.exists() and (time.time() - p.stat().st_mtime) < TTL_SECONDS:
        return json.loads(p.read_text(encoding="utf-8"))
    cik = ef.cik_for(ticker)
    if not cik:
        raise SystemExit(f"取不到 {ticker} 的 CIK")
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
    print(f"[edgar-raw] 拉取 {url}")
    r = requests.get(url, headers={"User-Agent": ef.SEC_USER_AGENT}, timeout=60)
    r.raise_for_status()
    data = r.json()
    p.write_text(json.dumps(data), encoding="utf-8")
    print(f"[edgar-raw] 已缓存 {p.stat().st_size/1e6:.1f} MB -> {p}")
    return data


def annual_value(data: dict, tag: str, target_end: str, unit_pref=("USD", "USD/shares")):
    ns = (data.get("facts") or {}).get("us-gaap") or {}
    node = ns.get(tag)
    if not node:
        return None, None, None
    for unit, rows in (node.get("units") or {}).items():
        if unit not in unit_pref:
            continue
        cands = [r for r in rows
                 if r.get("end") == target_end
                 and r.get("form") in ("10-K",)
                 and r.get("fp") == "FY"
                 and r.get("start") is not None]
        if not cands:
            # EPS 等可能没有 start
            cands = [r for r in rows if r.get("end") == target_end and r.get("form") == "10-K"]
        if cands:
            cands.sort(key=lambda r: (r.get("filed", ""), -len(str(r.get("val")))))
            return cands[-1]["val"], unit, cands[-1].get("filed")
    return None, None, None


def resolve_as_of(ticker: str, explicit: str | None) -> str:
    """选一份证据包。**绝不回退到写死的日期。**

    优先级：① 显式指定（命令行第 3 个位置参数 / ``--date``）；
            ② ``evidence/`` 下该标的的**最新**一份 ``<T>_<YYYY-MM-DD>.md``；
            ③ 报告后退出（非 0）。

    为什么不能有写死的默认值（2026-10-09 事故）
    ----------------------------------------
    原实现 ``as_of = sys.argv[3] if ... else "2026-09-28"``。
    它有两种失效模式，都比「崩溃」更危险：

    1. **FileNotFoundError 堆栈**（本轮触发）：用户跑了新日期的证据包却忘了传第 3 参数。
    2. **更隐蔽：张冠李戴。** 若那一份旧证据包恰好还在盘上（本项目 ``evidence/``
       属瞬态目录、不保证已清理），工具会**拿 A 轮的证据包去核 B 轮的 SEC 数据**，
       输出一列「✓ 一致」而实际上比的是两个不同时点 —— 这正是铁律 7/31 那类
       「看着在工作、结论不可信」的失效。

    ⇒ 正确行为是**自动发现本轮产物**；找不到就明确报错，而不是拿一个必然过期的常量兜底。
    """
    if explicit:
        return explicit

    ev_dir = ROOT / "wb_analysis" / "evidence"
    pat = re.compile(rf"^{re.escape(ticker)}_(\d{{4}}-\d{{2}}-\d{{2}})\.md$")
    cands = [(m.group(1), p) for p in ev_dir.glob(f"{ticker}_*.md") if (m := pat.match(p.name))]
    if not cands:
        raise SystemExit(
            f"[edgar-raw] 证据包缺失：未在 {ev_dir} 找到 {ticker}_<YYYY-MM-DD>.md\n"
            f"            请先跑 wb_analysis/collect.py {ticker} --date <基准日>，"
            f"或显式传入第 3 个位置参数指定基准日。"
        )
    cands.sort()          # 日期字符串按字典序 == 按时间序
    return cands[-1][0]


def parse_evidence(ticker: str, as_of: str) -> dict:
    ev = ROOT / "wb_analysis" / "evidence" / f"{ticker}_{as_of}.md"
    if not ev.exists():
        raise SystemExit(f"[edgar-raw] 证据包不存在：{ev}（可用基准日见 evidence/ 目录）")
    text = ev.read_text(encoding="utf-8")
    out = {}
    for line in text.split("\n"):
        if "," not in line or line.startswith("#") or line.startswith("`"):
            continue
        parts = line.split(",")
        label = parts[0].strip()
        if not label or " " not in label:
            continue
        try:
            out.setdefault(label, float(parts[1]))
        except (ValueError, IndexError):
            continue
    return out


def taxonomy_inventory(data: dict) -> dict[str, int]:
    """列出 companyfacts 里**实际存在**的税种（taxonomy）及其概念数。

    ★ 2026-10-11（O5）。为什么必须看税种键：旧版把下面两种情况打印成**同一种**
    「SEC 无该标签」，而它们处置方式完全相反（铁律 30）：

      · **某标签不存在**：`us-gaap` 在、只是这个 tag 没申报 ⇒ 正常，换候选链即可。
      · **结构性缺失**：整个 `us-gaap` / `ifrs-full` 都不存在（实测 SKHY 的
        CIK 0002120882 只有 `ffd` 税种，5 个概念，全是**申报费披露**）
        ⇒ 外国私人发行人无 US-GAAP XBRL，**全部财务科目都无法独立核验**。
    """
    return {k: len(v or {}) for k, v in (data.get("facts") or {}).items()}


def missing_tag_verdict(fetch_err: str | None, tax: dict, has_fin: bool) -> str:
    """`SEC 侧取不到值`时的措辞 —— **三种成因必须三套说法**（铁律 30）。

    抽成纯函数是为了**可双侧验证**：三种分支各自可被夹具直接命中，
    不依赖真去拉一次 SEC（也就不会把「没网」测成「结构性缺失」）。
    """
    if fetch_err or not tax:
        return "未核验（采集失败）"
    if has_fin:
        return "SEC 无该标签"
    return "结构性缺失（发行人无 us-gaap XBRL）"


def write_sidecar(ticker: str, as_of: str, target: str, status: str,
                  tax: dict, ok: int, diff: int, na: int, detail: str) -> Path | None:
    """把核验结论写成 `evidence/<T>_<as_of>.edgar.json`，供 `_gap_ledger.py` 消费。

    ★ 2026-10-11（O4）。为什么需要副档：`edgar_raw` **不是采集通道**，
    既不出现在证据包的「通道健康度」里，也不在快照自洽检测的覆盖内
    ⇒ 光在 `_gap_ledger.RULES` 登记规则是**够不着的**，缺口永远进不了台账。
    副档是二者之间唯一的桥。命名沿用 `<T>_<as_of>.*` 前缀 ⇒ `_seal_run.py`
    的 `glob(f"{ticker}_{date}*")` 会自动把它一并封存，无需另改封存逻辑。
    """
    ev = ROOT / "wb_analysis" / "evidence"
    if not ev.exists():
        return None
    out = ev / f"{ticker}_{as_of}.edgar.json"
    out.write_text(json.dumps({
        "ticker": ticker, "as_of": as_of, "target_end": target,
        "status": status, "taxonomies": tax,
        "checked": len(ITEMS), "ok": ok, "diff": diff, "missing_tag": na,
        "detail": detail,
    }, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"[edgar-raw] 状态副档 -> {out.relative_to(ROOT).as_posix()}（status={status}）")
    return out


def resolve_target_end(data: dict, as_of: str, explicit: str | None) -> str:
    """自动探测与基准日最匹配的最新 10-K 期末日（FY）。

    ★ 2026-10-15 新增：此前默认硬编码为 "2025-12-31"，导致
      WDC（7 月初）、NVDA（1 月底）、ORCL（5 月底）、MU（8 月底）等非自然年财年公司在默认调用下
      直接报 0/13 假缺失。现自动从 `us-gaap` 核心科目里提取 `filed <= as_of` 的最新 `10-K` `end`。
    """
    if explicit and explicit.lower() != "auto":
        return explicit
    ns = (data.get("facts") or {}).get("us-gaap") or {}
    ends: set[str] = set()
    for probe_tag in ("Assets", "NetIncomeLoss", "Revenues",
                      "RevenueFromContractWithCustomerExcludingAssessedTax", "StockholdersEquity"):
        node = ns.get(probe_tag) or {}
        for rows in (node.get("units") or {}).values():
            for r in rows:
                if r.get("form") == "10-K" and r.get("end"):
                    filed = str(r.get("filed") or "")
                    if not as_of or not filed or filed <= as_of:
                        ends.add(str(r["end"]))
    if ends:
        return sorted(ends)[-1]
    return "2025-12-31"


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NFLX"
    explicit_target = sys.argv[2] if len(sys.argv) > 2 else None
    explicit = sys.argv[3] if len(sys.argv) > 3 else None
    as_of = resolve_as_of(ticker, explicit)
    print(f"[edgar-raw] 基准日 = {as_of}（{'显式指定' if explicit else '自动选取最新证据包'}）")

    # ★ 采集失败必须与「结构性缺失」分开：旧版 `get_facts` 抛异常会直接崩，
    #   而崩掉和「SEC 没有这个标签」在操作上完全不是一回事。
    fetch_err = None
    data: dict = {}
    try:
        data = get_facts(ticker)
    except BaseException as exc:  # noqa: BLE001 — 含 SystemExit（取不到 CIK）
        fetch_err = f"{type(exc).__name__}: {exc}"

    target = resolve_target_end(data, as_of, explicit_target)
    tax = taxonomy_inventory(data)
    has_fin = any(k in ("us-gaap", "ifrs-full") and n > 0 for k, n in tax.items())
    ev = parse_evidence(ticker, as_of)

    print("=" * 104)
    print(f"SEC data.sec.gov 全量 companyfacts 复核（{ticker}，目标期末 {target}"
          f"{' [自动识别]' if not explicit_target else ''}，仅 10-K / FY）")
    print("=" * 104)
    if fetch_err:
        print(f"⛔ **采集失败**：{fetch_err}")
        print("   ⇒ 本次**未做任何核验**。这与「SEC 无该标签」是两回事，不得混同（铁律 30）。")
    elif not tax:
        print("⛔ **采集失败**：companyfacts 为空（CIK 无申报，或下载被截断）。")
    elif not has_fin:
        print(f"⛔ **结构性缺失**：该发行人 companyfacts 只含 {list(tax)} 税种"
              f"（{sum(tax.values())} 个概念），**没有 us-gaap / ifrs-full**。")
        print("   ⇒ 这不是「某个标签没申报」，而是**整个 US-GAAP 事实集不存在**"
              "（外国私人发行人常见）⇒ **全部财务科目无法独立核验**，一律按单一来源处理。")
    else:
        print(f"✓ 税种清单：{tax}")

    ok = diff = na = diff_derived = 0
    for ev_label, tags, end in ITEMS:
        end_date = target if target else end
        # ★ 2026-10-12：标记「派生量」条目。XBRL 里**没有单一 `Total Debt` 标签**，
        #   只能由「长期债务（非流动）+ 流动部分」自算（见下面的分支）。
        #   两侧定义天然不同（供应商的 Total Debt 通常还含融资租赁、短期借款等）
        #   ⇒ 该项的差值属**口径差异，不是数据错误**，必须与真「不一致」分开计，
        #   否则每一家都会被判成 mismatch 并产生一条**假的决定性缺口**。
        derived = "__DERIVED_LTD_PLUS_CURRENT__" in tags
        a = ev.get(ev_label)
        b = unit = filed = None
        used = None
        for t in tags:
            if t == "__DERIVED_LTD_PLUS_CURRENT__":
                # 「总债务」在 XBRL 里没有单一标签 ⇒ 用「长期债务（非流动）」+「长期债务（流动部分）」自算
                ltd, _, f1 = annual_value(data, "LongTermDebtNoncurrent", end_date)
                cur, _, f2 = annual_value(data, "LongTermDebtCurrent", end_date)
                if ltd is None:
                    ltd, _, f1 = annual_value(data, "LongTermDebt", end_date)
                if ltd is not None and cur is not None:
                    b, used, filed = ltd + cur, "LongTermDebtNoncurrent + LongTermDebtCurrent", f1 or f2
                continue
            b, unit, filed = annual_value(data, t, end_date)
            if b is not None:
                used = t
                break
        if a is None:
            verdict = "证据包无此科目"
        elif b is None:
            # ★ O5：区分「标签不存在」「整个税种不存在」「压根没采到」三种成因
            verdict = missing_tag_verdict(fetch_err, tax, has_fin)
            na += 1
        else:
            d = (a - b) / b * 100 if b else float("nan")
            same_abs = abs(abs(a) - abs(b)) / abs(b) < 0.005 if b else False
            if abs(d) < 0.5:
                verdict = "✓ 一致"
                ok += 1
            elif same_abs:
                verdict = "✓ 一致（仅符号约定差异：SEC 报绝对流出额）"
                ok += 1
            elif derived:
                verdict = (f"△ 差 {d:+.2f}% —— **派生口径差异**（XBRL 无单一 Total Debt 标签，"
                           f"两侧定义不同，非数据错误）")
                diff_derived += 1
            else:
                verdict = f"✗ 差 {d:+.2f}%"
                diff += 1
        a_s = f"{a:,.2f}" if isinstance(a, (int, float)) else "—"
        b_s = f"{b:,.2f}" if isinstance(b, (int, float)) else "—"
        print(f"   {ev_label:24s} 证据包={a_s:>20s}  SEC={b_s:>20s}  "
              f"{(used or '—'):46s} {(filed or ''):12s} {verdict}")
    print(f"\n[汇总] 一致 {ok} / 不一致 {diff} / 派生口径差异 {diff_derived} / SEC 无标签 {na}")

    # —— 落状态副档（供 _gap_ledger 消费）——
    #   ⚠️ `diff` 只计**非派生**条目的真不一致；`diff_derived`（如 Total Debt）是口径差异，
    #      不升级为 mismatch —— 否则每家公司都会带一条假的决定性缺口。
    if fetch_err or not tax:
        status = "fetch_failed"
        detail = f"SEC companyfacts 采集失败：{fetch_err or '空响应'} ⇒ 本轮未做独立核验"
    elif not has_fin:
        status = "taxonomy_missing"
        detail = (f"companyfacts 只有 {sorted(tax)} 税种，无 us-gaap / ifrs-full "
                  f"⇒ 全部财务科目无法独立核验（结构性缺失，非网络问题）")
    elif diff:
        status = "mismatch"
        detail = f"{diff}/{len(ITEMS)} 项与 SEC 申报不一致 ⇒ 必须逐项复核后方可引用"
    elif na:
        status = "partial"
        detail = f"{ok}/{len(ITEMS)} 项一致；{na} 项 SEC 未申报对应标签"
    else:
        status = "verified"
        detail = f"全部 {len(ITEMS)} 项与 SEC 申报一致（目标期末 {target}）"
    if diff_derived and status == "verified":
        detail += (f"；另有 {diff_derived} 项为**派生口径差异**"
                   f"（XBRL 无单一标签，两侧定义不同，非数据错误）")
    write_sidecar(ticker, as_of, target, status, tax, ok, diff, na, detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
