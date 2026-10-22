"""wb_analysis/_verify_ratings.py 的单元测试。

验证评级词扫描与契约字段校验（五档词允许席位、必需字段校验、违规阻断）。
"""
from __future__ import annotations

from pathlib import Path

from wb_analysis import _verify_ratings as vr


def test_required_fields_and_five_allowed_seats():
    assert "2_research/manager.md" in vr.REQUIRED_FIELDS
    assert "Recommendation" in vr.REQUIRED_FIELDS["2_research/manager.md"]

    assert "4_risk/portfolio_manager.md" in vr.REQUIRED_FIELDS
    assert "Rating" in vr.REQUIRED_FIELDS["4_risk/portfolio_manager.md"]

    assert "3_trading/trader.md" in vr.REQUIRED_FIELDS
    assert "Action" in vr.REQUIRED_FIELDS["3_trading/trader.md"]
    assert vr.FINAL_PROPOSAL in vr.REQUIRED_FIELDS["3_trading/trader.md"]

    # 允许出现五档评级的席位：2_research/manager.md, 3_trading/trader.md 及 4_risk 下各席位
    assert "2_research/manager.md" in vr.FIVE_ALLOWED
    assert "3_trading/trader.md" in vr.FIVE_ALLOWED
    assert "4_risk/portfolio_manager.md" in vr.FIVE_ALLOWED
    assert "4_risk/aggressive.md" in vr.FIVE_ALLOWED

    # 分析师与多空辩论席位禁止出现五档词
    assert "1_analysts/news.md" not in vr.FIVE_ALLOWED
    assert "2_research/bull.md" not in vr.FIVE_ALLOWED
    assert "2_research/bear.md" not in vr.FIVE_ALLOWED


def _populate_clean_draft(root: Path):
    """填充一份契约全部合规的最小草稿。"""
    for rel in vr.ROLE_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel == "2_research/manager.md":
            p.write_text("**Recommendation**: Overweight\n分析结论。\n", encoding="utf-8")
        elif rel == "4_risk/portfolio_manager.md":
            p.write_text("**Rating**: Overweight\n风控核准。\n", encoding="utf-8")
        elif rel == "3_trading/trader.md":
            p.write_text("**Action**: Buy\nFINAL TRANSACTION PROPOSAL: **BUY**\n", encoding="utf-8")
        else:
            p.write_text("无评级词的正文内容。\n", encoding="utf-8")


def test_main_passes_on_compliant_draft(tmp_path, monkeypatch):
    draft_dir = tmp_path / "drafts" / "NVDA_2026-10-10"
    _populate_clean_draft(draft_dir)
    monkeypatch.setattr(vr.sys, "argv", ["_verify_ratings.py", str(draft_dir)])
    assert vr.main() == 0


def test_main_fails_when_role_file_missing(tmp_path, monkeypatch):
    draft_dir = tmp_path / "drafts" / "NVDA_2026-10-10"
    _populate_clean_draft(draft_dir)
    # 删除必需的角色文件
    (draft_dir / "1_analysts" / "market.md").unlink()
    monkeypatch.setattr(vr.sys, "argv", ["_verify_ratings.py", str(draft_dir)])
    assert vr.main() == 1


def test_main_fails_when_stray_rating_in_disallowed_file(tmp_path, monkeypatch):
    draft_dir = tmp_path / "drafts" / "NVDA_2026-10-10"
    _populate_clean_draft(draft_dir)
    # 在禁止席位中写入裸五档词
    (draft_dir / "1_analysts" / "news.md").write_text("新闻分析师建议给予 Buy 评级。\n", encoding="utf-8")
    monkeypatch.setattr(vr.sys, "argv", ["_verify_ratings.py", str(draft_dir)])
    assert vr.main() == 1


def test_main_fails_when_required_field_missing(tmp_path, monkeypatch):
    draft_dir = tmp_path / "drafts" / "NVDA_2026-10-10"
    _populate_clean_draft(draft_dir)
    # manager.md 漏写 **Recommendation**:
    (draft_dir / "2_research" / "manager.md").write_text("正文内容但缺少必需推荐标签。\n", encoding="utf-8")
    monkeypatch.setattr(vr.sys, "argv", ["_verify_ratings.py", str(draft_dir)])
    assert vr.main() == 1
