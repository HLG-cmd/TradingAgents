# lifecycle: maintenance
# created: 2026-09-23
# usage: ./.venv/Scripts/python.exe wb_analysis/_precheck.py
"""交付前统一门禁 —— 一条命令跑完全部校验，输出一张表。

为什么需要它（2026-09-19 复盘）：
  本项目的交付前校验分散在 6 个脚本里，各有各的参数、各不相同的退出码约定，
  实际使用时还要人工剔除归档目录的噪音。结果是：
    - **顺序靠记**（先溯源、再口径、最后反读），漏一步就漏一类缺陷；
    - **判读靠眼**（`_lint_drafts.py` 永远返回 0，`_check_freshness.py` 的 mtime 告警是已知假阳性）；
    - **噪音靠手工过滤**（归档目录会一次带进几十行）。
  于是「跑完检查」这件事本身成了不可复现的手工仪式。

  本脚本把这些**固定下来**：统一的调用方式、统一的分级（PASS / WARN / FAIL）、
  统一的判读规则（把「哪些是硬失败、哪些只作提示」写成代码而不是记在脑子里）。

用法：
    python wb_analysis/_precheck.py <draft_dir> [options]

    # 最常用（用草稿目录自带的证据引用）
    python wb_analysis/_precheck.py wb_analysis/drafts/NDX_2026-09-17 \\
        --evidence wb_analysis/evidence/NDX_2026-09-17.md

    # 交付后连报告树一起反读
    python wb_analysis/_precheck.py wb_analysis/drafts/NDX_2026-09-17 \\
        --evidence wb_analysis/evidence/NDX_2026-09-17.md \\
        --report reports/NDX_20260917_230302

    --strict-freshness   把 mtime 时序告警也当成 FAIL（默认只作提示）

━━━ 分级规则（写死在这里，不再靠人判断）━━━
  FAIL —— 阻断交付：
    · 评级词/契约字段不合规（`_verify_ratings.py`）
    · 口径不一致（`_audit_values.py`：旧值残留、分项求和不自洽）
    · 契约违规（`_lint_drafts.py` 的 ✗ 行：越界收尾行、裸评级词、缺结构化头部、截断）
    · 报告树反读失败（`_verify_report.py`）
  WARN —— 不阻断，但需人工过目：
    · 未溯源数字（派生量属正常；凭空出现的绝对金额/倍数才是编造信号）
  INFO —— 固定作提示（**不阻断**）：
    · mtime 时序告警。该检查只看文件时间，而**「简报加了纯增补注释」也会触发它**，
      属已知假阳性类型 ⇒ 判据应是**内容比对**（见 MEMORY 铁律 7），
      不是这一行的退出码。故默认降级为提示。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
PY = sys.executable


def run(cmd: list[str]) -> tuple[int, str]:
    """在**项目根**下运行子工具。

    为什么固定 cwd：子工具接受的是调用方给的路径；而它们内部可能还有别的相对路径
    （实测 `_check_freshness.py` 曾把 evidence 目录写成相对路径，导致换个目录调用
    就误报「证据包缺失」）。把 cwd 钉死在项目根，配合下面把入参一律 `resolve()` 成
    绝对路径，两件事合起来才能保证**从任何目录调用结果一致**。
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def crashed(out: str) -> bool:
    """判断子工具**自身**是否崩了（而不是检出了问题）。

    ★ 为什么这条很关键：若校验器崩溃后返回非零，「非零 = 有问题」的朴素判断会**碰巧**得出
      「FAIL」——方向对了但原因是错的；更危险的是崩溃后返回 0，就会被当成「通过」。
      两种情形都必须被显式识别，否则**坏掉的检测器会伪装成干净的检测器**。
    """
    return "Traceback (most recent call last)" in out


#: 口径自动对账字段（2026-10-19 新增）。
#: 只收「单位一致、可比」的字段：PE / PB / 52 周高低。
#: ⚠ 市值不纳入：证据包里同时存在「亿元」与「元」两种单位，自动比对会 100 倍误报。
_CALIBER_FIELDS: dict[str, tuple[str, ...]] = {
    "PE(TTM)": (r"PE Ratio \(TTM\)\s*[:：]?\s*([\d.]+)",
                r"\bpe_ratio[^\d\n]{0,6}([\d.]+)",
                r"PE\(TTM\)[^\d\n]{0,6}([\d.]+)"),
    "PB": (r"Price to Book\s*[:：]?\s*([\d.]+)",
           r"\bpb_ratio[^\d\n]{0,6}([\d.]+)",
           # ★ 2026-10-21 修（NFLX 10-20 轮实测假阳性）：`ROE×(市值/PB) = 14.9B` 里的
           #   14.9 是「净利 14.9 亿」，却被本条读成 PB 倍数，触发
           #   「同字段多值 9.48626/14.9」的假 WARN。判据补一条负向先行断言：
           #   紧跟 B/b（十亿单位）的数字不是倍数。⚠️ 断言必须同时排除 `[\d.]`
           #   与 `B`：只写 `(?![Bb])` 会被正则回溯绕过（`14.9B` 退成 `14` 再匹配）。
           r"\bPB\b[^\d\n]{0,6}([\d.]+)(?![\d.Bb])"),
    "52周高": (r"52 Week High\s*[:：]?\s*([\d.]+)",
               r"high_52w[^\d\n]{0,6}([\d.]+)",
               r"52 ?周高[^\d\n]{0,6}([\d.]+)"),
    "52周低": (r"52 Week Low\s*[:：]?\s*([\d.]+)",
               r"low_52w[^\d\n]{0,6}([\d.]+)",
               r"52 ?周低[^\d\n]{0,6}([\d.]+)"),
}


def caliber_conflicts(evidence: list[Path]) -> list[dict]:
    """同字段多值检测：同一字段在证据源中相差 >1% 即判「口径冲突」。

    返回 ``[{"field": "PE(TTM)", "values": ["14.01", "14.71"]}, ...]``。

    ★ 为什么需要它：`_value_blacklist.json` 全项目从未存在 ⇒ 原「口径一致性」检查
      恒跳过（死检查）。而实测每轮都有 3–5 处双口径（PE 14.71/14.01、PB 2.823/2.92、
      52 周 656.35/664），全靠人工在简报里声明 —— 漏一处就会让两个角色用两个分母。
    """
    seen: dict[str, list[float]] = {}
    for ev in evidence:
        try:
            t = ev.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for field, pats in _CALIBER_FIELDS.items():
            for p in pats:
                for m in re.finditer(p, t, re.I):
                    try:
                        v = float(m.group(1).replace(",", ""))
                    except ValueError:
                        continue
                    if v > 0:
                        seen.setdefault(field, []).append(v)
    out: list[dict] = []
    for field, vals in seen.items():
        lo, hi = min(vals), max(vals)
        if hi > 0 and (hi - lo) / hi > 0.01:
            out.append({"field": field, "values": [f"{lo:g}", f"{hi:g}"]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="交付前统一门禁")
    ap.add_argument("draft_dir")
    ap.add_argument("--evidence", nargs="*", default=[], help="证据源 md（可多个）")
    ap.add_argument("--blacklist", default=None, help="旧值黑名单 JSON（默认取草稿目录下的 _value_blacklist.json）")
    ap.add_argument("--report", default=None, help="报告树目录（给了就做反读校验）")
    ap.add_argument("--strict-freshness", action="store_true",
                    help="把 mtime 时序告警也当 FAIL（默认只作提示）")
    args = ap.parse_args()

    # ★ 入参一律 `resolve()` 成绝对路径：这样即使调用方给的是相对路径、
    #   而子工具被放在项目根下运行，两边的解析基准也一致。
    draft = Path(args.draft_dir).resolve()
    if not draft.is_dir():
        print(f"✗ 草稿目录不存在: {draft}", file=sys.stderr)
        return 1

    # ★ 前置自检：工具缺失必须**显式失败**。
    #   否则 `python 缺失的脚本.py` 只会往 stderr 打一行「can't open file」并返回 2，
    #   可能被误读成「检出了问题」—— 又是一种坏检测器伪装成好检测器。
    needed = [
        "_verify_ratings.py",
        "_audit_values.py",
        "_lint_drafts.py",
        "_check_freshness.py",
        "_verify_snapshot_consistency.py",
        "_verify_earnings_quality.py",
    ]
    if args.report:
        needed.append("_verify_report.py")
    missing = [t for t in needed if not (HERE / t).exists()]
    if missing:
        print(f"✗ 前置自检失败：缺少校验工具 {missing}（应位于 {HERE}）", file=sys.stderr)
        return 1

    blacklist = Path(args.blacklist).resolve() if args.blacklist else draft / "_value_blacklist.json"
    evidence = [Path(e).resolve() for e in args.evidence]

    results: list[tuple[str, str, str]] = []   # (检查项, 级别, 摘要)
    fails: list[str] = []

    def add(name: str, level: str, summary: str) -> None:
        results.append((name, level, summary))
        if level == "FAIL":
            fails.append(name)

    # ---- 0. 运行卫生（报告/证据/草稿是否又开始堆积）----
    #   ★ 2026-09-23 新增：只报 WARN，不阻断交付 —— 堆积是「该整理」的信号，不是「报告错」的信号。
    #   判据在 wb_analysis/_reports_index.py：孤儿证据/草稿、缺草稿的报告树、顶层散落文件、修复前快照。
    rc, out = run([PY, str(HERE / "_reports_index.py"), "--check"])
    if crashed(out):
        add("运行卫生", "WARN", "检查器自身报错（见单独运行 _reports_index.py 的输出）")
    else:
        n = sum(1 for l in out.splitlines() if l.strip().startswith("- ["))
        if n == 0:
            add("运行卫生", "PASS", "无孤儿产物、无顶层散落、无缺草稿的报告树")
        else:
            add("运行卫生", "WARN", f"{n} 项待整理（见 _reports_index.py --check；不影响本次交付）")

    # ---- 0b. 数据缺口台账（决定性缺口必须在简报里声明）----
    #   ★ 2026-09-23 新增，**FAIL 级**。理由：缺数据本身不可怕，可怕的是**缺口没被下游看见**——
    #   角色会以为「证据包里没有这一项」等于「这一项无事发生」，于是凭空补出一个方向性结论。
    #   判据（客观、可复算）：证据包通道健康度 → 缺口台账（wb_analysis/_gap_ledger.py）→
    #   凡 `decisive=True` 的缺口，其关键词必须出现在 `0_brief.md` 里。
    m = re.match(r"^(.+?)_(\d{4}-\d{2}-\d{2})$", draft.name)
    tk, dt_ = (m.group(1), m.group(2)) if m else ("", "")
    if not m:
        add("数据缺口台账", "WARN", f"草稿目录名不形如 <标的>_<日期>（{draft.name}），跳过")
    else:
        if not (HERE / "_gap_ledger.py").exists():
            add("数据缺口台账", "WARN", "缺少 _gap_ledger.py，跳过")
        else:
            rc, out = run([PY, str(HERE / "_gap_ledger.py"), tk, dt_, "--check", str(draft), "--no-write"])
            if crashed(out):
                add("数据缺口台账", "FAIL", "台账工具自身报错")
            elif rc == 1:
                miss = [l.strip() for l in out.splitlines() if l.strip().startswith("✗ 未声明")]
                add("数据缺口台账", "FAIL", f"决定性缺口未在简报中声明 {len(miss)} 条：" +
                    "；".join(x.replace("✗ 未声明：", "")[:50] for x in miss[:3]))
            elif rc == 0:
                n = next((l for l in out.splitlines() if "决定性缺口" in l and "条" in l), "")
                add("数据缺口台账", "PASS", n.strip().replace("[门禁] ", "") or "决定性缺口均已声明")
            else:
                add("数据缺口台账", "WARN", f"非预期退出码 {rc}")

    # ---- 0c. 小节正文审计（「通道全绿但正文为空」= 静默失败特征）----
    # 2026-09-27 立：此前三次「全绿但正文为空」（GOOG ×2、AVGO）全靠人眼发现，
    # 判据其实完全可自动化。「全绿 + 空小节」必须逐条归因后才能交付。
    _ev = next((p for p in evidence if p.name.endswith(".md") and "supplement" not in p.name), None)
    if _ev is not None:
        try:
            import importlib.util as _ilu

            _spec = _ilu.spec_from_file_location(
                "_audit_empty_sections", HERE / "_audit_empty_sections.py")
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _text = _ev.read_text(encoding="utf-8")
            _secs = _mod.split_sections(_text)
            _empt: list[str] = []
            for _i, (_t, _b) in enumerate(_secs):
                if _mod.body_len(_b) != 0:
                    continue
                _nxt = _secs[_i + 1] if _i + 1 < len(_secs) else None
                if _nxt:
                    # ★ 2026-10-19 修：原豁免只认「非数字开头」的子标题，于是
                    #   `## 4. 三大财务报表` + `## 4.1 利润表` 会被判「父节正文为空」
                    #   （601899.SS 实测误报，报表内容全在 4.1/4.2/4.3 的围栏里）。
                    #   改为按编号前缀认父子：4.1 是 4 的子节。
                    _pn = re.match(r"^(\d+(?:\.\d+)*)", _t.strip())
                    _cn = re.match(r"^(\d+(?:\.\d+)*)", _nxt[0].strip())
                    _is_child = bool(_pn and _cn and _cn.group(1).startswith(_pn.group(1) + "."))
                    _non_digit_child = not _nxt[0][:1].isdigit()
                    if (_is_child or _non_digit_child) and _mod.body_len(_nxt[1]) > 0:
                        continue  # 父标题：内容挂在子节/同级通道标题下
                _empt.append(_t)
            _health = _mod.channels_health(_text)
            if not _empt:
                add("小节正文审计", "PASS", f"{len(_secs)} 个小节均有正文")
            else:
                _tail = "；".join(_empt[:3]) + ("…" if len(_empt) > 3 else "")
                if _health and _health[0] == _health[1]:
                    add("小节正文审计", "WARN",
                        f"通道 {_health[0]}/{_health[1]} **全绿**，但 {len(_empt)} 个小节正文为空"
                        f"（{_tail}）⇒ 须逐条归因（上游确缺 / **取错通道** / 判据误判），"
                        f"不得直接当作「上游缺口」交付")
                else:
                    add("小节正文审计", "WARN", f"{len(_empt)} 个小节正文为空：{_tail}")
        except Exception as e:  # noqa: BLE001
            add("小节正文审计", "WARN", f"审计器不可用：{type(e).__name__}")
    else:
        add("小节正文审计", "WARN", "未提供 --evidence，跳过")

    # ---- 0d. 快照内部自洽性检测（抓 Forward EPS 异常翻倍）----
    # 2026-10-10 接入：严防 Forward PE / Forward EPS 与 TTM 矛盾却未声明。
    if tk and dt_:
        snap_cmd = [PY, str(HERE / "_verify_snapshot_consistency.py"), tk, dt_,
                    "--draft-dir", str(draft)]
        if _ev:
            snap_cmd += ["--evidence", str(_ev)]
        rc, out = run(snap_cmd)
        if crashed(out):
            add("快照自洽性", "FAIL", "自洽性检测器自身报错")
        elif rc == 0:
            add("快照自洽性", "PASS", "快照派生比率自洽（或异常项已在简报中归因）")
        else:
            add("快照自洽性", "WARN", "快照存在可疑前瞻派生（未在简报中声明），需人工核验")
    else:
        add("快照自洽性", "WARN", "草稿目录未包含标的代码与日期，跳过")

    # ---- 0e. 收益质量硬闸门（Q3 负税 / Q4 正常化偏差 / Q5 非经营重估浮盈）----
    # 2026-10-10 接入：彻底杜绝「低 PE 陷阱」（GOOG 浮盈占 61%、WDC 分立利得 69%、DUOL 负税）。
    # 判据：若命中 FAIL，检查简报中是否已改用经营性口径/扣非/剥离非经常性利得。
    is_etf_or_index = any(x in tk.upper() for x in ("SPX", "NDX", "HSTECH", "512", "515", "159", "^"))
    if tk and not is_etf_or_index:
        rc, out = run([PY, str(HERE / "_verify_earnings_quality.py"), "--tickers", tk, "--exit-on-fail"])
        if crashed(out):
            add("收益质量硬闸门", "FAIL", "收益质量验证器自身报错")
        elif rc == 0:
            add("收益质量硬闸门", "PASS", "报表净利无负税/正常化偏差/非经营性重估扭曲")
        else:
            # 命中 FAIL：检查 0_brief.md 是否已穿透声明并改用经营性口径
            brief_p = draft / "0_brief.md"
            declared_eq = False
            if brief_p.exists():
                b_text = brief_p.read_text(encoding="utf-8")
                keywords = ("经营性", "扣非", "剥离", "公允价值", "非经营", "非常规", "一次性", "正常化PE")
                if any(kw in b_text for kw in keywords):
                    declared_eq = True
            if declared_eq:
                add("收益质量硬闸门", "PASS", "报表净利虽含非经常项，但简报已穿透并改用经营性/扣非口径")
            else:
                fail_lines = [l.strip() for l in out.splitlines() if "FAIL:" in l]
                summary_err = fail_lines[0] if fail_lines else "报表净利失真"
                add("收益质量硬闸门", "FAIL", f"命中硬闸门未在简报穿透声明：{summary_err[:60]}")
    elif tk:
        add("收益质量硬闸门", "PASS", f"标的 {tk} 为指数/ETF，无单一个股财务收益质量闸门")

    # ---- 1. 评级词与契约字段 ----
    rc, out = run([PY, str(HERE / "_verify_ratings.py"), str(draft)])
    if crashed(out):
        add("评级词/契约字段", "FAIL", "校验器自身报错（见单独运行该脚本的输出）")
    elif rc == 0:
        add("评级词/契约字段", "PASS", "五个档位英文词与必需字段全部合规")
    else:
        bad = [l.strip() for l in out.splitlines() if l.strip().startswith("结论：✗")]
        add("评级词/契约字段", "FAIL", bad[0][:90] if bad else "存在不合规项")

    # ---- 2. 口径一致性（旧值残留 + 同字段多值冲突）----
    # ★ 2026-10-19：`_value_blacklist.json` 全项目不存在 ⇒ 原检查恒跳过（死检查）。
    #   改为「自动检测同字段多值」：PE / PB / 52 周高低，相差 >1% 即冲突；
    #   若 `0_brief.md` 同时出现这两个值，视为「已声明口径差」⇒ PASS。
    _blk_done = False
    if blacklist.exists():
        rc, out = run([PY, str(HERE / "_audit_values.py"), str(draft), "--stale", str(blacklist)])
        if crashed(out):
            add("口径一致性", "FAIL", "校验器自身报错")
        elif rc == 0:
            add("口径一致性", "PASS", "无旧值残留，分项求和自洽")
        else:
            n = sum(1 for l in out.splitlines() if l.strip().startswith("L") and "[" in l)
            add("口径一致性", "FAIL", f"存在旧值残留或不自洽（约 {n} 处命中）")
        _blk_done = True
    if not _blk_done:
        _conf = caliber_conflicts(evidence) if evidence else []
        if not _conf:
            add("口径一致性", "PASS", "未检出同字段多值冲突")
        else:
            _bp = draft / "0_brief.md"
            _bt = _bp.read_text(encoding="utf-8", errors="replace") if _bp.exists() else ""
            _undecl = [c for c in _conf if not all(v in _bt for v in c["values"])]
            if _undecl:
                add("口径一致性", "WARN", f"{len(_undecl)} 处同字段多值未在简报声明：" +
                    "；".join(f"{c['field']} {c['values'][0]}/{c['values'][1]}" for c in _undecl[:3]))
            else:
                add("口径一致性", "PASS", f"{len(_conf)} 处口径差均已在简报声明")

    # ---- 3. 数字溯源 + 契约违规（lint）----
    # 退出码语义：0 = 无契约违规；2 = 有契约违规（阻断）；非零其它 = 工具出错。
    if evidence:
        # ★ 2026-10-15：自动将传入证据包同目录的 `.derived.md` 与 `.supplement.md` 纳入合法来源，
        #   消除 `_precheck.py` 只传 `--evidence <T>_<date>.md` 时把机算派生值/补充快照值误报为未溯源数字的断层。
        expanded_ev = list(evidence)
        for ev_p in evidence:
            if ev_p.name.endswith(".md") and not ev_p.name.endswith((".derived.md", ".supplement.md")):
                stem = ev_p.name[:-3]
                for suf in (".derived.md", ".supplement.md"):
                    cand = ev_p.parent / f"{stem}{suf}"
                    if cand.exists() and cand not in expanded_ev:
                        expanded_ev.append(cand)
        rc, out = run([PY, str(HERE / "_lint_drafts.py"), str(draft)] + [str(e) for e in expanded_ev])
        viol = [l.strip() for l in out.splitlines() if l.strip().startswith("✗")]
        untraced = [l.strip() for l in out.splitlines() if "未溯源数字" in l]
        if crashed(out):
            add("数字溯源/契约", "FAIL", "校验器自身报错")
        elif rc == 2:
            add("数字溯源/契约", "FAIL", f"契约违规 {len(viol)} 处：" + "；".join(v[:60] for v in viol[:3]))
        elif rc != 0:
            add("数字溯源/契约", "FAIL", f"校验器以非预期退出码 {rc} 结束")
        elif untraced:
            add("数字溯源/契约", "WARN", f"契约无违规；{len(untraced)} 个文件含待人工判定的未溯源数字")
        else:
            add("数字溯源/契约", "PASS", "无契约违规，无待判定数字")
    else:
        add("数字溯源/契约", "WARN", "未提供 --evidence，跳过（该检查必须有证据源才有意义）")

    # ---- 4. 时序新鲜度（默认只作提示）----
    rc, out = run([PY, str(HERE / "_check_freshness.py"), str(draft)])
    line = next((l.strip() for l in out.splitlines() if l.strip().startswith(("✓", "✗"))), "")
    if crashed(out):
        add("时序新鲜度", "FAIL", "校验器自身报错")
    elif rc == 0:
        add("时序新鲜度", "PASS", line or "12 个角色均不早于简报")
    else:
        lvl = "FAIL" if args.strict_freshness else "INFO"
        add("时序新鲜度", lvl, (line or "有文件早于简报") + " ← 需用**内容比对**确认，见铁律 7")

    # ---- 5. 报告树反读（可选）----
    if args.report:
        rep = Path(args.report).resolve()
        if not rep.is_dir():
            add("报告树反读", "FAIL", f"报告树不存在: {rep}")
        else:
            rc, out = run([PY, str(HERE / "_verify_report.py"), str(rep)])
            if crashed(out):
                add("报告树反读", "FAIL", "校验器自身报错")
            else:
                add("报告树反读", "PASS" if rc == 0 else "FAIL",
                    "评级可被上游解析器识别，末行契约一致" if rc == 0
                    else "反读失败，见单独运行该脚本的输出")

    # ---- 汇总 ----
    icon = {"PASS": "✓", "WARN": "△", "INFO": "·", "FAIL": "✗"}
    print("=" * 78)
    print(f"交付前门禁：{draft}")
    print("=" * 78)
    for name, level, summary in results:
        print(f"  {icon[level]} [{level:<4}] {name:<16} {summary}")
    print("-" * 78)
    if fails:
        print(f"结论：✗ {len(fails)} 项 FAIL —— {'、'.join(fails)}")
        print("      ⇒ 修正后重跑本脚本，全绿再渲染。")
        return 1
    warns = [n for n, l, _ in results if l == "WARN"]
    print("结论：✓ 无阻断项" + (f"（{len(warns)} 项待人工过目：{'、'.join(warns)}）" if warns else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
