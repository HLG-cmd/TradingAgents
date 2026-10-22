"""wb_analysis/_gen_meta.py 的测试。

选它是因为它身上有两处「曾经静默出错、后来硬阻断」的历史，测试就是守着它们不复发：

* ``notes`` 曾硬编码某一轮的结论 ⇒ 此后**每一轮** RUN.json 都带着错的事实
* 缺 ``meta.json`` 曾静默退化成空 ``as_of`` / 空 ``ratings`` ⇒ ``_precheck`` 反读失据

另外它是**缺口台账的消费端**（``gaps.json`` → ``notes``）：采集器在运行期
降级时并进台账的条目，必须能一路走到这里。
"""
from __future__ import annotations

import json

import pytest

from wb_analysis import _gen_meta as gm


@pytest.fixture()
def fake_root(tmp_path, monkeypatch):
    (tmp_path / "wb_analysis" / "evidence").mkdir(parents=True)
    monkeypatch.setattr(gm, "ROOT", tmp_path)
    return tmp_path


def _write_gaps(root, ticker="GOOG", as_of="2026-10-01", **payload):
    p = root / "wb_analysis" / "evidence" / f"{ticker}_{as_of}.gaps.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# ── notes 的四种状态：都必须显式说明，不许静默留空 ─────────────────────────

def test_notes_when_ledger_missing(fake_root):
    assert "未找到缺口台账" in gm._notes_from_gaps("GOOG", "2026-10-01")


def test_notes_when_ledger_unparsable(fake_root):
    (fake_root / "wb_analysis" / "evidence" / "GOOG_2026-10-01.gaps.json").write_text(
        "{not json", encoding="utf-8"
    )
    assert "解析失败" in gm._notes_from_gaps("GOOG", "2026-10-01")


def test_notes_when_no_gaps(fake_root):
    _write_gaps(fake_root, channels_ok=8, channels_total=8, gaps=[])
    notes = gm._notes_from_gaps("GOOG", "2026-10-01")
    assert "8/8" in notes
    assert "无登记缺口" in notes


def test_resolved_decisive_gap_is_not_counted_as_decisive(fake_root):
    """2026-10-19 的修复：supplement 补全后 status=resolved 但 decisive 仍为 True。

    若不过滤，notes 会长期声明一个**已解决**的问题，与 _precheck 的
    「决定性缺口 N 条」口径不一致。
    """
    _write_gaps(fake_root, channels_ok=7, channels_total=8, gaps=[
        {"channel": "options", "decisive": True, "status": "resolved"},
        {"channel": "insider", "decisive": True, "status": "open"},
        {"channel": "news", "decisive": False, "status": "open"},
    ])
    notes = gm._notes_from_gaps("GOOG", "2026-10-01")
    assert "登记缺口 3 条" in notes
    assert "决定性 1 条" in notes
    assert "insider" in notes
    assert "options" not in notes, "resolved 的不该算决定性"
    assert "news" not in notes, "非决定性不点名"


def test_channels_fall_back_to_evidence_md(fake_root):
    """部分采集器不写 channels_*，台账里是 None ⇒ 曾出现「通道 None/None」这种无信息文本。"""
    _write_gaps(fake_root, channels_ok=None, channels_total=None, gaps=[])
    (fake_root / "wb_analysis" / "evidence" / "GOOG_2026-10-01.md").write_text(
        "# 证据\n成功: 6 / 9\n", encoding="utf-8"
    )
    assert "6/9" in gm._notes_from_gaps("GOOG", "2026-10-01")


def test_runtime_degradation_entries_reach_notes(fake_root):
    """运行期降级（``cls=R``，来自 ``log_gap``）必须计入台账条数。

    这正是采集器把 ``gap_entries()`` 并进 gaps.json 的目的：采集器与台账脚本
    是**不同进程**，模块级 ``_gaps`` 传不过去，只能由采集器自己落盘。
    """
    from wb_analysis._log import gap_entries, log_gap, reset_gaps

    reset_gaps()
    try:
        log_gap("options.realtime_close", RuntimeError("vendor 502"))
        entries = gap_entries()
        assert entries, "log_gap 之后必须有记录"
        _write_gaps(fake_root, channels_ok=7, channels_total=8,
                    gaps=entries, total_gaps=len(entries))
        notes = gm._notes_from_gaps("GOOG", "2026-10-01")
        assert "登记缺口 1 条" in notes
        assert "决定性 0 条" in notes
    finally:
        reset_gaps()


# ── build：有失败项就不许写盘 ──────────────────────────────────────────────

def test_build_refuses_to_write_when_a_label_is_missing(fake_root, monkeypatch):
    drafts = fake_root / "wb_analysis" / "drafts"
    monkeypatch.setattr(gm, "DRAFTS", drafts)
    d = drafts / "GOOG_2026-10-01"
    for rel, text in {
        "2_research/manager.md": "**Recommendation**: Overweight",
        "3_trading/trader.md": "**Action**: 这里故意缺标签",
        "4_risk/portfolio_manager.md": "**Rating**: Hold",
    }.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    assert gm.build("GOOG_2026-10-01") == 1
    assert not (d / "meta.json").exists(), "有失败项时不得写盘（否则又是静默降级）"


def test_build_writes_ratings_extracted_from_conclusion_blocks(fake_root, monkeypatch):
    drafts = fake_root / "wb_analysis" / "drafts"
    monkeypatch.setattr(gm, "DRAFTS", drafts)
    d = drafts / "GOOG_2026-10-01"
    for rel, text in {
        "2_research/manager.md": "**Recommendation**: Overweight",
        "3_trading/trader.md": "**Action**: Sell\nFINAL TRANSACTION PROPOSAL: **SELL**",
        "4_risk/portfolio_manager.md": "**Rating**: Hold",
    }.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    assert gm.build("GOOG_2026-10-01") == 0
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["ticker"] == "GOOG"
    assert meta["as_of"] == "2026-10-01"
    assert meta["ratings"] == {
        "research_manager": "Overweight",
        "trader_action": "Sell",
        "portfolio_manager": "Hold",
    }
    # 没有台账时必须显式说明，而不是留一个空 notes
    assert meta["notes"]
    assert "缺口台账" in meta["notes"]
