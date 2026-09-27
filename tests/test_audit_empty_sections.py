"""`wb_analysis/_audit_empty_sections.py` 的双向夹具自检。

为什么必须双向：只测"能抓到空小节"会漏掉**误报**（把有内容的判成空），
只测"不误报"会漏掉**漏报**（把空的放过）。两个方向都要有夹具。
（2026-09-27 立：本项目此前三次「全绿但正文为空」全靠人眼发现，
本工具就是为把它自动化而写；首版曾两度判错 —— 一次误报父标题、一次漏掉只有标题的条目。）
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "_audit_empty_sections", ROOT / "wb_analysis" / "_audit_empty_sections.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = _load()


@pytest.mark.unit
def test_strips_link_url_fence_and_separator():
    """严格判据必须剔掉 Link / URL / 围栏 / 分隔线 / 标题行 —— 它们都不是正文。"""
    body = [
        "### Some Headline (source: X)",
        "Link: https://example.com/a",
        "---",
        "```",
        "```",
        "",
        "   ",
    ]
    assert A.body_len(body) == 0


@pytest.mark.unit
def test_keeps_real_prose():
    body = ["### Headline", "Link: https://x", "This is the actual summary text."]
    assert A.body_len(body) == len("This is the actual summary text.")


@pytest.mark.unit
def test_parent_heading_with_content_is_not_flagged():
    """`## 5. 个股新闻` 是父标题，内容挂在同级通道标题下 ⇒ **不得**报空（防误报）。"""
    text = (
        "## 5. 个股新闻\n"
        "\n"
        "## TICKER News, from 2026-01-01 to 2026-01-31:\n"
        "\n"
        "### A real headline\n"
        "Actual summary body text here.\n"
        "\n"
        "## 6. 全球宏观新闻\n"
    )
    secs = A.split_sections(text)
    empties = [
        t for i, (t, b) in enumerate(secs)
        if A.body_len(b) == 0
        and not (
            i + 1 < len(secs)
            and not secs[i + 1][0][:1].isdigit()
            and A.body_len(secs[i + 1][1]) > 0
        )
    ]
    assert "5. 个股新闻" not in empties


@pytest.mark.unit
def test_hollow_section_with_titles_and_links_is_flagged():
    """只有 `### 标题` + `Link:` 的小节 —— 原始字符数很大但**正文为 0**，必须报空（防漏报）。"""
    text = (
        "## 6. 全球宏观新闻\n"
        "\n"
        "## Global Market News, from 2026-01-01 to 2026-01-31:\n"
        "\n"
        "### Headline one (source: A)\n"
        "Link: https://example.com/1\n"
        "\n"
        "### Headline two (source: B)\n"
        "Link: https://example.com/2\n"
        "\n"
        "## 7. 社媒情绪\n"
    )
    secs = A.split_sections(text)
    target = dict(secs)
    # 该小节原始字符数不为 0（有标题和链接）……
    assert sum(len(x) for x in target["Global Market News, from 2026-01-01 to 2026-01-31:"]) > 50
    # ……但严格正文必须是 0
    assert A.body_len(target["Global Market News, from 2026-01-01 to 2026-01-31:"]) == 0


@pytest.mark.unit
def test_channels_health_parsed():
    assert A.channels_health("通道健康度: 35/35 通道成功") == (35, 35)
    assert A.channels_health("32/35 通道成功") == (32, 35)
    assert A.channels_health("no health line here") is None


@pytest.mark.unit
def test_gap_ledger_keywords_collected(tmp_path):
    ev = tmp_path / "T_2026-01-01.md"
    ev.write_text("# x", encoding="utf-8")
    (tmp_path / "T_2026-01-01.gaps.json").write_text(
        '{"gaps":[{"label":"profile","kw":["§3","快照被上游扣留"]}]}', encoding="utf-8"
    )
    keys = A.declared_gaps(ev)
    assert "profile" in keys and "§3" in keys
