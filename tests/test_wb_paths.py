"""wb_analysis/_paths.py 的单元测试。

锁定 reports/ 布局契约、功能目录、顶层白名单、草稿归档跳过判定及报告树枚举生成器。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wb_analysis import _paths as P


@pytest.mark.parametrize("name,ticker,ymd,hms", [
    ("NVDA_20261010_110109", "NVDA", "20261010", "110109"),
    ("512400.SS_20261010_110109", "512400.SS", "20261010", "110109"),
    ("hkHSTECH_20261010_110109", "hkHSTECH", "20261010", "110109"),
    ("515100_20261010_110109", "515100", "20261010", "110109"),
    ("BRK.B_20261010_110109", "BRK.B", "20261010", "110109"),
])
def test_tree_re_matches_valid_report_tree_names(name, ticker, ymd, hms):
    m = P.TREE_RE.match(name)
    assert m is not None
    assert m.group(1) == ticker
    assert m.group(2) == ymd
    assert m.group(3) == hms


@pytest.mark.parametrize("bad_name", [
    "NVDA_20261010",           # 缺时间
    "_archive",                # 功能目录
    "INDEX.md",                # 顶层文件
    "NVDA_20261010_1101",      # 时间不足 6 位
    "NVDA_20261010_110109_bak", # 额外后缀
    "NVDA 20261010 110109",    # 空格分隔
])
def test_tree_re_rejects_invalid_names(bad_name):
    assert P.TREE_RE.match(bad_name) is None


def test_func_dirs_and_allowed_top_constants():
    assert P.FUNC_DIRS == frozenset({"_datasets", "_other", "_archive", "_audit"})
    assert P.ALLOWED_TOP == frozenset({"INDEX.md", "README.md", "QUALITY.csv"})


def test_iter_report_trees(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()

    # 1. 正常标的与报告树
    (reports / "NVDA" / "NVDA_20261010_110109").mkdir(parents=True)
    (reports / "AAPL" / "AAPL_20261011_120000").mkdir(parents=True)

    # 2. 功能目录（不应被当作标的）
    (reports / "_datasets" / "data1").mkdir(parents=True)
    (reports / "_archive" / "old_tree").mkdir(parents=True)

    # 3. 标的下的非报告树子目录（如二级 _archive）
    (reports / "SKHY" / "_archive").mkdir(parents=True)
    (reports / "SKHY" / "SKHY_20261012_093000").mkdir(parents=True)

    # 4. 顶层文件
    (reports / "INDEX.md").write_text("# Index", encoding="utf-8")

    trees = list(P.iter_report_trees(reports))
    assert len(trees) == 3
    tree_names = [tr.name for _, tr in trees]
    assert tree_names == ["AAPL_20261011_120000", "NVDA_20261010_110109", "SKHY_20261012_093000"]

    # 缺失目录不崩
    missing = tmp_path / "nonexistent"
    assert list(P.iter_report_trees(missing)) == []


def test_is_archived_path_and_any_archived():
    assert P.SKIP_ARCHIVE_DIRS == ("_stale", "_archive")
    assert P.is_archived_path("wb_analysis/drafts/_stale_pre_brief/manager.md")
    assert P.is_archived_path(Path("wb_analysis/drafts/NVDA/_archive/trader.md"))
    assert not P.is_archived_path("wb_analysis/drafts/NVDA/manager.md")

    paths = [
        Path("wb_analysis/drafts/NVDA/manager.md"),
        Path("wb_analysis/drafts/NVDA/_stale/trader.md"),
    ]
    assert P.any_archived(paths)
    assert not P.any_archived([paths[0]])
