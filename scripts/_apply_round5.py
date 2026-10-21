#!/usr/bin/env python
# lifecycle: maintenance
"""第五轮：收尾全部遗留项。

  1. 修 _apply_round4.py 的行号漂移 bug —— 把 log_gap 导入的插入挪到编辑循环**之后**。
     （现在靠"预置导入"绕过：导入已存在就不插、行号不漂移。谁删了那行导入再跑它就重演。）
  2. 修 _apply_round2.py 的 CI 双补丁覆盖 bug —— cov1 改为基于 ci_text 计算。
     （此前两个补丁都基于同一份原文、先后写同一文件，lint 放宽被 coverage 覆盖掉。）
  3. A5 log_gap 消费端：_log.py 增 gap_entries()（记录 -> 台账条目 schema）。
  4. collect_a_stock.py 写台账时并入运行期降级 —— 采集器与台账脚本是不同进程，
     不落盘则下游 _gen_meta 的 notes / 记分卡永远读不到。
  5. 归档三个已用尽的一次性脚本到 scripts/_oneoff/ 并改标 oneoff。

默认干跑，逐条打印；确认后加 --apply。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R2 = ROOT / "scripts" / "_apply_round2.py"
R4 = ROOT / "scripts" / "_apply_round4.py"
LOG = ROOT / "wb_analysis" / "_log.py"
CAS = ROOT / "wb_analysis" / "collect_a_stock.py"
ONEOFF = ROOT / "scripts" / "_oneoff"

SERVES = "TradingAgents 治理一次性脚本 2026-10-22"
ARCHIVE = ["_fix_ci_lint.py", "_fix_r4.py", "_repair_r4.py"]

# ---- 1. _apply_round4.py 行号漂移 ----
R4_OLD = '''def apply_a1(path: Path, src: str, edits) -> str:
    nl = nl_of(src)
    lines = src.splitlines(keepends=True)
    if IMPORT_LINE not in src:
        anchor = None
        for i, ln in enumerate(lines):
            if ln.strip() == "from __future__ import annotations":
                anchor = i
                break
        if anchor is None:
            raise SystemExit(f"[FAIL] {path.name}: 找不到 __future__ 锚点，不写入")
        lines.insert(anchor + 1, f"{IMPORT_LINE}{nl}")
    for kind, lineno, old, new in sorted(edits, key=lambda e: -e[1]):
        if kind == "skip":
            continue
        if kind == "hdr":
            lines[lineno - 1] = new + nl
        else:
            lines.insert(lineno - 1, new)
    return "".join(lines)'''

R4_NEW = '''def apply_a1(path: Path, src: str, edits) -> str:
    """★ 先按原始行号落编辑，**最后**再插导入。

    历史坑（2026-10-22 实测踩过）：导入若先插入，其后所有行号 +1，而 edits 里存的
    仍是原始行号 —— 每条编辑都落到目标行的上一行：头部改写覆盖 try 体、插入语句
    跑到 except 之上，直接 IndentationError 并丢内容。
    """
    nl = nl_of(src)
    lines = src.splitlines(keepends=True)
    for kind, lineno, old, new in sorted(edits, key=lambda e: -e[1]):
        if kind == "skip":
            continue
        if kind == "hdr":
            lines[lineno - 1] = new + nl
        else:
            lines.insert(lineno - 1, new)
    if IMPORT_LINE not in src:
        anchor = None
        for i, ln in enumerate(lines):
            if ln.strip() == "from __future__ import annotations":
                anchor = i
                break
        if anchor is None:
            raise SystemExit(f"[FAIL] {path.name}: 找不到 __future__ 锚点，不写入")
        lines.insert(anchor + 1, f"{IMPORT_LINE}{nl}")
    return "".join(lines)'''

# ---- 2. _apply_round2.py CI 双补丁 ----
R2_OLD_CALL = '    cov1, cov1_msgs = patch_cov(CI_YML, "ci.yml")'
R2_NEW_CALL = '''    if ci_text is not None:
        _tmp = ROOT / ".ci_tmp.yml"
        write(_tmp, ci_text)
        cov1, cov1_msgs = patch_cov(_tmp, "ci.yml")
        _tmp.unlink()
    else:
        cov1, cov1_msgs = patch_cov(CI_YML, "ci.yml")'''
R2_OLD_LOOP = "        for p, s in [(CI_YML, ci_text), (CI_YML, cov1), (CI_WIN, cov2),"
R2_NEW_LOOP = "        for p, s in [(CI_YML, cov1), (CI_WIN, cov2),"

# ---- 3. _log.py gap_entries ----
LOG_ALL_OLD = '__all__ = ["get_logger", "log_gap", "gap_records", "reset_gaps", "attach_file_log"]'
LOG_ALL_NEW = ('__all__ = ["get_logger", "log_gap", "gap_records", "gap_entries", '
               '"reset_gaps", "attach_file_log"]')
LOG_ANCHOR = '''def reset_gaps() -> None:
    """清空本次进程内的降级记录（测试用）。"""
    _gaps.clear()'''
LOG_ADD = LOG_ANCHOR + '''


def gap_entries() -> list[dict[str, object]]:
    """把本次进程的降级记录转成**缺口台账**的条目格式，供 `.gaps.json` 合并。

    与 `_gap_ledger.py` 的条目 schema 对齐：``cls="R"`` 表示运行期降级、
    ``decisive=False``（log_gap 只登记「没取到但不阻断」的块，是否决定性由人判定，
    不在这里替下游下结论）。
    """
    return [
        {
            "channel": r["section"],
            "label": r["section"],
            "status": "runtime",
            "cls": "R",
            "decisive": False,
            "blocks": "运行期降级：该数据块本次未取到，采集未中断",
            "remedy": "重跑该通道；持续失败则检查数据源可用性与凭证",
            "fallback": "该块以占位/缺失呈现，依赖它的结论须写成条件式",
            "kw": [r["section"]],
            "note": r["detail"],
        }
        for r in gap_records()
    ]'''

# ---- 4. collect_a_stock.py 并入台账 ----
CAS_IMP_OLD = "from wb_analysis._log import log_gap"
CAS_IMP_NEW = "from wb_analysis._log import gap_entries, log_gap"
CAS_ANCHOR = '    gaps_path = EVID_DIR / f"{ticker}_{date}.gaps.json"'
CAS_ADD = '''    # ★ 2026-10-22：把本次运行期降级（log_gap 记录）并入台账。
    #   采集器与 _gap_ledger.py 是不同进程，进程内 _gaps 传不过去 —— 不落盘，
    #   下游 _gen_meta 的 notes 与 _scorecard 就永远读不到，「记了没人看」等于没记。
    gaps_record["gaps"].extend(gap_entries())
    gaps_record["total_gaps"] = len(gaps_record["gaps"])

''' + CAS_ANCHOR


def read(p: Path) -> str:
    with p.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(p: Path, s: str) -> None:
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(s)


def main() -> int:
    apply = "--apply" in sys.argv
    print(f"=== {'APPLY' if apply else 'DRY-RUN'} ===\n")

    jobs = [
        ("1. _apply_round4.py 行号漂移", R4, [(R4_OLD, R4_NEW)]),
        ("2. _apply_round2.py CI 双补丁", R2, [(R2_OLD_CALL, R2_NEW_CALL),
                                              (R2_OLD_LOOP, R2_NEW_LOOP)]),
        ("3. _log.py gap_entries", LOG, [(LOG_ALL_OLD, LOG_ALL_NEW),
                                         (LOG_ANCHOR, LOG_ADD)]),
        ("4. collect_a_stock.py 并入台账", CAS, [(CAS_IMP_OLD, CAS_IMP_NEW),
                                                 (CAS_ANCHOR, CAS_ADD)]),
    ]
    for title, path, rules in jobs:
        src = read(path)
        msgs = []
        for old, new in rules:
            if new in src:
                msgs.append("已有")
            elif old in src:
                src = src.replace(old, new, 1)
                msgs.append("改")
            else:
                msgs.append("FAIL:锚点未匹配")
        print(f"  [{title}] {', '.join(msgs)}")
        if apply and "FAIL" not in " ".join(msgs):
            write(path, src)

    # 5. 归档
    print("\n  [5. 归档一次性脚本]")
    if not ONEOFF.exists():
        print("      建 scripts/_oneoff/")
        if apply:
            ONEOFF.mkdir(parents=True, exist_ok=True)
    for name in ARCHIVE:
        src_p = ROOT / "scripts" / name
        dst_p = ONEOFF / name
        if not src_p.exists():
            print(f"      [跳过] {name} 不存在（可能已归档）")
            continue
        body = read(src_p)
        body = re.sub(r"# lifecycle:\s*\w+", "# lifecycle: oneoff", body, count=1)
        if "# serves:" not in body:
            body = body.replace("# lifecycle: oneoff",
                                f"# lifecycle: oneoff\n# serves: {SERVES}", 1)
        print(f"      {name} -> scripts/_oneoff/（标 oneoff + serves）")
        if apply:
            write(src_p, body)
            shutil.move(str(src_p), str(dst_p))

    print("\n" + ("已写入。" if apply else "干跑结束，未改动。确认后加 --apply。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
