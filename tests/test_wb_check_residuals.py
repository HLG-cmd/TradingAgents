"""wb_analysis/_check_residuals.py 的单元测试。

验证订正残留检查的行分类（引用 vs 疑似残留）与草稿目录扫描逻辑。
"""
from __future__ import annotations

import json

from wb_analysis import _check_residuals as cr


def test_classify_marks_lines_with_correction_keywords_as_quote():
    assert cr._classify("简报 §1.1 跳空幅度订正（原值 −5.02%）") == "引用"
    assert cr._classify("历史原写为 100 亿，实际为 120 亿") == "引用"
    assert cr._classify("注：此处为修正后的数据（旧值 50%）") == "引用"
    assert cr._classify("冲突登记 CF-2：旧表述不复述") == "引用"
    assert cr._classify("🔧 标记为错，已改为最新口径") == "引用"


def test_classify_marks_plain_lines_as_suspected_residual():
    assert cr._classify("预计下季度毛利率将达到 55.4%") == "疑似残留"
    assert cr._classify("当前股价相较于基准日跳空 −5.02%") == "疑似残留"


def test_check_passes_when_no_corrections_file(tmp_path):
    d = tmp_path / "draft_empty"
    d.mkdir()
    assert cr.check(d) == 0


def test_check_passes_when_corrections_list_empty(tmp_path):
    d = tmp_path / "draft_empty_list"
    d.mkdir()
    (d / "_corrections.json").write_text(json.dumps({"corrections": []}), encoding="utf-8")
    assert cr.check(d) == 0


def test_check_exempts_files_in_fixed_in(tmp_path):
    d = tmp_path / "draft_fixed_in"
    d.mkdir()
    corrections = {
        "corrections": [
            {
                "old": "−5.02%",
                "new": "−5.365%",
                "note": "跳空幅度订正",
                "fixed_in": ["0_brief.md"],
            }
        ]
    }
    (d / "_corrections.json").write_text(json.dumps(corrections), encoding="utf-8")
    # 0_brief.md 在 fixed_in 中，即使行内无额外标记也算合法留痕/订正源
    (d / "0_brief.md").write_text("跳空 −5.365%（此前记录 −5.02%）", encoding="utf-8")
    assert cr.check(d) == 0


def test_check_exempts_lines_with_quote_markers_even_if_not_in_fixed_in(tmp_path):
    d = tmp_path / "draft_quoted"
    d.mkdir()
    corrections = {
        "corrections": [
            {
                "old": "−5.02%",
                "new": "−5.365%",
                "note": "跳空幅度订正",
                "fixed_in": ["0_brief.md"],
            }
        ]
    }
    (d / "_corrections.json").write_text(json.dumps(corrections), encoding="utf-8")
    (d / "0_brief.md").write_text("已订正为 −5.365%", encoding="utf-8")
    # manager.md 不在 fixed_in 中，但行内有「订正」标记，识别为合法引用
    sub = d / "2_research"
    sub.mkdir()
    (sub / "manager.md").write_text("根据简报订正，旧值 −5.02% 不再采用。", encoding="utf-8")
    assert cr.check(d) == 0


def test_check_fails_on_unmarked_downstream_residual(tmp_path):
    d = tmp_path / "draft_residual"
    d.mkdir()
    corrections = {
        "corrections": [
            {
                "old": "−5.02%",
                "new": "−5.365%",
                "note": "跳空幅度订正",
                "fixed_in": ["0_brief.md"],
            }
        ]
    }
    (d / "_corrections.json").write_text(json.dumps(corrections), encoding="utf-8")
    (d / "0_brief.md").write_text("订正为 −5.365%", encoding="utf-8")
    # sentiment.md 不在 fixed_in，且正文没有订正标记，裸残留旧值
    sub = d / "1_analysts"
    sub.mkdir()
    (sub / "sentiment.md").write_text("开盘跳空 −5.02%，情绪低迷。", encoding="utf-8")
    assert cr.check(d) == 1


def test_check_skips_archive_dirs_and_skip_names(tmp_path):
    d = tmp_path / "draft_archive"
    d.mkdir()
    corrections = {
        "corrections": [
            {"old": "OLD_VAL", "new": "NEW_VAL", "fixed_in": []}
        ]
    }
    (d / "_corrections.json").write_text(json.dumps(corrections), encoding="utf-8")
    (d / "_constraints.md").write_text("OLD_VAL in constraints", encoding="utf-8")

    stale_dir = d / "_stale_run"
    stale_dir.mkdir()
    (stale_dir / "old_doc.md").write_text("OLD_VAL was here", encoding="utf-8")

    assert cr.check(d) == 0
