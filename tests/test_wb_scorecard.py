"""wb_analysis/_scorecard.py 的测试。

`score_tree` 是质量记分卡的唯一数据来源（`_health.py` 的「质量记分卡 77/77 轮」门禁
直接消费它），但它有一类失败最难发现：**指标缺值被填成 0**。
0 和「未知」在 CSV 里长得一样，而 0 读起来像「没问题」。

这里守的就是这条线：审计包里**没有**台账 ⇒ 决定性缺口必须是「未知」，不能是 0。
"""
from __future__ import annotations

import json
import zipfile

from wb_analysis import _scorecard as sc


def _tree(tmp_path, name="GOOG_2026-10-01", *, entries=None, run=None, report=""):
    """搭一棵最小报告树。`entries=None` 表示连 `_source.zip` 都没有。"""
    tr = tmp_path / name
    tr.mkdir(parents=True)
    if report:
        (tr / "complete_report.md").write_text(report, encoding="utf-8")
    if run is not None:
        (tr / "RUN.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    if entries is not None:
        with zipfile.ZipFile(tr / "_source.zip", "w") as z:
            for n, t in entries.items():
                z.writestr(n, t)
    return tr


LEDGER = {
    "channels_ok": 7, "channels_total": 8,
    "decisive_count": 2, "resolved_count": 0,
    "gaps": [
        {"channel": "option_iv", "label": "option_iv", "decisive": True,
         "status": "failed", "kw": ["期权维度", "IV 等级"]},
        {"channel": "forward_eps", "label": "forward_eps", "decisive": True,
         "status": "failed", "kw": ["前瞻 EPS"]},
        {"channel": "option_oi", "label": "option_oi", "decisive": False,
         "status": "failed", "kw": ["持仓量"]},
    ],
}


# ── 决定性缺口：缺值必须是「未知」，不是 0 ─────────────────────────────────

def test_pack_without_ledger_must_not_report_zero_decisive_gaps(tmp_path):
    """审计包在、但里面没有台账 ⇒ 状态**未知**。

    若这里算成 0，CSV 里就出现一个读起来像「本轮无决定性缺口」的干净数字，
    而真相是「台账没进包」——静默降级最典型的样子。
    """
    tr = _tree(tmp_path, entries={"evidence/GOOG_2026-10-01.md": "成功: 7 / 8\n"})
    assert sc.score_tree(tr)["decisive_gaps"] == ""


def test_decisive_gaps_read_from_ledger_in_pack(tmp_path):
    tr = _tree(tmp_path, entries={
        "evidence/GOOG_2026-10-01.md": "成功: 7 / 8\n",
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(LEDGER, ensure_ascii=False),
    })
    row = sc.score_tree(tr)
    assert row["decisive_gaps"] == 2, "台账自带 decisive_count，直接用"
    assert row["channels_ok"] == 7 and row["channels_total"] == 8


def test_decisive_gaps_counted_when_ledger_lacks_summary_field(tmp_path):
    """台账没写 decisive_count 时按条目数兜底（resolved 已被台账置为 decisive=False）。"""
    led = {k: v for k, v in LEDGER.items() if k != "decisive_count"}
    tr = _tree(tmp_path, entries={
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(led, ensure_ascii=False),
    })
    assert sc.score_tree(tr)["decisive_gaps"] == 2


def test_empty_ledger_in_pack_is_zero_not_unknown(tmp_path):
    """台账确实读了、且里面没有决定性缺口 ⇒ 这才该是 0。"""
    tr = _tree(tmp_path, entries={
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(
            {"channels_ok": 8, "channels_total": 8, "decisive_count": 0, "gaps": []}
        ),
    })
    assert sc.score_tree(tr)["decisive_gaps"] == 0


def test_falls_back_to_prev_cache_when_zip_stripped(tmp_path):
    """轻量归档副本剔掉了 `_source.zip` ⇒ 从既有 QUALITY.csv 回填。"""
    tr = _tree(tmp_path, run={"data_date": "2026-10-01"})
    prev = {"GOOG_2026-10-01": {"channels_ok": "6", "channels_total": "8",
                                "decisive_gaps": "3", "gap_declared": "yes"}}
    row = sc.score_tree(tr, prev)
    assert row["decisive_gaps"] == 3
    assert row["channels_ok"] == 6 and row["channels_total"] == 8
    assert row["gap_declared"] == "yes"


# ── 缺口是否在简报里声明：用台账的 kw，与门禁同口径 ────────────────────────

def test_gap_declared_yes_only_when_brief_mentions_every_decisive_gap(tmp_path):
    """口径是「**每一个**决定性缺口都被提到」——漏一个就判 no，不是提一个就够。"""
    tr = _tree(tmp_path, entries={
        "drafts/0_brief.md": "缺口台账：期权维度不可用（IV 等级缺失）、前瞻 EPS 不可得。\n",
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(LEDGER, ensure_ascii=False),
    })
    assert sc.score_tree(tr)["gap_declared"] == "yes"


def test_gap_declared_no_when_one_decisive_gap_is_unmentioned(tmp_path):
    """只提了一个决定性缺口（forward_eps 漏了）⇒ no。"""
    tr = _tree(tmp_path, entries={
        "drafts/0_brief.md": "缺口台账：期权维度不可用（IV 等级缺失）。\n",
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(LEDGER, ensure_ascii=False),
    })
    assert sc.score_tree(tr)["gap_declared"] == "no"


def test_gap_declared_no_when_brief_is_silent(tmp_path):
    tr = _tree(tmp_path, entries={
        "drafts/0_brief.md": "本轮结论：估值合理，维持持有。\n",
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(LEDGER, ensure_ascii=False),
    })
    assert sc.score_tree(tr)["gap_declared"] == "no"


def test_gap_declared_blank_when_no_decisive_gap(tmp_path):
    """没有决定性缺口时该项留空（不适用），不该硬写 yes/no。"""
    tr = _tree(tmp_path, entries={
        "drafts/0_brief.md": "无。\n",
        "evidence/GOOG_2026-10-01.gaps.json": json.dumps(
            {"channels_ok": 8, "channels_total": 8, "decisive_count": 0, "gaps": []}
        ),
    })
    assert sc.score_tree(tr)["gap_declared"] == ""


# ── 其余指标 ──────────────────────────────────────────────────────────────

def test_traceable_requires_run_json_and_a_manifest(tmp_path):
    assert sc.score_tree(_tree(tmp_path, name="A_2026-10-01"))["traceable"] == ""
    tr = _tree(tmp_path, name="B_2026-10-01", run={"data_date": "2026-10-01"})
    assert sc.score_tree(tr)["traceable"] == ""
    (tr / "SOURCE_MANIFEST.json").write_text("{}", encoding="utf-8")
    assert sc.score_tree(tr)["traceable"] == "yes"


def test_report_marks_counted_from_complete_report(tmp_path):
    tr = _tree(tmp_path, report=(
        "数据来源：FRED 官方/交易所 自算\n"
        "此处数据缺失，无法判定。\n"
        "若 IV 恢复则倾向 Sell，若否则维持 Hold。\n"
    ))
    row = sc.score_tree(tr)
    assert row["verif_marks"] >= 2, "FRED + 官方/交易所 应命中多个核验家族"
    assert row["honest_marks"] >= 2, "数据缺失 + 无法判定"
    assert row["conditional"] == "yes"
    assert row["report_chars"] == len((tr / "complete_report.md").read_text(encoding="utf-8"))
