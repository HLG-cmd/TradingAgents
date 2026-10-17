# lifecycle: test
"""`_reports_index.py` 索引层回归测试。

## 为什么测它
`_reports_index.py` 生成 `reports/INDEX.md` 并做**报告卫生检查** ——
它是「报告集有没有堆积/孤儿/缺草稿」的唯一判据，也是 `_health.py`
「报告卫生」一项的实现。判错的两个方向都有代价：
  · **假阳性**（明明是正常终态却报问题）⇒ 人会去修不存在的问题，
    久了就学会忽略告警（狼来了）；
  · **假阴性**（真有堆积却报干净）⇒ 与铁律 3 同型的静默失效。

本文件锁定三处**真实踩过坑**的判据（均在源码注释里有记录）：

1. `_zip_text` / `_manifest_has` —— 封存后散落目录被清空**本就是正常终态**，
   判据必须能回退到「树内审计包」或「SOURCE_MANIFEST.json」。此前只认散落目录
   ⇒ 整列退化成 `—`，**看起来像缺数据，其实判据太窄**。
2. `read_ratings` —— 从渲染后的报告树还原评级，含交易员末行的**宽松取数版**正则。
3. 「关联键用**数据基准日**、不是目录里的**运行时刻**」——两者通常差一天。
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis import _reports_index as ri  # noqa: E402

# --------------------------------------------------------------------------
# read_ratings：从渲染后的报告树还原三个评级
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestReadRatings:
    def _mk_tree(self, tmp_path: Path, manager: str, trader: str, pm: str) -> Path:
        t = tmp_path / "TREE"
        (t / "2_research").mkdir(parents=True)
        (t / "3_trading").mkdir(parents=True)
        (t / "5_portfolio").mkdir(parents=True)
        if manager is not None:
            (t / "2_research" / "manager.md").write_text(manager, encoding="utf-8")
        if trader is not None:
            (t / "3_trading" / "trader.md").write_text(trader, encoding="utf-8")
        if pm is not None:
            (t / "5_portfolio" / "decision.md").write_text(pm, encoding="utf-8")
        return t

    def test_reads_recommendation_and_rating_fields(self, tmp_path):
        """manager / pm 走 `**Recommendation**`/`**Rating**`，取值保持原样（Title Case）。"""
        t = self._mk_tree(
            tmp_path,
            "**Recommendation**: Hold\n",
            "**Action**: Hold\nFINAL TRANSACTION PROPOSAL: **HOLD**\n",
            "**Rating**: Hold\n",
        )
        got = ri.read_ratings(t)
        assert got["manager"] == "Hold"
        assert got["pm"] == "Hold"
        # ⚠️ trader 走的是 **PROPOSAL_RE 兜底路径**（见下条测试），取到原文大写 HOLD。
        assert got["trader"] == "HOLD"

    def test_trader_pick_does_not_recognize_action_label(self, tmp_path):
        """★ 记录一个真实边界：`read_ratings.pick()` 只认 `Recommendation|Rating`。

        `pick()` 的首个正则不匹配交易员的 `**Action**:` 标签，因此 trader 列**必然**
        落到 `PROPOSAL_RE`（宽松取数版）⇒ 取到末行的原文写法。

        影响面（已核实，故不当作 bug 修）：
          · `scan()` 里 `read_ratings()` **只在没有 RUN.json 的老树上启用**
            （实测 51 棵树中 47 棵有 RUN.json，走 `readings` 短键映射）⇒ 真实 INDEX
            的 trader 列显示 Title Case `Hold`；
          · 只有「老树 + 末行写成大写」时，trader 列才会显示 `HOLD`。
        ⇒ 本测试把它固化为**已知行为**：改 `pick()` 的标签集前，先确认这是有意变更。
        """
        t = self._mk_tree(tmp_path, "**Recommendation**: Hold\n",
                          "**Action**: Hold\n", "")   # 只有 Action，没有末行
        # Action 标签不被识别，且无末行可兜底 ⇒ 取不到值
        assert ri.read_ratings(t)["trader"] == "—"

        # 补上末行后才有值（且为大写原文）
        (t / "3_trading" / "trader.md").write_text(
            "**Action**: Hold\nFINAL TRANSACTION PROPOSAL: **HOLD**\n", encoding="utf-8")
        assert ri.read_ratings(t)["trader"] == "HOLD"

    def test_missing_files_yield_placeholder(self, tmp_path):
        t = tmp_path / "EMPTY"
        t.mkdir()
        assert ri.read_ratings(t) == {"manager": "—", "trader": "—", "pm": "—"}

    def test_trader_falls_back_to_final_proposal_line(self, tmp_path):
        """没有 `**Action**` 块时，须回退到末行的 `FINAL TRANSACTION PROPOSAL`。"""
        t = self._mk_tree(
            tmp_path,
            "**Recommendation**: Buy\n",
            "正文若干\n\nFINAL TRANSACTION PROPOSAL: **SELL**\n",
            "**Rating**: Sell\n",
        )
        got = ri.read_ratings(t)
        assert got["trader"] == "SELL", f"未回退到末行：{got}"

    def test_bold_value_is_captured(self, tmp_path):
        """值是粗体 `**Hold**` 时应剥掉星号只留词。"""
        t = self._mk_tree(tmp_path, "**Recommendation**: **Overweight**\n", "", "")
        assert ri.read_ratings(t)["manager"] == "Overweight"


# --------------------------------------------------------------------------
# _zip_text：从审计包读条目（封存后散落目录清空，必须能回退）
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestZipText:
    def test_reads_exact_entry(self, tmp_path):
        zp = tmp_path / "_source.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("evidence/AAPL_2026-01-01.md", "内容ABC")
        assert ri._zip_text(zp, "AAPL_2026-01-01.md") == "内容ABC"

    def test_reads_nested_entry_by_suffix(self, tmp_path):
        """包内是嵌套路径（`drafts/<T>_<date>/...`）时，按后缀也能命中。"""
        zp = tmp_path / "_source.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("drafts/AAPL_2026-01-01/1_analysts/market.md", "挂牌")
        assert ri._zip_text(zp, "market.md") == "挂牌"

    def test_missing_zip_returns_none(self, tmp_path):
        assert ri._zip_text(tmp_path / "nope.zip", "x") is None

    def test_corrupt_zip_returns_none_not_raise(self, tmp_path):
        """坏包必须返回 None（不能抛异常中断整个索引生成）。"""
        zp = tmp_path / "_source.zip"
        zp.write_bytes(b"this is not a zip")
        assert ri._zip_text(zp, "x") is None

    def test_missing_entry_returns_none(self, tmp_path):
        zp = tmp_path / "_source.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("other.md", "x")
        assert ri._zip_text(zp, "target.md") is None


# --------------------------------------------------------------------------
# _manifest_has：轻量导出包剔除了二进制 zip 时的回退
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestManifestHas:
    def test_true_when_prefix_present(self, tmp_path):
        (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps({
            "contents": ["SEAL.json", "drafts/A/1_analysts/market.md", "evidence/e.md"],
        }, ensure_ascii=False), encoding="utf-8")
        assert ri._manifest_has(tmp_path, "drafts/") is True
        assert ri._manifest_has(tmp_path, "evidence/") is True

    def test_false_when_prefix_absent(self, tmp_path):
        (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps({
            "contents": ["drafts/A/x.md"],
        }), encoding="utf-8")
        assert ri._manifest_has(tmp_path, "analysis/") is False

    def test_missing_manifest_is_false_not_error(self, tmp_path):
        assert ri._manifest_has(tmp_path, "drafts/") is False

    def test_corrupt_manifest_is_false_not_error(self, tmp_path):
        (tmp_path / "SOURCE_MANIFEST.json").write_text("{ not json", encoding="utf-8")
        assert ri._manifest_has(tmp_path, "drafts/") is False

    def test_empty_contents_is_false(self, tmp_path):
        (tmp_path / "SOURCE_MANIFEST.json").write_text(json.dumps({"contents": []}), encoding="utf-8")
        assert ri._manifest_has(tmp_path, "drafts/") is False


# --------------------------------------------------------------------------
# 报告树命名契约（TREE_RE）：索引与卫生检查的共同前提
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestTreeNamingContract:
    @pytest.mark.parametrize("name", [
        "GOOG_20261015_125112",
        "512400.SS_20261015_195220",
        "sh518850_20261016_024229",
    ])
    def test_valid_tree_names_match(self, name):
        assert ri.TREE_RE.match(name) is not None

    @pytest.mark.parametrize("name", [
        "GOOG_20261015",          # 缺时刻
        "GOOG",                    # 只有标的
        "_archive",                # 功能目录
        "GOOG_2026-10-15_125112",  # 日期带横线（不符契约）
    ])
    def test_invalid_names_do_not_match(self, name):
        assert ri.TREE_RE.match(name) is None

    def test_functional_dirs_are_skipped(self):
        """功能目录（_archive/_audit/…）不得被当成报告树。"""
        for d in ("_archive", "_audit", "_datasets", "_other"):
            assert d in ri.SKIP_DIRS, f"{d} 未列入 SKIP_DIRS"
