"""wb_analysis/_check_freshness.py 的单元测试。

验证流水线新鲜度校验：骨架判定、证据包/派生/简报/角色文件单调性时序约束。
"""
from __future__ import annotations

import os
import time

from wb_analysis import _check_freshness as cf


def test_is_stub_detects_tiny_files(tmp_path):
    p = tmp_path / "tiny.md"
    p.write_text("short", encoding="utf-8")
    reason = cf._is_stub(p)
    assert reason is not None
    assert "疑似占位骨架" in reason


def test_is_stub_detects_stub_markers_in_small_files(tmp_path):
    p = tmp_path / "stub.md"
    # 超过 200 字节，但小于 2000 字节且包含占位标记
    content = "A" * 300 + "\nFINAL TRANSACTION PROPOSAL: **HOLD**\n"
    p.write_text(content, encoding="utf-8")
    reason = cf._is_stub(p)
    assert reason is not None
    assert "含预填骨架标记" in reason


def test_is_stub_returns_none_for_normal_large_files(tmp_path):
    p = tmp_path / "normal.md"
    # 超过 2000 字节且真实的角色研究报告
    content = ("# Role Report\n\nDetailed analysis...\n" + "Body paragraph.\n" * 150)
    p.write_text(content, encoding="utf-8")
    assert cf._is_stub(p) is None


def test_fmt_formats_epoch_timestamp():
    t = 1700000000.0
    res = cf._fmt(t)
    assert len(res) == 14  # mm-dd HH:MM:SS


def test_main_fails_on_missing_draft_dir(monkeypatch):
    monkeypatch.setattr(cf.sys, "argv", ["_check_freshness.py", "nonexistent_dir"])
    assert cf.main() == 1


def test_freshness_pipeline_end_to_end(tmp_path, monkeypatch):
    # 准备目录结构
    ev_dir = tmp_path / "wb_analysis" / "evidence"
    ev_dir.mkdir(parents=True)
    monkeypatch.setattr(cf, "EVID", ev_dir)

    draft_dir = tmp_path / "drafts" / "NDX_2026-09-17"
    draft_dir.mkdir(parents=True)

    base_t = time.time() - 1000

    # 1. 证据包缺失时失败
    monkeypatch.setattr(cf.sys, "argv", ["_check_freshness.py", str(draft_dir)])
    assert cf.main() == 1

    # 写入证据包
    ev_md = ev_dir / "NDX_2026-09-17.md"
    ev_md.write_text("# Evidence", encoding="utf-8")
    os.utime(ev_md, (base_t, base_t))

    # 2. 缺失派生或简报时失败
    assert cf.main() == 1

    derived = draft_dir / "0_derived.md"
    derived.write_text("# Derived", encoding="utf-8")
    os.utime(derived, (base_t + 10, base_t + 10))

    brief = draft_dir / "0_brief.md"
    brief.write_text("# Brief", encoding="utf-8")
    os.utime(brief, (base_t + 20, base_t + 20))

    # 写入 12 角色文件（大于 2000 字节，时间晚于 brief）
    for sub in cf.ROLE_DIRS:
        sd = draft_dir / sub
        sd.mkdir(parents=True)
        f = sd / "test.md"
        f.write_text("# Test Role\n" + "Details\n" * 200, encoding="utf-8")
        os.utime(f, (base_t + 30, base_t + 30))

    # 3. 正常顺序：证据包 <= 派生指标 <= 简报 <= 角色文件
    assert cf.main() == 0

    # 4. 时间倒挂：若派生指标早于证据包（上游重采但派生未重跑）
    os.utime(ev_md, (base_t + 50, base_t + 50))
    assert cf.main() == 1
