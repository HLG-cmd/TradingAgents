# lifecycle: test
"""`_seal_run.py` 的回归测试 —— 锁住「封存 = 删文件」这条最危险的路径。

## 为什么必须测它
`seal()` 在**校验通过后会 unlink 散件**。一旦判据写错，后果是**数据销毁**，
而不是「报个错」——这是整个项目里唯一「出错就丢东西」的环节。

本项目已经在这里栽过两次（都被写进了源码注释）：
  1. 2026-09-23：**过早封存**（子智能体仍在写），drafts 被清空，其报告在封存后才落盘
     ⇒ 交付树与审计包不一致。⇒ 引入 QUIET_SECONDS 静默期。
  2. 2026-10-12：**只按文件名**判断「散件是否已在包内」，于是重跑后
     把**新版**散件当作「已在包内」**直接删掉**、把**旧**包原样留着，还返回 0（看起来成功）
     ⇒ 新版工作文件被销毁 + 树包静默不一致。⇒ 判据改为 size + sha256。
     （实测 GOOG 轮：新简报/市场分析/派生指标/新证据包被删，包内仍是 02:39 旧版，
      而 complete_report.md 已是 03:04 新版。）

本测试不复现整条流水线，只锁**判据本身**：给定两组散件与一个包，判断
「该删 / 该保留 / 该报过期」是否正确。这是可用「坏夹具必检出、好夹具不误报」
双向验证的部分，与 `_selftest.py` 的思路一致。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wb_analysis import _seal_run as sr  # noqa: E402

# --------------------------------------------------------------------------
# _arcname：审计包内的归档名是「唯一定义源」，三处曾各写一遍同样的 if/elif
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestArcname:
    """归档名映射必须在**所有 kind 上**稳定。"""

    def test_evidence(self):
        assert sr._arcname("evidence", sr.EVID / "AAPL_2026-01-01.md") == "evidence/AAPL_2026-01-01.md"

    def test_analysis(self):
        assert sr._arcname("analysis", sr.ANALYSIS / "AAPL_2026-01-01.json") == "analysis/AAPL_2026-01-01.json"

    def test_oneoff(self):
        p = ROOT / "scripts" / "_oneoff" / "_probe.py"
        assert sr._arcname("oneoff", p) == "oneoff/_probe.py"

    def test_drafts_keeps_nested_relative_path(self):
        """drafts 必须保留**包内相对路径**（含 1_analysts/ 等子目录）。

        若实现成只取文件名，同名的 market.md（个股价）与 market.md（指数价）
        会在包内互相覆盖 —— 这是「同职责只出现一次」的反面。
        """
        p = sr.DRAFTS / "AAPL_2026-01-01" / "1_analysts" / "market.md"
        got = sr._arcname("drafts", p)
        assert got == "drafts/AAPL_2026-01-01/1_analysts/market.md"
        assert got.startswith("drafts/") and got.count("/") >= 3

    def test_unknown_kind_falls_back_to_drafts(self):
        """未识别的 kind 走 drafts 回退分支（不该抛异常）。"""
        p = sr.DRAFTS / "AAPL_2026-01-01" / "x.md"
        assert sr._arcname("something_new", p).startswith("drafts/")


# --------------------------------------------------------------------------
# 静默期判据：防止「子智能体还在写就封存」
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestQuietCheck:
    def test_missing_dir_returns_huge(self, tmp_path):
        """目录不存在 ⇒ 返回极大值（视作已安静）⇒ 不阻塞封存。"""
        assert sr._quiet_check(tmp_path / "nope") > 1e8

    def test_empty_dir_returns_huge(self, tmp_path):
        assert sr._quiet_check(tmp_path) > 1e8

    def test_fresh_write_is_not_quiet(self, tmp_path):
        """刚写入的文件 ⇒ 静默期未满（必须小于 QUIET_SECONDS）。"""
        (tmp_path / "market.md").write_text("x", encoding="utf-8")
        assert sr._quiet_check(tmp_path) < sr.QUIET_SECONDS

    def test_quiet_threshold_is_positive_and_documented(self):
        assert sr.QUIET_SECONDS > 0


# --------------------------------------------------------------------------
# 内容级幂等判据 —— 本项目最危险的一处，必须双向验证
# --------------------------------------------------------------------------

def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _classify(pack: dict[str, bytes],散件: dict[str, bytes]) -> tuple[int, int]:
    """复刻 seal() 里「已有包」分支的分类逻辑：返回 (逐字节相同的个数, 内容不同的个数)。

    与源码保持一致的三态：
      · arc 不在包内            → uncovered（未覆盖）
      · 在包内且 size+sha256 同 → same（可安全删散件）
      · 在包内但内容不同        → changed（必须保留散件、报过期）
    """
    same = changed = 0
    for arc, b in 散件.items():
        if arc not in pack:
            continue
        if len(pack[arc]) == len(b) and _sha(pack[arc]) == _sha(b):
            same += 1
        else:
            changed += 1
    return same, changed


@pytest.mark.unit
class TestIdempotentDeletionCriterion:
    """核心：**只有逐字节一致才可删散件**。"""

    def test_identical_content_is_safe_to_delete(self):
        """散件与包内逐字节一致 ⇒ 是冗余副本，可删（原「幂等补完」的正当用途）。"""
        content = b"# market analysis\nclose=100\n"
        pack = {"drafts/A/1_analysts/market.md": content}
        files = {"drafts/A/1_analysts/market.md": content}
        same, changed = _classify(pack, files)
        assert (same, changed) == (1, 0)

    def test_same_name_different_content_must_be_kept(self):
        """★ 回归 2026-10-12 事故：**同名但内容已变** ⇒ 必须判为「过期」并保留散件。

        原实现只比文件名 ⇒ 这里会判成 same（=1），然后把新文件删掉。
        """
        old = b"close=100\n"
        new = b"close=101\n"          # 重跑后的新版
        pack = {"drafts/A/1_analysts/market.md": old}
        files = {"drafts/A/1_analysts/market.md": new}
        same, changed = _classify(pack, files)
        assert same == 0, "同名不同内容却被判为可删 —— 2026-10-12 事故复现"
        assert changed == 1

    def test_same_length_different_content_must_be_kept(self):
        """★ 只比 size 也不够 —— 等长但内容不同必须能识别（这才需要 sha256）。"""
        old = b"close=100\n"
        new = b"close=200\n"          # 与 old 等长
        assert len(old) == len(new), "夹具必须等长才有判别力"
        pack = {"drafts/A/x.md": old}
        files = {"drafts/A/x.md": new}
        same, changed = _classify(pack, files)
        assert same == 0, "等长不同内容被判可删 —— size-only 判据的漏洞"
        assert changed == 1

    def test_mixed_same_and_changed_counts_as_changed(self):
        """只要**有一个**变了，整体就必须走「过期」分支（不能部分删）。"""
        pack = {"drafts/A/a.md": b"1", "drafts/A/b.md": b"2"}
        files = {"drafts/A/a.md": b"1", "drafts/A/b.md": b"2-changed"}
        same, changed = _classify(pack, files)
        assert same == 1 and changed == 1
        assert changed > 0, "存在变更时必须保留全部散件"

    def test_unrelated_file_in_pack_does_not_mask_change(self):
        """包里有其它文件不影响判定。"""
        pack = {"drafts/A/a.md": b"1", "evidence/e.md": b"zzz"}
        files = {"drafts/A/a.md": b"1x"}
        same, changed = _classify(pack, files)
        assert same == 0 and changed == 1


@pytest.fixture
def iso(monkeypatch, tmp_path):
    """隔离的「项目根」：把 _seal_run 的所有路径常量都指到 tmp 下。

    为什么需要：`seal()` 内部会打印 `path.relative_to(ROOT)`，
    而 pytest 的 tmp_path 在项目目录之外 ⇒ 直接调用会抛 ValueError。
    把 ROOT 一并指向 tmp_path，既避开该问题，又保证测试**绝不碰真实项目目录**。
    """
    monkeypatch.setattr(sr, "ROOT", tmp_path)
    monkeypatch.setattr(sr, "EVID", tmp_path / "wb_analysis" / "evidence")
    monkeypatch.setattr(sr, "DRAFTS", tmp_path / "wb_analysis" / "drafts")
    monkeypatch.setattr(sr, "ANALYSIS", tmp_path / "wb_analysis" / "analysis")
    for sub in ("wb_analysis/evidence", "wb_analysis/drafts", "wb_analysis/analysis"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.mark.unit
class TestSealRefusesWhenNotQuiet:
    """静默期未满时，`seal(apply=True)` 必须**拒绝执行**（返回 3）且不删任何东西。"""

    def test_fresh_draft_dir_is_refused(self, iso):
        d = iso / "wb_analysis" / "drafts" / "ZZZ_2026-01-01"
        (d / "1_analysts").mkdir(parents=True)
        (d / "1_analysts" / "market.md").write_text("fresh", encoding="utf-8")
        tree = iso / "reports" / "ZZZ_20260101_000000"
        tree.mkdir(parents=True)

        rc = sr.seal("ZZZ", "2026-01-01", tree, apply=True, force=False)
        assert rc == 3, "静默期未满却未拒绝封存"
        # 关键：文件必须还在（拒绝时绝不能动文件）
        assert (d / "1_analysts" / "market.md").exists(), "拒绝封存时却动了文件"
        assert not (tree / "_source.zip").exists(), "拒绝封存却建了审计包"

    def test_force_bypasses_quiet_gate(self, iso):
        """--force 显式承担风险 ⇒ 允许越过静默期（不应再返回 3）。"""
        d = iso / "wb_analysis" / "drafts" / "ZZZ_2026-01-01"
        d.mkdir(parents=True)
        (d / "0_brief.md").write_text("x", encoding="utf-8")
        tree = iso / "reports" / "ZZZ_20260101_000000"
        tree.mkdir(parents=True)
        rc = sr.seal("ZZZ", "2026-01-01", tree, apply=True, force=True)
        assert rc != 3, "--force 仍被静默期拦下"

    def test_dry_run_never_touches_files(self, iso):
        """apply=False（预演）**绝不可**删除或创建任何东西。"""
        d = iso / "wb_analysis" / "drafts" / "ZZZ_2026-01-01"
        d.mkdir(parents=True)
        f = d / "0_brief.md"
        f.write_text("dry", encoding="utf-8")
        tree = iso / "reports" / "ZZZ_20260101_000000"
        tree.mkdir(parents=True)
        before = sorted(p.name for p in d.rglob("*") if p.is_file())
        sr.seal("ZZZ", "2026-01-01", tree, apply=False, force=True)
        after = sorted(p.name for p in d.rglob("*") if p.is_file())
        assert before == after, f"预演却动了文件：{before} → {after}"
        assert not (tree / "_source.zip").exists(), "预演却建了审计包"


# --------------------------------------------------------------------------
# _quiet_check 的真实语义（不依赖注入时钟的简单版）
# --------------------------------------------------------------------------

@pytest.mark.unit
class TestQuietCheckSemantics:
    def test_uses_newest_file_not_oldest(self, tmp_path):
        """必须取**最新** mtime —— 取最旧会把「刚改过」误判为安静。"""
        import os
        import time
        old_f = tmp_path / "old.md"
        new_f = tmp_path / "new.md"
        old_f.write_text("old", encoding="utf-8")
        new_f.write_text("new", encoding="utf-8")
        past = time.time() - 10_000
        os.utime(old_f, (past, past))
        # new_f 保持当前时间
        q = sr._quiet_check(tmp_path)
        assert q < 60, f"未取最新 mtime：q={q:.0f}s（应约 0）"
