"""`_seal_run` / `_lint_drafts` / `_role_prompt` 里纯函数的离线单测（零网络、零真实文件）。

为什么挑这三个函数：

* `_seal_run._arcname` —— 文件自称「唯一定义源」，历史上曾在**三处**各写一遍 if/elif；
  它决定散件进审计包后的路径，写错就是「包里有文件但读不到」。
* `_lint_drafts.norm` / `expand` —— 数字溯源的匹配基座：`expand` 漏一种写法，
  门禁就会把真实存在的数字判成「编造」（假红），反之过宽则放过编造（假绿）。
* `_role_prompt._forbidden` —— 角色隔离契约：牛熊互斥、分析师不读研究稿。
  这是「12 角色互相不抄」的唯一技术保障。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from wb_analysis import _lint_drafts, _role_prompt, _seal_run


@pytest.mark.unit
class TestArcname:
    """`_arcname`：散件 → 审计包内路径。"""

    @pytest.mark.parametrize(
        "kind,name,expected",
        [
            ("evidence", "NVDA_2026-10-22.md", "evidence/NVDA_2026-10-22.md"),
            ("analysis", "NVDA.json", "analysis/NVDA.json"),
            ("oneoff", "probe.py", "oneoff/probe.py"),
        ],
    )
    def test_known_kinds_use_fixed_prefix(self, kind, name, expected):
        assert _seal_run._arcname(kind, Path("whatever") / name) == expected

    def test_drafts_keep_relative_structure(self, monkeypatch, tmp_path):
        # drafts 保留相对层级（12 角色按子目录存放），不能压平成 drafts/<文件名>
        monkeypatch.setattr(_seal_run, "DRAFTS", tmp_path)
        f = tmp_path / "NVDA_2026-10-22" / "1_analysts" / "market.md"
        assert _seal_run._arcname("drafts", f) == "drafts/NVDA_2026-10-22/1_analysts/market.md"

    def test_unknown_kind_defaults_to_drafts(self, monkeypatch, tmp_path):
        # 未知 kind 不得抛异常：落到 drafts 分支（宁可按原层级归档，也不丢文件）
        monkeypatch.setattr(_seal_run, "DRAFTS", tmp_path)
        assert _seal_run._arcname("mystery", tmp_path / "a.md") == "drafts/a.md"


@pytest.mark.unit
class TestLintNormExpand:
    def test_norm_strips_thousands_sep_and_trailing_dot(self):
        assert _lint_drafts.norm("1,234.") == "1234"
        assert _lint_drafts.norm("12.5") == "12.5"

    def test_expand_keeps_original_token(self):
        assert "1234.5" in _lint_drafts.expand({"1234.5"})

    def test_expand_covers_scaled_forms(self):
        # 1.2345 亿在正文里可能写成 1.23 / 1.2 / 123450000 等多种形态
        got = _lint_drafts.expand({"123450000"})
        for form in ("1.2345", "1.23", "1.2", "123450000"):
            assert form in got, f"缺少等价写法 {form}"

    def test_expand_covers_yi_and_wan_units(self):
        """「亿元 / 万元」是本项目金额的默认单位（`_fmt.ystr` scale=1e8）。

        2026-10-23 实测：原缩放表缺 1e4/1e8 ⇒ 源值 12,345,000,000 展开后不含 "123.45"，
        草稿里合法的「123.45 亿元」会被 4b 节点判成编造数字（假红）。本用例锁住该修复。
        """
        assert "123.45" in _lint_drafts.expand({"12345000000"})   # 123.45 亿元
        assert "512" in _lint_drafts.expand({"5120000"})          # 512 万元
        assert "1.2345" in _lint_drafts.expand({"123450000"})     # 1.2345 亿元

    def test_expand_ignores_non_numeric(self):
        # 非数字 token 不得让 expand 抛错（证据包里混着日期、代码、单位）
        assert _lint_drafts.expand({"abc", ""}) == {str(n) for n in range(0, 101)}

    def test_expand_always_contains_small_integers(self):
        # 0~100 的整数近似是无条件加入的（用于「5 日 / 20 日」这类窗口数）
        assert {"0", "5", "20", "100"} <= _lint_drafts.expand(set())


@pytest.mark.unit
class TestRoleForbidden:
    """角色隔离：牛熊互斥、分析师不读研究与风控稿。"""

    def test_bull_cannot_read_bear(self):
        out = _role_prompt._forbidden("bull", Path("/d"))
        assert out == [Path("/d") / "2_research" / "bear.md"]

    def test_bear_cannot_read_bull(self):
        out = _role_prompt._forbidden("bear", Path("/d"))
        assert out == [Path("/d") / "2_research" / "bull.md"]

    def test_analyst_cannot_read_research_or_trading(self):
        out = _role_prompt._forbidden("market", Path("/d"))
        names = {p.name for p in out}
        assert {"bull.md", "bear.md", "manager.md", "trader.md"} <= names
        assert any(p.name == "portfolio_manager.md" for p in out)

    def test_risk_seats_can_read_everything(self):
        for role in ("aggressive", "conservative", "neutral"):
            assert _role_prompt._forbidden(role, Path("/d")) == []

    def test_manager_and_trader_have_no_restriction(self):
        # 研究经理/交易员读全部前置稿；若将来要限制，必须显式改这里并补测试
        for role in ("manager", "trader"):
            assert _role_prompt._forbidden(role, Path("/d")) == []


@pytest.mark.unit
class TestRoleWhitelistPriorRound:
    """前轮稿件必须进白名单（2026-10-23 修）。

    背景：此前 `_readable()` 对所有角色返回同一份固定清单，manager / trader / 三风控 / PM
    的提示词写着「评判辩论」，白名单里却没有 bull/bear/trader —— 角色被要求评判自己读不到的东西。
    """

    def _seed(self, tmp_path):
        (tmp_path / "0_brief.md").write_text("x", encoding="utf-8")
        for rel in ("1_analysts", "2_research", "3_trading", "4_risk"):
            (tmp_path / rel).mkdir(exist_ok=True)
        for rel in ("1_analysts/market.md", "2_research/bull.md", "2_research/bear.md",
                    "2_research/manager.md", "3_trading/trader.md",
                    "4_risk/aggressive.md", "4_risk/conservative.md", "4_risk/neutral.md"):
            (tmp_path / rel).write_text("x", encoding="utf-8")
        return tmp_path

    def _names(self, draft, role):
        return {p.name for p in _role_prompt._readable("T", "2026-01-01", draft, role)}

    def test_manager_sees_both_debate_drafts(self, tmp_path):
        d = self._seed(tmp_path)
        assert {"bull.md", "bear.md"} <= self._names(d, "manager")

    def test_trader_sees_analysts_and_manager(self, tmp_path):
        d = self._seed(tmp_path)
        got = self._names(d, "trader")
        assert {"market.md", "manager.md"} <= got

    def test_risk_seats_see_trader(self, tmp_path):
        d = self._seed(tmp_path)
        for role in ("aggressive", "conservative", "neutral"):
            assert "trader.md" in self._names(d, role), role

    def test_portfolio_manager_sees_all_prior_rounds(self, tmp_path):
        d = self._seed(tmp_path)
        got = self._names(d, "portfolio_manager")
        assert {"market.md", "bull.md", "bear.md", "manager.md",
                "trader.md", "aggressive.md", "conservative.md", "neutral.md"} <= got

    def test_analysts_do_not_get_research_drafts(self, tmp_path):
        d = self._seed(tmp_path)
        for role in ("market", "fundamentals", "news", "sentiment"):
            assert not ({"bull.md", "bear.md", "trader.md"} & self._names(d, role)), role

    def test_bull_bear_do_not_get_analyst_drafts(self, tmp_path):
        # R1 要求两派只从证据出发、互不预判（AGENT_PROTOCOL §3）
        d = self._seed(tmp_path)
        for role in ("bull", "bear"):
            assert "market.md" not in self._names(d, role), role

    def test_missing_prior_files_are_silently_skipped(self, tmp_path):
        # 上一轮尚未写完时生成提示词，缺文件不应报错
        (tmp_path / "0_brief.md").write_text("x", encoding="utf-8")
        got = self._names(tmp_path, "manager")
        assert "0_brief.md" in got
        assert not ({"bull.md", "bear.md"} & got)  # 缺文件只跳过，不抛错

    def test_prior_round_keys_are_valid_roles(self):
        assert set(_role_prompt.PRIOR_ROUND) <= set(_role_prompt.ROLE_FILES)
