"""证据包只读清单（`_integrity.py`）与辩论独立性判据（`_precheck._num_overlap`）的单测。

为什么测这两个：

* **只读清单**是门禁链上唯一一处「防止角色回改证据包」的防护。它失效（恒 PASS）时，
  角色把数字改成自己想引用的值，`_lint_drafts` 的数字溯源反而会以被改后的证据包为基准
  ⇒ 自我印证，编造数字变成「可溯源」。必须双向验证：**没改要 PASS，改了必须 FAIL**。
* **辩论独立性**把 AGENT_PROTOCOL §4 的「>70% 判拆分失败」从人眼判断变成可计算的数；
  算法错（例如只比整数、忽略小数）会让同质化的牛熊稿蒙混过关。
"""
from __future__ import annotations

import json

import pytest

from wb_analysis._integrity import manifest_path, verify, write_manifest
from wb_analysis._precheck import _num_overlap


@pytest.mark.unit
class TestIntegrityManifest:
    def _ev(self, tmp_path, text="# 证据包\n\nlatest_close: 320.76\n"):
        p = tmp_path / "T_2026-01-01.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_manifest_is_written_next_to_evidence(self, tmp_path):
        ev = self._ev(tmp_path)
        mp = write_manifest(ev)
        assert mp == manifest_path(ev)
        assert mp.name == "T_2026-01-01.md.integrity.json"   # 不吞掉 .md 后缀
        rec = json.loads(mp.read_text(encoding="utf-8"))
        assert rec["file"] == ev.name and len(rec["sha256"]) == 64

    def test_unchanged_passes(self, tmp_path):
        ev = self._ev(tmp_path)
        write_manifest(ev)
        ok, why = verify(ev)
        assert ok and "一致" in why

    def test_single_byte_change_fails(self, tmp_path):
        ev = self._ev(tmp_path)
        write_manifest(ev)
        ev.write_text(ev.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        ok, why = verify(ev)
        assert not ok and "被修改" in why

    def test_number_tampering_fails(self, tmp_path):
        # 最危险的形态：把证据包里的数字改掉，让编造的引用变成"可溯源"
        ev = self._ev(tmp_path, "# 证据包\n\nlatest_close: 320.76\n")
        write_manifest(ev)
        ev.write_text("# 证据包\n\nlatest_close: 999.99\n", encoding="utf-8")
        assert verify(ev)[0] is False

    def test_missing_manifest_is_not_a_failure(self, tmp_path):
        # 旧证据包/测试夹具没有清单：不阻断，但调用方会降级成 WARN
        ok, why = verify(self._ev(tmp_path))
        assert ok and "无完整性清单" in why

    def test_corrupt_manifest_fails_closed(self, tmp_path):
        ev = self._ev(tmp_path)
        manifest_path(ev).write_text("{not json", encoding="utf-8")
        ok, why = verify(ev)
        assert not ok and "不可解析" in why


@pytest.mark.unit
class TestDebateIndependence:
    def _draft(self, tmp_path, name, text):
        p = tmp_path / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_identical_drafts_hit_100(self, tmp_path):
        body = "PE 41.05，FCF 73.32，RSI 32.80，MACD -2.46，目标 339.13"
        a = self._draft(tmp_path, "bull.md", body)
        b = self._draft(tmp_path, "bear.md", body)
        assert _num_overlap(a, b) == pytest.approx(100.0)

    def test_disjoint_drafts_near_zero(self, tmp_path):
        a = self._draft(tmp_path, "bull.md", "营收 402.83，毛利 240.31，研发 61.09")
        b = self._draft(tmp_path, "bear.md", "PE 41.05，PB 6.28，ATR 8.74")
        assert _num_overlap(a, b) == pytest.approx(0.0)

    def test_partial_overlap_between_0_and_100(self, tmp_path):
        a = self._draft(tmp_path, "bull.md", "PE 41.05，FCF 73.32，研发 61.09")
        b = self._draft(tmp_path, "bear.md", "PE 41.05，ATR 8.74，PB 6.28")
        v = _num_overlap(a, b)
        assert v is not None and 0 < v < 100

    def test_no_numbers_returns_none(self, tmp_path):
        a = self._draft(tmp_path, "bull.md", "看多，但没有数字")
        b = self._draft(tmp_path, "bear.md", "看空，也没有数字")
        assert _num_overlap(a, b) is None
