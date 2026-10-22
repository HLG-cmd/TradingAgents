"""quant/cleanup_cache.py 的单元测试。

测试核心契约：
- _dir_size 计算文件数量与字节大小，对不存在的路径返回 (0, 0)
- _remove_dir_contents 逐文件自深到浅安全清理，返回 (removed, freed)
- 命令行参数解析：--status、--keep-edgar、--keep-prices、--yes
"""
from __future__ import annotations

import quant.cleanup_cache as cc


def test_dir_size_non_existent(tmp_path):
    not_here = tmp_path / "does_not_exist"
    n, s = cc._dir_size(not_here)
    assert n == 0
    assert s == 0


def test_dir_size_with_files(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    f1 = tmp_path / "a.txt"
    f2 = sub / "b.txt"
    f1.write_text("hello", encoding="utf-8")
    f2.write_text("world!", encoding="utf-8")

    n, s = cc._dir_size(tmp_path)
    assert n == 2
    assert s == len(b"hello") + len(b"world!")


def test_remove_dir_contents_non_existent(tmp_path):
    not_here = tmp_path / "does_not_exist"
    removed, freed = cc._remove_dir_contents(not_here)
    assert removed == 0
    assert freed == 0


def test_remove_dir_contents_cleans_nested_dirs(tmp_path):
    d1 = tmp_path / "dir1"
    d2 = d1 / "dir2"
    d2.mkdir(parents=True)
    f1 = d1 / "f1.bin"
    f2 = d2 / "f2.bin"
    f1.write_bytes(b"12345")
    f2.write_bytes(b"67890abc")

    removed, freed = cc._remove_dir_contents(tmp_path)
    assert removed == 2
    assert freed == 5 + 8
    # 目录内部文件已被删除，子目录已自深到浅被 rmdir
    assert not f1.exists()
    assert not f2.exists()
    assert not d2.exists()
    assert not d1.exists()


def test_show_status_runs_without_error(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "BASE", tmp_path)
    monkeypatch.setattr(cc, "CACHE_DIR", tmp_path / "cache")
    (tmp_path / "edgar").mkdir()
    (tmp_path / "edgar" / "sample.json").write_text("{}", encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "constituents_sp500.json").write_text("{}", encoding="utf-8")

    cc.show_status()
    out = capsys.readouterr().out
    assert "缓存占用" in out
    assert "edgar" in out
    assert "cache/constituents" in out
    assert "合计" in out


def test_main_status_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cleanup_cache.py", "--status"])
    rc = cc.main()
    assert rc == 0


def test_main_yes_cleans_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "BASE", tmp_path)
    monkeypatch.setattr(cc, "CACHE_DIR", tmp_path / "cache")
    edgar = tmp_path / "edgar"
    prices = tmp_path / "prices"
    cache = tmp_path / "cache"
    edgar.mkdir()
    prices.mkdir()
    cache.mkdir()
    (edgar / "fact.json").write_text("1", encoding="utf-8")
    (prices / "AAPL.csv").write_text("1", encoding="utf-8")
    (cache / "test.json").write_text("1", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["cleanup_cache.py", "--yes"])
    rc = cc.main()
    assert rc == 0
    assert not (edgar / "fact.json").exists()
    assert not (prices / "AAPL.csv").exists()
    assert not (cache / "test.json").exists()


def test_main_keep_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "BASE", tmp_path)
    monkeypatch.setattr(cc, "CACHE_DIR", tmp_path / "cache")
    edgar = tmp_path / "edgar"
    prices = tmp_path / "prices"
    cache = tmp_path / "cache"
    edgar.mkdir()
    prices.mkdir()
    cache.mkdir()
    (edgar / "fact.json").write_text("1", encoding="utf-8")
    (prices / "AAPL.csv").write_text("1", encoding="utf-8")
    (cache / "test.json").write_text("1", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["cleanup_cache.py", "--yes", "--keep-edgar", "--keep-prices"])
    rc = cc.main()
    assert rc == 0
    # edgar 和 prices 应该保留
    assert (edgar / "fact.json").exists()
    assert (prices / "AAPL.csv").exists()
    # 只有 cache 里的被清
    assert not (cache / "test.json").exists()
